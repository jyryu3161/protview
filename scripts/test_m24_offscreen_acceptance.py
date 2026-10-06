"""Options, live-call counting and guard, case and ledger judgement, evidence searches, wording check and regression
chain of scripts/m24_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from scripts import m24_offscreen_acceptance as m24

REPO = Path(m24.__file__).resolve().parents[1]
FLOW = REPO / "frontend/tests/offscreen" / m24.FLOW
PRODUCT_JEV = REPO / "frontend/src/lib/jev.ts"
REAL_LEDGER_PATH = m24.ledger_path
ENV = {"workerPython": True, "ligandAvailable": True, "mutationAvailable": True, "jevAvailable": True,
       "fixtureServer": True, "setup": True, "keyAvailable": True, "liveState": True}
CHECKS = {"keyScan": {"ok": True}, "wordingScan": {}, "fixtureProof": {"ok": True}, "liveCount": {"ok": True},
          "calibration": {"ok": True}, "liveLedger": {"ok": True}}
SERVER = {"fixture": True, "scienceGate": "EgressGate(httpx.MockTransport scripted, sentinel credential)",
          "viewerGate": "EgressGate(httpx.MockTransport refusing, no credential)"}


def _cases(phase, step):
    return [m24.ROW_CASE.get(case, case) for case, modes in m24.case_plan(phase).items() if step in modes]


def _row(step, phase="fixture", cases=None, status="pass", external=0):
    found = _cases(phase, m24.m13.step_base(step)[0]) if cases is None else cases
    return {"step": step, "status": status, "externalRequestCount": external,
            "cases": {case: "pass" for case in found} if isinstance(found, list) else found}


def _rows(phase="fixture"):
    return [_row(step, phase) for step in m24.PHASE_STEPS[phase]]


def _judge(phase="fixture", rows=None, leftovers=(), environment=None, checks=None):
    return m24.assemble(_rows(phase) if rows is None else rows, list(leftovers), ENV if environment is None else environment,
                        phase, CHECKS if checks is None else checks)


def _args(**override):
    values = {"root": str(REPO / "runs/m24-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m24-test-out"), "code_root": str(REPO), "build": "never", "phase": "fixture",
              "live_calls": 0, "regressions": False, "kbase": None, "finalize": False}
    return argparse.Namespace(**{**values, **override})


def _events(folder, run, lines):
    path = folder / run / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        for line in lines:
            out.write(json.dumps(line) + "\n")


DISPATCH = {"type": "jev_science_dispatch_started", "send_id": "s", "audit_id": "eg_x"}
SCIENCE_RESPONSE = {"type": "egress", "stage": "response_received", "scope": "science", "audit_id": "eg_x"}
VIEWER_RESPONSE = {"type": "egress", "stage": "response_received", "audit_id": "eg_y"}


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """No test reads or writes the repository's real-call ledger: every Runner gets a ledger in tmp_path."""
    path = tmp_path / "ledger" / m24.LEDGER_NAME
    monkeypatch.setattr(m24, "ledger_path", lambda code=None: path)
    return path


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


