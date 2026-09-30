"""M15 T6 residue numbering tool (``map_residue_numbering`` -> ``residue_numbering_map@1``).

Inputs: the public 1MQ4 mmCIF, the derived structures in ``fixtures/structures_m15`` and a reference FIXTURE set built
from ``fixtures/reference`` (verbatim kbase_kinase processed rows) by ``reference_fixture_set.build_fixture_set``.
Tests that need a different reference row build a SYNTHETIC fixture variant in memory (functions named
``_synthetic_*``; every one says what it changes) and install it with ``build_fixture_set(replace=...)``.

Independent oracles: SIFTS and the local alignment are two independent methods; the SIFTS segment arithmetic
(1MQ4 entity 1: PDBe 6-272 -> UniProt 125-391, read by hand from ``segments_fixture.jsonl``) is a third; KLIFS pocket
numbers are compared with KLIFS's own per-structure ``match_residues`` table (author number -> KLIFS position),
which the product never reads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import gemmi
import pytest
from reference_fixture_set import build_fixture_set

from mw import reference_snapshots as rs
from mw import residue_numbering as rn
from mw import sifts_mapping as sm
from mw.core.errors import FailureClass, ToolFailure
from mw.runtime.orchestrator import replay
from mw.tools import numbering
from mw.tools.structural import structure_residues
from mw.workspace import build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
REF = FIX / "reference"
STRUCT = FIX / "structures_m15"
CIF_1MQ4 = FIX / "public_1mq4.cif"
PDB_A200 = STRUCT / "derived_1mq4_a200_285_fixture.pdb"
PDB_ICODE = STRUCT / "derived_1mq4_a200_285_icode_fixture.pdb"
CIF_MSE = STRUCT / "derived_1mq4_a288_360_mse_fixture.cif"
PDB_MSE = STRUCT / "derived_1mq4_a288_360_mse_fixture.pdb"
PDB_TWO_CHAIN = STRUCT / "derived_1mq4_two_chain_fixture.pdb"
PDB_TWO_MODEL = STRUCT / "derived_1mq4_two_model_fixture.pdb"
TOOL = numbering.TOOL
# 1MQ4 entity 1 segment read by hand from segments_fixture.jsonl: PDBe 6..272 -> O14965 125..391 (offset 119).
SEGMENT_OFFSET = 119
# The one 1MQ4:A residue whose alignment position is a tie (see test_1mq4_oracle_sifts_vs_alignment).
TIE_RESIDUE = 388


# --- helpers ------------------------------------------------------------------------------------------------------

def _rows(rel: str) -> list[dict]:
    return [json.loads(line) for line in (REF / rel).read_bytes().splitlines() if line.strip()]


def _jsonl(rows: list[dict]) -> bytes:
    return b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows)


def _uniprot_sequence(accession: str) -> str:
    return next(r for r in _rows("uniprot/entries_fixture.jsonl") if r["id"] == accession)["data"]["sequence"]


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


def _registry():
    reg = build_registry()
    calls: list[dict] = []
    impl = reg.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    reg.impls[TOOL] = counted
    return reg, calls


def _run(tmp_path, name="run_numbering", dry_run=False):
    reg, calls = _registry()
    return new_run(tmp_path / "runs", run_id=name, dry_run=dry_run, registry=reg), calls


def _load(run, path: Path, model_index: int = 0) -> str:
    return run.call("load_structure", {"source": str(path), "model_index": model_index}).handle


def _map(run, structure, chains, pdb_id=None):
    out = run.call(TOOL, {"structure": structure, "pdb_id": pdb_id, "chains": chains})
    return out, run.store.load(out.handle)


def _chain(content, chain_auth="A"):
    return next(c for c in content["chains"] if c["chain_auth"] == chain_auth)


def _chain_rows(content, chain_auth="A"):
    return [r for r in content["rows"] if r["residue"]["chain_auth"] == chain_auth]


def _events(run, kind=None):
    return [e for e in run.events.read() if kind is None or e["type"] == kind]


def _created(run, kind):
    return [e for e in _events(run, "object_created") if e["kind"] == kind]


# --- synthetic reference variants (FIXTURE; each changes only what its docstring says) -----------------------------

def _synthetic_segments_1mq4(items: list[dict]) -> bytes:
    """SYNTHETIC: segments_fixture.jsonl with the 1MQ4 row's ``data`` replaced by ``items``."""
    rows = _rows("sifts/segments_fixture.jsonl")
    for row in rows:
        if row["pdb_id"] == "1MQ4":
            row["data"] = items
    return _jsonl(rows)


def _segment(**changes) -> dict:
    base = {"chain_id": "A", "coverage": 0.663, "entity_id": 1, "identity": 1.0, "res_end": 272, "res_start": 6,
            "uniprot": "O14965", "unp_end": 391, "unp_start": 125}
    return {**base, **changes}


def _synthetic_uniprot(transform) -> bytes:
    """SYNTHETIC: entries_fixture.jsonl passed through ``transform(rows) -> rows``."""
    return _jsonl(transform(copy.deepcopy(_rows("uniprot/entries_fixture.jsonl"))))


def _with_sequence(accession: str, sequence: str):
    def transform(rows):
        for row in rows:
            if row["id"] == accession:
                row["data"]["sequence"] = sequence
                row["data"]["sequence_length"] = len(sequence)
        return rows
    return transform


def _install(refroot, tag, replace):
    rs._VERIFIED.clear()
    return build_fixture_set(refroot, tag=tag, replace=replace)


# --- pure units ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("sifts", "alignment", "expected"), [
    ({"accession": "P1", "position": 5}, {"accession": "P1", "position": 5}, ("mapped", 5, None)),
    ({"accession": "P1", "position": 5}, {"accession": "P1", "position": 6}, ("conflict", None, "positions_differ")),
    ({"accession": "P1", "position": 5}, {"absent_reason": "alignment_gap", "absent_reasons": ["alignment_gap"]}, ("conflict", None, "one_method_only")),
    ({"absent_reason": "sifts_no_residue_row", "absent_reasons": ["sifts_no_residue_row"]}, {"accession": "P1", "position": 6},
     ("conflict", None, "one_method_only")),
    ({"accession": "P1", "position": 5}, {"absent_reason": "alignment_below_identity", "absent_reasons": ["alignment_below_identity"]},
     ("conflict", None, "one_method_only")),
    ({"absent_reason": "sifts_not_observed", "absent_reasons": ["sifts_not_observed"]}, {"absent_reason": "alignment_gap", "absent_reasons": ["alignment_gap"]}, ("unmapped", None, None)),
    ({"accession": "P1", "position": 5}, None, ("mapped", 5, None)),
    (None, {"accession": "P1", "position": 7}, ("mapped", 7, None)),
    ({"absent_reason": "sifts_outside_segments", "absent_reasons": ["sifts_outside_segments"]}, None, ("unmapped", None, None)),
    (None, {"absent_reason": "alignment_gap", "absent_reasons": ["alignment_gap"]}, ("unmapped", None, None)),
])
def test_row_status_every_case(sifts, alignment, expected):
    status, agreed, reason = rn.row_status(sifts, alignment)
    assert (status, agreed["position"] if agreed else None, reason) == expected
    with pytest.raises(ValueError):
        rn.row_status(None, None)


