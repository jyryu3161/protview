"""M20 T5: ``mutation_candidates`` reports (spec 9, 11): field-cited counts, minimum ligand distance, protection check
states ("검사하지 않음" / "사용할 수 없음", never 0), reference values kept apart from computed values, the five fixed
limitation sentences, forbidden interpretive words, and reopen that reads stored objects only.

Sets are made by the product tool path (``load_structure`` -> ``prepare_structure`` -> ``generate_mutation_candidates``
through ``Run.call``) on the SYNTHETIC fixture in ``fixtures/mutation/`` and on the public 1MQ4 mmCIF (+ ADP, a
reference FIXTURE set from ``fixtures/reference`` for the M15 map and M16 annotation), as in ``test_mutation_api.py``.
The minimum-distance value is checked against the independent brute-force oracle ``fixtures/mutation/expected.json``
and an independent ``Decimal`` half-up rendering. Tampered reports and objects are LABELED TEST FABRICATIONS.

M26 v2 (spec 8.5): every new set is v2, so a set without a catalytic annotation reports the catalytic check as
"검사하지 않음 (not_checked)" with no number. Sets with an annotation use ``reaction_knowledge@1`` results made by the
product tool over the LABELLED SYNTHETIC reaction reference set of ``m20_catalytic_fixture``. The v1 report bytes of
stored v1 sets are compared with the T1 baseline in ``test_mutation_api.py``.

M28 T3 (report format @2): reports citing reference values carry the snapshot source table; the stored @1 reports of
``fixtures/mutation_report_v1`` (recorded before T3, see its SYNTHETIC-PROVENANCE.md) reopen byte for byte.
"""
from __future__ import annotations

import copy
import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import m20_catalytic_fixture as CF
import pytest
from fastapi.testclient import TestClient
from reference_fixture_set import build_fixture_set

from mw import mutation_candidates as mc
from mw import mutation_constants as K
from mw import mutation_reports as mr
from mw import numbering_reports as nr
from mw import reaction_knowledge as rk
from mw import reaction_knowledge_constants as rkc
from mw import reaction_knowledge_reports as rkr
from mw import reference_snapshots as rs
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.reports import EvidenceError, _md
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
        CF.activate(base / "reaction_reference", patch)
        cat_residues = [res("A", 2, "ALA"), res("A", 6, "HID"), res("A", 10, "LEU"), res("A", 26, "ASP"),
                        res("B", 6, "HID")]
        made["knowledge"] = CF.link(run, syn, ["A", "B"])
        made["cat"] = run.call(K.TOOL, _args(syn, residues=cat_residues, released_residues=[res("A", 26, "ASP")],
                                             catalytic_annotation=made["knowledge"])).handle
        made["knowledge_cc"] = CF.link(run, syn, ["A", "B", "CC"])
        made["cat_partial"] = run.call(K.TOOL, _args(syn, residues=[*cat_residues, res("CC", 1, "HIE")],
                                                     catalytic_annotation=made["knowledge_cc"])).handle
        made["knowledge_none"] = CF.link(run, syn, ["A", "B"], pdb_id=CF.OTHER_PDB_ID)
        made["cat_none"] = run.call(K.TOOL, _args(syn, residues=cat_residues,
                                                  catalytic_annotation=made["knowledge_none"])).handle
        loaded_mq = run.call("load_structure", {"source": str(CIF_1MQ4), "model_index": 0}).handle
        made["knowledge_mq_raw"] = CF.link(run, loaded_mq, ["A"], pdb_id=CF.OTHER_PDB_ID)   # another structure
        # M28 T3: the numbering map alone, the annotation alone (its map is not given to M20)
        mq_residues = [res("A", 211, "GLU"), res("A", 230, "GLU")]
        made["mq_map"] = run.call(K.TOOL, _args(mq, residues=mq_residues, numbering_map=numbering_map)).handle
        made["mq_annotation"] = run.call(K.TOOL, _args(mq, residues=mq_residues, annotation=annotation)).handle
        CF.reset_caches()
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
    # M26 8.4: both v2 third-sentence variants are fixed sentences too (they say "이황화 결합")
    for variant in (K.LIMITATION_3_CHECKED, K.LIMITATION_3_NOT_CHECKED):
        assert variant in mr.FIXED_LIMITATIONS and "결합" in variant
        assert mr.check_no_interpretation(f"ok\n{variant}") == f"ok\n{variant}"
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            mr.check_no_interpretation(f"- {variant}")
    assert mr.FIXED_LIMITATIONS == frozenset(K.LIMITATIONS) | {K.LIMITATION_3_CHECKED, K.LIMITATION_3_NOT_CHECKED}
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
    # KLIFS not checked: a status claim, no number; the v2 catalytic check without an annotation: the same
    klifs = _claim(manifest, "protection_check_status", check="klifs_key_sites")
    assert klifs["exact_value"] == "not_checked" and klifs["rendered_value"] == "검사하지 않음 (not_checked)"
    catalytic = _claim(manifest, "protection_check_status", check="catalytic_residue_database")
    assert catalytic["rendered_value"] == "검사하지 않음 (not_checked)"
    counted = {c["field_path"] for c in manifest["claims"] if c["statement_id"] == "protection_check_count"}
    assert not any("klifs" in path or "catalytic" in path for path in counted)
    assert not [c for c in manifest["claims"] if c["statement_id"] == "catalytic_covered_chain_count"]
    assert "protection_checks.metal_contact.metal_residues" in counted
    klifs_line = next(line for line in markdown.splitlines() if "(klifs\\_key\\_sites)" in line)
    assert "검사하지 않음" in klifs_line and not any(ch.isdigit() for ch in klifs_line)
    catalytic_line = next(line for line in markdown.splitlines() if "(catalytic\\_residue\\_database)" in line)
    assert "검사하지 않음 \\(not\\_checked\\)" in catalytic_line and not any(ch.isdigit() for ch in catalytic_line)
    assert "사용할 수 없음" not in markdown and "- 촉매 잔기 주석: 주지 않음" in markdown
    # no annotation: the stored catalytic_residue count 0 counts nothing -> no claim, "—" with the reason, never 0
    assert content["counts"]["exclusion_reason_counts"]["catalytic_residue"] == 0
    assert not [c for c in manifest["claims"] if c["row_selector"] == {"exclusion_reason": "catalytic_residue"}]
    excluded = _line(markdown, "- M-CSA 촉매 잔기 주석 (catalytic\\_residue):")
    assert excluded == ("- M-CSA 촉매 잔기 주석 (catalytic\\_residue): — (촉매 잔기 검사 안 함: 주석을 주지 않음 "
                        "(annotation\\_not\\_given). M-CSA가 다룬 체인이 없어 이 사유의 위치를 세지 않았다)")
    assert not any(ch.isdigit() for ch in excluded)
    # no reference value without a map or annotation; no per-position table
    assert not [c for c in manifest["claims"] if c["evidence_kind"] == "reference_value"]
    assert all(c["evidence_kind"] == "computed" for c in manifest["claims"])
    assert "| index |" not in markdown and markdown.count("\n| ") <= len(K.PROTECTION_CHECK_KEYS) + 2
    assert manifest["limitations"] == list(K.LIMITATIONS_V2["not_checked"])
    for sentence in K.LIMITATIONS_V2["not_checked"]:
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


