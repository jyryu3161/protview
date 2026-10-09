"""M24 JEV science egress: closed sets, caps, wire field lists, question wording and fixed sentences.

Spec .dryforge/spec.md 3 (projection, wire allow lists), 4 (questions, body), 5 (consent, send records, reservation),
6 (J1-J7, U1-U3) and 10. Standard library only (``hashlib``, ``re``) so the projection, gate, read and report modules
share one copy. This module never imports ``mw.egress.gate``: the gate pins below are written out (no import cycle)
and a test checks they equal the gate's values. The M17 / M20 closed sets the wire carries are copied here on purpose
(the wire is its own contract) and a test checks they equal their originals.

Changing any closed set, cap, question wording or fixed sentence needs a user decision (spec 10, handoff absolute
condition 7). ``reserve_tokens`` and ``RESERVE_USD`` are adjustable defaults (spec 5).
"""
from __future__ import annotations

import hashlib
import re

# --- gate pins (the same values as mw.egress.gate) --------------------------------------------------------------------
DESTINATION = "https://openrouter.ai/api/alpha/decisions"
REQUEST_MODEL = "typesafe/jev-1.13"
SERVED_SNAPSHOT = "typesafe/jev-1.13-20260917"
PROVIDER = {"data_collection": "deny", "zdr": True, "allow_fallbacks": False}
MAX_RESPONSE_BYTES = 65_536
TIMEOUT_S = 15.0

# --- caps (closed; never truncated) ----------------------------------------------------------------------------------
MAX_CANDIDATES = 20
MAX_BODY_BYTES = 65_536
SEND_CAP = 10
NEIGHBOR_RADIUS_A = 5.0
WINDOW_FLANK = 5
MAX_OBJECT_BYTES = 1_048_576       # jev_projection@1 / jev_choice@1 content
MAX_SEND_REQUEST_BYTES = 4_096     # POST /runs/{id}/jev/sends body

# --- tool, objects, events -------------------------------------------------------------------------------------------
TOOL = "build_jev_projection"
TOOL_VERSION = "1"
KINDS = ("ligand", "mutation")
SOURCE_SCHEMAS = {"ligand": "ligand_candidate_set@1", "mutation": "mutation_candidate_set@1"}
SOURCE_STORE_KINDS = {"ligand": "ligand_candidate_set", "mutation": "mutation_candidate_set"}
STRUCTURE_KIND = "prepared_structure"
PROJECTION_KIND = "jev_projection"
PROJECTION_SCHEMA = "jev_projection@1"
PROJECTION_METHOD_VERSION = "mw.jev_projection/v1"
CHOICE_KIND = "jev_choice"
CHOICE_SCHEMA = "jev_choice@1"
CHOICE_METHOD_VERSION = "mw.jev_choice/v1"
SEND_SCHEMA = "jev_send@1"
STATUS_SCHEMA = "jev_status@1"
PREVIEW_SCHEMA = "jev_preview@1"
CHOICE_LABEL = "JEV 판정(모델 선택)"
CONSENT_POLICY = "jev_science@1"
CONFIRM = "send_to_jev"
APPROVED_BY = "human"
AUDIT_SCOPE = "science"
EVENT_CONSENT = "jev_science_consent_changed"
EVENT_APPROVED = "jev_send_approved"
EVENT_DISPATCH = "jev_science_dispatch_started"
EVENT_OUTCOME = "jev_send_outcome"

# --- projection admission (spec 3, in check order; first failure only) and read refusal -----------------------------
PROJECTION_REASON_CODES = (
    "unknown_field", "source_invalid", "selection_invalid", "candidate_unknown", "filter_invalid",
    "candidate_filtered_out", "structure_unavailable", "wire_field_invalid", "payload_too_large")
PROJECTION_INVALID = "projection_invalid"

# --- send records (spec 5) -------------------------------------------------------------------------------------------
SEND_STATUSES = ("completed", "rejected", "failed")
IN_PROGRESS = "in_progress"        # read-only derived state, never stored
REJECTED_REASONS = ("dry_run", "consent_off", "cancelled", "egress_stopped", "send_cap_exhausted",
                    "budget_exhausted", "missing_configuration", "missing_credential")
