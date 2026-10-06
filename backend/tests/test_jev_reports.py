"""M24 T5 report ``jev_choice`` (``mw.jev_reports``; spec .dryforge/spec.md 8).

Inputs are the REAL template runs of ``jev_send_fixture`` (public 1UBQ M20 set, real M17 set, real
``build_jev_projection`` objects) and proposals stored by the real send path (``jev_sends.run_send`` through a
``jev_send_fixture.Fake`` gate: ``httpx.MockTransport``, inert sentinel credential; no socket, no ``.env``). Provider
replies are fixture values. Stored reports, proposals and claims edited by hand are fault injection, marked where used.
"""
from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient
from jev_send_fixture import Fake, clone, no_secret, reopen, reply, run_bytes, send, templates

from mw import jev_constants as J
from mw import jev_reports as R
from mw import jev_sends as S
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.mutation_reports import build_mutation_report, saved_mutation_report
from mw.reports import EvidenceError, _md, _ref

PROBABILITY_VALUES = (0.4321, 0.1234)   # fixture reply values, never a provider output
MANIFEST_KEYS = {"schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle",
                 "result_schema", "result_sha256", "external_response", "kind", "method_version", "label",
                 "scientific_result", "send", "source", "projection", "question", "requested_model", "served_model",
                 "arrival", "limitations", "chosen", "claims", "provenance", "evidence_statement", "snapshot",
                 "markdown_handle"}
FORBIDDEN = ("순위", "추천", "최적", "개선", "예측", "유망", "좋은", "나쁜", "안전", "점수", "에너지", "활성", "친화도",
             "안정성", "ΔΔG", "winner", "best", "rank", "recommend", "결합", "important", "affinity", "중요", "기능")


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return templates(tmp_path_factory.getbasetemp() / "jev_send_templates")


@pytest.fixture(autouse=True)
def no_active_sends():
    S.ACTIVE_SENDS.clear()
    yield
    assert not S.ACTIVE_SENDS
    S.ACTIVE_SENDS.clear()


def _sent(base, tmp_path, which="mutation", responder=None, interrupt=None):
    world = clone(base[which], tmp_path / "runs")
    run = world["run"]
    S.set_consent(run, True)
    prefix = J.ALIAS_PREFIXES[which]

    def answer(request):
        if interrupt == "consent_off":
            S.set_consent(run, False)
        elif interrupt == "cancel":
            run.cancel()
        return (responder or (lambda: reply(f"{prefix}02", confidence=0.6789, probabilities={
            f"{prefix}01": PROBABILITY_VALUES[0], f"{prefix}02": PROBABILITY_VALUES[1]})))()

    record = send(world, Fake(answer))
    assert record["status"] == "completed", record
    return world, record


def _claims(manifest):
    return {claim["statement_id"]: claim for claim in manifest["claims"]}


def _forge(run, manifest, markdown):
    """Fault injection: store an edited report and its creation event the way the builder does."""
    md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                       produced_by="forged", summary={"result_handle": manifest["result_handle"]})
    manifest = {**manifest, "markdown_handle": md.handle}
    report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest, produced_by="forged",
                           summary={"result_handle": manifest["result_handle"], "analysis_type": R.ANALYSIS_TYPE,
                                    "status": "complete"})
    run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                      result_handle=manifest["result_handle"], snapshot_event_seq=manifest["snapshot"]["event_seq"])
    return report.handle


# ---------------------------------------------------------------- manifest, claims and Markdown


