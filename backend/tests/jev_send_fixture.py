"""Shared M24 T4 send fixtures: template runs with stored ``jev_projection@1`` objects, cloned per test.

Inputs:
* REAL M20 set: the unmodified cheap tool through ``Run.call`` on public 1UBQ (positions MET1, ILE44, LYS48) and two
  projections of it built by the real ``build_jev_projection`` tool; the same in a dry-run run.
* REAL M17 set: ``ligand_job_fixture.standard_run`` (real RDKit jobs on the labelled synthetic methacetin fixtures) and
  one projection of it.

Every HTTP exchange is an ``httpx.MockTransport`` and every credential the inert ``SENTINEL`` below; nothing here
opens a socket or reads ``.env``. A template run is built once per pytest process and each test gets an events-only
copy (``clone``) so it can append freely.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
from ligand_job_fixture import standard_run

from mw import jev_constants as J
from mw import jev_projection as P
from mw import jev_sends as S
from mw.egress.gate import EgressGate
from mw.workspace import new_run

FIX = Path(__file__).resolve().parent / "fixtures"
SENTINEL = "sentinel_m24_t4_key_do_not_store"
RAW_ERROR = "provider raw diagnostic m24 t4 do not store"
USAGE = {"input_tokens": 3000, "output_tokens": 20, "cost": 0.001}
_CACHE: dict[str, dict[str, Any]] = {}
_UNSET: Any = object()


def res(seq_auth: int, resname: str) -> dict[str, Any]:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq_auth, "icode": "", "resname": resname}


def _mutation_template(root: Path, run_id: str, *, dry_run: bool) -> dict[str, Any]:
    run = new_run(root, run_id=run_id, dry_run=dry_run)
    loaded = run.call("load_structure", {"source": str(FIX / "public_1ubq.cif"), "model_index": 0}).handle
    prepared = run.call("prepare_structure", {"structure": loaded}).handle
    source = run.call("generate_mutation_candidates", {
        "structure": prepared, "sources": {"pocket": None, "ligand_shell": None,
                                           "residues": [res(1, "MET"), res(44, "ILE"), res(48, "LYS")]}}).handle
    first = run.call(J.TOOL, {"source": source, "candidates": [30, 3, 0]}).handle
    second = run.call(J.TOOL, {"source": source, "candidates": [1, 2]}).handle
    return {"root": root, "run_id": run_id, "dry_run": dry_run, "kind": "mutation", "source": source,
            "prepared": prepared, "projection": first, "other_projection": second}


def _ligand_template(root: Path, run_id: str) -> dict[str, Any]:
    made = standard_run(root, run_id)
    run = made["run"]
    ids = [row["id"] for row in run.store.load(made["candidate_set"])["candidates"]]
    projection = run.call(J.TOOL, {"source": made["candidate_set"], "candidates": ids[:3]}).handle
    other = run.call(J.TOOL, {"source": made["candidate_set"], "candidates": ids[3:5]}).handle
    return {"root": root, "run_id": run_id, "dry_run": False, "kind": "ligand", "source": made["candidate_set"],
            "prepared": None, "projection": projection, "other_projection": other}


def templates(base: Path) -> dict[str, dict[str, Any]]:
    """Build (once per process) the mutation, dry-run mutation and ligand template runs."""
    key = str(base)
    if key not in _CACHE:
        base.mkdir(parents=True, exist_ok=True)
        _CACHE[key] = {
            "mutation": _mutation_template(base / "mut", "run_jev_send_mut", dry_run=False),
            "dry": _mutation_template(base / "dry", "run_jev_send_dry", dry_run=True),
            "ligand": _ligand_template(base / "lig", "run_jev_send_lig"),
        }
    return _CACHE[key]


def clone(template: dict[str, Any], root: Path) -> dict[str, Any]:
    """An events-only copy of a template run under ``root`` (same run id and handles)."""
    target = root / template["run_id"]
    target.mkdir(parents=True)
    shutil.copyfile(template["root"] / template["run_id"] / "events.jsonl", target / "events.jsonl")
    run = new_run(root, run_id=template["run_id"], dry_run=template["dry_run"])
    return {**template, "root": root, "run": run}


def reopen(world: dict[str, Any], root: Path | None = None) -> Any:
    """A fresh ``Run`` on the same run folder, or on an events-only copy under ``root``."""
    if root is not None:
        (root / world["run_id"]).mkdir(parents=True)
        shutil.copyfile(world["run"].run_dir / "events.jsonl", root / world["run_id"] / "events.jsonl")
    return new_run(root or world["root"], run_id=world["run_id"], dry_run=world["dry_run"])


class Fake:
    """A scripted MockTransport and a counting sentinel credential resolver."""

    def __init__(self, responder: Any = None, *, key: Any = SENTINEL) -> None:
        self.responder = responder or (lambda request: reply("m01"))
        self.requests: list[httpx.Request] = []
        self.key_reads = 0
        self.key = key
        self.gate = EgressGate(transport=httpx.MockTransport(self._handle), credential_resolver=self._resolve)

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        out = self.responder(request)
        return await out if inspect.isawaitable(out) else out

    def _resolve(self) -> Any:
        self.key_reads += 1
        if isinstance(self.key, BaseException):
            raise self.key
        return self.key


def reply(choice: str = "m01", *, model: Any = J.SERVED_SNAPSHOT, usage: Any = USAGE, status: int = 200,
          answer: dict[str, Any] | None = None, answers: dict[str, Any] | None = None,
          drop_model: bool = False, **extra: Any) -> httpx.Response:
    """A provider-shaped JSON reply (fixture, never a real provider output)."""
    body: dict[str, Any] = {"answers": answers if answers is not None else
                            {J.QUESTION_KEY: answer if answer is not None else
                             {"type": "choice", "choice": choice, **extra}}}
    if not drop_model:
        body["model"] = model
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status, json=body)


def new_send_id() -> str:
    return str(uuid.uuid4())


def projection_of(world: dict[str, Any], which: str = "projection") -> dict[str, Any]:
    return world["run"].store.load(world[which])


def body_of(world: dict[str, Any], which: str = "projection") -> bytes:
    return P.projection_body(projection_of(world, which))[1]


def send(world: dict[str, Any], fake: Fake, *, which: str = "projection", send_id: Any = _UNSET,
         **overrides: Any) -> dict[str, Any]:
    """One approved send through ``jev_sends.run_send`` (the T5 route will wrap exactly this call)."""
    request = {"send_id": new_send_id() if send_id is _UNSET else send_id, "projection": world[which],
               "body_sha256": P.body_sha256(body_of(world, which)), "confirm": J.CONFIRM, **overrides}
    return asyncio.run(S.run_send(world["run"], fake.gate, **request))


def events(run: Any, kind: str | None = None) -> list[dict[str, Any]]:
    return [event for event in run.events.read() if kind is None or event["type"] == kind]


def audits(run: Any, audit_id: str | None = None) -> list[dict[str, Any]]:
    return [event for event in run.events.read() if event["type"] == "egress"
            and (audit_id is None or event["audit_id"] == audit_id)]


def run_bytes(run: Any) -> bytes:
    return b"".join(path.read_bytes() for path in sorted(run.run_dir.rglob("*")) if path.is_file())


def no_secret(*values: Any) -> bool:
    text = json.dumps(values, default=repr, sort_keys=True)
    return SENTINEL not in text and RAW_ERROR not in text
