"""Immutable, field-cited reports for one ``docking_result@1`` (``method_report_manifest@1``,
``analysis_type: "ligand_docking"``, render ``ligand_docking_markdown@1``; spec M18 section 9).

The input is one docking result handle; a report never covers two results, so free and core-fixed results are never
mixed. Every value statement is ``computed`` evidence bound to that handle and one field path:

- stored fields: the mode count, per mode row ``score_kcal_mol`` (rendered ``Decimal(str(v))`` to 0.1 with
  ``ROUND_HALF_UP``), ``atoms_outside_box``, ``min_heavy_atom_distance_A`` and, for core-fixed results,
  ``core_max_deviation_A`` (distances and box values to 0.01, counts exactly), the core-fixed sample counts, the box
  centre/size (and margin when the box came from a range), the parameters (seed, exhaustiveness, num_modes,
  energy_range, conformers when used, cpu), the engine name and version, the Meeko/RDKit versions, the receptor import,
  the removed receptor instance (7 residue fields and atom count) and the ligand source fields (candidate results:
  candidate set, candidate id, parent SDF handle and SHA-256, the generated hydrogen/coordinate flags);
- ``count``/``count_where`` over each mode row's stored contact rows, recounted at every validation (the condition is
  in the claim's ``row_selector``);
- derived values: only the ``minimum`` and ``maximum`` of the stored scores ("점수 최솟값", "점수 최댓값").

M21: a result whose receptor came from a mutation model (``inputs.receptor.source``) has no import handle; its
receptor section shows the source (mutation model handle and side, copied from the validated stored result) instead
of the import line, and the other receptor statements are unchanged. Imported-receptor reports are byte-identical.

A field the result did not compute (null) is never a statement, so it can never be written as 0; a result without
mode rows has no row statistics. Candidate results must carry their candidate provenance and core-fixed results their
``core_max_deviation_A`` on every row, else no report is made.

Creating, reopening and downloading never dock again: the stored result is re-validated with
``docking_bundle.validated_result`` (single completed publication, inputs, closed sets), every manifest field and
claim is compared with the one rebuilt from the stored result, and the Markdown is compared byte for byte with a
re-render. Every Markdown line is checked for interpretive wording; the only exemptions are a line exactly equal to
one of the fixed limitation sentences, and the exact score-name text (``SCORE_LABEL``), which is removed from a line
before that line is checked (the rest of the line is still checked).
"""
from __future__ import annotations

import json
import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import docking_bundle as db
from . import ligand_reports as lr
from . import numbering_reports as nr
from .core.handles import canonical_json
from .docking_constants import CONTACT_CUTOFF_A, CONTACT_KINDS, METHODS, SCORE_COLUMN_LABEL, SCORE_LABEL
from .docking_constants import LIMITATIONS as FIXED_LIMITATIONS
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md

ANALYSIS_TYPE = "ligand_docking"
RENDER_VERSION = "ligand_docking_markdown@1"
RESULT_KIND = db.OUTPUT_KIND
RESULT_SCHEMA = "docking_result@1"
REPORT_BYTES = nr.REPORT_BYTES
RESIDUE_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
PARAMETERS = ("seed", "exhaustiveness", "num_modes", "energy_range", "conformers", "cpu")
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 qvina 작업 결과(도킹 결과 객체)의 값과, 저장된 모드 행의 접촉 행을 종류 "
                      "조건으로 센 개수, 저장된 점수의 최솟값·최댓값이다. 보고서는 도킹을 다시 하지 않았다.")

_RES = "|".join(RESIDUE_FIELDS)
_LIGAND = ("source|sdf_handle|sdf_sha256|candidate_set_handle|candidate_id|parent_sdf_handle|parent_sdf_sha256|"
           r"generated\.(hydrogens|coordinates)|stereo_flag|unspecified_stereo_centers")
