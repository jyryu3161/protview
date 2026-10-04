"""M21 T5: ``mutation_model`` reports (spec 8): field-cited OpenMM potentials (kJ/mol, 0.01 ``ROUND_HALF_UP``),
mutated-residue SASA, contact / partner residue / disulfide / protonation-difference / PDBFixer added-atom counts, the
fixed limitation sentences verbatim and in order, no difference or change claims, no docking scores, the forbidden
words, and reopen that reads stored objects only.

The model comes from the real worker through the product job path (``mutation_model_fixture.shared_world``; public
1UBQ I44W). Values are checked against the stored rows with independent recounts and an independent ``Decimal``
half-up rendering. Tampered claims, manifests and Markdown are LABELED TEST FABRICATIONS (forged reports are stored
in an events-only copy of the run, so the shared run stays untouched).
"""
from __future__ import annotations

import ast
import copy
import json
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mutation_model_fixture import SIDES, shared_world

from mw import mutation_model_bundle as bundle
from mw import mutation_model_constants as K
from mw import mutation_model_reports as rep
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError
from mw.runtime.orchestrator import Run
from mw.tools import openmm_method
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
IDENTITY = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return shared_world(tmp_path_factory)


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


def _report(client, handle, rid) -> dict:
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert response.status_code == 201, response.text
    return response.json()


def _selected(client, handle, rid):
    return client.get(f"/runs/{rid}/reports/selected", params={"handle": handle})


