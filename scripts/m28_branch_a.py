"""Branch A of the M28 end-to-end acceptance: structure analysis and knowledge (.dryforge/spec.md §4.1, A1–A8).

``run(ctx: m28_common.BranchContext) -> m28_common.BranchResult`` is the entry point the runner registers as
``BRANCH_REGISTRY["a"]`` (scripts/m28_offscreen_acceptance.py). The branch never imports ``mw``: the product is reached
through the real Electron offscreen harness ``frontend/tests/offscreen/endtoend-a-flow.cjs`` (every product action a
click) and read-only loopback GETs; the expectations are computed here from the inputs, independently of the product.

Inputs (public structures in this repository, T1 preflight (b)): 1M17 (EGFR kinase with the ligand AQ4), 1FIN (CDK2 /
cyclin A), 1MQ4 (Aurora A), 1S9I, 1A30, 1A4I (enzymes in M-CSA). Reference sets, each installed once in the phase's
isolated folders and never in .deps/precedent_reference or .deps/reaction_reference:
  A7  the M27 import command ``scripts/import_precedent_snapshots.py --from <ctx.kbase> --dest <ctx.precedent>`` in a
      child whose sockets are refused and counted (the M27 runner's guard): network 0.
  A8  the archived M26 set ``ctx.reaction_set`` copied to ``ctx.reaction`` (the runner copies it when the phase starts;
      this module checks the copy against the source tree digest and copies only when the folder is still empty). The
      source is never written.

Independent expectations (this module, standard library only; nothing is read from the product):
  A1  residues and atoms of model 1 of public_1m17.cif after the screen's default policy (altloc highest_occupancy,
      waters strip_all, hydrogens strip; T6 coordinator decision 1), counted from the mmCIF ``_atom_site`` loop.
  A2  every protein heavy atom – AQ4 heavy atom pair within the 4 Å cutoff of that prepared model with its distance and
      geometric kind (N/O–N/O polar, C–C hydrophobic, other contact); the harness matches every stored contact row
      (7-field residue, atom names, distance) to exactly one pair (``""`` ↔ ``?`` insertion code, ``null`` ↔ ``.`` label
      number), and the inspection report's claims to the same pairs.
  A6  per residue: the counts by kind, the minimum distance and the polar pairs of the A2 pairs (the 1M17 oracle of the
      reference sites; nothing is fixed in code: the polar pairs come from the coordinates).
  A7  per target accession: ``moves`` / ``moves_flagged`` records with that ``target.uniprot``, the ``target.variant``
      counts of the included file, the kbase reference rows, counted from the installed set's JSONL files.
  A8  per structure chain: the M-CSA coverage, entries and row states of the business rules (M26 M-CSA section)
      computed from the installed set's ``mcsa/entries.jsonl`` and the structure's polymer residues.

The A-branch reports (A2 inspection, A3 interface SASA, A4 pockets, A5 numbering, A6 site annotation, A7 precedents ×2,
A8 reaction knowledge ×3) are counted by the harness when their POST returns 201 (``reports_created``, X1-A).
Committed evidence never holds real kbase text: the harness keeps IDs, counts and digests for A7 / A8 and the panel
texts with reference strings stay in the git-ignored artifacts (the runner holds them).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The network guard of the M27 import child.
import m27_offscreen_acceptance as m27
import m28_common as c

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path("backend/tests/fixtures")
HARNESS = "endtoend-a-flow.cjs"
STEP = "a-endtoend"
PLAN_SCHEMA = "m28_branch_a_plan@1"
ROW_SCHEMA = "m28_branch_a_row@1"
EVIDENCE_FILE = "endtoend-a-evidence.json"
IMPORTER = Path("scripts/import_precedent_snapshots.py")
CASES = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")

# Inputs: repository path, provenance label. Their SHA-256 is recorded in the plan and checked by the harness.
INPUTS = {
    "m17": ("public_1m17.cif", "public PDB entry 1M17 (RCSB CC0, M27 T1 download; EGFR kinase domain with AQ4)"),
    "fin": ("public_1fin.cif", "public PDB entry 1FIN (RCSB CC0, M27 T1 download; CDK2 / cyclin A)"),
    "mq4": ("public_1mq4.cif", "public PDB entry 1MQ4 (repository fixture; Aurora A kinase domain)"),
    "s9i": ("public_1s9i.cif", "public PDB entry 1S9I (RCSB CC0, M26 T9a download)"),
    "a30": ("public_1a30.cif", "public PDB entry 1A30 (RCSB CC0, M26 T9a download)"),
    "a4i": ("public_1a4i.cif", "public PDB entry 1A4I (RCSB CC0, M26 T9a download)"),
}
# T6 coordinator decision 2: the one AQ4 instance of 1M17 (seq_label null ↔ ".", icode "" ↔ "?").
LIGAND = {"model_number": 1, "chain_auth": "A", "chain_label": "B", "seq_auth": 999, "seq_label": None, "icode": "",
          "resname": "AQ4"}
RESIDUE_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
# T6 coordinator decision 1: the screen defaults (frontend/app/page.tsx), not the tool spec default keep_all.
SCREEN_POLICY = {"altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip"}
CUTOFF_A = 4.0
POLAR = {"N", "O"}
HYDROGENS = {"H", "D"}
WATER_NAMES = {"HOH", "WAT", "H2O", "DOD", "D2O"}
STANDARD20 = {"ALA", "CYS", "ASP", "GLU", "PHE", "GLY", "HIS", "ILE", "LYS", "LEU", "MET", "ASN", "PRO", "GLN", "ARG",
              "SER", "THR", "VAL", "TRP", "TYR"}
# A5 maps (T6 coordinator decision 5): 1M17 A on the PREPARED structure (A6 needs the map and the contacts on the
# same prepared structure, decision 0024), 1FIN A·C and 1MQ4 A on the loaded structures (1FIN B·D give
# no_usable_method).
MAPS = (
    {"id": "m17", "structure": "m17", "use": "prepared", "pdbConfirm": "1M17",
     "chains": [{"chain": "A", "expect": "P00533"}]},
    {"id": "fin", "structure": "fin", "use": "loaded", "pdbConfirm": "1FIN",
     "chains": [{"chain": "A", "expect": "P24941"}, {"chain": "C", "expect": "P24941"}]},
    {"id": "mq4", "structure": "mq4", "use": "loaded", "pdbConfirm": "1MQ4",
     "chains": [{"chain": "A", "expect": "O14965"}]},
)
# A7 links (decision 7): 1M17 A → P00533, 1FIN A·C → P24941; default request (moves_flagged not included).
PRECEDENT_LINKS = (
    {"id": "l-m17", "map": "m17", "chains": None, "includeFlagged": False, "accessions": {"A": "P00533"}},
    {"id": "l-fin", "map": "fin", "chains": None, "includeFlagged": False,
     "accessions": {"A": "P24941", "C": "P24941"}},
)
# A8 links (the inputs the M26 real stage used: chains A and B of each structure, 1S9I chain A with the M-CSA accession
# suggestion, the other chains without an accession); every expectation is computed below.
REACTION_LINKS = (
    {"id": "s9i", "structure": "s9i", "pdbId": "1S9I", "chains": ("A", "B"), "suggest": {"A"}},
    {"id": "a30", "structure": "a30", "pdbId": "1A30", "chains": ("A", "B"), "suggest": set()},
    {"id": "a4i", "structure": "a4i", "pdbId": "1A4I", "chains": ("A", "B"), "suggest": set()},
)
# The harness's part names → the spec case they belong to (A5 runs in two parts around A6, see the harness).
PART_CASE = {"A1": "A1", "A2": "A2", "A3": "A3", "A4": "A4", "A5-m17": "A5", "A6": "A6", "A5-others": "A5",
             "A7": "A7", "A8": "A8"}


# ---------------------------------------------------------------------------------------------------- mmCIF (stdlib)
_TOKEN = re.compile(r"""'(?:[^']|'(?=\S))*'|"(?:[^"]|"(?=\S))*"|\S+""")


def cif_tokens(text: str) -> Iterator[str]:
    """Value tokens of a CIF text in order: quoted strings unquoted, ``;``-delimited text fields as one token,
    comments dropped. Enough for the ``_atom_site`` and ``_entity`` categories of wwPDB mmCIF files."""
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(";"):
            field = [line[1:]]
            index += 1
            while index < len(lines) and not lines[index].startswith(";"):
                field.append(lines[index])
                index += 1
            index += 1
            yield "\n".join(field).strip()
            continue
        for match in _TOKEN.finditer(line):
            token = match.group(0)
            if token.startswith("#"):
                break
            if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
                token = token[1:-1]
            yield token
        index += 1


def cif_category(text: str, category: str) -> list[dict[str, str]]:
    """Rows of one category (``loop_`` or single items) as {item: raw value}; raw ``?`` / ``.`` are kept."""
    tokens = list(cif_tokens(text))
    prefix = category + "."
    rows: list[dict[str, str]] = []
    single: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "loop_":
            headers = []
            i += 1
            while i < len(tokens) and tokens[i].startswith("_"):
                headers.append(tokens[i])
                i += 1
            values = []
            while i < len(tokens) and not tokens[i].startswith("_") and tokens[i] != "loop_" \
                    and not tokens[i].startswith("data_"):
                values.append(tokens[i])
                i += 1
            if headers and headers[0].startswith(prefix):
                if len(values) % len(headers):
                    raise ValueError(f"{category}: {len(values)} values for {len(headers)} columns")
                names = [header[len(prefix):] for header in headers]
                rows += [dict(zip(names, values[k:k + len(names)], strict=True))
                         for k in range(0, len(values), len(names))]
            continue
        if token.startswith(prefix) and i + 1 < len(tokens):
            single[token[len(prefix):]] = tokens[i + 1]
            i += 2
            continue
        i += 1
    return rows or ([single] if single else [])


def _missing(value: str) -> bool:
    return value in ("?", ".")


def atom_records(path: Path) -> list[dict[str, Any]]:
    """The atoms of the first model of an mmCIF file in file order (7-field residue identity per atom, the product's
    conventions: icode ``?``/``.`` → ``""``, ``label_seq_id`` ``.`` → None, ``label_asym_id`` → ``chain_label``)."""
    text = Path(path).read_text(encoding="utf-8")
    rows = cif_category(text, "_atom_site")
    if not rows:
        raise ValueError(f"{path}: no _atom_site rows")
    entity = {row["id"]: row["type"] for row in cif_category(text, "_entity") if "id" in row and "type" in row}
    first = rows[0]["pdbx_PDB_model_num"]
    atoms = []
    for row in rows:
        if row["pdbx_PDB_model_num"] != first:
            continue
        residue = {"model_number": int(row["pdbx_PDB_model_num"]), "chain_auth": row["auth_asym_id"],
                   "chain_label": None if _missing(row["label_asym_id"]) else row["label_asym_id"],
                   "seq_auth": int(row["auth_seq_id"]),
                   "seq_label": None if _missing(row["label_seq_id"]) else int(row["label_seq_id"]),
                   "icode": "" if _missing(row["pdbx_PDB_ins_code"]) else row["pdbx_PDB_ins_code"],
                   "resname": row["label_comp_id"]}
        atoms.append({"residue": residue, "group": row["group_PDB"], "id": row["id"],
                      "name": row["label_atom_id"], "auth_name": row.get("auth_atom_id", row["label_atom_id"]),
                      "element": row["type_symbol"].upper(),
                      "altloc": "" if _missing(row["label_alt_id"]) else row["label_alt_id"],
                      "occupancy": float(row["occupancy"]),
                      "xyz": (float(row["Cartn_x"]), float(row["Cartn_y"]), float(row["Cartn_z"])),
                      "entity_type": entity.get(row["label_entity_id"])})
    return atoms


def residue_key(residue: dict[str, Any]) -> str:
    """The 7-field key the harness uses (``JSON.stringify`` of the fields in order)."""
    return json.dumps([residue[field] for field in RESIDUE_FIELDS], separators=(",", ":"), ensure_ascii=False)


def group_residues(atoms: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Residues as consecutive runs of atoms with the same identity, in file order."""
    residues: list[dict[str, Any]] = []
    for atom in atoms:
        key = residue_key(atom["residue"])
        if not residues or residues[-1]["key"] != key:
            residues.append({"key": key, "residue": atom["residue"], "atoms": []})
        residues[-1]["atoms"].append(atom)
    return residues


