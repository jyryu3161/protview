"""M27 T5: ``kinase_precedents`` method reports (spec 7): a summary + a source list, counts recounted from the stored
result, kbase values kept apart as reference values ("kbase 가공본 값, 계산 아님" + set hash + ``kb_version`` + imported
time), no quote and no measured-change value, no number for a file that was not included (never 0; UP2 carries
``excluded_flagged``), the source table + KT1 + KP1-KP6 + UP5 always, the 300-line cap per target, escaped external
strings, forbidden words checked on the fixed template only, and create / reopen / download that read stored objects
only (the linking is never run again).

Results are made by the real tool (``POST /runs/{rid}/commands`` -> ``link_kinase_precedents``) on LABELLED SYNTHETIC
precedent sets written by ``precedent_fixture.build_set`` under a temporary ``MW_PRECEDENT_REFERENCE_DIR`` and the
LABELLED SYNTHETIC T2 numbering-map dicts stored for the uploaded public 1MQ4 structure. Expected counts come from the
independent T2 oracle (``fixtures/precedent/t2/expected.json``) or are recounted here from the stored result, never
taken from the report module. Tampered reports, objects and events are LABELED TEST FABRICATIONS. No real kbase_kinase
data, no network.
"""
from __future__ import annotations

import copy
import re
import shutil
from collections import Counter
from pathlib import Path

import precedent_fixture as PF
import pytest
from fastapi.testclient import TestClient
from test_kinase_precedents_tool import CIF_1MQ4, ORACLE, _store_map

from mw import kinase_precedents as kp
from mw import kinase_precedents_reports as pr
from mw import precedent_constants as K
from mw import precedent_snapshots as ps
from mw.core.handles import canonical_json
from mw.reports import EvidenceError, _md

CIF_1UBQ = Path(__file__).resolve().parent / "fixtures" / "public_1ubq.cif"
TOOL = K.TOOL
NOTE = "kbase 가공본 값, 계산 아님"


# ------------------------------------------------------------------------------------------- fixtures and helpers

@pytest.fixture
def refdir(tmp_path, monkeypatch):
    root = tmp_path / "precedent_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    yield root
    ps._VERIFIED.clear()
    kp.clear_index_cache()


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
    return client.post("/runs", json={"goal": "kinase precedent reports", "dry_run": False}).json()["run_id"]


def _load(client, rid, path=CIF_1MQ4) -> str:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": path.name}, content=path.read_bytes(),
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                         "args": {"source": upload.json()["upload_id"]}})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["handle"]["handle"]


def _link(client, rid, nmap, chains=None, include_flagged=False) -> str:
    response = client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "numbering_map": nmap, "chains": chains, "include_flagged": include_flagged}})
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


_PART = re.compile(r"([^\[\]]+)((?:\[\d+\])*)")