# ----- options -------------------------------------------------------------------------------------------------------
def test_live_calls_default_zero_and_at_most_six():
    parser = m24.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.phase, args.live_calls, args.build, args.regressions, args.kbase) == ("fixture", 0, "auto", False, None)
    assert parser.parse_args(["--root", "r", "--artifacts", "a", "--live-calls", "6"]).live_calls == 6
    for bad in ("7", "-1", "100", "two", "1.5"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--root", "r", "--artifacts", "a", "--live-calls", bad])
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--phase", "rehearse"])
    with pytest.raises(argparse.ArgumentTypeError, match="0..6"):
        m24.live_calls_arg("7")
    assert m24.MAX_LIVE_CALLS == 6 and m24.MAX_PER_RUN == 3


def test_phases_need_their_live_calls_and_regressions_need_the_fixture_phase(kbase):
    with pytest.raises(SystemExit, match="calibrate"):
        m24.Runner(_args(phase="calibrate", live_calls=0))
    with pytest.raises(SystemExit, match="live"):
        m24.Runner(_args(phase="live", live_calls=1))
    assert m24.Runner(_args(phase="calibrate", live_calls=1)).live_calls == 1
    assert m24.Runner(_args(phase="live", live_calls=6)).phase == "live"
    with pytest.raises(SystemExit, match="fixture phase"):
        m24.Runner(_args(phase="calibrate", live_calls=2, regressions=True, kbase=kbase))
    with pytest.raises(SystemExit, match="kbase"):
        m24.Runner(_args(regressions=True))


def test_default_out_is_the_m24_qa_folder_per_phase():
    runner = m24.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m24-jev-") and runner.out.name == "acceptance-fixture"
    assert runner.out.parent.parent == REPO / "docs/qa"
    assert m24.Runner(_args(out=None, phase="calibrate", live_calls=1)).out.name == "acceptance-calibrate"
    assert m24.Runner(_args(out=None, phase="calibrate", finalize=True)).out.name == "acceptance-calibrate"


def test_finalize_is_a_calibrate_option_that_takes_no_live_calls():
    parser = m24.build_parser()
    args = parser.parse_args(["--root", "r", "--artifacts", "a", "--phase", "calibrate", "--finalize"])
    assert (args.phase, args.finalize, args.live_calls) == ("calibrate", True, 0)
    assert parser.parse_args(["--root", "r", "--artifacts", "a"]).finalize is False
    runner = m24.Runner(_args(phase="calibrate", finalize=True))
    assert runner.finalize is True and runner.live_calls == 0
    for phase, calls in (("fixture", 0), ("live", 0), ("live", 6), ("calibrate", 1), ("calibrate", 6)):
        with pytest.raises(SystemExit, match="--finalize"):
            m24.Runner(_args(phase=phase, live_calls=calls, finalize=True))
    assert m24.Runner(_args(phase="calibrate", live_calls=1)).finalize is False


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m24.Runner(_args(**{field: "/tmp/m24-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m24.Runner(_args(**{field: "/private/tmp/m24-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m24.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m24.Runner(_args(artifacts=str(REPO / "docs/qa/m24-not-ignored")))


# ----- counting and the live guard ---------------------------------------------------------------------------------
def test_count_events_per_run(tmp_path):
    _events(tmp_path, "run_aa", [DISPATCH, SCIENCE_RESPONSE, {"type": "jev_send_outcome", "send_id": "s"}, DISPATCH,
                                 {"type": "egress", "stage": "dispatch_started", "audit_id": "eg_x"}])
    _events(tmp_path, "run_bb", [VIEWER_RESPONSE])
    (tmp_path / "not_a_run").mkdir()
    (tmp_path / "not_a_run/events.jsonl").write_text(json.dumps(DISPATCH) + "\n")
    counts = m24.count_events(tmp_path)
    assert counts == {"run_aa": {"dispatch": 2, "responseReceived": 1, "scienceResponses": 1},
                      "run_bb": {"dispatch": 0, "responseReceived": 1, "scienceResponses": 0}}
    assert m24.dispatch_total(counts) == 2


def test_live_count_bounds_total_responses_and_per_run(tmp_path):
    counts = {"run_a": {"dispatch": 3, "responseReceived": 3}, "run_b": {"dispatch": 3, "responseReceived": 3}}
    assert m24.live_count_ok(counts, 6) is True
    assert m24.live_count_ok(counts, 5) is False                                      # 6 dispatches > 5
    assert m24.live_count_ok({"run_a": {"dispatch": 4, "responseReceived": 4}}, 6) is False   # 4 in one run
    assert m24.live_count_ok({"run_a": {"dispatch": 1, "responseReceived": 2}}, 1) is False   # a response not dispatched
    assert m24.live_count_ok({}, 0) is True


def test_watch_stops_the_harness_group_once_the_count_passes_the_limit(tmp_path):
    runs = tmp_path / "runs"
    _events(runs, "run_aa", [DISPATCH])
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    started = time.monotonic()

    def late_dispatch():
        time.sleep(0.6)
        _events(runs, "run_aa", [DISPATCH])

    import threading
    writer = threading.Thread(target=late_dispatch)
    writer.start()
    rc, exceeded = m24.watch_process(proc, runs, 1, timeout_s=30, poll_s=0.1)
    writer.join()
    assert exceeded == {"run_aa": {"dispatch": 2, "responseReceived": 0, "scienceResponses": 0}}
    assert rc == -15 and proc.poll() is not None
    assert time.monotonic() - started < 15


def test_watch_without_a_limit_or_within_it_returns_the_exit_code(tmp_path):
    runs = tmp_path / "runs"
    _events(runs, "run_aa", [DISPATCH])
    proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"], start_new_session=True)
    assert m24.watch_process(proc, runs, 1, timeout_s=30, poll_s=0.05) == (3, None)
    proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    assert m24.watch_process(proc, runs, None, timeout_s=30, poll_s=0.05) == (0, None)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    assert m24.watch_process(proc, runs, None, timeout_s=0.3, poll_s=0.05) == (-9, None)


def test_live_plan_shape_and_phase_slices():
    plan = m24.LIVE_PLAN
    assert len(plan) == m24.MAX_LIVE_CALLS
    per_run = {}
    for index, entry in enumerate(plan):
        per_run[entry["run"]] = per_run.get(entry["run"], 0) + 1
        assert entry["run"] in m24.LIVE_RUNS
        if "resend" in entry:
            source = next(item for item in plan[:index] if item["id"] == entry["resend"])
            assert source["run"] == entry["run"] and plan[index - 1]["id"] == entry["resend"]
        else:
            assert entry["set"] in m24.LIVE_RUNS[entry["run"]] and 1 <= entry["pick"]["first"] <= 20
    assert max(per_run.values()) <= m24.MAX_PER_RUN
    assert plan[0]["kind"] == "ligand" and plan[0].get("report") is True    # the calibrate send makes the report
    checks = m24.PRE_CHECKS
    assert m24.plan_for("calibrate", 0, 6) == {"entries": plan[:1], "maxDispatch": 1, "maxPerRun": 3, "preChecks": checks}
    assert m24.plan_for("live", 1, 6) == {"entries": plan[1:6], "maxDispatch": 6, "maxPerRun": 3}   # no pre-checks
    assert m24.plan_for("live", 1, 3)["entries"] == plan[1:3]
    assert m24.plan_for("live", 6, 6)["entries"] == []
    # the rehearsal is the same two plans, shifted by the fixture dispatch events already in its runs folder
    assert m24.plan_for("rehearsal-calibrate", 0, 1, base=12) == {"entries": plan[:1], "maxDispatch": 13, "maxPerRun": 3,
                                                                   "preChecks": checks}
    assert m24.plan_for("rehearsal-live", 1, 6, base=13) == {"entries": plan[1:6], "maxDispatch": 19, "maxPerRun": 3}
    # the pre-checks use L1's 1UBQ set (a 21st candidate exists), keep 5, and send nothing
    assert checks == {"run": "L1", "kind": "mutation", "set": "ubq", "keep": 5}
    assert checks["set"] in m24.LIVE_RUNS[checks["run"]] and m24.STRUCTURES["ubq"][2] > 20


def test_calibration_needs_a_completed_send_with_known_usage_within_the_reservation():
    send = {"sendId": "s", "entry": "L1-ligand-5", "status": "completed", "reasonCode": None, "egressStop": None,
            "servedModel": "typesafe/jev-1.13-20260917", "bodyBytes": 6000,
            "usage": {"input_tokens": 2600, "output_tokens": 30, "external_tokens": 2630, "cost": 0.0002},
            "reservation": {"external_tokens": 7096, "usd": 0.1}, "responseShape": {"confidence": True}}
    good = m24.calibration({"status": "pass", "sends": [send]})
    assert good["ok"] is True and round(good["bodyBytesPerInputToken"], 3) == round(6000 / 2600, 3)
    assert good["reservedTokensOverUsed"] == 7096 / 2630
    for changed in ({"status": "failed"}, {"egressStop": "usage_unknown"},
                    {"usage": {**send["usage"], "cost": None}},
                    {"usage": {**send["usage"], "external_tokens": 7097}},
                    {"usage": {**send["usage"], "cost": 0.11}}):
        assert m24.calibration({"status": "pass", "sends": [{**send, **changed}]})["ok"] is False, changed
    # the send was fine but the calibrate flow (pre-checks, card, report, other tabs) did not pass: no live phase
    failed_flow = m24.calibration({"status": "fail", "sends": [send]})
    assert failed_flow["ok"] is False and failed_flow["flowPassed"] is False and failed_flow["status"] == "completed"
    assert m24.calibration({"sends": [send]})["ok"] is False
    assert m24.calibration({"status": "pass", "sends": []})["ok"] is False
    assert m24.calibration(None)["ok"] is False
    assert m24.calibration({"status": "pass", "sends": [{"entry": "x", "skipped": "stopped"}]})["ok"] is False


# ----- fixture proof, searches, wording ------------------------------------------------------------------------------
def test_fixture_proof_matches_every_audit_to_a_scripted_call():
    calls = [{"status": 200, "authorizationIsSentinel": True}, {"status": 500, "authorizationIsSentinel": True}]
    counts = {"run_a": {"dispatch": 2, "responseReceived": 2}}
    proof = m24.fixture_proof(SERVER, calls, counts)
    assert proof["ok"] is True and proof["realProviderCalls"] == 0
    for server, calls_, counts_ in (
            (None, calls, counts), ({**SERVER, "fixture": False}, calls, counts),
            ({**SERVER, "scienceGate": "EgressGate()"}, calls, counts),
            (SERVER, calls[:1], counts),                                                   # a dispatch without a call
            (SERVER, calls, {"run_a": {"dispatch": 2, "responseReceived": 3}}),            # a response not scripted
            (SERVER, [calls[0], {**calls[1], "authorizationIsSentinel": False}], counts),
            (SERVER, [], {})):
        assert m24.fixture_proof(server, calls_, counts_)["ok"] is False


def test_forbidden_words_with_the_fixed_lines_exempt():
    for sentence in m24.FIXED_SENTENCES:
        assert m24.forbidden_in(sentence) == []
        assert m24.forbidden_in(f"{sentence}\n{sentence}") == []
    # only a line exactly equal to a fixed sentence is exempt (the product's rule)
    assert m24.forbidden_in(f"카드: {m24.FIXED_SENTENCES[0]}") == ["순위", "추천", "예측"]
    assert m24.forbidden_in("JEV가 고른 후보는 최고의 추천") == ["최고", "추천"]
    assert m24.forbidden_in("the best candidate ranks first; we recommend it") == ["best", "rank", "recommend"]
    assert m24.forbidden_in("frank stabilizer") == []
    assert m24.forbidden_in("점수 · 친화도 · 안정성 · ΔΔG · winner") == ["점수", "친화", "안정성", "ΔΔG", "winner"]
    # spec 2 and 8 terms; 비활성 is a plain word, not 활성
    assert m24.forbidden_in("예측·유망·좋은·나쁜·안전·에너지·활성") == ["예측", "유망", "좋은", "나쁜", "안전", "에너지", "활성"]
    assert m24.forbidden_in("비활성 버튼") == [] and m24.forbidden_in("활성화") == ["활성"]
    assert m24.forbidden_in("가장 높은 값과 가장 낮은 값, highest") == ["가장 높", "가장 낮", "highest"]
    assert m24.forbidden_in("후보best") == ["best"]                   # ASCII word boundary, as in JavaScript


WORDING_PROBES = [*m24.FIXED_SENTENCES, f"요약: {m24.FIXED_SENTENCES[0]}", f" {m24.FIXED_SENTENCES[3]}",
                  "비활성\n활성\n활성화", "가장 높음 · 가장 낮음 · highest · Best · RANKS · ΔΔG", "후보best 순위c01",
                  "순위 추천 최고 최적 개선 예측 유망 점수 에너지 친화 안정성 좋은 나쁜 안전 winner recommend",
                  "bestow frank ranking", "JEV 판정(모델 선택)", "모델 보고 확신도(0–1, 과학 값 아님)"]


def test_wording_rule_is_the_product_rule_and_the_harness_rule():
    literal = re.search(r"^export const JEV_FORBIDDEN = /(.+)/gi;$", PRODUCT_JEV.read_text(), re.MULTILINE)
    assert literal, "JEV_FORBIDDEN literal not found in frontend/src/lib/jev.ts"
    assert m24.FORBIDDEN.pattern == literal.group(1)
    assert m24.FORBIDDEN.flags & re.IGNORECASE and m24.FORBIDDEN.flags & re.ASCII   # \b as in JavaScript (no u flag)
    script = (f"const f=require({json.dumps(str(FLOW))});const probes=JSON.parse(process.argv[1]);"
              "console.log(JSON.stringify({source:f.FORBIDDEN.source,flags:f.FORBIDDEN.flags,"
              "fixed:f.FIXED_LINES,found:probes.map(p=>f.forbiddenWords(p))}))")
    done = subprocess.run(["node", "-e", script, json.dumps(WORDING_PROBES)], capture_output=True, text=True, check=True)
    harness = json.loads(done.stdout)
    assert (harness["source"], harness["flags"]) == (literal.group(1), "gi")
    assert harness["fixed"] == list(m24.FIXED_SENTENCES)
    assert harness["found"] == [m24.forbidden_in(probe) for probe in WORDING_PROBES]


def test_fixed_sentences_equal_the_product_constants_and_the_harness_copy():
    tree = ast.parse((REPO / "backend/mw/jev_constants.py").read_text())
    constants = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 for target in node.targets if isinstance(target, ast.Name)
                 and target.id in {f"J{i}" for i in range(1, 8)} | {"U1", "U2", "U3"}}
    product = [constants[f"J{i}"] for i in range(1, 8)] + [constants[f"U{i}"] for i in range(1, 4)]
    assert list(m24.FIXED_SENTENCES) == product
    script = (f"const f=require({json.dumps(str(FLOW))});"
              "console.log(JSON.stringify([...Object.values(f.J), ...Object.values(f.U)]))")
    flow = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(flow) == product


def test_scan_wording_reads_json_strings_and_text_but_not_profiles_or_service_logs(tmp_path):
    (tmp_path / "step").mkdir()
    (tmp_path / "step/row.json").write_text(json.dumps({"limitations": [m24.FIXED_SENTENCES[0]], "note": "fine"},
                                                       ensure_ascii=False))
    (tmp_path / "step/rows.jsonl").write_text(json.dumps({"description": "만들기"}) + "\n" +
                                              json.dumps({"text": "best"}) + "\n")
    (tmp_path / "README.md").write_text("# 보고\n" + m24.FIXED_SENTENCES[7] + "\n")
    (tmp_path / "services").mkdir()
    (tmp_path / "services/build.log").write_text("ranking chunk\n")
    (tmp_path / "step/browser-profile").mkdir()
    (tmp_path / "step/browser-profile/Preferences.json").write_text('{"best": 1}')
    (tmp_path / "shot.png").write_bytes(b"\x89PNG best")
    # a panel dump: tags become line breaks, so a fixed sentence in its own element is its own (exempt) line
    (tmp_path / "step/F09-failure.panel.html").write_text(
        f'<section><p data-limitation="0">{m24.FIXED_SENTENCES[0]}</p><p>{m24.FIXED_SENTENCES[8]}</p></section>')
    (tmp_path / "step/F10-failure.panel.html").write_text("<div><p>비활성</p><b>순위</b> &amp; 1</div>")
    assert m24.scan_wording(tmp_path) == {"step/F10-failure.panel.html": ["순위"], "step/rows.jsonl": ["best"]}


def test_files_containing_finds_needles_and_skips_absent_roots(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/one.json").write_text('{"x": "placeholder-abc"}')
    (tmp_path / "a/two.bin").write_bytes(b"\x00\x01placeholder-abc\x02")
    (tmp_path / "a/three.txt").write_text("nothing")
    hits = m24.files_containing([tmp_path / "a", tmp_path / "missing"], [b"placeholder-abc", None])
    assert sorted(Path(item).name for item in hits) == ["one.json", "two.bin"]
    assert m24.files_containing([tmp_path / "a"], [b"other"]) == []


def test_key_scan_prints_only_booleans_counts_and_paths():
    assert "print(json.dumps({\"keyAvailable\"" in m24.KEY_SCAN
    assert "del key" in m24.KEY_SCAN and "print(key" not in m24.KEY_SCAN
    tree = ast.parse(m24.KEY_SCAN)
    printed = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"]
    assert len(printed) == 1


# ----- cases, judgement ----------------------------------------------------------------------------------------------
def test_every_case_has_a_text_and_the_harness_declares_it():
    flow = FLOW.read_text()
    for phase in m24.PHASES:
        plan = m24.case_plan(phase)
        assert set(plan) <= set(m24.CASE_TEXT)
        for case, modes in plan.items():
            assert modes and set(modes) <= set(m24.PHASE_STEPS[phase])
            assert f'"{m24.ROW_CASE.get(case, case)}"' in flow, case
    assert set(m24.FIXTURE_CASES) <= set(m24.CASE_TEXT)
    for mode in set(m24.MODE_OF.values()):
        assert f'"{mode}"' in flow
    for case in ("J-tab-entry", "J-consent-off-block", "J-consent-toggle", "J-source-choice", "J-candidate-limit",
                 "J-ligand-filter", "J-preview-match", "J-confirm-required", "J-send-good", "J-resend", "J-report",
                 "J-failed-alias", "J-failed-http", "J-failed-model", "J-no-usage-stop", "J-late", "J-send-cap",
                 "J-other-tabs", "J-no-egress-browser", "J-wording", "J-bytes-equal"):
        assert case in m24.FIXTURE_CASES
    assert not set(m24.NOT_OBSERVED_COMMON) & set(m24.CASE_TEXT)


def test_evidence_texts_carry_no_forbidden_word():
    texts = [*m24.CASE_TEXT.values(), *m24.RUNNER_CASE_TEXT.values(), *m24.NOT_OBSERVED_COMMON.values(),
             m24.NOT_OBSERVED_LIVE]
    runner = m24.Runner(_args())
    ledger = {"phase": "fixture", "generatedAt": "t", "verdict": "pass", "acceptance": True, "acceptanceScope": "fixture",
              "liveCalls": 0, "build": {}, "environment": ENV, "checks": {}, "leftoverProcesses": [],
              "externalRequestsTotal": 0, "cases": _judge()["cases"], "notObserved": m24.not_observed("fixture"),
              "steps": _judge()["steps"]}
    texts.append(runner.readme(ledger))
    texts.append(runner.readme({**ledger, "phase": "live", "notObserved": m24.not_observed("live")}))
    found = [word for text in texts for word in m24.forbidden_in(text)]
    assert found == []
    flow = FLOW.read_text()
    descriptions = [node for node in flow.split("rec_.step(")[1:]]
    assert descriptions and not [word for item in descriptions for word in m24.forbidden_in(item.split("async")[0])]


@pytest.mark.parametrize("phase", m24.PHASES)
def test_all_passing_rows_pass(phase):
    judged = _judge(phase)
    assert judged["passed"] is True, judged
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert m24.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True
    assert m24.acceptance_ok(judged["passed"], {"buildCurrentWithSource": False}) is False
    runner_cases = {"S-browser-egress-zero", "S-key-absent", "S-wording-evidence"}
    assert runner_cases <= set(judged["cases"])
    if phase == "fixture":
        assert "S-real-calls-zero" in judged["cases"] and "JL-count" not in judged["cases"]
        assert judged["notObserved"]["JL-calibrate-send"].startswith("관찰하지 않음 — 실호출 할당은 T10")
        assert judged["notObserved"]["JL-live-sends"] == m24.NOT_OBSERVED_LIVE
    else:
        assert {"JL-count", "JL-calibration", "JL-ledger"} <= set(judged["cases"])
        assert "JL-live-sends" not in judged["notObserved"]


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["J-late"]
    judged = _judge(rows=rows)
    assert judged["cases"]["J-late"]["status"] == "fail" and judged["passed"] is False
    for index in (1, 2):                                  # either rehearsal step decides the rehearsal case
        rows = _rows()
        rows[index]["cases"]["J-live-rehearsal"] = "fail"
        assert _judge(rows=rows)["cases"]["J-live-rehearsal"]["status"] == "fail"
    rows = _rows("calibrate")
    rows[0]["cases"]["JL-live"] = "fail"
    assert _judge("calibrate", rows=rows)["cases"]["JL-calibrate-send"]["status"] == "fail"


def test_missing_step_and_browser_egress_fail():
    assert m24.PHASE_STEPS["fixture"] == ["jev-fixture", "jev-rehearsal-calibrate", "jev-rehearsal-live"]
    judged = _judge(rows=[_row("jev-fixture"), _row("jev-rehearsal-calibrate")])
    assert judged["steps"]["jev-rehearsal-live"]["status"] == "missing"
    assert judged["cases"]["S-browser-egress-zero"]["status"] == "fail" and judged["passed"] is False
    for bad in (None, 1):
        judged = _judge(rows=[_row("jev-fixture", external=bad), _row("jev-rehearsal-calibrate"),
                              _row("jev-rehearsal-live")])
        assert judged["steps"]["jev-fixture"]["status"] == "fail"
        assert judged["cases"]["S-browser-egress-zero"]["status"] == "fail" and judged["passed"] is False


@pytest.mark.parametrize("phase,checks,case", [
    ("fixture", {**CHECKS, "keyScan": {"ok": False}}, "S-key-absent"),
    ("fixture", {**CHECKS, "keyScan": None}, "S-key-absent"),
    ("fixture", {**CHECKS, "wordingScan": {"x.json": ["best"]}}, "S-wording-evidence"),
    ("fixture", {**CHECKS, "wordingScan": None}, "S-wording-evidence"),
    ("fixture", {**CHECKS, "fixtureProof": {"ok": False}}, "S-real-calls-zero"),
    ("fixture", {k: v for k, v in CHECKS.items() if k != "fixtureProof"}, "S-real-calls-zero"),
    ("calibrate", {**CHECKS, "liveCount": {"ok": False}}, "JL-count"),
    ("calibrate", {**CHECKS, "calibration": {"ok": False}}, "JL-calibration"),
    ("calibrate", {**CHECKS, "liveLedger": {"ok": False}}, "JL-ledger"),
    ("live", {k: v for k, v in CHECKS.items() if k != "liveLedger"}, "JL-ledger"),
    ("live", {**CHECKS, "liveCount": {"ok": False}}, "JL-count"),
    ("live", {**CHECKS, "calibration": None}, "JL-calibration"),
])
def test_runner_checks_decide_their_cases(phase, checks, case):
    judged = _judge(phase, checks=checks)
    assert judged["cases"][case]["status"] == "fail"
    assert judged["passed"] is False


@pytest.mark.parametrize("phase,missing", [
    ("fixture", "fixtureServer"), ("fixture", "setup"), ("fixture", "workerPython"), ("fixture", "jevAvailable"),
    ("calibrate", "keyAvailable"), ("calibrate", "setup"), ("live", "keyAvailable"), ("live", "liveState"),
    ("live", "ligandAvailable"), ("calibrate", "mutationAvailable"),
])
def test_environment_must_be_present(phase, missing):
    judged = _judge(phase, environment={**ENV, missing: False})
    assert judged["verdictParts"]["environment"] is False and judged["passed"] is False


def test_leftovers_fail_and_latest_attempt_decides():
    assert _judge(leftovers=["port 8000 still listening: pid 1"])["passed"] is False
    failed = _row("jev-fixture", status="fail", cases={case: "fail" for case in m24.FIXTURE_CASES})
    retried = _row("jev-fixture-20261006T120000000000")
    judged = _judge(rows=[failed, retried, _row("jev-rehearsal-calibrate"), _row("jev-rehearsal-live")])
    assert judged["steps"]["jev-fixture"]["latest"] == "jev-fixture-20261006T120000000000"
    assert judged["passed"] is True


# ----- setup inputs, regression chain, boundaries ----------------------------------------------------------------------
def test_top_residues_are_the_most_connected_non_ala_positions():
    expected = json.loads((REPO / m24.NEIGHBORS).read_text())
    ubq = m24.top_residues(expected, "1UBQ", 22)
    assert len(ubq) == 22 and ubq[0] == {"model_number": 1, "chain_auth": "A", "seq_auth": 56, "icode": "",
                                         "resname": "LEU"}
    assert all(item["resname"] != "ALA" for item in ubq)
    rows = expected["structures"]["1UBQ"]["neighbor_counts"]
    counts = {(row[0], row[1]): row[4] for row in rows}
    picked = [counts[(item["chain_auth"], item["seq_auth"])] for item in ubq]
    assert picked == sorted(picked, reverse=True)
    assert len(m24.top_residues(expected, "1MQ4", 24)) == 24
    assert m24.STRUCTURES["ubq"][2] > m24.LIVE_PLAN[-1]["pick"]["first"]       # 21st candidate exists for the cap check


def test_regression_chain_is_opt_in_and_uses_fresh_folders(kbase):
    runner = m24.Runner(_args(regressions=True, kbase=kbase))
    commands = dict(runner.regression_commands())
    assert list(commands) == ["m23", "m22", "m21", "m20", "m19", "m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m24-test-root-{name}-regression")
        assert argv[argv.index("--artifacts") + 1].endswith(f"regressions/{name}")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m20", "m16", "m15"))
        assert "--regressions" not in argv and "--live-calls" not in argv
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m24.Runner(_args()).regressions is False


def test_runner_never_imports_mw_and_never_posts_to_a_jev_route():
    source = Path(m24.__file__).read_text()
    tree = ast.parse(source)
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
    posts = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "api"
             and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "POST"]
    assert posts
    for node in posts:
        assert "jev" not in ast.unparse(node.args[1]), ast.unparse(node)
    assert "/jev/consent" not in source and "/jev/sends" not in source and "limit_approval" not in source


def test_harness_never_posts_itself_and_its_fixture_server_never_uses_the_real_gate():
    flow = FLOW.read_text()
    assert "page.request.post" not in flow and "page.request.fetch" not in flow and ".dispatchEvent(" not in flow
    server = (REPO / m24.FIXTURE_SERVER).read_text()
    assert "product_api.SCIENCE_GATE = EgressGate(transport=httpx.MockTransport(" in server
    assert "product_api.VIEWER_GATE = EgressGate(transport=httpx.MockTransport(refuse)" in server
    assert f'SENTINEL = "{m24.SENTINEL}"' in server
    assert "env_or_root_dotenv_key" not in server and "OPENROUTER" not in server


# ----- the repository-level real-call ledger (every root, every phase) ---------------------------------------------------
def _ledger_file(path, roots):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": roots}))


def _phase(phase="calibrate", finished=True):
    return {"phase": phase, "startedAt": "2026-10-06T00:00:00+00:00",
            "finishedAt": "2026-10-06T00:01:00+00:00" if finished else None, "planned": 1}


def test_the_ledger_is_one_git_ignored_file_of_the_main_checkout():
    path = REAL_LEDGER_PATH(REPO)
    main = Path(subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO,
                               capture_output=True, text=True, check=True).stdout.strip()).parent
    assert path == main / "runs" / "m24-live-ledger.json"
    assert subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=main, check=False).returncode == 0
    with pytest.raises(m24.LedgerError, match="git"):
        REAL_LEDGER_PATH(Path("/"))


def test_ledger_total_adds_every_root_and_counts_their_dispatch_events(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    _events(a / "runs", "run_a1", [DISPATCH])
    _events(b / "runs", "run_b1", [DISPATCH, DISPATCH, SCIENCE_RESPONSE])
    ledger = {"schema": m24.LEDGER_SCHEMA, "roots": {
        str(a): {"phases": [_phase()], "dispatch": {"run_a1": 1}},
        str(b): {"phases": [_phase(finished=False)], "dispatch": {}}}}    # unfinished: its events are counted
    assert m24.ledger_total(ledger) == 3
    _events(a / "runs", "run_a1", [DISPATCH])                              # events only grow: the larger count wins
    assert m24.ledger_total(ledger) == 4
    shutil.rmtree(a)                                                       # a finished root that is gone keeps its record
    assert m24.ledger_total(ledger) == 3
    _events(c / "runs", "run_c1", [DISPATCH])                              # the current root is counted too
    assert m24.ledger_total(ledger, (c,)) == 4
    shutil.rmtree(b)                                                       # an unfinished root that is gone: not countable
    with pytest.raises(m24.LedgerError, match="unfinished"):
        m24.ledger_total(ledger)


def test_a_damaged_or_unreadable_ledger_is_refused(tmp_path):
    path = tmp_path / "ledger.json"
    assert m24.read_ledger(path) == {"schema": m24.LEDGER_SCHEMA, "roots": {}}          # absent = nothing recorded yet
    good = {"phases": [_phase()], "dispatch": {"run_a1": 1}}
    for bad in ("{", "[]", "null", json.dumps({"schema": "other@1", "roots": {}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": []}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {}, "extra": 1}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"relative/root": good}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": {**good, "dispatch": {"run_a1": -1}}}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": {**good, "dispatch": {"run_a1": True}}}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": {**good, "dispatch": {"x": 1}}}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": {**good, "phases": "calibrate"}}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": {**good, "phases": [{"phase": "fixture"}]}}}),
                json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": {"phases": []}}})):
        path.write_text(bad)
        with pytest.raises(m24.LedgerError):
            m24.read_ledger(path)
    path.write_text(json.dumps({"schema": m24.LEDGER_SCHEMA, "roots": {"/r": good}}))
    assert m24.read_ledger(path)["roots"]["/r"] == good
    path.chmod(0)
    try:
        with pytest.raises(m24.LedgerError):
            m24.read_ledger(path)
    finally:
        path.chmod(0o600)


