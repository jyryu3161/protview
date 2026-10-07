"""Independent oracle for the M25 loop send order ``sha256_order_v1`` (T2, written before the product module).

Standard library only (``hashlib``, ``json``): no ``mw`` import, no product function. Reads the spec 4.3 wording:

* the order of one send: every pool candidate that is not ``unavailable`` (computed or not), sorted by
  ``sha256(f"{loop_seed}:{iteration}:{send_ordinal}:{ref}".encode("ascii")).hexdigest()`` ascending, ties by the
  stored position in the candidate set (rule O1); ``ref`` is the ligand candidate id, or the decimal string of the
  mutation candidate ``index`` (rule O2);
* aliases ``c01``... (ligand) / ``m01``... (mutation) in that order, fresh for each send (rule O3);
* mutation position aliases ``p01``... in order of the first candidate (in the send order) that points at the position
  (rule O4);
* ``criteria``: the aliases of the candidates that are not computed, in the send order (rule O5);
* ``list_position``: the 1-based place of an alias inside ``criteria``; ``list_size`` = the number of criteria (O6).

The pools are the committed real product outputs ``../ligand_ga/m17-candidate-set-small-pool.json`` (M17, ids in
stored order) and ``../sequence_ga/m20-candidate-set-1ubq-8pos.json`` (M20, ``index`` / ``position_index``), read as
data, plus one LABELLED SYNTHETIC 20-id ligand pool made here from a fixed text (``synthetic_ids``; ids only, no
chemistry). Which candidates are "computed" or "unavailable" is an input of each case (test choices, not results).

``python3 independent_order.py --check`` recomputes every case of ``expected.json`` and exits 0 only if all are equal;
``--write`` rewrites it. Labelled ORACLE, not product output; see SYNTHETIC-PROVENANCE.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent
EXPECTED = HERE / "expected.json"
LIGAND_SET = FIXTURES / "ligand_ga/m17-candidate-set-small-pool.json"
MUTATION_SET = FIXTURES / "sequence_ga/m20-candidate-set-1ubq-8pos.json"
PREFIX = {"ligand": "c", "mutation": "m"}


def synthetic_ids(count: int) -> list[str]:
    """LABELLED SYNTHETIC candidate ids ``c_`` + 16 hex (shape only; no candidate set holds them)."""
    return ["c_" + hashlib.sha256(f"m25-t2-synthetic-{n:02d}".encode("ascii")).hexdigest()[:16] for n in range(count)]


def ligand_pool() -> list[str]:
    return [row["id"] for row in json.loads(LIGAND_SET.read_text(encoding="utf-8"))["candidates"]]


def mutation_positions() -> dict[int, int]:
    rows = json.loads(MUTATION_SET.read_text(encoding="utf-8"))["content"]["candidates"]
    return {row["index"]: row["position_index"] for row in rows}


def text_of(ref: Any) -> str:
    """Rule O2: the id as is, an index as its decimal string."""
    return ref if isinstance(ref, str) else str(int(ref))


def key_of(loop_seed: int, iteration: int, send_ordinal: int, ref: Any) -> str:
    return hashlib.sha256(f"{loop_seed}:{iteration}:{send_ordinal}:{text_of(ref)}".encode("ascii")).hexdigest()


def case(name: str, kind: str, stored: list[Any], loop_seed: int, iteration: int, send_ordinal: int, *,
         computed: list[Any] = (), unavailable: list[Any] = ()) -> dict[str, Any]:
    """One send. ``stored``: the pool refs in candidate-set (stored) order."""
    kept = [ref for ref in stored if ref not in unavailable]
    keys = {text_of(ref): key_of(loop_seed, iteration, send_ordinal, ref) for ref in kept}
    position = {text_of(ref): number for number, ref in enumerate(stored)}
    order = sorted(kept, key=lambda ref: (keys[text_of(ref)], position[text_of(ref)]))   # O1
    aliases = [{"alias": f"{PREFIX[kind]}{number:02d}", "ref": ref} for number, ref in enumerate(order, 1)]  # O3
    criteria = [item["alias"] for item in aliases if item["ref"] not in computed]   # O5
    out: dict[str, Any] = {
        "name": name, "kind": kind, "loop_seed": loop_seed, "iteration": iteration, "send_ordinal": send_ordinal,
        "pool": list(stored), "computed": list(computed), "unavailable": list(unavailable),
        "keys": [keys[text_of(ref)] for ref in kept], "order": order, "aliases": aliases, "criteria": criteria,
        "list_positions": {alias: number for number, alias in enumerate(criteria, 1)},   # O6
        "list_size": len(criteria)}
    if kind == "mutation":
        positions = mutation_positions()
        first: list[int] = []
        for ref in order:                                                                 # O4
            if positions[ref] not in first:
                first.append(positions[ref])
        out["position_order"] = first
    return out


def build() -> dict[str, Any]:
    lig = ligand_pool()
    syn = synthetic_ids(20)
    mut12 = [1, 4, 6, 9, 13, 17, 20, 22, 26, 30, 33, 39]
    mut20 = list(range(0, 40, 2))
    cases = [
        case("ligand_pool10_s0_i1_o0", "ligand", lig, 0, 1, 0),
        case("ligand_pool10_s0_i1_o1", "ligand", lig, 0, 1, 1),
        case("ligand_pool10_s0_i1_o2", "ligand", lig, 0, 1, 2),
        case("ligand_pool10_s123456789_i3_o0_computed3", "ligand", lig, 123456789, 3, 0,
             computed=[lig[0], lig[4], lig[9]]),
        case("ligand_pool10_s7_i2_o1_computed2_unavailable2", "ligand", lig, 7, 2, 1,
             computed=[lig[1], lig[8]], unavailable=[lig[3], lig[6]]),
        case("ligand_pool2_s2147483647_i8_o9", "ligand", lig[:2], 2147483647, 8, 9),
        case("ligand_synthetic20_s42_i1_o0_computed5", "ligand", syn, 42, 1, 0, computed=syn[::4]),
        case("mutation_pool12_s0_i1_o0", "mutation", mut12, 0, 1, 0),
        case("mutation_pool12_s0_i1_o1", "mutation", mut12, 0, 1, 1),
        case("mutation_pool12_s0_i1_o2", "mutation", mut12, 0, 1, 2),
        case("mutation_pool12_s99_i4_o0_computed4_unavailable2", "mutation", mut12, 99, 4, 0,
             computed=[4, 13, 22, 39], unavailable=[6, 9]),   # 6 and 9 are all of position 1's pool refs
        case("mutation_pool20_s2147483647_i8_o3_computed6", "mutation", mut20, 2147483647, 8, 3,
             computed=mut20[1::3]),
    ]
    return {
        "_fixture": ("ORACLE (independent, standard library only, no mw import): M25 T2 expected sha256_order_v1 send "
                     "order, aliases, mutation position aliases, criteria and list positions. Not product output."),
        "rules": {
            "O1": ("order = the pool refs that are not unavailable, sorted by sha256(f'{loop_seed}:{iteration}:"
                   "{send_ordinal}:{ref}'.encode('ascii')).hexdigest() ascending, ties by stored position"),
            "O2": "ref text = the ligand candidate id as is, or the decimal string of the mutation candidate index",
            "O3": "aliases c01... (ligand) / m01... (mutation) in that order, fresh for each send",
            "O4": "mutation position aliases p01... by the first candidate (send order) that points at the position",
            "O5": "criteria = aliases of the candidates not computed (unavailable ones are never listed), send order",
            "O6": "list_position = 1-based place of an alias inside criteria; list_size = number of criteria",
        },
        "inputs": {"ligand_set": "../ligand_ga/m17-candidate-set-small-pool.json",
                   "mutation_set": "../sequence_ga/m20-candidate-set-1ubq-8pos.json",
                   "synthetic_ids": "c_ + sha256('m25-t2-synthetic-NN')[:16], NN = 00..19 (LABELLED SYNTHETIC)"},
        "cases": cases,
    }


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
