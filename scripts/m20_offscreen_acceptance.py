#!/usr/bin/env python3
"""Run the M20 mutation candidate offscreen acceptance (spec §12 화면·회귀).

One command, given a code root (default: this repository), builds the frontend when needed (typecheck, then build,
never concurrently), starts its own loopback services (uvicorn 127.0.0.1:8000 with PYTHONPATH=<code root>/backend,
MW_RUNS_DIR=<root>/runs and MW_REFERENCE_DIR=<root>/reference; `next start` on 127.0.0.1:3000), drives the real
Electron offscreen flow frontend/tests/offscreen/mutation-flow.cjs, checks reproducibility over the API and assembles
case-ledger.json.

Sequence (one backend process):
  0. environment        the backend must report methods.mutation_candidates and pocket_detection (real fpocket)
                        available. Missing is an acceptance failure, never "unavailable".
  1. reference-import   scripts/import_reference_snapshots.py --from <kbase> --dest <root>/reference (subprocess);
                        the real .deps/reference is never touched (numbering map + annotation need it).
  2. mutation-main      fresh root: no run → 1MQ4 loaded, not prepared (사용할 수 없음) → 전처리 → ligand shell request
                        without annotation (KLIFS 검사하지 않음, ADP chosen explicitly; positions/distances/MG exclusions
                        vs the T1 oracle) → numbering map + annotation → direct + shell with protection, conflict and
                        release → allowed residues shrunk → same request again (same handle) → real fpocket → pocket
                        source + shell 12 Å → filters/sort/paging → zero candidates (empty scientific result) → server
                        refusals (labeled in-flight alteration) → report + library + downloads → late responses
                        (result switch, run switch) → tab state → wording.
  3. reproducibility    the flow's request without annotation (ADP shell 5.0 Å, defaults) is made twice in each of two
                        fresh runs over the API (upload, load, prepare with the flow's arguments). Handles are run-scoped
                        (obj://<run>/...), so the same handle can only repeat inside one run: each run must return the
                        same handle twice, and the stored contents with every obj:// handle replaced by a placeholder
                        must equal the flow's stored set.
  4. regressions        only with --regressions: the M19, M18, M17, M16, M15, M14 and M13 (all phases) runners, one
                        after another, each with its own fresh --root/--artifacts and --out <out>/../m1X-regression (their
                        own ledgers decide; this ledger records the exit codes and does not depend on them).
Cases the real environment cannot produce are recorded as not observed with the tests that cover them (never forged).
Every step keeps its own directory with ledger-row.json, JSONL rows, screenshots and paint frames; failures are never
deleted or retried away. The ledger's ``acceptance`` is true only when the environment check and the reference import
passed, every step ran in this invocation, every case passed, every flow row measured 0 non-loopback requests and zero
provider calls, the build was stamped from the current frontend source and no worker, fpocket or 8000/3000 listener
remains.

The root must be fresh and outside /tmp; the artifacts folder must be git-ignored. Child processes get an allowlisted
environment (no OPENROUTER_* or other secrets). This script never imports mw; the importer runs as a subprocess.

Usage:
  .venv/bin/python scripts/m20_offscreen_acceptance.py --root runs/m20-acceptance-<date> \\
      --artifacts frontend/tests/offscreen/artifacts/m20-acceptance/<label> --kbase <abs path>/kbase_kinase \\
      [--out docs/qa/m20-mutations-<YYYYMMDD>/acceptance] [--code-root <dir>] [--build auto|always|never] [--regressions]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
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

# The M16 runner (reference import + flow plumbing) and the loopback API helpers of the M18 runner.
import m16_offscreen_acceptance as m16
import m18_offscreen_acceptance as m18

REPO = Path(__file__).resolve().parents[1]
FLOW = "mutation-flow.cjs"
FLOW_STEPS = ["mutation-main"]
MODE_OF = {"mutation-main": "main"}
STRUCTURE = Path("backend/tests/fixtures/public_1mq4.cif")
TOOL = "generate_mutation_candidates"
# Spec §12 화면 cases → the flow modes that observe them.
MAIN_CASES = ["M-no-run", "M-load-prepare", "M-unprepared", "M-ligand-explicit", "M-not-checked", "M-shell-oracle",
              "M-numbering-annotation", "M-reread-on-entry", "M-protect-release", "M-allowed-shrink", "M-same-handle",
              "M-request-controls",
              "M-pocket", "M-tab-state", "M-filters-sort", "M-paging", "M-zero", "M-refused", "M-report",
              "M-late-result", "M-late-run", "M-wording"]
CASE_PLAN: dict[str, list[str]] = {case: ["mutation-main"] for case in MAIN_CASES}
CASE_TEXT = {
    "M-no-run": "fresh root, no run: the protein tab shows 사용할 수 없음 + the no-run reason only (no numbers, no "
                "controls, no mutation reads)",
    "M-load-prepare": "public_1mq4.cif loaded and prepared through the structure screen",
    "M-unprepared": "a run with a loaded but not prepared structure (run A before 전처리, run B): 사용할 수 없음 with the "
                    "reason, no numbers, no controls, no tool call",
    "M-ligand-explicit": "ADP and PO4 offered, none chosen automatically; ligand shell blocked until ADP is chosen; the "
                         "request carries the 7 ADP fields",
    "M-not-checked": "no annotation: the KLIFS 검사하지 않음 notice in the request area; stored and shown check row "
                     "not_checked (annotation_not_given), KLIFS cells — (검사하지 않음), list row status not_checked",
    "M-shell-oracle": "ADP 5.0 Å shell: 20 positions, distances (≤1e-9 Å) and ROUND_HALF_UP cells, MG contact "
                      "exclusions ASN261/ASP274 (MG A2088) equal the T1 numpy oracle; 342 candidates",
    "M-numbering-annotation": "numbering map (지식·보고서, PDB ID 1MQ4) and annotation without contacts (구조 분석) through "
                              "the existing screens; annotated sites equal the T1 list",
    "M-reread-on-entry": "entering the tab re-reads events, pockets, maps, annotations and results (GET only); choosing "
                         "the structure pre-selects the newest annotation and its map",
    "M-protect-release": "protect/release conflict blocked on screen; KLIFS key sites excluded with labels, ASP274 "
                         "KLIFS + metal, LEU139 user protected, ASN261 released (candidate), ARG126 release effect none; "
                         "excluded list = stored",
    "M-allowed-shrink": "allowed A/G/W: request AGW, a new handle, per-position candidate counts and targets",
    "M-same-handle": "the S1 request sent again returns S1's handle and stores nothing new",
    "M-request-controls": "annotation/map selects (the 검사하지 않음 notice follows the annotation choice), metal distance "
                          "5.0 Å → MG contacts in the shell equal the T1 oracle, 빼기 on the direct and protect lists, "
                          "결과 목록 다시 읽기 (GET only)",
    "M-pocket": "real fpocket on the prepared structure (approval), then pocket source with every stored pocket number + "
                "shell 12 Å: pocket positions = union of the stored lining residues",
    "M-tab-state": "the structure screen keeps its prepared source across protein-tab trips",
    "M-filters-sort": "four position filters and the distance sort equal the stored pages (rows without a value last); "
                      "candidate position and target filters",
    "M-paging": "position and candidate pagers (다음/이전) equal the stored pages",
    "M-zero": "zero candidates (ALA A:160, allowed A): 빈 결과 state with the stored exclusion counts, not 실패",
    "M-refused": "labeled in-flight request alterations → the real server refuses structure_invalid, annotation_invalid, "
                 "protect_release_conflict, ligand_required (422); the screen shows the Korean name and code; nothing "
                 "stored",
    "M-report": "보고서 만들기 → 변이 후보 보고서 in the knowledge-tab library; content = stored Markdown with the five "
                "fixed sentences; Markdown/JSON downloads equal the backend bytes",
    "M-late-result": "held detail / position responses of another result released after switching are not applied",
    "M-late-run": "a held run A result-list response released after switching to run B is not applied",
    "M-wording": "no rank/recommendation/effect wording in the panel outside the five fixed sentences",
}
REPRO_CASE = "M-reproducible"
REPRO_TEXT = ("the flow's request without annotation made twice in each of two fresh runs: the same handle twice per run "
              "and the stored content (obj:// handles replaced) equal to the flow's set")
NOT_OBSERVED = {
    "M-map-conflict": "only one numbering map exists per structure in this flow, so the screen's map/annotation "
                      "conflict notice is not reached; covered by frontend/tests/mutations.test.cjs "
                      "(annotationMapConflict) and backend annotation_map_mismatch in backend/tests/test_mutation_tool.py.",
    "M-too-many-positions": "1MQ4 has 261 protein residues, below the 400-position cap; covered by "
                            "backend/tests/test_mutation_tool.py::test_too_many_positions_is_429_and_nothing_is_stored.",
    "M-nonstandard-disulfide": "1MQ4 has no modified-name residue and no SG–SG pair within 2.5 Å (T1 preflight); "
                               "covered by the synthetic fixture tests in backend/tests/test_mutation_candidates.py.",
}
WORKERS = m13.WORKERS
REGRESSIONS = [("m19", []), ("m18", []), ("m17", []), ("m16", ["kbase"]), ("m15", ["kbase"]), ("m14", []),
               ("m13", ["--phases", "workflows,unavailable,regressions,m11,m12,ledger"])]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_ok(environment: dict) -> bool:
    """The backend reported the mutation method and real fpocket pocket detection available."""
    return environment.get("mutationAvailable") is True and environment.get("pocketAvailable") is True


def normalized(value: object) -> object:
    """Every obj:// handle string replaced by a placeholder (handles are run-scoped); every other field unchanged."""
    if isinstance(value, str):
        return "<handle>" if value.startswith("obj://") else value
    if isinstance(value, list):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    return value


