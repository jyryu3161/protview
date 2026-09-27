# ProtView phase harness

The phase plan lives in `phases/protview-mvp/`. Its `index.json` is the executable contract: each step has a `stepN.md`, a pending/completed/error/blocked status, and nonempty `acceptance_checks` expressed as argv arrays. The runner rejects shell wrappers and runs every command from the project root without a shell.

`scripts/execute.py` is adapted from `../kbase_kinase/scripts/execute.py`. Only its phase runner and hooks were used as source material. The imported runner had an Astra implementation model, trusted a worker's `completed` status, staged the entire repository, committed automatically, and offered automatic push. This project pins GPT-6 Sol for implementation and GPT-6 Astra for review, executes acceptance checks itself, and records review evidence bound to SHA-256 hashes. Git staging, commit, branch changes, and push are outside this runner.

## Commands

```bash
.venv/bin/python scripts/execute.py protview-mvp --dry-run
.venv/bin/python scripts/execute.py protview-mvp
.venv/bin/python scripts/execute.py protview-mvp --resume
.venv/bin/python scripts/execute.py protview-mvp --verify
```

`--dry-run` validates and prints the plan without changing files. Normal execution first checks that the local Codex project is trusted, that the hooks manifest and PreToolUse guard match the runner's pinned SHA-256 hashes, and that both the PreToolUse and Stop hooks have trusted hashes in the Codex configuration. If this preflight fails, execution stops. The runner invokes `codex exec --json --enable hooks --model gpt-6-sol --sandbox workspace-write` for implementation and `--model gpt-6-astra --sandbox read-only` for review. It rejects nonzero exit status, runtime stderr hook-trust diagnostics, malformed JSONL, top-level `error` or `turn.failed` events, and a stream without a completed turn. Stderr hook checks inspect standalone Warning/WARN/Error headers and timestamped runtime diagnostic records, excluding tool-router records and unprefixed multiline continuation text. Nested `item.*` agent and tool prose is never interpreted as a trust diagnostic. It does not pass hook trust, sandbox, or approval bypass flags.

Normal execution runs pending steps in order: Sol implements, the runner executes each acceptance check (AC), and Astra reviews the current code read only. It retries a failing step up to three times; `--resume` retries an error step after the cause is repaired. Before accepting a later step, the runner refreshes any stale predecessor reviews and reruns those predecessors' AC. It also refreshes stale reviews before final verification. Completed steps are skipped only if their review evidence still matches the files and contract. `--verify` invokes no model: it checks review evidence, reruns each step's AC, checks review freshness again, and marks the phase completed only after all steps pass. A failed AC records its output and invalidates completed status; a stale review also invalidates completed status. Either failure sets the top-level phase status to `error`.

An Astra review produced outside the runner can be attached after implementation:

```bash
.venv/bin/python scripts/execute.py protview-mvp --record-review 0 \
  --review-report phases/protview-mvp/reviews/step0.md \
  --reviewed-files backend/mw/core/contracts.py backend/tests/test_core.py \
  --reviewer-model gpt-6-astra
```

The report must be at the matching `reviews/stepN.md` path, contain substantive findings, and include an exact `Verdict: APPROVED` line. The optional `--reviewer-model` argument must equal `gpt-6-astra`; it does not establish reviewer identity on its own. To attach a later step, all predecessors must already have fresh approved reviews and passing AC. The command reruns the current step's AC before marking it completed. Review evidence binds the report hash, reviewed implementation file hashes, step specification hash, and a hash of the canonical acceptance-check argv arrays. `--verify` checks all of these against current files and checks, then reruns the AC. A changed specification or AC therefore requires a fresh Astra review. A report can record `Verdict: CHANGES_REQUESTED`; such a report cannot complete the step.

Do not include `.env` or other private files in review evidence. The runner rejects `.env*`, `.venv`, and `references/` as evidence paths. `.gitignore` also excludes `.env*` except `.env.example`.

The runner probes `codex --version` and falls back to `~/.local/bin/codex` when the command on `PATH` is unusable. It supervises each Codex and AC command in a new process session. On timeout it sends SIGTERM to the process group, then SIGKILL after a bounded grace period, and reaps the process before retrying or reporting failure.

The Stop hook runs Ruff on `backend/mw`, `backend/tests`, `scripts`, `.codex/hooks`, and `design/build_tokens.py` with a 45-second limit. It then runs three disjoint pytest groups concurrently: chemical science tests; M11 job/API tests; and the remaining backend tests plus `scripts/test_execute.py` and `scripts/test_codex_hooks.py`, with the first two test files explicitly ignored in that last group. Their collected union is the same full backend/harness suite as the former sequential command; no tests are skipped. Each group has a 480-second limit, and failures or timeouts block completion with bounded captured output. Process-group termination and final pipe cleanup are bounded beneath the unchanged trusted 600-second outer Stop deadline. The phase acceptance commands remain the exact sequential argv in the phase step.

The M11 root-wide heavy-worker gate scans at most 1,000 run entries and 256 MiB of event ledgers, and waits at most one second for a contended ledger lock. If those bounds or unresolved guardian cleanup block admission, preserve the immutable run histories and use the named run/job in the diagnostic to reconcile its supervisor before retrying. For capacity recovery, stop the service; verify each run selected for archival has no running or cleanup-pending job; copy the **whole** run directory, including events and objects, to an offline archive; verify its file hashes; then relocate that whole directory outside the configured runs root and record where it went. An archived run is unavailable through the active API until restored as a whole directory. Never trim an event ledger or delete scientific objects in place to free capacity. A denied pre-reservation attempt remains uncharged and can be started again after the condition is resolved.
