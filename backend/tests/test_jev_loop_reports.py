"""M25 T7: the ``jev_loop`` report (``mw.jev_loop_reports``), the M24 report route refusing a loop send's proposal,
and the ``loop`` key of the M21 same-condition docking pair rows (spec .dryforge/spec.md 2, 8.2, 8.3, 9.3, 10, 12).

Inputs are REAL product objects built once per module and served from events-only copies by the product app
(``SCIENCE_GATE`` is a ``jev_send_fixture.Fake``: MockTransport, inert sentinel credential, fixture replies):
* ligand world: real M17 jobs on the labelled synthetic small blocks (``fixtures/ligand_ga``), the public-derived parent
  SDF and the public prepared docking example receptor (not experimental validation); one standalone M18 docking made
  outside any loop; then one ended ligand loop (exploit, cap 3, pool of five): iteration 1 decided by a JEV fixture
  reply that reports a confidence, iteration 2 by one that reports none, iteration 3 named by the person after a late
  JEV reply (consent turned off in flight); its docking times out after its reservation (LABELLED fault injection:
  ``Run._time_left`` reports one second). Dockings run the pinned docking worker + ``qvina2``.
* protein world: public 1UBQ, an M20 set at ILE44 and the labelled synthetic phenol SDF, one real M21 model of I44W
  (``test_jev_loops_compute._protein_world``); one mutant docking of that model with another seed outside any loop;
  then one ended protein loop (explore, cap 2) whose iteration 1 is a JEV fixture choice of I44W: the stored model is
  adopted and the mutant docking runs in the loop. One test also docks the same condition outside a loop between the
  loop's model and docking approvals (the loop adopts that stored docking).
A missing engine FAILS, never skips. Engine values are never an oracle: every score is read from the stored result
object here, and the 0.1 ROUND_HALF_UP text is computed in this file with ``decimal``. Expected names come from the
spec (``analysis_type``, render, generation mode, the two evidence kinds, the model-response note, "보고 없음", the
LJ sentences, the pair ``loop`` key). Stored reports and claims edited by hand and a log cut before its end event are
fault injection, marked where used.
"""
from __future__ import annotations

import ast
import copy
import json
import re
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from jev_send_fixture import SENTINEL, Fake, reply
from ligand_job_fixture import import_file, new_ligand_run, run_job
from test_jev_loops_compute import (
    PROTEIN_FAST,
    A,
    B,
    Served,
    W,
    end_loop,
    hand_dock_request,
    hand_ligand_request,
    ligand_loop,
    one_second_left,
    protein_loop,
)
from test_jev_loops_compute import _protein_world as protein_template
from test_ligand_ga_jobs import BLOCKS, PARENT, REC

from mw import docking_batch_inputs, docking_bundle, docking_inputs, mutation_model_reads
from mw import docking_constants as DC
from mw import jev_constants as J
from mw import jev_loop_constants as L
from mw import jev_loop_reports as R
from mw import jev_reports as M24
from mw import jev_sends as S
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError, _md, _ref
from mw.runtime.guards import BudgetLimits
from mw.runtime.orchestrator import Run

MW = Path(__file__).resolve().parents[1] / "mw"
LRID = "run_m25_report_ligand"
OTHER_SEED = 20261009                                   # the outside mutant docking (a non-loop pair row)
CONFIDENCE = 0.25                                       # fixture reply value, never a provider output
PROBABILITY = 0.4321                                    # fixture reply value, never a provider output
MANIFEST_KEYS = {"schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle",
                 "result_schema", "result_sha256", "external_response", "branch", "loop_id", "goal", "loop_seed",
                 "iteration_cap", "effective_cap", "end_reason", "pool", "setup", "setup_sha256", "pins", "counts",
                 "candidates", "iterations", "unfinished", "score_label", "score_column_label", "chosen", "claims",
                 "provenance", "evidence_statement", "limitation_ids", "limitations", "snapshot", "markdown_handle"}
MODEL_NOTE = "외부 모델의 응답, 제안이며 과학 증거가 아니다"                     # spec 8.3
FORBIDDEN = ("순위", "추천", "최적", "개선", "예측", "유망", "좋은", "나쁜", "점수", "에너지", "활성", "친화도",
             "안정성", "결합", "최저", "최고", "좋아짐", "승자", "차이", "평균", "best", "rank", "recommend", "improve",
             "winner", "lowest", "affinity", "score")
REPORT_EVENTS = ["object_created", "object_created", "method_report_created"]


def _number_in(value, text):
    """``str(value)`` in ``text`` as a whole number, not as digits inside a longer one: the manifest's snapshot holds
    the last event's ``time.time()`` (``time_utc``) and the budget's wall clock, whose digits can run ``…0.4321…`` by
    chance (the M24 ``test_jev_reports`` failure, fixed there in M28 T2; here in M29 T2)."""
    return re.search(rf"(?<![\d.]){re.escape(str(value))}(?!\d)", text) is not None


