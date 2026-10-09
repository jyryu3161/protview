"""M24 T2 constants: closed sets, caps, gate pins, question wording, fixed sentences J1-J7 / U1-U3 and the reservation
formula of the JEV science egress channel (spec .dryforge/spec.md 3, 4, 5, 6, 10).

Expected sets, sentences and numbers are typed from the spec text (or, for ``property_methods``, from the T1
measurement ``docs/qa/m24-jev-20261006/preflight.txt`` (b)), never copied from the module under test. The gate pins
are compared with ``mw.egress.gate`` itself; copied M17 / M20 closed sets are compared with their originals.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from mw import jev_constants as J
from mw import ligand_bundle
from mw import ligand_constants as LC
from mw import mutation_constants as MC
from mw.egress import gate

MW = Path(__file__).resolve().parents[1] / "mw"
FIX = Path(__file__).resolve().parent / "fixtures"
NEW_MODULES = (MW / "jev_constants.py", MW / "jev_projection.py")

SPEC_J = {
    "J1": "JEV 판정은 외부 모델이 보낸 후보 목록에서 고른 하나일 뿐이며 계산 결과가 아니라 제안으로 따로 기록한 것이다. "
          "순위·추천·예측이 아니다.",
    "J2": "고른 이유는 알 수 없다. 응답에는 선택과 모델이 보고한 확신도·확률만 있으며 과학 값이 아니다.",
    "J3": "외부로 나간 내용은 승인한 미리보기 본문과 바이트가 같고(해시로 확인) 그 본문이 이 기록의 근거 전부이다.",
    "J4": "모델 선택은 후보 목록의 순서(로컬 저장 순서)의 영향을 받을 수 있다.",
    "J5": "후보는 2D 그래프이고 속성값은 RDKit 추정값이며 결합·활성·합성 가능성을 계산하지 않았고 수용체 정보 없이 고른 "
          "것이다.",
    "J6": "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 "
          "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 "
          "했고 촉매 잔기 데이터베이스는 사용하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.",
    "J7": "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다.",
}
# M26 spec 9: the J6 variants of a v2 candidate set (by the wire's catalytic_residue_database status), typed from the
# spec text; they are not members of STATEMENTS (J1-J7 stay fixed).
SPEC_J6N = ("후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 "
            "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 "
            "했고 이 집합에서는 M-CSA 촉매 잔기 주석을 전부 검사하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.")
SPEC_J6C = ("후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 "
            "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화·M-CSA 촉매 "
            "잔기 주석 기준으로만 했으며, 검사하지 않은 항목은 '없음'이 아니다.")
SPEC_U = {
    "U1": "같은 후보 목록을 다시 보내면 응답이 달라질 수 있다. 응답은 합치거나 다수결로 쓰지 않고 시간순으로 따로 보인다.",
    "U2": "과학 전송은 뷰어 모델 명령과 같은 외부 토큰·USD 예산과 '사용량 모름' 중지 상태를 쓰며, 한쪽이 예산을 다 쓰거나 "
          "사용량을 모르면 이 run에서 다른 쪽도 멈춘다.",
    "U3": "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다.",
}
# preflight.txt (b): the 8 stored M17 property_methods strings, observed in real M17 outputs.
OBSERVED_PROPERTY_METHODS = {
    "crippen_logp": "rdkit Crippen.MolLogP (Wildman-Crippen estimate)",
    "formal_charge": "rdkit GetFormalCharge (sum)",
    "hba": "rdkit CalcNumLipinskiHBA",
    "hbd": "rdkit CalcNumLipinskiHBD",
    "heavy_atoms": "rdkit GetNumHeavyAtoms",
    "mol_weight": "rdkit Descriptors.MolWt (average, Da)",
    "rotatable_bonds": "rdkit CalcNumRotatableBonds (default = Strict)",
    "tpsa": "rdkit CalcTPSA (A^2, includeSandP=False)",
}
LIGAND_NOTE = ("RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or pocket "
               "information is included")
MUTATION_NOTE = ("Distances and neighbor lists are geometry from stored coordinates, not interactions; "
                 "protection_released=false means no performed check applied, not that a residue is unimportant; "
                 "checks that are not_checked or not_available were not performed")


# ---------------------------------------------------------------- gate pins and caps


def test_gate_pins_are_the_gate_values():
    assert J.DESTINATION == gate.DESTINATION == "https://openrouter.ai/api/alpha/decisions"
    assert J.REQUEST_MODEL == gate.REQUEST_MODEL == "typesafe/jev-1.13"
    assert J.SERVED_SNAPSHOT == gate.SERVED_SNAPSHOT == "typesafe/jev-1.13-20260917"
    assert J.PROVIDER == gate.PROVIDER == {"data_collection": "deny", "zdr": True, "allow_fallbacks": False}
    assert J.MAX_RESPONSE_BYTES == gate.MAX_RESPONSE_BYTES == 65_536
    # gate.py has no named timeout constant: ``min(float(configured_timeout), 15.0, remaining)`` and viewer 15.0.
    assert J.TIMEOUT_S == 15.0 and "15.0" in (MW / "egress/gate.py").read_text()


def test_caps_match_spec():
    assert (J.MAX_CANDIDATES, J.MAX_BODY_BYTES, J.SEND_CAP, J.NEIGHBOR_RADIUS_A, J.WINDOW_FLANK) == \
        (20, 65_536, 10, 5.0, 5)
    assert type(J.NEIGHBOR_RADIUS_A) is float and type(J.WINDOW_FLANK) is int
    assert (J.MAX_OBJECT_BYTES, J.MAX_SEND_REQUEST_BYTES) == (1_048_576, 4_096)


def test_names_and_schemas_match_spec():
    assert (J.TOOL, J.TOOL_VERSION) == ("build_jev_projection", "1")
    assert J.KINDS == ("ligand", "mutation")
    assert J.SOURCE_SCHEMAS == {"ligand": "ligand_candidate_set@1", "mutation": "mutation_candidate_set@1"}
    assert J.SOURCE_STORE_KINDS == {"ligand": "ligand_candidate_set", "mutation": "mutation_candidate_set"}
    assert J.STRUCTURE_KIND == "prepared_structure"
    assert (J.LIGAND_QUESTION_ID, J.MUTATION_QUESTION_ID) == ("ligand_candidate_choice@1",
                                                              "mutation_candidate_choice@1")
    assert J.QUESTION_IDS == ("ligand_candidate_choice@1", "mutation_candidate_choice@1")
    assert J.QUESTION_FOR_KIND == {"ligand": "ligand_candidate_choice@1", "mutation": "mutation_candidate_choice@1"}
    assert (J.QUESTION_KEY, J.QUESTION_TYPE) == ("candidate_choice", "choice")
    assert J.WIRE_SCHEMAS == {"ligand": "jev_ligand_candidates@1", "mutation": "jev_mutation_candidates@1"}
    assert J.WIRE_TASK == "choose_one_candidate"
    assert (J.PROJECTION_KIND, J.PROJECTION_SCHEMA, J.PROJECTION_METHOD_VERSION) == (
        "jev_projection", "jev_projection@1", "mw.jev_projection/v1")
    assert (J.CHOICE_KIND, J.CHOICE_SCHEMA, J.CHOICE_METHOD_VERSION) == ("jev_choice", "jev_choice@1",
                                                                         "mw.jev_choice/v1")
    assert (J.SEND_SCHEMA, J.STATUS_SCHEMA, J.PREVIEW_SCHEMA) == ("jev_send@1", "jev_status@1", "jev_preview@1")
    assert J.CHOICE_LABEL == "JEV 판정(모델 선택)"
    assert (J.CONSENT_POLICY, J.CONFIRM, J.APPROVED_BY, J.AUDIT_SCOPE) == ("jev_science@1", "send_to_jev", "human",
                                                                          "science")
    assert (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME) == (
        "jev_science_consent_changed", "jev_send_approved", "jev_science_dispatch_started", "jev_send_outcome")
    assert J.ALIAS_PREFIXES == {"ligand": "c", "mutation": "m"} and J.POSITION_ALIAS_PREFIX == "p"
    assert J.CRITERION_TEMPLATE.format(alias="c01") == "Candidate c01."


def test_reason_and_status_sets_match_spec():
    assert J.PROJECTION_REASON_CODES == (
        "unknown_field", "source_invalid", "selection_invalid", "candidate_unknown", "filter_invalid",
        "candidate_filtered_out", "structure_unavailable", "wire_field_invalid", "payload_too_large")
    assert J.PROJECTION_INVALID == "projection_invalid"
    assert J.SEND_STATUSES == ("completed", "rejected", "failed") and J.IN_PROGRESS == "in_progress"
    assert J.REJECTED_REASONS == ("dry_run", "consent_off", "cancelled", "egress_stopped", "send_cap_exhausted",
                                  "budget_exhausted", "missing_configuration", "missing_credential")
    assert J.FAILED_REASONS == ("external_timeout", "transport_error", "provider_http_error", "response_invalid",
                                "missing_model", "model_mismatch", "delivery_unknown", "outcome_not_recorded")
    assert J.LATE_REASONS == ("run_cancelled", "consent_off")
    assert J.PREVIEW_BLOCK_REASONS == ("dry_run", "consent_off", "cancelled", "egress_stopped",
                                       "send_cap_exhausted", "budget_exhausted", "send_in_progress")
    assert J.SEND_CONFLICT_REASONS == ("preview_mismatch", "send_id_conflict", "send_in_progress")
    assert J.PARSE_REASONS == ("response_invalid", "missing_model", "model_mismatch")
    assert set(J.PARSE_REASONS) <= set(J.FAILED_REASONS)
    assert not set(J.REJECTED_REASONS) & set(J.FAILED_REASONS)


def test_allowed_wire_field_lists_match_spec():
    assert J.ALLOWED_BODY_KEYS == ("model", "state", "questions", "provider")
    assert J.ALLOWED_QUESTION_KEYS == ("type", "instructions", "criteria")
    assert J.ALLOWED_LIGAND_TOP == ("schema", "task", "parent", "property_methods", "candidates", "values_note")
    assert J.ALLOWED_LIGAND_PARENT == ("smiles", "properties")
    assert J.ALLOWED_LIGAND_CANDIDATE == ("alias", "smiles", "generation_kinds", "stereo_flag", "properties",
                                          "pains_matches")
    assert J.ALLOWED_PAINS_MATCH == ("catalog", "name")
    assert J.ALLOWED_MUTATION_TOP == ("schema", "task", "positions", "candidates", "protection_checks", "pockets",
                                      "values_note")
    assert J.ALLOWED_MUTATION_POSITION == ("pos", "residue", "one_letter", "sources", "ligand_min_distance_A",
                                           "protection_released", "window", "neighbors")
    assert J.ALLOWED_RESIDUE == ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode",
                                 "resname")
    assert J.ALLOWED_WINDOW == ("chain_auth", "first_seq_auth", "residues", "contiguous")
    assert J.ALLOWED_NEIGHBOR == ("chain_auth", "seq_auth", "icode", "resname")
    assert J.ALLOWED_MUTATION_CANDIDATE == ("alias", "pos", "from", "to")
    assert J.ALLOWED_POCKETS == ("ranks", "lining_residue_count")
    assert J.SELECTION_KEYS == {"ligand": ("alias", "candidate_id"),
                                "mutation": ("alias", "candidate_index", "position_index")}
    assert J.PROJECTION_KEYS == ("schema", "method_version", "kind", "source", "structure", "question", "filter",
                                 "selection", "wire", "wire_sha256", "body_sha256", "body_bytes", "limitations")
    assert J.FORBIDDEN_WIRE_KEYS == ("handle", "run_id", "path")
    assert J.GENERATION_KINDS == ("fixed_replace", "user_rule")
    assert J.SOURCE_NAMES == ("pocket", "ligand_shell", "user")
    assert J.PROTECTION_CHECK_STATUSES == ("checked", "not_checked", "not_available")
    assert J.NON_STANDARD_LETTER == "X"


def test_copied_closed_sets_equal_their_originals():
    assert J.PROPERTY_NAMES == LC.PROPERTY_NAMES
    assert J.STEREO_FLAGS == LC.STEREO_FLAGS
    assert J.PAINS_CATALOGS == ligand_bundle.PAINS_CATALOGS
    assert J.FIXED_RULE_ID == LC.FIXED_RULE_ID
    assert J.SOURCE_NAMES == MC.SOURCE_KINDS
    assert J.PROTECTION_CHECK_KEYS == MC.PROTECTION_CHECK_KEYS
    assert J.PROTECTION_CHECK_STATUSES == (MC.CHECKED, MC.NOT_CHECKED, MC.NOT_AVAILABLE)
    assert J.ALLOWED_RESIDUE == MC.IDENTITY_FIELDS
    assert J.ONE_LETTER == MC.STANDARD_ONE_LETTER and J.ONE_LETTER_CODES == MC.ONE_LETTER_ORDER
    assert J.MAPPED_RESNAMES == MC.MAPPED_RESNAMES   # window letters use the M20 one_letter name rule
    assert J.HYDROGEN_ELEMENTS == MC.HYDROGEN_ELEMENTS
    assert J.CANDIDATE_ID_RE.pattern == ligand_bundle.CANDIDATE_ID_RE.pattern


def test_property_methods_are_the_observed_stored_strings():
    assert J.PROPERTY_METHODS == OBSERVED_PROPERTY_METHODS
    assert set(J.PROPERTY_METHODS) == set(J.PROPERTY_NAMES)
    stored = json.loads((FIX / "ligand_ga/m17-candidate-set-small-pool.json").read_text())["property_methods"]
    assert stored == J.PROPERTY_METHODS


def test_wire_string_patterns():
    ident, smiles, pains = J.IDENT_RE, J.SMILES_RE, J.PAINS_NAME_RE
    for ok in ("", "A", "CC", "Axp", "a_b-9", "X" * 16):
        assert ident.fullmatch(ok)
    for bad in ("X" * 17, "A B", "A.B", "A/B", "obj://", "가", "A\n"):
        assert not ident.fullmatch(bad)
    for ok in ("C", "c1ccccc1O", "C[C@H](N)C(=O)O", "F/C=C\\F", "[NH4+].[Cl-]", "C%10CC%10", "*C", "C" * 1024):
        assert smiles.fullmatch(ok)
    for bad in ("", "C" * 1025, "C C", "C\nC", "C'C", "C{C}", "가"):
        assert not smiles.fullmatch(bad)
    for ok in ("ene_rhod_A(235)", "hzone_acyl_naphthol(22)", "a.b-c", "n" * 64):
        assert pains.fullmatch(ok)
    for bad in ("", "n" * 65, "a b", "a/b", "a:b"):
        assert not pains.fullmatch(bad)


# ---------------------------------------------------------------- notes, question wording, fixed sentences


def test_values_notes_are_the_spec_strings():
    assert J.LIGAND_VALUES_NOTE == LIGAND_NOTE and J.MUTATION_VALUES_NOTE == MUTATION_NOTE
    assert J.VALUES_NOTES == {"ligand": LIGAND_NOTE, "mutation": MUTATION_NOTE}


def test_j_and_u_sentences_verbatim():
    assert (J.J1, J.J2, J.J3, J.J4, J.J5, J.J6, J.J7) == tuple(SPEC_J.values())
    assert J.STATEMENTS == SPEC_J and list(J.STATEMENTS) == ["J1", "J2", "J3", "J4", "J5", "J6", "J7"]
    assert (J.U1, J.U2, J.U3) == tuple(SPEC_U.values())
    assert J.SCREEN_NOTES == SPEC_U and list(J.SCREEN_NOTES) == ["U1", "U2", "U3"]


def test_limitations_for_order_and_conditions():
    common = [SPEC_J["J1"], SPEC_J["J2"], SPEC_J["J3"], SPEC_J["J4"]]
    assert J.limitations_for("ligand", False) == [*common, SPEC_J["J5"]]
    assert J.limitations_for("mutation", False) == [*common, SPEC_J["J6"]]
    assert J.limitations_for("ligand", True) == [*common, SPEC_J["J5"], SPEC_J["J7"]]
    assert J.limitations_for("mutation", True) == [*common, SPEC_J["J6"], SPEC_J["J7"]]
    assert J.limitations_for("ligand", False) is not J.limitations_for("ligand", False)  # a fresh list each call
    for kind, late in (("protein", False), ("ligand", 1), ("ligand", None)):
        with pytest.raises(ValueError):
            J.limitations_for(kind, late)


def test_j6_variants_verbatim_and_outside_the_fixed_statements():
    assert (J.J6N, J.J6C) == (SPEC_J6N, SPEC_J6C)
    assert J.J6_BY_CATALYTIC_STATUS == {"not_available": SPEC_J["J6"], "not_checked": SPEC_J6N, "checked": SPEC_J6C}
    assert set(J.J6_BY_CATALYTIC_STATUS) == set(J.PROTECTION_CHECK_STATUSES)
    assert SPEC_J6N not in J.STATEMENTS.values() and SPEC_J6C not in J.STATEMENTS.values()
    assert len({SPEC_J["J6"], SPEC_J6N, SPEC_J6C}) == 3


def test_limitations_for_picks_the_j6_variant_of_the_catalytic_status():
    common = [SPEC_J["J1"], SPEC_J["J2"], SPEC_J["J3"], SPEC_J["J4"]]
    # the default and not_available (every v1 set) give the original J6 bytes
    assert J.limitations_for("mutation", False) == J.limitations_for("mutation", False, "not_available") == [
        *common, SPEC_J["J6"]]
    assert J.limitations_for("mutation", False, "not_checked") == [*common, SPEC_J6N]
    assert J.limitations_for("mutation", False, "checked") == [*common, SPEC_J6C]
    assert J.limitations_for("mutation", True, "not_checked") == [*common, SPEC_J6N, SPEC_J["J7"]]
    assert J.limitations_for("mutation", True, "checked") == [*common, SPEC_J6C, SPEC_J["J7"]]
    assert J.limitations_for("ligand", True, "not_available") == [*common, SPEC_J["J5"], SPEC_J["J7"]]
    for kind, status in (("mutation", "unknown"), ("mutation", None), ("mutation", "Checked"),
                         ("ligand", "checked"), ("ligand", "not_checked")):
        with pytest.raises(ValueError):
            J.limitations_for(kind, False, status)


def test_catalytic_status_reads_the_wire_check():
    for status in ("checked", "not_checked", "not_available"):
        wire = {"protection_checks": {"user_list": "checked", "catalytic_residue_database": status}}
        assert J.catalytic_status("mutation", wire) == status
    assert J.catalytic_status("ligand", {"schema": "jev_ligand_candidates@1"}) == "not_available"


REQUIRED_MEANING = (
    "Choose exactly one candidate", "place first in a local computation queue", "queue-order choice only",
    "not a prediction of", "binding", "activity", "affinity", "stability", "synthesizability", "safety",
    "effect of a substitution", "not measurements or interactions",
    "The order of the candidate list is the local stored order only and carries no meaning")
NO_CRITERION_OR_GOAL = ("best", "optimal", "optimiz", "improv", "promising", "rank", "score", "recommend", "goal",
                        "target", "objective", "prefer", "likely", "should", "most ", "highest", "lowest", "winner")


@pytest.mark.parametrize("question_id", ["ligand_candidate_choice@1", "mutation_candidate_choice@1"])
def test_instructions_are_ascii_and_carry_the_required_meaning(question_id):
    text = J.INSTRUCTIONS[question_id]
    assert text.isascii() and text == text.strip() and "\n" not in text
    for phrase in REQUIRED_MEANING:
        assert phrase in text, phrase
    lowered = text.lower()
    for word in NO_CRITERION_OR_GOAL:
        assert word not in lowered, word
    if question_id.startswith("ligand"):
        assert "Property values are RDKit estimates" in text and "coordinates" not in text
    else:
        assert "geometry from stored coordinates" in text and "RDKit" not in text
    assert J.instructions_sha256(question_id) == hashlib.sha256(text.encode("ascii")).hexdigest()


def test_instructions_cover_exactly_the_two_questions():
    assert set(J.INSTRUCTIONS) == set(J.QUESTION_IDS)
    assert J.INSTRUCTIONS[J.LIGAND_QUESTION_ID] != J.INSTRUCTIONS[J.MUTATION_QUESTION_ID]
    with pytest.raises(KeyError):
        J.instructions_sha256("inspection_view@1")


# ---------------------------------------------------------------- reservation


@pytest.mark.parametrize(("body_bytes", "tokens"), [
    (0, 4096), (1, 4097), (2, 4098), (3, 4098), (4, 4099), (3_539, 6_456), (29_828, 23_982), (65_535, 47_786),
    (65_536, 47_787), (68_854, 49_999), (68_855, 50_000), (68_857, 50_000), (10**9, 50_000)])
def test_reserve_tokens_formula_and_boundaries(body_bytes, tokens):
    # min(50000, 4096 + ceil(body_bytes * 2 / 3)); 3,539 B is the first real science call's body (T10 calibrate)
    assert J.reserve_tokens(body_bytes) == tokens
    assert type(J.reserve_tokens(body_bytes)) is int


def test_reserve_tokens_is_the_exact_integer_ceiling_and_never_exceeds_the_cap():
    for body_bytes in range(70_000):
        assert J.reserve_tokens(body_bytes) == min(50_000, 4096 + math.ceil(Fraction(2 * body_bytes, 3)))
    # the 64 KiB body cap reserves below the token cap, and the reservation covers 1.5 body bytes per token
    assert J.reserve_tokens(J.MAX_BODY_BYTES) < J.RESERVE_TOKEN_CAP
    assert all(J.reserve_tokens(size) - 4096 >= size / 1.5 for size in (1, 3_539, 29_828, J.MAX_BODY_BYTES))


def test_reserve_constants_and_bad_input():
    assert (J.RESERVE_TOKEN_BASE, J.RESERVE_TOKEN_CAP, J.RESERVE_USD) == (4096, 50_000, 0.10)
    for bad in (-1, 1.0, True, None, "1"):
        with pytest.raises(ValueError):
            J.reserve_tokens(bad)


# ---------------------------------------------------------------- module hygiene (AST and import graph)


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def test_constants_module_imports_only_the_standard_library():
    assert _imports(MW / "jev_constants.py") <= {"__future__", "hashlib", "re"}


def test_projection_module_imports_only_stdlib_numpy_and_its_constants():
    assert _imports(MW / "jev_projection.py") <= {"__future__", "hashlib", "itertools", "json", "math", "re",
                                                  "typing", "numpy", "gemmi", ".jev_constants"}


def test_new_modules_never_mention_the_limit_raise_names():
    # The three existing limit-raise AST tests scan every mw source text for these two names (preflight C6).
    for path in NEW_MODULES:
        text = path.read_text()
        assert "raise_limits" not in text and "limit_approval" not in text, path.name


def test_importing_the_new_modules_loads_no_network_validation_or_chemistry_package():
    code = ("import sys, mw.jev_constants, mw.jev_projection\n"
            "bad = [m for m in ('httpx', 'pydantic', 'rdkit', 'meeko', 'MDAnalysis', 'pdbfixer', 'openmm',"
            " 'mw.egress.gate', 'mw.egress', 'fastapi') if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
