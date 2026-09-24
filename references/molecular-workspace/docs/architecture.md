# Architecture

```
 Browser (Next.js, :3000)                         Local machine only
 ┌──────────────────────────────────────────┐
 │ WorkspaceShell                            │   /api/* (rewrite)
 │  Run/Models/Jobs rail · Mol* · Inspector  │ ─────────────────────┐
 │  GoalComposer · CommandBar · SequenceTrack│                      │
 └──────────────────────────────────────────┘                      ▼
                                              ┌───────────────────────────────────────────┐
                                              │ FastAPI  mw.api.app  (:8000)              │
                                              │   POST /runs/{id}/commands  ─┐            │
                                              │                              ▼            │
 Agent loop (M2)  ── plan/decide ──▶  ┌──────────────────────────────────────────────┐   │
  frontier.plan / jev.decide          │ Run.call  (mw.runtime.orchestrator)          │   │
                                      │  check_args(tools.yaml) → idempotency/resume │   │
                                      │  → LoopGuard → approval gate → Budget        │   │
                                      │  → impl | dry-run stub → retry by class      │   │
                                      │  → EventLog.append                           │   │
                                      └───────┬──────────────────────┬───────────────┘   │
                                              │                      │                   │
                              ┌───────────────▼─────┐   ┌────────────▼────────────┐      │
                              │ tools/* (gemmi,      │   │ jobs/queue (SQLite)     │      │
                              │ ProLIF, PLIP, fpocket│   │  → rosetta_worker        │      │
                              │ …) → ObjectStore     │   │    (subprocess, timeout) │      │
                              └──────────┬──────────┘   └────────────┬────────────┘      │
                                         ▼                           ▼                   │
                              runs/<run_id>/ events.jsonl · objects/ · index.sqlite       │
                                             egress.jsonl · jobs.jsonl · report.md        │
                                              └───────────────────────────────────────────┘
                                                             │
                                          EgressGate (sanitize + log) ── the ONLY way out
                                                             │
                                  OpenRouter (jev, frontier) · RCSB / AFDB / UniProt fetch
```

## Flows

**Human command.** CommandBar → `parseCommand` (refs → full handles) → `POST /commands`
→ `Run.call(decided_by="human")` → Handle → UI renders HandleChip; Inspector materializes rows.

**Agent step (M2+).** `compile_state` → `frontier.plan` (prompt registry → EgressGate → OpenRouter)
→ plan JSON (schema-validated) → for each step `Run.call(decided_by="frontier")`. Gray-zone branch
points → `jev.decide`. Threshold branch points → rule, logged as `decision{source:"rule"}`.

**Failure.** `ToolFailure` → `tool_failed` event → transient auto-retry, else the agent reads
`{error, fix}`; LoopGuard stops repeats/oscillation/no-progress → `checkpoint` → ApprovalGate in UI.

**Resume.** Restart = new `Run` on the same dir. `Run.call` finds the idempotency key in
`tool_succeeded` events and re-attaches the handle without executing.

**Replay test.** `replay(events.jsonl → empty dir)` must produce the same handle set.

## Where the UI reads what
| UI | source |
|---|---|
| StepRow list | events: tool_called / tool_succeeded / tool_failed / decision |
| BudgetMeter | GET /budget |
| ApprovalGate | events: approval_requested / checkpoint |
| Inspector tables | GET /objects (materialize with projection, paged) |
| PromptInspector / ModelRoute | events: llm_call (+ config) |
| EgressGateView | egress.jsonl (endpoint to add in M3) |
| JobQueue | jobs table (endpoint to add in M4) |
