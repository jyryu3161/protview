"""M23 T6: the sequence GA design report (``method_report_manifest@1``, ``analysis_type: "sequence_ga"``,
``sequence_ga_markdown@1``; spec .dryforge/spec.md 4, 5, 9).

The world is real product output (``sequence_ga_world``: real GA jobs with the real GA worker, modeling child and
qvina2; a missing environment FAILS, never skips). No report value is copied from the product: every claim is
re-resolved by path in the stored summary and in the stored result it cites, counts are recounted here, and scores are
rendered with an independent ``Decimal`` oracle. Forged report manifests, edited objects and the edited summary dicts
handed to the pure claim builder are labeled test fabrications written only to prove the validator rejects them.
"""
from __future__ import annotations

import ast
import copy
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sequence_ga_world import copy_run, shared_world

from mw import docking_bundle
from mw import docking_constants as C
from mw import sequence_ga_constants as SC
from mw import sequence_ga_jobs as SJ
from mw import sequence_ga_reports as sr
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError
from mw.tools import openmm_method

PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")
ORIGIN = {"initial": "초기", "carried": "다음 세대로 이어받음", "crossover": "교차", "edit": "편집", "random": "무작위"}
EDIT = {"add": "추가", "change": "바꿈", "move": "옮김", "remove": "뺌", None: ""}
EVALUATION = {"reused": "재사용", "computed": "새 평가", None: ""}
SCORE_STATEMENTS = ("individual_score", "individual_result_score", "reference_score", "reference_result_score")


def _score(value) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.1f}"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return shared_world(tmp_path_factory)


@pytest.fixture
def client(world, monkeypatch, tmp_path):
    """A function-scoped copy of the shared run (forged reports make the list fail; reports add objects)."""
    root = copy_run(world, tmp_path / "runs")
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    yield TestClient(api_module.app, base_url="http://127.0.0.1")
    api_module.RUNS.clear()


def _run(world):
    return api_module._run(world["rid"])


def _events(world) -> list[dict]:
    return list(_run(world).events.read())


def _report(client, world, name: str) -> dict:
    created = client.post(f"/runs/{world['rid']}/method_reports", json={"result_handle": world["handles"][name]})
    assert created.status_code == 201, created.text
    return created.json()


def _selected(client, world, handle):
    return client.get(f"/runs/{world['rid']}/reports/selected", params={"handle": handle})


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


def _evaluated(summary):
    return [entry for _g, _p, entry in _slots(summary) if entry["origin"] != "carried"]