@pytest.fixture
def qa_base():
    """A git-ignored QA folder inside the repository (the runner refuses tracked artifacts and /tmp), removed after."""
    base = REPO / "runs" / f"pytest-m24-ledger-{uuid.uuid4().hex[:12]}"
    yield base
    shutil.rmtree(base, ignore_errors=True)


def _stubbed(monkeypatch, base, name, phase, live_calls=0, dispatches=1, crash=False):
    """A Runner whose build, services, harness steps, searches and export are stubs; its phase writes ``dispatches``
    jev_science_dispatch_started events into one run of its root (then crashes when ``crash``)."""
    root, attempt = base / name, f"{name}-{phase}-{uuid.uuid4().hex[:8]}"
    runner = m24.Runner(_args(root=str(root), artifacts=str(base / "artifacts" / attempt),
                              out=str(base / "out" / attempt), phase=phase, live_calls=live_calls))
    monkeypatch.setattr(m24.m13, "listening", lambda port: [])
    monkeypatch.setattr(m24.m13, "build_is_current", lambda frontend: True)
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


def _calibrated(root):
    (root).mkdir(parents=True, exist_ok=True)
    (root / "live-state.json").write_text(json.dumps({"calibration": {"ok": True}, "livePhaseRan": False,
                                                      "setup": str(root / "live-setup.json")}))


