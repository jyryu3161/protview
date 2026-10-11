"""M28 T3 one-shot recorder: a run log holding ``mutation_candidates_markdown@1`` reports that cite reference values.

Recorded on the unmodified M20 report code (before the M28 T3 report format @2 existed) so that the tests can show
that a stored @1 report which cites a numbering map, an annotation or a reaction knowledge result still reopens with
the same bytes after T3. After T3 the product writes such reports as @2, so running this again makes a different log
(the recorded file is the evidence, not this script's output).

Unmodified product path through HTTP (upload -> ``load_structure`` -> ``prepare_structure`` -> the cheap tools
``map_residue_numbering`` / ``annotate_reference_sites`` / ``link_reaction_knowledge`` /
``generate_mutation_candidates`` -> ``POST /method_reports``), no engine, no job, no network, no ``.env``:

* run ``run_m28_t3_v1_cited``, M15 reference FIXTURE set (``tests/reference_fixture_set.py``) and the LABELLED
  SYNTHETIC M26 reaction set ``0SY6`` (``tests/m20_catalytic_fixture.py``) in temporary folders;
* ``map_annotation``: the derived public 1MQ4 fragment ``structures_m15/derived_1mq4_a200_285_fixture.pdb``, chain A
  numbering map (``pdb_id`` 1MQ4) and its annotation, user positions = every annotated KLIFS key-site residue of the
  fragment plus two other mapped residues (seq 230, 250);
* ``catalytic``: the synthetic mutation fixture structure, the 0SY6 result of chains A and B, the positions of
  ``test_mutation_reports.py`` (ASP A26 released);
* ``plain``: the synthetic structure, two user positions, nothing cited (no report is made for it).

One ``mutation_candidates`` report is made for ``map_annotation`` and for ``catalytic``. The positions and allowed
residues are test choices, not a design proposal. Usage (writes ``v1-cited-reports.events.jsonl`` here)::

    .venv/bin/python backend/tests/fixtures/mutation_report_v1/record_v1_cited_reports.py <scratch-root>
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[1]
for extra in (str(TESTS.parent), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import m20_catalytic_fixture as CF
import pytest
from fastapi.testclient import TestClient
from reference_fixture_set import build_fixture_set

from mw import reference_snapshots as rs
from mw.api import app as api_module
from mw.workspace import new_run

FIX = TESTS / "fixtures"
FRAGMENT = FIX / "structures_m15" / "derived_1mq4_a200_285_fixture.pdb"
SYNTHETIC = FIX / "mutation" / "synthetic-mutation-fixture.cif"
RUN_ID = "run_m28_t3_v1_cited"
LOG = HERE / "v1-cited-reports.events.jsonl"
RESIDUE_KEYS = ("model_number", "chain_auth", "seq_auth", "icode", "resname")


def res(chain_auth: str, seq_auth: int, resname: str, icode: str = "") -> dict:
    return {"model_number": 1, "chain_auth": chain_auth, "seq_auth": seq_auth, "icode": icode, "resname": resname}


def _command(client: TestClient, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{RUN_ID}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def _prepared(client: TestClient, path: Path) -> str:
    uploaded = client.post(f"/runs/{RUN_ID}/uploads", params={"filename": path.name}, content=path.read_bytes())
    assert uploaded.status_code in (200, 201), uploaded.text
    loaded = _command(client, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
    return _command(client, "prepare_structure", {"structure": loaded})


def _set(client: TestClient, structure: str, residues: list[dict], **kw) -> str:
    return _command(client, "generate_mutation_candidates", {
        "structure": structure, "sources": {"pocket": None, "ligand_shell": None, "residues": residues}, **kw})


def record(root: Path) -> dict:
    root.mkdir(parents=True)
    saved = api_module.RUNS_DIR
    with pytest.MonkeyPatch.context() as patch:
        try:
            (root / "reference").mkdir()
            patch.setenv(rs.ENV_VAR, str(root / "reference"))
            build_fixture_set(root / "reference")
            CF.activate(root / "reaction_reference", patch)
            new_run(root / "runs", run_id=RUN_ID, dry_run=False)
            api_module.RUNS_DIR = root / "runs"
            api_module.RUNS.clear()
            client = TestClient(api_module.app, base_url="http://127.0.0.1")
            run = api_module._run(RUN_ID)
            fragment = _prepared(client, FRAGMENT)
            numbering_map = _command(client, "map_residue_numbering", {"structure": fragment, "pdb_id": "1MQ4",
                                                                       "chains": [{"chain_auth": "A"}]})
            annotation = _command(client, "annotate_reference_sites", {"numbering_map": numbering_map})
            sites = [site["residue"] for group in run.store.load(annotation)["groups"] for site in group["sites"]
                     if site["status"] == "annotated"]
            rows = {row["residue"]["seq_auth"]: row["residue"] for row in run.store.load(numbering_map)["rows"]}
            picked = [*sites, rows[230], rows[250]]
            made = {"map": numbering_map, "annotation": annotation,
                    "map_annotation": _set(client, fragment, [{k: r[k] for k in RESIDUE_KEYS} for r in picked],
                                           numbering_map=numbering_map, annotation=annotation)}
            synthetic = _prepared(client, SYNTHETIC)
            made["knowledge"] = CF.link(run, synthetic, ["A", "B"])
            made["catalytic"] = _set(client, synthetic, [res("A", 2, "ALA"), res("A", 6, "HID"), res("A", 10, "LEU"),
                                                         res("A", 26, "ASP"), res("B", 6, "HID")],
                                     released_residues=[res("A", 26, "ASP")], catalytic_annotation=made["knowledge"])
            made["plain"] = _set(client, synthetic, [res("A", 5, "CYS"), res("A", 2, "ALA")])
            for name in ("map_annotation", "catalytic"):
                response = client.post(f"/runs/{RUN_ID}/method_reports", json={"result_handle": made[name]})
                assert response.status_code == 201, response.text
                body = response.json()
                assert body["manifest"]["render_version"] == "mutation_candidates_markdown@1"
                made[f"{name}_report"] = body["handle"]
            assert client.get(f"/runs/{RUN_ID}/reports").status_code == 200
            CF.reset_caches()
            return made
        finally:
            api_module.RUNS_DIR = saved
            api_module.RUNS.clear()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        return 2
    root = Path(argv[0])
    made = record(root)
    shutil.copyfile(root / "runs" / RUN_ID / "events.jsonl", LOG)
    print(json.dumps(made, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
