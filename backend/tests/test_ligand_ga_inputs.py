"""M22 T2 server pure modules: GA constants, admission (reason by reason, in the spec order), GA parameter
normalization and cross rules, filter eligibility, pool and selection record, reuse index from M18 call keys,
reserved units / need / shortfall / limit raise (spec .dryforge/spec.md 2, 3, 4, 6, 7, 10).

Expected sets, sentences and budget numbers are typed from the spec text or taken from the independent T1 oracle in
``fixtures/ligand_ga/expected.json`` (``arithmetic.reservation``), never copied from the module under test.
Store-dependent admission uses a real run with the public receptor, the public-derived parent and real M17
inspect + enumerate jobs on the synthetic small GA pool (pinned RDKit worker; fails, never skips, when missing).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from ligand_job_fixture import import_file, new_ligand_run, run_job

from mw import docking_batch_constants as BC
from mw import docking_batch_inputs as BI
from mw import docking_bundle, docking_inputs
from mw import ligand_ga_constants as GC
from mw import ligand_ga_inputs as GI
from mw.core.errors import FailureClass, ToolFailure

GA_FIX = Path(__file__).parent / "fixtures" / "ligand_ga"
DOCK = Path(__file__).parent / "fixtures" / "docking"
CHEM = Path(__file__).parent / "fixtures" / "chemical"
EXPECTED = json.loads((GA_FIX / "expected.json").read_text())
SMALL_SET = json.loads((GA_FIX / "m17-candidate-set-small-pool.json").read_text())
IDS = [row["id"] for row in SMALL_SET["candidates"]]
MW = Path(__file__).resolve().parents[1] / "mw"
H_REC = "obj://run_g/chemical_raw_input/" + "a" * 64
H_SET = "obj://run_g/ligand_candidate_set/" + "b" * 64
H_PARENT = "obj://run_g/chemical_raw_input/" + "c" * 64
REC_SHA, PARENT_SHA = "d" * 64, SMALL_SET["parent_sha256"]
ACK = {"keep_input_protonation": True, "tool_assigned_types_charges": True, "rigid_no_optimization": True}
PINS = {"engine": "qvina", "qvina_sha256": "1" * 64, "qvina_package": "qvina-2.1.0-x", "versions": {},
        "worker_sha256": "2" * 64, "constants_sha256": "3" * 64, "lock_sha256": "4" * 64,
        "qvina_lock_sha256": "5" * 64}
DEFAULT_GA = {"seed": 7, "population_size": 12, "generations": 5, "elite_count": 2, "tournament_size": 2,
              "neighbor_count": 10, "random_fraction": 0.2, "patience": 3, "max_new_dockings": 60, "total_s": 7200}
SMALL_GA = {**DEFAULT_GA, "population_size": 4, "elite_count": 1, "max_new_dockings": 10, "total_s": 600}


def _ga(**changes) -> dict:
    return {**DEFAULT_GA, **changes}


def _args(**changes) -> dict:
    args = {"receptor_handle": H_REC, "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
            "candidate_set_handle": H_SET, "parent_sdf_handle": H_PARENT,
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": 42},
            "acknowledgement": dict(ACK), "filter": {}, "ga": _ga()}
    args.update(changes)
    return args


def _reason(fn, *args, cls=FailureClass.input_invalid, **kwargs) -> str:
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    assert caught.value.cls is cls
    return caught.value.detail["reason_code"]


def _validate(args, timeout_s=7800):
    return GI.validate_arguments(args, timeout_s)


# ---------------------------------------------------------------- closed constants (spec 2, 3, 4, 6, 10)


def test_ga_constants_match_spec():
    assert (GC.PROTOCOL, GC.TOOL, GC.ENGINE) == ("qvina_ga_dock_v1", "qvina_ga_design", "qvina")
    assert (GC.SUMMARY_SCHEMA, GC.OUTPUT_KIND) == ("ligand_ga_result@1", "ligand_ga_result")
    assert GC.WORKER_INPUT_SCHEMA == "ligand_ga_worker_input@1"
    assert GC.WORKER_OUTPUT_SCHEMA == "ligand_ga_worker_output@1"
    assert GC.INDIVIDUAL_EVENT == "ligand_ga_individual_published"
    assert GC.GA_KEYS == ("seed", "population_size", "generations", "elite_count", "tournament_size",
                          "neighbor_count", "random_fraction", "patience", "max_new_dockings", "total_s")
    assert GC.GA_RANGES == {"seed": (0, 2147483647, None), "population_size": (4, 24, 12),
                            "generations": (1, 8, 5), "elite_count": (0, 4, 2), "tournament_size": (2, 4, 2),
                            "neighbor_count": (3, 30, 10), "random_fraction": (0.0, 0.5, 0.2),
                            "patience": (1, 8, 3), "max_new_dockings": (4, 100, 60), "total_s": (600, 14400, 7200)}
    assert (GC.MAX_POOL, GC.PER_CANDIDATE_S, GC.MAX_NEW_DOCKINGS, GC.TOTAL_S_MAX, GC.TIMEOUT_MAX_S) == \
        (2000, 300, 100, 14400, 15000)
    assert GC.PER_CANDIDATE_S == BC.PER_CANDIDATE_S and GC.FINISH_MARGIN_S == 600
    assert GC.MAX_OUTPUT_BYTES == GC.MAX_REUSE_STAGING_BYTES == 128 * 1024 * 1024
    assert GC.MAX_SUMMARY_BYTES == 1024 * 1024
    assert (GC.RAISE_MARGIN_S, GC.MAX_RAISE_EXPENSIVE_CALLS, GC.MAX_RAISE_WALL_CLOCK_S) == (60, 100, 15000)
    assert GC.ADMISSION_REASONS == ("ga_pool_too_small", "ga_reuse_too_large", "ga_limit_raise_required")
    assert GC.STOP_REASONS == ("generations_complete", "no_change", "pool_exhausted", "docking_limit",
                               "time_exhausted", "cancelled", "worker_failed", "resource_exceeded")
    assert {r for r, s in GC.STATUS_BY_STOP_REASON.items() if s == "complete"} == \
        {"generations_complete", "no_change", "pool_exhausted"}
    assert {r for r, s in GC.STATUS_BY_STOP_REASON.items() if s == "partial"} == \
        {"docking_limit", "time_exhausted", "cancelled", "worker_failed", "resource_exceeded"}
    assert set(GC.STATUS_BY_STOP_REASON) == set(GC.STOP_REASONS)
    assert GC.ORIGINS == ("initial", "carried", "similar", "random")
    assert GC.EVALUATIONS == ("reused", "docked")
    assert GC.STATES == ("scored", "null_result", "failed")
    assert GC.FAILED_EXTRA_REASONS == ("candidate_timeout", "worker_failed")
    assert GC.SCORE_ROW_LABEL == BC.SCORE_ROW_LABELS["free"]


def test_g_sentences_verbatim_and_in_order():
    assert GC.STATEMENTS == {
        "G1": "GA는 후보 풀에서 어디를 도킹할지 정하는 탐색 방법이며, 개체의 점수 정렬·선택 표시는 순위나 추천이 아니다. "
              "부모·유사 후보 연결은 작업 모듈 기록이며 서버가 다시 계산하지 않았다.",
        "G2": "이 실행은 시간·도킹 상한·취소 등으로 일부 세대만 계산되었다. 계산하지 않은 개체는 점수가 없으며 0이 아니고, "
              "한도 도달로 멈춘 실행은 같은 설정으로 다시 해도 같은 경로를 보장하지 않는다.",
        "G3": "재사용한 개체는 같은 수용체·상자·seed·방식·값으로 이전에 저장된 도킹 결과를 가져온 것이며, "
              "저장된 결과 집합이 다르면 같은 GA seed도 다른 경로를 낼 수 있다.",
    }
    assert list(GC.STATEMENTS) == ["G1", "G2", "G3"]


def test_constants_module_has_no_imports():
    tree = ast.parse((MW / "ligand_ga_constants.py").read_text())
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")]


# ---------------------------------------------------------------- argument shape and GA parameters (spec 2)


def test_valid_arguments_normalize():
    out = _validate(_args())
    assert out["ga"] == {**DEFAULT_GA, "random_fraction": 0.2}
    assert out["filter"] == {"ranges": {}, "pains_exclude": False}
    assert out["parameters"] == {"seed": 42, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                                 "conformers": None}
    assert out["box"] == {"source": "ligand_range", "margin_A": 8.0}
    assert out["acknowledgement"] == ACK
    assert "mode" not in out and "timeout_s" not in out
    assert (out["candidate_set_handle"], out["parent_sdf_handle"]) == (H_SET, H_PARENT)


def test_filter_defaults_to_empty_and_is_normalized():
    args = _args()
    del args["filter"]
    assert _validate(args)["filter"] == {"ranges": {}, "pains_exclude": False}
    spec = {"ranges": {"heavy_atoms": {"max": 45}, "tpsa": {"min": None, "max": None}}, "pains_exclude": True}
    assert _validate(_args(filter=spec))["filter"] == {"ranges": {"heavy_atoms": {"min": None, "max": 45}},
                                                       "pains_exclude": True}


@pytest.mark.parametrize("spec", [[], {"ranges": {"nope": {"max": 1}}}, {"ranges": {"tpsa": {"min": 5, "max": 1}}},
                                  {"pains_exclude": 1}, {"other": True}, {"ranges": {"tpsa": {"max": float("nan")}}}])
def test_filter_spec_errors_are_invalid_job_arguments(spec):
    assert _reason(_validate, _args(filter=spec)) == "invalid_job_arguments"


@pytest.mark.parametrize("key", ["mode", "ligand", "timeout_s", "candidate_ids", "include_parent", "receptor_source",
                                 "cpu"])
def test_unknown_top_level_keys_rejected(key):
    assert _reason(_validate, _args(**{key: "free"})) == "invalid_job_arguments"


@pytest.mark.parametrize("key", ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance",
                                 "candidate_set_handle", "parent_sdf_handle", "box", "parameters", "ga"])
def test_missing_required_key_rejected(key):
    args = _args()
    del args[key]
    assert _reason(_validate, args) == "invalid_job_arguments"


def test_not_an_object_rejected():
    assert _reason(_validate, [1]) == "invalid_job_arguments"


@pytest.mark.parametrize("key", GC.GA_KEYS)
def test_every_ga_key_is_required(key):
    ga = _ga()
    del ga[key]
    assert _reason(_validate, _args(ga=ga)) == "invalid_job_arguments"


def test_ga_unknown_key_and_shape_rejected():
    assert _reason(_validate, _args(ga={**_ga(), "crossover": 0.5})) == "invalid_job_arguments"
    assert _reason(_validate, _args(ga=[1])) == "invalid_job_arguments"


# boundary values typed from the spec table: (key, accepted lows/highs, rejected) with the other keys at defaults
# chosen so the cross rules hold.
BOUNDS = [
    ("seed", {}, [0, 2147483647], [-1, 2147483648]),
    ("population_size", {"max_new_dockings": 100}, [4, 24], [3, 25]),
    ("generations", {}, [1, 8], [0, 9]),
    ("elite_count", {}, [0, 4], [-1, 5]),
    ("tournament_size", {}, [2, 4], [1, 5]),
    ("neighbor_count", {}, [3, 30], [2, 31]),
    ("patience", {}, [1, 8], [0, 9]),
    ("max_new_dockings", {}, [12, 100], [11, 101]),
    ("total_s", {}, [600, 7200], [599, 14401]),
]


@pytest.mark.parametrize(("key", "base", "accepted", "rejected"), BOUNDS, ids=[b[0] for b in BOUNDS])
def test_integer_parameter_boundaries(key, base, accepted, rejected):
    for value in accepted:
        assert _validate(_args(ga=_ga(**base, **{key: value})), 15000)["ga"][key] == value
    for value in rejected:
        assert _reason(_validate, _args(ga=_ga(**base, **{key: value})), 15000) == "invalid_job_arguments", value
    for value in (True, False, float(accepted[0]), str(accepted[0]), None):
        assert _reason(_validate, _args(ga=_ga(**base, **{key: value})), 15000) == "invalid_job_arguments", value


def test_total_s_maximum_needs_the_maximum_timeout():
    assert _validate(_args(ga=_ga(total_s=14400)), 15000)["ga"]["total_s"] == 14400
    assert _reason(_validate, _args(ga=_ga(total_s=14400)), 15001) == "invalid_job_arguments"


def test_random_fraction_is_a_finite_real_in_range():
    for value, expect in ((0, 0.0), (0.0, 0.0), (0.5, 0.5), (0.25, 0.25), (-0.0, 0.0)):
        out = _validate(_args(ga=_ga(random_fraction=value)))["ga"]["random_fraction"]
        assert out == expect and type(out) is float
    for value in (-0.01, 0.51, 1, float("nan"), float("inf"), True, "0.2", None):
        assert _reason(_validate, _args(ga=_ga(random_fraction=value))) == "invalid_job_arguments", value


def test_elite_rule_population_minus_elite_at_least_two():
    assert _validate(_args(ga=_ga(population_size=4, elite_count=2, max_new_dockings=4)))["ga"]["elite_count"] == 2
    assert _validate(_args(ga=_ga(population_size=6, elite_count=4)))["ga"]["elite_count"] == 4
    for p, e in ((4, 3), (4, 4), (5, 4)):
        assert _reason(_validate, _args(ga=_ga(population_size=p, elite_count=e, max_new_dockings=10))) == \
            "invalid_job_arguments", (p, e)


def test_max_new_dockings_at_least_population_size():
    assert _validate(_args(ga=_ga(population_size=24, max_new_dockings=24)))["ga"]["max_new_dockings"] == 24
    assert _reason(_validate, _args(ga=_ga(population_size=24, max_new_dockings=23))) == "invalid_job_arguments"
    assert _validate(_args(ga=_ga(population_size=4, elite_count=0, max_new_dockings=4)))["ga"]["max_new_dockings"] \
        == 4


def test_timeout_must_cover_total_plus_600_and_stay_under_15000():
    assert _validate(_args(ga=_ga(total_s=7200)), 7800)
    assert _validate(_args(ga=_ga(total_s=7200)), 7800.0)
    assert _reason(_validate, _args(ga=_ga(total_s=7200)), 7799) == "invalid_job_arguments"
    assert _reason(_validate, _args(ga=_ga(total_s=7200)), 7799.999) == "invalid_job_arguments"
    for bad in (None, True, float("nan"), float("inf"), "7800", 15000.5, 0, -1):
        assert _reason(_validate, _args(), bad) == "invalid_job_arguments", bad


def test_m18_rules_apply_to_shared_fields():
    assert _reason(_validate, _args(box={"source": "manual", "center_A": [0, 0, 0], "size_A": [41, 10, 10]})) == \
        "box_too_large"
    assert _reason(_validate, _args(box={"source": "instance_range", "margin_A": 8})) == "box_invalid"
    assert _reason(_validate, _args(acknowledgement={})) == "acknowledgement_missing"
    args = _args()
    del args["acknowledgement"]
    assert _reason(_validate, args) == "acknowledgement_missing"
    assert _reason(_validate, _args(parameters={"seed": 42, "conformers": 3})) == "invalid_job_arguments"
    assert _reason(_validate, _args(parameters={"seed": -1})) == "invalid_job_arguments"


def test_step_one_comes_before_the_m18_reasons():
    """Spec 2 order: every step 1 problem (ga, filter, timeout) is reported before an M18 reason (step 2)."""
    bad_box = {"source": "instance_range", "margin_A": 8}
    assert _reason(_validate, _args(box=bad_box, ga=_ga(elite_count=11))) == "invalid_job_arguments"
    assert _reason(_validate, _args(box=bad_box, filter={"x": 1})) == "invalid_job_arguments"
    assert _reason(_validate, _args(acknowledgement={}), 100) == "invalid_job_arguments"
    assert _reason(_validate, _args(acknowledgement={})) == "acknowledgement_missing"


def test_validation_does_not_mutate_input():
    args = _args(filter={"ranges": {"tpsa": {"max": 100}}})
    before = copy.deepcopy(args)
    _validate(args)
    assert args == before


def test_row_arguments_are_a_standalone_free_m18_request():
    normalized = _validate(_args())
    row = GI.row_arguments(normalized, IDS[3])
    request = {key: normalized[key] for key in ("receptor_handle", "receptor_model_number", "connectivity",
                                               "receptor_instance", "box", "acknowledgement")}
    request.update(mode="free", parameters={"seed": 42},
                   ligand={"source": "candidate", "candidate_set_handle": H_SET, "candidate_id": IDS[3],
                           "parent_sdf_handle": H_PARENT})
    assert row == docking_inputs.validate_arguments(request)


# ---------------------------------------------------------------- pool and filter eligibility (spec 2 step 3, 3)


def _rows(*pains_and_atoms) -> list[dict]:
    rows = []
    for i, (heavy, pains) in enumerate(pains_and_atoms):
        props = {**SMALL_SET["candidates"][0]["properties"], "heavy_atoms": heavy}
        rows.append({"id": f"c_{i:016x}", "properties": props, "pains": {"matches": ["x"] * pains}})
    return rows


def test_empty_spec_makes_every_candidate_eligible():
    rows = _rows((44, 1), (60, 0), (45, 2))
    for spec in ({"ranges": {}, "pains_exclude": False},
                 GI.validate_arguments(_args(filter={"ranges": {"tpsa": {}}}), 7800)["filter"]):
        pool = GI.eligibility(rows, spec)
        assert pool == [{"index": i, "candidate_id": row["id"], "eligible": True} for i, row in enumerate(rows)]
        assert GI.pool_counts(pool) == {"size": 3, "eligible_count": 3, "filter_excluded_count": 0}


def test_active_spec_keeps_only_passes_all_true():
    rows = _rows((44, 0), (46, 0), (45, 1), (45, 0))
    pool = GI.eligibility(rows, {"ranges": {"heavy_atoms": {"min": None, "max": 45}}, "pains_exclude": True})
    assert [p["eligible"] for p in pool] == [True, False, False, True]
    assert GI.pool_counts(pool) == {"size": 4, "eligible_count": 2, "filter_excluded_count": 2}
    pains_only = GI.eligibility(rows, {"ranges": {}, "pains_exclude": True})
    assert [p["eligible"] for p in pains_only] == [True, True, False, True]


def test_pool_too_small_is_its_own_reason():
    pool = GI.eligibility(_rows((44, 0), (46, 0), (44, 0), (44, 0), (44, 0)),
                          {"ranges": {"heavy_atoms": {"min": None, "max": 45}}, "pains_exclude": False})
    GI.require_pool(pool, 4)
    assert _reason(GI.require_pool, pool, 5) == "ga_pool_too_small"
    assert _reason(GI.require_pool, [], 4) == "ga_pool_too_small"


def test_corrupt_stored_rows_are_refused():
    rows = _rows((44, 0))
    rows[0]["properties"]["tpsa"] = None
    with pytest.raises(ToolFailure):
        GI.eligibility(rows, {"ranges": {}, "pains_exclude": False})


# ---------------------------------------------------------------- selection record and hashes (spec 4, 7)


def _representative(normalized: dict, cid: str) -> dict:
    """A docking_selection@1-shaped M18 selection for one candidate (as docking_bundle.submission returns)."""
    args = GI.row_arguments(normalized, cid)
    row = next(item for item in SMALL_SET["candidates"] if item["id"] == cid)
    return {"schema": "docking_selection@1", "arguments": args, "input_sha256": docking_inputs.input_sha256(args),
            "receptor": {"handle": H_REC, "sha256": REC_SHA, "format": "pdb", "atom_count": 100,
                         "instance_sites": [], "removed_instance": None},
            "sidecar": None,
            "ligand": {"source": "candidate", "candidate_set_handle": H_SET,
                       "candidate_set_parent_sha256": PARENT_SHA,
                       "parent_sdf": {"handle": H_PARENT, "sha256": PARENT_SHA},
                       "candidate": {key: copy.deepcopy(row[key]) for key in
                                     ("id", "smiles", "retained_parent_atoms", "stereo_flag")}}}


def _selection(filter_spec=None, **changes) -> dict:
    normalized = _validate(_args(**({"filter": filter_spec} if filter_spec else {}), **changes))
    pool = GI.eligibility(SMALL_SET["candidates"], normalized["filter"])
    first = next(p["candidate_id"] for p in pool if p["eligible"])
    return GI.ga_selection(normalized, pool, _representative(normalized, first))


def _oracle_selection_sha(sel: dict) -> str:
    """Field list of the GA input, written out independently of the module."""
    args = sel["arguments"]
    pool = [{"index": i, "candidate_id": cid, "eligible": ok} for i, (cid, ok) in
            enumerate(zip([p["candidate_id"] for p in sel["pool"]], [p["eligible"] for p in sel["pool"]],
                          strict=True))]
    pool_sha = hashlib.sha256(json.dumps(pool, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode()).hexdigest()
    payload = {"receptor": {"handle": H_REC, "sha256": REC_SHA, "model_number": args["receptor_model_number"],
                            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None, "sidecar_sha256": None},
                            "instance": args["receptor_instance"]},
               "candidate_set_handle": H_SET, "parent_sdf": {"handle": H_PARENT, "sha256": PARENT_SHA},
               "pool_sha256": pool_sha, "filter": args["filter"], "box": args["box"],
               "parameters": args["parameters"], "ga": args["ga"]}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def test_selection_records_pool_order_eligibility_and_hashes_only():
    sel = _selection({"ranges": {"heavy_atoms": {"max": 44}}})
    assert sel["schema"] == "ligand_ga_selection@1"
    assert [p["candidate_id"] for p in sel["pool"]] == IDS
    assert [p["eligible"] for p in sel["pool"]] == [True, False, False, False, False, False, True, True, False,
                                                    False]
    assert sel["receptor"]["sha256"] == REC_SHA and sel["sidecar"] is None
    assert sel["candidate_set"] == {"handle": H_SET, "parent_sha256": PARENT_SHA}
    assert sel["parent_sdf"] == {"handle": H_PARENT, "sha256": PARENT_SHA}
    assert sel["selection_sha256"] == GI.selection_sha256(sel) == _oracle_selection_sha(sel)
    # no per-candidate M18 selection is kept for the pool (spec 7: only ids, eligibility, pool hash, filter, values)
    assert set(sel) == {"schema", "arguments", "receptor", "sidecar", "candidate_set", "parent_sdf", "pool",
                        "pool_sha256", "selection_sha256"}
    assert all(set(p) == {"index", "candidate_id", "eligible"} for p in sel["pool"])


def test_selection_hash_excludes_acknowledgement_and_changes_with_meaningful_inputs():
    base = _selection()["selection_sha256"]
    assert _selection(parameters={"seed": 42, "exhaustiveness": 8})["selection_sha256"] == base
    for changes in ({"parameters": {"seed": 43}}, {"ga": _ga(seed=8)}, {"ga": _ga(patience=4)},
                    {"box": {"source": "ligand_range", "margin_A": 7}}):
        assert _selection(**changes)["selection_sha256"] != base, changes
    assert _selection({"pains_exclude": True})["selection_sha256"] != base


def test_selection_refuses_a_representative_that_is_not_the_first_eligible():
    normalized = _validate(_args())
    pool = GI.eligibility(SMALL_SET["candidates"], normalized["filter"])
    with pytest.raises(ValueError):
        GI.ga_selection(normalized, pool, _representative(normalized, IDS[1]))
    rep = _representative(normalized, IDS[0])
    rep["arguments"]["parameters"]["seed"] = 43
    with pytest.raises(ValueError):
        GI.ga_selection(normalized, pool, rep)


def test_individual_selection_is_the_standalone_selection_shape():
    sel = _selection()
    normalized = sel["arguments"]
    for row in SMALL_SET["candidates"][:3]:
        assert GI.individual_selection(sel, row) == _representative(normalized, row["id"])


# ---------------------------------------------------------------- reuse index (spec 6, 7)


def test_call_keys_are_the_m18_call_keys_of_eligible_candidates_in_pool_order():
    sel = _selection({"ranges": {"heavy_atoms": {"max": 44}}})
    keys = GI.call_keys(sel, PINS)
    assert list(keys) == [IDS[0], IDS[6], IDS[7]]
    for cid, key in keys.items():
        assert key == docking_bundle.call_key(BI.row_arguments({**sel["arguments"], "mode": "free"}, "candidate",
                                                               cid), PINS)


def test_reuse_index_maps_stored_results_to_candidates():
    sel = _selection()
    keys = GI.call_keys(sel, PINS)
    existing = {keys[IDS[7]]: "obj://run_g/docking_result/" + "7" * 64,
                keys[IDS[2]]: "obj://run_g/docking_result/" + "2" * 64, "unrelated": "h"}
    assert GI.reuse_index(sel, PINS, existing) == {IDS[2]: existing[keys[IDS[2]]], IDS[7]: existing[keys[IDS[7]]]}
    assert list(GI.reuse_index(sel, PINS, existing)) == [IDS[2], IDS[7]]
    other = {**PINS, "worker_sha256": "9" * 64}
    assert GI.reuse_index(sel, other, existing) == {}


def test_reuse_index_ignores_filter_excluded_candidates():
    sel = _selection({"ranges": {"heavy_atoms": {"max": 44}}})
    full = GI.call_keys(_selection(), PINS)
    existing = {full[IDS[2]]: "h2", full[IDS[6]]: "h6"}
    assert GI.reuse_index(sel, PINS, existing) == {IDS[6]: "h6"}


def test_reuse_staging_bound():
    GI.require_reuse_size(0)
    GI.require_reuse_size(128 * 1024 * 1024)
    assert _reason(GI.require_reuse_size, 128 * 1024 * 1024 + 1) == "ga_reuse_too_large"


# ---------------------------------------------------------------- budget arithmetic (spec 6)


def test_reserved_units_by_hand():
    # min(max_new, P + (G - 1) * (P - E)), worked by hand
    assert GI.reserved_units(_ga()) == min(60, 12 + 4 * 10) == 52
    assert GI.reserved_units(_ga(population_size=24, generations=8, elite_count=0, max_new_dockings=100)) == 100
    assert GI.reserved_units(_ga(population_size=4, generations=1, elite_count=2, max_new_dockings=4)) == 4
    assert GI.reserved_units(_ga(population_size=6, generations=8, elite_count=4, max_new_dockings=100)) == 20
    assert GI.reserved_units(_ga(population_size=10, generations=3, elite_count=0, max_new_dockings=29)) == 29
    assert GI.reserved_units(_ga(population_size=10, generations=3, elite_count=0, max_new_dockings=30)) == 30
    assert GI.reserved_units(_ga(population_size=10, generations=3, elite_count=0, max_new_dockings=31)) == 30


@pytest.mark.parametrize("row", EXPECTED["arithmetic"]["reservation"], ids=lambda r: r["name"])
def test_reservation_matches_the_independent_oracle(row):
    ga = row["ga"]
    assert GI.reserved_units(ga) == row["reserved_units"]
    assert GI.needed_budget(ga) == {"expensive_calls": row["reserved_units"], "wall_clock_s": row["wall_clock_s"]}
    assert GI.full_run_may_be_partial(ga) is row["full_run_may_be_partial"]


def test_needed_wall_boundaries():
    # wall = min(total_s + 600, units * 300 + 300)
    ga = _ga(population_size=4, generations=1, elite_count=0, max_new_dockings=4, total_s=600)
    assert GI.needed_budget(ga) == {"expensive_calls": 4, "wall_clock_s": 1200}     # min(1200, 1500)
    ga = _ga(population_size=4, generations=1, elite_count=0, max_new_dockings=4, total_s=900)
    assert GI.needed_budget(ga) == {"expensive_calls": 4, "wall_clock_s": 1500}     # min(1500, 1500)
    ga = _ga(population_size=4, generations=1, elite_count=0, max_new_dockings=4, total_s=1200)
    assert GI.needed_budget(ga) == {"expensive_calls": 4, "wall_clock_s": 1500}     # min(1800, 1500)
    assert GI.full_run_may_be_partial(ga) is False                                    # 1200 > 1200 is false
    assert GI.full_run_may_be_partial({**ga, "total_s": 1199}) is True


def _budget(calls_used=0, wall_used=0.0, calls_limit=8, wall_limit=1800.0) -> dict:
    return {"expensive_calls": {"used": calls_used, "limit": calls_limit},
            "wall_clock_s": {"used": wall_used, "limit": wall_limit}}


def _apply(snapshot: dict, increase: dict) -> dict:
    out = copy.deepcopy(snapshot)
    for axis, amount in increase.items():
        out[axis]["limit"] += amount
    return out


def test_default_ga_is_short_on_the_default_run_budget():
    needed = GI.needed_budget(_ga())
    assert needed == {"expensive_calls": 52, "wall_clock_s": 7800}
    assert GI.shortfall(needed, _budget()) == {"expensive_calls": 44, "wall_clock_s": 6000}
    assert _reason(GI.require_budget, needed, _budget(), cls=FailureClass.resource_exceeded) == \
        "ga_limit_raise_required"
    GI.require_budget(needed, _budget(calls_limit=52, wall_limit=7800))


def test_limit_increase_raises_only_the_shortfall_with_wall_margin():
    needed = GI.needed_budget(_ga())
    snapshot = _budget()
    increase = GI.limit_increase(needed, snapshot)
    assert increase == {"expensive_calls": 44, "wall_clock_s": 6060}
    raised = _apply(snapshot, increase)
    assert GI.shortfall(needed, raised) == {"expensive_calls": 0, "wall_clock_s": 0}
    assert GI.limit_increase(needed, raised) == {"expensive_calls": 0, "wall_clock_s": 0}


def test_limit_increase_caps():
    # usage above every limit: the shortfall is clamped at the need, the need at the GA caps (100 calls, 15000 s)
    big = GI.needed_budget(_ga(population_size=24, generations=8, elite_count=0, max_new_dockings=100,
                               total_s=14400))
    assert big == {"expensive_calls": 100, "wall_clock_s": 15000}
    assert GI.limit_increase(big, _budget(500, 90_000, 8, 1800)) == {"expensive_calls": 100, "wall_clock_s": 15060}
    # one axis short only
    needed = GI.needed_budget(_ga())
    assert GI.limit_increase(needed, _budget(0, 0, 52, 100)) == {"expensive_calls": 0, "wall_clock_s": 7760}
    assert GI.limit_increase(needed, _budget(0, 0, 51, 7800)) == {"expensive_calls": 1, "wall_clock_s": 0}
    assert GI.limit_increase(needed, _budget(0, 0, 52, 7800)) == {"expensive_calls": 0, "wall_clock_s": 0}
    assert GI.limit_increase(needed, _budget(0, 1, 52, 7800)) == {"expensive_calls": 0, "wall_clock_s": 61}


def test_preflight_fields():
    sel = _selection({"ranges": {"heavy_atoms": {"max": 45}}}, ga=SMALL_GA)
    keys = GI.call_keys(sel, PINS)
    existing = {keys[IDS[0]]: "h0", keys[IDS[2]]: "h2"}
    out = GI.preflight(sel, PINS, existing, _budget(6, 600))
    assert out["pool"] == {"size": 10, "eligible_count": 7, "filter_excluded_count": 3}
    assert out["reusable_count"] == 2
    assert out["reserved_units"] == out["max_new_dockings_expected"] == min(10, 4 + 4 * 3) == 10
    assert out["needed"] == {"expensive_calls": 10, "wall_clock_s": min(600 + 600, 10 * 300 + 300)}
    assert out["remaining"] == {"expensive_calls": 2, "wall_clock_s": 1200}
    assert out["shortfall"] == {"expensive_calls": 8, "wall_clock_s": 0}
    assert out["full_run_may_be_partial"] is True                 # 10 * 300 > 600
    assert out["selection_sha256"] == sel["selection_sha256"]


# ---------------------------------------------------------------- store-dependent admission (real run, real M17)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    run = new_ligand_run(tmp_path_factory.mktemp("ga"), "run_ga_admission", dry_run=False)
    receptor = import_file(run, "receptor", "rec.pdb", (CHEM / "prolif-vina-rec.pdb").read_bytes())
    parent = import_file(run, "ligand_sdf", "parent.sdf", (DOCK / "public-derived-parent-record0.sdf").read_bytes())
    planar = import_file(run, "ligand_sdf", "planar.sdf", (DOCK / "synthetic-ligand-planar-z0.sdf").read_bytes())
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi",
                         (GA_FIX / "synthetic-ga-small-blocks.smi").read_bytes())
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    return {"run": run, "receptor": receptor, "parent": parent, "planar": planar,
            "candidate_set": enumerated["output_handles"][0]}


def _real(world, **changes) -> dict:
    fields = {"receptor_handle": world["receptor"], "candidate_set_handle": world["candidate_set"],
              "parent_sdf_handle": world["parent"], "ga": dict(SMALL_GA)}
    return _args(**{**fields, **changes})


def _submit(world, timeout_s=7800, **changes):
    return GI.submission(world["run"], _real(world, **changes), timeout_s)


def test_submission_records_the_pool_and_matches_standalone_m18(world):
    from mw.ligand_bundle import validated_candidate_set

    run = world["run"]
    selected, normalized, handles = _submit(world, filter={"ranges": {"heavy_atoms": {"max": 45}}})
    assert selected["arguments"] == normalized
    assert handles == [world["receptor"], world["candidate_set"], world["parent"]]
    assert [p["candidate_id"] for p in selected["pool"]] == IDS                # the T1 small pool, stored order
    assert [p["eligible"] for p in selected["pool"]] == [True, True, True, False, True, False, True, True, False,
                                                         True]
    assert selected["selection_sha256"] == GI.selection_sha256(selected)
    rows = {row["id"]: row for row in validated_candidate_set(run, world["candidate_set"])[0]["candidates"]}
    for cid in (IDS[0], IDS[2], IDS[9]):
        standalone, _, _ = docking_bundle.submission(run, BI.row_request({**normalized, "mode": "free"}, "candidate",
                                                                         cid))
        assert GI.individual_selection(selected, rows[cid]) == standalone


def test_submission_rejections_in_order(world):
    run = world["run"]
    none_pass = {"ranges": {"heavy_atoms": {"min": 47}}}
    three_pass = {"ranges": {"heavy_atoms": {"max": 44}}}
    foreign = "obj://other_run/ligand_candidate_set/" + "0" * 64
    # 1 before everything
    assert _reason(GI.submission, run, _real(world, ga=_ga(elite_count=9), candidate_set_handle=foreign), 7800) == \
        "invalid_job_arguments"
    # 2: candidate set kind / run / publication is checked without a candidate id, before the pool
    assert _reason(GI.submission, run, _real(world, candidate_set_handle=foreign, filter=none_pass), 7800) == \
        "invalid_job_arguments"
    assert _reason(GI.submission, run, _real(world, candidate_set_handle=world["parent"]), 7800) == \
        "invalid_job_arguments"
    # 3 with zero eligible comes before the representative's M18 checks (no representative exists)
    assert _reason(GI.submission, run, _real(world, filter=none_pass, parent_sdf_handle=world["planar"]), 7800) == \
        "ga_pool_too_small"
    assert _reason(GI.submission, run, _real(world, filter=none_pass, receptor_handle=world["parent"]), 7800) == \
        "ga_pool_too_small"
    # 2 (the representative's M18 checks) before 3 when some candidate is eligible
    assert _reason(GI.submission, run, _real(world, filter=three_pass, parent_sdf_handle=world["planar"]), 7800) == \
        "parent_mismatch"
    assert _reason(GI.submission, run, _real(world, filter=three_pass, receptor_handle=world["parent"]), 7800) == \
        "invalid_job_arguments"
    assert _reason(GI.submission, run, _real(world, filter=three_pass), 7800) == "ga_pool_too_small"
    _submit(world, filter={"ranges": {"heavy_atoms": {"max": 45}}})          # 7 eligible >= 4: admitted


def test_submission_creates_no_events(world):
    run = world["run"]
    before = len(list(run.events.read()))
    _submit(world)
    with pytest.raises(ToolFailure):
        _submit(world, filter={"ranges": {"heavy_atoms": {"min": 47}}})
    assert len(list(run.events.read())) == before


# ---------------------------------------------------------------- isolation


@pytest.mark.parametrize("name", ["ligand_ga_constants.py", "ligand_ga_inputs.py", "ligand_ga_bundle.py"])
def test_ga_server_modules_import_no_heavy_packages(name):
    tree = ast.parse((MW / name).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m.split(".")[0] in {"rdkit", "meeko", "MDAnalysis", "openmm", "pdbfixer"} for m in imported), name
    text = (MW / name).read_text()
    assert "__import__" not in text and "importlib" not in text and "subprocess" not in text


def test_ga_server_modules_load_without_heavy_packages():
    code = ("import sys; import mw.ligand_ga_constants, mw.ligand_ga_inputs, mw.ligand_ga_bundle; "
            "print(any(m.split('.')[0] in ('rdkit', 'meeko', 'MDAnalysis', 'openmm', 'pdbfixer') "
            "for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
