"""Failure taxonomy (plan §4.1).

Every tool failure MUST be one of these six classes. An empty scientific result
is NOT a failure: return a ToolResult with ``null_result=True`` instead of raising.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class FailureClass(str, Enum):
    transient = "transient"                  # retry with backoff (max 3)
    input_invalid = "input_invalid"          # fix args, retry once, then human
    precondition = "precondition"            # run the declared prerequisite, retry once
    resource_exceeded = "resource_exceeded"  # never retry; suggest smaller params
    fatal = "fatal"                          # stop, ask human


class Fix(BaseModel):
    """The next action a failure suggests. Rendered by the UI's ToolError."""
    tool: str
    args: dict[str, Any]


class ToolFailure(Exception):
    def __init__(self, cls: FailureClass, message: str, fix: Fix | None = None,
                 detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.cls = cls
        self.message = message
        self.fix = fix
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": self.cls.value,
            "message": self.message,
            "fix": self.fix.model_dump() if self.fix else None,
            "detail": self.detail,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"ToolFailure({self.cls.value}: {self.message})"
