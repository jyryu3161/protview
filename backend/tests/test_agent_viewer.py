"""M8 viewer intent privacy, exact scene, lifecycle and owned transport tests.

All model replies here are labeled injected fixtures. Real provider QA is a separate gate.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import mw.api.app as api_module
from mw.egress.gate import EgressGate
from mw.egress.viewer import body_for, parse_answers, request_viewer
from mw.viewer_intents import (
    QUESTION_VERSION,
    EgressViewerIntentV1,
    ViewerError,
    _catalog_projection,
    _session,
    compile_answers,
    create_session,
    intent_live,
    projected_state,
    request_intent,
    set_online,
)
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures"


def _id() -> str:
    return str(uuid.uuid4())


def fixture_reply(*, disposition="apply", representation="surface", selection="keep", camera="reset",
                  model="typesafe/jev-1.13-20260917", usage=None):
    return {"model": model, "answers": {name: {"type": "choice", "choice": value} for name, value in {
        "disposition": disposition, "representation": representation,
        "selection": selection, "camera": camera}.items()},
        "usage": usage or {"input_tokens": 200, "output_tokens": 30, "cost": 0.002}}


def setup_api(monkeypatch, tmp_path, *, dry_run=False):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app)
    response = client.post("/runs", json={"dry_run": dry_run})
    assert response.status_code == 201
    rid = response.json()["run_id"]
    return client, rid


def loaded_scene(client, rid, *, fixture="mini_complex.pdb", model_index=0, client_id=None,
                 generation=1, scope_chain_auth=None):
    source = FIX / fixture
    upload = client.post(f"/runs/{rid}/uploads?filename={source.name}", content=source.read_bytes())
    assert upload.status_code == 201, upload.text
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
        "args": {"source": upload.json()["upload_id"], "model_index": model_index}})
    assert loaded.status_code == 200, loaded.text
    handle = loaded.json()["handle"]["handle"]
    payload = {"client_instance_id": client_id or _id(), "scene_generation": generation,
               "structure_handle": handle}
    if scope_chain_auth is not None:
        payload["scope_chain_auth"] = scope_chain_auth
    response = client.post(f"/runs/{rid}/viewer/sessions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def intent_request(scene, prompt, request_id=None):
    return {"client_instance_id": scene["client_instance_id"],
            "viewer_session_id": scene["viewer_session_id"],
            "scene_generation": scene["scene_generation"],
            "request_id": request_id or _id(), "prompt": prompt}


def injected_gate(monkeypatch, handler, *, credential=None):
    calls = {"credentials": 0, "requests": 0}
    def resolver():
        calls["credentials"] += 1
        return credential if credential is not None else "fixture-only-key"
    def counting(request):
        calls["requests"] += 1
        return handler(request)
    monkeypatch.setattr(api_module, "VIEWER_GATE",
                        EgressGate(transport=httpx.MockTransport(counting), credential_resolver=resolver))
    return calls


def test_default_offline_and_dry_run_never_touch_transport_or_credential(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    calls = injected_gate(monkeypatch, lambda _: pytest.fail("offline transport invoked"))
    local = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "/representation surface"))
    assert local.status_code == 201
    assert local.json()["source"] == "local_command" and local.json()["status"] == "planned"
    assert local.json()["commands"][0]["value"] == "surface"
    natural = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "Show surface"))
    assert natural.json()["status"] == "unsupported"
    assert natural.json()["reason_code"] == "online_not_enabled"
    assert calls == {"credentials": 0, "requests": 0}
    assert client.get(f"/runs/{rid}/viewer/online").json()["mode"] == "local_only"
    dry_client, dry_rid = setup_api(monkeypatch, tmp_path / "dry", dry_run=True)
    dry_scene = loaded_scene(dry_client, dry_rid)
    assert dry_client.post(f"/runs/{dry_rid}/viewer/online", json={"enabled": True}).status_code == 412
    dry = dry_client.post(f"/runs/{dry_rid}/viewer/intents", json=intent_request(dry_scene, "Show surface"))
    assert dry.json()["reason_code"] == "dry_run"
    assert calls == {"credentials": 0, "requests": 0}


def test_local_ack_is_exact_idempotent_and_not_scientific_approval(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    value = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "/zoom in")).json()
    command = value["commands"][0]
    ack = {"command_id": command["command_id"], "status": "applied", "reason_code": None,
           "client_instance_id": scene["client_instance_id"],
           "viewer_session_id": scene["viewer_session_id"], "scene_generation": 1,
           "action_revision": 0}
    wrong = client.post(f"/runs/{rid}/viewer/intents/{value['intent_id']}/ack", json={**ack, "scene_generation": 2})
    assert wrong.status_code == 409
    assert client.post(f"/runs/{rid}/viewer/intents/{value['intent_id']}/ack", json=ack).json()["status"] == "applied"
    assert client.post(f"/runs/{rid}/viewer/intents/{value['intent_id']}/ack", json=ack).json()["status"] == "applied"
    assert client.post(f"/runs/{rid}/viewer/intents/{value['intent_id']}/ack",
                       json={**ack, "status": "failed"}).status_code == 409
    assert client.post(f"/runs/{rid}/viewer/intents/{value['intent_id']}/cancel").status_code == 409
    assert client.get(f"/runs/{rid}/viewer/online").json()["scientific_job_approved"] is False


def test_projection_forbids_unknown_fields_and_never_exports_structure_bytes(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid, fixture="public_1hsg.cif", scope_chain_auth="B")
    assert len(scene["catalog"]) <= 256
    # A normal blank insertion code is absence, not an unsafe identifier.
    assert any(item.get("chain_auth") == "B" and "model_number" in item for item in scene["catalog"])
    run = api_module.RUNS[rid]
    state = projected_state(scene, "Show the surface of target t0001")
    body = json.loads(body_for(state))
    assert body["state"]["selected_target"] is None
    assert set(body["state"]) == {"schema", "prompt", "representation", "selected_target", "scope_complete", "catalog"}
    assert body["model"] == "typesafe/jev-1.13"
    assert body["provider"] == {"data_collection": "deny", "zdr": True, "allow_fallbacks": False}
    assert all(set(target) <= {"alias", "category", "model_number", "chain_auth", "seq_auth", "icode",
                               "chain_label", "seq_label"} for target in body["state"]["catalog"])
    encoded = json.dumps(body)
    assert scene["structure_handle"] not in encoded
    assert "Cartn_x" not in encoded and "MK1" not in encoded and "public_1hsg" not in encoded
    assert len(json.dumps(body).encode()) < 65_536
    with pytest.raises(ValidationError):
        EgressViewerIntentV1.model_validate({**state.wire(), "source_path": "/private/structure.pdb"})
    for prompt in ("", "x" * 513, "abc\x00def", "🙂" * 513):
        with pytest.raises(ValidationError):
            EgressViewerIntentV1.model_validate({**state.wire(), "prompt": prompt})
    assert run.store.meta(scene["structure_handle"])["kind"] == "structure"


def test_selection_question_distinguishes_existing_target_from_requested_clear(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    state = projected_state(scene, "선택을 해제해 주세요")
    state.selected_target = scene["catalog"][0]["alias"]
    body = json.loads(body_for(state))
    selection = body["questions"]["selection"]
    assert body["state"]["selected_target"] == scene["catalog"][0]["alias"]
    assert "existing scene context" in selection["instructions"]
    assert "선택을 해제" in selection["instructions"]
    assert "do not select the current target" in selection["instructions"]
    assert selection["criteria"]["clear"] == "Explicitly remove current selection."
    assert selection["criteria"]["keep"] == "No requested selection change."
    assert "Explicitly requested exact target" in selection["criteria"][scene["catalog"][0]["alias"]]
    assert QUESTION_VERSION == "viewer_questions@2"


def test_unsafe_catalog_identifier_exports_alias_only():
    row = {"category": "polymer", "model_number": 1, "chain_auth": "/private/path.pdb",
           "seq_auth": 25, "icode": "", "chain_label": "A", "seq_label": 25}
    assert _catalog_projection("t0001", row) == {"alias": "t0001", "category": "polymer"}


def test_pinned_fixture_request_settles_usage_and_is_idempotent(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        assert request.url.path == "/api/alpha/decisions"
        return httpx.Response(200, json=fixture_reply())
    calls = injected_gate(monkeypatch, handler)
    assert client.post(f"/runs/{rid}/viewer/online", json={"enabled": True}).json()["scientific_job_approved"] is False
    payload = intent_request(scene, "Show surface and reset camera")
    first = client.post(f"/runs/{rid}/viewer/intents", json=payload)
    assert first.status_code == 201, first.text
    value = first.json()
    assert value["source"] == "jev" and value["status"] == "planned"
    assert [command["axis"] for command in value["commands"]] == ["representation", "camera"]
    assert value["served_model"] == "typesafe/jev-1.13-20260917"
    assert value["question_version"] == QUESTION_VERSION
    assert value["audit_id"]
    assert client.post(f"/runs/{rid}/viewer/intents", json=payload).json()["intent_id"] == value["intent_id"]
    assert calls == {"credentials": 1, "requests": 1}
    assert len(bodies) == 1
    assert bodies[0]["questions"]["selection"]["criteria"]["clear"] == "Explicitly remove current selection."
    assert any(event.get("question_version") == QUESTION_VERSION for event in api_module.RUNS[rid].events.read()
               if event["type"] == "egress")
    assert client.post(f"/runs/{rid}/viewer/intents", json={**payload, "prompt": "different"}).status_code == 409
    budget = client.get(f"/runs/{rid}/budget").json()
    assert budget["expensive_calls"]["used"] == 1
    assert budget["external_tokens"]["used"] == 230
    assert client.get(f"/runs/{rid}/viewer/online").json()["used"] == 1
    api_module.RUNS.clear()
    reopened = client.get(f"/runs/{rid}/viewer/online").json()
    assert reopened["mode"] == "online" and reopened["used"] == 1
    assert client.get(f"/runs/{rid}/viewer/intents/{value['intent_id']}").json()["status"] == "planned"


def test_per_run_cap_survives_disable_reenable(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    calls = injected_gate(monkeypatch, lambda _: httpx.Response(200, json=fixture_reply(
        disposition="unsupported", representation="keep", camera="keep")))
    client.post(f"/runs/{rid}/viewer/online", json={"enabled": True})
    for _ in range(4):
        response = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "unsupported ask"))
        assert response.json()["status"] == "unsupported", response.text
    assert calls["requests"] == 4
    client.post(f"/runs/{rid}/viewer/online", json={"enabled": False})
    client.post(f"/runs/{rid}/viewer/online", json={"enabled": True})
    fifth = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "one more"))
    assert fifth.json()["status"] == "rejected" and fifth.json()["reason_code"] == "viewer_cap_exhausted"
    assert calls["requests"] == 4
    assert client.get(f"/runs/{rid}/viewer/online").json()["remaining"] == 0


def test_invalid_model_answer_still_settles_valid_usage(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    injected_gate(monkeypatch, lambda _: httpx.Response(200, json=fixture_reply(
        selection="obj://foreign/structure/bad", usage={"input_tokens": 101, "output_tokens": 7, "cost": 0.003})))
    client.post(f"/runs/{rid}/viewer/online", json={"enabled": True})
    response = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "Choose target"))
    assert response.json()["status"] == "rejected" and response.json()["reason_code"] == "response_invalid"
    assert response.json()["commands"] == []
    assert client.get(f"/runs/{rid}/budget").json()["external_tokens"]["used"] == 108
    assert client.get(f"/runs/{rid}/budget").json()["usd"]["used"] == pytest.approx(0.003)


def test_alias_compiler_rejects_ambiguous_or_unsafe_choices(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid, fixture="public_1hsg.cif", scope_chain_auth="B")
    assert scene["targets"]
    target = scene["targets"][0]
    run = api_module.RUNS[rid]
    created = create_session(run, client_instance_id=_id(), scene_generation=1,
                             structure_handle=scene["structure_handle"], scope_chain_auth="B",
                             selected_target=target["residue"])
    internal = _session(run, created["viewer_session_id"])
    answers = fixture_reply(selection=target["alias"], camera="focus_selected")["answers"]
    status, commands, _ = compile_answers(answers, internal, intent_id=_id())
    assert status == "planned"
    assert commands[1]["target"] == target["residue"]
    assert commands[2]["target"] == target["residue"]
    with pytest.raises(ViewerError):
        compile_answers(fixture_reply(selection="t9999")["answers"], internal, intent_id=_id())
    with pytest.raises(ViewerError):
        compile_answers(fixture_reply(selection="clear", camera="focus_selected")["answers"], internal, intent_id=_id())
    with pytest.raises(ViewerError):
        compile_answers(fixture_reply(disposition="apply", representation="keep", camera="keep",
                                      selection="keep")["answers"] | {"unexpected": {}}, internal, intent_id=_id())


def test_cancel_while_transport_busy_and_revoke_online(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    entered = threading.Event()
    async def handler(request):
        entered.set()
        await asyncio.sleep(2)
        return httpx.Response(200, json=fixture_reply())
    gate = EgressGate(transport=httpx.MockTransport(handler), credential_resolver=lambda: "fixture-only-key")
    monkeypatch.setattr(api_module, "VIEWER_GATE", gate)
    client.post(f"/runs/{rid}/viewer/online", json={"enabled": True})
    payload = intent_request(scene, "Show surface")
    result = {}
    worker = threading.Thread(target=lambda: result.update(client.post(
        f"/runs/{rid}/viewer/intents", json=payload).json()), daemon=True)
    worker.start()
    assert entered.wait(3), "fixture transport did not begin"
    cancelled = client.post(f"/runs/{rid}/viewer/intents/{payload['request_id']}/cancel")
    assert cancelled.status_code == 200
    worker.join(3)
    assert not worker.is_alive()
    assert result["status"] == "cancelled" and result["commands"] == []
    assert client.get(f"/runs/{rid}/viewer/online").json()["used"] == 1
    # Unknown usage after cancellation conservatively stops this run. Use an
    # independent run to verify mode revocation while its transport waits.
    client2, rid2 = setup_api(monkeypatch, tmp_path / "revoke")
    scene2 = loaded_scene(client2, rid2)
    monkeypatch.setattr(api_module, "VIEWER_GATE", gate)
    client2.post(f"/runs/{rid2}/viewer/online", json={"enabled": True})
    entered.clear()
    payload2 = intent_request(scene2, "Zoom in")
    result2 = {}
    worker2 = threading.Thread(target=lambda: result2.update(client2.post(
        f"/runs/{rid2}/viewer/intents", json=payload2).json()), daemon=True)
    worker2.start()
    assert entered.wait(3)
    disabled = client2.post(f"/runs/{rid2}/viewer/online", json={"enabled": False})
    assert disabled.status_code == 200 and disabled.json()["mode"] == "local_only"
    worker2.join(3)
    assert not worker2.is_alive()
    assert result2["status"] == "cancelled" and result2["commands"] == []


def test_scene_revision_invalidates_late_ack_and_old_generation(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    planned = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "/zoom out")).json()
    update = client.post(f"/runs/{rid}/viewer/sessions/{scene['viewer_session_id']}/state", json={
        "representation": "cartoon", "selected_alias": None, "action_revision": 1})
    assert update.status_code == 200
    ack = {"command_id": planned["commands"][0]["command_id"], "status": "applied",
           "client_instance_id": scene["client_instance_id"], "viewer_session_id": scene["viewer_session_id"],
           "scene_generation": 1, "action_revision": 0}
    assert client.post(f"/runs/{rid}/viewer/intents/{planned['intent_id']}/ack", json=ack).status_code == 409
    newer = loaded_scene(client, rid, client_id=scene["client_instance_id"], generation=2)
    assert newer["scene_generation"] == 2
    stale = client.post(f"/runs/{rid}/viewer/intents", json=intent_request(scene, "/reset"))
    assert stale.status_code == 409


def test_crash_reopen_never_auto_resends_unfinished_intent(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    run = api_module.RUNS[rid]
    intent_id = _id()
    run.events.append("viewer_intent_requested", intent_id=intent_id, request_id=intent_id,
                      payload_sha256="0" * 64, prompt_sha256="1" * 64, source="jev",
                      viewer_session_id=scene["viewer_session_id"], client_instance_id=scene["client_instance_id"],
                      scene_generation=1, structure_handle=scene["structure_handle"],
                      catalog_hash=scene["catalog_hash"], action_revision=0)
    api_module.RUNS.clear()
    calls = injected_gate(monkeypatch, lambda _: pytest.fail("recovery resent a model request"))
    state = client.get(f"/runs/{rid}/viewer/intents/{intent_id}").json()
    assert state["status"] == "detached" and state["commands"] == []
    assert calls == {"credentials": 0, "requests": 0}


def test_stop_before_request_admission_is_durable_tombstone(monkeypatch, tmp_path):
    client, rid = setup_api(monkeypatch, tmp_path)
    scene = loaded_scene(client, rid)
    calls = injected_gate(monkeypatch, lambda _: pytest.fail("stopped intent dispatched"))
    client.post(f"/runs/{rid}/viewer/online", json={"enabled": True})
    payload = intent_request(scene, "Show surface")
    scope = {key: payload[key] for key in ("client_instance_id", "viewer_session_id", "scene_generation")}
    stopped = client.post(f"/runs/{rid}/viewer/intents/{payload['request_id']}/cancel", json=scope)
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
    delayed = client.post(f"/runs/{rid}/viewer/intents", json=payload)
    assert delayed.status_code == 201 and delayed.json()["status"] == "cancelled"
    assert calls == {"credentials": 0, "requests": 0}
    assert client.get(f"/runs/{rid}/viewer/online").json()["used"] == 0
    assert client.post(f"/runs/{rid}/viewer/intents", json=payload).json()["status"] == "cancelled"
    assert client.post(f"/runs/{rid}/viewer/intents/{_id()}/cancel", json={
        **scope, "scene_generation": 999}).status_code == 409


def test_old_consent_never_revives_plan_ack_or_pending_request(tmp_path):
    run = new_run(tmp_path, run_id="consent_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "mini_complex.pdb")})
    scene = create_session(run, client_instance_id=_id(), scene_generation=1, structure_handle=loaded.handle)
    set_online(run, True)
    intent_id, internal, _ = request_intent(run, client_instance_id=scene["client_instance_id"],
        viewer_session_id=scene["viewer_session_id"], scene_generation=1, request_id=_id(), prompt="surface")
    from mw.viewer_intents import finish_intent
    answers = fixture_reply(selection="keep", camera="keep")["answers"]
    status, commands, reason = compile_answers(answers, internal, intent_id=intent_id)
    finish_intent(run, intent_id, status=status, reason_code=reason, commands=commands)
    set_online(run, False)
    set_online(run, True)
    assert not intent_live(run, intent_id)
    from mw.viewer_intents import acknowledge
    with pytest.raises(ViewerError):
        acknowledge(run, intent_id, command_id=commands[0]["command_id"], status="applied",
            reason_code=None, client_instance_id=scene["client_instance_id"],
            viewer_session_id=scene["viewer_session_id"], scene_generation=1, action_revision=0)


def test_malformed_choice_and_mutated_validated_projection_are_rejected(tmp_path):
    run = new_run(tmp_path, run_id="projection_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "mini_complex.pdb")})
    scene = create_session(run, client_instance_id=_id(), scene_generation=1, structure_handle=loaded.handle)
    from mw.viewer_intents import _session
    state = projected_state(_session(run, scene["viewer_session_id"]), "Show surface")
    state.catalog[0].chain_auth = "/private/sensitive.pdb"
    with pytest.raises(ValidationError):
        body_for(state)
    state = projected_state(_session(run, scene["viewer_session_id"]), "Show surface")
    state.selected_target = "obj://foreign/bad"
    with pytest.raises(ValidationError):
        body_for(state)
    answers = fixture_reply()["answers"]
    answers["camera"]["choice"] = []
    assert parse_answers({"model": "typesafe/jev-1.13-20260917", "answers": answers}, [])[1] == "response_invalid"
    with pytest.raises(ViewerError):
        compile_answers(answers, _session(run, scene["viewer_session_id"]), intent_id=_id())


def test_concurrent_same_uuid_admission_and_gate_cannot_dispatch_twice(tmp_path):
    run = new_run(tmp_path, run_id="race_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "mini_complex.pdb")})
    scene = create_session(run, client_instance_id=_id(), scene_generation=1, structure_handle=loaded.handle)
    set_online(run, True)
    request_id = _id()
    entered = threading.Event()
    original_append = run.events.append
    def delayed_append(kind, **fields):
        if kind == "viewer_intent_requested" and fields.get("intent_id") == request_id:
            entered.set(); time.sleep(0.05)
        return original_append(kind, **fields)
    run.events.append = delayed_append
    def submit():
        return request_intent(run, client_instance_id=scene["client_instance_id"],
            viewer_session_id=scene["viewer_session_id"], scene_generation=1,
            request_id=request_id, prompt="Show surface")
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(submit)
        assert entered.wait(1)
        second = pool.submit(submit)
        results = [first.result(timeout=2), second.result(timeout=2)]
    run.events.append = original_append
    assert sorted(result[2] for result in results) == [False, True]
    assert sum(event["type"] == "viewer_intent_requested" and event.get("intent_id") == request_id
               for event in run.events.read()) == 1
    calls = []
    async def fake_http(encoded, key, timeout, observed):
        calls.append(timeout); observed["status"] = 200
        return json.dumps(fixture_reply()).encode(), False
    gate = EgressGate(credential_resolver=lambda: "inert-fixture-only")
    gate._http_request = fake_http
    async def dispatch():
        state = projected_state(results[0][1], "Show surface")
        return [await request_viewer(gate, run, state, request_id) for _ in results]
    outcomes = asyncio.run(dispatch())
    assert len(calls) == 1
    assert outcomes[0].status == "accepted" and outcomes[1].reason_code == "already_dispatched"


def test_outer_cancel_awaits_owned_transport_cleanup(tmp_path):
    run = new_run(tmp_path, run_id="outer_cancel_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "mini_complex.pdb")})
    scene = create_session(run, client_instance_id=_id(), scene_generation=1, structure_handle=loaded.handle)
    set_online(run, True)
    intent_id, internal, _ = request_intent(run, client_instance_id=scene["client_instance_id"],
        viewer_session_id=scene["viewer_session_id"], scene_generation=1, request_id=_id(), prompt="Show surface")
    async def check():
        entered = asyncio.Event(); cleaned = asyncio.Event(); child = []
        async def transport(*args):
            child.append(asyncio.current_task()); entered.set()
            try: await asyncio.Event().wait()
            finally: cleaned.set()
        gate = EgressGate(credential_resolver=lambda: "inert-fixture-only")
        gate._http_request = transport
        outer = asyncio.create_task(request_viewer(gate, run, projected_state(internal, "Show surface"), intent_id))
        await asyncio.wait_for(entered.wait(), 2)
        outer.cancel()
        try: await outer
        except asyncio.CancelledError: pass
        assert child[0].done() and cleaned.is_set()
        with run._owner(): pass
    asyncio.run(check())


def test_dispatch_audit_deadline_skips_transport_and_reopen_reconciles(tmp_path):
    run = new_run(tmp_path / "deadline", run_id="deadline_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "mini_complex.pdb")})
    scene = create_session(run, client_instance_id=_id(), scene_generation=1, structure_handle=loaded.handle)
    set_online(run, True)
    intent_id, internal, _ = request_intent(run, client_instance_id=scene["client_instance_id"],
        viewer_session_id=scene["viewer_session_id"], scene_generation=1, request_id=_id(), prompt="Show surface")
    clock = [0.0]; run.monotonic = lambda: clock[0]
    gate = EgressGate(credential_resolver=lambda: "inert-fixture-only")
    original_audit = gate._audit
    def slow_audit(owner, stage, audit_id, **fields):
        original_audit(owner, stage, audit_id, **fields)
        if stage == "dispatch_started": clock[0] += 2000
    gate._audit = slow_audit
    async def forbidden(*args):
        pytest.fail("expired attempt invoked transport")
    gate._http_request = forbidden
    outcome = asyncio.run(request_viewer(gate, run, projected_state(internal, "Show surface"), intent_id))
    assert outcome.reason_code == "budget_exhausted"
    # The accepted recovery path must parse the persisted dispatch audit.
    reopened = new_run(tmp_path / "deadline", run_id="deadline_probe", dry_run=False)
    with reopened._mutation(): pass


def test_crash_after_dispatch_audit_reopens_without_missing_deadline(tmp_path):
    root = Path(__file__).parents[2]
    script = """
