"""M15 T8 residue numbering report (``method_report_manifest@1``, ``analysis_type: "residue_numbering"``).

Every numbering map here is real ``map_residue_numbering`` output through the product HTTP path (``/commands``) on
the public 1MQ4 mmCIF and a reference FIXTURE set (``reference_fixture_set.build_fixture_set``). One test uses a
SYNTHETIC UniProt variant (``_synthetic_substituted``: seven O14965 letters changed) so the alignment identity is not
an integer and seven mapped rows differ from the UniProt letter. No report value is hard-coded from the product:
counts are recounted from the stored rows, percentages are re-derived from the stored alignment counts and rendered
with an independent Decimal oracle. Forged report manifests below are labeled test fabrications written only to
prove that the saved-report validator rejects them.
"""
from __future__ import annotations

import copy
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from reference_fixture_set import build_fixture_set

from mw import numbering_reports as nr
from mw import reference_snapshots as rs
from mw.core.handles import canonical_json
from mw.reports import EvidenceError

FIX = Path(__file__).resolve().parent / "fixtures"
CIF_1MQ4 = FIX / "public_1mq4.cif"
REF = FIX / "reference"
PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")
SUBSTITUTED = (140, 170, 200, 230, 260, 300, 340)   # O14965 positions inside the 1MQ4:A mapped range 125..391


def _pct_oracle(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _synthetic_substituted() -> bytes:
    """SYNTHETIC: entries_fixture.jsonl with O14965 letters at ``SUBSTITUTED`` replaced (W, or Y where W)."""
    rows = [json.loads(line) for line in (REF / "uniprot/entries_fixture.jsonl").read_bytes().splitlines() if line]
    for row in rows:
        if row["id"] == "O14965":
            seq = list(row["data"]["sequence"])
            for position in SUBSTITUTED:
                seq[position - 1] = "W" if seq[position - 1] != "W" else "Y"
            row["data"]["sequence"] = "".join(seq)
    return b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows)


@pytest.fixture
def refroot(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    return root


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    return TestClient(appmod.app, base_url="http://127.0.0.1")


def _new_run(client) -> tuple[str, str]:
    rid = client.post("/runs", json={"goal": "numbering report"}).json()["run_id"]
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "1mq4.cif"}, content=CIF_1MQ4.read_bytes(),
                         headers={"content-type": "application/octet-stream"}).json()
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
                                                         "args": {"source": upload["upload_id"]}})
    assert loaded.status_code == 200, loaded.text
    return rid, loaded.json()["handle"]["handle"]


def _map(client, rid, structure, chains, pdb_id=None) -> str:
    out = client.post(f"/runs/{rid}/commands", json={"tool": "map_residue_numbering", "args": {
        "structure": structure, "pdb_id": pdb_id, "chains": chains}})
    assert out.status_code == 200, out.text
    return out.json()["handle"]["handle"]


def _report(client, rid, handle) -> dict:
    created = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert created.status_code == 201, created.text
    return created.json()


def _run(rid):
    import mw.api.app as appmod
    return appmod._run(rid)


def _resolve(document, path):
    value = document
    for part in path.split("."):
        match = PATH_PART.fullmatch(part)
        assert match, path
        value = value[match.group(1)]
        if match.group(2) is not None:
            value = value[int(match.group(2))]
    return value


