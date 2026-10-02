"""M19 T2 batch summary ``docking_batch_result@1``: row derivation from staging observations and the job's stop
cause, status/stop_reason rules, limitations, validation and re-validation, batch call key (spec 4.3, 4.4, 5.2-5.4,
7.2, 12).

Expected row states and batch status come from the hand oracle in ``fixtures/docking/m19-batch-input.json`` and the
spec text. Per-row results here are hand-written ``docking_result@1``-shaped dicts (the server validates real ones
with ``docking_bundle.validated_result`` before they reach these functions); their scores are labeled test values,
not engine outputs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_docking_batch_inputs import IDS, PINS, _row_selection, _selection

from mw import docking_batch_bundle as BB
from mw import docking_batch_constants as BC
from mw import docking_constants as C
from mw.core.handles import canonical_json

FIX = Path(__file__).parent / "fixtures" / "docking"
ORACLE = json.loads((FIX / "m19-batch-input.json").read_text())["hand_oracle"]
ENGINE = {"name": "qvina", "version": "2.1.0", "binary_sha256": PINS["qvina_sha256"], "package": "qvina-2.1.0-x"}
PREPARATION = {"tool": "Meeko", "version": "0.8.0", "rdkit_version": "2026.03.6", "atom_typing": "ad4",
               "charges": "gasteiger"}
BOX = {"center_A": [3.4095, 0.7175, 11.314], "size_A": [22.321, 27.507, 27.6], "source": "ligand_range",
       "margin_A": 8.0}
LABEL = {"free": "모드 1(엔진 출력 순서)", "core_fixed": "샘플 1(점수 오름차순 나열)"}
B = {"B1": "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, "
           "표의 정렬은 표시 순서일 뿐 순위가 아니다.",
     "B2": "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다.",
     "B3": "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다."}


def _handle(n: int) -> str:
    return f"obj://run_b/docking_result/{n:064d}"


def _result(row: dict, scores: list[float], *, box: dict = BOX, unspecified: int | None = 0) -> dict:
    """A docking_result@1-shaped dict for one planned row (only what the batch checks reads is meaningful)."""
    sel = row["selected"]
    args = sel["arguments"]
    candidate = row["kind"] == "candidate"
    ligand = {"source": "candidate" if candidate else "sdf",
              "sdf_handle": None if candidate else args["ligand"]["sdf_handle"],
              "sdf_sha256": None if candidate else sel["ligand"]["sdf"]["sha256"],
              "candidate_set_handle": args["ligand"]["candidate_set_handle"] if candidate else None,
              "candidate_id": row["candidate_id"],
              "parent_sdf_handle": args["ligand"]["parent_sdf_handle"] if candidate else None,
              "parent_sdf_sha256": sel["ligand"]["parent_sdf"]["sha256"] if candidate else None,
              "generated": {"hydrogens": candidate, "coordinates": candidate},
              "stereo_flag": "none" if candidate else None,
              "unspecified_stereo_centers": unspecified if candidate else None}
    modes = [{"mode": i + 1, "score_kcal_mol": s} for i, s in enumerate(scores)]
    return {"schema": "docking_result@1", "protocol": "qvina_dock_v1", "method": C.METHODS[args["mode"]],
            "input_sha256": sel["input_sha256"],
            "inputs": {"receptor": {"handle": args["receptor_handle"], "sha256": sel["receptor"]["sha256"],
                                    "model_number": 1, "connectivity": args["connectivity"],
                                    "removed_instance": None, "acknowledgement": args["acknowledgement"]},
                       "ligand": ligand, "mode": args["mode"]},
            "box": copy.deepcopy(box), "parameters": {**args["parameters"], "cpu": 1}, "engine": dict(ENGINE),
            "preparation": dict(PREPARATION), "modes": modes,
            "counts": {"modes": len(modes), "null_result": not modes}, "limitations": []}


def _done(handle: str) -> dict:
    return {"started": True, "status": None, "result_handle": handle}


def _status(state: str, reason: str | None) -> dict:
    return {"started": True, "status": {"state": state, "reason_code": reason}, "result_handle": None}


STARTED = {"started": True, "status": None, "result_handle": None}
NOTHING = {"started": False, "status": None, "result_handle": None}


def _summary(sel: dict, observations: list[dict], results: dict, stop_cause: str | None, box: dict = BOX) -> dict:
    return BB.build_summary(sel, observations=observations, results=results, stop_cause=stop_cause, box=box,
                            engine=ENGINE)


def _scored_obs(sel: dict, index: int, scores: list[float], results: dict, *, scored_status: bool = True) -> dict:
    handle = _handle(index + 1)
    results[handle] = _result(sel["rows"][index], scores)
    obs = _done(handle)
    if scored_status:
        obs["status"] = {"state": "scored" if scores else "null_result", "reason_code": None}
    return obs


def _states(summary: dict) -> list[str]:
    return [row["state"] for row in summary["rows"]]


# ---------------------------------------------------------------- oracle scenarios (spec 4.4, fixture batch_status)


def test_failed_row_still_complete():
    sel, results = _selection(), {}
    obs = [_scored_obs(sel, 0, [-12.1, -11.0], results), _scored_obs(sel, 1, [-11.8], results),
           _status("failed", "core_match_failed")]
    out = _summary(sel, obs, results, None)
    case = ORACLE["batch_status"][0]
    assert (_states(out), out["status"], out["stop_reason"]) == (case["row_states"], case["status"],
                                                                 case["stop_reason"])
    assert [r["score_kcal_mol"] for r in out["rows"]] == [-12.1, -11.8, None]
    assert [r["reason_code"] for r in out["rows"]] == [None, None, "core_match_failed"]
    assert out["rows"][2]["result_handle"] is None and out["rows"][2]["score_row_label"] is None
    assert out["counts"] == {"rows": 3, "scored": 2, "null_result": 0, "failed": 1, "cancelled": 0, "not_run": 0}
    BB.check_summary(out, sel, results, PINS)


@pytest.mark.parametrize("in_progress", [STARTED, _status("cancelled", "cancelled")])
def test_user_cancel_during_row_two(in_progress):
    sel, results = _selection(), {}
    out = _summary(sel, [_scored_obs(sel, 0, [-12.1], results), in_progress, NOTHING], results, "cancelled")
    case = ORACLE["batch_status"][1]
    assert (_states(out), out["status"], out["stop_reason"]) == (case["row_states"], case["status"],
                                                                 case["stop_reason"])
    assert [r["reason_code"] for r in out["rows"]] == [None, "cancelled", "cancelled"]
    BB.check_summary(out, sel, results, PINS)


def test_worker_crash_during_last_row_is_complete():
    sel, results = _selection(), {}
    obs = [_scored_obs(sel, 0, [-12.1], results), _scored_obs(sel, 1, [-11.8], results), STARTED]
    out = _summary(sel, obs, results, "worker_failed")
    case = ORACLE["batch_status"][2]
    assert (_states(out), out["status"], out["stop_reason"]) == (case["row_states"], case["status"],
                                                                 case["stop_reason"])
    assert out["rows"][2]["reason_code"] == "worker_failed"
    assert out["limitations"]["batch_statements"] == ["B1"]
    BB.check_summary(out, sel, results, PINS)


def test_worker_crash_during_row_two_is_partial():
    sel, results = _selection(), {}
    out = _summary(sel, [_scored_obs(sel, 0, [-12.1], results), STARTED, NOTHING], results, "worker_failed")
    case = ORACLE["batch_status"][3]
    assert (_states(out), out["status"], out["stop_reason"]) == (case["row_states"], case["status"],
                                                                 case["stop_reason"])
    assert [r["reason_code"] for r in out["rows"]] == [None, "worker_failed", "worker_failed"]
    BB.check_summary(out, sel, results, PINS)


@pytest.mark.parametrize("in_progress", [STARTED, _status("cancelled", "time_exhausted")])
def test_time_exhausted_with_null_result_first_row(in_progress):
    sel, results = _selection(include_parent=True), {}
    obs = [_scored_obs(sel, 0, [], results), in_progress, NOTHING, NOTHING]
    out = _summary(sel, obs, results, "time_exhausted")
    case = ORACLE["batch_status"][4]
    assert (_states(out), out["status"], out["stop_reason"]) == (case["row_states"], case["status"],
                                                                 case["stop_reason"])
    null_row = out["rows"][0]
    assert null_row["result_handle"] == _handle(1)
    assert null_row["score_kcal_mol"] is None and null_row["score_row_label"] is None
    assert [r["reason_code"] for r in out["rows"]] == [None, "time_exhausted", "time_exhausted", "time_exhausted"]
    assert out["limitations"]["batch_statements"] == ["B1", "B2", "B3"]
    BB.check_summary(out, sel, results, PINS)


@pytest.mark.parametrize("over", [_status("not_run", "resource_exceeded"), STARTED])
def test_output_limit_marks_the_over_row_and_the_rest_not_run(over):
    sel, results = _selection(), {}
    out = _summary(sel, [_scored_obs(sel, 0, [-12.1], results), over, NOTHING], results, "resource_exceeded")
    assert _states(out) == ["scored", "not_run", "not_run"]
    assert [r["reason_code"] for r in out["rows"]] == [None, "resource_exceeded", "resource_exceeded"]
    assert (out["status"], out["stop_reason"]) == ("partial", "resource_exceeded")
    BB.check_summary(out, sel, results, PINS)


def test_candidate_timeout_row_fails_and_batch_continues():
    sel, results = _selection(), {}
    obs = [_status("failed", "candidate_timeout"), _scored_obs(sel, 1, [-11.8], results),
           _status("failed", "ligand_too_many_torsions")]
    out = _summary(sel, obs, results, None)
    assert _states(out) == ["failed", "scored", "failed"] and out["status"] == "complete"
    BB.check_summary(out, sel, results, PINS)


def test_cancel_or_time_after_the_last_row_is_complete():
    for cause in ("cancelled", "time_exhausted", "worker_failed"):
        sel, results = _selection(), {}
        obs = [_scored_obs(sel, i, [-10.0 - i], results) for i in range(3)]
        out = _summary(sel, obs, results, cause)
        assert out["status"] == "complete" and out["stop_reason"] is None, cause


def test_first_stop_reason_wins():
    sel, results = _selection(), {}
    obs = [_scored_obs(sel, 0, [-12.1], results), _status("cancelled", "time_exhausted"), NOTHING]
    out = _summary(sel, obs, results, "cancelled")  # a user cancel arriving after the worker's own time stop
    assert [r["reason_code"] for r in out["rows"]] == [None, "time_exhausted", "time_exhausted"]
    assert out["stop_reason"] == "time_exhausted"
    BB.check_summary(out, sel, results, PINS)


def test_reused_rows_are_filled_from_the_stored_result():
    sel, results = _selection(), {}
    reused = _scored_obs(sel, 2, [-9.5], results, scored_status=False)
    reused["started"] = False
    out = _summary(sel, [_scored_obs(sel, 0, [-12.1], results), STARTED, reused], results, "cancelled")
    assert _states(out) == ["scored", "cancelled", "scored"]
    assert (out["status"], out["stop_reason"]) == ("partial", "cancelled")
    BB.check_summary(out, sel, results, PINS)


def test_all_reused_empty_batch_is_complete():
    sel, results = _selection(), {}
    obs = []
    for i in range(3):
        o = _scored_obs(sel, i, [-10.0], results, scored_status=False)
        o["started"] = False
        obs.append(o)
    out = _summary(sel, obs, results, None)
    assert out["status"] == "complete" and out["counts"]["scored"] == 3


def test_scored_status_without_a_published_result_is_failed_output_invalid():
    sel = _selection()
    out = _summary(sel, [_status("scored", None), _status("null_result", None), _status("failed", "embed_failed")],
                   {}, None)
    assert _states(out) == ["failed", "failed", "failed"]
    assert [r["reason_code"] for r in out["rows"]] == ["engine_output_invalid", "engine_output_invalid",
                                                       "embed_failed"]
    BB.check_summary(out, sel, {}, PINS)


def test_core_fixed_label_and_limitations():
    sel, results = _selection(mode="core_fixed"), {}
    out = _summary(sel, [_scored_obs(sel, 0, [-12.32139], results), STARTED, NOTHING], results, "cancelled")
    assert out["rows"][0]["score_row_label"] == LABEL["core_fixed"]
    assert out["method"] == "qvina_core_fixed_score_only_v1"
    assert out["limitations"] == {"batch_statements": ORACLE["limitations"][1]["batch_statements"],
                                  "m18_sentences": [1, 2, 3, 4, 5, 7, 8]}
    assert out["parameters"]["conformers"] == 50 and out["parameters"]["cpu"] == 1
    BB.check_summary(out, sel, results, PINS)


def test_free_parent_limitations_and_stereo_sentence():
    sel, results = _selection(include_parent=True), {}
    obs = [_scored_obs(sel, i, [-12.0], results) for i in range(4)]
    out = _summary(sel, obs, results, None)
    assert out["limitations"] == {"batch_statements": ORACLE["limitations"][0]["batch_statements"],
                                  "m18_sentences": [1, 2, 3, 4, 5, 6, 7, 10]}
    assert out["rows"][0]["kind"] == "parent" and out["rows"][0]["candidate_id"] is None
    assert out["rows"][0]["score_row_label"] == LABEL["free"]
    results[_handle(3)]["inputs"]["ligand"]["unspecified_stereo_centers"] = 2
    out = _summary(sel, obs, results, None)
    assert out["limitations"]["m18_sentences"] == [1, 2, 3, 4, 5, 6, 7, 10, 11]
    BB.check_summary(out, sel, results, PINS)


def test_summary_fields_and_determinism():
    sel, results = _selection(include_parent=True), {}
    obs = [_scored_obs(sel, i, [-12.0 + i], results) for i in range(4)]
    first = _summary(sel, obs, results, None)
    assert set(first) == {"schema", "protocol", "method", "batch_input_sha256", "inputs", "box", "parameters",
                          "engine", "preparation", "limits", "status", "stop_reason", "rows", "counts",
                          "limitations"}
    assert (first["schema"], first["protocol"], first["method"]) == ("docking_batch_result@1",
                                                                     "qvina_batch_dock_v1", "qvina_free_v1")
    assert first["batch_input_sha256"] == sel["batch_input_sha256"]
    args = sel["arguments"]
    assert first["inputs"] == {
        "receptor": {"handle": args["receptor_handle"], "sha256": sel["receptor"]["sha256"], "model_number": 1,
                     "connectivity": args["connectivity"], "removed_instance": None,
                     "acknowledgement": args["acknowledgement"]},
        "candidate_set": {"handle": args["candidate_set_handle"], "parent_sdf_handle": args["parent_sdf_handle"],
                          "parent_sdf_sha256": sel["parent_sdf"]["sha256"]},
        "candidate_ids": IDS, "include_parent": True, "mode": "free"}
    assert first["limits"] == {"max_candidates": 50, "per_candidate_s": 300, "total_s": 7200}
    assert first["engine"] == ENGINE and first["preparation"] == PREPARATION and first["box"] == BOX
    assert set(first["rows"][0]) == {"row_index", "kind", "candidate_id", "state", "reason_code", "result_handle",
                                     "score_kcal_mol", "score_row_label"}
    second = _summary(copy.deepcopy(sel), copy.deepcopy(obs), copy.deepcopy(results), None)
    assert canonical_json(first) == canonical_json(second)
    text = canonical_json(first).decode()
    assert "job_" not in text and "attempt" not in text and "reuse" not in text and "elapsed" not in text


def test_score_less_rows_are_never_numeric():
    sel, results = _selection(include_parent=True), {}
    obs = [_scored_obs(sel, 0, [], results), _status("failed", "embed_failed"), STARTED, NOTHING]
    out = _summary(sel, obs, results, "cancelled")
    for row in out["rows"]:
        if row["state"] != "scored":
            assert row["score_kcal_mol"] is None and row["score_row_label"] is None
    assert "0.0" not in canonical_json(out["rows"]).decode()


# ---------------------------------------------------------------- inconsistent observations are refused


@pytest.mark.parametrize("obs,cause", [
    ([NOTHING, NOTHING, NOTHING], None),                                  # nothing ran but no stop cause
    ([STARTED, NOTHING, NOTHING], None),                                  # in-progress row without a stop cause
    ([_status("failed", "cancelled"), NOTHING, NOTHING], "cancelled"),    # failed takes no stop reason
    ([_status("cancelled", "worker_failed"), NOTHING, NOTHING], "cancelled"),
    ([_status("not_run", "embed_failed"), NOTHING, NOTHING], "cancelled"),
    ([_status("failed", None), NOTHING, NOTHING], "cancelled"),
    ([_status("scored", "embed_failed"), NOTHING, NOTHING], "cancelled"),
    ([_status("exploded", "embed_failed"), NOTHING, NOTHING], "cancelled"),
    ([{"started": True, "status": {"state": "failed", "reason_code": "embed_failed", "detail": "x"},
       "result_handle": None}, NOTHING, NOTHING], "cancelled"),
    ([NOTHING, NOTHING, NOTHING], "unknown_cause"),
    ([NOTHING, NOTHING], "cancelled"),                                    # wrong row count
])
def test_inconsistent_observations_raise(obs, cause):
    with pytest.raises(BB.DockingBatchEvidenceError):
        _summary(_selection(), obs, {}, cause)


def test_result_state_must_agree_with_status_file():
    sel, results = _selection(), {}
    obs = _scored_obs(sel, 0, [], results)
    obs["status"] = {"state": "scored", "reason_code": None}
    with pytest.raises(BB.DockingBatchEvidenceError):
        _summary(sel, [obs, NOTHING, NOTHING], results, "cancelled")


def test_result_of_another_row_is_refused_at_build():
    sel, results = _selection(), {}
    obs = _scored_obs(sel, 0, [-12.1], results)
    results[obs["result_handle"]] = _result(sel["rows"][1], [-12.1])
    with pytest.raises(BB.DockingBatchEvidenceError):
        _summary(sel, [obs, NOTHING, NOTHING], results, "cancelled")


# ---------------------------------------------------------------- validation of stored summaries (spec 5.2)


def _valid():
    sel, results = _selection(include_parent=True), {}
    obs = [_scored_obs(sel, 0, [-13.6], results), _scored_obs(sel, 1, [-12.1, -11.0], results),
           _status("failed", "embed_failed"), STARTED]
    return sel, results, _summary(sel, obs, results, "cancelled")


def _tamper(fn):
    sel, results, summary = _valid()
    BB.check_summary(summary, sel, results, PINS)
    changed = copy.deepcopy(summary)
    fn(changed, sel, results)
    with pytest.raises(BB.DockingBatchEvidenceError):
        BB.check_summary(changed, sel, results, PINS)


@pytest.mark.parametrize("edit", [
    lambda s, sel, r: s["rows"][1].update(score_kcal_mol=-12.2),
    lambda s, sel, r: s["rows"][1].update(score_kcal_mol=-11.0),            # not the first row's score
    lambda s, sel, r: s["rows"][2].update(score_kcal_mol=0.0),
    lambda s, sel, r: s["rows"][3].update(score_kcal_mol=0.0, score_row_label=LABEL["free"]),
    lambda s, sel, r: s["rows"][1].update(score_row_label=LABEL["core_fixed"]),
    lambda s, sel, r: s["rows"][1].update(reason_code="embed_failed"),
    lambda s, sel, r: s["rows"][2].update(reason_code=None),
    lambda s, sel, r: s["rows"][2].update(reason_code="no_such_reason"),
    lambda s, sel, r: s["rows"][3].update(state="not_run", reason_code="embed_failed"),
    lambda s, sel, r: s["rows"][1].update(state="null_result", score_kcal_mol=None, score_row_label=None),
    lambda s, sel, r: s["rows"][1].update(result_handle=_handle(1)),         # another row's result
    lambda s, sel, r: s["rows"][2].update(result_handle=_handle(1)),
    lambda s, sel, r: s["rows"][1].update(candidate_id=IDS[1]),
    lambda s, sel, r: s["rows"][0].update(kind="candidate"),
    lambda s, sel, r: s["rows"][1].update(row_index=5),
    lambda s, sel, r: s["rows"][1].update(detail="free text"),
    lambda s, sel, r: s["rows"].reverse(),
    lambda s, sel, r: s["rows"].pop(),
    lambda s, sel, r: s.update(status="complete", stop_reason=None),
    lambda s, sel, r: s.update(stop_reason="time_exhausted"),
    lambda s, sel, r: s["counts"].update(scored=3),
    lambda s, sel, r: s["limitations"].update(batch_statements=["B1", "B3"]),
    lambda s, sel, r: s["limitations"].update(m18_sentences=[1, 2, 3]),
    lambda s, sel, r: s.update(batch_input_sha256="0" * 64),
    lambda s, sel, r: s["box"].update(center_A=[0.0, 0.0, 0.0]),
    lambda s, sel, r: s["parameters"].update(seed=7),
    lambda s, sel, r: s["engine"].update(binary_sha256="9" * 64),
    lambda s, sel, r: s["preparation"].update(version="0.9.0"),
    lambda s, sel, r: s["limits"].update(total_s=9000),
    lambda s, sel, r: s["inputs"].update(include_parent=False),
    lambda s, sel, r: s["inputs"]["receptor"].update(model_number=2),
    lambda s, sel, r: s.update(method="qvina_core_fixed_score_only_v1"),
    lambda s, sel, r: s.update(schema="docking_batch_result@2"),
    lambda s, sel, r: s.update(reused_rows=[1]),
    lambda s, sel, r: r[_handle(2)]["modes"][0].update(score_kcal_mol=-1.0),   # stored result changed
    lambda s, sel, r: r[_handle(2)].update(input_sha256="0" * 64),
    lambda s, sel, r: r[_handle(2)]["parameters"].update(seed=99),
    lambda s, sel, r: r[_handle(2)]["box"].update(size_A=[10.0, 10.0, 10.0]),
    lambda s, sel, r: r[_handle(2)]["inputs"]["ligand"].update(candidate_id=IDS[2]),
    lambda s, sel, r: r[_handle(2)]["engine"].update(version="2.2.0", package="qvina-2.2.0-x"),
    lambda s, sel, r: r.pop(_handle(2)),
])
def test_tampered_summary_is_refused(edit):
    _tamper(edit)


def test_manual_box_must_be_the_request_and_range_box_its_margin():
    manual = {"source": "manual", "center_A": [1.0, 2.0, 3.0], "size_A": [20.0, 20.0, 20.0]}
    sel = _selection(box=manual)
    box = {**manual, "margin_A": None}
    results = {}
    obs = _scored_obs(sel, 0, [-1.5], results)
    results[_handle(1)]["box"] = dict(box)
    out = _summary(sel, [obs, _status("failed", "embed_failed"), _status("failed", "embed_failed")], results, None,
                   box=box)
    BB.check_summary(out, sel, results, PINS)
    with pytest.raises(BB.DockingBatchEvidenceError):
        _summary(sel, [_status("failed", "embed_failed")] * 3, {}, None, box={**box, "center_A": [0.0, 0.0, 0.0]})
    with pytest.raises(BB.DockingBatchEvidenceError):
        _summary(_selection(), [_status("failed", "embed_failed")] * 3, {}, None, box={**BOX, "margin_A": 4.0})


def test_summary_over_one_mebibyte_is_refused(monkeypatch):
    sel, results, summary = _valid()
    monkeypatch.setattr(BC, "MAX_SUMMARY_BYTES", len(canonical_json(summary)) - 1)
    with pytest.raises(BB.DockingBatchEvidenceError):
        BB.check_summary(summary, sel, results, PINS)


def test_row_results_on_selection_rows_independent_of_order_of_results_mapping():
    sel, results, summary = _valid()
    BB.check_summary(summary, sel, dict(reversed(list(results.items()))), PINS)
    assert summary["rows"][1]["result_handle"] in results


def test_row_selection_mismatch_in_stored_selection_is_refused():
    sel, results, summary = _valid()
    bad = copy.deepcopy(sel)
    bad["rows"][1] = {**bad["rows"][1], "selected": _row_selection(sel["arguments"], "candidate", IDS[1])}
    with pytest.raises(BB.DockingBatchEvidenceError):
        BB.check_summary(summary, bad, results, PINS)


# ---------------------------------------------------------------- batch call key (spec 5.3)


def test_only_a_complete_batch_deduplicates():
    sel, results = _selection(), {}
    full = _summary(sel, [_scored_obs(sel, i, [-10.0], results) for i in range(3)], results, None)
    partial = _summary(sel, [_scored_obs(sel, 0, [-10.0], results), STARTED, NOTHING], results, "cancelled")
    key = BB.batch_call_key(sel)
    assert key == sel["batch_input_sha256"]
    assert BB.complete_duplicate([("h_partial", partial)], key) is None
    assert BB.complete_duplicate([("h_partial", partial), ("h_full", full)], key) == "h_full"
    assert BB.complete_duplicate([("h_full", full)], "0" * 64) is None
