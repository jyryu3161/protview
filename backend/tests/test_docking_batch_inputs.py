"""M19 T2 server pure modules: batch constants, admission, per-row M18 arguments, batch input hash, preflight and
limit-raise arithmetic (spec .dryforge/spec.md 3, 4.2, 5.2, 5.4, 5.5, 6.2, 6.3, 12).

Expected sets, sentences and budget numbers are typed from the spec or taken from the hand oracle in
``fixtures/docking/m19-batch-input.json`` (arithmetic from the spec only), never copied from the module under test.
Store-dependent admission uses a real run with the public receptor, the public-derived parent and a real M17
inspect + enumerate job (pinned RDKit worker; fails, never skips, when the environment is missing).
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
from mw import docking_constants as C
from mw.core.errors import FailureClass, ToolFailure

FIX = Path(__file__).parent / "fixtures" / "docking"
CHEM = Path(__file__).parent / "fixtures" / "chemical"
BATCH = json.loads((FIX / "m19-batch-input.json").read_text())
ORACLE = BATCH["hand_oracle"]
IDS = BATCH["inputs"]["candidate_ids_in_set_order"]
MW = Path(__file__).resolve().parents[1] / "mw"
H_REC = "obj://run_b/chemical_raw_input/" + "a" * 64
H_SET = "obj://run_b/ligand_candidate_set/" + "b" * 64
H_PARENT = "obj://run_b/chemical_raw_input/" + "c" * 64
ACK = {"keep_input_protonation": True, "tool_assigned_types_charges": True, "rigid_no_optimization": True}
PINS = {"engine": "qvina", "qvina_sha256": "1" * 64, "qvina_package": "qvina-2.1.0-x", "versions": {},
        "worker_sha256": "2" * 64, "constants_sha256": "3" * 64, "lock_sha256": "4" * 64,
        "qvina_lock_sha256": "5" * 64}


def _batch(**changes) -> dict:
    args = {"receptor_handle": H_REC, "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
            "candidate_set_handle": H_SET, "parent_sdf_handle": H_PARENT, "candidate_ids": list(IDS),
            "include_parent": False, "mode": "free", "box": {"source": "ligand_range", "margin_A": 8},
            "parameters": {"seed": 42}, "acknowledgement": dict(ACK)}
    args.update(changes)
    return args


def _reason(fn, *args, **kwargs) -> str:
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    assert caught.value.cls is FailureClass.input_invalid
    return caught.value.detail["reason_code"]


# ---------------------------------------------------------------- closed constants (spec 4.2-4.4, 5.4, 5.5)


def test_batch_constants_match_spec():
    assert (BC.PROTOCOL, BC.TOOL, BC.ENGINE) == ("qvina_batch_dock_v1", "qvina_dock_batch", "qvina")
    assert (BC.SUMMARY_SCHEMA, BC.OUTPUT_KIND) == ("docking_batch_result@1", "docking_batch_result")
    assert (BC.MAX_CANDIDATES, BC.PER_CANDIDATE_S, BC.TOTAL_S, BC.TIMEOUT_MAX_S) == (50, 300, 7200, 7800)
    assert BC.MAX_OUTPUT_BYTES == 128 * 1024 * 1024 and BC.MAX_SUMMARY_BYTES == 1024 * 1024
    assert BC.LIMITS == {"max_candidates": 50, "per_candidate_s": 300, "total_s": 7200}
    assert BC.ROW_KINDS == ("parent", "candidate")
    assert BC.ROW_STATES == ("scored", "null_result", "failed", "cancelled", "not_run")
    assert BC.BATCH_STATUSES == ("complete", "partial")
    assert BC.STOP_REASONS == ("cancelled", "time_exhausted", "worker_failed", "resource_exceeded")
    assert BC.ADMISSION_REASONS == ("batch_empty", "batch_too_large", "batch_parent_not_allowed",
                                    "batch_limit_raise_required")
    assert BC.ROW_ONLY_REASONS == ("candidate_timeout", "time_exhausted", "cancelled", "worker_failed")
    assert "resource_exceeded" in C.REASONS  # already an M18 reason (spec 5.5)
    assert BC.SCORE_ROW_LABELS == {"free": "모드 1(엔진 출력 순서)", "core_fixed": "샘플 1(점수 오름차순 나열)"}
    assert (BC.FINISH_MARGIN_S, BC.EMPTY_BATCH_WALL_S, BC.RAISE_MARGIN_S) == (300, 60, 60)
    assert (BC.MAX_RAISE_EXPENSIVE_CALLS, BC.MAX_RAISE_WALL_CLOCK_S) == (51, 7800)


def test_batch_statements_verbatim_and_in_order():
    assert BC.BATCH_STATEMENTS == {
        "B1": "이 일괄의 모든 행은 같은 수용체·상자·seed·방식·값으로 계산되어 점수를 같은 표에서 나란히 볼 수 있으며, "
              "표의 정렬은 표시 순서일 뿐 순위가 아니다.",
        "B2": "이 일괄은 일부만 계산되었다. 계산하지 않은 행은 점수가 없으며 0이 아니다.",
        "B3": "부모 행은 후보와 같은 설정으로 도킹한 기준 입력이며, 점수 차이를 개선이나 악화로 해석하지 않는다.",
    }
    assert list(BC.BATCH_STATEMENTS) == ["B1", "B2", "B3"]


def test_constants_module_has_no_imports():
    tree = ast.parse((MW / "docking_batch_constants.py").read_text())
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                and not (isinstance(node, ast.ImportFrom) and node.module == "__future__")]


# ---------------------------------------------------------------- argument shape (spec 3.1, 3.2, 12)


def test_valid_batch_normalizes_and_fills_defaults():
    out = BI.validate_arguments(_batch(include_parent=True, candidate_ids=[IDS[2], IDS[0]]))
    assert out["candidate_ids"] == [IDS[2], IDS[0]]  # request order; set order is applied with the store
    assert out["include_parent"] is True and out["mode"] == "free"
    assert out["parameters"] == {"seed": 42, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                                 "conformers": None}
    assert out["box"] == {"source": "ligand_range", "margin_A": 8.0}
    assert out["acknowledgement"] == ACK


def test_include_parent_defaults_to_false_and_must_be_bool():
    args = _batch()
    del args["include_parent"]
    assert BI.validate_arguments(args)["include_parent"] is False
    for value in (1, "true", None):
        assert _reason(BI.validate_arguments, _batch(include_parent=value)) == "invalid_job_arguments"


@pytest.mark.parametrize("key", ["ligand", "timeout_s", "cpu", "seed", "receptor"])
def test_unknown_top_level_keys_rejected(key):
    assert _reason(BI.validate_arguments, _batch(**{key: 1})) == "invalid_job_arguments"


@pytest.mark.parametrize("key", ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance",
                                 "candidate_set_handle", "parent_sdf_handle", "candidate_ids", "mode", "box",
                                 "parameters"])
def test_missing_required_key_rejected(key):
    args = _batch()
    del args[key]
    assert _reason(BI.validate_arguments, args) == "invalid_job_arguments"


def test_not_an_object_rejected():
    assert _reason(BI.validate_arguments, [1]) == "invalid_job_arguments"


def test_batch_empty_and_too_large():
    case = {item["case"]: item["reason_code"] for item in ORACLE["admission"]}
    assert _reason(BI.validate_arguments, _batch(candidate_ids=[])) == case["candidate_ids []"]
    many = [f"c_{i:016x}" for i in range(51)]
    assert _reason(BI.validate_arguments, _batch(candidate_ids=many)) == case["51 distinct candidate ids"]
    assert BI.validate_arguments(_batch(candidate_ids=many[:50]))["candidate_ids"] == many[:50]
    # 50 candidates + the parent row is 51 rows and allowed (spec 4.2).
    assert BI.validate_arguments(_batch(candidate_ids=many[:50], include_parent=True))["include_parent"] is True


@pytest.mark.parametrize("ids", [[IDS[0], IDS[0]], [IDS[0], 3], [""], "c_1afb7cd3e603456c", None])
def test_candidate_id_shape_and_duplicates_rejected(ids):
    assert _reason(BI.validate_arguments, _batch(candidate_ids=ids)) == "invalid_job_arguments"


def test_parent_row_with_core_fixed_rejected():
    reason = next(i["reason_code"] for i in ORACLE["admission"] if i["case"].startswith("include_parent true"))
    args = _batch(include_parent=True, mode="core_fixed", parameters={"seed": 1, "conformers": 10})
    assert _reason(BI.validate_arguments, args) == reason == "batch_parent_not_allowed"
    assert BI.validate_arguments(_batch(mode="core_fixed", parameters={"seed": 1}))["parameters"]["conformers"] == 50


def test_m18_rules_apply_to_shared_fields():
    assert _reason(BI.validate_arguments, _batch(acknowledgement={**ACK, "rigid_no_optimization": False})) == \
        "acknowledgement_missing"
    no_ack = _batch()
    del no_ack["acknowledgement"]
    assert _reason(BI.validate_arguments, no_ack) == "acknowledgement_missing"
    assert _reason(BI.validate_arguments, _batch(box={"source": "manual", "center_A": [0, 0, 0],
                                                      "size_A": [41, 10, 10]})) == "box_too_large"
    assert _reason(BI.validate_arguments, _batch(box={"source": "instance_range", "margin_A": 8})) == "box_invalid"
    assert _reason(BI.validate_arguments, _batch(box={"source": "ligand_range", "margin_A": 21})) == "box_invalid"
    assert _reason(BI.validate_arguments, _batch(parameters={"seed": 1, "conformers": 5})) == \
        "invalid_job_arguments"  # conformers only for core_fixed
    assert _reason(BI.validate_arguments, _batch(parameters={"exhaustiveness": 8})) == "invalid_job_arguments"
    assert _reason(BI.validate_arguments, _batch(parameters={"seed": 2147483648})) == "invalid_job_arguments"
    assert _reason(BI.validate_arguments, _batch(mode="flexible")) == "invalid_job_arguments"
    assert _reason(BI.validate_arguments, _batch(receptor_instance={"resname": "LIG"})) == "invalid_job_arguments"


def test_validation_does_not_mutate_input():
    args = _batch(candidate_ids=[IDS[1], IDS[0]])
    before = copy.deepcopy(args)
    BI.validate_arguments(args)
    assert args == before


# ---------------------------------------------------------------- per-row M18 arguments (spec 4.1)


def test_row_arguments_are_valid_m18_arguments():
    normalized = BI.validate_arguments(_batch(include_parent=True))
    parent = BI.row_arguments(normalized, "parent", None)
    assert parent["ligand"] == {"source": "sdf", "sdf_handle": H_PARENT}
    candidate = BI.row_arguments(normalized, "candidate", IDS[1])
    assert candidate["ligand"] == {"source": "candidate", "candidate_set_handle": H_SET, "candidate_id": IDS[1],
                                   "parent_sdf_handle": H_PARENT}
    for kind, cid, row in (("parent", None, parent), ("candidate", IDS[1], candidate)):
        request = BI.row_request(normalized, kind, cid)
        assert "conformers" not in request["parameters"]  # M18 refuses conformers (even null) in free mode
        assert docking_inputs.validate_arguments(request) == row
        assert {k: row[k] for k in ("receptor_handle", "receptor_model_number", "connectivity",
                                    "receptor_instance", "mode", "box", "parameters", "acknowledgement")} == \
            {k: normalized[k] for k in ("receptor_handle", "receptor_model_number", "connectivity",
                                        "receptor_instance", "mode", "box", "parameters", "acknowledgement")}


def test_row_arguments_match_a_standalone_m18_request():
    """Same row input as a user's standalone M18 request -> same input_sha256 (spec 4.1)."""
    normalized = BI.validate_arguments(_batch(mode="core_fixed", parameters={"seed": 42, "conformers": 50}))
    standalone = docking_inputs.validate_arguments({
        "receptor_handle": H_REC, "receptor_model_number": 1,
        "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": None,
        "ligand": {"source": "candidate", "candidate_set_handle": H_SET, "candidate_id": IDS[0],
                   "parent_sdf_handle": H_PARENT},
        "mode": "core_fixed", "box": {"source": "ligand_range"}, "parameters": {"seed": 42},
        "acknowledgement": ACK})
    row = BI.row_arguments(normalized, "candidate", IDS[0])
    assert docking_inputs.input_sha256(row) == docking_inputs.input_sha256(standalone)
    assert docking_bundle.call_key(row, PINS) == docking_bundle.call_key(standalone, PINS)


