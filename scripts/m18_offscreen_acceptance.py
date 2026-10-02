#!/usr/bin/env python3
"""Run the M18 single-ligand docking (qvina) offscreen acceptance (spec §12.5).

One command, given a code root (default: this repository), checks the locked docking environments, builds the
frontend when needed (typecheck, then build, never concurrently), starts its own loopback services (uvicorn
127.0.0.1:8000 with PYTHONPATH=<code root>/backend and MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives
the real Electron offscreen flow frontend/tests/offscreen/docking-flow.cjs mode by mode, checks reproducibility over
the API and assembles case-ledger.json.

Sequence:
  0. environment        <code root>/.deps/docking/venv-locked/bin/python, .deps/qvina/env/bin/qvina2 and the M17
                        worker .deps/prolif/venv-locked/bin/python must exist, and the backend must report
                        methods.ligand_docking and methods.ligand_candidates available. Missing is an acceptance
                        failure, never "unavailable".
  1. docking-main       run A (structure tab: 새 run + 1MQ4) → ligand tab → receptor + 3D SDF → acknowledgement missing
                        → free docking (approval, real qvina) → summary, mode table, contacts, pose SDF downloads equal
                        the stored pose_sdf → report + knowledge-tab list + downloads → complex receptor with one removed
                        instance (instance_range box) → real M17 inspection + enumeration → core-fixed docking → structure
                        tab kept mounted → run B: run switch with a held late response → rejections (planar SDF, implicit
                        H, box over 40 Å on screen and in the worker) → cancel while qvina runs (no worker/qvina process
                        left) → no rank/best/improvement/affinity wording on screen.
  2. reproducibility    the free-docking inputs and values of step 1 are docked again in two fresh runs over the API
                        (approve, start); scores and the all-modes pose SDF bytes must equal step 1's stored result.
  3. docking-unavailable the backend is restarted from <root>/layout-worker-missing (byte-identical backend/mw and
                        config copy without .deps: capability worker_missing) on a fresh runs folder; no-run and
                        unavailable states show a reason only.
Zero-mode results are not forged: qvina returns modes for these valid inputs; the case is recorded as not observed with
the tests that cover it. Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint
frames; failures are never deleted or retried away. The ledger's ``acceptance`` is true only when the environment check
passed, every step ran in this invocation, every case passed, every flow row measured 0 non-loopback requests and zero
provider calls, the build was stamped from the current frontend source and no worker, qvina or 8000/3000 listener
remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw.

Usage:
  .venv/bin/python scripts/m18_offscreen_acceptance.py --root runs/m18-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m18-acceptance/<label> \\
      [--out docs/qa/m18-docking-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, bookkeeping and evidence export of the M15 runner.
import m15_offscreen_acceptance as m15

# Backend start/stop (PYTHONPATH + mw path check) of the M17 runner.
import m17_offscreen_acceptance as m17

REPO = Path(__file__).resolve().parents[1]
FLOW = "docking-flow.cjs"
FLOW_STEPS = ["docking-main", "docking-unavailable"]
MODE_OF = {"docking-main": "main", "docking-unavailable": "unavailable"}
DOCKING_PYTHON = Path(".deps/docking/venv-locked/bin/python")
QVINA = Path(".deps/qvina/env/bin/qvina2")
LIGAND_PYTHON = Path(".deps/prolif/venv-locked/bin/python")
LAYOUT = "layout-worker-missing"
LAYOUT_LABEL = ("labeled runtime layout: byte-identical backend/mw and config copy without .deps "
                "(locked docking environments absent: capability worker_missing)")
# Spec §12.5 cases → the flow modes that observe them.
CASE_PLAN: dict[str, list[str]] = {
    "D-run-create": ["docking-main"], "D-imports": ["docking-main"], "D-ack-missing": ["docking-main"],
    "D-mode-compat": ["docking-main"], "D-free-job": ["docking-main"], "D-free-result": ["docking-main"],
    "D-contacts": ["docking-main"], "D-downloads": ["docking-main"], "D-report": ["docking-main"],
    "D-instance": ["docking-main"], "D-m17-candidates": ["docking-main"], "D-core-fixed": ["docking-main"],
    "D-structure-kept": ["docking-main"], "D-run-switch-late": ["docking-main"], "D-reject-planar": ["docking-main"],
    "D-reject-implicit-h": ["docking-main"], "D-reject-box": ["docking-main"], "D-cancel": ["docking-main"],
    "D-wording": ["docking-main"], "D-no-run": ["docking-unavailable"], "D-unavailable": ["docking-unavailable"],
}
CASE_TEXT = {
    "D-run-create": "structure tab: 새 run + public_1mq4.cif; the ligand tab's docking area uses the global run (no run "
                    "choice there), capability line, empty result list, start disabled",
    "D-imports": "prolif-vina-rec.pdb and the public-derived 3D SDF chosen through the file chooser, 가져오기 → "
                 "chemical_raw_input handles listed by the docking prerequisites; nothing chosen automatically",
    "D-ack-missing": "two of three acknowledgements: 도킹 작업 시작 disabled with acknowledgement_missing",
    "D-mode-compat": "core-fixed disabled for the SDF source (mode_source_mismatch); instance range disabled without an "
                     "instance",
    "D-free-job": "도킹 작업 시작 → 비싼 계산 승인 → 작업 시작 → real qvina_dock_v1 done, one expensive unit, result not "
                  "opened automatically",
    "D-free-result": "summary (full score name, engine, seed 42, values, box = hand oracle, receptor/ligand SHA-256), mode "
                     "table = stored rows (모드 n(엔진 출력 순서), ROUND_HALF_UP), limitations = spec §5.4 selection",
    "D-contacts": "접촉 보기 모드 1: contact page = stored rows (pose SDF serial, receptor seven fields, site_index, "
                  "distance, geometric kind), cutoff 4.0 Å, element-pair kinds, order",
    "D-downloads": "모드 1 and 전체 pose SDF downloads = stored pose_sdf (events.jsonl payload) = backend bytes; "
                   "mode_<n> titles, $$$$ separators",
    "D-report": "보고서 만들기 → 리간드 도킹 보고서 in the knowledge-tab list; Markdown/JSON downloads equal the backend",
    "D-instance": "synthetic complex receptor: instance list (seven fields, 79 atoms, elements), instance range enabled "
                  "only after choosing it; result records the removed instance, the box equals the hand oracle and the "
                  "poses equal the plain-receptor poses byte for byte",
    "D-m17-candidates": "real M17 inspection + enumeration from the candidate area (site 22, fixed replacement) → the "
                        "fixture candidate ids, no second approval",
    "D-core-fixed": "입력 목록 다시 읽기 → M17 candidate + parent SDF, 코어 고정, conformers 5 → 샘플 n(점수 오름차순 "
                    "나열) rows, core deviation, generated H/coordinates, parent serials, limitations 1–5, 7, 8",
    "D-structure-kept": "structure tab stays mounted (hidden) while the ligand tab is shown; same Mol* session, source and "
                        "generation on return; global budget equals the backend",
    "D-run-switch-late": "run B shows only its own list; a held run A docking-results response released after the "
                         "switch is not applied",
    "D-reject-planar": "planar SDF → job failed ligand_not_3d, 실패 with the closed reason, no result stored",
    "D-reject-implicit-h": "implicit-H SDF → job failed ligand_hydrogens_missing, no result stored",
    "D-reject-box": "manual side 41 Å → start disabled (box_too_large, no job request); ligand range + margin 20 → worker "
                    "box_too_large, no result stored",
    "D-cancel": "exhaustiveness 32 job running with a qvina2 process → 작업 취소 → cancelled, no worker/guardian/qvina2 "
                "process left, no result stored",
    "D-wording": "no rank/best/optimum/improvement/binding-strength/affinity word on screen outside the fixed limitation "
                 "sentences and the score names",
    "D-no-run": "no run: the docking area shows only the no-run reason (no numbers, no controls)",
    "D-unavailable": "backend without the locked environments: 사용할 수 없음 with the capability reason (worker_missing), "
                     "no numbers, no controls, no docking requests",
}
REPRO_CASE = "D-reproducible"
REPRO_TEXT = ("same receptor, ligand, box, values and seed docked again in two fresh runs: scores and all-modes pose SDF "
              "bytes equal the flow's stored free-docking result (cpu 1, seed fixed)")
NOT_OBSERVED = {"D-zero-modes": "qvina returns modes for every valid input used here; no input is forged to produce a "
                                "zero-mode result. Covered by frontend/tests/docking.test.cjs (dockingPanelState) and "
                                "the backend docking tests."}
WORKERS = (*m13.WORKERS, "ligand_worker.py", "docking_worker.py", "qvina2")
FIXTURES = Path("backend/tests/fixtures")
REPRO_FILES = {"receptor": FIXTURES / "chemical/prolif-vina-rec.pdb",
               "ligand_sdf": FIXTURES / "docking/public-derived-parent-record0.sdf"}
ACK = {"keep_input_protonation": True, "tool_assigned_types_charges": True, "rigid_no_optimization": True}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_ok(environment: dict) -> bool:
    """Both docking environments and the M17 worker existed, the main backend reported docking and candidates
    available, and the layout backend reported worker_missing."""
    return (environment.get("dockingPython") is True and environment.get("qvina") is True
            and environment.get("ligandPython") is True and environment.get("mainAvailable") is True
            and environment.get("candidatesAvailable") is True and environment.get("layoutReason") == "worker_missing")


def repro_ok(repro: dict | None) -> bool:
    """At least two re-runs, every one done with modes, and every score list and pose-bytes hash equal the flow's."""
    if not isinstance(repro, dict):
        return False
    reference, reruns = repro.get("reference"), repro.get("reruns") or []
    if not isinstance(reference, dict) or not reference.get("scores") or len(reruns) < 2:
        return False
    return all(item.get("status") == "done" and item.get("scores") == reference["scores"]
               and item.get("posesSha256") == reference.get("posesSha256") and item.get("providerCallsZero") is True
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


class Runner(m17.Runner):
    """The M17 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw path
    check, allowlisted env, leftover check, redacted export) with the M18 flow, environment and reproducibility checks
    and ledger. No reference snapshot is needed."""

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m18-docking-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.repro: dict | None = None

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m18_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    def capability(self, name: str) -> dict:
        return (self.get_json("/capabilities").get("methods") or {}).get(name) or {}

    # ----- loopback API (reproducibility only; this runner never imports mw) ------------------
    def api(self, method: str, path: str, body: object = None, ctype: str = "application/json",
            raw: bool = False) -> tuple[int, object]:
        data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(m15.API + path, data=data, method=method, headers={"content-type": ctype})
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                data = response.read()
                return response.status, (data if raw else json.loads(data or b"null"))
        except urllib.error.HTTPError as exc:
            data = exc.read()
            try:
                return exc.code, json.loads(data or b"null")
            except ValueError:
                return exc.code, data.decode(errors="replace")

    def result_digest(self, run: str, handle: str) -> dict:
        quoted = urllib.parse.quote(handle, safe="")
        _, detail = self.api("GET", f"/runs/{run}/docking/results/detail?handle={quoted}")
        status, poses = self.api("GET", f"/runs/{run}/docking/results/poses_sdf?handle={quoted}", raw=True)
        modes = (detail or {}).get("result", {}).get("modes", []) if isinstance(detail, dict) else []
        return {"run": run, "handle": handle, "scores": [row["score_kcal_mol"] for row in modes],
                "contactCounts": [row["contact_count"] for row in modes],
                "posesSha256": m13.sha_bytes(poses) if status == 200 and isinstance(poses, bytes) else None,
                "posesBytes": len(poses) if isinstance(poses, bytes) else None}

    def provider_zero(self, run: str) -> bool:
        _, events = self.api("GET", f"/runs/{run}/events?after=0&limit=500")
        _, budget = self.api("GET", f"/runs/{run}/budget")
        egress = [e for e in events or [] if e.get("type") in ("egress", "egress_budget_settled",
                                                                "viewer_dispatch_started")]
        return (not egress and len(events or []) < 500 and (budget or {}).get("external_tokens", {}).get("used") == 0
                and (budget or {}).get("usd", {}).get("used") == 0)

    def rerun(self, free_args: dict) -> dict:
        """Dock the flow's free inputs and values again in a fresh run (imports, submit, approval, start)."""
        _, made = self.api("POST", "/runs", {"goal": "M18 reproducibility check", "context": [], "dry_run": False,
                                            "egress": "local_only"})
        run = made["run_id"]
        handles = {}
        for kind, rel in REPRO_FILES.items():
            status, body = self.api("POST", f"/runs/{run}/chemical/imports?kind={kind}&filename={rel.name}",
                                    (self.code / rel).read_bytes(), "application/octet-stream")
            if status != 201:
                return {"run": run, "status": f"import {kind} {status}", "detail": body}
            handles[kind] = body["handle"]
        args = {"receptor_handle": handles["receptor"], "receptor_model_number": 1,
                "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
                "ligand": {"source": "sdf", "sdf_handle": handles["ligand_sdf"]}, "mode": free_args["mode"],
                "box": free_args["box"], "parameters": free_args["parameters"], "acknowledgement": ACK}
        status, job = self.api("POST", f"/runs/{run}/jobs", {"protocol_id": "qvina_dock_v1", "args": args,
                                                             "timeout_s": 600})
        if status != 200 or not isinstance(job, dict) or "job_id" not in job:
            return {"run": run, "status": f"submit {status}", "detail": job}
        job_id = job["job_id"]
        status, _ = self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        approval = None
        if status == 409:
            approval = self.api("POST", f"/runs/{run}/jobs/approve")[0]
            self.api("POST", f"/runs/{run}/jobs/{job_id}/start")
        deadline = time.time() + 900
        while time.time() < deadline:
            _, job = self.api("GET", f"/runs/{run}/jobs/{job_id}")
            if job.get("status") not in ("queued", "claimed", "running"):
                break
            time.sleep(1)
        handle = (job.get("artifacts") or {}).get("docking_result")
        entry = {"run": run, "jobId": job_id, "status": job.get("status"), "failure": job.get("failure"),
                 "approvalStatus": approval, "args": {k: v for k, v in args.items() if k != "acknowledgement"}}
        if handle:
            entry.update(self.result_digest(run, handle))
        entry["providerCallsZero"] = self.provider_zero(run)
        return entry

    def reproducibility(self, row: dict | None) -> None:
        free_args = (row or {}).get("freeArgs")
        reference_handle = ((row or {}).get("handles") or {}).get("free")
        reference_run = ((row or {}).get("runs") or {}).get("A")
        if not (free_args and reference_handle and reference_run):
            self.repro = {"error": "the main flow did not record a free-docking result"}
            self.record("reproducibility", "fail", reason=self.repro["error"])
            return
        reference = self.result_digest(reference_run, reference_handle)
        reruns = [self.rerun(free_args) for _ in range(2)]
        self.repro = {"freeArgs": free_args, "reference": reference, "reruns": reruns}
        (self.artifacts / "reproducibility.json").write_text(json.dumps(self.repro, indent=2) + "\n")
        self.record("reproducibility", "pass" if repro_ok(self.repro) else "fail",
                    scores=reference.get("scores"), posesSha256=reference.get("posesSha256"),
                    reruns=[{k: item.get(k) for k in ("run", "status", "scores", "posesSha256")} for item in reruns])

    # ----- layout without the environments ----------------------------------------------------
    def layout(self) -> Path:
        """Byte-identical backend/mw + config copy without .deps (the locked worker interpreters are absent)."""
        target = self.root / LAYOUT
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.code / "backend/mw", target / "backend/mw", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.code / "config", target / "config", ignore=shutil.ignore_patterns("__pycache__"))
        source = {**{f"backend/mw/{k}": v for k, v in m17.tree_digest(self.code / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in m17.tree_digest(self.code / "config").items()}}
        copied = {**{f"backend/mw/{k}": v for k, v in m17.tree_digest(target / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in m17.tree_digest(target / "config").items()}}
        if source != copied:
            raise RuntimeError(f"{LAYOUT}: copied backend/config differs from source")
        if any((target / path).exists() for path in (DOCKING_PYTHON, QVINA, LIGAND_PYTHON)):
            raise RuntimeError(f"{LAYOUT}: a locked environment is present")
        manifest = {"label": LAYOUT_LABEL, "files": len(copied),
                    "treeSha256": hashlib.sha256(json.dumps(copied, sort_keys=True).encode()).hexdigest()}
        (self.artifacts / f"{LAYOUT}.json").write_text(json.dumps(manifest, indent=2) + "\n")
        self.state.setdefault("layouts", {})[LAYOUT] = manifest
        return target

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

    def run_flows(self) -> None:
        cap = self.capability("ligand_docking")
        candidates = self.capability("ligand_candidates")
        self.environment["mainAvailable"] = cap.get("available") is True
        self.environment["candidatesAvailable"] = candidates.get("available") is True
        self.environment["mainCapability"] = {k: cap.get(k) for k in ("available", "status", "reason_code", "pins")}
        ready = self.environment["mainAvailable"] and self.environment["candidatesAvailable"]
        self.record("environment-capability", "pass" if ready else "fail", capability=self.environment["mainCapability"],
                    candidates={k: candidates.get(k) for k in ("available", "status", "reason_code")})
        if ready:
            row = self.flow("docking-main", MODE_OF["docking-main"], ["--runs-dir", str(self.runs)])
            self.reproducibility(row)
        else:
            self.missing_prerequisite("docking-main", "backend reports methods.ligand_docking or ligand_candidates "
                                      f"unavailable: {cap.get('reason_code')} / {candidates.get('reason_code')}")
            self.repro = {"error": "not run: environment unavailable"}
        self.stop_backend()
        layout = self.layout()
        self.start_backend_at("backend-worker-missing", layout, self.unavailable_runs)
        cap = self.capability("ligand_docking")
        self.environment["layoutReason"] = cap.get("reason_code") if cap.get("available") is False else "available"
        self.record("layout-capability", "pass" if self.environment["layoutReason"] == "worker_missing" else "fail",
                    capability={k: cap.get(k) for k in ("available", "status", "reason_code")})
        if self.environment["layoutReason"] == "worker_missing":
            self.flow("docking-unavailable", MODE_OF["docking-unavailable"], ["--fixture-label", LAYOUT_LABEL])
        else:
            self.missing_prerequisite("docking-unavailable", f"layout backend did not report worker_missing: {cap}")

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
        ledger = {"schema": "m18_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
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
        lines = ["# M18 단일 리간드 도킹(qvina) 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 작업 환경: docking venv-locked {'있음' if env.get('dockingPython') else '없음'} · qvina2 "
                  f"{'있음' if env.get('qvina') else '없음'} · M17 venv-locked {'있음' if env.get('ligandPython') else '없음'}"
                  f" · 주 backend 도킹 capability {'사용 가능' if env.get('mainAvailable') else '사용 불가'} · 환경 없는 "
                  f"layout backend `{env.get('layoutReason')}`"),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
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
                  ".venv/bin/python scripts/m18_offscreen_acceptance.py --root runs/m18-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m18-acceptance/<label> \\",
                  "    --out docs/qa/m18-docking-<YYYYMMDD>/acceptance",
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
        found = {"dockingPython": DOCKING_PYTHON, "qvina": QVINA, "ligandPython": LIGAND_PYTHON}
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
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "acceptance": ledger["acceptance"], "artifacts": str(self.artifacts)}),
              flush=True)
        return 1 if failed or not ledger["acceptance"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (runs/, unavailable-runs/ and the layout are "
                        "created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m18-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m18-docking-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