def _verify_independently(world, name: str, manifest) -> None:
    """Re-resolve every claim from the stored summary or the stored result it cites; recount; check renderings."""
    handle = world["handles"][name]
    summary = world["stored"][name]
    run = _run(world)
    assert manifest["result_handle"] == handle and manifest["result_sha256"] == handle.rsplit("/", 1)[-1]
    seen = set()
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["source_handle"], claim["field_path"],
               json.dumps(claim["row_selector"], sort_keys=True))
        assert key not in seen
        seen.add(key)
        assert claim["evidence_kind"] == "computed"
        assert claim["source_sha256"] == claim["source_handle"].rsplit("/", 1)[-1]
        statement, value, path = claim["statement_id"], claim["exact_value"], claim["field_path"]
        selector = claim["row_selector"] or {}
        if statement in ("individual_result_score", "reference_result_score"):
            entry = (summary["reference"] if statement == "reference_result_score" else
                     summary["generations"][selector["generation"] - 1]["individuals"][selector["position"]])
            assert entry["state"] == "scored" and claim["source_handle"] == entry["result_handle"]
            assert (claim["source_kind"], claim["source_schema"]) == ("docking_result", "docking_result@1")
            assert path == "modes[0].score_kcal_mol"
            assert value == run.store.load(entry["result_handle"])["modes"][0]["score_kcal_mol"] == entry["score"]
        else:
            assert claim["source_handle"] == handle
            assert (claim["source_kind"], claim["source_schema"]) == ("sequence_ga_result", "sequence_ga_result@1")
        if statement == "run_count":
            evaluated = _evaluated(summary)
            expected = {"generations_done": sum(g["complete"] for g in summary["generations"]),
                        "new_evaluations_used": sum(e["evaluation"] == "computed" for e in evaluated),
                        "reused_count": sum(e["evaluation"] == "reused" for e in evaluated),
                        "reserved_evaluations": summary["reserved_evaluations"],
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
        elif statement == "reference_score":
            assert summary["reference"]["state"] == "scored" and value == summary["reference"]["score"]
        elif statement == "generation_score_range":
            gen = summary["generations"][selector["generation"] - 1]
            scores = [run.store.load(e["result_handle"])["modes"][0]["score_kcal_mol"]
                      for e in gen["individuals"] if e["state"] == "scored"]
            assert value == _resolve(summary, path) == (min(scores) if path.endswith("min_score") else max(scores))
        elif statement not in ("individual_result_score", "reference_result_score"):
            assert value == _resolve(summary, path)
        if claim["rounding"] == "score_1dp":
            assert claim["rendered_value"] == _score(value) and claim["unit"] == "kcal/mol"
    scored = sorted((g, p) for g, p, e in _slots(summary) if e["state"] == "scored")
    for statement in ("individual_score", "individual_result_score"):
        assert sorted((c["row_selector"]["generation"], c["row_selector"]["position"]) for c in manifest["claims"]
                      if c["statement_id"] == statement) == scored
    reference = summary["reference"]["state"] == "scored"
    for statement in ("reference_score", "reference_result_score"):
        assert len([c for c in manifest["claims"] if c["statement_id"] == statement]) == int(reference)
    assert {c["statement_id"] for c in manifest["claims"]} <= set(sr.STATEMENTS)


def _mutation(row) -> str:
    residue = row["residue"]   # 1UBQ: author chain and number are present
    assert residue["chain_auth"] is not None and residue["seq_auth"] is not None
    return f"{residue['chain_auth']}:{row['from']}{residue['seq_auth']}{residue['icode'] or ''}{row['to']}"


def _table_row(manifest, position, entry) -> str:
    scored = entry["state"] == "scored"
    cells = [str(position), sr._md(entry["key"]), sr._md(", ".join(_mutation(row) for row in entry["mutations"])),
             ORIGIN[entry["origin"]], "" if entry["parents"] is None else sr._md(", ".join(entry["parents"])),
             EDIT[entry["edit_op"]], EVALUATION[entry["evaluation"]], str(entry["pick_index"]),
             "" if entry["eval_index"] is None else str(entry["eval_index"]), sr._md(entry["state"]),
             _score(entry["score"]) if scored else "", SC.SCORE_ROW_LABEL if scored else "",
             "" if entry["reason_code"] is None else sr._md(entry["reason_code"]),
             "" if entry["model_handle"] is None else sr._md(entry["model_handle"]),
             "" if entry["result_handle"] is None else sr._md(entry["result_handle"])]
    return "| " + " | ".join(cells) + " |"


def _forbid_work(monkeypatch) -> None:
    def forbidden(*_a, **_k):
        raise AssertionError("a sequence GA report must never model, dock, stage or start a job")

    for target, name in ((JobQueue, "_supervise"), (JobQueue, "submit"), (JobQueue, "start"),
                         (docking_bundle, "stage"), (SJ, "stage"), (SJ, "finish"), (SJ, "start_plan"),
                         (SJ, "manifest"), (openmm_method, "preflight")):
        monkeypatch.setattr(target, name, forbidden)


# ----------------------------------------------------------------- rendering and forbidden words
@pytest.mark.parametrize(("value", "text"), [(-5.25, "-5.3"), (-5.24999, "-5.2"), (-0.04, "0.0"), (-13.6, "-13.6"),
                                             (-12.32139, "-12.3"), (-7.05, "-7.1"), (-6.35, "-6.4")])
def test_score_rendering_is_one_decimal_half_up(value, text):
    assert sr.render_score(value) == text == _score(value)


def test_forbidden_words_with_fixed_sentence_and_score_name_exemptions():
    assert "순위" in SC.STATEMENTS["S1"] and "ΔΔG" in SC.STATEMENTS["S5"] and "결합" in SC.STATEMENTS["S6"]
    text = "\n".join(["# x", *SC.STATEMENTS.values(), SC.SCORE_LABEL, f"- 점수 이름: {SC.SCORE_LABEL}",
                      C.SCORE_COLUMN_LABEL, SC.SCORE_ROW_LABEL, *ORIGIN.values(), *EVALUATION.values(),
                      *EDIT.values(), sr.NO_CHANGE_LABEL, "- 점수 최솟값 -7.1, 최댓값 -5.3 (값만)", "ok"])
    assert sr.check_no_interpretation(text) == text
    for bad in ("순위 1", "best", "Best individual", "개선", "최고 점수", "rank 1", "improved", "improvement",
                "야생형 대비 -0.4", "부모 대비", "점수 차이", "difference", "delta", "Delta score", "ΔΔG", "ddG",
                "안정성", "stability", "stabilizing", "친화도", "affinity", "binding", "결합", "승자", "winner",
                "평균 점수", "average score", "추천 후보", "recommended", "상위 개체", "better", "fittest", "증감",
                "점수 변화량", "두 구조 비교", "compared", "OpenMM 전위 -1000", "에너지", "energy", "-1010.25 kJ/mol"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            sr.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {SC.STATEMENTS['S1']}", SC.STATEMENTS["S5"] + " ", " " + SC.STATEMENTS["S6"],
                 SC.STATEMENTS["S1"].replace("아니다", "이다"), f"- 점수 이름: {SC.SCORE_LABEL} best",
                 f"{SC.SCORE_LABEL} 순위 1", "다음 세대로 이어받음 (최고)"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            sr.check_no_interpretation(near)


def test_identifiers_containing_forbidden_words_do_not_fail_a_report(world, client):
    """Values and identifiers are slots: the check runs on the template with the slots empty."""
    manifest = _report(client, world, "complete")["manifest"]
    forged = copy.deepcopy(manifest)
    for claim in forged["claims"]:
        if claim["statement_id"] in ("candidate_set_input", "structure_input", "ligand_input"):
            claim["rendered_value"] = f"obj://run_best_rank/{claim['statement_id']}/best"
    forged["stop_reason"] = "best_rank_difference"   # LABELED TEST FABRICATION, never stored
    text = sr.render_sequence_ga_report(forged)
    assert "run\\_best\\_rank" in text and "best\\_rank\\_difference" in text
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        sr.render_sequence_ga_report({**forged, "limitations": [*forged["limitations"], "best"]})


# ----------------------------------------------------------------- correct reports
def test_complete_report_round_trips_and_every_score_traces_to_both_objects(client, world, monkeypatch):
    _forbid_work(monkeypatch)
    before = _events(world)
    created = _report(client, world, "complete")
    added = _events(world)[len(before):]
    assert [e["type"] for e in added if e["type"] != "object_created"] == ["method_report_created"]
    assert {e.get("kind") for e in added if e["type"] == "object_created"} == {"report_markdown",
                                                                               "method_report_manifest"}
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["complete"]
    assert manifest["schema"] == "method_report_manifest@1" and manifest["analysis_type"] == "sequence_ga"
    assert manifest["render_version"] == "sequence_ga_markdown@1" and manifest["status"] == "complete"
    assert manifest["generation_mode"] == "local_rules_no_egress"
    assert manifest["result_schema"] == "sequence_ga_result@1"
    assert manifest["ga_status"] == stored["status"] == "complete"
    assert manifest["docking_method"] == C.METHODS["free"]
    for key in sr.COPIED_FIELDS:
        assert manifest[key] == stored[key], key
    assert set(stored) == {*sr.COPIED_FIELDS, "schema", "status", "limitations"}
    assert manifest["limitation_ids"] == stored["limitations"] == ["S1", "S4", "S5", "S6"]
    assert manifest["limitations"] == [SC.STATEMENTS[item] for item in ("S1", "S4", "S5", "S6")]
    assert manifest["score_label"] == SC.SCORE_LABEL and manifest["score_row_label"] == "모드 1(엔진 출력 순서)"
    assert manifest["score_column_label"] == C.SCORE_COLUMN_LABEL
    job = world["jobs"]["complete"]
    assert manifest["provenance"]["sequence_ga"]["job_id"] == job["job_id"]
    assert manifest["provenance"]["sequence_ga"]["protocol_id"] == SC.PROTOCOL
    rows = manifest["provenance"]["rows"]
    assert [row["key"] for row in rows] == ["wild_type", *(e["key"] for e in _evaluated(stored))]
    for row, entry in zip(rows, [stored["reference"], *_evaluated(stored)], strict=True):
        assert (row["model_handle"], row["result_handle"]) == (entry["model_handle"], entry["result_handle"])
        assert row["model_job_id"] == row["result_job_id"] == job["job_id"]   # all computed by this GA
    assert set(manifest["snapshot"]) == {"event_seq", "time_utc", "run_egress_mode", "capability", "budget"}
    assert manifest["snapshot"]["capability"]["available"] is True
    for word in ("pose_sdf", "contacts", "atom_mapping", "final_bonds", "kJ_mol", "protonation", "disulfide"):
        assert word not in json.dumps(manifest["claims"])
    _verify_independently(world, "complete", manifest)
    for gen in stored["generations"]:
        for position, entry in enumerate(gen["individuals"]):
            assert f"\n{_table_row(manifest, position, entry)}\n" in markdown
    reference = stored["reference"]
    assert f"\n- {C.SCORE_COLUMN_LABEL}: {_score(reference['score'])} ({SC.SCORE_ROW_LABEL})\n" in markdown
    assert "| 다음 세대로 이어받음 |" in markdown and "| 편집 |" in markdown and "| 무작위 |" in markdown
    assert f"\n- 점수 이름: {SC.SCORE_LABEL}\n" in markdown and f"| {C.SCORE_COLUMN_LABEL} |" in markdown
    for line in manifest["limitations"]:
        assert f"\n{line}\n" in markdown
    assert SC.STATEMENTS["S2"] not in markdown and SC.STATEMENTS["S3"] not in markdown
    # the template is checked with its slots empty (the M18 value name energy_range is an identifier slot)
    assert sr.render_sequence_ga_report(manifest) == markdown and "- energy\\_range: " in markdown
    # list / selected / download are byte-identical, write no event and never model or dock again
    run = _run(world)
    before = len(_events(world))
    listed = client.get(f"/runs/{world['rid']}/reports")
    assert listed.status_code == 200, listed.text
    entry = next(item for item in listed.json() if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "sequence_ga" and entry["result_handle"] == world["handles"]["complete"]
    selected = _selected(client, world, created["handle"])
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{world['rid']}/reports/download", params={"handle": created["handle"],
                                                                      "format": "markdown"})
    js = client.get(f"/runs/{world['rid']}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") == run.store.load(created["markdown_handle"])
    assert js.content == canonical_json(manifest) == canonical_json(run.store.load(created["handle"]))
    assert len(_events(world)) == before
    assert len([e for e in _events(world) if e["type"] == "method_report_created"]) == 1   # no per-row report


def test_partial_report_carries_s2_s3_and_has_no_claim_for_uncomputed_slots(client, world):
    created = _report(client, world, "partial")
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["partial"]
    _verify_independently(world, "partial", manifest)
    assert manifest["ga_status"] == "partial" and manifest["stop_reason"] == "evaluation_limit"
    assert manifest["limitations"] == [SC.STATEMENTS[item] for item in ("S1", "S2", "S3", "S4", "S5", "S6")]
    last = stored["generations"][-1]
    assert last["complete"] is False and "중간에 멈춤" in markdown
    assert len(last["individuals"]) < stored["ga"]["population_size"]
    assert _claim(manifest, "generation_count", generation=last["index"], where=None)["exact_value"] == \
        len(last["individuals"])
    assert _claim(manifest, "run_count", "new_evaluations_used")["exact_value"] == 4
    assert _claim(manifest, "run_count", "reused_count")["exact_value"] == stored["reused_count"] == 2
    assert "종료 이유 evaluation\\_limit" in markdown and "| 재사용 |" in markdown and "| 편집 |" in markdown
    crossover = next(e for e in _evaluated(stored) if e["origin"] == "crossover")
    assert "| 교차 |" in markdown and f"| 교차 | {sr._md(', '.join(crossover['parents']))} |" in markdown
    reused = [e for e in _evaluated(stored) if e["evaluation"] == "reused"]
    rows = {row["key"]: row for row in manifest["provenance"]["rows"]}
    for entry in reused:   # a reused row keeps its first producer (the complete GA)
        assert rows[entry["key"]]["model_job_id"] == world["jobs"]["complete"]["job_id"]


def test_failed_rows_have_no_score_claim_and_their_score_claims_are_refused(client, world):
    created = _report(client, world, "faulted")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["faulted"]
    stored = world["stored"]["faulted"]
    run = _run(world)
    _verify_independently(world, "faulted", manifest)
    individuals = stored["generations"][0]["individuals"]
    position, other = [p for p, e in enumerate(individuals) if e["state"] == "failed"]
    failed = individuals[position]
    assert _claim(manifest, "generation_count", generation=1, where="state == failed")["exact_value"] == 2
    assert _claim(manifest, "generation_count", generation=1, where="state == failed")["operation"].startswith(
        "count_where(state == failed;")
    for slot in (position, other):
        assert not [c for c in manifest["claims"] if c["row_selector"] == {"generation": 1, "position": slot}]
        assert f"\n{_table_row(manifest, slot, individuals[slot])}\n" in markdown
    # provenance: the model-only row is cited with its model, the row with neither object is not cited
    rows = {row["key"]: row for row in manifest["provenance"]["rows"]}
    assert rows[failed["key"]]["model_handle"] == failed["model_handle"]
    assert rows[failed["key"]]["result_handle"] is None
    assert individuals[other]["key"] not in rows
    # scored rows come first in the table (display order), the failed row last
    table = [line for line in markdown.split("\n") if line.startswith(f"| {position} |")]
    assert table and markdown.index(table[0]) > max(markdown.index(_table_row(manifest, p, e))
                                                    for p, e in enumerate(stored["generations"][0]["individuals"])
                                                    if e["state"] == "scored")
    score = _claim(manifest, "individual_score", generation=1, position=0 if position else 1)
    result_score = _claim(manifest, "individual_result_score", generation=1, position=0 if position else 1)
    assert sr.validate_sequence_ga_claim(run, handle, copy.deepcopy(score)) == score
    forged_claims = [{**score, "field_path": f"generations[0].individuals[{position}].score",
                      "row_selector": {"generation": 1, "position": position}, "exact_value": 0.0,
                      "rendered_value": "0.0"},
                     {**result_score, "row_selector": {"generation": 1, "position": position}, "exact_value": 0.0,
                      "rendered_value": "0.0"}]
    for claim in forged_claims:
        with pytest.raises(EvidenceError, match="field_not_allowed"):
            sr.validate_sequence_ga_claim(run, handle, claim)
        forged = _forge(world, manifest, markdown, lambda f, claim=claim: f["claims"].append(claim))
        assert _selected(client, world, forged).status_code == 422
    forged = _forge(world, manifest, markdown,
                    lambda f: f["generations"][0]["individuals"][position].update(score=0.0))
    assert _selected(client, world, forged).status_code == 422


def test_reference_failed_report_has_no_reference_score_and_refuses_one(client, world):
    created = _report(client, world, "reference_failed")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["reference_failed"]
    stored = world["stored"]["reference_failed"]
    _verify_independently(world, "reference_failed", manifest)
    assert manifest["generations"] == [] and manifest["stop_reason"] == "reference_failed"
    assert not [c for c in manifest["claims"] if c["statement_id"] in SCORE_STATEMENTS]
    assert _claim(manifest, "box", "box.source")["exact_value"] == "manual"
    assert "## 세대" not in markdown and stored["reference"]["reason_code"].replace("_", "\\_") in markdown
    complete = _report(client, world, "complete")["manifest"]
    reference = _claim(complete, "reference_score")
    run = _run(world)
    for claim in ({**reference, "source_handle": handle, "source_sha256": handle.rsplit("/", 1)[-1],
                   "subject": {**reference["subject"], "sequence_ga_result_handle": handle}},
                  {**reference, "source_handle": handle, "source_sha256": handle.rsplit("/", 1)[-1],
                   "exact_value": 0.0, "rendered_value": "0.0"}):
        with pytest.raises(EvidenceError, match="source_mismatch|field_not_allowed"):
            sr.validate_sequence_ga_claim(run, handle, claim)


def _forge(world, manifest: dict, markdown: str, mutate) -> str:
    """LABELED TEST FABRICATION: store a tampered report manifest and its creation event."""
    run = _run(world)
    forged = copy.deepcopy(manifest)
    mutate(forged)
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by="forged_test_report", summary={"result_handle": manifest["result_handle"]})
        forged["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_test_report",
                               summary={"result_handle": manifest["result_handle"], "analysis_type": "sequence_ga",
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=manifest["result_handle"], snapshot_event_seq=manifest["snapshot"]["event_seq"])
    return report.handle


# ----------------------------------------------------------------- rejections
def test_mixed_evidence_other_statement_fields_and_derived_claims_are_rejected(client, world):
    complete = _report(client, world, "complete")
    partial = _report(client, world, "partial")["manifest"]
    manifest, markdown = complete["manifest"], complete["markdown"]
    handle = world["handles"]["complete"]
    rid = world["rid"]
    run = _run(world)
    score = _claim(manifest, "individual_score", generation=1, position=0)
    result_score = _claim(manifest, "individual_result_score", generation=1, position=0)
    reference = _claim(manifest, "reference_result_score")
    other = next(e["result_handle"] for e in _evaluated(world["stored"]["complete"])
                 if e["result_handle"] and e["result_handle"] != result_score["source_handle"])
    elsewhere = handle.replace(rid, "run_other")
    cases = [
        ("source_mismatch", _claim(partial, "individual_score", generation=1, position=0)),   # another GA
        ("source_mismatch", {**score, "source_handle": elsewhere, "source_sha256": elsewhere.rsplit("/", 1)[-1]}),
        # another individual's result of this GA, cited for this slot
        ("field_not_allowed", {**result_score, "source_handle": other, "source_sha256": other.rsplit("/", 1)[-1]}),
        ("field_not_allowed", {**reference, "row_selector": {"generation": 1, "position": 0}}),
        ("source_mismatch", {**score, "source_sha256": "0" * 64}),
        ("evidence_kind_mismatch", {**score, "evidence_kind": "reference_value"}),
        ("field_rule", {**score, "field_path": "modes[0].score_kcal_mol"}),
        ("field_rule", {**result_score, "field_path": "modes[1].score_kcal_mol"}),
        ("field_rule", {**score, "field_path": "generations[0].individuals[0].score_difference"}),
        ("field_rule", {**score, "field_path": "reference.score"}),
        ("field_rule", {**_claim(manifest, "reference_score"), "field_path": "generations[0].min_score"}),
        ("statement_not_allowed", {**score, "statement_id": "binding_affinity"}),
        ("statement_not_allowed", {**score, "statement_id": "individual_rank"}),
        ("statement_not_allowed", {**score, "statement_id": "best_individual"}),
        ("statement_not_allowed", {**score, "statement_id": "wild_type_difference"}),
        ("statement_not_allowed", {**score, "statement_id": "openmm_energy"}),
        ("statement_not_allowed", {**score, "statement_id": "delta_delta_g"}),
        ("source_kind_mismatch", {**score, "source_kind": "docking_result", "source_schema": "docking_result@1"}),
        ("source_kind_mismatch", {**result_score, "source_kind": "sequence_ga_result",
                                  "source_schema": "sequence_ga_result@1"}),
        ("binding_mismatch", {**score, "quantity": "affinity_kcal_mol"}),
        ("binding_mismatch", {**score, "unit": "kJ/mol"}),
        ("binding_mismatch", {**score, "operation": "min(generations[0].individuals[*].score)"}),
        ("binding_mismatch", {**score, "subject": {**score["subject"], "key": "0-1"}}),
        ("field_not_allowed", {**score, "row_selector": {"generation": 1, "position": 99}}),
    ]
    for reason, claim in cases:
        with pytest.raises(EvidenceError, match=reason):
            sr.validate_sequence_ga_claim(run, handle, claim)
    for reason, claim in cases:
        def mutate(forged, claim=claim):
            index = next(i for i, c in enumerate(forged["claims"]) if c == score)
            forged["claims"][index] = claim
        assert _selected(client, world, _forge(world, manifest, markdown, mutate)).status_code == 422, reason
    mixed = _forge(world, manifest, markdown, lambda f: f["claims"].append(
        _claim(partial, "individual_score", generation=1, position=0)))
    assert _selected(client, world, mixed).status_code == 422
    swapped = _forge(world, manifest, markdown, lambda f: f.update(stop_reason="no_change"))
    assert _selected(client, world, swapped).status_code == 422


def test_wrong_rounding_is_rejected(client, world):
    created = _report(client, world, "complete")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["complete"]
    run = _run(world)
    for statement, selector in (("individual_score", {"generation": 1, "position": 0}),
                                ("individual_result_score", {"generation": 1, "position": 0}),
                                ("generation_score_range", {"generation": 1}),
                                ("reference_score", None), ("reference_result_score", None)):
        claim = next(c for c in manifest["claims"] if c["statement_id"] == statement and
                     (selector is None or c["row_selector"] == selector))
        exact = claim["exact_value"]
        good = _score(exact)
        for wrong in {f"{Decimal(str(exact)):.2f}", repr(exact), good + "0", str(int(exact)),
                      f"{float(good) - 0.1:.1f}", f"{float(good) + 0.1:.1f}"} - {good}:
            with pytest.raises(EvidenceError, match="binding_mismatch"):
                sr.validate_sequence_ga_claim(run, handle, {**claim, "rendered_value": wrong})
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            sr.validate_sequence_ga_claim(run, handle, {**claim, "rounding": "distance_2dp",
                                                        "rendered_value": f"{Decimal(str(exact)):.2f}"})
    count = _claim(manifest, "run_count", "new_evaluations_used")
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        sr.validate_sequence_ga_claim(run, handle, {**count, "exact_value": count["exact_value"] + 1,
                                                    "rendered_value": str(count["exact_value"] + 1)})
    fraction = _claim(manifest, "ga_parameter", "ga.random_fraction")
    assert fraction["rendered_value"] == "0.25"
    score = _claim(manifest, "individual_score", generation=1, position=0)
    forged = _forge(world, manifest, markdown, lambda f: next(c for c in f["claims"] if c == score).update(
        rendered_value=f"{score['exact_value']:.2f}"))
    assert _selected(client, world, forged).status_code == 422
    entry = world["stored"]["complete"]["generations"][0]["individuals"][0]
    line = _table_row(manifest, 0, entry)
    edited = _forge(world, manifest, markdown.replace(line, line.replace(f"| {_score(entry['score'])} |",
                                                                         f"| {entry['score']:.2f} |")),
                    lambda f: None)
    assert line in markdown and _selected(client, world, edited).status_code == 422


def test_interpretive_statements_and_missing_fields_are_rejected(client, world):
    created = _report(client, world, "complete")
    manifest, markdown = created["manifest"], created["markdown"]
    forged = [_forge(world, manifest, markdown.replace("## Limitations", f"{word}\n\n## Limitations"),
                     lambda f: None)
              for word in ("개체 1이 best 후보다.", "세대 2의 순위가 가장 높다.", "야생형 대비 0.4 낮다.",
                           "부모 대비 개선되었다.", "두 구조의 전위 차이는 -12 kJ/mol이다.", "변이가 안정성을 높였다.",
                           "ΔΔG -1.2", "추천 후보.", "결합이 더 강하다.")]
    forged += [
        _forge(world, manifest, markdown, lambda f: f["limitations"].append("점수가 낮아 순위가 높다.")),
        _forge(world, manifest, markdown, lambda f: f.update(evidence_statement="개체 1이 최고다.")),
        _forge(world, manifest, markdown, lambda f: f.update(score_label="qvina 점수(kcal/mol, 결합 친화도)")),
        _forge(world, manifest, markdown, lambda f: f.update(score_row_label="best 모드")),
        _forge(world, manifest, markdown, lambda f: f["generations"][0].update(rank=1)),
        _forge(world, manifest, markdown, lambda f: f["generations"][0]["individuals"][0].update(improved=True)),
        _forge(world, manifest, markdown, lambda f: f["reference"].update(difference=0.4)),
    ]
    for key in ("claims", "generations", "limitations", "provenance", "snapshot", "score_label", "reference"):
        forged.append(_forge(world, manifest, markdown, lambda f, key=key: f.pop(key)))
    forged.append(_forge(world, manifest, markdown, lambda f: f.update(wild_type_delta=-0.4)))
    forged.append(_forge(world, manifest, markdown, lambda f: f["claims"].remove(
        _claim(manifest, "individual_result_score", generation=1, position=0))))
    forged.append(_forge(world, manifest, markdown, lambda f: f["claims"].remove(
        _claim(manifest, "reference_result_score"))))
    for handle in forged:
        assert _selected(client, world, handle).status_code == 422
    for extra in ("rank 1", "improve", "winner", "평균", "추천", "차이", "야생형 대비"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            sr.render_sequence_ga_report({**manifest, "limitations": [*manifest["limitations"], extra]})
    without = {**manifest, "claims": [c for c in manifest["claims"] if c["statement_id"] != "individual_result_score"]}
    with pytest.raises(EvidenceError, match="claim_missing"):
        sr.render_sequence_ga_report(without)
    assert client.get(f"/runs/{world['rid']}/reports").status_code == 422   # forged objects fail the list closed


def test_reopen_rejects_tampered_summary_result_model_and_manifest(client, world):
    created = _report(client, world, "complete")
    other = _report(client, world, "partial")
    rid = world["rid"]
    root = api_module.RUNS_DIR
    assert _selected(client, world, created["handle"]).status_code == 200
    path = root / rid / "objects" / f"{other['handle'].rsplit('/', 1)[-1]}.json"   # LABELED FAULT: manifest edited
    content = json.loads(path.read_bytes())
    content["claims"][0]["rendered_value"] = "x"
    path.write_bytes(canonical_json(content))
    assert _selected(client, world, other["handle"]).status_code == 422
    entry = next(e for e in _evaluated(world["stored"]["complete"]) if e["state"] == "scored")
    path = root / rid / "objects" / f"{entry['result_handle'].rsplit('/', 1)[-1]}.json"   # LABELED FAULT
    content = json.loads(path.read_bytes())
    content["modes"][0]["score_kcal_mol"] = -99.0
    path.write_bytes(canonical_json(content))
    for response in (_selected(client, world, created["handle"]),
                     client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}),
                     client.get(f"/runs/{rid}/reports/download",
                                params={"handle": created["handle"], "format": "json"}),
                     client.post(f"/runs/{rid}/method_reports",
                                 json={"result_handle": world["handles"]["complete"]})):
        assert response.status_code == 422 and "-99" not in response.text


