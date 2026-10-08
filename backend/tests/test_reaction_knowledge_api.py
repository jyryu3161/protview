"""M26 read API and capability (spec 6): ``/reaction_reference/status``, ``/reaction_reference/pdb/{pdb_id}``,
``/runs/{rid}/reaction_knowledge`` (list) and ``/runs/{rid}/reaction_knowledge/{handle}`` (detail with paging),
``/capabilities`` ``methods.reaction_knowledge`` and the tool over ``POST /runs/{rid}/commands``.

Every reference folder is a LABELLED SYNTHETIC set written by ``reaction_fixture.build_set`` under a temporary
``MW_REACTION_REFERENCE_DIR``; structures are the synthetic T2 files and the public 1UBQ, uploaded through the HTTP
upload route. Every read is checked to write no event, start no tool or job, read the event log at most once and make
no socket connection.
"""
from __future__ import annotations

import copy
import shutil
import socket

import pytest
import reaction_fixture as RF
from fastapi.testclient import TestClient
from test_reaction_knowledge_tool import ALPHA, BETA, CIF_1UBQ, _synthetic_map

from mw import reaction_knowledge as rk
from mw import reaction_knowledge_constants as K
from mw import reaction_snapshots as rs

TOOL = K.TOOL
STATUS_KEYS = {"schema", "installed", "reason", "set_hash", "imported_at", "sources", "requested_accessions",
               "skipped_accessions"}
ITEM_KEYS = {"handle", "structure_handle", "structure_kind", "pdb_id", "chain_count", "covered_chain_count",
             "mcsa_rows", "uniprot_feature_count", "null_result", "set_hash", "active"}


@pytest.fixture
def refdir(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    yield root
    rs._VERIFIED.clear()
    rk.clear_index_cache()


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
    return client.post("/runs", json={"goal": "reaction knowledge reads", "dry_run": dry_run}).json()["run_id"]


def _load(client, rid, path) -> str:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": path.name}, content=path.read_bytes(),
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                         "args": {"source": upload.json()["upload_id"]}})
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["handle"]["handle"]


def _link(client, rid, structure, chains=(("A", "Q0SYN1"), ("B", None)), pdb_id="0SY1", numbering_map=None):
    return client.post(f"/runs/{rid}/commands", json={"tool": TOOL, "args": {
        "structure": structure, "pdb_id": pdb_id, "numbering_map": numbering_map,
        "chains": [{"chain_auth": c, "uniprot_accession": a} for c, a in chains]}})


def _ok(response) -> str:
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _events(rid):
    return list(_app()._run(rid).events.read())


@pytest.fixture
def world(client, refdir):
    set_hash = RF.build_set(refdir)
    rid = _new_run(client)
    alpha = _load(client, rid, ALPHA)
    nmap = _synthetic_map(_app()._run(rid), alpha)
    full = _ok(_link(client, rid, alpha, numbering_map=nmap))
    ubq = _load(client, rid, CIF_1UBQ)
    empty = _ok(_link(client, rid, ubq, chains=(("A", None),), pdb_id="1UBQ"))
    return {"rid": rid, "alpha": alpha, "map": nmap, "full": full, "empty": empty, "ubq": ubq, "set_hash": set_hash,
            "root": refdir}