def test_identifiers_containing_forbidden_words_do_not_fail_a_report(tmp_path):
    """SYNTHETIC: chain "BEST" and ligand CCD-like code "SAFE" (identifiers, not claims) give a valid report; the
    forbidden-word check covers the fixed template text only."""
    import gemmi

    lines, serial = [], 1
    for seq in range(1, 4):
        for name, dx, dy, element in (("N", -1.2, 0.0, "N"), ("CA", 0.0, 0.0, "C"), ("C", 1.2, 0.0, "C"),
                                      ("O", 1.2, 1.2, "O"), ("CB", 0.0, -1.5, "C")):
            lines.append(f"ATOM  {serial:5d} {name:<4} ALA A{seq:4d}    {seq * 10.0 + dx:8.3f}{dy:8.3f}{0.0:8.3f}"
                         f"  1.00 20.00          {element:>2}")
            serial += 1
    lines.append(f"HETATM{serial:5d} C1   LIG A 501    {30.0:8.3f}{3.0:8.3f}{0.0:8.3f}  1.00 20.00           C")
    st = gemmi.read_pdb_string("\n".join(lines) + "\nEND\n")
    st.setup_entities()
    for chain in st[0]:
        chain.name = "BEST"
        for residue in chain:
            if residue.name == "LIG":
                residue.name = "SAFE"
    path = tmp_path / "synthetic_best_chain.cif"
    path.write_text(st.make_mmcif_document().as_string())
    run = new_run(tmp_path / "runs", run_id="run_mutreports_ident", dry_run=False)
    prepared = _prepared(run, path)
    ligand = {"model_number": 1, "chain_auth": "BEST", "seq_auth": 501, "icode": "", "resname": "SAFE"}
    made = run.call(K.TOOL, _args(prepared, ligand_shell={"radius_A": 5.0}, ligand=ligand,
                                  residues=[res("BEST", 1, "ALA")])).handle
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        mr.check_no_interpretation("- 리간드: BEST/SAFE")   # the same words as template text are still refused
    created = mr.build_mutation_report(run, made)
    assert "BEST" in created["markdown"] and "SAFE" in created["markdown"]
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        mr.check_no_interpretation(created["markdown"])   # a whole-line check would have refused this report
    assert mr.saved_mutation_report(run, created["handle"])["markdown"] == created["markdown"]


