"""Immutable, field-cited reports for one ``mutation_model@1`` (``method_report_manifest@1``,
``analysis_type: "mutation_model"``, render ``mutation_model_markdown@1``; spec .dryforge/spec.md 8).

The input is one mutation model handle. Every value statement is ``computed`` evidence bound to that handle and one
field path (there is no other evidence kind in this report):

- the candidate: the 7 residue fields of the position, ``from``, ``to``, the mutant residue name, the candidate set
  and the candidate index (stored identifiers, rendered verbatim);
- per structure (``wild_type_reference`` and ``mutant``): the OpenMM potential before and after minimization
  (kJ/mol, ``Decimal(str(v))`` to 0.01 with ``ROUND_HALF_UP``), the mutated-residue SASA (Å², same rounding), the
  contact cutoff (the stored input value), the contact row count (``count`` over the stored rows), the contact partner
  residue count (``count_distinct`` of the stored partner residues) and the disulfide pair count (``count`` over the
  stored pairs);
- the number of residues outside the mutated one whose protonation variant differs (``count`` over the stored
  ``protonation_differences`` rows) and the number of heavy atoms PDBFixer placed in the mutated residue (``count``
  over the mutant's ``added_heavy_atoms``).

No claim states a difference between the two structures or a change within one structure (before -> after); such
claims and any docking score are refused (docking results have their own M18 reports). The fixed limitation sentences
(L1, L2, L3, L4, L7, then L5 / L6 when they apply) are written verbatim, in order.

Creating, reopening and downloading never model or minimize again: the stored model is re-validated with
``mutation_model_bundle.validated_result`` (single completed publication, job selection, candidate set row,
structure, stored mmCIF bytes, pure ``validated_model``), every manifest field and claim is compared with the one
rebuilt from the stored model, and the Markdown is compared byte for byte with a re-render. Interpolated values and
identifiers go into slots; the forbidden-word check (the M20 list: M15 words plus 안정성·ΔΔG·순위·추천·최적·개선·
활성·예측·유망·좋은·나쁜·안전·점수·에너지·수소결합 and the English words) runs on every template line with the slots
empty, except a line exactly equal to a fixed limitation sentence. The template says "OpenMM 전위", never "에너지".

M29 T8 (report format ``mutation_model_markdown@2``, spec .dryforge/spec.md 6.3): the report of a model whose candidate
set's structure is a repaired structure (``structure_origin_reports.origin``, the record re-validated with its
publication) is @2, and only such a model's report is: the @1 manifest keys plus ``structure_origin``, the two
record-count claims (``counts.added_residues`` / ``counts.added_atoms`` of the ``structure_repair@1`` record, neither a
difference nor a change) after the @1 claims, and a "구조 출처" section (SO1, the handles, the two counts) before the
limitations. Any other model's report is @1 with the @1 bytes; an @1 manifest for a repaired structure or an @2 one
for another structure is refused.
"""
from __future__ import annotations

import math
import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import mutation_model_bundle as bundle
from . import mutation_reports as m20
from . import numbering_reports as nr
from . import structure_origin_reports as origin_reports
from .core.handles import canonical_json
from .mutation_candidates import identity
from .mutation_constants import IDENTITY_FIELDS
from .mutation_model_constants import KIND, LIMITATION_ORDER, SCHEMA, STRUCTURE_SIDES, applicable_limitations
from .mutation_model_reads import structure_summary
from .pocket_reports import _budget_snapshot_valid
from .reports import EvidenceError, _md, _ref

ANALYSIS_TYPE = "mutation_model"
RENDER_VERSION = "mutation_model_markdown@1"
RENDER_VERSION_V2 = "mutation_model_markdown@2"   # M29 T8: a model on a repaired structure (구조 출처 section)
REPORT_BYTES = nr.REPORT_BYTES
FIXED_LIMITATIONS = frozenset(LIMITATION_ORDER)
EVIDENCE_STATEMENT = ("이 보고서의 수치는 저장된 변이 구조 모델 결과의 OpenMM 전위·변이 위치 SASA 값과, 저장된 접촉 "
                      "행·이황화 쌍·양성자 상태 차이 행·PDBFixer 추가 원자 행을 센 개수다. 보고서는 구조를 다시 만들거나 "
                      "최소화하지 않았고, 두 구조의 값이나 최소화 전후 값을 서로 빼지 않았다.")
