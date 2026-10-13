"""M29 T4: the splice builder, the record and the pure validator (spec 2.3, 3.2-3.6).

Inputs: the product-prepared public structures, the PDBFixer-measured addition fixtures
(``fixtures/structure_repair/*-additions.pdbfixer-measured.json``, PDBFixer 1.12.0 output at full precision, not product
values), and for the PDB-format gap and the calc_flag fixture the atoms the SYNTHETIC edit removed from 1UBQ (the
original observed coordinates, used as test additions). Expected values are read from the input bytes and the fixture
rows here (gemmi), not from the product's record.
"""
from __future__ import annotations

import copy
import json
import math

import gemmi
import numpy as np
import pytest
import test_structure_repair_common as C

from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw.core.errors import ToolFailure
from mw.core.handles import canonical_json


@pytest.fixture(scope="module", autouse=True)
def _root(tmp_path_factory):
    C.use_root(tmp_path_factory.mktemp("m29_t4_build"))


_BUILT: dict[tuple, tuple] = {}


def built(name: str, waters: str = "strip_all") -> tuple[sr.RepairInputs, bytes, dict]:
    if (name, waters) not in _BUILT:
        inputs = C.public(name, waters)
        rows = C.additions(name) if name in C.MEASURED else []
        _BUILT[(name, waters)] = (inputs, *sr.build_repaired(inputs, rows))
    return _BUILT[(name, waters)]


def _atoms(st: gemmi.Structure, mse_to_met: bool = False) -> dict[tuple, list]:
    """(chain, seq, icode, label chain, label seq, resname, atom name, altloc) -> [element, x, y, z, calc_flag]."""
    out = {}
    for chain in st[0]:
        for res in chain:
            mse = mse_to_met and res.name == "MSE"
            for atom in res:
                name, element = atom.name, atom.element.name
                if mse and name == "SE":
                    name, element = "SD", "S"
                key = (*C.key(chain, res)[:5], "MET" if mse else res.name, name, atom.altloc)
                assert key not in out
                out[key] = [element, atom.pos.x, atom.pos.y, atom.pos.z, atom.calc_flag]
    return out


def _row_key(row: dict) -> tuple:
    return (*C.ref_key(row["residue"]), row["atom_name"], "\0")


@pytest.mark.parametrize(("name", "waters"), [("8vf6", "strip_all"), ("8vf6", "keep_all"), ("1rnh", "keep_all"),
                                              ("1cll", "strip_all"), ("1hsg", "keep_all"), ("1mq4", "strip_all"),
                                              ("4ins", "keep_all"), ("1ay7", "keep_all")])
def test_observed_atoms_are_kept_and_new_atoms_are_the_rounded_pdbfixer_rows(name, waters):
    inputs, raw, record = built(name, waters)
    before = _atoms(C.structure(inputs.prepared_bytes, inputs.prepared_fmt), mse_to_met=True)
    after = _atoms(C.structure(raw))
    for key, (element, x, y, z, _flag) in before.items():
        got = after[key]
        assert got[0] == element and math.dist(got[1:4], (x, y, z)) <= 1e-9, key
        assert got[4] == gemmi.CalcFlag.NotSet
    new = {key: value for key, value in after.items() if key not in before}
    rows = C.additions(name) if name in C.MEASURED else []
    assert set(new) == {_row_key(row) for row in rows}
    for row in rows:
        element, *xyz, flag = new[_row_key(row)]
        assert (element, flag) == (row["element"], gemmi.CalcFlag.Calculated)
        assert all(abs(a - b) <= 0.5e-4 + 1e-12 and abs(a * 1e4 - round(a * 1e4)) < 1e-6
                   for a, b in zip(xyz, row["coordinates_A"]))
    assert record["unchanged"] == {"atom_count": len(before), "max_delta_A": 0.0, "input_calc_flag_cleared": 0}
    assert record["counts"]["added_atoms"] == len(rows) == len(record["added_atoms"])
    assert record["new_atom_rounding"]["decimals"] == 4
    assert 0.0 <= record["new_atom_rounding"]["max_abs_delta_A"] <= 0.5e-4
    assert [(a["residue"], a["atom_name"]) for a in record["added_atoms"]] == [
        (r, n) for r, n in ((dict(zip(K.IDENTITY_FIELDS, (1, k[0], k[3], k[1], k[4], k[2], k[5]))), k[6])
                            for k in after if k in new)]


