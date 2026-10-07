"""Options, the real-call plan and its budget, live-call counting and guard, the ledger and its rehearsal, case and
ledger judgement, evidence searches, wording check, --finalize and regression chain of
scripts/m25_offscreen_acceptance.py (no services run here; nothing is sent)."""

import argparse
import ast
import json
import re
import runpy
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from scripts import m25_offscreen_acceptance as m25

REPO = Path(m25.__file__).resolve().parents[1]
FLOW = REPO / "frontend/tests/offscreen" / m25.FLOW
REAL_LEDGER_PATH = m25.ledger_path
ENV = {**{key: True for key in (*m25.ENVIRONMENTS, *m25.CAPABILITIES)}, "loopLigand": True, "loopProtein": True,
       "fixtureServer": True, "setup": True, "keyAvailable": True, "dotenvPrivate": True, "liveState": True}
CHECKS = {"keyScan": {"ok": True}, "wordingScan": {}, "fixtureProof": {"ok": True}, "liveCount": {"ok": True},
          "calibration": {"ok": True}, "liveLedger": {"ok": True}, "budget": {"ok": True},
          "shuffle": {"planned": True, "ok": True}}
SERVER = {"schema": "m25_jev_loop_fixture_server@1", "fixture": True,
          "scienceGate": "EgressGate(httpx.MockTransport scripted, sentinel credential)",
          "viewerGate": "EgressGate(httpx.MockTransport refusing, no credential)",
          "defaultGate": "EgressGate defaults: httpx.MockTransport refusing, resolver without a credential"}
DISPATCH = {"type": "jev_science_dispatch_started", "send_id": "s", "audit_id": "eg_x"}
SCIENCE_RESPONSE = {"type": "egress", "stage": "response_received", "scope": "science", "audit_id": "eg_x"}
VIEWER_RESPONSE = {"type": "egress", "stage": "response_received", "audit_id": "eg_y"}


def _cases(phase, step):
    return [m25.ROW_CASE.get(case, case) for case, modes in m25.case_plan(phase).items() if step in modes]


def _row(step, phase="fixture", cases=None, status="pass", external=0):
    found = _cases(phase, m25.m13.step_base(step)[0]) if cases is None else cases
    return {"step": step, "status": status, "externalRequestCount": external,
            "cases": {case: "pass" for case in found} if isinstance(found, list) else found}


def _rows(phase="fixture"):
    return [_row(step, phase) for step in m25.PHASE_STEPS[phase]]


def _judge(phase="fixture", rows=None, leftovers=(), environment=None, checks=None, rehearsal=False):
    return m25.assemble(_rows(phase) if rows is None else rows, list(leftovers),
                        ENV if environment is None else environment, phase, CHECKS if checks is None else checks,
                        rehearsal)


def _args(**override):
    values = {"root": str(REPO / "runs/m25-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m25-test-out"), "code_root": str(REPO), "build": "never", "phase": "fixture",
              "live_calls": 0, "regressions": False, "kbase": None, "finalize": False, "rehearse": False}
    return argparse.Namespace(**{**values, **override})


def _events(folder, run, lines):
    path = folder / run / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        for line in lines:
            out.write(json.dumps(line) + "\n")


def _node(script, *args):
    return json.loads(subprocess.run(["node", "-e", script, *args], capture_output=True, text=True,
                                     check=True).stdout)


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """No test reads or writes the repository's real-call ledger: every Runner gets a ledger in tmp_path."""
    path = tmp_path / "ledger" / m25.LEDGER_NAME
    monkeypatch.setattr(m25, "ledger_path", lambda code=None: path)
    return path


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