class _NoSockets:
    """Fault injection: any socket connection during a read fails the test."""

    def __init__(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("a read must not open a network connection")

        monkeypatch.setattr(socket.socket, "connect", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)


# ------------------------------------------------------------------------------------------- capability

def test_capability_shape_in_every_state_and_templates_unaffected(client, refdir):
    methods = client.get("/capabilities").json()["methods"]
    missing = methods["reaction_knowledge"]
    assert set(missing) == set(methods["residue_numbering"])   # the same five keys as M15
    assert missing == {"available": False, "reason_code": "not_installed",
                       "reason": K.SNAPSHOT_REASONS["not_installed"], "set_hash": None, "sources": []}
    assert "scripts/import_reaction_references.py" in missing["reason"]
    templates = methods["analysis_workflows"]["templates"]
    set_hash = RF.build_set(refdir)
    ready = client.get("/capabilities").json()["methods"]
    assert ready["reaction_knowledge"] == {"available": True, "reason_code": None, "reason": None,
                                           "set_hash": set_hash, "sources": rs.pin_active_set().summary()}
    assert [s["source"] for s in ready["reaction_knowledge"]["sources"]] == ["mcsa", "uniprot_function", "rhea"]
    assert ready["analysis_workflows"]["templates"] == templates
    entries = next(refdir.glob("sets/*/files/mcsa/entries.jsonl"))
    entries.write_bytes(entries.read_bytes() + b"\n")
    invalid = client.get("/capabilities").json()["methods"]["reaction_knowledge"]
    assert invalid == {"available": False, "reason_code": "snapshot_invalid",
                       "reason": K.SNAPSHOT_REASONS["snapshot_invalid"], "set_hash": None, "sources": []}
    assert "scripts/import_reaction_references.py" in invalid["reason"]


def test_tool_is_listed_at_l2(client):
    names = {tool["name"] for tool in client.get("/tools", params={"levels": "L2"}).json()}
    assert TOOL in names


# ------------------------------------------------------------------------------------------- status

def test_status_unavailable_is_the_reason_only(client, refdir, monkeypatch):
    _NoSockets(monkeypatch)
    response = client.get("/reaction_reference/status")
    assert response.status_code == 200
    assert response.json() == {"schema": "reaction_reference_status@1", "installed": False, "reason": "not_installed",
                               "set_hash": None, "imported_at": None, "sources": None, "requested_accessions": None,
                               "skipped_accessions": None}
    RF.build_set(refdir, file_bytes={"rhea": b"not json\n"})
    body = client.get("/reaction_reference/status").json()
    assert body == {**dict.fromkeys(STATUS_KEYS), "schema": K.STATUS_SCHEMA, "installed": False,
                    "reason": "snapshot_invalid"}


def test_status_installed(client, refdir, monkeypatch):
    set_hash = RF.build_set(refdir)
    _NoSockets(monkeypatch)
    body = client.get("/reaction_reference/status").json()
    manifest = rs.pin_active_set().manifest
    assert set(body) == STATUS_KEYS
    assert (body["installed"], body["reason"], body["set_hash"]) == (True, None, set_hash)
    assert body["imported_at"] == RF.IMPORTED_AT
    assert body["requested_accessions"] == manifest["requested_accessions"]
    assert body["skipped_accessions"] == manifest["skipped_accessions"] == RF.SKIPPED
    rows = RF.synthetic_rows()
    assert body["sources"] == [{"source": s, "date": RF.DATE, "license": "CC-BY-4.0", "origin": K.ORIGIN,
                                "rows": len(rows[s])} for s in K.SOURCES]


# ------------------------------------------------------------------------------------------- PDB entries

def test_pdb_entries(client, refdir, monkeypatch):
    RF.build_set(refdir)
    _NoSockets(monkeypatch)
    body = client.get("/reaction_reference/pdb/0sy1").json()
    assert body == {"pdb_id": "0SY1", "entries": [
        {"mcsa_id": 101, "enzyme_name": "SYNTHETIC fixture enzyme alpha", "reference_uniprot_id": "Q0SYN1",
         "chains": ["A", "a"]},
        {"mcsa_id": 102, "enzyme_name": "SYNTHETIC fixture enzyme beta",
         "reference_uniprot_id": "Q0SYN2, P0SYN3", "chains": ["A"]}]}   # the stored raw string, not split
    beta = client.get("/reaction_reference/pdb/0SY2").json()["entries"]
    assert [(e["mcsa_id"], e["chains"]) for e in beta] == [(101, ["A"]), (103, ["A", "B"])]
    assert client.get("/reaction_reference/pdb/1UBQ").json() == {"pdb_id": "1UBQ", "entries": []}


@pytest.mark.parametrize("bad", ["SY01", "0SY12", "0S-1", "abc"])
def test_pdb_entries_bad_id_is_422_before_reading_the_folder(client, refdir, bad):
    response = client.get(f"/reaction_reference/pdb/{bad}")
    assert response.status_code == 422, response.text


def test_pdb_entries_unavailable_is_412_with_the_tool_reason(client, refdir):
    response = client.get("/reaction_reference/pdb/0SY1")
    assert response.status_code == 412
    body = response.json()
    assert body["error"] == "precondition" and body["detail"] == {"reason_code": "not_installed"}
    assert body["message"] == K.SNAPSHOT_REASONS["not_installed"]
    RF.build_set(refdir, file_bytes={"mcsa": b"[]\n"})
    response = client.get("/reaction_reference/pdb/0SY1")
    assert response.status_code == 412 and response.json()["detail"] == {"reason_code": "snapshot_invalid"}


# ------------------------------------------------------------------------------------------- list

def test_list_items_newest_first(client, world, monkeypatch):
    _NoSockets(monkeypatch)
    body = client.get(f"/runs/{world['rid']}/reaction_knowledge").json()
    assert set(body) == {"items", "total"} and body["total"] == 2
    empty, full = body["items"]
    assert set(empty) == ITEM_KEYS and set(full) == ITEM_KEYS
    content = _app()._run(world["rid"]).store.load(world["full"])
    assert full == {"handle": world["full"], "structure_handle": world["alpha"], "structure_kind": "structure",
                    "pdb_id": "0SY1", "chain_count": 2, "covered_chain_count": 1,
                    "mcsa_rows": content["counts"]["mcsa_rows"],
                    "uniprot_feature_count": sum(content["counts"]["uniprot_features"].values()),
                    "null_result": False, "set_hash": world["set_hash"], "active": True}
    assert full["uniprot_feature_count"] == 8   # Q0SYN1 has four sites; both chains carry Q0SYN1
    assert empty == {"handle": world["empty"], "structure_handle": world["ubq"], "structure_kind": "structure",
                     "pdb_id": "1UBQ", "chain_count": 1, "covered_chain_count": 0, "mcsa_rows": None,
                     "uniprot_feature_count": None, "null_result": True, "set_hash": world["set_hash"],
                     "active": True}
    paged = client.get(f"/runs/{world['rid']}/reaction_knowledge", params={"limit": 1, "offset": 1}).json()
    assert paged == {"items": [full], "total": 2}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"limit": "x"}, {"other": 1}])
