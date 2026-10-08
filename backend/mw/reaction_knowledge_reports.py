"""Immutable, field-cited reports for ``reaction_knowledge@1`` (``method_report_manifest@1``,
``analysis_type: "reaction_knowledge"``, render ``reaction_knowledge_markdown@1``; spec M26 section 7).

The input is one ``link_reaction_knowledge`` result handle. Every claim cites that stored result
(``source_handle``) and is one of two evidence kinds, kept apart as in the M15/M20 reports:

- ``computed`` -- what ProtView counted again from the stored rows: the chain count, each chain's M-CSA / UniProt /
  reaction section status and the M-CSA ``coverage`` (status claims, no number), M-CSA rows by status (per chain
  and over the covered chains), distinct M-CSA entries, UniProt sites by type (per chain and overall), linked site
  positions by link status (per site and overall), distinct Rhea IDs in / not in the snapshot, each listed row's
  status, each Rhea ID's ``in_snapshot`` state, chain flags and the number of lines not listed (see below). A
  section that was not checked has a "검사하지 않음" status claim only and never a number (never 0).
- ``reference_value`` -- values copied verbatim from the snapshot rows: M-CSA entry ID, enzyme name,
  ``reference_uniprot_id``, EC numbers, role text (``roles_summary``, ``function_location_abv``, ``ptm``,
  ``roles[]``), the reference-structure flag, what M-CSA lists (PDB / chain / numbers / residue name), UniProt
  accession / entry / site type / positions / description / ligand, catalytic-activity reaction name and EC, Rhea ID
  and equation, and the processed file row counts of the set. Each carries "참조 스냅샷 값, 계산 아님", the set hash
  and the source date / license.

Each statement ID has exactly one evidence kind and one closed field-path rule; a claim citing a field of the other
kind is refused before any value is compared. Residue-level reference lines list ``matched`` and ``conflict`` rows
first, at most 200 lines per chain and section (M-CSA rows, UniProt sites, UniProt catalytic activities); the
remaining count is a computed claim and every row stays in the result object. Residues are named by their 7 identity
fields (nulls kept), never by a name.

Creating, reopening and downloading never re-run the linking: the stored result is re-checked with
``reaction_knowledge.validated_result``, its tool provenance, structure and numbering map are checked in this run,
every manifest field and claim is compared with the ones rebuilt from the stored rows, and the Markdown is compared
byte for byte with a re-render. The forbidden-word check runs on the fixed template with identifiers and reference
strings left as empty slots and skips only lines that equal RK1-RK5 exactly ("촉매" is not forbidden). The active
set at creation is recorded in the report snapshot only ("이전 스냅샷 기준" / "사용 중 스냅샷 없음").
"""
from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from typing import Any

from . import mutation_reports as mr
from . import reaction_knowledge as rk
from . import reaction_knowledge_constants as K
from .core.handles import canonical_json
from .reports import EvidenceError, _md, _provenance

ANALYSIS_TYPE = "reaction_knowledge"
RENDER_VERSION = "reaction_knowledge_markdown@1"
REPORT_BYTES = mr.REPORT_BYTES
REFERENCE_NOTE = mr.REFERENCE_NOTE
CLAIM_KEYS = mr.CLAIM_KEYS
LINE_CAP = 200   # residue-level reference lines per chain and section (the rest is counted, never dropped silently)
HEX64 = re.compile(K.HEX64_PATTERN + r"\Z")
MAP_TYPE = (rk.MAP_KIND, "residue_numbering_map@1")
FIXED_LIMITATIONS = frozenset(K.LIMITATIONS)
ROLE_FIELDS = ("group_function", "function_type", "function", "emo")
UNITS = {"processed_rows": "count", "start": "uniprot_sequence_position", "end": "uniprot_sequence_position",
         "resid": "mcsa_residue_number", "auth_resid": "mcsa_residue_number"}   # reference values that are numbers
EVIDENCE_STATEMENT = ("ProtView는 저장된 결과의 행·부위·연결 위치·Rhea ID 개수만 다시 셌다. M-CSA·UniProt·Rhea 값"
                      "(항목 ID·효소 이름·EC 번호·역할 문구·기준 구조 여부·M-CSA가 적은 PDB/체인/번호/잔기 이름·"
                      "accession·부위 종류·위치·설명·촉매 활동·Rhea 반응식)은 참조 스냅샷 값(참조 스냅샷 값, 계산 아님)이며 "
                      "ProtView가 계산하거나 판정한 것이 아니다. 보고서를 만들 때 연결을 다시 계산하지 않았다.")
PROCESSED_LABEL = "공개 서버에서 가져온 가공본"
LICENSE_LABEL = "CC BY 4.0"
SOURCE_LABELS = {"mcsa": "M-CSA", "uniprot_function": "UniProt", "rhea": "Rhea"}

# Fixed wording of every status / reason code (part of the template: checked for forbidden words).
STATUS_LABELS = {
    "checked": "검사함", "not_checked": "검사하지 않음", "not_available": "사용할 수 없음",
    "covered": "M-CSA가 이 체인을 다룸", "chain_not_listed": "이 체인은 M-CSA 행에 없음",
    "pdb_not_in_snapshot": "이 PDB ID는 스냅샷에 없음",
    "matched": "대응됨", "unmatched": "대응 없음", "conflict": "충돌",
    "numbering_map": "번호 대응으로 구조 잔기에 연결함", "numbering_map_not_given": "연결하지 않음: 번호 대응을 주지 않음",
    "chain_not_in_map": "연결하지 않음: 번호 대응에 이 체인이 없음",
    "map_accession_differs": "연결하지 않음: 번호 대응의 accession이 체인 accession과 다름",
    "accession_differs_from_mcsa": "체인 accession이 M-CSA 항목이 적은 accession과 다름",
}
REASON_LABELS = {
    "pdb_id_not_given": "PDB ID를 주지 않음", "accession_not_given": "accession을 주지 않음",
    "accession_not_in_snapshot": "스냅샷에 없는 accession", "accession_skipped_at_import": "가져올 때 건너뛴 accession",
    "no_source": "반응 정보를 준 출처가 없음",
    "non_standard_code": "M-CSA 잔기 이름이 표준 20종이 아님", "no_author_number": "M-CSA에 저자 번호가 없음",
    "residue_not_in_structure": "이 번호의 사슬 잔기가 구조에 없음",
    "ambiguous_residue_number": "같은 번호의 사슬 잔기가 여럿", "insertion_code_present": "구조 잔기에 삽입 코드가 있음",
    "residue_name_differs": "구조 잔기 이름이 M-CSA 잔기 이름과 다름", "mcsa_rows_disagree": "M-CSA 행끼리 잔기 이름이 다름",
}
LINK_LABELS = {"mapped": "번호 대응 행 있음", "not_in_map": "번호 대응에 없음"}
RHEA_LABELS = {True: "스냅샷에 있음", False: "스냅샷에 없음"}
SKIP_LABELS = {"obsolete": "폐기", "merged": "병합", "demerged": "분할", "not_found": "찾지 못함",
               "fetch_failed": "받지 못함"}
ACCESSION_SOURCE_LABELS = {"user": "사용자 입력", "numbering_map": "번호 대응에서 가져옴"}
NOT_GIVEN = "주지 않음"
UNCOVERED_ROWS = ("- 행: — (M-CSA가 이 체인을 다루지 않아 행이 없다. 검사하지 않은 부분처럼 다루며 행 개수를 세지 "
                  "않았다.)")
