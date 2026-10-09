"""M26 T5: ``reaction_knowledge`` method reports (spec 7): counts recounted from the stored rows, reference values
kept apart (verbatim, with the set hash and source date / license), "검사하지 않음" with no number, the snapshot
source table + RK6, RK1-RK5 verbatim, the 200-line cap with the unlisted count, forbidden words on the fixed template
only, and create / reopen / download that read stored objects only (the linking is never run again).

Results are made by the real tool (``POST /runs/{rid}/commands`` -> ``link_reaction_knowledge``) on the LABELLED
SYNTHETIC T2 structures (``structure_alpha.cif`` = 0SY1, ``structure_beta.pdb`` = 0SY2), the public 1UBQ and 1MQ4
mmCIF, with LABELLED SYNTHETIC reaction reference sets written by ``reaction_fixture.build_set`` under a temporary
``MW_REACTION_REFERENCE_DIR`` (the 1MQ4 case also uses a real M15 ``map_residue_numbering`` result on the M15
reference FIXTURE set). Expected counts are recounted here from the stored result rows, never taken from the report
module. Tampered reports, objects and events are LABELED TEST FABRICATIONS.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import shutil
from pathlib import Path

import pytest
import reaction_fixture as RF
from fastapi.testclient import TestClient
from reference_fixture_set import build_fixture_set
from test_reaction_knowledge_tool import ALPHA, BETA, CIF_1MQ4, CIF_1UBQ, _synthetic_map

from mw import reaction_knowledge as rk
from mw import reaction_knowledge_constants as K
from mw import reaction_knowledge_reports as rr
from mw import reaction_snapshots as rs
from mw import reference_snapshots as m15_rs
from mw.core.handles import canonical_json
from mw.reports import EvidenceError, _md

TOOL = K.TOOL


# ------------------------------------------------------------------------------------------- fixtures and helpers

@pytest.fixture
def refdir(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    yield root
    rs._VERIFIED.clear()
    rk.clear_index_cache()


@pytest.fixture
def client(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    yield TestClient(appmod.app, base_url="http://127.0.0.1")
    appmod.RUNS.clear()


def _app():
    import mw.api.app as appmod
    return appmod


def _run(rid):
    return _app()._run(rid)


def _new_run(client) -> str:
    return client.post("/runs", json={"goal": "reaction knowledge reports", "dry_run": False}).json()["run_id"]


def _load(client, rid, path: Path) -> str:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": path.name}, content=path.read_bytes(),
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                         "args": {"source": upload.json()["upload_id"]}})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["handle"]["handle"]


def _link(client, rid, structure, chains=(("A", "Q0SYN1"), ("B", None)), pdb_id="0SY1", numbering_map=None) -> str:
    response = client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "structure": structure, "pdb_id": pdb_id, "numbering_map": numbering_map,
        "chains": [{"chain_auth": c, "uniprot_accession": a} for c, a in chains]}})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _report(client, rid, handle) -> dict:
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert response.status_code == 201, response.text
    return response.json()


def _selected(client, rid, handle):
    return client.get(f"/runs/{rid}/reports/selected", params={"handle": handle})


def _claims(manifest, statement, **selector):
    return [c for c in manifest["claims"] if c["statement_id"] == statement and
            all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]


def _claim(manifest, statement, path=None, **selector):
    found = [c for c in _claims(manifest, statement, **selector) if path is None or c["field_path"] == path]
    assert len(found) == 1, (statement, path, selector, len(found))
    return found[0]


_TOKEN = re.compile(r"([A-Za-z_]+)|\[(\d+)\]|\.")


def _at(content, path: str):
    """The stored value at a claim's field path (independent resolver, no report code)."""
    value = content
    for name, index in (m.groups() for m in _TOKEN.finditer(path)):
        if name:
            value = value[name]
        elif index is not None:
            value = value[int(index)]
    return value


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
                               summary={"result_handle": forged["result_handle"], "analysis_type": rr.ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _section(markdown: str, start: str, end: str) -> list[str]:
    lines = markdown.split("\n")
    first = lines.index(start)
    return lines[first:lines.index(end, first)]


@pytest.fixture
def world(client, refdir):
    set_hash = RF.build_set(refdir)
    rid = _new_run(client)
    run = _run(rid)
    alpha = _load(client, rid, ALPHA)
    nmap = _synthetic_map(run, alpha)
    beta = _load(client, rid, BETA)
    ubq = _load(client, rid, CIF_1UBQ)
    return {"rid": rid, "set_hash": set_hash, "root": refdir, "alpha": alpha, "map": nmap, "beta": beta, "ubq": ubq,
            "full": _link(client, rid, alpha, numbering_map=nmap),
            "beta_result": _link(client, rid, beta, chains=(("A", None), ("B", "Q0SYN5")), pdb_id="0SY2"),
            "empty": _link(client, rid, ubq, chains=(("A", None),), pdb_id="1UBQ"),
            "no_pdb": _link(client, rid, ubq, chains=(("A", None),), pdb_id=None),
            "skipped": _link(client, rid, alpha, chains=(("A", "Q0SYN4"), ("B", "Q0SYN0")), pdb_id="0SY9")}


# ------------------------------------------------------------------------------------------- computed values

def test_counts_are_recounted_from_the_stored_rows(client, world):
    rid, handle = world["rid"], world["full"]
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run(rid).store.load(handle)
    chains = content["chains"]
    assert (manifest["analysis_type"], manifest["render_version"], manifest["result_schema"]) == (
        "reaction_knowledge", "reaction_knowledge_markdown@1", "reaction_knowledge@1")
    assert {c["source_handle"] for c in manifest["claims"]} == {handle}
    computed = [c for c in manifest["claims"] if c["evidence_kind"] == "computed"]
    for claim in computed:   # no rounding: integers render as themselves, statuses as fixed wording
        if claim["rounding"] == "integer":
            assert type(claim["exact_value"]) is int and claim["rendered_value"] == str(claim["exact_value"])
        else:
            assert claim["rounding"] in ("status", "in_snapshot")
    assert _claim(manifest, "chain_count")["exact_value"] == len(chains) == 2
    covered = [c for c in chains if c["mcsa"]["coverage"] == "covered"]
    for status in K.ROW_STATUSES:
        total = sum(r["status"] == status for c in covered for r in c["mcsa"]["rows"])
        assert _claim(manifest, "total_mcsa_row_count", status=status)["exact_value"] == total
        assert total == content["counts"]["mcsa_rows"][status]
    assert {s: _claim(manifest, "total_mcsa_row_count", status=s)["exact_value"] for s in K.ROW_STATUSES} == {
        "matched": 15, "unmatched": 8, "conflict": 6}   # the independent T2 oracle (alpha_A)
    a_rows = chains[0]["mcsa"]["rows"]
    for status in K.ROW_STATUSES:
        assert _claim(manifest, "mcsa_row_count", chain_auth="A", status=status)["exact_value"] == \
            sum(r["status"] == status for r in a_rows)
    assert not _claims(manifest, "mcsa_row_count", chain_auth="B")          # chain_not_listed: no number
    assert _claim(manifest, "mcsa_entry_count")["exact_value"] == len({e["mcsa_id"] for c in covered
                                                                       for e in c["mcsa"]["entries"]}) == 2
    for site_type in K.SITE_TYPES:
        assert _claim(manifest, "total_uniprot_feature_count", type=site_type)["exact_value"] == sum(
            f["type"] == site_type for c in chains for f in c["uniprot"]["features"])
        for chain in chains:
            assert _claim(manifest, "uniprot_feature_count", chain_auth=chain["chain_auth"],
                          type=site_type)["exact_value"] == sum(f["type"] == site_type
                                                                for f in chain["uniprot"]["features"])
    for status in K.LINK_STATUSES:
        total = sum(link["status"] == status for c in chains for f in c["uniprot"]["features"] for link in f["links"])
        assert _claim(manifest, "total_linked_position_count", status=status)["exact_value"] == total
        for ci, chain in enumerate(chains):
            for fi, feature in enumerate(chain["uniprot"]["features"]):
                assert _claim(manifest, "feature_link_count", f"chains[{ci}].uniprot.features[{fi}].links[*].status",
                              status=status)["exact_value"] == sum(x["status"] == status for x in feature["links"])
    rhea = {link["rhea_id"]: link["in_snapshot"] for c in chains for a in c["reactions"]["uniprot_activities"]
            for link in a["rhea"]}
    assert _claim(manifest, "total_rhea_count", in_snapshot=True)["exact_value"] == sum(rhea.values()) == 3
    assert _claim(manifest, "total_rhea_count", in_snapshot=False)["exact_value"] == 1   # RHEA:9000099
    assert "- M-CSA 행 (M-CSA가 다룬 체인 전체): 대응됨 (matched) 15; 대응 없음 (unmatched) 8; 충돌 (conflict) 6" in markdown
    assert "- 서로 다른 Rhea ID: 스냅샷에 있음 3; 스냅샷에 없음 1" in markdown


def test_every_listed_row_status_and_section_state_is_a_claim(client, world):
    rid, handle = world["rid"], world["full"]
    manifest = _report(client, rid, handle)["manifest"]
    content = _run(rid).store.load(handle)
    for ci, chain in enumerate(content["chains"]):
        assert _claim(manifest, "mcsa_status", f"chains[{ci}].mcsa.status")["exact_value"] == chain["mcsa"]["status"]
        assert _claim(manifest, "mcsa_coverage", f"chains[{ci}].mcsa.coverage")["exact_value"] == \
            chain["mcsa"]["coverage"]
        assert _claim(manifest, "uniprot_status", f"chains[{ci}].uniprot.status")["rendered_value"] == "검사함 (checked)"
        assert _claim(manifest, "reactions_status", f"chains[{ci}].reactions.status")["exact_value"] == "checked"
    for ri, row in enumerate(content["chains"][0]["mcsa"]["rows"]):
        claim = _claim(manifest, "mcsa_row_status", f"chains[0].mcsa.rows[{ri}].status")
        assert claim["exact_value"] == row["status"] and claim["subject"]["residue"] == row["residue"]
    link = _claim(manifest, "rhea_link_state", "chains[0].reactions.uniprot_activities[1].rhea[1].in_snapshot")
    assert (link["exact_value"], link["rendered_value"]) == (False, "스냅샷에 없음 (false)")


# ------------------------------------------------------------------------------------------- reference values

def test_reference_values_are_the_stored_values_verbatim(client, world):
    rid, handle = world["rid"], world["full"]
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run(rid).store.load(handle)
    references = [c for c in manifest["claims"] if c["evidence_kind"] == "reference_value"]
    sources = {s["source"]: s for s in content["snapshot_set"]["sources"]}
    statements = {c["statement_id"] for c in references}
    assert statements == {s for s, (kind, _) in rr.STATEMENTS.items() if kind == "reference_value"}
    for claim in references:
        stored = _at(content, claim["field_path"])
        assert canonical_json(claim["exact_value"]) == canonical_json(stored), claim["field_path"]
        reference = claim["reference"]
        assert reference["note"] == "참조 스냅샷 값, 계산 아님"
        assert reference["set_hash"] == content["snapshot_set"]["set_hash"] == world["set_hash"]
        for item in reference["sources"]:
            assert item == {"source": item["source"], "date": sources[item["source"]]["date"],
                            "license": "CC-BY-4.0"}
    assert {c["exact_value"] for c in _claims(manifest, "reference_rhea_equation")} == {
        row["equation"] for row in content["reference_rows"]["rhea"]}
    # role text verbatim: every listed row's roles_summary appears escaped (never translated) in the Markdown
    row = content["chains"][0]["mcsa"]["rows"][0]
    assert row["reference"]["roles_summary"] == "fixture roles summary"
    assert f"roles\\_summary: {_md(row['reference']['roles_summary'])}" in markdown
    assert f"function\\_location\\_abv: {_md(row['reference']['function_location_abv'])}" in markdown
    assert "ptm: \"\"" in markdown                                          # the empty string stays visible
    reaction = content["chains"][0]["reactions"]["uniprot_activities"][0]["reaction_name"]
    assert _md(reaction) in markdown
    assert "RHEA:9000099 스냅샷에 없음 \\(false\\) |" in markdown            # no equation for an ID not in the set


def test_statement_ids_have_one_kind_and_disjoint_field_rules(client, world):
    manifest = _report(client, world["rid"], world["full"])["manifest"]
    for claim in manifest["claims"]:
        kind, rule = rr.STATEMENTS[claim["statement_id"]]
        assert claim["evidence_kind"] == kind and rule.fullmatch(claim["field_path"]), claim["field_path"]
        assert bool(rr.COMPUTED_FIELDS.fullmatch(claim["field_path"])) is (kind == "computed")
        assert bool(rr.REFERENCE_FIELDS.fullmatch(claim["field_path"])) is (kind == "reference_value")
        assert (claim["reference"] is None) is (kind == "computed")


def test_mixed_evidence_kinds_are_refused_before_any_value_comparison(client, world):
    run, handle = _run(world["rid"]), world["full"]
    manifest = _report(client, world["rid"], handle)["manifest"]
    count = _claim(manifest, "mcsa_row_count", chain_auth="A", status="conflict")
    role = _claim(manifest, "reference_mcsa_role", "chains[0].mcsa.rows[0].reference.roles_summary")
    for claim in (count, role):
        assert rr.validate_reaction_claim(run, handle, copy.deepcopy(claim)) == claim
    cases = {
        # a computed claim citing a reference field (values copied from the reference claim): refused on the path
        "reference_field_as_computed": [
            {**role, "statement_id": "mcsa_row_count", "evidence_kind": "computed", "reference": None},
            {**count, "field_path": "chains[0].mcsa.rows[0].listed.code"},
            {**count, "field_path": "chains[0].uniprot.features[0].start"}],
        "computed_field_as_reference": [{**role, "field_path": "chains[0].mcsa.rows[*].status"}],
        "evidence_kind_mismatch": [{**count, "evidence_kind": "reference_value"},
                                   {**role, "evidence_kind": "computed", "reference": None}],
        "reference_field_rule": [{**role, "reference": None}, {**role, "reference": {"note": "계산"}}],
        "computed_field_rule": [{**count, "reference": role["reference"]}],
    }
    for reason, claims in cases.items():
        for claim in claims:
            with pytest.raises(EvidenceError, match=reason):
                rr.validate_reaction_claim(run, handle, claim)


def test_wrong_values_unchecked_numbers_and_other_sources_are_refused(client, world):
    run, handle = _run(world["rid"]), world["full"]
    manifest = _report(client, world["rid"], handle)["manifest"]
    count = _claim(manifest, "mcsa_row_count", chain_auth="A", status="unmatched")
    coverage = _claim(manifest, "mcsa_coverage", "chains[1].mcsa.coverage")
    role = _claim(manifest, "reference_mcsa_role", "chains[0].mcsa.rows[0].reference.roles_summary")
    row_status = _claim(manifest, "mcsa_row_status", "chains[0].mcsa.rows[0].status")
    wrong = {
        "binding_mismatch": [
            {**count, "exact_value": 9, "rendered_value": "9"},
            {**count, "rendered_value": f"{count['exact_value']}.0"},
            {**count, "subject": {**count["subject"], "structure_handle": world["beta"]}},   # another structure
            {**coverage, "exact_value": "covered", "rendered_value": "M-CSA가 이 체인을 다룸 (covered)"},
            {**role, "exact_value": "translated summary", "rendered_value": "translated summary"}],
        "field_not_allowed": [   # a number for a section that was not checked (0 or otherwise)
            {**count, "field_path": "chains[1].mcsa.rows[*].status", "row_selector": {"chain_auth": "B",
                                                                                  "status": "unmatched"},
             "exact_value": 0, "rendered_value": "0"},
            {**row_status, "field_path": "chains[0].mcsa.rows[999].status"}],   # a row that does not exist
        "statement_not_allowed": [{**count, "statement_id": "mcsa_row_rank"}],
        "source_kind_mismatch": [{**count, "source_kind": "structure"}],
        "source_mismatch": [{**count, "source_handle": world["beta_result"],
                             "source_sha256": world["beta_result"].rsplit("/", 1)[-1]}],
        "claim_shape": [{k: v for k, v in count.items() if k != "unit"}],
    }
    for reason, claims in wrong.items():
        for claim in claims:
            with pytest.raises(EvidenceError, match=reason):
                rr.validate_reaction_claim(run, handle, claim)


# ------------------------------------------------------------------------------------------- not checked != 0

def test_not_checked_sections_carry_a_status_claim_and_no_number(client, world):
    rid = world["rid"]
    for key, mcsa_status in (("empty", "checked"), ("no_pdb", "not_checked")):
        created = _report(client, rid, world[key])
        manifest, markdown = created["manifest"], created["markdown"]
        statements = {c["statement_id"] for c in manifest["claims"]}
        assert statements == {"chain_count", "reference_snapshot_rows", "mcsa_status", "uniprot_status",
                              "reactions_status"} | ({"mcsa_coverage"} if mcsa_status == "checked" else set())
        assert _claim(manifest, "mcsa_status")["exact_value"] == mcsa_status
        assert _claim(manifest, "uniprot_status")["rendered_value"] == "검사하지 않음 (not_checked)"
        assert _claim(manifest, "reactions_status")["rendered_value"] == "검사하지 않음 (not_checked)"
        assert manifest["null_result"] is True and "유효한 빈 결과" in markdown
        body = _section(markdown, "## 전체 개수 (ProtView 계산: 저장된 행의 개수)", "## Limitations")
        numbered = [line for line in body if re.search(r"\d", line)]
        assert numbered == ["- 체인 수: 1"], numbered       # nothing else carries a number, never 0
        assert (rr.NOT_CHECKED_ROWS if mcsa_status == "not_checked" else rr.UNCOVERED_ROWS) in body
        assert rr.NOT_CHECKED_ROWS == "- 행: — (검사하지 않음. 행 개수를 세지 않았다.)"
    no_pdb = _report(client, rid, world["no_pdb"])["markdown"]
    assert "- 이유: PDB ID를 주지 않음 (pdb\\_id\\_not\\_given)" in no_pdb
    empty = _report(client, rid, world["empty"])["manifest"]
    assert _claim(empty, "mcsa_coverage")["rendered_value"] == "이 PDB ID는 스냅샷에 없음 (pdb_not_in_snapshot)"
    run = _run(rid)
    forged_zero = {**_claim(empty, "chain_count"), "statement_id": "total_mcsa_row_count",
                   "field_path": "chains[*].mcsa.rows[*].status", "row_selector": {"status": "matched"},
                   "exact_value": 0, "rendered_value": "0"}
    with pytest.raises(EvidenceError, match="field_not_allowed"):
        rr.validate_reaction_claim(run, world["empty"], forged_zero)
    checked = {**_claim(empty, "uniprot_status"), "exact_value": "checked", "rendered_value": "검사함 (checked)"}
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        rr.validate_reaction_claim(run, world["empty"], checked)


def test_unavailable_accessions_are_shown_with_their_reason_and_no_number(client, world):
    created = _report(client, world["rid"], world["skipped"])
    manifest, markdown = created["manifest"], created["markdown"]
    for chain in ("A", "B"):
        assert _claim(manifest, "uniprot_status", chain_auth=chain)["rendered_value"] == \
            "사용할 수 없음 (not_available)"
    assert not [c for c in manifest["claims"] if ".uniprot." in c["field_path"] and c["statement_id"] !=
                "uniprot_status"]
    assert "- 이유: 가져올 때 건너뛴 accession (accession\\_skipped\\_at\\_import)" in markdown
    assert "- 가져올 때 건너뛴 이유: 병합 (merged); UniProt가 알려 준 대표 accession: Q0SYN9" in markdown
    assert "- 이유: 스냅샷에 없는 accession (accession\\_not\\_in\\_snapshot)" in markdown
    assert markdown.count("- 부위: — (검사하지 않음. 부위 개수를 세지 않았다.)") == 2


def test_conflict_unmatched_and_uncovered_parts_are_never_hidden(client, world):
    markdown = _report(client, world["rid"], world["full"])["markdown"]
    chain_a = _section(markdown, "## 체인 A", "### UniProt")
    assert "- 행 수 (ProtView 계산): 대응됨 (matched) 15; 대응 없음 (unmatched) 8; 충돌 (conflict) 6" in chain_a
    table = [line for line in chain_a if line.startswith("| ") and "\\(" in line.split(" | ")[0]]
    assert len(table) == 29                                         # every row is listed (below the cap)
    assert sum("충돌 \\(conflict\\)" in line for line in table) == 6
    assert sum("대응 없음 \\(unmatched\\)" in line for line in table) == 8
    statuses = [line.split(" | ")[0] for line in table]
    first_unmatched = next(i for i, s in enumerate(statuses) if "unmatched" in s)
    assert all("unmatched" in s for s in statuses[first_unmatched:])   # matched and conflict rows first
    chain_b = _section(markdown, "## 체인 B", "### UniProt")
    chain_b = chain_b[chain_b.index("### M-CSA"):]
    assert "- 범위: 이 체인은 M\\-CSA 행에 없음 \\(chain\\_not\\_listed\\)" in chain_b
    assert rr.UNCOVERED_ROWS in chain_b and not any(re.search(r"\d", line) for line in chain_b)


def test_residue_lines_name_residues_by_the_7_fields_with_nulls(client, world):
    created = _report(client, world["rid"], world["beta_result"])
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run(world["rid"]).store.load(world["beta_result"])
    row = content["chains"][1]["mcsa"]["rows"][0]                  # chain B, PDB without label fields
    assert row["residue"]["chain_label"] is None and row["residue"]["seq_label"] is None
    claim = _claim(manifest, "mcsa_row_status", "chains[1].mcsa.rows[0].status")
    assert claim["subject"]["residue"] == row["residue"]          # 7 fields, nulls kept
    assert f"{row['residue']['resname']} auth B/{row['residue']['seq_auth']} icode \"\" label null/null model " \
           f"{row['residue']['model_number']}" in markdown
    assert "| 구조 잔기 없음 (null) |" in markdown                    # unmatched rows without a structure residue


def test_real_m15_numbering_map_links_a_site_in_the_report(client, refdir, tmp_path, monkeypatch):
    """Public 1MQ4 + a real M15 map (FIXTURE M15 set); the SYNTHETIC M26 UniProt row for O14965 holds made-up
    sites. The linked residue is the M15 SIFTS arithmetic (UniProt 256 -> label_seq 137), not report code."""
    m15 = tmp_path / "m15_reference"
    m15.mkdir()
    monkeypatch.setenv(m15_rs.ENV_VAR, str(m15))
    build_fixture_set(m15)
    rows = RF.synthetic_rows()
    rows["uniprot_function"].insert(0, {
        "accession": "O14965", "entry_name": "SYNTHETIC_FIXTURE", "protein_name": "SYNTHETIC fixture protein",
        "organism": "synthetic", "sequence_length": 403, "ec_numbers": [], "catalytic_activities": [],
        "features": [{"type": "Active site", "start": 256, "end": 256, "description": "SYNTHETIC fixture site",
                      "ligand_name": None, "ligand_id": None}]})
    RF.build_set(refdir, rows=rows)
    rid = _new_run(client)
    structure = _load(client, rid, CIF_1MQ4)
    mapped = client.post(f"/runs/{rid}/commands", json={"tool": "map_residue_numbering", "args": {
        "structure": structure, "pdb_id": "1MQ4", "chains": [{"chain_auth": "A", "uniprot_accession": "O14965"}]}})
    assert mapped.status_code == 200, mapped.text
    handle = _link(client, rid, structure, chains=(("A", None),), pdb_id="1MQ4",
                   numbering_map=mapped.json()["handle"]["handle"])
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    assert _claim(manifest, "uniprot_link_state")["rendered_value"] == "번호 대응으로 구조 잔기에 연결함 (numbering_map)"
    assert _claim(manifest, "feature_link_count", status="mapped")["exact_value"] == 1
    assert _claim(manifest, "reference_uniprot_entry", "chains[0].uniprot.entry.accession")["exact_value"] == "O14965"
    assert re.search(r"auth A/\d+ icode \"\" label A/137 model 1", markdown)
    assert _selected(client, rid, created["handle"]).json()["markdown"] == markdown


# ------------------------------------------------------------------------------------------- template wording

def test_forbidden_words_are_refused_except_on_the_rk1_rk5_lines():
    text = "\n".join(["# x", *K.LIMITATIONS, "ok", "촉매 잔기 행", K.STATEMENTS["RK6"]])
    assert rr.check_no_interpretation(text) == text
    assert any("활성" in line for line in K.LIMITATIONS) and any("메커니즘이 유지" in line for line in K.LIMITATIONS)
    for bad in ("필수 잔기", "핵심 잔기", "중요한 위치", "메커니즘이 유지된다", "메커니즘이  유지", "활성 잔기", "안정성",
                "ΔΔG", "순위", "추천", "최적", "개선", "예측", "유망", "좋은", "나쁜", "안전", "점수", "에너지", "수소 결합",
                "결합 부위", "기능", "essential", "key residue", "important", "critical", "binding", "active site",
                "activity", "score", "energy", "rank", "best", "recommended", "optimal", "improves", "predicted",
                "promising", "good", "safe", "hydrogen bond", "the mechanism is preserved", "mechanism maintained",
                "affinity", "stabilizing", "selectivity", "inhibits"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            rr.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {K.LIMITATIONS[4]}", K.LIMITATIONS[4] + " ", " " + K.LIMITATIONS[1]):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            rr.check_no_interpretation(near)


def test_rendered_reports_pass_only_because_identifiers_and_reference_strings_are_slots(client, world):
    for key in ("full", "beta_result", "empty", "no_pdb", "skipped"):
        created = _report(client, world["rid"], world[key])
        assert created["markdown"]   # the template itself passed the check
    full = _report(client, world["rid"], world["full"])["markdown"]
    assert "Active site" in full and "Binding site" in full       # UniProt site types: reference values
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        rr.check_no_interpretation(full)                          # a whole-line check would refuse this report


def test_forbidden_words_inside_reference_strings_do_not_fail_a_report(client, refdir):
    """SYNTHETIC rows whose role text, site description, reaction name and equation contain forbidden words: they
    are reference strings (slots), copied verbatim; the template stays checked."""
    rows = RF.synthetic_rows()
    wording = "SYNTHETIC essential key residue, important binding; mechanism is preserved; 핵심 필수 중요 활성"
    rows["mcsa"][0]["residues"][0]["roles_summary"] = wording
    q1 = next(r for r in rows["uniprot_function"] if r["accession"] == "Q0SYN1")
    q1["features"][0]["description"] = "SYNTHETIC best active site score"
    q1["catalytic_activities"][0]["reaction_name"] = "SYNTHETIC optimal energy reaction"
    next(r for r in rows["rhea"] if r["rhea_id"] == "RHEA:10000")["equation"] = "SYNTHETIC predicted = improved"
    RF.build_set(refdir, rows=rows)
    rid = _new_run(client)
    handle = _link(client, rid, _load(client, rid, ALPHA))
    created = _report(client, rid, handle)
    markdown = created["markdown"]
    for text in (wording, "SYNTHETIC best active site score", "SYNTHETIC optimal energy reaction",
                 "SYNTHETIC predicted = improved"):
        assert _md(text) in markdown
    assert _claim(created["manifest"], "reference_mcsa_role",
                  "chains[0].mcsa.rows[0].reference.roles_summary")["exact_value"] == wording
    assert _selected(client, rid, created["handle"]).json()["markdown"] == markdown


def test_a_forbidden_word_seeded_into_the_template_is_caught(client, world, monkeypatch):
    rid = world["rid"]
    log = _run(rid).run_dir / "events.jsonl"
    before = log.read_bytes()
    seeds = [(rr.STATUS_LABELS, "matched", "핵심 대응됨"), (rr, "UNCOVERED_ROWS", "- 행: — (중요한 체인)"),
             (rr, "EVIDENCE_STATEMENT", "ProtView는 촉매 메커니즘이 유지되는지 셌다."),
             (rr.REASON_LABELS, "residue_name_differs", "필수 잔기 이름이 다름")]
    for target, name, text in seeds:
        with pytest.MonkeyPatch.context() as patch:
            if isinstance(target, dict):
                patch.setitem(target, name, text)
            else:
                patch.setattr(target, name, text)
            response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["full"]})
            assert response.status_code == 422 and "interpretive_statement" in response.text, name
    assert log.read_bytes() == before                             # a refused report stores nothing
    assert _report(client, rid, world["full"])["markdown"]        # the unseeded template passes