def test_rehearsals_never_touch_the_ledger_and_real_phases_add_their_event_counts(monkeypatch, qa_base, isolated_ledger):
    # the fixture phase (its rehearsal dispatches against the fixture server) is not a real call: nothing is written
    fixture = _stubbed(monkeypatch, qa_base, "fixture", "fixture", dispatches=6)
    fixture.run()
    assert not isolated_ledger.exists()
    # a calibrate root, then a second calibrate root: the ledger adds both (event counts, failed sends included)
    first = _stubbed(monkeypatch, qa_base, "calibrate-1", "calibrate", live_calls=1)
    first.run()
    ledger = json.loads(isolated_ledger.read_text())
    entry = ledger["roots"][str(first.root)]
    assert sum(entry["dispatch"].values()) == 1 and entry["phases"][0]["finishedAt"] is not None
    assert first.checks["liveLedger"]["before"] == 0 and first.checks["liveLedger"]["after"] == 1
    second = _stubbed(monkeypatch, qa_base, "calibrate-2", "calibrate", live_calls=1, crash=True)
    with pytest.raises(RuntimeError, match="crashed"):
        second.run()
    assert m24.ledger_total(m24.read_ledger(isolated_ledger)) == 2      # the crashed phase's call is recorded too
    # live on the first root with --live-calls 6 plans 5 more: 2 + 5 > 6 is refused before anything starts
    _calibrated(first.root)
    refused = _stubbed(monkeypatch, qa_base, "calibrate-1", "live", live_calls=6, dispatches=5)
    with pytest.raises(SystemExit, match="ledger counts 2"):
        refused.run()
    assert m24.ledger_total(m24.read_ledger(isolated_ledger)) == 2
    assert not (refused.artifacts / "runner-summary.jsonl").exists()         # nothing started
    # with --live-calls 5 it plans 4: 2 + 4 = 6 is allowed and recorded
    allowed = _stubbed(monkeypatch, qa_base, "calibrate-1", "live", live_calls=5, dispatches=4)
    allowed.run()
    assert m24.ledger_total(m24.read_ledger(isolated_ledger)) == 6
    assert allowed.checks["liveLedger"]["planned"] == 4 and allowed.checks["liveLedger"]["after"] == 6
    # the allocation is used up: a new calibrate root is refused, whatever its --live-calls
    with pytest.raises(SystemExit, match="ledger counts 6"):
        _stubbed(monkeypatch, qa_base, "calibrate-3", "calibrate", live_calls=1).run()