def _claim(manifest, statement, **selector):
    found = [c for c in manifest["claims"] if c["statement_id"] == statement and
             all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
    assert len(found) == 1, (statement, selector, len(found))
    return found[0]


def _half_up(value: float) -> str:
    return str(Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _stored(world) -> dict:
    return api_module._run(world["rid"]).store.load(world["model"])


def _copy_run(world, tmp_path) -> tuple[Path, Run]:
    root = tmp_path / "copy"
    (root / world["rid"]).mkdir(parents=True)
    (root / world["rid"] / "events.jsonl").write_bytes((world["root"] / world["rid"] / "events.jsonl").read_bytes())
    return root, new_run(root, run_id=world["rid"], dry_run=False)


def _forge(run, manifest: dict, markdown: str, mutate) -> str:
    """LABELED TEST FABRICATION: store a tampered report manifest and its creation event."""
    forged = copy.deepcopy(manifest)
    mutate(forged)
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by="forged_test_report", summary={"result_handle": manifest["result_handle"]})
        forged["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_test_report",
                               summary={"result_handle": forged["result_handle"],
                                        "analysis_type": rep.ANALYSIS_TYPE, "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _forbid(*_args, **_kwargs):
    raise AssertionError("a report must not model, minimize, start a job or run a tool")


# --- rendering and forbidden words -------------------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "text"), [(2.675, "2.68"), (2.625, "2.63"), (-0.005, "-0.01"), (0.004, "0.00"),
                                             (-0.004, "0.00"), (-12345.675, "-12345.68"), (3.0, "3.00"),
                                             (-6789.6949999, "-6789.69")])
def test_two_decimal_rendering_is_decimal_half_up(value, text):
    assert rep.render_two_decimals(value) == text == _half_up(value).replace("-0.00", "0.00")
    assert round(2.675, 2) == 2.67   # the float rounding the rule forbids
    for bad in (float("nan"), float("inf"), "1.0", None, True):
        with pytest.raises(EvidenceError):
            rep.render_two_decimals(bad)


def test_forbidden_words_with_only_the_fixed_limitation_lines_exempt():
    text = "\n".join(["# x", *K.LIMITATION_ORDER, "OpenMM 전위, 최소화 전 (kJ/mol)", "이황화 SG–SG 쌍 수"])
    assert rep.check_no_interpretation(text) == text
    # the fixed sentences themselves contain ΔΔG·안정성·친화도 and 수소결합
    assert any("ΔΔG" in line for line in K.LIMITATION_ORDER) and any("수소결합" in line for line in K.LIMITATION_ORDER)
    for bad in ("에너지", "OpenMM 에너지", "energy", "안정성", "ΔΔG", "순위", "추천", "최적", "개선", "활성", "예측",
                "유망", "좋은", "나쁜", "안전", "점수", "수소결합", "수소 결합", "이황화 결합", "rank", "best",
                "recommend", "optimal", "improves", "predicted", "promising", "good", "safe", "active", "score",
                "H-bond", "hydrogen bond", "affinity", "binding"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            rep.check_no_interpretation(f"ok\n{bad}")
    for near in (f"- {K.L2}", K.L2 + " ", K.L7.replace("수소결합", "수소 결합")):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            rep.check_no_interpretation(near)


# --- a valid report through the API -----------------------------------------------------------------------------------

def test_report_cites_each_stored_value_with_independent_recounts(client, world):
    rid, handle = world["rid"], world["model"]
    stored = _stored(world)
    created = _report(client, handle, rid)
    manifest, markdown = created["manifest"], created["markdown"]
    assert (manifest["analysis_type"], manifest["render_version"], manifest["result_schema"]) == (
        "mutation_model", "mutation_model_markdown@1", "mutation_model@1")
    assert {c["source_handle"] for c in manifest["claims"]} == {handle}
    assert {(c["evidence_kind"], c["source_kind"], c["reference"]) for c in manifest["claims"]} == {
        ("computed", "mutation_model", None)}
    # candidate: 7 fields, from -> to
    candidate = stored["candidate"]
    for field in IDENTITY:
        claim = next(c for c in manifest["claims"] if c["field_path"] == f"candidate.residue.{field}")
        assert claim["exact_value"] == candidate["residue"][field]
    assert [next(c for c in manifest["claims"] if c["field_path"] == f"candidate.{k}")["rendered_value"]
            for k in ("from", "to", "mutant_resname")] == ["I", "W", "TRP"]
    for side in SIDES:
        entry = stored["structures"][side]
        for stage in ("before", "after"):
            claim = _claim(manifest, "openmm_potential", structure=side, stage=stage)
            assert claim["exact_value"] == entry["energy"][f"{stage}_kJ_mol"] and claim["unit"] == "kJ/mol"
            assert claim["rendered_value"] == _half_up(claim["exact_value"]) and claim["rounding"] == "potential_2dp"
        sasa = _claim(manifest, "mutated_residue_sasa", structure=side)
        assert sasa["exact_value"] == entry["sasa"]["value_A2"] and sasa["rendered_value"] == _half_up(
            entry["sasa"]["value_A2"]) and sasa["unit"] == "A2"
        rows = entry["contacts"]["rows"]
        assert _claim(manifest, "contact_count", structure=side)["exact_value"] == len(rows) > 0
        partners = {tuple(row["partner_residue"][f] for f in IDENTITY) for row in rows}
        assert _claim(manifest, "contact_residue_count", structure=side)["exact_value"] == len(partners)
        assert _claim(manifest, "contact_cutoff", structure=side)["rendered_value"] == "4.0"
        assert _claim(manifest, "disulfide_pair_count", structure=side)["exact_value"] == \
            len(entry["disulfide_bonds"]) == 0   # 1UBQ has no cysteine
    assert _claim(manifest, "protonation_difference_count")["exact_value"] == len(stored["protonation_differences"])
    # Ile -> Trp: PDBFixer places the Trp side-chain atoms Ile lacks (N, CA, C, O, CB, CD1 are kept by name).
    added = _claim(manifest, "added_heavy_atom_count")
    assert added["exact_value"] == len(stored["structures"]["mutant"]["added_heavy_atoms"]) == 8
    assert {a["atom_name"] for a in stored["structures"]["mutant"]["added_heavy_atoms"]} == {
        "CG", "CD2", "NE1", "CE2", "CE3", "CZ2", "CZ3", "CH2"}
    # no difference, change or docking statement anywhere
    named = json.dumps([[c["statement_id"], c["field_path"], c["quantity"], c["operation"]]
                        for c in manifest["claims"]])
    assert not rep.DIFFERENCE.search(named.replace("protonation_difference", ""))
    assert not rep.DOCKING.search(named)
    assert set(manifest["comparison"]) == {"mutated_residue", "resnames", "new_disulfide_in_mutant",
                                           "protonation_difference_count"}
    # Markdown: OpenMM 전위 (never 에너지), each value once per structure column, fixed sentences verbatim in order
    assert "OpenMM 전위, 최소화 전 (kJ/mol)" in markdown and "에너지" not in markdown
    before = _claim(manifest, "openmm_potential", structure="mutant", stage="before")["rendered_value"]
    assert before.replace("-", "\\-").replace(".", "\\.") in markdown
    assert rep.check_no_interpretation(markdown) == markdown   # even the filled identifiers pass here
    tail = markdown.split("## Limitations\n\n", 1)[1]
    assert [line for line in tail.split("\n") if line in rep.FIXED_LIMITATIONS] == stored["limitations"] == \
        list(K.applicable_limitations(protonation_difference_count=len(stored["protonation_differences"]),
                                      new_disulfide_in_mutant=stored["comparison"]["new_disulfide_in_mutant"]))
    for sentence in stored["limitations"]:
        assert f"\n{sentence}\n" in markdown
    assert manifest["provenance"]["mutation_model"]["job_id"] == world["job"]["job_id"]
    # reopen, list and download read the same bytes
    assert _selected(client, created["handle"], rid).json()["markdown"] == markdown
    listed = {row["handle"]: row for row in client.get(f"/runs/{rid}/reports").json()}
    assert listed[created["handle"]]["analysis_type"] == "mutation_model"
    assert listed[world["m20_report"]["handle"]]["analysis_type"] == "mutation_candidates"
    download = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]})
    assert download.status_code == 200 and download.content == markdown.encode()
    as_json = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert as_json.content == canonical_json(manifest)


