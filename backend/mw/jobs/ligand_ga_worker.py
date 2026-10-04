"""Fixed, isolated M22 GA design worker (spec .dryforge/spec.md 3, 7). JSON files only.

The guardian launches this script with the pinned ``.deps/docking/venv-locked`` interpreter, like the M18/M19
workers. Every individual is docked by the M18 worker's own functions (``docking_worker.py`` loaded by file path,
never a package import): ``receptor_inputs`` and ``receptor_prepared`` once per run, then ``dock_row`` per new
docking, so an individual's output is byte-identical to a standalone M18 ``qvina_dock_v1`` free job on the same
staged payload and control identity. RDKit is imported directly here for one purpose only: Morgan fingerprints of
the stored candidate SMILES (``rdFingerprintGenerator.GetMorganGenerator`` radius 2, 2048 bits, with the
generator defaults pinned below). The only other ``mw`` code used is the dependency-free
``mw/ligand_ga_constants.py`` (parameter ranges, limits, closed sets), loaded by file path.

Job mode (no arguments, cwd = private attempt directory). ``input.json`` = ``{adapter: "qvina_ga_dock_v1",
input_sha256 (of the structure.json bytes), job_id, attempt_id, ...}``; ``structure.json`` is the server's staged
manifest (byte entries ``{"b64", "sha256"}`` as in M18)::

    {"schema": "ligand_ga_worker_input@1",
     "receptor": <M18 docking_worker_input@1 receptor block>,      # shared by every individual
     "parent_sdf": entry,                                         # the M17 candidate set's parent SDF bytes
     "candidate_set_parent_sha256": hex,                          # ligand_candidate_set@1 parent_sha256
     "box": <M18 box>, "parameters": <M18 free parameters>,       # one per run (mode is fixed to free)
     "ga": {seed, population_size, generations, elite_count, tournament_size, neighbor_count,
            random_fraction, patience, max_new_dockings, total_s},  # every GA_KEYS value (server-normalized)
     "pool": [{"index": int (= list position = the candidate set's stored order), "candidate_id": str,
               "smiles": str, "eligible": bool,                    # eligible = the filter verdict (server)
               "retained_parent_atoms": [int] | null, "stereo_flag": str | null,  # eligible only (M18 fields)
               "input_sha256": hex | null,                         # eligible only: the individual's M18 input hash
               "reuse_result_bytes": entry | null}]}               # eligible only: a stored M18 result to reuse

Individual ``k`` (= ``eval_index``, 0, 1, ... in evaluation order across the run; carried individuals take none)
is run as the M18 payload ``{"schema": "docking_worker_input@1", "receptor", "mode": "free", "box", "parameters",
"ligand": {"source": "candidate", "parent_sdf", "candidate_set_parent_sha256", "candidate": {"id", "smiles",
"retained_parent_atoms", "stereo_flag"}}}``: exactly what ``mw.docking_bundle.stage`` stages for that candidate's
M18 selection. A reused individual (``reuse_result_bytes`` set) is not docked and gets no file; its score and state
are read from the stored result (first mode; no modes = ``null_result``).

GA procedure (spec 3, deterministic): ``random.Random(ga.seed)``; the only calls are ``rng.sample`` and
``rng.choice``, in this order: generation 1 ``rng.sample(eligible ids in pool order, population_size)``; each later
generation fills its similar slots in slot order (per slot ``rng.sample(previous generation's scored individuals,
carried first then evaluation order, min(tournament_size, count))`` then ``rng.choice(neighbours)``), then its random
slots in slot order (``rng.choice(unpicked eligible ids in pool order)``). Carried = the previous generation's
``elite_count`` lowest-score scored individuals (ties in pool order), not re-docked. ``slots = population_size -
carried``; random slots ``floor(random_fraction * slots + 0.5)`` (every slot when no individual is scored); the
parent is the tournament's lowest score (ties pool order); neighbours = the ``neighbor_count`` unpicked eligible
candidates of highest Tanimoto to the parent (full precision, ties pool order). "Unpicked" = never picked in this
run. When no unpicked candidate is left a slot stays empty and no rng call is made; a generation with no new
individual is not recorded and the run ends ``pool_exhausted``. A generation lists carried individuals first, then
the new ones in evaluation order (= selection order). Score-less individuals (``null_result``, ``failed``) are never
carried or parents. Tanimoto = |A & B| / |A | B| of the fingerprint on-bit sets (the RDKit Tanimoto of these bit
vectors: an integer ratio, so the float division equals RDKit's double); the stored similarity is the exact ratio
rounded ROUND_HALF_UP to 6 decimals, as a string.

Stops (closed set): after generation ``generations`` ``generations_complete`` (patience is not looked at there);
after a complete generation g >= 2 the running minimum score (every evaluation so far) is compared with the value
at the end of generation g - 1 (null -> number is a decrease, null -> null is not) and ``patience`` consecutive
non-decreases end the run ``no_change``. Before each individual: a cancel (``cancelled``), then a new docking needed
while new dockings already equal ``reserved_units = min(max_new_dockings, P + (G - 1)(P - E))`` (``docking_limit``),
then the total clock (``time_exhausted``). During a docking: the per-individual clock (the individual ``failed``
``candidate_timeout``, the run continues), the total clock (``time_exhausted``) and SIGTERM (``cancelled``); an
interrupted individual keeps only ``<k>.started`` and is not listed. An individual result that would pass the total
output cap is not stored and the run ends ``resource_exceeded`` (the individual is not listed). A docking failure
or null result is evaluated (no retry) and counts as a new docking. On every stop inside a generation that
generation is written with ``complete: false`` and its carried + evaluated individuals (none dropped).

Durable files (temporary file + fsync + ``os.replace`` + directory fsync), signals blocked while writing:
``prepared.json`` (canonical ``{"box": <the run box in the M18 result's shape>, "engine": <engine identity>}``)
after the receptor preparation and before any individual; ``individuals/<k>.started`` (empty) when a new docking
starts, then ``individuals/<k>.result.json`` (the M18 ``docking_worker_output@1`` bytes with this job's
``job_id``/``attempt_id``; scored and null_result only) and ``individuals/<k>.status.json`` (canonical
``{"reason_code": str | null, "state": "scored" | "null_result" | "failed"}``); ``generations/<g>.json`` (canonical
``{"index", "complete", "individuals": [{"candidate_id", "origin", "parent_candidate_id", "similarity",
"evaluation", "eval_index"}]}``) rewritten with ``complete: false`` after every evaluated individual and finally at
the generation's end (``complete: true``) or at the stop. Scores and states are never written into the generation
records: the server rebuilds them from the individual files and the stored results.

On a normal end the worker writes canonical ``result.json`` ``{"attempt_id", "generations_done", "job_id",
"protocol", "schema": "ligand_ga_worker_output@1", "stop_reason"}`` and exits 0. A stop during the receptor
preparation writes no other file. A malformed manifest or a receptor/box/engine refusal before any individual (M18
reasons) writes the M18 ``error.json`` envelope and exits 1.
"""
from __future__ import annotations