def _at(content, path: str):
    """The stored value at an indexed claim field path (independent resolver, no report code)."""
    value = content
    for segment in path.split("."):
        name, indexes = _PART.fullmatch(segment).groups()
        value = value[name]
        for index in re.findall(r"\[(\d+)\]", indexes):
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
                               summary={"result_handle": forged["result_handle"], "analysis_type": pr.ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _with_forged_provenance(run, content, name: str) -> str:
    """LABELED TEST FABRICATION: a result object plus tool_called / tool_succeeded events naming it."""
    call_id = f"call_forged_precedent_report_{name}"
    with run._owner():
        handle = run.store.put(K.KIND, K.SCHEMA, content, produced_by=call_id).handle
        run.events.append("tool_called", call_id=call_id, tool=TOOL, version="forged", args={})
        run.events.append("tool_succeeded", call_id=call_id, tool=TOOL, output={"handle": handle})
    return handle


def _section(markdown: str, start: str, end: str) -> list[str]:
    lines = markdown.split("\n")
    first = lines.index(start)
    return lines[first:lines.index(end, first + 1)]


def _note(key: str, n: int | None = None) -> str:
    """A fixed screen note as the report writes it: its own list item, sentence verbatim."""
    return "- " + (K.SCREEN_NOTES[key] if n is None else K.screen_note(key, n))


def _cells(line: str) -> list[str]:
    """Cells of a Markdown table line split at unescaped pipes."""
    return re.split(r"(?<!\\)\|", line)[1:-1]


@pytest.fixture
def world(client, refdir):
    set_hash = PF.build_set(refdir)
    rid = _new_run(client)
    structure = _load(client, rid)
    run = _run(rid)
    maps = {name: _store_map(run, structure, name) for name in ("main", "refs_only", "unlinked")}
    return {"rid": rid, "set_hash": set_hash, "root": refdir, "structure": structure, "maps": maps,
            "excluded": _link(client, rid, maps["main"]),
            "included": _link(client, rid, maps["main"], include_flagged=True),
            "refs_excluded": _link(client, rid, maps["refs_only"]),
            "refs_included": _link(client, rid, maps["refs_only"], include_flagged=True),
            "empty": _link(client, rid, maps["unlinked"])}


ALL = ("excluded", "included", "refs_excluded", "refs_included", "empty")
ORACLE_CASE = {"excluded": "main_all_excluded", "included": "main_all_included", "refs_excluded": "refs_only_excluded",
               "refs_included": "refs_only_included", "empty": "unlinked_only"}


# ------------------------------------------------------------------------------------------- computed values

@pytest.mark.parametrize("key", ALL)
def test_counts_are_recounted_from_the_stored_result_and_match_the_oracle(client, world, key):
    rid, handle = world["rid"], world[key]
    created = _report(client, rid, handle)
    manifest = created["manifest"]
    content = _run(rid).store.load(handle)
    oracle = ORACLE[ORACLE_CASE[key]]["result"]
    assert (manifest["analysis_type"], manifest["render_version"], manifest["result_schema"]) == (
        "kinase_precedents", "kinase_precedents_markdown@1", "kinase_precedents@1")
    assert {c["source_handle"] for c in manifest["claims"]} == {handle}
    for claim in manifest["claims"]:
        if claim["rounding"] == "integer":
            assert type(claim["exact_value"]) is int and claim["rendered_value"] == str(claim["exact_value"])
    chains, targets, include = content["chains"], content["targets"], content["include_flagged"]
    assert _claim(manifest, "chain_count")["exact_value"] == len(chains) == len(oracle["chains"])
    for status in K.CHAIN_STATUSES:
        assert _claim(manifest, "chain_status_count", status=status)["exact_value"] == \
            sum(c["status"] == status for c in oracle["chains"])
    for reason in K.CHAIN_REASONS:
        assert _claim(manifest, "chain_reason_count", reason=reason)["exact_value"] == \
            sum(c["reason"] == reason for c in oracle["chains"])
    assert _claim(manifest, "target_count")["exact_value"] == len(oracle["targets"])
    files = K.FILE_SOURCES if include else ("moves",)
    for name in files:
        assert _claim(manifest, "total_record_count", file=name)["exact_value"] == oracle["counts"]["records"][name]
    for ti, (target, expected) in enumerate(zip(targets, oracle["targets"])):
        acc = target["accession"]
        assert acc == expected["accession"]
        assert _claim(manifest, "target_status", f"targets[{ti}].status")["exact_value"] == expected["status"]
        for name in files:
            assert _claim(manifest, "target_record_count", accession=acc, file=name)["exact_value"] == \
                expected["counts"][name] == sum(item["file"] == name for item in target["records"])
        variants = {c["row_selector"]["variant"]: c["exact_value"]
                    for c in _claims(manifest, "target_variant_count", accession=acc)}
        assert variants == {v["variant"]: v["count"] for v in expected["counts"]["variants"]}
        for axis in K.TAG_AXES:
            # recount here: a record counts once per distinct term, even when kbase repeats it
            mine = Counter(term for item in target["records"] for term in set(item["record"]["tags"][axis]))
            claimed = {c["row_selector"]["term"]: c["exact_value"]
                       for c in _claims(manifest, "target_tag_count", accession=acc, axis=axis)}
            assert claimed == dict(mine) == {v["term"]: v["count"] for v in expected["counts"]["tags"][axis]}
        bases = {c["row_selector"]["basis"]: c["exact_value"]
                 for c in _claims(manifest, "target_basis_count", accession=acc)}
        assert bases == {v["basis"]: v["count"] for v in expected["counts"]["resolution_basis"]}
    unresolved = oracle["set_summary"]["unresolved_target_records"]
    for name in K.FILE_SOURCES:
        assert _claim(manifest, "unresolved_record_count", file=name)["exact_value"] == unresolved[name] == 2
    assert _claim(manifest, "unresolved_record_total")["exact_value"] == 4
    assert _note("UP5", 4) in created["markdown"].split("\n")


def test_overview_lines_and_up2_with_its_own_integer(client, world):
    rid = world["rid"]
    excluded = _report(client, rid, world["excluded"])["markdown"]
    lines = excluded.split("\n")
    assert "- 체인 수: 5" in lines
    assert "- 체인 상태별 수: 연결함 (linked) 3; 연결하지 않음 (not\\_linked) 2" in lines
    assert "- 표적 수: 2" in lines
    assert "- 포함한 전례 수 (모든 표적): moves 4; moves\\_flagged 포함하지 않음 \\(include\\_flagged false\\)" in lines
    assert "- 포함하지 않은 moves\\_flagged 전례 수 (모든 표적): 3" in lines
    assert "- 세트 전체 표적 미해석 전례 수 (세트 전체, 체인과 무관): moves 2; moves\\_flagged 2" in lines
    assert lines.count(_note("UP2", 1)) == 1 and lines.count(_note("UP2", 2)) == 1   # per target
    assert lines.count(_note("UP3")) == 2 and lines.count(_note("UP5", 4)) == 1
    included = _report(client, rid, world["included"])["markdown"].split("\n")
    assert "- 포함한 전례 수 (모든 표적): moves 4; moves\\_flagged 3" in included
    assert not [line for line in included if line.startswith("- moves_flagged 파일의 전례")]        # no UP2
    assert not [line for line in included if "포함하지 않은 moves" in line]


def test_a_file_that_was_not_included_has_no_number_and_is_never_zero(client, world):
    rid = world["rid"]
    created = _report(client, rid, world["excluded"])
    manifest, markdown = created["manifest"], created["markdown"]
    inclusion = _claim(manifest, "flagged_inclusion", "include_flagged")
    assert (inclusion["exact_value"], inclusion["rendered_value"]) == (False, "포함하지 않음 (include_flagged false)")
    assert not _claims(manifest, "target_record_count", file="moves_flagged")
    assert not _claims(manifest, "total_record_count", file="moves_flagged")
    assert [c["exact_value"] for c in _claims(manifest, "target_excluded_count")] == [1, 2]
    assert "moves\\_flagged 0" not in markdown and "moves_flagged 0" not in markdown
    target = _section(markdown, "## 표적 Q0SYN2", "## Limitations")
    assert "- 포함한 파일의 전례 수 (ProtView 계산): moves 0; moves\\_flagged 포함하지 않음 \\(include\\_flagged false\\)" \
        in target
    assert _note("UP2", 2) in target
    # excluded_flagged 0 is the integer the result holds: UP2 states it as it is (refs_only P0SYN3)
    refs = _report(client, rid, world["refs_excluded"])["markdown"]
    assert _note("UP2", 0) in _section(refs, "## 표적 P0SYN3", "## 표적 Q0SYN4")
    # included results carry no excluded number at all
    included = _report(client, rid, world["included"])["manifest"]
    assert not _claims(included, "target_excluded_count") and not _claims(included, "total_excluded_count")
    run = _run(rid)
    moves = _claim(manifest, "target_record_count", accession="Q0SYN2", file="moves")
    zero = {**moves, "row_selector": {**moves["row_selector"], "file": "moves_flagged"}, "quantity": "moves_flagged_records",
            "exact_value": 0, "rendered_value": "0"}
    with pytest.raises(EvidenceError, match="field_not_allowed"):
        pr.validate_precedent_claim(run, world["excluded"], zero)
    flipped = {**inclusion, "exact_value": True, "rendered_value": "포함함 (include_flagged true)"}
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        pr.validate_precedent_claim(run, world["excluded"], flipped)


def test_chain_rows_and_target_states_are_claims(client, world):
    created = _report(client, world["rid"], world["excluded"])
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run(world["rid"]).store.load(world["excluded"])
    for ci, chain in enumerate(content["chains"]):
        assert _claim(manifest, "chain_status", f"chains[{ci}].status")["exact_value"] == chain["status"]
        reasons = _claims(manifest, "chain_status", chain_auth=chain["chain_auth"])
        assert len(reasons) == (1 if chain["reason"] is None else 2)
    assert _claim(manifest, "chain_status", "chains[3].reason")["rendered_value"] == \
        "번호 대응에 mapped 잔기 행이 없음 (no_mapped_residues)"
    assert _claim(manifest, "chain_status", "chains[4].reason")["rendered_value"] == \
        "mapped 잔기의 accession이 둘 이상 (multiple_accessions)"
    table = _section(markdown, "## 체인", "## 표적 P0SYN1")
    rows = [line for line in table if line.startswith("| ") and not line.startswith("| 체인") and "---" not in line]
    assert [_cells(r)[0].strip() for r in rows] == ["C", "A", "B", "D", "E"]                   # the map's order
    assert _cells(rows[4])[4].strip() == "P0SYN3, Q0SYN4" and _cells(rows[3])[4].strip() == "빈 목록 ([])"
    refs = _report(client, world["rid"], world["refs_excluded"])["manifest"]
    assert [c["rendered_value"] for c in _claims(refs, "target_status")] == [
        "kbase에 이 표적 참조가 없음(전례 없음과 다름) (not_in_kbase_references)",
        "포함한 파일에 이 표적의 전례 기록 없음 (none_in_included_files)",
        "kbase에 이 표적 참조가 없음(전례 없음과 다름) (not_in_kbase_references)"]


# ------------------------------------------------------------------------------------------- reference values

def test_reference_values_are_the_stored_values_verbatim(client, world):
    rid, handle = world["rid"], world["included"]
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    content = _run(rid).store.load(handle)
    pset = content["precedent_set"]
    references = [c for c in manifest["claims"] if c["evidence_kind"] == "reference_value"]
    assert {c["statement_id"] for c in references} == {s for s, (kind, _) in pr.STATEMENTS.items()
                                                       if kind == "reference_value"}
    for claim in references:
        assert canonical_json(claim["exact_value"]) == canonical_json(_at(content, claim["field_path"])), \
            claim["field_path"]
        source = "kbase_pubmed" if claim["field_path"].startswith(("bibliography.", "precedent_set.bibliography")) \
            else "kbase_dist"
        assert claim["reference"] == {"note": NOTE, "set_hash": world["set_hash"],
                                      "kb_version": pset["kbase"]["kb_version"], "imported_at": pset["imported_at"],
                                      "source": source}
    record = content["targets"][0]["records"][0]["record"]       # MOVE-0001
    assert _claim(manifest, "reference_record_id", "targets[0].records[0].record.move_id")["exact_value"] == \
        record["move_id"] == "MOVE-0001"
    assert [c["exact_value"] for c in _claims(manifest, "reference_record_location", move_id="MOVE-0001")] == [
        "table", 3, 1, 2, "text", 4]                              # null location fields carry no claim
    title = content["bibliography"]["90000001"]["title"]
    assert _claim(manifest, "reference_bibliography", "bibliography.90000001.title")["exact_value"] == title
    assert _md(title) in markdown
    assert not _claims(manifest, "reference_bibliography", pmid="90000002")    # no bibliography: no claim
    assert len(_claims(manifest, "reference_target_ref", accession="P0SYN1")) == 10   # two refs x five fields


def test_each_precedent_has_one_source_line(client, world):
    created = _report(client, world["rid"], world["included"])
    markdown = created["markdown"]
    table = [line for line in _section(markdown, "## 표적 P0SYN1", "## 표적 Q0SYN2") if line.startswith("| MOVE")]
    assert [_cells(line)[0].strip() for line in table] == ["MOVE\\-0001", "MOVE\\-0007", "MOVE\\-0101",
                                                          "MOVE\\-9999", "MOVE\\-10000"]   # move_key order
    first = [c.strip() for c in _cells(table[0])]
    assert first[1:5] == ["moves", "gene", "not\\_reported", "90000001"]
    assert first[5].startswith("제목 " + _md("합성 SYNTHETIC fixture title 90000001") + "; 저널 ")
    assert first[5].endswith("; DOI " + _md("10.0000/synthetic.1"))
    assert first[6] == "종류 table, 쪽 3, 표 1, 행 2; 종류 text, 쪽 4"
    assert first[7] == "site bp\\_I\\_A, front; goal potency; tactic add\\_hydrophobic\\_bulk"
    assert first[8].startswith("sha256:")
    assert first[9] == "pass 10개"
    assert first[10] == "레코드 해시 일치 true; 인용 25단어 이하 true; 논문 쪽 위치 있음 true"
    seventh = [c.strip() for c in _cells(table[1])]
    assert seventh[5] == "서지 없음 (null)"                                  # PMID 90000003: status error
    assert seventh[9] == "pass 8개; chembl\\_crosscheck=lookup\\_failed; duplicate=fail"
    flagged = [c.strip() for c in _cells(table[2])]
    assert flagged[1] == "moves\\_flagged" and flagged[5] == "서지 없음 (null)"
    long_quote = [c.strip() for c in _cells(table[3])]
    assert long_quote[10] == "레코드 해시 일치 true; 인용 25단어 이하 false; 논문 쪽 위치 있음 true"
    assert long_quote[7].endswith("tactic 빈 목록 ([])")
    figure = [c.strip() for c in _cells(table[4])]
    assert figure[6] == "종류 figure, 쪽 7, 그림 F2, 패널 b"


def test_statement_ids_have_one_kind_and_disjoint_field_rules(client, world):
    manifest = _report(client, world["rid"], world["included"])["manifest"]
    for claim in manifest["claims"]:
        kind, rule = pr.STATEMENTS[claim["statement_id"]]
        assert claim["evidence_kind"] == kind and rule.fullmatch(claim["field_path"]), claim["field_path"]
        assert bool(pr.COMPUTED_FIELDS.fullmatch(claim["field_path"])) is (kind == "computed")
        assert bool(pr.REFERENCE_FIELDS.fullmatch(claim["field_path"])) is (kind == "reference_value")
        assert (claim["reference"] is None) is (kind == "computed")
    assert pr.STATEMENTS["record_integrity"][0] == "computed"           # ProtView checks, not kbase values
    assert pr.STATEMENTS["reference_record_check"][0] == "reference_value"


def test_mixed_evidence_kinds_are_refused_before_any_value_comparison(client, world):
    run, handle = _run(world["rid"]), world["included"]
    manifest = _report(client, world["rid"], handle)["manifest"]
    count = _claim(manifest, "target_variant_count", accession="P0SYN1", variant="A10V")
    variant = _claim(manifest, "reference_record_target", "targets[0].records[3].record.target.variant")
    for claim in (count, variant):
        assert pr.validate_precedent_claim(run, handle, copy.deepcopy(claim)) == claim
    cases = {
        # a computed claim citing a reference field: refused on the path, before the value is looked at
        "reference_field_as_computed": [
            {**variant, "statement_id": "target_variant_count", "evidence_kind": "computed", "reference": None},
            {**count, "field_path": "targets[0].records[3].record.target.variant"},
            {**count, "field_path": "bibliography.90000001.title"},
            {**count, "field_path": "targets[0].records[0].record.checks.duplicate.status"}],
        "computed_field_as_reference": [{**variant, "field_path": "targets[0].records[*].record.target.variant"},
                                        {**variant, "field_path": "targets[0].records[0].integrity.hash_verified"}],
        "evidence_kind_mismatch": [{**count, "evidence_kind": "reference_value"},
                                   {**variant, "evidence_kind": "computed", "reference": None}],
        "reference_field_rule": [{**variant, "reference": None}, {**variant, "reference": {"note": "계산"}}],
        "computed_field_rule": [{**count, "reference": variant["reference"]}],
    }
    for reason, claims in cases.items():
        for claim in claims:
            with pytest.raises(EvidenceError, match=reason):
                pr.validate_precedent_claim(run, handle, claim)


def test_wrong_values_other_sources_and_unknown_statements_are_refused(client, world):
    run, handle = _run(world["rid"]), world["included"]
    manifest = _report(client, world["rid"], handle)["manifest"]
    count = _claim(manifest, "target_record_count", accession="P0SYN1", file="moves")
    status = _claim(manifest, "target_status", "targets[1].status")
    move = _claim(manifest, "reference_record_id", "targets[0].records[0].record.move_id")
    wrong = {
        "binding_mismatch": [
            {**count, "exact_value": 9, "rendered_value": "9"},
            {**count, "rendered_value": f"{count['exact_value']}.0"},
            {**count, "subject": {**count["subject"], "structure_handle": world["maps"]["main"]}},
            {**status, "exact_value": "none_in_included_files",
             "rendered_value": "포함한 파일에 이 표적의 전례 기록 없음 (none_in_included_files)"},
            {**move, "exact_value": "MOVE-0002", "rendered_value": "MOVE-0002"}],
        "field_not_allowed": [{**move, "field_path": "targets[0].records[99].record.move_id"}],
        "statement_not_allowed": [{**count, "statement_id": "target_rank"}],
        "source_kind_mismatch": [{**count, "source_kind": "structure"}],
        "source_mismatch": [{**count, "source_handle": world["excluded"],
                             "source_sha256": world["excluded"].rsplit("/", 1)[-1]}],
        "claim_shape": [{k: v for k, v in count.items() if k != "unit"}],
    }
    for reason, claims in wrong.items():
        for claim in claims:
            with pytest.raises(EvidenceError, match=reason):
                pr.validate_precedent_claim(run, handle, claim)


# ------------------------------------------------------------------------------------------- not in the report

def test_quotes_and_measured_changes_are_never_in_the_report(client, refdir):
    """SYNTHETIC record whose quotes, observation, tradeoffs, change and effects carry unique tokens: the stored
    result has them (shown on screen), the report manifest and Markdown bytes have none of them."""
    tokens = ["zzobsquote", "zzobstext", "zztradequote", "zztradetext", "zzchangedesc", "zzfromcpd", "zztocpd",
              "zzmetric", "zzassay", "zzassaycontext", "zzoffref", "zzunit", "zzcompare", "zzeffectevidence",
              "13579.25", "24681357", "97531.5", "worsened", "zzinteraction", "zzextractmodel"]
    effect = PF.default_effect(metric="zzmetric", assay="zzassay", assay_context="zzassaycontext",
                               target_ref="zzoffref", target_role="off_target",
                               before={"qualifier": "=", "value": 24681357, "unit": "zzunit"},
                               after={"qualifier": "=", "value": 97531.5, "unit": "zzunit"},
                               direction="worsened", direction_basis="text", magnitude_bucket="moderate",
                               comparable=False, comparability_reason="zzcompare", fold_change=13579.25,
                               evidence={"synthetic": "zzeffectevidence"})
    record = PF.make_move(
        "MOVE-0400", uniprot="P0SYN1", quote="SYNTHETIC zzobsquote words", observation_text="SYNTHETIC zzobstext",
        tradeoffs=[{"text": "SYNTHETIC zztradetext", "quote": "SYNTHETIC zztradequote", "quote_truncated": True,
                    "evidence": {"synthetic": "fixture"}}],
        effects=[effect],
        change={"description": "SYNTHETIC zzchangedesc", "from_compound": "SYN zzfromcpd", "to_compound": "SYN zztocpd",
                "smiles_from": None, "smiles_to": None},
        interactions=[{"synthetic": "zzinteraction"}],
        extraction={"model": "zzextractmodel", "provider": "synthetic", "prompt_version": "fixture-1",
                    "run_at": "2026-10-01T00:00:00Z"})
    records = PF.t2_records()
    PF.build_set(refdir, moves=records["moves"] + [record])
    rid = _new_run(client)
    run = _run(rid)
    nmap = _store_map(run, _load(client, rid), "main")
    handle = _link(client, rid, nmap, chains=["C"])
    stored = canonical_json(run.store.load(handle)).decode()
    assert all(token in stored for token in tokens)                    # the result keeps them for the screen
    created = _report(client, rid, handle)
    manifest = canonical_json(created["manifest"]).decode()
    for text in (manifest, created["markdown"], _selected(client, rid, created["handle"]).text,
                 client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}).text,
                 client.get(f"/runs/{rid}/reports/download",
                            params={"handle": created["handle"], "format": "json"}).text):
        for token in tokens:
            assert token not in text, token
    assert "MOVE\\-0400" in created["markdown"]                       # the precedent itself is listed


