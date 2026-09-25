# ProtView phased implementation

GPT-6 Astra designs and reviews. GPT-6 Sol implements and repairs. The current user request authorizes this plan and implementation; no new plan approval is needed. Source references remain immutable. Phase task: phases/protview-mvp.

## Execution and evidence

Use a root .venv with the backend installed editable and dev dependencies available. Install frontend dependencies from its lockfile. The step index contains acceptance_checks as arrays of command argv; checks run from the repository root without shell interpolation. Initial statuses are pending. A check or review record is written only after execution, never prefilled with a successful result.

For each phase: read its step specification, implement, run the listed checks, have GPT-6 Astra inspect relevant code and behavior, resolve findings, and record the review. Review reports live at phases/protview-mvp/reviews/stepN.md. The runner records verification output and a review record binding the report to reviewed file SHA-256 hashes. --verify re-executes acceptance checks and checks review freshness. Do not mark later stages done solely because broad tests pass.

The actual executor command syntax is documented by python3 scripts/execute.py --help. The intended review command is python3 scripts/execute.py protview-mvp --record-review N --review-report phases/protview-mvp/reviews/stepN.md --reviewed-files <paths...> --reviewer-model gpt-6-astra. A review must explicitly approve or request changes, list inspected files, describe scientific/runtime limitations and cite verification evidence.

## M0 — Objects, imports and preparation

Import the selected archive scaffold. Establish canonical typed objects, full hashes, events with payloads and disposable indices. Load real PDB/mmCIF, select models, prepare with supported deterministic policies, preserve identifiers and link manifests. Add core/structural tests for known geometry and identifier edge cases. Gate: duplicate input is stable; events alone restore objects after deleting original inputs and derived storage; malformed input and unsupported policies fail honestly.

Checks: .venv/bin/python -m pytest backend/tests/test_core.py backend/tests/test_structural.py -q; .venv/bin/python -m ruff check backend/mw/core backend/mw/tools.

## M1 — Real viewer and structural API

Wire upload, run commands, capability metadata, structure-byte access and paginated interactions to the backend. Replace the mock main page with actual server state and Mol*. Render a local fixture, change representation and focus a measured residue. Keep selection and author/label identity accurate. Explicitly show no-contact and unsupported states. Gate: API numerical test changes when coordinates change; a browser session proves actual molecular rendering and live counts rather than an SVG/static dashboard.

Checks: .venv/bin/python -m pytest backend/tests/test_api.py backend/tests/test_structural.py -q; npm --prefix frontend run typecheck; npm --prefix frontend run build. Record browser smoke evidence in the Astra review, including real upload/render and a selected interaction.

## M2 — Bounded resumable runtime

Repair validation, caching, typed failure policy, retries, no-progress/repeat/oscillation guards, dry-run behavior and restart state. Exercise at least ten distinct malformed/failure cases, including unsupported tool, wrong kind, invalid selection, invalid policy, transient exhaustion, same-argument repair, resource timeout, fatal failure, no-progress loop and scientific-null success. Gate: bounded attempts, durable outcomes, no expensive dry-run fallback and no repeated work after resume.

Checks: .venv/bin/python -m pytest backend/tests/test_runtime.py -q; .venv/bin/python -m ruff check backend/mw/runtime.

## M3 — Local-only egress and decision provenance

Build compact state from approved schemas. Centralize optional external HTTP, accurate audit events, source labels and safe configured-model behavior. Keep main workflow fully offline. Gate: a denied request never reaches its transport; hidden coordinate/sequence/path fields and freeform sensitive text cannot leak through arbitrary keys; credentials never enter artifacts; local rules finish inspection without a model key. Fixture tests validate optional adapter behavior. Separately, the user authorized a minimal live OpenRouter connectivity smoke using the ignored root .env credential, an explicitly pinned available model, and synthetic compact state through the egress gate. The parent agent performs and records this check; keep default local_only and enable online only for the explicit smoke. Record actual connection/model response evidence without claiming a scientific quality benchmark.

Checks: .venv/bin/python -m pytest backend/tests/test_llm_egress.py -q; .venv/bin/python -m ruff check backend/mw/egress backend/mw/llm. Browser evidence confirms no third-party resource request in local_only.

