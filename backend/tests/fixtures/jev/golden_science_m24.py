"""GOLDEN recorder (M25 T1): the M24 science-send bytes BEFORE any M25 change, through the unmodified product API.

``golden_egress_events.json`` (M24 T1) pins only the M3 ``request_jev`` and M8 ``request_viewer`` gates. This file pins
the M24 science path that M25 extends (spec .dryforge/spec.md 11, handoff absolute condition 11): the projection tool
through ``POST /runs/{id}/commands`` (``build_jev_projection``) and the stored ``jev_projection@1``, ``POST
/jev/consent``, ``POST /jev/preview`` (``jev_preview@1``), ``POST /jev/sends`` (``jev_send@1``: completed, rejected,
failed, replayed, conflicts), ``GET /jev/sends`` and ``/jev/sends/{send_id}``, the stored ``jev_choice@1``, every
event the steps append (the science audit rows included), ``GET /jev/status``, the ``jev_choice`` method report and
``/capabilities`` ``methods.jev_choice``.

Inputs (fixed run ids, so every content handle is the same in every recording): public 1UBQ (M20 set for positions
MET1, ILE44, LYS48) in a normal and a dry-run run, and the labelled synthetic methacetin M17 run of
``ligand_job_fixture.standard_run`` (real RDKit jobs). Since M26 T1 the M20 set is the stored v1 content of
``fixtures/reaction/t1/m20-v1-candidate-set-<run id>.json`` (made once by the unmodified v1 tool), put with
``store.put`` inside the same ``Run.call`` envelope the tool call had, so the template keeps its event count and every
later event sequence number (a bare ``store.put`` moves the report's absolute ``*_event_seq`` values by -4); the M20
implementation is not run (M20 v2 builds other sets). Each case is an events-only copy of its template served by the
product app with ``SCIENCE_GATE`` replaced by an ``httpx.MockTransport`` gate and an inert sentinel credential
(fixture replies, never provider output); nothing opens a socket or reads ``.env``.

Volatile values are reduced the way ``prototype_golden_egress.py`` does, but keeping every other byte: the random
audit / call / attempt ids and the handles of objects whose content holds one (``jev_choice``, report objects) become
ordered markers (``<audit_id#1>``, ``<handle:jev_choice#1>``), times, sequence numbers and elapsed seconds become
``<number>``, and ``object_created.payload_b64`` of those objects becomes ``<payload_b64>`` (their content is recorded
separately, reduced the same way).

``--write`` rewrites ``golden_science_m24.json`` after checking that two fresh recordings are identical; ``--check``
exits 0 only if a fresh recording equals the stored file. Runs live under ``--work`` (default a new folder under the
Git-excluded ``runs/``), deleted at the end. Not product code.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
for extra in (str(BACKEND), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import httpx
from fastapi.testclient import TestClient
from ligand_job_fixture import standard_run

from mw import jev_constants as J
from mw import jev_projection as P
from mw.api import app as api_module
from mw.egress.gate import EgressGate
from mw.workspace import new_run

GOLDEN = HERE / "golden_science_m24.json"
FIX = TESTS / "fixtures"
V1_SETS = FIX / "reaction" / "t1"   # stored M20 v1 candidate sets (SYNTHETIC-PROVENANCE-t1.md)
SENTINEL = "sentinel_m25_t1_golden_science_key"
USAGE = {"input_tokens": 3000, "output_tokens": 20, "cost": 0.001}
JSON = {"content-type": "application/json"}
SEND = {n: f"00000000-0000-4000-8000-{n:012d}" for n in range(1, 10)}
VOLATILE_IDS = ("audit_id", "call_id", "root_call_id", "attempt_id", "produced_by")
NUMBER_KEYS = ("ts", "seq", "approved_event_seq", "outcome_event_seq", "created_seq", "last_seq", "seconds",
               "duration_s", "remaining_wall_s", "elapsed_s", "started_at", "finished_at", "time_utc")
TEXT_LIMIT = 200   # longer strings (bodies, markdown, stored object JSON) go to the shared ``texts`` table once
TOKEN_KINDS = ("jev_choice", "method_report_manifest", "report_markdown")


def res(seq_auth: int, resname: str) -> dict[str, Any]:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq_auth, "icode": "", "resname": resname}


# ----------------------------------------------------------------------------------------------- templates
def stored_v1_set(run: Any, args: dict[str, Any]) -> str:
    """The ``generate_mutation_candidates`` call of the template, its result taken from the stored v1 fixture."""
    fixture = json.loads((V1_SETS / f"m20-v1-candidate-set-{run.run_id}.json").read_text(encoding="utf-8"))
    content = fixture["content"]

    def put_stored(ctx: Any, structure: str, **params: Any) -> Any:
        assert structure == content["structure"]["handle"], structure
        assert all(params[key] == value for key, value in content["parameters"].items() if key in params), params
        summary = {"structure": structure, **content["counts"], "null_result": content["null_result"]}
        return ctx.store.put("mutation_candidate_set", "mutation_candidate_set@1", content, produced_by=ctx.call_id,
                             summary=summary, null_result=content["null_result"])

    run.registry.impls["generate_mutation_candidates"] = put_stored   # this run's own registry only
    handle = run.call("generate_mutation_candidates", args).handle
    assert handle == fixture["handle"], handle
    return handle


def templates(root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for name, dry in (("mutation", False), ("dry", True)):
        run = new_run(root / name, run_id=f"golden_m24_{name}", dry_run=dry)
        loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
        prepared = run.call("prepare_structure", {"structure": loaded}).handle
        source = stored_v1_set(run, {
            "structure": prepared, "sources": {"pocket": None, "ligand_shell": None,
                                               "residues": [res(1, "MET"), res(44, "ILE"), res(48, "LYS")]}})
        out[name] = {"root": root / name, "run_id": run.run_id, "dry_run": dry, "kind": "mutation",
                     "source": source, "candidates": [30, 3, 0], "other": [1, 2]}
    made = standard_run(root / "ligand", "golden_m24_ligand")
    ids = [row["id"] for row in made["run"].store.load(made["candidate_set"])["candidates"]]
    out["ligand"] = {"root": root / "ligand", "run_id": "golden_m24_ligand", "dry_run": False, "kind": "ligand",
                     "source": made["candidate_set"], "candidates": [ids[3], ids[1], ids[2]], "other": ids[:2]}
    return out


def clone(template: dict[str, Any], root: Path) -> None:
    target = root / template["run_id"]
    target.mkdir(parents=True)
    shutil.copyfile(template["root"] / template["run_id"] / "events.jsonl", target / "events.jsonl")
    new_run(root, run_id=template["run_id"], dry_run=template["dry_run"])


# ----------------------------------------------------------------------------------------------- reduction
class Reducer:
    """Ordered markers for random ids and for handles of objects whose content holds one."""

    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}

    def add(self, value: Any, label: str) -> None:
        if isinstance(value, str) and value and value not in self.tokens:
            count = len({marker for marker in self.tokens.values() if marker.startswith(f"<{label}#")})
            self.tokens[value] = f"<{label}#{count + 1}>"
            # the Markdown report escapes the same characters as ``mw.reports._md`` (read-only copy of its rule)
            self.tokens.setdefault(re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value), self.tokens[value])

    def learn(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            for key in VOLATILE_IDS:
                self.add(event.get(key), key)
            if event["type"] == "object_created" and event.get("kind") in TOKEN_KINDS:
                self.add(event["handle"], f"handle:{event['kind']}")
                self.add(event["handle"].rsplit("/", 1)[-1], f"sha256:{event['kind']}")   # bare hash in reports

    def _payload(self, event: dict[str, Any]) -> str:
        """Object payloads are pinned by the SHA-256 of their bytes; a payload holding a random id is a marker."""
        if self.tokens.get(event.get("handle")):
            return "<payload_b64>"
        return "<payload sha256 " + hashlib.sha256(base64.b64decode(event["payload_b64"])).hexdigest() + ">"

    def __call__(self, value: Any, key: str | None = None) -> Any:
        if key == "wall_clock_s" and isinstance(value, dict) and "used" in value:   # elapsed activity time
            return {k: ("<number>" if k == "used" else self(v, k)) for k, v in value.items()}
        if isinstance(value, dict):
            return {k: (self._payload(value) if k == "payload_b64" else self(v, k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self(item) for item in value]
        if key in NUMBER_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
            return "<number>"
        if isinstance(value, str):
            for token in sorted(self.tokens, key=len, reverse=True):
                value = value.replace(token, self.tokens[token])
        return value


# ----------------------------------------------------------------------------------------------- one case
def reply(choice: str, *, model: str = J.SERVED_SNAPSHOT, usage: Any = USAGE, status: int = 200,
          **extra: Any) -> httpx.Response:
    body: dict[str, Any] = {"model": model, "answers": {J.QUESTION_KEY: {"type": "choice", "choice": choice, **extra}}}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status, json=body)


def case(work: Path, name: str, template: dict[str, Any], steps: list[tuple[str, Any]], *,
         responder: Any = None, key: Any = SENTINEL) -> dict[str, Any]:
    root = work / "cases" / name
    clone(template, root)
    calls = {"transport": 0, "credential": 0}
    received: list[bytes] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls["transport"] += 1
        received.append(request.content)
        return responder(request)

    def resolve() -> Any:
        calls["credential"] += 1
        return key

    api_module.RUNS_DIR = root
    api_module.RUNS.clear()
    api_module.SCIENCE_GATE = EgressGate(transport=httpx.MockTransport(handle), credential_resolver=resolve)
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = template["run_id"]
    log = root / rid / "events.jsonl"
    before = len(log.read_text(encoding="utf-8").splitlines())
    state: dict[str, Any] = {}
    previews: list[bytes] = []
    exchanges = []
    for step, arg in steps:
        if step == "consent":
            response = client.post(f"/runs/{rid}/jev/consent", json={"enabled": arg})
        elif step == "project":
            response = client.post(f"/runs/{rid}/commands", json={"tool": J.TOOL, "args": {
                "source": template["source"], "candidates": template[arg]}})
            if response.status_code == 200:
                state[arg] = response.json()["handle"]["handle"]
        elif step == "preview":
            response = client.post(f"/runs/{rid}/jev/preview", json={"projection": state[arg]}, headers=JSON)
            if response.status_code == 200:
                state[f"sha:{arg}"] = response.json()["body_sha256"]
                previews.append(response.json()["body"].encode("ascii"))
        elif step == "send":
            which, number, sha = arg
            response = client.post(f"/runs/{rid}/jev/sends", headers=JSON, json={
                "send_id": SEND[number], "projection": state[which],
                "body_sha256": state[f"sha:{which}"] if sha is None else sha, "confirm": J.CONFIRM})
            if response.status_code == 200 and response.json().get("choice_handle"):
                state["choice"] = response.json()["choice_handle"]
        elif step == "list":
            response = client.get(f"/runs/{rid}/jev/sends")
        elif step == "detail":
            response = client.get(f"/runs/{rid}/jev/sends/{SEND[arg]}")
        elif step == "status":
            response = client.get(f"/runs/{rid}/jev/status")
        elif step == "report":
            response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": state["choice"]})
        else:
            raise ValueError(step)
        exchanges.append({"step": step, "arg": arg if step != "send" else list(arg[:2]),
                          "http_status": response.status_code, "response": response.json()})
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()[before:]]
    reduce = Reducer()
    reduce.learn(events)
    run = new_run(root, run_id=rid, dry_run=template["dry_run"])
    stored = {}
    for event in events:
        if event["type"] == "object_created" and event.get("kind") in ("jev_projection", "jev_choice"):
            content = reduce(run.store.load(event["handle"]))
            stored[reduce(event["handle"])] = json.dumps(content, ensure_ascii=False, sort_keys=True,
                                                         separators=(",", ":"))
    artifacts = b"".join(path.read_bytes() for path in (root / rid).rglob("*") if path.is_file())
    return {"exchanges": reduce(exchanges), "events": reduce(events), "stored_objects": stored,
            "transport_calls": calls["transport"], "credential_reads": calls["credential"],
            "transport_bytes_equal_a_preview_body": [body in previews for body in received],
            "prepared_audit_body_equal_transport_bytes": [P.canonical_ascii(event["body"]) in received
                                                          for event in events if event.get("stage") == "prepared"],
            "sentinel_key_in_any_artifact": SENTINEL.encode() in artifacts}


def compact(value: Any, texts: dict[str, str], key: str | None = None) -> Any:
    """Long strings move to ``texts`` (keyed by SHA-256, stored once); the ``prepared`` audit's request ``body`` object
    becomes its exact request bytes (the same text as the preview ``body`` string)."""
    if isinstance(value, dict) and value.get("type") == "egress" and value.get("stage") == "prepared":
        value = {**value, "body": P.canonical_ascii(value["body"]).decode("ascii")}
    if isinstance(value, dict):
        return {k: compact(v, texts, k) for k, v in value.items()}
    if isinstance(value, list):
        return [compact(item, texts) for item in value]
    if isinstance(value, str) and len(value) > TEXT_LIMIT:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        texts[digest] = value
        return f"<text sha256:{digest}>"
    return value


def record(work: Path) -> dict[str, Any]:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    saved = (api_module.RUNS_DIR, api_module.SCIENCE_GATE)
    try:
        made = templates(work / "templates")
        lig, mut, dry = made["ligand"], made["mutation"], made["dry"]
        probs = {"c01": 0.4321, "c02": 0.1234}
        full = [("consent", True), ("project", "candidates"), ("preview", "candidates"),
                ("send", ("candidates", 1, None)), ("send", ("candidates", 1, None)), ("list", None),
                ("detail", 1), ("status", None), ("report", None)]
        cases = {
            "ligand_completed": case(work, "ligand_completed", lig, full, responder=lambda r: reply(
                "c02", confidence=0.6789, probabilities=probs)),
            "mutation_completed_and_conflicts": case(work, "mutation_completed_and_conflicts", mut, [
                *full, ("project", "other"), ("preview", "other"), ("send", ("other", 1, None)),
                ("send", ("other", 2, "0" * 64)), ("list", None)], responder=lambda r: reply("m01")),
            "mutation_completed_usage_missing_then_egress_stopped": case(
                work, "mutation_completed_usage_missing_then_egress_stopped", mut, [
                    ("consent", True), ("project", "candidates"), ("preview", "candidates"),
                    ("send", ("candidates", 1, None)), ("status", None), ("preview", "candidates"),
                    ("send", ("candidates", 2, None)), ("list", None)], responder=lambda r: reply("m02", usage=None)),
            "mutation_rejected_consent_off": case(work, "mutation_rejected_consent_off", mut, [
                ("project", "candidates"), ("preview", "candidates"), ("send", ("candidates", 1, None)),
                ("detail", 1), ("status", None)], responder=lambda r: reply("m01")),
            "mutation_rejected_missing_credential": case(work, "mutation_rejected_missing_credential", mut, [
                ("consent", True), ("project", "candidates"), ("preview", "candidates"),
                ("send", ("candidates", 1, None)), ("detail", 1)], responder=lambda r: reply("m01"), key=None),
            "mutation_failed_http_500": case(work, "mutation_failed_http_500", mut, [
                ("consent", True), ("project", "candidates"), ("preview", "candidates"),
                ("send", ("candidates", 1, None)), ("detail", 1), ("status", None)],
                responder=lambda r: httpx.Response(500, json={"error": "fixture"})),
            "mutation_failed_response_invalid": case(work, "mutation_failed_response_invalid", mut, [
                ("consent", True), ("project", "candidates"), ("preview", "candidates"),
                ("send", ("candidates", 1, None)), ("detail", 1)], responder=lambda r: reply("m99")),
            "mutation_failed_model_mismatch": case(work, "mutation_failed_model_mismatch", mut, [
                ("consent", True), ("project", "candidates"), ("preview", "candidates"),
                ("send", ("candidates", 1, None)), ("detail", 1)],
                responder=lambda r: reply("m01", model="typesafe/other-model")),
            "dry_run_consent_and_preview": case(work, "dry_run_consent_and_preview", dry, [
                ("consent", True), ("project", "candidates"), ("preview", "candidates"), ("status", None)],
                responder=lambda r: reply("m01")),
        }
        api_module.RUNS_DIR = work / "capabilities"
        api_module.RUNS.clear()
        capability = TestClient(api_module.app, base_url="http://127.0.0.1").get("/capabilities").json()
        texts: dict[str, str] = {}
        cases = compact(cases, texts)
        return {"_fixture": ("GOLDEN (M25 T1): M24 science-send API answers, stored objects and appended events made "
                             "by the unmodified M24 code with a scripted MockTransport and an inert sentinel "
                             "credential; random ids, content handles that hold them, times, sequence numbers and "
                             "elapsed seconds reduced to ordered markers. Not provider output."),
                "capability_jev_choice": capability["methods"]["jev_choice"], "cases": cases,
                "texts": dict(sorted(texts.items()))}
    finally:
        api_module.RUNS_DIR, api_module.SCIENCE_GATE = saved
        api_module.RUNS.clear()
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    parser.add_argument("--work", type=Path, default=REPO / "runs" / f"golden-science-m24-{os.getpid()}")
    args = parser.parse_args()
    fresh = record(args.work)
    if args.write:
        if record(args.work) != fresh:
            print("two fresh recordings differ; golden would not be stable", file=sys.stderr)
            return 1
        GOLDEN.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN.name}")
        return 0
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if stored != fresh:
        for name in sorted(set(stored.get("cases", {})) | set(fresh["cases"])):
            if stored.get("cases", {}).get(name) != fresh["cases"].get(name):
                print(f"case differs: {name}", file=sys.stderr)
        if stored.get("capability_jev_choice") != fresh["capability_jev_choice"]:
            print("capability_jev_choice differs", file=sys.stderr)
        print("golden_science_m24.json differs from a fresh recording", file=sys.stderr)
        return 1
    print("golden_science_m24.json matches a fresh recording")
    return 0


if __name__ == "__main__":
    sys.exit(main())
