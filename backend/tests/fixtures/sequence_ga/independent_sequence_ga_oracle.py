"""Independent plain-Python reading of the M23 sequence GA procedure (.dryforge/spec.md 3, with 4 and 7 arithmetic).

SYNTHETIC-FIXTURE oracle, standard library only. Written in T1 from the spec text before any product GA code existed;
it never imports ``mw``, so it is the reference the T4 worker is compared with rather than a copy of it. Scores are an
input table (key -> state, score, reason_code); the oracle never models or docks. The synthetic tables in
``expected.json`` are selection-logic inputs, not docking or modeling values.

Readings the spec text leaves open are the ``ASSUMPTIONS`` below (also in ``expected.json`` and in the "spec
ambiguity" section of ``docs/qa/m23-sequence-ga-20261005/preflight.txt``). T2-T4 confirm or change them with the
coordinator and then update this file and ``expected.json`` together.

    python3 backend/tests/fixtures/sequence_ga/independent_sequence_ga_oracle.py --check
"""
from __future__ import annotations

import itertools
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONSECUTIVE_FAILURE_LIMIT = 5     # spec 3 step 3
DRAW_RETRIES = 50                 # spec 3 draw(): at most 50 further attempts
CHILD_RETRIES = 20                # spec 3 step 4 (e): at most 20 further attempts
B_RETRIES = 3                     # spec 3 step 4 (c): B re-drawn at most 3 times

ASSUMPTIONS = {
    "A1": "A generation lists the carried individuals first (score order of the carry list) and then the new "
          "individuals in selection order, which is also their evaluation order.",
    "A2": "A key becomes seen when it is selected, earlier slots of the generation being built included; a carried "
          "entry repeats an already seen key and adds nothing.",
    "A3": "All slots of a generation are selected first (step 2 and step 4 are selection), then evaluated in order "
          "(step 3). Parents only come from the previous generation, so this changes no choice.",
    "A4": "When no unseen key is left, a slot is skipped without any rng call, and so is every later slot of that "
          "generation.",
    "A5": "'At most 50 / 20 / 3 more times' are further attempts after the first one (51 / 21 / 4 in total).",
    "A6": "A crossover child is built in position storage order and, when it is larger than M, reduced with "
          "rng.sample(child, M) over that same position-ordered list.",
    "A7": "For a position only one parent uses, rng.random() is called even when the child already holds M "
          "mutations; the size is corrected afterwards by A6.",
    "A8": "A carried individual is skipped by the consecutive-failure counter: it neither raises nor resets it.",
    "A9": "min score comparison: null -> a number counts as decreased; null -> null and x -> y with y >= x count as "
          "not decreased. The patience counter starts at generation 2.",
    "A10": "A generation that could not fill a single new slot is not recorded; the run ends with space_exhausted "
           "and generations_done is the last recorded generation.",
    "A11": "The wild-type reference row is evaluated before any individual and is never counted in "
           "new_evaluations_used, reused_count or max_new_evaluations (reserved_units still reserves its 2 units).",
}


# ---------------------------------------------------------------- arithmetic (spec 3, 4, 7)
def elementary(counts: list[int], k: int) -> int:
    """The k-th elementary symmetric polynomial of ``counts`` (exact integer)."""
    table = [1] + [0] * len(counts)
    for value in counts:
        for index in range(len(counts), 0, -1):
            table[index] += table[index - 1] * value
    return table[k]


def space_size(counts: list[int], max_mutations: int) -> int:
    """N = sum over k = 1..M of e_k(n_1, ..., n_P) with M = min(max_mutations, P)."""
    effective = min(max_mutations, len(counts))
    return sum(elementary(counts, k) for k in range(1, effective + 1))


def slot_counts(population_size: int, carried: int, crossover_fraction: float, random_fraction: float) -> dict:
    slots = population_size - carried
    r = math.floor(random_fraction * slots + 0.5)
    s = slots - r
    c = math.floor(crossover_fraction * s + 0.5)
    return {"slots": slots, "crossover": c, "edit": s - c, "random": r}


def reserved_evaluations(ga: dict) -> int:
    return min(ga["max_new_evaluations"],
               ga["population_size"] + (ga["generations"] - 1) * (ga["population_size"] - ga["elite_count"]))


def reserved_units(ga: dict) -> int:
    return 2 * (reserved_evaluations(ga) + 1)


def wall_clock_s(ga: dict) -> int:
    return min(ga["total_s"] + 600, reserved_units(ga) * 270 + 300)


def full_run_may_be_partial(ga: dict) -> bool:
    return reserved_units(ga) * 270 > ga["total_s"]


def key_text(key: tuple[int, ...]) -> str:
    return "-".join(str(index) for index in key)