def test_snapshot_table_rk6_and_rk1_rk5_are_always_present(client, world):
    for key in ("full", "beta_result", "empty", "no_pdb", "skipped"):
        created = _report(client, world["rid"], world[key])
        manifest, markdown = created["manifest"], created["markdown"]
        lines = markdown.split("\n")
        assert K.STATEMENTS["RK6"] in lines
        rows = {s: len(RF.synthetic_rows()[s]) for s in K.SOURCES}
        for source, label in (("mcsa", "M\\-CSA"), ("uniprot_function", "UniProt"), ("rhea", "Rhea")):
            line = next(x for x in lines if x.startswith(f"| {label} | "))
            assert world["set_hash"] in line and f"| {rows[source]} |" in line
            assert "CC BY 4.0 (CC\\-BY\\-4\\.0)" in line and line.endswith("| 공개 서버에서 가져온 가공본 |")
            assert RF.DATE.replace("-", "\\-") in line
        limits = _section(markdown, "## Limitations", lines[-2])
        assert [line for line in limits if line in K.LIMITATIONS] == list(K.LIMITATIONS)
        assert manifest["limitations"] == list(K.LIMITATIONS)


def test_the_200_line_cap_lists_matched_and_conflict_first_and_counts_the_rest(client, refdir):
    """SYNTHETIC set: entry 101 gets 205 more chain-A residues (numbers 1000+, absent from the structure ->
    unmatched), Q0SYN1 205 more sites and 205 more catalytic activities."""
    rows = RF.synthetic_rows()
    entry = rows["mcsa"][0]
    template = copy.deepcopy(entry["residues"][0])
    for i in range(205):
        residue = copy.deepcopy(template)
        residue["residue_chains"][0].update(auth_resid=1000 + i, resid=900 + i, code="Lys")
        residue["residue_sequences"] = []
        entry["residues"].append(residue)
    q1 = next(r for r in rows["uniprot_function"] if r["accession"] == "Q0SYN1")
    q1["features"].extend({"type": "Site", "start": 150, "end": 150, "description": f"SYNTHETIC site {i}",
                           "ligand_name": None, "ligand_id": None} for i in range(205))
    q1["catalytic_activities"].extend({"reaction_name": f"SYNTHETIC reaction {i}", "ec_number": None,
                                       "rhea_ids": [], "chebi_ids": []} for i in range(205))
    RF.build_set(refdir, rows=rows)
    rid = _new_run(client)
    handle = _link(client, rid, _load(client, rid, ALPHA), chains=(("A", "Q0SYN1"),))
    content = _run(rid).store.load(handle)
    stored = content["chains"][0]["mcsa"]["rows"]
    assert len(stored) == 29 + 205
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    listed = [int(re.fullmatch(r"chains\[0\]\.mcsa\.rows\[(\d+)\]\.status", c["field_path"]).group(1))
              for c in _claims(manifest, "mcsa_row_status")]
    first = [i for i, r in enumerate(stored) if r["status"] in ("matched", "conflict")]
    rest = [i for i, r in enumerate(stored) if r["status"] == "unmatched"]
    assert listed == (first + rest)[:200] and len(first) == 21
    assert _claim(manifest, "unlisted_line_count", section="mcsa")["exact_value"] == len(stored) - 200 == 34
    assert _claim(manifest, "unlisted_line_count", section="uniprot")["exact_value"] == 4 + 205 - 200
    assert _claim(manifest, "unlisted_line_count", section="reactions")["exact_value"] == 4 + 205 - 200
    assert len(_claims(manifest, "reference_uniprot_site", chain_auth="A", feature_index=199)) == 4
    assert not _claims(manifest, "reference_uniprot_site", feature_index=200)
    assert "- 이 보고서에 나열하지 않은 행 (ProtView 계산): 34 (전체는 결과 객체에 있다)" in markdown
    assert "- 이 보고서에 나열하지 않은 부위 (ProtView 계산): 9 (전체는 결과 객체에 있다)" in markdown
    assert "- 이 보고서에 나열하지 않은 촉매 활동 (ProtView 계산): 9 (전체는 결과 객체에 있다)" in markdown
    chain_a = _section(markdown, "## 체인 A", "### UniProt")
    assert sum(1 for line in chain_a if line.startswith("| ") and "\\(" in line.split(" | ")[0]) == 200
    assert _claim(manifest, "mcsa_row_count", status="unmatched")["exact_value"] == 8 + 205   # counts are complete
    assert _selected(client, rid, created["handle"]).json()["markdown"] == markdown


