"""Immutable, field-cited reports for one ``ligand_ga_result@1`` (``method_report_manifest@1``,
``analysis_type: "ligand_ga"``, render ``ligand_ga_markdown@1``; spec .dryforge/spec.md 4, 5, 8). Mirrors the M19
batch report (``docking_batch_reports``).

The input is one GA summary handle. Every value statement is ``computed`` evidence bound to one handle and one field
path:

- the summary: the shared settings (receptor import, removed instance, candidate set and parent SDF, box, M18 values,
  GA values), the pool counts, the run counts (``generations_done``, ``new_dockings_used`` and ``reused_count``
  recounted with ``count_where`` over the stored generations and individuals at every validation;
  ``reserved_units``), per generation the individual counts (``count`` / ``count_where(state == ...)``) and the
  stored ``min_score`` / ``max_score`` (values only, each equal to an extreme of that generation's stored individual
  scores) and, for each ``scored`` individual only, ``generations[g].individuals[p].score``;
- the result of each ``scored`` individual: ``modes[0].score_kcal_mol`` (the score target "모드 1(엔진 출력 순서)").
  Both score claims carry ``row_selector {"generation": g, "position": p}`` and must hold the same value; the table
  cell is rendered from them (``Decimal(str(v))`` to 0.1, ``ROUND_HALF_UP``).

Individuals without a score (``null_result``, ``failed``) and individuals that were never computed have no score
claim, so a score for them is refused and their cell stays empty (never 0); they are listed after the scored ones of
their generation (display order only). ``parent_candidate_id`` and ``similarity`` are copied worker records (G1).

Creating, reopening and downloading never dock again: the summary is re-validated with
``ligand_ga_jobs.validated_summary``, every manifest field and claim is compared with the one rebuilt from the stored
objects, and the Markdown is compared byte for byte with a re-render. Every Markdown line is checked for interpretive
wording (ranking, best, improvement, winner, average or recommendation words on top of the M18 set); the only
exemptions are a line exactly equal to a fixed sentence G1-G3 (G1 names 순위/추천 only to deny them) and the exact
score-name text (``SCORE_LABEL``), removed from a line before that line is checked.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from . import docking_bundle as db
from . import docking_reports as dr
from . import ligand_ga_constants as GC
from . import ligand_ga_jobs as LJ
from .core.handles import canonical_json
from .docking_constants import METHODS, SCORE_COLUMN_LABEL, SCORE_LABEL
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md

ANALYSIS_TYPE = "ligand_ga"
RENDER_VERSION = "ligand_ga_markdown@1"
SUMMARY_KIND, SUMMARY_SCHEMA = GC.OUTPUT_KIND, GC.SUMMARY_SCHEMA
RESULT_KIND, RESULT_SCHEMA = db.OUTPUT_KIND, "docking_result@1"
REPORT_BYTES = dr.REPORT_BYTES
RESIDUE_FIELDS = dr.RESIDUE_FIELDS
PARAMETERS = dr.PARAMETERS
RUN_COUNTS = ("generations_done", "new_dockings_used", "reused_count", "reserved_units")
POOL_COUNTS = ("size", "eligible_count", "filter_excluded_count")
ORIGIN_LABELS = {"initial": "초기", "carried": "다음 세대로 이어받음", "similar": "유사", "random": "무작위"}
EVALUATION_LABELS = {"reused": "재사용", "docked": "새 도킹"}
NO_CHANGE_LABEL = "점수 최솟값 변화 없음"
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 GA 요약 객체의 값, 요약의 세대·개체를 조건으로 센 개수, 점수 있는 개체가 "
                      "가리키는 개체별 도킹 결과 객체의 첫 행 점수다. 보고서는 도킹을 다시 하지 않았다.")
FIXED_SENTENCES = frozenset(GC.STATEMENTS.values())
render_score = dr.render_score
_render = dr._render

_RES = "|".join(RESIDUE_FIELDS)
STATEMENTS = {
    "receptor_input": re.compile(r"receptor\.(handle|sha256|model_number)"),
    "removed_instance": re.compile(rf"receptor\.removed_instance\.(residue\.({_RES})|atom_count)"),
    "candidate_set_input": re.compile(r"candidate_set_handle|parent_sdf_handle"),
    "box": dr.STATEMENTS["box"],
    "parameter": dr.STATEMENTS["parameter"],
    "ga_parameter": re.compile(r"ga\.(" + "|".join(GC.GA_KEYS) + ")"),
    "pool_count": re.compile(r"pool\.(" + "|".join(POOL_COUNTS) + ")"),
    "run_count": re.compile("|".join(RUN_COUNTS)),
    "generation_count": re.compile(r"generations\[\d+\]\.individuals"),
    "generation_score_range": re.compile(r"generations\[\d+\]\.(min_score|max_score)"),
    "individual_score": re.compile(r"generations\[\d+\]\.individuals\[\d+\]\.score"),
    "individual_result_score": re.compile(r"modes\[0\]\.score_kcal_mol"),
}
SOURCES = {statement: (RESULT_KIND, RESULT_SCHEMA) if statement == "individual_result_score" else
           (SUMMARY_KIND, SUMMARY_SCHEMA) for statement in STATEMENTS}
EVIDENCE_KINDS = ("computed",)
CLAIM_KEYS = dr.CLAIM_KEYS
# M18 interpretive wording (ranking, best, improvement, binding strength ...) plus the GA additions (spec 5):
# winner, average comparison, recommendation, superiority.
INTERPRETIVE = re.compile(
    dr.INTERPRETIVE.pattern + r"|승자|우승|winner|\bwin\b|평균|average|\bmean\b|추천|recommend|우수|우월|상위|하위|"
    r"향상|악화|better|worse|superior|fittest", re.IGNORECASE)
CAPABILITY_KEYS = ("available", "status", "reason_code", "pins", "ga_pins")
SNAPSHOT_KEYS = dr.SNAPSHOT_KEYS
COPIED_FIELDS = ("protocol", "engine", "candidate_set_handle", "parent_sdf_handle", "receptor", "pins", "call_key",
                 "selection_sha256", "box", "parameters", "filter", "ga", "pool", "stop_reason", *RUN_COUNTS,
                 "generations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "ga_status", "method", "score_label", "score_column_label", "score_row_label",
    "claims", "provenance", "evidence_statement", "limitation_ids", "limitations", "snapshot", "markdown_handle"})
SHA_RE = re.compile(r"[0-9a-f]{64}")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on every line. A line exactly equal to a fixed G sentence is exempt; on any other
    line only the exact score-name text is removed before the check."""
    for line in text.split("\n"):
        if line in FIXED_SENTENCES:
            continue
        match = INTERPRETIVE.search(line.replace(SCORE_LABEL, ""))
        if match is not None:
            raise EvidenceError(f"ligand_ga_report_interpretive_statement: {match.group(0)}")
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


