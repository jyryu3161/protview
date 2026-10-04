"""M21 closed sets, limits, defaults and fixed wording (spec .dryforge/spec.md 2--5).

Dependency-free on purpose (no imports beyond ``__future__``) so the admission, computation/validation, job, read and
report modules can share one copy. Changing any reason set, value range, default, limit or limitation sentence needs a
user decision (spec 10.7; handoff absolute condition 6).
"""
from __future__ import annotations

PROTOCOL = "openmm_mutation_model_v1"
TOOL = "openmm_mutation_model"
KIND = "mutation_model"
SCHEMA = "mutation_model@1"
METHOD_VERSION = "mw.mutation_model/v1"
STRUCTURE_KIND = "prepared_structure"
CANDIDATE_SET_KIND = "mutation_candidate_set"
CANDIDATE_SET_SCHEMA = "mutation_candidate_set@1"

# 2 request fields (any other key -> ``unknown_field``) and the two literal confirmations.
ARG_KEYS = ("candidate_set", "candidate_index", "seed", "selection_policy", "hydrogen_policy", "contact_cutoff_A")
SELECTION_POLICY = "protein_only"
HYDROGEN_POLICY = "rebuild_pH7"

# 2 adjustable values (both ends inclusive). The seed range is the M18 one so the same seed can be docked.
CONTACT_CUTOFF_DEFAULT_A = 4.0
CONTACT_CUTOFF_RANGE_A = (2.5, 6.0)
SEED_RANGE = (0, 2147483647)
# 2 job time (JobSubmit.timeout_s, not a job argument and not in the call key; the queue applies these).
TIMEOUT_DEFAULT_S = 120
TIMEOUT_MAX_S = 240

# 2 admission reason codes, in check order: input_invalid (HTTP 422) ...
ADMISSION_REASON_CODES = ("unknown_field", "confirmation_missing", "argument_invalid", "candidate_set_invalid",
                          "candidate_unknown", "structure_invalid", "residue_mismatch", "openmm_preflight_failed")
# ... and precondition (HTTP 412), returned before any reservation or charge.
UNAVAILABLE_REASON_CODES = ("openmm_unavailable", "pdbfixer_unavailable", "process_identity_unavailable")

# 4 closed job failure reasons (``detail.reason_code``); timeout, cancel and retry are existing job states.
FAILURE_REASON_CODES = ("mutation_modeling_failed", "unexpected_atoms_added", "coordinates_changed",
                        "topology_unsupported", "energy_invalid", "engine_failed", "resource_exceeded")
TOO_MANY_CONTACTS = "too_many_contacts"   # ``resource_exceeded`` detail ``limit``; never truncated

# 3 (8) contact rows: per structure cap, and pairs within this many bonds (final bond graph) are excluded.
MAX_CONTACT_ROWS = 2000
EXCLUDED_BOND_DISTANCE = 3

# 3 / 4 fixed method: the M7 OpenMM method record (``openmm_method.dependencies()``, every value fixed except
# ``engine_build`` and the force-field fingerprint, which is checked against ``openmm_bundle.FORCEFIELD_SHA256``)
# plus the pinned PDBFixer version.
OPENMM_VERSION = "8.6.0"
PDBFIXER_VERSION = "1.12.0"
M7_METHOD_FIXED = {
    "method_id": "openmm_protein_minimize_v1", "schema": "openmm_protein_minimization@1",
    "distribution_version": OPENMM_VERSION, "platform": "CPU", "platform_properties": {"Threads": "1"},
    "hydrogen_platform": "CPU", "hydrogen_platform_properties": {"Threads": "1"},
    "forcefield_files": ["amber14-all.xml", "implicit/gbn2.xml"], "nonbonded_method": "NoCutoff",
    "constraints": None, "pH": 7.0, "tolerance_kJ_mol_nm": 10.0, "max_iterations": 50,
    "selection_policy": SELECTION_POLICY, "hydrogen_policy": HYDROGEN_POLICY,
}
MUTATION_METHOD_FIXED = {"pdbfixer_version": PDBFIXER_VERSION}
METHOD_KEYS = (*M7_METHOD_FIXED, "engine_build", "forcefield_files_sha256", *MUTATION_METHOD_FIXED)

