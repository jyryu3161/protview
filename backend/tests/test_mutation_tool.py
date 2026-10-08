"""M20 T3 tool wiring for ``generate_mutation_candidates`` (``mw.tools.mutations``) -> ``mutation_candidate_set@1``.

Inputs: the public 1MQ4 mmCIF (+ ADP; a reference FIXTURE set from ``fixtures/reference`` for the M15 map and M16
annotation), the public 1HSG mmCIF (only as "another structure" for fpocket), and a SYNTHETIC 401-residue PDB built in
``_synthetic_401_pdb`` (labelled; straight line of ALA residues 10 A apart plus one LIG atom next to residue 401).

Oracle: 1MQ4 ADP-shell distances, KLIFS sites and MG contacts are the independent numpy values recorded in
docs/qa/m20-mutations-20261003/preflight.txt (``abs <= 1e-9``); pocket expectations are re-read from the stored
pocket_set of the same run (fpocket is not deterministic, so no pocket numbers are hard-coded). fpocket runs for real
from ``.deps/fpocket``; these tests FAIL, never skip, when it is missing. Fault injections are labelled.

M26 v2 (catalytic annotation): ``reaction_knowledge@1`` results come from the product tool ``link_reaction_knowledge``
over the LABELLED SYNTHETIC reaction reference set of ``m20_catalytic_fixture`` (made-up PDB ID 0SY6 naming the M20
synthetic fixture's chains; rows in ``fixtures/reaction/t6/``). The expected protection is written out by hand from
the fixture design and re-derived here from the stored result rows (plain dict comparisons, no product function).
"""
from __future__ import annotations

import copy
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import m20_catalytic_fixture as CF
import pytest
from fastapi.testclient import TestClient
from reference_fixture_set import build_fixture_set

from mw import mutation_constants as K
from mw import pocket_bundle
from mw import reference_snapshots as rs
from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import replay
from mw.tools import mutations as tool_module
from mw.tools.structural import structure_residues
from mw.workspace import CONFIG, build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
CIF_1MQ4 = FIX / "public_1mq4.cif"
CIF_1HSG = FIX / "public_1hsg.cif"
CIF_1UBQ = FIX / "public_1ubq.cif"
SYN = FIX / "mutation" / "synthetic-mutation-fixture.cif"
REPO = Path(__file__).resolve().parents[2]
TOOL = K.TOOL
TOL = 1e-9

ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
PO4 = {"model_number": 1, "chain_auth": "A", "seq_auth": 1, "icode": "", "resname": "PO4"}
MG = {"model_number": 1, "chain_auth": "A", "seq_auth": 2086, "icode": "", "resname": "MG"}
# preflight.txt (c): ADP heavy-atom minimum distances <= 5.0 A (chain A seq_auth -> A).
ADP_SHELL_5 = {
    139: 3.6335530820396684, 140: 3.4748130884984305, 141: 3.5587813925556007, 142: 3.05630381343217,
    143: 2.6283578523481124, 144: 4.43855528297215, 147: 3.5023984639101227, 160: 3.613476304059567,
    162: 2.6428630308814687, 181: 4.647095114154647, 194: 3.424981313817638, 210: 3.912459584455801,
    211: 2.695699723633924, 212: 4.1012362770267154, 213: 3.167315109047404, 217: 3.297842476529162,
    260: 2.598733152903544, 261: 2.9617780132886407, 263: 3.4190263233850664, 274: 2.853779599058067}
KLIFS_1MQ4 = {162: ["III.17"], 181: ["αC.24"], 210: ["GK.45"], 211: ["hinge.46"], 212: ["hinge.47"],
              213: ["hinge.48"], 274: ["xDFG.81"]}
MG_1MQ4_3 = {261: (2.035529660800842, 2088), 274: (1.916987219571373, 2088)}
FORBIDDEN = ("점수", "순위", "추천", "최적", "개선", "안정성", "ΔΔG", "친화도", "활성", "예측", "안전", "유망")


def res(seq_auth: int, resname: str, chain_auth: str = "A") -> dict:
    return {"model_number": 1, "chain_auth": chain_auth, "seq_auth": seq_auth, "icode": "", "resname": resname}


LYS141, ARG126, LEU139, ASN261 = res(141, "LYS"), res(126, "ARG"), res(139, "LEU"), res(261, "ASN")


# --- helpers ---------------------------------------------------------------------------------------------------------

@pytest.fixture
def ref(tmp_path, monkeypatch):
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    build_fixture_set(root)
    return root


