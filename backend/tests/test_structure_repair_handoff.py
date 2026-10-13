"""M29 T7: the M20 hand-off of original-structure reference results to a repaired structure and ``modeled_basis``
(spec .dryforge/spec.md 5.3, 5.4).

Inputs (every one labelled):

* 8VF6 (public fixture) repaired with the PDBFixer-measured additions (T1 (j), copied by T3a) through T4's splice
  builder. The repaired objects are stored in the spec order (coordinates -> record -> manifest -> structure), as
  T4's origin test does; T5 owns the product publication path.
* An M15 reference FIXTURE set: the M15 fixture rows plus verbatim 8VF6 / STK33 / Q9BYT3 rows
  (``fixtures/structure_repair/reference-8vf6/provenance.json``), so the numbering map and annotation of the original
  8VF6 are made by the product tools without ``.deps``.
* 1MQ4 (a two-residue gap, side chains, OXT) and 1RNH (three MSE, OXT) with their measured additions, and a LABELLED
  SYNTHETIC M26 reaction reference set whose two M-CSA entries (made-up PDB IDs 0SY9 and 0SZ0) name 1MQ4 A274 Asp
  (observed) and A286 Arg (a gap residue), and 1RNH A10 Asp and A47 Met (an MSE residue in the original).
* SYNTHETIC edits made at test time from public fixtures (source names start with ``SYNTHETIC``, a comment line in the
  file says so): 1CLL without the A20 Asp CG / OD1 / OD2 (a calcium contact) and 4INS without the A6 Cys SG (a
  disulfide). Their additions are the removed atoms' own file coordinates. And 1HSG renumbered to model number 2 with
  insertion code "A" on A99 (``SYNTHETIC-1hsg-model2-a99-icode.cif``), its measured OXT additions renamed to match.
* Fault injections (labelled): a repaired structure carrying the original coordinates under a well-formed link, a
  set content stored with that structure, and the installed template made unavailable (``structure_repair._templates``
  monkeypatched to raise ``openmm_unavailable``).
* fpocket (``.deps/fpocket``) for the pocket hand-off: that test FAILS, never skips, when fpocket is missing.

Expected values come from the input files (gemmi + numpy here, independent of ``mutation_handoff``) or from the M20
result the product tool made on the original structure.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import gemmi
import m20_catalytic_fixture as CF
import numpy as np
import pytest
import reaction_fixture as RF
from fastapi.testclient import TestClient
from reference_fixture_set import FIXTURES as M15_FIXTURES
from reference_fixture_set import build_fixture_set

from mw import mutation_candidates as mc
from mw import mutation_handoff as mh
from mw import mutation_reads, pocket_bundle
from mw import reaction_knowledge_constants as RKC
from mw import reference_snapshots as rs
from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw.api import app as api_module
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse, structure_residues
from mw.workspace import new_run

TESTS = Path(__file__).resolve().parent
FIX = TESTS / "fixtures"
SR_FIX = FIX / "structure_repair"
REF_8VF6 = SR_FIX / "reference-8vf6"
MW = TESTS.parent / "mw"
RID = "run_m29_t7_handoff"
TOOL = "generate_mutation_candidates"
LIG_8VF6 = {"model_number": 1, "chain_auth": "A", "seq_auth": 600, "icode": "", "resname": "A1AAY"}
KLIFS_SEVEN = ["A145/LYS", "A192/MET", "A193/GLU", "A194/LEU", "A195/CYS", "A264/THR", "A265/ASP"]
DETAIL_KEYS = {"schema", "handle", "result", "total_positions", "total_candidates", "catalytic_status"}
METALS = {"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K"}
SO2 = {"id": "SO2", "text": "이 위치·보호 판정에는 모델링 원자 또는 잔기가 들어 있다."}
SO3 = {"id": "SO3", "text": "번호 대응·참조 주석·촉매 연결·포켓 결과는 보완 전 원본 구조에서 만든 것이며 잔기 식별자 일치로 "
                            "이었다. 모델링한 잔기는 검사하지 않았다."}


def res(chain: str, seq: int, name: str, *, model: int = 1, icode: str = "") -> dict:
    return {"model_number": model, "chain_auth": chain, "seq_auth": seq, "icode": icode, "resname": name}


def short(residue: dict) -> str:
    return f"{residue['chain_auth']}{residue['seq_auth']}/{residue['resname']}"


def args(structure, *, shell=None, residues=(), ligand=None, pocket=None, **extra) -> dict:
    out = {"structure": structure, "sources": {"pocket": pocket, "ligand_shell": shell, "residues": list(residues)},
           **extra}
    if ligand is not None:
        out["ligand"] = ligand
    return out


# --- building the world (product tools for every result; the repaired objects as T4 stores them) ---------------------

def _prepared(run, raw: bytes, name: str, waters: str = "strip_all") -> str:
    source = run.call("load_structure", {"source": name, "model_index": 0}, source_bytes=raw, source_format="cif")
    return run.call("prepare_structure", {"structure": source.handle, "altloc": "highest_occupancy",
                                          "waters": waters, "hydrogens": "strip", "missing_residues": "leave_gaps",
                                          "symmetry_mates": "ignore"}).handle


def _store_repaired(run, prepared: str, additions: list[dict]) -> dict:
    store = run.store
    inputs = sr.load_inputs(store, prepared)
    raw, record = sr.build_repaired(inputs, additions)
    coordinates = store.put(K.COORDINATES_KIND, K.COORDINATES_SCHEMA, raw, fmt=K.COORDINATES_FMT,
                            produced_by="test").handle
    record_handle = store.put(K.KIND, K.SCHEMA, record, produced_by="test").handle
    original = store.load(prepared)
    manifest = {**store.load(original["manifest"]),
                "missing_residues": K.MISSING_RESIDUES_FILLED if record["gaps"] else K.MISSING_RESIDUES_LEFT,
                K.MANIFEST_REPAIR_KEY: {"record": record_handle, "source": prepared}}
    manifest_handle = store.put(K.MANIFEST_KIND, K.MANIFEST_SCHEMA, manifest, produced_by="test").handle
    structure = store.put(K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, {
        "coordinates": coordinates, "manifest": manifest_handle, "model_index": original["model_index"],
        "model_number": original["model_number"]}, produced_by="test").handle
    return {"structure": structure, "record": record, "record_handle": record_handle, "raw": raw,
            "manifest": manifest, "source": prepared}


def _measured(name: str) -> list[dict]:
    return json.loads((SR_FIX / f"{name}-additions.pdbfixer-measured.json").read_text())["added_atoms"]


def _synthetic_edit(name: str, chain: str, seq: int, atoms: set[str]) -> tuple[bytes, list[dict]]:
    """SYNTHETIC: the public fixture without ``atoms`` of one residue, and those atoms (file coordinates)."""
    doc = gemmi.cif.read_string((FIX / f"public_{name}.cif").read_text())
    table = doc.sole_block().find("_atom_site.", ["auth_asym_id", "auth_seq_id", "label_atom_id", "type_symbol",
                                                  "Cartn_x", "Cartn_y", "Cartn_z"])
    removed = []
    for index in range(len(table) - 1, -1, -1):
        row = table[index]
        if row[0] == chain and row[1] == str(seq) and row[2] in atoms:
            removed.append({"atom_name": row[2], "element": row[3],
                            "coordinates_A": [float(row[i]) for i in (4, 5, 6)]})
            table.remove_row(index)
    assert sorted(item["atom_name"] for item in removed) == sorted(atoms)
    head, rest = doc.as_string().split("\n", 1)
    note = f"# SYNTHETIC TEST INPUT (M29 T7): public {name.upper()} without {chain}{seq} {sorted(atoms)}; not an " \
           "experimental structure\n"
    return (head + "\n" + note + rest).encode(), removed[::-1]


def _synthetic_model2_icode() -> bytes:
    """SYNTHETIC: public 1HSG with every atom in model number 2 and insertion code "A" on chain A residue 99."""
    doc = gemmi.cif.read_string((FIX / "public_1hsg.cif").read_text())
    table = doc.sole_block().find("_atom_site.", ["auth_asym_id", "auth_seq_id", "pdbx_PDB_ins_code",
                                                  "pdbx_PDB_model_num"])
    for index in range(len(table)):
        row = table[index]
        row[3] = "2"
        if (row[0], row[1]) == ("A", "99"):
            row[2] = "A"
    head, rest = doc.as_string().split("\n", 1)
    note = "# SYNTHETIC TEST INPUT (M29 T7): public 1HSG renumbered to model 2 with insertion code A on A99; not an " \
           "experimental structure\n"
    return (head + "\n" + note + rest).encode()


def _seven(store, prepared: str, chain: str, seq: int) -> dict:
    """The 7-field identity of one residue, read from the prepared bytes with gemmi."""
    raw = store.load(store.load(prepared)["coordinates"]).decode()
    model = gemmi.make_structure_from_block(gemmi.cif.read_string(raw).sole_block())[0]
    for ch in model:
        for residue in ch:
            if ch.name == chain and residue.seqid.num == seq:
                return {"model_number": model.num, "chain_auth": ch.name, "chain_label": residue.subchain or None,
                        "seq_auth": seq, "seq_label": residue.label_seq, "icode": residue.seqid.icode.strip(),
                        "resname": residue.name}
    raise AssertionError((chain, seq))


def _m15_set(root: Path) -> None:
    def plus(base: str, extra: str) -> bytes:
        return (M15_FIXTURES / base).read_bytes() + (REF_8VF6 / extra).read_bytes()
    build_fixture_set(root, replace={
        ("sifts", "residues.jsonl"): plus("sifts/residues_fixture.jsonl", "sifts_residues_8vf6.jsonl"),
        ("sifts", "segments.jsonl"): plus("sifts/segments_fixture.jsonl", "sifts_segments_8vf6.jsonl"),
        ("klifs", "kinases.jsonl"): plus("klifs/kinases_fixture.jsonl", "klifs_kinases_stk33.jsonl"),
        ("uniprot", "entries.jsonl"): plus("uniprot/entries_fixture.jsonl", "uniprot_entries_q9byt3.jsonl")})


def _mcsa_entry(mcsa_id: int, pdb_id: str, residues: list[tuple[str, int, bool]]) -> dict:
    """A LABELLED SYNTHETIC M-CSA entry in the shape of the M26 t6 fixture rows (made-up PDB ID)."""
    template = json.loads((FIX / "reaction" / "t6" / "mcsa_entries_0sy6.json").read_text())[0]
    rows = []
    for code, number, reference in residues:
        row = copy.deepcopy(template["residues"][1])
        row["roles_summary"] = f"SYNTHETIC fixture roles summary {mcsa_id} ({code} A{number})"
        row["roles"][0]["function"] = f"SYNTHETIC fixture function text {mcsa_id} ({code} A{number})"
        row["residue_chains"] = [{"pdb_id": pdb_id.lower(), "chain_name": "A", "assembly_chain_name": "A",
                                  "assembly": 1, "code": code, "resid": number, "auth_resid": number,
                                  "is_reference": reference}]
        row["residue_sequences"] = [{"uniprot_id": "Q0SYN1", "code": code, "is_reference": True}]
        rows.append(row)
    return {**copy.deepcopy(template), "mcsa_id": mcsa_id, "enzyme_name": f"SYNTHETIC fixture enzyme m29 t7 {mcsa_id}",
            "residues": rows}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("m29_t7_handoff")
    root = base / "runs"
    w: dict = {"root": root}
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(rs.ENV_VAR, str(base / "reference"))
        (base / "reference").mkdir()
        _m15_set(base / "reference")
        reaction = base / "reaction"
        (reaction / "sets").mkdir(parents=True)
        patch.setenv(RKC.ENV_VAR, str(reaction))
        CF.reset_caches()
        rows = RF.synthetic_rows()
        rows["mcsa"] = [_mcsa_entry(609, "0SY9", [("Asp", 274, True), ("Arg", 286, False)]),
                        _mcsa_entry(610, "0SZ0", [("Asp", 10, True), ("Met", 47, False)])]
        RF.build_set(reaction, rows=rows)
        run = new_run(root, dry_run=False, run_id=RID)
        w["run"] = run
        store = run.store
        # 8VF6: original results, then the repaired structure
        raw8 = (FIX / "public_8vf6.cif").read_bytes()
        p8 = _prepared(run, raw8, "8vf6.cif")
        w["p8"], w["p8_keep"] = p8, _prepared(run, raw8, "8vf6.cif", "keep_all")
        chains = [{"chain_auth": c, "uniprot_accession": "Q9BYT3"} for c in ("A", "B")]
        w["nm8"] = run.call("map_residue_numbering", {"structure": p8, "pdb_id": "8VF6", "chains": chains}).handle
        w["ann8"] = run.call("annotate_reference_sites", {"numbering_map": w["nm8"]}).handle
        w["nm8_keep"] = run.call("map_residue_numbering", {"structure": w["p8_keep"], "pdb_id": "8VF6",
                                                           "chains": chains}).handle
        w["r8"] = _store_repaired(run, p8, _measured("8vf6"))
        refs = {"numbering_map": w["nm8"], "annotation": w["ann8"]}
        w["s1_args"] = args(p8, shell={"radius_A": 5.0}, ligand=LIG_8VF6, **refs)
        w["s1_orig"] = run.call(TOOL, w["s1_args"]).handle
        w["s1_rep"] = run.call(TOOL, {**w["s1_args"], "structure": w["r8"]["structure"]}).handle
        added = _measured("8vf6")
        side = next(a["residue"] for a in added if a["origin"] == "side_chain")
        oxt = next(a["residue"] for a in added if a["origin"] == "oxt")
        gap = next(a["residue"] for a in added if a["origin"] == "gap_residue" and a["residue"]["seq_auth"] == 280)
        w["s2_user"] = (side, oxt, gap)
        w["s2_orig"] = run.call(TOOL, args(p8, shell={"radius_A": 12.0}, ligand=LIG_8VF6, residues=[side, oxt],
                                           **refs)).handle
        w["s2_args"] = args(w["r8"]["structure"], shell={"radius_A": 12.0}, ligand=LIG_8VF6,
                            residues=[side, oxt, gap], **refs)
        w["s2_rep"] = run.call(TOOL, w["s2_args"]).handle
        # user protection and release (A100 has a modeled side chain; A145 is a KLIFS key site)
        user = {"residues": [res("A", 100, "LYS"), res("A", 145, "LYS"), res("A", 150, "GLU")],
                "protected_residues": [res("A", 100, "LYS"), res("A", 150, "GLU")],
                "released_residues": [res("A", 145, "LYS")], **refs}
        w["prot_orig"] = run.call(TOOL, args(p8, **user)).handle
        w["prot_rep"] = run.call(TOOL, args(w["r8"]["structure"], **user)).handle
        # 1MQ4: the M15 fixture map (a third structure for 8VF6) and the catalytic hand-off
        p_mq = _prepared(run, (FIX / "public_1mq4.cif").read_bytes(), "1mq4.cif")
        w["p_mq"], w["r_mq"] = p_mq, _store_repaired(run, p_mq, _measured("1mq4"))
        w["nm_mq"] = run.call("map_residue_numbering", {"structure": p_mq, "pdb_id": "1MQ4",
                                                        "chains": [{"chain_auth": "A"}]}).handle
        link = {"chains": [{"chain_auth": "A", "uniprot_accession": None}], "numbering_map": None}
        w["cat_mq"] = run.call("link_reaction_knowledge", {"structure": p_mq, "pdb_id": "0SY9", **link}).handle
        user_mq = [res("A", 274, "ASP"), res("A", 286, "ARG"), res("A", 126, "ARG")]
        w["mq_orig"] = run.call(TOOL, args(p_mq, residues=[user_mq[0], user_mq[2]],
                                           catalytic_annotation=w["cat_mq"])).handle
        w["mq_rep"] = run.call(TOOL, args(w["r_mq"]["structure"], residues=user_mq,
                                          catalytic_annotation=w["cat_mq"])).handle
        # 1RNH: three MSE residues become MET
        p_rnh = _prepared(run, (FIX / "public_1rnh.cif").read_bytes(), "1rnh.cif")
        w["p_rnh"], w["r_rnh"] = p_rnh, _store_repaired(run, p_rnh, _measured("1rnh"))
        w["cat_rnh"] = run.call("link_reaction_knowledge", {"structure": p_rnh, "pdb_id": "0SZ0", **link}).handle
        w["rnh_rep"] = run.call(TOOL, args(w["r_rnh"]["structure"], residues=[
            res("A", 10, "ASP"), res("A", 47, "MET"), res("A", 152, "GLN")], catalytic_annotation=w["cat_rnh"])).handle
        CF.reset_caches()
        # SYNTHETIC 1CLL (metal) and 4INS (disulfide) edits
        for key, name, chain, seq, atoms, extra in (("cll", "1cll", "A", 20, {"CG", "OD1", "OD2"}, _measured("1cll")),
                                                    ("ins", "4ins", "A", 6, {"SG"}, [])):
            raw, removed = _synthetic_edit(name, chain, seq, atoms)
            prepared = _prepared(run, raw, f"SYNTHETIC-{name}-{chain}{seq}-atoms-removed.cif")
            residue = _seven(store, prepared, chain, seq)
            additions = extra + [{"residue": residue, "origin": "side_chain", **atom} for atom in removed]
            w[f"p_{key}"], w[f"r_{key}"] = prepared, _store_repaired(run, prepared, additions)
        w["cll_user"] = [res("A", 20, "ASP"), res("A", 22, "ASP"), res("A", 4, "LEU"), res("A", 26, "THR")]
        w["cll_orig"] = run.call(TOOL, args(w["p_cll"], residues=w["cll_user"])).handle
        w["cll_rep"] = run.call(TOOL, args(w["r_cll"]["structure"], residues=w["cll_user"])).handle
        w["ins_user"] = [res("A", 6, "CYS"), res("A", 7, "CYS"), res("A", 11, "CYS"), res("B", 7, "CYS")]
        w["ins_orig"] = run.call(TOOL, args(w["p_ins"], residues=w["ins_user"])).handle
        w["ins_rep"] = run.call(TOOL, args(w["r_ins"]["structure"], residues=w["ins_user"])).handle
        # SYNTHETIC 1HSG: model number 2 and insertion code "A" on A99 (the C-terminal residue that gets an OXT)
        raw = _synthetic_model2_icode()
        w["p_hsg"] = _prepared(run, raw, "SYNTHETIC-1hsg-model2-a99-icode.cif")
        additions = copy.deepcopy(_measured("1hsg"))
        for atom in additions:
            atom["residue"]["model_number"] = 2
            atom["residue"]["icode"] = "A" if atom["residue"]["chain_auth"] == "A" else ""
        w["r_hsg"] = _store_repaired(run, w["p_hsg"], additions)
        w["hsg_user"] = [res("A", 99, "PHE", model=2, icode="A"), res("A", 25, "ASP", model=2),
                         res("B", 25, "ASP", model=2), res("B", 99, "PHE", model=2)]
        hsg = {"residues": w["hsg_user"], "protected_residues": [w["hsg_user"][0], w["hsg_user"][1]]}
        w["hsg_orig"] = run.call(TOOL, args(w["p_hsg"], **hsg)).handle
        w["hsg_rep"] = run.call(TOOL, args(w["r_hsg"]["structure"], **hsg)).handle
    return w


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _load(world, name):
    return world["run"].store.load(world[name])


def _page(world, handle, **filters):
    params = {"status": None, "source": None, "exclusion_reason": None, "chain_auth": None, "sort": "order",
              "offset": 0, "limit": 100, **filters}
    return mutation_reads.position_page(world["run"], handle, **params)


def _excluded(content, reason):
    return [short(p["residue"]) for p in content["positions"] if reason in p["exclusion_reasons"]]


# --- independent expected modeled_basis (gemmi + numpy over the repaired bytes) --------------------------------------

def _independent(raw: bytes, content: dict) -> list[set[str]]:
    """Per stored position: the reasons of spec 5.4 recomputed from the repaired mmCIF (``calc_flag`` = modeled)."""
    model = gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())[0]
    residues = {}
    for chain in model:
        for residue in chain:
            key = (chain.name, residue.seqid.num, residue.seqid.icode.strip(), residue.subchain or None,
                   residue.label_seq, residue.name)
            atoms = [(a.name, a.element.name, np.array([a.pos.x, a.pos.y, a.pos.z]),
                      a.calc_flag == gemmi.CalcFlag.Calculated) for a in residue]
            residues[key] = {"atoms": atoms, "polymer": residue.het_flag == "A",
                             "metal": residue.het_flag == "H" and not residue.is_water() and residue.name in METALS}

    def key_of(ref):
        return (ref["chain_auth"], ref["seq_auth"], ref["icode"], ref["chain_label"], ref["seq_label"], ref["resname"])

    def heavy(key, observed):
        return [p for name, el, p, calc in residues[key]["atoms"] if el not in ("H", "D") and not (observed and calc)]

    def dmin(a, b):
        return min(float(np.linalg.norm(x - y)) for x in a for y in b)

    parameters = content["parameters"]
    ligand = key_of(parameters["ligand"]) if parameters["ligand"] else None
    shell = parameters["sources"]["ligand_shell"]
    metals = [key for key, item in residues.items() if item["metal"]]
    cys = [key for key, item in residues.items() if item["polymer"] and key[5] in ("CYS", "CYX")]

    def sg(key, observed):
        return [p for name, el, p, calc in residues[key]["atoms"] if name == "SG" and el not in ("H", "D")
                and not (observed and calc)]

    def judge(key, observed):
        own = heavy(key, observed)
        in_shell = bool(shell and own and dmin(own, heavy(ligand, observed)) <= shell["radius_A"])
        metal = None
        if metals and own:
            distances = [dmin(own, [p for _n, _e, p, _c in residues[m]["atoms"]]) for m in metals]
            if min(distances) <= parameters["metal_contact_A"]:
                metal = (min(distances), metals[distances.index(min(distances))])
        partner = None
        if key[5] in ("CYS", "CYX") and sg(key, observed):
            others = [(dmin(sg(key, observed), sg(c, observed)), c) for c in cys if c != key and sg(c, observed)]
            if others and min(others)[0] <= 2.5:
                partner = min(others)[1]
        return in_shell, metal, partner

    out = []
    for position in content["positions"]:
        key = key_of(position["residue"])
        found = {"modeled_atoms"} if any(calc for *_rest, calc in residues[key]["atoms"]) else set()
        for name, a, b in zip(("ligand_shell", "metal_contact", "disulfide"), judge(key, False), judge(key, True),
                              strict=True):
            if a != b:
                found.add(name)
        out.append(found)
    return out


def _check_basis(world, set_name, repaired) -> list[set[str]]:
    content = _load(world, set_name)
    expected = _independent(repaired["raw"], content)
    st = _parse(ToolContext(store=world["run"].store, call_id="test"), repaired["structure"])
    assert [set(item) for item in mh.basis_reasons(st, repaired["record"], content)] == expected
    rows = _page(world, world[set_name])["rows"]
    assert [row["modeled_basis"] for row in rows] == [bool(item) for item in expected]
    return expected


# --- 8VF6: the KLIFS key-site protection survives; modeled residues read as not checked ------------------------------

def test_8vf6_keeps_the_seven_klifs_key_site_exclusions_of_the_original(world):
    original, repaired = _load(world, "s1_orig"), _load(world, "s1_rep")
    assert _excluded(original, "klifs_key_site") == KLIFS_SEVEN == _excluded(repaired, "klifs_key_site")
    assert [(short(p["residue"]), p["exclusion_reasons"], p["protection"]) for p in repaired["positions"]] == \
           [(short(p["residue"]), p["exclusion_reasons"], p["protection"]) for p in original["positions"]]
    assert (repaired["counts"]["positions"], repaired["counts"]["candidates"]) == (20, 247)
    assert repaired["counts"]["candidates"] == original["counts"]["candidates"]
    assert repaired["structure"]["handle"] == world["r8"]["structure"]
    assert repaired["parameters"]["numbering_map"] == world["nm8"]   # the original structure's map, as given
    page = _page(world, world["s1_rep"])
    assert page["repair_handoff"] == {"references": ["numbering_map", "annotation"], "statements": [SO3]}
    assert all(row["modeled_basis"] is False and row["reference_not_checked"] == [] for row in page["rows"])
    _check_basis(world, "s1_rep", world["r8"])


def test_the_stored_repaired_set_is_what_m20_builds_and_validates(world):
    store = world["run"].store
    structure = world["r8"]["structure"]
    for name, call in (("s1_rep", {**world["s1_args"], "structure": structure}), ("s2_rep", world["s2_args"])):
        listing = structure_residues(store, structure)
        params = mc.normalize_request(call, listing["residues"], listing["ligands"])
        built = mc.build_candidate_set(structure, _parse(ToolContext(store=store, call_id="test"), structure), params,
                                       numbering_content=store.load(world["nm8"]),
                                       annotation_content=store.load(world["ann8"]))
        stored = store.load(world[name])
        assert canonical_json(stored) == canonical_json(built)
        assert mc.validated_set(stored) is stored


def test_8vf6_modeled_atoms_add_positions_only_with_modeled_basis(world):
    original, repaired = _load(world, "s2_orig"), _load(world, "s2_rep")
    expected = _check_basis(world, "s2_rep", world["r8"])
    by_original = {short(p["residue"]): p for p in original["positions"]}
    rows = _page(world, world["s2_rep"])["rows"]
    added = []
    for row, reasons in zip(rows, expected, strict=True):
        before = by_original.get(short(row["residue"]))
        if before is None:
            added.append(short(row["residue"]))
            assert row["modeled_basis"] is True
            continue
        assert set(before["protection"]["reasons"]) <= set(row["protection"]["reasons"])   # nothing lost
        if (before["protection"], before["sources"]) != (row["protection"], row["sources"]):
            assert row["modeled_basis"] is True, short(row["residue"])
        assert row["modeled_basis"] is bool(reasons)
    # the gap residue the user named and the gap residues the modeled atoms put in the 12 A shell
    assert added == ["A280/LEU", "B283/THR", "B284/CYS"]
    assert _excluded(repaired, "klifs_key_site") == _excluded(original, "klifs_key_site")
    gap_keys = {(r["chain_auth"], r["seq_auth"]) for g in world["r8"]["record"]["gaps"] for r in g["residues"]}
    for row in rows:
        if (row["residue"]["chain_auth"], row["residue"]["seq_auth"]) in gap_keys:
            assert row["numbering"]["status"] == "not_in_map" and row["protection"]["klifs_sites"] == []
            assert row["protection"]["catalytic"] is None   # stored "checked, none" / not given, never changed
            assert row["reference_not_checked"] == ["numbering", "klifs_sites"]
        else:
            assert row["reference_not_checked"] == []
    flagged = {short(row["residue"]) for row in rows if row["modeled_basis"]}
    side, oxt, _gap = world["s2_user"]
    assert {short(side), short(oxt), "A280/LEU", "B283/THR", "B284/CYS"} <= flagged
    page = _page(world, world["s2_rep"])
    assert page["repair_handoff"] == {"references": ["numbering_map", "annotation"], "statements": [SO2, SO3]}


def test_reads_and_routes_add_fields_only_for_a_repaired_structure(world, client):
    store = world["run"].store
    for name in ("s1_orig", "s2_orig", "mq_orig", "cll_orig", "ins_orig"):
        content = _load(world, name)
        detail = mutation_reads.set_detail(world["run"], world[name])
        assert set(detail) == DETAIL_KEYS
        page = _page(world, world[name])
        assert "repair_handoff" not in page and page["rows"] == content["positions"][:100]
        assert mutation_reads.repair_view(world["run"], content) is None
    for name in ("s2_rep", "mq_rep", "rnh_rep", "cll_rep", "ins_rep"):
        detail = mutation_reads.set_detail(world["run"], world[name])
        assert set(detail) == DETAIL_KEYS | {"repair_handoff", "structure_origin"}   # M29 T8b adds structure_origin
        page = _page(world, world[name])
        stored = store.load(world[name])["positions"]
        assert [{k: v for k, v in row.items() if k not in ("modeled_basis", "reference_not_checked")}
                for row in page["rows"]] == stored[:100]
        assert detail["repair_handoff"] == page["repair_handoff"]
        assert detail["structure_origin"] == page["structure_origin"]
    events = (world["root"] / RID / "events.jsonl").read_bytes()
    objects = sorted(p.name for p in (world["root"] / RID).rglob("*") if p.is_file())
    base = f"/runs/{RID}/mutation_candidate_sets/{world['s2_rep']}"
    body = client.get(base).json()
    assert body["repair_handoff"]["statements"] == [SO2, SO3] and body["meta"]["kind"] == "mutation_candidate_set"
    rows = client.get(f"{base}/positions", params={"limit": 100}).json()["rows"]
    assert [row["modeled_basis"] for row in rows] == [row["modeled_basis"] for row in _page(world, world["s2_rep"])
                                                       ["rows"]]
    original = client.get(f"/runs/{RID}/mutation_candidate_sets/{world['s2_orig']}/positions").json()
    assert "repair_handoff" not in original and all("modeled_basis" not in row for row in original["rows"])
    assert (world["root"] / RID / "events.jsonl").read_bytes() == events
    assert sorted(p.name for p in (world["root"] / RID).rglob("*") if p.is_file()) == objects


# --- admission --------------------------------------------------------------------------------------------------------

def _refusal(run, call) -> dict:
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, call)
    assert caught.value.cls.value == "input_invalid"
    return caught.value.detail


def test_results_of_any_other_structure_are_still_refused(world):
    run = world["run"]
    repaired = world["r8"]["structure"]
    lys = [res("A", 145, "LYS")]
    for call in (
            args(repaired, residues=lys, numbering_map=world["nm_mq"]),       # a third structure
            args(repaired, residues=lys, numbering_map=world["nm8_keep"]),    # another original, not repair.source
            args(repaired, residues=lys, numbering_map=world["nm8"], annotation=world["ann8"],
                 catalytic_annotation=world["cat_mq"]),                        # one result of a third structure
            args(world["r_mq"]["structure"], residues=[res("A", 274, "ASP")], catalytic_annotation=world["cat_rnh"]),
            args(world["p8_keep"], residues=lys, numbering_map=world["nm8"]),  # not repaired: unchanged rule
            args(world["p_mq"], residues=[res("A", 274, "ASP")], numbering_map=world["nm8"])):
        assert _refusal(run, call) == {"reason_code": "structure_mismatch"}


def test_a_repaired_structure_whose_record_does_not_validate_is_structure_invalid(world):
    run, store = world["run"], world["run"].store
    good = world["r8"]
    # the link names the coordinates object as its record (malformed link)
    manifest = {**good["manifest"], K.MANIFEST_REPAIR_KEY: {"record": store.load(good["structure"])["coordinates"],
                                                            "source": good["source"]}}
    # the link is well formed but the structure's coordinates are the ORIGINAL ones (the record does not re-derive)
    original_coordinates = store.load(good["source"])["coordinates"]
    broken = []
    for coordinates, link in ((store.load(good["structure"])["coordinates"], manifest),
                              (original_coordinates, good["manifest"])):
        handle = store.put(K.MANIFEST_KIND, K.MANIFEST_SCHEMA, link, produced_by="test").handle
        broken.append(store.put(K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, {
            **store.load(good["structure"]), "coordinates": coordinates, "manifest": handle},
            produced_by="test").handle)
    for structure in broken:
        assert _refusal(run, args(structure, residues=[res("A", 145, "LYS")])) == {"reason_code": "structure_invalid"}
        content = {**_load(world, "s1_rep"), "structure": {**_load(world, "s1_rep")["structure"],
                                                           "handle": structure}}
        with pytest.raises(mutation_reads.MutationEvidenceError):
            mutation_reads.repair_view(world["run"], content)


# --- catalytic, MSE and pocket hand-off ---------------------------------------------------------------------------

def test_catalytic_hand_off_keeps_the_matched_protection_and_marks_the_gap_residue(world):
    original, repaired = _load(world, "mq_orig"), _load(world, "mq_rep")
    by = {short(p["residue"]): p for p in repaired["positions"]}
    asp = next(p for p in original["positions"] if short(p["residue"]) == "A274/ASP")
    assert by["A274/ASP"]["protection"] == asp["protection"] and "catalytic_residue" in asp["protection"]["reasons"]
    assert by["A286/ARG"]["protection"]["catalytic"] == []          # stored "checked, none"
    rows = {short(row["residue"]): row for row in _page(world, world["mq_rep"])["rows"]}
    assert rows["A286/ARG"]["reference_not_checked"] == ["catalytic"] and rows["A286/ARG"]["modeled_basis"] is True
    assert rows["A274/ASP"]["reference_not_checked"] == [] and rows["A126/ARG"]["reference_not_checked"] == []
    assert rows["A126/ARG"]["modeled_basis"] is True                # a modeled side chain
    assert _page(world, world["mq_rep"])["repair_handoff"] == {"references": ["catalytic_annotation"],
                                                                "statements": [SO2, SO3]}
    _check_basis(world, "mq_rep", world["r_mq"])


def test_a_replaced_mse_residue_reads_as_not_checked(world):
    record = world["r_rnh"]["record"]
    assert [short(item["from"]) + ">" + item["to"]["resname"] for item in record["replaced"]] == [
        "A47/MSE>MET", "A50/MSE>MET", "A142/MSE>MET"]
    rows = {short(row["residue"]): row for row in _page(world, world["rnh_rep"])["rows"]}
    assert rows["A47/MET"]["protection"]["catalytic"] == []          # the original M-CSA row named an MSE residue
    assert rows["A47/MET"]["reference_not_checked"] == ["catalytic"]
    assert rows["A47/MET"]["modeled_basis"] is False                 # SD keeps the observed Se coordinates
    assert rows["A10/ASP"]["reference_not_checked"] == [] and "catalytic_residue" in rows["A10/ASP"]["protection"][
        "reasons"]
    assert rows["A152/GLN"]["modeled_basis"] is True                 # OXT
    _check_basis(world, "rnh_rep", world["r_rnh"])


def test_an_mse_residue_in_an_original_pocket_lining_is_pocket_residue_mismatch(world):
    """The known limit (spec 5.3). M12 refuses a structure with MSE (``modified_residue_unsupported``), so a published
    lining never names one; the M20 lining check (the hash file's pure function, as ``_admit`` calls it) is pinned on
    a SYNTHETIC pocket content naming the original A47 MSE. (On the original structure the HETATM MSE is not a
    protein residue for M20 either, so the same lining is refused there too.)"""
    store = world["run"].store
    with pytest.raises(ToolFailure) as caught:
        JobQueue(world["run"]).submit("fpocket_detect_v1", {"structure": world["p_rnh"]}, timeout_s=120)
    assert caught.value.detail["reason_code"] == "modified_residue_unsupported"
    mse = _seven(store, world["p_rnh"], "A", 47)
    pocket = {"pockets": [{"rank": 1, "lining_residues": [mse]}]}   # SYNTHETIC
    for structure in (world["r_rnh"]["structure"], world["p_rnh"]):
        with pytest.raises(mc.MutationInvalid) as refused:
            mc.pocket_lining(pocket, [1], structure_residues(store, structure)["residues"])
        assert refused.value.reason_code == "pocket_residue_mismatch"
    met = _seven(store, world["r_rnh"]["structure"], "A", 47)
    assert (met["resname"], {**met, "resname": "MSE"}) == ("MET", mse)   # the only identity field that changed


def test_pocket_hand_off_with_fpocket(world):
    capability = pocket_bundle.capability()
    assert capability["status"] == "ready", f"fpocket must be installed: {capability}"
    run = world["run"]
    run.approve("expensive_first_call")
    pockets = {}
    for name in ("p_mq", "p8_keep"):
        queue = JobQueue(run)
        job = queue.start(queue.submit("fpocket_detect_v1", {"structure": world[name]}, timeout_s=120)["job_id"])
        assert job["status"] == "done", job
        pockets[name] = job["output_handles"][0]
    repaired = world["r_mq"]["structure"]
    handle = run.call(TOOL, args(repaired, pocket={"pocket_set": pockets["p_mq"], "ranks": [1]})).handle
    content = run.store.load(handle)
    rank_one = next(p for p in run.store.load(pockets["p_mq"])["pockets"] if p["rank"] == 1)
    assert {mc.identity(p["residue"]) for p in content["positions"]} == {mc.identity(r) for r in
                                                                         rank_one["lining_residues"]}
    page = _page(world, handle)
    assert page["repair_handoff"]["references"] == ["pocket_set"] and SO3 in page["repair_handoff"]["statements"]
    gap = {(r["chain_auth"], r["seq_auth"]) for g in world["r_mq"]["record"]["gaps"] for r in g["residues"]}
    assert not {(p["residue"]["chain_auth"], p["residue"]["seq_auth"]) for p in content["positions"]} & gap
    assert _refusal(run, args(repaired, pocket={"pocket_set": pockets["p8_keep"], "ranks": [1]})) == {
        "reason_code": "structure_mismatch"}


# --- modeled_basis re-judgment: metal (SYNTHETIC 1CLL) and disulfide (SYNTHETIC 4INS) ---------------------------------

def test_metal_judgment_on_observed_atoms_only(world):
    expected = _check_basis(world, "cll_rep", world["r_cll"])
    original, repaired = _load(world, "cll_orig"), _load(world, "cll_rep")
    reasons = dict(zip([short(p["residue"]) for p in repaired["positions"]], expected, strict=True))
    assert reasons == {"A4/LEU": {"modeled_atoms"}, "A20/ASP": {"modeled_atoms", "metal_contact"}, "A22/ASP": set(),
                       "A26/THR": set()}
    protection = {short(p["residue"]): p["protection"]["reasons"] for p in repaired["positions"]}
    before = {short(p["residue"]): p["protection"]["reasons"] for p in original["positions"]}
    assert protection["A20/ASP"] == ["metal_contact"] and before["A20/ASP"] == []   # only with the modeled OD1
    assert protection["A22/ASP"] == before["A22/ASP"] == ["metal_contact"]          # observed OD1, kept


def test_disulfide_judgment_on_observed_atoms_only(world):
    expected = _check_basis(world, "ins_rep", world["r_ins"])
    original, repaired = _load(world, "ins_orig"), _load(world, "ins_rep")
    reasons = dict(zip([short(p["residue"]) for p in repaired["positions"]], expected, strict=True))
    # A11 has no modeled atom: its disulfide partner is the modeled A6 SG
    assert reasons == {"A6/CYS": {"modeled_atoms", "disulfide"}, "A7/CYS": set(), "A11/CYS": {"disulfide"},
                       "B7/CYS": set()}
    partner = {short(p["residue"]): p["protection"]["disulfide_partner"] for p in repaired["positions"]}
    before = {short(p["residue"]): p["protection"]["disulfide_partner"] for p in original["positions"]}
    assert short(partner["A11/CYS"]) == "A6/CYS" and before["A11/CYS"] is None
    assert partner["A7/CYS"] == before["A7/CYS"] and short(partner["A7/CYS"]) == "B7/CYS"
    rows = {short(row["residue"]): row for row in _page(world, world["ins_rep"])["rows"]}
    assert rows["A11/CYS"]["modeled_basis"] is True and rows["A11/CYS"]["reference_not_checked"] == []
    assert _page(world, world["ins_rep"])["repair_handoff"] == {"references": [], "statements": [SO2]}


# --- user protection, insertion code and model number ---------------------------------------------------------------

def _rows_by(content):
    return {(short(p["residue"]), p["residue"]["icode"]): p for p in content["positions"]}


def test_user_protected_and_released_residues_are_kept_on_the_repaired_structure(world):
    original, repaired = _load(world, "prot_orig"), _load(world, "prot_rep")
    assert repaired["parameters"]["protected_residues"] == original["parameters"]["protected_residues"]
    assert repaired["released_residues"] == original["released_residues"] == [
        {"residue": repaired["parameters"]["released_residues"][0], "effect": "released"}]
    before, after = _rows_by(original), _rows_by(repaired)
    assert set(before) == set(after)
    for key, position in after.items():
        assert (position["protection"], position["exclusion_reasons"], position["status"]) == (
            before[key]["protection"], before[key]["exclusion_reasons"], before[key]["status"]), key
    assert after[("A100/LYS", "")]["exclusion_reasons"] == ["user_protected"]
    assert after[("A150/GLU", "")]["protection"]["reasons"] == ["user_protected"]
    assert after[("A145/LYS", "")]["protection"]["reasons"] == ["klifs_key_site"]
    released = after[("A145/LYS", "")]
    assert released["protection"]["released"] is True and released["status"] == "candidate"
    rows = {short(row["residue"]): row for row in _page(world, world["prot_rep"])["rows"]}
    assert (rows["A100/LYS"]["modeled_basis"], rows["A150/GLU"]["modeled_basis"]) == (True, False)
    _check_basis(world, "prot_rep", world["r8"])


def test_an_insertion_code_residue_keeps_its_identity_and_protection(world):
    original, repaired = _load(world, "hsg_orig"), _load(world, "hsg_rep")
    a99 = [p for p in repaired["positions"] if (p["residue"]["chain_auth"], p["residue"]["seq_auth"]) == ("A", 99)]
    assert len(a99) == 1 and a99[0]["residue"]["icode"] == "A"
    assert a99[0]["residue"] == next(p["residue"] for p in original["positions"] if p["residue"]["icode"] == "A")
    assert a99[0]["protection"]["reasons"] == ["user_protected"]
    assert [(p["residue"], p["protection"], p["exclusion_reasons"]) for p in repaired["positions"]] == \
           [(p["residue"], p["protection"], p["exclusion_reasons"]) for p in original["positions"]]
    oxt = {(item["residue"]["chain_auth"], item["residue"]["icode"])
           for item in world["r_hsg"]["record"]["added_atoms"]}
    assert oxt == {("A", "A"), ("B", "")}
    rows = {(short(row["residue"]), row["residue"]["icode"]): row for row in _page(world, world["hsg_rep"])["rows"]}
    assert rows[("A99/PHE", "A")]["modeled_basis"] is True and rows[("B99/PHE", "")]["modeled_basis"] is True
    assert rows[("A25/ASP", "")]["modeled_basis"] is False
    _check_basis(world, "hsg_rep", world["r_hsg"])


def test_a_model_number_other_than_1_is_kept_through_the_hand_off(world):
    repaired = _load(world, "hsg_rep")
    assert world["r_hsg"]["record"]["source"]["model_number"] == 2
    assert repaired["structure"]["model_number"] == 2
    assert {p["residue"]["model_number"] for p in repaired["positions"]} == {2}
    assert {item["residue"]["model_number"] for item in world["r_hsg"]["record"]["added_atoms"]} == {2}
    st = _parse(ToolContext(store=world["run"].store, call_id="test"), world["r_hsg"]["structure"])
    assert st[0].num == 2
    assert world["run"].store.load(world["r_hsg"]["structure"])["model_number"] == 2


# --- environment failures are not invalid evidence; the list agrees with the detail ----------------------------------

def _no_template():
    raise sr._unavailable()


def test_an_unavailable_template_is_a_precondition_not_an_invalid_structure(world, client, monkeypatch):
    monkeypatch.setattr(sr, "_templates", _no_template)
    run = world["run"]
    # admission: the precondition passes through (the command route answers 412 precondition)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, {**world["s1_args"], "structure": world["r8"]["structure"]})
    assert (caught.value.cls.value, caught.value.detail) == ("precondition", {"reason_code": "openmm_unavailable"})
    response = client.post(f"/runs/{RID}/commands", json={"tool": TOOL, "args": {
        **world["s1_args"], "structure": world["r8"]["structure"]}})
    assert response.status_code == 412, response.text
    assert response.json()["error"] == "precondition"
    assert response.json()["detail"] == {"reason_code": "openmm_unavailable"}
    # reads of a repaired set: the same precondition, never MutationEvidenceError
    for read in (lambda: mutation_reads.set_detail(run, world["s1_rep"]), lambda: _page(world, world["s1_rep"]),
                 lambda: mutation_reads.list_sets(run, 0, 100)):
        with pytest.raises(ToolFailure) as caught:
            read()
        assert caught.value.cls.value == "precondition"
        assert caught.value.detail == {"reason_code": "openmm_unavailable"}
    # a structure that is not repaired never reads the template: unchanged
    assert run.call(TOOL, world["s1_args"]).handle == world["s1_orig"]
    assert set(mutation_reads.set_detail(run, world["s1_orig"])) == DETAIL_KEYS
    assert "repair_handoff" not in _page(world, world["s1_orig"])


def test_the_list_row_of_a_repaired_set_whose_record_fails_is_invalid_like_the_detail(world):
    run, store = world["run"], world["run"].store
    good = world["r8"]
    # SYNTHETIC fault: a well-formed link whose structure carries the ORIGINAL coordinates (the record cannot re-derive)
    manifest = store.put(K.MANIFEST_KIND, K.MANIFEST_SCHEMA, good["manifest"], produced_by="test").handle
    broken = store.put(K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, {
        **store.load(good["structure"]), "coordinates": store.load(good["source"])["coordinates"],
        "manifest": manifest}, produced_by="test").handle
    forged = copy.deepcopy(_load(world, "s1_rep"))
    forged["structure"]["handle"] = broken
    handle = store.put("mutation_candidate_set", "mutation_candidate_set@1", forged,
                       produced_by="forged_test_set").handle
    assert mc.validated_set(store.load(handle))   # the content alone validates
    rows = {row["handle"]: row for row in mutation_reads.list_sets(run, 0, 100)["rows"]}
    assert rows[handle] == {"handle": handle, "created_seq": rows[handle]["created_seq"], "valid": False,
                            **dict.fromkeys(("structure", "model_number", "ligand", "sources_used", "klifs_status",
                                             "numbering_map", "annotation", "counts", "null_result",
                                             "catalytic_status"))}
    for read in (lambda: mutation_reads.set_detail(run, handle), lambda: _page(world, handle)):
        with pytest.raises(mutation_reads.MutationEvidenceError):
            read()
    for name in ("s1_rep", "s2_rep", "mq_rep", "s1_orig", "cll_orig"):
        assert rows[world[name]]["valid"] is True and rows[world[name]]["counts"] == _load(world, name)["counts"]


# --- module boundary and fixture provenance -------------------------------------------------------------------------

def test_the_8vf6_reference_rows_match_their_provenance():
    provenance = json.loads((REF_8VF6 / "provenance.json").read_text())
    assert "not experimental evidence" in provenance["label"]
    assert sorted(item["file"] for item in provenance["files"]) == sorted(
        p.name for p in REF_8VF6.iterdir() if p.suffix == ".jsonl")
    for item in provenance["files"]:
        raw = (REF_8VF6 / item["file"]).read_bytes()
        assert (hashlib.sha256(raw).hexdigest(), len(raw)) == (item["sha256"], item["bytes"])
        lines = raw.split(b"\n")
        assert lines[-1] == b"" and [hashlib.sha256(line).hexdigest() for line in lines[:-1]] == [
            item["extracted_line_sha256"][key] for key in item["extracted_ids"]]
        assert b"/Users/" not in raw and b"/private/" not in raw




def test_the_hand_off_module_imports_no_network_process_or_engine_module():
    tree = ast.parse((MW / "mutation_handoff.py").read_text(encoding="utf-8"))
    absolute = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    absolute |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                 and node.level == 0}
    assert absolute - {"__future__", "numpy", "gemmi"} <= set(sys.stdlib_module_names) - {
        "socket", "urllib", "http", "ssl", "subprocess", "multiprocessing", "signal", "asyncio"}, absolute
    source = (MW / "mutation_handoff.py").read_text(encoding="utf-8")
    for banned in ("raise_limits", "limit_approval", "subprocess", "import openmm", "from openmm", "pdbfixer",
                   "httpx", ".put(", "events.append", "store.write"):
        assert banned not in source, banned
    assert K.SO2 == SO2["text"] and K.SO3 == SO3["text"]
