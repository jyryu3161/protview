# M18 docking fixtures (synthetic and public-derived, T1)

Made locally for ProtView M18 (single-ligand docking with QuickVina 2.1) on 2026-10-02. Nothing in this folder is
an experimental structure, an observed binding pose, a measured affinity or a validated docking result.

- Public source: the ProLIF 2.2.2 example files already in `../chemical/` (`prolif-vina-rec.pdb`, SHA-256
  `745bd4726ba956e27da5cf4da10189f2bbe937db59ff08f302bca9d2cdbc62cc`; `prolif-vina-output.sdf`, SHA-256
  `810b8c714edd3140585664f980c8e6644ba9c76372029cb3abbfa4d13b5899e0`; licence `../chemical/PROLIF-LICENSE.txt`).
  These are a public *prepared docking example* (a receptor and Vina output poses), not experimental validation.
- `build_docking_fixtures.py` (standard library only) rebuilds every `public-derived-*` and `synthetic-*` PDB/SDF
  below from those two files; `python3 backend/tests/fixtures/docking/build_docking_fixtures.py --check` exits 0
  only if the files on disk are byte-identical to a fresh build.
- The contact oracle files, the building-block list and `expected.json` are hand-written.
- `m17-enumerate-result-record0-nmethyl.json` is the unmodified output of the real M17 worker on these fixtures.
- T1 measurements and the cross-check of the hand oracle are in `docs/qa/m18-docking-20261002/preflight.txt`.

| File | SHA-256 | What it is |
|---|---|---|
| `public-derived-parent-record0.sdf` | `34a5c499e612156ab2c3ae7abedc95922cc4990363bda5275e7da6acd64c5fd9` | Record 0 of `prolif-vina-output.sdf` verbatim except line 1 (title) = `PUBLIC-DERIVED-FIXTURE ...`. 79 atoms (heavy 1–43, H 44–79), explicit H, 3D, N21 formal charge +1. Used as the 3D ligand (`sdf` source), as the M17 parent, and as the reference pose for redocking. |
| `synthetic-ligand-planar-z0.sdf` | `ad531eae2446c0baebf1f8d0ddb648677c0b1d6c4053d2224d404f7f1c7b4573` | Record 0 with every z column set to `0.0000` (title `SYNTHETIC-FIXTURE planar ...`). Negative for `ligand_not_3d`. |
| `synthetic-ligand-implicit-h.sdf` | `eca0d17066a3f00075805b79a1864782a5e11b721d28a341bda2da78a7d2e387` | Record 0 with all 36 H atoms and their bonds removed (heavy serials 1–43 unchanged, `M  CHG` kept; title `SYNTHETIC-FIXTURE implicit H ...`). Negative for `ligand_hydrogens_missing`. |
| `synthetic-complex-receptor-lig.pdb` | `2b840a4542fcef060b44f4ef78c4d4eee9e4abf8941a19ef526ce7b8b402d43d` | Public receptor ATOM lines (serials 1–4988, unchanged) + record 0 as one `HETATM` instance `LIG`, chain `L`, residue 1 (serials 4989–5067, names element+running number, e.g. `C1`, `H36`) + the public receptor `CONECT` lines + `CONECT` lines for every record 0 bond + `END`. Seven residue fields as read by gemmi: model 1, chain_auth `L`, chain_label null, seq_auth 1, seq_label null, icode `""`, resname `LIG`. Removing that instance leaves the public receptor atoms in the same order. |
| `synthetic-complex-duplicate-instance.pdb` | `1f81f2b038eabdda5603731bad9a8901f5afafc5d6754deeb583d3b47ab1f034` | Same, with two instances carrying the same seven fields: copy 1 between receptor chains A and B, copy 2 (x + 40 Å) after chain B. gemmi reads chains A, L, B, L. Negative for `receptor_instance_ambiguous`. |
| `synthetic-complex-covalent-instance.pdb` | `3af8139fde582f526570b7f6150f38b3f3c5fbfe3ffcab41c5c3859dbab7fc49` | Same as the complex plus one `CONECT` bond between ligand serial 5010 (SDF atom 22, name `C14`) and receptor serial 1 (`CAY`, TYR A 38). Chemically impossible on purpose (CAY becomes five-coordinate). Negative for `receptor_instance_covalent`. |
| `synthetic-receptor-water-zinc.pdb` | `affa0293ea815366c62fd576ce20090213ad3050e4e63e3877f2e4ac1e2e8f31` | Public receptor + one `HOH` (chain W, residue 1: O, H1, H2 with `CONECT`) at (60, 60, 60) + one `ZN` ion (chain Z, residue 1, no bonds) at (−60, −60, −60). Negative for `receptor_unsupported_residue`. |
| `synthetic-receptor-altloc.pdb` | `93a90813800a2d8d5ee4f8ebc4bb5383a6df364f44cc3cd8d45c35576c62e9b7` | Public receptor with atom serial 11 (CB, TYR A 38) given altloc `A`; nothing else changed. Negative for `receptor_altloc_present`. |
| `synthetic-contact-oracle-receptor.pdb` | `ebf929c1f39ee808b6ba3e385e916ff8b4059436de01e7ae6af0831502b691f8` | Six hand-placed atoms (geometry only, not a valid receptor): CB ALA A 1 (0,0,3.5), HB1 ALA A 1 (0,0,2.5), N GLY A 2 (1.43,3,0), O GLY A 2 (−4,0,0), CA GLY A 2 (0,0,−4.01), SG CYS B 3 icode A (1.43,0,−3.9). |
| `synthetic-contact-oracle-pose.sdf` | `07aaf8eba1284b064e2e536975759ecc561f032e1670eedc7014d69a2fa40563` | Hand-written V2000 methanol pose: 1 C (0,0,0), 2 O (1.43,0,0), H 3–6. With the receptor above it gives exactly six heavy-atom contacts ≤ 4.0 Å; every distance is written out in `expected.json`. |
| `synthetic-docking-blocks.smi` | `966f7a8607d3011fc3570a39f64e05ab284281fe0602c1cb18f847352d6392ec` | Hand-written M17 building blocks: `*CC ethyl`, `*C(F)(F)F trifluoromethyl`, `*C1CC1 cyclopropyl`. |
| `m17-enumerate-result-record0-nmethyl.json` | `cfebdf81afb32fef2fb41af2a4e46268cc9261676f7b21882776fb651fbe3a60` | `result.json` of the unmodified M17 worker, `rdkit_enumerate_v1`, parent = `public-derived-parent-record0.sdf`, blocks = `synthetic-docking-blocks.smi`, `site_atoms` [22] (N-methyl carbon), `use_fixed` true, limits 2,000 / 20,000. Three candidates; the fixed one for docking tests is `c_1afb7cd3e603456c` (ethyl, `stereo_flag` none, `retained_parent_atoms` 1–21, 23–43). |
| `expected.json` | (see git) | Hand oracle (contact pairs, kinds, minimum distance, box arithmetic, numbering, expected reasons) and the T1 observations on the public example, labelled as observations. Every value has a `how`. |
| `build_docking_fixtures.py` | (see git) | The generator described above. |

