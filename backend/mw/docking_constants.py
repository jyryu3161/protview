"""M18 closed sets, value ranges and fixed wording (spec .dryforge/spec.md 3--5).

Dependency-free on purpose (standard library only, no imports at all) so the server admission module, the
result/report modules and the isolated docking worker can share one copy. Changing any reason set, range,
enumeration or limitation sentence needs a user decision (spec 5.3, handoff absolute condition 6).
"""
from __future__ import annotations

PROTOCOL = "qvina_dock_v1"
TOOL = "qvina_dock_ligand"
ENGINE = "qvina"
RESULT_SCHEMA = "docking_result@1"

# 5.3 closed reason sets (admission and worker), in spec order.
RECEPTOR_REASONS = ("receptor_invalid", "receptor_hydrogens_missing", "receptor_unsupported_residue",
                    "receptor_altloc_present", "receptor_instance_unknown", "receptor_instance_ambiguous",
                    "receptor_instance_covalent", "receptor_prep_failed")
LIGAND_REASONS = ("ligand_unparseable", "ligand_record_count", "ligand_multiple_fragments",
                  "ligand_element_not_allowed", "ligand_too_many_atoms", "ligand_too_many_torsions", "ligand_not_3d",
                  "ligand_hydrogens_missing", "ligand_prep_failed")
CANDIDATE_REASONS = ("candidate_unknown", "parent_mismatch", "parent_not_3d", "core_match_failed",
                     "core_match_ambiguous", "embed_failed")
BOX_REASONS = ("box_invalid", "box_too_large", "box_no_receptor_atoms")
ENGINE_REASONS = ("engine_failed", "engine_output_invalid", "resource_exceeded")
REASONS = RECEPTOR_REASONS + LIGAND_REASONS + CANDIDATE_REASONS + BOX_REASONS + ENGINE_REASONS
# Server admission may also refuse with these (spec 5.3 last bullet); never produced by the worker. M21 (user
# approved, .dryforge/spec.md 7) adds ``mutation_model_invalid``: the ``receptor_source`` handle is not a published
# same-run ``mutation_model@1`` or its side is unknown.
ADMISSION_ONLY_REASONS = ("invalid_job_arguments", "mode_source_mismatch", "acknowledgement_missing",
                          "mutation_model_invalid")
# 5.5 capability reasons (no numbers, no controls when unavailable).
CAPABILITY_REASONS = ("worker_missing", "engine_missing", "engine_hash_mismatch", "handshake_failed",
                      "version_mismatch")

# 5.1 enumerations.
MODES = ("free", "core_fixed")
LIGAND_SOURCES = ("sdf", "candidate")
BOX_SOURCES = ("ligand_range", "instance_range", "manual")
CONNECTIVITY_KINDS = ("pdb_conect", "sidecar")
CONTACT_KINDS = ("polar_contact", "hydrophobic_contact", "contact")
ACKNOWLEDGEMENT_KEYS = ("keep_input_protonation", "tool_assigned_types_charges", "rigid_no_optimization")
METHODS = {"free": "qvina_free_v1", "core_fixed": "qvina_core_fixed_score_only_v1"}
# M21 optional receptor source (single M18 only; M19 refuses the key): the stored mmCIF of one side of a published
# ``mutation_model@1``, bonds from its stored OpenMM topology (``final_bonds`` + ``atom_mapping``).
RECEPTOR_SOURCE_KINDS = ("mutation_model",)
MUTATION_MODEL_SIDES = ("wild_type_reference", "mutant")
MUTATION_MODEL_CONNECTIVITY = "mutation_model_topology"

# 4.1 / 4.3 / 3.4 value ranges (inclusive) and defaults.
SEED_MIN, SEED_MAX = 0, 2147483647                      # required, no default
EXHAUSTIVENESS_MIN, EXHAUSTIVENESS_MAX, EXHAUSTIVENESS_DEFAULT = 1, 32, 8
NUM_MODES_MIN, NUM_MODES_MAX, NUM_MODES_DEFAULT = 1, 20, 9
ENERGY_RANGE_MIN, ENERGY_RANGE_MAX, ENERGY_RANGE_DEFAULT = 1, 5, 3     # kcal/mol, finite number
CONFORMERS_MIN, CONFORMERS_MAX, CONFORMERS_DEFAULT = 1, 200, 50        # core_fixed only
MARGIN_MIN_A, MARGIN_MAX_A, MARGIN_DEFAULT_A = 0, 20, 8
BOX_SIDE_MIN_A, BOX_SIDE_MAX_A = 8, 40                  # any side > 40 A is box_too_large (never shrunk)
MAX_BOX_CENTER_ABS_A = 100_000                          # same coordinate bound as M11 receptor/SDF parsing
CPU = 1