def content_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(normalized(value), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def repro_ok(repro: dict | None) -> bool:
    """At least two fresh runs; each returned one handle twice, provider calls zero, and the normalized content equals
    the flow's stored set."""
    if not isinstance(repro, dict):
        return False
    reference, reruns = repro.get("reference"), repro.get("reruns") or []
    if not isinstance(reference, dict) or not reference.get("contentSha256") or len(reruns) < 2:
        return False
    return all(item.get("sameHandle") is True and item.get("providerCallsZero") is True
               and item.get("contentSha256") == reference["contentSha256"] for item in reruns)


def assemble(rows: list[dict], leftovers: list[str], environment: dict, reference: dict,
             repro: dict | None = None) -> dict:
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
             "environment": environment_ok(environment), "reference": m16.reference_ok(reference),
             "leftoverProcesses": not leftovers}
    return {"steps": steps, "cases": cases, "notObserved": dict(NOT_OBSERVED), "verdictParts": parts,
            "passed": all(parts.values())}


def acceptance_ok(passed: bool, build: dict | None) -> bool:
    return passed and bool((build or {}).get("buildCurrentWithSource"))


class Runner(m16.Runner):
    """The M16 runner's protections (fresh root outside /tmp, git-ignored artifacts, free ports, build stamp, mw path
    check, allowlisted env, reference import into the root, leftover check, redacted export) with the M20 flow,
    environment and reproducibility checks and ledger."""

    api = m18.Runner.api
    provider_zero = m18.Runner.provider_zero

    def __init__(self, args: argparse.Namespace) -> None:
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        code = Path(args.code_root).resolve()
        out = args.out or str(code / "docs/qa" / f"m20-mutations-{stamp}" / "acceptance")
        super().__init__(argparse.Namespace(**{**vars(args), "out": out}))
        self.regressions = bool(getattr(args, "regressions", False))
        self.environment: dict = {}
        self.repro: dict | None = None

    def write_row(self, step_dir: Path, row: dict) -> None:
        step_dir.mkdir(parents=True, exist_ok=True)
        base = {"schema": "m20_case_ledger_row@1", "step": step_dir.name,
                "buildId": self.state.get("build", {}).get("buildId"),
                "harness": {"runnerSha256": m13.sha_file(Path(__file__))}, "finishedAt": now(), "artifacts": str(step_dir)}
        (step_dir / "ledger-row.json").write_text(json.dumps({**base, **row}, indent=2) + "\n")

    def capability(self, name: str) -> dict:
        return (self.get_json("/capabilities").get("methods") or {}).get(name) or {}

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

    def command(self, run: str, tool: str, args: dict) -> tuple[int, dict]:
        status, body = self.api("POST", f"/runs/{run}/commands", {"tool": tool, "args": args})
        return status, body if isinstance(body, dict) else {"raw": body}

    def rerun(self, repro: dict) -> dict:
        """The flow's request in a fresh run: upload, load, prepare (the flow's arguments), then the tool twice."""
        _, made = self.api("POST", "/runs", {"goal": "M20 reproducibility check", "context": [], "dry_run": False,
                                            "egress": "local_only"})
        run = made["run_id"]
        status, upload = self.api("POST", f"/runs/{run}/uploads?filename={STRUCTURE.name}",
                                  (self.code / STRUCTURE).read_bytes(), "application/octet-stream")
        if status != 201:
            return {"run": run, "status": f"upload {status}", "detail": upload}
        status, loaded = self.command(run, "load_structure", {"source": upload["upload_id"], **repro["loadArgs"]})
        if not loaded.get("ok"):
            return {"run": run, "status": f"load {status}", "detail": loaded}
        prepare_args = {**repro["prepareArgs"], "structure": loaded["handle"]["handle"]}
        status, prepared = self.command(run, "prepare_structure", prepare_args)
        if not prepared.get("ok"):
            return {"run": run, "status": f"prepare {status}", "detail": prepared}
        args = {**repro["args"], "structure": prepared["handle"]["handle"]}
        handles = []
        for _ in range(2):
            status, body = self.command(run, TOOL, args)
            if not body.get("ok"):
                return {"run": run, "status": f"{TOOL} {status}", "detail": body}
            handles.append(body["handle"]["handle"])
        content = self.stored(run, handles[0])
        return {"run": run, "status": "done", "handles": handles, "sameHandle": handles[0] == handles[1],
                "contentSha256": content_sha(content), "candidates": content["counts"]["candidates"],
                "providerCallsZero": self.provider_zero(run)}

    def reproducibility(self, row: dict | None) -> None:
        repro = (row or {}).get("repro") or {}
        if not (repro.get("run") and repro.get("flowSet") and repro.get("args") and repro.get("prepareArgs")):
            self.repro = {"error": "the main flow did not record its request without annotation"}
            self.record("reproducibility", "fail", reason=self.repro["error"])
            return
        content = self.stored(repro["run"], repro["flowSet"])
        reference = {"run": repro["run"], "handle": repro["flowSet"], "contentSha256": content_sha(content),
                     "candidates": content["counts"]["candidates"]}
        reruns = [self.rerun(repro) for _ in range(2)]
        self.repro = {"flowArgs": repro["args"], "reference": reference, "reruns": reruns}
        (self.artifacts / "reproducibility.json").write_text(json.dumps(self.repro, indent=2) + "\n")
        self.record("reproducibility", "pass" if repro_ok(self.repro) else "fail",
                    contentSha256=reference["contentSha256"],
                    reruns=[{k: item.get(k) for k in ("run", "status", "sameHandle", "contentSha256")} for item in reruns])

    def run_flows(self) -> None:
        mutation = self.capability("mutation_candidates")
        pocket = self.capability("pocket_detection")
        self.environment.update({"mutationAvailable": mutation.get("available") is True,
                                 "pocketAvailable": pocket.get("available") is True,
                                 "pocketCapability": {k: pocket.get(k) for k in ("available", "status", "engine", "release",
                                                                                 "build")}})
        ready = environment_ok(self.environment)
        self.record("environment-capability", "pass" if ready else "fail",
                    mutation={k: mutation.get(k) for k in ("available", "reason_code")},
                    pocket=self.environment["pocketCapability"])
        served = self.get_json("/reference/snapshots")
        self.state["emptyReference"] = {k: served.get(k) for k in ("available", "reason_code", "reason")}
        set_hash = self.import_real()
        if not ready:
            self.missing_prerequisite("mutation-main", "backend reports mutation_candidates or pocket_detection unavailable")
            self.repro = {"error": "not run: environment unavailable"}
        elif not set_hash:
            self.missing_prerequisite("mutation-main", "reference-import failed")
            self.repro = {"error": "not run: reference import failed"}
        else:
            row = self.flow("mutation-main", MODE_OF["mutation-main"], ["--set-hash", set_hash])
            self.reproducibility(row)

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
                         "controls": row.get("controls", {}), "setHash": row.get("setHash"),
                         "externalRequestCount": row.get("externalRequestCount"),
                         "providerCallsZero": row.get("providerCallsZero"), "partFailures": row.get("partFailures", []),
                         "error": row.get("error"), "artifacts": row.get("artifacts"), "finishedAt": row.get("finishedAt")})
        judged = assemble(rows, leftovers, self.environment, self.reference_steps, self.repro)
        passed = judged["passed"]
        ledger = {"schema": "m20_case_ledger@1", "generatedAt": now(), "build": self.state.get("build"),
                  "verdict": "pass" if passed else "fail",
                  "acceptance": acceptance_ok(passed, self.state.get("build")),
                  "verdictParts": judged["verdictParts"], "cases": judged["cases"], "steps": judged["steps"],
                  "notObserved": judged["notObserved"], "reproducibility": self.repro,
                  "environment": self.environment,
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
        env = ledger["environment"]
        change = ledger["reference"]["changes"].get("reference-import") or {}
        lines = ["# M20 변이 후보 오프스크린 수락 QA 증거", "",
                 (f"- 생성: {ledger['generatedAt']} · verdict **{ledger['verdict']}** · acceptance "
                  f"**{str(ledger['acceptance']).lower()}**"),
                 f"- 빌드: {json.dumps(ledger.get('build'), ensure_ascii=False)}",
                 (f"- 환경: mutation_candidates {'사용 가능' if env.get('mutationAvailable') else '사용 불가'} · "
                  f"fpocket 포켓 검출 {'사용 가능' if env.get('pocketAvailable') else '사용 불가'}"),
                 f"- 참조 스냅샷: 격리 폴더에 실제 kbase 가져오기 `{change.get('setHash')}`",
                 f"- 남은 프로세스/포트: {ledger['leftoverProcesses'] or '없음'}",
                 f"- 비-loopback 요청 합계: {ledger['externalRequestsTotal']}", "",
                 ("스크린숏·paint 프레임·다운로드 원본은 Git 제외 artifacts 폴더에 있고 여기에는 `binary-artifacts.json`의 "
                  "SHA-256만 기록한다. 절대 경로는 `<repo>`/`<home>`으로 바꿨다. 실패한 시도의 증거도 그대로 남긴다."), "",
                 ("재현 검사: handle은 run마다 다르다(obj://<run>/…). 그래서 새 run 두 개에서 흐름의 주석 없는 요청을 각각 두 번 "
                  "보내 run 안에서 같은 handle인지, 저장 내용(obj:// handle만 자리표시로 바꿈)이 흐름의 결과와 같은지 본다. "
                  "흐름 안에서는 같은 요청을 다시 보내 같은 handle을 받는다(사례 M-same-handle)."), "",
                 "## 사례", "", "| 사례 | 내용 | 결과 | 모드 |", "|---|---|---|---|"]
        for case, value in ledger["cases"].items():
            modes = ", ".join(f"{k}:{v}" for k, v in value.get("modes", {}).items())
            lines.append(f"| {case} | {value['text']} | {value['status']} | {modes} |")
        lines += ["", "## 관찰하지 않은 사례", ""]
        lines += [f"- {case}: {reason}" for case, reason in ledger["notObserved"].items()]
        lines += ["", "## 단계", "", "| 단계 | 결과 | 문제 |", "|---|---|---|"]
        for step, value in ledger["steps"].items():
            lines.append(f"| {step} | {value['status']} | {'; '.join(value.get('problems', []))} |")
        lines.append(f"| reference-import | {change.get('status')} | {change.get('problem', '')} |")
        lines += ["", "## 다시 실행하는 명령 (프로젝트 루트, 8000·3000 포트 비움)", "", "```bash",
                  ".venv/bin/python scripts/m20_offscreen_acceptance.py --root runs/m20-acceptance-<date> \\",
                  "    --artifacts frontend/tests/offscreen/artifacts/m20-acceptance/<label> --kbase <abs>/kbase_kinase \\",
                  "    --out docs/qa/m20-mutations-<YYYYMMDD>/acceptance [--regressions]",
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
    parser.add_argument("--root", required=True, help="fresh QA root (runs/ and reference/ are created inside); not /tmp")
    parser.add_argument("--artifacts", required=True, help="git-ignored evidence dir, e.g. "
                        "frontend/tests/offscreen/artifacts/m20-acceptance/<label>")
    parser.add_argument("--kbase", default=str(REPO.parent / "kbase_kinase"),
                        help="local kbase_kinase checkout (read only; default: <repo>/../kbase_kinase; give an absolute "
                        "path in a git worktree); also passed to the M16 and M15 regressions")
    parser.add_argument("--out", help="committed text evidence folder (default "
                        "docs/qa/m20-mutations-<YYYYMMDD>/acceptance)")
    parser.add_argument("--code-root", default=str(REPO), help="code root the services and harness are started from")
    parser.add_argument("--build", choices=["auto", "always", "never"], default="auto",
                        help="auto: typecheck then build unless frontend/.next/BUILD_ID was stamped by a runner "
                        "from the current frontend source (app/, src/, config and package files)")
    parser.add_argument("--regressions", action="store_true", help="afterwards run the M19, M18, M17, M16, M15, M14 "
                        "and M13 (all phases) runners, each with its own fresh root, artifacts and out folder")
    return parser


def main() -> int:
    return Runner(build_parser().parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
