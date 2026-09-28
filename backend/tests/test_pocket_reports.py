"""M12 ``pocket_report@1`` (method_report_manifest@1, analysis_type pocket_detection) over real fpocket results.

Every pocket_set here is produced by the real installed fpocket 4.2.3 build through the product HTTP path
(helpers shared with test_pocket_jobs.py); these tests FAIL, never skip, when the engine is absent. No
pocket counts or descriptor values are hard-coded: each report claim is re-resolved independently from
the stored pocket_set / detector-input bytes. Inputs: ``public_1hsg.cif`` (public PDB entry) and the
labeled derived fixture ``derived_1hsg_first10_fixture.cif``. Forged report manifests below are labeled
test fabrications written only to prove that the saved-report validator rejects them.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from test_pocket_jobs import DERIVED_FIRST10, HSG, _client, _detect, _new_run, _prepared

from mw import pocket_bundle
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.pocket_reports import EVIDENCE_STATEMENT, validate_pocket_claim
from mw.reports import EvidenceError
from mw.runtime.orchestrator import Run

RESIDUE_FIELDS = ("model_number", "chain_auth", "seq_auth", "icode", "chain_label", "seq_label", "resname")
PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")


def _resolve(document: dict, path: str):
    """Independent field-path resolver (``a.b[2].c``) over stored JSON."""
    value = document
    for part in path.split("."):
        match = PATH_PART.fullmatch(part)
        assert match, path
        value = value[match.group(1)]
        if match.group(2) is not None:
            value = value[int(match.group(2))]
    return value


def _render(value, rounding: str) -> str:
    if rounding == "integer":
        assert type(value) is int
        return str(value)
    if rounding == "exact":
        return repr(value)
    assert rounding == "native_3dp"
    return f"{value:.3f}"


def _verify_claims_independently(run: Run, manifest: dict) -> None:
    """Re-resolve every claim from the stored objects; recompute the two allowed derived counts."""
    handle = manifest["result_handle"]
    stored = run.store.load(handle)
    detector = run.store.load(stored["detector_input_handle"])
    assert manifest["total_count"] == stored["total_count"] == len(stored["pockets"])
    seen = set()
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["field_path"])
        assert key not in seen
        seen.add(key)
        assert claim["source_sha256"] == claim["source_handle"].rsplit("/", 1)[-1]
        assert claim["subject"]["pocket_set_handle"] == handle
        if claim["source_kind"] == "pocket_set":
            assert claim["source_handle"] == handle and claim["source_schema"] == "pocket_set@1"
            document = stored
        else:
            assert claim["source_kind"] == "pocket_detector_input"
            assert claim["source_handle"] == stored["detector_input_handle"]
            document = detector
        value = _resolve(document, claim["field_path"])
        if claim["statement_id"] == "pocket_count":
            assert value == len(stored["pockets"]) == claim["exact_value"] and claim["unit"] == "count"
        elif claim["statement_id"] == "lining_residue_count":
            index = int(re.match(r"pockets\[(\d+)\]", claim["field_path"]).group(1))
            assert claim["row_selector"] == {"rank": stored["pockets"][index]["rank"]} == {"rank": index + 1}
            distinct = {tuple(residue[field] for field in RESIDUE_FIELDS) for residue in value}
            assert claim["exact_value"] == len(distinct) and claim["unit"] == "count"
        elif claim["statement_id"] == "pocket_descriptor":
            index = int(re.match(r"pockets\[(\d+)\]", claim["field_path"]).group(1))
            pocket = stored["pockets"][index]
            assert claim["row_selector"] == {"rank": pocket["rank"]} and claim["subject"]["rank"] == pocket["rank"]
            descriptor = pocket["descriptors"][claim["quantity"]]
            assert claim["field_path"].endswith(f".descriptors.{claim['quantity']}.value")
            assert value == descriptor["value"] == claim["exact_value"]
            assert claim["unit"] == descriptor["unit"] == stored["units"][claim["quantity"]]
            assert claim["subject"]["native_name"] == descriptor["native_name"]
        elif claim["statement_id"] == "display_center_coordinate":
            index = int(re.match(r"pockets\[(\d+)\]", claim["field_path"]).group(1))
            spheres = stored["pockets"][index]["spheres"]
            axis = claim["field_path"].rsplit(".", 1)[-1]
            mean = sum(sphere[axis] for sphere in spheres) / len(spheres)
            assert abs(mean - value) < 1e-9 and value == claim["exact_value"]
            assert claim["operation"] == "arithmetic_mean_of_stored_sphere_centers" and claim["unit"] == "angstrom"
        else:
            assert claim["statement_id"] in {"excluded_site_count", "transport_count", "quantization"}
            assert value == claim["exact_value"]
        assert claim["rendered_value"] == _render(claim["exact_value"], claim["rounding"])
    ranks = {claim["row_selector"]["rank"] for claim in manifest["claims"] if claim["row_selector"]}
    assert ranks == {pocket["rank"] for pocket in stored["pockets"]}
    assert sum(claim["statement_id"] == "pocket_descriptor" for claim in manifest["claims"]) == 5 * len(ranks)


def _forge(run: Run, manifest: dict, markdown: str, mutate) -> str:
    """LABELED TEST FABRICATION: store a tampered report manifest and its creation event."""
    forged = copy.deepcopy(manifest)
    mutate(forged)
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by="forged_test_report", summary={"result_handle": manifest["result_handle"]})
        forged["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_test_report",
                               summary={"result_handle": forged["result_handle"],
                                        "analysis_type": "pocket_detection", "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"],
                          snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _claim_index(manifest: dict, path: str) -> int:
    return next(i for i, claim in enumerate(manifest["claims"]) if claim["field_path"] == path)


def _report(client, rid: str, handle: str) -> dict:
    created = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert created.status_code == 201, created.text
    return created.json()


def _downloads(client, rid: str, handle: str) -> tuple[bytes, bytes]:
    out = []
    for fmt in ("markdown", "json"):
        response = client.get(f"/runs/{rid}/reports/download", params={"handle": handle, "format": fmt})
        assert response.status_code == 200, response.text
        assert response.headers["content-disposition"].startswith('attachment; filename="protview-report-')
        assert response.headers["x-content-type-options"] == "nosniff"
        out.append(response.content)
    return out[0], out[1]


def _older_sasa_report(client, rid: str, prepared: str) -> str:
    ligands = client.get(f"/runs/{rid}/structures/residues", params={"handle": prepared}).json()["ligands"]
    ligand = next(item for item in ligands if item["resname"] == "MK1")
    computed = client.post(f"/runs/{rid}/commands", json={"tool": "compute_interface_sasa",
                                                          "args": {"structure": prepared, "ligand": ligand}})
    assert computed.status_code == 200, computed.text
    return _report(client, rid, computed.json()["handle"]["handle"])["handle"]


def test_public_1hsg_pocket_report_bytes_evidence_replay_and_rejections(tmp_path, monkeypatch):
    root = tmp_path / "original"
    client = _client(root, monkeypatch)
    rid = _new_run(client, "M12 pocket report on public 1hsg")
    _, prepared = _prepared(client, rid, HSG.read_bytes(), "public_1hsg.cif")
    older = _older_sasa_report(client, rid, prepared)
    older_bytes = _downloads(client, rid, older)

    handle = _detect(client, rid, prepared)["artifacts"]["pocket_set"]
    run = api_module._run(rid)
    stored = run.store.load(handle)
    assert stored["total_count"] >= 1
    created = _report(client, rid, handle)
    assert set(created) == {"handle", "markdown_handle", "manifest", "markdown"}
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["schema"] == "method_report_manifest@1" and manifest["analysis_type"] == "pocket_detection"
    assert manifest["result_schema"] == "pocket_set@1" and manifest["result_handle"] == handle
    assert manifest["status"] == "complete" and manifest["generation_mode"] == "local_rules_no_egress"
    assert manifest["method"] == stored["method"] and manifest["null_result"] is False
    assert manifest["selection"]["selected_chains"] == ["A", "B"]
    assert manifest["provenance"]["protocol_id"] == "fpocket_detect_v1"
    assert manifest["evidence_statement"] == EVIDENCE_STATEMENT
    assert all(item in manifest["limitations"] for item in stored["limitations"])
    assert [pocket["rank"] for pocket in manifest["pockets"]] == list(range(1, stored["total_count"] + 1))
    _verify_claims_independently(run, manifest)

    # Markdown states every bound number, the limits and warnings, and carries no remote content.
    claims = {claim["field_path"]: claim for claim in manifest["claims"]}
    assert f"- Pocket candidates: {claims['total_count']['rendered_value']} " in markdown
    for index, pocket in enumerate(stored["pockets"]):
        row = next(line for line in markdown.splitlines() if line.startswith(f"| {pocket['rank']} | "))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        expected = [claims[f"pockets[{index}].descriptors.{key}.value"]["rendered_value"] for key in
                    ("score", "druggability_score", "alpha_sphere_count", "total_sasa_A2", "volume_A3")]
        assert cells[1:6] == expected
        assert cells[6] == str(len(pocket["lining_residues"]))
    for text in ("결합 부위·친화도·druggability 증거 아님", "fpocket 고유 점수이며 약물성 증거가 아님",
                 "relative within one run", "Monte Carlo estimate", "Seed control: unsupported",
                 "Histidine name mapping", "Transported heavy atoms", "arithmetic mean", "hb88c64c\\_2"):
        assert text in markdown, text
    assert "http" not in markdown and "![" not in markdown and "<" not in markdown

    # Reopen: list, selected and downloads are byte-identical to the created report.
    listed = client.get(f"/runs/{rid}/reports")
    assert listed.status_code == 200, listed.text
    entry = next(item for item in listed.json() if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "pocket_detection" and entry["result_handle"] == handle
    assert entry["markdown_handle"] == created["markdown_handle"]
    selected = client.get(f"/runs/{rid}/reports/selected", params={"handle": created["handle"]})
    assert selected.status_code == 200 and selected.json() == created
    md_bytes, json_bytes = _downloads(client, rid, created["handle"])
    assert md_bytes == markdown.encode("utf-8")
    assert manifest["markdown_handle"] == created["markdown_handle"] and json_bytes == canonical_json(manifest)
    decoded = json.loads(json_bytes)
    assert decoded == manifest
    _verify_claims_independently(run, decoded)
    for claim in decoded["claims"]:
        assert validate_pocket_claim(run, handle, claim) == claim
    assert _downloads(client, rid, older) == older_bytes

    # Wrong kind, foreign run and an unpublished (tampered) pocket_set are rejected.
    for wrong in (stored["detector_input_handle"], stored["native_output_handle"], prepared,
                  f"obj://{rid}/pocket_set/{'0' * 64}"):
        response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": wrong})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"
    unpublished = copy.deepcopy(stored)
    unpublished["pockets"][0]["descriptors"]["volume_A3"]["value"] += 1.0
    with run._owner():
        fake = run.store.put("pocket_set", "pocket_set@1", unpublished, produced_by="forged_test_pocket_set")
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": fake.handle})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"

    # A second real pocket_set (chain A only) in the same run, and a real one from another run.
    other_set = _detect(client, rid, prepared, ["A"])["artifacts"]["pocket_set"]
    other_report = _report(client, rid, other_set)["manifest"]
    rid2 = _new_run(client, "M12 pocket report foreign run")
    _, prepared2 = _prepared(client, rid2, HSG.read_bytes(), "public_1hsg.cif")
    foreign_set = _detect(client, rid2, prepared2)["artifacts"]["pocket_set"]
    foreign_report = _report(client, rid2, foreign_set)["manifest"]
    assert client.post(f"/runs/{rid}/method_reports", json={"result_handle": foreign_set}).status_code == 422

    # Events-only replay (objects, SQLite, upload and engine absent): same report bytes, nothing re-run.
    events_before = (root / rid / "events.jsonl").read_bytes()
    listing_before = client.get(f"/runs/{rid}/reports").json()
    replay = tmp_path / "events_only"
    (replay / rid).mkdir(parents=True)
    (replay / rid / "events.jsonl").write_bytes(events_before)
    monkeypatch.setattr(pocket_bundle, "ENGINE_ROOT", tmp_path / "engine_removed")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("report reopen must not execute scientific work")

    monkeypatch.setattr(JobQueue, "_supervise", forbidden)
    monkeypatch.setattr(Run, "call", forbidden)
    monkeypatch.setattr(pocket_bundle, "publish", forbidden)
    monkeypatch.setattr(pocket_bundle, "project", forbidden)
    monkeypatch.setattr(api_module, "RUNS_DIR", replay)
    api_module.RUNS.clear()
    assert client.get("/capabilities").json()["methods"]["pocket_detection"]["status"] == "not_installed"
    assert _downloads(client, rid, created["handle"]) == (md_bytes, json_bytes)
    assert _downloads(client, rid, older) == older_bytes
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": created["handle"]}).json() == created
    assert client.get(f"/runs/{rid}/reports").json() == listing_before
    assert (replay / rid / "events.jsonl").read_bytes() == events_before
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    run = api_module._run(rid)

    # Tampered claims (labeled fabrications) are rejected on selected and download.
    volume = _claim_index(manifest, "pockets[0].descriptors.volume_A3.value")
    sasa_path = "pockets[0].descriptors.total_sasa_A2.value"
    other_rank = 2 if stored["total_count"] >= 2 else None

    def set_claim(index, **change):
        def mutate(forged):
            forged["claims"][index].update(change)
        return mutate

    def substitute(source_manifest, path):
        def mutate(forged):
            forged["claims"][_claim_index(forged, path)] = copy.deepcopy(
                source_manifest["claims"][_claim_index(source_manifest, path)])
        return mutate

    def other_value(forged):  # the same field's number taken from the other pocket_set
        theirs = other_report["claims"][_claim_index(other_report, "pockets[0].descriptors.volume_A3.value")]
        forged["claims"][volume].update(exact_value=theirs["exact_value"] + (
            1.0 if theirs["exact_value"] == forged["claims"][volume]["exact_value"] else 0.0))
        forged["claims"][volume]["rendered_value"] = f"{forged['claims'][volume]['exact_value']:.3f}"

    tampering = {
        "wrong_unit": set_claim(volume, unit="A2"),
        "wrong_field": set_claim(volume, field_path=sasa_path),
        "wrong_quantity": set_claim(volume, quantity="total_sasa_A2"),
        "wrong_rendering": set_claim(volume, rendered_value="0.000"),
        "unknown_field": set_claim(volume, field_path="pockets[0].native_fields.Polar SASA"),
        "unknown_statement": set_claim(volume, statement_id="binding_affinity"),
        "number_from_other_pocket_set": other_value,
        "claim_from_other_pocket_set": substitute(other_report, "pockets[0].descriptors.volume_A3.value"),
        "claim_from_other_run": substitute(foreign_report, "pockets[0].descriptors.volume_A3.value"),
        "count_from_other_run": substitute(foreign_report, "total_count"),
        "dropped_claim": lambda forged: forged["claims"].pop(volume),
        "wrong_descriptor_copy": lambda forged: forged["pockets"][0]["descriptors"]["score"].update(value=99.0),
        "wrong_result_handle": lambda forged: forged.update(result_handle=other_set),
    }
    if other_rank is not None:
        tampering["wrong_rank"] = set_claim(volume, row_selector={"rank": other_rank})
        tampering["wrong_subject_rank"] = set_claim(volume, subject={**manifest["claims"][volume]["subject"],
                                                                      "rank": other_rank})
    for name, mutate in tampering.items():
        probe = copy.deepcopy(manifest)
        mutate(probe)
        if name not in {"dropped_claim", "wrong_descriptor_copy", "wrong_result_handle"}:
            changed = next(c for c in probe["claims"] if c not in manifest["claims"])
            try:
                validate_pocket_claim(run, handle, changed)
            except EvidenceError:
                pass
            else:
                raise AssertionError(f"{name}: claim accepted")
        forged = _forge(run, manifest, markdown, mutate)
        for response in (client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}),
                         client.get(f"/runs/{rid}/reports/download", params={"handle": forged, "format": "json"})):
            assert response.status_code == 422, name
            assert response.json()["detail"]["error"] == "report_evidence_invalid", name
            assert "markdown" not in response.json()["detail"]["message"], name
    # An exact copy of a genuine manifest with altered Markdown text is rejected too.
    forged_md = _forge(run, manifest, markdown.replace("Pocket candidates", "Binding sites", 1), lambda _m: None)
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged_md}).status_code == 422
    # The genuine reports are still byte-identical.
    assert _downloads(client, rid, created["handle"]) == (md_bytes, json_bytes)
    assert _downloads(client, rid, older) == older_bytes


def test_derived_first10_null_pocket_report(tmp_path, monkeypatch):
    client = _client(tmp_path / "runs", monkeypatch)
    rid = _new_run(client, "M12 pocket report derived first10 fixture")
    _, prepared = _prepared(client, rid, DERIVED_FIRST10.read_bytes(), "derived_1hsg_first10_fixture.cif")
    handle = _detect(client, rid, prepared)["artifacts"]["pocket_set"]
    run = api_module._run(rid)
    stored = run.store.load(handle)
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_claims_independently(run, manifest)
    if stored["total_count"] == 0:
        assert manifest["null_result"] is True and manifest["pockets"] == [] and manifest["total_count"] == 0
        count = next(claim for claim in manifest["claims"] if claim["statement_id"] == "pocket_count")
        assert count["exact_value"] == 0 and count["rendered_value"] == "0"
        assert not any(claim["row_selector"] for claim in manifest["claims"])
        assert "- Pocket candidates: 0 " in markdown and "scientific\\_null" in markdown
        assert "None (valid empty result)" in markdown
    else:  # pragma: no cover - preserved, not forced (see test_pocket_jobs)
        print(f"derived first10 fixture produced {stored['total_count']} pockets; preserved for investigation")
    assert "결합 부위·친화도·druggability 증거 아님" in markdown
    md_bytes, json_bytes = _downloads(client, rid, created["handle"])
    assert md_bytes == markdown.encode("utf-8") and json.loads(json_bytes) == manifest
    listed = client.get(f"/runs/{rid}/reports").json()
    assert [item["analysis_type"] for item in listed] == ["pocket_detection"]


def test_report_module_reads_only_stored_evidence():
    source = (Path(__file__).resolve().parents[1] / "mw" / "pocket_reports.py").read_text()
    for forbidden in ("subprocess", "pocket_worker", "requests", "httpx", "urllib", "socket"):
        assert forbidden not in source


def _derived_hie() -> bytes:
    """DERIVED fixture: public_1hsg.cif with chain A HIS 69 atom records renamed HIE (not an experiment)."""
    lines = []
    for line in HSG.read_text().splitlines(keepends=True):
        if line.startswith("ATOM") and " HIS A 1 69 " in line:
            line = line.replace(" HIS ", " HIE ")
        lines.append(line)
    return "".join(lines).encode()


def test_histidine_alias_mapping_is_reported_with_original_names(tmp_path, monkeypatch):
    client = _client(tmp_path / "runs", monkeypatch)
    rid = _new_run(client, "M12 pocket report histidine alias")
    _, prepared = _prepared(client, rid, _derived_hie(), "derived_1hsg_hie_fixture.cif")
    preflight = client.get(f"/runs/{rid}/pockets/preflight", params={"structure": prepared}).json()
    assert [item["original_resname"] for item in preflight["resname_mapping"]] == ["HIE"]
    handle = _detect(client, rid, prepared)["artifacts"]["pocket_set"]
    run = api_module._run(rid)
    detector = run.store.load(run.store.load(handle)["detector_input_handle"])
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["resname_mapping"] == detector["resname_mapping"] == preflight["resname_mapping"]
    mapping = manifest["resname_mapping"][0]
    assert mapping["residue"]["resname"] == "HIE" and mapping["transport_resname"] == "HIS"
    assert ("- Histidine name mapping: HIE auth A/69 label A/69 model 1 sent as HIS (original HIE)"
            in markdown)
    _verify_claims_independently(run, manifest)
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": created["handle"]}).json() == created
