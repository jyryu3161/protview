"""M17 T3a: the isolated RDKit worker (``mw/jobs/ligand_worker.py``) run as a real subprocess.

The worker runs in the pinned ``.deps/prolif/venv-locked`` interpreter exactly as the guardian launches it
(``python -I ligand_worker.py`` in a private directory with ``input.json`` + ``structure.json``). The server
test process never imports RDKit. When the pinned environment is missing these tests fail; they never skip.

Expected values come from the T1 hand oracle (``fixtures/ligand/expected.json``) and from hand-written SMILES
in this file. RDKit is used on the test side only to canonicalise hand-written SMILES (final comparison), never
through the worker's own functions -- except the PAINS panel, which exercises the worker's PAINS function on
the hand oracle's known positive/negative molecules.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from mw import ligand_constants as C
from mw.ligand_site import check_site

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend/mw/jobs/ligand_worker.py"
WORKER_PYTHON = ROOT / ".deps/prolif/venv-locked/bin/python"
FIX = Path(__file__).parent / "fixtures/ligand"
CHEM_FIX = Path(__file__).parent / "fixtures/chemical"
EXPECTED = json.loads((FIX / "expected.json").read_text())
RULES = json.loads((FIX / "synthetic-reaction-rules.json").read_text())["rules"]
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
NO_H = "synthetic-parent-methacetin-no-h.sdf"
EXPLICIT_H = "synthetic-parent-methacetin-explicit-h.sdf"
STEREO_PARENT = "synthetic-parent-stereo-methoxyethylbenzene.sdf"
LIMITS = {"max_candidates": C.MAX_CANDIDATES, "max_attempts": C.MAX_ATTEMPTS}


def _engine() -> None:
    assert WORKER_PYTHON.is_file(), f"pinned RDKit worker interpreter missing at {WORKER_PYTHON} (no skip)"


def _entry(raw: bytes, key: str) -> dict:
    return {key: base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def _parent(raw: bytes) -> dict:
    return _entry(raw, "sdf_b64")


def _block(kind: str, raw: bytes) -> dict:
    return {"kind": kind, **_entry(raw, "b64")}


SMI = _block("building_blocks_smiles", (FIX / "synthetic-blocks.smi").read_bytes())
SDF = _block("building_blocks_sdf", (FIX / "synthetic-blocks.sdf").read_bytes())


def _call(tmp_path: Path, adapter: str, payload: dict) -> tuple[int, bytes | None, dict | None]:
    _engine()
    root = tmp_path / f"attempt_{len(list(tmp_path.iterdir()))}"
    root.mkdir()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps({"adapter": adapter, "nonce": "0" * 32, "job_id": "job_t",
                                                 "attempt_id": "att_t",
                                                 "input_sha256": hashlib.sha256(raw).hexdigest()}))
    proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER)], cwd=root, capture_output=True, timeout=120,
                          check=False, env={**ENV, "TMPDIR": str(root)})
    result = (root / "result.json").read_bytes() if (root / "result.json").exists() else None
    error = json.loads((root / "error.json").read_text()) if (root / "error.json").exists() else None
    assert len(proc.stderr) < 64_000
    return proc.returncode, result, error


def _ok(tmp_path: Path, adapter: str, payload: dict) -> dict:
    code, result, error = _call(tmp_path, adapter, payload)
    assert code == 0 and result is not None and error is None, error
    return json.loads(result)


def _fail(tmp_path: Path, adapter: str, payload: dict) -> dict:
    code, result, error = _call(tmp_path, adapter, payload)
    assert code == 1 and result is None and error is not None
    assert set(error) == {"schema", "error_class", "reason_code", "message"}
    assert error["schema"] == "ligand_worker_error@1"
    return error


def _inspect(tmp_path: Path, parent_raw: bytes, blocks: list | None = None, rules: list | None = None) -> dict:
    return _ok(tmp_path, "rdkit_inspect_v1", {"schema": "ligand_inspect_worker_input@1", "parent": _parent(parent_raw),
                                              "blocks": blocks or [], "rules": rules or []})


def _enum_payload(parent_raw: bytes, blocks: list, site: list, *, fixed: bool = True, rules: list | None = None,
                  limits: dict | None = None) -> dict:
    return {"schema": "ligand_enumerate_worker_input@1", "parent": _parent(parent_raw), "blocks": blocks,
            "site_atoms": site, "use_fixed": fixed, "rules": rules or [], "limits": limits or LIMITS}


def _enumerate(tmp_path: Path, *args, **kwargs) -> dict:
    return _ok(tmp_path, "rdkit_enumerate_v1", _enum_payload(*args, **kwargs))


def _canon(smiles: list[str]) -> list[str]:
    """RDKit canonical isomeric SMILES of hand-written strings (test-side canonicalisation only)."""
    _engine()
    code = ("import json,sys\nfrom rdkit import Chem\n"
            "print(json.dumps([Chem.MolToSmiles(Chem.MolFromSmiles(s)) for s in json.load(sys.stdin)]))")
    out = subprocess.run([str(WORKER_PYTHON), "-I", "-c", code], input=json.dumps(smiles), capture_output=True,
                         text=True, timeout=120, check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _hand(name: str) -> str:
    return EXPECTED["properties"][name]["hand_smiles"]


def _valid_rules() -> list[dict]:
    return [{"rule_id": f"user_{i}", "text": RULES[i - 1]} for i in (1, 2, 3, 10)]


# ------------------------------------------------------------------ inspection: parent table and numbering
@pytest.mark.parametrize("variant", ["no_h", "explicit_h"])
def test_inspect_parent_table_matches_hand_oracle_and_feeds_site_check(tmp_path, variant):
    hand = EXPECTED["parents"][variant]
    out = _inspect(tmp_path, (FIX / hand["file"]).read_bytes())
    assert out["schema"] == "ligand_inspect_worker_output@1" and out["rdkit_version"] == "2026.03.6"
    parent = out["parent"]
    assert parent["atoms_in_sdf"] == hand["atoms_in_sdf"] and parent["heavy_atom_count"] == 12
    assert [{"serial": a["serial"], "element": a["element"]} for a in parent["atoms"]] == hand["heavy_atoms"]
    assert all(set(a) == {"serial", "element", "formal_charge", "neighbors"} and a["formal_charge"] == 0
               for a in parent["atoms"])
    assert sorted([b["a"], b["b"], b["order"]] for b in parent["bonds"]) == sorted(hand["bonds_heavy"])
    assert [h["serial"] for h in parent["hydrogens"]] == hand.get("hydrogen_serials", [])
    graph = {key: parent[key] for key in ("atoms", "bonds", "hydrogens")}
    site = check_site(graph, hand["site_methoxy"])
    assert site["valid"] and site["core_atoms"] == hand["core_retained_parent_atoms"]
    assert [site["crossing_bonds"][0][k] for k in ("core_atom", "site_atom", "order")] == hand["crossing_bond"]
    assert site["site_hydrogens"] == hand.get("site_hydrogens_removed_with_site", [])
    assert out["input_sha256"]["parent"] == hashlib.sha256((FIX / hand["file"]).read_bytes()).hexdigest()
    # Numbered 2D drawing: one <text class='note'> per heavy atom carrying its SDF serial, in atom order.
    svg = parent["svg"]
    notes = re.findall(r"<text[^>]*class='note'[^>]*>([^<]*)</text>", svg)
    assert "".join(notes) == "".join(str(a["serial"]) for a in hand["heavy_atoms"])
    assert "<script" not in svg and parent["svg_bytes"] == len(svg.encode()) <= 256 * 1024


def test_inspect_parent_properties_match_hand_values(tmp_path):
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes())
    _assert_properties(out["parent"]["properties"], "parent_methacetin")
    assert out["parent"]["canonical_smiles"] == _canon([_hand("parent_methacetin")])[0]


def _assert_properties(values: dict, name: str) -> None:
    hand = EXPECTED["properties"][name]
    assert set(values) == set(C.PROPERTY_NAMES)
    assert abs(values["mol_weight"] - float(hand["mol_weight"]["value"])) < 5e-4
    assert abs(values["tpsa"] - float(hand["tpsa"]["value"])) < 5e-3
    for key in ("hbd", "hba", "heavy_atoms", "formal_charge"):
        assert values[key] == hand[key]["value"] and type(values[key]) is int
    assert values["rotatable_bonds"] == hand["rotatable_bonds_strict"]["value"]
    assert type(values["crippen_logp"]) is float  # no hand oracle for Crippen; a finite RDKit value is stored


# ------------------------------------------------------------------ inspection: parent rejections
def _chain_sdf(n: int, *, carbonyl: bool = False) -> bytes:
    """Hand-built V2000 zig-zag carbon chain (optionally one C=O on every carbon)."""
    atoms = [("C", 1.5 * i, 0.75 * (i % 2)) for i in range(n)]
    bonds = [(i, i + 1, 1) for i in range(1, n)]
    if carbonyl:
        atoms += [("O", 1.5 * i, -1.5) for i in range(n)]
        bonds += [(i + 1, n + i + 1, 2) for i in range(n)]
    lines = ["SYNTHETIC chain", "  test", "", f"{len(atoms):3d}{len(bonds):3d}  0  0  0  0  0  0  0  0999 V2000"]
    lines += [f"{x:10.4f}{y:10.4f}{0:10.4f} {s:<3} 0  0  0  0  0  0  0  0  0  0  0  0" for s, x, y in atoms]
    lines += [f"{a:3d}{b:3d}  {o}  0" for a, b, o in bonds]
    return ("\n".join([*lines, "M  END", "$$$$", ""])).encode()


def _replace_atom_symbol(raw: bytes, serial: int, symbol: str) -> bytes:
    lines = raw.decode().splitlines()
    row = lines[3 + serial]
    lines[3 + serial] = row[:31] + f"{symbol:<3}" + row[34:]
    return ("\n".join(lines) + "\n").encode()


V3000 = b"""v3000 parent
  hand-written

  0  0  0     0  0            999 V3000
