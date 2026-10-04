#!/usr/bin/env python3
"""Run the M21 mutation structure model offscreen acceptance (spec §9, §11).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend and
MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives the real Electron offscreen flow
frontend/tests/offscreen/mutation-model-flow.cjs, checks reproducibility over the API and assembles case-ledger.json.

Sequence (one backend process):
  0. environment        the backend must report methods.mutation_model (fixed OpenMM 8.6.0 + PDBFixer 1.12.0 + process
                        identity), methods.mutation_candidates and methods.ligand_docking (locked docking environments)
                        available. Missing is an acceptance failure, never "unavailable".
  1. model-main         fresh root: no run → public 1UBQ load + 전처리 → M20 direct-residue set (ILE A:44, allowed W) →
                        "변이 구조 모델링" on the candidate row → request validation → real modeling job (approval, start,
                        done) → side-by-side = stored values, contact table + paging, both mmCIF downloads = stored
                        structure_sha256, fixed limitation sentences, report + downloads → same submission again (same job
                        and handle, no new unit) → held contact page → synthetic phenol SDF import + tab trip →
                        same-condition docking (one action, two real qvina jobs) → pair table → partial pair (one side
                        cancelled) → cancel a running modeling job → run switch with a held response → wording.
  2. reproducibility    the flow's load, prepare, candidate and model requests are made in each of two fresh runs over
                        the API (approval, start, then the model request again). Handles are run-scoped (obj://<run>/...):
                        each run must return the same job and model handle twice, and the stored model with every obj://
                        handle replaced by a placeholder must equal the flow's stored model.
  3. regressions        only with --regressions: the M20, M19, M18, M17, M16, M15, M14 and M13 (all phases) runners, one
                        after another, each with its own fresh --root/--artifacts and --out <out>/../m2X|m1X-regression
                        (their own ledgers decide; this ledger records the exit codes and does not depend on them). M20,
                        M16 and M15 need --kbase.
Cases the real environment cannot produce honestly are recorded as not observed with the tests that cover them (never
forged). Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are
never deleted or retried away. The ledger's ``acceptance`` is true only when the environment check passed, every step
ran in this invocation, every case passed, every flow row measured 0 non-loopback requests and zero provider calls, the
build was stamped from the current frontend source and no worker, qvina or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw.

Usage:
  .venv/bin/python scripts/m21_offscreen_acceptance.py --root runs/m21-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m21-acceptance/<label> \\
      [--out docs/qa/m21-mutations-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never] \\
      [--regressions --kbase <abs path>/kbase_kinase]
"""
from __future__ import annotations

import argparse
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

# Loopback API helpers, backend start/stop and the runner protections of the M18 runner (M17 base, no kbase).
import m18_offscreen_acceptance as m18

# Run-scoped handle normalization, event-log reads and the command helper of the M20 runner.
import m20_offscreen_acceptance as m20

REPO = Path(__file__).resolve().parents[1]
FLOW = "mutation-model-flow.cjs"
FLOW_STEPS = ["model-main"]
MODE_OF = {"model-main": "main"}
STRUCTURE = Path("backend/tests/fixtures/public_1ubq.cif")
PROTOCOL = "openmm_mutation_model_v1"
CANDIDATE_TOOL = "generate_mutation_candidates"
# Spec §9/§11 화면 cases → the flow modes that observe them.
MAIN_CASES = ["MM-no-run", "MM-load-prepare", "MM-candidate-set", "MM-handoff", "MM-validation", "MM-job",
              "MM-side-by-side", "MM-limitations", "MM-negative", "MM-contacts", "MM-downloads", "MM-report",
              "MM-same-handle", "MM-late-contacts", "MM-tab-state", "MM-pair-submit", "MM-pair-scores",
              "MM-pair-partial", "MM-cancel", "MM-late-run"]
