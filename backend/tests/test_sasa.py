"""Real FreeSASA Lee–Richards engine, identity, replay and report evidence checks."""
from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path

import freesasa
import pytest
from fastapi.testclient import TestClient

from mw import method_reports
from mw.core.errors import FailureClass, ToolFailure
from mw.method_reports import (
    ROW_FIELDS,
    SUMMARY_FIELDS,
    _claim,
    _render,
    build_method_report,
    saved_method_report,
    validate_method_claim,
)
from mw.reports import EvidenceError
from mw.tools import sasa
from mw.tools.structural import structure_residues
from mw.workspace import new_run

FIX = Path(__file__).parent / "fixtures" / "mini_complex.pdb"


def _sphere(x: float, y: float, z: float) -> dict:
    return {"residue": {"model_number": 1, "chain_auth": "A", "seq_auth": int(x + y + z),
                        "icode": "", "chain_label": "A", "seq_label": int(x + y + z), "resname": "ALA"},
            "atom_name": "CA", "altloc": "", "coordinates_A": [x, y, z], "radius_A": 1.7}


def _params():
    return freesasa.Parameters({"algorithm": freesasa.LeeRichards, "probe-radius": 1.4,
                                "n-slices": 100, "n-threads": 1})


def _area(atoms: list[dict]) -> float:
    origin = (sasa._preflight(atoms[:-1], atoms[-1:]) if len(atoms) > 1 else
              [min(atom["coordinates_A"][axis] for atom in atoms) for axis in range(3)])
    return sum(sasa._calculate(atoms, origin, _params()))


def _measured(tmp_path: Path, raw: bytes | None = None):
    run = new_run(tmp_path, run_id="run_sasa", dry_run=False)
    source = run.call("load_structure", {"source": str(tmp_path / "removed_source.pdb")},
                      source_bytes=raw or FIX.read_bytes(), source_format="pdb")
    prepared = run.call("prepare_structure", {"structure": source.handle})
    ligand = structure_residues(run.store, prepared.handle)["ligands"][0]
    result = run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": ligand})
    return run, prepared, ligand, result


def test_analytic_spheres_translation_and_rotation():
    r = 1.7 + 1.4
    single = 4 * math.pi * r * r
    first = _sphere(0, 0, 0)
    far = _sphere(100, 0, 0)
    overlap = _sphere(r, 0, 0)
    assert abs(_area([first]) - single) < 1e-6
    separated = _area([first, far])
    assert abs(separated - 2 * single) < 1e-6
    assert abs(2 * single - separated) < 1e-6  # zero partner burial is a measured result
    # Expanded equal spheres at d=r: exposed union = 4πr² + 2πrd.
    reference = 4 * math.pi * r * r + 2 * math.pi * r * r
    for atoms in ([first, overlap], [_sphere(500, -600, 700), _sphere(500 + r, -600, 700)],
                  [_sphere(0, 0, 0), _sphere(0, r, 0)], [_sphere(0, 0, 0), _sphere(0, 0, r)]):
        assert abs(_area(atoms) - reference) <= 0.005 * reference + 1e-6


