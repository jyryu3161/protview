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
import re
import subprocess
import sys
import types
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
            # m29_common names the refused routes (FORBIDDEN_POST_PARTS) and the send route R10 looks for among the
            # page's requests (JEV_SEND_ROUTE, never sent: Api refuses every non-GET /jev route)
            if name == "m29_common.py" and word in ("raise_limits", "limit_approval", "jev/sends"):
                continue
            assert word not in text, (name, word)
    with pytest.raises(PermissionError):
        c.Api("http://127.0.0.1:9").post(f"/runs/r{c.JEV_SEND_ROUTE}", {})
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


_CLASSIFIED: dict[str, dict] = {}


def _classified(name: str, tpl) -> dict:
    if name not in _CLASSIFIED:
        _CLASSIFIED[name] = oracle.classify((FIX / f"public_{name}.cif").read_bytes(), "strip_all", tpl)
    return _CLASSIFIED[name]


def _doc_table(section: str, end: str, header: str) -> list[list[str]]:
    """The rows of the first Markdown table after ``header`` in one section of preflight.md (cells stripped)."""
    text = (QA / "preflight.md").read_text().split(section, 1)[1].split(end, 1)[0]
    text = text.split(header, 1)[1]
    rows = []
    for line in text.splitlines()[1:]:
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip().strip("*") for cell in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= {"-", ":"}:
            continue
        rows.append(cells)
    return rows


def _number(cell: str) -> float:
    return float(cell.split("(")[0].replace(",", "").strip("* "))


def test_the_measured_m21_rows_are_the_documented_s1_table_and_the_oracle_heavy_atoms(tpl):
    """``M21_BAND_MEASURED`` is the S1 table of preflight.md (heavy atoms after repair, seconds), its band follows the
    spec 10.1 rule on those heavy atoms, and the oracle's protein heavy atoms after repair of each input file are the
    documented ones."""
    rows = _doc_table("### S1.", "## 사용자 결정", "| 구조(보완 뒤) |")
    documented = {cells[0].split("(")[0].strip().lower(): (int(_number(cells[1])), _number(cells[2])) for cells in rows}
    assert set(documented) == set(c.M21_BAND_MEASURED)
    for name, (band, heavy, seconds) in c.M21_BAND_MEASURED.items():
        assert documented[name][0] == heavy, name
        assert abs(documented[name][1] - seconds) < 0.5, name
        rule = "completes" if heavy <= 1600 else "near_limit" if heavy <= 2200 else "exceeds"
        assert band == rule, name
        assert _classified(name, tpl)["protein_heavy_after"] == heavy, name


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


# ---------------------------------------------------------------------------------------------------- R4a docking gap
HARNESS = REPO / "frontend/tests/offscreen/structure-repair-flow.cjs"
# Refusal bodies (the product's 422 envelope) the old rule /receptor.*atom|atom.*limit/ over the whole JSON took for the
# receptor atom cap: none of them is.
NOT_THE_CAP = {
    "box_no_receptor_atoms": {"ok": False, "error": "input_invalid", "message": "no receptor heavy atom lies inside the box",
                              "fix": None, "detail": {"reason_code": "box_no_receptor_atoms"}},
    "receptor_altloc_present": {"ok": False, "error": "input_invalid", "message": "receptor has alternate locations",
                                "fix": None, "detail": {"reason_code": "receptor_altloc_present", "items": [
                                    {"residue": {"chain_auth": "A", "seq_auth": 25}, "atom_name": "CB", "altloc": "A"}],
                                    "total": 1}},
    "receptor_invalid_other": {"ok": False, "error": "input_invalid", "message": "receptor has no atoms", "fix": None,
                               "detail": {"reason_code": "receptor_invalid", "receptor_atom_count": 0}},
}
THE_CAP = {"ok": False, "error": "input_invalid", "message": "receptor atom count must be 1-10000", "fix": None,
           "detail": {"reason_code": "receptor_invalid"}}


