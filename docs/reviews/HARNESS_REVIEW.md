# Harness independent final review

Reviewer: GPT-6 Astra. Date: 2026-09-24. Latest correction: terminal GPT-6 Sol session69553. This approval concerns the phase harness; product M0–M5 reviews remain separately scoped.

Verdict: APPROVED

Final M5 continuity check: all reviewed harness implementation/config/documentation hashes remain identical to the approved snapshot. Parent current host Stop240 passed/0skipped includes all51 harness tests, and Astra current full Ruff passes. Actual normal trusted Sol invocation was used through final correction4438. No pin/trust/parser change or bypass was introduced. This paragraph does not claim that pending final ordered recording/--verify has already run.

The JSON event boundary and runtime diagnostic-header correction resolve both demonstrated false hook-trust rejections without changing hook pins, trust preflight, model roles or sandbox settings. Earlier contract/timeout/state/order findings remain corrected. The detailed earlier review history is preserved at `/tmp/protview-qa/harness-review-before-m4-refresh.md`.

## Independent verification

- `.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q`: **51 passed in 3.59 seconds**.
- `.venv/bin/python -m ruff check scripts .codex/hooks`: **passed**.
- Actual `StepExecutor.require_trusted_hooks()` against the current local configuration: **passed**, without printing or changing that configuration.
- Actual `check_codex_result` against two completed, parent-captured GPT-6 Sol CLI streams: **139 JSONL events with 1019 bytes of runtime stderr**, and **86 events with empty stderr**, both accepted. The first stderr contains two timestamped tool-router patch failures followed by quoted source paragraphs; those paragraphs are correctly excluded from trust diagnostics.
- For each actual capture, adding an ANSI/plain standalone skipped-untrusted-hooks warning before or after stderr is rejected: **four rejection checks passed**. Submitted regressions additionally cover timestamped hook diagnostics, explicit generic-runtime hook warnings, tool-header quotes, ordinary test prose, nested agent/tool messages, top-level failures, malformed JSONL, incomplete and out-of-order completion.

Safe evidence, event-type counts and exact source hashes: `/tmp/protview-qa/harness-m4-final-review-evidence.json`. The real CLI captures were inspected structurally; no credential or unrelated session data was read. Parent confirms session69553 terminal exit 0 and trusted-hook checks before/after the actual invocation. Its sandbox Stop result **205 passed / 17 skipped** is worker-reported and not used as proof of the skipped product process cases. No new paid model invocation was made for this review.

## Contract and implementation assessment

`invoke` uses `codex exec --json --enable hooks`, GPT-6 Sol with workspace-write for implementation and GPT-6 Astra with read-only for review. The parser requires valid JSONL with an ordered completed turn and rejects nonzero return codes and top-level error/turn.failed events. Nested item content is data, not runtime authority. Stderr checks operate on recognized standalone or timestamped diagnostic headers; tool-router records and unprefixed source continuations do not become trust failures. A recoverable tool patch error followed by a completed turn is not an invocation failure merely because it quotes the word hooks.

The runtime trust-warning boundary is intentionally separate from model text. Exact CLI diagnostics may evolve; currently verified headers and fixtures are covered, and future CLI changes should be validated rather than answered with a bypass. Official documentation supports JSONL event separation and hash-bound hook trust/startup warnings: [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode), [hooks](https://learn.chatgpt.com/docs/hooks). No hook-trust, sandbox or approval bypass flag is present in invocation.

The runner executes acceptance argv itself and binds the substantive Astra report, implementation files, phase specification and canonical acceptance commands to hashes. It checks predecessor order/freshness, invalidates stale/failed completion, refreshes stale predecessor reviews in the automatic route, and rechecks freshness around verification. It refuses private/reference review paths and excludes generated runtime/build output. It does not stage, commit, switch branches, reset or push, preserving unrelated dirty work. Process-group timeout/reaping and Stop-hook regressions remain in the passing suite.

The original generic runner/hooks provenance from `../kbase_kinase` remains documented; no kinase science was imported into this harness. Hook configuration and role templates remain unchanged and consistent. Review authorship is a workflow trust assertion backed by actual Astra review, not cryptographic model authentication.

## Exact reviewed files

- scripts/execute.py
- scripts/test_execute.py
- scripts/test_codex_hooks.py
- .codex/hooks/stop.py
- .codex/hooks/pre_tool_use.py
- .codex/hooks.json
- .claude/settings.json
- .claude/commands/harness.md
- .claude/commands/review.md
- .gitignore
- CLAUDE.md
- docs/HARNESS.md

The parent has used actual external record-review/verify gates for M0–M3 and actual trusted Sol CLI execution. This report does not claim that one uninterrupted automatic six-phase runner has completed. The parent must bind current reports/files through the harness after product reviews; this reviewer changed no index/status/hash records. M4 and M5 product reviews are now separately approved; final current-source recording and --verify remain the parent executor action.