import time

STARTED_AT = time.monotonic()   # total clock origin: worker start, before the chemistry imports

import importlib.util
import json
import math
import os
import random
import shutil
import signal
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any


def _load_by_path(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{name} unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve()
dw = _load_by_path(HERE.with_name("docking_worker.py"), "docking_worker_pinned")   # denies Python sockets first
GC = _load_by_path(HERE.parents[1] / "ligand_ga_constants.py", "ligand_ga_constants_pinned")
K = dw.K

# RDKit after the docking worker denied sockets; used for the Morgan fingerprints only.
from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator

ADAPTER = GC.PROTOCOL
MODE = GC.MODE
# Spec 2 / 10 limits (code constants in ligand_ga_constants; tests shrink these module copies only).
ROW_LIMIT_S = float(GC.PER_CANDIDATE_S)
TOTAL_LIMIT_S = float(GC.TOTAL_S_MAX)           # ceiling; the run's own clock is min(this, ga.total_s)
MAX_TOTAL_OUTPUT_BYTES = GC.MAX_OUTPUT_BYTES    # sum of individuals/*.result.json
MAX_STAGED_BYTES = GC.MAX_STAGED_BYTES
FINGERPRINT = {"radius": GC.FINGERPRINT["radius"], "fpSize": GC.FINGERPRINT["n_bits"], "countSimulation": False,
               "includeChirality": False, "useBondTypes": True, "onlyNonzeroInvariants": False,
               "includeRingMembership": True}   # the generator defaults, pinned
POOL_ROW_KEYS = {"index", "candidate_id", "smiles", "eligible", "retained_parent_atoms", "stereo_flag",
                 "input_sha256", "reuse_result_bytes"}
MANIFEST_KEYS = {"schema", "receptor", "parent_sdf", "candidate_set_parent_sha256", "box", "parameters", "ga",
                 "pool"}
STATE_REASONS = {"scored": (None,), "null_result": (None,), "failed": K.REASONS + GC.FAILED_EXTRA_REASONS}
IND_DIR = Path("individuals")
GEN_DIR = Path("generations")
SIGNALS = {signal.SIGALRM, signal.SIGTERM}


class _Stop(BaseException):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Clock:
    active = False                  # a docking (or the receptor preparation) may be interrupted
    cancelled = False
    row_deadline = float("inf")
    total_s = float(GC.TOTAL_S_MAX)


CLOCK = _Clock()


def _total_deadline() -> float:
    return STARTED_AT + min(TOTAL_LIMIT_S, CLOCK.total_s)


def _arm() -> None:
    remaining = min(CLOCK.row_deadline, _total_deadline()) - time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, max(remaining, 0.001))


