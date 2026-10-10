"""M27 read API and capability (spec 6): ``/precedent_reference/status``, ``/runs/{rid}/kinase_precedents`` (list),
``/runs/{rid}/kinase_precedents/{handle}`` (detail: target, filters, search, sort, page, facets, bibliography,
active set), ``/capabilities`` ``methods.kinase_precedents`` and the tool over ``POST /runs/{rid}/commands``.

Every precedent reference folder is a LABELLED SYNTHETIC set written by ``precedent_fixture.build_set`` under a
temporary ``MW_PRECEDENT_REFERENCE_DIR``: the T2 records, or the "designed" records below (made-up move IDs, PMIDs,
titles and tokens such as ``zzobstext`` placed in one field each so that filters, the twelve search fields and the
five sort keys can be told apart). Numbering maps are the SYNTHETIC T2 dicts stored for the uploaded public 1MQ4
structure. Every read is checked to write no event, start no tool or job, read the event log at most once and make no
socket connection. No real kbase_kinase data, no network.
"""
from __future__ import annotations

import copy
import shutil
import socket

import precedent_fixture as PF
import pytest
from fastapi.testclient import TestClient
from test_kinase_precedents_tool import CIF_1MQ4, ORACLE, _store_map

from mw import kinase_precedents as kp
from mw import kinase_precedents_reads as reads
from mw import precedent_constants as K
from mw import precedent_snapshots as ps

TOOL = K.TOOL
STATUS_KEYS = {"schema", "installed", "reason", "set_hash", "imported_at", "importer_version", "kbase", "files",
               "bibliography", "set_summary"}
ITEM_KEYS = {"handle", "numbering_map_handle", "pdb_id", "include_flagged", "chain_count", "linked_chain_count",
             "target_count", "records", "null_result", "set_hash", "active"}
DETAIL_KEYS = {"schema", "handle", "method_version", "numbering_map", "structure", "pdb_id", "include_flagged",
               "record_format", "precedent_set", "chains", "targets_overview", "set_summary", "counts", "null_result",
               "limitations", "page", "facets", "records", "bibliography", "active_set"}
STORED_KEYS = DETAIL_KEYS - {"schema", "handle", "targets_overview", "page", "facets", "records", "bibliography",
                             "active_set"}


@pytest.fixture
def refdir(tmp_path, monkeypatch):
    root = tmp_path / "precedent_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    yield root
    ps._VERIFIED.clear()
    kp.clear_index_cache()


@pytest.fixture
def client(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    yield TestClient(appmod.app, base_url="http://127.0.0.1")
    appmod.RUNS.clear()


def _app():
    import mw.api.app as appmod
    return appmod


def _new_run(client, dry_run=False) -> str:
    return client.post("/runs", json={"goal": "kinase precedent reads", "dry_run": dry_run}).json()["run_id"]


def _load(client, rid, path=CIF_1MQ4) -> str:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": path.name}, content=path.read_bytes(),
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                         "args": {"source": upload.json()["upload_id"]}})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["handle"]["handle"]


def _link(client, rid, nmap, chains=None, include_flagged=False):
    return client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "numbering_map": nmap, "chains": chains, "include_flagged": include_flagged}})


