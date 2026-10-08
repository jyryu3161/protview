"""M26 pure reaction-knowledge logic (mw.reaction_knowledge): set parsing/index, M-CSA matching (spec 5.3), UniProt
site linking (5.4), reactions (5.5), the ``reaction_knowledge@1`` result (5.6) and ``validated_result``.

Inputs are LABELLED SYNTHETIC fixtures (``fixtures/reaction/t2/``, see SYNTHETIC-PROVENANCE-t2.md): two made-up
structures (``0SY1`` mmCIF, ``0SY2`` PDB), synthetic processed M-CSA / UniProt / Rhea rows and hand-built numbering-map
dicts. The M-CSA expectations come from the independent standard-library oracle ``independent_match.py``
(``expected.json``); the UniProt / reaction expectations below are written by hand from the spec text.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import gemmi
import pytest
import reaction_fixture as RF

from mw import mutation_candidates as mcand
from mw import reaction_knowledge as rk
from mw import reaction_knowledge_constants as K
from mw import reaction_snapshots as rs

T2 = RF.T2
EXPECTED = json.loads((T2 / "expected.json").read_text(encoding="utf-8"))
CASES = EXPECTED["cases"]
HANDLE = "obj://run_t2/prepared_structure/" + "a" * 64
MAP_HANDLE = "obj://run_t2/residue_numbering_map/" + "b" * 64


def parse(name: str):
    """Like ``tools.structural._parse``: gemmi parse, keep the first model only (entity setup not called)."""
    path = T2 / name
    text = path.read_text()
    st = (gemmi.make_structure_from_block(gemmi.cif.read_string(text).sole_block()) if path.suffix == ".cif"
          else gemmi.read_pdb_string(text))
    for index in range(len(st) - 1, 0, -1):
        del st[index]
    return st


def residues_of(name: str) -> dict[str, list[dict]]:
    return rk.chain_polymer_residues(parse(name))


@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    return root


@pytest.fixture
def world(ref):
    RF.build_set(ref)
    return rk.pin_and_index()


# ------------------------------------------------------------------------------------------- oracle

def test_oracle_expected_json_matches_a_fresh_oracle_run():
    out = subprocess.run([sys.executable, str(T2 / "independent_match.py"), "--check"], capture_output=True,
                         text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    source = (T2 / "independent_match.py").read_text()
    assert not re.search(r"^\s*(from|import)\s+(mw|gemmi|numpy)\b", source, re.MULTILINE)
    tree = ast.parse(source)
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names}
    modules |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert modules - {"__future__"} <= set(sys.stdlib_module_names)


@pytest.mark.parametrize("name", sorted(CASES))
def test_chain_residues_follow_the_m15_rule_and_equal_the_oracle(name):
    case = CASES[name]
    got = residues_of(case["structure"])[case["chain_auth"]]
    assert got == case["chain_residues"]
    assert all(list(r) == list(K.RESIDUE_FIELDS) or set(r) == set(K.RESIDUE_FIELDS) for r in got)


@pytest.mark.parametrize("name", sorted(CASES))
def test_mcsa_section_equals_the_oracle(world, name):
    _pinned, index = world
    case = CASES[name]
    residues = residues_of(case["structure"])[case["chain_auth"]]
    got = rk.mcsa_section(index, case["pdb_id"], case["chain_auth"], residues)
    assert got == case["mcsa"]
    assert K.canonical_json(got) == K.canonical_json(case["mcsa"])


def test_oracle_cases_cover_every_status_reason_and_coverage():
    seen = set()
    coverage = set()
    for case in CASES.values():
        section = case["mcsa"]
        coverage.add(section["coverage"] if section["status"] == "checked" else "not_checked")
        for row in section["rows"] or []:
            seen.add((row["status"], row["reason"]))
    assert coverage == {"covered", "chain_not_listed", "pdb_not_in_snapshot", "not_checked"}
    assert seen == ({("matched", None)} | {("unmatched", r) for r in K.UNMATCHED_REASONS}
                    | {("conflict", r) for r in K.CONFLICT_REASONS})


def _row(section, mcsa_id, residue_index, auth_resid="any"):
    rows = [r for r in section["rows"] if r["mcsa_id"] == mcsa_id and r["residue_index"] == residue_index
            and (auth_resid == "any" or r["listed"]["auth_resid"] == auth_resid)]
    assert len(rows) == 1
    return rows[0]


def test_matching_details_spelled_out(world):
    _pinned, index = world
    section = rk.mcsa_section(index, "0SY1", "A", residues_of("structure_alpha.cif")["A"])
    # several M-CSA entries on one chain: all shown, none chosen
    assert [e["mcsa_id"] for e in section["entries"]] == [101, 102]
    # mcsa_rows_disagree comes first: before no_author_number and non_standard_code (Sec/Cys, auth_resid null)
    row = _row(section, 101, 12)
    assert (row["status"], row["reason"], row["listed"]["code"], row["listed"]["auth_resid"]) == (
        "conflict", "mcsa_rows_disagree", "Cys/Sec", None)
    assert row["residue"] is None and row["structure_resname"] is None
    # grouping: assemblies are the distinct non-null values, is_reference is any(), first member's resid
    row = _row(section, 101, 11)
    assert (row["listed"]["assemblies"], row["is_reference"], row["listed"]["resid"]) == ([1, 2], True, 33)
    row = _row(section, 101, 13)
    assert (row["status"], row["listed"]["assemblies"], row["is_reference"], row["listed"]["resid"]) == (
        "matched", [3], False, 35)
    # one residue, two author numbers: two rows, the null number last
    assert [r["listed"]["auth_resid"] for r in section["rows"] if r["mcsa_id"] == 101
            and r["residue_index"] == 16] == [50, None]
    # the LIG ligand numbered 10 is not a chain residue, so ASP 10 is matched (not ambiguous)
    assert _row(section, 101, 0)["status"] == "matched"
    # insertion code: the found residue is carried
    row = _row(section, 101, 3)
    assert row["residue"]["icode"] == "A" and row["structure_resname"] == "SER"
    # the M12 names are mapped through the M20 function
    mapped = {r["structure_resname"] for r in section["rows"] if r["status"] == "matched"}
    assert {"HID", "HIE", "HIP", "HSD", "HSE", "HSP", "CYX", "ASH", "GLH", "LYN"} <= mapped
    # a non-standard structure name (MSE, UNK) is a conflict, not a match
    assert _row(section, 101, 4)["reason"] == "residue_name_differs"
    assert _row(section, 101, 17)["reason"] == "residue_name_differs"
    # role text is verbatim; an empty roles list becomes null, an empty summary stays ""
    assert _row(section, 101, 1)["reference"] == {"roles_summary": "", "function_location_abv": "", "ptm": "",
                                                  "roles": None}
    assert _row(section, 101, 0)["reference"]["roles"] == RF.synthetic_rows()["mcsa"][0]["residues"][0]["roles"]


def test_null_labels_survive(world):
    _pinned, index = world
    section = rk.mcsa_section(index, "0SY2", "A", residues_of("structure_beta.pdb")["A"])
    residue = _row(section, 103, 0)["residue"]
    assert residue["chain_label"] is None and residue["seq_label"] is None and residue["icode"] == ""


def test_standard_name_is_the_m20_function():
    assert rk.standard_name is mcand.standard_name


# ------------------------------------------------------------------------------------------- index & cache

def test_index_lookups_and_pdb_entries(world):
    pinned, index = world
    assert index.set_hash == pinned.set_hash
    assert sorted(index.mcsa) == [101, 102, 103, 104]
    assert index.mcsa_by_pdb == {"0sy1": (101, 102), "0sy2": (101, 103), "0sy3": (104,)}
    assert sorted(index.uniprot) == ["P0SYN3", "Q0SYN1", "Q0SYN2", "Q0SYN5"]
    assert list(index.rhea) == ["RHEA:800", "RHEA:10000", "RHEA:9000010", "RHEA:9000020", "RHEA:90000300"]
    assert index.skipped["Q0SYN4"] == {"reason": "merged", "target_accessions": ["Q0SYN9"]}
    assert rk.pdb_entries(index, "0SY1") == [
        {"mcsa_id": 101, "enzyme_name": "SYNTHETIC fixture enzyme alpha", "reference_uniprot_id": "Q0SYN1",
         "chains": ["A", "a"]},
        {"mcsa_id": 102, "enzyme_name": "SYNTHETIC fixture enzyme beta", "reference_uniprot_id": "Q0SYN2, P0SYN3",
         "chains": ["A"]}]
    assert rk.pdb_entries(index, "0sy3")[0]["chains"] == ["A", "B"]
    assert rk.pdb_entries(index, "0SY9") == []


def test_index_is_built_once_per_set_and_keeps_one_set(ref, monkeypatch):
    first = RF.build_set(ref)
    calls = []
    real = K.decode_jsonl

    def counting(source, data):
        calls.append(source)
        return real(source, data)

    monkeypatch.setattr(K, "decode_jsonl", counting)
    pinned, index = rk.pin_and_index()
    assert pinned.set_hash == first and len(calls) == 3
    again = rk.reaction_index(rs.pin_active_set())
    assert again is index and len(calls) == 3
    second = RF.build_set(ref, imported_at="2026-10-08T00:00:09Z")
    _pinned2, index2 = rk.pin_and_index()
    assert index2.set_hash == second and len(calls) == 6
    assert len(rk._INDEX_CACHE) == 1  # only the most recent set is kept
    RF.activate(ref, first)
    assert rk.pin_and_index()[1].set_hash == first and len(calls) == 9


@pytest.mark.parametrize("source, damage", [
    ("uniprot_function", lambda b: b.replace(b'"organism"', b'"organism_name"', 1)),
    ("mcsa", lambda b: b.replace(b'"mcsa_id":101', b'"mcsa_id": 101', 1)),
    ("rhea", lambda b: b"".join(sorted(b.splitlines(keepends=True)))),
    ("mcsa", lambda b: b + b.splitlines(keepends=True)[0]),
])
def test_unknown_content_format_is_snapshot_invalid_and_not_cached(ref, source, damage):
    rows = RF.synthetic_rows()
    data = damage(K.encode_jsonl(source, rows[source]))
    RF.build_set(ref, file_bytes={source: data})
    rs.pin_active_set()  # hashes are consistent: the hash-level pin succeeds
    with pytest.raises(rs.SnapshotUnavailable) as err:
        rk.pin_and_index()
    assert err.value.reason_code == "snapshot_invalid"
    assert rk._INDEX_CACHE == {}
    assert rk.capability()["reason_code"] == "snapshot_invalid"


def test_capability_shapes(ref, tmp_path, monkeypatch):
    set_hash = RF.build_set(ref)
    cap = rk.capability()
    assert cap == {"available": True, "reason_code": None, "reason": None, "set_hash": set_hash,
                   "sources": rs.pin_active_set().summary()}
    monkeypatch.setenv(K.ENV_VAR, str(tmp_path / "none"))
    assert rk.capability() == {"available": False, "reason_code": "not_installed",
                               "reason": K.SNAPSHOT_REASONS["not_installed"], "set_hash": None, "sources": []}


# ------------------------------------------------------------------------------------------- UniProt (5.4)

ALPHA = None


def alpha_residues():
    global ALPHA
    if ALPHA is None:
        ALPHA = residues_of("structure_alpha.cif")
    return ALPHA


def res(chain, seq_auth, icode="", resname=None):
    found = [r for r in alpha_residues()[chain] if r["seq_auth"] == seq_auth and r["icode"] == icode
             and (resname is None or r["resname"] == resname)]
    assert len(found) == 1
    return found[0]


def map_row(residue, status, accession=None, position=None, letter=None, match=None):
    """A row with every key of an M15 ``residue_numbering_map@1`` row (hand-built, LABELLED SYNTHETIC)."""
    return {"residue": dict(residue), "status": status, "uniprot_accession": accession,
            "uniprot_position": position, "uniprot_residue": letter, "residue_match": match, "klifs_index": None,
            "klifs_label": None, "klifs_match": None,
            "conflict_reason": "positions_differ" if status == "conflict" else None, "sifts": None,
            "alignment": None}


def numbering_map(chains, rows, pdb_id="0SY1"):
    return {"schema": "residue_numbering_map@1", "method_version": "mw.residue_numbering/v1",
            "structure": {"handle": HANDLE, "structure_kind": "prepared_structure", "model_number": 2},
            "pdb_id": pdb_id,
            "chains": [{"chain_auth": c, "requested_uniprot_accession": a, "methods_run": ["local_alignment"]}
                       for c, a in chains],
            "rows": rows, "null_result": False}


def standard_map():
    rows = [map_row(res("A", 10), "mapped", "Q0SYN1", 10, "D", True),
            map_row(res("A", 12), "mapped", "Q0SYN1", 12, "H", False),
            map_row(res("A", 13), "mapped", "Q0SYN1", 13, "H", False),
            map_row(res("A", 14), "mapped", "Q0SYN1", 13, "C", False),  # two map rows at one position
            map_row(res("A", 15), "unmapped"),
            map_row(res("A", 16), "conflict"),
            map_row(res("B", 1), "mapped", "Q0SYN1", 10, "A", False)]
    return numbering_map([("A", None), ("B", None)], rows)


def seven(residue):
    return {k: residue[k] for k in K.RESIDUE_FIELDS}


def mapped(q, residue, letter, match):
    return {"position": q, "status": "mapped", "residue": seven(residue), "uniprot_residue": letter,
            "residue_match": match}


def not_in_map(q):
    return {"position": q, "status": "not_in_map", "residue": None, "uniprot_residue": None, "residue_match": None}


def features_q0syn1(links):
    rows = RF.synthetic_rows()["uniprot_function"]
    base = next(r for r in rows if r["accession"] == "Q0SYN1")["features"]
    return [{**f, "links": link} for f, link in zip(base, links, strict=True)]


def test_accession_derivation():
    m = standard_map()
    assert rk.chain_accession("A", "P0SYN3", m) == ("P0SYN3", "user")
    assert rk.chain_accession("A", None, m) == ("Q0SYN1", "numbering_map")
    assert rk.chain_accession("A", None, None) == (None, None)
    assert rk.chain_accession("C", None, m) == (None, None)
    # requested accession of the map chain wins over its rows
    m2 = numbering_map([("A", "P0SYN3")], [map_row(res("A", 10), "mapped", "Q0SYN1", 10, "D", True)])
    assert rk.map_accession(m2, "A") == "P0SYN3"
    # rows with two accessions: none derived
    m3 = numbering_map([("A", None)], [map_row(res("A", 10), "mapped", "Q0SYN1", 10, "D", True),
                                       map_row(res("A", 12), "mapped", "P0SYN3", 12, "H", False)])
    assert rk.map_accession(m3, "A") is None
    # only "mapped" rows of the same chain count
    m4 = numbering_map([("A", None)], [map_row(res("A", 15), "unmapped"), map_row(res("B", 1), "mapped",
                                                                                   "Q0SYN1", 1, "A", True)])
    assert rk.map_accession(m4, "A") is None


def test_uniprot_not_checked_without_an_accession(world):
    _pinned, index = world
    assert rk.uniprot_section(index, None, "A", None) == {
        "status": "not_checked", "reason": "accession_not_given", "skipped": None, "entry": None,
        "linked_via": None, "link_reason": None, "features": None}


def test_uniprot_not_in_snapshot_and_skipped_at_import(world):
    _pinned, index = world
    absent = {"status": "not_available", "reason": "accession_not_in_snapshot", "skipped": None, "entry": None,
              "linked_via": None, "link_reason": None, "features": None}
    assert rk.uniprot_section(index, "Q0SYN0", "A", None) == absent
    assert rk.uniprot_section(index, "Q0SYN4", "A", standard_map()) == {
        **absent, "reason": "accession_skipped_at_import",
        "skipped": {"reason": "merged", "target_accessions": ["Q0SYN9"]}}
    assert rk.uniprot_section(index, "P0SYN6", "A", None)["skipped"] == {
        "reason": "demerged", "target_accessions": ["P0SYN1", "P0SYN2"]}
    assert rk.uniprot_section(index, "Q0SYN7", "A", None)["skipped"] == {"reason": "obsolete",
                                                                          "target_accessions": []}


def test_uniprot_checked_without_a_map_shows_sequence_positions_only(world):
    _pinned, index = world
    got = rk.uniprot_section(index, "Q0SYN1", "A", None)
    assert got == {"status": "checked", "reason": None, "skipped": None,
                   "entry": {"accession": "Q0SYN1", "entry_name": "SYN1_FIXTURE",
                             "protein_name": "SYNTHETIC fixture protein one", "organism": "Fixtureus syntheticus",
                             "sequence_length": 200},
                   "linked_via": None, "link_reason": "numbering_map_not_given",
                   "features": features_q0syn1([None, None, None, None])}


def test_uniprot_linked_through_the_numbering_map(world):
    _pinned, index = world
    expected_a = features_q0syn1([
        [mapped(10, res("A", 10), "D", True)],
        [mapped(12, res("A", 12), "H", False), mapped(13, res("A", 13), "H", False),
         mapped(13, res("A", 14), "C", False), not_in_map(14)],
        [not_in_map(99)],
        [mapped(10, res("A", 10), "D", True)]])
    for accession in ("Q0SYN1",):  # the user's accession equal to the map's
        got = rk.uniprot_section(index, accession, "A", standard_map())
        assert (got["linked_via"], got["link_reason"]) == ("numbering_map", None)
        assert got["features"] == expected_a
    got_b = rk.uniprot_section(index, "Q0SYN1", "B", standard_map())  # rows of chain B only
    assert got_b["features"] == features_q0syn1([
        [mapped(10, res("B", 1), "A", False)], [not_in_map(12), not_in_map(13), not_in_map(14)],
        [not_in_map(99)], [mapped(10, res("B", 1), "A", False)]])


def test_uniprot_link_refusals(world):
    _pinned, index = world
    differs = rk.uniprot_section(index, "P0SYN3", "A", standard_map())
    assert differs["status"] == "checked"
    assert (differs["linked_via"], differs["link_reason"]) == (None, "map_accession_differs")
    assert all(f["links"] is None for f in differs["features"])
    only_b = numbering_map([("B", None)], [map_row(res("B", 1), "mapped", "Q0SYN1", 10, "A", False)])
    got = rk.uniprot_section(index, "Q0SYN1", "A", only_b)
    assert (got["linked_via"], got["link_reason"]) == (None, "chain_not_in_map")
    two = numbering_map([("A", None)], [map_row(res("A", 10), "mapped", "Q0SYN1", 10, "D", True),
                                        map_row(res("A", 12), "mapped", "P0SYN3", 12, "H", False)])
    got = rk.uniprot_section(index, "Q0SYN1", "A", two)  # derived accession is null
    assert (got["linked_via"], got["link_reason"]) == (None, "map_accession_differs")
    empty = rk.uniprot_section(index, "Q0SYN2", "A", standard_map())
    assert empty["features"] == [] and empty["link_reason"] == "map_accession_differs"


def test_accession_differs_from_mcsa_flag(world):
    _pinned, index = world
    covered = rk.mcsa_section(index, "0SY1", "A", alpha_residues()["A"])
    not_listed = rk.mcsa_section(index, "0SY1", "B", alpha_residues()["B"])
    assert rk.chain_flags(index, "Q0SYN1", covered) == []
    assert rk.chain_flags(index, "P0SYN3", covered) == []          # second accession of "Q0SYN2, P0SYN3"
    assert rk.chain_flags(index, "Q0SYN4", covered) == []          # residue_sequences accession
    assert rk.chain_flags(index, "Q0SYN5", covered) == ["accession_differs_from_mcsa"]
    assert rk.chain_flags(index, "Q0SYN5", not_listed) == []
    assert rk.chain_flags(index, None, covered) == []


# ------------------------------------------------------------------------------------------- reactions (5.5)

def _sections(index, pdb_id, chain, accession, structure="structure_alpha.cif", nmap=None):
    mcsa = rk.mcsa_section(index, pdb_id, chain, residues_of(structure)[chain])
    uniprot = rk.uniprot_section(index, accession, chain, nmap)
    return mcsa, uniprot, rk.reactions_section(index, mcsa, uniprot)


ACTIVITIES_Q0SYN1 = [
    {"reaction_name": "synthetic substrate one = synthetic product one", "ec_number": "9.99.1.1",
     "rhea": [{"rhea_id": "RHEA:10000", "in_snapshot": True}, {"rhea_id": "RHEA:9000010", "in_snapshot": True}]},
    {"reaction_name": "synthetic substrate two = synthetic product two", "ec_number": None,
     "rhea": [{"rhea_id": "RHEA:800", "in_snapshot": True}, {"rhea_id": "RHEA:9000099", "in_snapshot": False}]},
    {"reaction_name": "synthetic reaction without a Rhea link", "ec_number": "9.99.1.2", "rhea": []},
    {"reaction_name": "synthetic substrate one = synthetic product one (again)", "ec_number": "9.99.1.1",
     "rhea": [{"rhea_id": "RHEA:9000010", "in_snapshot": True}]},
]


def test_reactions_both_sources(world):
    _pinned, index = world
    _m, _u, got = _sections(index, "0SY1", "A", "Q0SYN1")
    mcsa_rows = RF.synthetic_rows()["mcsa"]
    assert got == {
        "status": "checked", "reason": None,
        "ecs": {"mcsa": ["9.99.1.1", "9.99.2.1"], "uniprot": ["9.99.1.1", "9.99.1.2", "9.99.1.3"]},
        "mcsa_compounds": [{"mcsa_id": 101, "ec": "9.99.1.1", "compounds": mcsa_rows[0]["reaction"]["compounds"]},
                           {"mcsa_id": 102, "ec": "9.99.2.1", "compounds": mcsa_rows[1]["reaction"]["compounds"]}],
        "uniprot_activities": ACTIVITIES_Q0SYN1}
    # no widening from EC numbers to Rhea: RHEA:9000020 carries EC 9.99.1.3 (in Q0SYN1's ec_numbers) but no
    # catalytic activity names it
    assert "RHEA:9000020" not in json.dumps(got)


def test_reactions_one_source_each_and_none(world):
    _pinned, index = world
    _m, _u, mcsa_only = _sections(index, "0SY1", "A", None)
    assert mcsa_only["ecs"] == {"mcsa": ["9.99.1.1", "9.99.2.1"], "uniprot": None}
    assert mcsa_only["uniprot_activities"] is None and len(mcsa_only["mcsa_compounds"]) == 2
    _m, _u, uniprot_only = _sections(index, "0SY9", "A", "Q0SYN1")
    assert uniprot_only["ecs"] == {"mcsa": None, "uniprot": ["9.99.1.1", "9.99.1.2", "9.99.1.3"]}
    assert uniprot_only["mcsa_compounds"] is None and uniprot_only["uniprot_activities"] == ACTIVITIES_Q0SYN1
    _m, _u, empty = _sections(index, "0SY9", "A", "Q0SYN2")
    assert empty == {"status": "checked", "reason": None, "ecs": {"mcsa": None, "uniprot": []},
                     "mcsa_compounds": None, "uniprot_activities": []}
    for pdb_id, accession in ((None, None), ("0SY1", None), ("0SY9", "Q0SYN0")):
        chain = "B" if pdb_id == "0SY1" else "A"  # chain_not_listed, not_checked, pdb_not_in_snapshot
        _m, _u, none = _sections(index, pdb_id, chain, accession)
        assert none == {"status": "not_checked", "reason": "no_source", "ecs": None, "mcsa_compounds": None,
                        "uniprot_activities": None}


def test_reactions_null_mcsa_ec(world):
    _pinned, index = world
    _m, _u, got = _sections(index, "0SY2", "A", None, structure="structure_beta.pdb")
    assert got["ecs"] == {"mcsa": ["9.99.1.1", "9.99.3.1"], "uniprot": None}  # 101 (His 60) and 103 (ec null)
    assert got["mcsa_compounds"][1] == {"mcsa_id": 103, "ec": None, "compounds": []}


# ------------------------------------------------------------------------------------------- result (5.6)

def build(world, *, structure="structure_alpha.cif", pdb_id="0SY1", chains=(("A", "Q0SYN1"),), nmap=None,
          map_handle=None):
    pinned, index = world
    st = parse(structure)
    return rk.build_reaction_knowledge(
        pinned=pinned, index=index, structure_handle=HANDLE, structure_kind="prepared_structure",
        model_number=st[0].num, pdb_id=pdb_id,
        chains=[{"chain_auth": c, "uniprot_accession": a} for c, a in chains],
        chain_residues=rk.chain_polymer_residues(st), numbering_map=nmap, numbering_map_handle=map_handle)


def full(world):
    return build(world, chains=(("A", "Q0SYN1"), ("B", None)), nmap=standard_map(), map_handle=MAP_HANDLE)


TOP_KEYS = {"schema", "method_version", "structure", "pdb_id", "numbering_map", "snapshot_set", "chains",
            "reference_rows", "counts", "null_result", "limitations"}


def test_full_result_shape_counts_and_reference_rows(world):
    pinned, _index = world
    result = full(world)
    assert set(result) == TOP_KEYS
    assert result["schema"] == "reaction_knowledge@1" and result["method_version"] == "mw.reaction_knowledge/v1"
    assert result["structure"] == {"handle": HANDLE, "structure_kind": "prepared_structure", "model_number": 2}
    assert result["pdb_id"] == "0SY1" and result["numbering_map"] == {"handle": MAP_HANDLE, "pdb_id": "0SY1"}
    manifest = pinned.manifest
    assert result["snapshot_set"] == {
        "set_hash": pinned.set_hash, "imported_at": manifest["imported_at"],
        "importer_version": "reaction_import/1",
        "sources": [{"source": s["source"], "date": s["date"], "license": s["license"], "origin": s["origin"],
                     "files": [{k: f[k] for k in ("name", "sha256", "bytes", "rows")} for f in s["files"]]}
                    for s in manifest["sources"]],
        "requested_accessions": manifest["requested_accessions"],
        "skipped_accessions": manifest["skipped_accessions"]}
    a, b = result["chains"]
    for chain in (a, b):
        assert set(chain) == {"chain_auth", "polymer_residue_count", "accession", "accession_source", "mcsa",
                              "uniprot", "reactions", "flags"}
        assert set(chain["mcsa"]) == {"status", "reason", "coverage", "entries", "rows", "counts"}
        assert set(chain["uniprot"]) == {"status", "reason", "skipped", "entry", "linked_via", "link_reason",
                                         "features"}
        assert set(chain["reactions"]) == {"status", "reason", "ecs", "mcsa_compounds", "uniprot_activities"}
    assert (a["chain_auth"], a["polymer_residue_count"], a["accession"], a["accession_source"]) == (
        "A", 24, "Q0SYN1", "user")
    assert (b["chain_auth"], b["polymer_residue_count"], b["accession"], b["accession_source"]) == (
        "B", 2, "Q0SYN1", "numbering_map")
    assert a["mcsa"] == CASES["alpha_A"]["mcsa"]
    assert b["mcsa"] == CASES["alpha_B_chain_not_listed"]["mcsa"]
    for row in a["mcsa"]["rows"]:
        assert set(row) == {"mcsa_id", "residue_index", "is_reference", "listed", "status", "reason", "residue",
                            "structure_resname", "reference"}
        assert set(row["listed"]) == {"pdb_id", "chain_name", "resid", "auth_resid", "code", "assemblies"}
        assert set(row["reference"]) == {"roles_summary", "function_location_abv", "ptm", "roles"}
    assert b["uniprot"]["linked_via"] == "numbering_map" and a["uniprot"]["linked_via"] == "numbering_map"
    assert a["flags"] == [] and b["flags"] == []
    assert b["reactions"]["ecs"] == {"mcsa": None, "uniprot": ["9.99.1.1", "9.99.1.2", "9.99.1.3"]}
    assert result["counts"] == {
        "chains": 2, "covered_chains": 1, "mcsa_rows": {"matched": 15, "unmatched": 8, "conflict": 6},
        "mcsa_entries": 2, "uniprot_features": {"Active site": 2, "Binding site": 4, "Site": 2},
        "linked_positions": {"mapped": 7, "not_in_map": 6}, "rhea": {"in_snapshot": 3, "not_in_snapshot": 1}}
    rows = RF.synthetic_rows()
    assert result["reference_rows"] == {
        "mcsa": [rows["mcsa"][0], rows["mcsa"][1]],
        "uniprot": [r for r in rows["uniprot_function"] if r["accession"] == "Q0SYN1"],
        "rhea": [r for r in rows["rhea"] if r["rhea_id"] in ("RHEA:800", "RHEA:10000", "RHEA:9000010")]}
    assert [r["rhea_id"] for r in result["reference_rows"]["rhea"]] == ["RHEA:800", "RHEA:10000", "RHEA:9000010"]
    assert result["null_result"] is False
    assert result["limitations"] == list(K.LIMITATIONS)
    assert rk.validated_result(result) is result


def test_valid_empty_result_counts_are_null_or_zero_by_rule(world):
    result = build(world, pdb_id="0SY9", chains=(("A", "Q0SYN2"),))
    assert result["chains"][0]["mcsa"]["coverage"] == "pdb_not_in_snapshot"
    assert result["counts"] == {"chains": 1, "covered_chains": 0, "mcsa_rows": None, "mcsa_entries": None,
                                "uniprot_features": {"Active site": 0, "Binding site": 0, "Site": 0},
                                "linked_positions": None, "rhea": {"in_snapshot": 0, "not_in_snapshot": 0}}
    assert result["null_result"] is True
    assert result["reference_rows"]["mcsa"] == [] and result["reference_rows"]["rhea"] == []
    rk.validated_result(result)


def test_nothing_checked_result(world):
    result = build(world, pdb_id=None, chains=(("A", None), ("B", None)))
    assert [c["mcsa"]["status"] for c in result["chains"]] == ["not_checked", "not_checked"]
    assert [c["reactions"]["status"] for c in result["chains"]] == ["not_checked", "not_checked"]
    assert [c["accession_source"] for c in result["chains"]] == [None, None]
    assert result["counts"] == {"chains": 2, "covered_chains": 0, "mcsa_rows": None, "mcsa_entries": None,
                                "uniprot_features": None, "linked_positions": None, "rhea": None}
    assert result["null_result"] is True and result["numbering_map"] is None
    assert result["reference_rows"] == {"mcsa": [], "uniprot": [], "rhea": []}
    rk.validated_result(result)


def test_not_null_when_only_uniprot_ecs_exist(world):
    result = build(world, pdb_id="0SY9", chains=(("A", "Q0SYN5"),))
    assert result["chains"][0]["uniprot"]["features"] and result["null_result"] is False
    rk.validated_result(result)


@pytest.mark.parametrize("kwargs", [
    {}, {"pdb_id": None}, {"pdb_id": "0SY9", "chains": (("A", "Q0SYN4"), ("B", "P0SYN6"))},
    {"structure": "structure_beta.pdb", "pdb_id": "0SY2", "chains": (("A", "Q0SYN5"), ("B", None))},
    {"chains": (("A", "Q0SYN5"),)}, {"chains": (("A", "Q0SYN0"),)},
])
def test_other_builds_validate(world, kwargs):
    result = build(world, **kwargs)
    assert rk.validated_result(result) is result
    if kwargs.get("chains") == (("A", "Q0SYN5"),):
        assert result["chains"][0]["flags"] == ["accession_differs_from_mcsa"]


def test_same_input_same_set_gives_the_same_dict(ref, world):
    first = full(world)
    second = full(world)
    assert first == second and K.canonical_json(first) == K.canonical_json(second)
    rk.clear_index_cache()
    rs._VERIFIED.clear()
    assert K.canonical_json(full(rk.pin_and_index())) == K.canonical_json(first)
    RF.build_set(ref, imported_at="2026-10-08T00:00:07Z")
    other = full(rk.pin_and_index())
    assert other["snapshot_set"]["set_hash"] != first["snapshot_set"]["set_hash"]
    assert {**other, "snapshot_set": None} == {**first, "snapshot_set": None}


def test_validation_needs_no_reference_folder(ref, world):
    result = full(world)
    shutil.rmtree(ref)
    rk.clear_index_cache()
    rs._VERIFIED.clear()
    assert rk.validated_result(copy.deepcopy(result)) == result  # events-only: the object carries what it used


def test_no_time_or_call_id_in_the_result(world):
    text = K.canonical_json(full(world)).decode()
    assert "call_" not in text and "created" not in text


def test_caps_raise_and_return_nothing(world, monkeypatch):
    result = full(world)
    size = len(K.canonical_json(result))
    links = sum(len(f["links"]) for c in result["chains"] for f in c["uniprot"]["features"] or [] if f["links"])
    assert links == 13
    monkeypatch.setattr(K, "MAX_LINKS", 13)
    assert full(world) == result
    monkeypatch.setattr(K, "MAX_LINKS", 12)
    with pytest.raises(rk.TooManyLinks):
        full(world)
    monkeypatch.setattr(K, "MAX_LINKS", 2000)
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", size)
    assert full(world) == result
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", size - 1)
    with pytest.raises(rk.ResultTooLarge):
        full(world)
    assert issubclass(rk.ResultTooLarge, rk.ResourceExceeded) and issubclass(rk.TooManyLinks, rk.ResourceExceeded)


def test_real_link_cap_with_a_long_site(ref):
    rows = RF.synthetic_rows()
    q1 = next(r for r in rows["uniprot_function"] if r["accession"] == "Q0SYN1")
    q1["sequence_length"] = 5000
    q1["features"] = [{"type": "Binding site", "start": 1, "end": 2001, "description": "", "ligand_name": None,
                       "ligand_id": None}]
    RF.build_set(ref, rows=rows)
    world = rk.pin_and_index()
    with pytest.raises(rk.TooManyLinks):
        build(world, chains=(("A", "Q0SYN1"),), nmap=standard_map(), map_handle=MAP_HANDLE)
    # positions 1..E give E + 1 link elements here (position 13 has two map rows): E = 2000 is 2001 elements
    q1["features"][0]["end"] = 2000
    RF.build_set(ref, rows=rows, imported_at="2026-10-08T00:00:08Z")
    with pytest.raises(rk.TooManyLinks):
        build(rk.pin_and_index(), chains=(("A", "Q0SYN1"),), nmap=standard_map(), map_handle=MAP_HANDLE)
    q1["features"][0]["end"] = 1999
    RF.build_set(ref, rows=rows, imported_at="2026-10-08T00:00:09Z")
    result = build(rk.pin_and_index(), chains=(("A", "Q0SYN1"),), nmap=standard_map(), map_handle=MAP_HANDLE)
    assert result["counts"]["linked_positions"] == {"mapped": 4, "not_in_map": 1996}
    rk.validated_result(result)


# ------------------------------------------------------------------------------------------- validated_result

def _set(obj, path, value):
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


def _get(obj, path):
    for key in path:
        obj = obj[key]
    return obj


A_ROWS = ["chains", 0, "mcsa", "rows"]
A_FEAT = ["chains", 0, "uniprot", "features"]
TAMPER = [
    ("extra top key", lambda r: r.update(created_at="2026-10-08")),
    ("missing top key", lambda r: r.pop("limitations")),
    ("schema", lambda r: r.update(schema="reaction_knowledge@2")),
    ("method version", lambda r: r.update(method_version="mw.reaction_knowledge/v2")),
    ("pdb lowercase", lambda r: r.update(pdb_id="0sy1")),
    ("structure kind", lambda r: _set(r, ["structure", "handle"], "obj://run_t2/structure/" + "a" * 64)),
    ("structure model bool", lambda r: _set(r, ["structure", "model_number"], True)),
    ("map other run", lambda r: _set(r, ["numbering_map", "handle"], "obj://run_x/residue_numbering_map/" + "b" * 64)),
    ("map other pdb", lambda r: _set(r, ["numbering_map", "pdb_id"], "0SY2")),
    ("set extra key", lambda r: r["snapshot_set"].update(origin="x")),
    ("set sources order", lambda r: r["snapshot_set"]["sources"].reverse()),
    ("set skipped", lambda r: r["snapshot_set"]["skipped_accessions"][0].update(reason="deleted")),
    ("counts matched", lambda r: _set(r, ["counts", "mcsa_rows", "matched"], 16)),
    ("counts chains", lambda r: _set(r, ["counts", "chains"], 3)),
    ("counts rhea", lambda r: _set(r, ["counts", "rhea", "in_snapshot"], 4)),
    ("counts links null", lambda r: _set(r, ["counts", "linked_positions"], None)),
    ("counts features zero", lambda r: _set(r, ["counts", "uniprot_features", "Site"], 0)),
    ("null result", lambda r: r.update(null_result=True)),
    ("limitations order", lambda r: r["limitations"].reverse()),
    ("limitation text", lambda r: _set(r, ["limitations", 0], "다른 문장.")),
    ("limitation dropped", lambda r: r["limitations"].pop()),
    ("limitation RK6 added", lambda r: r["limitations"].append(K.STATEMENTS["RK6"])),
    ("duplicate chain", lambda r: r["chains"].append(copy.deepcopy(r["chains"][0]))),
    ("residue count zero", lambda r: _set(r, ["chains", 0, "polymer_residue_count"], 0)),
    ("accession source null", lambda r: _set(r, ["chains", 1, "accession_source"], None)),
    ("flag added", lambda r: _set(r, ["chains", 0, "flags"], ["accession_differs_from_mcsa"])),
    ("unknown flag", lambda r: _set(r, ["chains", 1, "flags"], ["catalytic"])),
    ("row of another chain", lambda r: _set(r, A_ROWS + [0, "listed", "chain_name"], "B")),
    ("residue of another chain", lambda r: _set(r, A_ROWS + [0, "residue", "chain_auth"], "B")),
    ("residue other model", lambda r: _set(r, A_ROWS + [0, "residue", "model_number"], 1)),
    ("residue label type", lambda r: _set(r, A_ROWS + [0, "residue", "seq_label"], "1")),
    ("residue extra field", lambda r: _set(r, A_ROWS + [0, "residue", "atom_count"], 1)),
    ("matched name differs", lambda r: (_set(r, A_ROWS + [0, "residue", "resname"], "GLU"),
                                        _set(r, A_ROWS + [0, "structure_resname"], "GLU"))),
    ("matched other number", lambda r: _set(r, A_ROWS + [0, "residue", "seq_auth"], 11)),
    ("structure resname differs", lambda r: _set(r, A_ROWS + [0, "structure_resname"], "ASH")),
    ("rows reordered", lambda r: _get(r, A_ROWS).reverse()),
    ("row dropped", lambda r: _get(r, A_ROWS).pop()),
    ("row duplicated", lambda r: _get(r, A_ROWS).append(copy.deepcopy(_get(r, A_ROWS)[-1]))),
    ("entry dropped", lambda r: _get(r, ["chains", 0, "mcsa", "entries"]).pop()),
    ("entry name", lambda r: _set(r, ["chains", 0, "mcsa", "entries", 0, "enzyme_name"], "x")),
    ("status without reason", lambda r: _set(r, A_ROWS + [0, "status"], "unmatched")),
    ("unknown reason", lambda r: (_set(r, A_ROWS + [2, "reason"], "too_many_numbers"))),
    ("reason swapped", lambda r: _set(r, A_ROWS + [2, "reason"], "no_author_number")),
    ("disagree with residue", lambda r: _set(r, A_ROWS + [12, "residue"], copy.deepcopy(_get(r, A_ROWS)[0]["residue"]))),
    ("null number reason", lambda r: _set(r, A_ROWS + [10, "reason"], "residue_not_in_structure")),
    ("insertion without residue", lambda r: (_set(r, A_ROWS + [3, "residue"], None),
                                             _set(r, A_ROWS + [3, "structure_resname"], None))),
    ("listed code", lambda r: _set(r, A_ROWS + [0, "listed", "code"], "Glu")),
    ("listed resid", lambda r: _set(r, A_ROWS + [11, "listed", "resid"], 34)),
    ("listed assemblies", lambda r: _set(r, A_ROWS + [11, "listed", "assemblies"], [2, 1])),
    ("listed pdb", lambda r: _set(r, A_ROWS + [0, "listed", "pdb_id"], "0sy2")),
    ("is_reference", lambda r: _set(r, A_ROWS + [11, "is_reference"], False)),
    ("roles empty list", lambda r: _set(r, A_ROWS + [1, "reference", "roles"], [])),
    ("role text", lambda r: _set(r, A_ROWS + [0, "reference", "roles_summary"], "translated")),
    ("covered rows null", lambda r: _set(r, ["chains", 0, "mcsa", "coverage"], "chain_not_listed")),
    ("not listed rows empty", lambda r: _set(r, ["chains", 1, "mcsa", "rows"], [])),
    ("not listed counts zero", lambda r: _set(r, ["chains", 1, "mcsa", "counts"],
                                              {"matched": 0, "unmatched": 0, "conflict": 0})),
    ("mcsa not checked with pdb", lambda r: _set(r, ["chains", 1, "mcsa"], {
        "status": "not_checked", "reason": "pdb_id_not_given", "coverage": None, "entries": None, "rows": None,
        "counts": None})),
    ("mcsa counts", lambda r: _set(r, ["chains", 0, "mcsa", "counts", "conflict"], 5)),
    ("links null when linked", lambda r: _set(r, A_FEAT + [0, "links"], None)),
    ("feature description", lambda r: _set(r, A_FEAT + [0, "description"], "edited")),
    ("feature dropped", lambda r: _get(r, A_FEAT).pop()),
    ("link gap", lambda r: _get(r, A_FEAT + [1, "links"]).pop()),
    ("link status", lambda r: _set(r, A_FEAT + [1, "links", 3, "status"], "unmapped")),
    ("link of another chain", lambda r: _set(r, A_FEAT + [0, "links", 0, "residue", "chain_auth"], "B")),
    ("link not in map with residue", lambda r: _set(r, A_FEAT + [2, "links", 0, "residue"],
                                                    copy.deepcopy(_get(r, A_FEAT)[0]["links"][0]["residue"]))),
    ("link reason with link", lambda r: _set(r, ["chains", 0, "uniprot", "link_reason"], "chain_not_in_map")),
    ("uniprot entry", lambda r: _set(r, ["chains", 0, "uniprot", "entry", "organism"], "x")),
    ("uniprot skipped", lambda r: _set(r, ["chains", 0, "uniprot", "skipped"], {"reason": "merged",
                                                                                 "target_accessions": []})),
    ("reference uniprot row", lambda r: _set(r, ["reference_rows", "uniprot", 0, "features", 0, "description"],
                                             "edited")),
    ("reference mcsa order", lambda r: r["reference_rows"]["mcsa"].reverse()),
    ("reference mcsa extra", lambda r: r["reference_rows"]["mcsa"].append(RF.synthetic_rows()["mcsa"][3])),
    ("reference rhea extra", lambda r: r["reference_rows"]["rhea"].append(RF.synthetic_rows()["rhea"][3])),
    ("reference rhea order", lambda r: r["reference_rows"]["rhea"].reverse()),
    ("reference row invalid", lambda r: r["reference_rows"]["mcsa"][0].update(main_annotation="")),
    ("ecs uniprot null", lambda r: _set(r, ["chains", 0, "reactions", "ecs", "uniprot"], None)),
    ("ecs mcsa empty", lambda r: _set(r, ["chains", 1, "reactions", "ecs", "mcsa"], [])),
    ("ecs added", lambda r: _get(r, ["chains", 0, "reactions", "ecs", "mcsa"]).append("9.99.9.9")),
    ("in snapshot flipped", lambda r: _set(r, ["chains", 0, "reactions", "uniprot_activities", 1, "rhea", 1,
                                              "in_snapshot"], True)),
    ("activity order", lambda r: _get(r, ["chains", 0, "reactions", "uniprot_activities"]).reverse()),
    ("compounds edited", lambda r: _set(r, ["chains", 0, "reactions", "mcsa_compounds", 0, "ec"], None)),
    ("reactions not checked", lambda r: _set(r, ["chains", 1, "reactions"], {
        "status": "not_checked", "reason": "no_source", "ecs": None, "mcsa_compounds": None,
        "uniprot_activities": None})),
]


@pytest.mark.parametrize("name, mutate", TAMPER, ids=[n for n, _ in TAMPER])
def test_validated_result_rejects_tampering(world, name, mutate):
    result = full(world)
    rk.validated_result(result)
    tampered = copy.deepcopy(result)
    mutate(tampered)
    with pytest.raises(rk.ResultInvalid):
        rk.validated_result(tampered)


def test_validated_result_rejects_non_objects_and_floats(world):
    for bad in (None, [], "x", {"schema": "reaction_knowledge@1"}):
        with pytest.raises(rk.ResultInvalid):
            rk.validated_result(bad)
    result = full(world)
    result["counts"]["chains"] = 2.0
    with pytest.raises(rk.ResultInvalid):
        rk.validated_result(result)
    assert issubclass(rk.ResultInvalid, ValueError)


def test_validated_result_checks_skipped_and_not_in_snapshot_against_the_manifest(world):
    result = build(world, pdb_id="0SY9", chains=(("A", "Q0SYN4"), ("B", "Q0SYN0")))
    rk.validated_result(result)
    for chain, value in ((0, None), (1, {"reason": "merged", "target_accessions": ["Q0SYN9"]})):
        tampered = copy.deepcopy(result)
        tampered["chains"][chain]["uniprot"]["skipped"] = value
        tampered["chains"][chain]["uniprot"]["reason"] = ("accession_not_in_snapshot" if value is None
                                                          else "accession_skipped_at_import")
        with pytest.raises(rk.ResultInvalid):
            rk.validated_result(tampered)


# ------------------------------------------------------------------------------------------- module boundary

NEW_MODULES = [Path(rk.__file__), Path(K.__file__), Path(rs.__file__)]


@pytest.mark.parametrize("path", NEW_MODULES, ids=lambda p: p.name)
def test_no_network_imports_and_no_limit_raising_words(path):
    source = path.read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"socket", "urllib", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp"}
    assert "raise_limits" not in source and "limit_approval" not in source


def test_knowledge_module_imports_no_engine_or_m15_writer():
    tree = ast.parse(Path(rk.__file__).read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(("." * node.level) + (node.module or ""))
            if node.level and not node.module:
                modules.update("." + alias.name for alias in node.names)
    assert not {m.split(".")[0] for m in modules if not m.startswith(".")} & {
        "rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "prolif"}
    assert ".reference_snapshots" not in modules and ".jev_sends" not in modules
