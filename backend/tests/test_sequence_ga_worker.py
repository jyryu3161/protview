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

import base64
import copy
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import signal
import subprocess
import time
import types
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

import psutil
import pytest

from mw import docking_constants as C
from mw import docking_inputs
from mw import sequence_ga_constants as SC
from mw import sequence_ga_inputs as GI
from mw import sequence_model_bundle as SB
from mw.mutation_candidates import seven
from mw.mutation_model_constants import THREE_LETTER
from mw.tools.openmm_method import preflight
from mw.workspace import new_run

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


# ================================================================== real engines
PY = ROOT / ".deps/docking/venv-locked/bin/python"
PROJECT_PY = ROOT / ".venv/bin/python"
QVINA = ROOT / ".deps/qvina/env/bin/qvina2"
SINGLE = ROOT / "backend/mw/jobs/docking_worker.py"
PROGRAM = ROOT / "backend/mw/jobs/sequence_model_worker.py"
FIX = Path(__file__).parent / "fixtures"
TINY = json.loads((GA_FIX / "m20-candidate-set-1ubq-tiny.json").read_text())
TINY_SPACE = EXPECTED["spaces"]["s4_tiny_1ubq"]
PHENOL = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
# T1 (g) real qvina first-mode scores of every tiny key and the reference row (s4_tiny_observed's table, OBSERVED
# engine outputs with the values below). Real runs here must give the same values (deterministic engines).
OBSERVED = VECTORS["s4_tiny_observed"]["scores"]
GA1 = VECTORS["s4_tiny_observed"]["ga"]
SMALL = {**GA1, "generations": 2, "max_new_evaluations": 4}
DOCK_VALUES = {"seed": 20261004, "exhaustiveness": 4, "num_modes": 5}     # the T1 (g) docking values
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "OMP_NUM_THREADS": "1",
       "OPENBLAS_NUM_THREADS": "1"}
CONTROL = {"nonce": "0" * 32, "job_id": "job_m23t4", "attempt_id": "att_m23t4"}
LOAD = ("import importlib.util, json, os, sys, time, types\n"
        f"spec = importlib.util.spec_from_file_location('sgw', {str(WORKER)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n")
HANDLE = "obj://run_m23_golden_keys/SYNTHETIC_placeholder/"     # opaque reuse handles (the worker never reads them)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _entry(raw: bytes) -> dict:
    return {"b64": base64.b64encode(raw).decode(), "sha256": _sha(raw)}


def _canonical(raw: bytes):
    data = json.loads(raw)
    assert raw == SGW.canonical_json(data), "canonical JSON"
    return data


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """The staged manifest of the tiny set, built as the server will build it: the M7 preflight projection of public
    1UBQ, the M21 method record, the normalized M18 box and values (``sequence_ga_inputs.individual_arguments``)."""
    for path in (PY, PROJECT_PY, QVINA):
        assert path.is_file(), f"pinned environment missing at {path} (no skip)"
    run = new_run(tmp_path_factory.mktemp("projection"), dry_run=False, run_id="run_m23_t4_projection")
    source = run.call("load_structure", {"source": "public_1ubq.cif", "model_index": 0},
                      source_bytes=(FIX / "public_1ubq.cif").read_bytes(), source_format="cif")
    prepared = run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                              "waters": "strip_all", "hydrogens": "strip",
                                              "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
    selected = preflight(run.store, prepared.handle, seed=run.seed)
    content = TINY["content"]
    run_id = TINY["handle"].split("/")[2]
    args = {"candidate_set": TINY["handle"], "ligand": {"source": "sdf", "sdf_handle": f"obj://{run_id}/x/" + "1" * 64},
            "box": {"source": "ligand_range", "margin_A": 8}, "parameters": DOCK_VALUES,
            "selection_policy": SC.SELECTION_POLICY, "hydrogen_policy": SC.HYDROGEN_POLICY,
            "acknowledgement": {key: True for key in C.ACKNOWLEDGEMENT_KEYS}, "ga": GA1}
    normalized = GI.validate_arguments(args, GA1["total_s"] + SC.FINISH_MARGIN_S)
    normalized["box"] = GI.request_box(normalized["box"])
    m18 = GI.individual_arguments(normalized, f"obj://{run_id}/{SC.MODEL_KIND}/" + "2" * 64, SC.MUTANT_SIDE)
    candidates = [{"index": c["index"], "position_index": c["position_index"],
                   "residue": seven(content["positions"][c["position_index"]]["residue"]), "from": c["from"],
                   "to": c["to"], "mutant_resname": THREE_LETTER[c["to"]]} for c in content["candidates"]]
    base = {"schema": SC.WORKER_INPUT_SCHEMA, "run_id": run_id, "project_python": str(PROJECT_PY),
            "candidate_set": TINY["handle"], "structure": content["structure"],
            "model_number": selected["model_number"], "protein": selected["protein"],
            "method": {**selected["method"], "pdbfixer_version": version("pdbfixer")}, "ligand_sdf": _entry(PHENOL),
            "box": m18["box"], "parameters": m18["parameters"], "ga": normalized["ga"], "candidates": candidates,
            "reuse": [], "reference_reuse": None, "selection_sha256": "a" * 64, "conditions_sha256": "b" * 64}
    return {"base": base, "run_id": run_id}


