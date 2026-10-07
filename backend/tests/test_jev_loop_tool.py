"""M25 T4: the cheap tool ``build_jev_loop_projection`` -> ``jev_loop_projection@1`` and the M24 preview reading
loop projections (spec .dryforge/spec.md 3.2, 4.1-4.5, 5.1, 7, 9.1, 9.2, 11, 12).

One ligand scenario runs once per module through the product job lane with REAL engines (``JobQueue.submit`` /
``start`` / ``request_cancel``, the pinned docking worker and ``qvina2``; a missing engine FAILS, never skips) on the
T3 template run (``test_jev_loops_api._template``: real M17 RDKit jobs on the labelled synthetic small blocks, the public
prepared docking example receptor, real M20 sets of public 1UBQ). Outside any loop candidate A is docked by a standalone
M18 job (same call key: a stored, validated result) and B's same-key job is cancelled before it starts; then the loop
(exploit, cap 2, pool A-F) is created and its first projection built by the tool; iteration 1 docks C, iteration 2
docks D. The event log is kept after each stage and every test works on an events-only copy of one stage.

LABELLED stand-ins and fault injection (marked where used): the ``approve`` helper writes the T6 compute route's
approval event (the exact spec 6.1 payload); ``send_events`` writes the M24 approval / dispatch / outcome events the T5
send branch will write for a loop projection; ``proposal`` + a patched ``jev_loop_store.load_proposals`` stand in for
the T5 ``jev_loop_choice@1``; a synthetic ``jev_loop_ended`` event; lowered caps, a failing set check, a failing
structure parse and edited property-method strings.

Oracles: the send order / aliases / criteria from the independent standard-library oracle
``fixtures/jev_loop/independent_order.py``; neighbors and windows from the independent M24 oracle
``fixtures/jev/independent_neighbors.py`` (``expected.json``); scores read from the stored ``docking_result@1`` objects
themselves; the request body assembled here from the spec 4.5 wording; the reservation from the M24 formula written out.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import Fake
from ligand_job_fixture import new_ligand_run
from test_jev_loops_api import DRY_RID, FIX, RID, _template, ligand_body, protein_body
from test_jev_loops_read import approve, log_bytes

from mw import docking_bundle, jev_loop_store, ligand_bundle
from mw import docking_constants as DC
from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loop_projection as LP
from mw import jev_projection as P
from mw import jev_sends as S
from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.tools import jev as m24_tool
from mw.tools import jev_loop as tool_module
from mw.workspace import CONFIG, build_registry

MW = Path(__file__).resolve().parents[1] / "mw"
TOOL = L.TOOL
LOOP = "4f9a3d91-6e40-4ebc-8d84-9d5a4c3e0f44"
CENTER = json.loads((FIX / "docking/expected.json").read_text())["public_example_box"]["center_A"]
SMALL_BOX = {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]}
FAST = {"seed": 1, "exhaustiveness": 1, "num_modes": 2}
JSON = {"content-type": "application/json"}
EXPECTED = json.loads((FIX / "jev/expected.json").read_text())["structures"]
REASON_CLASS = {"unknown_field": "input_invalid", "loop_not_found": "input_invalid", "loop_ended": "precondition",
                "iteration_mismatch": "precondition", "selection_done": "precondition",
                "phase_invalid": "precondition", "cap_reached": "precondition", "too_few_candidates": "precondition",
                "source_invalid": "input_invalid", "structure_unavailable": "input_invalid",
                "wire_field_invalid": "input_invalid", "payload_too_large": "resource_exceeded",
                "projection_invalid": "input_invalid"}   # spec 4.1: input / existence 422, loop state 412, size 429
HTTP = {"input_invalid": 422, "precondition": 412, "resource_exceeded": 429}
M24_PREVIEW_KEYS = {"schema", "projection_handle", "kind", "source", "question", "body", "body_sha256", "body_bytes",
                    "selection", "selection_sent", "reservation", "send_cap", "used", "remaining", "budget_remaining",
                    "blocked_by", "previous_sends"}
FORBIDDEN_WORDS = ("점수", "순위", "추천", "최적", "개선", "안정성", "ΔΔG", "친화도", "활성", "예측", "안전", "유망")

_spec = importlib.util.spec_from_file_location("jev_loop_independent_order",
                                               FIX / "jev_loop/independent_order.py")
ORDER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ORDER)


# ---------------------------------------------------------------- the scenario (built once)


def _scenario(root: Path) -> dict:
    world = _template(root)
    run = new_ligand_run(root, RID)        # reopened from its events: the M17 jobs approved expensive calls
    source = world["ligand_set"]
    a, b, c, d, e, f = world["ids"][:6]
    raw_setup = {**ligand_body(world)["setup"], "box": SMALL_BOX, "parameters": FAST}
    setup = jev_loop_store.normalize_setup("ligand", raw_setup, source)
    pins = docking_bundle.require_ready()
    keys = {ref: jev_loop_store.ligand_call_key(setup, source, ref, pins) for ref in (a, b, c, d, e, f)}
    queue = JobQueue(run)

    def submit(ref):
        job = queue.submit(DC.PROTOCOL, jev_loop_store.ligand_request(setup, source, ref),
                           timeout_s=L.STEP_TIMEOUT_DEFAULTS_S["ligand_dock"])
        assert job["call_key"] == keys[ref] and job["status"] == "queued", job
        return job["job_id"]

    out = {"world": world, "root": root, "refs": (a, b, c, d, e, f), "keys": keys, "raw_setup": raw_setup,
           "logs": {}, "handles": {}}
    done = queue.start(submit(a))                                   # outside any loop: a stored, validated result
    assert done["status"] == "done", done
    out["handles"]["a"] = done["output_handles"][0]
    assert queue.request_cancel(submit(b))["job"]["status"] == "cancelled"   # outside any loop: never started
    out["logs"]["pre"] = log_bytes(run)
    body = ligand_body(world, loop_id=LOOP, goal="exploit", iteration_cap=2, loop_seed=7)
    body["pool"]["candidates"] = [f, e, d, c, b, a]
    body["setup"] = raw_setup
    jev_loop_store.create(run, body, send_active=False)
    out["projection"] = run.call(TOOL, {"loop_id": LOOP, "iteration": 1}).handle
    out["logs"]["select1"] = log_bytes(run)
    approve(run, LOOP, 1, "ligand_dock", c, keys[c])
    job_c = submit(c)
    out["logs"]["running1"] = log_bytes(run)
    done = queue.start(job_c)
    assert done["status"] == "done", done
    out["handles"]["c"] = done["output_handles"][0]
    out["logs"]["select2"] = log_bytes(run)
    approve(run, LOOP, 2, "ligand_dock", d, keys[d])
    done = queue.start(submit(d))
    assert done["status"] == "done", done
    out["handles"]["d"] = done["output_handles"][0]
    out["logs"]["capped"] = log_bytes(run)
    out["objects"] = {out["projection"]: (run.run_dir / "objects" /
                                          f"{out['projection'].rsplit('/', 1)[1]}.json").read_bytes()}
    out["dry_log"] = (root / DRY_RID / "events.jsonl").read_bytes()
    return out


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    return _scenario(tmp_path_factory.mktemp("jev_loop_tool"))


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    S.ACTIVE_SENDS.clear()


def _open(scenario, path: Path, monkeypatch, stage: str) -> dict:
    """An events-only copy of one stage served by the API (Fake science gate: no socket, counted key reads) with the
    tool implementation counted."""
    root = path / f"runs_{stage}"
    for rid, raw in ((RID, scenario["logs"][stage]), (DRY_RID, scenario["dry_log"])):
        (root / rid).mkdir(parents=True)
        (root / rid / "events.jsonl").write_bytes(raw)
    fake = Fake()
    calls: list[dict] = []
    impl = api_module.REGISTRY.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    monkeypatch.setitem(api_module.REGISTRY.impls, TOOL, counted)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    monkeypatch.setattr(api_module, "SCIENCE_GATE", fake.gate)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    return {"root": root, "run": api_module._run(RID), "client": client, "fake": fake, "calls": calls}


def _log(world) -> bytes:
    return (world["root"] / RID / "events.jsonl").read_bytes()


def _events(run, kind=None) -> list[dict]:
    return [event for event in run.events.read() if kind is None or event["type"] == kind]


def _projections(run) -> list[str]:
    return [event["handle"] for event in _events(run, "object_created") if event["kind"] == L.PROJECTION_KIND]


def _call(world, iteration=1, loop_id=LOOP, **extra):
    return world["run"].call(TOOL, {"loop_id": loop_id, "iteration": iteration, **extra})


def _refused(world, args, reason, run=None) -> ToolFailure:
    """A pre-check refusal: one ``proposal_rejected`` event, no tool call, no implementation call, no object."""
    run = run or world["run"]
    before, made, called = len(_events(run)), len(_projections(run)), len(world["calls"])
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.detail["reason_code"] == reason, (reason, caught.value.detail, caught.value.message)
    assert caught.value.cls == FailureClass(REASON_CLASS[reason])
    new = [event["type"] for event in _events(run)[before:] if event["type"] != "wall_charged"]
    assert new == ["proposal_rejected"], new
    assert len(world["calls"]) == called and len(_projections(run)) == made
    return caught.value


def _first_mode(run, handle):
    """The stored first-mode qvina score, read from the stored object itself (not through any loop code)."""
    modes = run.store.load(handle)["modes"]
    return modes[0]["score_kcal_mol"] if modes else None


def _oracle(scenario, iteration, send_ordinal, *, computed, unavailable, refs=None, seed=7):
    stored = list(refs or scenario["refs"])
    return ORDER.case("t4", "ligand", stored, seed, iteration, send_ordinal, computed=list(computed),
                      unavailable=list(unavailable))


def _alias_of(content, ref):
    return next(item["alias"] for item in content["selection"] if item["ref"] == ref)


def send_events(run, projection, *, status="failed", dispatched=True, choice=None, late=False) -> str:
    """LABELLED SYNTHETIC stand-in for the T5 send branch: the M24 approval / dispatch / outcome events of one send of
    a loop projection (nothing is sent; no audit row, reservation or key read)."""
    content = run.store.load(projection)
    send_id = str(uuid.uuid4())
    audit_id = f"eg_{uuid.uuid4().hex}"
    run.events.append(J.EVENT_APPROVED, send_id=send_id, projection_handle=projection,
                      body_sha256=content["body_sha256"], question_id=content["question"]["id"],
                      source_handle=content["source"]["handle"], selection_count=len(content["selection"]),
                      approved_by=J.APPROVED_BY)
    if dispatched:
        run.events.append(J.EVENT_DISPATCH, send_id=send_id, audit_id=audit_id)
    reason = None if status == "completed" else "provider_http_error" if dispatched else "consent_off"
    run.events.append(J.EVENT_OUTCOME, send_id=send_id, status=status, reason_code=reason,
                      audit_id=audit_id if dispatched else None, requested_model=J.REQUEST_MODEL,
                      served_model=J.SERVED_SNAPSHOT if status == "completed" else None, choice_handle=choice,
                      usage=None, late=late, late_reason="consent_off" if late else None)
    return send_id


def proposal(monkeypatch, run, projection, ref, *, late=False) -> str:
    """LABELLED SYNTHETIC stand-in for a T5 ``jev_loop_choice@1``: a completed send of ``projection`` whose validated
    proposal chose ``ref`` (``jev_loop_store.load_proposals`` is patched to return it; T5 stores the real object)."""
    content = run.store.load(projection)
    handle = f"obj://{run.run_id}/{L.CHOICE_KIND}/" + hashlib.sha256(projection.encode()).hexdigest()
    send_id = send_events(run, projection, status="completed", choice=handle, late=late)
    criteria = LP.criteria_aliases(content)
    chosen = {
        "loop": dict(content["loop"]), "send": {"send_id": send_id}, "arrival": {"late": late},
        "answer": {"local_ref": {"candidate_id": ref}, "list_position": criteria.index(_alias_of(content, ref)) + 1,
                   "list_size": len(criteria)}}
    monkeypatch.setattr(jev_loop_store, "load_proposals", lambda view, created: {handle: chosen})
    return handle


def ended(run, loop_id=LOOP) -> None:
    """LABELLED SYNTHETIC ``jev_loop_ended`` (the T6 end route writes the real one with its summary handle)."""
    run.events.append(L.EVENT_ENDED, loop_id=loop_id, end_reason="ended_by_user",
                      result_handle=f"obj://{run.run_id}/{L.RESULT_KIND}/" + "e" * 64)


def _protein_loop(scenario, world, goal, pool):
    body = protein_body({"ubq_set": scenario["world"]["ubq_set"], "phenol": scenario["world"]["phenol"],
                         "indexes": scenario["world"]["indexes"]}, goal=goal, loop_seed=11, iteration_cap=3)
    body["pool"]["candidates"] = pool
    record = jev_loop_store.create(world["run"], body, send_active=False)
    return record["loop_id"]


# ---------------------------------------------------------------- registration


def test_registered_in_the_four_places_with_a_precheck():
    import yaml

    spec = next(t for t in yaml.safe_load((CONFIG / "tools.yaml").read_text())["tools"] if t["name"] == TOOL)
    assert spec["level"] == "L2" and spec["version"] == L.TOOL_VERSION == "1" and spec["cost_class"] == "cheap"
    assert spec["emits"] == L.PROJECTION_KIND and "accepts" not in spec
    assert set(spec["params"]) == set(L.TOOL_ARGUMENTS) == {"loop_id", "iteration"}
    assert spec["params"]["loop_id"] == {"type": "str", "required": True}
    assert spec["params"]["iteration"] == {"type": "int", "required": True}
    assert not any(word in spec["description"] for word in FORBIDDEN_WORDS)
    reg = build_registry()
    assert TOOL in reg.impls and reg.prechecks[TOOL] is tool_module.precheck and TOOL not in reg.unavailable
    assert reg.specs[TOOL].idempotent is True
    assert TOOL in api_module.SUPPORTED_TOOLS and TOOL in api_module.REGISTRY.impls
    assert "jev_loop.register(reg)" in (MW / "workspace.py").read_text()


def test_the_registered_tool_makes_both_loop_branches_available(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "pre")
    tools = {t["name"]: t for t in world["client"].get("/tools", params={"levels": "L2"}).json()}
    assert tools[TOOL]["emits"] == L.PROJECTION_KIND and tools[TOOL]["cost_class"] == "cheap"
    loop = world["client"].get("/capabilities").json()["methods"]["jev_loop"]
    assert loop == {branch: {"available": True, "reason_code": None, "reason": None} for branch in L.BRANCHES}


# ---------------------------------------------------------------- stored projections from the real loop record


def test_ligand_projection_is_the_loop_record_shuffled_and_extended(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    run = world["run"]
    a, b, c, d, e, f = scenario["refs"]
    handle = scenario["projection"]
    content = run.store.load(handle)
    assert LP.validated_loop_projection(content) == content
    # Spec 4.3 against the independent oracle: A is computed (stored result), B unavailable (never sent).
    oracle = _oracle(scenario, 1, 0, computed=[a], unavailable=[b])
    assert [(item["alias"], item["ref"]) for item in content["selection"]] == [
        (item["alias"], item["ref"]) for item in oracle["aliases"]]
    assert LP.criteria_aliases(content) == oracle["criteria"]
    assert {item["ref"]: item["state"] for item in content["selection"]} == {
        a: "scored", c: "pending", d: "pending", e: "pending", f: "pending"}
    assert b not in {item["ref"] for item in content["selection"]} and len(content["wire"]["candidates"]) == 5
    # exploit computed rows: the stored first-mode value exactly (read from the stored object, no rounding)
    score_a = _first_mode(run, scenario["handles"]["a"])
    assert type(score_a) is float
    assert content["wire"]["computed"] == [{"alias": _alias_of(content, a), "state": "scored",
                                            "score_kcal_mol": score_a}]
    # candidate fields are the M24 allow-listed fields of the same stored candidates
    set_content, inspection = ligand_bundle.validated_candidate_set(run, scenario["world"]["ligand_set"])
    base, base_selection = P.build_ligand_wire(set_content, [a, c, d, e, f], inspection=inspection)
    m24 = {item["candidate_id"]: candidate for item, candidate in zip(base_selection, base["candidates"],
                                                                      strict=True)}
    for item, candidate in zip(content["selection"], content["wire"]["candidates"], strict=True):
        assert candidate == {**m24[item["ref"]], "alias": item["alias"]}
    assert content["wire"]["parent"] == base["parent"] and content["wire"]["goal"] == "exploit"
    assert content["wire"]["values_note"] == L.VALUES_NOTES[("ligand", "exploit")]
    assert content["loop"] == {"loop_id": LOOP, "iteration": 1, "send_ordinal": 0}
    assert content["order"] == {"algorithm": "sha256_order_v1", "loop_seed": 7, "iteration": 1, "send_ordinal": 0}
    assert content["source"] == {"handle": scenario["world"]["ligand_set"], "schema": "ligand_candidate_set@1"}
    assert content["structure"] is None and content["kind"] == "ligand" and content["goal"] == "exploit"
    assert content["question"] == {"id": "ligand_loop_choice@1", "key": "candidate_choice"}
    assert content["limitations"] == [L.STATEMENTS[name] for name in ("LJ1", "LJ2", "LJ3", "LJ4", "LJ6")]
    wire_text = canonical_json(content["wire"]).decode()
    for secret in (LOOP, "obj://", RID, "loop_seed", '"iteration"', b, scenario["keys"][a]):
        assert secret not in wire_text, secret
    meta = run.store.meta(handle)
    assert meta["summary"] == {"kind": "ligand", "loop_id": LOOP, "iteration": 1, "send_ordinal": 0,
                               "selection_count": 5, "body_bytes": content["body_bytes"],
                               "body_sha256": content["body_sha256"]}
    called = [event for event in _events(run, "tool_called") if event["tool"] == TOOL]
    assert [event["args"] for event in called] == [{"loop_id": LOOP, "iteration": 1}]
    assert world["fake"].requests == [] and world["fake"].key_reads == 0


def test_explore_sends_only_the_aliases_of_computed_candidates(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "pre")
    run = world["run"]
    a, b, c, d, _e, _f = scenario["refs"]
    body = ligand_body(scenario["world"], goal="explore", loop_seed=0, iteration_cap=3)
    body["pool"]["candidates"] = [d, c, b, a]
    body["setup"] = scenario["raw_setup"]
    loop_id = jev_loop_store.create(run, body, send_active=False)["loop_id"]
    out = _call(world, loop_id=loop_id)
    content = run.store.load(out.handle)
    oracle = _oracle(scenario, 1, 0, computed=[a], unavailable=[b], refs=[a, b, c, d], seed=0)
    assert [item["ref"] for item in content["selection"]] == oracle["order"]
    assert content["wire"]["computed"] == [{"alias": _alias_of(content, a)}]     # aliases only, no score or state
    assert "score_kcal_mol" not in canonical_json(content["wire"]).decode()
    assert content["wire"]["values_note"] == L.VALUES_NOTES[("ligand", "explore")]
    assert content["limitations"] == [L.STATEMENTS[name] for name in ("LJ1", "LJ2", "LJ3", "LJ5", "LJ6")]
    assert world["calls"] == [{"loop_id": loop_id, "iteration": 1}]


def test_a_candidate_this_loop_computed_is_sent_with_its_stored_score(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select2")
    run = world["run"]
    a, b, c, d, e, f = scenario["refs"]
    content = run.store.load(_call(world, iteration=2).handle)
    oracle = _oracle(scenario, 2, 0, computed=[a, c], unavailable=[b])
    assert [item["ref"] for item in content["selection"]] == oracle["order"]
    assert LP.criteria_aliases(content) == oracle["criteria"]
    scores = {a: _first_mode(run, scenario["handles"]["a"]), c: _first_mode(run, scenario["handles"]["c"])}
    assert all(type(value) is float for value in scores.values())
    expected = [{"alias": item["alias"], "state": "scored", "score_kcal_mol": scores[item["ref"]]}
                for item in content["selection"] if item["ref"] in scores]   # wire order
    assert content["wire"]["computed"] == expected
    assert {item["ref"]: item["state"] for item in content["selection"]} == {
        a: "scored", c: "scored", d: "pending", e: "pending", f: "pending"}
    assert content["loop"] == {"loop_id": LOOP, "iteration": 2, "send_ordinal": 0}


def test_same_input_gives_the_same_handle_and_one_build(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    run = world["run"]
    again = _call(world)                     # the scenario built it in the original run: a cache hit after replay
    assert again.handle == scenario["projection"] and world["calls"] == []
    called = [event for event in _events(run, "tool_called") if event["tool"] == TOOL][-1]
    hits = [event for event in _events(run, "cache_hit") if event["tool"] == TOOL]
    assert [hit["key"] for hit in hits] == [called["key"]]
    world2 = _open(scenario, tmp_path, monkeypatch, "select2")   # a new state: built once, then cached
    first, second = _call(world2, iteration=2), _call(world2, iteration=2)
    assert first.handle == second.handle and len(world2["calls"]) == 1
    assert first.handle != scenario["projection"]


def test_every_dispatched_send_gets_a_new_order(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    run = world["run"]
    a, b = scenario["refs"][:2]
    orders, handles = [], []
    for ordinal in range(3):
        out = _call(world)
        content = run.store.load(out.handle)
        assert content["loop"]["send_ordinal"] == content["order"]["send_ordinal"] == ordinal
        oracle = _oracle(scenario, 1, ordinal, computed=[a], unavailable=[b])
        assert [(item["alias"], item["ref"]) for item in content["selection"]] == [
            (item["alias"], item["ref"]) for item in oracle["aliases"]]
        assert [item["alias"] for item in content["selection"]] == [f"c0{n}" for n in range(1, 6)]
        orders.append([item["ref"] for item in content["selection"]])
        handles.append(out.handle)
        send_events(run, out.handle)                    # dispatched, then failed: the next send is reshuffled
    assert len({tuple(order) for order in orders}) == 3 and len(set(handles)) == 3
    # a send refused before dispatch uses no ordinal: the same projection is sent again under a new send_id
    current = _call(world).handle
    send_events(run, current, status="rejected", dispatched=False)
    assert _call(world).handle == current
    # a late proposal is no selection (spec 5.3): the iteration stays open and the next send is reshuffled
    late = _call(world).handle
    proposal(monkeypatch, run, late, scenario["refs"][2], late=True)
    content = run.store.load(_call(world).handle)
    assert content["loop"]["send_ordinal"] == 4


# ---------------------------------------------------------------- admission (spec 4.1 order, first failure only)


def test_unknown_field_then_loop_not_found(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    _refused(world, {"loop_id": 5, "iteration": "x", "rank": 1}, "unknown_field")
    _refused(world, {"loop_id": LOOP, "iteration": 1, "candidates": []}, "unknown_field")
    for loop_id in (str(uuid.uuid4()), "not-a-uuid", LOOP.upper(), None, 5, ["x"], {"a": 1}):
        _refused(world, {"loop_id": loop_id, "iteration": 1}, "loop_not_found")
    _refused(world, {"iteration": 1}, "loop_not_found")
    # loop_not_found comes before the loop-state checks (a wrong iteration as well)
    _refused(world, {"loop_id": str(uuid.uuid4()), "iteration": 9}, "loop_not_found")


def test_dry_run_runs_the_cheap_tool_but_hold_no_loop(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    dry = api_module._run(DRY_RID)
    assert dry.dry_run is True
    _refused(world, {"loop_id": LOOP, "iteration": 1}, "loop_not_found", run=dry)
    response = world["client"].post(f"/runs/{DRY_RID}/commands",
                                    json={"tool": TOOL, "args": {"loop_id": LOOP, "iteration": 1}})
    assert response.status_code == 422 and response.json()["detail"] == {"reason_code": "loop_not_found"}
    assert not [event for event in _events(dry) if event["type"] in ("tool_called", "budget_reserved")]


def test_loop_ended_comes_before_the_iteration(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    ended(world["run"])
    for iteration in (1, 2, "1", None):
        _refused(world, {"loop_id": LOOP, "iteration": iteration}, "loop_ended")


def test_iteration_mismatch(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    for iteration in (0, 2, 9, -1, "1", True, 1.0, None, [1]):
        _refused(world, {"loop_id": LOOP, "iteration": iteration}, "iteration_mismatch")
    _refused(world, {"loop_id": LOOP}, "iteration_mismatch")
    later = _open(scenario, tmp_path / "later", monkeypatch, "select2")   # iteration 1 is done: the current is 2
    _refused(later, {"loop_id": LOOP, "iteration": 1}, "iteration_mismatch")


def test_selection_done_comes_before_phase_invalid(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    run = world["run"]
    proposal(monkeypatch, run, scenario["projection"], scenario["refs"][3])
    record = jev_loop_store.read_loop(jev_loop_store.LoopReadView(run), LOOP,
                                      budget=jev_loop_store.remaining_budget(run.budget_snapshot())).record
    assert record["current"]["phase"] == "awaiting_compute"   # phase_invalid would hold too; selection_done is first
    _refused(world, {"loop_id": LOOP, "iteration": 1}, "selection_done")


def test_phase_invalid_while_the_approved_job_waits(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "running1")
    _refused(world, {"loop_id": LOOP, "iteration": 1}, "phase_invalid")
    _refused(world, {"loop_id": LOOP, "iteration": 2}, "iteration_mismatch")


def test_cap_reached_after_the_last_allowed_iteration(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "capped")
    _refused(world, {"loop_id": LOOP, "iteration": 3}, "cap_reached")


def test_too_few_candidates_when_one_pending_is_left(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "pre")
    run = world["run"]
    a, b, c = scenario["refs"][:3]
    body = ligand_body(scenario["world"], goal="exploit", iteration_cap=3)
    body["pool"]["candidates"] = [a, b, c]       # A reused (scored), B unavailable: one pending candidate
    body["setup"] = scenario["raw_setup"]
    loop_id = jev_loop_store.create(run, body, send_active=False)["loop_id"]
    _refused(world, {"loop_id": loop_id, "iteration": 1}, "too_few_candidates")


def test_source_invalid(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select2")

    def broken(*_args, **_kwargs):   # fault injection: the published set's stored-object check fails
        raise ValueError("synthetic: stored object check fails")

    monkeypatch.setattr(ligand_bundle, "check_candidate_set", broken)
    _refused(world, {"loop_id": LOOP, "iteration": 2}, "source_invalid")


def test_structure_unavailable(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "pre")
    indexes = scenario["world"]["indexes"]
    loop_id = _protein_loop(scenario, world, "explore", [indexes[0], indexes[19], indexes[5]])

    def unreadable(*_args, **_kwargs):   # fault injection: the set's prepared structure cannot be parsed
        raise ToolFailure(FailureClass.input_invalid, "synthetic: unreadable structure")

    monkeypatch.setattr(m24_tool, "_parse", unreadable)
    _refused(world, {"loop_id": loop_id, "iteration": 1}, "structure_unavailable")


def test_wire_field_invalid(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select2")
    # fault injection: the observed property method strings no longer match the stored ones
    monkeypatch.setattr(P, "PROPERTY_METHODS", {**J.PROPERTY_METHODS, "tpsa": "rdkit CalcTPSA (changed)"})
    _refused(world, {"loop_id": LOOP, "iteration": 2}, "wire_field_invalid")


def test_payload_too_large_stores_nothing_at_the_64_kib_boundary(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select2")   # no projection of iteration 2 yet: no cache entry
    run = world["run"]
    monkeypatch.setattr(L, "MAX_BODY_BYTES", 1_000)              # fault injection: lowered cap
    detail = _refused(world, {"loop_id": LOOP, "iteration": 2}, "payload_too_large").detail
    size = detail["body_bytes"]
    assert detail == {"reason_code": "payload_too_large", "body_bytes": size, "limit": 1_000} and size > 1_000
    monkeypatch.setattr(L, "MAX_BODY_BYTES", size - 1)            # one byte over the cap: refused, nothing stored
    assert _refused(world, {"loop_id": LOOP, "iteration": 2}, "payload_too_large").detail["limit"] == size - 1
    monkeypatch.setattr(L, "MAX_BODY_BYTES", size)                # exactly at the cap: built and stored once
    content = run.store.load(_call(world, iteration=2).handle)
    assert content["body_bytes"] == size and len(world["calls"]) == 1
    monkeypatch.setattr(L, "MAX_BODY_BYTES", 65_536)
    assert L.MAX_BODY_BYTES == J.MAX_BODY_BYTES == 65_536


def test_a_build_that_fails_validation_is_never_stored(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select2")
    run = world["run"]
    original = LP.validated_loop_projection
    calls = {"n": 0}

    def tampered(content):   # fault injection: the stored-form check refuses the implementation's build
        calls["n"] += 1
        if calls["n"] > 1:   # the pre-check's own build passes; the implementation's stored form fails
            raise P.ProjectionInvalid("synthetic: refused stored form")
        return original(content)

    monkeypatch.setattr(LP, "validated_loop_projection", tampered)
    before = len(_events(run))
    with pytest.raises(ToolFailure) as caught:
        _call(world, iteration=2)
    assert caught.value.cls == FailureClass.input_invalid and caught.value.detail["reason_code"] == "projection_invalid"
    assert [event["type"] for event in _events(run)[before:] if event["type"] != "wall_charged"] == [
        "tool_called", "tool_failed"]
    assert not _projections(run)[1:]


def test_commands_route_maps_the_reasons_to_422_412_429(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "running1")
    client = world["client"]

    def command(args):
        return client.post(f"/runs/{RID}/commands", json={"tool": TOOL, "args": args})

    for args, reason in (({"loop_id": LOOP, "iteration": 1, "x": 1}, "unknown_field"),
                         ({"loop_id": str(uuid.uuid4()), "iteration": 1}, "loop_not_found"),
                         ({"loop_id": LOOP, "iteration": 1}, "phase_invalid"),
                         ({"loop_id": LOOP, "iteration": 2}, "iteration_mismatch")):
        response = command(args)
        status = HTTP[REASON_CLASS[reason]]
        assert response.status_code == status, response.text
        assert response.json()["error"] == REASON_CLASS[reason] and response.json()["detail"]["reason_code"] == reason
    later = _open(scenario, tmp_path / "later", monkeypatch, "select2")
    monkeypatch.setattr(L, "MAX_BODY_BYTES", 1_000)              # fault injection: lowered cap
    response = later["client"].post(f"/runs/{RID}/commands",
                                    json={"tool": TOOL, "args": {"loop_id": LOOP, "iteration": 2}})
    assert response.status_code == 429 and response.json()["detail"]["reason_code"] == "payload_too_large"
    monkeypatch.setattr(L, "MAX_BODY_BYTES", 65_536)
    response = later["client"].post(f"/runs/{RID}/commands",
                                    json={"tool": TOOL, "args": {"loop_id": LOOP, "iteration": 2}})
    assert response.status_code == 200, response.text
    handle = response.json()["handle"]
    assert handle["kind"] == L.PROJECTION_KIND and handle["summary"]["iteration"] == 2
    assert world["fake"].requests == [] and later["fake"].requests == [] and later["fake"].key_reads == 0


# ---------------------------------------------------------------- mutation: geometry from the independent oracle


@pytest.mark.parametrize("goal", ["explore", "exploit"])
def test_mutation_projection_matches_the_independent_geometry_oracle(goal, scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "pre")
    run = world["run"]
    indexes = scenario["world"]["indexes"]
    pool = [indexes[30], indexes[0], indexes[17], indexes[19], indexes[5]]
    loop_id = _protein_loop(scenario, world, goal, pool)
    content = run.store.load(_call(world, loop_id=loop_id).handle)
    assert LP.validated_loop_projection(content) == content
    set_content = run.store.load(scenario["world"]["ubq_set"])
    stored = [row["index"] for row in set_content["candidates"] if row["index"] in pool]   # the set's stored order
    # spec 4.3 order by the oracle's own key function; aliases m01... in that order
    expected = sorted(stored, key=lambda ref: (ORDER.key_of(11, 1, 0, ref), stored.index(ref)))
    assert [item["ref"] for item in content["selection"]] == expected
    assert [item["alias"] for item in content["selection"]] == [f"m0{n}" for n in range(1, 6)]
    # position aliases p01... by first use in the send order
    position_of = {row["index"]: row["position_index"] for row in set_content["candidates"]}
    residue_of = {item["index"]: item["residue"] for item in set_content["positions"]}
    first_use: dict[int, str] = {}
    for ref in expected:
        first_use.setdefault(position_of[ref], f"p0{len(first_use) + 1}")
    assert [candidate["pos"] for candidate in content["wire"]["candidates"]] == [first_use[position_of[ref]]
                                                                                for ref in expected]
    oracle = {p["residue"]["seq_auth"]: p for p in EXPECTED["1UBQ"]["positions"]}
    positions = {position["pos"]: position for position in content["wire"]["positions"]}
    assert list(positions) == list(first_use.values())
    for index, alias in first_use.items():
        position = positions[alias]
        residue = residue_of[index]
        assert position["residue"]["seq_auth"] == residue["seq_auth"] and residue["seq_auth"] in (44, 48)
        truth = oracle[residue["seq_auth"]]
        assert position["neighbors"] == truth["neighbors"]
        assert position["window"] == {key: truth["window"][key] for key in J.ALLOWED_WINDOW}
        assert position["ligand_min_distance_A"] is None and position["sources"] == ["user"]
    assert content["wire"]["computed"] == [] and content["wire"]["goal"] == goal
    assert content["wire"]["values_note"] == L.VALUES_NOTES[("mutation", goal)]
    assert content["question"] == {"id": "mutation_loop_choice@1", "key": "candidate_choice"}
    assert content["structure"] == {"handle": set_content["structure"]["handle"], "model_number": 1}
    assert content["limitations"] == [L.STATEMENTS[name] for name in (
        "LJ1", "LJ2", "LJ3", "LJ5" if goal == "explore" else "LJ4", "LJ7")]
    text = canonical_json(content["wire"]).decode()
    assert "obj://" not in text and loop_id not in text and "_atom_site" not in text


# ---------------------------------------------------------------- the M24 preview reads loop projections


def _preview(world, handle):
    return world["client"].post(f"/runs/{RID}/jev/preview", content=json.dumps({"projection": handle}).encode(),
                                headers=JSON)


def _spec_body(content) -> str:
    """The spec 4.5 body assembled here from the stored projection (not through the product body function)."""
    criteria = [item["alias"] for item in content["selection"] if item["state"] == "pending"]
    body = {"model": "typesafe/jev-1.13", "state": content["wire"],
            "questions": {"candidate_choice": {
                "type": "choice", "instructions": L.INSTRUCTIONS[(content["kind"], content["goal"])],
                "criteria": {alias: f"Candidate {alias}." for alias in criteria}}},
            "provider": {"data_collection": "deny", "zdr": True, "allow_fallbacks": False}}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True)


def test_preview_of_a_loop_projection_is_its_exact_body(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    run, handle = world["run"], scenario["projection"]
    content = run.store.load(handle)
    before = _log(world)
    response = _preview(world, handle)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert set(preview) == M24_PREVIEW_KEYS | {"loop", "loop_blocks"}
    body = _spec_body(content)
    assert preview["body"] == body
    assert preview["body_sha256"] == hashlib.sha256(body.encode("ascii")).hexdigest() == content["body_sha256"]
    assert preview["body_bytes"] == len(body.encode("ascii")) == content["body_bytes"]
    instructions = L.INSTRUCTIONS[("ligand", "exploit")]
    assert preview["question"] == {"id": "ligand_loop_choice@1", "key": "candidate_choice", "type": "choice",
                                   "instructions": instructions,
                                   "instructions_sha256": hashlib.sha256(instructions.encode("ascii")).hexdigest()}
    assert preview["selection"] == content["selection"] and preview["selection_sent"] is False
    assert (preview["schema"], preview["projection_handle"], preview["kind"]) == ("jev_preview@1", handle, "ligand")
    assert preview["source"] == content["source"]
    tokens = min(50_000, 4_096 + math.ceil(content["body_bytes"] * 2 / 3))   # the M24 formula, written out
    assert preview["reservation"] == {"external_tokens": tokens, "usd": 0.10}
    assert preview["blocked_by"] == ["consent_off"] and preview["previous_sends"] == 0
    assert preview["loop_blocks"] == []
    # the loop record derived with that reservation: its send-side needs are the preview's reservation
    record = jev_loop_store.read_loop(jev_loop_store.LoopReadView(run), LOOP,
                                      budget=jev_loop_store.remaining_budget(run.budget_snapshot()),
                                      send_reservation=preview["reservation"]).record
    current = record["current"]
    assert preview["loop"] == {"loop_id": LOOP, "iteration": 1, "send_ordinal": 0, "needs": current["needs"],
                               "remaining": current["remaining"], "send_blocked_axes": current["send_blocked_axes"]}
    assert preview["loop"]["needs"]["external_tokens"] == tokens and preview["loop"]["needs"]["usd"] == 0.10
    assert preview["loop"]["needs"]["sends"] == 1 and preview["loop"]["send_blocked_axes"] == []
    # the record read without a preview keeps the send-side amounts null (spec 3.2)
    plain = world["client"].get(f"/runs/{RID}/jev_loops/{LOOP}").json()["current"]["needs"]
    assert plain["external_tokens"] is None and plain["usd"] is None
    assert _log(world) == before and world["fake"].requests == [] and world["fake"].key_reads == 0


def test_preview_loop_blocks_follow_the_loop_judgment(scenario, tmp_path, monkeypatch):
    handle = scenario["projection"]                # iteration 1, send ordinal 0, built at the select1 stage
    for stage, blocks in (("select1", []), ("running1", ["phase_invalid"]), ("select2", ["iteration_mismatch"]),
                          ("capped", ["iteration_mismatch"])):
        world = _open(scenario, tmp_path / stage, monkeypatch, stage)
        before = _log(world)
        response = _preview(world, handle)
        assert response.status_code == 200, response.text
        assert response.json()["loop_blocks"] == blocks, stage
        assert _log(world) == before
    # ended (a labelled synthetic jev_loop_ended)
    world = _open(scenario, tmp_path / "ended", monkeypatch, "select1")
    ended(world["run"])
    assert _preview(world, handle).json()["loop_blocks"] == ["loop_ended"]
    # state_changed: a pending candidate's same-key job is cancelled outside the loop after the projection was built
    world = _open(scenario, tmp_path / "changed", monkeypatch, "select1")
    run = world["run"]
    e = scenario["refs"][4]
    setup = jev_loop_store.created_payload(list(run.events.read()), LOOP)["setup"]
    queue = JobQueue(run)
    job = queue.submit(DC.PROTOCOL, jev_loop_store.ligand_request(setup, scenario["world"]["ligand_set"], e),
                       timeout_s=300)
    assert queue.request_cancel(job["job_id"])["job"]["status"] == "cancelled"
    assert _preview(world, handle).json()["loop_blocks"] == ["state_changed"]
    fresh = _call(world).handle                    # the record now: E left out of the new projection
    assert fresh != handle and e not in {item["ref"] for item in run.store.load(fresh)["selection"]}
    assert _preview(world, fresh).json()["loop_blocks"] == []
    # ordinal_mismatch: a dispatched send of this projection moved the iteration's send ordinal
    world = _open(scenario, tmp_path / "ordinal", monkeypatch, "select1")
    send_events(world["run"], handle)
    assert _preview(world, handle).json()["loop_blocks"] == ["ordinal_mismatch"]
    assert _preview(world, _call(world).handle).json()["loop_blocks"] == []
    # selection_done: a completed, not-late proposal of iteration 1 exists
    world = _open(scenario, tmp_path / "chosen", monkeypatch, "select1")
    proposal(monkeypatch, world["run"], handle, scenario["refs"][3])
    assert _preview(world, handle).json()["loop_blocks"] == ["selection_done"]


def test_the_loop_send_check_compares_the_projection_with_the_record_now(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select2")
    run = world["run"]
    a, _b, c = scenario["refs"][:3]
    projection = run.store.load(_call(world, iteration=2).handle)
    view = jev_loop_store.LoopReadView(run)
    budget = jev_loop_store.remaining_budget(run.budget_snapshot())
    state, reason = jev_loop_store.loop_send_check(view, projection, budget=budget, send_active=False)
    assert reason is None and state.record["loop_id"] == LOOP
    assert jev_loop_store.send_refusal(state, projection) is None

    def edited(change):
        out = json.loads(canonical_json(projection))
        change(out)
        return out

    def score(out):          # a sent score that is not the stored first mode any more
        out["wire"]["computed"][0]["score_kcal_mol"] += 0.5

    def goal(out):
        out["goal"] = "explore"

    def seed(out):
        out["order"]["loop_seed"] += 1

    def flipped(out):        # a computed candidate listed as not yet computed
        next(item for item in out["selection"] if item["ref"] == c)["state"] = "pending"

    def dropped(out):        # a pending candidate missing from the projection
        out["selection"] = [item for item in out["selection"] if item["ref"] in (a, c)] + [
            next(item for item in out["selection"] if item["state"] == "pending")]

    for change in (score, goal, seed, flipped, dropped):
        assert jev_loop_store.send_refusal(state, edited(change)) == "state_changed", change.__name__

    def ordinal(out):
        out["loop"]["send_ordinal"] = 1

    def iteration(out):
        out["loop"]["iteration"] = 3

    assert jev_loop_store.send_refusal(state, edited(ordinal)) == "ordinal_mismatch"
    assert jev_loop_store.send_refusal(state, edited(iteration)) == "iteration_mismatch"
    missing = edited(lambda out: out["loop"].update(loop_id=str(uuid.uuid4())))
    assert jev_loop_store.loop_send_check(view, missing, budget=budget, send_active=False) == (
        None, "loop_not_found")
    assert set(L.LOOP_SEND_REASONS) == {"loop_not_found", "loop_ended", "iteration_mismatch", "selection_done",
                                        "phase_invalid", "cap_reached", "too_few_candidates", "state_changed",
                                        "ordinal_mismatch"}


def test_preview_of_a_projection_whose_loop_is_absent(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    run = world["run"]
    # fault injection: a well-formed loop projection stored without the tool, naming a loop this run does not hold
    content = json.loads(canonical_json(run.store.load(scenario["projection"])))
    content["loop"]["loop_id"] = str(uuid.uuid4())
    assert LP.validated_loop_projection(content) == content
    forged = run.store.put(L.PROJECTION_KIND, L.PROJECTION_SCHEMA, content, produced_by="synthetic_forgery").handle
    preview = _preview(world, forged).json()
    assert preview["loop_blocks"] == ["loop_not_found"]
    assert preview["loop"] == {**content["loop"], "needs": None, "remaining": None, "send_blocked_axes": None}


def test_the_m24_preview_shape_is_unchanged_next_to_a_loop(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    m24 = world["run"].call(J.TOOL, {"source": scenario["world"]["ligand_set"],
                                     "candidates": list(scenario["refs"][:3])}).handle
    preview = _preview(world, m24).json()
    assert set(preview) == M24_PREVIEW_KEYS and preview["kind"] == "ligand"
    assert preview["question"]["id"] == J.QUESTION_FOR_KIND["ligand"]
    assert preview["body"] == P.projection_body(world["run"].store.load(m24))[1].decode("ascii")


def test_the_send_route_still_refuses_a_loop_projection_before_t5(scenario, tmp_path, monkeypatch):
    # T4 opens the preview only; the send branch for loop projections is T5 (this expectation changes there).
    world = _open(scenario, tmp_path, monkeypatch, "select1")
    content = world["run"].store.load(scenario["projection"])
    before = _log(world)
    response = world["client"].post(f"/runs/{RID}/jev/sends", headers=JSON, content=json.dumps({
        "send_id": str(uuid.uuid4()), "projection": scenario["projection"], "body_sha256": content["body_sha256"],
        "confirm": J.CONFIRM}).encode())
    assert response.status_code == 422 and response.json()["detail"]["reason_code"] == J.PROJECTION_INVALID
    assert _log(world) == before and world["fake"].requests == [] and world["fake"].key_reads == 0


# ---------------------------------------------------------------- events-only recovery


def test_events_only_recovery_reopens_the_projection_and_hits_the_cache(scenario, tmp_path, monkeypatch):
    world = _open(scenario, tmp_path, monkeypatch, "select1")   # an events-only copy of the original run
    run, handle = world["run"], scenario["projection"]
    path = run.run_dir / "objects" / f"{handle.rsplit('/', 1)[1]}.json"
    assert path.read_bytes() == scenario["objects"][handle]
    content = run.store.load(handle)
    assert LP.validated_loop_projection(content) == content
    assert _call(world).handle == handle and world["calls"] == []


# ---------------------------------------------------------------- module hygiene


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def test_tool_module_imports_and_forbidden_names():
    path = MW / "tools/jev_loop.py"
    assert _imports(path) <= {"__future__", "dataclasses", "hashlib", "json", "types", "typing", "..",
                              "..core.errors", "..core.handles", ".", ".registry"}
    text = path.read_text()
    for word in ("raise_limits", "limit_approval", "httpx", "pydantic", "rdkit", "meeko", "MDAnalysis", "pdbfixer",
                 "openmm", "egress", "jev_sends", "run_send", "request_science", "SCIENCE_GATE", "begin_send",
                 "reference_snapshots", "urllib", "socket", "requests", "JobQueue", "reserve_attempt"):
        assert word not in text, word
    for event in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME):
        assert event not in text, event
    for name in ("analysis_plans.py", "analysis_executions.py", "workflows.py"):   # M13 flows never call it
        assert TOOL not in (MW / name).read_text(), name
    for name in ("jev_loop_store.py", "jev_loops.py", "jev_loop_projection.py", "jev_loop_constants.py"):
        assert "jev_sends" not in _imports(MW / name) and ".jev_sends" not in _imports(MW / name), name


def test_importing_the_tool_loads_no_send_network_or_chemistry_module():
    code = ("import sys, mw.tools.jev_loop\n"
            "bad = [m for m in ('httpx', 'rdkit', 'meeko', 'MDAnalysis', 'pdbfixer', 'openmm', 'fastapi',"
            " 'mw.egress', 'mw.egress.gate', 'mw.egress.science', 'mw.jev_sends', 'mw.llm',"
            " 'mw.reference_snapshots') if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_jev_sends_reads_loop_projections_through_the_loop_modules():
    # the M24 module imports the loop modules (allowed), never the reverse; the loop judgment stays in them
    tree = ast.parse((MW / "jev_sends.py").read_text())
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 1
             for alias in node.names}
    assert {"jev_loop_projection", "jev_loop_store"} <= names
    text = (MW / "jev_sends.py").read_text()
    assert "jev_loop_store.loop_send_check" in text and "validated_loop_projection" in text
    for word in ("raise_limits", "limit_approval", "openmm", "socket", "requests", "selection_refusal"):
        assert word not in text, word
