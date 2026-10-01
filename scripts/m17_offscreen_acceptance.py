#!/usr/bin/env python3
"""Run the M17 ligand partial-replacement candidate offscreen acceptance (spec §12.4).

One command, given a code root (default: this repository), checks the locked RDKit environment, builds the frontend
when needed (typecheck, then build, never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000
with PYTHONPATH=<code root>/backend and MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives the real
Electron offscreen flow frontend/tests/offscreen/ligand-flow.cjs mode by mode, and assembles case-ledger.json.

Sequence:
  0. environment       <code root>/.deps/prolif/venv-locked/bin/python must exist and the backend must report
                       methods.ligand_candidates available. Missing is an acceptance failure, never "unavailable".
  1. ligand-main       run (structure tab: 새 run + 1MQ4) → ligand tab → parent/block files + rules → import →
                       inspection job (approval UI) → numbered 2D figure + atom table (explicit-H serials) → site
                       reject/pass → enumeration job → candidate table vs the T1 hand oracle → filters (boundaries),
                       passes-only, sort → report + knowledge-tab list + downloads → zero-candidate set → invalid
                       rules → paging (labeled generated chain list) → structure tab kept mounted → run switch with a
                       held late response.
  2. ligand-unavailable the backend is restarted from <root>/layout-worker-missing (byte-identical backend/mw and config
                       copy without .deps: capability worker_missing) on a fresh runs folder; no-run and unavailable
                       states show a reason only.
Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never
deleted or retried away. The ledger's ``acceptance`` is true only when the environment check passed, every step ran in
this invocation, every case passed, every flow row measured 0 non-loopback requests and zero provider calls, the
build was stamped from the current frontend source and no worker process or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw.

Usage:
  .venv/bin/python scripts/m17_offscreen_acceptance.py --root runs/m17-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/<label> \\
      [--out docs/qa/m17-ligand-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never]
"""
from __future__ import annotations

import argparse
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, bookkeeping and evidence export of the M15 runner.
import m15_offscreen_acceptance as m15

REPO = Path(__file__).resolve().parents[1]
FLOW = "ligand-flow.cjs"
FLOW_STEPS = ["ligand-main", "ligand-unavailable"]
MODE_OF = {"ligand-main": "main", "ligand-unavailable": "unavailable"}
WORKER_PYTHON = Path(".deps/prolif/venv-locked/bin/python")
LAYOUT = "layout-worker-missing"
LAYOUT_LABEL = ("labeled runtime layout: byte-identical backend/mw and config copy without .deps "
                "(locked RDKit environment absent: capability worker_missing)")
