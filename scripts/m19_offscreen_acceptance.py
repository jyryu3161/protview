#!/usr/bin/env python3
"""Run the M19 candidate batch docking (qvina) offscreen acceptance (spec §13.6).

One command, given a code root (default: this repository), checks the locked docking environments and the M17 worker,
builds the frontend when needed (typecheck, then build, never concurrently), starts its own loopback services (uvicorn
127.0.0.1:8000 with PYTHONPATH=<code root>/backend and MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives
the real Electron offscreen flow frontend/tests/offscreen/docking-batch-flow.cjs mode by mode, checks reproducibility
over the API and assembles case-ledger.json.

Sequence:
  0. environment        <code root>/.deps/docking/venv-locked/bin/python, .deps/qvina/env/bin/qvina2 and the M17
                        worker .deps/prolif/venv-locked/bin/python must exist, and the backend must report
                        methods.ligand_docking_batch, ligand_docking and ligand_candidates available. Missing is an
                        acceptance failure, never "unavailable".
  1. batch-main         run A: receptor imports + real M17 set → candidate filter and checkboxes → water/zinc receptor
                        refused at preflight with its list → free batch with the parent row (N 4, no shortfall, no
                        approval) → real qvina batch → table = stored values, sorting, row → M18 detail + pose SDF →
                        identical batch (existing job, no charge) → subset batch (0 new dockings, reused marks) →
                        core-fixed (parent row disabled; shortfall → explicit limit approval → batch) → report; run B:
                        planar parent row fails ligand_not_3d and the batch continues; run C: cancel mid-batch →
                        partial/cancelled, no worker/qvina2 left → 50-candidate cap and may-be-partial note; run D
                        (labeled dry-run record): no limit approval; wording; processes.
  2. reproducibility    the flow's free batch (same receptor, parent, candidate ids, box, values and seed) is run again in
                        two fresh runs over the API (M17 inspection + enumeration, approval, batch). Handles are
                        run-scoped (the content holds this run's import and candidate-set handles, and the input hashes
                        are computed over them), so identical handles across runs are impossible; the check compares
                        the stored contents with every obj:// handle and input hash replaced by a placeholder: the
                        summary and every row result (and its poses SDF bytes) must equal the flow's. Within one run
                        the same input gives the same summary (flow case B-dedupe).
  3. batch-unavailable  the backend is restarted from <root>/layout-worker-missing (byte-identical backend/mw and
                        config copy without .deps: capability worker_missing) on a fresh runs folder; no-run and
                        unavailable states show a reason only.
  4. regressions        only with --regressions: the M18, M17, M16, M15, M14 and M13 (all phases) runners, one after
                        another, each with its own fresh --root/--artifacts and --out <out>/../m1X-regression (their own
                        ledgers decide; this ledger records the exit codes and does not depend on them).
Cases the real environment cannot produce are recorded as not observed with the tests that cover them (never forged).
Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never
deleted or retried away. The ledger's ``acceptance`` is true only when the environment check passed, every step ran in
this invocation, every case passed, every flow row measured 0 non-loopback requests and zero provider calls, the build
was stamped from the current frontend source and no worker, qvina or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw.

Usage:
  .venv/bin/python scripts/m19_offscreen_acceptance.py --root runs/m19-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m19-acceptance/<label> \\
      [--out docs/qa/m19-batch-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never] \\
      [--regressions [--kbase <dir>]]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
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

# Environment paths, layout without .deps (M17 tree digest), backend start/stop of the M17 runner and the loopback API
# helpers of the M18 runner (the M17 runner's protections come through the M18 Runner).
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "docking-batch-flow.cjs"
FLOW_STEPS = ["batch-main", "batch-unavailable"]
MODE_OF = {"batch-main": "main", "batch-unavailable": "unavailable"}
STEP_TIMEOUT_S = 3600
LAYOUT = m18.LAYOUT
LAYOUT_LABEL = m18.LAYOUT_LABEL
# Spec §13.6 cases → the flow modes that observe them.
MAIN_CASES = ["B-run-panel", "B-m17-set", "B-select", "B-refusal", "B-preflight", "B-no-approval", "B-run", "B-table",
              "B-sort", "B-detail", "B-dedupe", "B-reuse", "B-core-parent-disabled", "B-limit-approval", "B-core-fixed",
              "B-report", "B-fail-row", "B-cancel", "B-cap", "B-dry-run", "B-processes", "B-wording"]
CASE_PLAN: dict[str, list[str]] = {**{case: ["batch-main"] for case in MAIN_CASES},
                                   "B-no-run": ["batch-unavailable"], "B-unavailable": ["batch-unavailable"]}
CASE_TEXT = {
    "B-run-panel": "ligand tab batch area uses the global run (no run choice), capability line, no summaries, start "
                   "blocked",
    "B-m17-set": "receptors imported in the docking area; real M17 inspection (approval) + enumeration at site 22 → the "
                 "fixture candidate ids in set order",
    "B-select": "candidate set + parent SDF; M17 filter (heavy atoms ≤ 45, passes only) rows = the server's filtered page "
                "and the stored properties; checkboxes; 선택 n / 50; ids recorded in set order, not click order",
    "B-refusal": "water/zinc receptor → preflight refused receptor_unsupported_residue; the refusal list (seven residue "
                 "fields, nulls kept, atom names) equals the fixture oracle; no job, no event",
    "B-preflight": "N 4 (parent + 3), needed 4 units / 1500 s = spec 6.3 arithmetic, remaining = budget, shortfall 0, "
                   "no-refund note, wait note, rows new/reused, B1 verbatim; the view shows the server numbers",
    "B-no-approval": "no limit approval control while the shortfall is 0",
    "B-run": "real qvina_batch_dock_v1 to done without a second approval, exactly N units, summary listed not opened",
    "B-table": "status, B1/B3, every row (state, score = stored first row with ROUND_HALF_UP, score target, reason, "
               "reuse mark, detail) equals the stored summary and per-row results (no client recompute)",
    "B-sort": "row/candidate/score headers both ways follow the stored values; rows without a score always last; "
              "aria-sort; no rank column",
    "B-detail": "상세 열기 → the existing M18 detail of that row's stored result; pose SDF download = stored pose_sdf",
    "B-dedupe": "identical batch: preflight N 0 and the existing job; 일괄 시작 shows that job again (no new job, no "
                "unit)",
    "B-reuse": "subset batch: preflight N 0 / needed 60 s; a new job with no unit; every row marked 저장된 결과 재사용 "
               "with the stored handles",
    "B-core-parent-disabled": "코어 고정 clears and disables the parent row with batch_parent_not_allowed (no number)",
    "B-limit-approval": "core-fixed N 3 with 2 units left → shortfall 1, approval control shown, start blocked "
                        "(batch_limit_raise_required); explicit approval raises the limit by the shortfall only (by "
                        "human, batch context, no job/object), preflight re-read; the raised limit stays (global "
                        "budget = backend)",
    "B-core-fixed": "core-fixed batch rows show 샘플 1(점수 오름차순 나열) scores equal to the stored results",
    "B-report": "보고서 만들기 → 리간드 도킹 일괄 보고서 in the knowledge-tab list (B1, B3, score name); Markdown/JSON "
                "downloads equal the backend",
    "B-fail-row": "planar parent fixture → the parent row fails ligand_not_3d (no score, detail disabled), the candidate "
                  "rows are scored, the batch is complete, 4 units",
    "B-cancel": "slow batch cancelled after a finished row → partial / cancelled; finished row kept with its score, "
                "running row cancelled, the rest not_run with the reason and no number; no worker/qvina2 left; no "
                "refund",
    "B-cap": "labeled generated chain set (59): 50 selected, the 51st cannot be ticked; preflight N = 50 − reused "
             "finished rows, 7800 s, shortfall, may-be-partial note, approval offered (not used), start blocked",
    "B-dry-run": "labeled dry-run run record: dry-run note, no limit approval control, nothing computed",
    "B-processes": "no batch worker, docking worker, M17 worker, guardian or qvina2 process under the runs folder",
    "B-wording": "no rank/best/optimum/improvement/binding-strength/affinity word in the batch area outside the fixed "
                 "sentences and the score names",
    "B-no-run": "no run: the batch area shows only the no-run reason (no numbers, no controls)",
    "B-unavailable": "backend without the locked environments: 사용할 수 없음 with the capability reason "
                     "(worker_missing), no numbers, no controls, no batch requests",
}
REPRO_CASE = "B-reproducible"
REPRO_TEXT = ("the flow's free batch run again in two fresh runs: the summary and every row result (contents with the "
              "run-scoped obj:// handles and input hashes replaced) and the poses SDF bytes equal the flow's (cpu 1, "
              "seed fixed)")
NOT_OBSERVED = {
    "B-dry-run-shortfall": "a dry-run run cannot hold a candidate set (M17 jobs only plan there), so an admitted "
                           "preflight with a shortfall cannot be reached in one; covered by "
                           "frontend/tests/docking-batch.test.cjs and backend/tests/test_docking_batch_budget.py.",
    "B-null-result": "qvina returns modes for every valid input here; no zero-mode row is forged. Covered by the backend "
                     "batch tests and frontend/tests/docking-batch.test.cjs.",
    "B-time-limits": "candidate_timeout, time_exhausted, worker_failed and the output cap need hours or a killed worker; "
                     "covered by backend/tests/test_docking_batch_worker.py and test_docking_batch_jobs.py with "
                     "test-only reduced constants.",
}
WORKERS = (*m13.WORKERS, "ligand_worker.py", "docking_worker.py", "docking_batch_worker.py", "qvina2")
FIXTURES = Path("backend/tests/fixtures")
REPRO_FILES = {"receptor": FIXTURES / "chemical/prolif-vina-rec.pdb",
               "ligand_sdf": FIXTURES / "docking/public-derived-parent-record0.sdf",
               "building_blocks_smiles": FIXTURES / "docking/synthetic-docking-blocks.smi"}
SITE_ATOM = 22
# SHA-256 of normalized inputs that contain this run's handles (spec 5.2 batch_input_sha256, M18 input_sha256).
RUN_SCOPED_KEYS = frozenset({"input_sha256", "batch_input_sha256"})
REGRESSIONS = [("m18", []), ("m17", []), ("m16", ["kbase"]), ("m15", ["kbase"]), ("m14", []),
               ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_ok(environment: dict) -> bool:
    """Both docking environments and the M17 worker existed, the main backend reported the batch, single docking and
    candidates available, and the layout backend reported worker_missing for the batch."""
    return (environment.get("dockingPython") is True and environment.get("qvina") is True
            and environment.get("ligandPython") is True and environment.get("mainAvailable") is True
            and environment.get("singleAvailable") is True and environment.get("candidatesAvailable") is True
            and environment.get("layoutReason") == "worker_missing")


def normalized(value: object) -> object:
    """Every obj:// handle string and every input hash computed over handles replaced by a placeholder (both are
    run-scoped); every other field (scores, poses, contacts, box, values, states, reasons) unchanged."""
    if isinstance(value, str):
        return "<handle>" if value.startswith("obj://") else value
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: "<run-scoped input hash>" if key in RUN_SCOPED_KEYS else normalized(item)
                for key, item in value.items()}
    return value


def content_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def repro_ok(repro: dict | None) -> bool:
    """At least two re-runs, every one done, provider calls zero, and the summary and row digests equal the flow's."""
    if not isinstance(repro, dict):
        return False
    reference, reruns = repro.get("reference"), repro.get("reruns") or []
    if not isinstance(reference, dict) or not reference.get("summarySha256") or not reference.get("rows") or len(reruns) < 2:
        return False
    if not any(row.get("state") == "scored" for row in reference["rows"]):
        return False
    return all(item.get("status") == "done" and item.get("providerCallsZero") is True
               and item.get("summarySha256") == reference["summarySha256"] and item.get("rows") == reference["rows"]
               for item in reruns)