def apply_policy(atoms: list[dict[str, Any]], altloc: str = "highest_occupancy", waters: str = "strip_all",
                 hydrogens: str = "strip") -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The preparation policy on the first model: hydrogens (H, D) removed, one alternate location per residue (the
    highest mean occupancy, ties by the alternate location name; ``first`` = the first one seen), waters removed."""
    if altloc not in ("highest_occupancy", "first") or waters not in ("strip_all", "keep_all") or \
            hydrogens not in ("strip", "keep"):
        raise ValueError("unknown policy")
    removed = {"waters": 0, "hydrogens": 0, "altlocs": 0}
    kept = []
    for residue in group_residues(atoms):
        members = residue["atoms"]
        if hydrogens == "strip":
            heavy = [atom for atom in members if atom["element"] not in HYDROGENS]
            removed["hydrogens"] += len(members) - len(heavy)
            members = heavy
        alternates: dict[str, list[float]] = {}
        for atom in members:
            if atom["altloc"]:
                alternates.setdefault(atom["altloc"], []).append(atom["occupancy"])
        if alternates:
            if altloc == "highest_occupancy":
                selected = min(alternates, key=lambda alt: (-sum(alternates[alt]) / len(alternates[alt]), alt))
            else:
                selected = next(iter(alternates))
            chosen = [atom for atom in members if not atom["altloc"] or atom["altloc"] == selected]
            removed["altlocs"] += len(members) - len(chosen)
            members = chosen
        if waters == "strip_all" and residue["residue"]["resname"] in WATER_NAMES:
            removed["waters"] += 1
            continue
        kept.extend(members)
    return kept, removed


def a1_expectation(path: Path, policy: dict[str, str] = SCREEN_POLICY) -> dict[str, Any]:
    """Residues and atoms after the policy (A1), and what the policy removed, from the input file alone."""
    atoms = atom_records(path)
    kept, removed = apply_policy(atoms, **policy)
    return {"policy": dict(policy), "residues": len(group_residues(kept)), "atoms": len(kept),
            "removed": removed, "input": {"residues": len(group_residues(atoms)), "atoms": len(atoms)}}


def contact_pairs(path: Path, ligand: dict[str, Any] = LIGAND, cutoff: float = CUTOFF_A,
                  policy: dict[str, str] = SCREEN_POLICY) -> list[dict[str, Any]]:
    """Every protein (ATOM record) heavy atom – ligand heavy atom pair within ``cutoff`` Å of the prepared model, with
    the distance and its geometric kind; the ligand is the residue with exactly these 7 fields."""
    kept, _ = apply_policy(atom_records(path), **policy)
    ligand_atoms = [atom for atom in kept if atom["residue"] == ligand and atom["element"] not in HYDROGENS]
    if not ligand_atoms:
        raise ValueError(f"no ligand with the 7 fields {ligand} in {path}")
    pairs = []
    for atom in kept:
        if atom["group"] != "ATOM" or atom["element"] in HYDROGENS:
            continue
        for other in ligand_atoms:
            distance = math.dist(atom["xyz"], other["xyz"])
            if distance > cutoff:
                continue
            if atom["element"] in POLAR and other["element"] in POLAR:
                kind = "polar_contact"
            elif atom["element"] == "C" and other["element"] == "C":
                kind = "hydrophobic_contact"
            else:
                kind = "contact"
            pairs.append({"residue": dict(atom["residue"]), "protein_atom": atom["name"], "ligand_atom": other["name"],
                          "type": kind, "distance_A": distance})
    return pairs


def contact_summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts the inspection report states (rows, distinct residues, per kind, minimum distance)."""
    kinds = Counter(pair["type"] for pair in pairs)
    return {"rows": len(pairs), "residues": len({residue_key(pair["residue"]) for pair in pairs}),
            "byType": {kind: kinds.get(kind, 0) for kind in ("contact", "polar_contact", "hydrophobic_contact")},
            "minimumDistance": min((pair["distance_A"] for pair in pairs), default=None)}


