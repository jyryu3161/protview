"""M22 GA admission, GA parameter normalization, filter eligibility, pool and selection record, reuse index from
M18 call keys, reserved units / need / shortfall / limit raise (spec .dryforge/spec.md 2, 3, 6, 7, 10).

No RDKit, no Meeko, no events. Every individual is a standalone M18 ``qvina_dock_v1`` free request: its arguments
are ``docking_batch_inputs.row_arguments`` on the shared fields (mode fixed to free), so its ``input_sha256`` and
call key (``docking_bundle.call_key``) are exactly those of a standalone M18 request.

Argument shape (fixed; unknown or missing keys ``invalid_job_arguments``): the M18/M19 receptor, box, parameter and
acknowledgement fields with their M18 names and rules, ``candidate_set_handle``, ``parent_sdf_handle``, ``filter``
(optional, default ``{}``, ``ligand_filters.normalize_filter_spec``) and ``ga`` (every key of
``GA_KEYS``). There is no ``mode`` key. The job's ``timeout_s`` is checked here too (no server default).

Admission order (spec 2): 1 ``invalid_job_arguments`` (keys, ``ga`` ranges and cross rules, ``timeout_s``, filter),
2 the M18 reasons (pure shared fields; the candidate set's kind/run/publication without a candidate id; then the
first eligible candidate as the representative through ``docking_bundle.submission``), 3 ``ga_pool_too_small``
(zero eligible is refused before the representative, since there is none), 4 ``ga_reuse_too_large``,
5 ``ga_limit_raise_required`` (429). Steps 4 and 5 need stored results and the run budget; the pure parts are here.

Budget figures use the run budget snapshot shape ``{axis: {"used", "limit"}}`` (as M19).
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from . import docking_batch_inputs, docking_bundle, docking_inputs, ligand_filters
from . import ligand_ga_constants as GC
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json

TOP_KEYS = frozenset({"receptor_handle", "receptor_model_number", "connectivity", "receptor_instance",
                      "candidate_set_handle", "parent_sdf_handle", "box", "parameters", "acknowledgement",
                      "filter", "ga"})
OPTIONAL_KEYS = frozenset({"acknowledgement", "filter"})
M18_KEYS = ("receptor_handle", "receptor_model_number", "connectivity", "receptor_instance", "box", "parameters",
            "acknowledgement")
PLACEHOLDER_ID = "ga_pool"            # shape-only stand-in candidate id for the pure M18 check (never stored)
CANDIDATE_FIELDS = ("id", "smiles", "retained_parent_atoms", "stereo_flag")
AXES = docking_batch_inputs.AXES


def _fail(reason: str, message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason, **detail})


def _args_error(message: str) -> ToolFailure:
    return _fail("invalid_job_arguments", message)


# ---------------------------------------------------------------- job arguments (pure)
def _int_in(value: Any, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def normalize_ga(value: Any) -> dict[str, Any]:
    """Spec 2 table: every key required, integers not bool, ``random_fraction`` a finite real; cross rules
    ``population_size - elite_count >= 2`` and ``population_size <= max_new_dockings``."""
    if type(value) is not dict or set(value) != set(GC.GA_KEYS):
        raise _args_error("ga needs exactly the keys " + ", ".join(GC.GA_KEYS))
    out: dict[str, Any] = {}
    for key in GC.GA_KEYS:
        low, high, _default = GC.GA_RANGES[key]
        item = value[key]
        if key in GC.GA_FLOAT_KEYS:
            if type(item) not in (int, float) or not math.isfinite(item) or not low <= item <= high:
                raise _args_error(f"ga.{key} must be a finite number {low}-{high}")
            out[key] = float(item) + 0.0
        elif not _int_in(item, low, high):
            raise _args_error(f"ga.{key} must be an integer {low}-{high}")
        else:
            out[key] = item
    if out["population_size"] - out["elite_count"] < GC.MIN_NEW_SLOTS:
        raise _args_error("ga.population_size - ga.elite_count must be at least 2")
    if out["max_new_dockings"] < out["population_size"]:
        raise _args_error("ga.max_new_dockings must be at least ga.population_size")
    return out


def _timeout(timeout_s: Any, total_s: int) -> None:
    if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or
            not total_s + GC.FINISH_MARGIN_S <= timeout_s <= GC.TIMEOUT_MAX_S):
        raise _args_error(f"timeout_s must be total_s + {GC.FINISH_MARGIN_S} to {GC.TIMEOUT_MAX_S} seconds")


def m18_shared(normalized: dict[str, Any]) -> dict[str, Any]:
    """The GA arguments in the shape ``docking_batch_inputs.row_request`` takes (mode fixed to free)."""
    return {**{key: normalized[key] for key in M18_KEYS}, "mode": GC.MODE,
            "candidate_set_handle": normalized["candidate_set_handle"],
            "parent_sdf_handle": normalized["parent_sdf_handle"]}


def validate_arguments(args: Any, timeout_s: Any) -> dict[str, Any]:
    """Validate ``qvina_ga_dock_v1`` arguments and the job ``timeout_s`` (shape and values only): step 1, then the
    M18 rules on the shared fields (their own reason codes)."""
    if type(args) is not dict:
        raise _args_error("job arguments must be an object")
    if not set(args) <= TOP_KEYS or not TOP_KEYS - OPTIONAL_KEYS <= set(args):
        raise _args_error("job arguments have unknown or missing keys")
    ga = normalize_ga(args["ga"])
    _timeout(timeout_s, ga["total_s"])
    try:
        spec = ligand_filters.normalize_filter_spec(args.get("filter", {}))
    except ToolFailure as exc:
        raise _args_error("filter is not a valid M17 filter spec") from exc
    template = {key: args[key] for key in M18_KEYS if key in args}
    template["mode"] = GC.MODE
    template["ligand"] = {"source": "candidate", "candidate_set_handle": args["candidate_set_handle"],
                          "candidate_id": PLACEHOLDER_ID, "parent_sdf_handle": args["parent_sdf_handle"]}
    row = docking_inputs.validate_arguments(template)
    return {**{key: row[key] for key in M18_KEYS},
            "candidate_set_handle": row["ligand"]["candidate_set_handle"],
            "parent_sdf_handle": row["ligand"]["parent_sdf_handle"], "filter": spec, "ga": ga}


def row_arguments(normalized: dict[str, Any], candidate_id: str) -> dict[str, Any]:
    """One individual's M18-normalized arguments (= a standalone free request's ``selected["arguments"]``)."""
    return docking_batch_inputs.row_arguments(m18_shared(normalized), "candidate", candidate_id)


# ---------------------------------------------------------------- pool and eligibility (spec 2 step 3, 3)
def eligibility(rows: list[Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The pool in stored order; eligible = every candidate when the spec is empty, else ``passes_all`` true."""
    pool = []
    for index, row in enumerate(rows):
        verdict = ligand_filters.evaluate_row(row, spec)["passes_all"]
        pool.append({"index": index, "candidate_id": row["id"], "eligible": verdict is None or verdict is True})
    return pool