FAILED_REASONS = ("external_timeout", "transport_error", "provider_http_error", "response_invalid",
                  "missing_model", "model_mismatch", "delivery_unknown", "outcome_not_recorded")
LATE_REASONS = ("run_cancelled", "consent_off")
PREVIEW_BLOCK_REASONS = ("dry_run", "consent_off", "cancelled", "egress_stopped", "send_cap_exhausted",
                         "budget_exhausted", "send_in_progress")
SEND_CONFLICT_REASONS = ("preview_mismatch", "send_id_conflict", "send_in_progress")
PARSE_REASONS = ("response_invalid", "missing_model", "model_mismatch")

# --- reservation (adjustable defaults, spec 5) -----------------------------------------------------------------------
# Checked against the first real science call (M24 T10 calibrate, 2026-10-06): a 3,539-byte ligand body (5 candidates)
# was reported as 2,087 input + 65 output = 2,152 external tokens and 8.7654e-05 USD, against a reservation of 5,866
# tokens / 0.10 USD under the first formula min(40000, 4096 + ceil(body_bytes / 2)). That body gave 1.70 body bytes per
# input token, below the 2.0 the first formula assumed, so for a large body (about 45 KB and up at that ratio) it could
# reserve less than the use. The token part now assumes 1.5 bytes per token (47,787 tokens at the 64 KiB body cap).
# The USD reservation stays 0.10: the measured cost was far below it.
RESERVE_TOKEN_BASE = 4096
RESERVE_TOKEN_CAP = 50_000
RESERVE_USD = 0.10