def test_alignment_threshold_boundaries_exact():
    assert rn.chain_reasons(90.0, 50.0) == []
    assert rn.chain_reasons(89.99999, 50.0) == ["alignment_below_identity"]
    assert rn.chain_reasons(90.0, 49.99999) == ["alignment_below_coverage"]
    assert rn.chain_reasons(10.0, 10.0) == ["alignment_below_identity", "alignment_below_coverage"]
    assert rn.chain_reasons(None, None) == ["alignment_below_identity", "alignment_below_coverage"]


def _res(seq_auth, seq_label=None, icode="", resname="ALA", chain="A"):
    return {"model_number": 1, "chain_auth": chain, "chain_label": chain if seq_label else None,
            "seq_auth": seq_auth, "seq_label": seq_label, "icode": icode, "resname": resname}


def test_alignment_answers_identity_boundary_by_hand():
    # 10 structure residues vs 10 UniProt letters, no gaps: one substitution -> 9/10 = 90.0 % (kept),
    # two substitutions -> 80 % (every residue absent, reason alignment_below_identity).
    names = ["ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE"]
    residues = [_res(i + 1, resname=n) for i, n in enumerate(names)]
    info, answers = rn.alignment_answers(residues, "PX", "ARNDCQEGHV")      # I -> V (BLOSUM62 +3)
    assert (info["aligned_pairs"], info["identical"], info["identity_pct"], info["coverage_pct"]) == (10, 9, 90.0, 100.0)
    assert info["chain_reason"] == [] and [a["position"] for a in answers] == list(range(1, 11))
    info, answers = rn.alignment_answers(residues, "PX", "ARNDCQEGYV")      # H -> Y, I -> V
    assert info["identity_pct"] == 80.0 and info["chain_reason"] == ["alignment_below_identity"]
    # both thresholds failed: every row carries both reasons (absent_reason = the first, kept for compatibility)
    _, both = rn.alignment_answers(residues[:4], "PX", "WWWWWWWWWWWWW")
    assert both == [{"absent_reason": "alignment_below_identity",
                     "absent_reasons": ["alignment_below_identity", "alignment_below_coverage"]}] * 4
    assert answers == [{"absent_reason": "alignment_below_identity", "absent_reasons": ["alignment_below_identity"]}] * 10


def test_alignment_answers_coverage_boundary_and_nonstandard_x():
    # 20 distinct residues; UniProt holds only the first 10 -> 10 aligned pairs = 50.0 % coverage (kept); 9 -> below.
    names = ["ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
             "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL"]
    residues = [_res(i + 1, resname=n) for i, n in enumerate(names)]
    info, answers = rn.alignment_answers(residues, "PX", "ARNDCQEGHI")
    assert info["ambiguous_residue_count"] == 0
    assert info["aligned_pairs"] == 10 and info["coverage_pct"] == 50.0 and info["chain_reason"] == []
    assert sum("position" in a for a in answers) == 10
    assert sum(a.get("absent_reason") == "alignment_gap" for a in answers) == 10
    info, _ = rn.alignment_answers(residues, "PX", "ARNDCQEGH")
    assert info["coverage_pct"] == 45.0 and info["chain_reason"] == ["alignment_below_coverage"]
    # MSE is X in the structure string; UniProt U/O/other letters are X for alignment only.
    info, answers = rn.alignment_answers([_res(1, resname="MSE"), _res(2, resname="ALA")], "PX", "UA")
    assert info["aligned_strings"] == {"structure": "XA", "uniprot": "XA"}
    assert rn.alignment_sequence("MUOA") == "MXXA"


def _sifts_chain(rows, segments):
    residues = tuple({"entity_id": e, "pdbe_number": p, "author_number": a, "icode": i, "residue_name": "ALA",
                      "observed": o, "exception_reason": None if o else "not_observed"}
                     for e, p, a, i, o in rows)
    return sm.SiftsChain("9ZZZ", "A", residues, segments)


def test_sifts_answers_label_author_icode_and_reasons():
    # SYNTHETIC SiftsChain: entity 1 PDBe 1..5 -> author 10..14 (PDBe 3 has icode 'A', PDBe 4 not observed);
    # entity 2 (a ligand, no segment) reuses PDBe 1. Segment covers PDBe 1..4 -> UniProt 101..104.
    seg = {1: (sm.SiftsSegment("P1", 1, 1, 4, 101, 104, 1.0, 1.0),)}
    chain = _sifts_chain([(1, 1, 10, "", True), (1, 2, 11, "", True), (1, 3, 11, "A", True),
                          (1, 4, 13, "", False), (1, 5, 14, "", True), (2, 1, 900, "", True)], seg)
    labelled = [_res(10, 1), _res(11, 2), _res(11, 3, "A"), _res(13, 4), _res(14, 5),
                _res(10, 2),        # label 2 exists but author 10 != 11 -> mismatch
                _res(11, 3),        # label 3 author 11 but icode '' != 'A' -> mismatch
                _res(99, 42),       # neither label nor author known -> no row
                _res(900, 1)]       # ligand entity author 900 is not a polymer row; label 1 has author 10 -> mismatch
    answers, key = rn.sifts_answers(labelled, chain)
    assert key == "label_and_author"
    assert answers == [{"accession": "P1", "position": 101}, {"accession": "P1", "position": 102},
                       {"accession": "P1", "position": 103}, {"absent_reason": "sifts_not_observed", "absent_reasons": ["sifts_not_observed"]},
                       {"absent_reason": "sifts_outside_segments", "absent_reasons": ["sifts_outside_segments"]}, {"absent_reason": "sifts_number_mismatch", "absent_reasons": ["sifts_number_mismatch"]},
                       {"absent_reason": "sifts_number_mismatch", "absent_reasons": ["sifts_number_mismatch"]}, {"absent_reason": "sifts_no_residue_row", "absent_reasons": ["sifts_no_residue_row"]},
                       {"absent_reason": "sifts_number_mismatch", "absent_reasons": ["sifts_number_mismatch"]}]
    author_only = [_res(10), _res(11, icode="A"), _res(11, icode="B"), _res(900)]
    answers, key = rn.sifts_answers(author_only, chain)
    assert key == "author_only"
    assert answers == [{"accession": "P1", "position": 101}, {"accession": "P1", "position": 103},
                       {"absent_reason": "sifts_no_residue_row", "absent_reasons": ["sifts_no_residue_row"]}, {"absent_reason": "sifts_no_residue_row", "absent_reasons": ["sifts_no_residue_row"]}]