# ------------------------------------------------------------------------------------------- create / reopen

def test_create_reopen_list_and_download_round_trip(client, world):
    rid = world["rid"]
    created = _report(client, rid, world["full"])
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["snapshot"]["active_set_hash"] == world["set_hash"]
    again = _selected(client, rid, created["handle"]).json()
    assert again["markdown"] == markdown and again["manifest"] == manifest
    assert rr.saved_reaction_report(_run(rid), created["handle"])["markdown"] == markdown
    listed = {row["handle"]: row for row in client.get(f"/runs/{rid}/reports").json()}
    assert listed[created["handle"]]["analysis_type"] == "reaction_knowledge"
    assert listed[created["handle"]]["result_handle"] == world["full"]
    download = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]})
    assert download.status_code == 200 and download.content == markdown.encode()
    raw = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert raw.status_code == 200 and raw.content == canonical_json(manifest)


def test_tampered_reports_are_refused_on_reopen(client, world):
    rid = world["rid"]
    run = _run(rid)
    created = _report(client, rid, world["full"])
    manifest, markdown = created["manifest"], created["markdown"]
    count = _claim(manifest, "mcsa_row_count", chain_auth="A", status="conflict")

    def flip_count(forged):
        claim = next(c for c in forged["claims"] if c == count)
        claim.update(exact_value=0, rendered_value="0")

    def swap_kind(forged):
        claim = next(c for c in forged["claims"] if c == count)
        claim.update(evidence_kind="reference_value")

    def drop_reference(forged):
        claim = next(c for c in forged["claims"] if c["evidence_kind"] == "reference_value")
        claim.update(evidence_kind="computed", reference=None)

    forged = [
        _forge(run, manifest, markdown, flip_count),
        _forge(run, manifest, markdown, swap_kind),
        _forge(run, manifest, markdown, drop_reference),
        _forge(run, manifest, markdown.replace("충돌 (conflict) 6", "충돌 (conflict) 0"), lambda _f: None),
        _forge(run, manifest, markdown.replace("## Limitations", "가장 중요한 잔기다.\n\n## Limitations"),
               lambda _f: None),
        _forge(run, manifest, markdown, lambda f: f["counts"]["mcsa_rows"].update(conflict=0)),
        _forge(run, manifest, markdown, lambda f: f["chains"][0]["mcsa"]["rows"][0].update(status="conflict")),
        _forge(run, manifest, markdown, lambda f: f["chains"][1]["mcsa"].update(status="not_checked")),
        _forge(run, manifest, markdown, lambda f: f["limitations"].reverse()),
        _forge(run, manifest, markdown, lambda f: f["snapshot_set"].update(set_hash="f" * 64)),
        _forge(run, manifest, markdown, lambda f: f["claims"].pop()),
        _forge(run, manifest, markdown, lambda f: f.update(evidence_statement="ProtView가 판정했다.")),
        _forge(run, manifest, markdown, lambda f: f["snapshot"].update(active_set_hash="not-a-hash")),
        _forge(run, manifest, markdown, lambda f: f.update(result_handle=world["beta_result"])),
        _forge(run, manifest, markdown, lambda f: f["structure"].update(handle=world["beta"])),
    ]
    for handle in forged:
        response = _selected(client, rid, handle)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "report_evidence_invalid"
        download = client.get(f"/runs/{rid}/reports/download", params={"handle": handle})
        assert download.status_code == 422
    assert client.get(f"/runs/{rid}/reports").status_code == 422
    assert _selected(client, rid, created["handle"]).status_code == 200   # the genuine report still reopens


