#!/usr/bin/env python3
"""Run every M12 pocket offscreen mode, the M8-M11 regressions, events-only replay and unavailable displays.

One command starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend
and MW_RUNS_DIR=<root>/..., `next start` on 127.0.0.1:3000), drives real Electron offscreen runs of
frontend/tests/offscreen/pocket-flow.cjs in dependency order, reruns the M8/M9/M10/M11 regression flows,
performs the events-only replay (only events.jsonl copied, original inputs withheld, engine absent),
shows the not_installed and unreviewed_build capability states, and assembles case-ledger.json.
Every step writes its own ledger-row.json; failures are kept, never retried away or overwritten.

The ledger verdict is keyed by step name: every step in ALL_STEPS must have a passing latest attempt (a missing
step fails), every row must carry a measured non-loopback request count of zero, and no worker process or port
may be left behind. ``--only`` runs are marked "partial_not_acceptance" (case-ledger-partial.json) and never
produce an acceptance verdict. Child processes get an allowlisted environment (no OPENROUTER_* or other secrets).
``--export-evidence <dir>`` writes a copy of the text evidence with absolute paths replaced by ``<repo>`` (and
the home directory by ``<home>``) plus SHA256SUMS, for committing under docs/qa/.

Labeled runtime layouts (under the QA root, never used by the product) are byte-identical copies of
backend/mw and config/: ``layout-engine-missing`` has no .deps (fpocket not installed) and
``layout-engine-tampered`` holds the real install record next to a labeled placeholder executable whose
SHA-256 is not the reviewed build (unreviewed_build). The server locates the engine only at
<code root>/.deps/fpocket, so no request-controlled or environment hook is needed. Neither fakes success.

The frontend must already be built (`npm --prefix frontend run typecheck` then `build`); this script never
builds, installs, imports mw or contacts a non-loopback host. The runs root must be fresh and outside
/tmp; ports 8000 and 3000 must be free.

Usage:
  .venv/bin/python scripts/m12_offscreen_acceptance.py --root runs/m12-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m12-acceptance/<label> \\
      [--phases pockets,regressions,replay,unavailable,ledger] [--only step,step] [--export-evidence <dir>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
OFFSCREEN = FRONTEND / "tests/offscreen"
FIXTURES = REPO / "backend/tests/fixtures"
PUBLIC_1HSG = FIXTURES / "public_1hsg.cif"
DERIVED = FIXTURES / "derived_1hsg_first10_fixture.cif"
CHEM = FIXTURES / "chemical"
PUBLIC_RECEPTOR = CHEM / "prolif-vina-rec.pdb"
PUBLIC_SDF = CHEM / "prolif-vina-output.sdf"
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
PHASES = ["pockets", "regressions", "replay", "unavailable", "ledger"]
POCKET_STEPS = ["positive", "empty", "invalid", "cancel", "reopen", "report-download", "overlay-disables",
                "distance-with-overlay", "comparison-block", "source-race", "minimized-source", "m11-create",
                "chemical-workspace"]
REGRESSION_STEPS = ["regression-m8-normal", "regression-m9-openmm", "regression-m9-scenes-core",
                    "regression-m10-measure", "regression-m10-alignment", "regression-m11-capability-ready",
                    "regression-m11-empty", "regression-m11-prepare-only", "regression-m11-detect-controls",
                    "regression-m11-job-controls", "regression-m11-running-cancel", "regression-m11-reopen"]
REPLAY_STEPS = ["replay-api-prebrowser", "replay-positive", "replay-empty", "replay-api-postbrowser"]
UNAVAILABLE_STEPS = ["unavailable-missing", "unavailable-hash"]
ALL_STEPS = POCKET_STEPS + REGRESSION_STEPS + REPLAY_STEPS + UNAVAILABLE_STEPS
PHASE_STEPS = {"pockets": POCKET_STEPS, "regressions": REGRESSION_STEPS, "replay": REPLAY_STEPS,
               "unavailable": UNAVAILABLE_STEPS, "ledger": []}
# Every required case is keyed by its step name. The expected mode is checked for pocket-flow / direct-API rows;
# M11 and regression rows are written by their own flows (None = no mode check).
STEP_MODES: dict[str, str | None] = {
    **{step: step for step in POCKET_STEPS if step != "m11-create"}, "m11-create": None,
    **{step: None for step in REGRESSION_STEPS},
    "replay-api-prebrowser": "replay-api", "replay-positive": "replay", "replay-empty": "replay",
    "replay-api-postbrowser": "replay-api",
    "unavailable-missing": "unavailable:not_installed", "unavailable-hash": "unavailable:unreviewed_build"}
assert set(STEP_MODES) == set(ALL_STEPS)
# Environment passed to every child process: nothing else (no OPENROUTER_* or other credentials) is inherited.
ENV_ALLOW = frozenset({"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TMPDIR", "TERM", "TZ",
                       "__CF_USER_TEXT_ENCODING"})
ATTEMPT_SUFFIX = re.compile(r"-(\d{8}T\d+)$")
STEP_TIMEOUT_S = 1800
TAMPERED_ENGINE = (b"#!/bin/sh\n# ProtView M12 QA labeled placeholder: NOT the reviewed fpocket 4.2.3 hb88c64c_2 build.\n"
                   b"# Exists only so the capability check reports unreviewed_build. Never produces results.\nexit 97\n")


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
    """Directory name -> (step, attempt order): the first attempt has no suffix, reruns carry a UTC timestamp."""
    found = ATTEMPT_SUFFIX.search(name)
    return (name[:found.start()], (1, found.group(1))) if found else (name, (0, ""))


def sanitize_text(text: str, replacements: list[tuple[str, str]]) -> str:
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def listening(port: int) -> list[str]:
    return subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
                          check=False).stdout.split()


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.root = Path(args.root).resolve()
        self.artifacts = Path(args.artifacts).resolve()
        self.only = set(filter(None, (args.only or "").split(",")))
        self.partial = bool(self.only)
        self.export = Path(args.export_evidence).resolve() if args.export_evidence else None
        unknown = self.only - set(ALL_STEPS)
        if unknown:
            raise SystemExit(f"unknown --only steps: {sorted(unknown)}; choose from {ALL_STEPS}")
        self.phases = [p for p in PHASES if p in set(args.phases.split(","))]
        if self.only:  # --only runs just the phases that own the named steps (plus the ledger if requested)
            self.phases = [p for p in self.phases if p == "ledger" or self.only & set(PHASE_STEPS[p])]
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        for bad in ("/tmp", "/private/tmp"):
            for path in (self.root, self.artifacts):
                if str(path) == bad or str(path).startswith(bad + "/"):
                    raise SystemExit("QA roots must not be under /tmp")
        ignored = subprocess.run(["git", "check-ignore", "-q", str(self.artifacts / "x")], cwd=REPO, check=False)
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
        """A rerun never overwrites an earlier attempt's evidence."""
        step_dir = self.artifacts / step
        if not step_dir.exists():
            return step_dir
        return self.artifacts / f"{step}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m12_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": sha_file(Path(__file__))}, "startedAt": row.get("startedAt", now()),
                "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

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
        probe = subprocess.run([str(REPO / ".venv/bin/python"), "-c", "import mw;print(mw.__file__)"],
                               env=env, cwd=code_root, capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(code_root / "backend")):
            raise RuntimeError(f"backend import resolved outside {code_root}: {probe.stdout}")
        runs_dir.mkdir(parents=True, exist_ok=True)
        log = self.artifacts / "services" / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(REPO / ".venv/bin/python"), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=code_root, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{API}/capabilities")
        self.state.setdefault("services", []).append({"name": name, "runs": str(runs_dir), "code": str(code_root),
                                                      "mw": probe.stdout.strip(), "startedAt": now()})
        self.save()

    def start_frontend(self) -> None:
        if not (FRONTEND / ".next/BUILD_ID").is_file():
            raise SystemExit("frontend is not built; run npm --prefix frontend run typecheck, then build")
        log = self.artifacts / "services" / "frontend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["frontend"] = subprocess.Popen(
            ["npm", "--prefix", str(FRONTEND), "run", "start", "--", "-p", "3000"], cwd=REPO,
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

    def get(self, path: str) -> bytes:
        with urllib.request.urlopen(API + path, timeout=120) as response:
            return response.read()

    def get_json(self, path: str):
        return json.loads(self.get(path))

    def pocket_capability(self) -> dict:
        return self.get_json("/capabilities")["methods"]["pocket_detection"]

    # ----- step execution ----------------------------------------------------------------------
    def node(self, step: str, script: str, args: list[str], evidence: str | None) -> tuple[int, Path, dict | None]:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(OFFSCREEN / script), "--url", WEB, *args, "--artifacts", str(step_dir)]
        log = step_dir.with_suffix(".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            try:
                rc = subprocess.run(argv, cwd=FRONTEND, env=child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    timeout=STEP_TIMEOUT_S, check=False).returncode
            except subprocess.TimeoutExpired:
                rc = -9
        data = None
        if evidence and (step_dir / evidence).exists():
            data = json.loads((step_dir / evidence).read_text())
        return rc, step_dir, data

    def pocket(self, step: str, mode: str, extra: list[str] | None = None) -> dict | None:
        rc, step_dir, evidence = self.node(step, "pocket-flow.cjs", ["--mode", mode, *(extra or [])],
                                           "pocket-evidence.json")
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        passed = rc == 0 and row is not None and row.get("status") == "pass"
        if row is None:
            self.write_row(step_dir, {"mode": mode, "evidenceKind": "real_electron_offscreen", "status": "fail",
                                      "error": f"harness exited {rc} without a ledger row"})
        self.record(step, "pass" if passed else "fail", exitCode=rc, artifacts=str(step_dir),
                    run=(evidence or {}).get("run"))
        return evidence if passed else None

    def m12_inputs(self) -> Path:
        out = self.root / "inputs" / "m12-invalid"
        if not (out / "m12-invalid-cases.json").exists():
            subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m12_qa_inputs.py"), "--out", str(out)],
                           env=child_env(), check=True, capture_output=True)
        return out

    def m11_inputs(self) -> Path:
        out = self.root / "inputs" / "m11"
        if not (out / "m11-synthetic-empty-1000A.sdf").exists():
            subprocess.run([str(REPO / ".venv/bin/python"), str(REPO / "scripts/m11_qa_inputs.py"), "--out", str(out)],
                           env=child_env(), check=True, capture_output=True)
        return out

    # ----- pocket modes ------------------------------------------------------------------------
    def run_pockets(self) -> None:
        state = self.state
        if self.wanted("positive"):
            ev = self.pocket("positive", "positive", ["--fixture", str(PUBLIC_1HSG)])
            if ev:
                state["positive"] = {"run": ev["run"], "set": ev["handles"]["set"],
                                     "prepared": ev["handles"]["prepared"], "original": ev["handles"]["original"]}
        if self.wanted("empty"):
            ev = self.pocket("empty", "empty", ["--fixture", str(DERIVED)])
            if ev:
                state["empty"] = {"run": ev["run"], "set": ev["handles"]["set"], "report": ev["handles"]["report"],
                                  "md": ev["report"]["md"], "json": ev["report"]["json"]}
        if self.wanted("invalid"):
            self.pocket("invalid", "invalid", ["--variants", str(self.m12_inputs())])
        if self.wanted("cancel"):
            self.pocket("cancel", "cancel", ["--fixture", str(PUBLIC_1HSG)])
        if self.wanted("minimized-source"):
            # OpenMM needs complete Amber templates; public 1HSG lacks terminal OXT, 1UBQ minimizes (M9 fixture).
            self.pocket("minimized-source", "minimized-source", ["--fixture", str(FIXTURES / "public_1ubq.cif")])
        self.save()
        positive = state.get("positive")
        if positive:
            existing = ["--run", positive["run"], "--set", positive["set"]]
            if self.wanted("reopen"):
                self.pocket("reopen", "reopen", existing)
            if self.wanted("report-download"):
                ev = self.pocket("report-download", "report-download", existing)
                if ev:
                    positive.update(report=ev["handles"]["report"], md=ev["report"]["md"], json=ev["report"]["json"])
            for step in ("overlay-disables", "distance-with-overlay", "comparison-block"):
                if self.wanted(step):
                    self.pocket(step, step, existing)
            if self.wanted("source-race"):
                if state.get("empty"):
                    self.pocket("source-race", "source-race", [*existing, "--other-run", state["empty"]["run"]])
                else:
                    self.record("source-race", "fail", reason="empty run unavailable (prerequisite failed)")
        else:
            for step in ("reopen", "report-download", "overlay-disables", "distance-with-overlay", "comparison-block",
                         "source-race"):
                if self.wanted(step):
                    self.record(step, "fail", reason="positive run unavailable (prerequisite failed)")
        self.save()
        if self.wanted("m11-create"):
            rc, step_dir, ev = self.node("m11-create", "chemical-flow.cjs",
                                         ["--mode", "create", "--receptor", str(PUBLIC_RECEPTOR), "--sdf",
                                          str(PUBLIC_SDF)], "chemical-evidence.json")
            ok = self.m11_row_status(step_dir, rc)
            self.record("m11-create", "pass" if ok else "fail", exitCode=rc, artifacts=str(step_dir),
                        run=(ev or {}).get("run"))
            if ok:
                state["chemical"] = {"run": ev["run"], "result": ev["resultHandle"]}
        if self.wanted("chemical-workspace"):
            chem = state.get("chemical")
            if chem:
                self.pocket("chemical-workspace", "chemical-workspace", ["--run", chem["run"], "--result", chem["result"]])
            else:
                self.record("chemical-workspace", "fail", reason="M11 chemical run unavailable (prerequisite failed)")
        self.save()

    def m11_row_status(self, step_dir: Path, rc: int) -> bool:
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        return rc == 0 and row is not None and row.get("status") == "pass"

    # ----- regressions -------------------------------------------------------------------------
    def regression(self, step: str, script: str, args: list[str], jsonl: str, cases: str) -> dict | None:
        started = now()
        rc, step_dir, _ = self.node(step, script, args, None)
        rows = []
        if (step_dir / jsonl).exists():
            rows = [json.loads(line) for line in (step_dir / jsonl).read_text().splitlines() if line.strip()]
        statuses = [row.get("status") for row in rows]
        # Measured, not inferred: every captured row carries the renderer's cumulative blocked-request list.
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
                                  "status": "pass" if passed else "fail", "exitCode": rc, "runId": run,
                                  "startedAt": started, "evidenceFile": jsonl,
                                  "statusCounts": {s: statuses.count(s) for s in set(statuses)},
                                  "harness": {"flowSha256": sha_file(OFFSCREEN / script),
                                              "runnerSha256": sha_file(Path(__file__))},
                                  "externalRequestCount": external,
                                  "externalRequestMeasurement": {"rowsWithStatus": len(measured), "rows": len(rows),
                                                                 "rule": "max(len(row.after.blockedRequests))"},
                                  "note": "Non-loopback requests measured from the renderer status captured with "
                                          "every step row (cumulative blocked-request list)."})
        self.record(step, "pass" if passed else "fail", exitCode=rc, run=run, artifacts=str(step_dir))
        return {"run": run} if passed else None

    def chemical_regression(self, step: str, args: list[str]) -> dict | None:
        rc, step_dir, ev = self.node(step, "chemical-flow.cjs", args, "chemical-evidence.json")
        ok = self.m11_row_status(step_dir, rc)
        self.record(step, "pass" if ok else "fail", exitCode=rc, artifacts=str(step_dir), run=(ev or {}).get("run"))
        return ev if ok else None

    def run_regressions(self) -> None:
        if self.wanted("regression-m8-normal"):
            self.regression("regression-m8-normal", "normal-flow.cjs", ["--fixture", str(PUBLIC_1HSG)],
                            "normal-flow.jsonl", "M8")
        # Original M9 QA order: scenes-core needs a run holding a completed OpenMM minimization.
        if self.wanted("regression-m9-openmm"):
            done = self.regression("regression-m9-openmm", "openmm-flow.cjs",
                                   ["--fixture", str(FIXTURES / "public_1ubq.cif"), "--mode", "full"],
                                   "openmm-full.jsonl", "M9 prerequisite (OpenMM run)")
            if done:
                self.state["scenesRun"] = done["run"]
        if self.wanted("regression-m9-scenes-core") and self.state.get("scenesRun"):
            self.regression("regression-m9-scenes-core", "scenes-flow.cjs", ["--run", self.state["scenesRun"],
                                                                             "--mode", "core"],
                            "scenes-core.jsonl", "M9")
        if self.wanted("regression-m10-measure"):
            self.regression("regression-m10-measure", "comparison-flow.cjs", ["--mode", "measure"],
                            "comparison-measure.jsonl", "M10")
        if self.wanted("regression-m10-alignment"):
            self.regression("regression-m10-alignment", "comparison-flow.cjs", ["--mode", "alignment"],
                            "comparison-alignment.jsonl", "M10")
        public = ["--receptor", str(PUBLIC_RECEPTOR), "--sdf", str(PUBLIC_SDF)]
        if self.wanted("regression-m11-capability-ready"):
            self.chemical_regression("regression-m11-capability-ready",
                                     ["--mode", "capability", "--expect-capability", "ready", *public])
        if self.wanted("regression-m11-empty"):
            empty = self.m11_inputs() / "m11-synthetic-empty-1000A.sdf"
            self.chemical_regression("regression-m11-empty", ["--mode", "empty", "--receptor", str(PUBLIC_RECEPTOR),
                                                              "--sdf", str(empty)])
        if self.wanted("regression-m11-prepare-only"):
            ev = self.chemical_regression("regression-m11-prepare-only", ["--mode", "prepare-only", *public])
            if ev:
                self.state["m11Prepared"] = {"run": ev["run"], "graph": ev["prepareOnly"]["graphHandle"]}
        if self.wanted("regression-m11-detect-controls") and self.state.get("m11Prepared"):
            prepared = self.state["m11Prepared"]
            self.chemical_regression("regression-m11-detect-controls", ["--mode", "detect-controls", "--run",
                                                                        prepared["run"], "--graph", prepared["graph"]])
        if self.wanted("regression-m11-job-controls"):
            self.chemical_regression("regression-m11-job-controls", ["--mode", "job-controls", *public])
        if self.wanted("regression-m11-running-cancel"):
            self.chemical_regression("regression-m11-running-cancel", ["--mode", "running-cancel", *public])
        if self.wanted("regression-m11-reopen") and self.state.get("chemical"):
            chem = self.state["chemical"]
            self.chemical_regression("regression-m11-reopen", ["--mode", "reopen", "--run", chem["run"],
                                                               "--result", chem["result"]])
        self.save()

    # ----- labeled layouts ---------------------------------------------------------------------
    def layout(self, name: str, tampered: bool) -> Path:
        """Byte-identical backend/mw + config copy; .deps/fpocket is absent or holds a labeled non-reviewed engine."""
        target = self.root / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(REPO / "backend/mw", target / "backend/mw", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "config", target / "config", ignore=shutil.ignore_patterns("__pycache__"))
        engine = None
        if tampered:
            record = REPO / ".deps/fpocket/install-record.json"
            if not record.is_file():
                raise RuntimeError("the real fpocket install record is required to build the tampered layout")
            root = target / ".deps/fpocket"
            (root / "env/bin").mkdir(parents=True)
            shutil.copyfile(record, root / "install-record.json")
            engine = root / "env/bin/fpocket"
            engine.write_bytes(TAMPERED_ENGINE)
            engine.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        source = {**{f"backend/mw/{k}": v for k, v in tree_digest(REPO / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(REPO / "config").items()}}
        copied = {**{f"backend/mw/{k}": v for k, v in tree_digest(target / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(target / "config").items()}}
        if source != copied:
            raise RuntimeError(f"{name}: copied backend/config differs from source")
        label = ("labeled runtime layout: byte-identical backend/mw and config copy; " +
                 ("real install record with a labeled placeholder bin/fpocket (SHA-256 "
                  f"{sha_bytes(TAMPERED_ENGINE)}, not the reviewed build)" if tampered else ".deps/fpocket absent"))
        manifest = {"label": label, "files": len(copied),
                    "treeSha256": sha_bytes(json.dumps(copied, sort_keys=True).encode()),
                    "engine": {"path": str(engine.relative_to(target)), "sha256": sha_file(engine)} if engine else None}
        (self.artifacts / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
        self.state.setdefault("layouts", {})[name] = manifest
        self.save()
        return target

    # ----- events-only replay ------------------------------------------------------------------
    def replay_targets(self) -> list[dict]:
        out = []
        for key in ("positive", "empty"):
            item = self.state.get(key)
            if item and item.get("report"):
                out.append({"key": key, **item})
        return out

    def api_snapshot(self, targets: list[dict]) -> dict:
        snap: dict = {}
        for item in targets:
            run, handle = item["run"], item["set"]
            q = urllib.parse.quote(handle, safe="")
            reads = {"list": f"/runs/{run}/pockets?offset=0&limit=100", "result": f"/runs/{run}/pockets/result?handle={q}"}
            summary = self.get_json(reads["result"])
            for pocket in summary["pockets"]:
                reads[f"geometry-{pocket['rank']}"] = f"/runs/{run}/pockets/geometry?handle={q}&rank={pocket['rank']}"
            rq = urllib.parse.quote(item["report"], safe="")
            reads["report-selected"] = f"/runs/{run}/reports/selected?handle={rq}"
            reads["report-md"] = f"/runs/{run}/reports/download?handle={rq}&format=markdown"
            reads["report-json"] = f"/runs/{run}/reports/download?handle={rq}&format=json"
            snap[item["key"]] = {name: sha_bytes(self.get(path)) for name, path in reads.items()}
        return snap

    def api_row(self, step: str, before: dict, after: dict | None, error: str | None) -> None:
        passed = error is None and after == before
        out = self.fresh_dir(step)
        out.mkdir(parents=True, exist_ok=True)
        (out / "replay-api.json").write_text(json.dumps({"baseline": before, "observed": after, "error": error},
                                                        indent=2) + "\n")
        self.write_row(out, {"mode": "replay-api", "evidenceKind": "direct_api", "status": "pass" if passed else "fail",
                             "runId": ",".join(t["run"] for t in self.replay_targets()),
                             "evidenceFile": "replay-api.json", "externalRequestCount": 0, "error": error,
                             "fixtureLabels": [self.state["layouts"]["layout-engine-missing"]["label"]],
                             "note": "GET-only loopback comparison (SHA-256 of each response body) of pocket list, "
                                     "result, every geometry rank and the saved report against the original root."})
        self.record(step, "pass" if passed else "fail", output=str(out))

    def run_replay(self) -> None:
        targets = self.replay_targets()
        if len(targets) < 2:
            self.record("replay", "fail", reason="positive/empty runs with saved reports unavailable")
            return
        for item in targets:
            jobs = self.get_json(f"/runs/{item['run']}/jobs")
            active = [job["job_id"] for job in jobs if job["status"] in {"running"}]
            if active:
                raise RuntimeError(f"replay run {item['run']} still has running jobs: {active}")
        before = self.api_snapshot(targets)
        (self.artifacts / "replay-before.json").write_text(json.dumps(before, indent=2) + "\n")
        self.stop("backend")
        replay_root = self.root / "replay-runs"
        inventory = []
        for item in targets:
            source = self.root / "runs" / item["run"] / "events.jsonl"
            target = replay_root / item["run"] / "events.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            inventory.append({"path": f"{item['run']}/events.jsonl", "bytes": target.stat().st_size,
                              "sha256": sha_file(target), "sourceSha256": sha_file(source)})
        withheld = self.root / "inputs.withheld-during-replay"
        inputs = self.root / "inputs"
        if inputs.exists():
            inputs.rename(withheld)
        (self.artifacts / "events-only-root-inventory.json").write_text(json.dumps({
            "recordedAt": now(), "replayRoot": str(replay_root), "eventsOnly": inventory,
            "entries": sorted(str(p.relative_to(replay_root)) for p in replay_root.rglob("*")),
            "originalInputsPathPresent": inputs.exists()}, indent=2) + "\n")
        try:
            layout = self.layout("layout-engine-missing", tampered=False)
            self.start_backend("backend-replay-engine-missing", replay_root, layout)
            cap = self.pocket_capability()
            if cap["available"] or cap["status"] != "not_installed":
                raise RuntimeError(f"replay backend engine is not absent: {cap}")
            label = self.state["layouts"]["layout-engine-missing"]["label"]
            try:
                self.api_row("replay-api-prebrowser", before, self.api_snapshot(targets), None)
            except (urllib.error.URLError, KeyError, ValueError) as exc:
                self.api_row("replay-api-prebrowser", before, None, repr(exc))
            for item in targets:
                step = f"replay-{item['key']}"
                if self.wanted(step):
                    self.pocket(step, "replay", ["--run", item["run"], "--set", item["set"], "--report", item["report"],
                                                 "--expect-markdown-sha", item["md"], "--expect-json-sha", item["json"],
                                                 "--expect-capability", "not_installed", "--fixture-label", label])
            try:
                self.api_row("replay-api-postbrowser", before, self.api_snapshot(targets), None)
            except (urllib.error.URLError, KeyError, ValueError) as exc:
                self.api_row("replay-api-postbrowser", before, None, repr(exc))
        finally:
            self.stop("backend")
            if withheld.exists():
                withheld.rename(inputs)
        self.save()

    # ----- unavailable displays -----------------------------------------------------------------
    def run_unavailable(self) -> None:
        for step, name, tampered, expected in (
                ("unavailable-missing", "layout-engine-missing", False, "not_installed"),
                ("unavailable-hash", "layout-engine-tampered", True, "unreviewed_build")):
            if not self.wanted(step):
                continue
            layout = self.layout(name, tampered)
            try:
                self.start_backend(f"backend-{step}", self.root / f"{step}-runs", layout)
                cap = self.pocket_capability()
                if cap["available"] or cap["status"] != expected:
                    self.record(step, "fail", reason=f"layout capability {cap.get('status')} != {expected}")
                    continue
                self.pocket(step, "unavailable", ["--fixture", str(PUBLIC_1HSG), "--expect-capability", expected,
                                                  "--fixture-label", self.state["layouts"][name]["label"]])
            finally:
                self.stop("backend")
        self.save()

    # ----- ledger ------------------------------------------------------------------------------
    def ledger(self, leftovers: list[str]) -> None:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            inputs = row.get("inputs") or [{"name": f.get("name"), "sha256": f.get("sha256"),
                                            "provenance": f.get("provenance")} for f in row.get("fixtures", [])]
            mode = row.get("mode")
            if mode == "unavailable" and row.get("expectCapability"):
                mode = f"unavailable:{row['expectCapability']}"
            rows.append({"step": row_file.parent.name, "mode": mode, "schema": row.get("schema"),
                         "evidenceKind": row.get("evidenceKind") or row.get("evidenceType"),
                         "status": row.get("status"), "runId": row.get("runId"), "handles": row.get("handles", {}),
                         "inputs": inputs, "provenanceLabels": row.get("provenanceLabels", []),
                         "fixtureLabels": row.get("fixtureLabels", []),
                         "externalRequestCount": row.get("externalRequestCount", row.get("nonLoopbackRequests")),
                         "regression": row.get("regression") or (row.get("cases") if row.get("schema") ==
                                                                  "m11_case_ledger_row@1" else None),
                         "error": row.get("error"), "artifacts": row.get("artifacts"),
                         "finishedAt": row.get("finishedAt")})
        # Each required step is judged by its latest attempt (reruns live in time-suffixed directories and every
        # earlier attempt, failing or not, stays listed in rows). A step with no row is missing, which fails.
        attempts: dict[str, list[tuple[tuple[int, str], dict]]] = {}
        for row in rows:
            base, order = step_base(row["step"])
            attempts.setdefault(base, []).append((order, row))
        required = sorted(self.only) if self.partial else ALL_STEPS
        steps: dict[str, dict] = {}
        for step in required:
            found = sorted(attempts.get(step, []), key=lambda item: item[0])
            if not found:
                steps[step] = {"status": "missing", "attempts": 0}
                continue
            latest = found[-1][1]
            expected_mode = STEP_MODES[step]
            problems = []
            if latest["status"] != "pass":
                problems.append(f"status {latest['status']}")
            if expected_mode is not None and latest["mode"] != expected_mode:
                problems.append(f"mode {latest['mode']!r} != {expected_mode!r}")
            if latest["externalRequestCount"] != 0:
                problems.append(f"externalRequestCount {latest['externalRequestCount']!r}")
            steps[step] = {"status": "fail" if problems else "pass", "attempts": len(found),
                           "latest": latest["step"], "mode": latest["mode"], "problems": problems}
        verdict_parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
                         "externalRequests": all(r["externalRequestCount"] == 0 for r in rows),
                         "leftoverProcesses": not leftovers}
        passed = all(verdict_parts.values())
        verdict = "partial_not_acceptance" if self.partial else "pass" if passed else "fail"
        ledger = {"schema": "m12_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": verdict, "acceptance": not self.partial and passed,
                  "scope": {"partial": self.partial, "only": sorted(self.only), "requiredSteps": required},
                  "verdictParts": verdict_parts, "steps": steps, "leftoverProcesses": leftovers,
                  "externalRequestsTotal": sum(r["externalRequestCount"] or 0 for r in rows),
                  "rowsWithUnknownExternalCount": [r["step"] for r in rows if r["externalRequestCount"] is None],
                  "rows": rows}
        name = "case-ledger-partial.json" if self.partial else "case-ledger.json"
        (self.artifacts / name).write_text(json.dumps(ledger, indent=2) + "\n")
        status = "fail" if not passed else "partial" if self.partial else "pass"
        self.record("case-ledger", status, verdict=verdict,
                    steps={step: value["status"] for step, value in steps.items()}, output=str(self.artifacts / name))

    def export_evidence(self) -> None:
        """Text evidence for docs/qa/: absolute paths become <repo>/<home>; binaries are listed by hash only."""
        assert self.export is not None
        replacements = [(str(REPO), "<repo>"), (str(Path.home()), "<home>")]
        self.export.mkdir(parents=True, exist_ok=True)
        sums, binaries = [], []
        for path in sorted(self.artifacts.rglob("*")):
            if not path.is_file() or "services" in path.relative_to(self.artifacts).parts:
                continue
            rel = path.relative_to(self.artifacts)
            if path.suffix in {".json", ".jsonl", ".log", ".md", ".txt"}:
                target = self.export / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(sanitize_text(path.read_text(errors="replace"), replacements))
                sums.append(f"{sha_file(target)}  {rel}")
            else:
                binaries.append({"path": str(rel), "bytes": path.stat().st_size, "sha256": sha_file(path)})
        (self.export / "binary-artifacts.json").write_text(sanitize_text(json.dumps({
            "note": "screenshots/paint frames/downloads stay in the git-ignored artifacts folder; hashes only",
            "artifacts": sanitize_text(str(self.artifacts), replacements), "files": binaries}, indent=2), replacements)
            + "\n")
        sums.append(f"{sha_file(self.export / 'binary-artifacts.json')}  binary-artifacts.json")
        (self.export / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        leaked = [str(p.relative_to(self.export)) for p in self.export.rglob("*") if p.is_file() and
                  any(old in p.read_text(errors="replace") for old, _ in replacements)]
        self.record("export-evidence", "fail" if leaked else "pass", output=str(self.export), leaked=leaked)

    def leftovers(self) -> list[str]:
        # Only processes working inside this acceptance root count: guardians and workers run with their
        # cwd in the job attempt folder under the runs root, while unrelated pytest runs (e.g. the Stop hook)
        # use the same scripts from their own temp folders. A short wait covers the guardian cleanup grace.
        workers = ("guardian.py", "chemical_worker.py", "openmm_worker.py", "pocket_worker.py", "fpocket")
        root = self.root.resolve()
        left: list[str] = []
        for _ in range(10):
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True,
                                check=False).stdout.splitlines()
            left = []
            for line in ps:
                pid, _, command = line.strip().partition(" ")
                if not any(w in command for w in workers):
                    continue
                cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True,
                                     text=True, check=False).stdout
                paths = [Path(item[1:]) for item in cwd.splitlines() if item.startswith("n")]
                # A worker whose working directory cannot be read is counted: fail closed, not open.
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
        if "pockets" in self.phases and not self.only and runs.exists() and any(runs.iterdir()):
            raise SystemExit(f"runs root {runs} is not fresh; choose a new --root")
        needs_services = [p for p in self.phases if p != "ledger"]
        if needs_services:
            busy = {port: listening(port) for port in (8000, 3000)}
            if any(busy.values()):
                raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              check=False).stdout.strip()
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True,
                                   check=False).stdout
        build_id = FRONTEND / ".next/BUILD_ID"
        self.state["build"] = {"buildId": build_id.read_text().strip() if build_id.exists() else None,
                               "gitHead": head, "gitStatusPorcelainSha256": sha_bytes(porcelain.encode()),
                               "dirtyFiles": porcelain.splitlines(), "recordedAt": now(),
                               "harnessSha256": {name: sha_file(OFFSCREEN / name) for name in (
                                   "pocket-flow.cjs", "driver.cjs", "main.cjs", "chemical-flow.cjs", "m11-ledger.cjs",
                                   "normal-flow.cjs", "openmm-flow.cjs", "scenes-flow.cjs", "comparison-flow.cjs")},
                               "inputSha256": {p.name: sha_file(p) for p in (PUBLIC_1HSG, DERIVED, PUBLIC_RECEPTOR,
                                                                              PUBLIC_SDF)},
                               "runnerSha256": sha_file(Path(__file__)),
                               "qaInputsSha256": sha_file(REPO / "scripts/m12_qa_inputs.py")}
        self.save()
        try:
            if needs_services:
                self.start_frontend()
            if {"pockets", "regressions", "replay"} & set(self.phases):
                self.start_backend("backend-main", runs, REPO)
            if "pockets" in self.phases:
                self.run_pockets()
            if "regressions" in self.phases:
                self.run_regressions()
            if "replay" in self.phases:
                self.run_replay()
            self.stop("backend")
            if "unavailable" in self.phases:
                self.run_unavailable()
        finally:
            for name in list(self.services):
                self.stop(name)
            self.save()
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        if "ledger" in self.phases:
            self.ledger(left)
        if self.export:
            self.export_evidence()
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "artifacts": str(self.artifacts)}), flush=True)
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (runs/, replay-runs/, inputs/, layouts); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m12-acceptance/<label>")
    parser.add_argument("--phases", default=",".join(PHASES), help=f"comma list of {PHASES}")
    parser.add_argument("--only", help=f"comma list of steps to (re)run: {ALL_STEPS}; the ledger is then "
                        "partial_not_acceptance")
    parser.add_argument("--export-evidence", help="write sanitized text evidence (<repo> paths) + SHA256SUMS here")
    return Runner(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
