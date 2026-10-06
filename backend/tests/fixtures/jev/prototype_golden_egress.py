"""PROTOTYPE golden recorder (M24 T1): the audit/event sequences the EXISTING gates write today.

Calls the unmodified ``EgressGate.request_jev`` (M3) and ``mw.egress.viewer.request_viewer`` (M8) with an injected
``httpx.MockTransport`` and an inert sentinel credential (never a real key or socket), in throw-away runs under
``_work_golden`` (deleted at the end), and records for every event appended by the gate call: its ``type``, its field
names in on-disk order with JSON value types, and the values of closed / constant fields only (stage, reason codes,
modes, sent flags, models, destination, reservation and settlement numbers fixed by the scripted transport). Times,
sequence numbers, audit/intent/session ids, hashes and elapsed seconds are reduced to their type. One viewer case also
goes through the product HTTP route to pin the ``viewer_intent_*`` events around the gate.

``--write`` rewrites ``golden_egress_events.json`` (after checking two fresh recordings are identical);
``--check`` exits 0 only if a fresh recording equals the stored file. Later tasks use ``--check`` to show the
existing gate behaviour is unchanged (handoff absolute conditions 3 and 10).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx
from fastapi.testclient import TestClient

from mw.api import app as api_module
from mw.egress.gate import REQUEST_MODEL, SERVED_SNAPSHOT, EgressGate
from mw.egress.viewer import request_viewer
from mw.llm.openrouter import synthetic_connection_fixture
from mw.viewer_intents import create_session, projected_state, request_intent, set_online
from mw.workspace import new_run

WORK = HERE / "_work_golden"
GOLDEN = HERE / "golden_egress_events.json"
FIXTURE = BACKEND / "tests/fixtures/mini_complex.pdb"
SENTINEL = "sentinel_m24_t1_golden_key"
CLOSED = ("stage", "reason_code", "mode", "sent", "transport_invoked", "error_code", "reason", "gate", "axis",
          "http_status", "response_oversized", "served_model", "requested_model", "destination", "question_version",
          "unknown_axes", "overrun", "status", "source", "approved", "policy", "enabled", "request_cap", "tool",
          "expensive_calls", "external_tokens", "usd", "reservation", "delta", "actual", "limit", "by",
          "allowed_served_model", "commands")
USAGE = {"input_tokens": 100, "output_tokens": 2, "cost": 0.001}
ID_KEYS = ("structure_handle", "catalog_hash", "command_id", "intent_id", "viewer_session_id", "client_instance_id")


def online_config() -> dict[str, Any]:
    return {"mode": "online", "jev": {"enabled": True, "request_model": REQUEST_MODEL,
                                      "allowed_served_models": [SERVED_SNAPSHOT], "timeout_s": 15}}


def kind(value: Any) -> str:
    return "null" if value is None else {bool: "bool", int: "int", float: "float", str: "str",
                                          dict: "dict", list: "list"}[type(value)]


def shape(event: dict[str, Any]) -> dict[str, Any]:
    fields = [[name, kind(value)] for name, value in event.items()]
    nested = {name: [[key, kind(item)] for key, item in value.items()]
              for name, value in event.items() if isinstance(value, dict)}
    closed = {name: event[name] for name in CLOSED if name in event}
    if isinstance(closed.get("commands"), list):   # viewer commands carry ids and handles: keep only their shape
        closed["commands"] = [{key: (kind(value) if key in ID_KEYS else value) for key, value in command.items()}
                              for command in closed["commands"]]
    if event["type"] == "egress" and "usage" in event:
        closed["usage"] = event["usage"]
    if event["type"] == "checkpoint":
        closed.pop("usage", None)
    return {"type": event["type"], "fields": fields, "nested_fields": nested, "closed_values": closed}


def tail(run: Any, before: int) -> list[dict[str, Any]]:
    """Events appended after ``before`` lines, in on-disk key order (the log is written with sort_keys)."""
    lines = (run.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    return [shape(json.loads(line)) for line in lines[before:] if line.strip()]


def count(run: Any) -> int:
    return sum(1 for line in (run.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())


def gate_with(handler: Any, *, key: str | None = SENTINEL) -> tuple[EgressGate, dict[str, int]]:
    calls = {"transport": 0, "credential": 0}

    def spy(request: httpx.Request) -> httpx.Response:
        calls["transport"] += 1
        return handler(request)

    def resolve() -> str | None:
        calls["credential"] += 1
        return key

    return EgressGate(transport=httpx.MockTransport(spy), credential_resolver=resolve), calls


def jev_answer(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"model": SERVED_SNAPSHOT, "usage": USAGE,
                                     "answers": {"inspection_view": {"type": "choice", "choice": "summary"}}})


def m3_cases() -> dict[str, Any]:
    cases = {
        "local_only": ({"mode": "local_only"}, False, True, jev_answer, SENTINEL),
        "dry_run": (online_config(), True, True, jev_answer, SENTINEL),
        "missing_configuration": ({"mode": "online"}, False, True, jev_answer, SENTINEL),
        "approval_required": (online_config(), False, False, jev_answer, SENTINEL),
        "missing_credential": (online_config(), False, True, jev_answer, None),
        "accepted": (online_config(), False, True, jev_answer, SENTINEL),
        "provider_http_error": (online_config(), False, True, lambda _: httpx.Response(503, json={"x": 1}), SENTINEL),
        "transport_error": (online_config(), False, True,
                            lambda _: (_ for _ in ()).throw(httpx.ConnectError("fixture")), SENTINEL),
        "usage_missing": (online_config(), False, True,
                          lambda _: httpx.Response(200, json={"model": SERVED_SNAPSHOT, "answers": {
                              "inspection_view": {"type": "choice", "choice": "summary"}}}), SENTINEL),
    }
    out = {}
    for name, (egress, dry, approve, handler, key) in cases.items():
        run = new_run(WORK / "m3", run_id=f"m3_{name}", dry_run=dry, egress_config=egress)
        if approve and not dry and egress.get("mode") == "online":
            run.approve("expensive_first_call")
        gate, calls = gate_with(handler, key=key)
        before = count(run)
        result = gate.request_jev(run, synthetic_connection_fixture())
        out[name] = {"result": {"status": result.status, "reason_code": result.reason_code, "action": result.action,
                                "served_model": result.served_model, "usage": result.usage},
                     "transport_calls": calls["transport"], "credential_reads": calls["credential"],
                     "events": tail(run, before)}
    return out


def viewer_answer(request: httpx.Request) -> httpx.Response:
    answers = {name: {"type": "choice", "choice": value} for name, value in {
        "disposition": "apply", "representation": "surface", "selection": "keep", "camera": "reset"}.items()}
    return httpx.Response(200, json={"model": SERVED_SNAPSHOT, "answers": answers, "usage": USAGE})


def viewer_run(name: str, *, dry: bool, online: bool) -> tuple[Any, str, Any]:
    run = new_run(WORK / "m8", run_id=f"m8_{name}", dry_run=dry)
    loaded = run.call("load_structure", {"source": str(FIXTURE), "model_index": 0})
    client = "00000000-0000-4000-8000-000000000001"
    scene = create_session(run, client_instance_id=client, scene_generation=1, structure_handle=loaded.handle)
    if online:
        set_online(run, True)
    intent_id, internal, _ = request_intent(run, client_instance_id=client,
                                            viewer_session_id=scene["viewer_session_id"], scene_generation=1,
                                            request_id=str(uuid.uuid4()), prompt="Show surface")
    return run, intent_id, projected_state(internal, "Show surface")


def m8_cases() -> dict[str, Any]:
    cases = {"local_only": (False, False, viewer_answer, SENTINEL), "dry_run": (True, False, viewer_answer, SENTINEL),
             "missing_credential": (False, True, viewer_answer, None),
             "accepted": (False, True, viewer_answer, SENTINEL),
             "provider_http_error": (False, True, lambda _: httpx.Response(503, json={"x": 1}), SENTINEL)}
    out = {}
    for name, (dry, online, handler, key) in cases.items():
        run, intent_id, state = viewer_run(name, dry=dry, online=online)
        gate, calls = gate_with(handler, key=key)
        before = count(run)
        result = asyncio.run(request_viewer(gate, run, state, intent_id))
        out[name] = {"result": {"status": result.status, "reason_code": result.reason_code,
                                "served_model": result.served_model, "usage": result.usage},
                     "transport_calls": calls["transport"], "credential_reads": calls["credential"],
                     "events": tail(run, before)}
    return out


def m8_route_case() -> dict[str, Any]:
    api_module.RUNS_DIR = WORK / "api"
    api_module.RUNS.clear()
    gate, calls = gate_with(viewer_answer)
    original = api_module.VIEWER_GATE
    api_module.VIEWER_GATE = gate
    try:
        client = TestClient(api_module.app, base_url="http://127.0.0.1")
        rid = client.post("/runs", json={"dry_run": False}).json()["run_id"]
        upload = client.post(f"/runs/{rid}/uploads?filename=mini_complex.pdb", content=FIXTURE.read_bytes())
        loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure", "args": {
            "source": upload.json()["upload_id"], "model_index": 0}}).json()["handle"]["handle"]
        scene = client.post(f"/runs/{rid}/viewer/sessions", json={
            "client_instance_id": "00000000-0000-4000-8000-000000000002", "scene_generation": 1,
            "structure_handle": loaded}).json()
        client.post(f"/runs/{rid}/viewer/online", json={"enabled": True})
        run = api_module.RUNS[rid]
        before = count(run)
        response = client.post(f"/runs/{rid}/viewer/intents", json={
            "client_instance_id": scene["client_instance_id"], "viewer_session_id": scene["viewer_session_id"],
            "scene_generation": 1, "request_id": str(uuid.uuid4()), "prompt": "Show surface"})
        body = response.json()
        return {"http_status": response.status_code, "intent_status": body.get("status"),
                "reason_code": body.get("reason_code"), "transport_calls": calls["transport"],
                "events": tail(run, before)}
    finally:
        api_module.VIEWER_GATE = original


def record() -> dict[str, Any]:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    try:
        data = {"_fixture": ("GOLDEN (M24 T1): event/audit shapes the existing M3 request_jev and M8 request_viewer "
                             "write with a scripted MockTransport and an inert sentinel credential; ids, times, "
                             "hashes and elapsed seconds reduced to their JSON type. Not provider output."),
                "m3_request_jev": m3_cases(), "m8_request_viewer": m8_cases(), "m8_viewer_route": m8_route_case()}
        artifacts = b"".join(path.read_bytes() for path in WORK.rglob("*") if path.is_file())
        data["sentinel_key_in_any_artifact"] = SENTINEL.encode() in artifacts
        return data
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    fresh = record()
    if args.write:
        if record() != fresh:
            print("two fresh recordings differ; golden would not be stable", file=sys.stderr)
            return 1
        GOLDEN.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN.name}")
        return 0
    if json.loads(GOLDEN.read_text(encoding="utf-8")) != fresh:
        print("golden_egress_events.json differs from a fresh recording", file=sys.stderr)
        return 1
    print("golden_egress_events.json matches a fresh recording")
    return 0


if __name__ == "__main__":
    sys.exit(main())
