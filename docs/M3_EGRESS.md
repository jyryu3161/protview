# M3 Decisions egress implementation

The default run mode is `local_only`. The internal `decide_inspection_view(run, interaction_handle)` operation reads an existing measured `interaction_set@1` object and returns one local table view. The rule works without credentials or networking. Online Jev is optional and must be enabled in the immutable `run_started.egress` configuration; a key's presence never changes the mode. The current HTTP API creates local-only runs and has no public online decision endpoint or chat UI.

## Boundary

`build_inspection_state` recomputes counts and minimum distance from measured interaction rows. Only the ten fields of `inspection_state@1` can enter the outbound body. The local evidence handle, residue/atom identities, structure data, source name and goal do not enter it. Invalid or unrepresentable state uses the rule. The synthetic connection fixture is intentionally separate from scientific object storage.

`EgressGate.request_jev` owns the fixed URL, static choice question, fixed privacy policy, JSON serialization, credential resolution, HTTP transport, response validation and durable audit. It sends at most one POST to `https://openrouter.ai/api/alpha/decisions` for a call. It requests `typesafe/jev-1.13` and accepts only the configured `typesafe/jev-1.13-20260917` served snapshot. It disables redirects and environment proxies and caps the decoded response body at 64 KiB. The request and response have no chat messages or arbitrary caller-selected fields. Invalid choices and model IDs fall back to the deterministic rule. A rejected provider model string is never retained in an event or returned envelope; only the recognized snapshot can appear as `served_model`.

The run event stream records a prepared body and SHA-256 before dispatch, then `dispatch_started`, a server response or transport failure, and per-axis settlement. `sent=unknown` means dispatch began but no server response was observed; a server response, including an HTTP error, records `sent=true`. The existing first-expensive-call approval is required and each dispatched attempt consumes one expensive-call unit. An unresolved reservation or unknown usage blocks further online spending. Known `usage.input_tokens` plus `usage.output_tokens` and `usage.cost` settle independently, even for a rejected recommendation. Numeric fields must be finite and representable within their declared bounds; an invalid cost leaves the USD reservation unknown while valid tokens still settle, and vice versa.

The gate checks remaining active wall time after credential resolution, after body preparation, and just before dispatch. The HTTP operation runs in an owned `httpx.AsyncClient` under a total AnyIO deadline spanning connect, send, headers and every response chunk. Response and client cleanup has a short bounded shield; its elapsed time is charged. HTTPX's per-phase timeout remains supplementary. The synchronous gate rejects a caller already inside an event loop before key lookup or reservation. No timeout uses a detached worker thread or leaves a request running after return. A timeout after response headers records `sent=true` and unknown usage if the body was incomplete.

Reservations, settlements, wall time and checkpoints replay through M2's run owner and budget. On reopen, a durably saved `response_received` usage is settled once by `audit_id`; a saved settlement is never applied twice. Unknown axes keep their conservative reservations. A known actual exceeding its reservation or run limit recreates a `budget_exhausted` stop from authoritative ledger values even when the later settled marker was interrupted. An ambiguous dispatch remains blocked as `usage_unknown`; no request is resent automatically. Egress wall time is charged once, while M2 tool-orphan reconciliation retains its original mutation-time behavior. There is no automatic retry or response cache in M3.

Measured residue aggregation validates the full `ResidueRef` shape and counts its canonical key, including `chain_label` and `seq_label`. Those identifiers stay local; only the count enters the outbound state. The frontend's existing read-only badge displays the reopened run's effective `local_only`, `online`, or `dry_run` mode. Public run creation still defaults to `local_only` and cannot create an online run.

## Root-owned synthetic connectivity smoke

The parent can invoke the following internal path once after review. It creates a new explicitly online run, sends **synthetic aggregate state only**, and prints safe fields. It does not store the synthetic fixture as a scientific object. The key resolver runs inside the online gate; do not print headers, inspect `.env`, or repeat an ambiguous call. Use a fresh run ID and a writable smoke directory. This snippet is documentation, not a routine test.

