"""M18 server-side admission: job-argument shape, call-key input and receptor instances (spec 3, 5.1, 5.3).

Pure functions on the job arguments and on receptor import bytes (gemmi). No RDKit, no Meeko, no events, no
store access: the caller (docking bundle) loads same-run import bytes and checks handle kinds. Every refusal is
``input_invalid`` with ``detail.reason_code`` from ``docking_constants`` (closed sets).

Argument rules (spec 5.1):
- Fixed shape; unknown keys anywhere are ``invalid_job_arguments``. Every top-level key is required
  (``receptor_instance`` may be null); a missing or not-all-true ``acknowledgement`` is ``acknowledgement_missing``.
- Adjustable values with a spec default may be omitted and are filled in: ``exhaustiveness`` 8, ``num_modes`` 9,
  ``energy_range`` 3, ``conformers`` 50 (``core_fixed`` only), ``margin_A`` 8. ``seed`` is required.
  ``conformers`` must be absent for ``free`` (even null) and is normalized to null there.
- Integers are ``int`` (never bool or float); ``energy_range``, ``margin_A``, ``center_A`` and ``size_A`` are finite
  ``int``/``float`` normalized to float (-0.0 becomes 0.0). Parameter range errors are ``invalid_job_arguments``;
  box value errors are ``box_invalid`` except a manual side above 40 A, which is ``box_too_large``.
- Check order: top-level keys, receptor fields, connectivity, receptor instance, ligand, mode/source, box,
  parameters, acknowledgement; the first failure is reported.

Call key (``call_key_input``/``input_sha256``): the normalized arguments without ``acknowledgement`` (confirmation
does not change the input's meaning), hashed as canonical JSON (keys sorted at every level, separators ``,``/``:``,
UTF-8, no NaN). List order is meaningful and kept (``center_A``/``size_A`` are x, y, z).

Receptor rules (spec 3.2), same traversal and connectivity rules as M11 ``chemical_inputs.receptor_atoms``/
``_bonds`` (re-implemented here because the M11 private functions take the M11 request and a store):
- A nonstandard residue instance is a non-water residue that is HETATM or whose name is not a supported amino
  acid (M11 ``AMINO``). Water is only counted. An instance is identified by the seven residue fields exactly,
  nulls included; it must match exactly one gemmi residue of the selected model, never the first of several.
- After removing the instance: water, any other nonstandard residue or a non-H/C/N/O/S element is
  ``receptor_unsupported_residue``; any altloc is ``receptor_altloc_present`` (lists of at most 20).
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any

from . import docking_constants as C
from .chemical_inputs import AMINO, RECEPTOR_ELEMENTS, _gemmi
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json
from .tools.structural import _res_ref

MAX_BONDS = 20_000  # M11 chemical_inputs.MAX_BONDS
RESIDUE_KEYS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
ATOM_REF_KEYS = {"structure_handle", "residue", "atom_name", "altloc", "element", "site_index"}
TOP_KEYS = {"receptor_handle", "receptor_model_number", "connectivity", "receptor_instance", "ligand", "mode",
            "box", "parameters", "acknowledgement"}
LIGAND_KEYS = {"sdf": {"source", "sdf_handle"},
               "candidate": {"source", "candidate_set_handle", "candidate_id", "parent_sdf_handle"}}


def _fail(reason: str, message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail={"reason_code": reason, **detail})


def _args_error(message: str) -> ToolFailure:
    return _fail("invalid_job_arguments", message)


def _is_int(value: Any, low: int, high: int | None = None) -> bool:
    return type(value) is int and value >= low and (high is None or value <= high)


def _number(value: Any) -> float | None:
    """Finite int/float (never bool) as a float with -0.0 folded to 0.0, else None."""
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value) + 0.0


def _handle(value: Any) -> str:
    if type(value) is not str or not value:
        raise _args_error("handles must be non-empty strings")
    return value


# ---------------------------------------------------------------- job arguments


def _residue(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(RESIDUE_KEYS):
        raise _args_error("receptor_instance needs exactly the seven residue fields")
    ok = (_is_int(value["model_number"], 1) and type(value["chain_auth"]) is str and
          (value["chain_label"] is None or type(value["chain_label"]) is str) and type(value["seq_auth"]) is int and
          (value["seq_label"] is None or type(value["seq_label"]) is int) and type(value["icode"]) is str and
          type(value["resname"]) is str and value["resname"] != "")
    if not ok:
        raise _args_error("receptor_instance residue field has the wrong type")
    return {key: value[key] for key in RESIDUE_KEYS}


def _connectivity(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {"kind", "sidecar_handle"} or value["kind"] not in C.CONNECTIVITY_KINDS:
        raise _args_error("connectivity is {kind: pdb_conect|sidecar, sidecar_handle}")
    if value["kind"] == "pdb_conect":
        if value["sidecar_handle"] is not None:
            raise _args_error("pdb_conect connectivity takes no sidecar handle")
        return {"kind": "pdb_conect", "sidecar_handle": None}
    return {"kind": "sidecar", "sidecar_handle": _handle(value["sidecar_handle"])}


def _ligand(value: Any) -> dict[str, Any]:
    if type(value) is not dict or value.get("source") not in C.LIGAND_SOURCES or set(value) != LIGAND_KEYS[
            value["source"]]:
        raise _args_error("ligand is {source: sdf, sdf_handle} or {source: candidate, candidate_set_handle, "
                          "candidate_id, parent_sdf_handle}")
    if value["source"] == "sdf":
        return {"source": "sdf", "sdf_handle": _handle(value["sdf_handle"])}
    if type(value["candidate_id"]) is not str or not value["candidate_id"]:
        raise _args_error("candidate_id must be a non-empty string")
    return {"source": "candidate", "candidate_set_handle": _handle(value["candidate_set_handle"]),
            "candidate_id": value["candidate_id"], "parent_sdf_handle": _handle(value["parent_sdf_handle"])}


def _margin(value: dict[str, Any]) -> float:
    margin = _number(value.get("margin_A", C.MARGIN_DEFAULT_A))
    if margin is None or not C.MARGIN_MIN_A <= margin <= C.MARGIN_MAX_A:
        raise _fail("box_invalid", f"margin_A must be a finite number {C.MARGIN_MIN_A}-{C.MARGIN_MAX_A} A")
    return margin


def _triple(value: Any) -> list[float] | None:
    if type(value) is not list or len(value) != 3:
        return None
    numbers = [_number(x) for x in value]
    return None if any(x is None for x in numbers) else numbers


def _box(value: Any, has_instance: bool) -> dict[str, Any]:
    source = value.get("source") if type(value) is dict else None
    if source not in C.BOX_SOURCES:
        raise _args_error("box source must be ligand_range, instance_range or manual")
    if source == "manual":
        if set(value) != {"source", "center_A", "size_A"}:
            raise _args_error("manual box is {source, center_A, size_A}")
        center, size = _triple(value["center_A"]), _triple(value["size_A"])
        if center is None or any(abs(x) > C.MAX_BOX_CENTER_ABS_A for x in center):
            raise _fail("box_invalid", "center_A must be three finite numbers")
        if size is None or any(x < C.BOX_SIDE_MIN_A for x in size):
            raise _fail("box_invalid", f"size_A must be three finite numbers >= {C.BOX_SIDE_MIN_A} A")
        if any(x > C.BOX_SIDE_MAX_A for x in size):
            raise _fail("box_too_large", f"a box side exceeds {C.BOX_SIDE_MAX_A} A")
        return {"source": "manual", "center_A": center, "size_A": size}
    if not set(value) <= {"source", "margin_A"}:
        raise _args_error("range box is {source, margin_A}")
    margin = _margin(value)
    if source == "instance_range" and not has_instance:
        raise _fail("box_invalid", "instance_range needs a receptor_instance")
    return {"source": source, "margin_A": margin}


def _parameters(value: Any, mode: str) -> dict[str, Any]:
    allowed = {"seed", "exhaustiveness", "num_modes", "energy_range"} | ({"conformers"} if mode == "core_fixed"
                                                                          else set())
    if type(value) is not dict or "seed" not in value or not set(value) <= allowed:
        raise _args_error("parameters are {seed, exhaustiveness, num_modes, energy_range"
                          + (", conformers}" if mode == "core_fixed" else "} (conformers only for core_fixed)"))
    out = {"seed": value["seed"], "exhaustiveness": value.get("exhaustiveness", C.EXHAUSTIVENESS_DEFAULT),
           "num_modes": value.get("num_modes", C.NUM_MODES_DEFAULT),
           "energy_range": _number(value.get("energy_range", C.ENERGY_RANGE_DEFAULT)),
           "conformers": value.get("conformers", C.CONFORMERS_DEFAULT) if mode == "core_fixed" else None}
    checks = (_is_int(out["seed"], C.SEED_MIN, C.SEED_MAX),
              _is_int(out["exhaustiveness"], C.EXHAUSTIVENESS_MIN, C.EXHAUSTIVENESS_MAX),
              _is_int(out["num_modes"], C.NUM_MODES_MIN, C.NUM_MODES_MAX),
              out["energy_range"] is not None and C.ENERGY_RANGE_MIN <= out["energy_range"] <= C.ENERGY_RANGE_MAX,
              mode != "core_fixed" or _is_int(out["conformers"], C.CONFORMERS_MIN, C.CONFORMERS_MAX))
    if not all(checks):
        raise _args_error("a docking parameter is out of range or has the wrong type")
    return out


def validate_arguments(args: Any) -> dict[str, Any]:
    """Validate ``qvina_dock_v1`` job arguments (shape and values only) and return the normalized copy."""
    if type(args) is not dict:
        raise _args_error("job arguments must be an object")
    if not set(args) <= TOP_KEYS or not TOP_KEYS - {"acknowledgement"} <= set(args):
        raise _args_error("job arguments have unknown or missing keys")
    if not _is_int(args["receptor_model_number"], 1):
        raise _args_error("receptor_model_number must be a positive integer")
    receptor_handle = _handle(args["receptor_handle"])
    connectivity = _connectivity(args["connectivity"])
    instance = None if args["receptor_instance"] is None else _residue(args["receptor_instance"])
    ligand = _ligand(args["ligand"])
    mode = args["mode"]
    if mode not in C.MODES:
        raise _args_error("mode must be free or core_fixed")
    if mode == "core_fixed" and ligand["source"] != "candidate":
        raise _fail("mode_source_mismatch", "core_fixed needs the candidate ligand source")
    box = _box(args["box"], instance is not None)
    parameters = _parameters(args["parameters"], mode)
    ack = args.get("acknowledgement")
    if type(ack) is dict and not set(ack) <= set(C.ACKNOWLEDGEMENT_KEYS):
        raise _args_error("acknowledgement has unknown keys")
    if type(ack) is not dict or any(ack.get(key) is not True for key in C.ACKNOWLEDGEMENT_KEYS):
        raise _fail("acknowledgement_missing", "all three acknowledgements must be true")
    return {"receptor_handle": receptor_handle, "receptor_model_number": args["receptor_model_number"],
            "connectivity": connectivity, "receptor_instance": instance, "ligand": ligand, "mode": mode,
            "box": box, "parameters": parameters,
            "acknowledgement": {key: True for key in C.ACKNOWLEDGEMENT_KEYS}}


def call_key_input(normalized: dict[str, Any]) -> dict[str, Any]:
    """The normalized arguments that define the call key and ``input_sha256`` (no acknowledgement)."""
    return {key: value for key, value in normalized.items() if key != "acknowledgement"}


def input_sha256(normalized: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(call_key_input(normalized))).hexdigest()


# ---------------------------------------------------------------- receptor bytes


def _structure(raw: bytes, fmt: str):
    try:
        st = _gemmi(raw.decode("utf-8"), fmt)
    except (UnicodeError, ValueError, RuntimeError, KeyError, IndexError) as exc:
        raise _fail("receptor_invalid", "receptor bytes are not a readable PDB/mmCIF structure") from exc
    if not st or not any(model.count_atom_sites() for model in st):
        raise _fail("receptor_invalid", "receptor has no atoms")
    return st


def _nonstandard(residue) -> bool:
    return not residue.is_water() and (residue.het_flag == "H" or residue.name not in AMINO)


def _element_counts(elements: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(elements).items()))


def receptor_instances(raw: bytes, fmt: str) -> dict[str, Any]:
    """Nonstandard residue instances of every model (seven fields as read, nulls kept); water only counted."""
    st = _structure(raw, fmt)
    models = []
    for model in st:
        instances, water = [], 0
        for chain in model:
            for residue in chain:
                if residue.is_water():
                    water += 1
                elif _nonstandard(residue):
                    instances.append({"residue": _res_ref(chain, residue, model.num), "atom_count": len(residue),
                                      "element_counts": _element_counts([a.element.name for a in residue])})
        models.append({"model_number": model.num, "water_residue_count": water, "instances": instances})
    return {"schema": "docking_receptor_instances@1", "models": models}


def receptor_rows(raw: bytes, fmt: str, handle: str, model_number: int) -> list[dict[str, Any]]:
    """Atom rows of one model in M11 ``receptor_atoms`` order (same ``ref``/``site_index``), plus
    ``residue_ordinal`` (gemmi residue position) and ``nonstandard`` for instance resolution."""
    if not _is_int(model_number, 1):
        raise _fail("receptor_invalid", "receptor model number must be a positive integer")
    st = _structure(raw, fmt)
    selected = [m for m in st if m.num == model_number]
    if len(selected) != 1:
        raise _fail("receptor_invalid", "exact receptor model unavailable or ambiguous")
    rows: list[dict[str, Any]] = []
    ordinal = 0
    for chain in selected[0]:
        for residue in chain:
            rr = _res_ref(chain, residue, selected[0].num)
            for atom in residue:
                coord = [atom.pos.x, atom.pos.y, atom.pos.z]
                if not all(math.isfinite(x) and abs(x) <= 100_000 for x in coord):
                    raise _fail("receptor_invalid", "receptor coordinate nonfinite or out of range", residue=rr)
                rows.append({"ref": {"structure_handle": handle, "residue": rr, "atom_name": atom.name,
                                     "altloc": atom.altloc.strip("\0 "), "element": atom.element.name,
                                     "site_index": len(rows)}, "coordinate_A": coord,
                             "element": atom.element.name, "water": residue.is_water(),
                             "serial": atom.serial, "het_flag": residue.het_flag,
                             "residue_ordinal": ordinal, "nonstandard": _nonstandard(residue)})
            ordinal += 1
    if not 1 <= len(rows) <= C.MAX_RECEPTOR_ATOMS:
        raise _fail("receptor_invalid", f"receptor atom count must be 1-{C.MAX_RECEPTOR_ATOMS}")
    return rows


def resolve_instance(rows: list[dict[str, Any]], instance: dict[str, Any]) -> list[int]:
    """Site indices of the one nonstandard residue whose seven fields equal ``instance`` exactly."""
    ordinals = sorted({row["residue_ordinal"] for row in rows
                       if row["nonstandard"] and row["ref"]["residue"] == instance})
    if not ordinals:
        raise _fail("receptor_instance_unknown", "no nonstandard residue instance has these seven fields")
    if len(ordinals) > 1:
        raise _fail("receptor_instance_ambiguous", "several residue instances share these seven fields",
                    matches=len(ordinals))
    return [row["ref"]["site_index"] for row in rows if row["residue_ordinal"] == ordinals[0]]


def instance_summary(rows: list[dict[str, Any]], sites: list[int]) -> dict[str, Any]:
    removed = [rows[site] for site in sites]
    return {"residue": removed[0]["ref"]["residue"], "atom_count": len(removed),
            "element_counts": _element_counts([row["element"] for row in removed])}


# ---------------------------------------------------------------- connectivity (M11 _bonds rules)


def _pdb_conect(rows: list[dict[str, Any]], raw: bytes) -> set[tuple[int, int]]:
    ids = [row["serial"] for row in rows]
    if any(type(x) is not int or x <= 0 for x in ids) or len(set(ids)) != len(ids):
        raise _fail("receptor_invalid", "PDB serials are ambiguous for CONECT")
    lookup = {x: i for i, x in enumerate(ids)}
    pairs: set[tuple[int, int]] = set()
    for line in raw.decode("utf-8").splitlines():
        if not line.startswith("CONECT"):
            continue
        try:
            values = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip()]
        except ValueError as exc:
            raise _fail("receptor_invalid", "malformed PDB CONECT serial") from exc
        for second in values[1:]:
            if values[0] not in lookup or second not in lookup or values[0] == second:
                raise _fail("receptor_invalid", "dangling or self PDB CONECT")
            pairs.add(tuple(sorted((lookup[values[0]], lookup[second]))))  # reverse duplicates merge
    return pairs


def _strict_ref(value: Any, source: str) -> str:
    residue = value.get("residue") if type(value) is dict else None
    ok = (type(value) is dict and set(value) == ATOM_REF_KEYS and value["structure_handle"] == source and
          type(residue) is dict and set(residue) == set(RESIDUE_KEYS) and
          all(type(value[k]) is str for k in ("atom_name", "altloc", "element")) and _is_int(value["site_index"], 0))
    if ok:
        try:
            _residue(residue)
        except ToolFailure:
            ok = False
    if not ok:
        raise _fail("receptor_invalid", "invalid complete atom reference or another source")
    return json.dumps(value, sort_keys=True)


def _sidecar(rows: list[dict[str, Any]], body: Any, source: str) -> set[tuple[int, int]]:
    try:
        obj = json.loads(body)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _fail("receptor_invalid", "bond sidecar is not JSON") from exc
    if (type(obj) is not dict or obj.get("schema") != "receptor_bonds@1" or obj.get("complete") is not True or
            type(obj.get("bonds")) is not list or obj.get("source_handle", obj.get("receptor_input_handle")) != source):
        raise _fail("receptor_invalid", "incomplete or source-mismatched bond sidecar")
    lookup = {json.dumps(row["ref"], sort_keys=True): i for i, row in enumerate(rows)}
    if len(lookup) != len(rows):
        raise _fail("receptor_invalid", "ambiguous source atom identities")
    pairs: set[tuple[int, int]] = set()
    for bond in obj["bonds"]:
        if type(bond) is not dict or set(bond) != {"first", "second"}:
            raise _fail("receptor_invalid", "invalid sidecar bond")
        x, y = lookup.get(_strict_ref(bond["first"], source)), lookup.get(_strict_ref(bond["second"], source))
        if x is None or y is None or x == y:
            raise _fail("receptor_invalid", "dangling/self sidecar bond")
        pair = tuple(sorted((x, y)))
        if pair in pairs:
            raise _fail("receptor_invalid", "duplicate sidecar bond")
        pairs.add(pair)
    return pairs


def receptor_bonds(rows: list[dict[str, Any]], connectivity: dict[str, Any], raw: bytes, fmt: str, source: str,
                   sidecar_raw: bytes | None = None) -> list[list[int]]:
    """Receptor bonds as sorted site-index pairs; every rule violation is ``receptor_invalid``."""
    if connectivity["kind"] == "pdb_conect":
        if fmt != "pdb":
            raise _fail("receptor_invalid", "PDB CONECT requires an original receptor PDB")
        pairs = _pdb_conect(rows, raw)
    else:
        pairs = _sidecar(rows, sidecar_raw, source)
    if not 1 <= len(pairs) <= MAX_BONDS:
        raise _fail("receptor_invalid", "empty or oversized receptor connectivity")
    return [list(pair) for pair in sorted(pairs)]


# ---------------------------------------------------------------- receptor admission


def check_receptor(raw: bytes, fmt: str, handle: str, model_number: int, connectivity: dict[str, Any],
                   instance: dict[str, Any] | None, sidecar_raw: bytes | None = None) -> dict[str, Any]:
    """Server receptor admission on normalized arguments: rows, instance, bonds, covalent link, leftovers.

    Order: receptor_invalid (model, atoms, cap), instance unknown/ambiguous, receptor_invalid (connectivity),
    receptor_instance_covalent, receptor_unsupported_residue, receptor_altloc_present.
    """
    rows = receptor_rows(raw, fmt, handle, model_number)
    sites = [] if instance is None else resolve_instance(rows, instance)
    bonds = receptor_bonds(rows, connectivity, raw, fmt, handle, sidecar_raw)
    removed = set(sites)
    crossing = [pair for pair in bonds if (pair[0] in removed) != (pair[1] in removed)]
    if crossing:
        raise _fail("receptor_instance_covalent", "the selected instance is covalently bonded to the receptor",
                    bonds=[[rows[a]["ref"], rows[b]["ref"]] for a, b in crossing[:C.MAX_LISTED_RECEPTOR_ITEMS]],
                    total=len(crossing))
    kept = [row for row in rows if row["ref"]["site_index"] not in removed]
    unsupported: dict[int, dict[str, Any]] = {}
    for row in kept:
        if row["water"] or row["nonstandard"] or row["element"].upper() not in RECEPTOR_ELEMENTS:
            item = unsupported.setdefault(row["residue_ordinal"], {"residue": row["ref"]["residue"],
                                                                   "atom_names": []})
            item["atom_names"].append(row["ref"]["atom_name"])
    if unsupported:
        items = list(unsupported.values())
        raise _fail("receptor_unsupported_residue", "receptor keeps water, ions, cofactors, other ligands or "
                    "unsupported residues", items=items[:C.MAX_LISTED_RECEPTOR_ITEMS], total=len(items))
    altloc = [{"residue": row["ref"]["residue"], "atom_name": row["ref"]["atom_name"], "altloc": row["ref"]["altloc"]}
              for row in kept if row["ref"]["altloc"]]
    if altloc:
        raise _fail("receptor_altloc_present", "receptor has alternate locations",
                    items=altloc[:C.MAX_LISTED_RECEPTOR_ITEMS], total=len(altloc))
    return {"rows": rows, "bonds": bonds, "instance_sites": sites,
            "removed_instance": instance_summary(rows, sites) if sites else None}
