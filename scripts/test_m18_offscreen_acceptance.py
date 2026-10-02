"""Ledger judgement, environment, reproducibility and option rules of scripts/m18_offscreen_acceptance.py (no services
run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m18_offscreen_acceptance as m18

ENV = {"dockingPython": True, "qvina": True, "ligandPython": True, "mainAvailable": True, "candidatesAvailable": True,
       "layoutReason": "worker_missing"}
REPO = Path(m18.__file__).resolve().parents[1]
DIGEST = {"scores": [-13.6, -12.8], "posesSha256": "a" * 64}
REPRO = {"reference": dict(DIGEST), "reruns": [{**DIGEST, "status": "done", "providerCallsZero": True}] * 2}


def _cases(step):
    return [case for case, modes in m18.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m18.FLOW_STEPS]


def _args(**override):
    values = {"root": str(REPO / "runs/m18-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m18-test-out"), "code_root": str(REPO), "build": "never"}
    return argparse.Namespace(**{**values, **override})


def test_every_spec_case_is_planned_and_covered():
    assert set(m18.CASE_PLAN) == set(m18.CASE_TEXT)
    assert all(modes and set(modes) <= set(m18.FLOW_STEPS) for modes in m18.CASE_PLAN.values())
    assert all(_cases(step) for step in m18.FLOW_STEPS)
    assert set(m18.MODE_OF) == set(m18.FLOW_STEPS)
    assert len(m18.CASE_PLAN) == 22
    assert "D-reject-receptor" in m18.CASE_PLAN
    assert m18.REPRO_CASE not in m18.CASE_PLAN and "D-zero-modes" not in m18.CASE_PLAN
    assert set(m18.NOT_OBSERVED) == {"D-zero-modes"}


def test_flow_declares_every_planned_case_and_mode():
    flow = (REPO / "frontend/tests/offscreen" / m18.FLOW).read_text()
    for case in m18.CASE_PLAN:
        assert f'"{case}"' in flow, case
    for mode in m18.MODE_OF.values():
        assert f'"{mode}"' in flow, mode
    assert '"runs-dir"' in flow  # stored pose bytes are read from the backend runs folder
    assert "D-zero-modes" in flow  # recorded as not observed, never forged


def test_package_script_runs_the_docking_flow():
    package = (REPO / "frontend/package.json").read_text()
    assert '"test:offscreen:docking": "node tests/offscreen/docking-flow.cjs"' in package


def test_all_passing_rows_pass():
    judged = m18.assemble(_rows(), [], ENV, REPRO)
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert judged["cases"]["S-no-egress"]["status"] == "pass"
    assert judged["cases"][m18.REPRO_CASE]["status"] == "pass"
    assert "D-zero-modes" not in judged["cases"] and "D-zero-modes" in judged["notObserved"]
    assert m18.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_from_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["D-cancel"]
    judged = m18.assemble(rows, [], ENV, REPRO)
    assert judged["cases"]["D-cancel"]["status"] == "fail"
    assert judged["passed"] is False


def test_a_failed_case_fails_even_if_the_row_says_pass():
    rows = _rows()
    rows[0]["cases"]["D-wording"] = "fail"
    judged = m18.assemble(rows, [], ENV, REPRO)
    assert judged["cases"]["D-wording"]["status"] == "fail"
    assert judged["passed"] is False


def test_missing_step_fails_its_cases_and_egress():
    judged = m18.assemble(_rows()[:1], [], ENV, REPRO)
    assert judged["steps"]["docking-unavailable"]["status"] == "missing"
    assert judged["cases"]["D-unavailable"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        rows = _rows()
        rows[0] = _row("docking-main", **bad)
        judged = m18.assemble(rows, [], ENV, REPRO)
        assert judged["steps"]["docking-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("repro", [
    None, {}, {"error": "not run"},
    {"reference": dict(DIGEST), "reruns": REPRO["reruns"][:1]},  # one re-run is not enough
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "status": "done", "scores": [-13.5, -12.8],
                                                                  "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "status": "done", "posesSha256": "b" * 64,
                                                                  "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "status": "failed", "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "status": "done", "providerCallsZero": False}]},
    {"reference": {"scores": [], "posesSha256": None}, "reruns": [{"scores": [], "posesSha256": None, "status": "done",
                                                                  "providerCallsZero": True}] * 2},
])
def test_reproducibility_must_match_the_flow_result(repro):
    judged = m18.assemble(_rows(), [], ENV, repro)
    assert judged["cases"][m18.REPRO_CASE]["status"] == "fail"
    assert judged["passed"] is False


@pytest.mark.parametrize("environment", [
    {**ENV, "dockingPython": False},  # no .deps/docking/venv-locked: a failure, never "unavailable"
    {**ENV, "qvina": False},
    {**ENV, "ligandPython": False},
    {**ENV, "mainAvailable": False},
    {**ENV, "candidatesAvailable": False},
    {**ENV, "layoutReason": "available"},
    {**ENV, "layoutReason": "engine_missing"},
    {},
])
def test_environment_must_be_present_and_the_layout_must_lack_it(environment):
    judged = m18.assemble(_rows(), [], environment, REPRO)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = m18.assemble(_rows(), ["port 8000 still listening: pid 1"], ENV, REPRO)
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m18.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m18.acceptance_ok(True, None) is False
    assert m18.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("docking-main", {case: "fail" for case in _cases("docking-main")}, status="fail")
    retried = _row("docking-main-20261002T120000000000", _cases("docking-main"))
    rows = [failed, retried, _rows()[1]]
    judged = m18.assemble(rows, [], ENV, REPRO)
    assert judged["steps"]["docking-main"]["latest"] == "docking-main-20261002T120000000000"
    assert judged["steps"]["docking-main"]["attempts"] == 2
    assert judged["passed"] is True
    rows = [retried, _row("docking-main-20261002T130000000000", {}, status="fail"), _rows()[1]]
    assert m18.assemble(rows, [], ENV, REPRO)["passed"] is False


def test_docking_qvina_and_ligand_workers_count_as_leftovers():
    assert {"docking_worker.py", "qvina2", "ligand_worker.py"} <= set(m18.WORKERS)
    assert set(m18.m13.WORKERS) <= set(m18.WORKERS)


def test_options():
    parser = m18.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root) == ("auto", None, str(REPO))
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--kbase", "k"])  # no reference snapshot is used


def test_default_out_is_the_m18_qa_folder():
    runner = m18.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m18-docking-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m18.Runner(_args(**{field: "/tmp/m18-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m18.Runner(_args(**{field: "/private/tmp/m18-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m18.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m18.Runner(_args(artifacts=str(REPO / "docs/qa/m18-not-ignored")))


def test_layout_lacks_every_locked_environment():
    # the unavailable step relies on the copied layout lacking all three interpreters/executables
    assert {m18.DOCKING_PYTHON, m18.QVINA, m18.LIGAND_PYTHON} == {
        Path(".deps/docking/venv-locked/bin/python"), Path(".deps/qvina/env/bin/qvina2"),
        Path(".deps/prolif/venv-locked/bin/python")}
    assert all(path.parts[0] == ".deps" for path in (m18.DOCKING_PYTHON, m18.QVINA, m18.LIGAND_PYTHON))


def test_reproducibility_uses_the_flow_fixture_files():
    for rel in m18.REPRO_FILES.values():
        assert (REPO / rel).is_file(), rel
    flow = (REPO / "frontend/tests/offscreen" / m18.FLOW).read_text()
    assert "chemical/prolif-vina-rec.pdb" in flow and "public-derived-parent-record0.sdf" in flow
    assert all(m18.ACK.values()) and len(m18.ACK) == 3


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m18.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
