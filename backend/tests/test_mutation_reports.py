"""M20 T5: ``mutation_candidates`` reports (spec 9, 11): field-cited counts, minimum ligand distance, protection check
states ("검사하지 않음" / "사용할 수 없음", never 0), reference values kept apart from computed values, the five fixed
limitation sentences, forbidden interpretive words, and reopen that reads stored objects only.

Sets are made by the product tool path (``load_structure`` -> ``prepare_structure`` -> ``generate_mutation_candidates``
through ``Run.call``) on the SYNTHETIC fixture in ``fixtures/mutation/`` and on the public 1MQ4 mmCIF (+ ADP, a
reference FIXTURE set from ``fixtures/reference`` for the M15 map and M16 annotation), as in ``test_mutation_api.py``.
The minimum-distance value is checked against the independent brute-force oracle ``fixtures/mutation/expected.json``
and an independent ``Decimal`` half-up rendering. Tampered reports and objects are LABELED TEST FABRICATIONS.
"""
from __future__ import annotations

import copy
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from reference_fixture_set import build_fixture_set

from mw import mutation_candidates as mc
from mw import mutation_constants as K
from mw import mutation_reports as mr
from mw import reference_snapshots as rs
from mw.api import app as api_module
from mw.reports import EvidenceError
from mw.workspace import new_run

FIX = Path(__file__).resolve().parent / "fixtures"
MUT = FIX / "mutation"
CIF = MUT / "synthetic-mutation-fixture.cif"
CIF_1MQ4 = FIX / "public_1mq4.cif"
ORACLE = json.loads((MUT / "expected.json").read_text())["files"]["synthetic-mutation-fixture.cif"]
RID, OTHER = "run_mutreports", "run_mutreports_other"


def res(chain_auth: str, seq_auth: int, resname: str, icode: str = "") -> dict:
    return {"model_number": 1, "chain_auth": chain_auth, "seq_auth": seq_auth, "icode": icode, "resname": resname}


def _args(structure, *, ligand_shell=None, residues=(), **kw):
    return {"structure": structure, "sources": {"pocket": None, "ligand_shell": ligand_shell,
                                                "residues": list(residues)}, **kw}


def _prepared(run, path: Path) -> str:
    loaded = run.call("load_structure", {"source": str(path), "model_index": 0}).handle
    return run.call("prepare_structure", {"structure": loaded}).handle


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("mutation_reports")
    root = base / "runs"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(rs.ENV_VAR, str(base / "reference"))
        (base / "reference").mkdir()
        build_fixture_set(base / "reference")
        run = new_run(root, run_id=RID, dry_run=False)
        syn = _prepared(run, CIF)
        made = {"syn": syn}
        made["shell"] = run.call(K.TOOL, _args(syn, ligand_shell={"radius_A": 5.0}, ligand=res("A", 101, "LIG"),
                                               residues=[res("A", 10, "ILE", "A"), res("A", 5, "CYS")],
                                               protected_residues=[res("A", 6, "HID")],
                                               released_residues=[res("A", 5, "CYS")])).handle
        made["plain"] = run.call(K.TOOL, _args(syn, residues=[res("A", 5, "CYS"), res("A", 2, "ALA")])).handle
        made["zero"] = run.call(K.TOOL, _args(syn, residues=[res("A", 2, "ALA"), res("A", 3, "SER")],
                                              allowed_residues="A")).handle
        mq = _prepared(run, CIF_1MQ4)
        numbering_map = run.call("map_residue_numbering", {"structure": mq, "pdb_id": "1MQ4",
                                                           "chains": [{"chain_auth": "A"}]}).handle
        annotation = run.call("annotate_reference_sites", {"numbering_map": numbering_map}).handle
        made.update(mq=run.call(K.TOOL, _args(mq, ligand_shell={"radius_A": 5.0}, ligand=res("A", 2001, "ADP"),
                                              numbering_map=numbering_map, annotation=annotation)).handle,
                    map=numbering_map, annotation=annotation)
        other = new_run(root, run_id=OTHER, dry_run=False)
        made["other"] = other.call(K.TOOL, _args(_prepared(other, CIF), residues=[res("A", 2, "ALA")])).handle
    return {"root": root, **made}


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _run(rid=RID):
    return api_module._run(rid)


