# ProtView implementation decisions

Reviewed by GPT-6 Astra on 2026-09-24. Inputs: root agent_protein_viewer_plan_v05.md, archived mw/docs/plan_v0.6.md, brand-book.md, frontend components/page and backend core/runtime/structural/egress/worker/verifier implementations.

## D01 — Adopt the scaffold selectively

Keep the archive as source evidence and import its useful frontend/backend layout, design tokens and component vocabulary. Do not treat imported tests, comments, mock numbers or TODOs as acceptance evidence. The main archived page imports mock/run, shows 47 contacts and uncomputed energy values, and renders an SVG placeholder; all must be replaced on the production route. A labeled gallery may retain design fixtures.

## D02 — Preserve the runtime-first M0–M5 sequence

M0 establishes real objects and preparation; M1 establishes real visualization and geometry; M2 makes execution resumable and bounded; M3 proves offline boundaries and optional model behavior; M4 adds honest optional energy jobs; M5 closes reporting and integration. A phase is complete only with actual checks and Astra review. Work may prepare independent scaffolding concurrently, but later phase acceptance does not waive earlier gates.

## D03 — Scientific baseline is geometry, not chemical certainty

The archived N/O-distance heuristic labels contacts hbond and salt_bridge without hydrogen directionality or ligand chemistry. Rename and document it as geometric contact evidence. The supported MVP computes actual distances and selections. ProLIF/PLIP, pocket detection and protonation are capability-gated follow-ups until real adapters and mapping tests exist. There is no fabricated surrogate for these capabilities.

## D04 — Identity and preparation are strict

Use gemmi for PDB/mmCIF. Retain both author and label identities, insertion codes and model identity; unknown label fields remain null. Keep prepared mmCIF when needed to avoid PDB information loss. Fix highest-occupancy selection rather than the archive's keep-first behavior. Explicitly reject unsupported preparation policy values. Every preparation result links an accurate manifest.

## D05 — Make events-only recovery true

The archived replay reruns calls and requires source files to still exist, contradicting the reference's events-only recovery criterion. For bounded MVP structures, persist complete object payloads in object events and rebuild objects/indices without recomputation. Full SHA-256 replaces truncated object identity. Large trajectories, streaming and log compaction are deferred.

## D06 — Default to an entirely local workflow

Adopt local_only by default with locally hosted fonts and Mol* assets. All external requests, including optional database fetches, must pass one gate. Prefer schema allowlisting over the archive's key-name-only filtering, which can miss coordinates or sensitive strings under other keys. Record attempted/sent distinction. Freeform goals are local unless transformed to approved compact fields.

OpenRouter is optional. No invented Jev pin or CHANGE_ME model is enabled. Parent-agent source verification identified the official Jev decisions endpoint (POST /api/alpha/decisions), with the typesafe/jev-1.13 request alias and a dated snapshot such as typesafe/jev-1.13-20260917. Treat this as a separate adapter contract from chat completions. Record both requested and served model; allow only an explicitly configured alias-to-snapshot mapping verified during the live check rather than blindly accepting any mismatch or rejecting every valid dated snapshot. Before that API check passes, do not advertise this adapter as live-validated. Source: https://openrouter.ai/blog/insights/what-is-jev/ (parent verified 2026-09-24). A configured HTTP adapter is fixture-tested without credentials. The user subsequently authorized use of an OpenRouter API key: perform one minimal live connectivity smoke through the gate with an explicit model pin and synthetic compact state, record the served model and actual result, and keep the credential only in the ignored root .env with mode 0600. The parent agent owns that live check. Rules still handle the selected inspection/report pipeline offline. A successful connection does not establish model quality; paid scientific benchmark runs remain deferred.

## D07 — Missing PyRosetta is a real unsupported capability

The archive's worker only contains TODO protocols. Do not advertise estimate_stability, Cartesian ddG or interface analysis as working merely because PyRosetta imports. Implement a durable isolated job contract, timeout/cancellation/budget behavior, and any real supported protocol separately. Each advertised protocol requires an actual implementation and relevant validation. Without a licensed installed engine, production requests return structured unavailable/precondition information; no energy result is generated. Dry-run planning is not a substitute for energy validation.

