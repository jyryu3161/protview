"""M11 QA input generator: synthetic derivatives are reproduced byte-for-byte from public fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mw.chemical_inputs import _bonds, import_raw, receptor_atoms
from mw.core.handles import ObjectStore
from mw.tools.comparison import atom_rows

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/m11_qa_inputs.py"
SETUP = ROOT / "scripts/m11_attach_browser_setup.py"
FIXTURES = ROOT / "backend/tests/fixtures/chemical"
EXPECTED = {
    "m11-attach-complex.pdb": "9c4426ae0c459e656040b11c10e51e36ff09b7a4adeb5c162d1b2dc32f96ee03",
    "m11-synthetic-empty-1000A.sdf": "a856c3c5495ad5d757575d780ebe0fc95f1111d1805f51545f5f3f026591a778",
    "m11-attach-receptor-edges.json": "76b01a9e3e02d27fe31a1aa3887a82c722dce6c7b2ab4c953b4c624dd758b03f",
}


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def test_generator_reproduces_pinned_synthetic_inputs(tmp_path: Path) -> None:
    done = subprocess.run([sys.executable, str(GENERATOR), "--out", str(tmp_path)],
                          capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    for name, digest in EXPECTED.items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
    edges = json.loads((tmp_path / "m11-attach-receptor-edges.json").read_text())["edges"]
    assert len(edges) == 5053


def test_generator_edges_equal_product_pdb_conect_path(tmp_path: Path) -> None:
    generator = _module(GENERATOR, "m11_qa_inputs_under_test")
    edges = json.loads(generator.build_inputs()["m11-attach-receptor-edges.json"])["edges"]
    raw = (FIXTURES / "prolif-vina-rec.pdb").read_bytes()
    store = ObjectStore(tmp_path / "run", "run_m11_qa_inputs")
    receptor = import_raw(store, "receptor", "rec.pdb", raw)
    rows = receptor_atoms(store, receptor["handle"], 1)
    product = _bonds(store, {"connectivity": {"kind": "pdb_conect", "sidecar_handle": None}},
                     rows, raw, receptor["handle"])
    assert edges == product


def test_generator_rejects_hash_mismatch() -> None:
    generator = _module(GENERATOR, "m11_qa_inputs_mismatch")
    with pytest.raises(SystemExit, match="SHA-256 mismatch"):
        generator.verify("m11-attach-complex.pdb", b"not the pinned bytes")


def test_attach_setup_maps_by_exact_catalog_identity(tmp_path: Path) -> None:
    generator = _module(GENERATOR, "m11_qa_inputs_setup")
    setup = _module(SETUP, "m11_attach_setup_under_test")
    inputs = generator.build_inputs()
    store = ObjectStore(tmp_path / "run", "run_m11_attach_setup")
    source = store.put("structure_source", "structure_source@1", inputs["m11-attach-complex.pdb"], fmt="pdb")
    complex_ = store.put("structure", "structure_selection@2",
                         {"source": source.handle, "format": "pdb", "model_index": 0})
    catalog = atom_rows(store, complex_.handle)["rows"]
    out = setup.build_run_inputs(catalog, complex_.handle, "obj://run_x/chemical_raw_input/lig", None,
                                 json.loads(inputs["m11-attach-receptor-edges.json"])["edges"],
                                 (FIXTURES / "prolif-vina-output.sdf").read_text())
    assert len(out["sidecar"]["bonds"]) == 5053
    assert out["sidecar"]["source_handle"] == complex_.handle
    assert out["ligand"] == catalog[4988]["ref"]["residue"]
    full, heavy = out["mapping_map_existing"]["mapping"], out["mapping_replace_from_sdf"]["mapping"]
    assert [m["source_atom"]["atom_name"] for m in full] == [f"X{i + 1}" for i in range(79)]
    assert len(heavy) == 43 and all(m["source_atom"]["element"] != "H" for m in heavy)
    assert out["request"]["mapping"] == full and out["request"]["connectivity"]["sidecar_handle"] is None