# statement ID -> its closed field-path rule (all ``computed``); a claim citing another statement's field is refused
# before any value comparison.
STATEMENTS = {
    "mode_count": re.compile(r"counts\.modes"),
    "sample_count": re.compile(r"counts\.(samples_generated|samples_scored)"),
    "score": re.compile(r"modes\[\d+\]\.score_kcal_mol"),
    "score_minimum": re.compile(r"modes\[\*\]\.score_kcal_mol"),
    "score_maximum": re.compile(r"modes\[\*\]\.score_kcal_mol"),
    "contact_count": re.compile(r"modes\[\d+\]\.contacts"),
    "contact_kind_count": re.compile(r"modes\[\d+\]\.contacts"),
    "atoms_outside_box": re.compile(r"modes\[\d+\]\.atoms_outside_box"),
    "min_heavy_atom_distance": re.compile(r"modes\[\d+\]\.min_heavy_atom_distance_A"),
    "core_max_deviation": re.compile(r"modes\[\d+\]\.core_max_deviation_A"),
    "box": re.compile(r"box\.(center_A|size_A)\[[0-2]\]|box\.source|box\.margin_A"),
    "parameter": re.compile(r"parameters\.(" + "|".join(PARAMETERS) + ")"),
    "engine": re.compile(r"engine\.(name|version)"),
    "preparation": re.compile(r"preparation\.(tool|version|rdkit_version)"),
    "receptor_input": re.compile(r"inputs\.receptor\.(handle|sha256|model_number)"),
    "removed_instance": re.compile(rf"inputs\.receptor\.removed_instance\.(residue\.({_RES})|atom_count)"),
    "ligand_input": re.compile(rf"inputs\.ligand\.({_LIGAND})"),
}
EVIDENCE_KINDS = ("computed",)
CLAIM_KEYS = lr.CLAIM_KEYS
# M15/M16/M17 interpretive wording plus the M18 additions (spec 9): ranking, best, improvement, binding strength.
INTERPRETIVE = re.compile(
    lr.INTERPRETIVE.pattern + r"|순위|최고|개선|결합\s*강도|\brank|\bbest|improv|stronger", re.IGNORECASE)
CAPABILITY_KEYS = ("available", "status", "reason_code", "pins")
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "capability", "budget"}
COPIED_FIELDS = ("method", "input_sha256", "inputs", "box", "parameters", "engine", "preparation", "counts")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "mode", "null_result", "score_label", "claims", "provenance",
    "evidence_statement", "limitations", "snapshot", "markdown_handle"})


# ---------------------------------------------------------------------------------------------------------------
# rendering

