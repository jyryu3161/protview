#!/usr/bin/env python3
"""Read-only M10/M9 events-only replay baseline and comparison helper.

This file is intentionally outside the repository. It sends only loopback GETs
and reads existing files. The operator owns stopping/restarting services and
copying only events into a distinct replay root.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RUN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
OBJECT_RE = re.compile(r"[0-9a-f]{64}\.[a-z0-9]{1,12}\Z")
SOURCE_KINDS = {"structure", "prepared_structure", "openmm_minimized_structure"}
RESULT_KINDS = {"atom_distance", "rigid_alignment"}
DEFAULT_ALLOWED = {"viewer_session_created", "viewer_scene_updated"}
OPTIONAL_VIEWER_EVENTS = {
    "viewer_intent_requested", "viewer_intent_outcome", "viewer_intent_cancelled",
    "viewer_dispatch_started", "viewer_command_ack",
}
FORBIDDEN_AFTER = {
    "object_created", "method_report_created", "report_created", "upload_received",
    "egress", "llm_call", "cache_hit", "budget_reserved", "wall_charged",
    "approval_requested", "approval_resolved", "egress_budget_settled",
    "viewer_scene_admitted", "viewer_figure_admitted", "viewer_scene_saved", "viewer_figure_saved",
}
FORBIDDEN_PREFIXES = ("tool_", "job_", "workflow_")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def summary(raw: bytes) -> dict:
    return {"bytes": len(raw), "sha256": sha(raw)}


def checked_base(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("base URL must be a plain loopback HTTP origin")
    return value.rstrip("/")


def checked_run(root: Path, run_id: str) -> Path:
    if not RUN_RE.fullmatch(run_id):
        raise ValueError(f"invalid run ID: {run_id!r}")
    root = root.resolve(strict=True)
    target = root / run_id
    if target.is_symlink() or not target.is_dir() or target.resolve(strict=True).parent != root:
        raise ValueError(f"missing or unsafe run directory: {run_id}")
    return target


def get(opener: urllib.request.OpenerDirector, base: str, path: str, params: dict | None = None) -> tuple[bytes, object]:
    query = "?" + urllib.parse.urlencode(params) if params else ""
    url = base + path + query
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json, */*"})
    try:
        with opener.open(request, timeout=45) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError(f"oversize GET response: {path}")
            return raw, json.loads(raw) if response.headers.get_content_type() == "application/json" else None
    except urllib.error.HTTPError as exc:
        detail = exc.read(500)
        raise RuntimeError(f"GET {path} returned {exc.code}: {detail!r}") from exc


def capture_get(opener, base: str, calls: dict, path: str, params: dict | None = None) -> object:
    query = "?" + urllib.parse.urlencode(params) if params else ""
    key = path + query
    raw, parsed = get(opener, base, path, params)
    calls[key] = summary(raw)
    return parsed


def object_files(run_dir: Path) -> dict[str, dict]:
    directory = run_dir / "objects"
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"object directory not restored: {run_dir}")
    files = {}
    for path in sorted(directory.iterdir()):
        if not OBJECT_RE.fullmatch(path.name):
            raise ValueError(f"unexpected object directory entry: {path}")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"unsafe object file: {path}")
        files[path.name] = summary(path.read_bytes())
    return files


def read_events(path: Path) -> tuple[bytes, list[dict]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe events file: {path}")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("events file has an incomplete final line")
    rows = [json.loads(line) for line in raw.splitlines()]
    for index, row in enumerate(rows, 1):
        if (type(row) is not dict or type(row.get("seq")) is not int or
                row["seq"] != index or type(row.get("type")) is not str):
            raise ValueError(f"invalid event sequence at row {index}")
    return raw, rows


def all_pages(opener, base: str, calls: dict, path: str, maximum: int) -> list[dict]:
    rows = []
    for offset in range(0, maximum + 1, 100):
        page = capture_get(opener, base, calls, path, {"offset": offset, "limit": 100})
        if type(page) is not dict or type(page.get("rows")) is not list or type(page.get("total")) is not int:
            raise ValueError(f"malformed paginated response: {path}")
        rows.extend(page["rows"])
        if len(rows) >= page["total"]:
            if len(rows) != page["total"]:
                raise ValueError(f"inconsistent pagination: {path}")
            return rows
    raise ValueError(f"too many rows at {path}")


def capture_run(root: Path, base: str, run_id: str, opener, max_atoms: int) -> dict:
    run_dir = checked_run(root, run_id)
    before, events = read_events(run_dir / "events.jsonl")
    prefix = f"/runs/{run_id}"
    calls: dict[str, dict] = {}
    # These reads also trigger normal object-index reconstruction on a fresh
    # events-only replay root. No command/job/report POST is issued here.
    scenes = all_pages(opener, base, calls, prefix + "/viewer/scenes", 100)
    figures = all_pages(opener, base, calls, prefix + "/viewer/figures", 100)
    reports = capture_get(opener, base, calls, prefix + "/reports")
    capture_get(opener, base, calls, prefix + "/budget")
    capture_get(opener, base, calls, prefix + "/jobs")
    capture_get(opener, base, calls, prefix + "/viewer/online")
    capture_get(opener, base, calls, prefix + "/viewer/intents")
    if type(reports) is not list:
        raise ValueError("report list is malformed")
    for row in scenes:
        capture_get(opener, base, calls, prefix + "/viewer/scenes/selected", {"handle": row["handle"]})
    for row in figures:
        handle = row["handle"]
        capture_get(opener, base, calls, prefix + "/viewer/figures/selected", {"handle": handle})
        for fmt in ("png", "json"):
            capture_get(opener, base, calls, prefix + "/viewer/figures/download", {"handle": handle, "format": fmt})
    for row in reports:
        handle = row["handle"]
        capture_get(opener, base, calls, prefix + "/reports/selected", {"handle": handle})
        for fmt in ("markdown", "json"):
            capture_get(opener, base, calls, prefix + "/reports/download", {"handle": handle, "format": fmt})
    created = [event for event in events if event["type"] == "object_created"]
    kind_by_handle = {event["handle"]: event["kind"] for event in created}
    for handle, kind in sorted(kind_by_handle.items()):
        if kind in RESULT_KINDS:
            capture_get(opener, base, calls, prefix + "/objects/measurement", {"handle": handle})
        if kind in SOURCE_KINDS:
            capture_get(opener, base, calls, prefix + "/structures/bytes", {"handle": handle})
            seen = 0
            while True:
                catalog = capture_get(opener, base, calls, prefix + "/structures/atoms",
                                      {"handle": handle, "offset": seen, "limit": 500})
                if type(catalog) is not dict or type(catalog.get("rows")) is not list or type(catalog.get("total")) is not int:
                    raise ValueError(f"malformed atom catalog for {handle}")
                seen += len(catalog["rows"])
                if seen == catalog["total"]:
                    break
                if seen > catalog["total"] or not catalog["rows"] or seen >= max_atoms:
                    raise ValueError(f"atom catalog exceeded configured bound for {handle}")
    after, post_read_events = read_events(run_dir / "events.jsonl")
    if after != before or post_read_events != events:
        raise ValueError(f"GETs appended or changed events for {run_id}")
    files = object_files(run_dir)
    return {"run_id": run_id, "events": {**summary(before), "count": len(events),
            "type_counts": dict(sorted(collections.Counter(e["type"] for e in events).items()))},
            "objects": files, "api_gets": dict(sorted(calls.items())),
            "source_handles": sorted(handle for handle, kind in kind_by_handle.items() if kind in SOURCE_KINDS),
            "measurement_handles": sorted(handle for handle, kind in kind_by_handle.items() if kind in RESULT_KINDS),
            "report_handles": sorted(row["handle"] for row in reports),
            "figure_handles": sorted(row["handle"] for row in figures),
            "scene_handles": sorted(row["handle"] for row in scenes)}


def verify_events(before: dict, now_raw: bytes, now_rows: list[dict], allowed: set[str]) -> dict:
    length = before["bytes"]
    old_count = before["count"]
    findings = []
    if len(now_raw) < length or sha(now_raw[:length]) != before["sha256"]:
        findings.append("original event-byte prefix changed")
    appended = now_rows[old_count:]
    types = collections.Counter(e["type"] for e in appended)
    for event in appended:
        kind = event["type"]
        if kind in FORBIDDEN_AFTER or kind.startswith(FORBIDDEN_PREFIXES) or kind not in allowed:
            findings.append(f"forbidden appended event seq={event['seq']} type={kind}")
    return {"ok": not findings, "findings": findings, "original_count": old_count,
            "current_count": len(now_rows), "appended_types": dict(sorted(types.items())),
            "current_sha256": sha(now_raw)}


def verify_run(before: dict, after: dict, current_events: tuple[bytes, list[dict]], allowed: set[str]) -> dict:
    mismatches = []
    if (summary(current_events[0]) != {key: after["events"][key] for key in ("bytes", "sha256")} or
            len(current_events[1]) != after["events"]["count"]):
        mismatches.append({"field": "events", "reason": "events changed during API snapshot"})
    for field in ("objects", "api_gets", "source_handles", "measurement_handles", "report_handles",
                  "figure_handles", "scene_handles"):
        if before[field] != after[field]:
            old, new = before[field], after[field]
            if isinstance(old, dict):
                changed = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
                mismatches.append({"field": field, "changed": changed})
            else:
                mismatches.append({"field": field, "before": old, "after": new})
    event_check = verify_events(before["events"], *current_events, allowed)
    return {"ok": not mismatches and event_check["ok"], "mismatches": mismatches,
            "events": event_check, "objects_checked": len(before["objects"]),
            "api_gets_checked": len(before["api_gets"])}


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".replay-probe-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def self_check() -> None:
    first = b'{"seq":1,"type":"run_started"}\n'
    entry = b'{"seq":2,"type":"viewer_session_created"}\n'
    baseline = {**summary(first), "count": 1}
    good = verify_events(baseline, first + entry, [
        {"seq": 1, "type": "run_started"}, {"seq": 2, "type": "viewer_session_created"}], DEFAULT_ALLOWED)
    bad = verify_events(baseline, first + b'{"seq":2,"type":"tool_called"}\n', [
        {"seq": 1, "type": "run_started"}, {"seq": 2, "type": "tool_called"}], DEFAULT_ALLOWED)
    changed = verify_events(baseline, b'X' + first[1:], [{"seq": 1, "type": "run_started"}], DEFAULT_ALLOWED)
    assert good["ok"] and not bad["ok"] and not changed["ok"]
    assert not verify_events(baseline, first + b'{"seq":2,"type":"object_created"}\n', [
        {"seq": 1, "type": "run_started"}, {"seq": 2, "type": "object_created"}], DEFAULT_ALLOWED)["ok"]
    assert checked_base("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    try:
        checked_base("https://example.org")
    except ValueError:
        pass
    else:
        raise AssertionError("remote endpoint accepted")
    print(json.dumps({"ok": True, "checks": 6}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("self-check")
    for name in ("snapshot", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--runs-root", type=Path, required=True)
        cmd.add_argument("--base-url", required=True)
        cmd.add_argument("--run-id", action="append", required=True)
        cmd.add_argument("--output", type=Path, required=True)
        cmd.add_argument("--max-atoms", type=int, default=200_000)
        if name == "verify":
            cmd.add_argument("--baseline", type=Path, required=True)
            cmd.add_argument("--allow-event", action="append", default=[])
    args = parser.parse_args()
    if args.mode == "self-check":
        self_check()
        return 0
    base = checked_base(args.base_url)
    if args.max_atoms < 1 or args.max_atoms > 200_000:
        raise ValueError("max-atoms must be in 1..200000")
    if len(set(args.run_id)) != len(args.run_id):
        raise ValueError("duplicate run ID")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if args.mode == "snapshot":
        result = {"schema": "protview_replay_probe@1", "runs": {rid: capture_run(
            args.runs_root, base, rid, opener, args.max_atoms) for rid in args.run_id}}
        atomic_json(args.output, result)
        print(json.dumps({"ok": True, "runs": args.run_id, "output": str(args.output)}))
        return 0
    baseline = json.loads(args.baseline.read_text())
    if baseline.get("schema") != "protview_replay_probe@1" or set(baseline.get("runs", {})) != set(args.run_id):
        raise ValueError("baseline schema or run IDs do not match")
    allowed = DEFAULT_ALLOWED | set(args.allow_event)
    if not set(args.allow_event) <= OPTIONAL_VIEWER_EVENTS:
        raise ValueError("--allow-event must name a known viewer observation event")
    reports = {}
    for rid in args.run_id:
        after = capture_run(args.runs_root, base, rid, opener, args.max_atoms)
        events = read_events(checked_run(args.runs_root, rid) / "events.jsonl")
        reports[rid] = verify_run(baseline["runs"][rid], after, events, allowed)
    result = {"schema": "protview_replay_verification@1", "ok": all(row["ok"] for row in reports.values()),
              "allowed_appended_events": sorted(allowed), "runs": reports}
    atomic_json(args.output, result)
    print(json.dumps({"ok": result["ok"], "runs": list(reports), "output": str(args.output)}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        sys.exit(2)
