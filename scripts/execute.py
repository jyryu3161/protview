#!/usr/bin/env python3
"""Phase executor: Sol implementation, executable acceptance checks, Astra review.

The runner never stages, commits, changes branches, or pushes. External reviews
can be attached with --record-review; --verify checks their file hashes and
re-runs acceptance commands without invoking an implementation model.
"""

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
from datetime import datetime, timezone
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTER_MODEL = "gpt-6-sol"
REVIEWER_MODEL = "gpt-6-astra"
MAX_ATTEMPTS = 3
TIMEOUT = 1800
VERDICT = re.compile(r"(?im)^\s*Verdict:\s*APPROVED\s*$")
HOOKS_MANIFEST_SHA256 = "af545f44ce86f88396bf1aff99d37183af016a48e365bf1d1899a7f8bb192486"
PRE_TOOL_GUARD_SHA256 = "7d93902bb1a7a6fe34fc293ff5e0ba6110ea047dfe85e33f71d4fb9685ebf0f6"
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
RUNTIME_DIAGNOSTIC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\s+"
    r"(?:ERROR|WARN|WARNING)\s+(?P<target>[\w.:-]+):\s*(?P<body>.*)$",
    re.IGNORECASE,
)
STANDALONE_DIAGNOSTIC = re.compile(r"^(?:Warning|WARN|Error):\s*(?P<body>.*)$", re.IGNORECASE)
HOOK_DIAGNOSTIC_TARGET = re.compile(r"(?:^|::)(?:hooks?|trust|startup|config)(?:$|::)", re.IGNORECASE)
HOOK_DIAGNOSTIC_BODY = re.compile(
    r"^(?:(?:warning|warn|error):\s*)?(?:(?:project|workspace)\s+)?"
    r"(?:hooks?\b|skipped\b|untrusted\b|trust\b)",
    re.IGNORECASE,
)
HOOK_TRUST_DIAGNOSTIC = re.compile(
    r"(?im)^(?:"
    r"(?=.*\bhooks?\b)(?=.*(?:\buntrusted\b|\bnot trusted\b|"
    r"\b(?:need|needs|require|requires)\b.{0,30}\btrust\b|"
    r"\btrust\b.{0,30}\b(?:required|review)\b)).*|"
    r".*\bhooks?\b(?:[ \t]+\w+){0,2}[ \t]+skipped\b.*|"
    r".*\bskipped\b(?:[ \t]+\w+){0,2}[ \t]+hooks?\b.*)"
)


def has_hook_trust_diagnostic(stderr):
    """Inspect runtime diagnostic headers, never multiline tool/source output."""
    for line in ANSI_ESCAPE.sub("", stderr).splitlines():
        runtime = RUNTIME_DIAGNOSTIC.match(line)
        if runtime:
            target, body = runtime.group("target", "body")
            if re.search(r"(?:^|::)tools(?:::|$)", target, re.IGNORECASE):
                continue
            if not (HOOK_DIAGNOSTIC_TARGET.search(target) or HOOK_DIAGNOSTIC_BODY.match(body)):
                continue
        else:
            standalone = STANDALONE_DIAGNOSTIC.match(line)
            if not standalone:
                continue
            body = standalone.group("body")
        if HOOK_TRUST_DIAGNOSTIC.search(body):
            return True
    return False