NOT_CHECKED_ROWS = "- 행: — (검사하지 않음. 행 개수를 세지 않았다.)"

EVIDENCE_KINDS = ("computed", "reference_value")
_C = r"chains\[\d+\]"
# statement ID -> (evidence kind, field path rule); fixed template, nothing else carries a number in this report.
STATEMENTS: dict[str, tuple[str, re.Pattern[str]]] = {
    "chain_count": ("computed", re.compile(r"chains\[\*\]")),
    "chain_flag": ("computed", re.compile(_C + r"\.flags\[\d+\]")),
    "mcsa_status": ("computed", re.compile(_C + r"\.mcsa\.status")),
    "mcsa_coverage": ("computed", re.compile(_C + r"\.mcsa\.coverage")),
    "mcsa_row_count": ("computed", re.compile(_C + r"\.mcsa\.rows\[\*\]\.status")),
    "mcsa_row_status": ("computed", re.compile(_C + r"\.mcsa\.rows\[\d+\]\.status")),
    "total_mcsa_row_count": ("computed", re.compile(r"chains\[\*\]\.mcsa\.rows\[\*\]\.status")),
    "mcsa_entry_count": ("computed", re.compile(r"chains\[\*\]\.mcsa\.entries\[\*\]\.mcsa_id")),
    "uniprot_status": ("computed", re.compile(_C + r"\.uniprot\.status")),
    "uniprot_link_state": ("computed", re.compile(_C + r"\.uniprot\.(linked_via|link_reason)")),
    "uniprot_feature_count": ("computed", re.compile(_C + r"\.uniprot\.features\[\*\]\.type")),
    "total_uniprot_feature_count": ("computed", re.compile(r"chains\[\*\]\.uniprot\.features\[\*\]\.type")),
    "feature_link_count": ("computed", re.compile(_C + r"\.uniprot\.features\[\d+\]\.links\[\*\]\.status")),
    "total_linked_position_count": ("computed", re.compile(
        r"chains\[\*\]\.uniprot\.features\[\*\]\.links\[\*\]\.status")),
    "reactions_status": ("computed", re.compile(_C + r"\.reactions\.status")),
    "rhea_link_state": ("computed", re.compile(
        _C + r"\.reactions\.uniprot_activities\[\d+\]\.rhea\[\d+\]\.in_snapshot")),
    "total_rhea_count": ("computed", re.compile(
        r"chains\[\*\]\.reactions\.uniprot_activities\[\*\]\.rhea\[\*\]\.in_snapshot")),
    "unlisted_line_count": ("computed", re.compile(
        _C + r"\.(mcsa\.rows|uniprot\.features|reactions\.uniprot_activities)\[\*\]")),
    "reference_snapshot_rows": ("reference_value", re.compile(r"snapshot_set\.sources\[\d+\]\.files\[\d+\]\.rows")),
    "reference_mcsa_entry": ("reference_value", re.compile(
        _C + r"\.mcsa\.entries\[\d+\]\.(mcsa_id|enzyme_name|reference_uniprot_id)")),
    "reference_ec_number": ("reference_value", re.compile(
        _C + r"\.(mcsa\.entries\[\d+\]\.all_ecs\[\d+\]|reactions\.ecs\.(mcsa|uniprot)\[\d+\]|"
        r"reactions\.uniprot_activities\[\d+\]\.ec_number)")),
    "reference_mcsa_row": ("reference_value", re.compile(
        _C + r"\.mcsa\.rows\[\d+\]\.(mcsa_id|is_reference|listed\.(pdb_id|chain_name|resid|auth_resid|code))")),
    "reference_mcsa_role": ("reference_value", re.compile(
        _C + r"\.mcsa\.rows\[\d+\]\.reference\.(roles_summary|function_location_abv|ptm|"
        r"roles\[\d+\]\.(group_function|function_type|function|emo))")),
    "reference_uniprot_entry": ("reference_value", re.compile(
        _C + r"\.uniprot\.entry\.(accession|entry_name|protein_name|organism)")),
    "reference_uniprot_site": ("reference_value", re.compile(
        _C + r"\.uniprot\.features\[\d+\]\.(type|start|end|description|ligand_name|ligand_id)")),
    "reference_uniprot_activity": ("reference_value", re.compile(
        _C + r"\.reactions\.uniprot_activities\[\d+\]\.reaction_name")),
    "reference_rhea_id": ("reference_value", re.compile(
        _C + r"\.reactions\.uniprot_activities\[\d+\]\.rhea\[\d+\]\.rhea_id")),
    "reference_rhea_equation": ("reference_value", re.compile(r"reference_rows\.rhea\[\d+\]\.equation")),
}
STATEMENT_IDS = tuple(STATEMENTS)
COMPUTED_FIELDS = re.compile("|".join(f"(?:{rule.pattern})" for kind, rule in STATEMENTS.values()
                                      if kind == "computed"))
REFERENCE_FIELDS = re.compile("|".join(f"(?:{rule.pattern})" for kind, rule in STATEMENTS.values()
                                       if kind == "reference_value"))
# The M15 and M20 interpretive lists (with their English counterparts) plus the M26 words (spec 7). "촉매" is not
# listed. Handles are lowercase hex, identifiers and reference strings are slots, so none of them is checked.
INTERPRETIVE = re.compile(
    mr.INTERPRETIVE.pattern + r"|필수|핵심|중요|메커니즘이\s*유지|"
    r"mechanism\W+(?:is\W+)?(?:preserved|maintained|retained|conserved)", re.IGNORECASE)
SNAPSHOT_KEYS = {"event_seq", "time_utc", "run_egress_mode", "budget", "active_set_hash"}
COPIED_FIELDS = ("method_version", "structure", "pdb_id", "numbering_map", "snapshot_set", "chains", "counts",
                 "null_result", "limitations")
MANIFEST_KEYS = frozenset({
    "schema", "analysis_type", "status", "render_version", "generation_mode", "result_handle", "result_schema",
    "result_sha256", *COPIED_FIELDS, "claims", "provenance", "evidence_statement", "snapshot", "markdown_handle"})


# ---------------------------------------------------------------------------------------------------------------
# rendering of one value

def _render(value: Any, rounding: str) -> str:
    if rounding == "integer":
        if type(value) is not int:
            raise EvidenceError("reaction_claim_integer_expected")
        return str(value)
    if rounding == "status":
        if type(value) is not str or value not in STATUS_LABELS:
            raise EvidenceError("reaction_claim_value_type")
        return f"{STATUS_LABELS[value]} ({value})"
    if rounding == "in_snapshot":
        if type(value) is not bool:
            raise EvidenceError("reaction_claim_value_type")
        return f"{RHEA_LABELS[value]} ({'true' if value else 'false'})"
    if rounding == "verbatim":
        if type(value) is bool:
            return "true" if value else "false"
        if type(value) not in (int, str):
            raise EvidenceError("reaction_claim_value_type")
        return str(value)
    raise EvidenceError("reaction_claim_rounding")


def check_no_interpretation(text: str) -> str:
    """Refuse interpretive wording on any line that is not exactly one of the fixed limitation sentences RK1-RK5."""
    for line in text.split("\n"):
        if line in FIXED_LIMITATIONS:
            continue
        match = INTERPRETIVE.search(line)
        if match is not None:
            raise EvidenceError(f"reaction_report_interpretive_statement: {match.group(0)}")
    return text


