#!/usr/bin/env python3
"""Run the M27 kinase precedent offscreen acceptance (.dryforge/spec.md §10 오프스크린 QA, 가져오기 실검증).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (`next start` on 127.0.0.1:3000 for the whole invocation; per
stage a backend uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend and the stage's isolated folders
MW_RUNS_DIR=<root>/<stage>/runs, MW_REFERENCE_DIR=<root>/<stage>/reference (a read-only copy of the active M15 set,
--m15-reference), MW_PRECEDENT_REFERENCE_DIR=<root>/<stage>/precedent_reference and an empty
MW_REACTION_REFERENCE_DIR=<root>/<stage>/reaction_reference), drives the real Electron offscreen flow
frontend/tests/offscreen/kinase-precedents-flow.cjs from stage plans this runner writes and assembles ONE
case-ledger.json for both stages. The default folder .deps/precedent_reference is never written.

Stages (``--stages``, default ``fixture,real``):
  fixture  a LABELLED SYNTHETIC precedent set (backend/tests/fixtures/precedent/t8/build_qa_set.py ``set``, a
           subprocess). Steps: fixture-empty (no set) → set A → fixture-maps (real M15 maps made by clicks on public
           1MQ4 and the derived two-chain 1MQ4 fixture) → backend stopped, LABELLED SYNTHETIC map variants stored from
           one real M15 map (``build_qa_set.py derive``), backend started → fixture-main (snapshot block, request
           defaults, chain previews, five admission refusals, chain states, chain choice, target states and tabs,
           moves_flagged toggle, filters, sort, pages, record details, fixed notes, the 429 size refusal, report,
           result list, dry-run run, tab invariants, wording, no 0 for what was not included) → active.json moved
           aside → fixture-unset → active.json back and one set file tampered → fixture-invalid → set B (same records,
           another imported_at) → fixture-stale.
  real     the real kbase_kinase dist/ installed TWICE by the user import command (scripts/import_precedent_snapshots.py
           --from <kbase> --dest <root>/real/precedent_reference --yes, in a child whose sockets are refused and
           counted) — rows, verification, dirty and equal file SHA-256 of both installs recorded — then real-maps
           (M15 maps of public 1MQ4, 1M17 and 1FIN chains A and C by clicks) → one LABELLED SYNTHETIC size-test variant
           of the 1FIN map (chains given P00533 and Q06187, refused above 1 MiB, never stored) → real-main.
The ledger's ``acceptance`` is true only when BOTH stages ran in this invocation and passed, every case passed, every
flow row measured 0 non-loopback browser requests and zero provider calls, the imports used no socket, the reference
folder changes did what they should, no real kbase text reached the committed evidence, the build was stamped from
the current frontend source and no worker or 8000/3000 listener remains.

Committed evidence (--out) holds text only: hashes, IDs, counts and the synthetic fixture stage. Screenshots, paint
frames, report downloads, failure panels, text above 256 KiB (decision 0020) and any text that contains a real kbase
string (quote, observation, tradeoff, change description, assay, bibliography title or journal, reference field: any
40-character piece of one, or the whole of one of 24–39 characters, compared with whitespace collapsed and case
ignored, also inside JSON \\uXXXX / Markdown / HTML escapes; held in memory only) stay in the git-ignored artifacts
folder and are listed with their SHA-256 only. The root must be fresh and outside /tmp; the artifacts folder must be
git-ignored. Child processes get an allowlisted environment (no secrets). This script never imports mw and never calls
a limit-raising route; the set builder, the derived-map builder and the importer run as subprocesses.

Usage:
  .venv/bin/python scripts/m27_offscreen_acceptance.py --root runs/m27-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m27-acceptance/<label> \\
      [--kbase <abs path>/kbase_kinase] [--m15-reference .deps/reference] [--stages fixture|real|fixture,real] \\
      [--out docs/qa/m27-precedents-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, bookkeeping and the leftover check of the M15 runner.
import m15_offscreen_acceptance as m15

# Loopback API helpers of the M18 runner.
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "kinase-precedents-flow.cjs"
STAGES = ("fixture", "real")
STEPS: dict[str, list[str]] = {
    "fixture": ["fixture-empty", "fixture-maps", "fixture-main", "fixture-unset", "fixture-invalid", "fixture-stale"],
    "real": ["real-maps", "real-main"],
}
MODE_OF = {"fixture-empty": "empty", "fixture-maps": "maps", "fixture-main": "main", "fixture-unset": "unset",
           "fixture-invalid": "invalid", "fixture-stale": "stale", "real-maps": "maps", "real-main": "main"}
FIXTURES = Path("backend/tests/fixtures")
T8 = FIXTURES / "precedent/t8"
QA_SET_BUILDER = T8 / "build_qa_set.py"
IMPORTER = Path("scripts/import_precedent_snapshots.py")
SECOND_IMPORTED_AT = "2026-10-10T02:00:00Z"
TAMPER_FILE = "files/dist/moves.jsonl"
TAMPER_BYTES = b'{"qa":"m27 tamper: this line makes the dist file hash differ"}\n'
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt", ".html"}
LEDGER_NAMES = {"case-ledger.json", "ledger-row.json"}
MAX_TEXT_BYTES = 256 * 1024
FAILURE_PANEL_SUFFIX = "-failure.panel.html"
# Real kbase text in committed evidence: any REAL_TEXT_FRAGMENT_CHARS-character piece of a source string, or the whole
# of a shorter one from REAL_TEXT_MIN_CHARS on (normalized: whitespace collapsed, case folded). The harness keeps a
# string in a real-stage step record only below REAL_TEXT_MIN_CHARS (kinase-precedents-flow.cjs realSafe).
REAL_TEXT_MIN_CHARS = 24
REAL_TEXT_FRAGMENT_CHARS = 40
REAL_TEXT_DECODE_ROUNDS = 3
REFERENCE_TEXT_FIELDS = ("gene", "klifs_name", "group", "family", "coverage")
SYNTHETIC_NOTE = ("every precedent value of the fixture stage is SYNTHETIC (made up, labelled): "
                  "backend/tests/fixtures/precedent/t8/build_qa_set.py with precedent_fixture.py "
                  "(SYNTHETIC-PROVENANCE-t8.md); the derived numbering maps are LABELLED SYNTHETIC variants of a real "
                  "M15 map; observations are of the screen, never results")
# Real stage expectations: counts and IDs measured in T1 (docs/qa/m27-precedents-20261010/preflight.md (a)-(c)).
REAL_EXPECT = {
    "files": {"dist/moves.jsonl": 891, "dist/moves_flagged.jsonl": 885, "dist/references.jsonl": 555},
    "bibliographyRows": 252, "unresolved": 396, "unresolvedNamesTotal": 35,
    "kbase": {"commit": "77354f94b844a8c64e7cd47691ac20a2e96214b3",
              "dist_commit": "43a935e4637d986700fa61a4deae8300e405edb7",
              "dist_commit_date": "2026-09-21T00:05:28+09:00", "dirty": False, "kb_version": "kbv1:ae11f41d19e5bef9"},
    "verification": {"moves": 891, "moves_flagged": 885, "references": 555},
}
# The import child: every socket connection and name lookup is refused and counted (sockets never needed).
NETWORK_GUARD = (
    "import json, socket, sys, runpy\n"
    "ATTEMPTS = []\n"
    "def refuse(*args, **kwargs):\n"
    "    ATTEMPTS.append(repr(args)[:200])\n"
    "    raise OSError('network refused by the M27 QA runner')\n"
    "socket.socket.connect = refuse\nsocket.socket.connect_ex = refuse\nsocket.getaddrinfo = refuse\n"
    "socket.create_connection = refuse\n"
    "sys.argv = [sys.argv[1], *sys.argv[2:]]\n"
    "code = 0\n"
    "try:\n"
    "    runpy.run_path(sys.argv[0], run_name='__main__')\n"
    "except SystemExit as exc:\n"
    "    code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)\n"
    "finally:\n"
    "    loaded = [m for m in ('mw', 'ssl', 'http.client', 'urllib.request', 'httpx', 'requests') if m in sys.modules]\n"
    "    print('QA-NETWORK ' + json.dumps({'attempts': len(ATTEMPTS), 'loaded': loaded}), flush=True)\n"
    "sys.exit(code)\n")

# ---------------------------------------------------------------------------------------------------- cases
CASE_PLAN: dict[str, dict[str, list[str]]] = {
    "fixture": {
        "P-no-snapshot": ["fixture-empty"], "P-maps-real-m15": ["fixture-maps"],
        "P-snapshot-ready": ["fixture-main"], "P-request-defaults": ["fixture-main"],
        "P-chain-previews": ["fixture-main"], "P-refusals": ["fixture-main"], "P-chain-states": ["fixture-main"],
        "P-chain-select": ["fixture-main"], "P-target-states": ["fixture-main"], "P-target-tabs": ["fixture-main"],
        "P-flagged-toggle": ["fixture-main"], "P-filters": ["fixture-main"], "P-sort": ["fixture-main"],
        "P-paging": ["fixture-main"], "P-detail": ["fixture-main"], "P-fixed-notes": ["fixture-main"],
        "P-too-large": ["fixture-main"], "P-report": ["fixture-main"], "P-results-list": ["fixture-main"],
        "P-dry-run": ["fixture-main"], "P-tabs": ["fixture-main"], "P-no-zero": ["fixture-main"],
        "P-wording": ["fixture-main"],
        "P-unset": ["fixture-unset"], "P-invalid": ["fixture-invalid"], "P-stale": ["fixture-stale"],
    },
    "real": {
        "X-maps": ["real-maps"], "X-snapshot-real": ["real-main"], "X-request-defaults": ["real-main"],
        "X-1mq4-none": ["real-main"], "X-1m17-found": ["real-main"], "X-1m17-flagged": ["real-main"],
        "X-1fin-one-target": ["real-main"], "X-records-real": ["real-main"], "X-detail-real": ["real-main"],
        "X-too-large-real": ["real-main"], "X-report-real": ["real-main"], "X-results-list": ["real-main"],
        "X-tabs": ["real-main"], "X-no-zero": ["real-main"], "X-wording": ["real-main"],
    },
}
CASE_TEXT = {
    "P-no-snapshot": "no precedent set: the snapshot block shows 사용할 수 없음, not_installed and the import command only "
                     "(no numbers, no controls); the request block a reason only; entering the tab posts nothing",
    "P-maps-real-m15": "real M15 maps made by clicks in the 잔기 번호 대응 area: 1MQ4 chain A (PDB ID confirmed, SIFTS "
                       "O14965) and the derived two-chain 1MQ4 fixture (A O14965 + B Q8IU85; A + B O14965)",
    "P-snapshot-ready": "set A: hash (12 + full in title), imported date, kbase / dist commits, dist date, dirty, "
                        "kb_version, three versions, file rows, bibliography snapshot, processed label, KT1, UP5 with "
                        "the set-wide N, unresolved-name table (opened) and the resolution-basis counts",
    "P-request-defaults": "the newest numbering map pre-selected and nothing posted; every chain ticked; the "
                          "moves_flagged toggle off; 전례 연결 enabled",
    "P-chain-previews": "chain previews before the request: linked (accession), 연결 안 함 (no_mapped_residues) and "
                        "연결 안 함 (multiple_accessions with both accessions)",
    "P-refusals": "five labelled in-flight request alterations → the real server refuses each admission reason (422); "
                  "the screen shows \"한국어 (code)\" beside its field; nothing stored",
    "P-chain-states": "chain table: linked, not_linked no_mapped_residues (real M15 map) and not_linked "
                      "multiple_accessions (derived map) with reason \"한국어 (code)\", accessions, mapped / total, "
                      "cross check",
    "P-chain-select": "one chain unticked → chains sent as the remaining list; the result lists only that chain",
    "P-target-states": "precedents_found (전례 N건), none_in_included_files and not_in_kbase_references (real map, "
                       "accession absent from the synthetic set) phrases; UP2 under the status whenever excluded_flagged "
                       "is an integer (0 too); references listed or — with the reason",
    "P-target-tabs": "a result with two targets: the target tabs switch the target block and its record page",
    "P-flagged-toggle": "the moves_flagged toggle on: its note; included moves_flagged counts become integers and the "
                        "excluded count — with the reason",
    "P-filters": "file, site / goal / tactic terms (OR inside an axis, AND across), variant and text search (record and "
                 "bibliography title, case-insensitive) — server pages equal the GET of the same query and the counts "
                 "counted from the synthetic records; a 101-character search is refused on the screen; clear",
    "P-sort": "sort by PMID (desc) and bibliography year (asc, no integer year last): the screen order equals the "
              "server order",
    "P-paging": "30 records: 1–25, 다음 쪽 → 26–30 (equal to the server page), 이전 쪽 → back; edges disabled",
    "P-detail": "record details: bibliography and its absence, every location, observation quote with "
                "quote_truncated and quote_assembled, tradeoffs (null quote —), change, measured-change table "
                "(target_role, direction_basis, fold_change null — with the reason), structure links with UP4, the "
                "ten kbase checks apart from the ProtView integrity values (25-word limit false), content hash note",
    "P-fixed-notes": "KP1–KP6 verbatim and in order, KT1, UP1–UP5 verbatim (UP2 / UP5 with their N)",
    "P-too-large": "moves_flagged on for a map above 1 MiB → 429 result_too_large: the refusal with the size advice "
                   "(without moves_flagged fits; per-target fit), nothing stored",
    "P-report": "보고서 만들기 → 키나아제 전례 보고서 in the library; Markdown / JSON downloads equal to the backend "
                "bytes; KP1–KP6, KT1, UP2, UP5 present; no quote or observation text; no forbidden word outside fixed "
                "lines and stored strings",
    "P-results-list": "결과 목록 다시 읽기 (GET only): the list equals the stored list; a file not included shows — with "
                      "the reason; 빈 결과 for null results",
    "P-dry-run": "a dry-run run (record over the loopback API; later steps real clicks): M15 map and 전례 연결 store "
                 "the result",
    "P-tabs": "구조 분석 hidden and inert while 지식·보고서 shows, run selection only there, the 단백질 공학 and 리간드 "
              "tabs' areas and text unchanged by the precedent work",
    "P-no-zero": "not included, not computed, no bibliography and null fold_change are — with the reason, never 0 or a "
                 "bare 없음",
    "P-wording": "no rank / recommendation / verified / success rate / effect wording outside the fixed sentences and "
                 "the stored strings",
    "P-unset": "active.json moved aside: not_installed with the import command, the request block closed, stored "
               "results open from events with 사용 중 스냅샷 없음",
    "P-invalid": "one set file tampered: snapshot_invalid, the request block closed, stored results open with 사용 중 "
                 "스냅샷 없음",
    "P-stale": "set B active: the new hash; every earlier result shows 이전 스냅샷 기준 (list and detail), nothing "
               "recomputed",
    "X-maps": "real M15 maps by clicks: 1MQ4 A (O14965), 1M17 A (P00533), 1FIN chains A and C only (P24941); B and D "
              "(cyclin A) not requested",
    "X-snapshot-real": "the imported real set: hash, kbase HEAD 77354f94b844, dist commit 43a935e4637d and its date, "
                       "dirty false, kb_version, rows 891 / 885 / 555, bibliography 252 rows, UP5 396, 35 unresolved "
                       "names",
    "X-request-defaults": "the newest numbering map pre-selected, nothing posted, chains ticked, toggle off",
    "X-1mq4-none": "1MQ4 → O14965 none_in_included_files: included moves 0, moves_flagged — (not included), UP2 with 0",
    "X-1m17-found": "1M17 → P00533 precedents_found: 76 moves, excluded 66 (UP2), variants not_reported 53 · L858R 15 · "
                    "T790M 4 · WT 3 · L834R 1",
    "X-1m17-flagged": "1M17 with moves_flagged: 76 + 66 = 142; 1FIN with moves_flagged: 32 + 24 = 56",
    "X-1fin-one-target": "1FIN chains A and C → one target P24941, two chain rows, 32 moves, excluded 24",
    "X-records-real": "1M17 records: variant L858R filter (15) and 다음 쪽 equal the server pages",
    "X-detail-real": "two 1M17 records expanded: bibliography, UP1, UP4, ten kbase checks, integrity, measured-change "
                     "table rows equal the stored record (observed in memory; only IDs recorded)",
    "X-too-large-real": "LABELLED SYNTHETIC size-test map (1FIN map, chains given P00533 and Q06187) with moves_flagged "
                        "→ 429 result_too_large with the advice, nothing stored",
    "X-report-real": "report of the 1M17 result: downloads equal to the backend bytes (hash only), fixed sentences, no "
                     "quote or observation text, the library entry",
    "X-results-list": "the result list equals the stored list; a file not included shows — with the reason",
    "X-tabs": "구조 분석 hidden and inert, run selection only there, other tabs unchanged",
    "X-no-zero": "not included / not computed values are — with the reason, never 0",
    "X-wording": "no rank / recommendation / verified / effect wording outside fixed sentences and stored strings",
}
NOT_OBSERVED = {
    "fixture": {
        "P-late-response": "late responses of another run / result are covered by the pure guard tests "
                           "(frontend/tests/kinase-precedents.test.cjs precedentResponseCurrent); this flow does not "
                           "hold responses.",
        "P-record-hash-412": "a record whose content_hash no longer matches (412 at call time) needs a set changed "
                             "between the pin and the call; covered by backend/tests/test_kinase_precedents_tool.py.",
    },
    "real": {
        "X-chain-states": "the public structures give linked chains only (1FIN B / D are not requested: M15 refuses them, "
                          "T1); no_mapped_residues and multiple_accessions are observed in the fixture stage.",
        "X-not-in-kbase": "not_in_kbase_references needs a structure outside the allowed downloads (T1 (d)); observed "
                          "in the fixture stage.",
        "X-snapshot-states": "unset / invalid / stale snapshot states are observed on the synthetic set (fixture stage).",
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stages_arg(text: str) -> list[str]:
    stages = [part.strip() for part in text.split(",") if part.strip()]
    if not stages or len(set(stages)) != len(stages) or any(stage not in STAGES for stage in stages):
        raise argparse.ArgumentTypeError(f"--stages takes fixture, real or fixture,real (got {text!r})")
    return [stage for stage in STAGES if stage in stages]


# ---------------------------------------------------------------------------------------------------- plans
def structure(code: Path, rel: Path, provenance: str) -> dict:
    return {"file": str(code / rel), "name": rel.name, "provenance": provenance,
            "sha256": m13.sha_file(code / rel) if (code / rel).is_file() else None}


def target_expect(counts: dict, include_flagged: bool, chains: list[str]) -> dict:
    """The target state of spec 5.4 from the synthetic design counts (independent of the product code)."""
    moves, flagged, refs = counts["moves"], counts["moves_flagged"], counts["references"]
    included = moves + (flagged if include_flagged else 0)
    status = ("precedents_found" if included else "none_in_included_files" if refs else "not_in_kbase_references")
    return {"status": status, "moves": moves, "movesFlagged": flagged if include_flagged else None,
            "excluded": None if include_flagged else flagged, "references": refs, "chains": chains}


def chain_expect(accessions: list[str]) -> list:
    """[status, reason, accession] of spec 5.3 from the accessions a chain's mapped rows carry."""
    if len(accessions) == 1:
        return ["linked", None, accessions[0]]
    return ["not_linked", "no_mapped_residues" if not accessions else "multiple_accessions", None]