CASE_PLAN: dict[str, list[str]] = {case: ["model-main"] for case in MAIN_CASES}
CASE_TEXT = {
    "MM-no-run": "fresh root, no run: the model area shows 사용할 수 없음 + the no-run reason only (no numbers, no "
                 "controls, no model reads)",
    "MM-load-prepare": "public_1ubq.cif loaded and prepared through the structure screen",
    "MM-candidate-set": "M20 direct-residue candidate set (ILE A:44, allowed W) through the candidate screen: one "
                        "candidate I → W",
    "MM-handoff": "변이 구조 모델링 on the M20 candidate row fills the request area with that set and index; seed empty, "
                  "confirmations unchecked, defaults 4.0 Å / 120 s; nothing chosen or sent automatically",
    "MM-validation": "submit blocked without seed and confirmations, with seed only, with one confirmation, with cutoff "
                     "7.0 (argument_invalid); enabled only when complete; no job request while blocked",
    "MM-job": "모델링 작업 제출 → 비싼 계산 승인 → 작업 시작 → real openmm_mutation_model_v1 done; the six request "
              "arguments + timeout_s; one expensive unit; the model listed, not opened automatically",
    "MM-side-by-side": "side-by-side table = API detail = stored event-log payload for both structures (OpenMM potential "
                       "before/after, mutated-residue SASA, contact and residue counts, PDBFixer atoms, disulfides, "
                       "atoms, hydrogens) with the harness ROUND_HALF_UP; no difference field stored",
    "MM-limitations": "the limitation sentences shown = stored = spec §4 verbatim in order (L5/L6 only under their "
                      "stored conditions)",
    "MM-negative": "no difference/change/rank/best/recommendation/stability wording or arrow in the model panel (every "
                   "check of the run); both structure cells of every side-by-side and pair row have the same style; no "
                   "extra column",
    "MM-contacts": "contact table pages (야생형 기준 1, 변이형 1 → 다음 → 이전) = API pages = stored rows (7 partner "
                   "fields, atom names, distance ROUND_HALF_UP); more than one page with cutoff 6.0 Å",
    "MM-downloads": "both mmCIF downloads: bytes SHA-256 = stored structure_sha256 = backend bytes",
    "MM-report": "보고서 만들기 → saved and listed for the model (no new model); Markdown/JSON downloads = backend bytes; "
                 "the Markdown carries the fixed sentences and no docking value",
    "MM-same-handle": "the same model submission again returns the existing done job and the same model handle; no new "
                      "job, no new model, no new unit",
    "MM-late-contacts": "a held 변이형 contact page released after switching back to 야생형 기준 is not applied",
    "MM-tab-state": "ligand SDF imported in the 리간드 설계·탐색 tab; back on 단백질 공학 the area remounts, re-reads its "
                    "lists (GET only) and opens nothing by itself",
    "MM-pair-submit": "same-condition docking: 2-unit notice, blocked until the 2-unit box is ticked; one click sends two "
                      "qvina_dock_v1 jobs that differ only in receptor_source.side (no imported-receptor key); both real "
                      "qvina jobs done through the screen's buttons; two expensive units",
    "MM-pair-scores": "pair row: both scores side by side = docking_pairs = each M18 result's first mode score (receptor "
                      "source recorded), header with the server's score name, four columns, no difference",
    "MM-pair-partial": "second condition (seed 7) with the 변이형 job cancelled while queued: per-side job status, both "
                       "cells '없음(server reason)' without a number; one unit for the started job; the first pair keeps "
                       "its scores",
    "MM-cancel": "a running modeling job (seed 7) cancelled from the screen: cancelled, no model, no worker/guardian "
                 "process left, the area shows 실패 with the cancel sentence, one reserved unit kept",
    "MM-late-run": "a held run A model-list response released after switching to run B is not applied",
}
REPRO_CASE = "MM-reproducible"
REPRO_TEXT = ("the flow's load, prepare, candidate and model requests made in each of two fresh runs over the API: the "
              "same job and model handle twice per run and the stored model (obj:// handles replaced) equal to the "
              "flow's model")