# --- M26 v2: the catalytic part (spec 8.5) ------------------------------------------------------------------------------

def _line(markdown, marker):
    return next(line for line in markdown.splitlines() if marker in line)


def test_checked_catalytic_report_counts_and_mcsa_reference_values(client, world):
    handle = world["cat"]
    created = _report(client, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run().store.load(handle)
    check = content["protection_checks"]["catalytic_residue_database"]
    assert check["status"] == "checked" and manifest["evidence_statement"] == mr.EVIDENCE_STATEMENT_V2
    assert _claim(manifest, "protection_check_status", check="catalytic_residue_database")["rendered_value"] == \
        "검사함 (checked)"
    chains = _claim(manifest, "catalytic_covered_chain_count")
    assert chains["exact_value"] == len(check["covered_chains"]) == 2 and chains["evidence_kind"] == "computed"
    for field, value in (("matched_rows", 9), ("conflict_rows", 2), ("unmatched_rows", 4)):
        claim = next(c for c in manifest["claims"]
                     if c["field_path"] == f"protection_checks.catalytic_residue_database.{field}")
        assert claim["exact_value"] == check[field] == value and claim["statement_id"] == "protection_check_count"
    assert _claim(manifest, "exclusion_reason_count", exclusion_reason="catalytic_residue")["exact_value"] == \
        sum("catalytic_residue" in p["exclusion_reasons"] for p in content["positions"]) == 3   # A2 A6 B6
    ids = [c for c in manifest["claims"] if c["statement_id"] == "reference_mcsa_entry_id"]
    assert all(c["evidence_kind"] == "reference_value" and c["reference"] == {
        "note": mr.REFERENCE_NOTE, "reference_object": world["knowledge"]} for c in ids)
    expected = {(e["mcsa_id"], p["protection"]["released"]) for p in content["positions"]
                for e in p["protection"]["catalytic"] or []}
    assert {(c["exact_value"], c["subject"]["released"]) for c in ids} == expected == {
        (601, False), (602, False), (601, True)}                     # ASP A26 (601/1) is released
    line = _line(markdown, "(catalytic\\_residue\\_database)")
    assert "검사함 \\(checked\\)" in line and "검사한 체인 2" in line and "대응됨 행 9" in line
    assert "충돌 행 2" in line and "대응 없음 행 4" in line
    assert "- M-CSA가 다룬 체인 위치에서 대응된 M-CSA 항목 ID" in markdown and "601, 602" in markdown
    assert "- 보호를 해제한 위치의 M-CSA 항목 ID (해제됨, 참조 스냅샷 값, 계산 아님): 601" in markdown
    assert _line(markdown, "- M-CSA 촉매 잔기 주석 (catalytic\\_residue):").endswith(": 3")   # checked: no note
    assert manifest["limitations"][2] == K.LIMITATION_3_CHECKED and f"\n{K.LIMITATION_3_CHECKED}\n" in markdown
    assert _selected(client, created["handle"]).json()["markdown"] == markdown
    assert mr.validate_mutation_claim(_run(), handle, copy.deepcopy(chains)) == chains


@pytest.mark.parametrize("name", ["cat_partial", "cat_none"])
def test_not_checked_catalytic_report_has_a_status_claim_and_no_number(client, world, name):
    created = _report(client, world[name])
    manifest, markdown = created["manifest"], created["markdown"]
    check = _run().store.load(world[name])["protection_checks"]["catalytic_residue_database"]
    assert (check["status"], check["reason"]) == ("not_checked", "chains_not_covered")
    assert _claim(manifest, "protection_check_status", check="catalytic_residue_database")["rendered_value"] == \
        "검사하지 않음 (not_checked)"
    catalytic_paths = [c["field_path"] for c in manifest["claims"] if "catalytic_residue_database" in c["field_path"]]
    assert catalytic_paths == ["protection_checks.catalytic_residue_database.status"]   # the status claim only
    line = _line(markdown, "(catalytic\\_residue\\_database)")
    assert "검사하지 않음 \\(not\\_checked\\)" in line and "chains\\_not\\_covered" in line
    knowledge = world["knowledge_cc" if name == "cat_partial" else "knowledge_none"]
    assert not any(ch.isdigit() for ch in line.replace(knowledge.rsplit("/", 1)[-1], ""))   # no number but the hash
    if name == "cat_partial":
        assert "CC (체인이 M-CSA 행에 없음, chain\\_not\\_listed)" in line and "M-CSA가 다룬 체인: A, B" in line
        assert [c["exact_value"] for c in manifest["claims"] if c["statement_id"] == "reference_mcsa_entry_id"] == \
            [601, 602]
    else:
        assert "pdb\\_not\\_in\\_snapshot" in line and "M-CSA가 다룬 체인" not in line
        assert "- 보호된 위치의 M-CSA 항목 ID: 검사하지 않음" in markdown and "none" not in _line(markdown, "M-CSA 항목 ID")
        assert not [c for c in manifest["claims"] if c["statement_id"] == "reference_mcsa_entry_id"]
    assert manifest["limitations"][2] == K.LIMITATION_3_NOT_CHECKED
    excluded = _line(markdown, "- M-CSA 촉매 잔기 주석 (catalytic\\_residue):")
    assert "촉매 잔기 검사 안 함" in excluded
    content = _run().store.load(world[name])
    reason_claims = [c for c in manifest["claims"] if c["row_selector"] == {"exclusion_reason": "catalytic_residue"}]
    if name == "cat_partial":   # A and B covered: the count of those chains, with the note
        counted = sum("catalytic_residue" in p["exclusion_reasons"] for p in content["positions"])
        assert [c["exact_value"] for c in reason_claims] == [counted] and counted > 0
        assert excluded.endswith(f": {counted} — 촉매 잔기 검사 안 함(검사하지 않은 위치는 세지 않았다)")
    else:                       # no chain covered: the stored 0 is no count -> no claim, "—" with the reason
        assert content["counts"]["exclusion_reason_counts"]["catalytic_residue"] == 0 and reason_claims == []
        assert excluded == ("- M-CSA 촉매 잔기 주석 (catalytic\\_residue): — (촉매 잔기 검사 안 함: 위치가 있는 체인을 M-CSA "
                            "주석이 모두 다루지는 않음 (chains\\_not\\_covered). M-CSA가 다룬 체인이 없어 이 사유의 위치를 세지 "
                            "않았다)")
        assert not any(ch.isdigit() for ch in excluded)
        # a proposed 0 for it is refused (no such claim exists)
        zero = {**_claim(manifest, "exclusion_reason_count", exclusion_reason="no_allowed_alternative"),
                "row_selector": {"exclusion_reason": "catalytic_residue"}, "quantity": "catalytic_residue_positions",
                "exact_value": 0, "rendered_value": "0",
                "operation": "count_where(catalytic_residue in exclusion_reasons; stored rows)"}
        with pytest.raises(EvidenceError, match="field_not_allowed"):
            mr.validate_mutation_claim(_run(), world[name], zero)
    assert _selected(client, created["handle"]).status_code == 200
    assert _selected(client, created["handle"]).json()["markdown"] == markdown


def test_catalytic_values_must_agree_with_the_reaction_result(client, world):
    # LABELED TEST FABRICATIONS of the stored v2 set's catalytic values, checked against the stored result.
    run = _run()
    content = run.store.load(world["cat"])
    result = run.store.load(world["knowledge"])
    mr.check_sources(content, None, None, None, result)
    edits = {
        "covered_chains": lambda c: c["protection_checks"]["catalytic_residue_database"]["covered_chains"].pop(),
        "row_count": lambda c: c["protection_checks"]["catalytic_residue_database"].update(matched_rows=8),
        "conflicts": lambda c: c["protection_checks"]["catalytic_residue_database"]["conflicts"].pop(),
        "protection": lambda c: c["positions"][1]["protection"].update(catalytic=[]),
        "entry": lambda c: c["positions"][1]["protection"]["catalytic"][0].update(is_reference=False),
    }
    for edit in edits.values():
        forged = copy.deepcopy(content)
        edit(forged)
        with pytest.raises(EvidenceError, match="catalytic_value_mismatch"):
            mr.check_sources(forged, None, None, None, result)
    with pytest.raises(EvidenceError, match="catalytic_value_mismatch"):        # another (valid) result
        mr.check_sources(content, None, None, None, run.store.load(world["knowledge_none"]))
    with pytest.raises(EvidenceError, match="catalytic_annotation_structure_mismatch"):
        mr.check_sources(content, None, None, None, run.store.load(world["knowledge_mq_raw"]))
    broken = copy.deepcopy(result)
    broken["counts"]["chains"] = 3
    with pytest.raises(EvidenceError, match="catalytic_annotation_invalid"):
        mr.check_sources(content, None, None, None, broken)
    with pytest.raises(EvidenceError, match="sources_missing"):
        mr.check_sources(content, None, None, None, None)
    v1 = json.loads((FIX / "sequence_ga" / "m20-candidate-set-1ubq-8pos.json").read_text())["content"]
    mr.check_sources(v1, None, None, None)                                       # v1: no catalytic source
    with pytest.raises(EvidenceError, match="sources_missing"):
        mr.check_sources(v1, None, None, None, result)


def test_a_v2_set_valid_on_its_own_but_not_matching_its_result_is_refused(client, world):
    # LABELED TEST FABRICATION: one M-CSA entry of HID A6 dropped. validated_set alone cannot see it (the set stays
    # internally consistent); only the comparison with the stored reaction_knowledge@1 result refuses it.
    run = _run()
    content = copy.deepcopy(run.store.load(world["cat"]))
    hid = content["positions"][1]
    assert (hid["residue"]["seq_auth"], len(hid["protection"]["catalytic"])) == (6, 2)
    hid["protection"]["catalytic"].pop()
    mc.validated_set(content)
    with pytest.raises(EvidenceError, match="catalytic_value_mismatch"):
        mr.check_sources(content, None, None, None, run.store.load(world["knowledge"]))


def test_reopen_re_validates_the_reaction_result(client, world, monkeypatch):
    created = _report(client, world["cat"])
    assert _selected(client, created["handle"]).status_code == 200
    calls = []
    real = rk.validated_result

    def counted(obj):
        calls.append(obj["schema"])
        return real(obj)

    monkeypatch.setattr(rk, "validated_result", counted)
    api_module.RUNS.clear()
    assert _selected(client, created["handle"]).status_code == 200 and calls == ["reaction_knowledge@1"]

    def refuse(obj):
        raise rk.ResultInvalid("LABELED TEST FABRICATION: the stored result no longer validates")

    monkeypatch.setattr(rk, "validated_result", refuse)
    api_module.RUNS.clear()
    response = _selected(client, created["handle"])
    assert response.status_code == 422 and "catalytic_annotation_invalid" in response.text
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["cat"]})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"


