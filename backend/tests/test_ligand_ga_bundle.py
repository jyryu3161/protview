"""M22 T2 GA summary ``ligand_ga_result@1``: individuals from worker generation records + server observations +
stored per-individual M18 results, carried = lowest-score elites, id uniqueness, score copy, counts vs caps,
status / stop_reason mapping, G sentences, call key and every rejection of ``check_summary``
(spec .dryforge/spec.md 3, 4, 6, 7).

Generation paths come from the independent T1 oracle (``fixtures/ligand_ga/expected.json`` ``ga_vectors``, written
before any product GA code and never importing ``mw``); per-individual results are hand-written
``docking_result@1``-shaped dicts whose first-mode scores are the oracle's labelled scores (observed fast qvina2
values or SYNTHETIC selection-logic inputs), not new engine outputs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_ligand_ga_inputs import IDS, PINS, SMALL_SET, _args, _representative, _validate

from mw import docking_constants as C
from mw import ligand_ga_bundle as GB
from mw import ligand_ga_constants as GC
from mw import ligand_ga_inputs as GI
from mw.core.handles import canonical_json

GA_FIX = Path(__file__).parent / "fixtures" / "ligand_ga"
VECTORS = json.loads((GA_FIX / "expected.json").read_text())["ga_vectors"]
ROWS = {row["id"]: row for row in SMALL_SET["candidates"]}
GA_PINS = {"ga_worker_sha256": "6" * 64, "ga_constants_sha256": "7" * 64}
ENGINE = {"name": "qvina", "version": "2.1.0", "binary_sha256": PINS["qvina_sha256"], "package": "qvina-2.1.0-x"}
PREPARATION = {"tool": "Meeko", "version": "0.8.0", "rdkit_version": "2026.03.6", "atom_typing": "ad4",
               "charges": "gasteiger"}
BOX = {"center_A": [3.4095, 0.7175, 11.314], "size_A": [22.321, 27.507, 27.6], "source": "ligand_range",
       "margin_A": 8.0}
RECORD_KEYS = ("candidate_id", "origin", "parent_candidate_id", "similarity", "evaluation", "eval_index")


def _handle(n: int) -> str:
    return f"obj://run_g/docking_result/{n:064d}"


def _result(sel: dict, scores: list[float]) -> dict:
    """A docking_result@1-shaped dict for one individual (only what the GA checks read is meaningful)."""
    args = sel["arguments"]
    ligand = {"source": "candidate", "sdf_handle": None, "sdf_sha256": None,
              "candidate_set_handle": args["ligand"]["candidate_set_handle"],
              "candidate_id": args["ligand"]["candidate_id"],
              "parent_sdf_handle": args["ligand"]["parent_sdf_handle"],
              "parent_sdf_sha256": sel["ligand"]["parent_sdf"]["sha256"],
              "generated": {"hydrogens": True, "coordinates": True}, "stereo_flag": "none",
              "unspecified_stereo_centers": 0}
    modes = [{"mode": i + 1, "score_kcal_mol": s} for i, s in enumerate(scores)]
    return {"schema": "docking_result@1", "protocol": "qvina_dock_v1", "method": C.METHODS["free"],
            "input_sha256": sel["input_sha256"],
            "inputs": {"receptor": {"handle": args["receptor_handle"], "sha256": sel["receptor"]["sha256"],
                                    "model_number": 1, "connectivity": args["connectivity"],
                                    "removed_instance": None, "acknowledgement": args["acknowledgement"]},
                       "ligand": ligand, "mode": "free"},
            "box": copy.deepcopy(BOX), "parameters": {**args["parameters"], "cpu": 1}, "engine": dict(ENGINE),
            "preparation": dict(PREPARATION), "modes": modes,
            "counts": {"modes": len(modes), "null_result": not modes}, "limitations": []}


def _world(name: str, expected: dict | None = None, **ga_changes) -> dict:
    """Selection, worker records, observations and stored results that reproduce one oracle vector (or the given
    ``expected`` path over that vector's pool)."""
    vector = VECTORS[name]
    ga = {**vector["ga"], **ga_changes}
    normalized = _validate(_args(ga=ga))
    eligible = vector.get("eligible", [True] * len(IDS))
    pool = [{"index": i, "candidate_id": cid, "eligible": ok} for i, (cid, ok) in enumerate(zip(IDS, eligible,
                                                                                                  strict=True))]
    first = next(p["candidate_id"] for p in pool if p["eligible"])
    selected = GI.ga_selection(normalized, pool, _representative(normalized, first))
    expected = vector["expected"] if expected is None else expected
    records, observations, results, selections = [], {}, {}, {}
    for gen in expected["generations"]:
        records.append({"index": gen["index"], "complete": gen["complete"],
                        "individuals": [{key: entry[key] for key in RECORD_KEYS} for entry in gen["individuals"]]})
        for entry in gen["individuals"]:
            if entry["origin"] == "carried":
                continue
            cid, k = entry["candidate_id"], entry["eval_index"]
            selections[cid] = GI.individual_selection(selected, ROWS[cid])
            if entry["state"] == "failed":
                observations[k] = {"status": {"state": "failed", "reason_code": "engine_failed"},
                                   "result_handle": None}
                continue
            handle = _handle(k + 1)
            score = entry["score"]
            results[handle] = _result(selections[cid], [] if score is None else [score, score + 0.5])
            observations[k] = {"status": {"state": entry["state"], "reason_code": None}, "result_handle": handle}
    return {"selected": selected, "records": records, "observations": observations, "results": results,
            "selections": selections, "stop_reason": expected["stop_reason"], "expected": expected}


def _build(world: dict, **changes) -> dict:
    kwargs = {"records": world["records"], "observations": world["observations"], "results": world["results"],
              "individual_selections": world["selections"], "stop_reason": world["stop_reason"], "box": BOX,
              "m18_pins": PINS, "ga_pins": GA_PINS, **changes}
    return GB.build_summary(world["selected"], **kwargs)


def _check(world: dict, content: dict) -> None:
    GB.check_summary(content, world["selected"], world["selections"], world["results"], PINS, GA_PINS)


def _refused(world: dict, content: dict) -> None:
    with pytest.raises(GB.LigandGaEvidenceError):
        _check(world, content)


# ---------------------------------------------------------------- oracle paths become valid summaries


@pytest.mark.parametrize("name", list(VECTORS))
def test_every_oracle_path_builds_and_validates(name):
    world = _world(name)
    out = _build(world)
    exp = world["expected"]
    assert (out["status"], out["stop_reason"], out["generations_done"], out["new_dockings_used"],
            out["reused_count"]) == (exp["status"], exp["stop_reason"], exp["generations_done"],
                                     exp["new_dockings_used"], exp["reused_count"])
    assert len(out["generations"]) == len(exp["generations"])
    for got, want in zip(out["generations"], exp["generations"], strict=True):
        assert (got["index"], got["complete"], got["min_score"], got["max_score"]) == \
            (want["index"], want["complete"], want["min_score"], want["max_score"])
        assert [{key: e[key] for key in (*RECORD_KEYS, "score", "state")} for e in got["individuals"]] == \
            want["individuals"]
    _check(world, out)
    assert canonical_json(_build(_world(name))) == canonical_json(out)            # same inputs, same summary


def test_summary_fields_and_g_sentences():
    world = _world("small_observed_seed7")
    out = _build(world)
    sel = world["selected"]
    assert set(out) == {"schema", "protocol", "engine", "candidate_set_handle", "parent_sdf_handle", "receptor",
                        "pins", "call_key", "selection_sha256", "box", "parameters", "filter", "ga", "pool",
                        "status", "stop_reason", "generations_done", "new_dockings_used", "reused_count",
                        "reserved_units", "generations", "limitations"}
    assert (out["schema"], out["protocol"], out["engine"]) == ("ligand_ga_result@1", "qvina_ga_dock_v1", "qvina")
    assert out["receptor"] == {"handle": sel["arguments"]["receptor_handle"], "sha256": sel["receptor"]["sha256"],
                               "model_number": 1, "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
                               "removed_instance": None, "acknowledgement": sel["arguments"]["acknowledgement"]}
    assert out["pins"] == {**GA_PINS, "worker_sha256": PINS["worker_sha256"],
                           "constants_sha256": PINS["constants_sha256"], "qvina_sha256": PINS["qvina_sha256"],
                           "qvina_package": PINS["qvina_package"]}
    assert out["selection_sha256"] == sel["selection_sha256"]
    assert out["call_key"] == GB.call_key(sel, PINS, GA_PINS) != sel["selection_sha256"]
    assert out["parameters"] == {**sel["arguments"]["parameters"], "cpu": 1}
    assert out["filter"] == {"ranges": {}, "pains_exclude": False} and out["ga"] == sel["arguments"]["ga"]
    assert out["pool"] == {"size": 10, "eligible_count": 10, "filter_excluded_count": 0}
    assert out["reserved_units"] == min(10, 4 + 2 * 3) == 10
    assert out["limitations"] == ["G1"]
    assert _build(_world("small_observed_limit5"))["limitations"] == ["G1", "G2"]
    assert _build(_world("small_observed_seed7_reuse_two"))["limitations"] == ["G1", "G3"]
    assert _build(_world("small_observed_limit5_reuse_two"))["limitations"] == ["G1", "G2", "G3"]


def test_carried_cites_the_first_evaluation():
    out = _build(_world("small_observed_seed7"))
    first = {e["candidate_id"]: e for g in out["generations"] for e in g["individuals"] if e["origin"] != "carried"}
    carried = [e for g in out["generations"] for e in g["individuals"] if e["origin"] == "carried"]
    assert carried
    for entry in carried:
        src = first[entry["candidate_id"]]
        assert (entry["score"], entry["result_handle"], entry["state"]) == (src["score"], src["result_handle"],
                                                                            "scored")
        assert entry["evaluation"] is None and entry["eval_index"] is None


def test_unscored_individuals_have_no_score_and_failed_keeps_its_reason():
    out = _build(_world("synthetic_ties_nulls"))
    entries = [e for g in out["generations"] for e in g["individuals"]]
    failed = [e for e in entries if e["state"] == "failed"]
    null = [e for e in entries if e["state"] == "null_result"]
    assert len(failed) == 1 and len(null) == 1
    assert failed[0]["score"] is None and failed[0]["result_handle"] is None
    assert failed[0]["reason_code"] == "engine_failed"
    assert null[0]["score"] is None and null[0]["result_handle"] is not None and null[0]["reason_code"] is None


def test_carried_count_is_what_scored_individuals_allow():
    out = _build(_world("synthetic_no_scored_parent"))
    # nothing scored in generation 1: no carried individual, every slot random (stopped at reserved_units, below)
    assert [e["origin"] for e in out["generations"][1]["individuals"]] == ["random"] * 2
    assert out["generations"][0]["min_score"] is None and out["generations"][0]["max_score"] is None


# ---------------------------------------------------------------- observations -> individual states


def test_scored_status_without_a_publishable_result_is_engine_output_invalid():
    world = _world("small_observed_seed7")
    world["observations"][2] = {"status": {"state": "scored", "reason_code": None}, "result_handle": None}
    out = _build(world)
    entry = next(e for e in out["generations"][0]["individuals"] if e["eval_index"] == 2)
    assert (entry["state"], entry["reason_code"], entry["score"]) == ("failed", "engine_output_invalid", None)


def test_no_status_and_no_result_is_worker_failed():
    world = _world("small_observed_limit5")
    world["observations"][4] = {"status": None, "result_handle": None}
    out = _build(world)
    entry = next(e for g in out["generations"] for e in g["individuals"] if e["eval_index"] == 4)
    assert (entry["state"], entry["reason_code"]) == ("failed", "worker_failed")


@pytest.mark.parametrize("bad", [
    {"status": {"state": "null_result", "reason_code": None}, "result_handle": "SAME"},
    {"status": {"state": "failed", "reason_code": "not_a_reason"}, "result_handle": None},
    {"status": {"state": "cancelled", "reason_code": None}, "result_handle": None},
    {"status": None, "result_handle": "obj://run_g/docking_result/" + "f" * 64},
    {"status": None},
])
def test_inconsistent_observations_are_refused(bad):
    world = _world("small_observed_seed7")
    bad = dict(bad)
    if bad.get("result_handle") == "SAME":
        bad["result_handle"] = world["observations"][0]["result_handle"]   # a scored result
    world["observations"][0] = bad
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world)