def _harness_judgement(bodies: list[dict]) -> dict:
    """The harness's own refusal summary and gap decision (node requires the harness module; nothing is launched)."""
    script = ("const h = require(process.argv[1]); const bodies = JSON.parse(process.argv[2]);"
              "const summaries = bodies.map(body => h.refusalSummary({ status: 422, body }));"
              "process.stdout.write(JSON.stringify({ summaries, gap: h.receptorAtomLimitGap(summaries),"
              " each: summaries.map(item => h.receptorAtomLimitGap([item])), cap: h.RECEPTOR_ATOM_LIMIT }));")
    done = subprocess.run(["node", "-e", script, str(HARNESS), json.dumps(bodies)], capture_output=True, text=True,
                          check=True, cwd=REPO / "frontend", timeout=120)
    return json.loads(done.stdout)


def test_the_receptor_atom_cap_is_the_products_refusal():
    tree = ast.parse((REPO / "backend/mw/docking_constants.py").read_text())
    caps = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
            and any(getattr(target, "id", None) == "MAX_RECEPTOR_ATOMS" for target in node.targets)]
    assert caps == [c.M18_MAX_RECEPTOR_ATOMS]
    source = (REPO / "backend/mw/docking_inputs.py").read_text()
    assert 'raise _fail("receptor_invalid", f"receptor atom count must be 1-{C.MAX_RECEPTOR_ATOMS}")' in source
    assert c.RECEPTOR_ATOM_LIMIT_MESSAGE == "receptor atom count must be 1-10000" == THE_CAP["message"]
    cap = _harness_judgement([])["cap"]
    assert cap == {"status": 422, "error": "input_invalid", "reason": c.RECEPTOR_ATOM_LIMIT_REASON,
                   "message": c.RECEPTOR_ATOM_LIMIT_MESSAGE}


def test_only_the_exact_cap_refusal_is_a_harness_gap():
    old_rule = re.compile(r"receptor.*atom|atom.*limit", re.IGNORECASE)
    for body in NOT_THE_CAP.values():
        assert old_rule.search(json.dumps(body))          # the old rule's misclassification
    judged = _harness_judgement([*NOT_THE_CAP.values(), THE_CAP])
    assert judged["each"] == [False, False, False, True]
    assert judged["gap"] is False                          # one other refusal among them: not a gap
    assert _harness_judgement([THE_CAP, THE_CAP])["gap"] is True
    assert _harness_judgement([])["gap"] is False
    summary = judged["summaries"][1]
    assert summary == {"status": 422, "error": "input_invalid", "reason": "receptor_altloc_present",
                       "message": "receptor has alternate locations"}             # code and message only, no detail


def _summary(body: dict) -> dict:
    return {"status": 422, "error": body["error"], "reason": body["detail"]["reason_code"], "message": body["message"]}


def test_r4a_docking_gap_needs_the_cap_refusal_and_a_receptor_above_the_cap(tpl):
    bound_1hsg = oracle.receptor_atoms_lower_bound(_classified("1hsg", tpl), tpl)
    assert bound_1hsg <= c.M18_MAX_RECEPTOR_ATOMS
    passing = [c.part("harness", "pass"), c.part("m21_completed_240", "pass")]
    for name, body in NOT_THE_CAP.items():
        docking = {"refused": [_summary(body)]}                       # the harness failed the part, no notObserved
        part = cases.receptor_limit_part(docking, "fail", bound_1hsg)
        assert part["status"] == "fail", name
        forged = {"notObserved": "receptor_atom_limit", "refused": [_summary(body)]}
        assert cases.receptor_limit_part(forged, "pass", 20000)["status"] == "fail", name
        assert c.case_record("R4a", [*passing, part])["status"] == "fail"
    exact = {"notObserved": "receptor_atom_limit", "refused": [_summary(THE_CAP), _summary(THE_CAP)]}
    on_1hsg = cases.receptor_limit_part(exact, "pass", bound_1hsg)
    assert on_1hsg["status"] == "fail" and "not implied by the input" in on_1hsg["reason"]
    assert c.case_record("R4a", [*passing, on_1hsg])["status"] == "fail"
    above = cases.receptor_limit_part(exact, "pass", c.M18_MAX_RECEPTOR_ATOMS + 1)
    assert above["status"] == "not_observed" and above["reason"] == "receptor_atom_limit"
    assert c.case_record("R4a", [*passing, above])["status"] == "pass"
    assert cases.receptor_limit_part({"notObserved": "receptor_atom_limit", "refused": []}, "pass",
                                     c.M18_MAX_RECEPTOR_ATOMS + 1)["status"] == "fail"


