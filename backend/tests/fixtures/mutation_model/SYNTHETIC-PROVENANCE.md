# M21 mutation-model fixtures (derived synthetic and synthetic, T1)

Made locally for ProtView M21 (`openmm_mutation_model`) on 2026-10-04. Nothing in this folder is an experimental
structure, a modelled mutant, a docking result or a measured value. Everything is written by
`build_mutation_model_fixtures.py` (standard library only) from the public 1UBQ mmCIF
(`backend/tests/fixtures/public_1ubq.cif`, SHA-256 `056f9871…0ca0f6`, checked by the script; public structure, not
experimental validation of anything here). `python3 backend/tests/fixtures/mutation_model/build_mutation_model_fixtures.py
--check` exits 0 only if every file below is byte-identical to a fresh build.

| File | SHA-256 | What it is |
|---|---|---|
| `derived_1ubq_f4c_t66c_disulfide_fixture.cif` | `08ae0063e5f3ba4d18edf5ca2058349cf626c993ba7be7ded97d0a04681ff5dd` | DERIVED SYNTHETIC. The 602 polymer `ATOM` rows of 1UBQ (waters dropped, other values verbatim, atom ids renumbered) with PHE A4 and THR A66 renamed CYS, side chains cut after CB and one hand-placed SG each: CB–SG 1.81 Å, CA–CB–SG 114°, chi1 chosen on a 2° grid so that SG–SG is closest to 2.04 Å (2.040 Å; ties by the larger clearance to every other heavy atom). Passes the M7 OpenMM preflight (596 heavy atoms); OpenMM `createDisulfideBonds` (3.0 Å) makes the A4–A66 disulfide (both CYX at pH 7). Not a real ubiquitin variant. |
| `derived_1ubq_f4c_single_cys_fixture.cif` | `f1c1d87f45670987593ac8bb5818f4daa54bcd3b4716387dc55c6b8013f498ea` | DERIVED SYNTHETIC. Same rows with only PHE A4 → CYS (THR A66 unchanged), SG with the same bond/angle and chi1 fixed at 66° (`SINGLE_CHI1`). Chosen in T1 because PDBFixer 1.12.0 then places the SG of a T66C mutation 1.997 Å from it (a new distance-based disulfide; see `docs/qa/m21-mutations-20261004/preflight.txt` (b)). Passes the M7 preflight (597 heavy atoms). |
| `synthetic-phenol-ligand.sdf` | `997c7d6f0a73142118df375bf5a09ec79b0083c1916db6f69ecfe3df9a0852a3` | SYNTHETIC hand-built phenol (V2000, 13 atoms with explicit H: regular hexagon C–C 1.39 Å, C–H 1.09 Å, C–O 1.36 Å, O–H 0.96 Å at 109°), centre 6.5 Å from the 1UBQ I44 CB along CA→CB, closest heavy-atom distance to 1UBQ 3.60 Å; tilted so not every z is equal. Title starts with `SYNTHETIC-FIXTURE`. Input for the M18 same-condition docking flow only (no public ligand-bearing structure passes the M7 preflight; 1HSG lacks OXT). |
| `expected.json` | `446111ad2310307263c6f190708235340a2d3852508c8df0f739681a2abbe3a5` | Hand-derived oracles written from closed-form values, before any implementation existed: (1) contact rows of a 12-atom synthetic graph (4 residues, mutated residue ordinal 2, 9 bonds, 2 H) at cutoffs 4.0 / 3.0 / 2.5 Å with pairs ≤ 3 bonds apart excluded (boundary 4.0 Å included; 5 / 2 / 0 rows; the 9 close-but-excluded pairs listed); (2) Lee–Richards SASA of an isolated carbon (4πR²) and of a carbon with an oxygen 4 Å away (2πR1(R1 + (d²+R1²−R2²)/2d)), using the float32 gemmi radii that `mw/tools/sasa.py` passes. |
| `build_mutation_model_fixtures.py` | (see git) | The generator described above. |

Cross-check (T1, separate code): numpy brute force + BFS reproduces every contact row bit-for-bit; FreeSASA `calcCoord`
gives 120.76282531910152 Å² (|Δ| 1.4e-13) and 101.98401095336611 Å² (relative 8.4e-5, tolerance 0.005). See the
preflight record (f).