def _individuals(content: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for gen in content["generations"] for entry in gen["individuals"]]


def _required(content: dict[str, Any], results: dict[str, Any]) -> None:
    """Free docking only, every scored individual's summary score is its result's first-row score, and every stored
    generation minimum and maximum is an extreme of that generation's stored scores."""
    method = METHODS[GC.MODE]
    for entry in _individuals(content):
        if entry["result_handle"] is None:
            continue
        result = results[entry["result_handle"]]
        if result["method"] != method or result["inputs"]["mode"] != GC.MODE:
            raise EvidenceError("ligand_ga_report_method_mismatch")
        if entry["state"] == "scored" and (not result["modes"] or
                                           result["modes"][0]["score_kcal_mol"] != entry["score"]):
            raise EvidenceError("ligand_ga_report_score_trace_mismatch")
    for gen in content["generations"]:
        scores = [results[e["result_handle"]]["modes"][0]["score_kcal_mol"] for e in gen["individuals"]
                  if e["state"] == "scored"]
        if (gen["min_score"], gen["max_score"]) != ((min(scores), max(scores)) if scores else (None, None)):
            raise EvidenceError("ligand_ga_report_score_trace_mismatch")


def claims_for(handle: str, content: dict[str, Any], results: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; counts are recounted from the stored generations and individuals."""
    try:
        _required(content, results)
        subject = {"ligand_ga_result_handle": handle}

        def claim(statement: str, path: str, quantity: str, unit: str, value: Any, rounding: str,
                  operation: str | None = None, selector: dict[str, Any] | None = None) -> dict[str, Any]:
            return _claim(statement, handle, path, selector, {**subject, **(selector or {})}, quantity, unit, value,
                          rounding, operation)

        receptor = content["receptor"]
        claims = [claim("receptor_input", "receptor.handle", "receptor_import", "handle", receptor["handle"],
                        "identifier"),
                  claim("receptor_input", "receptor.sha256", "receptor_sha256", "sha256", receptor["sha256"],
                        "identifier"),
                  claim("receptor_input", "receptor.model_number", "receptor_model_number", "model_number",
                        receptor["model_number"], "integer")]
        removed = receptor["removed_instance"]
        if removed is not None:
            for field in RESIDUE_FIELDS:
                claims.append(claim("removed_instance", f"receptor.removed_instance.residue.{field}",
                                    f"removed_instance_{field}", "residue_field", removed["residue"][field], "json"))
            claims.append(claim("removed_instance", "receptor.removed_instance.atom_count",
                                "removed_instance_atom_count", "count", removed["atom_count"], "integer"))
        for key in ("candidate_set_handle", "parent_sdf_handle"):
            claims.append(claim("candidate_set_input", key, key, "identifier", content[key], "identifier"))
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
            if params.get(key) is not None:
                claims.append(claim("parameter", f"parameters.{key}", key,
                                    "kcal/mol" if key == "energy_range" else "count" if key != "seed" else "seed",
                                    params[key], "input_decimal" if key == "energy_range" else "integer"))
        for key in GC.GA_KEYS:
            float_key = key in GC.GA_FLOAT_KEYS
            claims.append(claim("ga_parameter", f"ga.{key}", f"ga_{key}",
                                "fraction" if float_key else "s" if key == "total_s" else
                                "seed" if key == "seed" else "count", content["ga"][key],
                                "input_decimal" if float_key else "integer"))
        for key in POOL_COUNTS:
            claims.append(claim("pool_count", f"pool.{key}", f"pool_{key}", "count", content["pool"][key],
                                "integer"))
        generations = content["generations"]
        evaluated = [e for e in _individuals(content) if e["origin"] != "carried"]
        recounted = {"generations_done": (sum(g["complete"] is True for g in generations),
                                          "count_where(complete == true; generations)"),
                     "new_dockings_used": (sum(e["evaluation"] == "docked" for e in evaluated),
                                           "count_where(evaluation == docked; generations[*].individuals)"),
                     "reused_count": (sum(e["evaluation"] == "reused" for e in evaluated),
                                      "count_where(evaluation == reused; generations[*].individuals)"),
                     "reserved_units": (content["reserved_units"], None)}
        for key in RUN_COUNTS:
            value, operation = recounted[key]
            claims.append(claim("run_count", key, key, "count", value, "integer", operation))
        for position_g, gen in enumerate(generations):
            number = gen["index"]
            individuals = gen["individuals"]
            base = f"generations[{position_g}].individuals"
            claims.append(claim("generation_count", base, "individuals", "count", len(individuals), "integer",
                                f"count({base})", {"generation": number, "where": None}))
            for state in GC.STATES:
                claims.append(claim("generation_count", base, f"{state}_individuals", "count",
                                    sum(e["state"] == state for e in individuals), "integer",
                                    f"count_where(state == {state}; {base})",
                                    {"generation": number, "where": f"state == {state}"}))
            for key in ("min_score", "max_score"):
                if gen[key] is not None:
                    claims.append(claim("generation_score_range", f"generations[{position_g}].{key}", key,
                                        "kcal/mol", gen[key], "score_1dp", None, {"generation": number}))
            for position, entry in enumerate(individuals):
                if entry["state"] != "scored":
                    continue
                selector = {"generation": number, "position": position}
                result_handle = entry["result_handle"]
                who = {**subject, **selector, "candidate_id": entry["candidate_id"]}
                claims.append(_claim("individual_score", handle, f"{base}[{position}].score", selector, who,
                                     "score_kcal_mol", "kcal/mol", entry["score"], "score_1dp"))
                claims.append(_claim("individual_result_score", result_handle, "modes[0].score_kcal_mol", selector,
                                     {**who, "docking_result_handle": result_handle}, "score_kcal_mol",
                                     "kcal/mol", results[result_handle]["modes"][0]["score_kcal_mol"], "score_1dp"))
        return claims
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise EvidenceError("ligand_ga_report_evidence_unresolved") from exc


def _key(claim: dict[str, Any]) -> tuple[str, str, str, bytes]:
    return claim["statement_id"], claim["source_handle"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim rebuilt from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("ligand_ga_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("ligand_ga_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS:
        raise EvidenceError("ligand_ga_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("ligand_ga_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != SOURCES[statement]:
        raise EvidenceError("ligand_ga_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims if claim["statement_id"] == statement}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("ligand_ga_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("ligand_ga_claim_shape") from exc
    if match is None:
        raise EvidenceError("ligand_ga_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("ligand_ga_claim_binding_mismatch")
    return proposed


def validate_ligand_ga_claim(run: Any, summary_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, summary_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored summary and the individuals' results."""
    try:
        content = LJ.validated_summary(run, handle)
        source = LJ.summary_producer(run, handle)
        handles = list(dict.fromkeys(e["result_handle"] for e in _individuals(content)
                                     if e["result_handle"] is not None))
        results = {item: db.validated_result(run, item) for item in handles}
        individuals = [{"result_handle": item, **{key: producer[key] for key in ("job_id", "attempt_id")},
                        "protocol_id": producer["job"]["protocol_id"]}
                       for item in handles for producer in (db.producer(run, item),)]
    except (LJ.LigandGaEvidenceError, db.DockingEvidenceError) as exc:
        raise EvidenceError(f"ligand_ga_result_invalid: {exc}") from exc
    try:
        ids = content["limitations"]
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": SUMMARY_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS}, "ga_status": content["status"],
                "method": METHODS[GC.MODE], "score_label": SCORE_LABEL, "score_column_label": SCORE_COLUMN_LABEL,
                "score_row_label": GC.SCORE_ROW_LABEL, "claims": claims_for(handle, content, results),
                "provenance": {"ligand_ga": {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
                                             "protocol_id": source["job"]["protocol_id"],
                                             "tool_id": source["job"]["tool_id"],
                                             "created_event_seq": source["created_seq"],
                                             "completed_event_seq": source["published_seq"]},
                               "individuals": individuals},
                "evidence_statement": EVIDENCE_STATEMENT, "limitation_ids": ids,
                "limitations": [GC.STATEMENTS[item] for item in ids]}
    except EvidenceError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("ligand_ga_report_evidence_unresolved") from exc


