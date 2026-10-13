"""M29 T8b: ``structure_origin`` on the downstream reads and the JEV warning JW1 (spec .dryforge/spec.md 6.1, 6.2, 6.4).

Inputs (every one labelled):

* Run "repaired": a SYNTHETIC edit of public 1UBQ made at test time (residue A48 LYS without its NZ atom; a comment line
  in the uploaded file says so; public structure, not experimental validation) uploaded, loaded and prepared by the
  product, then repaired by the product repair job (REAL PDBFixer worker through POST /jobs -> approve -> start). On
  the repaired structure: an M20 set (I44, real tool), the M21 job I44W (REAL worker), the M18 job on its mutant side
  (REAL qvina worker, ``.deps``; the labelled synthetic phenol SDF), a JEV projection (real tool), one approved send
  through a ``jev_send_fixture.Fake`` gate (``httpx.MockTransport``, inert sentinel credential: no socket, no
  ``.env``, no real JEV call) and a protein loop (real create). The original (unrepaired) structure also gets an M20
  set.
* Run "plain": the same chain on public 1UBQ itself (no repair).
* M23 sequence GA: a LABELLED STAND-IN. A real GA takes minutes, so each run stores one SYNTHETIC
  ``sequence_ga_result`` object naming its candidate set (not a GA output) and the M23 read functions are replaced by
  fixed answers naming it: only the response layer (``app.py``) is under test; the read module is a call-key hash file
  and stays byte for byte as it was (its real-GA reads are the M23 tests').
* Fault injections (labelled): the installed template made unavailable (``structure_repair._templates`` raises
  ``openmm_unavailable``), a record that no longer re-derives (``structure_repair.validated_repair`` raises
  ``repair_record_mismatch``) and a malformed repair link stored in a scratch run.
* Baseline: ``app.py``, ``mutation_reads.py``, ``mutation_model_reads.py`` and ``docking_reads.py`` of commit
  ``ea166565`` (before T5-T8b) read from git and served next to the current app on the same runs.

Expected values come from the input edit (one NZ atom on A48) and from the stored record, never from the field itself.
"""
from __future__ import annotations

import ast
import importlib.abc
import importlib.util
import json
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import gemmi
import pytest
import structure_repair_lane_fixture as F
from fastapi.testclient import TestClient
from jev_send_fixture import SENTINEL, Fake, reply
from test_kinase_precedents_ast import BASELINE_BLOBS, _blob

from mw import docking_constants as DC
from mw import docking_reads, mutation_handoff, sequence_ga_reads, structure_origin_reads
from mw import jev_constants as J
from mw import mutation_model_constants as MC
from mw import sequence_ga_constants as SC
from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.jev_sends import ACTIVE_SENDS
from mw.workspace import new_run

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
MW = TESTS.parent / "mw"
FIX = TESTS / "fixtures"
BASE = "ea166565"
UBQ = (FIX / "public_1ubq.cif").read_bytes()
PHENOL = (FIX / "mutation_model/synthetic-phenol-ligand.sdf").read_bytes()
I44 = {"model_number": 1, "chain_auth": "A", "seq_auth": 44, "icode": "", "resname": "ILE"}
TRP, ALA = "ACDEFGHKLMNPQRSTVWY".index("W"), 0      # M20 candidate order at I44 (I excluded)
FAST = {"seed": 20261007, "exhaustiveness": 1, "num_modes": 2}
ACK = {key: True for key in DC.ACKNOWLEDGEMENT_KEYS}
SO1_TEXT = "이 결과의 구조는 보완 구조이다. 일부 잔기와 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다."
JW1_TEXT = "이 후보는 보완 구조 기준이며, 전송 본문은 이 사실을 담지 않는다."
SO1 = {"id": "SO1", "text": SO1_TEXT}
JW1 = {"id": "JW1", "text": JW1_TEXT}
M29_KEYS = {"structure_origin", "repair_warning", "repair_handoff", "modeled_basis", "reference_not_checked"}
FORBIDDEN_OUTSIDE = (SO1_TEXT, JW1_TEXT, "structure_origin", "repair_warning")