SIDE_KO = {"wild_type_reference": "야생형 기준", "mutant": "변이형"}
STAGES = ("before", "after")
STAGE_KO = {"before": "최소화 전", "after": "최소화 후"}

_SIDES = "|".join(STRUCTURE_SIDES)
_RES = "|".join(IDENTITY_FIELDS)
# statement ID -> its closed field-path rule (all ``computed``); a claim citing another statement's field is refused
# before any value comparison.
STATEMENTS = {
    "candidate": re.compile(rf"candidate\.(candidate_set|candidate_index|from|to|mutant_resname|residue\.({_RES}))"),
    "openmm_potential": re.compile(rf"structures\.({_SIDES})\.energy\.(before|after)_kJ_mol"),
    "mutated_residue_sasa": re.compile(rf"structures\.({_SIDES})\.sasa\.value_A2"),
    "contact_cutoff": re.compile(rf"structures\.({_SIDES})\.contacts\.cutoff_A"),
    "contact_count": re.compile(rf"structures\.({_SIDES})\.contacts\.rows"),
    "contact_residue_count": re.compile(rf"structures\.({_SIDES})\.contacts\.rows\[\*\]\.partner_residue"),
    "disulfide_pair_count": re.compile(rf"structures\.({_SIDES})\.disulfide_bonds"),
    "protonation_difference_count": re.compile(r"protonation_differences"),
    "added_heavy_atom_count": re.compile(r"structures\.mutant\.added_heavy_atoms"),
}
EVIDENCE_KINDS = ("computed",)
CLAIM_KEYS = nr.CLAIM_KEYS
INTERPRETIVE = m20.INTERPRETIVE
# A claim naming a difference between the structures or a before -> after change, or a docking score, is refused
# outright (spec 8); the closed statements above never carry one.
DIFFERENCE = re.compile(r"differen|delta|\bdiff|change|subtract|minus|Δ|차이|변화|증가|감소", re.IGNORECASE)
DOCKING = re.compile(r"score|docking|qvina|kcal|점수|도킹", re.IGNORECASE)
DOCKING_KINDS = frozenset({"docking_result", "docking_batch_result"})
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget"}
COPIED_FIELDS = ("method_version", "candidate", "structure", "parameters", "method", "excluded_components",
                 "comparison", "protonation_differences", "limitations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "structures", "claims", "provenance", "evidence_statement", "snapshot",
    "markdown_handle"})
MANIFEST_KEYS_BY_VERSION = {RENDER_VERSION: MANIFEST_KEYS, RENDER_VERSION_V2: MANIFEST_KEYS | {"structure_origin"}}


# ---------------------------------------------------------------------------------------------------------------
# rendering