def test_create_reopen_and_download_never_relink_and_write_only_report_events(client, world, monkeypatch):
    rid = world["rid"]
    run = _run(rid)
    calls = []
    impl = _app().REGISTRY.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    def boom(*_a, **_k):
        raise AssertionError("the linking was run again")

    monkeypatch.setitem(_app().REGISTRY.impls, TOOL, counted)
    for name in ("build_reaction_knowledge", "mcsa_section", "uniprot_section", "reactions_section",
                 "chain_polymer_residues", "chain_accession", "chain_flags"):
        monkeypatch.setattr(rk, name, boom)
    before = list(run.events.read())
    created = _report(client, rid, world["full"])
    added = list(run.events.read())[len(before):]
    assert [e["type"] for e in added] == ["object_created", "object_created", "method_report_created"]
    assert [e.get("kind") for e in added[:2]] == ["report_markdown", "method_report_manifest"]
    log = run.run_dir / "events.jsonl"
    frozen = log.read_bytes()
    assert _selected(client, rid, created["handle"]).status_code == 200
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}).status_code == 200
    assert client.get(f"/runs/{rid}/reports").status_code == 200
    assert log.read_bytes() == frozen and calls == []
    assert not [e for e in run.events.read() if e["type"] == "tool_called"][len(
        [e for e in before if e["type"] == "tool_called"]):]