def test_the_probability_check_finds_the_value_but_not_its_digits_inside_other_numbers():
    for leaked in ('{"p":0.4321}', '{"p":[1,0.4321]}', '"0.4321"', "p = 0.4321."):
        assert _number_in(PROBABILITY, leaked), leaked
    for other in ('{"time_utc":1760180000.43215}', '{"used":10.4321}', '{"x":0.43211}'):
        assert not _number_in(PROBABILITY, other), other


# ---------------------------------------------------------------- helpers


def half_up(value) -> str:
    """0.1 ROUND_HALF_UP of the stored value, written here (spec 8.3) independently of the report module."""
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.1f}"


def alias_of(run: Run, projection: str, ref) -> str:
    return next(item["alias"] for item in run.store.load(projection)["selection"] if item["ref"] == ref)


def project(served: Served, loop_id: str, iteration: int) -> str:
    return served.run.call(L.TOOL, {"loop_id": loop_id, "iteration": iteration}).handle


def build(served: Served, handle: str):
    return served.client.post(f"/runs/{served.rid}/method_reports", json={"result_handle": handle})


def built(served: Served, handle: str) -> dict:
    response = build(served, handle)
    assert response.status_code == 201, response.text
    return response.json()


def selected(served: Served, handle: str):
    return served.client.get(f"/runs/{served.rid}/reports/selected", params={"handle": handle})


def refused(response) -> str:
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "report_evidence_invalid", response.text
    return response.json()["detail"]["message"]


def claims_of(manifest: dict, statement: str | None = None, **selector) -> list[dict]:
    return [claim for claim in manifest["claims"] if (statement is None or claim["statement_id"] == statement)
            and all((claim["row_selector"] or {}).get(key) == value for key, value in selector.items())]


def forge(run: Run, manifest: dict, markdown: str) -> str:
    """Fault injection: store an edited report and its creation event the way the builder does."""
    md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                       produced_by="forged", summary={"result_handle": manifest["result_handle"]})
    manifest = {**manifest, "markdown_handle": md.handle}
    report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest, produced_by="forged",
                           summary={"result_handle": manifest["result_handle"], "analysis_type": "jev_loop",
                                    "status": "complete"})
    run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                      result_handle=manifest["result_handle"], snapshot_event_seq=manifest["snapshot"]["event_seq"])
    return report.handle


def stored_first_mode(run: Run, handle: str):
    return run.store.load(handle)["modes"][0]["score_kcal_mol"]


def published_handle(served: Served, request: dict) -> str:
    """The stored M18 result of ``request``, found through the run's publication index and the standalone call key
    of the request (not through the loop code)."""
    key = docking_bundle.call_key(docking_inputs.validate_arguments(request), docking_bundle.require_ready())
    return docking_batch_inputs.published_m18_results(served.events())[key]


# ---------------------------------------------------------------- the two worlds (built once)


def _ligand_world(root: Path) -> dict:
    run = new_ligand_run(root, LRID)
    world = {"rid": LRID}
    world["receptor"] = import_file(run, "receptor", "rec.pdb", REC)
    world["parent"] = import_file(run, "ligand_sdf", "parent.sdf", PARENT)
    blocks = import_file(run, "building_blocks_smiles", "blocks.smi", BLOCKS)
    inspected = run_job(run, "rdkit_inspect_v1", {"parent_sdf_handle": world["parent"], "block_handles": [blocks]})
    assert inspected["status"] == "done", inspected
    enumerated = run_job(run, "rdkit_enumerate_v1", {"inspection_handle": inspected["output_handles"][0],
                                                     "site_atoms": [22], "use_fixed": True})
    assert enumerated["status"] == "done", enumerated
    world["set"] = enumerated["output_handles"][0]
    ids = [row["id"] for row in run.store.load(world["set"])["candidates"]]
    world["pool"] = ids[:5]
    run.update_limits(BudgetLimits(expensive_calls=20, wall_clock_s=30000), by="test")
    queue = JobQueue(run)                       # outside any loop: the stored result the loop reuses
    single = queue.submit(DC.PROTOCOL, hand_ligand_request(world, ids[4]), timeout_s=300)
    assert queue.start(single["job_id"])["status"] == "done"
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(api_module, "RUNS_DIR", root)
        patch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
        api_module.RUNS.clear()
        served = Served(LRID, root)
        loop_id = served.create(ligand_loop(world, world["pool"], cap=3))
        S.set_consent(served.run, True)
        sends = []
        for number, ref in enumerate(ids[:2], 1):        # JEV decides: with a confidence, then without one
            projection = project(served, loop_id, number)
            alias = alias_of(served.run, projection, ref)
            extra = {"confidence": CONFIDENCE, "probabilities": {alias: PROBABILITY}} if number == 1 else {}
            sent = served.send(Fake(lambda request, alias=alias, extra=extra: reply(alias, **extra)), projection)
            assert (sent["status"], sent["late"]) == ("completed", False), sent
            response = served.compute(loop_id, iteration=number, proposal=sent["choice_handle"])
            assert response.status_code == 200, response.text
            sends.append(sent)
        projection = project(served, loop_id, 3)
        alias = alias_of(served.run, projection, ids[2])

        def late(request):                 # consent turned off while the request is in flight: a late reply
            S.set_consent(served.run, False)
            return reply(alias, confidence=0.75)

        sent = served.send(Fake(late), projection)
        assert (sent["status"], sent["late"]) == ("completed", True), sent
        sends.append(sent)
        S.set_consent(served.run, True)
        with one_second_left(patch):        # LABELLED fault injection: the docking times out after its reservation
            response = served.compute(loop_id, iteration=3, candidate=ids[3])
        assert response.status_code == 200, response.text
        record, content = end_loop(served, loop_id, "iteration_cap")
        world.update(loop_id=loop_id, sends=sends, record=record, summary=record["result_handle"], content=content,
                     log=served.log())
        return world
    finally:
        S.ACTIVE_SENDS.clear()
        patch.undo()
        api_module.RUNS.clear()