def test_the_receptor_atom_bound_is_below_every_documented_receptor_count(tpl):
    """preflight.md (g): the measured M18 receptor atoms (hydrogens included) of the M21 models on the repaired
    structures; the oracle's bound never exceeds them (it is a lower bound) and keeps every one under the cap."""
    rows = _doc_table("## (g)", "## (h)", "| 구조 | 변이형 | 야생형 참조 |")
    measured = {cells[0].lower(): int(_number(cells[1])) for cells in rows}
    assert set(measured) == {"8vf6", "1mq4", "1m17", "1a4i", "1hsg", "1a30"} and measured["1hsg"] == 3119
    for name, count in measured.items():
        bound = oracle.receptor_atoms_lower_bound(_classified(name, tpl), tpl)
        assert 0.9 * count <= bound <= count <= c.M18_MAX_RECEPTOR_ATOMS, (name, bound, count)


# ---------------------------------------------------------------------------------------------------- other case parts
def _set(*klifs: str) -> dict:
    positions = []
    for key in klifs:
        chain, seq, resname = key.split("/")
        positions.append({"residue": {"chain_auth": chain, "seq_auth": int(seq), "icode": "", "resname": resname},
                          "exclusion_reasons": ["klifs_key_site"]})
    return {"positions": positions}


def test_r3_klifs_needs_exactly_the_seven_documented_sites():
    seven = _set(*c.KLIFS_SEVEN)
    assert cases.klifs_seven_part(seven, seven)[0]["status"] == "pass"
    eight = _set(*c.KLIFS_SEVEN, "A/150/VAL")
    assert cases.klifs_seven_part(eight, eight)[0]["status"] == "fail"      # a superset of the seven is not the seven
    six = _set(*c.KLIFS_SEVEN[:6])
    assert cases.klifs_seven_part(six, seven)[0]["status"] == "fail"


def test_r6_viewer_needs_the_original_structure_offered():
    viewer = {"selects": 15, "optionsWithRepaired": 0, "optionsWithPrepared": 3, "viewerSource": "p", "repaired": "r"}
    api = {"ok": True, "targets": [], "nothingStored": {}, "count": 0}
    part = next(p for p in cases.r6_case(api, [], {"observed": {"viewer": viewer}})["parts"] if p["name"] == "viewer_path")
    assert part["status"] == "pass"
    part = next(p for p in cases.r6_case(api, [], {"observed": {"viewer": {**viewer, "optionsWithPrepared": 0}}})[
        "parts"] if p["name"] == "viewer_path")
    assert part["status"] == "fail"


def _r10_no_send(posts, sends=0) -> str:
    row = {"status": "pass", "externalRequestCount": 0, "parts": {}, "requestedPostPaths": posts,
           "observed": {"r10": {"sends": sends}}}
    record = cases.r10_case(None, row, [], {"ok": True}, 0, 0)
    return next(p for p in record["parts"] if p["name"] == "no_send")["status"]