def canonical_order(positions: list[int], alts: dict[int, list[int]], max_mutations: int) -> list[tuple[int, ...]]:
    """Every key in canonical order: size ascending, then lexicographic over the candidate-index list."""
    out = []
    for size in range(1, min(max_mutations, len(positions)) + 1):
        for chosen in itertools.combinations(positions, size):
            for combo in itertools.product(*(alts[position] for position in chosen)):
                out.append(tuple(sorted(combo)))
    out.sort(key=lambda key: (len(key), key))
    return out


class Run:
    """One GA run over a fixed space with a fixed score table (spec 3). Time, cancellation and worker failures are
    outside inputs and are not modelled."""

    def __init__(self, space: dict, scores: dict, reusable: list[str], ga: dict) -> None:
        self.positions = [int(p) for p in space["positions"]]
        self.alts = {int(p): list(space["alts"][str(p)] if str(p) in space["alts"] else space["alts"][p])
                     for p in self.positions}
        self.position_of = {index: position for position in self.positions for index in self.alts[position]}
        self.max_mutations = min(ga["max_mutations"], len(self.positions))
        self.size = space_size([len(self.alts[p]) for p in self.positions], ga["max_mutations"])
        self.canonical = canonical_order(self.positions, self.alts, ga["max_mutations"])
        self.scores = scores
        self.reusable = set(reusable)
        self.ga = ga
        self.reserved = reserved_evaluations(ga)
        self.rng = random.Random(ga["seed"])
        self.calls: list[dict] = []
        self.seen: set[tuple[int, ...]] = set()
        self.new = self.reused = self.pick = self.eval_index = 0
        self.failures = 0
        self.generations: list[dict] = []

    # ---- rng wrappers (every call is logged so T4 can compare call by call)
    def _randint(self, low: int, high: int) -> int:
        value = self.rng.randint(low, high)
        self.calls.append({"call": "randint", "low": low, "high": high, "result": value})
        return value

    def _random(self) -> float:
        value = self.rng.random()
        self.calls.append({"call": "random", "result_lt_half": value < 0.5})
        return value

    def _sample(self, population: list, k: int) -> list:
        value = self.rng.sample(population, k)
        self.calls.append({"call": "sample", "population": _log(population), "k": k, "result": _log(value)})
        return value

    def _choice(self, population: list):
        value = self.rng.choice(population)
        self.calls.append({"call": "choice", "population": _log(population), "result": _log([value])[0]})
        return value

    # ---- order and pools
    def order_key(self, entry: dict) -> tuple:
        return (entry["score"], len(entry["key"]), entry["pick_index"])

    def scored(self, individuals: list[dict]) -> list[dict]:
        return [entry for entry in individuals if entry["state"] == "scored"]

    def pool(self, previous: dict) -> list[dict]:
        carried = [entry for entry in previous["individuals"] if entry["origin"] == "carried"
                   and entry["state"] == "scored"]
        others = sorted((entry for entry in previous["individuals"] if entry["origin"] != "carried"
                         and entry["state"] == "scored"), key=lambda entry: entry["pick_index"])
        return [*carried, *others]

    def tournament(self, pool: list[dict]) -> dict:
        chosen = self._sample(pool, min(self.ga["tournament_size"], len(pool)))
        return min(chosen, key=self.order_key)

    # ---- selection
    def draw(self) -> tuple[int, ...] | None:
        for _ in range(DRAW_RETRIES + 1):
            size = self._randint(1, self.max_mutations)
            chosen = sorted(self._sample(self.positions, size), key=self.positions.index)
            key = tuple(sorted(self._choice(self.alts[position]) for position in chosen))
            if key not in self.seen:
                return key
        for key in self.canonical:
            if key not in self.seen:
                return key
        return None

    def crossover(self, pool: list[dict]) -> tuple[tuple[int, ...] | None, dict]:
        a = self.tournament(pool)
        b = self.tournament(pool)
        distinct = len({key_text(entry["key"]) for entry in pool}) > 1
        for _ in range(B_RETRIES):
            if a["key"] != b["key"] or not distinct:
                break
            b = self.tournament(pool)
        if a["key"] == b["key"]:
            return self.edit(pool, parent=a)         # spec 3 (c): the slot becomes an edit slot on A
        first = {self.position_of[index]: index for index in a["key"]}
        second = {self.position_of[index]: index for index in b["key"]}
        child: list[int] = []
        for position in self.positions:
            if position in first and position in second:
                if first[position] == second[position]:
                    child.append(first[position])
                else:
                    child.append(self._choice([first[position], second[position]]))
            elif (position in first or position in second) and self._random() < 0.5:
                child.append(first.get(position, second.get(position)))
        if not child:
            union = []
            for position in self.positions:
                for index in (first.get(position), second.get(position)):
                    if index is not None and index not in union:
                        union.append(index)
            child = [self._choice(union)]
        if len(child) > self.max_mutations:
            child = self._sample(child, self.max_mutations)
        return tuple(sorted(child)), {"origin": "crossover", "parents": [key_text(a["key"]), key_text(b["key"])],
                                      "edit_op": None}

    def edit(self, pool: list[dict], parent: dict | None = None) -> tuple[tuple[int, ...] | None, dict]:
        parent = parent if parent is not None else self.tournament(pool)
        used = {self.position_of[index]: index for index in parent["key"]}
        unused = [position for position in self.positions if position not in used]
        changeable = [index for index in parent["key"] if len(self.alts[self.position_of[index]]) > 1]
        operations = []
        if len(parent["key"]) < self.max_mutations and unused:
            operations.append("add")
        if changeable:
            operations.append("change")
        if unused:
            operations.append("move")
        if len(parent["key"]) > 1:
            operations.append("remove")
        if not operations:
            return None, {"origin": "random", "parents": None, "edit_op": None}
        operation = self._choice(operations)
        child = list(parent["key"])
        if operation == "add":
            position = self._choice(unused)
            child.append(self._choice(self.alts[position]))
        elif operation == "change":
            target = self._choice(changeable)
            others = [index for index in self.alts[self.position_of[target]] if index != target]
            child = [index for index in child if index != target] + [self._choice(others)]
        elif operation == "move":
            target = self._choice(list(parent["key"]))
            position = self._choice(unused)
            child = [index for index in child if index != target] + [self._choice(self.alts[position])]
        else:
            target = self._choice(list(parent["key"]))
            child = [index for index in child if index != target]
        return tuple(sorted(child)), {"origin": "edit", "parents": [key_text(parent["key"])], "edit_op": operation}

    def select(self, kind: str, pool: list[dict]) -> dict | None:
        """One slot. ``None`` when no unseen key could be selected (A4)."""
        if len(self.seen) >= self.size:
            return None
        if kind in ("crossover", "edit") and pool:
            for _ in range(CHILD_RETRIES + 1):
                key, info = self.crossover(pool) if kind == "crossover" else self.edit(pool)
                if key is None:                       # edit found no operation: a random slot
                    break
                if key not in self.seen:
                    return self._entry(key, info)
            kind = "random"
        elif kind in ("crossover", "edit"):
            kind = "random"                           # spec 3 (g): no scored individual
        key = self.draw()
        if key is None:
            return None
        return self._entry(key, {"origin": "random", "parents": None, "edit_op": None})

    def _entry(self, key: tuple[int, ...], info: dict) -> dict:
        self.seen.add(key)
        entry = {"key": key, "origin": info["origin"], "parents": info["parents"], "edit_op": info["edit_op"],
                 "evaluation": None, "pick_index": self.pick, "eval_index": None, "state": None,
                 "reason_code": None, "score": None}
        self.pick += 1
        return entry

    # ---- evaluation
    def row(self, key: str) -> dict:
        row = self.scores[key]
        return {"state": row["state"], "reason_code": row.get("reason_code"), "score": row.get("score")}

    def evaluate(self, entry: dict) -> str | None:
        text = key_text(entry["key"])
        if text in self.reusable:
            entry["evaluation"] = "reused"
            self.reused += 1
        else:
            if self.new >= self.reserved:
                return "evaluation_limit"
            entry["evaluation"] = "computed"
            entry["eval_index"] = self.eval_index
            self.new += 1
            self.eval_index += 1
        entry.update(self.row(text))
        if entry["state"] == "failed":
            self.failures += 1
            if self.failures >= CONSECUTIVE_FAILURE_LIMIT:
                return "repeated_failure"
        else:
            self.failures = 0
        return None

    # ---- the run
    def result(self) -> dict:
        reference = {"evaluation": "reused" if "wild_type" in self.reusable else "computed",
                     **self.row("wild_type")}
        if reference["state"] == "failed":
            return self._finish("reference_failed", reference, 0)
        stop = None
        done = 0
        best = None
        still = 0
        for generation in range(1, self.ga["generations"] + 1):
            carried: list[dict] = []
            if generation == 1:
                kinds = ["random"] * self.ga["population_size"]
                pool: list[dict] = []
            else:
                previous = self.generations[-1]
                ranked = sorted(self.scored(previous["individuals"]), key=self.order_key)
                carried = [{**entry, "origin": "carried", "parents": None, "edit_op": None, "evaluation": None,
                            "eval_index": None} for entry in ranked[:self.ga["elite_count"]]]
                counts = slot_counts(self.ga["population_size"], len(carried), self.ga["crossover_fraction"],
                                     self.ga["random_fraction"])
                kinds = (["crossover"] * counts["crossover"] + ["edit"] * counts["edit"] +
                         ["random"] * counts["random"])
                pool = self.pool(previous)
            chosen = []
            for kind in kinds:
                entry = self.select(kind, pool)
                if entry is None:
                    break
                chosen.append(entry)
            if generation > 1 and not chosen:
                stop = "space_exhausted"
                break
            individuals = list(carried)
            for entry in chosen:
                stop = self.evaluate(entry)
                if stop == "evaluation_limit":
                    break
                individuals.append(entry)
                if stop == "repeated_failure":
                    break
            if stop:
                self.generations.append(self._generation(generation, individuals, False))
                break
            self.generations.append(self._generation(generation, individuals, True))
            done = generation
            low = self.generations[-1]["min_score"]
            new_best = best if low is None else (low if best is None else min(best, low))
            if generation >= 2:
                still = 0 if (new_best is not None and (best is None or new_best < best)) else still + 1
            best = new_best
            if generation == self.ga["generations"]:
                stop = "generations_complete"
                break
            if len(self.seen) >= self.size:
                stop = "space_exhausted"
                break
            if generation >= 2 and still >= self.ga["patience"]:
                stop = "no_change"
                break
        return self._finish(stop, reference, done)

    def _generation(self, index: int, individuals: list[dict], complete: bool) -> dict:
        values = [entry["score"] for entry in individuals if entry["state"] == "scored"]
        return {"index": index, "complete": complete, "individuals": individuals,
                "min_score": min(values) if values else None, "max_score": max(values) if values else None}

    def _finish(self, stop: str | None, reference: dict, done: int) -> dict:
        complete = {"generations_complete", "no_change", "space_exhausted"}
        for record in self.generations:    # keys are tuples while the run builds; the result names them as text
            record["individuals"] = [{**entry, "key": key_text(entry["key"])} for entry in record["individuals"]]
        return {"stop_reason": stop, "status": "complete" if stop in complete else "partial",
                "generations_done": done, "new_evaluations_used": self.new, "reused_count": self.reused,
                "reserved_evaluations": self.reserved, "reserved_units": reserved_units(self.ga),
                "space": {"positions": len(self.positions),
                          "candidates": sum(len(self.alts[p]) for p in self.positions),
                          "effective_max_mutations": self.max_mutations, "size": self.size},
                "reference": reference, "generations": self.generations, "rng_calls": self.calls}


