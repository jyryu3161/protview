"""Versioned prompt registry (v0.6 §A3).

prompts/<id>@<version>.md with a YAML front matter block. The rendered text's
sha256 is recorded on every llm_call event, so a prompt change is visible in the log.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from ..core.handles import sha256_hex

FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptTemplate(BaseModel):
    id: str
    version: str
    role: str
    output_schema: str | None = None
    body: str

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def template_sha(self) -> str:
        return sha256_hex(self.body.encode())[:12]

    def render(self, **vars: Any) -> tuple[str, str]:
        missing = set(VAR.findall(self.body)) - set(vars)
        if missing:
            raise KeyError(f"{self.ref} missing vars: {sorted(missing)}")
        text = VAR.sub(lambda m: str(vars[m.group(1)]), self.body)
        return text, sha256_hex(text.encode())[:12]


class PromptRegistry:
    def __init__(self, root: Path) -> None:
        self.items: dict[str, PromptTemplate] = {}
        for p in sorted(Path(root).glob("*.md")):
            m = FM.match(p.read_text(encoding="utf-8"))
            if not m:
                continue
            meta = yaml.safe_load(m.group(1))
            t = PromptTemplate(body=m.group(2).strip() + "\n", **meta)
            self.items[t.ref] = t

    def get(self, ref: str) -> PromptTemplate:
        if "@" not in ref:  # latest version
            cands = sorted((t for t in self.items.values() if t.id == ref), key=lambda t: t.version)
            if not cands:
                raise KeyError(ref)
            return cands[-1]
        return self.items[ref]
