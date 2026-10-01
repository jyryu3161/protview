"""M16 T3 reference site annotation report (``method_report_manifest@1``, ``analysis_type:
"reference_site_annotation"``, ``reference_site_annotation_markdown@1``).

Every annotation here is real product output through the HTTP command path (``/commands``) on the public 1MQ4
mmCIF (prepared structure, ADP 2001:A contacts) and a reference FIXTURE set (``reference_fixture_set``). SYNTHETIC
variants are named so (``_synthetic_*``) and say what they change. No report value is copied from the product:
per-site counts and minimum distances are recounted here from the stored contact rows by the 7 identity fields, and
distances are rendered with an independent ``Decimal`` oracle; T1 preflight minima (docs/qa/m16-annotations-20261001/
preflight.txt, numpy on the prepared coordinates) give the expected rendered text. Forged report manifests and
annotation objects below are labeled test fabrications written only to prove that the saved-report validator
rejects them.
"""
from __future__ import annotations

import copy
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import gemmi
import pytest
from reference_fixture_set import build_fixture_set
from test_reference_site_annotation import _map_row, _res, _synthetic_map

from mw import reference_snapshots as rs
from mw import site_annotation as sa
from mw import site_annotation_reports as sr
from mw.core.handles import canonical_json
from mw.reports import EvidenceError
from mw.tools.structural import structure_residues

FIX = Path(__file__).resolve().parent / "fixtures"
REF = FIX / "reference"
CIF_1MQ4 = FIX / "public_1mq4.cif"
ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
TYPES = ("contact", "polar_contact", "hydrophobic_contact")
KEY7 = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
# T1 preflight minima (numpy, cutoff 4.0, all types) -> the only correct 2-decimal ROUND_HALF_UP text.
PREFLIGHT_MIN_TEXT = {"III.17": "2.64", "GK.45": "3.91", "hinge.46": "2.70", "hinge.48": "3.17", "xDFG.81": "2.85"}
PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")


def _dist_oracle(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _key7(residue):
    return tuple((type(residue[k]), residue[k]) for k in KEY7)


@pytest.fixture
def refroot(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    return root


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    return TestClient(appmod.app, base_url="http://127.0.0.1")


def _run(rid):
    import mw.api.app as appmod
    return appmod._run(rid)


def _command(client, rid, tool, args) -> str:
    out = client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
    assert out.status_code == 200, out.text
    return out.json()["handle"]["handle"]


def _setup(client, *, source: Path = CIF_1MQ4, contacts: dict | None | bool = True) -> dict:
    """1MQ4 -> prepared -> map (prepared, 1MQ4:A) -> optional ADP contacts -> annotation."""
    rid = client.post("/runs", json={"goal": "site report"}).json()["run_id"]
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "1mq4.cif"}, content=source.read_bytes(),
                         headers={"content-type": "application/octet-stream"}).json()
    structure = _command(client, rid, "load_structure", {"source": upload["upload_id"]})
    prepared = _command(client, rid, "prepare_structure", {"structure": structure})
    numbering_map = _command(client, rid, "map_residue_numbering", {"structure": prepared, "pdb_id": "1MQ4",
                                                                     "chains": [{"chain_auth": "A"}]})
    contact_handle = None
    if contacts is not False:
        params = contacts if isinstance(contacts, dict) else {}
        contact_handle = _command(client, rid, "compute_interactions", {"structure": prepared, "ligand": ADP,
                                                                        **params})
    annotation = _command(client, rid, "annotate_reference_sites", {"numbering_map": numbering_map,
                                                                     "contacts": contact_handle})
    return {"rid": rid, "prepared": prepared, "map": numbering_map, "contacts": contact_handle,
            "annotation": annotation, "structure": structure}


def _report(client, rid, handle) -> dict:
    created = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert created.status_code == 201, created.text
    return created.json()


