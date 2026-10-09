"""Plan, judgement, ledger and option rules of scripts/m26_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
import json
from pathlib import Path

import pytest

from scripts import m26_offscreen_acceptance as m26

REPO = Path(m26.__file__).resolve().parents[1]
FLOW = REPO / "frontend/tests/offscreen" / m26.FLOW
MUTATION_FLOW = REPO / "frontend/tests/offscreen" / m26.MUTATION_FLOW
GOOD_CHECKS = {
    "fixture": {"reaction": {"empty-at-start": {"status": "pass", "served": {"reason": "not_installed"}},
                             "set-a": {"status": "pass", "setHash": "a" * 64},
                             "unset": {"status": "pass", "served": {"reason": "not_installed"}},
                             "tamper": {"status": "pass", "served": {"reason": "snapshot_invalid"}},
                             "set-b": {"status": "pass", "setHash": "b" * 64}},
                "m15": {"status": "pass", "setHash": "f" * 64}},
    "real": {"reaction": {"copy": {"status": "pass", "setHash": "c" * 64}}, "m15": {"status": "pass", "setHash": "f" * 64}},
}
BUILD = {"buildCurrentWithSource": True}


def _row(step, cases=None, status="pass", external=0, provider=True, hosts=None):
    stage = "fixture" if step.startswith("fixture") else "real"
    if cases is None:
        cases = [case for case, steps in m26.CASE_PLAN[stage].items() if step in steps]
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider, "blockedHosts": hosts or []}


def _rows(stages=m26.STAGES):
    return [_row(step) for stage in stages for step in m26.STEPS[stage]]


def _judge(rows=None, leftovers=(), stages=m26.STAGES, checks=None):
    return m26.assemble(_rows(stages) if rows is None else rows, list(leftovers), list(stages),
                        GOOD_CHECKS if checks is None else checks)


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "ref").mkdir()
    (tmp_path / "ref/manifest.json").write_text("{}")
    return str(tmp_path)


@pytest.fixture
def reaction_set(tmp_path):
    folder = tmp_path / "installed"
    (folder / "sets").mkdir(parents=True)
    (folder / "active.json").write_text('{"schema":"reaction_active@1","set_hash":"' + "c" * 64 + '"}')
    return str(folder)


def _args(kbase, **override):
    values = {"root": str(REPO / "runs/m26-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m26-test-out"), "code_root": str(REPO), "build": "never", "kbase": kbase,
              "stages": ["fixture"], "reaction_set": None}
    return argparse.Namespace(**{**values, **override})


# ---------------------------------------------------------------------------------------------- cases and plans
def test_every_case_has_text_and_covering_steps():
    for stage, plan in m26.CASE_PLAN.items():
        assert plan, stage
        for case, steps in plan.items():
            assert case in m26.CASE_TEXT, case
            assert steps and set(steps) <= set(m26.STEPS[stage]), case
    assert set(m26.FLOW_OF) == {step for steps in m26.STEPS.values() for step in steps}
    assert not set(m26.NOT_OBSERVED["fixture"]) & set(m26.CASE_PLAN["fixture"])
    # spec §12 오프스크린: snapshot states, refusals, matched / conflict / empty, links, report, M20, pickers, tabs
    for case in ("R-no-snapshot", "R-unset", "R-invalid", "R-stale", "R-refusals", "R-matched-row", "R-conflict-derived",
                 "R-pdb-not-in-snapshot", "R-uniprot-link", "R-link-reasons", "R-paging", "R-report", "R-dry-run",
                 "R-no-zero", "R-wording", "R-tabs", "C-uk2-none", "C-preselect", "C-prediction", "C-chains-not-covered",
                 "C-checked", "C-lists", "C-release", "C-exclusion-seven", "C-limitation-variants", "C-picker-marks"):
        assert case in m26.CASE_PLAN["fixture"], case


def _plan_cases(plan):
    cases = {case for link in plan["links"] for case in link["cases"]}
    return cases | set(plan["dryRun"]["link"]["cases"])


@pytest.mark.parametrize("stage", m26.STAGES)
def test_every_planned_case_is_observed_by_a_harness(stage):
    plan = (m26.fixture_plan if stage == "fixture" else m26.real_plan)(REPO, "a" * 64, "run_dry")
    reaction, mutation = FLOW.read_text(), MUTATION_FLOW.read_text()
    for case, steps in m26.CASE_PLAN[stage].items():
        harness = {m26.FLOW_OF[step][0] for step in steps}
        found = case in _plan_cases(plan) or any(f'"{case}"' in (reaction if name == m26.FLOW else mutation)
                                                 for name in harness)
        if stage == "real":  # the harnesses map their built-in fixture ids onto the real ids
            found = found or f'"{case}"' in reaction + mutation or case in ("X-m20", "X-picker-marks")
        assert found, f"{stage}: {case} is observed by no harness step"
    for step in m26.STEPS[stage]:
        script, mode = m26.FLOW_OF[step]
        text = reaction if script == m26.FLOW else mutation
        assert f'"{mode}"' in text, (step, mode)


def test_fixture_plan_names_existing_inputs_and_consistent_references():
    plan = m26.fixture_plan(REPO, "a" * 64, "run_dry")
    assert plan["schema"] == "m26_qa_plan@1" and plan["stage"] == "fixture" and plan["setHash"] == "a" * 64
    assert "SYNTHETIC" in plan["synthetic"]
    for item in [*plan["structures"].values(), plan["mutation"]["structure"]]:
        assert Path(item["file"]).is_file(), item["file"]
        assert item["sha256"] and item["provenance"]
    ids = [link["id"] for link in plan["links"]]
    assert len(ids) == len(set(ids))
    maps = {spec["id"] for spec in plan["maps"]}
    for link in [*plan["links"], plan["dryRun"]["link"]]:
        assert link["structure"] in plan["structures"], link["id"]
        assert link["use"] in ("loaded", "prepared")
        if link["use"] == "prepared":
            assert plan["structures"][link["structure"]]["prepare"], link["id"]
        assert link["map"] is None or link["map"] in maps
        assert ("type" in link["pdbId"]) != ("suggested" in link["pdbId"])
        for chain in link["chains"]:
            assert chain["accession"] is None or len(chain["accession"]) == 1
            if chain["accession"] and "map" in chain["accession"]:
                assert any(spec["structure"] == link["structure"] for spec in plan["maps"]), link["id"]
        assert set(link["expect"]["chains"]) == {chain["chain"] for chain in link["chains"]}, link["id"]
    for key in ("paging", "report"):
        assert plan[key] in ids
    assert plan["uk3"]["link"] in ids and plan["uk3"]["structure"] in plan["structures"]
    assert next(link for link in plan["links"] if link["id"] == plan["refusals"]["case"]).get("refusals") is True
    assert next(link for link in plan["links"] if link["id"] == plan["refusals"]["case"])["map"] is not None
    assert plan["dryRun"]["run"] == "run_dry"
    assert plan["mutation"]["v1Run"] == m26.V1_RUN_ID and (REPO / m26.V1_RUN_EVENTS).is_file()
    assert set(plan["mutation"]["pickers"]) == {"m20", "m21", "m23", "m24", "m25"}
    # the uk3 link is the newest result on its structure (the M20 area pre-selects the newest)
    same = [link["id"] for link in plan["links"] if link["structure"] == plan["uk3"]["structure"]
            and link["use"] == "prepared"]
    assert same[-1] == plan["uk3"]["link"]


@pytest.mark.parametrize("stage", m26.STAGES)
def test_accession_entries_fit_the_numbering_maps(stage):
    """A numbering map on a structure prefills the chain accession: a lookup suggestion ("이 accession 쓰기", the field
    must be empty first) is never planned there, and a map accession is planned only there."""
    plan = (m26.fixture_plan if stage == "fixture" else m26.real_plan)(REPO, "a" * 64, "run_dry")
    mapped = {(spec["structure"], spec["use"], spec["chain"]): spec["accession"] for spec in plan["maps"]}
    for link in [*plan["links"], plan["dryRun"]["link"]]:
        for chain in link["chains"]:
            key = (link["structure"], link["use"], chain["chain"])
            accession = chain["accession"] or {}
            if "suggestion" in accession or chain["accession"] is None:
                assert key not in mapped, (link["id"], chain)
            if "map" in accession:
                assert mapped.get(key) == accession["map"], (link["id"], chain)


def test_fixture_expectations_follow_the_committed_synthetic_rows():
    """The plan's M-CSA expectations name only rows that exist in the committed synthetic files, for that PDB ID and
    chain (an independent read of the JSON, no mw)."""
    fixtures = REPO / "backend/tests/fixtures/reaction"
    rows = []
    for rel in ("t2/mcsa_entries.json", "t6/mcsa_entries_0sy6.json", "t9/mcsa_entries_t9.json"):
        rows += json.loads((fixtures / rel).read_text())
    listed = {(entry["mcsa_id"], index): {(c["pdb_id"], c["chain_name"]) for c in residue["residue_chains"]}
              for entry in rows for index, residue in enumerate(entry["residues"])}
    plan = m26.fixture_plan(REPO, "a" * 64, "run_dry")
    reasons = {"matched": {None}, "unmatched": {"non_standard_code", "no_author_number", "residue_not_in_structure",
                                                "ambiguous_residue_number", "insertion_code_present"},
               "conflict": {"residue_name_differs", "mcsa_rows_disagree"}}
    seen_reasons = set()
    for link in plan["links"]:
        pdb = (link["pdbId"].get("type") or link["pdbId"].get("suggested")).lower()
        for chain, want in link["expect"]["chains"].items():
            for key, state in (want.get("rows") or {}).items():
                mcsa_id, index = (int(part) for part in key.split("/"))
                assert (pdb, chain) in listed[(mcsa_id, index)], (link["id"], chain, key)
                status, _, reason = state.partition(":")
                assert (reason or None) in reasons[status], state
                seen_reasons.add(reason or status)
            for entry in want.get("entries") or []:
                assert any((pdb, chain) in chains for (mcsa_id, _), chains in listed.items() if mcsa_id == entry)
    # every unmatched and conflict reason reachable from the screen is planned
    assert reasons["unmatched"] | reasons["conflict"] <= seen_reasons
    coverages = {want["coverage"] for link in plan["links"] for want in link["expect"]["chains"].values()}
    assert coverages == {"covered", "chain_not_listed", "pdb_not_in_snapshot"}
    two = [want for link in plan["links"] for want in link["expect"]["chains"].values() if len(want.get("entries", [])) == 2]
    assert two, "no chain with two M-CSA entries"
    uniprot = {tuple(want["uniprot"]) for link in plan["links"] for want in link["expect"]["chains"].values()
               if "uniprot" in want}
    assert {("checked", None), ("not_checked", "accession_not_given"), ("not_available", "accession_skipped_at_import"),
            ("not_available", "accession_not_in_snapshot")} <= uniprot
    links = {want.get("link") for link in plan["links"] for want in link["expect"]["chains"].values() if "link" in want}
    assert {None, "numbering_map_not_given", "map_accession_differs"} <= links


def test_derived_structures_differ_from_their_source_by_one_residue_name():
    t9 = REPO / "backend/tests/fixtures/reaction/t9"
    for name, source, chain, number in (("derived_1hsg_A25_asp_to_glu.cif", "public_1hsg.cif", "A", "25"),
                                        ("derived_1s9i_A194_asp_to_glu.cif", "public_1s9i.cif", "A", "194")):
        derived = (t9 / name).read_text().split("\n")
        original = (REPO / "backend/tests/fixtures" / source).read_text().split("\n")
        assert len(derived) == len(original)
        changed = [(a, b) for a, b in zip(original, derived) if a != b]
        assert changed[0][1].startswith(changed[0][0] + "_DERIVED_")
        for before, after in changed[1:]:
            assert before.startswith("ATOM") and before.replace(" ASP ", " GLU ") == after, after
            assert f" {number}  GLU {chain} " in after or f" {number} GLU {chain} " in after, after
        assert len(changed) > 2


def test_real_plan_names_the_public_structures_and_needs_no_synthetic_label():
    plan = m26.real_plan(REPO, "c" * 64, "run_dry")
    assert plan["stage"] == "real" and plan["synthetic"] is None
    names = {item["name"] for item in plan["structures"].values()}
    assert {"public_1s9i.cif", "public_1a30.cif", "public_1a4i.cif", "public_1ubq.cif",
            "derived_1s9i_A194_asp_to_glu.cif"} <= names
    for item in plan["structures"].values():
        assert Path(item["file"]).is_file()
    entries = {link["id"]: link["expect"]["chains"] for link in plan["links"]}
    assert entries["a30"]["A"]["coverage"] == entries["a30"]["B"]["coverage"] == "covered"
    assert entries["a4i"]["A"]["entries"] == [389, 458]
    assert entries["s9i-derived"]["A"]["rowsInclude"] == {"282/A194": "conflict:residue_name_differs"}
    assert entries["ubq"]["A"]["coverage"] == "pdb_not_in_snapshot"


# ---------------------------------------------------------------------------------------------- judgement
def test_all_passing_both_stages_is_acceptance():
    judged = _judge()
    assert judged["passed"] is True and judged["missingStages"] == []
    assert all(value["status"] == "pass" for value in judged["cases"].values())
    assert judged["counts"]["failed"] == 0 and judged["counts"]["cases"] == judged["counts"]["passed"]
    assert m26.acceptance_ok(judged, BUILD) is True


def test_a_missing_stage_is_recorded_and_never_acceptance():
    judged = _judge(rows=_rows(["fixture"]), stages=["fixture"])
    assert judged["passed"] is True
    assert judged["missingStages"] == ["real"]
    assert judged["stages"]["real"]["status"] == "missing" and "real" in judged["stages"]["real"]["reason"]
    assert m26.acceptance_ok(judged, BUILD) is False
    assert not any(case.startswith("X-") for case in judged["cases"])
    judged = _judge(rows=_rows(["real"]), stages=["real"])
    assert judged["missingStages"] == ["fixture"] and m26.acceptance_ok(judged, BUILD) is False


def test_a_stage_requested_but_not_run_fails():
    judged = _judge(rows=_rows(["fixture"]))
    assert judged["stages"]["real"]["status"] == "fail"
    assert judged["passed"] is False
    assert judged["cases"]["X-m20"]["status"] == "fail"


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    main = next(row for row in rows if row["step"] == "fixture-main")
    del main["cases"]["R-refusals"]
    judged = _judge(rows)
    assert judged["cases"]["R-refusals"]["status"] == "fail" and judged["passed"] is False
    rows = _rows()
    mutation = next(row for row in rows if row["step"] == "fixture-mutation")
    mutation["cases"]["R-no-zero"] = "fail"
    assert _judge(rows)["cases"]["R-no-zero"]["status"] == "fail"  # needs both covering steps


@pytest.mark.parametrize("bad", [{"external": None}, {"external": 1}, {"provider": None}, {"provider": False},
                                 {"hosts": ["https://example.org"]}, {"status": "fail"}])
def test_egress_provider_hosts_and_status_fail_the_stage(bad):
    rows = [_row(step, **bad) if step == "fixture-stale" else _row(step) for step in m26.STEPS["fixture"]]
    judged = _judge(rows + _rows(["real"]))
    assert judged["stages"]["fixture"]["status"] == "fail"
    assert judged["passed"] is False
    if "external" in bad or "provider" in bad or "hosts" in bad:
        assert judged["cases"]["S-fixture-no-egress"]["status"] == "fail"


@pytest.mark.parametrize("change", ["empty-at-start", "set-a", "unset", "tamper", "set-b"])
def test_every_fixture_reference_change_must_pass(change):
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["fixture"]["reaction"][change]["status"] = "fail"
    judged = _judge(checks=checks)
    assert judged["cases"]["S-fixture-references"]["status"] == "fail" and judged["passed"] is False


def test_reference_change_details():
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["fixture"]["reaction"]["set-b"]["setHash"] = "a" * 64  # the same set again is not another set
    assert m26.reaction_changes_ok("fixture", checks["fixture"]["reaction"]) is False
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["fixture"]["reaction"]["tamper"]["served"]["reason"] = "not_installed"
    assert m26.reaction_changes_ok("fixture", checks["fixture"]["reaction"]) is False
    assert m26.reaction_changes_ok("real", {"copy": {"status": "pass", "setHash": None}}) is False
    assert m26.reaction_changes_ok("real", {}) is False
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["real"]["m15"] = {"status": "fail"}
    assert _judge(checks=checks)["cases"]["S-real-references"]["status"] == "fail"


def test_leftovers_stale_build_and_latest_attempt():
    judged = _judge(leftovers=["port 8000 still listening: pid 1"])
    assert judged["verdictParts"]["leftoverProcesses"] is False and judged["passed"] is False
    assert m26.acceptance_ok(_judge(), {"buildCurrentWithSource": False}) is False
    assert m26.acceptance_ok(_judge(), None) is False
    failed = _row("fixture-main", status="fail")
    retried = _row("fixture-main-20261009T120000000000",
                   [case for case, steps in m26.CASE_PLAN["fixture"].items() if "fixture-main" in steps])
    rows = [row for row in _rows() if row["step"] != "fixture-main"] + [failed, retried]
    judged = _judge(rows)
    assert judged["stages"]["fixture"]["steps"]["fixture-main"]["attempts"] == 2
    assert judged["passed"] is True


def test_browser_hosts_are_collected_from_rows():
    assert m26.browser_hosts([_row("fixture-main"), _row("real-main", hosts=["https://b.example", "https://a.example"])]) \
        == ["https://a.example", "https://b.example"]
    assert m26.browser_hosts(_rows()) == []


# ---------------------------------------------------------------------------------------------- options and runner
def test_options():
    parser = m26.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.stages, args.reaction_set) == ("auto", None, str(REPO),
                                                                                       ["fixture", "real"], None)
    assert parser.parse_args(["--root", "r", "--artifacts", "a", "--stages", "real,fixture"]).stages == ["fixture", "real"]
    assert parser.parse_args(["--root", "r", "--artifacts", "a", "--stages", "fixture"]).stages == ["fixture"]
    for bad in ("", "both", "fixture,fixture", "fixture,live"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--root", "r", "--artifacts", "a", "--stages", bad])
    with pytest.raises(SystemExit):
        parser.parse_args(["--artifacts", "a"])


def test_real_stage_needs_an_installed_set_outside_the_root(kbase, reaction_set, tmp_path):
    with pytest.raises(SystemExit, match="--reaction-set"):
        m26.Runner(_args(kbase, stages=["fixture", "real"]))
    with pytest.raises(SystemExit, match="active.json"):
        m26.Runner(_args(kbase, stages=["real"], reaction_set=str(tmp_path)))
    runner = m26.Runner(_args(kbase, stages=["fixture", "real"], reaction_set=reaction_set))
    assert runner.reaction_set == Path(reaction_set).resolve()
    inside = REPO / "runs/m26-test-root/installed"
    with pytest.raises(SystemExit, match="inside --root"):
        m26.Runner(_args(kbase, stages=["real"], reaction_set=str(inside), root=str(REPO / "runs/m26-test-root")))


def test_default_out_and_stage_folders(kbase):
    runner = m26.Runner(_args(kbase, out=None))
    assert runner.out.parent.name.startswith("m26-reaction-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"
    runner.use_stage("fixture")
    assert runner.runs == runner.root / "fixture/runs"
    assert runner.reference == runner.root / "fixture/reference"
    assert runner.reaction == runner.root / "fixture/reaction_reference"
    runner.use_stage("real")
    assert runner.reaction == runner.root / "real/reaction_reference"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(kbase, field):
    for bad in ("/tmp/m26-qa", "/private/tmp/m26-qa"):
        with pytest.raises(SystemExit, match="/tmp"):
            m26.Runner(_args(kbase, **{field: bad}))


def test_repository_runs_folder_tracked_artifacts_and_missing_kbase_are_refused(kbase, tmp_path):
    with pytest.raises(SystemExit, match="fresh folder"):
        m26.Runner(_args(kbase, root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m26.Runner(_args(kbase, artifacts=str(REPO / "docs/qa/m26-not-ignored")))
    with pytest.raises(SystemExit, match="manifest"):
        m26.Runner(_args(str(tmp_path / "no-kbase")))


def test_tamper_and_unset_touch_only_the_isolated_folder(kbase, tmp_path):
    runner = m26.Runner(_args(kbase))
    runner.reaction = tmp_path / "reaction_reference"
    set_hash = "d" * 64
    (runner.reaction / "sets" / set_hash / "files/rhea").mkdir(parents=True)
    target = runner.reaction / "sets" / set_hash / m26.TAMPER_FILE
    target.write_bytes(b"{}\n")
    (runner.reaction / "active.json").write_text(json.dumps({"schema": "reaction_active@1", "set_hash": set_hash}))
    assert runner.unset_active()["moved"].startswith("active.json")
    assert not (runner.reaction / "active.json").exists()
    record = runner.tamper_active()
    assert (runner.reaction / "active.json").exists()
    assert record["sha256Before"] != record["sha256After"]
    assert target.read_bytes() == b"{}\n" + m26.TAMPER_BYTES


def test_runner_never_imports_mw_and_never_names_a_limit_route():
    source = Path(m26.__file__).read_text()
    tree = ast.parse(source)
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
    assert "limit_approval" not in source and "raise_limits" not in source
    assert "/jev" not in source


def test_stop_hook_runs_this_test():
    assert '"scripts/test_m26_offscreen_acceptance.py"' in (REPO / ".codex/hooks/stop.py").read_text()