# ------------------------------------------------------------------------------------------- template wording

def test_forbidden_words_are_refused_except_on_the_kp_and_kt1_lines():
    fixed = [*K.LIMITATIONS, K.STATEMENTS["KT1"]]
    text = "\n".join(["# x", *fixed, "ok", K.screen_note("UP2", 3), K.screen_note("UP5", 4),
                      K.SCREEN_NOTES["UP1"], K.SCREEN_NOTES["UP3"]])
    assert pr.check_no_interpretation(text) == text
    assert "성공률" in K.STATEMENTS["KP6"] and "추천" in K.STATEMENTS["KP6"]
    for bad in ("성공률", "검증됨", "신뢰", "효과", "승자", "success rate", "verified", "validated", "trusted",
                "reliable", "effect", "winner", "필수", "핵심", "중요한", "메커니즘이 유지된다", "활성", "안정성", "ΔΔG",
                "순위", "추천", "최적", "개선", "예측", "유망", "좋은", "나쁜", "안전", "점수", "에너지", "수소 결합",
                "결합", "기능", "essential", "key residue", "important", "critical", "binding", "activity", "score",
                "energy", "rank", "best", "recommended", "optimal", "improves", "predicted", "promising", "good",
                "safe", "hydrogen bond", "mechanism is preserved", "affinity", "selectivity", "potency", "inhibits"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            pr.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {K.STATEMENTS['KP6']}", K.STATEMENTS["KP6"] + " ", " " + K.STATEMENTS["KP6"],
                 K.STATEMENTS["KP6"][:-1]):   # only the exact fixed line is exempt
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            pr.check_no_interpretation(near)


