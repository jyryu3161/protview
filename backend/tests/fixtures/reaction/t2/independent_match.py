"""Independent oracle for the M26 M-CSA matching rule (spec .dryforge/spec.md 5.3), written in task T2.

Standard library only (``json``, ``argparse``): no ``mw`` import, no product function, no gemmi. It reads the LABELLED
SYNTHETIC fixtures next to it and restates the spec in its own code:

* chain residues (M15 rule, spec 5.3 first bullet): the residues of the requested author chain in the first model, in
  file order, that are written as ATOM records or belong to a ``polymer`` entity (mmCIF ``_entity.type``). The PDB
  fixture has ATOM records only (a HETATM there would need gemmi's entity heuristic, so this oracle refuses one).
  Identity = 7 fields: model_number, chain_auth (auth_asym_id / column 22), chain_label (label_asym_id, null for the
  PDB file), seq_auth (auth_seq_id / columns 23-26), seq_label (label_seq_id, null for ``.``/``?`` and for PDB),
  icode (``pdbx_PDB_ins_code`` / column 27, ``?``/``.``/blank -> ""), resname (label_comp_id / columns 18-20).
  A new residue starts whenever (model, chain, number, insertion code, name) changes between consecutive atoms, so two
  names at one number (microheterogeneity) are two residues.
* candidates: every ``residue_chains`` member of every entry (``mcsa_id`` ascending) whose ``pdb_id`` equals the
  requested PDB ID ignoring case and whose ``chain_name`` equals the chain exactly; groups by
  (mcsa_id, residue_index, chain_name, auth_resid); per group the first matching rule of spec 5.3 steps 1-5:
  disagreeing codes -> conflict/mcsa_rows_disagree; auth_resid null -> unmatched/no_author_number; upper(code) not one of
  the 20 standard names -> unmatched/non_standard_code; chain residues with seq_auth == auth_resid: 0 ->
  residue_not_in_structure, 2+ -> ambiguous_residue_number, 1 with an insertion code -> insertion_code_present (with the
  residue); 1 without: standard name (20 names + HID HIE HIP HSD HSE HSP -> HIS, CYX -> CYS, ASH -> ASP, GLH -> GLU,
  LYN -> LYS) equal to upper(code) -> matched, otherwise conflict/residue_name_differs.
* coverage: ``pdb_not_in_snapshot`` when no member of any entry names the PDB, ``chain_not_listed`` when the PDB is
  named but no candidate is on this chain, ``covered`` otherwise; PDB ID null -> ``not_checked``.

``python3 independent_match.py --check`` recomputes every case and exits 0 only if ``expected.json`` is equal;
``--write`` rewrites it. Labelled ORACLE output, not product output; see SYNTHETIC-PROVENANCE-t2.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXPECTED = HERE / "expected.json"
STRUCTURES = {"alpha": HERE / "structure_alpha.cif", "beta": HERE / "structure_beta.pdb"}
ENTRIES = HERE / "mcsa_entries.json"

TWENTY = ("ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE", "PRO",
          "SER", "THR", "TRP", "TYR", "VAL")
RENAMED = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS", "CYX": "CYS",
           "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}
SEVEN = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")

# (name, structure, PDB ID as the caller passes it, author chain)
CASES = (
    ("alpha_A", "alpha", "0SY1", "A"),
    ("alpha_A_lowercase_pdb", "alpha", "0sy1", "A"),
    ("alpha_B_chain_not_listed", "alpha", "0SY1", "B"),
    ("alpha_A_pdb_not_in_snapshot", "alpha", "0SY9", "A"),
    ("alpha_A_pdb_not_given", "alpha", None, "A"),
    ("beta_A_null_labels", "beta", "0SY2", "A"),
    ("beta_B_null_labels", "beta", "0SY2", "B"),
)


# ------------------------------------------------------------------------------------------- structure reading

def _cif_value(token: str) -> str | None:
    return None if token in ("?", ".") else token


def _cif_atoms(text: str) -> list[dict[str, str]]:
    """The ``_atom_site`` loop rows (the fixture uses no quoted values) and the entity types."""
    lines = [line.strip() for line in text.splitlines()]
    entity_type: dict[str, str] = {}
    atoms: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        if lines[i] != "loop_":
            i += 1
            continue
        i += 1
        names = []
        while i < len(lines) and lines[i].startswith("_"):
            names.append(lines[i])
            i += 1
        table = []
        while i < len(lines) and lines[i] and not lines[i].startswith(("_", "#", "loop_", "data_")):
            values = lines[i].split()
            if len(values) != len(names):
                raise SystemExit("oracle: unexpected mmCIF row shape")
            table.append(dict(zip(names, values)))
            i += 1
        if names and names[0].startswith("_entity."):
            entity_type.update({row["_entity.id"]: row["_entity.type"] for row in table})
        elif names and names[0].startswith("_atom_site."):
            atoms = [{key.split(".", 1)[1]: value for key, value in row.items()} for row in table]
    for atom in atoms:
        atom["_entity_type"] = entity_type[atom["label_entity_id"]]
    return atoms


def _residues_cif(text: str) -> list[tuple[dict[str, Any], bool]]:
    out: list[tuple[dict[str, Any], bool]] = []
    previous = None
    first_model = None
    for atom in _cif_atoms(text):
        model = int(atom["pdbx_PDB_model_num"])
        first_model = model if first_model is None else first_model
        if model != first_model:
            continue
        icode = _cif_value(atom["pdbx_PDB_ins_code"]) or ""
        key = (model, atom["auth_asym_id"], int(atom["auth_seq_id"]), icode, atom["label_comp_id"])
        if key == previous:
            continue
        previous = key
        seq_label = _cif_value(atom["label_seq_id"])
        identity = {"model_number": model, "chain_auth": atom["auth_asym_id"],
                    "chain_label": _cif_value(atom["label_asym_id"]), "seq_auth": int(atom["auth_seq_id"]),
                    "seq_label": None if seq_label is None else int(seq_label), "icode": icode,
                    "resname": atom["label_comp_id"]}
        out.append((identity, atom["group_PDB"] == "ATOM" or atom["_entity_type"] == "polymer"))
    return out


def _residues_pdb(text: str) -> list[tuple[dict[str, Any], bool]]:
    out: list[tuple[dict[str, Any], bool]] = []
    previous = None
    for line in text.splitlines():
        record = line[:6].strip()
        if record == "HETATM":
            raise SystemExit("oracle: the PDB fixture must not contain HETATM records")
        if record != "ATOM":
            continue
        chain, number, icode, name = line[21], int(line[22:26]), line[26].strip(), line[17:20].strip()
        key = (chain, number, icode, name)
        if key == previous:
            continue
        previous = key
        out.append(({"model_number": 1, "chain_auth": chain, "chain_label": None, "seq_auth": number,
                     "seq_label": None, "icode": icode, "resname": name}, True))
    return out


def chain_residues(structure: str, chain: str) -> list[dict[str, Any]]:
    path = STRUCTURES[structure]
    parsed = _residues_cif(path.read_text()) if path.suffix == ".cif" else _residues_pdb(path.read_text())
    return [{k: identity[k] for k in SEVEN} for identity, included in parsed
            if included and identity["chain_auth"] == chain]


# ------------------------------------------------------------------------------------------- spec 5.3

def _status(group: list[dict[str, Any]], auth_resid: Any, residues: list[dict[str, Any]]):
    """(status, reason, residue, structure_resname) by the first applicable step."""
    codes = sorted({member["code"] for member in group})
    if len(codes) > 1:
        return "conflict", "mcsa_rows_disagree", None, None
    code = codes[0]
    if auth_resid is None:
        return "unmatched", "no_author_number", None, None
    if code.upper() not in TWENTY:
        return "unmatched", "non_standard_code", None, None
    found = [r for r in residues if r["seq_auth"] == auth_resid]
    if not found:
        return "unmatched", "residue_not_in_structure", None, None
    if len(found) > 1:
        return "unmatched", "ambiguous_residue_number", None, None
    residue = found[0]
    if residue["icode"] != "":
        return "unmatched", "insertion_code_present", dict(residue), residue["resname"]
    name = residue["resname"] if residue["resname"] in TWENTY else RENAMED.get(residue["resname"])
    if name == code.upper():
        return "matched", None, dict(residue), residue["resname"]
    return "conflict", "residue_name_differs", dict(residue), residue["resname"]


def mcsa_section(entries: list[dict[str, Any]], pdb_id: str | None, chain: str,
                 residues: list[dict[str, Any]]) -> dict[str, Any]:
    if pdb_id is None:
        return {"status": "not_checked", "reason": "pdb_id_not_given", "coverage": None, "entries": None,
                "rows": None, "counts": None}
    wanted = pdb_id.lower()
    pdb_named = False
    groups: dict[tuple, list[dict[str, Any]]] = {}
    sources: dict[tuple, tuple[dict[str, Any], dict[str, Any]]] = {}
    for entry in sorted(entries, key=lambda e: e["mcsa_id"]):
        for index, residue in enumerate(entry["residues"]):
            for member in residue["residue_chains"]:
                if member["pdb_id"].lower() != wanted:
                    continue
                pdb_named = True
                if member["chain_name"] != chain:
                    continue
                key = (entry["mcsa_id"], index, member["chain_name"], member["auth_resid"])
                groups.setdefault(key, []).append(member)
                sources[key] = (entry, residue)
    if not pdb_named:
        coverage = "pdb_not_in_snapshot"
    elif not groups:
        coverage = "chain_not_listed"
    else:
        coverage = "covered"
    if coverage != "covered":
        return {"status": "checked", "reason": None, "coverage": coverage, "entries": None, "rows": None,
                "counts": None}
    rows = []
    for key, members in groups.items():
        mcsa_id, index, chain_name, auth_resid = key
        entry, residue = sources[key]
        codes = sorted({m["code"] for m in members})
        status, reason, found, resname = _status(members, auth_resid, residues)
        rows.append({
            "mcsa_id": mcsa_id, "residue_index": index,
            "is_reference": any(m["is_reference"] for m in members),
            "listed": {"pdb_id": members[0]["pdb_id"], "chain_name": chain_name, "resid": members[0]["resid"],
                       "auth_resid": auth_resid, "code": "/".join(codes),
                       "assemblies": sorted({m["assembly"] for m in members if m["assembly"] is not None})},
            "status": status, "reason": reason, "residue": found, "structure_resname": resname,
            "reference": {"roles_summary": residue["roles_summary"],
                          "function_location_abv": residue["function_location_abv"], "ptm": residue["ptm"],
                          "roles": residue["roles"] if residue["roles"] else None},
        })
    rows.sort(key=lambda r: (r["mcsa_id"], r["residue_index"], r["listed"]["auth_resid"] is None,
                             r["listed"]["auth_resid"] or 0, r["listed"]["code"]))
    used = sorted({r["mcsa_id"] for r in rows})
    by_id = {e["mcsa_id"]: e for e in entries}
    return {"status": "checked", "reason": None, "coverage": "covered",
            "entries": [{"mcsa_id": i, "enzyme_name": by_id[i]["enzyme_name"],
                         "reference_uniprot_id": by_id[i]["reference_uniprot_id"],
                         "all_ecs": list(by_id[i]["all_ecs"])} for i in used],
            "rows": rows,
            "counts": {s: sum(1 for r in rows if r["status"] == s) for s in ("matched", "unmatched", "conflict")}}


def build() -> dict[str, Any]:
    entries = json.loads(ENTRIES.read_text(encoding="utf-8"))
    cases = {}
    for name, structure, pdb_id, chain in CASES:
        residues = chain_residues(structure, chain)
        cases[name] = {"structure": STRUCTURES[structure].name, "pdb_id": pdb_id, "chain_auth": chain,
                       "chain_residues": residues, "mcsa": mcsa_section(entries, pdb_id, chain, residues)}
    return {"note": ("LABELLED ORACLE output of independent_match.py over LABELLED SYNTHETIC fixtures "
                     "(not product output, not real M-CSA data)."),
            "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    fresh = build()
    if args.write:
        EXPECTED.write_text(json.dumps(fresh, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {EXPECTED.name}")
        return 0
    stored = json.loads(EXPECTED.read_text(encoding="utf-8"))
    if stored != fresh:
        print("expected.json differs from a fresh oracle run", file=sys.stderr)
        return 1
    print("expected.json matches a fresh oracle run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