import asyncio, os, sys, uuid
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from mw.workspace import new_run
from mw.viewer_intents import create_session, set_online, request_intent, projected_state
from mw.egress.gate import EgressGate
from mw.egress.viewer import request_viewer
run = new_run(Path(sys.argv[2]), run_id='crash_probe', dry_run=False)
loaded = run.call('load_structure', {'source': sys.argv[3]})
scene = create_session(run, client_instance_id=str(uuid.uuid4()), scene_generation=1, structure_handle=loaded.handle)
set_online(run, True)
intent_id, internal, _ = request_intent(run, client_instance_id=scene['client_instance_id'],
    viewer_session_id=scene['viewer_session_id'], scene_generation=1,
    request_id=str(uuid.uuid4()), prompt='Show surface')
gate = EgressGate(credential_resolver=lambda: 'inert-fixture-only')
original = gate._audit
def audit(owner, stage, audit_id, **fields):
    original(owner, stage, audit_id, **fields)
    if stage == 'dispatch_started': os._exit(86)
gate._audit = audit
asyncio.run(request_viewer(gate, run, projected_state(internal, 'Show surface'), intent_id))
"""
    run_dir = tmp_path / "crash"
    child = subprocess.run([sys.executable, "-c", script, str(root / "backend"),
                            str(run_dir), str(FIX / "mini_complex.pdb")],
                           cwd=root, env={**os.environ, "PYTHONPATH": str(root / "backend")},
                           capture_output=True, timeout=10, check=False)
    assert child.returncode == 86
    reopened = new_run(run_dir, run_id="crash_probe", dry_run=False)
    with reopened._mutation(): pass
    assert reopened.egress_unknown


def test_large_single_chain_allows_targetless_viewer_and_exact_local_scope(tmp_path):
    source = tmp_path / "large_single_chain.pdb"
    lines = [f"ATOM  {index:5d}  CA  ALA A{index:4d}    {float(index):8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{20.0:6.2f}           C"
             for index in range(1, 302)]
    source.write_text("\n".join(lines + ["END"]) + "\n")
    run = new_run(tmp_path / "large_run", run_id="large_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(source)})
    whole = create_session(run, client_instance_id=_id(), scene_generation=1,
                           structure_handle=loaded.handle)
    assert whole["catalog"] == [] and whole["targets"] == [] and whole["scope_complete"] is False
    from mw.viewer_intents import _session, local_answers
    internal = _session(run, whole["viewer_session_id"])
    answer = local_answers("/zoom in", internal)
    status, commands, _ = compile_answers(answer, internal, intent_id=_id())
    assert status == "planned" and commands[0]["axis"] == "camera"
    assert body_for(projected_state(internal, "Show surface"))
    # The chain itself remains oversized; the exact target scope is explicit.
    chain = create_session(run, client_instance_id=_id(), scene_generation=1,
                           structure_handle=loaded.handle, scope_chain_auth="A")
    assert chain["catalog"] == [] and chain["scope_complete"] is False
    from mw.tools.structural import structure_residues
    exact = structure_residues(run.store, loaded.handle)["residues"][24]
    narrow = create_session(run, client_instance_id=_id(), scene_generation=1,
                            structure_handle=loaded.handle, scope_target=exact)
    assert len(narrow["targets"]) == 1 and narrow["targets"][0]["residue"]["seq_auth"] == 25


def test_concurrent_scene_creation_cannot_roll_back_newer_generation(monkeypatch, tmp_path):
    run = new_run(tmp_path, run_id="scene_race_probe", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "mini_complex.pdb")})
    client_id = _id()
    create_session(run, client_instance_id=client_id, scene_generation=1,
                   structure_handle=loaded.handle)
    import mw.viewer_intents as viewer_module
    original = viewer_module.structure_residues
    older_entered = threading.Event(); release_older = threading.Event()
    def delayed_residues(*args):
        if threading.current_thread().name == "older_scene":
            older_entered.set()
            assert release_older.wait(2)
        return original(*args)
    monkeypatch.setattr(viewer_module, "structure_residues", delayed_residues)
    outcomes = {}
    def older():
        try:
            outcomes["older"] = create_session(run, client_instance_id=client_id,
                scene_generation=2, structure_handle=loaded.handle)
        except ViewerError as exc:
            outcomes["older"] = exc.code
    thread = threading.Thread(target=older, name="older_scene")
    thread.start()
    assert older_entered.wait(1)
    newer = create_session(run, client_instance_id=client_id,
                           scene_generation=3, structure_handle=loaded.handle)
    release_older.set(); thread.join(2)
    assert not thread.is_alive()
    assert outcomes["older"] == "stale_scene"
    assert newer["current"] is True
    assert [event["scene_generation"] for event in run.events.read()
            if event["type"] == "viewer_session_created"] == [1, 3]
