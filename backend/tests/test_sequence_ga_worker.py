"""M23 T4: the GA worker ``mw/jobs/sequence_ga_worker.py``.

Two kinds of tests.

Selection logic (the server test interpreter loads the worker module by file path; its GA part imports only the
standard library and the dependency-free ``sequence_ga_constants.py``): the GA is run with an injected scripted
environment whose evaluations return a vector's score table, and every path is compared with the INDEPENDENT T1
oracle (``fixtures/sequence_ga/independent_sequence_ga_oracle.py``, standard library only, written before this worker)
through its committed ``expected.json``: generation records, states, scores, stops, counts and every rng call with its
population and result. Score tables marked synthetic there are selection-logic inputs, never engine values.

Real engines (the worker in its pinned ``.deps/docking/venv-locked`` interpreter as ``python -I
sequence_ga_worker.py`` in a private directory; each new evaluation runs the real modeling child with the project
``.venv`` interpreter and the real ``qvina2``; a missing environment FAILS, never skips): public 1UBQ (not
experimental validation of anything here) with the real tiny M20 set of ``fixtures/sequence_ga`` and the labeled
synthetic phenol SDF. References: the oracle fed with the observed engine scores, a standalone M18
``docking_worker.py`` job on the same stored model (sidecar rebuilt with the server's ``docking_inputs`` functions),
the T2 server validator ``sequence_model_bundle.validated_model`` and the T1 observed first-mode table. Clocks, caps
and the modeling program path are changed only here, by loading the worker by path and assigning its module
constants before ``entry`` (no request field, no environment variable). Labeled stand-in modeling programs
(``SYNTHETIC`` failure injection) run the real program for every case they do not fail.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import random
import types
from collections import Counter
from pathlib import Path

import pytest

from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend/mw/jobs/sequence_ga_worker.py"
GA_FIX = Path(__file__).parent / "fixtures/sequence_ga"
EXPECTED = json.loads((GA_FIX / "expected.json").read_text())
VECTORS = EXPECTED["vectors"]
RECORD_KEYS = ("key", "origin", "parents", "edit_op", "evaluation", "pick_index", "eval_index")
ENTRY_KEYS = (*RECORD_KEYS, "state", "reason_code", "score")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SGW = _load(WORKER, "sequence_ga_worker_under_test")
ORACLE = _load(GA_FIX / "independent_sequence_ga_oracle.py", "independent_sequence_ga_oracle_t4")


# ------------------------------------------------------------------ selection logic: helpers
class Recording(random.Random):
    """``random.Random`` that logs every call in the oracle's ``rng_calls`` shape. ``getrandbits`` is defined so that
    ``Random.__init_subclass__`` keeps the getrandbits-based ``_randbelow`` (a subclass overriding only ``random()``
    gets the other algorithm and a different stream)."""

    def __init__(self, seed: int) -> None:
        super().__init__(seed)
        self.calls: list[dict] = []

    def getrandbits(self, k):
        return super().getrandbits(k)

    @staticmethod
    def _log(value):
        return SGW.key_text(value["key"]) if isinstance(value, dict) else value

    def randint(self, a, b):
        got = super().randint(a, b)
        self.calls.append({"call": "randint", "low": a, "high": b, "result": got})
        return got

    def random(self):
        got = super().random()
        self.calls.append({"call": "random", "result_lt_half": got < 0.5})
        return got

    def sample(self, population, k):
        got = super().sample(population, k)
        self.calls.append({"call": "sample", "population": [self._log(x) for x in population], "k": k,
                           "result": [self._log(x) for x in got]})
        return got

    def choice(self, population):
        got = super().choice(population)
        self.calls.append({"call": "choice", "population": [self._log(x) for x in population],
                           "result": self._log(got)})
        return got


class Script:
    """A scripted GA environment: evaluations come from a score table (``SYNTHETIC`` unless the vector says it
    holds observed engine values); optional stops are injected at chosen points."""

    def __init__(self, scores: dict, *, cancel_at: int | None = None, time_at: int | None = None,
                 full_at: int | None = None, stop_in: tuple[int, str] | None = None) -> None:
        self.scores = scores
        self.checks = 0                          # individual / reference checks so far
        self.cancel_at, self.time_at, self.full_at, self.stop_in = cancel_at, time_at, full_at, stop_in
        self.evaluated: list[tuple[str, int]] = []
        self.references: list = []
        self.records: dict[int, tuple[bool, list[dict]]] = {}
        self.writes = 0

    def _row(self, text: str) -> tuple:
        row = self.scores[text]
        return row["state"], row["reason_code"], row["score"]

    def cancelled(self) -> bool:
        self.checks += 1
        return self.cancel_at is not None and self.checks >= self.cancel_at

    def time_up(self) -> bool:
        return self.time_at is not None and self.checks >= self.time_at

    def output_full(self) -> bool:
        return self.full_at is not None and self.checks >= self.full_at

    def reference(self, reused):
        self.references.append(reused)
        return self._row(SC.REFERENCE_KEY)

    def evaluate(self, key, index):
        text = SGW.key_text(key)
        self.evaluated.append((text, index))
        if self.stop_in is not None and len(self.evaluated) == self.stop_in[0]:
            return self.stop_in[1]
        return self._row(text)

    def record(self, index: int, complete: bool, entries: list) -> None:
        self.writes += 1
        self.records[index] = (complete, [{k: (SGW.key_text(e[k]) if k == "key" else e[k]) for k in ENTRY_KEYS}
                                          for e in entries])


def _space(name: str) -> tuple[list[int], dict[int, list[int]]]:
    space = EXPECTED["spaces"][name]
    positions = [int(p) for p in space["positions"]]
    return positions, {p: list(space["alts"][str(p)]) for p in positions}


def _ga(vector: dict, monkeypatch, **changes):
    """(Ga, Script) for a vector; the worker's rng is a recording ``random.Random`` with the same seed."""
    monkeypatch.setattr(SGW, "random", types.SimpleNamespace(Random=Recording))
    positions, alts = _space(vector["space"])
    scores = vector["scores"]
    reusable = vector.get("reusable", [])
    reused = {k: {"state": scores[k]["state"], "score": scores[k]["score"]} for k in reusable if k != "wild_type"}
    reference = ({"state": scores["wild_type"]["state"], "score": scores["wild_type"]["score"]}
                 if "wild_type" in reusable else None)
    ga = SGW.Ga(positions, alts, {**vector["ga"], **changes.pop("ga", {})}, reused, reference)
    return ga, Script(scores, **changes)