def _protein_report_world(root: Path) -> dict:
    world = protein_template(root)
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(api_module, "RUNS_DIR", root)
        patch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
        api_module.RUNS.clear()
        served = Served(world["rid"], root)
        outside = {**hand_dock_request(world, world["model"]), "parameters": {**PROTEIN_FAST, "seed": OTHER_SEED}}
        job = served.submit_job(DC.PROTOCOL, outside, 300)
        started = served.client.post(f"/runs/{world['rid']}/jobs/{job['job_id']}/start")
        assert started.status_code == 200 and started.json()["status"] == "done", started.text
        world["outside_job"] = job["job_id"]
        world["before_loop"] = served.log()
        world["pairs_before"] = served.client.get(
            f"/runs/{world['rid']}/mutation_models/{world['model']}/docking_pairs").content
        w = world["refs"][W]
        loop_id = served.create(protein_loop(world, (W, A, B), cap=2, goal="explore"))
        S.set_consent(served.run, True)
        projection = project(served, loop_id, 1)
        alias = alias_of(served.run, projection, w)
        sent = served.send(Fake(lambda request: reply(alias, confidence=0.5)), projection)
        assert (sent["status"], sent["late"]) == ("completed", False), sent
        assert served.compute(loop_id, iteration=1, proposal=sent["choice_handle"]).status_code == 200
        response = served.compute(loop_id, iteration=1)                     # the mutant docking, in the loop
        assert response.status_code == 200, response.text
        record, content = end_loop(served, loop_id, "ended_by_user")
        world.update(loop_id=loop_id, send=sent, record=record, summary=record["result_handle"], content=content,
                     log=served.log())
        return world
    finally:
        S.ACTIVE_SENDS.clear()
        patch.undo()
        api_module.RUNS.clear()


@pytest.fixture(scope="module")
def ligand(tmp_path_factory):
    return _ligand_world(tmp_path_factory.mktemp("m25_report_ligand"))


@pytest.fixture(scope="module")
def protein(tmp_path_factory):
    return _protein_report_world(tmp_path_factory.mktemp("m25_report_protein"))


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    S.ACTIVE_SENDS.clear()


@pytest.fixture
def serve(tmp_path, monkeypatch):
    fakes: list[Fake] = []

    def open_copy(world: dict, raw: bytes, name: str = "runs") -> Served:
        root = tmp_path / name
        (root / world["rid"]).mkdir(parents=True)
        (root / world["rid"] / "events.jsonl").write_bytes(raw)
        fake = Fake()
        fakes.append(fake)
        monkeypatch.setattr(api_module, "RUNS_DIR", root)
        monkeypatch.setattr(api_module, "SCIENCE_GATE", fake.gate)
        api_module.RUNS.clear()
        served = Served(world["rid"], root)
        served.fake = fake
        return served
    yield open_copy
    api_module.RUNS.clear()
    assert all(fake.requests == [] and fake.key_reads == 0 for fake in fakes)     # no report path sends or reads a key


# ---------------------------------------------------------------- the ligand loop report


