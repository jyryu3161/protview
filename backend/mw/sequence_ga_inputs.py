"""M23 sequence GA admission, GA parameter normalization, combination space, individual keys, the RDKit-free ligand
SDF / box partial check, individual M18 arguments, pins, hashes, call key, reuse records and budget arithmetic
(spec .dryforge/spec.md 2, 3, 4, 7).

No RDKit, no Meeko, no MDAnalysis, no PDBFixer, no OpenMM, no events, no store writes. The store is only read (same
run metadata, the M20 candidate set, the ligand SDF import bytes).

Argument shape (``TOP_KEYS``; unknown keys, missing required keys, the receptor keys, ``mode``, ``contact_cutoff_A``
and ``filter`` are ``invalid_job_arguments``): ``candidate_set`` (handle), ``ligand`` (``{source: "sdf",
sdf_handle}`` only), ``box`` (M18 box), ``parameters`` (M18 free values; ``seed`` is the evaluation seed),
``selection_policy`` and ``hydrogen_policy`` (the two literals), ``acknowledgement`` (the three M18 items) and ``ga``
(every key of ``GA_KEYS``). A missing literal or acknowledgement is the step 2 reason (M21 / M18 precedent), not a
missing key. The job's ``timeout_s`` (no server default) is checked in step 1.

Admission order (spec 2 table, first failure only): 1 ``invalid_job_arguments`` (``validate_arguments`` plus the
ligand SDF handle being a same-run ``ligand_sdf`` import, the M18 rule), 2 ``confirmation_missing`` then
``acknowledgement_missing``, 3 ``candidate_set_invalid`` / ``structure_invalid`` (the M21 functions), 4 the ligand and
box partial check (``check_ligand_sdf`` in the worker's order, then the M18 box value rules, then the worker's
checks on a ligand-range box). ``admission`` runs 1-4. The caller (T5) then runs 5 (412 environment), the M7
preflight (6, ``openmm_preflight_failed``), ``after_preflight`` (6 ``residue_mismatch``, ``box_no_receptor_atoms``,
7 ``ga_space_too_small``), ``require_staged`` (8) and ``require_budget`` (9).

The server refuses only inputs the docking worker refuses with the same reason (never stricter): every SDF the
server reads with any doubt (a line RDKit may read differently, a query or unknown atom symbol, a missing ``M  END``)
skips the remaining server checks and is left to the worker (the wild-type reference row then fails). Reasons RDKit
reports before a server-detectable defect (valence and aromaticity during sanitization) cannot be seen here, so an
SDF with both kinds of defect may get a different reason from the server than from the worker (both refuse).
The manual box minimum side (8 A) and the margin range are M18 argument rules the M18 server applies before any
worker; the worker itself checks only the maximum side, finite values and the receptor atoms in the box.
"""
from __future__ import annotations

import copy
import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import docking_batch_inputs, docking_bundle, docking_inputs
from . import docking_constants as C
from . import mutation_candidates as mc
from . import mutation_model_bundle as mmb
from . import mutation_model_constants as MK
from . import mutation_model_inputs as mi
from . import mutation_model_math as mm
from . import sequence_ga_constants as SC
from .core.errors import FailureClass, ToolFailure
from .core.events import idempotency_key
from .core.handles import canonical_json
from .mutation_constants import STANDARD_ONE_LETTER

ROOT = Path(__file__).resolve().parents[2]
# Module files whose SHA-256 joins the call key, ``conditions_sha256`` and the start-time recheck. The GA worker and
# the modeling program are written in T3/T4; ``module_pins`` fails explicitly until they exist.
GA_MODULES = {"ga_worker_sha256": ROOT / "backend/mw/jobs/sequence_ga_worker.py",
              "ga_constants_sha256": ROOT / "backend/mw/sequence_ga_constants.py",
              "model_worker_sha256": ROOT / "backend/mw/jobs/sequence_model_worker.py"}
# The M21 worker and the M21 modules it depends on (``mutation_model_bundle.DEPENDENCIES``: math, constants,
# ``mutation_candidates.py``, the M7 worker and method), hashed for the same reason as the M21 call key: the modeling
# program calls their private functions (spec 4 (1)).
M21_MODULES = {"mw/jobs/openmm_mutation_worker.py": mmb.WORKER, **mmb.DEPENDENCIES}
MODULE_PIN_KEYS = (*GA_MODULES, "m21_sha256")

TOP_KEYS = frozenset({"candidate_set", "ligand", "box", "parameters", "selection_policy", "hydrogen_policy",
                      "acknowledgement", "ga"})
