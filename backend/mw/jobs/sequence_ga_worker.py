"""Fixed, isolated M23 sequence GA design worker (spec .dryforge/spec.md 3, 4, 8). JSON files only.

The guardian launches this script with the pinned ``.deps/docking/venv-locked`` interpreter, like the M18/M19/M22
workers (same process group, monitored tree). Each new evaluation runs the M23 modeling program
``sequence_model_worker.py`` as a CHILD process with the project interpreter, ``[<repo>/.venv/bin/python, "-I",
program]`` (that venv link is never resolved: resolving it reaches a base interpreter without ``mw`` and OpenMM),
then docks the model with the M18 worker's own functions (``docking_worker.py`` loaded by file path, never a package
import): ``receptor_inputs`` then ``dock_row(payload, workdir, shared, None)``, which runs ``receptor_prepared`` at
the M18 point. That is the standalone M18 ``qvina_dock_v1`` job's ``dock()`` on the same payload, so an individual's
result is byte-identical to that job and keeps its refusal order. The receptor is prepared per individual (each
individual has its own receptor). OpenMM and PDBFixer are imported only by the child; RDKit, Meeko and MDAnalysis
only through ``docking_worker.py``; the only other ``mw`` code is the dependency-free ``mw/sequence_ga_constants.py``,
loaded by file path. Python sockets are denied when ``docking_worker.py`` is loaded; nothing is fetched. The GA part
(``Ga``, ``validate_manifest`` and the arithmetic) needs neither and is loaded by the server tests directly.

Job mode (no arguments, cwd = private attempt directory). ``input.json`` = ``{adapter: "sequence_ga_dock_v1",
input_sha256 (of the structure.json bytes), job_id, attempt_id, ...}``; ``structure.json`` is the server's staged
manifest ``sequence_ga_worker_input@1`` (at most 16 MiB, canonical JSON, byte entries ``{"b64", "sha256"}`` as in M18;
exactly these keys)::

    schema             "sequence_ga_worker_input@1"
    run_id             the run id (the modeling program computes each mmCIF object handle in it)
    project_python     str(<repo>/.venv/bin/python) computed like guardian.DOCKING_PYTHON from the module file
                       (``Path(__file__).resolve().parents[3] / ".venv/bin/python"``, the link itself, not resolved);
                       any other value, or a missing interpreter, ends the job fatal
    candidate_set      the M20 mutation_candidate_set handle of this run (obj://<run_id>/mutation_candidate_set/<hex>)
    structure          the set's {handle (obj://<run_id>/prepared_structure/<hex>), model_number, structure_kind:
                       "prepared_structure"}
    model_number       int, the M7 preflight model number (= structure.model_number)
    protein            the M7 preflight heavy-atom projection ``preflight(...)["protein"]``, unchanged
    method             the M21 method record (``mutation_model_bundle.require_ready()["method"]``: exactly
                       ``mutation_model_constants.METHOD_KEYS``; the modeling program checks it against the engines)
    ligand_sdf         entry: the user ligand SDF import bytes
    box                the normalized M18 box (``sequence_ga_inputs.individual_arguments(...)["box"]``):
                       {source: ligand_range, margin_A} | {source: manual, center_A, size_A}
    parameters         the normalized M18 free parameters (``individual_arguments(...)["parameters"]``: seed,
                       exhaustiveness, num_modes, energy_range, conformers: null); ``seed`` is the evaluation seed of
                       both the modeling program and qvina2
    ga                 every GA_KEYS value, normalized (``sequence_ga_inputs.normalize_ga``)
    candidates         every candidate of the set in storage order: [{index (= list position), position_index
                       (non-decreasing: position storage order), residue (the position's 7 fields), from, to (one
                       letter), mutant_resname (three letters)}]; the positions are the distinct position_index values
    reuse              the reuse index: [{key, state: scored | null_result, reason_code: null, score: float | null,
                       model_handle, result_handle}] (``sequence_ga_inputs.reuse_record`` facts; unique keys of 1-4
                       candidates at distinct positions; never the reference row)
    reference_reuse    null, or the wild-type reference row's reuse fact {key: "wild_type", state, reason_code,
                       score, model_handle, result_handle, model_summary: {structure_sha256, protonation_variants,
                       disulfide_bonds}} (the stored reference model entry's values: every mutant model is compared
                       with them)
    selection_sha256, conditions_sha256    the job's hashes (shape-checked; they bind the staged bytes to the job)

Evaluation (spec 4; one at a time, CPU 1). The modeling child runs in ``model_work/`` (created fresh, removed after
every evaluation and at any stop) holding ``model_input.json`` = canonical ``{"input_sha256", "payload"}`` with the
payload ``{schema: "sequence_model_input@1", run_id, candidate_set, structure, method, model_number, protein, seed,
mutations: [{candidate_index, residue, from, to, mutant_resname}] (structure order, [] for the reference row),
reference: null | the reference model summary}``. Child environment = the guardian worker environment (``PATH``,
``LANG``, ``PYTHONUTF8``, ``PYTHONUNBUFFERED``, ``OMP_NUM_THREADS``, ``OPENBLAS_NUM_THREADS``, ``TMPDIR`` = its own
folder), stdin closed, stdout/stderr to files in its folder (each capped at 1 MiB while it runs), same process group.
The step limit is ``MODEL_STEP_S`` (240 s): the child is killed and the individual is ``failed`` ``model_timeout``;
the total clock and SIGTERM kill it too and stop the run (the individual is not recorded). Exit 1 with ``error.json``
gives its closed M21 reason; any other contract break is ``worker_failed``. ``receptor_error.json`` (the model is not
an M18 receptor) fails the docking step with its M18 reason and keeps the model. Docking (``DOCKING_STEP_S`` 300 s for
``receptor_inputs`` + ``dock_row``; over it the individual is ``failed`` ``docking_timeout``) uses the M18 payload
``{schema: "docking_worker_input@1", receptor: {handle: <the model's mmCIF object handle>, format: "cif", bytes,
model_number, connectivity: {kind: "sidecar", sidecar}, instance: null, source: "mutation_model"}, ligand: {source:
"sdf", sdf: ligand_sdf}, mode: "free", box, parameters}`` (``docking_bundle.stage`` for an M21-style receptor source).
A reused individual (its key in ``reuse``) or reference row (``reference_reuse``) is neither modeled nor docked.

GA procedure (spec 3 with its "detail" items 1-11): ``Ga`` below; ``random.Random(ga.seed)`` and only ``randint``,
``random``, ``sample`` and ``choice`` in the spec's order. Stops before every individual, in this order: SIGTERM
(``cancelled``), a needed new evaluation while ``reserved_evaluations`` new ones are done (``evaluation_limit``), the
total clock (``time_exhausted``), then for a new evaluation the output bound (written bytes + ``PER_INDIVIDUAL_OUTPUT_MAX``
> ``MAX_OUTPUT_BYTES``: ``resource_exceeded``); the reference row is checked the same way (no limit). The clock and
SIGTERM are also checked before each step and while the child or the docking runs. A stopped individual keeps only
``individuals/<k>.started`` and is not listed. Stops of the procedure: ``reference_failed``, ``repeated_failure`` (the
fifth consecutive failure is listed), ``space_exhausted``, ``no_change``, ``generations_complete``.

Durable files (temporary file + fsync + ``os.replace`` + directory fsync; SIGALRM/SIGTERM blocked while writing):
``prepared.json`` = canonical ``{"box": <the run box in the M18 result's shape, or null when RDKit cannot read the
ligand (the reference row then fails with the M18 reason)>, "engine": <qvina engine identity>, "model_method": <method
+ multi_mutation, as every model records it>}`` before the reference row; the reference row's
``reference.model.json`` / ``reference.model.cif`` (when modeled) / ``reference.result.json`` (scored and
null_result) / ``reference.status.json`` (written last, also for a reused row); per new evaluation ``k`` (=
``eval_index`` 0, 1, ...) ``individuals/<k>.started`` (empty) then ``<k>.model.json``, ``<k>.model.cif`` (the child's
bytes), ``<k>.result.json`` (the M18 ``docking_worker_output@1`` bytes with this job's ``job_id``/``attempt_id``) and
``<k>.status.json`` = canonical ``{"reason_code": str | null, "stage": "model" | "docking", "state": "scored" |
"null_result" | "failed"}`` last; ``generations/<g>.json`` = canonical ``{"index", "complete", "individuals": [{key,
origin, parents, edit_op, evaluation, pick_index, eval_index}]}`` (carried first, then new in selection order)
rewritten with ``complete: false`` after each evaluated individual and at a stop, ``complete: true`` at the end of the
generation. Scores and states are never in the generation records: the server reads them from the stored results.

On every stop the worker writes canonical ``result.json`` ``{"attempt_id", "generations_done", "job_id", "protocol",
"schema": "sequence_ga_worker_output@1", "stop_reason"}`` and exits 0 (a stop before ``reference.status.json`` is the
server's case without a summary). A malformed manifest or control record, another ``project_python``, unpinned
chemistry versions or a qvina2 identity failure writes the M18 ``error.json`` envelope (fatal ``engine_failed``) and
exits 1.
"""
from __future__ import annotations

