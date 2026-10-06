"""Options, live-call counting and guard, case and ledger judgement, evidence searches, wording check and regression
chain of scripts/m24_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import m24_offscreen_acceptance as m24

REPO = Path(m24.__file__).resolve().parents[1]
FLOW = REPO / "frontend/tests/offscreen" / m24.FLOW
ENV = {"workerPython": True, "ligandAvailable": True, "mutationAvailable": True, "jevAvailable": True,
       "fixtureServer": True, "setup": True, "keyAvailable": True, "liveState": True}
CHECKS = {"keyScan": {"ok": True}, "wordingScan": {}, "fixtureProof": {"ok": True}, "liveCount": {"ok": True},
          "calibration": {"ok": True}}
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
              "live_calls": 0, "regressions": False, "kbase": None}
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
    assert m24.plan_for("calibrate", 0, 6) == {"entries": plan[:1], "maxDispatch": 1, "maxPerRun": 3}
    assert m24.plan_for("live", 1, 6)["entries"] == plan[1:6] and m24.plan_for("live", 1, 6)["maxDispatch"] == 6
    assert m24.plan_for("live", 1, 3)["entries"] == plan[1:3]
    assert m24.plan_for("live", 6, 6)["entries"] == []
    assert m24.plan_for("rehearsal", 12, 0, base=12) == {"entries": plan, "maxDispatch": 18, "maxPerRun": 3}


def test_calibration_needs_a_completed_send_with_known_usage_within_the_reservation():
    send = {"sendId": "s", "entry": "L1-ligand-5", "status": "completed", "reasonCode": None, "egressStop": None,
            "servedModel": "typesafe/jev-1.13-20260917", "bodyBytes": 6000,
            "usage": {"input_tokens": 2600, "output_tokens": 30, "external_tokens": 2630, "cost": 0.0002},
            "reservation": {"external_tokens": 7096, "usd": 0.1}, "responseShape": {"confidence": True}}
    good = m24.calibration({"sends": [send]})
    assert good["ok"] is True and round(good["bodyBytesPerInputToken"], 3) == round(6000 / 2600, 3)
    assert good["reservedTokensOverUsed"] == 7096 / 2630
    for changed in ({"status": "failed"}, {"egressStop": "usage_unknown"},
                    {"usage": {**send["usage"], "cost": None}},
                    {"usage": {**send["usage"], "external_tokens": 7097}},
                    {"usage": {**send["usage"], "cost": 0.11}}):
        assert m24.calibration({"sends": [{**send, **changed}]})["ok"] is False, changed
    assert m24.calibration({"sends": []})["ok"] is False
    assert m24.calibration(None)["ok"] is False
    assert m24.calibration({"sends": [{"entry": "x", "skipped": "stopped"}]})["ok"] is False


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


def test_forbidden_words_with_the_fixed_sentences_exempt():
    for sentence in m24.FIXED_SENTENCES:
        assert m24.forbidden_in(sentence) == []
        assert m24.forbidden_in(f"카드: {sentence}") == []
    assert m24.forbidden_in("JEV가 고른 후보는 최고의 추천") == ["최고", "추천"]
    assert m24.forbidden_in("the best candidate ranks first; we recommend it") == ["best", "ranks", "recommend"]
    assert m24.forbidden_in("bestow a frank ranking") == ["ranking"]
    assert m24.forbidden_in("점수 · 친화도 · 안정성 · ΔΔG · winner") == ["점수", "친화도", "안정성", "ΔΔG", "winner"]


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
    assert m24.scan_wording(tmp_path) == {"step/rows.jsonl": ["best"]}


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
        assert {"JL-count", "JL-calibration"} <= set(judged["cases"]) and "JL-live-sends" not in judged["notObserved"]


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["J-late"]
    judged = _judge(rows=rows)
    assert judged["cases"]["J-late"]["status"] == "fail" and judged["passed"] is False
    rows = _rows()
    rows[1]["cases"]["J-live-rehearsal"] = "fail"
    assert _judge(rows=rows)["cases"]["J-live-rehearsal"]["status"] == "fail"
    rows = _rows("calibrate")
    rows[0]["cases"]["JL-live"] = "fail"
    assert _judge("calibrate", rows=rows)["cases"]["JL-calibrate-send"]["status"] == "fail"


def test_missing_step_and_browser_egress_fail():
    judged = _judge(rows=[_row("jev-fixture")])
    assert judged["steps"]["jev-rehearsal"]["status"] == "missing"
    assert judged["cases"]["S-browser-egress-zero"]["status"] == "fail" and judged["passed"] is False
    for bad in (None, 1):
        judged = _judge(rows=[_row("jev-fixture", external=bad), _row("jev-rehearsal")])
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
    judged = _judge(rows=[failed, retried, _row("jev-rehearsal")])
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