def test_missing_observation_or_selection_is_refused():
    world = _world("small_observed_seed7")
    del world["observations"][5]
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world)
    world = _world("small_observed_seed7")
    world["selections"].pop(IDS[0])
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world)


@pytest.mark.parametrize("stop", ["", "complete", "best", None])
def test_unknown_stop_reason_refused(stop):
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(_world("small_observed_seed7"), stop_reason=stop)


# ---------------------------------------------------------------- check_summary rejections


@pytest.fixture
def seed7():
    world = _world("small_observed_seed7")
    return world, _build(world)


@pytest.mark.parametrize("key", ["rank", "best", "improved", "score_diff", "diff", "best_score", "recommended"])
def test_rank_diff_best_improved_fields_are_refused_at_every_level(seed7, key):
    world, out = seed7
    for where in ("top", "generation", "individual"):
        bad = copy.deepcopy(out)
        target = {"top": bad, "generation": bad["generations"][1],
                  "individual": bad["generations"][1]["individuals"][1]}[where]
        target[key] = 1
        _refused(world, bad)


def test_score_must_equal_the_stored_first_mode(seed7):
    world, out = seed7
    bad = copy.deepcopy(out)
    bad["generations"][0]["individuals"][0]["score"] += 0.1
    _refused(world, bad)
    bad = copy.deepcopy(out)
    entry = bad["generations"][2]["individuals"][1]
    entry["score"] = int(entry["score"])
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][0]["individuals"][0]["score"] = None
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][0]["individuals"][0]["score"] = 0.0                  # no score is never 0
    _refused(world, bad)