@pytest.fixture
def reaction(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    CF.activate(root, monkeypatch)
    yield root
    CF.reset_caches()


def _run(tmp_path, name="run_mut", dry_run=False):
    reg = build_registry()
    calls: list[dict] = []
    impl = reg.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    reg.impls[TOOL] = counted
    return new_run(tmp_path / "runs", run_id=name, dry_run=dry_run, registry=reg), calls


def _load(run, path: Path) -> str:
    return run.call("load_structure", {"source": str(path), "model_index": 0}).handle


def _prepare(run, structure: str) -> str:
    return run.call("prepare_structure", {"structure": structure}).handle


def _map(run, structure, **kw) -> str:
    args = {"structure": structure, "pdb_id": "1MQ4", "chains": [{"chain_auth": "A"}], **kw}
    return run.call("map_residue_numbering", args).handle


def _annotate(run, numbering_map) -> str:
    return run.call("annotate_reference_sites", {"numbering_map": numbering_map}).handle


def _events(run, kind=None):
    return [e for e in run.events.read() if kind is None or e["type"] == kind]


def _args(structure, *, pocket=None, ligand_shell=None, residues=(), **kw):
    return {"structure": structure, "sources": {"pocket": pocket, "ligand_shell": ligand_shell,
                                                "residues": list(residues)}, **kw}


def _rejected(run, calls, args, reason_code, cls=FailureClass.input_invalid):
    before = len(_events(run))
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.cls == cls and caught.value.detail["reason_code"] == reason_code, (
        reason_code, caught.value.detail, caught.value.message)
    new = _events(run)[before:]
    assert [e["type"] for e in new if e["type"] != "wall_charged"] == ["proposal_rejected"]
    assert calls == []


def _seq(content):
    return [p["residue"]["seq_auth"] for p in content["positions"]]


# --- registration ----------------------------------------------------------------------------------------------------

def test_registered_in_all_four_places_with_a_precheck():
    import yaml

    spec = next(t for t in yaml.safe_load((CONFIG / "tools.yaml").read_text())["tools"] if t["name"] == TOOL)
    assert spec["accepts"] == {"structure": ["prepared_structure"]} and spec["emits"] == "mutation_candidate_set"
    assert spec["cost_class"] == "cheap"
    assert set(spec["params"]) == set(K.ARG_KEYS) - {"structure"}
    assert not any(word in spec["description"] for word in FORBIDDEN)
    reg = build_registry()
    assert TOOL in reg.impls and reg.prechecks[TOOL] is tool_module.precheck and TOOL not in reg.unavailable
    assert TOOL in api_module.SUPPORTED_TOOLS and TOOL in api_module.REGISTRY.impls
    workspace_source = (REPO / "backend/mw/workspace.py").read_text()
    assert "mutations.register(reg)" in workspace_source


def test_server_modules_import_no_heavy_chemistry_package():
    code = ("import sys, mw.tools.mutations, mw.workspace, mw.api.app; "
            "print(sorted(m for m in ('rdkit', 'meeko', 'MDAnalysis', 'openmm', 'prolif') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO / "backend", capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == "[]"


# --- admission through Run.call: typed failure, implementation never called -----------------------------------------

def test_every_admission_reason_rejects_before_the_implementation(tmp_path, ref, reaction):
    run, calls = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    prepared = _prepare(run, structure)
    numbering_map = _map(run, prepared)
    annotation = _annotate(run, numbering_map)
    original_map = _map(run, structure)                     # same run, another structure (the unprepared one)
    original_annotation = _annotate(run, original_map)
    other_map = _map(run, prepared, pdb_id=None, chains=[{"chain_auth": "A", "uniprot_accession": "O14965"}])
    assert other_map != numbering_map
    other, _ = _run(tmp_path, name="run_other")
    foreign_prepared = _prepare(other, _load(other, CIF_1MQ4))
    foreign_map = _map(other, foreign_prepared)
    foreign_annotation = _annotate(other, foreign_map)
    # M26 results on 1MQ4 with a PDB ID that no row of the set names (valid results: pdb_not_in_snapshot)
    knowledge = CF.link(run, prepared, ["A"], pdb_id=CF.OTHER_PDB_ID)
    original_knowledge = CF.link(run, structure, ["A"], pdb_id=CF.OTHER_PDB_ID)   # the unprepared structure
    foreign_knowledge = CF.link(other, foreign_prepared, ["A"], pdb_id=CF.OTHER_PDB_ID)
    # LABELLED FAULT INJECTION: a reaction_knowledge@1 object whose content fails validated_result (counts edited)
    forged_content = copy.deepcopy(run.store.load(knowledge))
    forged_content["counts"]["chains"] = 2
    forged_knowledge = run.store.put("reaction_knowledge", "reaction_knowledge@1", forged_content,
                                     produced_by="forged_test_fixture").handle

    base = _args(prepared, residues=[LYS141])
    shell = {"radius_A": 5.0}
    cases = [
        # unknown_field at each of the four levels; it wins over every later reason
        ({**base, "extra": 1}, "unknown_field"),
        ({**base, "sources": {**base["sources"], "x": 1}}, "unknown_field"),
        (_args(prepared, pocket={"pocket_set": prepared, "ranks": [1], "x": 1}), "unknown_field"),
        (_args(prepared, ligand_shell={"radius_A": 5.0, "x": 1}, ligand=ADP), "unknown_field"),
        ({**_args(structure), "extra": 1}, "unknown_field"),
        # structure_invalid: wrong kind, other run, not a handle, missing; before no_position_source
        (_args(structure, residues=[LYS141]), "structure_invalid"),
        (_args(numbering_map, residues=[LYS141]), "structure_invalid"),
        (_args(foreign_prepared, residues=[LYS141]), "structure_invalid"),
        (_args("obj://nope", residues=[LYS141]), "structure_invalid"),
        (_args(None, residues=[LYS141]), "structure_invalid"),
        ({"sources": base["sources"]}, "structure_invalid"),
        (_args(structure), "structure_invalid"),
        # no_position_source before argument_invalid
        (_args(prepared, metal_contact_A=99), "no_position_source"),
        # argument_invalid
        (_args(prepared, ligand_shell={"radius_A": 0.5}, ligand=ADP), "argument_invalid"),
        (_args(prepared, ligand_shell={"radius_A": 12.01}, ligand=ADP), "argument_invalid"),
        (_args(prepared, ligand_shell={"radius_A": True}, ligand=ADP), "argument_invalid"),
        (_args(prepared, ligand_shell={"radius_A": float("nan")}, ligand=ADP), "argument_invalid"),
        (_args(prepared, ligand_shell={"radius_A": float("inf")}, ligand=ADP), "argument_invalid"),
        ({**base, "metal_contact_A": 5.5}, "argument_invalid"),
        ({**base, "metal_contact_A": True}, "argument_invalid"),
        ({**base, "metal_contact_A": None}, "argument_invalid"),
        (_args(prepared, residues=[LYS141] * 401), "argument_invalid"),
        (_args(prepared, pocket={"pocket_set": prepared, "ranks": []}), "argument_invalid"),
        (_args(prepared, pocket={"pocket_set": prepared, "ranks": [True]}), "argument_invalid"),
        ({**base, "sources": "pocket"}, "argument_invalid"),
        ({**base, "ligand": {"resname": "ADP"}}, "argument_invalid"),
        (_args(prepared, residues=[{**LYS141, "seq_auth": "141"}]), "argument_invalid"),
        (_args(prepared, residues=[{**LYS141, "display": "LYS 141"}]), "argument_invalid"),
        # allowed_residues_invalid
        ({**base, "allowed_residues": ""}, "allowed_residues_invalid"),
        ({**base, "allowed_residues": "AB"}, "allowed_residues_invalid"),
        ({**base, "allowed_residues": "AA"}, "allowed_residues_invalid"),
        ({**base, "allowed_residues": ["A", "A"]}, "allowed_residues_invalid"),
        ({**base, "allowed_residues": ["AC"]}, "allowed_residues_invalid"),
        # residue_invalid: absent, non-polymer, label mismatch
        (_args(prepared, residues=[res(9999, "LYS")]), "residue_invalid"),
        (_args(prepared, residues=[ADP]), "residue_invalid"),
        (_args(prepared, residues=[{**LYS141, "chain_label": "Z"}]), "residue_invalid"),
        ({**base, "protected_residues": [res(141, "ALA")]}, "residue_invalid"),
        # duplicate_residue (also 5-field vs 7-field spelling of one residue)
        (_args(prepared, residues=[LYS141, LYS141]), "duplicate_residue"),
        (_args(prepared, residues=[LYS141, {**LYS141, "chain_label": "A"}]), "duplicate_residue"),
        ({**base, "released_residues": [ARG126, ARG126]}, "duplicate_residue"),
        ({**base, "protected_residues": [ARG126], "released_residues": [ARG126]}, "protect_release_conflict"),
        # ligand_required (even with two ligands present) before ligand_invalid
        (_args(prepared, ligand_shell=shell), "ligand_required"),
        (_args(prepared, ligand_shell=shell, ligand=None), "ligand_required"),
        (_args(prepared, ligand_shell=shell, ligand={**ADP, "seq_auth": 1}), "ligand_invalid"),
        ({**base, "ligand": LYS141}, "ligand_invalid"),
        ({**base, "ligand": MG}, "ligand_invalid"),
        # pocket_set_invalid: wrong kind, other run, not a handle, missing
        (_args(prepared, pocket={"pocket_set": prepared, "ranks": [1]}), "pocket_set_invalid"),
        (_args(prepared, pocket={"pocket_set": foreign_prepared, "ranks": [1]}), "pocket_set_invalid"),
        (_args(prepared, pocket={"pocket_set": "x", "ranks": [1]}), "pocket_set_invalid"),
        (_args(prepared, pocket={"ranks": [1]}), "pocket_set_invalid"),
        # numbering_map_invalid / annotation_invalid
        ({**base, "numbering_map": annotation}, "numbering_map_invalid"),
        ({**base, "numbering_map": foreign_map}, "numbering_map_invalid"),
        ({**base, "numbering_map": prepared}, "numbering_map_invalid"),
        ({**base, "numbering_map": 7}, "numbering_map_invalid"),
        ({**base, "annotation": numbering_map}, "annotation_invalid"),
        ({**base, "annotation": foreign_annotation}, "annotation_invalid"),
        ({**base, "annotation": "x"}, "annotation_invalid"),
        # catalytic_annotation_invalid (M26 8.1): not a handle, unknown, other kind, other run, fails validated_result
        ({**base, "catalytic_annotation": 7}, "catalytic_annotation_invalid"),
        ({**base, "catalytic_annotation": "x"}, "catalytic_annotation_invalid"),
        ({**base, "catalytic_annotation": numbering_map}, "catalytic_annotation_invalid"),
        ({**base, "catalytic_annotation": annotation}, "catalytic_annotation_invalid"),
        ({**base, "catalytic_annotation": foreign_knowledge}, "catalytic_annotation_invalid"),
        ({**base, "catalytic_annotation": forged_knowledge}, "catalytic_annotation_invalid"),
        # ... right after annotation_invalid
        ({**base, "annotation": numbering_map, "catalytic_annotation": "x"}, "annotation_invalid"),
        # every kind/run check runs before structure_mismatch
        ({**base, "numbering_map": original_map, "annotation": numbering_map}, "annotation_invalid"),
        ({**base, "numbering_map": original_map, "catalytic_annotation": forged_knowledge},
         "catalytic_annotation_invalid"),
        ({**base, "annotation": original_annotation, "catalytic_annotation": "x"}, "catalytic_annotation_invalid"),
        # structure_mismatch (map, annotation, catalytic annotation), before annotation_map_mismatch
        ({**base, "numbering_map": original_map}, "structure_mismatch"),
        ({**base, "annotation": original_annotation}, "structure_mismatch"),
        ({**base, "numbering_map": original_map, "annotation": original_annotation}, "structure_mismatch"),
        ({**base, "numbering_map": numbering_map, "annotation": original_annotation}, "structure_mismatch"),
        ({**base, "catalytic_annotation": original_knowledge}, "structure_mismatch"),
        ({**base, "numbering_map": other_map, "annotation": annotation, "catalytic_annotation": original_knowledge},
         "structure_mismatch"),
        ({**base, "numbering_map": other_map, "annotation": annotation}, "annotation_map_mismatch"),
        ({**base, "numbering_map": other_map, "annotation": annotation, "catalytic_annotation": knowledge},
         "annotation_map_mismatch"),
    ]
    assert {code for _, code in cases} == set(K.ADMISSION_REASON_CODES) - {"pocket_rank_invalid",
                                                                            "pocket_residue_mismatch"}
    for args, reason_code in cases:
        _rejected(run, calls, args, reason_code)
    assert not [e for e in _events(run, "tool_called") if e["tool"] == TOOL]
    assert not [e for e in _events(run, "object_created") if e["kind"] == K.KIND]
    # the same inputs are accepted once the wrong field is fixed
    ok = run.call(TOOL, {**base, "numbering_map": numbering_map, "annotation": annotation,
                         "catalytic_annotation": knowledge})
    assert ok.kind == K.KIND and len(calls) == 1
    check = run.store.load(ok.handle)["protection_checks"]["catalytic_residue_database"]
    assert check["annotation"] == knowledge and check["uncovered_chains"] == [{"chain_auth": "A",
                                                                              "coverage": "pdb_not_in_snapshot"}]


def test_argument_repair_runs_the_same_precheck(tmp_path):
    run, calls = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    _rejected(run, calls, _args(prepared, residues=[res(9999, "LYS")]), "residue_invalid")
    failed = _events(run, "proposal_rejected")[-1]["proposal_id"]
    with pytest.raises(ToolFailure) as caught:
        run.repair_call(failed, _args(prepared, residues=[LYS141, LYS141]))
    assert caught.value.detail["reason_code"] == "duplicate_residue" and calls == []
    out = run.repair_call(failed, _args(prepared, residues=[LYS141]))
    assert out.kind == K.KIND and len(calls) == 1


# --- result, call key, limits -----------------------------------------------------------------------------------------

def test_1mq4_shell_and_user_with_and_without_map_and_annotation(tmp_path, ref):
    run, calls = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    numbering_map = _map(run, prepared)
    annotation = _annotate(run, numbering_map)
    args = _args(prepared, ligand_shell={"radius_A": 5}, residues=[ARG126, LYS141], ligand=ADP)
    bare = run.call(TOOL, args)
    full = run.call(TOOL, {**args, "numbering_map": numbering_map, "annotation": annotation})
    assert bare.handle != full.handle and len(calls) == 2
    expected_seq = sorted({*ADP_SHELL_5, 126})
    map_rows = {(r["residue"]["chain_auth"], r["residue"]["seq_auth"]): r
                for r in run.store.load(numbering_map)["rows"]}
    for handle, annotated in ((bare.handle, False), (full.handle, True)):
        content = run.store.load(handle)
        meta = run.store.meta(handle)
        assert (meta["kind"], meta["schema"]) == (K.KIND, K.SCHEMA)
        assert meta["summary"] == {"structure": prepared, **content["counts"], "null_result": content["null_result"]}
        assert content["structure"] == {"handle": prepared, "model_number": 1, "structure_kind": "prepared_structure"}
        assert _seq(content) == expected_seq
        for p in content["positions"]:
            seq = p["residue"]["seq_auth"]
            kinds = [s["kind"] for s in p["sources"]]
            assert kinds == (["ligand_shell"] if seq in ADP_SHELL_5 else []) + (["user"] if seq in (126, 141) else [])
            if seq in ADP_SHELL_5:
                assert abs(p["ligand_min_distance_A"] - ADP_SHELL_5[seq]) <= TOL
            else:
                assert p["ligand_min_distance_A"] > 5.0
            metal = p["protection"]["metal"]
            assert (metal is None) == (seq not in MG_1MQ4_3)
            if metal is not None:
                assert abs(metal["min_distance_A"] - MG_1MQ4_3[seq][0]) <= TOL
                assert metal["metal_residue"]["seq_auth"] == MG_1MQ4_3[seq][1]
            if annotated:
                assert p["protection"]["klifs_sites"] == KLIFS_1MQ4.get(seq, [])
                row = map_rows[("A", seq)]
                assert p["numbering"] == {"status": row["status"], **{f: row[f] for f in K.NUMBERING_FIELDS}}
            else:
                assert p["protection"]["klifs_sites"] is None and p["numbering"] is None
            excluded = seq in MG_1MQ4_3 or (annotated and seq in KLIFS_1MQ4)
            assert p["status"] == ("excluded" if excluded else "candidate")
            assert p["candidate_count"] == (0 if excluded else 19)
        klifs_check = content["protection_checks"]["klifs_key_sites"]
        if annotated:
            assert klifs_check == {"status": "checked", "reason": None, "annotation": annotation,
                                   "annotated_sites": 10, "absent_sites": 0}
        else:
            assert klifs_check == {"status": "not_checked", "reason": "annotation_not_given", "annotation": None,
                                   "annotated_sites": None, "absent_sites": None}
        excluded_n = len(set(MG_1MQ4_3) | (set(KLIFS_1MQ4) if annotated else set()))
        assert content["counts"]["candidates"] == (len(expected_seq) - excluded_n) * 19
        assert content["null_result"] is False


def test_same_set_same_handle_and_different_allowed_set_new_handle(tmp_path):
    run, calls = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    first = run.call(TOOL, _args(prepared, residues=[ARG126, LYS141, LEU139], protected_residues=[LEU139],
                                 allowed_residues="ACDE", ligand=ADP))
    adp7 = {**ADP, "chain_label": "E", "seq_label": None}
    second = run.call(TOOL, _args(prepared, residues=[LEU139, {**LYS141, "chain_label": "A"}, ARG126],
                                  protected_residues=[LEU139], allowed_residues=["E", "D", "C", "A"], ligand=adp7,
                                  metal_contact_A=3, numbering_map=None, annotation=None))
    assert second.handle == first.handle and len(calls) == 1
    assert _events(run, "cache_hit")[-1]["tool"] == TOOL
    third = run.call(TOOL, _args(prepared, residues=[ARG126, LYS141, LEU139], protected_residues=[LEU139],
                                 allowed_residues="ACD", ligand=ADP))
    assert third.handle != first.handle and len(calls) == 2
    called = next(e for e in _events(run, "tool_called") if e["tool"] == TOOL)["args"]   # the call key args
    assert called["allowed_residues"] == "ACDE" and called["ligand"] == adp7 and called["metal_contact_A"] == 3.0
    assert "catalytic_annotation" in called and called["catalytic_annotation"] is None    # always in the call key
    assert [r["seq_auth"] for r in called["sources"]["residues"]] == [126, 139, 141]
    assert all(set(r) == set(K.IDENTITY_FIELDS) for r in called["sources"]["residues"])


def _synthetic_401_pdb() -> bytes:
    """SYNTHETIC: 401 ALA residues on a line (10 A apart, chain A 1..401) and one LIG carbon 3 A from residue 401."""
    lines, serial = [], 1
    for seq in range(1, 402):
        x = seq * 10.0
        for name, dx, dy, element in (("N", -1.2, 0.0, "N"), ("CA", 0.0, 0.0, "C"), ("C", 1.2, 0.0, "C"),
                                      ("O", 1.2, 1.2, "O"), ("CB", 0.0, -1.5, "C")):
            lines.append(f"ATOM  {serial:5d} {name:<4} ALA A{seq:4d}    {x + dx:8.3f}{dy:8.3f}{0.0:8.3f}"
                         f"  1.00 20.00          {element:>2}")
            serial += 1
    lines.append(f"HETATM{serial:5d} C1   LIG A 501    {4010.0:8.3f}{3.0:8.3f}{0.0:8.3f}  1.00 20.00           C")
    return ("\n".join(lines) + "\nEND\n").encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    api_module.RUNS.clear()
    calls: list[dict] = []
    impl = api_module.REGISTRY.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    monkeypatch.setitem(api_module.REGISTRY.impls, TOOL, counted)
    http = TestClient(api_module.app, base_url="http://127.0.0.1")
    http.calls = calls
    return http


def _http_run(client, goal="M20 mutations") -> str:
    created = client.post("/runs", json={"goal": goal, "dry_run": False})
    assert created.status_code == 201, created.text
    return created.json()["run_id"]


def _command(client, rid, tool, args):
    return client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})


