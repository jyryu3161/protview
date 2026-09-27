"""Source-bound atom measurements and explicit proper-rotation CA fitting."""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from typing import Any

import gemmi
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import Handle
from ..openmm_reports import validated_minimized_structure
from .registry import ToolContext, ToolRegistry
from .structural import _parse, _res_ref, structure_bytes

SOURCE_TYPES = {
    ("structure", "structure_selection@2"),
    ("prepared_structure", "prepared_structure@1"),
    ("openmm_minimized_structure", "openmm_minimized_structure@1"),
}
MAX_ATOMS = 200_000
RANK_ABSOLUTE = 1e-12
RANK_RELATIVE = 1e-8


class CompleteResidueRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model_number: int
    chain_auth: str
    seq_auth: int
    icode: str
    chain_label: str | None
    seq_label: int | None
    resname: str


class AtomRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    structure_handle: str
    residue: CompleteResidueRef
    atom_name: str
    altloc: str
    element: str
    site_index: int = Field(ge=0)


def _source(store: Any, handle: str) -> None:
    try:
        meta = store.meta(handle)
    except KeyError as exc:
        raise ToolFailure(FailureClass.input_invalid, "unknown same-run source") from exc
    if (meta["kind"], meta["schema"]) not in SOURCE_TYPES:
        raise ToolFailure(FailureClass.input_invalid, "unsupported immutable structure source")
    if meta["kind"] == "openmm_minimized_structure":
        try:
            validated_minimized_structure(type("RunView", (), {
                "store": store, "events": store.events, "run_id": store.run_id})(), handle)
        except ValueError as exc:
            raise ToolFailure(FailureClass.input_invalid, "invalid minimized structure") from exc


