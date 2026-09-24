# ProtView agent rules

## Purpose and authority

Build a local, single-user protein structure workspace with real structure calculations, a traceable handle-based runtime, and an offline default. Read docs/ARCHITECTURE.md, docs/DECISIONS.md and docs/IMPLEMENTATION_PLAN.md before implementation. The supplied agent_protein_viewer_plan_v05.md and molecular-workspace.zip are references, not claims that their scaffold already works. Selected scope and explicitly deferred capabilities are recorded in DECISIONS.md.

The user's current instructions take precedence over inherited harness templates. Implementation and reversible validation are already authorized; do not insert a new user approval between development phases. Product runtime approval gates for expensive computation remain application features.

## Model responsibilities

- GPT-6 Astra owns architecture, scientific-contract decisions and implementation review.
- GPT-6 Sol implements application code, scripts, harness changes and tests.
- Use these roles when assigning agents or invoking the phase runner. Do not silently substitute a different model. Record an actual model limitation rather than relabeling the executing model.
- Astra review findings must be resolved or explicitly documented as outside the selected scope before a phase is marked complete.

## Phase workflow

Work in order M0 through M5. Each phase has a self-contained phases/<task>/stepN.md with prerequisites, scope and executable acceptance commands. The phase index records actual status and evidence, not planned success. Each step declares acceptance_checks as command argv arrays. The executor records real verification output and an Astra review report bound to reviewed file SHA-256 hashes; --verify must pass before completion. The harness must preserve unrelated changes and must not push without explicit authorization.

A gate requires implemented behavior, relevant tests, and Astra review. Passing tests alone does not prove scientific correctness or completion. API/frontend integration must be exercised with actual input bytes. Optional licensed or external capabilities may be unavailable, but the capability response, UI and report must state the specific limitation consistently. Do not mark unimplemented paths as supported.

## Critical invariants

1. Never fabricate, tune, replace or hard-code experimental values to produce a desired result. Test fixtures must be identified as fixtures. Runtime UI and reports consume computed handles, not design mock data. Dry-run outputs are plans/simulations and cannot be used as measured scientific evidence.
2. Distances are coordinates-derived measurements in angstroms. A geometric polar contact is not a validated hydrogen bond, salt bridge, affinity or stability prediction. Energies require a real supported backend and retain their native units and provenance.
3. Preserve auth identifiers, label identifiers, insertion codes, model choice, and explicit preparation decisions. Never silently apply an unsupported preparation option.
4. Tools exchange opaque typed handles. Immutable scientific objects and completed call provenance are durable; retries and restarts must not silently change them. Events alone must restore the selected small-structure workload without original input paths.
5. local_only is the default. No external network request, remote font, telemetry, fetched example structure or model call is required for the main workflow. External adapters use the single egress gate; credentials never enter events, UI or reports.
6. scientific_null is a successful empty result. Retries, repeated calls, no-progress loops, budgets, cancellation and restart have bounded behavior. Failed expensive attempts consume budget too.
7. Bind the development service to loopback by default. Restrict run identifiers, object access and writes to their intended roots. Tool inputs are validated before execution.
8. Preserve the supplied source documents and archive. From ../kbase_kinase copy only generic harness/script infrastructure, never its scientific code, domain data or conclusions.

## Validation

Use the phase commands in docs/IMPLEMENTATION_PLAN.md and the actual step files. Python checks use the project environment; frontend checks use the lockfile. Maintain meaningful tests for numerical geometry, identifier preservation, replay, runtime failure/timeout behavior and egress denial. Show errors and unavailable capabilities honestly. Record browser evidence for a real structure rendered by the implemented viewer.