def test_the_ligand_report_cites_its_summary_and_results_and_keeps_jev_choices_as_model_responses(ligand, serve):
    served = serve(ligand, ligand["log"])
    content = served.run.store.load(ligand["summary"])
    assert content == ligand["content"]
    before = len(served.events())
    made = built(served, ligand["summary"])
    new = served.events()[before:]
    assert [event["type"] for event in new] == REPORT_EVENTS                  # nothing computed, sent or read again
    manifest, markdown = made["manifest"], made["markdown"]
    assert set(manifest) == MANIFEST_KEYS
    assert (manifest["schema"], manifest["analysis_type"], manifest["status"], manifest["render_version"],
            manifest["generation_mode"], manifest["result_handle"], manifest["result_schema"]) == (
        "method_report_manifest@1", "jev_loop", "complete", "jev_loop_markdown@1", "local_rules_no_egress",
        ligand["summary"], "jev_loop_result@1")
    assert manifest["external_response"] == {"kind": "jev_loop_choice", "scientific_evidence": False}
    assert markdown.startswith("# JEV 루프 보고서")
    for key in ("branch", "loop_id", "goal", "loop_seed", "iteration_cap", "effective_cap", "end_reason", "pool",
                "setup", "setup_sha256", "pins", "counts", "candidates", "iterations", "unfinished"):
        assert manifest[key] == content[key], key
    # computed: the pool, the loop settings, the counts (the summary numbers), never a model-response field
    computed = claims_of(manifest)
    by_path = {claim["field_path"]: claim for claim in computed if claim["source_handle"] == ligand["summary"]}
    assert by_path["pool.candidates"]["exact_value"] == len(content["pool"]["candidates"]) == 5
    assert by_path["pool.source.handle"]["exact_value"] == ligand["set"]
    for name in ("loop_seed", "iteration_cap", "effective_cap", "setup_sha256"):
        assert by_path[name]["exact_value"] == content[name]
    assert content["counts"] == {"started": 3, "done": 3, "jev_decided": 2, "human_decided": 1,
                                 "sends_dispatched": 3, "units_charged": 3, "reused_count": 1}
    for name, value in content["counts"].items():
        claim = by_path[f"counts.{name}"]
        assert (claim["exact_value"], claim["rendered_value"], claim["evidence_kind"]) == (value, str(value),
                                                                                         "computed")
    for path, value in content["setup"]["parameters"].items():
        if value is not None:
            assert by_path[f"setup.parameters.{path}"]["exact_value"] == value
    # per candidate: two score claims for a scored one (summary + its result's first mode), none for the others
    states = {row["ref"]: row["state"] for row in content["candidates"]}
    ids = ligand["pool"]
    assert [states[ref] for ref in ids[2:4]] == ["pending", "failed"]
    assert content["candidates"][4]["evaluation"] == "reused"
    scored = 0
    for index, row in enumerate(content["candidates"]):
        pair = claims_of(manifest, None, candidate=index)
        if row["state"] != "scored":
            assert pair == [] and row["score_kcal_mol"] is None, row
            continue
        scored += 1
        if row["evaluation"] == "reused":
            handle = published_handle(served, hand_ligand_request(ligand, row["ref"]))
        else:
            iteration = content["iterations"][row["iteration"] - 1]
            handle = iteration["steps"][-1]["result_handle"]
        first = stored_first_mode(served.run, handle)
        assert row["score_kcal_mol"] == first
        assert sorted((claim["statement_id"], claim["source_handle"], claim["field_path"]) for claim in pair) == [
            ("candidate_result_score", handle, "modes[0].score_kcal_mol"),
            ("candidate_score", ligand["summary"], f"candidates[{index}].score_kcal_mol")]
        for claim in pair:
            assert (claim["exact_value"], claim["rendered_value"], claim["unit"], claim["evidence_kind"],
                    claim["reference"]) == (first, half_up(first), "kcal/mol", "computed", None)
        assert f"| {_md(row['ref'])} |" in markdown and f"| {_md(half_up(first))} |" in markdown
    assert scored >= 2                                                       # the JEV-decided dockings and the reuse
    # the failed and pending rows keep an empty score cell (never 0)
    for ref in ids[2:4]:
        line = next(text for text in markdown.splitlines() if text.startswith(f"| {_md(ref)} |"))
        assert line.split(" | ")[5] == "", line
    # model responses: only the two JEV-decided iterations; the human one (with a late JEV reply stored) has none
    proposals = [send["choice_handle"] for send in ligand["sends"]]
    model = [claim for claim in manifest["claims"] if claim["evidence_kind"] == "model_response"]
    assert {claim["source_handle"] for claim in model} == set(proposals[:2])
    assert {claim["row_selector"]["iteration"] for claim in model} == {1, 2}
    for number, proposal in enumerate(proposals[:2], 1):
        answer = served.run.store.load(proposal)["answer"]
        mine = {claim["statement_id"]: claim for claim in claims_of(manifest, iteration=number)}
        assert set(mine) == ({"list_position", "list_size", "confidence", "arrival_late"} if number == 1 else
                             {"list_position", "list_size", "arrival_late"})
        assert (mine["list_position"]["exact_value"], mine["list_size"]["exact_value"]) == (
            answer["list_position"], answer["list_size"])
        assert content["iterations"][number - 1]["list_position"] == answer["list_position"]
        assert mine["arrival_late"]["exact_value"] is False
        for claim in mine.values():
            assert claim["reference"] == {"note": MODEL_NOTE, "proposal_handle": proposal}
            assert claim["source_schema"] == "jev_loop_choice@1"
            assert claim["field_path"].startswith(("answer.", "arrival."))
        assert manifest["chosen"][number - 1] == {"iteration": number, "proposal_handle": proposal,
                                                  "local_ref": answer["local_ref"],
                                                  "local_display": answer["local_display"]}
        assert _md(answer["local_display"]["smiles"]) in markdown
        assert f"- 목록 위치: {answer['list_position']}/{answer['list_size']}" in markdown
    assert claims_of(manifest, "confidence", iteration=1)[0]["exact_value"] == CONFIDENCE
    assert f"(0–1, 과학 값 아님): {_md(str(CONFIDENCE))}" in markdown and "(0–1, 과학 값 아님): 보고 없음" in markdown
    assert claims_of(manifest, iteration=3) == [] and len(manifest["chosen"]) == 2
    assert content["iterations"][2]["decided_by"] == "human"
    # no probability, rank, difference or improvement anywhere; the LJ sentences as fixed lines
    dumped = canonical_json(manifest).decode()
    assert "probabilities" not in dumped and not _number_in(PROBABILITY, dumped) and str(PROBABILITY) not in markdown
    for word in ("rank", "best", "improv", "diff", "delta"):
        assert f'"{word}' not in dumped
    assert manifest["limitation_ids"] == content["limitations"] == ["LJ1", "LJ2", "LJ3", "LJ4", "LJ6", "LJ8"]
    for name in content["limitations"]:
        assert f"\n{L.STATEMENTS[name]}\n" in markdown
    assert MODEL_NOTE in markdown and J.CHOICE_LABEL in markdown
    # reopen and download give the same bytes
    assert selected(served, made["handle"]).json() == made
    download = served.client.get(f"/runs/{LRID}/reports/download", params={"handle": made["handle"]})
    assert download.status_code == 200 and download.content == markdown.encode("utf-8")
    rows = {row["handle"]: row["analysis_type"] for row in served.client.get(f"/runs/{LRID}/reports").json()}
    assert rows == {made["handle"]: "jev_loop"}
    assert SENTINEL not in dumped and SENTINEL not in markdown


