#!/usr/bin/env python3
"""Run the M22 ligand GA design (qvina) offscreen acceptance (.dryforge/spec.md sections 9, 11).

One command, given a code root (default: this repository), checks the locked docking environments and the M17 worker,
builds the frontend when needed (typecheck, then build, never concurrently), starts its own loopback services (uvicorn
127.0.0.1:8000 with PYTHONPATH=<code root>/backend and MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives
the real Electron offscreen flow frontend/tests/offscreen/ligand-ga-flow.cjs mode by mode, checks reproducibility over
the API and assembles case-ledger.json.

Sequence:
  0. environment        <code root>/.deps/docking/venv-locked/bin/python, .deps/qvina/env/bin/qvina2 and the M17
                        worker .deps/prolif/venv-locked/bin/python must exist, and the backend must report
                        methods.ligand_ga_design, ligand_docking and ligand_candidates available. Missing is an
                        acceptance failure, never "unavailable".
  1. ga-main            run A: GA area before any candidate set (reason only) → receptor import + real M17 set of the
                        synthetic small pool (10 candidates) → parameter guards (out of range, cross rules, 기본값으로) →
                        refused preflights (ga_pool_too_small) → GA 1 preflight (server numbers = spec 6 arithmetic,
                        끝까지 못 갈 수 있음) → real GA (progress, done, units = reserved) → results = stored (tabs, rows,
                        carried/slot rules, fixture Tanimoto, min/max values, G1, stop reason), sort, M18 detail → GA 2
                        (other GA seed, same docking seed): shortfall → the screen's limit approval → GA 1 again
                        (existing job) → GA 2 reusing GA 1's stored results (G3) → GA 3 pool_exhausted → GA 4
                        docking_limit (partial, G2) → GA 5 cancelled while running → report + downloads; processes;
                        wording.
  2. reproducibility    the flow's GA 1 (same receptor, parent, blocks, box, docking values and seeds) is run again in two
                        fresh runs over the API (M17 inspection + enumeration, approval, GA). Handles are run-scoped and
                        the GA call key, the staging selection hash and the M18 input hashes are computed over them, so
                        the check compares the stored contents with every obj:// handle and those hashes replaced by a
                        placeholder: the summary and every individual's result (and its poses SDF bytes) must equal the
                        flow's. Within one run the same arguments return the same job (flow case GA-dedupe).
  3. ga-unavailable     the backend is restarted from <root>/layout-worker-missing (byte-identical backend/mw and config
                        copy without .deps: capability worker_missing) on a fresh runs folder; no-run and unavailable
                        states show a reason only.
  4. regressions        only with --regressions: the M21, M20, M19, M18, M17, M16, M15, M14 and M13 (all phases)
                        runners, one after another, each with its own fresh --root/--artifacts and --out
                        <out>/../m2X|m1X-regression (their own ledgers decide; this ledger records the exit codes and
                        does not depend on them). M20, M16 and M15 need --kbase.
Cases the real environment cannot produce honestly are recorded as not observed with the tests that cover them (never
forged). Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are
never deleted or retried away. The ledger's ``acceptance`` is true only when the environment check passed, every step
ran in this invocation, every case passed, every flow row measured 0 non-loopback requests and zero provider calls, the
build was stamped from the current frontend source and no worker, qvina or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw and never calls the limit raise route.

Usage:
  .venv/bin/python scripts/m22_offscreen_acceptance.py --root runs/m22-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m22-acceptance/<label> \\
      [--out docs/qa/m22-ga-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never] \\
      [--regressions --kbase <abs path>/kbase_kinase]
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

# Environment paths, layout without .deps, backend start/stop and the loopback API helpers of the M18 runner (the M17
# runner's protections come through the M18 Runner).
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "ligand-ga-flow.cjs"
FLOW_STEPS = ["ga-main", "ga-unavailable"]
MODE_OF = {"ga-main": "main", "ga-unavailable": "unavailable"}
STEP_TIMEOUT_S = 3600
PROTOCOL = "qvina_ga_dock_v1"
LAYOUT = m18.LAYOUT
LAYOUT_LABEL = m18.LAYOUT_LABEL
# Spec 9/11 cases → the flow modes that observe them.
MAIN_CASES = ["GA-run-panel", "GA-no-candidate-set", "GA-m17-set", "GA-param-guards", "GA-defaults",
              "GA-pool-too-small", "GA-preflight", "GA-run", "GA-progress", "GA-results", "GA-sort", "GA-detail",
              "GA-limit-approval", "GA-dedupe", "GA-reuse", "GA-pool-exhausted", "GA-partial", "GA-cancel",
              "GA-report", "GA-processes", "GA-wording"]
CASE_PLAN: dict[str, list[str]] = {**{case: ["ga-main"] for case in MAIN_CASES},
                                   "GA-no-run": ["ga-unavailable"], "GA-unavailable": ["ga-unavailable"]}
CASE_TEXT = {
    "GA-run-panel": "ligand tab GA area uses the global run (no run choice), capability line, no summaries, start "
                    "blocked",
    "GA-no-candidate-set": "before any M17 set the pool area shows 사용할 수 없음 with the reason only (no number, no "
                           "candidate set option, no GA request)",
    "GA-m17-set": "receptor imported in the docking area; real M17 inspection (approval) + enumeration of the synthetic "
                  "small pool at site 22 → the fixture's ten candidate ids in set order",
    "GA-param-guards": "GA seed empty, population 25, random fraction 0.6, population − elite < 2, max new < population: "
                       "each disables 시작 전 확인 and GA 시작 with the field's reason (invalid_job_arguments); no GA "
                       "request is sent",
    "GA-defaults": "기본값으로 restores every spec 2 default and keeps the GA seed; range/default text per field; "
                   "effective summary with the job time limit; 끝까지 못 갈 수 있음 advice",
    "GA-pool-too-small": "preflight refused ga_pool_too_small with the defaults (10 eligible < 12) and with the M17 "
                         "filter (3 eligible < 4); start blocked; no job, no event",
    "GA-preflight": "GA 1 preflight: pool, reusable 0, reserved_units 6 = expected, need 6 units / 1200 s, remaining = "
                    "budget, shortfall 0, 끝까지 못 갈 수 있음 (reserved × 300 s > total_s), G1; the view shows the "
                    "server numbers; no approval control without a shortfall",
    "GA-run": "real qvina_ga_dock_v1 to done without a second approval, timeout total_s + 600, exactly reserved_units "
              "units, summary listed not opened",
    "GA-progress": "while running, the progress line equals the stored job record's staged counts",
    "GA-results": "status, stop reason, G sentences, summary lines, generation tabs and every individual row equal the "
                  "stored summary; scores = each stored M18 result's first mode (ROUND_HALF_UP); carried = previous "
                  "generation's lowest stored scores; slot counts; similarity = fixture Morgan Tanimoto; min/max as "
                  "values only",
    "GA-sort": "slot/candidate/score headers both ways follow the stored values; rows without a score always last; "
               "aria-sort; no rank column",
    "GA-detail": "상세 열기 → the existing M18 detail of that individual's stored result; the individual read names it",
    "GA-limit-approval": "shortfall → approval control shown, start blocked (ga_limit_raise_required); the screen's "
                         "button raises the limit by the shortfall only (by human, GA context, no job/object), "
                         "preflight re-read with no shortfall (GA 2, 3, 4, 5)",
    "GA-dedupe": "GA 1 arguments again: preflight names the existing job; GA 시작 shows that job (no new job, no unit)",
    "GA-reuse": "GA 2 (other GA seed, same docking seed): reused individuals cite GA 1's stored results (저장된 결과 "
                "재사용), new docking objects = new_dockings_used, reserved_units charged once, G1 + G3",
    "GA-pool-exhausted": "GA 3 takes every eligible candidate, then complete / pool_exhausted",
    "GA-partial": "GA 4 (max new 4, nothing reusable): partial / docking_limit after generation 1; G1 + G2; stopped "
                  "generation marked; no number for uncomputed individuals",
    "GA-cancel": "GA 5 cancelled from the screen while an individual is docking: cancelled job, partial / cancelled "
                 "summary with the finished individuals, G2, no worker/qvina2 left, no refund",
    "GA-report": "보고서 만들기 → 리간드 GA 설계 보고서 in the knowledge-tab list (G1, G3, score name); Markdown/JSON "
                 "downloads equal the backend; the global budget equals the backend",
    "GA-processes": "no GA worker, docking worker, M17 worker, guardian or qvina2 process under the runs folder",
    "GA-wording": "no rank/best/improvement/affinity/winner/recommendation word in the GA area outside the fixed "
                  "sentences and the score names",
    "GA-no-run": "no run: the GA area shows only the no-run reason (no numbers, no controls)",
    "GA-unavailable": "backend without the locked environments: 사용할 수 없음 with the capability reason "
                      "(worker_missing), no numbers, no controls, no GA requests",
}
REPRO_CASE = "GA-reproducible"
REPRO_TEXT = ("the flow's GA 1 run again in two fresh runs: the summary and every evaluated individual's result "
              "(contents with the run-scoped obj:// handles and the hashes over them replaced) and the poses SDF bytes "
              "equal the flow's (cpu 1, GA and docking seeds fixed)")
NOT_OBSERVED = {
    "GA-null-result": "qvina returns modes for every small-pool candidate (T1: all ten scored), so no individual "
                      "without a score is shown; nothing is forged. Covered by frontend/tests/ligand-ga.test.cjs and "
                      "backend/tests/test_ligand_ga_worker.py.",
    "GA-no-change": "no_change depends on the engine's scores; no input is chosen to force it. Covered by "
                    "backend/tests/test_ligand_ga_worker.py.",
    "GA-time-and-worker-limits": "time_exhausted, candidate_timeout, worker_failed and resource_exceeded need hours, a "
                                 "killed worker or oversized output; covered by backend/tests/test_ligand_ga_worker.py "
                                 "and test_ligand_ga_jobs.py with test-only reduced constants.",
}
WORKERS = (*m13.WORKERS, "ligand_worker.py", "docking_worker.py", "ligand_ga_worker.py", "qvina2")
FIXTURES = Path("backend/tests/fixtures")
REPRO_FILES = {"receptor": FIXTURES / "chemical/prolif-vina-rec.pdb",
               "ligand_sdf": FIXTURES / "docking/public-derived-parent-record0.sdf",
               "building_blocks_smiles": FIXTURES / "ligand_ga/synthetic-ga-small-blocks.smi"}
SITE_ATOM = 22
# SHA-256 values computed over inputs that contain this run's handles: the M18 input_sha256, the GA staging selection
# hash and the GA call key (spec 4, 7).
RUN_SCOPED_KEYS = frozenset({"input_sha256", "selection_sha256", "call_key"})
REGRESSIONS = [("m21", []), ("m20", ["kbase"]), ("m19", []), ("m18", []), ("m17", []), ("m16", ["kbase"]),
               ("m15", ["kbase"]), ("m14", []), ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_ok(environment: dict) -> bool:
    """Both docking environments and the M17 worker existed, the main backend reported GA design, single docking and
    candidates available, and the layout backend reported worker_missing for GA design."""
    return (environment.get("dockingPython") is True and environment.get("qvina") is True
            and environment.get("ligandPython") is True and environment.get("mainAvailable") is True
            and environment.get("singleAvailable") is True and environment.get("candidatesAvailable") is True
            and environment.get("layoutReason") == "worker_missing")


def normalized(value: object) -> object:
    """Every obj:// handle string and every hash computed over handles replaced by a placeholder (both are
    run-scoped); every other field (scores, poses, origins, similarities, states, box, values) unchanged."""
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


def repro_ok(repro: dict | None) -> bool:
    """At least two re-runs, every one done, provider calls zero, and the summary and individual digests equal the
    flow's (which has at least one scored individual)."""
    if not isinstance(repro, dict):
        return False
    reference, reruns = repro.get("reference"), repro.get("reruns") or []
    if (not isinstance(reference, dict) or not reference.get("summarySha256") or not reference.get("individuals")
            or len(reruns) < 2):
        return False
    if not any(item.get("state") == "scored" for item in reference["individuals"]):
        return False
    return all(item.get("status") == "done" and item.get("providerCallsZero") is True
               and item.get("summarySha256") == reference["summarySha256"]
               and item.get("individuals") == reference["individuals"] for item in reruns)


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
    check, allowlisted env, layout without .deps, leftover check, redacted export, loopback API helpers) with the M22
    flow, environment and reproducibility checks and ledger. No reference snapshot is needed except for the optional
    regression chain."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m22-ga-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.regressions = bool(getattr(args, "regressions", False))
        kbase = getattr(args, "kbase", None)
        self.kbase = Path(kbase).resolve() if kbase else None
        if self.regressions and (self.kbase is None or not (self.kbase / "ref/manifest.json").is_file()):
            raise SystemExit("--regressions needs --kbase <kbase_kinase checkout with ref/manifest.json> "
                             "(the M20, M16 and M15 regressions import reference snapshots)")

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m22_case_ledger_row@1", "step": step_dir.name,
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

    def ga_digest(self, run: str, summary: str) -> dict:
        content = self.stored(run, summary)
        individuals = []
        for gen in content["generations"]:
            for position, item in enumerate(gen["individuals"]):
                entry = {"generation": gen["index"], "position": position,
                         **{key: item[key] for key in ("candidate_id", "origin", "parent_candidate_id", "similarity",
                                                       "evaluation", "eval_index", "state", "reason_code", "score")}}
                handle = item["result_handle"]
                if handle and item["origin"] != "carried":
                    quoted = urllib.parse.quote(handle, safe="")
                    status, poses = self.api("GET", f"/runs/{run}/docking/results/poses_sdf?handle={quoted}", raw=True)
                    entry["resultSha256"] = content_sha(self.stored(run, handle))
                    entry["posesSha256"] = m13.sha_bytes(poses) if status == 200 and isinstance(poses, bytes) else None
                individuals.append(entry)
        return {"run": run, "summary": summary, "summarySha256": content_sha(content), "gaStatus": content["status"],
                "stopReason": content["stop_reason"], "individuals": individuals}

    def job(self, run: str, protocol: str, args: dict, timeout_s: int) -> dict:
        """Submit; start (the run's first expensive call approval when asked, never a limit raise); wait."""
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

    def rerun(self, flow: dict) -> dict:
        """The flow's GA 1 in a fresh run: imports, real M17 inspection + enumeration, then the GA job."""
        _, made = self.api("POST", "/runs", {"goal": "M22 reproducibility check", "context": [], "dry_run": False,
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
        args = {**flow["args"], "receptor_handle": handles["receptor"], "candidate_set_handle": candidate_set,
                "parent_sdf_handle": handles["ligand_sdf"]}
        job = self.job(run, PROTOCOL, args, flow["timeoutS"])
        entry = {"run": run, "jobId": job.get("job_id"), "status": job.get("status"), "failure": job.get("failure"),
                 "args": {k: v for k, v in args.items() if k != "acknowledgement"}}
        summary = (job.get("ga") or {}).get("summary_handle")
        if summary:
            entry.update({k: v for k, v in self.ga_digest(run, summary).items() if k != "run"})
        entry["providerCallsZero"] = self.provider_zero(run)
        return entry

    def reproducibility(self, row: dict | None) -> None:
        flow = (row or {}).get("gaArgs") or {}
        if not (flow.get("args") and flow.get("summary") and flow.get("run") and flow.get("timeoutS")):
            self.repro = {"error": "the main flow did not record its GA 1 arguments"}
            self.record("reproducibility", "fail", reason=self.repro["error"])
            return
        reference = self.ga_digest(flow["run"], flow["summary"])
        reruns = [self.rerun(flow) for _ in range(2)]
        self.repro = {"flowArgs": {k: v for k, v in flow["args"].items() if k != "acknowledgement"},
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
        cap = self.capability("ligand_ga_design")
        single = self.capability("ligand_docking")
        candidates = self.capability("ligand_candidates")
        self.environment["mainAvailable"] = cap.get("available") is True
        self.environment["singleAvailable"] = single.get("available") is True
        self.environment["candidatesAvailable"] = candidates.get("available") is True
        self.environment["mainCapability"] = {k: cap.get(k) for k in ("available", "status", "reason_code", "pins",
                                                                      "ga_pins", "ga_ranges", "limits")}
        ready = (self.environment["mainAvailable"] and self.environment["singleAvailable"]
                 and self.environment["candidatesAvailable"])
        self.record("environment-capability", "pass" if ready else "fail", capability=self.environment["mainCapability"],
                    single={k: single.get(k) for k in ("available", "status", "reason_code")},
                    candidates={k: candidates.get(k) for k in ("available", "status", "reason_code")})
        if ready:
            row = self.flow("ga-main", MODE_OF["ga-main"], ["--runs-dir", str(self.runs)])
            self.reproducibility(row)
        else:
            self.missing_prerequisite("ga-main", "backend reports ligand_ga_design, ligand_docking or "
                                      f"ligand_candidates unavailable: {cap.get('reason_code')} / "
                                      f"{single.get('reason_code')} / {candidates.get('reason_code')}")
            self.repro = {"error": "not run: environment unavailable"}
        self.stop_backend()
        layout = self.layout()
        self.start_backend_at("backend-worker-missing", layout, self.unavailable_runs)
        cap = self.capability("ligand_ga_design")
        self.environment["layoutReason"] = cap.get("reason_code") if cap.get("available") is False else "available"
        self.record("layout-capability", "pass" if self.environment["layoutReason"] == "worker_missing" else "fail",
                    capability={k: cap.get(k) for k in ("available", "status", "reason_code")})
        if self.environment["layoutReason"] == "worker_missing":
            self.flow("ga-unavailable", MODE_OF["ga-unavailable"], ["--fixture-label", LAYOUT_LABEL])
        else:
            self.missing_prerequisite("ga-unavailable", f"layout backend did not report worker_missing: {cap}")

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
                         "budget": row.get("budget"), "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.repro)
        passed = judged["passed"]
        ledger = {"schema": "m22_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
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
        budget = next((row.get("budget") for row in reversed(ledger["rows"]) if row.get("budget")), None) or {}
        units = budget.get("expensive_calls") or {}
        lines = ["# M22 리간드 GA 설계(qvina) 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 작업 환경: docking venv-locked {'있음' if env.get('dockingPython') else '없음'} · qvina2 "
                  f"{'있음' if env.get('qvina') else '없음'} · M17 venv-locked {'있음' if env.get('ligandPython') else '없음'}"
                  f" · 주 backend GA capability {'사용 가능' if env.get('mainAvailable') else '사용 불가'} · 환경 없는 "
                  f"layout backend `{env.get('layoutReason')}`"),
                 ("- 입력: 공개 수용체 `backend/tests/fixtures/chemical/prolif-vina-rec.pdb`, 공개 파생 부모 "
                  "`backend/tests/fixtures/docking/public-derived-parent-record0.sdf`, 합성 표시 블록 "
                  "`backend/tests/fixtures/ligand_ga/synthetic-ga-small-blocks.smi`(실제 M17 작업으로 후보 10개)."),
                 (f"- run A 실제 비싼 계산 단위(백엔드 /budget): 사용 {units.get('used')} / 한도 {units.get('limit')} "
                  "(M17 2, GA마다 시작 전 reserved_units 한 번 예약·환불 없음, 같은 인자 재제출 0. 한도 증액은 모두 화면 "
                  "버튼 클릭)"),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 ("재현 검사: handle은 run마다 다르다(내용에 그 run의 가져오기·후보 집합 handle이 들어가고 GA 호출 키·"
                  "스테이징 선택 해시·M18 입력 해시가 그 handle로 계산됨). 그래서 새 run 두 개에서 흐름의 GA 1을 다시 "
                  "돌려 요약과 평가한 개체마다의 결과 내용(obj:// handle과 그 해시만 자리표시로 바꿈)과 포즈 SDF 바이트를 "
                  "흐름의 것과 비교한다. 같은 run 안의 같은 인자는 같은 작업을 돌려준다(사례 GA-dedupe)."), "",
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
                  ".venv/bin/python scripts/m22_offscreen_acceptance.py --root runs/m22-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m22-acceptance/<label> \\",
                  "    --out docs/qa/m22-ga-<YYYYMMDD>/acceptance [--regressions --kbase <abs>/kbase_kinase]",
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
                                   FLOW, "docking-flow.cjs", "driver.cjs", "main.cjs")},
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
                        "frontend/tests/offscreen/artifacts/m22-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m22-ga-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="afterwards run the M21, M20, M19, M18, M17, M16, "
                        "M15, M14 and M13 (all phases) runners, each with its own fresh root, artifacts and out folder")
    parser.add_argument("--kbase", help="local kbase_kinase checkout (read only, absolute path); required with "
                        "--regressions (passed to the M20, M16 and M15 regressions)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
