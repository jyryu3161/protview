"""M15 SIFTS decoder (mw.sifts_mapping) against verbatim FIXTURE rows of the kbase_kinase processed SIFTS snapshot.

``fixtures/reference/sifts/*_fixture.jsonl`` are byte-for-byte lines of kbase ``ref/sifts/2026-09-20`` (and one v0 line
of ``2026-09-16``); ``provenance_fixture.json`` records the source files, their SHA-256 and every extracted line hash.
Expected values below were read by hand from those raw JSON lines (derivations in the comments), not produced by the
decoder. Tests that need malformed input copy a real row and change one field in memory (marked "derived").
"""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mw import reference_snapshots as rs
from mw import sifts_mapping as sm

FIX = Path(__file__).resolve().parent / "fixtures" / "reference" / "sifts"


def _rows(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIX / name).read_bytes().splitlines() if line.strip()]


RES = _rows("residues_fixture.jsonl")
SEG = _rows("segments_fixture.jsonl")
RES_V0 = _rows("residues_v0_fixture.jsonl")


def _res(row_id: str) -> dict:
    return copy.deepcopy(next(r for r in RES if r["id"] == row_id))


def _seg(pdb: str) -> dict:
    return copy.deepcopy(next(r for r in SEG if r["pdb_id"] == pdb))


def _index(residues=None, segments=None) -> sm.SiftsIndex:
    return sm.SiftsIndex(RES if residues is None else residues, SEG if segments is None else segments)


def _row(chain: sm.SiftsChain, entity: int, pdbe: int, author=None) -> dict:
    found = [r for r in chain.residues if r["entity_id"] == entity and r["pdbe_number"] == pdbe
             and (author is None or r["author_number"] == author)]
    assert len(found) == 1, found
    return found[0]


def _unusable(result, reason: str, detail: str | None = None) -> None:
    assert isinstance(result, sm.SiftsUnusable), result
    assert result.reason_code == reason
    assert result.reason == sm.REASONS[reason]
    if detail is not None:
        assert result.detail == detail


# --- fixture integrity -------------------------------------------------------------------------------------------

