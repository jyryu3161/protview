"""M29 T5: the PDBFixer worker ``mw/jobs/structure_repair_worker.py`` (real processes and its own checks).

Real jobs (product path, real worker process, PDBFixer 1.12.0 in the project ``.venv``; FAIL, never skip, without the
engines): public 1RNH with three MSE residues (mmCIF, and the same structure written as PDB text where MSE is HETATM),
public 1CLL (side chain + OXT, calcium ions) and the SYNTHETIC PDB-format gap fixture of T4 (1UBQ with residues 30-32
removed, REMARK 465 + SEQRES; labelled in the file). Expected values come from the input files, the T1
PDBFixer-measured fixtures (``*-additions.pdbfixer-measured.json``, measured values, not product values) and the
installed template. The in-process tests drive the worker's own checks with LABELLED fake PDBFixer outputs.
"""
from __future__ import annotations

import copy
import json
import math
import subprocess
import sys

import gemmi
import pytest
import structure_repair_lane_fixture as F
import test_structure_repair_common as C

from mw import structure_repair_bundle as bundle
from mw import structure_repair_constants as K
from mw import structure_repair_jobs as jobs
from mw.core.handles import canonical_json
from mw.jobs import structure_repair_worker as W
from mw.workspace import new_run

RNH = F.public("1rnh")


def _st(raw: bytes, fmt: str = "cif") -> gemmi.Structure:
    if fmt == "pdb":
        return gemmi.read_pdb_string(raw.decode())
    return gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())


def _job(client, root, label, raw, name, waters="strip_all") -> tuple[dict, dict, object]:
    world = F.world(client, label, raw, name, waters=waters)
    try:
        done = F.run_job(client, world["rid"], F.args(world["structure"]))
    finally:
        F.kill_leftovers(root, world["rid"])
    assert done["status"] == "done", done
    F.workers_gone(root, world["rid"])
    return world, done, new_run(root, run_id=world["rid"], dry_run=False)


def _result_rows(root, done) -> list[dict]:
    return json.loads((root / done["run_id"] / "jobs" / done["job_id"] / done["attempt_id"] /
                       "result.json").read_bytes())["added_atoms"]


@pytest.fixture(scope="module")
def jobs_done(tmp_path_factory):
    root = tmp_path_factory.mktemp("m29_t5_worker") / "runs"
    patch = pytest.MonkeyPatch()
    try:
        client = F.client(root, patch)
        pdb_text = _st(RNH).make_pdb_string().encode()
        out = {"root": root}
        for key, raw, name, waters in (
                ("1rnh", RNH, "public_1rnh.cif", "keep_all"),
                ("1rnh_pdb", pdb_text, "rnh-rendered.pdb", "keep_all"),
                ("1cll", F.public("1cll"), "public_1cll.cif", "strip_all"),
                ("gap_pdb", (C.SR_FIX / "synthetic-gap.pdb").read_bytes(), "synthetic-gap.pdb", "strip_all")):
            out[key] = _job(client, root, f"M29 worker {key} (public or SYNTHETIC; not experimental validation)",
                            raw, name, waters)
        return out
    finally:
        patch.undo()


def test_1rnh_mse_becomes_met_before_pdbfixer_with_the_selenium_coordinates_kept(jobs_done):
    root = jobs_done["root"]
    world, done, run = jobs_done["1rnh"]
    record = bundle.validated_result(run, done["output_handles"][0])["record"]
    # The worker output is the T1 measurement (MSE renamed before PDBFixer, seed 1).
    fixture = json.loads((C.SR_FIX / "1rnh-additions.pdbfixer-measured.json").read_text())["added_atoms"]
    assert canonical_json(_result_rows(root, done)) == canonical_json(fixture)
    selenium = {}
    source = _st(run.store.load(run.store.load(world["structure"])["coordinates"]))
    for res in source[0]["A"]:
        if res.name == "MSE":
            selenium[res.seqid.num] = next(a.pos for a in res if a.name == "SE")
    assert sorted(selenium) == [47, 50, 142]   # the file's MSE residues
    assert [(r["from"]["seq_auth"], r["from"]["resname"], r["to"]["resname"], r["atom_map"], r["record_type"])
            for r in record["replaced"]] == [(n, "MSE", "MET", [{"from": "SE", "to": "SD"}],
                                              {"from": "HETATM", "to": "ATOM"}) for n in (47, 50, 142)]
    assert "nonstandard_replaced" in record["classes_applied"] and K.RP5 in record["limitations"]
    repaired = _st(bundle.structure_bytes(run, done["output_handles"][0]))
    names = set()
    for res in repaired[0]["A"]:
        names.add(res.name)
        if res.seqid.num in selenium:
            sd = next(a for a in res if a.name == "SD")
            assert (res.name, sd.element.name) == ("MET", "S") and sd.pos.dist(selenium[res.seqid.num]) <= 1e-9
    assert "MSE" not in names


