"""M22 T5: the ligand GA design report (``method_report_manifest@1``, ``analysis_type: "ligand_ga"``,
``ligand_ga_markdown@1``; spec .dryforge/spec.md 4, 5, 8).

The world is real product output (``ligand_ga_fixture``: real M17 jobs and real GA jobs with the pinned GA worker and
qvina2; a missing environment FAILS, never skips). No report value is copied from the product: every claim is
re-resolved by path in the stored summary and in the stored individual result, counts are recounted here, and scores
are rendered with an independent ``Decimal`` oracle. Forged report manifests, edited objects and the one edited
summary dict handed to the pure claim builder are labeled test fabrications written only to prove the validator
rejects them.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ligand_ga_fixture import RID, build_world

from mw import docking_bundle
from mw import docking_constants as C
from mw import ligand_ga_constants as GC
from mw import ligand_ga_jobs as LJ
from mw import ligand_ga_reports as gr
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError

PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")
ORIGIN = {"initial": "초기", "carried": "다음 세대로 이어받음", "similar": "유사", "random": "무작위"}
EVALUATION = {"reused": "재사용", "docked": "새 도킹", None: ""}


def _score(value) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.1f}"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("m22_reports") / "runs")


@pytest.fixture
def client(world, monkeypatch, tmp_path):
    """A function-scoped copy of the shared run (forged reports make the list fail; reports add objects)."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / RID, root / RID)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    yield TestClient(api_module.app, base_url="http://127.0.0.1")
    api_module.RUNS.clear()


def _run():
    return api_module._run(RID)


def _events() -> list[dict]:
    return list(_run().events.read())


def _report(client, world, name: str) -> dict:
    created = client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["handles"][name]})
    assert created.status_code == 201, created.text
    return created.json()


def _selected(client, handle):
    return client.get(f"/runs/{RID}/reports/selected", params={"handle": handle})


def _resolve(document, path):
    value = document
    for part in path.split("."):
        match = PATH_PART.fullmatch(part)
        assert match, path
        value = value[match.group(1)]
        if match.group(2) is not None:
            value = value[int(match.group(2))]
    return value


def _claim(manifest, statement, path=None, **selector):
    found = [claim for claim in manifest["claims"] if claim["statement_id"] == statement and
             (path is None or claim["field_path"] == path) and
             all((claim["row_selector"] or {}).get(k) == v for k, v in selector.items())]
    assert len(found) == 1, (statement, path, selector, len(found))
    return found[0]


def _slots(summary):
    return [(gen["index"], position, entry) for gen in summary["generations"]
            for position, entry in enumerate(gen["individuals"])]


