"""M29 structure repair: closed sets, limits, fixed wording and names (spec .dryforge/spec.md 2-4, 6.2, 7).

Dependency-free on purpose (no imports beyond ``__future__``) so the core (``structure_repair.py``), the origin
helpers (``structure_origin.py``), the job, read and report modules and the screen copy can share one copy. Changing
any closed set, its order, a limit or a fixed sentence needs a user decision (spec 2, 3.7, 6.2, 14).

The interpretive-wording check reuses the M20 list (``mutation_reports.INTERPRETIVE``); this module defines none.
"""
from __future__ import annotations

# 4.1 tool, protocol, objects, event and report names.
TOOL = "repair_structure"
PROTOCOL = "pdbfixer_repair_v1"
KIND = "structure_repair"
SCHEMA = "structure_repair@1"
METHOD_VERSION = "mw.structure_repair/v1"
EVENT_PUBLISHED = "structure_repair_published"
EVENT_HANDLE_KEYS = ("record", "prepared_structure", "coordinates", "manifest")
PREFLIGHT_SCHEMA = "structure_repair_preflight@1"
STRUCTURE_KIND = "prepared_structure"
STRUCTURE_SCHEMA = "prepared_structure@1"
COORDINATES_KIND = "prepared_coordinates"
COORDINATES_SCHEMA = "prepared_coordinates@1"
COORDINATES_FMT = "cif"
MANIFEST_KIND = "preparation_manifest"
MANIFEST_SCHEMA = "preparation_manifest@1"
SOURCE_KIND = "structure_source"
# 3.1 the only mark of a repaired structure: ``preparation_manifest@1`` key ``repair`` = {record, source}.
MANIFEST_REPAIR_KEY = "repair"
MANIFEST_REPAIR_KEYS = ("record", "source")
MISSING_RESIDUES_LEFT = "leave_gaps"
MISSING_RESIDUES_FILLED = "modeled_internal_gaps"   # only when gaps were filled (spec 3.1)
# 7 report.
REPORT_MANIFEST_SCHEMA = "method_report_manifest@1"
REPORT_ANALYSIS_TYPE = "structure_repair"
REPORT_RENDER = "structure_repair_markdown@1"
REPORT_LIST_NAME = "구조 보완 보고서"
REPORT_STATEMENT_IDS = ("repair_scope", "added_residue_count", "added_atom_count", "side_chain_residue_count",
                        "terminal_oxt_count", "gap_count", "replaced_count", "chain_parts_merged_count",
                        "unchanged_atom_count", "collision_min_distance", "zero_occupancy_input_atom_count")
# 6.3 statement ids of the "## 구조 출처" section of downstream reports.
ORIGIN_STATEMENT_IDS = ("repair_added_residue_count", "repair_added_atom_count")

# 4.1 arguments (any other key -> ``unknown_field``) and the literal confirmation.
ARG_KEYS = ("structure", "repair_policy")
REPAIR_POLICY = "complete_missing_atoms_v1"
# 3.3 / 2.3 fixed method values (constants, never arguments).
REPAIR_SEED = 1
MAX_GAP_RESIDUES = 20
NEW_ATOM_DECIMALS = 4
# 4.1 job time: ``JobSubmit.timeout_s`` (not an argument, not in the call key).
TIMEOUT_DEFAULT_S = 120
TIMEOUT_MAX_S = 240
# 4.6 pinned engines (the server reads PDBFixer's version with ``importlib.metadata`` only).
ENGINE = "PDBFixer"
OPENMM_VERSION = "8.6.0"
PDBFIXER_VERSION = "1.12.0"
# The installed Amber14 protein template M7 reads (relative to openmm/app/data; fingerprint in openmm_bundle).
TEMPLATE_FILE = "amber14/protein.ff14SB.xml"

# 2.1 repair classes, recorded in this order.
REPAIR_CLASSES = ("chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added", "internal_gap_filled",
                  "nonstandard_replaced")
