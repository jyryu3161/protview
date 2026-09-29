#!/usr/bin/env python3
"""Run the M13 analysis-workflow offscreen acceptance (spec §12) and, on request, the M8-M12 regressions.

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend and
MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives the real Electron offscreen flow
frontend/tests/offscreen/workflows-flow.cjs mode by mode, and assembles case-ledger.json. Every step keeps its own
directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never deleted or retried away.

Phases (``--phases``, comma list, in this order):
  workflows    main (1HSG: inspect_ligand raw+prepared, find_cavities, prerequisites, stops, quick clicks), m10
               (measure_atoms, compare_structures), race (second offscreen window, held Advance across a run switch),
               minimize (1UBQ: labeled worker fault → retry, shared job, stop while running), chemical-create
               (create_new, chemical find_cavities, main-panel placement), attach-setup (labeled loopback API setup:
               synthetic attach complex upload/load + SDF import, then scripts/m11_attach_browser_setup.py),
               chemical-attach (attach_existing), chemical-error (labeled impossible-valence SDF), dry-run.
  unavailable  backend from a labeled layout under the root (byte-identical backend/mw + config, no .deps: fpocket
               and the ProLIF worker absent); the unavailable mode shows 사용할 수 없음 with the reason.
  regressions  M8 normal-flow (1HSG), M9 openmm-flow full (1UBQ) then scenes-flow core on that run, M10
               comparison-flow measure and alignment, on this runner's services.
  m11          scripts/m11_offscreen_acceptance.py, all phases (it starts and stops its own services).
  m12          scripts/m12_offscreen_acceptance.py, all phases (it starts and stops its own services).
  ledger       case-ledger.json + README.md + SHA256SUMS into --out (text evidence, <repo>/<home> redacted).
Default: workflows,unavailable,ledger. Full T8 set: workflows,unavailable,regressions,m11,m12,ledger.

A case passes only when every step that covers it has a passing latest row. Every row must carry a measured
non-loopback request count of 0 and zero provider calls (no egress events, zero external tokens/USD). Product issues
observed while driving (recovered through a visible control) are failing P-* cases. No worker process whose working
directory is inside the root and no 8000/3000 listener may remain. Exit status is 1 on any failure.

The runs root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an
allowlisted environment (no OPENROUTER_* or other secrets). This script never imports mw.

Usage:
  .venv/bin/python scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/<label> \\
      [--out docs/qa/m13-workflows-<YYYYMMDD>] [--phases ...] [--only step,step] [--code-root <dir>] [--build auto|always|never]
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
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
PHASES = ["workflows", "unavailable", "regressions", "m11", "m12", "ledger"]
DEFAULT_PHASES = "workflows,unavailable,ledger"
WORKFLOW_STEPS = ["main", "m10", "race", "minimize", "chemical-create", "attach-setup", "chemical-attach",
                  "chemical-error", "dry-run"]
UNAVAILABLE_STEPS = ["unavailable"]
REGRESSION_STEPS = ["regression-m8-normal", "regression-m9-openmm", "regression-m9-scenes-core",
                    "regression-m10-measure", "regression-m10-alignment"]
RUNNER_STEPS = ["m11-acceptance", "m12-acceptance"]
PHASE_STEPS = {"workflows": WORKFLOW_STEPS, "unavailable": UNAVAILABLE_STEPS, "regressions": REGRESSION_STEPS,
               "m11": ["m11-acceptance"], "m12": ["m12-acceptance"], "ledger": []}
ALL_STEPS = WORKFLOW_STEPS + UNAVAILABLE_STEPS + REGRESSION_STEPS + RUNNER_STEPS
# Spec §12 cases → the flow modes that observe them (each listed mode must pass the case).
CASE_PLAN: dict[str, list[str]] = {
    "W-inspect-raw": ["main"], "W-inspect-prepared": ["main"], "W-cavities-main": ["main"],
    "W-measure": ["m10"], "W-compare": ["m10"], "W-minimize": ["minimize"],
    "W-chem-create": ["chemical-create"], "W-cavities-chemical": ["chemical-create"], "W-chem-attach": ["chemical-attach"],
    "S-unavailable": ["unavailable"], "S-nl-unavailable": ["main", "unavailable"],
    "S-prereq-ligand": ["main"], "S-prereq-chains": ["main"], "S-prereq-ca": ["m10"], "S-prereq-chem": ["chemical-create"],
    "S-error": ["chemical-error", "minimize"], "S-retry": ["minimize"],
    "S-stop-plan-approval": ["main"], "S-stop-scientific-approval": ["main"], "S-stop-running": ["minimize"],
    "S-shared": ["minimize"], "S-scientific-already": ["minimize", "chemical-create"],
    "S-race-clicks": ["main"], "S-race-window": ["race"], "S-race-run-switch": ["race"],
    "S-dry-run": ["dry-run"], "S-chem-placement": ["chemical-create"],
}
CASE_TEXT = {
    "W-inspect-raw": "inspect_ligand from the raw structure (prepare step in the plan)",
    "W-inspect-prepared": "inspect_ligand from a prepared structure",
    "W-cavities-main": "find_cavities, main screen, prepared source with explicit chains",
    "W-measure": "measure_atoms from two real atom picks", "W-compare": "compare_structures from explicit CA pairs",
    "W-minimize": "minimize_protein (1UBQ)", "W-chem-create": "chemical_interactions create_new",
    "W-cavities-chemical": "find_cavities on a chemical_structure (chemical screen)",
    "W-chem-attach": "chemical_interactions attach_existing",
    "S-unavailable": "method engine absent → 사용할 수 없음 with the reason",
    "S-nl-unavailable": "natural-language planning shown unavailable (disabled, reason)",
    "S-prereq-ligand": "prerequisite unmet: no ligand", "S-prereq-chains": "prerequisite unmet: no explicit chains",
    "S-prereq-ca": "prerequisite unmet: no CA pairs", "S-prereq-chem": "prerequisite unmet: no chemistry request",
    "S-error": "step error shown (typed native failure; job failure)",
    "S-retry": "one explicit retry after a labeled worker fault",
    "S-stop-plan-approval": "Stop while waiting for plan approval",
    "S-stop-scientific-approval": "Stop while the job waits for scientific approval",
    "S-stop-running": "Stop while the owned job runs", "S-shared": "shared-job explanation (observed_shared)",
    "S-scientific-already": "이 run에서 이미 계산 승인됨 shown instead of a second approval",
    "S-race-clicks": "two quick clicks start one step", "S-race-window": "second window: concurrent Advance",
    "S-race-run-switch": "held Advance response across a run switch", "S-dry-run": "dry-run run: plan_only + notice",
    "S-chem-placement": "chemical goal/results placed in the chemical screen",
}
ENV_ALLOW = frozenset({"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TMPDIR", "TERM", "TZ",
                       "__CF_USER_TEXT_ENCODING"})
ATTEMPT_SUFFIX = re.compile(r"-(\d{8}T\d+)$")
STEP_TIMEOUT_S = 2400
WORKERS = ("guardian.py", "chemical_worker.py", "openmm_worker.py", "pocket_worker.py", "fpocket")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def tree_digest(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha_file(path) for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    kept = {key: value for key, value in os.environ.items() if key in ENV_ALLOW or key.startswith("LC_")}
    return {**kept, **(extra or {})}


def step_base(name: str) -> tuple[str, tuple[int, str]]:
    found = ATTEMPT_SUFFIX.search(name)
    return (name[:found.start()], (1, found.group(1))) if found else (name, (0, ""))


def listening(port: int) -> list[str]:
    return subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                          check=False).stdout.split()


def redact(text: str, replacements: list[tuple[str, str]]) -> str:
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def sub_ledger_verdict(data: dict | None) -> tuple[str | None, int | None]:
    """(verdict, measured non-loopback total) of an M11 or M12 acceptance ledger; the total is None if any row is unmeasured.

    m11_case_ledger@1 has no verdict field: it passes iff summary.fail == 0, summary.missing == 0, at least one case
    passed, every row measured its non-loopback requests and nonLoopbackRequestsTotal == 0.
    m12_case_ledger@1 carries its own verdict, externalRequestsTotal and rowsWithUnknownExternalCount.
    """
    if not isinstance(data, dict):
        return None, None
    if data.get("schema") == "m11_case_ledger@1":
        summary = data.get("summary") or {}
        external = None if data.get("rowsWithUnknownRequestCount") else data.get("nonLoopbackRequestsTotal")
        passed = (summary.get("fail") == 0 and summary.get("missing") == 0 and (summary.get("pass") or 0) > 0
                  and external == 0)
        return ("pass" if passed else "fail"), external
    if data.get("schema") == "m12_case_ledger@1":
        external = None if data.get("rowsWithUnknownExternalCount") else data.get("externalRequestsTotal")
        verdict = data.get("verdict")
        return (verdict if verdict != "pass" or external == 0 else "fail"), external
    return None, None


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.code = Path(args.code_root).resolve()
        self.frontend = self.code / "frontend"
        self.offscreen = self.frontend / "tests/offscreen"
        self.fixtures = self.code / "backend/tests/fixtures"
        venv = self.code / ".venv/bin/python"
        self.python = venv if venv.exists() else REPO / ".venv/bin/python"
        self.root = Path(args.root).resolve()
        self.artifacts = Path(args.artifacts).resolve()
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        self.out = Path(args.out).resolve() if args.out else self.code / "docs/qa" / f"m13-workflows-{stamp}"
        self.build_mode = args.build
        self.only = set(filter(None, (args.only or "").split(",")))
        self.partial = bool(self.only)
        unknown = self.only - set(ALL_STEPS)
        if unknown:
            raise SystemExit(f"unknown --only steps: {sorted(unknown)}; choose from {ALL_STEPS}")
        requested = set(filter(None, args.phases.split(",")))
        if requested - set(PHASES):
            raise SystemExit(f"unknown phases: {sorted(requested - set(PHASES))}; choose from {PHASES}")
        self.phases = [p for p in PHASES if p in requested]
        if self.only:
            self.phases = [p for p in self.phases if p == "ledger" or self.only & set(PHASE_STEPS[p])]
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        for bad in ("/tmp", "/private/tmp"):
            for path in (self.root, self.artifacts):
                if str(path) == bad or str(path).startswith(bad + "/"):
                    raise SystemExit("QA roots must not be under /tmp")
        if self.root == self.code / "runs" or self.root == REPO / "runs":
            raise SystemExit("--root must be a fresh folder, not the repository runs/ folder itself")
        ignored = subprocess.run(["git", "check-ignore", "-q", str(self.artifacts / "x")], cwd=self.code, check=False)
        if ignored.returncode != 0:
            raise SystemExit(f"--artifacts must be git-ignored: {self.artifacts}")

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
        with (self.artifacts / "runner-summary.jsonl").open("a") as out:
            out.write(json.dumps(entry) + "\n")

    def fresh_dir(self, step: str) -> Path:
        step_dir = self.artifacts / step
        if not step_dir.exists():
            return step_dir
        return self.artifacts / f"{step}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m13_case_ledger_row@1", "step": step_dir.name, "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- build -------------------------------------------------------------------------------
    def build(self) -> None:
        build_id = self.frontend / ".next/BUILD_ID"
        if self.build_mode == "never" or (self.build_mode == "auto" and build_id.is_file()):
            if not build_id.is_file():
                raise SystemExit("frontend is not built and --build never was given")
            self.state["buildCommands"] = {"skipped": True, "reason": f"--build {self.build_mode}, BUILD_ID present"}
            return
        results = {}
        for script in ("typecheck", "build"):  # sequential: typecheck and build never run concurrently
            log = self.artifacts / "services" / f"{script}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("w") as out:
                rc = subprocess.run(["npm", "--prefix", str(self.frontend), "run", script], cwd=self.code,
                                    env=child_env(), stdout=out, stderr=subprocess.STDOUT, check=False).returncode
            results[script] = rc
            self.record(f"frontend-{script}", "pass" if rc == 0 else "fail", exitCode=rc, log=str(log))
            if rc != 0:
                raise SystemExit(f"npm run {script} failed ({rc}); see {log}")
        self.state["buildCommands"] = results

    # ----- services ----------------------------------------------------------------------------
    def wait_http(self, url: str, timeout: float = 120) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=5):
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(0.5)
        raise RuntimeError(f"service did not answer: {url}")

    def start_backend(self, name: str, runs_dir: Path, code_root: Path) -> None:
        env = child_env({"PYTHONPATH": str(code_root / "backend"), "MW_RUNS_DIR": str(runs_dir)})
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=code_root,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(code_root / "backend")):
            raise RuntimeError(f"backend import resolved outside {code_root}: {probe.stdout}")
        runs_dir.mkdir(parents=True, exist_ok=True)
        log = self.artifacts / "services" / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=code_root, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{API}/capabilities")
        self.state.setdefault("services", []).append({"name": name, "runs": str(runs_dir), "code": str(code_root),
                                                      "mw": probe.stdout.strip(), "startedAt": now()})
        self.save()

    def start_frontend(self) -> None:
        log = self.artifacts / "services" / "frontend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["frontend"] = subprocess.Popen(
            ["npm", "--prefix", str(self.frontend), "run", "start", "--", "-p", "3000"], cwd=self.code,
            env=child_env(), stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
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

    def stop_all(self) -> None:
        for name in list(self.services):
            self.stop(name)

    def get_json(self, path: str):
        with urllib.request.urlopen(API + path, timeout=120) as response:
            return json.loads(response.read())

    def call(self, method: str, path: str, body: object = None, ctype: str = "application/json") -> dict:
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        request = urllib.request.Request(API + path, data=data, method=method, headers={"content-type": ctype})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)

    # ----- flow steps --------------------------------------------------------------------------
    def node(self, step: str, script: str, args: list[str]) -> tuple[int, Path]:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / script), "--url", WEB, *args, "--artifacts", str(step_dir)]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            try:
                rc = subprocess.run(argv, cwd=self.frontend, env=child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    timeout=STEP_TIMEOUT_S, check=False).returncode
            except subprocess.TimeoutExpired:
                rc = -9
        return rc, step_dir

    def flow(self, step: str, mode: str, extra: list[str] | None = None) -> dict | None:
        rc, step_dir = self.node(step, "workflows-flow.cjs", ["--mode", mode, *(extra or [])])
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        if row is None:
            self.write_row(step_dir, {"mode": mode, "evidenceKind": "real_electron_offscreen", "status": "fail",
                                      "cases": {}, "externalRequestCount": None,
                                      "error": f"harness exited {rc} without a ledger row"})
        passed = rc == 0 and row is not None and row.get("status") == "pass"
        self.record(step, "pass" if passed else "fail", exitCode=rc, artifacts=str(step_dir),
                    run=(row or {}).get("runId"), cases=(row or {}).get("cases"))
        return row

    def run_workflows(self) -> None:
        runs = self.root / "runs"
        state = self.state
        if self.wanted("main"):
            row = self.flow("main", "main")
            if row and row.get("runId"):
                state["mainRun"] = row["runId"]
        if self.wanted("m10"):
            row = self.flow("m10", "m10")
            if row and row.get("runId"):
                state["m10Run"] = row["runId"]
        self.save()
        if self.wanted("race"):
            if state.get("mainRun") and state.get("m10Run"):
                self.flow("race", "race", ["--run", state["mainRun"], "--other-run", state["m10Run"]])
            else:
                self.missing_prerequisite("race", "main and m10 runs are required (prerequisite step failed)")
        if self.wanted("minimize"):
            self.flow("minimize", "minimize", ["--runs-root", str(runs)])
        if self.wanted("chemical-create"):
            self.flow("chemical-create", "chemical-create")
        if self.wanted("attach-setup"):
            self.attach_setup()
        if self.wanted("chemical-attach"):
            attach = state.get("attach")
            if attach:
                setup = Path(attach["dir"])
                self.flow("chemical-attach", "chemical-attach", [
                    "--run", attach["run"], "--complex", attach["complex"],
                    "--mapping", str(setup / "m11-attach-mapping-run.json"),
                    "--ligand", str(setup / "m11-attach-ligand-instance-run.json"),
                    "--sidecar", str(setup / "m11-attach-bonds-run.json")])
            else:
                self.missing_prerequisite("chemical-attach", "labeled attach setup unavailable (attach-setup failed)")
        if self.wanted("chemical-error"):
            self.flow("chemical-error", "chemical-error")
        if self.wanted("dry-run"):
            self.flow("dry-run", "dry-run")
        self.save()

    def missing_prerequisite(self, step: str, reason: str) -> None:
        step_dir = self.fresh_dir(step)
        self.write_row(step_dir, {"mode": step, "evidenceKind": "not_run", "status": "fail", "cases": {},
                                  "externalRequestCount": None, "error": reason})
        self.record(step, "fail", reason=reason)

    def m11_inputs(self) -> Path:
        out = self.root / "inputs" / "m11"
        if not (out / "m11-attach-complex.pdb").exists():
            subprocess.run([str(self.python), str(self.code / "scripts/m11_qa_inputs.py"), "--out", str(out)],
                           env=child_env(), check=True, capture_output=True)
        return out

    def attach_setup(self) -> None:
        """Labeled loopback API setup (as in the M11 runner): a QA run holding the synthetic attach complex."""
        step_dir = self.fresh_dir("attach-setup")
        try:
            inputs = self.m11_inputs()
            sdf_path = self.fixtures / "chemical/prolif-vina-output.sdf"
            run = self.call("POST", "/runs", {"goal": "M13 attach QA (synthetic attach fixture, not experimental)"})["run_id"]
            upload = self.call("POST", f"/runs/{run}/uploads?filename=m11-attach-complex.pdb",
                               (inputs / "m11-attach-complex.pdb").read_bytes(), "application/octet-stream")
            loaded = self.call("POST", f"/runs/{run}/commands", {"tool": "load_structure",
                                                                  "args": {"source": upload["upload_id"]}})
            handle = loaded["handle"]
            complex_handle = handle["handle"] if isinstance(handle, dict) else handle
            sdf = self.call("POST", f"/runs/{run}/chemical/imports?kind=ligand_sdf&filename=m11-attach-ligand.sdf",
                            sdf_path.read_bytes(), "application/octet-stream")
            setup_dir = self.root / "inputs" / "attach-setup"
            done = subprocess.run([str(self.python), str(self.code / "scripts/m11_attach_browser_setup.py"),
                                   "--api-base", API, "--run-id", run, "--complex-handle", complex_handle,
                                   "--ligand-import-handle", sdf["handle"], "--out", str(setup_dir)],
                                  env=child_env(), capture_output=True, text=True, check=True)
            self.state["attach"] = {"run": run, "complex": complex_handle, "dir": str(setup_dir), "sdfImport": sdf["handle"]}
            self.write_row(step_dir, {"mode": "attach-setup", "evidenceKind": "labeled_api_setup", "status": "pass",
                                      "cases": {}, "runId": run, "externalRequestCount": 0, "providerCallsZero": True,
                                      "handles": {"complex": complex_handle, "sdfImport": sdf["handle"]},
                                      "inputs": [{"name": "m11-attach-complex.pdb",
                                                  "sha256": sha_file(inputs / "m11-attach-complex.pdb"),
                                                  "provenance": "synthetic derivative attach complex; not experimental evidence"},
                                                 {"name": sdf_path.name, "sha256": sha_file(sdf_path),
                                                  "provenance": "public ProLIF tutorial docking-pose SDF"}],
                                      "setupOutput": json.loads(done.stdout),
                                      "note": "Setup only (loopback upload/load/import); covers no case."})
            self.record("attach-setup", "pass", run=run)
        except (subprocess.CalledProcessError, urllib.error.URLError, KeyError, ValueError, OSError) as exc:
            self.write_row(step_dir, {"mode": "attach-setup", "evidenceKind": "labeled_api_setup", "status": "fail",
                                      "cases": {}, "externalRequestCount": 0, "error": repr(exc)})
            self.record("attach-setup", "fail", error=repr(exc))
        self.save()

    # ----- unavailable (labeled layout) --------------------------------------------------------
    def layout(self, name: str) -> Path:
        """Byte-identical backend/mw + config copy without .deps: fpocket and the ProLIF worker are absent."""
        target = self.root / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.code / "backend/mw", target / "backend/mw", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.code / "config", target / "config", ignore=shutil.ignore_patterns("__pycache__"))
        source = {**{f"backend/mw/{k}": v for k, v in tree_digest(self.code / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(self.code / "config").items()}}
        copied = {**{f"backend/mw/{k}": v for k, v in tree_digest(target / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(target / "config").items()}}
        if source != copied:
            raise RuntimeError(f"{name}: copied backend/config differs from source")
        manifest = {"label": "labeled runtime layout: byte-identical backend/mw and config copy; .deps absent "
                             "(fpocket and the ProLIF worker environment not installed)",
                    "files": len(copied), "treeSha256": sha_bytes(json.dumps(copied, sort_keys=True).encode())}
        (self.artifacts / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
        self.state.setdefault("layouts", {})[name] = manifest
        self.save()
        return target

    def run_unavailable(self) -> None:
        if not self.wanted("unavailable"):
            return
        layout = self.layout("layout-engines-missing")
        try:
            self.start_backend("backend-unavailable", self.root / "unavailable-runs", layout)
            cap = self.get_json("/capabilities")["methods"]["analysis_workflows"]["templates"]
            if cap["find_cavities"]["available"] or cap["chemical_interactions"]["available"]:
                self.missing_prerequisite("unavailable", f"layout still reports the engines available: {cap}")
                return
            self.flow("unavailable", "unavailable", ["--fixture-label", self.state["layouts"]["layout-engines-missing"]["label"]])
        finally:
            self.stop("backend")

    # ----- M8-M10 regressions (same flows and order as the M12 runner) --------------------------
    def regression(self, step: str, script: str, args: list[str], jsonl: str, cases: str) -> dict | None:
        started = now()
        rc, step_dir = self.node(step, script, args)
        rows = []
        if (step_dir / jsonl).exists():
            rows = [json.loads(line) for line in (step_dir / jsonl).read_text().splitlines() if line.strip()]
        statuses = [row.get("status") for row in rows]
        measured = [len(row["after"]["blockedRequests"]) for row in rows
                    if isinstance(row.get("after"), dict) and isinstance(row["after"].get("blockedRequests"), list)]
        external = max(measured) if rows and len(measured) == len(rows) else None
        passed = (rc == 0 and bool(rows) and all(item in {"pass", "observed_unreviewed"} for item in statuses) and
                  external == 0)
        fixture = step_dir / "fixture-run.json"
        text = fixture.read_text() if fixture.exists() else (step_dir / jsonl).read_text() if rows else ""
        found = re.search(r'"runId"\s*:\s*"(run_[0-9a-f]{32})"', text) or re.search(r"(run_[0-9a-f]{32})", text)
        run = found.group(1) if found else None
        self.write_row(step_dir, {"mode": step, "regression": cases, "evidenceKind": "real_electron_offscreen",
                                  "status": "pass" if passed else "fail", "exitCode": rc, "runId": run, "cases": {},
                                  "startedAt": started, "evidenceFile": jsonl, "providerCallsZero": None,
                                  "statusCounts": {s: statuses.count(s) for s in set(statuses)},
                                  "harness": {"flowSha256": sha_file(self.offscreen / script),
                                              "runnerSha256": sha_file(Path(__file__))},
                                  "externalRequestCount": external,
                                  "externalRequestMeasurement": {"rowsWithStatus": len(measured), "rows": len(rows),
                                                                 "rule": "max(len(row.after.blockedRequests))"}})
        self.record(step, "pass" if passed else "fail", exitCode=rc, run=run, artifacts=str(step_dir))
        return {"run": run} if passed else None

    def run_regressions(self) -> None:
        f = self.fixtures
        if self.wanted("regression-m8-normal"):
            self.regression("regression-m8-normal", "normal-flow.cjs", ["--fixture", str(f / "public_1hsg.cif")],
                            "normal-flow.jsonl", "M8")
        if self.wanted("regression-m9-openmm"):
            done = self.regression("regression-m9-openmm", "openmm-flow.cjs",
                                   ["--fixture", str(f / "public_1ubq.cif"), "--mode", "full"],
                                   "openmm-full.jsonl", "M9 prerequisite (OpenMM run)")
            if done:
                self.state["scenesRun"] = done["run"]
        if self.wanted("regression-m9-scenes-core"):
            if self.state.get("scenesRun"):
                self.regression("regression-m9-scenes-core", "scenes-flow.cjs",
                                ["--run", self.state["scenesRun"], "--mode", "core"], "scenes-core.jsonl", "M9")
            else:
                self.missing_prerequisite("regression-m9-scenes-core", "no completed OpenMM run (regression-m9-openmm failed)")
        if self.wanted("regression-m10-measure"):
            self.regression("regression-m10-measure", "comparison-flow.cjs", ["--mode", "measure"],
                            "comparison-measure.jsonl", "M10")
        if self.wanted("regression-m10-alignment"):
            self.regression("regression-m10-alignment", "comparison-flow.cjs", ["--mode", "alignment"],
                            "comparison-alignment.jsonl", "M10")
        self.save()

    # ----- M11 / M12 acceptance runners (each owns its services) --------------------------------
    def sub_runner(self, step: str, script: str) -> None:
        if not self.wanted(step):
            return
        step_dir = self.fresh_dir(step)
        step_dir.mkdir(parents=True, exist_ok=True)
        sub_root = self.root / step
        sub_artifacts = step_dir / "evidence"
        argv = [str(self.python), str(self.code / "scripts" / script), "--root", str(sub_root),
                "--artifacts", str(sub_artifacts)]
        log = step_dir.with_suffix(".log")
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            rc = subprocess.run(argv, cwd=self.code, env=child_env(), stdout=out, stderr=subprocess.STDOUT,
                                check=False).returncode
        ledger = sub_artifacts / "case-ledger.json"
        verdict, external = sub_ledger_verdict(json.loads(ledger.read_text()) if ledger.exists() else None)
        passed = rc == 0 and verdict == "pass"
        self.write_row(step_dir, {"mode": step, "regression": script, "evidenceKind": "acceptance_runner",
                                  "status": "pass" if passed else "fail", "exitCode": rc, "cases": {},
                                  "subVerdict": verdict, "subLedger": str(ledger), "argv": argv,
                                  "externalRequestCount": external, "providerCallsZero": None,
                                  "note": "Its own ledger requires a measured non-loopback count of 0 on every row."})
        self.record(step, "pass" if passed else "fail", exitCode=rc, verdict=verdict, ledger=str(ledger))

    # ----- ledger and evidence -----------------------------------------------------------------
    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "status": row.get("status"),
                         "cases": row.get("cases") or {}, "runId": row.get("runId"),
                         "evidenceKind": row.get("evidenceKind"), "handles": row.get("handles", {}),
                         "inputs": row.get("inputs", []), "fixtureLabels": row.get("fixtureLabels", []),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        attempts: dict[str, list[tuple[tuple[int, str], dict]]] = {}
        for row in rows:
            base, order = step_base(row["step"])
            attempts.setdefault(base, []).append((order, row))
        required = sorted(self.only) if self.partial else [s for p in self.phases for s in PHASE_STEPS[p]]
        latest = {step: max(found, key=lambda item: item[0])[1] for step, found in attempts.items()}
        steps: dict[str, dict] = {}
        for step in required:
            row = latest.get(step)
            if row is None:
                steps[step] = {"status": "missing"}
                continue
            problems = []
            if row["status"] != "pass":
                problems.append(f"status {row['status']}")
            if row["externalRequestCount"] != 0:
                problems.append(f"externalRequestCount {row['externalRequestCount']!r}")
            if row["evidenceKind"] == "real_electron_offscreen" and step not in REGRESSION_STEPS and \
                    row.get("providerCallsZero") is not True:
                problems.append("provider calls not measured zero")
            steps[step] = {"status": "fail" if problems else "pass", "latest": row["step"], "problems": problems,
                           "attempts": len(attempts[step])}
        cases: dict[str, dict] = {}
        ran_steps = set(required)
        for case, modes in CASE_PLAN.items():
            covering = [mode for mode in modes if mode in ran_steps]
            if not covering:
                continue
            seen = {mode: (latest.get(mode) or {}).get("cases", {}).get(case) for mode in covering}
            cases[case] = {"text": CASE_TEXT[case], "modes": seen,
                           "status": "pass" if all(value == "pass" for value in seen.values()) else "fail"}
        egress_rows = [r for r in rows if r["step"] in {s["latest"] for s in steps.values() if "latest" in s}]
        cases["S-no-egress"] = {"text": "non-loopback requests 0 and zero provider calls on every flow row",
                                "status": "pass" if egress_rows and all(r["externalRequestCount"] == 0 for r in egress_rows)
                                and all(r["providerCallsZero"] in (True, None) for r in egress_rows) else "fail"}
        product = {}
        for row in rows:
            for case in row["cases"]:
                if case.startswith("P-") and step_base(row["step"])[0] in latest and latest[step_base(row["step"])[0]] is row:
                    product.setdefault(case, []).append(row["step"])
        for case, where in product.items():
            cases[case] = {"text": "product issue observed while driving (recovered through a visible control)",
                           "status": "fail", "steps": where}
        verdict_parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
                         "cases": all(v["status"] == "pass" for v in cases.values()),
                         "leftoverProcesses": not leftovers}
        passed = all(verdict_parts.values())
        verdict = "partial_not_acceptance" if self.partial else "pass" if passed else "fail"
        ledger = {"schema": "m13_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": verdict, "acceptance": not self.partial and passed, "phases": self.phases,
                  "scope": {"partial": self.partial, "only": sorted(self.only), "requiredSteps": required},
                  "verdictParts": verdict_parts, "cases": cases, "steps": steps, "leftoverProcesses": leftovers,
                  "externalRequestsTotal": sum(r["externalRequestCount"] or 0 for r in rows), "rows": rows}
        name = "case-ledger-partial.json" if self.partial else "case-ledger.json"
        (self.artifacts / name).write_text(json.dumps(ledger, indent=2) + "\n")
        self.record("case-ledger", "pass" if passed else "fail", verdict=verdict,
                    cases={case: value["status"] for case, value in cases.items()}, output=str(self.artifacts / name))
        return ledger

    def readme(self, ledger: dict) -> str:
        code = "<repo>"
        lines = ["# M13 분석 흐름 오프스크린 수락 QA 증거", "",
                 f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · phases {', '.join(ledger['phases'])}",
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 "## 사례", "", "| 사례 | 내용 | 결과 | 모드 |", "|---|---|---|---|"]
        for case, value in ledger["cases"].items():
            modes = ", ".join(f"{k}:{v}" for k, v in value.get("modes", {}).items()) or ", ".join(value.get("steps", []))
            lines.append(f"| {case} | {value['text']} | {value['status']} | {modes} |")
        lines += ["", "## 단계", "", "| 단계 | 결과 | 문제 |", "|---|---|---|"]
        for step, value in ledger["steps"].items():
            lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  "npm --prefix frontend run typecheck   # build와 동시에 돌리지 않음",
                  "npm --prefix frontend run build",
                  f"{'.venv/bin/python'} scripts/m13_offscreen_acceptance.py --root runs/m13-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m13-acceptance/<label> \\",
                  "    --phases workflows,unavailable,regressions,m11,m12,ledger --out docs/qa/m13-workflows-<YYYYMMDD>",
                  "```", "",
                  ("`regressions`는 이 실행기의 서비스로 M8 normal-flow, M9 openmm-flow full → scenes-flow core, M10 "
                   "comparison-flow measure/alignment를 돌린다. `m11`/`m12`는 `scripts/m11_offscreen_acceptance.py`·"
                   "`scripts/m12_offscreen_acceptance.py`를 기본(전체) phase로 `<root>/m11-acceptance`·`<root>/m12-acceptance` "
                   "루트에서 실행하며 각자 서비스를 띄우고 끈다. 이 README는 실제로 실행한 phase만 기록한다."), "",
                  f"코드 루트: `{code}`"]
        return "\n".join(lines) + "\n"

    def export(self, ledger: dict) -> None:
        replacements = [(str(self.code), "<repo>"), (str(REPO), "<repo>"), (str(Path.home()), "<home>")]
        self.out.mkdir(parents=True, exist_ok=True)
        sums, binaries = [], []
        for path in sorted(self.artifacts.rglob("*")):
            rel = path.relative_to(self.artifacts)
            if not path.is_file() or rel.parts[0] == "services" or "browser-profile" in rel.parts:
                continue
            if path.suffix in {".json", ".jsonl", ".log", ".md", ".txt", ".html"}:
                target = self.out / "evidence" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(redact(path.read_text(errors="replace"), replacements))
                sums.append(f"{sha_file(target)}  evidence/{rel}")
            else:
                binaries.append({"path": str(rel), "bytes": path.stat().st_size, "sha256": sha_file(path)})
        (self.out / "binary-artifacts.json").write_text(redact(json.dumps({
            "note": "screenshots/paint frames/downloads stay in the git-ignored artifacts folder; hashes only",
            "artifacts": str(self.artifacts), "files": binaries}, indent=2), replacements) + "\n")
        (self.out / "README.md").write_text(redact(self.readme(ledger), replacements))
        for name in ("binary-artifacts.json", "README.md"):
            sums.append(f"{sha_file(self.out / name)}  {name}")
        (self.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        leaked = [str(p.relative_to(self.out)) for p in self.out.rglob("*") if p.is_file() and
                  any(old in p.read_text(errors="replace") for old, _ in replacements)]
        self.record("export-evidence", "fail" if leaked else "pass", output=str(self.out), leaked=leaked)

    def leftovers(self) -> list[str]:
        # Only workers whose working directory is inside this acceptance root count (not other pytest runs).
        root = self.root.resolve()
        left: list[str] = []
        for _ in range(10):
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
            left = []
            for line in ps.splitlines():
                pid, _, command = line.strip().partition(" ")
                if not any(w in command for w in WORKERS):
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
            left += [f"port {port} still listening: pid {pid}" for pid in listening(port)]
        return left

    def run(self) -> int:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        runs = self.root / "runs"
        if "workflows" in self.phases and not self.only and runs.exists() and any(runs.iterdir()):
            raise SystemExit(f"runs root {runs} is not fresh; choose a new --root")
        own_services = [p for p in self.phases if p in {"workflows", "unavailable", "regressions"}]
        if [p for p in self.phases if p != "ledger"]:
            busy = {port: listening(port) for port in (8000, 3000)}
            if any(busy.values()):
                raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        self.build()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.code, capture_output=True, text=True,
                              check=False).stdout.strip()
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=self.code, capture_output=True, text=True,
                                   check=False).stdout
        build_id = self.frontend / ".next/BUILD_ID"
        self.state["build"] = {"buildId": build_id.read_text().strip() if build_id.exists() else None, "gitHead": head,
                               "gitStatusPorcelainSha256": sha_bytes(porcelain.encode()), "dirtyFiles": porcelain.splitlines(),
                               "recordedAt": now(), "codeRoot": str(self.code),
                               "harnessSha256": {name: sha_file(self.offscreen / name) for name in (
                                   "workflows-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs", "comparison-flow.cjs",
                                   "openmm-flow.cjs", "scenes-flow.cjs", "chemical-flow.cjs", "pocket-flow.cjs")},
                               "runnerSha256": sha_file(Path(__file__))}
        self.save()
        try:
            if own_services:
                self.start_frontend()
            if {"workflows", "regressions"} & set(self.phases):
                self.start_backend("backend-main", runs, self.code)
            if "workflows" in self.phases:
                self.run_workflows()
            if "regressions" in self.phases:
                self.run_regressions()
            self.stop("backend")
            if "unavailable" in self.phases:
                self.run_unavailable()
        finally:
            self.stop_all()
            self.save()
        if "m11" in self.phases:
            self.sub_runner("m11-acceptance", "m11_offscreen_acceptance.py")
        if "m12" in self.phases:
            self.sub_runner("m12-acceptance", "m12_offscreen_acceptance.py")
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        if "ledger" in self.phases:
            ledger = self.ledger(left)
            if not self.partial:
                self.export(ledger)
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "artifacts": str(self.artifacts)}), flush=True)
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (runs/, inputs/, layouts, sub-runner roots); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m13-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m13-workflows-<YYYYMMDD>)")
    parser.add_argument("--phases", default=DEFAULT_PHASES, help=f"comma list of {PHASES}")
    parser.add_argument("--only", help=f"comma list of steps to (re)run: {ALL_STEPS}; the ledger is then "
                        "partial_not_acceptance and nothing is exported")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build only when frontend/.next/BUILD_ID is missing")
    return Runner(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