def _resolve(document, path):
    value = document
    for part in path.split("."):
        match = PATH_PART.fullmatch(part)
        assert match, path
        value = value[match.group(1)]
        if match.group(2) is not None:
            value = value[int(match.group(2))]
    return value


def _verify_independently(run, manifest) -> None:
    """Re-resolve every claim from the stored objects; recount contact rows; check evidence-kind separation."""
    annotation = run.store.load(manifest["result_handle"])
    map_handle = annotation["numbering_map"]
    stored_map = run.store.load(map_handle)
    contacts = annotation["contacts"]
    rows = run.store.load(contacts["handle"])["rows"] if contacts else None
    seen = set()
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["field_path"], json.dumps(claim["row_selector"], sort_keys=True))
        assert key not in seen
        seen.add(key)
        assert claim["source_sha256"] == claim["source_handle"].rsplit("/", 1)[-1]
        if claim["evidence_kind"] == "reference_value":
            assert claim["source_handle"] == map_handle and claim["source_kind"] == "residue_numbering_map"
            ref = claim["reference"]
            assert ref["note"] == "참조 스냅샷 값, 계산 아님"
            assert ref["set_hash"] == stored_map["snapshot_set"]["set_hash"] == annotation["snapshot_set_hash"]
            value = _resolve(stored_map, claim["field_path"])
            assert claim["exact_value"] == value
            continue
        assert claim["evidence_kind"] == "computed" and claim["reference"] is None
        sel = claim["row_selector"]
        if claim["statement_id"] == "site_contact_count":
            assert claim["source_handle"] == contacts["handle"] and claim["field_path"] == "rows.type"
            residue = claim["subject"]["residue"]
            expected = [i for i, r in enumerate(rows)
                        if _key7(r["residue"]) == _key7(residue) and r["type"] == sel["type"]]
            assert sel["type"] in contacts["types"]
            assert sel["row_indexes"] == expected and claim["exact_value"] == len(expected)
            assert claim["rendered_value"] == str(len(expected))
        elif claim["statement_id"] == "site_min_distance_A":
            residue = claim["subject"]["residue"]
            mine = [(i, r["distance_A"]) for i, r in enumerate(rows) if _key7(r["residue"]) == _key7(residue)]
            low = min(d for _, d in mine)
            index = min(i for i, d in mine if d == low)
            assert claim["field_path"] == f"rows[{index}].distance_A" and claim["exact_value"] == low
            assert claim["rendered_value"] == _dist_oracle(low) and claim["unit"] == "angstrom"
        else:
            assert claim["source_handle"] == manifest["result_handle"]
            sites = [s for g in annotation["groups"] for s in g["sites"]]
            if claim["statement_id"] == "site_status_count":
                expected = sum(s["status"] == sel["status"] for s in sites)
            else:
                assert claim["statement_id"] == "site_absent_reason_count"
                expected = sum(s["absent_reason"] == sel["absent_reason"] for s in sites)
            assert claim["exact_value"] == expected and claim["rendered_value"] == str(expected)


def _forge(run, manifest: dict, markdown: str, mutate) -> str:
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
                                        "analysis_type": "reference_site_annotation", "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"],
                          snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _claim(manifest, statement, label=None, type_=None):
    for claim in manifest["claims"]:
        if claim["statement_id"] != statement:
            continue
        if label is not None and claim["subject"].get("klifs_label") != label:
            continue
        if type_ is not None and claim["row_selector"].get("type") != type_:
            continue
        return claim
    raise AssertionError((statement, label, type_))


def _site_line(markdown, label):
    return next(line for line in markdown.splitlines() if line.startswith(f"| {sr._md(label)} |"))


# --- rendering and forbidden words ----------------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "text"), [
    (2.6428630308814687, "2.64"), (2.695699723633924, "2.70"), (2.675, "2.68"), (2.625, "2.63"), (3.0, "3.00"),
    (2.6949999, "2.69")])
def test_distance_rendering_is_decimal_half_up(value, text):
    assert sr.render_distance(value) == text == _dist_oracle(value)
    assert round(2.675, 2) == 2.67   # the float rounding the rule forbids