def test_conditional_limitations_render_only_when_they_apply(client, world):
    """LABELED TEST FABRICATION (render only): the stored manifest with one protonation difference and a new
    disulfide pair must carry L5 and L6 after L7, and the unchanged sentence list is then refused."""
    manifest = _report(client, world["model"], world["rid"])["manifest"]
    forged = copy.deepcopy(manifest)
    residue = forged["comparison"]["mutated_residue"]
    forged["protonation_differences"] = [{"residue": {**residue, "seq_auth": 68, "seq_label": 68, "resname": "HIS"},
                                          "wild_type_reference": "HIE", "mutant": "HID"}]
    forged["comparison"].update(protonation_difference_count=1, new_disulfide_in_mutant=True)
    forged["claims"] = [c if c["statement_id"] != "protonation_difference_count" else
                        {**c, "exact_value": 1, "rendered_value": "1"} for c in forged["claims"]]
    with pytest.raises(EvidenceError, match="limitations_mismatch"):
        rep.render_mutation_model_report(forged)
    forged["limitations"] = [K.L1, K.L2, K.L3, K.L4, K.L7, K.L5, K.L6]
    text = rep.render_mutation_model_report(forged)
    assert text.index(K.L7) < text.index(K.L5) < text.index(K.L6)
    for wrong in ([K.L1, K.L2, K.L3, K.L4, K.L7, K.L6, K.L5], [K.L1, K.L2, K.L3, K.L4, K.L5, K.L7, K.L6]):
        with pytest.raises(EvidenceError, match="limitations_mismatch"):
            rep.render_mutation_model_report({**forged, "limitations": wrong})


def test_existing_reports_are_unchanged(client, world):
    rid = world["rid"]
    run = api_module._run(rid)
    m20 = world["m20_report"]
    paths = {handle: world["root"] / rid / run.store.meta(handle)["path"]
             for handle in (m20["handle"], m20["markdown_handle"])}
    files = {handle: path.read_bytes() for handle, path in paths.items()}
    _report(client, world["model"], rid)
    _report(client, world["model"], rid)
    for handle, raw in files.items():
        assert paths[handle].read_bytes() == raw
    reopened = _selected(client, m20["handle"], rid).json()
    assert reopened["markdown"] == m20["markdown"] and reopened["manifest"] == m20["manifest"]
    assert client.get(f"/runs/{rid}/reports").status_code == 200


# --- claim verification -------------------------------------------------------------------------------------------------

