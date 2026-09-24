"""M5 workflow, exact evidence, recovery and HTTP artifact checks."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mw.core.errors import FailureClass, Fix, ToolFailure
from mw.core.handles import canonical_json
from mw.reports import (
    EvidenceError,
    build_inspection_report,
    render_number,
    saved_report,
    validate_claim,
    validate_statement,
)
from mw.runtime.guards import BudgetLimits
from mw.workflows import VERSION, InspectionRequest, inspect_complex, normalize_request
from mw.workspace import load_config, new_run

FIX = Path(__file__).parent / "fixtures/mini_complex.pdb"


def request(raw, **extra):
    return {"upload_id": f"upload://run_report/{hashlib.sha256(raw).hexdigest()}.pdb", "model_index": 0, **extra}


def run_at(path):
    return new_run(path, run_id="run_report", dry_run=False)


def measured(path, cutoff=4.0):
    run = run_at(path)
    raw = FIX.read_bytes()
    outcome = inspect_complex(run, request(raw, cutoff_A=cutoff), source_bytes=raw, source_format="pdb")
    assert outcome["status"] == "complete"
    return run, outcome


def test_real_workflow_resume_and_provenance(tmp_path):
    run, first = measured(tmp_path)
    steps = [e for e in run.events.read() if e["type"] == "workflow_step_completed"]
    assert [e["step"] for e in steps] == ["load", "prepare", "interactions"]
    assert all(e["call_id"] and e["output_handle"] for e in steps)
    count = sum(e["type"] == "tool_called" for e in run.events.read())
    budget = run.budget_snapshot()["expensive_calls"]
    reopened = run_at(tmp_path)
    raw = FIX.read_bytes()
    again = inspect_complex(reopened, request(raw))  # completed load resumes without upload bytes
    assert again["workflow_id"] == first["workflow_id"] and again["outputs"] == first["outputs"]
    assert sum(e["type"] == "tool_called" for e in reopened.events.read()) == count
    reordered = inspect_complex(reopened, request(raw, types=["hydrophobic_contact", "contact", "polar_contact"]))
    assert reordered["workflow_id"] == first["workflow_id"] and reordered["outputs"] == first["outputs"]
    assert sum(e["type"] == "tool_called" for e in reopened.events.read()) == count
    assert reopened.budget_snapshot()["expensive_calls"] == budget
    with pytest.raises(ValueError):
        InspectionRequest.model_validate(request(raw, waters="keep_bridging"))
    assert not any(e["type"] == "egress" for e in reopened.events.read())


def test_resume_missing_step_without_latest_scan(tmp_path, monkeypatch):
    run = run_at(tmp_path)
    raw = FIX.read_bytes()
    original = run.call
    blocked = True

    def fail_once(tool, *args, **kwargs):
        nonlocal blocked
        if tool == "compute_interactions" and blocked:
            blocked = False
            raise ToolFailure(FailureClass.transient, "fixture interruption")
        return original(tool, *args, **kwargs)

    monkeypatch.setattr(run, "call", fail_once)
    first = inspect_complex(run, request(raw), source_bytes=raw, source_format="pdb")
    assert first["status"] == "failed" and set(first["outputs"]) == {"load", "prepare"}
    count = sum(e["type"] == "tool_called" for e in run.events.read())
    monkeypatch.setattr(run, "call", original)
    final = inspect_complex(run, request(raw), source_bytes=raw, source_format="pdb")
    assert final["status"] == "complete"
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == count + 1
    assert not any(e["type"] == "report_created" for e in run.events.read())


def test_typed_workflow_outcomes_from_runtime(tmp_path, monkeypatch):
    raw = FIX.read_bytes()
    run = run_at(tmp_path / "failure")
    source = run.call("load_structure", {"source": str(FIX)})

    def fail_prepare(ctx, **kwargs):
        raise ToolFailure(FailureClass.input_invalid, "fixture preparation failure",
                          fix=Fix(tool="prepare_structure", args={"structure": source.handle}),
                          detail={"reason_code": "fixture_policy", "unrelated": "/private/secret"})

    monkeypatch.setitem(run.registry.impls, "prepare_structure", fail_prepare)
    failed = inspect_complex(run, {"input_handle": source.handle})
    assert failed["status"] == "failed" and failed["failed_step"] == "prepare"
    assert failed["failed_tool"] == "prepare_structure" and failed["outputs"] == {}
    assert failed["failure"] == {"classification": "input_invalid", "message": "fixture preparation failure",
                                 "fix": {"tool": "prepare_structure", "args": {"structure": source.handle}},
                                 "detail": {"reason_code": "fixture_policy"}}
    assert failed["causal"]["call_id"] and failed["causal"]["event_seq"]
    assert any(e["type"] == "tool_failed" and e["seq"] == failed["causal"]["event_seq"]
               for e in run.events.read())
    assert "/private/secret" not in str(failed)

    budget = run_at(tmp_path / "budget")
    original = budget.call

    def lower_limit_after_load(tool, args, **kwargs):
        result = original(tool, args, **kwargs)
        if tool == "load_structure":
            budget.update_limits(BudgetLimits(wall_clock_s=0.0001))
        return result

    monkeypatch.setattr(budget, "call", lower_limit_after_load)
    checkpoint = inspect_complex(budget, request(raw), source_bytes=raw, source_format="pdb")
    assert checkpoint["status"] == "checkpoint" and set(checkpoint["outputs"]) == {"load"}
    assert checkpoint["failed_step"] == "prepare" and checkpoint["failed_tool"] == "prepare_structure"
    assert checkpoint["approval"]["gate"] == "budget"
    assert checkpoint["approval"]["tool"] == "prepare_structure"
    assert checkpoint["approval"]["args"]["structure"] == checkpoint["outputs"]["load"]
    assert checkpoint["causal"]["event_seq"] and checkpoint["causal"]["call_id"] is None
    assert any(e["type"] == "checkpoint" and e["seq"] == checkpoint["causal"]["event_seq"]
               for e in budget.events.read())

    config = load_config()
    config["runtime"]["loop_guards"]["repeated_call_hash"] = 0
    loop_run = new_run(tmp_path / "loop", run_id="run_report", dry_run=False, config=config)
    loop_source = loop_run.call("load_structure", {"source": str(FIX)})
    stopped = inspect_complex(loop_run, {"input_handle": loop_source.handle})
    assert stopped["status"] == "checkpoint" and stopped["failed_step"] == "prepare"
    assert stopped["loop_stop"] == {"reason": "repeated_call_hash",
                                   "detail": {"branch_id": stopped["workflow_id"]}}
    assert stopped["causal"]["call_id"] is None and stopped["causal"]["event_seq"]

    cancelled_run = run_at(tmp_path / "cancel")
    cancelled_source = cancelled_run.call("load_structure", {"source": str(FIX)})
    cancelled_run.cancel()
    cancelled = inspect_complex(cancelled_run, {"input_handle": cancelled_source.handle})
    assert cancelled["status"] == "cancelled" and cancelled["failed_step"] == "prepare"
    assert cancelled["cancellation"] == {"status": "cancelled", "reason": "run_cancelled"}
    assert cancelled["causal"]["call_id"] is None and cancelled["causal"]["event_seq"]
    assert any(e["type"] == "run_cancelled" and e["seq"] == cancelled["causal"]["event_seq"]
               for e in cancelled_run.events.read())


def test_foreign_progress_fails_before_later_calls(tmp_path):
    run = run_at(tmp_path)
    raw = FIX.read_bytes()
    a = tmp_path / "A.pdb"
    b = tmp_path / "B.pdb"
    a.write_bytes(raw)
    b.write_bytes(b"REMARK   DIFFERENT INPUT B\n" + raw)
    loaded_a = run.call("load_structure", {"source": str(a)})
    loaded_b = run.call("load_structure", {"source": str(b)})
    prepared_b = run.call("prepare_structure", {"structure": loaded_b.handle})
    req = InspectionRequest(input_handle=loaded_a.handle)
    normalized = normalize_request(req)
    workflow_id = "workflow_" + hashlib.sha256(canonical_json(
        {"version": VERSION, "run_id": run.run_id, "request": normalized})).hexdigest()
    call = next(e for e in run.events.read() if e["type"] == "tool_succeeded" and
                e["output"]["handle"] == prepared_b.handle)
    run.events.append("workflow_started", workflow_id=workflow_id, version=VERSION,
                      request=normalized, driver_mode="finite_rules", branch_id=workflow_id)
    run.events.append("workflow_step_completed", workflow_id=workflow_id, version=VERSION,
                      step="prepare", tool="prepare_structure", call_id=call["call_id"],
                      source_call_id=call["call_id"], output_handle=prepared_b.handle, null_result=False)
    before = sum(e["type"] == "tool_called" for e in run.events.read())
    with pytest.raises(ValueError, match="corrupt workflow"):
        inspect_complex(run, req)
    assert sum(e["type"] == "tool_called" for e in run.events.read()) == before


def test_own_cache_observation_resumes_from_events(tmp_path):
    run = run_at(tmp_path)
    source = run.call("load_structure", {"source": str(FIX)})
    run.call("prepare_structure", {"structure": source.handle, "waters": "strip_all"})
    first = inspect_complex(run, {"input_handle": source.handle})
    assert first["status"] == "complete"
    cached = next(e for e in run.events.read() if e["type"] == "workflow_step_completed" and
                  e["step"] == "prepare")
    observation = next(e for e in run.events.read() if e["seq"] == cached["child_event_seq"])
    assert observation["type"] == "cache_hit" and observation["observation_id"] == cached["call_id"]
    before = sum(e["type"] == "tool_called" for e in run.events.read())
    reopened = run_at(tmp_path)
    again = inspect_complex(reopened, {"input_handle": source.handle})
    assert again["outputs"] == first["outputs"]
    assert sum(e["type"] == "tool_called" for e in reopened.events.read()) == before


def test_paired_subject_links_require_supported_science_types(tmp_path):
    run, outcome = measured(tmp_path)
    manifest = build_inspection_report(run, outcome["outputs"]["interactions"])["manifest"]
    selected = next(c for c in manifest["claims"] if c["statement_id"] == "selected_model")
    counted = next(c for c in manifest["claims"] if c["statement_id"] == "contact_count")
    prepared = outcome["outputs"]["prepare"]
    interaction = outcome["outputs"]["interactions"]
    for kind, schema in (("job_lifecycle", "job_lifecycle@1"),
                         ("prepared_structure", "prepared_structure@999")):
        fake_prepared = run.store.put(kind, schema, run.store.load(prepared),
                                      produced_by="test_fixture", summary={})
        altered = copy.deepcopy(run.store.load(interaction))
        altered["structure"] = fake_prepared.handle
        fake_interaction = run.store.put("interaction_set", "interaction_set@1", altered,
                                         produced_by="test_fixture", summary={})
        links = {"prepared_handle": fake_prepared.handle, "interaction_handle": fake_interaction.handle}
        with pytest.raises(EvidenceError):
            validate_claim(run.store, {**selected, "subject": links})
        other = copy.deepcopy(counted)
        other["source_handle"] = fake_interaction.handle
        other["source_sha256"] = fake_interaction.handle.rsplit("/", 1)[-1]
        other["subject"] = {**counted["subject"], **links}
        with pytest.raises(EvidenceError):
            validate_claim(run.store, other)
    wrong_interaction = run.store.put("interaction_set", "interaction_set@999",
                                      run.store.load(interaction), produced_by="test_fixture", summary={})
    with pytest.raises(EvidenceError):
        validate_claim(run.store, {**selected, "subject": {
            "prepared_handle": prepared, "interaction_handle": wrong_interaction.handle}})


def test_selection_absence_and_measured_empty(tmp_path):
    raw = FIX.read_bytes()
    second_ligand = b"HETATM   21  C1  DRG D 303      40.000  40.000  40.000  1.00 20.00           C\n"
    two = raw.replace(b"END\n", second_ligand + b"END\n")
    run = run_at(tmp_path)
    ambiguous = inspect_complex(run, request(two), source_bytes=two, source_format="pdb")
    assert ambiguous["status"] == "needs_selection" and len(ambiguous["choices"]) == 2
    assert "interactions" not in ambiguous["outputs"]
    chosen = inspect_complex(run, request(two, ligand=ambiguous["choices"][0]), source_bytes=two, source_format="pdb")
    assert chosen["status"] == "complete" and chosen["scientific_null"] is False
    no_ligand = b"\n".join(line for line in raw.splitlines() if not line.startswith(b"HETATM")) + b"\n"
    absent = inspect_complex(run, request(no_ligand), source_bytes=no_ligand, source_format="pdb")
    assert absent["status"] == "no_ligand" and "interactions" not in absent["outputs"]
    empty = inspect_complex(run, request(raw, cutoff_A=2.5), source_bytes=raw, source_format="pdb")
    assert empty["status"] == "complete" and empty["scientific_null"] is True
    report = build_inspection_report(run, empty["outputs"]["interactions"])["manifest"]
    assert report["counts"]["atom_pairs"] == report["counts"]["contacting_residues"] == 0
    assert report["minimum_distance_A"] is None and report["rows"] == []


def test_exact_claim_binding_rounding_and_closed_language(tmp_path):
    run, outcome = measured(tmp_path)
    report = build_inspection_report(run, outcome["outputs"]["interactions"])["manifest"]
    distances = [c for c in report["claims"] if c["statement_id"] == "contact_distance"]
    claim = distances[0]
    assert validate_claim(run.store, claim).rendered_value == claim["rendered_value"]
    mismatches = [
        {"source_handle": report["prepared_handle"]}, {"source_sha256": "0" * 64},
        {"row_index": distances[1]["row_index"]}, {"field_path": "parameters.cutoff_A"},
        {"unit": "REU"}, {"quantity": "atom_pairs"},
        {"subject": {**claim["subject"], "protein_atom": "wrong"}},
        {"subject": {**claim["subject"], "residue": distances[3]["subject"]["residue"]}},
        {"subject": {**claim["subject"], "ligand": {**claim["subject"]["ligand"], "seq_auth": 99}}},
        {"subject": {**claim["subject"], "prepared_handle": "obj://run_report/prepared_structure/" + "0" * 64}},
        {"exact_value": claim["exact_value"] * 1.001}, {"rendered_value": "0.00"},
    ]
    for change in mismatches:
        with pytest.raises(EvidenceError):
            validate_claim(run.store, {**copy.deepcopy(claim), **change})
    # A second immutable table can contain the very same measured pair/value;
    # changing its source while retaining the selected subject is still wrong.
    second = run.call("compute_interactions", {"structure": outcome["outputs"]["prepare"],
        "ligand": claim["subject"]["ligand"], "cutoff_A": 6.0,
        "types": ["contact", "polar_contact", "hydrophobic_contact"], "engine": "geometric"})
    assert any(row["distance_A"] == claim["exact_value"] and
               row["protein_atom"] == claim["subject"]["protein_atom"] and
               row["ligand_atom"] == claim["subject"]["ligand_atom"]
               for row in run.store.load(second.handle)["rows"])
    with pytest.raises(EvidenceError):
        validate_claim(run.store, {**claim, "source_handle": second.handle,
                                   "source_sha256": second.handle.rsplit("/", 1)[-1]})
    duplicate_data = copy.deepcopy(run.store.load(outcome["outputs"]["interactions"]))
    duplicate_data["rows"] = [duplicate_data["rows"][0], duplicate_data["rows"][0]]
    duplicate = run.store.put("interaction_set", "interaction_set@1", duplicate_data)
    same_value_other_row = {**claim, "source_handle": duplicate.handle,
        "source_sha256": duplicate.sha, "subject": {**claim["subject"], "interaction_handle": duplicate.handle},
        "row_index": 1, "field_path": "rows[1].distance_A"}
    with pytest.raises(EvidenceError, match="row_fingerprint_mismatch"):
        validate_claim(run.store, same_value_other_row)
    assert render_number(2.6264474104767457, "distance_2dp") == "2.63"
    assert render_number(-0.0001, "distance_2dp") == "0.00"
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(EvidenceError):
            render_number(value, "distance_2dp")
    for predicate in ("stronger_affinity", "stabilizes", "hbond", "energy", "best_mutation"):
        with pytest.raises(EvidenceError):
            validate_statement(run.store, predicate, claim)
    plan = run.store.put("planned_call", "planned_call@1", {"energy_REU": -1.0})
    with pytest.raises(EvidenceError):
        validate_claim(run.store, {**claim, "source_handle": plan.handle,
                                   "source_kind": plan.kind, "source_schema": plan.schema_,
                                   "source_sha256": plan.sha})


def test_full_rows_aggregates_historical_and_no_latest_substitution(tmp_path):
    run, first_result = measured(tmp_path)
    first = build_inspection_report(run, first_result["outputs"]["interactions"])
    rows = first["manifest"]["rows"]
    assert len(rows) == first["manifest"]["counts"]["atom_pairs"] == 6
    assert first["manifest"]["counts"]["contacting_residues"] == 2
    assert first["manifest"]["minimum_distance_A"] == min(row["distance_A"] for row in rows)
    count = next(c for c in first["manifest"]["claims"] if c["statement_id"] == "contact_count")
    with pytest.raises(EvidenceError):
        validate_claim(run.store, {**count, "exact_value": count["exact_value"] + 1})
    raw = FIX.read_bytes().replace(b"HEADER    TEST COMPLEX", b"HEADER    OTHER STRUCTURE")
    newer = inspect_complex(run, request(raw, cutoff_A=2.5), source_bytes=raw, source_format="pdb")
    assert newer["status"] == "complete"
    historical = saved_report(run, first["handle"])
    assert historical["manifest"] == first["manifest"] and historical["markdown"] == first["markdown"]
    assert historical["manifest"]["interaction_handle"] != newer["outputs"]["interactions"]
    assert historical["manifest"]["source_handle"] != build_inspection_report(
        run, newer["outputs"]["interactions"])["manifest"]["source_handle"]
    with pytest.raises(EvidenceError):
        build_inspection_report(run, first_result["outputs"]["interactions"],
                                prepared_handle=newer["outputs"]["interactions"])


def test_events_only_exact_bytes_and_no_recomputation(tmp_path, monkeypatch):
    run, outcome = measured(tmp_path)
    artifact = build_inspection_report(run, outcome["outputs"]["interactions"])
    expected_json = json.dumps(artifact["manifest"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    expected_markdown = artifact["markdown"].encode()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    reopened = run_at(tmp_path)
    monkeypatch.setattr(reopened, "call", lambda *args, **kwargs: pytest.fail("reopen ran scientific tool"))
    restored = saved_report(reopened, artifact["handle"])
    assert restored["markdown"].encode() == expected_markdown
    assert json.dumps(restored["manifest"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() == expected_json
    assert reopened.store.load(outcome["outputs"]["interactions"])["rows"] == artifact["manifest"]["rows"]


def test_corrupt_absent_capabilities_and_private_fields(tmp_path, monkeypatch):
    run, outcome = measured(tmp_path)
    monkeypatch.setenv("REPORT_SENTINEL_KEY", "PRIVATE_SENTINEL_987654")
    run.events.append("goal", text="PRIVATE_SENTINEL_987654", context=["/private/sentinel/path"])
    run.events.append("decision", source="human", question="PRIVATE_SENTINEL_987654", answer="/private/sentinel/path")
    report = build_inspection_report(run, outcome["outputs"]["interactions"])
    exported = json.dumps(report["manifest"]) + report["markdown"]
    assert "PRIVATE_SENTINEL_987654" not in exported and "/private/sentinel/path" not in exported
    protocols = report["manifest"]["capabilities"]["protocols"]
    assert len(protocols) == 4 and all(not item["available"] and item["validation_status"] == "not_validated"
                                       for item in protocols.values())
    with pytest.raises(EvidenceError):
        build_inspection_report(run, "obj://run_report/interaction_set/" + "0" * 64)
    handle = outcome["outputs"]["interactions"]
    (run.run_dir / run.store.meta(handle)["path"]).write_bytes(b"corrupt")
    with pytest.raises(EvidenceError):
        build_inspection_report(run, handle)


def test_render_escaping_and_cancelled_workflow(tmp_path):
    from mw.reports import render_report

    run, outcome = measured(tmp_path)
    manifest = build_inspection_report(run, outcome["outputs"]["interactions"])["manifest"]
    hostile = copy.deepcopy(manifest)
    hostile["ligand"]["resname"] = '<script src="https://evil.test/x"></script>'
    hostile["rows"][0]["protein_atom"] = '![remote](https://evil.test/x.png)'
    rendered = render_report(hostile)
    assert "<script" not in rendered and "![remote](" not in rendered
    assert "&lt;script" in rendered and "\\!\\[remote\\]" in rendered
    raw = FIX.read_bytes()
    run.cancel()
    cancelled = inspect_complex(run, request(raw, cutoff_A=2.5), source_bytes=raw, source_format="pdb")
    assert cancelled["status"] == "cancelled" and "interactions" not in cancelled["outputs"]


def test_http_verified_source_download_and_confinement(tmp_path, monkeypatch):
    import mw.api.app as appmod

    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "http-runs")
    appmod.RUNS.clear()
    client = TestClient(appmod.app)
    rid = client.post("/runs", json={}).json()["run_id"]
    raw = FIX.read_bytes()
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "fixture.pdb"}, content=raw)
    assert upload.status_code == 201
    base = {"upload_id": upload.json()["upload_id"], "model_index": 0}
    for body in ({**base, "path": "/tmp/private"}, {**base, "waters": "keep_bridging"},
                 {**base, "upload_id": "upload://other/" + "0" * 64 + ".pdb"},
                 {"input_handle": "/tmp/private"}, {"input_handle": "https://example.test/structure.cif"}):
        assert client.post(f"/runs/{rid}/inspect_complex", json=body).status_code == 422
    outcome = client.post(f"/runs/{rid}/inspect_complex", json=base)
    assert outcome.status_code == 200 and outcome.json()["status"] == "complete"
    interaction = outcome.json()["outputs"]["interactions"]
    generated = client.post(f"/runs/{rid}/reports", json={"interaction_handle": interaction})
    assert generated.status_code == 201, generated.text
    handle = generated.json()["handle"]
    for fmt, expected in (("markdown", b"All measured atom pairs"), ("json", b'"exact_value"')):
        response = client.get(f"/runs/{rid}/reports/download", params={"handle": handle, "format": fmt})
        assert response.status_code == 200 and expected in response.content
        disposition = response.headers["content-disposition"]
        assert disposition.startswith('attachment; filename="protview-report-')
        assert "/" not in disposition.split("filename=", 1)[1]
        assert response.headers["x-content-type-options"] == "nosniff"
        if fmt == "json":
            exported = response.json()
            assert exported["interaction_handle"] == interaction
            assert len(exported["rows"]) == exported["counts"]["atom_pairs"]
            assert exported["minimum_distance_A"] == min(row["distance_A"] for row in exported["rows"])
        else:
            markdown = response.text
            assert f"- Atom pairs: {generated.json()['manifest']['counts']['atom_pairs']}" in markdown
            assert markdown.count("| 1 |") == 1
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": handle}).json()["markdown"] == generated.json()["markdown"]
    assert len(client.get(f"/runs/{rid}/reports").json()) == 1
    assert client.post(f"/runs/{rid}/reports", json={"interaction_handle": "obj://other/interaction_set/" + "0" * 64}).status_code == 422
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": interaction}).status_code == 422
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": handle, "format": "../../secret"}).status_code == 422
    appmod.RUNS.clear()
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": handle}).status_code == 200
