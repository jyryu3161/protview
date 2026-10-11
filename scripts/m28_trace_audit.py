#!/usr/bin/env python3
"""M28 trace audit of every saved report of the QA runs (.dryforge/spec.md §7, definition item 6, case X2).

Standard library only; never imports ``mw`` and never writes: it reads the loopback API with GET only (events,
``/reports/selected`` per report, ``/objects/meta`` per cited handle). The report list route is not used to judge
opening (one broken report makes the whole list 422). Both report families are audited: inspection reports
(``report_created``, ``report_manifest@1``) and method reports (``method_report_created``,
``method_report_manifest@1``, by ``analysis_type``). A kind or render version without an adapter fails (never
skipped).

Checks per report (any miss fails the report; failures name the report handle and the claim):
  reopen            1. ``GET /runs/{rid}/reports/selected?handle=…`` is 200 (the product's reopen validation: no
                       ``report_evidence_invalid``) and returns this report. Value recalculation is that product
                       validation's job and the cases' independent expectations; this audit recalculates nothing.
  evidence_exists   2a. every claim's evidence handle is ``obj://<this run>/<source_kind>/<source_sha256>``, the kind
                       is one the adapter allows, and ``/objects/meta`` of it is 200 with the claimed kind and schema.
  claim_fields      2b. field path non-empty (``[*]`` / collective paths only on aggregate claims with an
                       ``operation`` — the adapter's exemption), unit a non-empty string (a unit or an explicit unitless
                       marker), quantity named (comparison reports: exempt, the last field-path name is the quantity),
                       a row index carries its row fingerprint (a 64-hex ``row_fingerprint``; a missing key fails).
  (2 and 4)            a report without claims fails checks 2a, 2b and 4 (nothing was checked) unless its adapter says
                       claims may be empty (``claims_optional``; none of the 20 kinds does, T11: all 28 reports of the
                       T9 fixture and rehearsal runs carry claims).
  reference_source  3. a kind citing reference values ("참조값, 계산 아님") carries the snapshot source and the set
                       identifier (hash or version) in the report itself (manifest) and every reference claim
                       names that set. Resolving the source only through the cited object (M20 ``reference_object``)
                       does not pass.
  no_mixing         4. a claim is computed or reference (or model response) by ``evidence_kind``: computed carries no
                       ``reference``, a reference value carries the kind's note, and the field path belongs to its own
                       kind and to no other (the product's field rules, exported by
                       scripts/m28_export_fixed_sentences.py as ``reportRules``).
Forbidden words are not an audit check (spec §7 item 5): X4 scans them with the exported fixed sentences. Numbers in the
Markdown prose are not parsed.

Adapter table (T1 preflight (k); 20 kinds = inspection + 19 method analysis types).
Row: kind | render versions | claim shape | evidence object kinds
  inspection | inspection_markdown@1 | statement_id + operation; row claims row_index + row_fingerprint |
      interaction_set, preparation_manifest
  interface_sasa | interface_sasa_markdown@1 | summary.X / residues[i].X (+ row_index, row_fingerprint) |
      interface_sasa
  openmm_protein_minimize | openmm_markdown@1 | three top-level fields (kJ/mol) | openmm_minimization
  atom_distance | comparison_markdown@1 | no quantity (exempt), element paths [i] | atom_distance
  rigid_alignment | comparison_markdown@1 | no quantity (exempt), pairs[i].x | rigid_alignment
  chemical_interactions | chemical_markdown@1 | total / rows.{i}.field, row_id | chemical_interaction_set
  pocket_detection | pocket_markdown@1, @2 | statement_id, row_selector, operation |
      pocket_set, pocket_detector_input
  residue_numbering | residue_numbering_markdown@1 | CLAIM_KEYS (evidence_kind, reference) | residue_numbering_map
  reference_site_annotation | reference_site_annotation_markdown@1 | CLAIM_KEYS, selectors |
      reference_site_annotation, interaction_set, residue_numbering_map
  ligand_candidates | ligand_candidates_markdown@1 | computed only, count_where | ligand_candidate_set
  ligand_docking | ligand_docking_markdown@1 | computed only, {mode} selectors | docking_result
  ligand_docking_batch | ligand_docking_batch_markdown@1 | computed, {row_index} |
      docking_batch_result, docking_result
  ligand_ga | ligand_ga_markdown@1 | computed, generation selectors | ligand_ga_result, docking_result
  sequence_ga | sequence_ga_markdown@1 | computed, + reference row | sequence_ga_result, docking_result
  mutation_candidates | mutation_candidates_markdown@1, mutation_candidates_markdown@2 |
      CLAIM_KEYS; reference {note, reference_object} | mutation_candidate_set
  mutation_model | mutation_model_markdown@1 | computed, {structure[, stage]} | mutation_model
  jev_choice | jev_choice_markdown@1 | computed / model_response | jev_choice
  jev_loop | jev_loop_markdown@1 | computed / model_response | jev_loop_result, docking_result, jev_loop_choice
  reaction_knowledge | reaction_knowledge_markdown@1 | CLAIM_KEYS; reference {note, set_hash, sources} |
      reaction_knowledge
  kinase_precedents | kinase_precedents_markdown@1 | CLAIM_KEYS; reference {note, set_hash, kb_version, …} |
      kinase_precedents
  Exemptions: aggregate claims (``operation`` set) may cite ``[*]`` / collective paths; comparison claims have no
  quantity. Reference kinds (check 3): residue_numbering and reference_site_annotation (manifest ``snapshot_set``,
  M15), reaction_knowledge (``snapshot_set``, M26), kinase_precedents (``precedent_set``, M27), mutation_candidates
  (@1 has no source table → a report citing reference values fails; @2 must carry a snapshot set per cited family).
  Product recheck on reopen (spec §7 item 1 premise): full for every kind except ``inspection`` (no claim
  revalidation and no Markdown regeneration) and ``interface_sasa`` (no Markdown regeneration): for these two the
  premise "the product validation recalculates" does not hold (제품 재계산 전제 불성립); cases A2 / A3 compare the
  values with independent expectations instead (handoff decision 5).

Output (``m28_trace_audit@1``): status, report count, count per kind, pass / fail per check, the failures (report
handle, claim, check, problem), the adapter table used and the report SHA-256 list (handle hash, Markdown and canonical
manifest SHA-256; no content).

Usage (GET only, the backend of the QA runs on 127.0.0.1:8000):
  python scripts/m28_trace_audit.py --run <run id> [--run …] --rules <fixed-sentences.json> [--out audit.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass

SCHEMA = "m28_trace_audit@1"
CHECKS = ("reopen", "evidence_exists", "claim_fields", "reference_source", "no_mixing")
HEX64 = re.compile(r"[0-9a-f]{64}")
HANDLE = re.compile(r"obj://(?P<run>[^/]+)/(?P<kind>[A-Za-z0-9_]+)/(?P<sha>[0-9a-f]{64})")
REFERENCE_NOTE = "참조 스냅샷 값, 계산 아님"
KBASE_NOTE = "kbase 가공본 값, 계산 아님"
MODEL_RESPONSE_NOTE = "외부 모델의 응답, 제안이며 과학 증거가 아니다"
FULL = "full"
PARTIAL_NOTE = "제품 재계산 전제 불성립"
# Units the report modules write (T1 (k), product module constants). A non-empty unit string passes check 2b; this
# split only labels it (a physical unit or an explicit unitless marker) in the audit output.
PHYSICAL_UNITS = frozenset({"angstrom", "A", "A2", "A3", "angstrom_squared", "Da", "kcal/mol", "kJ/mol", "s", "degree"})
UNITLESS_MARKERS = frozenset({
    "count", "dimensionless", "identifier", "flag", "status", "text", "handle", "sha256", "residue_field",
    "model_number", "seed", "index", "one_letter", "residue_name", "position", "0-1", "bytes", "tokens", "usd",
    "percent", "fraction", "iterations", "uniprot_sequence_position", "klifs_pocket_index", "residue_identity",
    "sdf_atom_serial", "mcsa_residue_number", "paper_page", "reason"})
M15_SOURCES = frozenset({"sifts", "klifs"})
M26_SOURCES = frozenset({"mcsa", "rhea", "uniprot_function"})


@dataclass(frozen=True)
class Adapter:
    kind: str
    family: str                          # "inspection" | "method"
    versions: tuple[str, ...]
    shape: str
    source_kinds: tuple[str, ...]
    evidence_kinds: tuple[str, ...] | None = None   # None: the kind has no evidence_kind (all computed)
    aggregates: bool = False             # claims may carry an ``operation`` (aggregate exemption)
    collective: str | None = None        # a path pattern that is a collection (needs an operation) besides [*]
    quantity_exempt: bool = False
    reference: str | None = None         # check 3 rule: m15 | m26 | m27 | m20
    reference_note: str | None = None
    reopen: str = FULL                   # FULL or what the product reopen does not redo
    exemptions: str = ""
    claims_optional: bool = False        # a report of this kind may carry no claim (checks 2 and 4 then see nothing)


ADAPTERS: dict[str, Adapter] = {a.kind: a for a in (
    Adapter("inspection", "inspection", ("inspection_markdown@1",),
            "statement_id + operation; row claims row_index + row_fingerprint",
            ("interaction_set", "preparation_manifest"), aggregates=True, collective=r"rows(?:\..+)?",
            reopen="no claim revalidation, no Markdown regeneration",
            exemptions="aggregate claims (operation) on rows / rows.<field>"),
    Adapter("interface_sasa", "method", ("interface_sasa_markdown@1",),
            "summary.X (row_index null) / residues[i].X (row_index + row_fingerprint), unit A2",
            ("interface_sasa",), reopen="no Markdown regeneration"),
    Adapter("openmm_protein_minimize", "method", ("openmm_markdown@1",), "three top-level fields, kJ/mol",
            ("openmm_minimization",)),
    Adapter("atom_distance", "method", ("comparison_markdown@1",), "no quantity / statement_id; element paths [i]",
            ("atom_distance",), quantity_exempt=True, exemptions="quantity = last field-path name"),
    Adapter("rigid_alignment", "method", ("comparison_markdown@1",), "no quantity / statement_id; pairs[i].x",
            ("rigid_alignment",), quantity_exempt=True, exemptions="quantity = last field-path name"),
    Adapter("chemical_interactions", "method", ("chemical_markdown@1",), "total or rows.{i}.{distance_A|DHA_angle_deg}",
            ("chemical_interaction_set",)),
    Adapter("pocket_detection", "method", ("pocket_markdown@1", "pocket_markdown@2"),
            "statement_id, row_selector {rank} / null, operation", ("pocket_set", "pocket_detector_input"),
            aggregates=True, exemptions="pocket_count (count), lining_residue_count (count_distinct)"),
    Adapter("residue_numbering", "method", ("residue_numbering_markdown@1",),
            "CLAIM_KEYS: evidence_kind, row_selector, operation, reference", ("residue_numbering_map",),
            ("computed", "reference_value"), aggregates=True, collective=r"rows\..+", reference="m15",
            reference_note=REFERENCE_NOTE, exemptions="status / mismatch / ambiguous counts (count_kind)"),
    Adapter("reference_site_annotation", "method", ("reference_site_annotation_markdown@1",),
            "CLAIM_KEYS; selectors {status} {absent_reason} {chain_auth, klifs_item} {row_index, row_sha256}",
            ("reference_site_annotation", "interaction_set", "residue_numbering_map"), ("computed", "reference_value"),
            aggregates=True, collective=r"(?:groups\.sites|rows)\..+", reference="m15", reference_note=REFERENCE_NOTE,
            exemptions="site status / absent reason / contact counts (count_kind)"),
    Adapter("ligand_candidates", "method", ("ligand_candidates_markdown@1",), "computed only; count_where",
            ("ligand_candidate_set",), ("computed",), aggregates=True, exemptions="candidates[*] count_where"),
    Adapter("ligand_docking", "method", ("ligand_docking_markdown@1",), "computed only; {mode} / {mode, kind}",
            ("docking_result",), ("computed",), aggregates=True,
            exemptions="score minimum / maximum over modes[*], contact counts"),
    Adapter("ligand_docking_batch", "method", ("ligand_docking_batch_markdown@1",),
            "computed; row_score / row_result_score {row_index}", ("docking_batch_result", "docking_result"),
            ("computed",), aggregates=True, exemptions="row and state counts"),
    Adapter("ligand_ga", "method", ("ligand_ga_markdown@1",),
            "computed; {generation, where} {generation} {generation, position}", ("ligand_ga_result", "docking_result"),
            ("computed",), aggregates=True, exemptions="run / generation counts"),
    Adapter("sequence_ga", "method", ("sequence_ga_markdown@1",), "computed; generation selectors + reference row",
            ("sequence_ga_result", "docking_result"), ("computed",), aggregates=True,
            exemptions="run / generation counts"),
    Adapter("mutation_candidates", "method", ("mutation_candidates_markdown@1", "mutation_candidates_markdown@2"),
            "CLAIM_KEYS; reference {note, reference_object}", ("mutation_candidate_set",),
            ("computed", "reference_value"), aggregates=True, reference="m20", reference_note=REFERENCE_NOTE,
            exemptions="positions[*] / candidates[*] count / count_where, catalytic_covered_chain_count"),
    Adapter("mutation_model", "method", ("mutation_model_markdown@1",), "computed; {structure[, stage]}",
            ("mutation_model",), ("computed",), aggregates=True, exemptions="contact / pair / difference counts"),
    Adapter("jev_choice", "method", ("jev_choice_markdown@1",), "computed / model_response {note, proposal_handle}",
            ("jev_choice",), ("computed", "model_response"), aggregates=True, exemptions="selection_count"),
    Adapter("jev_loop", "method", ("jev_loop_markdown@1",), "computed / model_response; {candidate} {iteration}",
            ("jev_loop_result", "docking_result", "jev_loop_choice"), ("computed", "model_response"),
            aggregates=True, exemptions="pool_size"),
    Adapter("reaction_knowledge", "method", ("reaction_knowledge_markdown@1",),
            "CLAIM_KEYS; reference {note, set_hash, sources}; selectors row_index / row_sha256",
            ("reaction_knowledge",),
            ("computed", "reference_value"), aggregates=True, reference="m26", reference_note=REFERENCE_NOTE,
            exemptions="chains[*] count / count_where / count_distinct, unlisted_line_count"),
    Adapter("kinase_precedents", "method", ("kinase_precedents_markdown@1",),
            "CLAIM_KEYS; reference {note, set_hash, kb_version, imported_at, source}", ("kinase_precedents",),
            ("computed", "reference_value"), aggregates=True, reference="m27", reference_note=KBASE_NOTE,
            exemptions="chains[*] / targets[*] count / count_where / sum, unlisted / pass-check counts"),
)}
EXPECTED_SCHEMA = {"report_created": "report_manifest@1", "method_report_created": "method_report_manifest@1"}


def adapter_table() -> list[dict]:
    """The adapter table as data (written with every audit result)."""
    return [{**asdict(adapter), "productRecheck": adapter.reopen,
             "note": None if adapter.reopen == FULL else f"{PARTIAL_NOTE}: {adapter.reopen}"}
            for adapter in ADAPTERS.values()]


def canonical_sha256(value: object) -> str:
    """SHA-256 of the product's canonical JSON (sorted keys, no spaces, UTF-8): the JSON download's bytes."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def claim_label(index: int, claim: object) -> str:
    if not isinstance(claim, dict):
        return f"#{index}"
    return f"#{index} {claim.get('statement_id') or claim.get('field_path') or ''}".strip()


