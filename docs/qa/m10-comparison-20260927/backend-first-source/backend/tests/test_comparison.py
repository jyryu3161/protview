"""Independent synthetic-coordinate oracles for M10 measurements."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from mw.comparison_reports import build_comparison_report, saved_comparison_report, validated_comparison_result
from mw.core.errors import FailureClass, ToolFailure
from mw.reports import EvidenceError
from mw.tools.comparison import atom_rows
from mw.workspace import new_run

FIX = Path(__file__).parents[2] / "frontend/tests/offscreen/fixtures"


def _load(run, filename: str, model_index: int = 0) -> str:
    return run.call("load_structure", {"source": str(FIX / filename), "model_index": model_index}).handle


def _atom(catalog, seq: int, name: str, alt: str = "") -> dict:
    return next(row["ref"] for row in catalog["rows"] if row["ref"]["residue"]["seq_auth"] == seq
                and row["ref"]["atom_name"] == name and row["ref"]["altloc"] == alt)


def _pairs(ref, mov):
    return [{"reference": _atom(ref, seq, "CA", alt), "moving": _atom(mov, seq, "CA", alt)}
            for seq, alt in [(10, "A"), (11, ""), (12, ""), (13, "")]]


def test_distance_exact_zero_source_binding_and_cache(tmp_path):
    run = new_run(tmp_path, run_id="distance")
    handle = _load(run, "m10-reference.pdb")
    rows = atom_rows(run.store, handle)
    assert rows["total"] == 17
    assert rows["rows"][1]["ref"]["residue"]["chain_label"] == "Axp"
    assert rows["rows"][1]["ref"]["residue"]["seq_label"] is None
    a, b = _atom(rows, 10, "N"), _atom(rows, 11, "O")
    measured = run.call("measure_distance", {"structure": handle, "first": a, "second": b})
    result = run.store.load(measured.handle)
    assert result["distance_A"] == 5.0  # independent 3–4–5 coordinate fixture
    assert result["unit"] == "angstrom"
    assert run.call("measure_distance", {"structure": handle, "first": a, "second": b}).handle == measured.handle
    zero = run.store.load(run.call("measure_distance", {"structure": handle,
        "first": _atom(rows, 10, "C"), "second": _atom(rows, 11, "N")}).handle)
    assert zero["distance_A"] == 0.0
    other = _load(run, "m10-moving.pdb")
    with pytest.raises(ToolFailure) as error:
        run.call("measure_distance", {"structure": handle, "first": a,
                                      "second": _atom(atom_rows(run.store, other), 11, "O")})
    assert error.value.cls == FailureClass.input_invalid
    modified = (FIX / "m10-reference.pdb").read_text().replace(
        "4.000   5.000   1.000", "5.000   5.000   1.000")
    changed_file = tmp_path / "changed.pdb"
    changed_file.write_text(modified)
    changed_source = run.call("load_structure", {"source": str(changed_file), "model_index": 0}).handle
    changed_rows = atom_rows(run.store, changed_source)
    changed = run.store.load(run.call("measure_distance", {"structure": changed_source,
        "first": _atom(changed_rows, 10, "N"), "second": _atom(changed_rows, 11, "O")}).handle)
    assert changed["distance_A"] != result["distance_A"]


def test_proper_fit_reflection_order_and_degenerate_inputs(tmp_path):
    run = new_run(tmp_path, run_id="alignment")
    ref_handle = _load(run, "m10-reference.pdb")
    mov_handle = _load(run, "m10-moving.pdb")
    ref, mov = atom_rows(run.store, ref_handle), atom_rows(run.store, mov_handle)
    pairs = _pairs(ref, mov)
    output = run.call("align_structures", {"reference": ref_handle, "moving": mov_handle, "pairs": pairs})
    result = run.store.load(output.handle)
    rotation = np.asarray(result["rotation"])
    translation = np.asarray(result["translation_A"])
    assert result["rmsd_A"] <= 1e-8
    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=1e-10)
    assert rotation.T @ rotation == pytest.approx(np.eye(3), abs=1e-10)
    p = np.asarray([row["moving_coordinate_A"] for row in result["pairs"]])
    q = np.asarray([row["reference_coordinate_A"] for row in result["pairs"]])
    residual = np.linalg.norm(p @ rotation.T + translation - q, axis=1)
    assert math.sqrt(float(np.mean(residual ** 2))) == pytest.approx(result["rmsd_A"], abs=1e-10)
    assert result["unaligned_rmsd_A"] == pytest.approx(math.sqrt(float(np.mean(np.sum((p-q)**2, axis=1)))))
    shuffled = run.store.load(run.call("align_structures", {"reference": ref_handle,
        "moving": mov_handle, "pairs": list(reversed(pairs))}).handle)
    assert np.asarray(shuffled["rotation"]) == pytest.approx(rotation, abs=1e-8)
    reflected_handle = _load(run, "m10-reflected.pdb")
    reflected = run.store.load(run.call("align_structures", {"reference": ref_handle,
        "moving": reflected_handle, "pairs": _pairs(ref, atom_rows(run.store, reflected_handle))}).handle)
    assert reflected["rmsd_A"] > 0.1
    assert np.linalg.det(np.asarray(reflected["rotation"])) == pytest.approx(1.0, abs=1e-10)
    collinear_handle = _load(run, "m10-collinear.pdb")
    with pytest.raises(ToolFailure) as error:
        run.call("align_structures", {"reference": ref_handle, "moving": collinear_handle,
                                      "pairs": _pairs(ref, atom_rows(run.store, collinear_handle))})
    assert error.value.cls == FailureClass.input_invalid
    with pytest.raises(ToolFailure):
        run.call("align_structures", {"reference": ref_handle, "moving": mov_handle,
                                      "pairs": [pairs[0], pairs[0], pairs[2]]})
    bad = copy.deepcopy(pairs)
    bad[0]["reference"]["site_index"] = 0
    with pytest.raises(ToolFailure):
        run.call("align_structures", {"reference": ref_handle, "moving": mov_handle, "pairs": bad})


def test_catalog_preserves_duplicate_sites_altloc_insertion_and_model(tmp_path):
    run = new_run(tmp_path, run_id="identities")
    one = _load(run, "m10-identities.pdb", 0)
    two = _load(run, "m10-identities.pdb", 1)
    for handle, number in [(one, 1), (two, 2)]:
        catalog = atom_rows(run.store, handle)
        ca_a = [row for row in catalog["rows"] if row["ref"]["atom_name"] == "CA"
                and row["ref"]["altloc"] == "A"]
        assert len(ca_a) == 2
        assert ca_a[0]["ref"]["site_index"] != ca_a[1]["ref"]["site_index"]
        assert all(row["ref"]["residue"]["model_number"] == number for row in catalog["rows"])
        assert all(row["ref"]["residue"]["icode"] == "A" for row in catalog["rows"])
        assert all(row["ref"]["residue"]["chain_label"] == "Axp" for row in catalog["rows"])
        assert all(row["ref"]["residue"]["seq_label"] is None for row in catalog["rows"])


def test_three_planar_pairs_and_near_or_coincident_degeneracy(tmp_path):
    run = new_run(tmp_path, run_id="rank")
    ref = _load(run, "m10-reference.pdb")
    mov = _load(run, "m10-moving.pdb")
    a, b = atom_rows(run.store, ref), atom_rows(run.store, mov)
    planar_handle = run.call("align_structures", {"reference": ref, "moving": mov,
        "pairs": _pairs(a, b)[:3]}).handle
    planar = run.store.load(planar_handle)
    assert planar["pair_count"] == 3 and planar["rmsd_A"] <= 1e-8
    assert planar["fit_singular_values_A2"][2] <= 1e-8
    report = build_comparison_report(run, planar_handle)
    assert saved_comparison_report(run, report["handle"])["manifest"]["result_handle"] == planar_handle
    near = _load(run, "m10-near-degenerate.cif")
    near_catalog = atom_rows(run.store, near)
    near_pairs = [{"reference": _atom(a, seq, "CA", "A" if seq == 10 else ""),
                   "moving": _atom(near_catalog, seq, "CA")}
                  for seq in (10, 11, 12, 13)]
    with pytest.raises(ToolFailure) as error:
        run.call("align_structures", {"reference": ref, "moving": near,
            "pairs": near_pairs})
    assert error.value.cls == FailureClass.input_invalid
    raw = (FIX / "m10-reference.pdb").read_text()
    coincident = "\n".join(line[:30] + "   0.000   0.000   0.000" + line[54:]
        if line.startswith(("ATOM  ", "HETATM")) else line for line in raw.splitlines()) + "\n"
    file = tmp_path / "coincident.pdb"
    file.write_text(coincident)
    same = run.call("load_structure", {"source": str(file), "model_index": 0}).handle
    with pytest.raises(ToolFailure) as error:
        run.call("align_structures", {"reference": ref, "moving": same,
            "pairs": _pairs(a, atom_rows(run.store, same))})
    assert error.value.cls == FailureClass.input_invalid


def test_catalog_exact_source_order_and_prepared_mapping(tmp_path, monkeypatch):
    from mw.tools import comparison

    run = new_run(tmp_path, run_id="map")
    for model_index in (0, 1):
        source = _load(run, "m10-identities.pdb", model_index)
        catalog = atom_rows(run.store, source)
        assert [row["viewer_source_index"] for row in catalog["rows"]] == list(range(6))
        assert [row["coordinate_A"][0] for row in catalog["rows"]] == [
            value + (20 if model_index else 0) for value in (0, 1, 1.5, 1.25, 2, 3)]
        assert len({json.dumps(row["ref"], sort_keys=True) for row in catalog["rows"]}) == 6
        prepared = run.call("prepare_structure", {"structure": source}).handle
        prepared_catalog = atom_rows(run.store, prepared)
        assert all(row["ref"]["structure_handle"] == prepared for row in prepared_catalog["rows"])
        assert len({row["viewer_source_index"] for row in prepared_catalog["rows"]}) == prepared_catalog["total"]
        assert all(row["ref"]["residue"]["model_number"] == model_index + 1
                   for row in prepared_catalog["rows"])
    monkeypatch.setattr(comparison, "MAX_ATOMS", 2)
    with pytest.raises(ToolFailure) as error:
        atom_rows(run.store, source)
    assert error.value.cls == FailureClass.resource_exceeded


def test_identical_original_sites_do_not_guess_a_viewer_index(tmp_path):
    run = new_run(tmp_path, run_id="duplicates")
    lines = (FIX / "m10-reference.pdb").read_text().splitlines()
    duplicate = next(line for line in lines if line.startswith("ATOM  ") and line[12:16].strip() == "CA")
    lines.insert(-2, duplicate[:6] + f"{18:5d}" + duplicate[11:])
    fixture = tmp_path / "identical-sites.pdb"
    fixture.write_text("\n".join(lines) + "\n")
    source = run.call("load_structure", {"source": str(fixture), "model_index": 0}).handle
    with pytest.raises(ToolFailure) as error:
        atom_rows(run.store, source)
    assert error.value.cls == FailureClass.input_invalid


def test_strict_refs_wrong_source_kind_nonprotein_ca_and_hydrogen(tmp_path):
    run = new_run(tmp_path, run_id="invalid")
    source = _load(run, "m10-reference.pdb")
    catalog = atom_rows(run.store, source)
    first, second = _atom(catalog, 10, "N"), _atom(catalog, 11, "O")
    extra = {**first, "browser_guess": [1, 2, 3]}
    for proposed in (extra, {**first, "residue": {**first["residue"], "seq_label": 10}},
                     {**first, "atom_name": "CA"}, {**first, "element": "H"}):
        with pytest.raises(ToolFailure) as error:
            run.call("measure_distance", {"structure": source, "first": proposed, "second": second})
        assert error.value.cls == FailureClass.input_invalid
    wrong_kind = run.call("measure_distance", {"structure": source, "first": first, "second": second}).handle
    with pytest.raises(ToolFailure):
        atom_rows(run.store, wrong_kind)
    other_run = new_run(tmp_path, run_id="foreign")
    foreign = _load(other_run, "m10-reference.pdb")
    with pytest.raises(ToolFailure):
        run.call("measure_distance", {"structure": foreign, "first": first, "second": second})
    raw = (FIX / "m10-reference.pdb").read_text()
    changed = []
    for line in raw.splitlines():
        if line.startswith("ATOM  ") and line[22:26].strip() == "13":
            line = line[:17] + "LIG" + line[20:]
        changed.append(line)
    changed.insert(-2, "ATOM     18    H ALA A  10       1.100   1.100   1.100  1.00 20.00           H  ")
    fixture = tmp_path / "nonprotein-ca.pdb"
    fixture.write_text("\n".join(changed) + "\n")
    altered = run.call("load_structure", {"source": str(fixture), "model_index": 0}).handle
    rows = atom_rows(run.store, altered)
    assert any(row["ref"]["element"] == "H" for row in rows["rows"])
    ligand_ca = _atom(rows, 13, "CA")
    assert not rows["rows"][ligand_ca["site_index"]]["protein"]
    pairs = [{"reference": _atom(catalog, seq, "CA", "A" if seq == 10 else ""),
              "moving": _atom(rows, seq, "CA", "A" if seq == 10 else "")}
             for seq in (10, 11, 13)]
    with pytest.raises(ToolFailure) as error:
        run.call("align_structures", {"reference": source, "moving": altered, "pairs": pairs})
    assert error.value.cls == FailureClass.input_invalid


def test_reports_validate_source_claims_transform_and_provenance(tmp_path, monkeypatch):
    run = new_run(tmp_path, run_id="claims")
    ref, mov = _load(run, "m10-reference.pdb"), _load(run, "m10-moving.pdb")
    a, b = atom_rows(run.store, ref), atom_rows(run.store, mov)
    distance = run.call("measure_distance", {"structure": ref,
        "first": _atom(a, 10, "N"), "second": _atom(a, 11, "O")}).handle
    alignment = run.call("align_structures", {"reference": ref, "moving": mov,
        "pairs": _pairs(a, b)}).handle
    for handle, analysis_type in [(distance, "atom_distance"), (alignment, "rigid_alignment")]:
        artifact = build_comparison_report(run, handle)
        assert saved_comparison_report(run, artifact["handle"])["markdown"] == artifact["markdown"]
        claims = artifact["manifest"]["claims"]
        assert all(item["source_handle"] == handle and item["source_sha256"] == handle.rsplit("/", 1)[-1]
                   for item in claims)
        assert artifact["manifest"]["analysis_type"] == analysis_type
        if analysis_type == "rigid_alignment":
            assert len([item for item in claims if item["field_path"].startswith("rotation[")]) == 9
            assert all(item["unit"] == "dimensionless" for item in claims
                       if item["field_path"].startswith("rotation["))
        raw_load = run.store.load
        damaged = copy.deepcopy(artifact["manifest"])
        damaged["analysis_type"] = "atom_distance" if analysis_type == "rigid_alignment" else "rigid_alignment"
        with monkeypatch.context() as patch:
            patch.setattr(run.store, "load", lambda item, original=raw_load, value=damaged,
                          report_handle=artifact["handle"]: value if item == report_handle else original(item))
            with pytest.raises(EvidenceError):
                saved_comparison_report(run, artifact["handle"])
        damaged = copy.deepcopy(artifact["manifest"])
        damaged["provenance"]["tool"] = "compute_interactions"
        with monkeypatch.context() as patch:
            patch.setattr(run.store, "load", lambda item, original=raw_load, value=damaged,
                          report_handle=artifact["handle"]: value if item == report_handle else original(item))
            with pytest.raises(EvidenceError):
                saved_comparison_report(run, artifact["handle"])
        for mutation in (lambda item: item["claims"][0].__setitem__("unit", "kilojoule_per_mole"),
                         lambda item: item["claims"][0].__setitem__("field_path", "distance_A"),
                         lambda item: item["claims"][0].__setitem__("rendered_value", "999")):
            damaged = copy.deepcopy(artifact["manifest"])
            mutation(damaged)
            with monkeypatch.context() as patch:
                patch.setattr(run.store, "load", lambda item, original=raw_load, value=damaged,
                              report_handle=artifact["handle"]: value if item == report_handle else original(item))
                with pytest.raises(EvidenceError):
                    saved_comparison_report(run, artifact["handle"])
    raw_load = run.store.load
    for changed in (lambda item: item.__setitem__("rmsd_A", 99.0),
                    lambda item: item["pairs"][0].__setitem__("reference_coordinate_A", [9.0, 9.0, 9.0]),
                    lambda item: item.__setitem__("rotation", [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]),
                    lambda item: item["pairs"][0].__setitem__("after_residual_A", 99.0)):
        damaged = copy.deepcopy(raw_load(alignment))
        changed(damaged)
        with monkeypatch.context() as patch:
            patch.setattr(run.store, "load", lambda item, original=raw_load, value=damaged:
                          value if item == alignment else original(item))
            with pytest.raises(EvidenceError):
                validated_comparison_result(run.store, alignment)


def test_events_only_report_read_never_refits_or_opens_original_paths(tmp_path, monkeypatch):
    path_a, path_b = tmp_path / "reference.pdb", tmp_path / "moving.pdb"
    path_a.write_bytes((FIX / "m10-reference.pdb").read_bytes())
    path_b.write_bytes((FIX / "m10-moving.pdb").read_bytes())
    run = new_run(tmp_path, run_id="replay")
    ref = run.call("load_structure", {"source": str(path_a), "model_index": 0}).handle
    mov = run.call("load_structure", {"source": str(path_b), "model_index": 0}).handle
    alignment = run.call("align_structures", {"reference": ref, "moving": mov,
        "pairs": _pairs(atom_rows(run.store, ref), atom_rows(run.store, mov))}).handle
    saved = build_comparison_report(run, alignment)
    original_json = json.dumps(saved["manifest"], sort_keys=True, ensure_ascii=False)
    original_md = saved["markdown"].encode()
    path_a.unlink(); path_b.unlink()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    with monkeypatch.context() as patch:
        patch.setattr(np.linalg, "svd", lambda *args, **kwargs: pytest.fail("read refitted alignment"))
        reopened = new_run(tmp_path, run_id="replay")
        patch.setattr(reopened, "call", lambda *args, **kwargs: pytest.fail("read invoked tool"))
        recovered = saved_comparison_report(reopened, saved["handle"])
        assert json.dumps(recovered["manifest"], sort_keys=True, ensure_ascii=False) == original_json
        assert recovered["markdown"].encode() == original_md
        assert validated_comparison_result(reopened.store, alignment)["rmsd_A"] <= 1e-8


def test_http_catalog_commands_result_and_report_actual_bytes(tmp_path, monkeypatch):
    import mw.api.app as appmod

    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "api-runs")
    appmod.RUNS.clear()
    client = TestClient(appmod.app)
    rid = client.post("/runs", json={"goal": "M10 local fixture"}).json()["run_id"]
    handles = []
    for filename in ("m10-reference.pdb", "m10-moving.pdb"):
        upload = client.post(f"/runs/{rid}/uploads", params={"filename": filename},
            content=(FIX / filename).read_bytes(), headers={"content-type": "application/octet-stream"})
        assert upload.status_code == 201
        created = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
            "args": {"source": upload.json()["upload_id"], "model_index": 0}})
        assert created.status_code == 200
        handles.append(created.json()["handle"]["handle"])
    catalogs = []
    for handle in handles:
        response = client.get(f"/runs/{rid}/structures/atoms", params={"handle": handle, "limit": 500})
        assert response.status_code == 200
        catalog = response.json()
        assert catalog["schema"] == "atom_catalog@1" and catalog["total"] == len(catalog["rows"])
        assert len(catalog["viewer_source_sha256"]) == 64
        served = client.get(f"/runs/{rid}/structures/bytes", params={"handle": handle})
        assert served.status_code == 200
        assert catalog["viewer_source_sha256"] == hashlib.sha256(served.content).hexdigest()
        assert client.get(f"/runs/{rid}/structures/atoms", params={"handle": handle,
            "offset": 1, "limit": 2}).json()["rows"] == catalog["rows"][1:3]
        catalogs.append(catalog)
    first = next(row["ref"] for row in catalogs[0]["rows"] if row["ref"]["atom_name"] == "N")
    second = next(row["ref"] for row in catalogs[0]["rows"] if row["ref"]["atom_name"] == "O"
                  and row["ref"]["residue"]["seq_auth"] == 11)
    response = client.post(f"/runs/{rid}/commands", json={"tool": "measure_distance",
        "args": {"structure": handles[0], "first": first, "second": second}})
    assert response.status_code == 200, response.text
    result_handle = response.json()["handle"]["handle"]
    measured = client.get(f"/runs/{rid}/objects/measurement", params={"handle": result_handle})
    assert measured.status_code == 200 and measured.json()["result"]["distance_A"] == 5.0
    cross = client.post(f"/runs/{rid}/commands", json={"tool": "measure_distance",
        "args": {"structure": handles[0], "first": first,
                 "second": next(row["ref"] for row in catalogs[1]["rows"] if row["ref"]["atom_name"] == "N")}})
    assert cross.status_code in {400, 422}
    report = client.post(f"/runs/{rid}/method_reports", json={"result_handle": result_handle})
    assert report.status_code == 201, report.text
    report_handle = report.json()["handle"]
    downloaded = client.get(f"/runs/{rid}/reports/download", params={"handle": report_handle,
        "format": "markdown"})
    assert downloaded.status_code == 200 and downloaded.content == report.json()["markdown"].encode()
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": report_handle}).status_code == 200
    assert client.get(f"/runs/{rid}/budget").json()["expensive_calls"]["used"] == 0