def _verify_independently(run, manifest) -> dict:
    """Re-resolve every claim from the stored map; recount counts from rows; check evidence-kind separation."""
    handle = manifest["result_handle"]
    stored = run.store.load(handle)
    set_manifest = run.store.load(manifest["reference_set_handle"])
    licenses = {s["source"]: (s["license"], s["date"], s["snapshot_id"], s["version_hint"])
                for s in set_manifest["sources"]}
    seen = set()
    totals = {}
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["field_path"], json.dumps(claim["row_selector"], sort_keys=True))
        assert key not in seen
        seen.add(key)
        assert claim["source_handle"] == handle and claim["source_sha256"] == handle.rsplit("/", 1)[-1]
        assert claim["subject"]["map_handle"] == handle
        sid = claim["statement_id"]
        if claim["evidence_kind"] == "computed":
            assert claim["reference"] is None and not sid.startswith("reference_")
            if claim["field_path"].startswith("rows."):
                if sid == "status_count":
                    rows = stored["rows"]
                    status = claim["row_selector"]["status"]
                    expected = sum(r["status"] == status for r in rows)
                    totals[status] = expected
                else:
                    rows = [r for r in stored["rows"]
                            if r["residue"]["chain_auth"] == claim["row_selector"]["chain_auth"]]
                    if sid == "chain_residue_mismatch_count":
                        expected = sum(r["residue_match"] is False for r in rows)
                    elif sid == "chain_residue_mismatch_kind_count":
                        sel = claim["row_selector"]
                        expected = sum(r["residue_match"] is False and
                                       r["residue"]["resname"] == sel["structure_resname"] and
                                       r["uniprot_residue"] == sel["uniprot_residue"] for r in rows)
                        assert expected > 0  # only kinds that occur are claimed
                    else:
                        assert sid == "chain_ambiguous_residue_count"
                        expected = sum("alignment_ambiguous" in r["alignment"].get("absent_reasons", [])
                                       for r in rows)
                assert claim["exact_value"] == expected and claim["rendered_value"] == str(expected)
            else:
                value = _resolve(stored, claim["field_path"])
                assert claim["exact_value"] == value
                if sid in {"chain_identity_pct", "chain_coverage_pct"}:
                    chain = _resolve(stored, claim["field_path"].split(".")[0])["alignment"]
                    pairs, n = chain["aligned_pairs"], chain["chain_residue_count"]
                    oracle = (chain["identical"] / pairs * 100 if sid == "chain_identity_pct" else pairs / n * 100)
                    assert value == oracle and claim["rendered_value"] == _pct_oracle(oracle)
                    assert claim["unit"] == "percent"
                elif sid == "chain_status_count":
                    chain = _resolve(stored, claim["field_path"].split(".")[0])
                    status = claim["field_path"].rsplit(".", 1)[-1]
                    assert value == sum(r["status"] == status for r in stored["rows"]
                                        if r["residue"]["chain_auth"] == chain["chain_auth"])
                    assert claim["rendered_value"] == str(value)
                else:
                    assert sid == "chain_modified_residue_count" and claim["rendered_value"] == str(value)
        else:
            assert claim["evidence_kind"] == "reference_value" and sid.startswith("reference_")
            ref = claim["reference"]
            assert ref["note"] == "참조 스냅샷 값, 계산 아님" and ref["set_hash"] == stored["snapshot_set"]["set_hash"]
            assert ref["origin"] == "kbase_kinase processed snapshot" and ref["sources"]
            for source in ref["sources"]:
                assert (source["license"], source["date"], source["snapshot_id"], source["version_hint"]) == \
                    licenses[source["source"]]
            value = _resolve(stored, claim["field_path"])
            assert claim["exact_value"] == value and claim["rendered_value"] == str(value)
            if claim["field_path"].startswith("rows["):
                index = claim["row_selector"]["row_index"]
                row = stored["rows"][index]
                assert claim["subject"]["residue"] == row["residue"] and row["status"] == "mapped"
                assert row["klifs_index"] is not None
    labelled = [i for i, r in enumerate(stored["rows"]) if r["status"] == "mapped" and r["klifs_index"] is not None]
    assert [item["row_index"] for item in manifest["labelled_rows"]] == labelled
    assert sum(c["field_path"].endswith(".klifs_index") for c in manifest["claims"]) == len(labelled)
    assert totals == {s: sum(r["status"] == s for r in stored["rows"]) for s in ("mapped", "unmapped", "conflict")}
    return totals


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
                                        "analysis_type": "residue_numbering", "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"],
                          snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _index(manifest, statement, path_suffix):
    return next(i for i, c in enumerate(manifest["claims"])
                if c["statement_id"] == statement and c["field_path"].endswith(path_suffix))


# --- rendering ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(("value", "text"), [
    (97.25, "97.3"), (97.35, "97.4"), (97.24999, "97.2"), (100.0, "100.0"), (0.05, "0.1"), (0.0, "0.0"),
    (89.95, "90.0"), (97.31800766283524, "97.3"), (None, "undefined")])