def test_v2_report_template_has_no_interpretive_wording(client, world):
    for name in ("cat", "cat_partial", "cat_none", "shell"):
        markdown = _report(client, world[name])["markdown"]
        lines = [line for line in markdown.splitlines() if line not in mr.FIXED_LIMITATIONS]
        for word in ("점수", "순위", "추천", "활성", "중요", "핵심", "필수", "안정성", "효과"):
            assert not any(word in line for line in lines), (name, word)


# --- M28 T3: report format @2 with the reference snapshot source table (spec M28 10.2) -------------------------------------

V2 = "mutation_candidates_markdown@2"
V1_LOG = FIX / "mutation_report_v1" / "v1-cited-reports.events.jsonl"
V1_LOG_SHA256 = "7a2e0c6d2e1ec8a8bbe20e4ae9d6d67204c6e66a5a128393869f7e4c80e403a7"
V1_RID = "run_m28_t3_v1_cited"
V1_MAP = (f"obj://{V1_RID}/residue_numbering_map/"
          "bb5d86569f389ebe3ba756bbd76f762c8f5cc1e97066924468fc5903de513bf7")
V1_ANNOTATION = (f"obj://{V1_RID}/reference_site_annotation/"
                 "65a91e592cba7a1439ac2b8b1d5c99266fe28f04e9b8660d4b35d3c624b9f0df")
