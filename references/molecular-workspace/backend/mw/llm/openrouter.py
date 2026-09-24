"""OpenRouter adapter (plan §7, v0.6 §C).

Plain HTTP (no SDK). Every request goes through the EgressGate first.
- Model pins: fallbacks OFF for pinned roles; the served `model` is checked on every response.
- Provider policy defaults: data_collection=deny, zdr=true, require_parameters for structured output.
- Response cache keyed by sha256(model, messages, params).
- HTTP status -> FailureClass.
The API key is read from the OS keychain (keyring) or env var; it is never logged.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from ..core.errors import FailureClass, ToolFailure
from ..core.handles import canonical_json, sha256_hex
from ..egress.gate import EgressGate

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class ProviderPolicy(BaseModel):
    data_collection: str = "deny"
    zdr: bool = True
    require_parameters: bool = True
    allow_fallbacks: bool = False
    order: list[str] | None = None
    ignore: list[str] | None = None
    sort: str | None = None
    max_price: dict[str, float] | None = None

    def to_request(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class RoleConfig(BaseModel):
    role: str                      # "jev" | "frontier"
    model: str                     # pinned id, e.g. from config/default.yaml
    fallback_models: list[str] = []  # only honored if provider.allow_fallbacks
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout_s: float = 60
    provider: ProviderPolicy = ProviderPolicy()


class LLMResult(BaseModel):
    content: str
    parsed: Any = None
    requested_model: str
    served_model: str
    served_matches_pin: bool
    usage: dict[str, Any] = {}
    cached: bool = False
    latency_s: float = 0.0


def status_to_failure(code: int) -> FailureClass:
    if code in (408, 429) or code >= 500:
        return FailureClass.transient
    if code == 402:
        return FailureClass.fatal            # out of credits -> human
    if code in (400, 422):
        return FailureClass.input_invalid
    if code in (401, 403):
        return FailureClass.fatal
    return FailureClass.fatal


def get_api_key() -> str:
    try:
        import keyring  # optional
        k = keyring.get_password("molecular-workspace", "openrouter")
        if k:
            return k
    except Exception:
        pass
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        raise ToolFailure(FailureClass.fatal, "OpenRouter API key not configured (keyring or OPENROUTER_API_KEY)")
    return k


class OpenRouterClient:
    def __init__(self, gate: EgressGate, cache_dir: Path, *, transport: httpx.BaseTransport | None = None,
                 api_key: str | None = None) -> None:
        self.gate = gate
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(transport=transport, timeout=60)
        self._api_key = api_key

    def build_body(self, cfg: RoleConfig, messages: list[dict[str, Any]],
                   response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
            "provider": cfg.provider.to_request(),
            "usage": {"include": True},
        }
        if cfg.provider.allow_fallbacks and cfg.fallback_models:
            body["models"] = [cfg.model, *cfg.fallback_models]
        if response_schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": response_schema.get("title", "output"),
                                                       "strict": True, "schema": response_schema}}
        return body

    def complete(self, cfg: RoleConfig, messages: list[dict[str, Any]], *,
                 response_schema: dict[str, Any] | None = None, purpose: str) -> LLMResult:
        body = self.build_body(cfg, messages, response_schema)
        clean = self.gate.send("openrouter:" + cfg.model, body, purpose=purpose)  # may raise EgressDenied
        key = sha256_hex(canonical_json({k: clean[k] for k in ("model", "messages", "temperature",
                                                                   "max_tokens", "response_format") if k in clean}))
        cpath = self.cache_dir / f"{key}.json"
        if cpath.exists():
            r = LLMResult(**json.loads(cpath.read_text()))
            r.cached = True
            return r
        t0 = time.time()
        try:
            resp = self._client.post(API_URL, json=clean, timeout=cfg.timeout_s, headers={
                "Authorization": f"Bearer {self._api_key or get_api_key()}",
                "X-Title": "Molecular Workspace",
            })
        except httpx.TimeoutException as e:
            raise ToolFailure(FailureClass.transient, f"openrouter timeout: {e}")
        except httpx.TransportError as e:
            raise ToolFailure(FailureClass.transient, f"openrouter transport error: {e}")
        if resp.status_code != 200:
            raise ToolFailure(status_to_failure(resp.status_code),
                              f"openrouter HTTP {resp.status_code}", detail={"body": resp.text[:500]})
        data = resp.json()
        content = data["choices"][0]["message"].get("content") or ""
        served = data.get("model", cfg.model)
        parsed = None
        if response_schema is not None:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                raise ToolFailure(FailureClass.input_invalid, "structured output is not valid JSON",
                                  detail={"content": content[:500]})
        r = LLMResult(content=content, parsed=parsed, requested_model=cfg.model, served_model=served,
                      served_matches_pin=(served == cfg.model), usage=data.get("usage", {}),
                      latency_s=time.time() - t0)
        cpath.write_text(r.model_dump_json())
        return r