def _decimal(value: Any, places: str) -> str:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("docking_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.{len(places) - 2}f}"


def render_score(value: Any) -> str:
    """One decimal: ``Decimal(str(v))`` quantized to 0.1 with ``ROUND_HALF_UP`` (-5.25 -> -5.3)."""
    return _decimal(value, "0.1")


def render_distance(value: Any) -> str:
    """Two decimals: ``Decimal(str(v))`` quantized to 0.01 with ``ROUND_HALF_UP`` (2.675 -> 2.68)."""
    return _decimal(value, "0.01")


def _render(value: Any, rounding: str) -> str:
    if rounding == "score_1dp":
        return render_score(value)
    if rounding == "distance_2dp":
        return render_distance(value)
    if rounding == "input_decimal":
        if type(value) not in (int, float) or not math.isfinite(value):
            raise EvidenceError("docking_claim_value_type")
        return str(Decimal(str(value)))
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("docking_claim_integer_expected")
        return str(value)
    if rounding == "flag":
        if type(value) is not bool:
            raise EvidenceError("docking_claim_value_type")
        return "true" if value else "false"
    if rounding == "identifier":
        if type(value) is not str:
            raise EvidenceError("docking_claim_value_type")
        return value
    if rounding == "json":
        if value is not None and type(value) not in (str, int):
            raise EvidenceError("docking_claim_value_type")
        return json.dumps(value, ensure_ascii=False)
    raise EvidenceError("docking_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on every line. A line exactly equal to a fixed limitation sentence is exempt; on
    any other line only the exact score-name text is removed before the check (the rest of the line is checked)."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS:
            continue
        match = INTERPRETIVE.search(line.replace(SCORE_LABEL, ""))
        if match is not None:
            raise EvidenceError(f"docking_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, quantity: str, unit: str,
           value: Any, rounding: str, operation: str | None = None) -> dict[str, Any]:
    return {"statement_id": statement_id, "evidence_kind": "computed", "source_handle": handle,
            "source_kind": RESULT_KIND, "source_schema": RESULT_SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": {"docking_result_handle": handle},
            "quantity": quantity, "unit": unit, "exact_value": value, "rendered_value": _render(value, rounding),
            "rounding": rounding, "operation": operation}


def _required(content: dict[str, Any]) -> None:
    """Refuse a result that cannot be reported honestly (spec 9): one method per result, candidate provenance,
    ``core_max_deviation_A`` on every core-fixed row."""
    mode = content["inputs"]["mode"]
    if mode not in METHODS or content["method"] != METHODS[mode]:
        raise EvidenceError("docking_report_method_mismatch")
    ligand = content["inputs"]["ligand"]
    if ligand["source"] == "candidate":
        if (any(type(ligand[key]) is not str or not ligand[key] for key in
                ("candidate_set_handle", "candidate_id", "parent_sdf_handle", "parent_sdf_sha256")) or
                ligand["generated"] != {"hydrogens": True, "coordinates": True}):
            raise EvidenceError("docking_report_candidate_provenance_missing")
    elif mode == "core_fixed":
        raise EvidenceError("docking_report_method_mismatch")
    if mode == "core_fixed":
        for row in content["modes"]:
            value = row.get("core_max_deviation_A")
            if type(value) not in (int, float) or not math.isfinite(value):
                raise EvidenceError("docking_report_core_max_deviation_missing")


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; contact counts are recounted from each row's stored contacts."""
    try:
        _required(content)
        mode = content["inputs"]["mode"]
        receptor, ligand = content["inputs"]["receptor"], content["inputs"]["ligand"]
        claims = [*([] if "source" in receptor else [   # M21 mutation-model source: no import handle
                      _claim("receptor_input", handle, "inputs.receptor.handle", None, "receptor_import", "handle",
                             receptor["handle"], "identifier")]),
                  _claim("receptor_input", handle, "inputs.receptor.sha256", None, "receptor_sha256", "sha256",
                         receptor["sha256"], "identifier"),
                  _claim("receptor_input", handle, "inputs.receptor.model_number", None, "receptor_model_number",
                         "model_number", receptor["model_number"], "integer")]
        removed = receptor["removed_instance"]
        if removed is not None:
            for field in RESIDUE_FIELDS:
                claims.append(_claim("removed_instance", handle, f"inputs.receptor.removed_instance.residue.{field}",
                                     None, f"removed_instance_{field}", "residue_field",
                                     removed["residue"][field], "json"))
            claims.append(_claim("removed_instance", handle, "inputs.receptor.removed_instance.atom_count", None,
                                 "removed_instance_atom_count", "count", removed["atom_count"], "integer"))
        for key in ("source", "sdf_handle", "sdf_sha256", "candidate_set_handle", "candidate_id",
                    "parent_sdf_handle", "parent_sdf_sha256", "stereo_flag"):
            if ligand[key] is not None:
                claims.append(_claim("ligand_input", handle, f"inputs.ligand.{key}", None, f"ligand_{key}",
                                     "identifier", ligand[key], "identifier"))
        for key in ("hydrogens", "coordinates"):
            claims.append(_claim("ligand_input", handle, f"inputs.ligand.generated.{key}", None,
                                 f"generated_{key}", "flag", ligand["generated"][key], "flag"))
        if ligand["unspecified_stereo_centers"] is not None:
            claims.append(_claim("ligand_input", handle, "inputs.ligand.unspecified_stereo_centers", None,
                                 "unspecified_stereo_centers", "count", ligand["unspecified_stereo_centers"],
                                 "integer"))
        box = content["box"]
        claims.append(_claim("box", handle, "box.source", None, "box_source", "identifier", box["source"],
                             "identifier"))
        for key in ("center_A", "size_A"):
            for axis in range(3):
                claims.append(_claim("box", handle, f"box.{key}[{axis}]", None, f"box_{key}_{'xyz'[axis]}", "A",
                                     box[key][axis], "distance_2dp"))
        if box["margin_A"] is not None:
            claims.append(_claim("box", handle, "box.margin_A", None, "box_margin_A", "A", box["margin_A"],
                                 "distance_2dp"))
        params = content["parameters"]
        for key in PARAMETERS:
            if params[key] is not None:
                claims.append(_claim("parameter", handle, f"parameters.{key}", None, key,
                                     "kcal/mol" if key == "energy_range" else "count" if key != "seed" else "seed",
                                     params[key], "input_decimal" if key == "energy_range" else "integer"))
        for key in ("name", "version"):
            claims.append(_claim("engine", handle, f"engine.{key}", None, f"engine_{key}", "identifier",
                                 content["engine"][key], "identifier"))
        for key in ("tool", "version", "rdkit_version"):
            claims.append(_claim("preparation", handle, f"preparation.{key}", None, f"preparation_{key}",
                                 "identifier", content["preparation"][key], "identifier"))
        counts, rows = content["counts"], content["modes"]
        claims.append(_claim("mode_count", handle, "counts.modes", None, "modes", "count", counts["modes"],
                             "integer"))
        if mode == "core_fixed":
            for key in ("samples_generated", "samples_scored"):
                claims.append(_claim("sample_count", handle, f"counts.{key}", None, key, "count", counts[key],
                                     "integer"))
        for index, row in enumerate(rows):
            number = index + 1
            selector = {"mode": number}
            claims.append(_claim("score", handle, f"modes[{index}].score_kcal_mol", selector, "score_kcal_mol",
                                 "kcal/mol", row["score_kcal_mol"], "score_1dp"))
            contacts = row["contacts"]
            claims.append(_claim("contact_count", handle, f"modes[{index}].contacts", selector, "contacts", "count",
                                 len(contacts), "integer", "count(stored contact rows of this mode)"))
            for kind in CONTACT_KINDS:
                claims.append(_claim("contact_kind_count", handle, f"modes[{index}].contacts",
                                     {"mode": number, "kind": kind}, f"{kind}s", "count",
                                     sum(1 for item in contacts if item["kind"] == kind), "integer",
                                     f"count_where(kind == {kind}; stored contact rows of this mode)"))
            claims.append(_claim("atoms_outside_box", handle, f"modes[{index}].atoms_outside_box", selector,
                                 "atoms_outside_box", "count", row["atoms_outside_box"], "integer"))
            claims.append(_claim("min_heavy_atom_distance", handle, f"modes[{index}].min_heavy_atom_distance_A",
                                 selector, "min_heavy_atom_distance_A", "A", row["min_heavy_atom_distance_A"],
                                 "distance_2dp"))
            if mode == "core_fixed":
                claims.append(_claim("core_max_deviation", handle, f"modes[{index}].core_max_deviation_A", selector,
                                     "core_max_deviation_A", "A", row["core_max_deviation_A"], "distance_2dp"))
        if rows:   # no mode rows: no row statistics
            scores = [row["score_kcal_mol"] for row in rows]
            claims.append(_claim("score_minimum", handle, "modes[*].score_kcal_mol", None, "score_kcal_mol_minimum",
                                 "kcal/mol", min(scores), "score_1dp", "minimum"))
            claims.append(_claim("score_maximum", handle, "modes[*].score_kcal_mol", None, "score_kcal_mol_maximum",
                                 "kcal/mol", max(scores), "score_1dp", "maximum"))
        return claims
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise EvidenceError("docking_report_evidence_unresolved") from exc


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim rebuilt from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("docking_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("docking_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS:
        raise EvidenceError("docking_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("docking_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (RESULT_KIND, RESULT_SCHEMA):
        raise EvidenceError("docking_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("docking_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("docking_claim_shape") from exc
    if match is None:
        raise EvidenceError("docking_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("docking_claim_binding_mismatch")
    return proposed


def validate_docking_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored result (not snapshot/markdown)."""
    try:
        content = db.validated_result(run, handle)
        source = db.producer(run, handle)
    except db.DockingEvidenceError as exc:
        raise EvidenceError(f"docking_result_invalid: {exc}") from exc
    try:
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": RESULT_SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS}, "mode": content["inputs"]["mode"],
                "null_result": content["counts"]["null_result"], "score_label": SCORE_LABEL,
                "claims": claims_for(handle, content),
                "provenance": {"docking": {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
                                           "protocol_id": source["job"]["protocol_id"],
                                           "tool_id": source["job"]["tool_id"],
                                           "created_event_seq": source["created_seq"],
                                           "completed_event_seq": source["published_seq"]}},
                "evidence_statement": EVIDENCE_STATEMENT, "limitations": list(content["limitations"])}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("docking_report_evidence_unresolved") from exc


def capability_snapshot() -> dict[str, Any]:
    """Capability status and pins at report creation (the cached handshake; nothing is docked)."""
    value = db.capability()
    return {key: value[key] for key in CAPABILITY_KEYS}


def capability_snapshot_valid(value: Any) -> bool:
    if type(value) is not dict or set(value) != set(CAPABILITY_KEYS):
        return False
    ready = value["status"] == "ready"
    if not (ready or value["status"] in db.REASONS) or value["available"] is not ready:
        return False
    if not ready:
        return value["reason_code"] == value["status"] and value["pins"] is None
    try:
        db._pins(value["pins"])
    except db.DockingEvidenceError:
        return False
    return value["reason_code"] is None


# ---------------------------------------------------------------------------------------------------------------
# Markdown

def render_docking_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every engine number is the rendered text of a bound claim."""
    claims = manifest["claims"]

    def value(statement: str, path: str | None = None, **selector: Any) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and
                 (path is None or c["field_path"] == path) and
                 all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("docking_report_claim_missing")
        return found[0]

    mode = manifest["mode"]
    core = mode == "core_fixed"
    ligand = manifest["inputs"]["ligand"]
    receptor = manifest["inputs"]["receptor"]
    job = manifest["provenance"]["docking"]
    engine = manifest["engine"]
    lines = ["# 단일 리간드 도킹 보고서 (ligand docking)", "", "Status: complete", "",
             f"Result: {_md(manifest['result_handle'])}",
             f"Docking job: {_md(job['job_id'])}, attempt {_md(job['attempt_id'])}",
             f"Method: {_md(manifest['method'])} ({'코어 고정, 점수만' if core else '자유 도킹'})",
             (f"Engine: {_md(value('engine', 'engine.name'))} {_md(value('engine', 'engine.version'))} (package "
              f"{_md(engine['package'])}, binary SHA-256 {_md(engine['binary_sha256'])})"),
             (f"Preparation: {_md(value('preparation', 'preparation.tool'))} "
              f"{_md(value('preparation', 'preparation.version'))}, RDKit "
              f"{_md(value('preparation', 'preparation.rdkit_version'))}, atom typing "
              f"{_md(manifest['preparation']['atom_typing'])}, charges {_md(manifest['preparation']['charges'])}"),
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             f"- 점수 이름: {SCORE_LABEL}", "",
             "## 수용체", "",
             (f"- 가져오기: {_md(value('receptor_input', 'inputs.receptor.handle'))}" if "source" not in receptor else
              f"- 출처: 변이 모델링 구조 ({_md(receptor['source']['kind'])}) {_md(receptor['source']['mutation_model'])}"
              f", 쪽 {_md(receptor['source']['side'])}"),
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
    lines.extend(["", "## 리간드", "", f"- 출처: {_md(value('ligand_input', 'inputs.ligand.source'))}"])
    if ligand["source"] == "sdf":
        lines.extend([f"- SDF 가져오기: {_md(value('ligand_input', 'inputs.ligand.sdf_handle'))}",
                      f"- SDF SHA-256: {_md(value('ligand_input', 'inputs.ligand.sdf_sha256'))}"])
    else:
        lines.extend([f"- 후보 집합: {_md(value('ligand_input', 'inputs.ligand.candidate_set_handle'))}",
                      f"- 후보 id: {_md(value('ligand_input', 'inputs.ligand.candidate_id'))}",
                      f"- 부모 SDF 가져오기: {_md(value('ligand_input', 'inputs.ligand.parent_sdf_handle'))}",
                      f"- 부모 SDF SHA-256: {_md(value('ligand_input', 'inputs.ligand.parent_sdf_sha256'))}",
                      f"- stereo\\_flag: {_md(value('ligand_input', 'inputs.ligand.stereo_flag'))}",
                      f"- 미지정 입체 중심: {value('ligand_input', 'inputs.ligand.unspecified_stereo_centers')}"])
    lines.extend([f"- RDKit이 만든 수소: {value('ligand_input', 'inputs.ligand.generated.hydrogens')}",
                  f"- RDKit이 만든 좌표: {value('ligand_input', 'inputs.ligand.generated.coordinates')}",
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
    rows = manifest["counts"]["modes"]
    lines.extend(["", "## 샘플 (점수 오름차순 나열)" if core else "## 모드 (엔진 출력 순서)", "",
                  f"- 행 수: {value('mode_count', 'counts.modes')}"])
    if core:
        lines.extend([f"- 만든 형태 수: {value('sample_count', 'counts.samples_generated')}",
                      f"- 점수를 매긴 형태 수: {value('sample_count', 'counts.samples_scored')}"])
    if manifest["null_result"]:
        lines.extend(["- " + _md("모드 0개: 유효한 빈 결과(scientific_null)이며 실패가 아니다."),
                      "- 행이 없으므로 행 통계가 없다."])
    else:
        lines.extend([f"- 점수 최솟값 (저장된 행): {value('score_minimum')} kcal/mol",
                      f"- 점수 최댓값 (저장된 행): {value('score_maximum')} kcal/mol", "",
                      (f"| {'샘플' if core else '모드'} | {SCORE_COLUMN_LABEL} | 접촉 수 | polar\\_contact | "
                       "hydrophobic\\_contact | contact | 최소 중원자 거리 (Å) | 상자 밖 중원자 수 |"
                       + (" 코어 최대 이탈 (Å) |" if core else "")),
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |" + (" ---: |" if core else "")])
        for number in range(1, rows + 1):
            name = f"샘플 {number}(점수 오름차순 나열)" if core else f"모드 {number}(엔진 출력 순서)"
            cells = [name, value("score", mode=number), value("contact_count", mode=number),
                     *(value("contact_kind_count", mode=number, kind=kind) for kind in CONTACT_KINDS),
                     value("min_heavy_atom_distance", mode=number), value("atoms_outside_box", mode=number)]
            if core:
                cells.append(value("core_max_deviation", mode=number))
            lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "## 접촉 기준", "",
                  (f"- 포즈 리간드 중원자와 수용체 중원자 사이 거리 {CONTACT_CUTOFF_A:.1f} Å 이하. 종류: polar\\_contact "
                   "(둘 다 N/O), hydrophobic\\_contact (둘 다 C), contact (그 밖)."),
                  "", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, units, field paths and contact conditions are in the JSON download "
                   f"({len(claims)} claims). Contact rows and pose SDF files are in the ligand tab docking reads."),
                  ""])
    return check_no_interpretation("\n".join(lines))


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_docking_report(run: Any, result_handle: str) -> dict[str, Any]:
    """New report object for one stored docking result (nothing is docked again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "capability": capability_snapshot(),
                                "budget": run.budget_snapshot()}
        markdown = render_docking_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("docking_report_too_large")
        produced_by = f"docking_report_{uuid.uuid4().hex}"
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by=produced_by, summary={"result_handle": result_handle})
        manifest["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", manifest,
                               produced_by=produced_by,
                               summary={"result_handle": result_handle, "analysis_type": ANALYSIS_TYPE,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=result_handle, snapshot_event_seq=seq)
        return {"handle": report.handle, "markdown_handle": md.handle, "manifest": manifest, "markdown": markdown}


def saved_docking_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored docking report without docking again."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("docking_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("docking_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("docking_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"docking_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["docking"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not capability_snapshot_valid(snapshot["capability"]) or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("docking_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("docking_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("docking_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("docking_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_docking_report(report):
        raise EvidenceError("docking_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