def _stage(root: Path, manifest: dict, adapter: str = SC.PROTOCOL, control: dict | None = None) -> None:
    root.mkdir(parents=True)
    raw = SGW.canonical_json(manifest)
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps({**CONTROL, "adapter": adapter, "input_sha256": _sha(raw),
                                                 **(control or {})}))


def _argv(patch: str | None) -> list[str]:
    if patch is None:
        return [str(PY), "-I", str(WORKER)]
    return [str(PY), "-I", "-c", LOAD + patch + "\nraise SystemExit(m.entry([]))\n"]


def _popen(root: Path, manifest: dict, patch: str | None = None, **control) -> subprocess.Popen:
    _stage(root, manifest, control=control or None)
    return subprocess.Popen(_argv(patch), cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**ENV, "TMPDIR": str(root)}, start_new_session=True)


def _dir(root: Path, name: str) -> dict[str, bytes]:
    folder = root / name
    return {} if not folder.is_dir() else {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


class Out:
    def __init__(self, root: Path, code: int, stderr: bytes = b"") -> None:
        self.root, self.code, self.stderr = root, code, stderr
        self.files = _dir(root, "individuals")
        self.gens = {int(name[:-5]): _canonical(raw) for name, raw in _dir(root, "generations").items()}
        self.result = _canonical((root / "result.json").read_bytes()) if (root / "result.json").exists() else None
        self.error = json.loads((root / "error.json").read_bytes()) if (root / "error.json").exists() else None
        self.reference = {p.name: p.read_bytes() for p in sorted(root.glob("reference.*"))}
        self.prepared = _canonical((root / "prepared.json").read_bytes()) if (root / "prepared.json").exists() \
            else None

    def status(self, prefix: str) -> list:
        raw = self.reference["reference.status.json"] if prefix == "reference" else self.files[f"{prefix}.status.json"]
        data = _canonical(raw)
        assert set(data) == {"state", "reason_code", "stage"}
        return [data["state"], data["reason_code"], data["stage"]]

    def result_bytes(self, prefix) -> bytes | None:
        name = f"{prefix}.result.json"
        return self.reference.get(name) if prefix == "reference" else self.files.get(name)

    def score(self, prefix) -> float | None:
        raw = self.result_bytes(prefix)
        modes = json.loads(raw)["modes"] if raw is not None else []
        return modes[0]["score_kcal_mol"] if modes else None

    def records(self) -> list[dict]:
        return [self.gens[g] for g in sorted(self.gens)]

    def computed(self) -> dict[str, int]:
        return {e["key"]: e["eval_index"] for g in self.records() for e in g["individuals"]
                if e["evaluation"] == "computed"}

    def all_bytes(self) -> dict[str, bytes]:
        out = {f"individuals/{k}": v for k, v in self.files.items()}
        out.update({f"generations/{k}": v for k, v in _dir(self.root, "generations").items()})
        out.update(self.reference)
        for name in ("prepared.json", "result.json"):
            out[name] = (self.root / name).read_bytes()
        return out


def _finish(proc: subprocess.Popen, root: Path, timeout: float = 900) -> Out:
    stdout, stderr = proc.communicate(timeout=timeout)
    assert stdout == b"" and len(stderr) < 64_000, stderr[-2000:]
    assert not (root / "model_work").exists(), "the modeling folder is removed"
    assert not list(root.glob("**/*.tmp")), "no torn temporary file"
    return Out(root, proc.returncode, stderr)


def _run_all(runs: dict[str, tuple[Path, dict, str | None]]) -> dict[str, Out]:
    """Launch every staged run at once (each worker uses one CPU), then collect them."""
    procs = {name: (_popen(root, manifest, patch), root) for name, (root, manifest, patch) in runs.items()}
    with ThreadPoolExecutor(max_workers=len(procs)) as pool:
        return dict(zip(procs, pool.map(lambda item: _finish(*item), procs.values()), strict=True))


def _expected_records(expected: dict) -> list[dict]:
    return [{"index": g["index"], "complete": g["complete"],
             "individuals": [{key: e[key] for key in RECORD_KEYS} for e in g["individuals"]]}
            for g in expected["generations"]]


def _oracle(ga: dict, table: dict, reusable=()) -> dict:
    return ORACLE.run_ga(TINY_SPACE, table, list(reusable), ga)


def _result(stop: str, done: int) -> dict:
    return {"schema": SC.WORKER_OUTPUT_SCHEMA, "protocol": SC.PROTOCOL, "job_id": CONTROL["job_id"],
            "attempt_id": CONTROL["attempt_id"], "stop_reason": stop, "generations_done": done}


def _assert_path(out: Out, expected: dict, *, stages: dict | None = None) -> None:
    """Worker records, stop, reference row and individual files agree with an oracle path."""
    assert out.code == 0 and out.error is None, (out.error, out.stderr[-2000:])
    assert out.result == _result(expected["stop_reason"], expected["generations_done"])
    assert out.records() == _expected_records(expected)
    reference = expected["reference"]
    assert out.status("reference")[:2] == [reference["state"], reference["reason_code"]]
    if reference["evaluation"] == "reused":
        assert list(out.reference) == ["reference.status.json"]
    else:
        assert out.score("reference") == reference["score"]
    computed = [e for g in expected["generations"] for e in g["individuals"] if e["evaluation"] == "computed"]
    for e in computed:
        k = e["eval_index"]
        assert out.files[f"{k}.started"] == b""
        state, reason, stage = out.status(str(k))
        assert [state, reason] == [e["state"], e["reason_code"]] and out.score(str(k)) == e["score"], (k, e)
        assert stage == (stages or {}).get(e["key"], "docking")
        assert (f"{k}.model.json" in out.files) == (stage == "docking")
        assert (f"{k}.result.json" in out.files) == (state != "failed")
    assert sum(name.endswith(".started") for name in out.files) == len(computed) == expected["new_evaluations_used"]
    assert sum(name.endswith(".status.json") for name in out.files) == len(computed)


def _engines_under(root: Path) -> list[int]:
    """Live qvina2 / modeling children whose working directory is under ``root``."""
    found = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if str(root) in proc.cwd() and proc.pid != os.getpid() and proc.status() != psutil.STATUS_ZOMBIE:
                found.append(proc.pid)
        except (psutil.Error, OSError):
            continue
    return found


def _reuse(first: Out) -> tuple[list[dict], dict]:
    """The reuse index and the reference reuse fact of a finished run (handles are opaque placeholders)."""
    records = []
    for key, k in first.computed().items():
        state = first.status(str(k))[0]
        records.append({"key": key, "state": state, "reason_code": None, "score": first.score(str(k)),
                        "model_handle": f"{HANDLE}model_{k}", "result_handle": f"{HANDLE}result_{k}"})
    model = json.loads(first.reference["reference.model.json"])["structures"][SC.REFERENCE_SIDE]
    reference = {"key": SC.REFERENCE_KEY, "state": first.status("reference")[0], "reason_code": None,
                 "score": first.score("reference"), "model_handle": f"{HANDLE}model_reference",
                 "result_handle": f"{HANDLE}result_reference",
                 "model_summary": {k: model[k] for k in ("structure_sha256", "protonation_variants", "disulfide_bonds")}}
    return records, reference


# ------------------------------------------------------------------ the first real run (and its repeat)
@pytest.fixture(scope="module")
def first(world, tmp_path_factory):
    """s4_tiny_observed for real: the reference row and ten new evaluations, twice in parallel."""
    root = tmp_path_factory.mktemp("first")
    return _run_all({"run": (root / "run", world["base"], None), "again": (root / "again", world["base"], None)})


def test_real_run_follows_the_oracle_on_the_t1_observed_scores(first):
    out = first["run"]
    expected = VECTORS["s4_tiny_observed"]["expected"]
    _assert_path(out, _oracle(GA1, OBSERVED))
    assert out.result["stop_reason"] == expected["stop_reason"] and len(out.computed()) == 10
    reference = json.loads(out.reference["reference.result.json"])
    assert out.prepared == {"box": reference["box"], "engine": reference["engine"],
                            "model_method": {**json.loads(out.reference["reference.model.json"])["method"]}}
    assert out.prepared["model_method"]["multi_mutation"] == "sequential_structure_order_round4"


def test_same_ga_seed_and_inputs_give_the_same_bytes(first):
    assert first["run"].all_bytes() == first["again"].all_bytes()


def test_each_result_is_the_standalone_m18_job_on_the_stored_model(world, first, tmp_path):
    """The stored model bytes become an M18 receptor the way the server builds one (``docking_inputs`` sidecar);
    a standalone ``docking_worker.py`` job on it gives byte-identical output. Every stored model passes the T2
    server validator, and the server's reuse fact of each stored result is the worker's state and score."""
    out = first["run"]
    candidate_set = TINY["content"]
    reference_model = json.loads(out.reference["reference.model.json"])
    common = {"run_id": world["run_id"], "candidate_set_handle": TINY["handle"], "candidate_set": candidate_set}
    assert SB.validated_model(reference_model, structure_cif=out.reference["reference.model.cif"], **common)
    prefixes = {"reference": "reference"} | {key: str(k) for key, k in out.computed().items()}
    for key, prefix in prefixes.items():
        raw = out.reference if prefix == "reference" else out.files
        name = "reference." if prefix == "reference" else f"{prefix}."
        model, cif = json.loads(raw[name + "model.json"]), raw[name + "model.cif"]
        if prefix != "reference":
            assert SB.validated_model(model, structure_cif=cif, reference=reference_model, **common) == model
            assert model["mutations"] == SB.model_mutations(candidate_set, key)
        result = json.loads(out.result_bytes(prefix))
        fact = GI.reuse_record(key if key != "reference" else "wild_type", model_handle="m", result_handle="r",
                               result=result)
        assert [fact["state"], fact["score"]] == [out.status(prefix)[0], out.score(prefix)]
    checks = {}
    for key in ("reference", max(out.computed(), key=len)):
        prefix = prefixes[key]
        raw = out.reference if prefix == "reference" else out.files
        name = "reference." if prefix == "reference" else f"{prefix}."
        model, cif = json.loads(raw[name + "model.json"]), raw[name + "model.cif"]
        (side,) = model["structures"]
        entry = model["structures"][side]
        handle = entry["structure_object"]
        rows = docking_inputs.receptor_rows(cif, "cif", handle, world["base"]["model_number"])
        sidecar = docking_inputs.mutation_model_sidecar(rows, entry["atom_mapping"], entry["final_bonds"], handle)
        payload = {"schema": "docking_worker_input@1",
                   "receptor": {"handle": handle, "format": "cif", "bytes": _entry(cif),
                                "model_number": world["base"]["model_number"],
                                "connectivity": {"kind": "sidecar", "sidecar": _entry(sidecar)}, "instance": None,
                                "source": "mutation_model"},
                   "ligand": {"source": "sdf", "sdf": _entry(PHENOL)}, "mode": "free",
                   "box": world["base"]["box"], "parameters": world["base"]["parameters"]}
        root = tmp_path / prefix
        _stage(root, payload, adapter=C.PROTOCOL)
        checks[key] = (subprocess.Popen([str(PY), "-I", str(SINGLE)], cwd=root, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env={**ENV, "TMPDIR": str(root)}), root, prefix,
                       cif, sidecar)
    for key, (proc, root, prefix, cif, sidecar) in checks.items():
        assert proc.wait(timeout=600) == 0, proc.stderr.read()[-2000:]
        single = (root / "result.json").read_bytes()
        assert single == out.result_bytes(prefix), f"{key}: the individual's bytes = the standalone M18 job"
        inputs = json.loads(single)["inputs"]["receptor"]
        assert inputs["sha256"] == _sha(cif) and inputs["connectivity"]["sidecar_sha256"] == _sha(sidecar)


# ------------------------------------------------------------------ stops, failures and reuse (parallel real runs)
FAKE = '''# SYNTHETIC failure injection (M23 T4 tests only): fails or alters the chosen cases, runs the real program otherwise.
import json, os, runpy, signal, sys, time
from pathlib import Path
MODE, REAL, COUNTER, REASON = {mode!r}, {real!r}, {counter!r}, {reason!r}
count = int(Path(COUNTER).read_text()) if Path(COUNTER).exists() else 0
Path(COUNTER).write_text(str(count + 1))
if count == 0:      # what the worker gave this child
    Path(COUNTER + ".child.json").write_text(json.dumps({{
        "environ": dict(os.environ), "isolated": sys.flags.isolated, "prefix": sys.prefix, "cwd": os.getcwd(),
        "blocked": sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, [])),
        "stdin_null": os.fstat(0).st_rdev == os.stat("/dev/null").st_rdev}}))
mutations = json.loads(Path("model_input.json").read_text())["payload"]["mutations"]
if MODE == "flood":
    sys.stdout.write("x" * 20000)
    sys.stdout.flush()
    time.sleep(60)
if MODE == "silent_exit":
    raise SystemExit(0)
if MODE == "bad_error":
    Path("error.json").write_text(json.dumps({{"reason_code": "not_a_closed_reason"}}))
    raise SystemExit(1)
if MODE == "error_extra":    # a closed reason with exit 1, but a stray file next to error.json
    Path("model.cif").write_text("SYNTHETIC stray file")
    Path("error.json").write_text(json.dumps({{"reason_code": REASON, "message": "SYNTHETIC injected failure",
                                               "detail": {{"reason_code": REASON}}}}))
    raise SystemExit(1)
if (MODE == "fail_mutants" and mutations) or (MODE == "fail_reference" and not mutations):
    Path("error.json").write_text(json.dumps({{"reason_code": REASON, "message": "SYNTHETIC injected failure",
                                               "detail": {{"reason_code": REASON}}}}))
    raise SystemExit(1)
sys.argv = [REAL]
try:
    runpy.run_path(REAL, run_name="__main__")
    code = 0
except SystemExit as exc:
    code = exc.code
if MODE == "refuse_first" and count == 0 and code == 0:
    os.remove("receptor_bonds.json")
    Path("receptor_error.json").write_text(json.dumps({{"reason_code": REASON, "message": "SYNTHETIC injected refusal",
                                                        "detail": {{"reason_code": REASON}}}}))
if MODE == "flood_exit":     # a finished model, then past the stream limit and gone at once (between two polls)
    sys.stdout.write("x" * 20000)
    sys.stdout.flush()
    os._exit(code or 0)
raise SystemExit(code)
'''
NULL_DOCKINGS = '''
real_load = m._load_by_path
def load(path, name):
    module = real_load(path, name)
    if name == "docking_worker_pinned":
        real, calls = module.dock_row, []
        def dock_row(p, workdir, shared, prepared):
            out = real(p, workdir, shared, prepared)
            calls.append(1)
            if len(calls) in (1, 2):    # SYNTHETIC null result: the engine's modes are dropped (labeled fault)
                out = {**out, "modes": [], "counts": {**out["counts"], "modes": 0, "contacts_by_mode": [],
                                                        "null_result": True}}
            return out
        module.dock_row = dock_row
    return module
m._load_by_path = load
'''
TIME_IN_MODEL = '''
real_reference = m.Job.reference
def reference(self, reused):
    out = real_reference(self, reused)
    m.TOTAL_LIMIT_S = time.monotonic() - m.STARTED_AT + 3.0
    return out
m.Job.reference = reference
'''
TIME_IN_DOCKING = '''
real_dock = m.Job._dock
def dock(self, payload):
    m.TOTAL_LIMIT_S = time.monotonic() - m.STARTED_AT + 0.3
    return real_dock(self, payload)
m.Job._dock = dock
'''
LATE_SIGTERM = '''
real_rmtree = m.shutil.rmtree
sent = []
def rmtree(path, ignore_errors=False):
    if not sent and os.path.basename(str(path)) == "qvina" and os.path.isdir(path) and os.listdir(path):
        sent.append(1)
        os.kill(os.getpid(), m.signal.SIGTERM)     # SIGTERM while a finished docking's engine folder is removed
        time.sleep(0.2)
    return real_rmtree(path, ignore_errors=ignore_errors)
m.shutil = types.SimpleNamespace(rmtree=rmtree)
'''
MODULES = '''
import atexit
def dump():
    with open(os.getcwd() + ".modules.json", "w") as stream:
        json.dump(sorted({name.split(".")[0] for name in sys.modules}), stream)
atexit.register(dump)
'''
FAR_BOX = {"source": "manual", "center_A": [500.0, 500.0, 500.0], "size_A": [20.0, 20.0, 20.0]}


def _fake(root: Path, name: str, mode: str, reason: str) -> str:
    path = root / f"fake_{name}.py"
    path.write_text(FAKE.format(mode=mode, real=str(PROGRAM), counter=str(root / f"fake_{name}.count"),
                                reason=reason))
    return f"m.MODEL_PROGRAM = m.Path({str(path)!r})\n"


@pytest.fixture(scope="module")
def batch(world, first, tmp_path_factory):
    root = tmp_path_factory.mktemp("batch")
    records, reference = _reuse(first["run"])
    base = world["base"]
    reused_ref = {**base, "reference_reuse": reference}
    runs = {
        "reuse_limit": ({**base, "ga": {**GA1, "seed": 9, "max_new_evaluations": 4}, "reuse": records,
                         "reference_reuse": reference}, MODULES),
        "repeated_failure": ({**reused_ref, "ga": {**SMALL, "generations": 3, "seed": 5, "max_new_evaluations": 8}},
                             _fake(root, "repeated", "fail_mutants", "mutation_modeling_failed")),
        "reference_model_failed": (base, _fake(root, "reference", "fail_reference", "topology_unsupported")),
        "reference_box_refused": ({**base, "box": FAR_BOX}, None),
        "reference_docking_timeout": (base, "m.DOCKING_LIMIT_S = 0.05\n"),
        "reference_model_timeout": (base, "m.MODEL_LIMIT_S = 1.0\n"),
        "null_and_refusal": ({**reused_ref, "ga": SMALL},
                             _fake(root, "refusal", "refuse_first", "receptor_invalid") + NULL_DOCKINGS),
        "time_at_start": (base, "m.TOTAL_LIMIT_S = 0.0\n"),
        "time_in_model": (reused_ref, TIME_IN_MODEL),
        "time_in_docking": (reused_ref, TIME_IN_DOCKING),
        "output_cap": (reused_ref, "m.MAX_TOTAL_OUTPUT_BYTES = m.PER_INDIVIDUAL_MAX + 600_000\n"),
        "late_sigterm": (reused_ref, LATE_SIGTERM),
        "reference_stream_bound": (base, _fake(root, "flood", "flood", "") + "m.CHILD_STREAM_LIMIT = 10_000\n"),
        "reference_stream_after_exit": (base, _fake(root, "flood_exit", "flood_exit", "") +
                                        "m.CHILD_STREAM_LIMIT = 10_000\n"),
        "reference_error_extra_file": (base, _fake(root, "extra", "error_extra", "topology_unsupported")),
        "reference_silent_child": (base, _fake(root, "silent", "silent_exit", "")),
        "reference_bad_error": (base, _fake(root, "bad", "bad_error", "")),
        "reference_size_bound": (base, "m.PER_INDIVIDUAL_MAX = 4 * 1024 * 1024 + 100_000\n"),
    }
    outs = _run_all({name: (root / name, manifest, patch) for name, (manifest, patch) in runs.items()})
    return {"root": root, "outs": outs, "records": records, "reference": reference}


def test_another_ga_seed_reuses_stored_evaluations_and_stops_at_the_evaluation_limit(first, batch):
    """GA seed 9 with every evaluation of the first run (same evaluation seed) as the reuse index: reused individuals
    are neither modeled nor docked (no file), new ones are, and the fifth new evaluation needed stops the run."""
    out = batch["outs"]["reuse_limit"]
    ga = {**GA1, "seed": 9, "max_new_evaluations": 4}
    reusable = [*first["run"].computed(), "wild_type"]
    expected = _oracle(ga, OBSERVED, reusable)
    _assert_path(out, expected)
    assert (expected["stop_reason"], expected["reused_count"], expected["new_evaluations_used"]) == \
        ("evaluation_limit", 5, 4)
    assert [g["complete"] for g in out.records()][-1] is False
    reused = {e["key"] for g in out.records() for e in g["individuals"] if e["evaluation"] == "reused"}
    assert reused and reused <= set(first["run"].computed()) and not set(out.computed()) & set(first["run"].computed())
    assert out.records() != first["run"].records(), "another GA seed, another path"
    assert list(out.reference) == ["reference.status.json"] and out.status("reference") == ["scored", None, "docking"]
    for key, k in out.computed().items():
        assert json.loads(out.files[f"{k}.model.json"])["mutations"] == SB.model_mutations(TINY["content"], key)
    modules = set(json.loads((out.root.parent / "reuse_limit.modules.json").read_text()))
    assert not modules & {"openmm", "pdbfixer", "mw"}, "no OpenMM, no PDBFixer, no server package in the worker"
    assert {"rdkit", "meeko", "MDAnalysis", "gemmi"} <= modules       # through docking_worker.py only


def test_five_consecutive_failures_end_the_run(batch):
    out = batch["outs"]["repeated_failure"]
    keys = list(TINY_SPACE["canonical_at_cap"])
    table = {key: {"state": "failed", "reason_code": "mutation_modeling_failed", "score": None} for key in keys}
    table["wild_type"] = OBSERVED["wild_type"]
    expected = _oracle({**SMALL, "generations": 3, "seed": 5, "max_new_evaluations": 8}, table, ["wild_type"])
    assert (expected["stop_reason"], expected["new_evaluations_used"]) == ("repeated_failure", 5)
    _assert_path(out, expected, stages=dict.fromkeys(keys, "model"))
    assert not any(name.endswith((".model.json", ".result.json")) for name in out.files)
    assert out.records()[-1]["complete"] is False and len(out.records()[-1]["individuals"]) == 1


@pytest.mark.parametrize(("name", "status", "kept"), [
    ("reference_model_failed", ["failed", "topology_unsupported", "model"], False),
    ("reference_box_refused", ["failed", "box_no_receptor_atoms", "docking"], True),
    ("reference_docking_timeout", ["failed", "docking_timeout", "docking"], True),
    ("reference_model_timeout", ["failed", "model_timeout", "model"], False),
    ("reference_stream_bound", ["failed", "resource_exceeded", "model"], False),
    ("reference_stream_after_exit", ["failed", "resource_exceeded", "model"], False),   # T10: checked after exit too
    ("reference_error_extra_file", ["failed", "worker_failed", "model"], False),        # T10: exit 1 + a stray file
    ("reference_silent_child", ["failed", "worker_failed", "model"], False),
    ("reference_bad_error", ["failed", "worker_failed", "model"], False),
    ("reference_size_bound", ["failed", "resource_exceeded", "model"], False)])
def test_a_failed_reference_row_ends_the_run_before_any_individual(batch, name, status, kept):
    out = batch["outs"][name]
    assert out.code == 0 and out.error is None, out.error
    assert out.result == _result("reference_failed", 0)
    assert out.status("reference") == status
    assert sorted(out.reference) == (["reference.model.cif", "reference.model.json", "reference.status.json"] if kept
                                     else ["reference.status.json"])
    assert out.files == {} and out.gens == {}
    assert _engines_under(out.root) == []
    if name == "reference_box_refused":
        assert out.prepared["box"] == {**FAR_BOX, "margin_A": None}


def test_null_results_and_refused_receptors_are_evaluated_and_never_parents(batch):
    """Eval 0's model is refused as an M18 receptor (SYNTHETIC injected refusal: the docking step fails, the model is
    kept); evals 1 and 2 get SYNTHETIC null results (the engine's modes dropped). None of them is carried or a
    parent; the run follows the oracle on that table."""
    out = batch["outs"]["null_and_refusal"]
    first_keys = [e["key"] for e in _oracle(GA1, OBSERVED)["generations"][0]["individuals"]]
    table = copy.deepcopy(OBSERVED)
    table[first_keys[0]] = {"state": "failed", "reason_code": "receptor_invalid", "score": None}
    for key in first_keys[1:3]:
        table[key] = {"state": "null_result", "reason_code": None, "score": None}
    expected = _oracle(SMALL, table, ["wild_type"])
    _assert_path(out, expected)
    unscored = set(first_keys[:3])
    for g in out.records():
        for e in g["individuals"]:
            assert not (e["origin"] == "carried" and e["key"] in unscored)
            assert not set(e["parents"] or []) & unscored
    assert json.loads(out.files["1.result.json"])["modes"] == [] and "0.model.cif" in out.files


@pytest.mark.parametrize("name", ["time_in_model", "time_in_docking"])
def test_the_total_clock_stops_a_running_step_and_drops_that_individual(batch, name):
    out = batch["outs"][name]
    assert out.code == 0 and out.result == _result("time_exhausted", 0)
    assert out.files == {"0.started": b""}
    assert out.gens == {1: {"index": 1, "complete": False, "individuals": []}}
    assert out.status("reference") == ["scored", None, "docking"]
    assert _engines_under(out.root) == []


def test_the_total_clock_before_the_reference_row_writes_only_the_end_record(batch):
    out = batch["outs"]["time_at_start"]
    assert out.code == 0 and out.result == _result("time_exhausted", 0)
    assert out.reference == {} and out.files == {} and out.gens == {} and out.prepared is not None


def test_the_output_bound_stops_before_a_new_evaluation(batch):
    out = batch["outs"]["output_cap"]
    expected = _oracle(GA1, OBSERVED, ["wild_type"])
    assert out.result == _result("resource_exceeded", 0)
    assert out.records() == _expected_records({"generations": _truncated(expected, 2)})
    size = {k: sum(len(raw) for name, raw in out.files.items() if name.startswith(f"{k}.")) for k in (0, 1)}
    assert size[0] < 600_000 < size[0] + size[1], "the third new evaluation would pass the bound"
    assert sorted(out.files) == [f"{k}.{s}" for k in (0, 1) for s in ("model.cif", "model.json", "result.json",
                                                                      "started", "status.json")]


def test_a_finished_docking_survives_a_late_sigterm(first, batch):
    """Labeled fault: SIGTERM sent while the engine folder of a finished docking is removed. The individual is kept
    (byte-identical to the first run's same individual), the stop is the next check's ``cancelled``."""
    out = batch["outs"]["late_sigterm"]
    assert out.code == 0 and out.result == _result("cancelled", 0)
    assert sorted(out.files) == ["0.model.cif", "0.model.json", "0.result.json", "0.started", "0.status.json"]
    assert out.status("0") == ["scored", None, "docking"]
    for suffix in ("model.cif", "model.json", "result.json"):
        assert out.files[f"0.{suffix}"] == first["run"].files[f"0.{suffix}"]
    assert [(e["evaluation"], e["eval_index"]) for e in out.gens[1]["individuals"]] == [("computed", 0)]
    assert out.gens[1]["complete"] is False


# ------------------------------------------------------------------ SIGTERM (cancel) while a step runs
def _wait_for(proc: subprocess.Popen, root: Path, what: str) -> list[int]:
    """Pids of the running modeling child (``model``) or qvina2 (``qvina``) of the worker's first new evaluation."""
    end = time.monotonic() + 300
    while time.monotonic() < end:
        assert proc.poll() is None, "the worker exited before the step ran"
        found = []
        for child in psutil.Process(proc.pid).children(recursive=True):
            try:
                name, cmdline = child.name(), child.cmdline()
            except psutil.Error:
                continue
            if (what == "qvina" and name == "qvina2") or (what == "model" and str(SGW.MODEL_PROGRAM) in cmdline):
                found.append(child.pid)
        if found and (root / "individuals/0.started").exists():
            return found
        time.sleep(0.01)
    proc.kill()
    raise AssertionError(f"no {what} process appeared")


@pytest.mark.parametrize(("what", "target"), [("model", "group"), ("model", "worker"), ("qvina", "worker")])
def test_sigterm_cancels_the_running_step_and_leaves_no_process(world, first, tmp_path, what, target):
    """``group``: the guardian's cancel (SIGTERM to the whole process group: the worker and its modeling child);
    ``worker``: SIGTERM to the worker only, which then ends its own child (the modeling program or qvina2)."""
    _records, reference = _reuse(first["run"])
    root = tmp_path / "term"
    proc = _popen(root, {**world["base"], "reference_reuse": reference})
    engines = _wait_for(proc, root, what)
    if target == "group":
        os.killpg(proc.pid, signal.SIGTERM)
    else:
        os.kill(proc.pid, signal.SIGTERM)
    out = _finish(proc, root, timeout=5.0)          # within the guardian's grace period
    assert out.code == 0 and out.result == _result("cancelled", 0)
    assert out.files == {"0.started": b""}
    assert out.gens == {1: {"index": 1, "complete": False, "individuals": []}}
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and any(psutil.pid_exists(pid) for pid in engines):
        time.sleep(0.02)
    assert not [pid for pid in engines if psutil.pid_exists(pid) and
                psutil.Process(pid).status() != psutil.STATUS_ZOMBIE], "no engine process is left"
    assert _engines_under(root) == []


# ------------------------------------------------------------------ fatal inputs, handshake, isolation
FATAL = {
    "control_hash": ({}, {"input_sha256": "0" * 64}),
    "project_python": ({"project_python": str(PROJECT_PY.resolve())}, {}),
    "ligand_hash": ({"ligand_sdf": {"b64": base64.b64encode(PHENOL).decode(), "sha256": "0" * 64}}, {}),
    "instance_box": ({"box": {"source": "instance_range", "margin_A": 8.0}}, {}),
    "core_fixed_values": ({"parameters": {**DOCK_VALUES, "energy_range": 3.0, "conformers": 3}}, {}),
    "unknown_key": ({"mode": "free"}, {}),
}


def test_malformed_staging_ends_fatal_before_any_file(world, tmp_path):
    procs = {}
    for name, (changes, control) in FATAL.items():
        manifest = {**world["base"], **changes}
        procs[name] = (_popen(tmp_path / name, manifest, **control), tmp_path / name)
    for name, (proc, root) in procs.items():
        out = _finish(proc, root, timeout=120)
        assert out.code == 1 and out.result is None, name
        assert (out.error["schema"], out.error["error_class"], out.error["reason_code"]) == \
            ("docking_worker_error@1", "fatal", "engine_failed"), name
        assert sorted(p.name for p in root.iterdir()) == ["error.json", "input.json", "structure.json"], name


def test_handshake_names_the_protocol_the_module_hashes_and_the_project_interpreter():
    out = subprocess.run([str(PY), "-I", str(WORKER), "--handshake"], capture_output=True, text=True, timeout=120,
                         check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    shake = json.loads(out.stdout)
    assert shake["schema"] == "sequence_ga_worker_handshake@1" and shake["protocols"] == [SC.PROTOCOL]
    assert shake["worker_sha256"] == _sha(WORKER.read_bytes())
    assert shake["row_worker_sha256"] == _sha(SINGLE.read_bytes())
    assert shake["ga_constants_sha256"] == _sha((ROOT / "backend/mw/sequence_ga_constants.py").read_bytes())
    assert shake["model_worker_sha256"] == _sha(PROGRAM.read_bytes())
    assert shake["project_python"] == str(PROJECT_PY) and shake["project_python_present"] is True
    assert shake["versions"] == shake["versions_expected"] and shake["engine"]["hash_match"] is True


def test_isolation_and_unchanged_hashed_files():
    """The worker imports no server package, no OpenMM/PDBFixer and no chemistry itself (only through
    ``docking_worker.py``), runs no qvina2 itself; no server module imports it; the files whose bytes key the M18,
    M19, M21 and M22 calls are unchanged (T1 ``golden_call_keys.json``)."""
    text = WORKER.read_text()
    imports = re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", text, re.MULTILINE)
    assert {name.split(".")[0] for name in imports} <= {"__future__", "time", "base64", "hashlib", "importlib",
                                                       "json", "math", "os", "random", "re", "shutil", "signal",
                                                       "stat", "subprocess", "sys", "collections", "pathlib",
                                                       "typing"}
    assert "run_qvina" not in text and "QVINA" not in text and text.count("subprocess.Popen(") == 1
    assert re.search(r'subprocess\.Popen\(\[self\.p\["project_python"\], "-I", str\(MODEL_PROGRAM\)\]', text)
    pattern = re.compile(r"^\s*(from\s+\S*sequence_ga_worker\s+import|import\s+\S*sequence_ga_worker|"
                         r"from\s+\.+jobs\s+import\s+.*sequence_ga_worker)", re.MULTILINE)
    assert [str(p) for p in (ROOT / "backend/mw").rglob("*.py") if pattern.search(p.read_text())] == []
    golden = json.loads((GA_FIX / "golden_call_keys.json").read_text())
    for name, digest in {**golden["hashed_files"], **golden["also_hashed_files"]}.items():
        assert _sha((ROOT / name).read_bytes()) == digest, name


def test_the_modeling_child_gets_the_guardian_environment_and_the_default_signal_mask(batch):
    """Recorded by the labeled stand-in program at its first launch (the repeated-failure run): the guardian worker
    environment with TMPDIR = its own folder, ``-I``, the project venv (the link was not resolved), stdin closed,
    and SIGTERM / SIGALRM not blocked (so a guardian SIGTERM to the group reaches it)."""
    child = json.loads((batch["root"] / "fake_repeated.count.child.json").read_text())
    work = str(batch["root"] / "repeated_failure" / "model_work")
    expected = {**ENV, "TMPDIR": work}
    assert {k: child["environ"].get(k) for k in expected} == expected
    assert set(child["environ"]) - set(expected) <= {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}   # set by the platform
    assert child["isolated"] == 1 and child["cwd"] == work and child["stdin_null"] is True
    assert Path(child["prefix"]) == ROOT / ".venv"
    assert signal.SIGTERM not in child["blocked"] and signal.SIGALRM not in child["blocked"]
