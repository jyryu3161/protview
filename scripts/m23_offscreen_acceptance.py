#!/usr/bin/env python3
"""Run the M23 sequence GA design offscreen acceptance (.dryforge/spec.md sections 10, 12).

One command, given a code root (default: this repository), checks the locked docking environment and the project
interpreter, builds the frontend when needed (typecheck, then build, never concurrently), starts its own loopback
services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend and MW_RUNS_DIR=<root>/runs; `next start` on
127.0.0.1:3000), drives the real Electron offscreen flow frontend/tests/offscreen/sequence-ga-flow.cjs mode by mode,
checks reproducibility and the independent oracle paths, and assembles case-ledger.json.

Sequence (one backend process for main and repro):
  0. environment        <code root>/.deps/docking/venv-locked/bin/python, .deps/qvina/env/bin/qvina2 and the project
                        interpreter .venv/bin/python (OpenMM 8.6 + PDBFixer 1.12.0) must exist, and the backend must
                        report methods.sequence_ga_design, mutation_model, mutation_candidates and ligand_docking
                        available. Missing is an acceptance failure, never "unavailable".
  1. seqga-main         run A: no run → public 1UBQ load + 전처리 → GA area without a candidate set (reason only) → M20
                        tiny set (= the T1 fixture) + I44W set → three labeled SDF imports and the tab trip → parameter
                        guards (11 keys, two cross rules, 기본값으로), confirmation blocks, refused preflights
                        (ga_space_too_small ×2, ligand_not_3d) → GA 1 preflight = spec 7 arithmetic → the screen's limit
                        approval → real GA 1 (first expensive approval, progress, done; = the T1 oracle vector) →
                        results = stored, sort, individual and reference detail, mmCIF downloads → GA 1 again (existing
                        job) → GA 2 (other GA seed: reuse + evaluation_limit) → GA 3 cancelled while running → GA 4
                        (implicit-H SDF: reference_failed) → held response → report + downloads + reopen → tabs;
                        processes; wording.
  2. seqga-repro        the flow's GA 1 replayed through the screen in two fresh runs of the same backend process
                        (every sequence GA needs ≥ 10 units > the 8-unit default run budget and only a person's click on
                        the screen raises a limit, so the replay is screen input, not API calls).
  3. reproducibility    the stored summary and every evaluated row (model and M18 result contents with the run-scoped
                        obj:// handles and the hashes computed over them replaced; poses SDF bytes) of each replay must
                        equal the flow's GA 1 (cpu 1, GA and evaluation seeds fixed). Same server process, new runs: not a
                        cold restart.
  4. oracle paths       the flow's GA 1 and GA 2 stored paths equal the independent T1 oracle
                        (backend/tests/fixtures/sequence_ga/independent_sequence_ga_oracle.py, standard library only)
                        fed with the T1 real-engine first-mode table (GA 2 with GA 1's stored rows as the reuse index).
  5. seqga-unavailable  the backend is restarted from <root>/layout-worker-missing (byte-identical backend/mw and config
                        copy without .deps: capability worker_missing) on a fresh runs folder; no-run and unavailable
                        states show a reason only.
  6. regressions        only with --regressions: the M22, M21, M20, M19, M18, M17, M16, M15, M14 and M13 (all phases)
                        runners, one after another, each with its own fresh --root/--artifacts and --out
                        <out>/../m2X|m1X-regression (their own ledgers decide; this ledger records the exit codes and does
                        not depend on them). M20, M16 and M15 need --kbase.
Cases the real environment cannot produce honestly are recorded as not observed with the tests that cover them (never
forged). Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are
never deleted or retried away. The ledger's ``acceptance`` is true only when the environment check passed, every step
ran in this invocation, every case passed, every flow row measured 0 non-loopback requests and zero provider calls, the
build was stamped from the current frontend source and no worker, modeling child, qvina or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw and never calls the limit raise route.

Usage:
  .venv/bin/python scripts/m23_offscreen_acceptance.py --root runs/m23-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m23-acceptance/<label> \\
      [--out docs/qa/m23-sequence-ga-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never] \\
      [--regressions --kbase <abs path>/kbase_kinase]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, bookkeeping and evidence export of the M15 runner.
import m15_offscreen_acceptance as m15

# Environment paths, layout without .deps, backend start/stop and the loopback API helpers of the M18 runner (the M17
# runner's protections come through the M18 Runner).
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "sequence-ga-flow.cjs"
FLOW_STEPS = ["seqga-main", "seqga-repro", "seqga-unavailable"]
MODE_OF = {"seqga-main": "main", "seqga-repro": "repro", "seqga-unavailable": "unavailable"}
STEP_TIMEOUT_S = 5400
PROTOCOL = "sequence_ga_dock_v1"
LAYOUT = m18.LAYOUT
LAYOUT_LABEL = m18.LAYOUT_LABEL
PROJECT_PYTHON = Path(".venv/bin/python")
# Spec 10/12 screen cases → the flow modes that observe them.
MAIN_CASES = ["SG-load-prepare", "SG-no-candidate-set", "SG-candidate-sets", "SG-ligand-imports", "SG-initial-state",
              "SG-param-guards", "SG-cross-rules", "SG-defaults", "SG-confirmations", "SG-refusals", "SG-preflight",
              "SG-limit-approval", "SG-run", "SG-progress", "SG-results", "SG-oracle-path", "SG-sort", "SG-detail",
              "SG-download", "SG-dedupe", "SG-reuse", "SG-partial", "SG-cancel", "SG-reference-failed",
              "SG-late-response", "SG-report", "SG-tabs", "SG-processes", "SG-wording"]
CASE_PLAN: dict[str, list[str]] = {**{case: ["seqga-main"] for case in MAIN_CASES},
                                   "SG-no-run": ["seqga-main", "seqga-unavailable"],
                                   "SG-unavailable": ["seqga-unavailable"], "SG-repro-runs": ["seqga-repro"]}
CASE_TEXT = {
    "SG-load-prepare": "public_1ubq.cif loaded and prepared through the structure screen",
    "SG-no-candidate-set": "before any M20 set the sequence GA area shows 사용할 수 없음 with the reason only (no number, no "
                           "input, only the list re-read button, no POST)",
    "SG-candidate-sets": "M20 screen: the tiny set (I3 protected, K6, I44, G76; allowed A W) whose candidates and positions "
                         "equal the T1 fixture and the oracle space, and an I44W-only set",
    "SG-ligand-imports": "phenol, planar and implicit-H SDFs imported through the docking area; back on 단백질 공학 the "
                         "area remounts and reads its lists with GET only",
    "SG-initial-state": "nothing chosen, submitted or approved automatically: no set, SDF or box, confirmations and "
                        "acknowledgements unchecked, GA seed empty, defaults prefilled, both buttons blocked with the "
                        "reasons, 빈 결과, capability line",
    "SG-param-guards": "each of the 11 GA keys out of range (and the GA seed empty) blocks 시작 전 확인 and 서열 GA 시작 "
                       "with the field's reason (invalid_job_arguments); no request",
    "SG-cross-rules": "population − elite < 2 and max new < population: blocked at the named field; no request",
    "SG-defaults": "기본값으로 restores every spec 2 default and keeps the GA seed; range/default text per field; the "
                   "effective summary with the job time limit total_s + 600",
    "SG-confirmations": "a missing rebuild_pH7 confirmation or acknowledgement blocks the preflight with \"… "
                        "(confirmation_missing)\" / \"… (acknowledgement_missing)\"; no request",
    "SG-refusals": "preflight refusals ga_space_too_small (6 < 8 at max_mutations 1; the I44W set 1 < 4) and "
                   "ligand_not_3d (planar SDF) shown as \"한국어 (code)\" with the server detail; no job, no event, no "
                   "charge",
    "SG-preflight": "GA 1 preflight: space 3/6/26 (cap 3) in ②, 602 heavy atoms and no 4,890 warning line (server "
                    "flag), reserved 13 evaluations / 28 units, need, remaining, shortfall and may-be-partial = spec 7 "
                    "arithmetic; S1 S4 S5 S6 verbatim; the view shows the server numbers",
    "SG-limit-approval": "shortfall → approval control, start blocked (ga_limit_raise_required); the screen's button "
                         "raises by the shortfall only (by human, sequence GA context, no job/object/charge), the "
                         "preflight is read again with no shortfall, nothing starts by itself (GA 1, GA 1 again, GA 4)",
    "SG-run": "real sequence_ga_dock_v1 GA 1: the run's first expensive call approval, 작업 시작, done; timeout total_s + "
              "600; exactly reserved_units units; summary listed, not opened",
    "SG-progress": "while running, the progress line and data attributes equal the stored job record (reference row "
                   "recorded, generations, new evaluations)",
    "SG-results": "status, stop reason (no_change = 점수 최솟값 변화 없음), S sentences, summary lines, the reference row "
                  "apart from the table, generation tabs and every row (mutations from the set with 7 fields, origin, "
                  "parents, evaluation, state, score = stored M18 first mode ROUND_HALF_UP) = stored; carried rule; "
                  "min/max as values",
    "SG-oracle-path": "GA 1's stored path = the T1 independent oracle vector s4_tiny_observed (keys, origins, parents, "
                      "edit ops, evaluations, indices, states, scores, stop)",
    "SG-sort": "slot/key/score headers both ways follow the stored values; rows without a score last; aria-sort; no rank "
               "column",
    "SG-detail": "individual and reference detail = the stored mutation_set_model@1 values only (mutations, potentials "
                 "with S5, HIS/CYS states and differences, disulfides, PDBFixer atoms, model limitations) and the stored "
                 "M18 result detail",
    "SG-download": "individual and reference mmCIF downloads: bytes SHA-256 = stored structure_sha256 = backend bytes",
    "SG-dedupe": "GA 1 arguments again: preflight names the existing job; 서열 GA 시작 shows that job (no new job, object "
                 "or unit)",
    "SG-reuse": "GA 2 (other GA seed, same evaluation seed): reused individuals and the reference row cite GA 1's stored "
                "model and result (재사용), new objects = new evaluations, reserved_units charged once, S3",
    "SG-partial": "GA 2 stops at evaluation_limit (new = reserved evaluations), stopped generation marked, partial, S2",
    "SG-cancel": "GA 3 cancelled from the screen while running: cancelled job, partial / cancelled summary with the "
                 "finished individuals, S2, no worker/modeling child/qvina2 left, no refund",
    "SG-reference-failed": "GA 4 (implicit-H SDF, admitted by the server): the reference row fails in docking (reason "
                           "\"한국어 (code)\", score —, never 0), no generation, partial / reference_failed, S2, stored "
                           "reference model shown without an M18 result; reserved units charged",
    "SG-late-response": "a held summary-detail response released after switching to another summary is not applied",
    "SG-report": "보고서 만들기 → saved and listed for the summary (no new GA object, no unit); Markdown/JSON downloads = "
                 "backend bytes; 지식·보고서 lists 서열 GA 보고서 and reopens the saved Markdown; global budget = backend",
    "SG-tabs": "back on 단백질 공학 the area remounts (GET only, nothing opened); M20, M21, sequence GA areas in order; the "
               "구조 분석 panel stays mounted, hidden and inert; the four tabs unchanged",
    "SG-processes": "no GA worker, modeling child, docking worker, guardian or qvina2 process under the runs folder",
    "SG-wording": "no rank/best/improvement/winner/recommendation/comparison/difference/average/effect/affinity/stability "
                  "word in the sequence GA area outside the fixed and stored sentences and the score names",
    "SG-no-run": "no run: the sequence GA area shows only the no-run reason (no numbers, no controls, no request)",
    "SG-unavailable": "backend without the locked docking environment: 사용할 수 없음 with the capability reason "
                      "(worker_missing), no numbers, no controls, no sequence GA request",
    "SG-repro-runs": "two fresh runs replay GA 1 through the screen (load, prepare, M20 tiny set, phenol import, the same "
                     "inputs and values, the screen's limit approval, run to done)",
}
REPRO_CASE = "SG-reproducible"
REPRO_TEXT = ("the flow's GA 1 replayed in two fresh runs of the same backend process: the summary and every evaluated "
              "row's model and M18 result (contents with the run-scoped obj:// handles and the hashes over them "
              "replaced) and the poses SDF bytes equal the flow's (cpu 1, GA and evaluation seeds fixed)")
ORACLE_CASE = "SG-oracle-paths"
ORACLE_TEXT = ("the flow's GA 1 and GA 2 stored paths equal the independent T1 oracle on the T1 real-engine first-mode "
               "table (GA 2 with GA 1's stored rows as the reuse index)")
NOT_OBSERVED = {
    "SG-individual-without-score": "every individual of the 1UBQ + phenol GAs is scored (T1: all 26 keys and the reference "
                                   "row scored); nothing is forged. The reference row without a score is observed "
                                   "(SG-reference-failed). Covered by frontend/tests/sequence-ga.test.cjs and "
                                   "backend/tests/test_sequence_ga_api.py::test_rows_without_a_score_are_null_never_zero.",
    "SG-heavy-atom-warning": "1UBQ projects 602 heavy atoms (< 4,890): the flag is false and the line absent on every "
                             "preflight; no local public structure passing M7 exceeds it. Covered by "
                             "backend/tests/test_sequence_ga_inputs.py and frontend/tests/sequence-ga.test.cjs.",
    "SG-other-stop-reasons": "generations_complete, space_exhausted, time_exhausted, worker_failed, resource_exceeded and "
                             "repeated_failure need other scores, hours, a killed worker, oversized output or five failing "
                             "models; covered by backend/tests/test_sequence_ga_worker.py and test_sequence_ga_jobs.py.",
    "SG-model-conditional-sentences": "SL5/L6 need a HIS/CYS state difference outside the mutated residues or a new "
                                      "disulfide; the observed 1UBQ tiny-set models have none (the flow asserts the "
                                      "stored conditions). Covered by backend/tests/test_sequence_model_bundle.py and "
                                      "test_sequence_model_worker.py.",
    "SG-dry-run": "a dry-run run plans only; covered by backend/tests/test_sequence_ga_jobs.py::test_dry_run_plans_only and "
                  "frontend/tests/sequence-ga.test.cjs.",
}
WORKERS = (*m13.WORKERS, "sequence_ga_worker.py", "sequence_model_worker.py", "docking_worker.py", "qvina2")
FIXTURES = Path("backend/tests/fixtures/sequence_ga")
ORACLE_FILE = FIXTURES / "independent_sequence_ga_oracle.py"
EXPECTED_FILE = FIXTURES / "expected.json"
ORACLE_SPACE, ORACLE_SCORES = "s4_tiny_1ubq", "s4_tiny_observed"
PHENOL_FILE = Path("backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf")
# The T1 (g) evaluation conditions the oracle score table was observed under.
T1_PARAMETERS = {"seed": 20261004, "exhaustiveness": 4, "num_modes": 5, "energy_range": 3}
T1_BOX = {"source": "ligand_range", "margin_A": 8}
PATH_KEYS = ("key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index", "state", "reason_code",
             "score")
TOTAL_KEYS = ("stop_reason", "status", "generations_done", "new_evaluations_used", "reused_count",
              "reserved_evaluations", "reserved_units")
# SHA-256 values computed over inputs that contain this run's handles (or its run id): the M18 input_sha256, the GA
# staging selection hash, the conditions hash (candidate set, structure and SDF handles) and the GA call key.
RUN_SCOPED_KEYS = frozenset({"input_sha256", "selection_sha256", "conditions_sha256", "call_key"})
REGRESSIONS = [("m22", []), ("m21", []), ("m20", ["kbase"]), ("m19", []), ("m18", []), ("m17", []), ("m16", ["kbase"]),
               ("m15", ["kbase"]), ("m14", []), ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_ok(environment: dict) -> bool:
    """The docking environment and the project interpreter existed, the main backend reported the sequence GA, the
    mutation model, the candidates and single docking available, and the layout backend reported worker_missing."""
    return (environment.get("dockingPython") is True and environment.get("qvina") is True
            and environment.get("projectPython") is True and environment.get("mainAvailable") is True
            and environment.get("modelAvailable") is True and environment.get("candidatesAvailable") is True
            and environment.get("dockingAvailable") is True and environment.get("layoutReason") == "worker_missing")


def normalized(value: object) -> object:
    """Every obj:// handle string and every hash computed over handles replaced by a placeholder (both are
    run-scoped); every other field (scores, potentials, coordinates' hashes, states, origins, box, values) unchanged."""
    if isinstance(value, str):
        return "<handle>" if value.startswith("obj://") else value
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: "<run-scoped hash>" if key in RUN_SCOPED_KEYS else normalized(item)
                for key, item in value.items()}
    return value


