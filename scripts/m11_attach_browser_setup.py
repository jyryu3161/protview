#!/usr/bin/env python3
"""Generate exact run-bound M11 attach inputs from a loaded complex's actual source catalog.

Moved into the repository from the 2026-09-27 M11 QA scratch directory (m11-attach-browser-setup.py);
the scratch-directory ROOT was removed. Public inputs are read from
backend/tests/fixtures/chemical/, the receptor edge list is rebuilt and hash-checked by
scripts/m11_qa_inputs.py, and outputs go to --out.

Run only against a parent-owned loopback QA service. This script does no writes to that
service: it GETs the source catalog and writes local JSON for the harness or manual API use.
The complex loaded into the run must be the generator's m11-attach-complex.pdb (SHA-256
9c4426ae0c459e656040b11c10e51e36ff09b7a4adeb5c162d1b2dc32f96ee03). First run without
--sidecar-handle, import the generated sidecar as
chemical/imports?kind=receptor_bonds&filename=m11-attach-bonds.json, then rerun with the
returned handle. Preview the generated request and explicitly declare only the terminal
extensions from the returned inventory before submitting a job. Every mapping comes from the
catalog's own AtomRefs by exact site order and atom name; no nearest-coordinate or guessed
mapping is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
from urllib.request import urlopen

from m11_qa_inputs import LIGAND_SDF, build_inputs, verify

LABEL = ("Synthetic prepared attach QA fixture assembled from public receptor and selected SDF record; "
         "no experimental claim")
RECEPTOR_ATOMS = 4988
LIGAND_ATOMS = 79


def fetch_catalog(api_base: str, run_id: str, complex_handle: str) -> list[dict]:
    if urlparse(api_base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Only a loopback QA service is permitted")
    catalog: list[dict] = []
    offset = 0
    while True:
        query = urlencode({"handle": complex_handle, "offset": offset, "limit": 500})
        url = f"{api_base}/runs/{quote(run_id)}/structures/atoms?{query}"
        with urlopen(url, timeout=20) as response:
            page = json.load(response)
        assert page["structure_handle"] == complex_handle and page["offset"] == offset
        catalog.extend(page["rows"])
        offset += len(page["rows"])
        if offset == page["total"]:
            return catalog
        assert page["rows"] and offset < page["total"]


def build_run_inputs(catalog: list[dict], complex_handle: str, ligand_import_handle: str,
                     sidecar_handle: str | None, edges: list[list[int]], sdf_text: str) -> dict:
    assert len(edges) == 5053
    assert len(catalog) == RECEPTOR_ATOMS + LIGAND_ATOMS
    assert all(row["ref"]["site_index"] == i for i, row in enumerate(catalog))
    ligand_rows = catalog[RECEPTOR_ATOMS:]
    assert all(row["ref"]["residue"]["resname"] == "LIG" and row["ref"]["atom_name"] == f"X{i + 1}"
               for i, row in enumerate(ligand_rows))
    sdf_lines = sdf_text.splitlines()
    assert int(sdf_lines[3][:3]) == LIGAND_ATOMS
    elements = [sdf_lines[4 + i][31:34].strip().upper() for i in range(LIGAND_ATOMS)]
    assert all(row["ref"]["element"].upper() == elements[i] for i, row in enumerate(ligand_rows))
    ligand = ligand_rows[0]["ref"]["residue"]
    sidecar = {"schema": "receptor_bonds@1", "source_handle": complex_handle, "complete": True,
               "bonds": [{"first": catalog[a]["ref"], "second": catalog[b]["ref"]} for a, b in edges]}
    full = [{"sdf_atom_index": i, "source_atom": row["ref"]} for i, row in enumerate(ligand_rows)]
    heavy = [item for item in full if elements[item["sdf_atom_index"]] != "H"]

    def mapping_file(policy: str, mapping: list[dict]) -> dict:
        return {"label": LABEL, "complex_handle": complex_handle, "selected_ligand": ligand,
                "hydrogen_policy": policy, "sdf_record_index": 0, "mapping": mapping}

    request = {"schema": "chemical_prepare_request@1", "mode": "attach_existing",
               "complex_handle": complex_handle, "complex_model_number": 1,
               "selected_ligand": ligand,
               "connectivity": {"kind": "sidecar", "sidecar_handle": sidecar_handle},
               "ligand_sdf_handle": ligand_import_handle, "sdf_record_index": 0,
               "hydrogen_policy": "map_existing",
               "mapping": full,
               "terminal_extensions": [],
               "acknowledgement": {"schema": "chemical_preparation_ack@1",
                                   "supplied_graph_complete": True,
                                   "supplied_hydrogens_complete": True,
                                   "use_supplied_protonation_tautomer": True,
                                   "infer_receptor_orders_charges": True,
                                   "description": "labeled public ProLIF tutorial fixture",
                                   "ph_annotation": None}}
    return {"sidecar": sidecar, "request": request, "ligand": ligand,
            "mapping_map_existing": mapping_file("map_existing", full),
            "mapping_replace_from_sdf": mapping_file("replace_from_sdf", heavy)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--complex-handle", required=True)
    parser.add_argument("--ligand-import-handle", required=True)
    parser.add_argument("--sidecar-handle")
    parser.add_argument("--out", required=True, help="output directory (git-ignored, not /tmp)")
    args = parser.parse_args()
    edges = json.loads(build_inputs()["m11-attach-receptor-edges.json"])["edges"]
    sdf_text = verify("prolif-vina-output.sdf", LIGAND_SDF.read_bytes()).decode()
    catalog = fetch_catalog(args.api_base, args.run_id, args.complex_handle)
    built = build_run_inputs(catalog, args.complex_handle, args.ligand_import_handle,
                             args.sidecar_handle, edges, sdf_text)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = {"m11-attach-bonds-run.json": json.dumps(built["sidecar"], separators=(",", ":")) + "\n",
             "m11-attach-request-run.json": json.dumps(built["request"], indent=2) + "\n",
             "m11-attach-mapping-run.json": json.dumps(built["mapping_map_existing"], indent=2) + "\n",
             "m11-attach-mapping-replace-run.json": json.dumps(built["mapping_replace_from_sdf"], indent=2) + "\n",
             "m11-attach-ligand-instance-run.json": json.dumps(built["ligand"], indent=2) + "\n"}
    for name, text in files.items():
        (out / name).write_text(text)
    print(json.dumps({"out": str(out), "ligand_sdf": str(LIGAND_SDF),
                      "files": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()},
                      "mapping_count": len(built["request"]["mapping"]),
                      "replacement_heavy_mapping_count": len(built["mapping_replace_from_sdf"]["mapping"]),
                      "sidecar_handle_set": bool(args.sidecar_handle)}, indent=2))


if __name__ == "__main__":
    main()