def test_a_damaged_ledger_refuses_every_real_phase(monkeypatch, qa_base, isolated_ledger):
    isolated_ledger.parent.mkdir(parents=True, exist_ok=True)
    isolated_ledger.write_text("{not json")
    runner = _stubbed(monkeypatch, qa_base, "calibrate", "calibrate", live_calls=1)
    with pytest.raises(SystemExit, match="ledger"):
        runner.run()
    assert not runner.runs.exists() and isolated_ledger.read_text() == "{not json"
    # the fixture phase does not read it
    _stubbed(monkeypatch, qa_base, "fixture", "fixture").run()


# ----- the end of the calibrate phase and --finalize (stored files only; no service, harness or call) -------------------
# The shape of a stored jev-calibrate ledger row with one completed send (test data, not evidence).
CALIBRATE_SEND = {"entry": "L1-ligand-5", "run": "run_aa", "kind": "ligand", "aliases": 5, "bodyBytes": 3539,
                  "bodySha256": "a" * 64, "reservation": {"external_tokens": 5866, "usd": 0.1}, "sendId": "s",
                  "status": "completed", "reasonCode": None, "servedModel": "typesafe/jev-1.13-20260917",
                  "usage": {"cost": 8.7654e-05, "external_tokens": 2152, "input_tokens": 2087, "output_tokens": 65},
                  "late": False, "egressStop": None,
                  "responseShape": {"confidence": True, "probabilities": True, "probabilityCount": 5}}