def test_rendered_reports_pass_only_because_kbase_strings_are_slots(client, world):
    for key in ALL:
        assert _report(client, world["rid"], world[key])["markdown"]   # the template itself passed the check
    full = _report(client, world["rid"], world["included"])["markdown"]
    assert "potency" in full and "selectivity" in full and "hbond\\_engagement" in full   # kbase tag terms
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        pr.check_no_interpretation(full)                             # a whole-text check would refuse this report


def test_forbidden_words_inside_kbase_strings_do_not_fail_a_report(client, refdir):
    """SYNTHETIC records, reference and bibliography whose strings contain forbidden words: they are kbase strings
    (slots), copied verbatim; the template stays checked."""
    records = PF.t2_records()
    words = "SYNTHETIC 효과 검증됨 신뢰 승자 성공률 recommended best safe winner"
    moves = records["moves"] + [PF.make_move("MOVE-0500", uniprot="P0SYN1", variant="best-optimal-V1", pmid="90000010",
                                             site=["allosteric_non_atp"], goal=["safety_offtarget"],
                                             tactic=["salt_bridge_engagement"])]
    refs = records["references"] + [PF.make_reference("REF-SYN-0009", "P0SYN1", gene="SYN-PROMISING-ACTIVE")]
    pubmed = records["pubmed"] + [PF.make_pubmed_row("90000010", title=words, journal="Verified Effect Journal")]
    PF.build_set(refdir, moves=moves, references=refs, pubmed=pubmed)
    rid = _new_run(client)
    run = _run(rid)
    handle = _link(client, rid, _store_map(run, _load(client, rid), "main"), chains=["A"])
    created = _report(client, rid, handle)
    for text in (words, "best-optimal-V1", "SYN-PROMISING-ACTIVE", "Verified Effect Journal"):
        assert _md(text) in created["markdown"], text
    assert _selected(client, rid, created["handle"]).json()["markdown"] == created["markdown"]


