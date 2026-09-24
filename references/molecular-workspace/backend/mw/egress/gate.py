"""Egress Gate (plan §6, v0.6 §B).

EVERY outbound payload — OpenRouter calls AND structure/sequence fetches from
public databases — passes through here. The sanitized payload is logged verbatim.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal

EgressMode = Literal["online", "local_only", "dry_run"]

BLOCKED_KEYS = {"coords", "coordinates", "xyz", "atoms", "sequence", "seq", "fasta",
                "file_path", "path", "filename", "file_name", "pdb_text", "cif_text"}
AA = set("ACDEFGHIKLMNPQRSTVWYX")
PATH_RE = re.compile(r"(^|[\s\"'])(/|~/|[A-Za-z]:\\)[^\s\"']+|\.(pdb|cif|mmcif|ent|sdf|mol2|fasta|fa)\b", re.I)


class EgressDenied(Exception):
    pass


def _looks_like_sequence(s: str) -> bool:
    t = s.replace("\n", "").replace(" ", "").upper()
    return len(t) >= 30 and set(t) <= AA


def _looks_like_coords(v: Any) -> bool:
    return (isinstance(v, list) and len(v) >= 3 and all(
        isinstance(x, list) and len(x) == 3 and all(isinstance(c, (int, float)) for c in x) for x in v[:3]))


class EgressGate:
    def __init__(self, log_path: Path, mode: EgressMode = "local_only",
                 allow_sequence: bool = False) -> None:
        self.log_path = Path(log_path)
        self.mode = mode
        self.allow_sequence = allow_sequence

    def sanitize(self, payload: Any) -> tuple[Any, list[str]]:
        blocked: list[str] = []

        def walk(v: Any, path: str) -> Any:
            if isinstance(v, dict):
                out = {}
                for k, x in v.items():
                    p = f"{path}.{k}" if path else k
                    if k.lower() in BLOCKED_KEYS and not (self.allow_sequence and k.lower() in {"sequence", "seq"}):
                        blocked.append(p)
                        continue
                    out[k] = walk(x, p)
                return out
            if _looks_like_coords(v):
                blocked.append(path + "[coords]")
                return "[blocked:coords]"
            if isinstance(v, list):
                return [walk(x, f"{path}[{i}]") for i, x in enumerate(v)]
            if isinstance(v, str):
                if _looks_like_sequence(v) and not self.allow_sequence:
                    blocked.append(path + "[sequence]")
                    return "[blocked:sequence]"
                if PATH_RE.search(v):
                    blocked.append(path + "[path]")
                    return PATH_RE.sub(" [blocked:path]", v)
            return v

        return walk(payload, ""), blocked

    def send(self, destination: str, payload: Any, *, purpose: str) -> dict[str, Any]:
        """Sanitize + log. Returns the payload that may leave the process.

        Raises EgressDenied in local_only / dry_run modes; callers fall back to rules.
        """
        clean, blocked = self.sanitize(payload)
        allowed = self.mode == "online"
        self._log({"destination": destination, "purpose": purpose, "mode": self.mode,
                   "sent": allowed, "blocked_fields": blocked, "payload": clean})
        if not allowed:
            raise EgressDenied(f"egress mode is {self.mode}")
        return clean

    def fetch(self, url: str, *, purpose: str) -> None:
        """Record an outbound fetch (RCSB, AFDB, UniProt). The ID in the URL leaves too."""
        allowed = self.mode == "online"
        self._log({"destination": url, "purpose": purpose, "mode": self.mode, "sent": allowed,
                   "kind": "fetch"})
        if not allowed:
            raise EgressDenied(f"fetch blocked in {self.mode}")

    def _log(self, rec: dict[str, Any]) -> None:
        rec["ts"] = time.time()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