# ----- options -------------------------------------------------------------------------------------------------------
def test_live_calls_default_zero_and_at_most_eight():
    parser = m25.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.phase, args.live_calls, args.build, args.regressions, args.kbase, args.rehearse, args.finalize) == (
        "fixture", 0, "auto", False, None, False, False)
    assert parser.parse_args(["--root", "r", "--artifacts", "a", "--live-calls", "8"]).live_calls == 8
    for bad in ("9", "-1", "100", "two", "1.5"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--root", "r", "--artifacts", "a", "--live-calls", bad])
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--phase", "rehearse"])
    with pytest.raises(argparse.ArgumentTypeError, match="0..8"):
        m25.live_calls_arg("9")
    assert m25.MAX_LIVE_CALLS == 8


def test_phases_need_their_live_calls_and_regressions_need_the_fixture_phase(kbase):
    with pytest.raises(SystemExit, match="calibrate"):
        m25.Runner(_args(phase="calibrate", live_calls=0))
    with pytest.raises(SystemExit, match="live"):
        m25.Runner(_args(phase="live", live_calls=1))
    assert m25.Runner(_args(phase="calibrate", live_calls=1)).live_calls == 1
    assert m25.Runner(_args(phase="live", live_calls=8)).phase == "live"
    with pytest.raises(SystemExit, match="fixture phase"):
        m25.Runner(_args(phase="calibrate", live_calls=2, regressions=True, kbase=kbase))
    with pytest.raises(SystemExit, match="kbase"):
        m25.Runner(_args(regressions=True))


def test_rehearse_is_for_the_real_call_phases_and_writes_its_evidence_inside_the_root():
    with pytest.raises(SystemExit, match="--rehearse"):
        m25.Runner(_args(rehearse=True))
    runner = m25.Runner(_args(phase="calibrate", live_calls=8, rehearse=True, out=None))
    assert runner.rehearse is True and runner.out == runner.root / "out-calibrate"
    assert runner.ledger_location() == runner.root / m25.REHEARSAL_LEDGER_NAME
    assert m25.Runner(_args(phase="live", live_calls=8, rehearse=True, out=None)).out.name == "out-live"
    final = m25.Runner(_args(phase="calibrate", finalize=True, rehearse=True, out=None))
    assert final.out.name == "out-calibrate-finalize"


def test_default_out_is_the_m25_qa_folder_per_phase():
    runner = m25.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m25-jev-loop-") and runner.out.name == "acceptance-fixture"
    assert runner.out.parent.parent == REPO / "docs/qa"
    assert m25.Runner(_args(out=None, phase="calibrate", live_calls=1)).out.name == "acceptance-calibrate"
    assert m25.Runner(_args(out=None, phase="calibrate", finalize=True)).out.name == "acceptance-calibrate"
    assert m25.Runner(_args(phase="calibrate", live_calls=1)).ledger_location() == m25.ledger_path()


def test_finalize_is_a_calibrate_option_that_takes_no_live_calls():
    parser = m25.build_parser()
    args = parser.parse_args(["--root", "r", "--artifacts", "a", "--phase", "calibrate", "--finalize"])
    assert (args.phase, args.finalize, args.live_calls) == ("calibrate", True, 0)
    for phase, calls in (("fixture", 0), ("live", 0), ("live", 8), ("calibrate", 1), ("calibrate", 8)):
        with pytest.raises(SystemExit, match="--finalize"):
            m25.Runner(_args(phase=phase, live_calls=calls, finalize=True))
    assert m25.Runner(_args(phase="calibrate", finalize=True)).finalize is True


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    for bad in ("/tmp/m25-qa", "/private/tmp/m25-qa"):
        with pytest.raises(SystemExit, match="/tmp"):
            m25.Runner(_args(**{field: bad}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m25.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m25.Runner(_args(artifacts=str(REPO / "docs/qa/m25-not-ignored")))


# ----- counting and the live guard ---------------------------------------------------------------------------------
def test_count_events_per_run(tmp_path):
    _events(tmp_path, "run_aa", [DISPATCH, SCIENCE_RESPONSE, {"type": "jev_send_outcome", "send_id": "s"}, DISPATCH,
                                 {"type": "egress", "stage": "dispatch_started", "audit_id": "eg_x"}])
    _events(tmp_path, "run_bb", [VIEWER_RESPONSE])
    (tmp_path / "not_a_run").mkdir()
    (tmp_path / "not_a_run/events.jsonl").write_text(json.dumps(DISPATCH) + "\n")
    counts = m25.count_events(tmp_path)
    assert counts == {"run_aa": {"dispatch": 2, "responseReceived": 1, "scienceResponses": 1},
                      "run_bb": {"dispatch": 0, "responseReceived": 1, "scienceResponses": 0}}
    assert m25.dispatch_total(counts) == 2


def test_live_count_bounds_total_responses_and_each_run_by_its_plan():
    counts = {"run_l": {"dispatch": 5, "responseReceived": 5}, "run_p": {"dispatch": 3, "responseReceived": 3}}
    bound = {"run_l": 5, "run_p": 3}
    assert m25.live_count_ok(counts, 8, bound) is True
    assert m25.live_count_ok(counts, 7, bound) is False                                     # 8 dispatches > 7
    assert m25.live_count_ok(counts, 8, {"run_l": 4, "run_p": 4}) is False                  # run L over its plan
    assert m25.live_count_ok(counts, 8, {"run_l": 5}) is False                              # an unplanned run sent
    assert m25.live_count_ok({"run_l": {"dispatch": 1, "responseReceived": 2}}, 1, 1) is False   # a response not sent
    assert m25.live_count_ok({}, 0, {}) is True


def test_watch_stops_the_harness_group_once_the_count_passes_the_limit(tmp_path):
    runs = tmp_path / "runs"
    _events(runs, "run_aa", [DISPATCH])
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    started = time.monotonic()

    def late_dispatch():
        time.sleep(0.6)
        _events(runs, "run_aa", [DISPATCH])

    writer = threading.Thread(target=late_dispatch)
    writer.start()
    rc, exceeded = m25.watch_process(proc, runs, 1, timeout_s=30, poll_s=0.1)
    writer.join()
    assert exceeded == {"run_aa": {"dispatch": 2, "responseReceived": 0, "scienceResponses": 0}}
    assert rc == -15 and proc.poll() is not None and time.monotonic() - started < 15
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"], start_new_session=True)
    assert m25.watch_process(proc, runs, 2, timeout_s=30, poll_s=0.05) == (3, None)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    assert m25.watch_process(proc, runs, None, timeout_s=0.3, poll_s=0.05) == (-9, None)


# ----- the real-call plan and its budget ------------------------------------------------------------------------------
def test_the_plan_is_eight_sends_calibrate_ligand_exploit_protein_then_the_shuffle_check():
    plan = m25.LIVE_PLAN
    assert m25.plan_sends(plan) == m25.MAX_LIVE_CALLS == 8
    calibrate, ligand, protein, shuffle = plan
    # calibrate: ligand explore, a pool of 5-6, one iteration up to the JEV selection (no computation)
    assert (calibrate["branch"], calibrate["goal"], calibrate["rounds"], calibrate["compute"]) == ("ligand", "explore",
                                                                                                  1, False)
    assert 5 <= len(calibrate["pool"]) <= 6
    # ligand exploit: 3 iterations, real docking each; protein: 3 iterations in the other run
    assert (ligand["branch"], ligand["goal"], ligand["rounds"], ligand["compute"], ligand["run"]) == (
        "ligand", "exploit", 3, True, "L")
    assert (protein["branch"], protein["rounds"], protein["compute"], protein["run"]) == ("protein", 3, True, "P")
    assert not set(ligand["pool"]) & set(calibrate["pool"])        # the shuffle pool stays uncomputed
    # shuffle: same pool and goal as the calibrate loop, another loop seed, its first iteration, one send
    assert (shuffle["pool"], shuffle["goal"], shuffle["rounds"], shuffle["compareWith"]) == (
        calibrate["pool"], calibrate["goal"], 1, calibrate["id"])
    assert shuffle["loopSeed"] != calibrate["loopSeed"] and shuffle["run"] == calibrate["run"]
    for entry in plan:
        assert entry["sends"] == entry["rounds"] <= entry["cap"] and len(entry["pool"]) - entry["rounds"] + 1 >= 2
    assert all(0 < index < 22 for index in protein["pool"])          # the 1UBQ set has 22; not the N-terminal Met
    assert m25.per_run_sends() == {"L": 5, "P": 3}


def test_plan_for_slices_the_plan_by_phase_and_by_the_calls_left():
    plan = m25.LIVE_PLAN
    assert m25.plan_for("calibrate", 0, 8) == {"entries": plan[:1], "maxDispatch": 1, "maxPerRun": {"L": 5, "P": 3},
                                               "preChecks": True}
    assert m25.plan_for("live", 1, 8) == {"entries": plan[1:], "maxDispatch": 8, "maxPerRun": {"L": 5, "P": 3}}
    assert m25.plan_for("live", 1, 7)["entries"] == plan[1:3]        # 1 + 3 + 3 = 7: the shuffle check does not fit
    assert m25.plan_for("live", 1, 4)["entries"] == plan[1:2]        # an entry is never cut
    assert m25.plan_for("live", 1, 3)["entries"] == []
    assert m25.plan_for("live", 8, 8)["entries"] == []


def test_plan_budget_per_run_against_the_run_defaults():
    assert m25.reserve_tokens(12_288) == 4096 + 8192 and m25.reserve_tokens(10**6) == 50_000
    found = m25.plan_budget()
    assert found["ok"] is True
    assert found["needs"]["L"] == {"expensive_units": 5, "wall_clock_s": 1140, "external_tokens": 5 * 12_288,
                                   "usd": 0.5, "sends": 5}
    assert found["needs"]["P"]["expensive_units"] == 6 and found["needs"]["P"]["wall_clock_s"] == 1260
    assert found["needs"]["P"]["external_tokens"] == 3 * m25.reserve_tokens(32_768) <= 120_000
    heavy = [{**m25.LIVE_PLAN[2], "rounds": 5, "sends": 5, "cap": 5, "pool": list(range(1, 8))}]
    short = m25.plan_budget(heavy)
    assert short["ok"] is False and short["short"]["P"] == ["expensive_units", "wall_clock_s", "external_tokens"]


def test_remaining_budget_names_each_short_axis():
    budget = {"expensive_calls": {"used": 2, "limit": 8}, "wall_clock_s": {"used": 100.0, "limit": 1800.0},
              "external_tokens": {"used": 10_000, "limit": 120_000}, "usd": {"used": 0.1, "limit": 2.0}}
    need = {"expensive_units": 6, "wall_clock_s": 1700, "external_tokens": 110_000, "usd": 1.9, "sends": 9}
    assert m25.remaining_ok(need, budget, {"remaining": 9}) == []
    assert m25.remaining_ok({**need, "expensive_units": 7, "sends": 10}, budget, {"remaining": 9}) == [
        "expensive_units", "sends"]


def test_ledger_admission_counts_every_root_and_the_root_allocation():
    assert m25.ledger_admission(0, 0, 1, 8) is None                       # a fresh calibrate root
    assert m25.ledger_admission(0, 1, 7, 8) is None                       # its live phase: 1 + 7 = 8
    assert "ledger counts 1" in m25.ledger_admission(0, 1, 8, 8)
    assert "--live-calls 8" in m25.ledger_admission(1, 0, 1, 8)            # another root spent one: 7 are left
    assert m25.ledger_admission(1, 0, 1, 7) is None
    assert "ledger counts 8" in m25.ledger_admission(8, 0, 1, 1)


# ----- calibration, fixture proof, searches, wording ------------------------------------------------------------------
SEND = {"sendId": "s", "entry": "L-explore-calibrate", "status": "completed", "reasonCode": None, "egressStop": None,
        "servedModel": "typesafe/jev-1.13-20260917", "bodyBytes": 4000, "aliases": 5,
        "usage": {"input_tokens": 2300, "output_tokens": 30, "external_tokens": 2330, "cost": 0.0002},
        "reservation": {"external_tokens": 6763, "usd": 0.1},
        "responseShape": {"answersParsed": True, "confidence": True, "probabilities": True, "probabilityCount": 5}}


def test_calibration_needs_a_completed_send_with_known_usage_within_the_reservation():
    good = m25.calibration({"status": "pass", "sends": [SEND]})
    assert good["ok"] is True and good["withinReservation"] is True and good["adjustmentSuggested"] is False
    assert round(good["bodyBytesPerInputToken"], 3) == round(4000 / 2300, 3)
    assert good["reservedTokensOverUsed"] == 6763 / 2330 and good["responseShape"]["probabilityCount"] == 5
    assert good["reservationFormula"] == m25.RESERVATION_FORMULA and "사용자 결정" in good["adjustmentNote"]
    over = m25.calibration({"status": "pass", "sends": [{**SEND, "usage": {**SEND["usage"], "external_tokens": 7000}}]})
    assert over["ok"] is False and over["adjustmentSuggested"] is True             # recorded, never applied here
    for changed in ({"status": "failed"}, {"egressStop": "usage_unknown"}, {"usage": {**SEND["usage"], "cost": None}},
                    {"usage": {**SEND["usage"], "cost": 0.11}}):
        assert m25.calibration({"status": "pass", "sends": [{**SEND, **changed}]})["ok"] is False, changed
    unknown = m25.calibration({"status": "pass", "sends": [{**SEND, "usage": None}]})
    assert unknown["ok"] is False and unknown["adjustmentSuggested"] is None
    assert m25.calibration({"status": "fail", "sends": [SEND]})["ok"] is False
    assert m25.calibration(None)["ok"] is False and m25.calibration({"status": "pass", "sends": []})["ok"] is False


def test_fixture_proof_matches_every_audit_to_a_scripted_call_and_no_product_key_read():
    calls = [{"status": 200, "authorizationIsSentinel": True}, {"status": 500, "authorizationIsSentinel": True}]
    reads = {"sentinelReads": 2, "productResolverReads": 0}
    proof = m25.fixture_proof(SERVER, calls, 2, 2, reads)
    assert proof["ok"] is True and proof["realProviderCalls"] == 0
    for server, calls_, dispatched, responses, reads_ in (
            (None, calls, 2, 2, reads), ({**SERVER, "fixture": False}, calls, 2, 2, reads),
            ({**SERVER, "schema": "m24_jev_fixture_server@1"}, calls, 2, 2, reads),
            ({**SERVER, "defaultGate": "EgressGate()"}, calls, 2, 2, reads),
            (SERVER, calls[:1], 2, 2, reads), (SERVER, calls, 2, 3, reads),
            (SERVER, [calls[0], {**calls[1], "authorizationIsSentinel": False}], 2, 2, reads),
            (SERVER, calls, 2, 2, {**reads, "productResolverReads": 1}),
            (SERVER, calls, 2, 2, {**reads, "sentinelReads": 3}), (SERVER, calls, 2, 2, None), (SERVER, [], 0, 0, reads)):
        assert m25.fixture_proof(server, calls_, dispatched, responses, reads_)["ok"] is False


def test_forbidden_words_with_the_fixed_lines_instructions_and_score_names_exempt():
    for sentence in (*m25.FIXED_SENTENCES, *m25.INSTRUCTIONS):
        assert m25.forbidden_in(sentence) == []
    assert m25.forbidden_in(f"요약: {m25.FIXED_SENTENCES[0]}") == ["순위", "추천", "예측"]
    assert m25.forbidden_in(m25.SCORE_NAMES[0] + " · " + m25.SCORE_NAMES[1]) == []
    assert m25.forbidden_in("지금까지 최저 점수 · 평균 · 차이 · 증감 · 개선") == ["최저", "평균", "차이", "증감", "개선"]
    assert m25.forbidden_in("목록 위치의 효과 · 편향이 있다 · position bias · an effect") == ["효과", "편향", "bias", "effect"]
    assert m25.forbidden_in("the effective cap · biased? no: unbiased") == ["biased"]
    assert m25.forbidden_in("최적화 · 비활성 · 점수 · 계산") == []


WORDING_PROBES = [*m25.FIXED_SENTENCES, *m25.INSTRUCTIONS, f"요약: {m25.FIXED_SENTENCES[0]}", "비활성\n활성\n활성화",
                  "가장 높음 · 가장 낮음 · highest · lowest · Best · RANKS · ΔΔG", "효과 편향 effect effects bias biased",
                  "effective unbiased", m25.SCORE_NAMES[0], "최솟값 최댓값 평균 차이 증감 좋아짐 승자 recommend improve"]


def test_wording_rule_is_the_harness_rule():
    script = (f"const f=require({json.dumps(str(FLOW))});const probes=JSON.parse(process.argv[1]);"
              "console.log(JSON.stringify({flags:f.FORBIDDEN.flags,fixed:f.FIXED_LINES,instructions:"
              "Object.values(f.INSTRUCTIONS),found:probes.map(p=>f.forbiddenWords(p))}))")
    harness = _node(script, json.dumps(WORDING_PROBES))
    assert harness["flags"] == "gi"
    assert sorted(harness["fixed"]) == sorted(m25.FIXED_SENTENCES)
    assert sorted(harness["instructions"]) == sorted(m25.INSTRUCTIONS)
    # the harness exempts the instruction lines on screen through their element (question and body), the runner by text
    expected = [[] if probe in m25.INSTRUCTIONS else m25.forbidden_in(probe) for probe in WORDING_PROBES]
    found = [[] if probe in m25.INSTRUCTIONS else item for probe, item in zip(WORDING_PROBES, harness["found"],
                                                                                  strict=True)]
    assert found == expected
    source = re.search(r"^const FORBIDDEN = /(.+)/gi;$", FLOW.read_text(), re.MULTILINE).group(1)
    assert source == m25.FORBIDDEN.pattern
    assert m25.FORBIDDEN.flags & re.IGNORECASE and m25.FORBIDDEN.flags & re.ASCII


def test_fixed_sentences_and_instructions_equal_the_product_constants_and_the_harness_copy():
    loop = runpy.run_path(str(REPO / "backend/mw/jev_loop_constants.py"))      # standard library only
    tree = ast.parse((REPO / "backend/mw/jev_constants.py").read_text())
    m24 = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
           for target in node.targets if isinstance(target, ast.Name) and target.id in {"J7", "U3"}}
    product = [*loop["STATEMENTS"].values(), *loop["SCREEN_NOTES"].values(), m24["U3"], m24["J7"]]
    assert list(m25.FIXED_SENTENCES) == product and loop["J7"] == m24["J7"]
    assert list(m25.INSTRUCTIONS) == [loop["INSTRUCTIONS"][key] for key in (("ligand", "explore"), ("ligand", "exploit"),
                                                                            ("mutation", "explore"),
                                                                            ("mutation", "exploit"))]
    flow = _node(f"const f=require({json.dumps(str(FLOW))});console.log(JSON.stringify("
                 "{lj:Object.values(f.LJ),ul:Object.values(f.UL),fixed:f.FIXED_LINES}))")
    assert flow["lj"] == list(loop["STATEMENTS"].values()) and flow["ul"] == list(loop["SCREEN_NOTES"].values())
    assert flow["fixed"] == product


def test_scan_wording_reads_json_strings_and_text_but_not_screens_profiles_or_service_logs(tmp_path):
    (tmp_path / "step").mkdir()
    (tmp_path / "step/row.json").write_text(json.dumps({"limitations": [m25.FIXED_SENTENCES[2]], "note": "fine",
                                                        "question": m25.INSTRUCTIONS[1]}, ensure_ascii=False))
    (tmp_path / "step/rows.jsonl").write_text(json.dumps({"description": "만들기"}) + "\n" +
                                              json.dumps({"text": "best"}) + "\n")
    (tmp_path / "README.md").write_text("# 보고\n" + m25.FIXED_SENTENCES[7] + "\n고른 위치의 효과\n")
    (tmp_path / "services").mkdir()
    (tmp_path / "services/build.log").write_text("ranking chunk\n")
    (tmp_path / "step/browser-profile").mkdir()
    (tmp_path / "step/browser-profile/Preferences.json").write_text('{"best": 1}')
    (tmp_path / "step/L05.dom.txt").write_text("분자량(평균) · 세대별 최솟값·최댓값\n")           # a whole tab as shown
    (tmp_path / "shot.png").write_bytes(b"\x89PNG best")
    body = json.dumps({"model": "typesafe/jev-1.13", "questions": {"q": {"instructions": "the lowest score"}}})
    (tmp_path / "step/L09-failure.panel.html").write_text(
        f'<section><p data-limitation="0">{m25.FIXED_SENTENCES[0]}</p><p>{m25.INSTRUCTIONS[1]}</p>'
        f'<pre>{body}</pre></section>')
    (tmp_path / "step/L10-failure.panel.html").write_text("<div><p>비활성</p><b>순위</b> &amp; 1</div>")
    assert m25.scan_wording(tmp_path) == {"README.md": ["효과"], "step/L10-failure.panel.html": ["순위"],
                                          "step/rows.jsonl": ["best"]}


def test_files_containing_and_the_key_scan_print_only_booleans_counts_and_paths(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/one.json").write_text('{"x": "placeholder-abc"}')
    (tmp_path / "a/two.bin").write_bytes(b"\x00\x01placeholder-abc\x02")
    hits = m25.files_containing([tmp_path / "a", tmp_path / "missing"], [b"placeholder-abc", None])
    assert sorted(Path(item).name for item in hits) == ["one.json", "two.bin"]
    assert "del key" in m25.KEY_SCAN and "print(key" not in m25.KEY_SCAN
    printed = [node for node in ast.walk(ast.parse(m25.KEY_SCAN)) if isinstance(node, ast.Call)
               and getattr(node.func, "id", "") == "print"]
    assert len(printed) == 1


def test_dotenv_status_uses_lstat_only_and_never_reads_the_content(tmp_path):
    assert m25.dotenv_status(tmp_path) == {"present": False, "private": False, "mode": None}
    dotenv = tmp_path / ".env"
    dotenv.write_text("NOT_A_KEY=x\n")
    dotenv.chmod(0o200)                    # write-only: a read would fail, the status still answers
    try:
        assert m25.dotenv_status(tmp_path) == {"present": True, "private": True, "mode": "0o200"}
        dotenv.chmod(0o644)
        assert m25.dotenv_status(tmp_path)["private"] is False
    finally:
        dotenv.chmod(0o600)
    other = tmp_path / "dir"
    (other / ".env").mkdir(parents=True)
    assert m25.dotenv_status(other)["present"] is False
    source = Path(m25.__file__).read_text()
    body = source[source.index("def dotenv_status"):source.index("def fixture_proof")]
    assert "lstat" in body and "read_text" not in body and "open(" not in body


# ----- cases, judgement ----------------------------------------------------------------------------------------------
def test_every_case_has_a_text_and_the_harness_declares_it():
    flow = FLOW.read_text()
    for phase in m25.PHASES:
        plan = m25.case_plan(phase)
        assert set(plan) <= set(m25.CASE_TEXT)
        for case, modes in plan.items():
            assert modes and set(modes) <= set(m25.PHASE_STEPS[phase])
            assert f'"{m25.ROW_CASE.get(case, case)}"' in flow, case
    for mode in set(m25.MODE_OF.values()):
        assert f'"{mode}"' in flow
    assert not set(m25.NOT_OBSERVED_COMMON) & set(m25.CASE_TEXT)
    assert len(m25.FIXTURE_CASES) == len(set(m25.FIXTURE_CASES)) == 52


def test_evidence_texts_carry_no_forbidden_word_and_the_shuffle_is_observation_only():
    texts = [*m25.CASE_TEXT.values(), *m25.RUNNER_CASE_TEXT.values(), *m25.NOT_OBSERVED_COMMON.values(),
             m25.NOT_OBSERVED_LIVE]
    runner = m25.Runner(_args())
    base = {"phase": "fixture", "rehearsal": False, "generatedAt": "t", "verdict": "pass", "acceptance": True,
            "acceptanceScope": "fixture", "liveCalls": 0, "build": {}, "environment": ENV, "checks": CHECKS,
            "leftoverProcesses": [], "externalRequestsTotal": 0, "cases": _judge()["cases"],
            "notObserved": m25.not_observed("fixture"), "steps": _judge()["steps"]}
    for override in ({}, {"phase": "calibrate", "rehearsal": True, "notObserved": m25.not_observed("calibrate")},
                     {"phase": "live", "notObserved": m25.not_observed("live"), "finalize": {"at": "t"}}):
        texts.append(runner.readme({**base, **override}))
    assert [word for text in texts for word in m25.forbidden_in(text)] == []
    assert "관찰값" in m25.RUNNER_CASE_TEXT["JL-shuffle-observed"]
    flow = FLOW.read_text()
    descriptions = [item.split("async")[0] for item in flow.split("rec_.step(")[1:]]
    assert descriptions and [word for item in descriptions for word in m25.forbidden_in(item)] == []


@pytest.mark.parametrize("phase,rehearsal", [("fixture", False), ("calibrate", False), ("live", False),
                                             ("calibrate", True), ("live", True)])
def test_all_passing_rows_pass(phase, rehearsal):
    judged = _judge(phase, rehearsal=rehearsal)
    assert judged["passed"] is True, judged
    assert m25.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True
    assert m25.acceptance_ok(judged["passed"], {"buildCurrentWithSource": False}) is False
    cases = set(judged["cases"])
    assert {"S-browser-egress-zero", "S-key-absent", "S-wording-evidence"} <= cases
    assert ("S-real-calls-zero" in cases) == (phase == "fixture" or rehearsal)
    assert ({"JL-count", "JL-ledger", "JL-budget", "JL-calibration"} <= cases) == (phase != "fixture")
    assert ("JL-shuffle-observed" in cases) == (phase == "live")
    if phase == "fixture":
        assert judged["notObserved"]["JL-live-sends"] == m25.NOT_OBSERVED_LIVE


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["P-pair-loop"]
    judged = _judge(rows=rows)
    assert judged["cases"]["P-pair-loop"]["status"] == "fail" and judged["passed"] is False
    rows = _rows("calibrate")
    rows[0]["cases"]["JL-calibrate"] = "fail"
    assert _judge("calibrate", rows=rows)["cases"]["JL-calibrate-send"]["status"] == "fail"


def test_missing_step_and_browser_egress_fail():
    judged = _judge(rows=[])
    assert judged["steps"]["jev-loop-fixture"]["status"] == "missing" and judged["passed"] is False
    for bad in (None, 1):
        judged = _judge(rows=[_row("jev-loop-fixture", external=bad)])
        assert judged["cases"]["S-browser-egress-zero"]["status"] == "fail" and judged["passed"] is False


@pytest.mark.parametrize("phase,rehearsal,checks,case", [
    ("fixture", False, {**CHECKS, "keyScan": {"ok": False}}, "S-key-absent"),
    ("fixture", False, {**CHECKS, "wordingScan": {"x.json": ["best"]}}, "S-wording-evidence"),
    ("fixture", False, {**CHECKS, "fixtureProof": None}, "S-real-calls-zero"),
    ("calibrate", True, {**CHECKS, "fixtureProof": {"ok": False}}, "S-real-calls-zero"),
    ("calibrate", False, {**CHECKS, "liveCount": {"ok": False}}, "JL-count"),
    ("calibrate", False, {**CHECKS, "calibration": {"ok": False}}, "JL-calibration"),
    ("calibrate", False, {**CHECKS, "liveLedger": {"ok": False}}, "JL-ledger"),
    ("calibrate", False, {**CHECKS, "budget": None}, "JL-budget"),
    ("live", False, {**CHECKS, "shuffle": {"planned": True, "ok": False}}, "JL-shuffle-observed"),
    ("live", True, {**CHECKS, "liveLedger": None}, "JL-ledger"),
])
def test_runner_checks_decide_their_cases(phase, rehearsal, checks, case):
    judged = _judge(phase, checks=checks, rehearsal=rehearsal)
    assert judged["cases"][case]["status"] == "fail" and judged["passed"] is False


def test_an_unplanned_shuffle_is_not_a_case():
    assert "JL-shuffle-observed" not in _judge("live", checks={**CHECKS, "shuffle": {"planned": False, "ok": False}})[
        "cases"]
    row = {"shuffle": {"first": {"loopSeed": 101, "order": ["c_a", "c_b"]}, "second": {"loopSeed": 404,
                                                                                      "order": ["c_b", "c_a"]}}}
    assert m25.shuffle_observed(row) is True
    assert m25.shuffle_observed({"shuffle": {**row["shuffle"], "second": {"loopSeed": 101, "order": ["c_a", "c_b"]}}}) \
        is False
    assert m25.shuffle_observed({"shuffle": {**row["shuffle"], "second": {"loopSeed": 9, "order": ["c_a"]}}}) is False
    assert m25.shuffle_observed(None) is False


@pytest.mark.parametrize("phase,rehearsal,missing", [
    ("fixture", False, "fixtureServer"), ("fixture", False, "setup"), ("fixture", False, "qvina"),
    ("fixture", False, "loopProtein"), ("calibrate", False, "keyAvailable"), ("calibrate", False, "dotenvPrivate"),
    ("calibrate", True, "fixtureServer"), ("live", False, "liveState"), ("live", True, "liveState"),
    ("live", False, "modelAvailable"),
])
def test_environment_must_be_present(phase, rehearsal, missing):
    judged = _judge(phase, environment={**ENV, missing: False}, rehearsal=rehearsal)
    assert judged["verdictParts"]["environment"] is False and judged["passed"] is False


def test_a_rehearsal_does_not_need_the_key():
    environment = {**ENV, "keyAvailable": False, "dotenvPrivate": False}
    assert m25.environment_ok(environment, "calibrate", rehearsal=True) is True
    assert m25.environment_ok(environment, "calibrate", rehearsal=False) is False


def test_leftovers_fail_and_latest_attempt_decides():
    assert _judge(leftovers=["port 8000 still listening: pid 1"])["passed"] is False
    failed = _row("jev-loop-fixture", status="fail", cases={case: "fail" for case in m25.FIXTURE_CASES})
    judged = _judge(rows=[failed, _row("jev-loop-fixture-20261007T120000000000")])
    assert judged["steps"]["jev-loop-fixture"]["latest"] == "jev-loop-fixture-20261007T120000000000"
    assert judged["passed"] is True


# ----- regression chain, boundaries ------------------------------------------------------------------------------------
def test_regression_chain_is_opt_in_and_uses_fresh_folders(kbase):
    commands = dict(m25.Runner(_args(regressions=True, kbase=kbase)).regression_commands())
    assert list(commands) == ["m24", "m23", "m22", "m21", "m20", "m19", "m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m25-test-root-{name}-regression")
        assert argv[argv.index("--artifacts") + 1].endswith(f"regressions/{name}")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m20", "m16", "m15"))
        for flag in ("--regressions", "--live-calls", "--phase", "--rehearse"):
            assert flag not in argv                 # the M24 runner runs its fixture phase (no call)
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m25.Runner(_args()).regressions is False


def test_runner_never_imports_mw_never_posts_and_never_reads_the_m24_ledger():
    source = Path(m25.__file__).read_text()
    tree = ast.parse(source)
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "api"]
    assert calls and all(isinstance(node.args[0], ast.Constant) and node.args[0].value == "GET" for node in calls)
    for text in ("/jev/consent", "/jev/sends\"", "limit_approval", "raise_limits", "m24-live-ledger",
                 ".env\").read", "dotenv_values"):
        assert text not in source, text


def test_harness_never_posts_itself_and_the_fixture_files_never_use_the_real_gate():
    flow = FLOW.read_text()
    assert "page.request.post" not in flow and "page.request.fetch" not in flow and ".dispatchEvent(" not in flow
    server = (REPO / m25.FIXTURE_SERVER).read_text()
    assert "product_api.SCIENCE_GATE = EgressGate(transport=httpx.MockTransport(controller.transport)" in server
    assert f'SENTINEL = "{m25.SENTINEL}"' in server
    assert "env_or_root_dotenv_key" not in server and "OPENROUTER" not in server and ".env" not in server.replace(
        "never reads ``.env``", "").replace("never .env", "")
    setup = (REPO / m25.QA_SETUP).read_text()
    tree = ast.parse(setup)
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
    assert not re.search(r'"/runs/[^"]*jev', setup) and not re.search(r'f"/runs/[^"]*jev', setup)
    script = (f"const f=require({json.dumps(str(FLOW))});console.log(JSON.stringify({{modes:f.MODES,max:f.MAX_LIVE_CALLS}}))")
    assert _node(script) == {"modes": ["fixture", "calibrate", "live"], "max": m25.MAX_LIVE_CALLS}


def test_the_harness_takes_the_runner_plan_as_written():
    setup = {"runs": {"L": {"run": "run_l"}, "P": {"run": "run_p"}}}
    for phase, used in (("calibrate", 0), ("live", 1)):
        plan = m25.plan_for(phase, used, 8)
        mapped = {**plan, "maxPerRun": {setup["runs"][key]["run"]: value for key, value in plan["maxPerRun"].items()}}
        script = (f"const f=require({json.dumps(str(FLOW))});f.checkPlan(JSON.parse(process.argv[1]),"
                  "JSON.parse(process.argv[2]));console.log('true')")
        assert _node(script, json.dumps(mapped), json.dumps(setup)) is True
    bad = {**m25.plan_for("live", 1, 8), "maxPerRun": {"run_l": 5}, "maxDispatch": 9}
    script = (f"const f=require({json.dumps(str(FLOW))});"
              "f.checkPlan(JSON.parse(process.argv[1]),JSON.parse(process.argv[2]))")
    done = subprocess.run(["node", "-e", script, json.dumps(bad), json.dumps(setup)], capture_output=True, text=True,
                          check=False)
    assert done.returncode != 0 and "maxDispatch" in done.stderr


# ----- the repository-level real-call ledger (every root, every phase) ---------------------------------------------------
def _ledger_file(path, roots):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": roots}))


def _phase(phase="calibrate", finished=True):
    return {"phase": phase, "startedAt": "2026-10-07T00:00:00+00:00",
            "finishedAt": "2026-10-07T00:01:00+00:00" if finished else None, "planned": 1}


def test_the_ledger_is_one_git_ignored_m25_file_of_the_main_checkout():
    path = REAL_LEDGER_PATH(REPO)
    main = Path(subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO,
                               capture_output=True, text=True, check=True).stdout.strip()).parent
    assert path == main / "runs" / "m25-live-ledger.json"
    assert subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=main, check=False).returncode == 0
    with pytest.raises(m25.LedgerError, match="git"):
        REAL_LEDGER_PATH(Path("/"))


