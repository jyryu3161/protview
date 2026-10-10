"""Immutable, field-cited reports for ``kinase_precedents@1`` (``method_report_manifest@1``,
``analysis_type: "kinase_precedents"``, render ``kinase_precedents_markdown@1``; spec M27 section 7).

The input is one ``link_kinase_precedents`` result handle. The report is a summary plus a source list. Every claim
cites that stored result (``source_handle``) and is one of two evidence kinds, kept apart as in the M15 / M20 / M26
reports:

- ``computed`` -- what ProtView counted again from the stored result: chains (all, by status, by reason), each chain's
  status / reason, targets, each target's status, included records per file (all targets and per target), the
  ``include_flagged`` state (a file that was not included has this state claim only, never a number and never 0), the
  stored ``excluded_flagged`` numbers (UP2), records per variant notation / tag term / resolution basis per target (a
  record counts once per distinct tag term), the set-wide unresolved-target record counts (UP5), the number of
  ``pass`` kbase checks of each listed record, each listed record's ProtView integrity values and the number of records
  not listed.
- ``reference_value`` -- kbase values copied verbatim from the stored record copies and set record: file row counts of
  the set, each target's kbase references (``ref_id`` / gene / KLIFS name / group / family) and one source line per
  listed precedent (``move_id``, file, resolution basis, variant notation, PMID, bibliography title / journal / year /
  DOI, every paper location field, tags, the original ``content_hash`` and every kbase check whose status is not
  ``pass``). Each carries "kbase 가공본 값, 계산 아님", the set hash, ``kb_version`` and the imported time.

Quotes (observation, tradeoffs) and the measured-change values (``effects``) are never in the manifest or the Markdown
(they stay on the screen). Each statement ID has exactly one evidence kind and one closed field-path rule; a claim
citing a field of the other kind is refused before any value is compared. At most ``LINE_CAP`` source lines per target
(stored record order); the remaining count is a computed claim and every record stays in the result object.

Creating, reopening and downloading never re-run the linking: the stored result is re-checked with
``kinase_precedents.validated_result``, its tool provenance, structure and numbering map are checked in this run,
every manifest field and claim is compared with the ones rebuilt from the stored result, and the Markdown is compared
byte for byte with a re-render. The forbidden-word check runs on the fixed template with identifiers and kbase strings
left as empty slots and skips only lines that equal KP1-KP6 or KT1 exactly. The active set at creation is recorded in
the report snapshot only ("이전 스냅샷 기준" / "사용 중 스냅샷 없음").
"""
from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any

from . import kinase_precedents as kp
from . import precedent_constants as K
from .core.handles import canonical_json
from .reports import EvidenceError, _md, _provenance

ANALYSIS_TYPE = "kinase_precedents"
RENDER_VERSION = "kinase_precedents_markdown@1"
REPORT_BYTES = 8 * 1024 * 1024   # same bound the report list / selected routes use
REFERENCE_NOTE = "kbase 가공본 값, 계산 아님"
PROCESSED_LABEL = "kbase_kinase 가공본 · 미검수 · 기계 추출"
LINE_CAP = K.REPORT_MAX_LINES_PER_TARGET   # source lines per target (the rest is counted, never dropped silently)
HEX64 = re.compile(K.HEX64_PATTERN + r"\Z")
MAP_TYPE = (kp.MAP_KIND, kp.MAP_SCHEMA)
FIXED_LINES = frozenset((*K.LIMITATIONS, K.STATEMENTS["KT1"]))
CLAIM_KEYS = frozenset({"statement_id", "evidence_kind", "source_handle", "source_kind", "source_schema",
                        "source_sha256", "field_path", "row_selector", "subject", "quantity", "unit", "exact_value",
                        "rendered_value", "rounding", "operation", "reference"})
SOURCES = ("kbase_dist", "kbase_pubmed")   # the two capability source names (dist records / bibliography)
REFERENCE_KEYS = ("ref_id", "gene", "klifs_name", "group", "family")
BIBLIOGRAPHY_KEYS = ("title", "journal", "year", "doi")
LOCATION_KEYS = ("kind", "page", "table_index", "row", "figure_id", "panel")
INTEGRITY_KEYS = ("hash_verified", "quotes_within_limit", "locations_have_page")
VERSION_KEYS = ("kb_version", "schema_version", "effect_rules_version", "vocab_version")
UNITS = {"rows": "count", "location_page": "paper_page"}   # reference values that are numbers
EVIDENCE_STATEMENT = (
    "ProtView는 저장된 결과의 체인·표적·전례 개수만 다시 셌고, 무결성 확인 값(레코드 해시 일치·인용 25단어 이하·"
    "논문 쪽 위치 있음)은 연결할 때 ProtView가 한 확인을 그대로 적었다(ProtView 계산). 전례 필드(move_id·파일·"
    "해석 근거·변이 표기·PMID·서지·논문 위치·태그·원본 content_hash·kbase 기계 검사)와 kbase 참조는 kbase_kinase가 "
    "논문에서 기계로 추출한 미검수 기록의 값(kbase 가공본 값, 계산 아님)이며 ProtView가 계산하거나 판정한 것이 "
    "아니다. 인용문(관찰·교환)과 측정 변화 값은 이 보고서에 담지 않았다(화면에서만 본다). 보고서를 만들 때 연결을 "
    "다시 계산하지 않았다.")

# Fixed wording of every status / reason code (part of the template: checked for forbidden words).
STATUS_LABELS = {
    "linked": "연결함", "not_linked": "연결하지 않음",
    "no_mapped_residues": "번호 대응에 mapped 잔기 행이 없음",
    "multiple_accessions": "mapped 잔기의 accession이 둘 이상",
    "precedents_found": "포함한 파일에 전례 기록 있음",
    "none_in_included_files": "포함한 파일에 이 표적의 전례 기록 없음",
    "not_in_kbase_references": "kbase에 이 표적 참조가 없음(전례 없음과 다름)",
}
INCLUSION_LABELS = {True: "포함함", False: "포함하지 않음"}
LOCATION_LABELS = {"kind": "종류", "page": "쪽", "table_index": "표", "row": "행", "figure_id": "그림", "panel": "패널"}
BIBLIOGRAPHY_LABELS = {"title": "제목", "journal": "저널", "year": "연도", "doi": "DOI"}
INTEGRITY_LABELS = {"hash_verified": "레코드 해시 일치", "quotes_within_limit": "인용 25단어 이하",
                    "locations_have_page": "논문 쪽 위치 있음"}