def test_forbidden_words_with_the_four_fixed_limitation_lines_exempt():
    assert tuple(sr.LIMITATIONS) == sa.LIMITATIONS
    # The fixed lines themselves contain 수소결합 / 결합; exactly equal lines pass.
    text = "\n".join(["# x", *sa.LIMITATIONS, "ok"])
    assert sr.check_no_interpretation(text) == text
    for bad in ("hinge 결합 잔기", "촉매 Lys", "수소결합 2개", "중요한 부위", "핵심 잔기", "기능 부위", "important site",
                "binding pocket", "affinity", "억제", "친화", "hydrogen bond", "Hydrogen-bonds to ADP", "H-bond",
                "two h-bonds", "HBOND", "hbond count", "hydrogenbond", "catalytic Lys", "CATALYTIC"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            sr.check_no_interpretation(f"ok\n{bad}")
    # A limitation line with anything added (a list marker, a trailing word) is checked like any other line.
    for near in (f"- {sa.LIMITATIONS[0]}", sa.LIMITATIONS[0] + " 결합", " " + sa.LIMITATIONS[0]):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            sr.check_no_interpretation(near)


# --- 1MQ4 report with contacts through the product path -------------------------------------------------------------

def test_1mq4_report_with_contacts_round_trips_and_every_value_is_bound(refroot, client):
    active = build_fixture_set(refroot)
    ids = _setup(client)
    rid = ids["rid"]
    run = _run(rid)
    # an existing report (M15) created before; its bytes must not change
    old = _report(client, rid, ids["map"])
    old_md = client.get(f"/runs/{rid}/reports/download", params={"handle": old["handle"]}).content
    old_js = client.get(f"/runs/{rid}/reports/download", params={"handle": old["handle"], "format": "json"}).content
    created = _report(client, rid, ids["annotation"])
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["analysis_type"] == "reference_site_annotation" and manifest["status"] == "complete"
    assert manifest["render_version"] == "reference_site_annotation_markdown@1"
    assert manifest["result_handle"] == ids["annotation"] and manifest["numbering_map"] == ids["map"]
    _verify_independently(run, manifest)
    annotation = run.store.load(ids["annotation"])
    assert manifest["groups"] == annotation["groups"] and manifest["contacts"] == annotation["contacts"]
    assert manifest["limitations"] == list(sa.LIMITATIONS)
    # snapshot: map set hash and provenance, active set at creation, not stale
    assert manifest["snapshot_set"]["set_hash"] == annotation["snapshot_set_hash"] == active
    assert manifest["snapshot"]["active_set_hash"] == active and manifest["snapshot"]["stale_snapshot"] is False
    # min distances: bound to the stored rows, rendered to the preflight text
    for label, text in PREFLIGHT_MIN_TEXT.items():
        claim = _claim(manifest, "site_min_distance_A", label)
        assert claim["rendered_value"] == text
        assert f"| {text} |" in _site_line(markdown, label)
    for label in ("αC.24", "hinge.47", "xDFG.80", "xDFG.82", "xDFG.83"):   # computed, no row -> 0 counts, no min
        line = _site_line(markdown, label)
        assert "| 0 | 0 | 0 |" in line and "없음 (null)" in line
        assert not [c for c in manifest["claims"] if c["statement_id"] == "site_min_distance_A"
                    and c["subject"]["klifs_label"] == label]
    assert "| 7 | 3 | 0 |" in _site_line(markdown, "III.17")   # contact / polar_contact / hydrophobic_contact
    assert "Glu211 \\(hinge\\.46\\)" in _site_line(markdown, "hinge.46")
    # reference values are marked as such and carry the set hash
    position = _claim(manifest, "reference_uniprot_position", "hinge.46")
    assert position["reference"]["set_hash"] == active and position["exact_value"] == run.store.load(
        ids["map"])["rows"][85]["uniprot_position"]
    # stated contact context
    assert "계산한 종류·cutoff 안의 최소" in markdown
    assert sr._md(sr._ref(annotation["contacts"]["ligand"])) in markdown
    assert "Cutoff: 4\\.0 Å" in markdown and "contact, hydrophobic\\_contact, polar\\_contact" in markdown
    assert "- 주석됨 (annotated): 10\n" in markdown and "- 없음 (absent): 0\n" in markdown
    for reason in sa.ABSENT_REASONS:   # zero counts are shown, never hidden
        assert f"({sr._md(reason)}): 0\n" in markdown
    for line in sa.LIMITATIONS:
        assert f"\n{line}\n" in markdown
    assert "수소결합" not in markdown.replace(sa.LIMITATIONS[0], "")
    # list / selected / download (read routes write no event)
    events_before = client.get(f"/runs/{rid}/events", params={"limit": 500}).json()
    listed = client.get(f"/runs/{rid}/reports").json()
    entry = next(item for item in listed if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "reference_site_annotation" and entry["result_handle"] == ids["annotation"]
    selected = client.get(f"/runs/{rid}/reports/selected", params={"handle": created["handle"]})
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "markdown"})
    js = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") == run.store.load(created["markdown_handle"])
    assert js.content == canonical_json(manifest) == canonical_json(run.store.load(created["handle"]))
    assert client.get(f"/runs/{rid}/events", params={"limit": 500}).json() == events_before
    # the older report stays byte-identical
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": old["handle"]}).content == old_md
    assert client.get(f"/runs/{rid}/reports/download",
                      params={"handle": old["handle"], "format": "json"}).content == old_js