def _report(client, handle, rid=RID) -> dict:
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert response.status_code == 201, response.text
    return response.json()


def _selected(client, handle, rid=RID):
    return client.get(f"/runs/{rid}/reports/selected", params={"handle": handle})


def _claim(manifest, statement, **selector):
    found = [c for c in manifest["claims"] if c["statement_id"] == statement and
             all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
    assert len(found) == 1, (statement, selector, len(found))
    return found[0]


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
                                        "analysis_type": mr.ANALYSIS_TYPE, "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _half_up(value: float) -> str:
    return str(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --- rendering and forbidden words -------------------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "text"), [(2.675, "2.68"), (2.625, "2.63"), (3.0, "3.00"), (2.6949999, "2.69"),
                                             (0.004, "0.00")])
def test_distance_rendering_is_decimal_half_up(value, text):
    assert mr.render_distance(value) == text
    assert round(2.675, 2) == 2.67   # the float rounding the rule forbids


def test_forbidden_words_with_the_five_fixed_limitation_lines_exempt():
    text = "\n".join(["# x", *K.LIMITATIONS, "ok", "촉매 잔기 데이터베이스 | 사용할 수 없음 (not_available)"])
    assert mr.check_no_interpretation(text) == text
    # The fixed sentences themselves contain 안정성·결합·활성 and 순위나 추천.
    assert any("활성" in line for line in K.LIMITATIONS) and any("추천" in line for line in K.LIMITATIONS)
    for bad in ("친화도 높음", "ΔΔG 예상", "ddG", "안정성 향상", "순위 1", "추천 후보", "최적 위치", "개선된 변이",
                "활성 부위", "예측 결과", "유망한 위치", "좋은 후보", "안전한 위치", "점수 3", "결합 잔기", "affinity",
                "stabilizing", "rank 1", "best", "recommended", "optimal", "improves", "predicted", "promising",
                "active site", "score", "energy", "hydrogen bond", "binding"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            mr.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {K.LIMITATIONS[1]}", K.LIMITATIONS[1] + " ", " " + K.LIMITATIONS[1]):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            mr.check_no_interpretation(near)


# --- valid reports through the API ------------------------------------------------------------------------------------

def test_report_with_ligand_counts_minimum_and_not_checked_klifs(client, world):
    handle = world["shell"]
    created = _report(client, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run().store.load(handle)
    positions, candidates = content["positions"], content["candidates"]
    assert (manifest["analysis_type"], manifest["render_version"], manifest["result_schema"]) == (
        "mutation_candidates", "mutation_candidates_markdown@1", "mutation_candidate_set@1")
    assert {c["source_handle"] for c in manifest["claims"]} == {handle}
    # counts recounted here from the stored rows (not from the stored counts)
    assert _claim(manifest, "position_count")["exact_value"] == len(positions)
    assert _claim(manifest, "candidate_count")["exact_value"] == len(candidates)
    for status in K.POSITION_STATUSES:
        assert _claim(manifest, "position_status_count", status=status)["exact_value"] == \
            sum(p["status"] == status for p in positions)
    assert _claim(manifest, "released_position_count")["exact_value"] == \
        sum(p["protection"]["released"] for p in positions) == 1
    for reason in K.EXCLUSION_REASONS:
        assert _claim(manifest, "exclusion_reason_count", exclusion_reason=reason)["exact_value"] == \
            sum(reason in p["exclusion_reasons"] for p in positions)
    for kind in K.SOURCE_KINDS:
        assert _claim(manifest, "source_position_count", source=kind)["exact_value"] == \
            sum(any(s["kind"] == kind for s in p["sources"]) for p in positions)
    assert _claim(manifest, "exclusion_reason_count", exclusion_reason="user_protected")["exact_value"] == 1
    # minimum distance against the independent brute-force oracle, rendered with an independent Decimal half-up
    oracle = {json.dumps(r["residue"], sort_keys=True): r["ligand_min_distance_A"]["LIG A101"]
              for r in ORACLE["polymer_residues"]}
    low = min(oracle[json.dumps(p["residue"], sort_keys=True)] for p in positions)
    minimum = _claim(manifest, "ligand_min_distance_A")
    assert minimum["exact_value"] == pytest.approx(low, abs=1e-9)
    assert minimum["rendered_value"] == _half_up(minimum["exact_value"]) and minimum["unit"] == "angstrom"
    assert f"{minimum['rendered_value']} Å" in markdown
    # KLIFS not checked: a status claim, no number; catalytic database unavailable, no number
    klifs = _claim(manifest, "protection_check_status", check="klifs_key_sites")
    assert klifs["exact_value"] == "not_checked" and klifs["rendered_value"] == "검사하지 않음 (not_checked)"
    catalytic = _claim(manifest, "protection_check_status", check="catalytic_residue_database")
    assert catalytic["rendered_value"] == "사용할 수 없음 (not_available)"
    counted = {c["field_path"] for c in manifest["claims"] if c["statement_id"] == "protection_check_count"}
    assert not any("klifs" in path or "catalytic" in path for path in counted)
    assert "protection_checks.metal_contact.metal_residues" in counted
    klifs_line = next(line for line in markdown.splitlines() if "(klifs\\_key\\_sites)" in line)
    assert "검사하지 않음" in klifs_line and not any(ch.isdigit() for ch in klifs_line)
    assert "사용할 수 없음 \\(not\\_available\\)" in markdown
    # no reference value without a map or annotation; no per-position table
    assert not [c for c in manifest["claims"] if c["evidence_kind"] == "reference_value"]
    assert all(c["evidence_kind"] == "computed" for c in manifest["claims"])
    assert "| index |" not in markdown and markdown.count("\n| ") <= len(K.PROTECTION_CHECK_KEYS) + 2
    for sentence in K.LIMITATIONS:
        assert f"\n{sentence}\n" in markdown
    # reopen, list and download read the same bytes
    assert _selected(client, created["handle"]).json()["markdown"] == markdown
    listed = {row["handle"]: row for row in client.get(f"/runs/{RID}/reports").json()}
    assert listed[created["handle"]]["analysis_type"] == "mutation_candidates"
    download = client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"]})
    assert download.status_code == 200 and download.content == markdown.encode()


def test_report_without_ligand_has_no_distance_claim(client, world):
    created = _report(client, world["plain"])
    assert not [c for c in created["manifest"]["claims"] if c["statement_id"] == "ligand_min_distance_A"]
    assert "- 계산하지 않음: 리간드를 주지 않아 위치별 거리가 없다." in created["markdown"]
    assert "Å (" not in created["markdown"]


def test_zero_candidate_report_is_a_valid_empty_result(client, world):
    created = _report(client, world["zero"])
    manifest = created["manifest"]
    assert manifest["null_result"] is True
    assert _claim(manifest, "candidate_count")["exact_value"] == 0
    assert _claim(manifest, "exclusion_reason_count", exclusion_reason="no_allowed_alternative")["exact_value"] == 1
    assert "유효한 빈 과학 결과" in created["markdown"]
    assert _selected(client, created["handle"]).status_code == 200


def test_1mq4_report_keeps_reference_values_apart(client, world):
    created = _report(client, world["mq"])
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run().store.load(world["mq"])
    references = [c for c in manifest["claims"] if c["evidence_kind"] == "reference_value"]
    accessions = {p["numbering"]["uniprot_accession"] for p in content["positions"]} - {None}
    labels = {label for p in content["positions"] for label in p["protection"]["klifs_sites"]}
    assert accessions and labels
    assert {c["exact_value"] for c in references if c["statement_id"] == "reference_uniprot_accession"} == accessions
    assert {c["exact_value"] for c in references if c["statement_id"] == "reference_klifs_site_label"} == labels
    assert all(c["reference"]["note"] == mr.REFERENCE_NOTE for c in references)
    klifs = _claim(manifest, "protection_check_status", check="klifs_key_sites")
    assert klifs["exact_value"] == "checked"
    annotated = next(c for c in manifest["claims"]
                     if c["field_path"] == "protection_checks.klifs_key_sites.annotated_sites")
    assert annotated["exact_value"] == content["protection_checks"]["klifs_key_sites"]["annotated_sites"]
    for status in K.NUMBERING_STATUSES:
        assert _claim(manifest, "numbering_status_count", numbering_status=status)["exact_value"] == \
            sum(p["numbering"]["status"] == status for p in content["positions"])
    assert mr.REFERENCE_NOTE in markdown
    assert _selected(client, created["handle"]).status_code == 200


# --- claim verification -------------------------------------------------------------------------------------------------

def test_wrong_counts_rounding_and_unchecked_claims_are_rejected(client, world):
    run = _run()
    handle = world["shell"]
    manifest = _report(client, handle)["manifest"]
    count = _claim(manifest, "position_count")
    minimum = _claim(manifest, "ligand_min_distance_A")
    klifs = _claim(manifest, "protection_check_status", check="klifs_key_sites")
    for claim in (count, minimum, klifs):
        assert mr.validate_mutation_claim(run, handle, copy.deepcopy(claim)) == claim
    wrong = {
        "binding_mismatch": [
            {**count, "exact_value": count["exact_value"] + 1, "rendered_value": str(count["exact_value"] + 1)},
            {**minimum, "rendered_value": mr.render_distance(minimum["exact_value"] + 0.01)},
            {**minimum, "rendered_value": f"{minimum['exact_value']:.1f}"},
            {**minimum, "rounding": "verbatim"},
            {**klifs, "exact_value": "checked", "rendered_value": "검사함 (checked)"},
        ],
        "field_not_allowed": [
            # a number for the KLIFS check that was not done (0 or otherwise)
            {**_claim(manifest, "protection_check_count", check="metal_contact"),
             "field_path": "protection_checks.klifs_key_sites.annotated_sites",
             "row_selector": {"check": "klifs_key_sites"}, "exact_value": 0, "rendered_value": "0"},
            # another position's distance as the minimum
            {**minimum, "field_path": "positions[0].ligand_min_distance_A"},
        ],
        "computed_field_rule": [{**count, "field_path": "positions[*].numbering.status"},
                                {**count, "reference": {"note": mr.REFERENCE_NOTE}}],
        "statement_not_allowed": [{**count, "statement_id": "position_rank"}],
        "source_kind_mismatch": [{**count, "source_kind": "prepared_structure"}],
        "source_mismatch": [{**count, "source_handle": world["plain"],
                             "source_sha256": world["plain"].rsplit("/", 1)[-1]}],
    }
    for reason, claims in wrong.items():
        for claim in claims:
            with pytest.raises(EvidenceError, match=reason):
                mr.validate_mutation_claim(run, handle, claim)


def test_reference_and_computed_evidence_never_mix(client, world):
    run = _run()
    handle = world["mq"]
    manifest = _report(client, handle)["manifest"]
    reference = next(c for c in manifest["claims"] if c["statement_id"] == "reference_uniprot_accession")
    count = _claim(manifest, "position_count")
    assert mr.validate_mutation_claim(run, handle, copy.deepcopy(reference)) == reference
    cases = {
        "evidence_kind_mismatch": {**reference, "evidence_kind": "computed", "reference": None},
        "reference_field_as_computed": {**count, "field_path": reference["field_path"]},
        "reference_field_rule": {**reference, "reference": None},
    }
    for reason, claim in cases.items():
        with pytest.raises(EvidenceError, match=reason):
            mr.validate_mutation_claim(run, handle, claim)
    with pytest.raises(EvidenceError, match="evidence_kind_mismatch"):
        mr.validate_mutation_claim(run, handle, {**count, "evidence_kind": "reference_value"})


def test_report_from_another_run_or_kind_is_refused(client, world):
    assert client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["other"]}).status_code == 422
    assert client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["syn"]}).status_code == 422


