"""Legacy number-bag utility retained for prompt experiments.

This does not bind values to a specific handle, row, field or unit, and must not
be used as the M5 scientific report verifier.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel

UNITS = r"(Å²|Å\^2|A\^2|Å|REU|kcal/mol|%|°)"
NUM = re.compile(r"([−\-+]?\d+(?:[.,]\d+)?)\s*" + UNITS)
SENT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s*|\n+")


class SentenceVerdict(BaseModel):
    text: str
    numbers: list[tuple[float, str]] = []
    unmatched: list[tuple[float, str]] = []
    kept: bool = True


def _to_float(s: str) -> float:
    return float(s.replace("−", "-").replace(",", ""))


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.split(text) if s and s.strip()]


def verify(text: str, evidence: Iterable[float], rel_tol: float = 0.01, abs_tol: float | None = None) -> list[SentenceVerdict]:
    """evidence: every numeric value found in the handles the answer cites."""
    ev = list(evidence)
    out = []
    for s in split_sentences(text):
        nums = [(_to_float(n), u) for n, u in NUM.findall(s)]
        bad = []
        for v, u in nums:
            decimals = len(str(abs(v)).split(".")[1]) if "." in str(v) else 0
            tol = abs_tol if abs_tol is not None else max(0.5 * 10 ** (-decimals), abs(v) * rel_tol)
            if not any(abs(v - e) <= tol for e in ev):
                bad.append((v, u))
        out.append(SentenceVerdict(text=s, numbers=nums, unmatched=bad, kept=not bad))
    return out