# --- 1MQ4: independent oracles --------------------------------------------------------------------------------------

def test_1mq4_oracle_sifts_vs_alignment_segment_arithmetic_and_klifs_match_residues(tmp_path, ref):
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    out, content = _map(run, structure, [{"chain_auth": "A"}], pdb_id="1mq4")
    assert len(calls) == 1 and out.kind == "residue_numbering_map" and out.null_result is False
    chain = _chain(content)
    assert chain["methods_run"] == ["sifts", "local_alignment"] and chain["cross_check"] is True
    assert chain["cross_check_absent_reason"] is None and content["pdb_id"] == "1MQ4"
    assert chain["sifts"] == {"accessions": ["O14965"], "sifts_chain_match": "auth_only",
                              "sifts_residue_key": "label_and_author"}
    assert chain["residue_rule"] == {"rule": rn.RESIDUE_RULE, "modified_residue_count": 0}
    align = chain["alignment"]
    assert (align["identity_pct"], align["coverage_pct"], align["aligned_pairs"], align["chain_residue_count"]) == (
        100.0, 100.0, 261, 261)
    rows = _chain_rows(content)
    # chain residue rule: 261 polymer residues; 72 HOH, 2 MG, PO4 and ADP of chain A have no rows.
    assert len(rows) == 261 and not {"HOH", "MG", "PO4", "ADP"} & {r["residue"]["resname"] for r in rows}
    # (1) SIFTS vs hand-derived segment arithmetic: UniProt = PDBe(label_seq_id) + 119 for every row.
    assert all(r["sifts"] == {"accession": "O14965", "position": r["residue"]["seq_label"] + SEGMENT_OFFSET}
               for r in rows)
    # (2) SIFTS vs the independent alignment: equal for 260 of 261 residues. The C-terminal S388 is separated from
    # the rest by 15 unobserved residues; placing it at UniProt 388 (end gap after) or 403 (internal gap before)
    # scores the same, so over all co-optimal alignments its placement is not unique: alignment_ambiguous. With
    # SIFTS giving 388 the row is a one_method_only conflict with both answers kept (spec 5.4 amendment).
    agree = [r for r in rows if r["sifts"] == r["alignment"]]
    differ = [r for r in rows if r["sifts"] != r["alignment"]]
    assert len(agree) == 260 and [r["residue"]["seq_auth"] for r in differ] == [TIE_RESIDUE]
    assert differ[0]["alignment"] == {"absent_reason": "alignment_ambiguous", "absent_reasons": ["alignment_ambiguous"]}
    assert differ[0]["sifts"] == {"accession": "O14965", "position": 388}
    assert differ[0]["status"] == "conflict" and differ[0]["conflict_reason"] == "one_method_only"
    assert align["ambiguous_residue_count"] == 1
    assert differ[0]["uniprot_position"] is None and differ[0]["klifs_index"] is None
    sequence = _uniprot_sequence("O14965")
    assert sequence[387] == "S" and sequence[402] == "S"
    assert all(r["status"] == "mapped" and r["residue_match"] is True for r in agree)
    assert chain["counts"] == {"mapped": 260, "unmapped": 0, "conflict": 1}
    # (3) KLIFS pocket numbers vs KLIFS's own per-structure table for 1MQ4:A (comparison-only fixture).
    table = next(r for r in _rows("klifs/match_residues_fixture.jsonl")
                 if r["pdb_id"] == "1MQ4" and r["chain"] == "A")["data"]
    table = json.loads(table) if isinstance(table, str) else table
    by_author = {r["residue"]["seq_auth"]: r for r in rows if r["residue"]["icode"] == ""}
    compared = missing = 0
    for item in table:
        if not str(item["Xray_position"]).isdigit():
            continue
        row = by_author.get(int(item["Xray_position"]))
        if row is None or row["klifs_index"] is None:
            missing += 1
            continue
        compared += 1
        assert (row["klifs_index"], row["klifs_label"]) == (item["index"], item["KLIFS_position"])
    assert compared >= 75, (compared, missing)
    assert chain["klifs"] == [{"accession": "O14965", "applied": True, "absent_reason": None,
                               "unresolved_regions": chain["klifs"][0]["unresolved_regions"],
                               "gapped_regions": chain["klifs"][0]["gapped_regions"]}]
    labelled = [r for r in content["rows"] if r["klifs_index"] is not None]
    assert labelled and all(r["status"] == "mapped" for r in labelled)
    assert {r["klifs_match"] for r in labelled} <= {"contiguous", "gapped_unique"}


def test_prepared_structure_maps_like_its_source(tmp_path, ref):
    run, _ = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    prepared = run.call("prepare_structure", {"structure": structure, "waters": "strip_all"}).handle
    _, original = _map(run, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    _, content = _map(run, prepared, [{"chain_auth": "A"}], pdb_id="1MQ4")
    assert content["structure"] == {"handle": prepared, "structure_kind": "prepared_structure", "model_number": 1}
    strip = [{k: v for k, v in r.items()} for r in content["rows"]]
    assert strip == original["rows"]


# --- chain residue rule, MSE, PDB without label, icode, chains and models -------------------------------------------

@pytest.mark.parametrize("path", [CIF_MSE, PDB_MSE])
def test_hetatm_mse_is_a_chain_residue_and_a_flagged_mismatch(tmp_path, ref, path):
    run, _ = _run(tmp_path)
    structure = _load(run, path)
    _, content = _map(run, structure, [{"chain_auth": "A", "uniprot_accession": "O14965"}])
    chain = _chain(content)
    assert chain["methods_run"] == ["local_alignment"] and chain["cross_check"] is False
    assert chain["cross_check_absent_reason"] == "pdb_id_not_given" and chain["sifts"] is None
    assert chain["residue_rule"]["modified_residue_count"] == 1
    rows = _chain_rows(content)
    assert len(rows) == 73 and [r["residue"]["seq_auth"] for r in rows] == list(range(288, 361))
    mse = next(r for r in rows if r["residue"]["resname"] == "MSE")
    assert mse["residue"]["seq_auth"] == 300
    assert mse["residue"]["seq_label"] == (181 if path.suffix == ".cif" else None)
    assert mse["status"] == "mapped" and mse["uniprot_position"] == 300 and mse["uniprot_residue"] == "M"
    assert mse["residue_match"] is False
    structure_string = chain["alignment"]["aligned_strings"]["structure"].replace("-", "")
    assert structure_string[300 - 288] == "X" and structure_string.count("X") == 1
    assert all(r["residue_match"] is True for r in rows if r is not mse)


def test_mse_cif_with_sifts_uses_label_and_author(tmp_path, ref):
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_MSE), [{"chain_auth": "A"}], pdb_id="1MQ4")
    chain = _chain(content)
    assert chain["sifts"]["sifts_residue_key"] == "label_and_author" and chain["cross_check"] is True
    assert chain["counts"] == {"mapped": 73, "unmapped": 0, "conflict": 0}


