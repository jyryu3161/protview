"""M24 T5 JEV science routes (spec .dryforge/spec.md 5 and 7): status, consent, preview, approved send, list, detail,
``/capabilities`` ``methods.jev_choice`` and the ``jev_choice`` report through ``/method_reports`` and ``/reports``.

Inputs are the REAL template runs of ``jev_send_fixture`` (public 1UBQ M20 set; real M17 RDKit jobs on the labelled
synthetic methacetin fixtures) and projections built through ``POST /commands`` (the real ``build_jev_projection``
tool). ``api_module.SCIENCE_GATE`` is replaced by a ``jev_send_fixture.Fake`` gate (``httpx.MockTransport``, inert
sentinel credential): no socket is opened and ``.env`` is never read. Provider replies are fixture values. Held run
locks, pre-filled in-progress sets and edited pins are fault injection, marked where used.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import SENTINEL, USAGE, Fake, clone, new_send_id, no_secret, reply, run_bytes, templates

from mw import jev_constants as J
from mw import jev_projection as P
from mw import jev_sends as S
from mw.api import app as api_module
from mw.core.handles import canonical_json

SEND_KEYS = {"schema", "send_id", "status", "reason_code", "projection_handle", "source", "kind", "question_id",
             "selection_count", "body_sha256", "body_bytes", "audit_id", "requested_model", "served_model", "usage",
             "choice_handle", "late", "late_reason", "approved_event_seq", "outcome_event_seq"}
PROBABILITY_VALUES = (0.4321, 0.1234)   # fixture reply values, never a provider output


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return templates(tmp_path_factory.getbasetemp() / "jev_send_templates")


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    assert not S.ACTIVE_SENDS
    S.ACTIVE_SENDS.clear()


def _open(base, tmp_path, monkeypatch, which="mutation", fake=None, *, extra=()):
    """Events-only copies of template runs under one runs root; the API serves that root through a Fake gate."""
    root = tmp_path / "runs"
    world = clone(base[which], root)
    others = {name: clone(base[name], root) for name in extra}
    fake = fake or Fake(lambda request: reply("m01" if world["kind"] == "mutation" else "c01"))
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    monkeypatch.setattr(api_module, "SCIENCE_GATE", fake.gate)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    return world, fake, client, others


def _url(world, tail=""):
    return f"/runs/{world['run_id']}/jev{tail}"


def _log(world):
    return (world["root"] / world["run_id"] / "events.jsonl").read_bytes()


def _events(world):
    return [json.loads(line) for line in _log(world).splitlines()]


def _request(world, which="projection", **overrides):
    content = world["run"].store.load(world[which])
    return {"send_id": new_send_id(), "projection": world[which],
            "body_sha256": P.body_sha256(P.projection_body(content)[1]), "confirm": J.CONFIRM, **overrides}


def _consent(client, world, enabled=True):
    response = client.post(_url(world, "/consent"), json={"enabled": enabled})
    assert response.status_code == 200, response.text
    return response.json()


def _refused(response, status, error, reason_code=None):
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["error"] == error, detail
    if reason_code is not None:
        assert detail["reason_code"] == reason_code, detail
    return detail


# ---------------------------------------------------------------- the whole flow, one per source kind


@pytest.mark.parametrize("which", ["mutation", "ligand"])
def test_consent_projection_preview_send_list_detail_and_report_through_the_api(which, base, tmp_path, monkeypatch):
    prefix = J.ALIAS_PREFIXES[which]
    probabilities = {f"{prefix}01": PROBABILITY_VALUES[0], f"{prefix}02": PROBABILITY_VALUES[1]}
    fake = Fake(lambda request: reply(f"{prefix}02", confidence=0.6789, probabilities=probabilities))
    world, fake, client, _ = _open(base, tmp_path, monkeypatch, which, fake)
    rid, texts = world["run_id"], []

    def keep(response):
        texts.append(response.text)
        return response

    status = keep(client.get(_url(world, "/status"))).json()
    assert status["schema"] == J.STATUS_SCHEMA and status["enabled"] is False and status["used"] == 0
    assert keep(client.post(_url(world, "/consent"), json={"enabled": True})).json()["enabled"] is True
    if which == "mutation":
        candidates = [5, 1, 2]
    else:
        ids = [row["id"] for row in world["run"].store.load(world["source"])["candidates"]]
        candidates = [ids[3], ids[1], ids[2]]
    made = keep(client.post(f"/runs/{rid}/commands", json={
        "tool": J.TOOL, "args": {"source": world["source"], "candidates": candidates}}))
    assert made.status_code == 200, made.text
    projection = made.json()["handle"]["handle"]
    assert made.json()["handle"]["kind"] == J.PROJECTION_KIND

    preview = keep(client.post(_url(world, "/preview"), json={"projection": projection})).json()
    assert preview["schema"] == J.PREVIEW_SCHEMA and preview["blocked_by"] == [] and preview["previous_sends"] == 0
    stored = world["run"].store.load(projection)
    assert preview["body"].encode("ascii") == P.projection_body(stored)[1]
    assert preview["body_sha256"] == stored["body_sha256"] and preview["body_bytes"] == stored["body_bytes"]

    send_id = new_send_id()
    sent = keep(client.post(_url(world, "/sends"), json={
        "send_id": send_id, "projection": projection, "body_sha256": preview["body_sha256"], "confirm": J.CONFIRM}))
    assert sent.status_code == 200, sent.text
    record = sent.json()
    assert set(record) == SEND_KEYS and (record["status"], record["reason_code"]) == ("completed", None)
    assert record["send_id"] == send_id and record["kind"] == which and record["selection_count"] == 3
    # The bytes the transport received = the preview string = the audited prepared body.
    assert len(fake.requests) == 1 and fake.requests[0].content == preview["body"].encode("ascii")
    prepared = [e for e in _events(world) if e["type"] == "egress" and e["stage"] == "prepared"
                and e["audit_id"] == record["audit_id"]]
    assert len(prepared) == 1 and P.canonical_ascii(prepared[0]["body"]) == preview["body"].encode("ascii")

    listed = keep(client.get(_url(world, "/sends"))).json()
    assert listed == [record]
    detail = keep(client.get(_url(world, f"/sends/{send_id}"))).json()
    assert {key: detail[key] for key in SEND_KEYS} == record and set(detail) == SEND_KEYS | {"choice", "local_display"}
    choice = detail["choice"]
    assert choice["schema"] == J.CHOICE_SCHEMA and choice["scientific_result"] is False
    assert choice["answer"]["choice_alias"] == f"{prefix}02" and choice["answer"]["confidence"] == 0.6789
    assert choice["answer"]["probabilities"] == probabilities     # stored as received, in the reply's key order
    assert detail["local_display"] == choice["answer"]["local_display"]
    assert choice == world["run"].store.load(record["choice_handle"])

    made_report = keep(client.post(f"/runs/{rid}/method_reports", json={"result_handle": record["choice_handle"]}))
    assert made_report.status_code == 201, made_report.text
    report = made_report.json()
    manifest, markdown = report["manifest"], report["markdown"]
    assert manifest["analysis_type"] == "jev_choice" and manifest["render_version"] == "jev_choice_markdown@1"
    assert manifest["external_response"] == {"kind": "jev_choice", "scientific_evidence": False}
    assert {claim["evidence_kind"] for claim in manifest["claims"]} == {"computed", "model_response"}
    dumped = canonical_json(manifest).decode()
    assert '"probabilities"' not in dumped and "answer.probabilities" not in dumped   # no such key or field
    for value in PROBABILITY_VALUES:
        assert str(value) not in dumped and str(value) not in markdown
    rows = keep(client.get(f"/runs/{rid}/reports")).json()
    assert [(row["handle"], row["analysis_type"], row["result_handle"]) for row in rows] == [
        (report["handle"], "jev_choice", record["choice_handle"])]
    selected = keep(client.get(f"/runs/{rid}/reports/selected", params={"handle": report["handle"]})).json()
    assert selected == report
    as_md = client.get(f"/runs/{rid}/reports/download", params={"handle": report["handle"], "format": "markdown"})
    as_json = client.get(f"/runs/{rid}/reports/download", params={"handle": report["handle"], "format": "json"})
    assert as_md.status_code == as_json.status_code == 200
    assert as_md.content == markdown.encode("utf-8") and as_json.content == canonical_json(manifest)
    texts += [as_md.text, as_json.text]
    # The key never leaves the resolver: no API answer, event, object or report holds it.
    assert fake.key_reads == 1 and fake.requests[0].headers["authorization"] == f"Bearer {SENTINEL}"
    assert no_secret(texts) and SENTINEL.encode() not in run_bytes(world["run"])


# ---------------------------------------------------------------- reads write nothing and read the log once


def test_reads_create_no_event_and_read_the_event_log_once(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch, "ligand")
    _consent(client, world)
    request = _request(world)
    assert client.post(_url(world, "/sends"), json=request).json()["status"] == "completed"
    run = api_module.RUNS[world["run_id"]]
    reads = {"count": 0}
    real = run.events.read

    def counting():
        reads["count"] += 1
        return real()

    monkeypatch.setattr(run.events, "read", counting)
    before = _log(world)
    calls = {
        "status": lambda: client.get(_url(world, "/status")),
        "preview": lambda: client.post(_url(world, "/preview"), json={"projection": world["projection"]}),
        "list": lambda: client.get(_url(world, "/sends")),
        "detail": lambda: client.get(_url(world, f"/sends/{request['send_id']}")),
    }
    for name, call in calls.items():
        reads["count"] = 0
        response = call()
        assert response.status_code == 200, (name, response.text)
        assert reads["count"] == 1, name
    assert _log(world) == before and len(fake.requests) == 1
    assert client.get(_url(world, f"/sends/{request['send_id']}")).json()["choice"]["schema"] == J.CHOICE_SCHEMA


def test_unknown_query_parameters_are_refused_before_anything_runs(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch)
    _consent(client, world)
    request = _request(world)
    before = _log(world)
    params = {"x": "1"}
    for response in (
            client.get(_url(world, "/status"), params=params),
            client.post(_url(world, "/consent"), params=params, json={"enabled": False}),
            client.post(_url(world, "/preview"), params=params, json={"projection": world["projection"]}),
            client.post(_url(world, "/sends"), params=params, json=request),
            client.get(_url(world, "/sends"), params=params),
            client.get(_url(world, f"/sends/{request['send_id']}"), params=params)):
        _refused(response, 422, "input_invalid")
    assert _log(world) == before and fake.requests == [] and fake.key_reads == 0


def test_routes_are_registered_list_before_detail(base, tmp_path, monkeypatch):
    world, _, client, _ = _open(base, tmp_path, monkeypatch)
    paths = [(getattr(route, "path", ""), sorted(getattr(route, "methods", []) or [])) for route in api_module.app.routes]
    names = [path for path, _ in paths]
    assert names.index("/runs/{rid}/jev/sends") < names.index("/runs/{rid}/jev/sends/{send_id}")
    jev_routes = sorted((path, methods) for path, methods in paths if path.startswith("/runs/{rid}/jev/"))
    assert jev_routes == sorted([("/runs/{rid}/jev/status", ["GET"]), ("/runs/{rid}/jev/consent", ["POST"]),
                                 ("/runs/{rid}/jev/preview", ["POST"]), ("/runs/{rid}/jev/sends", ["POST"]),
                                 ("/runs/{rid}/jev/sends", ["GET"]), ("/runs/{rid}/jev/sends/{send_id}", ["GET"])])
    assert client.get(_url(world, "/sends")).json() == []
    _refused(client.get(_url(world, f"/sends/{new_send_id()}")), 404, "not_found")


# ---------------------------------------------------------------- refusals


def test_consent_route_refusals(base, tmp_path, monkeypatch):
    world, fake, client, others = _open(base, tmp_path, monkeypatch, extra=("dry",))
    dry = others["dry"]
    before = _log(dry)
    _refused(client.post(_url(dry, "/consent"), json={"enabled": True}), 412, "dry_run")
    assert _log(dry) == before
    assert _consent(client, dry, False)["enabled"] is False          # turning it off is always allowed
    before = _log(world)
    for body in ({"enabled": "yes"}, {"enabled": 1}, {}, {"enabled": True, "policy": "x"}, [], {"enabled": None}):
        _refused(client.post(_url(world, "/consent"), json=body), 422, "input_invalid")
    for raw in (b"not json", b'{"enabled": true, "enabled": false}', b'{"enabled": NaN}'):
        _refused(client.post(_url(world, "/consent"), content=raw), 422, "input_invalid")
    _refused(client.post(_url(world, "/consent"), content=b'{"enabled": true' + b" " * 5000 + b"}"),
             413, "resource_exceeded")
    _refused(client.post("/runs/run_jev_missing/jev/consent", json={"enabled": True}), 404, "not_found")
    assert _log(world) == before and fake.key_reads == 0
    status = _consent(client, world)
    assert status["enabled"] is True and api_module.RUNS[world["run_id"]].egress_config["mode"] == "local_only"
    consent = [e for e in _events(world) if e["type"] == J.EVENT_CONSENT]
    assert len(consent) == 1 and consent[0]["enabled"] is True and fake.key_reads == 0


def test_preview_and_send_refuse_other_runs_unknown_handles_and_other_kinds(base, tmp_path, monkeypatch):
    world, fake, client, others = _open(base, tmp_path, monkeypatch, extra=("ligand",))
    _consent(client, world)
    other = others["ligand"]
    missing = f"obj://{world['run_id']}/{J.PROJECTION_KIND}/{'0' * 64}"
    before = _log(world)
    for handle, status, error, reason in (
            (other["projection"], 404, "not_found", None),        # a projection of another run
            (missing, 404, "not_found", None),
            ("obj://not a handle", 404, "not_found", None),
            (world["source"], 422, "input_invalid", J.PROJECTION_INVALID),     # this run, another kind
            (world["prepared"], 422, "input_invalid", J.PROJECTION_INVALID)):
        _refused(client.post(_url(world, "/preview"), json={"projection": handle}), status, error, reason)
        request = _request(world, body_sha256="a" * 64, projection=handle)
        _refused(client.post(_url(world, "/sends"), json=request), status, error, reason)
    for body in ({}, {"projection": 3}, {"projection": world["projection"], "extra": 1}):
        _refused(client.post(_url(world, "/preview"), json=body), 422, "input_invalid")
    assert _log(world) == before and fake.requests == [] and fake.key_reads == 0


def test_send_request_shape_refusals_write_nothing(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch)
    _consent(client, world)
    good = _request(world)
    before = _log(world)
    bad = [
        {**good, "confirm": "yes"}, {**good, "confirm": None}, {k: v for k, v in good.items() if k != "confirm"},
        {**good, "send_id": "not-a-uuid"}, {**good, "send_id": "00000000-0000-1000-8000-000000000000"},
        {**good, "send_id": good["send_id"].upper()}, {**good, "body_sha256": good["body_sha256"].upper()},
        {**good, "body_sha256": "abc"}, {**good, "projection": 7}, {**good, "approved_by": "human"},
        {**good, "projection": [good["projection"]]}]
    for body in bad:
        _refused(client.post(_url(world, "/sends"), json=body), 422, "input_invalid")
    _refused(client.post(_url(world, "/sends"), content=json.dumps({**good, "pad": "x" * 4096}).encode()),
             413, "resource_exceeded")
    _refused(client.post(_url(world, "/sends"), content=b"[]"), 422, "input_invalid")
    assert _log(world) == before and fake.requests == [] and fake.key_reads == 0
    assert len(json.dumps(good).encode()) < J.MAX_SEND_REQUEST_BYTES


def test_send_conflicts_are_409_and_write_nothing(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch)
    _consent(client, world)
    before = _log(world)
    _refused(client.post(_url(world, "/sends"), json=_request(world, body_sha256="0" * 64)), 409, "preview_mismatch")
    assert _log(world) == before
    first = _request(world)
    assert client.post(_url(world, "/sends"), json=first).json()["status"] == "completed"
    after_first = _log(world)
    conflicting = _request(world, "other_projection", send_id=first["send_id"])
    _refused(client.post(_url(world, "/sends"), json=conflicting), 409, "send_id_conflict")
    assert _log(world) == after_first
    S.begin_send(world["run_id"], new_send_id())   # fault injection: another send of this run is in flight
    try:
        _refused(client.post(_url(world, "/sends"), json=_request(world)), 409, "send_in_progress")
        assert client.get(_url(world, "/status")).json()["send_in_progress"] is True
        preview = client.post(_url(world, "/preview"), json={"projection": world["projection"]}).json()
        assert "send_in_progress" in preview["blocked_by"]
    finally:
        S.ACTIVE_SENDS.clear()
    assert _log(world) == after_first and len(fake.requests) == 1


def test_a_busy_run_lock_is_503_with_no_event(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch)
    _consent(client, world)
    run = api_module.RUNS[world["run_id"]]
    before = _log(world)
    with run._owner():   # fault injection: another owner (a Run.call, a job start) holds the run execution lock
        response = client.post(_url(world, "/sends"), json=_request(world))
    detail = _refused(response, 503, "busy")
    assert detail["message"] == api_module.JEV_BUSY_MESSAGE
    assert _log(world) == before and fake.requests == [] and fake.key_reads == 0 and not S.ACTIVE_SENDS


# ---------------------------------------------------------------- replays, re-sends, refusals and failures answer 200


def test_same_send_id_replays_and_the_same_projection_can_be_sent_again(base, tmp_path, monkeypatch):
    answers = iter(["m01", "m03"])
    world, fake, client, _ = _open(base, tmp_path, monkeypatch, fake=Fake(lambda request: reply(next(answers))))
    _consent(client, world)
    first = _request(world)
    record = client.post(_url(world, "/sends"), json=first).json()
    log = _log(world)
    assert client.post(_url(world, "/sends"), json=first).json() == record      # idempotent, no new event
    assert _log(world) == log and len(fake.requests) == 1
    second = client.post(_url(world, "/sends"), json=_request(world)).json()
    assert second["status"] == "completed" and second["choice_handle"] != record["choice_handle"]
    assert len(fake.requests) == 2 and fake.requests[0].content == fake.requests[1].content
    listed = client.get(_url(world, "/sends")).json()
    assert [row["send_id"] for row in listed] == [record["send_id"], second["send_id"]]   # oldest first
    status = client.get(_url(world, "/status")).json()
    assert (status["used"], status["remaining"]) == (2, J.SEND_CAP - 2)
    preview = client.post(_url(world, "/preview"), json={"projection": world["projection"]}).json()
    assert preview["previous_sends"] == 2
    choices = [client.get(_url(world, f"/sends/{row['send_id']}")).json()["choice"] for row in listed]
    assert [c["answer"]["choice_alias"] for c in choices] == ["m01", "m03"]


def test_refused_and_failed_sends_answer_200_with_their_record(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch,
                                   fake=Fake(lambda request: httpx.Response(500, json={"usage": USAGE})))
    refused = client.post(_url(world, "/sends"), json=_request(world))
    assert refused.status_code == 200
    record = refused.json()
    assert (record["status"], record["reason_code"], record["choice_handle"]) == ("rejected", "consent_off", None)
    assert record["audit_id"] is not None and fake.requests == [] and fake.key_reads == 0
    _consent(client, world)
    failed = client.post(_url(world, "/sends"), json=_request(world))
    assert failed.status_code == 200
    assert (failed.json()["status"], failed.json()["reason_code"]) == ("failed", "provider_http_error")
    detail = client.get(_url(world, f"/sends/{failed.json()['send_id']}")).json()
    assert detail["choice"] is None and detail["local_display"] is None
    status = client.get(_url(world, "/status")).json()
    assert status["used"] == 1    # a refusal uses no cap, a dispatched failure does


# ---------------------------------------------------------------- capability


def test_capability_reads_no_key_and_no_consent(base, tmp_path, monkeypatch):
    world, fake, client, _ = _open(base, tmp_path, monkeypatch)
    before = _log(world)
    methods = client.get("/capabilities").json()["methods"]
    assert methods["jev_choice"] == {"available": True, "reason_code": None, "reason": None}
    assert fake.key_reads == 0 and _log(world) == before
    with monkeypatch.context() as patch:   # fault injection: the tool is not exposed
        patch.setattr(api_module, "SUPPORTED_TOOLS", api_module.SUPPORTED_TOOLS - {J.TOOL})
        down = client.get("/capabilities").json()["methods"]["jev_choice"]
        assert (down["available"], down["reason_code"]) == (False, "tool_unavailable") and down["reason"]
    with monkeypatch.context() as patch:   # fault injection: the projection module's model pin drifts from the gate
        patch.setattr(P, "REQUEST_MODEL", "typesafe/other")
        down = client.get("/capabilities").json()["methods"]["jev_choice"]
        assert (down["available"], down["reason_code"]) == (False, "missing_configuration") and down["reason"]
    assert client.get("/capabilities").json()["methods"]["jev_choice"]["available"] is True
    assert fake.key_reads == 0


def test_the_science_gate_is_its_own_gate_instance():
    from mw.egress.gate import EgressGate
    assert isinstance(api_module.SCIENCE_GATE, EgressGate) and isinstance(api_module.VIEWER_GATE, EgressGate)
    assert api_module.SCIENCE_GATE is not api_module.VIEWER_GATE