CALIBRATE_ROW = {"schema": "m24_case_ledger_row@1", "step": "jev-calibrate", "mode": "live", "status": "pass",
                 "cases": {"JL-live": "pass"}, "externalRequestCount": 0, "sends": [CALIBRATE_SEND],
                 "dispatchCounts": {"run_aa": 1, "run_bb": 0}}
CALIBRATE_ENV = {key: True for key in ("workerPython", "ligandAvailable", "mutationAvailable", "jevAvailable",
                                       "keyAvailable", "setup")}


def test_no_record_call_spreads_a_dict_into_its_keywords():
    """record(step, status, **extra): a ``**`` spread of a dict holding ``status`` (the calibration's send status) or
    ``step`` raises TypeError — the calibrate crash right after the first real call. Every check dict goes in as one
    ``detail`` keyword instead."""
    tree = ast.parse(Path(m24.__file__).read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "record"]
    assert len(calls) > 10
    assert [ast.unparse(node) for node in calls if any(keyword.arg is None for keyword in node.keywords)] == []
    assert [ast.unparse(node) for node in calls
            if any(keyword.arg in ("step", "status") for keyword in node.keywords)] == []


def test_run_calibrate_ends_by_storing_and_recording_the_calibration(monkeypatch, qa_base):
    root = qa_base / "calibrate-end"
    runner = m24.Runner(_args(root=str(root), artifacts=str(qa_base / "artifacts" / "calibrate-end"),
                              out=str(qa_base / "out" / "calibrate-end"), phase="calibrate", live_calls=6))
    runner.artifacts.mkdir(parents=True)
    runner.runs.mkdir(parents=True)
    monkeypatch.setattr(runner, "start_backend_at", lambda *args: None)
    monkeypatch.setattr(runner, "capabilities_ready", lambda: True)
    monkeypatch.setattr(runner, "key_available", lambda: True)

    def setup_runs(shapes, label, keys=None):
        target = runner.artifacts / f"setup-{label}.json"
        target.write_text(json.dumps({"schema": "m24_jev_setup@1", "label": label, "runs": {}}) + "\n")
        return target

    def flow(step, mode, extra, limit=None):
        assert (step, mode, limit) == ("jev-calibrate", "live", 1)
        _events(runner.runs, "run_aa", [DISPATCH, SCIENCE_RESPONSE])
        _events(runner.runs, "run_bb", [])
        return json.loads(json.dumps(CALIBRATE_ROW))
    monkeypatch.setattr(runner, "setup_runs", setup_runs)
    monkeypatch.setattr(runner, "flow", flow)
    runner.run_calibrate()
    state = json.loads(runner.state_path.read_text())
    assert state["calibration"] == m24.calibration(CALIBRATE_ROW)
    assert (state["calibration"]["ok"], state["calibration"]["status"], state["livePhaseRan"]) == (True, "completed", False)
    assert state["counts"] == m24.count_events(runner.runs) and runner.checks["liveCount"]["ok"] is True
    recorded = [json.loads(line) for line in (runner.artifacts / "runner-summary.jsonl").read_text().splitlines()]
    entry = [item for item in recorded if item["step"] == "calibration"][-1]
    assert (entry["status"], entry["detail"]) == ("pass", state["calibration"])     # the send status stays in detail


