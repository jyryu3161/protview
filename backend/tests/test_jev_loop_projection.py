"""M25 T2 pure loop projection module ``mw.jev_loop_projection`` (spec .dryforge/spec.md 4.2-4.5, 5.2).

Inputs:
* REAL product outputs (committed): the M17 set ``fixtures/ligand_ga/m17-candidate-set-small-pool.json`` and the M20
  set ``fixtures/sequence_ga/m20-candidate-set-1ubq-8pos.json`` (public 1UBQ, 8 positions x 5 = 40 candidates); the
  prepared 1UBQ structure is made here by the unmodified cheap tools through ``Run.call``.
* LABELLED SYNTHETIC values (``# SYNTHETIC`` comments, ``synthetic_*`` helpers): candidate states and score numbers
  given to the builders (test choices standing in for a loop record, never results), made-up SMILES-shaped strings
  for size boundaries, tampered wires / projections / provider replies.

Oracle for the send order, aliases, position aliases, criteria and list positions: the independent standard-library
``fixtures/jev_loop/independent_order.py`` and its ``expected.json`` (no ``mw`` import).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loop_projection as LP
from mw import jev_projection as P
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
FIX = Path(__file__).resolve().parent / "fixtures"
ORACLE = json.loads((FIX / "jev_loop/expected.json").read_text(encoding="utf-8"))
CASES = {case["name"]: case for case in ORACLE["cases"]}
SMALL_POOL = json.loads((FIX / "ligand_ga/m17-candidate-set-small-pool.json").read_text())
M20_8POS = json.loads((FIX / "sequence_ga/m20-candidate-set-1ubq-8pos.json").read_text())["content"]
LIGAND_IDS = [row["id"] for row in SMALL_POOL["candidates"]]
SET_HANDLE = {"ligand": "obj://run_x/ligand_candidate_set/" + "a" * 64,
              "mutation": "obj://run_x/mutation_candidate_set/" + "b" * 64}
STRUCTURE_REF = {"handle": "obj://run_x/prepared_structure/" + "c" * 64, "model_number": 1}
LOOP_ID = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
# SYNTHETIC score numbers for "scored" candidates (inputs standing in for stored first-mode values, not results)
SCORES = [-7.123456789012345, -12, -1.7976931348623157e308, 0.0, -9.8]


def _reason(fn, *args, **kwargs) -> str:
    with pytest.raises(P.JevProjectionError) as caught:
        fn(*args, **kwargs)
    assert caught.value.detail["reason_code"] == caught.value.reason_code
    return caught.value.reason_code


def _keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            found |= _keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _keys(item)
    return found


def rows_for(pool, *, scored=(), states=None, unavailable=()) -> list[dict]:
    """SYNTHETIC loop-record rows in pool order: ``scored`` refs get SCORES in turn, ``states`` maps other refs to a
    non-pending state, ``unavailable`` refs are unavailable, the rest pending."""
    states, rows, n = dict(states or {}), [], 0
    for ref in pool:
        if ref in scored:
            rows.append({"ref": ref, "state": "scored", "score_kcal_mol": SCORES[n % len(SCORES)]})
            n += 1
        elif ref in unavailable:
            rows.append({"ref": ref, "state": "unavailable", "score_kcal_mol": None})
        else:
            rows.append({"ref": ref, "state": states.get(ref, "pending"), "score_kcal_mol": None})
    return rows


def ligand(rows=None, *, goal="explore", seed=0, iteration=1, ordinal=0, content=SMALL_POOL):
    rows = rows_for(LIGAND_IDS) if rows is None else rows
    return LP.build_loop_ligand_wire(content, rows, goal=goal, loop_seed=seed, iteration=iteration,
                                     send_ordinal=ordinal)


def mutation(structure, rows, *, goal="explore", seed=0, iteration=1, ordinal=0, content=M20_8POS):
    return LP.build_loop_mutation_wire(content, rows, structure, goal=goal, loop_seed=seed, iteration=iteration,
                                       send_ordinal=ordinal)


def projection(kind, wire, selection, *, seed=0, iteration=1, ordinal=0, loop_id=LOOP_ID):
    return LP.build_loop_projection_content(
        kind, SET_HANDLE[kind], wire, selection, loop_id=loop_id, loop_seed=seed, iteration=iteration,
        send_ordinal=ordinal, structure=STRUCTURE_REF if kind == "mutation" else None)


def ligand_projection(rows=None, *, goal="exploit", seed=0, iteration=1, ordinal=0):
    wire, selection = ligand(rows, goal=goal, seed=seed, iteration=iteration, ordinal=ordinal)
    return projection("ligand", wire, selection, seed=seed, iteration=iteration, ordinal=ordinal)


MIXED = rows_for(LIGAND_IDS, scored=LIGAND_IDS[1:4], states={LIGAND_IDS[5]: "null_result", LIGAND_IDS[6]: "failed"},
                 unavailable=(LIGAND_IDS[8],))


@pytest.fixture(scope="module")
def ubq(tmp_path_factory):
    run = new_run(tmp_path_factory.mktemp("jev_loop_ubq"), run_id="run_jev_loop_ubq", dry_run=False)
    loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    return _parse(ToolContext(store=run.store, call_id="jev_loop_t2_test"), prepared)


# ---------------------------------------------------------------- independent oracle: order, aliases, positions


def test_oracle_expected_json_matches_a_fresh_oracle_run():
    out = subprocess.run([sys.executable, str(FIX / "jev_loop/independent_order.py"), "--check"],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    oracle_source = (FIX / "jev_loop/independent_order.py").read_text()
    assert not re.search(r"^\s*(from|import)\s+mw\b", oracle_source, re.MULTILINE)


@pytest.mark.parametrize("name", sorted(CASES))
def test_order_keys_and_send_order_equal_the_oracle(name):
    case = CASES[name]
    kept = [ref for ref in case["pool"] if ref not in case["unavailable"]]
    params = {"loop_seed": case["loop_seed"], "iteration": case["iteration"], "send_ordinal": case["send_ordinal"]}
    assert [LP.order_key(ref, **params) for ref in kept] == case["keys"]
    assert LP.shuffled_refs(kept, **params) == case["order"]


def _oracle_rows(case) -> list[dict]:
    return rows_for(case["pool"], scored=case["computed"], unavailable=case["unavailable"])


@pytest.mark.parametrize("goal", L.GOALS)
@pytest.mark.parametrize("name", [n for n in sorted(CASES) if n.startswith("ligand_pool")])
def test_ligand_wire_order_criteria_and_list_positions_equal_the_oracle(name, goal):
    case = CASES[name]
    stored = [ref for ref in LIGAND_IDS if ref in case["pool"]]
    assert stored == case["pool"]   # the oracle pool is in stored (candidate-set) order
    wire, selection = ligand(_oracle_rows(case), goal=goal, seed=case["loop_seed"], iteration=case["iteration"],
                             ordinal=case["send_ordinal"])
    assert [item["ref"] for item in selection] == case["order"]
    assert [{"alias": item["alias"], "ref": item["ref"]} for item in selection] == case["aliases"]
    assert [c["alias"] for c in wire["candidates"]] == [a["alias"] for a in case["aliases"]]
    smiles = {row["id"]: row["smiles"] for row in SMALL_POOL["candidates"]}
    assert [c["smiles"] for c in wire["candidates"]] == [smiles[ref] for ref in case["order"]]
    content = projection("ligand", wire, selection, seed=case["loop_seed"], iteration=case["iteration"],
                         ordinal=case["send_ordinal"])
    criteria = LP.criteria_aliases(content)
    assert criteria == case["criteria"]
    body = json.loads(LP.loop_projection_body(content)[1])
    assert list(body["questions"]["candidate_choice"]["criteria"]) == case["criteria"]
    assert {alias: LP.list_position(criteria, alias) for alias in criteria} == case["list_positions"]
    assert len(criteria) == case["list_size"]


@pytest.mark.parametrize("name", [n for n in sorted(CASES) if n.startswith("mutation_")])
def test_mutation_wire_order_position_aliases_and_list_positions_equal_the_oracle(name, ubq):
    case = CASES[name]
    for goal in L.GOALS:
        wire, selection = mutation(ubq, _oracle_rows(case), goal=goal, seed=case["loop_seed"],
                                   iteration=case["iteration"], ordinal=case["send_ordinal"])
        assert [item["ref"] for item in selection] == case["order"]
        assert [{"alias": item["alias"], "ref": item["ref"]} for item in selection] == case["aliases"]
        residues = [{k: M20_8POS["positions"][p]["residue"][k] for k in J.ALLOWED_RESIDUE}
                    for p in case["position_order"]]
        assert [position["residue"] for position in wire["positions"]] == residues
        assert [position["pos"] for position in wire["positions"]] == [f"p{n:02d}" for n in
                                                                      range(1, len(residues) + 1)]
        by_index = {row["index"]: row for row in M20_8POS["candidates"]}
        pos_alias = {p: f"p{n:02d}" for n, p in enumerate(case["position_order"], 1)}
        assert wire["candidates"] == [{"alias": a["alias"], "pos": pos_alias[by_index[a["ref"]]["position_index"]],
                                       "from": by_index[a["ref"]]["from"], "to": by_index[a["ref"]]["to"]}
                                      for a in case["aliases"]]
        content = projection("mutation", wire, selection, seed=case["loop_seed"], iteration=case["iteration"],
                             ordinal=case["send_ordinal"])
        criteria = LP.criteria_aliases(content)
        assert criteria == case["criteria"]
        assert {alias: LP.list_position(criteria, alias) for alias in criteria} == case["list_positions"]


def test_each_send_ordinal_gives_a_new_order_and_the_same_input_the_same_bytes(ubq):
    for kind in L.KINDS:
        def build(ordinal, seed=11, iteration=2, kind=kind):
            if kind == "ligand":
                wire, selection = ligand(MIXED, goal="exploit", seed=seed, iteration=iteration, ordinal=ordinal)
            else:
                wire, selection = mutation(ubq, rows_for(list(range(0, 40, 3)), scored=[3, 9]), goal="exploit",
                                           seed=seed, iteration=iteration, ordinal=ordinal)
            return projection(kind, wire, selection, seed=seed, iteration=iteration, ordinal=ordinal)

        first = build(0)
        assert build(0) == first and LP.loop_projection_body(build(0))[1] == LP.loop_projection_body(first)[1]
        orders = [tuple(item["ref"] for item in build(ordinal)["selection"]) for ordinal in (0, 1, 2)]
        assert len(set(orders)) == 3, kind
        assert tuple(item["ref"] for item in build(0, seed=12)["selection"]) != orders[0]
        assert tuple(item["ref"] for item in build(0, iteration=3)["selection"]) != orders[0]
        assert sorted(map(str, orders[0])) == sorted(map(str, orders[1]))   # the same candidates, reordered


def test_the_order_does_not_depend_on_the_pool_order_of_the_rows():
    wire, selection = ligand(MIXED, goal="exploit")
    assert ligand(list(reversed(MIXED)), goal="exploit") == (wire, selection)


def test_ties_fall_back_to_the_stored_order(monkeypatch):
    # SYNTHETIC: a constant key makes every candidate tie; the stored order then decides (spec 4.3).
    monkeypatch.setattr(LP, "order_key", lambda ref, **_: "0" * 64)
    refs = LIGAND_IDS[::-1]
    assert LP.shuffled_refs(refs, loop_seed=0, iteration=1, send_ordinal=0) == refs
    _wire, selection = ligand(list(reversed(rows_for(LIGAND_IDS))), goal="explore")
    assert [item["ref"] for item in selection] == LIGAND_IDS   # the candidate-set order, not the request order


@pytest.mark.parametrize(("seed", "iteration", "ordinal"), [
    (-1, 1, 0), (2**31, 1, 0), (True, 1, 0), (1.0, 1, 0), (None, 1, 0), (0, 0, 0), (0, 9, 0), (0, True, 0),
    (0, 1, -1), (0, 1, 1.5), (0, 1, False)])
def test_order_parameter_bounds(seed, iteration, ordinal):
    with pytest.raises(ValueError):
        LP.shuffled_refs(LIGAND_IDS, loop_seed=seed, iteration=iteration, send_ordinal=ordinal)
    with pytest.raises(P.ProjectionInvalid):
        ligand(seed=seed, iteration=iteration, ordinal=ordinal)


def test_ref_text_is_the_id_or_the_decimal_index():
    assert LP.order_key("c_1afb7cd3e603456c", loop_seed=5, iteration=1, send_ordinal=0) == hashlib.sha256(
        b"5:1:0:c_1afb7cd3e603456c").hexdigest()
    assert LP.order_key(17, loop_seed=5, iteration=2, send_ordinal=3) == hashlib.sha256(b"5:2:3:17").hexdigest()
    for bad in (True, -1, 1.0, None, ["c_1afb7cd3e603456c"]):
        with pytest.raises(ValueError):
            LP.order_key(bad, loop_seed=0, iteration=1, send_ordinal=0)


# ---------------------------------------------------------------- the wires


def test_ligand_explore_wire_shape():
    wire, selection = ligand(MIXED, goal="explore")
    assert set(wire) == set(L.ALLOWED_TOP["ligand"])
    assert (wire["schema"], wire["task"], wire["goal"]) == ("jev_loop_ligand_candidates@1", "choose_one_candidate",
                                                            "explore")
    assert wire["values_note"] == L.VALUES_NOTES[("ligand", "explore")]
    m24, m24_selection = P.build_ligand_wire(SMALL_POOL, [r["ref"] for r in MIXED if r["state"] != "unavailable"])
    assert wire["parent"] == m24["parent"] and wire["property_methods"] == m24["property_methods"]
    m24_by_ref = {s["candidate_id"]: c for s, c in zip(m24_selection, m24["candidates"], strict=True)}
    for item, candidate in zip(selection, wire["candidates"], strict=True):
        assert candidate == {**m24_by_ref[item["ref"]], "alias": item["alias"]}   # only the alias differs
    computed = [item["alias"] for item in selection if item["state"] != "pending"]
    assert wire["computed"] == [{"alias": alias} for alias in computed] and len(computed) == 5
    assert [item["state"] for item in selection].count("pending") == 4 and len(selection) == 9
    assert not _keys(wire) & {"handle", "run_id", "path", "id", "origins", "receptor", "pocket", "loop_id",
                              "loop_seed", "iteration", "send_ordinal", "ref", "state", "score_kcal_mol"}


def test_ligand_exploit_wire_keeps_scores_unrounded_and_marks_no_score():
    wire, selection = ligand(MIXED, goal="exploit")
    assert wire["values_note"] == L.VALUES_NOTES[("ligand", "exploit")]
    by_ref = {row["ref"]: row for row in MIXED}
    expected = []
    for item in selection:
        row = by_ref[item["ref"]]
        if row["state"] == "scored":
            expected.append({"alias": item["alias"], "state": "scored", "score_kcal_mol": row["score_kcal_mol"]})
        elif row["state"] != "pending":
            expected.append({"alias": item["alias"], "state": "no_score", "score_kcal_mol": None})
    assert wire["computed"] == expected
    for entry in wire["computed"]:
        if entry["state"] == "scored":
            source = by_ref[next(i["ref"] for i in selection if i["alias"] == entry["alias"])]["score_kcal_mol"]
            assert type(entry["score_kcal_mol"]) is type(source) and repr(entry["score_kcal_mol"]) == repr(source)
    text = P.canonical_ascii(wire).decode()
    for score in SCORES[:3]:
        assert json.dumps(score) in text   # exact stored values, no rounding
    assert {e["state"] for e in wire["computed"]} == {"scored", "no_score"}
    assert "failed" not in text and "null_result" not in text   # failure reasons / states are never sent


def test_explore_sends_no_score_at_all(ubq):
    for kind in L.KINDS:
        if kind == "ligand":
            wire, selection = ligand(MIXED, goal="explore")
        else:
            wire, selection = mutation(ubq, rows_for(list(range(0, 40, 4)), scored=[0, 8, 16]), goal="explore")
        body = LP.loop_projection_body(projection(kind, wire, selection))[1]
        assert b"score" not in body, kind
        for score in SCORES[:3]:
            assert json.dumps(score).encode() not in body


def test_computed_rows_shapes():
    entries = [{"alias": "c01", "state": "pending", "score_kcal_mol": None},
               {"alias": "c02", "state": "scored", "score_kcal_mol": -8.25},
               {"alias": "c03", "state": "not_run", "score_kcal_mol": None},
               {"alias": "c04", "state": "null_result", "score_kcal_mol": None}]
    assert LP.computed_rows("explore", entries) == [{"alias": "c02"}, {"alias": "c03"}, {"alias": "c04"}]
    assert LP.computed_rows("exploit", entries) == [
        {"alias": "c02", "state": "scored", "score_kcal_mol": -8.25},
        {"alias": "c03", "state": "no_score", "score_kcal_mol": None},
        {"alias": "c04", "state": "no_score", "score_kcal_mol": None}]
    assert LP.computed_rows("exploit", entries[:1]) == [] and LP.computed_rows("explore", []) == []


def test_no_computed_candidate_gives_an_empty_computed_list():
    for goal in L.GOALS:
        wire, selection = ligand(goal=goal)
        assert wire["computed"] == [] and all(item["state"] == "pending" for item in selection)


def test_mutation_wire_shape_and_positions_follow_the_m24_fields(ubq):
    pool = [1, 4, 6, 9, 13, 17, 20, 22, 26, 30, 33, 39]
    rows = rows_for(pool, scored=[4, 22], states={13: "not_run", 30: "failed"})
    wire, selection = mutation(ubq, rows, goal="exploit", seed=3, iteration=2, ordinal=1)
    assert set(wire) == set(L.ALLOWED_TOP["mutation"]) - {"pockets"}   # the 1UBQ set used no pocket source
    assert (wire["schema"], wire["goal"]) == ("jev_loop_mutation_candidates@1", "exploit")
    assert wire["values_note"] == L.VALUES_NOTES[("mutation", "exploit")]
    m24, _ = P.build_mutation_wire(M20_8POS, pool, ubq)
    assert wire["protection_checks"] == m24["protection_checks"]

    def ident(position):
        return json.dumps(position["residue"], sort_keys=True)

    m24_positions = {ident(p): p for p in m24["positions"]}
    for position in wire["positions"]:
        assert position == {**m24_positions[ident(position)], "pos": position["pos"]}   # only the alias differs
    assert [item["state"] for item in selection].count("pending") == 8
    assert [e["state"] for e in wire["computed"]].count("no_score") == 2
    assert not _keys(wire) & {"handle", "run_id", "path", "index", "position_index", "loop_id", "loop_seed",
                              "iteration", "send_ordinal", "ref", "numbering", "protection", "exclusion_reasons"}


def test_pockets_are_kept_when_the_set_used_a_pocket_source(ubq):
    content = copy.deepcopy(M20_8POS)   # SYNTHETIC: a pocket source added to the real 1UBQ set
    content["pockets"] = {"pocket_set": "obj://run_x/pocket_set/" + "d" * 64, "ranks": [1, 3],
                          "lining_residue_count": 17}
    wire, _ = mutation(ubq, rows_for([0, 5, 10]), content=content)
    assert wire["pockets"] == {"ranks": [1, 3], "lining_residue_count": 17}
    LP.check_loop_wire(wire, "mutation")


def test_unavailable_candidates_never_reach_the_wire_or_the_selection(ubq):
    wire, selection = ligand(MIXED, goal="exploit")
    gone = LIGAND_IDS[8]
    assert gone not in [item["ref"] for item in selection]
    smiles = next(row["smiles"] for row in SMALL_POOL["candidates"] if row["id"] == gone)
    assert smiles not in [c["smiles"] for c in wire["candidates"]] and len(wire["candidates"]) == 9
    case = CASES["mutation_pool12_s99_i4_o0_computed4_unavailable2"]   # 6 and 9 are all of position 1's refs
    wire, selection = mutation(ubq, _oracle_rows(case), seed=99, iteration=4)
    residue = {k: M20_8POS["positions"][1]["residue"][k] for k in J.ALLOWED_RESIDUE}
    assert residue not in [p["residue"] for p in wire["positions"]] and len(wire["positions"]) == 7
    assert not {6, 9} & {item["ref"] for item in selection}
    assert {item["state"] for item in selection} <= set(L.SELECTION_STATES)


def test_criteria_hold_only_the_uncomputed_aliases_in_wire_order():
    content = ligand_projection(MIXED)
    criteria = LP.criteria_aliases(content)
    assert criteria == [item["alias"] for item in content["selection"] if item["state"] == "pending"]
    computed = {entry["alias"] for entry in content["wire"]["computed"]}
    assert not computed & set(criteria) and len(criteria) + len(computed) == len(content["selection"])
    body = json.loads(LP.loop_projection_body(content)[1])
    assert body["questions"]["candidate_choice"]["criteria"] == {alias: f"Candidate {alias}." for alias in criteria}


def test_list_position_is_the_one_based_place_in_criteria():
    criteria = ["c02", "c05", "c09"]
    assert [LP.list_position(criteria, alias) for alias in criteria] == [1, 2, 3]
    for bad in ("c01", "C02", None, 2):
        with pytest.raises(ValueError):
            LP.list_position(criteria, bad)


# ---------------------------------------------------------------- builder refusals


def test_too_few_pending_candidates_is_refused():
    one_pending = rows_for(LIGAND_IDS, scored=LIGAND_IDS[1:])
    assert _reason(ligand, one_pending) == "too_few_candidates"
    rest_unavailable = rows_for(LIGAND_IDS, unavailable=LIGAND_IDS[1:])
    assert _reason(ligand, rest_unavailable) == "too_few_candidates"
    none_pending = rows_for(LIGAND_IDS, scored=LIGAND_IDS)
    assert _reason(ligand, none_pending) == "too_few_candidates"
    two_pending = rows_for(LIGAND_IDS, scored=LIGAND_IDS[2:])
    _wire, selection = ligand(two_pending)
    assert [item["state"] for item in selection].count("pending") == 2


def _row_change(index, **change):
    def apply(rows):
        rows[index] = {**rows[index], **change}
        return rows
    return apply


BAD_ROWS = {   # SYNTHETIC malformed loop-record rows
    "not_a_list": lambda rows: {"rows": rows},
    "one_row": lambda rows: rows[:1],
    "twenty_one_rows": lambda rows: rows + [{"ref": f"c_{n:016x}", "state": "pending", "score_kcal_mol": None}
                                            for n in range(11)],
    "duplicate_ref": lambda rows: rows[:-1] + [dict(rows[0])],
    "unknown_state": _row_change(0, state="running"),
    "scored_without_score": _row_change(0, state="scored", score_kcal_mol=None),
    "scored_bool_score": _row_change(0, state="scored", score_kcal_mol=True),
    "scored_nan_score": _row_change(0, state="scored", score_kcal_mol=math.nan),
    "scored_inf_score": _row_change(0, state="scored", score_kcal_mol=-math.inf),
    "scored_text_score": _row_change(0, state="scored", score_kcal_mol="-7.1"),
    "pending_with_score": _row_change(0, score_kcal_mol=-7.1),
    "failed_with_zero_score": _row_change(0, state="failed", score_kcal_mol=0.0),
    "missing_key": lambda rows: [{"ref": rows[0]["ref"], "state": "pending"}, *rows[1:]],
    "row_not_a_dict": lambda rows: [rows[0]["ref"], *rows[1:]],
    "ligand_ref_int": _row_change(0, ref=3),
    "ligand_ref_bad_id": _row_change(0, ref="c_XYZ"),
}


@pytest.mark.parametrize("name", sorted(BAD_ROWS))
def test_malformed_rows_are_projection_invalid(name):
    rows = BAD_ROWS[name](rows_for(LIGAND_IDS))
    with pytest.raises(P.ProjectionInvalid):
        ligand(rows)


def test_bad_goal_is_projection_invalid(ubq):
    for goal in ("neutral", None, "EXPLORE"):
        with pytest.raises(P.ProjectionInvalid):
            ligand(goal=goal)
        with pytest.raises(P.ProjectionInvalid):
            mutation(ubq, rows_for([0, 5, 10]), goal=goal)


def test_mutation_rows_need_integer_indices(ubq):
    for bad in ("5", True, -1, 2.0):
        with pytest.raises(P.ProjectionInvalid):
            mutation(ubq, [{"ref": bad, "state": "pending", "score_kcal_mol": None}, *rows_for([0, 10])])


def test_pool_refs_outside_the_set_are_source_invalid(ubq):
    rows = rows_for(LIGAND_IDS)
    rows[0] = {"ref": "c_0000000000000000", "state": "pending", "score_kcal_mol": None}
    assert _reason(ligand, rows) == "source_invalid"
    assert _reason(mutation, ubq, rows_for([0, 5, 999])) == "source_invalid"
    broken = copy.deepcopy(SMALL_POOL)   # SYNTHETIC: a set without readable candidate rows
    del broken["candidates"]
    assert _reason(ligand, content=broken) == "source_invalid"


def test_m24_wire_refusals_pass_through(ubq):
    other_model = copy.deepcopy(M20_8POS)   # SYNTHETIC: stored model number differs from the structure's
    other_model["structure"]["model_number"] = 2
    assert _reason(mutation, ubq, rows_for([0, 5]), content=other_model) == "structure_unavailable"
    assert _reason(mutation, None, rows_for([0, 5])) == "structure_unavailable"
    unsafe = copy.deepcopy(SMALL_POOL)   # SYNTHETIC: a SMILES-shaped field with a space
    unsafe["candidates"][0]["smiles"] = "C C"
    assert _reason(ligand, content=unsafe) == "wire_field_invalid"


# ---------------------------------------------------------------- check_loop_wire


@pytest.fixture(scope="module")
def ligand_wire():
    return ligand(MIXED, goal="exploit")[0]


@pytest.fixture(scope="module")
def mutation_wire(ubq):
    return mutation(ubq, rows_for([1, 4, 6, 9, 13, 17], scored=[4], states={9: "failed"}), goal="exploit")[0]


def test_check_loop_wire_accepts_both_kinds_and_goals(ligand_wire, mutation_wire, ubq):
    LP.check_loop_wire(ligand_wire, "ligand")
    LP.check_loop_wire(mutation_wire, "mutation")
    LP.check_loop_wire(ligand(MIXED, goal="explore")[0], "ligand")
    LP.check_loop_wire(mutation(ubq, rows_for([1, 4, 6], scored=[4]), goal="explore")[0], "mutation")
    with pytest.raises(ValueError):
        LP.check_loop_wire(ligand_wire, "protein")
    with pytest.raises(P.WireFieldInvalid):
        LP.check_loop_wire(ligand_wire, "mutation")


def _computed_alias(wire):
    return wire["computed"][0]["alias"]


LIGAND_TAMPER = {   # SYNTHETIC wire changes
    "extra_top_rank": lambda w: w.update(rank=[1, 2]),
    "extra_top_loop_id": lambda w: w.update(loop_id=LOOP_ID),
    "extra_top_loop_seed": lambda w: w.update(loop_seed=7),
    "extra_top_iteration": lambda w: w.update(iteration=1),
    "extra_top_send_ordinal": lambda w: w.update(send_ordinal=0),
    "extra_top_run_id": lambda w: w.update(run_id="run_x"),
    "extra_top_handle": lambda w: w.update(handle=SET_HANDLE["ligand"]),
    "missing_goal": lambda w: w.pop("goal"),
    "missing_computed": lambda w: w.pop("computed"),
    "m24_schema": lambda w: w.update(schema="jev_ligand_candidates@1"),
    "mutation_schema": lambda w: w.update(schema="jev_loop_mutation_candidates@1"),
    "task": lambda w: w.update(task="rank_candidates"),
    "goal_neutral": lambda w: w.update(goal="neutral"),
    "goal_list": lambda w: w.update(goal=["exploit"]),
    "goal_explore_with_exploit_rows": lambda w: w.update(goal="explore",
                                                         values_note=L.VALUES_NOTES[("ligand", "explore")]),
    "values_note_m24": lambda w: w.update(values_note=J.LIGAND_VALUES_NOTE),
    "values_note_other_goal": lambda w: w.update(values_note=L.VALUES_NOTES[("ligand", "explore")]),
    "computed_not_a_list": lambda w: w.update(computed={}),
    "computed_extra_key": lambda w: w["computed"][0].update(rank=1),
    "computed_handle_key": lambda w: w["computed"][0].update(handle="obj://x"),
    "computed_loop_id_key": lambda w: w["computed"][0].update(loop_id=LOOP_ID),
    "computed_missing_state": lambda w: w["computed"][0].pop("state"),
    "computed_unknown_alias": lambda w: w["computed"][0].update(alias="c99"),
    "computed_duplicate": lambda w: w["computed"].append(dict(w["computed"][0])),
    "computed_out_of_order": lambda w: w["computed"].reverse(),
    "computed_bad_state": lambda w: w["computed"][0].update(state="failed"),
    "computed_scored_null": lambda w: next(e for e in w["computed"] if e["state"] == "scored").update(
        score_kcal_mol=None),
    "computed_no_score_number": lambda w: next(e for e in w["computed"] if e["state"] == "no_score").update(
        score_kcal_mol=0.0),
    "computed_bool_score": lambda w: next(e for e in w["computed"] if e["state"] == "scored").update(
        score_kcal_mol=False),
    "computed_text_score": lambda w: next(e for e in w["computed"] if e["state"] == "scored").update(
        score_kcal_mol="-7.1"),
    "candidate_extra_ref": lambda w: w["candidates"][0].update(ref=LIGAND_IDS[0]),
    "candidate_extra_state": lambda w: w["candidates"][0].update(state="pending"),
    "candidate_extra_score": lambda w: w["candidates"][0].update(score_kcal_mol=-7.0),
    "candidate_id": lambda w: w["candidates"][0].update(id=LIGAND_IDS[0]),
    "smiles_obj_handle": lambda w: w["candidates"][0].update(smiles="obj://run_x/ligand_candidate_set/aa"),
    "smiles_path": lambda w: w["candidates"][0].update(smiles="/Users/me/parent.sdf"),
    "smiles_space": lambda w: w["candidates"][0].update(smiles="C C"),
    "smiles_newline": lambda w: w["candidates"][0].update(smiles="C\nC"),
    "alias_order": lambda w: w["candidates"].reverse(),
    "parent_handle": lambda w: w["parent"].update(handle="obj://x"),
    "property_nan": lambda w: w["candidates"][0]["properties"].update(tpsa=math.nan),
}


@pytest.mark.parametrize("name", sorted(LIGAND_TAMPER))
def test_check_loop_wire_refuses_tampered_ligand_wires(name, ligand_wire):
    wire = copy.deepcopy(ligand_wire)
    LIGAND_TAMPER[name](wire)
    with pytest.raises(P.WireFieldInvalid):
        LP.check_loop_wire(wire, "ligand")


MUTATION_TAMPER = {   # SYNTHETIC wire changes
    "extra_top_loop_seed": lambda w: w.update(loop_seed=7),
    "m24_values_note": lambda w: w.update(values_note=J.MUTATION_VALUES_NOTE),
    "m24_schema": lambda w: w.update(schema="jev_mutation_candidates@1"),
    "candidate_index": lambda w: w["candidates"][0].update(index=3),
    "position_index": lambda w: w["positions"][0].update(position_index=0),
    "position_numbering": lambda w: w["positions"][0].update(numbering={"klifs": 17}),
    "chain_path": lambda w: w["positions"][0]["residue"].update(chain_auth="/tmp"),
    "neighbor_handle": lambda w: w["positions"][0]["neighbors"][0].update(resname="obj://x"),
    "position_alias_order": lambda w: w["positions"].reverse(),
    "computed_score_on_explore_shape": lambda w: w["computed"][0].pop("score_kcal_mol"),
    "pockets_handle": lambda w: w.update(pockets={"ranks": [1], "lining_residue_count": 3,
                                                  "pocket_set": "obj://x"}),
}


@pytest.mark.parametrize("name", sorted(MUTATION_TAMPER))
def test_check_loop_wire_refuses_tampered_mutation_wires(name, mutation_wire):
    wire = copy.deepcopy(mutation_wire)
    MUTATION_TAMPER[name](wire)
    with pytest.raises(P.WireFieldInvalid):
        LP.check_loop_wire(wire, "mutation")


# ---------------------------------------------------------------- body


def test_loop_body_is_deterministic_ascii_and_spec_shaped(ligand_wire):
    criteria = ["c02", "c05", "c07"]
    body = LP.encode_loop_body(ligand_wire, "ligand", "exploit", criteria)
    reordered = dict(reversed(list(json.loads(json.dumps(ligand_wire, sort_keys=True)).items())))
    assert LP.encode_loop_body(reordered, "ligand", "exploit", criteria) == body and body.isascii()
    decoded = json.loads(body)
    assert set(decoded) == set(J.ALLOWED_BODY_KEYS)
    assert decoded["model"] == J.REQUEST_MODEL == "typesafe/jev-1.13" and decoded["provider"] == J.PROVIDER
    assert decoded["state"] == ligand_wire
    assert decoded["questions"] == {"candidate_choice": {
        "type": "choice", "instructions": L.INSTRUCTIONS[("ligand", "exploit")],
        "criteria": {"c02": "Candidate c02.", "c05": "Candidate c05.", "c07": "Candidate c07."}}}
    # the one M24 encoder: sort_keys, "," / ":" separators, allow_nan=False, ASCII
    assert body == P.canonical_ascii(decoded)
    assert body == json.dumps(decoded, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    assert LP.loop_body_object(ligand_wire, "ligand", "exploit", criteria) == decoded
    body_object = LP.loop_body_object(ligand_wire, "ligand", "exploit", criteria)
    body_object["provider"]["zdr"] = False
    assert J.PROVIDER["zdr"] is True
    with pytest.raises(KeyError):
        LP.encode_loop_body(ligand_wire, "protein", "exploit", criteria)


def test_loop_bodies_carry_the_loop_instructions_never_the_m24_ones(ubq):
    for kind in L.KINDS:
        for goal in L.GOALS:
            if kind == "ligand":
                wire, selection = ligand(MIXED, goal=goal)
            else:
                wire, selection = mutation(ubq, rows_for([0, 5, 10, 15], scored=[5]), goal=goal)
            content = projection(kind, wire, selection)
            body_object, body = LP.loop_projection_body(content)
            instructions = body_object["questions"]["candidate_choice"]["instructions"]
            assert instructions == L.INSTRUCTIONS[(kind, goal)]
            assert all(m24.encode() not in body for m24 in J.INSTRUCTIONS.values())
            assert content["question"] == {"id": L.QUESTION_FOR_KIND[kind], "key": "candidate_choice"}
            with pytest.raises(P.ProjectionInvalid):
                P.validated_projection(content)   # the M24 validator never accepts a loop projection


def _ligand_body_bytes(content) -> int:
    rows = rows_for([row["id"] for row in content["candidates"]])
    wire, selection = ligand(rows, goal="explore", content=content)
    criteria = [item["alias"] for item in selection if item["state"] == "pending"]
    return len(LP.encode_loop_body(wire, "ligand", "explore", criteria))


def synthetic_ligand_set(lengths: list[int], *, pains: int = 0) -> dict:
    """SYNTHETIC: the committed real M17 set's top-level fields with made-up rows (``N...C`` strings of the given
    lengths, unique per row; ``pains`` made-up 64-character PAINS-shaped names per row). Shape only, not chemistry."""
    content = copy.deepcopy(SMALL_POOL)
    template = content["candidates"][0]
    rows = []
    for i, length in enumerate(lengths):
        smiles = "N" * (i + 1) + "C" * (length - i - 1)
        row = copy.deepcopy(template)
        row["smiles"] = smiles
        row["id"] = "c_" + hashlib.sha256(smiles.encode()).hexdigest()[:16]
        row["pains"] = {"matches": [{"catalog": "PAINS_C", "name": f"synthetic_{j:03d}_".ljust(64, "n")}
                                    for j in range(pains)]}
        rows.append(row)
    content["candidates"] = rows
    return content


def _tuned_ligand_set(target: int) -> dict:
    """SYNTHETIC: 20 rows whose loop explore body is exactly ``target`` bytes (one SMILES character = one byte)."""
    for pains in range(80):
        lengths = [1024] * 19 + [1000]
        size = _ligand_body_bytes(synthetic_ligand_set(lengths, pains=pains))
        if size >= target:
            break
    excess, row = size - target, 19
    while excess:
        cut = min(excess, lengths[row] - 40)
        lengths[row] -= cut
        excess -= cut
        row -= 1
    content = synthetic_ligand_set(lengths, pains=pains)
    assert _ligand_body_bytes(content) == target
    return content


def test_body_size_boundary_64_kib_is_refused_not_truncated():
    exact = _tuned_ligand_set(L.MAX_BODY_BYTES)
    rows = rows_for([row["id"] for row in exact["candidates"]])
    wire, selection = ligand(rows, goal="explore", content=exact)
    content = projection("ligand", wire, selection)
    assert content["body_bytes"] == L.MAX_BODY_BYTES == 65_536 and len(content["selection"]) == 20
    over = copy.deepcopy(exact)
    last = over["candidates"][-1]
    assert len(last["smiles"]) < 1024
    last["smiles"] += "C"   # SYNTHETIC: one more body byte, still a 1-1024 character SMILES-shaped string
    last["id"] = "c_" + hashlib.sha256(last["smiles"].encode()).hexdigest()[:16]
    rows = rows_for([row["id"] for row in over["candidates"]])
    wire, selection = ligand(rows, goal="explore", content=over)
    assert len(wire["candidates"]) == 20   # nothing dropped or cut
    with pytest.raises(P.PayloadTooLarge) as caught:
        projection("ligand", wire, selection)
    assert caught.value.detail == {"reason_code": "payload_too_large", "body_bytes": 65_537, "limit": 65_536}


# ---------------------------------------------------------------- projection content and validated_loop_projection


def test_ligand_loop_projection_content():
    content = ligand_projection(MIXED, seed=2147483647, iteration=8, ordinal=4)
    assert list(content) == list(L.PROJECTION_KEYS)
    assert (content["schema"], content["method_version"], content["kind"], content["goal"]) == (
        "jev_loop_projection@1", "mw.jev_loop_projection/v1", "ligand", "exploit")
    assert content["loop"] == {"loop_id": LOOP_ID, "iteration": 8, "send_ordinal": 4}
    assert content["order"] == {"algorithm": "sha256_order_v1", "loop_seed": 2147483647, "iteration": 8,
                                "send_ordinal": 4}
    assert content["source"] == {"handle": SET_HANDLE["ligand"], "schema": "ligand_candidate_set@1"}
    assert content["structure"] is None
    assert content["question"] == {"id": "ligand_loop_choice@1", "key": "candidate_choice"}
    assert all(set(item) == {"alias", "ref", "state"} for item in content["selection"])
    body_object, body = LP.loop_projection_body(content)
    assert content["body_sha256"] == hashlib.sha256(body).hexdigest() and content["body_bytes"] == len(body)
    assert content["wire_sha256"] == hashlib.sha256(P.canonical_ascii(content["wire"])).hexdigest()
    assert body_object == json.loads(body) and body_object["state"] == content["wire"]
    assert content["limitations"] == L.limitations_for("ligand", "exploit", False)
    assert LP.validated_loop_projection(content) is content
    assert ligand_projection(MIXED, seed=2147483647, iteration=8, ordinal=4) == content   # same input, same content
    for word in ("time", "created", "call_id", "seq", "uuid", "run_id", "handle_path"):
        assert word not in _keys(content)
    assert LP.validated_loop_projection(json.loads(json.dumps(content, sort_keys=True))) == content
    assert LOOP_ID not in P.canonical_ascii(content["wire"]).decode()


def test_mutation_loop_projection_content(ubq):
    wire, selection = mutation(ubq, rows_for([1, 4, 6, 9, 13], scored=[6]), goal="explore")
    content = projection("mutation", wire, selection)
    assert content["kind"] == "mutation" and content["structure"] == STRUCTURE_REF
    assert content["question"] == {"id": "mutation_loop_choice@1", "key": "candidate_choice"}
    assert content["limitations"] == L.limitations_for("mutation", "explore", False)
    assert all(type(item["ref"]) is int for item in content["selection"])
    LP.validated_loop_projection(json.loads(json.dumps(content, sort_keys=True)))
    for structure in (None, "obj://x", {"handle": STRUCTURE_REF["handle"]},
                      {"handle": "obj://run_x/mutation_candidate_set/" + "c" * 64, "model_number": 1}):
        with pytest.raises(P.ProjectionInvalid):
            LP.build_loop_projection_content("mutation", SET_HANDLE["mutation"], wire, selection, loop_id=LOOP_ID,
                                             loop_seed=0, iteration=1, send_ordinal=0, structure=structure)
    with pytest.raises(P.ProjectionInvalid):   # a ligand projection has no structure
        LP.build_loop_projection_content("ligand", SET_HANDLE["ligand"], *ligand(MIXED), loop_id=LOOP_ID,
                                         loop_seed=0, iteration=1, send_ordinal=0, structure=STRUCTURE_REF)


def _rehash(content: dict) -> dict:
    """Recompute the hashes so that only the tampered rule fails (uses the module's body function on purpose)."""
    kind = content["kind"] if content["kind"] in L.KINDS else "ligand"
    goal = content["wire"].get("goal") if content["wire"].get("goal") in L.GOALS else "exploit"
    criteria = [s["alias"] for s in content["selection"] if isinstance(s, dict) and s.get("state") == "pending"]
    body = LP.encode_loop_body(content["wire"], kind, goal, criteria)
    content["wire_sha256"] = hashlib.sha256(P.canonical_ascii(content["wire"])).hexdigest()
    content["body_sha256"], content["body_bytes"] = hashlib.sha256(body).hexdigest(), len(body)
    return content


def _first(content, state):
    return next(item for item in content["selection"] if item["state"] == state)


def _swap_refs(c):
    first, second = c["selection"][0], c["selection"][1]
    first["ref"], second["ref"] = second["ref"], first["ref"]


PROJECTION_TAMPER = {   # SYNTHETIC tampering of a valid stored projection
    "rank_field": lambda c: c.update(rank=[1, 2]),
    "score_in_wire_candidate": lambda c: c["wire"]["candidates"][0].update(score=1.0),
    "best_in_selection": lambda c: c["selection"][0].update(best=True),
    "schema": lambda c: c.update(schema="jev_loop_projection@2"),
    "m24_schema": lambda c: c.update(schema="jev_projection@1"),
    "method_version": lambda c: c.update(method_version="mw.jev_projection/v1"),
    "kind_protein": lambda c: c.update(kind="protein"),
    "kind_mutation_for_ligand_wire": lambda c: c.update(kind="mutation"),
    "question_m24_id": lambda c: c["question"].update(id="ligand_candidate_choice@1"),
    "question_other_kind": lambda c: c["question"].update(id="mutation_loop_choice@1"),
    "question_key": lambda c: c["question"].update(key="inspection_view"),
    "source_schema": lambda c: c["source"].update(schema="mutation_candidate_set@1"),
    "source_handle_path": lambda c: c["source"].update(handle="/Users/me/set.json"),
    "source_handle_other_kind": lambda c: c["source"].update(handle=SET_HANDLE["mutation"]),
    "structure_on_ligand": lambda c: c.update(structure=STRUCTURE_REF),
    "loop_extra_run_id": lambda c: c["loop"].update(run_id="run_x"),
    "loop_id_v1": lambda c: c["loop"].update(loop_id=str(uuid.uuid1())),
    "loop_id_upper": lambda c: c["loop"].update(loop_id=LOOP_ID.upper()),
    "loop_id_missing": lambda c: c["loop"].pop("loop_id"),
    "iteration_zero": lambda c: (c["loop"].update(iteration=0), c["order"].update(iteration=0)),
    "iteration_nine": lambda c: (c["loop"].update(iteration=9), c["order"].update(iteration=9)),
    "iteration_bool": lambda c: (c["loop"].update(iteration=True), c["order"].update(iteration=True)),
    "send_ordinal_negative": lambda c: (c["loop"].update(send_ordinal=-1), c["order"].update(send_ordinal=-1)),
    "send_ordinal_float": lambda c: (c["loop"].update(send_ordinal=0.0), c["order"].update(send_ordinal=0.0)),
    "goal_differs_from_the_wire": lambda c: c.update(goal="explore"),
    "goal_neutral": lambda c: c.update(goal="neutral"),
    "order_algorithm": lambda c: c["order"].update(algorithm="sha256_order_v2"),
    "order_extra_key": lambda c: c["order"].update(shuffled=True),
    "order_seed_out_of_range": lambda c: c["order"].update(loop_seed=2**31),
    "order_seed_changed": lambda c: c["order"].update(loop_seed=c["order"]["loop_seed"] + 1),
    "order_iteration_differs": lambda c: c["order"].update(iteration=c["loop"]["iteration"] + 1),
    "order_ordinal_differs": lambda c: c["order"].update(send_ordinal=c["loop"]["send_ordinal"] + 1),
    "ordinal_changed_in_both": lambda c: (c["loop"].update(send_ordinal=c["loop"]["send_ordinal"] + 1),
                                          c["order"].update(send_ordinal=c["order"]["send_ordinal"] + 1)),
    "selection_alias_renamed": lambda c: c["selection"][0].update(alias="c09"),
    "selection_reversed": lambda c: c["selection"].reverse(),
    "selection_refs_swapped": _swap_refs,
    "selection_bad_ref": lambda c: c["selection"][0].update(ref="obj://x"),
    "selection_int_ref_for_ligand": lambda c: c["selection"][0].update(ref=3),
    "selection_duplicate_ref": lambda c: c["selection"][1].update(ref=c["selection"][0]["ref"]),
    "selection_state_unavailable": lambda c: c["selection"][0].update(state="unavailable"),
    "selection_pending_to_scored": lambda c: _first(c, "pending").update(state="scored"),
    "selection_scored_to_failed": lambda c: _first(c, "scored").update(state="failed"),
    "selection_failed_to_pending": lambda c: _first(c, "failed").update(state="pending"),
    "selection_extra_key": lambda c: c["selection"][0].update(position_index=0),
    "selection_dropped": lambda c: c["selection"].pop(),
    "computed_dropped": lambda c: c["wire"]["computed"].pop(),
    "limitations_with_j7": lambda c: c["limitations"].append(J.J7),
    "limitations_other_goal": lambda c: c.update(limitations=L.limitations_for("ligand", "explore", False)),
    "limitations_mutation": lambda c: c.update(limitations=L.limitations_for("mutation", "exploit", False)),
    "limitations_m24": lambda c: c.update(limitations=J.limitations_for("ligand", False)),
    "loop_id_inside_the_wire": lambda c: c["wire"]["candidates"][0].update(smiles=c["loop"]["loop_id"]),
    "wire_handle_key": lambda c: c["wire"]["parent"].update(handle="obj://x"),
    "wire_obj_string": lambda c: c["wire"]["candidates"][0].update(smiles="obj://run_x/a"),
    "wire_loop_seed_key": lambda c: c["wire"].update(loop_seed=0),
    "wire_m24_values_note": lambda c: c["wire"].update(values_note=J.LIGAND_VALUES_NOTE),
    "wire_nan": lambda c: c["wire"]["candidates"][0]["properties"].update(tpsa=math.nan),
}
NO_REHASH = {"wire_nan"}


@pytest.fixture(scope="module")
def stored_ligand_projection():
    content = ligand_projection(MIXED, seed=5, iteration=2, ordinal=1)
    assert {item["state"] for item in content["selection"]} == {"pending", "scored", "null_result", "failed"}
    return content


@pytest.mark.parametrize("name", sorted(PROJECTION_TAMPER))
def test_validated_loop_projection_refuses_tampering(name, stored_ligand_projection):
    content = copy.deepcopy(stored_ligand_projection)
    PROJECTION_TAMPER[name](content)
    if name not in NO_REHASH:
        _rehash(content)
    with pytest.raises(P.ProjectionInvalid) as caught:
        LP.validated_loop_projection(content)
    assert caught.value.reason_code == "projection_invalid"


EXPLORE_TAMPER = {   # SYNTHETIC: explore rows carry aliases only, so the alias lists alone must agree
    "pending_to_not_run": lambda c: _first(c, "pending").update(state="not_run"),
    "failed_to_pending": lambda c: _first(c, "failed").update(state="pending"),
    "computed_dropped": lambda c: c["wire"]["computed"].pop(),
    "computed_swapped_for_a_pending_alias": lambda c: c["wire"]["computed"].__setitem__(
        0, {"alias": _first(c, "pending")["alias"]}),
}


@pytest.mark.parametrize("name", sorted(EXPLORE_TAMPER))
def test_validated_explore_projection_matches_computed_aliases_to_the_selection(name):
    content = ligand_projection(MIXED, goal="explore")
    assert LP.validated_loop_projection(copy.deepcopy(content)) == content
    EXPLORE_TAMPER[name](content)
    try:
        _rehash(content)
    except (KeyError, TypeError):
        pass
    with pytest.raises(P.ProjectionInvalid):
        LP.validated_loop_projection(content)


HASH_TAMPER = {
    "wire_sha256": lambda c: c.update(wire_sha256="0" * 64),
    "body_sha256": lambda c: c.update(body_sha256="0" * 64),
    "body_bytes": lambda c: c.update(body_bytes=c["body_bytes"] + 1),
    "body_bytes_bool": lambda c: c.update(body_bytes=True),
    "wire_changed_without_rehash": lambda c: c["wire"]["candidates"][0]["properties"].update(tpsa=1.5),
    "selection_changed_without_rehash": lambda c: _first(c, "pending").update(state="not_run"),
}


@pytest.mark.parametrize("name", sorted(HASH_TAMPER))
def test_validated_loop_projection_recomputes_hashes_and_length(name, stored_ligand_projection):
    content = copy.deepcopy(stored_ligand_projection)
    HASH_TAMPER[name](content)
    with pytest.raises(P.ProjectionInvalid):
        LP.validated_loop_projection(content)


def _keep_pending(content: dict, keep: int) -> dict:
    """SYNTHETIC: all but ``keep`` pending candidates become not_run, with consistent computed rows and hashes."""
    content = copy.deepcopy(content)
    scores = {e["alias"]: e["score_kcal_mol"] for e in content["wire"]["computed"]}
    for item in [item for item in content["selection"] if item["state"] == "pending"][keep:]:
        item["state"] = "not_run"
    content["wire"]["computed"] = LP.computed_rows("exploit", [
        {"alias": item["alias"], "state": item["state"], "score_kcal_mol": scores.get(item["alias"])}
        for item in content["selection"]])
    return _rehash(content)


def test_validated_loop_projection_count_rules(stored_ligand_projection):
    assert len(LP.criteria_aliases(LP.validated_loop_projection(_keep_pending(stored_ligand_projection, 2)))) == 2
    with pytest.raises(P.ProjectionInvalid):   # one uncomputed candidate is never sent (spec 3.3)
        LP.validated_loop_projection(_keep_pending(stored_ligand_projection, 1))
    many = copy.deepcopy(stored_ligand_projection)   # SYNTHETIC: 21 candidates
    template = many["wire"]["candidates"][0]
    many["wire"]["candidates"] = [{**template, "alias": f"c{n:02d}"} for n in range(1, 22)]
    many["wire"]["computed"] = []
    many["selection"] = [{"alias": f"c{n:02d}", "ref": f"c_{n:016x}", "state": "pending"} for n in range(1, 22)]
    with pytest.raises(P.ProjectionInvalid):
        LP.validated_loop_projection(_rehash(many))
    for not_a_projection in (None, [], "jev_loop_projection@1", {}):
        with pytest.raises(P.ProjectionInvalid):
            LP.validated_loop_projection(not_a_projection)


# ---------------------------------------------------------------- parse_loop_choice (spec 5.2)


_DEFAULT = object()


def _response(answer=_DEFAULT, **top) -> dict:
    answer = {"type": "choice", "choice": "c01"} if answer is _DEFAULT else answer
    return {"model": J.SERVED_SNAPSHOT, "answers": {"candidate_choice": answer},
            "usage": {"input_tokens": 10, "output_tokens": 2, "cost": 0.001}, **top}


def test_parse_loop_choice_accepts_an_uncomputed_alias(stored_ligand_projection):
    criteria = LP.criteria_aliases(stored_ligand_projection)
    computed = [e["alias"] for e in stored_ligand_projection["wire"]["computed"]]
    assert len(criteria) == 4 and len(computed) == 5
    pick = criteria[-1]
    assert LP.parse_loop_choice(_response({"type": "choice", "choice": pick}), stored_ligand_projection) == (
        {"choice_alias": pick, "confidence": None, "probabilities": None}, None)
    probabilities = {criteria[2]: 0.5, criteria[0]: 0.25, criteria[1]: 0.25}
    answer = {"type": "choice", "choice": pick, "confidence": 0.5, "probabilities": probabilities}
    parsed, reason = LP.parse_loop_choice(_response(answer), stored_ligand_projection)
    assert reason is None and parsed == {"choice_alias": pick, "confidence": 0.5, "probabilities": probabilities}
    assert list(parsed["probabilities"]) == [criteria[2], criteria[0], criteria[1]]   # received order, no sorting
    sub = {"type": "choice", "choice": criteria[0], "probabilities": {criteria[0]: 1}}
    assert LP.parse_loop_choice(_response(sub), stored_ligand_projection)[1] is None


def test_parse_loop_choice_refuses_computed_aliases_and_out_of_range_probabilities(stored_ligand_projection):
    criteria = LP.criteria_aliases(stored_ligand_projection)
    computed = [e["alias"] for e in stored_ligand_projection["wire"]["computed"]]
    for alias in computed:   # a computed alias is never a selectable choice
        answer = {"type": "choice", "choice": alias}
        assert LP.parse_loop_choice(_response(answer), stored_ligand_projection) == (None, "response_invalid")
        assert P.parse_choice(_response(answer), [s["alias"] for s in stored_ligand_projection["selection"]])[1] \
            is None   # (the M24 parser over every alias would have accepted it)
    bad_probabilities = (
        {computed[0]: 0.1, criteria[0]: 0.9},                    # a computed alias as a probability key
        {"c99": 0.5}, {criteria[0]: 1.5}, {criteria[0]: -0.1}, {criteria[0]: math.nan}, {criteria[0]: True},
        [0.5, 0.5], None)
    for probabilities in bad_probabilities:
        answer = {"type": "choice", "choice": criteria[0], "probabilities": probabilities}
        assert LP.parse_loop_choice(_response(answer), stored_ligand_projection) == (None, "response_invalid")
    for answer in ({"type": "choice", "choice": criteria[0], "reason": "most promising"},
                   {"type": "choice", "choice": criteria[0], "confidence": 1.01},
                   {"type": "rank", "choice": criteria[0]}, {"choice": criteria[0]}, "c01", None):
        assert LP.parse_loop_choice(_response(answer), stored_ligand_projection) == (None, "response_invalid")


def test_parse_loop_choice_model_answer_and_http_error_shapes(stored_ligand_projection):
    content = stored_ligand_projection
    assert LP.parse_loop_choice({"answers": _response()["answers"]}, content) == (None, "missing_model")
    assert LP.parse_loop_choice({**_response(), "model": None}, content) == (None, "missing_model")
    for model in (J.REQUEST_MODEL, "typesafe/jev-1.14-20261001", 5, ""):
        assert LP.parse_loop_choice({**_response(), "model": model}, content) == (None, "model_mismatch"), model
    extra = _response()
    extra["answers"]["inspection_view"] = {"type": "choice", "choice": "c01"}
    assert LP.parse_loop_choice(extra, content) == (None, "response_invalid")
    for data in (None, [], "x", 1, {"model": J.SERVED_SNAPSHOT}, {"model": J.SERVED_SNAPSHOT, "answers": {}}):
        assert LP.parse_loop_choice(data, content) == (None, "response_invalid")
    # SYNTHETIC provider error bodies (the gate checks the HTTP status and size before the parser, unchanged M24
    # stages): an error body that still reaches the parser never becomes a proposal.
    for error_body in ({"error": {"code": 500, "message": "upstream error"}},
                       {"error": {"code": 429}, "model": J.SERVED_SNAPSHOT}):
        parsed, reason = LP.parse_loop_choice(error_body, content)
        assert parsed is None and reason in J.PARSE_REASONS
    # top-level extras of the provider reply (id, usage, created) are not answer keys
    pick = {"type": "choice", "choice": LP.criteria_aliases(content)[0]}
    assert LP.parse_loop_choice(_response(pick, id="r1", created=1), content)[1] is None


def test_criteria_aliases_refuse_a_malformed_selection():
    for selection in (None, [{"alias": "c01"}], [{"alias": 1, "state": "pending"}], "c01"):
        with pytest.raises(P.ProjectionInvalid):
            LP.criteria_aliases({"selection": selection})


# ---------------------------------------------------------------- module hygiene


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module is None:   # from . import name
            found |= {"." * node.level + alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + node.module)
    return found


def test_projection_module_imports_only_stdlib_and_the_jev_constant_and_projection_modules():
    allowed = {"__future__", "hashlib", "itertools", "json", "math", "re", "typing", ".jev_constants",
               ".jev_loop_constants", ".jev_projection"}
    assert _imports(MW / "jev_loop_projection.py") <= allowed


@pytest.mark.parametrize("name", ["jev_loop_constants.py", "jev_loop_projection.py"])
def test_loop_modules_name_no_send_path_limit_raise_or_m24_event_string(name):
    text = (MW / name).read_text()
    assert "raise_limits" not in text and "limit_approval" not in text
    for event in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME):
        assert event not in text, event
    tree = ast.parse(text)
    names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
             if isinstance(node, (ast.Name, ast.Attribute))}
    assert not names & {"run_send", "request_science", "SCIENCE_GATE", "begin_send", "jev_sends", "egress"}
    modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    for module in modules:
        assert module.split(".")[0] not in {"httpx", "rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "urllib",
                                            "http", "requests", "socket", "aiohttp"}, module
        assert "jev_sends" not in module and "egress" not in module, module


def test_importing_the_loop_modules_loads_no_send_network_or_chemistry_module():
    code = ("import sys, mw.jev_loop_constants, mw.jev_loop_projection\n"
            "bad = [m for m in ('httpx', 'rdkit', 'meeko', 'MDAnalysis', 'pdbfixer', 'openmm', 'mw.jev_sends',"
            " 'mw.egress', 'mw.egress.gate', 'mw.egress.science', 'fastapi') if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