def pick_adapter(event_type: str, manifest: dict) -> tuple[Adapter | None, str | None]:
    """The adapter of a reopened report, or (None, why): the event family, the manifest schema, the kind and the
    render version must all be known."""
    schema = manifest.get("schema")
    if EXPECTED_SCHEMA.get(event_type) != schema:
        return None, f"event {event_type} with manifest schema {schema!r}"
    kind = "inspection" if event_type == "report_created" else manifest.get("analysis_type")
    adapter = ADAPTERS.get(kind) if isinstance(kind, str) else None
    if adapter is None or (adapter.family == "inspection") != (event_type == "report_created"):
        return None, f"no adapter for kind {kind!r}"
    if manifest.get("render_version") not in adapter.versions:
        return None, f"no adapter for {kind} render version {manifest.get('render_version')!r}"
    return adapter, None


# ---------------------------------------------------------------------------------------------------- check 2
def evidence_problems(rid: str, adapter: Adapter, claim: dict,
                      meta_of: Callable[[str], tuple[int, object]]) -> list[str]:
    handle, kind = claim.get("source_handle"), claim.get("source_kind")
    found = HANDLE.fullmatch(handle) if isinstance(handle, str) else None
    if found is None:
        return [f"source_handle {handle!r} is not an object handle"]
    problems = []
    if found["run"] != rid:
        problems.append(f"source_handle belongs to run {found['run']}, not {rid}")
    if found["kind"] != kind:
        problems.append(f"source_handle kind {found['kind']} != source_kind {kind!r}")
    if found["sha"] != claim.get("source_sha256"):
        problems.append("source_handle hash != source_sha256")
    if kind not in adapter.source_kinds:
        problems.append(f"source_kind {kind!r} is not an evidence kind of {adapter.kind}")
    if problems:
        return problems
    status, meta = meta_of(handle)
    if status != 200 or not isinstance(meta, dict):
        return [f"evidence object not in the run's store (HTTP {status})"]
    if meta.get("kind") != kind or meta.get("schema") != claim.get("source_schema"):
        return [(f"stored object is {meta.get('kind')}/{meta.get('schema')}, the claim says "
                 f"{kind}/{claim.get('source_schema')}")]
    return []