def reserve_tokens(body_bytes: int) -> int:
    """External-token reservation for one science send: ``min(50000, 4096 + ceil(body_bytes * 2 / 3))``."""
    if type(body_bytes) is not int or body_bytes < 0:
        raise ValueError("body_bytes must be a non-negative integer")
    return min(RESERVE_TOKEN_CAP, RESERVE_TOKEN_BASE + (2 * body_bytes + 2) // 3)


# --- questions (spec 4) ----------------------------------------------------------------------------------------------
LIGAND_QUESTION_ID = "ligand_candidate_choice@1"
MUTATION_QUESTION_ID = "mutation_candidate_choice@1"
QUESTION_IDS = (LIGAND_QUESTION_ID, MUTATION_QUESTION_ID)
QUESTION_FOR_KIND = {"ligand": LIGAND_QUESTION_ID, "mutation": MUTATION_QUESTION_ID}
QUESTION_KEY = "candidate_choice"
QUESTION_TYPE = "choice"
CRITERION_TEMPLATE = "Candidate {alias}."
_CHOICE = ("Choose exactly one candidate from the list to place first in a local computation queue. "
           "This is a queue-order choice only; it is not a prediction of binding, activity, affinity, stability, "
           "synthesizability, safety or the effect of a substitution. ")
_ORDER = "The order of the candidate list is the local stored order only and carries no meaning."
INSTRUCTIONS = {
    LIGAND_QUESTION_ID: _CHOICE + "Property values are RDKit estimates, not measurements or interactions. " + _ORDER,
    MUTATION_QUESTION_ID: (_CHOICE + "Distances and neighbor lists are geometry from stored coordinates, not "
                           "measurements or interactions. " + _ORDER),
}


def instructions_sha256(question_id: str) -> str:
    """SHA-256 (hex) of the fixed instructions of ``question_id`` (``KeyError`` for any other id)."""
    return hashlib.sha256(INSTRUCTIONS[question_id].encode("ascii")).hexdigest()


# --- wire (spec 3) ---------------------------------------------------------------------------------------------------
WIRE_SCHEMAS = {"ligand": "jev_ligand_candidates@1", "mutation": "jev_mutation_candidates@1"}
WIRE_TASK = "choose_one_candidate"
ALIAS_PREFIXES = {"ligand": "c", "mutation": "m"}
POSITION_ALIAS_PREFIX = "p"
LIGAND_VALUES_NOTE = ("RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or "
                      "pocket information is included")
MUTATION_VALUES_NOTE = ("Distances and neighbor lists are geometry from stored coordinates, not interactions; "
                        "protection_released=false means no performed check applied, not that a residue is "
                        "unimportant; checks that are not_checked or not_available were not performed")
VALUES_NOTES = {"ligand": LIGAND_VALUES_NOTE, "mutation": MUTATION_VALUES_NOTE}

ALLOWED_BODY_KEYS = ("model", "state", "questions", "provider")
ALLOWED_QUESTION_KEYS = ("type", "instructions", "criteria")
ALLOWED_LIGAND_TOP = ("schema", "task", "parent", "property_methods", "candidates", "values_note")
ALLOWED_LIGAND_PARENT = ("smiles", "properties")
ALLOWED_LIGAND_CANDIDATE = ("alias", "smiles", "generation_kinds", "stereo_flag", "properties", "pains_matches")
ALLOWED_PAINS_MATCH = ("catalog", "name")
ALLOWED_MUTATION_TOP = ("schema", "task", "positions", "candidates", "protection_checks", "pockets", "values_note")
ALLOWED_MUTATION_POSITION = ("pos", "residue", "one_letter", "sources", "ligand_min_distance_A",
                             "protection_released", "window", "neighbors")
ALLOWED_RESIDUE = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
ALLOWED_WINDOW = ("chain_auth", "first_seq_auth", "residues", "contiguous")
ALLOWED_NEIGHBOR = ("chain_auth", "seq_auth", "icode", "resname")
ALLOWED_MUTATION_CANDIDATE = ("alias", "pos", "from", "to")
ALLOWED_POCKETS = ("ranks", "lining_residue_count")
FORBIDDEN_WIRE_KEYS = ("handle", "run_id", "path")

# M17 values the ligand wire carries (copies; a test checks them against ligand_constants / ligand_bundle).
PROPERTY_NAMES = ("mol_weight", "crippen_logp", "hbd", "hba", "tpsa", "rotatable_bonds", "heavy_atoms",
                  "formal_charge")
PROPERTY_METHODS = {   # the stored strings observed in real M17 outputs (T1 preflight (b)); exact comparison
    "crippen_logp": "rdkit Crippen.MolLogP (Wildman-Crippen estimate)",
    "formal_charge": "rdkit GetFormalCharge (sum)",
    "hba": "rdkit CalcNumLipinskiHBA",
    "hbd": "rdkit CalcNumLipinskiHBD",
    "heavy_atoms": "rdkit GetNumHeavyAtoms",
    "mol_weight": "rdkit Descriptors.MolWt (average, Da)",
    "rotatable_bonds": "rdkit CalcNumRotatableBonds (default = Strict)",
    "tpsa": "rdkit CalcTPSA (A^2, includeSandP=False)",
}
STEREO_FLAGS = ("none", "parent_stereo_lost", "new_unspecified_center")
PAINS_CATALOGS = ("PAINS_A", "PAINS_B", "PAINS_C")
FIXED_RULE_ID = "fixed"            # origins[].rule_id "fixed" -> fixed_replace, any other rule id -> user_rule
GENERATION_KINDS = ("fixed_replace", "user_rule")

# M20 values the mutation wire carries (copies; a test checks them against mutation_constants).
SOURCE_NAMES = ("pocket", "ligand_shell", "user")
PROTECTION_CHECK_KEYS = ("user_list", "klifs_key_sites", "metal_contact", "disulfide", "catalytic_residue_database")
PROTECTION_CHECK_STATUSES = ("checked", "not_checked", "not_available")
ONE_LETTER_CODES = "ACDEFGHIKLMNPQRSTVWY"
ONE_LETTER = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F", "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K",
    "LEU": "L", "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R", "SER": "S", "THR": "T", "VAL": "V",
    "TRP": "W", "TYR": "Y",
}
MAPPED_RESNAMES = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
                   "CYX": "CYS", "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}   # the ten M12/M20 mapped names
NON_STANDARD_LETTER = "X"          # window letter of any name outside the 20 standard and ten mapped names
HYDROGEN_ELEMENTS = ("H", "D")

# Wire string patterns (spec 3); always used with ``fullmatch`` on ``str`` values.
IDENT_RE = re.compile(r"[A-Za-z0-9_-]{0,16}")
SMILES_RE = re.compile(r"[A-Za-z0-9@+\-\[\]()=#$/\\%.:*]{1,1024}")
PAINS_NAME_RE = re.compile(r"[A-Za-z0-9_().\-]{1,64}")
CANDIDATE_ID_RE = re.compile(r"c_[0-9a-f]{16}")