STEP2_KEYS = frozenset({"selection_policy", "hydrogen_policy", "acknowledgement"})
PARAMETER_KEYS = ("seed", "exhaustiveness", "num_modes", "energy_range")
AXES = docking_batch_inputs.AXES
SHA_RE = re.compile(r"[0-9a-f]{64}")
KEY_RE = re.compile(rf"(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*)){{0,{SC.MAX_MUTATIONS - 1}}}")

# RDKit-free V2000 reading (worker ``read_sdf`` order). Atomic numbers of the element symbols RDKit reads as
# elements (case-sensitive); D and T are hydrogen isotopes there. Any other symbol (queries such as R#, A, Q, *, L,
# or an unknown symbol) leaves the SDF to the worker.
_SYMBOLS = ("H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K",
            "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
            "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
            "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
            "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra",
            "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db",
            "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og")
ATOMIC_NUMBERS = {**{symbol: number for number, symbol in enumerate(_SYMBOLS, start=1)}, "D": 1, "T": 1}
ALLOWED_ATOMIC_NUMBERS = frozenset(ATOMIC_NUMBERS[symbol] for symbol in C.ALLOWED_LIGAND_ELEMENTS)
COORD_LIMIT = 100_000            # = docking_worker.COORD_LIMIT
BOX_DECIMALS = 6                 # = docking_worker.BOX_DECIMALS
_NUMBER_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_COUNT_RE = re.compile(r"[0-9]+")
HYDROGEN_ELEMENTS = ("H", "D")


def _fail(reason: str, message: str, cls: FailureClass = FailureClass.input_invalid, **detail: Any) -> ToolFailure:
    return ToolFailure(cls, message, detail={"reason_code": reason, **detail})