def pool_counts(pool: list[dict[str, Any]]) -> dict[str, int]:
    eligible = sum(item["eligible"] for item in pool)
    return {"size": len(pool), "eligible_count": eligible, "filter_excluded_count": len(pool) - eligible}


def require_pool(pool: list[dict[str, Any]], population_size: int) -> None:
    eligible = pool_counts(pool)["eligible_count"]
    if eligible < population_size:
        raise _fail("ga_pool_too_small", "fewer eligible candidates than ga.population_size",
                    eligible_count=eligible, population_size=population_size)


def eligible_ids(selected: dict[str, Any]) -> list[str]:
    return [item["candidate_id"] for item in selected["pool"] if item["eligible"]]


# ---------------------------------------------------------------- selection record and hashes (spec 4, 7)
def pool_sha256(pool: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json([{"index": item["index"], "candidate_id": item["candidate_id"],
                                           "eligible": item["eligible"]} for item in pool])).hexdigest()


def selection_input(selected: dict[str, Any]) -> dict[str, Any]:
    """What defines one GA run (no acknowledgement, timeout, reuse, time or job identity)."""
    args = selected["arguments"]
    sidecar = selected["sidecar"]
    return {"receptor": {"handle": selected["receptor"]["handle"], "sha256": selected["receptor"]["sha256"],
                         "model_number": args["receptor_model_number"],
                         "connectivity": {"kind": args["connectivity"]["kind"],
                                          "sidecar_handle": None if sidecar is None else sidecar["handle"],
                                          "sidecar_sha256": None if sidecar is None else sidecar["sha256"]},
                         "instance": args["receptor_instance"]},
            "candidate_set_handle": args["candidate_set_handle"],
            "parent_sdf": {"handle": selected["parent_sdf"]["handle"], "sha256": selected["parent_sdf"]["sha256"]},
            "pool_sha256": selected["pool_sha256"], "filter": args["filter"], "box": args["box"],
            "parameters": args["parameters"], "ga": args["ga"]}


