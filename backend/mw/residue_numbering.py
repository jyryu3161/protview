"""M15 residue numbering: structure chain residues -> UniProt positions (SIFTS and local alignment) + KLIFS labels.

Pure logic over an already pinned reference set (``mw.reference_snapshots``) and an already parsed structure; the
tool wrapper (``mw.tools.numbering``) owns validation order, failure classes and object storage.

Chain residue rule (``RESIDUE_RULE``): in the selected model, a residue is a chain residue when gemmi's entity setup
(``Structure.setup_entities()`` on a private parse: mmCIF ``_entity``, PDB SEQRES/MODRES) puts it in a polymer entity,
or when it is written as an ATOM record (``het_flag == "A"``). HETATM modified residues inside the polymer (MSE) are
therefore included; water and non-polymer ligands are not. Residue identity (7 fields) is taken from a parse *before*
entity setup so it is exactly the identity every other tool reports (gemmi may invent subchain names for PDB input).

Method choice per chain, row status (``mapped | unmapped | conflict``), SIFTS matching and the alignment threshold
follow docs spec M15 5.2-5.7. Every position and KLIFS number is a reference snapshot value; the only values computed
here are the alignment statistics (identity, coverage, counts).
"""
from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from . import reference_snapshots as rs
from . import sequence_alignment as sa
from . import sifts_mapping as sm
from .klifs_numbering import index_kinases_by_uniprot, klifs_table

SCHEMA = "residue_numbering_map@1"
KIND = "residue_numbering_map"
SET_KIND = "reference_snapshot_set"
METHOD_VERSION = "mw.residue_numbering/v1"
RESIDUE_RULE = "gemmi_polymer_entity_or_atom_record@1"
MIN_IDENTITY_PCT = 90.0
MIN_COVERAGE_PCT = 50.0
MAX_ALIGNMENT_CELLS = sa.MAX_ALIGNMENT_CELLS
SIFTS_CHAIN_MATCH = "auth_only"

CROSS_CHECK_ABSENT_REASONS = (
    "pdb_id_not_given", "pdb_not_in_sifts_snapshot", "chain_not_in_sifts_snapshot", "sifts_chain_lookup_failed",
    "sifts_chain_no_segments", "accession_differs_from_sifts", "multiple_sifts_accessions",
    "sifts_accession_not_in_uniprot_snapshot", "sifts_accession_uniprot_lookup_failed", "alignment_too_large",
)
SIFTS_ABSENT_REASONS = ("sifts_no_residue_row", "sifts_ambiguous_residue_row", "sifts_number_mismatch",
                        "sifts_not_observed", "sifts_outside_segments", "sifts_position_outside_sequence")
ALIGNMENT_ABSENT_REASONS = ("alignment_gap", "alignment_ambiguous", "alignment_below_identity",
                            "alignment_below_coverage")
# Accession-level KLIFS reasons: the klifs_numbering set plus one for a mapped accession without a UniProt sequence.
KLIFS_ABSENT_REASONS = ("accession_not_in_klifs", "klifs_pocket_empty", "klifs_multiple_entries",
                        "uniprot_sequence_unavailable")
CONFLICT_REASONS = ("positions_differ", "one_method_only")
LIMITATIONS = ("UniProt positions, accessions and KLIFS pocket numbers are reference snapshot values (kbase_kinase "
               "processed snapshots), not ProtView calculations; ProtView computes only the alignment statistics. "
               "SIFTS chains are matched by author chain ID only. A conflict keeps both answers and picks neither.")
_ALIGN_ALPHABET = frozenset("ARNDCQEGHILKMFPSTWYVBZX*")


def absent(*reasons: str) -> dict[str, Any]:
    """A method's "no answer" for one residue: every reason in order; ``absent_reason`` is the first (compatibility)."""
    return {"absent_reason": reasons[0], "absent_reasons": list(reasons)}