def test_planned_rows_use_set_order_and_parent_first():
    for case in ORACLE["row_order"]:
        rows = BI.planned_rows(case["selected_ids"], IDS, case["include_parent"])
        assert [[row["kind"], row["candidate_id"]] for row in rows] == case["rows"], case["how"]
        assert [row["row_index"] for row in rows] == list(range(len(case["rows"])))


# ---------------------------------------------------------------- batch input hash (spec 5.2, 5.3)


def _row_selection(normalized: dict, kind: str, cid: str | None, removed=None) -> dict:
    args = BI.row_arguments(normalized, kind, cid)
    ligand = ({"source": "sdf", "sdf": {"handle": H_PARENT, "sha256": BATCH["inputs"]["parent_sdf_sha256"]}}
              if kind == "parent" else
              {"source": "candidate", "candidate_set_handle": H_SET,
               "candidate_set_parent_sha256": BATCH["inputs"]["parent_sdf_sha256"],
               "parent_sdf": {"handle": H_PARENT, "sha256": BATCH["inputs"]["parent_sdf_sha256"]},
               "candidate": {"id": cid, "smiles": "C", "retained_parent_atoms": [1], "stereo_flag": "none"}})
    return {"schema": "docking_selection@1", "arguments": args, "input_sha256": docking_inputs.input_sha256(args),
            "receptor": {"handle": H_REC, "sha256": BATCH["inputs"]["receptor_sha256"], "format": "pdb",
                         "atom_count": 100, "instance_sites": [], "removed_instance": removed},
            "sidecar": None, "ligand": ligand}


