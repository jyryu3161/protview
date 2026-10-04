"""Independent plain-Python reading of the M22 GA procedure (.dryforge/spec.md section 3), standard library only.

SYNTHETIC-FIXTURE oracle. Written in T1 before any product GA code existed and never imports ``mw``: it is the
reference the T3 worker is compared with, not a copy of it. Similarity is the Tanimoto of the stored Morgan on-bit
sets (``|A & B| / |A | B|``, exact ``Fraction``; sorting uses ``float`` of it, which equals RDKit's double, see
``docs/qa/m22-ga-20261004/preflight.txt`` (a)). Scores are an input map ``candidate_id -> float | None`` (None =
no score: ``null_result`` or ``failed``); the oracle never docks.

Readings of the spec that the text leaves open are the ``ASSUMPTIONS`` below (also listed in ``expected.json`` and
the preflight); T2/T3 must confirm or change them with the coordinator, and then this file and ``expected.json``.

``python3 backend/tests/fixtures/ligand_ga/independent_ga_oracle.py --check`` recomputes every ``ga_vectors`` entry
of ``expected.json`` and every arithmetic table and exits 0 only when all are equal.
"""
from __future__ import annotations

import json
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent

ASSUMPTIONS = {
    "A1": "Generation g's individual order is carried first (elite order: score ascending, ties pool order), then "
          "the new individuals in evaluation order (= selection order: similar slots, then random slots).",
    "A2": "'Not yet picked' means not picked anywhere in this run so far, including earlier slots of the "
          "generation being built; carried individuals were picked when first chosen.",
    "A3": "A generation stopped midway lists its carried individuals and the individuals evaluated before the stop; "
          "selected-but-not-evaluated individuals are not listed.",
    "A4": "When the patience counter reaches 'patience' at the last generation (g == generations), the stop reason "
          "is generations_complete (nothing was stopped early).",
    "A5": "Running minimum: None (no score yet) -> a number counts as decreased; None -> None and x -> y with y >= x "
          "count as not decreased.",
    "A6": "When no unpicked eligible candidate is left, no further rng call is made (the remaining slots stay empty); "
          "this cannot change the outcome because nothing can be picked afterwards.",
    "A7": "A generation whose new slots are all unfilled is not recorded; the run ends with pool_exhausted and "
          "generations_done = the last recorded generation.",
}


def tanimoto(a: frozenset, b: frozenset) -> Fraction:
    union = len(a | b)
    return Fraction(len(a & b), union) if union else Fraction(0)


def round6(value: Fraction) -> str:
    """ROUND_HALF_UP to 6 decimals of the exact value, as a decimal string."""
    scaled = value * 10**6
    floor = math.floor(scaled)
    up = floor + (1 if scaled - floor >= Fraction(1, 2) else 0)
    sign, digits = ("-" if up < 0 else ""), str(abs(up)).rjust(7, "0")
    return f"{sign}{digits[:-6]}.{digits[-6:]}"


def random_slots(fraction: float, slots: int) -> int:
    return math.floor(fraction * slots + 0.5)


def reserved_units(p: dict) -> int:
    return min(p["max_new_dockings"],
               p["population_size"] + (p["generations"] - 1) * (p["population_size"] - p["elite_count"]))


def wall_clock_s(p: dict) -> int:
    return min(p["total_s"] + 600, reserved_units(p) * 300 + 300)


