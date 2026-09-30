"""KLIFS 85-residue pocket -> UniProt position table. Pure functions, standard library only.

Input is already-parsed data: the KLIFS ``kinases.jsonl`` rows for one UniProt accession and that
accession's UniProt canonical sequence. Nothing here reads files, structures or the network.

Region boundaries and label spellings (``I``, ``g.l``, ..., ``αC``, ..., ``a.l``) were checked against every
``KLIFS_position`` value in the KLIFS 2026-09-19 snapshot ``match_residues.jsonl`` (label = ``<region>.<index>``).

Accession-level outcome (``absent_reason``):
- ``accession_not_in_klifs``: no KLIFS row for the accession.
- ``klifs_multiple_entries``: more than one KLIFS row (e.g. two kinase domains); no labels at all.
- ``klifs_pocket_empty``: the single row's pocket is null, ``""`` or only gap characters.
- ``None``: the table was applied (it may still have unresolved regions).

Placement and uniqueness (definition):
1. Each region is split on the gap characters ``-``/``_`` into contiguous fragments. Gap positions get no
   number. A region made only of gaps has nothing to place and is neither numbered nor listed as unresolved.
2. A region whose fragments do not all occur somewhere in the sequence (exact, case-sensitive substring) is
   unresolved and is removed from the ordering chain (it constrains nothing).
3. The fragments of the remaining regions, in region order then fragment order, form one chain. A chain
   assignment picks one occurrence per fragment such that each fragment starts at or after the end of the
   previous fragment in the chain (no overlap, any number of residues in between, including zero).
4. An occurrence is *feasible* when it belongs to at least one complete chain assignment. This is computed
   exactly with one forward pass (start >= the smallest end of a forward-feasible occurrence of the previous
   fragment) and one backward pass (end <= the largest start of a backward-feasible occurrence of the next
   fragment); an occurrence is feasible iff it passes both.
5. A region is resolved iff every one of its fragments has exactly one feasible occurrence, i.e. the region
   has exactly one placement over all order-consistent assignments. Otherwise the whole region is unresolved.
   If no complete assignment exists, every region in the chain is unresolved.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

POCKET_LENGTH = 85
GAP_CHARS = frozenset("-_")

# (region label, first KLIFS index, last KLIFS index), 1-based inclusive
KLIFS_REGIONS: tuple[tuple[str, int, int], ...] = (
    ("I", 1, 3),
    ("g.l", 4, 9),
    ("II", 10, 13),
    ("III", 14, 19),
    ("αC", 20, 30),
    ("b.l", 31, 37),
    ("IV", 38, 41),
    ("V", 42, 44),
    ("GK", 45, 45),
    ("hinge", 46, 48),
    ("linker", 49, 52),
    ("αD", 53, 59),
    ("αE", 60, 64),
    ("VI", 65, 67),
    ("c.l", 68, 75),
    ("VII", 76, 78),
    ("VIII", 79, 79),
    ("xDFG", 80, 83),
    ("a.l", 84, 85),
)

ABSENT_REASONS = ("accession_not_in_klifs", "klifs_pocket_empty", "klifs_multiple_entries")


def parse_kinases_jsonl(text: str) -> list[dict[str, Any]]:
    """Parse KLIFS ``kinases.jsonl`` text into row dicts (blank lines ignored)."""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def index_kinases_by_uniprot(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group KLIFS kinase rows by their ``uniprot`` accession, keeping file order. Rows without one are skipped."""
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        accession = row.get("uniprot")
        if isinstance(accession, str) and accession:
            index.setdefault(accession, []).append(dict(row))
    return index


def _fragments(pocket: str, start: int, end: int) -> list[tuple[str, int]]:
    """Contiguous non-gap runs of pocket[start..end] (1-based) as (text, first KLIFS index)."""
    out: list[tuple[str, int]] = []
    run_start = None
    for idx in range(start, end + 2):
        is_residue = idx <= end and pocket[idx - 1] not in GAP_CHARS
        if is_residue and run_start is None:
            run_start = idx
        elif not is_residue and run_start is not None:
            out.append((pocket[run_start - 1:idx - 1], run_start))
            run_start = None
    return out