def _generations(script: Script) -> list[dict]:
    out = []
    for index in sorted(script.records):
        complete, entries = script.records[index]
        values = [e["score"] for e in entries if e["state"] == "scored"]
        out.append({"index": index, "complete": complete, "individuals": entries,
                    "min_score": min(values) if values else None, "max_score": max(values) if values else None})
    return out


def _path(ga, script: Script, stop: str, done: int) -> dict:
    return {"stop_reason": stop, "generations_done": done, "new_evaluations_used": ga.new,
            "reused_count": ga.reused_count, "reserved_evaluations": ga.reserved, "reference": ga.reference,
            "generations": _generations(script)}


def _expected_path(expected: dict) -> dict:
    return {key: expected[key] for key in ("stop_reason", "generations_done", "new_evaluations_used", "reused_count",
                                           "reserved_evaluations", "reference", "generations")}


# ------------------------------------------------------------------ selection logic against every oracle vector
@pytest.mark.parametrize("name", sorted(VECTORS))
def test_every_oracle_vector_path_and_rng_calls(name, monkeypatch):
    vector = VECTORS[name]
    ga, script = _ga(vector, monkeypatch)
    stop, done = ga.run(script)
    expected = vector["expected"]
    assert _path(ga, script, stop, done) == _expected_path(expected)
    assert ga.rng.calls == expected["rng_calls"], name
    assert ga.size == expected["space"]["size"] and ga.cap == expected["space"]["effective_max_mutations"]
    computed = [(e["key"], e["eval_index"]) for g in expected["generations"] for e in g["individuals"]
                if e["evaluation"] == "computed"]
    assert script.evaluated == computed, "the environment evaluates exactly the computed individuals, in order"
    assert len(script.references) == 1 and (script.references[0] is None) == ("wild_type" not in vector["reusable"])