def test_8vf6_record_counts_classes_gaps_and_chain_parts():
    inputs, raw, record = built("8vf6", "keep_all")
    fixture = json.loads((C.SR_FIX / "8vf6-additions.pdbfixer-measured.json").read_text())
    assert record["counts"] == {"added_residues": 24, "added_atoms": 266, "side_chain_residues": 23, "terminal_oxt": 2,
                                "gaps": 2, "replaced": 0, "chain_parts_merged": 2, "protein_heavy_atoms": 4538}
    assert record["classes_applied"] == ["chain_parts_merged", "side_chain_atoms_added", "terminal_oxt_added",
                                         "internal_gap_filled"]
    assert record["chain_parts"] == [{"chain_auth": "A", "parts": 3, "merged": True},
                                     {"chain_auth": "B", "parts": 3, "merged": True}]
    assert record["gaps"] == [{k: g[k] for k in ("chain_auth", "after_residue", "before_residue", "length", "residues")}
                              for g in fixture["gaps"]]
    assert [s["residue"] for s in record["side_chain_repairs"]] == [s["residue"] for s in fixture["side_chain_repairs"]]
    assert [t["residue"] for t in record["terminal_oxt"]] == [t["residue"] for t in fixture["terminal_oxt"]]
    assert record["limitations"] == [K.RP1, K.RP2, K.RP3, K.RP4, K.RP6]
    assert [(e["chain_auth"], e["first_is_sequence_start"], e["last_is_sequence_end"]) for e in record["chain_ends"]] \
        == [("A", False, False), ("B", False, True)]
    assert set(record) == set(K.RECORD_KEYS)
    assert record["source"] == {"prepared_structure": inputs.prepared_structure, "model_number": 1}
    assert record["result"]["coordinates"] == sr.coordinates_handle(inputs.run_id, raw)
    assert record["parameters"] == {"repair_policy": K.REPAIR_POLICY, "seed": 1, "max_gap_residues": 20,
                                    "waters": "keep_all", "hydrogens": "strip", "new_atom_coordinate_decimals": 4}
    out = C.structure(raw)
    assert [chain.name for chain in out[0]] == ["A", "B"]
    labels = [res.label_seq for res in out[0]["A"] if res.het_flag == "A"]
    assert labels == list(range(labels[0], labels[0] + len(labels)))


def test_8vf6_collisions_follow_the_independent_count():
    _inputs, raw, record = built("8vf6", "keep_all")
    out = C.structure(raw)
    chains, polymer, where, kinds, xyz, new = [], [], [], [], [], []
    for chain_number, chain in enumerate(out[0]):
        polymer_index = 0
        for position, res in enumerate(chain):
            kind = "protein" if res.het_flag == "A" else "water" if res.is_water() else "ligand"
            for atom in res:
                chains.append(chain_number)
                polymer.append(polymer_index if kind == "protein" else -100)
                where.append(chain_number * 100000 + position)
                kinds.append(kind)
                xyz.append((atom.pos.x, atom.pos.y, atom.pos.z))
                new.append(atom.calc_flag == gemmi.CalcFlag.Calculated)
            polymer_index += kind == "protein"
    chains, polymer, where, kinds, xyz = (np.array(chains), np.array(polymer), np.array(where), np.array(kinds),
                                          np.array(xyz))
    for cls in ("protein", "ligand", "water"):
        nearest = []
        for i in np.flatnonzero(new):
            adjacent = (chains == chains[i]) & (np.abs(polymer - polymer[i]) == 1) & (polymer >= 0)
            mask = (kinds == cls) & (where != where[i]) & ~adjacent
            nearest.append(float(np.min(np.linalg.norm(xyz[mask] - xyz[i], axis=1))))
        got = record["collisions"][cls]
        assert got["min_distance_A"] == pytest.approx(min(nearest), abs=1e-9)
        assert (got["count_lt_2_0"], got["count_lt_1_5"]) == (sum(d < 2.0 for d in nearest),
                                                              sum(d < 1.5 for d in nearest))
    for cls in ("metal", "other"):
        assert record["collisions"][cls] == {"min_distance_A": None, "count_lt_2_0": 0, "count_lt_1_5": 0,
                                             "min_pair": None}
    pair = record["collisions"]["protein"]["min_pair"]
    assert set(pair) == {"new_residue", "new_atom", "partner_residue", "partner_atom"}


