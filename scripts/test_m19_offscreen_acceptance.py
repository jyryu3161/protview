"""Ledger judgement, environment, reproducibility and option rules of scripts/m19_offscreen_acceptance.py (no services
run here)."""

import argparse
import ast
from pathlib import Path

import pytest

from scripts import m19_offscreen_acceptance as m19

ENV = {"dockingPython": True, "qvina": True, "ligandPython": True, "mainAvailable": True, "singleAvailable": True,
       "candidatesAvailable": True, "layoutReason": "worker_missing"}
REPO = Path(m19.__file__).resolve().parents[1]
ROWS = [{"row_index": 0, "kind": "parent", "candidate_id": None, "state": "scored", "reason_code": None,
         "score_kcal_mol": -13.6, "score_row_label": "모드 1(엔진 출력 순서)", "resultSha256": "a" * 64,
         "posesSha256": "b" * 64},
        {"row_index": 1, "kind": "candidate", "candidate_id": "c_1", "state": "failed", "reason_code": "ligand_not_3d",
         "score_kcal_mol": None, "score_row_label": None}]
DIGEST = {"summarySha256": "c" * 64, "rows": ROWS}
REPRO = {"reference": dict(DIGEST), "reruns": [{**DIGEST, "status": "done", "providerCallsZero": True}] * 2}


def _cases(step):
    return [case for case, modes in m19.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m19.FLOW_STEPS]


def _args(**override):
    values = {"root": str(REPO / "runs/m19-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m19-test-out"), "code_root": str(REPO), "build": "never", "regressions": False,
              "kbase": None}
    return argparse.Namespace(**{**values, **override})


def test_every_spec_case_is_planned_and_covered():
    assert set(m19.CASE_PLAN) == set(m19.CASE_TEXT)
    assert all(modes and set(modes) <= set(m19.FLOW_STEPS) for modes in m19.CASE_PLAN.values())
    assert all(_cases(step) for step in m19.FLOW_STEPS)
    assert set(m19.MODE_OF) == set(m19.FLOW_STEPS)
    assert len(m19.CASE_PLAN) == 24
    for case in ("B-select", "B-preflight", "B-limit-approval", "B-sort", "B-detail", "B-report", "B-reuse", "B-cancel",
                 "B-core-parent-disabled", "B-fail-row", "B-refusal", "B-wording", "B-dry-run", "B-processes",
                 "B-unavailable"):
        assert case in m19.CASE_PLAN, case
    assert m19.REPRO_CASE not in m19.CASE_PLAN
    assert set(m19.NOT_OBSERVED) == {"B-dry-run-shortfall", "B-null-result", "B-time-limits"}
    assert not set(m19.NOT_OBSERVED) & set(m19.CASE_PLAN)


def test_flow_declares_every_planned_case_mode_and_not_observed_case():
    flow = (REPO / "frontend/tests/offscreen" / m19.FLOW).read_text()
    for case in [*m19.CASE_PLAN, *m19.NOT_OBSERVED]:
        assert f'"{case}"' in flow, case
    for mode in m19.MODE_OF.values():
        assert f'"{mode}"' in flow, mode
    assert '"runs-dir"' in flow  # stored objects are read from the backend runs folder


def test_package_script_runs_the_batch_flow():
    package = (REPO / "frontend/package.json").read_text()
    assert '"test:offscreen:docking-batch": "node tests/offscreen/docking-batch-flow.cjs"' in package


def test_all_passing_rows_pass():
    judged = m19.assemble(_rows(), [], ENV, REPRO)
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert judged["cases"]["S-no-egress"]["status"] == "pass"
    assert judged["cases"][m19.REPRO_CASE]["status"] == "pass"
    assert set(judged["notObserved"]) == set(m19.NOT_OBSERVED)
    assert m19.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_from_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["B-cancel"]
    judged = m19.assemble(rows, [], ENV, REPRO)
    assert judged["cases"]["B-cancel"]["status"] == "fail"
    assert judged["passed"] is False


def test_a_failed_case_fails_even_if_the_row_says_pass():
    rows = _rows()
    rows[0]["cases"]["B-wording"] = "fail"
    judged = m19.assemble(rows, [], ENV, REPRO)
    assert judged["cases"]["B-wording"]["status"] == "fail"
    assert judged["passed"] is False


def test_missing_step_fails_its_cases_and_egress():
    judged = m19.assemble(_rows()[:1], [], ENV, REPRO)
    assert judged["steps"]["batch-unavailable"]["status"] == "missing"
    assert judged["cases"]["B-unavailable"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        rows = _rows()
        rows[0] = _row("batch-main", **bad)
        judged = m19.assemble(rows, [], ENV, REPRO)
        assert judged["steps"]["batch-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("repro", [
    None, {}, {"error": "not run"},
    {"reference": dict(DIGEST), "reruns": REPRO["reruns"][:1]},  # one re-run is not enough
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "summarySha256": "d" * 64, "status": "done",
                                                                  "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "rows": [{**ROWS[0], "score_kcal_mol": -13.5},
                                                                                     ROWS[1]], "status": "done",
                                                                  "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "rows": [{**ROWS[0], "posesSha256": "e" * 64},
                                                                                     ROWS[1]], "status": "done",
                                                                  "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "status": "cancelled", "providerCallsZero": True}]},
    {"reference": dict(DIGEST), "reruns": [REPRO["reruns"][0], {**DIGEST, "status": "done", "providerCallsZero": False}]},
    # a reference without any scored row proves nothing about the engine
    {"reference": {**DIGEST, "rows": [ROWS[1]]}, "reruns": [{**DIGEST, "rows": [ROWS[1]], "status": "done",
                                                            "providerCallsZero": True}] * 2},
])
def test_reproducibility_must_match_the_flow_batch(repro):
    judged = m19.assemble(_rows(), [], ENV, repro)
    assert judged["cases"][m19.REPRO_CASE]["status"] == "fail"
    assert judged["passed"] is False


