#!/usr/bin/env python3
"""Run the M15 residue numbering offscreen acceptance (spec §10.4).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend,
MW_RUNS_DIR=<root>/runs and MW_REFERENCE_DIR=<root>/reference; `next start` on 127.0.0.1:3000), drives the real
Electron offscreen flow frontend/tests/offscreen/numbering-flow.cjs mode by mode, and assembles case-ledger.json.

Sequence (one backend process; the reference folder is changed underneath it, the backend pins it per request):
  1. numbering-empty   <root>/reference is empty: 사용할 수 없음 + reason, no numbers, no run control.
  2. reference-import  scripts/import_reference_snapshots.py --from <kbase> --dest <root>/reference (subprocess).
  3. numbering-main    confirmed PDB ID + SIFTS prefill (cross-check, rows, KLIFS numbers vs the committed KLIFS
                       match_residues fixture for 1MQ4:A, status filter, S388 conflict), accession without PDB ID,
                       wrong accession (below identity), prepared structure, report + download hashes, labeled read
                       failure + 다시 시도, run switch + held late response.
  4. reference-reimport a MARKED fixture set (backend/tests/reference_fixture_set.py, committed fixture rows, tag in
                       imported_at) is activated in <root>/reference: a different set hash (subprocess).
  5. numbering-stale   the main mode's maps show 이전 스냅샷 기준.
Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never
deleted or retried away. The ledger's ``acceptance`` is true only when every step ran in this invocation, both
reference changes succeeded, every case passed, every flow row measured 0 non-loopback requests and zero provider
calls, the build was stamped from the current frontend source and no worker process or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw; the importer and the fixture-set builder
run as subprocesses.

Usage:
  .venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/<label> --kbase ../kbase_kinase \\
      [--out docs/qa/m15-numbering-<YYYYMMDD>] [--code-root <dir>] [--build auto|always|never]
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
FLOW_STEPS = ["numbering-empty", "numbering-main", "numbering-stale"]
REFERENCE_STEPS = ["reference-import", "reference-reimport"]
STEP_TIMEOUT_S = 2400
MARKER_PREFIX = "m15-qa-marked-fixture"
# Spec §10.4 cases → the flow modes that observe them.
CASE_PLAN: dict[str, list[str]] = {
    "N-no-snapshot": ["numbering-empty"],
    "N-confirmed-sifts": ["numbering-main"], "N-klifs-oracle": ["numbering-main"], "N-status-filter": ["numbering-main"],
    "N-conflict-row": ["numbering-main"], "N-alignment-only": ["numbering-main"], "N-below-identity": ["numbering-main"],
    "N-prepared": ["numbering-main"], "N-report": ["numbering-main"], "N-read-retry": ["numbering-main"],
    "N-run-switch": ["numbering-main"], "N-late-response": ["numbering-main"], "N-stale": ["numbering-stale"],
}
CASE_TEXT = {
    "N-no-snapshot": "no snapshot: 사용할 수 없음 and reason, import command; no numbers, no run control",
    "N-confirmed-sifts": "1MQ4 uploaded, PDB ID suggestion confirmed → SIFTS accession prefilled → run → chain A "
                         "cross-checked, rows table equals the stored rows",
    "N-klifs-oracle": "KLIFS numbers on screen equal the KLIFS match_residues table of 1MQ4:A (author number → KLIFS "
                      "position; GK.45/hinge/xDFG residues required)",
    "N-status-filter": "status filter (충돌/대응됨/대응 없음/전체) changes the count text; total kept",
    "N-conflict-row": "S388 row shows 충돌 (one_method_only) with both answers",
    "N-alignment-only": "accession picked without confirming the PDB ID → 교차 확인 없음 marker; S388 대응 없음",
    "N-below-identity": "another kinase accession → chain unmapped below identity; 대응된 잔기 없음 (scientific_null)",
    "N-prepared": "prepared structure (structure-tab 전처리) → map with mapped rows",
    "N-report": "보고서 만들기 → 잔기 번호 대응 보고서 in the report list; download SHA-256 equal the backend bytes",
    "N-read-retry": "labeled read failure (snapshots, map list) → failure state with 다시 시도 → recovers",
    "N-run-switch": "after a run switch the numbering panel shows only the new run's maps",
    "N-late-response": "a held map-list response of the previous run released after the switch is not applied",
    "N-stale": "after a different (marked fixture) set is activated, earlier maps show 이전 스냅샷 기준",
}
WORKERS = m13.WORKERS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reference_ok(reference: dict) -> bool:
    """Both reference changes ran, produced set hashes, the backend served them, and the two hashes differ."""
    first, second = reference.get("reference-import") or {}, reference.get("reference-reimport") or {}
    return (first.get("status") == "pass" and second.get("status") == "pass" and bool(first.get("setHash"))
            and bool(second.get("setHash")) and first["setHash"] != second["setHash"])


def assemble(rows: list[dict], leftovers: list[str], reference: dict) -> dict:
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
             "reference": reference_ok(reference), "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "verdictParts": parts, "passed": all(parts.values())}


def acceptance_ok(passed: bool, build: dict | None) -> bool:
    return passed and bool((build or {}).get("buildCurrentWithSource"))


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.code = Path(args.code_root).resolve()
        self.frontend = self.code / "frontend"
        self.offscreen = self.frontend / "tests/offscreen"
        venv = self.code / ".venv/bin/python"
        # The code root's venv, else the interpreter running this runner (e.g. the main checkout's .venv).
        self.python = venv if venv.exists() else Path(sys.executable)
        self.root = Path(args.root).resolve()
        self.runs = self.root / "runs"
        self.reference = self.root / "reference"
        self.artifacts = Path(args.artifacts).resolve()
        self.kbase = Path(args.kbase).resolve()
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        self.out = Path(args.out).resolve() if args.out else self.code / "docs/qa" / f"m15-numbering-{stamp}"
        self.build_mode = args.build
        self.state_file = self.artifacts / "runner-state.json"
        self.state: dict = {}
        self.services: dict[str, subprocess.Popen] = {}
        self.summary: list[dict] = []
        self.reference_steps: dict[str, dict] = {}
        for bad in ("/tmp", "/private/tmp"):
            for path in (self.root, self.artifacts, self.out):
                if str(path) == bad or str(path).startswith(bad + "/"):
                    raise SystemExit("QA roots and evidence folders must not be under /tmp")
        if self.root in (self.code / "runs", REPO / "runs"):
            raise SystemExit("--root must be a fresh folder, not the repository runs/ folder itself")
        ignored = subprocess.run(["git", "check-ignore", "-q", str(self.artifacts / "x")], cwd=self.code, check=False)
        if ignored.returncode != 0:
            raise SystemExit(f"--artifacts must be git-ignored: {self.artifacts}")
        if not (self.kbase / "ref" / "manifest.json").is_file():
            raise SystemExit(f"--kbase has no ref/manifest.json: {self.kbase}")

    # ----- bookkeeping -------------------------------------------------------------------------
    def save(self) -> None:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2) + "\n")

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
        base = {"schema": "m15_case_ledger_row@1", "step": step_dir.name,
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

    def start_backend(self) -> None:
        env = m13.child_env({"PYTHONPATH": str(self.code / "backend"), "MW_RUNS_DIR": str(self.runs),
                             "MW_REFERENCE_DIR": str(self.reference)})
        probe = subprocess.run([str(self.python), "-c", "import mw;print(mw.__file__)"], env=env, cwd=self.code,
                               capture_output=True, text=True, check=True)
        if not probe.stdout.strip().startswith(str(self.code / "backend")):
            raise RuntimeError(f"backend import resolved outside {self.code}: {probe.stdout}")
        log = self.artifacts / "services" / "backend.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        self.services["backend"] = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "mw.api.app:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=self.code, env=env, stdout=log.open("a"), stderr=subprocess.STDOUT, start_new_session=True)
        self.wait_http(f"{API}/capabilities")
        self.state.setdefault("services", []).append({"name": "backend", "runs": str(self.runs),
                                                      "reference": str(self.reference), "code": str(self.code),
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
        with urllib.request.urlopen(API + path, timeout=300) as response:
            return json.loads(response.read())

    # ----- reference folder changes (subprocesses; this runner never imports mw) ----------------
    def reference_change(self, step: str, argv: list[str]) -> str | None:
        log = self.artifacts / "services" / f"{step}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(argv, cwd=self.code, env=m13.child_env(), capture_output=True, text=True, timeout=900,
                              check=False)
        log.write_text(json.dumps({"argv": argv, "exitCode": proc.returncode}) + "\n" + proc.stdout + proc.stderr)
        entry: dict = {"status": "fail", "exitCode": proc.returncode, "argv": argv, "log": str(log)}
        set_hash = None
        if proc.returncode == 0:
            try:
                set_hash = json.loads(proc.stdout)["set_hash"]
            except (ValueError, KeyError, TypeError):
                set_hash = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
        if set_hash:
            served = self.get_json("/reference/snapshots")
            entry.update({"setHash": set_hash, "served": {k: served.get(k) for k in (
                "available", "set_hash", "imported_at", "reason_code")},
                "sources": [{k: s.get(k) for k in ("source", "snapshot_id", "date", "license", "origin")}
                            for s in served.get("sources", [])]})
            if served.get("available") is True and served.get("set_hash") == set_hash:
                entry["status"] = "pass"
            else:
                entry["problem"] = "backend does not serve the new active set"
        self.reference_steps[step] = entry
        self.state["reference"] = self.reference_steps
        self.record(step, entry["status"], setHash=set_hash, exitCode=proc.returncode)
        self.save()
        return set_hash if entry["status"] == "pass" else None

    def import_real(self) -> str | None:
        return self.reference_change("reference-import", [
            str(self.python), str(self.code / "scripts/import_reference_snapshots.py"),
            "--from", str(self.kbase), "--dest", str(self.reference)])

    def activate_marked_fixture(self, marker: str) -> str | None:
        script = ("import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                  "from reference_fixture_set import build_fixture_set; "
                  "print(build_fixture_set(Path(sys.argv[2]), tag=sys.argv[3]))")
        return self.reference_change("reference-reimport", [
            str(self.python), "-c", script, str(self.code / "backend/tests"), str(self.reference), marker])

    # ----- flow steps --------------------------------------------------------------------------
    def flow(self, step: str, mode: str, extra: list[str]) -> dict | None:
        step_dir = self.fresh_dir(step)
        argv = ["node", str(self.offscreen / "numbering-flow.cjs"), "--url", WEB, "--mode", mode,
                "--artifacts", str(step_dir), *extra]
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
        served = self.get_json("/reference/snapshots")
        self.state["emptyReference"] = {k: served.get(k) for k in ("available", "reason_code", "reason")}
        self.flow("numbering-empty", "empty", [])
        first = self.import_real()
        if not first:
            for step in ("numbering-main", "numbering-stale"):
                self.missing_prerequisite(step, "reference-import failed")
            return
        main = self.flow("numbering-main", "main", ["--set-hash", first]) or {}
        runs = [run for run in ((main.get("runs") or {}).get("A"), (main.get("runs") or {}).get("B")) if run]
        marker = f"{MARKER_PREFIX}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        second = self.activate_marked_fixture(marker)
        if not second or not runs:
            self.missing_prerequisite("numbering-stale", "reference-reimport failed" if not second
                                      else "numbering-main recorded no run")
            return
        self.flow("numbering-stale", "stale", ["--set-hash", second, "--previous-set-hash", first,
                                               "--runs", ",".join(runs), "--marker", marker])

    # ----- ledger and evidence -----------------------------------------------------------------
    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "status": row.get("status"),
                         "cases": row.get("cases") or {}, "runs": row.get("runs"), "runId": row.get("runId"),
                         "evidenceKind": row.get("evidenceKind"), "handles": row.get("handles", {}),
                         "inputs": row.get("inputs", []), "fixtureLabels": row.get("fixtureLabels", []),
                         "setHash": row.get("setHash"), "previousSetHash": row.get("previousSetHash"),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.reference_steps)
        passed = judged["passed"]
        ledger = {"schema": "m15_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "reference": {"kbase": str(self.kbase), "folder": str(self.reference),
                                "emptyAtStart": self.state.get("emptyReference"), "changes": self.reference_steps},
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
        changes = ledger["reference"]["changes"]
        lines = ["# M15 잔기 번호 대응 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 참조 스냅샷: 빈 폴더로 시작 → 실제 kbase 가져오기 "
                  f"`{(changes.get('reference-import') or {}).get('setHash')}` → 표시된 fixture 세트 "
                  f"`{(changes.get('reference-reimport') or {}).get('setHash')}`"),
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
        for step, value in changes.items():
            lines.append(f"| {step} | {value.get('status')} | {value.get('problem', '')} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m15_offscreen_acceptance.py --root runs/m15-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m15-acceptance/<label> --kbase ../kbase_kinase \\",
                  "    --out docs/qa/m15-numbering-<YYYYMMDD>",
                  "```"]
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
                                   "numbering-flow.cjs", "driver.cjs", "main.cjs", "normal-flow.cjs")},
                               "runnerSha256": m13.sha_file(Path(__file__))}
        self.save()
        self.runs.mkdir(parents=True, exist_ok=True)
        self.reference.mkdir(parents=True, exist_ok=True)
        try:
            self.start_frontend()
            self.start_backend()
            self.run_flows()
        finally:
            self.stop_all()
            self.save()
        left = self.leftovers()
        self.record("leftover-processes", "pass" if not left else "fail", processes=left)
        ledger = self.ledger(left)
        self.export(ledger)
        failed = [entry["step"] for entry in self.summary if entry["status"] == "fail"]
        print(json.dumps({"failedSteps": failed, "acceptance": ledger["acceptance"], "artifacts": str(self.artifacts)}),
              flush=True)
        return 1 if failed or not ledger["acceptance"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", required=True, help="fresh QA root (runs/ and reference/ are created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m15-acceptance/<label>")
    parser.add_argument("--kbase", default=str(REPO.parent / "kbase_kinase"),
                        help="local kbase_kinase checkout (read only; default: <repo>/../kbase_kinase)")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m15-numbering-<YYYYMMDD>)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return Runner(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
