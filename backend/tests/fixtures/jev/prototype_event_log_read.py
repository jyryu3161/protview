"""PROTOTYPE (M24 T1 measurement only): cost of one event-log read for the planned status / preview reads.

1. Read-only timing of the largest existing local log, if given (``--real <events.jsonl>``): ``EventLog.read()`` only
   (shared lock, no Run is opened, nothing is written).
2. Synthetic logs of about 5 MB and 50 MB in ``_work_eventlog`` next to this file (deleted at the end): valid
   ``object_created`` events (48 KiB objects, the bulk of real logs) plus small events, then the costs of
   ``EventLog.read()``, one ``EventLog.append()`` (it re-reads the whole log to number the event), opening a ``Run``
   (store rebuild + refresh + egress reconcile), entering/leaving ``Run._mutation()``, and two prototype reads shaped
   like the spec 7 ``jev/status`` (one read, count consent / dispatch events) and ``jev/preview`` (one read + one
   object load + body encode). Synthetic content is labelled; no network. Prints one JSON report.
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
BACKEND = HERE.parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mw.core.events import EventLog
from mw.core.handles import canonical_json, object_sha
from mw.workspace import new_run

WORK = HERE / "_work_eventlog"
OBJECT_BYTES = 48 * 1024


def timed(fn: Any, repeat: int = 3) -> dict[str, float]:
    values = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        values.append(time.perf_counter() - start)
    return {"median_s": round(statistics.median(values), 4), "max_s": round(max(values), 4)}


def synthetic_log(run_id: str, target_bytes: int) -> Path:
    run_dir = WORK / run_id
    run = new_run(WORK, run_id=run_id, dry_run=False)   # writes run_started with the real config
    del run
    path = run_dir / "events.jsonl"
    seq = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    with path.open("a", encoding="utf-8") as stream:
        n = 0
        while path.stat().st_size < target_bytes:
            n += 1
            content = {"schema": "synthetic_padding@1", "label": "SYNTHETIC M24 T1 padding", "n": n,
                       "blob": base64.b64encode(os.urandom(OBJECT_BYTES)).decode("ascii")}
            raw = canonical_json(content)
            handle = f"obj://{run_id}/synthetic_padding/{object_sha('synthetic_padding', 'synthetic_padding@1', raw)}"
            events = [{"type": "object_created", "handle": handle, "kind": "synthetic_padding",
                       "schema": "synthetic_padding@1", "fmt": "json",
                       "payload_b64": base64.b64encode(raw).decode("ascii"), "summary": {}, "produced_by": None,
                       "null_result": False}]
            events += [{"type": "wall_charged", "seconds": 0.001, "reason": "runtime_overhead"} for _ in range(30)]
            for event in events:
                seq += 1
                stream.write(json.dumps({"seq": seq, "ts": time.time(), **event}, ensure_ascii=False,
                                        sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
    return path


def measure_synthetic(label: str, target: int) -> dict[str, Any]:
    run_id = f"m24_t1_{label}"
    path = synthetic_log(run_id, target)
    log = EventLog(path)
    out: dict[str, Any] = {"bytes": path.stat().st_size, "events": sum(1 for _ in log.read())}
    out["events_read"] = timed(lambda: list(log.read()))
    start = time.perf_counter()
    run = new_run(WORK, run_id=run_id, dry_run=False)
    out["run_open_first_s"] = round(time.perf_counter() - start, 4)
    out["run_open_again"] = timed(lambda: new_run(WORK, run_id=run_id, dry_run=False), repeat=2)

    def mutation() -> None:
        with run._mutation():
            pass
    out["mutation_enter_exit"] = timed(mutation, repeat=2)
    out["one_append"] = timed(lambda: run.events.append("wall_charged", seconds=0.0, reason="runtime_overhead"))
    handle = next(event["handle"] for event in log.read() if event["type"] == "object_created")

    def status_read() -> dict[str, int]:
        events = list(run.events.read())
        return {"consent": sum(e["type"] == "jev_science_consent_changed" for e in events),
                "dispatch": sum(e["type"] == "jev_science_dispatch_started" for e in events)}

    def preview_read() -> int:
        list(run.events.read())
        content = run.store.load(handle)
        return len(json.dumps({"state": content["n"]}, sort_keys=True, separators=(",", ":")).encode())
    out["status_like_read"] = timed(status_read)
    out["preview_like_read"] = timed(preview_read)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", type=Path, default=None, help="existing events.jsonl to time read-only")
    args = parser.parse_args()
    report: dict[str, Any] = {}
    if args.real is not None:
        real = args.real.resolve()
        if not (real.parent / "events.lock").exists():
            report["real"] = {"skipped": "no events.lock next to the log (would create one)"}
        else:
            log = EventLog(real)
            report["real"] = {"bytes": real.stat().st_size, "events": sum(1 for _ in log.read()),
                              "events_read": timed(lambda: list(log.read()))}
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    try:
        report["synthetic_5MB"] = measure_synthetic("5mb", 5 * 1024 * 1024)
        report["synthetic_50MB"] = measure_synthetic("50mb", 50 * 1024 * 1024)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