V1_KNOWLEDGE = (f"obj://{V1_RID}/reaction_knowledge/"
                "1597204750c1f57920c70e9d0ebf29fdb2b038da044c20881287618d5b945f69")
V1_SETS = {   # name -> stored set handle in the frozen log
    "map_annotation": f"obj://{V1_RID}/mutation_candidate_set/"
                      "bcc72be44d833ac5e17c7e28bbe3d3b1897ca4c14744773fbf35788f4e86ba62",
    "catalytic": f"obj://{V1_RID}/mutation_candidate_set/"
                 "20008e224db662ce59fbf89c85ba9806c25f33773214f639fa23ffe8218b9886",
    "plain": f"obj://{V1_RID}/mutation_candidate_set/c502d948fdef30ccc0a2bbe3d24d3f8b653ee86a1981182de141ff5a680ed60d",
}
V1_REPORTS = {   # name -> (stored @1 report handle, Markdown SHA-256, canonical manifest SHA-256), recorded before T3
    "map_annotation": ((f"obj://{V1_RID}/method_report_manifest/"
                        "dabea001401460367a40726bcf1bed4c1a80a9273181274e461c174d26820b23"),
                       "a2ddcba8ef9f30a32525d85b47194f6536f38924ba5841ad8761c28881908a1d",
                       "a5f71cb5983d2eb1fdc5886702313463ee600db0996b936f47b8ba1ae2a03f86"),
    "catalytic": ((f"obj://{V1_RID}/method_report_manifest/"
                   "f68061e6898316b9df11b6fbcbe35be65814932f6995bf236cd2c36fa4ca4330"),
                  "55cadf549ace58bc477ba8d9babcd8db2376149101f42ba8eaf1c4b77c6cda75",
                  "527577aa2d11825ffdd6fe92de49da911614147f41259e6ce0d9b87296af0c81"),
}
M15_HEADER = "| 출처 | 버전 | 날짜 | 스냅샷 ID | 라이선스 | 가공 |"
M26_HEADER = "| 출처 | 날짜 | 세트 해시 | 가공 행 수 | 라이선스 | 가공 |"
M20_REACTION_HEADER = "| 출처 | 날짜 | 세트 해시 | 라이선스 | 가공 |"


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """The committed run log with two stored @1 reports that cite reference values (``fixtures/mutation_report_v1``,
    recorded with the report code before T3), reopened events-only in a fresh root."""
    raw = V1_LOG.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V1_LOG_SHA256
    root = tmp_path / "runs"
    (root / V1_RID).mkdir(parents=True)
    (root / V1_RID / "events.jsonl").write_bytes(raw)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _table(markdown: str, header: str) -> list[str]:
    lines = markdown.splitlines()
    start = lines.index(header)
    rows = []
    for line in lines[start:]:
        if not line.startswith("| "):
            break
        rows.append(line)
    return rows


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.split(" | ")]