# 2.2 refusal reasons, checked in this order (the first one is the refusal; the preflight lists every blocker).
REFUSAL_REASONS = ("chain_identity_duplicate", "unsupported_residue", "unexpected_atoms", "backbone_atoms_missing",
                   "gap_listing_missing", "gap_too_long", "m7_condition_unsupported", "atom_limit_exceeded",
                   "nothing_to_repair")
REPAIR_NOT_POSSIBLE = "repair_not_possible"   # 4.2 step 4 error (class input_invalid), detail.reason_code above
# 4.2 admission, in this order: input_invalid (HTTP 422) ...
ADMISSION_REASON_CODES = ("unknown_field", "confirmation_missing", "argument_invalid", "structure_invalid",
                          "already_repaired")
# ... then precondition (HTTP 412).
UNAVAILABLE_REASON_CODES = ("process_identity_unavailable", "openmm_unavailable", "pdbfixer_unavailable")
STAGED_INPUT_LIMIT = "staged_input_bytes"   # 4.2 step 5 (429 resource_exceeded, ``limit``)
# 4.4 closed job failure reasons (``detail.reason_code``); a malformed error envelope is ``fatal``.
FAILURE_REASON_CODES = ("repair_incomplete", "repair_modeling_failed", "coordinates_changed", "unexpected_atoms_added",
                        "repair_identity_mismatch", "repair_record_mismatch", "resource_exceeded", "engine_failed")
WORKER_VERSION_INVALID = "worker_version_invalid"   # 412 when a pin changed at start
# 5.2 the default refusal of every consumer outside the modelling path.
REPAIRED_NOT_ACCEPTED = "repaired_structure_not_accepted"
REPAIRED_NOT_ACCEPTED_MESSAGE = "보완 구조는 모델링 경로에서만 쓴다"

# Limits (bytes; both refused, never truncated).
MAX_STAGED_INPUT_BYTES = 4_000_000   # 4.2 step 5
MAX_RECORD_BYTES = 4_000_000         # 3.5 the record
# 4.5 added-atom page.
ATOM_PAGE_DEFAULT = 100
ATOM_PAGE_RANGE = (1, 200)
# M7 values the analysis mirrors (a test checks them against tools/openmm_method.py).
M7_ATOM_CAP = 6000
PEPTIDE_CN_RANGE_A = (1.1, 1.7)
COORDINATE_ABS_MAX_A = 1e6

# 2.3 residue and atom rules.
STANDARD_RESIDUES = ("ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE",
                     "PRO", "SER", "THR", "TRP", "TYR", "VAL")
NONSTANDARD_REPLACEMENT = {"MSE": "MET"}               # the only replacement
REPLACED_ATOM_NAMES = {"MSE": {"SE": "SD"}}             # name map of a replaced residue
REPLACED_ATOM_ELEMENTS = {"MSE": {"SE": ("Se", "S")}}  # (from, to) element of the renamed atom
RECORD_TYPES = ("ATOM", "HETATM")
BACKBONE_ATOMS = ("N", "CA", "C", "O")
TERMINAL_OXT = "OXT"
HEAVY_ELEMENTS = ("C", "N", "O", "S")
HYDROGEN_ELEMENTS = ("H", "D")
# 3.2 / 3.5 new atoms.
ADDED_ATOM_ORIGINS = ("side_chain", "oxt", "gap_residue")
NEW_ATOM_OCCUPANCY = 1.0
NEW_ATOM_B_ISO = 0.0
CALC_FLAG_NEW = "c"
CALC_FLAG_OTHER = "."
COORDINATE_TOLERANCE_A = 1e-9   # 3.2 observed atoms

# 3.6 collision partner classes and thresholds (counted as "< threshold").
COLLISION_CLASSES = ("protein", "ligand", "metal", "water", "other")
COLLISION_THRESHOLDS_A = (2.0, 1.5)
COLLISION_KEYS = ("min_distance_A", "count_lt_2_0", "count_lt_1_5", "min_pair")

