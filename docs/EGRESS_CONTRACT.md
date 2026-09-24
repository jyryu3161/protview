# M3 compact-state and Jev boundary

Design: GPT-6 Astra, 2026-09-24. Scope: one optional, bounded Jev inspection-view recommendation over safe aggregate measurements, plus a complete local rule path. No new chat UI, remote structure downloader, generic prompt endpoint, frontier generation or scientific ranking is required. M2 runtime accounting remains authoritative. The parent owns the user-authorized single live connectivity smoke; this document does not read credentials or authorize additional paid requests.

## 1. Supported local decision

Expose an internal decide_inspection_view(run, interaction_handle) operation. It suggests which existing local table view to inspect: summary, all_contacts, polar_contacts or hydrophobic_contacts. This is an advisory UI/workflow decision, never a hydrogen-bond, affinity, energy or mutation-quality judgment. It does not execute another scientific tool automatically.

The rule fallback is deterministic: no contacts -> summary; otherwise polar_contacts if polar contacts exist, hydrophobic_contacts if they exist and polar contacts do not, else all_contacts. Record this as source=rule and rule_version=inspection_view@1. A configured Jev may make the advisory choice instead; retain both the suggestion and its evidence. Do not describe the rule as model output or invent confidence for the rule.

The decision envelope contains action enum, source (rule | jev), status (local | unavailable | accepted | fallback), reason_code enum, local evidence handle, requested_model/served_model when applicable, and request_id/cache status. Strings shown to the user come from static local templates keyed by reason_code. Provider freeform text is not needed for this use case.

## 2. Outbound state is a new projection

A local compact_state object may reference handles, but it is not itself safe to send. Build a separate strict EgressInspectionStateV1 by reading and validating the scientific interaction envelope. Recompute/verify its aggregates against measured rows rather than trusting arbitrary summary metadata. Keep the full handle/field evidence map local; it is not part of the HTTP body.

The complete outbound state is:

- schema: literal inspection_state@1.
- measurement_method: literal heavy_atom_distance.
- contact_count: nonnegative integer, at most 10,000,000.
- contacting_residue_count: nonnegative integer no greater than contact_count; zero when contact_count is zero.
- polar_contact_count, hydrophobic_contact_count, other_contact_count: nonnegative integers whose sum equals contact_count.
- minimum_distance_A: finite number in [0, 1000], or null only when contact_count is zero; obtained from the measured distance column.
- cutoff_A: finite number in the implemented structural tool's accepted range; obtained from the interaction input parameters.
- null_result: boolean equal to contact_count == 0.

These are product schema choices, not an OpenRouter-required state schema. There are no arbitrary strings, arrays, dictionaries, dynamic field names or user IDs in this state. Strict numeric validation must reject strings and booleans masquerading as numbers, NaN/Infinity, invalid bounds and inconsistent totals. Unknown fields are rejected by the gate; the projection builder never copies them in the first place. If an otherwise valid local result cannot be represented under these limits, use the local rule and disclose state_unrepresentable rather than truncating counts.

Do not forward raw goal/context, chat messages, file or ligand names, PDB IDs, chain/residue/atom names, sequence, source path, run ID, object handles, preparation notes, generic previews or object summaries. Excluding identifiers here is an intentional minimal MVP choice: aggregated counts/distances are enough for this decision and avoid injecting sensitive strings through fields that merely look harmless. Full residue IDs and handles stay available in the local workspace and reports.

The public/backend route must accept an existing interaction handle, not an arbitrary outbound JSON payload. A caller cannot submit its own messages, questions, criteria, destination, provider options or alleged numeric state. The authorized live smoke uses a clearly named internal synthetic fixture constructor; it creates synthetic aggregate inputs solely for connection testing and never stores them as a measured scientific result.

## 3. One outbound owner and injectable transport

Suggested interfaces, adaptable to existing code:

- build_inspection_state(store, interaction_handle) -> EgressInspectionStateV1 plus local evidence map.
- JevDecisionClient.decide(state, run_context) -> validated decision or typed unavailable/failure.
- EgressGate.request_jev(state, question_id, config, transport) -> validated transport response with audit_id.

The gate owns destination selection, request serialization, audit, budget reservation, credential injection and the actual transport call. Returning an arbitrary sanitized dictionary for a separate caller to send is insufficient: that arrangement lets callers bypass the boundary after validation. Inject httpx.MockTransport or a small callable transport for tests, with the same gate invocation path as real HTTP. Tests must count actual transport calls.