def test_result_must_be_the_individuals_own_m18_input(seed7):
    world, out = seed7
    bad = copy.deepcopy(out)
    a, b = bad["generations"][0]["individuals"][0], bad["generations"][0]["individuals"][1]
    a["result_handle"] = b["result_handle"]
    a["score"] = b["score"]
    _refused(world, bad)
    results = copy.deepcopy(world["results"])
    results[out["generations"][0]["individuals"][0]["result_handle"]]["box"]["margin_A"] = 7.0
    with pytest.raises(GB.LigandGaEvidenceError):
        GB.check_summary(out, world["selected"], world["selections"], results, PINS, GA_PINS)


def test_carried_must_be_the_lowest_score_elites_in_pool_order(seed7):
    world, out = seed7
    gen2 = out["generations"][1]["individuals"]
    assert gen2[0]["origin"] == "carried"
    # replace the carried individual with another scored individual of generation 1 (not the lowest score)
    bad = copy.deepcopy(out)
    other = next(e for e in out["generations"][0]["individuals"] if e["candidate_id"] != gen2[0]["candidate_id"])
    bad["generations"][1]["individuals"][0].update(candidate_id=other["candidate_id"], score=other["score"],
                                                   result_handle=other["result_handle"])
    _refused(world, bad)
    # carried with a score that is not its first evaluation's
    bad = copy.deepcopy(out)
    bad["generations"][1]["individuals"][0]["score"] -= 1.0
    _refused(world, bad)
    # carried dropped (elite_count 1 with scored individuals available)
    bad = copy.deepcopy(out)
    bad["generations"][1]["individuals"][0]["origin"] = "random"
    _refused(world, bad)
    # carried with an evaluation or an eval_index
    for key, value in (("evaluation", "reused"), ("eval_index", 99)):
        bad = copy.deepcopy(out)
        bad["generations"][1]["individuals"][0][key] = value
        _refused(world, bad)


