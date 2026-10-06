"""PROTOTYPE (M24 T1 measurement only, never product code): can an async FastAPI route, shaped like
``request_viewer`` (``async`` + ``with run._mutation():`` held across the awaited HTTP, the gate owning an
``httpx.MockTransport``), still write the egress audit, new ``jev_*`` events and an immutable object AFTER
``Run.cancel()`` or a consent-off event arrived during the request (spec 5 "late response")?

A throw-away FastAPI app mounts the unmodified product app (``tests/offscreen_agent_fixture/server.py`` pattern) and
adds one prototype route. The fixture transport blocks until released, so cancellation / consent-off / other requests
happen while the route awaits. Only an inert sentinel credential is used; no real network. Runs live in
``_work_late`` next to this file and are deleted at the end. Prints one JSON report.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mw.api import app as api_module
from mw.egress.gate import PROVIDER, REQUEST_MODEL, SERVED_SNAPSHOT, EgressGate, _usage
from mw.workspace import new_run

WORK = HERE / "_work_late"
SENTINEL = "sentinel_m24_t1_key_do_not_store"
TOKENS, USD = 8_000, 0.10


class Controller:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.bodies: list[bytes] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.content)
        self.entered.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return httpx.Response(200, json={"model": SERVED_SNAPSHOT,
                                         "answers": {"candidate_choice": {"type": "choice", "choice": "m01",
                                                                          "confidence": 0.5}},
                                         "usage": {"input_tokens": 3000, "output_tokens": 20, "cost": 0.001}})


CONTROLLER = Controller()
GATE = EgressGate(transport=httpx.MockTransport(CONTROLLER.handler), credential_resolver=lambda: SENTINEL)


async def science_like(run: Any, send_id: str) -> dict[str, Any]:
    body = {"model": REQUEST_MODEL, "state": {"schema": "prototype_state@0", "candidates": ["m01", "m02"]},
            "questions": {"candidate_choice": {"type": "choice", "instructions": "prototype",
                                               "criteria": {"m01": "Candidate m01.", "m02": "Candidate m02."}}},
            "provider": PROVIDER}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    audit_id = f"eg_{uuid.uuid4().hex}"
    with run._mutation():
        with run._transition():
            run.events.append("jev_send_approved", send_id=send_id, body_sha256=hashlib.sha256(encoded).hexdigest(),
                              approved_by="human")
            run.events.append("budget_reserved", audit_id=audit_id, external_tokens=TOKENS, usd=USD)
            run.budget.charge(external_tokens=TOKENS, usd=USD)
            GATE._audit(run, "prepared", audit_id, scope="science", send_id=send_id, body=body,
                        payload_sha256=hashlib.sha256(encoded).hexdigest(),
                        reservation={"external_tokens": TOKENS, "usd": USD}, transport_invoked=False, sent=False)
            GATE._audit(run, "dispatch_started", audit_id, remaining_wall_s=900.0, transport_invoked=True,
                        sent="unknown")
            started = run.events.append("jev_science_dispatch_started", send_id=send_id, audit_id=audit_id)
        observed: dict[str, int] = {}
        start_http = run.monotonic()
        run._active_started = start_http
        raw, too_large = await GATE._http_request(encoded, GATE.credential_resolver(), 15.0, observed)
        GATE._charge_wall(run, audit_id, start_http)
        data = json.loads(raw)
        usage = _usage(data)
        GATE._audit(run, "response_received", audit_id, http_status=observed["status"],
                    response_sha256=hashlib.sha256(raw).hexdigest(), response_oversized=too_large,
                    served_model=data.get("model"), usage=usage, transport_invoked=True, sent=True)
        unknown, overrun = run._settle_egress(audit_id, usage)
        GATE._audit(run, "settled", audit_id, unknown_axes=unknown, overrun=overrun, transport_invoked=True,
                    sent=True)
        after = [event for event in run.events.read() if event["seq"] > started["seq"]]
        cancelled = any(event["type"] in ("cancel_requested", "run_cancelled") for event in after)
        consent_off = any(event["type"] == "jev_science_consent_changed" and event.get("enabled") is False
                          for event in after)
        late_reason = "run_cancelled" if cancelled else "consent_off" if consent_off else None
        choice = run.store.put("jev_choice", "jev_choice@1",
                               {"schema": "jev_choice@1", "send": {"send_id": send_id, "audit_id": audit_id},
                                "answer": {"choice_alias": data["answers"]["candidate_choice"]["choice"]},
                                "arrival": {"late": late_reason is not None, "late_reason": late_reason}},
                               summary={"send_id": send_id})
        run.events.append("jev_send_outcome", send_id=send_id, status="completed", reason_code=None,
                          audit_id=audit_id, choice_handle=choice.handle, late=late_reason is not None,
                          late_reason=late_reason)
        flag_in_memory = run.cancelled
    return {"choice_handle": choice.handle, "late_reason": late_reason, "run_cancelled_flag_in_memory": flag_in_memory}


proto_app = FastAPI(title="M24 T1 prototype only")


@proto_app.post("/__proto/science/{rid}")
async def proto_science(rid: str) -> dict[str, Any]:
    return await science_like(api_module._run(rid), str(uuid.uuid4()))


proto_app.mount("/", api_module.app)


def scenario(client: TestClient, rid: str, interrupt: str) -> dict[str, Any]:
    source = BACKEND / "tests/fixtures/mini_complex.pdb"
    upload = client.post(f"/runs/{rid}/uploads?filename=mini_complex.pdb", content=source.read_bytes())
    upload_id = upload.json()["upload_id"]
    CONTROLLER.entered.clear()
    CONTROLLER.release.clear()
    result: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: result.update(response=client.post(f"/__proto/science/{rid}")),
                              daemon=True)
    worker.start()
    assert CONTROLLER.entered.wait(5), "transport not entered"
    run = api_module.RUNS[rid]
    out: dict[str, Any] = {}
    t0 = time.monotonic()
    if interrupt == "run_cancel":
        run.cancel()
    elif interrupt == "consent_off":
        with run._transition():
            run.events.append("jev_science_consent_changed", enabled=False, policy="jev_science@1", send_cap=10)
    out["interrupt_seconds"] = round(time.monotonic() - t0, 4)
    timings = {}
    for route in ("/events", "/budget", "/viewer/online"):
        t1 = time.monotonic()
        status = client.get(f"/runs/{rid}{route}").status_code
        timings[route] = {"status": status, "seconds": round(time.monotonic() - t1, 4)}
    busy = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                      "args": {"source": upload_id, "model_index": 0}})
    out["concurrent_get_routes"] = timings
    out["concurrent_mutating_command"] = {"status": busy.status_code, "body": busy.json()}
    CONTROLLER.release.set()
    worker.join(10)
    response = result["response"]
    out["route_status"] = response.status_code
    out["route_result"] = response.json()
    events = list(run.events.read())
    out["event_types_tail"] = [event["type"] + (f":{event['stage']}" if event["type"] == "egress" else "")
                               for event in events[-12:]]
    handle = response.json().get("choice_handle")
    if handle:
        copy_root = WORK / f"copy_{interrupt}"
        (copy_root / rid).mkdir(parents=True)
        shutil.copyfile(WORK / "runs" / rid / "events.jsonl", copy_root / rid / "events.jsonl")
        reopened = new_run(copy_root, run_id=rid, dry_run=False)
        out["events_only_reopen_loads_choice"] = reopened.store.load(handle) == run.store.load(handle)
        out["reopened_cancelled_flag"] = reopened.cancelled
        out["reopened_egress_stop_reason"] = reopened.egress_stop_reason
    return out


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "runs").mkdir(parents=True)
    api_module.RUNS_DIR = WORK / "runs"
    api_module.RUNS.clear()
    try:
        client = TestClient(proto_app, base_url="http://127.0.0.1")
        report: dict[str, Any] = {}
        for interrupt in ("run_cancel", "consent_off", "none"):
            rid = client.post("/runs", json={"dry_run": False}).json()["run_id"]
            report[interrupt] = scenario(client, rid, interrupt)
        cancelled_rid = next(iter(api_module.RUNS))
        run = api_module.RUNS[cancelled_rid]
        with run._mutation():
            later = run.store.put("jev_choice", "jev_choice@1", {"schema": "jev_choice@1", "probe": "after_cancel"})
        report["put_in_new_mutation_after_cancel"] = later.handle.startswith("obj://")
        artifacts = b"".join(path.read_bytes() for path in WORK.rglob("*") if path.is_file())
        report["sentinel_key_in_any_artifact"] = SENTINEL.encode() in artifacts
        prepared = [event["body"] for rid in api_module.RUNS for event in api_module.RUNS[rid].events.read()
                    if event["type"] == "egress" and event.get("stage") == "prepared"]
        report["transport_bodies_equal_prepared_body"] = [
            body == json.dumps(audit, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
            for body, audit in zip(CONTROLLER.bodies, prepared, strict=True)]
        print(json.dumps(report, indent=1, ensure_ascii=False))
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
