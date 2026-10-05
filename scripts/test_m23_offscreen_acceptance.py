"""Ledger judgement, environment, reproducibility, oracle-path and option rules of scripts/m23_offscreen_acceptance.py
(no services run here)."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

import pytest

from scripts import m23_offscreen_acceptance as m23

ENV = {"dockingPython": True, "qvina": True, "projectPython": True, "mainAvailable": True, "modelAvailable": True,
       "candidatesAvailable": True, "dockingAvailable": True, "layoutReason": "worker_missing"}
REPO = Path(m23.__file__).resolve().parents[1]
ROWS = [{"generation": "reference", "position": None, "key": "wild_type", "state": "scored", "score": -3.0,
         "modelSha256": "m" * 64, "resultSha256": "r" * 64, "posesSha256": "p" * 64},
        {"generation": 1, "position": 0, "key": "3", "state": "scored", "score": -3.6, "modelSha256": "n" * 64,
         "resultSha256": "s" * 64, "posesSha256": "q" * 64}]
RERUN = {"status": "done", "providerCallsZero": True, "argsEqual": True, "summarySha256": "s" * 64, "rows": ROWS}
REPRO = {"reference": {"summarySha256": "s" * 64, "rows": ROWS}, "reruns": [dict(RERUN), dict(RERUN)]}
CHECK = {"conditions": True, "equal": True}
ORACLE = {"checks": [{"name": "ga1", **CHECK}, {"name": "ga2", **CHECK}]}
EXPECTED = json.loads((REPO / m23.EXPECTED_FILE).read_text())


def _cases(step):
    return [case for case, modes in m23.CASE_PLAN.items() if step in modes]


def _row(step, cases=None, status="pass", external=0, provider=True):
    cases = _cases(step) if cases is None else cases
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider}


def _rows():
    return [_row(step) for step in m23.FLOW_STEPS]


def _judge(rows=None, leftovers=(), environment=None, repro=REPRO, oracle=ORACLE):
    return m23.assemble(_rows() if rows is None else rows, list(leftovers), ENV if environment is None else environment,
                        repro, oracle)


def _args(**override):
    values = {"root": str(REPO / "runs/m23-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m23-test-out"), "code_root": str(REPO), "build": "never", "regressions": False,
              "kbase": None}
    return argparse.Namespace(**{**values, **override})


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


def test_every_spec_case_is_planned_and_covered():
    assert set(m23.CASE_PLAN) == set(m23.CASE_TEXT)
    assert all(modes and set(modes) <= set(m23.FLOW_STEPS) for modes in m23.CASE_PLAN.values())
    assert set(m23.MODE_OF) == set(m23.FLOW_STEPS)
    # spec 10/12 screen cases: guards, preflight and the limit approval, a real GA with progress, results, oracle path,
    # sort, detail, downloads, reuse, partial, cancel, reference failure, late response, report, tabs, unavailable
    for case in ("SG-param-guards", "SG-cross-rules", "SG-defaults", "SG-confirmations", "SG-refusals", "SG-preflight",
                 "SG-limit-approval", "SG-run", "SG-progress", "SG-results", "SG-oracle-path", "SG-sort", "SG-detail",
                 "SG-download", "SG-dedupe", "SG-reuse", "SG-partial", "SG-cancel", "SG-reference-failed",
                 "SG-late-response", "SG-report", "SG-tabs", "SG-processes", "SG-wording", "SG-no-run",
                 "SG-unavailable", "SG-no-candidate-set", "SG-initial-state", "SG-repro-runs"):
        assert case in m23.CASE_PLAN, case
    assert m23.CASE_PLAN["SG-no-run"] == ["seqga-main", "seqga-unavailable"]
    assert m23.CASE_PLAN["SG-unavailable"] == ["seqga-unavailable"]
    assert m23.CASE_PLAN["SG-repro-runs"] == ["seqga-repro"]
    assert not {m23.REPRO_CASE, m23.ORACLE_CASE} & set(m23.CASE_PLAN)
    assert not set(m23.NOT_OBSERVED) & set(m23.CASE_PLAN)
    assert "SG-individual-without-score" in m23.NOT_OBSERVED  # no score-less individual from the real engine; never forged


def test_flow_declares_every_planned_case_and_mode():
    flow = (REPO / "frontend/tests/offscreen" / m23.FLOW).read_text()
    for case in m23.CASE_PLAN:
        assert f'"{case}"' in flow, case
    for mode in m23.MODE_OF.values():
        assert f'"{mode}"' in flow, mode
    for case in m23.NOT_OBSERVED:
        assert f'"{case}"' in flow, case
    assert '"runs-dir"' in flow  # stored payloads are read from the runs folder
    assert m23.ORACLE_SCORES in flow and "m20-candidate-set-1ubq-tiny.json" in flow
    assert "synthetic-phenol-ligand.sdf" in flow and str(m23.PHENOL_FILE).endswith("synthetic-phenol-ligand.sdf")


def test_flow_and_runner_never_post_the_limit_raise():
    # the flow only waits for the response of the screen's own button; it never sends a request itself
    flow = (REPO / "frontend/tests/offscreen" / m23.FLOW).read_text()
    assert "page.request.post" not in flow and "page.request.fetch" not in flow
    runner = Path(m23.__file__).read_text()
    assert "limit_approval" not in runner
    assert '"POST"' not in runner  # the runner only reads (GET) the loopback API


def test_all_passing_rows_pass():
    judged = _judge()
    assert judged["passed"] is True
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    for case in ("S-no-egress", m23.REPRO_CASE, m23.ORACLE_CASE):
        assert judged["cases"][case]["status"] == "pass", case
    assert set(judged["notObserved"]) == set(m23.NOT_OBSERVED)
    assert m23.acceptance_ok(judged["passed"], {"buildCurrentWithSource": True}) is True


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    del rows[0]["cases"]["SG-reuse"]
    judged = _judge(rows)
    assert judged["cases"]["SG-reuse"]["status"] == "fail"
    assert judged["passed"] is False
    rows = _rows()
    rows[2]["cases"]["SG-unavailable"] = "fail"
    assert _judge(rows)["cases"]["SG-unavailable"]["status"] == "fail"
    rows = _rows()
    rows[2]["cases"]["SG-no-run"] = "fail"   # observed in two modes: both must pass
    assert _judge(rows)["cases"]["SG-no-run"]["status"] == "fail"


def test_missing_step_fails_its_cases_and_egress():
    judged = _judge([_row("seqga-main"), _row("seqga-unavailable")])
    assert judged["steps"]["seqga-repro"]["status"] == "missing"
    assert judged["cases"]["SG-repro-runs"]["status"] == "fail"
    assert judged["cases"]["S-no-egress"]["status"] == "fail"
    assert judged["passed"] is False


def test_unmeasured_or_nonzero_egress_and_provider_calls_fail():
    for bad in ({"external": None}, {"external": 1}, {"provider": None}, {"provider": False}):
        judged = _judge([_row("seqga-main", **bad), _row("seqga-repro"), _row("seqga-unavailable")])
        assert judged["steps"]["seqga-main"]["status"] == "fail", bad
        assert judged["cases"]["S-no-egress"]["status"] == "fail", bad
        assert judged["passed"] is False


@pytest.mark.parametrize("repro", [
    None, {}, {"error": "not run"},
    {**REPRO, "reruns": [dict(RERUN)]},                                     # one replay is not enough
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "summarySha256": "t" * 64}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "rows": [ROWS[0], {**ROWS[1], "score": -3.5}]}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "rows": [ROWS[0], {**ROWS[1], "modelSha256": "x" * 64}]}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "providerCallsZero": False}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "status": "failed"}]},
    {**REPRO, "reruns": [dict(RERUN), {**RERUN, "argsEqual": False}]},       # other inputs are not a replay
    {"reference": {"summarySha256": "s" * 64, "rows": []}, "reruns": [dict(RERUN), dict(RERUN)]},
    {"reference": {"summarySha256": "s" * 64, "rows": [{**ROWS[1], "state": "failed"}]},
     "reruns": [dict(RERUN), dict(RERUN)]},                                 # nothing scored: nothing compared
])
def test_reproducibility_must_match_the_flow_ga(repro):
    judged = _judge(repro=repro)
    assert judged["cases"][m23.REPRO_CASE]["status"] == "fail"
    assert judged["passed"] is False


@pytest.mark.parametrize("oracle", [
    None, {}, {"error": "not run"}, {"checks": [{"name": "ga1", **CHECK}]},
    {"checks": [{"name": "ga1", **CHECK}, {"name": "ga2", "conditions": True, "equal": False}]},
    {"checks": [{"name": "ga1", "conditions": False, "equal": True}, {"name": "ga2", **CHECK}]},
    {"checks": [{"name": "ga1", **CHECK}, {"name": "ga1", **CHECK}]},
])
def test_oracle_paths_must_cover_both_gas_under_the_t1_conditions(oracle):
    judged = _judge(oracle=oracle)
    assert judged["cases"][m23.ORACLE_CASE]["status"] == "fail"
    assert judged["passed"] is False


def test_normalization_replaces_only_run_scoped_values():
    content = {"candidate_set": "obj://run_a/mutation_candidate_set/x", "call_key": "k" * 64, "selection_sha256": "s" * 64,
               "conditions_sha256": "c" * 64, "input_sha256": "i" * 64, "score": -3.6, "structure_sha256": "z" * 64,
               "energy": {"before_kJ_mol": -8046.1, "after_kJ_mol": -9012.3},
               "generations": [{"individuals": [{"result_handle": "obj://run_a/docking_result/y", "score": -3.6}]}]}
    other = {**content, "candidate_set": "obj://run_b/mutation_candidate_set/z", "call_key": "d" * 64,
             "selection_sha256": "t" * 64, "conditions_sha256": "e" * 64, "input_sha256": "j" * 64,
             "generations": [{"individuals": [{"result_handle": "obj://run_b/docking_result/w", "score": -3.6}]}]}
    assert m23.content_sha(content) == m23.content_sha(other)
    for changed in ({"score": -3.5}, {"structure_sha256": "y" * 64}, {"energy": {"before_kJ_mol": -8046.0,
                                                                                  "after_kJ_mol": -9012.3}}):
        assert m23.content_sha(content) != m23.content_sha({**content, **changed}), changed
    assert m23.RUN_SCOPED_KEYS == {"input_sha256", "selection_sha256", "conditions_sha256", "call_key"}
    assert m23.differing_paths(content, {**content, "score": -3.5}) == ["$.score"]
    assert m23.differing_paths(content, other) == []


def test_runner_oracle_reproduces_the_t1_vector_and_its_reuse_variant():
    module = m23.load_oracle(REPO)
    space, vector = EXPECTED["spaces"][m23.ORACLE_SPACE], EXPECTED["vectors"][m23.ORACLE_SCORES]
    want = m23.path_view(vector["expected"])
    assert m23.path_view(module.run_ga(space, vector["scores"], [], dict(vector["ga"]))) == want
    assert want["stop_reason"] == "no_change" and want["new_evaluations_used"] == 10
    reuse = EXPECTED["vectors"]["s4_tiny_observed_reuse"]
    assert m23.path_view(module.run_ga(space, reuse["scores"], list(reuse["reusable"]), dict(reuse["ga"]))) == \
        m23.path_view(reuse["expected"])


def test_reuse_index_takes_rows_with_stored_results_and_the_reference_row():
    content = {"reference": {"state": "scored"}, "generations": [{"individuals": [
        {"key": "3", "origin": "initial", "state": "scored"}, {"key": "1", "origin": "initial", "state": "failed"},
        {"key": "0-2", "origin": "initial", "state": "null_result"}]}, {"individuals": [
            {"key": "3", "origin": "carried", "state": "scored"}, {"key": "5", "origin": "edit", "state": "scored"}]}]}
    assert m23.reuse_index(content) == ["3", "0-2", "5", "wild_type"]
    assert m23.reuse_index({**content, "reference": {"state": "failed"}}) == ["3", "0-2", "5"]


def test_t1_conditions_need_the_phenol_box_values_and_space():
    phenol = hashlib.sha256((REPO / m23.PHENOL_FILE).read_bytes()).hexdigest()
    space = EXPECTED["vectors"][m23.ORACLE_SCORES]["expected"]["space"]
    content = {"ligand": {"sdf_sha256": phenol}, "box": {"source": "ligand_range", "margin_A": 8, "center_A": [0, 0, 0]},
               "parameters": {**m23.T1_PARAMETERS, "cpu": 1}, "space": dict(space)}
    assert m23.t1_conditions(content, phenol, space) is True
    for changed in ({"ligand": {"sdf_sha256": "0" * 64}}, {"box": {"source": "manual"}},
                    {"box": {"source": "ligand_range", "margin_A": 6}},
                    {"box": {"source": "ligand_range", "center_A": [0, 0, 0]}},       # T10: no margin is not 8 Å
                    {"box": {"source": "ligand_range", "margin_A": None}}, {"box": None},
                    {"parameters": {**m23.T1_PARAMETERS, "seed": 7, "cpu": 1}},
                    {"parameters": {**m23.T1_PARAMETERS, "cpu": 2}}, {"space": {**space, "size": 6}}):
        assert m23.t1_conditions({**content, **changed}, phenol, space) is False, changed


@pytest.mark.parametrize("environment", [
    {**ENV, "dockingPython": False}, {**ENV, "qvina": False}, {**ENV, "projectPython": False},
    {**ENV, "mainAvailable": False}, {**ENV, "modelAvailable": False}, {**ENV, "candidatesAvailable": False},
    {**ENV, "dockingAvailable": False}, {**ENV, "layoutReason": "available"}, {},
])
def test_environment_must_be_present(environment):
    judged = _judge(environment=environment)
    assert judged["verdictParts"]["environment"] is False
    assert judged["passed"] is False


def test_leftovers_and_stale_build_fail():
    judged = _judge(leftovers=["port 8000 still listening: pid 1"])
    assert judged["verdictParts"]["leftoverProcesses"] is False
    assert judged["passed"] is False
    assert m23.acceptance_ok(True, {"buildCurrentWithSource": False}) is False
    assert m23.acceptance_ok(True, None) is False
    assert m23.acceptance_ok(False, {"buildCurrentWithSource": True}) is False


def test_latest_attempt_decides():
    failed = _row("seqga-main", {case: "fail" for case in _cases("seqga-main")}, status="fail")
    retried = _row("seqga-main-20261005T120000000000", _cases("seqga-main"))
    judged = _judge([failed, retried, _row("seqga-repro"), _row("seqga-unavailable")])
    assert judged["steps"]["seqga-main"]["latest"] == "seqga-main-20261005T120000000000"
    assert judged["steps"]["seqga-main"]["attempts"] == 2
    assert judged["passed"] is True
    assert _judge([retried, _row("seqga-main-20261005T130000000000", {}, status="fail"), _row("seqga-repro"),
                   _row("seqga-unavailable")])["passed"] is False


def test_ga_worker_modeling_child_docking_worker_and_qvina_count_as_leftovers():
    assert {"sequence_ga_worker.py", "sequence_model_worker.py", "docking_worker.py", "qvina2",
            "guardian.py"} <= set(m23.WORKERS)


def test_options():
    parser = m23.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.regressions, args.kbase) == ("auto", None, str(REPO), False, None)
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])  # --root is required
    with pytest.raises(SystemExit):
        parser.parse_args(["--root", "r", "--artifacts", "a", "--build", "sometimes"])


def test_default_out_is_the_m23_qa_folder():
    runner = m23.Runner(_args(out=None))
    assert runner.out.parent.name.startswith("m23-sequence-ga-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(field):
    with pytest.raises(SystemExit, match="/tmp"):
        m23.Runner(_args(**{field: "/tmp/m23-qa"}))
    with pytest.raises(SystemExit, match="/tmp"):
        m23.Runner(_args(**{field: "/private/tmp/m23-qa"}))


def test_repository_runs_folder_and_tracked_artifacts_are_refused():
    with pytest.raises(SystemExit, match="fresh folder"):
        m23.Runner(_args(root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m23.Runner(_args(artifacts=str(REPO / "docs/qa/m23-not-ignored")))


def test_regressions_need_kbase(tmp_path):
    with pytest.raises(SystemExit, match="kbase"):
        m23.Runner(_args(regressions=True))
    with pytest.raises(SystemExit, match="kbase"):
        m23.Runner(_args(regressions=True, kbase=str(tmp_path / "no-kbase")))


def test_regression_chain_is_opt_in_and_uses_fresh_folders(kbase):
    runner = m23.Runner(_args(regressions=True, kbase=kbase))
    commands = dict(runner.regression_commands())
    assert list(commands) == ["m22", "m21", "m20", "m19", "m18", "m17", "m16", "m15", "m14", "m13"]
    for name, argv in commands.items():
        assert argv[1].endswith(f"scripts/{name}_offscreen_acceptance.py")
        assert argv[argv.index("--root") + 1].endswith(f"m23-test-root-{name}-regression")
        assert argv[argv.index("--artifacts") + 1].endswith(f"regressions/{name}")
        assert argv[argv.index("--out") + 1].endswith(f"{name}-regression")
        assert ("--kbase" in argv) == (name in ("m20", "m16", "m15"))
        assert "--regressions" not in argv
    assert "workflows,unavailable,regressions,m11,m12,ledger" in commands["m13"]
    assert m23.Runner(_args()).regressions is False


def test_runner_never_imports_mw():
    tree = ast.parse(Path(m23.__file__).read_text())
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
    oracle = (REPO / m23.ORACLE_FILE).read_text()   # the oracle it loads is standard library only
    assert "import mw" not in oracle and "from mw" not in oracle
