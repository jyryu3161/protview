"""Immutable, field-cited reports for one ``sequence_ga_result@1`` (``method_report_manifest@1``,
``analysis_type: "sequence_ga"``, render ``sequence_ga_markdown@1``; spec .dryforge/spec.md 4, 5, 9). Mirrors the M22
GA report (``ligand_ga_reports``).

The input is one sequence GA summary handle. Every value statement is ``computed`` evidence bound to one handle and one
field path. Statement IDs (closed set ``STATEMENTS``):

- on the summary (``sequence_ga_result``): ``candidate_set_input`` (``candidate_set``), ``structure_input``
  (``structure.handle``, ``structure.model_number``), ``ligand_input`` (``ligand.sdf_handle``, ``ligand.sdf_sha256``),
  ``box`` (``box.source``, ``box.center_A[i]``, ``box.size_A[i]``, ``box.margin_A``; none when no box exists),
  ``parameter`` (the M18 values), ``ga_parameter`` (every ``ga`` key), ``space_count`` (``space.positions``,
  ``space.candidates``, ``space.effective_max_mutations``, ``space.size``), ``run_count`` (``generations_done``,
  ``new_evaluations_used``, ``reused_count`` recounted with ``count_where`` over the stored generations and individuals
  at every validation; ``reserved_evaluations``, ``reserved_units``), ``generation_count`` (per generation ``count`` /
  ``count_where(state == ...)``), ``generation_score_range`` (the stored ``min_score`` / ``max_score``, values only,
  each an extreme of that generation's stored individual scores), ``individual_score``
  (``generations[g].individuals[p].score``, ``scored`` individuals only) and ``reference_score`` (``reference.score``,
  a ``scored`` wild-type reference row only);
- on a row's docking result (``docking_result``): ``individual_result_score`` and ``reference_result_score``
  (``modes[0].score_kcal_mol``, the score target "모드 1(엔진 출력 순서)").

Both individual score claims carry ``row_selector {"generation": g, "position": p}`` and must hold the same value (so
do the two reference claims, ``row_selector`` null); the table cell is rendered from them (``Decimal(str(v))`` to 0.1,
``ROUND_HALF_UP``). Rows without a score (``null_result``, ``failed``) and slots that were never computed have no score
claim, so a score for them is refused and their cell stays empty (never 0); they are listed after the scored ones of
their generation (display order only). Parents, edit operations and pick order are copied worker records (S1). There
is no OpenMM potential, protonation, structure-to-structure, wild-type-relative or derived claim: the models are cited
by handle in ``provenance`` only.

Creating, reopening and downloading never model or dock again: the summary is re-validated with
``sequence_ga_jobs.validated_summary`` on one read view, every manifest field and claim is compared with the one
rebuilt from the stored objects, and the Markdown is compared byte for byte with a re-render. Values and identifiers
are slots: the forbidden-word check runs on every line of the fixed template with the slots empty (M20 rule), so an
identifier cannot fail a report and the template can never say a forbidden word. The forbidden words are the M22 list
plus wild-type-relative, difference, change, comparison, stability, ΔΔG and potential wording; the only exemptions are
a line exactly equal to a fixed sentence S1-S6 (they name 순위·추천·ΔΔG·안정성 only to deny them) or to the score name
(``SCORE_LABEL``), which is also removed from any other line before that line is checked.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from . import docking_bundle as db
from . import docking_reports as dr
from . import ligand_ga_reports as gr
from . import sequence_ga_constants as SC
from . import sequence_ga_inputs as GI
from . import sequence_ga_jobs as SJ
from .core.handles import canonical_json
from .docking_constants import METHODS, SCORE_COLUMN_LABEL
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md
from .sequence_ga_bundle import SequenceGaEvidenceError

ANALYSIS_TYPE = "sequence_ga"
RENDER_VERSION = "sequence_ga_markdown@1"
SUMMARY_KIND, SUMMARY_SCHEMA = SC.OUTPUT_KIND, SC.SUMMARY_SCHEMA
RESULT_KIND, RESULT_SCHEMA = db.OUTPUT_KIND, "docking_result@1"
SCORE_LABEL = SC.SCORE_LABEL
REPORT_BYTES = dr.REPORT_BYTES
PARAMETERS = dr.PARAMETERS
RUN_COUNTS = ("generations_done", "new_evaluations_used", "reused_count", "reserved_evaluations", "reserved_units")
SPACE_COUNTS = ("positions", "candidates", "effective_max_mutations", "size")
ORIGIN_LABELS = {"initial": "초기", "carried": "다음 세대로 이어받음", "crossover": "교차", "edit": "편집",
                 "random": "무작위"}
EDIT_LABELS = {"add": "추가", "change": "바꿈", "move": "옮김", "remove": "뺌"}
EVALUATION_LABELS = {"reused": "재사용", "computed": "새 평가"}
NO_CHANGE_LABEL = "점수 최솟값 변화 없음"
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 서열 GA 요약 객체의 값, 요약의 세대·개체를 조건으로 센 개수, 점수 있는 개체와 "
                      "야생형 기준 행이 가리키는 도킹 결과 객체의 첫 행 점수다. 보고서는 모델링·도킹을 다시 하지 않았다.")
FIXED_LINES = frozenset({*SC.STATEMENTS.values(), SCORE_LABEL})
render_score = dr.render_score
_render = dr._render

STATEMENTS = {
    "candidate_set_input": re.compile(r"candidate_set"),
    "structure_input": re.compile(r"structure\.(handle|model_number)"),
    "ligand_input": re.compile(r"ligand\.(sdf_handle|sdf_sha256)"),
    "box": dr.STATEMENTS["box"],
    "parameter": dr.STATEMENTS["parameter"],
    "ga_parameter": re.compile(r"ga\.(" + "|".join(SC.GA_KEYS) + ")"),
    "space_count": re.compile(r"space\.(" + "|".join(SPACE_COUNTS) + ")"),
    "run_count": re.compile("|".join(RUN_COUNTS)),
    "generation_count": re.compile(r"generations\[\d+\]\.individuals"),
    "generation_score_range": re.compile(r"generations\[\d+\]\.(min_score|max_score)"),
    "individual_score": re.compile(r"generations\[\d+\]\.individuals\[\d+\]\.score"),
    "individual_result_score": re.compile(r"modes\[0\]\.score_kcal_mol"),
    "reference_score": re.compile(r"reference\.score"),
    "reference_result_score": re.compile(r"modes\[0\]\.score_kcal_mol"),
}
RESULT_STATEMENTS = ("individual_result_score", "reference_result_score")
SOURCES = {statement: (RESULT_KIND, RESULT_SCHEMA) if statement in RESULT_STATEMENTS else
           (SUMMARY_KIND, SUMMARY_SCHEMA) for statement in STATEMENTS}
EVIDENCE_KINDS = ("computed",)
CLAIM_KEYS = dr.CLAIM_KEYS
# The M22 list (M18 ranking, best, improvement, binding strength; GA winner, average, recommendation, superiority)
# plus the M23 additions (spec 5, 9): wild-type-relative or parent-relative wording, difference, increase/decrease,
# change amount, comparison, stability, ΔΔG, and OpenMM potential / energy wording (the report has no such claim).
INTERPRETIVE = re.compile(
    gr.INTERPRETIVE.pattern + r"|야생형\s*대비|대비|차이|증감|변화량|비교|안정성|stabil|ΔΔG|ddG|delta|\bdiff|compar|"
    r"전위|에너지|energ|\bkJ", re.IGNORECASE)
CAPABILITY_KEYS = ("available", "status", "reason_code", "pins")
SNAPSHOT_KEYS = dr.SNAPSHOT_KEYS
COPIED_FIELDS = ("protocol", "engine", "candidate_set", "structure", "ligand", "box", "parameters", "selection_policy",
                 "hydrogen_policy", "method", "pins", "call_key", "conditions_sha256", "selection_sha256", "ga",
                 "space", "stop_reason", *RUN_COUNTS, "reference", "generations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "ga_status", "docking_method", "score_label", "score_column_label",
    "score_row_label", "claims", "provenance", "evidence_statement", "limitation_ids", "limitations", "snapshot",
    "markdown_handle"})
_SLOT = re.compile("\x00(\\d+)\x00")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on every line. A line exactly equal to a fixed S sentence or to the score name is
    exempt; on any other line only the exact score-name text is removed before the check."""
    for line in text.split("\n"):
        if line in FIXED_LINES:
            continue
        match = INTERPRETIVE.search(line.replace(SCORE_LABEL, ""))
        if match is not None:
            raise EvidenceError(f"sequence_ga_report_interpretive_statement: {match.group(0)}")
    return text