def field_problems(adapter: Adapter, claim: dict) -> list[str]:
    problems = []
    path = claim.get("field_path")
    if not isinstance(path, str) or not path.strip():
        return ["field_path empty"]
    aggregate = isinstance(claim.get("operation"), str) and bool(claim["operation"].strip())
    collective = "[*]" in path or bool(adapter.collective and re.fullmatch(adapter.collective, path))
    if "operation" in claim and claim["operation"] is not None and not aggregate:
        problems.append("operation is not a non-empty string")
    if aggregate and not adapter.aggregates:
        problems.append(f"{adapter.kind} has no aggregate claims")
    if collective and not (aggregate and adapter.aggregates):
        problems.append(f"collection path {path!r} without an aggregate operation")
    unit = claim.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        problems.append("unit missing (neither a unit nor an explicit unitless marker)")
    if not adapter.quantity_exempt:
        quantity = claim.get("quantity")
        if not isinstance(quantity, str) or not quantity.strip():
            problems.append("quantity missing")
    if claim.get("row_index") is not None:
        if type(claim["row_index"]) is not int or claim["row_index"] < 0:
            problems.append("row_index is not a non-negative integer")
        if not HEX64.fullmatch(str(claim.get("row_fingerprint"))):
            problems.append("row_index without a row_fingerprint")
    selector = claim.get("row_selector")
    if selector is not None and not (isinstance(selector, dict) and selector):
        problems.append("row_selector is neither null nor a non-empty object")
    return problems