def test_1rnh_mse_becomes_met_with_its_map_and_unchanged_coordinates():
    inputs, raw, record = built("1rnh", "keep_all")
    assert [(r["from"]["seq_auth"], r["from"]["resname"], r["to"]["resname"], r["atom_map"], r["record_type"])
            for r in record["replaced"]] == [
        (n, "MSE", "MET", [{"from": "SE", "to": "SD"}], {"from": "HETATM", "to": "ATOM"}) for n in (47, 50, 142)]
    assert {k: v for k, v in record["replaced"][0]["from"].items() if k != "resname"} == {
        k: v for k, v in record["replaced"][0]["to"].items() if k != "resname"}
    assert record["classes_applied"] == ["terminal_oxt_added", "nonstandard_replaced"]
    assert record["limitations"] == [K.RP1, K.RP2, K.RP4, K.RP5]
    source = C.structure(inputs.prepared_bytes)
    selenium = {res.seqid.num: next(a.pos for a in res if a.name == "SE") for res in source[0]["A"] if res.name == "MSE"}
    out = C.structure(raw)
    for res in out[0]["A"]:
        if res.seqid.num in selenium:
            assert (res.name, res.het_flag) == ("MET", "A")
            sd = next(a for a in res if a.name == "SD")
            assert sd.element.name == "S" and sd.pos.dist(selenium[res.seqid.num]) <= 1e-9
    assert "MSE" not in {res.name for chain in out[0] for res in chain}


def test_chain_part_merge_keeps_every_residue_identity_and_coordinate():
    for name in ("4ins", "1ay7"):
        inputs, raw, record = built(name, "keep_all")
        source = C.structure(inputs.prepared_bytes)
        out = C.structure(raw)
        assert len({c.name for c in source[0]}) < len(source[0])
        assert sorted(C.key(c, r) for c in source[0] for r in c) == sorted(C.key(c, r) for c in out[0] for r in c)
        assert [c.name for c in out[0]] == list(dict.fromkeys(c.name for c in source[0]))
        assert record["classes_applied"] == ["chain_parts_merged"] and record["added_atoms"] == []
        assert record["limitations"] == [K.RP1, K.RP2, K.RP6]
        assert record["collisions"]["protein"] == {"min_distance_A": None, "count_lt_2_0": 0, "count_lt_1_5": 0,
                                                   "min_pair": None}
        assert record["new_atom_rounding"] == {"decimals": 4, "max_abs_delta_A": 0.0}


def test_same_inputs_give_the_same_bytes_and_record():
    inputs, raw, record = built("8vf6")
    again_raw, again_record = sr.build_repaired(inputs, C.additions("8vf6"))
    assert again_raw == raw and canonical_json(again_record) == canonical_json(record)
    assert sr.validated_repair(inputs, raw, json.loads(canonical_json(record))) is not None


def test_every_coordinate_survives_the_m21_four_decimal_pdbx_text():
    """M21 writes the protein with ``%10.4f`` and grafts at 1e-9 A (T1 D1): every coordinate must be at four decimals."""
    for name in ("8vf6", "1mq4", "1cll"):
        _inputs, raw, _record = built(name)
        for chain in C.structure(raw)[0]:
            for res in chain:
                for atom in res:
                    for value in (atom.pos.x, atom.pos.y, atom.pos.z):
                        assert abs(float(f"{value:10.4f}") - value) <= 1e-9


def _ubq_rows(numbers, names=None, label=None) -> list[dict]:
    rows = []
    for res in C.structure((C.FIX / "public_1ubq.cif").read_bytes())[0]["A"]:
        if res.seqid.num not in numbers:
            continue
        ref = {"model_number": 1, "chain_auth": "A", "chain_label": label[0] if label else "A", "seq_auth": res.seqid.num,
               "seq_label": label[1] if label else res.label_seq, "icode": "", "resname": res.name}
        rows += [{"residue": ref, "atom_name": a.name, "element": a.element.name,
                  "coordinates_A": [a.pos.x, a.pos.y, a.pos.z], "origin": "gap_residue" if label else "side_chain"}
                 for a in res if names is None or a.name in names]
    return rows