def _selection(**changes) -> dict:
    normalized = BI.validate_arguments(_batch(**changes))
    plan = BI.planned_rows(normalized["candidate_ids"], IDS, normalized["include_parent"])
    normalized = {**normalized, "candidate_ids": [r["candidate_id"] for r in plan if r["kind"] == "candidate"]}
    return BI.batch_selection(normalized, [_row_selection(normalized, r["kind"], r["candidate_id"]) for r in plan])


def _oracle_batch_sha(sel: dict) -> str:
    """Spec 5.2 field list, written out independently of the module."""
    args = sel["arguments"]
    payload = {"receptor": {"handle": H_REC, "sha256": BATCH["inputs"]["receptor_sha256"],
                            "model_number": args["receptor_model_number"],
                            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None, "sidecar_sha256": None},
                            "instance": args["receptor_instance"]},
               "candidate_set_handle": H_SET,
               "parent_sdf": {"handle": H_PARENT, "sha256": BATCH["inputs"]["parent_sdf_sha256"]},
               "candidate_ids": args["candidate_ids"], "include_parent": args["include_parent"],
               "mode": args["mode"], "box": args["box"], "parameters": args["parameters"]}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def test_batch_selection_records_rows_and_hash():
    sel = _selection(include_parent=True, candidate_ids=[IDS[2], IDS[0]])
    assert sel["schema"] == "docking_batch_selection@1"
    assert sel["arguments"]["candidate_ids"] == [IDS[0], IDS[2]]
    assert [(r["row_index"], r["kind"], r["candidate_id"]) for r in sel["rows"]] == \
        [(0, "parent", None), (1, "candidate", IDS[0]), (2, "candidate", IDS[2])]
    assert sel["receptor"]["sha256"] == BATCH["inputs"]["receptor_sha256"]
    assert sel["parent_sdf"] == {"handle": H_PARENT, "sha256": BATCH["inputs"]["parent_sdf_sha256"]}
    assert sel["batch_input_sha256"] == BI.batch_input_sha256(sel) == _oracle_batch_sha(sel)


