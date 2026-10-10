"""Plan, judgement, evidence and option rules of scripts/m27_offscreen_acceptance.py (no services run here)."""

import argparse
import ast
import html
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import m27_offscreen_acceptance as m27

REPO = Path(m27.__file__).resolve().parents[1]
FLOW = REPO / "frontend/tests/offscreen" / m27.FLOW
BUILDER = REPO / m27.QA_SET_BUILDER
CONSTANTS = REPO / "backend/mw/precedent_constants.py"
GOOD_IMPORT = {
    "status": "pass", "reproducible": True, "activeIsSecond": True, "defaultFolderUntouched": True,
    "imports": [{"number": n, "exitCode": 0, "networkAttempts": 0, "loaded": [], "setHash": h * 64,
                 "filesMatchManifest": True, "dirty": False,
                 "rows": {"files": dict(m27.REAL_EXPECT["files"]), "bibliography": m27.REAL_EXPECT["bibliographyRows"]},
                 "verification": {"records_hash_verified": dict(m27.REAL_EXPECT["verification"]),
                                  "references_without_hash": 0}} for n, h in ((1, "a"), (2, "b"))],
}
GOOD_CHECKS = {
    "fixture": {"precedent": {"empty-at-start": {"status": "pass", "served": {"reason": "not_installed"}},
                              "set-a": {"status": "pass", "setHash": "a" * 64},
                              "unset": {"status": "pass", "served": {"reason": "not_installed"}},
                              "tamper": {"status": "pass", "served": {"reason": "snapshot_invalid"}},
                              "set-b": {"status": "pass", "setHash": "b" * 64}},
                "m15": {"status": "pass", "setHash": "f" * 64}, "derive": {"status": "pass"}, "import": {}},
    "real": {"precedent": {"imported": {"status": "pass", "setHash": "b" * 64}}, "m15": {"status": "pass", "setHash": "f" * 64},
             "derive": {"status": "pass"}, "import": GOOD_IMPORT},
}
BUILD = {"buildCurrentWithSource": True}


def _row(step, cases=None, status="pass", external=0, provider=True, hosts=None):
    stage = "fixture" if step.startswith("fixture") else "real"
    if cases is None:
        cases = [case for case, steps in m27.CASE_PLAN[stage].items() if step in steps]
    return {"step": step, "status": status, "cases": {case: "pass" for case in cases} if isinstance(cases, list) else cases,
            "externalRequestCount": external, "providerCallsZero": provider, "blockedHosts": hosts or []}


def _rows(stages=m27.STAGES):
    return [_row(step) for stage in stages for step in m27.STEPS[stage]]


def _judge(rows=None, leftovers=(), stages=m27.STAGES, checks=None, leaks=()):
    return m27.assemble(_rows(stages) if rows is None else rows, list(leftovers), list(stages),
                        GOOD_CHECKS if checks is None else checks, list(leaks))


@pytest.fixture
def kbase(tmp_path):
    (tmp_path / "kbase/ref").mkdir(parents=True)
    (tmp_path / "kbase/ref/manifest.json").write_text("{}")
    (tmp_path / "kbase/dist").mkdir()
    (tmp_path / "kbase/dist/manifest.json").write_text("{}")
    return str(tmp_path / "kbase")


@pytest.fixture
def m15_reference(tmp_path):
    folder = tmp_path / "m15"
    (folder / "sets" / ("e" * 64)).mkdir(parents=True)
    (folder / "sets" / ("e" * 64) / "manifest.json").write_text("{}")
    (folder / "active.json").write_text('{"schema":"reference_active@1","set_hash":"' + "e" * 64 + '"}')
    return str(folder)


def _args(kbase, m15_reference, **override):
    values = {"root": str(REPO / "runs/m27-test-root"), "artifacts": str(REPO / "frontend/tests/offscreen/artifacts/x"),
              "out": str(REPO / "runs/m27-test-out"), "code_root": str(REPO), "build": "never", "kbase": kbase,
              "m15_reference": m15_reference, "stages": ["fixture"]}
    return argparse.Namespace(**{**values, **override})


def _load_constants():
    spec = importlib.util.spec_from_file_location("m27_test_precedent_constants", CONSTANTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder_derived() -> dict:
    """``DERIVED`` of build_qa_set.py, evaluated from its source (the builder imports mw; it is not imported here)."""
    tree = ast.parse(BUILDER.read_text())
    names: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Tuple):
            names.update(zip((t.id for t in node.targets[0].elts), ast.literal_eval(node.value)))
    derived = next(node for node in tree.body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "DERIVED")
    return eval(compile(ast.Expression(derived.value), str(BUILDER), "eval"), {"__builtins__": {}}, names)