def identity(residue: dict[str, Any] | None) -> str:
    """Markdown text of the 7 identity fields of a residue, nulls kept and each field escaped (never a name alone)."""
    if residue is None:
        return "구조 잔기 없음 (null)"

    def text(value: Any) -> str:
        return "null" if value is None else _md(value)

    return (f"{text(residue['resname'])} auth {text(residue['chain_auth'])}/{text(residue['seq_auth'])} icode "
            f"\"{text(residue['icode'])}\" label {text(residue['chain_label'])}/{text(residue['seq_label'])} model "
            f"{text(residue['model_number'])}")


# ---------------------------------------------------------------------------------------------------------------
# source validation (stored objects of this run only; the linking is never run again)

def validated_reaction_result(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve a stored result produced by the tool in this run; (content, provenance)."""
    try:
        own = f"obj://{run.run_id}/"
        if type(handle) is not str or not handle.startswith(own):
            raise EvidenceError("reaction_result_other_run")
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) != (K.KIND, K.SCHEMA):
            raise EvidenceError("wrong_result_kind")
        try:
            content = rk.validated_result(run.store.load(handle))
        except (rk.ResultInvalid, RecursionError) as exc:
            raise EvidenceError(f"reaction_result_invalid: {exc}") from exc
        provenance = _provenance(list(run.events.read()), handle, expected_tool=K.TOOL)
        structure = content["structure"]
        if (not structure["handle"].startswith(own) or
                run.store.meta(structure["handle"])["kind"] != structure["structure_kind"]):
            raise EvidenceError("reaction_structure_link_mismatch")
        numbering_map = content["numbering_map"]
        if numbering_map is not None:
            map_meta = run.store.meta(numbering_map["handle"])
            if (map_meta["kind"], map_meta["schema"]) != MAP_TYPE:
                raise EvidenceError("reaction_numbering_map_kind")
            map_content = run.store.load(numbering_map["handle"])
            if map_content["structure"]["handle"] != structure["handle"]:
                raise EvidenceError("reaction_numbering_map_structure_mismatch")
            if map_content["pdb_id"] != numbering_map["pdb_id"]:
                raise EvidenceError("reaction_numbering_map_pdb_mismatch")
        return content, provenance
    except EvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError, RecursionError) as exc:
        raise EvidenceError("reaction_evidence_unresolved") from exc


# ---------------------------------------------------------------------------------------------------------------
# claims

def _sha(index: int, item: Any) -> str:
    return hashlib.sha256(canonical_json({"index": index, "row": item})).hexdigest()


def _reference(snapshot_set: dict[str, Any], sources: tuple[str, ...]) -> dict[str, Any]:
    by_name = {item["source"]: item for item in snapshot_set["sources"]}
    return {"note": REFERENCE_NOTE, "set_hash": snapshot_set["set_hash"],
            "sources": [{key: by_name[name][key] for key in ("source", "date", "license")} for name in sources]}


def listed(items: list[Any], first: Callable[[Any], bool] | None = None) -> tuple[list[tuple[int, Any]], int]:
    """(index, item) pairs listed in the report (``first`` items first, stored order kept) and the unlisted count."""
    pairs = list(enumerate(items))
    if first is not None:
        pairs = [p for p in pairs if first(p[1])] + [p for p in pairs if not first(p[1])]
    return pairs[:LINE_CAP], max(0, len(pairs) - LINE_CAP)


def _row_first(row: dict[str, Any]) -> bool:
    return row["status"] in ("matched", "conflict")


def claims_for(handle: str, content: dict[str, Any]) -> list[dict[str, Any]]:
    """Every value statement of the report; each count is recounted from the stored rows (never copied)."""
    snapshot_set = content["snapshot_set"]
    base_subject = {"result_handle": handle, "structure_handle": content["structure"]["handle"]}
    claims: list[dict[str, Any]] = []

    def add(statement: str, path: str, selector: dict[str, Any] | None, quantity: str, unit: str, value: Any,
            rounding: str, operation: str | None = None, sources: tuple[str, ...] | None = None,
            subject: dict[str, Any] | None = None) -> None:
        kind = STATEMENTS[statement][0]
        if (kind == "reference_value") is (sources is None):
            raise EvidenceError("reaction_claim_kind_rule")   # programming guard: reference claims name a source
        claims.append({"statement_id": statement, "evidence_kind": kind, "source_handle": handle,
                       "source_kind": K.KIND, "source_schema": K.SCHEMA, "source_sha256": handle.rsplit("/", 1)[-1],
                       "field_path": path, "row_selector": selector, "subject": {**base_subject, **(subject or {})},
                       "quantity": quantity, "unit": unit, "exact_value": value,
                       "rendered_value": _render(value, rounding), "rounding": rounding, "operation": operation,
                       "reference": None if sources is None else _reference(snapshot_set, sources)})

    def ref(statement: str, path: str, selector: dict[str, Any], quantity: str, value: Any, sources: tuple[str, ...],
            subject: dict[str, Any] | None = None) -> None:
        unit = UNITS.get(quantity) or {str: "text", bool: "flag"}.get(type(value), "identifier")
        add(statement, path, selector, quantity, unit, value, "verbatim", None, sources, subject)

    chains = content["chains"]
    add("chain_count", "chains[*]", None, "chains", "count", len(chains), "integer", "count(chains)")
    for si, source in enumerate(snapshot_set["sources"]):
        for fi, record in enumerate(source["files"]):
            ref("reference_snapshot_rows", f"snapshot_set.sources[{si}].files[{fi}].rows",
                {"source": source["source"], "file": record["name"]}, "processed_rows", record["rows"],
                (source["source"],))
    covered = [c for c in chains if c["mcsa"]["coverage"] == K.COVERED]
    if covered:
        for status in K.ROW_STATUSES:
            add("total_mcsa_row_count", "chains[*].mcsa.rows[*].status", {"status": status}, f"{status}_rows",
                "count", sum(r["status"] == status for c in covered for r in c["mcsa"]["rows"]), "integer",
                f"count_where(status == {status}; rows of covered chains)")
        add("mcsa_entry_count", "chains[*].mcsa.entries[*].mcsa_id", None, "distinct_mcsa_entries", "count",
            len({e["mcsa_id"] for c in covered for e in c["mcsa"]["entries"]}), "integer",
            "count_distinct(mcsa_id; entries of covered chains)")
    checked = [c for c in chains if c["uniprot"]["status"] == K.CHECKED]
    if checked:
        for site_type in K.SITE_TYPES:
            add("total_uniprot_feature_count", "chains[*].uniprot.features[*].type", {"type": site_type},
                "uniprot_sites", "count",
                sum(f["type"] == site_type for c in checked for f in c["uniprot"]["features"]), "integer",
                "count_where(type; sites of checked chains)")
    linked_sites = [f for c in checked for f in c["uniprot"]["features"] if f["links"] is not None]
    if linked_sites:
        for status in K.LINK_STATUSES:
            add("total_linked_position_count", "chains[*].uniprot.features[*].links[*].status", {"status": status},
                f"{status}_positions", "count",
                sum(link["status"] == status for f in linked_sites for link in f["links"]), "integer",
                f"count_where(status == {status}; links of linked sites)")
    with_activities = [c for c in chains if c["reactions"]["uniprot_activities"] is not None]
    if with_activities:
        rhea = {link["rhea_id"]: link["in_snapshot"] for c in with_activities
                for activity in c["reactions"]["uniprot_activities"] for link in activity["rhea"]}
        for flag in (True, False):
            add("total_rhea_count", "chains[*].reactions.uniprot_activities[*].rhea[*].in_snapshot",
                {"in_snapshot": flag}, "distinct_rhea_ids", "count", sum(v is flag for v in rhea.values()), "integer",
                f"count_distinct(rhea_id; in_snapshot == {'true' if flag else 'false'})")
    for ci, chain in enumerate(chains):
        prefix, sel = f"chains[{ci}]", {"chain_auth": chain["chain_auth"]}
        for k, flag in enumerate(chain["flags"]):
            add("chain_flag", f"{prefix}.flags[{k}]", {**sel, "flag": flag}, "chain_flag", "status", flag, "status")
        _mcsa_claims(add, ref, prefix, sel, chain["mcsa"])
        _uniprot_claims(add, ref, prefix, sel, chain["uniprot"])
        _reaction_claims(add, ref, prefix, sel, chain["reactions"])
    for k, row in enumerate(content["reference_rows"]["rhea"]):
        ref("reference_rhea_equation", f"reference_rows.rhea[{k}].equation", {"rhea_id": row["rhea_id"]},
            "rhea_equation", row["equation"], ("rhea",))
    return claims


def _mcsa_claims(add: Callable, ref: Callable, prefix: str, sel: dict[str, Any], mcsa: dict[str, Any]) -> None:
    add("mcsa_status", f"{prefix}.mcsa.status", sel, "mcsa_status", "status", mcsa["status"], "status")
    if mcsa["status"] != K.CHECKED:
        return   # not checked: the status claim only, no number
    add("mcsa_coverage", f"{prefix}.mcsa.coverage", sel, "mcsa_coverage", "status", mcsa["coverage"], "status")
    if mcsa["coverage"] != K.COVERED:
        return   # rows / entries / counts are null: no number
    for status in K.ROW_STATUSES:
        add("mcsa_row_count", f"{prefix}.mcsa.rows[*].status", {**sel, "status": status}, f"{status}_rows", "count",
            sum(r["status"] == status for r in mcsa["rows"]), "integer",
            f"count_where(status == {status}; rows of this chain)")
    for ei, entry in enumerate(mcsa["entries"]):
        esel = {**sel, "mcsa_id": entry["mcsa_id"]}
        for field in ("mcsa_id", "enzyme_name", "reference_uniprot_id"):
            ref("reference_mcsa_entry", f"{prefix}.mcsa.entries[{ei}].{field}", esel, field, entry[field], ("mcsa",))
        for k, ec in enumerate(entry["all_ecs"]):
            ref("reference_ec_number", f"{prefix}.mcsa.entries[{ei}].all_ecs[{k}]", esel, "ec_number", ec, ("mcsa",))
    rows, unlisted = listed(mcsa["rows"], _row_first)
    for ri, row in rows:
        rsel = {**sel, "row_index": ri, "row_sha256": _sha(ri, row)}
        residue = {"residue": row["residue"]}
        path = f"{prefix}.mcsa.rows[{ri}]"
        add("mcsa_row_status", f"{path}.status", rsel, "row_status", "status", row["status"], "status",
            subject=residue)
        ref("reference_mcsa_row", f"{path}.mcsa_id", rsel, "mcsa_id", row["mcsa_id"], ("mcsa",), residue)
        ref("reference_mcsa_row", f"{path}.is_reference", rsel, "is_reference", row["is_reference"], ("mcsa",),
            residue)
        for field in ("pdb_id", "chain_name", "resid", "auth_resid", "code"):
            if row["listed"][field] is not None:
                ref("reference_mcsa_row", f"{path}.listed.{field}", rsel, field, row["listed"][field], ("mcsa",),
                    residue)
        text = row["reference"]
        for field in ("roles_summary", "function_location_abv", "ptm"):
            ref("reference_mcsa_role", f"{path}.reference.{field}", rsel, field, text[field], ("mcsa",), residue)
        for k, role in enumerate(text["roles"] or []):
            for field in ROLE_FIELDS:
                ref("reference_mcsa_role", f"{path}.reference.roles[{k}].{field}", rsel, f"role_{field}",
                    role[field], ("mcsa",), residue)
    if unlisted:
        add("unlisted_line_count", f"{prefix}.mcsa.rows[*]", {**sel, "section": "mcsa"}, "unlisted_rows", "count",
            unlisted, "integer", f"count(rows after the first {LINE_CAP} listed; matched and conflict first)")


def _uniprot_claims(add: Callable, ref: Callable, prefix: str, sel: dict[str, Any], uniprot: dict[str, Any]) -> None:
    add("uniprot_status", f"{prefix}.uniprot.status", sel, "uniprot_status", "status", uniprot["status"], "status")
    if uniprot["status"] != K.CHECKED:
        return
    for field in ("accession", "entry_name", "protein_name", "organism"):
        if uniprot["entry"][field] is not None:
            ref("reference_uniprot_entry", f"{prefix}.uniprot.entry.{field}", sel, field, uniprot["entry"][field],
                ("uniprot_function",))
    field = "linked_via" if uniprot["linked_via"] is not None else "link_reason"
    add("uniprot_link_state", f"{prefix}.uniprot.{field}", sel, "uniprot_link_state", "status", uniprot[field],
        "status")
    for site_type in K.SITE_TYPES:
        add("uniprot_feature_count", f"{prefix}.uniprot.features[*].type", {**sel, "type": site_type},
            "uniprot_sites", "count", sum(f["type"] == site_type for f in uniprot["features"]), "integer",
            "count_where(type; sites of this chain)")
    features, unlisted = listed(uniprot["features"])
    for fi, feature in features:
        fsel = {**sel, "feature_index": fi, "feature_sha256": _sha(fi, feature)}
        for field in ("type", "start", "end", "description", "ligand_name", "ligand_id"):
            if feature[field] is not None:
                ref("reference_uniprot_site", f"{prefix}.uniprot.features[{fi}].{field}", fsel, field,
                    feature[field], ("uniprot_function",))
        if feature["links"] is not None:
            for status in K.LINK_STATUSES:
                add("feature_link_count", f"{prefix}.uniprot.features[{fi}].links[*].status",
                    {**fsel, "status": status}, f"{status}_positions", "count",
                    sum(link["status"] == status for link in feature["links"]), "integer",
                    f"count_where(status == {status}; links of this site)")
    if unlisted:
        add("unlisted_line_count", f"{prefix}.uniprot.features[*]", {**sel, "section": "uniprot"}, "unlisted_sites",
            "count", unlisted, "integer", f"count(sites after the first {LINE_CAP} listed)")


def _reaction_claims(add: Callable, ref: Callable, prefix: str, sel: dict[str, Any],
                     reactions: dict[str, Any]) -> None:
    add("reactions_status", f"{prefix}.reactions.status", sel, "reactions_status", "status", reactions["status"],
        "status")
    if reactions["status"] != K.CHECKED:
        return
    for source, origin in (("mcsa", "mcsa"), ("uniprot", "uniprot_function")):
        for k, ec in enumerate(reactions["ecs"][source] or []):
            ref("reference_ec_number", f"{prefix}.reactions.ecs.{source}[{k}]", {**sel, "source": source},
                "ec_number", ec, (origin,))
    if reactions["uniprot_activities"] is None:
        return
    activities, unlisted = listed(reactions["uniprot_activities"])
    for ai, activity in activities:
        asel = {**sel, "activity_index": ai, "activity_sha256": _sha(ai, activity)}
        path = f"{prefix}.reactions.uniprot_activities[{ai}]"
        ref("reference_uniprot_activity", f"{path}.reaction_name", asel, "reaction_name", activity["reaction_name"],
            ("uniprot_function",))
        if activity["ec_number"] is not None:
            ref("reference_ec_number", f"{path}.ec_number", asel, "ec_number", activity["ec_number"],
                ("uniprot_function",))
        for bi, link in enumerate(activity["rhea"]):
            ref("reference_rhea_id", f"{path}.rhea[{bi}].rhea_id", asel, "rhea_id", link["rhea_id"],
                ("uniprot_function",))
            add("rhea_link_state", f"{path}.rhea[{bi}].in_snapshot", asel, "rhea_in_snapshot", "status",
                link["in_snapshot"], "in_snapshot")
    if unlisted:
        add("unlisted_line_count", f"{prefix}.reactions.uniprot_activities[*]", {**sel, "section": "reactions"},
            "unlisted_activities", "count", unlisted, "integer", f"count(activities after the first {LINE_CAP} listed)")


def _key(claim: dict[str, Any]) -> tuple[str, str, bytes]:
    return claim["statement_id"], claim["field_path"], canonical_json(claim["row_selector"])


def claim_index(expected_claims: list[dict[str, Any]]) -> tuple[dict[tuple[str, str, bytes], dict[str, Any]], set]:
    """(claims by key, source handles) of the expected claims, built once per reopen."""
    return {_key(claim): claim for claim in expected_claims}, {claim["source_handle"] for claim in expected_claims}


def match_claim(expected_claims: list[dict[str, Any]], proposed: Any, *, index: tuple | None = None) -> dict[str, Any]:
    """Accept a claim only if its kind, field rule, source and every value equal the claim built from that field."""
    by_key, handles = index if index is not None else claim_index(expected_claims)
    if type(proposed) is not dict or set(proposed) != CLAIM_KEYS:
        raise EvidenceError("reaction_claim_shape")
    statement = proposed["statement_id"]
    if statement not in STATEMENTS:
        raise EvidenceError("reaction_claim_statement_not_allowed")
    kind, rule = STATEMENTS[statement]
    if proposed["evidence_kind"] not in EVIDENCE_KINDS or proposed["evidence_kind"] != kind:
        raise EvidenceError("reaction_claim_evidence_kind_mismatch")
    path = proposed["field_path"]
    if type(path) is not str:
        raise EvidenceError("reaction_claim_shape")
    if kind == "computed":
        if REFERENCE_FIELDS.fullmatch(path):
            raise EvidenceError("reaction_claim_reference_field_as_computed")
        if not rule.fullmatch(path) or proposed["reference"] is not None:
            raise EvidenceError("reaction_claim_computed_field_rule")
    else:
        if COMPUTED_FIELDS.fullmatch(path):
            raise EvidenceError("reaction_claim_computed_field_as_reference")
        reference = proposed["reference"]
        if not rule.fullmatch(path) or type(reference) is not dict or reference.get("note") != REFERENCE_NOTE:
            raise EvidenceError("reaction_claim_reference_field_rule")
    if (proposed["source_kind"], proposed["source_schema"]) != (K.KIND, K.SCHEMA):
        raise EvidenceError("reaction_claim_source_kind_mismatch")
    if proposed["source_handle"] not in handles or \
            proposed["source_sha256"] != str(proposed["source_handle"]).rsplit("/", 1)[-1]:
        raise EvidenceError("reaction_claim_source_mismatch")
    try:
        match = by_key.get(_key(proposed))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("reaction_claim_shape") from exc
    if match is None:
        raise EvidenceError("reaction_claim_field_not_allowed")
    if canonical_json(match) != canonical_json(proposed):
        raise EvidenceError("reaction_claim_binding_mismatch")
    return proposed


def validate_reaction_claim(run: Any, result_handle: str, proposed: dict[str, Any]) -> dict[str, Any]:
    return match_claim(_expected(run, result_handle)["claims"], proposed)


# ---------------------------------------------------------------------------------------------------------------
# manifest, Markdown, build and saved read

def _expected(run: Any, handle: str) -> dict[str, Any]:
    """Every manifest field that follows from the validated stored result (not snapshot / markdown handle)."""
    content, provenance = validated_reaction_result(run, handle)
    try:
        return {"schema": "method_report_manifest@1", "analysis_type": ANALYSIS_TYPE, "status": "complete",
                "render_version": RENDER_VERSION, "generation_mode": "local_rules_no_egress", "result_handle": handle,
                "result_schema": K.SCHEMA, "result_sha256": handle.rsplit("/", 1)[-1],
                **{key: content[key] for key in COPIED_FIELDS},
                "claims": claims_for(handle, content),
                "provenance": {key: provenance[key] for key in ("call_id", "tool", "tool_version",
                                                                "created_event_seq", "completed_event_seq")},
                "evidence_statement": EVIDENCE_STATEMENT}
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise EvidenceError("reaction_report_evidence_unresolved") from exc


_SLOT = re.compile("\x00(\\d+)\x00")


class _Template:
    """The fixed template lines plus slots; every value comes from a bound claim of the manifest.

    ``value`` (counts, status wording) is template text and is checked for forbidden words; ``slot`` / ``ref``
    (identifiers and reference strings) are left empty for that check and filled afterwards.
    """

    def __init__(self, claims: list[dict[str, Any]]) -> None:
        self.index: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        for claim in claims:
            self.index.setdefault((claim["statement_id"], claim["field_path"]), []).append(claim)
            self.index.setdefault((claim["statement_id"], None), []).append(claim)
        self.slots: list[str] = []
        self.lines: list[str] = []

    def slot(self, text: Any, *, escaped: bool = False) -> str:
        self.slots.append(text if escaped else _md(text))
        return f"\x00{len(self.slots) - 1}\x00"

    def find(self, statement: str, path: str | None, **selector: Any) -> dict[str, Any]:
        """The one claim of ``statement`` at ``path`` (any path when None) whose selector holds ``selector``."""
        found = [c for c in self.index.get((statement, path), [])
                 if all((c["row_selector"] or {}).get(k) == v for k, v in selector.items())]
        if len(found) != 1:
            raise EvidenceError("reaction_report_claim_missing")
        return found[0]

    def value(self, statement: str, path: str | None, **selector: Any) -> str:
        return _md(self.find(statement, path, **selector)["rendered_value"])

    def ref(self, statement: str, path: str | None, **selector: Any) -> str:
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
        return "사용 중 스냅샷 없음: 보고서를 만들 때 사용할 수 있는 반응 참조 세트가 없었다."
    if active != set_hash:
        return "이전 스냅샷 기준: 결과의 세트가 보고서를 만들 때 사용 중이던 세트와 다르다. 결과를 다시 계산하지 않았다."
    return "결과의 세트가 보고서를 만들 때 사용 중이던 세트와 같다."


def render_reaction_report(manifest: dict[str, Any]) -> str:
    """Markdown from the manifest only; every value is the rendered text of a bound claim."""
    t = _Template(manifest["claims"])
    structure, snapshot_set, snapshot = manifest["structure"], manifest["snapshot_set"], manifest["snapshot"]
    numbering_map, active, counts = manifest["numbering_map"], snapshot["active_set_hash"], manifest["counts"]
    pdb_id = t.slot(manifest["pdb_id"]) if manifest["pdb_id"] is not None else f"{NOT_GIVEN} (null)"
    if numbering_map is None:
        given_map = f"{NOT_GIVEN} (null)"
    else:
        map_pdb = t.slot(numbering_map["pdb_id"]) if numbering_map["pdb_id"] is not None else "null"
        given_map = f"{t.slot(numbering_map['handle'])} (PDB ID {map_pdb})"
    t.lines.extend([
        "# 효소 반응 지식 보고서 (reaction knowledge)", "", "Status: complete", "",
        f"Result: {t.slot(manifest['result_handle'])}",
        (f"Structure: {t.slot(structure['handle'])} ({t.slot(structure['structure_kind'])}, "
         f"model {t.slot(structure['model_number'])})"),
        f"Method: {t.slot(manifest['method_version'])}", "",
        f"- 요청한 PDB ID: {pdb_id}", f"- 번호 대응: {given_map}", "",
        f"**{_md(manifest['evidence_statement'])}**", "", "## 참조 스냅샷", "", K.STATEMENTS["RK6"], "",
        "| 출처 | 날짜 | 세트 해시 | 가공 행 수 | 라이선스 | 가공 |", "| --- | --- | --- | ---: | --- | --- |"])
    for si, source in enumerate(snapshot_set["sources"]):
        for fi, record in enumerate(source["files"]):
            rows = t.ref("reference_snapshot_rows", f"snapshot_set.sources[{si}].files[{fi}].rows")
            t.lines.append(f"| {t.slot(SOURCE_LABELS[source['source']])} | {t.slot(source['date'])} | "
                           f"{t.slot(snapshot_set['set_hash'])} | {rows} | "
                           f"{LICENSE_LABEL} ({t.slot(source['license'])}) | {PROCESSED_LABEL} |")
    t.lines.extend([
        "", (f"- 가져온 시각: {t.slot(snapshot_set['imported_at'])} (importer {t.slot(snapshot_set['importer_version'])}"
             f", {t.slot(K.ORIGIN)})"),
        f"- 보고서를 만들 때 사용 중이던 반응 참조 세트: {t.slot(active) if active is not None else '없음 (null)'}",
        f"- {_basis(active, snapshot_set['set_hash'])}", "", "## 전체 개수 (ProtView 계산: 저장된 행의 개수)", "",
        f"- 체인 수: {t.value('chain_count', 'chains[*]')}"])
    if counts["mcsa_rows"] is not None:
        path = "chains[*].mcsa.rows[*].status"
        rows = "; ".join(f"{STATUS_LABELS[s]} ({_md(s)}) {t.value('total_mcsa_row_count', path, status=s)}"
                         for s in K.ROW_STATUSES)
        t.lines.extend([f"- M-CSA 행 (M-CSA가 다룬 체인 전체): {rows}",
                        f"- 서로 다른 M-CSA 항목: {t.value('mcsa_entry_count', 'chains[*].mcsa.entries[*].mcsa_id')}"])
    else:
        t.lines.append("- M-CSA 행·항목: 검사하지 않음 (M-CSA가 다룬 체인이 없어 행 개수를 세지 않았다.)")
    if counts["uniprot_features"] is not None:
        path = "chains[*].uniprot.features[*].type"
        sites = "; ".join(f"{t.slot(s)} {t.value('total_uniprot_feature_count', path, type=s)}" for s in K.SITE_TYPES)
        t.lines.append(f"- UniProt 부위 (검사한 체인 전체): {sites}")
    else:
        t.lines.append("- UniProt 부위: 검사하지 않음 (UniProt 절을 검사한 체인이 없다.)")
    if counts["linked_positions"] is not None:
        path = "chains[*].uniprot.features[*].links[*].status"
        links = "; ".join(f"{LINK_LABELS[s]} ({_md(s)}) {t.value('total_linked_position_count', path, status=s)}"
                          for s in K.LINK_STATUSES)
        t.lines.append(f"- 구조에 연결한 부위 위치: {links}")
    else:
        t.lines.append("- 구조에 연결한 부위 위치: 계산하지 않음 (번호 대응으로 연결한 부위가 없다.)")
    if counts["rhea"] is not None:
        path = "chains[*].reactions.uniprot_activities[*].rhea[*].in_snapshot"
        rhea = "; ".join(f"{RHEA_LABELS[flag]} {t.value('total_rhea_count', path, in_snapshot=flag)}"
                         for flag in (True, False))
        t.lines.append(f"- 서로 다른 Rhea ID: {rhea}")
    else:
        t.lines.append("- Rhea ID: 계산하지 않음 (UniProt 촉매 활동을 가진 체인이 없다.)")
    if manifest["null_result"]:
        t.lines.append("- 이 결과는 유효한 빈 결과(scientific\\_null)이며 실패가 아니다.")
    for ci, chain in enumerate(manifest["chains"]):
        _render_chain(t, f"chains[{ci}]", chain)
    t.lines.extend(["", "## Limitations", ""])
    for item in manifest["limitations"]:
        t.lines.extend([item, ""])
    t.lines.extend([("Exact values, evidence kinds and field paths are in the JSON download "
                     f"({len(manifest['claims'])} claims). Every row, site, link and M-CSA reaction compound is in "
                     "the stored result."), ""])
    return t.text()


def _render_chain(t: _Template, prefix: str, chain: dict[str, Any]) -> None:
    source = chain["accession_source"]
    accession = (f"{t.slot(chain['accession'])} (출처: {ACCESSION_SOURCE_LABELS[source]} ({_md(source)}))"
                 if chain["accession"] is not None else f"{NOT_GIVEN} (null)")
    t.lines.extend(["", f"## 체인 {t.slot(chain['chain_auth'])}", "", f"- 체인 accession: {accession}"])
    for k in range(len(chain["flags"])):
        t.lines.append(f"- 표시 (ProtView 계산): {t.value('chain_flag', f'{prefix}.flags[{k}]')}")
    mcsa = chain["mcsa"]
    t.lines.extend(["", "### M-CSA", "", f"- 상태: {t.value('mcsa_status', f'{prefix}.mcsa.status')}"])
    if mcsa["status"] != K.CHECKED:
        t.lines.extend([f"- 이유: {REASON_LABELS[mcsa['reason']]} ({_md(mcsa['reason'])})", NOT_CHECKED_ROWS])
    else:
        t.lines.append(f"- 범위: {t.value('mcsa_coverage', f'{prefix}.mcsa.coverage')}")
        if mcsa["coverage"] != K.COVERED:
            t.lines.append(UNCOVERED_ROWS)
        else:
            _render_mcsa_rows(t, prefix, mcsa)
    _render_uniprot(t, prefix, chain["uniprot"])
    _render_reactions(t, prefix, chain["reactions"])


def _render_mcsa_rows(t: _Template, prefix: str, mcsa: dict[str, Any]) -> None:
    path = f"{prefix}.mcsa.rows[*].status"
    counts = "; ".join(f"{STATUS_LABELS[s]} ({_md(s)}) {t.value('mcsa_row_count', path, status=s)}"
                       for s in K.ROW_STATUSES)
    t.lines.extend([f"- 행 수 (ProtView 계산): {counts}", f"- M-CSA 항목 ({REFERENCE_NOTE}):"])
    for ei, entry in enumerate(mcsa["entries"]):
        path = f"{prefix}.mcsa.entries[{ei}]"
        ecs = ", ".join(t.ref("reference_ec_number", f"{path}.all_ecs[{k}]") for k in range(len(entry["all_ecs"])))
        t.lines.append(f"  - M-CSA {t.ref('reference_mcsa_entry', f'{path}.mcsa_id')}: "
                       f"{t.ref('reference_mcsa_entry', f'{path}.enzyme_name')}; reference\\_uniprot\\_id "
                       f"{t.ref('reference_mcsa_entry', f'{path}.reference_uniprot_id')}; EC {ecs or '빈 목록 ([])'}")
    rows, unlisted = listed(mcsa["rows"], _row_first)
    t.lines.extend([
        "", (f"잔기 행: 대응됨·충돌 행을 먼저, 이 체인에서 최대 {LINE_CAP}줄. 잔기는 7필드로 식별한다. M-CSA가 적은 값과 "
             f"역할 문구는 M-CSA 원문({REFERENCE_NOTE})이다."), "",
        ("| 상태 (ProtView 계산) | 이유 | M-CSA 항목 | 잔기 순번 (residue\\_index) | 구조 잔기 (7필드) | "
         "M-CSA가 적은 PDB·체인·번호·잔기 이름 | 기준 구조 (is\\_reference) | 역할 문구 (M-CSA 원문) |"),
        "| --- | --- | --- | ---: | --- | --- | --- | --- |"])
    for ri, row in rows:
        path = f"{prefix}.mcsa.rows[{ri}]"
        reason = f"{REASON_LABELS[row['reason']]} ({_md(row['reason'])})" if row["reason"] is not None else "—"
        given = ", ".join(
            f"{_md(field)} {t.optional('reference_mcsa_row', f'{path}.listed.{field}', row['listed'][field])}"
            for field in ("pdb_id", "chain_name", "resid", "auth_resid", "code"))
        roles = row["reference"]["roles"]
        role_list = "null" if roles is None else " | ".join(
            " / ".join(t.ref("reference_mcsa_role", f"{path}.reference.roles[{k}].{field}") for field in ROLE_FIELDS)
            for k in range(len(roles)))
        role_text = "; ".join(f"{_md(field)}: {t.ref('reference_mcsa_role', f'{path}.reference.{field}')}"
                              for field in ("roles_summary", "function_location_abv", "ptm"))
        cells = [t.value("mcsa_row_status", f"{path}.status"), reason, t.ref("reference_mcsa_row", f"{path}.mcsa_id"),
                 t.slot(row["residue_index"]), t.slot(identity(row["residue"]), escaped=True), given,
                 t.ref("reference_mcsa_row", f"{path}.is_reference"), f"{role_text}; roles: {role_list}"]
        t.lines.append("| " + " | ".join(cells) + " |")
    if unlisted:
        t.lines.append(f"- 이 보고서에 나열하지 않은 행 (ProtView 계산): "
                       f"{t.value('unlisted_line_count', f'{prefix}.mcsa.rows[*]')} (전체는 결과 객체에 있다)")


def _render_uniprot(t: _Template, prefix: str, uniprot: dict[str, Any]) -> None:
    t.lines.extend(["", "### UniProt", "", f"- 상태: {t.value('uniprot_status', f'{prefix}.uniprot.status')}"])
    if uniprot["status"] != K.CHECKED:
        t.lines.append(f"- 이유: {REASON_LABELS[uniprot['reason']]} ({_md(uniprot['reason'])})")
        skipped = uniprot["skipped"]
        if skipped is not None:
            targets = ", ".join(t.slot(a) for a in skipped["target_accessions"]) or "빈 목록 ([])"
            t.lines.append(f"- 가져올 때 건너뛴 이유: {SKIP_LABELS[skipped['reason']]} ({_md(skipped['reason'])}); "
                           f"UniProt가 알려 준 대표 accession: {targets}")
        t.lines.append("- 부위: — (검사하지 않음. 부위 개수를 세지 않았다.)")
        return
    path = f"{prefix}.uniprot.entry"
    link_field = "linked_via" if uniprot["linked_via"] is not None else "link_reason"
    t.lines.extend([
        (f"- 항목 ({REFERENCE_NOTE}): accession {t.ref('reference_uniprot_entry', f'{path}.accession')}; "
         f"entry\\_name {t.ref('reference_uniprot_entry', f'{path}.entry_name')}; protein\\_name "
         f"{t.optional('reference_uniprot_entry', f'{path}.protein_name', uniprot['entry']['protein_name'])}; "
         f"organism {t.ref('reference_uniprot_entry', f'{path}.organism')}"),
        f"- 구조 연결: {t.value('uniprot_link_state', f'{prefix}.uniprot.{link_field}')}"])
    path = f"{prefix}.uniprot.features[*].type"
    sites = "; ".join(f"{t.slot(s)} {t.value('uniprot_feature_count', path, type=s)}" for s in K.SITE_TYPES)
    t.lines.append(f"- 종류별 부위 수 (ProtView 계산): {sites}")
    if not uniprot["features"]:
        t.lines.append("- 부위: 빈 목록 ([])")
        return
    features, unlisted = listed(uniprot["features"])
    t.lines.extend([
        "", (f"부위: 이 체인에서 최대 {LINE_CAP}줄. 종류·위치·설명·리간드는 UniProt 원문({REFERENCE_NOTE})이고 위치는 "
             "UniProt 서열 위치다."), "",
        "| 종류 | 시작 | 끝 | 설명 | 리간드 이름 | 리간드 ID | 구조 연결 (ProtView 계산) |",
        "| --- | ---: | ---: | --- | --- | --- | --- |"])
    for fi, feature in features:
        path = f"{prefix}.uniprot.features[{fi}]"
        if feature["links"] is None:
            link = "연결하지 않음"
        else:
            counts = "; ".join(
                f"{LINK_LABELS[s]} ({_md(s)}) {t.value('feature_link_count', f'{path}.links[*].status', status=s)}"
                for s in K.LINK_STATUSES)
            residues = "; ".join(t.slot(identity(item["residue"]), escaped=True) for item in feature["links"]
                                 if item["status"] == "mapped")
            link = f"{counts}; 구조 잔기: {residues or '—'}"
        cells = [t.ref("reference_uniprot_site", f"{path}.{field}")
                 for field in ("type", "start", "end", "description")]
        cells.extend(t.optional("reference_uniprot_site", f"{path}.{field}", feature[field])
                     for field in ("ligand_name", "ligand_id"))
        t.lines.append("| " + " | ".join([*cells, link]) + " |")
    if unlisted:
        t.lines.append(f"- 이 보고서에 나열하지 않은 부위 (ProtView 계산): "
                       f"{t.value('unlisted_line_count', f'{prefix}.uniprot.features[*]')} (전체는 결과 객체에 있다)")


def _render_reactions(t: _Template, prefix: str, reactions: dict[str, Any]) -> None:
    t.lines.extend(["", "### 반응", "", f"- 상태: {t.value('reactions_status', f'{prefix}.reactions.status')}"])
    if reactions["status"] != K.CHECKED:
        t.lines.extend([f"- 이유: {REASON_LABELS[reactions['reason']]} ({_md(reactions['reason'])})",
                        "- EC 번호·촉매 활동: — (검사하지 않음)"])
        return
    for source, label in (("mcsa", "M-CSA"), ("uniprot", "UniProt")):
        values = reactions["ecs"][source]
        if values is None:
            text = "이 출처는 반응 정보를 주지 않았다 (null)"
        elif not values:
            text = "빈 목록 ([])"
        else:
            text = ", ".join(t.ref("reference_ec_number", f"{prefix}.reactions.ecs.{source}[{k}]")
                             for k in range(len(values)))
        t.lines.append(f"- EC 번호 ({label}, {REFERENCE_NOTE}): {text}")
    if reactions["mcsa_compounds"] is not None:
        t.lines.append("- M-CSA 반응 화합물: 결과 객체에 있다 (이 보고서에는 나열하지 않는다).")
    activities = reactions["uniprot_activities"]
    if activities is None:
        t.lines.append("- UniProt 촉매 활동: — (UniProt 절을 검사하지 않았다)")
        return
    if not activities:
        t.lines.append("- UniProt 촉매 활동: 빈 목록 ([])")
        return
    listed_activities, unlisted = listed(activities)
    t.lines.extend([
        "", (f"UniProt 촉매 활동: 이 체인에서 최대 {LINE_CAP}줄. 반응 이름·EC·Rhea ID·반응식은 참조 스냅샷 원문"
             f"({REFERENCE_NOTE})이고 Rhea 스냅샷 여부만 ProtView가 확인했다."), "",
        "| 반응 이름 | EC | Rhea (ID, 스냅샷 여부, 반응식) |", "| --- | --- | --- |"])
    for ai, activity in listed_activities:
        path = f"{prefix}.reactions.uniprot_activities[{ai}]"
        parts = []
        for bi, link in enumerate(activity["rhea"]):
            part = (f"{t.ref('reference_rhea_id', f'{path}.rhea[{bi}].rhea_id')} "
                    f"{t.value('rhea_link_state', f'{path}.rhea[{bi}].in_snapshot')}")
            if link["in_snapshot"]:   # the equation of reference_rows.rhea, found by its Rhea ID selector
                part += f": {t.ref('reference_rhea_equation', None, rhea_id=link['rhea_id'])}"
            parts.append(part)
        cells = [t.ref("reference_uniprot_activity", f"{path}.reaction_name"),
                 t.optional("reference_ec_number", f"{path}.ec_number", activity["ec_number"]),
                 "; ".join(parts) or "Rhea ID 없음 (빈 목록 [])"]
        t.lines.append("| " + " | ".join(cells) + " |")
    if unlisted:
        t.lines.append(f"- 이 보고서에 나열하지 않은 촉매 활동 (ProtView 계산): "
                       f"{t.value('unlisted_line_count', f'{prefix}.reactions.uniprot_activities[*]')} "
                       "(전체는 결과 객체에 있다)")


def build_reaction_report(run: Any, result_handle: str, *, active_set_hash: str | None) -> dict[str, Any]:
    """New report object from the stored result (the linking is not run again); ``active_set_hash`` is the active
    reaction reference set at creation (None when none is usable), recorded in the report snapshot only."""
    if active_set_hash is not None and (type(active_set_hash) is not str or not HEX64.fullmatch(active_set_hash)):
        raise EvidenceError("reaction_report_active_set_invalid")
    with run._owner():
        run.store.rebuild_from_events()
        run._refresh()
        manifest = _expected(run, result_handle)
        events = list(run.events.read())
        seq = events[-1]["seq"]
        manifest["snapshot"] = {"event_seq": seq, "time_utc": events[-1]["ts"],
                                "run_egress_mode": run.egress_config["mode"], "budget": run.budget_snapshot(),
                                "active_set_hash": active_set_hash}
        markdown = render_reaction_report(manifest)
        if len(canonical_json({**manifest, "markdown_handle": "x" * 128})) > REPORT_BYTES or \
                len(markdown.encode("utf-8")) > REPORT_BYTES:
            raise EvidenceError("reaction_report_too_large")
        produced_by = f"reaction_knowledge_report_{uuid.uuid4().hex}"
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


def saved_reaction_report(run: Any, report_handle: str) -> dict[str, Any]:
    """Re-validate a stored reaction knowledge report from stored objects only (the linking is not run again)."""
    meta = run.store.meta(report_handle)
    if (meta["kind"], meta["schema"], meta["fmt"]) != ("method_report_manifest", "method_report_manifest@1", "json"):
        raise EvidenceError("reaction_report_type")
    report = run.store.load_bounded_json(report_handle, REPORT_BYTES)
    if (type(report) is not dict or set(report) != MANIFEST_KEYS or report["analysis_type"] != ANALYSIS_TYPE or
            type(report["result_handle"]) is not str or report["render_version"] != RENDER_VERSION):
        raise EvidenceError("reaction_report_schema_invalid")
    expected = _expected(run, report["result_handle"])
    if type(report["claims"]) is not list:
        raise EvidenceError("reaction_report_claims_invalid")
    index = claim_index(expected["claims"])
    for claim in report["claims"]:
        match_claim(expected["claims"], claim, index=index)
    for key, value in expected.items():
        if canonical_json(report[key]) != canonical_json(value):
            raise EvidenceError(f"reaction_report_field_mismatch: {key}")
    snapshot = report["snapshot"]
    if (type(snapshot) is not dict or set(snapshot) != SNAPSHOT_KEYS or type(snapshot["event_seq"]) is not int or
            snapshot["event_seq"] < expected["provenance"]["completed_event_seq"] or
            snapshot["run_egress_mode"] not in {"local_only", "online", "dry_run"} or
            type(snapshot["budget"]) is not dict or
            (snapshot["active_set_hash"] is not None and (type(snapshot["active_set_hash"]) is not str or
                                                          not HEX64.fullmatch(snapshot["active_set_hash"])))):
        raise EvidenceError("reaction_report_snapshot_invalid")
    events = list(run.events.read())
    at = next((event for event in events if event["seq"] == snapshot["event_seq"]), None)
    if at is None or at["ts"] != snapshot["time_utc"]:
        raise EvidenceError("reaction_report_snapshot_mismatch")
    markdown_handle = report["markdown_handle"]
    md_meta = run.store.meta(markdown_handle)
    if (md_meta["kind"], md_meta["schema"]) != ("report_markdown", "report_markdown@1"):
        raise EvidenceError("reaction_report_markdown_type")
    created = [event for event in events if event["type"] == "method_report_created" and
               event.get("report_handle") == report_handle and event.get("markdown_handle") == markdown_handle and
               event.get("result_handle") == report["result_handle"] and
               event.get("snapshot_event_seq") == snapshot["event_seq"] and event["seq"] > snapshot["event_seq"]]
    if len(created) != 1:
        raise EvidenceError("reaction_report_event_missing")
    markdown = run.store.load_bounded_bytes(markdown_handle, REPORT_BYTES).decode("utf-8")
    if markdown != render_reaction_report(report):
        raise EvidenceError("reaction_report_markdown_mismatch")
    return {"handle": report_handle, "markdown_handle": markdown_handle, "manifest": report, "markdown": markdown}