# --------------------------------------------------------------------------------------------------- inputs and world
def synthetic_1ubq_without_a48_nz() -> bytes:
    """SYNTHETIC: public 1UBQ without residue A48 LYS atom NZ (all else as published)."""
    doc = gemmi.cif.read_string(UBQ.decode())
    table = doc.sole_block().find("_atom_site.", ["auth_asym_id", "auth_seq_id", "label_atom_id"])
    rows = [index for index in range(len(table)) if (table[index][0], table[index][1], table[index][2]) ==
            ("A", "48", "NZ")]
    assert len(rows) == 1
    table.remove_row(rows[0])
    head, rest = doc.as_string().split("\n", 1)
    note = "# SYNTHETIC TEST INPUT (M29 T8b): public 1UBQ without A48 LYS NZ; not an experimental structure\n"
    return (head + "\n" + note + rest).encode()


def _post_job(client: TestClient, rid: str, protocol: str, args: dict, timeout_s: float) -> dict:
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args, "timeout_s": timeout_s})
    assert submitted.status_code == 200, submitted.text
    started = client.post(f"/runs/{rid}/jobs/{submitted.json()['job_id']}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{submitted.json()['job_id']}/start")
    assert started.status_code == 200, started.text
    done = started.json()
    assert done["status"] == "done", done
    return done