def test_report_without_contacts(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client, contacts=False)
    run = _run(ids["rid"])
    created = _report(client, ids["rid"], ids["annotation"])
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(run, manifest)
    assert manifest["contacts"] is None and manifest["provenance"]["contacts"] is None
    assert not [c for c in manifest["claims"] if c["statement_id"] in {"site_contact_count", "site_min_distance_A"}]
    assert "접촉 결과 없음" in markdown
    for label in sr.sa.SITE_LABELS.values():
        cells = [cell.strip() for cell in _site_line(markdown, label).strip("|").split("|")]
        assert cells[-4:] == ["접촉 결과 없음"] * 4
    selected = client.get(f"/runs/{ids['rid']}/reports/selected", params={"handle": created["handle"]})
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown


def test_not_computed_type_is_never_zero(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client, contacts={"types": ["contact", "hydrophobic_contact"]})
    run = _run(ids["rid"])
    created = _report(client, ids["rid"], ids["annotation"])
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(run, manifest)
    assert not [c for c in manifest["claims"] if c["row_selector"].get("type") == "polar_contact"]
    line = _site_line(markdown, "hinge.47")
    assert "| 0 | 계산하지 않음 | 0 |" in line
    assert "polar\\_contact: 계산하지 않음" in markdown
    # a claim of 0 for the not-computed type is not an allowed claim
    count = _claim(manifest, "site_contact_count", "hinge.47", "contact")
    zero_polar = {**count, "row_selector": {**count["row_selector"], "type": "polar_contact"},
                  "quantity": "polar_contact_rows"}
    with pytest.raises(EvidenceError, match="field_not_allowed"):
        sr.validate_site_annotation_claim(run, ids["annotation"], zero_polar)
    # a saved report that shows 0 instead of "계산하지 않음" (claim added and Markdown edited) is refused
    forged = _forge(run, manifest, markdown.replace("| 0 | 계산하지 않음 | 0 |", "| 0 | 0 | 0 |"),
                    lambda f: f["claims"].append(zero_polar))
    assert client.get(f"/runs/{ids['rid']}/reports/selected", params={"handle": forged}).status_code == 422
    edited_md = _forge(run, manifest, markdown.replace("| 0 | 계산하지 않음 | 0 |", "| 0 | 0 | 0 |"), lambda f: None)
    assert client.get(f"/runs/{ids['rid']}/reports/selected", params={"handle": edited_md}).status_code == 422


