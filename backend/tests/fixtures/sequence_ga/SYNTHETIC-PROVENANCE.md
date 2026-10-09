# M23 sequence GA fixtures (T1)

Made locally for ProtView M23 (sequence GA design engine) on 2026-10-05 in task T1 (preflight measurements). Nothing
in this folder is a measured binding value, an affinity, a stability, a ΔΔG or a validated result. The structure input
is the public 1UBQ fixture `../public_1ubq.cif` (public structure, not experimental validation of anything here); the
ligand is the labeled synthetic phenol `../mutation_model/synthetic-phenol-ligand.sdf` (hand-built, see
`../mutation_model/SYNTHETIC-PROVENANCE.md`); the imported-receptor and M19 inputs are the public prepared docking
example `../chemical/prolif-vina-rec.pdb`, the public-derived parent `../docking/public-derived-parent-record0.sdf` and
the labeled synthetic blocks `../docking/synthetic-docking-blocks.smi` (see those folders' provenance files).

| File | What it is |
|---|---|
| `build_sequence_ga_fixtures.py` | Builds the two real M20 candidate sets below through the unmodified product HTTP path (upload, `load_structure`, `prepare_structure`, the cheap `generate_mutation_candidates` tool; no engine, no job) in a run with the fixed id `run_m23_golden_keys`. `.venv/bin/python backend/tests/fixtures/sequence_ga/build_sequence_ga_fixtures.py <runs-root> --check` exits 0 only when a fresh build is byte-identical to the files on disk. |
| `m20-candidate-set-1ubq-8pos.json` | `{handle, content}` of the real `mutation_candidate_set@1` for user-selected 1UBQ chain A positions M1, Q2, I3, K6, L8, I44, G75, G76 with allowed residues `AFHWY` (8 positions x 5 = 40 candidates). Same handle as the golden run's set. The positions and allowed residues are test choices, not a design proposal. |
| `m20-candidate-set-1ubq-tiny.json` | `{handle, content}` of the real set for I3 (user-protected, so `excluded` with no candidate), K6, I44, G76 (C terminus) with allowed `AW` (3 candidate positions x 2 = 6 candidates; 26 individuals at `max_mutations` 3). For small real-engine GA tests. |
| `golden_call_keys.json` | Call keys and SHA-256 of stored object bytes recorded BEFORE any M23 server change (spec 8, 12): a standalone M18 docking on an imported receptor, the M21 I44W model job, a standalone M18 docking on the M21 mutant side (`receptor_source`), and a one-row M19 batch, plus the SHA-256 of the files whose change ends existing result reuse. Each entry keeps the submitted `request` (resubmittable) and the job's normalized `parameters`. These are identifiers and byte hashes, not science values; they are valid for the pinned environments of this machine (the pins are inside the keys). |
| `prototype_golden_call_keys.py` | PROTOTYPE that wrote `golden_call_keys.json` (fixed run id, unmodified product paths, real engines). Four rebuilds in separate roots gave byte-identical output (T1 (d)). |
| `prototype_sequence_model.py` | PROTOTYPE (never product code): multi-site mutant modeling by applying the unmodified M21 `mutant_projection` in structure order with the spec 4 rounding of PDBFixer-added atoms between steps, then the M21 `_prepare` / `_minimize` path; entry without SASA and contacts; the mmCIF handle computed before storage; `child` mode for the two-interpreter measurement. |
| `prototype_child_launch.py` | PROTOTYPE: a guardian-like group leader (`standin`, project `.venv`) that launches a docking-env `worker` the way `guardian.py` does; the worker runs the modeling child with the project interpreter and docks each model with the unmodified `docking_worker.py` (`receptor_inputs`, `receptor_prepared`, `dock_row`). Cleanup uses the real `guardian.cleanup` / `guardian.members`. |
| `prototype_receptor_extension.py` | PROTOTYPE of the spec 8 (b) server branch as a measurement-process monkeypatch: `mutation_set_model@1` handles go to a prototype reader, every other handle to the original `docking_bundle._mutation_receptor`. `docking_bundle.py` itself is unchanged. |
| `independent_sequence_ga_oracle.py` | Plain-Python reading of the spec 3 GA procedure (standard library only, no `mw` import), written in T1 before any product GA code. The readings the spec leaves open are its `ASSUMPTIONS` A1-A11 (to be confirmed in T2-T4). `python3 backend/tests/fixtures/sequence_ga/independent_sequence_ga_oracle.py --check` recomputes every vector and table in `expected.json` and exits 0 only if all are equal. |
| `expected.json` | `spaces`: four small spaces (three synthetic, one the real tiny 1UBQ set) with their N and canonical key order. `arithmetic`: the N / elementary-symmetric table (including the 400-position upper bound), the 75-row slot-count table `floor(x + 0.5)` and the reservation / wall-clock / may-be-partial rows. `vectors`: 16 oracle runs with their inputs and expected path, every rng call with its population and result. Score tables are INPUTS; `s4_tiny_observed` and `s4_tiny_observed_reuse` hold the real qvina first-mode values observed in T1 (g) (every key of the tiny set modeled and docked once), all others are labeled synthetic selection-logic inputs. |

## Changes after T1

- T4 (2026-10-05): the oracle labels generation 1 individuals `initial` instead of `random`, because spec 3 step 2
  names their origin `initial` (the spec wins). `expected.json` was regenerated by the changed oracle: the 65
  generation 1 entries changed `"origin": "random"` to `"origin": "initial"` and nothing else (same keys, rng calls,
  states, scores and stops); `--check` exits 0.
- M26 T1 (2026-10-08): `prototype_golden_call_keys.py` no longer calls the M20 tool (which builds v2 sets since M26); it puts the STORED v1 set `../reaction/t1/m20-v1-candidate-set-run_m23_golden_keys-8pos.json` (byte-equal to `m20-candidate-set-1ubq-8pos.json`, see `../reaction/t1/SYNTHETIC-PROVENANCE-t1.md`) with `store.put`; a recording before and after this change equalled `golden_call_keys.json` (`docs/qa/m26-reaction-20261008/v1-baseline/checks/`).

## How the observations were made

See `docs/qa/m23-sequence-ga-20261005/preflight.txt`. Engines: OpenMM 8.6.0 + PDBFixer 1.12.0 in the project `.venv`;
Meeko 0.8.0 / RDKit 2026.03.6 / MDAnalysis 2.10.0 / gemmi 0.7.5 in `.deps/docking/venv-locked`; `qvina2 --cpu 1`.

## Not claimed

qvina scores are Vina-family scoring function values (kcal/mol), not affinities, and scores of different receptors
(different individuals) are not a same-receptor comparison. OpenMM potentials are per-structure Amber14-all + GBn2
values and are never compared between sequences.