def test_pdb_format_gap_residues_take_the_reread_label_chain():
    inputs = C.synthetic("synthetic-gap.pdb")
    raw, record = sr.build_repaired(inputs, _ubq_rows((30, 31, 32), label=("Axp", None)))
    sr.validated_repair(inputs, raw, record)
    assert [(r["seq_auth"], r["chain_label"], r["seq_label"], r["resname"]) for r in record["gaps"][0]["residues"]] == [
        (30, "Axp", None, "ILE"), (31, "Axp", None, "GLN"), (32, "Axp", None, "ASP")]
    out = C.structure(raw)
    reread = [C.key(c, r) for c in out[0] for r in c if r.seqid.num in (30, 31, 32)]
    assert reread == [("A", 30, "", "Axp", None, "ILE"), ("A", 31, "", "Axp", None, "GLN"),
                      ("A", 32, "", "Axp", None, "ASP")]
    original = {(r.seqid.num, a.name): a.pos for r in C.structure((C.FIX / "public_1ubq.cif").read_bytes())[0]["A"]
                for a in r}
    assert all(a.pos.dist(original[(r.seqid.num, a.name)]) <= 1e-9 for c in out[0] for r in c for a in r)
    assert record["counts"]["protein_heavy_atoms"] == 602 and record["limitations"] == [K.RP1, K.RP2, K.RP3]


def test_input_calc_flags_are_cleared_and_counted():
    inputs = C.synthetic("synthetic-calc-flag.cif")
    flagged = sum(a.calc_flag != gemmi.CalcFlag.NotSet for c in C.structure(inputs.prepared_bytes)[0] for r in c
                  for a in r)
    assert flagged == 17
    raw, record = sr.build_repaired(inputs, _ubq_rows((6,), names=("CE", "NZ")))
    assert record["unchanged"]["input_calc_flag_cleared"] == flagged
    marked = [(r.seqid.num, a.name) for c in C.structure(raw)[0] for r in c for a in r
              if a.calc_flag != gemmi.CalcFlag.NotSet]
    assert marked == [(6, "CE"), (6, "NZ")]
    assert raw.count(b" c\n") == 2


def test_pdb_format_mse_rendering_of_1rnh_builds():
    raw_pdb = C.structure((C.FIX / "public_1rnh.cif").read_bytes()).make_pdb_string().encode()
    inputs = C.prepared(raw_pdb, "pdb")[0]
    rows = [{**row, "residue": {**row["residue"], "chain_label": "Axp", "seq_label": None}}
            for row in C.additions("1rnh")]
    raw, record = sr.build_repaired(inputs, rows)
    sr.validated_repair(inputs, raw, record)
    assert [r["record_type"] for r in record["replaced"]] == [{"from": "HETATM", "to": "ATOM"}] * 3
    assert record["limitations"] == [K.RP1, K.RP2, K.RP5]


def test_the_builder_refuses_unrepairable_inputs_and_bad_rows():
    with pytest.raises(ToolFailure) as caught:
        sr.build_repaired(C.public("1ubq"), [])
    assert caught.value.detail["reason_code"] == "nothing_to_repair"
    inputs = C.public("1hsg")
    good = C.additions("1hsg")
    bad = {
        "malformed": [{**good[0], "extra": 1}],
        "unknown residue": [{**good[0], "residue": {**good[0]["residue"], "seq_auth": 999}}],
        "backbone atom": [{**good[0], "atom_name": "N", "element": "N"}],
        "hydrogen": [{**good[0], "atom_name": "H", "element": "H"}],
        "already observed": [{**good[0], "atom_name": "CB", "element": "C"}],
        "not in template": [{**good[0], "atom_name": "XX", "element": "C"}],
        "wrong element": [{**good[0], "element": "N"}],
        "duplicate": [good[0], good[0]],
        "non-finite": [{**good[0], "coordinates_A": [math.nan, 0.0, 0.0]}],
    }
    for label, rows in bad.items():
        with pytest.raises(ToolFailure) as caught:
            sr.build_repaired(inputs, rows)
        assert caught.value.detail["reason_code"] == "unexpected_atoms_added", label


