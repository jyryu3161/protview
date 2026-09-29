"""M12 pocket detector input projection (server side, no fpocket execution).

Real inputs: public_1hsg.cif, public_1ubq.cif (OpenMM-minimized through the real
engine) and the licensed ProLIF fixture (chemical source through the pinned
native worker). Inputs built by ``_pdb``/``_cif`` below are SYNTHETIC boundary
inputs, not experimental structures; they still go through the product
load_structure → prepare_structure path. The derived small fixture is labeled in
its file name and provenance record and is not experimental evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import gemmi
import numpy as np
import pytest

from mw.core.errors import FailureClass, ToolFailure
from mw.pocket_input import (
    CHAIN_ALPHABET,
    MAX_INPUT_BYTES,
    STANDARD_RESIDUES,
    TRANSPORT_RESNAMES,
    preflight,
    project,
)
from mw.tools.comparison import atom_rows
from mw.workspace import new_run

FIXTURES = Path(__file__).parent / "fixtures"
HSG_SHA256 = "d2ba73b5c4be05c45275571bbb4dd042347927f91c6c05038c0df5d1ce23c268"
DERIVED = FIXTURES / "derived_1hsg_first10_fixture.cif"
DERIVED_PROVENANCE = FIXTURES / "derived_1hsg_first10_fixture.provenance.json"
PREPARE = {"altloc": "highest_occupancy", "waters": "keep_all", "hydrogens": "keep",
           "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}
# Idealized alanine-like heavy-atom offsets (synthetic geometry, not observed).
ALA = [("N", "N", (0.0, 0.0, 0.0)), ("CA", "C", (1.458, 0.0, 0.0)), ("C", "C", (2.009, 1.42, 0.0)),
       ("O", "O", (1.251, 2.39, 0.0)), ("CB", "C", (1.988, -0.773, -1.199))]


# ----------------------------------------------------------------- helpers
def _load(tmp_path: Path, raw: bytes, fmt: str, model_index: int = 0, run_id: str = "run_pockets",
          prepare: dict | None = None):
    run = new_run(tmp_path / run_id, dry_run=False, run_id=run_id)
    source = run.call("load_structure", {"source": f"input.{fmt}", "model_index": model_index},
                      source_bytes=raw, source_format=fmt)
    prepared = run.call("prepare_structure", {"structure": source.handle, **(prepare or PREPARE)})
    return run, source.handle, prepared.handle


def _pdb_line(serial: int, name: str, resname: str, chain: str, resseq: int, xyz, element: str,
              icode: str = " ", altloc: str = " ", occ: float = 1.0, b: float = 10.0, record: str = "ATOM") -> str:
    field = f" {name:<3}" if len(name) < 4 and len(element) == 1 else f"{name:<4}"
    return (f"{record:<6}{serial:5d} {field}{altloc}{resname:>3} {chain}{resseq:4d}{icode}   "
            f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{occ:6.2f}{b:6.2f}          {element:>2}  ")


def _pdb(residues: list[dict]) -> bytes:
    """SYNTHETIC PDB. Each residue: chain, seq, name, [icode], atoms [(name, element, xyz, extra)]."""
    lines, serial = [], 1
    for res in residues:
        for atom in res["atoms"]:
            name, element, xyz = atom[:3]
            extra = atom[3] if len(atom) > 3 else {}
            lines.append(_pdb_line(serial, name, res["name"], res["chain"], res["seq"], xyz, element,
                                   icode=res.get("icode", " "), record=res.get("record", "ATOM"), **extra))
            serial += 1
    return ("\n".join(lines) + "\nEND\n").encode()


def _ala(chain: str, seq: int, offset, name: str = "ALA", icode: str = " ") -> dict:
    return {"chain": chain, "seq": seq, "name": name, "icode": icode,
            "atoms": [(n, e, tuple(a + b for a, b in zip(xyz, offset))) for n, e, xyz in ALA]}


CIF_COLUMNS = ["group_PDB", "id", "type_symbol", "label_atom_id", "label_alt_id", "label_comp_id",
               "label_asym_id", "label_entity_id", "label_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y",
               "Cartn_z", "occupancy", "B_iso_or_equiv", "auth_seq_id", "auth_comp_id", "auth_asym_id",
               "auth_atom_id", "pdbx_PDB_model_num"]


def _cif(rows: list[dict]) -> bytes:
    """SYNTHETIC mmCIF; row keys: chain, label_chain, seq, label_seq, name, atom, element, xyz, model..."""
    out = ["data_synthetic", "#", "loop_", *(f"_atom_site.{c}" for c in CIF_COLUMNS)]
    for i, r in enumerate(rows, start=1):
        out.append(" ".join([
            r.get("group", "ATOM"), str(i), r["element"], r["atom"], r.get("alt", "."), r["name"],
            r.get("label_chain", r["chain"]), "1", str(r.get("label_seq", r["seq"])), r.get("icode", "?"),
            *(repr(float(v)) for v in r["xyz"]), str(r.get("occ", 1.0)), str(r.get("b", 10.0)), str(r["seq"]),
            r["name"], r["chain"], r["atom"], str(r.get("model", 1))]))
    out.append("#")
    return ("\n".join(out) + "\n").encode()


def _cif_ala(chain: str, seq: int, offset, **extra) -> list[dict]:
    return [{"chain": chain, "seq": seq, "name": "ALA", "atom": n, "element": e,
             "xyz": [a + b for a, b in zip(xyz, offset)], **extra} for n, e, xyz in ALA]


def _reject(store, handle, chains=None, cls=FailureClass.input_invalid, code=None) -> ToolFailure:
    with pytest.raises(ToolFailure) as caught:
        project(store, handle, chains)
    assert caught.value.cls == cls
    if code:
        assert caught.value.detail["reason_code"] == code
    summary = preflight(store, handle, chains)
    assert summary["ready"] is False and summary["reject"]["failure_class"] == cls.value
    assert summary["reject"]["reason_code"] == caught.value.detail.get("reason_code", "source_invalid")
    return caught.value


def _reread(pdb: bytes) -> list[dict]:
    """Independent fixed-column reader (not the module's parser)."""
    out = []
    for line in pdb.decode("ascii").splitlines():
        if line[:6] == "ATOM  ":
            out.append({"serial": int(line[6:11]), "name": line[12:16].strip(), "resname": line[17:20],
                        "chain": line[21], "resseq": int(line[22:26]),
                        "xyz": [float(line[30:38]), float(line[38:46]), float(line[46:54])],
                        "element": line[76:78].strip()})
    return out


def _assert_bijection(store, handle: str, result: dict) -> None:
    """Every transport atom maps to exactly one catalog site with the same identity and coordinates."""
    manifest = result["manifest"]
    assert hashlib.sha256(result["pdb_bytes"]).hexdigest() == result["pdb_sha256"] == manifest["transport_pdb_sha256"]
    records = _reread(result["pdb_bytes"])
    assert len(records) == len(manifest["atoms"]) == manifest["counts"]["heavy_atoms"]
    sites = [atom["ref"]["site_index"] for atom in manifest["atoms"]]
    assert len(set(sites)) == len(sites)
    keys = set()
    for atom, record in zip(manifest["atoms"], records, strict=True):
        assert atom["ref"]["structure_handle"] == handle
        assert (record["serial"], record["chain"], record["resseq"], record["name"], record["element"]) == (
            atom["serial"], atom["synthetic_chain"], atom["synthetic_resseq"], atom["atom_name"], atom["element"])
        assert record["xyz"] == atom["projected_coordinate_A"]
        assert all(abs(a - b) <= 0.0005 + 1e-9 for a, b in zip(record["xyz"], atom["original_coordinate_A"]))
        assert atom["element"] not in {"H", "D"}
        resname = atom["ref"]["residue"]["resname"]
        assert record["resname"] == TRANSPORT_RESNAMES.get(resname, resname)
        assert resname in STANDARD_RESIDUES | set(TRANSPORT_RESNAMES)
        keys.add((record["chain"], record["resseq"], record["name"]))
    assert len(keys) == len(records)  # synthetic chain + resseq + name is unique
    residue_ids = {}
    for atom in manifest["atoms"]:
        key = json.dumps(atom["ref"]["residue"], sort_keys=True)
        residue_ids.setdefault((atom["synthetic_chain"], atom["synthetic_resseq"]), key)
        assert residue_ids[(atom["synthetic_chain"], atom["synthetic_resseq"])] == key
    assert len(set(residue_ids.values())) == len(residue_ids)
    assert {r for _, r in residue_ids} == set(range(1, len(residue_ids) + 1))
    assert all(chain in CHAIN_ALPHABET for chain, _ in residue_ids)
    json.dumps(manifest, allow_nan=False)


def _catalog_check(store, handle: str, result: dict) -> None:
    rows = atom_rows(store, handle)["rows"]
    for atom in result["manifest"]["atoms"]:
        row = rows[atom["ref"]["site_index"]]
        assert row["ref"] == atom["ref"] and row["coordinate_A"] == atom["original_coordinate_A"]


def derived_first10_bytes() -> bytes:
    """Deterministic derived fixture rule (see the provenance record next to the fixture)."""
    raw = (FIXTURES / "public_1hsg.cif").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HSG_SHA256
    lines = raw.decode("utf-8").splitlines(keepends=True)
    start = lines.index("_atom_site.group_PDB \n")
    assert lines[start - 1] == "loop_\n"
    end = start
    while lines[end].startswith("_atom_site."):
        end += 1
    header = lines[start:end]
    names = [line.split()[0].removeprefix("_atom_site.") for line in header]
    kept, residues = [], []
    for line in lines[end:]:
        if line.startswith("#"):
            break
        assert "'" not in line and '"' not in line
        row = dict(zip(names, line.split(), strict=True))
        key = tuple(row[k] for k in ("pdbx_PDB_model_num", "auth_asym_id", "auth_seq_id", "pdbx_PDB_ins_code",
                                     "label_asym_id", "label_seq_id", "auth_comp_id"))
        if row["group_PDB"] != "ATOM" or row["auth_comp_id"] not in STANDARD_RESIDUES:
            continue
        if key not in residues:
            if len(residues) == 10:
                continue
            residues.append(key)
        kept.append(line)
    return "".join(["data_1HSG_DERIVED_FIRST10\n", "#\n", "loop_\n", *header, *kept, "#\n"]).encode()


# ------------------------------------------------------------ real sources
def test_public_1hsg_projection_sanity_against_raw_file(tmp_path: Path) -> None:
    raw = (FIXTURES / "public_1hsg.cif").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HSG_SHA256
    run, _, prepared = _load(tmp_path, raw, "cif")
    result = project(run.store, prepared)
    manifest = result["manifest"]
    # Independent oracle: count atom_site rows of the raw file by category.
    block = gemmi.cif.read_string(raw.decode()).sole_block().get_mmcif_category("_atom_site.")
    comp, element = block["auth_comp_id"], block["type_symbol"]
    protein = sum(c in STANDARD_RESIDUES and e not in {"H", "D"} for c, e in zip(comp, element, strict=True))
    water = sum(c == "HOH" for c in comp)
    ligand = sum(c not in STANDARD_RESIDUES and c != "HOH" for c in comp)
    assert manifest["counts"]["heavy_atoms"] == protein
    assert manifest["excluded_counts"] == {"water": water, "ligand": ligand, "ion": 0, "hydrogen": 0,
                                           "unselected_chain": 0}
    assert manifest["selected_chains"] == sorted(set(block["auth_asym_id"]))
    assert manifest["source_kind"] == "prepared_structure" and manifest["model_number"] == 1
    assert manifest["preparation_handle"] == run.store.load(prepared)["manifest"]
    assert manifest["resname_mapping"] == []
    assert len(manifest["excluded_sites"]) == water + ligand
    assert manifest["quantization"]["max_axis_discrepancy_A"] <= 0.0005
    _assert_bijection(run.store, prepared, result)
    _catalog_check(run.store, prepared, result)
    # Independent gemmi reread of the transport file gives the same heavy-atom geometry.
    st = gemmi.read_pdb_string(result["pdb_bytes"].decode())
    reread = np.array([[a.pos.x, a.pos.y, a.pos.z] for ch in st[0] for r in ch for a in r])
    original = np.array([a["original_coordinate_A"] for a in manifest["atoms"]])
    assert np.abs(reread - original).max() <= 0.0005 + 1e-9
    # Explicit selection: chains [] is the same projection as naming every protein chain.
    explicit = project(run.store, prepared, ["B", "A", "B"])
    assert explicit["manifest"] == manifest and explicit["pdb_bytes"] == result["pdb_bytes"]
    only_b = project(run.store, prepared, ["B"])["manifest"]
    assert only_b["selected_chains"] == ["B"] and only_b["chain_map"] == [{"chain_auth": "B",
                                                                           "synthetic_chain": "A"}]
    assert only_b["excluded_counts"]["unselected_chain"] == sum(c == "A" for c in block["auth_asym_id"])
    assert {a["ref"]["residue"]["chain_auth"] for a in only_b["atoms"]} == {"B"}
    summary = preflight(run.store, prepared, ["B"])
    assert summary["ready"] and summary["projected_atom_count"] == only_b["counts"]["heavy_atoms"]
    assert [c["chain_auth"] for c in summary["available_chains"]] == ["A", "B"]


def test_raw_structure_requires_preparation_and_foreign_or_wrong_handles(tmp_path: Path) -> None:
    run, source, prepared = _load(tmp_path, (FIXTURES / "public_1hsg.cif").read_bytes(), "cif")
    failure = _reject(run.store, source, cls=FailureClass.precondition, code="raw_structure_requires_preparation")
    assert "prepare" in failure.message
    manifest = run.store.load(prepared)["manifest"]
    _reject(run.store, manifest, code="unsupported_source_kind")
    _other, _, foreign = _load(tmp_path, (FIXTURES / "public_1hsg.cif").read_bytes(), "cif", run_id="run_other")
    _reject(run.store, foreign, code="unknown_source")
    _reject(run.store, prepared, chains=["Z"], code="unknown_chain")
    _reject(run.store, prepared, chains="A", code="invalid_chain_selection")


def test_derived_first10_fixture_is_regenerated_and_projects_88_heavy_atoms(tmp_path: Path) -> None:
    generated = derived_first10_bytes()
    assert DERIVED.read_bytes() == generated
    provenance = json.loads(DERIVED_PROVENANCE.read_text())
    assert provenance["sha256"] == hashlib.sha256(generated).hexdigest()
    assert provenance["source_sha256"] == HSG_SHA256
    assert "derived" in provenance["label"] and "not experimental evidence" in provenance["label"]
    run, _, prepared = _load(tmp_path, generated, "cif")
    result = project(run.store, prepared)
    manifest = result["manifest"]
    assert manifest["counts"] == {**manifest["counts"], "heavy_atoms": 88, "residues": 10, "chains": 1}
    assert sum(manifest["excluded_counts"].values()) == 0
    _assert_bijection(run.store, prepared, result)
    # The fixture residues are exactly the first 10 residues of the full 1hsg projection order.
    full_run, _, full = _load(tmp_path, (FIXTURES / "public_1hsg.cif").read_bytes(), "cif", run_id="run_full")
    full_atoms = [a for a in project(full_run.store, full)["manifest"]["atoms"] if a["synthetic_resseq"] <= 10]
    strip = lambda a: (a["ref"]["residue"], a["atom_name"], a["element"], a["original_coordinate_A"])
    assert [strip(a) for a in full_atoms] == [strip(a) for a in manifest["atoms"]]


def test_openmm_minimized_source_projection(tmp_path: Path, monkeypatch) -> None:
    from mw.jobs.openmm_worker import run as engine_run
    from mw.jobs.openmm_worker import write_preparation
    from mw.jobs.queue import JobQueue
    from mw.openmm_reports import validated_minimized_structure

    run, _, prepared = _load(tmp_path, (FIXTURES / "public_1ubq.cif").read_bytes(), "cif",
                             prepare={**PREPARE, "hydrogens": "strip"})
    queue = JobQueue(run)
    job = queue.submit("openmm_protein_minimize", {"structure": prepared, "selection_policy": "protein_only",
                                                   "hydrogen_policy": "rebuild_pH7"})
    run.approve("expensive_first_call")

    def supervise(record, attempt_id, nonce, directory, deadline, dispatch):
        output = engine_run(json.loads((directory / "structure.json").read_bytes()),
                            on_prepared=lambda item: write_preparation(item, directory))
        result = json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        (directory / "result.json").write_bytes(result)
        return {"kind": "RESULT", "nonce": nonce, "job_id": record["job_id"], "attempt_id": attempt_id,
                "reason": "completed", "returncode": 0, "unexpected_members": False, "clean": True,
                "direct_child_reaped": True,
                "payload": {"output_sha256": hashlib.sha256(result).hexdigest(), "output_bytes": len(result)}}, None

    monkeypatch.setattr(queue, "_supervise", supervise)
    done = queue.start(job["job_id"])
    assert done["status"] == "done"
    minimized = run.store.load(done["output_handles"][0])["minimized_structure"]
    validated_minimized_structure(run, minimized)
    result = project(run.store, minimized)
    manifest = result["manifest"]
    assert manifest["source_kind"] == "openmm_minimized_structure"
    assert manifest["preparation_handle"] == run.store.load(minimized)["manifest"]
    assert manifest["excluded_counts"]["hydrogen"] > 0
    assert 0 < manifest["quantization"]["max_axis_discrepancy_A"] <= 0.0005
    _assert_bijection(run.store, minimized, result)
    _catalog_check(run.store, minimized, result)
    # The minimized source is distinct from its prepared input: different handles and coordinates.
    before = project(run.store, prepared)["manifest"]
    assert before["source_handle"] != manifest["source_handle"]
    assert before["transport_pdb_sha256"] != manifest["transport_pdb_sha256"]


def test_chemical_structure_source_maps_charmm_histidines(tmp_path: Path) -> None:
    from test_chemical_interactions import _create, _run_worker

    from mw.chemical_bundle import atom_catalog, prepare_selected, publish_prepare
    from mw.core.handles import ObjectStore

    store = ObjectStore(tmp_path / "chem", "run_pockets_chem")
    selected = prepare_selected(store, _create(store))
    prepared = _run_worker(tmp_path, "prolif_prepare_v1", selected)
    _, source, _ = publish_prepare(SimpleNamespace(store=store), {"selected": selected}, "attempt_pocket", prepared)
    result = project(store, source)
    manifest = result["manifest"]
    assert manifest["source_kind"] == "chemical_structure"
    assert manifest["preparation_handle"] == store.load(source)["manifest_handle"]
    catalog = atom_catalog(store, source, 0, 1000)
    total = catalog["total"]
    rows = []
    for offset in range(0, total, 1000):
        rows.extend(atom_catalog(store, source, offset, 1000)["rows"])
    for atom in manifest["atoms"]:
        row = rows[atom["ref"]["site_index"]]
        assert row["ref"] == atom["ref"] and row["coordinate_A"] == atom["original_coordinate_A"]
    # Independent inventory from the catalog rows.
    residues = {json.dumps(r["ref"]["residue"], sort_keys=True): r["ref"]["residue"] for r in rows}
    aliases = [r for r in residues.values() if r["resname"] in TRANSPORT_RESNAMES]
    assert aliases and {r["resname"] for r in aliases} <= {"HSD", "HSE"}
    assert sorted(json.dumps(m["residue"], sort_keys=True) for m in manifest["resname_mapping"]) == sorted(
        json.dumps(r, sort_keys=True) for r in aliases)
    assert all(m["transport_resname"] == "HIS" and m["original_resname"] == m["residue"]["resname"]
               for m in manifest["resname_mapping"])
    ligand_sites = sum(not r["protein"] for r in rows)
    hydrogens = sum(r["protein"] and r["ref"]["element"] in {"H", "D"} for r in rows)
    ligand_chains = {r["ref"]["residue"]["chain_auth"] for r in rows if not r["protein"]}
    assert ligand_chains.isdisjoint(manifest["selected_chains"])  # ligand-only chain is not a default protein chain
    assert manifest["excluded_counts"] == {"water": 0, "ligand": 0, "ion": 0, "hydrogen": hydrogens,
                                           "unselected_chain": ligand_sites}
    assert manifest["counts"]["heavy_atoms"] == total - ligand_sites - hydrogens
    _assert_bijection(store, source, result)
    his = [a for a in manifest["atoms"] if a["ref"]["residue"]["resname"] in {"HSD", "HSE"}]
    assert his and all(a["transport_resname"] == "HIS" for a in his)


# --------------------------------------------------- synthetic boundaries
def test_residue_name_aliases_map_exactly_and_modified_residues_reject(tmp_path: Path) -> None:
    # SYNTHETIC alanine-like geometry; only the residue names vary (atom names and elements untouched).
    mapped = {"HID": "HIS", "HIE": "HIS", "HIP": "HIS", "HSD": "HIS", "HSE": "HIS", "HSP": "HIS",
              "CYX": "CYS", "ASH": "ASP", "GLH": "GLU", "LYN": "LYS"}
    assert TRANSPORT_RESNAMES == mapped
    names = [*mapped, "HIS", "CYS"]
    residues = [_ala("A", i + 1, (4.0 * i, 0.3 * i, 0.1 * i * i), name=n) for i, n in enumerate(names)]
    run, _, prepared = _load(tmp_path, _pdb(residues), "pdb")
    result = project(run.store, prepared)
    manifest = result["manifest"]
    _assert_bijection(run.store, prepared, result)
    assert [(m["original_resname"], m["transport_resname"], m["residue"]["resname"])
            for m in manifest["resname_mapping"]] == [(n, mapped[n], n) for n in mapped]
    assert [a["transport_resname"] for a in manifest["atoms"][::5]] == [mapped.get(n, n) for n in names]
    assert [a["ref"]["residue"]["resname"] for a in manifest["atoms"][::5]] == names
    assert [(r["resname"], a["atom_name"], a["element"]) for r, a in zip(
        (a["ref"]["residue"] for a in manifest["atoms"]), manifest["atoms"], strict=True)][:5] == [
        ("HID", name, element) for name, element, _ in ALA]
    assert preflight(run.store, prepared)["resname_mapping"] == manifest["resname_mapping"]
    for modified, record in (("MSE", "HETATM"), ("TPO", "HETATM"), ("CYM", "ATOM"), ("HYP", "HETATM")):
        bad = residues[:3] + [{**_ala("A", 50, (30.0, 5.0, 2.0), name=modified), "record": record}]
        other, _, handle = _load(tmp_path, _pdb(bad), "pdb", run_id=f"run_{modified.lower()}")
        failure = _reject(other.store, handle, code="modified_residue_unsupported")
        assert failure.detail["residues"] == [{"model_number": 1, "chain_auth": "A", "seq_auth": 50, "icode": "",
                                               "chain_label": None, "seq_label": None, "resname": modified}]
        # A modified residue in an unselected chain is counted, not rejected.
        moved = residues[:3] + [{**_ala("B", 50, (30.0, 5.0, 2.0), name=modified), "record": record}]
        other, _, handle = _load(tmp_path, _pdb(moved), "pdb", run_id=f"run_{modified.lower()}_b")
        _reject(other.store, handle, code="modified_residue_unsupported")
        kept = project(other.store, handle, ["A"])["manifest"]
        assert kept["excluded_counts"]["unselected_chain"] == 5
    # A non-polymer (HETATM) ligand whose atoms happen to be named N/CA/C stays a ligand.
    ligand = {**_ala("A", 60, (30.0, 5.0, 2.0), name="LG1"), "record": "HETATM"}
    other, _, handle = _load(tmp_path, _pdb(residues[:3] + [ligand]), "pdb", run_id="run_ligand_names")
    assert project(other.store, handle)["manifest"]["excluded_counts"]["ligand"] == 5


def test_blank_chain_id_is_selectable_and_bijective(tmp_path: Path) -> None:
    run, _, handle = _load(tmp_path, _pdb([_ala(" ", 1, (0, 0, 0)), _ala(" ", 2, (4, 1, 0.5))]), "pdb")
    chains = [row["ref"]["residue"]["chain_auth"] for row in atom_rows(run.store, handle)["rows"]]
    blank = chains[0]
    assert set(chains) == {blank} and blank.strip() == ""
    result = project(run.store, handle, [blank])
    assert result["manifest"]["chain_map"] == [{"chain_auth": blank, "synthetic_chain": "A"}]
    assert project(run.store, handle)["manifest"] == result["manifest"]
    _assert_bijection(run.store, handle, result)


def test_null_labels_insertion_codes_and_hydrogen_ion_water_counts(tmp_path: Path) -> None:
    residues = [_ala("A", 52, (0, 0, 0)), _ala("A", 52, (4, 1, 0), icode="A"), _ala("A", 52, (8, 0, 1), icode="B"),
                {"chain": "A", "seq": 53, "name": "GLY", "atoms": [
                    ("N", "N", (12, 0, 0)), ("CA", "C", (13.4, 0.2, 0.1)), ("C", "C", (14.0, 1.5, 0.3)),
                    ("O", "O", (13.2, 2.4, 0.2)), ("H", "H", (11.5, -0.8, 0.0)), ("HA2", "D", (13.8, -0.5, 0.8))]},
                {"chain": "A", "seq": 301, "name": "ZN", "record": "HETATM", "atoms": [("ZN", "ZN", (20, 20, 20))]},
                {"chain": "A", "seq": 401, "name": "HOH", "record": "HETATM",
                 "atoms": [("O", "O", (25, 25, 25)), ("H1", "H", (25.9, 25, 25))]},
                {"chain": "A", "seq": 501, "name": "LIG", "record": "HETATM",
                 "atoms": [("C1", "C", (30, 30, 30)), ("C2", "C", (31.5, 30, 30)), ("H1", "H", (29, 30, 30))]}]
    run, _, prepared = _load(tmp_path, _pdb(residues), "pdb")
    result = project(run.store, prepared)
    manifest = result["manifest"]
    assert manifest["excluded_counts"] == {"water": 2, "ligand": 3, "ion": 1, "hydrogen": 2, "unselected_chain": 0}
    idents = [(r["residue"]["seq_auth"], r["residue"]["icode"], r["synthetic_resseq"]) for r in manifest["residues"]]
    assert idents == [(52, "", 1), (52, "A", 2), (52, "B", 3), (53, "", 4)]
    assert all(r["residue"]["chain_label"] is None and r["residue"]["seq_label"] is None
               for r in manifest["residues"])
    assert all(a["ref"]["residue"]["chain_label"] is None for a in manifest["atoms"])
    categories = {e["site_index"]: e["category"] for e in manifest["excluded_sites"]}
    rows = atom_rows(run.store, prepared)["rows"]
    assert {rows[i]["ref"]["atom_name"] for i, c in categories.items() if c == "hydrogen"} == {"H", "HA2"}
    assert set(categories) | {a["ref"]["site_index"] for a in manifest["atoms"]} == set(range(len(rows)))
    _assert_bijection(run.store, prepared, result)


def test_multichar_chains_labels_and_quantization_roundtrip(tmp_path: Path) -> None:
    rows = []
    for k, (chain, label) in enumerate((("AB", "X"), ("C1", "Y"), ("long", "Z"))):
        for seq in (1, 2):
            rows += _cif_ala(chain, seq, (4.00031 * seq + 0.123456, 7.77777 * k, 0.5 * seq * k - 0.000449),
                             label_chain=label, label_seq=seq + 10)
    run, _, prepared = _load(tmp_path, _cif(rows), "cif")
    result = project(run.store, prepared, ["long", "AB", "C1"])
    manifest = result["manifest"]
    assert manifest["selected_chains"] == ["AB", "C1", "long"]
    assert manifest["chain_map"] == [{"chain_auth": "AB", "synthetic_chain": "A"},
                                     {"chain_auth": "C1", "synthetic_chain": "B"},
                                     {"chain_auth": "long", "synthetic_chain": "C"}]
    labels = {(r["residue"]["chain_auth"], r["residue"]["chain_label"], r["residue"]["seq_label"])
              for r in manifest["residues"]}
    assert ("AB", "X", 11) in labels and ("long", "Z", 12) in labels
    worst = manifest["quantization"]["max_axis_discrepancy_A"]
    independent = max(abs(round(v, 3) - v) for a in manifest["atoms"] for v in a["original_coordinate_A"])
    assert 0 < worst <= 0.0005 and worst == pytest.approx(independent, abs=1e-9)
    _assert_bijection(run.store, prepared, result)


def test_reordered_sites_keep_the_bijection(tmp_path: Path) -> None:
    residues = [_ala("A", 1, (0, 0, 0)), _ala("A", 2, (4, 1, 0.5)), _ala("B", 1, (1, 6, 2))]
    shuffled = [{**r, "atoms": list(reversed(r["atoms"]))} for r in reversed(residues)]
    run_a, _, first = _load(tmp_path, _pdb(residues), "pdb", run_id="run_order_a")
    run_b, _, second = _load(tmp_path, _pdb(shuffled), "pdb", run_id="run_order_b")
    a, b = project(run_a.store, first), project(run_b.store, second)
    for result, store, handle in ((a, run_a.store, first), (b, run_b.store, second)):
        _assert_bijection(store, handle, result)
        _catalog_check(store, handle, result)
    key = lambda atom: (json.dumps(atom["ref"]["residue"], sort_keys=True), atom["atom_name"])
    by_a = {key(x): x["original_coordinate_A"] for x in a["manifest"]["atoms"]}
    by_b = {key(x): x["original_coordinate_A"] for x in b["manifest"]["atoms"]}
    assert by_a == by_b
    assert [x["ref"]["site_index"] for x in b["manifest"]["atoms"]] == list(range(15))
    assert b["manifest"]["atoms"][0]["ref"]["residue"]["chain_auth"] == "B"
    assert b["manifest"]["atoms"][0]["atom_name"] == "CB"


def test_altloc_and_non_first_model_are_resolved_by_preparation(tmp_path: Path) -> None:
    model = []
    for n, e, xyz in ALA:
        if n == "CB":
            model.append({"chain": "A", "seq": 1, "name": "ALA", "atom": n, "element": e, "alt": "A",
                          "occ": 0.3, "xyz": list(xyz)})
            model.append({"chain": "A", "seq": 1, "name": "ALA", "atom": n, "element": e, "alt": "B",
                          "occ": 0.7, "xyz": [xyz[0] + 0.5, xyz[1], xyz[2]]})
        else:
            model.append({"chain": "A", "seq": 1, "name": "ALA", "atom": n, "element": e, "xyz": list(xyz)})
    model += _cif_ala("A", 2, (4, 1, 0.5))
    rows = [{**r, "model": 1} for r in model] + [{**r, "model": 7, "xyz": [v + 10 for v in r["xyz"]]} for r in model]
    run, source, prepared = _load(tmp_path, _cif(rows), "cif", model_index=1)
    _reject(run.store, source, cls=FailureClass.precondition, code="raw_structure_requires_preparation")
    manifest = project(run.store, prepared)["manifest"]
    assert manifest["model_number"] == 7
    assert {a["ref"]["residue"]["model_number"] for a in manifest["atoms"]} == {7}
    cb = [a for a in manifest["atoms"] if a["atom_name"] == "CB" and a["ref"]["residue"]["seq_auth"] == 1]
    assert len(cb) == 1 and cb[0]["original_coordinate_A"][0] == pytest.approx(ALA[4][2][0] + 10.5)
    # "first" policy keeps altloc A instead; the choice is the preparation's, not the projection's.
    run2, _, first = _load(tmp_path, _cif(rows), "cif", model_index=1, run_id="run_first",
                           prepare={**PREPARE, "altloc": "first"})
    cb2 = next(a for a in project(run2.store, first)["manifest"]["atoms"] if a["atom_name"] == "CB")
    assert cb2["original_coordinate_A"][0] == pytest.approx(ALA[4][2][0] + 10)


def test_duplicate_atom_names_and_split_residue_identity_reject(tmp_path: Path) -> None:
    dup = _ala("A", 1, (0, 0, 0))
    dup["atoms"].append(("CB", "C", (3.0, -1.5, -2.0)))
    run, _, prepared = _load(tmp_path, _pdb([dup, _ala("A", 2, (4, 1, 0.5))]), "pdb")
    failure = _reject(run.store, prepared, code="duplicate_atom_name")
    assert failure.detail["atom_name"] == "CB" and failure.detail["residue"]["seq_auth"] == 1
    # gemmi merges a re-opened residue on read, so the product path cannot produce a split
    # residue run; the projection guard is exercised on a SYNTHETIC reordered view of real rows.
    from mw.pocket_input import _group

    rows = [{"ref": r["ref"], "coordinate_A": r["coordinate_A"], "occupancy": 1.0, "b_factor": 0.0}
            for r in atom_rows(run.store, prepared)["rows"]]
    order = [r for r in rows if r["ref"]["residue"]["seq_auth"] == 1][:3] + \
        [r for r in rows if r["ref"]["residue"]["seq_auth"] == 2] + \
        [r for r in rows if r["ref"]["residue"]["seq_auth"] == 1][3:4]
    view = {"rows": [{**r, "ref": {**r["ref"], "site_index": i}} for i, r in enumerate(order)]}
    with pytest.raises(ToolFailure) as caught:
        _group(view)
    assert caught.value.detail["reason_code"] == "duplicate_residue_identity"


def test_field_overflow_and_nonrepresentable_values_reject(tmp_path: Path) -> None:
    far = _cif([*_cif_ala("A", 1, (0, 0, 0)), *_cif_ala("A", 2, (10000.0, 0, 0))])
    run, _, handle = _load(tmp_path, far, "cif", run_id="run_far")
    _reject(run.store, handle, code="field_overflow")
    negative = _cif([*_cif_ala("A", 1, (0, 0, 0)), *_cif_ala("A", 2, (-1000.0, 0, 0))])
    run, _, handle = _load(tmp_path, negative, "cif", run_id="run_negative")
    _reject(run.store, handle, code="field_overflow")
    b_factor = _cif([*_cif_ala("A", 1, (0, 0, 0)), *_cif_ala("A", 2, (4, 1, 0.5), b=1000.0)])
    run, _, handle = _load(tmp_path, b_factor, "cif", run_id="run_bfactor")
    _reject(run.store, handle, code="field_overflow")
    long_name = [*_cif_ala("A", 1, (0, 0, 0)), *_cif_ala("A", 2, (4, 1, 0.5))]
    long_name[-1] = {**long_name[-1], "atom": "CBXYZ"}
    run, _, handle = _load(tmp_path, _cif(long_name), "cif", run_id="run_name")
    _reject(run.store, handle, code="field_overflow")
    # Maximal representable coordinates are accepted.
    edge = _cif([*_cif_ala("A", 1, (-990.0, 0, 0)), *_cif_ala("A", 2, (9990.0, 9990.0, 9990.0))])
    run, _, handle = _load(tmp_path, edge, "cif", run_id="run_edge")
    _assert_bijection(run.store, handle, project(run.store, handle))


def test_coincident_projected_atoms_and_degenerate_inputs_reject(tmp_path: Path) -> None:
    near = [_ala("A", 1, (0, 0, 0)),
            {"chain": "A", "seq": 2, "name": "GLY", "atoms": [("N", "N", (1.458, 0.0, 0.0)),
                                                              ("CA", "C", (5, 5, 5))]}]
    run, _, handle = _load(tmp_path, _pdb(near), "pdb", run_id="run_coincident")
    failure = _reject(run.store, handle, code="coincident_atoms")
    assert {a["atom_name"] for a in failure.detail["atoms"]} == {"CA", "N"}
    # Distinct source coordinates that quantize to the same 8.3 value also coincide.
    close = [*_cif_ala("A", 1, (0, 0, 0)),
             {"chain": "A", "seq": 2, "name": "GLY", "atom": "N", "element": "N", "xyz": [1.4582, 0.0001, 0.0]},
             {"chain": "A", "seq": 2, "name": "GLY", "atom": "CA", "element": "C", "xyz": [6.0, 6.0, 6.0]}]
    run, _, handle = _load(tmp_path, _cif(close), "cif", run_id="run_quantized_coincident")
    _reject(run.store, handle, code="coincident_atoms")
    three = [{"chain": "A", "seq": 1, "name": "GLY", "atoms": [(n, e, xyz) for n, e, xyz in ALA[:3]]}]
    run, _, handle = _load(tmp_path, _pdb(three), "pdb", run_id="run_three")
    assert _reject(run.store, handle, code="too_few_atoms").detail["count"] == 3
    planar = [{"chain": "A", "seq": 1, "name": "GLY", "atoms": [(n, e, xyz) for n, e, xyz in ALA[:4]]},
              {"chain": "A", "seq": 2, "name": "GLY", "atoms": [("N", "N", (3.0, 3.0, 0.0)),
                                                                ("CA", "C", (4.0, 1.0, 0.0))]}]
    run, _, handle = _load(tmp_path, _pdb(planar), "pdb", run_id="run_planar")
    _reject(run.store, handle, code="degenerate_geometry")
    collinear = [{"chain": "A", "seq": i, "name": "GLY", "atoms": [("CA", "C", (3.8 * i, 0.0, 0.0))]}
                 for i in range(1, 7)]
    run, _, handle = _load(tmp_path, _pdb(collinear), "pdb", run_id="run_line")
    _reject(run.store, handle, code="degenerate_geometry")
    water_only = [_ala("A", 1, (0, 0, 0)), _ala("A", 2, (4, 1, 0.5)),
                  {"chain": "W", "seq": 1, "name": "HOH", "record": "HETATM", "atoms": [("O", "O", (9, 9, 9))]}]
    run, _, handle = _load(tmp_path, _pdb(water_only), "pdb", run_id="run_water_chain")
    assert _reject(run.store, handle, chains=["A", "W"], code="chain_without_protein").detail["chains"] == ["W"]
    assert project(run.store, handle)["manifest"]["excluded_counts"]["unselected_chain"] == 1


def _grid(n: int, spacing: float = 1.6):
    side = math.ceil(n ** (1 / 3))
    for i in range(n):
        yield (spacing * (i % side), spacing * ((i // side) % side), spacing * (i // side // side))


def test_projection_limits_reject_before_any_transport(tmp_path: Path) -> None:
    points = _grid(63 * 5)
    chains = [f"C{i}" for i in range(63)]
    rows = [{"chain": c, "seq": 1, "name": "ALA", "atom": n, "element": e, "xyz": list(next(points))}
            for c in chains for n, e, _ in ALA]
    run, _, handle = _load(tmp_path, _cif(rows), "cif", run_id="run_chains")
    _reject(run.store, handle, cls=FailureClass.resource_exceeded, code="chain_limit")
    assert project(run.store, handle, chains[:62])["manifest"]["counts"]["chains"] == 62
    points = _grid(3001)
    residues = [{"chain": "A", "seq": i + 1, "name": "GLY", "atoms": [("CA", "C", next(points))]}
                for i in range(3001)]
    run, _, handle = _load(tmp_path, _pdb(residues), "pdb", run_id="run_residues")
    _reject(run.store, handle, cls=FailureClass.resource_exceeded, code="residue_limit")
    summary = preflight(run.store, handle)
    assert summary["projected_residue_count"] == 3001 and summary["reject"]["stage"] == "transport"
    points = _grid(2001 * 5)
    residues = [{"chain": "A", "seq": i + 1, "name": "ALA",
                 "atoms": [(n, e, next(points)) for n, e, _ in ALA]} for i in range(2001)]
    run, _, handle = _load(tmp_path, _pdb(residues), "pdb", run_id="run_atoms")
    _reject(run.store, handle, cls=FailureClass.resource_exceeded, code="heavy_atom_limit")
    # Input byte limit: a synthetic prepared source larger than 10 MiB (bulk waters).
    lines = [_pdb_line(i + 1, n, "ALA", "A", 1, xyz, e) for i, (n, e, xyz) in enumerate(ALA)]
    points = _grid(132_000, 3.0)
    for k in range(132_000):
        lines.append(_pdb_line((k % 99_999) + 1, "O", "HOH", "W", (k % 9999) + 1, next(points), "O",
                               record="HETATM"))
    raw = ("\n".join(lines) + "\nEND\n").encode()
    run, _, handle = _load(tmp_path, raw, "pdb", run_id="run_bytes")
    from mw.tools.structural import structure_bytes
    assert len(structure_bytes(run.store, handle)[0]) > MAX_INPUT_BYTES
    _reject(run.store, handle, cls=FailureClass.resource_exceeded, code="input_size_limit")
