"""Immutable, field-cited reports for one ``docking_batch_result@1`` (``method_report_manifest@1``,
``analysis_type: "ligand_docking_batch"``, render ``ligand_docking_batch_markdown@1``; spec .dryforge/spec.md 10).

The input is one batch summary handle; a batch has one mode, so free and core-fixed rows are never mixed. Every value
statement is ``computed`` evidence bound to one handle and one field path:

- the summary: the shared settings (receptor import, removed instance, candidate set and parent SDF, box, parameters,
  engine, Meeko/RDKit versions), the row counts (``count``/``count_where(state == ...)`` over the stored rows,
  recounted at every validation) and, for each ``scored`` row only, ``rows[i].score_kcal_mol``;
- the per-row result of each ``scored`` row: ``modes[0].score_kcal_mol`` (the score column target, "모드 1(엔진 출력
  순서)" or "샘플 1(점수 오름차순 나열)", never "best"). Both score claims carry ``row_selector {"row_index": i}`` and
  must hold the same value; the table cell is rendered from them (``Decimal(str(v))`` to 0.1, ``ROUND_HALF_UP``).

Rows that were not computed (``failed``, ``cancelled``, ``not_run``) and ``null_result`` rows have no score claim, so
a score for them is refused and their cell stays empty (never 0); unscored rows show their closed reason code only.

Creating, reopening and downloading never dock again: the summary is re-validated with
``docking_batch_jobs.validated_summary`` (single publication, batch selection, every per-row result re-validated),
every manifest field and claim is compared with the one rebuilt from the stored objects, and the Markdown is compared
byte for byte with a re-render. No per-row M18 report is made. Every Markdown line is checked for interpretive
wording; the only exemptions are a line exactly equal to a fixed M18 limitation sentence or batch sentence B1-B3
(B1 and B3 name 순위/개선 only to deny them), and the exact score-name text (``SCORE_LABEL``), removed from a line
before that line is checked.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from . import docking_batch_constants as BC
from . import docking_batch_jobs as BJ
from . import docking_bundle as db
from . import docking_reports as dr
from .core.handles import canonical_json
from .docking_constants import LIMITATIONS, METHODS, SCORE_COLUMN_LABEL, SCORE_LABEL
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md

ANALYSIS_TYPE = "ligand_docking_batch"
RENDER_VERSION = "ligand_docking_batch_markdown@1"
SUMMARY_KIND, SUMMARY_SCHEMA = BC.OUTPUT_KIND, BC.SUMMARY_SCHEMA
RESULT_KIND, RESULT_SCHEMA = db.OUTPUT_KIND, "docking_result@1"
REPORT_BYTES = dr.REPORT_BYTES
RESIDUE_FIELDS = dr.RESIDUE_FIELDS
PARAMETERS = dr.PARAMETERS
COUNTED = ("rows", *BC.ROW_STATES)
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 일괄 요약 객체의 값, 요약 행을 상태 조건으로 센 개수, 점수 행이 가리키는 "
                      "후보별 도킹 결과 객체의 첫 행 점수다. 보고서는 도킹을 다시 하지 않았다.")
FIXED_SENTENCES = frozenset({*LIMITATIONS, *BC.BATCH_STATEMENTS.values()})
render_score = dr.render_score
_render = dr._render

_RES = "|".join(RESIDUE_FIELDS)
STATEMENTS = {
    "receptor_input": re.compile(r"inputs\.receptor\.(handle|sha256|model_number)"),
    "removed_instance": re.compile(rf"inputs\.receptor\.removed_instance\.(residue\.({_RES})|atom_count)"),
    "candidate_set_input": re.compile(r"inputs\.candidate_set\.(handle|parent_sdf_handle|parent_sdf_sha256)"),
    "box": dr.STATEMENTS["box"],
    "parameter": dr.STATEMENTS["parameter"],
    "engine": dr.STATEMENTS["engine"],
    "preparation": dr.STATEMENTS["preparation"],
    "row_count": re.compile(r"counts\.(" + "|".join(COUNTED) + ")"),
    "row_score": re.compile(r"rows\[\d+\]\.score_kcal_mol"),
    "row_result_score": re.compile(r"modes\[0\]\.score_kcal_mol"),
}
SOURCES = {statement: (RESULT_KIND, RESULT_SCHEMA) if statement == "row_result_score" else
           (SUMMARY_KIND, SUMMARY_SCHEMA) for statement in STATEMENTS}
EVIDENCE_KINDS = ("computed",)
CLAIM_KEYS = dr.CLAIM_KEYS
INTERPRETIVE = dr.INTERPRETIVE
CAPABILITY_KEYS = ("available", "status", "reason_code", "pins", "batch_pins")
SNAPSHOT_KEYS = dr.SNAPSHOT_KEYS
COPIED_FIELDS = ("method", "batch_input_sha256", "inputs", "box", "parameters", "engine", "preparation", "limits",
                 "stop_reason", "counts", "rows")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "batch_status", "mode", "score_label", "score_column_label",
    "score_row_label", "claims", "provenance", "evidence_statement", "limitation_ids", "limitations", "snapshot",
    "markdown_handle"})
SHA_RE = re.compile(r"[0-9a-f]{64}")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on every line. A line exactly equal to a fixed M18 limitation sentence or batch
    sentence is exempt; on any other line only the exact score-name text is removed before the check."""
    for line in text.split("\n"):
        if line in FIXED_SENTENCES:
            continue
        match = INTERPRETIVE.search(line.replace(SCORE_LABEL, ""))
        if match is not None:
            raise EvidenceError(f"docking_batch_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None = None) -> dict[str, Any]:
    kind, schema = SOURCES[statement_id]
    return {"statement_id": statement_id, "evidence_kind": "computed", "source_handle": handle,
            "source_kind": kind, "source_schema": schema, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": subject, "quantity": quantity, "unit": unit,
            "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": operation}


def _required(content: dict[str, Any], results: dict[str, Any]) -> None:
    """One method per batch, and every scored row's summary score is its per-row result's first-row score."""
    mode = content["inputs"]["mode"]
    if mode not in METHODS or content["method"] != METHODS[mode]:
        raise EvidenceError("docking_batch_report_method_mismatch")
    for row in content["rows"]:
        if row["result_handle"] is None:
            continue
        result = results[row["result_handle"]]
        if result["method"] != content["method"] or result["inputs"]["mode"] != mode:
            raise EvidenceError("docking_batch_report_method_mismatch")
        if row["state"] == "scored" and (not result["modes"] or
                                         result["modes"][0]["score_kcal_mol"] != row["score_kcal_mol"]):
            raise EvidenceError("docking_batch_report_score_trace_mismatch")


def claims_for(handle: str, content: dict[str, Any], results: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; state counts are recounted from the stored rows."""
    try:
        _required(content, results)
        subject = {"docking_batch_result_handle": handle}

        def claim(statement: str, path: str, quantity: str, unit: str, value: Any, rounding: str,
                  operation: str | None = None) -> dict[str, Any]:
            return _claim(statement, handle, path, None, subject, quantity, unit, value, rounding, operation)

        receptor = content["inputs"]["receptor"]
        claims = [claim("receptor_input", "inputs.receptor.handle", "receptor_import", "handle", receptor["handle"],
                        "identifier"),
                  claim("receptor_input", "inputs.receptor.sha256", "receptor_sha256", "sha256", receptor["sha256"],
                        "identifier"),
                  claim("receptor_input", "inputs.receptor.model_number", "receptor_model_number", "model_number",
                        receptor["model_number"], "integer")]
        removed = receptor["removed_instance"]
        if removed is not None:
            for field in RESIDUE_FIELDS:
                claims.append(claim("removed_instance", f"inputs.receptor.removed_instance.residue.{field}",
                                    f"removed_instance_{field}", "residue_field", removed["residue"][field], "json"))
            claims.append(claim("removed_instance", "inputs.receptor.removed_instance.atom_count",
                                "removed_instance_atom_count", "count", removed["atom_count"], "integer"))
        for key in ("handle", "parent_sdf_handle", "parent_sdf_sha256"):
            claims.append(claim("candidate_set_input", f"inputs.candidate_set.{key}", f"candidate_set_{key}",
                                "identifier", content["inputs"]["candidate_set"][key], "identifier"))
        box = content["box"]
        claims.append(claim("box", "box.source", "box_source", "identifier", box["source"], "identifier"))
        for key in ("center_A", "size_A"):
            for axis in range(3):
                claims.append(claim("box", f"box.{key}[{axis}]", f"box_{key}_{'xyz'[axis]}", "A", box[key][axis],
                                    "distance_2dp"))
        if box["margin_A"] is not None:
            claims.append(claim("box", "box.margin_A", "box_margin_A", "A", box["margin_A"], "distance_2dp"))
        params = content["parameters"]
        for key in PARAMETERS:
            if params[key] is not None:
                claims.append(claim("parameter", f"parameters.{key}", key,
                                    "kcal/mol" if key == "energy_range" else "count" if key != "seed" else "seed",
                                    params[key], "input_decimal" if key == "energy_range" else "integer"))
        for key in ("name", "version"):
            claims.append(claim("engine", f"engine.{key}", f"engine_{key}", "identifier", content["engine"][key],
                                "identifier"))
        for key in ("tool", "version", "rdkit_version"):
            claims.append(claim("preparation", f"preparation.{key}", f"preparation_{key}", "identifier",
                                content["preparation"][key], "identifier"))
        rows = content["rows"]
        claims.append(claim("row_count", "counts.rows", "rows", "count", len(rows), "integer", "count(rows)"))
        for state in BC.ROW_STATES:
            claims.append(claim("row_count", f"counts.{state}", f"{state}_rows", "count",
                                sum(1 for row in rows if row["state"] == state), "integer",
                                f"count_where(state == {state}; rows)"))
        for row in rows:
            if row["state"] != "scored":
                continue
            index, result_handle = row["row_index"], row["result_handle"]
            selector = {"row_index": index}
            claims.append(_claim("row_score", handle, f"rows[{index}].score_kcal_mol", selector,
                                 {**subject, "row_index": index}, "score_kcal_mol", "kcal/mol",
                                 row["score_kcal_mol"], "score_1dp"))
            claims.append(_claim("row_result_score", result_handle, "modes[0].score_kcal_mol", selector,
                                 {**subject, "row_index": index, "docking_result_handle": result_handle},
                                 "score_kcal_mol", "kcal/mol", results[result_handle]["modes"][0]["score_kcal_mol"],
                                 "score_1dp"))
        return claims
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise EvidenceError("docking_batch_report_evidence_unresolved") from exc


def _key(claim: dict[str, Any]) -> tuple[str, str, str, bytes]:
    return claim["statement_id"], claim["source_handle"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim rebuilt from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("docking_batch_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("docking_batch_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS:
        raise EvidenceError("docking_batch_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("docking_batch_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != SOURCES[statement]:
        raise EvidenceError("docking_batch_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims if claim["statement_id"] == statement}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("docking_batch_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("docking_batch_claim_shape") from exc
    if match is None:
        raise EvidenceError("docking_batch_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("docking_batch_claim_binding_mismatch")
    return proposed


def validate_docking_batch_claim(run: Any, summary_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, summary_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored summary and per-row results."""
    try:
        content = BJ.validated_summary(run, handle)
        source = BJ.summary_producer(run, handle)
        results = {row["result_handle"]: db.validated_result(run, row["result_handle"])
                   for row in content["rows"] if row["result_handle"] is not None}
        rows = [{"row_index": row["row_index"], "result_handle": row["result_handle"],
                 **{key: producer[key] for key in ("job_id", "attempt_id")},
                 "protocol_id": producer["job"]["protocol_id"]}
                for row in content["rows"] if row["result_handle"] is not None
                for producer in (db.producer(run, row["result_handle"]),)]
    except (BJ.DockingBatchEvidenceError, db.DockingEvidenceError) as exc:
        raise EvidenceError(f"docking_batch_result_invalid: {exc}") from exc
    try:
        mode = content["inputs"]["mode"]
        ids = content["limitations"]
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": SUMMARY_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS}, "batch_status": content["status"], "mode": mode,
                "score_label": SCORE_LABEL, "score_column_label": SCORE_COLUMN_LABEL,
                "score_row_label": BC.SCORE_ROW_LABELS[mode], "claims": claims_for(handle, content, results),
                "provenance": {"docking_batch": {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
                                                 "protocol_id": source["job"]["protocol_id"],
                                                 "tool_id": source["job"]["tool_id"],
                                                 "created_event_seq": source["created_seq"],
                                                 "completed_event_seq": source["published_seq"]},
                               "rows": rows},
                "evidence_statement": EVIDENCE_STATEMENT, "limitation_ids": ids,
                "limitations": [*(BC.BATCH_STATEMENTS[item] for item in ids["batch_statements"]),
                                *(LIMITATIONS[number - 1] for number in ids["m18_sentences"])]}
    except EvidenceError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("docking_batch_report_evidence_unresolved") from exc


def capability_snapshot() -> dict[str, Any]:
    """Batch capability status and pins at report creation (nothing is docked)."""
    value = BJ.capability()
    return {key: value[key] for key in CAPABILITY_KEYS}


def capability_snapshot_valid(value: Any) -> bool:
    if type(value) is not dict or set(value) != set(CAPABILITY_KEYS):
        return False
    ready = value["status"] == "ready"
    if not (ready or value["status"] in db.REASONS) or value["available"] is not ready:
        return False
    if not ready:
        return value["reason_code"] == value["status"] and value["pins"] is None and value["batch_pins"] is None
    try:
        db._pins(value["pins"])
    except db.DockingEvidenceError:
        return False
    pins = value["batch_pins"]
    return (value["reason_code"] is None and type(pins) is dict and
            set(pins) == {"batch_worker_sha256", "batch_constants_sha256"} and
            all(type(item) is str and SHA_RE.fullmatch(item) for item in pins.values()))


# ---------------------------------------------------------------------------------------------------------------
# Markdown

def render_docking_batch_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every engine number is the rendered text of a bound claim."""
    claims = manifest["claims"]

    def value(statement: str, path: str | None = None, **selector: Any) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and
                 (path is None or c["field_path"] == path) and
                 all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("docking_batch_report_claim_missing")
        return found[0]

    def score(index: int) -> str:
        text = value("row_score", f"rows[{index}].score_kcal_mol", row_index=index)
        if value("row_result_score", "modes[0].score_kcal_mol", row_index=index) != text:
            raise EvidenceError("docking_batch_report_score_trace_mismatch")
        return text

    core = manifest["mode"] == "core_fixed"
    receptor = manifest["inputs"]["receptor"]
    job = manifest["provenance"]["docking_batch"]
    engine = manifest["engine"]
    partial = manifest["batch_status"] == "partial"
    lines = ["# 리간드 도킹 일괄 보고서 (ligand docking batch)", "", "Status: complete", "",
             f"Batch summary: {_md(manifest['result_handle'])}",
             f"Batch job: {_md(job['job_id'])}, attempt {_md(job['attempt_id'])}",
             f"Method: {_md(manifest['method'])} ({'코어 고정, 점수만' if core else '자유 도킹'})",
             (f"Engine: {_md(value('engine', 'engine.name'))} {_md(value('engine', 'engine.version'))} (package "
              f"{_md(engine['package'])}, binary SHA-256 {_md(engine['binary_sha256'])})"),
             (f"Preparation: {_md(value('preparation', 'preparation.tool'))} "
              f"{_md(value('preparation', 'preparation.version'))}, RDKit "
              f"{_md(value('preparation', 'preparation.rdkit_version'))}, atom typing "
              f"{_md(manifest['preparation']['atom_typing'])}, charges {_md(manifest['preparation']['charges'])}"),
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             f"- 점수 이름: {SCORE_LABEL}",
             f"- 점수 열: 각 행 후보별 결과의 첫 행, {manifest['score_row_label']}",
             f"- 일괄 상태: {_md(manifest['batch_status'])}"
             + (f", 멈춘 이유 {_md(manifest['stop_reason'])}" if partial else ""), "",
             "## 수용체", "",
             f"- 가져오기: {_md(value('receptor_input', 'inputs.receptor.handle'))}",
             f"- SHA-256: {_md(value('receptor_input', 'inputs.receptor.sha256'))}",
             f"- 모델 번호: {value('receptor_input', 'inputs.receptor.model_number')}",
             f"- 연결 정보: {_md(receptor['connectivity']['kind'])}",
             "- 입력 확인 세 항목: " + ", ".join(f"{_md(key)} {'true' if item is True else 'false'}"
                                          for key, item in receptor["acknowledgement"].items())]
    if receptor["removed_instance"] is None:
        lines.append("- 뺀 리간드 인스턴스: 없음")
    else:
        prefix = "inputs.receptor.removed_instance"
        lines.append("- 뺀 리간드 인스턴스: " + ", ".join(
            f"{_md(field)} {_md(value('removed_instance', f'{prefix}.residue.{field}'))}" for field in RESIDUE_FIELDS)
            + f"; 원자 {value('removed_instance', f'{prefix}.atom_count')}개")
    lines.extend(["", "## 후보 집합", "",
                  f"- 후보 집합: {_md(value('candidate_set_input', 'inputs.candidate_set.handle'))}",
                  f"- 부모 SDF 가져오기: {_md(value('candidate_set_input', 'inputs.candidate_set.parent_sdf_handle'))}",
                  f"- 부모 SDF SHA-256: {_md(value('candidate_set_input', 'inputs.candidate_set.parent_sdf_sha256'))}",
                  f"- 부모 기준 행: {'포함' if manifest['inputs']['include_parent'] else '없음'}",
                  f"- 행 수: {value('row_count', 'counts.rows')}; "
                  + ", ".join(f"{_md(state)} {value('row_count', f'counts.{state}')}" for state in BC.ROW_STATES),
                  "", "## 상자 (Å)", "",
                  f"- 출처: {_md(value('box', 'box.source'))}"
                  + ("" if manifest["box"]["margin_A"] is None else f", 여백 {value('box', 'box.margin_A')} Å"),
                  "- 중심 x, y, z: " + ", ".join(value("box", f"box.center_A[{axis}]") for axis in range(3)),
                  "- 크기 x, y, z: " + ", ".join(value("box", f"box.size_A[{axis}]") for axis in range(3)),
                  "- 좌표계: 리간드 좌표가 수용체와 같은 좌표계라고 가정했다(도구가 검증하지 못한다).",
                  "", "## 값", ""])
    for key in PARAMETERS:
        if manifest["parameters"][key] is not None:
            unit = " kcal/mol" if key == "energy_range" else ""
            lines.append(f"- {_md(key)}: {value('parameter', f'parameters.{key}')}{unit}")
    lines.extend(["", "## 행 (일괄 행 순서)", "",
                  f"| 행 | 후보 id | 상태 | {SCORE_COLUMN_LABEL} | 점수 대상 | 이유 | 후보별 결과 |",
                  "| ---: | --- | --- | ---: | --- | --- | --- |"])
    for row in manifest["rows"]:
        scored = row["state"] == "scored"
        cells = [str(row["row_index"]), "부모(기준 입력)" if row["kind"] == "parent" else _md(row["candidate_id"]),
                 _md(row["state"]), score(row["row_index"]) if scored else "",
                 manifest["score_row_label"] if scored else "",
                 "" if row["reason_code"] is None else _md(row["reason_code"]),
                 "" if row["result_handle"] is None else _md(row["result_handle"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, units, field paths and row conditions are in the JSON download "
                   f"({len(claims)} claims). Per-row results open in the ligand tab docking reads; this report "
                   "makes no per-row docking report."), ""])
    return check_no_interpretation("\n".join(lines))


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_docking_batch_report(run: Any, summary_handle: str) -> dict[str, Any]:
    """New report object for one stored batch summary (nothing is docked again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, summary_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "capability": capability_snapshot(),
                                "budget": run.budget_snapshot()}
        markdown = render_docking_batch_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("docking_batch_report_too_large")
        produced_by = f"docking_batch_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by=produced_by, summary={"result_handle": summary_handle})
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                               produced_by=produced_by,
                               summary={"result_handle": summary_handle, "analysis_type": ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=summary_handle, snapshot_event_seq=seq)
        return {"handle": report.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_docking_batch_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored batch report without docking again."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("docking_batch_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("docking_batch_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("docking_batch_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"docking_batch_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["docking_batch"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not capability_snapshot_valid(snapshot["capability"]) or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("docking_batch_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("docking_batch_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("docking_batch_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("docking_batch_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_docking_batch_report(report):
        raise EvidenceError("docking_batch_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
