"""PROTOTYPE (M25 T1 measurement only, never product code): where the UNMODIFIED M24 send path refuses a loop shape.

Preflight item (c) of the M25 plan. A real M24 projection is built (public 1UBQ, M20 cheap tool, ``build_jev_projection``
through ``Run.call``) in a throw-away run; a LABELLED SYNTHETIC loop-shaped object (this script's reading of spec 4.2:
``jev_loop_projection@1`` with ``loop`` / ``goal`` / ``order`` and a wire carrying ``goal`` / ``computed``) is stored
next to it, and the M24 functions the loop must pass through are called on both, so the branch points listed in the
preflight are observed, not only read. Nothing is sent: no gate, network or credential is used. Runs live under
``--work`` (default ``runs/m25-t1-preflight/branch``), deleted at the end unless ``--keep``. Prints one JSON report.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mw import jev_constants as J
from mw import jev_projection as P
from mw import jev_sends as S
from mw.workspace import new_run

FIX = TESTS / "fixtures"


def outcome(call: Any) -> str:
    try:
        value = call()
    except Exception as exc:   # noqa: BLE001 - the measurement records which refusal each path raises
        detail = getattr(exc, "detail", None)
        return f"{type(exc).__name__}: {getattr(exc, 'message', str(exc))[:90]}" + (f" {detail}" if detail else "")
    return f"accepted ({type(value).__name__})"


def measure(work: Path) -> dict[str, Any]:
    run = new_run(work, run_id="m25_t1_branch", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    source = run.call("generate_mutation_candidates", {"structure": prepared, "sources": {
        "pocket": None, "ligand_shell": None,
        "residues": [{"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}]}}).handle
    m24 = run.call(J.TOOL, {"source": source, "candidates": [0, 1, 2]}).handle
    content = run.store.load(m24)
    loop = copy.deepcopy(content)
    loop.update(schema="jev_loop_projection@1", method_version="mw.jev_loop_projection/v1",
                loop={"loop_id": "00000000-0000-4000-8000-0000000000ee", "iteration": 1, "send_ordinal": 0},
                goal="exploit", order={"algorithm": "sha256_order_v1", "loop_seed": 1, "iteration": 1,
                                       "send_ordinal": 0},
                question={"id": "mutation_loop_choice@1", "key": J.QUESTION_KEY})
    loop["wire"] = {**loop["wire"], "schema": "jev_loop_mutation_candidates@1", "goal": "exploit",
                    "computed": [{"alias": "m01", "state": "scored", "score_kcal_mol": -7.1}]}
    loop_handle = run.store.put("jev_loop_projection", "jev_loop_projection@1",
                                {**loop, "label": "SYNTHETIC M25 T1 loop-shaped object, not a product projection"}).handle
    aliases = [item["alias"] for item in content["selection"]]
    reply = {"model": J.SERVED_SNAPSHOT, "answers": {J.QUESTION_KEY: {"type": "choice", "choice": "m01",
                                                                      "probabilities": {"m01": 0.5, "m02": 0.5}}}}
    events = [{"seq": 1, "type": J.EVENT_APPROVED, "send_id": "00000000-0000-4000-8000-0000000000ef",
               "projection_handle": loop_handle, "body_sha256": "0" * 64, "question_id": "mutation_loop_choice@1",
               "source_handle": source, "selection_count": 3, "approved_by": J.APPROVED_BY}]
    record = S.list_sends(events)[0]
    return {
        "m24_projection": {
            "load_projection": outcome(lambda: S.load_projection(run, m24)),
            "preview_for": outcome(lambda: S.preview_for(run, m24, list(run.events.read()))),
            "validated_projection": outcome(lambda: P.validated_projection(content))},
        "loop_shaped_object": {
            "load_projection (kind check)": outcome(lambda: S.load_projection(run, loop_handle)),
            "validated_projection (keys)": outcome(lambda: P.validated_projection(loop)),
            "INSTRUCTIONS[loop question id] (preview_for, build_choice, _check_choice)": outcome(
                lambda: J.INSTRUCTIONS["mutation_loop_choice@1"]),
            "parse_choice(reply choosing computed alias m01, every alias)": outcome(
                lambda: P.parse_choice(reply, aliases)),
            "_record of a loop-question approval": {key: record[key] for key in ("kind", "source", "body_bytes")},
            "_check_choice against the loop object": outcome(
                lambda: S.validated_choice({"schema": J.CHOICE_SCHEMA}, loop, run.store.load(source)))}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=REPO / "runs/m25-t1-preflight/branch")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    try:
        print(json.dumps(measure(args.work), indent=1, ensure_ascii=False))
    finally:
        if not args.keep:
            shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
