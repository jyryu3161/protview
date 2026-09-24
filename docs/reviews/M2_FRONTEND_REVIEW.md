# M2 cache-event frontend final review

Reviewer: GPT-6 Astra. Date: 2026-09-24. Implementation: GPT-6 Sol. Review follows the authoritative frontend correction handoff and the parent's final built-app browser validation.

Verdict: APPROVED

## Independently checked correction

`npm --prefix frontend run test:events`: **5 tests passed**. `npm --prefix frontend run typecheck`: **passed**. The final Sol handoff also records a successful sequential production build; the parent restarted the production server on that artifact before browser QA. No new build execution is attributed to this reviewer.

Astra reran the original independent malformed-event probe, `node /tmp/protview-qa/m2-frontend-cache-probes.cjs`. Current evidence is `/tmp/protview-qa/m2-frontend-cache-corrected-probe-results.json`; event-model.ts SHA-256 is `c9743d5cd3486ab38642e011d45c907de3097d3b96c5d0d8c7448ff23cfcae8f`. Wrong-key, reversed call/success order and duplicate-observation-ID acceptance counts are each zero; valid cache and equivalent reordered argument acceptance counts are each one. The duplicated ID can no longer resolve an A timeline selection to B.

The normalizer now requires exactly one original call and physical success, matching tool/key, strict call < success < cache sequence, canonical JSON-equivalent args and output, and a unique noncolliding observation ID. Canonical comparison sorts nested object keys and preserves array order. Timeline cache rows are built from validated event objects, rather than admitting an invalid event because its ID matches a valid one. Cache rows have independent selection IDs and no physical duration. Legacy cached-success events retain sequence-specific IDs. These were malformed synthetic-stream boundary defects; neither the original finding nor this correction claims the healthy UUID-generating backend emitted duplicate IDs.

## Browser and M1 integration evidence

Parent-run live results: `/tmp/protview-qa/m2-browser-evidence.json`. The two identified synthetic structures share residue/model identifiers but have distinct bytes and inputs: A computes six contacts, B computes zero. Default and explicit cached-A inspection load A's exact prepared handle, show six rows and actual ASP focus, and disable conflicting latest-pipeline mutations. Return-to-latest loads B and its successful empty result. A UI repeated B computation adds a labeled cache observation and survives reload without a new physical success.

Reupload/load of earlier A adds a cached-load observation, displays raw A without a foreign table, and return-to-pipeline resolves A's original prepared successor and six contacts. A cached preparation of B after latest load A displays B without a table and disables conflicting mutations; return-to-pipeline restores A. The resulting ledger retains six physical calls, six physical successes, four cache observations and four unique observation IDs.

The parent's existing public 1HSG run reopens its empty result, then historical contact selection restores 97 measured contacts and actual lime-highlighted ASP A25 focus. No external requests or page errors occurred. Astra inspected `/tmp/protview-qa/m2-cached-old-result.png`, `m2-cached-load-pipeline.png` and `m2-legacy-1hsg-focus.png`; the screenshots corroborate the correct source/result context, cache-read labeling and real focus. This is source/evidence/image review of the parent's browser session, not a separately executed reviewer browser session.

The M1 immutable-input viewer resolution, readiness/focus acknowledgment, stale asynchronous guards, empty/error separation and load→prepare→interaction lineage remain intact. Budget display uses the server ledger; cache timeline entries are not counted as physical work. Later runtime event types need no scientific result row to remain replayable.

## Exact reviewed files

- frontend/src/lib/event-model.ts
- frontend/tests/event-model.test.cjs
- frontend/app/page.tsx
- frontend/src/lib/contracts.ts
- frontend/src/lib/api.ts
- frontend/src/components/run.tsx
- frontend/src/components/MolstarViewer.tsx
- frontend/package.json
- frontend/package-lock.json
- docs/M2_RUNTIME.md

Current hashes: `/tmp/protview-qa/m2-final-frontend-review-hashes.json`. The initial findings are preserved in `/tmp/protview-qa/m2-initial-frontend-review.md`. Full M2 acceptance is recorded in phases/protview-mvp/reviews/step2.md and remains subject to actual harness verification/recording by the parent. No product, phase status or recorded source hash was edited here.