def test_preflight_rejects_native_hazards_before_free_sasa(monkeypatch):
    monkeypatch.setattr(freesasa, "calcCoord", lambda *args, **kwargs: pytest.fail("native call reached"))
    base = _sphere(0, 0, 0)
    cases = [
        ([base], [_sphere(0, 0, 0)], FailureClass.input_invalid),
        ([base], [_sphere(0.0000005, 0, 0)], FailureClass.input_invalid),
        ([base], [_sphere(1e6 + 1, 0, 0)], FailureClass.input_invalid),
        ([base], [_sphere(10001, 0, 0)], FailureClass.resource_exceeded),
        ([base], [{**_sphere(5, 0, 0), "radius_A": 0}], FailureClass.input_invalid),
        ([base], [{**_sphere(5, 0, 0), "coordinates_A": [math.nan, 0, 0]}], FailureClass.input_invalid),
        ([base], [{**_sphere(5, 0, 0), "coordinates_A": [5, 0]}], FailureClass.input_invalid),
        ([base], [{**_sphere(5, 0, 0), "coordinates_A": [5, 0, 0, 0]}], FailureClass.input_invalid),
        ([], [_sphere(5, 0, 0)], FailureClass.input_invalid),
        ([base] * 6000, [_sphere(5, 0, 0)], FailureClass.resource_exceeded),
    ]
    for protein, ligand, failure in cases:
        with pytest.raises(ToolFailure) as raised:
            sasa._preflight(protein, ligand)
        assert raised.value.cls == failure
    for malformed in ({**base, "coordinates_A": [0, 0]}, {**base, "coordinates_A": [0, 0, 0, 0]},
                      {**base, "radius_A": math.inf}):
        with pytest.raises(ToolFailure) as raised:
            sasa._calculate([malformed], [0, 0, 0], _params())
        assert raised.value.cls == FailureClass.input_invalid


def test_real_result_mapping_accounting_cache_and_identity(tmp_path):
    run, prepared, ligand, result = _measured(tmp_path)
    data = run.store.load(result.handle)
    assert data["method"]["method_id"] == "freesasa_lee_richards_v1"
    assert data["method"]["algorithm"] == "LeeRichards" and data["method"]["n_slices"] == 100
    assert data["method"]["engine_version"] == "2.2.1" and data["method"]["gemmi_version"] == "0.7.5"
    assert data["method"]["radius_policy"] == "gemmi_vdw_elements_v1"
    assert data["ligand"] == ligand and data["atom_counts"] == {"protein": 15, "ligand": 3, "excluded_residues": 2}
    assert {item["residue"]["resname"] for item in data["selection"]["excluded"]} == {"ZN", "HOH"}
    assert data["selection"]["protein_residues"][0]["icode"] == "A"
    assert any(row["residue"]["seq_auth"] == 100 and row["residue"]["icode"] == "A" for row in data["residues"])
    assert all(atom["residue"] == ligand for atom in data["atoms"][15:])
    assert all(atom["index"] == i for i, atom in enumerate(data["atoms"]))
    summary = data["summary"]
    assert math.isclose(summary["protein_burial_A2"] + summary["ligand_burial_A2"],
                        summary["total_sasa_loss_A2"], abs_tol=1e-6)
    assert math.isclose(sum(row["buried_A2"] for row in data["residues"]), summary["protein_burial_A2"], abs_tol=1e-6)
    assert run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": ligand}).handle == result.handle
    assert any(e["type"] == "cache_hit" and e["output"]["handle"] == result.handle for e in run.events.read())
    old_key = run._key("compute_interface_sasa", "1", {"structure": prepared.handle, "ligand": ligand}, None, None)
    assert run._key("compute_interface_sasa", "1", {"structure": prepared.handle,
                   "ligand": {**ligand, "chain_label": "another"}}, None, None) != old_key
    with pytest.raises(ToolFailure, match="unknown parameters"):
        run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": ligand,
                                            "n_slices": 1000})
    original = sasa.dependencies
    def changed():
        dep = original()
        dep["radii_A"]["C"] += 0.01
        return dep
    sasa.dependencies = changed
    try:
        assert run._key("compute_interface_sasa", "1", {"structure": prepared.handle, "ligand": ligand}, None, None) != old_key
    finally:
        sasa.dependencies = original
    wrong = {**ligand, "chain_label": "B"}
    with pytest.raises(ToolFailure, match="full ligand|selected ligand"):
        run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": wrong})
    with pytest.raises(ToolFailure, match="full ligand"):
        run.call("compute_interface_sasa", {"structure": prepared.handle,
                                            "ligand": {key: value for key, value in ligand.items() if key != "seq_label"}})