def _http_prepared(client, rid, raw: bytes, filename: str) -> tuple[str, str]:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": filename}, content=raw,
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    structure = _command(client, rid, "load_structure", {"source": upload.json()["upload_id"]})
    assert structure.status_code == 200, structure.text
    structure = structure.json()["handle"]["handle"]
    prepared = _command(client, rid, "prepare_structure", {"structure": structure})
    assert prepared.status_code == 200, prepared.text
    return structure, prepared.json()["handle"]["handle"]


def _kinds(rid) -> list[str]:
    return [e["kind"] for e in api_module._run(rid).events.read() if e["type"] == "object_created"]


def test_too_many_positions_is_429_and_nothing_is_stored(client):
    rid = _http_run(client)
    _, prepared = _http_prepared(client, rid, _synthetic_401_pdb(), "synthetic_401.pdb")
    first_400 = [res(seq, "ALA") for seq in range(1, 401)]
    lig = {"model_number": 1, "chain_auth": "A", "seq_auth": 501, "icode": "", "resname": "LIG"}
    over = _command(client, rid, TOOL, _args(prepared, residues=first_400, ligand_shell={"radius_A": 5.0},
                                             ligand=lig))
    assert over.status_code == 429, over.text
    assert over.json()["error"] == "resource_exceeded"
    assert over.json()["detail"] == {"reason_code": "too_many_positions", "positions": 401, "limit": 400}
    assert K.KIND not in _kinds(rid) and len(client.calls) == 1
    too_long = _command(client, rid, TOOL, _args(prepared, residues=[*first_400, res(401, "ALA")]))
    assert too_long.status_code == 422 and too_long.json()["detail"]["reason_code"] == "argument_invalid"
    assert len(client.calls) == 1
    exact = _command(client, rid, TOOL, _args(prepared, residues=first_400))
    assert exact.status_code == 200, exact.text
    content = api_module._run(rid).store.load(exact.json()["handle"]["handle"])
    assert content["counts"]["positions"] == 400 and content["counts"]["candidates"] == 400 * 19


