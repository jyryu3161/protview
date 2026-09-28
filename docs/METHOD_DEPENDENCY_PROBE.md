# M11–M12 isolated dependency and native execution probe

Probe owner: GPT-6 Sol, 2026-09-27. This is development feasibility evidence, not a ProtView capability declaration or M11/M12 acceptance. All installations, scripts, downloaded wheels, inputs derived for engines, native outputs, logs, and lock files are under `/tmp/protview-methods-probe-20260927`. No project environment, application module, run, service, credential, provider, phase index, or Git transition was changed for this probe. Only this note was added to the project. Existing unrelated worktree changes belong to concurrent work.

## Environment and resolved dependencies

Host: Darwin arm64/macOS 15.6, Python 3.11.11. The exact commands and complete stdout are retained in the probe directory. The Python setup was:

```sh
python3 -m venv /tmp/protview-methods-probe-20260927/venv
/tmp/protview-methods-probe-20260927/venv/bin/python -m pip install --log /tmp/protview-methods-probe-20260927/pip-install-success.log 'prolif==2.2.2' 'rdkit==2026.3.6' 'MDAnalysis==2.10.0' 'gemmi>=0.7.5,<0.8'
/tmp/protview-methods-probe-20260927/venv/bin/python -m pip check
```

The first full-resolution attempt supplied `gemmi==0.7.3` and failed with `ResolutionImpossible`: **ProLIF 2.2.2 depends on `gemmi>=0.7.5`**. That failure is real, but the original description incorrectly identified this probe constraint as the project parser pin. Parent inspection on 2026-09-27 found accepted commit `479d961` declares `gemmi>=0.6`, while the actual project environment contains gemmi **0.7.5** (distribution metadata modified 2026-09-24); M10 now explicitly pins that installed version. The failed attempt therefore does not demonstrate a conflict with the accepted server environment. The isolated retry resolved gemmi **0.7.5** without changing the project environment. Installed versions observed at import: ProLIF 2.2.2, RDKit 2026.03.6, MDAnalysis 2.10.0, gemmi 0.7.5; `pip check` reported “No broken requirements found.” The complete 33-wheel version/hash inventory is `pip-freeze.txt` plus `pip-wheel-hashes.json`, with wheels retained under `wheels/`; the full installer and download logs are `pip-install-success.log`, `pip-stdout-success.log`, and `pip-download.log`. The failed resolver log is `pip-stdout.log`. A separately pinned scientific worker remains the selected isolation/deployment boundary; parser regression checks still apply to any actual parser change.

The native detector setup was:

```sh
conda create --yes --prefix /tmp/protview-methods-probe-20260927/fpocket-conda --override-channels --channel conda-forge --channel bioconda 'fpocket=4.2.3'
conda list --prefix /tmp/protview-methods-probe-20260927/fpocket-conda --explicit
```

The solver selected conda-forge `osx-arm64/fpocket-4.2.3-hb88c64c_2.conda` (archive SHA-256 `b40c27414ee32f543f4ed67bbf06f74063796c7d3a5759e8da4c5eac37271c5a`). The installed `bin/fpocket` SHA-256 is `a79058e4d727a798212e8deb3a47587b7c9915451b5f70c7b56bd62e15252894`. The package record says **4.2.3**, whereas the binary `-h`/`-v` help banner prints **“fpocket 4.0”**; both observations must be carried in provenance until the release/build source is reconciled. `otool -L` on this executable lists `/usr/lib/libSystem.B.dylib` and `/usr/lib/libc++.1.dylib`; the installed conda environment nevertheless contains 35 resolved packages. Their exact URLs, versions, builds, archive hashes and sizes are in `fpocket-conda-explicit.txt` and `fpocket-conda-lock-hashes.json`; solver output is `conda-install.log`.