def link_expect(chain_accessions: dict[str, list[str]], counts: dict[str, dict], include_flagged: bool) -> dict:
    """Chain and target expectations of one link from the accessions per chain and the synthetic counts."""
    chains = {chain: chain_expect(accs) for chain, accs in chain_accessions.items()}
    linked: dict[str, list[str]] = {}
    for chain, (status, _reason, accession) in chains.items():
        if status == "linked":
            linked.setdefault(accession, []).append(chain)
    empty = {"moves": 0, "moves_flagged": 0, "references": 0}
    targets = {acc: target_expect(counts.get(acc, empty), include_flagged, sorted(names))
               for acc, names in sorted(linked.items())}
    included = sum(t["moves"] + (t["movesFlagged"] or 0) for t in targets.values())
    return {"chains": chains, "targets": targets, "nullResult": included == 0}


def fixture_plan(code: Path, made: dict, dry_run_run: str | None) -> dict:
    """The fixture plan the maps mode follows (structures and the real M15 maps it makes by clicks)."""
    two = FIXTURES / "structures_m15/derived_1mq4_two_chain_fixture.pdb"
    return {
        "schema": "m27_qa_plan@1", "stage": "fixture", "setHash": made["set_hash"], "synthetic": SYNTHETIC_NOTE,
        "structures": {
            "mq4": structure(code, FIXTURES / "public_1mq4.cif", "public PDB entry 1MQ4 (repository fixture)"),
            "two": structure(code, two, "DERIVED M15 test fixture from public 1MQ4 (chain A = residues 200-285, chain B "
                                        "= residues 126-199; structures_m15/provenance_fixture.json)"),
        },
        "maps": [
            {"id": "m1", "structure": "mq4", "pdbConfirm": "1MQ4", "chains": [{"chain": "A", "accession": "sifts",
                                                                               "expect": "O14965"}]},
            {"id": "m2", "structure": "two", "pdbConfirm": None,
             "chains": [{"chain": "A", "accession": "O14965"}, {"chain": "B", "accession": "Q8IU85"}]},
            {"id": "m3", "structure": "two", "pdbConfirm": None,
             "chains": [{"chain": "A", "accession": "O14965"}, {"chain": "B", "accession": "O14965"}]},
        ],
        "derivedFrom": "m3", "dryRunRun": dry_run_run, "expect": made["expect"],
    }