# --- projection object (spec 3) --------------------------------------------------------------------------------------
PROJECTION_KEYS = ("schema", "method_version", "kind", "source", "structure", "question", "filter", "selection",
                   "wire", "wire_sha256", "body_sha256", "body_bytes", "limitations")
SELECTION_KEYS = {"ligand": ("alias", "candidate_id"), "mutation": ("alias", "candidate_index", "position_index")}

# --- fixed sentences (spec 6, verbatim, order fixed) -----------------------------------------------------------------
J1 = ("JEV 판정은 외부 모델이 보낸 후보 목록에서 고른 하나일 뿐이며 계산 결과가 아니라 제안으로 따로 기록한 것이다. "
      "순위·추천·예측이 아니다.")
J2 = "고른 이유는 알 수 없다. 응답에는 선택과 모델이 보고한 확신도·확률만 있으며 과학 값이 아니다."
J3 = "외부로 나간 내용은 승인한 미리보기 본문과 바이트가 같고(해시로 확인) 그 본문이 이 기록의 근거 전부이다."
J4 = "모델 선택은 후보 목록의 순서(로컬 저장 순서)의 영향을 받을 수 있다."
J5 = "후보는 2D 그래프이고 속성값은 RDKit 추정값이며 결합·활성·합성 가능성을 계산하지 않았고 수용체 정보 없이 고른 것이다."
J6 = ("후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 "
      "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 "
      "했고 촉매 잔기 데이터베이스는 사용하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.")
J7 = "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다."
STATEMENTS = {"J1": J1, "J2": J2, "J3": J3, "J4": J4, "J5": J5, "J6": J6, "J7": J7}
# M26 spec 9: a mutation projection's fifth sentence follows the wire's ``catalytic_residue_database`` status. J6 is
# kept byte for byte for ``not_available`` (every v1 candidate set); J6N / J6C are the v2 variants (not in STATEMENTS).
J6N = ("후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 "
       "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 "
       "했고 이 집합에서는 M-CSA 촉매 잔기 주석을 전부 검사하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.")
J6C = ("후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 "
       "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화·M-CSA 촉매 "
       "잔기 주석 기준으로만 했으며, 검사하지 않은 항목은 '없음'이 아니다.")
J6_BY_CATALYTIC_STATUS = {"not_available": J6, "not_checked": J6N, "checked": J6C}
U1 = "같은 후보 목록을 다시 보내면 응답이 달라질 수 있다. 응답은 합치거나 다수결로 쓰지 않고 시간순으로 따로 보인다."
U2 = ("과학 전송은 뷰어 모델 명령과 같은 외부 토큰·USD 예산과 '사용량 모름' 중지 상태를 쓰며, 한쪽이 예산을 다 쓰거나 "
      "사용량을 모르면 이 run에서 다른 쪽도 멈춘다.")
U3 = "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다."
SCREEN_NOTES = {"U1": U1, "U2": U2, "U3": U3}


def limitations_for(kind: str, late: bool, catalytic: str = "not_available") -> list[str]:
    """J1-J4 always, then J5 (ligand) or the J6 variant of ``catalytic`` (mutation: the wire's
    ``catalytic_residue_database`` status, see ``catalytic_status``), then J7 when ``late`` (a fresh list, order fixed).
    The default gives the original J6."""
    if kind not in KINDS or type(late) is not bool or type(catalytic) is not str \
            or catalytic not in J6_BY_CATALYTIC_STATUS or (kind == "ligand" and catalytic != "not_available"):
        raise ValueError("kind must be ligand or mutation, late a boolean and catalytic a check status "
                         "(not_available for ligand)")
    return [J1, J2, J3, J4, J5 if kind == "ligand" else J6_BY_CATALYTIC_STATUS[catalytic], *([J7] if late else [])]


def catalytic_status(kind: str, wire: dict) -> str:
    """The ``catalytic_residue_database`` status of a mutation wire's ``protection_checks``; ``not_available`` for a
    ligand wire (which has no protection checks)."""
    return wire["protection_checks"]["catalytic_residue_database"] if kind == "mutation" else "not_available"