def test_batch_hash_excludes_acknowledgement_and_changes_with_meaningful_inputs():
    base = _selection()["batch_input_sha256"]
    assert _selection(parameters={"seed": 42, "exhaustiveness": 8})["batch_input_sha256"] == base
    for changes in ({"parameters": {"seed": 43}}, {"include_parent": True}, {"candidate_ids": IDS[:2]},
                    {"box": {"source": "ligand_range", "margin_A": 7}}, {"mode": "core_fixed"}):
        assert _selection(**changes)["batch_input_sha256"] != base, changes


def test_batch_selection_refuses_rows_that_disagree():
    normalized = BI.validate_arguments(_batch())
    rows = [_row_selection(normalized, "candidate", cid) for cid in IDS]
    rows[1]["receptor"]["sha256"] = "f" * 64
    with pytest.raises(ValueError):
        BI.batch_selection(normalized, rows)


# ---------------------------------------------------------------- reuse detection and preflight (spec 4.5, 6.2, 6.3)


def _budget(calls_used=0, wall_used=0.0, calls_limit=8, wall_limit=1800.0) -> dict:
    return {"expensive_calls": {"used": calls_used, "limit": calls_limit},
            "wall_clock_s": {"used": wall_used, "limit": wall_limit}}


@pytest.mark.parametrize("case", ORACLE["budget_cases"][:5], ids=lambda c: f"N={c['new_dockings']}")
def test_needed_and_shortfall_match_hand_oracle(case):
    used = case["used"]
    needed = BI.needed_budget(case["new_dockings"])
    assert needed == case["needed"], case["how"]
    snapshot = _budget(used["expensive_calls"], used["wall_clock_s"])
    assert BI.shortfall(needed, snapshot) == case["shortfall"], case["how"]
    assert BI.full_batch_may_be_partial(case["new_dockings"]) is case["full_batch_may_be_partial"]