# --- recovery, dry run ------------------------------------------------------------------------------------------------

def test_events_only_recovery(tmp_path, ref):
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    numbering_map = _map(run, prepared)
    out = run.call(TOOL, _args(prepared, ligand_shell={"radius_A": 5.0}, ligand=ADP, numbering_map=numbering_map,
                               annotation=_annotate(run, numbering_map)))
    sha = out.handle.rsplit("/", 1)[1]
    raw = (run.run_dir / "objects" / f"{sha}.json").read_bytes()
    handles = run.store.handles()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    shutil.rmtree(run.run_dir / "uploads", ignore_errors=True)
    shutil.rmtree(ref)
    reopened, calls = _run(tmp_path)
    assert (reopened.run_dir / "objects" / f"{sha}.json").read_bytes() == raw
    assert reopened.store.handles() == handles and calls == []
    assert reopened.store.meta(out.handle)["summary"] == out.summary
    replayed = replay(run.run_dir / "events.jsonl", tmp_path / "replay" / run.run_id, build_registry(), run.run_id)
    assert replayed == handles
    assert (tmp_path / "replay" / run.run_id / "objects" / f"{sha}.json").read_bytes() == raw


def test_dry_run_executes_the_cheap_tool(tmp_path):
    run, calls = _run(tmp_path, dry_run=True)
    prepared = _prepare(run, _load(run, CIF_1MQ4))
    out = run.call(TOOL, _args(prepared, ligand_shell={"radius_A": 5.0}, ligand=ADP))
    assert out.kind == K.KIND and len(calls) == 1
    assert _seq(run.store.load(out.handle)) == sorted(ADP_SHELL_5)
    assert not [e for e in _events(run, "tool_called") if e.get("plan_only")]