def mutation_label(row: dict[str, Any]) -> str:
    """``A:K6A``: chain (auth, else label), from, residue number (auth, else label) with insertion code, to."""
    residue = row["residue"]
    chain = residue["chain_auth"] if residue["chain_auth"] is not None else residue["chain_label"]
    number = residue["seq_auth"] if residue["seq_auth"] is not None else residue["seq_label"]
    return f"{chain}:{row['from']}{number}{residue['icode'] or ''}{row['to']}"


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
    """Free docking only, every scored row's summary score is its result's first-row score, and every stored
    generation minimum and maximum is an extreme of that generation's stored scores."""
    method = METHODS[SC.MODE]
    for entry in [content["reference"], *_individuals(content)]:
        if entry["result_handle"] is None:
            continue
        result = results[entry["result_handle"]]
        if result["method"] != method or result["inputs"]["mode"] != SC.MODE:
            raise EvidenceError("sequence_ga_report_method_mismatch")
        if entry["state"] == "scored" and (not result["modes"] or
                                           result["modes"][0]["score_kcal_mol"] != entry["score"]):
            raise EvidenceError("sequence_ga_report_score_trace_mismatch")
    for gen in content["generations"]:
        scores = [results[e["result_handle"]]["modes"][0]["score_kcal_mol"] for e in gen["individuals"]
                  if e["state"] == "scored"]
        if (gen["min_score"], gen["max_score"]) != ((min(scores), max(scores)) if scores else (None, None)):
            raise EvidenceError("sequence_ga_report_score_trace_mismatch")