# 3.5 record keys (exactly these, in this order).
RECORD_KEYS = ("schema", "method_version", "source", "result", "parameters", "method", "classes_applied",
               "chain_parts", "chain_ends", "side_chain_repairs", "terminal_oxt", "gaps", "replaced", "added_atoms",
               "counts", "unchanged", "new_atom_rounding", "zero_occupancy_input_atoms", "collisions", "limitations")
SOURCE_KEYS = ("prepared_structure", "model_number")
RESULT_KEYS = ("coordinates", "coordinates_sha256")
PARAMETER_KEYS = ("repair_policy", "seed", "max_gap_residues", "waters", "hydrogens", "new_atom_coordinate_decimals")
METHOD_KEYS = ("engine", "pdbfixer_version", "openmm_distribution_version", "forcefield_files_sha256")
COUNT_KEYS = ("added_residues", "added_atoms", "side_chain_residues", "terminal_oxt", "gaps", "replaced",
              "chain_parts_merged", "protein_heavy_atoms")
UNCHANGED_KEYS = ("atom_count", "max_delta_A", "input_calc_flag_cleared")
ROUNDING_KEYS = ("decimals", "max_abs_delta_A")
IDENTITY_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")

# 3.7 fixed limitation sentences, verbatim, in this order, each only under its condition.
RP1 = "보완 구조의 추가 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다."
RP2 = "실험으로 관측한 원자의 좌표는 입력 그대로이며 추가·치환·원자 순서 변경만 기록했다."
RP3 = "메운 틈 구간은 단순한 기하로 놓은 가상 좌표이며 실제 구조가 아니다."
RP4 = "사슬의 관측된 끝이 서열의 끝과 다른 곳에도 말단 원자를 두었으므로 그 끝의 화학은 실제와 다를 수 있다."
RP5 = "MSE는 MET로 바꾸었고 셀레늄 원자는 황 원자로 대체했다. 원래 이름은 보완 기록에 있다."
RP6 = "같은 저자 체인 이름의 조각을 한 체인으로 합쳐 원자 순서가 바뀌었다. 잔기 식별자와 좌표는 그대로이다."
LIMITATION_ORDER = (RP1, RP2, RP3, RP4, RP5, RP6)
# 6.2 fixed sentences of downstream screens and reports.
SO1 = "이 결과의 구조는 보완 구조이다. 일부 잔기와 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다."
SO2 = "이 위치·보호 판정에는 모델링 원자 또는 잔기가 들어 있다."
SO3 = ("번호 대응·참조 주석·촉매 연결·포켓 결과는 보완 전 원본 구조에서 만든 것이며 잔기 식별자 일치로 이었다. "
       "모델링한 잔기는 검사하지 않았다.")
JW1 = "이 후보는 보완 구조 기준이며, 전송 본문은 이 사실을 담지 않는다."


def applicable_limitations(*, classes_applied: tuple[str, ...] | list[str], chain_end_differs: bool) -> tuple[str, ...]:
    """The RP sentences of one record, in the fixed order: RP1 and RP2 always, RP3 with ``internal_gap_filled``,
    RP4 when a chain's observed end was determined to differ from its sequence end, RP5 with
    ``nonstandard_replaced`` and RP6 with ``chain_parts_merged``."""
    if type(chain_end_differs) is not bool or any(name not in REPAIR_CLASSES for name in classes_applied):
        raise ValueError("invalid limitation condition")
    applies = {RP3: "internal_gap_filled" in classes_applied, RP4: chain_end_differs,
               RP5: "nonstandard_replaced" in classes_applied, RP6: "chain_parts_merged" in classes_applied}
    return tuple(sentence for sentence in LIMITATION_ORDER if applies.get(sentence, True))