# ---------------------------------------------------------------------------------------------------- check 3
def _sources_ok(sources: object, need_date: bool = False) -> bool:
    return (isinstance(sources, list) and bool(sources) and all(
        isinstance(item, dict) and isinstance(item.get("source"), str) and item["source"].strip()
        and (not need_date or any(isinstance(item.get(key), str) and item[key].strip()
                                  for key in ("date", "version_hint", "snapshot_id")))
        for item in sources))


def _set_object(value: object, need_date: bool = True) -> bool:
    return (isinstance(value, dict) and HEX64.fullmatch(str(value.get("set_hash"))) is not None
            and _sources_ok(value.get("sources"), need_date))


def _reference_claims(claims: list) -> list[tuple[int, dict]]:
    return [(index, claim) for index, claim in enumerate(claims)
            if isinstance(claim, dict) and claim.get("evidence_kind") == "reference_value"]


def _claim_sets(refs: list[tuple[int, dict]], set_hash: str, key_values: dict[str, object] | None = None,
                source_names: set[str] | None = None) -> list[tuple[str, str]]:
    problems = []
    for index, claim in refs:
        reference = claim.get("reference") if isinstance(claim.get("reference"), dict) else {}
        if reference.get("set_hash") != set_hash:
            problems.append((claim_label(index, claim), "reference names no set of this report (set_hash)"))
            continue
        for key, value in (key_values or {}).items():
            if reference.get(key) != value:
                problems.append((claim_label(index, claim), f"reference {key} differs from the report's set"))
        if source_names is not None:
            named = {item.get("source") for item in reference.get("sources") or [] if isinstance(item, dict)}
            if not named or not named <= source_names:
                problems.append((claim_label(index, claim), "reference sources not in the report's set"))
    return problems