def test_list_parameter_bounds(client, world, params):
    assert client.get(f"/runs/{world['rid']}/reaction_knowledge", params=params).status_code == 422


def test_active_flag_follows_the_current_set(client, world):
    url = f"/runs/{world['rid']}/reaction_knowledge"
    RF.build_set(world["root"], imported_at="2026-10-08T00:00:03Z")
    assert [item["active"] for item in client.get(url).json()["items"]] == [False, False]
    RF.activate(world["root"], world["set_hash"])
    assert [item["active"] for item in client.get(url).json()["items"]] == [True, True]
    shutil.rmtree(world["root"])
    assert [item["active"] for item in client.get(url).json()["items"]] == [False, False]


def test_list_of_a_run_without_results(client, refdir):
    rid = _new_run(client)
    assert client.get(f"/runs/{rid}/reaction_knowledge").json() == {"items": [], "total": 0}


# ------------------------------------------------------------------------------------------- detail

def _detail(client, world, handle=None, **params):
    return client.get(f"/runs/{world['rid']}/reaction_knowledge/{handle or world['full']}", params=params)


def test_detail_default_page_is_the_stored_object_plus_page_and_active_set(client, world, monkeypatch):
    _NoSockets(monkeypatch)
    content = _app()._run(world["rid"]).store.load(world["full"])
    body = _detail(client, world).json()
    assert set(body) == set(content) | {"page", "active_set"}
    assert {k: body[k] for k in content if k != "chains"} == {k: v for k, v in content.items() if k != "chains"}
    assert body["page"] == {"chain_total": 2, "chain_offset": 0, "chain_limit": 10, "row_offset": 0, "row_limit": 50,
                            "feature_offset": 0, "feature_limit": 50}
    assert body["active_set"] == {"set_hash": world["set_hash"], "same": True}
    a, b = body["chains"]
    stored_a, stored_b = content["chains"]
    assert a["mcsa"] == {**stored_a["mcsa"], "row_total": len(stored_a["mcsa"]["rows"])}
    assert a["uniprot"] == {**stored_a["uniprot"], "feature_total": 4}
    assert b["mcsa"] == {**stored_b["mcsa"], "row_total": None}           # chain_not_listed: rows null
    assert {k: a[k] for k in a if k not in ("mcsa", "uniprot")} == {
        k: stored_a[k] for k in stored_a if k not in ("mcsa", "uniprot")}