def test_the_vectors_cover_every_procedure_stop_and_branch():
    stops = {vector["expected"]["stop_reason"] for vector in VECTORS.values()}
    assert stops == {"generations_complete", "no_change", "space_exhausted", "evaluation_limit", "reference_failed",
                     "repeated_failure"}
    origins, ops, calls = Counter(), Counter(), Counter()
    for vector in VECTORS.values():
        for g in vector["expected"]["generations"]:
            for e in g["individuals"]:
                origins[e["origin"]] += 1
                ops[e["edit_op"]] += 1
        calls.update(c["call"] for c in vector["expected"]["rng_calls"])
    assert set(origins) == set(SC.ORIGINS) and set(ops) == {None, *SC.EDIT_OPERATIONS}
    assert set(calls) == {"randint", "random", "sample", "choice"}
    states = {e["state"] for v in VECTORS.values() for g in v["expected"]["generations"] for e in g["individuals"]}
    assert states == set(SC.STATES)
    assert any(v["expected"]["reused_count"] for v in VECTORS.values())


def _evaluated(expected: dict) -> list[tuple[int, int]]:
    """(generation number, position in the generation) of every non-carried entry in evaluation order."""
    return [(g["index"], slot) for g in expected["generations"] for slot, e in enumerate(g["individuals"])
            if e["origin"] != "carried"]


def _truncated(expected: dict, evaluated: int) -> list[dict]:
    """The oracle generations of a run stopped right before its ``evaluated``-th evaluated entry (0-based)."""
    where = _evaluated(expected)[evaluated]
    out = []
    for g in expected["generations"]:
        if g["index"] < where[0]:
            out.append(g)
        elif g["index"] == where[0]:
            entries = g["individuals"][:where[1]]
            values = [e["score"] for e in entries if e["state"] == "scored"]
            out.append({**g, "complete": False, "individuals": entries,
                        "min_score": min(values) if values else None, "max_score": max(values) if values else None})
    return out


@pytest.mark.parametrize("stop", ["cancelled", "time_exhausted", "resource_exceeded", "interrupted"])
def test_an_outside_stop_keeps_the_evaluated_individuals_and_the_partial_generation(stop, monkeypatch):
    """s1_reuse: the fourth checked individual (a computed one) is stopped. Reused individuals never trigger the
    output check (they write nothing); an interruption inside an evaluation drops only that individual."""
    vector = VECTORS["s1_reuse"]
    expected = vector["expected"]
    order = [e for g in expected["generations"] for e in g["individuals"] if e["origin"] != "carried"]
    target = next(i for i, e in enumerate(order) if i >= 3 and e["evaluation"] == "computed")
    checks = target + 2                                       # the reference row is check 1
    kwargs = {"cancelled": {"cancel_at": checks}, "time_exhausted": {"time_at": checks},
              "resource_exceeded": {"full_at": 2},             # every new evaluation after the reference row
              "interrupted": {"stop_in": (sum(e["evaluation"] == "computed" for e in order[:target]) + 1,
                                          "time_exhausted")}}[stop]
    ga, script = _ga(vector, monkeypatch, **kwargs)
    got, done = ga.run(script)
    if stop == "resource_exceeded":
        target = next(i for i, e in enumerate(order) if e["evaluation"] == "computed")
    assert got == ("time_exhausted" if stop == "interrupted" else stop)
    generations = _generations(script)
    assert generations == _truncated(expected, target)
    assert done == sum(g["complete"] for g in generations)
    assert ga.new == sum(e["evaluation"] == "computed" for e in order[:target])


def test_stops_before_and_at_the_reference_row(monkeypatch):
    vector = VECTORS["s1_basic"]
    for kwargs, stop in (({"cancel_at": 1}, "cancelled"), ({"time_at": 1}, "time_exhausted"),
                         ({"full_at": 1}, "resource_exceeded")):
        ga, script = _ga(vector, monkeypatch, **kwargs)
        assert ga.run(script) == (stop, 0) and script.references == [] and script.records == {}
        assert ga.rng.calls == [] and ga.reference is None
    reused = copy.deepcopy(vector)
    reused["reusable"] = ["wild_type"]
    ga, script = _ga(reused, monkeypatch, full_at=1)      # a reused reference row writes no output: no check
    assert ga.run(script) == ("resource_exceeded", 0)    # the first (computed) individual is checked
    row = vector["scores"]["wild_type"]
    assert script.references == [{"state": row["state"], "score": row["score"]}]
    assert ga.reference == {"evaluation": "reused", "state": row["state"], "reason_code": None, "score": row["score"]}
    assert script.records == {1: (False, [])}


