"""M26 T1 v1 baseline: M20 v1 read responses, report bytes and ``validated_set`` outcomes of the stored v1 sets.

Recorded on the unmodified M20 v1 code (before any M26 product change) so that T6 (M20 v2) can show that every stored v1
candidate set still validates and that its read responses (existing keys and values) and method-report bytes are
unchanged. Two kinds of case, both rebuilt from committed fixtures only (no M20 tool call, no network, no ``.env``):

* ``frozen-run_m23_golden_keys``: the whole v1 run log ``backend/tests/fixtures/reaction/t1/v1-run-run_m23_golden_keys
  .events.jsonl`` (made by the unmodified v1 tool) reopened events-only: the M20 list read, detail / positions /
  candidates of both sets (8pos, tiny), one ``mutation_candidates`` method report per set (``POST /method_reports``,
  needs the tool provenance in the log; each report on its own fresh copy of the log, so its snapshot is the frozen
  last event and not the other report's creation time) and ``GET /reports`` (re-validates the saved report).
* ``stored-<fixture>``: each stored v1 set file put with ``store.put`` into a fresh run with the run id of its handle:
  handle equality, ``validated_set`` outcome, the four M20 reads, and the report answer (a set without the tool
  provenance has no report: the v1 refusal is recorded as it is).

Everything in a case is deterministic (fixed run ids, content handles, the frozen log's own times), so the files are
compared byte for byte. ``--write`` records twice and writes only if both recordings are equal; ``--check`` exits 0 only
if a fresh recording equals the files in ``baseline/`` and otherwise prints every differing JSON path. Not product code.

    .venv/bin/python docs/qa/m26-reaction-20261008/v1-baseline/record_v1_baseline.py --check --work <scratch>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
for extra in (str(REPO / "backend"), str(REPO / "backend" / "tests")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from fastapi.testclient import TestClient
from mw import mutation_candidates as mc
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.workspace import new_run

FIX = REPO / "backend" / "tests" / "fixtures"
T1 = FIX / "reaction" / "t1"
OUT = HERE / "baseline"
FROZEN_RUN = "run_m23_golden_keys"
FROZEN_LOG = T1 / f"v1-run-{FROZEN_RUN}.events.jsonl"
STORED = {   # label -> stored v1 set file ({handle, content}); every stored v1 M20 set fixture in the repository
    "sequence_ga-8pos": FIX / "sequence_ga" / "m20-candidate-set-1ubq-8pos.json",
    "sequence_ga-tiny": FIX / "sequence_ga" / "m20-candidate-set-1ubq-tiny.json",
    "t1-golden_m24_mutation": T1 / "m20-v1-candidate-set-golden_m24_mutation.json",
    "t1-golden_m24_dry": T1 / "m20-v1-candidate-set-golden_m24_dry.json",
    "t1-run_m23_golden_keys-8pos": T1 / "m20-v1-candidate-set-run_m23_golden_keys-8pos.json",
}
DRY_RUN_IDS = {"golden_m24_dry"}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def answer(response: Any) -> dict[str, Any]:
    return {"http_status": response.status_code, "body": response.json()}


def reads(client: TestClient, rid: str, handle: str) -> dict[str, Any]:
    base = f"/runs/{rid}/mutation_candidate_sets/{handle}"
    return {"detail": answer(client.get(base)), "positions": answer(client.get(f"{base}/positions")),
            "candidates": answer(client.get(f"{base}/candidates"))}


def validated(content: dict[str, Any]) -> dict[str, Any]:
    try:
        returned = mc.validated_set(content)
    except mc.MutationSetInvalid as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "returned_equals_input": returned == content,
            "input_canonical_sha256": sha(canonical_json(content)),
            "returned_canonical_sha256": sha(canonical_json(returned))}


def frozen_copy(root: Path) -> TestClient:
    (root / FROZEN_RUN).mkdir(parents=True)
    shutil.copyfile(FROZEN_LOG, root / FROZEN_RUN / "events.jsonl")
    new_run(root, run_id=FROZEN_RUN, dry_run=False)
    api_module.RUNS_DIR = root
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def frozen_case(root: Path, files: dict[str, bytes]) -> dict[str, Any]:
    listing = answer(frozen_copy(root / "list").get(f"/runs/{FROZEN_RUN}/mutation_candidate_sets"))
    sets = {}
    for label in ("8pos", "tiny"):
        handle = json.loads(STORED[f"sequence_ga-{label}"].read_text())["handle"]
        client = frozen_copy(root / label)
        report = client.post(f"/runs/{FROZEN_RUN}/method_reports", json={"result_handle": handle})
        stored = new_run(root / label, run_id=FROZEN_RUN, dry_run=False).store
        entry: dict[str, Any] = {"handle": handle, "validated_set": validated(stored.load(handle)),
                                 **reads(client, FROZEN_RUN, handle), "report": answer(report),
                                 "saved_reports": answer(client.get(f"/runs/{FROZEN_RUN}/reports"))}
        if report.status_code == 201:
            body = report.json()
            manifest = canonical_json(stored.load(body["handle"]))
            markdown = stored.load(body["markdown_handle"])
            files[f"frozen-{label}-report.manifest.json"] = manifest
            files[f"frozen-{label}-report.md"] = markdown
            entry["report_bytes"] = {"manifest_canonical_sha256": sha(manifest), "markdown_sha256": sha(markdown)}
        sets[label] = entry
    return {"run_id": FROZEN_RUN, "log_sha256": sha(FROZEN_LOG.read_bytes()), "list": listing, "sets": sets}


def stored_case(root: Path, path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text())
    rid = fixture["handle"].split("/")[2]
    run = new_run(root, run_id=rid, dry_run=rid in DRY_RUN_IDS)
    content = fixture["content"]
    with run._owner(), run._transition():
        handle = run.store.put("mutation_candidate_set", "mutation_candidate_set@1", content,
                               null_result=content["null_result"]).handle
    api_module.RUNS_DIR = root
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    report = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    return {"fixture": str(path.relative_to(REPO)), "fixture_sha256": sha(path.read_bytes()), "run_id": rid,
            "handle": handle, "handle_equals_fixture": handle == fixture["handle"],
            "method_version": content["method_version"],
            "catalytic_residue_database": content["protection_checks"]["catalytic_residue_database"],
            "validated_set": validated(content),
            "list": answer(client.get(f"/runs/{rid}/mutation_candidate_sets")), **reads(client, rid, handle),
            "report": answer(report)}


def record(work: Path) -> dict[str, bytes]:
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    saved = api_module.RUNS_DIR
    files: dict[str, bytes] = {}
    try:
        cases = {f"frozen-{FROZEN_RUN}": frozen_case(work / "frozen", files)}
        for label, path in STORED.items():
            cases[f"stored-{label}"] = stored_case(work / f"stored-{label}", path)
    finally:
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()
        shutil.rmtree(work, ignore_errors=True)
    for name, case in cases.items():
        files[f"{name}.json"] = (json.dumps(case, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
    files["SHA256SUMS"] = "".join(f"{sha(raw)}  {name}\n" for name, raw in sorted(files.items())).encode()
    return files


def paths(old: Any, new: Any, at: str, out: list[str]) -> None:
    if type(old) is not type(new) or not isinstance(old, (dict, list)):
        if old != new:
            out.append(at or "/")
    elif isinstance(old, dict):
        for key in sorted(set(old) | set(new)):
            if key not in old or key not in new:
                out.append(f"{at}/{key} ({'added' if key in new else 'removed'})")
            else:
                paths(old[key], new[key], f"{at}/{key}", out)
    elif len(old) != len(new):
        out.append(f"{at} (length {len(old)} -> {len(new)})")
    else:
        for index, (left, right) in enumerate(zip(old, new)):
            paths(left, right, f"{at}/{index}", out)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    parser.add_argument("--work", type=Path, required=True, help="scratch folder (deleted at the end)")
    args = parser.parse_args()
    fresh = record(args.work)
    if args.write:
        if record(args.work) != fresh:
            print("two fresh recordings differ; the baseline would not be stable", file=sys.stderr)
            return 1
        shutil.rmtree(OUT, ignore_errors=True)
        OUT.mkdir()
        for name, raw in fresh.items():
            (OUT / name).write_bytes(raw)
        print(f"wrote {len(fresh)} files to {OUT.relative_to(REPO)}")
        return 0
    on_disk = {path.name: path.read_bytes() for path in OUT.iterdir() if path.is_file()}
    bad = sorted(name for name in set(on_disk) | set(fresh) if on_disk.get(name) != fresh.get(name))
    for name in bad:
        print(f"differs: {name}", file=sys.stderr)
        if name.endswith(".json") and name in on_disk and name in fresh:
            found: list[str] = []
            paths(json.loads(on_disk[name]), json.loads(fresh[name]), "", found)
            for item in found[:50]:
                print(f"  {item}", file=sys.stderr)
    if bad:
        return 1
    print(f"v1 baseline matches a fresh recording ({len(fresh)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
