"""M23 T2 GA summary ``sequence_ga_result@1``: selection record, building from worker records and server
observations, and the pure ``validated_summary`` (spec .dryforge/spec.md 3, 4, 7).

Paths come from the INDEPENDENT T1 oracle (``fixtures/sequence_ga/independent_sequence_ga_oracle.py``, standard
library only, never the module under test): the committed ``expected.json`` vectors on the real tiny M20 set and
further oracle runs on the same set with LABELED SYNTHETIC score tables (selection-logic inputs, not docking values).
Models and docking results are SYNTHETIC-FIXTURE contents (``sequence_ga_fixture``); their scores are the score
table's values. The oracle names first-generation individuals ``random``; spec 3 step 2 names them ``initial``
(the spec wins), so the records here carry ``initial`` (reported as a T1 oracle / spec difference).
"""
from __future__ import annotations

import copy
import hashlib
import sys

import pytest
import sequence_ga_fixture as SF

from mw import sequence_ga_bundle as GB
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw import sequence_model_bundle as SM

sys.path.insert(0, str(SF.GA_FIX))
import independent_sequence_ga_oracle as ORACLE

TINY = SF.TINY["content"]
TINY_HANDLE = SF.TINY["handle"]
SPACE = SF.EXPECTED["spaces"]["s4_tiny_1ubq"]
VECTORS = SF.EXPECTED["vectors"]
SDF_HANDLE = f"obj://{SF.RUN_ID}/chemical_raw_input/" + "b" * 64
SDF_SHA = hashlib.sha256(SF.PHENOL).hexdigest()
BOX = {"center_A": [23.66925, 36.57215, 24.91205], "size_A": [19.9493, 18.3231, 17.3431], "source": "ligand_range",
       "margin_A": 8.0}
RECORD_KEYS = ("key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index")
ORACLE_KEYS = (*RECORD_KEYS, "state", "reason_code", "score")
SMALL = {"crossover_fraction": 0.5, "elite_count": 1, "generations": 3, "max_mutations": 3, "max_new_evaluations": 32,
         "patience": 2, "population_size": 4, "random_fraction": 0.25, "seed": 5, "total_s": 7200,
         "tournament_size": 2}
_MODELS: dict[str, tuple[dict, bytes]] = {}


def _normalized(ga: dict) -> dict:
    args = {"candidate_set": TINY_HANDLE, "ligand": {"source": "sdf", "sdf_handle": SDF_HANDLE},
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": {"seed": 42, "exhaustiveness": 4,
                                                                            "num_modes": 5},
            "selection_policy": SC.SELECTION_POLICY, "hydrogen_policy": SC.HYDROGEN_POLICY,
            "acknowledgement": dict(SF.ACK), "ga": dict(ga)}
    normalized = GI.validate_arguments(args, ga["total_s"] + 600)
    normalized["box"] = GI.request_box(normalized["box"])
    return normalized


def _model(key: str | None) -> tuple[dict, bytes]:
    name = key or SC.REFERENCE_KEY
    if name not in _MODELS:
        mutations = [] if key is None else SM.model_mutations(TINY, key)
        entry, cif = SF.synthetic_entry({m["residue"]["seq_auth"]: m["mutant_resname"] for m in mutations})
        reference = None if key is None else _model(None)[0]
        _MODELS[name] = (SM.model_content(run_id=SF.RUN_ID, candidate_set_handle=TINY_HANDLE,
                                          structure=SF.structure_record(), mutations=mutations, seed=42,
                                          method=SF.model_method(), entry=entry, cif_raw=cif, reference=reference),
                         cif)
    return _MODELS[name]


def _records(expected: dict) -> list[dict]:
    """The worker generation records of an oracle path (first generation ``initial``, spec 3 step 2)."""
    out = []
    for generation in expected["generations"]:
        out.append({"index": generation["index"], "complete": generation["complete"], "individuals": [
            {**{key: entry[key] for key in RECORD_KEYS},
             "origin": "initial" if generation["index"] == 1 else entry["origin"]}
            for entry in generation["individuals"]]})
    return out


