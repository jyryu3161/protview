# M20 mutation-candidate fixtures (synthetic, T1)

Made locally for ProtView M20 (`generate_mutation_candidates`) on 2026-10-03. Nothing in this folder is an
experimental structure, a chemically valid protein, a modelled mutant or a measured value. Every residue is a short
straight line of atoms 1.5 Å apart, hand-placed so that its first atom (the "probe") sits at a chosen distance from one
feature (a metal ion, a ligand atom or a partner SG). Residues without a feature are parked ≥ 85 Å away from every
feature.

- `build_mutation_fixtures.py` (standard library only) writes the two structures and `expected.json`;
  `python3 backend/tests/fixtures/mutation/build_mutation_fixtures.py --check` exits 0 only if all three files on disk
  are byte-identical to a fresh build.
- `expected.json` is the independent oracle. The script parses the bytes it just wrote (mmCIF by whitespace, PDB by
  column; no gemmi, no `mw` code) and takes the minimum `math.dist` over every heavy-atom pair (element not H/D) by
  brute force. Preparation is simulated explicitly: H/D removed; one altloc per residue kept by highest mean occupancy
  (tie by letter) — the `first` rule is recorded separately (`derived.altloc_first_rule_changes`); waters kept. These are
  the `prepare_structure` config defaults. Spec constants (metal list, 20 standard names, 10 mapped names, 2.5 Å SG–SG)
  are copied from `.dryforge/spec.md`, not imported.
- Cross-check (T1): the product read path (`load_structure` → `prepare_structure` → `structural._parse` /
  `structure_residues`) gives the same residue identities (typed, 7 fields), categories, ligand candidates and metal
  residues, and the same distances (max |Δ| 2.8e-14 Å, only far pairs differ in the last bit; every boundary value is
  bit-exact). See `docs/qa/m20-mutations-20261003/preflight.txt`.

| File | SHA-256 | What it is |
|---|---|---|
| `synthetic-mutation-fixture.cif` | `fc4e6d899a498419d51beaa8172da0cc8117021cfe2097c668d6bac85aeb3a20` | One model, 365 atom records. Chains `A` (label A) and `B` (label B) with the identical 28-residue sequence (auth 1–27 with `10A` insertion code: all 20 standard names except HIS replaced by HID at 6 and CYX at 8, MSE as ATOM at 9, HIS at 27). Chain `CC` (multi-letter auth chain, label C): HIE HIP HSD HSE HSP ASH GLH LYN (1–8), MSE as **HETATM** (9, a non-polymer and therefore a ligand candidate), SEP as ATOM (10, non-standard), ALA 11 with `label_seq_id` `.` (null `seq_label` on a polymer residue). HETATM: `LIG A 101` (label D) and `LIG B 101` (label E) — two instances of the same name, each C1 C2 O3 + H4; `ZN A 201`, `NA A 202` (metals), `CD A 203` (not in the metal list, so a ligand candidate), `HOH A 301`. `LYS A 11` NZ has altloc A (occ 0.30, 2.5 Å from ZN) and B (occ 0.70, 3.5 Å). `PHE A 15` has one H atom (HX) 2.0 Å from LIG O3. |
| `synthetic-mutation-fixture-nolabel.pdb` | `c8c57b276aab9fa78fd3939b723676088effee0947252a4cab5d93f4d7154d6b` | The chain A and B records (and their HETATM residues) of the same atoms in PDB format: gemmi reads no label IDs, so every `chain_label` and `seq_label` is null. 308 atom records. |
| `expected.json` | `2fc9c97a8ea43e189914e6f67bbb9dbbf49f0b5017d0703d0611c632f101e0d9` | Oracle per file: residues in file order (7 fields, record type, category), ligand candidates, metal residues, per polymer residue the heavy-atom minimum distance to every ligand candidate, the nearest metal (residue + distance), the disulfide partner (SG–SG ≤ 2.5 Å, nearest, tie → first in file order), mapped standard name and one-letter code; SG–SG pairs ≤ 2.5 Å; `derived` lists (shell membership at 1/4/5/12 Å per LIG instance, metal contact at 1/2/3/5 Å, `first`-rule changes, disulfide residues, non-standard polymer residues); `placement_notes`. |
| `build_mutation_fixtures.py` | (see git) | The generator and oracle described above. |

## Boundary cases built in (prepared, highest_occupancy)

- Metal (3.0 Å default): ALA A2 2.9 (in), SER A3 exactly 3.0 (in, inclusive), THR A4 3.1 (out), LYS A11 3.5 (out; 2.5
  under the `first` altloc rule), GLU A12 4.0 to NA (out at 3.0, in at 5.0), GLY B1 2.2 to NA (other chain), ASN A13
  2.0 to CD (never a metal contact: CD is not in the list), GLN A14 2.5 to the water O (never).
- Disulfide (SG–SG ≤ 2.5 Å, four pairs): CYS A5–CYX A8 2.05 (intra-chain, variant name), CYS A20–CYS B20 exactly 2.5
  (inter-chain, inclusive), CYS A21–CYS B21 2.6 (out), CYS B22 with CYS A22 and CYS B23 both 2.4 (tie: B22's partner is
  A22, first in file order). CYX B8 has no partner (the name alone is not a disulfide).
- Ligand shell around LIG A101 (5.0 Å default): HID A6 exactly 5.0 (in, inclusive), VAL A7 5.001 (out), MSE A9 3.5
  (in, non-standard), LEU A10 4.0, ILE A10A 6.0 (out; insertion code), PHE A15 4.5 heavy (its H at 2.0 does not
  count), THR A16 5.5 heavy (LIG H4 at 4.4 does not count), SEP CC10 4.2 (in, non-standard), MSE CC9 3.0 (HETATM: not a
  polymer residue, never a position). LIG B101: LEU B10 3.0, ASN B13 4.9.
- Ligand candidates without a selector: four in the mmCIF (LIG A101, CD A203, LIG B101, MSE CC9), three in the PDB.

## Not claimed

The distances are geometric facts of hand-placed coordinates. They say nothing about binding, metal coordination,
disulfide chemistry or the effect of any mutation.