def test_reports_reopen_from_events_only_without_the_reference_folder(client, world):
    rid = world["rid"]
    run = _run(rid)
    created = _report(client, rid, world["full"])
    shutil.rmtree(world["root"])
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    _app().RUNS.clear()   # reopen the run: objects come back from events.jsonl alone
    again = _selected(client, rid, created["handle"])
    assert again.status_code == 200 and again.json()["markdown"] == created["markdown"]


def test_a_result_of_an_older_set_still_reports_with_the_earlier_snapshot_wording(client, world):
    rid, first = world["rid"], world["set_hash"]
    same = _report(client, rid, world["full"])
    assert "- 결과의 세트가 보고서를 만들 때 사용 중이던 세트와 같다." in same["markdown"]
    assert "이전 스냅샷 기준" not in same["markdown"]
    second = RF.build_set(world["root"], imported_at="2026-10-08T00:00:07Z")
    older = _report(client, rid, world["full"])
    assert older["manifest"]["snapshot"]["active_set_hash"] == second != first
    assert older["manifest"]["snapshot_set"]["set_hash"] == first          # the result is never recomputed
    assert ("- 이전 스냅샷 기준: 결과의 세트가 보고서를 만들 때 사용 중이던 세트와 다르다. 결과를 다시 계산하지 않았다."
            in older["markdown"])
    assert {k: v for k, v in older["manifest"].items() if k not in ("snapshot", "markdown_handle")} == \
        {k: v for k, v in same["manifest"].items() if k not in ("snapshot", "markdown_handle")}
    RF.activate(world["root"], first)
    assert _selected(client, rid, older["handle"]).json()["markdown"] == older["markdown"]   # recorded, not live
    shutil.rmtree(world["root"])
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    gone = _report(client, rid, world["full"])
    assert gone["manifest"]["snapshot"]["active_set_hash"] is None
    assert "- 사용 중 스냅샷 없음: 보고서를 만들 때 사용할 수 있는 반응 참조 세트가 없었다." in gone["markdown"]
    with pytest.raises(EvidenceError, match="active_set_invalid"):
        rr.build_reaction_report(_run(rid), world["full"], active_set_hash="abc")