def test_stored_v1_reports_citing_reference_values_reopen_with_the_same_bytes(frozen, monkeypatch):
    run = api_module._run(V1_RID)

    def boom(*_a, **_k):
        raise AssertionError("an @1 report is reopened with the @1 rules only")

    monkeypatch.setattr(nr, "validated_numbering_map", boom)   # the @2 table path is never taken for @1
    for name, (handle, markdown_sha, manifest_sha) in V1_REPORTS.items():
        stored = run.store.load(handle)
        markdown = run.store.load(stored["markdown_handle"])
        assert hashlib.sha256(markdown).hexdigest() == markdown_sha, name
        assert hashlib.sha256(canonical_json(stored)).hexdigest() == manifest_sha, name
        assert stored["render_version"] == mr.RENDER_VERSION and set(stored) == mr.MANIFEST_KEYS
        assert [c for c in stored["claims"] if c["evidence_kind"] == "reference_value"], name   # it cites
        assert stored["result_handle"] == V1_SETS[name]
        response = _selected(frozen, handle, V1_RID)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["markdown"].encode() == markdown
        assert canonical_json(body["manifest"]) == canonical_json(stored)
        assert "## 참조 스냅샷" not in body["markdown"]
        download = frozen.get(f"/runs/{V1_RID}/reports/download", params={"handle": handle})
        assert download.status_code == 200 and download.content == markdown
    listed = frozen.get(f"/runs/{V1_RID}/reports")
    assert listed.status_code == 200
    assert {row["handle"] for row in listed.json()} == {item[0] for item in V1_REPORTS.values()}


def test_both_report_versions_coexist_in_one_run(frozen):
    made = {name: _report(frozen, handle, V1_RID) for name, handle in V1_SETS.items()}
    for name in ("map_annotation", "catalytic"):   # citing reference values: @2 with the table
        manifest = made[name]["manifest"]
        assert manifest["render_version"] == V2 and set(manifest) == mr.MANIFEST_KEYS_V2, name
        assert "\n## 참조 스냅샷\n" in made[name]["markdown"]
    plain = made["plain"]   # nothing cited: @1, no table, never "none" or 0 for it
    assert plain["manifest"]["render_version"] == mr.RENDER_VERSION and set(plain["manifest"]) == mr.MANIFEST_KEYS
    assert "참조 스냅샷\n" not in plain["markdown"] and "reference_snapshot_sets" not in plain["manifest"]
    handles = [item[0] for item in V1_REPORTS.values()] + [created["handle"] for created in made.values()]
    versions = []
    for handle in handles:
        response = _selected(frozen, handle, V1_RID)
        assert response.status_code == 200, response.text
        versions.append(response.json()["manifest"]["render_version"])
    assert versions == [mr.RENDER_VERSION, mr.RENDER_VERSION, V2, V2, mr.RENDER_VERSION]
    listed = frozen.get(f"/runs/{V1_RID}/reports")
    assert listed.status_code == 200 and {row["handle"] for row in listed.json()} == set(handles)