def _on_alarm(_signum: int, _frame: Any) -> None:
    if not CLOCK.active:
        return
    now = time.monotonic()
    if now >= _total_deadline():
        CLOCK.active = False
        raise _Stop("time_exhausted")
    if now >= CLOCK.row_deadline:
        CLOCK.active = False
        raise _Stop("candidate_timeout")
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


def _status(index: int, state: str, reason: str | None) -> None:
    if state not in GC.STATES or reason not in STATE_REASONS[state]:
        raise ValueError("individual status outside the closed set")
    _write_durable(IND_DIR / f"{index}.status.json", dw.canonical_json({"state": state, "reason_code": reason}))


def _write_generation(index: int, complete: bool, individuals: list[dict[str, Any]]) -> None:
    _write_durable(GEN_DIR / f"{index}.json",
                   dw.canonical_json({"index": index, "complete": complete, "individuals": individuals}))


# ------------------------------------------------------------------ staged manifest
def _ga_ok(ga: Any) -> bool:
    if type(ga) is not dict or set(ga) != set(GC.GA_KEYS):
        return False
    for key in GC.GA_KEYS:
        low, high, _default = GC.GA_RANGES[key]
        value = ga[key]
        if key in GC.GA_FLOAT_KEYS:
            if type(value) is not float or not math.isfinite(value) or not low <= value <= high:
                return False
        elif type(value) is not int or not low <= value <= high:
            return False
    return (ga["population_size"] - ga["elite_count"] >= GC.MIN_NEW_SLOTS and
            ga["population_size"] <= ga["max_new_dockings"])


def _row_ok(row: Any, position: int) -> bool:
    if type(row) is not dict or set(row) != POOL_ROW_KEYS or row["index"] != position or type(row["index"]) is not int:
        return False
    if type(row["candidate_id"]) is not str or not row["candidate_id"] or type(row["smiles"]) is not str or \
            type(row["eligible"]) is not bool:
        return False
    if not row["eligible"]:
        return all(row[key] is None for key in ("retained_parent_atoms", "stereo_flag", "input_sha256",
                                                "reuse_result_bytes"))
    return (type(row["retained_parent_atoms"]) is list and type(row["stereo_flag"]) is str and
            type(row["input_sha256"]) is str and dw.SHA_RE.fullmatch(row["input_sha256"]) is not None)


def _reused_score(row: dict[str, Any]) -> tuple[str, float | None]:
    """(state, first-mode score) of a staged stored result of this candidate (an M18 result or worker output)."""
    try:
        data = json.loads(dw._entry(row["reuse_result_bytes"]))
    except (ValueError, UnicodeError) as exc:
        raise dw._malformed("reused result unreadable") from exc
    modes = data.get("modes") if type(data) is dict else None
    ligand = data.get("inputs", {}).get("ligand") if type(data) is dict and type(data.get("inputs")) is dict else None
    if type(modes) is not list or type(ligand) is not dict or ligand.get("candidate_id") != row["candidate_id"] or \
            data.get("method") != K.METHODS[MODE]:
        raise dw._malformed("reused result is not this candidate's free docking")
    if not modes:
        return "null_result", None
    score = modes[0].get("score_kcal_mol") if type(modes[0]) is dict else None
    if type(score) is not float or not math.isfinite(score):
        raise dw._malformed("reused result score")
    return "scored", score