# ------------------------------------------------------------------------------------------------ validator

def _edit(raw: bytes, change) -> bytes:
    st = C.structure(raw)
    change(st[0])
    return C.write(st)


def _first(model, predicate):
    return next(a for c in model for r in c for a in r if predicate(r, a))


def _expect(code: str, inputs, raw, record) -> None:
    with pytest.raises(ToolFailure) as caught:
        sr.validated_repair(inputs, raw, record)
    assert caught.value.detail["reason_code"] == code


def test_validator_catches_a_moved_observed_atom():
    inputs, raw, record = built("8vf6")

    def move(model):
        atom = _first(model, lambda r, a: a.calc_flag == gemmi.CalcFlag.NotSet)
        atom.pos = gemmi.Position(atom.pos.x + 1e-3, atom.pos.y, atom.pos.z)
    _expect("coordinates_changed", inputs, _edit(raw, move), record)

    def rename(model):
        _first(model, lambda r, a: a.calc_flag == gemmi.CalcFlag.NotSet and a.name == "CA").name = "CX"
    _expect("coordinates_changed", inputs, _edit(raw, rename), record)


def test_validator_catches_atoms_outside_the_record_and_wrong_marks():
    inputs, raw, record = built("8vf6")

    def extra(model):
        res = next(r for c in model for r in c if r.name == "GLY" and r.het_flag == "A")
        atom = gemmi.Atom()
        atom.name, atom.element, atom.calc_flag = "CB", gemmi.Element("C"), gemmi.CalcFlag.Calculated
        atom.pos = res[1].pos
        res.add_atom(atom)
    _expect("unexpected_atoms_added", inputs, _edit(raw, extra), record)

    def unmark(model):
        _first(model, lambda r, a: a.calc_flag == gemmi.CalcFlag.Calculated).calc_flag = gemmi.CalcFlag.NotSet
    _expect("unexpected_atoms_added", inputs, _edit(raw, unmark), record)

    def mark(model):
        _first(model, lambda r, a: a.calc_flag == gemmi.CalcFlag.NotSet).calc_flag = gemmi.CalcFlag.Calculated
    _expect("unexpected_atoms_added", inputs, _edit(raw, mark), record)

    def ligand_atom(model):
        res = next(r for c in model for r in c if r.name == "A1AAY")
        atom = gemmi.Atom()
        atom.name, atom.element, atom.calc_flag = "C99", gemmi.Element("C"), gemmi.CalcFlag.Calculated
        res.add_atom(atom)
    _expect("unexpected_atoms_added", inputs, _edit(raw, ligand_atom), record)


def test_validator_catches_gap_residue_identity_changes():
    inputs, raw, record = built("8vf6")

    def renumber(model):
        next(r for c in model for r in c if r.seqid.num == 273 and r.subchain == "A").seqid = gemmi.SeqId(973, " ")
    _expect("repair_identity_mismatch", inputs, _edit(raw, renumber), record)

    def drop(model):
        chain = model["A"]
        del chain[next(i for i, r in enumerate(chain) if r.seqid.num == 280)]
    _expect("repair_identity_mismatch", inputs, _edit(raw, drop), record)


def test_validator_catches_record_changes():
    inputs, raw, record = built("8vf6")
    for path, value in ((("counts", "added_atoms"), 265), (("new_atom_rounding", "max_abs_delta_A"), 1.0),
                        (("unchanged", "input_calc_flag_cleared"), 1), (("limitations",), [K.RP1]),
                        (("collisions", "protein", "count_lt_2_0"), 0), (("chain_ends",), []),
                        (("parameters", "waters"), "keep_all"), (("method", "pdbfixer_version"), "1.11")):
        changed = copy.deepcopy(record)
        target = changed
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        _expect("repair_record_mismatch", inputs, raw, changed)
    missing = {k: v for k, v in record.items() if k != "collisions"}
    _expect("repair_record_mismatch", inputs, raw, missing)

    def unrounded(model):
        atom = _first(model, lambda r, a: a.calc_flag == gemmi.CalcFlag.Calculated)
        atom.pos = gemmi.Position(atom.pos.x + 1e-6, atom.pos.y, atom.pos.z)
    _expect("repair_record_mismatch", inputs, _edit(raw, unrounded), record)