@pytest.mark.parametrize("which", ["mutation", "ligand"])
def test_the_report_cites_the_proposal_with_two_evidence_kinds_and_no_probabilities(which, base, tmp_path):
    world, record = _sent(base, tmp_path, which)
    run, handle = world["run"], record["choice_handle"]
    choice = S.load_choice(run, handle)
    events_before = len(list(run.events.read()))
    built = R.build_jev_report(run, handle)
    manifest, markdown = built["manifest"], built["markdown"]
    assert set(manifest) == MANIFEST_KEYS
    assert (manifest["schema"], manifest["analysis_type"], manifest["status"], manifest["render_version"],
            manifest["generation_mode"]) == ("method_report_manifest@1", "jev_choice", "complete",
                                              "jev_choice_markdown@1", "local_rules_no_egress")
    assert manifest["external_response"] == {"kind": "jev_choice", "scientific_evidence": False}
    assert (manifest["result_handle"], manifest["result_schema"], manifest["kind"]) == (handle, J.CHOICE_SCHEMA, which)
    assert manifest["limitations"] == choice["limitations"] == J.limitations_for(which, False)
    assert manifest["chosen"] == {"local_ref": choice["answer"]["local_ref"],
                                  "local_display": choice["answer"]["local_display"]}
    claims = _claims(manifest)
    assert {c["evidence_kind"] for c in manifest["claims"]} == {"computed", "model_response"}
    assert {k for k, c in claims.items() if c["evidence_kind"] == "computed"} == {
        "selection_count", "body_bytes", "usage_input_tokens", "usage_output_tokens", "usage_cost"}
    assert {k for k, c in claims.items() if c["evidence_kind"] == "model_response"} == {
        "choice_alias", "confidence", "served_model", "arrival_late"}
    expected = {"selection_count": len(choice["selection"]), "body_bytes": choice["projection"]["body_bytes"],
                "usage_input_tokens": 3000, "usage_output_tokens": 20, "usage_cost": 0.001,
                "choice_alias": f"{J.ALIAS_PREFIXES[which]}02", "confidence": 0.6789,
                "served_model": J.SERVED_SNAPSHOT, "arrival_late": False}
    assert {key: claim["exact_value"] for key, claim in claims.items()} == expected
    for claim in manifest["claims"]:
        assert claim["source_handle"] == handle and claim["source_schema"] == J.CHOICE_SCHEMA
        assert (claim["reference"] is None) is (claim["evidence_kind"] == "computed")
        if claim["evidence_kind"] == "model_response":
            assert claim["reference"] == {"note": R.MODEL_RESPONSE_NOTE, "proposal_handle": handle}
        assert claim["rendered_value"] in markdown or _md(claim["rendered_value"]) in markdown
    for sentence in manifest["limitations"]:
        assert f"\n{sentence}\n" in markdown
    display = choice["answer"]["local_display"]
    if which == "ligand":
        assert _md(display["smiles"]) in markdown
    else:
        assert _md(_ref(display["residue"])) in markdown and f"{display['from']} → {display['to']}" in markdown
    dumped = canonical_json(manifest).decode()
    assert '"probabilities"' not in dumped and "answer.probabilities" not in dumped   # no such key or field
    for value in PROBABILITY_VALUES:
        assert str(value) not in dumped and str(value) not in markdown
    assert set(manifest["snapshot"]) == {"event_seq", "time_utc", "run_egress_mode", "science_consent", "budget"}
    assert manifest["snapshot"]["science_consent"] is True and manifest["snapshot"]["run_egress_mode"] == "local_only"
    created = [e for e in run.events.read()][events_before:]
    assert [e["type"] for e in created] == ["object_created", "object_created", "method_report_created"]
    assert not [e for e in created if e["type"] == "egress"]
    saved = R.saved_jev_report(run, built["handle"])
    assert saved == built
    assert no_secret(manifest, markdown) and b"sentinel_m24" not in run_bytes(run)


def test_missing_confidence_and_unknown_usage_get_words_not_numbers(base, tmp_path):
    world, record = _sent(base, tmp_path, responder=lambda: reply("m01", usage=None))
    built = R.build_jev_report(world["run"], record["choice_handle"])
    claims = _claims(built["manifest"])
    assert set(claims) == {"selection_count", "body_bytes", "choice_alias", "served_model", "arrival_late"}
    markdown = built["markdown"]
    assert markdown.count("알 수 없음") >= 3 and "보고 없음" in markdown
    assert R.saved_jev_report(world["run"], built["handle"]) == built