Only POST https://openrouter.ai/api/alpha/decisions is enabled for this adapter. Disable redirects, arbitrary base URLs, user-supplied headers and environment-derived proxies for the selected direct connection. A redirected response fails safely; it does not resend credentials elsewhere. External fetch helpers remain unsupported; in local_only they cannot touch a transport. All browser resources remain local.

Before credential lookup or transport creation/dispatch, enforce mode. local_only and dry_run never dispatch, even if an online response is cached: choose the labeled rule path. online requires explicit persisted run configuration, an enabled Jev adapter, a configured request pin, a compatible response-model allowlist and available credentials. Do not auto-switch mode because a key exists.

## 4. Jev wire contract and model identity

This is the Decisions API, not chat completions. The request contains model, the approved state, a static questions object and reviewed provider routing options. Use exactly one choice question named inspection_view. Its instructions and criteria descriptions are checked-in constants explaining the four local view enums and the limitation that geometric proximity is not chemical proof. They may not interpolate source data or user text.

Request shape:

    model: configured request pin
    state: EgressInspectionStateV1
    questions:
      inspection_view:
        type: choice
        instructions: <static reviewed instruction>
        criteria:
          summary: <static description>
          all_contacts: <static description>
          polar_contacts: <static description>
          hydrophobic_contacts: <static description>
    provider: <reviewed fixed privacy/routing policy>

Use the selected policy data_collection=deny, zdr=true and allow_fallbacks=false. Any additional provider flag must be supported by the actual Decisions adapter contract and fixture/live evidence; do not blindly copy chat-only response_format, messages or max_tokens fields. A provider rejecting the configured policy is a visible unavailable/fallback outcome, not permission to weaken the policy or retry on a different model.

Configured request alias: typesafe/jev-1.13. The parent verified the documented served snapshot typesafe/jev-1.13-20260917. Maintain an explicit mapping from that request alias to allowed response IDs (the alias itself only if actually returned/validated, and the documented pinned snapshot). Never accept arbitrary prefix matches or silently replace an absent served model with the requested alias. An unlisted/missing served ID rejects the model decision, records a bounded model_mismatch/missing_model code and falls back to rules. Preserve requested and served IDs separately. A new served snapshot needs a reviewed config update; do not claim benchmark equivalence.

The primary source confirms state/questions, choice instructions/criteria, answers and per-request usage.cost; it describes Decisions as alpha. It also distinguishes its choice API from chat completions. Source independently checked for this design: https://github.com/OpenRouterTeam/ai-sdk-provider#evaluation-jev-with-ai-sdk-through-openrouter . Parent additionally verified the endpoint and model page https://openrouter.ai/typesafe/jev-1.13 and https://openrouter.ai/blog/insights/what-is-jev/ . The MVP adapter remains plain HTTP; this reference does not add an SDK dependency.

## 5. Strict response and cache

Require a JSON object, a permitted model identifier, an answers object and answers.inspection_view.type exactly equal to choice, with answers.inspection_view.choice in the fixed action enum. A missing type, score/noul answer, array, string or other shape is response_invalid even if a choice-looking value appears elsewhere. Bound the decoded response body before parsing (64 KiB is sufficient for this single-question MVP); never scan an oversized response for a usable answer.

