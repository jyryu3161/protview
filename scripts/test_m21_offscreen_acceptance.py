"""Ledger judgement, environment, budget, reproducibility and option rules of scripts/m21_offscreen_acceptance.py (no
services run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m21_offscreen_acceptance as m21

ENV = {"modelAvailable": True, "candidatesAvailable": True, "dockingAvailable": True}
REPO = Path(m21.__file__).resolve().parents[1]
RERUN = {"status": "done", "sameHandle": True, "sameJob": True, "contentSha256": "c" * 64, "providerCallsZero": True}
REPRO = {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), dict(RERUN)]}
BUDGET = {"model": {"before": 0, "after": 1}, "pair": {"before": 1, "after": 3}, "partial": {"before": 3, "after": 4},
          "totalRunA": 5, "limitRunA": 8}


def _cases(step):
    return [case for case, modes in m21.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True, budget=BUDGET):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider, "budget": budget}


def _rows():
    return [_row(step) for step in m21.FLOW_STEPS]


def _judge(rows=None, leftovers=(), environment=None, repro=REPRO):
    return m21.assemble(_rows() if rows is None else rows, list(leftovers), ENV if environment is None else environment,
                        repro)


def _args(**override):
    values = {"root": str(REPO / "runs/m21-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m21-test-out"), "code_root": str(REPO), "build": "never", "regressions": False,
              "kbase": None}
    return argparse.Namespace(**{**values, **override})


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


def test_every_spec_case_is_planned_and_covered():
    assert set(m21.CASE_PLAN) == set(m21.CASE_TEXT)
    assert all(modes and set(modes) <= set(m21.FLOW_STEPS) for modes in m21.CASE_PLAN.values())
    assert set(m21.MODE_OF) == set(m21.FLOW_STEPS)
    assert len(m21.CASE_PLAN) == 20
    # spec §9/§11: request validation, real job with approval, side by side, contacts, downloads, limitations, report,
    # wording, same handle, late responses, tab state, same-condition docking (both and partial), cancel
    for case in ("MM-validation", "MM-job", "MM-side-by-side", "MM-contacts", "MM-downloads", "MM-limitations",
                 "MM-report", "MM-negative", "MM-same-handle", "MM-late-contacts", "MM-late-run", "MM-tab-state",
                 "MM-pair-submit", "MM-pair-scores", "MM-pair-partial", "MM-cancel", "MM-no-run"):
        assert case in m21.CASE_PLAN, case
    assert m21.REPRO_CASE not in m21.CASE_PLAN and m21.BUDGET_CASE not in m21.CASE_PLAN
    assert not set(m21.NOT_OBSERVED) & set(m21.CASE_PLAN)
    assert "MM-unavailable" in m21.NOT_OBSERVED  # engine-unavailable state: not inducible honestly, covered by tests


def test_flow_declares_every_planned_case_and_mode():
    flow = (REPO / "frontend/tests/offscreen" / m21.FLOW).read_text()
    for case in m21.CASE_PLAN:
        assert f'"{case}"' in flow, case
    for mode in m21.MODE_OF.values():
        assert f'"{mode}"' in flow, mode
    assert '"runs-dir"' in flow  # stored payloads are read from the runs folder
    assert "public_1ubq.cif" in flow and str(m21.STRUCTURE).endswith("public_1ubq.cif")
    assert "synthetic-phenol-ligand.sdf" in flow


def test_package_script_runs_the_mutation_model_flow():
    package = (REPO / "frontend/package.json").read_text()
    assert '"test:offscreen:mutation-model": "node tests/offscreen/mutation-model-flow.cjs"' in package


def test_all_passing_rows_pass():
    judged = _judge()
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    for case in ("S-no-egress", m21.REPRO_CASE, m21.BUDGET_CASE):
        assert judged["cases"][case]["status"] == "pass", case
    assert set(judged["notObserved"]) == set(m21.NOT_OBSERVED)
    assert m21.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["MM-pair-partial"]
    judged = _judge(rows)
    assert judged["cases"]["MM-pair-partial"]["status"] == "fail"
    assert judged["passed"] is False
    rows = _rows()
    rows[0]["cases"]["MM-negative"] = "fail"
    assert _judge(rows)["cases"]["MM-negative"]["status"] == "fail"


def test_missing_step_fails_its_cases_budget_and_egress():
    judged = _judge([])
    assert judged["steps"]["model-main"]["status"] == "missing"
    assert judged["cases"]["MM-job"]["status"] == "fail"
    assert judged["cases"][m21.BUDGET_CASE]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        judged = _judge([_row("model-main", **bad)])
        assert judged["steps"]["model-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("budget", [
    None, {},
    {**BUDGET, "model": {"before": 0, "after": 2}},       # the model job must cost exactly one unit
    {**BUDGET, "pair": {"before": 1, "after": 2}},        # the same-condition action is two units
    {**BUDGET, "partial": {"before": 3, "after": 5}},     # the queued side cancelled before it started costs nothing
    {**BUDGET, "totalRunA": 9},                           # over the run limit
    {**BUDGET, "totalRunA": None},
])
def test_budget_counts_must_match(budget):
    judged = _judge([_row("model-main", budget=budget)])
    assert judged["cases"][m21.BUDGET_CASE]["status"] == "fail"
    assert judged["passed"] is False


@pytest.mark.parametrize("repro", [
    None, {}, {"error": "not run"},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN)]},  # one fresh run is not enough
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "contentSha256": "d" * 64}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "sameHandle": False}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "sameJob": False}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "providerCallsZero": False}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "status": "model failed"}]},
    {"reference": {}, "reruns": [dict(RERUN), dict(RERUN)]},
])
def test_reproducibility_must_match_the_flow_model(repro):
    judged = _judge(repro=repro)
    assert judged["cases"][m21.REPRO_CASE]["status"] == "fail"
    assert judged["passed"] is False


@pytest.mark.parametrize("environment", [
    {**ENV, "modelAvailable": False}, {**ENV, "candidatesAvailable": False}, {**ENV, "dockingAvailable": False}, {},
])
def test_environment_must_be_present(environment):
    judged = _judge(environment=environment)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = _judge(leftovers=["port 8000 still listening: pid 1"])
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m21.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m21.acceptance_ok(True, None) is False
    assert m21.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("model-main", {case: "fail" for case in _cases("model-main")}, status="fail")
    retried = _row("model-main-20261004T120000000000", _cases("model-main"))
    judged = _judge([failed, retried])
    assert judged["steps"]["model-main"]["latest"] == "model-main-20261004T120000000000"
    assert judged["steps"]["model-main"]["attempts"] == 2
    assert judged["passed"] is True
    assert _judge([retried, _row("model-main-20261004T130000000000", {}, status="fail")])["passed"] is False


def test_model_docking_and_qvina_workers_count_as_leftovers():
    assert {"openmm_mutation_worker.py", "docking_worker.py", "qvina2", "guardian.py"} <= set(m21.WORKERS)


def test_options():
    parser = m21.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.regressions, args.kbase) == ("auto", None, str(REPO), False, None)
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])


def test_default_out_is_the_m21_qa_folder():
    runner = m21.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m21-mutations-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m21.Runner(_args(**{field: "/tmp/m21-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m21.Runner(_args(**{field: "/private/tmp/m21-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m21.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m21.Runner(_args(artifacts=str(REPO / "docs/qa/m21-not-ignored")))


def test_regressions_need_kbase(tmp_path):
    with pytest.raises(SystemExit, match="kbase"):
        m21.Runner(_args(regressions=True))
    with pytest.raises(SystemExit, match="kbase"):
        m21.Runner(_args(regressions=True, kbase=str(tmp_path / "no-kbase")))


def test_regression_chain_is_opt_in_and_uses_fresh_folders(kbase):
    runner = m21.Runner(_args(regressions=True, kbase=kbase))
    commands = dict(runner.regression_commands())
    assert list(commands) == ["m20", "m19", "m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m21-test-root-{name}-regression")
        assert argv[argv.index("--artifacts") + 1].endswith(f"regressions/{name}")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m20", "m16", "m15"))
        assert "--regressions" not in argv
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m21.Runner(_args()).regressions is False


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m21.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