def test_empty_batch_needs_sixty_seconds():
    """Spec 6.3 says N = 0 needs 60 s (the fixture's 300 s predates that sentence; the spec wins)."""
    assert BI.needed_budget(0) == {"expensive_calls": 0, "wall_clock_s": 60}
    assert BI.shortfall(BI.needed_budget(0), _budget(8, 1800)) == {"expensive_calls": 0, "wall_clock_s": 60}
    assert BI.full_batch_may_be_partial(0) is False


def test_needed_wall_cap_boundaries():
    assert BI.needed_budget(1)["wall_clock_s"] == 600
    assert BI.needed_budget(24)["wall_clock_s"] == 7500
    assert BI.needed_budget(25)["wall_clock_s"] == 7800
    assert BI.needed_budget(51) == {"expensive_calls": 51, "wall_clock_s": 7800}
    for bad in (-1, 52, True, 1.0):
        with pytest.raises(ValueError):
            BI.needed_budget(bad)


def _apply(snapshot: dict, increase: dict) -> dict:
    out = copy.deepcopy(snapshot)
    for axis, amount in increase.items():
        out[axis]["limit"] += amount
    return out


def test_limit_increase_raises_only_the_shortfall_with_wall_margin():
    case = ORACLE["budget_cases"][1]  # remaining 2 units / 1200 s, needs 4 / 1500
    snapshot = _budget(6, 600)
    increase = BI.limit_increase(BI.needed_budget(4), snapshot)
    assert increase == {"expensive_calls": case["shortfall"]["expensive_calls"],
                        "wall_clock_s": case["shortfall"]["wall_clock_s"] + 60}
    raised = _apply(snapshot, increase)
    assert BI.shortfall(BI.needed_budget(4), raised) == {"expensive_calls": 0, "wall_clock_s": 0}
    assert BI.limit_increase(BI.needed_budget(4), raised) == {"expensive_calls": 0, "wall_clock_s": 0}


def test_limit_increase_is_idempotent_and_zero_when_enough():
    assert BI.limit_increase(BI.needed_budget(4), _budget()) == {"expensive_calls": 0, "wall_clock_s": 0}
    snapshot = _budget(0, 0)
    first = BI.limit_increase(BI.needed_budget(51), snapshot)
    assert first == {"expensive_calls": 43, "wall_clock_s": 6060}  # oracle shortfall 43 / 6000, +60 s margin
    twice = _apply(_apply(snapshot, first), BI.limit_increase(BI.needed_budget(51), _apply(snapshot, first)))
    assert twice == _apply(snapshot, first)


