# M5 offline inspection and evidence-report contract

Design: GPT-6 Astra, 2026-09-24. Scope: finish the selected local inspection workflow and export an honest report from actual run objects. RUNTIME_CONTRACT.md, EGRESS_CONTRACT.md and JOBS_CONTRACT.md remain authoritative. No scientific ranking, agent chat, cloud sharing, DOCX production, new energy protocol or new remote language-generation dependency is added.

## 1. Offline inspect_complex is a bounded workflow

Implement inspect_complex as a deterministic driver over the existing validated Run.call path, not a parallel set of scientific functions that bypasses handles, contracts, cache, budget or event provenance. Its normalized request identifies one local upload or an existing structure/prepared_structure handle from this run, explicit model index when loading, supported preparation policies, an optional exact ligand selector, cutoff_A and geometric types. An HTTP caller cannot provide a filesystem path, remote URL, arbitrary YAML, tool name or executable. Reuse the verified-upload boundary from M1.

A suggested internal sequence is:

1. For an upload, call load_structure with verified bytes and the selected model. For an existing structure/prepared handle, resolve/hash-verify it; do not reload the original file or silently apply a different model.
2. If not already prepared, call prepare_structure with the normalized explicit policies. For a prepared input, use its linked manifest and do not claim newly requested incompatible policies were applied. Reject a conflicting request or require a new explicit preparation.
3. Resolve ligand candidates from that prepared object. Use the supplied exact residue reference or select automatically only when precisely one candidate exists. Multiple candidates return needs_selection with real choices; none returns a clear no_ligand/precondition result. Neither case is a measured zero-contact result.
4. Call compute_interactions with that exact prepared handle, ligand and parameters. A successful empty interaction handle completes the measurement normally; no cutoff expansion or automatic retry to seek a nonempty result.
5. Build a verified local inspection summary/report from those handles. compile_state may be used if its actual implementation preserves the source references, but its generic text/preview is not the scientific evidence authority. Resolve measured rows from the immutable interaction object.

Fix the archived pipeline's unsupported waters=keep_bridging; choose the same declared defaults as the supported UI/API (for example strip_all explicitly), preserving them in the manifest. Do not invent a bridging-water calculation. Pipeline version, normalized request, parent workflow ID and child call IDs are durable. Run.call internal attempts follow M2 finite recovery and shared budget; unavailable optional modules are not prerequisite repairs. A pipeline cancel/checkpoint stops subsequent calls and retains completed input/result handles.

A stable workflow ID plus per-step progress prevents resume from presenting old calls as new physical work. Resume resolves recorded outputs and runs only missing authorized steps through Run.call; validation/cache/recovery/loop accounting follows M2. Mark calls as pipeline provenance, with an explicit bounded driver mode/branch; decided_by alone is not authority. A new human repeat may reuse verified cache results without resetting the run's budget or falsely claiming new measurement. A failed step returns the linked typed outcome, not a successful report with invented defaults. Useful partial reporting may still describe the completed structure/preparation with the failure explicitly recorded.

The ordinary pipeline and report render are entirely local, whether or not a Jev key is configured. M3's optional view suggestion can be shown as separate labeled advisory metadata if explicitly invoked. It is not a source of scientific report facts and report generation does not trigger new model requests.

## 2. Report request and immutable artifact

Suggested functions, adaptable to existing module names:

- inspect_complex(run, request) -> completed inspection references or bounded needs_selection/checkpoint/failure state.
- build_inspection_report(run, interaction_handle=..., prepared_handle=...) -> validated report_manifest@1.
- validate_claim(store, claim) -> validated rendered statement or rejection with a bounded reason.
- render_report(manifest) -> UTF-8 Markdown plus machine-readable JSON manifest.

The normal complete-report request names one selected interaction handle; derive its exact prepared structure/manifest/ligand/parameters from the interaction envelope. If an explicit prepared handle is also supplied, it must match. Do not combine latest structure metadata with a historic interaction table. A partial report names an actual prepared/loaded handle and a linked failed/pending step; it must state which measurement is absent. A missing handle, wrong run, corrupt payload or unresolved linkage fails report generation rather than silently substituting another run object.

The immutable report manifest binds schema/render version, report status (complete | partial), selected input/result handles, preparation manifest, methods/versions, evidence-bearing claims/table rows, capability snapshot and its event/time context, and local provenance references. Snapshot optional budget/decision/job state at a specific event sequence; reopening an old report does not rewrite it with later costs, capabilities or results. Generation time/creator is provenance, not an experimental number. Store artifact content through the same immutable object/event mechanism as other selected small-workload objects so it can be restored without recomputation. A later explicit regeneration creates/reuses the appropriate new report object rather than mutating the old one.