class World:
    """One GA run's stored facts: selection, pins, models, results, observations, worker records and the summary."""

    def __init__(self, ga: dict, scores: dict, expected: dict, *, reusable=(), stop_reason=None, records=None):
        self.ga, self.scores, self.expected = ga, scores, expected
        self.normalized = _normalized(ga)
        self.selected = GB.selection_record({"arguments": self.normalized, "structure": SF.structure_record(),
                                             "ligand": {"sdf_handle": SDF_HANDLE, "sdf_sha256": SDF_SHA},
                                             "space": GI.candidate_space(TINY, ga["max_mutations"])})
        self.pins = SF.pins()
        self.models: dict[str, dict] = {}
        self.cifs: dict[str, bytes] = {}
        self.results: dict[str, dict] = {}
        self.handles: dict[str, tuple] = {}
        self.reference = {"evaluation": "reused" if SC.REFERENCE_KEY in reusable else "computed",
                          **self._observe(None)}
        self.observations = {}
        for generation in expected["generations"]:
            for entry in generation["individuals"]:
                if entry["origin"] != "carried":
                    self.observations[entry["key"]] = self._observe(entry["key"])
        self.records = _records(expected) if records is None else records
        self.stop_reason = stop_reason or expected["stop_reason"]
        self.summary = GB.build_summary(
            self.selected, candidate_set=TINY, records=self.records, reference=self.reference,
            observations=self.observations, results=self.results, models=self.models, stop_reason=self.stop_reason,
            box=BOX, pins=self.pins)

    def _observe(self, key: str | None) -> dict:
        row = self.scores[key or SC.REFERENCE_KEY]
        model, cif = _model(key)
        handle = SF.model_handle(model)
        side = SC.MUTANT_SIDE if key else SC.REFERENCE_SIDE
        failed_model = row["state"] == "failed" and row["reason_code"] in (*SC.MODEL_FAILURE_REASONS,
                                                                           "model_timeout", "worker_failed")
        model_handle = None if failed_model else handle
        if model_handle is not None:
            self.models[handle], self.cifs[handle] = model, cif
        result_handle = None
        if row["state"] != "failed":
            result = SF.synthetic_result(self.normalized, handle, model, side, BOX, row.get("score"), SDF_SHA)
            result_handle = SF.object_handle("docking_result", "docking_result@1", result)
            self.results[result_handle] = result
        self.handles[key or SC.REFERENCE_KEY] = (model_handle, result_handle)
        return {"state": row["state"], "reason_code": row.get("reason_code"), "model_handle": model_handle,
                "result_handle": result_handle}

    def validate(self, summary=None):
        return GB.validated_summary(self.summary if summary is None else summary, selected=self.selected,
                                    candidate_set=TINY, results=self.results, models=self.models, pins=self.pins)


def _oracle_world(ga: dict, scores: dict, reusable=()) -> World:
    return World(ga, scores, ORACLE.run_ga(SPACE, scores, list(reusable), ga), reusable=reusable)


def _vector_world(name: str) -> World:
    vector = VECTORS[name]
    return World(vector["ga"], vector["scores"], vector["expected"], reusable=vector["reusable"])


def _table(rule) -> dict:
    """A SYNTHETIC score table over every key of the tiny space plus the reference row."""
    keys = SPACE["canonical_at_cap"]
    table = {key: rule(position, key) for position, key in enumerate(keys)}
    table[SC.REFERENCE_KEY] = {"state": "scored", "reason_code": None, "score": -3.0}
    return table


def _scored(score):
    return {"state": "scored", "reason_code": None, "score": score}


FAILURES = ("coordinates_changed", "receptor_prep_failed", "model_timeout", "docking_timeout", "worker_failed",
            "ligand_hydrogens_missing", "energy_invalid")
