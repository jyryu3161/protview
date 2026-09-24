# ProtView architecture

Design owner: GPT-6 Astra. Implementation owner: GPT-6 Sol.

## Selected product

A locally running, single-user workspace imports PDB or mmCIF files, prepares a selected model deterministically, renders the real structure in Mol*, measures geometric contacts, and creates traceable reports. Humans and rule-based workflows use the same validated tools and event log. An offline workflow is complete without credentials or licensed software. Optional model and energy integrations disclose availability instead of manufacturing outputs.

The archived workspace supplies a useful visual language and module layout, but its mocked dashboard, SVG viewer and unimplemented worker protocols are not a finished product. Keep the dark/light tokens, compact shell, handle chips, step timeline and inspector; replace their data sources with runtime results.

## Components

- frontend/: Next.js/React, locally bundled Mol*, imported design tokens and reusable components. The main page contains upload/run controls, structure viewport, model or residue selection, interaction table, timeline and report access. Runtime scientific numbers come from backend handles.
- backend/mw/api/: FastAPI boundary, loopback by default. Run creation, file upload, tool commands, typed handle metadata/materialization, structure bytes, events, capabilities, jobs and report endpoints.
- backend/mw/tools/: a small registry of versioned tools with parameter schemas, accepted handle kinds, output kinds and cost classes. All human and workflow execution enters the runtime.
- backend/mw/core/: identifiers, canonical objects, content hashes, append-only events and derived SQLite indices.
- backend/mw/runtime/: call state, retry policy, guards, budget reservations/checkpoints, dry-run planning and resume.
- backend/mw/egress/ and llm/: a single outbound boundary and optional HTTP model adapter. The ordinary pipeline uses rules in local_only.
- backend/mw/jobs/: local durable queue, isolated subprocess workers, timeouts and capability discovery for optional PyRosetta.
- scripts/, phases/: adapted generic implementation harness, kept separate from the scientific runtime.

## Scientific contract

Import actual bytes, validate the format and reject empty or malformed structures. Preserve the source as an immutable local object. Select the requested model explicitly. Residue references carry chain_auth, chain_label, seq_auth, seq_label, icode, resname and model identity. Label IDs may be unavailable for PDB or non-polymers; null means unknown and must never be invented. Human labels use auth IDs; strings are display only, never an identity parser.

Preparation supports only implemented operations. Deterministic highest-occupancy altloc selection needs a stable tie-break and a test where A is not the winner. Keep shared atoms correctly, retain or strip water/hydrogen as requested, and record the selected model, original structure handle, removed counts and every policy in a preparation_manifest handle. Prepared mmCIF output must preserve identifier mappings; converting all inputs to PDB is not acceptable when it loses them. Protonation, missing-atom reconstruction and symmetry expansion are unsupported unless a real tested adapter is present. Reject those requests explicitly; recording a requested action as though applied is forbidden.

Geometric contacts use actual atom coordinates, a declared cutoff, explicit selection semantics and a deterministic ordering. Report contact or qualified geometric contact categories; N/O proximity alone does not establish a hydrogen bond. Record both residue and atom identities and measured distance. Multiple ligand instances must not be silently merged by residue name. A valid selected structure with no qualifying contacts returns an empty interaction_set with null_result=true, not a retryable failure. Invalid selection is input_invalid.

Every scientific table declares method, version, limitations and units. Energies are absent when no real supported engine exists. A geometry-based candidate score, if offered, must retain that name and never become ΔΔG or affinity.

## Objects and events

Object content is canonicalized and hashed with kind and schema using full SHA-256. Stable object identity excludes timestamps and call IDs; producer provenance belongs to events/metadata. A call cache key includes the tool name/version and normalized effective arguments, including preparation and seed settings. Do not conflate content hashing with call caching.

A handle envelope contains handle, kind, schema, summary, at most five preview rows, produced_by and null_result. Enforce accepted kinds before tool execution. Materialization is local, paginated, bounded and projection-aware; unknown handles and invalid columns fail clearly. Raw structure bytes are a viewer-only local endpoint and are not compact-state material.