def _snapshot_sets(value: object) -> list[dict]:
    """Snapshot-set objects anywhere in a manifest value (dicts with a 64-hex set_hash and named sources)."""
    found = []
    if isinstance(value, dict):
        if _set_object(value, need_date=False):
            found.append(value)
        for item in value.values():
            found += _snapshot_sets(item)
    elif isinstance(value, list):
        for item in value:
            found += _snapshot_sets(item)
    return found


def _families(entry: dict) -> set[str]:
    names = {item.get("source") for item in entry.get("sources") or [] if isinstance(item, dict)}
    return {name for name, sources in (("m15", M15_SOURCES), ("m26", M26_SOURCES)) if names & sources}


def reference_problems(adapter: Adapter, manifest: dict, markdown: str) -> list[tuple[str, str]]:
    """Check 3 for one report: (claim label or "report", problem) pairs."""
    claims = manifest.get("claims") if isinstance(manifest.get("claims"), list) else []
    refs = _reference_claims(claims)
    if adapter.reference is None:
        return [(claim_label(i, c), f"{adapter.kind} cites no reference values") for i, c in refs]
    if not refs:
        return []                                   # nothing cited: no source table needed
    if adapter.reference in ("m15", "m26"):
        snapshot = manifest.get("snapshot_set")
        if not _set_object(snapshot):
            return [("report", "manifest has no snapshot_set with a set hash and dated sources")]
        if adapter.reference == "m26" and not str(snapshot.get("imported_at") or "").strip():
            return [("report", "snapshot_set has no imported_at")]
        names = {item["source"] for item in snapshot["sources"]}
        return _claim_sets(refs, snapshot["set_hash"], source_names=names)
    if adapter.reference == "m27":
        precedent = manifest.get("precedent_set")
        kbase = precedent.get("kbase") if isinstance(precedent, dict) else None
        if not (isinstance(precedent, dict) and HEX64.fullmatch(str(precedent.get("set_hash")))
                and isinstance(kbase, dict) and str(kbase.get("kb_version") or "").strip()
                and str(kbase.get("origin") or "").strip()):
            return [("report", "manifest has no precedent_set with a set hash, kb_version and origin")]
        return _claim_sets(refs, precedent["set_hash"], {"kb_version": kbase["kb_version"]})
    # m20: the reference claims name only the cited object; the report itself must carry each cited family's set.
    if manifest.get("render_version") == "mutation_candidates_markdown@1":
        return [(claim_label(i, c), ("reference resolved only through the cited object (no snapshot source or "
                                     "set identifier in the report)")) for i, c in refs]
    need: set[str] = set()
    for index, claim in refs:
        reference = claim.get("reference") if isinstance(claim.get("reference"), dict) else {}
        found = HANDLE.fullmatch(str(reference.get("reference_object")))
        kind = found["kind"] if found else None
        need.add("m26" if kind == "reaction_knowledge" else "m15" if kind in (
            "residue_numbering_map", "reference_site_annotation") else f"unknown:{kind}")
    sets = _snapshot_sets({key: value for key, value in manifest.items() if key != "claims"})
    have: dict[str, list[str]] = {}
    for entry in sets:
        for family in _families(entry):
            have.setdefault(family, []).append(entry["set_hash"])
    problems = []
    for family in sorted(need):
        hashes = have.get(family) or []
        if not hashes:
            problems.append(("report", f"no {family} snapshot set (source and set hash) in the report"))
        elif not any(set_hash in markdown for set_hash in hashes):
            problems.append(("report", f"the {family} set hash is not in the report Markdown"))
    return problems