## How the M17 candidate file was made

`.deps/prolif/venv-locked/bin/python -I backend/mw/jobs/ligand_worker.py` was run twice in a fresh attempt directory,
exactly as `backend/tests/test_ligand_worker.py::_call` does (`input.json` control record with `adapter`, `nonce`,
`job_id` `job_t1`, `attempt_id` `att_t1`, `input_sha256`; canonical `structure.json`; environment `PATH=/usr/bin:/bin`,
`LANG=C`, `PYTHONUTF8=1`, `TMPDIR`=attempt dir): first `rdkit_inspect_v1` (parent + the block list, no rules), then
`rdkit_enumerate_v1` with the payload above. Both exited 0. The enumerate `result.json` was copied here unchanged.

## Not claimed

Scores, poses, RMSD values and contact counts recorded for the public example are engine outputs used as test
observations. They say nothing about how the molecule binds. The geometric contacts are distance counts, not
hydrogen bonds or other interaction judgements.

## M19 batch fixture (T1, 2026-10-03)

- `m19-batch-input.json` (hand-written, see git for SHA-256): the batch input description for M19 tests built only from
  the files above (public receptor, `public-derived-parent-record0.sdf`, the real M17 candidate set
  `m17-enumerate-result-record0-nmethyl.json`; a fresh real M17 inspect + enumerate job on 2026-10-03 returned the same
  three candidate ids in the same order). No new structure, SDF or candidate file was made.
- `hand_oracle` values are arithmetic from the M19 spec (row order, budget need/shortfall, `full_batch_may_be_partial`,
  admission reasons, batch status rules, batch statement applicability), each with a `how`. They do not come from
  product code.
- `t1_observations` are real qvina2 / Meeko / RDKit outputs (scores, mode counts, content sizes, run-specific handle
  hashes) recorded as observations, not oracle values and not binding claims. The measurement (standalone M18 jobs vs one
  worker process with the receptor PDBQT prepared once) is in `docs/qa/m19-batch-20261003/preflight.txt`.