def test_tampered_model_and_unpublished_or_other_run_summaries_are_refused(client, world):
    created = _report(client, world, "faulted")
    rid = world["rid"]
    run = _run(world)
    content = copy.deepcopy(world["stored"]["complete"])   # LABELED TEST FABRICATION: no job published this object
    content["generations"][0]["individuals"][0]["score"] = -1.0
    with run._owner():
        forged = run.store.put(SC.OUTPUT_KIND, SC.SUMMARY_SCHEMA, content, produced_by="forged_test_sequence_ga")
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": forged.handle})
    assert response.status_code == 422 and "sequence_ga_result_invalid" in response.text
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["handles"]["complete"],
                                                                "filters": {}})
    assert response.status_code == 422 and "filters" in response.text
    for handle in (world["base"]["receptor"], f"obj://{rid}/sequence_ga_result/{'1' * 64}",
                   world["handles"]["complete"].replace(rid, "run_other")):
        assert client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle}).status_code == 422
    # LABELED FAULT: a stored set model edited in place; the saved report no longer reopens
    failed = next(e for e in _evaluated(world["stored"]["faulted"]) if e["state"] == "failed")
    path = api_module.RUNS_DIR / rid / "objects" / f"{failed['model_handle'].rsplit('/', 1)[-1]}.json"
    model = json.loads(path.read_bytes())
    model["new_disulfide_in_mutant"] = not model["new_disulfide_in_mutant"]
    path.write_bytes(canonical_json(model))
    response = _selected(client, world, created["handle"])
    assert response.status_code == 422 and "sequence_ga_result_invalid" in response.text