def test_zero_row_contacts_show_zero_counts_and_no_distance(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client, contacts={"cutoff_A": 2.5, "types": ["polar_contact", "hydrophobic_contact"]})
    created = _report(client, ids["rid"], ids["annotation"])
    _verify_independently(_run(ids["rid"]), created["manifest"])
    markdown = created["markdown"]
    for label in sa.SITE_LABELS.values():
        line = _site_line(markdown, label)
        assert "| 계산하지 않음 | 0 | 0 | 없음 (null) |" in line
    assert "Cutoff: 2\\.5 Å" in markdown


def test_absent_sites_and_reasons_are_never_hidden(tmp_path, refroot, client):
    # SYNTHETIC: KLIFS kinases fixture without O14965 -> the group is not applied, all ten sites absent.
    rows = [json.loads(line) for line in (REF / "klifs/kinases_fixture.jsonl").read_bytes().splitlines() if line]
    data = b"".join(json.dumps(r, ensure_ascii=False).encode() + b"\n" for r in rows if r["uniprot"] != "O14965")
    build_fixture_set(refroot, replace={("klifs", "kinases.jsonl"): data})
    ids = _setup(client)
    created = _report(client, ids["rid"], ids["annotation"])
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(_run(ids["rid"]), manifest)
    assert manifest["null_result"] is True
    assert "- 없음 (absent): 10\n" in markdown and "(klifs\\_not\\_applied): 10\n" in markdown
    assert "not applied" in markdown and "accession\\_not\\_in\\_klifs" in markdown
    for label in sa.SITE_LABELS.values():
        assert "klifs\\_not\\_applied" in _site_line(markdown, label)
    assert "scientific\\_null" in markdown


def test_hetatm_site_is_not_assessed_without_numbers(tmp_path, refroot, client):
    # SYNTHETIC derived fixture: public 1MQ4 with GLU211 (hinge.46) written as HETATM MSE (names only).
    doc = gemmi.cif.read(str(CIF_1MQ4))
    table = doc.sole_block().find("_atom_site.", ["group_PDB", "auth_seq_id", "auth_asym_id", "label_comp_id",
                                                  "auth_comp_id"])
    for row in table:
        if row[1] == "211" and row[2] == "A":
            row[0], row[3], row[4] = "HETATM", "MSE", "MSE"
    path = tmp_path / "synthetic_1mq4_glu211_hetatm_mse_fixture.cif"
    doc.write_file(str(path))
    build_fixture_set(refroot)
    ids = _setup(client, source=path)
    created = _report(client, ids["rid"], ids["annotation"])
    _verify_independently(_run(ids["rid"]), created["manifest"])
    line = _site_line(created["markdown"], "hinge.46")
    assert line.count("접촉 도구가 검사하지 않는 잔기") == 4 and "MSE211" in line
    assert not [c for c in created["manifest"]["claims"] if c["subject"].get("klifs_label") == "hinge.46"
                and c["evidence_kind"] == "computed"]


def test_stale_and_missing_active_snapshot_are_recorded(tmp_path, refroot, client, monkeypatch):
    first = build_fixture_set(refroot)
    ids = _setup(client, contacts=False)
    later = build_fixture_set(refroot, tag="later")
    rs._VERIFIED.clear()
    assert later != first
    stale = _report(client, ids["rid"], ids["annotation"])
    assert stale["manifest"]["snapshot"]["active_set_hash"] == later
    assert stale["manifest"]["snapshot"]["stale_snapshot"] is True
    assert stale["manifest"]["snapshot_set"]["set_hash"] == first
    assert "yes" in next(line for line in stale["markdown"].splitlines() if line.startswith("Earlier snapshot"))
    empty = tmp_path / "no_reference"
    empty.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(empty))
    rs._VERIFIED.clear()
    none = _report(client, ids["rid"], ids["annotation"])
    assert none["manifest"]["snapshot"]["active_set_hash"] is None
    assert none["manifest"]["snapshot"]["stale_snapshot"] is True
    # reopening needs no reference folder
    for report in (stale, none):
        selected = client.get(f"/runs/{ids['rid']}/reports/selected", params={"handle": report["handle"]})
        assert selected.status_code == 200 and selected.json()["markdown"] == report["markdown"]
    forged = _forge(_run(ids["rid"]), none["manifest"], none["markdown"],
                    lambda f: f["snapshot"].update(stale_snapshot=False))
    assert client.get(f"/runs/{ids['rid']}/reports/selected", params={"handle": forged}).status_code == 422