def capability_snapshot() -> dict[str, Any]:
    """GA capability status and pins at report creation (nothing is docked)."""
    value = LJ.capability()
    return {key: value[key] for key in CAPABILITY_KEYS}


def capability_snapshot_valid(value: Any) -> bool:
    if type(value) is not dict or set(value) != set(CAPABILITY_KEYS):
        return False
    ready = value["status"] == "ready"
    if not (ready or value["status"] in db.REASONS) or value["available"] is not ready:
        return False
    if not ready:
        return value["reason_code"] == value["status"] and value["pins"] is None and value["ga_pins"] is None
    try:
        db._pins(value["pins"])
    except db.DockingEvidenceError:
        return False
    pins = value["ga_pins"]
    return (value["reason_code"] is None and type(pins) is dict and
            set(pins) == {"ga_worker_sha256", "ga_constants_sha256"} and
            all(type(item) is str and SHA_RE.fullmatch(item) for item in pins.values()))


# ---------------------------------------------------------------------------------------------------------------
# Markdown

def render_ligand_ga_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every engine number is the rendered text of a bound claim."""
    claims = manifest["claims"]

    def value(statement: str, path: str | None = None, **selector: Any) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and
                 (path is None or c["field_path"] == path) and
                 all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("ligand_ga_report_claim_missing")
        return found[0]

    def score(number: int, index: int, position: int) -> str:
        text = value("individual_score", f"generations[{index}].individuals[{position}].score",
                     generation=number, position=position)
        if value("individual_result_score", "modes[0].score_kcal_mol", generation=number, position=position) != text:
            raise EvidenceError("ligand_ga_report_score_trace_mismatch")
        return text

    receptor = manifest["receptor"]
    job = manifest["provenance"]["ligand_ga"]
    pins = manifest["pins"]
    stop = manifest["stop_reason"]
    lines = ["# 리간드 GA 설계 보고서 (ligand GA design)", "", "Status: complete", "",
             f"GA summary: {_md(manifest['result_handle'])}",
             f"GA job: {_md(job['job_id'])}, attempt {_md(job['attempt_id'])}",
             (f"Protocol: {_md(manifest['protocol'])}; individual method: {_md(manifest['method'])} (자유 도킹, "
              "개체마다 단독 M18 결과)"),
             (f"Engine: {_md(manifest['engine'])} (package {_md(pins['qvina_package'])}, binary SHA-256 "
              f"{_md(pins['qvina_sha256'])})"),
             f"Selection SHA-256: {_md(manifest['selection_sha256'])}",
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             f"- 점수 이름: {SCORE_LABEL}",
             f"- 점수 열: 각 개체 결과의 첫 행, {manifest['score_row_label']}",
             f"- GA 상태: {_md(manifest['ga_status'])}, 종료 이유 {_md(stop)}"
             + (f" ({NO_CHANGE_LABEL})" if stop == "no_change" else ""),
             (f"- 완료 세대: {value('run_count', 'generations_done')}; 새 도킹: "
              f"{value('run_count', 'new_dockings_used')}; 재사용: {value('run_count', 'reused_count')}; "
              f"예약 단위: {value('run_count', 'reserved_units')}"), "",
             "## 수용체", "",
             f"- 가져오기: {_md(value('receptor_input', 'receptor.handle'))}",
             f"- SHA-256: {_md(value('receptor_input', 'receptor.sha256'))}",
             f"- 모델 번호: {value('receptor_input', 'receptor.model_number')}",
             f"- 연결 정보: {_md(receptor['connectivity']['kind'])}",
             "- 입력 확인 세 항목: " + ", ".join(f"{_md(key)} {'true' if item is True else 'false'}"
                                          for key, item in receptor["acknowledgement"].items())]
    if receptor["removed_instance"] is None:
        lines.append("- 뺀 리간드 인스턴스: 없음")
    else:
        prefix = "receptor.removed_instance"
        lines.append("- 뺀 리간드 인스턴스: " + ", ".join(
            f"{_md(field)} {_md(value('removed_instance', f'{prefix}.residue.{field}'))}" for field in RESIDUE_FIELDS)
            + f"; 원자 {value('removed_instance', f'{prefix}.atom_count')}개")
    lines.extend(["", "## 후보 풀", "",
                  f"- 후보 집합: {_md(value('candidate_set_input', 'candidate_set_handle'))}",
                  f"- 부모 SDF 가져오기: {_md(value('candidate_set_input', 'parent_sdf_handle'))}",
                  f"- 필터 사양: {_md(canonical_json(manifest['filter']).decode('utf-8'))}",
                  (f"- 풀 크기: {value('pool_count', 'pool.size')}; 적격 {value('pool_count', 'pool.eligible_count')}, "
                   f"필터 탈락 {value('pool_count', 'pool.filter_excluded_count')}"),
                  "", "## 상자 (Å)", "",
                  f"- 출처: {_md(value('box', 'box.source'))}"
                  + ("" if manifest["box"]["margin_A"] is None else f", 여백 {value('box', 'box.margin_A')} Å"),
                  "- 중심 x, y, z: " + ", ".join(value("box", f"box.center_A[{axis}]") for axis in range(3)),
                  "- 크기 x, y, z: " + ", ".join(value("box", f"box.size_A[{axis}]") for axis in range(3)),
                  "- 좌표계: 리간드 좌표가 수용체와 같은 좌표계라고 가정했다(도구가 검증하지 못한다).",
                  "", "## 도킹 값", ""])
    for key in PARAMETERS:
        if manifest["parameters"].get(key) is not None:
            unit = " kcal/mol" if key == "energy_range" else ""
            lines.append(f"- {_md(key)}: {value('parameter', f'parameters.{key}')}{unit}")
    lines.extend(["", "## GA 값", ""])
    for key in GC.GA_KEYS:
        lines.append(f"- {_md(key)}: {value('ga_parameter', f'ga.{key}')}{' s' if key == 'total_s' else ''}")
    for index, gen in enumerate(manifest["generations"]):
        number = gen["index"]
        counts = ", ".join(f"{_md(state)} {value('generation_count', None, generation=number, where=f'state == {state}')}"
                           for state in GC.STATES)
        lines.extend(["", f"## 세대 {number} ({'완료' if gen['complete'] else '중간에 멈춤'})", "",
                      f"- 개체 수: {value('generation_count', None, generation=number, where=None)}; {counts}"])
        if gen["min_score"] is None:
            lines.append("- 점수 최솟값·최댓값: 점수 있는 개체 없음")
        else:
            lines.append(f"- 점수 최솟값 {value('generation_score_range', f'generations[{index}].min_score')}, "
                         f"최댓값 {value('generation_score_range', f'generations[{index}].max_score')} (값만)")
        lines.extend(["", (f"| 자리 | 후보 id | 출처 | 부모 후보 id | 유사도(지문 Tanimoto) | 평가 | 평가 순서 | 상태 | "
                           f"{SCORE_COLUMN_LABEL} | 점수 대상 | 이유 | 개체별 결과 |"),
                      "| ---: | --- | --- | --- | ---: | --- | ---: | --- | ---: | --- | --- | --- |"])
        ordered = sorted(enumerate(gen["individuals"]), key=lambda item: item[1]["state"] != "scored")
        for position, entry in ordered:
            scored = entry["state"] == "scored"
            cells = [str(position), _md(entry["candidate_id"]), ORIGIN_LABELS[entry["origin"]],
                     "" if entry["parent_candidate_id"] is None else _md(entry["parent_candidate_id"]),
                     "" if entry["similarity"] is None else _md(entry["similarity"]),
                     "" if entry["evaluation"] is None else EVALUATION_LABELS[entry["evaluation"]],
                     "" if entry["eval_index"] is None else str(entry["eval_index"]), _md(entry["state"]),
                     score(number, index, position) if scored else "",
                     manifest["score_row_label"] if scored else "",
                     "" if entry["reason_code"] is None else _md(entry["reason_code"]),
                     "" if entry["result_handle"] is None else _md(entry["result_handle"])]
            lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, units, field paths and conditions are in the JSON download "
                   f"({len(claims)} claims). Individual results open in the ligand tab docking reads; this report "
                   "makes no per-individual docking report. The table order is a display order only."), ""])
    return check_no_interpretation("\n".join(lines))


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_ligand_ga_report(run: Any, summary_handle: str) -> dict[str, Any]:
    """New report object for one stored GA summary (nothing is docked again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, summary_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "capability": capability_snapshot(),
                                "budget": run.budget_snapshot()}
        markdown = render_ligand_ga_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("ligand_ga_report_too_large")
        produced_by = f"ligand_ga_report_{uuid.uuid4().hex}"
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


def saved_ligand_ga_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored GA report without docking again."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("ligand_ga_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("ligand_ga_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("ligand_ga_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"ligand_ga_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["ligand_ga"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not capability_snapshot_valid(snapshot["capability"]) or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("ligand_ga_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("ligand_ga_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("ligand_ga_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("ligand_ga_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_ligand_ga_report(report):
        raise EvidenceError("ligand_ga_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
