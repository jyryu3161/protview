# Step1 / M7 — OpenMM protein-only potential and bounded minimization

Design/review: GPT-6 Astra. Implementation: GPT-6 Sol. Requires current approved M6 and a real branch phase/m7-openmm-minimization from its accepted commit; do not fabricate old history.

## Read first

AGENTS.md; docs/ALTERNATIVE_METHODS_CONTRACT.md sections4–7; docs/JOBS_CONTRACT.md; docs/JOBS_POSIX_ADDENDUM.md; docs/RUNTIME_CONTRACT.md; docs/REPORT_CONTRACT.md; actual M6 implementation/review; backend/mw/jobs/{queue,guardian}.py; backend/mw/tools/energetic.py; backend/mw/api/app.py; frontend/app/page.tsx.

## Implement

Pin/install verified OpenMM8.6.0 and expose the separate fixed openmm_protein_minimize protocol, not a renamed Rosetta method. Require explicit protein_only/rebuild_pH7 policy and exclusions; standard complete proteins only, no silent missing-heavy-atom repair. Use fixed Amber14+GBn2, CPU/thread1, NoCutoff/no constraints, tolerance10kJ/mol/nm, max50iterations and bounded job timeout. Persist atom/residue identity mapping, actual hydrogen/protonation choices, source/force-field/System hashes, input/final coordinates and exact native before/after/change potential. Do not claim convergence, ΔΔG, affinity or stability from a returned minimization.

Extend the existing fixed queue/guardian adapter map and registry schema/capability metadata. Add real explicit run approval/start/status/cancel/reopen UI/API behavior; preserve one durable reservation per physical launch and all M4 cohort/cleanup/STOP/CAS/admission invariants. No arbitrary executable/XML/platform/env input, fixture production exposure or nested Run.call double charge. Known unsupported input gives a typed reason without fabricated energy; engine-time parameterization failures retain a charged attempt. New minimized coordinates and method report are separate immutable objects; old complexes/contact tables/reports stay bound to their own inputs.

## Acceptance commands

```text
.venv/bin/python -m pytest backend/tests/test_openmm.py backend/tests/test_jobs.py backend/tests/test_runtime.py backend/tests/test_reports.py -q
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m ruff check backend/mw backend/tests
.venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q
npm --prefix frontend run test:events
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

The exact new index stores argv arrays. Engine/process tests require actual host evidence with no engine-missing or process-table skips counted as success; sandbox limitations may be documented separately.

## Required evidence

Real production-job1UBQ complete protein input and independent direct OpenMM energy consistency using recorded constructed topology/settings; actual finite before/after potential and changed mapped coordinates, fixed iteration bound/no invented convergence. Public1UBQ bytes SHA056f98710cb2b36f633c45e41902a02eb446e82871da21ff2dd44f74a56ca0f6 are a starting fixture, not fixed expected energies. Explicit protein-only1HSG missing-terminal-OXT failure remains honest under the no-heavy-repair policy. Cover modified/missing/ambiguous inputs, exclusions/H mapping and unsupported system settings.

Run actual production routing/approval/budget/cache tests, timeout/cancel/parent-loss/normal-success cleanup and forbidden fixture/command input; preserve earlier M4 process regressions. Verify missing/malformed/foreign output cannot publish energy. Test input/result/report semantic identity, wrong method/unit/subject claims, old report readability, exact events-only recovery with OpenMM calls forbidden and no new job launches. Parent browser shows explicit protein-only policies, real job state/cancel, successful supported potential/minimized model/report, unsupported1HSG reason, safe history/reopen/stale/error paths and zero nonloopback requests.

Write docs/M7_OPENMM.md with actual installed distribution/build/platform/force-field fingerprints, production evidence, scientific limits and known unsupported inputs. Astra performs final method and shared-source regression review; parent records current extension gates, handles stale MVP coverage explicitly, executes actual final --verify and commits M7. No extra OpenRouter request, proprietary engine, ranking or mutation scan is added.