# --- rejections -----------------------------------------------------------------------------------------------------

def test_reference_and_computed_evidence_never_mix(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client)
    rid, handle = ids["rid"], ids["annotation"]
    run = _run(rid)
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    position = _claim(manifest, "reference_uniprot_position", "hinge.46")
    klifs = _claim(manifest, "reference_klifs_index", "hinge.46")
    count = _claim(manifest, "site_contact_count", "hinge.46", "polar_contact")
    minimum = _claim(manifest, "site_min_distance_A", "hinge.46")
    for claim in (position, klifs, count, minimum):
        assert sr.validate_site_annotation_claim(run, handle, copy.deepcopy(claim)) == claim
    cases = {
        "evidence_kind_mismatch": {**position, "evidence_kind": "computed", "reference": None},
        "reference_field_as_computed": {**count, "field_path": klifs["field_path"]},
        "computed_field_as_reference": {**position, "field_path": minimum["field_path"]},
        "computed_field_rule": {**minimum, "reference": position["reference"]},
        "reference_field_rule": {**position, "reference": None},
        "statement_not_allowed": {**minimum, "statement_id": "hinge_hbond_strength"},
        "source_kind_mismatch": {**position, "source_kind": "interaction_set"},
    }
    for reason, claim in cases.items():
        with pytest.raises(EvidenceError, match=reason):
            sr.validate_site_annotation_claim(run, handle, claim)
    for reason, claim in cases.items():
        def mutate(forged, claim=claim):
            index = next(i for i, c in enumerate(forged["claims"]) if c == position)
            forged["claims"][index] = claim
        forged = _forge(run, manifest, markdown, mutate)
        assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}).status_code == 422, reason


def test_wrong_rounding_is_rejected(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client)
    rid, handle = ids["rid"], ids["annotation"]
    run = _run(rid)
    created = _report(client, rid, handle)
    minimum = _claim(created["manifest"], "site_min_distance_A", "hinge.46")
    assert minimum["rendered_value"] == "2.70" and minimum["rounding"] == "distance_2dp"
    for wrong in ("2.69", "2.7", "2.696", "2.6957", "3"):
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            sr.validate_site_annotation_claim(run, handle, {**minimum, "rendered_value": wrong})
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        sr.validate_site_annotation_claim(run, handle, {**minimum, "rounding": "verbatim",
                                                        "rendered_value": str(minimum["exact_value"])})
    forged = _forge(run, created["manifest"], created["markdown"].replace("| 2.70 |", "| 2.69 |"),
                    lambda f: next(c for c in f["claims"] if c == minimum).update(rendered_value="2.69"))
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}).status_code == 422
    # another row's distance under this site's claim
    other = _claim(created["manifest"], "site_min_distance_A", "hinge.48")
    with pytest.raises(EvidenceError):
        sr.validate_site_annotation_claim(run, handle, {**minimum, "exact_value": other["exact_value"],
                                                        "rendered_value": other["rendered_value"]})