def test_limit_increase_never_exceeds_one_batch_need():
    # A run that already used everything: the shortfall is the whole need; the increment stays <= 51 / 7800 s.
    snapshot = _budget(8, 1800)
    increase = BI.limit_increase(BI.needed_budget(51), snapshot)
    assert increase == {"expensive_calls": 51, "wall_clock_s": 7800}
    # Usage far above the defaults: no absolute cap, the limit still goes up by the need only.
    snapshot = _budget(300, 50_000, 300, 50_000)
    assert BI.limit_increase(BI.needed_budget(10), snapshot) == {"expensive_calls": 10, "wall_clock_s": 3360}
    # Only one axis short: the other is untouched.
    assert BI.limit_increase(BI.needed_budget(4), _budget(8, 0, 8)) == {"expensive_calls": 4, "wall_clock_s": 0}


def test_require_budget_refuses_with_limit_raise_reason():
    with pytest.raises(ToolFailure) as caught:
        BI.require_budget(BI.needed_budget(4), _budget(6, 600))
    assert caught.value.cls is FailureClass.resource_exceeded
    assert caught.value.detail["reason_code"] == "batch_limit_raise_required"
    assert caught.value.detail["shortfall"] == {"expensive_calls": 2, "wall_clock_s": 300}
    BI.require_budget(BI.needed_budget(4), _budget())  # enough: no refusal


def test_preflight_detects_reuse_by_m18_call_key():
    sel = _selection(include_parent=True)
    keys = BI.row_call_keys(sel, PINS)
    assert keys == [docking_bundle.call_key(row["selected"]["arguments"], PINS) for row in sel["rows"]]
    existing = {keys[0]: "obj://run_b/docking_result/" + "d" * 64, keys[2]: "obj://run_b/docking_result/" + "e" * 64}
    out = BI.preflight(sel, PINS, existing, _budget(6, 600))
    assert [(r["row_index"], r["kind"], r["candidate_id"], r["reuse"], r["reused_handle"]) for r in out["rows"]] == [
        (0, "parent", None, True, existing[keys[0]]), (1, "candidate", IDS[0], False, None),
        (2, "candidate", IDS[1], True, existing[keys[2]]), (3, "candidate", IDS[2], False, None)]
    assert out["new_dockings"] == 2
    assert out["needed"] == {"expensive_calls": 2, "wall_clock_s": 900}
    assert out["remaining"] == {"expensive_calls": 2, "wall_clock_s": 1200}
    assert out["shortfall"] == {"expensive_calls": 0, "wall_clock_s": 0}
    assert out["full_batch_may_be_partial"] is False
    assert out["batch_input_sha256"] == sel["batch_input_sha256"]


def test_preflight_all_reused_is_zero_units():
    sel = _selection()
    existing = {key: f"obj://run_b/docking_result/{i:064d}" for i, key in enumerate(BI.row_call_keys(sel, PINS))}
    out = BI.preflight(sel, PINS, existing, _budget(8, 1800))
    assert out["new_dockings"] == 0 and all(r["reuse"] for r in out["rows"])
    assert out["needed"] == {"expensive_calls": 0, "wall_clock_s": 60}
    assert out["shortfall"] == {"expensive_calls": 0, "wall_clock_s": 60}


def test_published_m18_results_index_only_completed_single_jobs():
    events = [
        {"type": "job_submitted", "seq": 1, "job": {"job_id": "j1", "protocol_id": "qvina_dock_v1",
                                                    "call_key": "K1"}},
        {"type": "job_terminal", "seq": 2, "job_id": "j1", "status": "done", "output_handles": ["h1"]},
        {"type": "job_submitted", "seq": 3, "job": {"job_id": "j2", "protocol_id": "qvina_dock_v1",
                                                    "call_key": "K2"}},
        {"type": "job_terminal", "seq": 4, "job_id": "j2", "status": "failed", "output_handles": []},
        {"type": "job_submitted", "seq": 5, "job": {"job_id": "j3", "protocol_id": "rdkit_enumerate_v1",
                                                    "call_key": "K3"}},
        {"type": "job_terminal", "seq": 6, "job_id": "j3", "status": "done", "output_handles": ["h3"]},
    ]
    assert BI.published_m18_results(events) == {"K1": "h1"}