# ---------------------------------------------------------------- the protein loop report


def test_the_protein_report_matches_its_summary(protein, serve):
    served = serve(protein, protein["log"])
    content = served.run.store.load(protein["summary"])
    made = built(served, protein["summary"])
    manifest, markdown = made["manifest"], made["markdown"]
    assert (manifest["branch"], manifest["goal"], manifest["end_reason"]) == ("protein", "explore", "ended_by_user")
    assert content["counts"] == {"started": 1, "done": 1, "jev_decided": 1, "human_decided": 0,
                                 "sends_dispatched": 1, "units_charged": 1, "reused_count": 0}
    w = protein["refs"][W]
    index = next(i for i, row in enumerate(content["candidates"]) if row["ref"] == w)
    row = content["candidates"][index]
    dock = content["iterations"][0]["steps"][-1]
    assert (dock["step"], dock["state"]) == ("dock", "completed")
    handle = dock["result_handle"]
    assert handle == published_handle(served, hand_dock_request(protein, protein["model"]))
    first = stored_first_mode(served.run, handle)
    assert row["state"] == "scored" and row["score_kcal_mol"] == first
    pair = claims_of(manifest, None, candidate=index)
    assert sorted((claim["statement_id"], claim["source_handle"], claim["exact_value"], claim["rendered_value"])
                  for claim in pair) == [("candidate_result_score", handle, first, half_up(first)),
                                         ("candidate_score", protein["summary"], first, half_up(first))]
    assert [claim for claim in manifest["claims"] if claim["statement_id"].startswith("candidate")
            and claim["row_selector"]["candidate"] != index] == []        # A and B are pending: no score claim
    proposal = protein["send"]["choice_handle"]
    answer = served.run.store.load(proposal)["answer"]
    mine = {claim["statement_id"]: claim["exact_value"] for claim in claims_of(manifest, iteration=1)}
    assert mine == {"list_position": answer["list_position"], "list_size": answer["list_size"],
                    "confidence": 0.5, "arrival_late": False}
    display = answer["local_display"]
    assert _md(_ref(display["residue"])) in markdown and f"{_md(display['from'])} → {_md(display['to'])}" in markdown
    assert manifest["limitation_ids"] == ["LJ1", "LJ2", "LJ3", "LJ5", "LJ7", "LJ8"]
    assert f"\n{L.LJ7}\n" in markdown and f"\n{L.LJ5}\n" in markdown
    for claim in manifest["claims"]:                       # the computed values never cite a proposal
        assert (claim["evidence_kind"] == "model_response") == (claim["source_schema"] == "jev_loop_choice@1")
    assert R.saved_jev_loop_report(served.run, made["handle"]) == made


