# Post-M8 product roadmap

Design owner: GPT-6 Astra. Written 2026-09-27 against accepted M8 source `392d45a`. **All work below is proposed and pending.** This document creates no completed phase, implemented capability, scientific result, or permission for additional provider calls. GPT-6 Sol implements; Astra reviews scientific contracts and completed implementation; the parent owns phase recording and Git transitions.

## Established scope and remaining gaps

The selected release already provides local PDB/mmCIF import, explicit model/preparation choices, actual Mol* rendering and residue selection, geometric contacts, FreeSASA protein–ligand exposure/burial, bounded protein-only OpenMM minimization, immutable reports, event recovery, and bounded optional model-directed viewer actions. The 86-item M8 ledger includes deliberate unavailable/error outcomes, not 86 scientific methods. Current integration evidence belongs in a new dated record; historical acceptance remains historical.

The original `agent_protein_viewer_plan_v05.md` also proposes snapshots/restore, general measurement/alignment, pocket detection, chemically typed interactions, conservation, comparative models, mutation proposals/ranking and broader agent orchestration. Those are not silently included in completed M0–M8. The selected decisions explicitly defer them. Gallery sequence/PAE/energy/mutation panels are labeled design fixtures, not implemented analyses. There is no selected-release defect merely because an aspirational tool is absent.

## Recommended order

| Priority | Proposed increment | User outcome | Dependencies | Status |
| --- | --- | --- | --- | --- |
| P1 | M9 — saved local scenes and figure export | Return to an exact view and export a traceable image | M8 exact source/session identity | Pending |
| P1 | M10 — direct measurement and structural comparison | Measure selected atoms and compare two explicit structures | M9 reusable scene schema; atom identity contract | Pending |
| P2 | M11 — chemistry-aware interaction adapter | Inspect qualified interaction assignments alongside geometry | Explicit ligand chemistry/preparation contract | Pending |
| P2 | M12 — local pocket proposals | Inspect candidate cavities without a bound ligand | Versioned supported detector and bounded job lane | Pending |
| P3 | M13 — bounded workflow assistance | Ask for a reviewable local analysis plan and approve its execution | Stable M9–M12 handles, protocol capabilities and execution policy | Pending |

The numbering is a proposal. Create actual phase files and pending index entries only when the increment enters implementation. Each requires executable argv acceptance checks, an actual offscreen per-control inventory, current shared-source review hashes and preserved prior report bytes. Do not prefill successful checks.

## M9 — saved scenes and traceable figure export

Deliver a local named scene object containing immutable source handle/model, full selected residue identity, supported representation, finite bounded camera state, theme and schema version. Add Save view, Restore view, and PNG export with a JSON sidecar containing source/scene identity and software versions. The persisted scene is distinct from an intent acknowledgment; restoring it never replays a provider request or scientific calculation. Labels are local untrusted text and never executable paths or egress context.

Acceptance:

- Save and restore original, historical and OpenMM-minimized scenes after reopening; restore actual representation, selection and camera within stated numerical tolerances. A restore creates a fresh valid session and invalidates pending stale commands.
- Reject missing/corrupt/cross-run sources and unsupported scene versions visibly. Missing source never silently becomes the latest structure.
- Capture a loaded actual WebGL frame, complete the real browser download, verify nonempty dimensions and sidecar source identity, and exercise lost-context/loading errors. Do not claim exact cross-GPU PNG hashes.
- Recover scene metadata from events without original paths. Keep exports local, bounded and explicit; old report bytes stay unchanged.

Scientific limit: a screenshot illustrates computed structure state; it is not new measurement evidence. A scene restore is not conformational sampling or trajectory replay.

## M10 — direct measurements and two-structure comparison

First ship atom-to-atom distance with a new atom reference carrying source/model/residue identifiers plus atom name and resolved altloc. Then introduce rigid alignment of two user-selected immutable structures using an explicit atom correspondence table (initially exact user-selected CA pairs). Store transform, mapping, pair count, RMSD, exclusions and method version in immutable result handles. Keep source coordinates unchanged and apply overlay transforms only to a separate display scene.

Acceptance:

- Known coordinate fixtures independently establish distance in Å and RMSD in Å. Translation/rotation fixtures align to the prescribed numerical tolerance; changing actual coordinates changes the result.
- Reject duplicate, missing, ambiguous or degenerate correspondence; disclose omitted atoms. Insertion codes, unknown labels, different chains and model numbers retain exact identity.
- Offscreen two-click measurement resolves actual atoms; source changes clear incompatible selections. Pair selection and overlay toggles agree with result identities and survive reopen/replay.
- Tables/reports cite exact distance/RMSD fields and method. Unaligned comparison and aligned comparison are visibly distinct; no hidden automatic chain pairing.

Scientific limit: RMSD depends on selected correspondence and alignment; it is not a universal model quality, binding, stability or energy score. Automatic sequence alignment and ensemble comparisons require a later explicit contract.