def atom_rows(store: Any, handle: str) -> dict[str, Any]:
    """Rows are in the deterministic traversal of the exact served model."""
    _source(store, handle)
    raw, fmt = structure_bytes(store, handle)
    # Raw served atom_site/PDB row order is Mol* sourceIndex order. Reconcile
    # unique row IDs to immutable selected-source sites; never infer by name.
    original = _parse(ToolContext(store=store, call_id="atom_catalog"), handle)
    def traverse(st: Any) -> list[tuple[Any, Any, Any, bool]]:
        return [(ch, res, atom, res.het_flag == "A" and gemmi.find_tabulated_residue(res.name).is_amino_acid())
                for ch in st[0] for res in ch for atom in res]

    source_atoms = traverse(original)
    if len(source_atoms) > MAX_ATOMS:
        raise ToolFailure(FailureClass.resource_exceeded, "source atom limit exceeded")
    try:
        if fmt == "pdb":
            viewer_records = []
            for line in raw.decode().splitlines():
                if line.startswith(("ATOM  ", "HETATM")):
                    viewer_records.append({"id": int(line[6:11]), "name": line[12:16].strip(),
                                           "altloc": line[16].strip(), "resname": line[17:20].strip(),
                                           "chain_auth": line[21].strip(), "seq_auth": int(line[22:26]),
                                           "icode": line[26].strip(), "model_number": original[0].num,
                                           "element": line[76:78].strip().upper(),
                                           "coordinate_A": [float(line[i:i + 8]) for i in (30, 38, 46)]})
        else:
            category = gemmi.cif.read_string(raw.decode()).sole_block().get_mmcif_category("_atom_site.")
            viewer_records = []
            for i, serial in enumerate(category["id"]):
                def value(key: str, fallback: Any = None, index: int = i) -> Any:
                    return category.get(key, fallback)[index]
                viewer_records.append({"id": int(serial),
                    "name": value("auth_atom_id", category["label_atom_id"]).strip(),
                    "altloc": "" if value("label_alt_id") in {".", "?", False, None} else value("label_alt_id"),
                    "resname": value("auth_comp_id", category["label_comp_id"]),
                    "chain_auth": value("auth_asym_id"), "seq_auth": int(value("auth_seq_id")),
                    "icode": "" if value("pdbx_PDB_ins_code") in {".", "?", False, None} else value("pdbx_PDB_ins_code"),
                    "model_number": int(value("pdbx_PDB_model_num")),
                    "element": value("type_symbol").upper(),
                    "coordinate_A": [float(value(key)) for key in ("Cartn_x", "Cartn_y", "Cartn_z") ]})
    except (UnicodeDecodeError, KeyError, ValueError, TypeError, IndexError, RuntimeError) as exc:
        raise ToolFailure(FailureClass.input_invalid, "served atom rows are malformed") from exc
    if len(viewer_records) != len(source_atoms):
        raise ToolFailure(FailureClass.input_invalid, "viewer/source atom count mismatch")
    if store.meta(handle)["kind"] == "structure":
        # structure_bytes serializes the exact selected Gemmi model in traversal
        # order and renumbers row IDs. Its writer order is the provenance map;
        # identical source sites cannot be proven distinct after serialization.
        fingerprints = [(ch.name, res.seqid.num, res.seqid.icode.strip(), res.subchain,
                         res.label_seq, res.name,
                         atom.name, atom.altloc.strip("\x00 "), atom.element.name.upper(),
                         atom.pos.x, atom.pos.y, atom.pos.z)
                        for ch, res, atom, _ in source_atoms]
        if len(set(fingerprints)) != len(fingerprints):
            raise ToolFailure(FailureClass.input_invalid, "identical original atom sites are ambiguous")
        source_to_viewer = {site: site for site in range(len(source_atoms))}
    else:
        # Prepared/minimized coordinates are served unchanged. Their raw
        # row IDs, unlike an original reserialized structure, are preserved.
        serials = [atom.serial for _, _, atom, _ in source_atoms]
        if (len(set(serials)) != len(serials) or
                Counter(record["id"] for record in viewer_records) != Counter(serials)):
            raise ToolFailure(FailureClass.input_invalid, "viewer atom rows lack unique source IDs")
        record_by_id = {record["id"]: i for i, record in enumerate(viewer_records)}
        source_to_viewer = {site: record_by_id[atom.serial]
                            for site, (_, _, atom, _) in enumerate(source_atoms)}
    if len(set(source_to_viewer.values())) != len(source_atoms):
        raise ToolFailure(FailureClass.input_invalid, "viewer/source atom mapping is not one-to-one")
    rows = []
    for i, (ch, res, atom, protein) in enumerate(source_atoms):
        viewer_index = source_to_viewer[i]
        record = viewer_records[viewer_index]
        if (record["name"] != atom.name or record["altloc"] != atom.altloc.strip("\x00 ") or
                record["element"] != atom.element.name.upper() or
                (record["chain_auth"], record["seq_auth"], record["icode"], record["resname"],
                 record["model_number"]) !=
                (ch.name, res.seqid.num, res.seqid.icode.strip(), res.name, original[0].num) or
                any(abs(x - y) > 1e-4 for x, y in zip(record["coordinate_A"],
                                                      (atom.pos.x, atom.pos.y, atom.pos.z)))):
            raise ToolFailure(FailureClass.input_invalid, "viewer atom row cannot be reconciled to source")
        ref = AtomRefV1(structure_handle=handle,
                        residue=CompleteResidueRef(**_res_ref(ch, res, original[0].num)),
                        atom_name=atom.name, altloc=atom.altloc.strip("\x00 "),
                        element=atom.element.name.upper(), site_index=i)
        rows.append({"ref": ref.model_dump(), "coordinate_A": [atom.pos.x, atom.pos.y, atom.pos.z],
                     "protein": protein, "viewer_source_index": viewer_index})
    return {"schema": "atom_catalog@1", "structure_handle": handle,
            "viewer_source_sha256": hashlib.sha256(raw).hexdigest(), "model_number": original[0].num,
            "total": len(rows), "rows": rows}