def test_1rnh_written_as_pdb_text_repairs_its_hetatm_mse(jobs_done):
    _world, done, run = jobs_done["1rnh_pdb"]
    record = bundle.validated_result(run, done["output_handles"][0])["record"]
    assert [r["record_type"] for r in record["replaced"]] == [{"from": "HETATM", "to": "ATOM"}] * 3
    assert {r["to"]["chain_label"] for r in record["replaced"]} == {r["from"]["chain_label"] for r in
                                                                    record["replaced"]}
    assert record["counts"]["replaced"] == 3 and record["parameters"]["waters"] == "keep_all"


def test_1cll_side_chain_oxt_and_metal_collision_record(jobs_done):
    root = jobs_done["root"]
    _world, done, run = jobs_done["1cll"]
    record = bundle.validated_result(run, done["output_handles"][0])["record"]
    expected = F.oracle("1cll")
    assert record["counts"]["added_atoms"] == expected["added_atoms"]
    assert record["counts"]["terminal_oxt"] == expected["terminal_oxt"]
    assert sorted((s["residue"]["chain_auth"], s["residue"]["seq_auth"]) for s in record["side_chain_repairs"]) == \
        expected["side_chain_residues"]
    fixture = json.loads((C.SR_FIX / "1cll-additions.pdbfixer-measured.json").read_text())["added_atoms"]
    assert canonical_json(_result_rows(root, done)) == canonical_json(fixture)
    assert record["collisions"]["metal"]["min_distance_A"] is not None   # 1CLL keeps its calcium ions


def test_pdb_format_gap_is_filled_with_the_listed_residues_and_passes_m7(jobs_done):
    _world, done, run = jobs_done["gap_pdb"]
    record = bundle.validated_result(run, done["output_handles"][0])["record"]
    assert record["classes_applied"] == ["internal_gap_filled"] and record["limitations"] == [K.RP1, K.RP2, K.RP3]
    gap = record["gaps"][0]
    # REMARK 465 (author numbers) + SEQRES (names) of the SYNTHETIC file; the label chain is the re-read value.
    remark = [line for line in (C.SR_FIX / "synthetic-gap.pdb").read_text().splitlines()
              if line.startswith("REMARK 465") and line[19:20] == "A" and line[21:26].strip().isdigit()]
    listed = [(int(line[21:26]), line[15:18]) for line in remark]
    assert [(r["seq_auth"], r["resname"]) for r in gap["residues"]] == listed == [(30, "ILE"), (31, "GLN"),
                                                                                  (32, "ASP")]
    assert {(r["chain_label"], r["seq_label"], r["icode"]) for r in gap["residues"]} == {("Axp", None, "")}
    assert record["counts"]["added_atoms"] == sum(len(C.template_heavy_names(name)) for _, name in listed)
    assert all(row["origin"] == "gap_residue" for row in record["added_atoms"])
    assert record["counts"]["protein_heavy_atoms"] == 602
    manifest = run.store.load(run.store.load(done["output_handles"][1])["manifest"])
    assert manifest["missing_residues"] == "modeled_internal_gaps"