def test_a_forbidden_word_seeded_into_the_template_is_caught(client, world):
    rid = world["rid"]
    log = _run(rid).run_dir / "events.jsonl"
    before = log.read_bytes()
    seeds = [(pr.STATUS_LABELS, "precedents_found", "포함한 파일에 효과 기록 있음"),
             (pr, "EVIDENCE_STATEMENT", "ProtView가 검증됨 표시를 셌다."),
             (pr.INTEGRITY_LABELS, "hash_verified", "신뢰 해시"),
             (pr.LOCATION_LABELS, "page", "승자 쪽")]
    for target, name, text in seeds:
        with pytest.MonkeyPatch.context() as patch:
            if isinstance(target, dict):
                patch.setitem(target, name, text)
            else:
                patch.setattr(target, name, text)
            response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["included"]})
            assert response.status_code == 422 and "interpretive_statement" in response.text, name
    assert log.read_bytes() == before                             # a refused report stores nothing
    assert _report(client, rid, world["included"])["markdown"]     # the unseeded template passes


def test_source_table_kt1_kp_lines_and_up5_are_always_present(client, world):
    for key in ALL:
        created = _report(client, world["rid"], world[key])
        manifest, markdown = created["manifest"], created["markdown"]
        lines = markdown.split("\n")
        assert K.STATEMENTS["KT1"] in lines and _md("kbase_kinase 가공본 · 미검수 · 기계 추출") in lines
        assert _note("UP5", 4) in lines
        kbase = PF.KBASE
        for label, value in (("세트 해시", world["set_hash"]), ("가져온 시각", PF.IMPORTED_AT),
                             ("kbase 커밋 (HEAD)", kbase["commit"]), ("dist 커밋", kbase["dist_commit"]),
                             ("dist 커밋 날짜", kbase["dist_commit_date"]), ("dirty", "false")):
            assert f"| {label} | {_md(value)} |" in lines, label
        for name in ("kb_version", "schema_version", "effect_rules_version", "vocab_version"):
            assert f"| {_md(name)} | {_md(kbase[name])} |" in lines, name
        rows = {"dist/moves.jsonl": 7, "dist/moves_flagged.jsonl": 6, "dist/references.jsonl": 6,
                f"pubmed/{PF.PUBMED_DATE}/documents.jsonl": 5}
        for name, count in rows.items():
            line = next(x for x in lines if x.startswith(f"| {_md(name)} | "))
            assert _cells(line)[1].strip() == str(count)
        snapshot = next(x for x in lines if x.startswith("| 서지 스냅샷 | "))
        assert _md(PF.PUBMED_DATE) in snapshot and _md(PF.BIBLIOGRAPHY["license"]) in snapshot
        limits = _section(markdown, "## Limitations", lines[-2])
        assert [line for line in limits if line in K.LIMITATIONS] == list(K.LIMITATIONS)
        assert manifest["limitations"] == list(K.LIMITATIONS)


