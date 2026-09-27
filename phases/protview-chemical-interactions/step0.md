# Step0 / M11 — chemical interactions

Design/review GPT-6 Astra; implementation GPT-6 Sol. **Pending.** Begin only after actual M10 acceptance and parent-created branch from its real commit. No index/check/review success is prefilled; parent owns phase recording and Git transitions.

## Required reading and implementation

Read AGENTS.md, docs/ARCHITECTURE.md, docs/DECISIONS.md, docs/IMPLEMENTATION_PLAN.md, docs/POST_M8_PLAN.md, docs/M11_M12_METHOD_SELECTION.md, docs/METHOD_DEPENDENCY_PROBE.md, docs/M11_CHEMICAL_INTERACTIONS_CONTRACT.md, and accepted M9/M10 source/scene/AtomRef contracts. Preserve old objects/reports/reviews. Implement the complete selected native-engine input/import, identity, durable job, capability, result, report, usable UI and native visualization contract. An unavailable-only panel or fixture worker is not completion. Keep scientific native dependencies isolated from the accepted server parser and lock artifacts/hashes. No provider calls or runtime downloads.

Sol implements new test_chemical_interactions.py and actual offscreen chemical-flow.cjs, with public/analytic/derived fixtures explicitly labeled, provenance and licenses. Native tests must require installed selected engine during gate verification, not skip successfully when absent. Configuration points to locally provisioned locked workers; no /tmp probe dependency is permitted. Missing worker in production remains an explicit capability state.

## acceptance_checks: exact executable argv

```json
[
  [
    ".venv/bin/python",
    "-m",
    "pytest",
    "backend/tests/test_chemical_interactions.py",
    "backend/tests/test_jobs.py",
    "backend/tests/test_reports.py",
    "backend/tests/test_core.py",
    "-q"
  ],
  [
    ".venv/bin/python",
    "-m",
    "pytest",
    "backend/tests",
    "-q"
  ],
  [
    ".venv/bin/python",
    "-m",
    "ruff",
    "check",
    "backend/mw",
    "backend/tests",
    "scripts",
    ".codex/hooks"
  ],
  [
    ".venv/bin/python",
    "-m",
    "pytest",
    "scripts/test_execute.py",
    "scripts/test_codex_hooks.py",
    "-q"
  ],
  [
    "npm",
    "--prefix",
    "frontend",
    "run",
    "test:events"
  ],
  [
    "npm",
    "--prefix",
    "frontend",
    "run",
    "typecheck"
  ],
  [
    "npm",
    "--prefix",
    "frontend",
    "run",
    "build"
  ],
  [
    "node",
    "--check",
    "frontend/tests/offscreen/chemical-flow.cjs"
  ]
]
```

These commands name files Sol must implement; they have not been executed as acceptance. When the phase starts, its pending index stores these arrays with no invented outcome. Record exact worker configuration/build manifests and actual command output. Actual offscreen execution requires owned loopback services and bundled fixtures; record its complete real command/environment/control ledger separately. Syntax checking is not browser evidence.

## Gate

1. Actual production engine positive, independently checked geometry/identity/chemistry or projection, and valid native empty/negative evidence under the contract; fixtures cannot be presented as experimental conclusions.
2. Exact graph/source/atom or cavity mapping through UI/report, adversarial identifiers and real downloaded report bytes. Actual Electron isOffscreen/WebGL/paint and native geometry evidence for every mounted new control, error/unavailable/cancel states and source races.
3. Budgets, approval, failed-attempt charges, timeout/process-tree cancellation, restart, malformed/oversized output and zero external runtime requests. Replaying events with original paths and engine removed restores identical objects/reports without calculation.
4. Full commands, documented native dependency setup/provenance, historical report preservation and relevant M8–M10 shared-source regression evidence. No fake broad-inventory rerun claim.
5. Current Astra approval with exact reviewed hashes and explicit shared-source supersession; resolve findings before parent record-review, real --verify and commit. Later authorized phases remain pending until their actual gates.