# --- HTTP: /tools, /capabilities, /commands ---------------------------------------------------------------------------

def test_http_tools_capabilities_and_commands_on_public_1mq4(client, ref):
    assert client.get("/capabilities").json()["methods"]["mutation_candidates"] == {
        "available": True, "reason_code": None, "reason": None}
    assert TOOL in {t["name"] for t in client.get("/tools").json()}
    rid = _http_run(client)
    structure, prepared = _http_prepared(client, rid, CIF_1MQ4.read_bytes(), "1mq4.cif")
    numbering_map = _command(client, rid, "map_residue_numbering", {"structure": prepared, "pdb_id": "1MQ4",
                                                                    "chains": [{"chain_auth": "A"}]})
    numbering_map = numbering_map.json()["handle"]["handle"]
    annotation = _command(client, rid, "annotate_reference_sites", {"numbering_map": numbering_map})
    annotation = annotation.json()["handle"]["handle"]
    args = _args(prepared, ligand_shell={"radius_A": 5.0}, residues=[ARG126], ligand=ADP,
                 protected_residues=[LEU139], released_residues=[ASN261, ARG126])
    bare = _command(client, rid, TOOL, args)
    assert bare.status_code == 200, bare.text
    full = _command(client, rid, TOOL, {**args, "numbering_map": numbering_map, "annotation": annotation})
    assert full.status_code == 200, full.text
    assert len(client.calls) == 2
    store = api_module._run(rid).store
    for response, annotated in ((bare, False), (full, True)):
        handle = response.json()["handle"]
        assert handle["kind"] == K.KIND and handle["null_result"] is False
        content = store.load(handle["handle"])
        assert _seq(content) == sorted({*ADP_SHELL_5, 126})
        by_seq = {p["residue"]["seq_auth"]: p for p in content["positions"]}
        assert by_seq[139]["exclusion_reasons"] == ["user_protected"]
        assert by_seq[261]["protection"] == {"reasons": ["metal_contact"], "released": True, "klifs_sites": (
            [] if annotated else None), "metal": by_seq[261]["protection"]["metal"], "disulfide_partner": None,
            "catalytic": None}   # v2 without a catalytic annotation: not checked
        assert by_seq[261]["status"] == "candidate"
        assert by_seq[274]["exclusion_reasons"] == (["klifs_key_site", "metal_contact"] if annotated
                                                    else ["metal_contact"])
        assert [r["effect"] for r in content["released_residues"]] == ["none", "released"]   # file order: 126, 261
        assert (content["protection_checks"]["klifs_key_sites"]["status"]
                == ("checked" if annotated else "not_checked"))
    before = len(client.calls)
    for bad, code in ((_args(structure, residues=[ARG126]), "structure_invalid"),
                      (_args(prepared, ligand_shell={"radius_A": 5.0}), "ligand_required"),
                      ({**args, "annotation": numbering_map}, "annotation_invalid")):
        rejected = _command(client, rid, TOOL, bad)
        assert rejected.status_code == 422 and rejected.json()["detail"]["reason_code"] == code
    assert len(client.calls) == before


# --- pocket source with real fpocket ----------------------------------------------------------------------------------

def _detect(client, rid, prepared, chains=None) -> dict:
    args = {"structure": prepared} if chains is None else {"structure": prepared, "chains": chains}
    job = client.post(f"/runs/{rid}/jobs", json={"protocol_id": "fpocket_detect_v1", "args": args,
                                                 "timeout_s": 120})
    assert job.status_code == 200, job.text
    return job.json()


def _start(client, rid, job_id):
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "done", started.json()
    return started.json()["artifacts"]["pocket_set"]


def test_pocket_source_reads_only_published_pocket_sets_of_the_same_structure(client, monkeypatch):
    capability = pocket_bundle.capability()
    assert capability["status"] == "ready", f"fpocket must be installed: {capability}"
    rid = _http_run(client)
    structure, prepared = _http_prepared(client, rid, CIF_1MQ4.read_bytes(), "1mq4.cif")
    _, hsg_prepared = _http_prepared(client, rid, CIF_1HSG.read_bytes(), "1hsg.cif")
    pocket_set = _start(client, rid, _detect(client, rid, prepared)["job_id"])
    hsg_pocket_set = _start(client, rid, _detect(client, rid, hsg_prepared)["job_id"])
    # an fpocket result written to the log but cancelled before its terminal event is never published
    # (on a second preparation of 1MQ4, so the cancelled job never shares a call key with a published one)
    run = api_module._run(rid)
    stripped = _command(client, rid, "prepare_structure", {"structure": structure, "waters": "strip_all"})
    stripped = stripped.json()["handle"]["handle"]
    assert stripped != prepared
    cancelled = _detect(client, rid, stripped)
    assert cancelled["status"] == "queued"
    JobQueue(run, barrier=lambda stage: stage == "before_terminal" and JobQueue(run).request_cancel(
        cancelled["job_id"])).start(cancelled["job_id"])
    assert JobQueue(run).get(cancelled["job_id"])["status"] == "cancelled"
    unpublished = [e["handle"] for e in run.events.read() if e["type"] == "object_created"
                   and e["kind"] == "pocket_set" and e["handle"] not in (pocket_set, hsg_pocket_set)]
    assert len(unpublished) == 1 and run.store.load(unpublished[0])["source_handle"] == stripped
    other_rid = _http_run(client, "other")
    _, foreign_prepared = _http_prepared(client, other_rid, CIF_1MQ4.read_bytes(), "1mq4.cif")

    stored = run.store.load(pocket_set)
    assert stored["null_result"] is False and stored["source_handle"] == prepared
    ranks = [p["rank"] for p in stored["pockets"]][:2]
    ok = _command(client, rid, TOOL, _args(prepared, pocket={"pocket_set": pocket_set, "ranks": ranks[::-1]}))
    assert ok.status_code == 200, ok.text
    content = run.store.load(ok.json()["handle"]["handle"])
    lining: dict[tuple, list[int]] = {}
    for pocket in stored["pockets"]:
        if pocket["rank"] in ranks:
            for item in pocket["lining_residues"]:
                lining.setdefault(tuple(item[k] for k in K.IDENTITY_FIELDS), []).append(pocket["rank"])
    assert lining    # fpocket found lining residues in the chosen ranks
    file_order = [tuple(r[k] for k in K.IDENTITY_FIELDS) for r in structure_residues(run.store, prepared)["residues"]]
    keys = [tuple(p["residue"][k] for k in K.IDENTITY_FIELDS) for p in content["positions"]]
    assert keys == [key for key in file_order if key in lining]
    for p, key in zip(content["positions"], keys, strict=True):
        assert p["sources"] == [{"kind": "pocket", "pocket_rank": rank} for rank in sorted(set(lining[key]))]
    assert content["pockets"] == {"pocket_set": pocket_set, "ranks": sorted(ranks),
                                  "lining_residue_count": len(lining)}
    assert len(client.calls) == 1

    max_rank = max(p["rank"] for p in stored["pockets"])
    cases = [
        (stripped, {"pocket_set": unpublished[0], "ranks": [1]}, "pocket_set_invalid"),   # its own structure
        (prepared, {"pocket_set": unpublished[0], "ranks": [1]}, "pocket_set_invalid"),
        (prepared, {"pocket_set": prepared, "ranks": [1]}, "pocket_set_invalid"),
        (prepared, {"pocket_set": foreign_prepared, "ranks": [1]}, "pocket_set_invalid"),
        (prepared, {"pocket_set": hsg_pocket_set, "ranks": [1]}, "structure_mismatch"),
        (prepared, {"pocket_set": pocket_set, "ranks": [max_rank + 1]}, "pocket_rank_invalid"),
        (prepared, {"pocket_set": pocket_set, "ranks": [1, 1]}, "pocket_rank_invalid"),
    ]
    for target, pocket, code in cases:
        rejected = _command(client, rid, TOOL, _args(target, pocket=pocket))
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["detail"]["reason_code"] == code, (code, rejected.text)
    # LABELLED FAULT INJECTION: the validated read returns a null-result set, then a lining residue that is not in
    # the structure (neither can come from a real published fpocket result of this structure).
    real = tool_module.validated_pocket_set

    def null_result(view, handle):
        content_, manifest, producer = real(view, handle)
        return {**content_, "null_result": True}, manifest, producer

    def foreign_lining(view, handle):
        content_, manifest, producer = real(view, handle)
        changed = copy.deepcopy(content_)
        changed["pockets"][0]["lining_residues"][0]["seq_auth"] = 9999
        return changed, manifest, producer

    for fault, code in ((null_result, "pocket_set_invalid"), (foreign_lining, "pocket_residue_mismatch")):
        monkeypatch.setattr(tool_module, "validated_pocket_set", fault)
        rejected = _command(client, rid, TOOL, _args(prepared, pocket={"pocket_set": pocket_set,
                                                                      "ranks": [stored["pockets"][0]["rank"]]}))
        assert rejected.status_code == 422 and rejected.json()["detail"]["reason_code"] == code
    assert len(client.calls) == 1
    assert [k for k in _kinds(rid) if k == K.KIND] == [K.KIND]