def _tree_bytes(folder):
    return {str(path.relative_to(folder)): path.read_bytes() for path in sorted(Path(folder).rglob("*")) if path.is_file()}


def _finished_calibrate(base, ledger_file, name="finished"):
    """A calibrate root whose real call finished but whose runner stopped before its evidence: its runs events,
    live-setup.json and live-state.json; the artifacts' runner-state.json, setup-live.json, jev-calibrate row and summary
    (with the live-ledger record); the ledger with this root's finished calibrate phase."""
    root, artifacts, out = base / name, base / "artifacts" / name, base / "out" / name
    _events(root / "runs", "run_aa", [DISPATCH, SCIENCE_RESPONSE])
    _events(root / "runs", "run_bb", [])
    setup = json.dumps({"schema": "m24_jev_setup@1", "label": "live", "runs": {}}) + "\n"
    (root / "live-setup.json").write_text(setup)
    (root / "live-state.json").write_text(json.dumps({
        "schema": "m24_jev_live_state@1", "setup": str(root / "live-setup.json"),
        "calibration": m24.calibration(CALIBRATE_ROW), "counts": m24.count_events(root / "runs"), "liveCalls": 6,
        "livePhaseRan": False, "writtenAt": "2026-10-06T00:00:30+00:00"}, indent=2) + "\n")
    (artifacts / "jev-calibrate").mkdir(parents=True)
    (artifacts / "jev-calibrate/ledger-row.json").write_text(json.dumps(CALIBRATE_ROW, indent=2) + "\n")
    (artifacts / "setup-live.json").write_text(setup)
    (artifacts / "runner-state.json").write_text(json.dumps({
        "build": {"buildId": "b", "gitHead": "h", "buildCurrentWithSource": True}, "environment": CALIBRATE_ENV},
        indent=2) + "\n")
    (artifacts / "runner-summary.jsonl").write_text(json.dumps({
        "step": "live-ledger", "status": "pass", "at": "2026-10-06T00:01:00+00:00", "ok": True, "before": 0,
        "planned": 1, "after": 1, "rootDispatch": 1}) + "\n")
    _ledger_file(ledger_file, {str(root): {"phases": [_phase()], "dispatch": {"run_aa": 1, "run_bb": 0}}})
    return root, artifacts, out