def test_pdb_without_label_matches_by_author_only(tmp_path, ref):
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, PDB_A200), [{"chain_auth": "A"}], pdb_id="1MQ4")
    chain = _chain(content)
    assert chain["sifts"]["sifts_residue_key"] == "author_only" and chain["cross_check"] is True
    rows = _chain_rows(content)
    assert all(r["residue"]["seq_label"] is None for r in rows)
    # identity is exactly what every other tool reports for this structure (gemmi's PDB subchain name included)
    ids = [{k: v for k, v in r.items() if k not in ("atom_count", "category")}
           for r in structure_residues(run.store, content["structure"]["handle"])["residues"]]
    assert [r["residue"] for r in rows] == ids
    assert chain["counts"] == {"mapped": 86, "unmapped": 0, "conflict": 0}
    assert all(r["uniprot_position"] == r["residue"]["seq_auth"] for r in rows)   # 1MQ4 author == UniProt here


def test_insertion_code_must_match_and_is_preserved(tmp_path, ref):
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, PDB_ICODE), [{"chain_auth": "A"}], pdb_id="1MQ4")
    row = next(r for r in content["rows"] if r["residue"]["icode"] == "A")
    assert row["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "Axp", "seq_auth": 240,
                              "seq_label": None, "icode": "A", "resname": "ALA"}
    # SIFTS knows author 241 without icode, never 240A: no row. The alignment still places it -> conflict.
    assert row["sifts"] == {"absent_reason": "sifts_no_residue_row", "absent_reasons": ["sifts_no_residue_row"]}
    assert row["alignment"] == {"accession": "O14965", "position": 241}
    assert row["status"] == "conflict" and row["conflict_reason"] == "one_method_only"
    assert row["klifs_index"] is None and row["residue_match"] is None and row["uniprot_position"] is None
    plain = next(r for r in content["rows"] if r["residue"]["seq_auth"] == 240 and r["residue"]["icode"] == "")
    assert plain["status"] == "mapped" and plain["uniprot_position"] == 240


def test_two_chains_and_non_first_model(tmp_path, ref):
    run, _ = _run(tmp_path)
    two = _load(run, PDB_TWO_CHAIN)
    _, content = _map(run, two, [{"chain_auth": "B", "uniprot_accession": "O14965"}, {"chain_auth": "A"}],
                      pdb_id="1MQ4")
    assert [c["chain_auth"] for c in content["chains"]] == ["B", "A"]
    assert _chain(content, "B")["cross_check_absent_reason"] == "chain_not_in_sifts_snapshot"
    assert _chain(content, "B")["counts"] == {"mapped": 74, "unmapped": 0, "conflict": 0}
    assert _chain(content, "A")["cross_check"] is True
    assert [r["residue"]["chain_auth"] for r in content["rows"]] == ["B"] * 74 + ["A"] * 86
    second_model = _load(run, PDB_TWO_MODEL, model_index=1)
    _, content = _map(run, second_model, [{"chain_auth": "A"}], pdb_id="1MQ4")
    assert content["structure"]["model_number"] == 2
    assert {r["residue"]["model_number"] for r in content["rows"]} == {2}
    assert [r["residue"]["seq_auth"] for r in content["rows"]] == list(range(200, 286))
    assert _chain(content)["counts"]["mapped"] == 86


def test_multi_letter_chain_with_synthetic_sifts_rows(tmp_path, refroot):
    # SYNTHETIC: the public 1MQ4 chain renamed "AB" (author chain only; labels kept) and the 1MQ4:A SIFTS residue
    # row / segment copied under chain "AB".
    st = gemmi.read_structure(str(CIF_1MQ4))
    st[0]["A"].name = "AB"
    path = tmp_path / "synthetic_1mq4_chain_ab_fixture.cif"
    path.write_text(st.make_mmcif_document().as_string())
    residues = _rows("sifts/residues_fixture.jsonl")
    row = copy.deepcopy(next(r for r in residues if r["id"] == "1MQ4:A"))
    row.update(id="1MQ4:AB", chain="AB")
    row["data"]["columns"]["chain"]["values"] = [{"value": "AB"}]
    residues.append(row)
    _install(refroot, "multi", {("sifts", "residues.jsonl"): _jsonl(residues),
                                ("sifts", "segments.jsonl"): _synthetic_segments_1mq4(
                                    [_segment(), _segment(chain_id="AB")])})
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, path), [{"chain_auth": "AB"}], pdb_id="1MQ4")
    chain = _chain(content, "AB")
    assert chain["cross_check"] is True and chain["sifts"]["sifts_residue_key"] == "label_and_author"
    assert chain["counts"] == {"mapped": 260, "unmapped": 0, "conflict": 1}
    assert {r["residue"]["chain_auth"] for r in content["rows"]} == {"AB"}


# --- 5.5 cases on real structures with synthetic reference variants -------------------------------------------------

def test_positions_differ_when_sifts_segment_is_shifted(tmp_path, refroot):
    _install(refroot, "shift", {("sifts", "segments.jsonl"): _synthetic_segments_1mq4(
        [_segment(unp_start=126, unp_end=392)])})
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    rows = content["rows"]
    assert {r["status"] for r in rows} == {"conflict"}
    assert [r["residue"]["seq_auth"] for r in rows if r["conflict_reason"] != "positions_differ"] == [TIE_RESIDUE]
    assert all(r["sifts"]["position"] == r["residue"]["seq_label"] + SEGMENT_OFFSET + 1 for r in rows)
    assert all(r["uniprot_position"] is None and r["klifs_index"] is None for r in rows)
    assert content["null_result"] is True