def test_the_batch_digest_never_overwrites_the_job_status():
    # a re-run entry carries the job status ("done"); the summary status lives under its own key
    source = Path(m19.__file__).read_text()
    assert '"batchStatus": content["status"]' in source and '"status": content["status"]' not in source


def test_normalization_hides_only_run_scoped_handles_and_input_hashes():
    one = {"input_sha256": "1" * 64, "batch_input_sha256": "2" * 64, "receptor": {"handle": "obj://run_a/x/1"},
           "rows": [{"result_handle": "obj://run_a/docking_result/3", "score_kcal_mol": -12.1}]}
    other = {"input_sha256": "4" * 64, "batch_input_sha256": "5" * 64, "receptor": {"handle": "obj://run_b/x/6"},
             "rows": [{"result_handle": "obj://run_b/docking_result/7", "score_kcal_mol": -12.1}]}
    assert m19.content_sha(one) == m19.content_sha(other)
    changed = {**other, "rows": [{"result_handle": "obj://run_b/docking_result/7", "score_kcal_mol": -12.2}]}
    assert m19.content_sha(one) != m19.content_sha(changed)
    assert m19.content_sha({**one, "receptor": {"sha256": "8" * 64}}) != m19.content_sha({**one, "receptor": {
        "sha256": "9" * 64}}), "content hashes other than the input hashes stay compared"


@pytest.mark.parametrize("environment", [
    {**ENV, "dockingPython": False},  # no .deps/docking/venv-locked: a failure, never "unavailable"
    {**ENV, "qvina": False},
    {**ENV, "ligandPython": False},
    {**ENV, "mainAvailable": False},
    {**ENV, "singleAvailable": False},
    {**ENV, "candidatesAvailable": False},
    {**ENV, "layoutReason": "available"},
    {**ENV, "layoutReason": "engine_missing"},
    {},
])
def test_environment_must_be_present_and_the_layout_must_lack_it(environment):
    judged = m19.assemble(_rows(), [], environment, REPRO)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = m19.assemble(_rows(), ["port 8000 still listening: pid 1"], ENV, REPRO)
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m19.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m19.acceptance_ok(True, None) is False
    assert m19.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("batch-main", {case: "fail" for case in _cases("batch-main")}, status="fail")
    retried = _row("batch-main-20261003T120000000000", _cases("batch-main"))
    rows = [failed, retried, _rows()[1]]
    judged = m19.assemble(rows, [], ENV, REPRO)
    assert judged["steps"]["batch-main"]["latest"] == "batch-main-20261003T120000000000"
    assert judged["steps"]["batch-main"]["attempts"] == 2
    assert judged["passed"] is True
    rows = [retried, _row("batch-main-20261003T130000000000", {}, status="fail"), _rows()[1]]
    assert m19.assemble(rows, [], ENV, REPRO)["passed"] is False


def test_batch_docking_qvina_and_ligand_workers_count_as_leftovers():
    assert {"docking_batch_worker.py", "docking_worker.py", "qvina2", "ligand_worker.py"} <= set(m19.WORKERS)
    assert set(m19.m13.WORKERS) <= set(m19.WORKERS)


def test_options():
    parser = m19.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.regressions, args.kbase) == ("auto", None, str(REPO), False, None)
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])


def test_default_out_is_the_m19_qa_folder():
    runner = m19.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m19-batch-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m19.Runner(_args(**{field: "/tmp/m19-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m19.Runner(_args(**{field: "/private/tmp/m19-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m19.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m19.Runner(_args(artifacts=str(REPO / "docs/qa/m19-not-ignored")))


def test_regression_chain_is_opt_in_and_uses_fresh_folders():
    runner = m19.Runner(_args(regressions=True, kbase="/abs/kbase"))
    commands = dict(runner.regression_commands())
    assert list(commands) == ["m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m19-test-root-{name}-regression")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m16", "m15"))
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m19.Runner(_args()).regressions is False


def test_reproducibility_uses_the_flow_fixture_files():
    for rel in m19.REPRO_FILES.values():
        assert (REPO / rel).is_file(), rel
    flow = (REPO / "frontend/tests/offscreen" / m19.FLOW).read_text()
    assert "chemical/prolif-vina-rec.pdb" in flow and "public-derived-parent-record0.sdf" in flow
    assert "synthetic-docking-blocks.smi" in flow
    assert m19.SITE_ATOM == 22 and "SITE_ATOM = 22" in flow


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m19.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