# ------------------------------------------------------------------------------------------- other evidence

def test_evidence_of_another_run_or_a_forged_result_is_refused(client, world):
    rid = world["rid"]
    run = _run(rid)
    other_rid = _new_run(client)
    other = _link(client, other_rid, _load(client, other_rid, BETA), chains=(("A", None),), pdb_id="0SY2")
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": other})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"
    with pytest.raises(EvidenceError, match="other_run"):
        rr.validated_reaction_result(run, other)
    for wrong in (world["alpha"], world["map"]):   # another kind of this run
        response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": wrong})
        assert response.status_code == 422
    content = copy.deepcopy(run.store.load(world["full"]))
    content["structure"]["handle"] = world["beta"]   # still a valid result shape, but no tool produced it
    with run._owner():
        orphan = run.store.put(K.KIND, K.SCHEMA, content, produced_by="forged_test_result").handle
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": orphan})
    assert response.status_code == 422 and "provenance" in response.text
    content = copy.deepcopy(run.store.load(world["empty"]))
    content["counts"]["chains"] = 2
    with run._owner():
        bad = run.store.put(K.KIND, K.SCHEMA, content, produced_by="forged_test_result").handle
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": bad})
    assert response.status_code == 422 and "reaction_result_invalid" in response.text
    depth = 100000
    with run._owner():
        deep = run.store.put(K.KIND, K.SCHEMA, b"[" * depth + b"]" * depth, produced_by="forged_test_result").handle
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": deep})
    assert response.status_code == 422 and "reaction_result_invalid" in response.text