def test_ledger_total_adds_every_root_and_counts_their_dispatch_events(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _events(a / "runs", "run_a1", [DISPATCH])
    _events(b / "runs", "run_b1", [DISPATCH, DISPATCH, SCIENCE_RESPONSE])
    ledger = {"schema": m25.LEDGER_SCHEMA, "roots": {
        str(a): {"phases": [_phase()], "dispatch": {"run_a1": 1}},
        str(b): {"phases": [_phase(finished=False)], "dispatch": {}}}}
    assert m25.ledger_total(ledger) == 3 and m25.ledger_total(ledger, exclude=b) == 1
    _events(a / "runs", "run_a1", [DISPATCH])                              # events only grow: the larger count wins
    assert m25.ledger_total(ledger) == 4
    shutil.rmtree(a)                                                       # a finished root that is gone keeps its record
    assert m25.ledger_total(ledger) == 3
    _events(c / "runs", "run_c1", [DISPATCH])
    assert m25.ledger_total(ledger, (c,)) == 4
    shutil.rmtree(b)
    with pytest.raises(m25.LedgerError, match="unfinished"):
        m25.ledger_total(ledger)


def test_a_damaged_or_unreadable_ledger_is_refused(tmp_path):
    path = tmp_path / "ledger.json"
    assert m25.read_ledger(path) == {"schema": m25.LEDGER_SCHEMA, "roots": {}}
    good = {"phases": [_phase()], "dispatch": {"run_a1": 1}}
    for bad in ("{", "[]", "null", json.dumps({"schema": "m24_live_ledger@1", "roots": {}}),
                json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": []}),
                json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": {}, "extra": 1}),
                json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": {"relative/root": good}}),
                json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": {"/r": {**good, "dispatch": {"run_a1": -1}}}}),
                json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": {"/r": {**good, "dispatch": {"x": 1}}}}),
                json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": {"/r": {**good, "phases": [{"phase": "fixture"}]}}})):
        path.write_text(bad)
        with pytest.raises(m25.LedgerError):
            m25.read_ledger(path)
    path.write_text(json.dumps({"schema": m25.LEDGER_SCHEMA, "roots": {"/r": good}}))
    assert m25.read_ledger(path)["roots"]["/r"] == good


@pytest.fixture
def qa_base():
    """A git-ignored QA folder inside the repository (the runner refuses tracked artifacts and /tmp), removed after."""
    base = REPO / "runs" / f"pytest-m25-ledger-{uuid.uuid4().hex[:12]}"
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _stubbed(monkeypatch, base, name, phase, live_calls=0, dispatches=1, crash=False, rehearse=False):
    """A Runner whose build, services, harness steps, searches and export are stubs; its phase writes ``dispatches``
    jev_science_dispatch_started events into one run of its root (then crashes when ``crash``)."""
    root, attempt = base / name, f"{name}-{phase}-{uuid.uuid4().hex[:8]}"
    runner = m25.Runner(_args(root=str(root), artifacts=str(base / "artifacts" / attempt),
                              out=str(base / "out" / attempt), phase=phase, live_calls=live_calls, rehearse=rehearse))
    monkeypatch.setattr(m25.m13, "listening", lambda port: [])
    monkeypatch.setattr(m25.m13, "build_is_current", lambda frontend: True)
    for method in ("build", "start_frontend", "stop_all", "export"):
        monkeypatch.setattr(runner, method, lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "leftovers", list)
    monkeypatch.setattr(runner, "key_scan", lambda roots: {"ok": True, "keyAvailable": True, "keyHits": [],
                                                           "sentinelHits": []})

    def harness():
        _events(runner.runs, f"run_{uuid.uuid4().hex}", [DISPATCH] * dispatches)
        if crash:
            raise RuntimeError("harness crashed after its sends")
    for method in ("run_fixture", "run_calibrate", "run_live"):
        monkeypatch.setattr(runner, method, harness)
    return runner


def _calibrated(root, rehearsal=False):
    root.mkdir(parents=True, exist_ok=True)
    (root / "live-state.json").write_text(json.dumps({"calibration": {"ok": True}, "livePhaseRan": False,
                                                      "rehearsal": rehearsal, "setup": str(root / "live-setup.json")}))


def test_real_phases_add_their_event_counts_and_the_allocation_is_eight(monkeypatch, qa_base, isolated_ledger):
    _stubbed(monkeypatch, qa_base, "fixture", "fixture", dispatches=5).run()      # not a real call: nothing written
    assert not isolated_ledger.exists()
    first = _stubbed(monkeypatch, qa_base, "calibrate-1", "calibrate", live_calls=8)
    first.run()
    entry = json.loads(isolated_ledger.read_text())["roots"][str(first.root)]
    assert sum(entry["dispatch"].values()) == 1 and entry["phases"][0]["finishedAt"] is not None
    assert (first.checks["liveLedger"]["before"], first.checks["liveLedger"]["after"]) == (0, 1)
    # live on that root plans 7 (1 + 7 = 8): allowed and recorded
    _calibrated(first.root)
    live = _stubbed(monkeypatch, qa_base, "calibrate-1", "live", live_calls=8, dispatches=7)
    live.run()
    assert m25.ledger_total(m25.read_ledger(isolated_ledger)) == 8
    assert live.checks["liveLedger"]["planned"] == 7 and live.checks["liveLedger"]["after"] == 8
    # the allocation is used up: a new calibrate root is refused, whatever its --live-calls
    refused = _stubbed(monkeypatch, qa_base, "calibrate-2", "calibrate", live_calls=1)
    with pytest.raises(SystemExit, match="ledger counts 8"):
        refused.run()
    assert not (refused.artifacts / "runner-summary.jsonl").exists() and not refused.runs.exists()


def test_a_crashed_phase_is_still_counted_and_live_calls_cannot_pass_what_is_left(monkeypatch, qa_base,
                                                                                  isolated_ledger):
    crashed = _stubbed(monkeypatch, qa_base, "calibrate-1", "calibrate", live_calls=3, crash=True)
    with pytest.raises(RuntimeError, match="crashed"):
        crashed.run()
    assert m25.ledger_total(m25.read_ledger(isolated_ledger)) == 1
    with pytest.raises(SystemExit, match="--live-calls 8"):                  # 1 spent by another root: 7 are left
        _stubbed(monkeypatch, qa_base, "calibrate-2", "calibrate", live_calls=8).run()
    _stubbed(monkeypatch, qa_base, "calibrate-3", "calibrate", live_calls=7).run()
    assert m25.ledger_total(m25.read_ledger(isolated_ledger)) == 2


def test_a_rehearsal_writes_only_its_own_ledger_inside_the_root(monkeypatch, qa_base, isolated_ledger):
    runner = _stubbed(monkeypatch, qa_base, "rehearsal", "calibrate", live_calls=8, rehearse=True)
    runner.run()
    assert not isolated_ledger.exists()                                    # the repository ledger is never touched
    own = runner.root / m25.REHEARSAL_LEDGER_NAME
    assert m25.ledger_total(m25.read_ledger(own)) == 1 and runner.checks["liveLedger"]["rehearsal"] is True
    _calibrated(runner.root, rehearsal=True)
    with pytest.raises(SystemExit, match="a rehearsal"):                    # a rehearsed root never goes live for real
        _stubbed(monkeypatch, qa_base, "rehearsal", "live", live_calls=8).run()
    _stubbed(monkeypatch, qa_base, "rehearsal", "live", live_calls=8, dispatches=7, rehearse=True).run()
    assert m25.ledger_total(m25.read_ledger(own)) == 8 and not isolated_ledger.exists()


def test_a_damaged_ledger_refuses_every_real_phase(monkeypatch, qa_base, isolated_ledger):
    isolated_ledger.parent.mkdir(parents=True, exist_ok=True)
    isolated_ledger.write_text("{not json")
    runner = _stubbed(monkeypatch, qa_base, "calibrate", "calibrate", live_calls=1)
    with pytest.raises(SystemExit, match="ledger"):
        runner.run()
    assert not runner.runs.exists() and isolated_ledger.read_text() == "{not json"
    _stubbed(monkeypatch, qa_base, "fixture", "fixture").run()             # the fixture phase does not read it


# ----- the end of the calibrate phase and --finalize (stored files only; no service, harness or call) -------------------
CALIBRATE_ROW = {"schema": "m25_case_ledger_row@1", "step": "jev-loop-calibrate", "mode": "calibrate", "status": "pass",
                 "rehearsal": False, "cases": {"JL-calibrate": "pass"}, "externalRequestCount": 0, "sends": [SEND],
                 "dispatchCounts": {"run_aa": 1, "run_bb": 0}}
CALIBRATE_ENV = {key: value for key, value in ENV.items() if key != "liveState"}


def test_no_record_call_spreads_a_dict_into_its_keywords():
    tree = ast.parse(Path(m25.__file__).read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "record"]
    assert len(calls) > 10
    assert [ast.unparse(node) for node in calls if any(keyword.arg is None for keyword in node.keywords)] == []
    assert [ast.unparse(node) for node in calls if any(keyword.arg in ("step", "status") for keyword in node.keywords)] == []


def test_run_calibrate_stores_and_records_the_calibration(monkeypatch, qa_base):
    root = qa_base / "calibrate-end"
    runner = m25.Runner(_args(root=str(root), artifacts=str(qa_base / "artifacts" / "calibrate-end"),
                              out=str(qa_base / "out" / "calibrate-end"), phase="calibrate", live_calls=8))
    runner.artifacts.mkdir(parents=True)
    runner.runs.mkdir(parents=True)
    monkeypatch.setattr(runner, "start_phase_backend", lambda: None)
    monkeypatch.setattr(runner, "capabilities_ready", lambda: True)
    monkeypatch.setattr(runner, "key_available", lambda: True)
    monkeypatch.setattr(runner, "check_remaining", lambda ids, entries: True)

    def setup_runs(label):
        target = runner.artifacts / f"setup-{label}.json"
        target.write_text(json.dumps({"schema": "m25_jev_loop_setup@1", "runs": {"L": {"run": "run_aa"},
                                                                                "P": {"run": "run_bb"}}}) + "\n")
        return target

    def flow(step, mode, extra, limit=None):
        assert (step, mode, limit) == ("jev-loop-calibrate", "calibrate", 1)
        plan = json.loads(Path(extra[extra.index("--plan") + 1]).read_text())
        assert plan["maxPerRun"] == {"run_aa": 5, "run_bb": 3} and plan["preChecks"] is True
        assert "--control" not in extra                                    # the real gate (no fixture control)
        _events(runner.runs, "run_aa", [DISPATCH, SCIENCE_RESPONSE])
        _events(runner.runs, "run_bb", [])
        return json.loads(json.dumps(CALIBRATE_ROW))
    monkeypatch.setattr(runner, "setup_runs", setup_runs)
    monkeypatch.setattr(runner, "flow", flow)
    runner.run_calibrate()
    state = json.loads(runner.state_path.read_text())
    assert state["calibration"] == m25.calibration(CALIBRATE_ROW) and state["rehearsal"] is False
    assert (state["calibration"]["ok"], state["livePhaseRan"], state["maxPerRun"]) == (True, False,
                                                                                        {"run_aa": 5, "run_bb": 3})
    assert runner.checks["liveCount"]["ok"] is True
    recorded = [json.loads(line) for line in (runner.artifacts / "runner-summary.jsonl").read_text().splitlines()]
    entry = [item for item in recorded if item["step"] == "calibration"][-1]
    assert (entry["status"], entry["detail"]) == ("pass", state["calibration"])


def _tree_bytes(folder):
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(Path(folder).rglob("*")) if path.is_file()}


def _finished_calibrate(base, ledger_file, name="finished"):
    root, artifacts, out = base / name, base / "artifacts" / name, base / "out" / name
    _events(root / "runs", "run_aa", [DISPATCH, SCIENCE_RESPONSE])
    _events(root / "runs", "run_bb", [])
    setup = json.dumps({"schema": "m25_jev_loop_setup@1", "runs": {}}) + "\n"
    (root / "live-setup.json").write_text(setup)
    (root / "live-state.json").write_text(json.dumps({
        "schema": "m25_jev_loop_live_state@1", "setup": str(root / "live-setup.json"), "rehearsal": False,
        "calibration": m25.calibration(CALIBRATE_ROW), "counts": m25.count_events(root / "runs"),
        "maxPerRun": {"run_aa": 5, "run_bb": 3}, "liveCalls": 8, "livePhaseRan": False,
        "writtenAt": "2026-10-07T00:00:30+00:00"}, indent=2) + "\n")
    (artifacts / "jev-loop-calibrate").mkdir(parents=True)
    (artifacts / "jev-loop-calibrate/ledger-row.json").write_text(json.dumps(CALIBRATE_ROW, indent=2) + "\n")
    (artifacts / "setup-live.json").write_text(setup)
    (artifacts / "runner-state.json").write_text(json.dumps({
        "build": {"buildId": "b", "gitHead": "h", "buildCurrentWithSource": True}, "environment": CALIBRATE_ENV},
        indent=2) + "\n")
    (artifacts / "runner-summary.jsonl").write_text(
        json.dumps({"step": "plan-budget", "status": "pass", "at": "t", "detail": {"ok": True}}) + "\n" +
        json.dumps({"step": "live-ledger", "status": "pass", "at": "t", "detail": {
            "ok": True, "before": 0, "planned": 1, "after": 1, "rootDispatch": 1}}) + "\n")
    _ledger_file(ledger_file, {str(root): {"phases": [_phase()], "dispatch": {"run_aa": 1, "run_bb": 0}}})
    return root, artifacts, out


def _finalizer(monkeypatch, root, artifacts, out):
    runner = m25.Runner(_args(root=str(root), artifacts=str(artifacts), out=str(out), phase="calibrate", live_calls=0,
                              finalize=True))
    monkeypatch.setattr(m25.m13, "listening", lambda port: [])
    monkeypatch.setattr(runner, "leftovers", list)
    monkeypatch.setattr(runner, "key_scan", lambda roots: {"ok": True, "keyAvailable": True, "keyHits": [],
                                                           "sentinelHits": [], "roots": [str(item) for item in roots]})

    def forbidden(*args, **kwargs):
        raise AssertionError("--finalize must not build, start services, post, call, write the ledger or the state")
    for method in ("build", "start_frontend", "start_backend_at", "start_fixture_backend", "start_phase_backend",
                   "flow", "api", "setup_runs", "run_fixture", "run_calibrate", "run_live", "ledger_guard", "execute",
                   "save", "key_available"):
        monkeypatch.setattr(runner, method, forbidden)
    monkeypatch.setattr(m25, "write_ledger", forbidden)
    return runner


def test_finalize_rebuilds_the_calibrate_evidence_from_the_stored_files_only(monkeypatch, qa_base, isolated_ledger):
    root, artifacts, out = _finished_calibrate(qa_base, isolated_ledger)
    ledger_before, root_before = isolated_ledger.read_bytes(), _tree_bytes(root)
    state_before = (artifacts / "runner-state.json").read_bytes()
    assert _finalizer(monkeypatch, root, artifacts, out).run() == 0
    assert isolated_ledger.read_bytes() == ledger_before and _tree_bytes(root) == root_before
    assert (artifacts / "runner-state.json").read_bytes() == state_before
    book = json.loads((artifacts / "case-ledger.json").read_text())
    assert (book["phase"], book["verdict"], book["acceptance"], book["liveCalls"]) == ("calibrate", "pass", True, 8)
    assert {case: value["status"] for case, value in book["cases"].items()} == {
        case: "pass" for case in ("JL-calibrate-send", "S-browser-egress-zero", "S-key-absent", "S-wording-evidence",
                                  "JL-count", "JL-ledger", "JL-budget", "JL-calibration")}
    ledger_check = book["checks"]["liveLedger"]
    assert {key: ledger_check[key] for key in ("ok", "before", "planned", "after", "rootDispatch", "readOnly")} == {
        "ok": True, "before": 0, "planned": 1, "after": 1, "rootDispatch": 1, "readOnly": True}
    assert book["finalize"]["realCalls"] == 0 and book["finalize"]["ledgerSha256"] == m25.m13.sha_bytes(ledger_before)
    readme = (out / "README.md").read_text()
    assert "--finalize" in readme and "acceptance **true**" in readme and m25.forbidden_in(readme) == []


def _set(path, **fields):
    path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))


