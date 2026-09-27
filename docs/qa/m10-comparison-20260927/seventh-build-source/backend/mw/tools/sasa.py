"""Fixed, explicit-coordinate FreeSASA protein–ligand exposure protocol."""
from __future__ import annotations

import math
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import canonical_json
from ..core.residue import ResidueRef
from .registry import ToolContext, ToolRegistry
from .structural import _parse, _res_ref

ELEMENTS = ("C", "N", "O", "S", "P", "F", "Cl", "Br", "I")
AMINO = frozenset(["ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"])
ATOM_CAP = 6000
CENTER_TOL_A = 1e-6
AREA_TOL_A2 = 1e-6


def dependencies() -> dict[str, Any]:
    try:
        import gemmi
        engine_version = version("freesasa")
    except (ImportError, PackageNotFoundError) as exc:
        raise ToolFailure(FailureClass.precondition, "FreeSASA or Gemmi is unavailable") from exc
    try:
        radii = {element: gemmi.Element(element).vdw_r for element in ELEMENTS}
    except (AttributeError, RuntimeError, ValueError) as exc:
        raise ToolFailure(FailureClass.precondition, "Gemmi radius table is unavailable") from exc
    if any(not math.isfinite(radius) or radius <= 0 for radius in radii.values()):
        raise ToolFailure(FailureClass.precondition, "Gemmi radius table is invalid")
    return {"method_id": "freesasa_lee_richards_v1", "method": "interface_sasa@1",
            "engine": "FreeSASA", "engine_version": engine_version,
            "gemmi_version": gemmi.__version__, "radius_policy": "gemmi_vdw_elements_v1",
            "radius_description": "Gemmi element van der Waals radii", "radii_A": radii,
            "algorithm": "LeeRichards", "n_slices": 100, "probe_radius_A": 1.4, "threads": 1}


def engine_capability() -> dict[str, Any]:
    """Check the installed native engine against independent analytic sphere geometry."""
    import freesasa

    dep = dependencies()
    params = freesasa.Parameters({"algorithm": freesasa.LeeRichards, "probe-radius": 1.4,
                                   "n-slices": 100, "n-threads": 1})
    radius = 1.7
    expanded = radius + 1.4
    single = freesasa.calcCoord([0.0, 0.0, 0.0], [radius], params).totalArea()
    separated = freesasa.calcCoord([0.0, 0.0, 0.0, 100.0, 0.0, 0.0], [radius, radius], params).totalArea()
    overlap = freesasa.calcCoord([0.0, 0.0, 0.0, expanded, 0.0, 0.0], [radius, radius], params).totalArea()
    expected = 4 * math.pi * expanded * expanded
    overlap_expected = 6 * math.pi * expanded * expanded
    if (not all(math.isfinite(area) and area > 0 for area in (single, separated, overlap)) or
            abs(single - expected) > 1e-6 or abs(separated - 2 * expected) > 1e-6 or
            abs(overlap - overlap_expected) > 0.005 * overlap_expected + 1e-6):
        raise ToolFailure(FailureClass.precondition, "FreeSASA analytic Lee–Richards probe failed")
    return {"available": True, "execution_lane": "run_call_sync", "unit": "A2",
            "method_id": dep["method_id"], "algorithm": dep["algorithm"],
            "n_slices": dep["n_slices"], "engine_version": dep["engine_version"],
            "limitations": "selected two-partner solvent-accessible geometry; no affinity or energy claim"}


def _atom(residue: dict[str, Any], atom: Any, partner: str, radius: float) -> dict[str, Any]:
    return {"partner": partner, "residue": residue, "atom_name": atom.name, "atom_serial": atom.serial,
            "altloc": atom.altloc.strip("\x00 "), "element": atom.element.name,
            "coordinates_A": [atom.pos.x, atom.pos.y, atom.pos.z], "radius_A": radius}


