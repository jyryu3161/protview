# Synthetic fpocket output parser fixtures

Label: **synthetic**. Every file under `synthetic-*/` was written by hand (a small generator script following the
fpocket 4.2.3 writer format strings in `src/fpout.c`, `src/writepdb.c` and `src/voronoi.c` of the pinned source
tag). None of it is fpocket engine output, none of it is experimental or derived from a real structure, and none
of the numbers are scientific observations. The PQR/PDB files carry a `HEADER SYNTHETIC PARSER FIXTURE` line;
`protein_info.txt` cannot carry a marker because its format has no comment lines.

- `synthetic-valid/`: a two-pocket output tree, the synthetic transport atom table it refers to
  (`transport_atoms.json`, same keys as `mw.pocket_input` transport rows), and the stdout/stderr bytes.
  Pocket 1 lists one lining atom twice to exercise the dedup policy. Pocket 2's opaque `Flexibility`
  field is `nan` to exercise opaque-string retention.
- `synthetic-empty/`: the supported empty-output shape (zero-byte `protein_info.txt`, header-only
  `protein_pockets.pqr`, no per-pocket files) with the no-pocket diagnostics. Git does not keep the empty
  `protein_out/pockets/` directory, so tests create it after copying.

Tests in `backend/tests/test_pocket_output.py` copy these trees into `tmp_path` and mutate them for each
malformed / missing / link / cap / empty-variant case. Symlinks, hardlinks, FIFOs and oversize files are made at
test time only.