def test_existing_report_kinds_and_saved_bytes_are_unchanged(client, world):
    """An M18 report of a GA individual result, an M20 candidate report and an M18 report on the reference row,
    saved before the sequence GA report, read back byte for byte."""
    stored = world["stored"]["complete"]
    individual = next(e["result_handle"] for e in _evaluated(stored) if e["evaluation"] == "computed")
    made = [client.post(f"/runs/{world['rid']}/method_reports", json={"result_handle": handle})
            for handle in (individual, world["base"]["tiny"], stored["reference"]["result_handle"])]
    assert all(item.status_code == 201 for item in made), [item.text for item in made]
    earlier = [item.json() for item in made]

    def downloads(handle):
        return {fmt: client.get(f"/runs/{world['rid']}/reports/download",
                                params={"handle": handle, "format": fmt}).content for fmt in ("markdown", "json")}
    before = {item["handle"]: downloads(item["handle"]) for item in earlier}
    ga = _report(client, world, "complete")
    after = {item["handle"]: downloads(item["handle"]) for item in earlier}
    assert after == before
    for item in earlier:
        assert before[item["handle"]]["markdown"] == item["markdown"].encode("utf-8")
        assert before[item["handle"]]["json"] == canonical_json(item["manifest"])
    listed = {entry["handle"]: entry["analysis_type"] for entry in client.get(f"/runs/{world['rid']}/reports").json()}
    assert listed == {earlier[0]["handle"]: "ligand_docking", earlier[1]["handle"]: "mutation_candidates",
                      earlier[2]["handle"]: "ligand_docking", ga["handle"]: "sequence_ga"}
    assert earlier[0]["manifest"]["provenance"]["docking"]["protocol_id"] == SC.PROTOCOL


def test_report_module_reads_only_stored_evidence():
    source = Path(sr.__file__).read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in ("rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm") for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "JobQueue", ".submit(", "stage(",
                      "qvina2", "build_docking_report", "finish(", "kJ_mol", "protonation_differences",
                      "protonation_variants", "disulfide", "openmm_method", "validated_model("):
        assert forbidden not in source, forbidden
    assert set(sr.STATEMENTS) == {"candidate_set_input", "structure_input", "ligand_input", "box", "parameter",
                                  "ga_parameter", "space_count", "run_count", "generation_count",
                                  "generation_score_range", "individual_score", "individual_result_score",
                                  "reference_score", "reference_result_score"}