import time

STARTED_AT = time.monotonic()   # total clock origin: worker start, before the chemistry imports

import base64
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import signal
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol


def _load_by_path(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{name} unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve()
GC = _load_by_path(HERE.parents[1] / "sequence_ga_constants.py", "sequence_ga_constants_pinned")
ROW_WORKER = HERE.with_name("docking_worker.py")
MODEL_PROGRAM = HERE.with_name("sequence_model_worker.py")
PROJECT_PYTHON = HERE.parents[3] / ".venv" / "bin" / "python"   # the venv link itself, never resolved (spec 8)

ADAPTER = GC.PROTOCOL
MODEL_INPUT_SCHEMA = "sequence_model_input@1"   # = sequence_model_worker.INPUT_SCHEMA
STRUCTURE_KIND = "prepared_structure"
# Spec 4, 8, 11 limits (code constants in sequence_ga_constants; tests shrink these module copies only).
MODEL_LIMIT_S = float(GC.MODEL_STEP_S)
DOCKING_LIMIT_S = float(GC.DOCKING_STEP_S)
TOTAL_LIMIT_S = float(GC.TOTAL_S_MAX)           # ceiling; the run's own clock is min(this, ga.total_s)
MAX_TOTAL_OUTPUT_BYTES = GC.MAX_OUTPUT_BYTES
PER_INDIVIDUAL_MAX = GC.PER_INDIVIDUAL_OUTPUT_MAX
CHILD_STREAM_LIMIT = 1024 * 1024                # per child stream (= the guardian's worker stream limit)
CHILD_JSON_LIMIT = 64 * 1024                    # error.json / receptor_error.json of the child
CONTROL_LIMIT = 4096
POLL_S = 0.05
WORK_DIR = Path("model_work")
IND_DIR = Path("individuals")
GEN_DIR = Path("generations")
REFERENCE_PREFIX = "reference."
SIGNALS = {signal.SIGALRM, signal.SIGTERM}
CHILD_OUTPUTS = ("model.json", "model.cif")
CHILD_OWN = {"model_input.json", "child.stdout", "child.stderr"}

SHA_RE = re.compile(r"[0-9a-f]{64}")
CONTROL_ID_RE = re.compile(r"[a-z0-9_]{1,100}")
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")   # = core.handles.RUN_ID_RE
KEY_RE = re.compile(rf"(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*)){{0,{GC.MAX_MUTATIONS - 1}}}")
LETTER_RE = re.compile(r"[A-Z]")
RESNAME_RE = re.compile(r"[A-Z]{3}")
RESIDUE_KEYS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
MANIFEST_KEYS = frozenset({"schema", "run_id", "project_python", "candidate_set", "structure", "model_number",
                           "protein", "method", "ligand_sdf", "box", "parameters", "ga", "candidates", "reuse",
                           "reference_reuse", "selection_sha256", "conditions_sha256"})
CANDIDATE_KEYS = frozenset({"index", "position_index", "residue", "from", "to", "mutant_resname"})
REUSE_KEYS = frozenset({"key", "state", "reason_code", "score", "model_handle", "result_handle"})
SUMMARY_KEYS = frozenset({"structure_sha256", "protonation_variants", "disulfide_bonds"})

Outcome = tuple[str, str | None, float | None]   # (state, reason_code, first-mode score)


def canonical_json(value: Any) -> bytes:
    """Byte-identical to ``mw.core.handles.canonical_json`` and ``docking_worker.canonical_json``."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


# ------------------------------------------------------------------ keys and arithmetic (spec 3, 7)
def key_text(key: tuple[int, ...]) -> str:
    return GC.KEY_SEPARATOR.join(str(index) for index in key)


def parse_key(text: Any) -> tuple[int, ...]:
    """``"12-57-203"`` -> (12, 57, 203): decimal, no sign or leading zero, 1-4 strictly ascending indices."""
    _require(type(text) is str and KEY_RE.fullmatch(text), "an individual key is 1-4 indices joined by '-'")
    key = tuple(int(part) for part in text.split(GC.KEY_SEPARATOR))
    _require(list(key) == sorted(set(key)), "individual key indices must be strictly ascending")
    return key


def elementary(counts: list[int], k: int) -> int:
    """The k-th elementary symmetric polynomial of ``counts`` (exact integer)."""
    table = [1] + [0] * len(counts)
    for value in counts:
        for index in range(len(counts), 0, -1):
            table[index] += table[index - 1] * value
    return table[k] if 0 <= k <= len(counts) else 0


def space_size(counts: list[int], max_mutations: int) -> int:
    """N = sum over k = 1..M of e_k(n_1, ..., n_P), M = min(max_mutations, P)."""
    return sum(elementary(counts, k) for k in range(1, min(max_mutations, len(counts)) + 1))


def reserved_evaluations(ga: dict[str, Any]) -> int:
    """Spec 7 (= ``sequence_ga_inputs.reserved_evaluations``): the new evaluations reserved before the start."""
    population, elite = ga["population_size"], ga["elite_count"]
    return min(ga["max_new_evaluations"], population + (ga["generations"] - 1) * (population - elite))


def slot_counts(population: int, carried: int, crossover_fraction: float, random_fraction: float) -> dict[str, int]:
    """Spec 3 step 4 (b): r = floor(random_fraction * slots + 0.5), c = floor(crossover_fraction * (slots - r) + 0.5)."""
    slots = population - carried
    randoms = math.floor(random_fraction * slots + 0.5)
    crossovers = math.floor(crossover_fraction * (slots - randoms) + 0.5)
    return {"slots": slots, "crossover": crossovers, "edit": slots - randoms - crossovers, "random": randoms}


# ------------------------------------------------------------------ the GA (spec 3)
class Environment(Protocol):
    """What the GA needs from its job: checks, evaluations (an ``Outcome`` or a run stop) and records."""

    def cancelled(self) -> bool: ...
    def time_up(self) -> bool: ...
    def output_full(self) -> bool: ...
    def reference(self, reused: dict[str, Any] | None) -> Outcome | str: ...
    def evaluate(self, key: tuple[int, ...], index: int) -> Outcome | str: ...
    def record(self, index: int, complete: bool, entries: list[dict[str, Any]]) -> None: ...


class Ga:
    """One GA run over one combination space (spec 3). ``positions`` are the position indices in storage order and
    ``alts[p]`` the candidate indices of position ``p`` in storage order (candidate index order is position storage
    order, then candidate storage order, so a key's ascending indices are its mutations in that order). ``reused`` =
    key text -> ``{"state", "score"}`` of the reuse index; ``reference_reused`` = the reference row's reuse fact."""

    def __init__(self, positions: list[int], alts: dict[int, list[int]], ga: dict[str, Any],
                 reused: dict[str, dict[str, Any]], reference_reused: dict[str, Any] | None) -> None:
        self.positions = list(positions)
        self.alts = {p: list(alts[p]) for p in self.positions}
        self.position_of = {index: p for p in self.positions for index in self.alts[p]}
        self.ga, self.reused, self.reference_reused = ga, reused, reference_reused
        self.cap = min(ga["max_mutations"], len(self.positions))
        self.size = space_size([len(self.alts[p]) for p in self.positions], ga["max_mutations"])
        self.reserved = reserved_evaluations(ga)
        self.rng = random.Random(ga["seed"])
        self.seen: set[tuple[int, ...]] = set()
        self.picks = self.new = self.reused_count = self.failures = 0
        self.reference: dict[str, Any] | None = None
        self.generations: list[list[dict[str, Any]]] = []

    # ---- order and selection
    @staticmethod
    def _order(entry: dict[str, Any]) -> tuple[float, int, int]:
        """Score order: lower score, then fewer mutations, then earlier pick."""
        return entry["score"], len(entry["key"]), entry["pick_index"]

    def canonical(self) -> Iterator[tuple[int, ...]]:
        """Every key in canonical order (size ascending, then the integer index list lexicographically), lazily."""
        flat = sorted(self.position_of)

        def extend(prefix: tuple[int, ...], start: int, used: frozenset[int], size: int) -> Iterator[tuple[int, ...]]:
            if len(prefix) == size:
                yield prefix
                return
            for at in range(start, len(flat)):
                if self.position_of[flat[at]] not in used:
                    yield from extend((*prefix, flat[at]), at + 1, used | {self.position_of[flat[at]]}, size)

        for size in range(1, self.cap + 1):
            yield from extend((), 0, frozenset(), size)

    def draw(self) -> tuple[int, ...] | None:
        """k uniform in 1..M, k positions, one candidate each; 50 more tries on a seen key, then the first unseen key
        in canonical order (no rng); None when every key was seen."""
        for _attempt in range(1 + GC.DRAW_RETRIES):
            size = self.rng.randint(1, self.cap)
            chosen = sorted(self.rng.sample(self.positions, size), key=self.positions.index)
            key = tuple(sorted(self.rng.choice(self.alts[p]) for p in chosen))
            if key not in self.seen:
                return key
        return next((key for key in self.canonical() if key not in self.seen), None)

    def tournament(self, pool: list[dict[str, Any]]) -> dict[str, Any]:
        return min(self.rng.sample(pool, min(self.ga["tournament_size"], len(pool))), key=self._order)

    def crossover(self, pool: list[dict[str, Any]]) -> tuple[tuple[int, ...], str, list[str], str | None] | None:
        first, second = self.tournament(pool), self.tournament(pool)
        distinct = len({entry["key"] for entry in pool}) > 1
        for _retry in range(GC.B_RETRIES):
            if first["key"] != second["key"] or not distinct:
                break
            second = self.tournament(pool)
        if first["key"] == second["key"]:
            return self.edit(pool, first)                 # the slot becomes an edit slot on A
        a = {self.position_of[index]: index for index in first["key"]}
        b = {self.position_of[index]: index for index in second["key"]}
        child: list[int] = []
        for p in self.positions:
            if p in a and p in b:
                child.append(a[p] if a[p] == b[p] else self.rng.choice([a[p], b[p]]))
            elif (p in a or p in b) and self.rng.random() < 0.5:
                child.append(a[p] if p in a else b[p])
        if not child:
            union: list[int] = []
            for p in self.positions:
                union += [index for index in (a.get(p), b.get(p)) if index is not None and index not in union]
            child = [self.rng.choice(union)]
        if len(child) > self.cap:
            child = self.rng.sample(child, self.cap)
        return tuple(sorted(child)), "crossover", [key_text(first["key"]), key_text(second["key"])], None

    def edit(self, pool: list[dict[str, Any]], parent: dict[str, Any] | None = None
             ) -> tuple[tuple[int, ...], str, list[str], str | None] | None:
        parent = parent if parent is not None else self.tournament(pool)
        key = list(parent["key"])
        used = {self.position_of[index] for index in key}
        unused = [p for p in self.positions if p not in used]
        changeable = [index for index in key if len(self.alts[self.position_of[index]]) > 1]
        possible = [op for op, ok in (("add", len(key) < self.cap and unused), ("change", changeable),
                                      ("move", unused), ("remove", len(key) > 1)) if ok]
        if not possible:
            return None                                       # the slot becomes a random slot
        op = self.rng.choice(possible)
        if op == "add":
            child = [*key, self.rng.choice(self.alts[self.rng.choice(unused)])]
        elif op == "change":
            target = self.rng.choice(changeable)
            others = [index for index in self.alts[self.position_of[target]] if index != target]
            child = [index for index in key if index != target] + [self.rng.choice(others)]
        elif op == "move":
            target = self.rng.choice(key)
            child = [index for index in key if index != target] + [self.rng.choice(self.alts[self.rng.choice(unused)])]
        else:
            target = self.rng.choice(key)
            child = [index for index in key if index != target]
        return tuple(sorted(child)), "edit", [key_text(parent["key"])], op

    def _pick(self, key: tuple[int, ...], origin: str, parents: list[str] | None, op: str | None) -> dict[str, Any]:
        self.seen.add(key)
        entry = {"key": key, "origin": origin, "parents": parents, "edit_op": op, "evaluation": None,
                 "pick_index": self.picks, "eval_index": None, "state": None, "reason_code": None, "score": None}
        self.picks += 1
        return entry

    def select(self, kind: str, pool: list[dict[str, Any]]) -> dict[str, Any] | None:
        """One slot of ``kind`` (initial, crossover, edit, random); None when every key of the space was seen."""
        if len(self.seen) >= self.size:
            return None                                       # no rng call for this and every later slot
        if kind in ("crossover", "edit") and pool:
            for _attempt in range(1 + GC.CHILD_RETRIES):
                made = self.crossover(pool) if kind == "crossover" else self.edit(pool)
                if made is None:
                    break
                if made[0] not in self.seen:
                    return self._pick(*made)
        key = self.draw()
        return None if key is None else self._pick(key, "initial" if kind == "initial" else "random", None, None)

    def _plan(self, previous: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        """(carried entries, slot kinds, tournament pool) of the next generation."""
        scored = [entry for entry in previous if entry["state"] == "scored"]
        carried = [{**entry, "origin": "carried", "parents": None, "edit_op": None, "evaluation": None,
                    "eval_index": None} for entry in sorted(scored, key=self._order)[:self.ga["elite_count"]]]
        counts = slot_counts(self.ga["population_size"], len(carried), self.ga["crossover_fraction"],
                             self.ga["random_fraction"])
        kinds = ["crossover"] * counts["crossover"] + ["edit"] * counts["edit"] + ["random"] * counts["random"]
        pool = ([entry for entry in scored if entry["origin"] == "carried"] +
                sorted((entry for entry in scored if entry["origin"] != "carried"), key=lambda e: e["pick_index"]))
        return carried, kinds, pool

    # ---- evaluation
    def _reference(self, env: Environment) -> str | None:
        reused = self.reference_reused
        if env.cancelled():
            return "cancelled"
        if env.time_up():
            return "time_exhausted"
        if reused is None and env.output_full():
            return "resource_exceeded"
        outcome = env.reference(reused)
        if isinstance(outcome, str):
            return outcome
        self.reference = {"evaluation": "computed" if reused is None else "reused", "state": outcome[0],
                          "reason_code": outcome[1], "score": outcome[2]}
        return "reference_failed" if outcome[0] == "failed" else None

    def _evaluate(self, entry: dict[str, Any], env: Environment) -> str | None:
        """Evaluate one selected individual; None, or the stop reason (the individual is then not evaluated)."""
        reused = self.reused.get(key_text(entry["key"]))
        if env.cancelled():
            return "cancelled"
        if reused is None and self.new >= self.reserved:
            return "evaluation_limit"
        if env.time_up():
            return "time_exhausted"
        if reused is None and env.output_full():
            return "resource_exceeded"
        if reused is not None:
            entry.update(evaluation="reused", state=reused["state"], reason_code=None, score=reused["score"])
            self.reused_count += 1
        else:
            outcome = env.evaluate(entry["key"], self.new)
            if isinstance(outcome, str):
                return outcome
            entry.update(evaluation="computed", eval_index=self.new, state=outcome[0], reason_code=outcome[1],
                         score=outcome[2])
            self.new += 1
        self.failures = self.failures + 1 if entry["state"] == "failed" else 0   # carried entries never come here
        return None

    def run(self, env: Environment) -> tuple[str, int]:
        """The reference row, then every generation; (stop reason, complete generations)."""
        stop = self._reference(env)
        if stop is not None:
            return stop, 0
        best: float | None = None
        still = done = 0
        for g in range(1, self.ga["generations"] + 1):
            if g == 1:
                carried, kinds, pool = [], ["initial"] * self.ga["population_size"], []
            else:
                carried, kinds, pool = self._plan(self.generations[-1])
            chosen = []
            for kind in kinds:                                # every slot is selected before any evaluation
                entry = self.select(kind, pool)
                if entry is None:
                    break
                chosen.append(entry)
            if not chosen:                                    # not recorded (generation 1 is always full)
                return "space_exhausted", done
            listed = list(carried)
            self.generations.append(listed)
            for entry in chosen:
                stop = self._evaluate(entry, env)
                if stop is None:
                    listed.append(entry)
                    env.record(g, False, listed)
                    if self.failures >= GC.CONSECUTIVE_FAILURE_LIMIT:
                        stop = "repeated_failure"
                if stop is not None:
                    env.record(g, False, listed)
                    return stop, done
            env.record(g, True, listed)
            done = g
            scores = [entry["score"] for entry in listed if entry["state"] == "scored"]
            low = min(scores) if scores else None
            new_best = best if low is None else (low if best is None else min(best, low))
            if g >= 2:
                still = 0 if new_best is not None and (best is None or new_best < best) else still + 1
            best = new_best
            if g == self.ga["generations"]:
                return "generations_complete", done
            if len(self.seen) >= self.size:
                return "space_exhausted", done
            if g >= 2 and still >= self.ga["patience"]:
                return "no_change", done
        raise AssertionError("unreachable")


# ------------------------------------------------------------------ staged manifest (pure checks)
def _int(value: Any, low: int, high: int | None = None) -> bool:
    return type(value) is int and low <= value and (high is None or value <= high)


def _hex(value: Any) -> bool:
    return type(value) is str and SHA_RE.fullmatch(value) is not None


def _handle_of(value: Any, run_id: str, kind: str) -> bool:
    return type(value) is str and re.fullmatch(rf"obj://{re.escape(run_id)}/{kind}/[0-9a-f]{{64}}", value) is not None


def _residue_ok(value: Any) -> bool:
    return (type(value) is dict and set(value) == set(RESIDUE_KEYS) and _int(value["model_number"], 1) and
            type(value["chain_auth"]) is str and (value["chain_label"] is None or type(value["chain_label"]) is str)
            and type(value["seq_auth"]) is int and (value["seq_label"] is None or type(value["seq_label"]) is int)
            and type(value["icode"]) is str and type(value["resname"]) is str and value["resname"] != "")


def _ga_ok(ga: Any) -> bool:
    if type(ga) is not dict or set(ga) != set(GC.GA_KEYS):
        return False
    for key in GC.GA_KEYS:
        low, high, _default = GC.GA_RANGES[key]
        value = ga[key]
        if key in GC.GA_FLOAT_KEYS:
            if type(value) is not float or not math.isfinite(value) or not low <= value <= high:
                return False
        elif not _int(value, low, high):
            return False
    return (ga["population_size"] - ga["elite_count"] >= GC.MIN_NEW_SLOTS and
            ga["max_new_evaluations"] >= ga["population_size"])


def _reuse_fact(record: Any, keys: frozenset[str]) -> dict[str, Any]:
    _require(type(record) is dict and set(record) == keys, "reuse record keys")
    scored = record["state"] == "scored"
    _require(record["state"] in ("scored", "null_result") and record["reason_code"] is None and
             ((type(record["score"]) is float and math.isfinite(record["score"])) if scored else record["score"] is None)
             and all(type(record[k]) is str and record[k] for k in ("model_handle", "result_handle")),
             "a reuse record is a stored model and result: scored with a finite score, or null_result")
    return {"state": record["state"], "score": record["score"]}


def validate_manifest(p: Any) -> dict[str, Any]:
    """Check the staged manifest (ValueError otherwise); returns the space (``positions``, ``alts``), the reuse
    facts (``reused``: key text -> {state, score}) and the reference row's reuse record (``reference_reused``)."""
    _require(type(p) is dict and set(p) == MANIFEST_KEYS and p["schema"] == GC.WORKER_INPUT_SCHEMA, "manifest keys")
    _require(p["project_python"] == str(PROJECT_PYTHON) and PROJECT_PYTHON.is_file(),
             "project_python is not this checkout's .venv/bin/python")
    run_id = p["run_id"]
    _require(type(run_id) is str and RUN_ID_RE.fullmatch(run_id), "run_id")
    _require(_handle_of(p["candidate_set"], run_id, "mutation_candidate_set"), "candidate_set handle")
    structure, model_number = p["structure"], p["model_number"]
    _require(type(structure) is dict and set(structure) == {"handle", "model_number", "structure_kind"} and
             _handle_of(structure["handle"], run_id, STRUCTURE_KIND) and structure["structure_kind"] == STRUCTURE_KIND
             and _int(model_number, 1) and type(structure["model_number"]) is int and
             structure["model_number"] == model_number, "structure")
    _require(type(p["protein"]) is list and p["protein"], "protein projection")
    method = p["method"]
    _require(type(method) is dict and method and all(type(key) is str for key in method) and
             not set(method) & set(GC.MULTI_MUTATION_METHOD), "method")
    _require(_hex(p["selection_sha256"]) and _hex(p["conditions_sha256"]), "input hashes")
    ligand = p["ligand_sdf"]
    _require(type(ligand) is dict and set(ligand) == {"b64", "sha256"} and type(ligand["b64"]) is str and
             _hex(ligand["sha256"]), "ligand SDF entry")
    _require(type(p["box"]) is dict and p["box"].get("source") in ("ligand_range", "manual"), "box source")
    _require(type(p["parameters"]) is dict, "parameters")
    _require(_ga_ok(p["ga"]), "ga parameters")
    rows = p["candidates"]
    _require(type(rows) is list and 1 <= len(rows) <= GC.MAX_CANDIDATES, "candidates")
    alts: dict[int, list[int]] = {}
    for at, row in enumerate(rows):
        _require(type(row) is dict and set(row) == CANDIDATE_KEYS and row["index"] == at and type(row["index"]) is int
                 and _int(row["position_index"], 0) and _residue_ok(row["residue"]) and
                 all(type(row[k]) is str and LETTER_RE.fullmatch(row[k]) for k in ("from", "to")) and
                 row["from"] != row["to"] and type(row["mutant_resname"]) is str and
                 RESNAME_RE.fullmatch(row["mutant_resname"]), f"candidate {at}")
        _require(not alts or row["position_index"] >= max(alts), "candidates are in position storage order")
        first = rows[alts[row["position_index"]][0]] if row["position_index"] in alts else row
        _require(first["residue"] == row["residue"] and first["from"] == row["from"], "one residue per position")
        alts.setdefault(row["position_index"], []).append(at)
    positions = list(alts)
    _require(len(positions) <= GC.MAX_POSITIONS, "positions")
    _require(space_size([len(alts[q]) for q in positions], p["ga"]["max_mutations"]) >= p["ga"]["population_size"],
             "the combination space is smaller than population_size")
    position_of = {index: q for q in positions for index in alts[q]}
    _require(type(p["reuse"]) is list, "reuse")
    reused: dict[str, dict[str, Any]] = {}
    for record in p["reuse"]:
        fact = _reuse_fact(record, REUSE_KEYS)
        key = parse_key(record["key"])
        _require(all(index in position_of for index in key) and
                 len({position_of[index] for index in key}) == len(key), "reuse key outside the space")
        _require(record["key"] not in reused, "duplicate reuse key")
        reused[record["key"]] = fact
    reference = p["reference_reuse"]
    if reference is not None:
        _reuse_fact(reference, REUSE_KEYS | {"model_summary"})
        summary = reference["model_summary"]
        _require(reference["key"] == GC.REFERENCE_KEY and type(summary) is dict and set(summary) == SUMMARY_KEYS and
                 _hex(summary["structure_sha256"]) and type(summary["protonation_variants"]) is list and
                 type(summary["disulfide_bonds"]) is list, "reference reuse record")
    return {"positions": positions, "alts": alts, "reused": reused, "reference_reused": reference}


# ------------------------------------------------------------------ clocks and signals
class _Stop(BaseException):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Clock:
    active = False                  # a docking step may be interrupted
    cancelled = False
    step_deadline = float("inf")
    total_s = float(GC.TOTAL_S_MAX)


CLOCK = _Clock()


def _total_deadline() -> float:
    return STARTED_AT + min(TOTAL_LIMIT_S, CLOCK.total_s)


def _arm() -> None:
    remaining = min(CLOCK.step_deadline, _total_deadline()) - time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, max(remaining, 0.001))


def _on_alarm(_signum: int, _frame: Any) -> None:
    if not CLOCK.active:
        return
    now = time.monotonic()
    if now >= _total_deadline():
        CLOCK.active = False
        raise _Stop("time_exhausted")
    if now >= CLOCK.step_deadline:
        CLOCK.active = False
        raise _Stop("docking_timeout")
    _arm()   # early tick


def _on_term(_signum: int, _frame: Any) -> None:
    CLOCK.cancelled = True
    if CLOCK.active:
        CLOCK.active = False
        raise _Stop("cancelled")


def _quiet() -> None:
    """Stop interruptions: block the two signals, disarm the timer, leave the interruptible section."""
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    signal.setitimer(signal.ITIMER_REAL, 0)
    CLOCK.active = False


# ------------------------------------------------------------------ files
def _write_durable(path: Path, raw: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_regular(path: Path, limit: int) -> bytes:
    """A regular file (never a link) of at most ``limit`` bytes (ValueError otherwise)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, f"{path.name} is not a bounded regular file")
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, f"{path.name} over its bound")
    return raw


def _read_json(path: Path, limit: int) -> Any:
    return json.loads(_read_regular(path, limit), parse_constant=_reject_constant)


def _entry(raw: bytes) -> dict[str, str]:
    return {"b64": base64.b64encode(raw).decode(), "sha256": _sha(raw)}


def _output_bytes() -> int:
    """Bytes of every file this worker wrote for the server (prepared, reference, individual and generation files)."""
    files = [Path("prepared.json"), *Path(".").glob(REFERENCE_PREFIX + "*"), *IND_DIR.iterdir(), *GEN_DIR.iterdir()]
    return sum(os.lstat(path).st_size for path in files if os.path.lexists(path))


def _status(path: Path, state: str, reason: str | None, stage: str) -> None:
    allowed = (None,) if state != "failed" else GC.FAILURE_REASONS
    if state not in GC.STATES or reason not in allowed or stage not in GC.STAGES:
        raise ValueError("individual status outside the closed set")
    _write_durable(path, canonical_json({"state": state, "reason_code": reason, "stage": stage}))


def run_box(dw: Any, p: dict[str, Any]) -> dict[str, Any] | None:
    """The box every docking computes (``dock_row``'s free box steps) in the M18 result's shape; None when RDKit
    cannot read the ligand (the reference row's docking then refuses with the M18 reason)."""
    req = p["box"]
    if req["source"] == "manual":
        return {"center_A": [float(x) + 0.0 for x in req["center_A"]], "size_A": [float(x) + 0.0 for x in req["size_A"]],
                "source": "manual", "margin_A": None}
    try:
        points = dw._heavy_points(dw.read_sdf(dw._entry(p["ligand_sdf"]), parent=True))
        box = dw.range_box(points, float(req["margin_A"]))
    except (dw.DockingWorkerError, ValueError):
        return None
    return {"center_A": box["center_A"], "size_A": box["size_A"], "source": req["source"],
            "margin_A": float(req["margin_A"]) + 0.0}


# ------------------------------------------------------------------ the job environment
class Job:
    """The GA environment of one job: checks, the modeling child, the docking and the durable files."""

    def __init__(self, dw: Any, p: dict[str, Any], control: dict[str, Any]) -> None:
        self.dw, self.p, self.control = dw, p, control
        self.rows = {row["index"]: row for row in p["candidates"]}
        self.reference_summary: dict[str, Any] | None = None

    def cancelled(self) -> bool:
        return CLOCK.cancelled or signal.SIGTERM in signal.sigpending()

    def time_up(self) -> bool:
        return time.monotonic() >= _total_deadline()

    def output_full(self) -> bool:
        return _output_bytes() + PER_INDIVIDUAL_MAX > MAX_TOTAL_OUTPUT_BYTES

    def record(self, index: int, complete: bool, entries: list[dict[str, Any]]) -> None:
        records = [{"key": key_text(e["key"]), "origin": e["origin"], "parents": e["parents"], "edit_op": e["edit_op"],
                    "evaluation": e["evaluation"], "pick_index": e["pick_index"], "eval_index": e["eval_index"]}
                   for e in entries]
        _write_durable(GEN_DIR / f"{index}.json",
                       canonical_json({"index": index, "complete": complete, "individuals": records}))

    def reference(self, reused: dict[str, Any] | None) -> Outcome | str:
        if reused is not None:
            self.reference_summary = reused["model_summary"]
            _status(Path(REFERENCE_PREFIX + "status.json"), reused["state"], None, "docking")
            return reused["state"], None, reused["score"]
        return self._evaluate([], REFERENCE_PREFIX)

    def evaluate(self, key: tuple[int, ...], index: int) -> Outcome | str:
        _write_durable(IND_DIR / f"{index}.started", b"")
        rows = [{"candidate_index": c, "residue": self.rows[c]["residue"], "from": self.rows[c]["from"],
                 "to": self.rows[c]["to"], "mutant_resname": self.rows[c]["mutant_resname"]} for c in key]
        return self._evaluate(rows, f"{IND_DIR}/{index}.")

    # ---- one evaluation: model, then dock
    def _evaluate(self, rows: list[dict[str, Any]], prefix: str) -> Outcome | str:
        shutil.rmtree(WORK_DIR, ignore_errors=True)
        os.mkdir(WORK_DIR, 0o700)
        try:
            _write_durable(WORK_DIR / "model_input.json", self._model_input(rows))
            modeled = self._model(not rows)
            if isinstance(modeled, str):
                return modeled
            if modeled[0] == "failed":
                return self._store(prefix, None, None, ("failed", modeled[1], None), "model")
            _ok, model_raw, cif_raw, sidecar_raw, refusal, handle = modeled
            if refusal is not None:
                return self._store(prefix, (model_raw, cif_raw), None, ("failed", refusal, None), "docking")
            if self.cancelled():
                return "cancelled"
            if self.time_up():
                return "time_exhausted"
            docked = self._dock(self._payload(handle, cif_raw, sidecar_raw))
            if isinstance(docked, str):
                return docked
            return self._store(prefix, (model_raw, cif_raw), docked[2], (docked[0], docked[1], docked[3]), "docking")
        finally:
            _quiet()
            shutil.rmtree(WORK_DIR, ignore_errors=True)

    def _model_input(self, rows: list[dict[str, Any]]) -> bytes:
        p = self.p
        if rows and self.reference_summary is None:
            raise ValueError("a mutant is modeled only after the reference row's model")
        payload = {"schema": MODEL_INPUT_SCHEMA, "run_id": p["run_id"], "candidate_set": p["candidate_set"],
                   "structure": p["structure"], "method": p["method"], "model_number": p["model_number"],
                   "protein": p["protein"], "seed": p["parameters"]["seed"], "mutations": rows,
                   "reference": self.reference_summary if rows else None}
        return canonical_json({"input_sha256": _sha(canonical_json(payload)), "payload": payload})

    def _model(self, reference: bool) -> tuple[Any, ...] | str:
        """Run the modeling child: a run stop, ("failed", reason) or ("ok", model, cif, sidecar | None,
        receptor refusal | None, mmCIF handle)."""
        work = Path.cwd() / WORK_DIR
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1",
               "TMPDIR": str(work), "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
        streams = (work / "child.stdout", work / "child.stderr")
        deadline = time.monotonic() + MODEL_LIMIT_S
        try:
            with streams[0].open("xb") as out, streams[1].open("xb") as err:
                child = subprocess.Popen([self.p["project_python"], "-I", str(MODEL_PROGRAM)], cwd=work, env=env,
                                         stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True)
        except OSError:
            return "failed", "worker_failed"
        outcome: tuple[str, str] | str | None = None
        try:
            while child.poll() is None:
                if self.cancelled():
                    outcome = "cancelled"
                elif self.time_up():
                    outcome = "time_exhausted"
                elif time.monotonic() >= deadline:
                    outcome = "failed", "model_timeout"
                elif any(path.stat().st_size > CHILD_STREAM_LIMIT for path in streams):
                    outcome = "failed", "resource_exceeded"
                if outcome is not None:
                    break
                try:
                    child.wait(timeout=POLL_S)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
        if outcome is not None:
            return outcome
        return self._model_outputs(work, child.returncode, reference)

    def _model_outputs(self, work: Path, code: int, reference: bool) -> tuple[Any, ...]:
        try:
            if code == 1:
                error = _read_json(work / "error.json", CHILD_JSON_LIMIT)
                reason = error.get("reason_code") if type(error) is dict else None
                return "failed", reason if reason in GC.MODEL_FAILURE_REASONS else "worker_failed"
            _require(code == 0, "modeling child exit")
            names = set(os.listdir(work)) - CHILD_OWN
            refused = "receptor_error.json" in names
            _require(names == {*CHILD_OUTPUTS, "receptor_error.json" if refused else "receptor_bonds.json"},
                     "modeling child outputs")
            model_raw = _read_regular(work / "model.json", GC.MAX_MODEL_OBJECT_BYTES)
            cif_raw = _read_regular(work / "model.cif", PER_INDIVIDUAL_MAX)
            model = json.loads(model_raw, parse_constant=_reject_constant)
            side = GC.REFERENCE_SIDE if reference else GC.MUTANT_SIDE
            _require(type(model) is dict and model.get("schema") == GC.MODEL_SCHEMA and
                     type(model.get("structures")) is dict and set(model["structures"]) == {side}, "model side")
            entry = model["structures"][side]
            handle = entry["structure_object"]
            _require(_handle_of(handle, self.p["run_id"], "mutation_set_model_structure") and
                     entry["structure_sha256"] == _sha(cif_raw), "model mmCIF handle and hash")
            if refused:
                error = _read_json(work / "receptor_error.json", CHILD_JSON_LIMIT)
                refusal = error.get("reason_code") if type(error) is dict else None
                _require(refusal in GC.DOCKING_FAILURE_REASONS, "receptor refusal reason")
                sidecar_raw = None
            else:
                refusal, sidecar_raw = None, _read_regular(work / "receptor_bonds.json", self.dw.MAX_ENTRY_BYTES)
            if reference:
                summary = {key: entry[key] for key in SUMMARY_KEYS}
                _require(_hex(summary["structure_sha256"]) and type(summary["protonation_variants"]) is list and
                         type(summary["disulfide_bonds"]) is list, "reference model summary")
                self.reference_summary = summary
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            return "failed", "worker_failed"
        if len(model_raw) + len(cif_raw) + self.dw.K.MAX_RESULT_BYTES + CONTROL_LIMIT > PER_INDIVIDUAL_MAX:
            return "failed", "resource_exceeded"                # never stored, never truncated
        return "ok", model_raw, cif_raw, sidecar_raw, refusal, handle

    def _payload(self, handle: str, cif_raw: bytes, sidecar_raw: bytes) -> dict[str, Any]:
        p = self.p
        return {"schema": "docking_worker_input@1",
                "receptor": {"handle": handle, "format": "cif", "bytes": _entry(cif_raw),
                             "model_number": p["model_number"],
                             "connectivity": {"kind": "sidecar", "sidecar": _entry(sidecar_raw)}, "instance": None,
                             "source": "mutation_model"},
                "ligand": {"source": "sdf", "sdf": p["ligand_sdf"]}, "mode": GC.MODE, "box": p["box"],
                "parameters": p["parameters"]}

    def _dock(self, payload: dict[str, Any]) -> tuple[str, str | None, bytes | None, float | None] | str:
        """(state, reason, output bytes, first-mode score) of the docking step, or a run stop. Interrupted by
        ``_Stop`` only while ``receptor_inputs`` / ``dock_row`` run; the interruptions are stopped (``_quiet``) as soon
        as they return and before the private engine folder is removed, so a late tick or SIGTERM can neither drop a
        finished docking nor leave the folder behind (a blocked SIGTERM is the next check's ``cancelled``)."""
        dw = self.dw
        engine_dir = WORK_DIR / "qvina"
        os.mkdir(engine_dir, 0o700)
        CLOCK.step_deadline = time.monotonic() + DOCKING_LIMIT_S
        CLOCK.active = True
        _arm()
        try:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, SIGNALS)   # inside try: a pending signal raises here
            dw._validate_payload(payload)
            output = dw.dock_row(payload, engine_dir, dw.receptor_inputs(payload["receptor"]), None)
            _quiet()
        except _Stop as stop:
            _quiet()
            return ("failed", "docking_timeout", None, None) if stop.reason == "docking_timeout" else stop.reason
        except dw.DockingWorkerError as exc:
            _quiet()
            return "failed", exc.reason_code, None, None
        except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, MemoryError, RecursionError):
            _quiet()
            return "failed", "engine_failed", None, None   # M18 internal-error mapping
        finally:
            _quiet()
            shutil.rmtree(engine_dir, ignore_errors=True)
        raw = canonical_json({**output, "job_id": self.control["job_id"], "attempt_id": self.control["attempt_id"]})
        if not 0 < len(raw) <= dw.K.MAX_RESULT_BYTES:      # the M18 result cap: a failure, never truncated
            return "failed", "resource_exceeded", None, None
        if output["counts"]["null_result"]:
            return "null_result", None, raw, None
        return "scored", None, raw, output["modes"][0]["score_kcal_mol"]

    @staticmethod
    def _store(prefix: str, model: tuple[bytes, bytes] | None, result: bytes | None,
               outcome: tuple[str, str | None, float | None], stage: str) -> Outcome:
        if model is not None:
            _write_durable(Path(prefix + "model.json"), model[0])
            _write_durable(Path(prefix + "model.cif"), model[1])
        if result is not None:
            _write_durable(Path(prefix + "result.json"), result)
        _status(Path(prefix + "status.json"), outcome[0], outcome[1], stage)
        return outcome


# ------------------------------------------------------------------ entry points
def run_job(dw: Any) -> dict[str, Any]:
    if dw.versions() != dw.PINNED:
        raise dw._fatal("engine_failed", "pinned Meeko/RDKit/MDAnalysis/gemmi versions unavailable")
    try:
        control = json.loads(dw._read_bounded("input.json", CONTROL_LIMIT))
        raw = dw._read_bounded("structure.json", GC.MAX_STAGED_BYTES)
        payload = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeError) as exc:
        raise dw._malformed("staged JSON unreadable") from exc
    if (type(control) is not dict or control.get("adapter") != ADAPTER or
            type(control.get("input_sha256")) is not str or _sha(raw) != control["input_sha256"] or
            any(type(control.get(key)) is not str or not CONTROL_ID_RE.fullmatch(control[key])
                for key in ("job_id", "attempt_id"))):
        raise dw._malformed("control record or staged hash mismatch")
    try:
        checked = validate_manifest(payload)
    except (ValueError, KeyError, TypeError) as exc:
        raise dw._malformed(f"GA manifest: {exc}"[:200]) from exc
    dw._entry(payload["ligand_sdf"])                        # decodes and checks its SHA-256
    template = {"handle": payload["candidate_set"], "format": "cif", "bytes": payload["ligand_sdf"],
                "model_number": payload["model_number"],
                "connectivity": {"kind": "sidecar", "sidecar": payload["ligand_sdf"]}, "instance": None,
                "source": "mutation_model"}               # shape only: every docking payload has this form
    dw._validate_payload({"schema": "docking_worker_input@1", "receptor": template,
                          "ligand": {"source": "sdf", "sdf": payload["ligand_sdf"]}, "mode": GC.MODE,
                          "box": payload["box"], "parameters": payload["parameters"]})
    os.mkdir(IND_DIR, 0o700)
    os.mkdir(GEN_DIR, 0o700)
    CLOCK.total_s = float(payload["ga"]["total_s"])
    _write_durable(Path("prepared.json"), canonical_json({
        "box": run_box(dw, payload), "engine": dw.engine_identity(),
        "model_method": {**payload["method"], **GC.MULTI_MUTATION_METHOD}}))
    ga = Ga(checked["positions"], checked["alts"], payload["ga"], checked["reused"], checked["reference_reused"])
    stop, done = ga.run(Job(dw, payload, control))
    if stop not in GC.STOP_REASONS:
        raise ValueError("stop reason outside the closed set")
    return {"schema": GC.WORKER_OUTPUT_SCHEMA, "protocol": ADAPTER, "job_id": control["job_id"],
            "attempt_id": control["attempt_id"], "stop_reason": stop, "generations_done": done}


def handshake(dw: Any) -> dict[str, Any]:
    """The M18 handshake with this protocol and the module hashes; nothing is computed, nothing is run."""
    return {**dw.handshake(), "schema": "sequence_ga_worker_handshake@1", "protocols": [ADAPTER],
            "worker_sha256": _sha(HERE.read_bytes()), "row_worker_sha256": _sha(ROW_WORKER.read_bytes()),
            "ga_constants_sha256": _sha(Path(GC.__file__).read_bytes()),
            "model_worker_sha256": _sha(MODEL_PROGRAM.read_bytes()), "project_python": str(PROJECT_PYTHON),
            "project_python_present": PROJECT_PYTHON.is_file()}


def _write_error(envelope: dict[str, Any]) -> None:
    Path("error.json").write_bytes(canonical_json(envelope))


def main(argv: list[str]) -> int:
    dw = _load_by_path(ROW_WORKER, "docking_worker_pinned")   # denies Python sockets first
    if argv == ["--handshake"]:
        sys.stdout.write(json.dumps(handshake(dw), sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    if argv:
        return 2
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.signal(signal.SIGTERM, _on_term)
    try:
        output = canonical_json(run_job(dw))
    except dw.DockingWorkerError as exc:
        _write_error(exc.envelope())
        return 1
    _write_durable(Path("result.json"), output)
    return 0


def entry(argv: list[str]) -> int:
    try:
        return main(argv)
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, ImportError,
            MemoryError, RecursionError) as exc:
        _write_error({"schema": "docking_worker_error@1", "error_class": "fatal", "reason_code": "engine_failed",
                      "message": f"GA worker internal error ({type(exc).__name__})"[:240], "detail": {}})
        return 1


if __name__ == "__main__":
    raise SystemExit(entry(sys.argv[1:]))