# ----------------------------------------------------------------- the worker's own checks (in process, LABELLED)
def _payload() -> dict:
    """A small staged payload (two residues of 1RNH incl. MSE 47) with the pinned method of this machine."""
    model = _st(RNH)[0]
    residues = []
    for res in model["A"]:
        if res.seqid.num in (46, 47):
            residues.append({"ref": {"model_number": 1, "chain_auth": "A", "seq_auth": res.seqid.num, "icode": "",
                                     "chain_label": res.subchain, "seq_label": res.label_seq, "resname": res.name},
                             "atoms": [{"atom_name": a.name, "element": a.element.name,
                                        "coordinates_A": [a.pos.x, a.pos.y, a.pos.z]} for a in res
                                       if a.element.name not in ("H", "D")]})
    return {"schema": W.INPUT_SCHEMA, "method": jobs.require_ready()["method"], "seed": 1, "model_number": 1,
            "chains": [{"chain_auth": "A", "residues": residues, "gaps": []}]}


def test_mse_is_renamed_before_pdbfixer_with_coordinates_kept():
    payload = _payload()
    mse = payload["chains"][0]["residues"][1]
    assert mse["ref"]["resname"] == "MSE"
    name, atoms, replaced = W._fixer_view(mse)
    assert (name, replaced) == ("MET", True)
    for before, after in zip(mse["atoms"], atoms, strict=True):
        if before["atom_name"] == "SE":
            assert (after["atom_name"], after["element"]) == ("SD", "S")
        else:
            assert after == before
        assert after["coordinates_A"] == before["coordinates_A"]
    other = payload["chains"][0]["residues"][0]
    assert W._fixer_view(other) == (other["ref"]["resname"], other["atoms"], False)


def _views(payload):
    return [[W._fixer_view(r)[:2] for r in chain["residues"]] for chain in payload["chains"]]


def _fake_output(payload, change=None):
    """LABELLED fake PDBFixer output: the staged residues (MSE renamed) plus one added OXT."""
    out = []
    for chain_index, chain in enumerate(_views(payload)):
        for name, atoms in chain:
            out.append({"chain_id": str(chain_index), "resname": name, "atoms": copy.deepcopy(atoms)})
    out[-1]["atoms"].append({"atom_name": "OXT", "element": "O", "coordinates_A": [1.0, 2.0, 3.0]})
    if change is not None:
        change(out)
    return out


def test_added_atoms_are_the_new_ones_and_every_observed_atom_is_checked():
    payload = _payload()
    rows, diagnostics = W.added_atoms(payload["chains"], _views(payload), _fake_output(payload))
    assert [(r["residue"]["resname"], r["atom_name"], r["origin"]) for r in rows] == [("MET", "OXT", "oxt")]
    assert diagnostics["observed_max_delta_A"] == 0.0 and diagnostics["added_residues"] == 0

    def move(out):
        out[0]["atoms"][0]["coordinates_A"][0] += 1e-6

    def drop(out):
        del out[1]["atoms"][0]

    def extra_residue(out):
        out.append(copy.deepcopy(out[0]))

    def rename(out):
        out[0]["resname"] = "GLY"

    def no_element(out):
        out[-1]["atoms"][-1]["element"] = None

    for change, code in ((move, "coordinates_changed"), (drop, "coordinates_changed"),
                         (extra_residue, "repair_identity_mismatch"), (rename, "repair_identity_mismatch"),
                         (no_element, "unexpected_atoms_added")):
        with pytest.raises(W.RepairFailure) as caught:
            W.added_atoms(payload["chains"], _views(payload), _fake_output(payload, change))
        assert caught.value.reason_code == code and caught.value.detail["reason_code"] == code


def test_gap_residues_come_back_with_their_listed_identity():
    payload = _payload()
    gap_ref = {"model_number": 1, "chain_auth": "A", "seq_auth": 900, "icode": "", "chain_label": "A",
               "seq_label": 900, "resname": "GLY"}
    payload["chains"][0]["gaps"] = [{"before_index": 1, "residues": [gap_ref]}]
    out = _fake_output(payload)
    gly = {"chain_id": "0", "resname": "GLY", "atoms": [{"atom_name": n, "element": n[0], "coordinates_A": [0, 0, i]}
                                                        for i, n in enumerate(("N", "CA", "C", "O"))]}
    rows, diagnostics = W.added_atoms(payload["chains"], _views(payload), [out[0], gly, out[1]])
    assert [(r["residue"], r["origin"]) for r in rows[:4]] == [(gap_ref, "gap_residue")] * 4
    assert diagnostics["added_residues"] == 1
    with pytest.raises(W.RepairFailure) as caught:
        W.added_atoms(payload["chains"], _views(payload), [out[0], {**gly, "resname": "ALA"}, out[1]])
    assert caught.value.reason_code == "repair_identity_mismatch"


