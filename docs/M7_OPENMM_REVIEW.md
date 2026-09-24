# M7 independent scientific and integration review

Reviewer: GPT-6 Astra. Implementation: GPT-6 Sol. Date: 2026-09-24. Branch: `phase/m7-openmm-minimization`, from actually accepted M6 commit `50569ee2736674cd4a8f34a12866a3c591be4e0e`. Product correction87994 exited normally before the final independent probes; subsequent test-only correction68295 is recorded below.

Verdict: APPROVED

The selected M7 implementation and its current shared-source regression coverage are approved. No blocking finding remains. This review covers the evidence below; parent still performs ordered extension review recording, acceptance-command reruns and final --verify. It does not prefill or claim those pending gate actions.

## Scientific calculation and evidence boundary

The new protocol is actual OpenMM8.6.0 protein-only potential minimization, separate from Rosetta and FreeSASA. It uses Amber14 plus GBn2 implicit solvent, explicit pH7 hydrogen rebuilding, CPU/Threads1 for construction and evaluation, NoCutoff, no constraints, tolerance10kJ/mol/nm and at most50 minimization iterations. The engine build string and six exact transitive force-field XML hashes are recorded. Native before, after and after-minus-before potentials retain kJ/mol. The result explicitly declines convergence and iteration-count claims; it does not imply affinity, binding free energy, ΔΔG or experimental stability.

Preflight binds an actual prepared/source/model to full author/label/insertion-code residue identities. Canonical complete protein heavy templates, terminal OXT, alternate-site resolution, finite bounded coordinates, known-label sequence adjacency and adjacent C–N geometry are checked before launch. There is no hidden heavy-atom repair or terminal capping. Excluded components and source hydrogens are disclosed, including water removed during prior preparation. Actual public1UBQ supplies602 heavy atoms,629 constructed hydrogens and1231 final atoms with58 excluded waters. Actual1HSG remains unsupported because its terminal OXT is missing; no energy is fabricated for it.

The worker preserves the actual serialized System XML, exact input/final Å arrays, viewer CIFs, canonical topology/bonds, source atom/residue bijections, added hydrogens, variants, seed and disulfides. Shared engine-free validation binds the typed source, preparation, System, coordinates, method, result and ordered job/attempt events. Counts are exact; every scientific quantity and report claim is linked to its named field, unit, subject and rendered value. System particle/bond topology and CIF/full-precision correspondence are checked. The fixed fingerprint table is exact, not merely nonempty or hex-shaped. This establishes internal consistency/provenance, not cryptographic authenticity of arbitrarily mutually forged science; fixed-worker execution and independent native reconstruction are separate numerical evidence.

## Resolved findings and durable execution

Initial paired malformed artifacts exposed missing shared validation: bad System/topology hashes, empty bonds, foreign residue mapping and header-only CIF could be accepted. They now fail the shared publication/saved-read validator. Later empty or nonhex force-field tables also fail the fixed-method check. The original deleted-residue gap case is rejected by bounded template/sequence/geometry preflight. Genuine native fixture bytes were preserved through the correction; no experimental values were replaced to make tests pass.

The actual hydrogenated preparation is atomically written and file/directory-fsynced before the first named protocol potential evaluation. After verified group cleanup, a pure validator ingests complete preparation/System/input-coordinate objects and an idempotent `job_preparation_recorded` event. Success reuses those exact objects; failure/cancellation may retain preparation but never energy output. Missing or malformed checkpoints cannot derail a terminal outcome or become a successful result. Null/list System values were independently reproduced and now safely reject.

Existing reservation, approval, transition/CAS, cleanup, direct-child reap, STOP-message drain, finite retry, owner-loss and admission rules remain in force. Physical host tests exposed a real cross-interpreter psutil public-clock identity mismatch. The bounded correction in `M7_PROCESS_IDENTITY.md` uses the pinned7.2.2 raw PID-reuse value with explicit kind/platform/version. UID, PID, PGID, session, nonce, receipt and before/after anchor/cohort checks remain required; no tolerance or blind group kill was added. Old completed records remain readable. Old active public-time records do not acquire new signaling authority. Huge integer identity values now reject safely. The policy probes mock every signal; they do not claim observed OS PID reuse.

Known boundary findings are resolved in source: correct preflight query, typed absent-engine failure before charge, public opaque input_handles, input-specific policy/error reset, current-run/job/input/result/action epochs, separate keyed result/report errors, retry paths, charged-budget refresh, and clearing the minimized override when returning to original/history. Actual browser evidence must establish these behaviors; unit guards alone are insufficient.

## Independent probes and continuity