EMPTY = "빈 목록 ([])"

EVIDENCE_KINDS = ("computed", "reference_value")
_T = r"targets\[\d+\]"
_R = _T + r"\.records\[\d+\]"
_CHECKS = "|".join(K.CHECK_NAMES)
# statement ID -> (evidence kind, field path rule); fixed template, nothing else carries a number in this report.
STATEMENTS: dict[str, tuple[str, re.Pattern[str]]] = {
    "chain_count": ("computed", re.compile(r"chains\[\*\]")),
    "chain_status_count": ("computed", re.compile(r"chains\[\*\]\.status")),
    "chain_reason_count": ("computed", re.compile(r"chains\[\*\]\.reason")),
    "chain_status": ("computed", re.compile(r"chains\[\d+\]\.(status|reason)")),
    "target_count": ("computed", re.compile(r"targets\[\*\]")),
    "flagged_inclusion": ("computed", re.compile(r"include_flagged")),
    "total_record_count": ("computed", re.compile(r"targets\[\*\]\.records\[\*\]\.file")),
    "total_excluded_count": ("computed", re.compile(r"targets\[\*\]\.excluded_flagged")),
    "unresolved_record_count": ("computed", re.compile(r"set_summary\.unresolved_target_records\.(moves|moves_flagged)")),
    "unresolved_record_total": ("computed", re.compile(r"set_summary\.unresolved_target_records")),
    "target_status": ("computed", re.compile(_T + r"\.status")),
    "target_record_count": ("computed", re.compile(_T + r"\.records\[\*\]\.file")),
    "target_excluded_count": ("computed", re.compile(_T + r"\.excluded_flagged")),
    "target_variant_count": ("computed", re.compile(_T + r"\.records\[\*\]\.record\.target\.variant")),
    "target_tag_count": ("computed", re.compile(_T + r"\.records\[\*\]\.record\.tags\.(site|goal|tactic)")),
    "target_basis_count": ("computed", re.compile(_T + r"\.records\[\*\]\.record\.target\.resolution_basis")),
    "unlisted_record_count": ("computed", re.compile(_T + r"\.records\[\*\]")),
    "record_pass_check_count": ("computed", re.compile(_R + r"\.record\.checks\[\*\]\.status")),
    "record_integrity": ("computed", re.compile(_R + r"\.integrity\.(" + "|".join(INTEGRITY_KEYS) + r")")),
    "reference_set_rows": ("reference_value", re.compile(
        r"precedent_set\.(files\[\d+\]|bibliography_snapshot\.file)\.rows")),
    "reference_target_ref": ("reference_value", re.compile(
        _T + r"\.references\[\d+\]\.(" + "|".join(REFERENCE_KEYS) + r")")),
    "reference_record_id": ("reference_value", re.compile(_R + r"\.record\.move_id")),
    "reference_record_file": ("reference_value", re.compile(_R + r"\.file")),
    "reference_record_target": ("reference_value", re.compile(_R + r"\.record\.target\.(resolution_basis|variant)")),
    "reference_record_pmid": ("reference_value", re.compile(_R + r"\.record\.source\.pmid")),
    "reference_bibliography": ("reference_value", re.compile(
        r"bibliography\.[0-9]+\.(" + "|".join(BIBLIOGRAPHY_KEYS) + r")")),
    "reference_record_location": ("reference_value", re.compile(
        _R + r"\.record\.source\.locations\[\d+\]\.(" + "|".join(LOCATION_KEYS) + r")")),
    "reference_record_tag": ("reference_value", re.compile(_R + r"\.record\.tags\.(site|goal|tactic)\[\d+\]")),
    "reference_record_hash": ("reference_value", re.compile(_R + r"\.record\.content_hash")),
    "reference_record_check": ("reference_value", re.compile(_R + r"\.record\.checks\.(" + _CHECKS + r")\.status")),
}
STATEMENT_IDS = tuple(STATEMENTS)
COMPUTED_FIELDS = re.compile("|".join(f"(?:{rule.pattern})" for kind, rule in STATEMENTS.values()
                                      if kind == "computed"))
REFERENCE_FIELDS = re.compile("|".join(f"(?:{rule.pattern})" for kind, rule in STATEMENTS.values()
                                       if kind == "reference_value"))
# The M15, M20 and M26 interpretive lists (with their English counterparts) plus the M27 words (spec 7). Handles are
# lowercase hex, identifiers and kbase strings (tag terms, variants, titles) are slots, so none of them is checked.
INTERPRETIVE = re.compile(
    # M15
    r"important|critical|essential|key residue|binding|binds|affinity|stabili[sz]|druggab|inhibit|selectiv|"
    r"potency|functional|중요|결합|친화|안정화|억제|선택성|핵심|기능|"
    # M20
    r"안정성|ΔΔG|ddG|delta\s*delta|순위|추천|최적|개선|활성|예측|유망|좋은|나쁜|안전|점수|에너지|수소\s*결합|\brank|"
    r"\bbest\b|recommend|optimal|improv|predict|promising|\bgood\b|\bsafe|\bactiv(e|ity)\b|\bscor(e|ing)\b|energ|"
    r"hydrogen[\s_-]?bond|\bh-?bond|"
    # M26
    r"필수|메커니즘이\s*유지|mechanism\W+(?:is\W+)?(?:preserved|maintained|retained|conserved)|"
    # M27
    r"성공률|검증됨|신뢰|효과|승자|success[\s_-]*rate|\bverified\b|\bvalidated\b|\btrust|\breliab|\beffects?\b|"
    r"\bwinner", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget", "active_set_hash"}
COPIED_FIELDS = ("method_version", "numbering_map", "structure", "pdb_id", "include_flagged", "record_format",
                 "precedent_set", "chains", "set_summary", "counts", "null_result", "limitations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "target_sources", "listed_bibliography", "claims", "provenance",
    "evidence_statement", "snapshot", "markdown_handle"})