def test_detail_paging(client, world):
    content = _app()._run(world["rid"]).store.load(world["full"])
    rows = content["chains"][0]["mcsa"]["rows"]
    features = content["chains"][0]["uniprot"]["features"]
    body = _detail(client, world, chain_offset=0, chain_limit=1, row_offset=3, row_limit=2, feature_offset=1,
                   feature_limit=2).json()
    (chain,) = body["chains"]
    assert chain["mcsa"]["rows"] == rows[3:5] and chain["mcsa"]["row_total"] == len(rows)
    assert chain["uniprot"]["features"] == features[1:3] and chain["uniprot"]["feature_total"] == 4
    assert body["page"] == {"chain_total": 2, "chain_offset": 0, "chain_limit": 1, "row_offset": 3, "row_limit": 2,
                            "feature_offset": 1, "feature_limit": 2}
    second = _detail(client, world, chain_offset=1, chain_limit=10).json()
    assert [c["chain_auth"] for c in second["chains"]] == ["B"]
    beyond = _detail(client, world, chain_offset=5, row_offset=1000, feature_offset=1000).json()
    assert beyond["chains"] == [] and beyond["page"]["chain_total"] == 2
    tail = _detail(client, world, row_offset=1000, feature_offset=1000).json()["chains"][0]
    assert tail["mcsa"]["rows"] == [] and tail["mcsa"]["row_total"] == len(rows)
    assert tail["uniprot"]["features"] == [] and tail["uniprot"]["feature_total"] == 4


def test_detail_null_sections_stay_null(client, world):
    (chain,) = _detail(client, world, handle=world["empty"]).json()["chains"]
    assert (chain["mcsa"]["rows"], chain["mcsa"]["row_total"]) == (None, None)
    assert (chain["uniprot"]["features"], chain["uniprot"]["feature_total"]) == (None, None)


@pytest.mark.parametrize("params", [
    {"chain_limit": 0}, {"chain_limit": 11}, {"row_limit": 0}, {"row_limit": 201}, {"feature_limit": 0},
    {"feature_limit": 201}, {"chain_offset": -1}, {"row_offset": -1}, {"feature_offset": -1}, {"chain_limit": "x"},
    {"limit": 5}])
def test_detail_parameter_bounds(client, world, params):
    assert _detail(client, world, **params).status_code == 422


def test_detail_parameter_upper_bounds_are_accepted(client, world):
    assert _detail(client, world, chain_limit=10, row_limit=200, feature_limit=200).status_code == 200
    assert _detail(client, world, chain_limit=1, row_limit=1, feature_limit=1).status_code == 200


def test_detail_after_a_set_swap_and_without_a_set(client, world):
    other = RF.build_set(world["root"], imported_at="2026-10-08T00:00:04Z")
    body = _detail(client, world).json()
    assert body["active_set"] == {"set_hash": other, "same": False}
    assert body["snapshot_set"]["set_hash"] == world["set_hash"]   # the result is never recomputed
    shutil.rmtree(world["root"])
    assert _detail(client, world).json()["active_set"] == {"set_hash": None, "same": False}


def test_detail_other_run_other_kind_and_unknown_handles_are_404(client, world):
    other_rid = _new_run(client)
    other_structure = _load(client, other_rid, BETA)
    other = _ok(_link(client, other_rid, other_structure, chains=(("A", None),), pdb_id="0SY2"))
    assert _detail(client, world, handle=other).status_code == 404               # another run's result
    assert _detail(client, world, handle=world["alpha"]).status_code == 404      # another kind of this run
    assert _detail(client, world, handle=world["map"]).status_code == 404
    unknown = f"obj://{world['rid']}/reaction_knowledge/" + "0" * 64
    assert _detail(client, world, handle=unknown).status_code == 404
    assert _detail(client, world, handle="not-a-handle").status_code == 404
    assert client.get(f"/runs/{other_rid}/reaction_knowledge/{other}").status_code == 200


def test_detail_and_list_revalidate_the_stored_object(client, world):
    run = _app()._run(world["rid"])
    content = copy.deepcopy(run.store.load(world["full"]))
    content["counts"]["chains"] = 3        # SYNTHETIC forged object written past the tool
    forged = run.store.put(K.KIND, K.SCHEMA, content, produced_by="synthetic_fixture").handle
    response = _detail(client, world, handle=forged)
    assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
    listed = client.get(f"/runs/{world['rid']}/reaction_knowledge")
    assert listed.status_code == 409 and listed.json()["detail"]["error"] == "run_corrupt"


