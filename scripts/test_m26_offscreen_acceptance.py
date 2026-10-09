"""Plan, judgement, ledger and option rules of scripts/m26_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
import json
import subprocess
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
        if stage == "real":  # every covering harness maps its built-in fixture ids onto the real id (REAL_CASE / K)
            found = found or all(f'"{case}"' in (reaction if name == m26.FLOW else mutation) for name in harness)
        assert found, f"{stage}: {case} is observed by no harness step"
    for step in m26.STEPS[stage]:
        script, mode = m26.FLOW_OF[step]
        text = reaction if script == m26.FLOW else mutation
        assert f'"{mode}"' in text, (step, mode)


def test_real_m20_cases_are_the_catalytic_steps_mapped_by_the_harness():
    """X-m20 and X-picker-marks are not named in the real plan: the catalytic mode's K() maps its C- case ids onto them.
    Each must be reached by real-stage steps of that mode (no vacuous pass): the mapping is in the harness, the C- cases
    it maps are each observed by a step that runs without the v1 run (the real plan has none), and the pickers run."""
    mutation = MUTATION_FLOW.read_text()
    assert 'id === "C-picker-marks" ? "X-picker-marks" : id.startsWith("C-") ? "X-m20"' in mutation
    real = m26.real_plan(REPO, "a" * 64, "run_dry")["mutation"]
    assert real["v1Run"] is None and set(real["pickers"]) == {"m20", "m21", "m23", "m24", "m25"}
    v1_only = {"C-v1-set", "C-limitation-variants"}   # step K11 runs only with a stored v1 run
    mapped = {case for case in m26.CASE_PLAN["fixture"] if case.startswith("C-")} - v1_only
    for case in mapped:
        assert f'K("{case}")' in mutation, case
    # X-m20's text names what those steps observe; X-picker-marks the five pickers (K12–K16)
    for step in ("K03-uk2-none", "K06-preselect", "K07-prediction", "K08-set-partial", "K09-set-all", "K10-release",
                 "K10c-derived-set", "K12-m20-list", "K13-m21", "K14-m23", "K15-m25", "K16-m24"):
        assert f'"{step}"' in mutation, step
    for step in ("K12-m20-list", "K13-m21", "K14-m23", "K15-m25", "K16-m24"):
        call = mutation[mutation.index(f'"{step}"'):]
        assert call[:200].count('K("C-picker-marks")') == 1, step
    assert {"X-m20", "X-picker-marks"} <= set(m26.CASE_PLAN["real"]) and not {"X-m20", "X-picker-marks"} & set(
        m26.NOT_OBSERVED["real"])


def _node(script, *args):
    done = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True, check=True, cwd=REPO / "frontend")
    return json.loads(done.stdout)


REACTION_PROBES = ["효과", "변이 효과가 있다", "side effect", "effects", "중요 잔기", "핵심", "필수", "important", "critical",
                   "촉매 잔기 · 반응 · 효소", "효소 반응 지식 (M-CSA 원문, 계산 아님)"]


def test_reaction_harness_wording_covers_effect_and_keeps_its_exemptions():
    """spec §2 / §7: 효과 and effect are refused by the reaction harness; the fixed RK / UK sentences and quoted stored
    reference strings (even ones saying "effect") stay exempt, as designed."""
    script = (f"const f=require({json.dumps(str(FLOW))});const p=JSON.parse(process.argv[1]);"
              "const ref={rows:[{reference:{roles_summary:'electrostatic effect on the substrate'}}]};"
              "console.log(JSON.stringify({probes:p.map(t=>f.forbiddenIn(t)),"
              "quoted:f.forbiddenIn('역할 원문: electrostatic effect on the substrate',[ref]),"
              "unquoted:f.forbiddenIn('역할 원문: electrostatic effect on the substrate')}))")
    out = _node(script, json.dumps(REACTION_PROBES))
    assert out["probes"][:9] == [["효과"], ["효과"], ["effect"], ["effect"], ["중요"], ["핵심"], ["필수"], ["important"],
                                 ["critical"]]
    assert out["probes"][9:] == [[], []]   # 효소 / 촉매 / the reference column label are not interpretive
    assert out["quoted"] == [] and out["unquoted"] == ["effect"]
    fixed = _node(f"const f=require({json.dumps(str(FLOW))});console.log(JSON.stringify({{fixed:f.FIXED,"
                  "found:f.FIXED.map(s=>f.forbiddenIn(s)),own:f.FIXED.filter(s=>/효과|effect/i.test(s))}))")
    assert len(fixed["fixed"]) == 10 and fixed["found"] == [[]] * 10
    assert fixed["own"] == []   # RK1–RK6 / UK1–UK4 never say 효과: the new words do not lean on the exemption


def test_m20_catalytic_wording_and_counts_line_expectations():
    """The catalytic mode refuses 중요·핵심·필수·효과 (the main M20 mode's pattern is unchanged); limitation sentence 2
    (it says 효과) is outside the check as the panel wording removes the limitation block. The counts-line expectation:
    catalytic_residue is — with the reason when no chain was covered, the number otherwise (partly: covered chains)."""
    script = (f"const f=require({json.dumps(str(MUTATION_FLOW))});"
              "const not_given={status:'not_checked',reason:'annotation_not_given',annotation:null};"
              "const none={status:'not_checked',reason:'chains_not_covered',annotation:'h',covered_chains:[],"
              "uncovered_chains:[{chain_auth:'A',coverage:'pdb_not_in_snapshot'}]};"
              "const part={...none,covered_chains:['A'],uncovered_chains:[{chain_auth:'B',coverage:'not_in_annotation'}]};"
              "const all={...none,status:'checked',reason:null,covered_chains:['A','B'],uncovered_chains:[]};"
              "console.log(JSON.stringify({catalytic:['중요','핵심','필수','효과','effect','순위'].map(w=>f.forbiddenIn(w,"
              "f.FORBIDDEN_CATALYTIC)),main:f.forbiddenIn('중요 핵심 필수 효과'),limit2:f.forbiddenIn(f.LIMITATIONS[1],"
              "f.FORBIDDEN_CATALYTIC),uk2:f.forbiddenIn(f.UK2,f.FORBIDDEN_CATALYTIC),"
              "variants:Object.values(f.LIMIT3).map(s=>f.forbiddenIn(s,f.FORBIDDEN_CATALYTIC)),"
              "counts:[not_given,none,part,all].map(c=>f.reasonCountText('catalytic_residue',0,c)),"
              "metal:f.reasonCountText('metal_contact',0,not_given)}))")
    out = _node(script)
    assert out["catalytic"] == [["중요"], ["핵심"], ["필수"], ["효과"], ["effect"], ["순위"]]
    assert out["main"] == []
    assert "효과" in out["limit2"] and out["uk2"] == []   # sentence 2 is fixed text, exempt by removal, not by pattern
    assert out["variants"][:2] == [[], []]
    assert out["counts"] == ["M-CSA 촉매 잔기 주석 — (효소 반응 지식 결과를 고르지 않음 (annotation_not_given), 세지 않음)",
                             "M-CSA 촉매 잔기 주석 — (M-CSA가 다룬 체인 없음, 세지 않음)",
                             "M-CSA 촉매 잔기 주석 0개 (검사한 체인 A만)", "M-CSA 촉매 잔기 주석 0개"]
    assert out["metal"] == "금속 근접 0개"
    panel = mutation_panel_wording()
    assert "[data-testid=\"mutation-limitations\"]" in panel   # the limitation block is removed before the check


def test_harness_steps_return_digests_of_report_and_tab_text_never_the_text():
    """A step's return value is kept in the jsonl (actionResult, up to 6000 characters, on a failed check): the library
    report Markdown (M14-library, Q02-listed) and the tab text (M04 / M16) leave their actions as length + SHA-256."""
    import hashlib
    import re

    for path in (FLOW, MUTATION_FLOW):
        source = path.read_text()
        assert not re.findall(r"text: await (?:pre|panel)\.(?:textContent|innerText)\(\)", source), path.name
        assert "...textDigest(" in source, path.name
    reaction = FLOW.read_text()
    signature = reaction[reaction.index("async function tabSignature"):reaction.index("// ---", reaction.index(
        "async function tabSignature"))]
    assert "textSha256: digest.sha256, chars: digest.chars }" in signature and ", text }" not in signature
    out = _node(f"const f=require({json.dumps(str(FLOW))});console.log(JSON.stringify(f.textDigest('촉매 abc')))")
    assert out == {"chars": len("촉매 abc"), "sha256": hashlib.sha256("촉매 abc".encode()).hexdigest()}


def mutation_panel_wording():
    source = MUTATION_FLOW.read_text()
    return source[source.index("async function panelWording"):source.index("function forbiddenIn")]


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
    # spec §12: 1HSG / 1MQ4 / 1UBQ not in the snapshot, both real M15 maps (1S9I and 1MQ4) link UniProt sites
    assert {entries[key]["A"]["coverage"] for key in ("hsg", "mq4-linked")} == {"pdb_not_in_snapshot"}
    assert {spec["pdbId"] for spec in plan["maps"]} == {"1S9I", "1MQ4"}
    assert all(entries[key]["A"]["link"] is None for key in ("s9i-linked", "mq4-linked"))
    # the M20 flow: a structure whose two chains are covered, so the all-chains result gives a checked set and the
    # chain-A result chains_not_covered; then the labelled derived 1S9I gives a checked set with a conflict row
    mutation = plan["mutation"]
    assert mutation["structure"]["name"] == "public_1a30.cif" and mutation["expect"]["allUncovered"] == []
    assert mutation["expect"]["partialUncovered"] == [{"chain_auth": "B", "coverage": "not_in_annotation"}]
    assert {residue["chain"] for residue in mutation["positions"]["residues"]} == set(mutation["chainsAll"])
    derived = mutation["derived"]
    assert "SYNTHETIC" in derived["structure"]["provenance"] and derived["expect"]["status"] == "checked"
    assert derived["expect"]["conflicts"] == [["A", 282, 0]]
    assert "SYNTHETIC" in plan["structures"]["s9i_derived"]["provenance"]


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


def test_report_downloads_are_held_out_of_the_text_evidence_and_restored(tmp_path):
    (tmp_path / "real-main" / "downloads").mkdir(parents=True)
    report = tmp_path / "real-main" / "downloads" / "r.md"
    report.write_text("quoted third-party text")
    other = tmp_path / "real-main" / "ledger.json"
    other.write_text("{}")
    with m26.held_downloads(tmp_path) as held:
        assert not report.exists() and (report.parent / "r.md.held").is_file()
        assert other.is_file()
        assert [target.name for target, _ in held] == ["r.md.held"]
    assert report.read_text() == "quoted third-party text" and not (report.parent / "r.md.held").exists()


def test_failure_panel_html_is_held_too_in_every_stage(tmp_path):
    """A failed step saves the panel HTML (it can quote M-CSA role text, UniProt descriptions, Rhea equations)."""
    files = {"real-main/L-s9i-failure.panel.html": "<td>role text</td>",
             "fixture-mutation/K09-set-all-failure.panel.html": "<td>x</td>",
             "real-mutation/downloads/report.md": "quoted",
             "real-main/reaction-main.jsonl": "{}\n", "real-main/K01-new-run.png": "png",
             "real-main/notes.panel.html": "<p>not a failure panel</p>"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    with m26.held_downloads(tmp_path) as held:
        assert sorted(str(path.relative_to(tmp_path)) for _, path in held) == [
            "fixture-mutation/K09-set-all-failure.panel.html", "real-main/L-s9i-failure.panel.html",
            "real-mutation/downloads/report.md"]
        texts = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file()
                       and p.suffix in m26.TEXT_SUFFIXES)
        assert texts == ["real-main/notes.panel.html", "real-main/reaction-main.jsonl"]   # what the export copies as text
    for rel, text in files.items():
        assert (tmp_path / rel).read_text() == text
    assert not list(tmp_path.rglob("*.held"))


def test_runner_export_holds_failure_panels_and_downloads(kbase, tmp_path, monkeypatch):
    runner = m26.Runner(_args(kbase))
    runner.artifacts = tmp_path / "artifacts"
    (runner.artifacts / "real-main" / "downloads").mkdir(parents=True)
    (runner.artifacts / "real-main" / "downloads" / "r.md").write_text("quoted")
    (runner.artifacts / "real-main" / "M14-library-failure.panel.html").write_text("<pre>report</pre>")
    seen = {}

    def export(self, ledger):
        seen["text"] = sorted(p.name for p in self.artifacts.rglob("*") if p.suffix in m26.TEXT_SUFFIXES)
        seen["held"] = sorted(p.name for p in self.artifacts.rglob("*.held"))

    monkeypatch.setattr(m26.m15.Runner, "export", export)
    runner.export({})
    assert seen == {"text": [], "held": ["M14-library-failure.panel.html.held", "r.md.held"]}
    assert (runner.artifacts / "real-main" / "M14-library-failure.panel.html").read_text() == "<pre>report</pre>"


def test_held_downloads_restores_even_when_the_export_fails(tmp_path):
    (tmp_path / "downloads").mkdir()
    report = tmp_path / "downloads" / "r.json"
    report.write_text("{}")
    with pytest.raises(RuntimeError), m26.held_downloads(tmp_path):
        raise RuntimeError("export failed")
    assert report.is_file() and not (tmp_path / "downloads" / "r.json.held").exists()