def test_one_method_only_and_both_absent(tmp_path, refroot):
    # SYNTHETIC: O14965 truncated after UniProt 380 and the SIFTS segment shortened to PDBe 6..200 (UniProt 125..319).
    _install(refroot, "short", {
        ("uniprot", "entries.jsonl"): _synthetic_uniprot(_with_sequence("O14965", _uniprot_sequence("O14965")[:380])),
        ("sifts", "segments.jsonl"): _synthetic_segments_1mq4([_segment(res_end=200, unp_end=319)])})
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    rows = content["rows"]
    for r in rows:
        status, _agreed, reason = rn.row_status(r["sifts"], r["alignment"])
        assert (r["status"], r["conflict_reason"]) == (status, reason)
    inside = [r for r in rows if r["residue"]["seq_label"] <= 200]
    assert inside and all(r["status"] == "mapped" for r in inside)
    one = [r for r in rows if r["status"] == "conflict"]
    assert one and all(r["conflict_reason"] == "one_method_only" and r["sifts"]["absent_reason"] ==
                       "sifts_outside_segments" and "position" in r["alignment"] for r in one)
    both = [r for r in rows if r["status"] == "unmapped"]
    assert both and all(r["sifts"] == {"absent_reason": "sifts_outside_segments", "absent_reasons": ["sifts_outside_segments"]}
                        and r["alignment"] == {"absent_reason": "alignment_gap", "absent_reasons": ["alignment_gap"]} for r in both)
    assert all(r["klifs_index"] is None for r in one + both)


def test_alignment_below_threshold_with_sifts_positions_is_conflict(tmp_path, refroot):
    # SYNTHETIC: every 5th O14965 letter from 125 on replaced (A<->G) -> identity about 80 %.
    seq = list(_uniprot_sequence("O14965"))
    for i in range(124, len(seq), 5):
        seq[i] = "G" if seq[i] != "G" else "A"
    _install(refroot, "mut", {("uniprot", "entries.jsonl"): _synthetic_uniprot(_with_sequence("O14965", "".join(seq)))})
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    chain = _chain(content)
    assert chain["cross_check"] is True and chain["alignment"]["chain_reason"] == ["alignment_below_identity"]
    assert chain["alignment"]["identity_pct"] < 90
    assert chain["counts"] == {"mapped": 0, "unmapped": 0, "conflict": 261}
    assert all(r["alignment"] == {"absent_reason": "alignment_below_identity", "absent_reasons": ["alignment_below_identity"]} and "position" in r["sifts"]
               and r["conflict_reason"] == "one_method_only" for r in content["rows"])
    assert content["null_result"] is True and chain["klifs"] == []


def test_engineered_substitution_stays_mapped_with_mismatch(tmp_path, refroot):
    # SYNTHETIC: O14965 position 250 letter changed to W (structure keeps its own residue).
    seq = list(_uniprot_sequence("O14965"))
    original = seq[249]
    assert original != "W"
    seq[249] = "W"
    _install(refroot, "gk", {("uniprot", "entries.jsonl"): _synthetic_uniprot(_with_sequence("O14965", "".join(seq)))})
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    row = next(r for r in content["rows"] if r["uniprot_position"] == 250)
    assert row["status"] == "mapped" and row["uniprot_residue"] == "W" and row["residue_match"] is False
    assert gemmi.find_tabulated_residue(row["residue"]["resname"]).one_letter_code.upper() == original
    assert sum(r["residue_match"] is False for r in content["rows"]) == 1


# --- 5.2: the ten cross-check-absent reasons -------------------------------------------------------------------------

def _two_sifts_accessions():
    return {("sifts", "segments.jsonl"): _synthetic_segments_1mq4(
        [_segment(res_end=150, unp_end=269), _segment(res_start=151, uniprot="Q8IU85", unp_start=1, unp_end=122)])}


def _uniprot_without_o14965():
    return {("uniprot", "entries.jsonl"): _synthetic_uniprot(lambda rows: [r for r in rows if r["id"] != "O14965"])}


def _uniprot_o14965_failed():
    def transform(rows):
        return [({"data": None, "id": "O14965", "reason": "UniprotFetchError", "status": "lookup_failed"}
                 if r["id"] == "O14965" else r) for r in rows]
    return {("uniprot", "entries.jsonl"): _synthetic_uniprot(transform)}


CROSS_CHECK_CASES = [
    ("pdb_id_not_given", CIF_1MQ4, "A", None, "O14965", None, ["local_alignment"]),
    ("pdb_not_in_sifts_snapshot", CIF_1MQ4, "A", "9XYZ", "O14965", None, ["local_alignment"]),
    ("chain_not_in_sifts_snapshot", PDB_TWO_CHAIN, "B", "1MQ4", "O14965", None, ["local_alignment"]),
    ("sifts_chain_lookup_failed", PDB_TWO_CHAIN, "B", "6Z1Q", "O14965", None, ["local_alignment"]),
    ("sifts_chain_no_segments", PDB_A200, "A", "1AD5", "O14965", None, ["local_alignment"]),
    ("accession_differs_from_sifts", CIF_1MQ4, "A", "1MQ4", "Q8IU85", None, ["local_alignment"]),
    ("multiple_sifts_accessions", CIF_1MQ4, "A", "1MQ4", None, _two_sifts_accessions, ["sifts"]),
    ("sifts_accession_not_in_uniprot_snapshot", CIF_1MQ4, "A", "1MQ4", None, _uniprot_without_o14965, ["sifts"]),
    ("sifts_accession_uniprot_lookup_failed", CIF_1MQ4, "A", "1MQ4", None, _uniprot_o14965_failed, ["sifts"]),
    ("alignment_too_large", CIF_1MQ4, "A", "1MQ4", None, None, ["sifts"]),
]


@pytest.mark.parametrize(("reason", "path", "chain_auth", "pdb_id", "accession", "replace", "methods"),
                         CROSS_CHECK_CASES, ids=[c[0] for c in CROSS_CHECK_CASES])