def test_carried_ties_follow_pool_order():
    world = _world("synthetic_ties_nulls")
    out = _build(world)
    gen3 = out["generations"][2]["individuals"]
    # -7.5 twice in generation 2 (pool positions 3 and 5): pool order carries position 3
    assert [e["candidate_id"] for e in gen3 if e["origin"] == "carried"] == [IDS[8], IDS[3]]
    bad = copy.deepcopy(out)
    src = next(e for e in out["generations"][1]["individuals"] if e["candidate_id"] == IDS[5])
    bad["generations"][2]["individuals"][1].update(candidate_id=IDS[5], result_handle=src["result_handle"])
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][2]["individuals"][0], bad["generations"][2]["individuals"][1] = \
        bad["generations"][2]["individuals"][1], bad["generations"][2]["individuals"][0]
    _refused(world, bad)


def test_non_carried_ids_are_unique_in_a_run(seed7):
    world, out = seed7
    bad = copy.deepcopy(out)
    dup = bad["generations"][0]["individuals"][1]
    entry = bad["generations"][2]["individuals"][3]
    entry.update(candidate_id=dup["candidate_id"], result_handle=dup["result_handle"], score=dup["score"])
    _refused(world, bad)


def test_individuals_must_be_eligible_pool_candidates():
    world = _world("synthetic_filter_excluded")
    out = _build(world)
    _check(world, out)
    excluded = {p["candidate_id"] for p in world["selected"]["pool"] if not p["eligible"]}
    assert excluded and not excluded & {e["candidate_id"] for g in out["generations"] for e in g["individuals"]}
    assert out["pool"] == {"size": 10, "eligible_count": 7, "filter_excluded_count": 3}
    bad_world = _world("synthetic_filter_excluded")
    bad_world["selected"]["pool"][IDS.index(out["generations"][0]["individuals"][0]["candidate_id"])][
        "eligible"] = False
    bad_world["selected"]["pool_sha256"] = GI.pool_sha256(bad_world["selected"]["pool"])
    bad_world["selected"]["selection_sha256"] = GI.selection_sha256(bad_world["selected"])
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(bad_world)                                 # hashes consistent: the refusal is the eligibility


