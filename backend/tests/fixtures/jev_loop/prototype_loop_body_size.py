"""PROTOTYPE (M25 T1 measurement only, never product code): the largest loop request bodies (spec 4.3-4.5).

Preflight item (d) of the M25 plan. The sources are real product output made in a throw-away runs root: the M20
cheap tool on public 1UBQ / 1MQ4 (through ``Run.call``; user positions = the 20 residues with the most neighbors in
the M24 oracle ``../jev/expected.json``, 1MQ4 plus the ADP 5.0 A shell, as in M24 T1) and real M17 RDKit jobs on the
labelled synthetic M22 2,000-candidate pool inputs (``../ligand_ga/``). The M24 wire builders
(``jev_projection.build_ligand_wire`` / ``build_mutation_wire``, unmodified) make the candidate and position fields;
this script then applies this reading of spec 4.3-4.5 (a PROTOTYPE of T2, not the T2 constants):

* order: ``sha256(f"{loop_seed}:{iteration}:{send_ordinal}:{ref}")`` ascending, ties by pool position; aliases
  ``c01``/``m01``... in the shuffled order; position aliases ``p01``... by first reference in that order;
* wire: the M24 fields plus ``goal`` and ``computed`` (explore ``[{alias}]``, exploit ``[{alias, state,
  score_kcal_mol}]``), the spec 4.4 schema names and ``values_note``;
* body: ``{model, state, questions: {candidate_choice: {type, instructions, criteria}}, provider}`` with the M24
  encoder ``jev_projection.canonical_ascii``; ``instructions`` = the spec 4.5 text (copied here verbatim);
  ``criteria`` = the not-yet-computed aliases only.

Score values are placeholders for width only (a qvina-like one-decimal value and the widest finite float repr), never
results. No network, no credential. Runs live under ``--work`` (default ``runs/m25-t1-preflight/body``), deleted at
the end unless ``--keep``. Prints one JSON report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
BACKEND = TESTS.parent
REPO = BACKEND.parent
for extra in (str(BACKEND), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from ligand_job_fixture import import_file, run_job

from mw import jev_constants as J
from mw import jev_projection as P
from mw import ligand_bundle
from mw.mutation_candidates import validated_set
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import new_run

FIX = TESTS / "fixtures"
ORACLE = json.loads((FIX / "jev/expected.json").read_text(encoding="utf-8"))
MAX_BODY = J.MAX_BODY_BYTES

# --- spec 4.5 text, copied verbatim (PROTOTYPE copy; T2 owns the constants) ------------------------------------
C = ("Choose exactly one candidate from the candidates listed in the criteria to place first in a local computation "
     "queue. This is a queue-order choice only; it is not a prediction of binding, activity, affinity, stability, "
     "synthesizability, safety or the effect of a substitution. ")
O = "The order of the candidate list and the alias numbers were shuffled for this request and carry no meaning."
E = "The computed field lists the aliases of the candidates that have already been computed. "
S = ("Computed candidates are listed with their stored qvina score (Vina-family scoring function value in kcal/mol, "
     "not an affinity); a candidate without a score is listed without one, which is not zero. ")
RDK = "Property values are RDKit estimates, not measurements or interactions. "
GEO = "Distances and neighbor lists are geometry from stored coordinates, not measurements or interactions. "
NC = ("Each score belongs to the modelled structure of its own mutation, so scores are not like-for-like "
      "comparisons. ")
INSTRUCTIONS = {
    ("ligand", "explore"): C + ("Prefer the candidate whose structure (SMILES) is most different from all the computed "
                                "candidates; if no candidate is computed, choose any one. ") + E + RDK + O,
    ("ligand", "exploit"): C + ("Prefer the candidate whose structure (SMILES) is most similar to the one computed "
                                "candidate with the lowest listed score; if no candidate has a listed score, choose any "
                                "one. This is a judgment of structural similarity only, not a prediction of any "
                                "score. ") + S + RDK + O,
    ("mutation", "explore"): C + ("Prefer the candidate whose position and substitution (from, to) are most different "
                                  "from all the computed candidates; if no candidate is computed, choose any one. ")
    + E + GEO + O,
    ("mutation", "exploit"): C + ("Prefer the candidate whose position and substitution (from, to) are most similar "
                                  "to the one computed candidate with the lowest listed score; if no candidate has a "
                                  "listed score, choose any one. This is a judgment of similarity of position and "
                                  "substitution only, not a prediction of any score or of the effect of a "
                                  "mutation. ") + S + NC + GEO + O,
}
VALUES_NOTE = {
    ("ligand", "explore"): J.LIGAND_VALUES_NOTE,
    ("ligand", "exploit"): J.LIGAND_VALUES_NOTE + "; scores are stored qvina values from one fixed receptor and box",
    ("mutation", "explore"): J.MUTATION_VALUES_NOTE,
    ("mutation", "exploit"): J.MUTATION_VALUES_NOTE + "; each score belongs to the modelled structure of its own "
                                                      "mutation",
}
WIRE_SCHEMA = {"ligand": "jev_loop_ligand_candidates@1", "mutation": "jev_loop_mutation_candidates@1"}
SCORES = {"qvina_like": -10.1, "widest_float": -1.7976931348623157e+308}


def shuffled(refs: list[str], loop_seed: int, iteration: int, send_ordinal: int) -> list[int]:
    """Pool positions in send order (spec 4.3 reading)."""
    keyed = [(hashlib.sha256(f"{loop_seed}:{iteration}:{send_ordinal}:{ref}".encode("ascii")).hexdigest(), position)
             for position, ref in enumerate(refs)]
    return [position for _, position in sorted(keyed)]


def loop_wire(kind: str, goal: str, base: dict[str, Any], selection: list[dict[str, Any]], order: list[int],
              computed: int, score: float) -> tuple[dict[str, Any], list[str]]:
    """The M24 wire re-ordered (aliases in send order) plus goal / computed; returns (wire, pending aliases)."""
    prefix = J.ALIAS_PREFIXES[kind]
    candidates = [dict(base["candidates"][position]) for position in order]
    positions_out: list[dict[str, Any]] = []
    if kind == "mutation":
        by_pos = {item["pos"]: item for item in base["positions"]}
        renamed: dict[str, str] = {}
        for candidate in candidates:
            if candidate["pos"] not in renamed:
                renamed[candidate["pos"]] = f"p{len(renamed) + 1:02d}"
                positions_out.append({**by_pos[candidate["pos"]], "pos": renamed[candidate["pos"]]})
            candidate["pos"] = renamed[candidate["pos"]]
    for number, candidate in enumerate(candidates, 1):
        candidate["alias"] = f"{prefix}{number:02d}"
    aliases = [candidate["alias"] for candidate in candidates]
    done, pending = aliases[:computed], aliases[computed:]
    rows = ([{"alias": alias} for alias in done] if goal == "explore" else
            [{"alias": alias, "state": "scored", "score_kcal_mol": score} for alias in done])
    if kind == "ligand":
        wire = {"schema": WIRE_SCHEMA[kind], "task": J.WIRE_TASK, "goal": goal, "parent": base["parent"],
                "property_methods": base["property_methods"], "candidates": candidates, "computed": rows,
                "values_note": VALUES_NOTE[(kind, goal)]}
    else:
        wire = {"schema": WIRE_SCHEMA[kind], "task": J.WIRE_TASK, "goal": goal, "positions": positions_out,
                "candidates": candidates, "protection_checks": base["protection_checks"],
                **({"pockets": base["pockets"]} if "pockets" in base else {}), "computed": rows,
                "values_note": VALUES_NOTE[(kind, goal)]}
    return wire, pending


def body(kind: str, goal: str, wire: dict[str, Any], criteria: list[str]) -> bytes:
    question = {"type": J.QUESTION_TYPE, "instructions": INSTRUCTIONS[(kind, goal)],
                "criteria": {alias: J.CRITERION_TEMPLATE.format(alias=alias) for alias in criteria}}
    return P.canonical_ascii({"model": J.REQUEST_MODEL, "state": wire, "questions": {J.QUESTION_KEY: question},
                              "provider": dict(J.PROVIDER)})


def cases(kind: str, base: dict[str, Any], selection: list[dict[str, Any]], refs: list[str]) -> dict[str, Any]:
    order = shuffled(refs, 123456789, 1, 0)
    out: dict[str, Any] = {"m24_wire_body_bytes": len(P.encode_body(base, J.QUESTION_FOR_KIND[kind],
                                                                    [item["alias"] for item in selection]))}
    for goal in ("explore", "exploit"):
        for computed in (0, len(refs) - 2):
            for label, score in SCORES.items():
                if goal == "explore" and label != "qvina_like":
                    continue
                wire, pending = loop_wire(kind, goal, base, selection, order, computed, score)
                size = len(body(kind, goal, wire, pending))
                out[f"{goal}_computed{computed}_pending{len(pending)}_{label}"] = {"body_bytes": size,
                                                                                    "fits_64KiB": size <= MAX_BODY}
        # unreachable upper bound: every candidate computed AND every alias in criteria
        wire, _ = loop_wire(kind, goal, base, selection, order, len(refs), SCORES["widest_float"])
        size = len(body(kind, goal, wire, [c["alias"] for c in wire["candidates"]]))
        out[f"{goal}_upper_bound_all{len(refs)}_computed_and_all_in_criteria"] = {"body_bytes": size,
                                                                                  "fits_64KiB": size <= MAX_BODY}
    orders = [shuffled(refs, 123456789, 1, ordinal) for ordinal in (0, 1, 2)]
    out["send_ordinal_orders_differ"] = len({tuple(item) for item in orders}) == 3
    out["same_input_same_order"] = shuffled(refs, 123456789, 1, 0) == orders[0]
    out["instructions_bytes"] = {goal: len(INSTRUCTIONS[(kind, goal)]) for goal in ("explore", "exploit")}
    return out


def mutation_source(work: Path, name: str, cif: Path, ligand: dict[str, Any] | None) -> dict[str, Any]:
    run = new_run(work, run_id=f"m25_t1_body_{name.lower()}", dry_run=False)
    loaded = run.call("load_structure", {"source": str(cif), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    counts = ORACLE["structures"][name]["neighbor_counts"]
    ranked = sorted(counts, key=lambda row: (-row[4], counts.index(row)))
    user = [{"model_number": 1, "chain_auth": c, "seq_auth": s, "icode": i, "resname": r} for c, s, i, r, _ in ranked[:20]]
    args = {"structure": prepared, "sources": {"pocket": None, "residues": user,
                                               "ligand_shell": {"radius_A": 5.0} if ligand else None}}
    if ligand:
        args["ligand"] = ligand
    content = validated_set(run.store.load(run.call("generate_mutation_candidates", args).handle))
    parsed = _parse(ToolContext(store=run.store, call_id="metadata"), prepared)
    number = {(c, s, i): n for c, s, i, _, n in counts}
    first: dict[int, int] = {}
    for candidate in content["candidates"]:
        first.setdefault(candidate["position_index"], candidate["index"])

    def neighbors(position_index: int) -> int:
        residue = content["positions"][position_index]["residue"]
        return number[(residue["chain_auth"], residue["seq_auth"], residue["icode"])]

    chosen = [first[p] for p in sorted(first, key=lambda p: (-neighbors(p), p))[:20]]
    wire, selection = P.build_mutation_wire(content, chosen, parsed)
    refs = [str(item["candidate_index"]) for item in selection]
    report = cases("mutation", wire, selection, refs)
    report.update(positions=len(content["positions"]), candidates=len(content["candidates"]),
                  wire_positions=len(wire["positions"]),
                  neighbors_total=sum(len(p["neighbors"] or []) for p in wire["positions"]))
    return report


def ligand_source(work: Path) -> dict[str, Any]:
    run = new_run(work, run_id="m25_t1_body_ligand", dry_run=False)
    rules = json.loads((FIX / "ligand_ga/synthetic-ga-pool2000-rules.json").read_text())["rules"]
    parent = import_file(run, "ligand_sdf", "parent.sdf", (FIX / "docking/public-derived-parent-record0.sdf").read_bytes())
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi",
                         (FIX / "ligand_ga/synthetic-ga-pool2000-blocks.smi").read_bytes())
    started = time.monotonic()
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks],
                                                  "rules": rules})
    enumerated = run_job(run, "rdkit_enumerate_v1", {
        "inspection_handle": inspected["output_handles"][0], "site_atoms": [22], "use_fixed": False,
        "rule_ids": [f"user_{n}" for n in range(1, len(rules) + 1)]})
    seconds = round(time.monotonic() - started, 1)
    content, inspection = ligand_bundle.validated_candidate_set(run, enumerated["output_handles"][0])
    rows = content["candidates"]

    def row_bytes(row: dict[str, Any]) -> int:
        return len(json.dumps({"smiles": row["smiles"], "pains": row["pains"]}, separators=(",", ":")).encode())

    largest = sorted(range(len(rows)), key=lambda i: (-row_bytes(rows[i]), i))[:20]
    ids = [rows[i]["id"] for i in largest]
    wire, selection = P.build_ligand_wire(content, ids, inspection=inspection)
    report = cases("ligand", wire, selection, [item["candidate_id"] for item in selection])
    report.update(pool_size=len(rows), job_seconds=seconds,
                  largest_rows_smiles_chars=max(len(rows[i]["smiles"]) for i in largest),
                  rows_with_pains=sum(bool(rows[i]["pains"]["matches"]) for i in largest))
    return report


def widest(kind: str) -> dict[str, Any]:
    """Byte arithmetic for the widest allowed shapes (the M24 T1 upper-bound shapes) under the loop body."""
    if kind == "ligand":
        properties = {"crippen_logp": -12.345678901234567, "formal_charge": -3, "hba": 99, "hbd": 99,
                      "heavy_atoms": 256, "mol_weight": 3456.789012345678, "rotatable_bonds": 99,
                      "tpsa": 1234.5678901234}
        out = {}
        for k in (0, 5, 10):
            pains = [{"catalog": "PAINS_C", "name": "n" * 23} for _ in range(k)]
            base = {"parent": {"smiles": "C" * 1024, "properties": properties},
                    "property_methods": dict(J.PROPERTY_METHODS),
                    "candidates": [{"alias": f"c{n:02d}", "smiles": "C" * 1024,
                                    "generation_kinds": ["fixed_replace", "user_rule"],
                                    "stereo_flag": "new_unspecified_center", "properties": properties,
                                    "pains_matches": pains} for n in range(1, 21)]}
            wire, pending = loop_wire("ligand", "exploit", base, [], list(range(20)), 18, SCORES["widest_float"])
            size = len(body("ligand", "exploit", wire, pending))
            out[f"ligand_20x1024char_smiles_{k}_pains_each_exploit18"] = {"body_bytes": size,
                                                                          "fits_64KiB": size <= MAX_BODY}
        return out
    chain = "C" * 16
    residue = {"model_number": 1, "chain_auth": chain, "chain_label": chain, "seq_auth": -99999, "seq_label": 99999,
               "icode": "Z", "resname": "TRP"}

    def size(per_position: int) -> int:
        base = {"positions": [{"pos": f"p{n:02d}", "residue": residue, "one_letter": "W",
                               "sources": list(J.SOURCE_NAMES), "ligand_min_distance_A": 4.999999999999999,
                               "protection_released": False,
                               "window": {"chain_auth": chain, "first_seq_auth": -99999, "residues": "W" * 11,
                                          "contiguous": False},
                               "neighbors": [{"chain_auth": chain, "seq_auth": -99999, "icode": "Z", "resname": "TRP"}
                                             for _ in range(per_position)]} for n in range(1, 21)],
                "candidates": [{"alias": f"m{n:02d}", "pos": f"p{n:02d}", "from": "W", "to": "A"}
                               for n in range(1, 21)],
                "protection_checks": {key: "not_available" for key in J.PROTECTION_CHECK_KEYS},
                "pockets": {"ranks": list(range(1, 11)), "lining_residue_count": 99999}}
        wire, pending = loop_wire("mutation", "exploit", base, [], list(range(20)), 18, SCORES["widest_float"])
        return len(body("mutation", "exploit", wire, pending))

    return {"mutation_20_positions_21_widest_neighbors_exploit18": {"body_bytes": size(21)},
            "mutation_max_widest_neighbors_per_position_that_fit": max(n for n in range(200) if size(n) <= MAX_BODY)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=REPO / "runs/m25-t1-preflight/body")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    try:
        adp = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
        report = {"mutation": {"1UBQ": mutation_source(args.work, "1UBQ", FIX / "public_1ubq.cif", None),
                               "1MQ4": mutation_source(args.work, "1MQ4", FIX / "public_1mq4.cif", adp)},
                  "ligand_pool2000_largest20": ligand_source(args.work),
                  "widest_shapes": {**widest("ligand"), **widest("mutation")}}
        print(json.dumps(report, indent=1, ensure_ascii=False))
    finally:
        if not args.keep:
            shutil.rmtree(args.work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
