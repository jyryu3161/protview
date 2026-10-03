"""M20 T4: mutation candidate read API (spec 8): list, detail, position page, candidate page. No read creates an
event, a tool call or a job.

Objects are made once per module by the product tool path (``load_structure`` -> ``prepare_structure`` ->
``generate_mutation_candidates`` through ``Run.call``) on the SYNTHETIC fixtures in ``fixtures/mutation/`` (labelled;
insertion code, null label, multi-letter chain, two same-sequence chains, metals, disulfides) and on the public 1MQ4
mmCIF (+ ADP; a reference FIXTURE set from ``fixtures/reference`` for the M15 map and M16 annotation). Expected read
values are the stored object's own values; ligand-distance order is checked against the independent brute-force
oracle ``fixtures/mutation/expected.json``. Fault injections (edited / forged stored objects) are labelled.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from reference_fixture_set import build_fixture_set

from mw import mutation_constants as K
from mw import mutation_reads
from mw import reference_snapshots as rs
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.workspace import new_run

FIX = Path(__file__).resolve().parent / "fixtures"
MUT = FIX / "mutation"
CIF = MUT / "synthetic-mutation-fixture.cif"
PDB = MUT / "synthetic-mutation-fixture-nolabel.pdb"
CIF_1MQ4 = FIX / "public_1mq4.cif"
ORACLE = json.loads((MUT / "expected.json").read_text())["files"]
TOOL = K.TOOL
RID, OTHER = "run_mutreads", "run_mutother"
LIST_KEYS = {"handle", "created_seq", "valid", "structure", "model_number", "ligand", "sources_used", "klifs_status",
             "numbering_map", "annotation", "counts", "null_result"}


def res(chain_auth: str, seq_auth: int, resname: str, icode: str = "") -> dict:
    return {"model_number": 1, "chain_auth": chain_auth, "seq_auth": seq_auth, "icode": icode, "resname": resname}


def _args(structure, *, ligand_shell=None, residues=(), **kw):
    return {"structure": structure, "sources": {"pocket": None, "ligand_shell": ligand_shell,
                                                "residues": list(residues)}, **kw}


def _prepared(run, path: Path) -> str:
    loaded = run.call("load_structure", {"source": str(path), "model_index": 0}).handle
    return run.call("prepare_structure", {"structure": loaded}).handle


# --- shared world (product tool path, built once) ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("mutation_api")
    root = base / "runs"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(rs.ENV_VAR, str(base / "reference"))
        (base / "reference").mkdir()
        build_fixture_set(base / "reference")
        run = new_run(root, run_id=RID, dry_run=False)
        syn = _prepared(run, CIF)
        lig_a = res("A", 101, "LIG")
        made = {"syn": syn}
        made["shell"] = run.call(TOOL, _args(syn, ligand_shell={"radius_A": 5.0}, ligand=lig_a, residues=[
            res("A", 10, "ILE", "A"), res("CC", 11, "ALA"), res("B", 1, "GLY"), res("A", 5, "CYS"),
            res("A", 11, "LYS")])).handle
        made["plain"] = run.call(TOOL, _args(syn, residues=[res("A", 5, "CYS"), res("CC", 11, "ALA"),
                                                             res("A", 2, "ALA"), res("A", 10, "ILE", "A")])).handle
        made["zero"] = run.call(TOOL, _args(syn, residues=[res("A", 2, "ALA"), res("A", 3, "SER")])).handle
        nolabel = _prepared(run, PDB)
        made["nolabel"] = run.call(TOOL, _args(nolabel, ligand_shell={"radius_A": 5.0}, ligand=lig_a,
                                               residues=[res("A", 10, "ILE", "A")])).handle
        mq = _prepared(run, CIF_1MQ4)
        numbering_map = run.call("map_residue_numbering", {"structure": mq, "pdb_id": "1MQ4",
                                                           "chains": [{"chain_auth": "A"}]}).handle
        annotation = run.call("annotate_reference_sites", {"numbering_map": numbering_map}).handle
        adp = res("A", 2001, "ADP")
        made["mq"] = run.call(TOOL, _args(mq, ligand_shell={"radius_A": 5.0}, ligand=adp, residues=[res("A", 126, "ARG")],
                                          protected_residues=[res("A", 139, "LEU")],
                                          released_residues=[res("A", 261, "ASN")], numbering_map=numbering_map,
                                          annotation=annotation)).handle
        made["wide"] = run.call(TOOL, _args(mq, ligand_shell={"radius_A": 12.0}, ligand=adp)).handle
        other = new_run(root, run_id=OTHER, dry_run=False)
        made["other"] = other.call(TOOL, _args(_prepared(other, CIF), residues=[res("A", 6, "HID")])).handle
        made["order"] = ["shell", "plain", "zero", "nolabel", "mq", "wide"]
        made["stored"] = {name: run.store.load(made[name]) for name in made["order"]}
    return {"root": root, **made}


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _base(rid=RID) -> str:
    return f"/runs/{rid}/mutation_candidate_sets"


def _get(client, handle, sub="", rid=RID, encode=False, **params):
    path = quote(handle, safe="") if encode else handle
    return client.get(f"{_base(rid)}/{path}{'/' + sub if sub else ''}", params=params)


def _events_bytes(root, rid=RID) -> bytes:
    return (root / rid / "events.jsonl").read_bytes()


def _all_positions(client, handle, **params) -> list[dict]:
    rows, offset = [], 0
    while True:
        page = _get(client, handle, "positions", offset=offset, limit=100, **params)
        assert page.status_code == 200, page.text
        rows += page.json()["rows"]
        offset += 100
        if offset >= page.json()["total"]:
            return rows


# --- reads write no event and start nothing ---------------------------------------------------------------------------

def test_every_read_leaves_the_event_log_unchanged(client, world):
    client.get(_base())   # first touch reopens the run
    before = _events_bytes(world["root"])
    shell = world["shell"]
    ok = [client.get(_base()), _get(client, shell), _get(client, shell, encode=True),
          _get(client, shell, "positions"), _get(client, shell, "positions", sort="ligand_distance", status="candidate"),
          _get(client, shell, "candidates"), _get(client, shell, "candidates", position_index=0, to="A"),
          _get(client, world["zero"], "candidates")]
    assert all(response.status_code == 200 for response in ok), [r.text for r in ok if r.status_code != 200]
    refused = [client.get(_base(), params={"bogus": "1"}), _get(client, shell, x="1"),
               _get(client, shell, "positions", sort="score"), _get(client, shell, "candidates", to="B"),
               _get(client, world["syn"]), _get(client, world["other"])]
    assert all(response.status_code in (404, 422) for response in refused)
    after = _events_bytes(world["root"])
    assert after == before
    types = {json.loads(line)["type"] for line in after.splitlines()}
    assert "job_submitted" not in types


# --- list -------------------------------------------------------------------------------------------------------------

def test_list_is_newest_first_with_creating_event_sequence(client, world):
    response = client.get(_base())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema"] == "mutation_candidate_set_list@1" and body["total"] == 6
    assert (body["offset"], body["limit"]) == (0, 50)
    handles = [world[name] for name in world["order"]]
    assert [row["handle"] for row in body["rows"]] == handles[::-1]
    seqs = {}
    for line in _events_bytes(world["root"]).splitlines():
        event = json.loads(line)
        if event["type"] == "object_created" and event["kind"] == K.KIND:
            seqs.setdefault(event["handle"], event["seq"])
    for row in body["rows"]:
        assert set(row) == LIST_KEYS and row["valid"] is True
        assert row["created_seq"] == seqs[row["handle"]]
        stored = world["stored"][world["order"][handles.index(row["handle"])]]
        sources = stored["parameters"]["sources"]
        assert row["structure"] == stored["structure"]["handle"]
        assert row["model_number"] == stored["structure"]["model_number"] == 1
        assert row["ligand"] == stored["ligand"]
        assert row["sources_used"] == {"pocket": False, "ligand_shell": sources["ligand_shell"] is not None,
                                       "user": bool(sources["residues"])}
        assert row["klifs_status"] == stored["protection_checks"]["klifs_key_sites"]["status"]
        assert (row["numbering_map"], row["annotation"]) == (stored["parameters"]["numbering_map"],
                                                             stored["parameters"]["annotation"])
        assert row["counts"] == stored["counts"] and row["null_result"] == stored["null_result"]
    by = {row["handle"]: row for row in body["rows"]}
    assert by[world["mq"]]["klifs_status"] == "checked" and by[world["shell"]]["klifs_status"] == "not_checked"
    assert by[world["wide"]]["sources_used"] == {"pocket": False, "ligand_shell": True, "user": False}
    assert by[world["zero"]]["null_result"] is True and by[world["zero"]]["counts"]["candidates"] == 0
    assert by[world["plain"]]["ligand"] is None


def test_list_pagination_and_limit_bounds(client, world):
    newest = [world[name] for name in world["order"]][::-1]
    page = client.get(_base(), params={"offset": 2, "limit": 3}).json()
    assert page["total"] == 6 and [row["handle"] for row in page["rows"]] == newest[2:5]
    assert client.get(_base(), params={"offset": 6}).json()["rows"] == []
    assert client.get(_base(), params={"limit": 100}).status_code == 200
    assert client.get(_base(), params={"limit": 1}).json()["rows"][0]["handle"] == newest[0]
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"handle": world["shell"]}):
        assert client.get(_base(), params=params).status_code == 422, params
    other = client.get(_base(OTHER)).json()
    assert [row["handle"] for row in other["rows"]] == [world["other"]]
    assert client.get(_base("run_missing")).status_code == 404


# --- detail -----------------------------------------------------------------------------------------------------------

def test_detail_is_the_stored_set_without_rows(client, world):
    for name in world["order"]:
        stored = world["stored"][name]
        for encode in (False, True):
            response = _get(client, world[name], encode=encode)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["schema"] == "mutation_candidate_set_detail@1" and body["handle"] == world[name]
            assert body["result"] == {k: v for k, v in stored.items() if k not in ("positions", "candidates")}
            assert (body["total_positions"], body["total_candidates"]) == (len(stored["positions"]),
                                                                           len(stored["candidates"]))
            assert body["meta"]["kind"] == K.KIND and body["meta"]["schema"] == K.SCHEMA
    assert _get(client, world["shell"], verbose="1").status_code == 422


# --- refusals ---------------------------------------------------------------------------------------------------------

def test_other_run_wrong_kind_and_unknown_handles_are_refused(client, world):
    shell = world["shell"]
    renamed = shell.replace(RID, OTHER)
    unknown = shell[:-64] + "0" * 64
    for sub in ("", "positions", "candidates"):
        for handle in (world["other"], renamed, unknown, "not-a-handle"):
            response = _get(client, handle, sub)
            assert response.status_code == 404, (sub, handle, response.text)
            assert response.json()["detail"]["error"] == "not_found"
        response = _get(client, world["syn"], sub)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid"
        # this run's own set read through the other run's URL is not that run's object
        assert _get(client, shell, sub, rid=OTHER).status_code == 404
        assert _get(client, world["other"], sub, rid=OTHER).status_code == 200


# --- positions --------------------------------------------------------------------------------------------------------

def _expected_positions(stored, status=None, source=None, exclusion_reason=None, chain_auth=None):
    return [p for p in stored["positions"] if (status is None or p["status"] == status)
            and (source is None or source in [s["kind"] for s in p["sources"]])
            and (exclusion_reason is None or exclusion_reason in p["exclusion_reasons"])
            and (chain_auth is None or p["residue"]["chain_auth"] == chain_auth)]


def test_position_filters_and_totals(client, world):
    combos = [{}, {"status": "candidate"}, {"status": "excluded"}, {"source": "ligand_shell"}, {"source": "user"},
              {"source": "pocket"}, {"chain_auth": "CC"}, {"chain_auth": "B"}, {"chain_auth": "Z"},
              {"status": "excluded", "source": "user"}]
    combos += [{"exclusion_reason": reason} for reason in K.EXCLUSION_REASONS]
    nonzero = set()
    for name in world["order"]:
        stored = world["stored"][name]
        for params in combos:
            response = _get(client, world[name], "positions", limit=100, **params)
            assert response.status_code == 200, response.text
            body = response.json()
            expected = _expected_positions(stored, **params)
            assert body["total"] == len(expected) and body["rows"] == expected[:100], (name, params)
            assert body["sort"] == "order" and body["filters"] == {
                key: params.get(key) for key in ("status", "source", "exclusion_reason", "chain_auth")}
            if expected:
                nonzero.add(tuple(sorted(params.items())))
    # the fixtures give a nonzero total for these reasons (klifs_key_site from the annotated 1MQ4 set)
    for reason in ("non_standard_residue", "user_protected", "klifs_key_site", "metal_contact", "disulfide_cys"):
        assert (("exclusion_reason", reason),) in nonzero, reason
    for params in ({"status": "protected"}, {"source": "fpocket"}, {"exclusion_reason": "catalytic"},
                   {"sort": "rank"}, {"sort": "score"}, {"limit": 0}, {"limit": 101}, {"offset": -1},
                   {"position_index": 0}, {"order": "asc"}):
        assert _get(client, world["shell"], "positions", **params).status_code == 422, params


def test_position_pages_default_limit_and_offsets(client, world):
    stored = world["stored"]["wide"]
    assert len(stored["positions"]) > 50   # 1MQ4 ADP shell at 12 A (93 positions)
    first = _get(client, world["wide"], "positions").json()
    assert first["limit"] == 50 and first["offset"] == 0 and first["rows"] == stored["positions"][:50]
    assert first["total"] == len(stored["positions"])
    assert _all_positions(client, world["wide"]) == stored["positions"]
    beyond = _get(client, world["wide"], "positions", offset=len(stored["positions"])).json()
    assert beyond["rows"] == [] and beyond["total"] == len(stored["positions"])
    assert _get(client, world["wide"], "positions", offset=50, limit=100).json()["rows"] == stored["positions"][50:150]


def test_ligand_distance_sort_matches_the_oracle(client, world):
    oracle = {(r["residue"]["chain_auth"], r["residue"]["seq_auth"], r["residue"]["icode"]):
              r["ligand_min_distance_A"]["LIG A101"] for r in ORACLE["synthetic-mutation-fixture.cif"]["polymer_residues"]}
    stored = world["stored"]["shell"]
    rows = _get(client, world["shell"], "positions", sort="ligand_distance").json()["rows"]
    keys = [(p["residue"]["chain_auth"], p["residue"]["seq_auth"], p["residue"]["icode"]) for p in rows]
    assert keys == sorted(keys, key=lambda key: oracle[key])
    assert sorted(p["index"] for p in rows) == list(range(len(stored["positions"])))
    for row in rows:
        key = (row["residue"]["chain_auth"], row["residue"]["seq_auth"], row["residue"]["icode"])
        assert abs(row["ligand_min_distance_A"] - oracle[key]) <= 1e-9
    wide = world["stored"]["wide"]["positions"]
    distances = [p["ligand_min_distance_A"] for p in _all_positions(client, world["wide"], sort="ligand_distance")]
    assert distances == sorted(p["ligand_min_distance_A"] for p in wide)
    # no ligand: every distance is null, so the order is the stored order
    plain = _get(client, world["plain"], "positions", sort="ligand_distance").json()["rows"]
    assert plain == world["stored"]["plain"]["positions"]
    assert all(p["ligand_min_distance_A"] is None for p in plain)
    filtered = _get(client, world["shell"], "positions", sort="ligand_distance", status="candidate").json()
    expected = sorted(_expected_positions(stored, status="candidate"), key=lambda p: p["ligand_min_distance_A"])
    assert filtered["rows"] == expected and filtered["total"] == len(expected)


def test_position_order_puts_nulls_last_and_breaks_ties_by_order():
    rows = [{"index": 0, "ligand_min_distance_A": None}, {"index": 1, "ligand_min_distance_A": 4.0},
            {"index": 2, "ligand_min_distance_A": 0.0}, {"index": 3, "ligand_min_distance_A": 4.0},
            {"index": 4, "ligand_min_distance_A": None}, {"index": 5, "ligand_min_distance_A": 2.5}]
    shuffled = [rows[i] for i in (4, 3, 0, 5, 1, 2)]
    assert [r["index"] for r in mutation_reads.position_order(shuffled, "ligand_distance")] == [2, 5, 1, 3, 0, 4]
    assert [r["index"] for r in mutation_reads.position_order(shuffled, "order")] == [0, 1, 2, 3, 4, 5]


# --- candidates -------------------------------------------------------------------------------------------------------

def _expected_candidates(stored, position_index=None, to=None):
    positions = stored["positions"]
    return [{"index": c["index"], "position_index": c["position_index"],
             "residue": positions[c["position_index"]]["residue"],
             "standard_resname": positions[c["position_index"]]["standard_resname"], "from": c["from"], "to": c["to"]}
            for c in stored["candidates"] if (position_index is None or c["position_index"] == position_index)
            and (to is None or c["to"] == to)]


def test_candidate_pages_filters_and_bounds(client, world):
    stored = world["stored"]["wide"]
    assert len(stored["candidates"]) > 200
    first = _get(client, world["wide"], "candidates").json()
    assert first["schema"] == "mutation_candidate_page@1" and (first["offset"], first["limit"]) == (0, 100)
    assert first["total"] == len(stored["candidates"]) and first["rows"] == _expected_candidates(stored)[:100]
    assert _get(client, world["wide"], "candidates", limit=200).json()["rows"] == _expected_candidates(stored)[:200]
    last = _get(client, world["wide"], "candidates", offset=len(stored["candidates"]) - 1).json()["rows"]
    assert last == _expected_candidates(stored)[-1:]
    a_position = next(p["index"] for p in stored["positions"] if p["status"] == "candidate")
    excluded = next(p["index"] for p in stored["positions"] if p["status"] == "excluded")
    for params in ({"position_index": a_position}, {"to": "W"}, {"position_index": a_position, "to": "G"},
                   {"position_index": excluded}, {"position_index": 100000}):
        body = _get(client, world["wide"], "candidates", limit=200, **params).json()
        expected = _expected_candidates(stored, **params)
        assert body["total"] == len(expected) and body["rows"] == expected[:200], params
        assert body["filters"] == {"position_index": params.get("position_index"), "to": params.get("to")}
    assert _get(client, world["wide"], "candidates", position_index=excluded).json()["total"] == 0
    for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"position_index": -1}, {"position_index": "x"},
                   {"to": "B"}, {"to": "AA"}, {"to": "a"}, {"from": "A"}, {"status": "candidate"}):
        assert _get(client, world["wide"], "candidates", **params).status_code == 422, params


# --- identifiers survive intact ---------------------------------------------------------------------------------------

def test_null_label_insertion_code_and_multi_letter_chain_rows_survive(client, world):
    oracle = {json.dumps(r["residue"], sort_keys=True) for r in ORACLE["synthetic-mutation-fixture.cif"]["residues"]}
    rows = _get(client, world["shell"], "positions").json()["rows"]
    assert all(json.dumps(p["residue"], sort_keys=True) in oracle for p in rows)
    by = {(p["residue"]["chain_auth"], p["residue"]["seq_auth"], p["residue"]["icode"]): p["residue"] for p in rows}
    assert by[("A", 10, "A")] == {"model_number": 1, "chain_auth": "A", "chain_label": "A", "seq_auth": 10,
                                  "seq_label": 11, "icode": "A", "resname": "ILE"}
    assert by[("CC", 11, "")] == {"model_number": 1, "chain_auth": "CC", "chain_label": "C", "seq_auth": 11,
                                  "seq_label": None, "icode": "", "resname": "ALA"}
    assert by[("A", 10, "")]["resname"] == "LEU" and ("B", 10, "A") not in by
    cc = _get(client, world["shell"], "positions", chain_auth="CC").json()["rows"]
    assert [p["residue"]["seq_auth"] for p in cc] == [10, 11] and cc[0]["status"] == "excluded"
    cc_candidates = _get(client, world["shell"], "candidates", position_index=cc[1]["index"], limit=200).json()
    assert cc_candidates["total"] == 19 and all(c["residue"] == by[("CC", 11, "")] for c in cc_candidates["rows"])
    nolabel = _get(client, world["nolabel"], "positions").json()["rows"]
    assert nolabel and all(p["residue"]["chain_label"] is None and p["residue"]["seq_label"] is None for p in nolabel)
    assert any(p["residue"]["icode"] == "A" for p in nolabel)
    mq = _get(client, world["mq"], "positions", limit=100).json()["rows"]
    assert all(p["numbering"] is not None for p in mq) and any(p["protection"]["klifs_sites"] for p in mq)
    assert mq == world["stored"]["mq"]["positions"]


def test_zero_candidate_set_is_a_valid_empty_result(client, world):
    stored = world["stored"]["zero"]
    assert stored["null_result"] is True and stored["candidates"] == []
    detail = _get(client, world["zero"]).json()
    assert detail["total_candidates"] == 0 and detail["total_positions"] == 2
    assert detail["result"]["null_result"] is True and detail["result"]["counts"]["candidates"] == 0
    positions = _get(client, world["zero"], "positions").json()
    assert positions["total"] == 2 and all(p["exclusion_reasons"] == ["metal_contact"] for p in positions["rows"])
    assert _get(client, world["zero"], "positions", status="candidate").json()["total"] == 0
    candidates = _get(client, world["zero"], "candidates").json()
    assert candidates["total"] == 0 and candidates["rows"] == []


# --- tampered objects are never served --------------------------------------------------------------------------------

def _copy_client(world, tmp_path, monkeypatch):
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / RID, root / RID)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    assert client.get(_base()).status_code == 200   # reopen before the edit
    return client, root


def _assert_refused(client, root, handle, marker):
    before = _events_bytes(root)
    row = next(r for r in client.get(_base()).json()["rows"] if r["handle"] == handle)
    assert row["valid"] is False
    assert all(row[key] is None for key in LIST_KEYS - {"handle", "created_seq", "valid"})
    for sub in ("", "positions", "candidates"):
        response = _get(client, handle, sub)
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid"
        assert marker not in response.text
    others = [r for r in client.get(_base()).json()["rows"] if r["handle"] != handle]
    assert others and all(r["valid"] is True for r in others)
    assert _events_bytes(root) == before


def test_edited_stored_object_is_refused(world, tmp_path, monkeypatch):
    """Fault injection: the stored bytes of one set are edited in place (content hash no longer matches)."""
    client, root = _copy_client(world, tmp_path, monkeypatch)
    handle = world["shell"]
    path = root / RID / "objects" / f"{handle.rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["positions"][0]["ligand_min_distance_A"] = 0.123456
    path.write_bytes(canonical_json(content))
    _assert_refused(client, root, handle, "0.123456")


def test_forged_object_with_a_matching_hash_is_refused_by_validation(world, tmp_path, monkeypatch):
    """Fault injection: a set whose content was changed and stored under its own (matching) hash; only
    ``validated_set`` can refuse it (the candidate rows no longer match the counts)."""
    client, root = _copy_client(world, tmp_path, monkeypatch)
    run = api_module._run(RID)
    forged = json.loads(json.dumps(world["stored"]["shell"]))
    forged["candidates"][0]["to"] = "W" if forged["candidates"][0]["to"] != "W" else "Y"
    forged["positions"][-1]["status"] = "candidate"
    handle = run.store.put(K.KIND, K.SCHEMA, forged, summary={"forged": True}).handle
    assert run.store.load(handle) == forged
    _assert_refused(client, root, handle, '"forged"')