def _validate_manifest(p: Any) -> dict[str, tuple[str, float | None]]:
    """Check the manifest shape; returns candidate id -> (state, score) of every reused individual."""
    ok = (type(p) is dict and set(p) == MANIFEST_KEYS and p["schema"] == GC.WORKER_INPUT_SCHEMA and
          type(p["candidate_set_parent_sha256"]) is str and
          dw.SHA_RE.fullmatch(p["candidate_set_parent_sha256"]) is not None and _ga_ok(p["ga"]) and
          type(p["pool"]) is list and 1 <= len(p["pool"]) <= GC.MAX_POOL)
    rows = p["pool"] if ok else []
    ok = ok and all(_row_ok(row, position) for position, row in enumerate(rows))
    ids = [row["candidate_id"] for row in rows] if ok else []
    eligible = [row for row in rows if ok and row["eligible"]]
    if not ok or len(set(ids)) != len(ids) or len(eligible) < p["ga"]["population_size"]:
        raise dw._malformed("GA manifest shape")
    for row in eligible:
        dw._validate_payload(individual_payload(p, row))   # every eligible candidate is a valid M18 payload
    return {row["candidate_id"]: _reused_score(row) for row in eligible if row["reuse_result_bytes"] is not None}


def individual_payload(p: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """One eligible pool row as the M18 ``docking_worker_input@1`` payload (``docking_bundle.stage`` shape)."""
    candidate = {"id": row["candidate_id"], "smiles": row["smiles"],
                 "retained_parent_atoms": row["retained_parent_atoms"], "stereo_flag": row["stereo_flag"]}
    return {"schema": "docking_worker_input@1", "receptor": p["receptor"],
            "ligand": {"source": "candidate", "parent_sdf": p["parent_sdf"],
                       "candidate_set_parent_sha256": p["candidate_set_parent_sha256"], "candidate": candidate},
            "mode": MODE, "box": p["box"], "parameters": p["parameters"]}


# ------------------------------------------------------------------ fingerprints and similarity
def fingerprints(smiles: dict[str, str]) -> dict[str, frozenset[int]]:
    """Candidate id -> Morgan (radius 2, 2048 bits) on-bit set of the stored SMILES."""
    generator = rdFingerprintGenerator.GetMorganGenerator(**FINGERPRINT)
    out = {}
    for cid, text in smiles.items():
        mol = Chem.MolFromSmiles(text)
        if mol is None:
            raise dw._malformed("a stored candidate SMILES does not parse")
        out[cid] = frozenset(generator.GetFingerprint(mol).GetOnBits())
    return out


def tanimoto(a: frozenset[int], b: frozenset[int]) -> Fraction:
    common = len(a & b)
    union = len(a) + len(b) - common
    return Fraction(common, union) if union else Fraction(0)


def round6(value: Fraction) -> str:
    """ROUND_HALF_UP of the exact ratio to 6 decimals, as a decimal string (0 <= value <= 1)."""
    scaled = value * 10**6
    whole = math.floor(scaled)
    up = whole + (1 if scaled - whole >= Fraction(1, 2) else 0)
    digits = str(up).rjust(7, "0")
    return f"{digits[:-6]}.{digits[-6:]}"


def reserved_units(ga: dict[str, Any]) -> int:
    """Spec 6 (= ``ligand_ga_inputs.reserved_units``): the units reserved before the start, never more."""
    population, elite = ga["population_size"], ga["elite_count"]
    return min(ga["max_new_dockings"], population + (ga["generations"] - 1) * (population - elite))


# ------------------------------------------------------------------ run box and one docking
def run_box(p: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    """The box every individual computes (``dock_row``'s free box steps, as M19 ``batch_box``) in the M18 result's
    shape. A refusal (``box_*``, unreadable parent) fails the run before any individual."""
    req, receptor = p["box"], shared["checked"]
    rows = receptor["rows"]
    if req["source"] == "manual":
        box = {"center_A": [float(x) + 0.0 for x in req["center_A"]], "size_A": [float(x) + 0.0 for x in req["size_A"]]}
    elif req["source"] == "instance_range":
        if not receptor["instance_sites"]:
            raise dw._refuse("box_invalid", "instance_range needs a receptor_instance")
        box = dw.range_box([rows[s]["coordinate_A"] for s in receptor["instance_sites"]
                            if rows[s]["element"].upper() != "H"] or
                           [rows[s]["coordinate_A"] for s in receptor["instance_sites"]], float(req["margin_A"]))
    else:
        parent = dw.read_sdf(dw._entry(p["parent_sdf"]), parent=True)
        box = dw.range_box(dw._heavy_points(parent), float(req["margin_A"]))
    dw.check_box(box, [atom["xyz"] for atom in shared["heavy"]])
    return {"center_A": box["center_A"], "size_A": box["size_A"], "source": req["source"],
            "margin_A": None if req["source"] == "manual" else float(req["margin_A"]) + 0.0}


def _dock(payload: dict[str, Any], shared: dict[str, Any], prepared: tuple[str, dict[str, Any]],
          control: dict[str, Any]) -> tuple[str, str | None, bytes | None, float | None]:
    """(state, reason, output bytes, first-mode score) of one docking; interrupted by ``_Stop`` only while
    ``dock_row`` runs: the interruptions are stopped (``_quiet``) as soon as it returns and before the private
    directory is removed, so a late timer tick or SIGTERM can neither drop a finished docking nor leave the
    directory behind (it stays pending for the check before the next individual). A directory left by an earlier
    interrupted removal is removed first."""
    workdir = Path("qvina_work")
    shutil.rmtree(workdir, ignore_errors=True)
    os.mkdir(workdir, 0o700)
    try:
        output = dw.dock_row(payload, workdir, shared, prepared)
        _quiet()
        raw = dw.canonical_json({**output, "job_id": control["job_id"], "attempt_id": control["attempt_id"]})
        if not 0 < len(raw) <= K.MAX_RESULT_BYTES:   # the M18 result cap: a failure, never truncated
            return "failed", "resource_exceeded", None, None
        if output["counts"]["null_result"]:
            return "null_result", None, raw, None
        return "scored", None, raw, output["modes"][0]["score_kcal_mol"]
    except dw.DockingWorkerError as exc:
        return "failed", exc.reason_code, None, None
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, MemoryError, RecursionError):
        return "failed", "engine_failed", None, None   # M18 internal-error mapping
    finally:
        _quiet()
        shutil.rmtree(workdir, ignore_errors=True)


# ------------------------------------------------------------------ GA
class _Run:
    """The GA state of one run: rng, picks, scores, counters and the staged context."""

    def __init__(self, p: dict[str, Any], control: dict[str, Any], reused: dict[str, tuple[str, float | None]],
                 bits: dict[str, frozenset[int]], shared: dict[str, Any], prepared: tuple[str, dict[str, Any]]):
        self.p, self.control, self.reused, self.bits = p, control, reused, bits
        self.shared, self.prepared = shared, prepared
        self.ga = p["ga"]
        self.rows = {row["candidate_id"]: row for row in p["pool"]}
        self.order = {row["candidate_id"]: row["index"] for row in p["pool"]}
        self.eligible = [row["candidate_id"] for row in p["pool"] if row["eligible"]]
        self.rng = random.Random(self.ga["seed"])
        self.picked: set[str] = set()
        self.score: dict[str, float | None] = {}
        self.reserved = reserved_units(self.ga)
        self.eval_index = 0
        self.new = 0
        self.output = 0

    def _key(self, entry: dict[str, Any]) -> tuple[float, int]:
        return self.score[entry["candidate_id"]], self.order[entry["candidate_id"]]

    def _unpicked(self) -> list[str]:
        return [cid for cid in self.eligible if cid not in self.picked]

    def _pick(self, cid: str, origin: str, parent: str | None, similarity: str | None) -> dict[str, Any]:
        self.picked.add(cid)
        return {"candidate_id": cid, "origin": origin, "parent_candidate_id": parent, "similarity": similarity,
                "evaluation": None, "eval_index": None}

    def first(self) -> list[dict[str, Any]]:
        return [self._pick(cid, "initial", None, None)
                for cid in self.rng.sample(self.eligible, self.ga["population_size"])]

    def next(self, previous: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(carried, new picks) of the next generation from the previous generation's individuals."""
        ranked = [e for e in previous if self.score[e["candidate_id"]] is not None]
        elite = sorted(ranked, key=self._key)[:self.ga["elite_count"]]
        carried = [{"candidate_id": e["candidate_id"], "origin": "carried", "parent_candidate_id": None,
                    "similarity": None, "evaluation": None, "eval_index": None} for e in elite]
        slots = self.ga["population_size"] - len(carried)
        randoms = math.floor(self.ga["random_fraction"] * slots + 0.5) if ranked else slots
        chosen = []
        for _ in range(slots - randoms):
            unpicked = self._unpicked()
            if not unpicked:
                break
            tour = self.rng.sample(ranked, min(self.ga["tournament_size"], len(ranked)))
            parent = min(tour, key=self._key)["candidate_id"]
            ratio = {cid: tanimoto(self.bits[parent], self.bits[cid]) for cid in unpicked}
            neighbours = sorted(unpicked, key=lambda cid: (-float(ratio[cid]), self.order[cid]))
            child = self.rng.choice(neighbours[:self.ga["neighbor_count"]])
            chosen.append(self._pick(child, "similar", parent, round6(ratio[child])))
        for _ in range(randoms):
            unpicked = self._unpicked()
            if not unpicked:
                break
            chosen.append(self._pick(self.rng.choice(unpicked), "random", None, None))
        return carried, chosen

    def evaluate(self, entry: dict[str, Any]) -> str | None:
        """Evaluate one picked individual (reuse or one new docking); None, or the stop reason (not evaluated)."""
        cid = entry["candidate_id"]
        if CLOCK.cancelled or signal.SIGTERM in signal.sigpending():
            return "cancelled"
        reuse = self.reused.get(cid)
        if reuse is None and self.new >= self.reserved:
            return "docking_limit"
        if time.monotonic() >= _total_deadline():
            return "time_exhausted"
        index = self.eval_index
        if reuse is not None:
            entry.update(evaluation="reused", eval_index=index)
            self.score[cid] = reuse[1]
            self.eval_index += 1
            return None
        _write_durable(IND_DIR / f"{index}.started", b"")
        CLOCK.row_deadline = time.monotonic() + ROW_LIMIT_S
        CLOCK.active = True
        _arm()
        try:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, SIGNALS)
            state, reason, raw, score = _dock(individual_payload(self.p, self.rows[cid]), self.shared,
                                              self.prepared, self.control)
            _quiet()
        except _Stop as stop:
            _quiet()
            if stop.reason != "candidate_timeout":
                return stop.reason              # cancelled | time_exhausted: only <k>.started is left
            state, reason, raw, score = "failed", "candidate_timeout", None, None
        if raw is not None and self.output + len(raw) > MAX_TOTAL_OUTPUT_BYTES:
            return "resource_exceeded"          # this result is not stored, the individual is not listed
        if raw is not None:
            _write_durable(IND_DIR / f"{index}.result.json", raw)
            self.output += len(raw)
        _status(index, state, reason)
        entry.update(evaluation="docked", eval_index=index)
        self.score[cid] = score
        self.new += 1
        self.eval_index += 1
        return None

    def run(self) -> tuple[str, int]:
        """All generations; (stop reason, complete generations)."""
        best: float | None = None
        still = 0
        done = 0
        listed: list[dict[str, Any]] = []
        for g in range(1, self.ga["generations"] + 1):
            if g == 1:
                carried, chosen = [], self.first()
            else:
                carried, chosen = self.next(listed)
                if not chosen:
                    return "pool_exhausted", done
            listed = list(carried)
            for entry in chosen:
                stop = self.evaluate(entry)
                if stop is not None:
                    _write_generation(g, False, listed)
                    return stop, done
                listed.append(entry)
                _write_generation(g, False, listed)
            _write_generation(g, True, listed)
            done = g
            scores = [self.score[e["candidate_id"]] for e in listed if self.score[e["candidate_id"]] is not None]
            low = min(scores) if scores else None
            new_best = best if low is None else (low if best is None else min(best, low))
            if g >= 2:
                still = 0 if new_best is not None and (best is None or new_best < best) else still + 1
            best = new_best
            if g == self.ga["generations"]:
                return "generations_complete", done
            if g >= 2 and still >= self.ga["patience"]:
                return "no_change", done
        raise AssertionError("unreachable")


def run_ga(p: dict[str, Any], control: dict[str, Any], reused: dict[str, tuple[str, float | None]]
           ) -> tuple[str, int]:
    """Fingerprints, the receptor once, ``prepared.json``, then the generations; (stop reason, generations done)."""
    CLOCK.total_s = float(p["ga"]["total_s"])
    bits = fingerprints({row["candidate_id"]: row["smiles"] for row in p["pool"] if row["eligible"]})
    CLOCK.active = True
    _arm()
    try:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, SIGNALS)   # inside try: a pending signal raises here
        shared = dw.receptor_inputs(p["receptor"])
        prepared = dw.receptor_prepared(shared)
    except _Stop as stop:
        _quiet()
        return ("cancelled" if stop.reason == "cancelled" else "time_exhausted"), 0
    finally:
        _quiet()
    _write_durable(Path("prepared.json"), dw.canonical_json({"box": run_box(p, shared), "engine": prepared[1]}))
    return _Run(p, control, reused, bits, shared, prepared).run()