def test_eval_index_is_the_run_evaluation_order(seed7):
    world, out = seed7
    bad = copy.deepcopy(out)
    bad["generations"][1]["individuals"][1]["eval_index"] = 9
    _refused(world, bad)
    bad = copy.deepcopy(out)
    gen = bad["generations"][0]["individuals"]
    gen[0], gen[1] = gen[1], gen[0]
    _refused(world, bad)


def test_origin_order_and_generation_one(seed7):
    world, out = seed7
    bad = copy.deepcopy(out)
    bad["generations"][1]["individuals"][3]["origin"] = "initial"
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][0]["individuals"][0]["origin"] = "random"
    _refused(world, bad)
    bad = copy.deepcopy(out)
    gen = bad["generations"][1]["individuals"]
    gen[3]["origin"], gen[1]["origin"] = "similar", "random"   # random before similar
    gen[1]["parent_candidate_id"], gen[1]["similarity"] = None, None
    gen[3]["parent_candidate_id"], gen[3]["similarity"] = IDS[0], "0.500000"
    _refused(world, bad)


def test_similar_fields_are_shape_checked_only(seed7):
    world, out = seed7
    entry_path = (1, 1)
    ok = copy.deepcopy(out)
    ok["generations"][entry_path[0]]["individuals"][entry_path[1]]["similarity"] = "0.123456"
    _check(world, ok)                                   # the server does not recompute fingerprints (G1)
    for field, value in (("similarity", 0.833333), ("similarity", "0.83333"), ("similarity", "1.5"),
                         ("similarity", None), ("parent_candidate_id", None), ("parent_candidate_id", 3)):
        bad = copy.deepcopy(out)
        bad["generations"][entry_path[0]]["individuals"][entry_path[1]][field] = value
        _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][1]["individuals"][3]["similarity"] = "0.500000"        # random slot
    _refused(world, bad)