def test_a_stop_before_the_first_individual_of_a_generation_lists_only_the_carried(monkeypatch):
    vector = VECTORS["s1_basic"]
    expected = vector["expected"]
    first_g2 = _evaluated(expected).index((2, 1))           # generation 2 = carried + three new individuals
    ga, script = _ga(vector, monkeypatch, time_at=first_g2 + 2)
    assert ga.run(script) == ("time_exhausted", 1)
    generations = _generations(script)
    assert generations == _truncated(expected, first_g2)
    assert [e["origin"] for e in generations[1]["individuals"]] == ["carried"]


# ------------------------------------------------------------------ arithmetic and canonical order
def test_canonical_order_space_size_and_reserved_evaluations_match_the_oracle_and_the_server():
    for name, space in EXPECTED["spaces"].items():
        positions, alts = _space(name)
        for cap in range(1, space["max_mutations_cap"] + 1):
            ga = SGW.Ga(positions, alts, {**VECTORS["s1_basic"]["ga"], "max_mutations": cap}, {}, None)
            keys = [SGW.key_text(key) for key in ga.canonical()]
            assert keys == [ORACLE.key_text(k) for k in ORACLE.canonical_order(positions, alts, cap)], (name, cap)
            assert len(keys) == ga.size
        assert ga.size == space["size_at_cap"]
    for row in EXPECTED["arithmetic"]["space_size"]:
        assert SGW.space_size(row["counts"], row["max_mutations"]) == row["size"] == \
            GI.space_size(row["counts"], row["max_mutations"])
    for row in EXPECTED["arithmetic"]["reservation"]:
        assert SGW.reserved_evaluations(row["ga"]) == row["reserved_evaluations"] == GI.reserved_evaluations(row["ga"])
    for row in EXPECTED["arithmetic"]["slot_counts"]:
        assert SGW.slot_counts(row["population_size"], row["carried"], row["crossover_fraction"],
                               row["random_fraction"]) == row["counts"]


def test_canonical_fallback_is_lazy_on_the_largest_space():
    """400 positions x 19 candidates, cap 4 (N about 1.4e14): the first unseen canonical key is found at once."""
    positions = list(range(400))
    alts = {p: list(range(19 * p, 19 * p + 19)) for p in positions}
    ga = SGW.Ga(positions, alts, {**VECTORS["s1_basic"]["ga"], "max_mutations": 4}, {}, None)
    assert ga.size == 137_006_118_184_500
    ga.seen.update({(0,), (1,), (2,)})
    keys = ga.canonical()
    assert [next(keys) for _ in range(3)] == [(0,), (1,), (2,)]
    ga.seen.update((i,) for i in range(19 * 400))
    first_pair = next(key for key in ga.canonical() if key not in ga.seen)
    assert first_pair == (0, 19)                                  # no two candidates of one position


def test_draw_falls_back_to_the_canonical_order_like_the_oracle(monkeypatch):
    """No vector reaches the fallback (51 seen draws in a row), so draw() is compared here with the oracle's own
    ``Run.draw`` on spaces where only improbable keys are unseen: same rng calls, same key."""
    monkeypatch.setattr(SGW, "random", types.SimpleNamespace(Random=Recording))
    space = EXPECTED["spaces"]["s1_4pos_2312"]
    positions, alts = _space("s1_4pos_2312")
    canonical = [tuple(int(i) for i in key.split("-")) for key in space["canonical_at_cap"]]
    cases = {"one_left": [(0, 4, 6)], "two_left": [(2, 5, 7), (1, 4, 7)]}       # unseen keys (size 3)
    fallbacks = 0
    for name, unseen in cases.items():
        seen = [key for key in canonical if key not in unseen]
        for seed in range(40):
            ga_values = {**VECTORS["s1_basic"]["ga"], "seed": seed, "max_mutations": 3}
            ours = SGW.Ga(positions, alts, ga_values, {}, None)
            ours.seen.update(seen)
            oracle = ORACLE.Run(space, {}, [], ga_values)
            oracle.seen.update(seen)
            got = ours.draw()
            assert got == oracle.draw() and got in unseen, (name, seed)
            assert ours.rng.calls == oracle.calls, (name, seed)
            last = max(i for i, call in enumerate(oracle.calls) if call["call"] == "randint")
            last_key = tuple(sorted(call["result"] for call in oracle.calls[last + 2:]))
            if sum(call["call"] == "randint" for call in oracle.calls) == 1 + SC.DRAW_RETRIES and last_key in seen:
                fallbacks += 1
                assert got == min(unseen), "the first unseen key in canonical order, without an rng call"
    assert fallbacks >= 10, "the canonical fallback is exercised"
    full = SGW.Ga(positions, alts, {**VECTORS["s1_basic"]["ga"], "max_mutations": 3}, {}, None)
    full.seen.update(canonical)
    assert full.select("random", []) is None and full.rng.calls == []      # a full space makes no rng call


