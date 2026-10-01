"""M17 T5 ligand candidate report (``method_report_manifest@1``, ``analysis_type: "ligand_candidates"``,
``ligand_candidates_markdown@1``; spec 9).

Every candidate set here is real product output: labeled synthetic methacetin + block libraries through the pinned
RDKit worker (``ligand_job_fixture``). Missing environment -> these tests FAIL, never skip. No report value is copied
from the product: stored fields are re-resolved by path, ``count_where`` values are recounted here from the stored
rows with the test's own comparisons, numbers are rendered with an independent ``Decimal`` oracle, and the parent
properties are compared with the hand oracle in ``fixtures/ligand/expected.json``. Forged report manifests and edited
objects below are labeled test fabrications written only to prove that the validator rejects them.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import EXPECTED, run_job, standard_run

from mw import ligand_constants as C
from mw import ligand_reports as lr
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.reports import EvidenceError

PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")
FLOATS = {"mol_weight", "crippen_logp", "tpsa"}


def _oracle(value) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.2f}"


# ----------------------------------------------------------------- shared world (real jobs, built once)
@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("ligand_reports") / "runs"
    std = standard_run(root, "run_ligand_reports")
    run = std["run"]
    # Zero-candidate set: user_3 only matches the acetyl group outside the site (empty scientific result).
    empty = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": std["inspection"], "site_atoms": [11, 12],
                                                "use_fixed": False, "rule_ids": ["user_3"]})
    assert empty["status"] == "done", empty
    from mw import ligand_bundle
    with pytest.MonkeyPatch.context() as patch:   # labeled internal cap hook, never a request field
        patch.setattr(ligand_bundle, "ENUMERATE_LIMITS", {"max_candidates": 3, "max_attempts": C.MAX_ATTEMPTS})
        capped = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": std["inspection"], "site_atoms": [11, 12],
                                                     "use_fixed": True})
    assert capped["status"] == "done", capped
    return {**std, "root": root, "rid": "run_ligand_reports", "empty": empty["output_handles"][0],
            "capped": capped["output_handles"][0]}


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _run(world):
    return api_module._run(world["rid"])


def _report(client, world, handle=None, filters=None) -> dict:
    body = {"result_handle": handle or world["candidate_set"]}
    if filters is not None:
        body["filters"] = filters
    created = client.post(f"/runs/{world['rid']}/method_reports", json=body)
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


def _passes(row, name, bounds) -> bool:
    if name == "pains_exclude":
        return len(row["pains"]["matches"]) == 0
    value = row["properties"][name]
    low, high = bounds["min"], bounds["max"]
    return (low is None or low <= value) and (high is None or value <= high)


def _verify_independently(run, manifest) -> None:
    """Re-resolve every claim from the stored candidate set; recount every count_where; check the rendering."""
    handle = manifest["result_handle"]
    stored = run.store.load(handle)
    rows = stored["candidates"]
    spec = manifest["filter_spec"]
    seen = set()
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["field_path"], json.dumps(claim["row_selector"], sort_keys=True))
        assert key not in seen
        seen.add(key)
        assert claim["evidence_kind"] == "computed"
        assert claim["source_handle"] == handle and claim["source_sha256"] == handle.rsplit("/", 1)[-1]
        assert claim["source_kind"] == "ligand_candidate_set" and claim["source_schema"] == "ligand_candidate_set@1"
        statement, sel, value = claim["statement_id"], claim["row_selector"], claim["exact_value"]
        if statement == "pains_match_count":
            assert value == sum(1 for row in rows if row["pains"]["matches"])
        elif statement == "stereo_flag_count":
            assert value == sum(1 for row in rows if row["stereo_flag"] == sel["stereo_flag"])
        elif statement == "filter_pass_count":
            condition = sel["filter"]
            bounds = spec["ranges"].get(condition)
            assert condition == "pains_exclude" or sel == {"filter": condition, **bounds}
            assert value == sum(1 for row in rows if _passes(row, condition, bounds))
        elif statement == "filter_all_pass_count":
            assert sel == {"filter_spec": spec}
            names = [*spec["ranges"], *(["pains_exclude"] if spec["pains_exclude"] else [])]
            assert value == sum(1 for row in rows if all(_passes(row, n, spec["ranges"].get(n)) for n in names))
        else:
            assert "[*]" not in claim["field_path"]
            assert value == _resolve(stored, claim["field_path"])
        if claim["rounding"] == "property_2dp":
            assert claim["rendered_value"] == _oracle(value)
        elif claim["rounding"] == "integer":
            assert type(value) is int and claim["rendered_value"] == str(value)
    assert not [c for c in manifest["claims"] if c["field_path"] == "candidates"]  # never every row as evidence


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
                                        "analysis_type": "ligand_candidates", "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"],
                          snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _claim(manifest, statement, path=None, **selector):
    for claim in manifest["claims"]:
        if claim["statement_id"] != statement or (path is not None and claim["field_path"] != path):
            continue
        if all((claim["row_selector"] or {}).get(k) == v for k, v in selector.items()):
            return claim
    raise AssertionError((statement, path, selector))


def _selected(client, world, handle):
    return client.get(f"/runs/{world['rid']}/reports/selected", params={"handle": handle})


def _filters(world):
    stored = world["run"].store.load(world["candidate_set"])["candidates"]
    pivot = sorted(row["properties"]["mol_weight"] for row in stored)[5]
    return {"ranges": {"mol_weight": {"max": pivot}, "hbd": {"min": 1}}, "pains_exclude": True}


# ----------------------------------------------------------------- rendering and forbidden words
@pytest.mark.parametrize(("value", "text"), [
    (165.192, "165.19"), (2.675, "2.68"), (38.325, "38.33"), (38.33, "38.33"), (1.0, "1.00"), (-0.005, "-0.01"),
    (-0.004, "0.00"), (0.0, "0.00"), (12, "12.00"), (2.6949999, "2.69")])
def test_property_rendering_is_decimal_half_up(value, text):
    assert lr.render_property(value) == text == _oracle(value)
    assert round(2.675, 2) == 2.67   # the float rounding the rule forbids


def test_forbidden_words_with_the_five_fixed_limitation_lines_exempt():
    assert tuple(lr.LIMITATIONS) == C.LIMITATIONS
    text = "\n".join(["# x", *C.LIMITATIONS, "ok"])
    assert lr.check_no_interpretation(text) == text
    for bad in ("좋은 후보", "나쁜 후보", "약물 유사성 높음", "약물유사", "독성 없음", "안전한 후보", "활성 예상", "친화도",
                "억제제", "합성 가능", "최적 후보", "중요한 치환", "핵심 골격", "기능기", "결합 부위", "수소결합 2개",
                "drug-like", "druglike", "toxic", "safe candidate", "synthesizable", "optimal", "best candidate",
                "good candidate", "active analog", "activity", "binding", "affinity", "inhibitor", "important",
                "hydrogen bond", "H-bond"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            lr.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {C.LIMITATIONS[0]}", C.LIMITATIONS[1] + " 좋은", " " + C.LIMITATIONS[2]):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            lr.check_no_interpretation(near)


# ----------------------------------------------------------------- the correct report
def test_report_with_filters_round_trips_and_every_value_is_bound(client, world):
    run = _run(world)
    filters = _filters(world)
    events_before = len(list(run.events.read()))
    created = _report(client, world, filters=filters)
    events_after = list(run.events.read())
    # creating writes the report objects and one creation event; no job, tool or worker call
    added = events_after[events_before:]
    assert [e["type"] for e in added if e["type"] != "object_created"] == ["method_report_created"]
    assert {e.get("kind") for e in added if e["type"] == "object_created"} == {"report_markdown",
                                                                               "method_report_manifest"}
    manifest, markdown = created["manifest"], created["markdown"]
    assert manifest["schema"] == "method_report_manifest@1" and manifest["analysis_type"] == "ligand_candidates"
    assert manifest["render_version"] == "ligand_candidates_markdown@1" and manifest["status"] == "complete"
    assert manifest["generation_mode"] == "local_rules_no_egress"
    assert manifest["result_handle"] == world["candidate_set"] and manifest["inspection_handle"] == world["inspection"]
    assert manifest["filter_spec"] == {"ranges": {"mol_weight": {"min": None, "max": filters["ranges"]["mol_weight"]["max"]},
                                                  "hbd": {"min": 1, "max": None}}, "pains_exclude": True}
    assert manifest["limitations"] == list(C.LIMITATIONS) and manifest["null_result"] is False
    assert manifest["provenance"]["candidate_set"]["job_id"] == world["enumerate_job"]["job_id"]
    assert manifest["provenance"]["inspection"]["job_id"] == world["inspect_job"]["job_id"]
    assert "candidates" not in manifest
    _verify_independently(run, manifest)
    # parent properties against the hand oracle (fixtures/ligand/expected.json)
    oracle = EXPECTED["properties"]["parent_methacetin"]
    expected_text = {"mol_weight": _oracle(Decimal(oracle["mol_weight"]["value"])), "tpsa": oracle["tpsa"]["value"],
                     "hbd": str(oracle["hbd"]["value"]), "hba": str(oracle["hba"]["value"]),
                     "heavy_atoms": str(oracle["heavy_atoms"]["value"]),
                     "formal_charge": str(oracle["formal_charge"]["value"]),
                     "rotatable_bonds": str(oracle["rotatable_bonds_strict"]["value"])}
    for name, text in expected_text.items():
        claim = _claim(manifest, "parent_property", f"parent_properties.{name}")
        assert claim["rendered_value"] == text, name
        assert claim["unit"] == {"mol_weight": "Da", "tpsa": "A2"}.get(name, "count" if name in {
            "hbd", "hba", "rotatable_bonds", "heavy_atoms"} else "dimensionless")
        assert f"| {name.replace('_', chr(92) + '_')} | {text} |" in markdown
    # the fixed statements are all present
    stored = run.store.load(world["candidate_set"])
    for reason in C.PRODUCT_REJECT_REASONS:
        assert _claim(manifest, "rejected_count", f"counts.rejected.{reason}")["exact_value"] == \
            stored["counts"]["rejected"][reason]
    for rule in stored["rules_used"]:
        _claim(manifest, "not_applicable_count", f"counts.not_applicable.{rule['rule_id']}")
    texts = [c["exact_value"] for c in manifest["claims"] if c["statement_id"] == "rule_text"]
    assert texts == [rule["text"] for rule in stored["rules_used"] if rule["text"] is not None]
    assert _claim(manifest, "site_atoms", "site_atoms")["rendered_value"] == "11, 12"
    assert _claim(manifest, "limit_state", "limit_reached")["rendered_value"] == "false"
    assert _claim(manifest, "limit_state", "stop_reason")["rendered_value"] == "none (null)"
    for flag in C.STEREO_FLAGS:
        _claim(manifest, "stereo_flag_count", stereo_flag=flag)
    assert len([c for c in manifest["claims"] if c["statement_id"] == "filter_pass_count"]) == 3
    _claim(manifest, "filter_all_pass_count")
    for line in C.LIMITATIONS:
        assert f"\n{line}\n" in markdown
    assert "RDKit 추정값" in markdown
    # snapshot: event sequence, capability, budget
    snapshot = manifest["snapshot"]
    assert snapshot["event_seq"] == events_before and snapshot["capability"]["available"] is True
    assert snapshot["capability"]["pins"] == stored["method"] and set(snapshot["budget"]) >= {"expensive_calls"}
    # list / selected / download are byte-identical and write no event
    rid = world["rid"]
    events_before = len(list(run.events.read()))
    listed = client.get(f"/runs/{rid}/reports").json()
    assert type(listed) is list, listed
    entry = next(item for item in listed if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "ligand_candidates" and entry["result_handle"] == world["candidate_set"]
    selected = _selected(client, world, created["handle"])
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "markdown"})
    js = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") == run.store.load(created["markdown_handle"])
    assert js.content == canonical_json(manifest) == canonical_json(run.store.load(created["handle"]))
    assert len(list(run.events.read())) == events_before
    # a second report (other filter) is a new object; the first report's bytes do not change
    second = _report(client, world)
    assert second["handle"] != created["handle"]
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}).content == md.content
    assert client.get(f"/runs/{rid}/reports/download",
                      params={"handle": created["handle"], "format": "json"}).content == js.content


def test_report_without_filters_states_no_filter_result(client, world):
    created = _report(client, world)
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(_run(world), manifest)
    assert manifest["filter_spec"] == {"ranges": {}, "pains_exclude": False}
    assert not [c for c in manifest["claims"] if c["statement_id"].startswith("filter_")]
    assert "통과" not in markdown and "적용한 필터 없음" in markdown
    # explicit empty filters are the same normalized spec
    same = _report(client, world, filters={"ranges": {"tpsa": {"min": None, "max": None}}})
    assert same["manifest"]["filter_spec"] == manifest["filter_spec"]
    assert same["manifest"]["claims"] == manifest["claims"]


def test_zero_candidate_set_report_has_counts_only(client, world):
    created = _report(client, world, world["empty"], filters={"ranges": {"mol_weight": {"min": 100}}})
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(_run(world), manifest)
    assert manifest["null_result"] is True and manifest["counts"]["candidates"] == 0
    assert _claim(manifest, "candidate_count", "counts.candidates")["rendered_value"] == "0"
    assert _claim(manifest, "rejected_count", "counts.rejected.outside_site")["exact_value"] >= 1
    statements = {c["statement_id"] for c in manifest["claims"]}
    assert not statements & {"pains_match_count", "stereo_flag_count", "filter_pass_count", "filter_all_pass_count"}
    assert "scientific\\_null" in markdown and "후보 0개" in markdown
    assert [c["field_path"] for c in manifest["claims"] if c["statement_id"] == "not_applicable_count"] == [
        "counts.not_applicable.user_3"]


def test_capped_set_report_shows_the_limit(client, world):
    created = _report(client, world, world["capped"])
    manifest = created["manifest"]
    _verify_independently(_run(world), manifest)
    assert _claim(manifest, "limit_state", "limit_reached")["rendered_value"] == "true"
    assert _claim(manifest, "limit_state", "stop_reason")["rendered_value"] == "candidate_limit"
    assert _claim(manifest, "limit_state", "limits.max_candidates")["rendered_value"] == "3"
    assert _claim(manifest, "candidate_count", "counts.candidates")["rendered_value"] == "3"
    assert "candidate\\_limit" in created["markdown"]


# ----------------------------------------------------------------- rejections
def test_mixed_evidence_is_rejected(client, world):
    run = _run(world)
    handle = world["candidate_set"]
    created = _report(client, world, filters=_filters(world))
    manifest, markdown = created["manifest"], created["markdown"]
    weight = _claim(manifest, "parent_property", "parent_properties.mol_weight")
    pains = _claim(manifest, "pains_match_count")
    other = _report(client, world, world["capped"])["manifest"]
    other_count = _claim(other, "candidate_count", "counts.candidates")
    for claim in (weight, pains):
        assert lr.validate_ligand_claim(run, handle, manifest["filter_spec"], copy.deepcopy(claim)) == claim
    cases = [
        ("source_mismatch", other_count),   # another candidate set's count
        ("source_mismatch", {**weight, "source_handle": world["capped"]}),
        ("evidence_kind_mismatch", {**weight, "evidence_kind": "reference_value"}),
        ("field_rule", {**pains, "field_path": "parent_properties.tpsa"}),
        ("field_rule", {**weight, "field_path": "candidates[*].stereo_flag"}),
        ("field_rule", {**weight, "field_path": "inspection.parent.properties.mol_weight"}),
        ("statement_not_allowed", {**weight, "statement_id": "drug_likeness"}),
        ("source_kind_mismatch", {**weight, "source_kind": "ligand_inspection"}),
        ("binding_mismatch", {**weight, "quantity": "tpsa"}),
        ("binding_mismatch", {**weight, "unit": "A2"}),
    ]
    for reason, claim in cases:
        with pytest.raises(EvidenceError, match=reason):
            lr.validate_ligand_claim(run, handle, manifest["filter_spec"], claim)
    for reason, claim in cases:
        def mutate(forged, claim=claim):
            index = next(i for i, c in enumerate(forged["claims"]) if c == weight)
            forged["claims"][index] = claim
        forged = _forge(run, manifest, markdown, mutate)
        assert _selected(client, world, forged).status_code == 422, reason


def test_wrong_rounding_is_rejected(client, world):
    run = _run(world)
    created = _report(client, world)
    manifest = created["manifest"]
    weight = _claim(manifest, "parent_property", "parent_properties.mol_weight")
    assert weight["rounding"] == "property_2dp" and weight["rendered_value"] == "165.19"
    for wrong in ("165.2", "165.20", "165.192", "165.18", "165"):
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            lr.validate_ligand_claim(run, world["candidate_set"], manifest["filter_spec"],
                                     {**weight, "rendered_value": wrong})
    with pytest.raises(EvidenceError):
        lr.validate_ligand_claim(run, world["candidate_set"], manifest["filter_spec"],
                                 {**weight, "rounding": "integer", "rendered_value": "165"})
    hbd = _claim(manifest, "parent_property", "parent_properties.hbd")
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        lr.validate_ligand_claim(run, world["candidate_set"], manifest["filter_spec"],
                                 {**hbd, "rounding": "property_2dp", "rendered_value": "1.00"})
    forged = _forge(run, manifest, created["markdown"].replace("| 165.19 |", "| 165.20 |"),
                    lambda f: next(c for c in f["claims"] if c == weight).update(rendered_value="165.20"))
    assert _selected(client, world, forged).status_code == 422
    edited = _forge(run, manifest, created["markdown"].replace("| 165.19 |", "| 165.2 |"), lambda f: None)
    assert _selected(client, world, edited).status_code == 422


def test_interpretive_statements_are_rejected(client, world):
    run = _run(world)
    created = _report(client, world)
    manifest, markdown = created["manifest"], created["markdown"]
    tampered = _forge(run, manifest, markdown.replace("## Limitations", "후보 3은 약물 유사 후보다.\n\n## Limitations"),
                      lambda f: None)
    extra = _forge(run, manifest, markdown, lambda f: f["limitations"].append("PAINS 일치가 없어 안전하다."))
    judged = _forge(run, manifest, markdown, lambda f: f.update(evidence_statement="mol_weight가 최적이다."))
    for forged in (tampered, extra, judged):
        assert _selected(client, world, forged).status_code == 422
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        lr.render_ligand_report({**manifest, "limitations": [*manifest["limitations"], "좋은 후보"]})
    # forged report objects make the run's report list fail closed
    assert client.get(f"/runs/{world['rid']}/reports").status_code == 422


def test_uncomputed_values_written_as_zero_are_rejected(client, world):
    run = _run(world)
    created = _report(client, world, world["empty"])
    manifest, markdown = created["manifest"], created["markdown"]
    spec = manifest["filter_spec"]
    count = _claim(manifest, "candidate_count", "counts.candidates")
    na = _claim(manifest, "not_applicable_count", "counts.not_applicable.user_3")
    zero_claims = {
        "pains": {**count, "statement_id": "pains_match_count", "field_path": "candidates[*].pains.matches",
                  "quantity": "pains_match_candidates", "operation": "count_where(len(pains.matches) > 0)"},
        "stereo": {**count, "statement_id": "stereo_flag_count", "field_path": "candidates[*].stereo_flag",
                   "row_selector": {"stereo_flag": "none"}},
        "filter": {**count, "statement_id": "filter_pass_count", "field_path": "candidates[*].properties.tpsa",
                   "row_selector": {"filter": "tpsa", "min": 0, "max": None}},
        "unused_rule": {**na, "field_path": "counts.not_applicable.user_2", "row_selector": {"rule_id": "user_2"}},
    }
    for name, claim in zero_claims.items():
        with pytest.raises(EvidenceError, match="field_not_allowed"):
            lr.validate_ligand_claim(run, world["empty"], spec, claim)
        forged = _forge(run, manifest, markdown, lambda f, claim=claim: f["claims"].append(claim))
        assert _selected(client, world, forged).status_code == 422, name
    # an inactive filter's pass count on a set with candidates is not a statement either
    full = _report(client, world)["manifest"]
    with pytest.raises(EvidenceError, match="field_not_allowed"):
        lr.validate_ligand_claim(run, world["candidate_set"], full["filter_spec"],
                                 {**_claim(full, "pains_match_count"), "statement_id": "filter_pass_count",
                                  "row_selector": {"filter": "pains_exclude"}})


def test_count_where_is_recomputed_from_stored_rows(client, world):
    run = _run(world)
    created = _report(client, world, filters=_filters(world))
    manifest, markdown = created["manifest"], created["markdown"]
    spec = manifest["filter_spec"]
    stored = run.store.load(world["candidate_set"])
    assert lr.claims_for(world["candidate_set"], stored, spec) == manifest["claims"]
    # LABELED TEST FABRICATION (in memory): one stored row's mol_weight moved across the max bound
    edited = copy.deepcopy(stored)
    bound = spec["ranges"]["mol_weight"]["max"]
    index = next(i for i, row in enumerate(edited["candidates"]) if row["properties"]["mol_weight"] <= bound)
    edited["candidates"][index]["properties"]["mol_weight"] = bound + 1.0
    claim = _claim(manifest, "filter_pass_count", filter="mol_weight")
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        lr.match_claim(lr.claims_for(world["candidate_set"], edited, spec), claim)
    # a stored row's PAINS match list edited in memory changes the PAINS count
    edited = copy.deepcopy(stored)
    edited["candidates"][0]["pains"]["matches"] = [] if stored["candidates"][0]["pains"]["matches"] else [
        {"catalog": "PAINS_A", "name": "test_fabrication"}]
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        lr.match_claim(lr.claims_for(world["candidate_set"], edited, spec), _claim(manifest, "pains_match_count"))
    # a saved report whose count_where value differs from the recount is refused
    def bump(forged):
        target = next(c for c in forged["claims"] if c == claim)
        target.update(exact_value=claim["exact_value"] + 1, rendered_value=str(claim["exact_value"] + 1))
    forged = _forge(run, manifest, markdown, bump)
    assert _selected(client, world, forged).status_code == 422
    # a saved report whose recorded condition differs from its filter spec is refused
    widened = _forge(run, manifest, markdown, lambda f: next(c for c in f["claims"] if c == claim)[
        "row_selector"].update(max=bound + 100))
    assert _selected(client, world, widened).status_code == 422
    # a filter spec that is not in normalized form is refused
    raw = _forge(run, manifest, markdown, lambda f: f["filter_spec"]["ranges"].update(tpsa={"min": None, "max": None}))
    assert _selected(client, world, raw).status_code == 422


def test_reopen_rejects_tampered_objects(world, monkeypatch, tmp_path):
    """A copy of the run whose stored candidate set bytes were edited in place (labeled fault injection)."""
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    created = _report(client, world, filters=_filters(world))
    api_module.RUNS.clear()
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / world["rid"], root / world["rid"])
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = world["rid"]
    assert _selected(client, world, created["handle"]).status_code == 200
    path = root / rid / "objects" / f"{world['candidate_set'].rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["candidates"][0]["properties"]["mol_weight"] = 1.0
    path.write_bytes(canonical_json(content))
    for response in (_selected(client, world, created["handle"]),
                     client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}),
                     client.get(f"/runs/{rid}/reports/download",
                                params={"handle": created["handle"], "format": "json"})):
        assert response.status_code == 422
    # no new report is made from the edited object either
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["candidate_set"]})
    assert response.status_code == 422


def test_unpublished_or_wrong_kind_sources_and_bad_filters_are_refused(client, world):
    run = _run(world)
    # LABELED TEST FABRICATION: a candidate set object that no enumeration job published
    content = copy.deepcopy(run.store.load(world["candidate_set"]))
    content["candidates"] = list(reversed(content["candidates"]))
    with run._owner():
        forged = run.store.put("ligand_candidate_set", "ligand_candidate_set@1", content,
                               produced_by="forged_test_candidate_set")
    rid = world["rid"]
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": forged.handle})
    assert response.status_code == 422 and "ligand_candidate_set_invalid" in response.text
    for filters, status in (({"ranges": {"density": {"min": 1}}}, 422), ({"ranges": {"tpsa": {"min": 5, "max": 1}}}, 422),
                            ({"ranges": {"tpsa": {"min": "1"}}}, 422), ({"pains_exclude": "yes"}, 422),
                            ({"other": 1}, 422)):
        response = client.post(f"/runs/{rid}/method_reports",
                               json={"result_handle": world["candidate_set"], "filters": filters})
        assert response.status_code == status, (filters, response.text)
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["inspection"], "filters": {}})
    assert response.status_code == 422 and "filters" in response.text
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["inspection"]})
    assert response.status_code == 422


def test_report_module_reads_only_stored_evidence():
    import ast
    source = Path(lr.__file__).read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name == "rdkit" or name.startswith("rdkit.") for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "JobQueue", ".submit(", "stage(",
                      "query_candidates("):
        assert forbidden not in source