def selection_sha256(selected: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(selection_input(selected))).hexdigest()


def ga_selection(normalized: dict[str, Any], pool: list[dict[str, Any]],
                 representative: dict[str, Any]) -> dict[str, Any]:
    """The GA job's selection record (spec 7: pool ids in stored order, eligibility, hashes, filter, values; no
    per-candidate M18 selection). ``representative`` is the first eligible candidate's ``docking_selection@1``."""
    first = next((item["candidate_id"] for item in pool if item["eligible"]), None)
    ligand = representative["ligand"]
    if (first is None or representative["arguments"] != row_arguments(normalized, first) or
            ligand["source"] != "candidate" or ligand["candidate"]["id"] != first or
            ligand["candidate_set_handle"] != normalized["candidate_set_handle"] or
            ligand["parent_sdf"]["handle"] != normalized["parent_sdf_handle"]):
        raise ValueError("the representative is not the first eligible candidate under these arguments")
    pool = [{"index": item["index"], "candidate_id": item["candidate_id"], "eligible": item["eligible"]}
            for item in pool]
    selected = {"schema": GC.SELECTION_SCHEMA, "arguments": normalized,
                "receptor": copy.deepcopy(representative["receptor"]),
                "sidecar": copy.deepcopy(representative["sidecar"]),
                "candidate_set": {"handle": normalized["candidate_set_handle"],
                                  "parent_sha256": ligand["candidate_set_parent_sha256"]},
                "parent_sdf": dict(ligand["parent_sdf"]), "pool": pool, "pool_sha256": pool_sha256(pool)}
    selected["selection_sha256"] = selection_sha256(selected)
    return selected


