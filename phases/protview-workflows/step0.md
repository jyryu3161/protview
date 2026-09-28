# Step0 / M13 — deterministic local workflow planning and execution

GPT-6 Astra design/review; GPT-6 Sol implementation. Pending design after accepted M12. Parent records the actual predecessor/branch when implementation starts. No index, completed status, check evidence or model call is created by this specification.

## Read and scope

Read AGENTS.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/IMPLEMENTATION_PLAN.md, docs/POST_M8_PLAN.md, docs/M10_MEASUREMENT_ALIGNMENT_CONTRACT.md, docs/M11_CHEMICAL_INTERACTIONS_CONTRACT.md, docs/M12_POCKET_DETECTION_CONTRACT.md, docs/M13_WORKFLOWS_CONTRACT.md, accepted M9–M12 reviews/interfaces, and current runtime/guards/jobs/workflows/report source. Validate accepted versions rather than treating pending contracts as installed capability.

Implement all fixed local goal templates, immutable typed plans, visible explicit inputs/prerequisites, plan approval distinct from scientific approval, plans-only dry-run, event-backed step execution over ordinary Run.call/durable jobs/report builders, atomic idempotent admission, crash-gap reconciliation, scoped cancellation, bounded attempts/null behavior, result navigation and evidence-linked immutable summaries/reports. Preserve existing inspect_complex and old scientific/report semantics. No model planner or live call; expose its specific unavailable reason. Do not present local rules as natural-language intelligence or enable arbitrary tools/paths/commands.

Sol owns a new pending index and code/tests/offscreen harness. Parent owns real branch transitions and phase recording. A source-compatible extension may add internal operation-link/cancellation fields to existing lanes, but cannot bypass run ownership, job supervision, budget reservation or method validation.

## Exact acceptance command argv

```json
[
  [".venv/bin/python", "-m", "pytest", "backend/tests/test_analysis_workflows.py", "backend/tests/test_runtime.py", "backend/tests/test_jobs.py", "-q"],
  [".venv/bin/python", "-m", "pytest", "backend/tests", "-q"],
  [".venv/bin/python", "-m", "ruff", "check", "backend/mw", "backend/tests", "scripts", ".codex/hooks"],
  [".venv/bin/python", "-m", "pytest", "scripts/test_execute.py", "scripts/test_codex_hooks.py", "-q"],
  ["npm", "--prefix", "frontend", "run", "test:events"],
  ["npm", "--prefix", "frontend", "run", "typecheck"],
  ["npm", "--prefix", "frontend", "run", "build"],
  ["node", "--check", "frontend/tests/offscreen/workflows-flow.cjs"]
]
```

Store these arrays exactly when creating the pending index. Actual offscreen execution needs owned services, accepted engines/fixtures and stable build: preserve exact invocation, environment, source/build and full case ledger separately, never replace it with a fake passing check.

## Mandatory gate evidence

1. Plans-only dry-run proves zero scientific calls/jobs/report measurements, including cheap tools. Every goal compiles exact supported typed sources/decisions and blocks missing capabilities or incompatible accepted versions. No hidden default ligand/chemistry/mapping or numeric plan fixture appears as measured output.
2. Plan/scientific approval separation; atomic concurrent UUID/revision behavior; fault injection at every admission→child→success→workflow-event boundary; recovery verifies exact child causality without repeat physical work or new cache proposals. Reports and plan bytes remain immutable.
3. Scoped Stop leaves the run and unrelated manual/shared jobs usable. Before-dispatch, in-call/backoff, owned-job, shared-job, result-publication and run-switch races preserve actual charges/cleanup and start no downstream steps. Limits, one explicit retry, scientific_null and no-progress terminate durably.
4. Events-only reconstruction works with original inputs and method executables unavailable, no new science/model calls. Normal real accepted adapters produce results in their original native units; repeated reads/summary creation cannot alter them. Each quantitative report field is verified against its exact handle/path/unit.
5. Actual nonvisible Electron offscreen WebGL/paint inventory individually tests every preset/control and stated error/retry/cancel/reopen states, with real inputs, output navigation and completed exact-byte downloads. Direct Astra screenshot/result/causal review. No new provider request or falsely claimed model planning.
6. Current full backend/frontend/harness checks plus relevant fresh M8–M12 shared viewer/report/method/job regressions. Document actual rerun scope rather than claiming all historical controls were rerun. Astra approves exact source/evidence and shared supersession; parent then records review hashes, actual --verify and commit. No approval or phase completion is prefilled by this design.