# Spec §12.4 cases → the flow modes that observe them.
CASE_PLAN: dict[str, list[str]] = {
    "L-run-create": ["ligand-main"], "L-inputs-import": ["ligand-main"], "L-inspect-job": ["ligand-main"],
    "L-inspection-figure": ["ligand-main"], "L-atom-numbering": ["ligand-main"], "L-rules-status": ["ligand-main"],
    "L-invalid-rule": ["ligand-main"], "L-site-check": ["ligand-main"], "L-enumerate-job": ["ligand-main"],
    "L-candidates-oracle": ["ligand-main"], "L-filters": ["ligand-main"], "L-passes-only": ["ligand-main"],
    "L-sort": ["ligand-main"], "L-paging": ["ligand-main"], "L-report": ["ligand-main"],
    "L-zero-candidates": ["ligand-main"], "L-structure-kept": ["ligand-main"], "L-run-switch-late": ["ligand-main"],
    "L-no-run": ["ligand-unavailable"], "L-unavailable": ["ligand-unavailable"],
}
CASE_TEXT = {
    "L-run-create": "structure tab: 새 run + public_1mq4.cif; the ligand tab uses the global run (ready, capability line)",
    "L-inputs-import": "explicit-H parent SDF, block SDF, block SMILES chosen through the file chooser, six rules typed, "
                       "가져오기 → three chemical_raw_input handles listed by the backend",
    "L-inspect-job": "점검 시작 → 비싼 계산 승인 → 작업 시작 → real rdkit_inspect_v1 done, one expensive unit",
    "L-inspection-figure": "inspection chosen by hand (none automatic); numbered RDKit 2D figure loads as an <img> data "
                           "URI equal to the stored SVG, no inline SVG",
    "L-atom-numbering": "atom table = heavy atoms with SDF serials of the explicit-H parent (H serials skipped), elements "
                        "and heavy neighbours equal the T1 hand oracle",
    "L-rules-status": "rules user_1–3 valid, user_4 reactant_count, user_5 reaction_parse_failed, user_6 "
                      "duplicate_rule; block library accepted/rejected counts equal the hand oracle",
    "L-invalid-rule": "invalid rules shown as invalid with the reason and cannot be chosen for generation",
    "L-site-check": "site 19 → rejected crossing_bond_count (start disabled); 19+20 → one single crossing bond 14–19, "
                    "site hydrogens 21–23, start enabled",
    "L-enumerate-job": "후보 생성 시작 (fixed + user_1–3) → real rdkit_enumerate_v1 done, one expensive unit",
    "L-candidates-oracle": "table rows = server rows; 10 candidate SMILES equal the hand oracle, ids = c_ + SHA-256[:16], "
                           "duplicate origins and rejected counts equal the hand trace, five limitations",
    "L-filters": "heavy atoms 12–14 (inclusive) and mol_weight max = stored boundary value; invalid input refused "
                 "without a read; PAINS exclusion per stored matches",
    "L-passes-only": "필터 통과만 보기: only passing rows; total and hidden-by-filter counts shown",
    "L-sort": "sort by mol_weight descending equals the stored values' order",
    "L-paging": "labeled generated chain list → 62 candidates: page 1 (50), 다음 (12), 이전; ids disjoint and complete",
    "L-report": "보고서 만들기 (filters recorded) → 리간드 후보 보고서 in the knowledge-tab list; downloads equal the "
                "backend bytes",
    "L-zero-candidates": "fixed off + user_3 (outside the site) → 0 candidates: 빈 결과 (not 실패), outside_site counts",
    "L-structure-kept": "structure tab stays mounted (hidden) while the ligand tab is shown; same Mol* session, source "
                        "and generation on return; global budget equals the backend",
    "L-run-switch-late": "run B shows only its own lists; a held run A inspection-list response released after the "
                         "switch is not applied",
    "L-no-run": "no run: the ligand tab shows only the no-run reason (no numbers, no controls)",
    "L-unavailable": "backend without the locked environment: 사용할 수 없음 with the capability reason "
                     "(worker_missing), no numbers, no controls, no ligand requests",
}
WORKERS = (*m13.WORKERS, "ligand_worker.py")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tree_digest(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): m13.sha_file(path) for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts}


def environment_ok(environment: dict) -> bool:
    """The locked worker interpreter existed, the main backend reported the method available and the layout backend
    reported worker_missing."""
    return (environment.get("workerPython") is True and environment.get("mainAvailable") is True
            and environment.get("layoutReason") == "worker_missing")