def test_v2_numbering_table_is_the_cited_map_set_in_the_m15_wording(frozen):
    run = api_module._run(V1_RID)
    created = _report(frozen, V1_SETS["map_annotation"], V1_RID)
    manifest, markdown = created["manifest"], created["markdown"]
    map_content, annotation = run.store.load(V1_MAP), run.store.load(V1_ANNOTATION)
    (entry,) = manifest["reference_snapshot_sets"]
    snapshot_set = map_content["snapshot_set"]
    assert entry["snapshot_set"] == snapshot_set and snapshot_set["set_hash"] == annotation["snapshot_set_hash"]
    set_handle = entry["reference_set_handle"]
    assert run.store.meta(set_handle)["kind"] == "reference_snapshot_set"
    assert hashlib.sha256(canonical_json(run.store.load(set_handle))).hexdigest() == snapshot_set["set_hash"]
    assert entry == {"set_schema": "reference_snapshot_set@1", "copied_from": V1_MAP, "reference_set_handle": set_handle,
                     "snapshot_set": snapshot_set, "klifs_terms": nr.KLIFS_TERMS}
    # the M15 report of the same map: the source table rows and the Origin line appear verbatim
    m15 = _report(frozen, V1_MAP, V1_RID)["markdown"]
    rows = _table(markdown, M15_HEADER)
    assert rows == _table(m15, M15_HEADER) and len(rows) == 2 + len(snapshot_set["sources"]) == 5
    klifs = next(row for row in rows if row.startswith("| KLIFS |"))
    assert _cells(klifs)[4] == _md(nr.KLIFS_TERMS)                       # "이용 조건 명시 없음(none-stated)"
    origin = next(line for line in m15.splitlines() if line.startswith("- Origin: "))
    assert origin in markdown.splitlines()
    m15_set = next(line for line in m15.splitlines() if line.startswith("Reference snapshot set: "))
    line = f"Reference snapshot set of the numbering map: {m15_set.removeprefix('Reference snapshot set: ')}"
    assert line in markdown.splitlines() and f"Numbering map: {_md(V1_MAP)}" in markdown.splitlines()
    assert snapshot_set["set_hash"] in markdown
    assert "가공 행 수" not in markdown and "Active reference set" not in markdown   # no row count, no active-set line
    assert _selected(frozen, created["handle"], V1_RID).json()["markdown"] == markdown


def test_v2_reaction_table_is_the_cited_result_set_in_the_m26_wording(frozen):
    run = api_module._run(V1_RID)
    created = _report(frozen, V1_SETS["catalytic"], V1_RID)
    manifest, markdown = created["manifest"], created["markdown"]
    result = run.store.load(V1_KNOWLEDGE)
    assert [c["exact_value"] for c in manifest["claims"] if c["statement_id"] == "reference_mcsa_entry_id"]
    (entry,) = manifest["reference_snapshot_sets"]
    assert entry == {"set_schema": rkc.SET_SCHEMA, "copied_from": V1_KNOWLEDGE, "snapshot_set": result["snapshot_set"]}
    m26 = _report(frozen, V1_KNOWLEDGE, V1_RID)["markdown"]
    assert rkc.STATEMENTS["RK6"] in markdown.splitlines()
    imported = next(line for line in m26.splitlines() if line.startswith("- 가져온 시각: "))
    assert imported in markdown.splitlines()
    m26_rows = _table(m26, M26_HEADER)
    ours = _table(markdown, M20_REACTION_HEADER)
    # the M26 rows without the processed-row-count column (one file per source)
    assert [_cells(row)[:3] + _cells(row)[4:] for row in m26_rows[2:]] == [_cells(row) for row in ours[2:]]
    assert len(ours) == 2 + len(result["snapshot_set"]["sources"]) == 5
    assert all(result["snapshot_set"]["set_hash"] in row for row in ours[2:])
    assert f"| {rkr.LICENSE_LABEL} (" in ours[2] and ours[2].endswith(f"| {rkr.PROCESSED_LABEL} |")
    assert "가공 행 수" not in markdown and "사용 중이던" not in markdown   # no row count, no active-set line
    assert "### 번호 대응" not in markdown                                # no numbering map or annotation cited
    assert _selected(frozen, created["handle"], V1_RID).json()["markdown"] == markdown


@pytest.mark.parametrize(("name", "families"), [
    ("mq", ["reference_snapshot_set@1"]), ("mq_map", ["reference_snapshot_set@1"]),
    ("mq_annotation", ["reference_snapshot_set@1"]), ("cat", [rkc.SET_SCHEMA]), ("cat_partial", [rkc.SET_SCHEMA]),
    ("cat_none", []), ("shell", []), ("plain", []), ("zero", [])])