def test_cross_check_absent_reasons(tmp_path, refroot, monkeypatch, reason, path, chain_auth, pdb_id, accession,
                                    replace, methods):
    _install(refroot, reason, replace() if replace else None)
    if reason == "alignment_too_large":
        monkeypatch.setattr(rn, "MAX_ALIGNMENT_CELLS", 1000)
    run, calls = _run(tmp_path)
    out, content = _map(run, _load(run, path), [{"chain_auth": chain_auth, "uniprot_accession": accession}], pdb_id)
    chain = _chain(content, chain_auth)
    assert chain["methods_run"] == methods and chain["cross_check"] is False
    assert chain["cross_check_absent_reason"] == reason and reason in rn.CROSS_CHECK_ABSENT_REASONS
    assert len(calls) == 1
    rows = _chain_rows(content, chain_auth)
    assert all((r["sifts"] is None) == ("sifts" not in methods) for r in rows)
    assert all((r["alignment"] is None) == ("local_alignment" not in methods) for r in rows)
    assert {r["status"] for r in rows} <= {"mapped", "unmapped"}
    if reason == "accession_differs_from_sifts":
        assert chain["alignment"]["accession"] == "Q8IU85" and chain["alignment"]["chain_reason"]
        assert out.null_result is True and content["null_result"] is True
    elif reason == "multiple_sifts_accessions":
        assert chain["sifts"]["accessions"] == ["O14965", "Q8IU85"]
        assert {r["uniprot_accession"] for r in rows} == {"O14965", "Q8IU85"}
        assert [k["accession"] for k in chain["klifs"]] == ["O14965", "Q8IU85"]
    elif reason in ("sifts_accession_not_in_uniprot_snapshot", "sifts_accession_uniprot_lookup_failed"):
        mapped = [r for r in rows if r["status"] == "mapped"]
        assert mapped and all(r["uniprot_residue"] is None and r["residue_match"] is None for r in mapped)
        assert all(r["klifs_index"] is None for r in rows)
        assert chain["klifs"] == [{"accession": "O14965", "applied": False,
                                   "absent_reason": "uniprot_sequence_unavailable",
                                   "unresolved_regions": [], "gapped_regions": []}]
    else:
        ambiguous = chain["alignment"]["ambiguous_residue_count"] if chain["alignment"] else 0
        assert chain["counts"]["mapped"] == len(rows) - ambiguous
        assert ambiguous == (1 if path == CIF_1MQ4 and chain["alignment"] else 0)


# --- input validation: failure recorded like other validation failures, implementation never called ----------------

def _rejected(run, calls, args, reason_code, cls=FailureClass.input_invalid):
    before = len(_events(run))
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.cls == cls and caught.value.detail["reason_code"] == reason_code
    new = _events(run)[before:]
    assert [e["type"] for e in new if e["type"] != "wall_charged"] == ["proposal_rejected"]
    rejected = next(e for e in new if e["type"] == "proposal_rejected")
    assert rejected["error"] == cls.value and rejected["tool"] == TOOL
    assert calls == []


def test_input_validation_never_calls_the_implementation(tmp_path, refroot, monkeypatch):
    _install(refroot, "invalid", {
        **_two_sifts_accessions(),
        ("uniprot", "entries.jsonl"): _synthetic_uniprot(lambda rows: rows + [
            {"data": None, "id": "O43930", "reason": "UniprotFetchError", "status": "lookup_failed"}])})
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    other, _ = _run(tmp_path, name="run_other")
    foreign = _load(other, CIF_1MQ4)
    source = run.store.meta(structure)["summary"]["source_handle"]
    ok_chain = {"chain_auth": "A", "uniprot_accession": "O14965"}
    cases = [
        ({"structure": structure, "chains": [{"chain_auth": "Z", "uniprot_accession": "O14965"}]}, "chain_not_found"),
        ({"structure": foreign, "chains": [ok_chain]}, "structure_invalid"),
        ({"structure": source, "chains": [ok_chain]}, "structure_kind_not_allowed"),
        ({"structure": structure, "chains": [ok_chain], "extra": 1}, "unknown_field"),
        ({"structure": structure, "chains": [{**ok_chain, "label": "x"}]}, "unknown_field"),
        ({"structure": structure, "chains": [{"chain_auth": "A", "uniprot_accession": "P99999"}]},
         "accession_not_in_uniprot_snapshot"),
        ({"structure": structure, "chains": [{"chain_auth": "A", "uniprot_accession": "O43930"}]},
         "accession_not_in_uniprot_snapshot"),
        ({"structure": structure, "pdb_id": "1MQ4", "chains": [ok_chain]}, "accession_with_multiple_sifts_accessions"),
        ({"structure": structure, "chains": [{"chain_auth": "A"}]}, "no_usable_method"),
        ({"structure": structure, "chains": [ok_chain, ok_chain]}, "duplicate_chain"),
        ({"structure": structure, "chains": []}, "chains_invalid"),
        ({"structure": structure, "pdb_id": "1MQ45", "chains": [ok_chain]}, "pdb_id_invalid"),
        ({"structure": structure, "pdb_id": 1234, "chains": [ok_chain]}, "pdb_id_invalid"),
        ({"chains": [ok_chain]}, "structure_invalid"),
    ]
    for args, reason_code in cases:
        _rejected(run, calls, args, reason_code)
    monkeypatch.setattr(rn, "MAX_ALIGNMENT_CELLS", 1000)
    _rejected(run, calls, {"structure": structure, "chains": [ok_chain]}, "no_usable_method")
    assert not [e for e in _events(run, "tool_called") if e["tool"] == TOOL]


def test_http_command_success_and_validation_status(tmp_path, ref, monkeypatch):
    from fastapi.testclient import TestClient

    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    client = TestClient(appmod.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={"goal": "numbering"}).json()["run_id"]
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "1mq4.cif"}, content=CIF_1MQ4.read_bytes(),
                         headers={"content-type": "application/octet-stream"}).json()
    structure = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                            "args": {"source": upload["upload_id"]}}).json()
    handle = structure["handle"]["handle"]
    ok = client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "structure": handle, "pdb_id": "1MQ4", "chains": [{"chain_auth": "A"}]}})
    assert ok.status_code == 200 and ok.json()["handle"]["kind"] == "residue_numbering_map"
    bad = client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "structure": handle, "pdb_id": "1MQ4", "chains": [{"chain_auth": "Q"}]}})
    assert bad.status_code == 422 and bad.json()["detail"]["reason_code"] == "chain_not_found"


# --- snapshot availability, record rule, cache, same handle, recovery, dry run --------------------------------------

def test_unavailable_set_fails_before_cache_lookup(tmp_path, refroot):
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    args = {"structure": structure, "pdb_id": "1MQ4", "chains": [{"chain_auth": "A"}]}
    _rejected(run, calls, args, "not_installed", FailureClass.precondition)
    set_hash = _install(refroot, "avail", None)
    run.call(TOOL, args)
    assert len(calls) == 1
    calls.clear()
    (refroot / "active.json").unlink()
    _rejected(run, calls, args, "not_installed", FailureClass.precondition)
    (refroot / "active.json").write_bytes(rs.canonical_json({"schema": rs.POINTER_SCHEMA, "set_hash": set_hash}))
    data = refroot / "sets" / set_hash / "files" / "klifs" / "2026-09-19" / "kinases.jsonl"
    data.write_bytes(data.read_bytes() + b"\n")
    _rejected(run, calls, args, "snapshot_invalid", FailureClass.precondition)
    assert not _events(run, "cache_hit")