The independently checked primary wire schema is [OpenRouter Decisions schemas.ts](https://github.com/OpenRouterTeam/ai-sdk-provider/blob/main/src/evaluation/schemas.ts); the [evaluation adapter index.ts](https://github.com/OpenRouterTeam/ai-sdk-provider/blob/main/src/evaluation/index.ts) maps its usage fields to SDK result fields. The HTTP response uses a choice-discriminated answer, optional probabilities/confidence, optional model metadata and usage.input_tokens/output_tokens/cost. The API-documentation URL embedded in that source returned 404 in the parent check, so it is not claimed as a separately verified API page. These public main-branch source references were checked on 2026-09-24; fixture compatibility and the bounded live check remain necessary for the alpha endpoint.

ProtView deliberately requires model even though the SDK schema permits it to be absent. Missing model therefore triggers the existing safe missing_model fallback; never substitute the request alias as a served ID. A rejected decision can still represent a billed request. Account for independently valid usage even when the answer or served model is rejected. Receipt/delivery evidence and usage settlement must not depend on accepting the advisory action. If probabilities/confidence are present, ProtView accepts only finite numeric values in [0, 1] (not booleans or strings), with probability keys restricted to the four fixed actions and at most four entries. This is the local safety/normalization policy, stricter than the SDK wire schema’s generic numeric fields. Do not invent missing confidence or a missing distribution; the advisory choice does not require either optional field. Parse only the supported answer and usage fields. Unknown provider metadata and freeform messages are discarded without being copied into an event, result or cache. A polar/hydrophobic view with zero applicable contacts is unusable and falls back to the rule; a model does not override facts.

Do not turn advisory probabilities into scientific confidence. A normalized response object may preserve provider-reported advisory probabilities with an explicit model_decision_probability label. A malformed shape, nonfinite field, excessive response size or inconsistent answer yields response_invalid with no raw body attached.

Cache only a validated response. The cache key includes endpoint, request alias, allowed served-model mapping/version, exact approved state, static question version/hash and provider policy. It excludes credentials. A hit revalidates the saved response against current policy, performs no credential lookup/transport/budget charge, and records cache_hit with sent=false. Switching to local_only/dry_run bypasses model cache usage to retain a purely local rule decision. Do not cache invalid HTTP/model responses. This small cache is optional if omitted honestly; do not claim it exists based on the archive alone.

## 6. Durable audit: request intent is not confirmed delivery

Use the existing run event stream as authoritative; egress.jsonl may be its derived projection. Append and sync a record before any dispatch. If audit persistence fails, do not send. All audit IDs and field names are generated locally, never from arbitrary request/response strings.

Persist these states with one linked audit_id:

1. denied/unavailable: reason_code and safe config summary, transport_invoked=false, sent=false. Do not log the rejected raw payload, rejected key names, goal or credential.
2. prepared: exact approved body, payload hash, constant destination, request alias, question version, mode, budget reservation; transport_invoked=false, sent=false.
3. dispatch_started: record immediately before calling transport; transport_invoked=true, sent=unknown until an outcome. This documents intent/possible delivery without claiming a response was received.
4. response_received: HTTP status code, bounded validated model/usage fields and payload hash; sent=true because a server response proves request dispatch. Validate scientific/advisory content separately; a 400/401 still means the request was sent.
5. transport_failed: safe error enum; transport_invoked=true, sent=unknown. A timeout/connection exception does not establish whether the peer received the request.
6. cache_hit: normalized cache reference and safe decision, transport_invoked=false, sent=false.

Use a tri-state sent value (true | false | unknown) or an equivalent explicit delivery enum; never set sent=true solely because mode=online. On restart, dispatch_started without an outcome remains delivery_unknown. Do not automatically replay it as though it was never sent. The parent-authorized single smoke must not silently retry after an ambiguous transport failure.

Raw local run events may contain imported structures under M0's local object policy, but egress records contain only the strict outbound body and safe metadata. Credentials never appear in either stream, cache, API error, frontend, report, source-control changes or test output. Error redaction is construction from safe enums/status numbers, not optimistic truncation of arbitrary exceptions.

## 7. Credentials, errors and bounded fallback

Resolve the key server-side from the existing approved environment/.env loading arrangement or optional keychain helper. Do not read it for local mode. Attach it only as the Authorization header inside the transport boundary; never include request headers in serialized diagnostics. Tests use a sentinel key and scan all produced artifacts for it. No test loads the real .env.

Use a configurable finite HTTP timeout, bounded by the M2 remaining wall budget (for the minimal smoke, at most 15 seconds is sufficient as a policy default). Disable library-level retries. One adapter invocation makes at most one HTTP attempt. HTTP 408/429/5xx and timeout/transport exceptions are typed transient; 400/422 are input_invalid; authentication, credit and other nonrecoverable status failures are fatal/unavailable for this optional adapter. Return static messages such as external_timeout or provider_http_error plus integer status, never str(exception), response.text, response.content, request repr or response headers.

The selected decide_inspection_view wrapper falls back once to the local rule on unavailable/denied/invalid/failed model results; it does not repeatedly ask Jev for a favorable answer. If a future driver explicitly retries transient failures, it must use M2's shared recovery counters and charge each actual request. That driver is not required for this MVP. Missing configuration/key in local operation is not a whole-app fatal error.

Budget reservation precedes dispatch and is durable. Bound the approved request size and one-call allowance; settle actual valid reported usage once against that reservation. Use the Decisions HTTP fields explicitly:

| HTTP response field | Local meaning and validation |
|---|---|
| usage.input_tokens | Reported input token count; nonnegative safe integer, rejecting booleans, strings, fractions, NaN and Infinity. |
| usage.output_tokens | Reported output token count with the same validation. |
| Both token fields present and valid | external_tokens = input_tokens + output_tokens, with checked integer addition. Retain the components as provenance. |
| usage.cost | Reported cost charged to the run's usd axis; finite nonnegative numeric value, excluding booleans/strings. Preserve the reported value and do not replace it with a price estimate. |

Do not parse chat-completion prompt_tokens/completion_tokens or SDK camelCase inputTokens/outputTokens as fallback HTTP fields. The SDK's camelCase names are an adapter transformation, not the wire contract. A complete fixture must use the documented snake_case Decisions fields. Unknown response/usage fields are discarded, never copied into events or used as authoritative totals.

Settle known axes independently: valid cost can be settled even if one token count is missing, and valid token totals can be settled if cost is missing. An absent/invalid component makes that axis unknown; do not compute a partial total with a fabricated zero. Retain the conservative reservation for unknown axes under the existing policy. If actual reported usage exceeds the reservation or remaining limit, record the actual usage/overrun, checkpoint and prevent another dispatch; do not clamp it to make the budget appear respected. Parsing a model mismatch or invalid choice must still retain any safely validated usage and the original delivery audit. Reopen and repeated normalization cannot settle one response twice. Missing usage is unknown, not a fabricated zero: retain a clearly labeled conservative reservation and prevent further online spending until reconciled or explicitly acknowledged. An HTTP/transport failure after dispatch can still incur cost, so it cannot silently refund a possible spend. The minimal live smoke records the actual returned usage if available. No price estimate is described as actual cost.

## 8. Bounded acceptance evidence

Implement these cases in the existing test_llm_egress.py entry point, using sentinel credentials and an injected transport:

1. local_only/dry_run/missing configuration make zero transport calls; the key resolver is not touched for local modes; the rule decision is usable and labeled.
2. Projection from a real measured interaction produces only the fixed aggregates and keeps evidence local. Empty contacts produce a scientific-null summary action.
3. A parameterized hostile input suite covers extra keys, arbitrary-key coordinates, arrays of any length, embedded/mixed-case sequences, Unix/Windows paths, filenames and instruction text. Unknown fields and unsafe string-valued numeric fields cannot reach the transport or the denied audit body. Add source-name/goal injection to the measured object's extra metadata and verify projection excludes it.
4. Static questions/provider/destination cannot be overridden through user data. Sent body has no messages, raw context or identifiers. Redirects do not trigger a second credential-bearing request.
5. A documented alias->snapshot response with type=choice is accepted and both IDs retained; missing/unlisted model, absent/wrong answer type, malformed answer, oversized body, unsafe raw error and NaN response are rejected with a labeled fallback and no leaked body/key. SDK-optional model metadata does not weaken the deliberate required-model policy.
6. Audits distinguish denied, cache hit, dispatch with response, and ambiguous timeout; a persistence failure prevents dispatch and interrupted dispatch is not replayed automatically.
7. One invocation makes at most one HTTP call; timeout respects remaining budget; failed/unknown usage does not silently appear free. A valid fixture with usage.input_tokens/output_tokens/cost settles each known axis once, including when the decision is rejected for model mismatch. Chat token-field aliases, fractional/boolean counts and missing components cannot create false totals; over-limit actual usage is recorded and checkpoints rather than being clamped.
8. A valid online cache hit, if implemented, makes zero calls and zero new charges; changed question/provider/mapping invalidates it; local mode still uses rules.
9. Scan events, egress projection, cache, returned errors and decision output for sentinel key, hidden path, sequence and raw provider error. Only the known safe numeric state and static request text may appear in outbound/audit payloads.
10. Parent-run authorized live synthetic smoke records requested/served model, exact sanitized body hash, response validation and actual/unknown usage without dumping headers or raw secrets. A failed connection remains an honest unavailable result; successful transport alone is not a scientific quality benchmark.

M3 is not complete merely because the archive's sanitizer tests pass. The proof is transport-level denial and strict useful projection through the same boundary used by the real adapter. Frontend no-third-party network evidence remains part of the existing phase gate.