def fixture_main_plan(base: dict, run: str, maps: dict[str, str], derived: dict, dry_run_run: str | None) -> dict:
    """The fixture main plan: links, refusals, previews, records and the expectations counted from the synthetic set."""
    counts = base["expect"]["accessions"]
    real_maps = {"m1": {"A": ["O14965"]}, "m2": {"A": ["O14965"], "B": []}, "m3": {"A": ["O14965"], "B": ["O14965"]}}
    chain_accessions = {**real_maps, **{name: info["chains"] for name, info in derived["maps"].items()}}
    handles = {**maps, **{name: info["handle"] for name, info in derived["maps"].items()}}

    def link(link_id: str, map_id: str, chains: list[str] | None, include: bool, cases: list[str]) -> dict:
        accs = chain_accessions[map_id]
        chosen = {chain: accs[chain] for chain in accs if chains is None or chain in chains}
        return {"id": link_id, "map": map_id, "chains": chains, "includeFlagged": include, "cases": cases,
                "expect": link_expect(chosen, counts, include)}
    links = [
        link("l-m1", "m1", None, False, ["P-target-states", "P-no-zero", "P-fixed-notes"]),
        link("l-m2", "m2", None, False, ["P-chain-states"]),
        link("l-m2-a", "m2", ["A"], False, ["P-chain-select"]),
        # only the chain without mapped residues: no linked target, the empty result says so (not "no records")
        link("l-m2-b", "m2", ["B"], False, ["P-chain-states", "P-no-zero"]),
        link("l-two", "d-two", None, False, ["P-target-states", "P-no-zero", "P-fixed-notes"]),
        link("l-two-incl", "d-two", None, True, ["P-flagged-toggle", "P-no-zero"]),
        link("l-fusion", "d-fusion", None, False, ["P-chain-states", "P-target-states"]),
    ]
    filters = counts["P0QA01"]["filters"]
    return {
        **base, "run": run, "mapHandles": handles, "derived": derived, "links": links,
        "unresolvedTotal": base["expect"]["unresolved"]["moves"] + base["expect"]["unresolved"]["moves_flagged"],
        "unresolvedNamesTotal": base["expect"]["unresolved"]["names_total"],
        "previews": [{"map": "m2", "chains": {"A": ["linked", None], "B": ["not_linked", "no_mapped_residues"]}},
                     {"map": "d-fusion", "chains": {"A": ["not_linked", "multiple_accessions"], "B": ["linked", None]},
                      "accessions": {"A": ["P0QA01", "P0QA03"]}}],
        "refusals": {"map": "m1"},
        "tooLarge": {"map": "d-big", "includeFlagged": True, "cases": ["P-too-large"],
                     "expect": {"withoutFlaggedFits": True, "targets": {"P0QA01": True, "P0QA04": False}}},
        "records": {"link": "l-two-incl", "target": "P0QA01", "filters": filters["include_flagged_true"],
                    "searchToken": base["expect"]["searchToken"], "titleToken": base["expect"]["titleToken"]},
        "paging": {"link": "l-two", "target": "P0QA01", "total": filters["include_flagged_false"]["all"]["total"]},
        "targetTabs": {"link": "l-two", "to": "P0QA02"},
        "detail": {"link": "l-two", "target": "P0QA01", "expand": {
            "MOVE-7001": {"bibliography": True, "truncated": True, "assembled": True, "quotesWithinLimit": True,
                          "roles": ["on_target", "off_target", "not_applicable"], "foldNull": [False, True, True],
                          "fail": ["duplicate"], "lookupFailed": ["chembl_crosscheck"], "structureLinks": 1,
                          "tradeoffNullQuote": True},
            "MOVE-7009": {"bibliography": False, "quotesWithinLimit": False}}},
        "report": {"link": "l-two", "cases": ["P-report"]},
        "dryRun": {"run": dry_run_run, "structure": "mq4",
                   "map": {"id": "dm1", "structure": "mq4", "pdbConfirm": "1MQ4",
                           "chains": [{"chain": "A", "accession": "sifts", "expect": "O14965"}]},
                   "link": {"id": "l-dry", "map": "dm1", "chains": None, "includeFlagged": False, "cases": ["P-dry-run"],
                            "expect": link_expect({"A": ["O14965"]}, counts, False)}},
    }