# ---------------------------------------------------------------- store-dependent admission (real run, real M17)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    run = new_ligand_run(tmp_path_factory.mktemp("batch"), "run_batch_admission", dry_run=False)
    receptor = import_file(run, "receptor", "rec.pdb", (CHEM / "prolif-vina-rec.pdb").read_bytes())
    parent = import_file(run, "ligand_sdf", "parent.sdf", (FIX / "public-derived-parent-record0.sdf").read_bytes())
    planar = import_file(run, "ligand_sdf", "planar.sdf", (FIX / "synthetic-ligand-planar-z0.sdf").read_bytes())
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi",
                         (FIX / "synthetic-docking-blocks.smi").read_bytes())
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    return {"run": run, "receptor": receptor, "parent": parent, "planar": planar,
            "candidate_set": enumerated["output_handles"][0]}


def _real(world, **changes) -> dict:
    fields = {"receptor_handle": world["receptor"], "candidate_set_handle": world["candidate_set"],
              "parent_sdf_handle": world["parent"]}
    return _batch(**{**fields, **changes})


def test_submission_builds_row_selections_equal_to_standalone_m18(world):
    run = world["run"]
    selected, normalized, handles = BI.submission(run, _real(world, include_parent=True,
                                                             candidate_ids=[IDS[2], IDS[0]]))
    assert normalized["candidate_ids"] == [IDS[0], IDS[2]] and selected["arguments"] == normalized
    assert handles == [world["receptor"], world["candidate_set"], world["parent"]]
    assert [(r["kind"], r["candidate_id"]) for r in selected["rows"]] == \
        [("parent", None), ("candidate", IDS[0]), ("candidate", IDS[2])]
    for row in selected["rows"]:
        standalone, _, _ = docking_bundle.submission(run, BI.row_request(normalized, row["kind"],
                                                                         row["candidate_id"]))
        assert row["selected"] == standalone
    assert selected["receptor"]["sha256"] == BATCH["inputs"]["receptor_sha256"]
    assert selected["parent_sdf"]["sha256"] == BATCH["inputs"]["parent_sdf_sha256"]
    assert selected["batch_input_sha256"] == BI.batch_input_sha256(selected)


def test_submission_rejections(world):
    run = world["run"]
    assert _reason(BI.submission, run, _real(world, candidate_ids=[IDS[0], "c_0000000000000000"])) == \
        "candidate_unknown"
    assert _reason(BI.submission, run, _real(world, parent_sdf_handle=world["planar"])) == "parent_mismatch"
    assert _reason(BI.submission, run, _real(world, candidate_ids=[])) == "batch_empty"
    assert _reason(BI.submission, run, _real(world, include_parent=True, mode="core_fixed")) == \
        "batch_parent_not_allowed"
    foreign = "obj://other_run/ligand_candidate_set/" + "0" * 64
    assert _reason(BI.submission, run, _real(world, candidate_set_handle=foreign)) == "invalid_job_arguments"
    assert _reason(BI.submission, run, _real(world, candidate_set_handle=world["parent"])) == \
        "invalid_job_arguments"
    assert _reason(BI.submission, run, _real(world, receptor_handle=world["parent"])) == "invalid_job_arguments"
    assert _reason(BI.submission, run, _real(world, box={"source": "instance_range", "margin_A": 8})) == \
        "box_invalid"


def test_submission_creates_no_events(world):
    run = world["run"]
    before = len(list(run.events.read()))
    BI.submission(run, _real(world))
    with pytest.raises(ToolFailure):
        BI.submission(run, _real(world, candidate_ids=["c_0000000000000000"]))
    assert len(list(run.events.read())) == before


# ---------------------------------------------------------------- isolation


@pytest.mark.parametrize("name", ["docking_batch_constants.py", "docking_batch_inputs.py",
                                  "docking_batch_bundle.py"])
def test_batch_server_modules_import_no_rdkit_meeko_or_mdanalysis(name):
    tree = ast.parse((MW / name).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m.split(".")[0] in {"rdkit", "meeko", "MDAnalysis"} for m in imported), name
    text = (MW / name).read_text()
    assert "__import__" not in text and "importlib" not in text and "subprocess" not in text


def test_batch_server_modules_load_without_rdkit_or_meeko():
    code = ("import sys; import mw.docking_batch_constants, mw.docking_batch_inputs, mw.docking_batch_bundle; "
            "print(any(m.split('.')[0] in ('rdkit', 'meeko', 'MDAnalysis') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
