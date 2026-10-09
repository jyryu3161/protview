#!/usr/bin/env python3
"""Run the M26 reaction knowledge offscreen acceptance (.dryforge/spec.md §12 오프스크린 QA).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (`next start` on 127.0.0.1:3000 for the whole invocation; per
stage a backend uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend, MW_RUNS_DIR=<root>/<stage>/runs,
MW_REFERENCE_DIR=<root>/<stage>/reference and MW_REACTION_REFERENCE_DIR=<root>/<stage>/reaction_reference), drives the
real Electron offscreen flows frontend/tests/offscreen/reaction-knowledge-flow.cjs and mutation-flow.cjs (mode
``catalytic``) from a stage plan this runner writes, and assembles ONE case-ledger.json for both stages.

Stages (``--stages``, default ``fixture,real``):
  fixture  a LABELLED SYNTHETIC reaction reference set (backend/tests/fixtures/reaction/t9/build_qa_set.py, run as a
           subprocess: synthetic M-CSA / UniProt / Rhea rows, every value made up) and the M15 snapshot imported from
           --kbase into <root>/fixture/reference (subprocess, as the M20 runner does). Steps: fixture-empty (no set) →
           set A installed → fixture-main (snapshot block, request defaults, field errors, nine admission refusals,
           1HSG / derived 1HSG / 1UBQ / synthetic 0SY6 and 0SY2 structures / prepared 1MQ4 with an M15 numbering map,
           paging, report, dry-run run, result list, wording, M20 pre-selection with UK3, tab invariants) →
           fixture-mutation (M20 v2: UK2, pre-selection, per-chain prediction, chains_not_covered, checked, lists,
           release, seven exclusion reasons, limitation variants with a stored v1 run copied from the T1 fixture,
           marks on the M20 / M21 / M23 / M24 / M25 pickers) → active.json moved aside → fixture-unset → active.json
           back and one set file tampered → fixture-invalid → set B (same rows, another imported_at) → fixture-stale.
  real     --reaction-set <dir>: an installed reaction reference folder (active.json + sets/) COPIED into
           <root>/real/reaction_reference (the source is never written), the M15 snapshot from --kbase, the public
           structures 1S9I / 1A30 / 1A4I, the synthetic derived 1S9I (Asp194 → Glu), 1UBQ and 1MQ4. Steps: real-main
           and real-mutation with the real plan.
The ledger's ``acceptance`` is true only when BOTH stages ran in this invocation and passed, every case passed, every
flow row measured 0 non-loopback browser requests (no host contacted) and zero provider calls, the reaction set and
M15 reference changes did what they should, the build was stamped from the current frontend source and no worker or
8000/3000 listener remains. A stage that was not requested is recorded as missing (never as passed).

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw and never calls a limit-raising route;
the set builder and the M15 importer run as subprocesses, run setup (one dry-run run record) uses the loopback API.

Usage:
  .venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs path>/kbase_kinase \\
      [--stages fixture|real|fixture,real] [--reaction-set <installed set folder>] \\
      [--out docs/qa/m26-reaction-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, reference import, bookkeeping, leftover check and evidence export of the M15 runner.
import m15_offscreen_acceptance as m15

# Loopback API helpers of the M18 runner.
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "reaction-knowledge-flow.cjs"
MUTATION_FLOW = "mutation-flow.cjs"
STAGES = ("fixture", "real")
STEPS: dict[str, list[str]] = {
    "fixture": ["fixture-empty", "fixture-main", "fixture-mutation", "fixture-unset", "fixture-invalid",
                "fixture-stale"],
    "real": ["real-main", "real-mutation"],
}
# step → (harness, mode)
FLOW_OF = {"fixture-empty": (FLOW, "empty"), "fixture-main": (FLOW, "main"), "fixture-mutation": (MUTATION_FLOW, "catalytic"),
           "fixture-unset": (FLOW, "unset"), "fixture-invalid": (FLOW, "invalid"), "fixture-stale": (FLOW, "stale"),
           "real-main": (FLOW, "main"), "real-mutation": (MUTATION_FLOW, "catalytic")}
FIXTURES = Path("backend/tests/fixtures")
T9 = FIXTURES / "reaction/t9"
QA_SET_BUILDER = T9 / "build_qa_set.py"
V1_RUN_ID = "run_m23_golden_keys"
V1_RUN_EVENTS = FIXTURES / "reaction/t1/v1-run-run_m23_golden_keys.events.jsonl"
SECOND_IMPORTED_AT = "2026-10-08T00:00:01Z"
TAMPER_FILE = "files/rhea/reactions.jsonl"
TAMPER_BYTES = b'{"qa":"m26 tamper: this line makes the processed file hash differ"}\n'
SYNTHETIC_NOTE = ("every reaction reference value of the fixture stage is SYNTHETIC (made up, labelled): "
                  "backend/tests/fixtures/reaction/t9/build_qa_set.py with the T2, T6 and T9 rows "
                  "(SYNTHETIC-PROVENANCE-t2.md, -t6.md, -t9.md); observations are of the screen, never results")

# ---------------------------------------------------------------------------------------------------- cases
CASE_PLAN: dict[str, dict[str, list[str]]] = {
    "fixture": {
        "R-no-snapshot": ["fixture-empty"],
        "R-snapshot-ready": ["fixture-main"], "R-request-defaults": ["fixture-main"],
        "R-field-errors": ["fixture-main"], "R-refusals": ["fixture-main"], "R-matched-row": ["fixture-main"],
        "R-reaction-section": ["fixture-main"], "R-conflict-derived": ["fixture-main"],
        "R-unmatched-reasons": ["fixture-main"], "R-two-entries": ["fixture-main"], "R-uk4": ["fixture-main"],
        "R-pdb-not-in-snapshot": ["fixture-main"], "R-accession-states": ["fixture-main"],
        "R-uniprot-link": ["fixture-main"], "R-link-reasons": ["fixture-main"], "R-paging": ["fixture-main"],
        "R-report": ["fixture-main"], "R-dry-run": ["fixture-main"], "R-results-list": ["fixture-main"],
        "R-no-zero": ["fixture-main", "fixture-mutation"], "R-wording": ["fixture-main", "fixture-mutation"],
        "R-m20-uk3": ["fixture-main"], "R-tabs": ["fixture-main"],
        "C-uk2-none": ["fixture-mutation"], "C-preselect": ["fixture-mutation"], "C-prediction": ["fixture-mutation"],
        "C-chains-not-covered": ["fixture-mutation"], "C-checked": ["fixture-mutation"],
        "C-lists": ["fixture-mutation"], "C-release": ["fixture-mutation"], "C-exclusion-seven": ["fixture-mutation"],
        "C-limitation-variants": ["fixture-mutation"], "C-v1-set": ["fixture-mutation"],
        "C-picker-marks": ["fixture-mutation"],
        "R-unset": ["fixture-unset"], "R-invalid": ["fixture-invalid"], "R-stale": ["fixture-stale"],
    },
    "real": {
        "X-snapshot-real": ["real-main"], "X-matched-real": ["real-main"], "X-two-chains": ["real-main"],
        "X-two-entries": ["real-main"], "X-conflict-derived": ["real-main"], "X-pdb-not-in-snapshot": ["real-main"],
        "X-uniprot-link": ["real-main"], "X-report": ["real-main"], "X-dry-run": ["real-main"],
        "X-no-zero": ["real-main", "real-mutation"], "X-wording": ["real-main", "real-mutation"],
        "X-tabs": ["real-main"], "X-m20": ["real-mutation"], "X-picker-marks": ["real-mutation"],
    },
}
CASE_TEXT = {
    "R-no-snapshot": "no reaction set: the snapshot block shows 사용할 수 없음, the not_installed reason and the import "
                     "command only (no numbers, no controls); the request block shows a reason only",
    "R-snapshot-ready": "set A: hash (12 + full in title), three sources with date, CC BY 4.0 and row counts, the "
                        "processed-copy label, user-named and skipped counts, the skipped list, RK1 / UK1 / RK6 verbatim",
    "R-request-defaults": "nothing chosen by itself: no structure, the file's PDB ID suggestion unconfirmed, no chain "
                          "ticked, no numbering map, 연결하기 disabled",
    "R-field-errors": "typed values the screen refuses (PDB ID ABCD confirmed, accession p0syn1): the reason beside the "
                      "field, 연결하기 disabled, nothing posted",
    "R-refusals": "nine labelled in-flight request alterations → the real server refuses each admission reason; the "
                  "screen shows \"한국어 (code)\" beside its field; nothing stored",
    "R-matched-row": "1HSG with PDB ID 0T91 (synthetic rows): both chains covered; matched rows with the 7-field "
                     "identity, the verbatim text in the column \"M-CSA 원문, 계산 아님\" (\"\" for an empty string) and "
                     "the reference-structure flag; the screen equals the stored rows",
    "R-reaction-section": "chain A with accession Q0SYN1: EC of both sources, M-CSA compounds, UniProt activities with "
                          "Rhea in_snapshot true and false (equation or — with the reason)",
    "R-conflict-derived": "the synthetic derived 1HSG (ASP A25 renamed GLU): the A25 row is 충돌 (residue_name_differs) "
                          "with the structure name GLU",
    "R-unmatched-reasons": "synthetic 0SY6 and 0SY2 structures: all five 대응 없음 reasons and both 충돌 reasons, the "
                           "insertion-code identity and null label fields as —",
    "R-two-entries": "one chain with two M-CSA entries (601, 602): both listed, none chosen",
    "R-uk4": "chains M-CSA does not cover (chain_not_listed, pdb_not_in_snapshot) carry UK4 beside the chain label",
    "R-pdb-not-in-snapshot": "1UBQ (file suggestion confirmed): pdb_not_in_snapshot, the area's 빈 결과 state, the PDB "
                             "lookup sentence without a number",
    "R-accession-states": "이 accession 쓰기 (lookup suggestion), an accession skipped at import (demerged + targets), "
                          "an accession not in the snapshot, the accession_differs_from_mcsa flag",
    "R-uniprot-link": "prepared 1MQ4 + M15 numbering map (real kbase snapshot in the isolated folder): sites linked "
                      "through the map, mapped links with the 7 fields and not_in_map links",
    "R-link-reasons": "without the map: numbering_map_not_given; map with another accession: map_accession_differs",
    "R-paging": "60 rows on one chain: M-CSA 행 다음 / 이전 equal the stored pages; chain and site pagers disabled",
    "R-report": "보고서 만들기 → 효소 반응 지식 보고서 in the library; Markdown / JSON downloads non-empty and equal to "
                "the backend bytes; RK1–RK6 present; no forbidden word outside fixed lines and reference strings",
    "R-dry-run": "a dry-run run (record made over the loopback API; every later step a real click) still links and "
                 "stores the result",
    "R-results-list": "the result list equals the stored list; counts that were not made are — with the reason; "
                      "결과 목록 다시 읽기 reads (GET only)",
    "R-no-zero": "values that were not checked, not available or not computed are — with the reason, never 0",
    "R-wording": "no rank / recommendation / importance / activity / effect wording outside the fixed sentences and the "
                 "verbatim reference strings",
    "R-m20-uk3": "M20 request area: the newest same-structure result is pre-selected (no POST) and, its sites being "
                 "linked, UK3 is shown",
    "R-tabs": "구조 분석 hidden and inert while 지식·보고서 shows, run selection only in 구조 분석, the 단백질 공학 and "
              "리간드 tabs' areas and text unchanged by the reaction work",
    "C-uk2-none": "M20 with no same-structure result: the not-selected notice and UK2 in the request area",
    "C-preselect": "two results on the prepared 1HSG: choosing the structure pre-selects the newest; nothing is posted",
    "C-prediction": "the partial result chosen: UK2 and one line per uncovered chain (B not_in_annotation) before the "
                    "request; the covered chains line",
    "C-chains-not-covered": "set from the partial result: not_checked (chains_not_covered), covered A, uncovered B "
                            "not_in_annotation, chain B positions — (not checked)",
    "C-checked": "set from the full result: checked, row counts, catalytic_residue on matched positions with the M-CSA "
                 "entry id, the checked limitation sentence",
    "C-lists": "conflict and unmatched lists with the M-CSA positions, prominent",
    "C-release": "the released matched position: candidate, its entries kept, \"해제됨\"",
    "C-exclusion-seven": "seven exclusion reasons in the counts line and the reason filter",
    "C-limitation-variants": "limitation sentence 3: v1 (stored v1 set), not_checked and checked variants verbatim",
    "C-v1-set": "the stored v1 run (copied T1 fixture, events only): not_available, the v1 mark detail, — (v1) cells",
    "C-picker-marks": "\"촉매 잔기 검사 안 함\" on not-checked sets and none on the checked set: M20 list, M21 handoff, "
                      "M23 select, M24 sources, M25 protein loop pool",
    "R-unset": "active.json moved aside: not_installed with the import command, the request block closed, stored "
               "results open from events with 사용 중 스냅샷 없음",
    "R-invalid": "one set file tampered: snapshot_invalid, the request block closed, stored results open with "
                 "사용 중 스냅샷 없음",
    "R-stale": "set B active: the new hash; every earlier result shows 이전 스냅샷 기준 (list and detail), nothing "
               "recomputed",
    "X-snapshot-real": "the copied real set: hash, three sources with dates, CC BY 4.0, row counts, skipped list",
    "X-matched-real": "1S9I chain A covered: matched rows, verbatim role text, reference flag, reaction section",
    "X-two-chains": "1A30: both chains covered",
    "X-two-entries": "1A4I: one chain with two M-CSA entries",
    "X-conflict-derived": "synthetic derived 1S9I (ASP A194 renamed GLU): the A194 row is 충돌 (residue_name_differs)",
    "X-pdb-not-in-snapshot": "1UBQ: pdb_not_in_snapshot and the empty result",
    "X-uniprot-link": "an M15 numbering map (1S9I or 1MQ4): UniProt sites linked to structure residues",
    "X-report": "report + downloads, fixed sentences, no forbidden word",
    "X-dry-run": "a dry-run run links",
    "X-no-zero": "not checked / not available / not computed values are — with the reason, never 0",
    "X-wording": "no rank / importance / activity wording outside fixed sentences and reference strings",
    "X-tabs": "구조 분석 hidden and inert, run selection only there, other tabs unchanged",
    "X-m20": "M20 v2 on the real result: pre-selection, prediction, protection status and lists",
    "X-picker-marks": "marks on the pickers for not-checked sets",
}
NOT_OBSERVED = {
    "fixture": {
        "R-late-response": "late responses of another run / result are covered by the pure guard tests "
                           "(frontend/tests/reaction-knowledge.test.cjs reactionResponseCurrent) and the M15/M20 flows' "
                           "held-response checks of the same pattern; this flow does not hold responses.",
        "R-too-many-links": "the 2,000-link and 1 MiB caps need inputs far larger than the QA structures; covered by "
                            "backend/tests/test_reaction_knowledge_tool.py (429, nothing stored).",
        "C-list-too-long": "the 400-item conflict / unmatched cap is covered by backend/tests/test_mutation_tool.py "
                           "(m20_catalytic_fixture long_unmatched).",
    },
    "real": {},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stages_arg(text: str) -> list[str]:
    stages = [part.strip() for part in text.split(",") if part.strip()]
    if not stages or len(set(stages)) != len(stages) or any(stage not in STAGES for stage in stages):
        raise argparse.ArgumentTypeError(f"--stages takes fixture, real or fixture,real (got {text!r})")
    return [stage for stage in STAGES if stage in stages]


# ---------------------------------------------------------------------------------------------------- plans
def structure(code: Path, rel: Path, provenance: str, prepare: bool = False) -> dict:
    return {"file": str(code / rel), "name": rel.name, "provenance": provenance, "prepare": prepare,
            "sha256": m13.sha_file(code / rel) if (code / rel).is_file() else None}


def fixture_plan(code: Path, set_hash: str, dry_run_run: str | None) -> dict:
    """The fixture stage plan the harnesses follow (inputs, the person's entries and the expectations hand-derived from
    the synthetic rows, SYNTHETIC-PROVENANCE-t9.md). Every reaction value it names is synthetic."""
    def row(status: str, reason: str | None = None) -> str:
        return status if reason is None else f"{status}:{reason}"
    hsg_a = {"691/0": row("matched"), "691/2": row("matched"), "691/4": row("conflict", "residue_name_differs"),
             "691/5": row("unmatched", "residue_not_in_structure"), "691/6": row("unmatched", "no_author_number")}
    links = [
        {"id": "hsg-0t91", "structure": "hsg", "use": "loaded", "pdbId": {"type": "0T91"}, "lookupEntries": [691],
         "chains": [{"chain": "A", "accession": {"type": "Q0SYN1"}}, {"chain": "B", "accession": None}], "map": None,
         "cases": ["R-matched-row", "R-reaction-section", "R-accession-states", "R-no-zero"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [691], "rows": hsg_a, "uniprot": ["checked", None],
                   "link": "numbering_map_not_given", "flags": ["accession_differs_from_mcsa"], "reactions": "checked",
                   "rheaInSnapshot": [True, False]},
             "B": {"coverage": "covered", "entries": [691], "rows": {"691/1": "matched", "691/3": "matched"},
                   "uniprot": ["not_checked", "accession_not_given"], "flags": [], "reactions": "checked"}}}},
        {"id": "hsg-0t92", "structure": "hsg", "use": "loaded", "pdbId": {"type": "0T92"}, "lookupEntries": [692],
         "chains": [{"chain": "A", "accession": None}], "map": None, "cases": ["R-paging"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [692], "rowCount": 60, "allRows": "matched",
                   "uniprot": ["not_checked", "accession_not_given"], "flags": [], "reactions": "checked"}}}},
        {"id": "derived-0t91", "structure": "hsg_derived", "use": "loaded", "pdbId": {"type": "0T91"},
         "lookupEntries": [691], "chains": [{"chain": "A", "accession": None}], "map": None,
         "cases": ["R-conflict-derived"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [691],
                   "rows": {**hsg_a, "691/0": row("conflict", "residue_name_differs")},
                   "structureResname": {"691/0": "GLU"}, "uniprot": ["not_checked", "accession_not_given"],
                   "flags": [], "reactions": "checked"}}}},
        {"id": "ubq-1ubq", "structure": "ubq", "use": "loaded", "pdbId": {"suggested": "1UBQ"}, "lookupEntries": [],
         "chains": [{"chain": "A", "accession": None}], "map": None,
         "cases": ["R-pdb-not-in-snapshot", "R-uk4", "R-no-zero"],
         "expect": {"nullResult": True, "chains": {
             "A": {"coverage": "pdb_not_in_snapshot", "uniprot": ["not_checked", "accession_not_given"],
                   "flags": [], "reactions": "not_checked"}}}},
        {"id": "syn-0sy6", "structure": "syn", "use": "loaded", "pdbId": {"type": "0SY6"}, "lookupEntries": [601, 602],
         "chains": [{"chain": "A", "accession": {"suggestion": "Q0SYN1"}}, {"chain": "B", "accession": {"type": "P0SYN6"}},
                    {"chain": "CC", "accession": None}], "map": None,
         "cases": ["R-unmatched-reasons", "R-two-entries", "R-uk4", "R-accession-states", "R-no-zero"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [601, 602], "rows": {
                 "601/0": "matched", "601/1": "matched", "601/2": row("conflict", "residue_name_differs"),
                 "601/3": row("unmatched", "ambiguous_residue_number"),
                 "601/4": row("unmatched", "residue_not_in_structure"), "601/5": row("unmatched", "no_author_number"),
                 "601/6": "matched", "601/7": "matched", "601/11": row("unmatched", "non_standard_code"),
                 "602/0": "matched", "602/1": "matched"},
                 "uniprot": ["checked", None], "link": "numbering_map_not_given", "flags": [], "reactions": "checked"},
             "B": {"coverage": "covered", "entries": [601, 602], "rows": {
                 "601/8": "matched", "601/9": "matched", "601/10": row("conflict", "mcsa_rows_disagree"),
                 "602/2": "matched"},
                 "uniprot": ["not_available", "accession_skipped_at_import"],
                 "skipped": {"reason": "demerged", "target_accessions": ["P0SYN1", "P0SYN2"]},
                 "flags": ["accession_differs_from_mcsa"], "reactions": "checked"},
             "CC": {"coverage": "chain_not_listed", "uniprot": ["not_checked", "accession_not_given"], "flags": [],
                    "reactions": "not_checked"}}}},
        {"id": "beta-0sy2", "structure": "beta", "use": "loaded", "pdbId": {"type": "0SY2"}, "lookupEntries": [101, 103],
         "chains": [{"chain": "A", "accession": {"type": "Q0SZZ1"}}, {"chain": "B", "accession": None}], "map": None,
         "cases": ["R-unmatched-reasons", "R-accession-states", "R-no-zero"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [101, 103], "rows": {
                 "101/14": "matched", "103/0": "matched", "103/1": row("unmatched", "ambiguous_residue_number"),
                 "103/2": row("unmatched", "insertion_code_present"),
                 "103/4": row("unmatched", "residue_not_in_structure")},
                 "insertionCode": {"103/2": "A"}, "nullLabels": ["101/14", "103/0", "103/2"],
                 "uniprot": ["not_available", "accession_not_in_snapshot"], "flags": ["accession_differs_from_mcsa"],
                 "reactions": "checked"},
             "B": {"coverage": "covered", "entries": [103], "rows": {"103/3": "matched", "103/5": "matched"},
                   "uniprot": ["not_checked", "accession_not_given"], "flags": [], "reactions": "checked"}}}},
        {"id": "mq4-nomap", "structure": "mq4", "use": "prepared", "pdbId": {"suggested": "1MQ4"}, "lookupEntries": [],
         "chains": [{"chain": "A", "accession": {"map": "O14965"}}], "map": None, "cases": ["R-link-reasons"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "pdb_not_in_snapshot", "uniprot": ["checked", None], "link": "numbering_map_not_given",
                   "flags": [], "reactions": "checked"}}}},
        {"id": "mq4-differs", "structure": "mq4", "use": "prepared", "pdbId": {"suggested": "1MQ4"}, "lookupEntries": [],
         "chains": [{"chain": "A", "accession": {"type": "Q0SYN1"}}], "map": "mq4-map", "cases": ["R-link-reasons"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "pdb_not_in_snapshot", "uniprot": ["checked", None], "link": "map_accession_differs",
                   "flags": [], "reactions": "checked"}}}},
        {"id": "mq4-linked", "structure": "mq4", "use": "prepared", "pdbId": {"suggested": "1MQ4"}, "lookupEntries": [],
         "chains": [{"chain": "A", "accession": {"map": "O14965"}}], "map": "mq4-map", "refusals": True,
         "cases": ["R-uniprot-link", "R-uk4"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "pdb_not_in_snapshot", "uniprot": ["checked", None], "link": None, "flags": [],
                   "reactions": "checked", "linkStatuses": [["not_in_map"], ["mapped"], ["mapped", "mapped", "mapped"]],
                   "rheaInSnapshot": [True, False]}}}},
    ]
    return {
        "schema": "m26_qa_plan@1", "stage": "fixture", "setHash": set_hash, "synthetic": SYNTHETIC_NOTE,
        "structures": {
            "hsg": structure(code, FIXTURES / "public_1hsg.cif", "public PDB entry 1HSG (repository fixture)"),
            "hsg_derived": structure(code, T9 / "derived_1hsg_A25_asp_to_glu.cif",
                                     "SYNTHETIC derived from public 1HSG: ASP A25 renamed GLU (SYNTHETIC-PROVENANCE-t9.md)"),
            "ubq": structure(code, FIXTURES / "public_1ubq.cif", "public PDB entry 1UBQ (repository fixture)"),
            "syn": structure(code, FIXTURES / "mutation/synthetic-mutation-fixture.cif",
                             "SYNTHETIC M20 fixture structure (fixtures/mutation/SYNTHETIC-PROVENANCE.md)"),
            "beta": structure(code, FIXTURES / "reaction/t2/structure_beta.pdb",
                              "SYNTHETIC M26 T2 structure (fixtures/reaction/t2/SYNTHETIC-PROVENANCE-t2.md)"),
            "mq4": structure(code, FIXTURES / "public_1mq4.cif", "public PDB entry 1MQ4 (repository fixture)",
                             prepare=True),
        },
        "maps": [{"id": "mq4-map", "structure": "mq4", "use": "prepared", "pdbId": "1MQ4", "chain": "A",
                  "accession": "O14965"}],
        "links": links,
        "fieldErrors": {"structure": "hsg", "badPdbId": "ABCD", "chain": "A", "badAccession": "p0syn1"},
        "refusals": {"case": "mq4-linked", "otherStructure": "hsg"},
        "paging": "hsg-0t92",
        "report": "hsg-0t91",
        "uk3": {"structure": "mq4", "link": "mq4-linked"},
        "dryRun": {"run": dry_run_run, "structure": "hsg", "link": {
            "id": "dry-hsg-0t91", "structure": "hsg", "use": "loaded", "pdbId": {"type": "0T91"}, "lookupEntries": [691],
            "chains": [{"chain": "A", "accession": None}], "map": None, "cases": ["R-dry-run"],
            "expect": {"nullResult": False, "chains": {"A": {"coverage": "covered", "entries": [691],
                                                              "rows": hsg_a, "uniprot": ["not_checked",
                                                                                         "accession_not_given"],
                                                              "flags": [], "reactions": "checked"}}}}},
        "mutation": {
            "structure": structure(code, FIXTURES / "public_1hsg.cif", "public PDB entry 1HSG (repository fixture)"),
            "pdbId": "0T91", "chainsPartial": ["A"], "chainsAll": ["A", "B"],
            "positions": {"ligandShell": {"resname": "MK1", "chain": "B", "seq": 902, "radius": "5"}},
            "release": {"resname": "ASP", "chain": "A", "seq": 25},
            "expect": {
                "partialUncovered": [{"chain_auth": "B", "coverage": "not_in_annotation"}],
                "catalytic": {"ASP A:25": [[691, 0, True]], "GLY A:27": [[691, 2, True]],
                              "ASP B:25": [[691, 1, False]], "GLY B:27": [[691, 3, True]]},
                "partialCounts": {"matched_rows": 2, "conflict_rows": 1, "unmatched_rows": 2},
                "allCounts": {"matched_rows": 4, "conflict_rows": 1, "unmatched_rows": 2},
                "conflicts": [["A", 691, 4]], "unmatched": [["A", 691, 5], ["A", 691, 6]]},
            "v1Run": V1_RUN_ID,
            "pickers": ["m20", "m21", "m23", "m24", "m25"],
        },
    }


def real_plan(code: Path, set_hash: str, dry_run_run: str | None) -> dict:
    """The real stage plan (T9c runs and tunes it): structures and entries named from the shape of the installed set
    (M-CSA 282 → 1S9I chain A, 175 → 1A30 chains A and B, 389 and 458 → 1A4I chain A); row statuses are not
    pre-judged beyond the coverage, the entry ids and the derived conflict, and the screen must equal the stored rows."""
    links = [
        {"id": "s9i", "structure": "s9i", "use": "loaded", "pdbId": {"suggested": "1S9I"}, "lookupEntries": [282],
         "chains": [{"chain": "A", "accession": {"suggestion": "P36507"}}, {"chain": "B", "accession": None}],
         "map": None, "cases": ["X-matched-real", "X-no-zero"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [282], "minMatched": 1, "uniprot": ["checked", None],
                   "link": "numbering_map_not_given", "flags": [], "reactions": "checked"},
             "B": {"coverage": "chain_not_listed", "uniprot": ["not_checked", "accession_not_given"], "flags": [],
                   "reactions": "not_checked"}}}},
        {"id": "a30", "structure": "a30", "use": "loaded", "pdbId": {"suggested": "1A30"}, "lookupEntries": [175],
         "chains": [{"chain": "A", "accession": None}, {"chain": "B", "accession": None}], "map": None,
         "cases": ["X-two-chains"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [175], "minMatched": 1, "reactions": "checked"},
             "B": {"coverage": "covered", "entries": [175], "minMatched": 1, "reactions": "checked"}}}},
        {"id": "a4i", "structure": "a4i", "use": "loaded", "pdbId": {"suggested": "1A4I"}, "lookupEntries": [389, 458],
         "chains": [{"chain": "A", "accession": None}], "map": None, "cases": ["X-two-entries"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [389, 458], "minMatched": 1, "reactions": "checked"}}}},
        {"id": "s9i-derived", "structure": "s9i_derived", "use": "loaded", "pdbId": {"suggested": "1S9I"},
         "lookupEntries": [282], "chains": [{"chain": "A", "accession": None}], "map": None,
         "cases": ["X-conflict-derived"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [282], "rowsInclude": {"282/A194": "conflict:residue_name_differs"},
                   "reactions": "checked"}}}},
        {"id": "ubq", "structure": "ubq", "use": "loaded", "pdbId": {"suggested": "1UBQ"}, "lookupEntries": [],
         "chains": [{"chain": "A", "accession": None}], "map": None, "cases": ["X-pdb-not-in-snapshot", "X-no-zero"],
         "expect": {"nullResult": True, "chains": {"A": {"coverage": "pdb_not_in_snapshot", "reactions": "not_checked"}}}},
        {"id": "s9i-linked", "structure": "s9i", "use": "prepared", "pdbId": {"suggested": "1S9I"},
         "lookupEntries": [282], "chains": [{"chain": "A", "accession": {"map": "P36507"}}], "map": "s9i-map",
         "cases": ["X-uniprot-link"],
         "expect": {"nullResult": False, "chains": {
             "A": {"coverage": "covered", "entries": [282], "uniprot": ["checked", None], "link": None,
                   "minLinked": 1, "reactions": "checked"}}}},
    ]
    return {
        "schema": "m26_qa_plan@1", "stage": "real", "setHash": set_hash, "synthetic": None,
        "structures": {
            "s9i": structure(code, FIXTURES / "public_1s9i.cif", "public PDB entry 1S9I (RCSB CC0, T9a download)",
                             prepare=True),
            "a30": structure(code, FIXTURES / "public_1a30.cif", "public PDB entry 1A30 (RCSB CC0, T9a download)"),
            "a4i": structure(code, FIXTURES / "public_1a4i.cif", "public PDB entry 1A4I (RCSB CC0, T9a download)"),
            "s9i_derived": structure(code, T9 / "derived_1s9i_A194_asp_to_glu.cif",
                                     "SYNTHETIC derived from public 1S9I: ASP A194 renamed GLU (SYNTHETIC-PROVENANCE-t9.md)"),
            "ubq": structure(code, FIXTURES / "public_1ubq.cif", "public PDB entry 1UBQ (repository fixture)"),
        },
        "maps": [{"id": "s9i-map", "structure": "s9i", "use": "prepared", "pdbId": "1S9I", "chain": "A",
                  "accession": "P36507"}],
        "links": links, "fieldErrors": None, "refusals": None, "paging": None, "report": "s9i",
        "uk3": {"structure": "s9i", "link": "s9i-linked"},
        "dryRun": {"run": dry_run_run, "structure": "ubq", "link": {
            "id": "dry-ubq", "structure": "ubq", "use": "loaded", "pdbId": {"suggested": "1UBQ"}, "lookupEntries": [],
            "chains": [{"chain": "A", "accession": None}], "map": None, "cases": ["X-dry-run"],
            "expect": {"nullResult": True, "chains": {"A": {"coverage": "pdb_not_in_snapshot",
                                                            "reactions": "not_checked"}}}}},
        "mutation": {
            "structure": structure(code, FIXTURES / "public_1s9i.cif", "public PDB entry 1S9I (RCSB CC0, T9a download)"),
            "pdbId": "1S9I", "chainsPartial": ["A"], "chainsAll": ["A", "B"],
            "positions": {"residues": [{"resname": "ASP", "chain": "A", "seq": 194},
                                       {"resname": "ASP", "chain": "A", "seq": 221},
                                       {"resname": "ASP", "chain": "B", "seq": 194}]},
            "release": {"resname": "ASP", "chain": "A", "seq": 194},
            "expect": {"partialUncovered": [{"chain_auth": "B", "coverage": "not_in_annotation"}],
                       "allUncovered": [{"chain_auth": "B", "coverage": "chain_not_listed"}]},
            "v1Run": None,
            "pickers": ["m20", "m21", "m23", "m24", "m25"],
        },
    }


# ---------------------------------------------------------------------------------------------------- judgement
def reaction_changes_ok(stage: str, changes: dict) -> bool:
    """The reaction reference folder changes of a stage did what they should (status read back over the API)."""
    def entry(name: str) -> dict:
        return changes.get(name) or {}
    if stage == "fixture":
        empty, first, unset, tamper, second = (entry(name) for name in ("empty-at-start", "set-a", "unset", "tamper",
                                                                         "set-b"))
        return (empty.get("status") == "pass" and first.get("status") == "pass" and bool(first.get("setHash"))
                and unset.get("status") == "pass" and unset.get("served", {}).get("reason") == "not_installed"
                and tamper.get("status") == "pass" and tamper.get("served", {}).get("reason") == "snapshot_invalid"
                and second.get("status") == "pass" and bool(second.get("setHash"))
                and second.get("setHash") != first.get("setHash"))
    copied = entry("copy")
    return copied.get("status") == "pass" and bool(copied.get("setHash"))


def assemble(rows: list[dict], leftovers: list[str], stages: list[str], checks: dict) -> dict:
    """Judge every requested stage (latest row per step, the stage's cases, its reference changes) and record the
    others as missing. ``checks`` = {stage: {"reaction": {...}, "m15": {...}}}. Returns
    {stages, cases, missingStages, counts, verdictParts, passed}."""
    attempts: dict[str, list[tuple[tuple[int, str], dict]]] = {}
    for row in rows:
        base, order = m13.step_base(row["step"])
        attempts.setdefault(base, []).append((order, row))
    latest = {step: max(found, key=lambda item: item[0])[1] for step, found in attempts.items()}
    judged_stages: dict[str, dict] = {}
    all_cases: dict[str, dict] = {}
    for stage in STAGES:
        if stage not in stages:
            judged_stages[stage] = {"status": "missing", "reason": f"stage {stage} was not run in this invocation "
                                    f"(--stages {','.join(stages)})"}
            continue
        steps: dict[str, dict] = {}
        for step in STEPS[stage]:
            row = latest.get(step)
            if row is None:
                steps[step] = {"status": "missing", "problems": ["no row"]}
                continue
            problems = []
            if row.get("status") != "pass":
                problems.append(f"status {row.get('status')}")
            if row.get("externalRequestCount") != 0:
                problems.append(f"externalRequestCount {row.get('externalRequestCount')!r}")
            if row.get("providerCallsZero") is not True:
                problems.append("provider calls not measured zero")
            steps[step] = {"status": "fail" if problems else "pass", "latest": row["step"], "problems": problems,
                           "attempts": len(attempts[step])}
        cases: dict[str, dict] = {}
        for case, covering in CASE_PLAN[stage].items():
            seen = {step: ((latest.get(step) or {}).get("cases") or {}).get(case) for step in covering}
            cases[case] = {"stage": stage, "text": CASE_TEXT[case], "steps": seen,
                           "status": "pass" if all(value == "pass" for value in seen.values()) else "fail"}
        rows_of_stage = [latest[step] for step in STEPS[stage] if step in latest]
        cases[f"S-{stage}-no-egress"] = {
            "stage": stage, "text": "every flow row: 0 non-loopback browser requests (no host contacted) and zero "
                                    "provider calls",
            "status": "pass" if len(rows_of_stage) == len(STEPS[stage]) and all(
                r.get("externalRequestCount") == 0 and r.get("providerCallsZero") is True and not r.get("blockedHosts")
                for r in rows_of_stage) else "fail"}
        stage_checks = checks.get(stage) or {}
        m15_ok = (stage_checks.get("m15") or {}).get("status") == "pass" and bool((stage_checks.get("m15") or {})
                                                                                   .get("setHash"))
        cases[f"S-{stage}-references"] = {
            "stage": stage, "text": ("the reaction set changes (set A, active.json aside, one file tampered, set B) and "
                                     "the M15 import into the isolated folders, read back over the API"
                                     if stage == "fixture" else
                                     "the reaction set copied into the isolated folder and the M15 import, read back"),
            "status": "pass" if reaction_changes_ok(stage, stage_checks.get("reaction") or {}) and m15_ok else "fail"}
        parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
                 "cases": all(v["status"] == "pass" for v in cases.values())}
        judged_stages[stage] = {"status": "pass" if all(parts.values()) else "fail", "steps": steps,
                                "parts": parts, "notObserved": dict(NOT_OBSERVED[stage])}
        all_cases.update(cases)
    missing = [stage for stage in STAGES if judged_stages[stage]["status"] == "missing"]
    ran = [stage for stage in STAGES if stage not in missing]
    parts = {"stagesRan": bool(ran) and all(judged_stages[stage]["status"] == "pass" for stage in ran),
             "bothStages": not missing, "leftoverProcesses": not leftovers}
    counts = {"cases": len(all_cases), "passed": sum(1 for v in all_cases.values() if v["status"] == "pass"),
              "failed": sum(1 for v in all_cases.values() if v["status"] != "pass")}
    return {"stages": judged_stages, "cases": all_cases, "missingStages": missing, "counts": counts,
            "verdictParts": parts, "passed": parts["stagesRan"] and parts["leftoverProcesses"]}


def acceptance_ok(judged: dict, build: dict | None) -> bool:
    """True only when both stages ran in this invocation and passed, nothing was left and the build was stamped."""
    return (judged["passed"] and judged["verdictParts"]["bothStages"]
            and bool((build or {}).get("buildCurrentWithSource")))


def browser_hosts(rows: list[dict]) -> list[str]:
    hosts: set[str] = set()
    for row in rows:
        hosts.update(row.get("blockedHosts") or [])
    return sorted(hosts)


# ---------------------------------------------------------------------------------------------------- runner
class Runner(m15.Runner):
    """The M15 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw path
    check, allowlisted env, leftover check, redacted export) with per-stage isolated folders, the reaction reference
    changes, the two M26 flows and the two-stage ledger."""

    api = m18.Runner.api
    provider_zero = m18.Runner.provider_zero

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m26-reaction-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.stages: list[str] = list(args.stages)
        self.reaction_set = Path(args.reaction_set).resolve() if args.reaction_set else None
        if "real" in self.stages:
            if self.reaction_set is None:
                raise SystemExit("the real stage needs --reaction-set <installed reaction reference folder>")
            if self.reaction_set == self.root or self.root in self.reaction_set.parents:
                raise SystemExit("--reaction-set must not be inside --root (it is copied, never written)")
            if not (self.reaction_set / "active.json").is_file() or not (self.reaction_set / "sets").is_dir():
                raise SystemExit(f"--reaction-set has no active.json and sets/: {self.reaction_set}")
        self.stage: str | None = None
        self.reaction = self.root / "reaction_reference"
        self.checks: dict[str, dict] = {stage: {"reaction": {}, "m15": {}} for stage in STAGES}
        self.plans: dict[str, dict] = {}
        self.setup: dict[str, dict] = {stage: {} for stage in STAGES}

    # ----- folders and services --------------------------------------------------------------------
    def use_stage(self, stage: str) -> None:
        self.stage = stage
        base = self.root / stage
        self.runs, self.reference, self.reaction = base / "runs", base / "reference", base / "reaction_reference"

    def start_backend(self) -> None:
        """m15's backend start with the isolated reaction reference folder of the current stage as well."""
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(self.runs),
                             "MW_REFERENCE_DIR": str(self.reference),
                             "MW_REACTION_REFERENCE_DIR": str(self.reaction)})
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=self.code,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(self.code / "backend")):
            raise RuntimeError(f"backend import resolved outside {self.code}: {probe.stdout}")
        log = self.artifacts / "services" / f"backend-{self.stage}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=self.code, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{m15.API}/capabilities")
        self.state.setdefault("services", []).append({"name": f"backend-{self.stage}", "runs": str(self.runs),
                                                      "reference": str(self.reference),
                                                      "reactionReference": str(self.reaction), "code": str(self.code),
                                                      "python": str(self.python), "mw": probe.stdout.strip(),
                                                      "startedAt": now()})
        self.save()

    def stop_backend(self) -> None:
        """m15's stop_all for the stage backend only (the frontend keeps running for the next stage)."""
        keep = {name: proc for name, proc in self.services.items() if name != "backend"}
        self.services = {name: proc for name, proc in self.services.items() if name == "backend"}
        try:
            self.stop_all()
        finally:
            self.services = {**keep, **self.services}

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m26_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- reaction reference folder (subprocess builder, file moves; this runner never imports mw) --------------
    def reaction_status(self) -> dict:
        served = self.get_json("/reaction_reference/status")
        return {key: served.get(key) for key in ("installed", "reason", "set_hash", "imported_at")}

    def reaction_change(self, name: str, action, expect: dict) -> dict:
        """Apply one change to the stage's reaction reference folder and read the status back over the API. Returns the
        recorded entry (``status`` pass only when the served status matches ``expect`` and any new set hash)."""
        entry: dict = {"status": "fail", "at": now()}
        try:
            entry.update(action() or {})
            served = self.reaction_status()
            entry["served"] = served
            ok = all(served.get(key) == value for key, value in expect.items())
            if "setHash" in entry:
                ok = ok and served.get("set_hash") == entry["setHash"]
            entry["status"] = "pass" if ok else "fail"
            if not ok:
                entry["problem"] = f"served {served} does not match {expect}"
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            entry["problem"] = f"{type(exc).__name__}: {exc}"
        self.checks[self.stage]["reaction"][name] = entry
        self.state["checks"] = self.checks
        self.record(f"{self.stage}-reaction-{name}", entry["status"], setHash=entry.get("setHash"),
                    served=entry.get("served"), problem=entry.get("problem"))
        self.save()
        return entry

    def build_qa_set(self, imported_at: str | None = None) -> dict:
        argv = [str(self.python), str(self.code / QA_SET_BUILDER), "--root", str(self.reaction)]
        if imported_at:
            argv += ["--imported-at", imported_at]
        log = self.artifacts / "services" / f"qa-set-{imported_at or 'a'}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(argv, cwd=self.code, env=m13.child_env(), capture_output=True, text=True, timeout=300,
                              check=False)
        log.write_text(json.dumps({"argv": argv, "exitCode": proc.returncode}) + "\n" + proc.stdout + proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"set builder exited {proc.returncode}; see {log}")
        made = json.loads(proc.stdout.strip().splitlines()[-1])
        return {"setHash": made["set_hash"], "importedAt": made["imported_at"], "rows": made["rows"],
                "builder": str(QA_SET_BUILDER), "label": SYNTHETIC_NOTE}

    def active_set(self) -> str:
        return json.loads((self.reaction / "active.json").read_text())["set_hash"]

    def unset_active(self) -> dict:
        (self.reaction / "active.json").rename(self.reaction / "active.json.qa-unset")
        return {"moved": "active.json -> active.json.qa-unset"}

    def tamper_active(self) -> dict:
        (self.reaction / "active.json.qa-unset").rename(self.reaction / "active.json")
        target = self.reaction / "sets" / self.active_set() / TAMPER_FILE
        before = m13.sha_file(target)
        with target.open("ab") as out:
            out.write(TAMPER_BYTES)
        return {"restored": "active.json", "tampered": TAMPER_FILE, "sha256Before": before,
                "sha256After": m13.sha_file(target)}

    def copy_real_set(self) -> dict:
        if self.reaction.exists() and any(self.reaction.iterdir()):
            raise RuntimeError(f"{self.reaction} is not empty")
        self.reaction.rmdir()
        shutil.copytree(self.reaction_set, self.reaction, symlinks=False)
        return {"setHash": self.active_set(), "source": str(self.reaction_set)}

    def m15_import(self) -> str | None:
        set_hash = self.reference_change(f"{self.stage}-m15-import", [
            str(self.python), str(self.code / "scripts/import_reference_snapshots.py"),
            "--from", str(self.kbase), "--dest", str(self.reference)])
        self.checks[self.stage]["m15"] = self.reference_steps.get(f"{self.stage}-m15-import", {})
        return set_hash

    # ----- run setup over the loopback API (no tool, no job, no limit change) -------------------------------------
    def dry_run_run(self) -> str | None:
        status, made = self.api("POST", "/runs", {"goal": "M26 QA dry-run run (setup record; later steps are real "
                                                          "clicks)", "context": [], "dry_run": True,
                                                  "egress": "local_only"})
        ok = status in (200, 201) and isinstance(made, dict) and made.get("dry_run") is True
        self.setup[self.stage]["dryRunRun"] = {"status": status, "run": (made or {}).get("run_id") if ok else None,
                                               "label": "QA setup record: dry-run run made through POST /runs (the "
                                                        "UI has no dry-run control)"}
        self.record(f"{self.stage}-setup-dry-run-run", "pass" if ok else "fail", httpStatus=status)
        return made.get("run_id") if ok else None

    def copy_v1_run(self) -> None:
        target = self.runs / V1_RUN_ID / "events.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.code / V1_RUN_EVENTS, target)
        self.setup[self.stage]["v1Run"] = {"run": V1_RUN_ID, "source": str(V1_RUN_EVENTS),
                                           "sha256": m13.sha_file(target),
                                           "label": "stored M20 v1 run (T1 fixture, SYNTHETIC-PROVENANCE-t1.md) copied "
                                                    "into the isolated runs folder; opened from events only"}

    # ----- flows ---------------------------------------------------------------------------------------------------
    def write_plan(self, plan: dict) -> Path:
        path = self.artifacts / f"{self.stage}-plan.json"
        path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
        self.plans[self.stage] = plan
        return path

    def flow(self, step: str, extra: list[str]) -> dict | None:
        script, mode = FLOW_OF[step]
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / script), "--url", m15.WEB, "--mode", mode, "--artifacts", str(step_dir),
                *extra]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            try:
                rc = subprocess.run(argv, cwd=self.frontend, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    timeout=m15.STEP_TIMEOUT_S, check=False).returncode
            except subprocess.TimeoutExpired:
                rc = -9
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        if row is None:
            self.write_row(step_dir, {"mode": mode, "evidenceKind": "real_electron_offscreen", "status": "fail",
                                      "cases": {}, "externalRequestCount": None, "providerCallsZero": None,
                                      "error": f"harness exited {rc} without a ledger row"})
        passed = rc == 0 and row is not None and row.get("status") == "pass"
        self.record(step, "pass" if passed else "fail", exitCode=rc, artifacts=str(step_dir),
                    runs=(row or {}).get("runs"), cases=(row or {}).get("cases"))
        return row

    def skip(self, steps: list[str], reason: str) -> None:
        for step in steps:
            self.missing_prerequisite(step, reason)

    def run_fixture(self) -> None:
        self.use_stage("fixture")
        for folder in (self.runs, self.reference, self.reaction):
            folder.mkdir(parents=True, exist_ok=True)
        self.start_backend()
        try:
            self.reaction_change("empty-at-start", dict, {"installed": False, "reason": "not_installed"})
            self.flow("fixture-empty", [])
            first = self.reaction_change("set-a", self.build_qa_set, {"installed": True, "reason": None})
            set_a = first.get("setHash") if first["status"] == "pass" else None
            m15_hash = self.m15_import()
            dry = self.dry_run_run()
            if not (set_a and m15_hash and dry):
                self.skip(STEPS["fixture"][1:], "a prerequisite failed (set A, M15 import or the dry-run run)")
                return
            plan = self.write_plan(fixture_plan(self.code, set_a, dry))
            main = self.flow("fixture-main", ["--plan", str(plan)]) or {}
            self.copy_v1_run()
            self.flow("fixture-mutation", ["--plan", str(plan)])
            runs = [run for run in ((main.get("runs") or {}).get("A"), (main.get("runs") or {}).get("D")) if run]
            if not runs:
                self.skip(STEPS["fixture"][3:], "fixture-main recorded no run")
                return
            listed = ["--runs", ",".join(runs), "--plan", str(plan)]
            if self.reaction_change("unset", self.unset_active,
                                    {"installed": False, "reason": "not_installed"})["status"] == "pass":
                self.flow("fixture-unset", [*listed, "--set-hash", set_a])
            else:
                self.skip(["fixture-unset"], "moving active.json aside did not give not_installed")
            if self.reaction_change("tamper", self.tamper_active,
                                    {"installed": False, "reason": "snapshot_invalid"})["status"] == "pass":
                self.flow("fixture-invalid", [*listed, "--set-hash", set_a])
            else:
                self.skip(["fixture-invalid"], "tampering did not give snapshot_invalid")
            second = self.reaction_change("set-b", lambda: self.build_qa_set(SECOND_IMPORTED_AT),
                                          {"installed": True, "reason": None})
            set_b = second.get("setHash") if second["status"] == "pass" else None
            if set_b and set_b != set_a:
                self.flow("fixture-stale", [*listed, "--set-hash", set_b, "--previous-set-hash", set_a])
            else:
                self.skip(["fixture-stale"], "set B was not installed")
        finally:
            self.stop_backend()

    def run_real(self) -> None:
        self.use_stage("real")
        for folder in (self.runs, self.reference, self.reaction):
            folder.mkdir(parents=True, exist_ok=True)
        self.start_backend()
        try:
            entry = self.reaction_change("copy", self.copy_real_set, {"installed": True, "reason": None})
            copied = entry.get("setHash") if entry["status"] == "pass" else None
            m15_hash = self.m15_import()
            dry = self.dry_run_run()
            if not (copied and m15_hash and dry):
                self.skip(STEPS["real"], "a prerequisite failed (set copy, M15 import or the dry-run run)")
                return
            plan = self.write_plan(real_plan(self.code, copied, dry))
            self.flow("real-main", ["--plan", str(plan)])
            self.flow("real-mutation", ["--plan", str(plan)])
        finally:
            self.stop_backend()

    # ----- ledger and evidence -------------------------------------------------------------------------------------
    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "status": row.get("status"),
                         "cases": row.get("cases") or {}, "runs": row.get("runs"), "runId": row.get("runId"),
                         "evidenceKind": row.get("evidenceKind"), "handles": row.get("handles", {}),
                         "inputs": row.get("inputs", []), "fixtureLabels": row.get("fixtureLabels", []),
                         "controls": row.get("controls", {}), "setHash": row.get("setHash"),
                         "observations": row.get("observations", {}),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "blockedHosts": row.get("blockedHosts") or sorted({item.get("origin") for item in (
                             (row.get("offscreen") or {}).get("blockedRequests") or [])}),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.stages, self.checks)
        build = self.state.get("build")
        acceptance = acceptance_ok(judged, build)
        ledger = {"schema": "m26_case_ledger@1", "generatedAt": now(), "build": build,
                  "stagesRequested": self.stages, "missingStages": judged["missingStages"],
                  "verdict": "pass" if judged["passed"] else "fail", "acceptance": acceptance,
                  "acceptanceRule": "both stages ran in this invocation and passed, nothing left, build stamped",
                  "verdictParts": judged["verdictParts"], "counts": judged["counts"], "stages": judged["stages"],
                  "cases": judged["cases"], "checks": self.checks, "setup": self.setup,
                  "plans": {stage: str(self.artifacts / f"{stage}-plan.json") for stage in self.plans},
                  "syntheticNote": SYNTHETIC_NOTE if "fixture" in self.stages else None,
                  "reference": {"kbase": str(self.kbase), "reactionSet": str(self.reaction_set) if self.reaction_set
                                else None, "changes": self.reference_steps},
                  "leftoverProcesses": leftovers,
                  "browserHostsContacted": browser_hosts(rows),
                  "externalRequestsTotal": sum(r["externalRequestCount"] or 0 for r in rows),
                  "rowsWithUnknownExternalCount": [r["step"] for r in rows if r["externalRequestCount"] is None],
                  "rows": rows}
        (self.artifacts / "case-ledger.json").write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
        self.record("case-ledger", "pass" if judged["passed"] else "fail", verdict=ledger["verdict"],
                    acceptance=acceptance, missingStages=judged["missingStages"],
                    cases={case: value["status"] for case, value in judged["cases"].items()},
                    output=str(self.artifacts / "case-ledger.json"))
        return ledger

    def readme(self, ledger: dict) -> str:
        lines = ["# M26 효소 반응 지식 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}** (두 단계가 이번 실행에서 모두 돌고 통과할 때만 true)"),
                 (f"- 요청한 단계: {', '.join(ledger['stagesRequested'])} · 빠진 단계: "
                  f"{', '.join(ledger['missingStages']) or '없음'}"),
                 f"- 사례: {ledger['counts']['passed']}/{ledger['counts']['cases']} 통과",
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 (f"- 브라우저 비-loopback 요청 합계: {ledger['externalRequestsTotal']} · 접촉한 외부 호스트: "
                  f"{', '.join(ledger['browserHostsContacted']) or '없음'}"), ""]
        if ledger.get("syntheticNote"):
            lines += [("**fixture 단계의 반응 참조값(M-CSA·UniProt·Rhea 행)은 모두 합성(SYNTHETIC)이다.** "
                       "`backend/tests/fixtures/reaction/t9/build_qa_set.py`가 T2·T6·T9 합성 행으로 만든 세트이며 "
                       "(`SYNTHETIC-PROVENANCE-t2.md`·`-t6.md`·`-t9.md`), 지어낸 PDB ID(0T91·0T92·0SY6·0SY2 등)를 사람이 "
                       "구조에 준 것으로 보고 입력했다. 관찰은 화면이 저장된 값을 그대로 보이는지에 대한 것이며 과학 결과가 "
                       "아니다. 촉매 잔기·부위·반응에 대한 사실이나 변이의 효과를 뜻하지 않는다."), ""]
        lines += [("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                   "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), ""]
        for stage in STAGES:
            info = ledger["stages"][stage]
            lines += [f"## 단계 `{stage}` — {info['status']}", ""]
            if info["status"] == "missing":
                lines += [f"- {info['reason']}", ""]
                continue
            lines += ["| 사례 | 내용 | 결과 | 단계 |", "|---|---|---|---|"]
            for case, value in ledger["cases"].items():
                if value["stage"] != stage:
                    continue
                steps = ", ".join(f"{k}:{v}" for k, v in value.get("steps", {}).items())
                lines.append(f"| {case} | {value['text']} | {value['status']} | {steps} |")
            lines += ["", "| 흐름 단계 | 결과 | 문제 |", "|---|---|---|"]
            for step, value in info["steps"].items():
                lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
            for name, value in (ledger["checks"].get(stage) or {}).get("reaction", {}).items():
                lines.append(f"| reaction-{name} | {value.get('status')} | {value.get('problem', '')} |")
            lines += ["", "관찰하지 않은 사례:", ""]
            lines += [f"- {case}: {reason}" for case, reason in info["notObserved"].items()] or ["- 없음"]
            lines.append("")
        lines += ["## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  "# fixture 단계만 (실서버 요청 0, 합성 세트)",
                  ".venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \\",
                  "    --stages fixture --out docs/qa/m26-reaction-<YYYYMMDD>/fixture-stage",
                  "# 두 단계 (수락: 설치된 실제 세트 폴더를 격리 폴더로 복사)",
                  ".venv/bin/python scripts/m26_offscreen_acceptance.py --root runs/m26-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m26-acceptance/<label> --kbase <abs>/kbase_kinase \\",
                  "    --stages fixture,real --reaction-set <installed set folder> \\",
                  "    --out docs/qa/m26-reaction-<YYYYMMDD>/acceptance",
                  "```"]
        return "\n".join(lines) + "\n"

    def run(self) -> int:
        if self.root.exists() and any(self.root.iterdir()):
            raise SystemExit(f"{self.root} is not fresh; choose a new --root")
        busy = {port: m13.listening(port) for port in (8000, 3000)}
        if any(busy.values()):
            raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.build()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.code, capture_output=True, text=True,
                              check=False).stdout.strip()
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=self.code, capture_output=True, text=True,
                                   check=False).stdout
        build_id = self.frontend / ".next/BUILD_ID"
        self.state["build"] = {"buildId": build_id.read_text().strip() if build_id.exists() else None, "gitHead": head,
                               "buildCurrentWithSource": m13.build_is_current(self.frontend),
                               "gitStatusPorcelainSha256": m13.sha_bytes(porcelain.encode()),
                               "dirtyFiles": porcelain.splitlines(), "recordedAt": now(), "codeRoot": str(self.code),
                               "harnessSha256": {name: m13.sha_file(self.offscreen / name) for name in (
                                   FLOW, MUTATION_FLOW, "driver.cjs", "main.cjs", "normal-flow.cjs")},
                               "runnerSha256": m13.sha_file(Path(__file__))}
        self.save()
        try:
            self.start_frontend()
            if "fixture" in self.stages:
                self.run_fixture()
            if "real" in self.stages:
                self.run_real()
        finally:
            self.stop_all()
            self.save()
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        ledger = self.ledger(left)
        self.export(ledger)
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "acceptance": ledger["acceptance"],
                          "missingStages": ledger["missingStages"], "artifacts": str(self.artifacts)}), flush=True)
        stage_failed = any(ledger["stages"][stage]["status"] == "fail" for stage in self.stages)
        return 1 if failed or stage_failed or not ledger["verdictParts"]["leftoverProcesses"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (<stage>/runs, reference and reaction_reference "
                        "are created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m26-acceptance/<label>")
    parser.add_argument("--kbase", default=str(REPO.parent / "kbase_kinase"),
                        help="local kbase_kinase checkout for the M15 snapshot import (read only; default: "
                        "<repo>/../kbase_kinase; give an absolute path in a git worktree)")
    parser.add_argument("--stages", type=stages_arg, default=list(STAGES),
                        help="fixture, real or fixture,real (default); acceptance needs both in one invocation")
    parser.add_argument("--reaction-set", help="installed reaction reference folder (active.json + sets/) for the real "
                        "stage; copied into the isolated folder, never written")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m26-reaction-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