SCENARIOS = {
    "repeated_failure": (SMALL, _table(lambda i, k: {"state": "failed", "reason_code": FAILURES[i % 7],
                                                     "score": None})),
    "evaluation_limit": ({**SMALL, "max_new_evaluations": 4, "elite_count": 1},
                         _table(lambda i, k: _scored(-2.0 - 0.1 * (i % 5)))),
    "space_exhausted": ({**SMALL, "max_mutations": 1}, _table(lambda i, k: _scored(-2.5 - 0.1 * i))),
    "null_and_failed": ({**SMALL, "generations": 4, "seed": 9},
                        _table(lambda i, k: {"state": "null_result", "reason_code": None, "score": None} if i % 4 == 1
                               else {"state": "failed", "reason_code": "receptor_prep_failed", "score": None}
                               if i % 4 == 2 else _scored(-2.0 - 0.1 * (i % 3)))),
    "ties": ({**SMALL, "generations": 4, "elite_count": 2, "seed": 3}, _table(lambda i, k: _scored(-3.0))),
}


@pytest.fixture(scope="module")
def synthetic():
    return _vector_world("s4_tiny_synthetic")


@pytest.fixture(scope="module")
def reused():
    return _vector_world("s4_tiny_observed_reuse")


# ---------------------------------------------------------------- selection record


def test_selection_record_holds_request_facts_and_counts_only(synthetic):
    selected = synthetic.selected
    assert set(selected) == {"schema", "arguments", "structure", "ligand", "space", "selection_sha256"}
    assert selected["schema"] == "sequence_ga_selection@1"
    assert selected["space"] == {"positions": 3, "candidates": 6, "effective_max_mutations": 3, "size": 26}
    assert selected["selection_sha256"] == GI.selection_sha256(selected)
    assert "candidates" not in selected["arguments"] and len(str(selected)) < 4000


# ---------------------------------------------------------------- oracle paths


def _project(summary: dict) -> list[list[dict]]:
    return [[{key: entry[key] for key in ORACLE_KEYS} for entry in generation["individuals"]]
            for generation in summary["generations"]]


def _oracle_projection(expected: dict) -> list[list[dict]]:
    return [[{**{key: entry[key] for key in ORACLE_KEYS},
              "origin": "initial" if generation["index"] == 1 else entry["origin"]}
             for entry in generation["individuals"]] for generation in expected["generations"]]


def _check_against_oracle(world: World) -> None:
    summary, expected = world.summary, world.expected
    assert _project(summary) == _oracle_projection(expected)
    for field in ("status", "stop_reason", "generations_done", "new_evaluations_used", "reused_count",
                  "reserved_evaluations", "reserved_units", "space"):
        assert summary[field] == expected[field], field
    assert {key: summary["reference"][key] for key in ("evaluation", "state", "reason_code", "score")} == \
        expected["reference"]
    assert [(g["min_score"], g["max_score"]) for g in summary["generations"]] == \
        [(g["min_score"], g["max_score"]) for g in expected["generations"]]
    assert world.validate() is summary


@pytest.mark.parametrize("name", ["s4_tiny_synthetic", "s4_tiny_observed", "s4_tiny_observed_reuse"])
def test_committed_oracle_vectors_build_and_validate(name):
    _check_against_oracle(_vector_world(name))


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_further_oracle_paths_build_and_validate(name):
    ga, scores = SCENARIOS[name]
    world = _oracle_world(ga, scores)
    _check_against_oracle(world)
    assert world.summary["stop_reason"] == {"repeated_failure": "repeated_failure",
                                            "evaluation_limit": "evaluation_limit",
                                            "space_exhausted": "space_exhausted"}.get(name,
                                                                                      world.summary["stop_reason"])


def test_reference_row_failures_end_the_run_without_generations():
    scores = dict(VECTORS["s4_tiny_synthetic"]["scores"])
    for reason, has_model in (("coordinates_changed", False), ("receptor_prep_failed", True)):
        scores[SC.REFERENCE_KEY] = {"state": "failed", "reason_code": reason, "score": None}
        world = _oracle_world(VECTORS["s4_tiny_synthetic"]["ga"], scores)
        summary = world.summary
        assert (summary["stop_reason"], summary["status"], summary["generations"]) == ("reference_failed",
                                                                                       "partial", [])
        assert summary["reference"]["reason_code"] == reason and summary["reference"]["score"] is None
        assert (summary["reference"]["model_handle"] is not None) is has_model
        assert summary["reference"]["result_handle"] is None
        assert summary["limitations"] == ["S1", "S2", "S4", "S5", "S6"]
        world.validate()


