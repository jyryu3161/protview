"""Test-only loopback API for the M25 JEV loop offscreen QA: the real app with scripted science-gate replies.

The product app (``mw.api.app``) runs unchanged on 127.0.0.1 except for its two module-global egress gates and the
default arguments of ``EgressGate`` (the M24 fixture server's way, ``backend/tests/offscreen_jev_fixture/server.py``):
``SCIENCE_GATE`` becomes an ``EgressGate`` over an in-process ``httpx.MockTransport`` with a sentinel placeholder
credential; ``VIEWER_GATE`` and every gate built later with the default arguments (the M3 path builds one) get a
transport that refuses and a resolver that finds no credential and never reads ``.env``. Nothing here opens a
provider socket: every science "reply" is written by this file from the script named in the control folder, and is a
labeled fixture, never a model decision.

Control folder (inside the QA root, given by ``--control``):
  script.json        {"script": <name>} read at each science request. A missing or unknown script fails the request
                     as a transport error (nothing is guessed).
  inflight.json      present only while a ``slow`` reply is held (the QA harness waits for it before acting).
  release            created by the QA harness to let a ``slow`` reply go (consumed when seen).
  calls.jsonl        one safe row per science request: the request body SHA-256 and byte count, the loop wire schema
                     and goal, the question keys, the alias, criteria (not-yet-computed) and computed alias counts,
                     whether the Authorization header carried the sentinel (boolean only), the script, the HTTP status
                     and the scripted reply (fixture content only). Never the body, a header value or a credential.
  credentials.json   how many times each credential resolver was called: ``sentinelReads`` (the science gate's
                     placeholder) and ``productResolverReads`` (the stand-in for the product's key resolver, which
                     returns no credential; it must stay 0). Counts only.
  server.json        written at start: which gates and defaults were replaced and the runs folder.

Scripts (spec 12, fixture phase): good (the first ``criteria`` key, i.e. the first not-yet-computed alias in the sent
order, with a confidence and per-criteria probabilities in the sent order), computed_alias (the first alias of the
wire's ``computed`` list: the gate refuses it, ``response_invalid``; no computed alias = transport error),
http_500 (HTTP 500 without usage), slow (waits for ``release`` up to 20 s, then answers as ``good``), no_usage (a valid
answer without usage), model_mismatch (another served model). Usage values are small labeled fixture numbers.

Run only with an explicit isolated runs directory (the QA root); this module is never imported by production.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import mw.api.app as product_api
from mw.egress.gate import EgressGate

SENTINEL = "m25-loop-fixture-sentinel-placeholder-not-a-key"
SERVED = "typesafe/jev-1.13-20260917"
OTHER_MODEL = "fixture/unexpected-model-snapshot"
SCRIPTS = ("good", "computed_alias", "http_500", "slow", "no_usage", "model_mismatch")
CONFIDENCE = 0.62
SLOW_WAIT_S = 20.0


def probabilities(aliases: list[str]) -> dict[str, float]:
    """Labeled fixture values in the sent order: weights ((i * 5) % 7) + 1, normalized, four decimals (unsorted)."""
    weights = [((index * 5) % 7) + 1 for index in range(len(aliases))]
    total = sum(weights)
    return {alias: round(weight / total, 4) for alias, weight in zip(aliases, weights, strict=True)}


def usage(body_bytes: int) -> dict[str, float | int]:
    """Small labeled fixture usage (well under any reservation; never a measurement)."""
    return {"input_tokens": 100 + body_bytes // 100, "output_tokens": 20, "cost": 0.0001}


def reply(script: str, criteria: list[str], computed: list[str], body_bytes: int) -> tuple[int, dict]:
    """The scripted HTTP status and JSON reply for one science request."""
    if script == "http_500":
        return 500, {"error": {"code": 500, "message": "fixture provider error"}}
    answer: dict = {"type": "choice", "choice": criteria[0], "confidence": CONFIDENCE,
                    "probabilities": probabilities(criteria)}
    if script == "computed_alias":
        answer["choice"] = computed[0]       # an alias that was sent but is not in criteria (already computed)
    payload: dict = {"model": OTHER_MODEL if script == "model_mismatch" else SERVED,
                     "answers": {"candidate_choice": answer}}
    if script != "no_usage":
        payload["usage"] = usage(body_bytes)
    return 200, payload


class Controller:
    def __init__(self, control: Path) -> None:
        self.control = control
        self.calls = 0
        self.reads = {"sentinelReads": 0, "productResolverReads": 0}
        self.write_reads()

    def write_reads(self) -> None:
        (self.control / "credentials.json").write_text(json.dumps({**self.reads, "updatedAt": datetime.now(
            UTC).isoformat()}, sort_keys=True) + "\n")

    def credential(self) -> str:
        self.reads["sentinelReads"] += 1
        self.write_reads()
        return SENTINEL

    def product_resolver(self) -> None:
        """Stands in for the product key resolver: counts the call, reads nothing, finds no credential."""
        self.reads["productResolverReads"] += 1
        self.write_reads()

    def script(self) -> str | None:
        try:
            name = json.loads((self.control / "script.json").read_text()).get("script")
        except (OSError, ValueError, AttributeError):
            return None
        return name if name in SCRIPTS else None

    async def released(self) -> bool:
        marker = self.control / "release"
        deadline = time.monotonic() + SLOW_WAIT_S
        while time.monotonic() < deadline:
            if marker.exists():
                marker.unlink(missing_ok=True)
                return True
            await asyncio.sleep(0.05)
        return False

    def record(self, row: dict) -> None:
        with (self.control / "calls.jsonl").open("a") as out:
            out.write(json.dumps(row, sort_keys=True) + "\n")

    async def transport(self, request: httpx.Request) -> httpx.Response:
        body = bytes(request.content)
        self.calls += 1
        row: dict = {"n": self.calls, "receivedAt": datetime.now(UTC).isoformat(), "path": request.url.path,
                     "bodySha256": hashlib.sha256(body).hexdigest(), "bodyBytes": len(body),
                     "authorizationIsSentinel": request.headers.get("authorization") == f"Bearer {SENTINEL}",
                     "sentinelReadsSoFar": self.reads["sentinelReads"]}
        script = self.script()
        row["script"] = script
        try:
            data = json.loads(body)
            state = data["state"]
            aliases = [item["alias"] for item in state["candidates"]]
            criteria = list(data["questions"]["candidate_choice"]["criteria"])
            computed = [item["alias"] for item in state.get("computed") or []]
            row.update(stateSchema=state.get("schema"), goal=state.get("goal"),
                       questionKeys=sorted(data.get("questions") or {}), aliasCount=len(aliases),
                       criteria=criteria, computed=computed)
        except (ValueError, KeyError, TypeError):
            aliases, criteria, computed = [], [], []
        if script is None or not criteria or (script == "computed_alias" and not computed):
            row.update(status=None, outcome="transport_error")
            self.record(row)
            raise httpx.ConnectError("fixture: no valid script, no criteria or no computed alias for the script")
        if script == "slow":
            inflight = self.control / "inflight.json"
            inflight.write_text(json.dumps({"n": self.calls, "script": script}) + "\n")
            try:
                row["released"] = await self.released()
            finally:
                inflight.unlink(missing_ok=True)
        status, payload = reply(script, criteria, computed, len(body))
        row.update(status=status, response=payload, answeredAt=datetime.now(UTC).isoformat())
        self.record(row)
        return httpx.Response(status, json=payload)


async def refuse(_request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("fixture: only the scripted science gate answers in the M25 loop fixture server")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("fixture port must be in 1024..65535")
    runs, control = args.runs_dir.resolve(), args.control.resolve()
    repo_runs = BACKEND.parent / "runs"
    for path in (runs, control):
        if str(path).startswith(("/tmp/", "/private/tmp/")) or path in (repo_runs, BACKEND.parent):
            parser.error(f"use an isolated QA folder (not /tmp, not the repository runs/ folder itself): {path}")
    runs.mkdir(parents=True, exist_ok=True)
    control.mkdir(parents=True, exist_ok=True)
    controller = Controller(control)
    # Any gate built later with the default arguments refuses and reads no credential (never .env).
    EgressGate.__init__.__kwdefaults__.update(transport=httpx.MockTransport(refuse),
                                              credential_resolver=controller.product_resolver)
    product_api.RUNS_DIR = runs
    product_api.SCIENCE_GATE = EgressGate(transport=httpx.MockTransport(controller.transport),
                                          credential_resolver=controller.credential)
    product_api.VIEWER_GATE = EgressGate(transport=httpx.MockTransport(refuse),
                                         credential_resolver=controller.product_resolver)
    (control / "server.json").write_text(json.dumps({
        "schema": "m25_jev_loop_fixture_server@1", "fixture": True, "pid": os.getpid(), "port": args.port,
        "runsDir": str(runs), "scienceGate": "EgressGate(httpx.MockTransport scripted, sentinel credential)",
        "viewerGate": "EgressGate(httpx.MockTransport refusing, no credential)",
        "defaultGate": "EgressGate defaults: httpx.MockTransport refusing, resolver without a credential",
        "scripts": list(SCRIPTS), "startedAt": datetime.now(UTC).isoformat()}, indent=2) + "\n")
    uvicorn.run(product_api.app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