def real_plan(code: Path, set_hash: str) -> dict:
    """The real stage plan: public structures, the maps made by clicks and the T1-measured counts."""
    return {
        "schema": "m27_qa_plan@1", "stage": "real", "setHash": set_hash, "synthetic": None,
        "structures": {
            "mq4": structure(code, FIXTURES / "public_1mq4.cif", "public PDB entry 1MQ4 (repository fixture)"),
            "m17": structure(code, FIXTURES / "public_1m17.cif", "public PDB entry 1M17 (RCSB CC0, M27 T1 download)"),
            "fin": structure(code, FIXTURES / "public_1fin.cif", "public PDB entry 1FIN (RCSB CC0, M27 T1 download)"),
        },
        "maps": [
            {"id": "rm-mq4", "structure": "mq4", "pdbConfirm": "1MQ4",
             "chains": [{"chain": "A", "accession": "sifts", "expect": "O14965"}]},
            {"id": "rm-m17", "structure": "m17", "pdbConfirm": "1M17",
             "chains": [{"chain": "A", "accession": "sifts", "expect": "P00533"}]},
            {"id": "rm-fin", "structure": "fin", "pdbConfirm": "1FIN",
             "chains": [{"chain": "A", "accession": "sifts", "expect": "P24941"},
                        {"chain": "C", "accession": "sifts", "expect": "P24941"}]},
        ],
        "derivedFrom": "rm-fin", "dryRunRun": None, "expect": REAL_EXPECT,
    }


def real_main_plan(base: dict, run: str, maps: dict[str, str], derived: dict) -> dict:
    counts = {"O14965": {"moves": 0, "moves_flagged": 0, "references": 1},
              "P00533": {"moves": 76, "moves_flagged": 66, "references": 1},
              "P24941": {"moves": 32, "moves_flagged": 24, "references": 1}}
    accs = {"rm-mq4": {"A": ["O14965"]}, "rm-m17": {"A": ["P00533"]}, "rm-fin": {"A": ["P24941"], "C": ["P24941"]}}
    handles = {**maps, **{name: info["handle"] for name, info in derived["maps"].items()}}

    def link(link_id: str, map_id: str, include: bool, cases: list[str], extra: dict | None = None) -> dict:
        expect = link_expect(accs[map_id], counts, include)
        for target, more in (extra or {}).items():
            expect["targets"][target].update(more)
        return {"id": link_id, "map": map_id, "chains": None, "includeFlagged": include, "cases": cases,
                "expect": expect}
    variants = {"L834R": 1, "L858R": 15, "T790M": 4, "WT": 3, "not_reported": 53}
    links = [
        link("l-mq4", "rm-mq4", False, ["X-1mq4-none", "X-no-zero"]),
        link("l-m17", "rm-m17", False, ["X-1m17-found", "X-no-zero"], {"P00533": {"variants": variants}}),
        link("l-m17-incl", "rm-m17", True, ["X-1m17-flagged", "X-no-zero"]),
        link("l-fin", "rm-fin", False, ["X-1fin-one-target"]),
        link("l-fin-incl", "rm-fin", True, ["X-1m17-flagged"]),
    ]
    return {
        **base, "run": run, "mapHandles": handles, "derived": derived, "links": links,
        "unresolvedTotal": REAL_EXPECT["unresolved"], "unresolvedNamesTotal": REAL_EXPECT["unresolvedNamesTotal"],
        "previews": [], "refusals": None,
        "tooLarge": {"map": "d-size", "includeFlagged": True, "cases": ["X-too-large-real"],
                     "expect": {"withoutFlaggedFits": True, "targets": {"P00533": True, "Q06187": True}}},
        "records": {"link": "l-m17", "target": "P00533", "variant": {"value": "L858R", "total": 15}},
        "paging": {"link": "l-m17", "target": "P00533", "total": 76},
        "targetTabs": None,
        "detail": {"link": "l-m17", "target": "P00533", "expandFirst": 2},
        "report": {"link": "l-m17", "cases": ["X-report-real"]},
        "dryRun": None,
    }


# ---------------------------------------------------------------------------------------------------- judgement
def precedent_changes_ok(stage: str, changes: dict) -> bool:
    """The precedent reference folder changes of a stage did what they should (status read back over the API)."""
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
    served = entry("imported")
    return served.get("status") == "pass" and bool(served.get("setHash"))


def import_ok(info: dict) -> bool:
    """Both real imports exited 0 with no socket use, gave two sets with byte-identical files and the T1 counts."""
    imports = info.get("imports") or []
    if len(imports) != 2 or any(item.get("exitCode") != 0 or item.get("networkAttempts") != 0 or item.get("loaded")
                                or not item.get("setHash") or not item.get("filesMatchManifest") for item in imports):
        return False
    first, second = imports
    return (first["setHash"] != second["setHash"] and info.get("reproducible") is True
            and first.get("rows") == second.get("rows") and first.get("rows", {}).get("files") == REAL_EXPECT["files"]
            and first.get("rows", {}).get("bibliography") == REAL_EXPECT["bibliographyRows"]
            and first.get("verification", {}).get("records_hash_verified") == REAL_EXPECT["verification"]
            and first.get("dirty") is False and info.get("activeIsSecond") is True)