def test_a_null_reference_row_is_not_a_failure():
    scores = dict(VECTORS["s4_tiny_synthetic"]["scores"])
    scores[SC.REFERENCE_KEY] = {"state": "null_result", "reason_code": None, "score": None}
    world = _oracle_world(VECTORS["s4_tiny_synthetic"]["ga"], scores)
    assert world.summary["reference"]["state"] == "null_result" and world.summary["reference"]["score"] is None
    assert world.summary["stop_reason"] == "generations_complete"
    world.validate()


def test_summary_fields_and_sentences(synthetic, reused):
    summary = synthetic.summary
    assert set(summary) == {"schema", "protocol", "engine", "candidate_set", "structure", "ligand", "box",
                            "parameters", "selection_policy", "hydrogen_policy", "method", "pins", "call_key",
                            "conditions_sha256", "selection_sha256", "ga", "space", "status", "stop_reason",
                            "generations_done", "new_evaluations_used", "reused_count", "reserved_evaluations",
                            "reserved_units", "reference", "generations", "limitations"}
    assert (summary["schema"], summary["protocol"], summary["engine"]) == ("sequence_ga_result@1",
                                                                          "sequence_ga_dock_v1", "qvina")
    assert summary["structure"] == {"handle": TINY["structure"]["handle"], "model_number": 1}
    assert summary["parameters"] == {"seed": 42, "exhaustiveness": 4, "num_modes": 5, "energy_range": 3.0,
                                     "conformers": None, "cpu": 1}
    assert summary["method"] == {"model": SF.model_method(), "docking": SF.DOCKING_PINS}
    assert summary["pins"] == SF.pins()["modules"]
    assert summary["call_key"] == GI.call_key(synthetic.selected, synthetic.pins)
    assert summary["conditions_sha256"] == GI.conditions_sha256(synthetic.selected, synthetic.pins)
    # reserved: min(32, 4 + 3 * 3) = 13 evaluations, 2 * 14 = 28 units (the reference row's 2 included)
    assert (summary["reserved_evaluations"], summary["reserved_units"]) == (13, 28)
    assert summary["limitations"] == ["S1", "S4", "S5", "S6"]
    assert reused.summary["limitations"] == ["S1", "S3", "S4", "S5", "S6"]
    entry = summary["generations"][1]["individuals"][1]                  # 0-4: crossover of 0 and 3-4
    assert entry["mutations"] == [{"candidate_index": 0, "residue": SF.seven(6, "LYS"), "from": "K", "to": "A"},
                                  {"candidate_index": 4, "residue": SF.seven(76, "GLY"), "from": "G", "to": "A"}]
    assert entry["model_handle"] == synthetic.handles["0-4"][0] and entry["result_handle"] == \
        synthetic.handles["0-4"][1]
    carried = summary["generations"][1]["individuals"][0]
    first = summary["generations"][0]["individuals"][2]
    assert carried["origin"] == "carried" and {k: v for k, v in carried.items() if k not in
                                               ("origin", "evaluation", "eval_index")} == \
        {k: v for k, v in first.items() if k not in ("origin", "evaluation", "eval_index")}
    assert (carried["evaluation"], carried["eval_index"]) == (None, None)


def test_scores_come_from_the_stored_results_not_the_worker(synthetic):
    """The worker records carry no score; every score is the stored result's first mode."""
    for generation in synthetic.records:
        for entry in generation["individuals"]:
            assert "score" not in entry and "state" not in entry
    for generation in synthetic.summary["generations"]:
        for entry in generation["individuals"]:
            result = synthetic.results[entry["result_handle"]]
            assert entry["score"] == result["modes"][0]["score_kcal_mol"]