def _log(values: list) -> list:
    return [key_text(item["key"]) if isinstance(item, dict) else item for item in values]


def run_ga(space: dict, scores: dict, reusable: list[str], ga: dict) -> dict:
    return Run(space, scores, reusable, ga).result()


def check(document: dict) -> list[str]:
    bad = []
    for name, vector in document["vectors"].items():
        space = document["spaces"][vector["space"]]
        got = run_ga(space, vector["scores"], vector.get("reusable", []), vector["ga"])
        if json.loads(json.dumps(got)) != vector["expected"]:
            bad.append(f"vectors.{name}")
    for row in document["arithmetic"]["space_size"]:
        # ``elementary`` holds e_1 .. e_m for the first m of them (the 400-position row keeps only four).
        if (space_size(row["counts"], row["max_mutations"]) != row["size"] or
                [elementary(row["counts"], k) for k in range(1, len(row["elementary"]) + 1)] != row["elementary"]):
            bad.append(f"space_size {len(row['counts'])} positions, max_mutations {row['max_mutations']}")
    for row in document["arithmetic"]["slot_counts"]:
        if slot_counts(row["population_size"], row["carried"], row["crossover_fraction"],
                       row["random_fraction"]) != row["counts"]:
            bad.append(f"slot_counts {row}")
    for row in document["arithmetic"]["reservation"]:
        if (reserved_evaluations(row["ga"]) != row["reserved_evaluations"] or
                reserved_units(row["ga"]) != row["reserved_units"] or
                wall_clock_s(row["ga"]) != row["wall_clock_s"] or
                full_run_may_be_partial(row["ga"]) != row["full_run_may_be_partial"]):
            bad.append(f"reservation {row['name']}")
    for name, space in document["spaces"].items():
        positions = [int(p) for p in space["positions"]]
        alts = {position: space["alts"][str(position)] for position in positions}
        cap = space["max_mutations_cap"]
        if space_size([len(alts[p]) for p in positions], cap) != space["size_at_cap"]:
            bad.append(f"spaces.{name}")
        if [key_text(key) for key in canonical_order(positions, alts, cap)] != space["canonical_at_cap"]:
            bad.append(f"spaces.{name}.canonical")
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