def individual_selection(selected: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """One evaluated individual's ``docking_selection@1``, rebuilt from the GA record and its stored candidate row
    (receptor and parent checked once at admission); equal to ``docking_bundle.submission`` for that candidate."""
    args = row_arguments(selected["arguments"], row["id"])
    return {"schema": "docking_selection@1", "arguments": args, "input_sha256": docking_inputs.input_sha256(args),
            "receptor": copy.deepcopy(selected["receptor"]), "sidecar": copy.deepcopy(selected["sidecar"]),
            "ligand": {"source": "candidate", "candidate_set_handle": selected["candidate_set"]["handle"],
                       "candidate_set_parent_sha256": selected["candidate_set"]["parent_sha256"],
                       "parent_sdf": dict(selected["parent_sdf"]),
                       "candidate": {key: copy.deepcopy(row[key]) for key in CANDIDATE_FIELDS}}}


def submission(run: Any, args: Any, timeout_s: Any) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """(selected, normalized arguments, input handles); admission steps 1-3 in the spec order, before any job."""
    from .ligand_bundle import LigandEvidenceError, validated_candidate_set

    normalized = validate_arguments(args, timeout_s)
    try:
        candidate_set, _inspection = validated_candidate_set(run, normalized["candidate_set_handle"])
    except LigandEvidenceError as exc:
        raise _args_error("candidate_set_handle is not a completed same-run ligand candidate set") from exc
    pool = eligibility(candidate_set["candidates"], normalized["filter"])
    first = next((item["candidate_id"] for item in pool if item["eligible"]), None)
    if first is None:
        require_pool(pool, normalized["ga"]["population_size"])
    representative, _row_args, handles = docking_bundle.submission(
        run, docking_batch_inputs.row_request(m18_shared(normalized), "candidate", first))
    require_pool(pool, normalized["ga"]["population_size"])
    return ga_selection(normalized, pool, representative), normalized, handles


# ---------------------------------------------------------------- reuse index (spec 6, 7)
def call_keys(selected: dict[str, Any], pins: dict[str, Any]) -> dict[str, str]:
    """candidate id -> full M18 call key (pins included) of every eligible candidate, in pool order."""
    return {cid: docking_bundle.call_key(row_arguments(selected["arguments"], cid), pins)
            for cid in eligible_ids(selected)}


def reuse_index(selected: dict[str, Any], pins: dict[str, Any], existing: Mapping[str, str]) -> dict[str, str]:
    """candidate id -> stored result handle for eligible candidates whose M18 call key has one (``existing``: call
    key -> handle, from ``docking_batch_inputs.published_m18_results``). The caller still validates each handle."""
    return {cid: existing[key] for cid, key in call_keys(selected, pins).items() if key in existing}


def require_reuse_size(total_bytes: int) -> None:
    if total_bytes > GC.MAX_REUSE_STAGING_BYTES:
        raise _fail("ga_reuse_too_large", "reused results to stage exceed 128 MiB",
                    limit_bytes=GC.MAX_REUSE_STAGING_BYTES)


# ---------------------------------------------------------------- budget arithmetic (spec 6)
def reserved_units(ga: Mapping[str, Any]) -> int:
    population, elite = ga["population_size"], ga["elite_count"]
    return min(ga["max_new_dockings"], population + (ga["generations"] - 1) * (population - elite))


def needed_budget(ga: Mapping[str, Any]) -> dict[str, int]:
    units = reserved_units(ga)
    return {"expensive_calls": units,
            "wall_clock_s": min(ga["total_s"] + GC.FINISH_MARGIN_S, units * GC.PER_CANDIDATE_S + GC.NEED_MARGIN_S)}


def full_run_may_be_partial(ga: Mapping[str, Any]) -> bool:
    return reserved_units(ga) * GC.PER_CANDIDATE_S > ga["total_s"]


remaining = docking_batch_inputs.remaining
shortfall = docking_batch_inputs.shortfall


def limit_increase(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The M19 ``limit_increase`` formula with the GA constants: calls = min(shortfall, need, 100); wall = 0 when not
    short, else min(shortfall, need, 15000) + 60. Zero when nothing is short (idempotent)."""
    short = shortfall(needed, snapshot)
    calls = min(short["expensive_calls"], needed["expensive_calls"], GC.MAX_RAISE_EXPENSIVE_CALLS)
    wall = min(short["wall_clock_s"], needed["wall_clock_s"], GC.MAX_RAISE_WALL_CLOCK_S)
    return {"expensive_calls": calls, "wall_clock_s": wall + GC.RAISE_MARGIN_S if wall > 0 else 0}


def require_budget(needed: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Admission step 5: a short budget refuses the GA (429 ``ga_limit_raise_required``, nothing charged)."""
    short = shortfall(needed, snapshot)
    if any(value > 0 for value in short.values()):
        raise ToolFailure(FailureClass.resource_exceeded, "the run budget is short for this GA; raise the limits "
                          "first", detail={"reason_code": "ga_limit_raise_required", "needed": dict(needed),
                                           "shortfall": short})


def preflight(selected: dict[str, Any], pins: dict[str, Any], existing: Mapping[str, str],
              snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Spec 6, 8: pool counts, reusable eligible candidates, reserved units (= the expected maximum of new
    dockings), need, remaining, shortfall and ``full_run_may_be_partial``."""
    ga = selected["arguments"]["ga"]
    needed = needed_budget(ga)
    units = reserved_units(ga)
    return {"selection_sha256": selected["selection_sha256"], "pool": pool_counts(selected["pool"]),
            "reusable_count": len(reuse_index(selected, pins, existing)), "reserved_units": units,
            "max_new_dockings_expected": units, "needed": needed, "remaining": remaining(snapshot),
            "shortfall": shortfall(needed, snapshot), "full_run_may_be_partial": full_run_may_be_partial(ga)}