def test_outside_stops_keep_the_evaluated_part():
    vector = VECTORS["s4_tiny_synthetic"]
    expected = copy.deepcopy(vector["expected"])
    expected["generations"] = expected["generations"][:3]
    expected["generations"][2]["individuals"] = expected["generations"][2]["individuals"][:3]
    expected["generations"][2]["complete"] = False
    for stop in ("time_exhausted", "cancelled", "worker_failed", "resource_exceeded"):
        world = World(vector["ga"], vector["scores"], expected, stop_reason=stop)
        assert (world.summary["status"], world.summary["generations_done"]) == ("partial", 2)
        assert world.summary["limitations"] == ["S1", "S2", "S4", "S5", "S6"]
        world.validate()
    nothing = {**copy.deepcopy(vector["expected"]), "generations": []}
    world = World(vector["ga"], vector["scores"], nothing, stop_reason="cancelled")
    assert world.summary["generations"] == [] and world.summary["generations_done"] == 0
    world.validate()


# ---------------------------------------------------------------- observations


def test_resolve_observation_rules(synthetic):
    result_handle = synthetic.handles["0"][1]
    model_handle = synthetic.handles["0"][0]
    results = synthetic.results
    done = {"state": "scored", "reason_code": None, "stage": "docking"}
    assert GB.resolve_observation(done, model_handle, result_handle, results) == \
        {"state": "scored", "reason_code": None, "model_handle": model_handle, "result_handle": result_handle}
    assert GB.resolve_observation(None, model_handle, result_handle, results)["state"] == "scored"
    modeling = {"state": "failed", "reason_code": "coordinates_changed", "stage": "model"}
    assert GB.resolve_observation(modeling, None, None, results) == \
        {"state": "failed", "reason_code": "coordinates_changed", "model_handle": None, "result_handle": None}
    docking = {"state": "failed", "reason_code": "docking_timeout", "stage": "docking"}
    assert GB.resolve_observation(docking, model_handle, None, results)["reason_code"] == "docking_timeout"
    # a docked individual whose result could not be published, a worker without a status, a lost model
    assert GB.resolve_observation(done, model_handle, None, results)["reason_code"] == "engine_output_invalid"
    assert GB.resolve_observation(None, None, None, results)["reason_code"] == "worker_failed"
    assert GB.resolve_observation(docking, None, None, results)["reason_code"] == "worker_failed"
    for status, model, result in ((modeling, model_handle, result_handle), (done, None, result_handle),
                                  ({**done, "state": "null_result"}, model_handle, result_handle),
                                  ({"state": "failed", "reason_code": "nope", "stage": "model"}, None, None),
                                  ({"state": "scored", "reason_code": None}, model_handle, result_handle)):
        with pytest.raises(GB.SequenceGaEvidenceError):
            GB.resolve_observation(status, model, result, results)


# ---------------------------------------------------------------- refusals (changed summaries)


def _refused(world: World, change, match: str | None = None) -> None:
    summary = copy.deepcopy(world.summary)
    change(summary)
    with pytest.raises(GB.SequenceGaEvidenceError, match=match):
        world.validate(summary)


def _entry(summary, generation, index):
    return summary["generations"][generation - 1]["individuals"][index]


def _rekey(entry, key, world):
    """Point an entry at another key's stored facts (mutations, handles, score) so only the targeted rule fails."""
    entry["key"] = key
    entry["mutations"] = GI.key_mutations(TINY, GI.candidate_space(TINY, 3), key)
    model, result = world.handles[key]
    entry["model_handle"], entry["result_handle"] = model, result
    entry["score"] = world.results[result]["modes"][0]["score_kcal_mol"]


@pytest.mark.parametrize("field", ["rank", "best", "improved", "difference", "delta_score", "ddg"])
def test_rank_difference_and_best_fields_are_refused_at_every_level(synthetic, field):
    _refused(synthetic, lambda s: s.__setitem__(field, 1), "summary keys")
    _refused(synthetic, lambda s: s["generations"][0].__setitem__(field, 1), "generation keys")
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__(field, 1), "individual keys")
    _refused(synthetic, lambda s: s["reference"].__setitem__(field, 1), "reference keys")


def test_a_score_that_is_not_the_stored_first_mode_is_refused(synthetic):
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("score", _entry(s, 1, 0)["score"] - 0.1), "score")
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("score", 0.0), "score")
    _refused(synthetic, lambda s: s["reference"].__setitem__("score", -9.0), "score")
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("state", "null_result"))