# 4 structure entries (same shape on both sides) and fixed labels.
STRUCTURE_SIDES = ("wild_type_reference", "mutant")
ENERGY_FIXED = {"unit": "kJ/mol", "engine": "OpenMM", "force_field": "amber14-all + implicit/gbn2",
                "convergence": "convergence_not_claimed"}
ENERGY_INCREASE_TOLERANCE_KJ_MOL = 1e-4   # after > before + this is ``energy_invalid`` (M7)
SASA_ENGINE = "FreeSASA"
SASA_PARAMETERS = {"engine_version": "2.2.1", "algorithm": "LeeRichards", "n_slices": 100, "probe_radius_A": 1.4,
                   "threads": 1, "radius_policy": "gemmi_vdw_elements_v1"}   # M6 parameters
# M7 exclusion categories (``excluded_components`` lists every category in this order, zero counts included).
EXCLUDED_CATEGORIES = ("water_removed_during_preparation", "water", "nonprotein")
# Elements an M7-admitted protein model can hold after hydrogen rebuilding.
MODEL_ELEMENTS = ("C", "N", "O", "S", "H")
HYDROGEN_ELEMENTS = ("H", "D")
# Variant names OpenMM may assign (null = the default template), as M7 ``openmm_bundle`` accepts them.
PROTONATION_VARIANTS = {"HIS": (None, "HID", "HIE", "HIP"), "CYS": (None, "CYS", "CYX")}
DISULFIDE_ATOM = "SG"

# 20 standard residue names by one-letter code (mutant residue names are standard names, spec 3.9).
THREE_LETTER = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE", "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS",
    "L": "LEU", "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG", "S": "SER", "T": "THR", "V": "VAL",
    "W": "TRP", "Y": "TYR",
}

# 4 fixed limitation sentences, verbatim (result, report and screen). The numbers are constant names only.
L1 = "변이 구조는 PDBFixer가 곁사슬을 한 가지 형태로 만든 뒤 OpenMM으로 최대 50회 최소화한 모델이며 회전이성질체 탐색과 수렴을 주장하지 않는다."
L2 = ("OpenMM 전위는 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol)이며 서열이 다른 두 구조의 값은 서로 비교할 수 없고 "
      "ΔΔG·안정성·친화도가 아니다.")
L3 = "모델은 단백질만 포함하며 리간드·금속 이온·물·보조인자는 제외했다."
L4 = "SASA는 리간드가 없는 단백질 모델의 변이 위치 잔기 값이다."
L5 = "변이한 잔기 밖에서 히스티딘·시스테인 양성자 상태가 두 구조에서 다르게 지정되었으므로 두 구조의 차이는 변이 하나만이 아니다."
L6 = "변이형에는 야생형 기준에 없는 이황화 결합이 거리 기준으로 만들어졌다."
L7 = "접촉은 중원자 사이 거리(Å)이며 수소결합이나 상호작용의 종류를 뜻하지 않는다."
LIMITATION_ORDER = (L1, L2, L3, L4, L7, L5, L6)


def applicable_limitations(*, protonation_difference_count: int, new_disulfide_in_mutant: bool) -> tuple[str, ...]:
    """The limitation sentences of one result, in the fixed order: L5 only when ``protonation_difference_count > 0``
    and L6 only when the mutant has a disulfide bond the wild-type reference lacks."""
    if type(protonation_difference_count) is not int or protonation_difference_count < 0:
        raise ValueError("protonation_difference_count must be a non-negative integer")
    if type(new_disulfide_in_mutant) is not bool:
        raise ValueError("new_disulfide_in_mutant must be a bool")
    applies = {L5: protonation_difference_count > 0, L6: new_disulfide_in_mutant}
    return tuple(sentence for sentence in LIMITATION_ORDER if applies.get(sentence, True))