def resolve(store: Any, handle: str, proposed: Any, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        ref = AtomRefV1.model_validate(proposed).model_dump()
    except ValueError as exc:
        raise ToolFailure(FailureClass.input_invalid, "invalid complete AtomRefV1") from exc
    if ref["structure_handle"] != handle:
        raise ToolFailure(FailureClass.input_invalid, "atom belongs to a different structure source")
    rows = (catalog or atom_rows(store, handle))["rows"]
    index = ref["site_index"]
    if index >= len(rows) or rows[index]["ref"] != ref:
        raise ToolFailure(FailureClass.input_invalid, "atom identity does not match source site")
    return rows[index]


def _checked(ctx: ToolContext) -> None:
    if ctx.check_cancelled:
        ctx.check_cancelled()
    if ctx.remaining_s and ctx.remaining_s() <= 0:
        raise ToolFailure(FailureClass.resource_exceeded, "comparison deadline exceeded")


def _rank(values: np.ndarray, unit: str) -> tuple[list[float], float]:
    if not np.isfinite(values).all():
        raise ToolFailure(FailureClass.input_invalid, "nonfinite centered coordinates")
    try:
        singular = np.linalg.svd(values, compute_uv=False)
    except np.linalg.LinAlgError as exc:
        raise ToolFailure(FailureClass.input_invalid, "singular-value fit did not converge") from exc
    if not np.isfinite(singular).all():
        raise ToolFailure(FailureClass.input_invalid, "nonfinite singular values")
    threshold = max(RANK_ABSOLUTE, RANK_RELATIVE * float(singular[0]))
    if len(singular) < 2 or singular[1] <= threshold:
        raise ToolFailure(FailureClass.input_invalid, f"degenerate or ill-conditioned {unit} correspondence")
    return singular.tolist(), threshold


def register(reg: ToolRegistry) -> None:
    @reg.register("measure_distance")
    def measure_distance(ctx: ToolContext, structure: str, first: dict[str, Any], second: dict[str, Any]) -> Handle:
        _checked(ctx)
        catalog = atom_rows(ctx.store, structure)
        a, b = resolve(ctx.store, structure, first, catalog), resolve(ctx.store, structure, second, catalog)
        distance = math.dist(a["coordinate_A"], b["coordinate_A"])
        if not math.isfinite(distance):
            raise ToolFailure(FailureClass.input_invalid, "distance exceeds finite numeric range")
        result = {"schema": "atom_distance@1", "structure_handle": structure,
                  "first": a["ref"], "second": b["ref"],
                  "first_coordinate_A": a["coordinate_A"], "second_coordinate_A": b["coordinate_A"],
                  "distance_A": distance, "unit": "angstrom", "method": "euclidean_atom_distance@1",
                  "limitations": "Original-source Euclidean geometry; no bond, affinity or stability inference."}
        _checked(ctx)
        return ctx.store.put("atom_distance", "atom_distance@1", result, produced_by=ctx.call_id,
                             summary={"structure_handle": structure, "distance_A": distance})

    @reg.register("align_structures")
    def align_structures(ctx: ToolContext, reference: str, moving: str,
                         pairs: list[dict[str, Any]]) -> Handle:
        _checked(ctx)
        if reference == moving:
            raise ToolFailure(FailureClass.input_invalid, "reference and moving source must differ")
        if not 3 <= len(pairs) <= 1000:
            raise ToolFailure(FailureClass.input_invalid, "alignment requires 3–1000 explicit CA pairs")
        ref_catalog, mov_catalog = atom_rows(ctx.store, reference), atom_rows(ctx.store, moving)
        used_ref, used_mov = set(), set()
        ordered = []
        for pair in pairs:
            _checked(ctx)
            if type(pair) is not dict or set(pair) != {"reference", "moving"}:
                raise ToolFailure(FailureClass.input_invalid, "pair requires exact reference and moving AtomRefs")
            a = resolve(ctx.store, reference, pair["reference"], ref_catalog)
            b = resolve(ctx.store, moving, pair["moving"], mov_catalog)
            if not a["protein"] or not b["protein"] or a["ref"]["atom_name"] != "CA" or b["ref"]["atom_name"] != "CA":
                raise ToolFailure(FailureClass.input_invalid, "alignment accepts protein CA sites only")
            ai, bi = a["ref"]["site_index"], b["ref"]["site_index"]
            if ai in used_ref or bi in used_mov:
                raise ToolFailure(FailureClass.input_invalid, "duplicate CA site in correspondence")
            used_ref.add(ai); used_mov.add(bi)
            ordered.append({"reference": a["ref"], "moving": b["ref"],
                            "reference_coordinate_A": a["coordinate_A"], "moving_coordinate_A": b["coordinate_A"]})
        q = np.asarray([row["reference_coordinate_A"] for row in ordered], dtype=np.float64)
        p = np.asarray([row["moving_coordinate_A"] for row in ordered], dtype=np.float64)
        if not np.isfinite(p).all() or not np.isfinite(q).all():
            raise ToolFailure(FailureClass.input_invalid, "nonfinite source coordinates")
        pc, qc = p.mean(axis=0), q.mean(axis=0)
        x, y = p - pc, q - qc
        p_s, p_t = _rank(x, "moving Å")
        q_s, q_t = _rank(y, "reference Å")
        h = x.T @ y
        if not np.isfinite(h).all():
            raise ToolFailure(FailureClass.input_invalid, "covariance exceeds finite numeric range")
        try:
            u, singular, vt = np.linalg.svd(h, full_matrices=False)
        except np.linalg.LinAlgError as exc:
            raise ToolFailure(FailureClass.input_invalid, "Kabsch fit did not converge") from exc
        if not np.isfinite(singular).all():
            raise ToolFailure(FailureClass.input_invalid, "nonfinite covariance singular values")
        h_t = max(RANK_ABSOLUTE, RANK_RELATIVE * float(singular[0]))
        if singular[1] <= h_t:
            raise ToolFailure(FailureClass.input_invalid, "degenerate or ill-conditioned covariance Å²")
        d = np.diag([1.0, 1.0, float(np.linalg.det(vt.T @ u.T))])
        rotation = vt.T @ d @ u.T
        translation = qc - rotation @ pc
        fitted = p @ rotation.T + translation
        determinant = float(np.linalg.det(rotation))
        if (not np.isfinite(rotation).all() or not np.isfinite(translation).all() or
                abs(determinant - 1) > 1e-10 or
                not np.allclose(rotation.T @ rotation, np.eye(3), rtol=0, atol=1e-10)):
            raise ToolFailure(FailureClass.fatal, "proper rotation numerical validation failed")
        before = np.linalg.norm(p - q, axis=1)
        after = np.linalg.norm(fitted - q, axis=1)
        if not np.isfinite(before).all() or not np.isfinite(after).all():
            raise ToolFailure(FailureClass.input_invalid, "alignment residual exceeds finite numeric range")
        for row, old, new in zip(ordered, before, after):
            row["before_residual_A"] = float(old)
            row["after_residual_A"] = float(new)
        result = {"schema": "rigid_alignment@1", "reference_handle": reference, "moving_handle": moving,
                  "reference_model_number": ref_catalog["model_number"],
                  "moving_model_number": mov_catalog["model_number"], "pairs": ordered,
                  "pair_count": len(ordered), "method": "unweighted_proper_rotation_kabsch@1",
                  "numpy_version": np.__version__, "rotation": rotation.tolist(),
                  "translation_A": translation.tolist(), "transform_convention": "column_q=R_p+t; row_Pfit=P_Rtranspose+t",
                  "rmsd_A": float(np.sqrt(np.mean(after ** 2))),
                  "unaligned_rmsd_A": float(np.sqrt(np.mean(before ** 2))),
                  "fit_singular_values_A2": singular.tolist(),
                  "degeneracy": {"relative": RANK_RELATIVE, "absolute": RANK_ABSOLUTE,
                                 "moving_singular_values_A": p_s, "moving_threshold_A": p_t,
                                 "reference_singular_values_A": q_s, "reference_threshold_A": q_t,
                                 "covariance_threshold_A2": h_t},
                  "unit": "angstrom", "limitations": "RMSD applies only to the explicit CA pairs; rigid fit is not affinity, stability or structural quality."}
        if not math.isfinite(result["rmsd_A"]) or not math.isfinite(result["unaligned_rmsd_A"]):
            raise ToolFailure(FailureClass.input_invalid, "RMSD exceeds finite numeric range")
        _checked(ctx)
        return ctx.store.put("rigid_alignment", "rigid_alignment@1", result, produced_by=ctx.call_id,
                             summary={"reference_handle": reference, "moving_handle": moving,
                                      "pair_count": len(ordered), "rmsd_A": result["rmsd_A"]})