def test_carry_rules(synthetic):
    # gen 2 carries "0" (the lowest score of gen 1); carrying another scored key is refused
    _refused(synthetic, lambda s: _rekey(_entry(s, 2, 0), "3", synthetic), "carried")
    _refused(synthetic, lambda s: _entry(s, 2, 0).__setitem__("pick_index", 0), "carried")
    _refused(synthetic, lambda s: _entry(s, 2, 0).__setitem__("evaluation", "computed"))
    _refused(synthetic, lambda s: s["generations"][1]["individuals"].pop(0), "carried")
    _refused(synthetic, lambda s: s["generations"][1]["individuals"].append(
        s["generations"][1]["individuals"].pop(0)), "carried individuals come first")
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("origin", "carried"))


def test_unique_keys_and_selection_order(synthetic):
    _refused(synthetic, lambda s: _rekey(_entry(s, 3, 3), "0-3-4", synthetic), "unique")
    _refused(synthetic, lambda s: _entry(s, 1, 1).__setitem__("pick_index", 0), "pick_index")
    _refused(synthetic, lambda s: _entry(s, 3, 3).__setitem__("eval_index", 0), "eval_index")
    _refused(synthetic, lambda s: s["generations"][0]["individuals"].reverse())
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("origin", "random"), "origin")
    _refused(synthetic, lambda s: _entry(s, 1, 0)["mutations"][0].__setitem__("from", "Q"), "mutations")


def test_crossover_and_edit_relations(synthetic):
    # gen 2: 0-4 = crossover(0, 3-4); 2-4 = edit change of 3-4; gen 4: 5 = edit move of 0
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("parents", ["0", "3"]), "crossover")
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("parents", ["0", "0"]), "crossover")
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("parents", ["0", "1"]), "parent")
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("parents", ["0"]), "crossover")
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("edit_op", "add"), "crossover")
    _refused(synthetic, lambda s: _entry(s, 2, 2).__setitem__("edit_op", "move"), "edit")
    _refused(synthetic, lambda s: _entry(s, 2, 2).__setitem__("edit_op", "add"), "edit")
    _refused(synthetic, lambda s: _entry(s, 2, 2).__setitem__("edit_op", None), "edit")
    _refused(synthetic, lambda s: _entry(s, 4, 2).__setitem__("edit_op", "change"), "edit")
    _refused(synthetic, lambda s: _entry(s, 4, 2).__setitem__("parents", ["1-2"]), "parent")
    _refused(synthetic, lambda s: _entry(s, 2, 3).__setitem__("parents", ["0"]), "random")
    _refused(synthetic, lambda s: _entry(s, 2, 3).__setitem__("edit_op", "add"), "random")


def test_edit_relation_rules_by_hand():
    position = {0: 1, 1: 1, 2: 2, 3: 2, 4: 3, 5: 3}                   # the tiny set: candidate -> position
    cases = {("add", "0", "0-2"): True, ("add", "0", "1-2"): False, ("remove", "0-2", "2"): True,
             ("remove", "0-2", "1"): False, ("change", "0-2", "1-2"): True, ("change", "0-2", "0-4"): False,
             ("move", "0-2", "0-4"): True, ("move", "0", "2"): True, ("move", "0-2", "1-2"): False,
             ("change", "0", "1"): True, ("add", "0-2", "0-2-4"): True, ("remove", "0", "0"): False}
    for (op, parent, child), allowed in cases.items():
        assert GB.edit_relation(op, GI.parse_key(parent), GI.parse_key(child), position) is allowed, (op, parent)
    assert GB.crossover_relation(GI.parse_key("0"), GI.parse_key("3-4"), GI.parse_key("0-4")) is True
    assert GB.crossover_relation(GI.parse_key("0"), GI.parse_key("3-4"), GI.parse_key("1-4")) is False


def test_model_and_result_relations(synthetic):
    # an individual pointing at another key's model/result, a reference model built for another reference
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("model_handle", synthetic.handles["0"][0]))
    _refused(synthetic, lambda s: _entry(s, 2, 1).__setitem__("result_handle", synthetic.handles["0"][1]))
    _refused(synthetic, lambda s: s["reference"].__setitem__("model_handle", synthetic.handles["0"][0]))
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("model_handle", None))
    _refused(synthetic, lambda s: _entry(s, 1, 0).__setitem__("result_handle", None))