def test_wrong_values_mixed_evidence_differences_and_docking_scores_are_rejected(client, world):
    rid, handle = world["rid"], world["model"]
    run = api_module._run(rid)
    manifest = _report(client, handle, rid)["manifest"]
    potential = _claim(manifest, "openmm_potential", structure="mutant", stage="after")
    sasa = _claim(manifest, "mutated_residue_sasa", structure="mutant")
    count = _claim(manifest, "contact_count", structure="wild_type_reference")
    for claim in (potential, sasa, count):
        assert rep.validate_mutation_model_claim(run, handle, copy.deepcopy(claim)) == claim
    wild_after = _claim(manifest, "openmm_potential", structure="wild_type_reference", stage="after")
    value = potential["exact_value"]
    wrong = {
        "binding_mismatch": [
            {**potential, "exact_value": value + 1.0, "rendered_value": _half_up(value + 1.0)},
            {**potential, "rendered_value": f"{value:.1f}"},
            {**potential, "rendered_value": rep.render_two_decimals(value + 0.01)},
            {**potential, "rounding": "area_2dp"},
            {**potential, "unit": "kJ"},
            {**sasa, "rendered_value": f"{sasa['exact_value']:.3f}"},
            {**count, "exact_value": count["exact_value"] + 1, "rendered_value": str(count["exact_value"] + 1)},
            {**potential, "exact_value": wild_after["exact_value"], "rendered_value": wild_after["rendered_value"]},
        ],
        "difference_not_allowed": [
            {**potential, "statement_id": "openmm_potential_difference"},
            {**potential, "quantity": "openmm_potential_change_kJ_mol"},
            {**potential, "operation": "after_kJ_mol - before_kJ_mol (delta)"},
            {**potential, "operation": "mutant minus wild_type_reference"},
            {**sasa, "quantity": "sasa 차이"},
            {**count, "statement_id": "contact_count_difference"},
        ],
        "docking_score_not_allowed": [
            {**potential, "source_kind": "docking_result", "source_schema": "docking_result@1"},
            {**potential, "statement_id": "docking_score", "unit": "kcal/mol"},
            {**potential, "field_path": "docking_pairs[0].mutant.score_kcal_mol"},
        ],
        "evidence_kind_mismatch": [
            {**potential, "evidence_kind": "reference_value"},
            {**potential, "reference": {"note": "참조 스냅샷 값, 계산 아님"}},
        ],
        "statement_not_allowed": [{**potential, "statement_id": "stability"}],
        "field_rule": [
            {**count, "field_path": "structures.wild_type_reference.sasa.value_A2"},
            {**potential, "field_path": "comparison.protonation_difference_count"},
            {**_claim(manifest, "added_heavy_atom_count"),
             "field_path": "structures.wild_type_reference.added_heavy_atoms"},
        ],
        "source_kind_mismatch": [
            {**count, "source_kind": "mutation_candidate_set", "source_schema": "mutation_candidate_set@1",
             "source_handle": world["candidate_set"], "source_sha256": world["candidate_set"].rsplit("/", 1)[-1]},
        ],
        "source_mismatch": [
            {**count, "source_handle": world["other_model"],
             "source_sha256": world["other_model"].rsplit("/", 1)[-1]},
            {**count, "source_sha256": "0" * 64},
        ],
        "field_not_allowed": [
            {**count, "row_selector": {"structure": "mutant"}},
        ],
    }
    for reason, claims in wrong.items():
        for claim in claims:
            with pytest.raises(EvidenceError, match=reason):
                rep.validate_mutation_model_claim(run, handle, claim)


def test_report_from_another_run_wrong_kind_or_unpublished_model_is_refused(client, world, tmp_path, monkeypatch):
    rid = world["rid"]
    side_object = _stored(world)["structures"]["mutant"]["structure_object"]
    for handle in (world["other_model"], side_object, world["structure"]):
        response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
        assert response.status_code in (404, 422), (handle, response.text)
        if response.status_code == 422:
            assert response.json()["detail"]["error"] == "report_evidence_invalid"
    # LABELED TEST FABRICATION: a model object with no completed job publication, in an events-only copy.
    root, copied = _copy_run(world, tmp_path)
    content = copied.store.load(world["model"])
    with copied._owner():
        forged = copied.store.put(K.KIND, K.SCHEMA, {**content, "parameters": {**content["parameters"],
                                                                                "seed": 9}}).handle
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    other = TestClient(api_module.app, base_url="http://127.0.0.1")
    response = other.post(f"/runs/{rid}/method_reports", json={"result_handle": forged})
    assert response.status_code == 422 and "mutation_model_invalid" in response.text


# --- reopen -------------------------------------------------------------------------------------------------------------