def render_two_decimals(value: Any) -> str:
    """Two decimals: ``Decimal(str(v))`` quantized to 0.01 with ``ROUND_HALF_UP`` (2.675 -> 2.68, -0.005 -> -0.01)."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise EvidenceError("mutation_model_claim_value_type")
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.2f}"


def _render(value: Any, rounding: str) -> str:
    if rounding in ("potential_2dp", "area_2dp"):
        return render_two_decimals(value)
    if rounding == "input_decimal":
        if type(value) not in (int, float) or not math.isfinite(value):
            raise EvidenceError("mutation_model_claim_value_type")
        return str(Decimal(str(value)))
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("mutation_model_claim_integer_expected")
        return str(value)
    if rounding == "identifier":
        if type(value) is not str:
            raise EvidenceError("mutation_model_claim_value_type")
        return value
    if rounding == "json":
        if value is not None and type(value) not in (str, int):
            raise EvidenceError("mutation_model_claim_value_type")
        return "null" if value is None else str(value)
    raise EvidenceError("mutation_model_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the fixed limitation sentences or the M29
    structure origin sentence (SO1)."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS or line in origin_reports.FIXED_LINES:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"mutation_model_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# claims

def _claim(statement_id: str, handle: str, path: str, selector: dict[str, Any] | None, subject: dict[str, Any],
           quantity: str, unit: str, value: Any, rounding: str, operation: str | None = None) -> dict[str, Any]:
    return {"statement_id": statement_id, "evidence_kind": "computed", "source_handle": handle,
            "source_kind": KIND, "source_schema": SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
            "field_path": path, "row_selector": selector, "subject": subject, "quantity": quantity, "unit": unit,
            "exact_value": value, "rendered_value": _render(value, rounding), "rounding": rounding,
            "operation": operation, "reference": None}


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; counts are recounted from the stored rows."""
    try:
        candidate = content["candidate"]
        subject = {"mutation_model_handle": handle, "residue": candidate["residue"]}
        claims = []
        for field in IDENTITY_FIELDS:
            claims.append(_claim("candidate", handle, f"candidate.residue.{field}", None, subject,
                                 f"position_{field}", "residue_field", candidate["residue"][field], "json"))
        for key, unit in (("from", "one_letter"), ("to", "one_letter"), ("mutant_resname", "residue_name"),
                          ("candidate_set", "handle")):
            claims.append(_claim("candidate", handle, f"candidate.{key}", None, subject, key, unit, candidate[key],
                                 "identifier"))
        claims.append(_claim("candidate", handle, "candidate.candidate_index", None, subject, "candidate_index",
                             "index", candidate["candidate_index"], "integer"))
        for side in STRUCTURE_SIDES:
            entry = content["structures"][side]
            selector = {"structure": side}
            side_subject = {"mutation_model_handle": handle, "structure": side,
                            "residue": entry["sasa"]["residue"]}
            for stage in STAGES:
                claims.append(_claim("openmm_potential", handle, f"structures.{side}.energy.{stage}_kJ_mol",
                                     {**selector, "stage": stage}, side_subject, f"openmm_potential_{stage}_kJ_mol",
                                     "kJ/mol", entry["energy"][f"{stage}_kJ_mol"], "potential_2dp"))
            claims.append(_claim("mutated_residue_sasa", handle, f"structures.{side}.sasa.value_A2", selector,
                                 side_subject, "mutated_residue_sasa_A2", "A2", entry["sasa"]["value_A2"],
                                 "area_2dp"))
            rows = entry["contacts"]["rows"]
            claims.append(_claim("contact_cutoff", handle, f"structures.{side}.contacts.cutoff_A", selector,
                                 side_subject, "contact_cutoff_A", "A", entry["contacts"]["cutoff_A"],
                                 "input_decimal"))
            claims.append(_claim("contact_count", handle, f"structures.{side}.contacts.rows", selector, side_subject,
                                 "contact_rows", "count", len(rows), "integer",
                                 "count(stored contact rows of this structure)"))
            claims.append(_claim("contact_residue_count", handle,
                                 f"structures.{side}.contacts.rows[*].partner_residue", selector, side_subject,
                                 "contact_partner_residues", "count",
                                 len({identity(row["partner_residue"]) for row in rows}), "integer",
                                 "count_distinct(partner_residue, 7 fields; stored contact rows of this structure)"))
            claims.append(_claim("disulfide_pair_count", handle, f"structures.{side}.disulfide_bonds", selector,
                                 side_subject, "disulfide_pairs", "count", len(entry["disulfide_bonds"]), "integer",
                                 "count(stored SG-SG pairs of this structure)"))
        claims.append(_claim("protonation_difference_count", handle, "protonation_differences", None,
                             {"mutation_model_handle": handle}, "protonation_difference_residues", "count",
                             len(content["protonation_differences"]), "integer",
                             "count(stored protonation_differences rows)"))
        claims.append(_claim("added_heavy_atom_count", handle, "structures.mutant.added_heavy_atoms",
                             {"structure": "mutant"},
                             {"mutation_model_handle": handle, "structure": "mutant",
                              "residue": content["structures"]["mutant"]["sasa"]["residue"]},
                             "pdbfixer_added_heavy_atoms", "count",
                             len(content["structures"]["mutant"]["added_heavy_atoms"]), "integer",
                             "count(stored added heavy atom rows of the mutated residue)"))
        return claims
    except EvidenceError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_model_report_evidence_unresolved") from exc


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim rebuilt from that field."""
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("mutation_model_claim_shape")
    named = " ".join(str(proposed[key]) for key in ("statement_id", "field_path", "quantity", "operation", "unit"))
    if proposed["source_kind"] in DOCKING_KINDS or DOCKING.search(named):
        raise EvidenceError("mutation_model_claim_docking_score_not_allowed")
    if DIFFERENCE.search(named.replace("protonation_difference", "")):
        raise EvidenceError("mutation_model_claim_difference_not_allowed")
    statement = proposed["statement_id"]
    if statement in origin_reports.STATEMENT_IDS:   # M29 @2: the record counts of a repaired structure
        return origin_reports.match_claim(expected_claims, proposed, "mutation_model")
    if statement not in STATEMENTS:
        raise EvidenceError("mutation_model_claim_statement_not_allowed")
    if proposed["evidence_kind"] not in EVIDENCE_KINDS or proposed["reference"] is not None:
        raise EvidenceError("mutation_model_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str or not STATEMENTS[statement].fullmatch(path):
        raise EvidenceError("mutation_model_claim_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (KIND, SCHEMA):
        raise EvidenceError("mutation_model_claim_source_kind_mismatch")
    handles = {claim["source_handle"] for claim in expected_claims}
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("mutation_model_claim_source_mismatch")
    try:
        match = {_key(claim): claim for claim in expected_claims}.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("mutation_model_claim_shape") from exc
    if match is None:
        raise EvidenceError("mutation_model_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("mutation_model_claim_binding_mismatch")
    return proposed


def validate_mutation_model_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# source validation, manifest

def _expected(run: Any, handle: str, version: str | None = None) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored model (not snapshot / markdown handle).

    ``version`` is the render version of a stored report; None picks it for a new report: @2 when the model's
    structure (its candidate set's structure) is a repaired structure, else @1."""
    try:
        content = bundle.validated_result(run, handle)
        source = bundle.producer(run, handle)
    except bundle.MutationEvidenceError as exc:
        raise EvidenceError(f"mutation_model_invalid: {exc}") from exc
    try:
        origin = origin_reports.origin(run, content["structure"]["handle"])
    except (KeyError, TypeError) as exc:
        raise EvidenceError("mutation_model_report_evidence_unresolved") from exc
    if version is None:
        version = RENDER_VERSION if origin is None else RENDER_VERSION_V2
    if version not in MANIFEST_KEYS_BY_VERSION:
        raise EvidenceError("mutation_model_report_schema_invalid")
    if (version == RENDER_VERSION_V2) is (origin is None):
        raise EvidenceError("mutation_model_report_structure_origin_mismatch")   # @2 is a repaired structure's only
    try:
        expected = {
                "schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": version, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS},
                "structures": {side: structure_summary(content["structures"][side]) for side in STRUCTURE_SIDES},
                "claims": claims_for(handle, content) + ([] if origin is None else origin_reports.claims(origin)),
                "provenance": {"mutation_model": {"job_id": source["job_id"], "attempt_id": source["attempt_id"],
                                                  "protocol_id": source["job"]["protocol_id"],
                                                  "tool_id": source["job"]["tool_id"],
                                                  "created_event_seq": source["created_seq"],
                                                  "completed_event_seq": source["published_seq"]}},
                "evidence_statement": EVIDENCE_STATEMENT}
        if origin is not None:
            expected["structure_origin"] = origin_reports.manifest_field(origin)
        return expected
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("mutation_model_report_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# Markdown

_SLOT = re.compile("\x00(\\d+)\x00")


def render_mutation_model_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every engine value and count is the rendered text of a bound claim.

    Values and identifiers go into slots; the forbidden-word check runs on the fixed template text with the slots
    left empty, then the slots are filled. The limitation lines must be exactly the sentences that apply.
    """
    claims = manifest["claims"]
    comparison = manifest["comparison"]
    if manifest["limitations"] != list(applicable_limitations(
            protonation_difference_count=comparison["protonation_difference_count"],
            new_disulfide_in_mutant=comparison["new_disulfide_in_mutant"])):
        raise EvidenceError("mutation_model_report_limitations_mismatch")
    slots: list[str] = []

    def slot(text: str) -> str:
        slots.append(text)
        return f"\x00{len(slots) - 1}\x00"

    def md(item: Any) -> str:
        return slot(_md(item))

    def value(statement: str, path: str | None = None, **selector: Any) -> str:
        found = [c["rendered_value"] for c in claims if c["statement_id"] == statement and
                 (path is None or c["field_path"] == path) and
                 all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("mutation_model_report_claim_missing")
        return md(found[0])

    candidate, structure, method = manifest["candidate"], manifest["structure"], manifest["method"]
    job = manifest["provenance"]["mutation_model"]
    residue = {field: candidate["residue"][field] for field in IDENTITY_FIELDS}
    lines = ["# 변이 구조 모델 보고서 (mutation model)", "", "Status: complete", "",
             f"Result: {md(manifest['result_handle'])}",
             f"Modeling job: {md(job['job_id'])}, attempt {md(job['attempt_id'])}",
             f"Method: {md(manifest['method_version'])}",
             (f"Engines: OpenMM {md(method['distribution_version'])} (build {md(method['engine_build'])}), "
              f"PDBFixer {md(method['pdbfixer_version'])}, FreeSASA "
              f"{md(manifest['structures']['mutant']['sasa']['parameters']['engine_version'])}"),
             (f"- 포스필드: {md(' + '.join(method['forcefield_files']))}, pH {md(method['pH'])}, "
              f"최대 {md(method['max_iterations'])}회 최소화, 허용 오차 {md(method['tolerance_kJ_mol_nm'])} kJ/mol/nm, "
              f"CPU {md(method['platform_properties']['Threads'])}스레드"),
             "", f"**{_md(manifest['evidence_statement'])}**", "",
             "## 후보", "",
             "- 위치 잔기 (7필드): " + ", ".join(
                 f"{md(field)} {value('candidate', f'candidate.residue.{field}')}" for field in IDENTITY_FIELDS),
             f"- 표시: {md(_ref(residue))}",
             (f"- 바꾼 잔기: {value('candidate', 'candidate.from')} → {value('candidate', 'candidate.to')} "
              f"({value('candidate', 'candidate.mutant_resname')})"),
             (f"- 후보 집합: {value('candidate', 'candidate.candidate_set')}, 후보 index "
              f"{value('candidate', 'candidate.candidate_index')}"),
             (f"- 구조: {md(structure['handle'])} ({md(structure['structure_kind'])}, "
              f"model {md(structure['model_number'])})"),
             f"- seed: {md(manifest['parameters']['seed'])}",
             "- 제외한 구성 요소: " + ", ".join(
                 f"{md(item['reason'])} 잔기 {md(item['residue_count'])}개·원자 {md(item['atom_count'])}개"
                 for item in manifest["excluded_components"]),
             "", "## 구조별 값", "",
             "두 구조의 저장값을 나란히 놓았을 뿐이며 서로 빼거나 최소화 전후 값을 빼지 않았다.", "",
             "| 항목 | 야생형 기준 (wild\\_type\\_reference) | 변이형 (mutant) |", "| --- | ---: | ---: |"]

    def row(label: str, statement: str, **selector: Any) -> str:
        return f"| {label} | " + " | ".join(value(statement, structure=side, **selector)
                                            for side in STRUCTURE_SIDES) + " |"

    for stage in STAGES:
        lines.append(row(f"OpenMM 전위, {STAGE_KO[stage]} (kJ/mol)", "openmm_potential", stage=stage))
    lines.extend([row("변이 위치 잔기 SASA (Å²)", "mutated_residue_sasa"),
                  row("접촉 cutoff (Å)", "contact_cutoff"),
                  row("접촉 행 수", "contact_count"),
                  row("접촉 상대 잔기 수", "contact_residue_count"),
                  row("이황화 SG–SG 쌍 수", "disulfide_pair_count"),
                  (f"| PDBFixer가 놓은 변이 잔기 중원자 수 | 해당 없음 (변이 없음) | "
                   f"{value('added_heavy_atom_count', 'structures.mutant.added_heavy_atoms')} |"),
                  "", "## 정의", "",
                  ("- OpenMM 전위: 각 구조의 Amber14-all + GBn2 암시 용매 값(kJ/mol). 최소화 전은 수소를 다시 놓은 "
                   "직후, 최소화 후는 최대 50회 최소화 뒤다."),
                  ("- SASA: FreeSASA Lee–Richards 100 slices, probe 1.4 Å, 수소를 뺀 단백질 중원자 전체 모델에서 계산한 "
                   "변이 위치 잔기 하나의 값."),
                  ("- 접촉: 변이 위치 잔기 중원자와 다른 모든 잔기 중원자 사이 거리가 cutoff 이하인 원자 쌍. 최종 위상 "
                   "그래프에서 3단계 이내로 이어진 쌍은 뺐다. 상대 잔기는 7필드로 센다."),
                  "", "## 양성자 상태", "",
                  ("- 변이한 잔기 밖에서 두 구조의 변형 이름이 다른 잔기 수: "
                   f"{value('protonation_difference_count', 'protonation_differences')}")])
    for item in manifest["protonation_differences"]:
        lines.append(f"  - {md(_ref(item['residue']))}: 야생형 기준 {md(item['wild_type_reference'] or 'default')}, "
                     f"변이형 {md(item['mutant'] or 'default')}")
    if manifest["render_version"] == RENDER_VERSION_V2:   # M29 T8: the structure origin section
        lines.extend(origin_reports.section_lines(manifest["structure_origin"], claims, md))
    lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        lines.extend([item, ""])
    lines.extend([("Exact values, units and field paths are in the JSON download "
                   f"({md(len(claims))} claims). Contact rows and the two mmCIF files are in the mutation model reads; "
                   "same-condition docking results have their own M18 reports."), ""])
    template = "\n".join(lines)
    check_no_interpretation(_SLOT.sub("", template))
    return _SLOT.sub(lambda match: slots[int(match.group(1))], template)


# ---------------------------------------------------------------------------------------------------------------
# build and saved read

def build_mutation_model_report(run: Any, result_handle: str) -> dict[str, Any]:
    """New report object for one stored mutation model (nothing is modelled or minimized again)."""
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot()}
        markdown = render_mutation_model_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("mutation_model_report_too_large")
        produced_by = f"mutation_model_report_{uuid.uuid4().hex}"
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


def saved_mutation_model_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored mutation model report from stored objects only (nothing is modelled again)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("mutation_model_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    version = report.get("render_version") if type(report) is dict else None
    keys = MANIFEST_KEYS_BY_VERSION.get(version) if type(version) is str else None   # @1 and @2 are read
    if (keys is None or set(report) != keys or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str):
        raise EvidenceError("mutation_model_report_schema_invalid")
    expected = _expected(run, report["result_handle"], version)
    if type(report["claims"]) is not list:
        raise EvidenceError("mutation_model_report_claims_invalid")
    for claim in report["claims"]:
        match_claim(expected["claims"], claim)
    for key, item in expected.items():
        if canonical_json(report[key]) != canonical_json(item):
            raise EvidenceError(f"mutation_model_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["mutation_model"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            not _budget_snapshot_valid(snapshot["budget"])):
        raise EvidenceError("mutation_model_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("mutation_model_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("mutation_model_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("mutation_model_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_mutation_model_report(report):
        raise EvidenceError("mutation_model_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
