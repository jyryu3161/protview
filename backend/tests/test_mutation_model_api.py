"""M21 T5: ``mutation_model@1`` read API (spec 6): list, detail without rows, contact pages, mmCIF downloads, ``/tools``.

The model comes from the real worker through the product job path (``mutation_model_fixture.shared_world``; public
1UBQ I44W). Reads must write no event, start no job or tool, refuse unknown query parameters, other-run and wrong-kind
handles, and return stored values only (download bytes = the stored mmCIF object bytes). Forged objects below are
LABELED TEST FABRICATIONS in a copied run.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from mutation_model_fixture import SIDES, shared_world

from mw import mutation_model_bundle as bundle
from mw import mutation_model_constants as K
from mw.api import app as api_module
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.tools import openmm_method
from mw.workspace import new_run

ROW_FIELDS = ("final_bonds", "atom_mapping")
LIST_KEYS = {"handle", "created_seq", "valid", "candidate", "structure", "parameters"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return shared_world(tmp_path_factory)


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _base(rid: str) -> str:
    return f"/runs/{rid}/mutation_models"


def _get(client, rid, handle, sub="", encode=False, **params):
    path = quote(handle, safe="") if encode else handle
    return client.get(f"{_base(rid)}/{path}{'/' + sub if sub else ''}", params=params)


def _events_bytes(world, rid=None) -> bytes:
    return (world["root"] / (rid or world["rid"]) / "events.jsonl").read_bytes()


def _stored(world) -> dict:
    return api_module._run(world["rid"]).store.load(world["model"])


def _forbid(*_args, **_kwargs):
    raise AssertionError("a read must not run scientific work, a tool, a job or a process")


# --- reads write no event and start nothing ---------------------------------------------------------------------------

def test_every_read_leaves_the_event_log_unchanged_and_runs_nothing(client, world, monkeypatch):
    rid, model = world["rid"], world["model"]
    client.get(_base(rid))   # first touch reopens the run
    before = _events_bytes(world)
    with monkeypatch.context() as patch:
        patch.setattr(bundle, "require_ready", _forbid)
        patch.setattr(openmm_method, "preflight", _forbid)
        patch.setattr(openmm_method, "dependencies", _forbid)
        patch.setattr(JobQueue, "_supervise", _forbid)
        patch.setattr(JobQueue, "submit", _forbid)
        patch.setattr(Run, "call", _forbid)
        patch.setattr(subprocess, "Popen", _forbid)
        ok = [client.get(_base(rid)), _get(client, rid, model), _get(client, rid, model, encode=True),
              *(_get(client, rid, model, "contacts", structure=side) for side in SIDES),
              _get(client, rid, model, "contacts", structure="mutant", page=2, page_size=3),
              *(_get(client, rid, model, "structure", side=side) for side in SIDES),
              _get(client, rid, model, "structure", encode=True, side="mutant")]
        assert all(r.status_code == 200 for r in ok), [r.text for r in ok if r.status_code != 200]
        refused = [client.get(_base(rid), params={"bogus": "1"}), _get(client, rid, model, x="1"),
                   _get(client, rid, model, "contacts", structure="both"),
                   _get(client, rid, model, "contacts", structure="mutant", offset=0),
                   _get(client, rid, model, "structure", side="mutant", format="pdb"),
                   _get(client, rid, model, "structure", side="both"),
                   _get(client, rid, world["candidate_set"]), _get(client, rid, world["other_model"])]
        assert all(r.status_code in (404, 422) for r in refused), [r.status_code for r in refused]
    after = _events_bytes(world)
    assert after == before


# --- list -------------------------------------------------------------------------------------------------------------

def test_list_is_validated_newest_first_with_candidate_summary(client, world):
    response = client.get(_base(world["rid"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "mutation_model_list@1" and body["total"] == 1
    assert (body["offset"], body["limit"]) == (0, 50)
    [row] = body["rows"]
    stored = _stored(world)
    created = [json.loads(line) for line in _events_bytes(world).splitlines()]
    seq = next(e["seq"] for e in created if e["type"] == "object_created" and e["handle"] == world["model"])
    assert set(row) == LIST_KEYS and row["valid"] is True and row["created_seq"] == seq
    assert row["handle"] == world["model"]
    assert row["candidate"] == {key: stored["candidate"][key] for key in
                                ("candidate_set", "candidate_index", "residue", "from", "to", "mutant_resname")}
    assert row["candidate"]["residue"] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 44,
                                           "seq_label": 44, "icode": "", "resname": "ILE"}
    assert (row["candidate"]["from"], row["candidate"]["to"]) == ("I", "W")
    assert row["structure"] == stored["structure"] and row["parameters"] == stored["parameters"]
    other = client.get(_base(world["other_rid"])).json()
    assert [r["handle"] for r in other["rows"]] == [world["other_model"]]
    assert client.get(_base(world["rid"]), params={"offset": 1}).json()["rows"] == []
    assert client.get(_base(world["rid"]), params={"limit": 100}).status_code == 200
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"handle": world["model"]}):
        assert client.get(_base(world["rid"]), params=params).status_code == 422, params
    assert client.get(_base("run_missing")).status_code == 404


# --- detail -----------------------------------------------------------------------------------------------------------

def test_detail_is_the_validated_model_without_rows(client, world):
    stored = _stored(world)
    for encode in (False, True):
        response = _get(client, world["rid"], world["model"], encode=encode)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema"] == "mutation_model_detail@1" and body["handle"] == world["model"]
        assert body["meta"]["kind"] == K.KIND and body["meta"]["schema"] == K.SCHEMA
        result = body["result"]
        assert {key: value for key, value in result.items() if key != "structures"} == \
            {key: value for key, value in stored.items() if key != "structures"}
        for side in SIDES:
            entry, shown = stored["structures"][side], result["structures"][side]
            assert set(shown) == set(entry) - set(ROW_FIELDS)
            assert shown["contacts"] == {key: entry["contacts"][key] for key in
                                         ("cutoff_A", "excluded_bond_distance", "count", "residue_count")}
            for key in set(entry) - {*ROW_FIELDS, "contacts"}:
                assert shown[key] == entry[key], (side, key)
        text = response.text
        assert all(field not in text for field in (*ROW_FIELDS, '"rows"', "partner_atom_name"))
    # the stored comparison holds no difference value; the detail adds none
    assert set(result["comparison"]) == {"mutated_residue", "resnames", "new_disulfide_in_mutant",
                                         "protonation_difference_count"}
    assert result["limitations"][:5] == [K.L1, K.L2, K.L3, K.L4, K.L7]


# --- contacts ---------------------------------------------------------------------------------------------------------

def test_contact_pages_return_the_stored_rows_in_order(client, world):
    stored = _stored(world)
    rid, model = world["rid"], world["model"]
    for side in SIDES:
        contacts = stored["structures"][side]["contacts"]
        first = _get(client, rid, model, "contacts", structure=side).json()
        assert first["schema"] == "mutation_model_contact_page@1" and first["structure"] == side
        assert (first["page"], first["page_size"], first["total"]) == (1, 100, contacts["count"])
        assert first["cutoff_A"] == contacts["cutoff_A"] == 4.0 and first["excluded_bond_distance"] == 3
        assert first["mutated_residue"] == stored["structures"][side]["sasa"]["residue"]
        rows, page = [], 1
        while True:
            body = _get(client, rid, model, "contacts", structure=side, page=page, page_size=7).json()
            rows += body["rows"]
            if page * 7 >= body["total"]:
                break
            page += 1
        assert contacts["count"] > 0
        assert [{k: v for k, v in r.items() if k != "index"} for r in rows] == contacts["rows"]
        assert [r["index"] for r in rows] == list(range(contacts["count"]))
        beyond = _get(client, rid, model, "contacts", structure=side, page=999, page_size=200).json()
        assert beyond["rows"] == [] and beyond["total"] == contacts["count"]
    assert _get(client, rid, model, "contacts", structure="mutant", page_size=200).status_code == 200
    for params in ({}, {"structure": "both"}, {"structure": "mutant", "page": 0},
                   {"structure": "mutant", "page_size": 0}, {"structure": "mutant", "page_size": 201},
                   {"structure": "mutant", "limit": 5}):
        assert _get(client, rid, model, "contacts", **params).status_code == 422, params


# --- structure download -----------------------------------------------------------------------------------------------

def test_structure_download_bytes_are_the_stored_mmcif(client, world):
    stored = _stored(world)
    run = api_module._run(world["rid"])
    downloaded = {}
    for side in SIDES:
        entry = stored["structures"][side]
        response = _get(client, world["rid"], world["model"], "structure", side=side)
        assert response.status_code == 200, response.text
        assert response.content == run.store.load(entry["structure_object"]) == \
            bundle.structure_bytes(run, world["model"], side)
        assert hashlib.sha256(response.content).hexdigest() == entry["structure_sha256"]
        assert response.headers["content-type"] == "chemical/x-mmcif"
        disposition = response.headers["content-disposition"]
        assert disposition == (f'attachment; filename="protview-mutation-model-'
                               f'{world["model"].rsplit("/", 1)[-1][:12]}-{side}.cif"')
        assert response.headers["cache-control"] == "private, no-store"
        downloaded[side] = response.content
    assert downloaded["wild_type_reference"] != downloaded["mutant"]
    assert b" TRP " in downloaded["mutant"] and b" TRP " not in downloaded["wild_type_reference"]
    for params in ({}, {"side": "both"}, {"side": "mutant", "structure": "mutant"}):
        assert _get(client, world["rid"], world["model"], "structure", **params).status_code == 422, params


# --- refusals ---------------------------------------------------------------------------------------------------------

def test_other_run_wrong_kind_and_unknown_handles_are_refused(client, world):
    rid, model = world["rid"], world["model"]
    renamed = model.replace(rid, world["other_rid"])
    unknown = model[:-64] + "0" * 64
    side_object = _stored(world)["structures"]["mutant"]["structure_object"]
    for sub, params in (("", {}), ("contacts", {"structure": "mutant"}), ("structure", {"side": "mutant"})):
        for handle in (world["other_model"], renamed, unknown, "not-a-handle"):
            response = _get(client, rid, handle, sub, **params)
            assert response.status_code == 404, (sub, handle, response.text)
            assert response.json()["detail"]["error"] == "not_found"
        for wrong in (world["candidate_set"], world["structure"], side_object):
            response = _get(client, rid, wrong, sub, **params)
            assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid", wrong
        assert _get(client, world["other_rid"], model, sub, **params).status_code == 404
        assert _get(client, world["other_rid"], world["other_model"], sub, **params).status_code == 200


def test_forged_models_never_read(world, tmp_path, monkeypatch):
    """LABELED TEST FABRICATIONS in a copy of the run (events only), so the shared run stays untouched."""
    rid = world["rid"]
    copy_root = tmp_path / "copy"
    (copy_root / rid).mkdir(parents=True)
    (copy_root / rid / "events.jsonl").write_bytes(_events_bytes(world))
    copied = new_run(copy_root, run_id=rid, dry_run=False)
    content = copied.store.load(world["model"])
    with copied._owner():
        forged = copied.store.put(K.KIND, K.SCHEMA, {**content, "parameters": {**content["parameters"],
                                                                                "seed": 7}}).handle
    monkeypatch.setattr(api_module, "RUNS_DIR", copy_root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    # A model object with the right kind but no completed publication (no job produced it) never reads.
    for sub, params in (("", {}), ("contacts", {"structure": "wild_type_reference"}),
                        ("structure", {"side": "wild_type_reference"})):
        response = _get(client, rid, forged, sub, **params)
        assert response.status_code == 422, (sub, response.text)
        assert response.json()["detail"]["error"] == "method_evidence_invalid"
        assert _get(client, rid, world["model"], sub, **params).status_code == 200
    rows = client.get(_base(rid)).json()["rows"]
    assert [(r["handle"], r["valid"]) for r in rows] == [(forged, False), (world["model"], True)]
    assert all(rows[0][key] is None for key in ("candidate", "structure", "parameters"))


# --- tools listing ----------------------------------------------------------------------------------------------------

def test_tools_lists_the_job_only_mutation_model_tool(client):
    l3 = {tool["name"]: tool for tool in client.get("/tools", params={"levels": "L3"}).json()}
    tool = l3[K.TOOL]
    assert tool["execution_lane"] == "durable_job" and tool["submit_protocol_id"] == K.PROTOCOL
    assert tool["cost_class"] == "expensive" and tool["emits"] == K.KIND
    assert l3["openmm_protein_minimize"]["submit_protocol_id"] == "openmm_protein_minimize"
    assert K.TOOL not in {tool["name"] for tool in client.get("/tools").json()}   # default levels L2,L4
    assert K.TOOL not in api_module.SUPPORTED_TOOLS