def content_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def differing_paths(a: object, b: object, prefix: str = "$", limit: int = 20) -> list[str]:
    """JSON paths where two normalized contents differ (diagnostics only; the first ``limit``)."""
    found: list[str] = []

    def walk(x: object, y: object, where: str) -> None:
        if len(found) >= limit:
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for key in sorted(set(x) | set(y)):
                walk(x.get(key, "<absent>"), y.get(key, "<absent>"), f"{where}.{key}")
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for index, (left, right) in enumerate(zip(x, y)):
                walk(left, right, f"{where}[{index}]")
        elif x != y:
            found.append(where)

    walk(normalized(a), normalized(b), prefix)
    return found


def path_view(content: dict) -> dict:
    """The GA path of a summary (or an oracle result): generations with the path fields, the totals and the
    reference row's state."""
    return {"generations": [{"index": gen["index"], "complete": gen["complete"], "min_score": gen["min_score"],
                             "max_score": gen["max_score"],
                             "individuals": [{key: item[key] for key in PATH_KEYS} for item in gen["individuals"]]}
                            for gen in content["generations"]],
            **{key: content[key] for key in TOTAL_KEYS}, "space": content["space"],
            "reference": {key: content["reference"][key] for key in ("evaluation", "state", "reason_code", "score")}}