A useful report contains:

- Which source/prepared object and model were inspected; author/label/insertion identifiers remain distinct, and missing label values remain unknown.
- Preparation choices and limitations, selected ligand identity, geometric method/version, cutoff and requested contact classes.
- Measured atom-pair count, distinct contacting-residue count, minimum distance when defined, and a contact table with residue/atom identity, geometric label and distance in Å. Compute summaries from rows and verify them; do not trust unrelated summary metadata.
- Evidence/provenance references sufficient to identify the exact local objects and calls, plus the actual optional capability matrix. Missing/unimplemented energy protocols have a reason and no numeric placeholder.
- Errors, incomplete steps, scientific-null status and method limitations where applicable. Distances and geometric polar/hydrophobic labels are not validated hydrogen bonds, affinity, ΔΔG or biological efficacy.

The download should be useful without a running server: Markdown with a clearly labeled measured table and provenance, plus a downloadable JSON manifest for exact values/evidence. Include all rows for the selected bounded MVP object, or disclose an explicit table truncation/count with a complete companion JSON dataset; never call a five-row preview the full result. No image capture, PDF or office conversion is required. Use a server-generated safe filename and Content-Disposition; never write to a user-supplied path. Local identifiers in the report are authorized local content, not permission to send them to a model. Exclude credentials, original absolute input paths, raw environment and unrelated goal/context fields by default.

## 3. Quantitative claims bind a specific location

Replace the archive's global-number-pool verifier as the acceptance mechanism. A matching number elsewhere in a run cannot validate a claim. Use a small typed statement schema; render prose from approved templates after validation. A suggested Claim has:

- statement_id from a fixed local template enum, such as contact_distance, contact_count, contacting_residue_count, minimum_distance, cutoff or selected_model;
- source_handle including immutable hash and schema/kind, plus a whitelisted field path;
- for row statements, a stable row index within that immutable object and asserted residue/atom identity (or row fingerprint), not just a residue-name string;
- quantity and unit, exact_value, rendered_value and declared formatting rule;
- subject references (prepared structure and ligand; row residue/atom identities when relevant) and, for derived claims, the approved operation.

Resolve evidence only through the store, not caller-supplied alleged contents. Allowed paths are specific implemented fields (for example rows[i].distance_A and parameters.cutoff_A), not arbitrary Python expressions. The source handle hash fixes row order/content; validate the row selector and subject identity against it. Cross-check envelope structure/selection/method linkage. A numerically equal distance for a different residue, ligand, atom pair or structure does not support the statement.

Derived evidence uses only reviewed operations over that same immutable rows array: count(rows), count_distinct(collision-safe residue identity), minimum(distance_A), and counts by implemented type. Recompute these operations when validating the report. A derived claim names both source and operation; no arbitrary formula evaluator or freeform aggregate name. For zero rows, the first two counts are zero and minimum is null/undefined. Null is never converted to 0 Å or an energy value.

Unit validation is semantic: distance/cutoff uses Å; counts are integers with a quantity distinguishing atom pairs from residues; model numbers are identifiers rather than physical measurements. REU requires an actual validated energy protocol and cannot validate Å or kcal/mol. Numeric-looking residue IDs, run IDs, dates, schema versions and model pins are not scientific quantities to be collected in a number bag. Model 5 must not accidentally substantiate five contacts.

Keep the underlying finite numeric value in the JSON manifest. Render contact/cutoff distances with a single checked-in policy (for example Decimal(str(value)) quantized to 0.01 with ROUND_HALF_UP, preserving two decimal places). Compare a proposed rendered value to the exact output of that formatting policy, not a global ±1% tolerance. Counts must match exactly. Normalize presentation of negative zero if relevant and reject NaN/Infinity. Rounding 2.6264474104767457 Å to 2.63 Å is valid for that field; 2.62 Å is not under this policy. Optional extra precision uses a declared bounded format, never a tolerance chosen to make a claim pass. Display rounded numbers does not alter stored measurements or classify contacts using rounded distances.

## 4. Language, nulls and errors

The supported report language is deterministic local templates plus escaped identifiers and validated evidence slots. Static limitations such as “geometric proximity does not establish a hydrogen bond” need no fabricated evidence citation. Freeform text is not marked validated merely because it has no numeric token.

If an optional explanation path is retained, it must submit structured approved statement IDs with evidence bindings, not arbitrary prose to be approved by scanning numbers. Validate each statement and render the final wording locally. Reject unsupported predicates such as stabilizes, stronger affinity, causal mechanism or best mutation even if all embedded numbers happen to match. Record dropped/rejected statement reason codes without inserting the rejected scientific assertion into the final report as accepted text. User annotations, if retained, are explicitly labeled unverified and separated; they do not become evidence. The M3 Jev view-choice API does not provide a new explanation-generation capability.

