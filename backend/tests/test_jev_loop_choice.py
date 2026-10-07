"""M25 T5-A: the loop proposal ``jev_loop_choice@1`` (spec .dryforge/spec.md 3.2 proposals, 5.2, 5.3, 9.3, 11, 12):
the pure ``jev_loop_projection.build_loop_choice`` / ``validated_loop_choice`` and ``jev_loop_store.load_proposals``
(the loop read's ``proposals``).

Inputs:
* REAL product outputs (pure part): the M17 set ``fixtures/ligand_ga/m17-candidate-set-small-pool.json`` and the M20
  set ``fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json`` (public 1UBQ); the prepared 1UBQ structure made here by
  the unmodified cheap tools through ``Run.call``.
* REAL product run (store part, built once per module): a real M20 set of public 1UBQ (cheap tool), the labelled
  synthetic phenol SDF, a protein loop made by the real creation admission (``jev_loop_store.create``: OpenMM /
  PDBFixer / docking capability, a missing engine FAILS, never skips), its first ``jev_loop_projection@1`` made by the
  real ``build_jev_loop_projection`` tool and an M24 ``jev_projection@1`` made by the real ``build_jev_projection`` tool
  in the same run. Each test works on an events-only copy.
* LABELLED SYNTHETIC: the provider answers (chosen alias, confidence, probabilities), send / audit ids and usage numbers
  given to the builder; loop-record candidate states and scores given to the wire builders (pure part); the M24
  approval / dispatch / outcome events of a loop send (``send_events``: the stand-in for the T5-B send branch, which
  will write exactly these through ``jev_sends.run_send``); tampered proposals (fault injection).

Expected values are written from the spec 5.3 rules and read from the fixtures themselves (the chosen candidate's
SMILES / residue / substitution from the stored set rows, the instruction hash from the spec 4.5 text), never from the
module under test.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import Fake
from ligand_job_fixture import import_file
from test_jev_loops_api import I44, PHENOL, UBQ, protein_body

from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loop_projection as LP
from mw import jev_loop_store, jev_loops
from mw import jev_sends as S
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
FIX = Path(__file__).resolve().parent / "fixtures"
SMALL_POOL = json.loads((FIX / "ligand_ga/m17-candidate-set-small-pool.json").read_text())
M20_8POS = json.loads((FIX / "sequence_ga/m20-candidate-set-1ubq-8pos.json").read_text())["content"]
LIGAND_IDS = [row["id"] for row in SMALL_POOL["candidates"]]
MUTATION_POOL = [0, 3, 5, 9, 12, 17, 22, 31]                       # candidate indexes of the 8-position set
SET_HANDLE = {"ligand": "obj://run_x/ligand_candidate_set/" + "a" * 64,
              "mutation": "obj://run_x/mutation_candidate_set/" + "b" * 64}
STRUCTURE_REF = {"handle": "obj://run_x/prepared_structure/" + "c" * 64, "model_number": 1}
PROJECTION_HANDLE = "obj://run_x/jev_loop_projection/" + "d" * 64
LOOP_ID = "7a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
SEND_ID = "5b6c7d8e-9f0a-4b1c-8d2e-3f4a5b6c7d8e"                     # SYNTHETIC send id (v4)
AUDIT_ID = "eg_" + "0123456789abcdef" * 2                           # SYNTHETIC audit id
USAGE = {"input_tokens": 2087, "output_tokens": 65, "external_tokens": 2152, "cost": 0.00009}   # SYNTHETIC
# SYNTHETIC first-mode score numbers standing in for stored values (inputs of the exploit wire, not results)
SCORES = {LIGAND_IDS[1]: -7.123456789012345, LIGAND_IDS[3]: -12}
LP_RUN = "run_m25_t5a_choice"
LOOP = "8b2c3d4e-5f60-4b7c-9d8e-0f1a2b3c4d5e"
JSON_HEADERS = {"content-type": "application/json"}


# ---------------------------------------------------------------- pure fixtures


def _rows(pool, states):
    return [{"ref": ref, "state": states.get(ref, "pending"),
             "score_kcal_mol": SCORES.get(ref) if states.get(ref) == "scored" else None} for ref in pool]


def _projection(kind, wire, selection, *, goal):
    content = LP.build_loop_projection_content(
        kind, SET_HANDLE[kind], wire, selection, loop_id=LOOP_ID, loop_seed=11, iteration=2, send_ordinal=1,
        structure=STRUCTURE_REF if kind == "mutation" else None)
    assert content["goal"] == goal
    return content


@pytest.fixture(scope="module")
def ubq(tmp_path_factory):
    run = new_run(tmp_path_factory.mktemp("jev_loop_choice_ubq"), run_id="run_jev_loop_choice_ubq", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    return _parse(ToolContext(store=run.store, call_id="jev_loop_t5a_test"), prepared)


@pytest.fixture(scope="module")
def ligand_projection():
    # exploit; two scored, one null_result, one unavailable (left out of the wire), six pending
    states = {LIGAND_IDS[1]: "scored", LIGAND_IDS[3]: "scored", LIGAND_IDS[5]: "null_result",
              LIGAND_IDS[8]: "unavailable"}
    wire, selection = LP.build_loop_ligand_wire(SMALL_POOL, _rows(LIGAND_IDS, states), goal="exploit", loop_seed=11,
                                                iteration=2, send_ordinal=1)
    return _projection("ligand", wire, selection, goal="exploit")


@pytest.fixture(scope="module")
def mutation_projection(ubq):
    # explore; one failed, one not_run, the rest pending
    states = {MUTATION_POOL[2]: "failed", MUTATION_POOL[6]: "not_run"}
    wire, selection = LP.build_loop_mutation_wire(M20_8POS, _rows(MUTATION_POOL, states), ubq, goal="explore",
                                                  loop_seed=11, iteration=2, send_ordinal=1)
    return _projection("mutation", wire, selection, goal="explore")


def _criteria(projection):
    return [item["alias"] for item in projection["selection"] if item["state"] == "pending"]


def _computed(projection):
    return [item["alias"] for item in projection["selection"] if item["state"] != "pending"]


def _ref(projection, alias):
    return next(item["ref"] for item in projection["selection"] if item["alias"] == alias)


def _answer(projection, *, at=-1, confidence=0.4375, probabilities="default"):
    """SYNTHETIC provider answer: the ``at``-th criteria alias with a confidence and probabilities in a scrambled
    (received) order."""
    criteria = _criteria(projection)
    alias = criteria[at]
    if probabilities == "default":
        probabilities = {criteria[-1]: 0.4375, criteria[0]: 0.3125, criteria[1]: 0.25}
    return {"choice_alias": alias, "confidence": confidence, "probabilities": probabilities}


def build(projection, source, *, answer=None, late=False, late_reason=None, usage=USAGE, served=J.SERVED_SNAPSHOT,
          handle=PROJECTION_HANDLE, send_id=SEND_ID):
    return LP.build_loop_choice(handle, projection, source, send_id=send_id, audit_id=AUDIT_ID,
                                answer=answer if answer is not None else _answer(projection), served_model=served,
                                usage=usage, late=late, late_reason=late_reason)


def _instructions_sha256(kind, goal):
    return hashlib.sha256(L.INSTRUCTIONS[(kind, goal)].encode("ascii")).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _differs(left, right) -> bool:
    """Different as JSON (0 / False and 1 / 1.0 differ; NaN allowed here)."""
    return json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True)


# ---------------------------------------------------------------- build: keys and values (spec 5.3)


def test_ligand_proposal_keys_and_values(ligand_projection):
    projection = ligand_projection
    answer = _answer(projection)
    content = build(projection, SMALL_POOL, answer=answer)
    assert list(content) == list(L.CHOICE_KEYS)
    assert set(L.CHOICE_KEYS) == {"schema", "method_version", "label", "scientific_result", "loop", "goal", "send",
                                  "source", "projection", "question", "requested_model", "served_model", "selection",
                                  "answer", "usage", "arrival", "limitations"}
    assert (content["schema"], content["method_version"], content["label"]) == (
        "jev_loop_choice@1", "mw.jev_loop_choice/v1", "JEV 판정(모델 선택)")
    assert content["scientific_result"] is False
    assert content["loop"] == {"loop_id": LOOP_ID, "iteration": 2, "send_ordinal": 1} == projection["loop"]
    assert content["goal"] == "exploit"
    assert content["send"] == {"send_id": SEND_ID, "audit_id": AUDIT_ID}
    assert content["source"] == {"handle": SET_HANDLE["ligand"], "schema": "ligand_candidate_set@1"}
    assert content["projection"] == {"handle": PROJECTION_HANDLE, "wire_sha256": projection["wire_sha256"],
                                     "body_sha256": projection["body_sha256"], "body_bytes": projection["body_bytes"]}
    assert content["question"] == {"id": "ligand_loop_choice@1", "key": "candidate_choice",
                                   "instructions_sha256": _instructions_sha256("ligand", "exploit")}
    assert (content["requested_model"], content["served_model"]) == ("typesafe/jev-1.13", "typesafe/jev-1.13-20260917")
    assert content["selection"] == projection["selection"] and content["selection"] is not projection["selection"]
    criteria = _criteria(projection)
    chosen = criteria[-1]
    ref = _ref(projection, chosen)
    smiles = next(row["smiles"] for row in SMALL_POOL["candidates"] if row["id"] == ref)   # from the stored set row
    assert content["answer"] == {"choice_alias": chosen, "list_position": len(criteria), "list_size": len(criteria),
                                 "local_ref": {"candidate_id": ref}, "local_display": {"smiles": smiles},
                                 "confidence": 0.4375, "probabilities": answer["probabilities"]}
    assert len(criteria) == 6 and len(projection["selection"]) == 9   # unavailable left out; 3 computed, 6 pending
    assert content["usage"] == USAGE and content["arrival"] == {"late": False, "late_reason": None}
    assert content["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ6]
    assert LP.validated_loop_choice(content, projection, SMALL_POOL) is content


def test_mutation_proposal_local_ref_and_display_come_from_the_stored_set(mutation_projection):
    projection = mutation_projection
    criteria = _criteria(projection)
    for at in range(len(criteria)):
        content = build(projection, M20_8POS, answer=_answer(projection, at=at, probabilities=None, confidence=None))
        alias = criteria[at]
        index = _ref(projection, alias)
        row = next(row for row in M20_8POS["candidates"] if row["index"] == index)
        position = next(item for item in M20_8POS["positions"] if item["index"] == row["position_index"])
        residue = {key: position["residue"][key] for key in ("model_number", "chain_auth", "chain_label", "seq_auth",
                                                             "seq_label", "icode", "resname")}
        assert content["answer"]["local_ref"] == {"candidate_index": index, "position_index": row["position_index"]}
        assert content["answer"]["local_display"] == {"residue": residue, "from": row["from"], "to": row["to"]}
        # the loop record shows the same notation for that candidate (spec 3.2 display = 5.3 local_display)
        assert content["answer"]["local_display"] == jev_loop_store.candidate_displays(
            "protein", M20_8POS, [index])[index]
        assert (content["answer"]["list_position"], content["answer"]["list_size"]) == (at + 1, len(criteria))
        assert (content["answer"]["confidence"], content["answer"]["probabilities"]) == (None, None)
    assert content["question"] == {"id": "mutation_loop_choice@1", "key": "candidate_choice",
                                   "instructions_sha256": _instructions_sha256("mutation", "explore")}
    assert content["source"] == {"handle": SET_HANDLE["mutation"], "schema": "mutation_candidate_set@1"}
    assert content["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ5, L.LJ7]
    assert LP.validated_loop_choice(content, projection, M20_8POS) is content


def test_the_answer_is_kept_exactly_as_received(ligand_projection):
    projection = ligand_projection
    criteria = _criteria(projection)
    # SYNTHETIC: values a rounding, sorting or float conversion would change; received key order not sorted
    probabilities = {criteria[4]: 0.1234567890123456789, criteria[1]: 1, criteria[3]: 0, criteria[0]: 1e-12}
    answer = {"choice_alias": criteria[3], "confidence": 0.30000000000000004, "probabilities": probabilities}
    before = copy.deepcopy(answer)
    content = build(projection, SMALL_POOL, answer=answer)
    assert answer == before                                    # the input is not changed
    got = content["answer"]
    assert list(got["probabilities"]) == [criteria[4], criteria[1], criteria[3], criteria[0]]   # received order
    assert _canonical(got["probabilities"]) == _canonical(probabilities)   # 1 stays int 1, 0 stays int 0
    assert got["probabilities"] is not probabilities
    assert got["confidence"] == 0.30000000000000004 and type(got["confidence"]) is float
    assert got["choice_alias"] == criteria[3] and got["list_position"] == 4
    assert not {"rank", "score", "best", "recommended", "order", "ranking"} & set(got)
    # a stored round trip (sorted keys, the store's encoder) keeps every value and type
    stored = json.loads(_canonical(content))
    assert _canonical(stored) == _canonical(content)
    assert LP.validated_loop_choice(stored, projection, SMALL_POOL) == stored


def test_a_choice_from_the_parsed_reply_is_the_proposal(ligand_projection):
    projection = ligand_projection
    criteria = _criteria(projection)
    reply = {"model": J.SERVED_SNAPSHOT, "usage": {"input_tokens": 1, "output_tokens": 1, "cost": 0.0},
             "answers": {"candidate_choice": {"type": "choice", "choice": criteria[2], "confidence": 0.5,
                                              "probabilities": {criteria[2]: 0.5, criteria[5]: 0.5}}}}
    parsed, reason = LP.parse_loop_choice(reply, projection)
    assert reason is None
    content = build(projection, SMALL_POOL, answer=parsed)
    assert content["answer"]["choice_alias"] == criteria[2] and content["answer"]["list_position"] == 3
    assert content["answer"]["probabilities"] == {criteria[2]: 0.5, criteria[5]: 0.5}


@pytest.mark.parametrize("reason", J.LATE_REASONS)
def test_a_late_proposal_carries_j7_and_validates(ligand_projection, reason):
    content = build(ligand_projection, SMALL_POOL, late=True, late_reason=reason)
    assert content["arrival"] == {"late": True, "late_reason": reason}
    assert content["limitations"] == [L.LJ1, L.LJ2, L.LJ3, L.LJ4, L.LJ6, J.J7]
    assert LP.validated_loop_choice(content, ligand_projection, SMALL_POOL) is content


def test_usage_may_be_absent(mutation_projection):
    content = build(mutation_projection, M20_8POS, usage=None,
                    answer=_answer(mutation_projection, probabilities=None, confidence=None))
    assert content["usage"] is None
    assert LP.validated_loop_choice(content, mutation_projection, M20_8POS) is content


def test_build_refuses_a_computed_or_unknown_alias(ligand_projection, mutation_projection):
    for projection, source in ((ligand_projection, SMALL_POOL), (mutation_projection, M20_8POS)):
        for alias in [*_computed(projection), "c99", "m99", None, 1]:
            with pytest.raises(LP.LoopChoiceInvalid):
                build(projection, source, answer={"choice_alias": alias, "confidence": None, "probabilities": None})
    with pytest.raises(LP.LoopChoiceInvalid):   # a reply the gate would not accept (another served model)
        build(ligand_projection, SMALL_POOL, served="typesafe/jev-1.14-20261001")
    with pytest.raises(LP.LoopChoiceInvalid):   # a pool ref the stored set does not hold
        build(ligand_projection, {**SMALL_POOL, "candidates": SMALL_POOL["candidates"][:1]})


# ---------------------------------------------------------------- validated_loop_choice refuses tampering


def _other_ref(content, projection):
    other = next(alias for alias in _criteria(projection) if alias != content["answer"]["choice_alias"])
    return {"candidate_id": _ref(projection, other)}


def _computed_alias(content, projection):
    return _computed(projection)[0]


TAMPER = {   # SYNTHETIC edits of a valid stored proposal (each must be refused on read)
    "top_rank": lambda c, p: c.update(rank=1),
    "top_best": lambda c, p: c.update(best=c["answer"]["choice_alias"]),
    "top_score": lambda c, p: c.update(score=-9.1),
    "top_recommended": lambda c, p: c.update(recommended=True),
    "answer_rank": lambda c, p: c["answer"].update(rank=1),
    "answer_score": lambda c, p: c["answer"].update(score_kcal_mol=-7.0),
    "drop_goal": lambda c, p: c.pop("goal"),
    "drop_list_size": lambda c, p: c["answer"].pop("list_size"),
    "drop_arrival": lambda c, p: c.pop("arrival"),
    "send_extra": lambda c, p: c["send"].update(at="now"),
    "scientific_result": lambda c, p: c.update(scientific_result=True),
    "scientific_result_missing_false": lambda c, p: c.update(scientific_result=0),
    "label": lambda c, p: c.update(label="JEV 추천"),
    "schema_m24": lambda c, p: c.update(schema=J.CHOICE_SCHEMA),
    "method_version": lambda c, p: c.update(method_version="mw.jev_choice/v1"),
    "computed_alias": lambda c, p: c["answer"].update(choice_alias=_computed_alias(c, p)),
    "computed_alias_consistent": lambda c, p: c["answer"].update(
        choice_alias=_computed_alias(c, p), local_ref={"candidate_id": _ref(p, _computed_alias(c, p))}),
    "alias_outside": lambda c, p: c["answer"].update(choice_alias="c99"),
    "list_position_off": lambda c, p: c["answer"].update(list_position=c["answer"]["list_position"] - 1),
    "list_position_float": lambda c, p: c["answer"].update(list_position=float(c["answer"]["list_position"])),
    "list_size_all": lambda c, p: c["answer"].update(list_size=len(p["selection"])),
    "local_ref_other": lambda c, p: c["answer"].update(local_ref=_other_ref(c, p)),
    "local_ref_extra": lambda c, p: c["answer"]["local_ref"].update(position_index=0),
    "local_display_other": lambda c, p: c["answer"].update(local_display={"smiles": "CCO"}),
    "local_display_extra": lambda c, p: c["answer"]["local_display"].update(name="x"),
    "probability_computed_key": lambda c, p: c["answer"].update(probabilities={_computed_alias(c, p): 0.1}),
    "probability_key_outside": lambda c, p: c["answer"].update(probabilities={"c99": 0.1}),
    "probability_range_high": lambda c, p: c["answer"].update(probabilities={c["answer"]["choice_alias"]: 1.1}),
    "probability_range_low": lambda c, p: c["answer"].update(probabilities={c["answer"]["choice_alias"]: -0.1}),
    "probability_nan": lambda c, p: c["answer"].update(probabilities={c["answer"]["choice_alias"]: math.nan}),
    "probability_bool": lambda c, p: c["answer"].update(probabilities={c["answer"]["choice_alias"]: True}),
    "probabilities_ranked_list": lambda c, p: c["answer"].update(probabilities=[[c["answer"]["choice_alias"], 0.9]]),
    "confidence_range": lambda c, p: c["answer"].update(confidence=1.5),
    "confidence_bool": lambda c, p: c["answer"].update(confidence=False),
    "served_model": lambda c, p: c.update(served_model="typesafe/jev-1.14-20261001"),
    "served_model_missing": lambda c, p: c.update(served_model=None),
    "requested_model": lambda c, p: c.update(requested_model=J.SERVED_SNAPSHOT),
    "limitations_dropped": lambda c, p: c.update(limitations=c["limitations"][:-1]),
    "limitations_m24": lambda c, p: c.update(limitations=J.limitations_for("ligand", False)),
    "limitations_other_goal": lambda c, p: c.update(limitations=[L.LJ1, L.LJ2, L.LJ3, L.LJ5, L.LJ6]),
    "limitations_j7_not_late": lambda c, p: c.update(limitations=[*c["limitations"], J.J7]),
    "projection_wire_hash": lambda c, p: c["projection"].update(wire_sha256="0" * 64),
    "projection_body_hash": lambda c, p: c["projection"].update(body_sha256="0" * 64),
    "projection_body_bytes": lambda c, p: c["projection"].update(body_bytes=c["projection"]["body_bytes"] + 1),
    "projection_m24_handle": lambda c, p: c["projection"].update(handle="obj://run_x/jev_projection/" + "d" * 64),
    "late_without_reason": lambda c, p: c["arrival"].update(late=True),
    "reason_without_late": lambda c, p: c["arrival"].update(late_reason="consent_off"),
    "late_without_j7": lambda c, p: c.update(arrival={"late": True, "late_reason": "consent_off"}),
    "late_other_reason": lambda c, p: c.update(arrival={"late": True, "late_reason": "timeout"},
                                               limitations=[*c["limitations"], J.J7]),
    "late_not_bool": lambda c, p: c["arrival"].update(late=0),
    "loop_iteration": lambda c, p: c["loop"].update(iteration=1),
    "loop_send_ordinal": lambda c, p: c["loop"].update(send_ordinal=0),
    "loop_id": lambda c, p: c["loop"].update(loop_id=str(uuid.UUID(int=1, version=4))),
    "goal_other": lambda c, p: c.update(goal="explore"),
    "send_id": lambda c, p: c["send"].update(send_id="not-a-uuid"),
    "audit_id": lambda c, p: c["send"].update(audit_id="eg_x"),
    "source_handle": lambda c, p: c["source"].update(handle="obj://run_x/ligand_candidate_set/" + "e" * 64),
    "question_m24_id": lambda c, p: c["question"].update(id=J.LIGAND_QUESTION_ID),
    "instructions_hash_other_goal": lambda c, p: c["question"].update(
        instructions_sha256=_instructions_sha256("ligand", "explore")),
    "selection_reordered": lambda c, p: c.update(selection=c["selection"][::-1]),
    "selection_state": lambda c, p: c["selection"][0].update(state="scored" if c["selection"][0]["state"] == "pending"
                                                             else "pending"),
    "usage_negative": lambda c, p: c.update(usage={**c["usage"], "input_tokens": -1}),
    "usage_extra": lambda c, p: c.update(usage={**c["usage"], "rank": 1}),
}


@pytest.mark.parametrize("name", sorted(TAMPER))
def test_validated_loop_choice_refuses_tampered_proposals(name, ligand_projection):
    content = build(ligand_projection, SMALL_POOL)
    assert LP.validated_loop_choice(copy.deepcopy(content), ligand_projection, SMALL_POOL) == content
    tampered = copy.deepcopy(content)
    TAMPER[name](tampered, ligand_projection)
    assert _differs(tampered, content)
    with pytest.raises(LP.LoopChoiceInvalid):
        LP.validated_loop_choice(tampered, ligand_projection, SMALL_POOL)


MUTATION_TAMPER = {   # SYNTHETIC edits of the mutation-only fields
    "position_index_other": lambda c, p: c["answer"]["local_ref"].update(
        position_index=c["answer"]["local_ref"]["position_index"] + 1),
    "candidate_id_shape": lambda c, p: c["answer"].update(local_ref={"candidate_id": "c_" + "0" * 16}),
    "residue_label_null": lambda c, p: c["answer"]["local_display"]["residue"].update(chain_label=None),
    "residue_seq_float": lambda c, p: c["answer"]["local_display"]["residue"].update(
        seq_auth=float(c["answer"]["local_display"]["residue"]["seq_auth"])),
    "substitution_to": lambda c, p: c["answer"]["local_display"].update(to="P"),
    "index_as_string": lambda c, p: c["answer"]["local_ref"].update(
        candidate_index=str(c["answer"]["local_ref"]["candidate_index"])),
    "structure_less_source": lambda c, p: c.update(source={"handle": SET_HANDLE["ligand"],
                                                           "schema": "ligand_candidate_set@1"}),
}


@pytest.mark.parametrize("name", sorted(MUTATION_TAMPER))
def test_validated_loop_choice_refuses_tampered_mutation_proposals(name, mutation_projection):
    content = build(mutation_projection, M20_8POS)
    tampered = copy.deepcopy(content)
    MUTATION_TAMPER[name](tampered, mutation_projection)
    assert _differs(tampered, content)
    with pytest.raises(LP.LoopChoiceInvalid):
        LP.validated_loop_choice(tampered, mutation_projection, M20_8POS)


def test_the_proposal_is_checked_against_its_own_projection_and_set(ligand_projection, mutation_projection):
    content = build(ligand_projection, SMALL_POOL)
    with pytest.raises(LP.LoopChoiceInvalid):          # another projection (other kind, loop, hashes)
        LP.validated_loop_choice(content, mutation_projection, M20_8POS)
    # the same loop reference but another send order: the alias no longer names the same candidate
    other_wire, other_selection = LP.build_loop_ligand_wire(
        SMALL_POOL, [{"ref": item["ref"], "state": item["state"], "score_kcal_mol": SCORES.get(item["ref"])
                      if item["state"] == "scored" else None} for item in ligand_projection["selection"]],
        goal="exploit", loop_seed=12, iteration=2, send_ordinal=1)
    other = LP.build_loop_projection_content("ligand", SET_HANDLE["ligand"], other_wire, other_selection,
                                             loop_id=LOOP_ID, loop_seed=12, iteration=2, send_ordinal=1)
    assert other["loop"] == ligand_projection["loop"] and other["selection"] != ligand_projection["selection"]
    with pytest.raises(LP.LoopChoiceInvalid):
        LP.validated_loop_choice(content, other, SMALL_POOL)
    edited = copy.deepcopy(SMALL_POOL)                 # the stored set row of the chosen candidate reads otherwise
    ref = content["answer"]["local_ref"]["candidate_id"]
    next(row for row in edited["candidates"] if row["id"] == ref)["smiles"] = "CCO"
    with pytest.raises(LP.LoopChoiceInvalid):
        LP.validated_loop_choice(content, ligand_projection, edited)
    for not_a_choice in (None, [], "jev_loop_choice@1", {}):
        with pytest.raises(LP.LoopChoiceInvalid):
            LP.validated_loop_choice(not_a_choice, ligand_projection, SMALL_POOL)
    with pytest.raises(LP.LoopChoiceInvalid):          # a malformed projection is refused, not a crash
        LP.validated_loop_choice(content, {"selection": None}, SMALL_POOL)


def test_an_m24_proposal_is_never_a_loop_proposal(ligand_projection):
    content = build(ligand_projection, SMALL_POOL)
    m24_shaped = {key: value for key, value in content.items() if key not in ("loop", "goal")}
    m24_shaped.update(schema=J.CHOICE_SCHEMA, method_version=J.CHOICE_METHOD_VERSION,
                      limitations=J.limitations_for("ligand", False))
    m24_shaped["answer"] = {key: value for key, value in content["answer"].items()
                            if key not in ("list_position", "list_size")}
    assert set(m24_shaped) == set(S.CHOICE_KEYS)
    with pytest.raises(LP.LoopChoiceInvalid):
        LP.validated_loop_choice(m24_shaped, ligand_projection, SMALL_POOL)


def test_the_one_mebibyte_limit_is_checked(ligand_projection, monkeypatch):
    content = build(ligand_projection, SMALL_POOL)
    size = len(_canonical(content).encode("utf-8"))
    monkeypatch.setattr(L, "MAX_OBJECT_BYTES", size)   # fault injection: the limit at exactly this proposal's size
    assert LP.validated_loop_choice(content, ligand_projection, SMALL_POOL) is content
    monkeypatch.setattr(L, "MAX_OBJECT_BYTES", size - 1)
    with pytest.raises(LP.LoopChoiceInvalid):
        LP.validated_loop_choice(content, ligand_projection, SMALL_POOL)
    with pytest.raises(LP.LoopChoiceInvalid):
        build(ligand_projection, SMALL_POOL)


def test_loop_choice_invalid_is_a_value_error_like_the_m24_choice_error():
    assert issubclass(LP.LoopChoiceInvalid, ValueError) and issubclass(S.ChoiceInvalid, ValueError)


# ---------------------------------------------------------------- the stored proposal in a real run


def _protein_template(root: Path) -> dict:
    run = new_run(root, run_id=LP_RUN, dry_run=False)
    loaded = run.call("load_structure", {"source": str(UBQ), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    mutation_set = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}}).handle
    phenol = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    indexes = [row["index"] for row in run.store.load(mutation_set)["candidates"]]
    body = protein_body({"ubq_set": mutation_set, "phenol": phenol, "indexes": indexes}, loop_id=LOOP,
                        goal="exploit", iteration_cap=3)
    body["pool"]["candidates"] = [indexes[17], indexes[3], indexes[0], indexes[9]]
    record = jev_loop_store.create(run, body, send_active=False)            # the real admission (engines present)
    assert record["current"]["action"] == "select"
    projection = run.call(L.TOOL, {"loop_id": LOOP, "iteration": 1}).handle   # the real loop projection tool
    m24 = run.call(J.TOOL, {"source": mutation_set, "candidates": [indexes[0], indexes[3]]}).handle
    return {"root": root, "set": mutation_set, "projection": projection, "m24_projection": m24,
            "log": (root / LP_RUN / "events.jsonl").read_bytes()}


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    return _protein_template(tmp_path_factory.mktemp("jev_loop_choice_store"))


@pytest.fixture
def world(template, tmp_path):
    """An events-only copy of the template run (the store is rebuilt from its events)."""
    root = tmp_path / "runs"
    (root / LP_RUN).mkdir(parents=True)
    (root / LP_RUN / "events.jsonl").write_bytes(template["log"])
    run = new_run(root, run_id=LP_RUN, dry_run=False)
    return {**template, "root": root, "run": run}


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    S.ACTIVE_SENDS.clear()


def send_events(run, projection, *, late=False) -> tuple[str, str]:
    """LABELLED SYNTHETIC stand-in for the T5-B send branch: the M24 approval and dispatch of one send of a loop
    projection (no request, audit row, reservation or key read). The outcome is written by ``outcome``."""
    content = run.store.load(projection)
    send_id, audit_id = str(uuid.uuid4()), f"eg_{uuid.uuid4().hex}"
    run.events.append(J.EVENT_APPROVED, send_id=send_id, projection_handle=projection,
                      body_sha256=content["body_sha256"], question_id=content["question"]["id"],
                      source_handle=content["source"]["handle"], selection_count=len(content["selection"]),
                      approved_by=J.APPROVED_BY)
    run.events.append(J.EVENT_DISPATCH, send_id=send_id, audit_id=audit_id)
    if late:   # the M24 late order: consent turned off after the dispatch
        run.events.append(J.EVENT_CONSENT, enabled=False, policy=J.CONSENT_POLICY, send_cap=J.SEND_CAP,
                          request_model=J.REQUEST_MODEL, allowed_served_model=J.SERVED_SNAPSHOT,
                          destination=J.DESTINATION)
    return send_id, audit_id


def outcome(run, send_id, audit_id, *, choice, late=False) -> None:
    """LABELLED SYNTHETIC: the M24 outcome event of a completed send (as ``jev_sends._finish`` writes it)."""
    run.events.append(J.EVENT_OUTCOME, send_id=send_id, status="completed", reason_code=None, audit_id=audit_id,
                      requested_model=J.REQUEST_MODEL, served_model=J.SERVED_SNAPSHOT, choice_handle=choice,
                      usage=USAGE, late=late, late_reason="consent_off" if late else None)


def store_choice(world, *, at=-1, late=False, tamper=None, write_outcome=True) -> tuple[str, dict]:
    """One loop send whose proposal (built by the module under test from a SYNTHETIC answer) is stored as the T5-B
    ``_finish`` will store it, then the outcome naming it."""
    run = world["run"]
    projection = run.store.load(world["projection"])
    source = jev_loop_store.source_content(jev_loop_store.LoopReadView(run), "protein", projection["source"]["handle"])
    send_id, audit_id = send_events(run, world["projection"], late=late)
    content = LP.build_loop_choice(world["projection"], projection, source, send_id=send_id, audit_id=audit_id,
                                   answer=_answer(projection, at=at), served_model=J.SERVED_SNAPSHOT, usage=USAGE,
                                   late=late, late_reason="consent_off" if late else None)
    if tamper is not None:
        tamper(content)
    handle = run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, content).handle
    if write_outcome:
        outcome(run, send_id, audit_id, choice=handle, late=late)
    return handle, content


def read(run, **kwargs):
    view = jev_loop_store.LoopReadView(run)
    budget = jev_loop_store.remaining_budget(run.budget_snapshot())
    return jev_loop_store.read_loop(view, LOOP, budget=budget, **kwargs)


def proposals(run):
    view = jev_loop_store.LoopReadView(run)
    return jev_loop_store.load_proposals(view, jev_loop_store.created_payload(view.read(), LOOP))


def test_a_fresh_loop_has_no_proposal(world):
    assert proposals(world["run"]) == {}


def test_a_stored_valid_proposal_is_the_iterations_selection(world):
    run = world["run"]
    handle, content = store_choice(world, at=1)
    assert proposals(run) == {handle: content}
    state = read(run)
    record = state.record
    projection = run.store.load(world["projection"])
    criteria = _criteria(projection)
    chosen = _ref(projection, criteria[1])
    iteration = record["iterations"][0]
    assert (iteration["index"], iteration["phase"], iteration["state"]) == (1, "awaiting_compute", "in_progress")
    assert iteration["sends"] == [{"send_id": content["send"]["send_id"], "status": "completed", "send_ordinal": 0,
                                   "proposal_handle": handle, "late": False}]
    assert (record["current"]["action"], record["current"]["phase"]) == ("compute", "awaiting_compute")
    assert record["counts"]["sends_dispatched"] == 1
    admitted = jev_loops.compute_admission(state, iteration=1, proposal=handle, capability_available=True)
    assert (admitted["outcome"], admitted["candidate_ref"], admitted["decided_by"], admitted["proposal_handle"]) == (
        "approve", chosen, "jev", handle)
    # the projection tool now refuses a second send of iteration 1 (spec 3.3: the first completed answer decides)
    with pytest.raises(ToolFailure) as caught:
        run.call(L.TOOL, {"loop_id": LOOP, "iteration": 1})
    assert caught.value.detail["reason_code"] == "selection_done"


def test_a_late_proposal_is_stored_but_never_the_selection(world):
    run = world["run"]
    handle, content = store_choice(world, late=True)
    assert content["arrival"] == {"late": True, "late_reason": "consent_off"} and content["limitations"][-1] == J.J7
    assert proposals(run) == {handle: content}                 # it validates and is kept
    state = read(run)
    iteration = state.record["iterations"][0]
    assert iteration["phase"] == "awaiting_selection" and iteration["proposal_handle"] is None
    assert iteration["sends"][0]["late"] is True and iteration["sends"][0]["proposal_handle"] == handle
    assert state.record["current"]["action"] == "select"
    refused = jev_loops.compute_admission(state, iteration=1, proposal=handle, capability_available=True)
    assert refused["reason_code"] == "proposal_late"
    chosen = content["answer"]["local_ref"]["candidate_index"]
    human = jev_loops.compute_admission(state, iteration=1, candidate=chosen, capability_available=True)
    assert (human["outcome"], human["candidate_ref"], human["decided_by"]) == ("approve", chosen, "human")
    # not selection_done: a new send of iteration 1 may be prepared (the next send ordinal)
    again = run.call(L.TOOL, {"loop_id": LOOP, "iteration": 1}).handle
    assert run.store.load(again)["loop"] == {"loop_id": LOOP, "iteration": 1, "send_ordinal": 1}


def _list_position_off(content):
    content["answer"]["list_position"] += 1


def _scientific(content):
    content["scientific_result"] = True


@pytest.mark.parametrize("tamper", [_list_position_off, _scientific])
def test_a_completed_send_whose_stored_proposal_does_not_validate_is_no_selection(world, tamper):
    run = world["run"]
    handle, _content = store_choice(world, tamper=tamper)      # fault injection: stored, then refused on read
    assert proposals(run) == {}
    iteration = read(run).record["iterations"][0]
    assert iteration["phase"] == "awaiting_selection"
    # T5 review ruling: a send row names its proposal only when that proposal validates and belongs to the send
    assert iteration["sends"][0]["status"] == "completed" and iteration["sends"][0]["proposal_handle"] is None
    assert handle != iteration["sends"][0]["proposal_handle"]


def test_only_this_loops_validated_loop_proposals_are_read(world):
    run = world["run"]
    good, content = store_choice(world, at=0)
    # an M24 jev_choice@1 of the M24 projection in the same run (a real M24 proposal object)
    m24 = run.store.load(world["m24_projection"])
    m24_choice = S.build_choice(world["m24_projection"], m24, S.source_content(run, m24), send_id=str(uuid.uuid4()),
                                audit_id=f"eg_{uuid.uuid4().hex}", answer={"choice_alias": "m01", "confidence": None,
                                                                          "probabilities": None},
                                served_model=J.SERVED_SNAPSHOT, usage=None, late=False, late_reason=None)
    S.validated_choice(m24_choice, m24, S.source_content(run, m24))
    run.store.put(J.CHOICE_KIND, J.CHOICE_SCHEMA, m24_choice)
    # the M24 proposal content stored under the loop kind (fault injection)
    run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, m24_choice)
    # a loop proposal of another loop (fault injection: only the loop id differs)
    other = copy.deepcopy(content)
    other["loop"]["loop_id"] = "9c3d4e5f-6071-4c8d-8e9f-1a2b3c4d5e6f"
    run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, other)
    # a loop proposal whose projection reference names the M24 projection (fault injection)
    pointed = copy.deepcopy(content)
    pointed["projection"]["handle"] = world["m24_projection"]
    run.store.put(L.CHOICE_KIND, L.CHOICE_SCHEMA, pointed)
    # a loop proposal object stored under another schema name (fault injection)
    run.store.put(L.CHOICE_KIND, "jev_loop_choice@2", content)
    assert proposals(run) == {good: content}
    assert read(run).record["iterations"][0]["phase"] == "awaiting_compute"


def test_proposals_reopen_from_events_only_and_reads_touch_the_log_once(world, tmp_path, monkeypatch):
    handle, content = store_choice(world)
    raw = (world["root"] / LP_RUN / "events.jsonl").read_bytes()
    root = tmp_path / "reopen"
    (root / LP_RUN).mkdir(parents=True)
    (root / LP_RUN / "events.jsonl").write_bytes(raw)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    monkeypatch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    reopened = api_module._run(LP_RUN)
    assert proposals(reopened) == {handle: content}
    reads = {"n": 0}
    original = reopened.events.read

    def counting():
        reads["n"] += 1
        return original()

    monkeypatch.setattr(reopened.events, "read", counting)
    for path in (f"/runs/{LP_RUN}/jev_loops/{LOOP}", f"/runs/{LP_RUN}/jev_loops"):
        reads["n"] = 0
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert reads["n"] == 1, (path, reads["n"])
    record = client.get(f"/runs/{LP_RUN}/jev_loops/{LOOP}").json()
    assert record["iterations"][0]["phase"] == "awaiting_compute"
    assert record["iterations"][0]["sends"][0]["proposal_handle"] == handle
    assert (root / LP_RUN / "events.jsonl").read_bytes() == raw   # reads wrote nothing
    api_module.RUNS.clear()


# ---------------------------------------------------------------- module hygiene (the proposal code stays pure)


def test_the_choice_code_names_no_send_path_or_m24_event_string():
    for name in ("jev_loop_projection.py", "jev_loop_store.py"):
        text = (MW / name).read_text()
        assert "raise_limits" not in text and "limit_approval" not in text
        for event in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME):
            assert event not in text, (name, event)
        tree = ast.parse(text)
        names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
                 if isinstance(node, (ast.Name, ast.Attribute))}
        assert not names & {"run_send", "request_science", "SCIENCE_GATE", "begin_send", "jev_sends", "egress",
                            "ChoiceInvalid", "build_choice", "validated_choice"}, name
