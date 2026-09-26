"""Test-only loopback API with an injected in-process Jev transport fixture.

Run only with an explicit isolated runs directory. No real provider socket or
credential resolver is used. This module is never imported by production.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import mw.api.app as product_api
from mw.egress.gate import EgressGate


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["apply", "clarify", "unsupported", "invalid_choice", "wrong_model",
                  "http_error", "transport_error", "timeout"] = "apply"
    hold: bool = False
    delay_ms: int = Field(default=0, ge=0, le=5000)
    representation: Literal["keep", "cartoon", "ball_and_stick", "surface"] = "surface"
    selection: str = "keep"
    camera: Literal["keep", "focus_selected", "zoom_in", "zoom_out", "reset"] = "keep"
    key_available: bool = True


class Controller:
    def __init__(self) -> None:
        self.scenario = Scenario()
        self.release = asyncio.Event()
        self.calls = 0
        self.inflight = 0
        self.last_safe: dict[str, object] | None = None

    def credential(self) -> str | None:
        return "fixture-placeholder-only" if self.scenario.key_available else None

    async def transport(self, request: httpx.Request) -> httpx.Response:
        # Never record Authorization, raw prompt, raw catalog, coordinates or bytes.
        state = json.loads(request.content)
        self.last_safe = {"path": request.url.path, "model": state.get("model"),
                          "state_schema": state.get("state", {}).get("schema"),
                          "catalog_count": len(state.get("state", {}).get("catalog", [])),
                          "question_ids": sorted(state.get("questions", {}))}
        self.calls += 1
        self.inflight += 1
        scenario = self.scenario.model_copy(deep=True)
        release = self.release
        try:
            if scenario.hold:
                await release.wait()
            if scenario.delay_ms:
                await asyncio.sleep(scenario.delay_ms / 1000)
            if scenario.mode == "timeout":
                await asyncio.sleep(20)
            if scenario.mode == "transport_error":
                raise httpx.ConnectError("fixture transport unavailable")
            if scenario.mode == "http_error":
                return httpx.Response(503, json={"error": "fixture_unavailable"})
            answers = {name: {"type": "choice", "choice": choice} for name, choice in {
                "disposition": ("clarify" if scenario.mode == "clarify" else
                                "unsupported" if scenario.mode == "unsupported" else "apply"),
                "representation": scenario.representation,
                "selection": scenario.selection,
                "camera": scenario.camera,
            }.items()}
            if scenario.mode == "invalid_choice":
                answers["selection"]["choice"] = []
            return httpx.Response(200, json={
                "model": ("fixture/unexpected-snapshot" if scenario.mode == "wrong_model"
                          else "typesafe/jev-1.13-20260917"),
                "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 20, "cost": 0.001},
            })
        finally:
            self.inflight -= 1


controller = Controller()
product_api.VIEWER_GATE = EgressGate(transport=httpx.MockTransport(controller.transport),
                                     credential_resolver=controller.credential)
fixture_app = FastAPI(title="ProtView test-only viewer transport fixture")


@fixture_app.post("/__fixture/scenario")
async def configure(scenario: Scenario) -> dict[str, object]:
    controller.scenario = scenario
    controller.release = asyncio.Event()
    return {"mode": scenario.mode, "hold": scenario.hold}


@fixture_app.post("/__fixture/release")
async def release() -> dict[str, bool]:
    controller.release.set()
    return {"released": True}


@fixture_app.get("/__fixture/status")
async def status() -> dict[str, object]:
    return {"fixture": True, "calls": controller.calls, "inflight": controller.inflight,
            "mode": controller.scenario.mode, "last_safe_request": controller.last_safe}


fixture_app.mount("/", product_api.app)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--runs-dir", type=Path, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("fixture port must be in 1024..65535")
    runs = args.runs_dir.resolve()
    if BACKEND.parent in runs.parents or runs == BACKEND.parent:
        parser.error("fixture runs directory must be outside the product repository")
    runs.mkdir(parents=True, exist_ok=True)
    product_api.RUNS_DIR = runs
    uvicorn.run(fixture_app, host="127.0.0.1", port=args.port, log_level="warning",
                access_log=False)


if __name__ == "__main__":
    main()