def test_percent_rendering_is_decimal_half_up(value, text):
    assert nr.render_pct(value) == text
    if value is not None:
        assert _pct_oracle(value) == text
    assert round(97.25, 1) == 97.2   # the float rounding the rule forbids


def test_wrong_rounding_of_a_percent_claim_is_rejected():
    source = {"source": "uniprot", "snapshot_id": "s", "date": "d", "version_hint": None, "license": "l"}
    content = {"rows": [], "snapshot_set": {"set_hash": "h", "origin": "o", "sources": [source]},
               "chains": [{"chain_auth": "A", "counts": {"mapped": 0, "unmapped": 0, "conflict": 0},
                           "residue_rule": {"modified_residue_count": 0}, "sifts": None,
                           "alignment": {"accession": "P0", "identity_pct": 97.25, "coverage_pct": 50.0}}]}
    handle = "obj://r/residue_numbering_map/" + "a" * 64
    claims = nr.claims_for(handle, content)
    identity = next(c for c in claims if c["statement_id"] == "chain_identity_pct")
    assert identity["rendered_value"] == "97.3" and identity["exact_value"] == 97.25
    assert nr.match_claim(claims, copy.deepcopy(identity)) == identity
    for wrong in ("97.2", "97.25", "97", "97.30"):
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            nr.match_claim(claims, {**identity, "rendered_value": wrong})


# --- 1MQ4 report through the product path ---------------------------------------------------------------------------

def test_1mq4_report_round_trips_and_every_value_is_bound(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    run = _run(rid)
    assert manifest["analysis_type"] == "residue_numbering" and manifest["status"] == "complete"
    totals = _verify_independently(run, manifest)
    stored = run.store.load(handle)
    assert totals["mapped"] + totals["unmapped"] + totals["conflict"] == len(stored["rows"])
    # Counts are never hidden, including zero ones.
    for status, label in (("mapped", "대응됨"), ("unmapped", "대응 없음"), ("conflict", "충돌")):
        assert f"- {label} ({status}): {totals[status]}\n" in markdown
    chain = stored["chains"][0]
    assert f"coverage (ProtView 계산): {_pct_oracle(chain['alignment']['coverage_pct'])} %" in markdown
    assert f"Alignment identity (ProtView 계산): {_pct_oracle(chain['alignment']['identity_pct'])} %" in markdown
    # Snapshot source table, KLIFS terms, processed-copy label.
    for line in (("| UniProt | 2026\\_03 | 2026\\-09\\-15 | SNAP\\-uniprot\\-2026\\-09\\-15 | CC\\-BY\\-4\\.0 | "
                  "kbase\\_kinase 가공본 |"),
                 ("| SIFTS | none \\(null\\) | 2026\\-09\\-20 | SNAP\\-sifts\\-2026\\-09\\-20 | EMBL\\-EBI\\-terms | "
                  "kbase\\_kinase 가공본 |"),
                 ("| KLIFS | none \\(null\\) | 2026\\-09\\-19 | SNAP\\-klifs\\-2026\\-09\\-19 | "
                  "이용 조건 명시 없음\\(none\\-stated\\) | kbase\\_kinase 가공본 |")):
        assert line in markdown
    assert "Cross-check (both methods): yes" in markdown and "Methods run: sifts, local\\_alignment" in markdown
    assert not nr.INTERPRETIVE.search(markdown)
    # Every labelled row appears with its reference values.
    for item in manifest["labelled_rows"]:
        assert f"| {item['uniprot_position']} | " in markdown and f"| {item['klifs_index']} | " in markdown
    # list / selected / download
    listed = client.get(f"/runs/{rid}/reports").json()
    entry = next(item for item in listed if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "residue_numbering" and entry["result_handle"] == handle
    selected = client.get(f"/runs/{rid}/reports/selected", params={"handle": created["handle"]})
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "markdown"})
    js = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") and js.content == canonical_json(manifest)
    assert md.headers["content-disposition"].startswith('attachment; filename="protview-report-')
    # A second report is a new object; the first stays byte-identical.
    again = _report(client, rid, handle)
    assert again["handle"] != created["handle"] or again["manifest"]["snapshot"] != manifest["snapshot"]
    assert client.get(f"/runs/{rid}/reports/download",
                      params={"handle": created["handle"], "format": "json"}).content == js.content