After worker87994 terminal, Astra ran `/tmp/protview-qa/m7-astra-final-probe-wrapper.py`. Its evidence `/tmp/protview-qa/m7-astra-final-probe-evidence.json` records four successful probes and unchanged before/after source hashes at10:48:00UTC. The bundle probe retains genuine cached native coordinates/energies/System bytes and derives only the new selected-input digest from the identical stored input. Its checkpoint/publication setup uses explicitly synthetic cleanup evidence, not a real guardian claim. Positive native validation and publication pass; all seven original malformed cases reject for their scientific validation reasons. Force-field paired fixtures update their selection digest consistently so a trivial backlink mismatch cannot mask the fixed-method test.

The shape probe rejects all three malformed/truncated checkpoint fixtures. The raw-identity probe rejects altered raw identity with zero mocked signals, accepts the legitimate identity for one mocked signal, and rejects huge integer/bool/NaN/infinity. The legacy probe copies only accepted1HSG events, forbids OpenMM/FreeSASA imports, reconstructs exact M5 and M6 manifest/Markdown bytes, adds no events and leaves the original run untouched. Parent also recovered actual new done/cancelled UI runs with engine imports and process launch forbidden; preparation persists, cancellation has no output and repeated reconciliation adds no events.

## Final host and browser evidence

Parent final stable host evidence `/tmp/protview-qa/m7-final-host-evidence.json` records288 passed, zero skipped in143.01s across all backend and harness tests, plus full Ruff PASS. One existing Starlette/httpx deprecation warning is disclosed. Astra checked every recorded source hash against files at the original review and confirmed identical before/after hashes; the later test-only change is isolated below. This includes real production success/timeout/cancel/parent-loss/checkpoint cases and existing runtime/jobs/MVP regressions. Frontend19 tests, typecheck and production build passed in terminal Sol70701; the only later implementation change is the identity helper/focused backend tests. Parent reruns the phase acceptance argv when recording. Sandbox process-enumeration skips and controlled writer interruptions are historical limitations, not host acceptance or completed implementation claims.

Parent final actual API/guardian/OpenMM evidence `/tmp/protview-qa/m7-host-production-evidence.json` has identical before/after hashes for eight production sources. Actual1UBQ completed with verified cleanup and separate preparation/result/report objects; semantic resubmission returns the same job and saved reads append no events. Observed potentials were−10346.694301882708 before and−12808.036541236112 after, change−2461.342239353404kJ/mol. These are measured values for this constructed system, not expected constants. Actual launched timeout and cancellation retain one expensive charge and verified cleanup with no result. Public1HSG returns typed412 missing-terminal-OXT with zero expensive units.

Independent native reconstruction `/tmp/protview-qa/m7-independent-energy-evidence.json` rebuilds the recorded1231-atom/76-residue/1237-bond System without calling the product worker or minimization. Serialized System SHA matches exactly; before/after potential discrepancies are−1.4551915228366852e-11 and0kJ/mol against a1e-5kJ/mol tolerance. This verifies the recorded native calculation, not biological accuracy or convergence.

Parent final browser evidence `/tmp/protview-qa/m7-final-browser-evidence.json` is after the last worker and backend restart, with stable before/after source hashes. It confirms actual minimized Mol* rendering, exact preview/Markdown download, unchanged43→43-event reopen, visible1/8 charged budget and successful return to original/latest input. Astra inspected `m7-final-browser-viewer.png`: a real molecular canvas, explicit protein-only method/units/exclusions, measured potentials and no original-complex contact claims are visible. No nonloopback request or page error occurred.

The complementary exhaustive candidate browser evidence `/tmp/protview-qa/m7-browser-candidate-evidence.json` exercises real approvals and first charge, actual UI cancellation after worker start with preserved preparation/no energy, legacy M6 report equality, policy reset, separate result/report503 errors and retry, delayed result/report reads and submit/start/approve/report-create responses across run changes. Its guardian changed during capture; all nine other listed UI/API/queue/scientific sources were stable. The final production lifecycle rerun and final unchanged-source browser check close that attribution gap. No preflight query shim was used for accepted evidence; earlier shim-assisted exploration remains unaccepted historical diagnostics.

Nonblocking display limitation: the canvas's auxiliary caption can still say “latest pipeline structure” during a minimized-coordinate override. The actual selected coordinate handle, explicit protein-only panel, latest-input mismatch warning, disabled original-input mutations and tested return action remain correct. The caption is not used as scientific evidence or to attach old contact measurements to the minimized protein.

## Extension coverage and Git history

M0–M5 were actually accepted/verified at baseline `d22fe15` without historical per-phase branches. M6 was actually recorded and committed as `50569ee` on `phase/m6-interface-sasa`; M7 is a real subsequent branch. This review and refreshed extension step0 explicitly supersede current changed shared-source coverage. They do not claim historical MVP hashes remain fresh or rewrite its reviews. Parent owns ordered extension recording, actual `protview-methods --verify` and the final Git commit.