## M4 — Durable jobs and honest energy capabilities

Implement durable queue transitions and isolated worker supervision, timeout/kill, cancellation/restart and budget reservation/charging on failure. Expose actual protocol-level capability status. Optional PyRosetta calls must either perform a real implemented protocol with seed/version/score function/native units or return unavailable, with no numeric substitute. Gate: unapproved or exhausted expensive calls do not start, failed attempts consume budget, timed-out subprocesses terminate, unavailable engine produces no energy table. Live licensed protocol validation is recorded separately and never inferred from fake-worker lifecycle tests.

Checks: .venv/bin/python -m pytest backend/tests/test_jobs.py backend/tests/test_runtime.py -q; .venv/bin/python -m ruff check backend/mw/jobs backend/mw/tools/energetic.py.

## M5 — Traceable reports and release verification

Connect offline inspect_complex and report generation to the real page. Every quantitative claim has handle/field/unit evidence; reject wrong-row/wrong-unit claims. Persist run history sufficiently to reopen results, publish usable startup instructions and document adopted/deferred capabilities. Verify source-only restoration and full local workflow on a nontrivial structure. Gate: full suite, frontend build, browser workflow, harness tests and final Astra audit of each selected requirement. No design mock values on the runtime route.

Checks: .venv/bin/python -m pytest backend/tests -q; .venv/bin/python -m ruff check backend/mw backend/tests; .venv/bin/python -m pytest scripts/test_execute.py scripts/test_codex_hooks.py -q; npm --prefix frontend run typecheck; npm --prefix frontend run build. Record local browser upload -> prepare -> measure -> select -> report evidence and explicit optional capability limitations.

## Completion boundary

Deliver a running local workspace and verified M0–M5 selected scope, not all aspirational v0.5 features. A clean phase index is evidence only when backed by actual tests and reviewed file hashes. Missing browser validation, broken scientific identity, fabricated output, replay dependence on original paths or an offline network leak prevents completion. Unavailable optional methods remain visibly unavailable and are documented with their requirements.

## Authorized continuation: M6–M7 alternative methods

After the accepted M0–M5 release and real baseline commit d22fe15, implement the user's requested alternatives in a separate protview-methods group. Follow docs/ALTERNATIVE_METHODS_CONTRACT.md. Step0/M6 on phase/m6-interface-sasa delivers actual selected protein–ligand FreeSASA geometry plus full UI/report/recovery. Step1/M7, branched from the real accepted M6 commit, delivers actual supported protein-only OpenMM Amber/GBn2 potential and bounded minimization via the durable production worker, with explicit unsupported-input behavior. New specs are phases/protview-methods/step0.md and step1.md; Sol creates their pending index with the listed executable argv. Astra reviews real output and parent performs gates/commits. No retrospective M0–M5 branch claim, no changed MVP specs or fake completed state.

Each extension gate includes current shared-source regression coverage, exact method dependencies/provenance, preserved historical objects/reports, actual browser evidence and zero external runtime requests. Refresh stale MVP review records or explicitly document their supersession in the extension's current full review before claiming final current verification. Optional scientific methods remain distinguishable by scope: SASA geometry and protein potential do not establish ligand affinity, mutation stability or Rosetta energy equivalence.

## Authorized continuation: M8 actual viewer agent and offscreen QA

On the real phase/m8-agent-viewer branch from accepted e0abffc, implement phases/protview-agent-ui/step0.md under docs/M8_AGENT_VIEWER_CONTRACT.md. Actual model choices must become acknowledged typed Mol* representation/selection/camera operations; local commands remain labeled offline. Add scoped consent/caps/cancel/idempotent history without changing scientific calculations or global job approval. Sol owns the official Electron offscreen harness and application corrections. Root performs every case in docs/M8_OFFSCREEN_QA_PLAN.md using actual offscreen rendering and at most4 bounded real model requests; fixture error/race tests are separately labeled. All current product controls, history/reports/jobs and disabled states must be exercised, not only the new prompt composer. Astra then reviews current shared sources and real evidence; parent records actual gates/commit. Historical M0–M7 reviews/specs remain preserved and are not falsely called current by their old hashes.
