# M3 final implementation and integration review

Reviewer: GPT-6 Astra. Date: 2026-09-24. Implementation: terminal GPT-6 Sol correction session 50991. Reviewed against docs/EGRESS_CONTRACT.md.

Verdict: APPROVED

All seven initial findings are resolved in the corrected source and bounded evidence. The parent completed the single authorized synthetic live smoke and final built-app browser validation. The selected M3 contract is approved, subject to actual harness checks and source-hash recording. This does not approve M4 jobs or M5 reports. No credential was read or external request made by this reviewer; live execution is explicitly attributed to the parent.

## Independent execution

- `.venv/bin/python -m pytest backend/tests/test_llm_egress.py backend/tests/test_runtime.py -q`: **88 passed in 2.49s**, one existing Starlette TestClient deprecation warning.
- `.venv/bin/python -m ruff check backend/mw/egress backend/mw/llm backend/mw/runtime`: **passed**.
- `npm --prefix frontend run test:events`: **6 passed**; `npm --prefix frontend run typecheck`: **passed**.
- Original reviewer child-process fixture rerun on the corrected source: `/tmp/protview-qa/m3-astra-crash-probes.py`; output `/tmp/protview-qa/m3-astra-corrected-crash-probe-results.json`. Both gate and runtime hashes match before/after execution. These are MockTransport lifecycle fixtures, with inert keys and termination only of owned children.

Sol reports 64 M3 tests and passing frontend production build. Parent independently confirms exact Stop Ruff, 151 combined tests in 7.03s and 26 compatible installed packages through uv pip check. Reviewer additionally executed core/structural/API regressions: 32 passed in 1.22s. Parent supplies corrected sentinel probes in `/tmp/protview-qa/m3-parent-corrected-probe-results.json`, runnable from `m3-corrected-parent-probes.py`. Its tests are explicitly parent-executed; reviewer independently inspected the corrected code, executed the suites and repeated the actual child crash probes. Original failing evidence and the initial review are retained under `/tmp/protview-qa/m3-initial-egress-review.md` and the initial probe filenames.

## Correction assessment

1. **Safe model identity.** Only the known allowed served snapshot can be persisted or returned as served_model. The parent rejected-path response no longer appears in events/results; its valid 18-token/$0.03 usage still settles. Unrecognized model metadata is discarded rather than accepted by a path-like regex.
2. **Bounded numeric conversion.** Shared finite conversion handles unrepresentable integers without OverflowError. Strict counts/tokens retain integer bounds; state, confidence, probabilities, costs and timeout validation reject unsuitable values. A valid answer with an invalid huge cost may remain an advisory acceptance, while USD remains unknown/reserved and further spending is blocked; the implementation does not invent a zero cost. Known token usage settles independently.
3. **Pre-dispatch active time.** Remaining wall budget subtracts monotonic time spent in the current operation and is rechecked after preparation/audit. Parent resolver and dispatch-audit 2000-second fixtures now make zero transport calls. A proved skipped dispatch records its state and refunds only the unspent reservation; ambiguous dispatch remains conservative.
4. **Owned total deadline.** The actual HTTP path uses AsyncClient inside AnyIO fail_after for connect/send/headers/body iteration, with bounded shielded cleanup and no detached request thread. The sync gate rejects an existing asyncio-loop context before key lookup/reservation. Parent's real-await AsyncByteStream fixture with a 0.05-second deadline returns external_timeout at approximately 0.0535 seconds, closes the stream, and produces zero chunks after return. Observed headers preserve sent=true; incomplete usage remains unknown. This is controlled fixture timing, not a claim of observed internet latency or live provider behavior.
5. **Lossless residue count.** Projection validates the complete ResidueRef field/type shape and aggregates its full key, including label chain/sequence. Parent same-author/different-label fixture now yields two distinct residues for two contacts. Identifiers remain local, with only the count projected.
6. **Durable settlement.** Saved response usage is reconciled once under run ownership; overrun state derives from reservation/actual ledger relationships, not the later convenience marker. The reviewer killed a child before settlement after saved 18-token/$3.25 usage: reopen now reconstructs exactly 18/$3.25 and prevents new dispatch as budget_exhausted. Killing immediately after the $0.06 settlement against a $0.05 reservation also preserves the stop. Repeated reopen yields one settlement and zero new credential/transport calls in both cases. During a live owner, the competing call remains typed busy; dispatch-time kill retains one reservation, no automatic resend and one egress wall charge.
7. **Truthful mode.** RunSummary carries the persisted EgressMode, the page computes effective mode with dry_run precedence, and the read-only shell renders its prop. The executed mode-render regression covers local, online and dry modes. Public creation remains local-only; no online control or public arbitrary-state endpoint was added. The final parent browser session also confirms all three modes and retained local creation.