# ---------------------------------------------------------------- reading writes nothing and runs nothing


def _forbid(*_args, **_kwargs):
    raise AssertionError("a report path must not run a tool, a job, a send or a process")


def test_building_reopening_downloading_and_listing_run_nothing_and_reads_write_nothing(ligand, serve, monkeypatch):
    served = serve(ligand, ligand["log"])
    with monkeypatch.context() as patch:
        for target, name in ((JobQueue, "submit"), (JobQueue, "start"), (JobQueue, "_supervise"), (Run, "call"),
                             (S, "run_send"), (subprocess, "Popen")):
            patch.setattr(target, name, _forbid)
        made = built(served, ligand["summary"])
        log = served.log()
        for _ in range(2):
            assert selected(served, made["handle"]).json() == made
            for fmt in ("markdown", "json"):
                response = served.client.get(f"/runs/{LRID}/reports/download",
                                              params={"handle": made["handle"], "format": fmt})
                assert response.status_code == 200
            assert served.client.get(f"/runs/{LRID}/reports").status_code == 200
        assert served.log() == log


def test_the_report_reopens_from_an_events_only_copy(ligand, serve):
    made = built(serve(ligand, ligand["log"]), ligand["summary"])
    raw = (api_module.RUNS_DIR / LRID / "events.jsonl").read_bytes()
    copy_served = serve(ligand, raw, name="events_only")
    assert selected(copy_served, made["handle"]).json() == made


# ---------------------------------------------------------------- refusals


def test_other_runs_other_kinds_and_a_loop_that_has_not_ended_are_refused(ligand, serve):
    served = serve(ligand, ligand["log"])
    log = served.log()
    other = ligand["summary"].replace(LRID, "run_other")
    for handle in (other, ligand["summary"][:-64] + "0" * 64, ligand["sends"][0]["choice_handle"], "not-a-handle"):
        refused(build(served, handle))
    projection = ligand["sends"][0]["projection_handle"]
    for handle in (other, ligand["set"], projection, ligand["sends"][0]["choice_handle"]):   # not a loop summary
        with pytest.raises(EvidenceError, match="jev_loop_result_invalid"):
            R.build_jev_loop_report(served.run, handle)
    assert served.log() == log
    # LABELLED fault injection: the log stopped between the stored summary and the end event (the loop never ended)
    lines = ligand["log"].splitlines(keepends=True)
    cut = b"".join(line for line in lines if json.loads(line)["type"] != L.EVENT_ENDED)
    stopped = serve(ligand, cut, name="stopped")
    assert stopped.run.store.meta(ligand["summary"])["kind"] == L.RESULT_KIND
    log = stopped.log()
    assert "jev_loop_result_invalid" in refused(build(stopped, ligand["summary"]))
    assert stopped.log() == log


def test_a_loop_proposal_cannot_make_an_m24_report_and_its_send_row_names_the_loop(ligand, serve):
    served = serve(ligand, ligand["log"])
    log = served.log()
    send = ligand["sends"][0]
    for handle in (send["choice_handle"], send["send_id"]):                  # the M24 "보고서 만들기" request
        refused(build(served, handle))
    assert "wrong_method_result_kind" in refused(build(served, send["choice_handle"]))
    with pytest.raises(EvidenceError, match="wrong_result_kind"):
        M24.build_jev_report(served.run, send["choice_handle"])
    assert served.log() == log
    rows = served.client.get(f"/runs/{LRID}/jev/sends").json()
    assert {row["send_id"]: row["loop"] for row in rows} == {
        item["send_id"]: {"loop_id": ligand["loop_id"], "iteration": number, "send_ordinal": 0}
        for number, item in enumerate(ligand["sends"], 1)}
    assert all(row["choice_handle"].split("/")[-2] == L.CHOICE_KIND for row in rows)


@pytest.mark.parametrize("edit", [
    "score_value", "result_value", "drop_model_claim", "duplicate_claim", "model_as_computed",
    "computed_cites_model_field", "probabilities_key", "counts", "chosen_display", "scientific_evidence",
    "limitations", "markdown", "snapshot_seq"])