def test_substituted_reference_gives_exact_rounding_and_mismatch_counts(tmp_path, refroot, client):
    build_fixture_set(refroot, replace={("uniprot", "entries.jsonl"): _synthetic_substituted()})
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    run = _run(rid)
    _verify_independently(run, manifest)
    stored = run.store.load(handle)
    alignment = stored["chains"][0]["alignment"]
    identity = alignment["identical"] / alignment["aligned_pairs"] * 100
    assert identity != int(identity) and _pct_oracle(identity) == "97.3"
    mismatched = [r for r in stored["rows"] if r["residue_match"] is False]
    assert sorted(r["uniprot_position"] for r in mismatched) == list(SUBSTITUTED)
    assert "(ProtView 계산): 7\n" in markdown and "Alignment identity (ProtView 계산): 97.3 %" in markdown
    # Mismatch counts by kind = (structure resname, UniProt one-letter) per chain, summing to the chain count.
    kinds = [c for c in manifest["claims"] if c["statement_id"] == "chain_residue_mismatch_kind_count"]
    oracle: dict = {}
    for r in mismatched:
        key = (r["residue"]["resname"], r["uniprot_residue"])
        oracle[key] = oracle.get(key, 0) + 1
    assert {(c["row_selector"]["structure_resname"], c["row_selector"]["uniprot_residue"]): c["exact_value"]
            for c in kinds} == oracle
    assert all(c["evidence_kind"] == "computed" and c["field_path"] == "rows.residue_match" for c in kinds)
    assert sum(c["exact_value"] for c in kinds) == 7
    for (resname, letter), count in oracle.items():
        assert f"{resname}/{letter} {count}" in markdown
    kind = kinds[0]
    assert nr.validate_numbering_claim(run, handle, kind) == kind  # the correct count is accepted
    for wrong in ({**kind, "exact_value": kind["exact_value"] + 1, "rendered_value": str(kind["exact_value"] + 1)},
                  {**kind, "row_selector": {**kind["row_selector"], "uniprot_residue": "Z"}}):
        with pytest.raises(EvidenceError, match="binding_mismatch|field_not_allowed"):
            nr.validate_numbering_claim(run, handle, wrong)
    claim = manifest["claims"][_index(manifest, "chain_identity_pct", ".identity_pct")]
    for wrong in ("97.32", "97.4", "97.31800766283524"):
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            nr.validate_numbering_claim(run, handle, {**claim, "rendered_value": wrong})
    forged = _forge(run, manifest, markdown.replace("97.3 %", "97.32 %"),
                    lambda f: f["claims"][_index(f, "chain_identity_pct", ".identity_pct")].update(
                        rendered_value="97.32"))
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}).status_code == 422