def test_model_records_must_match_the_summary(synthetic):
    handle = synthetic.handles["0-4"][0]
    original = synthetic.models[handle]
    try:
        for change in (lambda m: m.__setitem__("seed", 43), lambda m: m["method"].__setitem__("engine_build", "8.6.0x"),
                       lambda m: m.__setitem__("reference_structure_sha256", "0" * 64),
                       lambda m: m["protonation_differences"].append({"residue": SF.seven(68, "HIS"),
                                                                     "wild_type_reference": "HIE", "mutant": "HID"}),
                       lambda m: m.__setitem__("new_disulfide_in_mutant", True),
                       lambda m: m["mutations"][0].__setitem__("to", "W")):
            changed = copy.deepcopy(original)
            change(changed)
            synthetic.models[handle] = changed
            with pytest.raises(GB.SequenceGaEvidenceError):
                synthetic.validate()
    finally:
        synthetic.models[handle] = original
    synthetic.validate()


def test_result_inputs_must_be_the_individuals_own_m18_request(synthetic):
    handle = synthetic.handles["0-4"][1]
    original = synthetic.results[handle]
    try:
        for change in (lambda r: r.__setitem__("input_sha256", "0" * 64),
                       lambda r: r["inputs"]["receptor"]["source"].__setitem__("side", "wild_type_reference"),
                       lambda r: r["inputs"]["ligand"].__setitem__("sdf_sha256", "0" * 64),
                       lambda r: r["box"].__setitem__("margin_A", 7.0),
                       lambda r: r["parameters"].__setitem__("seed", 43),
                       lambda r: r["engine"].__setitem__("binary_sha256", "0" * 64),
                       lambda r: r.__setitem__("method", "qvina_core_fixed_score_only_v1")):
            changed = copy.deepcopy(original)
            change(changed)
            synthetic.results[handle] = changed
            with pytest.raises(GB.SequenceGaEvidenceError):
                synthetic.validate()
    finally:
        synthetic.results[handle] = original
    synthetic.validate()


def test_counts_status_and_stop_rules(synthetic):
    _refused(synthetic, lambda s: s.__setitem__("stop_reason", "no_change"))
    _refused(synthetic, lambda s: s.__setitem__("status", "partial"), "status")
    _refused(synthetic, lambda s: s.update(stop_reason="evaluation_limit", status="partial",
                                           limitations=["S1", "S2", "S4", "S5", "S6"]))
    _refused(synthetic, lambda s: s.__setitem__("generations_done", 3), "counts")
    _refused(synthetic, lambda s: s.__setitem__("new_evaluations_used", 14), "counts")
    _refused(synthetic, lambda s: s.__setitem__("reused_count", 1), "counts")
    _refused(synthetic, lambda s: s.__setitem__("reserved_units", 26), "reserved")
    _refused(synthetic, lambda s: s.__setitem__("reserved_evaluations", 14), "reserved")
    _refused(synthetic, lambda s: s["generations"][3].__setitem__("complete", False))
    _refused(synthetic, lambda s: s["generations"][1].__setitem__("min_score", -9.0), "min_score")
    _refused(synthetic, lambda s: s.__setitem__("limitations", ["S1", "S2", "S4", "S5", "S6"]), "limitations")
    _refused(synthetic, lambda s: s.__setitem__("limitations", ["S1", "S4", "S5"]), "limitations")
    _refused(synthetic, lambda s: s.update(generations=s["generations"][:2], generations_done=2,
                                           new_evaluations_used=7), "generations_complete")   # cut short
    _refused(synthetic, lambda s: s.update(stop_reason="reference_failed", status="partial",
                                           limitations=["S1", "S2", "S4", "S5", "S6"]))


