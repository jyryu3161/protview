# PROTOTYPE (M29 T1 (k) measurement only; never product code, never imported by mw).
"""Where do the gap-identity facts live? Prepared mmCIF vs original `structure_source`, and PDB-format inputs.

For 8VF6 (and 1M17) this makes a fresh run under ``<runs-root>`` with the unmodified product tools
(`load_structure` -> `prepare_structure`, waters strip_all and keep_all), then reports which mmCIF categories
survive in the stored `prepared_coordinates` bytes versus the original `structure_source` bytes. It then writes
the same model as PDB text with gemmi (headers via `make_pdb_headers` when available), loads that through the
product tools as format ``pdb`` and reports what the product parser (`tools.structural._parse`) gives for
`label_seq` / `chain_label`, and whether SEQRES / REMARK 465 survive preparation.

    PYTHONPATH=backend .venv/bin/python docs/qa/m29-repair-20261013/probe/info_location.py <runs-root>

``<runs-root>`` must be a new Git-ignored folder (e.g. ``runs/m29-t1-20261013/k``), not under /tmp.
Only category names, counts and booleans are printed (no absolute paths).
"""
from __future__ import annotations

import sys
from pathlib import Path

import gemmi

from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import new_run

REPO = Path(__file__).resolve().parents[4]
INPUTS = {"8VF6": REPO / "runs" / "stk33-8vf6-20261013" / "8VF6.cif",
          "1M17": REPO / "backend" / "tests" / "fixtures" / "public_1m17.cif"}
WANTED = ("_entity_poly_seq.", "_pdbx_unobs_or_zero_occ_residues.", "_pdbx_unobs_or_zero_occ_atoms.",
          "_pdbx_poly_seq_scheme.", "_struct_asym.", "_entity_poly.", "_entity.")


def categories(raw: bytes) -> dict[str, int]:
    block = gemmi.cif.read_string(raw.decode()).sole_block()
    out = {}
    for cat in WANTED:
        table = block.find_mmcif_category(cat)
        out[cat] = (len(table) if table is not None and table.width() else 0) if table is not None else -1
    return out


def prepare(run, name: str, raw: bytes, fmt: str, waters: str):
    source = run.call("load_structure", {"source": name, "model_index": 0}, source_bytes=raw, source_format=fmt)
    prepared = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                              "waters": waters, "hydrogens": "strip",
                                              "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    return source, prepared


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    root = Path(argv[0])
    if str(root.resolve()).startswith(("/tmp", "/private/tmp")):
        print("runs-root must not be under /tmp", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=False)
    run = new_run(root, dry_run=False, run_id="run_m29t1_info_location")
    store = run.store
    print("## mmCIF inputs: categories in structure_source vs prepared_coordinates (-1 = category absent)")
    for pdb, path in INPUTS.items():
        raw = path.read_bytes()
        for waters in ("strip_all", "keep_all"):
            source, prepared = prepare(run, f"{pdb}.cif", raw, "cif", waters)
            selection = store.load(source.handle)
            src_raw = store.load(selection["source"])
            prep = store.load(prepared.handle)
            prep_raw = store.load(prep["coordinates"])
            manifest = store.load(prep["manifest"])
            print(f"{pdb}\t{waters}\tsource_is_input_bytes={src_raw == raw}\tsource={categories(src_raw)}")
            print(f"{pdb}\t{waters}\tprepared_fmt={store.meta(prep['coordinates'])['fmt']}\t"
                  f"prepared={categories(prep_raw)}")
            print(f"{pdb}\t{waters}\tmanifest_source_handle_is_structure_source="
                  f"{store.meta(manifest['source_handle'])['kind'] == 'structure_source'}\t"
                  f"manifest_keys={sorted(manifest)}")
    print("## PDB-format input (8VF6 written as PDB text by gemmi)")
    st = gemmi.make_structure_from_block(gemmi.cif.read(str(INPUTS["8VF6"])).sole_block())
    st.setup_entities()
    pdb_text = st.make_pdb_string()
    lines = pdb_text.splitlines()
    print(f"gemmi_pdb_writer: SEQRES_lines={sum(l.startswith('SEQRES') for l in lines)} "
          f"REMARK_465_lines={sum(l.startswith('REMARK 465') for l in lines)}")
    source, prepared = prepare(run, "8VF6.pdb", pdb_text.encode(), "pdb", "strip_all")
    prep = store.load(prepared.handle)
    print(f"prepared_fmt={store.meta(prep['coordinates'])['fmt']}")
    prep_lines = store.load(prep["coordinates"]).decode().splitlines()
    print(f"prepared_pdb: SEQRES_lines={sum(l.startswith('SEQRES') for l in prep_lines)} "
          f"REMARK_465_lines={sum(l.startswith('REMARK 465') for l in prep_lines)}")
    model = _parse(ToolContext(store=store, call_id="t1k"), prepared.handle)[0]
    labels = [(r.label_seq, r.subchain) for ch in model for r in ch if r.het_flag == "A"]
    print(f"product _parse on prepared PDB: polymer residues={len(labels)} "
          f"label_seq_none={sum(1 for x, _ in labels if x is None)} chain_label_empty={sum(1 for _, s in labels if not s)}"
          f" distinct_subchains_all_residues={sorted({r.subchain for ch in model for r in ch})}")
    mini = (REPO / "backend" / "tests" / "fixtures" / "mini_complex.pdb").read_text()
    mini_model = gemmi.read_pdb_string(mini)[0]
    print(f"gemmi read of a PDB without SEQRES (backend/tests/fixtures/mini_complex.pdb): distinct_subchains="
          f"{sorted({r.subchain for ch in mini_model for r in ch})} label_seq_none="
          f"{all(r.label_seq is None for ch in mini_model for r in ch)}")
    src_model = _parse(ToolContext(store=store, call_id="t1k"), source.handle)[0]
    src_labels = [r.label_seq for ch in src_model for r in ch if r.het_flag == "A"]
    print(f"product _parse on PDB structure selection: label_seq_none={sum(1 for x in src_labels if x is None)}"
          f" of {len(src_labels)}")
    rows = []
    for ch in model:
        pol = [r for r in ch if r.het_flag == "A"]
        for a, b in zip(pol, pol[1:]):
            c = next((x for x in a if x.name == "C"), None)
            n = next((x for x in b if x.name == "N"), None)
            if c and n and not 1.1 <= c.pos.dist(n.pos) <= 1.7:
                rows.append(f"{ch.name}/{a.seqid.num}->{b.seqid.num} C-N {c.pos.dist(n.pos):.2f}A")
    print(f"PDB-format chain breaks seen only by C-N distance (M7 peptide_geometry): {rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