def test_an_empty_result_states_its_lists_without_zero_claims(client, world):
    created = _report(client, world["rid"], world["empty"])
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["null_result"] is True and "- 이 결과는 유효한 빈 결과(scientific\\_null)이며 실패가 아니다." in markdown
    assert "- 표적: 빈 목록 ([]) — 연결한 체인이 없어 표적을 만들지 않았다." in markdown
    assert not [c for c in manifest["claims"] if re.match(r"targets\[\d+\]", c["field_path"])]
    assert _claim(manifest, "target_count")["exact_value"] == 0
    refs = _report(client, world["rid"], world["refs_excluded"])["markdown"]
    target = _section(refs, "## 표적 O0SYN5", "## 표적 P0SYN3")
    assert "- kbase 참조: 빈 목록 ([])" in target and "- 전례 출처 목록: 빈 목록 ([])" in target
    assert "- 변이 표기별 전례 수 (ProtView 계산): 빈 목록 ([])" in target


def test_the_300_line_cap_lists_the_first_records_and_counts_the_rest(client, refdir):
    """SYNTHETIC set: 305 more P0SYN1 records (MOVE-1000 ... MOVE-1304) on top of the T2 records."""
    records = PF.t2_records()
    extra = [PF.make_move(f"MOVE-{1000 + i}", uniprot="P0SYN1", variant=f"SYN-V{i % 3}") for i in range(305)]
    PF.build_set(refdir, moves=records["moves"] + extra)
    rid = _new_run(client)
    run = _run(rid)
    handle = _link(client, rid, _store_map(run, _load(client, rid), "main"), chains=["C"])
    content = run.store.load(handle)
    stored = content["targets"][0]["records"]
    assert len(stored) == 4 + 305
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    listed = [c["exact_value"] for c in _claims(manifest, "reference_record_id")]
    assert listed == [item["record"]["move_id"] for item in stored[:300]] and pr.LINE_CAP == 300
    assert _claim(manifest, "unlisted_record_count", accession="P0SYN1")["exact_value"] == 9
    assert not _claims(manifest, "reference_record_id", record_index=300)
    assert "- 이 보고서에 나열하지 않은 전례 (ProtView 계산): 9 (전체는 결과 객체에 있다)" in markdown
    assert sum(1 for line in markdown.split("\n") if line.startswith("| MOVE")) == 300
    assert _claim(manifest, "target_record_count", accession="P0SYN1", file="moves")["exact_value"] == 309
    assert sum(c["exact_value"] for c in _claims(manifest, "target_variant_count", accession="P0SYN1")) == 309
    assert _selected(client, rid, created["handle"]).json()["markdown"] == markdown


def test_a_bibliography_title_that_would_break_markdown_is_escaped(client, refdir):
    """SYNTHETIC bibliography row whose title holds table pipes, a newline + heading, a link, HTML and emphasis."""
    title = "SYNTHETIC | pipe | title\n# Injected heading [link](javascript:x) <script>x</script> *em* `c` > q"
    records = PF.t2_records()
    pubmed = [row for row in records["pubmed"] if row["id"] != "90000001"]
    pubmed.append(PF.make_pubmed_row("90000001", title=title, journal="SYN | journal\n## h2", doi="10.0000/syn|x"))
    PF.build_set(refdir, pubmed=pubmed)
    rid = _new_run(client)
    run = _run(rid)
    handle = _link(client, rid, _store_map(run, _load(client, rid), "main"), chains=["C"])
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    assert _claim(manifest, "reference_bibliography", "bibliography.90000001.title")["exact_value"] == title
    assert "<script>" not in markdown and "](javascript" not in markdown
    assert not [line for line in markdown.split("\n") if line.startswith(("# Injected", "## h2"))]
    rows = [line for line in markdown.split("\n") if line.startswith("| MOVE")]
    assert len(rows) == 4 and all(len(_cells(line)) == 11 for line in rows)   # the table keeps its 11 columns
    assert _md(title) in rows[0] and "\\|" in rows[0]
    assert _selected(client, rid, created["handle"]).json()["markdown"] == markdown


