"""Ledger judgement, environment, reproducibility and option rules of scripts/m22_offscreen_acceptance.py (no services
run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m22_offscreen_acceptance as m22

ENV = {"dockingPython": True, "qvina": True, "ligandPython": True, "mainAvailable": True, "singleAvailable": True,
       "candidatesAvailable": True, "layoutReason": "worker_missing"}
REPO = Path(m22.__file__).resolve().parents[1]
INDIVIDUALS = [{"candidate_id": "c_1", "state": "scored", "score": -8.5, "resultSha256": "r" * 64,
                "posesSha256": "p" * 64}]
RERUN = {"status": "done", "providerCallsZero": True, "summarySha256": "s" * 64, "individuals": INDIVIDUALS}
REPRO = {"reference": {"summarySha256": "s" * 64, "individuals": INDIVIDUALS}, "reruns": [dict(RERUN), dict(RERUN)]}


def _cases(step):
    return [case for case, modes in m22.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m22.FLOW_STEPS]


def _judge(rows=None, leftovers=(), environment=None, repro=REPRO):
    return m22.assemble(_rows() if rows is None else rows, list(leftovers), ENV if environment is None else environment,
                        repro)


def _args(**override):
    values = {"root": str(REPO / "runs/m22-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m22-test-out"), "code_root": str(REPO), "build": "never", "regressions": False,
              "kbase": None}
    return argparse.Namespace(**{**values, **override})


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


def test_every_spec_case_is_planned_and_covered():
    assert set(m22.CASE_PLAN) == set(m22.CASE_TEXT)
    assert all(modes and set(modes) <= set(m22.FLOW_STEPS) for modes in m22.CASE_PLAN.values())
    assert set(m22.MODE_OF) == set(m22.FLOW_STEPS)
    # spec 9/11: parameter guards and defaults, preflight and the limit approval, a real GA with progress, results with
    # generation tabs, sort, M18 detail, reuse, partial, report, unavailable states
    for case in ("GA-param-guards", "GA-defaults", "GA-pool-too-small", "GA-preflight", "GA-limit-approval", "GA-run",
                 "GA-progress", "GA-results", "GA-sort", "GA-detail", "GA-dedupe", "GA-reuse", "GA-partial",
                 "GA-cancel", "GA-report", "GA-wording", "GA-no-run", "GA-unavailable", "GA-no-candidate-set"):
        assert case in m22.CASE_PLAN, case
    assert m22.CASE_PLAN["GA-unavailable"] == ["ga-unavailable"] and m22.CASE_PLAN["GA-no-run"] == ["ga-unavailable"]
    assert m22.REPRO_CASE not in m22.CASE_PLAN
    assert not set(m22.NOT_OBSERVED) & set(m22.CASE_PLAN)
    assert "GA-null-result" in m22.NOT_OBSERVED  # no score-less individual from the real engine here; never forged


def test_flow_declares_every_planned_case_and_mode():
    flow = (REPO / "frontend/tests/offscreen" / m22.FLOW).read_text()
    for case in m22.CASE_PLAN:
        assert f'"{case}"' in flow, case
    for mode in m22.MODE_OF.values():
        assert f'"{mode}"' in flow, mode
    for case in m22.NOT_OBSERVED:
        assert f'"{case}"' in flow, case
    assert '"runs-dir"' in flow  # stored payloads are read from the runs folder
    assert "synthetic-ga-small-blocks.smi" in flow and str(m22.REPRO_FILES["building_blocks_smiles"]).endswith(
        "synthetic-ga-small-blocks.smi")


def test_flow_and_runner_never_post_the_limit_raise():
    # the flow only waits for the response of the screen's own button; it never sends a request itself
    flow = (REPO / "frontend/tests/offscreen" / m22.FLOW).read_text()
    assert "page.request.post" not in flow and "page.request.fetch" not in flow
    runner = Path(m22.__file__).read_text()
    assert "limit_approval" not in runner


def test_package_script_runs_the_ligand_ga_flow():
    package = (REPO / "frontend/package.json").read_text()
    assert '"test:offscreen:ligand-ga": "node tests/offscreen/ligand-ga-flow.cjs"' in package


def test_all_passing_rows_pass():
    judged = _judge()
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    for case in ("S-no-egress", m22.REPRO_CASE):
        assert judged["cases"][case]["status"] == "pass", case
    assert set(judged["notObserved"]) == set(m22.NOT_OBSERVED)
    assert m22.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["GA-reuse"]
    judged = _judge(rows)
    assert judged["cases"]["GA-reuse"]["status"] == "fail"
    assert judged["passed"] is False
    rows = _rows()
    rows[1]["cases"]["GA-unavailable"] = "fail"
    assert _judge(rows)["cases"]["GA-unavailable"]["status"] == "fail"


def test_missing_step_fails_its_cases_and_egress():
    judged = _judge([_row("ga-main")])
    assert judged["steps"]["ga-unavailable"]["status"] == "missing"
    assert judged["cases"]["GA-unavailable"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        judged = _judge([_row("ga-main", **bad), _row("ga-unavailable")])
        assert judged["steps"]["ga-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("repro", [
    None, {}, {"error": "not run"},
    {**REPRO, "reruns": [dict(RERUN)]},                                     # one fresh run is not enough
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "summarySha256": "t" * 64}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "individuals": [{**INDIVIDUALS[0], "score": -8.4}]}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "providerCallsZero": False}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "status": "failed"}]},
    {"reference": {"summarySha256": "s" * 64, "individuals": []}, "reruns": [dict(RERUN), dict(RERUN)]},
    {"reference": {"summarySha256": "s" * 64, "individuals": [{**INDIVIDUALS[0], "state": "failed"}]},
     "reruns": [dict(RERUN), dict(RERUN)]},                                 # nothing scored: nothing compared
])
def test_reproducibility_must_match_the_flow_ga(repro):
    judged = _judge(repro=repro)
    assert judged["cases"][m22.REPRO_CASE]["status"] == "fail"
    assert judged["passed"] is False


def test_normalization_replaces_only_run_scoped_values():
    content = {"candidate_set_handle": "obj://run_a/ligand_candidate_set/x", "call_key": "k" * 64,
               "selection_sha256": "s" * 64, "input_sha256": "i" * 64, "score": -8.5, "similarity": 0.5,
               "generations": [{"individuals": [{"result_handle": "obj://run_a/docking_result/y", "score": -8.5}]}]}
    other = {**content, "candidate_set_handle": "obj://run_b/ligand_candidate_set/z", "call_key": "c" * 64,
             "selection_sha256": "t" * 64, "input_sha256": "j" * 64,
             "generations": [{"individuals": [{"result_handle": "obj://run_b/docking_result/w", "score": -8.5}]}]}
    assert m22.content_sha(content) == m22.content_sha(other)
    assert m22.content_sha(content) != m22.content_sha({**content, "score": -8.4})
    assert m22.content_sha(content) != m22.content_sha({**content, "similarity": 0.4})
    assert m22.RUN_SCOPED_KEYS == {"input_sha256", "selection_sha256", "call_key"}


@pytest.mark.parametrize("environment", [
    {**ENV, "dockingPython": False}, {**ENV, "qvina": False}, {**ENV, "ligandPython": False},
    {**ENV, "mainAvailable": False}, {**ENV, "singleAvailable": False}, {**ENV, "candidatesAvailable": False},
    {**ENV, "layoutReason": "available"}, {},
])
def test_environment_must_be_present(environment):
    judged = _judge(environment=environment)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = _judge(leftovers=["port 8000 still listening: pid 1"])
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m22.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m22.acceptance_ok(True, None) is False
    assert m22.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("ga-main", {case: "fail" for case in _cases("ga-main")}, status="fail")
    retried = _row("ga-main-20261005T120000000000", _cases("ga-main"))
    judged = _judge([failed, retried, _row("ga-unavailable")])
    assert judged["steps"]["ga-main"]["latest"] == "ga-main-20261005T120000000000"
    assert judged["steps"]["ga-main"]["attempts"] == 2
    assert judged["passed"] is True
    assert _judge([retried, _row("ga-main-20261005T130000000000", {}, status="fail"),
                   _row("ga-unavailable")])["passed"] is False


def test_ga_docking_m17_and_qvina_workers_count_as_leftovers():
    assert {"ligand_ga_worker.py", "docking_worker.py", "ligand_worker.py", "qvina2", "guardian.py"} <= set(m22.WORKERS)


def test_options():
    parser = m22.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.regressions, args.kbase) == ("auto", None, str(REPO), False, None)
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])


def test_default_out_is_the_m22_qa_folder():
    runner = m22.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m22-ga-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m22.Runner(_args(**{field: "/tmp/m22-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m22.Runner(_args(**{field: "/private/tmp/m22-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m22.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m22.Runner(_args(artifacts=str(REPO / "docs/qa/m22-not-ignored")))


def test_regressions_need_kbase(tmp_path):
    with pytest.raises(SystemExit, match="kbase"):
        m22.Runner(_args(regressions=True))
    with pytest.raises(SystemExit, match="kbase"):
        m22.Runner(_args(regressions=True, kbase=str(tmp_path / "no-kbase")))


def test_regression_chain_is_opt_in_and_uses_fresh_folders(kbase):
    runner = m22.Runner(_args(regressions=True, kbase=kbase))
    commands = dict(runner.regression_commands())
    assert list(commands) == ["m21", "m20", "m19", "m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m22-test-root-{name}-regression")
        assert argv[argv.index("--artifacts") + 1].endswith(f"regressions/{name}")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m20", "m16", "m15"))
        assert "--regressions" not in argv
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m22.Runner(_args()).regressions is False


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m22.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
