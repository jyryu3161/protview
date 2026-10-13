"""Unit tests of the M29 acceptance runner, its oracle and its case judgement (no service, no Electron, no network).

The oracle is checked against the documents it must reproduce (``docs/qa/m29-repair-20261013/preflight.md`` (a) and
``t3b-classification.tsv``) and the input files; the judgement against the rules of spec 10.3 (not_observed and fail
never count as pass, a case that did not run is not_observed); the loopback helper against the forbidden routes; the
evidence helpers against leaks; and the runner's argument checks.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import m29_api_cases as cases
import m29_common as c
import m29_oracle as oracle

FIX = REPO / "backend/tests/fixtures"
QA = REPO / "docs/qa/m29-repair-20261013"
MODULES = ("m29_common.py", "m29_oracle.py", "m29_api_cases.py", "m29_offscreen_acceptance.py")


@pytest.fixture(scope="module")
def tpl():
    return oracle.templates()


# ---------------------------------------------------------------------------------------------------- independence
def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("name", MODULES)
def test_runner_modules_never_import_the_product_or_an_engine(name):
    found = _imports(SCRIPTS / name)
    assert not found & {"mw", "openmm", "pdbfixer", "httpx", "requests", "socket"}, found


def test_only_the_exporter_imports_mw_and_only_the_constants_module():
    tree = ast.parse((SCRIPTS / "m29_export_fixed_sentences.py").read_text())
    mods = [(node.module, [alias.name for alias in node.names]) for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mw")]
    assert mods == [("mw", ["structure_repair_constants"])]


def test_the_oracle_reads_the_template_as_a_file_without_importing_openmm():
    text = (SCRIPTS / "m29_oracle.py").read_text()
    assert "find_spec(\"openmm\")" in text and "import openmm" not in text
    assert oracle.template_path().name == "protein.ff14SB.xml"


def test_no_limit_raising_or_jev_write_route_is_named_outside_the_refusal_list():
    for name in MODULES:
        text = (SCRIPTS / name).read_text()
        for word in ("raise_limits", "limit_approval", "jev/sends", "jev_loops/"):
            if name == "m29_common.py" and word in ("raise_limits", "limit_approval"):
                continue
            assert word not in text, (name, word)
    harness = (REPO / "frontend/tests/offscreen/structure-repair-flow.cjs").read_text()
    assert '"jev-send"' not in harness and "jev-confirm\").check" not in harness
    assert "page.request.post" not in harness and "fetch(" not in harness


# ---------------------------------------------------------------------------------------------------- documents
def _preflight_table() -> dict[str, dict[str, str]]:
    names = {"8VF6": "8vf6", "1M17": "1m17", "1MQ4": "1mq4", "1A30": "1a30", "1A4I": "1a4i", "1HSG": "1hsg",
             "1S9I": "1s9i", "1FIN": "1fin", "1UBQ": "1ubq"}
    text = (QA / "preflight.md").read_text().split("## (a) 독립 분류", 1)[1].split("## (b)", 1)[0]
    out: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] not in names:
            continue
        verdict = cells[2].split(" ")[0].strip("`")
        policies = c.WATERS if cells[1] == "둘 다" else (cells[1],)
        for policy in policies:
            out.setdefault(names[cells[0]], {})[policy] = verdict
    for line in (QA / "t3b-classification.tsv").read_text().splitlines():
        if line.startswith(("#", "file")):
            continue
        cells = line.split("\t")
        out.setdefault(cells[0][len("public_"):-len(".cif")], {})[cells[1]] = cells[2]
    return out


def test_the_expected_table_is_the_documented_table():
    documented = _preflight_table()
    assert set(documented) == set(c.STRUCTURES) == set(c.EXPECTED_TABLE)
    assert documented == c.EXPECTED_TABLE


@pytest.mark.parametrize("name", c.STRUCTURES)
def test_the_oracle_reproduces_the_documented_classification(name, tpl):
    raw = (FIX / f"public_{name}.cif").read_bytes()
    for policy in c.WATERS:
        assert oracle.classify(raw, policy, tpl)["verdict"] == c.EXPECTED_TABLE[name][policy], (name, policy)


def test_the_oracle_8vf6_matches_the_t1_measurement(tpl):
    row = oracle.classify((FIX / "public_8vf6.cif").read_bytes(), "strip_all", tpl)
    assert len(row["side_chain"]) == 23 and row["side_chain_atoms"] == 91
    assert row["gap_lengths"] == [13, 11] and len(row["terminal_oxt"]) == 2
    assert row["expected_added_residues"] == 24 and row["expected_added_heavy_atoms"] == 266
    assert row["protein_heavy_after"] == 4538
    gap = row["gaps"][0]["residues"]
    assert all(set(item) == set(oracle.FIELDS) for item in gap)          # every identity comes from the file's listing


def test_the_oracle_finds_the_three_mse_of_1rnh_and_the_synthetic_codes(tpl):
    row = oracle.classify((FIX / "public_1rnh.cif").read_bytes(), "strip_all", tpl)
    assert [oracle.short(item["ref"]) for item in row["nonstandard"]] == ["A/47/MSE", "A/50/MSE", "A/142/MSE"]
    for code, filename in cases.SYNTHETIC.items():
        found = oracle.classify((FIX / "structure_repair" / filename).read_bytes(), "strip_all", tpl)
        assert found["code"] == code, filename
        assert "SYNTHETIC" in (FIX / "structure_repair/synthetic-fixtures.provenance.json").read_text()


def test_m21_bands_are_the_measured_table_or_the_rule():
    assert c.band_for("8vf6", 4538)["band"] == "exceeds" and c.band_for("8vf6", 1)["source"] == c.BAND_SOURCE_MEASURED
    assert c.band_for("1mq4", None)["band"] == "near_limit"
    assert c.band_for("1hsg", None)["band"] == "completes"
    assert c.band_for("1rnh", 1207) == {"band": "completes", "heavyAtoms": 1207, "seconds": None,
                                        "source": c.BAND_SOURCE_RULE}
    assert c.band_for("4ins", 2600)["band"] == "exceeds"


def test_repair_problems_sees_an_observed_atom_that_moved(tpl):
    raw = (FIX / "public_1ubq.cif").read_bytes()
    row = oracle.classify(raw, "strip_all", tpl)
    _st, text = oracle.prepared_view(raw, "strip_all")
    same = oracle.repair_problems(row, text.encode(), text.encode(), tpl)
    assert same["problems"] == [] and same["newAtoms"] == 0 and same["inputAtoms"] > 600
    lines = text.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("ATOM"))
    fields = lines[index].split()
    moved_x = f"{float(fields[10]) + 0.001:.3f}"
    lines[index] = lines[index].replace(fields[10], moved_x, 1)
    moved = oracle.repair_problems(row, text.encode(), "\n".join(lines).encode(), tpl)
    assert any("moved" in problem for problem in moved["problems"])


# ---------------------------------------------------------------------------------------------------- judgement
def test_a_case_passes_only_when_every_part_passes():
    assert c.case_record("R1", [c.part("a", "pass")])["status"] == "pass"
    failed = c.case_record("R1", [c.part("a", "pass"), c.part("b", "fail", "x")])
    assert failed["status"] == "fail" and failed["reason"] == "b: x"
    unobserved = c.case_record("R2", [c.part("a", "pass"), c.part("b", "not_observed", "prerequisite_failed:R5")])
    assert unobserved["status"] == "not_observed"
    assert c.case_record("R3", [])["status"] == "not_observed"


def test_only_the_two_documented_part_gaps_are_allowed_in_a_passing_case():
    ok = c.case_record("R4b", [c.part("job_state", "pass"), c.part("docking", "not_observed", "no_model_time_limit")])
    assert ok["status"] == "pass" and ok["allowedGaps"] == [{"part": "docking", "reason": "no_model_time_limit"}]
    ok = c.case_record("R4a", [c.part("x", "pass"), c.part("docking", "not_observed", "receptor_atom_limit")])
    assert ok["status"] == "pass"
    wrong = c.case_record("R4a", [c.part("docking", "not_observed", "no_model_time_limit")])
    assert wrong["status"] == "not_observed"
    other = c.case_record("R1", [c.part("docking", "not_observed", "receptor_atom_limit")])
    assert other["status"] == "not_observed"


def test_a_not_observed_part_needs_a_closed_reason():
    with pytest.raises(ValueError):
        c.part("a", "not_observed", "made_up_reason")
    with pytest.raises(ValueError):
        c.part("a", "pass", "a reason")
    with pytest.raises(ValueError):
        c.part("a", "fail")


def test_missing_cases_are_not_observed_and_never_count():
    records = {"R1": c.case_record("R1", [c.part("a", "pass")])}
    done = c.complete_cases(records, ["R1", "R2"])
    assert done["R2"]["status"] == "not_observed" and done["R2"]["reason"] == "case_not_reported"
    assert done["R3"]["reason"] == "not_run"
    judged = c.judge(done, {"gate": True}, rehearsal=False, subset=False)
    assert judged["acceptance"] is False and judged["passed"] is False and "R2" in judged["notPassing"]


def test_acceptance_needs_every_case_every_gate_and_no_rehearsal_or_subset():
    every = {case: c.case_record(case, [c.part("a", "pass")]) for case in c.CASES}
    assert c.judge(every, {"g": True}, rehearsal=False, subset=False)["acceptance"] is True
    assert c.judge(every, {"g": False}, rehearsal=False, subset=False)["acceptance"] is False
    assert c.judge(every, {}, rehearsal=False, subset=False)["acceptance"] is False
    rehearsed = c.judge(every, {"g": True}, rehearsal=True, subset=False)
    assert rehearsed["acceptance"] is False and rehearsed["passed"] is True
    assert c.judge(every, {"g": True}, rehearsal=True, subset=True)["acceptance"] is False


def test_r5_fails_on_a_bad_or_missing_row():
    rows = [{"structure": name.upper(), "waters": policy, "ok": True, "problems": []}
            for name in c.STRUCTURES for policy in c.WATERS]
    assert cases.r5_case(rows)["status"] == "pass"
    assert cases.r5_case(rows[:-1])["status"] == "fail"
    rows[3] = {**rows[3], "ok": False, "problems": ["product x != oracle y"]}
    assert cases.r5_case(rows)["status"] == "fail"


def test_r6_and_r9_without_their_inputs_are_not_pass():
    assert cases.r6_case({"ok": None, "reason": "prerequisite_failed:R5"}, [], None)["status"] == "not_observed"
    assert cases.r9_case(None, None, [], [], True)["status"] == "not_observed"


def test_expected_limitations_follow_the_conditions():
    assert c.expected_limitations([], False) == [c.FIXED["RP1"], c.FIXED["RP2"]]
    every = c.expected_limitations(oracle.CLASSES, True)
    assert every == [c.FIXED[key] for key in ("RP1", "RP2", "RP3", "RP4", "RP5", "RP6")]


# ---------------------------------------------------------------------------------------------------- loopback API
@pytest.mark.parametrize("path", ["/runs/r/docking/batches/limit_approval", "/runs/r/sequence_ga/limit_approval",
                                  "/runs/r/raise_limits", "/runs/r/jev/sends", "/runs/r/jev/consent",
                                  "/runs/r/jev/preview", "/runs/r/jev_loops", "/runs/r/jev_loops/x/compute"])
def test_the_api_refuses_limit_and_jev_writes_before_sending(path):
    api = c.Api("http://127.0.0.1:9")
    with pytest.raises(PermissionError):
        api.post(path, {})
    assert api.sent == []


def test_the_api_is_loopback_only():
    with pytest.raises(ValueError):
        c.Api("http://example.org:8000")


# ---------------------------------------------------------------------------------------------------- evidence
def test_leaks_are_found_and_clean_text_passes():
    assert c.leak_kinds("see /Users/someone/x.cif") == ["absolute_path"]
    assert "key_pattern" in c.leak_kinds("OPENROUTER_API_KEY=abc")
    assert "placeholder" in c.leak_kinds(c.SENTINELS[0])
    assert c.leak_kinds("<repo>/runs/m29 and obj://run_x/structure/abc") == []


def test_wording_scan_exempts_fixed_sentence_lines_only():
    assert c.forbidden_hits("\n".join(c.FIXED.values())) == []
    hits = c.forbidden_hits("이 위치는 추천 위치이다\n- 수소결합 2개")
    assert [hit["words"] for hit in hits] == [["추천"], ["수소결합"]]
    assert "text" not in hits[0] and len(hits[0]["line_sha256"]) == 64
    assert c.forbidden_hits("충돌 없음") and c.forbidden_hits("predicted stability")


def test_stored_objects_hash_to_their_handles_in_the_saved_fixture():
    events = [json.loads(line) for line in
              (FIX / "mutation_report_v1/v1-cited-reports.events.jsonl").read_text().splitlines()]
    reports = cases.stored_reports(events)
    assert {item["render"] for item in reports} == {"mutation_candidates_markdown@1"}
    for item in reports:
        assert c.handle_matches(events, item["handle"])
    assert not c.handle_matches(events, reports[0]["handle"][:-1] + "0")


# ---------------------------------------------------------------------------------------------------- runner
def _runner_args(reference: Path, **over):
    import m29_offscreen_acceptance as runner
    base = {"root": f"runs/m29-unit-{uuid.uuid4().hex}", "artifacts":
            f"frontend/tests/offscreen/artifacts/m29-repair/unit-{uuid.uuid4().hex}", "out": None, "rehearse": False,
            "only": None, "structures": None, "m15_reference": str(reference),
            "saved_report_runs": "runs/m28-fixture-20261012/fixture", "code_root": str(REPO), "build": "never"}
    return runner, argparse.Namespace(**{**base, **over})


def test_the_runner_refuses_tmp_roots_and_subsets_without_rehearsal():
    reference = REPO / "runs" / f"m29-unit-reference-{uuid.uuid4().hex}"
    reference.mkdir(parents=True)
    try:
        (reference / "active.json").write_text('{"set_hash": "unit"}')
        runner, args = _runner_args(reference, root="/tmp/m29-unit-root")
        with pytest.raises(SystemExit, match="/tmp"):
            runner.Runner(args)
        runner, args = _runner_args(reference, only=["r1"])
        with pytest.raises(SystemExit, match="rehearsal"):
            runner.Runner(args)
        runner, args = _runner_args(reference, rehearse=True, only=["r1"])
        made = runner.Runner(args)
        assert made.subset is True and not made.root.exists() and not made.artifacts.exists()
        runner, args = _runner_args(reference, root="runs")
        with pytest.raises(SystemExit, match="new folder"):
            runner.Runner(args)
        runner, args = _runner_args(reference, out=str(reference))      # an --out holding files it did not write
        with pytest.raises(SystemExit, match="not empty"):
            runner.Runner(args)
    finally:
        (reference / "active.json").unlink()
        reference.rmdir()


def test_steps_and_their_needs_are_ordered():
    import m29_offscreen_acceptance as runner
    for step, needs in runner.STEP_NEEDS.items():
        assert all(runner.STEPS.index(need) < runner.STEPS.index(step) for need in needs)
    assert set(runner.PYTEST) == {"R6", "R9", "R10"}
    blobs = runner.blob_check(REPO)
    assert blobs["files"] == 27 and blobs["ok"] is True


def test_help_and_the_exporter_run():
    help_text = subprocess.run([sys.executable, str(SCRIPTS / "m29_offscreen_acceptance.py"), "--help"],
                               capture_output=True, text=True, check=True).stdout
    assert "--rehearse" in help_text and "--only" in help_text
    out = SCRIPTS.parent / "runs" / f"m29-unit-export-{uuid.uuid4().hex}.json"
    try:
        env = {**os.environ, "PYTHONPATH": str(REPO / "backend")}
        subprocess.run([sys.executable, str(SCRIPTS / "m29_export_fixed_sentences.py"), "--out", str(out)], env=env,
                       check=True, timeout=120)
        exported = json.loads(out.read_text())
        assert exported["sentences"] == c.FIXED
        assert exported["refusedCode"] == c.REFUSED and exported["refusedMessage"] == c.REFUSED_MESSAGE
    finally:
        out.unlink(missing_ok=True)


def test_the_harness_parses():
    harness = REPO / "frontend/tests/offscreen/structure-repair-flow.cjs"
    if subprocess.run(["node", "--version"], capture_output=True, check=False).returncode != 0:
        pytest.fail("node is required for the harness syntax check")
    subprocess.run(["node", "--check", str(harness)], check=True)