def _ok(response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _events(rid):
    return list(_app()._run(rid).events.read())


def _store(rid):
    return _app()._run(rid).store


class _NoSockets:
    """Fault injection: any socket connection during a read fails the test."""

    def __init__(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("a read must not open a network connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def world(client, refdir):
    set_hash = PF.build_set(refdir)
    rid = _new_run(client)
    structure = _load(client, rid)
    run = _app()._run(rid)
    maps = {name: _store_map(run, structure, name) for name in ("main", "refs_only", "unlinked")}
    full = _ok(_link(client, rid, maps["main"]))
    empty = _ok(_link(client, rid, maps["unlinked"]))
    return {"rid": rid, "structure": structure, "maps": maps, "full": full, "empty": empty, "set_hash": set_hash,
            "root": refdir}


# ------------------------------------------------------------------------------------------- designed records

def _designed_records():
    """LABELLED SYNTHETIC records of target P0SYN1 for the filter / search / sort cases (one token per field)."""
    def move(move_id, **fields):
        return PF.make_move(move_id, uniprot="P0SYN1", **fields)

    trade = {"quote_truncated": False, "evidence": {"synthetic": "zzdecoytradeevidence"}}
    gene_decoy = {"gene": "ZZDECOYGENE", "uniprot": "P0SYN1", "name_as_written": "SYN-KINASE",
                  "resolution_basis": "gene", "candidates": [], "variant": "not_reported"}
    moves = [
        move("MOVE-00001", pmid="900", variant="A10V", site=["bp_I_A", "bp_I_A"], goal=["potency"],
             tactic=["scaffold_hop"], observation_text="SYNTHETIC zzobstext observation",
             effects=[PF.default_effect(assay="zzdecoyassay")]),
        move("MOVE-0010", pmid="1000", variant="not_reported", site=["bp_I_B"], goal=["selectivity", "potency"],
             tactic=["ring_fusion"],
             change={"description": "SYNTHETIC zzchangedesc", "from_compound": "SYN-a", "to_compound": "SYN-b",
                     "smiles_from": "zzdecoysmiles", "smiles_to": None},
             extraction={"model": "zzdecoymodel", "provider": "synthetic", "prompt_version": "fixture-1",
                         "run_at": "2026-10-01T00:00:00Z"}),
        move("MOVE-9999", pmid="1000", variant="T20M", site=["bp_I_A", "back"], goal=["solubility"],
             tactic=["scaffold_hop", "ring_fusion"], structure_ref="zzdecoystructref",
             change={"description": "SYNTHETIC change", "from_compound": "SYN-c", "to_compound": "SYN zztocpd",
                     "smiles_from": None, "smiles_to": None},
             tradeoffs=[{"text": "SYNTHETIC tradeoff", "quote": "SYNTHETIC zztradequote", **trade}]),
        move("MOVE-10000", pmid="777", variant="not_reported", site=[], goal=[], tactic=[],
             name_as_written="SYN zznamewritten"),
    ]
    flagged = [
        move("MOVE-0001", pmid="60", site=["front"], goal=["potency"], tactic=[], quote="SYNTHETIC zzobsquote words",
             target=gene_decoy),
        move("MOVE-0100", pmid="50", variant="A10V", site=["front"], goal=["potency"], tactic=[],
             change={"description": "SYNTHETIC change", "from_compound": "SYN zzfromcpd", "to_compound": "SYN-d",
                     "smiles_from": None, "smiles_to": None},
             tradeoffs=[{"text": "SYNTHETIC zztradetext", "quote": None, **trade}]),
    ]
    pubmed = [PF.make_pubmed_row("900", year="2019", journal="zzdecoyjournal"),
              PF.make_pubmed_row("60", year=None),
              PF.make_pubmed_row("1000", year="2021", title="SYNTHETIC zzbibtitle"),
              PF.make_pubmed_row("50", year="n.d.")]                     # PMID 777 has no bibliography row
    references = [PF.make_reference("REF-SYN-0001", "P0SYN1"), PF.make_reference("REF-SYN-0002", "Q0SYN2")]
    return {"moves": moves, "moves_flagged": flagged, "pubmed": pubmed, "references": references}


@pytest.fixture
def designed(client, refdir):
    set_hash = PF.build_set(refdir, **_designed_records())
    rid = _new_run(client)
    run = _app()._run(rid)
    nmap = _store_map(run, _load(client, rid), "main")
    flagged = _ok(_link(client, rid, nmap, ["A", "B"], True))
    excluded = _ok(_link(client, rid, nmap, ["A", "B"], False))
    return {"rid": rid, "map": nmap, "flagged": flagged, "excluded": excluded, "set_hash": set_hash, "root": refdir}


def _detail(client, rid, handle, params=None):
    return client.get(f"/runs/{rid}/kinase_precedents/{handle}", params=params)


def _ids(client, designed, params):
    response = _detail(client, designed["rid"], designed["flagged"], params)
    assert response.status_code == 200, response.text
    return [item["record"]["move_id"] for item in response.json()["records"]]


# ------------------------------------------------------------------------------------------- capability

def test_capability_shape_in_every_state_and_templates_unaffected(client, refdir):
    methods = client.get("/capabilities").json()["methods"]
    missing = methods["kinase_precedents"]
    assert set(missing) == set(methods["reaction_knowledge"])   # the same five keys as M26
    assert missing == {"available": False, "reason_code": "not_installed",
                       "reason": K.SNAPSHOT_REASONS["not_installed"], "set_hash": None, "sources": []}
    assert "scripts/import_precedent_snapshots.py" in missing["reason"]
    templates = methods["analysis_workflows"]["templates"]
    set_hash = PF.build_set(refdir)
    ready = client.get("/capabilities").json()["methods"]
    assert ready["kinase_precedents"] == {
        "available": True, "reason_code": None, "reason": None, "set_hash": set_hash,
        "sources": [{"source": "kbase_dist", "date": "2026-10-01", "license": "none-stated",
                     "origin": "kbase_kinase processed dist", "rows": 7 + 6 + 6},
                    {"source": "kbase_pubmed", "date": PF.PUBMED_DATE, "license": "synthetic-fixture-license",
                     "origin": "kbase_kinase processed ref/pubmed", "rows": 5}]}
    assert ready["analysis_workflows"]["templates"] == templates
    moves = next(refdir.glob("sets/*/files/dist/moves.jsonl"))
    moves.write_bytes(moves.read_bytes() + b"\n")
    invalid = client.get("/capabilities").json()["methods"]["kinase_precedents"]
    assert invalid == {"available": False, "reason_code": "snapshot_invalid",
                       "reason": K.SNAPSHOT_REASONS["snapshot_invalid"], "set_hash": None, "sources": []}


def test_capability_decodes_the_records_not_only_the_file_hashes(client, refdir):
    """SYNTHETIC set whose files match the manifest but whose record leaves the format (review_status changed)."""
    PF.build_set(refdir, moves=[PF.make_move("MOVE-0001", review_status="reviewed")], moves_flagged=[])
    assert ps.capability()["available"] is True                  # hash level only
    cap = client.get("/capabilities").json()["methods"]["kinase_precedents"]
    assert cap == {"available": False, "reason_code": "snapshot_invalid",
                   "reason": K.SNAPSHOT_REASONS["snapshot_invalid"], "set_hash": None, "sources": []}


def test_tool_is_listed_at_l2(client):
    names = {tool["name"] for tool in client.get("/tools", params={"levels": "L2"}).json()}
    assert TOOL in names


# ------------------------------------------------------------------------------------------- status

def test_status_unavailable_is_the_reason_only(client, refdir, monkeypatch):
    _NoSockets(monkeypatch)
    response = client.get("/precedent_reference/status")
    assert response.status_code == 200
    assert response.json() == {**dict.fromkeys(STATUS_KEYS), "schema": "precedent_reference_status@1",
                               "installed": False, "reason": "not_installed"}
    PF.build_set(refdir, moves=[PF.make_move("MOVE-0001", review_status="reviewed")], moves_flagged=[])
    assert client.get("/precedent_reference/status").json() == {
        **dict.fromkeys(STATUS_KEYS), "schema": K.STATUS_SCHEMA, "installed": False, "reason": "snapshot_invalid"}
    assert client.get("/precedent_reference/status", params={"x": 1}).status_code == 422


def test_status_installed(client, refdir, monkeypatch):
    set_hash = PF.build_set(refdir)
    _NoSockets(monkeypatch)
    body = client.get("/precedent_reference/status").json()
    manifest = ps.pin_active_set().manifest
    assert set(body) == STATUS_KEYS
    assert (body["schema"], body["installed"], body["reason"], body["set_hash"]) == (K.STATUS_SCHEMA, True, None,
                                                                                    set_hash)
    assert (body["imported_at"], body["importer_version"]) == (PF.IMPORTED_AT, "precedent_import/1")
    assert body["kbase"] == manifest["kbase"] == PF.KBASE
    assert body["files"] == [{"name": "dist/moves.jsonl", "rows": 7, "bytes": manifest["files"][0]["bytes"]},
                             {"name": "dist/moves_flagged.jsonl", "rows": 6, "bytes": manifest["files"][1]["bytes"]},
                             {"name": "dist/references.jsonl", "rows": 6, "bytes": manifest["files"][2]["bytes"]}]
    assert body["bibliography"] == {"snapshot_id": PF.BIBLIOGRAPHY["snapshot_id"], "date": PF.PUBMED_DATE,
                                    "license": "synthetic-fixture-license", "rows": 5}
    assert body["set_summary"] == ORACLE["main_all_excluded"]["result"]["set_summary"]   # independent oracle (T2)


# ------------------------------------------------------------------------------------------- list

def test_list_items_newest_first(client, world, monkeypatch):
    _NoSockets(monkeypatch)
    body = client.get(f"/runs/{world['rid']}/kinase_precedents").json()
    assert set(body) == {"items", "total"} and body["total"] == 2
    empty, full = body["items"]
    assert set(empty) == ITEM_KEYS and set(full) == ITEM_KEYS
    assert full == {"handle": world["full"], "numbering_map_handle": world["maps"]["main"], "pdb_id": "0SY5",
                    "include_flagged": False, "chain_count": 5, "linked_chain_count": 3, "target_count": 2,
                    "records": {"moves": 4, "moves_flagged": None}, "null_result": False,
                    "set_hash": world["set_hash"], "active": True}
    assert empty == {"handle": world["empty"], "numbering_map_handle": world["maps"]["unlinked"], "pdb_id": "0SY6",
                     "include_flagged": False, "chain_count": 1, "linked_chain_count": 0, "target_count": 0,
                     "records": {"moves": 0, "moves_flagged": None}, "null_result": True,
                     "set_hash": world["set_hash"], "active": True}
    paged = client.get(f"/runs/{world['rid']}/kinase_precedents", params={"limit": 1, "offset": 1}).json()
    assert paged == {"items": [full], "total": 2}


def test_list_default_limit_is_50(client, world):
    assert (reads.LIST_LIMIT_DEFAULT, reads.LIST_LIMIT_MAX) == (50, 100)
    run = _app()._run(world["rid"])
    for i in range(49):   # 49 more distinct results (one SYNTHETIC map copy each) -> 51 in all
        nmap = _store_map(run, world["structure"], "unlinked", f" copy {i}")
        run.call(TOOL, {"numbering_map": nmap, "chains": None, "include_flagged": False})
    body = client.get(f"/runs/{world['rid']}/kinase_precedents").json()
    assert body["total"] == 51 and len(body["items"]) == 50
    rest = client.get(f"/runs/{world['rid']}/kinase_precedents", params={"offset": 50}).json()["items"]
    assert [item["handle"] for item in rest] == [world["full"]]
    assert len(client.get(f"/runs/{world['rid']}/kinase_precedents", params={"limit": 100}).json()["items"]) == 51


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}, {"other": 1}])
def test_list_parameter_bounds(client, world, params):
    assert client.get(f"/runs/{world['rid']}/kinase_precedents", params=params).status_code == 422