def assemble(rows: list[dict], leftovers: list[str], stages: list[str], checks: dict, leaks: list[str]) -> dict:
    """Judge every requested stage (latest row per step, the stage's cases, its folder changes) and record the others
    as missing. ``checks`` = {stage: {"precedent", "m15", "derive", "import"}}. Returns
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
        m15_ok = (stage_checks.get("m15") or {}).get("status") == "pass"
        derive_ok = (stage_checks.get("derive") or {}).get("status") == "pass"
        cases[f"S-{stage}-references"] = {
            "stage": stage, "text": ("the precedent set changes (none, set A, active.json aside, one file tampered, "
                                     "set B) and the read-only M15 copy, read back over the API; the derived maps "
                                     "stored from a real M15 map"
                                     if stage == "fixture" else
                                     "the imported real set served, the read-only M15 copy and the derived "
                                     "size-test map stored from the real 1FIN map"),
            "status": "pass" if precedent_changes_ok(stage, stage_checks.get("precedent") or {}) and m15_ok
            and derive_ok else "fail"}
        if stage == "real":
            cases["S-real-import"] = {
                "stage": stage, "text": "the user import command run twice on the real kbase dist/ (sockets refused "
                                        "and counted: 0): exit 0, rows 891 / 885 / 555 and 252, verification "
                                        "891 / 885 / 555, dirty false, two sets with byte-identical files",
                "status": "pass" if import_ok(stage_checks.get("import") or {}) else "fail"}
        parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
                 "cases": all(v["status"] == "pass" for v in cases.values())}
        judged_stages[stage] = {"status": "pass" if all(parts.values()) else "fail", "steps": steps,
                                "parts": parts, "notObserved": dict(NOT_OBSERVED[stage])}
        all_cases.update(cases)
    missing = [stage for stage in STAGES if judged_stages[stage]["status"] == "missing"]
    ran = [stage for stage in STAGES if stage not in missing]
    parts = {"stagesRan": bool(ran) and all(judged_stages[stage]["status"] == "pass" for stage in ran),
             "bothStages": not missing, "leftoverProcesses": not leftovers, "noRealTextInEvidence": not leaks}
    counts = {"cases": len(all_cases), "passed": sum(1 for v in all_cases.values() if v["status"] == "pass"),
              "failed": sum(1 for v in all_cases.values() if v["status"] != "pass")}
    return {"stages": judged_stages, "cases": all_cases, "missingStages": missing, "counts": counts,
            "verdictParts": parts,
            "passed": parts["stagesRan"] and parts["leftoverProcesses"] and parts["noRealTextInEvidence"]}


def acceptance_ok(judged: dict, build: dict | None) -> bool:
    """True only when both stages ran in this invocation and passed, nothing was left, no real kbase text reached the
    committed evidence and the build was stamped."""
    return (judged["passed"] and judged["verdictParts"]["bothStages"]
            and bool((build or {}).get("buildCurrentWithSource")))


def browser_hosts(rows: list[dict]) -> list[str]:
    hosts: set[str] = set()
    for row in rows:
        hosts.update(row.get("blockedHosts") or [])
    return sorted(hosts)


# ---------------------------------------------------------------------------------------------------- evidence rules
def normalize_text(text: str) -> str:
    """The form real kbase strings and evidence text are compared in: whitespace collapsed, trimmed, case folded."""
    return " ".join(text.split()).casefold()


def real_text_strings(set_dir: Path, min_chars: int = REAL_TEXT_MIN_CHARS) -> set[str]:
    """Normalized strings of an installed precedent set that committed evidence must never contain (at least
    ``min_chars`` once normalized): observation text and quote, tradeoff text and quote, change description, effect
    assay, assay context and comparability reason, bibliography title and journal, and the reference fields a result
    carries (``REFERENCE_TEXT_FIELDS``). Identifiers, hashes and closed codes are not taken."""
    found: set[str] = set()

    def keep(value) -> None:
        if isinstance(value, str) and len(normalize_text(value)) >= min_chars:
            found.add(normalize_text(value))

    def lines(path: Path):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
    for name in ("moves.jsonl", "moves_flagged.jsonl"):
        for record in lines(set_dir / "files" / "dist" / name):
            observation = record.get("observation") or {}
            keep(observation.get("text"))
            keep(observation.get("quote"))
            for tradeoff in record.get("tradeoffs") or []:
                if isinstance(tradeoff, dict):
                    keep(tradeoff.get("text"))
                    keep(tradeoff.get("quote"))
            change = record.get("change")
            if isinstance(change, dict):
                keep(change.get("description"))
            for effect in record.get("effects") or []:
                if isinstance(effect, dict):
                    keep(effect.get("assay"))
                    keep(effect.get("assay_context"))
                    keep(effect.get("comparability_reason"))
    for reference in lines(set_dir / "files" / "dist" / "references.jsonl"):
        for key in REFERENCE_TEXT_FIELDS:
            keep(reference.get(key))
    for path in sorted((set_dir / "files" / "pubmed").glob("*/documents.jsonl")):
        for row in lines(path):
            data = row.get("data") or {}
            keep(data.get("title"))
            keep(data.get("journal"))
    return found


_JSON_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|[\"\\/bfnrt])")
_JSON_SIMPLE = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+.!|>~-])")


def _json_unescape(text: str) -> str:
    """One level of JSON string escapes undone (``\\uXXXX`` with surrogate pairs, ``\\"``, ``\\n`` …)."""
    def one(match: re.Match) -> str:
        token = match.group(1)
        return chr(int(token[1:], 16)) if token[0] == "u" else _JSON_SIMPLE.get(token, token)
    return _JSON_ESCAPE.sub(one, text).encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def text_views(text: str) -> list[str]:
    """A text as written, with up to ``REAL_TEXT_DECODE_ROUNDS`` levels of JSON escapes undone, and each of those with
    the report's Markdown escape (backslash before Markdown syntax, then HTML entities) undone; all normalized."""
    views = [text]
    for _ in range(REAL_TEXT_DECODE_ROUNDS):
        decoded = _json_unescape(views[-1])
        if decoded == views[-1]:
            break
        views.append(decoded)
    views += [html.unescape(_MARKDOWN_ESCAPE.sub(r"\1", view)) for view in list(views)]
    return list(dict.fromkeys(normalize_text(view) for view in views))


class RealText:
    """The normalized real kbase strings of one installed set, in memory only (never written): every
    ``REAL_TEXT_FRAGMENT_CHARS``-character window of the long ones, and the ones of ``REAL_TEXT_MIN_CHARS`` up to the
    fragment length whole (indexed by their first ``REAL_TEXT_MIN_CHARS`` characters)."""

    def __init__(self, strings: Iterable[str] = ()) -> None:
        self.strings = frozenset(item for item in map(normalize_text, strings) if len(item) >= REAL_TEXT_MIN_CHARS)
        size = REAL_TEXT_FRAGMENT_CHARS
        self.fragments = frozenset(item[i:i + size] for item in self.strings if len(item) >= size
                                   for i in range(len(item) - size + 1))
        whole: dict[str, set[str]] = {}
        for item in self.strings:
            if len(item) < size:
                whole.setdefault(item[:REAL_TEXT_MIN_CHARS], set()).add(item)
        self.whole = {key: tuple(sorted(items)) for key, items in whole.items()}

    def __len__(self) -> int:
        return len(self.strings)

    def _in_view(self, view: str) -> bool:
        size, head = REAL_TEXT_FRAGMENT_CHARS, REAL_TEXT_MIN_CHARS
        for i in range(len(view) - head + 1):
            if view[i:i + size] in self.fragments:
                return True
            for item in self.whole.get(view[i:i + head], ()):
                if view.startswith(item, i):
                    return True
        return False

    def found_in(self, text: str) -> bool:
        return bool(self.strings) and any(self._in_view(view) for view in text_views(text))


def contains_any(text: str, strings: RealText) -> bool:
    """Whether ``text`` holds a real kbase string by the rule of ``RealText`` (pieces, whole short ones, escapes)."""
    return strings.found_in(text)


def hold_reason(artifacts: Path, path: Path, strings: RealText) -> str | None:
    """Why a text artifact stays out of the committed evidence (hash only), or None to export it."""
    rel = path.relative_to(artifacts)
    if "downloads" in rel.parts:
        return "download"
    if path.name.endswith(FAILURE_PANEL_SUFFIX):
        return "failure_panel"
    if path.stat().st_size > MAX_TEXT_BYTES and path.name not in LEDGER_NAMES:
        return "over_256KiB"
    if strings and contains_any(path.read_text(encoding="utf-8", errors="replace"), strings):
        return "real_kbase_text"
    return None


def import_summary(entry_a: dict, entry_b: dict) -> bool:
    """Two installs of the same input are reproducible: every file's SHA-256 equal and the manifests equal apart
    from ``imported_at``."""
    return (bool(entry_a.get("fileSha256")) and entry_a.get("fileSha256") == entry_b.get("fileSha256")
            and entry_a.get("manifestWithoutImportedAt") == entry_b.get("manifestWithoutImportedAt"))


# ---------------------------------------------------------------------------------------------------- runner
class Runner(m15.Runner):
    """The M15 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw path
    check, allowlisted env, leftover check) with per-stage isolated folders, the precedent reference changes, the
    derived maps, the guarded real import, the M27 flow, the two-stage ledger and the hash-only export rules."""

    api = m18.Runner.api
    provider_zero = m18.Runner.provider_zero

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m27-precedents-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.stages: list[str] = list(args.stages)
        source = Path(args.m15_reference)
        self.m15_source = (source if source.is_absolute() else self.code / source).resolve()
        if self.root == self.m15_source or self.root in self.m15_source.parents:
            raise SystemExit("--m15-reference must not be inside --root (it is copied, never written)")
        if not (self.m15_source / "active.json").is_file() or not (self.m15_source / "sets").is_dir():
            raise SystemExit(f"--m15-reference has no active.json and sets/: {self.m15_source}")
        if "real" in self.stages and not (self.kbase / "dist" / "manifest.json").is_file():
            raise SystemExit(f"the real stage needs --kbase with dist/manifest.json: {self.kbase}")
        self.stage: str | None = None
        self.precedent = self.root / "precedent_reference"
        self.reaction = self.root / "reaction_reference"
        self.checks: dict[str, dict] = {stage: {"precedent": {}, "m15": {}, "derive": {}, "import": {}}
                                        for stage in STAGES}
        self.plans: dict[str, dict] = {}
        self.setup: dict[str, dict] = {stage: {} for stage in STAGES}
        self.real_strings = RealText()
        self.held: dict[str, str] = {}

    # ----- folders and services --------------------------------------------------------------------
    def use_stage(self, stage: str) -> None:
        self.stage = stage
        base = self.root / stage
        self.runs, self.reference = base / "runs", base / "reference"
        self.precedent, self.reaction = base / "precedent_reference", base / "reaction_reference"

    def backend_env(self) -> dict[str, str]:
        return m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(self.runs),
                              "MW_REFERENCE_DIR": str(self.reference),
                              "MW_PRECEDENT_REFERENCE_DIR": str(self.precedent),
                              "MW_REACTION_REFERENCE_DIR": str(self.reaction)})

    def start_backend(self) -> None:
        env = self.backend_env()
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
                                                      "precedentReference": str(self.precedent),
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
        base = {"schema": "m27_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- M15 reference: a read-only copy of the active set (the source is never written) -----------------------
    def m15_copy(self) -> dict:
        before = m13.tree_digest(self.m15_source)
        if self.reference.exists():
            if any(self.reference.iterdir()):
                raise RuntimeError(f"{self.reference} is not empty")
            self.reference.rmdir()
        shutil.copytree(self.m15_source, self.reference, symlinks=False)
        for path in self.reference.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        after = m13.tree_digest(self.m15_source)
        copied = m13.tree_digest(self.reference)
        active = json.loads((self.reference / "active.json").read_text())["set_hash"]
        entry = {"status": "pass" if before == after == copied else "fail", "source": str(self.m15_source),
                 "setHash": active, "files": len(copied), "readOnly": True,
                 "treeSha256": m13.sha_bytes(json.dumps(copied, sort_keys=True).encode())}
        self.checks[self.stage]["m15"] = entry
        return entry

    def m15_served(self) -> None:
        entry = self.checks[self.stage]["m15"]
        served = self.get_json("/reference/snapshots")
        entry["served"] = {key: served.get(key) for key in ("available", "set_hash", "reason_code")}
        if not (served.get("available") is True and served.get("set_hash") == entry.get("setHash")):
            entry["status"] = "fail"
            entry["problem"] = "the backend does not serve the copied M15 set"
        self.record(f"{self.stage}-m15-copy", entry["status"], setHash=entry.get("setHash"), served=entry["served"])
        self.state["checks"] = self.checks
        self.save()

    # ----- precedent reference folder (subprocess builder and importer, file moves; never imports mw) --------------
    def precedent_status(self) -> dict:
        served = self.get_json("/precedent_reference/status")
        return {key: served.get(key) for key in ("installed", "reason", "set_hash", "imported_at")}

    def precedent_change(self, name: str, action, expect: dict) -> dict:
        """Apply one change to the stage's precedent folder and read the status back over the API. Returns the
        recorded entry (``status`` pass only when the served status matches ``expect`` and any new set hash)."""
        entry: dict = {"status": "fail", "at": now()}
        try:
            entry.update(action() or {})
            served = self.precedent_status()
            entry["served"] = served
            ok = all(served.get(key) == value for key, value in expect.items())
            if "setHash" in entry:
                ok = ok and served.get("set_hash") == entry["setHash"]
            entry["status"] = "pass" if ok else "fail"
            if not ok:
                entry["problem"] = f"served {served} does not match {expect}"
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            entry["problem"] = f"{type(exc).__name__}: {exc}"
        self.checks[self.stage]["precedent"][name] = entry
        self.state["checks"] = self.checks
        self.record(f"{self.stage}-precedent-{name}", entry["status"], setHash=entry.get("setHash"),
                    served=entry.get("served"), problem=entry.get("problem"))
        self.save()
        return entry

    def builder(self, argv: list[str], log_name: str) -> dict:
        log = self.artifacts / "services" / f"{log_name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        full = [str(self.python), str(self.code / QA_SET_BUILDER), *argv]
        proc = subprocess.run(full, cwd=self.code, env=m13.child_env(), capture_output=True, text=True, timeout=600,
                              check=False)
        log.write_text(json.dumps({"argv": full, "exitCode": proc.returncode}) + "\n" + proc.stdout + proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"build_qa_set.py exited {proc.returncode}; see {log}")
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def build_qa_set(self, imported_at: str | None = None) -> dict:
        argv = ["set", "--root", str(self.precedent)]
        if imported_at:
            argv += ["--imported-at", imported_at]
        made = self.builder(argv, f"qa-set-{imported_at or 'a'}")
        self.setup[self.stage].setdefault("sets", []).append({k: made[k] for k in ("set_hash", "imported_at", "rows")})
        return {"setHash": made["set_hash"], "importedAt": made["imported_at"], "rows": made["rows"],
                "builder": str(QA_SET_BUILDER), "label": made["label"], "made": made}

    def active_set(self) -> str:
        return json.loads((self.precedent / "active.json").read_text())["set_hash"]

    def unset_active(self) -> dict:
        (self.precedent / "active.json").rename(self.precedent / "active.json.qa-unset")
        return {"moved": "active.json -> active.json.qa-unset"}

    def tamper_active(self) -> dict:
        (self.precedent / "active.json.qa-unset").rename(self.precedent / "active.json")
        target = self.precedent / "sets" / self.active_set() / TAMPER_FILE
        before = m13.sha_file(target)
        with target.open("ab") as out:
            out.write(TAMPER_BYTES)
        return {"restored": "active.json", "tampered": TAMPER_FILE, "sha256Before": before,
                "sha256After": m13.sha_file(target)}

    def import_once(self, number: int) -> dict:
        """One user import of the real kbase dist/ into the isolated folder, in a child whose sockets are refused."""
        argv = [str(self.python), "-I", "-c", NETWORK_GUARD, str(self.code / IMPORTER), "--from", str(self.kbase),
                "--dest", str(self.precedent), "--yes"]
        log = self.artifacts / "services" / f"import-{number}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(argv, cwd=self.code, env=m13.child_env(), capture_output=True, text=True, timeout=900,
                              check=False)
        log.write_text(json.dumps({"argv": argv[:3] + ["<guard>"] + argv[4:], "exitCode": proc.returncode}) + "\n"
                       + proc.stdout + proc.stderr)
        guard = next((json.loads(line[len("QA-NETWORK "):]) for line in proc.stdout.splitlines()
                      if line.startswith("QA-NETWORK ")), None)
        entry: dict = {"number": number, "exitCode": proc.returncode, "log": str(log),
                       "networkAttempts": None if guard is None else guard["attempts"],
                       "loaded": None if guard is None else guard["loaded"]}
        if proc.returncode != 0:
            return entry
        set_hash = self.active_set()
        set_dir = self.precedent / "sets" / set_hash
        manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
        files = [*manifest["files"], manifest["bibliography"]["file"]]
        digests = {item["name"]: m13.sha_file(set_dir / item["path"]) for item in files}
        entry.update({
            "setHash": set_hash, "importedAt": manifest["imported_at"],
            "manifestSha256": m13.sha_file(set_dir / "manifest.json"),
            "fileSha256": digests, "filesMatchManifest": all(digests[item["name"]] == item["sha256"] for item in files),
            "rows": {"files": {item["name"]: item["rows"] for item in manifest["files"]},
                     "bibliography": manifest["bibliography"]["file"]["rows"]},
            "verification": manifest["verification"], "dirty": manifest["kbase"]["dirty"],
            "kbase": {key: manifest["kbase"][key] for key in ("commit", "dist_commit", "dist_commit_date", "dirty",
                                                              "kb_version")},
            "manifestWithoutImportedAt": m13.sha_bytes(json.dumps(
                {k: v for k, v in manifest.items() if k != "imported_at"}, sort_keys=True).encode()),
        })
        return entry

    def import_real(self) -> dict:
        imports = [self.import_once(1)]
        time.sleep(1.2)   # imported_at has whole seconds: the second install needs another second
        imports.append(self.import_once(2))
        ok = all(item.get("setHash") for item in imports)
        info = {"imports": imports, "kbase": str(self.kbase), "dest": str(self.precedent),
                "reproducible": ok and import_summary(*imports),
                "activeIsSecond": ok and self.active_set() == imports[1]["setHash"],
                "defaultFolderUntouched": not (self.code / ".deps" / "precedent_reference").exists()}
        info["status"] = "pass" if import_ok(info) and info["defaultFolderUntouched"] else "fail"
        self.checks[self.stage]["import"] = info
        self.state["checks"] = self.checks
        self.record("real-import", info["status"], sets=[item.get("setHash") for item in imports],
                    networkAttempts=[item.get("networkAttempts") for item in imports],
                    reproducible=info["reproducible"])
        self.save()
        if ok:
            self.real_strings = RealText(real_text_strings(self.precedent / "sets" / imports[1]["setHash"]))
        return info

    # ----- derived maps (backend stopped; a subprocess stores them in the run) --------------------------------------
    def derive(self, run: str, source: str) -> dict | None:
        entry: dict = {"status": "fail", "run": run, "source": source, "at": now()}
        self.stop_backend()
        try:
            made = self.builder(["derive", "--runs", str(self.runs), "--run", run, "--source", source,
                                 "--stage", self.stage], f"derive-{self.stage}")
            entry.update({"status": "pass", "maps": made["maps"]})
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            entry["problem"] = f"{type(exc).__name__}: {exc}"
            made = None
        finally:
            self.start_backend()
        self.checks[self.stage]["derive"] = entry
        self.state["checks"] = self.checks
        self.record(f"{self.stage}-derive-maps", entry["status"], maps=sorted(entry.get("maps") or {}),
                    problem=entry.get("problem"))
        self.save()
        return made

    # ----- run setup over the loopback API (no tool, no job, no limit change) -------------------------------------
    def dry_run_run(self) -> str | None:
        status, made = self.api("POST", "/runs", {"goal": "M27 QA dry-run run (setup record; later steps are real "
                                                          "clicks)", "context": [], "dry_run": True,
                                                  "egress": "local_only"})
        ok = status in (200, 201) and isinstance(made, dict) and made.get("dry_run") is True
        self.setup[self.stage]["dryRunRun"] = {"status": status, "run": (made or {}).get("run_id") if ok else None,
                                               "label": "QA setup record: dry-run run made through POST /runs (the "
                                                        "UI has no dry-run control)"}
        self.record(f"{self.stage}-setup-dry-run-run", "pass" if ok else "fail", httpStatus=status)
        return made.get("run_id") if ok else None

    # ----- flows ---------------------------------------------------------------------------------------------------
    def write_plan(self, name: str, plan: dict) -> Path:
        path = self.artifacts / f"{name}-plan.json"
        path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
        self.plans[name] = plan
        return path

    def flow(self, step: str, extra: list[str]) -> dict | None:
        mode = MODE_OF[step]
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / FLOW), "--url", m15.WEB, "--mode", mode, "--artifacts", str(step_dir),
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

    def fresh_folders(self) -> None:
        for folder in (self.runs, self.precedent, self.reaction):
            folder.mkdir(parents=True, exist_ok=True)

    def maps_of(self, row: dict | None) -> tuple[str | None, dict[str, str]]:
        row = row or {}
        return (row.get("runs") or {}).get("A"), dict((row.get("handles") or {}).get("maps") or {})

    def run_fixture(self) -> None:
        self.use_stage("fixture")
        self.fresh_folders()
        self.m15_copy()
        self.start_backend()
        try:
            self.m15_served()
            self.precedent_change("empty-at-start", dict, {"installed": False, "reason": "not_installed"})
            self.flow("fixture-empty", [])
            first = self.precedent_change("set-a", self.build_qa_set, {"installed": True, "reason": None})
            made = first.pop("made", None)
            dry = self.dry_run_run()
            if not (first["status"] == "pass" and made and dry and self.checks["fixture"]["m15"]["status"] == "pass"):
                self.skip(STEPS["fixture"][1:], "a prerequisite failed (set A, the M15 copy or the dry-run run)")
                return
            base = fixture_plan(self.code, made, dry)
            maps_row = self.flow("fixture-maps", ["--plan", str(self.write_plan("fixture", base))])
            run, maps = self.maps_of(maps_row)
            if not run or set(maps) != {"m1", "m2", "m3"}:
                self.skip(STEPS["fixture"][2:], "fixture-maps recorded no run or not every map")
                return
            derived = self.derive(run, maps[base["derivedFrom"]])
            if derived is None:
                self.skip(STEPS["fixture"][2:], "the derived maps were not stored")
                return
            plan = self.write_plan("fixture-main", fixture_main_plan(base, run, maps, derived, dry))
            main = self.flow("fixture-main", ["--plan", str(plan)]) or {}
            runs = [item for item in (run, (main.get("runs") or {}).get("D")) if item]
            listed = ["--runs", ",".join(runs), "--plan", str(plan)]
            set_a = first["setHash"]
            if self.precedent_change("unset", self.unset_active,
                                     {"installed": False, "reason": "not_installed"})["status"] == "pass":
                self.flow("fixture-unset", [*listed, "--set-hash", set_a])
            else:
                self.skip(["fixture-unset"], "moving active.json aside did not give not_installed")
            if self.precedent_change("tamper", self.tamper_active,
                                     {"installed": False, "reason": "snapshot_invalid"})["status"] == "pass":
                self.flow("fixture-invalid", [*listed, "--set-hash", set_a])
            else:
                self.skip(["fixture-invalid"], "tampering did not give snapshot_invalid")
            second = self.precedent_change("set-b", lambda: self.build_qa_set(SECOND_IMPORTED_AT),
                                           {"installed": True, "reason": None})
            second.pop("made", None)
            set_b = second.get("setHash") if second["status"] == "pass" else None
            if set_b and set_b != set_a:
                self.flow("fixture-stale", [*listed, "--set-hash", set_b, "--previous-set-hash", set_a])
            else:
                self.skip(["fixture-stale"], "set B was not installed")
        finally:
            self.stop_backend()

    def run_real(self) -> None:
        self.use_stage("real")
        self.fresh_folders()
        self.m15_copy()
        info = self.import_real()
        self.start_backend()
        try:
            self.m15_served()
            second = (info["imports"][1] if len(info["imports"]) == 2 else {}).get("setHash")
            entry = self.precedent_change("imported", lambda: {"setHash": second} if second else {},
                                          {"installed": True, "reason": None})
            if not (second and entry["status"] == "pass" and self.checks["real"]["m15"]["status"] == "pass"):
                self.skip(STEPS["real"], "a prerequisite failed (the real import or the M15 copy)")
                return
            base = real_plan(self.code, second)
            maps_row = self.flow("real-maps", ["--plan", str(self.write_plan("real", base))])
            run, maps = self.maps_of(maps_row)
            if not run or set(maps) != {"rm-mq4", "rm-m17", "rm-fin"}:
                self.skip(["real-main"], "real-maps recorded no run or not every map")
                return
            derived = self.derive(run, maps[base["derivedFrom"]])
            if derived is None:
                self.skip(["real-main"], "the derived size-test map was not stored")
                return
            plan = self.write_plan("real-main", real_main_plan(base, run, maps, derived))
            self.flow("real-main", ["--plan", str(plan)])
        finally:
            self.stop_backend()

    # ----- ledger and evidence -------------------------------------------------------------------------------------
    def scan_held(self) -> dict[str, str]:
        """Hold decision of every text artifact (relative path → reason); ``real_kbase_text`` entries are leaks."""
        held: dict[str, str] = {}
        for path in sorted(self.artifacts.rglob("*")):
            rel = path.relative_to(self.artifacts)
            if (not path.is_file() or rel.parts[0] == "services" or "browser-profile" in rel.parts
                    or path.suffix not in TEXT_SUFFIXES):
                continue
            reason = hold_reason(self.artifacts, path, self.real_strings)
            if reason:
                held[str(rel)] = reason
        return held

    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "stage": row.get("stage"),
                         "status": row.get("status"), "cases": row.get("cases") or {}, "runs": row.get("runs"),
                         "runId": row.get("runId"), "evidenceKind": row.get("evidenceKind"),
                         "handles": row.get("handles", {}), "inputs": row.get("inputs", []),
                         "fixtureLabels": row.get("fixtureLabels", []), "controls": row.get("controls", {}),
                         "setHash": row.get("setHash"), "observations": row.get("observations", {}),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "blockedHosts": row.get("blockedHosts") or sorted({item.get("origin") for item in (
                             (row.get("offscreen") or {}).get("blockedRequests") or [])}),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        self.held = self.scan_held()
        leaks = sorted(rel for rel, reason in self.held.items() if reason == "real_kbase_text")
        judged = assemble(rows, leftovers, self.stages, self.checks, leaks)
        build = self.state.get("build")
        acceptance = acceptance_ok(judged, build)
        ledger = {"schema": "m27_case_ledger@1", "generatedAt": now(), "build": build,
                  "stagesRequested": self.stages, "missingStages": judged["missingStages"],
                  "verdict": "pass" if judged["passed"] else "fail", "acceptance": acceptance,
                  "acceptanceRule": "both stages ran in this invocation and passed, nothing left, no real kbase text "
                                    "in the committed evidence, build stamped",
                  "verdictParts": judged["verdictParts"], "counts": judged["counts"], "stages": judged["stages"],
                  "cases": judged["cases"], "checks": self.checks, "setup": self.setup,
                  "plans": {name: str(self.artifacts / f"{name}-plan.json") for name in self.plans},
                  "syntheticNote": SYNTHETIC_NOTE if "fixture" in self.stages else None,
                  "reference": {"kbase": str(self.kbase), "m15Source": str(self.m15_source),
                                "defaultPrecedentFolderUntouched":
                                    not (self.code / ".deps" / "precedent_reference").exists()},
                  "realTextLeaks": leaks, "realTextStringsChecked": len(self.real_strings),
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

    def summary_json(self, ledger: dict) -> dict:
        imports = (ledger["checks"].get("real") or {}).get("import") or {}
        return {"schema": "m27_acceptance_summary@1", "generatedAt": ledger["generatedAt"],
                "acceptance": ledger["acceptance"], "verdict": ledger["verdict"], "counts": ledger["counts"],
                "stagesRequested": ledger["stagesRequested"], "missingStages": ledger["missingStages"],
                "stages": {stage: info["status"] for stage, info in ledger["stages"].items()},
                "verdictParts": ledger["verdictParts"], "browserHostsContacted": ledger["browserHostsContacted"],
                "externalRequestsTotal": ledger["externalRequestsTotal"],
                "importNetworkAttempts": [item.get("networkAttempts") for item in imports.get("imports") or []],
                "import": {key: imports.get(key) for key in ("status", "reproducible", "activeIsSecond",
                                                             "defaultFolderUntouched")} if imports else None,
                "importSets": [{key: item.get(key) for key in ("setHash", "importedAt", "rows", "verification",
                                                               "dirty", "kbase", "fileSha256")}
                               for item in imports.get("imports") or []],
                "m15": {stage: {k: (ledger["checks"].get(stage) or {}).get("m15", {}).get(k)
                                for k in ("status", "setHash", "files", "treeSha256")} for stage in self.stages},
                "derivedMaps": {stage: sorted(((ledger["checks"].get(stage) or {}).get("derive") or {}).get("maps")
                                              or {}) for stage in self.stages},
                "realTextLeaks": ledger["realTextLeaks"], "realTextStringsChecked": ledger["realTextStringsChecked"],
                "leftoverProcesses": ledger["leftoverProcesses"], "build": ledger["build"]}

    def readme(self, ledger: dict, held: list[dict]) -> str:
        lines = ["# M27 키나아제 전례 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}** (두 단계가 이번 실행에서 모두 돌고 통과하고, 실제 kbase 문구가 "
                  "커밋 증거에 없을 때만 true)"),
                 (f"- 요청한 단계: {', '.join(ledger['stagesRequested'])} · 빠진 단계: "
                  f"{', '.join(ledger['missingStages']) or '없음'}"),
                 f"- 사례: {ledger['counts']['passed']}/{ledger['counts']['cases']} 통과",
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 (f"- 브라우저 비-loopback 요청 합계: {ledger['externalRequestsTotal']} · 접촉한 외부 호스트: "
                  f"{', '.join(ledger['browserHostsContacted']) or '없음'}"),
                 (f"- 커밋 증거에서 찾은 실제 kbase 문구: {len(ledger['realTextLeaks'])}개 파일 (검사한 문자열 "
                  f"{ledger['realTextStringsChecked']}개)"), ""]
        if ledger.get("syntheticNote"):
            lines += [("**fixture 단계의 전례 값은 모두 합성(SYNTHETIC)이다.** "
                       "`backend/tests/fixtures/precedent/t8/build_qa_set.py`가 `precedent_fixture.py`로 만든 세트"
                       "(지어낸 accession P0QA01–P0QA04, PMID 9100000n, `MOVE-7xxx`, SYNTHETIC 문구; "
                       "`SYNTHETIC-PROVENANCE-t8.md`)이고, 파생 번호 대응(d-two·d-fusion·d-big)은 M15 도구가 만든 실제 "
                       "번호 대응의 mapped 행 accession만 지어낸 값으로 바꾼 합성 변형이다. 관찰은 화면이 저장된 값을 그대로 "
                       "보이는지에 대한 것이며 과학 결과가 아니다."), ""]
        if "real" in ledger["stagesRequested"]:
            lines += [("**real 단계는 실제 kbase_kinase `dist/`를 사용자 가져오기 명령으로 격리 폴더에 두 번 설치해 썼다**"
                       "(소켓을 막고 센 자식 프로세스, 시도 0). 구조는 공개 PDB 항목 1MQ4(저장소)·1M17·1FIN(T1 내려받기, "
                       "RCSB CC0)이고 1FIN은 체인 A·C만 번호 대응에 넣었다. 크기 시험용 d-size 하나만 합성 변형(1FIN "
                       "번호 대응의 두 체인에 P00533·Q06187을 준 것, 1 MiB 초과로 거절되어 저장되지 않음)이다. "
                       "이 폴더에는 실제 전례 문구(인용문·관찰 문장·교환 문장·변형 설명·서지 제목)가 없다: 화면 캡처·"
                       "paint 프레임·보고서 다운로드·실패 패널은 Git 제외 artifacts 폴더에만 있고 아래 목록에는 경로·"
                       "크기·SHA-256만 있다. 기록한 숫자는 개수이고 상태는 닫힌 집합 값이다."), ""]
        lines += ["## 무엇이 커밋이고 무엇이 Git 제외인가", "",
                  "| 커밋(이 폴더) | Git 제외(artifacts 폴더, 해시만 여기) |", "|---|---|",
                  ("| `README.md`, `summary.json`(요약), `cases.json`(사례 목록), `SHA256SUMS`(해시 목록), "
                   "`binary-artifacts.json`(Git 제외 파일 목록과 해시), `evidence/`(대장·단계 기록·계획·요청 기록, "
                   "fixture 합성 결과) | PNG(스크린숏·paint), `downloads/`(보고서 Markdown·JSON), 실패 패널 HTML, "
                   "256 KiB 초과 텍스트(결정 0020), 실제 kbase 문구가 든 텍스트, 실데이터 세트·run 폴더(`--root`) |"),
                  ""]
        lines += [f"Git 제외로 둔 텍스트 {len(held)}개: "
                  + ", ".join(f"{reason} {sum(1 for h in held if h['held'] == reason)}"
                              for reason in sorted({h["held"] for h in held})) if held else "Git 제외로 둔 텍스트 없음",
                  "", "절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다.", ""]
        imports = (ledger["checks"].get("real") or {}).get("import") or {}
        if imports.get("imports"):
            lines += ["## 가져오기 실검증 (real)", "", "| 설치 | 종료 | 소켓 시도 | 세트 해시 | 행 수 | verification | dirty |",
                      "|---|---|---|---|---|---|---|"]
            for item in imports["imports"]:
                rows = item.get("rows") or {}
                lines.append(f"| {item.get('number')} | {item.get('exitCode')} | {item.get('networkAttempts')} | "
                             f"`{item.get('setHash')}` | {json.dumps(rows, ensure_ascii=False)} | "
                             f"{json.dumps(item.get('verification'), ensure_ascii=False)} | {item.get('dirty')} |")
            lines += ["", (f"- 두 설치의 파일 SHA-256 같음(재현): {imports.get('reproducible')} · 활성 세트 = 두 번째 설치: "
                           f"{imports.get('activeIsSecond')} · 기본 폴더 `.deps/precedent_reference` 만들지 않음: "
                           f"{imports.get('defaultFolderUntouched')}"), ""]
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
            for name, value in (ledger["checks"].get(stage) or {}).get("precedent", {}).items():
                lines.append(f"| precedent-{name} | {value.get('status')} | {value.get('problem', '')} |")
            m15_entry = (ledger["checks"].get(stage) or {}).get("m15") or {}
            lines.append(f"| m15-copy | {m15_entry.get('status')} | {m15_entry.get('problem', '')} |")
            derive_entry = (ledger["checks"].get(stage) or {}).get("derive") or {}
            lines.append(f"| derived-maps | {derive_entry.get('status')} | {derive_entry.get('problem', '')} |")
            lines += ["", "관찰하지 않은 사례:", ""]
            lines += [f"- {case}: {reason}" for case, reason in info["notObserved"].items()] or ["- 없음"]
            lines.append("")
        lines += ["## 다시 실행하는 명령 (메인 체크아웃 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m27_offscreen_acceptance.py --root runs/m27-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m27-acceptance/<label> \\",
                  "    --kbase <abs>/kbase_kinase --stages fixture,real --out docs/qa/m27-precedents-<YYYYMMDD>/acceptance",
                  "```"]
        return "\n".join(lines) + "\n"

    def export(self, ledger: dict) -> None:
        replacements = [(str(self.code), "<repo>"), (str(REPO), "<repo>"), (str(Path.home()), "<home>")]
        self.out.mkdir(parents=True, exist_ok=True)
        held_map = self.scan_held()   # again: case-ledger.json exists now
        sums, files, held = [], [], []
        for path in sorted(self.artifacts.rglob("*")):
            rel = path.relative_to(self.artifacts)
            if not path.is_file() or rel.parts[0] == "services" or "browser-profile" in rel.parts:
                continue
            record = {"path": str(rel), "bytes": path.stat().st_size, "sha256": m13.sha_file(path)}
            if path.suffix in TEXT_SUFFIXES and str(rel) not in held_map:
                target = self.out / "evidence" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(m13.redact(path.read_text(errors="replace"), replacements))
                sums.append(f"{m13.sha_file(target)}  evidence/{rel}")
            elif path.suffix in TEXT_SUFFIXES:
                held.append({**record, "held": held_map[str(rel)]})
            else:
                files.append(record)
        (self.out / "binary-artifacts.json").write_text(m13.redact(json.dumps({
            "note": "screenshots, paint frames, downloads, failure panels, text above 256 KiB and text with real "
                    "kbase strings stay in the git-ignored artifacts folder; path, size and sha256 only",
            "artifacts": str(self.artifacts), "files": files, "heldText": held}, indent=2), replacements) + "\n")
        (self.out / "summary.json").write_text(m13.redact(json.dumps(self.summary_json(ledger), indent=2,
                                                                     ensure_ascii=False), replacements) + "\n")
        (self.out / "cases.json").write_text(m13.redact(json.dumps(
            {"schema": "m27_acceptance_cases@1", "acceptance": ledger["acceptance"], "counts": ledger["counts"],
             "cases": ledger["cases"]}, indent=2, ensure_ascii=False), replacements) + "\n")
        (self.out / "README.md").write_text(m13.redact(self.readme(ledger, held), replacements))
        for name in ("binary-artifacts.json", "summary.json", "cases.json", "README.md"):
            sums.append(f"{m13.sha_file(self.out / name)}  {name}")
        (self.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        leaked = [str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file() and
                  any(old in p.read_text(errors="replace") for old, _ in replacements)]
        real = [str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file() and self.real_strings and
                contains_any(p.read_text(errors="replace"), self.real_strings)]
        leaks = sorted(rel for rel, reason in held_map.items() if reason == "real_kbase_text")
        status = "fail" if leaked or real or leaks else "pass"
        self.record("export-evidence", status, output=str(self.out), leaked=leaked, realText=real, heldLeaks=leaks)

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
                                   FLOW, "driver.cjs", "main.cjs", "normal-flow.cjs")},
                               "runnerSha256": m13.sha_file(Path(__file__)),
                               "builderSha256": m13.sha_file(self.code / QA_SET_BUILDER)}
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
    parser.add_argument("--root", required=True, help="fresh QA root (<stage>/runs, reference, precedent_reference "
                        "and reaction_reference are created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m27-acceptance/<label>")
    parser.add_argument("--kbase", default=str(REPO.parent / "kbase_kinase"),
                        help="local kbase_kinase checkout for the real import (read only; default: "
                        "<repo>/../kbase_kinase; give an absolute path in a git worktree)")
    parser.add_argument("--m15-reference", default=".deps/reference",
                        help="active M15 reference folder copied read-only into each stage (never written; a relative "
                        "path is taken from the code root)")
    parser.add_argument("--stages", type=stages_arg, default=list(STAGES),
                        help="fixture, real or fixture,real (default); acceptance needs both in one invocation")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m27-precedents-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