# ---------------------------------------------------------------------------------------------------- check 4
def mixing_problems(adapter: Adapter, claim: dict, rules: dict | None) -> list[str]:
    kind, reference = claim.get("evidence_kind"), claim.get("reference")
    if adapter.evidence_kinds is None:
        problems = []
        if kind is not None:
            problems.append(f"evidence_kind {kind!r} on a kind without evidence kinds")
        if reference is not None:
            problems.append("a computed-only kind carries a reference")
        return problems
    if kind not in adapter.evidence_kinds:
        return [f"evidence_kind {kind!r} not in {adapter.evidence_kinds}"]
    problems = []
    if kind == "computed" and reference is not None:
        problems.append("computed claim carries a reference")
    if kind == "reference_value" and not (isinstance(reference, dict)
                                          and reference.get("note") == adapter.reference_note):
        problems.append("reference value without the kind's reference note")
    if kind == "model_response" and not (isinstance(reference, dict)
                                         and reference.get("note") == MODEL_RESPONSE_NOTE):
        problems.append("model response without the model-response note")
    fields = ((rules or {}).get(adapter.kind) or {}).get("fields")
    if not isinstance(fields, dict) or kind not in fields:
        return [*problems, f"field rules of {adapter.kind} not exported"]
    path = str(claim.get("field_path"))
    if not re.fullmatch(fields[kind], path):
        problems.append(f"{kind} claim cites {path!r}, not a {kind} field")
    for other, pattern in fields.items():
        if other != kind and re.fullmatch(pattern, path):
            problems.append(f"{kind} claim cites a {other} field {path!r}")
    return problems


