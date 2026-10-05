"""Build the two real M20 candidate sets of this folder from public 1UBQ (user-selected positions, product tool path).

Unmodified product path through HTTP (upload -> ``load_structure`` -> ``prepare_structure`` ->
``generate_mutation_candidates``, the cheap M20 tool; no engine, no job), in a run with the fixed id of
``golden_call_keys.json`` so the eight-position set is byte-identical to the golden run's set. The positions and the
allowed residues are user choices for testing, not a design proposal; 1UBQ is a public structure, not experimental
validation of anything here.

    .venv/bin/python backend/tests/fixtures/sequence_ga/build_sequence_ga_fixtures.py <runs-root>          # write
    .venv/bin/python backend/tests/fixtures/sequence_ga/build_sequence_ga_fixtures.py <runs-root> --check  # compare

``--check`` exits 0 only when a fresh build equals the files on disk byte for byte.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from mw.api import app as api_module
from mw.core.handles import canonical_json

HERE = Path(__file__).resolve().parent
UBQ = (HERE.parent / "public_1ubq.cif").read_bytes()
RUN_ID = "run_m23_golden_keys"
SETS = {
    # N terminus, adjacent pairs, the M21 I44, the C terminus; allowed AFHWY -> 8 x 5 = 40 candidates.
    "m20-candidate-set-1ubq-8pos.json": {
        "residues": [(1, "MET"), (2, "GLN"), (3, "ILE"), (6, "LYS"), (8, "LEU"), (44, "ILE"), (75, "GLY"),
                     (76, "GLY")],
        "protected": [], "allowed": "AFHWY"},
    # Small real-engine GA set: K6, I44, G76 (C terminus) with allowed AW, plus I3 user-protected (an excluded
    # position the GA must skip) -> 3 candidate positions x 2 = 6 candidates.
    "m20-candidate-set-1ubq-tiny.json": {
        "residues": [(3, "ILE"), (6, "LYS"), (44, "ILE"), (76, "GLY")], "protected": [(3, "ILE")], "allowed": "AW"},
}


def residue(seq: int, name: str) -> dict:
    return {"model_number": 1, "chain_auth": "A", "seq_auth": seq, "icode": "", "resname": name}


def _command(client: TestClient, tool: str, args: dict) -> str:
    response = client.post(f"/runs/{RUN_ID}/commands", json={"tool": tool, "args": args})
    assert response.status_code == 200, response.text
    return response.json()["handle"]["handle"]


def build(root: Path) -> dict[str, bytes]:
    from mw.workspace import new_run

    new_run(root, run_id=RUN_ID, dry_run=False)
    saved = api_module.RUNS_DIR
    try:
        api_module.RUNS_DIR = root
        api_module.RUNS.clear()
        client = TestClient(api_module.app, base_url="http://127.0.0.1")
        uploaded = client.post(f"/runs/{RUN_ID}/uploads", params={"filename": "public_1ubq.cif"}, content=UBQ)
        assert uploaded.status_code in (200, 201), uploaded.text
        source = _command(client, "load_structure", {"source": uploaded.json()["upload_id"], "model_index": 0})
        prepared = _command(client, "prepare_structure", {
            "structure": source, "altloc": "highest_occupancy", "waters": "strip_all", "hydrogens": "strip",
            "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})
        out = {}
        for name, spec in SETS.items():
            handle = _command(client, "generate_mutation_candidates", {
                "structure": prepared,
                "sources": {"pocket": None, "ligand_shell": None,
                            "residues": [residue(seq, res) for seq, res in spec["residues"]]},
                "protected_residues": [residue(seq, res) for seq, res in spec["protected"]],
                "allowed_residues": spec["allowed"]})
            response = client.get(f"/runs/{RUN_ID}/mutation_candidate_sets/{handle}")
            assert response.status_code == 200, response.text
            run = api_module._run(RUN_ID)
            out[name] = canonical_json({"handle": handle, "content": run.store.load(handle)}) + b"\n"
        return out
    finally:
        api_module.RUNS_DIR = saved
        api_module.RUNS.clear()


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--check"):
        return 2
    built = build(Path(argv[0]))
    if len(argv) == 2:
        bad = [name for name, raw in built.items() if (HERE / name).read_bytes() != raw]
        for name in bad:
            print(f"differs: {name}")
        return 1 if bad else 0
    for name, raw in built.items():
        (HERE / name).write_bytes(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