@pytest.mark.parametrize("interrupt, reason", [("consent_off", "consent_off"), ("cancel", "run_cancelled")])
def test_a_late_reply_is_marked_with_j7(interrupt, reason, base, tmp_path):
    world, record = _sent(base, tmp_path, interrupt=interrupt)
    assert (record["late"], record["late_reason"]) == (True, reason)
    built = R.build_jev_report(world["run"], record["choice_handle"])
    claims = _claims(built["manifest"])
    assert claims["arrival_late"]["exact_value"] is True
    assert claims["arrival_late_reason"]["exact_value"] == reason
    assert built["manifest"]["limitations"][-1] == J.J7 and f"\n{J.J7}\n" in built["markdown"]
    assert built["manifest"]["snapshot"]["science_consent"] is (interrupt != "consent_off")
    assert R.saved_jev_report(world["run"], built["handle"]) == built


# ---------------------------------------------------------------- interpretation wording


@pytest.mark.parametrize("word", FORBIDDEN)
def test_forbidden_wording_is_refused_on_template_lines(word):
    with pytest.raises(EvidenceError):
        R.check_no_interpretation(f"- 고른 별칭: {word}")


def test_the_fixed_sentences_are_exempt_and_slot_values_are_not_checked(base, tmp_path):
    for sentence in J.STATEMENTS.values():
        R.check_no_interpretation(sentence)
    assert R.INTERPRETIVE.search(J.J1) and R.INTERPRETIVE.search(J.J5)   # exempt only as whole fixed lines
    with pytest.raises(EvidenceError):
        R.check_no_interpretation(J.J1 + " ")
    world, record = _sent(base, tmp_path, "ligand")
    manifest = R.build_jev_report(world["run"], record["choice_handle"])["manifest"]
    edited = copy.deepcopy(manifest)   # fault injection: an identifier that spells a forbidden word sits in a slot
    edited["chosen"]["local_display"]["smiles"] = "CCbestrankCC"
    assert "bestrankCC" in R.render_jev_report(edited)
    edited = copy.deepcopy(manifest)   # fault injection: a template text with an interpretive word
    edited["evidence_statement"] += " This is the best candidate."
    with pytest.raises(EvidenceError, match="interpretive"):
        R.render_jev_report(edited)


# ---------------------------------------------------------------- evidence kinds never mix


def test_mixed_evidence_kinds_and_wrong_fields_are_refused(base, tmp_path):
    world, record = _sent(base, tmp_path)
    manifest = R.build_jev_report(world["run"], record["choice_handle"])["manifest"]
    claims = _claims(manifest)
    for claim in manifest["claims"]:
        assert R.match_claim(manifest["claims"], copy.deepcopy(claim)) == claim
    cases = {
        "computed_cites_model_field": {**claims["selection_count"], "field_path": "answer.confidence"},
        "model_cites_computed_field": {**claims["confidence"], "field_path": "usage.cost"},
        "model_claim_as_computed": {**claims["confidence"], "evidence_kind": "computed", "reference": None},
        "computed_claim_as_model": {**claims["usage_cost"], "evidence_kind": "model_response",
                                    "reference": claims["confidence"]["reference"]},
        "probability_field": {**claims["confidence"], "field_path": "answer.probabilities"},
        "unknown_statement": {**claims["confidence"], "statement_id": "probabilities"},
        "computed_with_note": {**claims["body_bytes"], "reference": claims["confidence"]["reference"]},
        "model_without_note": {**claims["served_model"], "reference": None},
        "changed_value": {**claims["usage_cost"], "exact_value": 0.002, "rendered_value": "0.002"},
        "other_source": {**claims["body_bytes"], "source_handle": world["projection"]},
        "extra_key": {**claims["body_bytes"], "rank": 1},
    }
    for name, proposed in cases.items():
        with pytest.raises(EvidenceError):
            R.match_claim(manifest["claims"], proposed)
            pytest.fail(name)


@pytest.mark.parametrize("edit", [
    "drop_claim", "duplicate_claim", "swap_kind", "computed_cites_model_field", "changed_value", "markdown",
    "probabilities_key", "scientific_evidence", "science_consent", "limitations", "chosen", "snapshot_seq"])