def test_stop_reason_structure_from_oracle_paths():
    limit = _oracle_world(*SCENARIOS["evaluation_limit"])
    limit.validate()
    _refused(limit, lambda s: s["generations"][-1].__setitem__("complete", True))
    exhausted = _oracle_world(*SCENARIOS["space_exhausted"])
    assert len(exhausted.summary["generations"][-1]["individuals"]) < 4             # a short complete generation
    partial = {"status": "partial", "limitations": ["S1", "S2", "S4", "S5", "S6"]}
    _refused(exhausted, lambda s: s.update(stop_reason="evaluation_limit", **partial))
    _refused(exhausted, lambda s: s["generations"][1]["individuals"].pop())         # not every key seen
    failing = _oracle_world(*SCENARIOS["repeated_failure"])
    trailing = [e for g in failing.summary["generations"] for e in g["individuals"] if e["origin"] != "carried"]
    assert [e["state"] for e in trailing[-5:]] == ["failed"] * 5
    _refused(failing, lambda s: s.update(stop_reason="evaluation_limit"))

    def four_failures(summary):
        summary["generations"][-1]["individuals"].pop()
        summary["new_evaluations_used"] -= 1

    _refused(failing, four_failures, "five consecutive")
    observed = _vector_world("s4_tiny_observed")                                    # no_change at generation 3
    _refused(observed, lambda s: s.update(stop_reason="generations_complete"))
    _refused(observed, lambda s: s.update(stop_reason="evaluation_limit", **partial))
    # a stop from outside the worker (cancel, clock, crash) can race its own terminal decision: accepted there
    for world in (exhausted, observed, failing):
        changed = copy.deepcopy(world.summary)
        changed.update(stop_reason="cancelled", **partial)
        world.validate(changed)


def test_selection_pins_and_hashes_are_checked(synthetic):
    _refused(synthetic, lambda s: s.__setitem__("call_key", "0" * 64), "call key")
    _refused(synthetic, lambda s: s.__setitem__("conditions_sha256", "0" * 64), "call key")
    _refused(synthetic, lambda s: s["pins"].__setitem__("ga_worker_sha256", "0" * 64))
    _refused(synthetic, lambda s: s["space"].__setitem__("size", 25))
    _refused(synthetic, lambda s: s["ga"].__setitem__("seed", 21))
    _refused(synthetic, lambda s: s["box"].__setitem__("size_A", [50.0, 18.0, 17.0]), "box")
    with pytest.raises(GB.SequenceGaEvidenceError):
        GB.validated_summary(synthetic.summary, selected={**synthetic.selected, "selection_sha256": "0" * 64},
                             candidate_set=TINY, results=synthetic.results, models=synthetic.models,
                             pins=synthetic.pins)


def test_summary_size_bound(synthetic, monkeypatch):
    monkeypatch.setattr(SC, "MAX_SUMMARY_BYTES", 2000)
    with pytest.raises(GB.SequenceGaEvidenceError, match="size"):
        synthetic.validate()


def test_validation_does_not_mutate(synthetic):
    before = copy.deepcopy(synthetic.summary)
    synthetic.validate()
    assert synthetic.summary == before


def test_a_null_box_only_with_a_ligand_or_box_refusal_of_the_reference_row():
    """T5: a range box over a ligand neither the server nor RDKit reads has no box; the summary keeps null only when
    the reference row's docking refused the ligand or the box (the M18 ligand_* / box_* reasons)."""
    scores = dict(VECTORS["s4_tiny_synthetic"]["scores"])
    ga = VECTORS["s4_tiny_synthetic"]["ga"]
    for reason, allowed in (("ligand_unparseable", True), ("box_invalid", True), ("receptor_prep_failed", False)):
        scores[SC.REFERENCE_KEY] = {"state": "failed", "reason_code": reason, "score": None}
        world = _oracle_world(ga, scores)
        summary = {**copy.deepcopy(world.summary), "box": None}
        if allowed:
            assert world.validate(summary)["box"] is None
        else:
            with pytest.raises(GB.SequenceGaEvidenceError, match="box"):
                world.validate(summary)
    with pytest.raises(GB.SequenceGaEvidenceError, match="box"):   # a scored run always has its box
        _oracle_world(ga, VECTORS["s4_tiny_synthetic"]["scores"]).validate(
            {**copy.deepcopy(_oracle_world(ga, VECTORS["s4_tiny_synthetic"]["scores"]).summary), "box": None})