def _verify_independently(world, name: str, manifest) -> None:
    """Re-resolve every claim from the stored summary or individual result; recount; check every rendering."""
    handle = world["handles"][name]
    summary = world["stored"][name]
    run = _run()
    assert manifest["result_handle"] == handle and manifest["result_sha256"] == handle.rsplit("/", 1)[-1]
    seen = set()
    evaluated = [e for _g, _p, e in _slots(summary) if e["origin"] != "carried"]
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["source_handle"], claim["field_path"],
               json.dumps(claim["row_selector"], sort_keys=True))
        assert key not in seen
        seen.add(key)
        assert claim["evidence_kind"] == "computed"
        assert claim["source_sha256"] == claim["source_handle"].rsplit("/", 1)[-1]
        statement, value, path = claim["statement_id"], claim["exact_value"], claim["field_path"]
        selector = claim["row_selector"] or {}
        if statement == "individual_result_score":
            entry = summary["generations"][selector["generation"] - 1]["individuals"][selector["position"]]
            assert entry["state"] == "scored" and claim["source_handle"] == entry["result_handle"]
            assert (claim["source_kind"], claim["source_schema"]) == ("docking_result", "docking_result@1")
            assert path == "modes[0].score_kcal_mol"
            assert value == run.store.load(entry["result_handle"])["modes"][0]["score_kcal_mol"] == entry["score"]
        else:
            assert claim["source_handle"] == handle
            assert (claim["source_kind"], claim["source_schema"]) == ("ligand_ga_result", "ligand_ga_result@1")
        if statement == "run_count":
            expected = {"generations_done": sum(g["complete"] for g in summary["generations"]),
                        "new_dockings_used": sum(e["evaluation"] == "docked" for e in evaluated),
                        "reused_count": sum(e["evaluation"] == "reused" for e in evaluated),
                        "reserved_units": summary["reserved_units"]}[path]
            assert value == expected == summary[path]
        elif statement == "generation_count":
            individuals = _resolve(summary, path)
            where = selector["where"]
            expected = len(individuals) if where is None else sum(
                f"state == {e['state']}" == where for e in individuals)
            assert value == expected
        elif statement == "individual_score":
            entry = summary["generations"][selector["generation"] - 1]["individuals"][selector["position"]]
            assert entry["state"] == "scored" and value == _resolve(summary, path) == entry["score"]
        elif statement == "generation_score_range":
            gen = summary["generations"][selector["generation"] - 1]
            scores = [run.store.load(e["result_handle"])["modes"][0]["score_kcal_mol"]
                      for e in gen["individuals"] if e["state"] == "scored"]
            assert value == _resolve(summary, path) == (min(scores) if path.endswith("min_score") else max(scores))
        elif statement != "individual_result_score":
            assert value == _resolve(summary, path)
        if claim["rounding"] == "score_1dp":
            assert claim["rendered_value"] == _score(value) and claim["unit"] == "kcal/mol"
    scored = sorted((g, p) for g, p, e in _slots(summary) if e["state"] == "scored")
    for statement in ("individual_score", "individual_result_score"):
        assert sorted((c["row_selector"]["generation"], c["row_selector"]["position"]) for c in manifest["claims"]
                      if c["statement_id"] == statement) == scored


def _table_row(manifest, position, entry) -> str:
    scored = entry["state"] == "scored"
    cells = [str(position), gr._md(entry["candidate_id"]), ORIGIN[entry["origin"]],
             "" if entry["parent_candidate_id"] is None else gr._md(entry["parent_candidate_id"]),
             "" if entry["similarity"] is None else gr._md(entry["similarity"]), EVALUATION[entry["evaluation"]],
             "" if entry["eval_index"] is None else str(entry["eval_index"]), gr._md(entry["state"]),
             _score(entry["score"]) if scored else "", GC.SCORE_ROW_LABEL if scored else "",
             "" if entry["reason_code"] is None else gr._md(entry["reason_code"]),
             "" if entry["result_handle"] is None else gr._md(entry["result_handle"])]
    return "| " + " | ".join(cells) + " |"


# ----------------------------------------------------------------- rendering and forbidden words
@pytest.mark.parametrize(("value", "text"), [(-5.25, "-5.3"), (-5.24999, "-5.2"), (-0.04, "0.0"), (-13.6, "-13.6"),
                                             (-12.32139, "-12.3"), (-7.05, "-7.1"), (-6.35, "-6.4")])
def test_score_rendering_is_one_decimal_half_up(value, text):
    assert gr.render_score(value) == text == _score(value)