def run_job() -> dict[str, Any]:
    if dw.versions() != dw.PINNED:
        raise dw._fatal("engine_failed", "pinned Meeko/RDKit/MDAnalysis/gemmi versions unavailable")
    try:
        control = json.loads(dw._read_bounded("input.json", 4096))
        raw = dw._read_bounded("structure.json", MAX_STAGED_BYTES)
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise dw._malformed("staged JSON unreadable") from exc
    if (type(control) is not dict or control.get("adapter") != ADAPTER or
            type(control.get("input_sha256")) is not str or dw._sha(raw) != control["input_sha256"] or
            any(type(control.get(key)) is not str or not dw.CONTROL_ID_RE.fullmatch(control[key])
                for key in ("job_id", "attempt_id"))):
        raise dw._malformed("control record or staged hash mismatch")
    reused = _validate_manifest(payload)
    os.mkdir(IND_DIR, 0o700)
    os.mkdir(GEN_DIR, 0o700)
    stop, done = run_ga(payload, control, reused)
    if stop not in GC.STOP_REASONS:
        raise ValueError("stop reason outside the closed set")
    return {"schema": GC.WORKER_OUTPUT_SCHEMA, "protocol": ADAPTER, "job_id": control["job_id"],
            "attempt_id": control["attempt_id"], "stop_reason": stop, "generations_done": done}


