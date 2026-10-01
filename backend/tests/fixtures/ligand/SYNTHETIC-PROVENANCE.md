# M17 ligand fixtures (synthetic, T1)

All files in this folder were made locally for ProtView M17 (ligand partial-replacement candidates). None is an
experimental structure, a binding pose, a measured property, or a vendor catalog entry. Expected values in
`expected.json` were derived by hand (atomic-weight sums, Ertl 2000 TPSA fragment sums, Lipinski N/O and NH/OH
counts, rotatable-bond SMARTS read by hand, PAINS SMARTS read by hand); RDKit 2026.03.6 was used only to
canonicalise the hand-written SMILES. The cross-check against RDKit is recorded in
`docs/qa/m17-ligand-20261001/preflight.txt`.

| File | SHA-256 | What it is |
|---|---|---|
| `synthetic-parent-methacetin-no-h.sdf` | `e862e2b95c9f7dccbdc7e23b8f55b8811d559b443dbac409cabaeac1e21091d7` | V2000, 12 heavy atoms, no H lines. Pinned RDKit 2026.03.6: `MolFromSmiles("CC(=O)Nc1ccc(cc1)OC")`, `Compute2DCoords(canonOrient=False)`, `MolToMolBlock`, title `SYNTHETIC-FIXTURE ...`, one `fixture_provenance` data field. Serials 1–12 follow the SMILES atom order (11 = methoxy O, 12 = methoxy C). |
| `synthetic-parent-methacetin-explicit-h.sdf` | `2e4f5b395f92a12b6a3a15a898e18d744345f5203da76c2489ebb0e7ef463d8e` | Same molecule, `AddHs` + `Compute2DCoords`, then `RenumberAtoms` so each heavy atom is followed by its own H atoms (23 atoms). Heavy serials 1,5,6,7,9,10,12,14,15,17,19,20; H serials 2,3,4,8,11,13,16,18,21,22,23. Tests SDF numbering with gaps. |
| `synthetic-blocks.sdf` | `0bfeb73474ede8b1f372b69072774fc9e2fd1398e8d0b24b31768e69fc9bda11` | 10 hand-written V2000 records (line 2 of each record says `SYNTHETIC-FIXTURE`): `*` marker, `R#` marker with `M  RGP`, empty title, 0-atom record, Se, two components, bond to a missing atom, repeated title, methyl, bromomethane. |
| `synthetic-blocks.smi` | `fc603c4b9d2e3cf48ab0521963369a270f73a78b354977af6c4d4d452d85c976` | Hand-written `SMILES name` list with a `#` header, a blank line and a `#` line; normal, one `*`, no `*`, two `*`, unreadable, B and Se, duplicate name, no name, two fragments, 65 and 64 carbon chains. |
| `synthetic-reaction-rules.json` | `cc27e69029c68d1481c1237cefaec5e6b6d8001dd6d0e08bcd0015ebca9bd66c` | 10 hand-written reaction SMARTS in request order (`user_1`…`user_10`): 3 valid, reactant count, product count, no mapped atom, parse error, duplicate text, 4097-byte and 4096-byte texts. |
| `pains-panel.smi` | `d2ce144e51e7f479b5d655cc5832a7b3016cef14efd9a1ab609c2b289ad11fef` | Hand-written SMILES of textbook structures (benzylidene rhodanine, p-benzoquinone, catechol, 4-aminophenol, 4-benzylaminophenol; negatives methacetin, paracetamol, benzene, aspirin). Structures only, no assay data. PAINS source: Baell & Holloway, J Med Chem 2010, 53, 2719 (doi:10.1021/jm901137j); SMARTS as shipped in RDKit `Data/Pains/wehi_pains.csv`. |
| `expected.json` | `5d6790aa0d2f9a4a91a1810fb766cd9c6e4e3fb63bdd3122a146ec0cea607606` | Hand oracle: parent atom tables and bonds in both numberings, block accept/reject per record, rule validity, fixed-replacement and rule products for site = methoxy, properties, PAINS. Every value has a `how` field. |

Methacetin, phenacetin and paracetamol are named only as structure identifiers. Nothing here claims any property of
those compounds beyond the hand-computed descriptor arithmetic.