This MVP may complete with PyRosetta unavailable because the user explicitly permits selective adoption of the reference. The delivered capability matrix and report must say exactly which protocols remain unavailable and why. Mutation optimization and a scientific stability ranking are deferred if their required engine is unavailable.

## D08 — Evidence-bound offline reports

Generate a useful inspection report from actual prepared structure and measured contacts. Each quantitative statement cites a handle and field, with unit and method. The archive's global number-list verifier is insufficient: the same number from a different residue or unit cannot validate a claim. Optional generated explanations require structured evidence validation; unsupported sentences are dropped or clearly rejected. Final candidate selection is not manufactured when no candidate workflow exists.

## D09 — Keep the design useful and honest

Adopt the dense dark/light shell, status glyphs, provenance tags, handle chips and neutral scientific_null treatment. Keep Korean descriptions with tool identifiers unchanged. Replace mock counts, timing, budgets and energy tables with runtime values or explicit unavailable states. Provide real file loading, viewport rendering, representation control, residue/interaction focus, events and reports. Hide or disable controls whose operation is not implemented. Do not ship dead demo buttons as product features.

## D10 — Harness is borrowed; scientific domain is not

Bring only generic phase executor, hooks, command templates and their relevant tests from ../kbase_kinase. Adapt project paths, checks and model defaults. Never import kinase-specific scripts, data, prior results or domain claims. Existing user changes must survive execution; no whole-worktree staging by accident, no implicit push and no approval/sandbox bypass flags.

## Deferred scope

Multi-user accounts, cloud deployment, public sharing, AG-UI/A2A, plugins, GUI pipeline editing, MD trajectories, PAE analysis, conservation databases, comprehensive pocket methods, remote structure lookup, multi-model comparative analysis, Rosetta mutation design and unvalidated energetic protocols are outside the selected release unless explicitly added with implementation and evidence. These omissions must remain visible in capability documentation; they do not justify weakening the implemented local viewer/runtime contracts.

## D11 — User-authorized alternative local methods after M0–M5

The subsequent user request adds real FreeSASA protein–ligand exposure/burial geometry in M6 and OpenMM protein-only Amber/GBn2 potential/minimization in M7. They have distinct names, units, preparation assumptions, runtime lanes and reports; neither substitutes numerical values into Rosetta/ΔΔG/affinity labels. Follow docs/ALTERNATIVE_METHODS_CONTRACT.md and the protview-methods phase group. Existing optional Rosetta protocols remain honestly unavailable. New capabilities require actual product-path scientific and lifecycle evidence, not import detection. Historical report bytes and local-only behavior remain preserved. Before M6 approval, independent single/separated-sphere tests rejected FreeSASA2.2.1 Shrake–Rupley1000 output. M6 now fixes Lee–Richards100slices/probe1.4Å/thread1, which passed analytic checks; retain the failed engine evidence and do not patch numbers. The contract defines precise algorithm metadata and0.5% analytic overlap tolerance.

## D12 — Honest Git history and current review scope

M0–M5 used phase gates and Astra reviews without per-phase Git branches/commits. Commit d22fe15 on master is the actual completed baseline, not reconstructed history. Extension work starts on phase/m6-interface-sasa; after its real accepted commit, phase/m7-openmm-minimization starts from it. Parent records actual commits only. Shared-source modifications can stale earlier review hashes: refresh affected gates or document a complete extension supersession before describing current verification; do not edit old scientific results or pretend stale completion is fresh.

## D13 — User-authorized real viewer agent and offscreen acceptance

The new user request after accepted M7 baseline e0abffc requires actual prompts to control the local viewer through a real model. Add one typed viewer-intent Decisions adapter using the existing verified Jev pin/endpoint; do not masquerade rules as model output. Explicit user prompt text and safe identifier aliases are newly allowed only in this dedicated projection with visible online consent, limits and audit. Original files/coordinates/sequences/credentials remain local and scientific approval is not inherited from viewer consent. Mol* acknowledgment distinguishes planned from applied actions. A real Electron offscreen renderer, positively verified with isOffscreen and paint/WebGL evidence, is selected after Orca's available hidden-tab controls could not establish actual offscreen mode. Implement/fix and click-test all mounted product controls; preserve failures and unavailable-case evidence. Details and scope limits are authoritative in the two M8 design documents.