def test_reopening_refuses_an_edited_report(edit, base, tmp_path):
    world, record = _sent(base, tmp_path)
    run = world["run"]
    built = R.build_jev_report(run, record["choice_handle"])
    manifest, markdown = copy.deepcopy(built["manifest"]), built["markdown"]
    claims = manifest["claims"]
    index = next(i for i, c in enumerate(claims) if c["statement_id"] == "confidence")
    if edit == "drop_claim":
        claims.pop(index)
    elif edit == "duplicate_claim":
        claims.append(copy.deepcopy(claims[index]))
    elif edit == "swap_kind":
        claims[index].update(evidence_kind="computed", reference=None)
    elif edit == "computed_cites_model_field":
        claims[0]["field_path"] = "answer.choice_alias"
    elif edit == "changed_value":
        claims[index].update(exact_value=0.9, rendered_value="0.9")
    elif edit == "markdown":
        markdown = markdown.replace("응답 모델", "응답  모델")
    elif edit == "probabilities_key":
        manifest["probabilities"] = {"m01": 0.5}
    elif edit == "scientific_evidence":
        manifest["external_response"]["scientific_evidence"] = True
    elif edit == "science_consent":
        manifest["snapshot"]["science_consent"] = False
    elif edit == "limitations":
        manifest["limitations"] = manifest["limitations"][:-1]
    elif edit == "chosen":
        manifest["chosen"]["local_display"]["to"] = "W"
    else:
        manifest["snapshot"]["event_seq"] = record["approved_event_seq"]
    handle = _forge(run, manifest, markdown)
    with pytest.raises(EvidenceError):
        R.saved_jev_report(run, handle)
    assert R.saved_jev_report(run, built["handle"]) == built


def test_a_proposal_without_its_send_chain_is_refused(base, tmp_path):
    world, record = _sent(base, tmp_path)
    run = world["run"]
    content = copy.deepcopy(run.store.load(record["choice_handle"]))
    content["answer"]["confidence"] = 0.5   # fault injection: a well-formed proposal no send outcome names
    forged = run.store.put(J.CHOICE_KIND, J.CHOICE_SCHEMA, content).handle
    assert S.load_choice(run, forged) == content          # it passes the object check on its own
    with pytest.raises(EvidenceError, match="outcome"):
        R.build_jev_report(run, forged)
    with pytest.raises(EvidenceError):
        R.build_jev_report(run, world["projection"])      # not a proposal


# ---------------------------------------------------------------- recovery, API registration, existing kinds


def test_the_report_reopens_from_an_events_only_copy(base, tmp_path):
    world, record = _sent(base, tmp_path)
    built = R.build_jev_report(world["run"], record["choice_handle"])
    copy_run = reopen(world, tmp_path / "events_only")
    assert R.saved_jev_report(copy_run, built["handle"]) == built


def test_api_registration_and_existing_report_kinds_unchanged(base, tmp_path, monkeypatch):
    world, record = _sent(base, tmp_path)
    run, rid = world["run"], world["run_id"]
    mutation_before = build_mutation_report(run, world["source"])
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    made = client.post(f"/runs/{rid}/method_reports", json={"result_handle": record["choice_handle"]})
    assert made.status_code == 201, made.text
    mutation_after = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["source"]}).json()
    assert mutation_after["markdown"] == mutation_before["markdown"]
    assert saved_mutation_report(run, mutation_before["handle"]) == mutation_before
    rows = {row["handle"]: row["analysis_type"] for row in client.get(f"/runs/{rid}/reports").json()}
    assert rows == {mutation_before["handle"]: "mutation_candidates", made.json()["handle"]: "jev_choice",
                    mutation_after["handle"]: "mutation_candidates"}
    for params, status in (({"result_handle": record["choice_handle"], "filters": {}}, 422),
                           ({"result_handle": world["projection"]}, 422),
                           ({"result_handle": f"obj://run_other/jev_choice/{'0' * 64}"}, 422)):
        refused = client.post(f"/runs/{rid}/method_reports", json=params)
        assert refused.status_code == status and refused.json()["detail"]["error"] == "report_evidence_invalid"
    forged = copy.deepcopy(made.json()["manifest"])   # fault injection: an edited stored report
    forged["claims"][0]["exact_value"] += 1
    handle = _forge(run, forged, made.json()["markdown"])
    for path in ("/reports/selected", "/reports/download"):
        response = client.get(f"/runs/{rid}{path}", params={"handle": handle})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"
    listed = client.get(f"/runs/{rid}/reports")
    assert listed.status_code == 422 and json.loads(listed.text)["detail"]["error"] == "report_evidence_invalid"