# --- reopen -------------------------------------------------------------------------------------------------------------

def test_tampered_reports_are_rejected_on_reopen(client, world):
    run = _run()
    created = _report(client, world["shell"])
    manifest, markdown = created["manifest"], created["markdown"]
    count = _claim(manifest, "position_count")

    def bump(forged):
        claim = next(c for c in forged["claims"] if c == count)
        claim.update(exact_value=count["exact_value"] + 1, rendered_value=str(count["exact_value"] + 1))

    forged = [
        _forge(run, manifest, markdown, bump),
        _forge(run, manifest, markdown.replace("## Limitations", "가장 유망한 위치다.\n\n## Limitations"),
               lambda _f: None),
        _forge(run, manifest, markdown, lambda f: f["limitations"].append("추천 목록이다.")),
        _forge(run, manifest, markdown, lambda f: f["counts"].update(candidates=0)),
        _forge(run, manifest, markdown, lambda f: f["claims"].pop()),
        _forge(run, manifest, markdown, lambda f: f["structure"].update(handle=world["mq"])),
        _forge(run, manifest, markdown.replace("검사하지 않음 \\(not\\_checked\\)", "검사함 \\(checked\\)"), lambda _f: None),
    ]
    for handle in forged:
        assert _selected(client, handle).status_code == 422
    assert client.get(f"/runs/{RID}/reports").status_code == 422