Primary release/API references: [ProLIF 2.2.2 package](https://pypi.org/project/prolif/2.2.2/), [ProLIF direct fingerprint API](https://prolif.readthedocs.io/en/stable/source/modules/interaction-fingerprint.html), [MDAnalysis 2.10 RDKit converter](https://docs.mdanalysis.org/2.10.0/documentation_pages/converters/RDKit.html), [fpocket 4.2.3 source](https://github.com/Discngine/fpocket/tree/4.2.3), [conda-forge package record](https://api.anaconda.org/package/conda-forge/fpocket). License references to review before distribution: [ProLIF Apache-2.0](https://github.com/chemosim-lab/ProLIF/blob/v2.2.2/LICENSE), [fpocket MIT and bundled notices](https://github.com/Discngine/fpocket/tree/4.2.3), plus the installed RDKit and MDAnalysis package notices. No redistribution conclusion is made here.

## ProLIF native molecule-pair execution

`prolif_analytic.py` creates **synthetic analytic graph fixtures**, each with explicit O–H bonds, fixed conformer coordinates, atom residue metadata, and no measured experimental claim. Direct `Fingerprint(interactions=['HBDonor'], count=True).generate(lig, prot, metadata=True)` returned:

| Fixture | Independently calculated D···A | D–H···A angle | Native HBDonor assignments |
| --- | ---: | ---: | ---: |
| Straight | 2.800 Å | 180.000° | 1, parent ligand indices `[0,1]`, protein `[0]` |
| Bent | 2.795 Å | 79.695° | 0 |
| Distant | 4.000 Å | 180.000° | 0 |

The bent fixture deliberately changes coordinates while keeping a similar D···A distance; the native angle filter rejects it. The distant fixture tests the native 3.5 Å D···A cutoff. The first draft of the bent water fixture had a second H pointing toward the acceptor and correctly produced a different positive assignment; this revealed why assignment *roles and hydrogen indices* must be checked, not just one nominated angle. The corrected fixture moves that second H away. These are real ProLIF computations on constructed graphs, not scientific observations. Exact output is `prolif-analytic.log`.

The independent public demonstration used **unchanged packaged ProLIF 2.2.2 docking tutorial data**: `prolif/data/vina/rec.pdb` (504,575 bytes, SHA-256 `745bd4726ba956e27da5cf4da10189f2bbe937db59ff08f302bca9d2cdbc62cc`) and the first record of `vina_output.sdf` (full file 60,682 bytes, SHA-256 `810b8c714edd3140585664f980c8e6644ba9c76372029cb3abbfa4d13b5899e0`). Source and method: [official ProLIF PDB tutorial](https://prolif.readthedocs.io/en/stable/notebooks/pdb.html) and [pinned package tree](https://github.com/chemosim-lab/ProLIF/tree/v2.2.2/prolif/data/vina). `MDAnalysis.Universe(rec.pdb)` reported 4,988 receptor atoms and 5,053 bonds; `Molecule.from_mda` inferred the receptor RDKit chemistry from the prepared, explicit-H file. The supplied SDF yielded a 79-atom ligand. Receptor graph inference is a named limitation; these bytes are a prepared docking example, not experimental validation of assignments.

The direct native call found 32 `Hydrophobic`, 1 `HBDonor`, 1 `HBAcceptor`, and 2 `Cationic` occurrences across six residue pairs. In the donor example, ligand parent atom indices `[20,58]` (N–H single bond) meet receptor ASP A:129 atom index `[1489]`: native D···A **3.021745413745174 Å**, angle **137.17258546337172°**. An independent calculation from conformer coordinates reproduced both within floating precision. In the acceptor example, ligand atom `[11]` (double-bonded O) meets receptor VAL A:201 donor/H `[2626,2627]`: D···A **2.8973910288310383 Å**, angle **150.02509493763267°**, also independently reproduced. `prolif-public-check.log` records parent indices, both graphs, and calculations. A clearly labeled **synthetic derivative** translated only the ligand pose by +1,000 Å while retaining its graph; the same native call returned `{}` (zero residue pairs). `prolif-example.log` contains the native category counts and per-assignment metadata. None of these values is an affinity, stability result, or experimentally validated hydrogen bond.

## fpocket native protein-only execution

`fpocket_project.py` reads the existing `backend/tests/fixtures/public_1hsg.cif` (SHA-256 `d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268`), selects model 0 and only 20 standard protein residue names/heavy atoms, excludes 128 other residues (including ligand/solvent), and writes a **temporary transport PDB**, never a replacement source. The projection includes 198 residues/1,514 heavy atoms, no input hydrogens, and a complete source-to-synthetic atom map in `fpocket-run/projection.json`. Its three-decimal PDB coordinates and SHA-256 `8c5cf88101960dd063569dbceb5ee9ed37f588d3f5017c7e86233c3cfd203918` are the actual engine input. Source author/label identity and general alternate-location handling still require production validation; this is a bounded fixture probe.

In private `/tmp/protview-methods-probe-20260927/fpocket-run` with a private `TMPDIR`, the actual fixed argv was:

```sh
/tmp/protview-methods-probe-20260927/fpocket-conda/bin/fpocket -f protein.pdb -m 3.4 -M 6.2 -D 2.4 -C s -e e -i 15 -p 0.0 -A 3 -v 300 -w p
```

The binary exited 0 and created `protein_out/protein_info.txt` plus pocket atom and vertex files for **8 pockets**. The native info SHA-256 is `b7fb7a96a80a55d8fa993fa31b684c2e40be6f46e4e1c9a75c944ca111402a60`. In that observed run, pocket 1 reported score **0.094**, 157 alpha spheres, total SASA **358.866** (native area field), and volume **1590.776** (native volume field). Its vertex PQR has exactly 157 sphere records and first sphere center `(18.716, 18.473, 11.303)` Å with radius `4.10` Å. Its lining-atom PDB has 83 atoms. `fpocket_verify.py` checked every pocket's reported sphere count against vertex records and mapped every lining atom's name, synthetic residue and coordinate to the exact transport input, with maximum discrepancy **0.000 Å** at the PDB's stored precision. `fpocket-verify.log` and `fpocket-output-hashes.json` retain all pocket counts, individual output hashes, and checks. The detector is wall-clock seeded in this release; these are observed values from this run, not deterministic expected values or validated biological pocket labels.

For a small, nondegenerate **derived fixture**, the first ten standard residues/88 atoms from that same transport input were passed through identical fixed flags in a separate private directory. The binary exited **0** and stdout said `! No Pockets Found while refining` followed by two `! No pocket to reindex.` lines. It created `protein_out/` with a **zero-byte `protein_info.txt`** (SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`), a 178-byte `protein_pockets.pqr` header, and no pocket atom/vertex files. Input SHA-256: `5f35f746ad09d2fc69a176f8b5b3c8c8f82bc5ee192c6325cd2840c62a4050b6`. The exact stdout is `fpocket-small-native.log`. This combination is evidence for a real native empty result; a missing output directory, nonzero exit, or malformed/missing expected files after a crash has **not** been shown to be scientific_null and must be treated separately by the future adapter.

## Remaining contract work

This probe did not implement import mapping, durable objects, bounded worker supervision, capability/UI/report wiring, cancellation, restart, resource limits, deterministic caching, or offscreen controls. The ProLIF prepared-receptor inference route needs graph-level validation for diverse residues and exact recording of connectivity guessing; the strict supplied-graph lane needs a product sidecar format and adversarial identity tests. The fpocket package/banner mismatch needs source/build reconciliation; native output parsing needs hostile-file checks and explicit units for each accepted descriptor. The source-to-transport identity map, quantization policy, small-result classification, seed-control limitation, dependency packaging/licenses, and old gemmi parser regression remain review items. No unsupported mode is waived, and neither method should appear as supported in product capabilities based on this probe alone.