def test_fixture_files_match_their_provenance():
    prov = json.loads((FIX / "provenance_fixture.json").read_text())
    assert "fixture" in prov["label"]
    for entry in prov["files"]:
        assert "fixture" in entry["file"]
        data = (FIX / entry["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["bytes"]
        lines = [line for line in data.split(b"\n") if line]
        assert [json.loads(line)["id"] for line in lines] == entry["extracted_ids"]
        for row_id, line in zip(entry["extracted_ids"], lines):
            assert hashlib.sha256(line).hexdigest() == entry["extracted_line_sha256"][row_id]


# --- 1MQ4 chain A: several entities in one chain row ------------------------------------------------------------

def test_1mq4_a_multi_entity_rows_hand_derived():
    # Raw v1 row 1MQ4:A: runs (pdbe_start, pdb_start, length) = (1,1,1) (1,2001,1) (1,2086,1) (1,2088,1) (7,126,160)
    # (169,288,101); exceptions (all not_observed, uniprot_resnum = PDBe number) pdbe 1..6 -> author 120..125,
    # 167/168 -> 286/287, 270..272 -> 389..391. 4+160+101 run rows + 11 exceptions = 276 = len(insertion_codes).
    # kbase row order sorts by (pdbe, author): idx0 (1,1) idx1 (1,120) idx2 (1,2001) idx3 (1,2086) idx4 (1,2088)
    # idx5..9 pdbe 2..6, idx10 pdbe 7 ...
    # columns: entity_id values [1,2,3,4], indices[0:5] = [2,0,3,1,1] -> entities 3,1,4,2,2;
    # residue_name indices[0:13] = [16,8,0,14,14,1,13,8,18,12,2,6,20] -> PO4 GLY ADP MG MG ALA MET GLY SER LYS ARG GLN
    # TRP; observed_ratio values [0.0,0.454,0.555,1.0], indices[0:13] = [3,0,3,3,3,0,0,0,0,0,1,2,3].
    chain = _index().lookup("1MQ4", "A")
    assert isinstance(chain, sm.SiftsChain)
    assert (chain.pdb_id, chain.chain_auth) == ("1MQ4", "A")
    assert len(chain.residues) == 276
    assert _row(chain, 3, 1) == {"entity_id": 3, "pdbe_number": 1, "author_number": 1, "icode": "",
                                 "residue_name": "PO4", "observed": True, "exception_reason": None}
    assert _row(chain, 1, 1) == {"entity_id": 1, "pdbe_number": 1, "author_number": 120, "icode": "",
                                 "residue_name": "GLY", "observed": False, "exception_reason": "not_observed"}
    assert _row(chain, 4, 1)["residue_name"] == "ADP" and _row(chain, 4, 1)["author_number"] == 2001
    # entity 2 (MG) has two instances that both restart at PDBe number 1: both kept, never merged.
    assert [(r["author_number"], r["residue_name"]) for r in chain.residues
            if r["entity_id"] == 2] == [(2086, "MG"), (2088, "MG")]
    assert _row(chain, 1, 2)["residue_name"] == "ALA" and _row(chain, 1, 2)["author_number"] == 121
    assert _row(chain, 1, 7) == {"entity_id": 1, "pdbe_number": 7, "author_number": 126, "icode": "",
                                 "residue_name": "ARG", "observed": True, "exception_reason": None}  # ratio 0.454
    assert _row(chain, 1, 9)["residue_name"] == "TRP" and _row(chain, 1, 9)["author_number"] == 128
    assert _row(chain, 1, 272)["author_number"] == 391 and _row(chain, 1, 272)["observed"] is False


def test_1mq4_a_uniprot_positions_hand_derived():
    # Segment 1MQ4: entity 1, chain A, O14965, res 6..272 (PDBe) -> unp 125..391; linear: unp = 125 + (pdbe - 6).
    chain = _index().lookup("1MQ4", "A")
    assert chain.accessions == frozenset({"O14965"})
    assert chain.uniprot_position(1, 7) == ("O14965", 126)     # author 126 ARG
    assert chain.uniprot_position(1, 9) == ("O14965", 128)     # author 128 TRP
    assert chain.uniprot_position(1, 272) == ("O14965", 391)   # author 391, not observed
    assert chain.uniprot_position(1, 5) is None                # before res_start 6 -> sifts_outside_segments
    assert chain.uniprot_position(2, 1) is None                # MG entity has no segment
    assert chain.uniprot_position(3, 1) is None                # PO4 entity has no segment
    assert chain.mapping(1, 5) == {"accession": None, "position": None, "reason_code": "sifts_outside_segments"}
    assert chain.mapping(1, 7) == {"accession": "O14965", "position": 126, "reason_code": None}
    assert [(s.accession, s.entity_id, s.pdbe_start, s.pdbe_end, s.unp_start, s.unp_end) for s in chain.segments[1]] \
        == [("O14965", 1, 6, 272, 125, 391)]


def test_exception_uniprot_resnum_field_is_the_pdbe_number():
    # Exception {"uniprot_resnum": 6, "pdb_resnum": 125, "observed_ratio": 0}: 6 is the PDBe number, NOT a UniProt
    # position. The UniProt position comes only from the segment: 125 + (6 - 6) = 125.
    chain = _index().lookup("1MQ4", "A")
    row = _row(chain, 1, 6)
    assert (row["author_number"], row["residue_name"], row["exception_reason"]) == (125, "LYS", "not_observed")
    assert chain.uniprot_position(1, 6) == ("O14965", 125)
    # Had 6 been read as a UniProt position, PDBe 125 would be confused with it: PDBe 125 is run (7,126,160) ->
    # author 126 + (125 - 7) = 244, UniProt 125 + (125 - 6) = 244.
    assert _row(chain, 1, 125)["author_number"] == 244 and chain.uniprot_position(1, 125) == ("O14965", 244)


def test_v0_list_format_decodes_to_the_same_rows_as_v1():
    # 1MQ4:A from the older 2026-09-16 snapshot stores the raw PDBe residue listing as a JSON list (v0). It is an
    # independent encoding of the same chain, so the v1 run/column restore must give exactly the same residue rows.
    v0 = sm.SiftsIndex(RES_V0, SEG).lookup("1MQ4", "A")
    v1 = _index().lookup("1MQ4", "A")
    assert isinstance(v0, sm.SiftsChain) and isinstance(v1, sm.SiftsChain)
    assert v0.residues == v1.residues
    assert v0.uniprot_position(1, 7) == ("O14965", 126)


# --- other real chains ------------------------------------------------------------------------------------------

def test_insertion_codes_normalized_and_kept():
    # 6T6F:A insertion_codes[297..310] = 'A'..'N'; kbase order idx0 (1,8) idx1 (1,401) then idx n = pdbe n for n >= 2,
    # and exceptions (297,303,'A') .. (310,303,'N'): author 303 with codes A..N. residue_name idx297 SER, idx310 ARG.
    # Segment Q8IU85 res 3..322 -> unp 10..329: pdbe 296 (author 303) -> 303, pdbe 297 (303A) -> 304,
    # pdbe 311 (author 317, run (311,317,12)) -> 318.
    chain = _index().lookup("6T6F", "A")
    assert {r["icode"] for r in chain.residues} == {""} | set("ABCDEFGHIJKLMN")
    assert _row(chain, 1, 297) == {"entity_id": 1, "pdbe_number": 297, "author_number": 303, "icode": "A",
                                   "residue_name": "SER", "observed": False, "exception_reason": "not_observed"}
    assert _row(chain, 1, 310)["icode"] == "N" and _row(chain, 1, 310)["residue_name"] == "ARG"
    assert _row(chain, 1, 296)["author_number"] == 303 and _row(chain, 1, 296)["icode"] == ""
    assert chain.uniprot_position(1, 296) == ("Q8IU85", 303)
    assert chain.uniprot_position(1, 297) == ("Q8IU85", 304)
    assert chain.uniprot_position(1, 311) == ("Q8IU85", 318) and _row(chain, 1, 311)["author_number"] == 317


def test_null_insertion_codes_normalize_to_empty_string():
    row = _res("1MQ4:A")   # derived: every stored code '' -> null (kbase keeps both spellings verbatim)
    row["data"]["insertion_codes"] = [None] * len(row["data"]["insertion_codes"])
    chain = _index(residues=[row]).lookup("1MQ4", "A")
    assert {r["icode"] for r in chain.residues} == {""}


def test_segment_row_without_chain_key():
    # 3CS9 segments row has no "chain" key; data lists chains A..D, entity 1, P00519, res 6..277 -> unp 229..500.
    # 3CS9:A run (10,233,42): pdbe 10 -> author 233 and unp 229 + 4 = 233; exception (6,229) -> unp 229.
    assert "chain" not in _seg("3CS9")
    chain = _index().lookup("3CS9", "A")
    assert chain.accessions == frozenset({"P00519"})
    assert _row(chain, 1, 10)["author_number"] == 233 and chain.uniprot_position(1, 10) == ("P00519", 233)
    assert chain.uniprot_position(1, 6) == ("P00519", 229)


def test_two_accessions_in_one_entity():
    # 5JGA segments for chain A, entity 1: O43318 res 6..278 -> 31..303 and Q15750 res 279..315 -> 468..504.
    # Runs (2,27,153) (166,191,113) (279,468,29): pdbe 6 -> author 31, 278 -> 303, 279 -> 468.
    chain = _index().lookup("5JGA", "A")
    assert chain.accessions == frozenset({"O43318", "Q15750"})
    assert chain.uniprot_position(1, 6) == ("O43318", 31) and _row(chain, 1, 6)["author_number"] == 31
    assert chain.uniprot_position(1, 278) == ("O43318", 303)
    assert chain.uniprot_position(1, 279) == ("Q15750", 468) and _row(chain, 1, 279)["author_number"] == 468
    assert chain.uniprot_position(1, 1) is None   # polymer pdbe 1 (author 26) precedes res_start 6


# --- unusable reasons -------------------------------------------------------------------------------------------

def test_unusable_reasons_on_real_rows():
    index = _index()
    _unusable(index.lookup("9ZZZ", "A"), "pdb_not_in_sifts_snapshot")
    _unusable(index.lookup("3CS9", "B"), "chain_not_in_sifts_snapshot")      # B not extracted into the fixture
    _unusable(index.lookup("6Z1Q", "A"), "chain_not_in_sifts_snapshot")
    _unusable(index.lookup("6Z1Q", "B"), "sifts_chain_lookup_failed", "residues_status_lookup_failed")
    _unusable(index.lookup("5LQE", "A"), "sifts_chain_lookup_failed", "residues_status_not_found")
    _unusable(index.lookup("1AD5", "A"), "sifts_chain_no_segments", "segments_status_lookup_failed")
    assert isinstance(index.lookup("1mq4", "A"), sm.SiftsChain)              # PDB id is case-insensitive
    _unusable(index.lookup("1MQ4", "a"), "chain_not_in_sifts_snapshot")      # chain id is not


def test_no_segments_when_segments_ok_but_do_not_cover_the_chain():
    seg = _seg("1MQ4")   # derived: the real segment moved to another chain id / list emptied / row missing
    seg["data"][0]["chain_id"] = "Z"
    _unusable(_index(segments=[seg]).lookup("1MQ4", "A"), "sifts_chain_no_segments", "no_segment_for_chain")
    seg["data"] = []
    _unusable(_index(segments=[seg]).lookup("1MQ4", "A"), "sifts_chain_no_segments", "no_segment_for_chain")
    _unusable(_index(segments=[]).lookup("1MQ4", "A"), "sifts_chain_no_segments", "segments_row_missing")


@pytest.mark.parametrize("mutate, detail", [
    (lambda d: d["insertion_codes"].pop(), "restore_mismatch"),
    (lambda d: d["insertion_codes"].append(""), "restore_mismatch"),
    (lambda d: d["columns"]["entity_id"]["indices"].pop(), "restore_mismatch"),
    (lambda d: d["columns"]["residue_name"]["indices"].__setitem__(0, 99), "restore_mismatch"),
    (lambda d: d["runs"][4].__setitem__("length", 159), "restore_mismatch"),
    (lambda d: d["exceptions"].pop(0), "restore_mismatch"),
    # swapping two exceptions' observed ratio columns breaks the not_observed <-> observed_ratio == 0 invariant
    (lambda d: d["columns"]["observed_ratio"]["indices"].__setitem__(1, 3), "restore_mismatch"),
    # a letter code at a row whose restored insertion code is null: row order is not the one the columns index
    (lambda d: d["insertion_codes"].__setitem__(10, "A"), "restore_mismatch"),
    (lambda d: d["columns"]["chain"]["values"].__setitem__(0, {"value": "B"}), "restore_mismatch"),
    (lambda d: d["columns"].pop("entity_id"), "restore_mismatch"),
    (lambda d: d["exceptions"][0].__setitem__("reason", "sequence_mismatch"), "unknown_format"),
    (lambda d: d.__setitem__("format", "pdbe-residue-runs-v2"), "unknown_format"),
    (lambda d: d.pop("format"), "unknown_format"),
    (lambda d: d.__setitem__("extra", 1), "unknown_format"),
    (lambda d: d["runs"][0].__setitem__("pdbe_start", "1"), "unknown_format"),
])
def test_v1_restore_mismatch_or_unknown_format_is_rejected(mutate, detail):
    row = _res("1MQ4:A")   # derived from the real row
    mutate(row["data"])
    _unusable(_index(residues=[row]).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", detail)


def test_unknown_data_shape_is_rejected():
    row = _res("1MQ4:A")
    row["data"] = "pdbe-residue-runs-v1"
    _unusable(_index(residues=[row]).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", "unknown_format")
    v0 = copy.deepcopy(RES_V0[0])
    v0["data"][3]["chain"] = "B"          # a v0 row belonging to another chain
    _unusable(sm.SiftsIndex([v0], SEG).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", "restore_mismatch")
    v0 = copy.deepcopy(RES_V0[0])
    del v0["data"][0]["observed_ratio"]
    _unusable(sm.SiftsIndex([v0], SEG).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", "unknown_format")


def test_bad_segments_are_rejected():
    seg = _seg("1MQ4")   # derived: non-linear range
    seg["data"][0]["unp_end"] = 392
    _unusable(_index(segments=[seg]).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", "segment_invalid")
    seg = _seg("1MQ4")   # derived: an overlapping second segment
    seg["data"].append(dict(seg["data"][0], uniprot="P00000", res_start=270, res_end=280, unp_start=1, unp_end=11))
    _unusable(_index(segments=[seg]).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", "segments_overlap")


def test_duplicate_pdbe_number_inside_a_mapped_entity_is_rejected():
    row = _res("1MQ4:A")   # derived: relabel PO4 (entity 3, pdbe 1) as entity 1, which already has pdbe 1
    row["data"]["columns"]["entity_id"]["indices"][0] = 0
    _unusable(_index(residues=[row]).lookup("1MQ4", "A"), "sifts_chain_lookup_failed", "duplicate_pdbe_number")


def test_duplicate_chain_rows_are_not_guessed():
    _unusable(_index(residues=RES + [_res("1MQ4:A")]).lookup("1MQ4", "A"), "sifts_chain_lookup_failed",
              "duplicate_rows")


# --- listing and pinned-set cache -------------------------------------------------------------------------------

def test_chains_for_pdb():
    index = _index()
    assert index.chains_for_pdb("5jga") == [{"chain_auth": "A", "accessions": ["O43318", "Q15750"],
                                            "reason_code": None}]
    assert index.chains_for_pdb("1AD5") == [{"chain_auth": "A", "accessions": [],
                                            "reason_code": "sifts_chain_no_segments"}]
    assert index.chains_for_pdb("9ZZZ") == []


def _write_set(root: Path) -> None:
    """A FIXTURE set in the importer layout: SIFTS files are the committed fixture bytes, others are placeholders."""
    date = "2026-09-20"
    files = {"uniprot": [("entries.jsonl", "product", b'{"fixture":1}\n')],
             "sifts": [("residues.jsonl", "product", (FIX / "residues_fixture.jsonl").read_bytes()),
                       ("segments.jsonl", "product", (FIX / "segments_fixture.jsonl").read_bytes())],
             "klifs": [("kinases.jsonl", "product", b'{"fixture":1}\n'),
                       ("match_residues.jsonl", "comparison_only", b'{"fixture":1}\n')]}
    sources = []
    staging = root / "staging"
    for source, entries in files.items():
        records = []
        for name, use, data in entries:
            rel = f"{source}/{date}/{name}"
            (staging / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
            (staging / "files" / rel).write_bytes(data)
            records.append({"name": name, "path": rel, "sha256": hashlib.sha256(data).hexdigest(),
                            "bytes": len(data), "rows": data.count(b"\n"), "use": use})
        sources.append({"source": source, "snapshot_id": f"SNAP-{source}-{date}", "date": date, "version_hint": None,
                        "license": "fixture", "origin": "kbase_kinase processed snapshot", "url_count": 0,
                        "raw_sha256": [], "files": records})
    manifest = {"schema": "reference_snapshot_set@1", "imported_at": "fixture",
                "kbase_repo": {"commit": "0" * 40, "dirty": False}, "sources": sources}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    (staging / "manifest.json").write_bytes(raw)
    set_hash = hashlib.sha256(raw).hexdigest()
    (root / "sets").mkdir()
    staging.rename(root / "sets" / set_hash)
    (root / "active.json").write_bytes(json.dumps({"schema": "reference_active@1", "set_hash": set_hash},
                                                  separators=(",", ":")).encode())


def test_pinned_set_index_is_cached_per_set_hash(tmp_path, monkeypatch):
    _write_set(tmp_path)
    monkeypatch.setenv(rs.ENV_VAR, str(tmp_path))
    pinned = rs.pin_active_set()
    first = sm.index_for_set(pinned)
    assert sm.index_for_set(rs.pin_active_set()) is first
    chain = sm.lookup_chain("1MQ4", "A")
    assert isinstance(chain, sm.SiftsChain) and chain.uniprot_position(1, 7) == ("O14965", 126)
    assert sm.lookup_chain("1MQ4", "A") is chain          # decoded chains are cached inside the index
    assert sm.sifts_chains_for_pdb("3CS9") == [{"chain_auth": "A", "accessions": ["P00519"], "reason_code": None}]
    _unusable(sm.lookup_chain("9ZZZ", "A", pinned=pinned), "pdb_not_in_sifts_snapshot")


def test_malformed_snapshot_rows_raise():
    with pytest.raises(sm.SiftsFormatError):
        sm.SiftsIndex([{"id": "X"}], SEG)
    with pytest.raises(sm.SiftsFormatError):
        sm.SiftsIndex(RES, [["not", "a", "row"]])
