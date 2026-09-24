# CLAUDE.md — rules for coding agents in this repo

You are implementing **Molecular Workspace**: a local protein-structure workspace (Mol* + FastAPI)
with an autonomous agent runtime (OpenRouter: Jev + a frontier model, PyRosetta jobs).
Single user, everything local except OpenRouter calls and public-DB fetches.

Read before any change: `docs/plan_v0.6.md` (what and why) → `docs/contracts.md` (shapes you must keep)
→ the milestone file you were asked to do in `docs/milestones/`.

## Invariants — never break these (tests enforce most of them)

1. **Tools return handles, not data.** Every tool puts its output in `ObjectStore` and returns a `Handle`
   (`handle, kind, schema, summary, preview≤5`). Full content only via `materialize(handle, columns)`.
2. **Handles are content-addressed.** Same kind+schema+canonical content → same handle. Don't put
   timestamps, random ids, absolute paths or file names inside stored content.
3. **Failure taxonomy.** A failing tool raises `ToolFailure(FailureClass.<one of 5>)`.
   An empty scientific result is **not** a failure: return a Handle with `null_result=True`.
4. **Everything runs through `Run.call`** (backend/mw/runtime/orchestrator.py) — agent AND human
   commands. Never call a tool implementation directly from API, UI or agent code.
5. **`events.jsonl` is the single source of truth.** sqlite files are derived. Any new state
   change needs an event. `tests/test_core.py::test_replay_from_events_only` must stay green.
6. **Contracts before execution.** Tool args are checked against `config/tools.yaml` (`accepts` kinds,
   param enums/ranges) before the tool runs. A wrong kind → `precondition` with a `fix`.
7. **Egress.** Anything leaving the machine (OpenRouter, RCSB/AFDB/UniProt fetch) goes through
   `EgressGate` and is logged to `egress.jsonl`. Never send coordinates, full sequences, file paths
   or file names. API keys never appear in logs, runs/, or the frontend.
8. **Model pins.** OpenRouter roles use pinned models, `allow_fallbacks: false`, and record the
   *served* model on every call. `data_collection: deny`, `zdr: true` by default.
9. **Rules before models.** If a threshold decides it, it's `rule`, not Jev. Every decision event
   is labeled `rule | jev | frontier | human`.
10. **Units.** Rosetta energies are stored and shown in **REU**. Distances Å, areas Å². Residues are
    displayed auth-style `A/100A`; the canonical key is label-based (`ResidueRef.key`).
11. **Reproducibility.** Every Rosetta job records scorefxn, Rosetta version, seed.

## Frontend rules

- Components come from `frontend/src/components` (import from `@/components`). Visual reference is
  `design/previews/*.html` (open `design/index.html`). Match them; don't restyle.
- **No hex colors, px spacing or font names in components.** Use CSS variables from
  `src/design/tokens.css` (generated — edit `design/tokens.json`, then `npm run tokens`).
- Status is never color-only: glyph + enum string + color. `scientific_null` is neutral gray, dashed.
- UI copy: Korean sentences, English identifiers in mono, no emoji, no exclamation marks.
  Buttons are verbs ("실행", "여기서 멈춤"). Questions only inside ApprovalGate.
- The page never builds DSL strings for the backend: CommandBar resolves refs to full handles and
  sends JSON (`parseCommand`).

## How to work

- One milestone at a time. Start by reading its "Acceptance" list and writing/confirming the tests.
- Keep changes small; run the checks after each step:
  - backend: `cd backend && python -m pytest -q`
  - frontend: `cd frontend && npm run typecheck && npm run build`
- If a contract must change: update `docs/contracts.md`, `backend/mw/...`, `frontend/src/lib/contracts.ts`
  **in the same change**, and say so in the commit message.
- Don't add dependencies casually. Heavy science libs go in `[project.optional-dependencies].science`.
  PyRosetta is licensed — import it lazily, only inside `mw/jobs/rosetta_worker.py`.
- Don't build: accounts, auth, sharing, multi-tenant queues, plugin SDKs, onboarding (plan §2).
- When unsure between two designs, pick the one that keeps the invariants above testable, and note
  the decision in `docs/decisions.md` (create if missing: date · decision · why).

## Map

```
backend/mw/core/        handles (ObjectStore), events (EventLog), errors, contracts, residue
backend/mw/runtime/     orchestrator (Run.call, replay), guards (retry, loop guards, budget)
backend/mw/egress/      EgressGate
backend/mw/llm/         openrouter client, prompt registry, number verifier
backend/mw/tools/       registry + structural (gemmi baseline) + energetic (stubs → M4)
backend/mw/jobs/        SQLite job queue + PyRosetta worker entry
backend/mw/api/         FastAPI (same command path for humans)
config/                 default.yaml (runtime/egress/openrouter), tools.yaml (contracts), pipelines/
prompts/                versioned prompt templates  <id>@<version>.md
design/                 tokens.json (source of truth), components.css, previews/, index.html gallery
frontend/               Next.js app: src/components, src/lib (contracts, api), src/mock, app/
docs/                   plan, contracts, architecture, milestones, prompts for vibe-coding sessions
```
