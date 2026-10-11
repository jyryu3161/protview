"""Branch C of the M28 end-to-end acceptance: protein engineering (.dryforge/spec.md §4.3, C1–C7; §6 live L-C6).

``run(ctx: m28_common.BranchContext) -> m28_common.BranchResult`` is the entry point the runner registers as
``BRANCH_REGISTRY["c"]`` (scripts/m28_offscreen_acceptance.py, wired in T9). The branch never imports ``mw``: the
product is reached through the real Electron offscreen harness ``frontend/tests/offscreen/endtoend-c-flow.cjs`` (every
product action a click, every approval and limit raise a person's click on the screen) and read-only loopback GETs; the
expectations are computed here from the input files and the coordinator's decisions, independently of the product.

Inputs (repository fixtures and the archived M26 set; T1 preflight (b), (d)):
  C1      public 1A30 (HIV-1 protease, chains A and B in M-CSA entry 175) and the archived M26 reaction set copied to the
          phase's isolated reaction folder (the runner copies it; ``ctx.reaction_set`` is never written). Positions are
          direct residues ARG A8, ASP A25, THR A26, ASP B25, GLY B27; the reaction knowledge result is linked twice on
          the prepared structure (chain A only, then chains A and B); ASP A25 is released in a third set.
  C2–C6   public 1UBQ (the only local public structure that passes the M7 preflight, T1 (c)); one M20 set made on the
          screen: direct residues I3 (protected), K6, I44, G76 with allowed residues A and W (6 candidates, 26
          combinations at three mutations); M21 on I44W; the labeled synthetic phenol SDF for every docking.
C1 (1A30) and C2–C6 (1UBQ) are DIFFERENT structures (no local public structure passes M7 and is in M-CSA): the scope
table states it (spec §3.2 item 1).

Fixture phase order (coordinator decision 1, budget): C1, C2, C3, C5, C6 (explore round, then exploit round), C4
(setting 1, setting 2), C7. Units no raise can cover: M7 1 + M21 1 + C3 pair 2 + C6 4 = 8 of the default 8 (no margin);
then two raises by a person's click (C4 setting 1 +22, setting 2 +14). The harness checks before every computation that
the remaining units cover its need and after it the units it used.

Live phase (decision 9, spec §6): a new run rebuilds L-pre-C2 (M7 1 + M21 1) with the same part code, then ONE explore
round of the protein loop (L-C6: model + docking, 2 units): 4 units, no raise. The send is clicked only when
``ctx.send_allowed`` and the dispatch events of the runs folder are below the limit given to the harness (one send);
with ``ctx.rehearse`` the backend is the fixture server (no call). Result: ``live['L-C6']`` ∈ completed |
provider_failed | product_failed (spec §6.3), or not_sent with its closed cause.

Independent expectations (standard library only, nothing read from the product): the input files' SHA-256; the 1A30
polymer residues and the archived set's ``mcsa/entries.jsonl`` rows naming 1A30 (per chain coverage, row states and,
per position residue, the matched M-CSA rows that protect it); the ``catalytic_annotation.checked`` rule (true only
when every chain holding a position is covered by the chosen result); the 1UBQ residue names at the chosen positions,
its protein heavy atoms and waters (the M7 preflight of the keep_all preparation); the candidate list and the
combination space of the M20 set; the loop pools; the two GA settings checked against the ranges read from
``backend/mw/sequence_ga_constants.py`` as text (``ast``, no import) with their spec 7 numbers; the unit plan.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# mmCIF residues, the M-CSA row states and the reaction-set copy check of branch A (standard library only).
import m28_branch_a as a

# SDF record reading of branch B.
import m28_branch_b as b
import m28_common as c

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path("backend/tests/fixtures")
HARNESS = "endtoend-c-flow.cjs"
STEPS = {"fixture": "c-endtoend", "live": "c-live"}
PLAN_SCHEMA = "m28_branch_c_plan@1"
EVIDENCE_FILE = "endtoend-c-evidence.json"
SEQ_GA_CONSTANTS = Path("backend/mw/sequence_ga_constants.py")
CASES = ("C1", "C2", "C3", "C4", "C5", "C6", "C7")
LIVE_PARTS = ("L-pre-C2", "L-C6")
# Decision 1: the order the harness runs the parts in (the spec case IDs stay fixed).
FIXTURE_ORDER = ("C1", "C2", "C3", "C5", "C6", "C4", "C7")
# What a part needs from earlier parts (m28_common.PREREQUISITES plus the live parts' chain).
PART_NEEDS = {"C1": (), "C2": (), "C3": ("C2",), "C5": ("C2",), "C6": ("C2",), "C4": ("C2",), "C7": (),
              "L-pre-C2": (), "L-C6": ("L-pre-C2",)}

INPUTS = {
    "a30": ("public_1a30.cif", "public PDB entry 1A30 (RCSB CC0, M26 T9a download; HIV-1 protease, M-CSA entry 175)",
            False),
    "ubq": ("public_1ubq.cif", "public PDB entry 1UBQ (repository fixture; SHA-256 recorded in docs/M7_OPENMM.md)",
            False),
    "phenol": ("mutation_model/synthetic-phenol-ligand.sdf", ("SYNTHETIC-FIXTURE hand-built phenol "
                                                               "(mutation_model/SYNTHETIC-PROVENANCE.md); a mechanical "
                                                               "path check, not a biological pose"), True),
}
STANDARD20 = {"ALA": "A", "CYS": "C", "ASP": "D", "GLU": "E", "PHE": "F", "GLY": "G", "HIS": "H", "ILE": "I",
              "LYS": "K", "LEU": "L", "MET": "M", "ASN": "N", "PRO": "P", "GLN": "Q", "ARG": "R", "SER": "S",
              "THR": "T", "VAL": "V", "TRP": "W", "TYR": "Y"}
# Decision 2: C1 = 1A30, direct residues (the M26 real-mutation inputs), results chain A only / chains A and B.
C1 = {"pdbId": "1A30", "chainsPartial": ["A"], "chainsAll": ["A", "B"],
      "residues": [{"resname": "ARG", "chain": "A", "seq": 8}, {"resname": "ASP", "chain": "A", "seq": 25},
                   {"resname": "THR", "chain": "A", "seq": 26}, {"resname": "ASP", "chain": "B", "seq": 25},
                   {"resname": "GLY", "chain": "B", "seq": 27}],
      "release": {"resname": "ASP", "chain": "A", "seq": 25}}
REPORT_V2 = "mutation_candidates_markdown@2"
REPORT_V1 = "mutation_candidates_markdown@1"
# Decision 4: the 1UBQ tiny set (sequence-ga-flow m20Create), keep_all water for the M7 run (openmm-flow pattern).
C2 = {"waters": "keep_all", "residues": [["ILE", 3], ["LYS", 6], ["ILE", 44], ["GLY", 76]], "protect": [["ILE", 3]],
      "allowed": ["A", "W"], "model": {"residue": ["ILE", 44], "to": "W", "seed": "20261004", "cutoff": "4.0",
                                       "timeout": "240"}}
MAX_MUTATIONS = 3
# One docking setting for every docking of the branch (C3 pairs, C4 individuals, C6 loop rounds): the M23 T1 values.
DOCKING = {"margin": "8", "seed": "20261004", "exhaustiveness": "4", "numModes": "5", "energyRange": "3"}
# The loop pools leave out the M21 target (already modelled in C2) and Gly / Pro / Cys positions (the M25 qa_setup
# NOT_MODELLED_HERE choice of the harness; not a product limit), so every round computes a model and a docking.
LOOP_POOL_EXCLUDED_RESNAMES = ("GLY", "PRO", "CYS")
# Decision 7: two GA settings (seed fixed; population, generations, elite, random fraction and the cap differ).
GA_SETTING_1 = {"seed": 21, "population_size": 4, "generations": 3, "elite_count": 1, "tournament_size": 2,
                "crossover_fraction": 0.5, "random_fraction": 0.25, "max_mutations": 3, "patience": 3,
                "max_new_evaluations": 10, "total_s": 600}
GA_SETTING_2 = {**GA_SETTING_1, "population_size": 6, "generations": 2, "elite_count": 2, "random_fraction": 0.5,
                "max_new_evaluations": 6}
# Decision 8: one round each (iteration cap 1); the fixture reply scripts are the good ones only.
LOOPS = {"explore": {"goal": "explore", "seed": "31", "cap": "1", "script": "good"},
         "exploit": {"goal": "exploit", "seed": "37", "cap": "1", "script": "good_second"}}
SEND_SCRIPT = "good"                            # C5 (M24 mutation candidates)
SEND_PICK = 3                                   # C5: the first three candidates of the set
DEFAULT_UNITS = 8
UNIT_PLAN = {
    "fixture": {"C2-m7": 1, "C2-m21": 1, "C3-pair": 2, "C6-explore": 2, "C6-exploit": 2, "C4-1": 22, "C4-2": 14},
    "live": {"C2-m7": 1, "C2-m21": 1, "C6-explore": 2},
}
RAISES = {"fixture": {"C4-1": 22, "C4-2": 14}, "live": {}}
# Spec §6.3 classes of a send that did not complete (the reason codes of mw.jev_constants, by name).
PROVIDER_FAILURES = ("external_timeout", "transport_error", "provider_http_error", "delivery_unknown")


# ---------------------------------------------------------------------------------------------------- inputs
def file_record(code: Path, rel: str, label: str, synthetic: bool) -> dict[str, Any]:
    path = code / FIXTURES / rel
    raw = path.read_bytes()
    return {"path": str(path), "name": path.name, "rel": rel, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "provenance": label, "syntheticLabeled": synthetic}


def residue_text(residue: dict[str, Any]) -> str:
    """``RESNAME CHAIN:SEQ`` (the M20 screen's residue key without an insertion code)."""
    return f"{residue['resname']} {residue['chain']}:{residue['seq']}"


# ---------------------------------------------------------------------------------------------------- C1 (M-CSA)
def mcsa_groups(entries: list[dict[str, Any]], pdb_id: str, chain: str) -> list[dict[str, Any]]:
    """The M-CSA rows of one (PDB ID ignoring case, chain) grouped by (mcsa_id, residue index, author number), with
    the codes and whether any member is the entry's reference (the business-rule grouping, written here)."""
    pdb = pdb_id.lower()
    groups: dict[tuple, dict[str, Any]] = {}
    for entry in entries:
        for index, residue in enumerate(entry["residues"]):
            for member in residue["residue_chains"]:
                if member["pdb_id"].lower() != pdb or member["chain_name"] != chain:
                    continue
                group = groups.setdefault((entry["mcsa_id"], index, member["auth_resid"]), {
                    "mcsa_id": entry["mcsa_id"], "residue_index": index, "auth": member["auth_resid"], "codes": set(),
                    "is_reference": False})
                group["codes"].add(member["code"])
                group["is_reference"] = group["is_reference"] or member["is_reference"] is True
    return sorted(groups.values(), key=lambda g: (g["mcsa_id"], g["residue_index"], g["auth"] is None, g["auth"] or 0))


def checked_expectation(position_chains: Iterable[str], annotation_chains: Iterable[str],
                        coverage: dict[str, str]) -> dict[str, Any]:
    """The M20 v2 catalytic check of a set (business rules, M26 → M20 v2): ``checked`` only when every chain holding a
    position is covered by the chosen result; a chain the result does not name is ``not_in_annotation``; otherwise
    ``not_checked`` with ``chains_not_covered``."""
    chains = sorted(set(position_chains))
    named = set(annotation_chains)
    covered = [chain for chain in chains if chain in named and coverage.get(chain) == "covered"]
    uncovered = [{"chain_auth": chain, "coverage": "not_in_annotation" if chain not in named else coverage.get(chain)}
                 for chain in chains if chain not in covered]
    status = "checked" if chains and not uncovered else "not_checked"
    return {"status": status, "reason": None if status == "checked" else "chains_not_covered", "covered": covered,
            "uncovered": uncovered}


def c1_expectation(reaction_set_dir: Path, structure: Path, spec: dict[str, Any] = C1) -> dict[str, Any]:
    """C1 expectations from the archived set's ``mcsa/entries.jsonl`` and the 1A30 file alone: per chain coverage and
    row counts, per position the matched rows that protect it (only on covered chains), the checked state of the
    two results, the protected positions and the released residue; the set hash the report table must name."""
    set_hash = reaction_set_dir.name
    entries = a.read_jsonl(reaction_set_dir / "files" / "mcsa" / "entries.jsonl")
    polymer = a.polymer_chains(structure)
    for item in spec["residues"]:
        found = [r for r in polymer.get(item["chain"], []) if r["seq_auth"] == item["seq"]]
        if len(found) != 1 or found[0]["resname"] != item["resname"] or found[0]["icode"]:
            raise ValueError(f"{residue_text(item)} is not one residue of the structure")
    chains = sorted({item["chain"] for item in spec["residues"]})
    mcsa = a.mcsa_expectation(entries, spec["pdbId"], {chain: polymer[chain] for chain in chains})
    coverage = {chain: value["coverage"] for chain, value in mcsa["chains"].items()}
    states = {chain: value.get("rows") or {} for chain, value in mcsa["chains"].items()}
    catalytic: dict[str, list[list[Any]]] = {}
    for item in spec["residues"]:
        rows = []
        for group in mcsa_groups(entries, spec["pdbId"], item["chain"]):
            key = f"{group['mcsa_id']}/{group['residue_index']}"
            if group["auth"] == item["seq"] and states[item["chain"]].get(key) == "matched":
                rows.append([group["mcsa_id"], group["residue_index"], group["is_reference"]])
        catalytic[residue_text(item)] = rows

    def result(annotation_chains: list[str]) -> dict[str, Any]:
        state = checked_expectation(chains, annotation_chains, coverage)
        counts = {f"{status}_rows": sum((mcsa["chains"][chain]["counts"] or {}).get(status, 0)
                                        for chain in state["covered"]) for status in ("matched", "conflict",
                                                                                      "unmatched")}
        protected = sorted(key for key, rows in catalytic.items()
                           if rows and key.split()[1].split(":")[0] in state["covered"])
        return {**state, "counts": counts, "protected": protected}
    release = residue_text(spec["release"])
    return {"setHash": set_hash, "pdbId": spec["pdbId"], "positionChains": chains, "coverage": coverage,
            "rowCounts": {chain: value["counts"] for chain, value in mcsa["chains"].items()},
            "catalytic": catalytic, "partial": result(spec["chainsPartial"]), "all": result(spec["chainsAll"]),
            "release": {"residue": release, "catalytic": catalytic[release]}, "reportRender": REPORT_V2}


# ---------------------------------------------------------------------------------------------------- C2 (1UBQ)
def ubq_expectation(structure: Path, spec: dict[str, Any] = C2) -> dict[str, Any]:
    """The 1UBQ facts of the M7 preflight (keep_all: protein heavy atoms, excluded waters) and of the M20 set (the
    residue at every chosen position, the candidates: each unprotected position × each allowed residue other than its
    own), from the mmCIF file alone."""
    atoms = a.atom_records(structure)
    residues = a.group_residues(atoms)
    waters = sum(1 for item in residues if item["residue"]["resname"] in a.WATER_NAMES)
    heavy = sum(1 for atom in atoms if atom["element"] not in a.HYDROGENS and atom["entity_type"] == "polymer")
    chain = a.polymer_chains(structure)["A"]
    names = {}
    for resname, seq in spec["residues"]:
        found = [r for r in chain if r["seq_auth"] == seq]
        if len(found) != 1 or found[0]["resname"] != resname:
            raise ValueError(f"{resname} A:{seq} is not one residue of the structure")
        names[seq] = resname
    protected = {seq for _name, seq in spec["protect"]}
    candidates = []
    for resname, seq in spec["residues"]:
        if seq in protected:
            continue
        for code in spec["allowed"]:
            if STANDARD20[resname] != code:
                candidates.append({"residue": f"{resname} A:{seq}", "resname": resname, "seq": seq,
                                   "from": STANDARD20[resname], "to": code})
    counts = [sum(1 for item in candidates if item["seq"] == seq) for _name, seq in spec["residues"] if
              seq not in protected]
    model = spec["model"]
    target = f"{model['residue'][0]} A:{model['residue'][1]}"
    pool = [f"{item['residue']} {item['from']}→{item['to']}" for item in candidates
            if item["resname"] not in LOOP_POOL_EXCLUDED_RESNAMES
            and not (item["residue"] == target and item["to"] == model["to"])]
    return {"proteinHeavyAtoms": heavy, "waters": waters, "residueNames": names, "positions": len(spec["residues"]),
            "candidatePositions": len(counts), "candidates": candidates, "candidateCount": len(candidates),
            "space": {"positions": len(counts), "candidates": len(candidates),
                      "effective_max_mutations": min(MAX_MUTATIONS, len(counts)),
                      "size": space_size(counts, MAX_MUTATIONS)},
            "modelTarget": {"residue": target, "from": STANDARD20[model["residue"][0]], "to": model["to"]},
            "loopPool": pool}


def space_size(counts: Iterable[int], max_mutations: int) -> int:
    """N = Σ_{k=1..M} e_k(counts): the elementary symmetric polynomials of the per-position candidate counts (the
    combinations of one candidate at each of up to M distinct positions)."""
    values = list(counts)
    e = [1] + [0] * len(values)
    for n in values:
        for k in range(len(values), 0, -1):
            e[k] += e[k - 1] * n
    return sum(e[k] for k in range(1, min(max_mutations, len(values)) + 1))


# ---------------------------------------------------------------------------------------------------- GA settings
def ga_ranges(code: Path = REPO) -> dict[str, Any]:
    """``GA_RANGES``, ``MIN_NEW_SLOTS``, ``UNITS_PER_EVALUATION``, ``SECONDS_PER_UNIT``, ``NEED_MARGIN_S`` and
    ``FINISH_MARGIN_S`` read from the product constants file as literals (``ast``; never imported or executed)."""
    tree = ast.parse((code / SEQ_GA_CONSTANTS).read_text(encoding="utf-8"))
    wanted = {"GA_RANGES", "MIN_NEW_SLOTS", "UNITS_PER_EVALUATION", "SECONDS_PER_UNIT", "NEED_MARGIN_S",
              "FINISH_MARGIN_S"}
    found: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in wanted:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    missing = wanted - set(found)
    if missing:
        raise ValueError(f"{SEQ_GA_CONSTANTS}: {sorted(missing)} not found as literals")
    return found


def ga_problems(setting: dict[str, Any], constants: dict[str, Any], space: int | None = None) -> list[str]:
    """Why a GA setting is outside the product ranges or cross rules (empty = inside)."""
    problems = []
    ranges = constants["GA_RANGES"]
    if set(setting) != set(ranges):
        problems.append(f"keys {sorted(set(setting) ^ set(ranges))}")
    for key, (low, high, _default) in ranges.items():
        value = setting.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
            problems.append(f"{key}={value!r} outside {low}..{high}")
    if setting.get("population_size", 0) - setting.get("elite_count", 0) < constants["MIN_NEW_SLOTS"]:
        problems.append("population_size - elite_count below MIN_NEW_SLOTS")
    if setting.get("max_new_evaluations", 0) < setting.get("population_size", 0):
        problems.append("max_new_evaluations below population_size")
    if space is not None and space < setting.get("population_size", 0):
        problems.append("combination space below population_size")
    return problems


def ga_need(setting: dict[str, Any], constants: dict[str, Any]) -> dict[str, Any]:
    """Spec 7: reserved_evaluations = min(max_new, P + (G-1)(P-E)); reserved_units = 2 × (reserved_evaluations + 1);
    needed wall = min(total_s + finish margin, units × seconds per unit + need margin); partial when units × seconds
    per unit > total_s."""
    p, g, e = setting["population_size"], setting["generations"], setting["elite_count"]
    reserved = min(setting["max_new_evaluations"], p + (g - 1) * (p - e))
    units = constants["UNITS_PER_EVALUATION"] * (reserved + 1)
    wall = min(setting["total_s"] + constants["FINISH_MARGIN_S"], units * constants["SECONDS_PER_UNIT"]
               + constants["NEED_MARGIN_S"])
    return {"reservedEvaluations": reserved, "reserved": units, "neededWall": wall,
            "mayBePartial": units * constants["SECONDS_PER_UNIT"] > setting["total_s"]}


def settings_differ(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    """Spec §3.1: of population size, generations, seed and random fraction at least two differ."""
    return [key for key in ("population_size", "generations", "seed", "random_fraction") if first[key] != second[key]]


# ---------------------------------------------------------------------------------------------------- plan
def unit_plan(phase: str) -> dict[str, Any]:
    """The planned units per computation, the raise a person clicks before it (the shortfall) and the remaining units
    before that raise (default limit 8); a raised computation leaves exactly 0."""
    used = 0
    raised = 0
    before = {}
    for label, units in UNIT_PLAN[phase].items():
        before[label] = DEFAULT_UNITS + raised - used
        raise_by = RAISES[phase].get(label, 0)
        if raise_by and before[label] + raise_by != units:
            raise ValueError(f"{label}: a raise of {raise_by} does not cover exactly {units} units")
        if before[label] + raise_by < units:
            raise ValueError(f"{label}: {units} units planned with {before[label]} remaining and no raise")
        raised += raise_by
        used += units
    return {"units": dict(UNIT_PLAN[phase]), "raises": dict(RAISES[phase]), "remainingBefore": before,
            "totalUsed": used, "finalLimit": DEFAULT_UNITS + raised, "finalRemaining": DEFAULT_UNITS + raised - used}


def build_plan(code: Path, phase: str, reaction_set_dir: Path | None, *, send_allowed: bool = True,
               dispatch_limit: int = 0) -> dict[str, Any]:
    """Everything the harness needs: inputs (path, SHA-256, provenance, synthetic label), the C1 expectations from
    the reaction set copy (fixture phase only; None without a set), the 1UBQ facts, the docking values, the GA
    settings checked against the product ranges with their spec 7 numbers, the loops, the unit plan and (live) the
    send guard."""
    if phase not in STEPS:
        raise ValueError(f"unknown phase {phase!r}")
    inputs = {key: file_record(code, rel, label, synthetic) for key, (rel, label, synthetic) in INPUTS.items()}
    base = code / FIXTURES
    phenol = b.sdf_records(base / INPUTS["phenol"][0])
    if len(phenol) != 1 or not phenol[0]["atoms"] or all(atom["xyz"][2] == 0 for atom in phenol[0]["atoms"]):
        raise ValueError("the phenol SDF is not one 3D V2000 record")
    ubq = ubq_expectation(base / INPUTS["ubq"][0])
    constants = ga_ranges(code)
    settings = {"1": dict(GA_SETTING_1), "2": dict(GA_SETTING_2)}
    problems = {key: ga_problems(value, constants, ubq["space"]["size"]) for key, value in settings.items()}
    if any(problems.values()):
        raise ValueError(f"GA settings outside the product ranges: {problems}")
    differ = settings_differ(GA_SETTING_1, GA_SETTING_2)
    if len(differ) < 2:
        raise ValueError(f"the two GA settings differ in {differ} only (spec §3.1 needs two)")
    c1 = None
    if phase == "fixture" and reaction_set_dir is not None:
        c1 = {**C1, "expect": c1_expectation(reaction_set_dir, base / INPUTS["a30"][0])}
    return {
        "schema": PLAN_SCHEMA, "phase": phase, "inputs": inputs, "c1": c1,
        "c2": {**C2, "expect": ubq}, "docking": DOCKING,
        "ga": {"settings": settings, "need": {key: ga_need(value, constants) for key, value in settings.items()},
               "differ": differ, "ranges": {key: list(value) for key, value in constants["GA_RANGES"].items()}},
        "loops": LOOPS, "loopPoolExcludedResnames": list(LOOP_POOL_EXCLUDED_RESNAMES),
        "send": {"script": SEND_SCRIPT, "pick": SEND_PICK}, "units": unit_plan(phase),
        "structures": {"c1": "1A30", "c2": "1UBQ", "same": False},
        "live": {"sendAllowed": bool(send_allowed), "dispatchLimit": int(dispatch_limit)} if phase == "live" else None,
    }


# ---------------------------------------------------------------------------------------------------- judgement
# The part names of each phase → the case rules they follow (the live parts rebuild C2 with the same code).
RULE_OF = {"fixture": {case: case for case in CASES}, "live": {"L-pre-C2": "C2"}}
DIFFERENCE_KEYS = ("delta", "difference", "change", "diff")


def _check_c1(seen: dict[str, Any], plan: dict[str, Any]) -> list[tuple[bool, str]]:
    want = ((plan.get("c1") or {}).get("expect")) or {}
    checks: list[tuple[bool, str]] = [(bool(want), "no C1 expectation in the plan")]
    for name in ("partial", "all"):
        got, exp = (seen.get("sets") or {}).get(name) or {}, want.get(name) or {}
        for key in ("status", "reason", "covered", "uncovered", "counts"):
            checks.append((got.get(key) == exp.get(key), f"{name} set {key} {got.get(key)!r} ≠ {exp.get(key)!r}"))
    checks.append((seen.get("catalytic") == want.get("catalytic"), "per-position M-CSA rows differ"))
    protected = seen.get("protected") or []
    checks.append((len(protected) >= 1 and protected == (want.get("all") or {}).get("protected"),
                   f"protected positions {protected}"))
    release = seen.get("release") or {}
    checks.append((release.get("residue") == (want.get("release") or {}).get("residue")
                   and release.get("status") == "candidate" and release.get("released") is True
                   and release.get("catalytic") == (want.get("release") or {}).get("catalytic"),
                   "the released residue is not a candidate keeping its M-CSA rows"))
    report = seen.get("report") or {}
    checks.append((report.get("renderVersion") == want.get("reportRender"), f"report {report.get('renderVersion')}"))
    checks.append((report.get("setHashes") == [want.get("setHash")], "report set table hash ≠ the reaction set"))
    return checks


def _rule_problems(rule: str, seen: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """The problems of one part's observation under one case rule (empty = none)."""
    units = plan["units"]["units"]
    expect = (plan.get("c2") or {}).get("expect") or {}
    checks: list[tuple[bool, str]] = []
    if rule == "C1":
        checks = _check_c1(seen, plan)
    elif rule == "C2":
        m7, model, made = seen.get("m7") or {}, seen.get("model") or {}, seen.get("set") or {}
        checks = [(m7.get("heavyAtoms") == expect.get("proteinHeavyAtoms"), f"M7 heavy atoms {m7.get('heavyAtoms')}"),
                  (m7.get("excluded") == expect.get("waters"), f"M7 excluded {m7.get('excluded')}"),
                  (made.get("candidates") == [f"{x['residue']} {x['from']}→{x['to']}"
                                              for x in expect.get("candidates", [])], "M20 candidates differ"),
                  (made.get("positions") == expect.get("positions"), f"M20 positions {made.get('positions')}"),
                  (model.get("target") == expect.get("modelTarget"), "M21 target differs"),
                  (model.get("sideBySideMismatches") == 0, "M21 side-by-side differs from the stored values"),
                  (model.get("contactMismatches") == 0, "M21 contacts differ from the stored rows"),
                  (model.get("differenceKeys") == [], f"difference-like keys {model.get('differenceKeys')}"),
                  (model.get("energyUnit") == "kJ/mol", "the potentials are not kJ/mol"),
                  (seen.get("units") == [units.get("C2-m7"), units.get("C2-m21")], f"units {seen.get('units')}")]
    elif rule == "C3":
        checks = [(seen.get("scoresFirstMode") is True, "a pair score is not its M18 first mode"),
                  (seen.get("units") == units.get("C3-pair"), f"units {seen.get('units')}")]
    elif rule == "C4":
        settings = seen.get("settings") or {}
        for key, setting in settings.items():
            need = plan["ga"]["need"][key]
            checks.append((setting.get("reserved") == need["reserved"], f"setting {key} reserved {setting.get('reserved')}"))
            checks.append((setting.get("reservedEvaluations") == need["reservedEvaluations"],
                           f"setting {key} reserved evaluations {setting.get('reservedEvaluations')}"))
            checks.append((setting.get("space") == expect.get("space"), f"setting {key} space {setting.get('space')}"))
        checks.append((set(settings) == {"1", "2"}, f"settings run {sorted(settings)}"))
        checks.append((seen.get("reuseMismatches") == 0, "setting 2 computed an individual stored by setting 1"))
    elif rule == "C5":
        checks = [(seen.get("bodyHashEqual") is True, "preview hash ≠ sent bytes hash"),
                  (seen.get("limitationsOk") is True, "the card sentences differ")]
    elif rule == "C6":
        checks = [(bool(seen.get("explore")) and seen["explore"].get("bodyHasScore") is False,
                   "the explore body carries a score"),
                  (bool(seen.get("exploit")) and seen["exploit"].get("bodyScoresStored") is True,
                   "exploit body scores differ from the stored ones")]
    elif rule == "C7":
        checks = [(seen.get("listed") == seen.get("created") and seen.get("created", 0) > 0,
                   f"listed {seen.get('listed')} of {seen.get('created')}"),
                  (seen.get("downloadMismatches") == 0, "JSON downloads differ from the stored bytes")]
    return [message for ok, message in checks if not ok]


def compare_observed(plan: dict[str, Any], observed: dict[str, Any]) -> dict[str, list[str]]:
    """This module's own check of what the harness observed against the plan (an absent observation is no problem
    here; the harness part then decides): {part: [problems]}."""
    problems: dict[str, list[str]] = {}
    for name, rule in RULE_OF[plan.get("phase", "fixture")].items():
        seen = observed.get(name) or {}
        found = _rule_problems(rule, seen, plan) if seen else []
        if found:
            problems[name] = [f"{name} {message}" for message in found]
    return problems


def harness_clean(row: dict[str, Any] | None, phase: str, rehearse: bool) -> bool:
    """The harness ran offscreen with no non-loopback request; with the fixture server every dispatch was a scripted
    transport call with the placeholder and the product key resolver was not read."""
    if not row or row.get("offscreenComplete") is not True or row.get("externalRequestCount") != 0:
        return False
    if phase == "fixture" or rehearse:
        return row.get("fixtureProof") is True
    return True


def case_records(row: dict[str, Any] | None, evidence: dict[str, Any] | None, plan: dict[str, Any] | None,
                 refs: list[str], *, phase: str = "fixture", rehearse: bool = False,
                 setup: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The phase's case records from the harness row, its evidence and this module's own comparison. A part the
    harness did not run because an earlier part failed is not_observed prerequisite_failed:<that part>; a part it
    did not report is a fail; a setup failure (the reaction set copy) fails its case."""
    parts = (evidence or {}).get("parts") or {}
    observed = (evidence or {}).get("observed") or {}
    mine = compare_observed(plan, observed) if plan else {}
    clean = harness_clean(row, phase, rehearse)
    names = CASES if phase == "fixture" else LIVE_PARTS
    out = []
    for name in names:
        if name == "L-C6":
            continue                                   # the live outcome (run()) decides L-C6
        state = parts.get(name) or {}
        detail = {"part": state, "observed": observed.get(name)}
        if (setup or {}).get(name, {}).get("status") == "fail":
            out.append(c.case_record(name, "fail", setup[name].get("reason") or "setup_failed", evidence_refs=refs,
                                     detail={**detail, "setup": setup[name]}))
            continue
        if state.get("status") == "not_run":
            blocked = next(iter(state.get("blockedBy") or []), None)
            if blocked in c.CASE_BRANCH:
                out.append(c.case_record(name, "not_observed", f"prerequisite_failed:{blocked}",
                                         evidence_refs=refs, detail=detail))
                continue
        if state.get("status") == "pass":
            if mine.get(name):
                out.append(c.case_record(name, "fail", "independent_expectation_mismatch", evidence_refs=refs,
                                         detail={**detail, "problems": mine[name]}))
            elif not clean:
                out.append(c.case_record(name, "fail", "harness_row_not_clean", evidence_refs=refs, detail=detail))
            else:
                out.append(c.case_record(name, "pass", evidence_refs=refs, detail=detail))
        elif state.get("status") == "fail":
            out.append(c.case_record(name, "fail", "harness_assertion_failed", evidence_refs=refs, detail=detail))
        else:
            out.append(c.case_record(name, "fail", "case_not_completed", evidence_refs=refs, detail=detail))
    return out


def live_result(evidence: dict[str, Any] | None, records: dict[str, dict[str, Any]],
                send_allowed: bool) -> tuple[str | None, str | None]:
    """Spec §6.3 result of the explore round and, for not_sent, its closed cause (None, None = leave it to the
    runner: the send was not allowed by the plan). Completed means the round's computation (model, then docking)
    ended with a stored result after the compute approval."""
    blocked = next((case for case in ("L-pre-C2",) if (records.get(case) or {}).get("status") != "pass"), None)
    live = (evidence or {}).get("live") or {}
    send = live.get("send") or {}
    if not send.get("dispatched") and not send.get("status"):
        if blocked:
            return "not_sent", f"prerequisite_failed:{blocked}"
        if not send_allowed:
            return None, None
        if live.get("guard"):
            return "not_sent", "ledger_refused"
        return "product_failed", None              # nothing sent although it was allowed: the product path broke
    status, reason = send.get("status"), send.get("reasonCode")
    if status == "completed":
        if live.get("egressStop"):
            return "product_failed", None          # usage unknown stops the run's egress (spec §6.3)
        computed = live.get("compute") or {}
        return ("completed", None) if computed.get("state") in ("scored", "null_result") else ("product_failed", None)
    if status == "failed" and reason in PROVIDER_FAILURES:
        return "provider_failed", None
    return "product_failed", None


def observations(evidence: dict[str, Any] | None) -> list[tuple[bool, str]]:
    """X5: the honest-absence displays the harness observed, as (ok, detail)."""
    return [(bool(item.get("ok")), str(item.get("detail"))) for item in (evidence or {}).get("x5") or []]


def tab_texts(step_dir: Path, evidence: dict[str, Any] | None) -> dict[str, str]:
    """The tab-area texts the harness captured (``texts/*.tabtext``, git-ignored, the branch-A convention; X4 scans
    them through ``BranchResult.texts``)."""
    out = {}
    for name, file in ((evidence or {}).get("texts") or {}).items():
        path = step_dir / file
        if path.is_file():
            out[name] = path.read_text(encoding="utf-8")
    return out


def step_folder(row: dict[str, Any] | None, runner_artifacts: Path, step: str) -> Path | None:
    """The harness step's artifacts folder: the one its ledger row names, else the newest ``<step>*`` folder of the
    runner's artifacts holding the evidence file (the runner adds a time suffix when the folder exists)."""
    named = (row or {}).get("artifacts")
    if named and Path(named).is_dir():
        return Path(named)
    found = sorted((path for path in Path(runner_artifacts).glob(f"{step}*")
                    if path.is_dir() and (path / EVIDENCE_FILE).is_file()), key=lambda path: path.stat().st_mtime)
    return found[-1] if found else None


def default_folders(code: Path) -> dict[str, bool]:
    return {name: (code / name).exists() for name in (".deps/precedent_reference", ".deps/reaction_reference")}


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------- entry point
def run(ctx: c.BranchContext) -> c.BranchResult:
    """Branch C of the fixture phase (C1–C7) or of the live phase (L-pre-C2 and the explore round L-C6)."""
    if ctx.phase not in STEPS:
        return c.BranchResult(notes={"error": f"unknown phase {ctx.phase!r}"})
    ctx.artifacts.mkdir(parents=True, exist_ok=True)
    folders_before = default_folders(ctx.code)
    setup: dict[str, dict[str, Any]] = {}
    reaction_dir = None
    copy = None
    if ctx.phase == "fixture":
        copy = a.ensure_reaction_copy(ctx.reaction_set, ctx.reaction)
        ctx.record("c-reaction-copy", copy["status"], copiedBy=copy.get("copiedBy"), setHash=copy.get("setHash"))
        if copy["status"] == "pass":
            reaction_dir = ctx.reaction / "sets" / copy["setHash"]
        else:
            setup["C1"] = {"status": "fail", "reason": "reaction_set_copy_failed"}
    dispatch_limit = 0
    if ctx.phase == "live":
        already = c.dispatch_total(c.count_dispatch(ctx.runs)) if Path(ctx.runs).is_dir() else 0
        dispatch_limit = already + 1 if ctx.send_allowed and already < ctx.live_calls else already
    plan = build_plan(ctx.code, ctx.phase, reaction_dir, send_allowed=ctx.send_allowed, dispatch_limit=dispatch_limit)
    plan_file = ctx.artifacts / "plan.json"
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    step = STEPS[ctx.phase]
    extra = ["--plan", str(plan_file)]
    if ctx.fixture:
        extra += ["--control", str(ctx.fixture["control"]), "--backend-pid", str(ctx.fixture["pid"])]
    row = ctx.flow(step, HARNESS, ctx.phase, extra)
    step_dir = step_folder(row, ctx.artifacts.parent, step)
    evidence = _load(step_dir / EVIDENCE_FILE) if step_dir else None
    name = step_dir.name if step_dir else step
    refs = [f"{name}/ledger-row.json", f"{name}/{EVIDENCE_FILE}", f"{ctx.branch}/plan.json"]
    cases = case_records(row, evidence, plan, refs, phase=ctx.phase, rehearse=ctx.rehearse, setup=setup)
    live: dict[str, str] = {}
    causes: dict[str, str] = {}
    if ctx.phase == "live":
        result, cause = live_result(evidence, {record["id"]: record for record in cases}, ctx.send_allowed)
        if result is not None:
            live["L-C6"] = result
            if result == "not_sent" and cause:
                causes["L-C6"] = cause
            status, reason = c.live_case_status(result, not_sent_cause=cause if result == "not_sent" else None)
            cases.append(c.case_record("L-C6", status, reason, evidence_refs=refs,
                                       detail={"result": result, "live": (evidence or {}).get("live")}))
    return c.BranchResult(
        cases=cases, runs=[run_id for run_id in [(evidence or {}).get("run")] if run_id],
        reports_created=(evidence or {}).get("reportsCreated") if evidence else None,
        texts=tab_texts(step_dir, evidence) if step_dir else {}, observations={"X5": observations(evidence)},
        live=live, not_sent_causes=causes,
        notes={"defaultFoldersBefore": folders_before, "defaultFoldersAfter": default_folders(ctx.code),
               "reactionCopy": copy, "structures": plan["structures"],
               "harness": {key: (row or {}).get(key) for key in ("status", "externalRequestCount", "fixtureProof",
                                                                 "offscreenComplete", "error")},
               "reportHandles": (evidence or {}).get("reportHandles"), "units": (evidence or {}).get("units"),
               "raises": (evidence or {}).get("raises"), "sends": (evidence or {}).get("sends"),
               "syntheticInputs": [key for key, value in plan["inputs"].items() if value["syntheticLabeled"]],
               "dispatchLimit": dispatch_limit if ctx.phase == "live" else None})
