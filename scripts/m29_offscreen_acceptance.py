#!/usr/bin/env python3
"""Run the M29 structure repair acceptance (.dryforge/spec.md 10; plan T11): phase ``fixture`` only.

One command from the main checkout (where .deps and frontend/node_modules are), 8000/3000 free. The runner builds the
frontend when needed (typecheck, then build, never concurrently), starts its own loopback services (``next start`` on
127.0.0.1:3000; the M25 fixture server ``backend/tests/offscreen_jev_loop_fixture/server.py`` on 127.0.0.1:8000: the
product app with only the egress gates over a scripted MockTransport and no credential read, so no JEV call can leave;
no script is written, so even a send would fail as a transport error) with ``MW_RUNS_DIR=<root>/runs``, a read-only copy
of the M15 reference set (``--m15-reference``) and empty isolated precedent / reaction reference folders, then runs, in
this order (``STEPS``):

  r1     harness ``frontend/tests/offscreen/structure-repair-flow.cjs --mode r1`` (8VF6, UI)          -> R1
  r3     the original 8VF6's numbering map, annotation, fpocket set and a comparison M20 set (API), then the harness
         ``--mode r3`` on the same run (M20 hand-off, JEV preview/approval without a send, M23 option, viewer
         selects)                                                                                    -> R3, R10, R6 (UI)
  r4a    harness ``--mode r4a`` (1HSG: repair, M20, M21 240 s, reports, phenol same-condition docking) -> R4a
  table  every structure x water policy through the API (``m29_api_cases.Lab.table``)                -> R5, R2
  r8     harness ``--mode r8`` on the repaired 1RNH run                                               -> R8
  r7     the admission refusals (1UBQ, 1S9I, already_repaired, the five LABELLED SYNTHETIC files)     -> R7
  r6     every spec 5.2 consumer with the repaired 1HSG (API)                                          -> R6
  r4b    one M21 job on the repaired 8VF6 with timeout_s 240 (the documented time limit)              -> R4b
  pytest the named backend tests as subprocesses (R6 inventory and refusals, R9 baseline reads / reports, R10 M23)
         and the 27 call-key hash files against ``BASELINE_BLOBS`` (read with ``ast``)
  r9     the services stop; a second fixture server on ``<root>/reopen`` holding ONLY the events.jsonl of the R1 run,
         of ``backend/tests/fixtures/mutation_report_v1`` (stored M20 @1) and of the M28 fixture runs
         (``--saved-report-runs``: stored M20 @2 and M21 @1) re-reads the repair record, structure and reports
         -> R9
  R11 is judged over the harness screen texts and the new report text.

Expectations come from ``scripts/m29_oracle.py`` (input files + the installed template) and the documents in
``scripts/m29_common.py``; never from a product answer. Every case is pass | fail | not_observed (+ closed reason);
only pass counts and a case that did not run is not_observed (never pass). ``acceptance`` is true only when every case
of ``m29_common.CASES`` passed, every gate held (fresh build stamp, browser non-loopback requests 0, provider calls 0,
dispatch events 0, nothing left, default reference folders absent before and after, the product's fixed sentences
exported, the evidence searches clean), the whole step list ran and this is not ``--rehearse``.

This runner never imports ``mw`` (the product constants come from the subprocess ``m29_export_fixed_sentences.py``),
never calls a limit-raising route and never sends to a ``/jev`` / ``/jev_loops`` write route (``m29_common.Api``
refuses them); the confirmations, approvals and starts of the UI cases are the harness's real clicks.

Evidence: --out (text only, decision 0020; default ``docs/qa/m29-repair-<YYYYMMDD>/acceptance``, with --rehearse
``<root>/out-rehearsal``): README.md, summary.json, cases.json, classification-table.{json,md}, evidence/ (runner
evidence, harness rows and step logs, redacted), binary-artifacts.json (path, size, SHA-256 of screenshots, paint
frames, downloads, screen texts, text above 256 KiB), SHA256SUMS. --artifacts and --root are git-ignored, new, never
under /tmp.

Usage (main checkout root, 8000/3000 free):
  .venv/bin/python scripts/m29_offscreen_acceptance.py --root runs/m29-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m29-repair/<label> [--out docs/qa/m29-repair-<date>/acceptance] \\
      [--rehearse] [--only r1,r3,...] [--structures 1hsg,8vf6,...] [--m15-reference .deps/reference] \\
      [--saved-report-runs runs/m28-fixture-20261012/fixture] [--build auto|always|never] [--code-root <dir>]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m13_offscreen_acceptance as m13  # build stamp, env allowlist, ports, hashes, path redaction
import m15_offscreen_acceptance as m15  # Runner: bookkeeping, build, service start / stop
import m25_offscreen_acceptance as m25  # harness watch (dispatch events), process groups, fixture server record
import m29_api_cases as cases
import m29_common as c
import m29_oracle as oracle

REPO = Path(__file__).resolve().parents[1]
FLOW = "structure-repair-flow.cjs"
STEPS = ("r1", "r3", "r4a", "table", "r8", "r7", "r6", "r4b", "pytest", "r9")
STEP_NEEDS = {"r3": ("r1",), "r8": ("table",), "r6": ("table",), "r4b": ("table",), "r9": ("r1",)}
STEP_TIMEOUT_S = 3600
EXPORTER = Path("scripts/m29_export_fixed_sentences.py")
FIXTURE_SERVER = m25.FIXTURE_SERVER
DEFAULT_FOLDERS = (Path(".deps/precedent_reference"), Path(".deps/reaction_reference"))
WORKERS = (*m25.WORKERS, "structure_repair_worker.py", "sequence_model_worker.py", "tests/offscreen/main.cjs")
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt"}
MAX_TEXT_BYTES = 256 * 1024
OUT_MARKER = ".m29-export"
PHENOL = c.FIXTURES / "mutation_model/synthetic-phenol-ligand.sdf"
DOCKING = {"margin": "8", "seed": "20261004", "exhaustiveness": "4", "numModes": "5", "energyRange": "3"}
SAVED_V1 = c.FIXTURES / "mutation_report_v1/v1-cited-reports.events.jsonl"
SAVED_V1_RUN = "run_m28_t3_v1_cited"
# The stored @1 reports of the M28 T3 fixture and their Markdown SHA-256 as its SYNTHETIC-PROVENANCE.md records them.
SAVED_V1_DIGESTS = {"174d26820b23": "a2ddcba8ef9f30a32525d85b47194f6536f38924ba5841ad8761c28881908a1d",
                    "c36fa4ca4330": "55cadf549ace58bc477ba8d9babcd8db2376149101f42ba8eaf1c4b77c6cda75"}
SAVED_RENDERS = ("mutation_candidates_markdown@1", "mutation_candidates_markdown@2", "mutation_model_markdown@1")
PYTEST = {
    "R6": ["backend/tests/test_structure_repair_consumers.py", "backend/tests/test_structure_repair_refusals.py"],
    "R9": ["backend/tests/test_structure_repair_downstream_reads.py",
           "backend/tests/test_structure_repair_reports_downstream.py"],
    "R10": [("backend/tests/test_structure_repair_downstream_reads.py::"
             "test_the_m23_read_and_report_hash_files_are_unchanged")],
}
BLOB_SOURCE = Path("backend/tests/test_kinase_precedents_ast.py")
M23_FILES = ("backend/mw/sequence_ga_reports.py", "backend/mw/sequence_ga_reads.py")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def under_tmp(path: Path) -> bool:
    text = str(Path(path).resolve())
    return any(text == bad or text.startswith(bad + "/") for bad in ("/tmp", "/private/tmp"))


def steps_arg(text: str) -> list[str]:
    names = [part.strip() for part in text.split(",") if part.strip()]
    if not names or any(name not in STEPS for name in names):
        raise argparse.ArgumentTypeError(f"--only takes steps of {','.join(STEPS)} (got {text!r})")
    return [name for name in STEPS if name in names]


def structures_arg(text: str) -> list[str]:
    names = [part.strip().lower() for part in text.split(",") if part.strip()]
    if not names or any(name not in c.STRUCTURES for name in names):
        raise argparse.ArgumentTypeError(f"--structures takes names of {','.join(c.STRUCTURES)} (got {text!r})")
    return [name for name in c.STRUCTURES if name in names]


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(raw) + raw).hexdigest()


def baseline_blobs(code: Path) -> dict[str, str]:
    """``BASELINE_BLOBS`` of the M27 test, read with ``ast`` (never imported)."""
    tree = ast.parse((code / BLOB_SOURCE).read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "BASELINE_BLOBS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("BASELINE_BLOBS not found")


def blob_check(code: Path) -> dict:
    baseline = baseline_blobs(code)
    current = {rel: git_blob((code / rel).read_bytes()) for rel in baseline}
    changed = sorted(rel for rel in baseline if current[rel] != baseline[rel])
    m23 = {rel: current[rel] == baseline[rel] for rel in M23_FILES}
    return {"ok": not changed and len(baseline) == 27 and all(m23.values()), "files": len(baseline),
            "changed": changed, "m23ReportFiles": m23}


def pytest_summary(output: str) -> str:
    lines = [line.strip("= ").strip() for line in output.splitlines() if line.strip()]
    return next((line for line in reversed(lines) if " in " in line and ("passed" in line or "failed" in line
                                                                       or "error" in line)), lines[-1] if lines else "")


class Runner(m15.Runner):
    """The M15 bookkeeping, build and service helpers with the M29 folders, steps, cases and evidence."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.code = Path(args.code_root).resolve()
        self.frontend = self.code / "frontend"
        self.offscreen = self.frontend / "tests/offscreen"
        venv = self.code / ".venv/bin/python"
        self.python = venv if venv.exists() else Path(sys.executable)
        self.root = Path(args.root).resolve()
        self.artifacts = Path(args.artifacts).resolve()
        self.rehearse = bool(args.rehearse)
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        if args.out:
            self.out = Path(args.out).resolve()
        elif self.rehearse:
            self.out = self.root / "out-rehearsal"
        else:
            self.out = self.code / "docs/qa" / f"m29-repair-{stamp}" / "acceptance"
        for path in (self.root, self.artifacts, self.out):
            if under_tmp(path):
                raise SystemExit("QA roots and evidence folders must not be under /tmp")
        if self.root in (self.code / "runs", REPO / "runs"):
            raise SystemExit("--root must be a new folder, not the repository runs/ folder itself")
        if self.root.exists() and (not self.root.is_dir() or any(self.root.iterdir())):
            raise SystemExit(f"{self.root} is not new; choose a new --root")
        for path, name in ((self.root, "--root"), (self.artifacts, "--artifacts")):
            if subprocess.run(["git", "check-ignore", "-q", str(path / "x")], cwd=self.code,
                              check=False).returncode != 0:
                raise SystemExit(f"{name} must be git-ignored: {path}")
        if self.artifacts.exists() and any(self.artifacts.iterdir()):
            raise SystemExit(f"{self.artifacts} is not empty; choose a new --artifacts")
        if self.out.exists() and any(self.out.iterdir()):
            raise SystemExit(f"{self.out} is not empty; choose a new --out (the runner writes a new folder)")
        self.only = list(args.only) if args.only else list(STEPS)
        self.structures = list(args.structures) if args.structures else list(c.STRUCTURES)
        self.subset = self.only != list(STEPS) or self.structures != list(c.STRUCTURES)
        if self.subset and not self.rehearse:
            raise SystemExit("--only / --structures are for a rehearsal (--rehearse): the acceptance runs every step")
        self.m15_source = self.resolve(args.m15_reference)
        if not (self.m15_source / "active.json").is_file():
            raise SystemExit(f"--m15-reference has no active.json: {self.m15_source}")
        self.saved_runs = self.resolve(args.saved_report_runs)
        self.build_mode = args.build
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        self.runs, self.reference = self.root / "runs", self.root / "reference"
        self.precedent, self.reaction = self.root / "precedent_reference", self.root / "reaction_reference"
        self.control = self.root / "fixture-control"
        self.api = c.Api()
        self.rows: dict[str, dict | None] = {}
        self.records: dict[str, dict] = {}
        self.evidence: dict[str, Any] = {}
        self.fixed: dict | None = None
        self.flow_rows: list[dict] = []
        self.lab: cases.Lab | None = None
        self.done: set[str] = set()
        self.external: dict = {}

    def resolve(self, value: str) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else self.code / path).resolve()

    # ----- bookkeeping ---------------------------------------------------------------------------------------------
    def write(self, name: str, value: Any) -> str:
        path = self.artifacts / "evidence" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
        return f"evidence/{name}"

    def default_folders(self) -> dict[str, bool]:
        return {str(rel): (self.code / rel).exists() for rel in DEFAULT_FOLDERS}

    def ready(self, step: str) -> bool:
        if step not in self.only:
            return False
        missing = [need for need in STEP_NEEDS.get(step, ()) if need not in self.done]
        if missing:
            self.record(f"step-{step}", "fail", reason=f"prerequisite step not done: {missing}")
            return False
        return True

    # ----- services ----------------------------------------------------------------------------------------------
    def prepare_folders(self) -> None:
        for folder in (self.runs, self.precedent, self.reaction, self.control):
            folder.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.m15_source, self.reference, symlinks=False)
        for path in self.reference.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        self.state["m15"] = {"setHash": json.loads((self.reference / "active.json").read_text())["set_hash"],
                             "files": sum(1 for p in self.reference.rglob("*") if p.is_file())}

    def backend_env(self, runs: Path, reaction: Path) -> dict[str, str]:
        return m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(runs),
                              "MW_REFERENCE_DIR": str(self.reference), "MW_PRECEDENT_REFERENCE_DIR": str(self.precedent),
                              "MW_REACTION_REFERENCE_DIR": str(reaction)})

    def start_fixture_backend(self, runs: Path, control: Path, reaction: Path, label: str) -> bool:
        control.mkdir(parents=True, exist_ok=True)
        env = self.backend_env(runs, reaction)
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=self.code,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(self.code / "backend")):
            raise RuntimeError(f"backend import resolved outside {self.code}: {probe.stdout}")
        log = self.artifacts / "services" / f"backend-{label}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen([str(self.python), str(self.code / FIXTURE_SERVER), "--port", "8000", "--runs-dir",
                                 str(runs), "--control", str(control)], cwd=self.code, env=env, stdout=log.open("a"),
                                stderr=subprocess.STDOUT, start_new_session=True)
        self.services["backend"] = proc
        self.wait_http(f"{c.API}/capabilities")
        try:
            server = json.loads((control / "server.json").read_text())
        except (OSError, ValueError):
            server = {}
        started = m25.fixture_server_started(server, proc.pid, m13.listening(8000), runs)
        self.state.setdefault("services", []).append({"name": f"fixture-backend-{label}", "pid": proc.pid,
                                                      "started": started, "startedAt": now()})
        self.save()
        self.record(f"backend-{label}", "pass" if started else "fail", pid=proc.pid)
        return started

    def stop_backend(self) -> None:
        proc = self.services.pop("backend", None)
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=30)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)

    def leftovers(self) -> list[str]:
        """Workers (guardian, repair / model / docking workers, fpocket, qvina2, the fixture server, the harness's
        Electron) whose command or working directory is inside the root, and 8000/3000 listeners."""
        root = self.root.resolve()
        left: list[str] = []
        for _ in range(10):
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
            left = []
            for line in ps.splitlines():
                pid, _, command = line.strip().partition(" ")
                if "tests/offscreen/main.cjs" in command and str(self.offscreen) in command:
                    left.append(line.strip())
                    continue
                if not any(worker in command for worker in WORKERS):
                    continue
                cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True,
                                     check=False).stdout
                paths = [Path(item[1:]) for item in cwd.splitlines() if item.startswith("n")]
                if str(root) in command or str(self.artifacts) in command or any(
                        path == root or root in path.parents for path in paths):
                    left.append(line.strip())
            if not left:
                break
            time.sleep(0.5)
        return left

    def worker_leftovers(self) -> list[str]:
        """While the backend runs: worker processes only (the fixture server itself names the root)."""
        return [line for line in self.leftovers() if "offscreen_jev_loop_fixture/server.py" not in line]

    # ----- fixed sentences (subprocess; this runner never imports mw) ----------------------------------------------
    def export_fixed_sentences(self) -> dict | None:
        target = self.artifacts / "evidence" / "fixed-sentences.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend")})
        done = subprocess.run([str(self.python), str(self.code / EXPORTER), "--out", str(target)], cwd=self.code,
                              env=env, capture_output=True, text=True, timeout=300, check=False)
        ok = done.returncode == 0 and target.is_file()
        self.record("fixed-sentences", "pass" if ok else "fail", exitCode=done.returncode)
        self.fixed = json.loads(target.read_text()) if ok else None
        return self.fixed

    # ----- harness steps ------------------------------------------------------------------------------------------
    def flow(self, step: str, plan: dict) -> dict | None:
        """One harness step; it and the backend are stopped at once if a dispatch event appears (limit 0)."""
        step_dir = self.artifacts / "steps" / step
        step_dir.mkdir(parents=True, exist_ok=True)
        plan_file = self.artifacts / "plans" / f"{step}.json"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text(json.dumps({"schema": "m29_plan@1", **plan}, indent=2) + "\n")
        argv = ["node", str(self.offscreen / FLOW), "--url", c.WEB, "--mode", plan["mode"], "--artifacts",
                str(step_dir), "--plan", str(plan_file), "--runs-dir", str(self.runs)]
        log = step_dir.with_suffix(".log")
        with log.open("w") as out:
            out.write(json.dumps({"argv": argv, "startedAt": now()}) + "\n")
            out.flush()
            proc = subprocess.Popen(argv, cwd=self.frontend, env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            rc, exceeded = m25.watch_process(proc, self.runs, 0, STEP_TIMEOUT_S)
        if exceeded is not None:
            self.stop_backend()
            self.state["dispatchSeen"] = {"step": step, "counts": exceeded}
            self.record("dispatch-guard", "fail", step=step, counts=exceeded)
        row_file = step_dir / "ledger-row.json"
        row = json.loads(row_file.read_text()) if row_file.exists() else None
        if row is None:
            row = {"schema": "m29_harness_row@1", "mode": plan["mode"], "status": "fail", "parts": {}, "observed": {},
                   "externalRequestCount": None, "error": f"harness exited {rc} without a ledger row"}
        self.flow_rows.append({"step": step, "status": row.get("status"), "exitCode": rc,
                               "externalRequestCount": row.get("externalRequestCount"),
                               "dispatchedDuringFlow": row.get("dispatchedDuringFlow"),
                               "dispatchGuard": exceeded is not None, "parts": row.get("parts")})
        self.record(f"harness-{step}", "pass" if rc == 0 and row.get("status") == "pass" else "fail", exitCode=rc,
                    parts=row.get("parts"))
        self.rows[step] = row
        return row

    def input_ref(self, name: str) -> dict:
        path = self.code / c.FIXTURES / f"public_{name}.cif"
        return {"path": str(path), "sha256": c.sha256(path.read_bytes())}

    # ----- steps ----------------------------------------------------------------------------------------------------
    def step_r1(self) -> None:
        row = self.flow("r1", {"mode": "r1", "run": None, "input": self.input_ref("8vf6"), "waters": "strip_all"})
        record, facts = cases.r1_case(self.lab, row)
        self.records["R1"] = record
        self.evidence["r1"] = facts
        self.write("r1.json", facts)
        if ((row or {}).get("observed") or {}).get("r1", {}).get("record"):
            self.done.add("r1")

    def step_r3(self) -> None:
        r1 = self.rows["r1"]["observed"]["r1"]
        try:
            setup = cases.r3_setup(self.lab, r1["run"], r1["prepared"])
        except Exception as exc:  # noqa: BLE001 - recorded; R3 then fails on the missing setup
            self.record("r3-setup", "fail", error=f"{type(exc).__name__}: {exc}")
            setup = None
        self.evidence["r3Setup"] = setup
        self.write("r3-setup.json", setup)
        row = None
        if setup is not None:
            plan = {"mode": "r3", "run": r1["run"], "r3": {**setup, "record": r1["record"], "repaired": r1["repaired"],
                                                         "prepared": r1["prepared"]}}
            row = self.flow("r3", plan)
        record, facts = cases.r3_case(self.lab, row, setup)
        self.records["R3"] = record
        self.evidence["r3"] = facts
        self.write("r3.json", facts)
        self.done.add("r3")

    def step_r4a(self) -> None:
        found = self.lab.oracle("1hsg", "strip_all")
        residue = oracle.mutable_residue(found)
        phenol = self.code / PHENOL
        plan = {"mode": "r4a", "run": None, "input": self.input_ref("1hsg"), "waters": "strip_all",
                "r4a": {"residue": residue, "allowed": "A", "model": {"seed": "1", "cutoff": "4.0",
                                                                     "timeout": str(c.M21_TIMEOUT_S)},
                        "docking": DOCKING},
                "phenol": {"path": str(phenol), "sha256": c.sha256(phenol.read_bytes()),
                           "label": "SYNTHETIC-FIXTURE hand-built phenol (mutation_model/SYNTHETIC-PROVENANCE.md)"}}
        row = self.flow("r4a", plan)
        record, facts = cases.r4a_case(self.lab, row)
        self.records["R4a"] = record
        self.evidence["r4a"] = facts
        self.write("r4a.json", facts)
        self.done.add("r4a")

    def step_table(self) -> None:
        rows = self.lab.table(tuple(self.structures))
        self.evidence["table"] = rows
        self.write("classification-table.json", rows)
        self.records["R5"] = cases.r5_case(rows, tuple(self.structures))
        self.records["R2"] = cases.r2_case(self.lab)
        self.done.add("table")

    def step_r8(self) -> None:
        row = self.lab.rows.get(("1rnh", "strip_all"))
        ui = None
        if row and row.get("record"):
            ui = self.flow("r8", {"mode": "r8", "run": row["run"], "r8": {"record": row["record"],
                                                                         "rp5": c.FIXED["RP5"]}})
        self.records["R8"] = cases.r8_case(self.lab, ui)
        self.done.add("r8")

    def step_r7(self) -> None:
        r1 = ((self.rows.get("r1") or {}).get("observed") or {}).get("r1") or {}
        repaired = (r1["run"], r1["repaired"]) if r1.get("repaired") else next(
            ((row["run"], row["repaired"]) for row in self.lab.rows.values() if row.get("repaired")), None)
        self.records["R7"] = cases.r7_case(self.lab, repaired)
        self.write("r7.json", self.records["R7"])
        self.done.add("r7")

    def step_r6(self) -> None:
        self.evidence["r6Api"] = cases.r6_api(self.lab)
        self.write("r6.json", self.evidence["r6Api"])
        self.done.add("r6")

    def step_r4b(self) -> None:
        record, facts = cases.r4b_case(self.lab, self.worker_leftovers)
        self.records["R4b"] = record
        self.write("r4b.json", facts)
        self.done.add("r4b")

    def step_pytest(self) -> None:
        out: dict[str, list[dict]] = {}
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend")})
        for case, targets in PYTEST.items():
            base = self.root / "pytest-tmp" / case
            started = time.monotonic()
            done = subprocess.run([str(self.python), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs",
                                   f"--basetemp={base}", *targets], cwd=self.code, env=env, capture_output=True,
                                  text=True, timeout=3600, check=False)
            text = done.stdout + done.stderr
            log = self.artifacts / "pytest" / f"{case}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(text)
            summary = pytest_summary(text)
            ok = done.returncode == 0 and "passed" in summary and "skipped" not in summary and "failed" not in summary
            out[case] = [{"name": ",".join(Path(t.split("::")[0]).name for t in targets), "ok": ok,
                          "summary": summary, "exitCode": done.returncode,
                          "seconds": round(time.monotonic() - started, 1)}]
            self.record(f"pytest-{case}", "pass" if ok else "fail", summary=summary)
        self.evidence["pytest"] = out
        self.evidence["blobs"] = blob_check(self.code)
        self.write("pytest.json", {"pytest": out, "blobs": self.evidence["blobs"]})
        self.done.add("pytest")

    # ----- R9 ------------------------------------------------------------------------------------------------------
    def r9_before(self) -> dict | None:
        r1 = ((self.rows.get("r1") or {}).get("observed") or {}).get("r1") or {}
        if not r1.get("record"):
            return None
        reports = [handle for handle in ((r1.get("report") or {}).get("handle"),
                                         ((self.rows.get("r3") or {}).get("observed") or {}).get("r3", {}).get("report"))
                   if handle]
        self.evidence["r9Reports"] = reports
        return cases.reopen_reads(self.api, r1["run"], r1["record"], reports)

    def step_r9(self, before: dict | None) -> None:
        reopen = self.root / "reopen"
        runs = reopen / "runs"
        runs.mkdir(parents=True)
        r1 = ((self.rows.get("r1") or {}).get("observed") or {}).get("r1") or {}
        copies = {r1["run"]: self.runs / r1["run"] / "events.jsonl"} if r1.get("run") else {}
        copies[SAVED_V1_RUN] = self.code / SAVED_V1
        missing_fixture = False
        saved_runs = self.saved_runs / "runs"
        m28 = []
        if saved_runs.is_dir():
            for folder in sorted(saved_runs.glob("run_*")):
                events = c.read_events(saved_runs, folder.name)
                if any(item["render"] in SAVED_RENDERS[1:] for item in cases.stored_reports(events)):
                    copies[folder.name] = folder / "events.jsonl"
                    m28.append(folder.name)
        if not m28:
            missing_fixture = True
        for rid, source in copies.items():
            (runs / rid).mkdir()
            shutil.copyfile(source, runs / rid / "events.jsonl")
        reaction = reopen / "reaction_reference"
        if (self.saved_runs / "reaction_reference").is_dir():
            shutil.copytree(self.saved_runs / "reaction_reference", reaction, symlinks=False)
            for path in reaction.rglob("*"):
                if path.is_file():
                    path.chmod(0o444)
        else:
            reaction.mkdir()
        after, saved = None, []
        try:
            if self.start_fixture_backend(runs, reopen / "fixture-control", reaction, "reopen"):
                if before is not None:
                    after = cases.reopen_reads(self.api, r1["run"], r1["record"], self.evidence.get("r9Reports") or [])
                saved = self.saved_report_checks(runs, [SAVED_V1_RUN, *m28])
        finally:
            self.stop_backend()
        calls = reopen / "fixture-control" / "calls.jsonl"
        self.external["reopenProviderCalls"] = len(calls.read_text().splitlines()) if calls.is_file() else 0
        self.evidence["r9"] = {"copiedRuns": sorted(copies), "m28Runs": m28, "saved": saved,
                               "differs": sorted(k for k in (before or {}) if (before or {}).get(k) != (after or {}).get(k))}
        self.write("r9.json", self.evidence["r9"])
        self.records["R9"] = cases.r9_case(before, after, saved, (self.evidence.get("pytest") or {}).get("R9", []),
                                           missing_fixture)
        self.done.add("r9")

    def saved_report_checks(self, runs: Path, rids: list[str]) -> list[dict]:
        out = []
        for rid in rids:
            for item in cases.stored_reports(c.read_events(runs, rid)):
                if item["render"] not in SAVED_RENDERS:
                    continue
                status, body = self.api.get(f"/runs/{rid}/reports/selected?handle={c.enc(item['handle'])}")
                markdown = (body or {}).get("markdown") if isinstance(body, dict) else None
                manifest = (body or {}).get("manifest") if isinstance(body, dict) else None
                digest = SAVED_V1_DIGESTS.get(item["handle"][-12:]) if rid == SAVED_V1_RUN else None
                ok = (status == 200 and markdown == item["markdown"] and manifest == item["manifest"]
                      and (digest is None or c.sha256(markdown.encode()) == digest))
                out.append({"run": rid, "handle": item["handle"], "render": item["render"], "ok": ok,
                            "why": f"HTTP {status}, markdown same {markdown == item['markdown']}, manifest same "
                                   f"{manifest == item['manifest']}, documented digest {digest is not None}"})
        return out

    # ----- the phase ----------------------------------------------------------------------------------------------
    def run(self) -> int:
        busy = {port: m13.listening(port) for port in (8000, 3000)}
        if any(busy.values()):
            raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
        self.artifacts.mkdir(parents=True, exist_ok=True)
        folders_before = self.default_folders()
        self.state["defaultFoldersBefore"] = folders_before
        self.build()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.code, capture_output=True, text=True,
                              check=False).stdout.strip()
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=self.code, capture_output=True, text=True,
                                   check=False).stdout
        build_id = self.frontend / ".next/BUILD_ID"
        self.state["build"] = {"buildId": build_id.read_text().strip() if build_id.exists() else None, "gitHead": head,
                               "buildCurrentWithSource": m13.build_is_current(self.frontend),
                               "dirtyFiles": porcelain.splitlines(), "recordedAt": now(),
                               "runnerSha256": m13.sha_file(Path(__file__)),
                               "harnessSha256": m13.sha_file(self.offscreen / FLOW)}
        self.save()
        self.export_fixed_sentences()
        self.prepare_folders()
        before_r9 = None
        try:
            self.start_frontend()
            if self.start_fixture_backend(self.runs, self.control, self.reaction, "main"):
                self.lab = cases.Lab(self.api, self.runs, self.code, self.record)
                for step in ("r1", "r3", "r4a", "table", "r8", "r7", "r6", "r4b"):
                    if self.ready(step):
                        self.guarded(step, getattr(self, f"step_{step}"))
                before_r9 = self.guarded("r9-before", self.r9_before) if "r9" in self.only else None
                self.external = self.external_counts()
        finally:
            self.stop_all()
            self.save()
        if self.ready("pytest"):
            self.guarded("pytest", self.step_pytest)
        if self.ready("r9") and self.lab is not None:
            self.guarded("r9", lambda: self.step_r9(before_r9))
        return self.finish(folders_before)

    def guarded(self, step: str, work):
        try:
            return work()
        except Exception as exc:  # noqa: BLE001 - a crashing step is recorded; its cases stay unreported
            self.record(f"step-{step}", "fail", error=f"{type(exc).__name__}: {str(exc)[:600]}")
            return None

    def external_counts(self) -> dict:
        calls_file = self.control / "calls.jsonl"
        calls = [line for line in calls_file.read_text().splitlines() if line] if calls_file.is_file() else []
        reads_file = self.control / "credentials.json"
        reads = json.loads(reads_file.read_text()) if reads_file.is_file() else None
        counts = m25.count_events(self.runs) if self.runs.is_dir() else {}
        rows = self.flow_rows
        browser = (sum(row["externalRequestCount"] for row in rows)
                   if rows and all(isinstance(row["externalRequestCount"], int) for row in rows) else None)
        return {"browserNonLoopbackRequests": browser, "providerCalls": len(calls),
                "productResolverReads": (reads or {}).get("productResolverReads"),
                "dispatchEvents": m25.dispatch_total(counts), "harnessDispatchGuard": any(
                    row["dispatchGuard"] for row in rows), "apiRequests": len(self.api.sent),
                "apiForbiddenSent": sum(1 for item in self.api.sent if item["method"] != "GET" and any(
                    part in item["path"] for part in c.FORBIDDEN_POST_PARTS))}

    def finish(self, folders_before: dict) -> int:
        lab = self.lab
        pytest_rows = self.evidence.get("pytest") or {}
        if lab is not None and "r6" in self.done:
            self.records["R6"] = cases.r6_case(self.evidence.get("r6Api") or {}, pytest_rows.get("R6", []),
                                               self.rows.get("r3"))
        if lab is not None and "r3" in self.done:
            ext = self.external
            self.records["R10"] = cases.r10_case(lab, self.rows.get("r3"), pytest_rows.get("R10", []),
                                                 self.evidence.get("blobs") or {}, ext.get("dispatchEvents", -1),
                                                 ext.get("providerCalls", -1))
        if lab is not None and {"r1", "r3", "r4a"} & self.done:
            texts, reports = self.r11_inputs_safe()
            record, scans = cases.r11_case(texts, reports, self.fixed)
            self.records["R11"] = record
            self.write("r11.json", scans)
        left = self.leftovers()
        folders_after = self.default_folders()
        gates = {
            "buildStamped": bool((self.state.get("build") or {}).get("buildCurrentWithSource")),
            "browserNonLoopback0": self.external.get("browserNonLoopbackRequests") == 0,
            "providerCalls0": self.external.get("providerCalls") == 0
            and self.external.get("reopenProviderCalls", 0) == 0
            and self.external.get("productResolverReads") in (0, None),
            "dispatchEvents0": self.external.get("dispatchEvents") == 0
            and not self.external.get("harnessDispatchGuard"),
            "noForbiddenRequest": self.external.get("apiForbiddenSent") == 0,
            "nothingLeft": not left,
            "defaultFoldersAbsent": not any(folders_before.values()) and not any(folders_after.values()),
            "fixedSentencesExported": self.fixed is not None,
        }
        cases_out = c.complete_cases(self.records, self.selected_cases())
        judged = c.judge(cases_out, {**gates, "exportClean": True}, rehearsal=self.rehearse, subset=self.subset)
        ledger = self.ledger(cases_out, gates, judged, left, folders_before, folders_after)
        clean = self.export(ledger)
        gates["exportClean"] = clean
        judged = c.judge(cases_out, gates, rehearsal=self.rehearse, subset=self.subset)
        ledger = self.ledger(cases_out, gates, judged, left, folders_before, folders_after)
        self.export(ledger)
        print(json.dumps({"acceptance": judged["acceptance"], "passed": judged["passed"], "counts": judged["counts"],
                          "notPassing": judged["notPassing"], "gates": gates, "out": str(self.out)},
                         ensure_ascii=False), flush=True)
        return 0 if judged["acceptance"] or (self.rehearse and judged["passed"]) else 1

    def r11_inputs_safe(self) -> tuple[dict[str, str], dict[str, str]]:
        """The report Markdown is read from the saved run folder by a short-lived second read: the services are down
        here, so the texts come from the stored report objects in the events (read-only)."""
        texts: dict[str, str] = {}
        for step, row in self.rows.items():
            for name, rel in ((row or {}).get("texts") or {}).items():
                path = self.artifacts / "steps" / step / rel
                if path.is_file():
                    texts[name] = path.read_text(errors="replace")
        reports: dict[str, str] = {}
        def observed(step: str) -> dict:
            return (self.rows.get(step) or {}).get("observed") or {}
        r1, r3, r4a = observed("r1").get("r1") or {}, observed("r3").get("r3") or {}, observed("r4a").get("r4a") or {}
        wanted = (("structure_repair", r1.get("run"), (r1.get("report") or {}).get("handle"), True),
                  ("mutation_candidates@3:section", r3.get("run"), r3.get("report"), False),
                  ("mutation_model@2:section", r4a.get("run"), r4a.get("modelReport"), False),
                  ("ligand_docking@2:section", r4a.get("run"), (r4a.get("docking") or {}).get("report"), False))
        for name, rid, handle, whole in wanted:
            if not (rid and handle):
                continue
            events = c.read_events(self.runs, rid)
            created = next((e for e in events if e.get("type") == "method_report_created"
                            and e.get("report_handle") == handle), None)
            if created is None:
                continue
            markdown = c.stored_object(events, created["markdown_handle"]).decode()
            reports[name] = markdown if whole else cases.report_section(markdown)
        return texts, reports

    def selected_cases(self) -> list[str]:
        step_cases = {"r1": ["R1", "R11"], "r3": ["R3", "R10"], "r4a": ["R4a"], "table": ["R5", "R2"], "r8": ["R8"],
                      "r7": ["R7"], "r6": ["R6"], "r4b": ["R4b"], "r9": ["R9"]}
        return [case for step in self.only for case in step_cases.get(step, [])]

    # ----- ledger and evidence ------------------------------------------------------------------------------------
    def ledger(self, cases_out: dict, gates: dict, judged: dict, left: list[str], before: dict, after: dict) -> dict:
        ledger = {"schema": c.LEDGER_SCHEMA, "phase": "fixture", "rehearsal": self.rehearse, "subset": self.subset,
                  "steps": self.only, "structures": self.structures, "acceptance": judged["acceptance"],
                  "passed": judged["passed"], "counts": judged["counts"], "notPassing": judged["notPassing"],
                  "gates": gates, "external": self.external, "leftover": left,
                  "defaultFolders": {"before": before, "after": after}, "build": self.state.get("build"),
                  "m15": self.state.get("m15"), "flowRows": self.flow_rows, "cases": list(cases_out.values()),
                  "fixedSentencesSha256": (self.fixed or {}).get("sha256"), "generatedAt": now()}
        (self.artifacts / "case-ledger.json").write_text(json.dumps(ledger, indent=2, ensure_ascii=False,
                                                                    default=str) + "\n")
        return ledger

    def table_markdown(self) -> str:
        lines = ["# M29 구조 분류 표 (명세 §10.1)", "",
                 ("독립 분류 = `scripts/m29_oracle.py`(입력 파일과 설치된 Amber14 템플릿만). 제품 = 사전 검사 읽기. "
                  "`m21_band`는 T1 측정 표 상수(출처 열)이고 독립 계산이 아니다."), "",
                 "| 구조 | 물 정책 | 문서 | 독립 분류 | 제품 | 보완 뒤 중원자 | m21_band (출처) | 사슬 | 결과 |",
                 "|---|---|---|---|---|---|---|---|---|"]
        for row in self.evidence.get("table") or []:
            band = row.get("m21Band") or {}
            source = "측정" if band.get("source") == c.BAND_SOURCE_MEASURED else "규칙" if band.get("source") else ""
            chain = ("repair→M20→M21 " + ((row.get("m21Job") or {}).get("status") or "?")) if row.get("record") else (
                f"거절 {((row.get('submit') or {}).get('reason'))}" if row.get("submit") else "—")
            lines.append(f"| {row['structure']} | {row['waters']} | {row.get('documented')} | "
                         f"{(row.get('oracle') or {}).get('verdict')} | {row.get('product')} | "
                         f"{(row.get('oracle') or {}).get('proteinHeavyAfter')} | {band.get('band') or '—'} "
                         f"({source or 'n/a'}) | {chain} | {'pass' if row.get('ok') else 'fail'} |")
        return "\n".join(lines) + "\n"

    def readme(self, ledger: dict) -> str:
        scope = "연습(rehearsal, 최종 수락 증거 아님)" if ledger["rehearsal"] else "fixture"
        lines = [f"# M29 구조 보완 수락 증거 ({scope})", "",
                 (f"- 생성: {ledger['generatedAt']} · acceptance **{str(ledger['acceptance']).lower()}** · 통과 "
                  f"{ledger['passed']} · 사례 {json.dumps(ledger['counts'], ensure_ascii=False)}"),
                 f"- 단계: {', '.join(ledger['steps'])} (일부만 돌리면 acceptance는 늘 false) · 구조 {len(ledger['structures'])}개",
                 (f"- 소스: {(ledger['build'] or {}).get('gitHead')} · 작업 트리 변경 "
                  f"{len((ledger['build'] or {}).get('dirtyFiles') or [])}개"),
                 f"- 관문: {json.dumps(ledger['gates'], ensure_ascii=False)}",
                 f"- 외부 요청: {json.dumps(ledger['external'], ensure_ascii=False)}", "",
                 "## 사례", "", "| 사례 | 내용 | 상태 | 이유 | 허용된 관찰 공백 |", "|---|---|---|---|---|"]
        for record in ledger["cases"]:
            gaps = ", ".join(f"{gap['part']}:{gap['reason']}" for gap in record.get("allowedGaps") or [])
            lines.append(f"| {record['id']} | {record['title']} | {record['status']} | {record.get('reason') or ''} | "
                         f"{gaps} |")
        lines += ["", ("not_observed와 fail은 통과로 세지 않는다. 합성 표시 자료: `backend/tests/fixtures/structure_repair/"
                       "synthetic-*.cif`(R7), `backend/tests/fixtures/mutation_model/synthetic-phenol-ligand.sdf`(R4a "
                       "도킹, 기계적 경로 확인). 큰 증거·스크린숏·내려받기·화면 글자는 Git 제외 artifacts에 있고 여기에는 "
                       "경로·크기·SHA-256만 있다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다."), ""]
        return "\n".join(lines) + "\n"

    def export(self, ledger: dict) -> bool:
        replacements = [(str(self.code), "<repo>"), (str(REPO), "<repo>"), (str(Path.home()), "<home>"),
                        ("/private/var/folders", "<tmp>")]
        marker = self.out / OUT_MARKER
        if self.out.exists() and any(self.out.iterdir()):
            if not marker.is_file():
                raise RuntimeError(f"{self.out} holds files this runner did not write")
            shutil.rmtree(self.out)          # the runner's own first export (rewritten with the final gates)
        self.out.mkdir(parents=True, exist_ok=True)
        marker.write_text("written by scripts/m29_offscreen_acceptance.py\n")
        sums, files, held = [], [], []
        for path in sorted(self.artifacts.rglob("*")):
            rel = path.relative_to(self.artifacts)
            if not path.is_file() or rel.parts[0] == "services" or "browser-profile" in rel.parts:
                continue
            record = {"path": str(rel), "bytes": path.stat().st_size, "sha256": m13.sha_file(path)}
            if path.suffix not in TEXT_SUFFIXES or "downloads" in rel.parts:
                files.append(record)
                continue
            text = m13.redact(path.read_text(errors="replace"), replacements)
            leaks = c.leak_kinds(text)
            if path.stat().st_size > MAX_TEXT_BYTES and path.name != "case-ledger.json":
                held.append({**record, "held": "over_256KiB"})
            elif leaks:
                held.append({**record, "held": leaks[0]})
            else:
                target = self.out / "evidence" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
                sums.append(f"{m13.sha_file(target)}  evidence/{rel}")
        written = {
            "binary-artifacts.json": json.dumps({"note": "screenshots, paint frames, downloads, screen texts and text "
                                                         "above 256 KiB stay in the git-ignored artifacts folder; path, "
                                                         "size and sha256 only", "artifacts": str(self.artifacts),
                                                 "files": files, "heldText": held}, indent=2),
            "summary.json": json.dumps({key: ledger[key] for key in (
                "schema", "phase", "rehearsal", "subset", "steps", "acceptance", "passed", "counts", "notPassing",
                "gates", "external", "leftover", "defaultFolders", "build", "generatedAt")}, indent=2,
                ensure_ascii=False, default=str),
            "cases.json": json.dumps({"schema": "m29_acceptance_cases@1", "acceptance": ledger["acceptance"],
                                      "cases": ledger["cases"]}, indent=2, ensure_ascii=False, default=str),
            "classification-table.json": json.dumps(self.evidence.get("table") or [], indent=2, ensure_ascii=False,
                                                    default=str),
            "classification-table.md": self.table_markdown(),
            "README.md": self.readme(ledger)}
        for name, text in written.items():
            (self.out / name).write_text(m13.redact(text, replacements) + ("\n" if not text.endswith("\n") else ""))
            sums.append(f"{m13.sha_file(self.out / name)}  {name}")
        (self.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
        found = {str(p.relative_to(self.out)): c.leak_kinds(p.read_text(errors="replace"))
                 for p in self.out.rglob("*") if p.is_file()}
        found = {name: kinds for name, kinds in found.items() if kinds}
        for name in found:
            target = self.artifacts / "held-from-out" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self.out / name), str(target))
        self.record("export-evidence", "pass" if not found else "fail", leaks=found, held=len(held))
        return not found


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="a NEW git-ignored QA root (runs, reference copies, fixture "
                        "control and the reopen folder are made inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="new git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m29-repair/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m29-repair-<YYYYMMDD>/acceptance; "
                        "with --rehearse <root>/out-rehearsal)")
    parser.add_argument("--rehearse", action="store_true", help="a rehearsal: never acceptance (its result is "
                        "'passed'); allows --only / --structures")
    parser.add_argument("--only", type=steps_arg, default=None, help=f"rehearsal only: a subset of {','.join(STEPS)}")
    parser.add_argument("--structures", type=structures_arg, default=None, help="rehearsal only: the structures of the "
                        "table step (default all thirteen)")
    parser.add_argument("--m15-reference", default=".deps/reference", help="active M15 reference folder, copied "
                        "read-only (relative paths from the code root)")
    parser.add_argument("--saved-report-runs", default="runs/m28-fixture-20261012/fixture",
                        help="the M28 fixture phase folder whose runs/ hold stored M20 @2 and M21 @1 reports (R9; its "
                        "reaction_reference is copied read-only for the reopen)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner from "
                        "the current frontend source")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
