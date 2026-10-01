"""M17 closed sets, caps and fixed wording (spec .dryforge/spec.md 3--6).

Dependency-free on purpose (standard library only, no imports at all) so the
server modules, the report module and, if T3 chooses, the isolated worker can
share one copy. Changing any reason set, flag value or limitation sentence
needs a user decision (spec 5, handoff absolute condition 5).
"""
from __future__ import annotations

# 3.1 import kinds (new; ``ligand_sdf`` stays the M11 parent kind) and their input formats/extensions.
BLOCK_IMPORT_KINDS = ("building_blocks_sdf", "building_blocks_smiles")
BLOCK_INPUT_FORMATS = {"building_blocks_sdf": "sdf_multi", "building_blocks_smiles": "smiles_list"}
BLOCK_EXTENSIONS = {"building_blocks_sdf": ("sdf",), "building_blocks_smiles": ("smi", "txt")}
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_BLOCK_SDF_RECORDS = 1_000

# 3.2 / 3.3 chemistry limits used by the worker.
ALLOWED_ELEMENTS = ("H", "C", "N", "O", "S", "P", "F", "Cl", "Br", "I")
MAX_PARENT_HEAVY_ATOMS = 256
MAX_BLOCK_HEAVY_ATOMS = 64
MAX_BLOCKS = 1_000

# 6.2 parent rejection (typed inspection failure).
PARENT_REJECT_REASONS = ("unparseable", "record_count", "multiple_fragments", "element_not_allowed",
                         "too_many_atoms")
# 3.3 per-record block rejection, fixed order; ``duplicate_name`` is the separate 3.3 name rule.
BLOCK_REJECT_REASONS = ("unparseable", "empty", "multiple_fragments", "element_not_allowed", "too_many_atoms",
                        "duplicate_name")
MAX_REPORTED_BLOCK_REJECTIONS = 200

# 4.1 site pre-check.
SITE_REASONS = ("site_empty", "core_empty", "crossing_bond_count", "crossing_bond_not_single",
                "site_atom_unknown")
BOND_ORDERS = ("single", "double", "triple", "aromatic")

# 4.2 / 4.3 methods and rules.
FIXED_RULE_ID = "fixed"
FIXED_METHOD = "replace_single_bond_v1"
USER_RULE_METHOD = "user_reaction_smarts_v1"
USER_RULE_PREFIX = "user_"
MAX_RULES = 10
MAX_RULE_BYTES = 4 * 1024
RULE_VALID = "valid"
RULE_REASONS = ("reaction_parse_failed", "reactant_count", "product_count", "no_mapped_atom", "too_large",
                "duplicate_rule")

# 4.4 products.
PRODUCT_REJECT_REASONS = ("sanitize_failed", "element_not_allowed", "too_many_atoms", "equals_parent",
                          "outside_site")
STEREO_FLAGS = ("none", "parent_stereo_lost", "new_unspecified_center")
MAX_PRODUCT_HEAVY_ATOMS = 256
MAX_CANDIDATES = 2_000
MAX_ATTEMPTS = 20_000
STOP_REASONS = ("candidate_limit", "attempt_limit")

# 5 properties, filters and sorting.
PROPERTY_NAMES = ("mol_weight", "crippen_logp", "hbd", "hba", "tpsa", "rotatable_bonds", "heavy_atoms",
                  "formal_charge")
PAINS_FILTER = "pains_exclude"
SORT_KEYS = ("generation_order", *PROPERTY_NAMES)
SORT_DIRECTIONS = ("asc", "desc")

# 6.5 fixed limitation sentences, verbatim and in order.
LIMITATIONS = (
    "속성값은 RDKit 추정값이며 측정값·예측 활성이 아니다.",
    "PAINS 일치는 구조 경고일 뿐 화합물의 좋고 나쁨 판정이 아니다.",
    "후보는 2D 그래프이며 3D 배치·점수·합성 가능성은 계산하지 않았다.",
    "새로 생긴 입체 중심은 미지정이며 입체이성질체는 열거하지 않았다.",
    "수소·양성자화·토토머 상태는 입력 그대로이다.",
)
