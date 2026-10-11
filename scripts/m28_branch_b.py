"""Branch B of the M28 end-to-end acceptance: ligand design and search (.dryforge/spec.md §4.2, B1–B8; §6 live L-B7).

``run(ctx: m28_common.BranchContext) -> m28_common.BranchResult`` is the entry point the runner registers as
``BRANCH_REGISTRY["b"]`` (scripts/m28_offscreen_acceptance.py, wired in T9). The branch never imports ``mw``: the
product is reached through the real Electron offscreen harness ``frontend/tests/offscreen/endtoend-b-flow.cjs`` (every
product action a click, every approval and limit raise a person's click on the screen) and read-only loopback GETs; the
expectations are computed here from the input files and the coordinator's decisions, independently of the product.

Inputs (repository fixtures, T1 preflight (b); the block list and the reaction rules are labeled synthetic, the parent
is public-derived, so the scope table says so):
  B1      the ProLIF public example: prepared receptor ``chemical/prolif-vina-rec.pdb`` + pose SDF
          ``chemical/prolif-vina-output.sdf`` (record 0), the M11 runner's create inputs.
  B2      parent ``docking/public-derived-parent-record0.sdf`` (site atom 22, the N-methyl carbon), SMILES blocks
          ``ligand_ga/synthetic-ga-small-blocks.smi``, SDF blocks ``ligand/synthetic-blocks.sdf`` (bromomethane among
          rejected records), and rules 2 and 3 of ``ligand_ga/synthetic-ga-pool2000-rules.json`` typed in that order
          (their rule ids become user_1, user_2), fixed replacement on (T7 coordinator decision 2).
  B3–B7   one docking setting for every docking (decision 3; the M25 ``LIGAND_SETUP``): the prepared receptor, model
          1, no instance removed, PDB CONECT, manual box centre (3.41, 0.72, 11.31) size 12 Å, seed 1, exhaustiveness
          1, two modes, energy range 3, so B3, B4, B5 and B7 reuse each other's stored M18 results.

Fixture phase order (decision 1, budget): B1, B2, B3 (+ the same arguments again), B6, B7 (explore round, then exploit
round), B4, B5 (setting 1 then 2), B8. Units: B1 2 + B2 2 + B3 1 + B7 2 = 7 of the default 8; then three limit raises
by a person's click: B4 +1, B5 setting 1 +6, setting 2 +8. The harness checks the remaining units before every
computation and the units each one used.

Live phase (decision 7, spec §6): a new run rebuilds L-pre-B2 (2 units), L-pre-B3 (1), L-pre-B4 (the B3 candidate and
three others plus the parent row: 4 new rows) with the same harness code, then ONE exploit round of the ligand loop
(L-B7, 1 unit): 8 units, no raise. The send is clicked only when ``ctx.send_allowed`` and the dispatch events of the
runs folder are below the limit given to the harness (one send); with ``ctx.rehearse`` the backend is the fixture
server (no call). Result: ``live['L-B7']`` ∈ completed | provider_failed | product_failed (spec §6.3), or not_sent with
its closed cause.
The flow gets that limit too (the runner stops the harness past it) and the dispatch events are counted around the
flow: a dispatch the harness left no send evidence for (it died, timed out or was stopped) is product_failed (T11 R2).
Only the folder the harness ledger row names is read, and its evidence must carry this plan's SHA-256 and phase.

Independent expectations (standard library only, nothing read from the product): the input files' SHA-256 and record
counts; the receptor PDB atoms (identity, element, coordinates) and the pose SDF record-0 atoms, against which every
stored chemical row role and every stored docking contact is matched and its distance recomputed; the rule texts; the
GA settings checked against the ranges read from ``backend/mw/ligand_ga_constants.py`` as text (``ast``, no import)
and their reserved units / needed seconds by the spec 6 arithmetic; the unit plan of the phase.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m28_common as c

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path("backend/tests/fixtures")
HARNESS = "endtoend-b-flow.cjs"
STEPS = {"fixture": "b-endtoend", "live": "b-live"}
PLAN_SCHEMA = "m28_branch_b_plan@1"
EVIDENCE_FILE = "endtoend-b-evidence.json"
GA_CONSTANTS = Path("backend/mw/ligand_ga_constants.py")
CASES = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8")
LIVE_PARTS = ("L-pre-B2", "L-pre-B3", "L-pre-B4", "L-B7")
# Decision 1: the order the harness runs the parts in (the spec case IDs stay fixed); a topological order of
# PART_NEEDS (the second pass of case_records follows it).
FIXTURE_ORDER = ("B1", "B2", "B3", "B6", "B7", "B4", "B5", "B8")
ORDER = {"fixture": FIXTURE_ORDER, "live": LIVE_PARTS}
# What a part needs from earlier parts = m28_common.PREREQUISITES = the harness NEEDS table (T11 R3 / R5): B4 docks
# with B3's receptor, parent and values and lists B3's and both B7 candidates as stored results; B5 uses B3's; B8
# lists the reports of B1–B7.
PART_NEEDS = {"B1": (), "B2": (), "B3": ("B2",), "B6": ("B2",), "B7": ("B2", "B3"), "B4": ("B2", "B3", "B7"),
              "B5": ("B2", "B3"), "B8": ("B1", "B2", "B3", "B4", "B5", "B6", "B7"), "L-pre-B2": (),
              "L-pre-B3": ("L-pre-B2",), "L-pre-B4": ("L-pre-B3",), "L-B7": ("L-pre-B2", "L-pre-B3", "L-pre-B4")}
# The reports each part makes (analysis type and count; T11 R3): compared with the harness's reportHandles.
REPORTS = {"fixture": {"B1": {"chemical_interactions": 1}, "B2": {"ligand_candidates": 1},
                       "B3": {"ligand_docking": 1}, "B4": {"ligand_docking_batch": 1}, "B5": {"ligand_ga": 2},
                       "B6": {"jev_choice": 1}, "B7": {"jev_loop": 2}, "B8": {}},
           "live": {"L-pre-B2": {"ligand_candidates": 1}, "L-pre-B3": {"ligand_docking": 1},
                    "L-pre-B4": {"ligand_docking_batch": 1}}}

# Inputs: repository path, provenance label, whether the scope table calls it synthetic (the parent is public-derived:
# record 0 of the ProLIF example pose file, not synthetic).
INPUTS = {
    "receptor": ("chemical/prolif-vina-rec.pdb", ("ProLIF 2.2.2 public example examples/vina prepared receptor "
                                                  "(chemical/PROVENANCE.json); a tutorial input, not experimental "
                                                  "validation"), False),
    "pose": ("chemical/prolif-vina-output.sdf", ("ProLIF 2.2.2 public example examples/vina docked poses "
                                                 "(chemical/PROVENANCE.json); record 0 is used"), False),
    "parent": ("docking/public-derived-parent-record0.sdf", ("public-derived parent: record 0 of the ProLIF pose file "
                                                             "with a fixture title line "
                                                             "(docking/SYNTHETIC-PROVENANCE.md)"), False),
    "blocksSmiles": ("ligand_ga/synthetic-ga-small-blocks.smi", ("SYNTHETIC-FIXTURE hand-written fixed-replacement "
                                                                 "blocks (ligand_ga/SYNTHETIC-PROVENANCE.md)"), True),
    "blocksSdf": ("ligand/synthetic-blocks.sdf", ("SYNTHETIC-FIXTURE block SDF with rejected records and bromomethane "
                                                  "(ligand/SYNTHETIC-PROVENANCE.md)"), True),
    "rules": ("ligand_ga/synthetic-ga-pool2000-rules.json", ("SYNTHETIC-FIXTURE user reaction SMARTS "
                                                             "(ligand_ga/SYNTHETIC-PROVENANCE.md)"), True),
}
RULE_PICK = (2, 3)                      # decision 2: the file's rules 2 and 3, typed in this order
SITE_ATOM = 22                          # the parent's N-methyl carbon (the M18/M19/M22 fixture site)
MIN_CANDIDATES = 5                      # spec B2
# B1 chemical form (the M11 runner's create inputs): model 1, SDF record 0, the user-declared ligand instance.
CHEMICAL = {"model": 1, "record": 0, "ligand": {"model_number": 1, "chain_auth": "Z", "chain_label": None,
                                                "seq_auth": 901, "seq_label": None, "icode": "", "resname": "LQA"}}
# Decision 3 (= the M25 harness LIGAND_SETUP, the M22 T1 small-pool values).
DOCKING = {"model": "1", "center": ["3.41", "0.72", "11.31"], "size": ["12", "12", "12"], "seed": "1",
           "exhaustiveness": "1", "numModes": "2", "energyRange": "3"}
CONTACT_CUTOFF_A = 4.0
# Decision 4: two GA settings (seed and population fixed; generations, random fraction and the docking cap differ).
GA_SETTING_1 = {"seed": 11, "population_size": 4, "generations": 2, "elite_count": 2, "tournament_size": 2,
                "neighbor_count": 3, "random_fraction": 0.2, "patience": 3, "max_new_dockings": 6, "total_s": 600}
GA_SETTING_2 = {**GA_SETTING_1, "generations": 3, "random_fraction": 0.5, "max_new_dockings": 8}
# The loops of B7 / L-B7: one round each (iteration cap 1); the fixture reply scripts are the good ones only.
LOOPS = {"explore": {"goal": "explore", "seed": "31", "cap": "1", "script": "good"},
         "exploit": {"goal": "exploit", "seed": "37", "cap": "1", "script": "good_second"}}
DEFAULT_UNITS = 8
# Units each computation uses (planned) and the raises a person clicks (decision 1 / decision 7).
UNIT_PLAN = {
    "fixture": {"B1-prepare": 1, "B1-detect": 1, "B2-inspect": 1, "B2-enumerate": 1, "B3": 1, "B3-again": 0,
                "B7-explore": 1, "B7-exploit": 1, "B4": 2, "B5-1": 6, "B5-2": 8},
    "live": {"B2-inspect": 1, "B2-enumerate": 1, "B3": 1, "B3-again": 0, "B4": 4, "B7-exploit": 1},
}
RAISES = {"fixture": {"B4": 1, "B5-1": 6, "B5-2": 8}, "live": {}}
# The live round's own need (the runner's LIVE_STEP["ligand"]): the harness reads /budget right before the send.
LIVE_ROUND_NEED = {"expensive_units": 1, "wall_clock_s": 300}
INPUT_LABELS = {"synthetic": "합성 표시", "public_derived": "공개 파생(합성 아님)"}
# The new rows of the batch: fixture = the B3 and both loop candidates (reused) + one new candidate + the parent row;
# live = the B3 candidate (reused) + three new candidates + the parent row.
BATCH = {"fixture": {"computed": 3, "new": 1, "newRows": 2}, "live": {"computed": 1, "new": 3, "newRows": 4}}
# Spec §6.3 classes of a send that did not complete (the reason codes of mw.jev_constants, by name).
PROVIDER_FAILURES = ("external_timeout", "transport_error", "provider_http_error", "delivery_unknown")


# ---------------------------------------------------------------------------------------------------- input files
def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pdb_atoms(path: Path) -> list[dict[str, Any]]:
    """ATOM/HETATM records of a PDB file (fixed columns): serial, name, altloc, residue identity, element, xyz."""
    atoms = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        name = line[12:16].strip()
        element = line[76:78].strip().upper() or name.lstrip("0123456789")[:1].upper()
        atoms.append({"serial": int(line[6:11]), "name": name, "altloc": line[16].strip(),
                      "resname": line[17:20].strip(), "chain": line[21].strip(), "seq": int(line[22:26]),
                      "icode": line[26].strip(), "element": element,
                      "xyz": [float(line[30:38]), float(line[38:46]), float(line[46:54])]})
    if not atoms:
        raise ValueError(f"{path}: no ATOM/HETATM records")
    return atoms


def sdf_records(path: Path) -> list[dict[str, Any]]:
    """V2000 records of an SDF file: title, atoms (1-based serial, element, xyz), bond count. A V3000 or unreadable
    record is kept with ``atoms`` None (the count of records is still the file's)."""
    records = []
    for index, chunk in enumerate(Path(path).read_text(encoding="utf-8").split("$$$$")):
        if not chunk.strip():
            continue
        if index and chunk.startswith("\n"):
            chunk = chunk[1:]                      # the line break after the previous "$$$$" (the title may be empty)
        lines = chunk.split("\n")
        title = lines[0].strip()
        atoms = None
        bonds = None
        if len(lines) > 3 and lines[3].rstrip().endswith("V2000"):
            try:
                count, bonds = int(lines[3][0:3]), int(lines[3][3:6])
                atoms = [{"serial": i + 1, "element": line[31:34].strip().upper(),
                          "xyz": [float(line[0:10]), float(line[10:20]), float(line[20:30])]}
                         for i, line in enumerate(lines[4:4 + count])]
            except (ValueError, IndexError):
                atoms = None
        records.append({"title": title, "atoms": atoms, "bonds": bonds})
    return records


def smiles_blocks(path: Path) -> list[str]:
    """Non-empty, non-comment lines of a SMILES block file (one block each)."""
    return [line for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def rule_texts(path: Path, pick: Iterable[int] = RULE_PICK) -> list[str]:
    rules = json.loads(Path(path).read_text(encoding="utf-8"))["rules"]
    return [rules[index - 1] for index in pick]


# ---------------------------------------------------------------------------------------------------- GA settings
def ga_ranges(code: Path = REPO) -> dict[str, Any]:
    """``GA_RANGES``, ``MIN_NEW_SLOTS``, ``PER_CANDIDATE_S``, ``FINISH_MARGIN_S`` and ``NEED_MARGIN_S`` read from the
    product constants file as literals (``ast``; the file is never imported or executed)."""
    tree = ast.parse((code / GA_CONSTANTS).read_text(encoding="utf-8"))
    wanted = {"GA_RANGES", "MIN_NEW_SLOTS", "PER_CANDIDATE_S", "FINISH_MARGIN_S", "NEED_MARGIN_S"}
    found: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in wanted:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    missing = wanted - set(found)
    if missing:
        raise ValueError(f"{GA_CONSTANTS}: {sorted(missing)} not found as literals")
    return found


def ga_problems(setting: dict[str, Any], constants: dict[str, Any]) -> list[str]:
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
    if setting.get("max_new_dockings", 0) < setting.get("population_size", 0):
        problems.append("max_new_dockings below population_size")
    return problems


def ga_need(setting: dict[str, Any], constants: dict[str, Any]) -> dict[str, Any]:
    """Spec 6 arithmetic: reserved_units = min(max_new, P + (G-1)(P-E)); needed wall = min(total_s + finish margin,
    reserved × per-candidate seconds + need margin); full run may be partial when reserved × per-candidate > total_s."""
    p, g, e = setting["population_size"], setting["generations"], setting["elite_count"]
    reserved = min(setting["max_new_dockings"], p + (g - 1) * (p - e))
    per = constants["PER_CANDIDATE_S"]
    wall = min(setting["total_s"] + constants["FINISH_MARGIN_S"], reserved * per + constants["NEED_MARGIN_S"])
    return {"reserved": reserved, "neededWall": wall, "mayBePartial": reserved * per > setting["total_s"]}


def settings_differ(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    """Spec §3.1: of population size, generations, seed and random fraction at least two differ."""
    return [key for key in ("population_size", "generations", "seed", "random_fraction") if first[key] != second[key]]


# ---------------------------------------------------------------------------------------------------- plan
def file_record(code: Path, rel: str, label: str, synthetic: bool) -> dict[str, Any]:
    path = code / FIXTURES / rel
    raw = path.read_bytes()
    return {"path": str(path), "name": path.name, "rel": rel, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(), "provenance": label, "syntheticLabeled": synthetic}


def unit_plan(phase: str) -> dict[str, Any]:
    """The planned units per computation, the raise a person clicks before it (the shortfall) and the remaining units
    before that raise (default limit 8); every computation must leave exactly 0 when it was raised for."""
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


def build_plan(code: Path, phase: str, *, send_allowed: bool = True, dispatch_limit: int = 0) -> dict[str, Any]:
    """Everything the harness needs: inputs (path, SHA-256, provenance, synthetic label), the independent atom tables
    of the receptor and the pose, the B2 input counts and rule texts, the docking values, the GA settings checked
    against the product ranges with their spec 6 numbers, the loops, the unit plan and (live) the send guard."""
    if phase not in STEPS:
        raise ValueError(f"unknown phase {phase!r}")
    inputs = {key: file_record(code, rel, label, synthetic) for key, (rel, label, synthetic) in INPUTS.items()}
    base = code / FIXTURES
    receptor = pdb_atoms(base / INPUTS["receptor"][0])
    poses = sdf_records(base / INPUTS["pose"][0])
    parent = sdf_records(base / INPUTS["parent"][0])
    block_records = sdf_records(base / INPUTS["blocksSdf"][0])
    constants = ga_ranges(code)
    settings = {"1": dict(GA_SETTING_1), "2": dict(GA_SETTING_2)}
    problems = {key: ga_problems(value, constants) for key, value in settings.items()}
    if any(problems.values()):
        raise ValueError(f"GA settings outside the product ranges: {problems}")
    differ = settings_differ(GA_SETTING_1, GA_SETTING_2)
    if len(differ) < 2:
        raise ValueError(f"the two GA settings differ in {differ} only (spec §3.1 needs two)")
    return {
        "schema": PLAN_SCHEMA, "phase": phase, "inputs": inputs,
        "receptorAtoms": receptor, "poseRecord0": poses[0]["atoms"], "poseRecords": len(poses),
        "parentAtoms": parent[0]["atoms"],
        "chemical": CHEMICAL,
        "b2": {"siteAtom": SITE_ATOM, "rules": rule_texts(base / INPUTS["rules"][0]), "rulePick": list(RULE_PICK),
               "smilesBlocks": len(smiles_blocks(base / INPUTS["blocksSmiles"][0])),
               "sdfRecords": len(block_records), "sdfTitles": [record["title"] for record in block_records],
               "minCandidates": MIN_CANDIDATES, "useFixed": True},
        "docking": DOCKING, "contactCutoff_A": CONTACT_CUTOFF_A,
        "ga": {"settings": settings, "need": {key: ga_need(value, constants) for key, value in settings.items()},
               "differ": differ, "ranges": {key: list(value) for key, value in constants["GA_RANGES"].items()}},
        "loops": LOOPS, "batch": BATCH[phase], "units": unit_plan(phase), "reports": REPORTS[phase],
        "live": {"sendAllowed": bool(send_allowed), "dispatchLimit": int(dispatch_limit),
                 "roundNeed": dict(LIVE_ROUND_NEED)} if phase == "live" else None,
    }


# ------------------------------------------------------------------------------------------------- independent checks
def nearest_atom(atoms: Iterable[dict[str, Any]], element: str, xyz: Iterable[float],
                 tolerance: float = 0.002) -> dict[str, Any] | None:
    """The atom of ``element`` whose coordinates are within ``tolerance`` Å of ``xyz`` (None when there is none or
    more than one)."""
    point = list(xyz)
    found = [atom for atom in atoms
             if atom["element"] == element.upper() and math.dist(atom["xyz"], point) <= tolerance]
    return found[0] if len(found) == 1 else None


def contact_pairs(receptor: list[dict[str, Any]], pose: list[dict[str, Any]],
                  cutoff: float = CONTACT_CUTOFF_A) -> list[dict[str, Any]]:
    """Every receptor heavy atom – pose heavy atom pair within ``cutoff`` Å (the M18 contact rule: heavy atoms only,
    distance only; kind by element pair), recomputed from the input receptor and a stored pose's coordinates."""
    heavy = [atom for atom in receptor if atom["element"] not in ("H", "D")]
    pairs = []
    for ligand in pose:
        if ligand["element"] in ("H", "D"):
            continue
        for atom in heavy:
            distance = math.dist(atom["xyz"], ligand["xyz"])
            if distance <= cutoff:
                both = {atom["element"], ligand["element"]}
                kind = ("polar_contact" if both <= {"N", "O"} else
                        "hydrophobic_contact" if both == {"C"} else "contact")
                pairs.append({"ligandSerial": ligand["serial"], "chain": atom["chain"], "seq": atom["seq"],
                              "icode": atom["icode"], "resname": atom["resname"], "name": atom["name"],
                              "distance_A": distance, "kind": kind})
    return pairs


# The part names of each phase → the case rules they follow (the live parts rebuild B2–B4 with the same code).
RULE_OF = {"fixture": {case: case for case in CASES},
           "live": {"L-pre-B2": "B2", "L-pre-B3": "B3", "L-pre-B4": "B4"}}


def _rule_problems(rule: str, seen: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """The problems of one part's observation under one case rule (empty = none)."""
    units = plan["units"]["units"]
    checks: list[tuple[bool, str]] = []
    if rule == "B1":
        checks = [(seen.get("rows", 0) >= 1, "no interaction row"),
                  (seen.get("rolesUnmatched") == 0, "rows with a role atom outside the input files"),
                  (seen.get("distanceMismatches") == 0, "distances differ from the input coordinates"),
                  (seen.get("units") == [units.get("B1-prepare"), units.get("B1-detect")],
                   f"units {seen.get('units')}")]
    elif rule == "B2":
        checks = [(seen.get("candidates", 0) >= plan["b2"]["minCandidates"], f"candidates {seen.get('candidates')}"),
                  (seen.get("filterMismatches") == 0, "filter results differ from the stored values"),
                  (seen.get("idMismatches") == 0, "candidate ids are not c_ + SHA-256(SMILES)[:16]"),
                  (seen.get("sdfBlocksSeen") == plan["b2"]["sdfRecords"], "SDF block records counted differently"),
                  (seen.get("smilesBlocksSeen") == plan["b2"]["smilesBlocks"], "SMILES blocks counted differently")]
    elif rule == "B3":
        again = seen.get("again") or {}
        checks = [(again.get("sameJob") is True, "the same arguments made another job"),
                  (again.get("units") == 0, "the same arguments used a unit"),
                  (seen.get("contactMismatches") == 0, "contacts differ from the recomputed pairs"),
                  (seen.get("scoreIsFirstMode") is True, "the score is not the stored first mode")]
    elif rule == "B4":
        checks = [(seen.get("newRows") == plan["batch"]["newRows"], f"new rows {seen.get('newRows')}"),
                  (seen.get("rowScoreMismatches") == 0, "row scores differ from their M18 first modes")]
    elif rule == "B5":
        for key, setting in (seen.get("settings") or {}).items():
            checks.append((setting.get("reserved") == plan["ga"]["need"][key]["reserved"],
                           f"setting {key} reserved {setting.get('reserved')}"))
        if (seen.get("settings") or {}).get("2"):
            checks.append((seen.get("reuseMismatches") == 0, "setting 2 shows an earlier individual as a new docking"))
    elif rule == "B7":
        if seen.get("explore"):
            checks.append((seen["explore"].get("bodyHasScore") is False, "the explore body carries a score"))
            checks.append((seen["explore"].get("computedSent", 0) >= 1,
                           "the explore body sent no computed candidate (the no-score check would be empty)"))
        if seen.get("exploit"):
            checks.append((seen["exploit"].get("bodyScoresStored") is True,
                           "exploit body scores differ from the stored ones"))
    elif rule == "B8":
        made = sum(count for case, kinds in (plan.get("reports") or {}).items() if case != "B8"
                   for count in kinds.values())
        checks = [(seen.get("listed") == seen.get("created") and seen.get("created", 0) > 0,
                   f"listed {seen.get('listed')} of {seen.get('created')}"),
                  (seen.get("created") == made, f"{seen.get('created')} reports made, the plan expects {made}"),
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
                 evidence_problem: str | None = None) -> list[dict[str, Any]]:
    """The phase's case records from the harness row, its evidence and this module's own comparison. A part the
    harness did not run because an earlier part failed is not_observed prerequisite_failed:<that part>; a part it
    did not report is a fail; a pass without the reports the plan expects of it is a fail; then a part whose need
    (PART_NEEDS) is not pass is not_observed prerequisite_failed:<that need> (m28_common.apply_needs). Evidence that
    is not of this step (another plan or phase) fails every part with ``evidence_problem``."""
    parts = (evidence or {}).get("parts") or {}
    observed = (evidence or {}).get("observed") or {}
    mine = compare_observed(plan, observed) if plan else {}
    clean = harness_clean(row, phase, rehearse)
    names = CASES if phase == "fixture" else LIVE_PARTS
    expected = (plan or {}).get("reports") or {}
    out = []
    for name in names:
        state = parts.get(name) or {}
        detail = {"part": state, "observed": observed.get(name)}
        if name == "L-B7":
            continue                                   # the live outcome (run()) decides L-B7
        if evidence_problem:
            out.append(c.case_record(name, "fail", evidence_problem, evidence_refs=refs, detail=detail))
            continue
        if state.get("status") == "not_run":
            blocked = next(iter(state.get("blockedBy") or []), None)
            if blocked in c.CASE_BRANCH:
                out.append(c.case_record(name, "not_observed", f"prerequisite_failed:{blocked}",
                                         evidence_refs=refs, detail=detail))
                continue
        if state.get("status") == "pass":
            reports = c.report_problems(expected.get(name), (evidence or {}).get("reportHandles"), name)
            if mine.get(name):
                out.append(c.case_record(name, "fail", "independent_expectation_mismatch", evidence_refs=refs,
                                         detail={**detail, "problems": mine[name]}))
            elif reports:
                out.append(c.case_record(name, "fail", "expected_report_missing", evidence_refs=refs,
                                         detail={**detail, "problems": reports}))
            elif not clean:
                out.append(c.case_record(name, "fail", "harness_row_not_clean", evidence_refs=refs, detail=detail))
            else:
                out.append(c.case_record(name, "pass", evidence_refs=refs, detail=detail))
        elif state.get("status") == "fail":
            out.append(c.case_record(name, "fail", "harness_assertion_failed", evidence_refs=refs, detail=detail))
        else:
            out.append(c.case_record(name, "fail", "case_not_completed", evidence_refs=refs, detail=detail))
    needed = c.apply_needs({record["id"]: record for record in out}, ORDER[phase], PART_NEEDS)
    return [needed[record["id"]] for record in out]


def live_result(evidence: dict[str, Any] | None, records: dict[str, dict[str, Any]],
                send_allowed: bool, dispatched: int = 0) -> tuple[str | None, str | None]:
    """Spec §6.3 result of the exploit round and, for not_sent, its closed cause (None, None = leave it to the
    runner: the send was not allowed by the plan). ``dispatched`` = the dispatch events the runs folder gained while
    the harness ran (T11 R2): a dispatch without the harness's send evidence (it died, timed out or was stopped after
    the click) is product_failed (spec §6.3: when it is hard to tell, product_failed), never not_sent; a send the
    harness reports (completed, provider_failed) stands only with exactly one dispatch event, none or two and more is
    product_failed (never a waivable provider failure)."""
    live = (evidence or {}).get("live") or {}
    send = live.get("send") or {}
    if dispatched and not send.get("dispatched"):
        return "product_failed", None
    blocked = next((case for case in ("L-pre-B2", "L-pre-B3", "L-pre-B4")
                    if (records.get(case) or {}).get("status") != "pass"), None)
    if not send.get("dispatched") and not send.get("status"):
        if blocked:
            return "not_sent", f"prerequisite_failed:{blocked}"
        if not send_allowed:
            return None, None
        if live.get("guard"):
            return "not_sent", "ledger_refused"
        return "product_failed", None              # nothing sent although it was allowed: the product path broke
    status, reason = send.get("status"), send.get("reasonCode")
    if dispatched != 1:
        return "product_failed", None              # a sent round has exactly one dispatch event (none, 2+: not it)
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


def step_folder(row: dict[str, Any] | None) -> Path | None:
    """The harness step's artifacts folder: the one its ledger row names and only that one (T11; no fallback to the
    newest folder of another attempt)."""
    return c.step_folder(row)


def default_folders(code: Path) -> dict[str, bool]:
    return {name: (code / name).exists() for name in (".deps/precedent_reference", ".deps/reaction_reference")}


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------- entry point
def run(ctx: c.BranchContext) -> c.BranchResult:
    """Branch B of the fixture phase (B1–B8) or of the live phase (L-pre-B2/B3/B4 and the exploit round L-B7)."""
    if ctx.phase not in STEPS:
        return c.BranchResult(notes={"error": f"unknown phase {ctx.phase!r}"})
    ctx.artifacts.mkdir(parents=True, exist_ok=True)
    folders_before = default_folders(ctx.code)
    dispatch_limit = 0
    before = 0
    if ctx.phase == "live":
        before = c.dispatch_now(ctx.runs)
        dispatch_limit = before + 1 if ctx.send_allowed and before < ctx.live_calls else before
    plan = build_plan(ctx.code, ctx.phase, send_allowed=ctx.send_allowed, dispatch_limit=dispatch_limit)
    plan_file = ctx.artifacts / "plan.json"
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    step = STEPS[ctx.phase]
    extra = ["--plan", str(plan_file)]
    if ctx.fixture:
        extra += ["--control", str(ctx.fixture["control"]), "--backend-pid", str(ctx.fixture["pid"])]
    # live: the runner stops the harness past this branch's own round (T11: already counted + its one send)
    row = ctx.flow(step, HARNESS, ctx.phase, extra, limit=dispatch_limit if ctx.phase == "live" else None)
    dispatched = c.dispatch_now(ctx.runs) - before if ctx.phase == "live" else 0
    step_dir = step_folder(row)
    evidence = _load(step_dir / EVIDENCE_FILE) if step_dir else None
    checked = c.evidence_check(evidence, plan_file, ctx.phase)
    problem = "evidence_not_of_this_step" if checked is not None and not all(checked.values()) else None
    name = step_dir.name if step_dir else step
    refs = [f"{name}/ledger-row.json", f"{name}/{EVIDENCE_FILE}", f"{ctx.branch}/plan.json"]
    cases = case_records(row, evidence, plan, refs, phase=ctx.phase, rehearse=ctx.rehearse, evidence_problem=problem)
    if problem:
        evidence = {"live": None}                  # nothing of another step's evidence is used below
    live: dict[str, str] = {}
    causes: dict[str, str] = {}
    if ctx.phase == "live":
        result, cause = live_result(evidence, {record["id"]: record for record in cases}, ctx.send_allowed,
                                    dispatched)
        if result is not None:
            live["L-B7"] = result
            if result == "not_sent" and cause:
                causes["L-B7"] = cause
            status, reason = c.live_case_status(result, not_sent_cause=cause if result == "not_sent" else None)
            cases.append(c.case_record("L-B7", status, reason, evidence_refs=refs,
                                       detail={"result": result, "live": (evidence or {}).get("live"),
                                               "dispatchedDuringFlow": dispatched}))
    labels = {key: INPUT_LABELS["synthetic"] if value["syntheticLabeled"] else INPUT_LABELS["public_derived"]
              for key, value in plan["inputs"].items() if value["syntheticLabeled"] or key == "parent"}
    return c.BranchResult(
        cases=cases, runs=[run_id for run_id in [(evidence or {}).get("run")] if run_id],
        reports_created=(evidence or {}).get("reportsCreated") if evidence else None,
        texts=tab_texts(step_dir, evidence) if step_dir and not problem else {},
        observations={"X5": observations(evidence)}, live=live, not_sent_causes=causes,
        notes={"defaultFoldersBefore": folders_before, "defaultFoldersAfter": default_folders(ctx.code),
               "harness": {key: (row or {}).get(key) for key in ("status", "externalRequestCount", "fixtureProof",
                                                                 "offscreenComplete", "error")},
               "evidenceCheck": checked,
               "reportHandles": (evidence or {}).get("reportHandles"), "units": (evidence or {}).get("units"),
               "raises": (evidence or {}).get("raises"), "sends": (evidence or {}).get("sends"),
               "syntheticInputs": dict(sorted(labels.items(), key=lambda item: item[0] != "parent")),
               "dispatchLimit": dispatch_limit if ctx.phase == "live" else None,
               "dispatchedDuringFlow": dispatched if ctx.phase == "live" else None})