BUDGET_CASE = "MM-budget"
BUDGET_TEXT = ("real expensive units of run A counted from the backend budget: model job 1, same submission 0, "
               "same-condition docking 2, partial pair 1 (the queued side cancelled before it started), cancelled "
               "modeling job 1; total within the run limit")
NOT_OBSERVED = {
    "MM-unavailable": "methods.mutation_model depends on the project .venv (OpenMM 8.6.0, PDBFixer 1.12.0) and the "
                      "process-identity adapter, not on .deps; the M18/M13 layout-without-.deps precedent cannot make it "
                      "unavailable without forging an interpreter. Covered by backend/tests/test_mutation_model_jobs.py::"
                      "test_unavailable_engine_pdbfixer_or_identity_is_412_without_reservation and frontend/tests/"
                      "mutation-model.test.cjs ('five area states: unavailable, failed, loading, empty, ready', 'submit is "
                      "blocked without capability…').",
    "MM-pair-approval": "the expensive_first_call approval is per run and the model job (needed before any pair) already "
                        "took it, so the docking pair's own approval button cannot be reached honestly. Covered by "
                        "frontend/tests/mutation-model.test.cjs (pairApprovalRequired) and the M18 acceptance (D-free-job).",
    "MM-failed-job": "no valid 1UBQ input makes the worker fail with a closed reason (all T1 combinations model). Covered "
                     "by backend/tests/test_mutation_model_worker.py (test_energy_contact_and_output_limits_are_closed_"
                     "failures, test_pdbfixer_errors_are_mutation_modeling_failed) and test_mutation_model_jobs.py "
                     "(test_tampered_output_typed_errors_size_limit_and_late_cancel_publish_nothing).",
    "MM-zero-contacts": "the I44W model has contacts on both structures; a zero contact page ('0개, 계산한 결과') is covered "
                        "by frontend/tests/mutation-model.test.cjs ('contact pages: query, cells, and a zero count…').",
    "MM-conditional-limitations": "L5/L6 need a histidine/cysteine state difference or a new disulfide; 1UBQ I44W has "
                                  "neither (the flow asserts the stored conditions). Covered by backend/tests/"
                                  "test_mutation_model_worker.py (test_removed_disulfide_records_the_partner_difference_"
                                  "and_l5, test_new_disulfide_is_recorded_with_l5_and_l6) on the derived synthetic fixtures.",
}
WORKERS = (*m13.WORKERS, "openmm_mutation_worker.py", "docking_worker.py", "qvina2")
REGRESSIONS = [("m20", ["kbase"]), ("m19", []), ("m18", []), ("m17", []), ("m16", ["kbase"]), ("m15", ["kbase"]),
               ("m14", []), ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_ok(environment: dict) -> bool:
    """The backend reported the mutation model, the M20 candidates and the M18 docking methods available."""
    return (environment.get("modelAvailable") is True and environment.get("candidatesAvailable") is True
            and environment.get("dockingAvailable") is True)


def repro_ok(repro: dict | None) -> bool:
    """At least two fresh runs; each returned one job and one model handle twice, provider calls zero, and the
    normalized stored model equals the flow's."""
    if not isinstance(repro, dict):
        return False
    reference, reruns = repro.get("reference"), repro.get("reruns") or []
    if not isinstance(reference, dict) or not reference.get("contentSha256") or len(reruns) < 2:
        return False
    return all(item.get("status") == "done" and item.get("sameHandle") is True and item.get("sameJob") is True
               and item.get("providerCallsZero") is True and item.get("contentSha256") == reference["contentSha256"]
               for item in reruns)


def budget_ok(budget: dict | None) -> bool:
    """Units per action as the backend counted them: model 1, docking pair 2, partial pair 1, run total ≤ limit."""
    if not isinstance(budget, dict):
        return False

    def delta(key: str) -> int | None:
        entry = budget.get(key) or {}
        before, after = entry.get("before"), entry.get("after")
        return after - before if isinstance(before, int) and isinstance(after, int) else None

    total, limit = budget.get("totalRunA"), budget.get("limitRunA")
    return (delta("model") == 1 and delta("pair") == 2 and delta("partial") == 1 and isinstance(total, int)
            and (not isinstance(limit, (int, float)) or total <= limit))


def assemble(rows: list[dict], leftovers: list[str], environment: dict, repro: dict | None = None) -> dict:
    """Judge the latest row of every flow step, every case of CASE_PLAN, the budget and the reproducibility check.

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
    main_budget = (latest.get("model-main") or {}).get("budget")
    cases[BUDGET_CASE] = {"text": BUDGET_TEXT, "modes": {"model-main": "pass" if budget_ok(main_budget) else "fail"},
                          "status": "pass" if budget_ok(main_budget) else "fail"}
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


class Runner(m18.Runner):
    """The M18 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw path
    check, allowlisted env, leftover check, redacted export, loopback API helpers) with the M21 flow, environment and
    reproducibility checks and ledger. No reference snapshot is needed except for the optional regression chain."""

    stored = m20.Runner.stored
    command = m20.Runner.command

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m21-mutations-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.regressions = bool(getattr(args, "regressions", False))
        kbase = getattr(args, "kbase", None)
        self.kbase = Path(kbase).resolve() if kbase else None
        if self.regressions and (self.kbase is None or not (self.kbase / "ref/manifest.json").is_file()):
            raise SystemExit("--regressions needs --kbase <kbase_kinase checkout with ref/manifest.json> "
                             "(the M20, M16 and M15 regressions import reference snapshots)")
        self.environment: dict = {}

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m21_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

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

    # ----- reproducibility (loopback API + read-only event-log reads; never imports mw) -------
    def model_job(self, run: str, args: dict, timeout_s: int) -> tuple[dict, str | None]:
        """Submit the model request; start it (approve once when the run asks); wait until it leaves the active states."""
        status, job = self.api("POST", f"/runs/{run}/jobs", {"protocol_id": PROTOCOL, "args": args,
                                                             "timeout_s": timeout_s})
        if status != 200 or not isinstance(job, dict) or "job_id" not in job:
            return {"status": f"submit {status}", "detail": job}, None
        job_id = job["job_id"]
        approval = None
        if job.get("status") == "queued":
            status, _ = self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
            if status == 409:
                approval = self.api("POST", f"/runs/{run}/jobs/approve")[0]
                self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        deadline = time.time() + 600
        while time.time() < deadline:
            _, job = self.api("GET", f"/runs/{run}/jobs/{job_id}")
            if job.get("status") not in ("queued", "claimed", "running"):
                break
            time.sleep(1)
        return {**job, "approvalStatus": approval}, (job.get("artifacts") or {}).get("mutation_model")

    def rerun(self, repro: dict) -> dict:
        """The flow's requests in a fresh run: upload, load, prepare, candidate set, then the model request twice."""
        _, made = self.api("POST", "/runs", {"goal": "M21 reproducibility check", "context": [], "dry_run": False,
                                            "egress": "local_only"})
        run = made["run_id"]
        status, upload = self.api("POST", f"/runs/{run}/uploads?filename={STRUCTURE.name}",
                                  (self.code / STRUCTURE).read_bytes(), "application/octet-stream")
        if status != 201:
            return {"run": run, "status": f"upload {status}", "detail": upload}
        status, loaded = self.command(run, "load_structure", {"source": upload["upload_id"], **repro["loadArgs"]})
        if not loaded.get("ok"):
            return {"run": run, "status": f"load {status}", "detail": loaded}
        status, prepared = self.command(run, "prepare_structure", {**repro["prepareArgs"],
                                                                   "structure": loaded["handle"]["handle"]})
        if not prepared.get("ok"):
            return {"run": run, "status": f"prepare {status}", "detail": prepared}
        status, made_set = self.command(run, CANDIDATE_TOOL, {**repro["candidateArgs"],
                                                              "structure": prepared["handle"]["handle"]})
        if not made_set.get("ok"):
            return {"run": run, "status": f"{CANDIDATE_TOOL} {status}", "detail": made_set}
        args = {**repro["modelArgs"], "candidate_set": made_set["handle"]["handle"]}
        first, handle = self.model_job(run, args, repro["timeoutS"])
        if first.get("status") != "done" or not handle:
            return {"run": run, "status": f"model {first.get('status')}", "detail": first}
        units = (self.api("GET", f"/runs/{run}/budget")[1] or {}).get("expensive_calls", {}).get("used")
        second, again = self.model_job(run, args, repro["timeoutS"])
        units_after = (self.api("GET", f"/runs/{run}/budget")[1] or {}).get("expensive_calls", {}).get("used")
        content = self.stored(run, handle)
        quoted = urllib.parse.quote(handle, safe="")
        _, detail = self.api("GET", f"/runs/{run}/mutation_models/{quoted}")
        structures = (detail or {}).get("result", {}).get("structures", {}) if isinstance(detail, dict) else {}
        return {"run": run, "status": "done", "jobs": [first.get("job_id"), second.get("job_id")],
                "handles": [handle, again], "sameHandle": handle == again,
                "sameJob": first.get("job_id") == second.get("job_id"), "approvalStatus": first.get("approvalStatus"),
                "unitsAfterFirst": units, "unitsAfterSecond": units_after,
                "contentSha256": m20.content_sha(content),
                "structureSha256": {side: (structures.get(side) or {}).get("structure_sha256")
                                    for side in ("wild_type_reference", "mutant")},
                "energies": {side: (structures.get(side) or {}).get("energy")
                             for side in ("wild_type_reference", "mutant")},
                "providerCallsZero": self.provider_zero(run)}

    def reproducibility(self, row: dict | None) -> None:
        repro = (row or {}).get("repro") or {}
        needed = ("run", "model", "loadArgs", "prepareArgs", "candidateArgs", "modelArgs", "timeoutS")
        if not all(repro.get(key) for key in needed):
            self.repro = {"error": "the main flow did not record its model request"}
            self.record("reproducibility", "fail", reason=self.repro["error"])
            return
        content = self.stored(repro["run"], repro["model"])
        reference = {"run": repro["run"], "handle": repro["model"], "contentSha256": m20.content_sha(content),
                     "structureSha256": {side: content["structures"][side]["structure_sha256"]
                                         for side in ("wild_type_reference", "mutant")}}
        reruns = [self.rerun(repro) for _ in range(2)]
        self.repro = {"flowRequests": {key: repro[key] for key in needed if key not in ("run", "model")},
                      "reference": reference, "reruns": reruns}
        (self.artifacts / "reproducibility.json").write_text(json.dumps(self.repro, indent=2) + "\n")
        self.record("reproducibility", "pass" if repro_ok(self.repro) else "fail",
                    contentSha256=reference["contentSha256"],
                    reruns=[{k: item.get(k) for k in ("run", "status", "sameHandle", "sameJob", "contentSha256")}
                            for item in reruns])

    def run_flows(self) -> None:
        model = self.capability("mutation_model")
        candidates = self.capability("mutation_candidates")
        docking = self.capability("ligand_docking")
        self.environment.update({
            "modelAvailable": model.get("available") is True, "candidatesAvailable": candidates.get("available") is True,
            "dockingAvailable": docking.get("available") is True,
            "modelCapability": {k: model.get(k) for k in ("available", "reason_code", "versions", "protocol_id",
                                                          "timeout_s", "contact_cutoff_A", "limits")},
            "dockingCapability": {k: docking.get(k) for k in ("available", "status", "reason_code")}})
        ready = environment_ok(self.environment)
        self.record("environment-capability", "pass" if ready else "fail", model=self.environment["modelCapability"],
                    candidates={k: candidates.get(k) for k in ("available", "reason_code")},
                    docking=self.environment["dockingCapability"])
        if ready:
            row = self.flow("model-main", MODE_OF["model-main"], ["--runs-dir", str(self.runs)])
            self.reproducibility(row)
        else:
            self.missing_prerequisite("model-main", "backend reports mutation_model, mutation_candidates or "
                                      f"ligand_docking unavailable: {model.get('reason_code')} / "
                                      f"{candidates.get('reason_code')} / {docking.get('reason_code')}")
            self.repro = {"error": "not run: environment unavailable"}

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
                         "controls": row.get("controls", {}), "budget": row.get("budget"),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.repro)
        passed = judged["passed"]
        ledger = {"schema": "m21_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "notObserved": judged["notObserved"], "reproducibility": self.repro,
                  "environment": self.environment, "leftoverProcesses": leftovers,
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
        versions = (env.get("modelCapability") or {}).get("versions") or {}
        budget = next((row.get("budget") for row in reversed(ledger["rows"]) if row.get("budget")), None) or {}
        lines = ["# M21 변이 구조 모델링 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 환경: mutation_model {'사용 가능' if env.get('modelAvailable') else '사용 불가'} "
                  f"(OpenMM {versions.get('openmm')}, PDBFixer {versions.get('pdbfixer')}) · mutation_candidates "
                  f"{'사용 가능' if env.get('candidatesAvailable') else '사용 불가'} · ligand_docking "
                  f"{'사용 가능' if env.get('dockingAvailable') else '사용 불가'}"),
                 ("- 입력: 공개 1UBQ(`backend/tests/fixtures/public_1ubq.cif`, M7 사전 검사를 통과하는 유일한 로컬 공개 "
                  "구조, 리간드 없음)와 합성 표시 페놀 SDF(`backend/tests/fixtures/mutation_model/"
                  "synthetic-phenol-ligand.sdf`, 같은 조건 도킹 흐름의 기계적 검증용). 후보는 M20 직접 선택 I44W."),
                 (f"- run A 실제 비싼 계산 단위: {budget.get('totalRunA')} / 한도 {budget.get('limitRunA')} "
                  f"(모델 {budget.get('model')}, 같은 조건 도킹 {budget.get('pair')}, 한쪽 취소 짝 {budget.get('partial')}; "
                  "같은 요청 재제출 0, 실행 중 취소한 모델 작업 1)"),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 ("재현 검사: handle은 run마다 다르다(obj://<run>/…). 그래서 같은 서버 프로세스의 새 run 두 개에서 흐름의 "
                  "불러오기·전처리·후보·모델 요청을 API로 보내고(승인·시작), 모델 요청을 한 번 더 보내 같은 작업·같은 "
                  "handle인지, 저장된 모델(obj:// handle만 자리표시로 바꿈)이 흐름의 모델과 같은지 본다. 흐름 안에서는 같은 "
                  "요청을 다시 보내 같은 handle·새 단위 없음을 본다(사례 MM-same-handle)."), "",
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
                  ".venv/bin/python scripts/m21_offscreen_acceptance.py --root runs/m21-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m21-acceptance/<label> \\",
                  "    --out docs/qa/m21-mutations-<YYYYMMDD>/acceptance [--regressions --kbase <abs>/kbase_kinase]",
                  "```"]
        return "\n".join(lines) + "\n"

    def run(self) -> int:
        for folder in (self.runs, self.reference):
            if folder.exists() and any(folder.iterdir()):
                raise SystemExit(f"{folder} is not fresh; choose a new --root")
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
    parser.add_argument("--root", required=True, help="fresh QA root (runs/ and reference/ are created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m21-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m21-mutations-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="afterwards run the M20, M19, M18, M17, M16, M15, "
                        "M14 and M13 (all phases) runners, each with its own fresh root, artifacts and out folder")
    parser.add_argument("--kbase", help="local kbase_kinase checkout (read only, absolute path); required with "
                        "--regressions (passed to the M20, M16 and M15 regressions)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