def _derived(stage: str) -> dict:
    return {"source": "obj://run_x/residue_numbering_map/" + "1" * 64,
            "maps": {name: {"handle": f"obj://run_x/residue_numbering_map/{str(i) * 64}", "chains": chains, "label": "L"}
                     for i, (name, chains) in enumerate(_builder_derived()[stage].items(), start=2)}}


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """The real builder output (``set``) for a synthetic set in a temporary folder."""
    root = tmp_path_factory.mktemp("qa-set")
    proc = subprocess.run([sys.executable, str(BUILDER), "set", "--root", str(root)], capture_output=True, text=True,
                          timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    return {**json.loads(proc.stdout.strip().splitlines()[-1]), "root": str(root)}


# ---------------------------------------------------------------------------------------------- cases and plans
def test_every_case_has_text_and_covering_steps():
    assert set(m27.MODE_OF) == {step for steps in m27.STEPS.values() for step in steps}
    for stage, plan in m27.CASE_PLAN.items():
        assert plan, stage
        for case, steps in plan.items():
            assert case in m27.CASE_TEXT, case
            assert steps and set(steps) <= set(m27.STEPS[stage]), case
    assert set(m27.CASE_TEXT) == {case for plan in m27.CASE_PLAN.values() for case in plan}
    for stage in m27.STAGES:
        assert m27.NOT_OBSERVED[stage]


def _plan_cases(plan: dict) -> set[str]:
    found = {case for link in plan["links"] for case in link["cases"]}
    for key in ("tooLarge", "report"):
        found.update((plan.get(key) or {}).get("cases") or [])
    found.update(((plan.get("dryRun") or {}).get("link") or {}).get("cases") or [])
    return found


def test_every_planned_case_is_observed_by_the_harness_or_its_plan(made):
    harness = FLOW.read_text()
    fixture = m27.fixture_main_plan(m27.fixture_plan(REPO, made, "run_d"), "run_a", {"m1": "h1", "m2": "h2", "m3": "h3"},
                                    _derived("fixture"), "run_d")
    real = m27.real_main_plan(m27.real_plan(REPO, "c" * 64), "run_r", {"rm-mq4": "h", "rm-m17": "h", "rm-fin": "h"},
                              _derived("real"))
    observed = {"fixture": _plan_cases(fixture), "real": _plan_cases(real)}
    for stage, plan in m27.CASE_PLAN.items():
        for case in plan:
            assert f'"{case}"' in harness or case in observed[stage], f"{case} is observed nowhere"


def test_harness_fixed_sentences_are_the_spec_constants_verbatim():
    constants = _load_constants()
    script = ("const h = require(process.argv[1]); console.log(JSON.stringify({kp: h.LIMITATIONS, kt1: h.KT1, up1: h.UP1, "
              "up2: h.UP2('N'), up3: h.UP3, up4: h.UP4, up5: h.UP5('N')}));")
    proc = subprocess.run(["node", "-e", script, str(FLOW)], cwd=REPO / "frontend", capture_output=True, text=True,
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    shown = json.loads(proc.stdout)
    assert shown["kp"] == list(constants.LIMITATIONS)
    assert shown["kt1"] == constants.STATEMENTS["KT1"]
    for key in ("UP1", "UP2", "UP3", "UP4", "UP5"):
        assert shown[key.lower()] == constants.SCREEN_NOTES[key], key


def test_harness_wording_check_and_digest_rules():
    script = ("const h = require(process.argv[1]); console.log(JSON.stringify({"
              "fixed: h.forbiddenIn(h.LIMITATIONS.join('\\n') + '\\n' + h.UP5(396) + '\\n' + h.UP2(0)), "
              "words: h.forbiddenIn('추천 순위 검증됨 성공률 효과 best effect verified'), "
              "stored: h.forbiddenIn('potency selectivity', [{t: 'potency selectivity'}]), "
              "zero: h.bareZeroOrNone('a\\n0\\t없음\\n0개\\n없음 (x)'), min: h.REAL_TEXT_MIN_CHARS, "
              "safe: h.realSafe({n: 3, id: 'MOVE-0001', long: 'x'.repeat(41), at24: 'x'.repeat(24), at23: 'x'.repeat(23), "
              "spaced: 'ab  '.repeat(7), code: 'not_in_kbase_references', "
              "handle: 'obj://run_a/kinase_precedents/' + 'a'.repeat(64)})}));")
    proc = subprocess.run(["node", "-e", script, str(FLOW)], cwd=REPO / "frontend", capture_output=True, text=True,
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["fixed"] == []
    assert sorted(out["words"]) == sorted(["추천", "순위", "검증됨", "성공률", "효과", "best", "effect", "verified"])
    assert out["stored"] == []
    assert out["zero"] == ["0", "없음"]
    # the harness keeps a real-stage string by the runner's leak measure: below REAL_TEXT_MIN_CHARS once whitespace is
    # collapsed (or a handle); 24 characters and up become a digest
    assert out["min"] == m27.REAL_TEXT_MIN_CHARS == 24
    safe = out["safe"]
    assert safe["n"] == 3 and safe["id"] == "MOVE-0001" and safe["handle"].startswith("obj://")
    assert safe["at23"] == "x" * 23 and safe["code"] == "not_in_kbase_references"
    assert safe["spaced"] == "ab  " * 7                      # 27 characters written, 20 once collapsed: kept
    for key in ("long", "at24"):
        assert set(safe[key]) == {"textDigest"}, key


def test_harness_kbase_field_check_compares_each_entry_with_the_stored_record():
    record = {"move_id": "MOVE-0001", "content_hash": "sha256:" + "e" * 64,
              "observation": {"text": "SYNTHETIC", "quote": "SYNTHETIC q", "quote_truncated": False, "evidence": {}},
              "tradeoffs": [{"text": "t", "quote": None, "quote_truncated": False, "evidence": {"p": 1}}],
              "effects": [{"metric": "IC50", "assay_context": "SYNTHETIC context", "chembl_crosscheck": None,
                           "evidence": {"s": "x"}}],
              "extraction": {"model": "m", "dropped_effects": 0}}
    rows = [{"path": p, "dt": p, "value": v} for p, v in (
        ("effects[0].assay_context", '"SYNTHETIC context"'), ("effects[0].chembl_crosscheck", "null"),
        ("effects[0].evidence", '{"s":"x"}'), ("extraction.dropped_effects", "0"), ("observation.evidence", "{}"),
        ("tradeoffs[0].evidence", '{"p":1}'))]
    good = {"open": True, "summary": "그 밖의 kbase 필드(원본 값 그대로)", "rows": rows}
    bad = {
        "closed": {**good, "open": False},
        "zero_for_null": {**good, "rows": [{**rows[1], "value": "0"}, *rows[:1], *rows[2:]]},
        "twice": {**good, "rows": [*rows, rows[0]]},
        "shown_elsewhere": {**good, "rows": [*rows, {"path": "move_id", "dt": "move_id", "value": '"MOVE-0001"'}]},
        "left_out": {**good, "rows": [*rows, {"path": "source.parser", "dt": "source.parser", "value": "null"}]},
        "missing_evidence": {**good, "rows": rows[:2] + rows[3:]},
        "status": {**good, "rows": [*rows, {"path": "checks.schema.status", "dt": "checks.schema.status", "value": '"x"'}]},
    }
    script = ("const h = require(process.argv[1]); const input = JSON.parse(process.argv[2]); const out = {};"
              "for (const [name, block] of Object.entries(input.blocks)) {"
              "  try { out[name] = h.checkKbaseFields(block, input.record); } catch (e) { out[name] = 'refused'; } }"
              "console.log(JSON.stringify(out));")
    payload = json.dumps({"record": record, "blocks": {"good": good, **bad}})
    proc = subprocess.run(["node", "-e", script, str(FLOW), payload], cwd=REPO / "frontend", capture_output=True,
                          text=True, timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out.pop("good") == len(rows)
    assert out == {name: "refused" for name in bad}


def test_harness_markdown_escape_is_the_report_escape():
    sample = "metabolic_stability & <b> [x](y) a.b-c\nd #1 it's *bold* `code` {q} +!|>~\\"
    node = subprocess.run(["node", "-e", "process.stdout.write(require(process.argv[1]).mdEscape(process.argv[2]))",
                           str(FLOW), sample], cwd=REPO / "frontend", capture_output=True, text=True, timeout=60,
                          check=False)
    code = "import sys; sys.path.insert(0, sys.argv[1]); from mw.reports import _md; sys.stdout.write(_md(sys.argv[2]))"
    python = subprocess.run([sys.executable, "-c", code, str(REPO / "backend"), sample], capture_output=True, text=True,
                            timeout=120, check=False)
    assert node.returncode == 0 and python.returncode == 0, node.stderr + python.stderr
    assert node.stdout == python.stdout


def test_target_and_chain_expectations_follow_the_spec_rules():
    counts = {"moves": 2, "moves_flagged": 3, "references": 1}
    assert m27.target_expect(counts, False, ["A"]) == {"status": "precedents_found", "moves": 2, "movesFlagged": None,
                                                       "excluded": 3, "references": 1, "chains": ["A"]}
    assert m27.target_expect(counts, True, ["A"])["movesFlagged"] == 3
    assert m27.target_expect(counts, True, ["A"])["excluded"] is None
    flagged_only = {"moves": 0, "moves_flagged": 4, "references": 1}
    assert m27.target_expect(flagged_only, False, [])["status"] == "none_in_included_files"
    assert m27.target_expect(flagged_only, True, [])["status"] == "precedents_found"
    nothing = {"moves": 0, "moves_flagged": 0, "references": 0}
    assert m27.target_expect(nothing, False, [])["status"] == "not_in_kbase_references"
    assert m27.target_expect(nothing, False, [])["excluded"] == 0   # 0 is an integer, not null
    assert m27.chain_expect(["P0QA01"]) == ["linked", None, "P0QA01"]
    assert m27.chain_expect([]) == ["not_linked", "no_mapped_residues", None]
    assert m27.chain_expect(["A1", "B1"]) == ["not_linked", "multiple_accessions", None]
    same = m27.link_expect({"C": ["P1"], "A": ["P1"]}, {"P1": counts}, False)
    assert list(same["targets"]) == ["P1"] and same["targets"]["P1"]["chains"] == ["A", "C"]
    assert m27.link_expect({"A": []}, {}, False) == {"chains": {"A": ["not_linked", "no_mapped_residues", None]},
                                                     "targets": {}, "nullResult": True}


def test_fixture_plans_follow_the_synthetic_records(made):
    expect = made["expect"]
    assert made["label"].startswith("SYNTHETIC")
    assert expect["accessions"]["P0QA01"]["moves"] == 30 and expect["accessions"]["P0QA01"]["moves_flagged"] == 6
    base = m27.fixture_plan(REPO, made, "run_d")
    assert all(item["sha256"] for item in base["structures"].values())
    assert base["derivedFrom"] == "m3"
    plan = m27.fixture_main_plan(base, "run_a", {"m1": "h1", "m2": "h2", "m3": "h3"}, _derived("fixture"), "run_d")
    links = {link["id"]: link for link in plan["links"]}
    two = links["l-two"]["expect"]
    assert two["chains"] == {"A": ["linked", None, "P0QA01"], "B": ["linked", None, "P0QA02"]}
    assert two["targets"]["P0QA01"]["status"] == "precedents_found" and two["targets"]["P0QA01"]["excluded"] == 6
    assert two["targets"]["P0QA02"]["status"] == "none_in_included_files" and two["targets"]["P0QA02"]["excluded"] == 3
    assert links["l-two-incl"]["expect"]["targets"]["P0QA02"]["status"] == "precedents_found"
    assert links["l-m1"]["expect"]["targets"]["O14965"]["status"] == "not_in_kbase_references"
    assert links["l-m1"]["expect"]["nullResult"] is True
    assert links["l-m2"]["expect"]["chains"]["B"] == ["not_linked", "no_mapped_residues", None]
    assert links["l-m2-a"]["chains"] == ["A"] and list(links["l-m2-a"]["expect"]["chains"]) == ["A"]
    # a link whose only chain is not linked: no target at all, an empty result (the "no linked target" sentence)
    no_target = links["l-m2-b"]
    assert no_target["chains"] == ["B"] and no_target["expect"] == {
        "chains": {"B": ["not_linked", "no_mapped_residues", None]}, "targets": {}, "nullResult": True}
    fusion = links["l-fusion"]["expect"]
    assert fusion["chains"]["A"] == ["not_linked", "multiple_accessions", None]
    assert fusion["targets"]["P0QA03"]["status"] == "not_in_kbase_references"
    statuses = {t["status"] for link in plan["links"] for t in link["expect"]["targets"].values()}
    assert statuses == {"precedents_found", "none_in_included_files", "not_in_kbase_references"}
    chain_states = {tuple(c[:2]) for link in plan["links"] for c in link["expect"]["chains"].values()}
    assert chain_states == {("linked", None), ("not_linked", "no_mapped_residues"), ("not_linked", "multiple_accessions")}
    assert plan["paging"]["total"] == 30   # two record pages at 25
    assert plan["records"]["filters"]["file:moves_flagged"]["total"] == 6
    assert plan["records"]["filters"][f"q:{expect['searchToken']}"]["total"] == 1
    assert plan["unresolvedTotal"] == 4 and plan["unresolvedNamesTotal"] == 3
    assert plan["tooLarge"]["expect"] == {"withoutFlaggedFits": True, "targets": {"P0QA01": True, "P0QA04": False}}
    assert plan["dryRun"]["link"]["expect"]["targets"]["O14965"]["status"] == "not_in_kbase_references"


def test_builder_derived_maps_and_label():
    derived = _builder_derived()
    assert derived["fixture"]["d-fusion"]["A"] == ["P0QA01", "P0QA03"]
    assert derived["real"] == {"d-size": {"A": ["P00533"], "C": ["Q06187"]}}
    text = BUILDER.read_text()
    assert "SYNTHETIC" in text and not BUILDER.name.startswith("test_")
    assert (BUILDER.parent / "SYNTHETIC-PROVENANCE-t8.md").is_file()


def test_real_plans_use_the_t1_counts():
    base = m27.real_plan(REPO, "c" * 64)
    assert all(item["sha256"] for item in base["structures"].values())
    fin = next(spec for spec in base["maps"] if spec["id"] == "rm-fin")
    assert [chain["chain"] for chain in fin["chains"]] == ["A", "C"]   # 1FIN B / D (cyclin A) are never requested
    plan = m27.real_main_plan(base, "run_r", {"rm-mq4": "h", "rm-m17": "h", "rm-fin": "h"}, _derived("real"))
    links = {link["id"]: link["expect"] for link in plan["links"]}
    mq4 = links["l-mq4"]["targets"]["O14965"]
    assert (mq4["status"], mq4["moves"], mq4["movesFlagged"], mq4["excluded"]) == ("none_in_included_files", 0, None, 0)
    m17 = links["l-m17"]["targets"]["P00533"]
    assert (m17["moves"], m17["excluded"], m17["variants"]) == (76, 66, {"L834R": 1, "L858R": 15, "T790M": 4, "WT": 3,
                                                                         "not_reported": 53})
    incl = links["l-m17-incl"]["targets"]["P00533"]
    assert incl["moves"] + incl["movesFlagged"] == 142 and incl["excluded"] is None
    fin_target = links["l-fin"]["targets"]["P24941"]
    assert (fin_target["chains"], fin_target["moves"], fin_target["excluded"]) == (["A", "C"], 32, 24)
    assert list(links["l-fin"]["targets"]) == ["P24941"] and set(links["l-fin"]["chains"]) == {"A", "C"}
    assert links["l-fin-incl"]["targets"]["P24941"]["movesFlagged"] == 24
    assert plan["tooLarge"]["map"] == "d-size" and plan["unresolvedTotal"] == 396
    assert json.dumps(plan, ensure_ascii=False).count("SYNTHETIC") == 0 or plan["synthetic"] is None


# ---------------------------------------------------------------------------------------------- judgement
def test_all_passing_both_stages_is_acceptance():
    judged = _judge()
    assert judged["passed"] and judged["verdictParts"]["bothStages"]
    assert m27.acceptance_ok(judged, BUILD)
    assert not m27.acceptance_ok(judged, {"buildCurrentWithSource": False})
    assert {"S-fixture-no-egress", "S-real-no-egress", "S-fixture-references", "S-real-references",
            "S-real-import"} <= set(judged["cases"])


def test_a_missing_stage_is_recorded_and_never_acceptance():
    judged = _judge(stages=["fixture"])
    assert judged["missingStages"] == ["real"] and judged["stages"]["real"]["status"] == "missing"
    assert judged["passed"] and not m27.acceptance_ok(judged, BUILD)


def test_a_case_missing_or_failed_in_its_row_fails():
    rows = _rows()
    rows[2] = _row("fixture-main", cases={"P-filters": "fail"})
    judged = _judge(rows=rows)
    assert judged["cases"]["P-filters"]["status"] == "fail" and judged["cases"]["P-report"]["status"] == "fail"
    assert not judged["passed"]
    assert not _judge(rows=_rows()[:-1])["passed"]


@pytest.mark.parametrize("bad", [{"external": 1}, {"provider": False}, {"hosts": ["https://x.example"]},
                                 {"status": "fail"}])
def test_egress_provider_hosts_and_status_fail_the_stage(bad):
    rows = [_row(step, **bad) if step == "real-main" else _row(step) for step in m27.STEPS["fixture"] + m27.STEPS["real"]]
    judged = _judge(rows=rows)
    assert judged["stages"]["real"]["status"] == "fail" and not judged["passed"]


def test_real_text_in_the_evidence_fails_the_verdict():
    judged = _judge(leaks=["real-main/precedent-main.jsonl"])
    assert judged["verdictParts"]["noRealTextInEvidence"] is False and not judged["passed"]
    assert not m27.acceptance_ok(judged, BUILD)


@pytest.mark.parametrize("change", ["empty-at-start", "set-a", "unset", "tamper", "set-b"])
def test_every_fixture_precedent_change_must_pass(change):
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["fixture"]["precedent"][change]["status"] = "fail"
    assert _judge(checks=checks)["cases"]["S-fixture-references"]["status"] == "fail"


@pytest.mark.parametrize("part", ["m15", "derive"])
def test_the_m15_copy_and_the_derived_maps_must_pass(part):
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["real"][part]["status"] = "fail"
    assert _judge(checks=checks)["cases"]["S-real-references"]["status"] == "fail"


def test_same_set_hash_twice_fails_the_fixture_references():
    checks = json.loads(json.dumps(GOOD_CHECKS))
    checks["fixture"]["precedent"]["set-b"]["setHash"] = "a" * 64
    assert not m27.precedent_changes_ok("fixture", checks["fixture"]["precedent"])


@pytest.mark.parametrize("mutate", [
    lambda info: info["imports"][0].update(networkAttempts=1),
    lambda info: info["imports"][1].update(loaded=["urllib.request"]),
    lambda info: info["imports"][1].update(exitCode=1),
    lambda info: info["imports"][1].update(setHash="a" * 64),
    lambda info: info.update(reproducible=False),
    lambda info: info.update(activeIsSecond=False),
    lambda info: info["imports"][0].update(dirty=True),
    lambda info: info["imports"][0]["rows"]["files"].update({"dist/moves.jsonl": 890}),
    lambda info: info["imports"][0]["verification"]["records_hash_verified"].update(moves=1),
    lambda info: info["imports"][0].update(filesMatchManifest=False),
    lambda info: info["imports"].pop(),
])
def test_import_rules(mutate):
    info = json.loads(json.dumps(GOOD_IMPORT))
    assert m27.import_ok(info)
    mutate(info)
    assert not m27.import_ok(info)


def test_reproducibility_compares_every_file_hash_and_the_manifest_without_imported_at():
    a = {"fileSha256": {"dist/moves.jsonl": "1", "pubmed/x/documents.jsonl": "2"}, "manifestWithoutImportedAt": "m"}
    assert m27.import_summary(a, dict(a))
    assert not m27.import_summary(a, {**a, "fileSha256": {**a["fileSha256"], "dist/moves.jsonl": "3"}})
    assert not m27.import_summary(a, {**a, "manifestWithoutImportedAt": "other"})
    assert not m27.import_summary({"fileSha256": {}}, {"fileSha256": {}})


def test_browser_hosts_are_collected_from_rows():
    assert m27.browser_hosts([{"blockedHosts": ["https://b"]}, {"blockedHosts": ["https://a", "https://b"]}, {}]) == [
        "https://a", "https://b"]


# ---------------------------------------------------------------------------------------------- evidence rules
def test_real_text_strings_collect_quotes_observations_titles_and_journals(made):
    root = Path(made["root"])
    set_dir = root / "sets" / made["set_hash"]
    strings = m27.real_text_strings(set_dir)
    norm = m27.normalize_text
    assert norm("합성 SYNTHETIC fixture observation 1 of P0QA01.") in strings      # observation text
    assert norm("SYNTHETIC tradeoff quote words") in strings                      # tradeoff quote
    assert norm("합성 SYNTHETIC QA fixture title 91000001") in strings             # bibliography title
    assert norm("Synthetic Fixture Journal") in strings                           # bibliography journal (25)
    assert all(item == norm(item) and len(item) >= m27.REAL_TEXT_MIN_CHARS for item in strings)
    # IDs, short names, reference codes and hashes are not text
    assert not [item for item in strings if item in {"p0qa01", "syn-qa-kinase-1", "syngroup", "synfamily", "partial"}]
    assert not [item for item in strings if item.startswith(("sha256:", "move-"))]


# A LABELLED SYNTHETIC stand-in for real kbase strings (made-up sentences; no kbase record).
SOURCE_LONG = "SYNTHETIC observation: the made-up compound 12a's α-helix contact stayed at 3.1 μM in the fixture assay."
SOURCE_SHORT = "SYNTHETIC assay type XYZ-30 b"        # 29 characters: matched whole only
SOURCE_TINY = "SYNTHETIC 23 characters"               # 23 characters: never a source string


def _md(value: str) -> str:
    code = "import sys; sys.path.insert(0, sys.argv[1]); from mw.reports import _md; sys.stdout.write(_md(sys.argv[2]))"
    proc = subprocess.run([sys.executable, "-c", code, str(REPO / "backend"), value], capture_output=True, text=True,
                          timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_real_text_matcher_finds_pieces_whole_short_strings_and_escaped_or_recased_forms():
    real = m27.RealText([SOURCE_LONG, SOURCE_SHORT, SOURCE_TINY])
    assert len(real) == 2 and m27.normalize_text(SOURCE_TINY) not in real.strings
    piece = SOURCE_LONG[17:57]                                  # a 40-character piece from the middle
    assert len(piece) == m27.REAL_TEXT_FRAGMENT_CHARS
    found = {
        "whole": SOURCE_LONG,
        "piece": f'{{"error": "x {piece} y"}}',
        "piece_upper": f"log: {piece.upper()}",
        "piece_whitespace": "log: " + piece.replace(" ", " \n\t  "),
        "json_ascii": json.dumps({"text": SOURCE_LONG}),          # ensure_ascii: α and μ as \\uXXXX
        "json_twice": json.dumps(json.dumps({"text": SOURCE_LONG})),
        "json_quotes": json.dumps({"t": 'say "' + SOURCE_LONG + '"'}),
        "markdown": f"| row | {_md(SOURCE_LONG)} |",
        "markdown_in_json": json.dumps({"markdown": _md(SOURCE_LONG)}, ensure_ascii=True),
        "html": "<td>" + html.escape(SOURCE_LONG) + "</td>",      # ' as &#x27;
        "short_whole": f"assay={SOURCE_SHORT.lower()};",
        "short_escaped": json.dumps(SOURCE_SHORT),
    }
    assert "\\u03b1" in found["json_ascii"] and "\\." in found["markdown"]
    for name, text in found.items():
        assert m27.contains_any(text, real), name
    passed = {
        "piece_39": SOURCE_LONG[17:56],                        # one character short of a piece
        "short_prefix": SOURCE_SHORT[:-1],                     # a short string is matched only whole
        "tiny": SOURCE_TINY,                                   # below the minimum: never a source string
        "ids_codes_accessions": ("MOVE-0001 PMID 91000001 P00533 Q06187 precedents_found none_in_included_files "
                                 "not_in_kbase_references kbase_record_minus_2_paths@1 moves_flagged multiple_accessions "
                                 "obj://run_a/kinase_precedents/" + "a" * 64 + " sha256:" + "b" * 64),
        "hashes_only": json.dumps({"textDigest": {"chars": 104, "sha256": "c" * 64}}),
    }
    for name, text in passed.items():
        assert not m27.contains_any(text, real), name
    # an empty matcher finds nothing (fixture-only runs)
    assert not m27.contains_any(SOURCE_LONG, m27.RealText())


def test_real_text_matcher_identifiers_and_codes_inside_source_text_still_pass():
    # the source sentence mentions identifiers and a closed code; evidence carrying only those passes
    real = m27.RealText(["SYNTHETIC: P00533 and MOVE-0001 were recorded as precedents_found by a made-up rule."])
    assert not m27.contains_any('{"accession": "P00533", "move": "MOVE-0001", "status": "precedents_found"}', real)
    assert m27.contains_any("…P00533 and MOVE-0001 were recorded as precedents_found…", real)


def test_hold_reasons(tmp_path):
    files = {"real-main/downloads/r.md": "report", "real-main/L-x-failure.panel.html": "<td>x</td>",
             "real-main/big.json": "x" * (m27.MAX_TEXT_BYTES + 1), "real-main/ledger-row.json": "y" * (m27.MAX_TEXT_BYTES + 1),
             "real-main/precedent-main.jsonl": '{"text": "a real observation sentence here"}\n',
             "fixture-main/precedent-main.jsonl": '{"ok": true}\n', "real-main/notes.panel.html": "<p>plain</p>"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    strings = m27.RealText({"a real observation sentence here"})
    reasons = {rel: m27.hold_reason(tmp_path, tmp_path / rel, strings) for rel in files}
    assert reasons == {"real-main/downloads/r.md": "download", "real-main/L-x-failure.panel.html": "failure_panel",
                       "real-main/big.json": "over_256KiB", "real-main/ledger-row.json": None,
                       "real-main/precedent-main.jsonl": "real_kbase_text", "fixture-main/precedent-main.jsonl": None,
                       "real-main/notes.panel.html": None}


def test_the_import_child_refuses_and_counts_sockets(tmp_path):
    connects = tmp_path / "connects.py"
    connects.write_text("import socket\ntry:\n    socket.create_connection(('127.0.0.1', 9))\nexcept OSError:\n    pass\n")
    quiet = tmp_path / "quiet.py"
    quiet.write_text("print('local only')\n")
    for script, attempts in ((connects, 1), (quiet, 0)):
        proc = subprocess.run([sys.executable, "-I", "-c", m27.NETWORK_GUARD, str(script)], capture_output=True,
                              text=True, timeout=60, check=False)
        assert proc.returncode == 0, proc.stderr
        line = next(item for item in proc.stdout.splitlines() if item.startswith("QA-NETWORK "))
        assert json.loads(line[len("QA-NETWORK "):]) == {"attempts": attempts, "loaded": []}


def test_runner_export_holds_real_text_downloads_and_large_files(kbase, m15_reference, tmp_path):
    runner = m27.Runner(_args(kbase, m15_reference))
    runner.artifacts = tmp_path / "artifacts"
    runner.out = tmp_path / "out"
    runner.real_strings = m27.RealText({"a real observation sentence here"})
    files = {"real-main/downloads/r.md": "a real observation sentence here",
             "real-main/precedent-main.jsonl": '{"ok": true}\n', "real-main/x.page.png": "png",
             "real-main/leak.log": "error: A REAL OBSERVATION\nsentence here"}
    for rel, text in files.items():
        (runner.artifacts / rel).parent.mkdir(parents=True, exist_ok=True)
        (runner.artifacts / rel).write_text(text)
    ledger = {"generatedAt": "t", "acceptance": False, "verdict": "fail", "counts": {"cases": 0, "passed": 0, "failed": 0},
              "stagesRequested": ["real"], "missingStages": ["fixture"], "stages": {
                  "fixture": {"status": "missing", "reason": "r"}, "real": {"status": "missing", "reason": "r"}},
              "verdictParts": {}, "browserHostsContacted": [], "externalRequestsTotal": 0, "checks": {},
              "realTextLeaks": ["real-main/leak.log"], "realTextStringsChecked": 1, "leftoverProcesses": [], "build": None,
              "cases": {}, "syntheticNote": None}
    runner.export(ledger)
    exported = sorted(str(p.relative_to(runner.out)) for p in runner.out.rglob("*") if p.is_file())
    assert "evidence/real-main/precedent-main.jsonl" in exported
    assert not [rel for rel in exported if "leak.log" in rel or "downloads" in rel or rel.endswith(".png")]
    binary = json.loads((runner.out / "binary-artifacts.json").read_text())
    assert {item["path"]: item["held"] for item in binary["heldText"]} == {"real-main/downloads/r.md": "download",
                                                                          "real-main/leak.log": "real_kbase_text"}
    assert [item["path"] for item in binary["files"]] == ["real-main/x.page.png"]
    assert all(len(item["sha256"]) == 64 for item in binary["files"] + binary["heldText"])
    for name in ("README.md", "summary.json", "cases.json", "SHA256SUMS"):
        assert (runner.out / name).is_file()
        assert "a real observation sentence here" not in (runner.out / name).read_text()
    assert runner.summary[-1]["step"] == "export-evidence" and runner.summary[-1]["status"] == "fail"


# ---------------------------------------------------------------------------------------------- options
def test_options():
    parser = m27.build_parser()
    args = parser.parse_args(["--root", "runs/r", "--artifacts", "frontend/tests/offscreen/artifacts/a"])
    assert (args.build, args.out, args.code_root, args.stages, args.m15_reference) == (
        "auto", None, str(REPO), ["fixture", "real"], ".deps/reference")
    assert args.kbase == str(REPO.parent / "kbase_kinase")
    assert parser.parse_args(["--root", "r", "--artifacts", "a", "--stages", "real,fixture"]).stages == ["fixture", "real"]
    for bad in ("", "both", "fixture,fixture", "fixture,live"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--root", "r", "--artifacts", "a", "--stages", bad])


def test_default_out_and_stage_folders(kbase, m15_reference):
    runner = m27.Runner(_args(kbase, m15_reference, out=None))
    assert runner.out.parent.name.startswith("m27-precedents-") and runner.out.name == "acceptance"
    assert runner.out.parent.parent == REPO / "docs/qa"
    runner.use_stage("fixture")
    assert (runner.runs, runner.reference, runner.precedent, runner.reaction) == (
        runner.root / "fixture/runs", runner.root / "fixture/reference", runner.root / "fixture/precedent_reference",
        runner.root / "fixture/reaction_reference")
    env = runner.backend_env()
    assert env["MW_PRECEDENT_REFERENCE_DIR"] == str(runner.precedent) and env["MW_REFERENCE_DIR"] == str(runner.reference)
    assert env["MW_REACTION_REFERENCE_DIR"] == str(runner.reaction) and env["MW_RUNS_DIR"] == str(runner.runs)
    assert not any(key.startswith("OPENROUTER") for key in env)
    runner.use_stage("real")
    assert runner.precedent == runner.root / "real/precedent_reference"


@pytest.mark.parametrize("field", ["root", "artifacts", "out"])
def test_tmp_paths_are_refused(kbase, m15_reference, field):
    for bad in ("/tmp/m27-qa", "/private/tmp/m27-qa"):
        with pytest.raises(SystemExit, match="/tmp"):
            m27.Runner(_args(kbase, m15_reference, **{field: bad}))


def test_inputs_are_checked(kbase, m15_reference, tmp_path):
    with pytest.raises(SystemExit, match="fresh folder"):
        m27.Runner(_args(kbase, m15_reference, root=str(REPO / "runs")))
    with pytest.raises(SystemExit, match="git-ignored"):
        m27.Runner(_args(kbase, m15_reference, artifacts=str(REPO / "docs/qa/m27-not-ignored")))
    with pytest.raises(SystemExit, match="m15-reference"):
        m27.Runner(_args(kbase, str(tmp_path / "no-m15")))
    with pytest.raises(SystemExit, match="inside --root"):
        m27.Runner(_args(kbase, str(REPO / "runs/m27-test-root/m15"), root=str(REPO / "runs/m27-test-root")))
    no_dist = tmp_path / "no-dist"
    (no_dist / "ref").mkdir(parents=True)
    (no_dist / "ref/manifest.json").write_text("{}")
    m27.Runner(_args(str(no_dist), m15_reference, stages=["fixture"]))
    with pytest.raises(SystemExit, match="dist/manifest.json"):
        m27.Runner(_args(str(no_dist), m15_reference, stages=["real"]))


def test_m15_copy_is_read_only_and_leaves_the_source(kbase, m15_reference, tmp_path):
    runner = m27.Runner(_args(kbase, m15_reference))
    runner.stage = "fixture"
    runner.reference = tmp_path / "copy"
    entry = runner.m15_copy()
    assert entry["status"] == "pass" and entry["setHash"] == "e" * 64 and entry["files"] == 2
    copied = runner.reference / "active.json"
    assert copied.read_text() == Path(m15_reference, "active.json").read_text()
    assert not copied.stat().st_mode & 0o222


def test_tamper_and_unset_touch_only_the_isolated_folder(kbase, m15_reference, tmp_path):
    runner = m27.Runner(_args(kbase, m15_reference))
    runner.precedent = tmp_path / "precedent_reference"
    set_hash = "d" * 64
    target = runner.precedent / "sets" / set_hash / m27.TAMPER_FILE
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}\n")
    (runner.precedent / "active.json").write_text(json.dumps({"schema": "precedent_active@1", "set_hash": set_hash}))
    assert runner.unset_active()["moved"].startswith("active.json")
    assert not (runner.precedent / "active.json").exists()
    record = runner.tamper_active()
    assert (runner.precedent / "active.json").exists() and record["sha256Before"] != record["sha256After"]
    assert target.read_bytes() == b"{}\n" + m27.TAMPER_BYTES


def test_runner_never_imports_mw_never_names_a_limit_route_and_never_writes_the_default_folder():
    source = Path(m27.__file__).read_text()
    tree = ast.parse(source)
    names = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    names += [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not [name for name in names if name == "mw" or name.startswith("mw.")]
    assert "limit_approval" not in source and "raise_limits" not in source and "/jev" not in source
    assert '"--dest", str(self.precedent)' in source            # the importer always gets the isolated folder
    assert source.count('".deps" / "precedent_reference"') == 2  # existence checks only


def test_stop_hook_runs_this_test():
    assert '"scripts/test_m27_offscreen_acceptance.py"' in (REPO / ".codex/hooks/stop.py").read_text()
