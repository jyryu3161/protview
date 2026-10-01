#!/usr/bin/env python3
"""Run the M16 reference site annotation offscreen acceptance (spec §10.4).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend,
MW_RUNS_DIR=<root>/runs and MW_REFERENCE_DIR=<root>/reference; `next start` on 127.0.0.1:3000), drives the real
Electron offscreen flow frontend/tests/offscreen/annotation-flow.cjs mode by mode, and assembles case-ledger.json.

Sequence (one backend process):
  1. reference-import   scripts/import_reference_snapshots.py --from <kbase> --dest <root>/reference (subprocess);
                        the real .deps/reference is never touched.
  2. annotation-main    1MQ4 → 전처리 → ADP 기하 접촉 → prepared-structure numbering map (PDB ID 1MQ4 confirmed) →
                        panel create/show, Mol* readback vs the T1 oracle, viewer_scene@2 / viewer_figure@2 with and
                        without legend, viewer_scene@1 unchanged, PNG pixels, @2 restore, M8 block, report + library +
                        downloads, annotation without contacts, pocket overlay and M10 comparison exclusivity, labeled
                        read failures + retry, run switch + held late response.
  3. annotation-minimized  public 1UBQ → OpenMM minimization → minimized source shows only the unavailable reason.
Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never
deleted or retried away. The ledger's ``acceptance`` is true only when every step ran in this invocation, the
reference import succeeded, every case passed, every flow row measured 0 non-loopback requests and zero provider
calls, the build was stamped from the current frontend source and no worker process or 8000/3000 listener remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw; the importer runs as a subprocess.

Usage:
  .venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/<label> --kbase ../kbase_kinase \\
      [--out docs/qa/m16-annotations-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Shared build stamp, env allowlist, port and redaction helpers of the M13 runner.
import m13_offscreen_acceptance as m13

# Services, build, reference import, bookkeeping and evidence export of the M15 runner.
import m15_offscreen_acceptance as m15

REPO = Path(__file__).resolve().parents[1]
FLOW = "annotation-flow.cjs"
FLOW_STEPS = ["annotation-main", "annotation-minimized"]
MODE_OF = {"annotation-main": "main", "annotation-minimized": "minimized"}
# Spec §10.4 cases → the flow modes that observe them.
CASE_PLAN: dict[str, list[str]] = {
    "A-load-prepare-contacts": ["annotation-main"], "A-numbering-prepared": ["annotation-main"],
    "A-panel-create": ["annotation-main"], "A-site-table": ["annotation-main"], "A-show-readback": ["annotation-main"],
    "A-figure-legend": ["annotation-main"], "A-figure-no-legend": ["annotation-main"],
    "A-figure-pixels": ["annotation-main"], "A-scene-v1-unchanged": ["annotation-main"],
    "A-restore-redraw": ["annotation-main"], "A-blocked-m8": ["annotation-main"], "A-report": ["annotation-main"],
    "A-no-contacts": ["annotation-main"], "A-blocked-pocket": ["annotation-main"],
    "A-blocked-comparison": ["annotation-main"], "A-run-switch-late": ["annotation-main"],
    "A-read-retry": ["annotation-main"], "B-minimized": ["annotation-minimized"],
}
CASE_TEXT = {
    "A-load-prepare-contacts": "public_1mq4.cif loaded, 전처리, 기하 접촉 with the ADP instance chosen explicitly "
                               "(7 fields equal the T1 preflight ligand; PO4 also offered)",
    "A-numbering-prepared": "지식·보고서: numbering map on the prepared structure with PDB ID 1MQ4 confirmed",
    "A-panel-create": "panel lists only same-structure maps and contact results, chooses nothing automatically; "
                      "map + ADP contacts → 주석 만들기 (annotate_reference_sites)",
    "A-site-table": "site table labels/status/counts/min distance equal the stored annotation and the T1 numpy oracle; "
                    "computed zero shown as 0, no contact within cutoff shown as text",
    "A-show-readback": "Mol* readback: 10 sites, labels equal display_labels (Glu211 (hinge.46)), lines equal the 10 T1 "
                       "polar pairs between the exact catalog atoms, distance labels ROUND_HALF_UP, 0 undrawn",
    "A-figure-legend": "viewer_scene@2 (legend on) + viewer_figure@2 molstar_image_pass+legend; PNG/JSON download "
                       "bytes equal the backend; legend pixels only in the lower-left box",
    "A-figure-no-legend": "legend unticked → redraw → viewer_scene@2 legend false → figure capture molstar_image_pass",
    "A-figure-pixels": "same camera: annotation-on vs annotation-off PNG differ; polar line colour only with annotation",
    "A-scene-v1-unchanged": "annotation off → viewer_scene@1 body without annotation key, viewer_figure@1",
    "A-restore-redraw": "annotation off, restore the @2 view → stored annotation redrawn (no tool call)",
    "A-blocked-m8": "annotation shown: natural-language request blocked with reason, nothing sent; /zoom in works",
    "A-report": "보고서 만들기 → 참조 주석 보고서 in the knowledge-tab library; downloads equal the backend bytes",
    "A-no-contacts": "접촉 결과 없이 → annotation with contacts null; 접촉 결과 없음 cells, 0 lines",
    "A-blocked-pocket": "annotation on blocks the pocket overlay (reason); overlay on blocks the annotation and refuses "
                        "the @2 restore without clearing the overlay",
    "A-blocked-comparison": "M10 comparison start turns the annotation off; it cannot be turned on; @2 restore refused",
    "A-run-switch-late": "run switch turns the annotation off; a held run A annotation-list response is not applied",
    "A-read-retry": "labeled read failures (map list, annotation list, detail) → 다시 읽기 controls recover",
    "B-minimized": "OpenMM-minimized 1UBQ source: only the unavailable reason, no numbers or controls",
}
WORKERS = m13.WORKERS


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reference_ok(reference: dict) -> bool:
    """The reference import ran, produced a set hash and the backend served it."""
    entry = reference.get("reference-import") or {}
    return entry.get("status") == "pass" and bool(entry.get("setHash"))


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


class Runner(m15.Runner):
    """The M15 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw
    path check, allowlisted env, leftover check, redacted export) with the M16 flow, cases and ledger."""

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(args)
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        self.out = (Path(args.out).resolve() if args.out
                    else self.code / "docs/qa" / f"m16-annotations-{stamp}" / "acceptance")
        for bad in ("/tmp", "/private/tmp"):
            if str(self.out) == bad or str(self.out).startswith(bad + "/"):
                raise SystemExit("QA roots and evidence folders must not be under /tmp")

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m16_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

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
        served = self.get_json("/reference/snapshots")
        self.state["emptyReference"] = {k: served.get(k) for k in ("available", "reason_code", "reason")}
        set_hash = self.import_real()
        if not set_hash:
            self.missing_prerequisite("annotation-main", "reference-import failed")
        else:
            self.flow("annotation-main", MODE_OF["annotation-main"], ["--set-hash", set_hash])
        self.flow("annotation-minimized", MODE_OF["annotation-minimized"], [])

    def ledger(self, leftovers: list[str]) -> dict:
        rows = []
        for row_file in sorted(self.artifacts.glob("*/ledger-row.json")):
            row = json.loads(row_file.read_text())
            rows.append({"step": row_file.parent.name, "mode": row.get("mode"), "status": row.get("status"),
                         "cases": row.get("cases") or {}, "runs": row.get("runs"), "runId": row.get("runId"),
                         "evidenceKind": row.get("evidenceKind"), "handles": row.get("handles", {}),
                         "inputs": row.get("inputs", []), "fixtureLabels": row.get("fixtureLabels", []),
                         "controls": row.get("controls", {}), "setHash": row.get("setHash"),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.reference_steps)
        passed = judged["passed"]
        ledger = {"schema": "m16_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
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
        change = ledger["reference"]["changes"].get("reference-import") or {}
        lines = ["# M16 참조 주석 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 f"- 참조 스냅샷: 격리 폴더에 실제 kbase 가져오기 `{change.get('setHash')}`",
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·PNG·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 "## 사례", "", "| 사례 | 내용 | 결과 | 모드 |", "|---|---|---|---|"]
        for case, value in ledger["cases"].items():
            modes = ", ".join(f"{k}:{v}" for k, v in value.get("modes", {}).items())
            lines.append(f"| {case} | {value['text']} | {value['status']} | {modes} |")
        lines += ["", "## 단계", "", "| 단계 | 결과 | 문제 |", "|---|---|---|"]
        for step, value in ledger["steps"].items():
            lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
        lines.append(f"| reference-import | {change.get('status')} | {change.get('problem', '')} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m16_offscreen_acceptance.py --root runs/m16-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m16-acceptance/<label> --kbase ../kbase_kinase \\",
                  "    --out docs/qa/m16-annotations-<YYYYMMDD>/acceptance",
                  "```"]
        return "\n".join(lines) + "\n"

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
                                   FLOW, "driver.cjs", "main.cjs", "normal-flow.cjs")},
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
                        "frontend/tests/offscreen/artifacts/m16-acceptance/<label>")
    parser.add_argument("--kbase", default=str(REPO.parent / "kbase_kinase"),
                        help="local kbase_kinase checkout (read only; default: <repo>/../kbase_kinase)")
    parser.add_argument("--out", help="committed text evidence folder (default docs/qa/m16-annotations-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    return Runner(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
