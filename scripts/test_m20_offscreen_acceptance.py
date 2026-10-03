"""Ledger judgement, environment, reproducibility and option rules of scripts/m20_offscreen_acceptance.py (no services
run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m20_offscreen_acceptance as m20

ENV = {"mutationAvailable": True, "pocketAvailable": True}
REFERENCE = {"reference-import": {"status": "pass", "setHash": "f" * 64}}
REPO = Path(m20.__file__).resolve().parents[1]
RERUN = {"status": "done", "sameHandle": True, "contentSha256": "c" * 64, "providerCallsZero": True}
REPRO = {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), dict(RERUN)]}


def _cases(step):
    return [case for case, modes in m20.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m20.FLOW_STEPS]


def _judge(rows=None, leftovers=(), environment=None, reference=None, repro=REPRO):
    return m20.assemble(_rows() if rows is None else rows, list(leftovers), ENV if environment is None else environment,
                        REFERENCE if reference is None else reference, repro)


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


def _args(kbase, **override):
    values = {"root": str(REPO / "runs/m20-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m20-test-out"), "code_root": str(REPO), "build": "never", "regressions": False,
              "kbase": kbase}
    return argparse.Namespace(**{**values, **override})


def test_every_spec_case_is_planned_and_covered():
    assert set(m20.CASE_PLAN) == set(m20.CASE_TEXT)
    assert all(modes and set(modes) <= set(m20.FLOW_STEPS) for modes in m20.CASE_PLAN.values())
    assert set(m20.MODE_OF) == set(m20.FLOW_STEPS)
    assert len(m20.CASE_PLAN) == 22
    # spec §12 화면: request inputs, sources, protection/release, run, filters, sort, paging, report, unavailable,
    # empty result, refusals, late responses
    for case in ("M-ligand-explicit", "M-not-checked", "M-protect-release", "M-pocket", "M-allowed-shrink",
                 "M-filters-sort", "M-paging", "M-zero", "M-refused", "M-unprepared", "M-no-run", "M-report",
                 "M-late-result", "M-late-run", "M-tab-state", "M-wording"):
        assert case in m20.CASE_PLAN, case
    assert m20.REPRO_CASE not in m20.CASE_PLAN
    assert not set(m20.NOT_OBSERVED) & set(m20.CASE_PLAN)


def test_flow_declares_every_planned_case_and_mode():
    flow = (REPO / "frontend/tests/offscreen" / m20.FLOW).read_text()
    for case in m20.CASE_PLAN:
        assert f'"{case}"' in flow, case
    for mode in m20.MODE_OF.values():
        assert f'"{mode}"' in flow, mode
    assert '"set-hash"' in flow  # the numbering map is checked against the imported reference set
    assert "public_1mq4.cif" in flow and str(m20.STRUCTURE).endswith("public_1mq4.cif")


def test_package_script_runs_the_mutation_flow():
    package = (REPO / "frontend/package.json").read_text()
    assert '"test:offscreen:mutations": "node tests/offscreen/mutation-flow.cjs"' in package


def test_all_passing_rows_pass():
    judged = _judge()
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert judged["cases"]["S-no-egress"]["status"] == "pass"
    assert judged["cases"][m20.REPRO_CASE]["status"] == "pass"
    assert set(judged["notObserved"]) == set(m20.NOT_OBSERVED)
    assert m20.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["M-refused"]
    judged = _judge(rows)
    assert judged["cases"]["M-refused"]["status"] == "fail"
    assert judged["passed"] is False
    rows = _rows()
    rows[0]["cases"]["M-wording"] = "fail"
    assert _judge(rows)["cases"]["M-wording"]["status"] == "fail"


def test_missing_step_fails_its_cases_and_egress():
    judged = _judge([])
    assert judged["steps"]["mutation-main"]["status"] == "missing"
    assert judged["cases"]["M-zero"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        judged = _judge([_row("mutation-main", **bad)])
        assert judged["steps"]["mutation-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("repro", [
    None, {}, {"error": "not run"},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN)]},  # one fresh run is not enough
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "contentSha256": "d" * 64}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "sameHandle": False}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {**RERUN, "providerCallsZero": False}]},
    {"reference": {"contentSha256": "c" * 64}, "reruns": [dict(RERUN), {"status": "prepare 422"}]},
    {"reference": {}, "reruns": [dict(RERUN), dict(RERUN)]},
])
def test_reproducibility_must_match_the_flow_set(repro):
    judged = _judge(repro=repro)
    assert judged["cases"][m20.REPRO_CASE]["status"] == "fail"
    assert judged["passed"] is False


def test_normalization_hides_only_run_scoped_handles():
    one = {"structure": {"handle": "obj://run_a/prepared_structure/1"}, "counts": {"candidates": 342},
           "positions": [{"ligand_min_distance_A": 2.6283578523481124}]}
    other = {"structure": {"handle": "obj://run_b/prepared_structure/2"}, "counts": {"candidates": 342},
             "positions": [{"ligand_min_distance_A": 2.6283578523481124}]}
    assert m20.content_sha(one) == m20.content_sha(other)
    changed = {**other, "positions": [{"ligand_min_distance_A": 2.62835785234812}]}
    assert m20.content_sha(one) != m20.content_sha(changed)
    assert m20.content_sha({**one, "counts": {"candidates": 341}}) != m20.content_sha(one)


@pytest.mark.parametrize("environment", [
    {**ENV, "mutationAvailable": False}, {**ENV, "pocketAvailable": False}, {},
])
def test_environment_must_be_present(environment):
    judged = _judge(environment=environment)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


@pytest.mark.parametrize("reference", [{}, {"reference-import": {"status": "fail"}},
                                       {"reference-import": {"status": "pass", "setHash": None}}])
def test_reference_import_must_pass(reference):
    judged = _judge(reference=reference)
    assert judged["verdictParts"]["reference"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = _judge(leftovers=["port 8000 still listening: pid 1"])
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m20.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m20.acceptance_ok(True, None) is False
    assert m20.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("mutation-main", {case: "fail" for case in _cases("mutation-main")}, status="fail")
    retried = _row("mutation-main-20261003T120000000000", _cases("mutation-main"))
    judged = _judge([failed, retried])
    assert judged["steps"]["mutation-main"]["latest"] == "mutation-main-20261003T120000000000"
    assert judged["steps"]["mutation-main"]["attempts"] == 2
    assert judged["passed"] is True
    assert _judge([retried, _row("mutation-main-20261003T130000000000", {}, status="fail")])["passed"] is False


def test_fpocket_and_pocket_workers_count_as_leftovers():
    assert {"fpocket", "pocket_worker.py", "guardian.py"} <= set(m20.WORKERS)


def test_options():
    parser = m20.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.regressions) == ("auto", None, str(REPO), False)
    assert args.kbase == str(REPO.parent / "kbase_kinase")
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])


def test_default_out_is_the_m20_qa_folder(kbase):
    runner = m20.Runner(_args(kbase, out=None))
    assert runner.out.parent.name.startswith("m20-mutations-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(kbase, field):
    with pytest.raises(SystemExit, match="/tmp"):
        m20.Runner(_args(kbase, **{field: "/tmp/m20-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m20.Runner(_args(kbase, **{field: "/private/tmp/m20-qa"}))


def test_repository_runs_folder_tracked_artifacts_and_missing_kbase_are_refused(kbase, tmp_path):
    with pytest.raises(SystemExit, match="fresh folder"):
        m20.Runner(_args(kbase, root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m20.Runner(_args(kbase, artifacts=str(REPO / "docs/qa/m20-not-ignored")))
    with pytest.raises(SystemExit, match="manifest"):
        m20.Runner(_args(str(tmp_path / "no-kbase")))


def test_regression_chain_is_opt_in_and_uses_fresh_folders(kbase):
    runner = m20.Runner(_args(kbase, regressions=True))
    commands = dict(runner.regression_commands())
    assert list(commands) == ["m19", "m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m20-test-root-{name}-regression")
        assert argv[argv.index("--artifacts") + 1].endswith(f"regressions/{name}")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m16", "m15"))
        assert "--regressions" not in argv
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m20.Runner(_args(kbase)).regressions is False


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m20.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