M  V30 BEGIN CTAB
M  V30 COUNTS 2 1 0 0 0
M  V30 BEGIN ATOM
M  V30 1 C 0 0 0 0
M  V30 2 O 1.5 0 0 0
M  V30 END ATOM
M  V30 BEGIN BOND
M  V30 1 1 1 2
M  V30 END BOND
M  V30 END CTAB
M  END
$$$$
"""


@pytest.mark.parametrize("case,reason", [
    ("disconnected", "multiple_fragments"), ("selenium", "element_not_allowed"), ("two_records", "record_count"),
    ("v3000", "unparseable"), ("garbage", "unparseable"), ("chain257", "too_many_atoms")])
def test_inspect_parent_rejections_are_typed_failures(tmp_path, case, reason):
    no_h = (FIX / NO_H).read_bytes()
    raw = {"disconnected": (CHEM_FIX / "synthetic-disconnected-methane-water.sdf").read_bytes(),
           "selenium": _replace_atom_symbol(no_h, 3, "Se"), "two_records": no_h + no_h,
           "v3000": V3000, "garbage": b"not a molfile\n\n\nxx\nM  END\n$$$$\n", "chain257": _chain_sdf(257)}[case]
    error = _fail(tmp_path, "rdkit_inspect_v1", {"schema": "ligand_inspect_worker_input@1",
                                                 "parent": _parent(raw), "blocks": [], "rules": []})
    assert error["error_class"] == "input_invalid" and error["reason_code"] == reason
    assert reason in C.PARENT_REJECT_REASONS


def test_inspect_accepts_256_heavy_atoms_but_fails_drawing_over_256_kib(tmp_path):
    assert _inspect(tmp_path, _chain_sdf(256))["parent"]["heavy_atom_count"] == 256
    error = _fail(tmp_path, "rdkit_inspect_v1", {"schema": "ligand_inspect_worker_input@1",
                                                 "parent": _parent(_chain_sdf(128, carbonyl=True)),
                                                 "blocks": [], "rules": []})
    assert (error["error_class"], error["reason_code"]) == ("resource_exceeded", "svg_limit")


# ------------------------------------------------------------------ inspection: blocks and rules
def test_inspect_block_libraries_and_rules_match_hand_oracle(tmp_path):
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes(), [SMI, SDF], RULES)
    for summary, key in zip(out["block_libraries"], ("smiles", "sdf"), strict=True):
        hand = EXPECTED["block_libraries"][key]
        assert summary["accepted"] == hand["summary"]["accepted"]
        assert {r: n for r, n in summary["rejected_counts"].items() if n} == hand["summary"]["rejected_counts"]
        assert set(summary["rejected_counts"]) == set(C.BLOCK_REJECT_REASONS)
        assert summary["fixed_targets"] == hand["summary"]["fixed_targets"]
        assert summary["rule_targets"] == hand["summary"]["rule_targets"]
        assert summary["rejected"] == [{"ordinal": r["ordinal"], "name": r["name"], "reason": r["reason"]}
                                       for r in hand["records"] if r["status"] == "rejected"]
        assert summary["block_limit_reached"] is False
        assert summary["records_total"] == summary["records_read"] == len(hand["records"])
    assert [(r["rule_id"], r["status"]) for r in out["rules"]] == [
        (r["rule_id"], r["status"]) for r in EXPECTED["rules"]["results"]]
    assert out["rules"][8]["text"] is None and out["rules"][9]["text"] == RULES[9]
    assert len(RULES[9].encode()) == C.MAX_RULE_BYTES


def test_block_limit_reads_the_first_thousand_records(tmp_path):
    raw = "".join(f"*C{'C' * (i % 3)} b{i}\n" for i in range(1, 1003)).encode()
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes(), [_block("building_blocks_smiles", raw)])
    summary = out["block_libraries"][0]
    assert (summary["records_total"], summary["records_read"], summary["accepted"]) == (1002, 1000, 1000)
    assert summary["block_limit_reached"] is True and summary["rejected"] == []


def test_block_limit_is_shared_by_both_libraries_in_input_order(tmp_path):
    first = _block("building_blocks_smiles", "".join(f"*C{'C' * (i % 3)} a{i}\n" for i in range(1, 601)).encode())
    second = _block("building_blocks_smiles", "".join(f"*N{'C' * (i % 3)} b{i}\n" for i in range(1, 601)).encode())
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes(), [first, second])
    one, two = out["block_libraries"]
    assert (one["records_total"], one["records_read"], one["accepted"], one["block_limit_reached"]) == (
        600, 600, 600, False)
    assert (two["records_total"], two["records_read"], two["accepted"], two["block_limit_reached"]) == (
        600, 400, 400, True)
    full = _block("building_blocks_smiles", "".join(f"*C c{i}\n" for i in range(1, 1001)).encode())
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes(), [full, second])
    assert [(s["records_read"], s["block_limit_reached"]) for s in out["block_libraries"]] == [(1000, False),
                                                                                             (0, True)]


def test_block_name_over_128_characters_is_unparseable(tmp_path):
    long_name, ok_name = "n" * 129, "m" * 128
    smiles = _block("building_blocks_smiles", f"*C {long_name}\n*Cl {ok_name}\n".encode())
    sdf_raw = (FIX / "synthetic-blocks.sdf").read_text().split("$$$$")[0].lstrip("\n").splitlines()
    sdf = _block("building_blocks_sdf", ("\n".join([long_name, *sdf_raw[1:]]) + "\n$$$$\n").encode())
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes(), [smiles, sdf])
    assert out["block_libraries"][0]["rejected"] == [{"ordinal": 1, "name": "block_1", "reason": "unparseable"}]
    assert out["block_libraries"][0]["accepted"] == 1
    assert out["block_libraries"][1]["rejected"] == [{"ordinal": 1, "name": "block_1", "reason": "unparseable"}]


def test_output_echoes_the_control_job_and_attempt(tmp_path):
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes())
    assert (out["job_id"], out["attempt_id"]) == ("job_t", "att_t")
    out = _enumerate(tmp_path, (FIX / NO_H).read_bytes(), [SMI], [11, 12])
    assert (out["job_id"], out["attempt_id"]) == ("job_t", "att_t")


def test_duplicate_name_spans_libraries_and_unnamed_records_use_their_ordinal(tmp_path):
    first = _block("building_blocks_smiles", b"# header\n\n*C methyl\n*Cl\n")
    second = _block("building_blocks_smiles", b"*N methyl\n*O block_2\n*F\n")
    out = _inspect(tmp_path, (FIX / NO_H).read_bytes(), [first, second])
    assert out["block_libraries"][0]["rejected"] == []
    assert out["block_libraries"][1]["rejected"] == [{"ordinal": 1, "name": "methyl", "reason": "duplicate_name"},
                                                     {"ordinal": 2, "name": "block_2", "reason": "duplicate_name"}]
    assert out["block_libraries"][1]["accepted"] == 1  # "*F" -> block_3


# ------------------------------------------------------------------ enumeration against the hand oracle
FIXED_SMILES_PRODUCTS = ["fixed_methyl", "fixed_chloro", "fixed_morpholino", "fixed_phenyl",
                         "fixed_trifluoromethyl", "fixed_hydroxy_block_15"]


def _counts_subset(counts: dict) -> dict:
    return {"raw_products": counts["raw_products"], "candidates": counts["candidates"],
            "duplicate_products": counts["duplicate_products"],
            "rejected": {r: n for r, n in counts["rejected"].items() if n}, "not_applicable": counts["not_applicable"]}


def test_fixed_replacement_smiles_library(tmp_path):
    out = _enumerate(tmp_path, (FIX / NO_H).read_bytes(), [SMI], [11, 12])
    gen = EXPECTED["generation_with_site_methoxy"]
    assert [row["smiles"] for row in out["candidates"]] == _canon([_hand(n) for n in FIXED_SMILES_PRODUCTS])
    assert _counts_subset(out["counts"]) == gen["fixed_smiles_counts"]
    assert out["counts"]["blocks_accepted"] == 12
    for row, name in zip(out["candidates"], FIXED_SMILES_PRODUCTS, strict=True):
        assert row["id"] == "c_" + hashlib.sha256(row["smiles"].encode()).hexdigest()[:16]
        assert row["retained_parent_atoms"] == list(range(1, 11)) and row["stereo_flag"] == "none"
        _assert_properties(row["properties"], name)
        expected_pains = ([{"catalog": "PAINS_A", "name": "anil_di_alk_A(478)"}] if name == "fixed_morpholino" else [])
        assert row["pains"] == {"matches": expected_pains}
    assert out["candidates"][0]["origins"] == [{"rule_id": "fixed", "block_name": "methyl"},
                                               {"rule_id": "fixed", "block_name": "methyl_alt"}]
    assert out["rules_used"] == [{"rule_id": "fixed", "method": "replace_single_bond_v1", "text": None}]
    assert out["limit_reached"] is False and out["stop_reason"] is None
    assert out["limitations"] == list(C.LIMITATIONS)
    _assert_properties(out["parent_properties"], "parent_methacetin")


def test_fixed_replacement_sdf_library_with_rgroup_marker(tmp_path):
    out = _enumerate(tmp_path, (FIX / NO_H).read_bytes(), [SDF], [11, 12])
    names = ["fixed_sdf_ethyl", "phenacetin", "fixed_sdf_nitrile_block_3", "fixed_methyl"]
    assert [row["smiles"] for row in out["candidates"]] == _canon([_hand(n) for n in names])
    assert _counts_subset(out["counts"]) == EXPECTED["generation_with_site_methoxy"]["fixed_sdf_counts"]
    assert [row["origins"][0]["block_name"] for row in out["candidates"]] == [
        "sdf_ethyl", "sdf_rgroup_ethoxy", "block_3", "sdf_methyl"]


@pytest.mark.parametrize("parent_file,site", [(NO_H, [11, 12]), (EXPLICIT_H, [19, 20])])
def test_fixed_and_rules_both_libraries_union(tmp_path, parent_file, site):
    out = _enumerate(tmp_path, (FIX / parent_file).read_bytes(), [SMI, SDF], site, rules=_valid_rules())
    gen = EXPECTED["generation_with_site_methoxy"]
    union = gen["union_unique_candidates_fixed_plus_valid_rules_both_libraries"]
    assert sorted(row["smiles"] for row in out["candidates"]) == sorted(_canon([_hand(n) for n in union]))
    by_smiles = {row["smiles"]: row for row in out["candidates"]}
    methyl, phenacetin, acetate = _canon([_hand("fixed_methyl"), _hand("phenacetin"), _hand("rule_aryl_acetate")])
    assert by_smiles[methyl]["origins"] == [{"rule_id": "fixed", "block_name": n}
                                            for n in ("methyl", "methyl_alt", "sdf_methyl")]
    assert by_smiles[phenacetin]["origins"] == [{"rule_id": "fixed", "block_name": "sdf_rgroup_ethoxy"},
                                                {"rule_id": "user_1", "block_name": "bromoethane"}]
    assert by_smiles[acetate]["origins"] == [{"rule_id": "user_2", "block_name": "acetic_acid"}]
    _assert_properties(by_smiles[acetate]["properties"], "rule_aryl_acetate")
    counts = out["counts"]
    # fixed 12 raw (8 + 4); user_1: bromoethane -> phenacetin, bromomethane -> parent; user_2: acetic acid;
    # user_3: one acetyl match per bromide (outside the site); user_10 never matches.
    assert counts["raw_products"] == 17 and counts["candidates"] == 10 and counts["duplicate_products"] == 3
    assert {r: n for r, n in counts["rejected"].items() if n} == {"equals_parent": 2, "outside_site": 2}
    assert counts["not_applicable"] == {"fixed": 5, "user_1": 13, "user_2": 13, "user_3": 13, "user_10": 13}
    expected_core = EXPECTED["parents"]["no_h" if parent_file == NO_H else "explicit_h"]["core_retained_parent_atoms"]
    assert out["retained_parent_atoms"] == expected_core
    assert all(row["retained_parent_atoms"] == expected_core for row in out["candidates"])
    assert [r["rule_id"] for r in out["rules_used"]] == ["fixed", "user_1", "user_2", "user_3", "user_10"]
    assert out["methods"] == ["replace_single_bond_v1"] + ["user_reaction_smarts_v1"] * 4


def test_rules_only_outside_site_counts(tmp_path):
    out = _enumerate(tmp_path, (FIX / NO_H).read_bytes(), [SMI], [11, 12], fixed=False,
                     rules=[{"rule_id": "user_3", "text": RULES[2]}])
    assert out["candidates"] == [] and out["counts"]["raw_products"] == 1
    assert {r: n for r, n in out["counts"]["rejected"].items() if n} == {"outside_site": 1}
    assert out["counts"]["not_applicable"] == {"user_3": 9} and out["limit_reached"] is False


# ------------------------------------------------------------------ caps: deterministic stop points
@pytest.mark.parametrize("limits,smiles_names,raw,stop", [
    ({"max_candidates": 3, "max_attempts": 20_000}, FIXED_SMILES_PRODUCTS[:3], 4, "candidate_limit"),
    ({"max_candidates": 6, "max_attempts": 20_000}, FIXED_SMILES_PRODUCTS, 8, None),
    ({"max_candidates": 2_000, "max_attempts": 5}, FIXED_SMILES_PRODUCTS[:4], 5, "attempt_limit"),
    ({"max_candidates": 2_000, "max_attempts": 8}, FIXED_SMILES_PRODUCTS, 8, None)])
def test_candidate_and_attempt_caps(tmp_path, limits, smiles_names, raw, stop):
    # Generation order of the SMILES library (fixed): methyl, chloro, methoxy(=parent), morpholino, phenyl,
    # trifluoromethyl, methyl_alt(duplicate), block_15.
    out = _enumerate(tmp_path, (FIX / NO_H).read_bytes(), [SMI], [11, 12], limits=limits)
    assert [row["smiles"] for row in out["candidates"]] == _canon([_hand(n) for n in smiles_names])
    assert out["counts"]["raw_products"] == raw and out["counts"]["rejected"]["equals_parent"] == 1
    assert out["limit_reached"] is (stop is not None) and out["stop_reason"] == stop
    assert out["limits"] == limits


def test_same_input_same_bytes(tmp_path):
    payload = _enum_payload((FIX / EXPLICIT_H).read_bytes(), [SMI, SDF], [19, 20], rules=_valid_rules())
    first, second = (_call(tmp_path, "rdkit_enumerate_v1", payload)[1] for _ in range(2))
    assert first is not None and first == second
    inspect_payload = {"schema": "ligand_inspect_worker_input@1", "parent": _parent((FIX / EXPLICIT_H).read_bytes()),
                       "blocks": [SMI, SDF], "rules": RULES}
    first, second = (_call(tmp_path, "rdkit_inspect_v1", inspect_payload)[1] for _ in range(2))
    assert first is not None and first == second


# ------------------------------------------------------------------ stereo (hand-written expectations)
STEREO_BLOCKS = _block("building_blocks_smiles", (FIX / "synthetic-stereo-blocks.smi").read_bytes())
# Parent C[C@H](OC)c1ccccc1 (serials 1 CH3, 2 stereocentre, 3 O, 4 OCH3, 5-10 ring); site = [3, 4].
# The new group takes the methoxy position, so the stereocentre keeps its written parity.
STEREO_EXPECTED = [
    ("chloro", "C[C@H](Cl)c1ccccc1", "none"),
    ("ethyl", "C[C@H](CC)c1ccccc1", "none"),
    ("methyl", "CC(C)c1ccccc1", "parent_stereo_lost"),            # two methyls: centre no longer stereogenic
    ("sec_butyl", "C[C@H](C(C)CC)c1ccccc1", "new_unspecified_center"),  # block CH unspecified
    ("sec_butyl_specified", "C[C@H]([C@@H](C)CC)c1ccccc1", "none"),     # block stereo kept
    ("bromoethane", "C[C@H](OCC)c1ccccc1", "none"),                # user rule, centre untouched
]


def test_stereo_kept_and_flags(tmp_path):
    out = _enumerate(tmp_path, (FIX / STEREO_PARENT).read_bytes(), [STEREO_BLOCKS], [3, 4],
                     rules=[{"rule_id": "user_1", "text": RULES[0]}])
    assert out["parent_canonical_smiles"] == _canon(["C[C@H](OC)c1ccccc1"])[0]
    expected = _canon([smiles for _, smiles, _ in STEREO_EXPECTED])
    assert [(row["origins"][0]["block_name"], row["smiles"], row["stereo_flag"]) for row in out["candidates"]] == [
        (name, smiles, flag) for (name, _, flag), smiles in zip(STEREO_EXPECTED, expected, strict=True)]
    assert {row["stereo_flag"] for row in out["candidates"]} == set(C.STEREO_FLAGS)
    assert out["retained_parent_atoms"] == [1, 2, 5, 6, 7, 8, 9, 10]


# ------------------------------------------------------------------ enumeration refusals
@pytest.mark.parametrize("site,reason", [([], "site_empty"), ([99], "site_atom_unknown"),
                                         (list(range(1, 13)), "core_empty"), ([5], "crossing_bond_count"),
                                         ([3], "crossing_bond_not_single")])
def test_enumerate_rechecks_the_site(tmp_path, site, reason):
    error = _fail(tmp_path, "rdkit_enumerate_v1", _enum_payload((FIX / NO_H).read_bytes(), [SMI], site))
    assert (error["error_class"], error["reason_code"]) == ("input_invalid", reason)
    assert reason in C.SITE_REASONS


@pytest.mark.parametrize("fixed,rules,reason", [
    (True, [{"rule_id": "user_7", "text": RULES[6]}], "rule_invalid"),
    (True, [{"rule_id": "user_1", "text": RULES[0]}, {"rule_id": "user_8", "text": RULES[7]}], "rule_invalid"),
    (False, [], "no_generation_method")])
def test_enumerate_refuses_invalid_rules_and_no_method(tmp_path, fixed, rules, reason):
    error = _fail(tmp_path, "rdkit_enumerate_v1",
                  _enum_payload((FIX / NO_H).read_bytes(), [SMI], [11, 12], fixed=fixed, rules=rules))
    assert (error["error_class"], error["reason_code"]) == ("input_invalid", reason)


def test_staged_hash_mismatch_is_fatal_without_result(tmp_path):
    _engine()
    root = tmp_path / "bad"
    root.mkdir()
    (root / "structure.json").write_bytes(b"{}")
    (root / "input.json").write_text(json.dumps({"adapter": "rdkit_inspect_v1", "input_sha256": "0" * 64}))
    proc = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER)], cwd=root, capture_output=True, timeout=120,
                          check=False, env=ENV)
    assert proc.returncode == 1 and not (root / "result.json").exists()
    assert json.loads((root / "error.json").read_text())["error_class"] == "fatal"


# ------------------------------------------------------------------ PAINS panel and handshake
def test_pains_panel_known_positives_and_negatives():
    _engine()
    code = ("import importlib.util,json,sys\nfrom rdkit import Chem\n"
            "spec=importlib.util.spec_from_file_location('lw',sys.argv[1]);m=importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "print(json.dumps({n:m.pains(Chem.MolFromSmiles(s))['matches'] for s,n in json.load(sys.stdin)}))")
    panel = [line.split() for line in (FIX / "pains-panel.smi").read_text().splitlines()
             if line.strip() and not line.startswith("#")]
    out = subprocess.run([str(WORKER_PYTHON), "-I", "-c", code, str(WORKER)], input=json.dumps(panel),
                         capture_output=True, text=True, timeout=120, check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    found = json.loads(out.stdout)
    for positive in EXPECTED["pains"]["positives"]:
        if "smiles_ref" not in positive:
            assert positive["must_include"] in found[positive["name"]]
    for negative in EXPECTED["pains"]["negatives"]:
        assert found[negative["name"]] == negative["expected_matches"]


def test_handshake_reports_pinned_rdkit_and_pains_catalogs():
    _engine()
    out = subprocess.run([str(WORKER_PYTHON), "-I", str(WORKER), "--handshake"], capture_output=True, text=True,
                         timeout=120, check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["rdkit_version"] == data["rdkit_version_expected"] == "2026.03.6"
    assert data["pains_catalog_entries"] == {"PAINS_A": 16, "PAINS_B": 55, "PAINS_C": 409}
    assert data["protocols"] == ["rdkit_inspect_v1", "rdkit_enumerate_v1"]
