"""Lossless residue identity across PDB and mmCIF.

Label identifiers may be unknown. `uid` is display-only and must never be parsed.
"""
from __future__ import annotations

from pydantic import BaseModel


class ResidueRef(BaseModel):
    model_number: int
    chain_auth: str
    seq_auth: int
    icode: str = ""
    chain_label: str | None = None
    seq_label: int | None = None     # None for non-polymer entities
    resname: str

    @property
    def uid(self) -> str:
        return f"{self.chain_auth}/{self.seq_auth}{self.icode}"

    @property
    def key(self) -> tuple[int, str, int, str, str | None, int | None, str]:
        """Lossless identity; unknown labels cannot merge distinct author IDs."""
        return (self.model_number, self.chain_auth, self.seq_auth, self.icode,
                self.chain_label, self.seq_label, self.resname)

    def display(self) -> str:
        return f"{self.resname} {self.uid} (model {self.model_number})"
