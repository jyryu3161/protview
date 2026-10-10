"""M27 pure precedent linking (mw.kinase_precedents): set index (spec 3.5), chain judgement (5.3), targets and record
copies (5.4-5.5), the ``kinase_precedents@1`` result (5.6) and ``validated_result``.

Inputs are LABELLED SYNTHETIC fixtures (``fixtures/precedent/t2/``, see SYNTHETIC-PROVENANCE-t2.md): made-up records,
references, bibliography rows and hand-built numbering-map dicts. The expected results come from the independent
standard-library oracle ``independent_match.py`` (``expected.json``); further expectations below are written by hand
from the spec text. No real kbase_kinase data, no network, no ``.deps`` folder.
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

import precedent_fixture as PF
import pytest

from mw import kinase_precedents as kp
from mw import precedent_constants as K
from mw import precedent_snapshots as ps

T2 = PF.T2
EXPECTED = json.loads((T2 / "expected.json").read_text(encoding="utf-8"))
CASES = EXPECTED["cases"]
MAPS = json.loads((T2 / "numbering_maps.json").read_text(encoding="utf-8"))


@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "precedent_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    return root


@pytest.fixture
def world(ref):
    PF.build_set(ref)
    return kp.pin_and_index()


def build(world, map_name="main", chains=None, include_flagged=False, nmap=None):
    pinned, index = world
    return kp.build_kinase_precedents(
        pinned=pinned, index=index,
        numbering_map=copy.deepcopy(MAPS["maps"][map_name]) if nmap is None else nmap,
        numbering_map_handle=MAPS["map_handles"][map_name], chains=chains, include_flagged=include_flagged)


def without_set(result):
    return {k: v for k, v in result.items() if k != "precedent_set"}


def same(a, b) -> bool:
    return K.canonical_json(a) == K.canonical_json(b)


def originals():
    records = PF.t2_records()
    return {r["move_id"]: r for r in records["moves"] + records["moves_flagged"]}


def target(result, accession):
    (found,) = [t for t in result["targets"] if t["accession"] == accession]
    return found


# ------------------------------------------------------------------------------------------- oracle

def test_oracle_expected_json_matches_a_fresh_oracle_run():
    out = subprocess.run([sys.executable, str(T2 / "independent_match.py"), "--check"], capture_output=True,
                         text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    source = (T2 / "independent_match.py").read_text()
    assert not re.search(r"^\s*(from|import)\s+mw\b", source, re.MULTILINE)
    tree = ast.parse(source)
    modules = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
               for alias in node.names}
    modules |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert modules - {"__future__"} <= set(sys.stdlib_module_names)


@pytest.mark.parametrize("name", sorted(CASES))
def test_result_equals_the_oracle(world, name):
    case = CASES[name]
    result = build(world, case["map"], case["chains"], case["include_flagged"])
    assert same(without_set(result), case["result"]), name
    assert kp.validated_result(result) is result


def test_oracle_cases_cover_every_state_the_spec_names():
    chains = [c for case in CASES.values() for c in case["result"]["chains"]]
    targets = [t for case in CASES.values() for t in case["result"]["targets"]]
    items = [item for t in targets for item in t["records"]]
    assert {(c["status"], c["reason"]) for c in chains} == {("linked", None), ("not_linked", "no_mapped_residues"),
                                                            ("not_linked", "multiple_accessions")}
    assert any(c["status"] == "linked" and c["mapped_residue_count"] == 1 for c in chains)
    assert {t["status"] for t in targets} == set(K.TARGET_STATUSES)
    excluded = [t["excluded_flagged"] for t in targets]
    assert None in excluded and 0 in excluded and any(type(v) is int and v > 0 for v in excluded)
    assert any(t["status"] == "none_in_included_files" and t["counts"]["moves"] == 0 and t["excluded_flagged"]
               for t in targets)
    assert any(len(t["chains"]) >= 2 for t in targets) and any(len(t["references"]) >= 2 for t in targets)
    assert {"name_token", "pubmed_title", "alias", "notation"} <= {i["record"]["target"]["resolution_basis"]
                                                                   for i in items}
    assert {i["file"] for i in items} == set(K.FILE_SOURCES)
    assert {i["integrity"]["quotes_within_limit"] for i in items} == {True, False}
    books = [v for case in CASES.values() for v in case["result"]["bibliography"].values()]
    assert None in books and any(isinstance(v, dict) for v in books)
    assert {case["result"]["null_result"] for case in CASES.values()} == {True, False}


# ------------------------------------------------------------------------------------------- spelled out by hand

def test_chain_rows_follow_map_order_and_ignore_unmapped_and_conflict_rows():
    nmap = MAPS["maps"]["main"]
    rows = kp.chain_rows(nmap, ["E", "A", "D"])
    assert [r["chain_auth"] for r in rows] == ["A", "D", "E"]  # map order, not request order
    a, d, e = rows
    assert (a["status"], a["accession"], a["accessions"]) == ("linked", "P0SYN1", ["P0SYN1"])  # conflict Q0SYN4 unused
    assert (d["status"], d["reason"], d["accession"], d["accessions"]) == (
        "not_linked", "no_mapped_residues", None, [])  # an unmapped row naming P0SYN1 is no evidence
    assert (e["status"], e["reason"], e["accession"], e["accessions"]) == (
        "not_linked", "multiple_accessions", None, ["P0SYN3", "Q0SYN4"])
    assert (a["mapped_residue_count"], a["total_residue_count"]) == (2, 3)
    assert [r["chain_auth"] for r in kp.chain_rows(nmap, None)] == ["C", "A", "B", "D", "E"]
    for bad in (["Z"], ["A", "A"], []):
        with pytest.raises(ValueError):
            kp.chain_rows(nmap, bad)


def test_same_accession_on_two_chains_gives_one_target_and_two_chain_rows(world):
    result = build(world, chains=["A", "C"])
    assert [c["chain_auth"] for c in result["chains"]] == ["C", "A"]
    assert [t["accession"] for t in result["targets"]] == ["P0SYN1"]
    assert result["targets"][0]["chains"] == ["A", "C"]
    assert result["counts"]["chains"] == 2 and result["counts"]["targets"] == 1


def test_unresolved_and_other_target_records_are_never_linked(world):
    result = build(world, include_flagged=True)
    linked = {i["record"]["move_id"] for t in result["targets"] for i in t["records"]}
    assert linked == {"MOVE-0001", "MOVE-0007", "MOVE-9999", "MOVE-10000", "MOVE-0101", "MOVE-0102", "MOVE-0103"}
    assert not {"MOVE-0004", "MOVE-0005", "MOVE-0006", "MOVE-0105", "MOVE-0106"} & linked  # P0SYN6 and null targets
    summary = result["set_summary"]
    assert summary["unresolved_target_records"] == {"moves": 2, "moves_flagged": 2}
    assert summary["unresolved_names"] == [
        {"name_as_written": "SYN-UNRESOLVED-A", "moves": 1, "moves_flagged": 1},
        {"name_as_written": None, "moves": 1, "moves_flagged": 0},
        {"name_as_written": "SYN-UNRESOLVED-B", "moves": 0, "moves_flagged": 1}]
    assert summary["unresolved_names_total"] == 3
    n = sum(summary["unresolved_target_records"].values())
    assert K.screen_note("UP5", n) == "표적이 해석되지 않은 전례 4건(세트 전체)이 있어 어느 체인에도 연결하지 못했다."


def test_unresolved_names_are_capped_at_100_and_the_total_is_kept(ref):
    extra = [PF.make_move(f"MOVE-{5000 + i}", uniprot=None, resolution_basis="unmapped",
                          name_as_written=f"SYN-NAME-{i:03d}") for i in range(102)]
    extra.append(PF.make_move("MOVE-5999", uniprot=None, resolution_basis="unmapped", name_as_written="SYN-NAME-050"))
    PF.build_set(ref, moves=PF.t2_records()["moves"] + extra)
    world = kp.pin_and_index()
    summary = kp.set_summary(world[1])
    names = summary["unresolved_names"]
    assert len(names) == 100 and summary["unresolved_names_total"] == 105  # 102 new + SYN-UNRESOLVED-A, -B, null
    assert summary["unresolved_target_records"] == {"moves": 105, "moves_flagged": 2}
    assert names[0] == {"name_as_written": "SYN-NAME-050", "moves": 2, "moves_flagged": 0}  # ties: name ascending
    assert names[1] == {"name_as_written": "SYN-UNRESOLVED-A", "moves": 1, "moves_flagged": 1}
    assert names[2] == {"name_as_written": None, "moves": 1, "moves_flagged": 0}  # null first among equal counts
    assert names[3]["name_as_written"] == "SYN-NAME-000"
    assert kp.validated_result(build(world)) is not None


def test_inferred_target_records_are_linked_with_their_basis_shown(world):
    p1 = target(build(world), "P0SYN1")
    assert {i["record"]["move_id"]: i["record"]["target"]["resolution_basis"] for i in p1["records"]} == {
        "MOVE-0001": "gene", "MOVE-0007": "alias", "MOVE-9999": "name_token", "MOVE-10000": "pubmed_title"}
    assert p1["counts"]["resolution_basis"] == [{"basis": "alias", "count": 1}, {"basis": "gene", "count": 1},
                                                {"basis": "name_token", "count": 1},
                                                {"basis": "pubmed_title", "count": 1}]


def test_included_and_excluded_counts_are_separate_fields_null_versus_integer(world):
    excluded = build(world)
    p1, q2 = target(excluded, "P0SYN1"), target(excluded, "Q0SYN2")
    assert (p1["counts"]["moves_flagged"], p1["excluded_flagged"]) == (None, 1)
    assert (q2["status"], q2["counts"]["moves"], q2["counts"]["moves_flagged"], q2["excluded_flagged"]) == (
        "none_in_included_files", 0, None, 2)
    assert K.screen_note("UP2", q2["excluded_flagged"]) == "moves_flagged 파일의 전례 2건은 포함하지 않았다."
    assert excluded["counts"]["records"] == {"moves": 4, "moves_flagged": None}
    assert excluded["counts"]["excluded_moves_flagged"] == 3
    included = build(world, include_flagged=True)
    p1, q2 = target(included, "P0SYN1"), target(included, "Q0SYN2")
    assert (p1["counts"]["moves_flagged"], p1["excluded_flagged"]) == (1, None)
    assert (q2["status"], q2["counts"]["moves_flagged"], q2["excluded_flagged"]) == ("precedents_found", 2, None)
    assert included["counts"]["records"] == {"moves": 4, "moves_flagged": 3}
    assert included["counts"]["excluded_moves_flagged"] is None
    refs_only = build(world, "refs_only")
    p3, q4, o5 = (target(refs_only, a) for a in ("P0SYN3", "Q0SYN4", "O0SYN5"))
    assert (p3["status"], p3["excluded_flagged"]) == ("none_in_included_files", 0)  # 0 stays an integer
    assert (q4["status"], q4["excluded_flagged"], q4["references"]) == ("not_in_kbase_references", 0, [])
    assert (o5["status"], o5["excluded_flagged"]) == ("not_in_kbase_references", 1)
    assert refs_only["null_result"] is True
    unlinked = build(world, "unlinked")
    assert unlinked["targets"] == [] and unlinked["null_result"] is True
    assert unlinked["counts"] == {"chains": 1, "linked_chains": 0, "not_linked_chains": 1, "targets": 0,
                                  "records": {"moves": 0, "moves_flagged": None}, "excluded_moves_flagged": 0}


def test_records_are_in_move_number_order_and_references_by_ref_id(world):
    p1 = target(build(world, include_flagged=True), "P0SYN1")
    assert [(i["file"], i["record"]["move_id"]) for i in p1["records"]] == [
        ("moves", "MOVE-0001"), ("moves", "MOVE-0007"), ("moves_flagged", "MOVE-0101"), ("moves", "MOVE-9999"),
        ("moves", "MOVE-10000")]
    assert [r["ref_id"] for r in p1["references"]] == ["REF-SYN-0001", "REF-SYN-0002"]  # both kept, none chosen
    assert set(p1["references"][0]) == {"ref_id", "gene", "klifs_name", "group", "family", "coverage", "content_hash"}


def test_move_ids_with_the_same_number_are_ordered_by_the_move_id_string(ref):
    """``^MOVE-\\d{4,}$`` admits ``MOVE-0001`` and ``MOVE-00001`` (the same integer part, distinct move IDs): the fixed
    record order is (integer part, ``move_id`` string), in the index, the result and ``validated_result``."""
    moves = [PF.make_move("MOVE-0002"), PF.make_move("MOVE-0001"), PF.make_move("MOVE-00001")]  # SYNTHETIC records
    PF.build_set(ref, moves=moves, moves_flagged=[])
    world = kp.pin_and_index()
    order = ["MOVE-00001", "MOVE-0001", "MOVE-0002"]
    assert [r["move_id"] for _f, r in world[1].by_uniprot["P0SYN1"]] == order
    result = build(world, chains=["A"])
    assert [i["record"]["move_id"] for i in result["targets"][0]["records"]] == order
    assert kp.validated_result(result) is result
    assert kp.move_key("MOVE-00001") < kp.move_key("MOVE-0001") < kp.move_key("MOVE-0002") < kp.move_key("MOVE-10")
    swapped = copy.deepcopy(result)
    records = swapped["targets"][0]["records"]
    records[0], records[1] = records[1], records[0]
    with pytest.raises(kp.ResultInvalid):
        kp.validated_result(swapped)


def test_bibliography_present_or_null(world):
    books = build(world, include_flagged=True)["bibliography"]
    assert list(books) == ["90000001", "90000002", "90000003", "90000004", "90000005"]
    assert books["90000001"] == {"title": "합성 SYNTHETIC fixture title 90000001", "journal": "Synthetic Fixture Journal",
                                 "year": "2020", "doi": "10.0000/synthetic.1", "pmc": "PMC0000001"}
    assert books["90000002"] is None  # not in the snapshot
    assert books["90000003"] is None  # status is not "ok"
    assert books["90000004"] is None  # data.pmid differs from id
    assert books["90000005"]["year"] == "2021"


def test_record_copy_drops_exactly_two_paths_and_keeps_the_original_hash(world):
    source = originals()
    for item in [i for t in build(world, include_flagged=True)["targets"] for i in t["records"]]:
        original = copy.deepcopy(source[item["record"]["move_id"]])
        assert "parser" in original["source"] and "measurements" in original["checks"]["cross_parser_numbers"]
        del original["source"]["parser"]
        del original["checks"]["cross_parser_numbers"]["measurements"]
        assert same(item["record"], original)
        assert item["record"]["content_hash"] == source[item["record"]["move_id"]]["content_hash"]
        assert K.content_hash(item["record"]) != item["record"]["content_hash"]  # not recomputed on the copy
        assert item["record"]["extraction"]["notes"] == "SYNTHETIC nested key kept as is"


def test_integrity_values_and_a_long_quote_is_shown_not_dropped(world):
    items = {i["record"]["move_id"]: i for t in build(world)["targets"] for i in t["records"]}
    assert items["MOVE-9999"]["integrity"] == {"hash_verified": True, "observation_quote_words": 26,
                                               "tradeoff_quote_words": [None, 4], "quotes_within_limit": False,
                                               "locations_have_page": True}
    assert items["MOVE-0001"]["integrity"] == {"hash_verified": True, "observation_quote_words": 4,
                                               "tradeoff_quote_words": [], "quotes_within_limit": True,
                                               "locations_have_page": True}


def test_record_hash_mismatch_at_call_time_is_snapshot_invalid(world):
    _pinned, index = world
    for _file, record in index.by_uniprot["P0SYN1"]:
        if record["move_id"] == "MOVE-0007":
            record["observation"]["text"] = "SYNTHETIC changed in memory after the set was read"
    with pytest.raises(ps.SnapshotUnavailable) as err:
        build(world)
    assert err.value.reason_code == "snapshot_invalid"
    assert kp._INDEX_CACHE == {}  # the damaged index is dropped; the next pin re-reads the files
    fresh = kp.pin_and_index()
    assert fresh[1] is not index
    build(fresh)


def test_same_input_same_result_and_request_order_does_not_matter(world):
    first = build(world, chains=["B", "C"])
    assert same(first, build(world, chains=["C", "B"]))
    every = [c["chain_auth"] for c in MAPS["maps"]["main"]["chains"]]
    assert same(build(world), build(world, chains=every))
    raw = K.canonical_json(build(world, include_flagged=True))
    for word in (b"created", b"call_id", b"timestamp"):
        assert word not in raw


def test_precedent_set_block_comes_from_the_manifest(world):
    pinned, _index = world
    manifest = pinned.manifest
    block = build(world)["precedent_set"]
    plain = [{k: f[k] for k in ("name", "path", "sha256", "bytes", "rows")} for f in manifest["files"]]
    bib = manifest["bibliography"]
    assert block == {
        "set_hash": pinned.set_hash, "imported_at": PF.IMPORTED_AT, "importer_version": "precedent_import/1",
        "kbase": manifest["kbase"], "files": plain,
        "bibliography_snapshot": {"snapshot_id": bib["snapshot_id"], "date": bib["date"], "license": bib["license"],
                                  "origin": "kbase_kinase processed ref/pubmed",
                                  "file": {k: bib["file"][k] for k in ("name", "path", "sha256", "bytes", "rows")}}}


def test_result_does_not_share_objects_with_the_cached_index(world):
    result = build(world)
    result["targets"][0]["records"][0]["record"]["observation"]["text"] = "edited copy"
    result["bibliography"]["90000001"]["title"] = "edited copy"
    result["set_summary"]["unresolved_names"].clear()
    again = build(world)
    assert same(without_set(again), CASES["main_all_excluded"]["result"])


def test_validation_needs_no_reference_folder(ref, world):
    result = build(world, include_flagged=True)
    shutil.rmtree(ref)
    assert kp.validated_result(json.loads(K.canonical_json(result))) is not None


# ------------------------------------------------------------------------------------------- index

def test_index_content(world):
    _pinned, index = world
    assert set(index.by_uniprot) == {"P0SYN1", "P0SYN6", "Q0SYN2", "O0SYN5"}
    assert [(f, r["move_id"]) for f, r in index.by_uniprot["P0SYN1"]] == [
        ("moves", "MOVE-0001"), ("moves", "MOVE-0007"), ("moves_flagged", "MOVE-0101"), ("moves", "MOVE-9999"),
        ("moves", "MOVE-10000")]
    assert [r["ref_id"] for r in index.references_by_uniprot["P0SYN1"]] == ["REF-SYN-0001", "REF-SYN-0002"]
    assert set(index.references_by_uniprot) == {"P0SYN1", "Q0SYN2", "P0SYN3", "P0SYN6", "Q0SYN7"}
    assert set(index.bibliography) == {"90000001", "90000005", "90000006"}
    assert same(kp.set_summary(index), CASES["main_all_excluded"]["result"]["set_summary"])
    summary = kp.set_summary(index)
    summary["records"]["moves"] = 0
    assert kp.set_summary(index)["records"]["moves"] == 7  # a copy each time


def test_index_is_built_once_per_set_and_keeps_one_set(ref, monkeypatch):
    calls = []
    real = K.validate_dist_files

    def counting(*args):
        calls.append(1)
        return real(*args)

    monkeypatch.setattr(K, "validate_dist_files", counting)
    PF.build_set(ref)
    first = kp.pin_and_index()[1]
    assert kp.pin_and_index()[1] is first and len(calls) == 1
    kp.capability()
    assert len(calls) == 1
    PF.build_set(ref, imported_at="2026-10-10T00:00:06Z")
    second = kp.pin_and_index()[1]
    assert second is not first and len(calls) == 2
    assert len(kp._INDEX_CACHE) == 1


def _bad_hash_move():
    record = PF.make_move("MOVE-0201", uniprot="P0SYN1")
    record["observation"]["text"] = "SYNTHETIC edited after hashing"
    return record


DAMAGED_SETS = [
    ("record hash differs", lambda r: {"moves": r["moves"] + [_bad_hash_move()]}),
    ("unknown vocabulary term", lambda r: {"moves_flagged": r["moves_flagged"] + [PF.make_move("MOVE-0202",
                                                                                               tactic=["magic"])]}),
    ("review status", lambda r: {"moves": r["moves"] + [PF.make_move("MOVE-0203", review_status="reviewed")]}),
    ("move_id across files", lambda r: {"moves_flagged": r["moves_flagged"] + [PF.make_move("MOVE-0001")]}),
    ("reference hash differs", lambda r: {"references": r["references"] + [
        PF.make_reference("REF-SYN-0009", "P0SYN1") | {"family": "edited"}]}),
    ("pubmed id repeats", lambda r: {"pubmed": r["pubmed"] + [PF.make_pubmed_row("90000001")]}),
    ("not a JSON line", lambda r: {"file_bytes": {"moves": PF.jsonl(r["moves"]) + b"not json\n"}}),
]


@pytest.mark.parametrize("name, damage", DAMAGED_SETS, ids=[n for n, _ in DAMAGED_SETS])
def test_set_with_invalid_records_is_snapshot_invalid_and_not_cached(ref, name, damage):
    PF.build_set(ref, **damage(PF.t2_records()))
    assert ps.capability()["available"] is True  # hashes match: only decoding the records finds the problem
    with pytest.raises(ps.SnapshotUnavailable) as err:
        kp.pin_and_index()
    assert err.value.reason_code == "snapshot_invalid"
    assert kp._INDEX_CACHE == {}
    assert kp.capability() == {"available": False, "reason_code": "snapshot_invalid",
                               "reason": K.SNAPSHOT_REASONS["snapshot_invalid"], "set_hash": None, "sources": []}


def test_verification_counts_must_match_the_records(ref):
    records = PF.t2_records()
    records["references"][0] = PF.make_reference("REF-SYN-0002", "P0SYN1", hashed=False)

    def claim_all_hashed(manifest):
        verification = manifest["verification"]
        verification["records_hash_verified"]["references"] += verification["references_without_hash"]
        verification["references_without_hash"] = 0

    PF.build_set(ref, references=records["references"], manifest_patch=claim_all_hashed)
    with pytest.raises(ps.SnapshotUnavailable) as err:
        kp.pin_and_index()
    assert err.value.reason_code == "snapshot_invalid"


def test_capability_shapes(ref, tmp_path, monkeypatch):
    set_hash = PF.build_set(ref)
    cap = kp.capability()
    assert cap == {"available": True, "reason_code": None, "reason": None, "set_hash": set_hash,
                   "sources": ps.pin_active_set().summary()}
    assert [s["source"] for s in cap["sources"]] == ["kbase_dist", "kbase_pubmed"]
    monkeypatch.setenv(K.ENV_VAR, str(tmp_path / "absent"))
    assert kp.capability() == {"available": False, "reason_code": "not_installed",
                               "reason": K.SNAPSHOT_REASONS["not_installed"], "set_hash": None, "sources": []}


# ------------------------------------------------------------------------------------------- size cap

def _big_move(move_id, uniprot):
    return PF.make_move(move_id, uniprot=uniprot, observation_text="SYNTHETIC filler " * 1250)  # ~21 KB each


def _big_world(ref):
    moves = [_big_move(f"MOVE-{1000 + i}", "P0SYN1") for i in range(28)]
    moves += [_big_move(f"MOVE-{2000 + i}", "Q0SYN2") for i in range(28)]
    flagged = [_big_move(f"MOVE-{3000 + i}", "P0SYN1") for i in range(28)]
    PF.build_set(ref, moves=moves, moves_flagged=flagged)
    return kp.pin_and_index()


def test_result_above_one_mib_is_refused_with_hints_and_nothing_returned(ref):
    world = _big_world(ref)
    alone = build(world, chains=["A"], include_flagged=False)
    assert len(K.canonical_json(alone)) < K.MAX_RESULT_BYTES
    with pytest.raises(kp.ResultTooLarge) as err:
        build(world, chains=["A"], include_flagged=True)
    exc = err.value
    assert exc.limit == K.MAX_RESULT_BYTES and exc.actual > K.MAX_RESULT_BYTES
    assert exc.size_without_flagged == len(K.canonical_json(alone))
    assert exc.target_sizes == [{"accession": "P0SYN1", "chains": ["A"], "bytes": exc.actual}]
    assert "include_flagged" in str(exc) and "P0SYN1" in str(exc)
    with pytest.raises(kp.ResultTooLarge) as err:
        build(world, chains=["A", "B"], include_flagged=False)  # two targets: split the chains
    exc = err.value
    assert exc.size_without_flagged is None
    assert [t["accession"] for t in exc.target_sizes] == ["P0SYN1", "Q0SYN2"]
    assert all(t["bytes"] < K.MAX_RESULT_BYTES for t in exc.target_sizes)
    assert "체인 A)" in str(exc) and "체인 B)" in str(exc)
    assert issubclass(kp.ResultTooLarge, kp.ResourceExceeded)


def test_size_cap_uses_canonical_json_bytes(world, monkeypatch):
    size = len(K.canonical_json(build(world)))
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", size)
    build(world)
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", size - 1)
    with pytest.raises(kp.ResultTooLarge):
        build(world)


# ------------------------------------------------------------------------------------------- numbering map shape

def test_numbering_map_shape_check():
    for nmap in MAPS["maps"].values():
        assert kp.numbering_map_shape_ok(nmap)
    bad = [
        lambda m: m.pop("schema"),
        lambda m: m.update(schema="residue_numbering_map@2"),
        lambda m: m.pop("pdb_id"),
        lambda m: m.update(pdb_id=5),
        lambda m: m["structure"].pop("model_number"),
        lambda m: m["structure"].update(model_number=True),
        lambda m: m["structure"].update(handle=None),
        lambda m: m.update(chains={}),
        lambda m: m["chains"][0].pop("counts"),
        lambda m: m["chains"][0]["counts"].pop("conflict"),
        lambda m: m["chains"][0]["counts"].update(mapped=True),
        lambda m: m["chains"][0]["counts"].update(mapped=-1),
        lambda m: m["chains"][0].update(cross_check="yes"),
        lambda m: m["chains"][0].pop("cross_check_absent_reason"),
        lambda m: m["chains"][0].update(cross_check_absent_reason=3),
        lambda m: m["chains"][0].update(chain_auth=""),
        lambda m: m["chains"].append(copy.deepcopy(m["chains"][0])),
        lambda m: m.update(rows=None),
        lambda m: m["rows"][0]["residue"].pop("chain_auth"),
        lambda m: m["rows"][0].update(residue="C1"),
        lambda m: m["rows"][0].update(status=1),
        lambda m: m["rows"][0].pop("uniprot_accession"),
        lambda m: m["rows"][0].update(uniprot_accession=None),  # a mapped row always names its accession
        lambda m: m["rows"][3].update(uniprot_accession=7),
    ]
    for mutate in bad:
        nmap = copy.deepcopy(MAPS["maps"]["main"])
        mutate(nmap)
        assert not kp.numbering_map_shape_ok(nmap), mutate
    for value in (None, [], "map"):
        assert not kp.numbering_map_shape_ok(value)


# ------------------------------------------------------------------------------------------- validated_result

def _set(obj, path, value):
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


def _get(obj, path):
    for key in path:
        obj = obj[key]
    return obj


P1 = ["targets", 0]
P1_REC = P1 + ["records"]
TAMPER_INCLUDED = [
    ("extra top key", lambda r: r.update(created_at="2026-10-10")),
    ("missing top key", lambda r: r.pop("limitations")),
    ("schema", lambda r: r.update(schema="kinase_precedents@2")),
    ("method version", lambda r: r.update(method_version="mw.kinase_precedents/v2")),
    ("record format", lambda r: r.update(record_format="kbase_record@1")),
    ("include flag string", lambda r: r.update(include_flagged="true")),
    ("include flag flipped", lambda r: r.update(include_flagged=False)),
    ("map extra key", lambda r: r["numbering_map"].update(pdb_id="0SY5")),
    ("map other run", lambda r: _set(r, ["numbering_map", "handle"], "obj://run_x/residue_numbering_map/" + "b" * 64)),
    ("map other kind", lambda r: _set(r, ["numbering_map", "handle"], "obj://run_syn/structure/" + "b" * 64)),
    ("structure kind", lambda r: _set(r, ["structure", "structure_kind"], "structure")),
    ("structure model bool", lambda r: _set(r, ["structure", "model_number"], True)),
    ("pdb lowercase", lambda r: r.update(pdb_id="0sy5")),
    ("set extra key", lambda r: r["precedent_set"].update(origin="x")),
    ("set hash short", lambda r: _set(r, ["precedent_set", "set_hash"], "abc")),
    ("set importer", lambda r: _set(r, ["precedent_set", "importer_version"], "precedent_import/2")),
    ("set kbase pin", lambda r: _set(r, ["precedent_set", "kbase", "effect_rules_version"], "2")),
    ("set files kbase sha back", lambda r: _get(r, ["precedent_set", "files", 0]).update(kbase_sha256="sha256:x")),
    ("set files order", lambda r: _get(r, ["precedent_set", "files"]).reverse()),
    ("set bibliography origin", lambda r: _set(r, ["precedent_set", "bibliography_snapshot", "origin"], "pubmed")),
    ("set bibliography file name", lambda r: _set(r, ["precedent_set", "bibliography_snapshot", "date"],
                                                  "2026-10-02")),
    ("no chains", lambda r: r.update(chains=[])),
    ("duplicate chain", lambda r: r["chains"].append(copy.deepcopy(r["chains"][0]))),
    ("chain status flipped", lambda r: _set(r, ["chains", 0, "status"], "not_linked")),
    ("chain unknown reason", lambda r: (_set(r, ["chains", 3, "reason"], "fusion"))),
    ("chain reason swapped", lambda r: _set(r, ["chains", 4, "reason"], "no_mapped_residues")),
    ("chain accession other", lambda r: _set(r, ["chains", 0, "accession"], "Q0SYN2")),
    ("chain accessions unsorted", lambda r: _get(r, ["chains", 4, "accessions"]).reverse()),
    ("chain linked without accession", lambda r: _set(r, ["chains", 0, "accessions"], [])),
    ("chain mapped above total", lambda r: _set(r, ["chains", 0, "mapped_residue_count"], 9)),
    ("chain zero mapped but accession", lambda r: _set(r, ["chains", 0, "mapped_residue_count"], 0)),
    ("chain cross check string", lambda r: _set(r, ["chains", 0, "cross_check"], "yes")),
    ("chain extra key", lambda r: r["chains"][0].update(klifs="x")),
    ("targets reversed", lambda r: r["targets"].reverse()),
    ("target dropped", lambda r: r["targets"].pop()),
    ("target chains", lambda r: _set(r, P1 + ["chains"], ["C"])),
    ("target status", lambda r: _set(r, P1 + ["status"], "none_in_included_files")),
    ("target excluded while included", lambda r: _set(r, P1 + ["excluded_flagged"], 0)),
    ("references reordered", lambda r: _get(r, P1 + ["references"]).reverse()),
    ("reference extra key", lambda r: _get(r, P1 + ["references", 0]).update(uniprot="P0SYN1")),
    ("reference hash format", lambda r: _set(r, P1 + ["references", 0, "content_hash"], "abc")),
    ("records reordered", lambda r: _get(r, P1_REC).reverse()),
    ("record dropped", lambda r: _get(r, P1_REC).pop()),
    ("record duplicated", lambda r: _get(r, P1_REC).append(copy.deepcopy(_get(r, P1_REC)[-1]))),
    ("record file unknown", lambda r: _set(r, P1_REC + [0, "file"], "moves_passed")),
    ("record file swapped", lambda r: _set(r, P1_REC + [2, "file"], "moves")),
    ("record extra key", lambda r: _get(r, P1_REC + [0]).update(score=1)),
    ("record other target", lambda r: _set(r, P1_REC + [0, "record", "target", "uniprot"], "Q0SYN2")),
    ("record parser restored", lambda r: _set(r, P1_REC + [0, "record", "source", "parser"], {"x": 1})),
    ("record measurements restored", lambda r: _set(r, P1_REC + [0, "record", "checks", "cross_parser_numbers",
                                                                  "measurements"], [])),
    ("record reviewed", lambda r: _set(r, P1_REC + [0, "record", "review_status"], "reviewed")),
    ("record hash format", lambda r: _set(r, P1_REC + [0, "record", "content_hash"], "sha256:00")),
    ("record vocabulary", lambda r: _set(r, P1_REC + [0, "record", "tags", "site"], ["bp_VI"])),
    ("record move id", lambda r: _set(r, P1_REC + [0, "record", "move_id"], "MOVE-1")),
    ("integrity hash false", lambda r: _set(r, P1_REC + [0, "integrity", "hash_verified"], False)),
    ("integrity words", lambda r: _set(r, P1_REC + [0, "integrity", "observation_quote_words"], 5)),
    ("integrity limit flipped", lambda r: _set(r, P1_REC + [3, "integrity", "quotes_within_limit"], True)),
    ("integrity tradeoffs", lambda r: _set(r, P1_REC + [3, "integrity", "tradeoff_quote_words"], [4])),
    ("integrity pages false", lambda r: _set(r, P1_REC + [0, "integrity", "locations_have_page"], False)),
    ("integrity extra key", lambda r: _get(r, P1_REC + [0, "integrity"]).update(verified=True)),
    ("counts moves", lambda r: _set(r, P1 + ["counts", "moves"], 5)),
    ("counts flagged null while included", lambda r: _set(r, P1 + ["counts", "moves_flagged"], None)),
    ("counts variant count", lambda r: _set(r, P1 + ["counts", "variants", 0, "count"], 2)),
    ("counts variants order", lambda r: _get(r, P1 + ["counts", "variants"]).reverse()),
    ("counts tag count", lambda r: _set(r, P1 + ["counts", "tags", "goal", 1, "count"], 1)),
    ("counts tag axis missing", lambda r: _get(r, P1 + ["counts", "tags"]).pop("tactic")),
    ("counts basis", lambda r: _set(r, P1 + ["counts", "resolution_basis", 0, "basis"], "gene")),
    ("bibliography missing pmid", lambda r: r["bibliography"].pop("90000002")),
    ("bibliography extra pmid", lambda r: r["bibliography"].update({"90000006": None})),
    ("bibliography value text", lambda r: r["bibliography"].update({"90000002": "no bibliography"})),
    ("bibliography extra field", lambda r: r["bibliography"]["90000001"].update(abstract="x")),
    ("summary records", lambda r: _set(r, ["set_summary", "records", "moves"], 8)),
    ("summary names order", lambda r: _get(r, ["set_summary", "unresolved_names"]).reverse()),
    ("summary names total", lambda r: _set(r, ["set_summary", "unresolved_names_total"], 2)),
    ("summary unresolved", lambda r: _set(r, ["set_summary", "unresolved_target_records", "moves"], 3)),
    ("summary unknown basis", lambda r: _set(r, ["set_summary", "resolution_basis_counts", 0, "basis"], "guess")),
    ("summary zero basis", lambda r: _get(r, ["set_summary", "resolution_basis_counts"]).insert(
        0, {"basis": "absent", "moves": 0, "moves_flagged": 0})),
    ("summary references float", lambda r: _set(r, ["set_summary", "references"], 6.0)),
    ("counts chains", lambda r: _set(r, ["counts", "chains"], 4)),
    ("counts linked", lambda r: _set(r, ["counts", "linked_chains"], 2)),
    ("counts targets", lambda r: _set(r, ["counts", "targets"], 3)),
    ("counts records moves", lambda r: _set(r, ["counts", "records", "moves"], 0)),
    ("counts records flagged null", lambda r: _set(r, ["counts", "records", "moves_flagged"], None)),
    ("counts excluded while included", lambda r: _set(r, ["counts", "excluded_moves_flagged"], 0)),
    ("null result", lambda r: r.update(null_result=True)),
    ("limitations order", lambda r: r["limitations"].reverse()),
    ("limitation text", lambda r: _set(r, ["limitations", 0], "다른 문장.")),
    ("limitation dropped", lambda r: r["limitations"].pop()),
    ("KT1 added", lambda r: r["limitations"].append(K.STATEMENTS["KT1"])),
]
TAMPER_EXCLUDED = [
    ("excluded null", lambda r: _set(r, P1 + ["excluded_flagged"], None)),
    ("included count zero instead of null", lambda r: _set(r, P1 + ["counts", "moves_flagged"], 0)),
    ("total included zero instead of null", lambda r: _set(r, ["counts", "records", "moves_flagged"], 0)),
    ("total excluded null", lambda r: _set(r, ["counts", "excluded_moves_flagged"], None)),
    ("total excluded differs", lambda r: _set(r, ["counts", "excluded_moves_flagged"], 1)),
    ("flagged record while excluded", lambda r: _set(r, P1_REC + [0, "file"], "moves_flagged")),
    ("include flag flipped", lambda r: r.update(include_flagged=True)),
]


@pytest.mark.parametrize("name, mutate", TAMPER_INCLUDED, ids=[n for n, _ in TAMPER_INCLUDED])
def test_validated_result_rejects_tampering_with_an_included_result(world, name, mutate):
    result = build(world, include_flagged=True)
    kp.validated_result(result)
    tampered = copy.deepcopy(result)
    mutate(tampered)
    with pytest.raises(kp.ResultInvalid) as err:
        kp.validated_result(tampered)
    assert str(err.value).startswith("kinase_precedents@1")


@pytest.mark.parametrize("name, mutate", TAMPER_EXCLUDED, ids=[n for n, _ in TAMPER_EXCLUDED])
def test_validated_result_rejects_tampering_with_an_excluded_result(world, name, mutate):
    result = build(world, include_flagged=False)
    kp.validated_result(result)
    tampered = copy.deepcopy(result)
    mutate(tampered)
    with pytest.raises(kp.ResultInvalid):
        kp.validated_result(tampered)


def test_validated_result_rejects_non_objects_floats_and_deep_nesting(world):
    for bad in (None, [], "x", {"schema": "kinase_precedents@1"}):
        with pytest.raises(kp.ResultInvalid):
            kp.validated_result(bad)
    result = build(world)
    result["counts"]["chains"] = 5.0
    with pytest.raises(kp.ResultInvalid):
        kp.validated_result(result)
    deep: list = []
    for _ in range(100000):
        deep = [deep]
    for path in (["limitations"], ["targets", 0, "records", 0, "record", "effects"], ["bibliography", "90000001"]):
        result = build(world)
        _set(result, path, deep)
        with pytest.raises(kp.ResultInvalid):
            kp.validated_result(result)
    assert issubclass(kp.ResultInvalid, ValueError)


# ------------------------------------------------------------------------------------------- module boundary

SERVER_MODULES = [Path(kp.__file__), Path(K.__file__), Path(ps.__file__)]
BANNED_IMPORTS = {"socket", "urllib", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp", "subprocess",
                  "rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "prolif", "gemmi", "numpy"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(("." * node.level) + (node.module or ""))
            if node.level and not node.module:
                found.update("." + alias.name for alias in node.names)
    return found


@pytest.mark.parametrize("path", SERVER_MODULES, ids=lambda p: p.name)
def test_server_modules_never_network_spawn_or_load_chemistry(path):
    source = path.read_text()
    imported = _imports(path)
    assert not {name.lstrip(".").split(".")[0] for name in imported} & BANNED_IMPORTS
    assert {name.split(".")[0] for name in imported if not name.startswith(".")} - {"__future__"} <= set(
        sys.stdlib_module_names)
    for banned in ("raise_limits", "limit_approval", "kbase_kinase/", "../kbase", ".git", "request_science"):
        assert banned not in source


def test_linking_module_imports_only_its_own_family():
    local = {name for name in _imports(Path(kp.__file__)) if name.startswith(".")}
    assert local <= {".", ".precedent_constants", ".precedent_snapshots"}
    source = Path(kp.__file__).read_text()
    for other in ("reaction_snapshots", "reaction_knowledge", "reference_snapshots", "residue_numbering",
                  "jev_sends"):
        assert f"import {other}" not in source and f"from .{other}" not in source