def test_r10_no_send_is_read_from_the_pages_own_post_requests():
    preview = ["/api/runs/<run>/commands", "/api/runs/<run>/jev/preview"]
    assert _r10_no_send(preview) == "pass"
    assert _r10_no_send([*preview, "/api/runs/<run>/jev/sends"]) == "fail"
    assert _r10_no_send(["/api/runs/<run>/commands"]) == "fail"             # the list did not see the JEV writes
    assert _r10_no_send(None) == "fail"
    assert _r10_no_send(preview, sends=1) == "fail"
    harness = HARNESS.read_text()
    assert "sendClicked" not in harness and "requestedPostPaths" in harness


def test_r9_needs_every_compared_read_to_be_200():
    ok = {"list": (200, []), "detail": (200, {}), "atoms": (200, {}), "structure": [200, "x"]}
    assert cases.r9_case(ok, dict(ok), [], [], True)["parts"][0]["status"] == "pass"
    refused = {**ok, "atoms": (404, {"error": "not_found"})}
    assert cases.r9_case(refused, dict(refused), [], [], True)["parts"][0]["status"] == "fail"   # same, but not 200
    missing = {**ok, "structure": [500, None]}
    assert cases.r9_case(ok, missing, [], [], True)["parts"][0]["status"] == "fail"


def test_r11_fixed_sentence_wording_can_fail():
    def wording(sentences: dict) -> str:
        record, _scans = cases.r11_case({"s": "보완 구조"}, {"r": "## 구조 출처"}, {"sentences": sentences})
        return next(p for p in record["parts"] if p["name"] == "fixed_sentences_wording")["status"]
    assert wording(dict(c.FIXED)) == "pass"
    assert wording({**c.FIXED, "SO2": c.FIXED["SO2"] + " 추천"}) == "fail"
    assert c.forbidden_hits(c.FIXED["SO1"]) == [] and c.forbidden_hits(c.FIXED["SO1"] + "\n최적 위치", skip_fixed=False)
    record, _scans = cases.r11_case({"s": "x"}, {"r": "y"}, None)
    assert next(p for p in record["parts"] if p["name"] == "fixed_sentences_wording")["status"] == "fail"


# ---------------------------------------------------------------------------------------------------- gates
def _gates(**over):
    import m29_offscreen_acceptance as runner
    external = {"browserNonLoopbackRequests": 0, "providerCalls": 0, "productResolverReads": 0, "dispatchEvents": 0,
                "harnessDispatchGuard": False, "apiForbiddenSent": 0, "apiServerErrors": [], "harnessServerErrors": 0,
                "proxyTimeouts": [], **over.pop("external", {})}
    base = {"left": [], "listening": {}, "folders_before": {"a": False}, "folders_after": {"a": False},
            "build": {"buildCurrentWithSource": True}, "fixed": {"sentences": {}}, **over}
    return runner.gate_values(external, **base)


def test_gates_never_read_a_missing_count_as_zero():
    assert all(_gates().values())
    assert _gates(external={"productResolverReads": None})["providerCalls0"] is False
    assert _gates(external={"reopenResolverReads": None})["providerCalls0"] is False
    assert _gates(external={"reopenResolverReads": 0, "reopenProviderCalls": 0})["providerCalls0"] is True
    assert _gates(external={"harnessServerErrors": None})["noServerError"] is False
    assert _gates(external={"apiServerErrors": [{"method": "GET", "path": "/x", "status": 500}]})["noServerError"] is False
    assert _gates(listening={"8000": ["123"]})["nothingLeft"] is False
    assert _gates(left=["123 guardian"])["nothingLeft"] is False


# A job start Next's rewrite proxy cut (rehearsal 07b, 1HSG R4a: the M21 start answers after about 114 s): the page got
# 500, the frontend log names the start; ids here are made up.
RUN, JOB = "run_" + "a1" * 16, "job_" + "b2" * 16
PROXY_LINE = (f"Failed to proxy http://127.0.0.1:8000/runs/{RUN}/jobs/{JOB}/start [Error: socket hang up] "
              "{ code: 'ECONNRESET' }")
