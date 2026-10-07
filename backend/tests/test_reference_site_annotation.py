"""M16 T2 site annotation tool (``annotate_reference_sites`` -> ``reference_site_annotation@1``).

Inputs: the public 1MQ4 mmCIF (``fixtures/public_1mq4.cif``), the derived structures in ``fixtures/structures_m15``,
a reference FIXTURE set built from ``fixtures/reference`` (verbatim kbase_kinase processed rows) by
``reference_fixture_set.build_fixture_set``, and SYNTHETIC variants made inside the tests (functions / file names
containing ``synthetic``; each says what it changes). Constructed numbering maps are labelled SYNTHETIC too.

Independent oracle: the 1MQ4 site contacts are recomputed here with numpy from the prepared structure's ``_atom_site``
table (read with ``gemmi.cif`` only, not ``gemmi.Structure`` and not ``compute_interactions``) and compared with the
annotation and with the T1 preflight values (docs/qa/m16-annotations-20261001/preflight.txt). numpy and gemmi
distances may differ in the last float digit, so distances are compared with ``abs <= 1e-9``.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import gemmi
import numpy as np
import pytest
from reference_fixture_set import build_fixture_set

from mw import reference_snapshots as rs
from mw import site_annotation as sa
from mw.core.errors import FailureClass, ToolFailure
from mw.runtime.orchestrator import replay
from mw.tools import site_annotation as tool_module
from mw.tools.structural import structure_residues
from mw.workspace import build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
REF = FIX / "reference"
CIF_1MQ4 = FIX / "public_1mq4.cif"
PDB_A200 = FIX / "structures_m15" / "derived_1mq4_a200_285_fixture.pdb"
TOOL = tool_module.TOOL
ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
ADP_7 = {**ADP, "chain_label": "E", "seq_label": None}
TYPES = ("contact", "polar_contact", "hydrophobic_contact")
TOL = 1e-9
SITE_LABELS = ["III.17", "αC.24", "GK.45", "hinge.46", "hinge.47", "hinge.48", "xDFG.80", "xDFG.81", "xDFG.82",
               "xDFG.83"]
TOP_KEYS = {"schema", "method_version", "site_set", "numbering_map", "snapshot_set_hash", "structure", "contacts",
            "groups", "other_contact_residues", "null_result", "limitations"}
SITE_KEYS = {"klifs_index", "klifs_label", "status", "absent_reason", "residue", "map_row_index", "residue_match",
             "klifs_match", "display_label", "contact"}
LIMITATIONS = [
    "기하 접촉은 중원자 사이 거리만으로 정한 것이며 수소결합이나 화학 상호작용 판정이 아니다.",
    "KLIFS 번호는 참조 스냅샷 값이며 잔기의 역할을 뜻하지 않는다.",
    "없음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이다.",
    "접촉 도구는 폴리머 레코드 잔기만 검사하므로 HETATM 변형 잔기는 검사하지 않는다.",
]
# T1 preflight (1MQ4:A, prepared structure, fixture set): site -> (map row, resname, seq_auth, seq_label,
# (contact, polar_contact, hydrophobic_contact) counts, cutoff-4.0 minimum distance or None).
PREFLIGHT = {
    17: (36, "LYS", 162, 43, (7, 3, 0), 2.6428630308814687),
    24: (55, "GLU", 181, 62, (0, 0, 0), None),
    45: (84, "LEU", 210, 91, (2, 0, 0), 3.912459584455801),
    46: (85, "GLU", 211, 92, (2, 1, 0), 2.695699723633924),
    47: (86, "TYR", 212, 93, (0, 0, 0), None),
    48: (87, "ALA", 213, 94, (4, 2, 0), 3.167315109047404),
    80: (147, "ALA", 273, 154, (0, 0, 0), None),
    81: (148, "ASP", 274, 155, (8, 4, 0), 2.853779599058067),
    82: (149, "PHE", 275, 156, (0, 0, 0), None),
    83: (150, "GLY", 276, 157, (0, 0, 0), None),
}
PREFLIGHT_POLAR = {
    17: [("NZ", "O1A", 2.6428630308814687), ("NZ", "O1B", 2.891246444009921), ("NZ", "O3A", 3.199847808880909)],
    46: [("O", "N6", 2.695699723633924)],
    48: [("N", "N1", 3.167315109047404), ("O", "N1", 3.84715804198372)],
    81: [("OD1", "O1B", 2.9342752086333013), ("OD1", "O2A", 2.9254124495530527), ("OD1", "O3B", 2.853779599058067),
         ("OD2", "O1B", 2.9631592937268834)],
}


# --- helpers ------------------------------------------------------------------------------------------------------

def _rows(rel: str) -> list[dict]:
    return [json.loads(line) for line in (REF / rel).read_bytes().splitlines() if line.strip()]


def _jsonl(rows: list[dict]) -> bytes:
    return b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows)


@pytest.fixture
def refroot(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    return root


@pytest.fixture
def ref(refroot):
    build_fixture_set(refroot)
    return refroot


def _install(refroot, tag, replace):
    rs._VERIFIED.clear()
    return build_fixture_set(refroot, tag=tag, replace=replace)


def _run(tmp_path, name="run_sites", dry_run=False):
    reg = build_registry()
    calls: list[dict] = []
    impl = reg.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    reg.impls[TOOL] = counted
    return new_run(tmp_path / "runs", run_id=name, dry_run=dry_run, registry=reg), calls


def _load(run, path: Path, model_index: int = 0) -> str:
    return run.call("load_structure", {"source": str(path), "model_index": model_index}).handle


def _prepare(run, structure: str) -> str:
    return run.call("prepare_structure", {"structure": structure}).handle   # config defaults (waters keep_all)


def _map(run, structure, chains=None, pdb_id="1MQ4") -> str:
    chains = chains or [{"chain_auth": "A"}]
    return run.call("map_residue_numbering", {"structure": structure, "pdb_id": pdb_id, "chains": chains}).handle


def _contacts(run, structure, ligand=None, **params) -> str:
    return run.call("compute_interactions", {"structure": structure, "ligand": ligand or ADP, **params}).handle


def _annotate(run, numbering_map, contacts=None, *, omit_contacts=False):
    args = {"numbering_map": numbering_map} if omit_contacts else {"numbering_map": numbering_map,
                                                                    "contacts": contacts}
    out = run.call(TOOL, args)
    return out, run.store.load(out.handle)


def _events(run, kind=None):
    return [e for e in run.events.read() if kind is None or e["type"] == kind]


def _site(content, label, accession="O14965", chain_auth="A"):
    group = next(g for g in content["groups"] if g["accession"] == accession and g["chain_auth"] == chain_auth)
    return next(s for s in group["sites"] if s["klifs_label"] == label)


def _key7(residue):
    return tuple(residue[k] for k in ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode",
                                      "resname"))


# --- independent numpy oracle on the prepared coordinates ---------------------------------------------------------

def _oracle(prepared_cif: bytes, cutoff: float, types=TYPES) -> dict:
    """{(seq_auth, icode): [(type, protein_atom, ligand_atom, distance)]} from _atom_site with numpy.

    The prepared mmCIF (written by gemmi) has label_atom_id/label_comp_id and auth_seq_id/auth_asym_id only.
    """
    block = gemmi.cif.read_string(prepared_cif.decode()).sole_block()
    table = block.find("_atom_site.", ["group_PDB", "type_symbol", "label_atom_id", "label_comp_id", "auth_asym_id",
                                      "auth_seq_id", "pdbx_PDB_ins_code", "Cartn_x", "Cartn_y", "Cartn_z"])
    atoms = []
    for row in table:
        icode = row[6] if row[6] not in ("?", ".") else ""
        atoms.append({"group": row[0], "element": row[1].upper(), "name": gemmi.cif.as_string(row[2]),
                      "resname": row[3], "chain": row[4], "seq": int(row[5]), "icode": icode,
                      "xyz": (float(row[7]), float(row[8]), float(row[9]))})
    protein = [a for a in atoms if a["group"] == "ATOM" and a["element"] != "H"]
    ligand = [a for a in atoms if a["resname"] == "ADP" and a["chain"] == "A" and a["seq"] == 2001
              and a["element"] != "H"]
    assert len(ligand) == 27
    p_xyz = np.array([a["xyz"] for a in protein])
    l_xyz = np.array([a["xyz"] for a in ligand])
    dist = np.sqrt(((p_xyz[:, None, :] - l_xyz[None, :, :]) ** 2).sum(axis=2))
    out: dict = {}
    for i, j in zip(*np.nonzero(dist <= cutoff), strict=True):
        pa, la = protein[i], ligand[j]
        if pa["element"] in ("N", "O") and la["element"] in ("N", "O"):
            kind = "polar_contact"
        elif pa["element"] == "C" and la["element"] == "C":
            kind = "hydrophobic_contact"
        else:
            kind = "contact"
        if kind in types:
            out.setdefault((pa["seq"], pa["icode"]), []).append((kind, pa["name"], la["name"], float(dist[i, j])))
    return out


def _prepared_bytes(run, prepared) -> bytes:
    return run.store.load(run.store.load(prepared)["coordinates"])


# --- constants, label, limitations --------------------------------------------------------------------------------

def test_site_set_and_limitations_are_exact():
    assert sa.SITE_SET_ID == "kinase_key_sites@1"
    assert [s["klifs_index"] for s in sa.site_set()["sites"]] == [17, 24, 45, 46, 47, 48, 80, 81, 82, 83]
    assert [s["klifs_label"] for s in sa.site_set()["sites"]] == SITE_LABELS
    assert sa.site_set()["sites"][1]["klifs_label"].encode() == b"\xce\xb1C.24"
    assert list(sa.LIMITATIONS) == LIMITATIONS
    assert sa.SCHEMA == "reference_site_annotation@1" and sa.KIND == "reference_site_annotation"


@pytest.mark.parametrize(("resname", "seq_auth", "icode", "label", "expected"), [
    ("MET", 318, "", "hinge.47", "Met318 (hinge.47)"),
    ("ALA", 100, "A", "hinge.46", "Ala100A (hinge.46)"),
    ("MSE", 300, "", "xDFG.80", "MSE300 (xDFG.80)"),
    ("GLU", 181, "", "αC.24", "Glu181 (αC.24)"),
    ("SEP", 12, "", "GK.45", "SEP12 (GK.45)"),
])
def test_display_label(resname, seq_auth, icode, label, expected):
    residue = {"model_number": 1, "chain_auth": "A", "chain_label": None, "seq_auth": seq_auth, "seq_label": None,
               "icode": icode, "resname": resname}
    assert sa.display_label(residue, label) == expected


# --- 1MQ4 oracle --------------------------------------------------------------------------------------------------

def test_1mq4_prepared_adp_sites_match_numpy_oracle_and_preflight(tmp_path, ref):
    run, calls = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    numbering_map = _map(run, prepared)
    contacts = _contacts(run, prepared)
    out, content = _annotate(run, numbering_map, contacts)
    assert len(calls) == 1 and out.kind == "reference_site_annotation" and out.null_result is False
    assert set(content) == TOP_KEYS
    assert content["schema"] == "reference_site_annotation@1"
    assert content["site_set"] == {"id": "kinase_key_sites@1",
                                   "sites": [{"klifs_index": i, "klifs_label": lab} for i, lab in
                                             zip(PREFLIGHT, SITE_LABELS, strict=True)]}
    map_content = run.store.load(numbering_map)
    assert content["numbering_map"] == numbering_map
    assert content["snapshot_set_hash"] == map_content["snapshot_set"]["set_hash"]
    assert content["structure"] == {"handle": prepared, "structure_kind": "prepared_structure", "model_number": 1}
    assert content["contacts"] == {"handle": contacts, "ligand": ADP_7, "cutoff_A": 4.0, "types": sorted(TYPES)}
    assert content["limitations"] == LIMITATIONS and content["null_result"] is False
    assert [(g["chain_auth"], g["accession"], g["klifs_applied"], g["klifs_absent_reason"])
            for g in content["groups"]] == [("A", "O14965", True, None)]
    rows = run.store.load(contacts)["rows"]
    oracle = _oracle(_prepared_bytes(run, prepared), 4.0)
    for site, label in zip(content["groups"][0]["sites"], SITE_LABELS, strict=True):
        assert set(site) == SITE_KEYS
        row_index, resname, seq_auth, seq_label, counts, minimum = PREFLIGHT[site["klifs_index"]]
        assert site["status"] == "annotated" and site["absent_reason"] is None and site["klifs_label"] == label
        assert site["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": seq_auth,
                                   "seq_label": seq_label, "icode": "", "resname": resname}
        assert site["map_row_index"] == row_index and map_content["rows"][row_index]["residue"] == site["residue"]
        assert site["residue_match"] is True and site["klifs_match"] == "contiguous"
        assert site["display_label"] == f"{resname.capitalize()}{seq_auth} ({label})"
        contact = site["contact"]
        assert contact["assessed"] is True and contact["not_assessed_reason"] is None
        # oracle (independent numpy) and preflight counts agree with the annotation
        found = oracle.get((seq_auth, ""), [])
        oracle_counts = tuple(sum(1 for f in found if f[0] == t) for t in TYPES)
        assert oracle_counts == counts
        assert {t: contact["by_type"][t] for t in TYPES} == {
            t: {"computed": True, "count": c} for t, c in zip(TYPES, counts, strict=True)}
        if minimum is None:
            assert contact["min_distance_A"] is None and contact["min_distance_row_index"] is None and not found
        else:
            assert abs(contact["min_distance_A"] - minimum) <= TOL
            assert abs(contact["min_distance_A"] - min(f[3] for f in found)) <= TOL
            # the value is the stored row value itself, from the lowest row index among equal minima
            chosen = rows[contact["min_distance_row_index"]]
            assert chosen["distance_A"] == contact["min_distance_A"] and _key7(chosen["residue"]) == _key7(
                site["residue"])
            assert all(r["distance_A"] > contact["min_distance_A"] for r in rows[:contact["min_distance_row_index"]]
                       if _key7(r["residue"]) == _key7(site["residue"]))
        expected_polar = sorted(PREFLIGHT_POLAR.get(site["klifs_index"], []))
        oracle_polar = sorted((f[1], f[2], f[3]) for f in found if f[0] == "polar_contact")
        got = sorted((p["protein_atom"], p["ligand_atom"], p["distance_A"]) for p in contact["polar_pairs"])
        assert [(a, b) for a, b, _ in got] == [(a, b) for a, b, _ in expected_polar] == [(a, b) for a, b, _ in
                                                                                        oracle_polar]
        for (_, _, d), (_, _, e), (_, _, o) in zip(got, expected_polar, oracle_polar, strict=True):
            assert abs(d - e) <= TOL and abs(d - o) <= TOL
        for pair in contact["polar_pairs"]:
            stored = rows[pair["contact_row_index"]]
            assert stored["type"] == "polar_contact" and stored["distance_A"] == pair["distance_A"]
            assert (stored["protein_atom"], stored["ligand_atom"]) == (pair["protein_atom"], pair["ligand_atom"])
    # other contact residues: every contacted residue that is not an annotated site, with all its row indexes
    site_keys = {_key7(s["residue"]) for s in content["groups"][0]["sites"]}
    expected_other: dict = {}
    for index, row in enumerate(rows):
        if _key7(row["residue"]) not in site_keys:
            expected_other.setdefault(_key7(row["residue"]), []).append(index)
    got_other = {_key7(o["residue"]): o["row_indexes"] for o in content["other_contact_residues"]}
    assert got_other == expected_other and got_other
    oracle_other = {k for k in oracle if k not in {(s["residue"]["seq_auth"], "") for s in
                                                  content["groups"][0]["sites"]}}
    assert {(k[3], k[5]) for k in got_other} == oracle_other


def test_1mq4_site_labels_and_residues_equal_the_klifs_match_residues_excerpt(tmp_path, ref):
    # Spec 10.2: the committed KLIFS per-structure table (comparison-only, parsed here, not via product code) gives
    # each pocket index its label and author residue number; the excerpt has no residue name, so the name is read
    # independently from the 1MQ4 mmCIF itself with gemmi.
    table = next(r for r in _rows("klifs/match_residues_fixture.jsonl")
                 if r["pdb_id"] == "1MQ4" and r["chain"] == "A")["data"]
    table = json.loads(table) if isinstance(table, str) else table
    excerpt = {item["index"]: item for item in table}
    model = gemmi.read_structure(str(CIF_1MQ4))[0]
    names = {(res.seqid.num, res.seqid.icode.strip()): res.name for res in model["A"]}
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    _, content = _annotate(run, _map(run, prepared), _contacts(run, prepared))
    sites = content["groups"][0]["sites"]
    assert [s["klifs_index"] for s in sites] == list(PREFLIGHT)
    for site in sites:
        item = excerpt[site["klifs_index"]]
        assert site["status"] == "annotated" and site["klifs_label"] == item["KLIFS_position"]
        assert str(site["residue"]["seq_auth"]) == item["Xray_position"] and site["residue"]["icode"] == ""
        assert site["residue"]["chain_auth"] == "A"
        assert site["residue"]["resname"] == names[(int(item["Xray_position"]), "")]


def test_same_input_same_handle_and_omitted_contacts_is_null(tmp_path, ref):
    run, calls = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    numbering_map = _map(run, prepared)
    first, _ = _annotate(run, numbering_map, None)
    second, _ = _annotate(run, numbering_map, omit_contacts=True)
    assert first.handle == second.handle and len(calls) == 1
    assert len([e for e in _events(run, "object_created") if e["kind"] == "reference_site_annotation"]) == 1
    # the content is deterministic: building it again from the same objects gives the same bytes
    content = run.store.load(first.handle)
    rebuilt = sa.build_annotation(numbering_map, run.store.load(numbering_map),
                                  structure_residues(run.store, prepared)["residues"], None, None)
    assert rebuilt == content


def test_no_contacts_leaves_every_contact_null(tmp_path, ref):
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    _, content = _annotate(run, _map(run, prepared), None)
    assert content["contacts"] is None and content["other_contact_residues"] is None
    assert all(s["contact"] is None for g in content["groups"] for s in g["sites"])
    assert all(s["status"] == "annotated" for g in content["groups"] for s in g["sites"])


def test_polar_not_computed_is_null_not_zero(tmp_path, ref):
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    contacts = _contacts(run, prepared, types=["contact", "hydrophobic_contact"])
    _, content = _annotate(run, _map(run, prepared), contacts)
    assert content["contacts"]["types"] == ["contact", "hydrophobic_contact"]
    oracle = _oracle(_prepared_bytes(run, prepared), 4.0, types=("contact", "hydrophobic_contact"))
    lys = _site(content, "III.17")["contact"]
    assert lys["by_type"] == {"contact": {"computed": True, "count": 7},
                              "polar_contact": {"computed": False, "count": None},
                              "hydrophobic_contact": {"computed": True, "count": 0}}
    assert lys["polar_pairs"] is None
    assert abs(lys["min_distance_A"] - min(f[3] for f in oracle[(162, "")])) <= TOL
    hinge47 = _site(content, "hinge.47")["contact"]
    assert hinge47["by_type"]["polar_contact"] == {"computed": False, "count": None}
    assert hinge47["by_type"]["contact"] == {"computed": True, "count": 0} and hinge47["polar_pairs"] is None


def test_zero_row_contacts_counts_zero_and_distance_null(tmp_path, ref):
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    contacts = _contacts(run, prepared, cutoff_A=2.5, types=["polar_contact", "hydrophobic_contact"])
    assert run.store.load(contacts)["rows"] == [] and run.store.meta(contacts)["null_result"] is True
    assert not _oracle(_prepared_bytes(run, prepared), 2.5, types=("polar_contact", "hydrophobic_contact"))
    _, content = _annotate(run, _map(run, prepared), contacts)
    assert content["other_contact_residues"] == [] and content["null_result"] is False
    for site in content["groups"][0]["sites"]:
        contact = site["contact"]
        assert contact["by_type"] == {"contact": {"computed": False, "count": None},
                                      "polar_contact": {"computed": True, "count": 0},
                                      "hydrophobic_contact": {"computed": True, "count": 0}}
        assert contact["min_distance_A"] is None and contact["min_distance_row_index"] is None
        assert contact["polar_pairs"] == []


# --- absent reasons and groups ------------------------------------------------------------------------------------

def _synthetic_klifs(transform) -> dict:
    """SYNTHETIC: kinases_fixture.jsonl passed through ``transform(rows) -> rows``."""
    return {("klifs", "kinases.jsonl"): _jsonl(transform(copy.deepcopy(_rows("klifs/kinases_fixture.jsonl"))))}


def _pocket_edit(**positions):
    def transform(rows):
        for row in rows:
            if row["uniprot"] == "O14965":
                pocket = list(row["pocket"])
                for index, letter in positions.items():
                    pocket[int(index[1:]) - 1] = letter
                row["pocket"] = "".join(pocket)
        return rows
    return transform


def test_klifs_not_applied_group_reason(tmp_path, refroot):
    _install(refroot, "no_klifs", _synthetic_klifs(lambda rows: [r for r in rows if r["uniprot"] != "O14965"]))
    run, _ = _run(tmp_path)
    _, content = _annotate(run, _map(run, _prepare(run, _load(run, CIF_1MQ4))), None)
    [group] = content["groups"]
    assert (group["accession"], group["klifs_applied"], group["klifs_absent_reason"]) == (
        "O14965", False, "accession_not_in_klifs")
    assert {(s["status"], s["absent_reason"]) for s in group["sites"]} == {("absent", "klifs_not_applied")}
    assert all(s["residue"] is None and s["contact"] is None and s["display_label"] is None for s in group["sites"])
    assert content["null_result"] is True


def test_pocket_gap_and_region_unresolved(tmp_path, refroot):
    # SYNTHETIC: O14965 pocket position 80 -> '-' (gap) and position 45 -> 'X' (a letter not in the sequence, so the
    # GK region cannot be placed).
    _install(refroot, "gap", _synthetic_klifs(_pocket_edit(p80="-", p45="X")))
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    numbering_map = _map(run, prepared)
    assert run.store.load(numbering_map)["chains"][0]["klifs"][0]["unresolved_regions"] == ["I", "GK", "a.l"]
    _, content = _annotate(run, numbering_map, _contacts(run, prepared))
    assert (_site(content, "xDFG.80")["status"], _site(content, "xDFG.80")["absent_reason"]) == ("absent",
                                                                                                "pocket_gap")
    assert (_site(content, "GK.45")["status"], _site(content, "GK.45")["absent_reason"]) == ("absent",
                                                                                            "region_unresolved")
    assert _site(content, "xDFG.80")["contact"] is None and _site(content, "GK.45")["contact"] is None
    assert _site(content, "xDFG.81")["status"] == "annotated" and _site(content, "hinge.46")["status"] == "annotated"
    # the residues of the absent sites that touch the ligand now count as other contact residues (LEU210)
    assert 210 in {o["residue"]["seq_auth"] for o in content["other_contact_residues"]}


def test_no_mapped_residue_when_the_structure_lacks_the_site(tmp_path, ref):
    run, _ = _run(tmp_path)
    _, content = _annotate(run, _map(run, _load(run, PDB_A200)), None)   # chain A residues 200-285 only
    assert [(s["klifs_label"], s["status"], s["absent_reason"]) for s in content["groups"][0]["sites"]][:3] == [
        ("III.17", "absent", "no_mapped_residue"), ("αC.24", "absent", "no_mapped_residue"),
        ("GK.45", "annotated", None)]
    hinge = _site(content, "hinge.46")["residue"]
    assert hinge["seq_label"] is None and hinge["seq_auth"] == 211   # PDB without labels: null kept
    assert content["null_result"] is False


def test_chain_without_mapped_accession_is_a_null_group(tmp_path, refroot):
    # SYNTHETIC: the 1MQ4 SIFTS segment shifted by one UniProt position -> every row is a conflict, no accession.
    segments = _rows("sifts/segments_fixture.jsonl")
    for row in segments:
        if row["pdb_id"] == "1MQ4":
            for item in row["data"]:
                item["unp_start"] += 1
                item["unp_end"] += 1
    _install(refroot, "shift", {("sifts", "segments.jsonl"): _jsonl(segments)})
    run, _ = _run(tmp_path)
    numbering_map = _map(run, _load(run, CIF_1MQ4))
    assert run.store.load(numbering_map)["chains"][0]["klifs"] == []
    out, content = _annotate(run, numbering_map, None)
    assert [(g["chain_auth"], g["accession"], g["klifs_applied"], g["klifs_absent_reason"])
            for g in content["groups"]] == [("A", None, False, "no_mapped_accession")]
    assert {(s["status"], s["absent_reason"]) for s in content["groups"][0]["sites"]} == {
        ("absent", "klifs_not_applied")}
    assert content["null_result"] is True and out.null_result is True


def test_fusion_chain_gets_one_group_per_accession(tmp_path, refroot):
    # SYNTHETIC: the 1MQ4 entity split into O14965 (PDBe 6-150) and Q8IU85 (PDBe 151-272), as in the M15 tests.
    segments = _rows("sifts/segments_fixture.jsonl")
    base = {"chain_id": "A", "coverage": 0.663, "entity_id": 1, "identity": 1.0, "res_end": 150, "res_start": 6,
            "uniprot": "O14965", "unp_end": 269, "unp_start": 125}
    for row in segments:
        if row["pdb_id"] == "1MQ4":
            row["data"] = [base, {**base, "res_start": 151, "res_end": 272, "uniprot": "Q8IU85", "unp_start": 1,
                                  "unp_end": 122}]
    _install(refroot, "fusion", {("sifts", "segments.jsonl"): _jsonl(segments)})
    run, _ = _run(tmp_path)
    numbering_map = _map(run, _load(run, CIF_1MQ4))
    map_content = run.store.load(numbering_map)
    _, content = _annotate(run, numbering_map, None)
    assert [(g["chain_auth"], g["accession"]) for g in content["groups"]] == [("A", "O14965"), ("A", "Q8IU85")]
    for group in content["groups"]:
        assert len(group["sites"]) == 10
        for site in group["sites"]:
            if site["status"] == "annotated":
                row = map_content["rows"][site["map_row_index"]]
                assert row["uniprot_accession"] == group["accession"] and row["status"] == "mapped"
                assert row["klifs_index"] == site["klifs_index"] and row["residue"] == site["residue"]
            else:
                assert not [r for r in map_content["rows"] if r["status"] == "mapped" and r["klifs_index"] ==
                            site["klifs_index"] and r["uniprot_accession"] == group["accession"]]
    # hinge residues 211-213 (PDBe 92-94) are O14965 rows; xDFG residues 273-276 (PDBe 154-157) are not
    assert _site(content, "hinge.46")["residue"]["seq_auth"] == 211
    assert _site(content, "xDFG.81")["absent_reason"] == "no_mapped_residue"


# --- HETATM site residue and identity (null label, insertion code, non-first model) --------------------------------

def test_hetatm_site_residue_is_annotated_but_not_assessed(tmp_path, ref):
    # SYNTHETIC derived fixture: public 1MQ4 with GLU211 (hinge.46) written as HETATM MSE (names only).
    doc = gemmi.cif.read(str(CIF_1MQ4))
    table = doc.sole_block().find("_atom_site.", ["group_PDB", "auth_seq_id", "auth_asym_id", "label_comp_id",
                                                  "auth_comp_id"])
    for row in table:
        if row[1] == "211" and row[2] == "A":
            row[0], row[3], row[4] = "HETATM", "MSE", "MSE"
    path = tmp_path / "synthetic_1mq4_glu211_hetatm_mse_fixture.cif"
    doc.write_file(str(path))
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, path))
    residue = next(r for r in structure_residues(run.store, prepared)["residues"] if r["seq_auth"] == 211)
    assert residue["resname"] == "MSE" and residue["category"] == "nonpolymer"
    _, content = _annotate(run, _map(run, prepared), _contacts(run, prepared))
    site = _site(content, "hinge.46")
    assert site["status"] == "annotated" and site["residue"]["resname"] == "MSE"
    assert site["residue_match"] is False and site["display_label"] == "MSE211 (hinge.46)"
    assert site["contact"] == {"assessed": False, "not_assessed_reason": "residue_not_checked_by_contact_method",
                               "by_type": {t: {"computed": True, "count": None} for t in TYPES},
                               "min_distance_A": None, "min_distance_row_index": None, "polar_pairs": None}
    assert _site(content, "hinge.48")["contact"]["assessed"] is True


def test_null_label_insertion_code_and_non_first_model(tmp_path, ref):
    # SYNTHETIC derived fixture: public 1MQ4 without waters as a two-model PDB (no labels); in MODEL 2 ALA213
    # (hinge.48) is renumbered 212A. Mapped by alignment only (the insertion code has no SIFTS row).
    st = gemmi.read_structure(str(CIF_1MQ4))
    st.remove_waters()
    st.add_model(st[0])
    st[1].num = 2
    for residue in st[1]["A"]:
        if residue.seqid.num == 213:
            residue.seqid = gemmi.SeqId(212, "A")
    path = tmp_path / "synthetic_1mq4_two_model_icode_fixture.pdb"
    path.write_text(st.make_pdb_string())
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, path, model_index=1))
    numbering_map = _map(run, prepared, [{"chain_auth": "A", "uniprot_accession": "O14965"}], pdb_id=None)
    contacts = _contacts(run, prepared, ligand={**ADP, "model_number": 2})
    _, content = _annotate(run, numbering_map, contacts)
    assert content["structure"]["model_number"] == 2
    hinge47, hinge48 = _site(content, "hinge.47"), _site(content, "hinge.48")
    assert hinge47["residue"] == {"model_number": 2, "chain_auth": "A", "chain_label": hinge47["residue"][
        "chain_label"], "seq_auth": 212, "seq_label": None, "icode": "", "resname": "TYR"}
    assert hinge48["residue"]["icode"] == "A" and hinge48["residue"]["seq_auth"] == 212
    assert hinge48["residue"]["seq_label"] is None and hinge48["residue"]["model_number"] == 2
    assert hinge48["display_label"] == "Ala212A (hinge.48)"
    # identity is compared with all 7 fields: 212 and 212A are different residues
    assert [hinge47["contact"]["by_type"][t]["count"] for t in TYPES] == [0, 0, 0]
    assert [hinge48["contact"]["by_type"][t]["count"] for t in TYPES] == [4, 2, 0]
    assert {(p["protein_atom"], p["ligand_atom"]) for p in hinge48["contact"]["polar_pairs"]} == {("N", "N1"),
                                                                                                ("O", "N1")}
    assert all(o["residue"]["model_number"] == 2 for o in content["other_contact_residues"])


def _synthetic_map(residue_rows: list[dict], *, klifs=None, pocket=None) -> dict:
    """SYNTHETIC residue_numbering_map@1-shaped content (only the fields the annotation reads)."""
    return {"schema": "residue_numbering_map@1", "structure": {"handle": "obj://structure/x", "structure_kind":
                                                                "prepared_structure", "model_number": 1},
            "snapshot_set": {"set_hash": "f" * 64},
            "chains": [{"chain_auth": "A", "klifs": klifs if klifs is not None else [
                {"accession": "P1", "applied": True, "absent_reason": None, "unresolved_regions": [],
                 "gapped_regions": []}]}],
            "reference_rows": {"klifs": [{"accession": "P1", "entries": [{"pocket": pocket or "A" * 85}]}]},
            "rows": residue_rows}


def _res(seq_auth, icode="", chain_label="A", model_number=1, resname="ALA"):
    return {"model_number": model_number, "chain_auth": "A", "chain_label": chain_label, "seq_auth": seq_auth,
            "seq_label": None, "icode": icode, "resname": resname}


def _map_row(residue, klifs_index, status="mapped", accession="P1"):
    return {"residue": residue, "status": status, "uniprot_accession": accession if status == "mapped" else None,
            "klifs_index": klifs_index if status == "mapped" else None,
            "klifs_label": sa.SITE_LABELS[klifs_index] if status == "mapped" else None,
            "klifs_match": "contiguous" if status == "mapped" else None,
            "residue_match": True if status == "mapped" else None}


def test_contact_rows_must_match_all_seven_fields():
    site = _res(211)
    rows = [{"residue": dict(site), "type": "contact", "distance_A": 3.0, "protein_atom": "CB", "ligand_atom": "C1"},
            {"residue": _res(211, chain_label=None), "type": "contact", "distance_A": 2.0, "protein_atom": "CB",
             "ligand_atom": "C1"},
            {"residue": _res(211, icode="A"), "type": "polar_contact", "distance_A": 2.1, "protein_atom": "N",
             "ligand_atom": "N1"},
            {"residue": _res(211, model_number=2), "type": "contact", "distance_A": 2.2, "protein_atom": "CB",
             "ligand_atom": "C1"},
            {"residue": dict(site), "type": "contact", "distance_A": 3.0, "protein_atom": "CG", "ligand_atom": "C2"}]
    contacts = {"structure": "obj://structure/x", "selection": {"ligand": _res(900, resname="LIG")},
                "parameters": {"cutoff_A": 4.0, "types": ["contact", "polar_contact"]}, "rows": rows}
    residues = [{**_res(211), "category": "polymer"}]
    content = sa.build_annotation("obj://map/x", _synthetic_map([_map_row(site, 46)]), residues, "obj://c/x",
                                  contacts)
    contact = _site(content, "hinge.46", accession="P1")["contact"]
    assert contact["by_type"]["contact"] == {"computed": True, "count": 2}
    assert contact["by_type"]["polar_contact"] == {"computed": True, "count": 0}
    assert contact["by_type"]["hydrophobic_contact"] == {"computed": False, "count": None}
    assert (contact["min_distance_A"], contact["min_distance_row_index"]) == (3.0, 0)   # tie -> lowest row index
    assert contact["polar_pairs"] == []
    assert [(o["residue"], o["row_indexes"]) for o in content["other_contact_residues"]] == [
        (_res(211, chain_label=None), [1]), (_res(211, icode="A"), [2]), (_res(211, model_number=2), [3])]


def test_absent_reason_order_and_conflict_rows_are_never_annotated():
    # SYNTHETIC maps: site 45 (GK) is a pocket gap AND in an unresolved region -> pocket_gap (reason 2 before 3);
    # xDFG is unresolved without gaps -> region_unresolved; site 47 has only a conflict row -> no_mapped_residue
    # (conflict rows are never annotated); site 46 has one mapped row -> annotated.
    pocket = ["A"] * 85
    pocket[44] = "-"
    klifs = [{"accession": "P1", "applied": True, "absent_reason": None, "unresolved_regions": ["GK", "xDFG"],
              "gapped_regions": []}]
    rows = [_map_row(_res(211), 46), {**_map_row(_res(212), 47, status="conflict")}]
    content = sa.build_annotation("obj://map/x", _synthetic_map(rows, klifs=klifs, pocket="".join(pocket)),
                                  [{**_res(211), "category": "polymer"}, {**_res(212), "category": "polymer"}],
                                  None, None)
    reasons = {s["klifs_label"]: (s["status"], s["absent_reason"]) for s in content["groups"][0]["sites"]}
    assert reasons["GK.45"] == ("absent", "pocket_gap")
    assert reasons["hinge.46"] == ("annotated", None)
    assert reasons["hinge.47"] == ("absent", "no_mapped_residue")
    assert reasons["xDFG.81"] == ("absent", "region_unresolved")
    assert reasons["III.17"] == ("absent", "no_mapped_residue")
    not_applied = sa.build_annotation("obj://map/x", _synthetic_map(rows, klifs=[{**klifs[0], "applied": False,
                                                                                  "absent_reason":
                                                                                  "klifs_multiple_entries"}],
                                                                    pocket="".join(pocket)),
                                      [{**_res(211), "category": "polymer"}], None, None)
    group = not_applied["groups"][0]
    assert group["klifs_absent_reason"] == "klifs_multiple_entries"
    assert {(s["status"], s["absent_reason"]) for s in group["sites"]} == {("absent", "klifs_not_applied")}


def test_duplicate_site_residue_is_refused_by_the_pure_builder():
    rows = [_map_row(_res(211), 46), _map_row(_res(212), 46)]
    with pytest.raises(sa.AnnotationInvalid) as caught:
        sa.site_groups(_synthetic_map(rows))
    assert caught.value.reason_code == "duplicate_site_residue"
    # a second row of another accession or with another status is not a duplicate
    ok = [_map_row(_res(211), 46), _map_row(_res(212), 46, accession="P2"), _map_row(_res(213), 46, "unmapped")]
    assert sa.site_groups(_synthetic_map(ok))


# --- validation through Run.call: typed failure, implementation never called --------------------------------------

def _rejected(run, calls, args, reason_code):
    before = len(_events(run))
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.cls == FailureClass.input_invalid and caught.value.detail["reason_code"] == reason_code
    new = _events(run)[before:]
    assert [e["type"] for e in new if e["type"] != "wall_charged"] == ["proposal_rejected"]
    assert calls == []


def test_input_validation_never_calls_the_implementation(tmp_path, ref):
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    prepared = _prepare(run, structure)
    numbering_map = _map(run, prepared)
    original_map = _map(run, structure)
    contacts = _contacts(run, prepared)
    other, _ = _run(tmp_path, name="run_other")
    other_prepared = _prepare(other, _load(other, CIF_1MQ4))
    foreign_map = _map(other, other_prepared)
    foreign_contacts = _contacts(other, other_prepared)
    cases = [
        ({"numbering_map": structure}, "numbering_map_invalid"),                     # wrong kind
        ({"numbering_map": contacts}, "numbering_map_invalid"),
        ({"numbering_map": foreign_map}, "numbering_map_invalid"),                   # other run
        ({"numbering_map": "not-a-handle"}, "numbering_map_invalid"),
        ({"numbering_map": None}, "numbering_map_invalid"),
        ({}, "numbering_map_invalid"),
        ({"numbering_map": numbering_map, "contacts": numbering_map}, "contacts_invalid"),
        ({"numbering_map": numbering_map, "contacts": prepared}, "contacts_invalid"),
        ({"numbering_map": numbering_map, "contacts": foreign_contacts}, "contacts_invalid"),
        ({"numbering_map": numbering_map, "contacts": 7}, "contacts_invalid"),
        ({"numbering_map": numbering_map, "contacts": [contacts]}, "contacts_invalid"),
        ({"numbering_map": numbering_map, "extra": 1}, "unknown_field"),
        ({"numbering_map": original_map, "contacts": contacts}, "structure_mismatch"),
    ]
    for args, reason_code in cases:
        _rejected(run, calls, args, reason_code)
    assert not [e for e in _events(run, "tool_called") if e["tool"] == TOOL]


def test_duplicate_site_residue_through_run_call(tmp_path, ref):
    run, calls = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    content = copy.deepcopy(run.store.load(_map(run, prepared)))
    # SYNTHETIC constructed map object: TYR212's row relabelled hinge.46 so two mapped rows carry KLIFS 46.
    content["rows"][86].update(klifs_index=46, klifs_label="hinge.46")
    content["pdb_id"] = "SYNTHETIC_FIXTURE"
    synthetic = run.store.put("residue_numbering_map", "residue_numbering_map@1", content,
                              produced_by="synthetic_fixture").handle
    _rejected(run, calls, {"numbering_map": synthetic}, "duplicate_site_residue")


def test_only_the_new_tool_and_m15_have_prechecks():
    # M20 generate_mutation_candidates and M24 build_jev_projection add their own pre-checks (no key fields), M25
    # build_jev_loop_projection one with key fields (the hash of the loop-record inputs); no other tool gains one.
    assert set(build_registry().prechecks) == {"map_residue_numbering", TOOL, "generate_mutation_candidates",
                                               "build_jev_projection", "build_jev_loop_projection"}


# --- recovery, dry run, API ---------------------------------------------------------------------------------------

def test_events_only_recovery_without_reference_folder(tmp_path, ref):
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    out, _ = _annotate(run, _map(run, prepared), _contacts(run, prepared))
    sha = out.handle.rsplit("/", 1)[1]
    raw = (run.run_dir / "objects" / f"{sha}.json").read_bytes()
    handles = run.store.handles()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    for upload in (run.run_dir / "uploads",):
        shutil.rmtree(upload, ignore_errors=True)
    shutil.rmtree(ref)
    reopened, calls = _run(tmp_path)
    assert (reopened.run_dir / "objects" / f"{sha}.json").read_bytes() == raw
    assert reopened.store.handles() == handles and calls == []
    replayed = replay(run.run_dir / "events.jsonl", tmp_path / "replay" / run.run_id, build_registry(), run.run_id)
    assert replayed == handles
    assert (tmp_path / "replay" / run.run_id / "objects" / f"{sha}.json").read_bytes() == raw


def test_dry_run_executes_the_cheap_tool(tmp_path, ref):
    run, calls = _run(tmp_path, dry_run=True)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    out, content = _annotate(run, _map(run, prepared), _contacts(run, prepared))
    assert out.kind == "reference_site_annotation" and len(calls) == 1
    assert _site(content, "hinge.46")["contact"]["by_type"]["polar_contact"]["count"] == 1
    assert not [e for e in _events(run, "tool_called") if e.get("plan_only")]


def test_http_capability_command_list_and_detail(tmp_path, ref, monkeypatch):
    from fastapi.testclient import TestClient

    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    client = TestClient(appmod.app, base_url="http://127.0.0.1")
    assert client.get("/capabilities").json()["methods"]["reference_site_annotation"] == {
        "available": True, "reason_code": None, "reason": None}
    assert TOOL in {t["name"] for t in client.get("/tools").json()}
    rid = client.post("/runs", json={"goal": "sites"}).json()["run_id"]
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "1mq4.cif"}, content=CIF_1MQ4.read_bytes(),
                         headers={"content-type": "application/octet-stream"}).json()

    def command(tool, args):
        return client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})

    structure = command("load_structure", {"source": upload["upload_id"]}).json()["handle"]["handle"]
    prepared = command("prepare_structure", {"structure": structure}).json()["handle"]["handle"]
    numbering_map = command("map_residue_numbering", {"structure": prepared, "pdb_id": "1MQ4",
                                                      "chains": [{"chain_auth": "A"}]}).json()["handle"]["handle"]
    contacts = command("compute_interactions", {"structure": prepared, "ligand": ADP}).json()["handle"]["handle"]
    ok = command(TOOL, {"numbering_map": numbering_map, "contacts": contacts})
    assert ok.status_code == 200 and ok.json()["handle"]["kind"] == "reference_site_annotation"
    handle = ok.json()["handle"]["handle"]
    bare = command(TOOL, {"numbering_map": numbering_map}).json()["handle"]["handle"]
    bad = command(TOOL, {"numbering_map": structure})
    assert bad.status_code == 422 and bad.json()["detail"]["reason_code"] == "numbering_map_invalid"
    events_before = client.get(f"/runs/{rid}/events", params={"limit": 500}).json()
    listing = client.get(f"/runs/{rid}/site_annotations").json()
    assert listing["schema"] == "reference_site_annotation_list@1" and listing["total"] == 2
    assert [r["handle"] for r in listing["rows"]] == [bare, handle]            # newest first
    row = listing["rows"][1]
    assert row["structure"] == prepared and row["numbering_map"] == numbering_map and row["contacts"] == contacts
    assert row["ligand"] == ADP_7 and row["counts"] == {"annotated": 10, "absent": 0}
    assert row["stale_snapshot"] is False and listing["rows"][0]["contacts"] is None
    assert client.get(f"/runs/{rid}/site_annotations", params={"structure": structure}).json()["total"] == 0
    assert client.get(f"/runs/{rid}/site_annotations", params={"structure": prepared}).json()["total"] == 2
    paged = client.get(f"/runs/{rid}/site_annotations", params={"offset": 1, "limit": 1}).json()
    assert [r["handle"] for r in paged["rows"]] == [handle] and paged["total"] == 2
    assert client.get(f"/runs/{rid}/site_annotations", params={"bogus": 1}).status_code == 422
    assert client.get(f"/runs/{rid}/site_annotations", params={"limit": 101}).status_code == 422
    detail = client.get(f"/runs/{rid}/site_annotations/detail", params={"handle": handle})
    assert detail.status_code == 200 and detail.json()["annotation"] == appmod._run(rid).store.load(handle)
    assert detail.json()["meta"]["kind"] == "reference_site_annotation"
    assert client.get(f"/runs/{rid}/site_annotations/detail",
                      params={"handle": numbering_map}).status_code == 422
    assert client.get(f"/runs/{rid}/site_annotations/detail",
                      params={"handle": handle, "x": 1}).status_code == 422
    assert client.get(f"/runs/{rid}/events", params={"limit": 500}).json() == events_before