def _args_error(message: str) -> ToolFailure:
    return _fail("invalid_job_arguments", message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- step 1: argument shape and GA parameters (pure)
def _int_in(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def normalize_ga(value: Any) -> dict[str, Any]:
    """Spec 2 table: every key required, integers not bool, the fractions finite reals; cross rules
    ``population_size - elite_count >= 2`` and ``max_new_evaluations >= population_size``."""
    if type(value) is not dict or set(value) != set(SC.GA_KEYS):
        raise _args_error("ga needs exactly the keys " + ", ".join(SC.GA_KEYS))
    out: dict[str, Any] = {}
    for key in SC.GA_KEYS:
        low, high, _default = SC.GA_RANGES[key]
        item = value[key]
        if key in SC.GA_FLOAT_KEYS:
            if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
                raise _args_error(f"ga.{key} must be a finite number {low}-{high}")
            out[key] = float(item) + 0.0
        elif not _int_in(item, low, high):
            raise _args_error(f"ga.{key} must be an integer {low}-{high}")
        else:
            out[key] = item
    if out["population_size"] - out["elite_count"] < SC.MIN_NEW_SLOTS:
        raise _args_error("ga.population_size - ga.elite_count must be at least 2")
    if out["max_new_evaluations"] < out["population_size"]:
        raise _args_error("ga.max_new_evaluations must be at least ga.population_size")
    return out


def _timeout(timeout_s: Any, total_s: int) -> None:
    if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or
            not total_s + SC.FINISH_MARGIN_S <= timeout_s <= SC.TIMEOUT_MAX_S):
        raise _args_error(f"timeout_s must be total_s + {SC.FINISH_MARGIN_S} to {SC.TIMEOUT_MAX_S} seconds")


def _box_shape(value: Any) -> dict[str, Any]:
    """The M18 box shape (``docking_inputs._box`` keys); its values are step 4."""
    source = value.get("source") if type(value) is dict else None
    if source not in C.BOX_SOURCES:
        raise _args_error("box source must be ligand_range, instance_range or manual")
    if source == "manual" and set(value) != {"source", "center_A", "size_A"}:
        raise _args_error("manual box is {source, center_A, size_A}")
    if source != "manual" and not set(value) <= {"source", "margin_A"}:
        raise _args_error("range box is {source, margin_A}")
    return copy.deepcopy(value)


def validate_arguments(args: Any, timeout_s: Any) -> dict[str, Any]:
    """Step 1 (pure): keys, ligand shape, box shape, M18 free parameters, ``ga`` and ``timeout_s``. The returned
    arguments keep the box as given (its values are step 4) and carry the fixed literals and acknowledgement; the
    request's own literals and acknowledgement are step 2 (``check_confirmations``)."""
    if type(args) is not dict:
        raise _args_error("job arguments must be an object")
    if not set(args) <= TOP_KEYS or not TOP_KEYS - STEP2_KEYS <= set(args):
        raise _args_error("job arguments have unknown or missing keys (no receptor, mode, contact_cutoff_A or "
                          "filter keys)")
    ligand = args["ligand"]
    if type(ligand) is not dict or set(ligand) != {"source", "sdf_handle"} or ligand["source"] != "sdf":
        raise _args_error("ligand is {source: sdf, sdf_handle} (the M21 receptor-source rule: no candidate source)")
    if type(ligand["sdf_handle"]) is not str or not ligand["sdf_handle"]:
        raise _args_error("ligand.sdf_handle must be a non-empty string")
    box = _box_shape(args["box"])
    parameters = docking_inputs._parameters(args["parameters"], SC.MODE)
    ack = args.get("acknowledgement")
    if type(ack) is dict and not set(ack) <= set(C.ACKNOWLEDGEMENT_KEYS):
        raise _args_error("acknowledgement has unknown keys")
    ga = normalize_ga(args["ga"])
    _timeout(timeout_s, ga["total_s"])
    return {"candidate_set": args["candidate_set"], "ligand": {"source": "sdf", "sdf_handle": ligand["sdf_handle"]},
            "box": box, "parameters": parameters, "selection_policy": SC.SELECTION_POLICY,
            "hydrogen_policy": SC.HYDROGEN_POLICY,
            "acknowledgement": {key: True for key in C.ACKNOWLEDGEMENT_KEYS}, "ga": ga}


# ---------------------------------------------------------------- step 2: the two literals and the M18 items
def check_confirmations(args: dict[str, Any]) -> None:
    for key, literal in (("selection_policy", SC.SELECTION_POLICY), ("hydrogen_policy", SC.HYDROGEN_POLICY)):
        if type(args.get(key)) is not str or args[key] != literal:
            raise _fail("confirmation_missing", f"selection_policy must be '{SC.SELECTION_POLICY}' and "
                                                f"hydrogen_policy must be '{SC.HYDROGEN_POLICY}'")
    ack = args.get("acknowledgement")
    if type(ack) is not dict or any(ack.get(key) is not True for key in C.ACKNOWLEDGEMENT_KEYS):
        raise _fail("acknowledgement_missing", "all three acknowledgements must be true")


# ---------------------------------------------------------------- step 3: the M20 candidate set and its structure
def _meta(run: Any, handle: Any) -> dict[str, Any] | None:
    """Store metadata of an object of this run, or None (other run, unknown, malformed)."""
    if type(handle) is not str or not handle:
        return None
    try:
        return run.store.meta(handle)
    except (KeyError, ValueError, TypeError):
        return None


def candidate_set_and_structure(run: Any, handle: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """(validated candidate set content, its structure record); ``candidate_set_invalid`` / ``structure_invalid``."""
    if type(handle) is not str or not handle:
        raise _fail("candidate_set_invalid", "candidate_set must be a mutation_candidate_set handle")
    content = mi.validated_candidate_set(handle, _meta(run, handle), run.store.load)
    mi.check_structure(content, _meta(run, content["structure"]["handle"]))
    return content, dict(content["structure"])


# ---------------------------------------------------------------- combination space (spec 3)
def elementary(counts: Iterable[int], k: int) -> int:
    """The k-th elementary symmetric polynomial of ``counts`` (exact integer; e_0 = 1)."""
    values = list(counts)
    table = [1] + [0] * len(values)
    for value in values:
        for index in range(len(values), 0, -1):
            table[index] += table[index - 1] * value
    return table[k] if 0 <= k <= len(values) else 0


def space_size(counts: list[int], max_mutations: int) -> int:
    """N = sum over k = 1..M of e_k(n_1, ..., n_P) with M = min(max_mutations, P)."""
    effective = min(max_mutations, len(counts))
    return sum(elementary(counts, k) for k in range(1, effective + 1))


def candidate_space(content: dict[str, Any], max_mutations: int) -> dict[str, Any]:
    """Positions (``status == candidate`` with a candidate, storage order), their candidate indices (storage
    order), the effective cap M and N, from a validated candidate set."""
    alts: dict[int, list[int]] = {}
    for candidate in content["candidates"]:
        alts.setdefault(candidate["position_index"], []).append(candidate["index"])
    positions = [p["index"] for p in content["positions"] if p["status"] == "candidate" and alts.get(p["index"])]
    counts = [len(alts[p]) for p in positions]
    return {"positions": positions, "alts": [list(alts[p]) for p in positions],
            "effective_max_mutations": min(max_mutations, len(positions)),
            "size": space_size(counts, max_mutations)}


def space_counts(space: dict[str, Any]) -> dict[str, int]:
    """The summary / preflight ``space`` record."""
    return {"positions": len(space["positions"]), "candidates": sum(len(item) for item in space["alts"]),
            "effective_max_mutations": space["effective_max_mutations"], "size": space["size"]}


def require_space(space: dict[str, Any], population_size: int) -> None:
    """Step 7: N >= population_size (a set without candidates has N = 0)."""
    if space["size"] < population_size:
        raise _fail("ga_space_too_small", "the combination space is smaller than ga.population_size",
                    size=space["size"], population_size=population_size)


# ---------------------------------------------------------------- individual keys (spec 3)
def key_text(indices: Iterable[int]) -> str:
    return SC.KEY_SEPARATOR.join(str(index) for index in indices)


def parse_key(text: Any) -> tuple[int, ...]:
    """``"12-57-203"`` -> (12, 57, 203): decimal, no sign or leading zero, strictly ascending, 1-4 indices.
    ``wild_type`` is not an individual key (ValueError)."""
    if type(text) is not str or not KEY_RE.fullmatch(text):
        raise ValueError("an individual key is 1-4 candidate indices joined by '-'")
    indices = tuple(int(part) for part in text.split(SC.KEY_SEPARATOR))
    if list(indices) != sorted(set(indices)):
        raise ValueError("individual key indices must be strictly ascending")
    return indices


def key_mutations(content: dict[str, Any], space: dict[str, Any], key: Any) -> list[dict[str, Any]]:
    """The summary ``mutations`` of one individual key, filled from the candidate set: ``{candidate_index, residue
    (7 fields), from, to}`` in key (= position) order. Every index must be a candidate of a space position, the
    positions distinct and the size at most the effective cap (ValueError otherwise)."""
    indices = parse_key(key)
    in_space = {index: position for position, alts in zip(space["positions"], space["alts"], strict=True)
                for index in alts}
    if any(index not in in_space for index in indices):
        raise ValueError("an individual uses a candidate outside the combination space")
    positions = [in_space[index] for index in indices]
    if len(set(positions)) != len(positions) or len(indices) > space["effective_max_mutations"]:
        raise ValueError("an individual mutates one position twice or exceeds the effective max_mutations")
    rows = []
    for index in indices:
        candidate = content["candidates"][index]
        rows.append({"candidate_index": index,
                     "residue": mc.seven(content["positions"][candidate["position_index"]]["residue"]),
                     "from": candidate["from"], "to": candidate["to"]})
    return rows


# ---------------------------------------------------------------- step 4: ligand SDF partial check (no RDKit)
def split_sdf_records(text: str) -> list[str]:
    """Same split as ``docking_worker.split_sdf_records``."""
    segments, current = [], []
    for line in text.splitlines():
        if line.rstrip() == "$$$$":
            segments.append(current)
            current = []
        else:
            current.append(line)
    segments.append(current)
    return ["\n".join(lines) for lines in segments if any(line.strip() for line in lines)]


def _number(field: str) -> float | None:
    text = field.strip()
    return float(text) if _NUMBER_RE.fullmatch(text) else None


def _count(field: str) -> int | None:
    text = field.strip()
    return int(text) if _COUNT_RE.fullmatch(text) else None


def _block(lines: list[str]) -> dict[str, Any] | None:
    """The V2000 atoms and bonds read at RDKit's fixed columns, or None when any part might read differently.
    Raises ``ligand_unparseable`` only when every worker path is that reason (no atoms, a coordinate beyond
    ``COORD_LIMIT``: RDKit either fails or reads the same value)."""
    counts = lines[3]
    n_atoms, n_bonds = _count(counts[0:3]), _count(counts[3:6])
    if n_atoms is None or n_bonds is None:
        return None
    if n_atoms == 0:
        raise _fail("ligand_unparseable", "ligand SDF has no atom")
    unsure = len(counts) > 35 and counts[34:39] != "V2000"
    atoms: list[tuple[int, list[float]]] = []
    for line in lines[4:4 + n_atoms]:
        fields = [_number(line[start:start + 10]) for start in (0, 10, 20)] if len(line) >= 30 else [None] * 3
        if any(value is not None and abs(value) > COORD_LIMIT for value in fields):
            raise _fail("ligand_unparseable", "ligand coordinate out of range")
        number = ATOMIC_NUMBERS.get(line[31:34].strip()) if len(line) >= 34 else None
        if "\t" in line or number is None or any(value is None for value in fields):
            unsure = True
            continue
        atoms.append((number, [value + 0.0 for value in fields]))
    if unsure or len(atoms) != n_atoms or len(lines) < 4 + n_atoms + n_bonds:
        return None
    bonds: set[tuple[int, int]] = set()
    for line in lines[4 + n_atoms:4 + n_atoms + n_bonds]:
        first, second, kind = (_count(line[0:3]), _count(line[3:6]), _count(line[6:9])) if len(line) >= 9 else \
            (None, None, None)
        if (first is None or second is None or kind is None or not 1 <= first <= n_atoms or
                not 1 <= second <= n_atoms or first == second or kind > 8 or "\t" in line):
            return None
        pair = (min(first, second), max(first, second))
        if pair in bonds:
            return None
        bonds.add(pair)
    tail = lines[4 + n_atoms + n_bonds:]
    end = next((i for i, line in enumerate(tail) if line.rstrip() == "M  END"), None)
    if end is None or any(not line.startswith("M  ") for line in tail[:end]):
        return None
    return {"atoms": atoms, "bonds": sorted(bonds)}


def _fragments(n_atoms: int, bonds: list[tuple[int, int]]) -> int:
    parent = list(range(n_atoms))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first, second in bonds:
        parent[root(first - 1)] = root(second - 1)
    return len({root(index) for index in range(n_atoms)})


def check_ligand_sdf(raw: bytes) -> dict[str, Any]:
    """Step 4 ligand part in the worker's ``read_sdf`` order: ``ligand_unparseable`` (UTF-8), ``ligand_record_count``,
    ``ligand_unparseable`` (V2000 frame, no atom, coordinate range), then on a block read without doubt
    ``ligand_multiple_fragments``, ``ligand_element_not_allowed``, ``ligand_unparseable`` (no heavy atom),
    ``ligand_too_many_atoms`` and ``ligand_not_3d``. Returns ``{"read": bool, "heavy_points": [[x, y, z]] | None,
    "heavy_atoms": int | None}``; ``read`` false leaves the rest to the worker."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise _fail("ligand_unparseable", "ligand SDF is not UTF-8") from exc
    records = split_sdf_records(text)
    if len(records) != 1:
        raise _fail("ligand_record_count", "ligand SDF must hold exactly one record")
    lines = records[0].splitlines()
    if len(lines) < 4 or "V3000" in lines[3] or "\x00" in text:
        raise _fail("ligand_unparseable", "ligand SDF must be one V2000 record (V3000 is not accepted)")
    block = _block(lines)
    if block is None:
        return {"read": False, "heavy_points": None, "heavy_atoms": None}
    atoms = block["atoms"]
    if _fragments(len(atoms), block["bonds"]) != 1:
        raise _fail("ligand_multiple_fragments", "ligand must be one connected molecule")
    if any(number not in ALLOWED_ATOMIC_NUMBERS for number, _xyz in atoms):
        raise _fail("ligand_element_not_allowed", "ligand element outside H C N O S P F Cl Br I")
    heavy = [xyz for number, xyz in atoms if number > 1]
    if not heavy:
        raise _fail("ligand_unparseable", "ligand has no heavy atom")
    if len(heavy) > C.MAX_LIGAND_HEAVY_ATOMS:
        raise _fail("ligand_too_many_atoms", f"ligand has more than {C.MAX_LIGAND_HEAVY_ATOMS} heavy atoms")
    if len({xyz[2] for _number, xyz in atoms}) == 1:
        raise _fail("ligand_not_3d", "every ligand atom has the same z coordinate (planar input)")
    return {"read": True, "heavy_points": heavy, "heavy_atoms": len(heavy)}


# ---------------------------------------------------------------- step 4: box
def request_box(value: Any) -> dict[str, Any]:
    """The M18 box value rules on a shape-checked box (``box_invalid`` / ``box_too_large``; ``instance_range`` is
    ``box_invalid``: a protein-only model has no instance to remove)."""
    return docking_inputs._box(value, False)


def range_box(points: list[list[float]], margin: float) -> dict[str, list[float]]:
    """``docking_worker.range_box``: center = (min + max) / 2, side = (max - min) + 2 * margin, 1e-6 A rounding."""
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    return {"center_A": [round((low[k] + high[k]) / 2, BOX_DECIMALS) + 0.0 for k in range(3)],
            "size_A": [round((high[k] - low[k]) + 2 * margin, BOX_DECIMALS) + 0.0 for k in range(3)]}


def ligand_box(request: dict[str, Any], ligand: dict[str, Any]) -> dict[str, Any] | None:
    """The box the worker will use (M18 result ``box`` shape), checked as ``docking_worker.check_box`` checks it
    (``box_too_large`` then ``box_invalid``); None for a ligand-range box over an SDF the server did not read."""
    if request["source"] == "manual":
        box = {"center_A": [float(x) + 0.0 for x in request["center_A"]],
               "size_A": [float(x) + 0.0 for x in request["size_A"]], "source": "manual", "margin_A": None}
    elif ligand["heavy_points"] is None:
        return None
    else:
        margin = float(request["margin_A"]) + 0.0
        box = {**range_box(ligand["heavy_points"], margin), "source": request["source"], "margin_A": margin}
    if any(side > C.BOX_SIDE_MAX_A for side in box["size_A"]):
        raise _fail("box_too_large", f"a box side exceeds {C.BOX_SIDE_MAX_A} A (never shrunk)", size_A=box["size_A"])
    if not all(math.isfinite(x) for x in box["center_A"] + box["size_A"]) or any(s <= 0 for s in box["size_A"]):
        raise _fail("box_invalid", "box must have finite center and positive sides")
    return box


# ---------------------------------------------------------------- admission steps 1-4
def admission(run: Any, args: Any, timeout_s: Any) -> dict[str, Any]:
    """Steps 1-4 (no job, no event, no budget). Returns ``{"arguments"`` (normalized, box included), ``"candidate_set"``
    (validated content), ``"structure"``, ``"ligand"`` (``{sdf_handle, sdf_sha256}``), ``"ligand_check"``,
    ``"box"`` (the box the worker will use, or None when the server could not read the SDF), ``"space"}``."""
    normalized = validate_arguments(args, timeout_s)
    sdf_meta = docking_bundle._import_meta(run, normalized["ligand"]["sdf_handle"], "ligand_sdf")
    check_confirmations(args)
    content, structure = candidate_set_and_structure(run, normalized["candidate_set"])
    raw = run.store.load_bounded_bytes(sdf_meta["handle"], docking_bundle.MAX_INPUT_BYTES)
    if _sha(raw) != sdf_meta["summary"]["sha256"]:
        raise ValueError("ligand SDF import bytes differ from their recorded SHA-256")
    ligand = check_ligand_sdf(raw)
    normalized["box"] = request_box(normalized["box"])
    box = ligand_box(normalized["box"], ligand)
    return {"arguments": normalized, "candidate_set": content, "structure": structure,
            "ligand": {"sdf_handle": sdf_meta["handle"], "sdf_sha256": sdf_meta["summary"]["sha256"]},
            "ligand_check": ligand, "box": box,
            "space": candidate_space(content, normalized["ga"]["max_mutations"])}


# ---------------------------------------------------------------- steps 6-8 (after the M7 preflight)
def projection_atoms(projection: dict[str, Any]) -> list[dict[str, Any]]:
    return [atom for chain in projection["protein"] for residue in chain["residues"] for atom in residue["atoms"]
            if atom["element"] not in HYDROGEN_ELEMENTS]


def projection_heavy_atoms(projection: dict[str, Any]) -> int:
    return len(projection_atoms(projection))


def heavy_atom_warning(heavy_atoms: int) -> bool:
    """Spec 2: above about 4,890 projected heavy atoms the M18 10,000-atom receptor cap may refuse the reference row
    (``receptor_invalid``); a warning only, never an admission refusal."""
    return heavy_atoms > SC.M18_HEAVY_ATOM_ESTIMATE


def check_positions(content: dict[str, Any], space: dict[str, Any], projection: dict[str, Any]) -> None:
    """Step 6 ``residue_mismatch``: every space position's 7 fields resolve to exactly one projection residue whose
    standard one-letter code is the ``from`` of that position's candidates."""
    residues = [residue["residue"] for chain in projection["protein"] for residue in chain["residues"]]
    for position_index in space["positions"]:
        position = content["positions"][position_index]
        key = mc.identity(position["residue"])
        found = [residue for residue in residues if mc.identity(residue) == key]
        standard = mc.standard_name(found[0]["resname"]) if len(found) == 1 else None
        letters = {c["from"] for c in content["candidates"] if c["position_index"] == position_index}
        if standard is None or letters != {STANDARD_ONE_LETTER[standard]}:
            raise _fail("residue_mismatch", "a candidate position is not one projected residue with its 'from' "
                        "residue", residue=mc.seven(position["residue"]))


def _inside(point: list[float], box: dict[str, Any]) -> bool:
    """``docking_worker._inside``."""
    return all(box["center_A"][k] - box["size_A"][k] / 2 <= point[k] <= box["center_A"][k] + box["size_A"][k] / 2
               for k in range(3))


def check_box_receptor(box: dict[str, Any] | None, projection: dict[str, Any]) -> None:
    """Step 6 ``box_no_receptor_atoms`` against the M7 projected protein heavy atoms (skipped when the server could
    not compute a ligand-range box)."""
    if box is not None and not any(_inside(atom["coordinates_A"], box) for atom in projection_atoms(projection)):
        raise _fail("box_no_receptor_atoms", "no projected protein heavy atom lies inside the box")


def after_preflight(admitted: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
    """Step 6 (``residue_mismatch``, ``box_no_receptor_atoms``) and step 7 (``ga_space_too_small``), in order;
    returns the projected heavy-atom count and the 4,890 warning."""
    check_positions(admitted["candidate_set"], admitted["space"], projection)
    check_box_receptor(admitted["box"], projection)
    require_space(admitted["space"], admitted["arguments"]["ga"]["population_size"])
    heavy = projection_heavy_atoms(projection)
    return {"projection_heavy_atoms": heavy, "heavy_atom_warning": heavy_atom_warning(heavy)}


def require_staged(size: int) -> None:
    """Step 8: the staged worker input is at most 16 MiB (429, nothing charged)."""
    if size > SC.MAX_STAGED_BYTES:
        raise _fail("staged_input_bytes", "staged sequence GA input exceeds 16 MiB", FailureClass.resource_exceeded,
                    limit="staged_input_bytes", max_bytes=SC.MAX_STAGED_BYTES, bytes=size)


# ---------------------------------------------------------------- one individual as a standalone M18 request
def individual_arguments(normalized: dict[str, Any], model_handle: str, side: str) -> dict[str, Any]:
    """The normalized standalone M18 free request docking one model side with the GA's ligand, box and values
    (``docking_inputs.validate_arguments``; its ``input_sha256`` and call key are the M18 ones)."""
    return docking_inputs.validate_arguments({
        "receptor_source": {"kind": "mutation_model", "mutation_model": model_handle, "side": side},
        "ligand": dict(normalized["ligand"]), "mode": SC.MODE, "box": copy.deepcopy(normalized["box"]),
        "parameters": {key: normalized["parameters"][key] for key in PARAMETER_KEYS},
        "acknowledgement": dict(normalized["acknowledgement"])})


# ---------------------------------------------------------------- pins, hashes and the call key (spec 4, 7)
def module_pins() -> dict[str, Any]:
    """SHA-256 of the GA worker, the constants, the modeling program and the M21 modules. Raises FileNotFoundError
    naming the missing module (the GA worker and modeling program arrive in T3/T4)."""
    missing = [str(path) for path in (*GA_MODULES.values(), *M21_MODULES.values()) if not path.is_file()]
    if missing:
        raise FileNotFoundError("sequence GA module missing: " + ", ".join(missing))
    return {**{key: _sha(path.read_bytes()) for key, path in GA_MODULES.items()},
            "m21_sha256": {name: _sha(path.read_bytes()) for name, path in sorted(M21_MODULES.items())}}


def model_method(m21_method: dict[str, Any]) -> dict[str, Any]:
    """The modeling method record: the M21 method (``mutation_model_bundle.require_ready()["method"]``) plus the
    fixed multi-mutation method."""
    return {**m21_method, **SC.MULTI_MUTATION_METHOD}


def check_model_method(method: Any) -> None:
    """ValueError unless ``method`` is the M21 method record (``METHOD_KEYS``, fixed values) plus the fixed
    multi-mutation method."""
    keys = set(MK.METHOD_KEYS)
    if type(method) is not dict or set(method) != keys | set(SC.MULTI_MUTATION_METHOD):
        raise ValueError("model method keys")
    if any(method[key] != value for key, value in SC.MULTI_MUTATION_METHOD.items()):
        raise ValueError("multi-mutation method")
    mm._validate_method({key: method[key] for key in keys})


def check_pins(pins: Any) -> dict[str, Any]:
    """``{"modules": module_pins(), "model_method": model_method(...), "docking": docking_bundle pins}``, checked
    (ValueError otherwise)."""
    if type(pins) is not dict or set(pins) != {"modules", "model_method", "docking"}:
        raise ValueError("pins keys")
    modules = pins["modules"]
    if (type(modules) is not dict or set(modules) != set(MODULE_PIN_KEYS) or
            not all(type(modules[key]) is str and SHA_RE.fullmatch(modules[key]) for key in GA_MODULES) or
            type(modules["m21_sha256"]) is not dict or set(modules["m21_sha256"]) != set(M21_MODULES) or
            not all(type(v) is str and SHA_RE.fullmatch(v) for v in modules["m21_sha256"].values())):
        raise ValueError("module pins")
    check_model_method(pins["model_method"])
    try:
        docking_bundle._pins(pins["docking"])
    except docking_bundle.DockingEvidenceError as exc:
        raise ValueError("docking pins") from exc
    return pins


def selection_input(selected: dict[str, Any]) -> dict[str, Any]:
    """What defines one GA run (no acknowledgement, timeout, reuse, time or job identity)."""
    args = selected["arguments"]
    return {"candidate_set": args["candidate_set"],
            "structure": {"handle": selected["structure"]["handle"],
                          "model_number": selected["structure"]["model_number"]},
            "ligand": dict(selected["ligand"]), "box": args["box"], "parameters": args["parameters"],
            "selection_policy": args["selection_policy"], "hydrogen_policy": args["hydrogen_policy"],
            "ga": args["ga"]}


def selection_sha256(selected: dict[str, Any]) -> str:
    return _sha(canonical_json(selection_input(selected)))


def conditions_input(selected: dict[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    """Spec 4 reuse conditions: candidate set, structure and model number, ligand SDF hash, box, parameters, the two
    literals, the modeling and docking pins and the module hashes (no ``ga``: another GA seed reuses)."""
    args = selected["arguments"]
    return {"candidate_set": args["candidate_set"],
            "structure": {"handle": selected["structure"]["handle"],
                          "model_number": selected["structure"]["model_number"]},
            "ligand_sdf_sha256": selected["ligand"]["sdf_sha256"], "box": args["box"],
            "parameters": args["parameters"], "selection_policy": args["selection_policy"],
            "hydrogen_policy": args["hydrogen_policy"], "model_method": pins["model_method"],
            "docking": pins["docking"], "modules": pins["modules"]}


def conditions_sha256(selected: dict[str, Any], pins: dict[str, Any]) -> str:
    return _sha(canonical_json(conditions_input(selected, pins)))


def call_key(selected: dict[str, Any], pins: dict[str, Any]) -> str:
    """The GA call key: the selection hash and every pin (same request and environment = same key; the reuse set
    and the job timeout are not part of it)."""
    return idempotency_key(SC.PROTOCOL, SC.IMPLEMENTATION, {"input": selection_sha256(selected), "pins": pins})


# ---------------------------------------------------------------- reuse index (spec 4)
def reuse_record(key: str, *, model_handle: str, result_handle: str, result: dict[str, Any]) -> dict[str, Any]:
    """One reuse index fact from a validated stored model handle and docking result (state and score from the
    result's modes: the first mode's ``score_kcal_mol``, or null with zero modes)."""
    if key != SC.REFERENCE_KEY:
        parse_key(key)
    if type(model_handle) is not str or type(result_handle) is not str or not model_handle or not result_handle:
        raise ValueError("a reusable individual has a stored model and result")
    modes = result["modes"]
    if type(modes) is not list:
        raise ValueError("result modes")
    score = modes[0]["score_kcal_mol"] if modes else None
    if score is not None and (type(score) is not float or not math.isfinite(score)):
        raise ValueError("first mode score")
    return {"key": key, "state": "scored" if modes else "null_result", "reason_code": None, "score": score,
            "model_handle": model_handle, "result_handle": result_handle}


def reuse_index(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """key -> record; the first record of a key wins (records in publication order)."""
    out: dict[str, dict[str, Any]] = {}
    for record in records:
        out.setdefault(record["key"], record)
    return out


# ---------------------------------------------------------------- budget arithmetic (spec 7)
def reserved_evaluations(ga: Mapping[str, Any]) -> int:
    population, elite = ga["population_size"], ga["elite_count"]
    return min(ga["max_new_evaluations"], population + (ga["generations"] - 1) * (population - elite))


def reserved_units(ga: Mapping[str, Any]) -> int:
    """2 x (reserved_evaluations + 1): the wild-type reference row always reserves its 2 units."""
    return SC.UNITS_PER_EVALUATION * (reserved_evaluations(ga) + 1)


def needed_budget(ga: Mapping[str, Any]) -> dict[str, int]:
    units = reserved_units(ga)
    return {"expensive_calls": units,
            "wall_clock_s": min(ga["total_s"] + SC.FINISH_MARGIN_S, units * SC.SECONDS_PER_UNIT + SC.NEED_MARGIN_S)}


def full_run_may_be_partial(ga: Mapping[str, Any]) -> bool:
    return reserved_units(ga) * SC.SECONDS_PER_UNIT > ga["total_s"]


remaining = docking_batch_inputs.remaining
shortfall = docking_batch_inputs.shortfall


def limit_increase(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The M19 ``limit_increase`` formula with the M23 constants: calls = min(shortfall, need, 140); wall = 0 when not
    short, else min(shortfall, need, 15000) + 60. Zero when nothing is short (idempotent)."""
    short = shortfall(needed, snapshot)
    calls = min(short["expensive_calls"], needed["expensive_calls"], SC.MAX_RAISE_EXPENSIVE_CALLS)
    wall = min(short["wall_clock_s"], needed["wall_clock_s"], SC.MAX_RAISE_WALL_CLOCK_S)
    return {"expensive_calls": calls, "wall_clock_s": wall + SC.RAISE_MARGIN_S if wall > 0 else 0}


def require_budget(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Step 9: a short budget refuses the GA (429 ``ga_limit_raise_required``, nothing charged)."""
    short = shortfall(needed, snapshot)
    if any(value > 0 for value in short.values()):
        raise _fail("ga_limit_raise_required", "the run budget is short for this GA; raise the limits first",
                    FailureClass.resource_exceeded, needed=dict(needed), shortfall=short)


def budget_figures(ga: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The preflight budget fields (spec 7, 9)."""
    needed = needed_budget(ga)
    return {"reserved_evaluations": reserved_evaluations(ga), "reserved_units": reserved_units(ga),
            "needed": needed, "remaining": remaining(snapshot), "shortfall": shortfall(needed, snapshot),
            "full_run_may_be_partial": full_run_may_be_partial(ga)}