def claims_for(handle: str, content: dict[str, Any], results: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; counts are recounted from the stored generations and individuals."""
    try:
        _required(content, results)
        subject = {"sequence_ga_result_handle": handle}

        def claim(statement: str, path: str, quantity: str, unit: str, value: Any, rounding: str,
                  operation: str | None = None, selector: dict[str, Any] | None = None) -> dict[str, Any]:
            return _claim(statement, handle, path, selector, {**subject, **(selector or {})}, quantity, unit, value,
                          rounding, operation)

        claims = [claim("candidate_set_input", "candidate_set", "candidate_set", "identifier",
                        content["candidate_set"], "identifier"),
                  claim("structure_input", "structure.handle", "structure", "identifier",
                        content["structure"]["handle"], "identifier"),
                  claim("structure_input", "structure.model_number", "structure_model_number", "model_number",
                        content["structure"]["model_number"], "integer"),
                  claim("ligand_input", "ligand.sdf_handle", "ligand_sdf", "identifier",
                        content["ligand"]["sdf_handle"], "identifier"),
                  claim("ligand_input", "ligand.sdf_sha256", "ligand_sdf_sha256", "sha256",
                        content["ligand"]["sdf_sha256"], "identifier")]
        box = content["box"]
        if box is not None:
            claims.append(claim("box", "box.source", "box_source", "identifier", box["source"], "identifier"))
            for key in ("center_A", "size_A"):
                for axis in range(3):
                    claims.append(claim("box", f"box.{key}[{axis}]", f"box_{key}_{'xyz'[axis]}", "A",
                                        box[key][axis], "distance_2dp"))
            if box["margin_A"] is not None:
                claims.append(claim("box", "box.margin_A", "box_margin_A", "A", box["margin_A"], "distance_2dp"))
        params = content["parameters"]
        for key in PARAMETERS:
            if params.get(key) is not None:
                claims.append(claim("parameter", f"parameters.{key}", key,
                                    "kcal/mol" if key == "energy_range" else "count" if key != "seed" else "seed",
                                    params[key], "input_decimal" if key == "energy_range" else "integer"))
        for key in SC.GA_KEYS:
            float_key = key in SC.GA_FLOAT_KEYS
            claims.append(claim("ga_parameter", f"ga.{key}", f"ga_{key}",
                                "fraction" if float_key else "s" if key == "total_s" else
                                "seed" if key == "seed" else "count", content["ga"][key],
                                "input_decimal" if float_key else "integer"))
        for key in SPACE_COUNTS:
            claims.append(claim("space_count", f"space.{key}", f"space_{key}", "count", content["space"][key],
                                "integer"))
        generations = content["generations"]
        evaluated = [e for e in _individuals(content) if e["origin"] != "carried"]
        recounted = {"generations_done": (sum(g["complete"] is True for g in generations),
                                          "count_where(complete == true; generations)"),
                     "new_evaluations_used": (sum(e["evaluation"] == "computed" for e in evaluated),
                                              "count_where(evaluation == computed; generations[*].individuals)"),
                     "reused_count": (sum(e["evaluation"] == "reused" for e in evaluated),
                                      "count_where(evaluation == reused; generations[*].individuals)"),
                     "reserved_evaluations": (content["reserved_evaluations"], None),
                     "reserved_units": (content["reserved_units"], None)}
        for key in RUN_COUNTS:
            value, operation = recounted[key]
            claims.append(claim("run_count", key, key, "count", value, "integer", operation))
        reference = content["reference"]
        if reference["state"] == "scored":
            who = {**subject, "key": SC.REFERENCE_KEY}
            result_handle = reference["result_handle"]
            claims.append(_claim("reference_score", handle, "reference.score", None, who, "score_kcal_mol",
                                 "kcal/mol", reference["score"], "score_1dp"))
            claims.append(_claim("reference_result_score", result_handle, "modes[0].score_kcal_mol", None,
                                 {**who, "docking_result_handle": result_handle}, "score_kcal_mol", "kcal/mol",
                                 results[result_handle]["modes"][0]["score_kcal_mol"], "score_1dp"))
        for position_g, gen in enumerate(generations):
            number = gen["index"]
            individuals = gen["individuals"]
            base = f"generations[{position_g}].individuals"
            claims.append(claim("generation_count", base, "individuals", "count", len(individuals), "integer",
                                f"count({base})", {"generation": number, "where": None}))
            for state in SC.STATES:
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
                who = {**subject, **selector, "key": entry["key"]}
                claims.append(_claim("individual_score", handle, f"{base}[{position}].score", selector, who,
                                     "score_kcal_mol", "kcal/mol", entry["score"], "score_1dp"))
                claims.append(_claim("individual_result_score", result_handle, "modes[0].score_kcal_mol", selector,
                                     {**who, "docking_result_handle": result_handle}, "score_kcal_mol",
                                     "kcal/mol", results[result_handle]["modes"][0]["score_kcal_mol"], "score_1dp"))
        return claims
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise EvidenceError("sequence_ga_report_evidence_unresolved") from exc


def _key(claim: dict[str, Any]) -> tuple[str, str, str, bytes]:
    return claim["statement_id"], claim["source_handle"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim rebuilt from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("sequence_ga_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("sequence_ga_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS:
        raise EvidenceError("sequence_ga_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("sequence_ga_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != SOURCES[statement]:
        raise EvidenceError("sequence_ga_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims if claim["statement_id"] == statement}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("sequence_ga_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("sequence_ga_claim_shape") from exc
    if match is None:
        raise EvidenceError("sequence_ga_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("sequence_ga_claim_binding_mismatch")
    return proposed


def validate_sequence_ga_claim(run: Any, summary_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, summary_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _rows(content: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The reference row, then every evaluated (non-carried) individual in listing order."""
    return [(SC.REFERENCE_KEY, content["reference"]),
            *((entry["key"], entry) for entry in _individuals(content) if entry["origin"] != "carried")]


def _provenance_rows(view: Any, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Each row with a stored model or result: its handles and their first publications (a reused row keeps the GA
    that computed it)."""
    out = []
    for key, entry in _rows(content):
        model, result = entry["model_handle"], entry["result_handle"]
        if model is None and result is None:
            continue
        made = None if model is None else SJ.model_producer(view, model)
        docked = None if result is None else db.producer(view, result)
        out.append({"key": key, "model_handle": model,
                    "model_job_id": None if made is None else made["job_id"],
                    "model_attempt_id": None if made is None else made["attempt_id"], "result_handle": result,
                    "result_job_id": None if docked is None else docked["job_id"],
                    "result_attempt_id": None if docked is None else docked["attempt_id"],
                    "result_protocol_id": None if docked is None else docked["job"]["protocol_id"]})
    return out


def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored summary and its rows' stored objects (one read
    view: the event log is read once)."""
    view = SJ.snapshot(run)
    try:
        content = SJ.validated_summary(view, handle)
        source = SJ.summary_producer(view, handle)
        handles = list(dict.fromkeys(e["result_handle"] for e in [content["reference"], *_individuals(content)]
                                     if e["result_handle"] is not None))
        results = {item: db.validated_result(view, item) for item in handles}
        rows = _provenance_rows(view, content)
    except (SequenceGaEvidenceError, db.DockingEvidenceError) as exc:
        raise EvidenceError(f"sequence_ga_result_invalid: {exc}") from exc
    try:
        ids = content["limitations"]
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": SUMMARY_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS}, "ga_status": content["status"],
                "docking_method": METHODS[SC.MODE], "score_label": SCORE_LABEL,
                "score_column_label": SCORE_COLUMN_LABEL, "score_row_label": SC.SCORE_ROW_LABEL,
                "claims": claims_for(handle, content, results),
                "provenance": {"sequence_ga": {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
                                               "protocol_id": source["job"]["protocol_id"],
                                               "tool_id": source["job"]["tool_id"],
                                               "created_event_seq": source["created_seq"],
                                               "completed_event_seq": source["published_seq"]},
                               "rows": rows},
                "evidence_statement": EVIDENCE_STATEMENT, "limitation_ids": ids,
                "limitations": [SC.STATEMENTS[item] for item in ids]}
    except EvidenceError:
        raise
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("sequence_ga_report_evidence_unresolved") from exc


def capability_snapshot() -> dict[str, Any]:
    """Sequence GA capability status and pins at report creation (nothing is modelled or docked)."""
    value = SJ.capability()
    return {key: value[key] for key in CAPABILITY_KEYS}


def capability_snapshot_valid(value: Any) -> bool:
    if type(value) is not dict or set(value) != set(CAPABILITY_KEYS):
        return False
    ready = value["status"] == "ready"
    if not (ready or value["status"] in SJ.REASONS) or value["available"] is not ready:
        return False
    if not ready:
        return value["reason_code"] == value["status"] and value["pins"] is None
    try:
        GI.check_pins(value["pins"])
    except ValueError:
        return False
    return value["reason_code"] is None


# ---------------------------------------------------------------------------------------------------------------
# Markdown

def render_sequence_ga_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every engine number is the rendered text of a bound claim. Values and
    identifiers go into slots; the forbidden-word check runs on the template with the slots empty, then the slots are
    filled."""
    claims = manifest["claims"]
    slots: list[str] = []

    def slot(text: str) -> str:
        slots.append(text)
        return f"\x00{len(slots) - 1}\x00"

    def md(item: Any) -> str:
        return slot(_md(item))

    def rendered(statement: str, path: str | None = None, **selector: Any) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and
                 (path is None or c["field_path"] == path) and
                 all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("sequence_ga_report_claim_missing")
        return found[0]

    def value(statement: str, path: str | None = None, **selector: Any) -> str:
        return slot(rendered(statement, path, **selector))

    def identifier(statement: str, path: str) -> str:
        return md(rendered(statement, path))

    def score(number: int, index: int, position: int) -> str:
        text = rendered("individual_score", f"generations[{index}].individuals[{position}].score",
                        generation=number, position=position)
        if rendered("individual_result_score", "modes[0].score_kcal_mol", generation=number,
                    position=position) != text:
            raise EvidenceError("sequence_ga_report_score_trace_mismatch")
        return slot(text)

    def reference_score() -> str:
        text = rendered("reference_score", "reference.score")
        if rendered("reference_result_score", "modes[0].score_kcal_mol") != text:
            raise EvidenceError("sequence_ga_report_score_trace_mismatch")
        return slot(text)

    def handle_or_none(item: Any) -> str:
        return "없음" if item is None else md(item)

    job = manifest["provenance"]["sequence_ga"]
    pins = manifest["method"]["docking"]
    stop = manifest["stop_reason"]
    row_label = manifest["score_row_label"]
    lines = ["# 서열 GA 설계 보고서 (sequence GA design)", "", "Status: complete", "",
             f"GA summary: {md(manifest['result_handle'])}",
             f"GA job: {md(job['job_id'])}, attempt {md(job['attempt_id'])}",
             (f"Protocol: {md(manifest['protocol'])}; individual docking method: {md(manifest['docking_method'])} "
              "(자유 도킹, 개체마다 단독 M18 결과)"),
             (f"Individual model: {md(SC.MODEL_SCHEMA)} (PDBFixer + OpenMM, 단백질만. 이 보고서는 모델의 값을 싣지 "
              "않고 handle만 적는다)"),
             (f"Engine: {md(manifest['engine'])} (package {md(pins['qvina_package'])}, binary SHA-256 "
              f"{md(pins['qvina_sha256'])})"),
             f"Selection SHA-256: {md(manifest['selection_sha256'])}",
             f"Conditions SHA-256: {md(manifest['conditions_sha256'])}",
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             f"- 점수 이름: {SCORE_LABEL}",
             f"- 점수 열: 각 개체 결과의 첫 행, {row_label}",
             f"- GA 상태: {md(manifest['ga_status'])}, 종료 이유 {md(stop)}"
             + (f" ({NO_CHANGE_LABEL})" if stop == "no_change" else ""),
             (f"- 완료 세대: {value('run_count', 'generations_done')}; 새 평가: "
              f"{value('run_count', 'new_evaluations_used')}; 재사용: {value('run_count', 'reused_count')}; "
              f"예약 평가: {value('run_count', 'reserved_evaluations')}; "
              f"예약 단위: {value('run_count', 'reserved_units')}"),
             "", "## 입력", "",
             f"- 변이 후보 집합: {identifier('candidate_set_input', 'candidate_set')}",
             (f"- 구조: {identifier('structure_input', 'structure.handle')}, 모델 번호 "
              f"{value('structure_input', 'structure.model_number')}"),
             (f"- 리간드 SDF 가져오기: {identifier('ligand_input', 'ligand.sdf_handle')} (SHA-256 "
              f"{identifier('ligand_input', 'ligand.sdf_sha256')})"),
             f"- 선택 정책: {md(manifest['selection_policy'])}; 수소 정책: {md(manifest['hydrogen_policy'])}",
             "", "## 조합 공간", "",
             (f"- 위치: {value('space_count', 'space.positions')}; 후보: {value('space_count', 'space.candidates')}; "
              f"유효 동시 변이 수 상한: {value('space_count', 'space.effective_max_mutations')}; "
              f"조합 수: {value('space_count', 'space.size')}"),
             "", "## 상자 (Å)", ""]
    box = manifest["box"]
    if box is None:
        lines.append("- 상자: 없음. 기준 행의 도킹이 리간드·상자 이유로 거절되어 작업 모듈이 상자를 만들지 않았다.")
    else:
        lines.extend([f"- 출처: {identifier('box', 'box.source')}"
                      + ("" if box["margin_A"] is None else f", 여백 {value('box', 'box.margin_A')} Å"),
                      "- 중심 x, y, z: " + ", ".join(value("box", f"box.center_A[{axis}]") for axis in range(3)),
                      "- 크기 x, y, z: " + ", ".join(value("box", f"box.size_A[{axis}]") for axis in range(3)),
                      "- 좌표계: 리간드 좌표가 구조와 같은 좌표계라고 가정했다(도구가 검증하지 못한다)."])
    lines.extend(["", "## 도킹 값", ""])
    for key in PARAMETERS:
        if manifest["parameters"].get(key) is not None:
            unit = " kcal/mol" if key == "energy_range" else ""
            lines.append(f"- {md(key)}: {value('parameter', f'parameters.{key}')}{unit}")
    lines.extend(["", "## GA 값", ""])
    for key in SC.GA_KEYS:
        lines.append(f"- {md(key)}: {value('ga_parameter', f'ga.{key}')}{' s' if key == 'total_s' else ''}")
    reference = manifest["reference"]
    lines.extend(["", "## 야생형 기준 행 (참고 행, 값만)", "",
                  (f"- 키: {md(SC.REFERENCE_KEY)}; 평가: {EVALUATION_LABELS[reference['evaluation']]}; "
                   f"상태: {md(reference['state'])}")
                  + ("" if reference["reason_code"] is None else f"; 이유: {md(reference['reason_code'])}")])
    if reference["state"] == "scored":
        lines.append(f"- {SCORE_COLUMN_LABEL}: {reference_score()} ({row_label})")
    lines.extend([(f"- 모델: {handle_or_none(reference['model_handle'])}; 개체별 결과: "
                   f"{handle_or_none(reference['result_handle'])}"),
                  "- 이 행은 개체가 아니며 선택·이어받음·종료 판단과 세대 점수 최솟값·최댓값에 쓰지 않았다."])
    for index, gen in enumerate(manifest["generations"]):
        number = gen["index"]
        counts = ", ".join(
            f"{md(state)} {value('generation_count', None, generation=number, where=f'state == {state}')}"
            for state in SC.STATES)
        lines.extend(["", f"## 세대 {md(number)} ({'완료' if gen['complete'] else '중간에 멈춤'})", "",
                      f"- 개체 수: {value('generation_count', None, generation=number, where=None)}; {counts}"])
        if gen["min_score"] is None:
            lines.append("- 점수 최솟값·최댓값: 점수 있는 개체 없음")
        else:
            lines.append(f"- 점수 최솟값 {value('generation_score_range', f'generations[{index}].min_score')}, "
                         f"최댓값 {value('generation_score_range', f'generations[{index}].max_score')} (값만)")
        lines.extend(["", (f"| 자리 | 개체 키 | 변이 | 출처 | 부모 키 | 편집 | 평가 | 선택 순서 | 평가 순서 | 상태 | "
                           f"{SCORE_COLUMN_LABEL} | 점수 대상 | 이유 | 모델 | 개체별 결과 |"),
                      ("| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | ---: | --- | --- | --- "
                       "| --- |")])
        ordered = sorted(enumerate(gen["individuals"]), key=lambda item: item[1]["state"] != "scored")
        for position, entry in ordered:
            scored = entry["state"] == "scored"
            cells = [str(position), md(entry["key"]), md(", ".join(mutation_label(row) for row in entry["mutations"])),
                     ORIGIN_LABELS[entry["origin"]],
                     "" if entry["parents"] is None else md(", ".join(entry["parents"])),
                     "" if entry["edit_op"] is None else EDIT_LABELS[entry["edit_op"]],
                     "" if entry["evaluation"] is None else EVALUATION_LABELS[entry["evaluation"]],
                     str(entry["pick_index"]), "" if entry["eval_index"] is None else str(entry["eval_index"]),
                     md(entry["state"]), score(number, index, position) if scored else "",
                     row_label if scored else "", "" if entry["reason_code"] is None else md(entry["reason_code"]),
                     "" if entry["model_handle"] is None else md(entry["model_handle"]),
                     "" if entry["result_handle"] is None else md(entry["result_handle"])]
            lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([(f"Exact values, units, field paths and conditions are in the JSON download ({md(len(claims))} "
                   "claims). Individual models and results open in the protein engineering tab reads (sequence GA "
                   "individual detail and the M18 docking reads); this report makes no per-individual model or "
                   "docking report. The table order is a display order only."), ""])
    template = "\n".join(lines)
    check_no_interpretation(_SLOT.sub("", template))
    return _SLOT.sub(lambda match: slots[int(match.group(1))], template)


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_sequence_ga_report(run: Any, summary_handle: str) -> dict[str, Any]:
    """New report object for one stored sequence GA summary (nothing is modelled or docked again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, summary_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "capability": capability_snapshot(),
                                "budget": run.budget_snapshot()}
        markdown = render_sequence_ga_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("sequence_ga_report_too_large")
        produced_by = f"sequence_ga_report_{uuid.uuid4().hex}"
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


def saved_sequence_ga_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored sequence GA report without modelling or docking again."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("sequence_ga_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("sequence_ga_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("sequence_ga_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"sequence_ga_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["sequence_ga"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not capability_snapshot_valid(snapshot["capability"]) or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("sequence_ga_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("sequence_ga_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("sequence_ga_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("sequence_ga_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_sequence_ga_report(report):
        raise EvidenceError("sequence_ga_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
