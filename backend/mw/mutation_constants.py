"""M20 closed sets, limits, defaults and fixed wording (spec .dryforge/spec.md 2--6, 11).

Dependency-free on purpose (no imports beyond ``__future__``) so the tool, read, report and any later module can
share one copy. Changing any reason set, status, source kind, limitation sentence or limit needs a user decision
(spec 6, 11; handoff absolute condition 7).
"""
from __future__ import annotations

TOOL = "generate_mutation_candidates"
KIND = "mutation_candidate_set"
SCHEMA = "mutation_candidate_set@1"
METHOD_VERSION = "mw.mutation_candidates/v1"
STRUCTURE_KIND = "prepared_structure"

# 2 request fields (unknown keys at these four levels -> ``unknown_field``).
ARG_KEYS = ("structure", "sources", "ligand", "allowed_residues", "protected_residues", "released_residues",
            "metal_contact_A", "numbering_map", "annotation")
SOURCES_KEYS = ("pocket", "ligand_shell", "residues")
POCKET_KEYS = ("pocket_set", "ranks")
LIGAND_SHELL_KEYS = ("radius_A",)
RESIDUE_LIST_KEYS = ("protected_residues", "released_residues")

# 2 residue reference / ligand selector: five required fields + two optional label fields (null is a value).
IDENTITY_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
REFERENCE_REQUIRED = ("model_number", "chain_auth", "seq_auth", "icode", "resname")
REFERENCE_OPTIONAL = ("chain_label", "seq_label")

# 2 admission reason codes, in check order (the handle kind/run checks of pocket_set, numbering_map and annotation
# all run before ``structure_mismatch``; see spec 2).
ADMISSION_REASON_CODES = (
    "unknown_field", "structure_invalid", "no_position_source", "argument_invalid", "allowed_residues_invalid",
    "residue_invalid", "duplicate_residue", "protect_release_conflict", "ligand_required", "ligand_invalid",
    "pocket_set_invalid", "structure_mismatch", "pocket_rank_invalid", "pocket_residue_mismatch",
    "numbering_map_invalid", "annotation_invalid", "annotation_map_mismatch",
)
TOO_MANY_POSITIONS = "too_many_positions"  # resource_exceeded (HTTP 429), never truncated

# 2 / 11 limits, defaults and ranges (both ends inclusive).
MAX_POSITIONS = 400
MAX_LIST = 400
LIGAND_SHELL_RADIUS_DEFAULT_A = 5.0
LIGAND_SHELL_RADIUS_RANGE_A = (1.0, 12.0)
METAL_CONTACT_DEFAULT_A = 3.0
METAL_CONTACT_RANGE_A = (1.0, 5.0)
DISULFIDE_SG_A = 2.5  # constant, never a request field

# 3 position sources, stored in this order on each position.
SOURCE_KINDS = ("pocket", "ligand_shell", "user")

# 4 protection reasons and exclusion reasons (closed, in this order).
PROTECTION_REASONS = ("user_protected", "klifs_key_site", "metal_contact", "disulfide_cys")
EXCLUSION_REASONS = ("non_standard_residue", "user_protected", "klifs_key_site", "metal_contact", "disulfide_cys",
                     "no_allowed_alternative")
POSITION_STATUSES = ("candidate", "excluded")
RELEASE_EFFECTS = ("released", "none")
NUMBERING_STATUSES = ("mapped", "unmapped", "conflict", "not_in_map")
NUMBERING_FIELDS = ("uniprot_accession", "uniprot_position", "uniprot_residue", "klifs_index", "klifs_label")

# 4 protection_checks (always present, these keys exactly).
PROTECTION_CHECK_KEYS = ("user_list", "klifs_key_sites", "metal_contact", "disulfide", "catalytic_residue_database")
CHECKED = "checked"
NOT_CHECKED = "not_checked"
NOT_AVAILABLE = "not_available"
KLIFS_NOT_CHECKED_REASON = "annotation_not_given"
CATALYTIC_NOT_AVAILABLE_REASON = "not_implemented"
ANNOTATED_SITE_STATUS = "annotated"

# 4 / 5 residue names: the 20 standard names with one-letter codes, and the ten M12 mapped names.
ONE_LETTER_ORDER = "ACDEFGHIKLMNPQRSTVWY"
STANDARD_ONE_LETTER = {
    "ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F", "GLY": "G", "HIS": "H", "ILE": "I", "LYS": "K",
    "LEU": "L", "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R", "SER": "S", "THR": "T", "VAL": "V",
    "TRP": "W", "TYR": "Y",
}
MAPPED_RESNAMES = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
                   "CYX": "CYS", "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}
CYSTEINE = "CYS"
SG_ATOM = "SG"
HYDROGEN_ELEMENTS = ("H", "D")

# 11 fixed limitation sentences, verbatim and in order (result, report and screen).
LIMITATIONS = (
    "후보는 위치와 바꿀 잔기의 조합 목록이며 구조 모델링·에너지·점수를 계산하지 않았다.",
    "이 목록은 변이의 효과(안정성·결합·활성)를 뜻하지 않으며 순위나 추천이 아니다.",
    ("보호 잔기는 사용자 지정·KLIFS 주요 부위·금속 근접·이황화 결합 기준으로만 판정했고 촉매 잔기 데이터베이스는 "
     "사용하지 않았다(없음)."),
    "거리는 준비된 구조의 저장 좌표에서 계산한 중원자 사이 최소 거리(Å)이며 결합이나 상호작용을 뜻하지 않는다.",
    "바꿀 히스티딘의 양성자 상태와 변이 구조의 형태는 정하지 않았다.",
)