## Completed live and browser evidence

The parent made exactly one request through the corrected gate, with no retry, in run_119df4c5823b476d941d2cfaafe39f6a. `/tmp/protview-qa/m3-live-evidence.json` records HTTP 200, accepted summary, requested alias typesafe/jev-1.13 and served snapshot typesafe/jev-1.13-20260917. The body contains only the explicitly synthetic empty aggregate state and reviewed static question/provider fields. There are zero scientific object events. Audit progresses prepared(sent=false) → dispatch_started(sent=unknown) → response_received(sent=true) → settled; the single attempt consumes 493 input + 52 output = 545 tokens and reported cost $0.000020706. The budget's tiny binary floating-point representation difference is not a changed reported cost. The parent artifact scan found no credential.

Astra independently recomputed the prepared body SHA-256 from that safe evidence as `395fe61ffc464d762b8da09a360c709af81095e2d3862425a4777a9d27907afc`, matching the audit, and verified the requested/served mapping and token sum against the budget. This proves one live transport/schema/policy interaction, not scientific recommendation quality or a model benchmark. No further live call is required or claimed.

Parent final production browser evidence is `/tmp/protview-qa/m3-browser-evidence.json`. It confirms online and dry-run badges, a newly created local_only/non-dry run, the legacy real 1HSG 97-contact result with actual green ASP A25 focus, the six-row historical cache observation on its exact earlier input, and a cached successful empty result. Browser external requests and page errors are both zero. Astra inspected `m3-online-mode.png`, `m3-dry-mode.png` and `m3-legacy-1hsg-focus.png` alongside the structured results. This is review of the parent's browser execution, not a claimed second reviewer session. Parent-only QA selector mistakes were corrected before the final evidence and are not represented as product defects.

## Retained limits

The HTTP body contains only the strict numeric projection and fixed question/provider/model constants. The gate owns all transport and credential injection; local_only/dry_run do not resolve a key or create a network attempt. The synchronous internal operation is the supported entry point; no new generic async API is claimed. Responses are bounded, unsupported answers use the labeled rule, unknown usage blocks further spending, and no response cache or automatic retry is claimed. Rule recommendations concern table views only, not scientific affinity, energy or bond certainty.

Future use retains the same explicit configuration, approval, strict projection and audit requirements. Do not silently retry an ambiguous outcome, weaken privacy/model policy, or interpret the synthetic connection result as scientific validation.

## Exact reviewed files

- backend/mw/egress/gate.py
- backend/mw/llm/openrouter.py
- backend/mw/llm/prompts.py
- backend/mw/llm/verifier.py
- backend/mw/runtime/orchestrator.py
- backend/mw/runtime/guards.py
- backend/mw/core/events.py
- backend/mw/core/residue.py
- backend/mw/workspace.py
- backend/mw/api/app.py
- config/default.yaml
- backend/tests/test_llm_egress.py
- frontend/src/components/shell.tsx
- frontend/app/page.tsx
- frontend/src/lib/api.ts
- docs/M3_EGRESS.md
- docs/EGRESS_CONTRACT.md
- backend/pyproject.toml
- frontend/package.json
- frontend/tests/mode-badge.test.cjs
- frontend/tests/event-model.test.cjs
- frontend/src/lib/event-model.ts

Final snapshot: `/tmp/protview-qa/m3-final-review-hashes.json`. M0–M2 reports are refreshed for the shared-source integration. The parent must record current source hashes and passing acceptance commands through the real harness before step completion. This review changes documentation only, not implementation, contracts, index/status or recorded approval hashes.