def test_snapshot_set_record_same_handle_and_recompute_after_set_change(tmp_path, refroot):
    first_hash = _install(refroot, "first", None)
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    args = {"structure": structure, "pdb_id": "1mq4", "chains": [{"chain_auth": "A"}]}
    out = run.call(TOOL, args)
    kinds = [e.get("kind") for e in _events(run, "object_created")]
    assert kinds[-2:] == ["reference_snapshot_set", "residue_numbering_map"]
    set_event = _created(run, "reference_snapshot_set")[0]
    set_bytes = run.store.load_bounded_json(set_event["handle"], 1 << 20)
    assert hashlib.sha256(rs.canonical_json(set_bytes)).hexdigest() == first_hash
    assert set_bytes == json.loads((refroot / "sets" / first_hash / "manifest.json").read_bytes())
    assert set_event["schema"] == "reference_snapshot_set@1" and set_event["summary"] == {"set_hash": first_hash}
    content = run.store.load(out.handle)
    assert content["snapshot_set"]["set_hash"] == first_hash and content["snapshot_set"]["origin"] == rs.ORIGIN
    assert [s["source"] for s in content["snapshot_set"]["sources"]] == ["uniprot", "sifts", "klifs"]
    assert content["snapshot_set"]["sources"][2]["license"] == "none-stated"
    # same inputs (pdb_id case, explicit null accession) + same set -> cache hit, same handle, no new set object
    again = run.call(TOOL, {"structure": structure, "pdb_id": "1MQ4",
                            "chains": [{"chain_auth": "A", "uniprot_accession": None}]})
    assert again.handle == out.handle and len(calls) == 1 and _events(run, "cache_hit")
    # another request under the same set: new map, the set is not recorded again
    run.call(TOOL, {"structure": structure, "chains": [{"chain_auth": "A", "uniprot_accession": "O14965"}]})
    assert len(calls) == 2 and len(_created(run, "reference_snapshot_set")) == 1
    # re-import: new set hash -> the same request recomputes, the new set is recorded before its map
    second_hash = _install(refroot, "second", None)
    assert second_hash != first_hash
    third = run.call(TOOL, args)
    assert len(calls) == 3 and third.handle != out.handle
    kinds = [e.get("kind") for e in _events(run, "object_created")]
    assert kinds[-2:] == ["reference_snapshot_set", "residue_numbering_map"]
    assert run.store.load(third.handle)["snapshot_set"]["set_hash"] == second_hash
    assert run.store.load(third.handle)["rows"] == content["rows"]
    keys = [e["key"] for e in _events(run, "tool_called") if e["tool"] == TOOL]
    assert len(set(keys)) == 3


def test_events_only_recovery_without_reference_folder(tmp_path, ref):
    run, _ = _run(tmp_path)
    out, _ = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    sha = out.handle.rsplit("/", 1)[1]
    raw = (run.run_dir / "objects" / f"{sha}.json").read_bytes()
    handles = run.store.handles()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    shutil.rmtree(ref)
    assert rs.capability()["available"] is False
    reopened, calls = _run(tmp_path)
    assert (reopened.run_dir / "objects" / f"{sha}.json").read_bytes() == raw
    assert reopened.store.handles() == handles and calls == []
    replayed = replay(run.run_dir / "events.jsonl", tmp_path / "replay" / run.run_id, build_registry(), run.run_id)
    assert replayed == handles
    assert (tmp_path / "replay" / run.run_id / "objects" / f"{sha}.json").read_bytes() == raw


def test_dry_run_executes_the_cheap_tool(tmp_path, ref):
    run, calls = _run(tmp_path, dry_run=True)
    out, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    assert out.kind == "residue_numbering_map" and len(calls) == 1
    assert _chain(content)["counts"]["mapped"] == 260
    assert not [e for e in _events(run, "tool_called") if e.get("plan_only")]


def test_reference_rows_are_embedded(tmp_path, ref):
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], pdb_id="1MQ4")
    refs = content["reference_rows"]
    assert refs["uniprot"] == [{"accession": "O14965", "status": "ok", "in_snapshot": True,
                                "sequence": _uniprot_sequence("O14965")}]
    assert refs["sifts"][0]["segments"] == [{"accession": "O14965", "entity_id": 1, "pdbe_start": 6, "pdbe_end": 272,
                                            "unp_start": 125, "unp_end": 391, "identity": 1.0, "coverage": 0.663}]
    assert len(refs["sifts"][0]["residues"]) == 272 and {r["entity_id"] for r in refs["sifts"][0]["residues"]} == {1}
    pocket = next(r for r in _rows("klifs/kinases_fixture.jsonl") if r["uniprot"] == "O14965")["pocket"]
    assert refs["klifs"] == [{"accession": "O14965", "entries": [{"kinase_ID": 259, "name": "AurA",
                                                                  "pocket": pocket}]}]
    assert content["alignment_params"]["min_identity_pct"] == 90.0
    assert content["alignment_params"]["min_coverage_pct"] == 50.0
    assert content["alignment_params"]["matrix"] == "BLOSUM62"
    assert content["alignment_params"]["gap_open"] == -10 and content["alignment_params"]["gap_extend"] == -0.5


def test_argument_repair_path_runs_the_same_precheck(tmp_path, ref):
    assert set(build_registry().prechecks) == {TOOL}          # no other tool's validation or key changes
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    with pytest.raises(ToolFailure):
        run.call(TOOL, {"structure": structure, "chains": [{"chain_auth": "Z", "uniprot_accession": "O14965"}]})
    failed = _events(run, "proposal_rejected")[-1]["proposal_id"]
    with pytest.raises(ToolFailure) as caught:
        run.repair_call(failed, {"structure": structure, "chains": [{"chain_auth": "A"}]})
    assert caught.value.detail["reason_code"] == "no_usable_method" and calls == []
    out = run.repair_call(failed, {"structure": structure, "pdb_id": "1mq4", "chains": [{"chain_auth": "A"}]})
    assert len(calls) == 1 and run.store.load(out.handle)["pdb_id"] == "1MQ4"
    repaired = [e for e in _events(run, "tool_called") if e["tool"] == TOOL]
    assert repaired[-1]["attempt_kind"] == "argument_repair" and repaired[-1]["args"]["pdb_id"] == "1MQ4"