def test_a_pdbfixer_exception_is_repair_modeling_failed(monkeypatch):
    payload = _payload()

    class Refusing:   # LABELLED stand-in for a PDBFixer that refuses the input
        def __init__(self, *args, **kwargs):
            raise ValueError("labelled refusal")

    monkeypatch.setattr(W, "PDBFixer", Refusing)
    with pytest.raises(W.RepairFailure) as caught:
        W.run(payload)
    assert caught.value.reason_code == "repair_modeling_failed"


def test_the_payload_and_the_pinned_engines_are_checked_before_pdbfixer(monkeypatch):
    monkeypatch.setattr(W, "PDBFixer", F.forbid)
    good = _payload()
    bad = []
    for change in (lambda p: p.update(seed=2), lambda p: p.update(extra=1), lambda p: p["method"].update(pH=7.5),
                   lambda p: p["method"].update(pdbfixer_version="1.11"),
                   lambda p: p["chains"][0]["residues"][0]["atoms"].append(
                       {"atom_name": "H", "element": "H", "coordinates_A": [0.0, 0.0, 0.0]}),
                   lambda p: p["chains"][0]["gaps"].append({"before_index": 0, "residues": []}),
                   lambda p: p["chains"][0]["residues"][0]["atoms"][0].update(coordinates_A=[math.nan, 0.0, 0.0])):
        payload = copy.deepcopy(good)
        change(payload)
        bad.append(payload)
    for payload in bad:
        with pytest.raises((ValueError, KeyError)):
            W.run(payload)


def test_the_output_bound_and_the_script_error_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "MAX_OUTPUT_BYTES", 10)
    with pytest.raises(W.RepairFailure) as caught:
        W.encode_output({"schema": W.OUTPUT_SCHEMA, "added_atoms": []})
    assert caught.value.reason_code == "resource_exceeded" and caught.value.detail["limit"] == "output_bytes"
    # The script: a payload that does not match its control checksum is the closed engine failure (exit 1).
    (tmp_path / "structure.json").write_bytes(b"{}")
    (tmp_path / "input.json").write_text(json.dumps({"input_sha256": "0" * 64}))
    out = subprocess.run([sys.executable, "-I", str(jobs.WORKER)], cwd=tmp_path, capture_output=True, timeout=120,
                         check=False, env={"PATH": "/usr/bin:/bin"})
    assert out.returncode == 1, out.stderr
    error = json.loads((tmp_path / "error.json").read_text())
    assert error["reason_code"] == "engine_failed" and error["detail"] == {"reason_code": "engine_failed"}
    assert jobs.worker_error(tmp_path)["reason_code"] == "engine_failed"


def test_a_long_engine_error_message_is_cut_whole_and_stays_engine_failed(tmp_path):
    # LABELLED payload: a 400-character element symbol passes the payload check and makes OpenMM's element lookup raise
    # a KeyError whose text alone is longer than the 300 characters the server's envelope check takes. The whole
    # message (type prefix included) is cut to 300, so the job is the closed ``engine_failed``, never ``fatal``.
    payload = _payload()
    payload["chains"][0]["residues"][0]["atoms"][0]["element"] = "Q" * 400
    raw = canonical_json(payload)
    (tmp_path / "structure.json").write_bytes(raw)
    (tmp_path / "input.json").write_text(json.dumps({"input_sha256": W._digest(raw)}))
    out = subprocess.run([sys.executable, "-I", str(jobs.WORKER)], cwd=tmp_path, capture_output=True, timeout=120,
                         check=False, env={"PATH": "/usr/bin:/bin"})
    assert out.returncode == 1, out.stderr
    error = json.loads((tmp_path / "error.json").read_text())
    assert error["reason_code"] == "engine_failed" and error["detail"] == {"reason_code": "engine_failed"}
    assert error["message"].startswith("KeyError: 'QQQ") and len(error["message"]) == 300
    assert jobs.worker_error(tmp_path) == {"error": jobs.FAILURE_CLASSES["engine_failed"],
                                           "reason_code": "engine_failed", "message": error["message"],
                                           "detail": {"reason_code": "engine_failed"}}