def test_counts_and_caps(seed7):
    world, out = seed7
    for key, value in (("new_dockings_used", 9), ("reused_count", 1), ("generations_done", 2),
                       ("reserved_units", 9)):
        bad = copy.deepcopy(out)
        bad[key] = value
        _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][1]["min_score"] = -6.4
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][1]["max_score"] = None
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["pool"]["eligible_count"] = 9
    _refused(world, bad)


def test_more_new_dockings_than_the_cap_is_refused():
    # the seed-7 path docks 10; under max_new_dockings 9 it cannot be a valid summary
    world = _world("small_observed_seed7", max_new_dockings=9)
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world)


def test_new_dockings_are_capped_at_reserved_units():
    # spec 3/6: no carried individual makes generation 2 open P slots (> P - E); new dockings stop at
    # reserved_units = min(20, 4 + 1 * (4 - 2)) = 6, below max_new_dockings 20
    exp = VECTORS["synthetic_no_scored_parent"]["expected"]
    assert (exp["stop_reason"], exp["status"], exp["new_dockings_used"], exp["generations_done"]) == \
        ("docking_limit", "partial", 6, 1)
    assert [g["complete"] for g in exp["generations"]] == [True, False]
    assert len(exp["generations"][1]["individuals"]) == 2
    world = _world("synthetic_no_scored_parent")
    out = _build(world)
    assert out["reserved_units"] == 6 < out["ga"]["max_new_dockings"] and out["new_dockings_used"] == 6
    # the pre-amendment path (all four generation-2 slots docked, 8 new) is not a valid summary
    over = copy.deepcopy(exp)
    over.update(stop_reason="generations_complete", status="complete", generations_done=2, new_dockings_used=8)
    gen2 = over["generations"][1]
    gen2["complete"] = True
    for k, cid in enumerate(("c_1afb7cd3e603456c", "c_9d4897ac9ecdb2d4"), start=6):
        gen2["individuals"].append({"candidate_id": cid, "origin": "random", "parent_candidate_id": None,
                                    "similarity": None, "evaluation": "docked", "eval_index": k, "score": None,
                                    "state": "null_result"})
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(_world("synthetic_no_scored_parent", expected=over))


def test_docking_limit_is_checked_against_reserved_units():
    world = _world("synthetic_no_scored_parent")
    out = _build(world)
    _check(world, out)                                    # 6 new = reserved_units 6 < max_new_dockings 20
    bad = copy.deepcopy(out)
    bad["reserved_units"] = 20
    _refused(world, bad)
    with pytest.raises(GB.LigandGaEvidenceError):         # reserved 4 + 1 * (4 - 1) = 7: the cap was not reached
        _build(_world("synthetic_no_scored_parent", elite_count=1))


def test_no_change_is_not_evaluated_at_the_last_generation():
    # synthetic_no_change stops at generation 2 with patience 1; with generations 2 the same path is
    # generations_complete (spec 3 step 4: the last generation is generations_complete, no_change is not looked at)
    world = _world("synthetic_no_change", generations=2)
    _check(world, _build(world, stop_reason="generations_complete"))
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world, stop_reason="no_change")


def _first_generations(name: str, count: int, **ga_changes) -> dict:
    """The world of an oracle vector's first ``count`` generations (records, observations and selections cut)."""
    expected = copy.deepcopy(VECTORS[name]["expected"])
    expected["generations"] = expected["generations"][:count]
    return _world(name, expected=expected, **ga_changes)