CUT = {"at": 1, "method": "POST", "path": f"/api/runs/<run>/jobs/{JOB}/start", "status": 500, "busy": False}


def _classify(errors, log=PROXY_LINE + "\n[Error: socket hang up] { code: 'ECONNRESET' }\n", run=RUN):
    import m29_offscreen_acceptance as runner
    return runner.classify_server_errors(errors, run, log)


def test_a_job_start_the_frontend_proxy_cut_is_a_proxy_timeout():
    proxied, other = _classify([CUT])                                                      # (a)
    assert other == [] and proxied == [{"job": JOB, "method": "POST", "path": "/api/runs/<run>/jobs/<job>/start",
                                        "status": 500, "frontendLogLine": True, "finalJobStatus": None,
                                        "frontendLog": "Failed to proxy http://127.0.0.1:8000/runs/<run>/jobs/<job>/start "
                                                       "[socket hang up]"}]
    ended = [{**proxied[0], "finalJobStatus": "done"}]
    assert _gates(external={"proxyTimeouts": ended})["noServerError"] is True
    assert _gates(external={"proxyTimeouts": ended, "harnessServerErrors": len(other)})["noServerError"] is True


def test_only_that_exact_shape_is_a_proxy_timeout():
    assert _classify([CUT], log="ready on 127.0.0.1:3000\n") == ([], [{"method": "POST", "path": CUT["path"],
                                                                       "status": 500, "busy": False}])     # (b)
    other_job = PROXY_LINE.replace(JOB, "job_" + "c3" * 16)
    assert _classify([CUT], log=other_job)[0] == []                                       # the log names another job
    assert _classify([CUT], run="run_" + "d4" * 16)[0] == []                              # ... or another run
    for path in (f"/api/runs/<run>/jobs/{JOB}", "/api/runs/<run>/jobs", "/api/runs/<run>/jobs/approve",
                 f"/api/runs/<run>/jobs/{JOB}/start/x", f"/api/runs/<run>/jobs/{JOB}/cancel", "/api/runs/<run>/commands"):
        proxied, other = _classify([{**CUT, "path": path}])                               # (c)
        assert proxied == [] and len(other) == 1, path
    assert _classify([{**CUT, "method": "GET"}])[0] == []                                 # (d)
    assert _classify([{**CUT, "status": 502}])[0] == [] and _classify([{**CUT, "busy": True}])[0] == []
    assert _classify([{**CUT, "status": 503, "busy": True}]) == ([], [])                  # the busy 503 stays exempt
    assert _classify(None) == (None, None)
    assert _gates(external={"harnessServerErrors": 1})["noServerError"] is False


def test_a_proxy_timeout_whose_job_did_not_end_fails_the_gate():
    proxied, _other = _classify([CUT])
    for status in ("running", "queued", "claimed", None):                                  # (e), and a failed read
        assert _gates(external={"proxyTimeouts": [{**proxied[0], "finalJobStatus": status}]})["noServerError"] is False
    assert _gates(external={"proxyTimeouts": None})["noServerError"] is False
    assert _gates(external={"proxyTimeouts": [{**proxied[0], "finalJobStatus": "done", "frontendLogLine": False}]})[
        "noServerError"] is False


def test_the_proxy_timeouts_and_their_job_states_reach_the_evidence():
    import m29_offscreen_acceptance as runner
    reference = REPO / "runs" / f"m29-unit-reference-{uuid.uuid4().hex}"
    reference.mkdir(parents=True)
    try:
        (reference / "active.json").write_text('{"set_hash": "unit"}')
        made = runner.Runner(_runner_args(reference, rehearse=True, only=["r4a"])[1])

        def get(path):
            if JOB not in path:
                raise OSError("no backend")
            return 200, {"status": "done"}
        made.api = types.SimpleNamespace(sent=[], get=get)
        assert made.final_job_status(RUN, JOB) == "done" and made.final_job_status(RUN, "job_x") is None
        assert made.final_job_status(None, JOB) is None
        proxied, other = _classify([CUT])
        proxied[0]["finalJobStatus"] = made.final_job_status(RUN, JOB)
        made.flow_rows = [{"externalRequestCount": 0, "serverErrorResponses": len(other), "proxyTimeouts": proxied,
                           "dispatchGuard": False}]
        external = made.external_counts()                                                   # (f)
        assert external["proxyTimeouts"] == proxied and external["harnessServerErrors"] == 0
        assert runner.gate_values(external | {"apiServerErrors": []}, left=[], listening={}, folders_before={},
                                  folders_after={}, build=None, fixed=None)["noServerError"] is True
    finally:
        (reference / "active.json").unlink()
        reference.rmdir()