# --- hydrogen-only residues (no heavy atom) ----------------------------------------------------------------------------

def _hydrogen_only_pdb(ligand_hydrogen_only: bool) -> bytes:
    """SYNTHETIC: ALA 1-3 on a line (10 A apart), GLY 4 with only an H atom, and LIG 501 (one carbon 3 A from ALA 3,
    or only H atoms when ``ligand_hydrogen_only``)."""
    lines, serial = [], 1
    for seq in range(1, 4):
        x = seq * 10.0
        for name, dx, dy, element in (("N", -1.2, 0.0, "N"), ("CA", 0.0, 0.0, "C"), ("C", 1.2, 0.0, "C"),
                                      ("O", 1.2, 1.2, "O"), ("CB", 0.0, -1.5, "C")):
            lines.append(f"ATOM  {serial:5d} {name:<4} ALA A{seq:4d}    {x + dx:8.3f}{dy:8.3f}{0.0:8.3f}"
                         f"  1.00 20.00          {element:>2}")
            serial += 1
    lines.append(f"ATOM  {serial:5d}  H   GLY A   4    {40.0:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           H")
    serial += 1
    ligand = (("H1", 30.0, 3.0, "H"), ("H2", 30.0, 4.0, "H")) if ligand_hydrogen_only else (("C1", 30.0, 3.0, "C"),)
    for name, x, y, element in ligand:
        lines.append(f"HETATM{serial:5d} {name:<4} LIG A 501    {x:8.3f}{y:8.3f}{0.0:8.3f}  1.00 20.00          "
                     f"{element:>2}")
        serial += 1
    return ("\n".join(lines) + "\nEND\n").encode()


LIG501 = {"model_number": 1, "chain_auth": "A", "seq_auth": 501, "icode": "", "resname": "LIG"}


def _prepared_keeping_hydrogens(client, rid, raw: bytes) -> str:
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": "synthetic_h_only.pdb"}, content=raw,
                         headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    structure = _command(client, rid, "load_structure", {"source": upload.json()["upload_id"]})
    assert structure.status_code == 200, structure.text
    prepared = _command(client, rid, "prepare_structure", {"structure": structure.json()["handle"]["handle"],
                                                           "hydrogens": "keep"})
    assert prepared.status_code == 200, prepared.text
    return prepared.json()["handle"]["handle"]


def test_hydrogen_only_position_with_a_ligand_is_stored_with_a_null_distance(client):
    rid = _http_run(client)
    prepared = _prepared_keeping_hydrogens(client, rid, _hydrogen_only_pdb(False))
    made = _command(client, rid, TOOL, _args(prepared, residues=[res(3, "ALA"), res(4, "GLY")], ligand=LIG501))
    assert made.status_code == 200, made.text
    handle = made.json()["handle"]["handle"]
    stored = api_module._run(rid).store.load(handle)
    by_seq = {p["residue"]["seq_auth"]: p for p in stored["positions"]}
    assert by_seq[4]["ligand_min_distance_A"] is None   # no heavy atom: null, never 0
    # independent oracle: the nearest ALA 3 heavy atom to LIG C1 (30, 3, 0)
    oracle = min(math.dist((30.0 + dx, dy, 0.0), (30.0, 3.0, 0.0))
                 for dx, dy in ((-1.2, 0.0), (0.0, 0.0), (1.2, 0.0), (1.2, 1.2), (0.0, -1.5)))
    assert by_seq[3]["ligand_min_distance_A"] == pytest.approx(oracle, abs=1e-9)
    base = f"/runs/{rid}/mutation_candidate_sets"
    listed = client.get(base)
    assert listed.status_code == 200 and [r["valid"] for r in listed.json()["rows"] if r["handle"] == handle] == [True]
    for sub in ("", "/positions", "/candidates"):
        read = client.get(f"{base}/{handle}{sub}")
        assert read.status_code == 200, (sub, read.text)
    report = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert report.status_code == 201, report.text
    minimum = [c for c in report.json()["manifest"]["claims"] if c["statement_id"] == "ligand_min_distance_A"]
    assert len(minimum) == 1 and minimum[0]["exact_value"] == by_seq[3]["ligand_min_distance_A"]


def test_hydrogen_only_ligand_is_ligand_invalid_before_the_implementation(client):
    rid = _http_run(client)
    prepared = _prepared_keeping_hydrogens(client, rid, _hydrogen_only_pdb(True))
    for args in (_args(prepared, residues=[res(3, "ALA")], ligand=LIG501),
                 _args(prepared, ligand_shell={"radius_A": 5.0}, ligand=LIG501)):
        rejected = _command(client, rid, TOOL, args)
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["detail"]["reason_code"] == "ligand_invalid"
    assert client.calls == [] and K.KIND not in _kinds(rid)