def test_reopening_refuses_an_edited_report(edit, ligand, serve):
    served = serve(ligand, ligand["log"])
    made = built(served, ligand["summary"])
    manifest, markdown = copy.deepcopy(made["manifest"]), made["markdown"]
    claims = manifest["claims"]
    score = next(i for i, c in enumerate(claims) if c["statement_id"] == "candidate_score")
    result = next(i for i, c in enumerate(claims) if c["statement_id"] == "candidate_result_score")
    model = next(i for i, c in enumerate(claims) if c["statement_id"] == "list_position")
    if edit == "score_value":
        claims[score].update(exact_value=claims[score]["exact_value"] - 1.0)
    elif edit == "result_value":
        claims[result].update(rendered_value="0.0")
    elif edit == "drop_model_claim":
        claims.pop(model)
    elif edit == "duplicate_claim":
        claims.append(copy.deepcopy(claims[score]))
    elif edit == "model_as_computed":
        claims[model].update(evidence_kind="computed", reference=None)
    elif edit == "computed_cites_model_field":
        claims[score].update(field_path="answer.list_position")
    elif edit == "probabilities_key":
        manifest["probabilities"] = {"c01": 0.5}
    elif edit == "counts":
        manifest["counts"]["units_charged"] += 1
    elif edit == "chosen_display":
        manifest["chosen"][0]["local_display"]["smiles"] = "C"
    elif edit == "scientific_evidence":
        manifest["external_response"]["scientific_evidence"] = True
    elif edit == "limitations":
        manifest["limitations"] = manifest["limitations"][:-1]
    elif edit == "markdown":
        markdown = markdown.replace("목록 위치", "목록  위치")
    else:
        manifest["snapshot"]["event_seq"] = manifest["provenance"]["ended_event_seq"] - 1
    handle = forge(served.run, manifest, markdown)
    refused(selected(served, handle))
    with pytest.raises(EvidenceError):
        R.saved_jev_loop_report(served.run, handle)
    assert R.saved_jev_loop_report(served.run, made["handle"]) == made


def test_mixed_evidence_kinds_probabilities_and_wrong_fields_are_refused(ligand, serve):
    served = serve(ligand, ligand["log"])
    manifest = built(served, ligand["summary"])["manifest"]
    for claim in manifest["claims"]:
        assert R.match_claim(manifest["claims"], copy.deepcopy(claim)) == claim
    first = {claim["statement_id"]: claim for claim in reversed(manifest["claims"])}
    note = first["list_position"]["reference"]
    cases = {
        "computed_cites_model_field": {**first["candidate_score"], "field_path": "answer.confidence"},
        "computed_cites_list_position": {**first["count"], "field_path": "iterations[0].list_position"},
        "model_cites_computed_field": {**first["list_position"], "field_path": "counts.started"},
        "model_as_computed": {**first["confidence"], "evidence_kind": "computed", "reference": None},
        "computed_as_model": {**first["count"], "evidence_kind": "model_response", "reference": note},
        "probability_field": {**first["confidence"], "field_path": "answer.probabilities"},
        "probability_statement": {**first["confidence"], "statement_id": "probabilities"},
        "rank_statement": {**first["candidate_score"], "statement_id": "rank"},
        "computed_with_note": {**first["candidate_score"], "reference": note},
        "model_without_note": {**first["list_size"], "reference": None},
        "changed_score": {**first["candidate_score"], "exact_value": -99.0, "rendered_value": "-99.0"},
        "other_source": {**first["candidate_result_score"], "source_handle": ligand["summary"]},
        "extra_key": {**first["count"], "best": True},
    }
    for name, proposed in cases.items():
        with pytest.raises(EvidenceError):
            R.match_claim(manifest["claims"], proposed)
            pytest.fail(name)


# ---------------------------------------------------------------- wording


@pytest.mark.parametrize("word", FORBIDDEN)
def test_interpretive_wording_is_refused_on_template_lines(word):
    with pytest.raises(EvidenceError):
        R.check_no_interpretation(f"- 바퀴: {word}")


def test_lj_lines_and_the_score_name_are_exempt_and_slot_values_are_not_checked(ligand, serve):
    for sentence in L.STATEMENTS.values():
        R.check_no_interpretation(sentence)
    assert R.INTERPRETIVE.search(L.LJ1) and R.INTERPRETIVE.search(L.LJ2)     # exempt only as whole fixed lines
    with pytest.raises(EvidenceError):
        R.check_no_interpretation(L.LJ1 + " ")
    R.check_no_interpretation(f"| 후보 | {DC.SCORE_COLUMN_LABEL} |")
    R.check_no_interpretation(f"- {DC.SCORE_LABEL}: 모드 1")
    with pytest.raises(EvidenceError):
        R.check_no_interpretation(f"- {DC.SCORE_LABEL} 최저")
    assert M24.INTERPRETIVE.pattern in R.INTERPRETIVE.pattern                # the M24 list, then the loop additions
    manifest = built(serve(ligand, ligand["log"]), ligand["summary"])["manifest"]
    edited = copy.deepcopy(manifest)   # fault injection: an identifier that spells forbidden words sits in a slot
    edited["chosen"][0]["local_display"]["smiles"] = "CCbestrankCC"
    assert "bestrankCC" in R.render_jev_loop_report(edited)
    edited = copy.deepcopy(manifest)   # fault injection: a template text with an interpretive word
    edited["evidence_statement"] += " 최고 후보."
    with pytest.raises(EvidenceError, match="interpretive"):
        R.render_jev_loop_report(edited)


# ---------------------------------------------------------------- the M21 same-condition docking pairs