class NumberingInvalid(Exception):
    """Input that the tool must refuse before running (mapped to ``input_invalid`` by the tool wrapper)."""

    def __init__(self, reason_code: str, message: str, chain_auth: str | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.chain_auth = chain_auth


# ---------------------------------------------------------------------------------------------------------------
# reference indexes (per pinned set)

@dataclass(frozen=True)
class ReferenceIndex:
    set_hash: str
    uniprot: dict[str, dict[str, Any]]            # accession -> {"status", "sequence" (None unless ok)}
    klifs: dict[str, list[dict[str, Any]]]        # accession -> KLIFS kinases rows (file order)
    sifts: sm.SiftsIndex


_INDEXES: dict[str, ReferenceIndex] = {}
_INDEX_LOCK = threading.Lock()
_CACHE_SETS = 2


def _uniprot_index(rows: Iterable[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if (type(row) is not dict or type(row.get("id")) is not str or not row["id"]
                or type(row.get("status")) is not str or row["id"] in index):
            raise ValueError("unknown UniProt snapshot row")
        sequence = None
        if row["status"] == "ok":
            data = row.get("data")
            if (type(data) is not dict or type(data.get("sequence")) is not str or not data["sequence"]
                    or not (data["sequence"].isascii() and data["sequence"].isalpha() and data["sequence"].isupper())
                    or data.get("accession", row["id"]) != row["id"]):
                raise ValueError("unknown UniProt entry")
            sequence = data["sequence"]
        index[row["id"]] = {"status": row["status"], "sequence": sequence}
    return index


def reference_index(pinned: rs.PinnedSet) -> ReferenceIndex:
    """UniProt / KLIFS / SIFTS lookups of one pinned set, built once per set hash (bad format -> snapshot_invalid)."""
    with _INDEX_LOCK:
        cached = _INDEXES.get(pinned.set_hash)
    if cached is not None:
        return cached
    try:
        uniprot = _uniprot_index(pinned.iter_jsonl("uniprot", "entries.jsonl"))
        klifs_rows = list(pinned.iter_jsonl("klifs", "kinases.jsonl"))
        if any(type(row) is not dict for row in klifs_rows):
            raise ValueError("unknown KLIFS row")
        klifs = index_kinases_by_uniprot(klifs_rows)
    except ValueError as exc:
        raise rs.SnapshotUnavailable("snapshot_invalid") from exc
    index = ReferenceIndex(pinned.set_hash, uniprot, klifs, sm.index_for_set(pinned))
    with _INDEX_LOCK:
        while len(_INDEXES) >= _CACHE_SETS:
            _INDEXES.pop(next(iter(_INDEXES)))
        return _INDEXES.setdefault(pinned.set_hash, index)


# ---------------------------------------------------------------------------------------------------------------
# chain residues

def chain_residues(st: Any, res_ref: Any) -> dict[str, dict[str, Any]]:
    """Chain residues per author chain of ``st[0]`` in file order: ``{chain_auth: {"residues", "modified"}}``.

    ``st`` must hold only the selected model and must not have had ``setup_entities()`` called; ``res_ref(chain,
    residue, model_number)`` builds the 7-field identity. This function calls ``setup_entities()`` on ``st``.
    """
    import gemmi

    model = st[0]
    before = [(chain.name, residue.seqid.num, residue.seqid.icode, residue.name, res_ref(chain, residue, model.num))
              for chain in model for residue in chain]
    st.setup_entities()
    model = st[0]
    after = [(chain.name, residue) for chain in model for residue in chain]
    if len(after) != len(before):
        raise ValueError("entity setup changed the residue list")
    result: dict[str, dict[str, Any]] = {}
    for (name, num, icode, resname, ref), (name2, residue) in zip(before, after, strict=True):
        if (name, num, icode, resname) != (name2, residue.seqid.num, residue.seqid.icode, residue.name):
            raise ValueError("entity setup changed the residue order")
        if residue.entity_type == gemmi.EntityType.Polymer or residue.het_flag == "A":
            chain = result.setdefault(name, {"residues": [], "modified": 0})
            chain["residues"].append(ref)
            if resname not in sa.THREE_TO_ONE:
                chain["modified"] += 1
    return result


# ---------------------------------------------------------------------------------------------------------------
# method decision (spec 5.2)

@dataclass(frozen=True)
class ChainPlan:
    chain_auth: str
    residues: tuple[dict[str, Any], ...]
    modified_count: int
    methods: tuple[str, ...]
    cross_check_absent_reason: str | None
    sifts_chain: sm.SiftsChain | None
    sifts_accessions: tuple[str, ...]
    alignment_accession: str | None
    user_accession: str | None


def plan_chain(chain_auth: str, residues: list[dict[str, Any]], modified_count: int, pdb_id: str | None,
               user_accession: str | None, index: ReferenceIndex,
               max_cells: int = MAX_ALIGNMENT_CELLS) -> ChainPlan:
    """Decide the methods for one chain or raise ``NumberingInvalid`` (no usable method / fused chain + accession)."""
    if user_accession is not None and (index.uniprot.get(user_accession) or {}).get("status") != "ok":
        raise NumberingInvalid("accession_not_in_uniprot_snapshot",
                               "uniprot_accession is not an ok entry of the active UniProt snapshot", chain_auth)
    sifts_chain: sm.SiftsChain | None = None
    if pdb_id is None:
        sifts_reason: str | None = "pdb_id_not_given"
    else:
        found = index.sifts.lookup(pdb_id, chain_auth)
        if isinstance(found, sm.SiftsChain):
            sifts_chain, sifts_reason = found, None
        else:
            sifts_reason = found.reason_code
    accessions = tuple(sorted(sifts_chain.accessions)) if sifts_chain is not None else ()

    def too_large(accession: str) -> bool:
        return sa.alignment_too_large(len(residues), len(index.uniprot[accession]["sequence"]), max_cells)

    def plan(methods: tuple[str, ...], reason: str | None, align: str | None) -> ChainPlan:
        return ChainPlan(chain_auth, tuple(residues), modified_count, methods, reason,
                         sifts_chain if "sifts" in methods else None, accessions, align, user_accession)

    def no_method() -> NumberingInvalid:
        return NumberingInvalid("no_usable_method", "no numbering method is usable for this chain", chain_auth)

    if sifts_chain is None:
        if user_accession is None:
            raise no_method()
        if too_large(user_accession):
            raise no_method()
        return plan(("local_alignment",), sifts_reason, user_accession)
    if len(accessions) > 1:
        if user_accession is not None:
            raise NumberingInvalid("accession_with_multiple_sifts_accessions",
                                   "the chain maps to several SIFTS accessions; leave uniprot_accession empty",
                                   chain_auth)
        return plan(("sifts",), "multiple_sifts_accessions", None)
    sifts_accession = accessions[0]
    if user_accession is not None and user_accession != sifts_accession:
        if too_large(user_accession):
            raise no_method()
        return plan(("local_alignment",), "accession_differs_from_sifts", user_accession)
    entry = index.uniprot.get(sifts_accession)
    if entry is None:
        return plan(("sifts",), "sifts_accession_not_in_uniprot_snapshot", None)
    if entry["status"] != "ok":
        return plan(("sifts",), "sifts_accession_uniprot_lookup_failed", None)
    if too_large(sifts_accession):
        return plan(("sifts",), "alignment_too_large", None)
    return plan(("sifts", "local_alignment"), None, sifts_accession)


# ---------------------------------------------------------------------------------------------------------------
# SIFTS answers (spec 5.3)

def sifts_answers(residues: Iterable[Mapping[str, Any]], chain: sm.SiftsChain) -> tuple[list[dict[str, Any]], str]:
    """Per residue ``{"accession", "position"}`` or ``{"absent_reason"}``, and the residue key used for the chain."""
    rows = [r for r in chain.residues if r["entity_id"] in chain.segments]
    by_pdbe: dict[int, list[dict[str, Any]]] = {}
    by_author: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_pdbe.setdefault(row["pdbe_number"], []).append(row)
        if row["author_number"] is not None:
            by_author.setdefault((row["author_number"], row["icode"]), []).append(row)
    residues = list(residues)
    key = "label_and_author" if all(r["seq_label"] is not None for r in residues) else "author_only"
    answers = []
    for residue in residues:
        author_key = (residue["seq_auth"], residue["icode"])
        if residue["seq_label"] is not None:
            candidates = by_pdbe.get(residue["seq_label"], [])
            full = [r for r in candidates if (r["author_number"], r["icode"]) == author_key]
            partial = bool(candidates) or bool(by_author.get(author_key))
        else:
            full = by_author.get(author_key, [])
            partial = False
        if len(full) > 1:
            answers.append(absent("sifts_ambiguous_residue_row"))
            continue
        if not full:
            answers.append(absent("sifts_number_mismatch" if partial else "sifts_no_residue_row"))
            continue
        row = full[0]
        if not row["observed"]:
            answers.append(absent("sifts_not_observed"))
            continue
        found = chain.uniprot_position(row["entity_id"], row["pdbe_number"])
        answers.append(absent(sm.OUTSIDE_SEGMENTS) if found is None
                       else {"accession": found[0], "position": found[1]})
    return answers, key


# ---------------------------------------------------------------------------------------------------------------
# alignment answers (spec 5.4)

def alignment_sequence(uniprot_sequence: str) -> str:
    """UniProt letters outside the BLOSUM62 alphabet (U, O, ...) become ``X`` for alignment only."""
    return "".join(c if c in _ALIGN_ALPHABET else "X" for c in uniprot_sequence)


def chain_reasons(identity_pct: float | None, coverage_pct: float | None,
                  min_identity: float = MIN_IDENTITY_PCT, min_coverage: float = MIN_COVERAGE_PCT) -> list[str]:
    reasons = []
    if identity_pct is None or identity_pct < min_identity:
        reasons.append("alignment_below_identity")
    if coverage_pct is None or coverage_pct < min_coverage:
        reasons.append("alignment_below_coverage")
    return reasons


def alignment_answers(residues: Iterable[Mapping[str, Any]], accession: str,
                      uniprot_sequence: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    residues = list(residues)
    structure_seq = "".join(sa.to_one_letter(r["resname"]) for r in residues)
    result = sa.align_global(structure_seq, alignment_sequence(uniprot_sequence))
    reasons = chain_reasons(result.identity_pct, result.coverage_pct)
    info = {"accession": accession, "identity_pct": result.identity_pct, "coverage_pct": result.coverage_pct,
            "aligned_pairs": result.aligned_pairs, "identical": result.identical,
            "chain_residue_count": len(residues), "score": result.score, "chain_reason": reasons,
            "ambiguous_residue_count": len(result.ambiguous_positions),
            "aligned_strings": {"structure": result.aligned_structure, "uniprot": result.aligned_uniprot}}
    if reasons:
        return info, [absent(*reasons) for _ in residues]
    ambiguous = set(result.ambiguous_positions)
    return info, [absent("alignment_ambiguous") if k in ambiguous else
                  absent("alignment_gap") if p is None else {"accession": accession, "position": p}
                  for k, p in enumerate(result.structure_to_uniprot)]


# ---------------------------------------------------------------------------------------------------------------
# row status (spec 5.5)

def row_status(sifts: Mapping[str, Any] | None, alignment: Mapping[str, Any] | None) -> tuple[str, dict | None,
                                                                                              str | None]:
    """``(status, agreed {"accession","position"} | None, conflict_reason)``; ``None`` means the method did not run."""
    answers = [a for a in (sifts, alignment) if a is not None]
    if not answers:
        raise ValueError("at least one method must have run")
    given = [a for a in answers if "position" in a]
    if len(answers) == 1:
        return ("mapped", dict(given[0]), None) if given else ("unmapped", None, None)
    if len(given) == 2:
        same = (given[0]["accession"], given[0]["position"]) == (given[1]["accession"], given[1]["position"])
        return ("mapped", dict(given[0]), None) if same else ("conflict", None, "positions_differ")
    if len(given) == 1:
        return "conflict", None, "one_method_only"
    return "unmapped", None, None


# ---------------------------------------------------------------------------------------------------------------
# full computation

def _klifs_table(accession: str, index: ReferenceIndex) -> dict[str, Any]:
    entries = index.klifs.get(accession, [])
    sequence = (index.uniprot.get(accession) or {}).get("sequence")
    table = klifs_table(accession, entries, sequence if sequence is not None else "")
    if table["absent_reason"] is None and sequence is None:
        table = {**table, "absent_reason": "uniprot_sequence_unavailable", "positions": {},
                 "unresolved_regions": [], "gapped_regions": []}
    return table


def _segment_record(segment: sm.SiftsSegment) -> dict[str, Any]:
    return {"accession": segment.accession, "entity_id": segment.entity_id, "pdbe_start": segment.pdbe_start,
            "pdbe_end": segment.pdbe_end, "unp_start": segment.unp_start, "unp_end": segment.unp_end,
            "identity": segment.identity, "coverage": segment.coverage}


def snapshot_set_record(pinned: rs.PinnedSet) -> dict[str, Any]:
    manifest = pinned.manifest
    return {"set_hash": pinned.set_hash, "origin": rs.ORIGIN,
            "sources": [{"source": s["source"], "snapshot_id": s["snapshot_id"], "date": s["date"],
                         "version_hint": s["version_hint"], "license": s["license"],
                         "file_sha256s": {f["name"]: f["sha256"] for f in s["files"]}}
                        for s in manifest["sources"]]}


def alignment_params() -> dict[str, Any]:
    return {"matrix": "BLOSUM62", "gap_open": -sa.GAP_OPEN, "gap_extend": -sa.GAP_EXTEND,
            "gap_cost": "open + extend * (length - 1)", "end_gaps": "penalized", "tie_break": sa.TIE_BREAK,
            "implementation": sa.IMPLEMENTATION_VERSION, "min_identity_pct": MIN_IDENTITY_PCT,
            "min_coverage_pct": MIN_COVERAGE_PCT, "max_alignment_cells": MAX_ALIGNMENT_CELLS}


def build_map(*, structure_handle: str, structure_kind: str, model_number: int, pdb_id: str | None,
              plans: Iterable[ChainPlan], pinned: rs.PinnedSet, index: ReferenceIndex) -> dict[str, Any]:
    """The ``residue_numbering_map@1`` content (deterministic for the same inputs and set)."""
    chains_out: list[dict[str, Any]] = []
    rows_out: list[dict[str, Any]] = []
    klifs_tables: dict[str, dict[str, Any]] = {}
    uniprot_used: set[str] = set()
    sifts_used: list[dict[str, Any]] = []
    for plan in plans:
        residues = list(plan.residues)
        n = len(residues)
        s_answers: list[dict[str, Any] | None] = [None] * n
        a_answers: list[dict[str, Any] | None] = [None] * n
        sifts_info = alignment_info = None
        if plan.sifts_chain is not None:
            chain = plan.sifts_chain
            answers, residue_key = sifts_answers(residues, chain)
            # A SIFTS position beyond the snapshot's UniProt sequence is never an answer (sequence known only).
            s_answers = []
            for answer in answers:
                sequence = (index.uniprot.get(answer.get("accession")) or {}).get("sequence")
                if "position" in answer and sequence is not None and answer["position"] > len(sequence):
                    answer = absent("sifts_position_outside_sequence")
                s_answers.append(answer)
            sifts_info = {"accessions": list(plan.sifts_accessions), "sifts_chain_match": SIFTS_CHAIN_MATCH,
                          "sifts_residue_key": residue_key}
            uniprot_used.update(plan.sifts_accessions)
            sifts_used.append({
                "pdb_id": chain.pdb_id, "chain_auth": chain.chain_auth,
                "segments": [_segment_record(s) for group in chain.segments.values() for s in group],
                "residues": [dict(r) for r in chain.residues if r["entity_id"] in chain.segments]})
        if plan.alignment_accession is not None:
            sequence = index.uniprot[plan.alignment_accession]["sequence"]
            alignment_info, answers = alignment_answers(residues, plan.alignment_accession, sequence)
            a_answers = list(answers)
            uniprot_used.add(plan.alignment_accession)
        counts = {"mapped": 0, "unmapped": 0, "conflict": 0}
        mapped_accessions: list[str] = []
        for residue, s_ans, a_ans in zip(residues, s_answers, a_answers, strict=True):
            status, agreed, conflict_reason = row_status(s_ans, a_ans)
            counts[status] += 1
            row = {"residue": dict(residue), "status": status, "uniprot_accession": None, "uniprot_position": None,
                   "uniprot_residue": None, "residue_match": None, "klifs_index": None, "klifs_label": None,
                   "klifs_match": None, "conflict_reason": conflict_reason, "sifts": s_ans, "alignment": a_ans}
            if agreed is not None:
                accession, position = agreed["accession"], agreed["position"]
                if accession not in mapped_accessions:
                    mapped_accessions.append(accession)
                uniprot_used.add(accession)
                sequence = (index.uniprot.get(accession) or {}).get("sequence")
                letter = sequence[position - 1] if sequence is not None and 1 <= position <= len(sequence) else None
                row.update(uniprot_accession=accession, uniprot_position=position, uniprot_residue=letter,
                           residue_match=(None if letter is None else
                                          residue["resname"] in sa.THREE_TO_ONE
                                          and sa.THREE_TO_ONE[residue["resname"]] == letter))
                if accession not in klifs_tables:
                    klifs_tables[accession] = _klifs_table(accession, index)
                label = klifs_tables[accession]["positions"].get(position)
                if label is not None:
                    row.update(klifs_index=label["klifs_index"], klifs_label=label["klifs_label"],
                               klifs_match=label["klifs_match"])
            rows_out.append(row)
        chains_out.append({
            "chain_auth": plan.chain_auth,
            "requested_uniprot_accession": plan.user_accession,
            "methods_run": list(plan.methods),
            "cross_check": len(plan.methods) == 2,
            "cross_check_absent_reason": plan.cross_check_absent_reason,
            "sifts": sifts_info,
            "alignment": alignment_info,
            "klifs": [{"accession": acc, "applied": klifs_tables[acc]["absent_reason"] is None,
                       "absent_reason": klifs_tables[acc]["absent_reason"],
                       "unresolved_regions": list(klifs_tables[acc]["unresolved_regions"]),
                       "gapped_regions": list(klifs_tables[acc]["gapped_regions"])} for acc in mapped_accessions],
            "residue_rule": {"rule": RESIDUE_RULE, "modified_residue_count": plan.modified_count},
            "counts": counts,
        })
    reference_rows = {
        "uniprot": [{"accession": acc, "status": index.uniprot[acc]["status"] if acc in index.uniprot else None,
                     "in_snapshot": acc in index.uniprot,
                     "sequence": (index.uniprot.get(acc) or {}).get("sequence")} for acc in sorted(uniprot_used)],
        "sifts": sifts_used,
        "klifs": [{"accession": acc, "entries": [{"kinase_ID": e.get("kinase_ID"), "name": e.get("name"),
                                                  "pocket": e.get("pocket")} for e in index.klifs.get(acc, [])]}
                  for acc in sorted(klifs_tables)],
    }
    mapped = sum(c["counts"]["mapped"] for c in chains_out)
    return {
        "schema": SCHEMA,
        "method_version": METHOD_VERSION,
        "structure": {"handle": structure_handle, "structure_kind": structure_kind, "model_number": model_number},
        "snapshot_set": snapshot_set_record(pinned),
        "pdb_id": pdb_id,
        "alignment_params": alignment_params(),
        "chains": chains_out,
        "reference_rows": reference_rows,
        "rows": rows_out,
        "null_result": mapped == 0,
        "limitations": LIMITATIONS,
    }