# ---------------------------------------------------------------------------------------------------- one report
def audit_report(fetch: Callable[[str], tuple[int, object]], rid: str, event: dict, rules: dict | None,
                 meta_cache: dict | None = None) -> dict:
    """Every check of one report (by its creation event). Returns {handle, kind, checks, failures, hashes, markdown}."""
    handle = event.get("report_handle")
    meta_cache = {} if meta_cache is None else meta_cache
    result: dict = {"run": rid, "handle": handle, "event": event.get("type"), "kind": None,
                    "checks": {check: "not_checked" for check in CHECKS}, "failures": [], "hashes": None,
                    "markdown": None, "units": {}}

    def fail(check: str, claim: str, problem: str) -> None:
        result["checks"][check] = "fail"
        result["failures"].append({"run": rid, "report": handle, "claim": claim, "check": check, "problem": problem})

    quoted = urllib.parse.quote(str(handle), safe="")
    status, body = fetch(f"/runs/{rid}/reports/selected?handle={quoted}")
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("manifest"), dict):
        code = body.get("detail", {}).get("error") if isinstance(body, dict) and isinstance(
            body.get("detail"), dict) else None
        fail("reopen", "report", f"reopen HTTP {status}" + (f" {code}" if code else ""))
        return result
    manifest, markdown = body["manifest"], body.get("markdown")
    if body.get("handle") != handle or not isinstance(markdown, str):
        fail("reopen", "report", "reopen returned another report or no Markdown")
        return result
    result["checks"]["reopen"] = "pass"
    result["markdown"] = markdown
    result["hashes"] = {"handleSha256": str(handle).rsplit("/", 1)[-1], "manifestSha256": canonical_sha256(manifest),
                        "markdownSha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest()}
    adapter, why = pick_adapter(str(event.get("type")), manifest)
    if adapter is None:
        result["kind"] = manifest.get("analysis_type") or manifest.get("schema")
        for check in CHECKS[1:]:
            fail(check, "report", f"no adapter: {why}")
        return result
    result["kind"] = adapter.kind
    result["productRecheck"] = adapter.reopen
    claims = manifest.get("claims")
    if not isinstance(claims, list):
        for check in CHECKS[1:]:
            fail(check, "report", "manifest has no claims list")
        return result

    def meta_of(object_handle: str) -> tuple[int, object]:
        if object_handle not in meta_cache:
            meta_cache[object_handle] = fetch(f"/runs/{rid}/objects/meta?handle="
                                              f"{urllib.parse.quote(object_handle, safe='')}")
        return meta_cache[object_handle]

    for check in ("evidence_exists", "claim_fields", "no_mixing"):
        result["checks"][check] = "pass"
    if not claims and not adapter.claims_optional:
        for check in ("evidence_exists", "claim_fields", "no_mixing"):
            fail(check, "report", f"the report has no claims (the {adapter.kind} adapter does not allow none)")
    for index, claim in enumerate(claims):
        label = claim_label(index, claim)
        if not isinstance(claim, dict):
            for check in ("evidence_exists", "claim_fields", "no_mixing"):
                fail(check, label, "claim is not an object")
            continue
        for problem in evidence_problems(rid, adapter, claim, meta_of):
            fail("evidence_exists", label, problem)
        for problem in field_problems(adapter, claim):
            fail("claim_fields", label, problem)
        for problem in mixing_problems(adapter, claim, rules):
            fail("no_mixing", label, problem)
        unit = claim.get("unit")
        if isinstance(unit, str):
            result["units"][unit] = result["units"].get(unit, 0) + 1
    result["checks"]["reference_source"] = "pass"
    for label, problem in reference_problems(adapter, manifest, markdown):
        fail("reference_source", label, problem)
    return result


# ---------------------------------------------------------------------------------------------------- runs
def report_events(fetch: Callable[[str], tuple[int, object]], rid: str) -> list[dict]:
    """The report creation events of a run (every page of 500)."""
    found, after = [], 0
    while True:
        status, page = fetch(f"/runs/{rid}/events?after={after}&limit=500")
        if status != 200 or not isinstance(page, list):
            raise RuntimeError(f"events of {rid} unreadable (HTTP {status})")
        found += [event for event in page if isinstance(event, dict) and event.get("type") in EXPECTED_SCHEMA]
        if len(page) < 500:
            return found
        after = page[-1]["seq"]


def audit_runs(fetch: Callable[[str], tuple[int, object]], runs: Iterable[str], rules: dict | None) -> dict:
    """Audit every saved report of ``runs``. The returned summary is JSON; its ``_markdown`` entry (report handle →
    Markdown text, for the X4 scan) must be dropped before writing."""
    reports, failures, markdown = [], [], {}
    per_check = {check: {"pass": 0, "fail": 0, "not_checked": 0} for check in CHECKS}
    by_kind: dict[str, int] = {}
    units: dict[str, int] = {}
    read_errors = []
    for rid in runs:
        try:
            events = report_events(fetch, rid)
        except RuntimeError as exc:
            read_errors.append({"run": rid, "problem": str(exc)})
            continue
        cache: dict = {}
        for event in events:
            result = audit_report(fetch, rid, event, rules, cache)
            if result["markdown"] is not None:
                markdown[result["handle"]] = result["markdown"]
            for check, value in result["checks"].items():
                per_check[check][value] += 1
            by_kind[str(result["kind"])] = by_kind.get(str(result["kind"]), 0) + 1
            for unit, count in result["units"].items():
                units[unit] = units.get(unit, 0) + count
            failures += result["failures"]
            reports.append({"run": rid, "handle": result["handle"], "kind": result["kind"],
                            "event": result["event"], "checks": result["checks"],
                            "productRecheck": result.get("productRecheck"), "hashes": result["hashes"]})
    failures += [{"run": item["run"], "report": None, "claim": None, "check": "reopen", "problem": item["problem"]}
                 for item in read_errors]
    status = "pass" if reports and not failures else "fail"
    partial = sorted({r["kind"] for r in reports if r.get("productRecheck") not in (None, FULL)})
    return {
        "schema": SCHEMA, "status": status, "reportCount": len(reports), "byKind": dict(sorted(by_kind.items())),
        "checks": per_check, "failures": failures, "noReports": not reports,
        "units": {"physical": sorted(u for u in units if u in PHYSICAL_UNITS),
                  "unitless": sorted(u for u in units if u in UNITLESS_MARKERS),
                  "unclassified": sorted(u for u in units if u not in PHYSICAL_UNITS | UNITLESS_MARKERS)},
        "partialProductRecheck": [{"kind": kind, "note": f"{PARTIAL_NOTE}: {ADAPTERS[kind].reopen}"}
                                  for kind in partial],
        "scope": ["값 재계산은 하지 않는다(제품의 다시 열기 검증과 사례별 독립 기대값이 맡음)",
                  "Markdown 서술 속 숫자는 파싱하지 않는다", "금지어는 이 감사의 검사 항목이 아니다(X4)"],
        "adapters": adapter_table(), "reports": reports, "_markdown": markdown}


def http_fetch(base: str = "http://127.0.0.1:8000", timeout: float = 300) -> Callable[[str], tuple[int, object]]:
    """GET-only loopback reader."""
    if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError(f"loopback only: {base}")

    def fetch(path: str) -> tuple[int, object]:
        try:
            with urllib.request.urlopen(urllib.request.Request(base + path, method="GET"), timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            data = exc.read()
            try:
                return exc.code, json.loads(data or b"null")
            except ValueError:
                return exc.code, data.decode(errors="replace")
        except (OSError, ValueError) as exc:      # no answer or no JSON: status 0, the checks fail (never skipped)
            return 0, {"error": type(exc).__name__}
    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--run", action="append", required=True, help="run ID whose reports are audited (repeatable)")
    parser.add_argument("--rules", required=True, help="JSON of scripts/m28_export_fixed_sentences.py (reportRules)")
    parser.add_argument("--out", help="write the audit JSON here (else stdout)")
    args = parser.parse_args(argv)
    with open(args.rules, encoding="utf-8") as handle:
        rules = json.load(handle).get("reportRules")
    summary = audit_runs(http_fetch(args.api), args.run, rules)
    summary.pop("_markdown", None)
    text = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