def test_patience_must_agree_with_the_generation_minimums():
    # seed 8: minimum -10.1 at every generation; with patience 1 the run ends after generation 2 with no_change
    world = _world("small_observed_seed8", patience=1)
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world)                                     # a generation after the no_change point
    two = _first_generations("small_observed_seed8", 2, patience=1)
    _check(two, _build(two, stop_reason="no_change"))
    with pytest.raises(GB.LigandGaEvidenceError):         # patience reached: a complete stop must be no_change
        _build(two, stop_reason="pool_exhausted")
    _check(two, _build(two, stop_reason="cancelled"))     # a stop from outside the worker at that point
    # seed 7: the minimum decreases at generations 2 and 3, so patience 1 never stops it
    seed7 = _world("small_observed_seed7", patience=1)
    _check(seed7, _build(seed7))
    seed7_two = _first_generations("small_observed_seed7", 2, patience=1)
    _check(seed7_two, _build(seed7_two, stop_reason="cancelled"))
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(seed7_two, stop_reason="no_change")


def test_patience_null_minimum_comparison():
    # null -> null is not a decrease: patience 1 stops after generation 2
    nulls = VECTORS["synthetic_null_null_no_change"]["expected"]
    assert (nulls["stop_reason"], nulls["generations_done"]) == ("no_change", 2)
    assert [g["min_score"] for g in nulls["generations"]] == [None, None]
    world = _world("synthetic_null_null_no_change")
    _check(world, _build(world))
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world, stop_reason="pool_exhausted")
    # null -> a number is a decrease: patience 1 does not stop after generation 2
    first = VECTORS["synthetic_null_then_score"]["expected"]
    assert first["generations"][0]["min_score"] is None and first["generations"][1]["min_score"] is not None
    assert first["generations_done"] >= 3 and first["stop_reason"] != "no_change"
    two = _first_generations("synthetic_null_then_score", 2)
    _check(two, _build(two, stop_reason="cancelled"))
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(two, stop_reason="no_change")


def test_generation_size_cap():
    world = _world("small_observed_seed7")
    out = _build(world)
    bad = copy.deepcopy(out)
    bad["generations"][1]["individuals"].append(copy.deepcopy(bad["generations"][1]["individuals"][0]))
    _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["generations"][0]["individuals"].pop()           # a complete generation 1 has population_size individuals
    _refused(world, bad)


@pytest.mark.parametrize(("status", "stop"), [("complete", "docking_limit"), ("partial", "generations_complete"),
                                              ("complete", "cancelled"), ("partial", "no_change"),
                                              ("complete", "rank")])
def test_status_must_match_stop_reason(seed7, status, stop):
    world, out = seed7
    bad = copy.deepcopy(out)
    bad["status"], bad["stop_reason"] = status, stop
    _refused(world, bad)


def test_stop_reason_structure():
    # generations_complete needs every generation; docking_limit needs the cap reached; a complete run has no
    # incomplete generation; only the last generation of a partial run can be incomplete.
    world = _world("small_observed_limit5")
    out = _build(world)
    _check(world, out)
    _refused(world, {**out, "stop_reason": "generations_complete", "status": "complete"})
    bad = copy.deepcopy(out)
    bad["generations"][1]["complete"] = True
    bad["generations_done"] = 2
    _refused(world, bad)                                  # docking_limit with every generation done
    time_out = _build(world, stop_reason="time_exhausted")
    _check(world, time_out)                               # time can stop anywhere
    assert time_out["status"] == "partial" and "G2" in time_out["limitations"]
    seed = _world("small_observed_seed7")                 # 10 new = max 10, but nothing was left to evaluate
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(seed, stop_reason="docking_limit")
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(_world("small_observed_limit5_reuse_two", max_new_dockings=6), stop_reason="docking_limit")
    bad = copy.deepcopy(_build(seed))
    bad["generations"][0]["complete"] = False
    bad["generations_done"] = 2
    _refused(seed, bad)                                   # only the last generation can be incomplete
    one = _first_generations("synthetic_no_change", 1)
    _check(one, _build(one, stop_reason="cancelled"))
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(one, stop_reason="no_change")              # no_change needs patience generations after generation 1