def _with_forged_provenance(run, content, name: str) -> str:
    """LABELED TEST FABRICATION: a result object plus tool_called / tool_succeeded events naming it."""
    call_id = f"call_forged_reaction_report_{name}"
    with run._owner():
        handle = run.store.put(K.KIND, K.SCHEMA, content, produced_by=call_id).handle
        run.events.append("tool_called", call_id=call_id, tool=TOOL, version="forged", args={})
        run.events.append("tool_succeeded", call_id=call_id, tool=TOOL, output={"handle": handle})
    return handle


def test_a_result_naming_another_structure_or_map_is_refused_even_with_provenance(client, world):
    run = _run(world["rid"])
    stranger = "obj://run_someone_else/structure/" + "a" * 64
    content = copy.deepcopy(run.store.load(world["empty"]))
    content["structure"]["handle"] = stranger
    with pytest.raises(EvidenceError, match="structure_link_mismatch"):
        rr.validated_reaction_result(run, _with_forged_provenance(run, content, "structure"))
    content = copy.deepcopy(run.store.load(world["full"]))
    beta_map = _synthetic_map(run, world["alpha"], structure_handle=world["beta"])   # a map of another structure
    content["numbering_map"]["handle"] = beta_map
    with pytest.raises(EvidenceError, match="numbering_map_structure_mismatch"):
        rr.validated_reaction_result(run, _with_forged_provenance(run, content, "map"))


# ------------------------------------------------------------------------------------------- module boundary

def test_the_report_module_reads_stored_evidence_only():
    path = Path(rr.__file__)
    source = path.read_text()
    tree = ast.parse(source)
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert not imported & {"socket", "urllib", "http", "httpx", "requests", "ssl", "gemmi", "numpy", "subprocess"}
    assert "raise_limits" not in source and "limit_approval" not in source
    for name in ("build_reaction_knowledge", "mcsa_section", "uniprot_section", "reactions_section",
                 "chain_polymer_residues", "pin_and_index", "reaction_index", "pin_active_set", "_parse("):
        assert name not in source, name
    assert json.dumps(rr.LINE_CAP) == "200"