def test_interpretive_statements_in_a_saved_report_are_rejected(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client)
    rid = ids["rid"]
    run = _run(rid)
    created = _report(client, rid, ids["annotation"])
    manifest, markdown = created["manifest"], created["markdown"]
    tampered = _forge(run, manifest, markdown.replace("## Limitations", "hinge.46은 촉매 부위다.\n\n## Limitations"),
                      lambda _f: None)
    extra = _forge(run, manifest, markdown, lambda f: f["limitations"].append("hinge 결합이 중요하다."))
    for forged in (tampered, extra):
        assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}).status_code == 422
    assert client.get(f"/runs/{rid}/reports").status_code == 422
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        sr.render_site_annotation_report({**manifest, "limitations": [*manifest["limitations"], "촉매 Lys 자리"]})


@pytest.mark.parametrize("mutate", [
    lambda c, rows: c["groups"][0]["sites"][0].update(status="partial"),
    lambda c, rows: c["groups"][0]["sites"][1].update(status="absent", absent_reason="made_up", residue=None,
                                                      map_row_index=None, residue_match=None, klifs_match=None,
                                                      display_label=None, contact=None),
    lambda c, rows: c["groups"][0].update(klifs_applied=False, klifs_absent_reason="made_up"),
    lambda c, rows: c["groups"][0]["sites"][0]["contact"]["by_type"]["contact"].update(count=8),
    lambda c, rows: c["groups"][0]["sites"][0]["contact"]["by_type"]["polar_contact"].update(computed=False,
                                                                                            count=None),
    lambda c, rows: c["groups"][0]["sites"][0]["contact"].update(min_distance_A=2.5),
    lambda c, rows: c["groups"][0]["sites"][0]["contact"].update(
        min_distance_row_index=c["groups"][0]["sites"][0]["contact"]["min_distance_row_index"] + 1),
    lambda c, rows: c["groups"][0]["sites"][4]["contact"]["by_type"]["contact"].update(count=None),
    lambda c, rows: c["groups"][0]["sites"][3]["contact"]["polar_pairs"].clear(),
    lambda c, rows: c["groups"][0]["sites"][3].update(display_label="Glu211 (catalytic)"),
    lambda c, rows: c["groups"][0]["sites"][3]["residue"].update(seq_label=None),
    lambda c, rows: c["other_contact_residues"].pop(),
    lambda c, rows: c.update(null_result=True),
    lambda c, rows: c["contacts"].update(cutoff_A=5.0),
], ids=["status", "absent_reason", "group_reason", "count", "computed_flag", "min_distance", "min_row",
        "zero_as_null", "polar_pairs", "display_label", "residue", "other_residues", "null_result", "cutoff"])
def test_annotation_validation_rejects_inconsistent_objects(refroot, client, mutate):
    build_fixture_set(refroot)
    ids = _setup(client)
    run = _run(ids["rid"])
    content = copy.deepcopy(run.store.load(ids["annotation"]))
    map_content = run.store.load(ids["map"])
    contacts = run.store.load(ids["contacts"])
    residues = structure_residues(run.store, map_content["structure"]["handle"])["residues"]
    sr.check_annotation(content, map_content, contacts, residues)   # the stored object passes
    mutate(content, contacts["rows"])
    with pytest.raises(EvidenceError):
        sr.check_annotation(content, map_content, contacts, residues)