def _finalizer(monkeypatch, root, artifacts, out):
    """A --finalize Runner: every way to build, start a service or Electron, post, run a phase, write the ledger or
    rewrite runner-state.json fails the test; leftovers and the key search are stubs."""
    runner = m24.Runner(_args(root=str(root), artifacts=str(artifacts), out=str(out), phase="calibrate", live_calls=0,
                              finalize=True))
    monkeypatch.setattr(m24.m13, "listening", lambda port: [])
    monkeypatch.setattr(runner, "leftovers", list)
    monkeypatch.setattr(runner, "key_scan", lambda roots: {"ok": True, "keyAvailable": True, "keyHits": [],
                                                           "sentinelHits": [], "roots": [str(item) for item in roots]})

    def forbidden(*args, **kwargs):
        raise AssertionError("--finalize must not build, start services, post, call, write the ledger or the state")
    for method in ("build", "start_frontend", "start_backend_at", "start_fixture_backend", "flow", "api", "setup_runs",
                   "run_fixture", "run_calibrate", "run_live", "ledger_guard", "execute", "save", "key_available"):
        monkeypatch.setattr(runner, method, forbidden)
    monkeypatch.setattr(m24, "write_ledger", forbidden)
    return runner


def test_finalize_rebuilds_the_calibrate_evidence_from_the_stored_files_only(monkeypatch, qa_base, isolated_ledger):
    root, artifacts, out = _finished_calibrate(qa_base, isolated_ledger)
    ledger_before, root_before = isolated_ledger.read_bytes(), _tree_bytes(root)
    state_before = (artifacts / "runner-state.json").read_bytes()
    assert _finalizer(monkeypatch, root, artifacts, out).run() == 0
    # the ledger, the root (events, live-state.json) and runner-state.json are only read
    assert isolated_ledger.read_bytes() == ledger_before and _tree_bytes(root) == root_before
    assert (artifacts / "runner-state.json").read_bytes() == state_before
    book = json.loads((artifacts / "case-ledger.json").read_text())
    assert (book["phase"], book["verdict"], book["acceptance"], book["liveCalls"]) == ("calibrate", "pass", True, 6)
    assert {case: value["status"] for case, value in book["cases"].items()} == {
        case: "pass" for case in ("JL-calibrate-send", "S-browser-egress-zero", "S-key-absent", "S-wording-evidence",
                                  "JL-count", "JL-calibration", "JL-ledger")}
    assert book["checks"]["calibration"] == json.loads((root / "live-state.json").read_text())["calibration"]
    ledger_check = book["checks"]["liveLedger"]
    assert {key: ledger_check[key] for key in ("ok", "before", "planned", "after", "rootDispatch", "readOnly")} == {
        "ok": True, "before": 0, "planned": 1, "after": 1, "rootDispatch": 1, "readOnly": True}
    assert book["finalize"]["realCalls"] == 0 and book["finalize"]["ledgerSha256"] == m24.m13.sha_bytes(ledger_before)
    assert book["build"] == json.loads(state_before)["build"] and book["environment"] == CALIBRATE_ENV
    readme = (out / "README.md").read_text()
    assert "--finalize" in readme and "acceptance **true**" in readme and m24.forbidden_in(readme) == []
    assert (out / "evidence/case-ledger.json").is_file() and (out / "post-export-checks.json").is_file()
    recorded = [json.loads(line) for line in (artifacts / "runner-summary.jsonl").read_text().splitlines()]
    assert recorded[0]["step"] == "live-ledger" and recorded[0]["before"] == 0         # the original record is kept
    calibration = [item for item in recorded if item["step"] == "calibration"][-1]
    assert (calibration["status"], calibration["detail"]["status"]) == ("pass", "completed")


def _set(path, **fields):
    path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))


FINALIZE_REFUSALS = {
    "ledger-absent": (lambda root, art, out, book: book.unlink(), "no record"),
    "ledger-damaged": (lambda root, art, out, book: book.write_text("{"), "ledger"),
    "root-not-recorded": (lambda root, art, out, book: _ledger_file(book, {}), "no record"),
    "phase-unfinished": (lambda root, art, out, book: _ledger_file(book, {str(root): {
        "phases": [_phase(finished=False)], "dispatch": {"run_aa": 1, "run_bb": 0}}}), "finished"),
    "no-calibrate-phase": (lambda root, art, out, book: _ledger_file(book, {str(root): {
        "phases": [_phase("live")], "dispatch": {"run_aa": 1, "run_bb": 0}}}), "finished"),
    "ledger-counts-differ": (lambda root, art, out, book: _ledger_file(book, {str(root): {
        "phases": [_phase()], "dispatch": {"run_aa": 0, "run_bb": 0}}}), "dispatch counts"),
    "events-grew": (lambda root, art, out, book: _events(root / "runs", "run_bb", [DISPATCH]), "dispatch counts"),
    "no-live-state": (lambda root, art, out, book: (root / "live-state.json").unlink(), "live-state"),
    "live-phase-ran": (lambda root, art, out, book: _set(root / "live-state.json", livePhaseRan=True), "live"),
    "calibration-differs": (lambda root, art, out, book: _set(root / "live-state.json", calibration={"ok": True}),
                            "calibration"),
    "no-runner-state": (lambda root, art, out, book: (art / "runner-state.json").unlink(), "runner-state"),
    "no-calibrate-row": (lambda root, art, out, book: (art / "jev-calibrate/ledger-row.json").unlink(), "jev-calibrate"),
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
