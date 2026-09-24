"""Residue identifier convention (plan §5.4).

Internal canonical form is LABEL-based; what humans and models see is AUTH-based.
`uid` is for display/logs only — never parse it.
"""
from __future__ import annotations

from pydantic import BaseModel


class ResidueRef(BaseModel):
    chain_auth: str
    seq_auth: int
    icode: str = ""
    chain_label: str
    seq_label: int | None = None     # None for non-polymer entities
    resname: str

    @property
    def uid(self) -> str:
        return f"{self.chain_auth}/{self.seq_auth}{self.icode}"

    @property
    def key(self) -> tuple[str, int | None, str]:
        """Canonical identity used for joins across adapters."""
        return (self.chain_label, self.seq_label, self.resname)

    def display(self) -> str:
        return f"{self.resname} {self.uid}"