def test_assessed_must_follow_the_structure_residue_category(refroot, client):
    # LABELED TEST FABRICATIONS of the stored 1MQ4 annotation (and of the residue list the validator reads).
    build_fixture_set(refroot)
    ids = _setup(client)
    run = _run(ids["rid"])
    stored = run.store.load(ids["annotation"])
    map_content = run.store.load(ids["map"])
    contacts = run.store.load(ids["contacts"])
    residues = structure_residues(run.store, map_content["structure"]["handle"])["residues"]
    # A polymer site residue without contact rows (αC.24) claimed as not assessed.
    content = copy.deepcopy(stored)
    site = next(s for s in content["groups"][0]["sites"] if s["klifs_label"] == "αC.24")
    assert site["contact"]["assessed"] is True and site["contact"]["min_distance_A"] is None
    site["contact"] = {"assessed": False, "not_assessed_reason": sa.NOT_ASSESSED_REASON,
                       "by_type": {t: {"computed": True, "count": None} for t in TYPES},
                       "min_distance_A": None, "min_distance_row_index": None, "polar_pairs": None}
    with pytest.raises(EvidenceError, match="site_contact_assessed_mismatch"):
        sr.check_annotation(content, map_content, contacts, residues)
    # The stored annotation says assessed, but the structure lists that residue as a non-polymer record.
    key = _key7(next(s for s in stored["groups"][0]["sites"] if s["klifs_label"] == "αC.24")["residue"])
    changed = [{**r, "category": "nonpolymer"} if _key7(r) == key else r for r in residues]
    assert changed != residues
    with pytest.raises(EvidenceError, match="site_contact_assessed_mismatch"):
        sr.check_annotation(stored, map_content, contacts, changed)
    # Contacts without the structure residues cannot be checked.
    with pytest.raises(EvidenceError, match="site_structure_residues_missing"):
        sr.check_annotation(stored, map_content, contacts, None)


@pytest.mark.parametrize(("label", "forged_reason"), [
    ("GK.45", "region_unresolved"),        # pocket_gap applies first (GK is also unresolved)
    ("GK.45", "no_mapped_residue"),
    ("xDFG.81", "no_mapped_residue"),      # region_unresolved applies first
    ("xDFG.81", "pocket_gap"),             # not a gap
    ("III.17", "pocket_gap"),              # no_mapped_residue is the only applicable reason
    ("III.17", "region_unresolved"),
])
def test_absent_reason_must_be_the_first_applicable_one(label, forged_reason):
    # SYNTHETIC map (same shape as test_reference_site_annotation's): site 45 is a gap in an unresolved region,
    # xDFG is unresolved, site 46 mapped, site 47 only a conflict row. The annotation is built by the product's pure
    # builder; the forged reason is a LABELED TEST FABRICATION.
    pocket = ["A"] * 85
    pocket[44] = "-"
    klifs = [{"accession": "P1", "applied": True, "absent_reason": None, "unresolved_regions": ["GK", "xDFG"],
              "gapped_regions": []}]
    rows = [_map_row(_res(211), 46), _map_row(_res(212), 47, status="conflict")]
    map_content = _synthetic_map(rows, klifs=klifs, pocket="".join(pocket))
    content = sa.build_annotation("obj://map/x", map_content, [], None, None)
    sr.check_annotation(content, map_content, None, None)
    site = next(s for s in content["groups"][0]["sites"] if s["klifs_label"] == label)
    assert site["status"] == "absent" and site["absent_reason"] != forged_reason
    site["absent_reason"] = forged_reason
    with pytest.raises(EvidenceError, match="site_status_or_reason_mismatch"):
        sr.check_annotation(content, map_content, None, None)


def test_unpublished_annotation_is_not_reported(refroot, client):
    build_fixture_set(refroot)
    ids = _setup(client)
    run = _run(ids["rid"])
    # LABELED TEST FABRICATION: an annotation object no tool call published (other residues reordered so the
    # object bytes differ from the published one).
    other = copy.deepcopy(run.store.load(ids["annotation"]))
    other["other_contact_residues"] = list(reversed(other["other_contact_residues"]))
    with run._owner():
        forged = run.store.put("reference_site_annotation", "reference_site_annotation@1", other,
                               produced_by="forged_test_annotation")
    response = client.post(f"/runs/{ids['rid']}/method_reports", json={"result_handle": forged.handle})
    assert response.status_code == 422 and "missing_successful_tool_provenance" in response.text
    assert client.post(f"/runs/{ids['rid']}/method_reports",
                       json={"result_handle": ids["prepared"]}).status_code == 422


def test_report_module_reads_only_stored_evidence():
    source = (Path(__file__).resolve().parents[1] / "mw" / "site_annotation_reports.py").read_text()
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "reference_snapshots", "numbering_reads",
                      "pin_active_set", "compute_interactions(", "build_annotation("):
        assert forbidden not in source
