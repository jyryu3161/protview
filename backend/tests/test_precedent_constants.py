"""M27 closed sets, fixed sentences, kbase record format checks and shared manifest helpers (mw.precedent_constants).

Records are LABELLED SYNTHETIC (``precedent_fixture.make_*`` and the committed ``fixtures/precedent/t2`` files, see
SYNTHETIC-PROVENANCE-t2.md); no real kbase_kinase record, quote or bibliography fragment is read or committed.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import precedent_fixture as PF
import pytest

from mw import precedent_constants as K
from mw.core.handles import canonical_json as core_canonical_json

MODULE = Path(K.__file__)


def _rejects(func, *args):
    with pytest.raises(K.FormatError):
        func(*args)


# ------------------------------------------------------------------------------------------- module boundary

def test_constants_module_imports_only_the_standard_library_and_no_mw():
    source = MODULE.read_text()
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative (mw) import in the constants module"
            imported.add((node.module or "").split(".")[0])
    assert imported - {"__future__"} <= set(sys.stdlib_module_names)
    assert not imported & {"mw", "socket", "urllib", "http", "httpx", "requests", "ftplib", "ssl", "subprocess"}
    for banned in ("raise_limits", "limit_approval", "kbase_kinase/", "../kbase", ".git"):
        assert banned not in source


# ------------------------------------------------------------------------------------------- fixed values

def test_names_location_and_caps():
    assert (K.TOOL, K.KIND, K.SCHEMA, K.METHOD_VERSION) == (
        "link_kinase_precedents", "kinase_precedents", "kinase_precedents@1", "mw.kinase_precedents/v1")
    assert (K.SET_SCHEMA, K.POINTER_SCHEMA, K.IMPORTER_VERSION) == (
        "precedent_reference_set@1", "precedent_active@1", "precedent_import/1")
    assert (K.STATUS_SCHEMA, K.DETAIL_SCHEMA) == ("precedent_reference_status@1", "kinase_precedents_detail@1")
    assert K.RECORD_FORMAT == "kbase_record_minus_2_paths@1"
    assert K.REMOVED_PATHS == (("source", "parser"), ("checks", "cross_parser_numbers", "measurements"))
    assert K.ENV_VAR == "MW_PRECEDENT_REFERENCE_DIR"
    assert K.DEFAULT_DIR_PARTS == (".deps", "precedent_reference")
    assert K.DIST_FILE_NAMES == ("dist/moves.jsonl", "dist/moves_flagged.jsonl", "dist/references.jsonl")
    assert K.pubmed_file_name("2026-09-18") == "pubmed/2026-09-18/documents.jsonl"
    assert K.file_path("dist/moves.jsonl") == "files/dist/moves.jsonl"
    assert (K.KBASE_ORIGIN, K.BIBLIOGRAPHY_ORIGIN) == ("kbase_kinase processed dist",
                                                       "kbase_kinase processed ref/pubmed")
    assert K.CAPABILITY_SOURCES == ("kbase_dist", "kbase_pubmed") and K.DIST_LICENSE == "none-stated"
    mib = 1024 * 1024
    assert (K.MAX_RESULT_BYTES, K.MAX_UNRESOLVED_NAMES, K.MAX_QUERY_CHARS) == (mib, 100, 100)
    assert (K.PAGE_LIMIT_MIN, K.PAGE_LIMIT_MAX, K.RECORDS_PAGE_DEFAULT, K.LIST_PAGE_DEFAULT) == (1, 100, 25, 50)
    assert K.REPORT_MAX_LINES_PER_TARGET == 300 and K.MAX_QUOTE_WORDS == 25
    assert (K.MAX_FILE_BYTES, K.MAX_FILE_ROWS, K.MAX_DIST_MANIFEST_BYTES, K.MAX_REF_MANIFEST_BYTES) == (
        64 * mib, 100000, mib, 64 * mib)


def test_kbase_pins_are_the_three_spec_values():
    assert K.KBASE_PINS == {
        "schema_version": "1",
        "effect_rules_version": "1",
        "vocab_version": ("contact_class@1+goal@1+interaction@1+site@2+tactic@1+target_aliases@2:"
                          "024a47d5a62eab2a1ad1a52a0bb8f8e2740cbe3f8ad279bc6c62055c778cc11e"),
    }


def test_closed_sets_verbatim():
    assert K.SNAPSHOT_REASON_CODES == ("not_installed", "snapshot_invalid")
    assert set(K.SNAPSHOT_REASONS) == set(K.SNAPSHOT_REASON_CODES)
    assert all("scripts/import_precedent_snapshots.py" in text for text in K.SNAPSHOT_REASONS.values())
    assert K.FILE_SOURCES == ("moves", "moves_flagged")
    assert K.CHAIN_STATUSES == ("linked", "not_linked")
    assert K.CHAIN_REASONS == ("no_mapped_residues", "multiple_accessions")
    assert K.TARGET_STATUSES == ("precedents_found", "none_in_included_files", "not_in_kbase_references")
    assert K.ADMISSION_REASON_CODES == ("unknown_field", "numbering_map_invalid", "include_flagged_invalid",
                                        "chains_invalid", "chain_not_in_map")
    assert (K.RESULT_TOO_LARGE_REASON, K.RESULT_INVALID_REASON) == ("result_too_large", "result_invalid")
    assert K.FILTER_KEYS == ("file", "site", "goal", "tactic", "variant", "q")
    assert K.SORT_KEYS == ("move_id", "pmid", "year", "variant", "file")
    assert K.SORT_ORDERS == ("asc", "desc")
    assert K.RESOLUTION_BASES == ("gene", "klifs_gene_name", "klifs_name", "alias", "ambiguous", "unmapped", "absent",
                                  "name_token", "pubmed_title", "notation")
    assert K.TARGET_ROLES == ("on_target", "off_target", "not_applicable")
    assert K.DIRECTIONS == ("improved", "worsened", "unchanged", "unknown")
    assert K.DIRECTION_BASES == ("numeric", "text", "none")
    assert K.MAGNITUDE_BUCKETS == ("small", "moderate", "large", "unknown")
    assert K.CHECK_STATUSES == ("pass", "fail", "not_applicable", "lookup_failed")
    assert K.LOCATION_KINDS == ("table", "figure", "text")
    assert K.STRUCTURE_LINK_BASES == ("pdb_title", "paper_context", "sole_candidate")
    assert K.CHECK_NAMES == ("qualifier_consistency", "tag_vocab", "schema", "target_in_reference", "quote_in_source",
                             "cross_parser_numbers", "chembl_crosscheck", "pmid_exists", "structure_ref_exists",
                             "duplicate")
    assert K.MOVE_KEYS == ("review_status", "schema_version", "move_id", "source", "target", "structure_ref",
                           "structure_link_reason", "structure_ref_from", "structure_links", "interactions",
                           "observation", "change", "effects", "tradeoffs", "mutations", "tags", "proposed_tags",
                           "figures", "checks", "extraction", "content_hash")
    assert len(K.MOVE_KEYS) == 21
    assert K.EFFECT_KEYS == ("metric", "assay", "assay_context", "target_ref", "target_role", "before", "after",
                             "direction", "direction_basis", "magnitude_bucket", "comparable", "comparability_reason",
                             "fold_change", "chembl_crosscheck", "evidence")
    assert len(K.EFFECT_KEYS) == 15
    assert K.REFERENCE_KEYS == ("ref_id", "gene", "klifs_name", "uniprot", "group", "family", "coverage",
                                "content_hash", "review_status", "schema_version")


def test_vocabulary_in_spec_order():
    assert K.SITE_TERMS == ("bp_I_A", "bp_I_B", "bp_II_in", "bp_II_A_in", "bp_II_B_in", "bp_II_B", "bp_II_out",
                            "bp_III", "bp_IV", "bp_V", "fp_I", "fp_II", "front", "back", "gate", "allosteric_non_atp",
                            "myristoyl_pocket", "substrate_site", "solvent_exposed", "not_site_specific")
    assert K.GOAL_TERMS == ("potency", "selectivity", "mutant_coverage", "binding_kinetics", "solubility",
                            "permeability", "metabolic_stability", "oral_exposure", "cns_penetration",
                            "safety_offtarget", "chemical_stability", "synthetic_accessibility")
    assert K.TACTIC_TERMS == ("add_hydrophobic_bulk", "truncate_substituent", "vector_extension", "ring_fusion",
                              "scaffold_hop", "heteroatom_swap", "bioisostere_replacement", "halogen_substitution",
                              "hbond_engagement", "salt_bridge_engagement", "covalent_warhead",
                              "conformational_restriction", "macrocyclization", "stereochemistry_change",
                              "polar_group_add", "lipophilicity_reduction", "prodrug_masking", "degrader_conversion")
    assert (len(K.SITE_TERMS), len(K.GOAL_TERMS), len(K.TACTIC_TERMS)) == (20, 12, 18)
    assert K.TAG_AXES == {"site": K.SITE_TERMS, "goal": K.GOAL_TERMS, "tactic": K.TACTIC_TERMS}


def test_fixed_sentences_verbatim_and_in_order():
    assert K.STATEMENTS == {
        "KP1": "전례는 kbase_kinase가 논문에서 기계로 추출한 미검수 기록이며 ProtView가 계산하거나 판정한 것이 아니다.",
        "KP2": ("방향과 크기는 kbase 규칙 v1이 숫자 또는 본문에서 산출한 값이며 논문의 결론도 ProtView의 판정도 아니고, "
                "측정 변화마다 대상 역할(on_target·off_target·not_applicable)이 함께 있다."),
        "KP3": ("kbase 기계 검사는 kbase가 만들 때 한 결과를 그대로 보인 것이며 ProtView는 논문 원문과 대조하지 않았다. "
                "파일 이름(moves·moves_flagged)은 모든 검사의 통과 여부를 뜻하지 않는다."),
        "KP4": ("전례가 없다는 표시는 포함한 파일에 기록이 없다는 뜻이며 선행 연구가 없다는 뜻이 아니다. 포함하지 않은 "
                "파일의 전례와 표적이 해석되지 않은 전례는 이 결과에 연결하지 않았다."),
        "KP5": ("표적(UniProt)이 같은 전례만 연결했다. 다른 키나아제의 전례는 연결하지 않았고, 변이·리간드·구조와의 "
                "일치는 판단하지 않았다."),
        "KP6": "전례 개수와 목록 순서는 순위·추천·유망도·성공률을 뜻하지 않는다.",
        "KT1": "kbase_kinase 비공개 저장소 자료 · 이용 조건 명시 없음 · ChEMBL 유래 필드 포함 · 외부 공개 전 확인",
    }
    assert list(K.STATEMENTS) == ["KP1", "KP2", "KP3", "KP4", "KP5", "KP6", "KT1"]
    assert K.LIMITATIONS == tuple(K.STATEMENTS[k] for k in ("KP1", "KP2", "KP3", "KP4", "KP5", "KP6"))
    assert K.SCREEN_NOTES == {
        "UP1": ("원문 대조 안 함: ProtView에는 논문 원문이 없어 인용이 원문과 같은지 확인하지 않았다. "
                "'ProtView 무결성 확인'은 가져온 파일과 레코드의 해시, 인용 길이, 논문 쪽 위치 존재만 뜻한다."),
        "UP2": "moves_flagged 파일의 전례 N건은 포함하지 않았다.",
        "UP3": "변이 표기는 kbase 기록 그대로이며 이 구조의 서열과 대조하지 않았다.",
        "UP4": "PDB 언급은 kbase가 기록한 것(근거 수준 포함)이며 이 구조와의 일치를 판단하지 않았다.",
        "UP5": "표적이 해석되지 않은 전례 N건(세트 전체)이 있어 어느 체인에도 연결하지 못했다.",
    }
    assert list(K.SCREEN_NOTES) == ["UP1", "UP2", "UP3", "UP4", "UP5"]


def test_numbered_screen_notes_fill_n_with_an_integer_only():
    assert K.screen_note("UP2", 0) == "moves_flagged 파일의 전례 0건은 포함하지 않았다."
    assert K.screen_note("UP5", 396) == "표적이 해석되지 않은 전례 396건(세트 전체)이 있어 어느 체인에도 연결하지 못했다."
    assert K.screen_note("UP3") == K.SCREEN_NOTES["UP3"]
    for bad in (None, -1, True, 1.0, "3"):
        with pytest.raises(ValueError):
            K.screen_note("UP2", bad)
    with pytest.raises(ValueError):
        K.screen_note("UP3", 2)
    with pytest.raises(KeyError):
        K.screen_note("UP9", 1)


# ------------------------------------------------------------------------------------------- canonical JSON and hashes

def test_canonical_json_equals_the_core_formula_and_refuses_nan():
    obj = {"b": [1, 2.5, None, True], "a": "한글 ü", "c": {"z": 1, "y": "x"}}
    assert K.canonical_json(obj) == core_canonical_json(obj)
    assert K.canonical_json(obj) == '{"a":"한글 ü","b":[1,2.5,null,true],"c":{"y":"x","z":1}}'.encode()
    with pytest.raises(ValueError):
        K.canonical_json({"x": float("nan")})


def test_content_hash_is_sha256_of_canonical_json_without_the_top_level_hash():
    record = PF.make_move("MOVE-0042")
    body = {k: v for k, v in record.items() if k != "content_hash"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert record["content_hash"] == "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert K.content_hash(record) == record["content_hash"]
    assert K.content_hash(body) == record["content_hash"]  # the key may be absent
    nested = copy.deepcopy(record)
    nested["extraction"]["content_hash"] = "kept"  # only the TOP-LEVEL key is left out
    assert K.content_hash(nested) != record["content_hash"]
    assert K.hash_matches(record) and not K.hash_matches(nested)


def test_set_hash_and_file_record():
    assert K.set_hash_of(b"{}") == hashlib.sha256(b"{}").hexdigest()
    data = b'{"a": 1}\n{"b": 2}\n'
    assert K.file_record("dist/moves.jsonl", data) == {
        "name": "dist/moves.jsonl", "path": "files/dist/moves.jsonl", "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data), "rows": 2, "kbase_sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    assert K.file_record("dist/moves.jsonl", b"")["rows"] == 0
    _rejects(K.file_record, "dist/moves.jsonl", b'{"a": 1}')  # the last line needs its newline


def test_pointer_round_trip():
    raw = K.pointer_bytes("a" * 64)
    assert raw == b'{"schema":"precedent_active@1","set_hash":"' + b"a" * 64 + b'"}'
    assert K.validate_pointer(json.loads(raw)) == "a" * 64
    for bad in ({"schema": "reaction_active@1", "set_hash": "a" * 64}, {"schema": "precedent_active@1"},
                {"schema": "precedent_active@1", "set_hash": "A" * 64}, [], "x",
                {"schema": "precedent_active@1", "set_hash": "a" * 64, "extra": 1}):
        _rejects(K.validate_pointer, bad)


# ------------------------------------------------------------------------------------------- JSONL

def test_parse_jsonl_reads_kbase_style_lines():
    records = [PF.make_move("MOVE-0001"), PF.make_move("MOVE-0002")]
    assert K.parse_jsonl(PF.jsonl(records)) == records
    assert K.parse_jsonl(b"") == []


@pytest.mark.parametrize("data", [
    b'{"a": 1}',                       # last line without newline
    b'{"a": 1}\n\n',                   # blank line
    b'{"a": 1}\n[1]\n',                # not an object
    b'{"a": NaN}\n',                   # non-finite number
    b'{"a": 1, "a": 2}\n',             # duplicate key
    b'{"a": "\xff"}\n',                # not UTF-8
    b'{"a": 1}{"b": 2}\n',             # two values on one line
    b'\xef\xbb\xbf{"a": 1}\n',         # byte order mark
], ids=["no-final-newline", "blank-line", "not-object", "nan", "duplicate-key", "not-utf8", "two-values", "bom"])
def test_parse_jsonl_refuses_malformed_lines(data):
    _rejects(K.parse_jsonl, data)


def test_parse_jsonl_refuses_too_many_lines(monkeypatch):
    monkeypatch.setattr(K, "MAX_FILE_ROWS", 2)
    assert len(K.parse_jsonl(b"{}\n{}\n")) == 2
    _rejects(K.parse_jsonl, b"{}\n{}\n{}\n")


def test_parse_jsonl_refuses_deep_nesting():
    _rejects(K.parse_jsonl, b"[" * 100000 + b"\n")


# ------------------------------------------------------------------------------------------- move records

def test_valid_move_and_committed_t2_records_pass():
    K.validate_move(PF.make_move())
    records = PF.t2_records()
    for record in records["moves"] + records["moves_flagged"]:
        K.validate_move(record)
        assert K.hash_matches(record)
    for record in records["references"]:
        K.validate_reference(record)


def _move_with(path: str, value):
    record = PF.make_move()
    PF.set_path(record, path, value)
    return PF.rehash(record)


def _move_without(path: str):
    record = PF.make_move()
    parts = path.split(".")
    node = record
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    del node[parts[-1]]
    return PF.rehash(record)


MOVE_VIOLATIONS = [
    ("missing top key", lambda: _move_without("figures")),
    ("extra top key", lambda: PF.make_move(score=1)),
    ("missing content_hash", lambda: {k: v for k, v in PF.make_move().items() if k != "content_hash"}),
    ("content_hash format", lambda: PF.make_move() | {"content_hash": "md5:00"}),
    ("review_status reviewed", lambda: _move_with("review_status", "reviewed")),
    ("schema_version 2", lambda: _move_with("schema_version", 2)),
    ("schema_version string", lambda: _move_with("schema_version", "1")),
    ("schema_version bool", lambda: _move_with("schema_version", True)),
    ("move_id short", lambda: PF.make_move("MOVE-123")),
    ("move_id prefix", lambda: PF.make_move("move-0001")),
    ("move_id unicode digits", lambda: PF.make_move("MOVE-١٢٣٤")),
    ("move_id trailing newline", lambda: PF.make_move("MOVE-0001\n")),
    ("move_id int", lambda: _move_with("move_id", 1)),
    ("pmid int", lambda: _move_with("source.pmid", 90000001)),
    ("pmid letters", lambda: PF.make_move(pmid="PMID9")),
    ("pmid empty", lambda: PF.make_move(pmid="")),
    ("source missing locations", lambda: _move_without("source.locations")),
    ("locations empty", lambda: PF.make_move(locations=[])),
    ("location kind", lambda: PF.make_move(locations=[{"kind": "supplement", "page": 1}])),
    ("location page zero", lambda: PF.make_move(locations=[{"kind": "text", "page": 0}])),
    ("location page bool", lambda: PF.make_move(locations=[{"kind": "text", "page": True}])),
    ("location page missing", lambda: PF.make_move(locations=[{"kind": "text"}])),
    ("location page float", lambda: PF.make_move(locations=[{"kind": "text", "page": 2.0}])),
    ("target missing variant", lambda: _move_without("target.variant")),
    ("target missing candidates", lambda: _move_without("target.candidates")),
    ("target uniprot format", lambda: PF.make_move(uniprot="EGFR")),
    ("target resolution_basis", lambda: PF.make_move(resolution_basis="guessed")),
    ("target variant null", lambda: _move_with("target.variant", None)),
    ("target name int", lambda: _move_with("target.name_as_written", 7)),
    ("tags missing axis", lambda: _move_without("tags.tactic")),
    ("tags extra axis", lambda: _move_with("tags.mood", [])),
    ("site term unknown", lambda: PF.make_move(site=["bp_VI"])),
    ("goal term unknown", lambda: PF.make_move(goal=["efficacy"])),
    ("tactic term unknown", lambda: PF.make_move(tactic=["magic_methyl"])),
    ("tags not a list", lambda: _move_with("tags.site", "bp_I_A")),
    ("effects empty", lambda: PF.make_move(effects=[])),
    ("effect 14 keys", lambda: PF.make_move(effects=[{k: v for k, v in PF.default_effect().items()
                                                      if k != "fold_change"}])),
    ("effect target_role", lambda: PF.make_move(effects=[PF.default_effect(target_role="primary")])),
    ("effect direction", lambda: PF.make_move(effects=[PF.default_effect(direction="better")])),
    ("effect direction_basis", lambda: PF.make_move(effects=[PF.default_effect(direction_basis="model")])),
    ("effect magnitude", lambda: PF.make_move(effects=[PF.default_effect(magnitude_bucket="huge")])),
    ("effect not a dict", lambda: PF.make_move(effects=["improved"])),
    ("observation quote null", lambda: _move_with("observation.quote", None)),
    ("observation missing evidence", lambda: _move_without("observation.evidence")),
    ("tradeoff quote int", lambda: PF.make_move(tradeoffs=[{"text": "t", "quote": 3, "quote_truncated": False,
                                                            "evidence": None}])),
    ("tradeoff missing text", lambda: PF.make_move(tradeoffs=[{"quote": None, "quote_truncated": False,
                                                               "evidence": None}])),
    ("check missing", lambda: _move_without("checks.duplicate")),
    ("check status", lambda: _move_with("checks.schema.status", "passed")),
    ("check not a dict", lambda: _move_with("checks.schema", "pass")),
    ("structure link basis", lambda: PF.make_move(structure_links=[{"basis": "guess", "pdb_id": "0SYN"}])),
    ("extraction missing model", lambda: _move_without("extraction.model")),
    ("observation not a dict", lambda: _move_with("observation", "text")),
    ("not a dict", lambda: ["MOVE-0001"]),
]


@pytest.mark.parametrize("name, make", MOVE_VIOLATIONS, ids=[n for n, _ in MOVE_VIOLATIONS])
def test_move_format_violations_are_refused(name, make):
    _rejects(K.validate_move, make())


def test_unknown_nested_keys_are_kept_and_valid():
    record = PF.make_move()
    record["source"]["extra_source_field"] = {"synthetic": [1, 2]}
    record["effects"][0]["extra_effect_field"] = "kept"
    record["checks"]["duplicate"]["candidate_ids"] = ["MOVE-0002"]
    record["checks"]["extra_check"] = {"status": "pass"}  # beyond the ten names: kept, not refused
    record["target"]["resolution_evidence"] = {"synthetic": True}
    PF.rehash(record)
    K.validate_move(record)
    parsed = K.parse_jsonl(PF.jsonl([record]))
    assert parsed == [record]
    assert parsed[0]["source"]["extra_source_field"] == {"synthetic": [1, 2]}
    assert parsed[0]["checks"]["extra_check"] == {"status": "pass"}
    assert K.hash_matches(parsed[0])


def test_every_closed_value_is_accepted():
    for basis in K.RESOLUTION_BASES:
        K.validate_move(PF.make_move(resolution_basis=basis, uniprot=None if basis == "unmapped" else "P0SYN1"))
    for kind in K.LOCATION_KINDS:
        K.validate_move(PF.make_move(locations=[{"kind": kind, "page": 1}]))
    for basis in K.STRUCTURE_LINK_BASES:
        K.validate_move(PF.make_move(structure_links=[{"basis": basis}]))
    for status in K.CHECK_STATUSES:
        record = PF.make_move()
        record["checks"]["schema"]["status"] = status
        K.validate_move(PF.rehash(record))
    K.validate_move(PF.make_move(site=K.SITE_TERMS, goal=K.GOAL_TERMS, tactic=K.TACTIC_TERMS))
    K.validate_move(PF.make_move(site=(), goal=(), tactic=()))
    K.validate_move(PF.make_move(effects=[PF.default_effect(target_role=r, direction=d, direction_basis=b,
                                                            magnitude_bucket=m)
                                          for r in K.TARGET_ROLES for d in K.DIRECTIONS
                                          for b in K.DIRECTION_BASES for m in K.MAGNITUDE_BUCKETS]))
    K.validate_move(PF.make_move(uniprot=None, name_as_written=None, resolution_basis="absent"))


# ------------------------------------------------------------------------------------------- reference records

REFERENCE_VIOLATIONS = [
    ("missing coverage", lambda r: r.pop("coverage")),
    ("missing content_hash key", lambda r: r.pop("content_hash")),
    ("review_status", lambda r: r.update(review_status="reviewed")),
    ("schema_version", lambda r: r.update(schema_version=2)),
    ("uniprot format", lambda r: r.update(uniprot="P0SYN")),
    ("uniprot null", lambda r: r.update(uniprot=None)),
    ("ref_id empty", lambda r: r.update(ref_id="")),
    ("ref_id int", lambda r: r.update(ref_id=5)),
    ("content_hash format", lambda r: r.update(content_hash="sha256:xyz")),
]


@pytest.mark.parametrize("name, mutate", REFERENCE_VIOLATIONS, ids=[n for n, _ in REFERENCE_VIOLATIONS])
def test_reference_format_violations_are_refused(name, mutate):
    record = PF.make_reference("REF-SYN-0001", "P0SYN1")
    K.validate_reference(record)
    mutate(record)
    _rejects(K.validate_reference, record)


def test_reference_without_hash_is_valid():
    K.validate_reference(PF.make_reference("REF-SYN-0001", "P0SYN1", hashed=False))


# ------------------------------------------------------------------------------------------- the three dist files

def _dist(moves, flagged, references):
    return K.validate_dist_files(PF.jsonl(moves), PF.jsonl(flagged), PF.jsonl(references))


def test_validate_dist_files_returns_records_and_verification():
    t2 = PF.t2_bytes()
    dist = K.validate_dist_files(t2["moves"], t2["moves_flagged"], t2["references"])
    records = PF.t2_records()
    assert dist.moves == records["moves"] and dist.moves_flagged == records["moves_flagged"]
    assert dist.references == records["references"]
    assert dist.verification == {"records_hash_verified": {"moves": len(records["moves"]),
                                                           "moves_flagged": len(records["moves_flagged"]),
                                                           "references": len(records["references"])},
                                 "references_without_hash": 0}
    unhashed = _dist([PF.make_move()], [], [PF.make_reference("REF-SYN-0001", "P0SYN1", hashed=False),
                                            PF.make_reference("REF-SYN-0002", "P0SYN1")])
    assert unhashed.verification == {"records_hash_verified": {"moves": 1, "moves_flagged": 0, "references": 1},
                                     "references_without_hash": 1}


def test_move_id_must_be_unique_across_both_files():
    _rejects(_dist, [PF.make_move("MOVE-0001")], [PF.make_move("MOVE-0001")], [])
    _rejects(_dist, [PF.make_move("MOVE-0001"), PF.make_move("MOVE-0001")], [], [])
    _dist([PF.make_move("MOVE-0001")], [PF.make_move("MOVE-0002")], [])


def test_record_hash_mismatch_is_refused_in_every_file():
    bad = PF.make_move("MOVE-0003")
    bad["observation"]["text"] = "SYNTHETIC edited after hashing"
    _rejects(_dist, [bad], [], [])
    _rejects(_dist, [], [bad], [])
    ref = PF.make_reference("REF-SYN-0001", "P0SYN1")
    ref["family"] = "edited after hashing"
    _rejects(_dist, [], [], [ref])


def test_ref_id_must_be_unique_and_one_accession_may_have_several_references():
    _rejects(_dist, [], [], [PF.make_reference("REF-SYN-0001", "P0SYN1"), PF.make_reference("REF-SYN-0001", "Q0SYN2")])
    _dist([], [], [PF.make_reference("REF-SYN-0001", "P0SYN1"), PF.make_reference("REF-SYN-0002", "P0SYN1")])


def test_invalid_record_in_a_file_is_refused():
    _rejects(_dist, [PF.make_move(site=["bp_VI"])], [], [])
    _rejects(_dist, [], [PF.make_move(review_status="reviewed")], [])


# ------------------------------------------------------------------------------------------- pubmed rows

def test_parse_pubmed_and_bibliography_entries():
    rows = [PF.make_pubmed_row("90000001", doi="10.0000/synthetic.1", pmc="PMC0000001"),
            PF.make_pubmed_row("90000003", status="error"),
            PF.make_pubmed_row("90000004", data_pmid="90000099"),
            {"id": "90000006", "status": "ok", "data": {"pmid": "90000006", "title": "SYNTHETIC no other keys"}},
            {"id": "90000007", "status": "ok", "data": {"doi": None, "journal": None, "pmc": None, "pmid": "90000007",
                                                         "title": None, "year": 2020}}]
    parsed = K.parse_pubmed(PF.jsonl(rows))
    assert parsed == rows
    assert K.bibliography_entries(parsed) == {
        "90000001": {"title": "합성 SYNTHETIC fixture title 90000001", "journal": "Synthetic Fixture Journal",
                     "year": "2020", "doi": "10.0000/synthetic.1", "pmc": "PMC0000001"}}


@pytest.mark.parametrize("rows", [
    [{"id": 90000001, "status": "ok", "data": {}}],
    [{"id": "PMID1", "status": "ok", "data": {}}],
    [{"status": "ok", "data": {}}],
    [{"id": "1", "status": "ok"}, {"id": "1", "status": "ok"}],
    [[1]],
], ids=["int-id", "letters", "no-id", "duplicate", "not-object"])
def test_parse_pubmed_refuses_bad_ids(rows):
    _rejects(K.parse_pubmed, PF.jsonl(rows))


# ------------------------------------------------------------------------------------------- kbase pins

def test_check_kbase_pins():
    K.check_kbase_pins(dict(K.KBASE_PINS) | {"source_snapshots": [], "other": 1})
    for key in K.KBASE_PINS:
        _rejects(K.check_kbase_pins, dict(K.KBASE_PINS) | {key: K.KBASE_PINS[key] + "x"})
        _rejects(K.check_kbase_pins, {k: v for k, v in K.KBASE_PINS.items() if k != key})
    _rejects(K.check_kbase_pins, dict(K.KBASE_PINS) | {"schema_version": 1})  # a number is not the string pin
    _rejects(K.check_kbase_pins, None)


# ------------------------------------------------------------------------------------------- set manifest

def _manifest(tmp_path, **kwargs):
    set_hash = PF.build_set(tmp_path / "ref", activate_set=False, **kwargs)
    return json.loads((tmp_path / "ref" / "sets" / set_hash / "manifest.json").read_bytes())


def test_fixture_manifest_is_valid_canonical_and_hashed(tmp_path):
    set_hash = PF.build_set(tmp_path / "ref")
    raw = (tmp_path / "ref" / "sets" / set_hash / "manifest.json").read_bytes()
    assert K.set_hash_of(raw) == set_hash
    manifest = json.loads(raw)
    assert K.canonical_json(manifest) == raw == K.manifest_bytes(manifest)
    K.validate_manifest(manifest)
    assert [f["name"] for f in manifest["files"]] == list(K.DIST_FILE_NAMES)
    assert manifest["bibliography"]["file"]["name"] == "pubmed/2026-10-01/documents.jsonl"
    assert json.loads((tmp_path / "ref" / "active.json").read_bytes()) == {"schema": K.POINTER_SCHEMA,
                                                                           "set_hash": set_hash}


def _drop(key):
    return lambda m: m.pop(key)


MANIFEST_VIOLATIONS = [
    ("extra top key", lambda m: m.update(request_log=None)),
    ("missing verification", _drop("verification")),
    ("schema", lambda m: m.update(schema="precedent_reference_set@2")),
    ("importer version", lambda m: m.update(importer_version="precedent_import/2")),
    ("imported_at microseconds", lambda m: m.update(imported_at="2026-10-10T00:00:00.123Z")),
    ("imported_at offset", lambda m: m.update(imported_at="2026-10-10T09:00:00+09:00")),
    ("kbase extra key", lambda m: m["kbase"].update(license="x")),
    ("kbase missing key", lambda m: m["kbase"].pop("dirty")),
    ("pin schema_version", lambda m: m["kbase"].update(schema_version="2")),
    ("pin effect_rules_version", lambda m: m["kbase"].update(effect_rules_version="2")),
    ("pin vocab_version", lambda m: m["kbase"].update(vocab_version="site@3")),
    ("commit short", lambda m: m["kbase"].update(commit="77354f9")),
    ("commit null", lambda m: m["kbase"].update(commit=None)),
    ("commit upper", lambda m: m["kbase"].update(commit="C0DE" * 10)),
    ("dist commit without date", lambda m: m["kbase"].update(dist_commit_date=None)),
    ("date without dist commit", lambda m: m["kbase"].update(dist_commit=None)),
    ("dist commit date format", lambda m: m["kbase"].update(dist_commit_date="2026-10-01")),
    ("dirty string", lambda m: m["kbase"].update(dirty="false")),
    ("kb_version number", lambda m: m["kbase"].update(kb_version=1)),
    ("source_snapshots string", lambda m: m["kbase"].update(source_snapshots="SNAP")),
    ("kbase origin", lambda m: m["kbase"].update(origin="kbase")),
    ("files two", lambda m: m["files"].pop()),
    ("files order", lambda m: m["files"].reverse()),
    ("file path", lambda m: m["files"][0].update(path="dist/moves.jsonl")),
    ("file name", lambda m: m["files"][1].update(name="dist/moves_flagged.json")),
    ("file sha upper", lambda m: m["files"][0].update(sha256=m["files"][0]["sha256"].upper())),
    ("file kbase sha differs", lambda m: m["files"][0].update(kbase_sha256="sha256:" + "0" * 64)),
    ("file kbase sha bare", lambda m: m["files"][0].update(kbase_sha256=m["files"][0]["sha256"])),
    ("file missing kbase sha", lambda m: m["files"][2].pop("kbase_sha256")),
    ("file bytes negative", lambda m: m["files"][0].update(bytes=-1)),
    ("file bytes above cap", lambda m: m["files"][0].update(bytes=64 * 1024 * 1024 + 1)),
    ("file rows above cap", lambda m: m["files"][0].update(rows=100001)),
    ("file rows bool", lambda m: m["files"][0].update(rows=True)),
    ("bibliography extra", lambda m: m["bibliography"].update(rows=4)),
    ("bibliography origin", lambda m: m["bibliography"].update(origin="pubmed")),
    ("bibliography date", lambda m: m["bibliography"].update(date="2026-10-02")),
    ("bibliography date format", lambda m: m["bibliography"].update(date="20261001")),
    ("bibliography snapshot empty", lambda m: m["bibliography"].update(snapshot_id="")),
    ("bibliography license null", lambda m: m["bibliography"].update(license=None)),
    ("bibliography file path", lambda m: m["bibliography"]["file"].update(path="pubmed/2026-10-01/documents.jsonl")),
    ("bibliography file kbase sha", lambda m: m["bibliography"]["file"].pop("kbase_sha256")),
    ("verification extra", lambda m: m["verification"].update(note="x")),
    ("verification moves count", lambda m: m["verification"]["records_hash_verified"].update(moves=0)),
    ("verification flagged count", lambda m: m["verification"]["records_hash_verified"].update(moves_flagged=1)),
    ("verification references sum", lambda m: m["verification"].update(references_without_hash=1)),
    ("verification key", lambda m: m["verification"]["records_hash_verified"].update(structures=1)),
]


@pytest.mark.parametrize("name, patch", MANIFEST_VIOLATIONS, ids=[n for n, _ in MANIFEST_VIOLATIONS])
def test_manifest_violations_are_refused(tmp_path, name, patch):
    manifest = _manifest(tmp_path)
    K.validate_manifest(manifest)
    patch(manifest)
    _rejects(K.validate_manifest, manifest)
    _rejects(K.manifest_bytes, manifest)


def test_manifest_accepts_null_dist_commit_and_a_dirty_checkout(tmp_path):
    kbase = dict(PF.KBASE) | {"dist_commit": None, "dist_commit_date": None, "dirty": True}
    K.validate_manifest(_manifest(tmp_path, kbase=kbase))
    kbase = dict(PF.KBASE) | {"dist_commit_date": "2026-09-21T00:05:28Z"}
    K.validate_manifest(_manifest(tmp_path / "z", kbase=kbase))


def test_manifest_validators_are_exposed_for_the_result_check():
    K.validate_kbase_block(dict(PF.KBASE))
    _rejects(K.validate_kbase_block, dict(PF.KBASE) | {"vocab_version": "x"})
    entry = K.file_record("dist/moves.jsonl", b"{}\n")
    K.validate_file_entry(entry, "dist/moves.jsonl", kbase_sha256=True)
    K.validate_file_entry({k: v for k, v in entry.items() if k != "kbase_sha256"}, "dist/moves.jsonl",
                          kbase_sha256=False)
    _rejects(K.validate_file_entry, entry, "dist/moves.jsonl", False)
    _rejects(K.validate_file_entry, entry, "dist/references.jsonl", True)


# ------------------------------------------------------------------------------------------- helpers

def test_move_number_and_accession_pattern():
    assert K.move_number("MOVE-0042") == 42 and K.move_number("MOVE-10000") == 10000
    assert sorted(["MOVE-10000", "MOVE-9999", "MOVE-0101"], key=K.move_number) == ["MOVE-0101", "MOVE-9999",
                                                                                   "MOVE-10000"]
    assert K.is_accession("P00533") and K.is_accession("A0A024R161") and K.is_accession("P0SYN1")
    assert not K.is_accession("p00533") and not K.is_accession("P00533-2") and not K.is_accession(None)