def handshake() -> dict[str, Any]:
    """The M18 handshake with this protocol and the module hashes; nothing is computed, qvina2 is not run."""
    return {**dw.handshake(), "schema": "ligand_ga_worker_handshake@1", "protocols": [ADAPTER],
            "worker_sha256": dw._sha(HERE.read_bytes()),
            "row_worker_sha256": dw._sha(Path(dw.__file__).read_bytes()),
            "ga_constants_sha256": dw._sha(Path(GC.__file__).read_bytes())}


def main(argv: list[str]) -> int:
    if argv == ["--handshake"]:
        sys.stdout.write(json.dumps(handshake(), sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    if argv:
        return 2
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.signal(signal.SIGTERM, _on_term)
    output = dw.canonical_json(run_job())
    _write_durable(Path("result.json"), output)
    return 0


def entry(argv: list[str]) -> int:
    try:
        return main(argv)
    except dw.DockingWorkerError as exc:
        dw._write_error(exc.envelope())
        return 1
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, ImportError,
            MemoryError, RecursionError) as exc:
        dw._write_error({"schema": "docking_worker_error@1", "error_class": "fatal", "reason_code": "engine_failed",
                         "message": f"GA worker internal error ({type(exc).__name__})"[:240], "detail": {}})
        return 1


if __name__ == "__main__":
    raise SystemExit(entry(sys.argv[1:]))