def test_forbidden_words_with_fixed_sentence_and_neutral_label_exemptions():
    assert "순위" in GC.STATEMENTS["G1"] and "추천" in GC.STATEMENTS["G1"]
    text = "\n".join(["# x", *GC.STATEMENTS.values(), f"- 점수 이름: {C.SCORE_LABEL}", C.SCORE_COLUMN_LABEL,
                      GC.SCORE_ROW_LABEL, *ORIGIN.values(), *EVALUATION.values(), gr.NO_CHANGE_LABEL,
                      "- 점수 최솟값 -7.1, 최댓값 -5.3 (값만)", "ok"])
    assert gr.check_no_interpretation(text) == text
    for bad in ("순위 1", "best", "Best individual", "개선", "최고 점수", "최적 후보", "결합 강도", "rank 1",
                "improved", "stronger", "친화도", "affinity", "binding", "좋은 후보", "활성", "수소결합", "승자",
                "winner", "the winner", "평균 점수", "average score", "mean score", "추천 후보", "recommended",
                "우수한 개체", "상위 개체", "점수 향상", "better", "worse", "superior", "fittest"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            gr.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {GC.STATEMENTS['G1']}", GC.STATEMENTS["G1"] + " ", " " + GC.STATEMENTS["G1"],
                 GC.STATEMENTS["G1"].replace("아니다", "이다"), f"- 점수 이름: {C.SCORE_LABEL} best",
                 f"{C.SCORE_LABEL} 순위 1", "다음 세대로 이어받음 (최고)"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            gr.check_no_interpretation(near)


# ----------------------------------------------------------------- correct reports
def test_complete_report_round_trips_and_every_score_traces_to_both_objects(client, world, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("a GA report must never dock, stage or start a job")

    for target, name in ((JobQueue, "_supervise"), (JobQueue, "submit"), (JobQueue, "start"),
                         (docking_bundle, "stage"), (LJ, "stage"), (LJ, "finish")):
        monkeypatch.setattr(target, name, forbidden)
    before = _events()
    created = _report(client, world, "complete")
    added = _events()[len(before):]
    assert [e["type"] for e in added if e["type"] != "object_created"] == ["method_report_created"]
    assert {e.get("kind") for e in added if e["type"] == "object_created"} == {"report_markdown",
                                                                               "method_report_manifest"}
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["complete"]
    assert manifest["schema"] == "method_report_manifest@1" and manifest["analysis_type"] == "ligand_ga"
    assert manifest["render_version"] == "ligand_ga_markdown@1" and manifest["status"] == "complete"
    assert manifest["generation_mode"] == "local_rules_no_egress" and manifest["result_schema"] == "ligand_ga_result@1"
    assert manifest["ga_status"] == stored["status"] == "complete" and manifest["method"] == C.METHODS["free"]
    for key in ("protocol", "engine", "candidate_set_handle", "parent_sdf_handle", "receptor", "pins", "call_key",
                "selection_sha256", "box", "parameters", "filter", "ga", "pool", "stop_reason", "generations_done",
                "new_dockings_used", "reused_count", "reserved_units", "generations"):
        assert manifest[key] == stored[key], key
    assert manifest["limitation_ids"] == stored["limitations"] == ["G1", "G3"]
    assert manifest["limitations"] == [GC.STATEMENTS["G1"], GC.STATEMENTS["G3"]]
    assert manifest["score_label"] == C.SCORE_LABEL and manifest["score_row_label"] == "모드 1(엔진 출력 순서)"
    assert manifest["provenance"]["ligand_ga"]["job_id"] == world["jobs"]["complete"]["job_id"]
    assert manifest["provenance"]["ligand_ga"]["protocol_id"] == GC.PROTOCOL
    handles = list(dict.fromkeys(e["result_handle"] for _g, _p, e in _slots(stored) if e["result_handle"]))
    assert [item["result_handle"] for item in manifest["provenance"]["individuals"]] == handles
    reused = {e["result_handle"] for _g, _p, e in _slots(stored) if e["evaluation"] == "reused"}
    for item in manifest["provenance"]["individuals"]:   # a reused individual keeps its first producer
        if item["result_handle"] in reused:
            assert item["job_id"] == world["jobs"]["partial"]["job_id"]
    assert "pose_sdf" not in json.dumps(manifest) and "contacts" not in json.dumps(manifest)
    _verify_independently(world, "complete", manifest)
    for gen in stored["generations"]:
        for position, entry in enumerate(gen["individuals"]):
            assert f"\n{_table_row(manifest, position, entry)}\n" in markdown
    assert any(e["origin"] == "carried" for _g, _p, e in _slots(stored)) and "| 다음 세대로 이어받음 |" in markdown
    assert f"\n- 점수 이름: {C.SCORE_LABEL}\n" in markdown and f"| {C.SCORE_COLUMN_LABEL} |" in markdown
    for line in manifest["limitations"]:
        assert f"\n{line}\n" in markdown
    assert GC.STATEMENTS["G2"] not in markdown
    assert gr.check_no_interpretation(markdown) == markdown
    # list / selected / download are byte-identical, write no event and never re-dock
    run = _run()
    before = len(_events())
    listed = client.get(f"/runs/{RID}/reports")
    assert listed.status_code == 200, listed.text
    entry = next(item for item in listed.json() if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "ligand_ga" and entry["result_handle"] == world["handles"]["complete"]
    selected = _selected(client, created["handle"])
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"], "format": "markdown"})
    js = client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") == run.store.load(created["markdown_handle"])
    assert js.content == canonical_json(manifest) == canonical_json(run.store.load(created["handle"]))
    assert len(_events()) == before
    assert len([e for e in _events() if e["type"] == "method_report_created"]) == 1   # no per-individual report


def test_partial_report_carries_g2_and_has_no_claim_for_uncomputed_slots(client, world):
    created = _report(client, world, "partial")
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["partial"]
    _verify_independently(world, "partial", manifest)
    assert manifest["ga_status"] == "partial" and manifest["stop_reason"] == "docking_limit"
    assert manifest["limitations"] == [GC.STATEMENTS["G1"], GC.STATEMENTS["G2"]]
    last = stored["generations"][-1]
    assert last["complete"] is False and "중간에 멈춤" in markdown
    size = len(last["individuals"])
    assert size < stored["ga"]["population_size"]
    assert _claim(manifest, "generation_count", generation=last["index"], where=None)["exact_value"] == size
    assert _claim(manifest, "run_count", "new_dockings_used")["exact_value"] == stored["reserved_units"] == 4
    assert "종료 이유 docking\\_limit" in markdown


def test_score_claims_for_individuals_without_a_score_are_rejected(client, world):
    created = _report(client, world, "partial")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["partial"]
    stored = world["stored"]["partial"]
    run = _run()
    last = stored["generations"][-1]
    number, missing = last["index"], len(last["individuals"])   # never computed: no individual at this slot
    score = _claim(manifest, "individual_score", generation=1, position=0)
    result_score = _claim(manifest, "individual_result_score", generation=1, position=0)
    assert gr.validate_ligand_ga_claim(run, handle, copy.deepcopy(score)) == score
    cases = [{**score, "field_path": f"generations[{number - 1}].individuals[{missing}].score",
              "row_selector": {"generation": number, "position": missing}, "exact_value": 0.0,
              "rendered_value": "0.0"},
             {**result_score, "row_selector": {"generation": number, "position": missing}, "exact_value": 0.0,
              "rendered_value": "0.0"}]
    for claim in cases:
        with pytest.raises(EvidenceError, match="field_not_allowed"):
            gr.validate_ligand_ga_claim(run, handle, claim)
        forged = _forge(manifest, markdown, lambda f, claim=claim: f["claims"].append(claim))
        assert _selected(client, forged).status_code == 422
    # LABELED TEST FABRICATION (pure builder input, never stored): the same summary with one individual made
    # score-less; its score claims disappear and a score claim for it is refused.
    content = copy.deepcopy(stored)
    results = {e["result_handle"]: docking_bundle.validated_result(run, e["result_handle"])
               for _g, _p, e in _slots(content) if e["result_handle"]}
    first = content["generations"][0]
    first["individuals"][0].update(state="failed", reason_code="worker_failed", score=None, result_handle=None)
    kept = [results[e["result_handle"]]["modes"][0]["score_kcal_mol"] for e in first["individuals"]
            if e["state"] == "scored"]
    first.update(min_score=min(kept), max_score=max(kept))
    if len(content["generations"]) > 1:   # keep only generation 1 so no carried copy of the edited one remains
        content["generations"] = content["generations"][:1]
    rebuilt = gr.claims_for(handle, content, results)
    assert not [c for c in rebuilt if c["row_selector"] == {"generation": 1, "position": 0}]
    for claim in (score, result_score):   # no claim at that slot (its result may be cited nowhere else)
        with pytest.raises(EvidenceError, match="field_not_allowed|source_mismatch"):
            gr.match_claim(rebuilt, claim)
    counted = next(c for c in rebuilt if c["row_selector"] == {"generation": 1, "where": "state == failed"})
    assert counted["exact_value"] == 1 and counted["operation"].startswith("count_where(state == failed;")
    forged = _forge(manifest, markdown, lambda f: f["generations"][0]["individuals"][0].update(score=0.0))
    assert _selected(client, forged).status_code == 422


def _forge(manifest: dict, markdown: str, mutate) -> str:
    """LABELED TEST FABRICATION: store a tampered report manifest and its creation event."""
    run = _run()
    forged = copy.deepcopy(manifest)
    mutate(forged)
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by="forged_test_report", summary={"result_handle": manifest["result_handle"]})
        forged["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_test_report",
                               summary={"result_handle": manifest["result_handle"], "analysis_type": "ligand_ga",
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=manifest["result_handle"], snapshot_event_seq=manifest["snapshot"]["event_seq"])
    return report.handle


# ----------------------------------------------------------------- rejections
def test_mixed_evidence_and_other_statement_fields_are_rejected(client, world):
    complete = _report(client, world, "complete")
    partial = _report(client, world, "partial")["manifest"]
    manifest, markdown = complete["manifest"], complete["markdown"]
    handle = world["handles"]["complete"]
    run = _run()
    score = _claim(manifest, "individual_score", generation=1, position=0)
    result_score = _claim(manifest, "individual_result_score", generation=1, position=0)
    other = next(e["result_handle"] for _g, _p, e in _slots(world["stored"]["complete"])
                 if e["result_handle"] and e["result_handle"] != result_score["source_handle"])
    cases = [
        ("source_mismatch", _claim(partial, "individual_score", generation=1, position=0)),   # another GA
        # another individual's result of this GA, cited for this slot
        ("field_not_allowed", {**result_score, "source_handle": other, "source_sha256": other.rsplit("/", 1)[-1]}),
        ("source_mismatch", {**score, "source_sha256": "0" * 64}),
        ("evidence_kind_mismatch", {**score, "evidence_kind": "reference_value"}),
        ("field_rule", {**score, "field_path": "modes[0].score_kcal_mol"}),
        ("field_rule", {**result_score, "field_path": "modes[1].score_kcal_mol"}),
        ("field_rule", {**score, "field_path": "generations[0].individuals[0].similarity"}),
        ("field_rule", {**score, "field_path": "generations[0].individuals[0].score_difference"}),
        ("statement_not_allowed", {**score, "statement_id": "binding_affinity"}),
        ("statement_not_allowed", {**score, "statement_id": "individual_rank"}),
        ("statement_not_allowed", {**score, "statement_id": "generation_score_average"}),
        ("statement_not_allowed", {**score, "statement_id": "best_individual"}),
        ("source_kind_mismatch", {**score, "source_kind": "docking_result", "source_schema": "docking_result@1"}),
        ("source_kind_mismatch", {**result_score, "source_kind": "ligand_ga_result",
                                  "source_schema": "ligand_ga_result@1"}),
        ("binding_mismatch", {**score, "quantity": "affinity_kcal_mol"}),
        ("binding_mismatch", {**score, "unit": "kJ/mol"}),
        ("binding_mismatch", {**score, "operation": "min(generations[0].individuals[*].score)"}),
        ("binding_mismatch", {**score, "subject": {**score["subject"], "candidate_id": "c_0000000000000000"}}),
        ("field_not_allowed", {**score, "row_selector": {"generation": 1, "position": 99}}),
    ]
    for reason, claim in cases:
        with pytest.raises(EvidenceError, match=reason):
            gr.validate_ligand_ga_claim(run, handle, claim)
    for reason, claim in cases:
        def mutate(forged, claim=claim):
            index = next(i for i, c in enumerate(forged["claims"]) if c == score)
            forged["claims"][index] = claim
        assert _selected(client, _forge(manifest, markdown, mutate)).status_code == 422, reason
    mixed = _forge(manifest, markdown, lambda f: f["claims"].append(
        _claim(partial, "individual_score", generation=1, position=0)))
    assert _selected(client, mixed).status_code == 422
    swapped = _forge(manifest, markdown, lambda f: f.update(stop_reason="no_change"))
    assert _selected(client, swapped).status_code == 422


def test_wrong_rounding_is_rejected(client, world):
    created = _report(client, world, "complete")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["complete"]
    run = _run()
    for statement, selector in (("individual_score", {"generation": 1, "position": 0}),
                                ("individual_result_score", {"generation": 1, "position": 0}),
                                ("generation_score_range", {"generation": 1})):
        claim = next(c for c in manifest["claims"] if c["statement_id"] == statement and
                     c["row_selector"] == selector)
        exact = claim["exact_value"]
        good = _score(exact)
        for wrong in {f"{Decimal(str(exact)):.2f}", repr(exact), good + "0", str(int(exact)),
                      f"{float(good) - 0.1:.1f}", f"{float(good) + 0.1:.1f}"} - {good}:
            with pytest.raises(EvidenceError, match="binding_mismatch"):
                gr.validate_ligand_ga_claim(run, handle, {**claim, "rendered_value": wrong})
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            gr.validate_ligand_ga_claim(run, handle, {**claim, "rounding": "distance_2dp",
                                                      "rendered_value": f"{Decimal(str(exact)):.2f}"})
    count = _claim(manifest, "run_count", "new_dockings_used")
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        gr.validate_ligand_ga_claim(run, handle, {**count, "exact_value": count["exact_value"] + 1,
                                                  "rendered_value": str(count["exact_value"] + 1)})
    fraction = _claim(manifest, "ga_parameter", "ga.random_fraction")
    assert fraction["rendered_value"] == "0.25"
    score = _claim(manifest, "individual_score", generation=1, position=0)
    forged = _forge(manifest, markdown, lambda f: next(c for c in f["claims"] if c == score).update(
        rendered_value=f"{score['exact_value']:.2f}"))
    assert _selected(client, forged).status_code == 422
    entry = world["stored"]["complete"]["generations"][0]["individuals"][0]
    line = _table_row(manifest, 0, entry)
    edited = _forge(manifest, markdown.replace(line, line.replace(f"| {_score(entry['score'])} |",
                                                                  f"| {entry['score']:.2f} |")), lambda f: None)
    assert line in markdown and _selected(client, edited).status_code == 422


def test_interpretive_statements_and_missing_fields_are_rejected(client, world):
    created = _report(client, world, "complete")
    manifest, markdown = created["manifest"], created["markdown"]
    forged = [_forge(manifest, markdown.replace("## Limitations", f"{word}\n\n## Limitations"), lambda f: None)
              for word in ("개체 1이 best 후보다.", "세대 2의 순위가 가장 높다.", "부모 대비 개선되었다.", "이 개체가 승자다.",
                           "세대 평균 점수가 낮아졌다.", "추천 후보.", "결합 강도가 크다.")]
    forged += [
        _forge(manifest, markdown, lambda f: f["limitations"].append("점수가 낮아 순위가 높다.")),
        _forge(manifest, markdown, lambda f: f.update(evidence_statement="개체 1이 최고다.")),
        _forge(manifest, markdown, lambda f: f.update(score_label="qvina 점수(kcal/mol, 결합 친화도)")),
        _forge(manifest, markdown, lambda f: f.update(score_row_label="best 모드")),
        _forge(manifest, markdown, lambda f: f["generations"][0].update(rank=1)),
        _forge(manifest, markdown, lambda f: f["generations"][0]["individuals"][0].update(improved=True)),
    ]
    for key in ("claims", "generations", "limitations", "provenance", "snapshot", "score_label"):
        forged.append(_forge(manifest, markdown, lambda f, key=key: f.pop(key)))
    forged.append(_forge(manifest, markdown, lambda f: f.update(average_score=-6.0)))
    forged.append(_forge(manifest, markdown, lambda f: f["claims"].remove(
        _claim(manifest, "individual_result_score", generation=1, position=0))))
    for handle in forged:
        assert _selected(client, handle).status_code == 422
    for extra in ("rank 1", "improve", "winner", "평균", "추천"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            gr.render_ligand_ga_report({**manifest, "limitations": [*manifest["limitations"], extra]})
    without = {**manifest, "claims": [c for c in manifest["claims"] if c["statement_id"] != "individual_result_score"]}
    with pytest.raises(EvidenceError, match="claim_missing"):
        gr.render_ligand_ga_report(without)
    assert client.get(f"/runs/{RID}/reports").status_code == 422   # forged objects fail the list closed


def test_reopen_rejects_tampered_summary_individual_result_and_manifest(client, world):
    created = _report(client, world, "complete")
    other = _report(client, world, "partial")
    root = api_module.RUNS_DIR
    assert _selected(client, created["handle"]).status_code == 200
    path = root / RID / "objects" / f"{other['handle'].rsplit('/', 1)[-1]}.json"   # LABELED FAULT: manifest edited
    content = json.loads(path.read_bytes())
    content["claims"][0]["rendered_value"] = "x"
    path.write_bytes(canonical_json(content))
    assert _selected(client, other["handle"]).status_code == 422
    entry = next(e for _g, _p, e in _slots(world["stored"]["complete"]) if e["state"] == "scored")
    path = root / RID / "objects" / f"{entry['result_handle'].rsplit('/', 1)[-1]}.json"   # LABELED FAULT
    content = json.loads(path.read_bytes())
    content["modes"][0]["score_kcal_mol"] = -99.0
    path.write_bytes(canonical_json(content))
    for response in (_selected(client, created["handle"]),
                     client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"]}),
                     client.get(f"/runs/{RID}/reports/download",
                                params={"handle": created["handle"], "format": "json"}),
                     client.post(f"/runs/{RID}/method_reports",
                                 json={"result_handle": world["handles"]["complete"]})):
        assert response.status_code == 422 and "-99" not in response.text


def test_tampered_summary_and_unpublished_summaries_are_refused(client, world):
    created = _report(client, world, "complete")
    run = _run()
    content = copy.deepcopy(world["stored"]["complete"])   # LABELED TEST FABRICATION: no job published this object
    content["generations"][0]["individuals"][0]["score"] = -1.0
    with run._owner():
        forged = run.store.put(GC.OUTPUT_KIND, GC.SUMMARY_SCHEMA, content, produced_by="forged_test_ga")
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": forged.handle})
    assert response.status_code == 422 and "ligand_ga_result_invalid" in response.text
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["handles"]["complete"],
                                                                "filters": {}})
    assert response.status_code == 422 and "filters" in response.text
    for handle in (world["receptor"], f"obj://{RID}/ligand_ga_result/{'1' * 64}"):
        assert client.post(f"/runs/{RID}/method_reports", json={"result_handle": handle}).status_code == 422
    # LABELED FAULT: the stored summary edited in place; the saved report no longer reopens
    path = api_module.RUNS_DIR / RID / "objects" / f"{world['handles']['complete'].rsplit('/', 1)[-1]}.json"
    stored = json.loads(path.read_bytes())
    stored["generations"][0]["max_score"] = -99.0
    path.write_bytes(canonical_json(stored))
    response = _selected(client, created["handle"])
    assert response.status_code == 422 and "ligand_ga_result_invalid" in response.text and "-99" not in response.text


def test_existing_report_kinds_and_saved_bytes_are_unchanged(client, world):
    """An M18 report of a GA individual and a candidate report saved before the GA report read back byte for byte."""
    individual = next(e["result_handle"] for _g, _p, e in _slots(world["stored"]["complete"])
                      if e["evaluation"] == "docked" and e["result_handle"])
    made = [client.post(f"/runs/{RID}/method_reports", json={"result_handle": handle})
            for handle in (individual, world["candidate_set"])]
    assert all(item.status_code == 201 for item in made), [item.text for item in made]
    earlier = [item.json() for item in made]

    def downloads(handle):
        return {fmt: client.get(f"/runs/{RID}/reports/download", params={"handle": handle, "format": fmt}).content
                for fmt in ("markdown", "json")}
    before = {item["handle"]: downloads(item["handle"]) for item in earlier}
    ga = _report(client, world, "complete")
    after = {item["handle"]: downloads(item["handle"]) for item in earlier}
    assert after == before
    for item in earlier:
        assert before[item["handle"]]["markdown"] == item["markdown"].encode("utf-8")
        assert before[item["handle"]]["json"] == canonical_json(item["manifest"])
    listed = {entry["handle"]: entry["analysis_type"] for entry in client.get(f"/runs/{RID}/reports").json()}
    assert listed == {earlier[0]["handle"]: "ligand_docking", earlier[1]["handle"]: "ligand_candidates",
                      ga["handle"]: "ligand_ga"}


def test_report_module_reads_only_stored_evidence():
    source = Path(gr.__file__).read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in ("rdkit", "meeko", "MDAnalysis") for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "JobQueue", ".submit(", "stage(",
                      "qvina2", "build_docking_report", "finish("):
        assert forbidden not in source