def reuse_index(content: dict) -> list[str]:
    """Keys a later GA under the same conditions may reuse: rows with a stored model and result (scored / null_result),
    plus ``wild_type`` when the reference row has both."""
    keys = [item["key"] for gen in content["generations"] for item in gen["individuals"]
            if item["origin"] != "carried" and item["state"] in ("scored", "null_result")]
    if content["reference"]["state"] in ("scored", "null_result"):
        keys.append("wild_type")
    return keys


def t1_conditions(content: dict, phenol_sha256: str, space: dict) -> bool:
    """The summary was computed under the conditions of the T1 score table: the labeled phenol SDF, the ligand-range
    box with 8 Å margin, the T1 evaluation seed and docking values on one CPU, and the tiny set's space."""
    box = content.get("box") or {}
    return (content.get("ligand", {}).get("sdf_sha256") == phenol_sha256
            and box.get("source") == T1_BOX["source"] and box.get("margin_A") == T1_BOX["margin_A"]
            and content.get("parameters", {}).get("cpu") == 1
            and {key: content.get("parameters", {}).get(key) for key in T1_PARAMETERS} == T1_PARAMETERS
            and content.get("space") == space)


def repro_ok(repro: dict | None) -> bool:
    """At least two replays, every one done, provider calls zero, and the summary and row digests equal the flow's
    (which has at least one scored row)."""
    if not isinstance(repro, dict):
        return False
    reference, reruns = repro.get("reference"), repro.get("reruns") or []
    if (not isinstance(reference, dict) or not reference.get("summarySha256") or not reference.get("rows")
            or len(reruns) < 2):
        return False
    if not any(item.get("state") == "scored" for item in reference["rows"]):
        return False
    return all(item.get("status") == "done" and item.get("providerCallsZero") is True
               and item.get("argsEqual") is True and item.get("summarySha256") == reference["summarySha256"]
               and item.get("rows") == reference["rows"] for item in reruns)