A measured empty interaction object gives a complete report with zero contact/zero contacting-residue counts, no contact rows and an explicitly undefined minimum. A failed fetch, absent measurement, invalid ligand or worker error gives a generation error or an explicitly partial report; it never becomes scientific_null. Optional unavailable energy/pocket protocols do not make an otherwise complete selected geometric inspection incomplete: state their capability limitations without a score/rank placeholder. A retry or model fallback is provenance, not improved scientific evidence.

HTML previews must escape identifiers and source strings; do not render raw uploaded names or explanation text as executable HTML. Markdown rendering must not turn untrusted text into remote images/scripts or automatic network fetches. The main report download/preview remains local_only and works with no key or external network.

## 5. Final UI flow and recovery

Add an actionable report control for the selected successful interaction in the Inspector. Show which structure/result it uses. Generating while inspecting a historic interaction must export that exact result; changing run/selection during fetch must not show or download another selection's artifact. Key pending/ready/error state by run and selected handle, and clear stale state. A partial report, if exposed, is visibly labeled and never the default replacement for a failed complete report.

Expose report preview and local Markdown/JSON download, report provenance and optional capability limitations. Reopen the stored run and recover its saved report references/artifacts from events; report reads do not rerun structural tools, energy jobs or external requests. After deleting original uploads/object files/SQLite in a temporary test run, events-only reconstruction must recover the selected structure, interaction and report bytes. If a report was never generated, its construction from recovered immutable evidence is a new explicit local report action, not recovery of a nonexistent artifact.

The final selected flow is upload -> explicit model/preparation -> ligand/cutoff -> measured contacts -> correct residue focus -> report preview/download -> reopen the same report. inspect_complex provides the bounded deterministic API/workflow equivalent; it does not remove the explicit selection required by an ambiguous structure. Continue to hide/disable unimplemented energy/ranking actions rather than presenting them as completed work.

## 6. Bounded acceptance evidence

Add focused report/workflow tests under the existing backend/tests entry point and exercise the final browser flow. No new AC command or paid benchmark is required.

1. Real local PDB/mmCIF fixture through inspect_complex uses actual Run.call outputs and preparation policies; no mock counts. Repeated/resumed workflow reuses verified outputs, preserves child provenance and never resets budget/recovery counters. Unsupported keep_bridging is not silently accepted.
2. Two ligands require exact selection; no ligand returns a distinct no_ligand/precondition outcome; neither becomes zero measured contacts. Selected-ligand contacts and valid empty contacts generate correct complete reports.
3. Validate one contact claim; then hold its rendered number constant while independently changing source handle, row/atom/residue, structure/ligand, field, unit and quantity. Each mismatched binding is rejected, even when that number exists elsewhere.
4. Count and distinct-residue aggregates recompute from actual rows. Minimum is correct for nonempty rows and absent for empty; no NaN/Infinity. Test rounding boundary and full precision, exact integer counts, and rejection of an unjustified ±1% near-match.
5. A missing/corrupt handle, failed row read and incomplete workflow never produce scientific_null or substitute latest results. Partial output, if supported, states the missing measurement and contains no invented count/minimum.
6. Structured explanations with unsupported predicates/evidence are rejected; number-free claims of affinity/stability are not accepted. Plain text injection/HTML/remote-image strings are escaped or excluded and never trigger transport.
7. Capability snapshot truthfully lists missing/unimplemented energy protocols with no energy/ranking values. Fixture job output and dry-run plan cannot validate an energy claim. M3 advisory choice remains separately labeled and does not cause a report-time model call.
8. Exported Markdown and JSON agree on selected input, counts, units and formatting; all rows or explicit truncation plus complete dataset are present. Sentinel secret/path/environment values cannot appear through generic metadata copying. Safe download filename and local-only rendering are checked.
9. Save a report, remove original source/uploads, objects and disposable indices in a temporary run, reconstruct from events, and compare recovered report/evidence bytes. Reopening calls no scientific/external worker; later new measurements do not rewrite the saved report.
10. Parent final browser pass on an actual public structure verifies correct row focus, selected-result report preview/download, a historic-result report in a two-structure run, error/empty distinctions and reopened report. Record zero nonloopback requests for the offline path and actual source/hash/result evidence; lifecycle fixtures and smoke connections do not become scientific benchmarks.

The final release review also checks README install/start/check commands, declared runtime versions, source-reference preservation and adopted/deferred capability documentation. Optional licensed energy validation is not required when availability is accurately false; no overall completion claim may imply those protocols were exercised.