def _chain(client: TestClient, fake: Fake, label: str, raw: bytes, name: str, *, repair: bool) -> dict[str, Any]:
    """One run: prepared structure (repaired when asked), M20 set, M21 model, M18 docking, projection, send, loop."""
    built = F.world(client, label, raw, name)
    rid, w = built["rid"], {"rid": built["rid"], "prepared": built["structure"]}
    if repair:
        done = F.run_job(client, rid, F.args(built["structure"]))
        assert done["status"] == "done", done
        w["record"], w["structure"] = done["output_handles"]
        w["original_set"] = F.command(client, rid, "generate_mutation_candidates", {
            "structure": built["structure"], "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}})
    else:
        w["structure"] = built["structure"]
    w["set"] = F.command(client, rid, "generate_mutation_candidates", {
        "structure": w["structure"], "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}})
    model = _post_job(client, rid, MC.PROTOCOL, {"candidate_set": w["set"], "candidate_index": TRP, "seed": 20261004,
                                                 "selection_policy": "protein_only",
                                                 "hydrogen_policy": "rebuild_pH7"}, 120)
    w["model"] = model["artifacts"]["mutation_model"]
    imported = client.post(f"/runs/{rid}/chemical/imports", params={"kind": "ligand_sdf", "filename": "phenol.sdf"},
                           content=PHENOL, headers={"content-type": "application/octet-stream"})
    assert imported.status_code == 201, imported.text
    w["sdf"] = imported.json()["handle"]
    dock = _post_job(client, rid, DC.PROTOCOL, {
        "ligand": {"source": "sdf", "sdf_handle": w["sdf"]}, "mode": "free",
        "box": {"source": "ligand_range", "margin_A": 8}, "parameters": dict(FAST), "acknowledgement": ACK,
        "receptor_source": {"kind": "mutation_model", "mutation_model": w["model"], "side": "mutant"}}, 600)
    w["dock"] = dock["output_handles"][0]
    w["projection"] = F.command(client, rid, J.TOOL, {"source": w["set"], "candidates": [TRP, ALA]})
    assert client.post(f"/runs/{rid}/jev/consent", json={"enabled": True}).status_code == 200
    preview = client.post(f"/runs/{rid}/jev/preview", json={"projection": w["projection"]})
    assert preview.status_code == 200, preview.text
    w["preview"] = preview.json()
    sent = len(fake.requests)
    send = client.post(f"/runs/{rid}/jev/sends", json={"send_id": str(uuid.uuid4()), "projection": w["projection"],
                                                       "body_sha256": w["preview"]["body_sha256"],
                                                       "confirm": J.CONFIRM})
    assert send.status_code == 200, send.text
    w["send"] = send.json()
    assert w["send"]["status"] == "completed", w["send"]
    assert len(fake.requests) == sent + 1
    w["wire"] = fake.requests[-1].content
    w["loop"] = str(uuid.uuid4())
    loop = client.post(f"/runs/{rid}/jev_loops", headers={"content-type": "application/json"}, content=json.dumps({
        "loop_id": w["loop"], "branch": "protein", "pool": {"source": w["set"], "candidates": [TRP, ALA],
                                                             "filter": None},
        "goal": "explore", "loop_seed": 11, "iteration_cap": 2,
        "setup": {"ligand": {"source": "sdf", "sdf_handle": w["sdf"]}, "box": {"source": "ligand_range",
                                                                            "margin_A": 8},
                  "parameters": dict(FAST), "selection_policy": "protein_only", "hydrogen_policy": "rebuild_pH7",
                  "acknowledgement": ACK}}).encode())
    assert loop.status_code == 200, loop.text
    w["loop_created"] = loop.json()
    # the M25 protein loop's first send projection (real tool); it is previewed, not sent
    w["loop_projection"] = F.command(client, rid, "build_jev_loop_projection", {"loop_id": w["loop"], "iteration": 1})
    # LABELLED STAND-IN for the M23 summary (see the module docstring): it names the run's candidate set only.
    w["ga"] = api_module._run(rid).store.put(SC.OUTPUT_KIND, SC.SUMMARY_SCHEMA, {
        "schema": SC.SUMMARY_SCHEMA, "candidate_set": w["set"],
        "note": "SYNTHETIC STAND-IN (M29 T8b response-layer test); not a sequence GA output"}).handle
    return w


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("m29_t8b") / "runs"
    patch = pytest.MonkeyPatch()
    saved = api_module.RUNS_DIR
    rids: list[str] = []
    try:
        client = F.client(root, patch)
        fake = Fake(lambda request: reply("m01"))
        patch.setattr(api_module, "SCIENCE_GATE", fake.gate)

        def refused(*_args, **_kwargs):
            raise AssertionError("no socket may be opened: the JEV exchange is an httpx.MockTransport")
        patch.setattr(socket.socket, "connect", refused)
        patch.setattr(socket, "create_connection", refused)
        ACTIVE_SENDS.clear()
        out: dict[str, Any] = {"root": root, "fake": fake}
        for key, label, raw, name, repair in (
                ("repaired", "M29 T8b repaired downstream reads (SYNTHETIC 1UBQ edit)", synthetic_1ubq_without_a48_nz(),
                 "SYNTHETIC-1ubq-A48-NZ-removed.cif", True),
                ("plain", "M29 T8b plain downstream reads (public 1UBQ)", UBQ, "public_1ubq.cif", False)):
            try:
                out[key] = _chain(client, fake, label, raw, name, repair=repair)
            finally:
                rids.extend(path.name for path in root.iterdir()
                            if (path / "events.jsonl").is_file() and path.name not in rids)
                for rid in rids:
                    F.kill_leftovers(root, rid)
        return out
    finally:
        ACTIVE_SENDS.clear()
        patch.undo()
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()


class _GitSource(importlib.abc.SourceLoader):
    """A module's source as it was at commit ``BASE`` (``git show``); nothing is written."""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.source = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE}:{rel}"], capture_output=True,
                                     check=True).stdout

    def get_filename(self, fullname: str) -> str:
        return f"<{BASE}:{self.rel}>"

    def get_data(self, path: str) -> bytes:
        return self.source


def _baseline_module(rel: str, name: str) -> Any:
    """The module ``rel`` of commit ``BASE`` under ``name`` (a sibling of the current module, so its relative imports
    are the current package's)."""
    spec = importlib.util.spec_from_loader(name, _GitSource(rel))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def baseline_app():
    """The ``ea166565`` app with the ``ea166565`` M20 / M21 / M18 read modules; every other module is the current one
    (unchanged on these read paths since then)."""
    app = _baseline_module("backend/mw/api/app.py", "mw.api._t8b_baseline_app")
    for name in ("mutation_reads", "mutation_model_reads", "docking_reads"):
        setattr(app, name, _baseline_module(f"backend/mw/{name}.py", f"mw._t8b_baseline_{name}"))
    return app


def _serve(module: Any, root: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(module, "RUNS_DIR", root)
    monkeypatch.setattr(module, "SCIENCE_GATE", Fake(lambda request: reply("m01")).gate)
    module.RUNS.clear()
    return TestClient(module.app, base_url="http://127.0.0.1")


@pytest.fixture
def client(world, monkeypatch):
    return _serve(api_module, world["root"], monkeypatch)


def _stand_in_list(run, offset, limit):
    handles = [event["handle"] for event in run.events.read()
               if event["type"] == "object_created" and event.get("kind") == SC.OUTPUT_KIND]
    rows = [{"handle": handle, "published_seq": None, "valid": True, "reason_code": None,
             **{key: run.store.load(handle)["candidate_set"] if key == "candidate_set" else "stand-in"
                for key in sequence_ga_reads.LIST_FIELDS}} for handle in handles]
    return {"schema": "sequence_ga_list@1", "total": len(rows), "offset": offset, "limit": limit, "rows": rows}


@pytest.fixture
def stand_in(monkeypatch):
    """LABELLED STAND-IN answers of the M23 read functions (see the module docstring)."""
    monkeypatch.setattr(sequence_ga_reads, "list_summaries", _stand_in_list)
    monkeypatch.setattr(sequence_ga_reads, "summary_detail", lambda run, handle: {
        "schema": "sequence_ga_detail@1", "handle": handle, "summary": run.store.load(handle)})
    monkeypatch.setattr(sequence_ga_reads, "individual", lambda run, handle, key: {
        "schema": "sequence_ga_individual@1", "summary_handle": handle, "key": key})


def _reads(w: dict[str, Any]) -> list[tuple[str, str, dict[str, Any] | None]]:
    """(name, url, json body or None for a GET) of every read this task touches, for one run."""
    rid = w["rid"]
    base = f"/runs/{rid}"
    sets = f"{base}/mutation_candidate_sets/{w['set']}"
    return [("m20_list", f"{base}/mutation_candidate_sets", None), ("m20_detail", sets, None),
            ("m20_positions", f"{sets}/positions", None), ("m20_candidates", f"{sets}/candidates", None),
            ("m21_list", f"{base}/mutation_models", None), ("m21_detail", f"{base}/mutation_models/{w['model']}", None),
            ("m18_list", f"{base}/docking/results", None),
            ("m18_detail", f"{base}/docking/results/detail?handle={w['dock']}", None),
            ("m23_list", f"{base}/sequence_ga/results", None),
            ("m23_detail", f"{base}/sequence_ga/results/{w['ga']}", None),
            ("m23_individual", f"{base}/sequence_ga/results/{w['ga']}/individual?key=wild_type", None),
            ("jev_preview", f"{base}/jev/preview", {"projection": w["projection"]}),
            ("loop_preview", f"{base}/jev/preview", {"projection": w["loop_projection"]}),
            ("jev_sends", f"{base}/jev/sends", None),
            ("jev_send", f"{base}/jev/sends/{w['send']['send_id']}", None),
            ("loops", f"{base}/jev_loops", None), ("loop", f"{base}/jev_loops/{w['loop']}", None)]


def _get(client: TestClient, url: str, body: dict[str, Any] | None):
    return client.get(url) if body is None else client.post(url, json=body)


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in M29_KEYS}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def _state(root: Path, rid: str) -> tuple[bytes, list[str]]:
    return ((root / rid / "events.jsonl").read_bytes(),
            sorted(str(path.relative_to(root)) for path in (root / rid).rglob("*") if path.is_file()))


def _expected_origin(world: dict[str, Any]) -> dict[str, Any]:
    """From the job's output handles and the stored record (never from a read answer)."""
    w = world["repaired"]
    run = new_run(world["root"], run_id=w["rid"], dry_run=False)
    record = run.store.load(w["record"])
    manifest = run.store.load(run.store.load(w["structure"])["manifest"])
    assert manifest["repair"] == {"record": w["record"], "source": w["prepared"]}
    return {"repair_record": w["record"], "repaired_structure": w["structure"], "source_structure": w["prepared"],
            "counts": record["counts"], "statements": [SO1]}


# ------------------------------------------------------------------------------------------------------------- tests
def test_the_fixed_sentences_are_the_spec_text_from_the_constants():
    assert (K.SO1, K.JW1) == (SO1_TEXT, JW1_TEXT)
    assert structure_origin_reads.field({"repair_record": "r", "repaired_structure": "s", "source_structure": "o",
                                         "counts": {"added_atoms": 1}})["statements"] == [SO1]


def test_the_repaired_record_is_the_edit_one_nz_atom(world):
    record = new_run(world["root"], run_id=world["repaired"]["rid"], dry_run=False).store.load(
        world["repaired"]["record"])
    assert record["classes_applied"] == ["side_chain_atoms_added"]
    assert [(row["residue"]["chain_auth"], row["residue"]["seq_auth"], row["atom_name"])
            for row in record["added_atoms"]] == [("A", 48, "NZ")]
    assert (record["counts"]["added_atoms"], record["counts"]["added_residues"],
            record["counts"]["side_chain_residues"]) == (1, 0, 1)


def test_every_read_on_the_repaired_structure_carries_structure_origin(world, client, stand_in):
    expected = _expected_origin(world)
    w = world["repaired"]
    before = _state(world["root"], w["rid"])
    got = {}
    for name, url, body in _reads(w):
        response = _get(client, url, body)
        assert response.status_code == 200, (name, response.text)
        got[name] = response.json()
    for name in ("m20_detail", "m20_positions", "m21_detail", "m18_detail", "m23_detail", "m23_individual",
                 "jev_preview", "loop_preview", "jev_send", "loop"):
        assert got[name]["structure_origin"] == expected, name
    assert "structure_origin" not in got["m20_candidates"]   # the candidate page carries no field (the detail does)
    rows = {row["handle"]: row for row in got["m20_list"]["rows"]}
    assert rows[w["set"]]["structure_origin"] == expected and rows[w["set"]]["valid"] is True
    assert "structure_origin" not in rows[w["original_set"]]  # the unrepaired original: no key
    for name, key in (("m21_list", w["model"]), ("m18_list", w["dock"]), ("m23_list", w["ga"])):
        (row,) = [row for row in got[name]["rows"] if row["handle"] == key]
        assert row["structure_origin"] == expected and row["valid"] is True, name
    for name in ("jev_sends", "loops"):
        (row,) = got[name]
        assert row["structure_origin"] == expected, name
    assert got["jev_preview"]["repair_warning"] == JW1 and got["loop_preview"]["repair_warning"] == JW1
    assert got["loop_preview"]["loop"]["loop_id"] == w["loop"] and got["loop_preview"]["kind"] == "mutation"
    assert all('"repair_warning"' not in json.dumps(got[name]) for name in got if not name.endswith("preview"))
    assert _state(world["root"], w["rid"]) == before                    # reads write nothing


def test_the_approval_answer_carries_jw1_and_the_body_events_and_audit_do_not(world):
    rep, plain = world["repaired"], world["plain"]
    assert rep["send"]["repair_warning"] == JW1 and "structure_origin" not in rep["send"]
    assert "repair_warning" not in plain["send"]
    assert rep["preview"]["repair_warning"] == JW1 and "repair_warning" not in plain["preview"]
    # the wire is exactly the previewed body (spec 6.4: the body never says the structure was repaired)
    assert rep["wire"] == rep["preview"]["body"].encode("ascii")
    for text in (*FORBIDDEN_OUTSIDE, "repair", rep["record"], rep["structure"], rep["prepared"], SENTINEL):
        assert text.encode() not in rep["wire"], text
    assert len(world["fake"].requests) == 2     # one send per run, both to the MockTransport (no socket opened)
    shapes: dict[str, list[dict[str, list[str]]]] = {}
    for w in (rep, plain):
        log = (world["root"] / w["rid"] / "events.jsonl").read_bytes()
        for text in FORBIDDEN_OUTSIDE:
            assert text.encode() not in log, (w["rid"], text)
        events = [json.loads(line) for line in log.splitlines()]
        # the audit rows and the send events of the repaired run have the plain run's columns (nothing added)
        shapes[w["rid"]] = [{event["type"] + "/" + str(event.get("stage")): sorted(event)} for event in events
                            if event["type"] == "egress" or event["type"].startswith("jev_send")]
    assert shapes[rep["rid"]] and shapes[rep["rid"]] == shapes[plain["rid"]]


def test_unrepaired_reads_are_byte_identical_to_the_baseline_commit(world, baseline_app, stand_in, monkeypatch):
    w = world["plain"]
    current = _serve(api_module, world["root"], monkeypatch)
    old = _serve(baseline_app, world["root"], monkeypatch)
    before = _state(world["root"], w["rid"])
    for name, url, body in _reads(w):
        new, base = _get(current, url, body), _get(old, url, body)
        assert (new.status_code, base.status_code) == (200, 200), (name, new.text, base.text)
        assert new.content == base.content, name
        for text in FORBIDDEN_OUTSIDE:
            assert text.encode() not in new.content, (name, text)
    assert _state(world["root"], w["rid"]) == before


def test_repaired_reads_differ_from_the_baseline_commit_only_by_the_m29_fields(world, baseline_app, stand_in,
                                                                              monkeypatch):
    w = world["repaired"]
    current = _serve(api_module, world["root"], monkeypatch)
    old = _serve(baseline_app, world["root"], monkeypatch)
    for name, url, body in _reads(w):
        new, base = _get(current, url, body), _get(old, url, body)
        assert (new.status_code, base.status_code) == (200, 200), (name, new.text, base.text)
        assert not any(f'"{key}"' in base.text for key in M29_KEYS), name      # the baseline modules were served
        assert ('"structure_origin"' in new.text) == (name != "m20_candidates"), name
        assert json.dumps(_strip(new.json())) == json.dumps(base.json()), name


def test_the_m23_read_and_report_hash_files_are_unchanged():
    for rel in ("backend/mw/sequence_ga_reads.py", "backend/mw/sequence_ga_reports.py"):
        assert _blob((ROOT / rel).read_bytes()) == BASELINE_BLOBS[rel], rel
    # the M18 detail read the M23 individual read nests is unchanged too: the route adds the field
    source = (MW / "docking_reads.py").read_text()
    tree = ast.parse(source)
    detail = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "result_detail")
    assert "origin" not in ast.unparse(detail)


def test_the_nested_m18_detail_of_a_repaired_result_is_unchanged(world):
    w = world["repaired"]
    run = new_run(world["root"], run_id=w["rid"], dry_run=False)
    assert "structure_origin" not in docking_reads.result_detail(run, w["dock"])


def _unavailable():
    raise sr._unavailable()


def test_an_unavailable_environment_is_412_precondition_on_repaired_reads_only(world, client, stand_in, monkeypatch):
    """LABELLED FAULT: the installed template cannot be read (``openmm_unavailable``). M20's three reads answer 412
    instead of 500 (the T7 hand-over), like every other read of a result on a repaired structure."""
    monkeypatch.setattr(sr, "_templates", _unavailable)
    for name, url, body in _reads(world["repaired"]):
        response = _get(client, url, body)
        if name == "m20_candidates":
            assert response.status_code == 200, response.text      # no record check on this page
            continue
        assert response.status_code == 412, (name, response.status_code, response.text)
        assert response.json()["error"] == "precondition", name
        assert response.json()["detail"]["reason_code"] == "openmm_unavailable", name
    for name, url, body in _reads(world["plain"]):
        assert _get(client, url, body).status_code == 200, name


def test_a_record_that_no_longer_re_derives_shows_no_values(world, client, stand_in, monkeypatch):
    """LABELLED FAULT: the record does not re-derive (``repair_record_mismatch``, e.g. after an upgrade). List rows are
    ``valid: false`` with null fields; details and lists without row validity are 422 ``method_evidence_invalid``."""
    def mismatch(*_args, **_kwargs):
        raise ToolFailure(FailureClass.input_invalid, "record differs", detail={"reason_code": "repair_record_mismatch"})
    monkeypatch.setattr(sr, "validated_repair", mismatch)
    w = world["repaired"]
    got = {name: _get(client, url, body) for name, url, body in _reads(w)}
    for name in ("m20_detail", "m20_positions", "m21_detail", "m18_detail", "m23_detail", "m23_individual",
                 "jev_preview", "loop_preview", "jev_sends", "jev_send", "loops", "loop"):
        assert got[name].status_code == 422, (name, got[name].text)
        assert got[name].json()["detail"]["error"] == "method_evidence_invalid", name
        assert "counts" not in got[name].text and "structure_origin" not in got[name].text, name
    assert got["m20_candidates"].status_code == 200
    rows = {row["handle"]: row for row in got["m20_list"].json()["rows"]}
    assert rows[w["set"]]["valid"] is False and rows[w["set"]]["counts"] is None
    assert "structure_origin" not in rows[w["set"]] and rows[w["original_set"]]["valid"] is True
    for name, key, nulls in (("m21_list", w["model"], ("candidate", "structure", "parameters")),
                             ("m18_list", w["dock"], ("job_id", "method", "modes")),
                             ("m23_list", w["ga"], sequence_ga_reads.LIST_FIELDS)):
        (row,) = [row for row in got[name].json()["rows"] if row["handle"] == key]
        assert row["valid"] is False and "structure_origin" not in row, name
        assert all(row[field] is None for field in nulls), name
    assert got["m23_list"].json()["rows"][0]["reason_code"] == "evidence_invalid"
    for name, url, body in _reads(world["plain"]):
        assert _get(client, url, body).status_code == 200, name


def test_a_malformed_repair_link_is_origin_invalid_and_jw1_needs_only_the_mark(tmp_path):
    run = new_run(tmp_path, dry_run=False, run_id="run_m29_t8b_link")
    loaded = run.call("load_structure", {"source": "ubq.cif", "model_index": 0}, source_bytes=UBQ,
                      source_format="cif").handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    original = run.store.load(prepared)
    # LABELLED FAULT: the link names the coordinates object as its record
    manifest = {**run.store.load(original["manifest"]), K.MANIFEST_REPAIR_KEY: {"record": original["coordinates"],
                                                                                 "source": prepared}}
    manifest_handle = run.store.put(K.MANIFEST_KIND, K.MANIFEST_SCHEMA, manifest).handle
    broken = run.store.put(K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, {**original, "manifest": manifest_handle}).handle
    origins = structure_origin_reads.Origins(run.store)
    with pytest.raises(structure_origin_reads.OriginInvalid):
        origins.of_structure(broken)
    with pytest.raises(structure_origin_reads.OriginInvalid):   # stays invalid for the read (memo)
        origins.of_structure(broken)
    assert origins.of_structure(prepared) is None
    assert structure_origin_reads.warning(run.store, broken) == JW1      # the mark alone (the approval answer)
    assert structure_origin_reads.warning(run.store, prepared) is None
    for value in (None, 7, "obj://nowhere/prepared_structure/" + "0" * 64, {"a": 1}):
        assert structure_origin_reads.warning(run.store, value) is None
    with pytest.raises(structure_origin_reads.OriginInvalid):
        origins.of_candidate_set(prepared)                                # not a candidate set
    with pytest.raises(structure_origin_reads.OriginInvalid):
        origins.of_receptor_source({"kind": "import"})
    assert origins.of_receptor_source(None) is None


def _imports(rel: str) -> tuple[set[str], set[str]]:
    absolute, relative = set(), set()
    for node in ast.walk(ast.parse((MW / rel).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            absolute.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                absolute.add(node.module or "")
            else:
                relative.update(f"{'.' * node.level}{node.module or ''}{'.' if node.module else ''}{alias.name}"
                                for alias in node.names)
    return absolute, relative


def test_import_boundaries_of_the_new_module_and_its_importers():
    absolute, relative = _imports("structure_origin_reads.py")
    assert absolute == {"__future__", "typing"}
    assert relative == {".mutation_handoff", ".structure_repair_constants", ".core.errors.FailureClass",
                        ".core.errors.ToolFailure", ".structure_origin.is_repaired"}
    source = (MW / "structure_origin_reads.py").read_text(encoding="utf-8")
    for banned in ("raise_limits", "limit_approval", "subprocess", "jev_sends", "egress", "__import__", "API_KEY"):
        assert banned not in source, banned
    importers = sorted(path.relative_to(MW).as_posix() for path in MW.rglob("*.py")
                       if "structure_origin_reads" in path.read_text(encoding="utf-8")
                       and path.name != "structure_origin_reads.py")
    assert importers == ["api/app.py", "docking_reads.py", "mutation_model_reads.py", "mutation_reads.py"]
    for rel in ("jev_sends.py", "jev_loops.py", "jev_loop_store.py", "jev_loop_reports.py", "jev_reports.py",
                "sequence_ga_reads.py", "sequence_ga_reports.py"):
        assert "structure_origin" not in (MW / rel).read_text(encoding="utf-8"), rel
    code = ("import sys, mw.structure_origin_reads, mw.docking_reads, mw.mutation_model_reads, mw.mutation_reads\n"
            "print([m for m in ('httpx', 'mw.jev_sends', 'mw.egress', 'mw.jev_reports', 'rdkit', 'openmm', "
            "'pdbfixer', 'meeko') if m in sys.modules])\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_the_m20_handoff_verification_is_the_one_the_field_rides_on():
    """The field is built from ``mutation_handoff.validated_origin`` (the M20 admission's and reads' check), so a set
    the M20 admission accepted and the field agree on what a valid repaired structure is."""
    assert structure_origin_reads.mutation_handoff is mutation_handoff
    source = (MW / "structure_origin_reads.py").read_text(encoding="utf-8")
    assert "mutation_handoff.validated_origin(store, structure)" in source
