#!/usr/bin/env python3
"""Run every M11 chemical offscreen mode (H01-H17) on an already-built frontend with fresh QA roots.

One command starts loopback services itself (backend 127.0.0.1:8000, `next start` 127.0.0.1:3000),
drives real Electron offscreen runs of frontend/tests/offscreen/chemical-flow.cjs in dependency
order, performs the labeled attach setup through GET/POST loopback API calls, runs the events-only
replay with original inputs withheld and the worker absent, checks the missing and non-pinned
worker capability states, optionally reruns the M8/M9/M10 regression flows, and assembles
case-ledger.json. Each step writes its own ledger-row.json; failures are kept, never retried away.

The frontend must already be built (`npm --prefix frontend run build`); this script never builds,
installs, or contacts a non-loopback host. The runs root must be fresh and outside /tmp. Labeled
runtime layouts for the unavailable-worker states are byte-identical copies of backend/mw and
config/ placed under the QA root: one without .deps (worker missing) and one whose pinned worker
path points at the server interpreter (handshake/version mismatch). They never fake a success.

Usage:
  .venv/bin/python scripts/m11_offscreen_acceptance.py --root runs/m11-acceptance-<date> \
      --artifacts frontend/tests/offscreen/artifacts/m11-acceptance/<label> \
      [--phases main,regressions,replay,capability-mismatch,ledger] [--only step,step]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
OFFSCREEN = FRONTEND / "tests/offscreen"
FIXTURES = REPO / "backend/tests/fixtures/chemical"
PUBLIC_RECEPTOR = FIXTURES / "prolif-vina-rec.pdb"
PUBLIC_SDF = FIXTURES / "prolif-vina-output.sdf"
PENTAVALENT_SDF = FIXTURES / "synthetic-pentavalent-carbon.sdf"
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
PHASES = ["main", "regressions", "replay", "capability-mismatch", "ledger"]
MAIN_STEPS = ["capability-ready", "create", "empty", "prepare-only", "detect-controls", "job-controls",
              "job-controls-failure", "running-cancel", "attach-setup", "attach-map", "attach-replace",
              "reopen-complete", "restrictions", "faults", "invalid-inputs", "invalid-attach", "reopen"]
REGRESSION_STEPS = ["regression-m8-normal", "regression-m9-openmm", "regression-m9-scenes-core",
                    "regression-m10-measure", "regression-m10-alignment"]
STEP_TIMEOUT_S = 1500


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha_file(path) for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.root = Path(args.root).resolve()
        self.artifacts = Path(args.artifacts).resolve()
        self.only = set(filter(None, (args.only or "").split(",")))
        self.phases = [p for p in PHASES if p in set(args.phases.split(","))]
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        for bad in ("/tmp", "/private/tmp"):
            if str(self.root).startswith(bad + "/") or str(self.artifacts).startswith(bad + "/"):
                raise SystemExit("QA roots must not be under /tmp")
        subprocess.run(["git", "check-ignore", "-q", str(self.artifacts / "x")], cwd=REPO, check=True)

    # ----- bookkeeping -------------------------------------------------------------------------
    def save(self) -> None:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2) + "\n")

    def wanted(self, step: str) -> bool:
        return not self.only or step in self.only

    def record(self, step: str, status: str, **extra) -> None:
        entry = {"step": step, "status": status, "at": now(), **extra}
        self.summary.append(entry)
        print(json.dumps(entry), flush=True)
        (self.artifacts / "runner-summary.jsonl").open("a").write(json.dumps(entry) + "\n")

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m11_case_ledger_row@1", "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": sha_file(Path(__file__))}, "startedAt": row.get("startedAt", now()),
                "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- services ----------------------------------------------------------------------------
    def wait_http(self, url: str, timeout: float = 90) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=5):
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.5)
        raise RuntimeError(f"service did not answer: {url}")

    def start_backend(self, name: str, runs_dir: Path, code_root: Path) -> None:
        env = {**os.environ, "PYTHONPATH": str(code_root / "backend"), "MW_RUNS_DIR": str(runs_dir)}
        probe = subprocess.run([str(REPO / ".venv/bin/python"), "-c", "import mw;print(mw.__file__)"],
                               env=env, cwd=code_root, capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(code_root / "backend")):
            raise RuntimeError(f"backend import resolved outside {code_root}: {probe.stdout}")
        runs_dir.mkdir(parents=True, exist_ok=True)
        log = (self.artifacts / "services" / f"{name}.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(REPO / ".venv/bin/python"), "-m", "uvicorn", "mw.api.app:app",
             "--host", "127.0.0.1", "--port", "8000"],
            cwd=code_root, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{API}/capabilities")
        self.state.setdefault("services", []).append({"name": name, "runs": str(runs_dir), "code": str(code_root),
                                                      "mw": probe.stdout.strip(), "startedAt": now()})
        self.save()

    def start_frontend(self) -> None:
        build = FRONTEND / ".next/BUILD_ID"
        if not build.is_file():
            raise SystemExit("frontend is not built; run npm --prefix frontend run build first")
        log = self.artifacts / "services" / "frontend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["frontend"] = subprocess.Popen(
            ["npm", "--prefix", str(FRONTEND), "run", "start", "--", "-p", "3000"], cwd=REPO,
            stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(WEB + "/")

    def stop(self, name: str) -> None:
        proc = self.services.pop(name, None)
        if not proc:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=30)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)

    def capability(self) -> dict:
        with urllib.request.urlopen(f"{API}/capabilities", timeout=30) as response:
            return json.load(response)["methods"]["chemical_interactions"]

    # ----- loopback API (labeled attach setup only) -----------------------------------------------
    def call(self, method: str, path: str, body: object = None, ctype: str = "application/json") -> dict:
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        request = urllib.request.Request(API + path, data=data, method=method, headers={"content-type": ctype})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)

    # ----- step execution ----------------------------------------------------------------------
    def harness(self, step: str, args: list[str], script: str = "chemical-flow.cjs") -> tuple[int, dict | None]:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(OFFSCREEN / script), "--url", WEB, *args, "--artifacts", str(step_dir)]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        started = now()
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": started}) + "\n")
            out.flush()
            try:
                rc = subprocess.run(argv, cwd=FRONTEND, stdout=out, stderr=subprocess.STDOUT,
                                    timeout=STEP_TIMEOUT_S, check=False).returncode
            except subprocess.TimeoutExpired:
                rc = -9
        evidence_file = step_dir / "chemical-evidence.json"
        evidence = json.loads(evidence_file.read_text()) if evidence_file.exists() else None
        self.record(step, "pass" if rc == 0 else "fail", exitCode=rc, artifacts=str(step_dir), log=str(log),
                    run=(evidence or {}).get("run"))
        return rc, evidence | {"_dir": str(step_dir)} if evidence else None

    def inputs(self) -> Path:
        out = self.root / "inputs"
        if not (out / "m11-synthetic-empty-1000A.sdf").exists():
            subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m11_qa_inputs.py"), "--out", str(out)],
                           check=True, capture_output=True)
        return out

    def run_main(self) -> None:
        public = ["--receptor", str(PUBLIC_RECEPTOR), "--sdf", str(PUBLIC_SDF)]
        state = self.state
        if self.wanted("capability-ready"):
            self.harness("capability-ready", ["--mode", "capability", "--expect-capability", "ready", *public])
        if self.wanted("create"):
            rc, ev = self.harness("create", ["--mode", "create", *public])
            if rc == 0:
                state["create"] = {"run": ev["run"], "result": ev["resultHandle"], "report": ev["reportHandle"],
                                   "md": ev["report"]["markdown"]["sha256"], "json": ev["report"]["json"]["sha256"]}
        if self.wanted("empty"):
            empty = self.inputs() / "m11-synthetic-empty-1000A.sdf"
            rc, ev = self.harness("empty", ["--mode", "empty", "--receptor", str(PUBLIC_RECEPTOR), "--sdf", str(empty)])
            if rc == 0:
                state["empty"] = {"run": ev["run"], "result": ev["resultHandle"], "report": ev["reportHandle"],
                                  "md": ev["report"]["markdown"]["sha256"], "json": ev["report"]["json"]["sha256"]}
        if self.wanted("prepare-only"):
            rc, ev = self.harness("prepare-only", ["--mode", "prepare-only", *public])
            if rc == 0:
                state["prepared"] = {"run": ev["run"], "graph": ev["prepareOnly"]["graphHandle"]}
        if self.wanted("detect-controls") and state.get("prepared"):
            self.harness("detect-controls", ["--mode", "detect-controls", "--run", state["prepared"]["run"],
                                             "--graph", state["prepared"]["graph"]])
        if self.wanted("job-controls"):
            self.harness("job-controls", ["--mode", "job-controls", *public])
        if self.wanted("job-controls-failure"):
            self.harness("job-controls-failure", ["--mode", "job-controls", "--failure-expected", "true",
                                                  "--receptor", str(PUBLIC_RECEPTOR), "--sdf", str(PENTAVALENT_SDF)])
        if self.wanted("running-cancel"):
            self.harness("running-cancel", ["--mode", "running-cancel", *public])
        self.save()
        if self.wanted("attach-setup"):
            self.attach_setup()
        attach = state.get("attach")
        if attach:
            setup = Path(attach["dir"])
            common = ["--run", attach["run"], "--complex", attach["complex"], "--sdf", str(PUBLIC_SDF),
                      "--ligand", str(setup / "m11-attach-ligand-instance-run.json"),
                      "--sidecar", str(setup / "m11-attach-bonds-run.json"), "--connectivity", "sidecar"]
            if self.wanted("attach-map"):
                rc, ev = self.harness("attach-map", ["--mode", "attach", *common,
                                                     "--mapping", str(setup / "m11-attach-mapping-run.json")])
                if rc == 0:
                    attach.update(mapResult=ev["resultHandle"], mapReport=ev["reportHandle"],
                                  mapMd=ev["report"]["markdown"]["sha256"], mapJson=ev["report"]["json"]["sha256"])
            if self.wanted("attach-replace") and attach.get("mapResult"):
                rc, ev = self.harness("attach-replace", ["--mode", "attach", *common,
                                                         "--mapping",
                                                         str(setup / "m11-attach-mapping-replace-run.json")])
                if rc == 0:
                    attach.update(replaceResult=ev["resultHandle"], replaceReport=ev["reportHandle"])
            if self.wanted("reopen-complete") and attach.get("replaceResult"):
                rc, ev = self.harness("reopen-complete", ["--mode", "reopen-complete", "--run", attach["run"],
                                                          "--result", attach["replaceResult"]])
                if rc == 0:
                    attach["replaceReport2"] = ev["reportHandle"]
            if self.wanted("restrictions") and attach.get("mapResult"):
                self.harness("restrictions", ["--mode", "restrictions", "--run", attach["run"],
                                              "--result", attach["mapResult"]])
            if self.wanted("faults") and attach.get("replaceReport2"):
                self.harness("faults", ["--mode", "faults", "--run", attach["run"], "--result", attach["mapResult"],
                                        "--other-result", attach["replaceResult"], "--report", attach["replaceReport"],
                                        "--other-report", attach["replaceReport2"]])
        self.save()
        if self.wanted("invalid-inputs"):
            variants = self.root / "inputs" / "invalid"
            subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m11_invalid_inputs.py"),
                            "--out", str(variants)], check=True, capture_output=True)
            self.harness("invalid-inputs", ["--mode", "invalid-inputs", "--variants", str(variants)])
        if self.wanted("invalid-attach") and attach:
            setup = Path(attach["dir"])
            variants = self.root / "inputs" / "invalid-attach"
            subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m11_invalid_inputs.py"),
                            "--out", str(variants), "--attach-sidecar", str(setup / "m11-attach-bonds-run.json")],
                           check=True, capture_output=True)
            self.harness("invalid-attach", ["--mode", "invalid-attach", "--variants", str(variants),
                                            "--run", attach["run"], "--complex", attach["complex"],
                                            "--ligand", str(setup / "m11-attach-ligand-instance-run.json"),
                                            "--sdf", str(PUBLIC_SDF)])
        if self.wanted("reopen") and state.get("create"):
            self.harness("reopen", ["--mode", "reopen", "--run", state["create"]["run"],
                                    "--result", state["create"]["result"], "--report", state["create"]["report"]])
        self.save()

    def attach_setup(self) -> None:
        """Labeled loopback API setup: a QA run holding the synthetic attach complex, then run-bound inputs."""
        step_dir = self.fresh_dir("attach-setup")
        started = now()
        inputs = self.inputs()
        goal = "M11 attach QA (synthetic attach fixture, not experimental)"
        run = self.call("POST", "/runs", {"goal": goal})["run_id"]
        upload = self.call("POST", f"/runs/{run}/uploads?filename=m11-attach-complex.pdb",
                           (inputs / "m11-attach-complex.pdb").read_bytes(), "application/octet-stream")
        loaded = self.call("POST", f"/runs/{run}/commands", {"tool": "load_structure",
                                                              "args": {"source": upload["upload_id"]}})
        handle = loaded["handle"]
        complex_handle = handle["handle"] if isinstance(handle, dict) else handle
        sdf = self.call("POST", f"/runs/{run}/chemical/imports?kind=ligand_sdf&filename=m11-attach-ligand.sdf",
                        PUBLIC_SDF.read_bytes(), "application/octet-stream")
        setup_dir = self.root / "inputs" / "attach-setup"
        done = subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m11_attach_browser_setup.py"),
                               "--api-base", API, "--run-id", run, "--complex-handle", complex_handle,
                               "--ligand-import-handle", sdf["handle"], "--out", str(setup_dir)],
                              capture_output=True, text=True, check=True)
        self.state["attach"] = {"run": run, "complex": complex_handle, "dir": str(setup_dir),
                                "sdfImport": sdf["handle"]}
        self.write_row(step_dir, {"cases": [], "mode": "attach-setup", "evidenceType": "labeled_api_setup",
                                  "status": "pass", "runId": run, "startedAt": started,
                                  "handles": {"complex": complex_handle, "sdfImport": sdf["handle"]},
                                  "fixtures": [{"name": "m11-attach-complex.pdb",
                                                "sha256": sha_file(inputs / "m11-attach-complex.pdb")},
                                               {"name": PUBLIC_SDF.name, "sha256": sha_file(PUBLIC_SDF)}],
                                  "provenanceLabels": ["synthetic derivative attach complex; not experimental evidence",
                                                       "public ProLIF tutorial docking-pose SDF"],
                                  "setupOutput": json.loads(done.stdout), "nonLoopbackRequests": 0,
                                  "note": "Setup only (upload/load/import through loopback API); covers no H case."})
        self.record("attach-setup", "pass", run=run)
        self.save()

    # ----- H17 regression flows ------------------------------------------------------------------
    def fresh_dir(self, step: str) -> Path:
        """A rerun never overwrites an earlier attempt's evidence."""
        step_dir = self.artifacts / step
        if not step_dir.exists():
            return step_dir
        return self.artifacts / f"{step}-{datetime.now(timezone.utc).strftime('%H%M%S')}"

    def regression(self, step: str, script: str, args: list[str], jsonl: str) -> dict | None:
        step_dir = self.fresh_dir(step)
        started = now()
        argv = ["node", str(OFFSCREEN / script), "--url", WEB, *args, "--artifacts", str(step_dir)]
        log = step_dir.with_suffix(".log")
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv}) + "\n")
            out.flush()
            try:
                rc = subprocess.run(argv, cwd=FRONTEND, stdout=out, stderr=subprocess.STDOUT,
                                    timeout=STEP_TIMEOUT_S, check=False).returncode
            except subprocess.TimeoutExpired:
                rc = -9
        rows = []
        if (step_dir / jsonl).exists():
            rows = [json.loads(line) for line in (step_dir / jsonl).read_text().splitlines() if line.strip()]
        statuses = [row.get("status") for row in rows]
        passed = rc == 0 and rows and all(status in {"pass", "observed_unreviewed"} for status in statuses)
        fixture = step_dir / "fixture-run.json"
        text = fixture.read_text() if fixture.exists() else (step_dir / jsonl).read_text() if rows else ""
        found = re.search(r'"runId"\s*:\s*"(run_[0-9a-f]{32})"', text) or re.search(r"(run_[0-9a-f]{32})", text)
        run = found.group(1) if found else None
        self.write_row(step_dir, {"cases": ["H17"], "mode": step, "evidenceType": "real_electron_offscreen",
                                  "status": "pass" if passed else "fail", "exitCode": rc, "runId": run,
                                  "startedAt": started, "evidenceFile": jsonl,
                                  "statusCounts": {s: statuses.count(s) for s in set(statuses)},
                                  "harness": {"flowSha256": sha_file(OFFSCREEN / script),
                                              "runnerSha256": sha_file(Path(__file__))},
                                  "nonLoopbackRequests": 0 if passed else None,
                                  "note": "The flow asserts zero blocked non-loopback requests at each captured step."})
        self.record(step, "pass" if passed else "fail", exitCode=rc, run=run, artifacts=str(step_dir))
        return {"run": run} if passed else None

    def run_regressions(self) -> None:
        normal = None
        if self.wanted("regression-m8-normal"):
            normal = self.regression("regression-m8-normal", "normal-flow.cjs",
                                     ["--fixture", str(REPO / "backend/tests/fixtures/public_1hsg.cif")],
                                     "normal-flow.jsonl")
            if normal:
                self.state["normalRun"] = normal["run"]
        # Original M9 QA order: scenes-core needs a run holding a completed OpenMM minimization
        # (V05 saves the minimized-coordinate view), so it runs on the openmm-flow run.
        if self.wanted("regression-m9-openmm"):
            openmm = self.regression("regression-m9-openmm", "openmm-flow.cjs",
                                     ["--fixture", str(REPO / "backend/tests/fixtures/public_1ubq.cif"),
                                      "--mode", "full"], "openmm-full.jsonl")
            if openmm:
                self.state["scenesRun"] = openmm["run"]
        if self.wanted("regression-m9-scenes-core") and self.state.get("scenesRun"):
            self.regression("regression-m9-scenes-core", "scenes-flow.cjs",
                            ["--run", self.state["scenesRun"], "--mode", "core"], "scenes-core.jsonl")
        if self.wanted("regression-m10-measure"):
            self.regression("regression-m10-measure", "comparison-flow.cjs", ["--mode", "measure"],
                            "comparison-measure.jsonl")
        if self.wanted("regression-m10-alignment"):
            self.regression("regression-m10-alignment", "comparison-flow.cjs", ["--mode", "alignment"],
                            "comparison-alignment.jsonl")
        self.save()

    # ----- events-only replay (H16) ---------------------------------------------------------------
    def replay_runs(self) -> list[str]:
        return [self.state[key]["run"] for key in ("create", "empty", "attach") if self.state.get(key)]

    def probe(self, args: list[str], out: Path) -> dict:
        done = subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m11_replay_probe.py"), *args,
                               "--base-url", API, "--output", str(out),
                               *[flag for run in self.replay_runs() for flag in ("--run-id", run)]],
                              capture_output=True, text=True, check=False)
        (out.with_suffix(".log")).write_text(json.dumps({"argv": done.args}) + "\n" + done.stdout + done.stderr)
        return {"exitCode": done.returncode, "output": str(out)}

    def layout(self, name: str, pinned_worker: Path | None) -> Path:
        """Byte-identical backend/mw + config copy; the pinned worker path is absent or non-pinned."""
        target = self.root / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(REPO / "backend/mw", target / "backend/mw", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "config", target / "config", ignore=shutil.ignore_patterns("__pycache__"))
        if pinned_worker is not None:
            worker = target / ".deps/prolif/venv-locked/bin/python"
            worker.parent.mkdir(parents=True)
            worker.symlink_to(pinned_worker)
        source = {**{f"backend/mw/{k}": v for k, v in tree_digest(REPO / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(REPO / "config").items()}}
        copied = {**{f"backend/mw/{k}": v for k, v in tree_digest(target / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(target / "config").items()}}
        if source != copied:
            raise RuntimeError(f"{name}: copied backend/config differs from source")
        manifest = {"label": ("labeled runtime layout: byte-identical backend/mw and config copy; "
                              + ("pinned worker path is absent" if pinned_worker is None else
                                 f"pinned worker path points at a non-pinned interpreter {pinned_worker}")),
                    "files": len(copied), "treeSha256": hashlib.sha256(json.dumps(copied, sort_keys=True)
                                                                        .encode()).hexdigest()}
        (self.artifacts / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
        self.state.setdefault("layouts", {})[name] = manifest
        return target

    def run_replay(self) -> None:
        runs = self.replay_runs()
        if not runs or not self.state.get("create"):
            self.record("replay", "skipped", reason="create/empty/attach runs unavailable")
            return
        replay_dir = self.artifacts / "replay"
        replay_dir.mkdir(parents=True, exist_ok=True)
        # Baseline from the original root while the normal backend still serves it.
        jobs = {run: self.call("GET", f"/runs/{run}/jobs") for run in runs}
        active = {run: [job["job_id"] for job in items if job["status"] in {"running", "claimed"}]
                  for run, items in jobs.items()}
        if any(active.values()):
            raise RuntimeError(f"replay runs still have active jobs: {active}")
        before = self.probe(["snapshot", "--runs-root", str(self.root / "runs")], replay_dir / "replay-before.json")
        self.record("replay-snapshot", "pass" if before["exitCode"] == 0 else "fail", **before)
        self.stop("backend")
        replay_root = self.root / "replay-runs"
        inventory = []
        for run in runs:
            source = self.root / "runs" / run / "events.jsonl"
            target = replay_root / run / "events.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            inventory.append({"path": f"{run}/events.jsonl", "bytes": target.stat().st_size,
                              "sha256": sha_file(target), "sourceSha256": sha_file(source)})
        withheld = self.root / "inputs.withheld-during-replay"
        (self.root / "inputs").rename(withheld)
        (replay_dir / "events-only-root-inventory.json").write_text(json.dumps({
            "recordedAt": now(), "replayRoot": str(replay_root), "eventsOnly": inventory,
            "entries": sorted(str(p.relative_to(replay_root)) for p in replay_root.rglob("*")),
            "originalInputsWithheldAt": str(withheld), "originalInputsPathPresent": (self.root / "inputs").exists()},
            indent=2) + "\n")
        try:
            layout = self.layout("layout-worker-missing", None)
            self.start_backend("backend-replay-worker-missing", replay_root, layout)
            cap = self.capability()
            if cap["available"] or cap["reason_code"] != "worker_missing":
                raise RuntimeError(f"replay backend worker is not missing: {cap}")
            verify_args = ["verify", "--runs-root", str(replay_root),
                           "--baseline", str(replay_dir / "replay-before.json")]
            pre = self.probe(verify_args, replay_dir / "replay-prebrowser-verification.json")
            self.api_row("replay-probe-prebrowser", pre, replay_dir)
            label = self.state["layouts"]["layout-worker-missing"]["label"]
            for key, result, report, md, js in (
                    ("create", "result", "report", "md", "json"), ("empty", "result", "report", "md", "json"),
                    ("attach", "mapResult", "mapReport", "mapMd", "mapJson")):
                item = self.state.get(key)
                if not item or not item.get(result):
                    continue
                self.harness(f"replay-{key}", ["--mode", "replay", "--run", item["run"], "--result", item[result],
                                               "--report", item[report], "--expect-capability", "worker_missing",
                                               "--expect-markdown-sha", item[md], "--expect-json-sha", item[js],
                                               "--fixture-label", label])
            post = self.probe(verify_args, replay_dir / "replay-postbrowser-verification.json")
            self.api_row("replay-probe-postbrowser", post, replay_dir)
            self.harness("capability-worker-missing", [
                "--mode", "capability", "--expect-capability", "worker_missing", "--fixture-label", label,
                "--receptor", str(PUBLIC_RECEPTOR), "--sdf", str(PUBLIC_SDF)])
        finally:
            self.stop("backend")
            withheld.rename(self.root / "inputs")
        self.save()

    def api_row(self, mode: str, probe: dict, replay_dir: Path) -> None:
        out = Path(probe["output"])
        result = json.loads(out.read_text()) if out.exists() else {}
        passed = probe["exitCode"] == 0 and result.get("ok") is True
        self.write_row(self.fresh_dir(mode), {
            "cases": ["H16"], "mode": mode, "evidenceType": "direct_api", "status": "pass" if passed else "fail",
            "runId": ",".join(self.replay_runs()), "evidenceFile": str(out), "exitCode": probe["exitCode"],
            "harness": {"replayProbeSha256": sha_file(REPO / "scripts/m11_replay_probe.py"),
                        "runnerSha256": sha_file(Path(__file__))},
            "nonLoopbackRequests": 0, "fixtureLabels": [self.state["layouts"]["layout-worker-missing"]["label"]],
            "note": "GET-only loopback comparison of all object files, API responses and report bytes against the "
                    "original-root baseline; events may only gain allowed viewer observations."})
        self.record(mode, "pass" if passed else "fail", output=str(out))

    def run_capability_mismatch(self) -> None:
        layout = self.layout("layout-worker-mismatch", REPO / ".venv/bin/python")
        try:
            self.start_backend("backend-worker-mismatch", self.root / "capability-mismatch-runs", layout)
            cap = self.capability()
            if cap["available"] or cap["reason_code"] != "worker_version_invalid":
                raise RuntimeError(f"mismatch layout did not report worker_version_invalid: {cap}")
            self.harness("capability-worker-version-invalid", [
                "--mode", "capability", "--expect-capability", "worker_version_invalid",
                "--fixture-label", self.state["layouts"]["layout-worker-mismatch"]["label"],
                "--receptor", str(PUBLIC_RECEPTOR), "--sdf", str(PUBLIC_SDF)])
        finally:
            self.stop("backend")
        self.save()

    def leftovers(self) -> list[str]:
        ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True,
                            check=False).stdout.splitlines()
        markers = [str(REPO / "backend/mw/jobs"), str(self.root)]
        left = [line.strip() for line in ps if any(marker in line for marker in markers) and
                ("guardian.py" in line or "chemical_worker.py" in line or "openmm_worker.py" in line)]
        for port in (8000, 3000):
            listening = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                       capture_output=True, text=True, check=False).stdout.split()
            left += [f"port {port} still listening: pid {pid}" for pid in listening]
        return left

    def run(self) -> int:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        runs = self.root / "runs"
        if "main" in self.phases and not self.only and runs.exists() and any(runs.iterdir()):
            raise SystemExit(f"runs root {self.root / 'runs'} is not fresh; choose a new --root")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True,
                                check=False).stdout
        self.state["build"] = {"buildId": (FRONTEND / ".next/BUILD_ID").read_text().strip(), "gitHead": head,
                               "gitStatusPorcelainSha256": hashlib.sha256(status.encode()).hexdigest(),
                               "dirtyFiles": status.splitlines(), "recordedAt": now(),
                               "harnessSha256": {name: sha_file(OFFSCREEN / name) for name in (
                                   "chemical-flow.cjs", "m11-ledger.cjs", "m11-case-ledger.cjs", "driver.cjs",
                                   "main.cjs")},
                               "runnerSha256": sha_file(Path(__file__))}
        self.save()
        try:
            needs_services = [p for p in self.phases if p != "ledger"]
            if needs_services:
                self.start_frontend()
            if "main" in self.phases or "regressions" in self.phases or "replay" in self.phases:
                self.start_backend("backend-main", self.root / "runs", REPO)
            if "main" in self.phases:
                self.run_main()
            if "regressions" in self.phases:
                self.run_regressions()
            if "replay" in self.phases:
                self.run_replay()
            self.stop("backend")
            if "capability-mismatch" in self.phases:
                self.run_capability_mismatch()
        finally:
            for name in list(self.services):
                self.stop(name)
            self.save()
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        if "ledger" in self.phases:
            done = subprocess.run(["node", str(OFFSCREEN / "m11-case-ledger.cjs"), "--root", str(self.artifacts),
                                   "--out", str(self.artifacts / "case-ledger.json")],
                                  capture_output=True, text=True, check=False)
            self.record("case-ledger", "pass" if done.returncode == 0 else "fail", output=done.stdout.strip(),
                        error=done.stderr.strip()[-2000:])
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "artifacts": str(self.artifacts)}), flush=True)
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (runs/, replay-runs/, inputs/); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m11-acceptance/<label>")
    parser.add_argument("--phases", default=",".join(PHASES), help=f"comma list of {PHASES}")
    parser.add_argument("--only", help=f"comma list of steps to (re)run: {MAIN_STEPS + REGRESSION_STEPS}")
    return Runner(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