# ------------------------------------------------------------------------------------------- create / reopen

def test_create_reopen_list_and_download_round_trip(client, world):
    rid = world["rid"]
    created = _report(client, rid, world["included"])
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["snapshot"]["active_set_hash"] == world["set_hash"]
    assert set(manifest) == pr.MANIFEST_KEYS
    again = _selected(client, rid, created["handle"]).json()
    assert again["markdown"] == markdown and again["manifest"] == manifest
    assert pr.saved_precedent_report(_run(rid), created["handle"])["markdown"] == markdown
    listed = {row["handle"]: row for row in client.get(f"/runs/{rid}/reports").json()}
    assert listed[created["handle"]]["analysis_type"] == "kinase_precedents"
    assert listed[created["handle"]]["result_handle"] == world["included"]
    download = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]})
    assert download.status_code == 200 and download.content == markdown.encode()
    raw = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert raw.status_code == 200 and raw.content == canonical_json(manifest)


def test_the_same_input_gives_byte_identical_reports(client, world):
    rid = world["rid"]
    first = _report(client, rid, world["included"])
    second = _report(client, rid, world["included"])
    assert first["handle"] != second["handle"]                      # two report objects (their snapshots differ)
    assert first["markdown"].encode() == second["markdown"].encode()
    assert first["markdown_handle"] == second["markdown_handle"]
    strip = ("snapshot", "markdown_handle")
    assert canonical_json({k: v for k, v in first["manifest"].items() if k not in strip}) == \
        canonical_json({k: v for k, v in second["manifest"].items() if k not in strip})


def test_tampered_manifests_claims_and_markdown_are_refused_on_reopen(client, world):
    rid = world["rid"]
    run = _run(rid)
    created = _report(client, rid, world["excluded"])
    manifest, markdown = created["manifest"], created["markdown"]
    count = _claim(manifest, "target_record_count", accession="P0SYN1", file="moves")

    def flip_count(forged):
        next(c for c in forged["claims"] if c == count).update(exact_value=0, rendered_value="0")

    def swap_kind(forged):
        next(c for c in forged["claims"] if c == count).update(evidence_kind="reference_value")

    def drop_reference(forged):
        next(c for c in forged["claims"] if c["evidence_kind"] == "reference_value").update(
            evidence_kind="computed", reference=None)

    def add_flagged_zero(forged):
        forged["claims"].append({**count, "row_selector": {**count["row_selector"], "file": "moves_flagged"},
                                 "exact_value": 0, "rendered_value": "0"})

    forged = [
        # claims
        _forge(run, manifest, markdown, flip_count),
        _forge(run, manifest, markdown, swap_kind),
        _forge(run, manifest, markdown, drop_reference),
        _forge(run, manifest, markdown, add_flagged_zero),
        _forge(run, manifest, markdown, lambda f: f["claims"].pop()),
        # manifest fields
        _forge(run, manifest, markdown, lambda f: f["counts"]["records"].update(moves_flagged=0)),
        _forge(run, manifest, markdown, lambda f: f["target_sources"][0].update(excluded_flagged=0)),
        _forge(run, manifest, markdown, lambda f: f["target_sources"][0]["records"].pop()),
        _forge(run, manifest, markdown, lambda f: f["chains"][3].update(status="linked")),
        _forge(run, manifest, markdown, lambda f: f["limitations"].reverse()),
        _forge(run, manifest, markdown, lambda f: f["precedent_set"].update(set_hash="f" * 64)),
        _forge(run, manifest, markdown, lambda f: f.update(include_flagged=True)),
        _forge(run, manifest, markdown, lambda f: f.update(evidence_statement="ProtView가 판정했다.")),
        _forge(run, manifest, markdown, lambda f: f["snapshot"].update(active_set_hash="not-a-hash")),
        _forge(run, manifest, markdown, lambda f: f.update(result_handle=world["included"])),
        _forge(run, manifest, markdown, lambda f: f["structure"].update(handle=world["maps"]["main"])),
        # Markdown bytes
        _forge(run, manifest, markdown.replace("moves 4; moves\\_flagged 포함하지 않음", "moves 4; moves\\_flagged 0"),
               lambda _f: None),
        _forge(run, manifest, markdown.replace("- 표적 수: 2", "- 표적 수: 3"), lambda _f: None),
        _forge(run, manifest, markdown.replace("## Limitations", "이 전례는 검증됨.\n\n## Limitations"), lambda _f: None),
        _forge(run, manifest, markdown + "\n", lambda _f: None),
    ]
    for handle in forged:
        response = _selected(client, rid, handle)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == "report_evidence_invalid"
        assert client.get(f"/runs/{rid}/reports/download", params={"handle": handle}).status_code == 422
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
    for name in ("build_kinase_precedents", "chain_rows", "_assemble", "_target", "_item", "record_copy"):
        monkeypatch.setattr(kp, name, boom)
    before = list(run.events.read())
    created = _report(client, rid, world["included"])
    added = list(run.events.read())[len(before):]
    assert [e["type"] for e in added] == ["object_created", "object_created", "method_report_created"]
    assert [e.get("kind") for e in added[:2]] == ["report_markdown", "method_report_manifest"]
    log = run.run_dir / "events.jsonl"
    frozen = log.read_bytes()
    assert _selected(client, rid, created["handle"]).status_code == 200
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}).status_code == 200
    assert client.get(f"/runs/{rid}/reports/download",
                      params={"handle": created["handle"], "format": "json"}).status_code == 200
    assert client.get(f"/runs/{rid}/reports").status_code == 200
    assert log.read_bytes() == frozen and calls == []


