"""Test-only setup of the M25 JEV loop offscreen QA runs over the loopback API (no ``mw`` import).

Before the harness ``frontend/tests/offscreen/jev-loop-flow.cjs`` drives the screen, this makes the two runs it needs
with the M24 runner's way (``scripts/m24_offscreen_acceptance.py`` ``setup_runs``): fresh runs (``local_only``,
consent off), the same public and labelled synthetic fixture inputs, real cheap tools and real M17 jobs. Nothing here
creates a loop, a projection, a send or a loop computation (those are the harness's clicks).

  L (ligand)   public 1UBQ loaded for the viewer; the public prepared docking example receptor
               (``fixtures/chemical/prolif-vina-rec.pdb``), the public-derived parent SDF and the labelled synthetic
               small blocks imported; real M17 inspection + enumeration (site 22, fixed rules): 10 candidates. The
               run's first expensive-call approval is given here for the M17 jobs (as the M24 runner does).
  P (protein)  public 1UBQ loaded and prepared; a real M20 set at the 22 non-Ala residues with the most neighbors in
               the M24 oracle file (allowed residue A only: 22 candidates, so a 21st check can be refused); public 1MQ4
               loaded and prepared with a real M20 set at its 3 non-Ala residues with the most neighbors (1MQ4 does
               not pass the M7 preflight, so a protein loop over it is refused at creation); the labelled synthetic
               phenol SDF imported. No expensive call: the loop's first compute meets the first-call approval.

Writes ``--out`` (``m25_jev_loop_setup@1``): run ids, handles, the candidate counts and, for P, the candidate indices
of the 1UBQ set whose residue is not Gly, Pro or Cys (``modelPool``; the harness picks its protein pool from them).
Run against the fixture server only (``server.py`` in this folder); refuses a non-loopback ``--api``.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "backend/tests/fixtures"
UBQ = FIX / "public_1ubq.cif"
MQ4 = FIX / "public_1mq4.cif"
RECEPTOR = FIX / "chemical/prolif-vina-rec.pdb"
PARENT = FIX / "docking/public-derived-parent-record0.sdf"
BLOCKS = FIX / "ligand_ga/synthetic-ga-small-blocks.smi"
PHENOL = FIX / "mutation_model/synthetic-phenol-ligand.sdf"
NEIGHBORS = FIX / "jev/expected.json"
SITE_ATOM = 22                  # the parent's N-methyl carbon (M18/M19/M22/M24 fixture site)
LIGAND_CANDIDATES = 10          # the small pool of fixtures/ligand_ga (use_fixed, site 22)
UBQ_POSITIONS = 22
MQ4_POSITIONS = 3
NOT_MODELLED_HERE = {"GLY", "PRO", "CYS"}
JOB_TIMEOUT_S = 600


class Api:
    def __init__(self, base: str) -> None:
        host = urllib.parse.urlparse(base).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit("--api must be a loopback URL")
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, body: object = None, ctype: str = "application/json") -> tuple[int, object]:
        data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"content-type": ctype})
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw or b"null")
            except ValueError:
                return exc.code, raw.decode(errors="replace")

    def ok(self, label: str, method: str, path: str, body: object = None, ctype: str = "application/json",
           want: tuple[int, ...] = (200, 201)) -> dict:
        status, value = self.call(method, path, body, ctype)
        if status not in want or not isinstance(value, dict):
            raise RuntimeError(f"{label}: HTTP {status} {json.dumps(value)[:600]}")
        return value


def new_run(api: Api, goal: str) -> str:
    made = api.ok("new run", "POST", "/runs", {"goal": goal, "context": [], "dry_run": False, "egress": "local_only"})
    return made["run_id"]


def command(api: Api, run: str, tool: str, args: dict) -> dict:
    body = api.ok(tool, "POST", f"/runs/{run}/commands", {"tool": tool, "args": args})
    if body.get("ok") is not True:
        raise RuntimeError(f"{tool}: {json.dumps(body)[:600]}")
    return body["handle"]


def structure(api: Api, run: str, path: Path, prepare: bool) -> dict:
    upload = api.ok(f"upload {path.name}", "POST", f"/runs/{run}/uploads?filename={path.name}", path.read_bytes(),
                    "application/octet-stream")
    loaded = command(api, run, "load_structure", {"source": upload["upload_id"], "model_index": 0})
    return command(api, run, "prepare_structure", {"structure": loaded["handle"]}) if prepare else loaded


def imported(api: Api, run: str, kind: str, path: Path) -> str:
    body = api.ok(f"import {kind}", "POST", f"/runs/{run}/chemical/imports?kind={kind}&filename={path.name}",
                  path.read_bytes(), "application/octet-stream")
    return body["handle"]


def job(api: Api, run: str, protocol: str, args: dict) -> dict:
    """Submit, start (the run's first expensive-call approval when the server asks for it), wait for the end."""
    job_id = api.ok(f"{protocol} submit", "POST", f"/runs/{run}/jobs",
                    {"protocol_id": protocol, "args": args, "timeout_s": 120})["job_id"]
    status, started = api.call("POST", f"/runs/{run}/jobs/{job_id}/start")
    if status == 409 and isinstance(started, dict) and "approval" in started:
        api.ok(f"{protocol} approve", "POST", f"/runs/{run}/jobs/approve")
        api.call("POST", f"/runs/{run}/jobs/{job_id}/start")
    deadline = time.monotonic() + JOB_TIMEOUT_S
    value: dict = {}
    while time.monotonic() < deadline:
        value = api.ok(f"{protocol} read", "GET", f"/runs/{run}/jobs/{job_id}")
        if value.get("status") not in ("queued", "claimed", "running"):
            break
        time.sleep(1)
    if value.get("status") != "done":
        raise RuntimeError(f"{protocol}: job {job_id} ended {value.get('status')} {value.get('failure')}")
    return value


def top_residues(name: str, count: int) -> list[dict]:
    """The ``count`` non-Ala residues of ``name`` with the most neighbors in the M24 oracle file (ties: file order)."""
    rows = json.loads(NEIGHBORS.read_text())["structures"][name]["neighbor_counts"]
    ranked = [row for _, row in sorted(enumerate(rows), key=lambda item: (-item[1][4], item[0]))]
    picked = [row for row in ranked if row[3] != "ALA"][:count]
    return [{"model_number": 1, "chain_auth": chain, "seq_auth": seq, "icode": icode, "resname": resname}
            for chain, seq, icode, resname, _ in picked]


def mutation_set(api: Api, run: str, path: Path, name: str, count: int) -> dict:
    prepared = structure(api, run, path, prepare=True)
    made = command(api, run, "generate_mutation_candidates", {
        "structure": prepared["handle"], "sources": {"pocket": None, "ligand_shell": None,
                                                     "residues": top_residues(name, count)},
        "allowed_residues": ["A"]})
    handle = made["handle"]
    quoted = urllib.parse.quote(handle, safe="")
    page = api.ok("mutation rows", "GET", f"/runs/{run}/mutation_candidate_sets/{quoted}/candidates?offset=0&limit=100")
    rows = page["rows"]
    return {"handle": handle, "candidates": len(rows), "structure": prepared["handle"],
            "modelPool": [row["index"] for row in rows if row["residue"]["resname"] not in NOT_MODELLED_HERE],
            "inputs": {"structure": str(path.relative_to(REPO)), "positions": count, "allowed_residues": ["A"]}}


def ligand_run(api: Api) -> dict:
    run = new_run(api, "M25 JEV loop QA fixture L (ligand)")
    viewer = structure(api, run, UBQ, prepare=False)
    receptor = imported(api, run, "receptor", RECEPTOR)
    parent = imported(api, run, "ligand_sdf", PARENT)
    blocks = imported(api, run, "building_blocks_smiles", BLOCKS)
    inspected = job(api, run, "rdkit_inspect_v1", {"parent_sdf_handle": parent, "block_handles": [blocks]})
    enumerated = job(api, run, "rdkit_enumerate_v1", {"inspection_handle": inspected["artifacts"]["ligand_inspection"],
                                                      "site_atoms": [SITE_ATOM], "use_fixed": True})
    handle = enumerated["artifacts"]["ligand_candidate_set"]
    rows = api.ok("ligand rows", "GET", f"/runs/{run}/ligand/candidate_sets/rows?handle="
                  f"{urllib.parse.quote(handle, safe='')}&offset=0&limit=100")
    if rows["total"] != LIGAND_CANDIDATES:
        raise RuntimeError(f"ligand set has {rows['total']} candidates, expected {LIGAND_CANDIDATES}")
    return {"run": run, "viewerStructure": viewer["handle"], "receptor": receptor, "parent": parent,
            "ligandSet": {"handle": handle, "candidates": rows["total"],
                          "ids": [row["candidate"]["id"] for row in rows["rows"]]}}


def protein_run(api: Api) -> dict:
    run = new_run(api, "M25 JEV loop QA fixture P (protein)")
    ubq = mutation_set(api, run, UBQ, "1UBQ", UBQ_POSITIONS)
    if ubq["candidates"] < 21 or len(ubq["modelPool"]) < 3:
        raise RuntimeError(f"1UBQ set: {ubq['candidates']} candidates, {len(ubq['modelPool'])} model pool")
    mq4 = mutation_set(api, run, MQ4, "1MQ4", MQ4_POSITIONS)
    if mq4["candidates"] < 2:
        raise RuntimeError(f"1MQ4 set has {mq4['candidates']} candidates")
    return {"run": run, "ubqSet": ubq, "mq4Set": mq4, "phenol": imported(api, run, "ligand_sdf", PHENOL)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if str(out).startswith(("/tmp/", "/private/tmp/")):
        parser.error("write the setup file into the isolated QA folder (not /tmp)")
    api = Api(args.api)
    server = api.ok("capabilities", "GET", "/capabilities")
    loop = (server.get("methods") or {}).get("jev_loop") or {}
    if not all((loop.get(branch) or {}).get("available") is True for branch in ("ligand", "protein")):
        raise SystemExit(f"methods.jev_loop is not available for both branches: {json.dumps(loop)[:600]}")
    setup = {"schema": "m25_jev_loop_setup@1", "runs": {"L": ligand_run(api), "P": protein_run(api)},
             "madeAt": datetime.now(UTC).isoformat()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(setup, indent=2) + "\n")
    print(json.dumps({"ok": True, "out": str(out), "runs": {key: value["run"] for key, value in setup["runs"].items()}}))


if __name__ == "__main__":
    main()