# ------------------------------------------------------------------------------------------- read side effects

def test_reads_write_nothing_read_the_log_at_most_once_and_open_no_socket(client, world, monkeypatch):
    rid = world["rid"]
    run = _app()._run(rid)
    log = run.run_dir / "events.jsonl"
    before = log.read_bytes()
    jobs_before = client.get(f"/runs/{rid}/jobs").json()
    reads = {"n": 0}
    original = run.events.read

    def counting():
        reads["n"] += 1
        return original()

    monkeypatch.setattr(run.events, "read", counting)
    _NoSockets(monkeypatch)
    for path, most in ((f"/runs/{rid}/reaction_knowledge", 1), (f"/runs/{rid}/reaction_knowledge/{world['full']}", 1),
                       ("/reaction_reference/status", 0), ("/reaction_reference/pdb/0SY1", 0)):
        reads["n"] = 0
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert reads["n"] <= most, (path, reads["n"])
        if path == f"/runs/{rid}/reaction_knowledge":
            assert reads["n"] == 1
    assert log.read_bytes() == before
    assert client.get(f"/runs/{rid}/jobs").json() == jobs_before


def test_reads_recover_from_events_only_without_the_reference_folder(client, world):
    rid = world["rid"]
    run = _app()._run(rid)
    detail = _detail(client, world).json()
    listed = client.get(f"/runs/{rid}/reaction_knowledge").json()
    shutil.rmtree(world["root"])
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    _app().RUNS.clear()   # reopen the run: objects come back from events.jsonl alone
    again = _detail(client, world).json()
    assert {**again, "active_set": None} == {**detail, "active_set": None}
    assert again["active_set"] == {"set_hash": None, "same": False}
    relisted = client.get(f"/runs/{rid}/reaction_knowledge").json()
    assert relisted == {"items": [{**item, "active": False} for item in listed["items"]], "total": 2}


# ------------------------------------------------------------------------------------------- route order

def test_the_path_handle_route_is_registered_after_the_other_reaction_routes(client, world):
    paths = [getattr(route, "path", None) for route in _app().app.routes]
    detail = paths.index("/runs/{rid}/reaction_knowledge/{handle:path}")
    for literal in ("/reaction_reference/status", "/reaction_reference/pdb/{pdb_id}",
                    "/runs/{rid}/reaction_knowledge"):
        assert paths.index(literal) < detail, literal
    assert client.get("/reaction_reference/status").json()["schema"] == K.STATUS_SCHEMA
    assert set(client.get(f"/runs/{world['rid']}/reaction_knowledge").json()) == {"items", "total"}
    assert client.get("/reaction_reference/pdb/0SY1").json()["pdb_id"] == "0SY1"


# ------------------------------------------------------------------------------------------- the tool over HTTP

def test_commands_route_status_codes(client, refdir, monkeypatch):
    rid = _new_run(client)
    alpha = _load(client, rid, ALPHA)
    missing = _link(client, rid, alpha)
    assert missing.status_code == 412 and missing.json()["detail"] == {"reason_code": "not_installed"}
    RF.build_set(refdir)
    invalid = _link(client, rid, alpha, pdb_id="bad")
    assert invalid.status_code == 422 and invalid.json()["detail"] == {"reason_code": "pdb_id_invalid"}
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", 1000)
    capped = _link(client, rid, alpha)
    assert capped.status_code == 429 and capped.json()["detail"]["reason_code"] == "result_too_large"
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", 1024 * 1024)
    first = _ok(_link(client, rid, alpha))
    assert _ok(_link(client, rid, alpha)) == first
    assert [e["type"] for e in _events(rid) if e.get("tool") == TOOL][-1] == "cache_hit"
    created = [e["handle"] for e in _events(rid) if e["type"] == "object_created" and e.get("kind") == K.KIND]
    assert created == [first]   # the refused calls stored nothing


def test_dry_run_run_stores_the_result(client, refdir):
    RF.build_set(refdir)
    rid = _new_run(client, dry_run=True)
    handle = _ok(_link(client, rid, _load(client, rid, ALPHA)))
    assert client.get(f"/runs/{rid}/reaction_knowledge/{handle}").status_code == 200