## M11 — qualified chemical interactions

Design a local adapter contract before choosing a supported implementation. ProLIF or PLIP are candidates from the original reference, not presently verified dependency choices. Record exact backend/version, ligand bond-order source, protonation/hydrogen policy, atom mapping and category-specific geometric criteria. Preserve the existing geometric contact tool and its names. Missing chemistry must return unavailable or a qualified partial result; no inference is silently presented as supplied experimental chemistry.

Acceptance:

- Explicit supported-input matrix and capability response precede enabled controls. Unsupported metals, covalent ligands, alternate states or incomplete chemistry have specific reasons until separately validated.
- Author/label/insertion/model/ligand-instance mappings round-trip through the chosen backend, with adversarial fixtures. Analytical geometry fixtures and independently reviewed public examples distinguish plausible positive and negative assignments.
- Reports retain per-contact atom identities, distances/angles and declared criteria with units. Disagreement with plain distance contacts is visible, not overwritten.
- Installation-absent, valid-empty, malformed input, timeout and cancellation paths are tested; no external structure/dictionary download occurs during local_only execution.
- Offscreen controls select exact assigned contacts and display method assumptions. Any required chemical dictionary ships locally with provenance and license review.

Scientific limit: backend-assigned interaction categories are model/geometry-dependent annotations. They do not establish experimental hydrogen bonding, affinity, a salt-bridge energetic contribution or stability.

## M12 — local pocket candidates

Evaluate one real local detector, with fpocket/P2Rank as unselected candidates. Pin the chosen algorithm, parameters and deterministic/seed behavior; use isolated bounded jobs where necessary. Emit a pocket-set handle containing actual geometry, residue membership, detector-native fields and units. Keep ranking explicitly detector-specific. An empty supported result is scientific_null.

Acceptance:

- Actual detector execution on a supplied local positive structure and a documented negative/small case; independent checks reconcile pocket geometry and residue mapping with source coordinates.
- Top-k limit is explicit; full versus truncated results are distinguishable. Historical/minimized/original source bindings cannot mix.
- Real offscreen pocket selection changes the displayed cavity/residue set; cancellation, restart, budget, unavailable binary/model asset and malformed output have truthful terminal outcomes.
- Reopening/replaying uses stored objects without rerunning the detector. No remote weights, database fetch or hidden model request is needed.

Scientific limit: a proposed cavity is not proof of a ligand binding site or druggability; detector scores are never affinity estimates. Benchmarks and any quality claim require a separately specified evaluation dataset and metrics.

## M13 — bounded analysis planning and execution

Add a local deterministic plan format first, separate from viewer intents. It may refer only to supported typed tools, same-run handles and explicit preparation decisions. Display the concrete steps, estimated limits and unavailable prerequisites before execution. Model assistance remains optional and requires a separately reviewed projection/consent contract; M8 viewer consent must never authorize scientific tools or expose additional molecular content.

Acceptance:

- Dry-run produces only labeled plans; execution follows ordinary runtime guards, actual cost reservation and scientific approval. A model cannot choose arbitrary tool names, shell commands, URLs or paths.
- Plan cancellation, failed expensive attempts, no-progress loops, scientific_null branches, restart and idempotent requests remain bounded and durable.
- Compare model-assisted plans with deterministic baselines on a declared fixture set; record actual failure/retry rates and costs before making performance claims. Live calls require a new explicit cap; the historical four-call M8 allocation is exhausted.
- Reports use existing field-bound evidence validation. Unsupported mutation ranking is rejected rather than generated from SASA, RMSD or OpenMM potential.

## Longer-term items requiring separate decisions

Mutation design/ΔΔG requires an actually supported and validated protocol with native units and licensed availability where relevant. Ligand force-field parameterization, full-complex OpenMM, conformational ensembles and free-energy methods are separate scientific projects; current protein-only potential cannot be extended by relabeling it. Conservation, remote lookup and downloaded model weights require explicit data provenance and egress rules. PAE/confidence views require validated supplied inputs and identity correspondence. Large trajectories need a durable blob/recovery redesign before replacing small-structure event payloads. Multi-user/cloud/sharing, plugins, AG-UI/A2A and GUI pipeline editing remain deferred.

## Completion audit boundary

The 2026-09-27 design audit compared mounted controls in `frontend/app/page.tsx`, `ViewerAgentPanel.tsx`, `MolstarViewer.tsx` and the labeled gallery with the M8 inventory. It inspected original scope/decision/contracts, selected native-picking, partial-ack, dry-run and report raw records, model usage/failure summaries, and the native-selection screenshot. The archived host baseline alone has no loaded canvas; loaded-scene records supply the actual ready Mol*/camera/selection evidence. This audit does not claim a new full renderer run or retest of provider behavior. Parent-owned current checks and reruns determine integration readiness; this roadmap does not supersede historical review hashes.