FINALIZE_REFUSALS = {
    "ledger-absent": (lambda root, art, out, book: book.unlink(), "no record"),
    "ledger-damaged": (lambda root, art, out, book: book.write_text("{"), "ledger"),
    "root-not-recorded": (lambda root, art, out, book: _ledger_file(book, {}), "no record"),
    "phase-unfinished": (lambda root, art, out, book: _ledger_file(book, {str(root): {
        "phases": [_phase(finished=False)], "dispatch": {"run_aa": 1, "run_bb": 0}}}), "finished"),
    "ledger-counts-differ": (lambda root, art, out, book: _ledger_file(book, {str(root): {
        "phases": [_phase()], "dispatch": {"run_aa": 0, "run_bb": 0}}}), "dispatch counts"),
    "events-grew": (lambda root, art, out, book: _events(root / "runs", "run_bb", [DISPATCH]), "dispatch counts"),
    "no-live-state": (lambda root, art, out, book: (root / "live-state.json").unlink(), "live-state"),
    "rehearsal-state": (lambda root, art, out, book: _set(root / "live-state.json", rehearsal=True), "rehearsal"),
    "live-phase-ran": (lambda root, art, out, book: _set(root / "live-state.json", livePhaseRan=True), "live"),
    "calibration-differs": (lambda root, art, out, book: _set(root / "live-state.json", calibration={"ok": True}),
                            "calibration"),
    "no-runner-state": (lambda root, art, out, book: (art / "runner-state.json").unlink(), "runner-state"),
    "no-calibrate-row": (lambda root, art, out, book: (art / "jev-loop-calibrate/ledger-row.json").unlink(),
                         "jev-loop-calibrate"),
    "other-run-artifacts": (lambda root, art, out, book: (art / "setup-live.json").write_text("{}\n"), "setup"),
    "out-not-empty": (lambda root, art, out, book: (out.mkdir(parents=True), (out / "README.md").write_text("kept\n")),
                      "--out"),
}


@pytest.mark.parametrize("case", list(FINALIZE_REFUSALS))
def test_finalize_refuses_before_writing_anything(monkeypatch, qa_base, isolated_ledger, case):
    root, artifacts, out = _finished_calibrate(qa_base, isolated_ledger)
    change, reason = FINALIZE_REFUSALS[case]
    change(root, artifacts, out, isolated_ledger)
    ledger_before = isolated_ledger.read_bytes() if isolated_ledger.exists() else None
    root_before, artifacts_before = _tree_bytes(root), _tree_bytes(artifacts)
    out_before = _tree_bytes(out) if out.exists() else None
    with pytest.raises(SystemExit, match=f"--finalize refused.*{re.escape(reason)}"):
        _finalizer(monkeypatch, root, artifacts, out).run()
    assert (isolated_ledger.read_bytes() if isolated_ledger.exists() else None) == ledger_before
    assert _tree_bytes(root) == root_before and _tree_bytes(artifacts) == artifacts_before
    assert (_tree_bytes(out) if out.exists() else None) == out_before