def assemble(rows: list[dict], leftovers: list[str], environment: dict, repro: dict | None = None) -> dict:
    """Judge the latest row of every flow step, every case of CASE_PLAN and the reproducibility check.

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
    check, allowlisted env, layout without .deps, leftover check, redacted export) with the M19 flow, environment and
    reproducibility checks and ledger. No reference snapshot is needed."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m19-batch-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.regressions = bool(getattr(args, "regressions", False))
        self.kbase = getattr(args, "kbase", None)

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m19_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- reproducibility (loopback API + read-only event-log reads; never imports mw) -------
    def stored(self, run: str, handle: str) -> dict:
        """A stored object's content: its object_created payload in <runs>/<run>/events.jsonl (read only)."""
        with (self.runs / run / "events.jsonl").open() as log:
            for line in log:
                if handle in line:
                    event = json.loads(line)
                    if event.get("type") == "object_created" and event.get("handle") == handle:
                        return json.loads(base64.b64decode(event["payload_b64"]))
        raise RuntimeError(f"no object_created event for {handle}")

    def batch_digest(self, run: str, summary: str) -> dict:
        content = self.stored(run, summary)
        rows = []
        for row in content["rows"]:
            entry = {key: row[key] for key in ("row_index", "kind", "candidate_id", "state", "reason_code",
                                                 "score_kcal_mol", "score_row_label")}
            handle = row["result_handle"]
            if handle:
                quoted = urllib.parse.quote(handle, safe="")
                status, poses = self.api("GET", f"/runs/{run}/docking/results/poses_sdf?handle={quoted}", raw=True)
                entry["resultSha256"] = content_sha(self.stored(run, handle))
                entry["posesSha256"] = m13.sha_bytes(poses) if status == 200 and isinstance(poses, bytes) else None
            rows.append(entry)
        return {"run": run, "summary": summary, "summarySha256": content_sha(content), "status": content["status"],
                "rows": rows}

    def job(self, run: str, protocol: str, args: dict, timeout_s: int) -> dict:
        status, job = self.api("POST", f"/runs/{run}/jobs", {"protocol_id": protocol, "args": args,
                                                             "timeout_s": timeout_s})
        if status != 200 or not isinstance(job, dict) or "job_id" not in job:
            return {"status": f"submit {status}", "detail": job}
        job_id = job["job_id"]
        status, _ = self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        if status == 409:
            self.api("POST", f"/runs/{run}/jobs/approve")
            self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        deadline = time.time() + 3600
        while time.time() < deadline:
            _, job = self.api("GET", f"/runs/{run}/jobs/{job_id}")
            if job.get("status") not in ("queued", "claimed", "running"):
                break
            time.sleep(1)
        return job

    def rerun(self, flow_args: dict) -> dict:
        """The flow's free batch in a fresh run: imports, real M17 inspection + enumeration, then the batch."""
        _, made = self.api("POST", "/runs", {"goal": "M19 reproducibility check", "context": [], "dry_run": False,
                                            "egress": "local_only"})
        run = made["run_id"]
        handles = {}
        for kind, rel in REPRO_FILES.items():
            status, body = self.api("POST", f"/runs/{run}/chemical/imports?kind={kind}&filename={rel.name}",
                                    (self.code / rel).read_bytes(), "application/octet-stream")
            if status != 201:
                return {"run": run, "status": f"import {kind} {status}", "detail": body}
            handles[kind] = body["handle"]
        inspect = self.job(run, "rdkit_inspect_v1", {"parent_sdf_handle": handles["ligand_sdf"],
                                                     "block_handles": [handles["building_blocks_smiles"]],
                                                     "rules": []}, 120)
        inspection = (inspect.get("artifacts") or {}).get("ligand_inspection")
        if not inspection:
            return {"run": run, "status": f"inspection {inspect.get('status')}", "detail": inspect.get("failure")}
        enumerate_ = self.job(run, "rdkit_enumerate_v1", {"inspection_handle": inspection, "site_atoms": [SITE_ATOM],
                                                          "use_fixed": True, "rule_ids": []}, 120)
        candidate_set = (enumerate_.get("artifacts") or {}).get("ligand_candidate_set")
        if not candidate_set:
            return {"run": run, "status": f"enumeration {enumerate_.get('status')}", "detail": enumerate_.get("failure")}
        args = {**flow_args, "receptor_handle": handles["receptor"], "candidate_set_handle": candidate_set,
                "parent_sdf_handle": handles["ligand_sdf"]}
        job = self.job(run, "qvina_batch_dock_v1", args, 7800)
        entry = {"run": run, "jobId": job.get("job_id"), "status": job.get("status"), "failure": job.get("failure"),
                 "args": {k: v for k, v in args.items() if k != "acknowledgement"}}
        summary = (job.get("batch") or {}).get("summary_handle")
        if summary:
            entry.update({k: v for k, v in self.batch_digest(run, summary).items() if k != "run"})
        entry["providerCallsZero"] = self.provider_zero(run)
        return entry

    def reproducibility(self, row: dict | None) -> None:
        free = (row or {}).get("freeArgs") or {}
        if not (free.get("args") and free.get("summary") and free.get("run")):
            self.repro = {"error": "the main flow did not record a free batch"}
            self.record("reproducibility", "fail", reason=self.repro["error"])
            return
        reference = self.batch_digest(free["run"], free["summary"])
        reruns = [self.rerun(free["args"]) for _ in range(2)]
        self.repro = {"flowArgs": {k: v for k, v in free["args"].items() if k != "acknowledgement"},
                      "reference": reference, "reruns": reruns}
        (self.artifacts / "reproducibility.json").write_text(json.dumps(self.repro, indent=2) + "\n")
        self.record("reproducibility", "pass" if repro_ok(self.repro) else "fail",
                    summarySha256=reference.get("summarySha256"),
                    reruns=[{k: item.get(k) for k in ("run", "status", "summarySha256")} for item in reruns])

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
        cap = self.capability("ligand_docking_batch")
        single = self.capability("ligand_docking")
        candidates = self.capability("ligand_candidates")
        self.environment["mainAvailable"] = cap.get("available") is True
        self.environment["singleAvailable"] = single.get("available") is True
        self.environment["candidatesAvailable"] = candidates.get("available") is True
        self.environment["mainCapability"] = {k: cap.get(k) for k in ("available", "status", "reason_code", "pins",
                                                                      "batch_pins")}
        ready = (self.environment["mainAvailable"] and self.environment["singleAvailable"]
                 and self.environment["candidatesAvailable"])
        self.record("environment-capability", "pass" if ready else "fail", capability=self.environment["mainCapability"],
                    single={k: single.get(k) for k in ("available", "status", "reason_code")},
                    candidates={k: candidates.get(k) for k in ("available", "status", "reason_code")})
        if ready:
            row = self.flow("batch-main", MODE_OF["batch-main"], ["--runs-dir", str(self.runs)])
            self.reproducibility(row)
        else:
            self.missing_prerequisite("batch-main", "backend reports ligand_docking_batch, ligand_docking or "
                                      f"ligand_candidates unavailable: {cap.get('reason_code')} / "
                                      f"{single.get('reason_code')} / {candidates.get('reason_code')}")
            self.repro = {"error": "not run: environment unavailable"}
        self.stop_backend()
        layout = self.layout()
        self.start_backend_at("backend-worker-missing", layout, self.unavailable_runs)
        cap = self.capability("ligand_docking_batch")
        self.environment["layoutReason"] = cap.get("reason_code") if cap.get("available") is False else "available"
        self.record("layout-capability", "pass" if self.environment["layoutReason"] == "worker_missing" else "fail",
                    capability={k: cap.get(k) for k in ("available", "status", "reason_code")})
        if self.environment["layoutReason"] == "worker_missing":
            self.flow("batch-unavailable", MODE_OF["batch-unavailable"], ["--fixture-label", LAYOUT_LABEL])
        else:
            self.missing_prerequisite("batch-unavailable", f"layout backend did not report worker_missing: {cap}")

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
                    argv += ["--kbase", str(self.kbase)] if self.kbase else []
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
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.repro)
        passed = judged["passed"]
        ledger = {"schema": "m19_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "notObserved": judged["notObserved"], "reproducibility": self.repro,
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
        lines = ["# M19 후보 일괄 도킹(qvina) 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 작업 환경: docking venv-locked {'있음' if env.get('dockingPython') else '없음'} · qvina2 "
                  f"{'있음' if env.get('qvina') else '없음'} · M17 venv-locked {'있음' if env.get('ligandPython') else '없음'}"
                  f" · 주 backend 일괄 capability {'사용 가능' if env.get('mainAvailable') else '사용 불가'} · 환경 없는 "
                  f"layout backend `{env.get('layoutReason')}`"),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 ("재현 검사: handle은 run마다 다르다(내용에 그 run의 가져오기·후보 집합 handle이 들어감). 그래서 새 run 두 "
                  "개에서 같은 일괄을 다시 돌려 요약과 행별 결과의 내용(obj:// handle과 그 handle로 계산한 입력 해시만 "
                  "자리표시로 바꿈)과 포즈 SDF "
                  "바이트를 흐름의 것과 비교한다. 같은 run 안의 같은 입력은 같은 요약을 돌려준다(사례 B-dedupe)."), "",
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
                  ".venv/bin/python scripts/m19_offscreen_acceptance.py --root runs/m19-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m19-acceptance/<label> \\",
                  "    --out docs/qa/m19-batch-<YYYYMMDD>/acceptance",
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
        found = {"dockingPython": m18.DOCKING_PYTHON, "qvina": m18.QVINA, "ligandPython": m18.LIGAND_PYTHON}
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
                                   FLOW, "docking-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs")},
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
                        "frontend/tests/offscreen/artifacts/m19-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m19-batch-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="afterwards run the M18, M17, M16, M15, M14 and "
                        "M13 (all phases) runners, each with its own fresh root, artifacts and out folder")
    parser.add_argument("--kbase", help="reference snapshot folder for the M16 and M15 regressions (their default "
                        "otherwise)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