```python
from pathlib import Path
from uuid import uuid4
from mw.egress.gate import EgressGate
from mw.llm.openrouter import synthetic_connection_fixture
from mw.workspace import new_run

run = new_run(
    Path("runs"), run_id=f"run_{uuid4().hex}", dry_run=False,
    egress_config={
        "mode": "online",
        "jev": {
            "enabled": True,
            "request_model": "typesafe/jev-1.13",
            "allowed_served_models": ["typesafe/jev-1.13-20260917"],
            "timeout_s": 15,
        },
    },
)
run.approve("expensive_first_call", by="human")
result = EgressGate().request_jev(run, synthetic_connection_fixture())
print({"status": result.status, "reason_code": result.reason_code,
       "requested_model": result.requested_model, "served_model": result.served_model,
       "audit_id": result.audit_id, "http_status": result.http_status,
       "usage": result.usage})
```

The parent should inspect the safe egress events for the exact prepared body hash, confirmed or unknown delivery, model identity and actual or unknown usage. A successful connection tests the transport contract only; no scientific recommendation quality is established. No live smoke was run by the M3 implementer.

## Files changed

- `backend/mw/egress/gate.py`: recognized model IDs, bounded numerics, elapsed-aware dispatch and owned total-deadline transport.
- `backend/mw/llm/openrouter.py`: canonical validated residue aggregation and bounded projection numerics.
- `backend/mw/runtime/orchestrator.py`: exactly-once response settlement on reopen and ledger-derived overrun stop.
- `backend/pyproject.toml`: declares the direct AnyIO dependency.
- `backend/tests/test_llm_egress.py`: seven-finding regressions using inert credentials, async streams, replay fixtures and API mode reads.
- `frontend/src/lib/api.ts`: types the persisted run mode and derives its effective badge mode.
- `frontend/app/page.tsx`: passes that effective mode to the shell.
- `frontend/src/components/shell.tsx`: renders the supplied read-only mode.
- `frontend/package.json`: includes the mode test in `test:events`.
- `frontend/tests/mode-badge.test.cjs`: renders local, online and dry badges from run summaries.
- `docs/M3_EGRESS.md`: final correction handoff and limits.

## Validation and limits

Correction validation: scoped M3 pytest **64 passed** and Ruff passed; exact Stop Ruff passed and exact Stop pytest **151 passed**; frontend `test:events` **6 passed**, typecheck passed and production build passed, in that order. The supplied independent crash probe was rerun read-only: live owner remains busy, interrupted dispatch retains one conservative reservation and one wall charge, saved actual usage settles on reopen, and both known overruns block another transport or credential lookup. The supplied initial evidence remains unchanged. These fixture checks do not establish a real network outcome or browser rendering proof. The public API and new-run UI remain local-only; the online badge applies to internally configured runs that the API can reopen. The M5 evidence-bound report verifier remains future work. Caching, remote structure fetch, generic chat, model quality benchmarking and paid scientific decisions are outside this implementation. Parent-owned validation is now complete: one synthetic-only gate request returned HTTP 200 and action summary, with requested typesafe/jev-1.13 and served typesafe/jev-1.13-20260917. Actual usage was 493 input plus 52 output tokens (545 total), cost $0.000020706, and one expensive attempt; there was no automatic retry or scientific object output. The prepared body SHA-256 is 395fe61ffc464d762b8da09a360c709af81095e2d3862425a4777a9d27907afc. The parent artifact scan found no credential. This validates connectivity, not scientific decision quality. Safe evidence: /tmp/protview-qa/m3-live-evidence.json.

Parent browser validation on the final built app confirms truthful online/dry badges, local-only default creation, reopened real 1HSG with 97 contacts and actual ASP A25 focus, and preserved cached historical/empty results with exact input association. No external browser requests or page errors occurred. Evidence: /tmp/protview-qa/m3-browser-evidence.json. Astra independently reviewed the corrected source, process interruption probes, suites and these artifacts; the final review is docs/reviews/M3_EGRESS_REVIEW.md and phases/protview-mvp/reviews/step3.md. The parent records actual phase acceptance through the harness.