# ---------------------------------------------------------------------------------------------------------------
# rendering of one value

def _verbatim(value: Any) -> str:
    if type(value) is str:
        return value
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    return canonical_json(value).decode("utf-8")   # any other JSON value of a kbase field, as JSON text


def _render(value: Any, rounding: str) -> str:
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("precedent_claim_integer_expected")
        return str(value)
    if rounding == "status":
        if type(value) is not str or value not in STATUS_LABELS:
            raise EvidenceError("precedent_claim_value_type")
        return f"{STATUS_LABELS[value]} ({value})"
    if rounding == "inclusion":
        if type(value) is not bool:
            raise EvidenceError("precedent_claim_value_type")
        return f"{INCLUSION_LABELS[value]} (include_flagged {'true' if value else 'false'})"
    if rounding == "flag":
        if type(value) is not bool:
            raise EvidenceError("precedent_claim_value_type")
        return "true" if value else "false"
    if rounding == "verbatim":
        return _verbatim(value)
    raise EvidenceError("precedent_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the fixed sentences KP1-KP6 or KT1."""
    for line in text.split("\n"):
        if line in FIXED_LINES:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"precedent_report_interpretive_statement: {match.group(0)}")
    return text


# ---------------------------------------------------------------------------------------------------------------
# source validation (stored objects of this run only; the linking is never run again)