def test_a_built_set_that_does_not_validate_is_never_stored(client, monkeypatch):
    """LABELED FAULT INJECTION: the builder returns content that fails ``validated_set``."""
    rid = _http_run(client)
    prepared = _prepared_keeping_hydrogens(client, rid, _hydrogen_only_pdb(False))
    build = tool_module.mc.build_candidate_set

    def broken(*args, **kwargs):
        content = build(*args, **kwargs)
        content["positions"][0]["ligand_min_distance_A"] = 0
        return content

    monkeypatch.setattr(tool_module.mc, "build_candidate_set", broken)
    failed = _command(client, rid, TOOL, _args(prepared, residues=[res(3, "ALA")], ligand=LIG501))
    assert failed.status_code == 422, failed.text
    assert failed.json()["error"] == "input_invalid"
    assert failed.json()["detail"]["reason_code"] == "candidate_set_invalid"
    assert K.KIND not in _kinds(rid)


# --- M26 v2: catalytic residue protection through the tool (spec 8) ---------------------------------------------------

def _syn(run):
    return _prepare(run, _load(run, SYN))


def _rows_by_status(result, chains):
    """Independent re-derivation from the stored result: (matched entries by residue, conflict items, unmatched items)
    of the named chains whose M-CSA section is covered, in chain order then (mcsa_id, residue_index)."""
    matched, lists = {}, {"conflict": [], "unmatched": []}
    by_chain = {c["chain_auth"]: c for c in result["chains"]}
    for chain in chains:
        mcsa = by_chain[chain]["mcsa"]
        if mcsa["coverage"] != "covered":
            continue
        for row in sorted(mcsa["rows"], key=lambda r: (r["mcsa_id"], r["residue_index"])):
            if row["status"] == "matched":
                key = json.dumps(row["residue"], sort_keys=True)
                matched.setdefault(key, []).append({"mcsa_id": row["mcsa_id"], "residue_index": row["residue_index"],
                                                    "is_reference": row["is_reference"]})
            else:
                lists[row["status"]].append({
                    "chain_auth": chain, "mcsa_id": row["mcsa_id"], "residue_index": row["residue_index"],
                    "reason": row["reason"], "residue": row["residue"],
                    "listed": {k: row["listed"][k] for k in ("chain_name", "resid", "auth_resid", "code")}})
    return matched, lists["conflict"], lists["unmatched"]


CAT_RESIDUES = [res(2, "ALA"), res(5, "CYS"), res(6, "HID"), {**res(10, "LEU")}, res(26, "ASP"), res(2, "ALA", "B"),
                res(6, "HID", "B")]


def test_catalytic_protection_from_a_real_reaction_result(tmp_path, reaction):
    run, calls = _run(tmp_path)
    prepared = _syn(run)
    knowledge = CF.link(run, prepared, ["A", "B"])
    result = run.store.load(knowledge)
    out = run.call(TOOL, _args(prepared, residues=CAT_RESIDUES, protected_residues=[res(5, "CYS")],
                               released_residues=[res(26, "ASP")], catalytic_annotation=knowledge))
    content = run.store.load(out.handle)
    assert content["method_version"] == "mw.mutation_candidates/v2" and len(calls) == 1
    by = {(p["residue"]["chain_auth"], p["residue"]["seq_auth"]): p for p in content["positions"]}
    entry = {"mcsa_id": 601, "residue_index": 0, "is_reference": True}
    expected = {("A", 2): [{"mcsa_id": 601, "residue_index": 7, "is_reference": True}],
                ("A", 5): [{"mcsa_id": 601, "residue_index": 6, "is_reference": True}],
                ("A", 6): [entry, {"mcsa_id": 602, "residue_index": 0, "is_reference": False}],
                ("A", 10): [],    # only an unmatched (ambiguous number) row names 10: checked, not protected
                ("A", 26): [{"mcsa_id": 601, "residue_index": 1, "is_reference": False}],   # a non-reference row too
                ("B", 2): [{"mcsa_id": 601, "residue_index": 9, "is_reference": True}],
                ("B", 6): [{"mcsa_id": 601, "residue_index": 8, "is_reference": True}]}
    assert {key: p["protection"]["catalytic"] for key, p in by.items()} == expected
    matched, conflicts, unmatched = _rows_by_status(result, ["A", "B"])
    for p in content["positions"]:      # every matched row of the same 7 fields protects, nothing else does
        assert p["protection"]["catalytic"] == matched.get(json.dumps(p["residue"], sort_keys=True), [])
        assert ("catalytic_residue" in p["protection"]["reasons"]) == bool(p["protection"]["catalytic"])
    assert by[("A", 5)]["protection"]["reasons"] == ["user_protected", "disulfide_cys", "catalytic_residue"]
    assert by[("A", 2)]["exclusion_reasons"] == ["metal_contact", "catalytic_residue"]
    assert by[("A", 26)]["protection"]["released"] is True and by[("A", 26)]["status"] == "candidate"
    assert by[("A", 26)]["protection"]["reasons"] == ["catalytic_residue"]   # released: the reason list stays
    assert content["protection_checks"]["catalytic_residue_database"] == {
        "status": "checked", "reason": None, "annotation": knowledge, "covered_chains": ["A", "B"],
        "uncovered_chains": [], "matched_rows": 9, "conflict_rows": 2, "unmatched_rows": 4,
        "conflicts": conflicts, "unmatched": unmatched}
    assert [(i["chain_auth"], i["mcsa_id"], i["residue_index"], i["reason"]) for i in conflicts] == [
        ("A", 601, 2, "residue_name_differs"), ("B", 601, 10, "mcsa_rows_disagree")]
    assert conflicts[0]["residue"]["resname"] == "MSE" and conflicts[1]["residue"] is None
    assert conflicts[1]["listed"] == {"chain_name": "B", "resid": 13, "auth_resid": 13, "code": "Asn/Asp"}
    assert [(i["residue_index"], i["reason"]) for i in unmatched] == [
        (3, "ambiguous_residue_number"), (4, "residue_not_in_structure"), (5, "no_author_number"),
        (11, "non_standard_code")]
    assert unmatched[2]["listed"] == {"chain_name": "A", "resid": None, "auth_resid": None, "code": "Cys"}
    assert content["counts"]["exclusion_reason_counts"]["catalytic_residue"] == 5   # A2 A5 A6 B2 B6 (A26 released)
    assert content["limitations"][2] == K.LIMITATION_3_CHECKED