def _preflight(protein: list[dict[str, Any]], ligand: list[dict[str, Any]]) -> list[float]:
    atoms = protein + ligand
    if not protein or not ligand:
        raise ToolFailure(FailureClass.input_invalid, "protein and selected ligand require heavy atoms")
    if len(atoms) > ATOM_CAP:
        raise ToolFailure(FailureClass.resource_exceeded, "SASA selected heavy-atom cap is 6000",
                          detail={"selected_atoms": len(atoms), "limit": ATOM_CAP})
    identities: set[bytes] = set()
    for item in atoms:
        coordinates = item.get("coordinates_A")
        radius = item.get("radius_A")
        if (not isinstance(coordinates, (list, tuple)) or len(coordinates) != 3 or
                any(type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 1e6 for x in coordinates) or
                type(radius) not in (float, int) or not math.isfinite(radius) or radius <= 0):
            raise ToolFailure(FailureClass.input_invalid, "invalid radius or coordinate shape/value")
        ident = canonical_json([item["residue"], item["atom_name"], item["altloc"]])
        if ident in identities or item["altloc"]:
            raise ToolFailure(FailureClass.input_invalid, "duplicate atom identity or unresolved altloc")
        identities.add(ident)
    origin = [min(a["coordinates_A"][axis] for a in atoms) for axis in range(3)]
    if any(max(a["coordinates_A"][axis] for a in atoms) - origin[axis] > 1e4 for axis in range(3)):
        raise ToolFailure(FailureClass.resource_exceeded, "SASA coordinate extent exceeds 10000 Å")
    # Sorted sweep checks all pairs closer than 1e-6 Å before entering native code.
    ordered = sorted(atoms, key=lambda a: a["coordinates_A"][0])
    for i, left in enumerate(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j]["coordinates_A"][0] - left["coordinates_A"][0] <= CENTER_TOL_A:
            right = ordered[j]
            if math.dist(left["coordinates_A"], right["coordinates_A"]) <= CENTER_TOL_A:
                raise ToolFailure(FailureClass.input_invalid, "coincident or indistinguishable selected atom centers")
            j += 1
    return origin


def _calculate(atoms: list[dict[str, Any]], origin: list[float], params: Any) -> list[float]:
    import freesasa
    if (not atoms or len(origin) != 3 or any(type(x) not in (float, int) or not math.isfinite(x) for x in origin) or
            any(not isinstance(atom.get("coordinates_A"), (list, tuple)) or len(atom["coordinates_A"]) != 3 or
                any(type(x) not in (float, int) or not math.isfinite(x) for x in atom["coordinates_A"])
                for atom in atoms) or
            any(type(atom.get("radius_A")) not in (float, int) or not math.isfinite(atom["radius_A"]) or
                atom["radius_A"] <= 0 for atom in atoms)):
        raise ToolFailure(FailureClass.input_invalid, "invalid native SASA coordinate/radius array")
    coordinates = [x - origin[axis] for atom in atoms for axis, x in enumerate(atom["coordinates_A"])]
    radii = [atom["radius_A"] for atom in atoms]
    if len(coordinates) != 3 * len(radii):
        raise ToolFailure(FailureClass.input_invalid, "invalid native SASA coordinate/radius array")
    try:
        result = freesasa.calcCoord(coordinates, radii, params)
        if result.nAtoms() != len(atoms):
            raise ValueError("native atom count mismatch")
        areas = [result.atomArea(i) for i in range(len(atoms))]
        if any(not math.isfinite(a) or a < 0 for a in areas):
            raise ValueError("invalid native atom area")
        if not math.isclose(sum(areas), result.totalArea(), rel_tol=1e-10, abs_tol=AREA_TOL_A2):
            raise ValueError("native area sum mismatch")
        return areas
    except (Exception, AssertionError) as exc:
        raise ToolFailure(FailureClass.fatal, "FreeSASA calculation failed", detail={"reason": str(exc)}) from exc