def check_codex_result(result, model):
    """Accept a completed JSONL turn only after checking runtime diagnostics."""
    stderr = ANSI_ESCAPE.sub("", result.stderr)
    if has_hook_trust_diagnostic(result.stderr):
        raise ValueError("Codex skipped or did not trust project hooks; inspect /hooks in Codex CLI")
    if result.returncode:
        raise ValueError(f"Codex {model} failed ({result.returncode}): {stderr[-1000:]}")
    thread_started = turn_started = turn_completed = False
    for number, line in enumerate(result.stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Codex {model} emitted malformed JSONL at line {number}") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise ValueError(f"Codex {model} emitted malformed JSONL at line {number}")  # noqa: TRY004
        kind = event["type"]
        if kind == "thread.started":
            thread_started = True
        elif kind == "turn.started":
            if not thread_started or turn_started:
                raise ValueError(f"Codex {model} emitted an out-of-order turn at line {number}")
            turn_started = True
            turn_completed = False
        elif kind in {"turn.failed", "error"}:
            detail = event.get("message")
            if not isinstance(detail, str):
                error = event.get("error")
                detail = error.get("message") if isinstance(error, dict) else None
            raise ValueError(f"Codex {model} reported {kind}: {detail or 'no detail'}")
        elif kind == "turn.completed":
            if not turn_started:
                raise ValueError(f"Codex {model} emitted an out-of-order completion at line {number}")
            turn_started = False
            turn_completed = True
        # item.* contains untrusted agent and tool text, not CLI diagnostics.
    if not (thread_started and turn_completed and not turn_started):
        raise ValueError(f"Codex {model} JSONL ended without a completed turn")


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def project_file(path):
    path = path.resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError(f"Expected a project file: {path}")
    if any(part == "references" or part == ".venv" or part.startswith(".env") for part in path.relative_to(ROOT.resolve()).parts):
        raise ValueError(f"Review evidence cannot include private or reference files: {path}")
    return path


def project_rel(path):
    return project_file(path).relative_to(ROOT.resolve()).as_posix()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checks_hash(checks):
    encoded = json.dumps(checks, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_supervised(command, *, input_text=None, timeout=TIMEOUT):
    """Kill and reap the whole process group when a command exceeds its limit."""
    process = subprocess.Popen(
        command, cwd=ROOT, stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        deadline = time.monotonic() + 1
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        time.sleep(max(0, deadline - time.monotonic()))
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def checks_for(step):
    checks = step.get("acceptance_checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError(f"Step {step.get('step')}: acceptance_checks must be nonempty")
    for command in checks:
        if not isinstance(command, list) or not command or any(not isinstance(x, str) or not x for x in command):
            raise ValueError(f"Step {step['step']}: each check must be an argv list")
        if command[0] in {"sh", "bash", "zsh", "sudo"}:
            raise ValueError(f"Step {step['step']}: shell and sudo checks are unsupported")
    return checks


class StepExecutor:
    def __init__(self, name):
        if Path(name).name != name or name in {".", ".."}:
            raise ValueError("Phase must be a directory name under phases/")
        self.name = name
        self.directory = ROOT / "phases" / name
        self.index_path = self.directory / "index.json"
        self.top_path = ROOT / "phases" / "index.json"
        if not self.index_path.is_file():
            raise ValueError(f"Missing phase index: {self.index_path}")
        self.validate()

    def index(self):
        return read_json(self.index_path)

    def validate(self):
        index = self.index()
        steps = index.get("steps")
        if index.get("phase") != self.name or not isinstance(steps, list) or not steps:
            raise ValueError("Phase index must match its directory and contain steps")
        for number, step in enumerate(steps):
            if step.get("step") != number or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", step.get("name", "")):
                raise ValueError(f"Step {number}: invalid number or slug")
            if step.get("status") not in {"pending", "completed", "error", "blocked"}:
                raise ValueError(f"Step {number}: invalid status")
            if not (self.directory / f"step{number}.md").is_file():
                raise ValueError(f"Step {number}: missing spec")
            checks_for(step)

    def step(self, number):
        return self.index()["steps"][number]

    def save_step(self, number, **changes):
        index = self.index()
        index["steps"][number].update(changes)
        write_json(self.index_path, index)

    def check(self, number):
        commands = checks_for(self.step(number))
        records = []
        for command in commands:
            try:
                result = run_supervised(command)
                record = {"command": command, "exit_code": result.returncode,
                          "output_tail": (result.stdout + result.stderr)[-3000:]}
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                record = {"command": command, "exit_code": 127, "output_tail": str(exc)}
            records.append(record)
            print(f"  {'PASS' if record['exit_code'] == 0 else 'FAIL'}: {' '.join(command)}")
            if record["exit_code"]:
                break
        return {"ran_at": stamp(), "checks": records,
                "passed": len(records) == len(commands) and all(x["exit_code"] == 0 for x in records)}

    def record_review(self, number, report, files):
        if number < 0 or number >= len(self.index()["steps"]):
            raise ValueError("Invalid step number")
        for previous in range(number):
            self.verify_review(previous)
            if not self.check(previous)["passed"]:
                raise ValueError(f"Step {previous}: acceptance checks failed before step {number}")
        report = project_file(report)
        expected_report = (self.directory / "reviews" / f"step{number}.md").resolve()
        if report != expected_report:
            raise ValueError(f"Expected review report: {expected_report}")
        body = report.read_text(encoding="utf-8")
        if not VERDICT.search(body) or len(body.strip()) < 100:
            raise ValueError("Astra report needs substantive findings and a 'Verdict: APPROVED' line")
        if not files:
            raise ValueError("At least one reviewed project file is required")
        review_files = [project_file(file) for file in files]
        if any(project_rel(file).startswith(("phases/", ".git/")) for file in review_files):
            raise ValueError("Reviewed files must be implementation files outside phase and Git metadata")
        verification = self.check(number)
        if not verification["passed"]:
            raise ValueError("Acceptance checks failed; review was not recorded")
        reviewed = {project_rel(file): file_hash(file) for file in review_files}
        review = {"model": REVIEWER_MODEL, "verdict": "approved", "reviewed_at": stamp(),
                  "report": project_rel(report), "report_sha256": file_hash(report),
                  "reviewed_files": reviewed,
                  "spec_sha256": file_hash(self.directory / f"step{number}.md"),
                  "acceptance_checks_sha256": checks_hash(checks_for(self.step(number)))}
        self.save_step(number, status="completed", verification=verification,
                       review=review, completed_at=stamp())
        print(f"Step {number}: accepted with Astra review evidence")

    def verify_review(self, number):
        step = self.step(number)
        review = step.get("review") or {}
        if step["status"] != "completed" or review.get("model") != REVIEWER_MODEL or review.get("verdict") != "approved":
            raise ValueError(f"Step {number}: approved Astra review is missing")
        report_name = review.get("report", "")
        report = project_file(ROOT / report_name)
        if project_rel(report) != report_name or file_hash(report) != review.get("report_sha256"):
            raise ValueError(f"Step {number}: review report changed")
        if not VERDICT.search(report.read_text(encoding="utf-8")):
            raise ValueError(f"Step {number}: review verdict invalid")
        if review.get("spec_sha256") != file_hash(self.directory / f"step{number}.md"):
            raise ValueError(f"Step {number}: step specification changed")
        if review.get("acceptance_checks_sha256") != checks_hash(checks_for(step)):
            raise ValueError(f"Step {number}: acceptance checks changed")
        files = review.get("reviewed_files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"Step {number}: reviewed file hashes missing")
        for name, expected in files.items():
            file = project_file(ROOT / name)
            if project_rel(file) != name or file_hash(file) != expected:
                raise ValueError(f"Step {number}: reviewed file changed: {name}")

    def verify(self):
        self.validate()
        for number in range(len(self.index()["steps"])):
            try:
                self.verify_review(number)
                result = self.check(number)
                if not result["passed"]:
                    self.save_step(number, verification=result)
                    raise ValueError(f"Step {number}: acceptance checks failed")
                self.verify_review(number)
            except ValueError as exc:
                if self.step(number)["status"] == "completed":
                    self.save_step(number, status="error", error_message=str(exc), failed_at=stamp())
                self.update_top("error")
                raise
        for number in range(len(self.index()["steps"])):
            try:
                self.verify_review(number)
            except ValueError as exc:
                self.save_step(number, status="error", error_message=str(exc), failed_at=stamp())
                self.update_top("error")
                raise
        index = self.index()
        index["completed_at"] = stamp()
        write_json(self.index_path, index)
        self.update_top("completed")
        print(f"Phase {self.name}: all checks and reviews verified")

    def update_top(self, status):
        if self.top_path.is_file():
            top = read_json(self.top_path)
            for phase in top.get("phases", []):
                if phase.get("dir") == self.name:
                    field = {"completed": "completed_at", "error": "failed_at"}[status]
                    phase.update({"status": status, field: stamp()})
                    write_json(self.top_path, top)
                    break

    def dry_run(self):
        print(f"Phase: {self.name} | worker: {IMPLEMENTER_MODEL} | reviewer: {REVIEWER_MODEL}")
        for step in self.index()["steps"]:
            print(f"  {step['step']} {step['name']} [{step['status']}]")
            for command in checks_for(step):
                print(f"    AC: {' '.join(command)}")

    @staticmethod
    def require_trusted_hooks():
        manifest = ROOT / ".codex" / "hooks.json"
        guard = ROOT / ".codex" / "hooks" / "pre_tool_use.py"
        if not manifest.is_file() or not guard.is_file():
            raise ValueError("Project Codex hooks are missing")
        if file_hash(manifest) != HOOKS_MANIFEST_SHA256 or file_hash(guard) != PRE_TOOL_GUARD_SHA256:
            raise ValueError("Project hooks changed; review their definitions and update the runner pin")
        config_path = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"
        try:
            with config_path.open("rb") as stream:
                config = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Codex hook trust configuration unavailable: {exc}") from exc
        if config.get("projects", {}).get(str(ROOT.resolve()), {}).get("trust_level") != "trusted":
            raise ValueError("Project is not trusted in Codex configuration")
        state = config.get("hooks", {}).get("state", {})
        for event in ("pre_tool_use", "stop"):
            key = f"{manifest.resolve()}:{event}:0:0"
            if not state.get(key, {}).get("trusted_hash"):
                raise ValueError("Project hooks need trust review in Codex CLI /hooks")

    @staticmethod
    def codex_binary():
        # A broken global npm shim must not mask a working standalone install.
        candidates = [shutil.which("codex"), str(Path.home() / ".local" / "bin" / "codex")]
        for binary in dict.fromkeys(candidates):
            if not binary or not Path(binary).is_file():
                continue
            try:
                result = subprocess.run([binary, "--version"], capture_output=True,
                                        text=True, timeout=10, check=False)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0:
                return binary
        return None

    def invoke(self, model, prompt, *, read_only=False, report=None):
        binary = self.codex_binary()
        if not binary:
            raise ValueError("Codex CLI is unavailable")
        command = [binary, "exec", "--json", "--enable", "hooks", "--model", model, "--sandbox",
                   "read-only" if read_only else "workspace-write"]
        if report:
            command.extend(["--output-last-message", str(report)])
        command.append("-")
        result = run_supervised(command, input_text=prompt)
        check_codex_result(result, model)

    def changed_files(self):
        result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode:
            raise ValueError(result.stderr.strip())
        found = []
        for line in result.stdout.splitlines():
            name = line[3:].split(" -> ")[-1]
            if name.startswith(("phases/", ".codex/", ".claude/", "references/", ".env")) or name.endswith(".zip"):
                continue
            file = ROOT / name
            if file.is_file() and not any(x in {"node_modules", ".venv", "__pycache__", "references"} or x.startswith(".env") for x in file.parts):
                found.append(file)
        return found

    def run(self, resume=False):
        self.require_trusted_hooks()
        for number, step in enumerate(self.index()["steps"]):
            if step["status"] == "completed":
                self.verify_review(number)
                continue
            if step["status"] == "blocked":
                raise ValueError(f"Step {number} blocked: {step.get('blocked_reason', 'unknown')}")
            if step["status"] == "error" and not resume:
                raise ValueError(f"Step {number} failed; use --resume after fixing its cause")
            self.save_step(number, status="pending", started_at=stamp())
            spec = (self.directory / f"step{number}.md").read_text(encoding="utf-8")
            before = {project_rel(file): file_hash(file) for file in self.changed_files()}
            feedback = ""
            for attempt in range(MAX_ATTEMPTS):
                try:
                    self.invoke(IMPLEMENTER_MODEL, f"Implement this step. Read AGENTS.md and docs. Do not edit phase status, commit, or push.\n\n{spec}\n\nPrevious feedback:\n{feedback}")
                    result = self.check(number)
                    if not result["passed"]:
                        feedback = json.dumps(result["checks"][-1], ensure_ascii=False)
                        continue
                    report = self.directory / "reviews" / f"step{number}.md"
                    report.parent.mkdir(exist_ok=True)
                    self.invoke(REVIEWER_MODEL,
                                "Review this step against AGENTS.md, docs, and actual code and tests. Do not edit files. "
                                "Write substantive findings. Finish with exactly 'Verdict: APPROVED' if all pass, "
                                "otherwise 'Verdict: CHANGES_REQUESTED'.\n\n" + spec,
                                read_only=True, report=report)
                    if not VERDICT.search(report.read_text(encoding="utf-8")):
                        feedback = report.read_text(encoding="utf-8")[-3000:]
                        continue
                    files = [file for file in self.changed_files()
                             if file_hash(file) != before.get(project_rel(file))]
                    self.refresh_stale_reviews(up_to=number)
                    self.record_review(number, report, files)
                    break
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    feedback = str(exc)
                    if attempt == MAX_ATTEMPTS - 1:
                        break
            if self.step(number)["status"] != "completed":
                self.save_step(number, status="error", error_message=feedback, failed_at=stamp())
                self.update_top("error")
                raise ValueError(f"Step {number} failed after {MAX_ATTEMPTS} attempts: {feedback[-1000:]}")
        self.refresh_stale_reviews()
        self.verify()

    def refresh_stale_reviews(self, up_to=None):
        if up_to is None:
            up_to = len(self.index()["steps"])
        for number in range(up_to):
            step = self.step(number)
            try:
                self.verify_review(number)
                continue
            except ValueError:
                if step["status"] != "completed":
                    raise
            report = self.directory / "reviews" / f"step{number}.md"
            spec = (self.directory / f"step{number}.md").read_text(encoding="utf-8")
            self.invoke(REVIEWER_MODEL,
                        "Re-review this completed step after later edits. Inspect the current files and tests. "
                        "Write substantive findings. Finish with exactly 'Verdict: APPROVED' only if valid, "
                        "otherwise 'Verdict: CHANGES_REQUESTED'.\n\n" + spec,
                        read_only=True, report=report)
            if not VERDICT.search(report.read_text(encoding="utf-8")):
                raise ValueError(f"Step {number}: re-review requested changes")
            files = [ROOT / name for name in step["review"]["reviewed_files"]]
            self.record_review(number, report, files)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase_dir")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--record-review", type=int, metavar="N")
    parser.add_argument("--review-report", type=Path)
    parser.add_argument("--reviewed-files", nargs="+", type=Path)
    parser.add_argument("--reviewer-model", default=REVIEWER_MODEL)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        runner = StepExecutor(args.phase_dir)
        if args.dry_run:
            runner.dry_run()
        elif args.verify:
            runner.verify()
        elif args.record_review is not None:
            if not args.review_report or not args.reviewed_files:
                parser.error("--record-review requires --review-report and --reviewed-files")
            if args.reviewer_model != REVIEWER_MODEL:
                parser.error(f"--reviewer-model must be {REVIEWER_MODEL}")
            runner.record_review(args.record_review, args.review_report, args.reviewed_files)
        else:
            runner.run(args.resume)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
