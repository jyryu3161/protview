"""M26 closed sets, fixed sentences, processed-row formats and shared manifest helpers (mw.reaction_knowledge_constants).

Rows used here are the LABELLED SYNTHETIC fixtures of ``fixtures/reaction/t2/`` (see SYNTHETIC-PROVENANCE-t2.md); no
real M-CSA / UniProt / Rhea response is read or committed.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest
import reaction_fixture as RF

from mw import mutation_constants as MC
from mw import reaction_knowledge_constants as K
from mw.core.handles import canonical_json as core_canonical_json

MODULE = Path(K.__file__)


# ------------------------------------------------------------------------------------------- module boundary

def test_constants_module_imports_only_the_standard_library():
    tree = ast.parse(MODULE.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative (mw) import in the constants module"
            imported.add((node.module or "").split(".")[0])
    assert imported - {"__future__"} <= set(sys.stdlib_module_names)
    assert not imported & {"mw", "socket", "urllib", "http", "httpx", "requests", "ftplib", "ssl"}


def test_constants_module_loads_by_file_path_without_the_mw_package():
    spec = importlib.util.spec_from_file_location("reaction_constants_by_path", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.STATEMENTS == K.STATEMENTS and module.SOURCE_FORMATS == K.SOURCE_FORMATS
    assert module.canonical_json({"b": 1, "a": "é"}) == core_canonical_json({"b": 1, "a": "é"})


def test_no_limit_raising_words_in_the_module():
    text = MODULE.read_text()
    assert "raise_limits" not in text and "limit_approval" not in text


# ------------------------------------------------------------------------------------------- closed sets

def test_closed_sets_and_their_order():
    assert K.SOURCES == ("mcsa", "uniprot_function", "rhea")
    assert K.SOURCE_FILES == {"mcsa": ("entries.jsonl",), "uniprot_function": ("entries.jsonl",),
                              "rhea": ("reactions.jsonl",)}
    assert K.SITE_TYPES == ("Active site", "Binding site", "Site")
    assert K.SKIP_REASONS == ("obsolete", "merged", "demerged", "not_found", "fetch_failed")
    assert K.M15_KINASE_LIST == ("present", "absent", "disabled")
    assert K.ALLOWED_HOSTS == ("www.ebi.ac.uk", "rest.uniprot.org", "www.rhea-db.org")
    assert K.MCSA_STATUSES == ("checked", "not_checked")
    assert K.MCSA_NOT_CHECKED_REASON == "pdb_id_not_given"
    assert K.COVERAGE == ("covered", "chain_not_listed", "pdb_not_in_snapshot")
    assert K.ROW_STATUSES == ("matched", "unmatched", "conflict")
    assert K.UNMATCHED_REASONS == ("non_standard_code", "no_author_number", "residue_not_in_structure",
                                   "ambiguous_residue_number", "insertion_code_present")
    assert K.CONFLICT_REASONS == ("residue_name_differs", "mcsa_rows_disagree")
    assert K.UNIPROT_STATUSES == ("checked", "not_checked", "not_available")
    assert K.UNIPROT_REASONS == ("accession_not_given", "accession_not_in_snapshot", "accession_skipped_at_import")
    assert K.LINKED_VIA == ("numbering_map",)
    assert K.LINK_STATUSES == ("mapped", "not_in_map")
    assert K.LINK_REASONS == ("numbering_map_not_given", "chain_not_in_map", "map_accession_differs")
    assert K.REACTIONS_STATUSES == ("checked", "not_checked")
    assert K.REACTIONS_NOT_CHECKED_REASON == "no_source"
    assert K.ACCESSION_SOURCES == ("user", "numbering_map")
    assert K.CHAIN_FLAGS == ("accession_differs_from_mcsa",)
    assert K.M20_UNCOVERED_COVERAGE == ("chain_not_listed", "pdb_not_in_snapshot", "not_checked",
                                        "not_in_annotation")
    assert K.SNAPSHOT_REASON_CODES == ("not_installed", "snapshot_invalid")
    assert set(K.SNAPSHOT_REASONS) == set(K.SNAPSHOT_REASON_CODES)
    assert all("scripts/import_reaction_references.py" in text for text in K.SNAPSHOT_REASONS.values())


def test_admission_reason_codes_are_the_nine_of_spec_5_2_in_order():
    assert K.ADMISSION_REASON_CODES == (
        "unknown_field", "structure_invalid", "pdb_id_invalid", "chains_invalid", "chain_not_found",
        "accession_invalid", "numbering_map_invalid", "structure_mismatch", "map_pdb_mismatch")
    assert K.RESULT_INVALID_REASON == "result_invalid"


def test_names_caps_and_defaults():
    assert (K.TOOL, K.KIND, K.SCHEMA) == ("link_reaction_knowledge", "reaction_knowledge", "reaction_knowledge@1")
    assert K.METHOD_VERSION == "mw.reaction_knowledge/v1"
    assert (K.SET_SCHEMA, K.POINTER_SCHEMA, K.IMPORTER_VERSION) == (
        "reaction_reference_set@1", "reaction_active@1", "reaction_import/1")
    assert K.STATUS_SCHEMA == "reaction_reference_status@1"
    assert K.ENV_VAR == "MW_REACTION_REFERENCE_DIR" and K.DEFAULT_DIR_PARTS == (".deps", "reaction_reference")
    assert (K.LICENSE, K.ORIGIN) == ("CC-BY-4.0", "public server import")
    assert K.LICENSE_URL == "https://creativecommons.org/licenses/by/4.0/"
    assert (K.REQUEST_LOG_NAME, K.REQUEST_LOG_PATH) == ("request_log.jsonl", "files/request_log.jsonl")
    assert (K.MAX_ACCESSIONS, K.MAX_SKIPPED) == (20000, 50)
    assert (K.MAX_RESULT_BYTES, K.MAX_LINKS, K.MAX_M20_CATALYTIC_LIST) == (1024 * 1024, 2000, 400)
    assert K.RESIDUE_FIELDS == MC.IDENTITY_FIELDS


def test_fixed_sentences_verbatim_and_in_order():
    assert list(K.STATEMENTS) == ["RK1", "RK2", "RK3", "RK4", "RK5", "RK6"]
    assert K.STATEMENTS["RK1"] == ("촉매 잔기·부위·반응은 참조 스냅샷(M-CSA·UniProt·Rhea)에 적힌 값이며 ProtView가 "
                                   "계산하거나 판정한 것이 아니다.")
    assert K.STATEMENTS["RK2"] == ("대응됨은 M-CSA가 적은 PDB·체인·번호와 이 구조의 잔기 이름이 모두 같다는 뜻이며 "
                                   "잔기의 역할이나 활성을 뜻하지 않는다.")
    assert K.STATEMENTS["RK3"] == ("대응 없음·충돌·검사하지 않음은 이 스냅샷과 방법으로 확실하지 않다는 뜻이며 촉매 "
                                   "잔기가 없다는 뜻이 아니다.")
    assert K.STATEMENTS["RK4"] == ("UniProt 부위는 번호 대응이 있는 체인에서만 구조 잔기에 연결했고 그 밖에는 단백질 "
                                   "서열 위치로만 보여 준다.")
    assert K.STATEMENTS["RK5"] == "반응 정보는 효소 활성·속도·특이성이나 반응 메커니즘이 유지된다는 뜻이 아니다."
    assert K.STATEMENTS["RK6"] == "M-CSA·UniProt·Rhea 자료는 CC BY 4.0이며 출처·스냅샷 날짜는 아래에 있다."
    assert K.LIMITATIONS == tuple(K.STATEMENTS[k] for k in ("RK1", "RK2", "RK3", "RK4", "RK5"))
    assert list(K.SCREEN_NOTES) == ["UK1", "UK2", "UK3", "UK4"]
    assert K.SCREEN_NOTES["UK1"] == ("촉매 잔기·부위·반응은 M-CSA·UniProt·Rhea가 적은 참조값이며 ProtView가 계산한 "
                                     "값이 아니다. 가져온 스냅샷 날짜 기준이다.")
    assert K.SCREEN_NOTES["UK2"] == ("촉매 잔기 검사 안 함: 이 집합은 M-CSA 촉매 잔기 주석 없이 만들었거나 일부 체인만 "
                                     "검사했다.")
    assert K.SCREEN_NOTES["UK3"] == "UniProt 부위 정보는 지식 탭에서만 보이며 보호에 쓰지 않음."
    assert K.SCREEN_NOTES["UK4"] == "이 체인을 M-CSA가 다루지 않았다는 것은 촉매 잔기가 없다는 뜻이 아니다."


@pytest.mark.parametrize("value, ok", [
    ("P36507", True), ("Q0SYN1", True), ("O14965", True), ("A0A023GPI8", True), ("A2BC19", True),
    ("p36507", False), ("P3650", False), ("P365071", False), ("Q0SYNZ", False), ("", False), (" P36507", False),
    ("P36507 ", False), ("P36507-2", False), ("A0A023GPI8X", False), (1, False), (None, False),
])
def test_uniprot_accession_pattern(value, ok):
    assert K.is_accession(value) is ok


def test_split_accessions_and_entry_accessions():
    assert K.split_accessions("Q0SYN2, P0SYN3") == ["Q0SYN2", "P0SYN3"]
    assert K.split_accessions("Q0SYN1") == ["Q0SYN1"]
    rows = RF.synthetic_rows()["mcsa"]
    assert K.entry_accessions(rows[0]) == ["Q0SYN1"]
    assert K.entry_accessions(rows[1]) == ["P0SYN3", "Q0SYN2", "Q0SYN4"]  # "" residue_sequences ids are not accessions


# ------------------------------------------------------------------------------------------- canonical JSON

CANONICAL_BATTERY = [
    {}, [], "", 0, -1, 2 ** 63, True, False, None, 1.5, -0.0, 1e-300, 3.141592653589793,
    {"b": 1, "a": 2, "c": {"z": [3, 2, {"y": None, "x": True}], "é": "é"}},
    {"한국어": "촉매 잔기", "emoji": "☃", "ctrl": "line\nbreak\ttab\"quote\\", "nul": "\u0000"},
    [{"k": [[], {}, [None]]}, "RHEA:9000010", "ChEBI:CHEBI:990005"],
    {"10": 1, "9": 2, "a": 3, "B": 4, "_": 5},
]


@pytest.mark.parametrize("obj", CANONICAL_BATTERY)
def test_canonical_json_equals_core_handles(obj):
    assert K.canonical_json(obj) == core_canonical_json(obj)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, {"a": [math.nan]}])
def test_canonical_json_rejects_nan_like_core(bad):
    with pytest.raises(ValueError):
        K.canonical_json(bad)
    with pytest.raises(ValueError):
        core_canonical_json(bad)


def test_jsonl_line_set_hash_and_digest():
    assert K.jsonl_line({"b": 1, "a": "é"}) == '{"a":"é","b":1}\n'.encode()
    assert K.set_hash_of(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert K.raw_sha256_digest([]) == K.sha256_hex(b"")
    assert K.raw_sha256_digest(["a" * 64, "b" * 64]) == K.sha256_hex(("a" * 64 + "\n" + "b" * 64).encode())
    with pytest.raises(ValueError):
        K.raw_sha256_digest(["A" * 64])


# ------------------------------------------------------------------------------------------- processed rows

def test_synthetic_fixture_rows_pass_the_format_and_round_trip():
    rows = RF.synthetic_rows()
    for source in K.SOURCES:
        data = K.encode_jsonl(source, rows[source])
        assert data == b"".join(K.jsonl_line(r) for r in rows[source])
        assert K.decode_jsonl(source, data) == rows[source]
        assert K.encode_jsonl(source, rows[source]) == data  # same rows -> same bytes


def _mcsa():
    return copy.deepcopy(RF.synthetic_rows()["mcsa"][0])


def _uniprot():
    return copy.deepcopy(RF.synthetic_rows()["uniprot_function"][1])


def _rhea():
    return copy.deepcopy(RF.synthetic_rows()["rhea"][2])


def _set(obj, path, value):
    *head, last = path
    for key in head:
        obj = obj[key]
    obj[last] = value


def _del(obj, path):
    *head, last = path
    for key in head:
        obj = obj[key]
    del obj[last]


MCSA_BAD = [
    ("extra top field", lambda r: r.update(main_annotation="")),
    ("missing field", lambda r: _del(r, ["all_ecs"])),
    ("mechanisms kept", lambda r: _set(r, ["reaction", "mechanisms"], [])),
    ("id is bool", lambda r: _set(r, ["mcsa_id"], True)),
    ("id is float", lambda r: _set(r, ["mcsa_id"], 101.0)),
    ("id zero", lambda r: _set(r, ["mcsa_id"], 0)),
    ("name null", lambda r: _set(r, ["enzyme_name"], None)),
    ("accession list bad", lambda r: _set(r, ["reference_uniprot_id"], "Q0SYN1,,P0SYN3")),
    ("accession empty", lambda r: _set(r, ["reference_uniprot_id"], "")),
    ("ecs unsorted", lambda r: _set(r, ["all_ecs"], ["9.9.9.2", "9.9.9.1"])),
    ("ecs not list", lambda r: _set(r, ["all_ecs"], "9.99.1.1")),
    ("compound count kept", lambda r: _set(r, ["reaction", "compounds", 0, "count"], 1)),
    ("assembly empty string", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "assembly"], "")),
    ("auth_resid string", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "auth_resid"], "10")),
    ("is_reference int", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "is_reference"], 1)),
    ("pdb uppercase", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "pdb_id"], "0SY1")),
    ("pdb too long", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "pdb_id"], "0sy12")),
    ("chain empty", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "chain_name"], "")),
    ("code empty", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "code"], "")),
    ("domain kept", lambda r: _set(r, ["residues", 0, "residue_chains", 0, "domain_name"], "d")),
    ("sequence resid kept", lambda r: _set(r, ["residues", 0, "residue_sequences", 0, "resid"], 5)),
    ("sequence accession bad", lambda r: _set(r, ["residues", 0, "residue_sequences", 0, "uniprot_id"], "x")),
    ("roles summary null", lambda r: _set(r, ["residues", 0, "roles_summary"], None)),
    ("role extra", lambda r: _set(r, ["residues", 0, "roles", 0, "extra"], "")),
    ("residue mcsa_id kept", lambda r: _set(r, ["residues", 0, "mcsa_id"], 101)),
    ("residues not list", lambda r: _set(r, ["residues"], {})),
]


@pytest.mark.parametrize("name, mutate", MCSA_BAD, ids=[n for n, _ in MCSA_BAD])
def test_mcsa_row_format_rejects(name, mutate):
    row = _mcsa()
    K.validate_row("mcsa", row)
    mutate(row)
    with pytest.raises(K.FormatError):
        K.validate_row("mcsa", row)


def test_mcsa_row_allows_null_ec_and_null_numbers_and_empty_strings():
    row = _mcsa()
    row["reaction"]["ec"] = None
    row["residues"][0]["residue_chains"][0].update(resid=None, auth_resid=None, assembly=None)
    row["residues"][0].update(roles_summary="", function_location_abv="", ptm="", roles=[])
    row["residues"][0]["residue_sequences"][0]["uniprot_id"] = ""
    K.validate_row("mcsa", row)


UNIPROT_BAD = [
    ("extra", lambda r: r.update(entryType="x")),
    ("accession bad", lambda r: _set(r, ["accession"], "q0syn1")),
    ("length zero", lambda r: _set(r, ["sequence_length"], 0)),
    ("ec duplicate", lambda r: _set(r, ["ec_numbers"], ["9.99.1.1", "9.99.1.1"])),
    ("ec unsorted", lambda r: _set(r, ["ec_numbers"], ["9.99.1.3", "9.99.1.1"])),
    ("site type", lambda r: _set(r, ["features", 0, "type"], "Mutagenesis")),
    ("site type case", lambda r: _set(r, ["features", 0, "type"], "active site")),
    ("start after end", lambda r: _set(r, ["features", 1, "start"], 15)),
    ("start zero", lambda r: (_set(r, ["features", 0, "start"], 0), _set(r, ["features", 0, "end"], 0))),
    ("start string", lambda r: _set(r, ["features", 0, "start"], "10")),
    ("description null", lambda r: _set(r, ["features", 0, "description"], None)),
    ("evidences kept", lambda r: _set(r, ["features", 0, "evidences"], [])),
    ("rhea comp id", lambda r: _set(r, ["catalytic_activities", 0, "rhea_ids"], ["RHEA-COMP:1"])),
    ("rhea unsorted", lambda r: _set(r, ["catalytic_activities", 0, "rhea_ids"], ["RHEA:9000010", "RHEA:10000"])),
    ("chebi bad", lambda r: _set(r, ["catalytic_activities", 0, "chebi_ids"], ["ChEBI:CHEBI:1"])),
    ("activity extra", lambda r: _set(r, ["catalytic_activities", 0, "physiologicalReactions"], [])),
    ("entry name empty", lambda r: _set(r, ["entry_name"], "")),
]


@pytest.mark.parametrize("name, mutate", UNIPROT_BAD, ids=[n for n, _ in UNIPROT_BAD])
def test_uniprot_row_format_rejects(name, mutate):
    row = _uniprot()
    K.validate_row("uniprot_function", row)
    mutate(row)
    with pytest.raises(K.FormatError):
        K.validate_row("uniprot_function", row)


RHEA_BAD = [
    ("id bad", lambda r: _set(r, ["rhea_id"], "9000010")),
    ("ec prefix kept", lambda r: _set(r, ["ec_numbers"], ["EC:9.99.1.1"])),
    ("participant chebi", lambda r: _set(r, ["participants", 0, "chebi_id"], "990001")),
    ("participant extra", lambda r: _set(r, ["participants", 0, "x"], 1)),
    ("equation empty", lambda r: _set(r, ["equation"], "")),
]


@pytest.mark.parametrize("name, mutate", RHEA_BAD, ids=[n for n, _ in RHEA_BAD])
def test_rhea_row_format_rejects(name, mutate):
    row = _rhea()
    K.validate_row("rhea", row)
    mutate(row)
    with pytest.raises(K.FormatError):
        K.validate_row("rhea", row)


def test_unknown_source_is_refused():
    with pytest.raises(K.FormatError):
        K.validate_row("cofactor", {})
    with pytest.raises(K.FormatError):
        K.validate_row("mcsa", [])


def test_jsonl_order_rules():
    rows = RF.synthetic_rows()
    mcsa = rows["mcsa"]
    with pytest.raises(K.FormatError):
        K.encode_jsonl("mcsa", [mcsa[1], mcsa[0]])
    with pytest.raises(K.FormatError):
        K.encode_jsonl("mcsa", [mcsa[0], mcsa[0]])
    uniprot = rows["uniprot_function"]
    with pytest.raises(K.FormatError):
        K.encode_jsonl("uniprot_function", [uniprot[1], uniprot[0]])
    rhea = rows["rhea"]
    assert [r["rhea_id"] for r in rhea][:2] == ["RHEA:800", "RHEA:10000"]  # integer order, not string order
    with pytest.raises(K.FormatError):
        K.encode_jsonl("rhea", sorted(rhea, key=lambda r: r["rhea_id"]))


@pytest.mark.parametrize("data", [
    b'{"a":1}',                         # no final newline
    b'{ "mcsa_id": 1 }\n',               # not canonical
    b'\n',                              # empty line
    b'\xff\n',                          # not UTF-8
    b'NaN\n',
])
def test_decode_jsonl_rejects_non_canonical_bytes(data):
    with pytest.raises(K.FormatError):
        K.decode_jsonl("mcsa", data)


def test_decode_jsonl_rejects_a_non_canonical_but_valid_row():
    row = RF.synthetic_rows()["rhea"][0]
    pretty = json.dumps(row, ensure_ascii=True).encode() + b"\n"
    assert K.decode_jsonl("rhea", K.jsonl_line(row)) == [row]
    with pytest.raises(K.FormatError):
        K.decode_jsonl("rhea", pretty)
    assert K.decode_jsonl("rhea", b"") == []


def test_request_log_row_format():
    good = {"seq": 1, "source": "mcsa", "method": "GET", "url": "https://www.ebi.ac.uk/x", "status": 200,
            "bytes": 10, "sha256": "a" * 64}
    K.validate_request_log_row(good)
    for bad in ({**good, "headers": {}}, {**good, "method": "POST"}, {**good, "seq": 0}, {**good, "source": "x"},
                {**good, "url": "http://www.ebi.ac.uk/x"}, {**good, "sha256": "A" * 64}, {**good, "status": "200"}):
        with pytest.raises(K.FormatError):
            K.validate_request_log_row(bad)


# ------------------------------------------------------------------------------------------- manifest

def _manifest(tmp_path):
    set_hash = RF.build_set(tmp_path / "ref")
    raw = (tmp_path / "ref" / "sets" / set_hash / "manifest.json").read_bytes()
    assert K.set_hash_of(raw) == set_hash and K.canonical_json(json.loads(raw)) == raw
    return json.loads(raw)


def test_fixture_manifest_is_valid_and_shaped_as_spec_3_2(tmp_path):
    manifest = _manifest(tmp_path)
    K.validate_manifest(manifest)
    assert list(manifest) == sorted(["schema", "imported_at", "importer_version", "sources", "requested_accessions",
                                     "skipped_accessions", "request_log"])
    assert [s["source"] for s in manifest["sources"]] == list(K.SOURCES)
    assert manifest["sources"][0]["files"][0]["path"] == "files/mcsa/entries.jsonl"
    assert manifest["request_log"]["path"] == "files/request_log.jsonl"


def _patched(manifest, mutate):
    manifest = copy.deepcopy(manifest)
    mutate(manifest)
    return manifest


MANIFEST_BAD = [
    ("extra key", lambda m: m.update(kbase_repo={})),
    ("missing key", lambda m: m.pop("request_log")),
    ("schema", lambda m: m.update(schema="reaction_reference_set@2")),
    ("imported_at micro", lambda m: m.update(imported_at="2026-10-08T00:00:00.000Z")),
    ("importer version", lambda m: m.update(importer_version="reaction_import/2")),
    ("sources order", lambda m: m["sources"].reverse()),
    ("sources two", lambda m: m["sources"].pop()),
    ("source extra key", lambda m: m["sources"][0].update(url_count=1)),
    ("license", lambda m: m["sources"][0].update(license="CC0")),
    ("license url", lambda m: m["sources"][0].update(license_url="http://example.org")),
    ("origin", lambda m: m["sources"][0].update(origin="kbase_kinase processed snapshot")),
    ("date", lambda m: m["sources"][0].update(date="2026-10-8")),
    ("raw count", lambda m: m["sources"][0].update(raw_response_count=-1)),
    ("raw digest", lambda m: m["sources"][0].update(raw_sha256_digest="x")),
    ("file name", lambda m: m["sources"][0]["files"][0].update(name="curated.jsonl")),
    ("file path escapes", lambda m: m["sources"][0]["files"][0].update(path="files/mcsa/../../../x")),
    ("file path other source", lambda m: m["sources"][0]["files"][0].update(path="files/rhea/entries.jsonl")),
    ("file sha", lambda m: m["sources"][0]["files"][0].update(sha256="0" * 63)),
    ("file bytes bool", lambda m: m["sources"][0]["files"][0].update(bytes=True)),
    ("file extra", lambda m: m["sources"][0]["files"][0].update(use="product")),
    ("two files", lambda m: m["sources"][0]["files"].append(dict(m["sources"][0]["files"][0]))),
    ("request log path", lambda m: m["request_log"].update(path="request_log.jsonl")),
    ("request log name", lambda m: m["request_log"].update(name="log.jsonl")),
    ("requested extra", lambda m: m["requested_accessions"].update(extra=1)),
    ("kinase list value", lambda m: m["requested_accessions"].update(m15_kinase_list="missing")),
    ("absent with hash", lambda m: m["requested_accessions"].update(
        m15_kinase_list="absent", from_m15_kinase_set={"set_hash": "e" * 64, "count": 2})),
    ("present without hash", lambda m: m["requested_accessions"].update(
        from_m15_kinase_set={"set_hash": None, "count": 2})),
    ("user named unsorted", lambda m: m["requested_accessions"].update(user_named=["Q0SYN2", "P0SYN3"])),
    ("user named bad", lambda m: m["requested_accessions"].update(user_named=["nope"])),
    ("dropped overlaps", lambda m: m["requested_accessions"].update(user_named=["P0SYN3"],
                                                                     dropped_previous_user_named=["P0SYN3"])),
    ("union below part", lambda m: m["requested_accessions"].update(union_count=1)),
    ("skipped unsorted", lambda m: m["skipped_accessions"].reverse()),
    ("skipped reason", lambda m: m["skipped_accessions"][0].update(reason="deleted")),
    ("skipped extra", lambda m: m["skipped_accessions"][0].update(primary_accession=None)),
    ("merged two targets", lambda m: m["skipped_accessions"][1].update(target_accessions=["Q0SYN8", "Q0SYN9"])),
    ("obsolete with target", lambda m: m["skipped_accessions"][2].update(target_accessions=["Q0SYN9"])),
    ("demerged four", lambda m: m["skipped_accessions"][0].update(
        target_accessions=["P0SYN1", "P0SYN2", "P0SYN4", "P0SYN5"])),
    ("user named skipped", lambda m: m["requested_accessions"].update(user_named=["Q0SYN7"])),
]


@pytest.mark.parametrize("name, mutate", MANIFEST_BAD, ids=[n for n, _ in MANIFEST_BAD])
def test_manifest_validation_rejects(tmp_path, name, mutate):
    manifest = _manifest(tmp_path)
    with pytest.raises(ValueError):
        K.validate_manifest(_patched(manifest, mutate))


def test_manifest_absent_and_disabled_kinase_lists(tmp_path):
    manifest = _manifest(tmp_path)
    for value in ("absent", "disabled"):
        ok = _patched(manifest, lambda m, v=value: m["requested_accessions"].update(
            m15_kinase_list=v, from_m15_kinase_set={"set_hash": None, "count": 0}, union_count=5))
        K.validate_manifest(ok)


def test_pointer_helpers():
    raw = K.pointer_bytes("a" * 64)
    assert raw == b'{"schema":"reaction_active@1","set_hash":"' + b"a" * 64 + b'"}'
    assert K.validate_pointer(json.loads(raw)) == "a" * 64
    for bad in ({"schema": "reference_active@1", "set_hash": "a" * 64}, {"schema": K.POINTER_SCHEMA},
                {"schema": K.POINTER_SCHEMA, "set_hash": "A" * 64},
                {"schema": K.POINTER_SCHEMA, "set_hash": "a" * 64, "x": 1}, []):
        with pytest.raises(ValueError):
            K.validate_pointer(bad)


def test_file_record_shape():
    data = b'{"a":1}\n{"a":2}\n'
    assert K.file_record("files/mcsa/entries.jsonl", "entries.jsonl", data) == {
        "name": "entries.jsonl", "path": "files/mcsa/entries.jsonl", "sha256": K.sha256_hex(data),
        "bytes": len(data), "rows": 2}