def test_draw_takes_the_mutation_count_uniformly_first(monkeypatch):
    """Spec 3 draw(): k uniform in 1..M, then positions and substitutions uniform (fixed seed, 30,000 draws)."""
    positions = list(range(12))
    alts = {p: [3 * p, 3 * p + 1, 3 * p + 2] for p in positions}
    ga = SGW.Ga(positions, alts, {**VECTORS["s1_basic"]["ga"], "max_mutations": 3, "seed": 7}, {}, None)
    sizes, firsts = Counter(), Counter()
    for _ in range(30_000):
        key = ga.draw()
        sizes[len(key)] += 1
        if len(key) == 1:
            firsts[ga.position_of[key[0]]] += 1
    assert set(sizes) == {1, 2, 3} and all(abs(sizes[k] / 30_000 - 1 / 3) < 0.02 for k in sizes)
    assert set(firsts) == set(positions) and all(abs(n / sizes[1] - 1 / 12) < 0.02 for n in firsts.values())


# ------------------------------------------------------------------ staged manifest (pure checks)
def _manifest_ok(**changes) -> dict:
    """A shape-valid staged manifest over the tiny set (no engine needed for the pure checks)."""
    tiny = json.loads((GA_FIX / "m20-candidate-set-1ubq-tiny.json").read_text())
    content = tiny["content"]
    rows = [{"index": c["index"], "position_index": c["position_index"],
             "residue": {k: content["positions"][c["position_index"]]["residue"].get(k)
                         for k in ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode",
                                   "resname")},
             "from": c["from"], "to": c["to"], "mutant_resname": {"A": "ALA", "W": "TRP"}[c["to"]]}
            for c in content["candidates"]]
    manifest = {"schema": SC.WORKER_INPUT_SCHEMA, "run_id": "run_m23_golden_keys",
                "project_python": str(ROOT / ".venv/bin/python"), "candidate_set": tiny["handle"],
                "structure": content["structure"], "model_number": 1, "protein": [{"chain": "SYNTHETIC"}],
                "method": {"openmm_version": "SYNTHETIC"},
                "ligand_sdf": {"b64": "", "sha256": "0" * 64},
                "box": {"source": "ligand_range", "margin_A": 8.0},
                "parameters": {"seed": 1, "exhaustiveness": 4, "num_modes": 5, "energy_range": 3.0, "conformers": None},
                "ga": {"seed": 1, "population_size": 4, "generations": 2, "elite_count": 1, "tournament_size": 2,
                       "crossover_fraction": 0.5, "random_fraction": 0.25, "max_mutations": 3, "patience": 2,
                       "max_new_evaluations": 8, "total_s": 600},
                "candidates": rows, "reuse": [], "reference_reuse": None,
                "selection_sha256": "a" * 64, "conditions_sha256": "b" * 64}
    for key, value in changes.items():
        manifest[key] = value
    return manifest


REUSE = {"key": "0-2", "state": "scored", "reason_code": None, "score": -3.6, "model_handle": "obj://r/m/1",
         "result_handle": "obj://r/d/1"}
SUMMARY = {"structure_sha256": "c" * 64, "protonation_variants": [], "disulfide_bonds": []}


def test_a_valid_manifest_gives_the_space_and_the_reuse_facts():
    reference = {**REUSE, "key": "wild_type", "state": "null_result", "score": None, "model_summary": SUMMARY}
    checked = SGW.validate_manifest(_manifest_ok(reuse=[REUSE], reference_reuse=reference))
    assert checked["positions"] == [1, 2, 3] and checked["alts"] == {1: [0, 1], 2: [2, 3], 3: [4, 5]}
    assert checked["reused"] == {"0-2": {"state": "scored", "score": -3.6}}
    assert checked["reference_reused"] == reference


def _bad_candidate(rows):
    rows = copy.deepcopy(rows)
    rows[2]["position_index"] = 0                                   # positions out of storage order
    return rows