def run_ga(pool: list[str], eligible: list[bool], bits: dict[str, frozenset], scores: dict[str, float | None],
           reusable: set[str], ga: dict, unscored: dict[str, str] | None = None) -> dict:
    """The spec 3 path for one run. Time is not modelled (no time_exhausted / cancelled / worker_failed).
    ``unscored`` names the state of a None score (default ``null_result``; ``failed`` for a failed docking)."""
    rng = random.Random(ga["seed"])
    calls: list[dict] = []
    order = {cid: i for i, cid in enumerate(pool)}
    elig = [cid for cid, ok in zip(pool, eligible, strict=True) if ok]
    picked: set[str] = set()
    state = {"new": 0, "reused": 0, "eval_index": 0}
    generations: list[dict] = []
    best: float | None = None
    still = 0

    def sample(population: list, k: int) -> list:
        got = rng.sample(population, k)
        calls.append({"call": "sample", "population": list(population), "k": k, "result": list(got)})
        return got

    def choice(population: list):
        got = rng.choice(population)
        calls.append({"call": "choice", "population": list(population), "result": got})
        return got

    def evaluate(entry: dict) -> str | None:
        cid = entry["candidate_id"]
        if cid in reusable:
            entry["evaluation"] = "reused"
            state["reused"] += 1
        elif state["new"] >= ga["max_new_dockings"]:
            return "docking_limit"
        else:
            entry["evaluation"] = "docked"
            state["new"] += 1
        entry["eval_index"] = state["eval_index"]
        state["eval_index"] += 1
        entry["score"] = scores[cid]
        return None

    def close(index: int, individuals: list[dict], complete: bool) -> dict:
        scored = [e["score"] for e in individuals if e["score"] is not None]
        record = {"index": index, "complete": complete, "individuals": individuals,
                  "min_score": min(scored) if scored else None, "max_score": max(scored) if scored else None}
        generations.append(record)
        return record

    stop = None
    for g in range(1, ga["generations"] + 1):
        if g == 1:
            chosen = [{"candidate_id": cid, "origin": "initial", "parent_candidate_id": None, "similarity": None}
                      for cid in sample(elig, ga["population_size"])]
            carried: list[dict] = []
        else:
            prev = generations[-1]["individuals"]
            ranked = [e for e in prev if e["score"] is not None]   # A1 order
            elite = sorted(ranked, key=lambda e: (e["score"], order[e["candidate_id"]]))[:ga["elite_count"]]
            carried = [{"candidate_id": e["candidate_id"], "origin": "carried", "parent_candidate_id": None,
                        "similarity": None, "evaluation": None, "eval_index": None, "score": e["score"]}
                       for e in elite]
            slots = ga["population_size"] - len(carried)
            r = random_slots(ga["random_fraction"], slots) if ranked else slots
            chosen = []
            for _ in range(slots - r):
                unpicked = [cid for cid in elig if cid not in picked]
                if not unpicked:
                    break                                           # A6
                tour = sample(ranked, min(ga["tournament_size"], len(ranked)))
                parent = min(tour, key=lambda e: (e["score"], order[e["candidate_id"]]))["candidate_id"]
                sims = {cid: tanimoto(bits[parent], bits[cid]) for cid in unpicked}
                neighbors = sorted(unpicked, key=lambda cid: (-float(sims[cid]), order[cid]))[:ga["neighbor_count"]]
                child = choice(neighbors)
                picked.add(child)
                chosen.append({"candidate_id": child, "origin": "similar", "parent_candidate_id": parent,
                               "similarity": round6(sims[child])})
            for _ in range(r):
                unpicked = [cid for cid in elig if cid not in picked]
                if not unpicked:
                    break                                           # A6
                child = choice(unpicked)
                picked.add(child)
                chosen.append({"candidate_id": child, "origin": "random", "parent_candidate_id": None,
                               "similarity": None})
            if not chosen:
                stop = "pool_exhausted"                             # A7
                break
        if g == 1:
            picked.update(e["candidate_id"] for e in chosen)
        individuals = list(carried)
        for entry in chosen:
            entry.update(evaluation=None, eval_index=None, score=None)
            stop = evaluate(entry)
            if stop:
                break
            individuals.append(entry)
        if stop:
            close(g, individuals, False)                            # A3
            break
        record = close(g, individuals, True)
        low = record["min_score"]
        new_best = best if low is None else (low if best is None else min(best, low))
        if g >= 2:
            decreased = new_best is not None and (best is None or new_best < best)   # A5
            still = 0 if decreased else still + 1
        best = new_best
        if g == ga["generations"]:
            stop = "generations_complete"                           # A4 (checked before patience)
            break
        if g >= 2 and still >= ga["patience"]:
            stop = "no_change"
            break
    status = "complete" if stop in ("generations_complete", "no_change", "pool_exhausted") else "partial"
    for record in generations:
        for entry in record["individuals"]:
            entry["state"] = ("scored" if entry["score"] is not None else
                              (unscored or {}).get(entry["candidate_id"], "null_result"))
    return {"stop_reason": stop, "status": status,
            "generations_done": sum(1 for r in generations if r["complete"]),
            "new_dockings_used": state["new"], "reused_count": state["reused"],
            "generations": generations, "rng_calls": calls}


def _vector_inputs(doc: dict, vector: dict) -> tuple:
    pool_doc = doc["pools"][vector["pool"]]
    pool = [row["candidate_id"] for row in pool_doc["candidates"]]
    bits = {row["candidate_id"]: frozenset(row["morgan_r2_2048_on_bits"]) for row in pool_doc["candidates"]}
    eligible = vector.get("eligible", [True] * len(pool))
    scores = vector["scores"]
    return pool, eligible, bits, scores, set(vector.get("reusable", [])), vector["ga"], vector.get("unscored")


def check(doc: dict) -> list[str]:
    bad = []
    for name, vector in doc["ga_vectors"].items():
        got = run_ga(*_vector_inputs(doc, vector))
        if got != vector["expected"]:
            bad.append(f"ga_vectors.{name}")
    for row in doc["arithmetic"]["random_slots"]:
        if random_slots(row["random_fraction"], row["slots"]) != row["r"]:
            bad.append(f"random_slots {row}")
    for row in doc["arithmetic"]["reservation"]:
        if (reserved_units(row["ga"]) != row["reserved_units"] or wall_clock_s(row["ga"]) != row["wall_clock_s"] or
                (row["reserved_units"] * 300 > row["ga"]["total_s"]) != row["full_run_may_be_partial"]):
            bad.append(f"reservation {row['name']}")
    for name, pool_doc in doc["pools"].items():
        rows = pool_doc["candidates"]
        sets = [frozenset(row["morgan_r2_2048_on_bits"]) for row in rows]
        for i, row in enumerate(rows):
            if [round6(tanimoto(sets[i], other)) for other in sets] != row["tanimoto_round6"]:
                bad.append(f"pools.{name}.{row['candidate_id']}")
    return bad


def main(argv: list[str]) -> int:
    if argv != ["--check"]:
        return 2
    bad = check(json.loads((HERE / "expected.json").read_text()))
    for item in bad:
        print(f"differs: {item}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