def _occurrences(sequence: str, text: str) -> list[int]:
    """All 0-based starts of ``text`` in ``sequence``, overlapping occurrences included, ascending."""
    starts = []
    i = sequence.find(text)
    while i != -1:
        starts.append(i)
        i = sequence.find(text, i + 1)
    return starts


def _empty(accession: str, reason: str | None) -> dict[str, Any]:
    return {"accession": accession, "absent_reason": reason, "positions": {}, "unresolved_regions": []}


def klifs_table(accession: str, klifs_entries_for_accession: list[Mapping[str, Any]],
                uniprot_sequence: str) -> dict[str, Any]:
    """Map UniProt positions to KLIFS pocket indexes for one accession.

    Returns ``{"accession", "absent_reason", "positions", "unresolved_regions"}`` where ``positions`` maps a
    1-based UniProt position (int) to ``{"klifs_index": 1..85, "klifs_label": "<region>.<index>"}`` and
    ``unresolved_regions`` lists region labels in KLIFS order. See the module docstring for the rules.
    """
    entries = list(klifs_entries_for_accession)
    for entry in entries:
        if entry.get("uniprot") != accession:
            raise ValueError("KLIFS entry belongs to a different accession")
    if not entries:
        return _empty(accession, "accession_not_in_klifs")
    if len(entries) > 1:
        return _empty(accession, "klifs_multiple_entries")
    pocket = entries[0].get("pocket")
    if pocket is None or pocket == "":
        return _empty(accession, "klifs_pocket_empty")
    if not isinstance(pocket, str) or len(pocket) != POCKET_LENGTH:
        raise ValueError("KLIFS pocket must be an 85-character string")
    if any(not (ch.isalpha() and ch.isascii()) and ch not in GAP_CHARS for ch in pocket):
        raise ValueError("KLIFS pocket contains a character that is neither a residue letter nor a gap")
    if all(ch in GAP_CHARS for ch in pocket):
        return _empty(accession, "klifs_pocket_empty")
    if not isinstance(uniprot_sequence, str):
        raise TypeError("UniProt sequence must be a string")

    unresolved: set[str] = set()
    # chain of fragments: (region, text, first KLIFS index, occurrence starts)
    chain: list[tuple[str, str, int, list[int]]] = []
    for region, start, end in KLIFS_REGIONS:
        frags = _fragments(pocket, start, end)
        if not frags:
            continue
        occs = [_occurrences(uniprot_sequence, text) for text, _ in frags]
        if any(not o for o in occs):
            unresolved.add(region)
            continue
        chain.extend((region, text, first, o) for (text, first), o in zip(frags, occs, strict=True))

    # forward feasibility
    forward: list[list[int]] = []
    min_end = 0
    for _region, text, _first, occ in chain:
        ok = [s for s in occ if s >= min_end]
        forward.append(ok)
        min_end = (ok[0] + len(text)) if ok else len(uniprot_sequence) + 1
    # backward feasibility, intersected with forward
    feasible: list[list[int]] = [[] for _ in chain]
    max_start = len(uniprot_sequence)
    for j in range(len(chain) - 1, -1, -1):
        text = chain[j][1]
        back = [s for s in chain[j][3] if s + len(text) <= max_start]
        max_start = back[-1] if back else -1
        fwd = set(forward[j])
        feasible[j] = [s for s in back if s in fwd]

    placement: dict[str, list[tuple[str, int, int]]] = {}
    for (region, text, first, _occ), options in zip(chain, feasible, strict=True):
        if len(options) != 1:
            unresolved.add(region)
            continue
        placement.setdefault(region, []).append((text, first, options[0]))

    positions: dict[int, dict[str, Any]] = {}
    for region, _start, _end in KLIFS_REGIONS:
        if region in unresolved or region not in placement:
            continue
        for text, first, seq_start in placement[region]:
            for offset in range(len(text)):
                klifs_index = first + offset
                positions[seq_start + offset + 1] = {"klifs_index": klifs_index,
                                                     "klifs_label": f"{region}.{klifs_index}"}
    return {
        "accession": accession,
        "absent_reason": None,
        "positions": dict(sorted(positions.items())),
        "unresolved_regions": [r for r, _s, _e in KLIFS_REGIONS if r in unresolved],
    }