def test_revalidation_with_unchanged_args_reuses_the_bound(tmp_path, ref, monkeypatch):
    import mw.tools.numbering as numbering_tool
    parsed = []
    real = numbering_tool._parse

    def counting(ctx, handle):
        parsed.append(handle)
        return real(ctx, handle)

    monkeypatch.setattr(numbering_tool, "_parse", counting)
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    parsed.clear()
    out = run.call(TOOL, {"structure": structure, "pdb_id": "1mq4", "chains": [{"chain_auth": "A"}]})
    assert len(calls) == 1 and run.store.load(out.handle)["pdb_id"] == "1MQ4"
    assert parsed == [structure]  # the pre-check parsed once; _execute_chain reused its bound
    first = numbering_tool.precheck(run.store, {"structure": structure, "pdb_id": "1mq4",
                                                "chains": [{"chain_auth": "A"}]})[1]
    parsed.clear()
    changed = numbering_tool.precheck(run.store, {"structure": structure, "pdb_id": None,
                                                  "chains": [{"chain_auth": "A", "uniprot_accession": "O14965"}]},
                                      first)
    assert parsed == [structure] and changed[1] is not first and changed[1].pinned is first.pinned
    same = numbering_tool.precheck(run.store, {"structure": structure, "pdb_id": "1MQ4",
                                               "chains": [{"chain_auth": "A", "uniprot_accession": None}]}, first)
    assert same[1] is first and parsed == [structure]


def test_1mq4_alignment_only_does_not_map_the_ambiguous_residue(tmp_path, ref):
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A", "uniprot_accession": "O14965"}])
    chain = _chain(content)
    assert chain["methods_run"] == ["local_alignment"] and chain["cross_check_absent_reason"] == "pdb_id_not_given"
    assert chain["alignment"]["ambiguous_residue_count"] == 1
    assert chain["alignment"]["identity_pct"] == 100.0 and chain["alignment"]["coverage_pct"] == 100.0
    assert chain["counts"] == {"mapped": 260, "unmapped": 1, "conflict": 0}
    row = next(r for r in content["rows"] if r["residue"]["seq_auth"] == TIE_RESIDUE)
    assert row["status"] == "unmapped" and row["alignment"] == {"absent_reason": "alignment_ambiguous", "absent_reasons": ["alignment_ambiguous"]}
    assert row["uniprot_position"] is None and row["klifs_index"] is None and row["sifts"] is None
    mapped = [r for r in content["rows"] if r["status"] == "mapped"]
    assert all(r["uniprot_position"] == r["residue"]["seq_label"] + SEGMENT_OFFSET for r in mapped)


def test_sifts_ambiguous_residue_row_when_two_rows_fully_match():
    # SYNTHETIC SiftsChain: two polymer entities with segments both hold PDBe 1 / author 10.
    seg = {1: (sm.SiftsSegment("P1", 1, 1, 1, 101, 101, 1.0, 1.0),),
           2: (sm.SiftsSegment("P2", 2, 1, 1, 201, 201, 1.0, 1.0),)}
    chain = _sifts_chain([(1, 1, 10, "", True), (2, 1, 10, "", True)], seg)
    for residue in (_res(10, 1), _res(10)):
        answers, _ = rn.sifts_answers([residue], chain)
        assert answers == [{"absent_reason": "sifts_ambiguous_residue_row",
                            "absent_reasons": ["sifts_ambiguous_residue_row"]}]
    assert "sifts_ambiguous_residue_row" in rn.SIFTS_ABSENT_REASONS


def test_sifts_position_beyond_uniprot_sequence_is_absent(tmp_path, refroot):
    # SYNTHETIC: O14965 truncated after UniProt 380 while the SIFTS segment still reaches 391.
    _install(refroot, "beyond", {("uniprot", "entries.jsonl"): _synthetic_uniprot(
        _with_sequence("O14965", _uniprot_sequence("O14965")[:380]))})
    run, _ = _run(tmp_path)
    for chains, pdb_id in (([{"chain_auth": "A"}], "1MQ4"),):
        _, content = _map(run, _load(run, CIF_1MQ4), chains, pdb_id)
        beyond = [r for r in content["rows"] if r["residue"]["seq_label"] + SEGMENT_OFFSET > 380]
        assert beyond and all(r["sifts"] == {"absent_reason": "sifts_position_outside_sequence",
                                             "absent_reasons": ["sifts_position_outside_sequence"]} for r in beyond)
        assert all(r["status"] != "mapped" and r["uniprot_position"] is None for r in beyond)
        assert all(r["uniprot_residue"] is not None for r in content["rows"] if r["status"] == "mapped")


def test_sifts_only_position_beyond_sequence_is_not_mapped(tmp_path, refroot, monkeypatch):
    # SYNTHETIC as above; alignment disabled by the size cap -> SIFTS only, the beyond rows must be unmapped.
    _install(refroot, "beyond_sifts", {("uniprot", "entries.jsonl"): _synthetic_uniprot(
        _with_sequence("O14965", _uniprot_sequence("O14965")[:380]))})
    monkeypatch.setattr(rn, "MAX_ALIGNMENT_CELLS", 1000)
    run, _ = _run(tmp_path)
    _, content = _map(run, _load(run, CIF_1MQ4), [{"chain_auth": "A"}], "1MQ4")
    assert _chain(content)["methods_run"] == ["sifts"]
    beyond = [r for r in content["rows"] if r["residue"]["seq_label"] + SEGMENT_OFFSET > 380]
    assert beyond and all(r["status"] == "unmapped" for r in beyond)
    assert _chain(content)["counts"]["mapped"] == 261 - len(beyond)


def test_set_sequence_a_b_a_keeps_one_immutable_record_per_set(tmp_path, refroot):
    # Content addressing: re-activating set A yields A's existing handle (no second object_created event); the new
    # map embeds A's hash, and A's full manifest stays recorded in this run's events.
    first = _install(refroot, "a", None)
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    _map(run, structure, [{"chain_auth": "A"}], "1MQ4")
    _install(refroot, "b", None)
    _map(run, structure, [{"chain_auth": "A"}], "1MQ4")
    (refroot / "active.json").write_bytes(rs.canonical_json({"schema": rs.POINTER_SCHEMA, "set_hash": first}))
    _, content = _map(run, structure, [{"chain_auth": "A", "uniprot_accession": "O14965"}], "1MQ4")
    assert content["snapshot_set"]["set_hash"] == first and len(calls) == 3
    recorded = [e["summary"]["set_hash"] for e in _created(run, "reference_snapshot_set")]
    assert recorded[0] == first and len(recorded) == 2 and first in recorded
