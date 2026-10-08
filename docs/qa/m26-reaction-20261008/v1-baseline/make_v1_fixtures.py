"""ONE-SHOT generator (M26 T1, before any M26 product change): stored M20 v1 candidate sets for the golden recorders.

Runs the UNMODIFIED M20 v1 tool ``generate_mutation_candidates`` (``mw.mutation_candidates/v1``) on the in-repo public
``backend/tests/fixtures/public_1ubq.cif`` exactly the way the two golden recorders built their sets until M26 T1, and
writes into ``backend/tests/fixtures/reaction/t1/``:

* ``m20-v1-candidate-set-golden_m24_mutation.json`` / ``m20-v1-candidate-set-golden_m24_dry.json``: the sets of
  ``backend/tests/fixtures/jev/golden_science_m24.py`` ``templates()`` (path-loaded 1UBQ, default preparation, user
  positions MET1 / ILE44 / LYS48, normal and dry-run run),
* ``m20-v1-candidate-set-run_m23_golden_keys-8pos.json``: the set of
  ``backend/tests/fixtures/sequence_ga/prototype_golden_call_keys.py`` (HTTP upload, explicit preparation, eight
  positions, allowed ``AFHWY``); byte-identical to ``fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json``,
* ``v1-run-run_m23_golden_keys.events.jsonl``: the whole event log of the ``build_sequence_ga_fixtures.py`` run
  (upload, ``load_structure``, ``prepare_structure``, the 8pos and tiny sets through the v1 tool), so a v1 set that has
  its tool provenance can be reopened events-only after M20 v2 (method reports need that provenance).

Each set file is ``canonical_json({"handle", "content"}) + "\\n"`` (the ``fixtures/sequence_ga`` format). After M20 v2
this script cannot reproduce the files (the tool then builds v2 sets); it is the record of how they were made, not a
check. Not product code.

    .venv/bin/python docs/qa/m26-reaction-20261008/v1-baseline/make_v1_fixtures.py <scratch-root>
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
TESTS = REPO / "backend" / "tests"
for extra in (str(REPO / "backend"), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.mutation_constants import METHOD_VERSION
from mw.workspace import new_run

FIX = TESTS / "fixtures"
OUT = FIX / "reaction" / "t1"
SEQ_GA = FIX / "sequence_ga"


def res(seq_auth: int, resname: str) -> dict:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq_auth, "icode": "", "resname": resname}


def golden_m24_sets(root: Path) -> dict[str, bytes]:
    """``golden_science_m24.templates()`` up to and including its M20 call (same args, same fixed run ids)."""
    out = {}
    for name, dry in (("mutation", False), ("dry", True)):
        run = new_run(root / name, run_id=f"golden_m24_{name}", dry_run=dry)
        loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
        prepared = run.call("prepare_structure", {"structure": loaded}).handle
        source = run.call("generate_mutation_candidates", {
            "structure": prepared, "sources": {"pocket": None, "ligand_shell": None,
                                               "residues": [res(1, "MET"), res(44, "ILE"), res(48, "LYS")]}}).handle
        content = run.store.load(source)
        assert content["method_version"] == METHOD_VERSION == "mw.mutation_candidates/v1", content["method_version"]
        out[f"m20-v1-candidate-set-{run.run_id}.json"] = canonical_json({"handle": source, "content": content}) + b"\n"
    return out


def golden_keys_run(root: Path) -> tuple[dict[str, bytes], bytes]:
    """``build_sequence_ga_fixtures.build`` (the run of ``golden_call_keys.json``): both sets and the whole log."""
    spec = importlib.util.spec_from_file_location("build_sequence_ga_fixtures_m26_t1",
                                                  SEQ_GA / "build_sequence_ga_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    built = module.build(root)
    for name, raw in built.items():   # the committed M23 fixtures are this exact output
        assert (SEQ_GA / name).read_bytes() == raw, name
    log = (root / module.RUN_ID / "events.jsonl").read_bytes()
    return {"m20-v1-candidate-set-run_m23_golden_keys-8pos.json": built["m20-candidate-set-1ubq-8pos.json"]}, log


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        return 2
    root = Path(argv[0])
    shutil.rmtree(root, ignore_errors=True)
    saved = api_module.RUNS_DIR
    try:
        files = golden_m24_sets(root / "golden_m24")
        sets, log = golden_keys_run(root / "golden_keys")
    finally:
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()
    files.update(sets)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, raw in sorted(files.items()):
        (OUT / name).write_bytes(raw)
        print(f"wrote {name} ({len(raw)} bytes)")
    (OUT / "v1-run-run_m23_golden_keys.events.jsonl").write_bytes(log)
    print(f"wrote v1-run-run_m23_golden_keys.events.jsonl ({len(log)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
