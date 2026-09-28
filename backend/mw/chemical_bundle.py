"""M11 typed native-worker exchange and immutable, acyclic chemistry objects."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import subprocess
import threading
from pathlib import Path
from typing import Any

import gemmi

from .chemical_inputs import (
    DERIVED_COORDINATE_POLICY,
    _bonds,
    _bytes,
    _sdf_records,
    _source_rows,
    _terminal_extension_inventory,
    invalid,
    preview,
)
from .core.errors import FailureClass, ToolFailure
from .core.handles import canonical_json, object_sha
from .tools.comparison import atom_rows

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend/mw/jobs/chemical_worker.py"
WORKER_PYTHON = ROOT / ".deps/prolif/venv-locked/bin/python"
LOCK = ROOT / "config/chemical/prolif-wheel-hashes-macos-arm64-py311.json"
CATEGORIES = ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]
NATIVE_SMARTS_SHA256 = "3dbf3c1663f9ed4f7e49250f32f9a8849bc6297278ffaf2f624004591f81caf5"
NATIVE_ENGINE_SOURCE_SHA256 = {
    "interactions.py": "9b891c16eae1340269b6860131b9bef6f8d9676a54171e0b9c48b6c7aa1b6798",
    "base.py": "3c10fe88839767db22eb43e7b535e087af1d98e60e07a21a2b1708e0727aad91",
}
ENGINE_COORDINATE_POLICY = "source float64; receptor MDAnalysis float32 and ligand SDF conformer retained"
STEREOCHEMISTRY_POLICY = ("V2000 explicit tetrahedral atom parity must agree with selected 3D geometry; "
                          "RDKit 3D coordinates supersede wedge/dash depiction; ambiguous stereo is unsupported")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _native_criteria(dependency_manifest: dict[str, Any]) -> dict[str, Any]:
    method = dependency_manifest["native_method"]
    expected = {"categories": CATEGORIES, "Hbond_distance_A": 3.5,
                "Hbond_DHA_angle_deg": [130, 180], "Hydrophobic_distance_A": 4.5,
                "Cationic_distance_A": 4.5, "Anionic_distance_A": 4.5,
                "vicinity_cutoff_A": 6.0}
    smarts = method["native_smarts"]
    if (method["schema"] != "chemical_native_method@1" or
            method["source_sha256"] != NATIVE_ENGINE_SOURCE_SHA256 or
            method["criteria"] != expected or
            type(smarts) is not dict or set(smarts) != set(CATEGORIES) or
            any(type(smarts[name]) is not dict or set(smarts[name]) != {"ligand", "protein"} or
                any(type(value) is not str or not value or len(value) > 2048
                    for value in smarts[name].values()) for name in CATEGORIES) or
            method["native_smarts_sha256"] != NATIVE_SMARTS_SHA256 or
            _sha(canonical_json(smarts)) != NATIVE_SMARTS_SHA256):
        raise ValueError("native method SMARTS/criteria provenance mismatch")
    return {**expected, "native_smarts": smarts, "native_smarts_sha256": NATIVE_SMARTS_SHA256}


_DEPENDENCY_CACHE: dict[tuple, dict[str, Any]] = {}
_DEPENDENCY_LOCK = threading.Lock()


def _dependency_key() -> tuple:
    """Everything a successful handshake is bound to; any change forces a fresh handshake."""
    interpreter = WORKER_PYTHON.resolve(strict=True)
    info = interpreter.stat()
    return (str(WORKER_PYTHON), str(interpreter), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            _sha(LOCK.read_bytes()), _sha(WORKER.read_bytes()))


def dependency() -> dict[str, Any]:
    # A Python venv normally exposes bin/python as a symlink to its pinned
    # base interpreter. The path is fixed by deployment, never request data.
    if not WORKER_PYTHON.is_file() or not LOCK.is_file():
        raise ToolFailure(FailureClass.precondition, "pinned chemical worker unavailable",
                          detail={"reason_code": "chemical_worker_missing"})
    with _DEPENDENCY_LOCK:
        try:
            key = _dependency_key()
        except OSError as exc:
            raise ToolFailure(FailureClass.precondition, "pinned chemical worker handshake failed",
                              detail={"reason_code": "chemical_worker_unavailable"}) from exc
        # Only a verified handshake is reused, and only while the interpreter identity, lock-file
        # and worker-file hashes it was checked against are unchanged. Failures always re-probe.
        cached = _DEPENDENCY_CACHE.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
        data = _handshake()
        _DEPENDENCY_CACHE.clear()
        _DEPENDENCY_CACHE[key] = copy.deepcopy(data)
        return data


def _handshake() -> dict[str, Any]:
    try:
        proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER), "--handshake"],
                              cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1",
                                             "PYTHONUNBUFFERED": "1"}, capture_output=True, timeout=8, check=True)
        if len(proc.stdout) > 8192 or len(proc.stderr) > 8192:
            raise ValueError("oversized capability output")
        data = json.loads(proc.stdout)
        if (data.get("schema") != "chemical_worker_handshake@1" or
                data.get("lock_sha256") != _sha(LOCK.read_bytes()) or
                data.get("worker_sha256") != _sha(WORKER.read_bytes()) or
                data.get("versions") != {"prolif": "2.2.2", "rdkit": "2026.3.6",
                                         "MDAnalysis": "2.10.0", "gemmi": "0.7.5"} or
                data.get("python", "").split(".")[:2] != ["3", "11"]):
            raise ValueError("worker pin mismatch")
        _native_criteria(data)
        return data
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ToolFailure(FailureClass.precondition, "pinned chemical worker handshake failed",
                          detail={"reason_code": "chemical_worker_unavailable"}) from exc


def prepare_selected(store: Any, req: dict[str, Any]) -> dict[str, Any]:
    check = preview(store, req, strict=True)
    if not check["ready"]:
        raise invalid("chemical preparation is not ready")
    rows, raw_pdb, source = _source_rows(store, req)
    full_bonds = _bonds(store, req, rows, raw_pdb, source)
    selected_ligand = req.get("selected_ligand") if req["mode"] == "attach_existing" else None
    kept = [(i, r) for i, r in enumerate(rows) if not r["water"] and r["ref"]["residue"] != selected_ligand]
    remap = {old: new for new, (old, _) in enumerate(kept)}
    bonds = [[remap[a], remap[b]] for a, b in full_bonds if a in remap and b in remap]
    raw, _ = _bytes(store, req["ligand_sdf_handle"], "ligand_sdf")
    attached_source_sites = ([{"sdf_atom_index": entry["sdf_atom_index"],
                               "source_atom": entry["source_atom"],
                               "source_coordinate_A": rows[entry["source_atom"]["site_index"]]["coordinate_A"],
                               "discrepancy_A": next(item["discrepancy_A"] for item in check["ligand_mapping"]
                                                     if item["sdf_atom_index"] == entry["sdf_atom_index"])}
                              for entry in req["mapping"]] if req["mode"] == "attach_existing" else [])
    return {"schema": "chemical_prepare_worker_input@1", "request": req,
            "source_handle": source, "dependency": dependency(),
            "receptor_atoms": [{"source_ref": r["ref"], "coordinate_A": r["coordinate_A"],
                                "element": r["element"]} for _, r in kept],
            "receptor_bonds": bonds, "excluded_water_atoms": sum(r["water"] for r in rows),
            "attached_source_sites": attached_source_sites,
            "excluded_original_ligand_hydrogens": check["excluded_original_ligand_hydrogens"],
            "terminal_extension_inventory": check["terminal_extensions"],
            "ligand_sdf_b64": base64.b64encode(raw).decode("ascii"),
            "ligand_atom_names": [atom["atom_name"] for atom in check["ligand_atoms"]],
            "ligand_sdf_sha256": _sha(raw), "sdf_record_index": req["sdf_record_index"]}


def _json_object(store: Any, handle: str, kind: str, schema: str) -> dict[str, Any]:
    meta = store.meta(handle)
    limit = {"chemical_preparation_manifest": 8 * 1024 * 1024,
             "chemical_structure": 32 * 1024 * 1024,
             "chemical_graph": 32 * 1024 * 1024,
             "chemical_interaction_set": 8 * 1024 * 1024}[kind]
    value = store.load_bounded_json(handle, limit)
    if (meta["kind"], meta["schema"]) != (kind, schema) or type(value) is not dict or value.get("schema") != schema:
        raise invalid("chemical object type or schema mismatch")
    return value


def _single_ligand_component(atom_count: int, bonds: list[dict[str, Any]]) -> bool:
    if not 1 <= atom_count <= 256:
        return False
    adjacency = [set() for _ in range(atom_count)]
    for bond in bonds:
        if (type(bond) is not dict or type(bond.get("first")) is not int or
                type(bond.get("second")) is not int or
                not 0 <= bond["first"] < atom_count or not 0 <= bond["second"] < atom_count or
                bond["first"] == bond["second"]):
            return False
        adjacency[bond["first"]].add(bond["second"])
        adjacency[bond["second"]].add(bond["first"])
    seen = {0}
    frontier = [0]
    while frontier:
        for other in adjacency[frontier.pop()]:
            if other not in seen:
                seen.add(other)
                frontier.append(other)
    return len(seen) == atom_count


def _tetrahedral_determinant(points: list[list[float]]) -> float:
    vectors = [[points[i][axis] - points[3][axis] for axis in range(3)] for i in range(3)]
    return (vectors[0][0] * (vectors[1][1] * vectors[2][2] - vectors[1][2] * vectors[2][1]) -
            vectors[0][1] * (vectors[1][0] * vectors[2][2] - vectors[1][2] * vectors[2][0]) +
            vectors[0][2] * (vectors[1][0] * vectors[2][1] - vectors[1][1] * vectors[2][0]))


def _validate_stereo_audit(audit: Any, record: dict[str, Any], ligand: list[dict[str, Any]]) -> None:
    atoms = record["atoms"]
    if len(atoms) != len(ligand) or type(audit) is not list or len(audit) > 256:
        raise ValueError("incomplete selected-SDF stereochemistry audit")
    neighbor_ids = [set() for _ in atoms]
    for first, second, _ in record["bonds"]:
        neighbor_ids[first].add(second)
        neighbor_ids[second].add(first)
    expected_indices = [i for i, atom in enumerate(atoms) if atom["declared_parity"] in {1, 2}]
    if [row.get("sdf_atom_index") for row in audit if type(row) is dict] != expected_indices or len(audit) != len(expected_indices):
        raise ValueError("selected-SDF declared stereo centers not completely audited")
    for row in audit:
        if (type(row) is not dict or set(row) != {"sdf_atom_index", "declared_parity", "declared_CIP",
                                                "observed_CIP", "signed_tetrahedral_determinant_A3",
                                                "method", "outcome"}):
            raise ValueError("invalid stereochemistry audit row shape")
        index = row["sdf_atom_index"]
        if (type(index) is not int or type(row["declared_parity"]) is not int or
                row["declared_parity"] != atoms[index]["declared_parity"] or
                row["declared_CIP"] not in {"R", "S"} or row["observed_CIP"] != row["declared_CIP"] or
                row["method"] != "rdkit_v2000_parity_vs_3d@1" or row["outcome"] != "match" or
                len(neighbor_ids[index]) != 4):
            raise ValueError("stereochemistry audit declaration/outcome mismatch")
        ids = sorted(neighbor_ids[index])
        coordinates = [ligand[i]["coordinate_A"] for i in ids]
        if any(math.dist(coordinates[j], atoms[ids[j]]["coordinate_A"]) > 1e-5 for j in range(4)):
            raise ValueError("stereochemistry audit source coordinates changed")
        determinant = _tetrahedral_determinant(coordinates)
        saved = row["signed_tetrahedral_determinant_A3"]
        if (type(saved) not in (int, float) or not math.isfinite(saved) or
                abs(determinant) <= 1e-8 or
                abs(saved - determinant) > 1e-8 * max(1.0, abs(determinant))):
            raise ValueError("stereochemistry audit 3D geometry mismatch")


def _cif_row_matches(category: dict[str, list[Any]], index: int, row: dict[str, Any],
                     generated_labels: dict[str, str], model_number: int) -> bool:
    residue = row["residue"]
    label_asym = (residue["chain_label"] if residue["chain_label"] is not None else
                  generated_labels[residue["chain_auth"]])
    expected = {"id": str(index + 1), "group_PDB": "ATOM" if row["protein"] else "HETATM",
                "type_symbol": row["element"], "label_atom_id": row["atom_name"],
                "label_alt_id": row["altloc"] or False, "label_comp_id": residue["resname"],
                "label_asym_id": label_asym, "label_seq_id": str(residue["seq_label"])
                if residue["seq_label"] is not None else False,
                "pdbx_PDB_ins_code": residue["icode"] or None,
                "auth_seq_id": str(residue["seq_auth"]), "auth_comp_id": residue["resname"],
                "auth_asym_id": residue["chain_auth"], "auth_atom_id": row["atom_name"],
                "pdbx_PDB_model_num": str(model_number)}
    return (all(category[key][index] == value for key, value in expected.items()) and
            [float(category[key][index]) for key in ("Cartn_x", "Cartn_y", "Cartn_z")] == row["coordinate_A"])


def validated_source(store: Any, handle: str) -> dict[str, Any]:
    source = _json_object(store, handle, "chemical_structure", "chemical_structure@1")
    manifest = _json_object(store, source["manifest_handle"], "chemical_preparation_manifest",
                            "chemical_preparation_manifest@1")
    raw = source["text"].encode("utf-8")
    if (source["manifest_sha256"] != _sha(canonical_json(manifest)) or
            source["viewer_source_sha256"] != _sha(raw) or
            source["model_number"] != manifest["model_number"] or
            type(source["atoms"]) is not list or len(source["atoms"]) > 10_256):
        raise invalid("chemical source manifest/hash/model mismatch")
    try:
        category = gemmi.cif.read_string(source["text"]).sole_block().get_mmcif_category("_atom_site.")
        if len(category["id"]) != len(source["atoms"]):
            raise ValueError("atom_site count")
        expanded = []
        for i, local in enumerate(source["atoms"]):
            ref = {"structure_handle": handle, "residue": local["residue"],
                   "atom_name": local["atom_name"], "altloc": local["altloc"],
                   "element": local["element"], "site_index": i}
            row = {"ref": ref, "coordinate_A": local["coordinate_A"],
                   "protein": local["protein"], "viewer_source_index": i}
            if (local["local_site_index"] != i or local["viewer_source_index"] != i or
                    not _cif_row_matches(category, i, local,
                                         manifest["generated_label_asym_by_auth_chain"],
                                         source["model_number"])):
                raise ValueError("atom_site/ref mapping")
            expanded.append(row)
    except (KeyError, ValueError, RuntimeError, IndexError, TypeError) as exc:
        raise invalid("chemical source atom-site mapping invalid") from exc
    try:
        sdf_bytes, _ = _bytes(store, manifest["ligand_sdf_handle"], "ligand_sdf")
        record = _sdf_records(sdf_bytes.decode("utf-8"))[manifest["request"]["sdf_record_index"]]
        receptor_count = len(manifest["receptor_local_sites"])
        _validate_stereo_audit(manifest["stereochemistry_audit"], record, expanded[receptor_count:])
    except (KeyError, ValueError, UnicodeError, IndexError, TypeError, ToolFailure) as exc:
        raise invalid("chemical source stereochemistry provenance invalid") from exc
    return {**source, "atoms": expanded, "handle": handle}


def atom_catalog(store: Any, handle: str, offset: int, limit: int) -> dict[str, Any]:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise invalid("invalid chemical atom catalog page")
    source = validated_source(store, handle)
    return {"schema": "atom_catalog@1", "structure_handle": handle,
            "viewer_source_sha256": source["viewer_source_sha256"], "model_number": source["model_number"],
            "total": len(source["atoms"]), "offset": offset, "limit": limit,
            "rows": source["atoms"][offset:offset + limit]}


def validated_graph(store: Any, handle: str) -> dict[str, Any]:
    graph = _json_object(store, handle, "chemical_graph", "chemical_graph@1")
    source = validated_source(store, graph["chemical_structure_handle"])
    manifest = _json_object(store, graph["manifest_handle"], "chemical_preparation_manifest",
                            "chemical_preparation_manifest@1")
    if (graph["manifest_handle"] != source["manifest_handle"] or
            graph["dependency"] != manifest["dependency"] or
            graph.get("coordinate_policy") != ENGINE_COORDINATE_POLICY):
        raise invalid("chemical graph/source manifest mismatch")
    combined = graph["receptor_atoms"] + graph["ligand_atoms"]
    if (len(combined) != len(source["atoms"]) or
            any(a["ref"] != b["ref"] or a["coordinate_A"] != b["coordinate_A"]
                for a, b in zip(combined, source["atoms"], strict=True))):
        raise invalid("chemical graph atom/source bijection mismatch")
    request = manifest["request"]
    if (manifest.get("derived_coordinate_policy") != DERIVED_COORDINATE_POLICY or
            manifest.get("stereochemistry_policy") != STEREOCHEMISTRY_POLICY):
        raise invalid("chemical derived coordinate policy changed")
    originals = ({entry["sdf_atom_index"]: entry["source_atom"] for entry in request["mapping"]}
                 if request["mode"] == "attach_existing" else {})
    if len(originals) != len(request.get("mapping", [])):
        raise invalid("chemical attach mapping duplicates SDF site")
    attached = manifest["attached_source_sites"]
    if (type(attached) is not list or len(attached) != len(originals) or
            {entry["sdf_atom_index"] for entry in attached} != set(originals)):
        raise invalid("chemical attach source-coordinate provenance incomplete")
    original_rows = atom_rows(store, request["complex_handle"])["rows"] if originals else []
    if request["mode"] == "attach_existing":
        old_ligand = [row["ref"] for row in original_rows
                      if row["ref"]["residue"] == request["selected_ligand"]]
        required = {ref["site_index"] for ref in old_ligand
                    if ref["element"].upper() != "H" or request["hydrogen_policy"] == "map_existing"}
        mapped = {ref["site_index"] for ref in originals.values()}
        excluded = ([ref for ref in old_ligand if ref["element"].upper() == "H"]
                    if request["hydrogen_policy"] == "replace_from_sdf" else [])
        if mapped != required or manifest["excluded_original_ligand_hydrogens"] != excluded:
            raise invalid("chemical attach original ligand inventory is not bijective")
    elif manifest["excluded_original_ligand_hydrogens"]:
        raise invalid("new chemical source cannot exclude prior ligand hydrogens")
    for entry in attached:
        index = entry["sdf_atom_index"]
        original = entry["source_atom"]
        coordinate = entry["source_coordinate_A"]
        site = original["site_index"]
        if (type(index) is not int or index not in originals or original != originals[index] or
                type(site) is not int or not 0 <= site < len(original_rows) or
                original_rows[site]["ref"] != original or original_rows[site]["coordinate_A"] != coordinate or
                type(entry["discrepancy_A"]) not in (int, float) or
                not math.isfinite(entry["discrepancy_A"]) or
                abs(math.dist(coordinate, graph["ligand_atoms"][index]["coordinate_A"]) -
                    entry["discrepancy_A"]) > 1e-9 or entry["discrepancy_A"] > .002):
            raise invalid("chemical attach original/SDF coordinate provenance changed")
    for i, atom in enumerate(graph["ligand_atoms"]):
        if atom.get("original_source_ref") != originals.get(i):
            raise invalid("chemical ligand original source map changed")
        original = originals.get(i)
        if original and (atom["ref"]["atom_name"] != original["atom_name"] or
                         atom["ref"]["altloc"] != original["altloc"] or
                         atom["ref"]["residue"] != original["residue"]):
            raise invalid("chemical attached ligand source identity changed")
    for side in ("receptor", "ligand"):
        atoms, bonds = graph[f"{side}_atoms"], graph[f"{side}_bonds"]
        if [a["native_parent_index"] for a in atoms] != list(range(len(atoms))):
            raise invalid("chemical native parent index mismatch")
        synthetic: dict[str, int] = {}
        for i, atom in enumerate(atoms):
            ref = atom["ref"]
            residue_key = json.dumps(ref["residue"], sort_keys=True)
            synthetic.setdefault(residue_key, len(synthetic))
            coords = atom["engine_coordinate_A"]
            if (atom["local_site_index"] != i or atom["element"] != ref["element"] or
                    atom["synthetic_residue_index"] != synthetic[residue_key] or
                    type(atom["formal_charge"]) is not int or type(atom["aromatic"]) is not bool or
                    type(coords) is not list or len(coords) != 3 or
                    any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 100_000
                        for x in coords) or math.dist(coords, atom["coordinate_A"]) > 1e-4):
                raise invalid("chemical graph native atom/source mapping invalid")
            if side == "receptor" and atom["source_ref"] != manifest["receptor_local_sites"][i]:
                raise invalid("chemical graph receptor source identity changed")
            if side == "ligand" and atom["sdf_atom_index"] != manifest["ligand_sdf_indices"][i]:
                raise invalid("chemical graph SDF atom identity changed")
        pairs = []
        for bond in bonds:
            x, y = bond["first"], bond["second"]
            if (type(x) is not int or type(y) is not int or x == y or not 0 <= x < len(atoms) or
                    not 0 <= y < len(atoms) or bond["order"] not in {"SINGLE", "DOUBLE", "TRIPLE", "AROMATIC"}):
                raise invalid("chemical graph bond endpoint invalid")
            pairs.append(tuple(sorted((x, y))))
        if len(set(pairs)) != len(pairs):
            raise invalid("chemical graph duplicate bond")
    if not _single_ligand_component(len(graph["ligand_atoms"]), graph["ligand_bonds"]):
        raise invalid("chemical ligand covalent graph is disconnected")
    try:
        sdf_bytes, _ = _bytes(store, manifest["ligand_sdf_handle"], "ligand_sdf")
        record = _sdf_records(sdf_bytes.decode("utf-8"))[request["sdf_record_index"]]
        _validate_stereo_audit(manifest["stereochemistry_audit"], record, graph["ligand_atoms"])
    except (KeyError, ValueError, UnicodeError, IndexError, TypeError, ToolFailure) as exc:
        raise invalid("chemical graph stereochemistry provenance invalid") from exc
    receptor_sites = [{"ref": atom["source_ref"], "element": atom["element"], "water": False}
                      for atom in graph["receptor_atoms"]]
    inventory, blockers = _terminal_extension_inventory(
        receptor_sites, [[bond["first"], bond["second"]] for bond in graph["receptor_bonds"]],
        None, manifest["request"]["terminal_extensions"])
    if blockers or inventory != manifest["terminal_extension_inventory"]:
        raise invalid("chemical terminal extension graph provenance mismatch")
    try:
        if manifest["histidine_states"] != _histidine_inventory(graph["receptor_atoms"],
                                                               graph["receptor_bonds"]):
            raise ValueError("histidine graph state changed")
    except (KeyError, ValueError, TypeError) as exc:
        raise invalid("chemical graph histidine provenance mismatch") from exc
    return graph


def detect_selected(store: Any, req: dict[str, Any]) -> dict[str, Any]:
    if (type(req) is not dict or set(req) != {"schema", "graph_handle", "categories"} or
            req["schema"] != "chemical_detect_request@1" or req["categories"] != CATEGORIES):
        raise invalid("fixed chemical detection request required")
    graph = validated_graph(store, req["graph_handle"])
    return {"schema": "chemical_detect_worker_input@1", "request": req,
            "dependency": dependency(), "graph": graph}


def _generated_label_asym(rows: list[dict]) -> dict[str, str]:
    chains: list[str] = []
    for row in rows:
        residue = row["residue"]
        if residue["chain_label"] is None and residue["chain_auth"] not in chains:
            chains.append(residue["chain_auth"])
    return {auth: f"PV{index + 1}" for index, auth in enumerate(chains)}


def _cif_rows(receptor: list[dict], ligand: list[dict], model_number: int,
              generated_labels: dict[str, str]) -> str:
    doc = gemmi.cif.Document()
    block = doc.add_new_block("protview_chemical")
    columns = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
               "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x",
               "Cartn_y", "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_comp_id",
               "auth_asym_id", "auth_atom_id", "pdbx_PDB_model_num"]
    loop = block.init_loop("_atom_site.", columns)
    def q(value: str) -> str:
        # gemmi.cif.Loop.add_row accepts already-quoted CIF tokens.
        return gemmi.cif.quote(value)

    for i, row in enumerate(receptor + ligand):
        ref = row["ref"]; res = ref["residue"]
        xyz = row["coordinate_A"]
        label_asym = res["chain_label"] if res["chain_label"] is not None else generated_labels[res["chain_auth"]]
        loop.add_row(["ATOM" if row["protein"] else "HETATM", str(i + 1), q(ref["element"]),
                      q(ref["atom_name"]), q(ref["altloc"]) if ref["altloc"] else ".", q(res["resname"]),
                      q(label_asym), "1" if row["protein"] else "2",
                      str(res["seq_label"]) if res["seq_label"] is not None else ".",
                      q(res["icode"]) if res["icode"] else "?", *(repr(float(x)) for x in xyz), "1", "0",
                      str(res["seq_auth"]), q(res["resname"]), q(res["chain_auth"]),
                      q(ref["atom_name"]), str(model_number)])
    return doc.as_string()


def _check_worker_dependency(selected: dict, output: dict) -> None:
    if (type(output) is not dict or output.get("dependency") != selected["dependency"] or
            output["dependency"]["worker_sha256"] != _sha(WORKER.read_bytes())):
        raise ValueError("worker dependency or version changed during job")


def _histidine_inventory(receptor: list[dict], bonds: list[dict]) -> list[dict]:
    """Independently reconstruct the reported ring-H state from exact sites."""
    by_residue: dict[str, tuple[dict, dict[str, int]]] = {}
    for i, row in enumerate(receptor):
        residue = row["source_ref"]["residue"]
        key = json.dumps(residue, sort_keys=True)
        if key not in by_residue:
            by_residue[key] = (residue, {})
        name = row["source_ref"]["atom_name"]
        if name in by_residue[key][1]:
            raise ValueError("duplicate receptor atom name")
        by_residue[key][1][name] = i
    edges = {tuple(sorted((x["first"], x["second"]))): x["order"] for x in bonds}
    adjacency: dict[int, set[int]] = {i: set() for i in range(len(receptor))}
    for first, second in edges:
        adjacency[first].add(second)
        adjacency[second].add(first)
    states = []
    for residue, names in by_residue.values():
        if residue["resname"] not in {"HSD", "HID", "HSE", "HIE", "HSP", "HIP", "HIS"}:
            continue
        ring = ("CG", "ND1", "CE1", "NE2", "CD2")
        if not {"CB", *ring} <= names.keys():
            raise ValueError("incomplete histidine ring in native graph")
        required = tuple(zip(ring, ring[1:] + ring[:1]))
        if (any(edges.get(tuple(sorted((names[a], names[b])))) != "AROMATIC" for a, b in required) or
                edges.get(tuple(sorted((names["CB"], names["CG"])))) != "SINGLE"):
            raise ValueError("histidine aromatic ring/CB attachment invalid")
        expected_heavy = {"CG": {"CB", "ND1", "CD2"}, "ND1": {"CG", "CE1"},
                          "CE1": {"ND1", "NE2"}, "NE2": {"CE1", "CD2"},
                          "CD2": {"NE2", "CG"}}
        for name in ring:
            actual = {i for i in adjacency[names[name]] if receptor[i]["element"].upper() != "H"}
            if (not receptor[names[name]]["aromatic"] or
                    actual != {names[other] for other in expected_heavy[name]}):
                raise ValueError("histidine ring heavy-neighbor/aromatic state invalid")
        sites = []
        for atom_name in ("ND1", "NE2"):
            site = names[atom_name]
            hydrogens = [i for i, row in enumerate(receptor)
                         if row["element"].upper() == "H" and tuple(sorted((site, i))) in edges]
            if len(hydrogens) > 1:
                raise ValueError("multiple histidine ring hydrogens")
            if hydrogens:
                sites.append(atom_name)
        expected_sites = {"HSD": ["ND1"], "HID": ["ND1"], "HSE": ["NE2"],
                          "HIE": ["NE2"], "HSP": ["ND1", "NE2"], "HIP": ["ND1", "NE2"]}.get(residue["resname"])
        if expected_sites is not None and sites != expected_sites:
            raise ValueError("histidine alias/native graph mismatch")
        if sites not in (["ND1"], ["NE2"], ["ND1", "NE2"]):
            raise ValueError("unsupported histidine ring-H state")
        charges = {name: receptor[names[name]]["formal_charge"] for name in ring}
        n_charges = {name: charges[name] for name in ("ND1", "NE2")}
        if (any(charges[name] != 0 for name in ("CG", "CE1", "CD2")) or
                (sites == ["ND1", "NE2"] and sorted(n_charges.values()) != [0, 1]) or
                (sites != ["ND1", "NE2"] and any(n_charges.values()))):
            raise ValueError("histidine ring charge/H state mismatch")
        represented = {("ND1",): "neutral_ND1_H", ("NE2",): "neutral_NE2_H",
                       ("ND1", "NE2"): "cationic_ND1_NE2_H"}[tuple(sites)]
        states.append({"residue": residue, "ring_h_sites": sites,
                       "ring_formal_charge": sum(charges.values()),
                       "ring_n_charges": n_charges, "represented_state": represented,
                       "annotation": "graph-derived supplied state; not a pH prediction"})
    return states


def publish_prepare(run: Any, job: dict[str, Any], attempt_id: str,
                    worker_output: dict[str, Any]) -> list[str]:
    selected = job["selected"]
    _check_worker_dependency(selected, worker_output)
    if worker_output.get("schema") != "chemical_prepare_worker_output@1":
        raise ValueError("preparation worker schema mismatch")
    receptor, ligand = worker_output["receptor_atoms"], worker_output["ligand_atoms"]
    if (type(receptor) is not list or type(ligand) is not list or
            len(receptor) != len(selected["receptor_atoms"]) or
            not 1 <= len(ligand) <= 256 or len(receptor) + len(ligand) > 10_256 or
            worker_output["receptor_atom_count"] != len(receptor) or
            worker_output["ligand_atom_count"] != len(ligand)):
        raise ValueError("preparation atom count mismatch")
    receptor_fields = {"local_site_index", "source_ref", "coordinate_A", "engine_coordinate_A",
                       "element", "formal_charge", "aromatic", "synthetic_residue_index",
                       "native_parent_index", "atom_name"}
    ligand_fields = {"local_site_index", "sdf_atom_index", "coordinate_A", "engine_coordinate_A",
                     "element", "formal_charge", "aromatic", "synthetic_residue_index",
                     "native_parent_index", "atom_name"}
    if (any(type(row) is not dict or set(row) != receptor_fields for row in receptor) or
            any(type(row) is not dict or set(row) != ligand_fields for row in ligand)):
        raise ValueError("preparation native atom fields changed")
    if any(type(row["element"]) is not str or not row["element"] for row in receptor + ligand):
        raise ValueError("preparation native atom element type invalid")
    for i, (actual, expected) in enumerate(zip(receptor, selected["receptor_atoms"], strict=True)):
        if (actual["source_ref"] != expected["source_ref"] or
                actual["coordinate_A"] != expected["coordinate_A"] or
                actual["element"].upper() != expected["element"].upper() or
                actual["native_parent_index"] != i or actual["local_site_index"] != i or
                not math.dist(actual["engine_coordinate_A"], actual["coordinate_A"]) <= 1e-4):
            raise ValueError("receptor worker/source mapping mismatch")
    ligand_raw = base64.b64decode(selected["ligand_sdf_b64"], validate=True)
    expected_ligand = _sdf_records(ligand_raw.decode())[selected["sdf_record_index"]]
    if len(ligand) != len(expected_ligand["atoms"]):
        raise ValueError("ligand selected-record atom count mismatch")
    for i, (actual, expected) in enumerate(zip(ligand, expected_ligand["atoms"], strict=True)):
        if (actual["native_parent_index"] != i or actual["sdf_atom_index"] != i or
                actual["local_site_index"] != i or
                actual["atom_name"] != expected["atom_name"] or
                actual["element"].upper() != expected["element"].upper() or
                actual["formal_charge"] != expected["formal_charge"] or
                math.dist(actual["coordinate_A"], expected["coordinate_A"]) > 1e-5 or
                math.dist(actual["engine_coordinate_A"], expected["coordinate_A"]) > 1e-5):
            raise ValueError("ligand native/SDF mapping mismatch")
    _validate_stereo_audit(worker_output.get("stereochemistry_audit"), expected_ligand, ligand)
    if ({tuple(sorted((x["first"], x["second"]))) for x in worker_output["receptor_bonds"]} !=
            {tuple(sorted(x)) for x in selected["receptor_bonds"]}):
        raise ValueError("receptor edge-set mismatch")
    if ({tuple(sorted((x["first"], x["second"]))) for x in worker_output["ligand_bonds"]} !=
            {tuple(sorted(x[:2])) for x in expected_ligand["bonds"]}):
        raise ValueError("ligand SDF edge-set mismatch")
    if not _single_ligand_component(len(ligand), worker_output["ligand_bonds"]):
        raise ValueError("ligand SDF covalent graph is disconnected")
    input_orders = {tuple(sorted(x[:2])): x[2] for x in expected_ligand["bonds"]}
    allowed_orders = {1: {"SINGLE", "AROMATIC"}, 2: {"DOUBLE", "AROMATIC"},
                      3: {"TRIPLE"}, 4: {"AROMATIC"}}
    for bond in worker_output["ligand_bonds"]:
        edge = tuple(sorted((bond["first"], bond["second"])))
        if bond["order"] not in allowed_orders[input_orders[edge]]:
            raise ValueError("ligand native bond order contradicts selected SDF")
    if (worker_output["supplied_graph_edge_count"] !=
            len(worker_output["receptor_bonds"]) + len(worker_output["ligand_bonds"]) or
            len(worker_output["receptor_bonds"]) + len(worker_output["ligand_bonds"]) > 20_000):
        raise ValueError("combined graph edge count mismatch")
    for side in ("receptor", "ligand"):
        graph_atoms = worker_output[f"{side}_atoms"]
        for atom in graph_atoms:
            if (type(atom["formal_charge"]) is not int or type(atom["aromatic"]) is not bool or
                    type(atom["synthetic_residue_index"]) is not int or atom["synthetic_residue_index"] < 0 or
                    any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100_000
                        for v in atom["engine_coordinate_A"])):
                raise ValueError("invalid native graph atom state")
        for bond in worker_output[f"{side}_bonds"]:
            if (type(bond) is not dict or set(bond) != {"first", "second", "order"} or
                    type(bond["first"]) is not int or type(bond["second"]) is not int or
                    bond["first"] == bond["second"] or
                    not 0 <= bond["first"] < len(graph_atoms) or
                    not 0 <= bond["second"] < len(graph_atoms) or
                    bond["order"] not in {"SINGLE", "DOUBLE", "TRIPLE", "AROMATIC"}):
                raise ValueError("invalid native graph bond")
    if (type(worker_output.get("histidine_states")) is not list or
            worker_output["histidine_states"] != _histidine_inventory(receptor, worker_output["receptor_bonds"])):
        raise ValueError("native histidine state differs from supplied exact graph")
    if worker_output.get("coordinate_policy") != ENGINE_COORDINATE_POLICY:
        raise ValueError("native engine coordinate policy mismatch")
    req = selected["request"]
    model_number = req["receptor_model_number"] if req["mode"] == "create_new" else req["complex_model_number"]
    lig_identity = req["ligand_instance"] if req["mode"] == "create_new" else req["selected_ligand"]
    source_mapping = ({entry["sdf_atom_index"]: entry["source_atom"] for entry in req["mapping"]}
                      if req["mode"] == "attach_existing" else {})
    if len(source_mapping) != len(req.get("mapping", [])):
        raise ValueError("duplicate attach source mapping")
    receptor_sites = [{"ref": atom["source_ref"], "element": atom["element"], "water": False}
                      for atom in receptor]
    inventory, blockers = _terminal_extension_inventory(
        receptor_sites, selected["receptor_bonds"], None, req["terminal_extensions"])
    if blockers or inventory != selected["terminal_extension_inventory"]:
        raise ValueError("terminal extension inventory/native graph changed")
    attached_source_sites = selected["attached_source_sites"]
    if (len(attached_source_sites) != len(source_mapping) or
            {entry["sdf_atom_index"] for entry in attached_source_sites} != set(source_mapping)):
        raise ValueError("attach source-site provenance incomplete")
    for entry in attached_source_sites:
        index = entry["sdf_atom_index"]
        coordinate = entry["source_coordinate_A"]
        if (type(index) is not int or index not in source_mapping or
                entry["source_atom"] != source_mapping[index] or
                type(coordinate) is not list or len(coordinate) != 3 or
                any(type(x) not in (int, float) or not math.isfinite(x) for x in coordinate) or
                not math.dist(coordinate, ligand[index]["coordinate_A"]) <= .002 or
                abs(entry["discrepancy_A"] - math.dist(coordinate, ligand[index]["coordinate_A"])) > 1e-9):
            raise ValueError("attach source/SDF coordinate provenance mismatch")
    if (type(selected["excluded_original_ligand_hydrogens"]) is not list or
            req["mode"] == "create_new" and selected["excluded_original_ligand_hydrogens"]):
        raise ValueError("invalid replaced original ligand hydrogen inventory")
    for i, row in enumerate(ligand):
        original = source_mapping.get(i)
        if original is not None and (original["residue"] != lig_identity or
                                     original["element"].upper() != row["element"].upper()):
            raise ValueError("mapped ligand original source identity differs from selected SDF")
        row["original_source_ref"] = original
        if row["synthetic_residue_index"] != 0:
            raise ValueError("ligand synthetic residue identity changed")
    receptor_residues: dict[str, int] = {}
    for row in receptor:
        key = json.dumps(row["source_ref"]["residue"], sort_keys=True)
        receptor_residues.setdefault(key, len(receptor_residues))
        if row["synthetic_residue_index"] != receptor_residues[key]:
            raise ValueError("receptor synthetic residue identity changed")
    # The stored source payload cannot include its own handle. Derived AtomRefs
    # are expanded only in graph/catalog readers after its handle is known.
    source_rows = []
    for i, row in enumerate(receptor + ligand):
        original = row["source_ref"] if i < len(receptor) else row["original_source_ref"]
        residue = original["residue"] if original else lig_identity
        name = original["atom_name"] if original else row["atom_name"]
        source_rows.append({"local_site_index": i, "residue": residue, "atom_name": name,
                            "altloc": original["altloc"] if original else "", "element": row["element"],
                            "coordinate_A": row["coordinate_A"], "protein": i < len(receptor),
                            "viewer_source_index": i})
    generated_labels = _generated_label_asym(source_rows)
    manifest = {"schema": "chemical_preparation_manifest@1", "mode": req["mode"],
                "request": req, "source_handle": selected["source_handle"],
                "ligand_sdf_handle": req["ligand_sdf_handle"],
                "ligand_sdf_sha256": selected["ligand_sdf_sha256"],
                "model_number": model_number, "excluded_water_atoms": selected["excluded_water_atoms"],
                "receptor_local_sites": [r["source_ref"] for r in receptor],
                "ligand_sdf_indices": list(range(len(ligand))), "dependency": selected["dependency"],
                "attached_source_sites": attached_source_sites,
                "excluded_original_ligand_hydrogens": selected["excluded_original_ligand_hydrogens"],
                "terminal_extension_inventory": selected["terminal_extension_inventory"],
                "derived_coordinate_policy": DERIVED_COORDINATE_POLICY,
                "stereochemistry_policy": STEREOCHEMISTRY_POLICY,
                "stereochemistry_audit": worker_output["stereochemistry_audit"],
                "generated_label_asym_by_auth_chain": generated_labels,
                "histidine_states": worker_output["histidine_states"],
                "label_policy": "Retain supplied label chains; deterministic PVn for absent labels; preserve authoritative null in AtomRefs",
                "limitations": ["Native inferred receptor orders/charges are model dependent; supplied H state unverified."]}
    run_id = run.store.run_id
    manifest_handle = f"obj://{run_id}/chemical_preparation_manifest/" + object_sha(
        "chemical_preparation_manifest", "chemical_preparation_manifest@1", canonical_json(manifest))
    # Write a canonical exact-row mmCIF independent of source-file writer order.
    source_view_rows = [{"ref": {"structure_handle": "LOCAL", "residue": r["residue"],
                                 "atom_name": r["atom_name"], "altloc": r["altloc"],
                                 "element": r["element"], "site_index": r["local_site_index"]},
                         "coordinate_A": r["coordinate_A"], "protein": r["protein"],
                         "viewer_source_index": r["viewer_source_index"]} for r in source_rows]
    text = _cif_rows(source_view_rows[:len(receptor)], source_view_rows[len(receptor):],
                     model_number, generated_labels)
    source_payload = {"schema": "chemical_structure@1", "manifest_handle": manifest_handle,
                      "manifest_sha256": _sha(canonical_json(manifest)), "model_number": model_number,
                      "format": "mmcif", "text": text, "viewer_source_sha256": _sha(text.encode()),
                      "atoms": source_rows}
    # Parse/verify the exact to-be-served rows before publishing any object.
    cif_category = gemmi.cif.read_string(text).sole_block().get_mmcif_category("_atom_site.")
    if len(cif_category["id"]) != len(source_rows):
        raise ValueError("canonical chemical CIF atom count mismatch")
    for i, row in enumerate(source_rows):
        if not _cif_row_matches(cif_category, i, row, generated_labels, model_number):
            raise ValueError("canonical chemical CIF mapping mismatch")
    source_handle = f"obj://{run_id}/chemical_structure/" + object_sha(
        "chemical_structure", "chemical_structure@1", canonical_json(source_payload))
    # Refs in the source payload are deliberately local IDs. Readers expand to
    # the immutable source handle and verify each atom_site row.
    for i, row in enumerate(receptor + ligand):
        row["ref"] = {"structure_handle": source_handle, "residue": source_rows[i]["residue"],
                      "atom_name": source_rows[i]["atom_name"], "altloc": source_rows[i]["altloc"],
                      "element": source_rows[i]["element"], "site_index": i}
    graph = {"schema": "chemical_graph@1", "chemical_structure_handle": source_handle,
             "manifest_handle": manifest_handle, "dependency": selected["dependency"],
             "receptor_atoms": receptor, "receptor_bonds": worker_output["receptor_bonds"],
             "ligand_atoms": ligand, "ligand_bonds": worker_output["ligand_bonds"],
             "coordinate_policy": worker_output["coordinate_policy"]}
    # All native and prospective object payloads are now validated. Publication
    # is monotonic and acyclic; a failed native output leaves no new objects.
    committed_manifest = run.store.put("chemical_preparation_manifest", "chemical_preparation_manifest@1",
                                       manifest, produced_by=attempt_id,
                                       summary={"source_handle": selected["source_handle"],
                                                "model_number": model_number})
    committed_source = run.store.put("chemical_structure", "chemical_structure@1", source_payload,
                                     produced_by=attempt_id, summary={"model_number": model_number,
                                                                       "atom_count": len(source_rows)})
    if committed_manifest.handle != manifest_handle or committed_source.handle != source_handle:
        raise ValueError("content-addressed chemical publication mismatch")
    graph_handle = run.store.put("chemical_graph", "chemical_graph@1", graph,
                                 produced_by=attempt_id, summary={"chemical_structure_handle": source_handle,
                                                                   "receptor_atoms": len(receptor),
                                                                   "ligand_atoms": len(ligand)})
    return [manifest_handle, source_handle, graph_handle.handle]


def validated_result(store: Any, handle: str) -> dict[str, Any]:
    result = _json_object(store, handle, "chemical_interaction_set", "chemical_interaction_set@1")
    graph = validated_graph(store, result["graph_handle"])
    try:
        expected_criteria = _native_criteria(result["dependency_manifest"])
    except (KeyError, ValueError, TypeError) as exc:
        raise invalid("chemical method provenance invalid") from exc
    expected_limitations = ["Native chemistry-dependent assignments; not experimental validation, affinity or energy."]
    if (result["chemical_structure_handle"] != graph["chemical_structure_handle"] or
            result["manifest_handle"] != graph["manifest_handle"] or
            result["dependency_manifest"] != graph["dependency"] or
            result["method"] != "prolif_prepared_explicit_h@1" or
            result["criteria"] != expected_criteria or result["limitations"] != expected_limitations or
            type(result["rows"]) is not list or type(result["total"]) is not int or
            not 0 <= result["total"] <= 20_000 or type(result["null_result"]) is not bool or
            result["total"] != len(result["rows"]) or result["null_result"] != (not result["rows"])):
        raise invalid("chemical interaction result graph/count mismatch")
    maps = _row_maps(graph)
    for i, row in enumerate(result["rows"]):
        if row["row_id"] != f"r{i + 1:06d}" or row["category"] not in CATEGORIES:
            raise invalid("chemical interaction row identity/category invalid")
        _validate_row(graph, row, maps)
    return result


def _point(atom: dict) -> list[float]:
    value = atom["engine_coordinate_A"]
    if type(value) is not list or len(value) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError("nonfinite engine coordinate")
    return value


def _row_maps(graph: dict) -> tuple[dict[str, dict], dict[str, dict[int, list[int]]]]:
    refs: dict[str, dict] = {}
    local: dict[str, dict[int, list[int]]] = {"ligand": {}, "receptor": {}}
    for side in ("ligand", "receptor"):
        for i, atom in enumerate(graph[f"{side}_atoms"]):
            refs[json.dumps(atom["ref"], sort_keys=True)] = atom
            local[side].setdefault(atom["synthetic_residue_index"], []).append(i)
    return refs, local


def _validate_row(graph: dict, row: dict,
                  maps: tuple[dict[str, dict], dict[str, dict[int, list[int]]]] | None = None) -> None:
    refs, local_map = maps if maps is not None else _row_maps(graph)
    category = row["category"]
    if category not in CATEGORIES or row["backend_category"] != category:
        raise ValueError("unsupported interaction category")
    native = row["native_parent_indices"]
    local = row["native_within_residue_indices"]
    if set(native) != {"ligand", "protein"} or set(local) != {"ligand", "protein"}:
        raise ValueError("native index side keys invalid")
    for side, label in (("ligand", "ligand"), ("protein", "receptor")):
        atoms = graph[f"{label}_atoms"]
        parents, locals_ = native[side], local[side]
        if type(parents) is not list or type(locals_) is not list or len(parents) != len(locals_) or not parents:
            raise ValueError("native index cardinality invalid")
        for parent, within in zip(parents, locals_, strict=True):
            if (type(parent) is not int or type(within) is not int or
                    not 0 <= parent < len(atoms) or atoms[parent]["native_parent_index"] != parent):
                raise ValueError("native parent index invalid")
            resid = atoms[parent]["synthetic_residue_index"]
            local_atoms = local_map[label][resid]
            if not 0 <= within < len(local_atoms) or local_atoms[within] != parent:
                raise ValueError("native within-residue to parent index mismatch")
        expected_refs = [atoms[i]["ref"] for i in parents]
        if row["ligand_atoms" if side == "ligand" else "receptor_atoms"] != expected_refs:
            raise ValueError("interaction matched-atom refs mismatch")
    if category == "HBDonor":
        if len(native["ligand"]) != 2 or len(native["protein"]) != 1:
            raise ValueError("HBDonor role cardinality")
        expected_roles = {"donor": graph["ligand_atoms"][native["ligand"][0]]["ref"],
                          "hydrogen": graph["ligand_atoms"][native["ligand"][1]]["ref"],
                          "acceptor": graph["receptor_atoms"][native["protein"][0]]["ref"]}
    elif category == "HBAcceptor":
        if len(native["ligand"]) != 1 or len(native["protein"]) != 2:
            raise ValueError("HBAcceptor role cardinality")
        expected_roles = {"donor": graph["receptor_atoms"][native["protein"][0]]["ref"],
                          "hydrogen": graph["receptor_atoms"][native["protein"][1]]["ref"],
                          "acceptor": graph["ligand_atoms"][native["ligand"][0]]["ref"]}
    elif category == "Hydrophobic":
        expected_roles = {"ligand_site": graph["ligand_atoms"][native["ligand"][0]]["ref"],
                          "receptor_site": graph["receptor_atoms"][native["protein"][0]]["ref"]}
    elif category == "Cationic":
        expected_roles = {"cation_site": graph["ligand_atoms"][native["ligand"][0]]["ref"],
                          "anion_site": graph["receptor_atoms"][native["protein"][0]]["ref"]}
    else:
        expected_roles = {"cation_site": graph["receptor_atoms"][native["protein"][0]]["ref"],
                          "anion_site": graph["ligand_atoms"][native["ligand"][0]]["ref"]}
    if row["roles"] != expected_roles:
        raise ValueError("category role direction mismatch")
    expected_distance_roles = (["donor", "acceptor"] if category in {"HBDonor", "HBAcceptor"} else
                               ["ligand_site", "receptor_site"] if category == "Hydrophobic" else
                               ["cation_site", "anion_site"])
    if row["distance_roles"] != expected_distance_roles:
        raise ValueError("distance endpoint roles mismatch")
    roles = row["roles"]
    for role, ref in roles.items():
        atom = refs.get(json.dumps(ref, sort_keys=True))
        if atom is None or row["engine_role_coordinates_A"][role] != _point(atom) or row["role_coordinates_A"][role] != atom["coordinate_A"]:
            raise ValueError("interaction role is not exact graph atom")
    first, second = row["distance_roles"]
    distance = math.dist(row["engine_role_coordinates_A"][first], row["engine_role_coordinates_A"][second])
    if not math.isfinite(row["distance_A"]) or abs(distance - row["distance_A"]) > 1e-6:
        raise ValueError("interaction distance mismatch")
    metadata = row["native_metadata"]
    if (type(metadata) is not dict or metadata.get("distance") != row["distance_A"] or
            set(metadata) != ({"distance", "DHA_angle"} if category in {"HBDonor", "HBAcceptor"} else {"distance"})):
        raise ValueError("native distance metadata mismatch")
    cutoff = 3.5 if category in {"HBDonor", "HBAcceptor"} else 4.5
    if distance > cutoff + 1e-6:
        raise ValueError("native assignment exceeds fixed distance criterion")
    if row["category"] in {"HBDonor", "HBAcceptor"}:
        if row["roles"]["hydrogen"]["element"].upper() != "H":
            raise ValueError("hydrogen role is not an explicit H vertex")
        side = "ligand" if category == "HBDonor" else "receptor"
        donor_id, hydrogen_id = native["ligand" if side == "ligand" else "protein"]
        if tuple(sorted((donor_id, hydrogen_id))) not in {
                tuple(sorted((b["first"], b["second"]))) for b in graph[f"{side}_bonds"]}:
            raise ValueError("native donor-H role is not a supplied bonded edge")
        d, h, a = (row["engine_role_coordinates_A"][x] for x in ("donor", "hydrogen", "acceptor"))
        u, v = [d[i] - h[i] for i in range(3)], [a[i] - h[i] for i in range(3)]
        den = math.sqrt(sum(x*x for x in u) * sum(x*x for x in v))
        if den <= 0:
            raise ValueError("zero H-bond angle vector")
        angle = math.degrees(math.acos(max(-1, min(1, sum(x*y for x, y in zip(u, v)) / den))))
        if (row["DHA_angle_deg"] != metadata["DHA_angle"] or
                abs(angle - row["DHA_angle_deg"]) > 1e-6 or not 130 - 1e-6 <= angle <= 180 + 1e-6):
            raise ValueError("interaction angle mismatch")
    elif row["DHA_angle_deg"] is not None:
        raise ValueError("non-H interaction cannot have DHA angle")


def publish_detect(run: Any, job: dict[str, Any], attempt_id: str,
                   worker_output: dict[str, Any]) -> list[str]:
    selected = job["selected"]
    _check_worker_dependency(selected, worker_output)
    if worker_output.get("schema") != "chemical_detect_worker_output@1":
        raise ValueError("detection worker schema mismatch")
    graph_handle = selected["request"]["graph_handle"]
    graph = validated_graph(run.store, graph_handle)
    native = worker_output["native_rows"]
    if (type(native) is not list or len(native) > 20_000 or
            worker_output["native_total"] != len(native) or worker_output["null_result"] != (not native)):
        raise ValueError("invalid native interaction count")
    rows = []
    maps = _row_maps(graph)
    for occurrence in native:
        if type(occurrence) is not dict:
            raise ValueError("invalid native interaction occurrence")
        category = occurrence.get("category")
        if category not in CATEGORIES:
            raise ValueError("unsupported native interaction category")
        ids = occurrence.get("parent_indices")
        locals_ = occurrence.get("within_residue_indices")
        if (type(ids) is not dict or type(locals_) is not dict or
                set(ids) != {"ligand", "protein"} or set(locals_) != {"ligand", "protein"}):
            raise ValueError("native index side keys invalid")
        for side, label in (("ligand", "ligand"), ("protein", "receptor")):
            atoms = graph[f"{label}_atoms"]
            if (type(ids[side]) is not list or type(locals_[side]) is not list or not ids[side] or
                    len(ids[side]) != len(locals_[side]) or
                    any(type(i) is not int or not 0 <= i < len(atoms) for i in ids[side])):
                raise ValueError("native parent index out of range")
        # Role cardinality is fixed before any positional role is read. Charged and hydrophobic
        # matches may carry additional audit atoms; their endpoint is the first matched index.
        cardinality = {"HBDonor": (2, 1), "HBAcceptor": (1, 2)}.get(category)
        if (cardinality is not None and
                (len(ids["ligand"]), len(ids["protein"])) != cardinality):
            raise ValueError(f"{category} native role cardinality")
        la = [graph["ligand_atoms"][i] for i in ids["ligand"]]
        ra = [graph["receptor_atoms"][i] for i in ids["protein"]]
        if category == "HBDonor":
            roles = {"donor": la[0], "hydrogen": la[1], "acceptor": ra[0]}
        elif category == "HBAcceptor":
            roles = {"donor": ra[0], "hydrogen": ra[1], "acceptor": la[0]}
        elif category == "Hydrophobic":
            roles = {"ligand_site": la[0], "receptor_site": ra[0]}
        elif category == "Cationic":
            roles = {"cation_site": la[0], "anion_site": ra[0]}
        else:
            roles = {"cation_site": ra[0], "anion_site": la[0]}
        distance_roles = (["donor", "acceptor"] if category in {"HBDonor", "HBAcceptor"} else
                          ["ligand_site", "receptor_site"] if category == "Hydrophobic" else
                          ["cation_site", "anion_site"])
        metadata = occurrence["native_metadata"]
        if type(metadata) is not dict or set(metadata) != ({"distance", "DHA_angle"} if category in {"HBDonor", "HBAcceptor"} else {"distance"}):
            raise ValueError("unexpected native metadata")
        row = {"row_id": f"r{len(rows) + 1:06d}", "category": category, "backend_category": category,
               "ligand_atoms": [x["ref"] for x in la], "receptor_atoms": [x["ref"] for x in ra],
               "roles": {name: x["ref"] for name, x in roles.items()},
               "role_coordinates_A": {name: x["coordinate_A"] for name, x in roles.items()},
               "engine_role_coordinates_A": {name: x["engine_coordinate_A"] for name, x in roles.items()},
               "native_parent_indices": ids, "native_within_residue_indices": locals_,
               "distance_A": metadata["distance"], "distance_roles": distance_roles,
               "DHA_angle_deg": metadata.get("DHA_angle"), "native_metadata": metadata}
        _validate_row(graph, row, maps)
        rows.append(row)
    result = {"schema": "chemical_interaction_set@1", "chemical_structure_handle": graph["chemical_structure_handle"],
              "graph_handle": graph_handle, "manifest_handle": graph["manifest_handle"],
              "method": "prolif_prepared_explicit_h@1", "dependency_manifest": selected["dependency"],
              "criteria": _native_criteria(selected["dependency"]),
              "rows": rows, "total": len(rows), "null_result": not rows,
              "limitations": ["Native chemistry-dependent assignments; not experimental validation, affinity or energy."]}
    output = run.store.put("chemical_interaction_set", "chemical_interaction_set@1", result,
                           produced_by=attempt_id, null_result=not rows,
                           summary={"graph_handle": graph_handle, "total": len(rows)})
    return [output.handle]