def test_reports_reopen_from_events_only_without_the_reference_folder(client, world):
    rid = world["rid"]
    run = _run(rid)
    created = _report(client, rid, world["included"])
    shutil.rmtree(world["root"])
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    _app().RUNS.clear()   # reopen the run: objects come back from events.jsonl alone
    again = _selected(client, rid, created["handle"])
    assert again.status_code == 200 and again.json()["markdown"] == created["markdown"]


def test_a_result_of_an_older_set_reports_with_the_earlier_snapshot_wording(client, world):
    rid, first = world["rid"], world["set_hash"]
    same = _report(client, rid, world["excluded"])
    assert "- 결과의 세트가 보고서를 만들 때 사용 중이던 세트와 같다." in same["markdown"]
    assert "이전 스냅샷 기준" not in same["markdown"]
    second = PF.build_set(world["root"], imported_at="2026-10-10T00:00:07Z")
    older = _report(client, rid, world["excluded"])
    assert older["manifest"]["snapshot"]["active_set_hash"] == second != first
    assert older["manifest"]["precedent_set"]["set_hash"] == first          # the result is never recomputed
    assert ("- 이전 스냅샷 기준: 결과의 세트가 보고서를 만들 때 사용 중이던 세트와 다르다. 결과를 다시 계산하지 않았다."
            in older["markdown"])
    strip = ("snapshot", "markdown_handle")
    assert {k: v for k, v in older["manifest"].items() if k not in strip} == \
        {k: v for k, v in same["manifest"].items() if k not in strip}
    PF.activate(world["root"], first)
    assert _selected(client, rid, older["handle"]).json()["markdown"] == older["markdown"]   # recorded, not live
    shutil.rmtree(world["root"])
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    gone = _report(client, rid, world["excluded"])
    assert gone["manifest"]["snapshot"]["active_set_hash"] is None
    assert "- 사용 중 스냅샷 없음: 보고서를 만들 때 사용할 수 있는 전례 참조 세트가 없었다." in gone["markdown"]
    assert _selected(client, rid, older["handle"]).json()["markdown"] == older["markdown"]
    with pytest.raises(EvidenceError, match="active_set_invalid"):
        pr.build_precedent_report(_run(rid), world["excluded"], active_set_hash="abc")


# ------------------------------------------------------------------------------------------- other evidence

def test_evidence_of_another_run_kind_or_an_unproduced_result_is_refused(client, world):
    rid = world["rid"]
    run = _run(rid)
    other_rid = _new_run(client)
    other_run = _run(other_rid)
    other = _link(client, other_rid, _store_map(other_run, _load(client, other_rid), "main"))
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": other})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"
    with pytest.raises(EvidenceError, match="other_run"):
        pr.validated_precedent_result(run, other)
    for wrong in (world["structure"], world["maps"]["main"]):   # another kind of this run
        response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": wrong})
        assert response.status_code == 422
    content = copy.deepcopy(run.store.load(world["excluded"]))
    content["pdb_id"] = "0SY7"                                 # a valid result shape that no tool produced
    with run._owner():
        orphan = run.store.put(K.KIND, K.SCHEMA, content, produced_by="forged_test_result").handle
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": orphan})
    assert response.status_code == 422 and "provenance" in response.text
    content = copy.deepcopy(run.store.load(world["excluded"]))
    content["counts"]["targets"] = 3
    with run._owner():
        bad = run.store.put(K.KIND, K.SCHEMA, content, produced_by="forged_test_result").handle
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": bad})
    assert response.status_code == 422 and "precedent_result_invalid" in response.text


def test_a_result_naming_another_structure_or_map_is_refused_even_with_provenance(client, world):
    rid = world["rid"]
    run = _run(rid)
    ubq = _load(client, rid, CIF_1UBQ)
    content = copy.deepcopy(run.store.load(world["excluded"]))
    content["structure"]["handle"] = ubq                       # another structure of this run; the map is 1MQ4's
    other_structure = _with_forged_provenance(run, content, "structure")
    with pytest.raises(EvidenceError, match="numbering_map_structure_mismatch"):
        pr.validated_precedent_result(run, other_structure)
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": other_structure})
    assert response.status_code == 422 and "structure_mismatch" in response.text
    content = copy.deepcopy(run.store.load(world["excluded"]))
    content["pdb_id"] = "0SY9"                                  # the map says 0SY5
    with pytest.raises(EvidenceError, match="numbering_map_pdb_mismatch"):
        pr.validated_precedent_result(run, _with_forged_provenance(run, content, "pdb"))
    content = copy.deepcopy(run.store.load(world["excluded"]))
    content["numbering_map"]["handle"] = world["structure"].replace("/structure/", "/residue_numbering_map/")
    with pytest.raises(EvidenceError):                          # a map handle that is no object of this run
        pr.validated_precedent_result(run, _with_forged_provenance(run, content, "map"))
    stranger = copy.deepcopy(run.store.load(world["excluded"]))
    stranger["structure"]["handle"] = "obj://run_someone_else/structure/" + "a" * 64
    with pytest.raises(EvidenceError):
        pr.validated_precedent_result(run, _with_forged_provenance(run, stranger, "stranger"))


# ------------------------------------------------------------------------------------------- module boundary

def test_the_report_module_reads_stored_evidence_only():
    source = Path(pr.__file__).read_text()
    for name in ("build_kinase_precedents", "chain_rows", "pin_and_index", "precedent_index", "pin_active_set",
                 "read_bytes", "reaction_knowledge_reports", "mutation_reports", "numbering_reports"):
        assert name not in source, name
    assert pr.LINE_CAP == K.REPORT_MAX_LINES_PER_TARGET == 300
    assert pr.REFERENCE_NOTE == NOTE
