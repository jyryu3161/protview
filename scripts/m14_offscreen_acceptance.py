#!/usr/bin/env python3
"""Run the M14 top-level tab offscreen acceptance (spec §10.4).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend and
MW_RUNS_DIR=<root>/runs; `next start` on 127.0.0.1:3000), drives the real Electron offscreen flow
frontend/tests/offscreen/tabs-flow.cjs mode by mode, and assembles case-ledger.json. Every step keeps its own directory
with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never deleted or retried away.

Phases (``--phases``, comma list, in this order):
  tabs    tabs-main (fresh root: no-run guidance first; tab bar; 1HSG structure state across the three other tabs;
          unavailable notices (protein/ligand; knowledge shows the M15 numbering screen) and their requests; inspect_ligand workflow (interaction + method report, summary) and a
          stopped execution; saved figure; reports tab lists/content/downloads; labeled 422 reports-list fault; 1UBQ
          OpenMM job progressing while another tab is shown; global run/budget; run switch with held late responses),
          tabs-chemical (chemical workspace: tab bar, state across a tab round trip, global run/budget after the
          expensive ProLIF jobs; needs <code root>/.deps/prolif).
  ledger  case-ledger.json + README.md + SHA256SUMS into --out (text evidence, <repo>/<home> redacted).
Default: tabs,ledger. The ledger's ``acceptance`` is true only when every tabs step ran in this invocation and every
case passed. ``--build auto`` reuses frontend/.next only when a runner stamped it from the current frontend source
(the stamp is shared with scripts/m13_offscreen_acceptance.py).

A case passes only when every step that covers it has a passing latest row. Every row must carry a measured
non-loopback request count of 0 and zero provider calls (no egress events, zero external tokens/USD). Product issues
observed while driving (recovered through a visible control) are failing P-* cases. No worker process whose working
directory is inside the root and no 8000/3000 listener may remain. Exit status is 1 on any failure.

The runs root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an
allowlisted environment (no OPENROUTER_* or other secrets). This script never imports mw.

Usage:
  .venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m14-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/<label> \\
      [--out docs/qa/m14-tabs-<YYYYMMDD>] [--phases tabs,ledger] [--only tabs-main,tabs-chemical] [--code-root <dir>]
      [--build auto|always|never]
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

REPO = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
PHASES = ["tabs", "ledger"]
DEFAULT_PHASES = "tabs,ledger"
TAB_STEPS = ["tabs-main", "tabs-chemical"]
PHASE_STEPS = {"tabs": TAB_STEPS, "ledger": []}
ALL_STEPS = list(TAB_STEPS)
ACCEPTANCE_PHASES = ("tabs",)
STEP_TIMEOUT_S = 2400
# Spec §10.4 cases → the flow modes that observe them (each listed mode must pass the case).
CASE_PLAN: dict[str, list[str]] = {
    "T-tabs": ["tabs-main"], "T-structure-state": ["tabs-main"], "T-running-job": ["tabs-main"],
    "T-chemical-preserved": ["tabs-chemical"], "T-unavailable": ["tabs-main"], "T-reports-list": ["tabs-main"],
    "T-reports-content": ["tabs-main"], "T-reports-fault": ["tabs-main"], "T-no-run": ["tabs-main"],
    "T-run-switch": ["tabs-main"], "T-late-response": ["tabs-main"], "T-global-run": ["tabs-main", "tabs-chemical"],
    "T-budget-main": ["tabs-main"], "T-budget-chemical": ["tabs-chemical"],
}
CASE_TEXT = {
    "T-tabs": "four tabs in order with their labels; 구조 분석 selected by default; switching keeps the address",
    "T-structure-state": "source handle, representation, residue selection, camera identical after visiting the other "
                         "three tabs; non-empty paint after return",
    "T-running-job": "a running OpenMM job keeps progressing (polling) while another tab is shown",
    "T-chemical-preserved": "chemical workspace kept across a tab round trip; tab bar visible there",
    "T-unavailable": "unavailable tabs (단백질 공학, 리간드 설계·탐색): 사용할 수 없음, reason, opening stage; no "
                     "numbers/controls; no requests of their own. 지식·보고서 shows the M15 numbering screen instead of "
                     "its former notice",
    "T-reports-list": "interaction + method report, saved figure, completed summary listed; non-complete execution absent",
    "T-reports-content": "content shown; download bytes SHA-256 equal the backend bytes of the same format",
    "T-reports-fault": "reports-list fault (labeled fixture) affects only that list; retry; structure screen intact",
    "T-no-run": "no run: guidance shown and no list request",
    "T-run-switch": "after a run switch in 구조 분석 the reports tab shows only the new run's lists",
    "T-late-response": "held list responses of the previous run released after the switch are dropped",
    "T-global-run": "global run id equals the structure (and chemical) screen's",
    "T-budget-main": "global budget equals backend /budget after an expensive computation at tab switch (main screen)",
    "T-budget-chemical": "global budget equals backend /budget after expensive jobs at tab switch (chemical screen)",
}
WORKERS = m13.WORKERS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def acceptance_ok(partial: bool, phases: list[str], passed: bool) -> bool:
    return not partial and passed and set(ACCEPTANCE_PHASES) <= set(phases)


def assemble(rows: list[dict], required: list[str], leftovers: list[str]) -> dict:
    """Judge the latest row of every required step and every case of CASE_PLAN covered by a required step.

    A step passes when its latest row passed, measured 0 non-loopback requests and zero provider calls. A case passes
    only when every covering required step's latest row reports it as pass (absent = fail). P-* product issues on a
    latest row are failing cases. Returns {steps, cases, verdictParts, passed}.
    """
    attempts: dict[str, list[tuple[tuple[int, str], dict]]] = {}
    for row in rows:
        base, order = m13.step_base(row["step"])
        attempts.setdefault(base, []).append((order, row))
    latest = {step: max(found, key=lambda item: item[0])[1] for step, found in attempts.items()}
    steps: dict[str, dict] = {}
    for step in required:
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
        covering = [mode for mode in modes if mode in required]
        if not covering:
            continue
        seen = {mode: ((latest.get(mode) or {}).get("cases") or {}).get(case) for mode in covering}
        cases[case] = {"text": CASE_TEXT[case], "modes": seen,
                       "status": "pass" if all(value == "pass" for value in seen.values()) else "fail"}
    judged = [latest[step] for step in required if step in latest]
    cases["S-no-egress"] = {"text": "non-loopback requests 0 and zero provider calls on every flow row",
                            "status": "pass" if judged and all(r.get("externalRequestCount") == 0 and
                                                               r.get("providerCallsZero") is True for r in judged)
                            else "fail"}
    for row in judged:
        for case in row.get("cases") or {}:
            if case.startswith("P-"):
                entry = cases.setdefault(case, {"text": "product issue observed while driving (recovered through a "
                                                        "visible control)", "status": "fail", "steps": []})
                entry["steps"].append(row["step"])
    parts = {"steps": bool(steps) and all(v["status"] == "pass" for v in steps.values()),
             "cases": all(v["status"] == "pass" for v in cases.values()), "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "verdictParts": parts, "passed": all(parts.values())}


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.code = Path(args.code_root).resolve()
        self.frontend = self.code / "frontend"
        self.offscreen = self.frontend / "tests/offscreen"
        venv = self.code / ".venv/bin/python"
        # The code root's venv, else the interpreter running this runner (e.g. the main checkout's .venv).
        self.python = venv if venv.exists() else Path(sys.executable)
        self.root = Path(args.root).resolve()
        self.artifacts = Path(args.artifacts).resolve()
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        self.out = Path(args.out).resolve() if args.out else self.code / "docs/qa" / f"m14-tabs-{stamp}"
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
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        for bad in ("/tmp", "/private/tmp"):
            for path in (self.root, self.artifacts, self.out):
                if str(path) == bad or str(path).startswith(bad + "/"):
                    raise SystemExit("QA roots and evidence folders must not be under /tmp")
        if self.root in (self.code / "runs", REPO / "runs"):
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
        base = {"schema": "m14_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    def missing_prerequisite(self, step: str, reason: str) -> None:
        step_dir = self.fresh_dir(step)
        self.write_row(step_dir, {"mode": step, "evidenceKind": "not_run", "status": "fail", "cases": {},
                                  "externalRequestCount": None, "providerCallsZero": None, "error": reason})
        self.record(step, "fail", reason=reason)

    # ----- build -------------------------------------------------------------------------------
    def build(self) -> None:
        build_id = self.frontend / ".next/BUILD_ID"
        if self.build_mode == "never" or (self.build_mode == "auto" and m13.build_is_current(self.frontend)):
            if not build_id.is_file():
                raise SystemExit("frontend is not built and --build never was given")
            reason = ("BUILD_ID stamped from the current source" if self.build_mode == "auto"
                      else "BUILD_ID present; source not checked")
            self.state["buildCommands"] = {"skipped": True, "reason": f"--build {self.build_mode}, {reason}"}
            return
        results: dict = {}
        for script in ("typecheck", "build"):  # sequential: typecheck and build never run concurrently
            log = self.artifacts / "services" / f"{script}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("w") as out:
                rc = subprocess.run(["npm", "--prefix", str(self.frontend), "run", script], cwd=self.code,
                                    env=m13.child_env(), stdout=out, stderr=subprocess.STDOUT, check=False).returncode
            results[script] = rc
            self.record(f"frontend-{script}", "pass" if rc == 0 else "fail", exitCode=rc, log=str(log))
            if rc != 0:
                raise SystemExit(f"npm run {script} failed ({rc}); see {log}")
        results["sourceSha256"] = m13.stamp_build(self.frontend)
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

    def start_backend(self, runs_dir: Path) -> None:
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(runs_dir)})
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=self.code,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(self.code / "backend")):
            raise RuntimeError(f"backend import resolved outside {self.code}: {probe.stdout}")
        runs_dir.mkdir(parents=True, exist_ok=True)
        log = self.artifacts / "services" / "backend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=self.code, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{API}/capabilities")
        self.state.setdefault("services", []).append({"name": "backend", "runs": str(runs_dir), "code": str(self.code),
                                                      "python": str(self.python), "mw": probe.stdout.strip(),
                                                      "startedAt": now()})
        self.save()

    def start_frontend(self) -> None:
        log = self.artifacts / "services" / "frontend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["frontend"] = subprocess.Popen(
            ["npm", "--prefix", str(self.frontend), "run", "start", "--", "-p", "3000"], cwd=self.code,
            env=m13.child_env(), stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(WEB + "/")

    def stop_all(self) -> None:
        for name in list(self.services):
            proc = self.services.pop(name)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=30)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)

    def get_json(self, path: str):
        with urllib.request.urlopen(API + path, timeout=120) as response:
            return json.loads(response.read())

    # ----- flow steps --------------------------------------------------------------------------
    def flow(self, step: str, mode: str) -> dict | None:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / "tabs-flow.cjs"), "--url", WEB, "--mode", mode, "--artifacts", str(step_dir)]
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

    def run_tabs(self) -> None:
        if self.wanted("tabs-main"):
            self.flow("tabs-main", "main")
        if self.wanted("tabs-chemical"):
            templates = self.get_json("/capabilities")["methods"]["analysis_workflows"]["templates"]
            chemical = templates.get("chemical_interactions", {})
            self.state["chemicalCapability"] = chemical
            if chemical.get("available") is True:
                self.flow("tabs-chemical", "chemical")
            else:
                self.missing_prerequisite("tabs-chemical", "chemical_interactions unavailable on this backend "
                                          f"(<code root>/.deps/prolif needed): {chemical.get('reason')}")
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
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        required = sorted(self.only) if self.partial else [s for p in self.phases for s in PHASE_STEPS[p]]
        judged = assemble(rows, required, leftovers)
        passed = judged["passed"]
        verdict = "partial_not_acceptance" if self.partial else "pass" if passed else "fail"
        ledger = {"schema": "m14_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": verdict, "acceptance": acceptance_ok(self.partial, self.phases, passed)
                  and bool((self.state.get("build") or {}).get("buildCurrentWithSource")),
                  "acceptancePhases": list(ACCEPTANCE_PHASES), "phases": self.phases,
                  "scope": {"partial": self.partial, "only": sorted(self.only), "requiredSteps": required},
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "leftoverProcesses": leftovers,
                  "externalRequestsTotal": sum(r["externalRequestCount"] or 0 for r in rows),
                  "rowsWithUnknownExternalCount": [r["step"] for r in rows if r["externalRequestCount"] is None],
                  "rows": rows}
        name = "case-ledger-partial.json" if self.partial else "case-ledger.json"
        (self.artifacts / name).write_text(json.dumps(ledger, indent=2) + "\n")
        self.record("case-ledger", "pass" if passed else "fail", verdict=verdict, acceptance=ledger["acceptance"],
                    cases={case: value["status"] for case, value in judged["cases"].items()},
                    output=str(self.artifacts / name))
        return ledger

    def readme(self, ledger: dict) -> str:
        lines = ["# M14 탭 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}** · phases {', '.join(ledger['phases'])}"),
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
                  ".venv/bin/python scripts/m14_offscreen_acceptance.py --root runs/m14-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m14-acceptance/<label> \\",
                  "    --out docs/qa/m14-tabs-<YYYYMMDD>",
                  "```", "",
                  ("`--build auto`는 현재 frontend 소스로 도장 찍힌 빌드만 재사용하고, 아니면 typecheck 다음 build를 "
                   "차례로 돌린다. 화학 모드는 `<code root>/.deps/prolif`가 있어야 하며 없으면 실패로 기록한다.")]
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
                target.write_text(m13.redact(path.read_text(errors="replace"), replacements))
                sums.append(f"{m13.sha_file(target)}  evidence/{rel}")
            else:
                binaries.append({"path": str(rel), "bytes": path.stat().st_size, "sha256": m13.sha_file(path)})
        (self.out / "binary-artifacts.json").write_text(m13.redact(json.dumps({
            "note": "screenshots/paint frames/downloads stay in the git-ignored artifacts folder; hashes only",
            "artifacts": str(self.artifacts), "files": binaries}, indent=2), replacements) + "\n")
        (self.out / "README.md").write_text(m13.redact(self.readme(ledger), replacements))
        for name in ("binary-artifacts.json", "README.md"):
            sums.append(f"{m13.sha_file(self.out / name)}  {name}")
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

    def run(self) -> int:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        runs = self.root / "runs"
        if "tabs" in self.phases and self.wanted("tabs-main") and runs.exists() and any(runs.iterdir()):
            raise SystemExit(f"runs root {runs} is not fresh; choose a new --root (tabs-main needs an empty root)")
        if "tabs" in self.phases:
            busy = {port: m13.listening(port) for port in (8000, 3000)}
            if any(busy.values()):
                raise SystemExit(f"ports must be free before the runner starts its own services: {busy}")
            self.build()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.code, capture_output=True, text=True,
                              check=False).stdout.strip()
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=self.code, capture_output=True, text=True,
                                   check=False).stdout
        build_id = self.frontend / ".next/BUILD_ID"
        deps = self.code / ".deps"
        self.state["build"] = {"buildId": build_id.read_text().strip() if build_id.exists() else None, "gitHead": head,
                               "buildCurrentWithSource": m13.build_is_current(self.frontend),
                               "gitStatusPorcelainSha256": m13.sha_bytes(porcelain.encode()),
                               "dirtyFiles": porcelain.splitlines(), "recordedAt": now(), "codeRoot": str(self.code),
                               "deps": {"present": deps.exists(), "symlink": deps.is_symlink(),
                                        "resolved": str(deps.resolve()) if deps.exists() else None},
                               "harnessSha256": {name: m13.sha_file(self.offscreen / name) for name in (
                                   "tabs-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs")},
                               "runnerSha256": m13.sha_file(Path(__file__))}
        self.save()
        try:
            if "tabs" in self.phases:
                self.start_frontend()
                self.start_backend(runs)
                self.run_tabs()
        finally:
            self.stop_all()
            self.save()
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
    parser.add_argument("--root", required=True, help="fresh QA root (runs/); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m14-acceptance/<label>")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m14-tabs-<YYYYMMDD>)")
    parser.add_argument("--phases", default=DEFAULT_PHASES, help=f"comma list of {PHASES}")
    parser.add_argument("--only", help=f"comma list of steps to (re)run: {ALL_STEPS}; the ledger is then "
                        "partial_not_acceptance and nothing is exported")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return Runner(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