def calculate(ctx: ToolContext, structure: str, ligand: dict[str, Any]) -> Any:
    if ctx.dry_run:
        raise ToolFailure(FailureClass.precondition, "dry-run does not produce measured SASA")
    try:
        import freesasa
    except ImportError as exc:
        raise ToolFailure(FailureClass.precondition, "FreeSASA is unavailable") from exc
    dep = dependencies()
    st = _parse(ctx, structure)
    model = st[0]
    try:
        selector = ResidueRef.model_validate(ligand, strict=True)
        if set(ligand) != set(ResidueRef.model_fields):
            raise ValueError("full ResidueRef required")
    except (ValueError, TypeError) as exc:
        raise ToolFailure(FailureClass.input_invalid, "exact full ligand ResidueRef required") from exc
    selected = []
    for chain in model:
        for res in chain:
            if _res_ref(chain, res, model.num) == selector.model_dump():
                selected.append((chain, res))
    if len(selected) != 1 or selected[0][1].het_flag != "H" or selected[0][1].is_water():
        raise ToolFailure(FailureClass.input_invalid, "selected ligand is missing, ambiguous or not nonpolymer")
    radius_table = dep["radii_A"]
    protein: list[dict[str, Any]] = []
    ligand_atoms: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    protein_refs: list[dict[str, Any]] = []
    for chain in model:
        for res in chain:
            ref = _res_ref(chain, res, model.num)
            is_selected = (chain, res) == selected[0]
            is_polymer = res.het_flag == "A" or res.label_seq is not None
            if is_polymer and res.name not in AMINO:
                raise ToolFailure(FailureClass.precondition, "nonstandard polymer is unsupported",
                                  detail={"residue": ref})
            target = ligand_atoms if is_selected else protein if is_polymer else None
            if target is None:
                excluded.append({"residue": ref, "atom_count": len(res),
                                 "reason": "water" if res.is_water() else "other_nonprotein"})
                continue
            if is_polymer:
                protein_refs.append(ref)
            for atom in res:
                element = atom.element.name
                if element in {"H", "D"}:
                    continue
                radius = radius_table.get(element)
                if radius is None:
                    raise ToolFailure(FailureClass.input_invalid, "unsupported SASA element",
                                      detail={"element": element, "residue": ref, "atom": atom.name})
                target.append(_atom(ref, atom, "ligand" if is_selected else "protein", radius))
    if (len({canonical_json(ref) for ref in protein_refs}) != len(protein_refs) or
            len({canonical_json(item["residue"]) for item in excluded}) != len(excluded)):
        raise ToolFailure(FailureClass.input_invalid, "ambiguous full residue identity")
    origin = _preflight(protein, ligand_atoms)
    try:
        params = freesasa.Parameters({"algorithm": freesasa.LeeRichards, "probe-radius": 1.4,
                                       "n-slices": 100, "n-threads": 1})
    except (AttributeError, RuntimeError, ValueError) as exc:
        raise ToolFailure(FailureClass.fatal, "FreeSASA Lee–Richards settings unavailable") from exc
    isolated_p = _calculate(protein, origin, params)
    isolated_l = _calculate(ligand_atoms, origin, params)
    bound = _calculate(protein + ligand_atoms, origin, params)
    p_count = len(protein)
    rows = []
    for index, atom in enumerate(protein + ligand_atoms):
        isolated = isolated_p[index] if index < p_count else isolated_l[index - p_count]
        rows.append({**atom, "index": index, "isolated_A2": isolated,
                     "bound_A2": bound[index], "buried_A2": isolated - bound[index]})
    residues: dict[bytes, dict[str, Any]] = {
        canonical_json(ref): {"residue": ref, "atom_indices": [],
                              "isolated_A2": 0.0, "bound_A2": 0.0, "buried_A2": 0.0}
        for ref in protein_refs
    }
    for atom in rows[:p_count]:
        key = canonical_json(atom["residue"])
        row = residues.setdefault(key, {"residue": atom["residue"], "atom_indices": [],
                                        "isolated_A2": 0.0, "bound_A2": 0.0, "buried_A2": 0.0})
        row["atom_indices"].append(atom["index"])
        for field in ("isolated_A2", "bound_A2", "buried_A2"):
            row[field] += atom[field]
    per_residue = sorted(residues.values(), key=lambda r: canonical_json(r["residue"]))
    summary = {"protein_sasa_isolated_A2": sum(isolated_p), "ligand_sasa_isolated_A2": sum(isolated_l),
               "complex_sasa_A2": sum(bound), "protein_sasa_bound_A2": sum(bound[:p_count]),
               "ligand_sasa_bound_A2": sum(bound[p_count:])}
    summary["protein_burial_A2"] = summary["protein_sasa_isolated_A2"] - summary["protein_sasa_bound_A2"]
    summary["ligand_burial_A2"] = summary["ligand_sasa_isolated_A2"] - summary["ligand_sasa_bound_A2"]
    summary["total_sasa_loss_A2"] = (summary["protein_sasa_isolated_A2"] +
                                    summary["ligand_sasa_isolated_A2"] - summary["complex_sasa_A2"])
    tolerance = AREA_TOL_A2 + 1e-10 * max(summary.values())
    if (summary["protein_burial_A2"] < -tolerance or summary["ligand_burial_A2"] < -tolerance or
            any(row["buried_A2"] < -tolerance for row in per_residue) or
            any(atom["buried_A2"] < -tolerance for atom in rows) or
            abs(summary["protein_sasa_bound_A2"] + summary["ligand_sasa_bound_A2"] - summary["complex_sasa_A2"]) > tolerance or
            abs(sum(atom["isolated_A2"] for atom in rows[:p_count]) - summary["protein_sasa_isolated_A2"]) > tolerance or
            abs(sum(atom["isolated_A2"] for atom in rows[p_count:]) - summary["ligand_sasa_isolated_A2"]) > tolerance or
            abs(sum(atom["bound_A2"] for atom in rows[:p_count]) - summary["protein_sasa_bound_A2"]) > tolerance or
            abs(sum(atom["bound_A2"] for atom in rows[p_count:]) - summary["ligand_sasa_bound_A2"]) > tolerance or
            abs(summary["total_sasa_loss_A2"] - summary["protein_burial_A2"] - summary["ligand_burial_A2"]) > tolerance or
            any(abs(sum(row[field] for row in per_residue) - sum(atom[field] for atom in rows[:p_count])) > tolerance
                for field in ("isolated_A2", "bound_A2", "buried_A2"))):
        raise ToolFailure(FailureClass.fatal, "SASA partner/residue accounting failed")
    content = {"schema": "interface_sasa@1", "structure": structure, "ligand": selector.model_dump(),
               "selection": {"protein": "canonical20_polymer_heavy_atoms_all_included_chains",
                             "protein_residues": protein_refs,
                             "ligand": selector.model_dump(), "excluded": excluded,
                             "hydrogen_policy": "exclude_H_D", "origin_translation_A": origin,
                             "environment_scope": "selected protein and one ligand only; not the full crystal or asymmetric unit",
                             "max_absolute_coordinate_A": 1e6, "max_extent_A": 1e4},
               "method": dep, "numeric_tolerance": {"absolute_A2": AREA_TOL_A2, "relative": 1e-10,
                                                     "rendering": "ROUND_HALF_UP_2dp"},
               "atom_counts": {"protein": p_count, "ligand": len(ligand_atoms), "excluded_residues": len(excluded)},
               "atoms": rows, "residues": per_residue, "summary": summary,
               "limitations": "Probe/radius/resolution-dependent two-partner solvent-accessible geometry; not affinity, energy or stability."}
    return ctx.store.put("interface_sasa", "interface_sasa@1", content, produced_by=ctx.call_id,
                         summary={"structure": structure, "ligand": selector.model_dump(),
                                  "protein_burial_A2": summary["protein_burial_A2"],
                                  "ligand_burial_A2": summary["ligand_burial_A2"],
                                  "total_sasa_loss_A2": summary["total_sasa_loss_A2"]})


def register(reg: ToolRegistry) -> None:
    reg.register("compute_interface_sasa")(calculate)
