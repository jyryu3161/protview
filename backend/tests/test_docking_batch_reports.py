"""M19 T7: the ligand docking batch report (``method_report_manifest@1``, ``analysis_type: "ligand_docking_batch"``,
``ligand_docking_batch_markdown@1``; spec .dryforge/spec.md 10).

The world is real product output (``docking_batch_fixture``: real M17 jobs and real batch jobs with the pinned worker;
a missing environment FAILS, never skips). No report value is copied from the product: every claim is re-resolved by
path in the stored summary and in the stored per-row result, state counts are recounted here, and scores are rendered
with an independent ``Decimal`` oracle. Forged report manifests and edited objects are labeled test fabrications
written only to prove the validator rejects them.
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
from docking_batch_fixture import RID, build_world
from fastapi.testclient import TestClient

from mw import docking_batch_constants as BC
from mw import docking_batch_jobs as BJ
from mw import docking_batch_reports as br
from mw import docking_bundle
from mw import docking_constants as C
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError
from mw.runtime.guards import BudgetLimits

PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")
UNSCORED = ("failed", "cancelled", "not_run")


def _score(value) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.1f}"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build_world(tmp_path_factory.mktemp("m19_reports") / "runs", pytest.MonkeyPatch.context)


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


def _verify_independently(world, name: str, manifest) -> None:
    """Re-resolve every claim from the stored summary or per-row result; recount states; check every rendering."""
    handle = world["handles"][name]
    summary = world["stored"][name]
    run = _run()
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
        if statement == "row_result_score":
            index = claim["row_selector"]["row_index"]
            row = summary["rows"][index]
            assert row["state"] == "scored" and claim["source_handle"] == row["result_handle"]
            assert (claim["source_kind"], claim["source_schema"]) == ("docking_result", "docking_result@1")
            assert path == "modes[0].score_kcal_mol"
            assert value == run.store.load(row["result_handle"])["modes"][0]["score_kcal_mol"] == row["score_kcal_mol"]
            continue
        assert claim["source_handle"] == handle
        assert (claim["source_kind"], claim["source_schema"]) == ("docking_batch_result", "docking_batch_result@1")
        if statement == "row_count":
            state = path.split(".")[1]
            expected = len(summary["rows"]) if state == "rows" else sum(r["state"] == state for r in summary["rows"])
            assert value == expected == summary["counts"][state]
        elif statement == "row_score":
            index = claim["row_selector"]["row_index"]
            assert path == f"rows[{index}].score_kcal_mol" and summary["rows"][index]["state"] == "scored"
            assert value == _resolve(summary, path)
        else:
            assert value == _resolve(summary, path)
            assert value is not None or statement == "removed_instance"
        if claim["rounding"] == "score_1dp":
            assert claim["rendered_value"] == _score(value) and claim["unit"] == "kcal/mol"
    scored = [row["row_index"] for row in summary["rows"] if row["state"] == "scored"]
    for statement in ("row_score", "row_result_score"):
        assert sorted(c["row_selector"]["row_index"] for c in manifest["claims"]
                      if c["statement_id"] == statement) == scored


def _table_row(manifest, row) -> str:
    who = "부모(기준 입력)" if row["kind"] == "parent" else br._md(row["candidate_id"])
    scored = row["state"] == "scored"
    cells = [str(row["row_index"]), who, br._md(row["state"]), _score(row["score_kcal_mol"]) if scored else "",
             BC.SCORE_ROW_LABELS[manifest["mode"]] if scored else "",
             "" if row["reason_code"] is None else br._md(row["reason_code"]),
             "" if row["result_handle"] is None else br._md(row["result_handle"])]
    return "| " + " | ".join(cells) + " |"


# ----------------------------------------------------------------- rendering and forbidden words
@pytest.mark.parametrize(("value", "text"), [(-5.25, "-5.3"), (-5.24999, "-5.2"), (-0.04, "0.0"), (-13.6, "-13.6"),
                                             (-12.32139, "-12.3"), (-7.05, "-7.1")])
def test_score_rendering_is_one_decimal_half_up(value, text):
    assert br.render_score(value) == text == _score(value)


def test_forbidden_words_with_fixed_sentence_and_score_label_exemptions():
    fixed = [*C.LIMITATIONS, *BC.BATCH_STATEMENTS.values()]
    assert "순위" in BC.BATCH_STATEMENTS["B1"] and "개선" in BC.BATCH_STATEMENTS["B3"]
    text = "\n".join(["# x", *fixed, f"- 점수 이름: {C.SCORE_LABEL}", C.SCORE_COLUMN_LABEL,
                      *BC.SCORE_ROW_LABELS.values(), "ok"])
    assert br.check_no_interpretation(text) == text
    for bad in ("순위 1", "best", "Best row", "개선", "최고 점수", "최적 후보", "결합 강도", "결합강도", "rank 1",
                "improved", "stronger", "친화도", "affinity", "binding", "좋은 후보", "활성", "optimal", "수소결합"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            br.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {BC.BATCH_STATEMENTS['B1']}", BC.BATCH_STATEMENTS["B3"] + " ", " " + BC.BATCH_STATEMENTS["B1"],
                 BC.BATCH_STATEMENTS["B1"].replace("아니다", "이다"), f"- 점수 이름: {C.SCORE_LABEL} best",
                 f"{C.SCORE_LABEL} 순위 1"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            br.check_no_interpretation(near)


# ----------------------------------------------------------------- correct reports
def test_free_complete_report_round_trips_and_every_score_traces_to_both_objects(client, world, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("a batch report must never dock, stage or start a job")

    for target, name in ((JobQueue, "_supervise"), (JobQueue, "submit"), (JobQueue, "start"),
                         (docking_bundle, "stage"), (BJ, "stage"), (BJ, "finish")):
        monkeypatch.setattr(target, name, forbidden)
    before = _events()
    created = _report(client, world, "free")
    added = _events()[len(before):]
    assert [e["type"] for e in added if e["type"] != "object_created"] == ["method_report_created"]
    assert {e.get("kind") for e in added if e["type"] == "object_created"} == {"report_markdown",
                                                                               "method_report_manifest"}
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["free"]
    assert manifest["schema"] == "method_report_manifest@1" and manifest["analysis_type"] == "ligand_docking_batch"
    assert manifest["render_version"] == "ligand_docking_batch_markdown@1" and manifest["status"] == "complete"
    assert manifest["generation_mode"] == "local_rules_no_egress"
    assert manifest["result_schema"] == "docking_batch_result@1" and manifest["batch_status"] == "complete"
    for key in ("method", "batch_input_sha256", "inputs", "box", "parameters", "engine", "preparation", "limits",
                "stop_reason", "counts", "rows"):
        assert manifest[key] == stored[key], key
    assert manifest["limitation_ids"] == stored["limitations"] == {"batch_statements": ["B1", "B3"],
                                                                   "m18_sentences": [1, 2, 3, 4, 5, 6, 7, 10]}
    assert manifest["limitations"] == [BC.BATCH_STATEMENTS["B1"], BC.BATCH_STATEMENTS["B3"],
                                       *(C.LIMITATIONS[n - 1] for n in (1, 2, 3, 4, 5, 6, 7, 10))]
    assert manifest["score_label"] == C.SCORE_LABEL and manifest["score_row_label"] == "모드 1(엔진 출력 순서)"
    assert manifest["provenance"]["docking_batch"]["job_id"] == world["jobs"]["free"]["job_id"]
    assert manifest["provenance"]["docking_batch"]["protocol_id"] == BC.PROTOCOL
    assert [item["result_handle"] for item in manifest["provenance"]["rows"]] == [
        row["result_handle"] for row in stored["rows"] if row["result_handle"]]
    assert "pose_sdf" not in json.dumps(manifest) and "contacts" not in json.dumps(manifest)
    _verify_independently(world, "free", manifest)
    for row in stored["rows"]:
        assert f"\n{_table_row(manifest, row)}\n" in markdown
    assert f"\n- 점수 이름: {C.SCORE_LABEL}\n" in markdown and f"| {C.SCORE_COLUMN_LABEL} |" in markdown
    for line in manifest["limitations"]:
        assert f"\n{line}\n" in markdown
    assert BC.BATCH_STATEMENTS["B2"] not in markdown and "부모(기준 입력)" in markdown
    assert br.check_no_interpretation(markdown) == markdown
    # list / selected / download are byte-identical, write no event and never re-dock
    run = _run()
    before = len(_events())
    listed = client.get(f"/runs/{RID}/reports")
    assert listed.status_code == 200, listed.text
    entry = next(item for item in listed.json() if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "ligand_docking_batch" and entry["result_handle"] == world["handles"]["free"]
    selected = _selected(client, created["handle"])
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"], "format": "markdown"})
    js = client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") == run.store.load(created["markdown_handle"])
    assert js.content == canonical_json(manifest) == canonical_json(run.store.load(created["handle"]))
    assert len(_events()) == before
    # no per-row M18 report was made: exactly one report event for the one request
    assert len([e for e in _events() if e["type"] == "method_report_created"]) == 1


def test_partial_report_lists_reasons_only_and_carries_b2_b3(client, world):
    created = _report(client, world, "partial")
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["partial"]
    _verify_independently(world, "partial", manifest)
    assert manifest["batch_status"] == "partial" and manifest["stop_reason"] == "cancelled"
    assert manifest["limitations"][:3] == [BC.BATCH_STATEMENTS[item] for item in ("B1", "B2", "B3")]
    unscored = [row for row in stored["rows"] if row["state"] in UNSCORED]
    assert [(r["state"], r["reason_code"]) for r in unscored] == [("cancelled", "cancelled"), ("not_run", "cancelled")]
    for row in unscored:
        line = _table_row(manifest, row)
        assert f"\n{line}\n" in markdown and "0.0" not in line and "kcal" not in line
        assert not [c for c in manifest["claims"] if (c["row_selector"] or {}).get("row_index") == row["row_index"]]
    assert "멈춘 이유 cancelled" in markdown and _claim(manifest, "row_count", "counts.not_run")["exact_value"] == 1
    assert _claim(manifest, "row_count", "counts.cancelled")["rendered_value"] == "1"


def test_core_fixed_report_names_samples(client, world):
    created = _report(client, world, "core")
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(world, "core", manifest)
    assert manifest["method"] == C.METHODS["core_fixed"] and manifest["score_row_label"] == "샘플 1(점수 오름차순 나열)"
    assert C.LIMITATIONS[7] in manifest["limitations"] and BC.BATCH_STATEMENTS["B3"] not in manifest["limitations"]
    assert "모드 1(엔진 출력 순서)" not in markdown and "| 샘플 1(점수 오름차순 나열) |" in markdown
    assert _claim(manifest, "parameter", "parameters.conformers")["rendered_value"] == "2"


def test_snapshot_carries_human_raised_limits(client, world):
    run = _run()
    snapshot = run.budget_snapshot()
    run.update_limits(BudgetLimits(expensive_calls=snapshot["expensive_calls"]["used"],
                                   wall_clock_s=snapshot["wall_clock_s"]["used"] + 10), by="test")
    raised = client.post(f"/runs/{RID}/docking/batches/limit_approval", json=world["args"]["partial"])
    assert raised.status_code == 200 and raised.json()["raised"] is True, raised.text
    limits = raised.json()["limits_after"]
    created = _report(client, world, "free")
    budget = created["manifest"]["snapshot"]["budget"]
    assert budget["expensive_calls"]["limit"] == limits["expensive_calls"]
    assert budget["wall_clock_s"]["limit"] == limits["wall_clock_s"]
    assert _selected(client, created["handle"]).status_code == 200


# ----------------------------------------------------------------- rejections
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
                               summary={"result_handle": manifest["result_handle"],
                                        "analysis_type": "ligand_docking_batch", "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=manifest["result_handle"], snapshot_event_seq=manifest["snapshot"]["event_seq"])
    return report.handle


def test_score_claims_for_rows_without_a_score_are_rejected(client, world):
    created = _report(client, world, "partial")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["partial"]
    score = _claim(manifest, "row_score", row_index=0)
    result_score = _claim(manifest, "row_result_score", row_index=0)
    run = _run()
    assert br.validate_docking_batch_claim(run, handle, copy.deepcopy(score)) == score
    for index in (2, 3):   # cancelled and not_run rows: no score, never 0
        cases = [{**score, "field_path": f"rows[{index}].score_kcal_mol", "row_selector": {"row_index": index},
                  "subject": {"docking_batch_result_handle": handle, "row_index": index}, "exact_value": 0.0,
                  "rendered_value": "0.0"},
                 {**result_score, "row_selector": {"row_index": index}, "exact_value": 0.0, "rendered_value": "0.0"}]
        for claim in cases:
            with pytest.raises(EvidenceError, match="field_not_allowed"):
                br.validate_docking_batch_claim(run, handle, claim)
            forged = _forge(manifest, markdown, lambda f, claim=claim: f["claims"].append(claim))
            assert _selected(client, forged).status_code == 422
    # a score written into an unscored table row is refused (the Markdown is re-rendered and compared)
    row = world["stored"]["partial"]["rows"][2]
    line = _table_row(manifest, row)
    edited = _forge(manifest, markdown.replace(line, line.replace("| cancelled |", "| cancelled | 0.0 |", 1)),
                    lambda f: None)
    assert line in markdown and _selected(client, edited).status_code == 422
    forged = _forge(manifest, markdown, lambda f: f["rows"][2].update(score_kcal_mol=0.0))
    assert _selected(client, forged).status_code == 422


def test_mixed_evidence_and_other_statement_fields_are_rejected(client, world):
    free = _report(client, world, "free")
    core = _report(client, world, "core")["manifest"]
    reused = _report(client, world, "reused")["manifest"]
    manifest, markdown = free["manifest"], free["markdown"]
    handle = world["handles"]["free"]
    run = _run()
    score = _claim(manifest, "row_score", row_index=1)
    result_score = _claim(manifest, "row_result_score", row_index=1)
    other_row = world["stored"]["core"]["rows"][0]["result_handle"]
    cases = [
        ("source_mismatch", _claim(core, "row_score", row_index=0)),       # a core-fixed batch's score
        ("source_mismatch", _claim(core, "row_result_score", row_index=0)),
        ("source_mismatch", _claim(reused, "row_score", row_index=0)),     # another summary's row
        ("source_mismatch", {**result_score, "source_handle": other_row,
                             "source_sha256": other_row.rsplit("/", 1)[-1]}),
        ("source_mismatch", {**score, "source_sha256": "0" * 64}),
        ("evidence_kind_mismatch", {**score, "evidence_kind": "reference_value"}),
        ("field_rule", {**score, "field_path": "modes[0].score_kcal_mol"}),
        ("field_rule", {**result_score, "field_path": "modes[1].score_kcal_mol"}),
        ("field_rule", {**score, "field_path": "rows[1].result_handle"}),
        ("statement_not_allowed", {**score, "statement_id": "binding_affinity"}),
        ("statement_not_allowed", {**score, "statement_id": "score_minimum"}),
        ("source_kind_mismatch", {**score, "source_kind": "docking_result", "source_schema": "docking_result@1"}),
        ("source_kind_mismatch", {**result_score, "source_kind": "docking_batch_result",
                                  "source_schema": "docking_batch_result@1"}),
        ("binding_mismatch", {**score, "quantity": "affinity_kcal_mol"}),
        ("binding_mismatch", {**score, "unit": "kJ/mol"}),
        ("binding_mismatch", {**score, "subject": {"docking_batch_result_handle": handle, "row_index": 2}}),
        ("field_not_allowed", {**score, "row_selector": {"row_index": 2}}),
    ]
    for reason, claim in cases:
        with pytest.raises(EvidenceError, match=reason):
            br.validate_docking_batch_claim(run, handle, claim)
    for reason, claim in cases:
        def mutate(forged, claim=claim):
            index = next(i for i, c in enumerate(forged["claims"]) if c == score)
            forged["claims"][index] = claim
        assert _selected(client, _forge(manifest, markdown, mutate)).status_code == 422, reason
    mixed = _forge(manifest, markdown, lambda f: f["claims"].append(_claim(core, "row_score", row_index=0)))
    assert _selected(client, mixed).status_code == 422
    swapped = _forge(manifest, markdown, lambda f: f.update(method=core["method"]))
    assert _selected(client, swapped).status_code == 422


def test_wrong_rounding_is_rejected(client, world):
    created = _report(client, world, "free")
    manifest, markdown = created["manifest"], created["markdown"]
    handle = world["handles"]["free"]
    run = _run()
    for statement in ("row_score", "row_result_score"):
        claim = _claim(manifest, statement, row_index=1)
        exact = claim["exact_value"]
        good = _score(exact)
        for wrong in {f"{Decimal(str(exact)):.2f}", repr(exact), good + "0", str(int(exact)),
                      f"{float(good) - 0.1:.1f}"} - {good}:
            with pytest.raises(EvidenceError, match="binding_mismatch"):
                br.validate_docking_batch_claim(run, handle, {**claim, "rendered_value": wrong})
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            br.validate_docking_batch_claim(run, handle, {**claim, "rounding": "distance_2dp",
                                                          "rendered_value": f"{Decimal(str(exact)):.2f}"})
    count = _claim(manifest, "row_count", "counts.scored")
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        br.validate_docking_batch_claim(run, handle, {**count, "exact_value": count["exact_value"] + 1,
                                                      "rendered_value": str(count["exact_value"] + 1)})
    score = _claim(manifest, "row_score", row_index=1)
    forged = _forge(manifest, markdown, lambda f: next(c for c in f["claims"] if c == score).update(
        rendered_value=f"{score['exact_value']:.2f}"))
    assert _selected(client, forged).status_code == 422
    row = world["stored"]["free"]["rows"][1]
    line = _table_row(manifest, row)
    edited = _forge(manifest, markdown.replace(line, line.replace(f"| {_score(row['score_kcal_mol'])} |",
                                                                  f"| {row['score_kcal_mol']:.2f} |")),
                    lambda f: None)
    assert line in markdown and _selected(client, edited).status_code == 422


def test_interpretive_statements_and_missing_fields_are_rejected(client, world):
    created = _report(client, world, "free")
    manifest, markdown = created["manifest"], created["markdown"]
    forged = [_forge(manifest, markdown.replace("## Limitations", f"{word}\n\n## Limitations"), lambda f: None)
              for word in ("행 1이 best 후보다.", "행 1의 순위가 가장 높다.", "부모 대비 개선되었다.", "최고 점수 후보.",
                           "최적 후보.", "결합 강도가 크다.")]
    forged += [
        _forge(manifest, markdown, lambda f: f["limitations"].append("점수가 낮아 순위가 높다.")),
        _forge(manifest, markdown, lambda f: f.update(evidence_statement="행 1이 최고다.")),
        _forge(manifest, markdown, lambda f: f.update(score_label="qvina 점수(kcal/mol, 결합 친화도)")),
        _forge(manifest, markdown, lambda f: f.update(score_row_label="best 모드")),
    ]
    for key in ("claims", "rows", "limitations", "provenance", "snapshot", "score_label"):
        forged.append(_forge(manifest, markdown, lambda f, key=key: f.pop(key)))
    # a required claim removed: the row score must trace to both objects
    forged.append(_forge(manifest, markdown, lambda f: f["claims"].remove(
        _claim(manifest, "row_result_score", row_index=1))))
    for handle in forged:
        assert _selected(client, handle).status_code == 422
    for extra in ("rank 1", "improve", "stronger", "친화"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            br.render_docking_batch_report({**manifest, "limitations": [*manifest["limitations"], extra]})
    without = {**manifest, "claims": [c for c in manifest["claims"] if c["statement_id"] != "row_result_score"]}
    with pytest.raises(EvidenceError, match="claim_missing"):
        br.render_docking_batch_report(without)
    assert client.get(f"/runs/{RID}/reports").status_code == 422   # forged objects fail the list closed


def test_reopen_rejects_tampered_summary_per_row_result_and_manifest(client, world):
    created = _report(client, world, "free")
    other = _report(client, world, "core")
    root = api_module.RUNS_DIR
    assert _selected(client, created["handle"]).status_code == 200
    path = root / RID / "objects" / f"{other['handle'].rsplit('/', 1)[-1]}.json"   # LABELED FAULT: manifest edited
    content = json.loads(path.read_bytes())
    content["claims"][0]["rendered_value"] = "x"
    path.write_bytes(canonical_json(content))
    assert _selected(client, other["handle"]).status_code == 422
    row = world["stored"]["free"]["rows"][1]["result_handle"]   # LABELED FAULT: a per-row result edited in place
    path = root / RID / "objects" / f"{row.rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["modes"][0]["score_kcal_mol"] = -99.0
    path.write_bytes(canonical_json(content))
    for response in (_selected(client, created["handle"]),
                     client.get(f"/runs/{RID}/reports/download", params={"handle": created["handle"]}),
                     client.get(f"/runs/{RID}/reports/download",
                                params={"handle": created["handle"], "format": "json"}),
                     client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["handles"]["free"]})):
        assert response.status_code == 422 and "-99" not in response.text


def test_wrong_kind_and_unpublished_summaries_are_refused(client, world):
    run = _run()
    content = copy.deepcopy(world["stored"]["free"])   # LABELED TEST FABRICATION: no job published this object
    content["rows"][0]["score_kcal_mol"] = -1.0
    with run._owner():
        forged = run.store.put(BC.OUTPUT_KIND, BC.SUMMARY_SCHEMA, content, produced_by="forged_test_batch")
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": forged.handle})
    assert response.status_code == 422 and "docking_batch_result_invalid" in response.text
    response = client.post(f"/runs/{RID}/method_reports", json={"result_handle": world["handles"]["free"],
                                                                "filters": {}})
    assert response.status_code == 422 and "filters" in response.text
    for handle in (world["receptor"], f"obj://{RID}/docking_batch_result/{'1' * 64}"):
        assert client.post(f"/runs/{RID}/method_reports", json={"result_handle": handle}).status_code == 422


def test_existing_report_kinds_and_saved_bytes_are_unchanged(client, world):
    """An M18 report of a batch row and a candidate report saved before the batch report read back byte for byte."""
    row = world["stored"]["free"]["rows"][1]["result_handle"]
    made = [client.post(f"/runs/{RID}/method_reports", json={"result_handle": handle})
            for handle in (row, world["candidate_set"])]
    assert all(item.status_code == 201 for item in made), [item.text for item in made]
    earlier = [item.json() for item in made]

    def downloads(handle):
        return {fmt: client.get(f"/runs/{RID}/reports/download", params={"handle": handle, "format": fmt}).content
                for fmt in ("markdown", "json")}
    before = {item["handle"]: downloads(item["handle"]) for item in earlier}
    batch = _report(client, world, "free")
    after = {item["handle"]: downloads(item["handle"]) for item in earlier}
    assert after == before
    for item in earlier:
        assert before[item["handle"]]["markdown"] == item["markdown"].encode("utf-8")
        assert before[item["handle"]]["json"] == canonical_json(item["manifest"])
    listed = {entry["handle"]: entry["analysis_type"] for entry in client.get(f"/runs/{RID}/reports").json()}
    assert listed == {earlier[0]["handle"]: "ligand_docking", earlier[1]["handle"]: "ligand_candidates",
                      batch["handle"]: "ligand_docking_batch"}


def test_report_module_reads_only_stored_evidence():
    source = Path(br.__file__).read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in ("rdkit", "meeko", "MDAnalysis") for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "JobQueue", ".submit(", "stage(",
                      "qvina2", "build_docking_report"):
        assert forbidden not in source