# 3.2 / 3.3 / 4.5 chemistry and contact limits.
MAX_RECEPTOR_ATOMS = 10_000                             # M11 limit, removed instance included
MAX_LISTED_RECEPTOR_ITEMS = 20                          # receptor_unsupported_residue / altloc lists
ALLOWED_LIGAND_ELEMENTS = ("H", "C", "N", "O", "S", "P", "F", "Cl", "Br", "I")   # M17 set
MAX_LIGAND_HEAVY_ATOMS = 100
MAX_ACTIVE_TORSIONS = 32                                # qvina limit, not adjustable
CONTACT_CUTOFF_A = 4.0                                  # M2 default, not adjustable in M18

# 4.1 job time limit (POST /jobs timeout_s, not a job argument, not in the call key).
TIMEOUT_DEFAULT_S = 600
TIMEOUT_MAX_S = 900

# 5.2 size limits. The result object is at most 4 MiB; a larger result fails resource_exceeded (never truncated).
MAX_RESULT_BYTES = 4 * 1024 * 1024
# Per-mode contact row cap, from T1 preflight (f) (docs/qa/m18-docking-20261002/preflight.txt): worst row 346 B,
# 200-atom pose SDF ~17,058 B, non-mode part 2,258 B. With num_modes at its maximum 20 the 4 MiB object holds
# ~554 rows per mode; 500 keeps a margin and is far above the observed maximum (80 rows per mode). More rows than
# this cap fail the job with resource_exceeded.
MAX_CONTACTS_PER_MODE = 500

# 8 / 9 fixed score wording.
SCORE_LABEL = "qvina 점수(kcal/mol, Vina 계열 스코어링 함수 값. 친화도가 아님)"
SCORE_COLUMN_LABEL = "qvina 점수(kcal/mol)"

# 5.4 fixed limitation sentences, verbatim and in order (index i is sentence i + 1).
LIMITATIONS = (
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
    # 12 (M21, user approved; only when the receptor source is a mutation model, always last)
    "수용체는 변이 모델링으로 최소화한 구조이며 리간드 자세는 이 수용체에 맞춰 조정하지 않았다(리간드 좌표는 사용자가 준 SDF 그대로).",
)


def applicable_limitations(*, mode: str, source: str, removed_instance: bool,
                           unspecified_stereo_centers: int | None,
                           receptor_source: str | None = None) -> tuple[str, ...]:
    """Limitation sentences for one result, in the fixed order (spec 5.4 conditions).

    ``unspecified_stereo_centers`` is the ``inputs.ligand`` value: null for the ``sdf`` source, a count >= 0 for
    ``candidate``. ``receptor_source`` is null for an imported receptor (sentences 1--11 only, unchanged) or
    ``mutation_model`` (M21: sentence 12 appended last; no instance is ever removed from a protein-only model).
    Impossible combinations raise ValueError instead of guessing.
    """
    if mode not in MODES or source not in LIGAND_SOURCES or type(removed_instance) is not bool:
        raise ValueError("unknown docking mode, ligand source or removed-instance flag")
    if receptor_source is not None and (receptor_source not in RECEPTOR_SOURCE_KINDS or removed_instance):
        raise ValueError("unknown receptor source, or an instance removed from a mutation-model receptor")
    if mode == "core_fixed" and source != "candidate":
        raise ValueError("core_fixed requires the candidate source")
    if unspecified_stereo_centers is not None and (type(unspecified_stereo_centers) is not int or
                                                   unspecified_stereo_centers < 0):
        raise ValueError("unspecified_stereo_centers must be null or a non-negative integer")
    applies = (True, True, True, True, True,
               mode == "free",
               source == "candidate",
               mode == "core_fixed",
               removed_instance,
               source == "candidate" and mode == "free",
               (unspecified_stereo_centers or 0) > 0,
               receptor_source == "mutation_model")
    return tuple(sentence for sentence, used in zip(LIMITATIONS, applies, strict=True) if used)