Core events/objects/runtime, SASA calculator and existing M5/M6 report engines remain unchanged from the accepted M6 source. Shared API, queue/guardian, registry/dependencies, structure bytes and frontend changes are included below; full regression and old/new report/browser evidence must cover them. The old four Rosetta capability records remain unavailable and separate from the new method capability, preserving old report rendering. No new OpenRouter request, credential change, original archive/reference modification or proprietary-engine installation belongs to M7.

## Final test-only correction after the first verify attempt

The first actual ordered record-review0 and1 succeeded, but the subsequent real extension `--verify` failed: the full backend run reported1 failure/236 passes because the parent-loss test observed an existing but empty barrier marker. `/tmp/protview-qa/m7-final-gate-evidence.json` preserves that failed gate; it is not relabeled successful. Earlier host288/0 and production/browser evidence remain valid historical results on the unchanged product, not a claim that this later verification succeeded.

Astra confirmed a test publication race: child `Path.write_text` created/truncated the marker before writing, while the parent polled existence and immediately required exact content. Actual GPT-6 Sol worker68295 made only the test's private marker publication atomic: write a job-specific sibling temporary file, close it, then `Path.replace(marker)`. Exact stage, authenticated worker-start event, real parent kill/wait, interrupted state, empty owned group, budget1 and finally cleanup assertions are unchanged. No extra sleep, relaxed assertion, mock lifecycle or product change was introduced.

After normal worker termination, parent reran the real host test: **1 passed,0 skipped in1.62s**, with the existing deprecation warning. Evidence: `/tmp/protview-qa/m7-atomic-marker-final-host-evidence.json`. Astra independently compared all51 previously reviewed files: only `backend/tests/test_openmm.py` changed, to SHA256 `697901ea37005f8e3d1f0b0ee65648fddae6ad0adc2c00bd705e50129129ed12`. Product, scientific, UI and other evidence sources are unchanged; no repeat native/browser measurement is claimed or required for this test-only edit. Approval is reaffirmed for the corrected test and source inventory. Parent must now rerun ordered recording and actual extension --verify; no post-correction full-suite or successful final --verify is claimed here.

The original public1HSG/1UBQ CIF fixtures retain their required exact source SHA bytes. Their raw-input trailing whitespace is an explicit exception to staged whitespace checking, limited to those two files; do not normalize source fixtures or conceal a general whitespace-check failure.

## Exact reviewed files

- AGENTS.md
- README.md
- backend/mw/tools/sasa.py
- backend/mw/method_reports.py
- backend/mw/api/app.py
- backend/mw/runtime/orchestrator.py
- backend/mw/workspace.py
- backend/pyproject.toml
- backend/tests/test_sasa.py
- backend/tests/test_api.py
- config/tools.yaml
- frontend/app/page.tsx
- frontend/src/lib/api.ts
- frontend/src/lib/event-model.ts
- frontend/src/lib/report-selection.ts
- frontend/src/lib/area-format.ts
- frontend/tests/event-model.test.cjs
- frontend/tests/report-selection.test.cjs
- frontend/tests/area-format.test.cjs
- docs/ALTERNATIVE_METHODS_CONTRACT.md
- docs/ARCHITECTURE.md
- docs/DECISIONS.md
- docs/IMPLEMENTATION_PLAN.md
- docs/M6_SASA.md
- backend/mw/core/residue.py
- backend/mw/tools/structural.py
- backend/mw/reports.py
- frontend/src/components/MolstarViewer.tsx
- frontend/package.json
- docs/M6_SASA_REVIEW.md
- backend/mw/jobs/queue.py
- backend/mw/jobs/guardian.py
- backend/mw/jobs/lifecycle_fixture.py
- backend/mw/jobs/process_identity.py
- backend/mw/jobs/openmm_worker.py
- backend/mw/openmm_bundle.py
- backend/mw/openmm_reports.py
- backend/mw/tools/openmm_method.py
- backend/mw/tools/energetic.py
- backend/tests/test_jobs.py
- backend/tests/test_openmm.py
- backend/tests/fixtures/public_1ubq.cif
- backend/tests/fixtures/public_1hsg.cif
- frontend/src/lib/openmm-action.ts
- frontend/tests/openmm-action.test.cjs
- frontend/tests/openmm-api.test.cjs
- docs/M7_OPENMM.md
- docs/M7_PROCESS_IDENTITY.md
- docs/M7_OPENMM_REVIEW.md
- docs/JOBS_CONTRACT.md
- docs/JOBS_POSIX_ADDENDUM.md