def test_the_proxy_log_summary_never_carries_a_path():
    import m29_offscreen_acceptance as runner
    line = (f"Failed to proxy http://127.0.0.1:8000/runs/{RUN}/jobs/{JOB}/start [Error: socket hang up] at "
            "/Users/someone/protview/frontend/node_modules/next/dist/server/lib/router-utils/proxy-request.js:122 "
            "{ code: 'ECONNRESET' }")
    summaries = runner.proxy_failures(line)                                                 # (g)
    assert list(summaries) == [(RUN, JOB)]
    text = summaries[(RUN, JOB)]
    assert c.leak_kinds(text) == [] and "/Users" not in text and RUN not in text and JOB not in text
    proxied, _other = _classify([CUT], log=line)
    assert c.leak_kinds(json.dumps(proxied)) == []


def test_export_is_not_clean_when_a_text_was_held_for_a_leak():
    import m29_offscreen_acceptance as runner
    assert runner.held_for_leak([{"path": "a", "held": "over_256KiB"}]) == []
    assert runner.held_for_leak([{"path": "b", "held": "absolute_path"}]) == [{"path": "b", "held": "absolute_path"}]


def test_the_api_keeps_each_answers_status():
    api = c.Api("http://127.0.0.1:9")
    with pytest.raises(OSError):
        api.get("/x")                                    # nothing listens on port 9: no HTTP answer, status None
    assert api.sent == [{"method": "GET", "path": "/x", "status": None}] and api.server_errors() == []
    api.sent.append({"method": "GET", "path": "/y", "status": 503, "busy": False})
    api.sent.append({"method": "POST", "path": "/z", "status": 503, "busy": True})
    assert api.server_errors() == [{"method": "GET", "path": "/y", "status": 503, "busy": False}]


BUSY_CASES = [  # (status, body, busy)
    (503, {"ok": False, "error": "transient", "message": "run execution owner is busy", "detail": {"busy": True}}, True),
    (503, {"detail": {"error": "busy", "message": "m"}}, True),
    (503, {"ok": False, "error": "transient", "message": "m", "detail": {"reason_code": "global_concurrency_busy"}}, True),
    (503, {"ok": False, "error": "fatal", "message": "invalid error envelope", "detail": {}}, False),
    (500, {"detail": {"error": "internal_error", "message": "m"}}, False),
    (502, {"detail": {"busy": True}}, False),
    (503, "Service Unavailable", False),
]


def test_only_the_products_busy_503_is_not_a_server_error():
    assert [c.busy_answer(status, body) for status, body, _ in BUSY_CASES] == [busy for *_, busy in BUSY_CASES]
    script = ("const h = require(process.argv[1]); const cases = JSON.parse(process.argv[2]);"
              "process.stdout.write(JSON.stringify(cases.map(([status, body]) => h.busyAnswer(status, body))));")
    done = subprocess.run(["node", "-e", script, str(HARNESS), json.dumps([[s, b] for s, b, _ in BUSY_CASES])],
                          capture_output=True, text=True, check=True, cwd=REPO / "frontend", timeout=120)
    assert json.loads(done.stdout) == [busy for *_, busy in BUSY_CASES]          # the harness applies the same rule


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
