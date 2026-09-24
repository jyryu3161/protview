"""Append-only event log — the single source of truth (plan §4.4, §9).

run.sqlite / index.sqlite are derived and may be deleted; events.jsonl may not.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterator, Literal

from .handles import canonical_json, sha256_hex

EventType = Literal[
    "run_started", "goal", "tool_called", "tool_succeeded", "tool_failed",
    "decision", "approval_requested", "approval_resolved", "egress", "llm_call",
    "checkpoint", "run_finished",
]
DecisionSource = Literal["rule", "jev", "frontier", "human"]


def normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Drop None, sort keys (canonical_json sorts). Floats kept as given."""
    return {k: v for k, v in sorted(args.items()) if v is not None}


def idempotency_key(tool: str, version: str, args: dict[str, Any]) -> str:
    return sha256_hex(canonical_json({"tool": tool, "v": version, "args": normalize_args(args)}))


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in self.read()) if self.path.exists() else 0

    def append(self, type: EventType, **data: Any) -> dict[str, Any]:
        self._seq += 1
        ev = {"seq": self._seq, "ts": time.time(), "type": type, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
        return ev

    def read(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return iter(())
        with self.path.open(encoding="utf-8") as f:
            return iter([json.loads(line) for line in f if line.strip()])

    def completed(self) -> dict[str, dict[str, Any]]:
        """idempotency_key -> tool_succeeded event (used to skip on resume)."""
        return {e["key"]: e for e in self.read() if e["type"] == "tool_succeeded"}