def oracle_ok(oracle: dict | None) -> bool:
    """Both GA paths were compared under the T1 conditions and equal the oracle."""
    if not isinstance(oracle, dict):
        return False
    checks = oracle.get("checks") or []
    return (len(checks) >= 2 and {item.get("name") for item in checks} >= {"ga1", "ga2"}
            and all(item.get("conditions") is True and item.get("equal") is True for item in checks))


def assemble(rows: list[dict], leftovers: list[str], environment: dict, repro: dict | None = None,
             oracle: dict | None = None) -> dict:
    """Judge the latest row of every flow step, every case of CASE_PLAN, the reproducibility and the oracle checks.

    A step passes when its latest row passed, measured 0 non-loopback requests and zero provider calls. A case passes
    only when every covering step's latest row reports it as pass (absent = fail). Returns
    {steps, cases, notObserved, verdictParts, passed}.
    """
    attempts: dict[str, list[tuple[tuple[int, str], dict]]] = {}
    for row in rows:
        base, order = m13.step_base(row["step"])
        attempts.setdefault(base, []).append((order, row))
    latest = {step: max(found, key=lambda item: item[0])[1] for step, found in attempts.items()}
    steps: dict[str, dict] = {}
    for step in FLOW_STEPS:
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
    for case, modes in CASE_PLAN.items():
        seen = {mode: ((latest.get(mode) or {}).get("cases") or {}).get(case) for mode in modes}
        cases[case] = {"text": CASE_TEXT[case], "modes": seen,
                       "status": "pass" if all(value == "pass" for value in seen.values()) else "fail"}
    cases[REPRO_CASE] = {"text": REPRO_TEXT, "modes": {"runner": "pass" if repro_ok(repro) else "fail"},
                         "status": "pass" if repro_ok(repro) else "fail"}
    cases[ORACLE_CASE] = {"text": ORACLE_TEXT, "modes": {"runner": "pass" if oracle_ok(oracle) else "fail"},
                          "status": "pass" if oracle_ok(oracle) else "fail"}
    judged = [latest[step] for step in FLOW_STEPS if step in latest]
    cases["S-no-egress"] = {"text": "non-loopback requests 0 and zero provider calls on every flow row",
                            "status": "pass" if len(judged) == len(FLOW_STEPS) and all(
                                r.get("externalRequestCount") == 0 and r.get("providerCallsZero") is True
                                for r in judged) else "fail"}
    parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
             "cases": all(v["status"] == "pass" for v in cases.values()),
             "environment": environment_ok(environment), "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "notObserved": dict(NOT_OBSERVED), "verdictParts": parts,
            "passed": all(parts.values())}