def test_null_result_report(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A", "uniprot_accession": "Q8IU85"}])
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    totals = _verify_independently(_run(rid), manifest)
    assert manifest["null_result"] is True and totals["mapped"] == 0 and manifest["labelled_rows"] == []
    assert "scientific\\_null" in markdown and "Cross-check (both methods): no (reason: pdb\\_id\\_not\\_given)" in markdown
    assert f"- 대응 없음 (unmapped): {totals['unmapped']}\n" in markdown


# --- rejections -----------------------------------------------------------------------------------------------------

def test_reference_and_computed_evidence_never_mix(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    run = _run(rid)
    position = manifest["claims"][_index(manifest, "reference_uniprot_position", ".uniprot_position")]
    klifs = manifest["claims"][_index(manifest, "reference_klifs_index", ".klifs_index")]
    identity = manifest["claims"][_index(manifest, "chain_identity_pct", ".identity_pct")]
    count = manifest["claims"][_index(manifest, "chain_status_count", ".counts.mapped")]
    cases = {
        # a reference value relabelled as computed evidence
        "evidence_kind_mismatch": {**position, "evidence_kind": "computed", "reference": None},
        # a computed statement citing a reference field
        "reference_field_as_computed": {**count, "field_path": klifs["field_path"],
                                        "row_selector": klifs["row_selector"], "exact_value": klifs["exact_value"],
                                        "rendered_value": klifs["rendered_value"]},
        # a reference statement citing a computed field
        "computed_field_as_reference": {**position, "field_path": identity["field_path"]},
        # computed evidence may not carry a reference record, reference evidence must
        "computed_field_rule": {**identity, "reference": position["reference"]},
        "reference_field_rule": {**position, "reference": None},
        "statement_not_allowed": {**identity, "statement_id": "hinge_binding_importance"},
    }
    for reason, claim in cases.items():
        with pytest.raises(EvidenceError, match=reason):
            nr.validate_numbering_claim(run, handle, claim)
    for reason, claim in cases.items():
        def mutate(forged, claim=claim):
            forged["claims"][_index(forged, "reference_uniprot_position", ".uniprot_position")] = claim
        forged = _forge(run, manifest, markdown, mutate)
        response = client.get(f"/runs/{rid}/reports/selected", params={"handle": forged})
        assert response.status_code == 422, reason


def test_interpretive_statements_are_rejected(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    run = _run(rid)
    for text in ("This hinge residue is important for binding.", "hinge 결합에 중요", "affinity hotspot",
                 "stabilizes the αC helix", "핵심 잔기"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            nr.check_no_interpretation(text)
    tampered_md = _forge(run, manifest, markdown.replace("## Limitations", "Hinge residues are important for "
                                                                          "binding.\n\n## Limitations"),
                         lambda _f: None)
    extra_limitation = _forge(run, manifest, markdown,
                              lambda f: f["limitations"].append("The hinge is important for binding."))
    for forged in (tampered_md, extra_limitation):
        response = client.get(f"/runs/{rid}/reports/selected", params={"handle": forged})
        assert response.status_code == 422
    listed = client.get(f"/runs/{rid}/reports")
    assert listed.status_code == 422   # the list refuses to present a run holding an invalid report
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        nr.render_numbering_report({**manifest, "limitations": ["Key residue for ATP binding."]})


def test_wrong_row_handle_and_source_are_rejected(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    other = _map(client, rid, structure, [{"chain_auth": "A", "uniprot_accession": "O14965"}])
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    run = _run(rid)
    i = _index(manifest, "reference_uniprot_position", ".uniprot_position")
    position = manifest["claims"][i]
    row_index = position["row_selector"]["row_index"]
    other_row = manifest["labelled_rows"][1]["row_index"]
    other_position = next(c for c in manifest["claims"]
                          if c["field_path"] == f"rows[{other_row}].uniprot_position")
    cases = [
        # the other row's number under this row's selector and subject
        {**position, "exact_value": other_position["exact_value"],
         "rendered_value": other_position["rendered_value"]},
        # this row's number under another row's field path
        {**position, "field_path": f"rows[{other_row}].uniprot_position"},
        # the same field of another numbering map
        {**position, "source_handle": other, "source_sha256": other.rsplit("/", 1)[-1],
         "subject": {**position["subject"], "map_handle": other}},
        # a stale row fingerprint
        {**position, "row_selector": {"row_index": row_index, "row_sha256": "0" * 64}},
        # an unlabelled (conflict) row
        {**position, "field_path": "rows[0].uniprot_position",
         "row_selector": {**position["row_selector"], "row_index": 0}},
    ]
    for claim in cases:
        with pytest.raises(EvidenceError):
            nr.validate_numbering_claim(run, handle, claim)
    count = manifest["claims"][_index(manifest, "chain_status_count", ".counts.conflict")]
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        nr.validate_numbering_claim(run, handle, {**count, "exact_value": count["exact_value"] + 1,
                                                  "rendered_value": str(count["exact_value"] + 1)})
    forgeries = {
        "wrong_result_handle": lambda f: f.update(result_handle=other),
        "dropped_labelled_row": lambda f: f["labelled_rows"].pop(),
        "count_changed": lambda f: f["chains"][0]["counts"].update(conflict=0),
        "license_changed": lambda f: f["snapshot_set"]["sources"][2].update(license="CC0"),
    }
    for name, mutate in forgeries.items():
        forged = _forge(run, manifest, markdown, mutate)
        assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}).status_code == 422, name
    # Not a numbering map, or a map that no successful tool call published.
    assert client.post(f"/runs/{rid}/method_reports", json={"result_handle": structure}).status_code == 422
    content = run.store.load(handle)
    with run._owner():
        fake = run.store.put("residue_numbering_map", "residue_numbering_map@1",
                             {**content, "pdb_id": None}, produced_by="forged_test_numbering_map")
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": fake.handle})
    assert response.status_code == 422 and "missing_successful_tool_provenance" in response.text


def test_report_module_reads_only_stored_evidence():
    source = (Path(__file__).resolve().parents[1] / "mw" / "numbering_reports.py").read_text()
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "pin_active_set", "reference_index"):
        assert forbidden not in source


# --- snapshot scope and closed reason sets ---------------------------------------------------------------------------

def test_report_states_snapshot_scope_without_numbers(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    created = _report(client, rid, handle)
    manifest, markdown = created["manifest"], created["markdown"]
    assert nr.SNAPSHOT_SCOPE in manifest["limitations"]
    limits = markdown.split("## Limitations", 1)[1]
    assert f"- {nr._md(nr.SNAPSHOT_SCOPE)}\n" in limits
    for fragment in ("kinase 한정", "원출처 원본 바이트 아님", "SIFTS 대응이나 KLIFS 번호가 없습니다"):
        assert fragment in nr.SNAPSHOT_SCOPE
    assert not re.search(r"\d", nr.SNAPSHOT_SCOPE)


def test_saved_report_with_legacy_limitations_still_reopens(tmp_path, refroot, client):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    with pytest.MonkeyPatch.context() as patch:   # a report saved before the snapshot-scope line existed
        patch.setattr(nr, "REPORT_LIMITATIONS", list(nr.LEGACY_REPORT_LIMITATIONS))
        old = _report(client, rid, handle)
    assert nr.SNAPSHOT_SCOPE not in old["manifest"]["limitations"]
    selected = client.get(f"/runs/{rid}/reports/selected", params={"handle": old["handle"]})
    assert selected.status_code == 200, selected.text
    assert selected.json()["markdown"] == old["markdown"]
    # Any other limitation list is still a field mismatch.
    forged = _forge(_run(rid), old["manifest"], old["markdown"], lambda f: f["limitations"].pop())
    assert client.get(f"/runs/{rid}/reports/selected", params={"handle": forged}).status_code == 422


@pytest.mark.parametrize(("mutate", "check"), [
    (lambda c: c["rows"][0].update(sifts={"absent_reason": "made_up", "absent_reasons": ["made_up"]}), "rows"),
    (lambda c: c["rows"][0].update(alignment={"absent_reason": "alignment_gap",
                                              "absent_reasons": ["alignment_gap", "made_up"]}), "rows"),
    (lambda c: c["rows"][0].update(sifts={"absent_reason": "alignment_gap", "absent_reasons": ["alignment_gap"]}),
     "rows"),
    (lambda c: c["rows"][0].update(conflict_reason="made_up"), "rows"),
    (lambda c: c["chains"][0]["klifs"][0].update(applied=False, absent_reason="made_up"), "chains"),
    (lambda c: c["chains"][0]["klifs"][0].update(applied=True, absent_reason="accession_not_in_klifs"), "chains"),
], ids=["sifts", "alignment", "sifts_with_alignment_reason", "conflict", "klifs", "klifs_applied_with_reason"])
def test_unknown_reason_codes_are_rejected(tmp_path, refroot, client, mutate, check):
    build_fixture_set(refroot)
    rid, structure = _new_run(client)
    handle = _map(client, rid, structure, [{"chain_auth": "A"}], pdb_id="1MQ4")
    content = copy.deepcopy(_run(rid).store.load(handle))
    # rows[0] becomes a conflict row with both method answers (row order does not matter to the checks)
    content["rows"].insert(0, content["rows"].pop(next(i for i, r in enumerate(content["rows"])
                                                         if r["status"] == "conflict")))
    nr._check_rows(content)
    nr._check_chains(content)
    assert content["rows"][0]["conflict_reason"] is not None and content["chains"][0]["klifs"]
    mutate(content)
    with pytest.raises(EvidenceError):
        (nr._check_rows if check == "rows" else nr._check_chains)(content)
