"""M11 H06 invalid-input QA derivatives: pinned bytes and exact product diagnostics.

The generator's manifest names each offending identity from the edit it made (an independent
oracle); the product preview must reject with that code and exactly those AtomRef identities.
All inputs are labeled synthetic invalid derivatives of the public ProLIF tutorial fixture.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mw.chemical_inputs import import_raw, preview
from mw.core.errors import ToolFailure
from mw.core.handles import ObjectStore
from mw.tools.comparison import atom_rows

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/m11_invalid_inputs.py"
QA_INPUTS = ROOT / "scripts/m11_qa_inputs.py"
SETUP = ROOT / "scripts/m11_attach_browser_setup.py"
FIXTURES = ROOT / "backend/tests/fixtures/chemical"
ACK = {"schema": "chemical_preparation_ack@1", "supplied_graph_complete": True,
       "supplied_hydrogens_complete": True, "use_supplied_protonation_tautomer": True,
       "infer_receptor_orders_charges": True, "description": "", "ph_annotation": None}
LIGAND = {"model_number": 1, "chain_auth": "L", "chain_label": None, "seq_auth": 1, "seq_label": None,
          "icode": "", "resname": "LIG"}


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def _identity(ref: dict) -> tuple:
    return (json.dumps(ref["residue"], sort_keys=True), ref["atom_name"], ref["altloc"], ref["element"].upper())


def _generate(tmp_path: Path, *extra: str) -> dict:
    done = subprocess.run([sys.executable, str(GENERATOR), "--out", str(tmp_path), *extra],
                          capture_output=True, text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads((tmp_path / "m11-invalid-cases.json").read_text())


def _assert_expected(store: ObjectStore, req: dict, expected: dict) -> None:
    if expected["kind"] in {"preview_error", "upload_error"}:
        with pytest.raises(ToolFailure, match=expected["text"]):
            preview(store, req)
        return
    result = preview(store, req)
    assert result["ready"] is False
    codes = {blocker["code"] for blocker in result["blockers"]}
    assert set(expected["codes"]) <= codes
    for code, atoms in expected["atoms"].items():
        shown = [ref for blocker in result["blockers"] if blocker["code"] == code for ref in blocker["atoms"]]
        assert sorted(map(_identity, shown)) == sorted(map(_identity, atoms)), code


def test_invalid_create_inputs_reject_with_exact_identities(tmp_path: Path) -> None:
    manifest = _generate(tmp_path / "out")
    for name, info in manifest["files"].items():
        assert hashlib.sha256((tmp_path / "out" / name).read_bytes()).hexdigest() == info["sha256"]
        assert info["pinned"] is True
    store = ObjectStore(tmp_path / "run", "run_m11_invalid")
    checked = set()

    def source(name: str) -> Path:
        return FIXTURES / name if (FIXTURES / name).exists() else tmp_path / "out" / name

    for case in manifest["cases"]:
        receptor = import_raw(store, "receptor", "rec.pdb", source(case["receptor"]).read_bytes())
        ligand = import_raw(store, "ligand_sdf", "lig.sdf", source(case["sdf"]).read_bytes())
        connectivity = {"kind": "pdb_conect", "sidecar_handle": None}
        if case["connectivity"] == "sidecar":
            if case["sidecar"] is None:
                assert case["expected"]["kind"] == "client_error"  # the UI refuses before any request
                checked.add(case["case"])
                continue
            raw = source(case["sidecar"]).read_bytes()
            if case["expected"]["kind"] == "upload_error":
                with pytest.raises(ToolFailure, match=case["expected"]["text"]):
                    import_raw(store, "receptor_bonds", "bonds.json", raw)
                checked.add(case["case"])
                continue
            connectivity = {"kind": "sidecar",
                            "sidecar_handle": import_raw(store, "receptor_bonds", "bonds.json", raw)["handle"]}
        ack = dict(ACK) if case.get("acknowledge", True) else {
            **ACK, **{key: False for key in ("supplied_graph_complete", "supplied_hydrogens_complete",
                                             "use_supplied_protonation_tautomer", "infer_receptor_orders_charges")}}
        req = {"schema": "chemical_prepare_request@1", "mode": "create_new",
               "receptor_input_handle": receptor["handle"], "receptor_model_number": 1,
               "connectivity": connectivity, "ligand_sdf_handle": ligand["handle"], "sdf_record_index": 0,
               "ligand_instance": case.get("ligand_instance", LIGAND), "terminal_extensions": [],
               "acknowledgement": ack}
        _assert_expected(store, req, case["expected"])
        checked.add(case["case"])
    assert checked == {case["case"] for case in manifest["cases"]}


def test_invalid_covalent_ligand_sidecar_reports_both_endpoints(tmp_path: Path) -> None:
    qa = _module(QA_INPUTS, "m11_qa_inputs_invalid")
    setup = _module(SETUP, "m11_attach_setup_invalid")
    inputs = qa.build_inputs()
    store = ObjectStore(tmp_path / "run", "run_m11_invalid_attach")
    raw_source = store.put("structure_source", "structure_source@1", inputs["m11-attach-complex.pdb"], fmt="pdb")
    complex_ = store.put("structure", "structure_selection@2",
                         {"source": raw_source.handle, "format": "pdb", "model_index": 0})
    sdf = (FIXTURES / "prolif-vina-output.sdf").read_bytes()
    ligand = import_raw(store, "ligand_sdf", "lig.sdf", sdf)
    built = setup.build_run_inputs(atom_rows(store, complex_.handle)["rows"], complex_.handle, ligand["handle"],
                                   None, json.loads(inputs["m11-attach-receptor-edges.json"])["edges"],
                                   sdf.decode())
    run_sidecar = tmp_path / "m11-attach-bonds-run.json"
    run_sidecar.write_text(json.dumps(built["sidecar"]))
    manifest = _generate(tmp_path / "out", "--attach-sidecar", str(run_sidecar))
    case = next(item for item in manifest["cases"] if item["case"] == "covalent_ligand")
    assert manifest["files"][case["sidecar"]]["pinned"] is False
    sidecar = import_raw(store, "receptor_bonds", "covalent.json", (tmp_path / "out" / case["sidecar"]).read_bytes())
    req = {**built["request"], "connectivity": {"kind": "sidecar", "sidecar_handle": sidecar["handle"]},
           "mapping": []}
    _assert_expected(store, req, case["expected"])