def test_unknown_element_duplicate_and_dry_run(tmp_path, monkeypatch):
    raw = FIX.read_bytes().replace(b"HETATM   17  C1  LIG", b"HETATM   17  C1  LIG")
    # Replace the ligand's element column, keeping a valid PDB atom record.
    lines = raw.splitlines(keepends=True)
    lines = [line[:76] + b"ZN" + line[78:] if line.startswith(b"HETATM   17") else line for line in lines]
    run = new_run(tmp_path / "unknown", run_id="run_unknown", dry_run=False)
    source = run.call("load_structure", {"source": str(FIX)}, source_bytes=b"".join(lines), source_format="pdb")
    prep = run.call("prepare_structure", {"structure": source.handle})
    ligand = structure_residues(run.store, prep.handle)["ligands"][0]
    monkeypatch.setattr(freesasa, "calcCoord", lambda *args, **kwargs: pytest.fail("native call reached"))
    with pytest.raises(ToolFailure, match="unsupported SASA element"):
        run.call("compute_interface_sasa", {"structure": prep.handle, "ligand": ligand})
    duplicate = FIX.read_bytes().replace(b"END\n", FIX.read_bytes().splitlines(keepends=True)[16] + b"END\n")
    run2 = new_run(tmp_path / "duplicate", run_id="run_duplicate", dry_run=False)
    src2 = run2.call("load_structure", {"source": str(FIX)}, source_bytes=duplicate, source_format="pdb")
    prep2 = run2.call("prepare_structure", {"structure": src2.handle})
    lig2 = structure_residues(run2.store, prep2.handle)["ligands"][0]
    with pytest.raises(ToolFailure, match="ambiguous full residue identity"):
        run2.call("compute_interface_sasa", {"structure": prep2.handle, "ligand": lig2})
    dry = new_run(tmp_path / "dry", run_id="run_dry", dry_run=True)
    src = dry.call("load_structure", {"source": str(FIX)})
    prepared = dry.call("prepare_structure", {"structure": src.handle})
    dry_ligand = structure_residues(dry.store, prepared.handle)["ligands"][0]
    with pytest.raises(ToolFailure, match="dry-run"):
        dry.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": dry_ligand})


def test_zero_area_protein_row_is_retained(tmp_path):
    hydrogen_only = b"ATOM     21  H   ALA A 102      30.000  30.000  30.000  1.00 20.00           H\n"
    raw = FIX.read_bytes().replace(b"END\n", hydrogen_only + b"END\n")
    run = new_run(tmp_path, run_id="run_zero_row", dry_run=False)
    source = run.call("load_structure", {"source": str(tmp_path / "removed.pdb")},
                      source_bytes=raw, source_format="pdb")
    prepared = run.call("prepare_structure", {"structure": source.handle, "hydrogens": "keep"})
    ligand = structure_residues(run.store, prepared.handle)["ligands"][0]
    result = run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": ligand})
    rows = run.store.load(result.handle)["residues"]
    zero = next(row for row in rows if row["residue"]["resname"] == "ALA")
    assert zero["atom_indices"] == [] and zero["isolated_A2"] == zero["bound_A2"] == zero["buried_A2"] == 0
    report = build_method_report(run, result.handle)["manifest"]
    assert any(row["residue"] == zero["residue"] for row in report["residues"])


def test_separated_product_partners_keep_positive_sasa_and_zero_burial(tmp_path):
    raw = (b"ATOM      1  C   ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n"
           b"HETATM    2  C1  LIG B   2     100.000   0.000   0.000  1.00 20.00           C\nEND\n")
    run = new_run(tmp_path, run_id="run_separated", dry_run=False)
    source = run.call("load_structure", {"source": str(tmp_path / "removed.pdb")},
                      source_bytes=raw, source_format="pdb")
    prepared = run.call("prepare_structure", {"structure": source.handle})
    ligand = structure_residues(run.store, prepared.handle)["ligands"][0]
    result = run.call("compute_interface_sasa", {"structure": prepared.handle, "ligand": ligand})
    summary = run.store.load(result.handle)["summary"]
    assert result.null_result is False
    assert summary["protein_sasa_isolated_A2"] > 0 and summary["ligand_sasa_isolated_A2"] > 0
    assert abs(summary["protein_burial_A2"]) < 1e-6
    assert abs(summary["ligand_burial_A2"]) < 1e-6
    assert abs(summary["total_sasa_loss_A2"]) < 1e-6