def site_oracle(pairs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per residue key: the counts by kind, the minimum distance and the polar pairs (A6 oracle)."""
    out: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        entry = out.setdefault(residue_key(pair["residue"]), {
            "counts": {"contact": 0, "polar_contact": 0, "hydrophobic_contact": 0}, "min": None, "polar": []})
        entry["counts"][pair["type"]] += 1
        if entry["min"] is None or pair["distance_A"] < entry["min"]:
            entry["min"] = pair["distance_A"]
        if pair["type"] == "polar_contact":
            entry["polar"].append({"protein_atom": pair["protein_atom"], "ligand_atom": pair["ligand_atom"],
                                   "distance_A": pair["distance_A"]})
    return out


def polymer_chains(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Polymer residues per author chain of the first model in file order (polymer entity or ATOM records; the M15
    chain-residue rule, without the product's code)."""
    chains: dict[str, list[dict[str, Any]]] = {}
    for residue in group_residues(atom_records(path)):
        members = residue["atoms"]
        if any(atom["entity_type"] == "polymer" or atom["group"] == "ATOM" for atom in members):
            chains.setdefault(residue["residue"]["chain_auth"], []).append(residue["residue"])
    return chains


# ---------------------------------------------------------------------------------------------------- A7 precedents
def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def precedent_counts(moves: list[dict], flagged: list[dict], references: list[dict], accession: str,
                     include_flagged: bool = False) -> dict[str, Any]:
    """One target's expectation from the kbase files: records with ``target.uniprot == accession`` per file, the
    variant counts of the included records, the kbase reference rows, and the target state."""
    mine = [record for record in moves if record["target"]["uniprot"] == accession]
    mine_flagged = [record for record in flagged if record["target"]["uniprot"] == accession]
    included = mine + (mine_flagged if include_flagged else [])
    refs = sum(1 for row in references if row.get("uniprot") == accession)
    status = ("precedents_found" if included else "none_in_included_files" if refs else "not_in_kbase_references")
    return {"status": status, "moves": len(mine), "movesFlagged": len(mine_flagged) if include_flagged else None,
            "excluded": None if include_flagged else len(mine_flagged), "references": refs,
            "variants": dict(sorted(Counter(record["target"]["variant"] for record in included).items())),
            "flaggedInFile": len(mine_flagged)}


def precedent_set_files(set_dir: Path) -> dict[str, Path]:
    manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    return {entry["name"]: set_dir / entry["path"] for entry in manifest["files"]}


def precedent_expectations(set_dir: Path, links: Iterable[dict] = PRECEDENT_LINKS) -> list[dict[str, Any]]:
    """The expectation of every A7 link from the installed set's files (independent counts)."""
    files = precedent_set_files(set_dir)
    moves = read_jsonl(files["dist/moves.jsonl"])
    flagged = read_jsonl(files["dist/moves_flagged.jsonl"])
    references = read_jsonl(files["dist/references.jsonl"])
    out = []
    for link in links:
        by_accession: dict[str, list[str]] = {}
        for chain, accession in link["accessions"].items():
            by_accession.setdefault(accession, []).append(chain)
        targets = {}
        for accession, chains in sorted(by_accession.items()):
            counts = precedent_counts(moves, flagged, references, accession, link["includeFlagged"])
            targets[accession] = {key: counts[key] for key in ("status", "moves", "movesFlagged", "excluded",
                                                                "references", "variants")} | {"chains": sorted(chains)}
        included = sum(target["moves"] + (target["movesFlagged"] or 0) for target in targets.values())
        out.append({"id": link["id"], "map": link["map"], "chains": link["chains"],
                    "includeFlagged": link["includeFlagged"],
                    "expect": {"nullResult": included == 0,
                               "chains": {chain: ["linked", None, accession]
                                          for chain, accession in link["accessions"].items()},
                               "targets": targets}})
    return out


# ---------------------------------------------------------------------------------------------------- A8 reaction
def mcsa_expectation(entries: list[dict[str, Any]], pdb_id: str,
                     chains: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """M-CSA section expectations of one structure (business rules, M26 "M-CSA 절"): the entries naming the PDB ID,
    and per requested chain the coverage, the entries and every row's state (``mcsa_id/residue_index`` →
    ``status[:reason]``) against the structure's polymer residues."""
    pdb = pdb_id.lower()
    lookup = sorted({entry["mcsa_id"] for entry in entries for residue in entry["residues"]
                     for member in residue["residue_chains"] if member["pdb_id"].lower() == pdb})
    out: dict[str, Any] = {"lookupEntries": lookup, "chains": {}}
    for chain, residues in chains.items():
        groups: dict[tuple, list[dict[str, Any]]] = {}
        for entry in entries:
            for index, residue in enumerate(entry["residues"]):
                for member in residue["residue_chains"]:
                    if member["pdb_id"].lower() == pdb and member["chain_name"] == chain:
                        groups.setdefault((entry["mcsa_id"], index, member["auth_resid"]), []).append(member)
        if not groups:
            out["chains"][chain] = {"coverage": "chain_not_listed" if lookup else "pdb_not_in_snapshot",
                                    "counts": None}
            continue
        rows: dict[str, str] = {}
        unknown: list[str] = []
        for (mcsa_id, index, auth), members in sorted(groups.items(), key=lambda item: (
                item[0][0], item[0][1], item[0][2] is None, item[0][2] or 0)):
            key = f"{mcsa_id}/{index}"
            codes = {member["code"] for member in members}
            if len(codes) > 1:
                state = "conflict:mcsa_rows_disagree"
            elif auth is None:
                state = "unmatched:no_author_number"
            elif next(iter(codes)).upper() not in STANDARD20:
                state = "unmatched:non_standard_code"
            else:
                found = [item for item in residues if item["seq_auth"] == auth]
                if not found:
                    state = "unmatched:residue_not_in_structure"
                elif len(found) > 1:
                    state = "unmatched:ambiguous_residue_number"
                elif found[0]["icode"]:
                    state = "unmatched:insertion_code_present"
                elif found[0]["resname"] not in STANDARD20:
                    state = "unknown"                       # a name only the product's name map decides
                    unknown.append(key)
                else:
                    state = "matched" if found[0]["resname"] == next(iter(codes)).upper() else \
                        "conflict:residue_name_differs"
            rows[key] = state
        counts = Counter(state.split(":")[0] for state in rows.values())
        out["chains"][chain] = {"coverage": "covered", "entries": sorted({key[0] for key in groups}), "rows": rows,
                                "counts": {status: counts.get(status, 0) for status in ("matched", "unmatched",
                                                                                         "conflict")},
                                "unknownRows": unknown}
    return out


def uniprot_accessions(path: Path) -> set[str]:
    return {row["accession"] for row in read_jsonl(path)}


def reaction_expectations(set_dir: Path, structures: dict[str, Path],
                          links: Iterable[dict] = REACTION_LINKS) -> list[dict[str, Any]]:
    """The plan of every A8 link: the request chains (each must be a polymer chain of the file), the accession
    suggestion click for the chains named in ``suggest`` (the M-CSA entry's single reference accession), and the
    expectations."""
    files = set_dir / "files"
    entries = read_jsonl(files / "mcsa" / "entries.jsonl")
    known = uniprot_accessions(files / "uniprot_function" / "entries.jsonl")
    out = []
    for link in links:
        polymer = polymer_chains(structures[link["structure"]])
        missing = [chain for chain in link["chains"] if chain not in polymer]
        if missing:
            raise ValueError(f"{link['structure']}: no polymer chain {missing}")
        chains = {chain: polymer[chain] for chain in link["chains"]}
        expect = mcsa_expectation(entries, link["pdbId"], chains)
        requested, want = [], {}
        for chain, value in expect["chains"].items():
            suggestion = None
            if chain in link["suggest"] and value["coverage"] == "covered":
                ids = {entry["reference_uniprot_id"] for entry in entries if entry["mcsa_id"] in value["entries"]}
                if len(ids) == 1 and "," not in next(iter(ids)):
                    suggestion = next(iter(ids))
            requested.append({"chain": chain, "accession": {"suggestion": suggestion} if suggestion else None})
            item = {"coverage": value["coverage"]}
            if value["coverage"] == "covered":
                item |= {"entries": value["entries"], "rows": value["rows"]}
            item["uniprot"] = (["checked", None] if suggestion in known else
                               ["not_available", "accession_not_in_snapshot"]) if suggestion else \
                ["not_checked", "accession_not_given"]
            want[chain] = item
        out.append({"id": link["id"], "structure": link["structure"], "use": "loaded",
                    "pdbId": {"suggested": link["pdbId"]}, "lookupEntries": expect["lookupEntries"],
                    "chains": requested, "map": None,
                    "expect": {"nullResult": not expect["lookupEntries"], "chains": want},
                    "counts": {chain: value["counts"] for chain, value in expect["chains"].items()},
                    "unknownRows": {chain: value.get("unknownRows", []) for chain, value in expect["chains"].items()
                                    if value.get("unknownRows")}})
    return out


# ---------------------------------------------------------------------------------------------------- reference sets
def tree_digest(root: Path) -> str:
    """SHA-256 over every file's relative path and bytes (a folder's identity)."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def ensure_reaction_copy(source: Path, target: Path) -> dict[str, Any]:
    """The phase's reaction folder is a copy of the archived set (A8). The runner copies it when the phase starts; when
    the folder is still empty this copies it (read-only files). The source tree digest is the same before and after
    and equal to the copy's."""
    before = tree_digest(source)
    copied_by = "runner"
    if not (target / "active.json").is_file():
        if target.exists() and any(target.iterdir()):
            return {"status": "fail", "reason": "reaction folder is neither empty nor a set copy"}
        if target.exists():
            target.rmdir()
        shutil.copytree(source, target, symlinks=False)
        for path in target.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        copied_by = "branch"
    after, copy = tree_digest(source), tree_digest(target)
    active = json.loads((target / "active.json").read_text())["set_hash"]
    ok = before == after == copy
    return {"status": "pass" if ok else "fail", "copiedBy": copied_by, "setHash": active,
            "sourceDigestBefore": before, "sourceDigestAfter": after, "copyDigest": copy}


def import_argv(python: Path, code: Path, kbase: Path, dest: Path) -> list[str]:
    """The user import command in a child whose sockets are refused and counted (the M27 runner's guard)."""
    return [str(python), "-I", "-c", m27.NETWORK_GUARD, str(code / IMPORTER), "--from", str(kbase), "--dest",
            str(dest), "--yes"]


def install_precedent_set(ctx: c.BranchContext) -> dict[str, Any]:
    """One install of the real kbase dist/ into the phase's isolated precedent folder (A7), network 0."""
    log = ctx.artifacts / "precedent-import.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = import_argv(ctx.python, ctx.code, ctx.kbase, ctx.precedent)
    started = time.monotonic()
    done = subprocess.run(argv, cwd=ctx.code, env=ctx.child_env(), capture_output=True, text=True, timeout=900,
                          check=False)
    log.write_text(json.dumps({"argv": argv[:3] + ["<guard>"] + argv[4:], "exitCode": done.returncode}) + "\n"
                   + done.stdout + done.stderr)
    guard = next((json.loads(line[len("QA-NETWORK "):]) for line in done.stdout.splitlines()
                  if line.startswith("QA-NETWORK ")), None)
    info: dict[str, Any] = {"exitCode": done.returncode, "seconds": round(time.monotonic() - started, 1),
                            "networkAttempts": None if guard is None else guard["attempts"],
                            "loaded": None if guard is None else guard["loaded"], "log": log.name}
    active = ctx.precedent / "active.json"
    if done.returncode == 0 and active.is_file():
        set_hash = json.loads(active.read_text())["set_hash"]
        set_dir = ctx.precedent / "sets" / set_hash
        manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
        files = [*manifest["files"], manifest["bibliography"]["file"]]
        digests = {entry["name"]: hashlib.sha256((set_dir / entry["path"]).read_bytes()).hexdigest() for entry in files}
        info.update({"setHash": set_hash, "rows": {entry["name"]: entry["rows"] for entry in files},
                     "fileSha256": digests,
                     "filesMatchManifest": all(digests[entry["name"]] == entry["sha256"] for entry in files),
                     "kbaseCommit": manifest["kbase"]["commit"]})
    info["status"] = "pass" if (info.get("setHash") and info["networkAttempts"] == 0 and not info["loaded"]
                                and info.get("filesMatchManifest")) else "fail"
    return info


def default_folders(code: Path) -> dict[str, bool]:
    return {name: (code / name).exists() for name in (".deps/precedent_reference", ".deps/reaction_reference")}


# ---------------------------------------------------------------------------------------------------- plan
def file_record(code: Path, rel: Path) -> dict[str, Any]:
    path = code / rel
    raw = path.read_bytes()
    return {"path": str(path), "name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def build_plan(code: Path, precedent_set: Path | None, reaction_set: Path | None) -> dict[str, Any]:
    """Everything the harness needs: inputs (path, SHA-256, provenance), the independent expectations of A1, A2, A6,
    A7 and A8, the maps and links to make. ``None`` sets give no A7 / A8 part (those cases fail as not prepared)."""
    inputs = {key: {**file_record(code, FIXTURES / name), "provenance": label} for key, (name, label) in INPUTS.items()}
    m17 = code / FIXTURES / INPUTS["m17"][0]
    pairs = contact_pairs(m17)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA, "inputs": inputs, "ligand": LIGAND,
        "a1": a1_expectation(m17),
        "contacts": {"cutoff_A": CUTOFF_A, "types": ["contact", "polar_contact", "hydrophobic_contact"],
                     "pairs": pairs, "summary": contact_summary(pairs)},
        "siteOracle": site_oracle(pairs),
        "maps": [dict(spec) for spec in MAPS],
        "precedent": None, "reaction": None,
    }
    if precedent_set is not None:
        plan["precedent"] = {"setHash": precedent_set.name, "links": precedent_expectations(precedent_set)}
    if reaction_set is not None:
        structures = {key: code / FIXTURES / name for key, (name, _label) in INPUTS.items()}
        plan["reaction"] = {"setHash": reaction_set.name, "links": reaction_expectations(reaction_set, structures)}
    return plan


# ---------------------------------------------------------------------------------------------------- judgement
def compare_observed(plan: dict[str, Any], observed: dict[str, Any]) -> dict[str, list[str]]:
    """This module's own check of the values the harness observed against the plan (A1 counts, A2 contact summary,
    A7 target counts, A8 chain counts): {case: [problems]} (an absent observation is no problem here; the harness
    case is then not pass)."""
    problems: dict[str, list[str]] = {}

    def need(case: str, ok: bool, message: str) -> None:
        if not ok:
            problems.setdefault(case, []).append(message)
    a1 = observed.get("A1") or {}
    if a1:
        need("A1", a1.get("residues") == plan["a1"]["residues"], f"A1 residues {a1.get('residues')}")
        need("A1", a1.get("atoms") == plan["a1"]["atoms"], f"A1 atoms {a1.get('atoms')}")
    a2 = observed.get("A2") or {}
    if a2:
        summary = plan["contacts"]["summary"]
        need("A2", a2.get("rows") == summary["rows"] and a2.get("rows", 0) >= 1, f"A2 rows {a2.get('rows')}")
        need("A2", a2.get("byType") == summary["byType"], "A2 per-kind counts")
        need("A2", a2.get("unmatchedRows") == 0, "A2 rows without an input atom pair")
    for link in (plan.get("precedent") or {}).get("links") or []:
        got = ((observed.get("A7") or {}).get("links") or {}).get(link["id"])
        if got is None:
            continue
        for accession, want in link["expect"]["targets"].items():
            seen = (got.get("targets") or {}).get(accession) or {}
            for key in ("status", "moves", "movesFlagged", "excluded", "references"):
                need("A7", seen.get(key) == want[key], f"A7 {link['id']} {accession} {key}")
            need("A7", seen.get("variants") == want["variants"], f"A7 {link['id']} {accession} variants")
    for link in (plan.get("reaction") or {}).get("links") or []:
        got = ((observed.get("A8") or {}).get("links") or {}).get(link["id"])
        if got is None:
            continue
        for chain, counts in link["counts"].items():
            seen = (got.get("chains") or {}).get(chain) or {}
            need("A8", seen.get("coverage") == link["expect"]["chains"][chain]["coverage"],
                 f"A8 {link['id']} {chain} coverage")
            need("A8", seen.get("counts") == counts, f"A8 {link['id']} {chain} counts")
    return problems


def case_records(row: dict[str, Any] | None, evidence: dict[str, Any] | None, plan: dict[str, Any] | None,
                 setup: dict[str, Any], refs: list[str], *,
                 evidence_problem: str | None = None) -> list[dict[str, Any]]:
    """A1–A8 records from the harness row, its evidence and this module's own comparison. A case one of whose parts
    the harness did not run for want of an earlier part's state (and none of whose parts failed) is not_observed
    prerequisite_failed:<the case of that part> (T11 R5: A5 when A1 failed and A5-others passed); a case it did not
    report at all is a fail. Evidence that is not of this step fails every case with ``evidence_problem``."""
    parts = (evidence or {}).get("parts") or {}
    observed = (evidence or {}).get("observed") or {}
    mine = compare_observed(plan or {"a1": {}, "contacts": {"summary": {}}}, observed) if plan else {}
    harness_ok = bool(row) and row.get("offscreenComplete") is True and row.get("externalRequestCount") == 0 \
        and row.get("providerCallsZero") is True
    out = []
    for case in CASES:
        names = [name for name, owner in PART_CASE.items() if owner == case]
        states = [(parts.get(name) or {}).get("status") for name in names]
        blocked = [(parts.get(name) or {}).get("blockedBy") for name in names if
                   (parts.get(name) or {}).get("status") == "not_run"]
        detail = {"parts": {name: parts.get(name) for name in names}, "setup": setup.get(case)}
        if setup.get(case, {}).get("status") == "fail":
            out.append(c.case_record(case, "fail", setup[case].get("reason") or "setup_failed", evidence_refs=refs,
                                     detail=detail))
            continue
        if evidence_problem:
            out.append(c.case_record(case, "fail", evidence_problem, evidence_refs=refs, detail=detail))
            continue
        first = next((PART_CASE.get(need, need) for names_blocked in blocked for need in names_blocked or []
                      if PART_CASE.get(need, need) in c.CASE_BRANCH), None)
        if "fail" in states:
            out.append(c.case_record(case, "fail", "harness_assertion_failed", evidence_refs=refs, detail=detail))
        elif first is not None:
            out.append(c.case_record(case, "not_observed", f"prerequisite_failed:{first}", evidence_refs=refs,
                                     detail=detail))
        elif states and all(state == "pass" for state in states):
            if mine.get(case):
                out.append(c.case_record(case, "fail", "independent_expectation_mismatch", evidence_refs=refs,
                                         detail={**detail, "problems": mine[case]}))
            elif not harness_ok:
                out.append(c.case_record(case, "fail", "harness_row_not_clean", evidence_refs=refs, detail=detail))
            else:
                out.append(c.case_record(case, "pass", evidence_refs=refs, detail=detail))
        else:
            out.append(c.case_record(case, "fail", "case_not_completed", evidence_refs=refs, detail=detail))
    return out


def observations(evidence: dict[str, Any] | None) -> list[tuple[bool, str]]:
    """X5: the honest-absence displays the harness observed, as (ok, detail)."""
    return [(bool(item.get("ok")), str(item.get("detail"))) for item in (evidence or {}).get("x5") or []]


def tab_texts(step_dir: Path, evidence: dict[str, Any] | None) -> dict[str, str]:
    """The tab-area texts the harness captured (``texts/*.tabtext``: kept out of the committed evidence because the
    knowledge tab quotes kbase and M-CSA / UniProt / Rhea text; X4 scans them through ``BranchResult.texts``)."""
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


def _load(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------------- entry point
def run(ctx: c.BranchContext) -> c.BranchResult:
    """Branch A of the fixture phase (spec §4.1). The live phase has no branch A (spec §5)."""
    if ctx.phase != "fixture":
        return c.BranchResult(notes={"error": "branch A runs in the fixture phase only"})
    ctx.artifacts.mkdir(parents=True, exist_ok=True)
    folders_before = default_folders(ctx.code)
    setup: dict[str, dict[str, Any]] = {}
    precedent_dir = reaction_dir = None
    install = install_precedent_set(ctx)
    ctx.record("a-precedent-import", install["status"], networkAttempts=install.get("networkAttempts"),
               setHash=install.get("setHash"))
    if install["status"] == "pass":
        precedent_dir = ctx.precedent / "sets" / install["setHash"]
    else:
        setup["A7"] = {"status": "fail", "reason": "precedent_set_install_failed"}
    reaction = ensure_reaction_copy(ctx.reaction_set, ctx.reaction)
    ctx.record("a-reaction-copy", reaction["status"], copiedBy=reaction.get("copiedBy"),
               setHash=reaction.get("setHash"))
    if reaction["status"] == "pass":
        reaction_dir = ctx.reaction / "sets" / reaction["setHash"]
    else:
        setup["A8"] = {"status": "fail", "reason": "reaction_set_copy_failed"}
    plan = build_plan(ctx.code, precedent_dir, reaction_dir)
    plan_file = ctx.artifacts / "plan.json"
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    row = ctx.flow(STEP, HARNESS, "fixture", ["--plan", str(plan_file)])
    step_dir = step_folder(row)
    evidence = _load(step_dir / EVIDENCE_FILE) if step_dir else None
    checked = c.evidence_check(evidence, plan_file, ctx.phase)
    problem = "evidence_not_of_this_step" if checked is not None and not all(checked.values()) else None
    folders_after = default_folders(ctx.code)
    name = step_dir.name if step_dir else STEP
    refs = [f"{name}/ledger-row.json", f"{name}/{EVIDENCE_FILE}", "a/plan.json"]
    cases = case_records(row, evidence, plan, setup, refs, evidence_problem=problem)
    if problem:
        evidence = {}                              # nothing of another step's evidence is used below
    return c.BranchResult(
        cases=cases, runs=[run_id for run_id in [(evidence or {}).get("run")] if run_id],
        reports_created=(evidence or {}).get("reportsCreated") if evidence else None,
        texts=tab_texts(step_dir, evidence) if step_dir and not problem else {},
        observations={"X5": observations(evidence)},
        notes={"evidenceCheck": checked,
               "precedentImport": {key: value for key, value in install.items() if key != "fileSha256"},
               "reactionCopy": reaction, "defaultFoldersBefore": folders_before, "defaultFoldersAfter": folders_after,
               "harness": {key: (row or {}).get(key) for key in ("status", "externalRequestCount", "providerCallsZero",
                                                                 "offscreenComplete", "error")},
               "reportHandles": (evidence or {}).get("reportHandles"),
               "expected": {"a1": plan["a1"], "contacts": plan["contacts"]["summary"]}})