def test_active_flag_follows_the_current_set(client, world):
    url = f"/runs/{world['rid']}/kinase_precedents"
    PF.build_set(world["root"], imported_at="2026-10-10T00:00:03Z")
    assert [item["active"] for item in client.get(url).json()["items"]] == [False, False]
    PF.activate(world["root"], world["set_hash"])
    assert [item["active"] for item in client.get(url).json()["items"]] == [True, True]
    shutil.rmtree(world["root"])
    assert [item["active"] for item in client.get(url).json()["items"]] == [False, False]


def test_list_of_a_run_without_results(client, refdir):
    rid = _new_run(client)
    assert client.get(f"/runs/{rid}/kinase_precedents").json() == {"items": [], "total": 0}


# ------------------------------------------------------------------------------------------- detail: shape

def test_detail_default_is_the_stored_object_plus_the_first_target_page(client, world, monkeypatch):
    _NoSockets(monkeypatch)
    content = _store(world["rid"]).load(world["full"])
    response = _detail(client, world["rid"], world["full"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DETAIL_KEYS
    assert {k: body[k] for k in STORED_KEYS} == {k: content[k] for k in STORED_KEYS}
    assert (body["schema"], body["handle"]) == ("kinase_precedents_detail@1", world["full"])
    assert body["targets_overview"] == [
        {k: t[k] for k in ("accession", "chains", "status", "references", "excluded_flagged", "counts")}
        for t in content["targets"]]
    assert [t["accession"] for t in body["targets_overview"]] == ["P0SYN1", "Q0SYN2"]
    first = content["targets"][0]
    assert body["page"] == {"target": "P0SYN1", "total": 4, "filtered_total": 4, "offset": 0, "limit": 25}
    assert body["records"] == first["records"]
    assert [i["record"]["move_id"] for i in body["records"]] == ["MOVE-0001", "MOVE-0007", "MOVE-9999", "MOVE-10000"]
    pmids = sorted({i["record"]["source"]["pmid"] for i in first["records"]})
    assert list(body["bibliography"]) == pmids
    assert body["bibliography"] == {pmid: content["bibliography"][pmid] for pmid in pmids}
    assert body["bibliography"]["90000002"] is None                     # no bibliography: null, never dropped
    assert body["active_set"] == {"set_hash": world["set_hash"], "same": True}


def test_detail_target_selection(client, world):
    rid, handle = world["rid"], world["full"]
    content = _store(rid).load(handle)
    body = _detail(client, rid, handle, {"target": "Q0SYN2"}).json()
    assert body["page"] == {"target": "Q0SYN2", "total": 0, "filtered_total": 0, "offset": 0, "limit": 25}
    assert body["records"] == [] and body["bibliography"] == {}
    assert body["facets"] == {"file": [], "site": [], "goal": [], "tactic": [], "variant": []}
    assert body["targets_overview"][1]["status"] == "none_in_included_files"
    assert body["targets_overview"][1]["excluded_flagged"] == 2 == content["targets"][1]["excluded_flagged"]
    for bad in ({"target": "P0SYN6"}, {"target": "p0syn1"}, {"target": ""}):
        response = _detail(client, rid, handle, bad)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid"


def test_detail_of_a_result_without_targets(client, world):
    rid, handle = world["rid"], world["empty"]
    body = _detail(client, rid, handle).json()
    assert body["page"] == {"target": None, "total": None, "filtered_total": None, "offset": 0, "limit": 25}
    assert body["records"] == [] and body["facets"] is None and body["bibliography"] == {}
    assert body["targets_overview"] == [] and body["null_result"] is True
    assert _detail(client, rid, handle, {"target": "P0SYN1"}).status_code == 422
    assert _detail(client, rid, handle, {"site": "bp_I_A", "q": "x", "sort": "year"}).status_code == 200
    assert _detail(client, rid, handle, {"site": "nope"}).status_code == 422


# ------------------------------------------------------------------------------------------- detail: facets

def test_facets_count_the_whole_target_before_filters(client, designed):
    body = _detail(client, designed["rid"], designed["flagged"], {"site": "front", "q": "zzobsquote"}).json()
    assert body["page"]["total"] == 6 and body["page"]["filtered_total"] == 1
    assert body["facets"] == {
        "file": [{"value": "moves", "count": 4}, {"value": "moves_flagged", "count": 2}],
        "site": [{"value": "back", "count": 1}, {"value": "bp_I_A", "count": 2}, {"value": "bp_I_B", "count": 1},
                 {"value": "front", "count": 2}],     # MOVE-00001 repeats bp_I_A: counted once
        "goal": [{"value": "potency", "count": 4}, {"value": "selectivity", "count": 1},
                 {"value": "solubility", "count": 1}],
        "tactic": [{"value": "ring_fusion", "count": 2}, {"value": "scaffold_hop", "count": 2}],
        "variant": [{"value": "A10V", "count": 2}, {"value": "T20M", "count": 1}, {"value": "not_reported", "count": 3}]}
    excluded = _detail(client, designed["rid"], designed["excluded"]).json()
    assert excluded["facets"]["file"] == [{"value": "moves", "count": 4}]   # only the included records
    assert excluded["page"]["total"] == 4
    assert excluded["targets_overview"][0]["excluded_flagged"] == 2
    assert excluded["targets_overview"][0]["counts"]["moves_flagged"] is None


# ------------------------------------------------------------------------------------------- detail: filters

FILTERS = [
    ({}, ["MOVE-00001", "MOVE-0001", "MOVE-0010", "MOVE-0100", "MOVE-9999", "MOVE-10000"]),
    ({"file": "moves_flagged"}, ["MOVE-0001", "MOVE-0100"]),
    ({"file": "moves"}, ["MOVE-00001", "MOVE-0010", "MOVE-9999", "MOVE-10000"]),
    ({"site": "bp_I_A"}, ["MOVE-00001", "MOVE-9999"]),
    ({"site": ["bp_I_A", "front"]}, ["MOVE-00001", "MOVE-0001", "MOVE-0100", "MOVE-9999"]),        # OR in a key
    ({"site": "front", "goal": "potency"}, ["MOVE-0001", "MOVE-0100"]),                              # AND across
    ({"site": "bp_I_A", "goal": "potency"}, ["MOVE-00001"]),
    ({"goal": ["selectivity", "solubility"]}, ["MOVE-0010", "MOVE-9999"]),
    ({"tactic": "ring_fusion"}, ["MOVE-0010", "MOVE-9999"]),
    ({"file": "moves", "site": "bp_I_A", "tactic": "scaffold_hop"}, ["MOVE-00001", "MOVE-9999"]),
    ({"variant": "A10V"}, ["MOVE-00001", "MOVE-0100"]),
    ({"variant": "a10v"}, []),                                                                       # exact match
    ({"variant": "not_reported", "file": "moves_flagged"}, ["MOVE-0001"]),
    ({"site": "gate"}, []),                       # in the vocabulary, absent from this target: an empty page
    ({"tactic": "macrocyclization", "goal": "potency"}, []),
]


@pytest.mark.parametrize("params, expected", FILTERS, ids=[str(p) for p, _ in FILTERS])
def test_filters_or_within_a_key_and_across_keys(client, designed, params, expected):
    response = _detail(client, designed["rid"], designed["flagged"], params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [i["record"]["move_id"] for i in body["records"]] == expected
    assert body["page"]["filtered_total"] == len(expected) and body["page"]["total"] == 6


SEARCH = [
    ("MOVE-0100", ["MOVE-0100"]),                       # record.move_id
    ("777", ["MOVE-10000"]),                            # record.source.pmid
    ("zznamewritten", ["MOVE-10000"]),                  # record.target.name_as_written
    ("T20M", ["MOVE-9999"]),                            # record.target.variant
    ("zzobstext", ["MOVE-00001"]),                      # record.observation.text
    ("zzobsquote", ["MOVE-0001"]),                      # record.observation.quote
    ("zzchangedesc", ["MOVE-0010"]),                    # record.change.description
    ("zzfromcpd", ["MOVE-0100"]),                       # record.change.from_compound
    ("zztocpd", ["MOVE-9999"]),                         # record.change.to_compound
    ("zztradetext", ["MOVE-0100"]),                     # record.tradeoffs[].text
    ("zztradequote", ["MOVE-9999"]),                    # record.tradeoffs[].quote
    ("zzbibtitle", ["MOVE-0010", "MOVE-9999"]),         # bibliography title (both records cite PMID 1000)
    ("ZZOBSTEXT", ["MOVE-00001"]),                      # case-insensitive
    ("  zzobstext  ", ["MOVE-00001"]),                  # surrounding spaces dropped
    ("zzdecoyassay", []), ("zzdecoymodel", []), ("zzdecoyjournal", []), ("ZZDECOYGENE", []),
    ("zzdecoysmiles", []), ("zzdecoystructref", []), ("zzdecoytradeevidence", []),   # fields outside the twelve
]


@pytest.mark.parametrize("q, expected", SEARCH, ids=[q.strip() for q, _ in SEARCH])
def test_search_reads_exactly_the_twelve_fields(client, designed, q, expected):
    assert _ids(client, designed, {"q": q}) == expected


def test_search_field_list_is_the_spec_list():
    assert reads.SEARCH_FIELDS == (
        "record.move_id", "record.source.pmid", "record.target.name_as_written", "record.target.variant",
        "record.observation.text", "record.observation.quote", "record.change.description",
        "record.change.from_compound", "record.change.to_compound", "record.tradeoffs[].text",
        "record.tradeoffs[].quote", "bibliography.title")
    assert len(SEARCH[:12]) == len(reads.SEARCH_FIELDS)   # one SEARCH case above per field, in this order


def test_search_combines_with_filters(client, designed):
    assert _ids(client, designed, {"q": "zzbibtitle", "site": "back"}) == ["MOVE-9999"]
    assert _ids(client, designed, {"q": "SYNTHETIC", "file": "moves_flagged"}) == ["MOVE-0001", "MOVE-0100"]


# ------------------------------------------------------------------------------------------- detail: sort

SORTS = [
    ({}, ["MOVE-00001", "MOVE-0001", "MOVE-0010", "MOVE-0100", "MOVE-9999", "MOVE-10000"]),   # move_id number, then id
    ({"sort": "move_id", "order": "desc"},
     ["MOVE-10000", "MOVE-9999", "MOVE-0100", "MOVE-0010", "MOVE-0001", "MOVE-00001"]),
    ({"sort": "pmid"}, ["MOVE-0100", "MOVE-0001", "MOVE-10000", "MOVE-00001", "MOVE-0010", "MOVE-9999"]),  # integers
    ({"sort": "pmid", "order": "desc"},
     ["MOVE-0010", "MOVE-9999", "MOVE-00001", "MOVE-10000", "MOVE-0001", "MOVE-0100"]),   # tie: move_id ascending
    ({"sort": "year"}, ["MOVE-00001", "MOVE-0010", "MOVE-9999", "MOVE-0001", "MOVE-0100", "MOVE-10000"]),
    ({"sort": "year", "order": "desc"},
     ["MOVE-0010", "MOVE-9999", "MOVE-00001", "MOVE-0001", "MOVE-0100", "MOVE-10000"]),   # no integer year: last
    ({"sort": "variant"}, ["MOVE-00001", "MOVE-0100", "MOVE-9999", "MOVE-0001", "MOVE-0010", "MOVE-10000"]),
    ({"sort": "variant", "order": "desc"},
     ["MOVE-0001", "MOVE-0010", "MOVE-10000", "MOVE-9999", "MOVE-00001", "MOVE-0100"]),
    ({"sort": "file"}, ["MOVE-00001", "MOVE-0010", "MOVE-9999", "MOVE-10000", "MOVE-0001", "MOVE-0100"]),
    ({"sort": "file", "order": "desc"},
     ["MOVE-0001", "MOVE-0100", "MOVE-00001", "MOVE-0010", "MOVE-9999", "MOVE-10000"]),
]


@pytest.mark.parametrize("params, expected", SORTS, ids=[str(p) for p, _ in SORTS])
def test_sort_keys_orders_and_ties(client, designed, params, expected):
    assert _ids(client, designed, params) == expected


def test_sort_keys_are_exactly_five_and_never_an_effect_value():
    assert K.SORT_KEYS == ("move_id", "pmid", "year", "variant", "file")
    assert not {"direction", "magnitude_bucket", "fold_change", "effects", "target_role"} & set(K.SORT_KEYS)


def test_page_offset_limit_and_page_bibliography(client, designed):
    body = _detail(client, designed["rid"], designed["flagged"], {"sort": "year", "limit": 2, "offset": 3}).json()
    assert [i["record"]["move_id"] for i in body["records"]] == ["MOVE-0001", "MOVE-0100"]
    assert body["page"] == {"target": "P0SYN1", "total": 6, "filtered_total": 6, "offset": 3, "limit": 2}
    assert list(body["bibliography"]) == ["50", "60"]                   # this page's PMIDs only
    assert body["bibliography"]["60"]["year"] is None
    tail = _detail(client, designed["rid"], designed["flagged"], {"sort": "year", "offset": 5}).json()
    assert [i["record"]["move_id"] for i in tail["records"]] == ["MOVE-10000"]
    assert tail["bibliography"] == {"777": None}                        # no bibliography row: null
    beyond = _detail(client, designed["rid"], designed["flagged"], {"offset": 100}).json()
    assert beyond["records"] == [] and beyond["page"]["filtered_total"] == 6 and beyond["bibliography"] == {}
    assert _detail(client, designed["rid"], designed["flagged"], {"limit": 100}).status_code == 200
    assert _detail(client, designed["rid"], designed["flagged"], {"limit": 1}).status_code == 200


BAD_PARAMS = [
    {"file": "flagged"}, {"file": ["moves", "moves_flagged"]}, {"site": "bp_I_C"}, {"goal": "Potency"},
    {"tactic": "nope"}, {"site": ["bp_I_A", "nope"]}, {"sort": "direction"}, {"sort": "magnitude_bucket"},
    {"sort": "fold_change"}, {"sort": ""}, {"sort": ["pmid", "year"]}, {"order": "up"}, {"order": ""},
    {"limit": 0}, {"limit": 101}, {"limit": "x"}, {"limit": "-1"}, {"limit": ["5", "6"]}, {"offset": -1},
    {"offset": "1.5"}, {"q": ""}, {"q": "   "}, {"q": "x" * 101}, {"q": ["a", "b"]}, {"variant": ["A10V", "T20M"]},
    {"target": ["P0SYN1", "Q0SYN2"]}, {"chain_limit": 5}, {"handle": "x"}, {"Sort": "pmid"},
]


@pytest.mark.parametrize("params", BAD_PARAMS, ids=[str(p) for p in BAD_PARAMS])
def test_unknown_keys_and_values_are_422(client, designed, params):
    response = _detail(client, designed["rid"], designed["flagged"], params)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "input_invalid"


def test_query_of_exactly_100_characters_is_accepted(client, designed):
    assert _detail(client, designed["rid"], designed["flagged"], {"q": "z" * 100}).status_code == 200
    assert _ids(client, designed, {"q": " " + "z" * 99}) == []


# ------------------------------------------------------------------------------------------- detail: sets, 404

def test_detail_after_a_set_swap_and_without_a_set(client, world):
    rid, handle = world["rid"], world["full"]
    other = PF.build_set(world["root"], imported_at="2026-10-10T00:00:04Z")
    body = _detail(client, rid, handle).json()
    assert body["active_set"] == {"set_hash": other, "same": False}
    assert body["precedent_set"]["set_hash"] == world["set_hash"]      # the result is never recomputed
    PF.activate(world["root"], world["set_hash"])
    assert _detail(client, rid, handle).json()["active_set"] == {"set_hash": world["set_hash"], "same": True}
    shutil.rmtree(world["root"])
    assert _detail(client, rid, handle).json()["active_set"] == {"set_hash": None, "same": False}


def test_detail_other_run_other_kind_and_unknown_handles_are_404(client, world):
    rid = world["rid"]
    other_rid = _new_run(client)
    other_map = _store_map(_app()._run(other_rid), _load(client, other_rid), "main")
    other = _ok(_link(client, other_rid, other_map))
    assert _detail(client, rid, other).status_code == 404                    # another run's result
    assert _detail(client, rid, world["structure"]).status_code == 404       # another kind of this run
    assert _detail(client, rid, world["maps"]["main"]).status_code == 404
    assert _detail(client, rid, f"obj://{rid}/kinase_precedents/" + "0" * 64).status_code == 404
    assert _detail(client, rid, "not-a-handle").status_code == 404
    assert _detail(client, other_rid, other).status_code == 200


def test_detail_and_list_revalidate_the_stored_object(client, world):
    run = _app()._run(world["rid"])
    content = copy.deepcopy(run.store.load(world["full"]))
    content["counts"]["chains"] = 9        # SYNTHETIC forged object written past the tool
    forged = run.store.put(K.KIND, K.SCHEMA, content, produced_by="synthetic_fixture").handle
    response = _detail(client, world["rid"], forged)
    assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    listed = client.get(f"/runs/{world['rid']}/kinase_precedents")
    assert listed.status_code == 409 and listed.json()["detail"]["error"] == "run_corrupt"


def test_a_deeply_nested_stored_result_is_refused_by_the_reads(client, world):
    """SYNTHETIC damaged object: raw JSON nested past the recursion limit, stored under the result kind."""
    run = _app()._run(world["rid"])
    depth = 100000
    deep = run.store.put(K.KIND, K.SCHEMA, b"[" * depth + b"]" * depth, produced_by="synthetic_fixture").handle
    with pytest.raises(RecursionError):
        run.store.load(deep)
    response = _detail(client, world["rid"], deep)
    assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    listed = client.get(f"/runs/{world['rid']}/kinase_precedents")
    assert listed.status_code == 409 and listed.json()["detail"]["error"] == "run_corrupt"


# ------------------------------------------------------------------------------------------- read side effects

def test_reads_write_nothing_read_the_log_at_most_once_and_open_no_socket(client, designed, monkeypatch):
    rid = designed["rid"]
    run = _app()._run(rid)
    log = run.run_dir / "events.jsonl"
    before = log.read_bytes()
    jobs_before = client.get(f"/runs/{rid}/jobs").json()
    counted = {"n": 0}
    original = run.events.read

    def counting():
        counted["n"] += 1
        return original()

    monkeypatch.setattr(run.events, "read", counting)
    _NoSockets(monkeypatch)
    detail = f"/runs/{rid}/kinase_precedents/{designed['flagged']}"
    for path, params, most in ((f"/runs/{rid}/kinase_precedents", None, 1), (detail, None, 1),
                               (detail, {"q": "zz", "site": ["front", "bp_I_A"], "sort": "year", "order": "desc",
                                         "limit": 2, "offset": 1}, 1),
                               ("/precedent_reference/status", None, 0)):
        counted["n"] = 0
        response = client.get(path, params=params)
        assert response.status_code == 200, response.text
        assert counted["n"] <= most, (path, counted["n"])
        if path == f"/runs/{rid}/kinase_precedents":
            assert counted["n"] == 1
    assert log.read_bytes() == before
    assert client.get(f"/runs/{rid}/jobs").json() == jobs_before


def test_reads_recover_from_events_only_without_the_reference_folder(client, world):
    rid = world["rid"]
    run = _app()._run(rid)
    detail = _detail(client, rid, world["full"]).json()
    listed = client.get(f"/runs/{rid}/kinase_precedents").json()
    shutil.rmtree(world["root"])
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    _app().RUNS.clear()   # reopen the run: objects come back from events.jsonl alone
    again = _detail(client, rid, world["full"]).json()
    assert {**again, "active_set": None} == {**detail, "active_set": None}
    assert again["active_set"] == {"set_hash": None, "same": False}
    relisted = client.get(f"/runs/{rid}/kinase_precedents").json()
    assert relisted == {"items": [{**item, "active": False} for item in listed["items"]], "total": 2}


# ------------------------------------------------------------------------------------------- route order

def test_the_path_handle_route_is_registered_after_the_other_precedent_routes(client, world):
    paths = [getattr(route, "path", None) for route in _app().app.routes]
    detail = paths.index("/runs/{rid}/kinase_precedents/{handle:path}")
    for literal in ("/precedent_reference/status", "/runs/{rid}/kinase_precedents"):
        assert paths.index(literal) < detail, literal
    assert client.get("/precedent_reference/status").json()["schema"] == K.STATUS_SCHEMA
    assert set(client.get(f"/runs/{world['rid']}/kinase_precedents").json()) == {"items", "total"}


# ------------------------------------------------------------------------------------------- the tool over HTTP

def test_commands_route_status_codes(client, refdir, monkeypatch):
    rid = _new_run(client)
    run = _app()._run(rid)
    nmap = _store_map(run, _load(client, rid), "main")
    missing = _link(client, rid, nmap)
    assert missing.status_code == 412 and missing.json()["detail"] == {"reason_code": "not_installed"}
    PF.build_set(refdir)
    invalid = _link(client, rid, nmap, chains=["Z"])
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {"reason_code": "chain_not_in_map", "chain_auth": "Z"}
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", 1000)
    capped = _link(client, rid, nmap)
    assert capped.status_code == 429 and capped.json()["detail"]["reason_code"] == "result_too_large"
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", 1024 * 1024)
    first = _ok(_link(client, rid, nmap))
    assert _ok(_link(client, rid, nmap, chains=["E", "D", "C", "B", "A"])) == first
    assert [e["type"] for e in _events(rid) if e.get("tool") == TOOL][-1] == "cache_hit"
    created = [e["handle"] for e in _events(rid) if e["type"] == "object_created" and e.get("kind") == K.KIND]
    assert created == [first]   # the refused calls stored nothing


def test_dry_run_run_stores_the_result(client, refdir):
    PF.build_set(refdir)
    rid = _new_run(client, dry_run=True)
    nmap = _store_map(_app()._run(rid), _load(client, rid), "main")
    handle = _ok(_link(client, rid, nmap, include_flagged=True))
    assert _detail(client, rid, handle).status_code == 200