@pytest.mark.parametrize("coverage", ["chain_not_listed", "not_in_annotation", "pdb_not_in_snapshot", "not_checked"])
def test_catalytic_uncovered_chains_through_the_tool(tmp_path, reaction, coverage):
    run, _ = _run(tmp_path)
    prepared = _syn(run)
    residues = [res(6, "HID"), res(6, "HID", "B"), res(1, "HIE", "CC")]
    if coverage == "chain_not_listed":
        knowledge = CF.link(run, prepared, ["A", "B", "CC"])
    elif coverage == "not_in_annotation":
        knowledge = CF.link(run, prepared, ["A", "B"])
    elif coverage == "pdb_not_in_snapshot":
        knowledge = CF.link(run, prepared, ["A", "B", "CC"], pdb_id=CF.OTHER_PDB_ID)
    else:
        knowledge = CF.link(run, prepared, ["A", "B", "CC"], pdb_id=None)
    content = run.store.load(run.call(TOOL, _args(prepared, residues=residues,
                                                  catalytic_annotation=knowledge)).handle)
    check = content["protection_checks"]["catalytic_residue_database"]
    assert (check["status"], check["reason"]) == ("not_checked", "chains_not_covered")
    by = {p["residue"]["chain_auth"]: p for p in content["positions"]}
    assert by["CC"]["protection"]["catalytic"] is None
    if coverage in ("chain_not_listed", "not_in_annotation"):
        assert check["covered_chains"] == ["A", "B"]
        assert check["uncovered_chains"] == [{"chain_auth": "CC", "coverage": coverage}]
        assert (check["matched_rows"], check["conflict_rows"], check["unmatched_rows"]) == (9, 2, 4)
        assert by["A"]["protection"]["reasons"] == ["catalytic_residue"]       # covered chains still protect
        assert by["B"]["protection"]["catalytic"] == [{"mcsa_id": 601, "residue_index": 8, "is_reference": True}]
    else:
        assert check["covered_chains"] == []
        assert check["uncovered_chains"] == [{"chain_auth": c, "coverage": coverage} for c in ("A", "B", "CC")]
        assert (check["matched_rows"], check["conflict_rows"], check["unmatched_rows"]) == (0, 0, 0)
        assert check["conflicts"] == [] and check["unmatched"] == []
        assert all(p["protection"]["catalytic"] is None and not p["protection"]["reasons"]
                   for p in content["positions"])
    assert content["limitations"][2] == K.LIMITATION_3_NOT_CHECKED


def _synthetic_numbering_map(run, structure):
    """LABELLED SYNTHETIC residue_numbering_map@1 object (hand-built, not an M15 result): chain A residue LEU A10 at
    position 10 of the synthetic accession Q0SYN1, whose T2 UniProt row has an Active site at 10."""
    from mw import reaction_knowledge as rk
    from mw.tools.registry import ToolContext
    from mw.tools.structural import _parse
    residues = rk.chain_polymer_residues(_parse(ToolContext(store=run.store, call_id="test"), structure))
    (a10,) = [r for r in residues["A"] if r["seq_auth"] == 10 and r["icode"] == ""]
    row = {"residue": dict(a10), "status": "mapped", "uniprot_accession": "Q0SYN1", "uniprot_position": 10,
           "uniprot_residue": "L", "residue_match": True, "klifs_index": None, "klifs_label": None,
           "klifs_match": None, "conflict_reason": None, "sifts": None, "alignment": None}
    content = {"schema": "residue_numbering_map@1", "method_version": "mw.residue_numbering/v1",
               "structure": {"handle": structure, "structure_kind": "prepared_structure", "model_number": 1},
               "pdb_id": CF.PDB_ID, "chains": [{"chain_auth": "A", "requested_uniprot_accession": "Q0SYN1",
                                                "methods_run": ["local_alignment"]}],
               "rows": [row], "null_result": False, "fixture": "SYNTHETIC constructed numbering map (not M15 output)"}
    return run.store.put("residue_numbering_map", "residue_numbering_map@1", content,
                         produced_by="synthetic_fixture").handle


def test_uniprot_sites_never_protect(tmp_path, reaction):
    run, _ = _run(tmp_path)
    prepared = _syn(run)
    knowledge = CF.link(run, prepared, ["A"], accessions={"A": "Q0SYN1"},
                        numbering_map=_synthetic_numbering_map(run, prepared))
    chain = run.store.load(knowledge)["chains"][0]
    linked = [link for f in chain["uniprot"]["features"] if f["type"] == "Active site" for link in f["links"] or []
              if link["status"] == "mapped"]
    assert linked and linked[0]["residue"]["seq_auth"] == 10          # a UniProt Active site linked to LEU A10
    content = run.store.load(run.call(TOOL, _args(prepared, residues=[res(10, "LEU")],
                                                  catalytic_annotation=knowledge)).handle)
    (a10,) = content["positions"]
    assert a10["protection"]["catalytic"] == [] and a10["protection"]["reasons"] == []
    assert a10["status"] == "candidate"


def test_catalytic_list_cap_is_429_and_nothing_is_stored(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    CF.activate(root, monkeypatch, long_unmatched=401)     # 4 + 401 unmatched rows on chain A
    try:
        run, calls = _run(tmp_path)
        prepared = _syn(run)
        knowledge = CF.link(run, prepared, ["A"])
        before = len(_events(run, "object_created"))
        with pytest.raises(ToolFailure) as caught:
            run.call(TOOL, _args(prepared, residues=[res(6, "HID")], catalytic_annotation=knowledge))
        assert caught.value.cls == FailureClass.resource_exceeded
        assert caught.value.detail == {"reason_code": "catalytic_list_too_long", "list": "unmatched", "count": 405,
                                       "limit": 400}
        assert len(calls) == 1 and not [e for e in _events(run, "object_created")[before:] if e["kind"] == K.KIND]
        CF.activate(root, monkeypatch, long_unmatched=396, imported_at="2026-10-08T00:00:01Z")   # exactly 400
        at_limit = CF.link(run, prepared, ["A"])
        content = run.store.load(run.call(TOOL, _args(prepared, residues=[res(6, "HID")],
                                                      catalytic_annotation=at_limit)).handle)
        check = content["protection_checks"]["catalytic_residue_database"]
        assert check["unmatched_rows"] == len(check["unmatched"]) == 400 and check["status"] == "checked"
    finally:
        CF.reset_caches()


def test_v2_set_differs_from_the_stored_v1_set_of_the_same_input_only_in_the_m26_fields(tmp_path):
    fixture = json.loads((FIX / "reaction" / "t1" / "m20-v1-candidate-set-golden_m24_mutation.json").read_text())
    v1 = fixture["content"]
    run = new_run(tmp_path / "runs", run_id="golden_m24_mutation", dry_run=False)
    prepared = _prepare(run, _load(run, CIF_1UBQ))
    assert prepared == v1["structure"]["handle"]
    out = run.call(TOOL, _args(prepared, residues=[res(1, "MET"), res(44, "ILE"), res(48, "LYS")]))
    assert out.handle != fixture["handle"]
    v2 = run.store.load(out.handle)
    assert v2["method_version"] == "mw.mutation_candidates/v2"
    expected = copy.deepcopy(v1)     # v1 + exactly the M26 spec 8.6 changes
    expected["method_version"] = "mw.mutation_candidates/v2"
    expected["parameters"]["catalytic_annotation"] = None
    for p in expected["positions"]:
        p["protection"]["catalytic"] = None
    expected["protection_checks"]["catalytic_residue_database"] = {"status": "not_checked",
                                                                   "reason": "annotation_not_given", "annotation": None}
    expected["counts"]["exclusion_reason_counts"]["catalytic_residue"] = 0
    expected["limitations"][2] = K.LIMITATION_3_NOT_CHECKED
    assert v2 == expected