def acceptance_ok(passed: bool, build: dict | None) -> bool:
    return passed and bool((build or {}).get("buildCurrentWithSource"))


def load_oracle(code: Path):
    """The independent T1 oracle module (standard library only; never mw) loaded from its file."""
    spec = importlib.util.spec_from_file_location("independent_sequence_ga_oracle_m23_runner", code / ORACLE_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Runner(m18.Runner):
    """The M18 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw path
    check, allowlisted env, layout without .deps, leftover check, redacted export, loopback API helpers) with the M23
    flow, environment, reproducibility and oracle checks and ledger. No reference snapshot is needed except for the
    optional regression chain."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m23-sequence-ga-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.regressions = bool(getattr(args, "regressions", False))
        kbase = getattr(args, "kbase", None)
        self.kbase = Path(kbase).resolve() if kbase else None
        if self.regressions and (self.kbase is None or not (self.kbase / "ref/manifest.json").is_file()):
            raise SystemExit("--regressions needs --kbase <kbase_kinase checkout with ref/manifest.json> "
                             "(the M20, M16 and M15 regressions import reference snapshots)")
        self.oracle: dict | None = None
        self._objects: dict[str, dict[str, bytes]] = {}

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m23_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- stored objects (read-only event-log reads; never imports mw) ----------------------------
    def payloads(self, run: str) -> dict[str, bytes]:
        """Every object_created payload of a run's event log, read once per run (read only)."""
        if run not in self._objects:
            found: dict[str, bytes] = {}
            with (self.runs / run / "events.jsonl").open() as log:
                for line in log:
                    if '"object_created"' not in line:
                        continue
                    event = json.loads(line)
                    if event.get("type") == "object_created" and event.get("handle") not in found:
                        found[event["handle"]] = base64.b64decode(event["payload_b64"])
            self._objects[run] = found
        return self._objects[run]

    def stored(self, run: str, handle: str) -> dict:
        payload = self.payloads(run).get(handle)
        if payload is None:
            raise RuntimeError(f"no object_created event for {handle}")
        return json.loads(payload)

    def ga_digest(self, run: str, summary: str) -> dict:
        """The summary and every row with a stored model or result (reference row and new evaluations): normalized
        content SHA-256 of the summary, each model and each M18 result, and the poses SDF bytes over the API."""
        content = self.stored(run, summary)
        entries = [("reference", None, {**content["reference"], "key": "wild_type"})]
        entries += [(gen["index"], position, item) for gen in content["generations"]
                    for position, item in enumerate(gen["individuals"])]
        rows = []
        for generation, position, item in entries:
            entry = {"generation": generation, "position": position,
                     **{key: item.get(key) for key in PATH_KEYS if key in item}}
            if item.get("origin") != "carried":
                if item.get("model_handle"):
                    entry["modelSha256"] = content_sha(self.stored(run, item["model_handle"]))
                if item.get("result_handle"):
                    handle = item["result_handle"]
                    quoted = urllib.parse.quote(handle, safe="")
                    status, poses = self.api("GET", f"/runs/{run}/docking/results/poses_sdf?handle={quoted}", raw=True)
                    entry["resultSha256"] = content_sha(self.stored(run, handle))
                    entry["posesSha256"] = m13.sha_bytes(poses) if status == 200 and isinstance(poses, bytes) else None
            rows.append(entry)
        return {"run": run, "summary": summary, "summarySha256": content_sha(content), "gaStatus": content["status"],
                "stopReason": content["stop_reason"], "rows": rows}

    def reproducibility(self, main: dict | None, repro_row: dict | None) -> None:
        flow = (main or {}).get("gaArgs") or {}
        replays = (repro_row or {}).get("repro") or []
        if not (flow.get("args") and flow.get("summary") and flow.get("run")):
            self.repro = {"error": "the main flow did not record its GA 1 arguments"}
            self.record("reproducibility", "fail", reason=self.repro["error"])
            return
        reference = self.ga_digest(flow["run"], flow["summary"])
        reruns = []
        for item in replays:
            entry = {"run": item.get("run"), "label": item.get("label"), "jobId": item.get("job"),
                     "status": item.get("status"),
                     "argsEqual": normalized(item.get("args")) == normalized(flow["args"])
                     and item.get("timeoutS") == flow.get("timeoutS")}
            if item.get("run") and item.get("summary"):
                entry.update({k: v for k, v in self.ga_digest(item["run"], item["summary"]).items() if k != "run"})
                if entry.get("summarySha256") != reference["summarySha256"]:
                    entry["summaryDifferences"] = differing_paths(self.stored(flow["run"], flow["summary"]),
                                                                  self.stored(item["run"], item["summary"]))
            entry["providerCallsZero"] = self.provider_zero(item["run"]) if item.get("run") else False
            reruns.append(entry)
        self.repro = {"method": "same backend process, two new runs replayed through the screen (not a cold restart)",
                      "flowArgs": {k: v for k, v in flow["args"].items() if k != "acknowledgement"},
                      "reference": reference, "reruns": reruns}
        (self.artifacts / "reproducibility.json").write_text(json.dumps(self.repro, indent=2) + "\n")
        self.record("reproducibility", "pass" if repro_ok(self.repro) else "fail",
                    summarySha256=reference.get("summarySha256"),
                    reruns=[{k: item.get(k) for k in ("run", "status", "argsEqual", "summarySha256")} for item in reruns])

    def oracle_paths(self, main: dict | None) -> None:
        """GA 1 and GA 2 of run A against the independent T1 oracle (same tiny set, T1 docking values)."""
        flow = (main or {}).get("gaArgs") or {}
        runs = (main or {}).get("gaRuns") or {}
        run = flow.get("run")
        if not (run and runs.get("ga1") and runs.get("ga2")):
            self.oracle = {"error": "the main flow did not record GA 1 and GA 2"}
            self.record("oracle-paths", "fail", reason=self.oracle["error"])
            return
        module = load_oracle(self.code)
        expected = json.loads((self.code / EXPECTED_FILE).read_text())
        space, scores = expected["spaces"][ORACLE_SPACE], expected["vectors"][ORACLE_SCORES]["scores"]
        ga1, ga2 = self.stored(run, runs["ga1"]), self.stored(run, runs["ga2"])
        phenol = m13.sha_file(self.code / PHENOL_FILE)
        checks = []
        for name, content, reusable in (("ga1", ga1, []), ("ga2", ga2, reuse_index(ga1))):
            conditions = t1_conditions(content, phenol, expected["vectors"][ORACLE_SCORES]["expected"]["space"])
            want = path_view(module.run_ga(space, scores, list(reusable), dict(content["ga"])))
            got = path_view(content)
            checks.append({"name": name, "summary": runs[name], "ga": content["ga"], "reusable": reusable,
                           "conditions": conditions, "equal": got == want,
                           "differences": [] if got == want else differing_paths(got, want)})
        self.oracle = {"oracle": str(ORACLE_FILE), "scores": f"{EXPECTED_FILE}#vectors.{ORACLE_SCORES}.scores",
                       "checks": checks}
        (self.artifacts / "oracle-paths.json").write_text(json.dumps(self.oracle, indent=2) + "\n")
        self.record("oracle-paths", "pass" if oracle_ok(self.oracle) else "fail",
                    checks=[{k: item[k] for k in ("name", "conditions", "equal")} for item in checks])

    def leftovers(self) -> list[str]:
        # Only workers whose working directory or command lies inside this acceptance root count.
        root = self.root.resolve()
        left: list[str] = []
        for _ in range(10):
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
            left = []
            for line in ps.splitlines():
                pid, _, command = line.strip().partition(" ")
                if not any(worker in command for worker in WORKERS):
                    continue
                cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True,
                                     check=False).stdout
                paths = [Path(item[1:]) for item in cwd.splitlines() if item.startswith("n")]
                if not paths or str(root) in command or any(path == root or root in path.parents for path in paths):
                    left.append(line.strip())
            if not left:
                break
            time.sleep(0.5)
        for port in (8000, 3000):
            left += [f"port {port} still listening: pid {pid}" for pid in m13.listening(port)]
        return left

    # ----- flow steps --------------------------------------------------------------------------
    def flow(self, step: str, mode: str, extra: list[str]) -> dict | None:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / FLOW), "--url", m15.WEB, "--mode", mode, "--artifacts", str(step_dir), *extra]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            try:
                rc = subprocess.run(argv, cwd=self.frontend, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    timeout=STEP_TIMEOUT_S, check=False).returncode
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

    def run_flows(self) -> None:
        methods = {name: self.capability(name) for name in ("sequence_ga_design", "mutation_model",
                                                             "mutation_candidates", "ligand_docking")}
        for key, name in (("mainAvailable", "sequence_ga_design"), ("modelAvailable", "mutation_model"),
                          ("candidatesAvailable", "mutation_candidates"), ("dockingAvailable", "ligand_docking")):
            self.environment[key] = methods[name].get("available") is True
        cap = methods["sequence_ga_design"]
        self.environment["mainCapability"] = {k: cap.get(k) for k in ("available", "status", "reason_code", "versions",
                                                                      "ga_ranges", "timeout_s", "limits")}
        ready = all(self.environment[key] for key in ("mainAvailable", "modelAvailable", "candidatesAvailable",
                                                      "dockingAvailable"))
        self.record("environment-capability", "pass" if ready else "fail", capability=self.environment["mainCapability"],
                    others={name: {k: methods[name].get(k) for k in ("available", "status", "reason_code")}
                            for name in ("mutation_model", "mutation_candidates", "ligand_docking")})
        if ready:
            main = self.flow("seqga-main", MODE_OF["seqga-main"], ["--runs-dir", str(self.runs)])
            if ((main or {}).get("gaArgs") or {}).get("summary"):
                repro = self.flow("seqga-repro", MODE_OF["seqga-repro"], ["--runs-dir", str(self.runs)])
            else:
                repro = None
                self.missing_prerequisite("seqga-repro", "the main flow did not record a published GA 1 summary")
            self.reproducibility(main, repro)
            self.oracle_paths(main)
        else:
            reason = " / ".join(f"{name} {methods[name].get('reason_code')}" for name in methods
                                if methods[name].get("available") is not True)
            for step in ("seqga-main", "seqga-repro"):
                self.missing_prerequisite(step, f"backend reports unavailable: {reason}")
            self.repro = {"error": "not run: environment unavailable"}
            self.oracle = {"error": "not run: environment unavailable"}
        self.stop_backend()
        layout = self.layout()
        self.start_backend_at("backend-worker-missing", layout, self.unavailable_runs)
        cap = self.capability("sequence_ga_design")
        self.environment["layoutReason"] = cap.get("reason_code") if cap.get("available") is False else "available"
        self.record("layout-capability", "pass" if self.environment["layoutReason"] == "worker_missing" else "fail",
                    capability={k: cap.get(k) for k in ("available", "status", "reason_code")})
        if self.environment["layoutReason"] == "worker_missing":
            self.flow("seqga-unavailable", MODE_OF["seqga-unavailable"], ["--fixture-label", LAYOUT_LABEL])
        else:
            self.missing_prerequisite("seqga-unavailable", f"layout backend did not report worker_missing: {cap}")

    # ----- optional regression chain (separate runners; their own ledgers decide) -----------------
    def regression_commands(self) -> list[tuple[str, list[str]]]:
        commands = []
        for name, extra in REGRESSIONS:
            argv = [str(self.python), str(self.code / "scripts" / f"{name}_offscreen_acceptance.py"),
                    "--root", str(self.root.parent / f"{self.root.name}-{name}-regression"),
                    "--artifacts", str(self.artifacts / "regressions" / name),
                    "--out", str(self.out.parent / f"{name}-regression"), "--code-root", str(self.code)]
            for item in extra:
                if item == "kbase":
                    argv += ["--kbase", str(self.kbase)]
                else:
                    argv.append(item)
            commands.append((name, argv))
        return commands

    def run_regressions(self) -> None:
        results = {}
        for name, argv in self.regression_commands():
            log = self.artifacts / "services" / f"regression-{name}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("w") as out:
                rc = subprocess.run(argv, cwd=self.code, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    check=False).returncode
            results[name] = {"exitCode": rc, "argv": argv, "log": str(log)}
            self.record(f"regression-{name}", "pass" if rc == 0 else "fail", exitCode=rc, log=str(log))
        self.state["regressions"] = results
        self.save()

    # ----- ledger and evidence -----------------------------------------------------------------
    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "status": row.get("status"),
                         "cases": row.get("cases") or {}, "runs": row.get("runs"), "runId": row.get("runId"),
                         "evidenceKind": row.get("evidenceKind"), "handles": row.get("handles", {}),
                         "inputs": row.get("inputs", []), "fixtureLabels": row.get("fixtureLabels", []),
                         "controls": row.get("controls", {}), "notObserved": row.get("notObserved", []),
                         "budget": row.get("budget"), "gaRuns": row.get("gaRuns"),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.repro, self.oracle)
        passed = judged["passed"]
        ledger = {"schema": "m23_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "notObserved": judged["notObserved"], "reproducibility": self.repro, "oraclePaths": self.oracle,
                  "environment": self.environment, "layout": (self.state.get("layouts") or {}).get(LAYOUT),
                  "leftoverProcesses": leftovers,
                  "externalRequestsTotal": sum(r["externalRequestCount"] or 0 for r in rows),
                  "rowsWithUnknownExternalCount": [r["step"] for r in rows if r["externalRequestCount"] is None],
                  "rows": rows}
        (self.artifacts / "case-ledger.json").write_text(json.dumps(ledger, indent=2, ensure_ascii=False) + "\n")
        self.record("case-ledger", "pass" if passed else "fail", verdict=ledger["verdict"],
                    acceptance=ledger["acceptance"],
                    cases={case: value["status"] for case, value in judged["cases"].items()},
                    output=str(self.artifacts / "case-ledger.json"))
        return ledger

    def readme(self, ledger: dict) -> str:
        env = ledger["environment"]
        main = next((row for row in reversed(ledger["rows"]) if row.get("mode") == "main" and row.get("budget")), None)
        units = ((main or {}).get("budget") or {}).get("expensive_calls") or {}
        versions = (env.get("mainCapability") or {}).get("versions") or {}
        lines = ["# M23 서열 GA 설계 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 환경: docking venv-locked {'있음' if env.get('dockingPython') else '없음'} · qvina2 "
                  f"{'있음' if env.get('qvina') else '없음'} · 프로젝트 .venv {'있음' if env.get('projectPython') else '없음'} · "
                  f"sequence_ga_design {'사용 가능' if env.get('mainAvailable') else '사용 불가'} · 환경 없는 layout backend "
                  f"`{env.get('layoutReason')}` · 버전 {json.dumps(versions, ensure_ascii=False)}"),
                 ("- 입력: 공개 1UBQ(`backend/tests/fixtures/public_1ubq.cif`, M7을 통과하는 유일한 로컬 공개 구조), M20 "
                  "화면으로 만든 tiny 집합(I3 보호, K6·I44·G76, 허용 A·W: 후보 6개, 조합 26개 = T1 fixture)과 I44W 집합, "
                  "합성 표시 SDF 셋(페놀, 평면(ligand_not_3d), 암시 수소(기준 행 도킹 실패))."),
                 (f"- run A 실제 비싼 계산 단위(백엔드 /budget): 사용 {units.get('used')} / 한도 {units.get('limit')} "
                  "(GA마다 시작 전 reserved_units 한 번 예약·환불 없음, 같은 인자 재제출 0. 한도 증액은 모두 화면 버튼 "
                  "클릭)"),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 ("재현 검사: 같은 서버 프로세스의 새 run 두 개에서 흐름의 GA 1을 화면 입력으로 다시 돌린다(콜드 재시작이 "
                  "아니다. 서열 GA는 어떤 설정이든 10단위 이상이 필요해 기본 run 예산 8단위를 넘고, 한도 증액은 사람이 화면 "
                  "버튼으로만 하므로 API 재실행이 아니라 화면 재실행이다). handle은 run마다 다르고 GA 호출 키·조건 해시·"
                  "스테이징 선택 해시·M18 입력 해시가 그 handle로 계산되므로, 요약과 평가한 행마다의 모델·M18 결과 내용"
                  "(obj:// handle과 그 해시만 자리표시로 바꿈)과 포즈 SDF 바이트를 흐름의 것과 비교한다."), "",
                 ("독립 oracle: 흐름의 GA 1·GA 2 저장 경로를 T1 독립 oracle(`backend/tests/fixtures/sequence_ga/"
                  "independent_sequence_ga_oracle.py`, 표준 라이브러리만)에 T1 실제 엔진 첫 모드 점수표를 넣은 결과와 "
                  "비교한다(GA 2는 GA 1의 저장 행을 재사용 색인으로)."), "",
                 "## 사례", "", "| 사례 | 내용 | 결과 | 모드 |", "|---|---|---|---|"]
        for case, value in ledger["cases"].items():
            modes = ", ".join(f"{k}:{v}" for k, v in value.get("modes", {}).items())
            lines.append(f"| {case} | {value['text']} | {value['status']} | {modes} |")
        lines += ["", "## 관찰하지 않은 사례", ""]
        lines += [f"- {case}: {reason}" for case, reason in ledger["notObserved"].items()]
        lines += ["", "## 단계", "", "| 단계 | 결과 | 문제 |", "|---|---|---|"]
        for step, value in ledger["steps"].items():
            lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m23_offscreen_acceptance.py --root runs/m23-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m23-acceptance/<label> \\",
                  "    --out docs/qa/m23-sequence-ga-<YYYYMMDD>/acceptance [--regressions --kbase <abs>/kbase_kinase]",
                  "```"]
        return "\n".join(lines) + "\n"

    def run(self) -> int:
        for folder in (self.runs, self.unavailable_runs, self.root / LAYOUT):
            if folder.exists() and any(folder.iterdir()):
                raise SystemExit(f"{folder} is not fresh; choose a new --root")
        busy = {port: m13.listening(port) for port in (8000, 3000)}
        if any(busy.values()):
            raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        self.artifacts.mkdir(parents=True, exist_ok=True)
        found = {"dockingPython": m18.DOCKING_PYTHON, "qvina": m18.QVINA, "projectPython": PROJECT_PYTHON}
        for key, rel in found.items():
            self.environment[key] = (self.code / rel).is_file()
            self.environment[f"{key}Path"] = str(rel)
        present = all(self.environment[key] for key in found)
        self.record("environment", "pass" if present else "fail",
                    **{key: self.environment[key] for key in found})
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
                                   FLOW, "docking-flow.cjs", "normal-flow.cjs", "driver.cjs", "main.cjs")},
                               "runnerSha256": m13.sha_file(Path(__file__))}
        self.save()
        self.runs.mkdir(parents=True, exist_ok=True)
        self.reference.mkdir(parents=True, exist_ok=True)
        try:
            self.start_frontend()
            self.start_backend_at("backend", self.code, self.runs)
            self.run_flows()
        finally:
            self.stop_all()
            self.state["environment"] = self.environment
            self.save()
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        ledger = self.ledger(left)
        self.export(ledger)
        if self.regressions:
            self.run_regressions()
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "acceptance": ledger["acceptance"], "artifacts": str(self.artifacts)}),
              flush=True)
        return 1 if failed or not ledger["acceptance"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (runs/, unavailable-runs/ and the layout are "
                        "created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m23-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m23-sequence-ga-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="afterwards run the M22, M21, M20, M19, M18, M17, "
                        "M16, M15, M14 and M13 (all phases) runners, each with its own fresh root, artifacts and out "
                        "folder")
    parser.add_argument("--kbase", help="local kbase_kinase checkout (read only, absolute path); required with "
                        "--regressions (passed to the M20, M16 and M15 regressions)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