For this small-structure MVP, object creation events carry enough payload and metadata to rebuild every object. Replaying into an empty directory rebuilds bytes, indices, completed calls and handle identity without original source files, network access or scientific recomputation. This deliberately favors correct recovery over event-log size. Future large trajectories require a revised durable blob policy and are out of scope.

Events are append-only and ordered. Object persistence, event append and index update must have a documented recoverable ordering; indices are disposable. Handle tampering or corrupt payload hashes must fail rather than being trusted. Resume must restore consumed budgets and approvals; interrupted work is not silently considered complete.

## Runtime contract

Execution order is validate -> identify/cache -> guard -> approval/budget reservation -> running event -> execute -> durable result/failure -> charge/update. Failures include transient, input_invalid, precondition, resource_exceeded and fatal. scientific_null remains a success marker. Transient failures receive bounded exponential retries; changed-argument repair and prerequisites have separate bounded attempts. Same-argument input repair is forbidden. Resource/fatal failures are not automatically retried.

Count submitted expensive attempts, including failures, toward the limit. Enforce elapsed time for every call class, including retries/backoff and waiting. Repeated cache reads must not make an autonomous loop appear to progress; cache lookup itself remains safe and idempotent. Track repeated calls, no new handles and oscillation separately. Dry-run emits clearly identified planned actions and never falls through to the expensive implementation when a stub is missing. No synthetic energy table becomes scientific evidence.

Product approval gates pause before the first expensive action and checkpoint when budgets are exhausted. Their resolution is an explicit recorded action. They are not additional developer approvals. Keep cancellation and timeout terminal and kill the associated worker process. A durable local queue records submitted/running/done/failed/cancelled states and reconciles interrupted jobs on restart.

## Local-only boundary

The app works with networking blocked except localhost. Fonts, scripts, styles and sample structures are local assets. The default mode is local_only; dry_run also forbids outbound calls. Only the egress gate may authorize an external HTTP adapter. Database lookups count as outbound requests too; they are optional and must not bypass the gate.

Build compact state from an allowlisted schema of summaries and selected measured scalars. Do not recursively copy arbitrary object metadata, goal text or freeform strings into an outbound prompt. Block coordinates, raw structure contents, complete sequences, local paths and original filenames; never log credentials. Denied attempts and sanitized allowed payloads are locally auditable. Record attempted versus actually sent requests accurately. online availability requires explicit configuration; missing keys/model pins produce a clear unavailable state and local rule fallback.

## Reports and UI

Reports cite each quantitative result through structured evidence: handle, row or field path, unit and rendered value. Validate against that specific field, not against a bag of numbers where the wrong residue or unit can accidentally match. Rules can generate the entire report offline. Optional language-model explanations cannot add unsupported measurements or scientific claims.

UI states are loading, ready, empty scientific result, failure and unavailable capability. An unavailable PyRosetta panel has no numeric placeholder. Clicking a real interaction selects/focuses its actual residue; displayed chain numbering includes insertion codes. The viewport supports actual structure loading and representation changes, and selection is synchronized where exposed. Only implemented controls are actionable. Reports, jobs, mode and budget displays reflect server state.

## User-authorized method extension after the accepted MVP

M6/M7 add real alternative calculations under docs/ALTERNATIVE_METHODS_CONTRACT.md. FreeSASA computes explicit protein–ligand SASA and burial in Å² through the bounded local Run.call lane. OpenMM computes explicit protein-only Amber/GBn2 potential/minimization in kJ/mol through a fixed production adapter on the reviewed durable job supervisor. These methods have separate capability/protocol names and scientific result types; unavailable Rosetta methods are not relabeled as supported. New method reports preserve all old report_manifest@1 bytes and bind their own complete quantitative evidence. Existing local-only, identity, recovery, approval/accounting and process ownership boundaries remain authoritative.