def test_method_claim_report_and_events_only_recovery(tmp_path, monkeypatch):
    run, _, _, result = _measured(tmp_path)
    artifact = build_method_report(run, result.handle)
    report = artifact["manifest"]
    assert _render(2.625, "area_2dp") == "2.63" and _render(-0.0001, "area_2dp") == "0.00"
    assert report["schema"] == "method_report_manifest@1" and report["analysis_type"] == "interface_sasa"
    assert len(report["capabilities"]["protocols"]) == 4
    assert all(not item["available"] for item in report["capabilities"]["protocols"].values())
    assert len(report["residues"]) == 2 and len(report["claims"]) == 8 + 3 * len(report["residues"])
    claim = report["claims"][-1]
    assert validate_method_claim(run.store, claim) == claim
    for alteration in ({"unit": "angstrom"}, {"quantity": "ligand_burial_A2"},
                       {"field_path": "summary.ligand_burial_A2"}, {"exact_value": claim["exact_value"] + 1},
                       {"rendered_value": "0.00"}, {"row_fingerprint": "0" * 64},
                       {"subject": {**claim["subject"], "ligand": {**claim["subject"]["ligand"], "seq_auth": 999}}},
                       {"subject": {**claim["subject"], "prepared_handle": "obj://foreign/prepared_structure/" + "0" * 64}},
                       {"subject": {**claim["subject"], "residue": report["residues"][0]["residue"]}},
                       {"source_handle": report["prepared_handle"]}):
        with pytest.raises(EvidenceError):
            validate_method_claim(run.store, {**claim, **alteration})
    foreign = run.store.put("interface_sasa", "interface_sasa@1", {**copy.deepcopy(run.store.load(result.handle)),
                                                                     "summary": {**report["summary"], "total_sasa_loss_A2": 42}},
                            produced_by="test_fixture", summary={})
    with pytest.raises(EvidenceError):
        build_method_report(run, foreign.handle)
    exact_manifest = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    exact_markdown = artifact["markdown"].encode()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    reopened = new_run(tmp_path, run_id="run_sasa", dry_run=False)
    monkeypatch.setattr(freesasa, "calcCoord", lambda *args, **kwargs: pytest.fail("replay recomputed SASA"))
    restored = saved_method_report(reopened, artifact["handle"])
    assert restored["markdown"].encode() == exact_markdown
    assert json.dumps(restored["manifest"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() == exact_manifest
    assert reopened.store.load(result.handle)["summary"] == report["summary"]


@pytest.mark.parametrize(
    ("kind", "metadata_schema", "payload_schema", "expected_error"),
    [("job_result", "job_fixture@1", "interface_sasa@1", "wrong_result_kind"),
     ("interface_sasa", "interface_sasa@999", "interface_sasa@1", "wrong_result_kind"),
     ("interface_sasa", "interface_sasa@1", "interface_sasa@999", "result_schema_mismatch")],
)
def test_saved_method_report_rejects_paired_wrong_result_type(
        tmp_path, monkeypatch, kind, metadata_schema, payload_schema, expected_error):
    run, _, _, result = _measured(tmp_path)
    artifact = build_method_report(run, result.handle)
    assert saved_method_report(run, artifact["handle"]) == artifact

    data = copy.deepcopy(run.store.load(result.handle))
    data["schema"] = payload_schema
    foreign = run.store.put(kind, metadata_schema, data, produced_by="test_fixture", summary={})
    report = copy.deepcopy(artifact["manifest"])
    report["result_handle"] = foreign.handle
    report["claims"] = [_claim(foreign.handle, data, field, data["summary"][field]) for field in SUMMARY_FIELDS]
    report["claims"].extend(_claim(foreign.handle, data, field, row[field], row_index=index)
                            for index, row in enumerate(data["residues"]) for field in ROW_FIELDS)
    forged = run.store.put("method_report_manifest", "method_report_manifest@1", report,
                           produced_by="test_fixture", summary={})
    run.events.append("method_report_created", report_handle=forged.handle,
                      markdown_handle=report["markdown_handle"], result_handle=foreign.handle)
    assert any(event["type"] == "method_report_created" and event.get("report_handle") == forged.handle
               and event.get("markdown_handle") == report["markdown_handle"]
               and event.get("result_handle") == foreign.handle for event in run.events.read())
    monkeypatch.setattr(freesasa, "calcCoord", lambda *args, **kwargs: pytest.fail("saved read recomputed SASA"))
    monkeypatch.setattr(method_reports, "dependencies", lambda: pytest.fail("saved read queried current dependencies"))
    with pytest.raises(EvidenceError, match=expected_error):
        saved_method_report(run, forged.handle)


def test_http_real_bytes_method_report_download_and_reopen(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "http-runs")
    appmod.RUNS.clear()
    client = TestClient(appmod.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={}).json()["run_id"]
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "fixture.pdb"}, content=FIX.read_bytes())
    assert upload.status_code == 201
    source = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure", "args": {"source": upload.json()["upload_id"]}}).json()["handle"]
    prep = client.post(f"/runs/{rid}/commands", json={"tool": "prepare_structure", "args": {"structure": source["handle"]}}).json()["handle"]
    ligand = client.get(f"/runs/{rid}/structures/residues", params={"handle": prep["handle"]}).json()["ligands"][0]
    computed = client.post(f"/runs/{rid}/commands", json={"tool": "compute_interface_sasa",
                              "args": {"structure": prep["handle"], "ligand": ligand}})
    assert computed.status_code == 200, computed.text
    result = computed.json()["handle"]
    assert result["kind"] == "interface_sasa"
    detail = client.get(f"/runs/{rid}/interface_sasa", params={"handle": result["handle"]})
    assert detail.status_code == 200 and detail.json()["result"]["summary"]["total_sasa_loss_A2"] > 0
    report = client.post(f"/runs/{rid}/method_reports", json={"result_handle": result["handle"]})
    assert report.status_code == 201, report.text
    report_handle = report.json()["handle"]
    listed = client.get(f"/runs/{rid}/reports").json()
    assert any(item.get("result_handle") == result["handle"] for item in listed)
    for fmt in ("markdown", "json"):
        download = client.get(f"/runs/{rid}/reports/download", params={"handle": report_handle, "format": fmt})
        assert download.status_code == 200
        assert download.headers["content-disposition"].startswith('attachment; filename="protview-report-')
        if fmt == "json":
            assert download.json()["result_handle"] == result["handle"]
            assert len(download.json()["atoms"]) == 18
        else:
            assert "Protein–ligand interface SASA" in download.text
    assert client.post(f"/runs/{rid}/method_reports", json={"result_handle": prep["handle"]}).status_code == 422
    assert client.get("/capabilities").json()["methods"]["interface_sasa"]["available"] is True
    run_dir = appmod.RUNS_DIR / rid
    shutil.rmtree(run_dir / "uploads")
    shutil.rmtree(run_dir / "objects")
    (run_dir / "index.sqlite").unlink()
    appmod.RUNS.clear()
    monkeypatch.setattr(freesasa, "calcCoord", lambda *args, **kwargs: pytest.fail("HTTP replay recomputed SASA"))
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": report_handle}).status_code == 200
    assert client.get(f"/runs/{rid}/interface_sasa", params={"handle": result["handle"]}).status_code == 200