def _pairs(served: Served, model: str):
    response = served.client.get(f"/runs/{served.rid}/mutation_models/{model}/docking_pairs")
    assert response.status_code == 200, response.text
    return response


def test_only_the_loop_docking_pair_row_gets_the_loop_key_and_other_rows_keep_their_bytes(protein, serve):
    served = serve(protein, protein["log"])
    log = served.log()
    before = json.loads(protein["pairs_before"])
    assert [pair["sides"]["mutant"]["job_id"] for pair in before["pairs"]] == [protein["outside_job"]]
    response = _pairs(served, protein["model"])
    body = response.json()
    assert {key: value for key, value in body.items() if key not in ("total", "pairs")} == {
        key: value for key, value in before.items() if key not in ("total", "pairs")}
    assert body["total"] == 2 and body["pairs"][0] == before["pairs"][0] and "loop" not in body["pairs"][0]
    # the non-loop row is the same bytes in both responses (the app renders JSON compactly, as written here)
    row = json.dumps(before["pairs"][0], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert row in protein["pairs_before"] and row in response.content
    loop_pair = body["pairs"][1]
    assert loop_pair["loop"] == {"loop_id": protein["loop_id"], "iteration": 1}
    assert set(loop_pair) == {"index", "first_submitted_seq", "condition", "both_published", "sides", "loop"}
    mutant, wild = loop_pair["sides"]["mutant"], loop_pair["sides"]["wild_type_reference"]
    dock = protein["content"]["iterations"][0]["steps"][-1]
    assert (mutant["job_id"], mutant["reason_code"], wild["reason_code"]) == (dock["job_id"], "other_side_missing",
                                                                              "not_submitted")
    assert mutant["score_kcal_mol"] is None and mutant["reason"] == mutation_model_reads.PAIR_REASONS[
        "other_side_missing"]
    assert set(mutation_model_reads.PAIR_REASONS) == {
        "not_submitted", "job_not_finished", "job_failed", "job_cancelled", "job_interrupted", "result_invalid",
        "other_side_missing", "no_modes"}
    assert served.log() == log                                                  # the read writes nothing


def test_a_docking_submitted_before_its_loop_approval_adopted_it_has_no_loop_key(protein, serve):
    served = serve(protein, protein["before_loop"])
    w = protein["refs"][W]
    loop_id = served.create(protein_loop(protein, (W, A), cap=2))
    assert served.compute(loop_id, iteration=1, candidate=w).status_code == 200          # the stored model, adopted
    outside = served.submit_job(DC.PROTOCOL, hand_dock_request(protein, protein["model"]), 300)
    started = served.client.post(f"/runs/{served.rid}/jobs/{outside['job_id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "done", started.text
    response = served.compute(loop_id, iteration=1)                                    # the docking, adopted
    assert response.status_code == 200, response.text
    approved = served.events(L.EVENT_COMPUTE_APPROVED)[-1]
    assert (approved["step"], approved["units"]) == ("dock", 0)
    pairs = _pairs(served, protein["model"]).json()["pairs"]
    adopted = next(pair for pair in pairs if pair["sides"]["mutant"]["job_id"] == outside["job_id"])
    assert "loop" not in adopted and all("loop" not in pair for pair in pairs)
    # its loop report reads the adopted docking as the candidate's result
    record, _content = end_loop(served, loop_id, "ended_by_user")
    manifest = built(served, record["result_handle"])["manifest"]
    result = claims_of(manifest, "candidate_result_score")
    assert [claim["source_handle"] for claim in result] == started.json()["output_handles"]


# ---------------------------------------------------------------- module boundaries


def test_the_report_module_imports_no_send_module_and_names_no_send_or_limit_path():
    for name in ("jev_loop_reports.py", "mutation_model_reads.py"):
        text = (MW / name).read_text()
        assert "raise_limits" not in text and "limit_approval" not in text, name
        tree = ast.parse(text)
        modules = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        modules |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert not {m for m in modules if "jev_sends" in m or "egress" in m or m == "jev_reports"}, (name, modules)
        names = {node.id if isinstance(node, ast.Name) else node.attr for node in ast.walk(tree)
                 if isinstance(node, (ast.Name, ast.Attribute))}
        assert not names & {"run_send", "request_science", "SCIENCE_GATE", "begin_send", "JobQueue" if name ==
                            "jev_loop_reports.py" else "run_send"}, name
        for event in (J.EVENT_CONSENT, J.EVENT_APPROVED, J.EVENT_DISPATCH, J.EVENT_OUTCOME, *L.EVENT_TYPES):
            assert f'"{event}"' not in text, (name, event)
    code = ("import sys, mw.jev_loop_reports, mw.mutation_model_reads\n"
            "print([m for m in ('httpx', 'mw.jev_sends', 'mw.egress', 'mw.jev_reports', 'rdkit', 'openmm', "
            "'pdbfixer') if m in sys.modules])\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