def assemble(rows: list[dict], leftovers: list[str], environment: dict) -> dict:
    """Judge the latest row of every flow step and every case of CASE_PLAN.

    A step passes when its latest row passed, measured 0 non-loopback requests and zero provider calls. A case passes
    only when every covering step's latest row reports it as pass (absent = fail). Returns
    {steps, cases, verdictParts, passed}.
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
    judged = [latest[step] for step in FLOW_STEPS if step in latest]
    cases["S-no-egress"] = {"text": "non-loopback requests 0 and zero provider calls on every flow row",
                            "status": "pass" if len(judged) == len(FLOW_STEPS) and all(
                                r.get("externalRequestCount") == 0 and r.get("providerCallsZero") is True
                                for r in judged) else "fail"}
    parts = {"steps": all(v["status"] == "pass" for v in steps.values()),
             "cases": all(v["status"] == "pass" for v in cases.values()),
             "environment": environment_ok(environment), "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "verdictParts": parts, "passed": all(parts.values())}


def acceptance_ok(passed: bool, build: dict | None) -> bool:
    return passed and bool((build or {}).get("buildCurrentWithSource"))


class Runner(m15.Runner):
    """The M15 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw
    path check, allowlisted env, leftover check, redacted export) with the M17 flow, environment check and ledger.
    No reference snapshot is needed (the M15 kbase check is not run)."""

    def __init__(self, args: argparse.Namespace) -> None:  # not super().__init__: that one requires --kbase
        self.code = Path(args.code_root).resolve()
        self.frontend = self.code / "frontend"
        self.offscreen = self.frontend / "tests/offscreen"
        venv = self.code / ".venv/bin/python"
        self.python = venv if venv.exists() else Path(sys.executable)
        self.root = Path(args.root).resolve()
        self.runs = self.root / "runs"
        self.reference = self.root / "reference"
        self.unavailable_runs = self.root / "unavailable-runs"
        self.artifacts = Path(args.artifacts).resolve()
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        self.out = (Path(args.out).resolve() if args.out
                    else self.code / "docs/qa" / f"m17-ligand-{stamp}" / "acceptance")
        self.build_mode = args.build
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        self.reference_steps: dict[str, dict] = {}
        self.environment: dict = {}
        for bad in ("/tmp", "/private/tmp"):
            for path in (self.root, self.artifacts, self.out):
                if str(path) == bad or str(path).startswith(bad + "/"):
                    raise SystemExit("QA roots and evidence folders must not be under /tmp")
        if self.root in (self.code / "runs", REPO / "runs"):
            raise SystemExit("--root must be a fresh folder, not the repository runs/ folder itself")
        ignored = subprocess.run(["git", "check-ignore", "-q", str(self.artifacts / "x")], cwd=self.code, check=False)
        if ignored.returncode != 0:
            raise SystemExit(f"--artifacts must be git-ignored: {self.artifacts}")

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m17_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    # ----- services ----------------------------------------------------------------------------
    def start_backend_at(self, name: str, code_root: Path, runs: Path) -> None:
        env = m13.child_env({"PYTHONPATH": str(code_root / "backend"), "MW_RUNS_DIR": str(runs),
                             "MW_REFERENCE_DIR": str(self.reference)})
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=code_root,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(code_root / "backend")):
            raise RuntimeError(f"backend import resolved outside {code_root}: {probe.stdout}")
        runs.mkdir(parents=True, exist_ok=True)
        log = self.artifacts / "services" / f"{name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=code_root, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{m15.API}/capabilities")
        self.state.setdefault("services", []).append({"name": name, "runs": str(runs), "code": str(code_root),
                                                      "python": str(self.python), "mw": probe.stdout.strip(),
                                                      "startedAt": now()})
        self.save()

    def stop_backend(self) -> None:
        proc = self.services.pop("backend", None)
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=30)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
        deadline = time.time() + 30
        while m13.listening(8000) and time.time() < deadline:
            time.sleep(0.5)

    def ligand_capability(self) -> dict:
        return (self.get_json("/capabilities").get("methods") or {}).get("ligand_candidates") or {}

    def layout(self) -> Path:
        """Byte-identical backend/mw + config copy without .deps (the locked worker interpreter is absent)."""
        target = self.root / LAYOUT
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.code / "backend/mw", target / "backend/mw", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.code / "config", target / "config", ignore=shutil.ignore_patterns("__pycache__"))
        source = {**{f"backend/mw/{k}": v for k, v in tree_digest(self.code / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(self.code / "config").items()}}
        copied = {**{f"backend/mw/{k}": v for k, v in tree_digest(target / "backend/mw").items()},
                  **{f"config/{k}": v for k, v in tree_digest(target / "config").items()}}
        if source != copied:
            raise RuntimeError(f"{LAYOUT}: copied backend/config differs from source")
        if (target / WORKER_PYTHON).exists():
            raise RuntimeError(f"{LAYOUT}: the locked worker interpreter is present")
        manifest = {"label": LAYOUT_LABEL, "files": len(copied),
                    "treeSha256": hashlib.sha256(json.dumps(copied, sort_keys=True).encode()).hexdigest()}
        (self.artifacts / f"{LAYOUT}.json").write_text(json.dumps(manifest, indent=2) + "\n")
        self.state.setdefault("layouts", {})[LAYOUT] = manifest
        return target

    def leftovers(self) -> list[str]:
        # Only workers whose working directory is inside this acceptance root count (not other pytest runs).
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
        cap = self.ligand_capability()
        self.environment["mainAvailable"] = cap.get("available") is True
        self.environment["mainCapability"] = {k: cap.get(k) for k in ("available", "status", "reason_code", "pins")}
        self.record("environment-capability", "pass" if self.environment["mainAvailable"] else "fail",
                    capability=self.environment["mainCapability"])
        if self.environment["mainAvailable"]:
            self.flow("ligand-main", MODE_OF["ligand-main"], [])
        else:
            self.missing_prerequisite("ligand-main", "backend reports methods.ligand_candidates unavailable: "
                                      f"{cap.get('reason_code')}")
        self.stop_backend()
        layout = self.layout()
        self.start_backend_at("backend-worker-missing", layout, self.unavailable_runs)
        cap = self.ligand_capability()
        self.environment["layoutReason"] = cap.get("reason_code") if cap.get("available") is False else "available"
        self.record("layout-capability", "pass" if self.environment["layoutReason"] == "worker_missing" else "fail",
                    capability={k: cap.get(k) for k in ("available", "status", "reason_code")})
        if self.environment["layoutReason"] == "worker_missing":
            self.flow("ligand-unavailable", MODE_OF["ligand-unavailable"], ["--fixture-label", LAYOUT_LABEL])
        else:
            self.missing_prerequisite("ligand-unavailable", f"layout backend did not report worker_missing: {cap}")

    # ----- ledger and evidence -----------------------------------------------------------------
    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "status": row.get("status"),
                         "cases": row.get("cases") or {}, "runs": row.get("runs"), "runId": row.get("runId"),
                         "evidenceKind": row.get("evidenceKind"), "handles": row.get("handles", {}),
                         "inputs": row.get("inputs", []), "fixtureLabels": row.get("fixtureLabels", []),
                         "controls": row.get("controls", {}),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment)
        passed = judged["passed"]
        ledger = {"schema": "m17_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
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
        lines = ["# M17 리간드 부분 교체 후보 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 작업 환경: venv-locked 인터프리터 {'있음' if env.get('workerPython') else '없음'} · 주 backend "
                  f"capability {'사용 가능' if env.get('mainAvailable') else '사용 불가'} · 환경 없는 layout backend "
                  f"`{env.get('layoutReason')}`"),
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 "## 사례", "", "| 사례 | 내용 | 결과 | 모드 |", "|---|---|---|---|"]
        for case, value in ledger["cases"].items():
            modes = ", ".join(f"{k}:{v}" for k, v in value.get("modes", {}).items())
            lines.append(f"| {case} | {value['text']} | {value['status']} | {modes} |")
        lines += ["", "## 단계", "", "| 단계 | 결과 | 문제 |", "|---|---|---|"]
        for step, value in ledger["steps"].items():
            lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m17_offscreen_acceptance.py --root runs/m17-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m17-acceptance/<label> \\",
                  "    --out docs/qa/m17-ligand-<YYYYMMDD>/acceptance",
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
        worker = self.code / WORKER_PYTHON
        self.environment["workerPython"] = worker.is_file()
        self.environment["workerPythonPath"] = str(WORKER_PYTHON)
        self.record("environment", "pass" if worker.is_file() else "fail", workerPython=str(worker),
                    present=worker.is_file())
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
                        "frontend/tests/offscreen/artifacts/m17-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m17-ligand-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