def test_tampered_reports_are_rejected_on_reopen(world, tmp_path, monkeypatch):
    root, run = _copy_run(world, tmp_path)
    created = rep.build_mutation_model_report(run, world["model"])
    manifest, markdown = created["manifest"], created["markdown"]
    potential = _claim(manifest, "openmm_potential", structure="mutant", stage="after")

    def bump(forged):
        claim = next(c for c in forged["claims"] if c == potential)
        value = potential["exact_value"] + 0.5
        claim.update(exact_value=value, rendered_value=_half_up(value))

    def difference(forged):
        forged["claims"].append({**potential, "statement_id": "openmm_potential_difference",
                                 "operation": "mutant - wild_type_reference"})

    def docking(forged):
        forged["claims"].append({**potential, "statement_id": "docking_score", "source_kind": "docking_result",
                                 "source_schema": "docking_result@1", "unit": "kcal/mol"})

    def first_changed(forged):
        forged["limitations"][0] = K.L1.replace("최대 50회", "최대 100회")

    forged = {
        "wrong value": _forge(run, manifest, markdown, bump),
        "difference claim": _forge(run, manifest, markdown, difference),
        "docking score": _forge(run, manifest, markdown, docking),
        "forbidden word line": _forge(run, manifest, markdown.replace("## Limitations", "안정성이 개선된 변이다.\n\n"
                                                                      "## Limitations"), lambda _f: None),
        "에너지 label": _forge(run, manifest, markdown.replace("OpenMM 전위,", "OpenMM 에너지,"), lambda _f: None),
        "altered limitation": _forge(run, manifest, markdown.replace(K.L1, K.L1.replace("최대 50회", "최대 100회")),
                                     first_changed),
        "dropped limitation": _forge(run, manifest, markdown, lambda f: f["limitations"].pop()),
        "reordered limitations": _forge(run, manifest, markdown,
                                        lambda f: f["limitations"].insert(0, f["limitations"].pop())),
        "missing claim": _forge(run, manifest, markdown, lambda f: f["claims"].pop()),
        "summary edited": _forge(run, manifest, markdown,
                                 lambda f: f["structures"]["mutant"]["contacts"].update(count=0)),
        "candidate edited": _forge(run, manifest, markdown, lambda f: f["candidate"].update(to="A")),
        "other model": _forge(run, manifest, markdown, lambda f: f.update(result_handle=world["other_model"])),
    }
    for name, handle in forged.items():
        with pytest.raises((EvidenceError, KeyError, ValueError)):
            rep.saved_mutation_model_report(run, handle)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    for name, handle in forged.items():
        assert _selected(client, handle, world["rid"]).status_code == 422, name
    assert _selected(client, created["handle"], world["rid"]).status_code == 200
    assert client.get(f"/runs/{world['rid']}/reports").status_code == 422


def test_reopen_reads_stored_objects_only(client, world, monkeypatch):
    created = _report(client, world["model"], world["rid"])
    monkeypatch.setattr(bundle, "require_ready", _forbid)
    monkeypatch.setattr(bundle, "model_content", _forbid)
    monkeypatch.setattr(openmm_method, "preflight", _forbid)
    monkeypatch.setattr(openmm_method, "dependencies", _forbid)
    monkeypatch.setattr(JobQueue, "_supervise", _forbid)
    monkeypatch.setattr(Run, "call", _forbid)
    monkeypatch.setattr(subprocess, "Popen", _forbid)
    api_module.RUNS.clear()
    assert _selected(client, created["handle"], world["rid"]).json()["markdown"] == created["markdown"]


def test_read_and_report_modules_import_no_engine():
    for name in ("mutation_model_reports.py", "mutation_model_reads.py"):
        tree = ast.parse((MW / name).read_text())
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        # The docking-pairs read (T7) needs job states, so only that module may import the queue (no engine).
        allowed = {"mutation_model_reads.py": {"jobs"}}.get(name, set())
        for forbidden in ("openmm", "pdbfixer", "freesasa", "gemmi", "numpy", "subprocess", "socket", "httpx",
                          "requests", "urllib", "tools", "jobs"):
            if forbidden in allowed:
                continue
            assert not any(module == forbidden or module.startswith(forbidden + ".") or
                           module.endswith("." + forbidden) for module in imported), (name, forbidden)
