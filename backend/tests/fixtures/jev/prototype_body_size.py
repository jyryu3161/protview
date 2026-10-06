"""PROTOTYPE (M24 T1 measurement only, never product code): expected wire body size of 20-candidate projections.

Real product tools make the sources in a throw-away runs root (``_work_body_size`` next to this file, deleted at the
end): M20 ``generate_mutation_candidates`` on the public 1UBQ / 1MQ4 (through ``Run.call``) and M17 RDKit jobs
(``rdkit_inspect_v1`` -> ``rdkit_enumerate_v1`` through ``JobQueue``, pinned worker) on the labelled synthetic
M22 pool inputs. The wire dicts below follow spec 3 by hand (field names, aliases, closed source names, protection
check statuses only); neighbors and windows come from the independent gemmi oracle ``independent_neighbors.py``. The
question instructions are a PROTOTYPE English text of the spec 4 meaning (the real wording is a T2 constant), so the
measured bytes carry a margin note. The body is ``json.dumps(sort_keys=True, separators=(",", ":"),
allow_nan=False)`` (ASCII) of ``{model, state, questions, provider}`` with the existing gate constants.

No network, no credential, no OpenRouter call. Prints one JSON report.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
for extra in (str(BACKEND), str(TESTS), str(HERE)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import independent_neighbors as oracle
from ligand_job_fixture import import_file, run_job

from mw import ligand_bundle
from mw.egress.gate import PROVIDER, REQUEST_MODEL
from mw.mutation_candidates import validated_set
from mw.workspace import new_run

WORK = HERE / "_work_body_size"
FIX = TESTS / "fixtures"
MAX_BODY_BYTES = 65_536
SMILES_RE = re.compile(r"[A-Za-z0-9@+\-\[\]()=#$/\\%.:*]{1,1024}")
IDENT_RE = re.compile(r"[A-Za-z0-9_-]{0,16}")
LIGAND_NOTE = ("RDKit estimates, not measurements; PAINS matches are structural alerts only; no receptor or pocket "
               "information is included")
MUTATION_NOTE = ("Distances and neighbor lists are geometry from stored coordinates, not interactions; "
                 "protection_released=false means no performed check applied, not that a residue is unimportant; "
                 "checks that are not_checked or not_available were not performed")
PROTOTYPE_INSTRUCTIONS = (
    "Choose exactly one candidate from the list to place first in a local computation queue. This is a queue-order "
    "choice only; it is not a prediction of binding, activity, affinity, stability, synthesizability, safety or the "
    "effect of a substitution. Property values are RDKit estimates and distances are geometry from stored "
    "coordinates, not measurements or interactions. The order of the candidate list is the local stored order only "
    "and carries no meaning.")
CHECK_KEYS = ("user_list", "klifs_key_sites", "metal_contact", "disulfide", "catalytic_residue_database")
SOURCE_NAMES = ("pocket", "ligand_shell", "user")
KIND_OF_RULE = {"fixed": "fixed_replace"}


def encode(wire: dict[str, Any], aliases: list[str]) -> bytes:
    question = {"type": "choice", "instructions": PROTOTYPE_INSTRUCTIONS,
                "criteria": {alias: f"Candidate {alias}." for alias in aliases}}
    body = {"model": REQUEST_MODEL, "state": wire, "questions": {"candidate_choice": question}, "provider": PROVIDER}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


# ----------------------------------------------------------------------------------------------- mutation (M20)
def mutation_run(name: str, cif: Path, *, ligand: dict[str, Any] | None) -> dict[str, Any]:
    run = new_run(WORK, run_id=f"m24_t1_{name.lower()}", dry_run=False)
    loaded = run.call("load_structure", {"source": str(cif), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    expected = json.loads(oracle.EXPECTED.read_text(encoding="utf-8"))["structures"][name]
    ranked = sorted(expected["neighbor_counts"], key=lambda row: (-row[4], expected["neighbor_counts"].index(row)))
    user = [{"model_number": 1, "chain_auth": c, "seq_auth": s, "icode": i, "resname": r}
            for c, s, i, r, _ in ranked[:20]]
    args = {"structure": prepared, "sources": {"pocket": None, "residues": user,
                                               "ligand_shell": {"radius_A": 5.0} if ligand else None}}
    if ligand:
        args["ligand"] = ligand
    handle = run.call("generate_mutation_candidates", args).handle
    content = validated_set(run.store.load(handle))
    coords = run.store.load(run.store.load(prepared)["coordinates"])
    prepared_st = oracle.load_cif_text(coords.decode("utf-8"))
    raw_st = oracle.load_path(cif)
    return {"run": run, "content": content, "prepared_res": oracle.residues(prepared_st),
            "raw_res": oracle.residues(raw_st),
            "counts": {(c, s, i): n for c, s, i, _, n in expected["neighbor_counts"]}}


def mutation_wire(content: dict[str, Any], residues: list[dict[str, Any]], chosen: list[int]) -> dict[str, Any]:
    by_key = {oracle.key(entry): entry for entry in residues}
    positions, candidates, pos_alias = [], [], {}
    for n, index in enumerate(sorted(chosen), 1):
        candidate = content["candidates"][index]
        position = content["positions"][candidate["position_index"]]
        residue = position["residue"]
        if position["index"] not in pos_alias:
            pos_alias[position["index"]] = f"p{len(pos_alias) + 1:02d}"
            target = by_key[(residue["chain_auth"], residue["seq_auth"], residue["icode"])]
            found, _ = oracle.neighbors(residues, target)
            window = oracle.window(residues, target)
            names = []
            for source in position["sources"]:
                if source["kind"] not in names:
                    names.append(source["kind"])
            positions.append({
                "pos": pos_alias[position["index"]], "residue": residue, "one_letter": position["one_letter"],
                "sources": [kind for kind in SOURCE_NAMES if kind in names],
                "ligand_min_distance_A": position["ligand_min_distance_A"],
                "protection_released": position["protection"]["released"],
                "window": None if window is None else {k: window[k] for k in
                                                       ("chain_auth", "first_seq_auth", "residues", "contiguous")},
                "neighbors": found})
        candidates.append({"alias": f"m{n:02d}", "pos": pos_alias[position["index"]],
                           "from": candidate["from"], "to": candidate["to"]})
    wire = {"schema": "jev_mutation_candidates@1", "task": "choose_one_candidate", "positions": positions,
            "candidates": candidates,
            "protection_checks": {key: content["protection_checks"][key]["status"] for key in CHECK_KEYS},
            "values_note": MUTATION_NOTE}
    if content["pockets"] is not None:
        wire["pockets"] = {"ranks": content["pockets"]["ranks"],
                           "lining_residue_count": content["pockets"]["lining_residue_count"]}
    return wire


def one_per_position(content: dict[str, Any], counts: dict[tuple[str, int, str], int]) -> list[int]:
    """First candidate of each of the 20 candidate positions with the most neighbors (ties: position order)."""
    first: dict[int, int] = {}
    for candidate in content["candidates"]:
        first.setdefault(candidate["position_index"], candidate["index"])
    def neighbor_count(position_index: int) -> int:
        residue = content["positions"][position_index]["residue"]
        return counts[(residue["chain_auth"], residue["seq_auth"], residue["icode"])]
    ranked = sorted(first, key=lambda p: (-neighbor_count(p), p))[:20]
    return [first[p] for p in ranked]


def measure_mutation(name: str, cif: Path, ligand: dict[str, Any] | None) -> dict[str, Any]:
    made = mutation_run(name, cif, ligand=ligand)
    content = made["content"]
    same_geometry = all(
        (oracle.ident(a), a["protein"], a["heavy"]) == (oracle.ident(b), b["protein"], b["heavy"])
        for a, b in zip(made["prepared_res"], made["raw_res"], strict=True))
    out: dict[str, Any] = {"positions": len(content["positions"]), "candidates": len(content["candidates"]),
                           "protection_checks": {k: content["protection_checks"][k]["status"] for k in CHECK_KEYS},
                           "prepared_vs_raw_geometry_equal": same_geometry, "cases": {}}
    cases = {"max_20_positions_most_neighbors": one_per_position(content, made["counts"]),
             "min_first_20_by_index": list(range(min(20, len(content["candidates"]))))}
    for label, chosen in cases.items():
        wire = mutation_wire(content, made["prepared_res"], chosen)
        aliases = [c["alias"] for c in wire["candidates"]]
        body = encode(wire, aliases)
        neighbor_total = sum(len(p["neighbors"]) for p in wire["positions"])
        unsafe = [p["residue"] for p in wire["positions"]
                  if not all(IDENT_RE.fullmatch(str(p["residue"][f])) for f in ("chain_auth", "icode", "resname"))]
        out["cases"][label] = {"selected": len(chosen), "wire_positions": len(wire["positions"]),
                               "neighbors_total": neighbor_total, "state_bytes": len(json.dumps(
                                   wire, sort_keys=True, separators=(",", ":")).encode()),
                               "body_bytes": len(body), "fits_64KiB": len(body) <= MAX_BODY_BYTES,
                               "unsafe_identifiers": unsafe}
    return out


# ------------------------------------------------------------------------------------------------- ligand (M17)
def ligand_set(name: str, parent: Path, blocks: Path, *, rules: list[str] | None,
               use_fixed: bool) -> tuple[Any, dict[str, Any], dict[str, Any], float]:
    run = new_run(WORK, run_id=f"m24_t1_lig_{name}", dry_run=False)
    parent_h = import_file(run, "ligand_sdf", "parent.sdf", parent.read_bytes())
    blocks_h = import_file(run, "building_blocks_smiles", "blocks.smi", blocks.read_bytes())
    started = time.monotonic()
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent_h, "block_handles": [blocks_h],
                                                  **({"rules": rules} if rules else {})})
    assert inspected["status"] == "done", inspected
    args = {"inspection_handle": inspected["output_handles"][0], "site_atoms": [22], "use_fixed": use_fixed}
    if rules:
        args["rule_ids"] = [f"user_{n}" for n in range(1, len(rules) + 1)]
    enumerated = run_job(run, "rdkit_enumerate_v1", args)
    assert enumerated["status"] == "done", enumerated
    elapsed = time.monotonic() - started
    content, inspection = ligand_bundle.validated_candidate_set(run, enumerated["output_handles"][0])
    return run, content, inspection, elapsed


def ligand_wire(content: dict[str, Any], rows: list[int]) -> dict[str, Any]:
    candidates = []
    for n, index in enumerate(sorted(rows), 1):
        row = content["candidates"][index]
        kinds = sorted({KIND_OF_RULE.get(o["rule_id"], "user_rule") for o in row["origins"]})
        candidates.append({"alias": f"c{n:02d}", "smiles": row["smiles"], "generation_kinds": kinds,
                           "stereo_flag": row["stereo_flag"], "properties": row["properties"],
                           "pains_matches": [{"catalog": m["catalog"], "name": m["name"]}
                                             for m in row["pains"]["matches"]]})
    return {"schema": "jev_ligand_candidates@1", "task": "choose_one_candidate",
            "parent": {"smiles": content["parent_canonical_smiles"], "properties": content["parent_properties"]},
            "property_methods": content["property_methods"], "candidates": candidates, "values_note": LIGAND_NOTE}


def row_bytes(row: dict[str, Any]) -> int:
    return len(json.dumps({"smiles": row["smiles"], "pains": row["pains"]}, separators=(",", ":")).encode())


def measure_ligand(name: str, content: dict[str, Any], elapsed: float) -> dict[str, Any]:
    rows = content["candidates"]
    smiles_len = [len(row["smiles"]) for row in rows]
    out: dict[str, Any] = {
        "candidates": len(rows), "job_seconds": round(elapsed, 2),
        "smiles_chars": {"min": min(smiles_len), "max": max(smiles_len)},
        "parent_smiles_chars": len(content["parent_canonical_smiles"]),
        "rows_with_pains": sum(bool(row["pains"]["matches"]) for row in rows),
        "max_pains_per_row": max(len(row["pains"]["matches"]) for row in rows),
        "smiles_failing_wire_rule": sum(not SMILES_RE.fullmatch(row["smiles"]) for row in rows),
        "parent_smiles_passes_wire_rule": bool(SMILES_RE.fullmatch(content["parent_canonical_smiles"])),
        "origin_rule_ids": sorted({o["rule_id"] for row in rows for o in row["origins"]}),
        "stereo_flags": sorted({row["stereo_flag"] for row in rows}), "cases": {}}
    first = list(range(min(20, len(rows))))
    largest = sorted(range(len(rows)), key=lambda i: (-row_bytes(rows[i]), i))[:20]
    for label, chosen in {"first_20_generation_order": first, "largest_20_rows": largest}.items():
        wire = ligand_wire(content, chosen)
        body = encode(wire, [c["alias"] for c in wire["candidates"]])
        out["cases"][label] = {"selected": len(chosen), "body_bytes": len(body),
                               "fits_64KiB": len(body) <= MAX_BODY_BYTES}
    return out


def upper_bounds(mutation: dict[str, Any]) -> dict[str, Any]:
    """Byte arithmetic from the encoder for the ligand wire caps (1024-char SMILES, k PAINS matches per row)."""
    properties = {"crippen_logp": -12.345678901234567, "formal_charge": -3, "hba": 99, "hbd": 99,
                  "heavy_atoms": 256, "mol_weight": 3456.789012345678, "rotatable_bonds": 99, "tpsa": 1234.5678901234}
    methods = {key: "x" * 60 for key in properties}
    out = {}
    for k in (0, 5, 10, 20):
        pains = [{"catalog": "PAINS_C", "name": "n" * 23} for _ in range(k)]
        cands = [{"alias": f"c{n:02d}", "smiles": "C" * 1024, "generation_kinds": ["fixed_replace", "user_rule"],
                  "stereo_flag": "new_unspecified_center", "properties": properties, "pains_matches": pains}
                 for n in range(1, 21)]
        wire = {"schema": "jev_ligand_candidates@1", "task": "choose_one_candidate",
                "parent": {"smiles": "C" * 1024, "properties": properties}, "property_methods": methods,
                "candidates": cands, "values_note": LIGAND_NOTE}
        size = len(encode(wire, [c["alias"] for c in cands]))
        out[f"ligand_20x1024char_smiles_{k}_pains_each"] = {"body_bytes": size, "fits_64KiB": size <= MAX_BODY_BYTES}
    chain = "C" * 16   # longest safe chain identifier; every field at its widest allowed shape
    residue = {"model_number": 1, "chain_auth": chain, "chain_label": chain, "seq_auth": -99999, "seq_label": 99999,
               "icode": "Z", "resname": "TRP"}

    def mutation_body(per_position: int) -> int:
        positions = [{"pos": f"p{n:02d}", "residue": residue, "one_letter": "W",
                      "sources": list(SOURCE_NAMES), "ligand_min_distance_A": 4.999999999999999,
                      "protection_released": False,
                      "window": {"chain_auth": chain, "first_seq_auth": -99999, "residues": "W" * 11,
                                 "contiguous": False},
                      "neighbors": [{"chain_auth": chain, "seq_auth": -99999, "icode": "Z", "resname": "TRP"}
                                    for _ in range(per_position)]} for n in range(1, 21)]
        cands = [{"alias": f"m{n:02d}", "pos": f"p{n:02d}", "from": "W", "to": "A"} for n in range(1, 21)]
        wire = {"schema": "jev_mutation_candidates@1", "task": "choose_one_candidate", "positions": positions,
                "candidates": cands, "protection_checks": {key: "not_available" for key in CHECK_KEYS},
                "pockets": {"ranks": list(range(1, 11)), "lining_residue_count": 99999}, "values_note": MUTATION_NOTE}
        return len(encode(wire, [c["alias"] for c in cands]))

    for per_position in (21, 30):
        size = mutation_body(per_position)
        out[f"mutation_20_positions_{per_position}_widest_neighbors_each"] = {"body_bytes": size,
                                                                            "fits_64KiB": size <= MAX_BODY_BYTES}
    largest = max(n for n in range(200) if mutation_body(n) <= MAX_BODY_BYTES)
    out["mutation_20_positions_max_widest_neighbors_each_that_fit"] = largest
    observed = mutation["1MQ4"]["cases"]["max_20_positions_most_neighbors"]
    out["observed_1MQ4_mean_neighbors_per_position"] = observed["neighbors_total"] / observed["wire_positions"]
    return out


def main() -> int:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir()
    try:
        adp = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
        report: dict[str, Any] = {"mutation": {
            "1UBQ": measure_mutation("1UBQ", FIX / "public_1ubq.cif", None),
            "1MQ4": measure_mutation("1MQ4", FIX / "public_1mq4.cif", adp)}}
        rules = json.loads((FIX / "ligand_ga/synthetic-ga-pool2000-rules.json").read_text())["rules"]
        parent = FIX / "docking/public-derived-parent-record0.sdf"
        _, pool, _, seconds = ligand_set("pool2000", parent, FIX / "ligand_ga/synthetic-ga-pool2000-blocks.smi",
                                         rules=rules, use_fixed=False)
        _, small, small_inspection, small_seconds = ligand_set(
            "small", parent, FIX / "ligand_ga/synthetic-ga-small-blocks.smi", rules=None, use_fixed=True)
        report["ligand"] = {"pool2000": measure_ligand("pool2000", pool, seconds),
                            "small_pool": measure_ligand("small", small, small_seconds)}
        report["ligand"]["small_pool"]["parent_smiles_equals_inspection"] = (
            small["parent_canonical_smiles"] == small_inspection["parent"]["canonical_smiles"])
        report["ligand"]["small_pool"]["property_methods"] = small["property_methods"]
        report["upper_bounds"] = upper_bounds(report["mutation"])
        report["prototype_instructions_bytes"] = len(PROTOTYPE_INSTRUCTIONS)
        print(json.dumps(report, indent=1, ensure_ascii=False))
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
