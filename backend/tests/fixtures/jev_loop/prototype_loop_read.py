"""PROTOTYPE (M25 T1 measurement only, never product code): one-read loop derivation and its cost on large logs.

Preflight item (e) of the M25 plan. ``--source-run`` is the real ligand run ``prototype_engine_calls.py --keep``
leaves (real M17 jobs, two standalone M18 dockings, one M19 batch row, one job cancelled before start). Its
``events.jsonl`` is copied (events-only reopen), then two LABELLED SYNTHETIC loop events are appended
(``jev_loop_created`` with the 10-candidate pool and the setup of the real standalone M18 job, and one
``jev_loop_compute_approved`` per real docked candidate), so a prototype of the spec 3.2 read can be timed:

* ``derive_one_read``: ONE ``events.read()`` snapshot behind a read view (the M24 ``app._JevReadView`` / M23 pattern:
  ``store``, ``run_id``, ``run_dir`` and ``events.read()`` returning the snapshot), then the job fold
  (``JobQueue(view)._state()``), the M18 reuse index (``docking_batch_inputs.published_m18_results``) and, for every
  pool candidate with an indexed result, ``docking_bundle.validated_result(view, handle)``. Event-log reads are
  counted with a counting wrapper on this ``Run`` instance's ``events.read``.
* ``derive_naive``: the same with ``validated_result(run, handle)`` (each call re-reads the log).

Then the log is padded with LABELLED SYNTHETIC ``object_created`` padding objects (48 KiB, written as log lines like
M24 T1 ``prototype_event_log_read.py``) to about 5 MB and 50 MB and everything is timed again, plus one
``EventLog.append`` (the compute route writes one approval event) and entering/leaving ``Run._mutation()``.
No network, no credential. Runs live under ``--work`` (default ``runs/m25-t1-preflight/read``), deleted at the end
unless ``--keep``. Prints one JSON report.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mw import docking_batch_inputs, docking_bundle, docking_inputs
from mw.core.handles import canonical_json, object_sha
from mw.jobs.queue import JobQueue
from mw.workspace import new_run

OBJECT_BYTES = 48 * 1024
LOOP_ID = "00000000-0000-4000-8000-0000000000dd"


class ReadView:
    """One event-log snapshot for one read (the M24 ``_JevReadView`` shape)."""

    def __init__(self, run: Any) -> None:
        self.store, self.run_id, self.run_dir = run.store, run.run_id, run.run_dir
        self._events = list(run.events.read())
        self.events = self

    def read(self) -> list[dict[str, Any]]:
        return self._events


def timed(fn: Any, repeat: int = 3) -> tuple[dict[str, float], Any]:
    values, result = [], None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        values.append(time.perf_counter() - start)
    return {"median_s": round(statistics.median(values), 4), "max_s": round(max(values), 4)}, result


def loop_setup(run: Any) -> tuple[str, list[str], dict[str, Any]]:
    events = list(run.events.read())
    candidate_set = next(e["handle"] for e in events if e["type"] == "object_created"
                         and e.get("kind") == "ligand_candidate_set")
    ids = [row["id"] for row in run.store.load(candidate_set)["candidates"]]
    first = next(e["job"] for e in events if e["type"] == "job_submitted"
                 and e["job"]["protocol_id"] == docking_bundle.PROTOCOL)
    return candidate_set, ids, first["parameters"]


def key_of(parameters: dict[str, Any], cid: str, pins: dict[str, Any]) -> str:
    request = {**parameters, "ligand": {**parameters["ligand"], "candidate_id": cid}}
    request["parameters"] = {k: v for k, v in request["parameters"].items() if v is not None}
    return docking_bundle.call_key(docking_inputs.validate_arguments(request), pins)


def derive(source: Any, ids: list[str], keys: dict[str, str]) -> dict[str, Any]:
    """Prototype of the spec 3.2 derivation inputs: loop events, job states, reuse index, validated scores."""
    events = list(source.events.read())
    loops = [e for e in events if e["type"].startswith("jev_loop_")]
    jobs = JobQueue(source)._state()
    by_key: dict[str, list[str]] = {}
    for job in jobs.values():
        by_key.setdefault(job["call_key"], []).append(job["status"])
    index = docking_batch_inputs.published_m18_results(events)
    scores = {}
    for cid in ids:
        handle = index.get(keys[cid])
        if handle is not None:
            content = docking_bundle.validated_result(source, handle)
            scores[cid] = content["modes"][0]["score_kcal_mol"] if content["modes"] else None
    return {"loop_events": len(loops), "job_statuses_by_key": {cid: by_key.get(keys[cid]) for cid in ids},
            "validated_scores": scores}


def pad(path: Path, run_id: str, target_bytes: int, start_n: int) -> int:
    seq = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    n = start_n
    with path.open("a", encoding="utf-8") as stream:
        while path.stat().st_size < target_bytes:
            n += 1
            content = {"schema": "synthetic_padding@1", "label": "SYNTHETIC M25 T1 padding, not a result", "n": n,
                       "blob": base64.b64encode(os.urandom(OBJECT_BYTES)).decode("ascii")}
            raw = canonical_json(content)
            handle = f"obj://{run_id}/synthetic_padding/{object_sha('synthetic_padding', 'synthetic_padding@1', raw)}"
            lines = [{"type": "object_created", "handle": handle, "kind": "synthetic_padding",
                      "schema": "synthetic_padding@1", "fmt": "json", "payload_b64": base64.b64encode(raw).decode(),
                      "summary": {}, "produced_by": None, "null_result": False}]
            lines += [{"type": "wall_charged", "seconds": 0.0, "reason": "runtime_overhead"} for _ in range(30)]
            for event in lines:
                seq += 1
                stream.write(json.dumps({"seq": seq, "ts": time.time(), **event}, ensure_ascii=False,
                                        sort_keys=True, allow_nan=False) + "\n")
    return n


def measure(root: Path, rid: str, ids: list[str], keys: dict[str, str]) -> dict[str, Any]:
    run = new_run(root, run_id=rid, dry_run=False)
    path = run.run_dir / "events.jsonl"
    counter = {"reads": 0}
    original = run.events.read

    def counting() -> Any:
        counter["reads"] += 1
        return original()

    run.events.read = counting   # this Run instance only
    out: dict[str, Any] = {"log_bytes": path.stat().st_size, "events": sum(1 for _ in original())}
    out["events_read"], _ = timed(lambda: list(original()))
    counter["reads"] = 0
    out["derive_one_read"], one = timed(lambda: derive(ReadView(run), ids, keys))
    out["reads_per_derive_one_read"] = counter["reads"] / 3
    counter["reads"] = 0
    out["derive_naive"], naive = timed(lambda: derive(run, ids, keys), repeat=1)
    out["reads_per_derive_naive"] = counter["reads"]
    out["same_result"] = canonical_json(one) == canonical_json(naive)
    out["validated_scores_count"] = len(one["validated_scores"])
    out["job_queue_list"], _ = timed(lambda: JobQueue(run).list())
    out["one_append"], _ = timed(lambda: run.events.append("wall_charged", seconds=0.0, reason="runtime_overhead"))

    def mutation() -> None:
        with run._mutation():
            pass

    out["mutation_enter_exit"], _ = timed(mutation, repeat=2)
    del run.events.read
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=REPO / "runs/m25-t1-preflight/read")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    rid = args.source_run.name
    try:
        (args.work / rid).mkdir()
        shutil.copyfile(args.source_run / "events.jsonl", args.work / rid / "events.jsonl")
        run = new_run(args.work, run_id=rid, dry_run=False)
        candidate_set, ids, parameters = loop_setup(run)
        pins = docking_bundle.require_ready()
        keys = {cid: key_of(parameters, cid, pins) for cid in ids}
        index = docking_batch_inputs.published_m18_results(list(run.events.read()))
        docked = [cid for cid in ids if keys[cid] in index]
        run.events.append("jev_loop_created", loop_id=LOOP_ID, branch="ligand",
                          pool={"source": {"handle": candidate_set, "schema": "ligand_candidate_set@1"},
                                "structure": None, "candidates": ids, "filter": None},
                          goal="explore", loop_seed=1, iteration_cap=5, setup={"synthetic": "M25 T1 label"},
                          setup_sha256="0" * 64, pins=pins)
        for number, cid in enumerate(docked, 1):
            run.events.append("jev_loop_compute_approved", loop_id=LOOP_ID, iteration=number, step="ligand_dock",
                              candidate_ref=cid, decided_by="human", proposal_handle=None, call_key=keys[cid],
                              units=1, approved_by="human")
        report: dict[str, Any] = {"pool": len(ids), "candidates_with_stored_result": len(docked)}
        report["source_log"] = measure(args.work, rid, ids, keys)
        n = pad(args.work / rid / "events.jsonl", rid, 5 * 1024 * 1024, 0)
        report["padded_5MB"] = measure(args.work, rid, ids, keys)
        pad(args.work / rid / "events.jsonl", rid, 50 * 1024 * 1024, n)
        report["padded_50MB"] = measure(args.work, rid, ids, keys)
        print(json.dumps(report, indent=1))
    finally:
        if not args.keep:
            shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
