"""M18 T3 server pure modules: closed constants, job-argument admission, receptor instances (spec 3, 5.1, 5.3, 5.4).

Expected sets and sentences below are typed from the spec, not copied from the module under test. Receptor
expectations come from the T1 fixtures (``fixtures/docking/expected.json``, hand oracle) and, for the M11-equivalence
checks only, from the unmodified M11 functions used as the reference implementation.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import gemmi
import pytest

from mw import docking_constants as C
from mw.chemical_inputs import _bonds, import_raw, receptor_atoms
from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import ObjectStore
from mw.docking_inputs import (
    call_key_input,
    check_receptor,
    input_sha256,
    instance_summary,
    receptor_bonds,
    receptor_instances,
    receptor_rows,
    resolve_instance,
    validate_arguments,
)

FIX = Path(__file__).parent / "fixtures" / "docking"
CHEM = Path(__file__).parent / "fixtures" / "chemical"
EXPECTED = json.loads((FIX / "expected.json").read_text())
MW = Path(__file__).resolve().parents[1] / "mw"
H = "obj://run_t3/chemical_raw_input/" + "a" * 64
H2 = "obj://run_t3/chemical_raw_input/" + "b" * 64
INSTANCE = {"model_number": 1, "chain_auth": "L", "chain_label": None, "seq_auth": 1, "seq_label": None,
            "icode": "", "resname": "LIG"}
ACK = {"keep_input_protonation": True, "tool_assigned_types_charges": True, "rigid_no_optimization": True}


def _base(**changes) -> dict:
    args = {"receptor_handle": H, "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None},
            "receptor_instance": None,
            "ligand": {"source": "sdf", "sdf_handle": H2},
            "mode": "free",
            "box": {"source": "ligand_range", "margin_A": 8.0},
            "parameters": {"seed": 0, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3},
            "acknowledgement": dict(ACK)}
    args.update(changes)
    return args


def _candidate(**changes) -> dict:
    fields = {"ligand": {"source": "candidate", "candidate_set_handle": H2, "candidate_id": "c_1afb7cd3e603456c",
                         "parent_sdf_handle": H}, "mode": "core_fixed"}
    return _base(**{**fields, **changes})


def _reason(fn, *args, **kwargs) -> str:
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    assert caught.value.cls is FailureClass.input_invalid
    return caught.value.detail["reason_code"]


def _failure(fn, *args, **kwargs) -> ToolFailure:
    with pytest.raises(ToolFailure) as caught:
        fn(*args, **kwargs)
    return caught.value


# ---------------------------------------------------------------- closed constants (spec 5.3, 5.4)


def test_reason_sets_match_spec_verbatim():
    assert C.RECEPTOR_REASONS == ("receptor_invalid", "receptor_hydrogens_missing", "receptor_unsupported_residue",
                                  "receptor_altloc_present", "receptor_instance_unknown",
                                  "receptor_instance_ambiguous", "receptor_instance_covalent",
                                  "receptor_prep_failed")
    assert C.LIGAND_REASONS == ("ligand_unparseable", "ligand_record_count", "ligand_multiple_fragments",
                                "ligand_element_not_allowed", "ligand_too_many_atoms", "ligand_too_many_torsions",
                                "ligand_not_3d", "ligand_hydrogens_missing", "ligand_prep_failed")
    assert C.CANDIDATE_REASONS == ("candidate_unknown", "parent_mismatch", "parent_not_3d", "core_match_failed",
                                   "core_match_ambiguous", "embed_failed")
    assert C.BOX_REASONS == ("box_invalid", "box_too_large", "box_no_receptor_atoms")
    assert C.ENGINE_REASONS == ("engine_failed", "engine_output_invalid", "resource_exceeded")
    # M21 (user approved, spec 7): one admission-only reason added; the worker reason set is unchanged.
    assert C.ADMISSION_ONLY_REASONS == ("invalid_job_arguments", "mode_source_mismatch", "acknowledgement_missing",
                                        "mutation_model_invalid")
    assert "mutation_model_invalid" not in C.REASONS
    assert C.REASONS == (C.RECEPTOR_REASONS + C.LIGAND_REASONS + C.CANDIDATE_REASONS + C.BOX_REASONS +
                         C.ENGINE_REASONS)
    assert len(set(C.REASONS + C.ADMISSION_ONLY_REASONS)) == 33
    assert C.CAPABILITY_REASONS == ("worker_missing", "engine_missing", "engine_hash_mismatch", "handshake_failed",
                                    "version_mismatch")


SPEC_LIMITATIONS = (
    "점수는 qvina 2.1(Vina 계열 스코어링 함수)이 낸 값(kcal/mol)이며 결합 친화도·결합 자유 에너지가 아니다.",
    "같은 수용체·상자·seed·방식(자유/코어 고정)·값에서 나온 점수끼리만 나란히 볼 수 있다.",
    "수용체는 입력 그대로의 강체이며 수소·양성자화·토토머를 바꾸지 않았고, AutoDock4 원자 유형·부분 전하는 Meeko가 정한 값이다.",
    "리간드 고리 형태는 입력 형태(후보는 RDKit이 만든 형태)로 고정되어 탐색하지 않았다.",
    "접촉은 거리만으로 센 기하 접촉이며 수소결합 등 상호작용 판정이 아니다.",
    "포즈는 엔진이 낸 배치이며 실험으로 확인한 결합 자세가 아니다.",
    "후보의 3D 좌표와 수소는 RDKit이 만든 것이며 입력 구조가 아니다.",
    ("코어 중원자 좌표만 부모 값으로 고정했고 나머지는 RDKit 구속 형태 샘플이며, 점수만 매기고 구조는 최적화하지 않았다. "
     "이 배치는 실험으로 확인한 결합 자세가 아니다."),
    "수용체에서 지정한 리간드 인스턴스 하나만 뺐고 그 밖의 요소는 바꾸지 않았다.",
    "자유 도킹은 RDKit 형태 하나를 시작점으로 썼다.",
    "미지정 입체 중심의 입체는 RDKit이 임의로 정한 것이다.",
    # 12: M21, user approved, only for the mutation_model receptor source (appended last)
    "수용체는 변이 모델링으로 최소화한 구조이며 리간드 자세는 이 수용체에 맞춰 조정하지 않았다(리간드 좌표는 사용자가 준 SDF 그대로).",
)


def test_limitation_sentences_match_spec_verbatim_and_in_order():
    assert C.LIMITATIONS == SPEC_LIMITATIONS
    assert C.SCORE_LABEL == "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"
    assert C.SCORE_COLUMN_LABEL == "qvina 점수(kcal/mol)"


@pytest.mark.parametrize("mode,source,removed,stereo,numbers", [
    ("free", "sdf", False, None, [1, 2, 3, 4, 5, 6]),
    ("free", "sdf", True, None, [1, 2, 3, 4, 5, 6, 9]),
    ("free", "candidate", False, 0, [1, 2, 3, 4, 5, 6, 7, 10]),
    ("free", "candidate", True, 2, [1, 2, 3, 4, 5, 6, 7, 9, 10, 11]),
    ("core_fixed", "candidate", False, 0, [1, 2, 3, 4, 5, 7, 8]),
    ("core_fixed", "candidate", True, 1, [1, 2, 3, 4, 5, 7, 8, 9, 11]),
])
def test_limitation_conditions(mode, source, removed, stereo, numbers):
    got = C.applicable_limitations(mode=mode, source=source, removed_instance=removed,
                                   unspecified_stereo_centers=stereo)
    assert got == tuple(SPEC_LIMITATIONS[n - 1] for n in numbers)


@pytest.mark.parametrize("kwargs", [
    {"mode": "core_fixed", "source": "sdf", "removed_instance": False, "unspecified_stereo_centers": None},
    {"mode": "rigid", "source": "sdf", "removed_instance": False, "unspecified_stereo_centers": None},
    {"mode": "free", "source": "smiles", "removed_instance": False, "unspecified_stereo_centers": None},
    {"mode": "free", "source": "sdf", "removed_instance": 1, "unspecified_stereo_centers": None},
    {"mode": "free", "source": "candidate", "removed_instance": False, "unspecified_stereo_centers": -1},
    {"mode": "free", "source": "candidate", "removed_instance": False, "unspecified_stereo_centers": True},
])
def test_limitation_conditions_reject_impossible_combinations(kwargs):
    with pytest.raises(ValueError):
        C.applicable_limitations(**kwargs)


def test_value_ranges_defaults_and_enumerations():
    assert (C.SEED_MIN, C.SEED_MAX) == (0, 2147483647)
    assert (C.EXHAUSTIVENESS_MIN, C.EXHAUSTIVENESS_MAX, C.EXHAUSTIVENESS_DEFAULT) == (1, 32, 8)
    assert (C.NUM_MODES_MIN, C.NUM_MODES_MAX, C.NUM_MODES_DEFAULT) == (1, 20, 9)
    assert (C.ENERGY_RANGE_MIN, C.ENERGY_RANGE_MAX, C.ENERGY_RANGE_DEFAULT) == (1, 5, 3)
    assert (C.CONFORMERS_MIN, C.CONFORMERS_MAX, C.CONFORMERS_DEFAULT) == (1, 200, 50)
    assert (C.MARGIN_MIN_A, C.MARGIN_MAX_A, C.MARGIN_DEFAULT_A) == (0, 20, 8)
    assert (C.BOX_SIDE_MIN_A, C.BOX_SIDE_MAX_A) == (8, 40)
    assert C.MAX_LIGAND_HEAVY_ATOMS == 100 and C.MAX_ACTIVE_TORSIONS == 32
    assert C.CONTACT_CUTOFF_A == 4.0 and C.CPU == 1
    assert (C.TIMEOUT_DEFAULT_S, C.TIMEOUT_MAX_S) == (600, 900)
    assert C.MAX_RESULT_BYTES == 4 * 1024 * 1024
    assert C.MAX_RECEPTOR_ATOMS == 10_000 and C.MAX_LISTED_RECEPTOR_ITEMS == 20
    assert C.ALLOWED_LIGAND_ELEMENTS == ("H", "C", "N", "O", "S", "P", "F", "Cl", "Br", "I")
    assert C.BOX_SOURCES == ("ligand_range", "instance_range", "manual")
    assert C.MODES == ("free", "core_fixed")
    assert C.LIGAND_SOURCES == ("sdf", "candidate")
    assert C.CONNECTIVITY_KINDS == ("pdb_conect", "sidecar")
    assert C.CONTACT_KINDS == ("polar_contact", "hydrophobic_contact", "contact")
    assert C.ACKNOWLEDGEMENT_KEYS == ("keep_input_protonation", "tool_assigned_types_charges",
                                      "rigid_no_optimization")
    assert C.METHODS == {"free": "qvina_free_v1", "core_fixed": "qvina_core_fixed_score_only_v1"}
    assert (C.PROTOCOL, C.TOOL, C.ENGINE, C.RESULT_SCHEMA) == ("qvina_dock_v1", "qvina_dock_ligand", "qvina",
                                                               "docking_result@1")


def test_contact_cap_fits_result_limit_at_t1_worst_case():
    # T1 (f): worst contact row 346 B, 200-atom pose SDF ~17,058 B, non-mode part 2,258 B, num_modes max 20.
    per_mode = 346 * C.MAX_CONTACTS_PER_MODE + 17_058 + 1_000
    assert 2_258 + C.NUM_MODES_MAX * per_mode <= C.MAX_RESULT_BYTES
    assert C.MAX_CONTACTS_PER_MODE >= 80  # largest observed on the public example (T1)


def test_constants_module_has_no_imports():
    tree = ast.parse((MW / "docking_constants.py").read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom)]
    assert [ast.unparse(node) for node in imports] == ["from __future__ import annotations"]


# ---------------------------------------------------------------- job-argument shape (spec 5.1)


def test_valid_sdf_free_normalizes_with_null_conformers():
    out = validate_arguments(_base())
    assert out["parameters"] == {"seed": 0, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                                 "conformers": None}
    assert out["box"] == {"source": "ligand_range", "margin_A": 8.0}
    assert out["acknowledgement"] == ACK
    assert out["receptor_instance"] is None


def test_defaults_fill_omitted_adjustable_values():
    args = _candidate(parameters={"seed": 5}, box={"source": "ligand_range"})
    out = validate_arguments(args)
    assert out["parameters"] == {"seed": 5, "exhaustiveness": 8, "num_modes": 9, "energy_range": 3.0,
                                 "conformers": 50}
    assert out["box"] == {"source": "ligand_range", "margin_A": 8.0}
    assert out["ligand"] == {"source": "candidate", "candidate_set_handle": H2, "candidate_id": "c_1afb7cd3e603456c",
                             "parent_sdf_handle": H}


def test_free_mode_rejects_conformers_key_even_null():
    for value in (50, None):
        args = _base(parameters={"seed": 0, "conformers": value})
        assert _reason(validate_arguments, args) == "invalid_job_arguments"
    args = _candidate(mode="free", parameters={"seed": 0, "conformers": 10})
    assert _reason(validate_arguments, args) == "invalid_job_arguments"
    assert validate_arguments(_candidate(mode="free"))["parameters"]["conformers"] is None


def test_core_fixed_requires_candidate_source():
    assert _reason(validate_arguments, _base(mode="core_fixed")) == "mode_source_mismatch"


@pytest.mark.parametrize("path,value", [
    ((), "extra"),
    (("connectivity",), "extra"),
    (("ligand",), "extra"),
    (("box",), "extra"),
    (("parameters",), "extra"),
])
def test_unknown_keys_rejected(path, value):
    args = _base()
    target = args
    for key in path:
        target = target[key]
    target["unexpected"] = value
    assert _reason(validate_arguments, args) == "invalid_job_arguments"


def test_unknown_key_in_instance_and_acknowledgement_rejected():
    args = _base(receptor_instance={**INSTANCE, "altloc": ""})
    assert _reason(validate_arguments, args) == "invalid_job_arguments"
    args = _base(acknowledgement={**ACK, "extra": True})
    assert _reason(validate_arguments, args) == "invalid_job_arguments"


@pytest.mark.parametrize("key", ["receptor_handle", "receptor_model_number", "connectivity", "receptor_instance",
                                 "ligand", "mode", "box", "parameters", "acknowledgement"])
def test_missing_top_level_key_rejected(key):
    args = _base()
    del args[key]
    expected = "acknowledgement_missing" if key == "acknowledgement" else "invalid_job_arguments"
    assert _reason(validate_arguments, args) == expected


@pytest.mark.parametrize("args", [
    "not an object",
    _base(receptor_handle=""),
    _base(receptor_handle=7),
    _base(receptor_model_number=0),
    _base(receptor_model_number=True),
    _base(receptor_model_number=1.0),
    _base(receptor_model_number="1"),
    _base(connectivity={"kind": "pdb_conect", "sidecar_handle": H2}),
    _base(connectivity={"kind": "sidecar", "sidecar_handle": None}),
    _base(connectivity={"kind": "mmcif_bonds", "sidecar_handle": None}),
    _base(connectivity={"kind": "pdb_conect"}),
    _base(ligand={"source": "sdf"}),
    _base(ligand={"source": "sdf", "sdf_handle": H2, "candidate_id": "c_1afb7cd3e603456c"}),
    _base(ligand={"source": "smiles", "sdf_handle": H2}),
    _base(ligand={"source": "candidate", "candidate_set_handle": H2, "candidate_id": 3, "parent_sdf_handle": H}),
    _base(mode="rigid"),
    _base(box={"source": "pocket", "margin_A": 8.0}),
    _base(box={"source": "manual", "center_A": [0, 0, 0]}),
    _base(box={"source": "manual", "center_A": [0, 0, 0], "size_A": [20, 20, 20], "margin_A": 8.0}),
    _base(box=[0, 0, 0]),
    _base(parameters={"exhaustiveness": 8}),
    _base(parameters="seed"),
])
def test_shape_errors_are_invalid_job_arguments(args):
    assert _reason(validate_arguments, args) == "invalid_job_arguments"


@pytest.mark.parametrize("instance", [
    {k: v for k, v in INSTANCE.items() if k != "icode"},
    {**INSTANCE, "model_number": True},
    {**INSTANCE, "model_number": 0},
    {**INSTANCE, "seq_auth": "1"},
    {**INSTANCE, "seq_auth": True},
    {**INSTANCE, "seq_label": 1.0},
    {**INSTANCE, "chain_label": 5},
    {**INSTANCE, "icode": None},
    {**INSTANCE, "resname": ""},
    "LIG",
])
def test_malformed_receptor_instance_rejected(instance):
    assert _reason(validate_arguments, _base(receptor_instance=instance)) == "invalid_job_arguments"


@pytest.mark.parametrize("name,low,high", [
    ("seed", 0, 2147483647), ("exhaustiveness", 1, 32), ("num_modes", 1, 20), ("conformers", 1, 200),
])
def test_integer_parameter_boundaries(name, low, high):
    for value in (low, high):
        parameters = {"seed": 0, name: value}
        assert validate_arguments(_candidate(parameters=parameters))["parameters"][name] == value
    for value in (low - 1, high + 1, True, False, float(low), "1", None, math.nan):
        if name == "seed" and value is False:
            continue  # False would equal 0; still a bool, checked separately below
        parameters = {"seed": 0, name: value}
        assert _reason(validate_arguments, _candidate(parameters=parameters)) == "invalid_job_arguments", value
    assert _reason(validate_arguments, _candidate(parameters={"seed": False})) == "invalid_job_arguments"


def test_energy_range_boundaries_and_finite_numbers():
    for value, normalized in ((1, 1.0), (5, 5.0), (2.5, 2.5), (3, 3.0)):
        assert validate_arguments(_base(parameters={"seed": 0, "energy_range": value}))["parameters"][
            "energy_range"] == normalized
    for value in (0.999, 5.001, math.nan, math.inf, -math.inf, True, "3", None):
        args = _base(parameters={"seed": 0, "energy_range": value})
        assert _reason(validate_arguments, args) == "invalid_job_arguments", value


def test_margin_boundaries_are_box_invalid():
    for value in (0, 20, 0.0, 8):
        assert validate_arguments(_base(box={"source": "ligand_range", "margin_A": value}))["box"][
            "margin_A"] == float(value)
    for value in (-0.001, 20.001, math.nan, math.inf, True, "8", None):
        args = _base(box={"source": "ligand_range", "margin_A": value})
        assert _reason(validate_arguments, args) == "box_invalid", value


def test_manual_box_values():
    ok = validate_arguments(_base(box={"source": "manual", "center_A": [1, -0.0, 2.5], "size_A": [8, 40, 20.5]}))
    assert ok["box"] == {"source": "manual", "center_A": [1.0, 0.0, 2.5], "size_A": [8.0, 40.0, 20.5]}
    assert json.dumps(ok["box"]["center_A"]) == "[1.0, 0.0, 2.5]"  # -0.0 normalized
    for size in ([7.999, 20, 20], [20, 20, math.nan], [20, 20], [20, 20, 20, 20], [20, True, 20],
                 [20, "20", 20], "20", [-20, 20, 20]):
        args = _base(box={"source": "manual", "center_A": [0, 0, 0], "size_A": size})
        assert _reason(validate_arguments, args) == "box_invalid", size
    for center in ([0, 0, math.inf], [0, 0], [0, 0, None], [0, 0, 100_001]):
        args = _base(box={"source": "manual", "center_A": center, "size_A": [20, 20, 20]})
        assert _reason(validate_arguments, args) == "box_invalid", center
    args = _base(box={"source": "manual", "center_A": [0, 0, 0], "size_A": [20, 40.001, 20]})
    assert _reason(validate_arguments, args) == "box_too_large"


def test_instance_range_requires_receptor_instance():
    assert _reason(validate_arguments, _base(box={"source": "instance_range", "margin_A": 8})) == "box_invalid"
    out = validate_arguments(_base(receptor_instance=dict(INSTANCE), box={"source": "instance_range"}))
    assert out["box"] == {"source": "instance_range", "margin_A": 8.0}
    assert out["receptor_instance"] == INSTANCE


@pytest.mark.parametrize("ack", [
    {**ACK, "keep_input_protonation": False},
    {**ACK, "rigid_no_optimization": 1},
    {**ACK, "tool_assigned_types_charges": "true"},
    {k: v for k, v in ACK.items() if k != "rigid_no_optimization"},
    {},
    None,
    True,
])
def test_acknowledgement_missing(ack):
    assert _reason(validate_arguments, _base(acknowledgement=ack)) == "acknowledgement_missing"


def test_validation_does_not_mutate_input():
    args = _candidate(parameters={"seed": 1})
    before = copy.deepcopy(args)
    validate_arguments(args)
    assert args == before


# ---------------------------------------------------------------- call-key normalization


def _independent_sha(normalized: dict) -> str:
    body = {k: v for k, v in normalized.items() if k != "acknowledgement"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def test_call_key_input_excludes_acknowledgement_and_is_order_independent():
    out = validate_arguments(_base())
    key = call_key_input(out)
    assert "acknowledgement" not in key
    assert set(key) == {"receptor_handle", "receptor_model_number", "connectivity", "receptor_instance", "ligand",
                        "mode", "box", "parameters"}
    assert input_sha256(out) == _independent_sha(out)
    reordered = dict(reversed(list(_base().items())))
    reordered["parameters"] = dict(reversed(list(reordered["parameters"].items())))
    assert input_sha256(validate_arguments(reordered)) == input_sha256(out)


def test_equivalent_spellings_share_one_call_key_and_seed_changes_it():
    explicit = validate_arguments(_base(parameters={"seed": 0, "exhaustiveness": 8, "num_modes": 9,
                                                    "energy_range": 3.0}, box={"source": "ligand_range",
                                                                               "margin_A": 8}))
    implicit = validate_arguments(_base(parameters={"seed": 0}, box={"source": "ligand_range"}))
    assert input_sha256(explicit) == input_sha256(implicit)
    assert input_sha256(validate_arguments(_base(parameters={"seed": 1}))) != input_sha256(implicit)
    assert input_sha256(validate_arguments(_base(mode="free", ligand={"source": "sdf", "sdf_handle": H}))) != \
        input_sha256(implicit)
    with_instance = validate_arguments(_base(receptor_instance=dict(INSTANCE)))
    assert input_sha256(with_instance) != input_sha256(implicit)


# ---------------------------------------------------------------- receptor instances (spec 3.1, 3.2)


def _raw(name: str, folder: Path = FIX) -> bytes:
    return (folder / name).read_bytes()


def test_instance_listing_complex_preserves_null_labels_and_counts():
    listing = receptor_instances(_raw("synthetic-complex-receptor-lig.pdb"), "pdb")
    expected = EXPECTED["receptor_fixtures"]["synthetic-complex-receptor-lig.pdb"]
    assert listing["schema"] == "docking_receptor_instances@1"
    assert listing["models"] == [{"model_number": 1, "water_residue_count": 0, "instances": [
        {"residue": EXPECTED["receptor_fixtures"]["instance"], "atom_count": expected["instance_atoms"],
         "element_counts": expected["instance_element_counts"]}]}]
    residue = listing["models"][0]["instances"][0]["residue"]
    assert residue["chain_label"] is None and residue["seq_label"] is None and residue["icode"] == ""


def test_instance_listing_water_count_only_and_metal_listed():
    listing = receptor_instances(_raw("synthetic-receptor-water-zinc.pdb"), "pdb")
    (model,) = listing["models"]
    assert model["water_residue_count"] == 1
    assert [row["residue"]["resname"] for row in model["instances"]] == ["ZN"]
    assert model["instances"][0] == {"residue": {"model_number": 1, "chain_auth": "Z", "chain_label": None,
                                                 "seq_auth": 1, "seq_label": None, "icode": "", "resname": "ZN"},
                                     "atom_count": 1, "element_counts": {"Zn": 1}}


def test_instance_listing_duplicates_and_plain_protein():
    dup = receptor_instances(_raw("synthetic-complex-duplicate-instance.pdb"), "pdb")["models"][0]["instances"]
    assert [row["residue"] for row in dup] == [INSTANCE, INSTANCE]
    assert receptor_instances(_raw("prolif-vina-rec.pdb", CHEM), "pdb")["models"][0]["instances"] == []


def test_instance_listing_rejects_malformed_bytes():
    assert _reason(receptor_instances, b"not a structure", "pdb") == "receptor_invalid"
    assert _reason(receptor_instances, _raw("synthetic-complex-receptor-lig.pdb"), "sdf") == "receptor_invalid"


def test_resolve_instance_exact_seven_fields():
    rows = receptor_rows(_raw("synthetic-complex-receptor-lig.pdb"), "pdb", H, 1)
    sites = resolve_instance(rows, INSTANCE)
    assert sites == list(range(4988, 5067))
    summary = instance_summary(rows, sites)
    expected = EXPECTED["receptor_fixtures"]["synthetic-complex-receptor-lig.pdb"]
    assert summary == {"residue": INSTANCE, "atom_count": 79, "element_counts": expected["instance_element_counts"]}


@pytest.mark.parametrize("change", [
    {"seq_auth": 2}, {"chain_auth": "A"}, {"chain_label": "L"}, {"seq_label": 1}, {"icode": "A"},
    {"resname": "LIG2"}, {"model_number": 2},
])
def test_resolve_instance_unknown_when_any_field_differs(change):
    rows = receptor_rows(_raw("synthetic-complex-receptor-lig.pdb"), "pdb", H, 1)
    assert _reason(resolve_instance, rows, {**INSTANCE, **change}) == "receptor_instance_unknown"


def test_resolve_instance_refuses_standard_residue_and_water():
    rows = receptor_rows(_raw("synthetic-receptor-water-zinc.pdb"), "pdb", H, 1)
    tyr = {"model_number": 1, "chain_auth": "A", "chain_label": None, "seq_auth": 38, "seq_label": None,
           "icode": "", "resname": "TYR"}
    water = {**tyr, "chain_auth": "W", "seq_auth": 1, "resname": "HOH"}
    assert _reason(resolve_instance, rows, tyr) == "receptor_instance_unknown"
    assert _reason(resolve_instance, rows, water) == "receptor_instance_unknown"


def test_resolve_instance_ambiguous_never_first():
    rows = receptor_rows(_raw("synthetic-complex-duplicate-instance.pdb"), "pdb", H, 1)
    failure = _failure(resolve_instance, rows, INSTANCE)
    assert failure.detail["reason_code"] == "receptor_instance_ambiguous"
    assert failure.detail["matches"] == 2


def test_mmcif_labels_are_part_of_identity():
    st = gemmi.read_pdb_string(_raw("synthetic-complex-receptor-lig.pdb").decode())
    st.setup_entities()
    st.assign_label_seq_id(True)
    cif = st.make_mmcif_document().as_string().encode()
    listing = receptor_instances(cif, "cif")["models"][0]["instances"]
    (row,) = listing
    labelled = row["residue"]
    assert labelled["chain_label"] is not None and labelled["chain_auth"] == "L"
    rows = receptor_rows(cif, "cif", H, 1)
    assert len(resolve_instance(rows, labelled)) == 79
    assert _reason(resolve_instance, rows, INSTANCE) == "receptor_instance_unknown"  # null label != label


def test_receptor_rows_match_m11_traversal(tmp_path: Path):
    store = ObjectStore(tmp_path / "run", "run_t3_rows")
    raw = _raw("synthetic-complex-receptor-lig.pdb")
    handle = import_raw(store, "receptor", "complex.pdb", raw)["handle"]
    reference = receptor_atoms(store, handle, 1)
    rows = receptor_rows(raw, "pdb", handle, 1)
    assert len(rows) == len(reference) == 5067
    for mine, theirs in zip(rows, reference, strict=True):
        assert {k: mine[k] for k in theirs} == theirs


def test_receptor_rows_model_number_must_exist():
    raw = _raw("synthetic-complex-receptor-lig.pdb")
    assert _reason(receptor_rows, raw, "pdb", H, 2) == "receptor_invalid"


# ---------------------------------------------------------------- connectivity adapter (M11 _bonds rules)


def _pdb_atom(serial: int, name: str, resname: str, chain: str, seq: int, xyz: tuple, element: str,
              record: str = "ATOM  ", altloc: str = " ") -> str:
    padded = f" {name:<3s}" if len(name) < 4 else name
    return (f"{record}{serial:5d} {padded}{altloc}{resname:>3s} {chain}{seq:4d}    "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00  0.00          {element:>2s}")


def _tiny(conect: list[str], serials: tuple[int, int, int] = (1, 2, 3)) -> bytes:
    atoms = [_pdb_atom(serials[0], "N", "GLY", "A", 1, (0, 0, 0), "N"),
             _pdb_atom(serials[1], "CA", "GLY", "A", 1, (1.45, 0, 0), "C"),
             _pdb_atom(serials[2], "HA2", "GLY", "A", 1, (1.8, 1.0, 0), "H")]
    return ("\n".join(atoms + conect + ["END"]) + "\n").encode()


PDB_CONECT = {"kind": "pdb_conect", "sidecar_handle": None}


def test_pdb_conect_reverse_duplicates_merge():
    raw = _tiny(["CONECT    1    2", "CONECT    2    1    3", "CONECT    3    2"])
    rows = receptor_rows(raw, "pdb", H, 1)
    assert receptor_bonds(rows, PDB_CONECT, raw, "pdb", H) == [[0, 1], [1, 2]]


@pytest.mark.parametrize("conect", [["CONECT    1    1"], ["CONECT    1    9"], ["CONECT    9    1"],
                                    ["CONECT    1   xx"], []])
def test_pdb_conect_self_dangling_malformed_or_empty_rejected(conect):
    raw = _tiny(conect)
    rows = receptor_rows(raw, "pdb", H, 1)
    assert _reason(receptor_bonds, rows, PDB_CONECT, raw, "pdb", H) == "receptor_invalid"


def test_pdb_conect_ambiguous_serial_rejected():
    raw = _tiny(["CONECT    1    2"], serials=(1, 2, 2))
    rows = receptor_rows(raw, "pdb", H, 1)
    assert _reason(receptor_bonds, rows, PDB_CONECT, raw, "pdb", H) == "receptor_invalid"


def test_pdb_conect_requires_pdb_format():
    raw = _tiny(["CONECT    1    2"])
    rows = receptor_rows(raw, "pdb", H, 1)
    assert _reason(receptor_bonds, rows, PDB_CONECT, raw, "cif", H) == "receptor_invalid"


def _sidecar(rows: list, pairs: list, **changes) -> bytes:
    obj = {"schema": "receptor_bonds@1", "complete": True, "source_handle": H,
           "bonds": [{"first": rows[a]["ref"], "second": rows[b]["ref"]} for a, b in pairs]}
    obj.update(changes)
    return json.dumps(obj).encode()


SIDECAR = {"kind": "sidecar", "sidecar_handle": H2}


def test_sidecar_bonds_accepted():
    raw = _tiny([])
    rows = receptor_rows(raw, "pdb", H, 1)
    assert receptor_bonds(rows, SIDECAR, raw, "pdb", H, _sidecar(rows, [(1, 0), (1, 2)])) == [[0, 1], [1, 2]]


@pytest.mark.parametrize("pairs,changes", [
    ([(0, 1), (1, 0)], {}),                    # duplicate (reversed) bond is refused in a sidecar
    ([(0, 1), (0, 1)], {}),
    ([(0, 0)], {}),                            # self bond
    ([(0, 1)], {"complete": False}),
    ([(0, 1)], {"source_handle": H2}),         # another source
    ([(0, 1)], {"schema": "receptor_bonds@2"}),
    ([], {}),
])
def test_sidecar_rule_violations_rejected(pairs, changes):
    raw = _tiny([])
    rows = receptor_rows(raw, "pdb", H, 1)
    assert _reason(receptor_bonds, rows, SIDECAR, raw, "pdb", H, _sidecar(rows, pairs, **changes)) == \
        "receptor_invalid"


def test_sidecar_dangling_or_mismatched_ref_rejected():
    raw = _tiny([])
    rows = receptor_rows(raw, "pdb", H, 1)
    bad_site = {**rows[1]["ref"], "site_index": 9}
    bad_name = {**rows[1]["ref"], "atom_name": "CB"}
    for second in (bad_site, bad_name, {**rows[1]["ref"], "extra": 1}):
        body = json.dumps({"schema": "receptor_bonds@1", "complete": True, "source_handle": H,
                           "bonds": [{"first": rows[0]["ref"], "second": second}]}).encode()
        assert _reason(receptor_bonds, rows, SIDECAR, raw, "pdb", H, body) == "receptor_invalid"
    assert _reason(receptor_bonds, rows, SIDECAR, raw, "pdb", H, b"{not json") == "receptor_invalid"
    assert _reason(receptor_bonds, rows, SIDECAR, raw, "pdb", H, None) == "receptor_invalid"


def test_pdb_conect_adapter_matches_m11_bonds(tmp_path: Path):
    store = ObjectStore(tmp_path / "run", "run_t3_bonds")
    raw = _raw("synthetic-complex-receptor-lig.pdb")
    handle = import_raw(store, "receptor", "complex.pdb", raw)["handle"]
    m11_rows = receptor_atoms(store, handle, 1)
    reference = _bonds(store, {"connectivity": PDB_CONECT}, m11_rows, raw, handle)
    mine = receptor_bonds(receptor_rows(raw, "pdb", handle, 1), PDB_CONECT, raw, "pdb", handle)
    assert mine == reference and len(mine) > 5053


def test_sidecar_adapter_matches_m11_bonds(tmp_path: Path):
    store = ObjectStore(tmp_path / "run", "run_t3_sidecar")
    raw = _tiny([])
    handle = import_raw(store, "receptor", "tiny.pdb", raw)["handle"]
    rows = receptor_rows(raw, "pdb", handle, 1)
    body = json.dumps({"schema": "receptor_bonds@1", "complete": True, "source_handle": handle,
                       "bonds": [{"first": rows[1]["ref"], "second": rows[0]["ref"]},
                                 {"first": rows[2]["ref"], "second": rows[1]["ref"]}]}).encode()
    sidecar = import_raw(store, "receptor_bonds", "bonds.json", body)["handle"]
    connectivity = {"kind": "sidecar", "sidecar_handle": sidecar}
    reference = _bonds(store, {"connectivity": connectivity}, receptor_atoms(store, handle, 1), None, handle)
    assert receptor_bonds(rows, connectivity, raw, "pdb", handle, body) == reference == [[0, 1], [1, 2]]


# ---------------------------------------------------------------- receptor admission sequence


def test_check_receptor_removes_exactly_one_instance():
    raw = _raw("synthetic-complex-receptor-lig.pdb")
    out = check_receptor(raw, "pdb", H, 1, PDB_CONECT, INSTANCE)
    assert out["instance_sites"] == list(range(4988, 5067))
    assert out["removed_instance"] == {"residue": INSTANCE, "atom_count": 79,
                                       "element_counts": {"C": 33, "H": 36, "N": 5, "O": 5}}
    assert len(out["rows"]) == 5067


def test_check_receptor_plain_protein_without_instance():
    out = check_receptor(_raw("prolif-vina-rec.pdb", CHEM), "pdb", H, 1, PDB_CONECT, None)
    assert out["removed_instance"] is None and out["instance_sites"] == [] and len(out["bonds"]) == 5053


def test_check_receptor_reasons_from_fixtures():
    complex_raw = _raw("synthetic-complex-receptor-lig.pdb")
    failure = _failure(check_receptor, complex_raw, "pdb", H, 1, PDB_CONECT, None)
    assert failure.detail["reason_code"] == "receptor_unsupported_residue"
    assert failure.detail["items"] == [{"residue": INSTANCE, "atom_names": [
        row["ref"]["atom_name"] for row in receptor_rows(complex_raw, "pdb", H, 1)[4988:]]}]
    assert _reason(check_receptor, _raw("synthetic-complex-duplicate-instance.pdb"), "pdb", H, 1, PDB_CONECT,
                   INSTANCE) == "receptor_instance_ambiguous"
    assert _reason(check_receptor, complex_raw, "pdb", H, 1, PDB_CONECT,
                   {**INSTANCE, "seq_auth": 2}) == "receptor_instance_unknown"
    covalent = _failure(check_receptor, _raw("synthetic-complex-covalent-instance.pdb"), "pdb", H, 1, PDB_CONECT,
                        INSTANCE)
    assert covalent.detail["reason_code"] == "receptor_instance_covalent"
    endpoints = {(atom["residue"]["resname"], atom["atom_name"]) for pair in covalent.detail["bonds"]
                 for atom in pair}
    assert endpoints == {("LIG", "C14"), ("TYR", "CAY")}
    water = _failure(check_receptor, _raw("synthetic-receptor-water-zinc.pdb"), "pdb", H, 1, PDB_CONECT, None)
    assert water.detail["reason_code"] == "receptor_unsupported_residue"
    assert [(item["residue"]["resname"], item["residue"]["chain_auth"], item["atom_names"])
            for item in water.detail["items"]] == [("HOH", "W", ["O", "H1", "H2"]), ("ZN", "Z", ["ZN"])]
    altloc = _failure(check_receptor, _raw("synthetic-receptor-altloc.pdb"), "pdb", H, 1, PDB_CONECT, None)
    assert altloc.detail["reason_code"] == "receptor_altloc_present"
    assert [(item["residue"]["seq_auth"], item["atom_name"], item["altloc"]) for item in altloc.detail["items"]] \
        == [(38, "CB", "A")]
    assert _reason(check_receptor, complex_raw, "pdb", H, 2, PDB_CONECT, None) == "receptor_invalid"
    assert _reason(check_receptor, complex_raw, "pdb", H, 1, {"kind": "sidecar", "sidecar_handle": H2},
                   INSTANCE, None) == "receptor_invalid"


def test_check_receptor_unsupported_list_capped_at_twenty():
    atoms = [_pdb_atom(1, "N", "GLY", "A", 1, (0, 0, 0), "N"), _pdb_atom(2, "CA", "GLY", "A", 1, (1.45, 0, 0), "C")]
    atoms += [_pdb_atom(3 + i, "O", "HOH", "W", i + 1, (10 + 3 * i, 0, 0), "O", record="HETATM") for i in range(25)]
    raw = ("\n".join(atoms + ["CONECT    1    2", "END"]) + "\n").encode()
    failure = _failure(check_receptor, raw, "pdb", H, 1, PDB_CONECT, None)
    assert failure.detail["reason_code"] == "receptor_unsupported_residue"
    assert len(failure.detail["items"]) == 20 and failure.detail["total"] == 25


def test_check_receptor_atom_cap_counts_removed_instance():
    atoms = [_pdb_atom(i + 1, "C", "LIG", "L", 1, (i * 0.01, 0, 0), "C", record="HETATM") for i in range(10_001)]
    raw = ("\n".join(atoms) + "\nEND\n").encode()
    assert _reason(check_receptor, raw, "pdb", H, 1, PDB_CONECT,
                   {**INSTANCE, "resname": "LIG"}) == "receptor_invalid"


# ---------------------------------------------------------------- isolation


def test_server_docking_modules_do_not_import_rdkit_or_meeko():
    for name in ("docking_constants.py", "docking_inputs.py"):
        tree = ast.parse((MW / name).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any(m.split(".")[0] in {"rdkit", "meeko"} for m in imported), name
        text = (MW / name).read_text()
        assert "__import__" not in text and "importlib" not in text
    code = ("import sys; import mw.docking_constants, mw.docking_inputs; "
            "print(any(m.split('.')[0] in ('rdkit', 'meeko') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"