def test_identity_hashes_and_pins_are_checked(seed7):
    world, out = seed7
    for key, value in (("call_key", "0" * 64), ("selection_sha256", "0" * 64), ("engine", "vina"),
                       ("candidate_set_handle", "obj://x"), ("protocol", "qvina_batch_dock_v1"),
                       ("schema", "ligand_ga_result@2")):
        bad = copy.deepcopy(out)
        bad[key] = value
        _refused(world, bad)
    bad = copy.deepcopy(out)
    bad["pins"]["ga_worker_sha256"] = "8" * 64
    _refused(world, bad)
    with pytest.raises(GB.LigandGaEvidenceError):
        GB.check_summary(out, world["selected"], world["selections"], world["results"],
                         {**PINS, "qvina_sha256": "9" * 64}, GA_PINS)
    for key, value in (("box", {**BOX, "margin_A": 7.0}), ("parameters", {"seed": 1}),
                       ("ga", {**out["ga"], "seed": 8}), ("filter", {"ranges": {}, "pains_exclude": True}),
                       ("limitations", ["G1", "G2"]), ("limitations", [])):
        bad = copy.deepcopy(out)
        bad[key] = value
        _refused(world, bad)


def test_reused_individual_needs_its_stored_result():
    world = _world("small_observed_seed7_reuse_two")
    out = _build(world)
    _check(world, out)
    reused = [e for g in out["generations"] for e in g["individuals"] if e["evaluation"] == "reused"]
    assert len(reused) == 2 and all(e["result_handle"] for e in reused)
    bad = copy.deepcopy(out)
    entry = next(e for e in bad["generations"][1]["individuals"] if e["evaluation"] == "reused")
    entry.update(state="failed", reason_code="engine_failed", score=None, result_handle=None)
    _refused(world, bad)


def test_failed_reason_set(seed7):
    world, out = seed7
    bad = copy.deepcopy(out)
    entry = bad["generations"][0]["individuals"][0]
    entry["reason_code"] = "engine_failed"                  # a scored individual has no reason
    _refused(world, bad)
    for reason in GC.FAILED_EXTRA_REASONS + ("engine_failed", "receptor_prep_failed"):
        world2 = _world("small_observed_seed7")
        world2["observations"][3] = {"status": {"state": "failed", "reason_code": reason}, "result_handle": None}
        _check(world2, _build(world2))
    world3 = _world("small_observed_seed7")
    world3["observations"][3] = {"status": {"state": "failed", "reason_code": "time_exhausted"},
                                 "result_handle": None}
    with pytest.raises(GB.LigandGaEvidenceError):
        _build(world3)


def test_summary_size_bound(seed7, monkeypatch):
    world, out = seed7
    monkeypatch.setattr(GC, "MAX_SUMMARY_BYTES", len(canonical_json(out)) - 1)
    _refused(world, out)


# ---------------------------------------------------------------- call key and duplicates (spec 6)


def test_call_key_tracks_inputs_and_pins():
    sel = _world("small_observed_seed7")["selected"]
    key = GB.call_key(sel, PINS, GA_PINS)
    assert key == GB.call_key(copy.deepcopy(sel), PINS, GA_PINS)
    assert GB.call_key(_world("small_observed_seed8")["selected"], PINS, GA_PINS) != key
    assert GB.call_key(sel, {**PINS, "worker_sha256": "9" * 64}, GA_PINS) != key
    assert GB.call_key(sel, PINS, {**GA_PINS, "ga_constants_sha256": "9" * 64}) != key


def test_complete_duplicate_only_for_complete():
    done = _build(_world("small_observed_seed7"))
    part = _build(_world("small_observed_limit5"))
    assert GB.complete_duplicate([("h1", part), ("h2", done)], done["call_key"]) == "h2"
    assert GB.complete_duplicate([("h1", part)], part["call_key"]) is None