def test_report_version_follows_the_cited_reference_values(client, world, name, families):
    created = _report(client, world[name])
    manifest, markdown = created["manifest"], created["markdown"]
    run = _run()
    content = run.store.load(world[name])
    references = [c for c in manifest["claims"] if c["evidence_kind"] == "reference_value"]
    if not families:
        # cat_none names a reaction result but cites no M-CSA ID (no chain covered): no table, the @1 bytes
        assert manifest["render_version"] == mr.RENDER_VERSION and set(manifest) == mr.MANIFEST_KEYS
        assert not references and "## 참조 스냅샷" not in markdown
    else:
        assert manifest["render_version"] == V2 and set(manifest) == mr.MANIFEST_KEYS_V2
        sets = manifest["reference_snapshot_sets"]
        assert [entry["set_schema"] for entry in sets] == families
        for entry in sets:
            assert entry["snapshot_set"]["set_hash"] in markdown
            if entry["set_schema"] == rkc.SET_SCHEMA:
                assert entry["copied_from"] == content["parameters"]["catalytic_annotation"]
                assert entry["snapshot_set"] == run.store.load(entry["copied_from"])["snapshot_set"]
            else:
                assert entry["copied_from"] == world["map"]   # the map, also when only the annotation is given
                assert entry["snapshot_set"] == run.store.load(world["map"])["snapshot_set"]
                assert entry["snapshot_set"]["set_hash"] == run.store.load(world["annotation"])["snapshot_set_hash"]
    assert _selected(client, created["handle"]).json()["markdown"] == markdown
    # the M20 lines of @1 are kept as they are in @2: removing the table section gives the @1 rendering
    as_v1 = {key: value for key, value in manifest.items() if key != "reference_snapshot_sets"}
    as_v1["render_version"] = mr.RENDER_VERSION
    v1_markdown = mr.render_mutation_report(as_v1)
    if not families:
        assert markdown == v1_markdown
    else:
        assert v1_markdown.split("\n## Limitations\n")[0] == markdown.split("\n## 참조 스냅샷\n")[0]


def test_annotation_only_report_names_the_map_it_reached_through_the_annotation(client, world):
    created = _report(client, world["mq_annotation"])
    markdown = created["markdown"]
    assert "- 번호 대응: 주지 않음" in markdown                          # the request: no map given to M20
    assert f"Numbering map: {_md(world['map'])}" in markdown.splitlines()   # the set is named through the annotation


def test_tampered_v2_reports_are_rejected_on_reopen(client, world):
    run = _run()
    created = _report(client, world["mq"])
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["render_version"] == V2

    def entry(forged):
        return forged["reference_snapshot_sets"][0]

    edits = [
        lambda f: entry(f)["snapshot_set"].update(set_hash="0" * 64),
        lambda f: entry(f)["snapshot_set"]["sources"][0].update(license="CC0-1.0"),
        lambda f: entry(f)["snapshot_set"]["sources"][-1].update(date="2026-01-01"),
        lambda f: entry(f).update(klifs_terms="CC-BY-4.0"),
        lambda f: entry(f).update(reference_set_handle=world["annotation"]),   # another stored object
        lambda f: entry(f).update(copied_from=world["annotation"]),
        lambda f: entry(f).update(note="extra"),
        lambda f: f["reference_snapshot_sets"].clear(),
        lambda f: f["reference_snapshot_sets"].append(copy.deepcopy(entry(f))),
        lambda f: f.pop("reference_snapshot_sets"),
        lambda f: f.update(render_version=mr.RENDER_VERSION),
        lambda f: f.update(render_version="mutation_candidates_markdown@3"),
    ]
    forged = [_forge(run, manifest, markdown, edit) for edit in edits]
    # the table rows of the Markdown changed with the manifest kept
    kbase = _md(nr.PROCESSED_LABEL)
    assert kbase in markdown
    forged.append(_forge(run, manifest, markdown.replace(kbase, "kbase\\_kinase 원본", 1), lambda _f: None))
    forged.append(_forge(run, manifest, markdown.replace("\n## 참조 스냅샷\n", "\n## 참조\n"), lambda _f: None))
    # an @2 manifest for a set that cites nothing
    plain = _report(client, world["plain"])
    forged.append(_forge(run, plain["manifest"], plain["markdown"],
                         lambda f: f.update(render_version=V2, reference_snapshot_sets=[])))
    for handle in forged:
        response = _selected(client, handle)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "report_evidence_invalid"
    assert _selected(client, created["handle"]).status_code == 200


def test_v2_table_template_is_checked_for_interpretive_wording(client, world, monkeypatch):
    for name in ("mq", "mq_map", "mq_annotation", "cat", "cat_partial"):
        markdown = _report(client, world[name])["markdown"]
        assert "\n## 참조 스냅샷\n" in markdown
        section = markdown.split("\n## 참조 스냅샷\n")[1].split("\n## Limitations\n")[0]
        for word in ("점수", "순위", "추천", "활성", "중요", "핵심", "필수", "안정성", "효과", "결합"):
            assert word not in section, (name, word)
        mr.check_no_interpretation(section)
    # the fixed table text is template text: a forbidden word in it refuses the report (create and reopen)
    created = _report(client, world["mq"])
    monkeypatch.setattr(nr, "PROCESSED_LABEL", "kbase_kinase 가공본 (추천)")
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["mq"]})
    assert response.status_code == 422 and "interpretive_statement" in response.text
    response = _selected(client, created["handle"])
    assert response.status_code == 422 and "interpretive_statement" in response.text
    monkeypatch.undo()
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    monkeypatch.setitem(rkc.STATEMENTS, "RK6", rkc.STATEMENTS["RK6"] + " 활성")
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["cat"]})
    assert response.status_code == 422 and "interpretive_statement" in response.text