def test_reopen_reads_stored_objects_only(client, world, monkeypatch):
    created = _report(client, world["mq"])

    def boom(*_a, **_k):
        raise AssertionError("recomputed")

    monkeypatch.setattr(mc, "build_candidate_set", boom)
    monkeypatch.setattr(mc, "position_sources", boom)
    monkeypatch.setattr(mc, "normalize_request", boom)
    api_module.RUNS.clear()
    assert _selected(client, created["handle"]).json()["markdown"] == created["markdown"]


def test_stored_set_must_agree_with_the_objects_it_names(client, world):
    # LABELED TEST FABRICATIONS of the stored 1MQ4 set's copied reference values.
    run = _run()
    content = run.store.load(world["mq"])
    map_content, annotation = run.store.load(world["map"]), run.store.load(world["annotation"])
    mr.check_sources(content, map_content, annotation, None)
    edits = [
        lambda c: c["positions"][0]["numbering"].update(uniprot_accession="P00000"),
        lambda c: c["protection_checks"]["klifs_key_sites"].update(annotated_sites=0),
        lambda c: next(p for p in c["positions"] if p["protection"]["klifs_sites"])["protection"].update(
            klifs_sites=["made.up"]),
        lambda c: c["structure"].update(handle=world["syn"]),
    ]
    for edit in edits:
        forged = copy.deepcopy(content)
        edit(forged)
        with pytest.raises(EvidenceError):
            mr.check_sources(forged, map_content, annotation, None)
    with pytest.raises(EvidenceError, match="sources_missing"):
        mr.check_sources(content, None, annotation, None)


def test_tampered_stored_set_is_not_reported(client, world):
    # LABELED TEST FABRICATION: an altered copy of a stored set put without a tool call.
    run = _run()
    content = copy.deepcopy(run.store.load(world["plain"]))
    content["counts"]["candidates"] += 1
    with run._owner():
        bad = run.store.put(K.KIND, K.SCHEMA, content, produced_by="forged_test_set").handle
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": bad})
    assert response.status_code == 422 and "mutation_candidate_set_invalid" in response.text
    content = copy.deepcopy(run.store.load(world["plain"]))
    content["parameters"]["metal_contact_A"] = 3.5   # still a valid set, but no tool produced it
    content["protection_checks"]["metal_contact"]["threshold_A"] = 3.5
    with run._owner():
        orphan = run.store.put(K.KIND, K.SCHEMA, content, produced_by="forged_test_set").handle
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": orphan})
    assert response.status_code == 422 and "provenance" in response.text


def test_report_module_reads_only_stored_evidence():
    source = (Path(__file__).resolve().parents[1] / "mw" / "mutation_reports.py").read_text()
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "gemmi", "numpy", "build_candidate_set",
                      "position_sources", "normalize_request", "structure_residues", "_parse("):
        assert forbidden not in source