def validated_precedent_result(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a stored result produced by the tool in this run; (content, provenance)."""
    try:
        own = f"obj://{run.run_id}/"
        if type(handle) is not str or not handle.startswith(own):
            raise EvidenceError("precedent_result_other_run")
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (K.KIND, K.SCHEMA):
            raise EvidenceError("wrong_result_kind")
        try:
            content = kp.validated_result(run.store.load(handle))
        except (kp.ResultInvalid, RecursionError) as exc:
            raise EvidenceError(f"precedent_result_invalid: {exc}") from exc
        provenance = _provenance(list(run.events.read()), handle, expected_tool=K.TOOL)
        structure = content["structure"]
        if (not structure["handle"].startswith(own) or
                run.store.meta(structure["handle"])["kind"] != structure["structure_kind"]):
            raise EvidenceError("precedent_structure_link_mismatch")
        map_handle = content["numbering_map"]["handle"]
        map_meta = run.store.meta(map_handle)
        if (map_meta["kind"], map_meta["schema"]) != MAP_TYPE:
            raise EvidenceError("precedent_numbering_map_kind")
        map_content = run.store.load(map_handle)
        if {key: map_content["structure"][key] for key in ("handle", "structure_kind", "model_number")} != structure:
            raise EvidenceError("precedent_numbering_map_structure_mismatch")
        if map_content["pdb_id"] != content["pdb_id"]:
            raise EvidenceError("precedent_numbering_map_pdb_mismatch")
        return content, provenance
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError, RecursionError) as exc:
        raise EvidenceError("precedent_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# claims

def _sha(index: int, item: Any) -> str:
    return hashlib.sha256(canonical_json({"index": index, "row": item})).hexdigest()


def _reference(precedent_set: dict[str, Any], source: str) -> dict[str, Any]:
    return {"note": REFERENCE_NOTE, "set_hash": precedent_set["set_hash"],
            "kb_version": precedent_set["kbase"]["kb_version"], "imported_at": precedent_set["imported_at"],
            "source": source}


def _tally(values: list[str], label: str) -> list[dict[str, Any]]:
    counter = Counter(values)
    return [{label: value, "count": counter[value]} for value in sorted(counter)]


def recount_target(records: list[dict[str, Any]], include_flagged: bool) -> dict[str, Any]:
    """``targets[].counts`` recounted here from the stored records (same rule as the linking: a record counts once
    per distinct tag term); compared with the stored counts before any claim is made."""
    copies = [item["record"] for item in records]
    return {"moves": sum(1 for item in records if item["file"] == "moves"),
            "moves_flagged": sum(1 for item in records if item["file"] == "moves_flagged") if include_flagged else None,
            "variants": _tally([r["target"]["variant"] for r in copies], "variant"),
            "tags": {axis: _tally([term for r in copies for term in set(r["tags"][axis])], "term")
                     for axis in K.TAG_AXES},
            "resolution_basis": _tally([r["target"]["resolution_basis"] for r in copies], "basis")}


def _source_line(item: dict[str, Any]) -> dict[str, Any]:
    """The quote-free source line of one record (what the report lists; no observation, tradeoff or effect)."""
    record = item["record"]
    return {"file": item["file"], "move_id": record["move_id"], "pmid": record["source"]["pmid"],
            "resolution_basis": record["target"]["resolution_basis"], "variant": record["target"]["variant"],
            "locations": [{key: location[key] for key in LOCATION_KEYS if key in location}
                          for location in record["source"]["locations"]],
            "tags": {axis: list(record["tags"][axis]) for axis in K.TAG_AXES},
            "content_hash": record["content_hash"],
            "checks": {name: record["checks"][name]["status"] for name in K.CHECK_NAMES},
            "integrity": {key: item["integrity"][key] for key in INTEGRITY_KEYS}}


def target_sources(content: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for target in content["targets"]:
        records = target["records"]
        out.append({"accession": target["accession"], "chains": list(target["chains"]), "status": target["status"],
                    "references": [{key: ref[key] for key in REFERENCE_KEYS} for ref in target["references"]],
                    "excluded_flagged": target["excluded_flagged"], "counts": target["counts"],
                    "records": [_source_line(item) for item in records[:LINE_CAP]],
                    "unlisted_records": max(0, len(records) - LINE_CAP)})
    return out


def listed_bibliography(content: dict[str, Any]) -> dict[str, Any]:
    """Bibliography (title / journal / year / DOI, or null = no bibliography) of the listed records' PMIDs."""
    pmids = sorted({item["record"]["source"]["pmid"] for target in content["targets"]
                    for item in target["records"][:LINE_CAP]})
    books = content["bibliography"]
    return {pmid: None if books[pmid] is None else {key: books[pmid][key] for key in BIBLIOGRAPHY_KEYS}
            for pmid in pmids}


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; each count is recounted from the stored result (never copied)."""
    precedent_set = content["precedent_set"]
    base_subject = {"result_handle": handle, "structure_handle": content["structure"]["handle"]}
    claims: list[dict[str, Any]] = []

    def add(statement: str, path: str, selector: dict[str, Any] | None, quantity: str, unit: str, value: Any,
            rounding: str, operation: str | None = None, source: str | None = None) -> None:
        kind = STATEMENTS[statement][0]
        if (kind == "reference_value") is (source is None):
            raise EvidenceError("precedent_claim_kind_rule")   # programming guard: reference claims name a source
        claims.append({"statement_id": statement, "evidence_kind": kind, "source_handle": handle,
                       "source_kind": K.KIND, "source_schema": K.SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
                       "field_path": path, "row_selector": selector, "subject": dict(base_subject),
                       "quantity": quantity, "unit": unit, "exact_value": value,
                       "rendered_value": _render(value, rounding), "rounding": rounding, "operation": operation,
                       "reference": None if source is None else _reference(precedent_set, source)})

    def ref(statement: str, path: str, selector: dict[str, Any], quantity: str, value: Any,
            source: str = "kbase_dist") -> None:
        unit = UNITS.get(quantity) or {str: "text", bool: "flag"}.get(type(value), "identifier")
        add(statement, path, selector, quantity, unit, value, "verbatim", None, source)

    chains, targets, include = content["chains"], content["targets"], content["include_flagged"]
    files = K.FILE_SOURCES if include else ("moves",)
    _check_totals(content)
    add("chain_count", "chains[*]", None, "chains", "count", len(chains), "integer", "count(chains)")
    for status in K.CHAIN_STATUSES:
        add("chain_status_count", "chains[*].status", {"status": status}, f"{status}_chains", "count",
            sum(c["status"] == status for c in chains), "integer", f"count_where(status == {status}; chains)")
    for reason in K.CHAIN_REASONS:
        add("chain_reason_count", "chains[*].reason", {"reason": reason}, f"{reason}_chains", "count",
            sum(c["reason"] == reason for c in chains), "integer", f"count_where(reason == {reason}; chains)")
    for ci, chain in enumerate(chains):
        sel = {"chain_auth": chain["chain_auth"]}
        add("chain_status", f"chains[{ci}].status", sel, "chain_status", "status", chain["status"], "status")
        if chain["reason"] is not None:
            add("chain_status", f"chains[{ci}].reason", sel, "chain_reason", "status", chain["reason"], "status")
    add("target_count", "targets[*]", None, "targets", "count", len(targets), "integer", "count(targets)")
    add("flagged_inclusion", "include_flagged", None, "include_flagged", "flag", include, "inclusion")
    for name in files:   # a file that was not included gets no number (the inclusion claim only)
        add("total_record_count", "targets[*].records[*].file", {"file": name}, f"{name}_records", "count",
            sum(item["file"] == name for t in targets for item in t["records"]), "integer",
            f"count_where(file == {name}; records of all targets)")
    if not include:
        add("total_excluded_count", "targets[*].excluded_flagged", None, "excluded_moves_flagged", "count",
            sum(t["excluded_flagged"] for t in targets), "integer", "sum(excluded_flagged; targets)")
    unresolved = content["set_summary"]["unresolved_target_records"]
    for name in K.FILE_SOURCES:
        add("unresolved_record_count", f"set_summary.unresolved_target_records.{name}", {"file": name},
            f"unresolved_{name}_records", "count", unresolved[name], "integer",
            "stored set-wide count (records with a null target accession)")
    add("unresolved_record_total", "set_summary.unresolved_target_records", None, "unresolved_records", "count",
        sum(unresolved[name] for name in K.FILE_SOURCES), "integer", "sum(moves, moves_flagged)")
    for fi, entry in enumerate(precedent_set["files"]):
        ref("reference_set_rows", f"precedent_set.files[{fi}].rows", {"file": entry["name"]}, "rows", entry["rows"])
    bibliography_file = precedent_set["bibliography_snapshot"]["file"]
    ref("reference_set_rows", "precedent_set.bibliography_snapshot.file.rows", {"file": bibliography_file["name"]},
        "rows", bibliography_file["rows"], "kbase_pubmed")
    for ti, target in enumerate(targets):
        _target_claims(add, ref, f"targets[{ti}]", target, files, include)
    for pmid, entry in listed_bibliography(content).items():
        for key in BIBLIOGRAPHY_KEYS:
            if entry is not None and entry[key] is not None:
                ref("reference_bibliography", f"bibliography.{pmid}.{key}", {"pmid": pmid}, f"bibliography_{key}",
                    entry[key], "kbase_pubmed")
    return claims


def _check_totals(content: dict[str, Any]) -> None:
    """The stored ``counts`` and every ``targets[].counts`` equal the counts recounted here."""
    include, chains, targets = content["include_flagged"], content["chains"], content["targets"]
    for target in targets:
        if canonical_json(recount_target(target["records"], include)) != canonical_json(target["counts"]):
            raise EvidenceError("precedent_count_mismatch")
    linked = sum(1 for c in chains if c["status"] == "linked")
    recount = {"chains": len(chains), "linked_chains": linked, "not_linked_chains": len(chains) - linked,
               "targets": len(targets),
               "records": {"moves": sum(t["counts"]["moves"] for t in targets),
                           "moves_flagged": sum(t["counts"]["moves_flagged"] for t in targets) if include else None},
               "excluded_moves_flagged": None if include else sum(t["excluded_flagged"] for t in targets)}
    if canonical_json(recount) != canonical_json(content["counts"]):
        raise EvidenceError("precedent_count_mismatch")


def _target_claims(add: Callable, ref: Callable, prefix: str, target: dict[str, Any], files: tuple[str, ...],
                   include: bool) -> None:
    tsel = {"accession": target["accession"]}
    records = target["records"]
    add("target_status", f"{prefix}.status", tsel, "target_status", "status", target["status"], "status")
    for name in files:
        add("target_record_count", f"{prefix}.records[*].file", {**tsel, "file": name}, f"{name}_records", "count",
            sum(item["file"] == name for item in records), "integer", f"count_where(file == {name}; records)")
    if not include:
        add("target_excluded_count", f"{prefix}.excluded_flagged", tsel, "excluded_moves_flagged", "count",
            target["excluded_flagged"], "integer", "stored count (moves_flagged records of this target not included)")
    variants = Counter(item["record"]["target"]["variant"] for item in records)
    for variant in sorted(variants):
        add("target_variant_count", f"{prefix}.records[*].record.target.variant", {**tsel, "variant": variant},
            "records_with_variant", "count", variants[variant], "integer", "count_where(record.target.variant)")
    for axis in K.TAG_AXES:
        terms = Counter(term for item in records for term in set(item["record"]["tags"][axis]))
        for term in sorted(terms):
            add("target_tag_count", f"{prefix}.records[*].record.tags.{axis}", {**tsel, "axis": axis, "term": term},
                "records_with_tag", "count", terms[term], "integer",
                f"count_where(term in record.tags.{axis}; once per record)")
    bases = Counter(item["record"]["target"]["resolution_basis"] for item in records)
    for basis in sorted(bases):
        add("target_basis_count", f"{prefix}.records[*].record.target.resolution_basis", {**tsel, "basis": basis},
            "records_with_basis", "count", bases[basis], "integer", "count_where(record.target.resolution_basis)")
    for k, reference in enumerate(target["references"]):
        rsel = {**tsel, "ref_id": reference["ref_id"]}
        for key in REFERENCE_KEYS:
            if reference[key] is not None:
                ref("reference_target_ref", f"{prefix}.references[{k}].{key}", rsel, key, reference[key])
    for ri, item in enumerate(records[:LINE_CAP]):
        _record_claims(add, ref, f"{prefix}.records[{ri}]",
                       {**tsel, "record_index": ri, "move_id": item["record"]["move_id"],
                        "record_sha256": _sha(ri, item)}, item)
    if len(records) > LINE_CAP:
        add("unlisted_record_count", f"{prefix}.records[*]", tsel, "unlisted_records", "count",
            len(records) - LINE_CAP, "integer", f"count(records after the first {LINE_CAP} listed)")


def _record_claims(add: Callable, ref: Callable, path: str, rsel: dict[str, Any], item: dict[str, Any]) -> None:
    record = item["record"]
    ref("reference_record_id", f"{path}.record.move_id", rsel, "move_id", record["move_id"])
    ref("reference_record_file", f"{path}.file", rsel, "file", item["file"])
    for key in ("resolution_basis", "variant"):
        ref("reference_record_target", f"{path}.record.target.{key}", rsel, key, record["target"][key])
    ref("reference_record_pmid", f"{path}.record.source.pmid", rsel, "pmid", record["source"]["pmid"])
    for li, location in enumerate(record["source"]["locations"]):
        for key in LOCATION_KEYS:
            if location.get(key) is not None:
                ref("reference_record_location", f"{path}.record.source.locations[{li}].{key}",
                    {**rsel, "location_index": li}, f"location_{key}", location[key])
    for axis in K.TAG_AXES:
        for k, term in enumerate(record["tags"][axis]):
            ref("reference_record_tag", f"{path}.record.tags.{axis}[{k}]", rsel, f"tag_{axis}", term)
    ref("reference_record_hash", f"{path}.record.content_hash", rsel, "content_hash", record["content_hash"])
    checks = record["checks"]
    add("record_pass_check_count", f"{path}.record.checks[*].status", {**rsel, "status": "pass"}, "pass_checks",
        "count", sum(checks[name]["status"] == "pass" for name in K.CHECK_NAMES), "integer",
        "count_where(status == pass; the ten kbase checks)")
    for name in K.CHECK_NAMES:
        if checks[name]["status"] != "pass":
            ref("reference_record_check", f"{path}.record.checks.{name}.status", rsel, f"check_{name}",
                checks[name]["status"])
    for key in INTEGRITY_KEYS:
        add("record_integrity", f"{path}.integrity.{key}", rsel, key, "flag", item["integrity"][key], "flag")


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def claim_index(expected_claims: list[dict[str, Any]]) -> tuple[dict[tuple[str, str, bytes], dict[str, Any]], set]:
    """(claims by key, source handles) of the expected claims, built once per reopen."""
    return {_key(claim): claim for claim in expected_claims}, {claim["source_handle"] for claim in expected_claims}


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any, *, index: tuple | None = None) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim built from that field."""
    by_key, handles = index if index is not None else claim_index(expected_claims)
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("precedent_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("precedent_claim_statement_not_allowed")
    kind, rule = STATEMENTS[statement]
    if proposed["evidence_kind"] not in EVIDENCE_KINDS or proposed["evidence_kind"] != kind:
        raise EvidenceError("precedent_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str:
        raise EvidenceError("precedent_claim_shape")
    if kind == "computed":
        if REFERENCE_FIELDS.fullmatch(path):
            raise EvidenceError("precedent_claim_reference_field_as_computed")
        if not rule.fullmatch(path) or proposed["reference"] is not None:
            raise EvidenceError("precedent_claim_computed_field_rule")
    else:
        if COMPUTED_FIELDS.fullmatch(path):
            raise EvidenceError("precedent_claim_computed_field_as_reference")
        reference = proposed["reference"]
        if not rule.fullmatch(path) or type(reference) is not dict or reference.get("note") != REFERENCE_NOTE:
            raise EvidenceError("precedent_claim_reference_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (K.KIND, K.SCHEMA):
        raise EvidenceError("precedent_claim_source_kind_mismatch")
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("precedent_claim_source_mismatch")
    try:
        match = by_key.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("precedent_claim_shape") from exc
    if match is None:
        raise EvidenceError("precedent_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("precedent_claim_binding_mismatch")
    return proposed


def validate_precedent_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored result (not snapshot / markdown handle)."""
    content, provenance = validated_precedent_result(run, handle)
    try:
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": K.SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS},
                "target_sources": target_sources(content), "listed_bibliography": listed_bibliography(content),
                "claims": claims_for(handle, content),
                "provenance": {key: provenance[key] for key in ("call_id", "tool", "tool_version",
                                                                "created_event_seq", "completed_event_seq")},
                "evidence_statement": EVIDENCE_STATEMENT}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("precedent_report_evidence_unresolved") from exc


_SLOT = re.compile("\x00(\\d+)\x00")


class _Template:
    """The fixed template lines plus slots; every value comes from a bound claim of the manifest.

    ``value`` (counts, status wording) is template text and is checked for forbidden words; ``slot`` / ``ref``
    (identifiers and kbase strings) are left empty for that check and filled afterwards.
    """

    def __init__(self, claims: list[dict[str, Any]]) -> None:
        self.index: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for claim in claims:
            self.index.setdefault((claim["statement_id"], claim["field_path"]), []).append(claim)
        self.slots: list[str] = []
        self.lines: list[str] = []

    def slot(self, text: Any) -> str:
        self.slots.append(_md(text))
        return f"\x00{len(self.slots) - 1}\x00"

    def find(self, statement: str, path: str, **selector: Any) -> dict[str, Any]:
        """The one claim of ``statement`` at ``path`` whose selector holds ``selector``."""
        found = [c for c in self.index.get((statement, path), [])
                 if all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("precedent_report_claim_missing")
        return found[0]

    def value(self, statement: str, path: str, **selector: Any) -> str:
        return _md(self.find(statement, path, **selector)["rendered_value"])

    def ref(self, statement: str, path: str, **selector: Any) -> str:
        text = self.find(statement, path, **selector)["rendered_value"]
        return self.slot(text) if text != "" else "\"\""   # an empty string stays visible as ""

    def optional(self, statement: str, path: str, present: Any) -> str:
        return self.ref(statement, path) if present is not None else "null"

    def text(self) -> str:
        template = "\n".join(self.lines)
        check_no_interpretation(_SLOT.sub("", template))
        return _SLOT.sub(lambda match: self.slots[int(match.group(1))], template)


def _basis(active: str | None, set_hash: str) -> str:
    if active is None:
        return "사용 중 스냅샷 없음: 보고서를 만들 때 사용할 수 있는 전례 참조 세트가 없었다."
    if active != set_hash:
        return "이전 스냅샷 기준: 결과의 세트가 보고서를 만들 때 사용 중이던 세트와 다르다. 결과를 다시 계산하지 않았다."
    return "결과의 세트가 보고서를 만들 때 사용 중이던 세트와 같다."


def _note(key: str, value: str | None = None) -> str:
    """A list item holding screen note ``key`` verbatim (UP2 / UP5: ``N`` replaced by the rendered integer of a bound
    claim), so Markdown never folds it into the bullet above."""
    text = K.SCREEN_NOTES[key]
    return "- " + (text if value is None else text.replace("N건", f"{value}건", 1))


def _per_file(t: _Template, statement: str, path: str, include: bool, **selector: Any) -> str:
    """``moves N; moves_flagged M`` -- a file that was not included shows the inclusion claim, no number."""
    flagged = (t.value(statement, path, file="moves_flagged", **selector) if include
               else t.value("flagged_inclusion", "include_flagged"))
    return f"moves {t.value(statement, path, file='moves', **selector)}; moves\\_flagged {flagged}"


def render_precedent_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every value is the rendered text of a bound claim."""
    t = _Template(manifest["claims"])
    structure, pset, snapshot = manifest["structure"], manifest["precedent_set"], manifest["snapshot"]
    active, include, kbase = snapshot["active_set_hash"], manifest["include_flagged"], pset["kbase"]
    pdb_id = t.slot(manifest["pdb_id"]) if manifest["pdb_id"] is not None else "null (번호 대응에 PDB ID가 없다)"
    t.lines.extend([
        "# 키나아제 전례 보고서 (kinase precedents)", "", "Status: complete", "",
        f"Result: {t.slot(manifest['result_handle'])}",
        (f"Structure: {t.slot(structure['handle'])} ({t.slot(structure['structure_kind'])}, "
         f"model {t.slot(structure['model_number'])})"),
        f"Numbering map: {t.slot(manifest['numbering_map']['handle'])}",
        f"Method: {t.slot(manifest['method_version'])}", "",
        f"- PDB ID (번호 대응에서 복사): {pdb_id}",
        f"- moves\\_flagged 파일 전례: {t.value('flagged_inclusion', 'include_flagged')}",
        f"- 전례 사본 형식: {t.slot(manifest['record_format'])}", "",
        f"**{_md(manifest['evidence_statement'])}**", "",
        "## 전례 참조 스냅샷", "", _md(PROCESSED_LABEL), "", K.STATEMENTS["KT1"], "",
        "| 항목 | 값 |", "| --- | --- |",
        f"| 세트 해시 | {t.slot(pset['set_hash'])} |",
        f"| 가져온 시각 | {t.slot(pset['imported_at'])} |",
        f"| 가져오기 명령 버전 | {t.slot(pset['importer_version'])} |",
        f"| 출처 | {t.slot(kbase['origin'])} |",
        f"| kbase 커밋 (HEAD) | {t.slot(kbase['commit'])} |",
        ("| dist 커밋 | " + (t.slot(kbase["dist_commit"]) if kbase["dist_commit"] is not None
                            else "null (dist를 추적하는 커밋 없음)") + " |"),
        ("| dist 커밋 날짜 | " + (t.slot(kbase["dist_commit_date"]) if kbase["dist_commit_date"] is not None
                               else "날짜 없음 (null)") + " |"),
        f"| dirty | {t.slot('true' if kbase['dirty'] else 'false')} |"])
    t.lines.extend(f"| {t.slot(key)} | {t.slot(kbase[key])} |" for key in VERSION_KEYS)
    bibliography = pset["bibliography_snapshot"]
    t.lines.extend([
        f"| source\\_snapshots | {', '.join(t.slot(s) for s in kbase['source_snapshots']) or EMPTY} |",
        (f"| 서지 스냅샷 | {t.slot(bibliography['snapshot_id'])}; 날짜 {t.slot(bibliography['date'])}; 라이선스 "
         f"{t.slot(bibliography['license'])}; 출처 {t.slot(bibliography['origin'])} |"), "",
        f"| 파일 | 행 수 ({REFERENCE_NOTE}) | SHA\\-256 |", "| --- | ---: | --- |"])
    for fi, entry in enumerate(pset["files"]):
        t.lines.append(f"| {t.slot(entry['name'])} | {t.ref('reference_set_rows', f'precedent_set.files[{fi}].rows')} "
                       f"| {t.slot(entry['sha256'])} |")
    rows = t.ref("reference_set_rows", "precedent_set.bibliography_snapshot.file.rows")
    t.lines.extend([
        f"| {t.slot(bibliography['file']['name'])} | {rows} | {t.slot(bibliography['file']['sha256'])} |", "",
        f"- 보고서를 만들 때 사용 중이던 전례 참조 세트: {t.slot(active) if active is not None else '없음 (null)'}",
        f"- {_basis(active, pset['set_hash'])}", ""])
    _render_overview(t, manifest, include)
    _render_chains(t, manifest["chains"])
    if not manifest["target_sources"]:
        t.lines.extend(["", "## 표적", "", f"- 표적: {EMPTY} — 연결한 체인이 없어 표적을 만들지 않았다."])
    for ti, source in enumerate(manifest["target_sources"]):
        _render_target(t, f"targets[{ti}]", source, manifest["listed_bibliography"], include)
    t.lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        t.lines.extend([item, ""])
    t.lines.extend([(f"Exact values, evidence kinds and field paths are in the JSON download "
                     f"({len(manifest['claims'])} claims). Quotes and measured changes are not in this report; every "
                     "record is in the stored result."), ""])
    return t.text()


def _render_overview(t: _Template, manifest: dict[str, Any], include: bool) -> None:
    statuses = "; ".join(f"{STATUS_LABELS[s]} ({_md(s)}) {t.value('chain_status_count', 'chains[*].status', status=s)}"
                         for s in K.CHAIN_STATUSES)
    reasons = "; ".join(f"{STATUS_LABELS[r]} ({_md(r)}) {t.value('chain_reason_count', 'chains[*].reason', reason=r)}"
                        for r in K.CHAIN_REASONS)
    unresolved = "set_summary.unresolved_target_records"
    t.lines.extend([
        "## 전체 개수 (ProtView 계산: 저장된 결과의 개수)", "",
        f"- 체인 수: {t.value('chain_count', 'chains[*]')}",
        f"- 체인 상태별 수: {statuses}",
        f"- 연결하지 않은 이유별 체인 수: {reasons}",
        f"- 표적 수: {t.value('target_count', 'targets[*]')}",
        f"- 포함한 전례 수 (모든 표적): {_per_file(t, 'total_record_count', 'targets[*].records[*].file', include)}"])
    if not include:
        t.lines.append("- 포함하지 않은 moves\\_flagged 전례 수 (모든 표적): "
                       f"{t.value('total_excluded_count', 'targets[*].excluded_flagged')}")
    t.lines.extend([
        (f"- 세트 전체 표적 미해석 전례 수 (세트 전체, 체인과 무관): moves "
         f"{t.value('unresolved_record_count', f'{unresolved}.moves')}; moves\\_flagged "
         f"{t.value('unresolved_record_count', f'{unresolved}.moves_flagged')}"),
        _note("UP5", t.value("unresolved_record_total", unresolved))])
    if manifest["null_result"]:
        t.lines.append("- 이 결과는 유효한 빈 결과(scientific\\_null)이며 실패가 아니다.")


def _render_chains(t: _Template, chains: list[dict[str, Any]]) -> None:
    t.lines.extend(["", "## 체인", "",
                    "| 체인 | 상태 (ProtView 계산) | 이유 (ProtView 계산) | accession | 번호 대응의 mapped accession |",
                    "| --- | --- | --- | --- | --- |"])
    for ci, chain in enumerate(chains):
        reason = t.value("chain_status", f"chains[{ci}].reason") if chain["reason"] is not None else "—"
        accession = t.slot(chain["accession"]) if chain["accession"] is not None else "— (null)"
        accessions = ", ".join(t.slot(a) for a in chain["accessions"]) or EMPTY
        t.lines.append(f"| {t.slot(chain['chain_auth'])} | {t.value('chain_status', f'chains[{ci}].status')} | "
                       f"{reason} | {accession} | {accessions} |")


def _render_target(t: _Template, prefix: str, source: dict[str, Any], books: dict[str, Any], include: bool) -> None:
    acc = source["accession"]
    variants = "; ".join(
        f"{t.slot(v['variant'])} "
        f"{t.value('target_variant_count', f'{prefix}.records[*].record.target.variant', variant=v['variant'])}"
        for v in source["counts"]["variants"]) or EMPTY
    tags = "; ".join(f"{axis} " + (", ".join(
        f"{t.slot(v['term'])} "
        f"{t.value('target_tag_count', f'{prefix}.records[*].record.tags.{axis}', axis=axis, term=v['term'])}"
        for v in source["counts"]["tags"][axis]) or EMPTY) for axis in K.TAG_AXES)
    bases = "; ".join(
        f"{t.slot(v['basis'])} "
        f"{t.value('target_basis_count', f'{prefix}.records[*].record.target.resolution_basis', basis=v['basis'])}"
        for v in source["counts"]["resolution_basis"]) or EMPTY
    t.lines.extend([
        "", f"## 표적 {t.slot(acc)}", "",
        f"- 체인: {', '.join(t.slot(c) for c in source['chains'])}",
        f"- 상태 (ProtView 계산): {t.value('target_status', f'{prefix}.status')}",
        f"- 포함한 파일의 전례 수 (ProtView 계산): {_per_file(t, 'target_record_count', f'{prefix}.records[*].file', include)}"])
    if source["excluded_flagged"] is not None:
        t.lines.append(_note("UP2", t.value("target_excluded_count", f"{prefix}.excluded_flagged")))
    t.lines.extend([f"- 변이 표기별 전례 수 (ProtView 계산): {variants}", _note("UP3"),
                    f"- 태그별 전례 수 (ProtView 계산, 한 전례의 같은 태그는 한 번): {tags}",
                    f"- 해석 근거별 전례 수 (ProtView 계산): {bases}"])
    if source["references"]:
        t.lines.extend([f"- kbase 참조 ({REFERENCE_NOTE}):", "", "| ref\\_id | gene | KLIFS 이름 | group | family |",
                        "| --- | --- | --- | --- | --- |"])
        for k, reference in enumerate(source["references"]):
            cells = [t.optional("reference_target_ref", f"{prefix}.references[{k}].{key}", reference[key])
                     for key in REFERENCE_KEYS]
            t.lines.append("| " + " | ".join(cells) + " |")
    else:
        t.lines.append(f"- kbase 참조: {EMPTY}")
    if not source["records"]:
        t.lines.extend([""] * bool(source["references"]) + [f"- 전례 출처 목록: {EMPTY}"])   # a table ends first
        return
    t.lines.extend([
        "", (f"전례 출처 목록 ({REFERENCE_NOTE}): 이 표적에서 최대 {LINE_CAP}줄, move\\_id 순서. kbase 기계 검사는 "
             "kbase가 만들 때 한 결과를 그대로 적은 것이고 ProtView 무결성 확인은 ProtView가 한 확인이다. 둘 다 원문 "
             "대조가 아니다."), "", K.SCREEN_NOTES["UP1"], "",
        ("| move\\_id | 파일 | 해석 근거 | 변이 표기 | PMID | 서지 | 논문 위치 | 태그 | 원본 content\\_hash | "
         "kbase 기계 검사 (pass 개수는 ProtView 계산) | ProtView 무결성 확인 (ProtView 계산) |"),
        "| " + " | ".join(["---"] * 11) + " |"])
    for ri, line in enumerate(source["records"]):
        t.lines.append(_record_row(t, f"{prefix}.records[{ri}]", line, books))
    if source["unlisted_records"]:
        unlisted = t.value("unlisted_record_count", f"{prefix}.records[*]")
        t.lines.extend(["", f"- 이 보고서에 나열하지 않은 전례 (ProtView 계산): {unlisted} (전체는 결과 객체에 있다)"])


def _record_row(t: _Template, path: str, line: dict[str, Any], books: dict[str, Any]) -> str:
    pmid = line["pmid"]
    entry = books[pmid]
    if entry is None:
        bibliography = "서지 없음 (null)"
    else:
        bibliography = "; ".join(
            f"{BIBLIOGRAPHY_LABELS[key]} {t.optional('reference_bibliography', f'bibliography.{pmid}.{key}', entry[key])}"
            for key in BIBLIOGRAPHY_KEYS)
    locations = "; ".join(", ".join(
        f"{LOCATION_LABELS[key]} {t.ref('reference_record_location', f'{path}.record.source.locations[{li}].{key}')}"
        for key in LOCATION_KEYS if location.get(key) is not None) for li, location in enumerate(line["locations"]))
    tags = "; ".join(f"{axis} " + (", ".join(t.ref("reference_record_tag", f"{path}.record.tags.{axis}[{k}]")
                                             for k in range(len(line["tags"][axis]))) or EMPTY)
                     for axis in K.TAG_AXES)
    checks = f"pass {t.value('record_pass_check_count', f'{path}.record.checks[*].status')}개" + "".join(
        f"; {t.slot(name)}={t.ref('reference_record_check', f'{path}.record.checks.{name}.status')}"
        for name in K.CHECK_NAMES if line["checks"][name] != "pass")
    integrity = "; ".join(f"{INTEGRITY_LABELS[key]} {t.value('record_integrity', f'{path}.integrity.{key}')}"
                          for key in INTEGRITY_KEYS)
    cells = [t.ref("reference_record_id", f"{path}.record.move_id"), t.ref("reference_record_file", f"{path}.file"),
             t.ref("reference_record_target", f"{path}.record.target.resolution_basis"),
             t.ref("reference_record_target", f"{path}.record.target.variant"),
             t.ref("reference_record_pmid", f"{path}.record.source.pmid"), bibliography, locations, tags,
             t.ref("reference_record_hash", f"{path}.record.content_hash"), checks, integrity]
    return "| " + " | ".join(cells) + " |"


def build_precedent_report(run: Any, result_handle: str, *, active_set_hash: str | None) -> dict[str, Any]:
    """New report object from the stored result (the linking is not run again); ``active_set_hash`` is the active
    precedent reference set at creation (None when none is usable), recorded in the report snapshot only."""
    if active_set_hash is not None and (type(active_set_hash) is not str or not HEX64.fullmatch(active_set_hash)):
        raise EvidenceError("precedent_report_active_set_invalid")
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot(),
                                "active_set_hash": active_set_hash}
        markdown = render_precedent_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("precedent_report_too_large")
        produced_by = f"kinase_precedents_report_{uuid.uuid4().hex}"
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


def saved_precedent_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored kinase precedent report from stored objects only (the linking is not run again)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("precedent_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("precedent_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("precedent_report_claims_invalid")
    index = claim_index(expected["claims"])
    for claim in report["claims"]:
        match_claim(expected["claims"], claim, index=index)
    for key, value in expected.items():
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"precedent_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            type(snapshot["budget"]) is not dict or
            (snapshot["active_set_hash"] is not None and (type(snapshot["active_set_hash"]) is not str or
                                                          not HEX64.fullmatch(snapshot["active_set_hash"])))):
        raise EvidenceError("precedent_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("precedent_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("precedent_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("precedent_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_precedent_report(report):
        raise EvidenceError("precedent_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
