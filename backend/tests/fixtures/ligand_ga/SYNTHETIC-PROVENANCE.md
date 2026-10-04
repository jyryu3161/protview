# M22 GA design fixtures (synthetic, T1)

Made locally for ProtView M22 (ligand GA design engine) on 2026-10-04. Nothing in this folder is a real compound
library, a measured value, an observed binding pose, an affinity or a validated docking result. Scores recorded here
are either real qvina2 outputs kept as *observations* (labelled so) or *synthetic selection-logic inputs* (labelled
SYNTHETIC); neither says anything about binding.

Inputs reused from other fixture folders (not copied): the public prepared docking example receptor
`../chemical/prolif-vina-rec.pdb` (ProLIF 2.2.2 example, not experimental validation) and the public-derived parent
`../docking/public-derived-parent-record0.sdf` (see `../docking/SYNTHETIC-PROVENANCE.md`). Site atom 22 is the
parent's N-methyl carbon (the M18/M19 fixture site).

| File | What it is |
|---|---|
| `build_ligand_ga_fixtures.py` | Standard-library generator of the three block/rule files below. `python3 backend/tests/fixtures/ligand_ga/build_ligand_ga_fixtures.py --check` exits 0 only if the files on disk are byte-identical to a fresh build. |
| `synthetic-ga-small-blocks.smi` | Ten hand-written fixed-replacement blocks (`*` attachment): ethyl, propyl, isopropyl, butyl, cyclopropyl, cyclobutyl, hydroxymethyl, fluoromethyl, trifluoromethyl, hydroxyethyl. |
| `synthetic-ga-pool2000-blocks.smi` | 1,000 generated mono-bromides `BrC<chain>`, `<chain>` = strings on `C`, `N`, `O` of length 1–6 in (length, lexicographic) order, first 1,000. Synthetic chemistry for size and timing only (some chains such as `O–O` or `N–O` are chemically odd on purpose of simplicity; they are valid RDKit molecules). |
| `synthetic-ga-pool2000-rules.json` | Three user reaction SMARTS (`user_1`–`user_3`) that join the bromide carbon to the site methyl carbon directly, through `O`, and through `C(=O)`. With the blocks above a real M17 enumeration stops at the 2,000-candidate cap (`candidate_limit`, 4,001 raw products, 2,001 `outside_site` at the parent's other methyl). |
| `m17-candidate-set-small-pool.json` | Canonical content of the real `ligand_candidate_set@1` object made by unmodified M17 jobs (`rdkit_inspect_v1` → `rdkit_enumerate_v1`, parent above, `synthetic-ga-small-blocks.smi`, `site_atoms` [22], `use_fixed` true) through `JobQueue` on 2026-10-04. Its `parent_handle`, `inspection_handle` and `block_handles` name that T1 measurement
run (`m22_t1`), so tests rebuild the set with real jobs in their own run and use this file for the candidate ids,
SMILES, properties and order. Ten candidates; three ids equal the M18/M19 fixture ids (ethyl `c_1afb7cd3e603456c`, cyclopropyl `c_21d6c6f0d07e3759`, trifluoromethyl `c_2c7a25e0cc0ad3f2`). |
| `independent_ga_oracle.py` | Plain-Python reading of the spec 3 GA procedure (standard library only, no `mw` import), written in T1 before any product GA code. Similarity = Tanimoto of the stored Morgan on-bit sets as an exact `Fraction`. The readings the spec leaves open are its `ASSUMPTIONS` A1–A7 (to be confirmed in T2/T3). `python3 backend/tests/fixtures/ligand_ga/independent_ga_oracle.py --check` recomputes every vector and table in `expected.json` and exits 0 only if all are equal. |
| `expected.json` | `pools.small`: the ten candidates with RDKit 2026.03.6 Morgan (radius 2, 2,048 bits, `rdFingerprintGenerator.GetMorganGenerator` defaults) on-bit lists, the RDKit Tanimoto doubles and the ROUND_HALF_UP 6-decimal values of the exact Tanimoto (equal in the docking env and the separate ProLIF/RDKit env). `ga_vectors`: oracle runs (inputs + expected path, every `rng.sample`/`rng.choice` call with its population and result). `arithmetic`: random-slot counts `floor(r × slots + 0.5)`, the float-vs-exact-decimal comparison, and reservation / wall-clock / may-be-partial rows. `t1_observations.small_pool_docking`: real qvina2 first-mode scores for the ten candidates (fast values: manual 12 Å box, exhaustiveness 1, num_modes 2, seed 1), identical result bytes in two processes. Every block has a `how`. |

## How the observations were made

See `docs/qa/m22-ga-20261004/preflight.txt`: fingerprints in `.deps/docking/venv-locked` (after loading
`docking_worker.py` by file path, as the GA worker will) and again in `.deps/prolif/venv-locked`; docking with the
unmodified `docking_worker.py` functions (`receptor_inputs`, `receptor_prepared` once, `dock_row` per candidate) on
payloads staged by the unmodified server `docking_bundle.submission` / `stage`.

## Not claimed

The scores are Vina-family scoring function values (kcal/mol), not affinities. Lower scores being "kept" by the GA is a
search rule only. Tanimoto values are fingerprint arithmetic, not activity or similarity of effect.