BAD_MANIFESTS = {
    "unknown_key": lambda m: m.update(extra=1),
    "schema": lambda m: m.update(schema="sequence_ga_worker_input@2"),
    "project_python_resolved": lambda m: m.update(project_python=str((ROOT / ".venv/bin/python").resolve())),
    "project_python_other": lambda m: m.update(project_python="/usr/bin/python3"),
    "run_id": lambda m: m.update(run_id="../x"),
    "candidate_set_other_run": lambda m: m.update(candidate_set=m["candidate_set"].replace("golden", "other")),
    "structure_kind": lambda m: m["structure"].update(structure_kind="structure"),
    "model_number": lambda m: m.update(model_number=2),
    "method_multi": lambda m: m.update(method={"multi_mutation": "x"}),
    "hash": lambda m: m.update(conditions_sha256="B" * 64),
    "ga_bool": lambda m: m["ga"].update(generations=True),
    "ga_fraction_int": lambda m: m["ga"].update(random_fraction=0),
    "ga_elite": lambda m: m["ga"].update(elite_count=3),
    "ga_max_new": lambda m: m["ga"].update(max_new_evaluations=3),
    "ga_unknown": lambda m: m["ga"].update(mode="x"),
    "space_too_small": lambda m: m["ga"].update(population_size=16, elite_count=0, max_new_evaluations=16,
                                                max_mutations=1),
    "candidate_index": lambda m: m["candidates"][3].update(index=7),
    "candidate_order": lambda m: m.update(candidates=_bad_candidate(m["candidates"])),
    "candidate_same_to": lambda m: m["candidates"][0].update(to="K"),
    "candidate_residue": lambda m: m["candidates"][0]["residue"].pop("icode"),
    "candidate_resname": lambda m: m["candidates"][0].update(mutant_resname="Ala"),
    "instance_box": lambda m: m.update(box={"source": "instance_range", "margin_A": 8.0}),
    "reuse_failed": lambda m: m.update(reuse=[{**REUSE, "state": "failed", "reason_code": "engine_failed",
                                               "score": None}]),
    "reuse_int_score": lambda m: m.update(reuse=[{**REUSE, "score": -3}]),
    "reuse_null_with_score": lambda m: m.update(reuse=[{**REUSE, "state": "null_result"}]),
    "reuse_unknown_candidate": lambda m: m.update(reuse=[{**REUSE, "key": "0-9"}]),
    "reuse_same_position": lambda m: m.update(reuse=[{**REUSE, "key": "0-1"}]),
    "reuse_unsorted_key": lambda m: m.update(reuse=[{**REUSE, "key": "2-0"}]),
    "reuse_duplicate": lambda m: m.update(reuse=[REUSE, REUSE]),
    "reuse_reference_key": lambda m: m.update(reuse=[{**REUSE, "key": "wild_type"}]),
    "reuse_no_handle": lambda m: m.update(reuse=[{**REUSE, "result_handle": None}]),
    "reference_without_summary": lambda m: m.update(reference_reuse={**REUSE, "key": "wild_type"}),
    "reference_key": lambda m: m.update(reference_reuse={**REUSE, "model_summary": SUMMARY}),
    "reference_summary_keys": lambda m: m.update(reference_reuse={**REUSE, "key": "wild_type",
                                                                  "model_summary": {**SUMMARY, "x": 1}}),
}


@pytest.mark.parametrize("name", sorted(BAD_MANIFESTS))
def test_malformed_manifests_are_refused(name):
    manifest = _manifest_ok()
    BAD_MANIFESTS[name](manifest)
    with pytest.raises(ValueError):
        SGW.validate_manifest(manifest)


def test_pure_parts_match_the_server_and_the_modeling_program():
    assert SGW.canonical_json({"b": 1.0, "a": ["é", None]}) == b'{"a":["\xc3\xa9",null],"b":1.0}'
    assert SGW.MODEL_INPUT_SCHEMA == "sequence_model_input@1"
    assert SGW.PROJECT_PYTHON == ROOT / ".venv/bin/python" and SGW.PROJECT_PYTHON.is_symlink()
    assert SGW.MODEL_PROGRAM == ROOT / "backend/mw/jobs/sequence_model_worker.py"
    for text in ("0", "12-57-203", "1-2-3-4"):
        assert SGW.parse_key(text) == GI.parse_key(text)
    for text in ("01", "1-1", "2-1", "1-2-3-4-5", "wild_type", "", "-1"):
        with pytest.raises(ValueError):
            SGW.parse_key(text)
    assert math.isfinite(SGW.STARTED_AT)
    digest = hashlib.sha256(WORKER.read_bytes()).hexdigest()
    assert GI.module_pins()["ga_worker_sha256"] == digest
