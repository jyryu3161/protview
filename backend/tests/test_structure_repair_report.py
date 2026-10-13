"""M29 T9: the structure repair report (``analysis_type: "structure_repair"``, ``structure_repair_markdown@1``; spec
.dryforge/spec.md 7, 3.5-3.7, 6.3).

Inputs (every one labelled):

* Public 8VF6 (RCSB, CC0), 1CLL and 1RNH fixtures, loaded and prepared by the product (``strip_all``), then repaired
  through the product repair job (``pdbfixer_repair_v1``: admission, approval, the server's checks 1-5 and the M7
  preflight, the four objects and ``structure_repair_published``) whose worker is the LABELLED simulated guardian of the
  T7 tests (``test_structure_repair_handoff._store_repaired``): its output carries the PDBFixer-MEASURED additions of
  ``fixtures/structure_repair/<id>-additions.pdbfixer-measured.json`` (T1 / T4, real PDBFixer 1.12.0 output, seed 1;
  T5 checks that the real worker returns exactly these rows for 8VF6) instead of launching PDBFixer.
  8VF6: chain parts, 23 side chains, two gaps, two OXT. 1CLL: one side chain and an OXT, no gap (a calcium ion and an
  ethanol are the metal / ligand partners). 1RNH: three MSE residues and an OXT.
* Fault injections (labelled): edited reports, claims and manifests stored in events-only copies of a run (the shared
  runs stay untouched), an unpublished record stored with ``store.put``, and the installed template made unavailable
  (``structure_repair._templates`` raises ``openmm_unavailable``).

Expected values come from the input files (``structure_repair_lane_fixture.oracle``: the unobserved-residue listing
and the installed template; gemmi reads of the prepared input) and from the stored repaired mmCIF read with gemmi
(``_atom_site.calc_flag``, partner atoms), never from the record or the report.
"""
from __future__ import annotations

import ast
import copy
import json
import math
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import gemmi
import pytest
import structure_repair_lane_fixture as F
from fastapi.testclient import TestClient
from test_structure_repair_handoff import _measured, _prepared, _store_repaired

from mw import structure_repair as sr
from mw import structure_repair_bundle as bundle
from mw import structure_repair_constants as K
from mw import structure_repair_jobs as RJ
from mw import structure_repair_reports as srr
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError, _md
from mw.tools import openmm_method
from mw.workspace import new_run

MW = Path(__file__).resolve().parents[1] / "mw"
NAMES = ("8vf6", "1cll", "1rnh")
RID = {name: f"run_m29_t9_{name}" for name in NAMES}
SIDE, OXT, GAP, CHAIN, MSE = ("side_chain_atoms_added", "terminal_oxt_added", "internal_gap_filled",
                              "chain_parts_merged", "nonstandard_replaced")
RP1 = "보완 구조의 추가 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다."
RP2 = "실험으로 관측한 원자의 좌표는 입력 그대로이며 추가·치환·원자 순서 변경만 기록했다."
RP3 = "메운 틈 구간은 단순한 기하로 놓은 가상 좌표이며 실제 구조가 아니다."
RP4 = "사슬의 관측된 끝이 서열의 끝과 다른 곳에도 말단 원자를 두었으므로 그 끝의 화학은 실제와 다를 수 있다."
RP5 = "MSE는 MET로 바꾸었고 셀레늄 원자는 황 원자로 대체했다. 원래 이름은 보완 기록에 있다."
RP6 = "같은 저자 체인 이름의 조각을 한 체인으로 합쳐 원자 순서가 바뀌었다. 잔기 식별자와 좌표는 그대로이다."
NO_PARTNER = "— (상대 없음: 이 분류의 비이웃 중원자가 보완 구조에 없다)"
FORBIDDEN = ("안정성", "ΔΔG", "순위", "추천", "최적", "개선", "활성", "예측", "유망", "좋은", "나쁜", "안전", "점수", "에너지",
             "수소결합", "stability", "rank", "recommend", "optimal", "improv", "activ", "predict", "promising", "good",
             "safe", "score", "energy", "hydrogen", "충돌 없음", "best")
METAL_NAMES = {"ZN", "MG", "CA", "MN", "FE", "CU", "CO", "NI", "NA", "K"}   # the M7 / M20 metal list, spelled out here


# --- world ------------------------------------------------------------------------------------------------------------

def _report(client: TestClient, rid: str, handle: str) -> dict:
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("m29_t9_report") / "runs"
    w = {"root": root}
    for name in NAMES:
        run = new_run(root, run_id=RID[name], dry_run=False)
        prepared = _prepared(run, F.public(name), f"public_{name}.cif")
        repaired = _store_repaired(run, prepared, _measured(name))
        w[name] = {"rid": RID[name], "prepared": prepared, "structure": repaired["structure"],
                   "record_handle": repaired["record_handle"], "record": repaired["record"], "raw": repaired["raw"]}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(api_module, "RUNS_DIR", root)
        api_module.RUNS.clear()
        try:
            client = TestClient(api_module.app, base_url="http://127.0.0.1")
            for name in NAMES:
                w[name]["report"] = _report(client, RID[name], w[name]["record_handle"])
        finally:
            api_module.RUNS.clear()
    return w


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    yield TestClient(api_module.app, base_url="http://127.0.0.1")
    api_module.RUNS.clear()


def _claims(manifest: dict) -> dict[tuple, dict]:
    return {(c["statement_id"], c["field_path"], json.dumps(c["row_selector"], sort_keys=True)): c
            for c in manifest["claims"]}


def _value(manifest: dict, statement: str, path: str, selector=None):
    return _claims(manifest)[(statement, path, json.dumps(selector, sort_keys=True))]["exact_value"]


def _read(raw: bytes) -> gemmi.Model:
    return gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())[0]


def _input(store, prepared: str) -> dict:
    """From the stored prepared input read with gemmi (not the record): atoms, occupancy-0 atoms, waters, MSE residues
    and the author chain names that come in more than one part."""
    model = _read(store.load(store.load(prepared)["coordinates"]))
    names = [chain.name for chain in model]
    atoms = [atom for chain in model for res in chain for atom in res]
    return {"atoms": len(atoms), "zero_occupancy": sum(atom.occ == 0 for atom in atoms),
            "waters": sum(res.is_water() for chain in model for res in chain),
            "mse": sum(res.name == "MSE" for chain in model for res in chain),
            "split_chains": sorted({name for name in names if names.count(name) > 1})}


def _repaired(raw: bytes) -> dict:
    """From the stored repaired mmCIF read with gemmi (not the record): the new atoms (``calc_flag = c``), the residues
    made only of new atoms, the observed atoms and the author chain names."""
    model = _read(raw)
    new = [atom for chain in model for res in chain for atom in res if atom.calc_flag == gemmi.CalcFlag.Calculated]
    whole = [res for chain in model for res in chain
             if len(res) and all(atom.calc_flag == gemmi.CalcFlag.Calculated for atom in res)]
    observed = sum(atom.calc_flag != gemmi.CalcFlag.Calculated for chain in model for res in chain for atom in res)
    return {"new_atoms": len(new), "new_residues": len(whole), "observed": observed,
            "chains": [chain.name for chain in model]}


def _half_up(value: float) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


# --- counts against the input file and the stored structure ------------------------------------------------------

def test_8vf6_report_counts_equal_the_input_file_and_the_stored_structure(world):
    w = world["8vf6"]
    manifest, markdown = w["report"]["manifest"], w["report"]["markdown"]
    run = new_run(world["root"], run_id=w["rid"], dry_run=False)
    oracle = F.oracle("8vf6")
    given = _input(run.store, w["prepared"])
    made = _repaired(run.store.load(run.store.load(w["structure"])["coordinates"]))
    # the independent expectation: 23 side chains (A 10, B 13), gaps of 13 and 11, two OXT, chains A and B in parts
    assert len(oracle["side_chain_residues"]) == 23
    assert [chain for chain, _ in oracle["side_chain_residues"]].count("A") == 10
    assert oracle["gap_lengths"] == {"A": [13], "B": [11]} and oracle["terminal_oxt"] == 2
    assert given["split_chains"] == ["A", "B"] and made["chains"] == ["A", "B"]
    assert made["new_atoms"] == oracle["added_atoms"] and made["new_residues"] == oracle["added_residues"] == 24
    assert made["observed"] == given["atoms"]
    gap_atoms = oracle["added_atoms"] - oracle["side_chain_atoms"] - oracle["terminal_oxt"]
    expected = [
        (("added_residue_count", "counts.added_residues", None), oracle["added_residues"]),
        (("added_atom_count", "counts.added_atoms", None), oracle["added_atoms"]),
        (("added_atom_count", "added_atoms[*].origin", {"origin": "side_chain"}), oracle["side_chain_atoms"]),
        (("added_atom_count", "added_atoms[*].origin", {"origin": "oxt"}), oracle["terminal_oxt"]),
        (("added_atom_count", "added_atoms[*].origin", {"origin": "gap_residue"}), gap_atoms),
        (("side_chain_residue_count", "counts.side_chain_residues", None), 23),
        (("terminal_oxt_count", "counts.terminal_oxt", None), 2),
        (("gap_count", "counts.gaps", None), 2),
        (("replaced_count", "counts.replaced", None), given["mse"]),
        (("chain_parts_merged_count", "counts.chain_parts_merged", None), len(given["split_chains"])),
        (("unchanged_atom_count", "unchanged.atom_count", None), given["atoms"]),
        (("zero_occupancy_input_atom_count", "zero_occupancy_input_atoms.count", None), given["zero_occupancy"]),
        (("zero_occupancy_input_atom_count", "zero_occupancy_input_atoms.residues", None), 0),
    ]
    for (statement, path, selector), value in expected:
        assert _value(manifest, statement, path, selector) == value, (statement, path, selector)
    lengths = [claim for claim in manifest["claims"] if claim["field_path"].startswith("gaps[")]
    assert [(c["subject"]["chain_auth"], c["exact_value"]) for c in lengths] == [("A", 13), ("B", 11)]
    # every claim is computed evidence citing this record; the scope lists exactly the classes the counts show
    assert {c["statement_id"] for c in manifest["claims"]} == set(K.REPORT_STATEMENT_IDS)
    for claim in manifest["claims"]:
        assert (claim["evidence_kind"], claim["source_handle"], claim["source_kind"], claim["source_schema"],
                claim["source_sha256"], claim["reference"]) == (
            "computed", w["record_handle"], "structure_repair", "structure_repair@1",
            w["record_handle"].rsplit("/", 1)[-1], None)
    assert _value(manifest, "repair_scope", "classes_applied") == [CHAIN, SIDE, OXT, GAP]
    assert _value(manifest, "unchanged_atom_count", "unchanged.max_delta_A") <= 1e-9
    # the report states the modelling facts: handles, the observed atoms unchanged, RP1 RP2 RP3 RP4 RP6 in order
    assert manifest["repaired_structure"] == w["structure"] and manifest["source_structure"] == w["prepared"]
    assert (f"Result: {_md(w['record_handle'])} ({_md('structure_repair@1')})" in markdown and
            f"- 보완 구조: {_md(w['structure'])}" in markdown and
            f"- 보완 전 원본 전처리 구조: {_md(w['prepared'])}" in markdown)
    assert f"- 실험으로 관측한 입력 원자: {given['atoms']}개, 좌표 그대로 (최대 이동 " in markdown
    assert oracle["unobserved_tails"] is True   # the file lists unobserved chain ends: RP4
    assert manifest["limitations"] == [RP1, RP2, RP3, RP4, RP6] == list(K.LIMITATION_ORDER[:4]) + [K.RP6]
    tail = markdown[markdown.index("\n## Limitations\n"):]
    assert [line for line in tail.split("\n") if line.startswith(("보완", "실험", "메운", "사슬", "MSE", "같은"))] == [
        RP1, RP2, RP3, RP4, RP6]
    assert RP5 not in markdown and markdown.count(RP1) == 1


def test_a_repair_without_gaps_lists_no_gap_class_and_mse_lists_the_replacement(world):
    cll, rnh = world["1cll"], world["1rnh"]
    oracle = F.oracle("1cll")
    assert all(runs == [] for runs in oracle["gaps"].values()) and oracle["added_residues"] == 0
    manifest, markdown = cll["report"]["manifest"], cll["report"]["markdown"]
    assert _value(manifest, "repair_scope", "classes_applied") == manifest["classes_applied"] == [SIDE, OXT]
    assert GAP not in markdown and "internal\\_gap\\_filled" not in markdown and RP3 not in markdown
    assert "\n## 메운 틈\n" not in markdown and "\n## 치환 잔기\n" not in markdown
    assert _value(manifest, "gap_count", "counts.gaps") == 0
    assert not [c for c in manifest["claims"] if c["field_path"].startswith("gaps[")]
    assert _value(manifest, "side_chain_residue_count", "counts.side_chain_residues") == len(
        oracle["side_chain_residues"]) == 1
    assert _value(manifest, "added_atom_count", "counts.added_atoms") == oracle["added_atoms"]
    assert manifest["limitations"] == [RP1, RP2, RP4]
    # 1RNH: the three MSE residues of the input are the replaced residues (MSE -> MET, SE -> SD, HETATM -> ATOM)
    run = new_run(world["root"], run_id=rnh["rid"], dry_run=False)
    given = _input(run.store, rnh["prepared"])
    manifest, markdown = rnh["report"]["manifest"], rnh["report"]["markdown"]
    assert given["mse"] == 3 == _value(manifest, "replaced_count", "counts.replaced")
    assert _value(manifest, "repair_scope", "classes_applied") == [OXT, MSE]
    rows = [line for line in markdown.split("\n") if line.startswith("| MSE auth")]
    assert len(rows) == 3 and all("| MET auth" in row and "SE → SD" in row and "HETATM → ATOM" in row for row in rows)
    assert manifest["limitations"] == [RP1, RP2, RP4, RP5] and RP6 not in markdown and RP3 not in markdown


def test_collision_distances_round_half_up_and_a_class_without_partner_shows_a_dash(world):
    assert (srr.render_distance(0.125), srr.render_distance(2.665), srr.render_distance(2.675),
            srr.render_distance(1.005), srr.render_distance(0.004), srr.render_distance(2)) == (
        "0.13", "2.67", "2.68", "1.01", "0.00", "2.00")   # ROUND_HALF_UP of Decimal(str(v)), not half-even
    for name in NAMES:
        w = world[name]
        manifest, markdown = w["report"]["manifest"], w["report"]["markdown"]
        rows = {line.split(" (", 1)[0].lstrip("| "): line for line in markdown.split("\n")
                if line.startswith("| ") and "(" in line and line.split("(", 1)[1].split(")")[0] in
                K.COLLISION_CLASSES}
        claimed = {c["row_selector"]["partner_class"]: c for c in manifest["claims"]
                   if c["statement_id"] == "collision_min_distance"}
        for partner in K.COLLISION_CLASSES:
            entry = w["record"]["collisions"][partner]
            row = next(line for line in rows.values() if f"({partner})" in line)
            if entry["min_distance_A"] is None:
                assert partner not in claimed
                assert row.endswith(f"| {NO_PARTNER} | 0 | 0 | — |"), row
                continue
            claim = claimed[partner]
            assert (claim["field_path"], claim["unit"], claim["rounding"], claim["exact_value"]) == (
                f"collisions.{partner}.min_distance_A", "angstrom", "distance_2dp", entry["min_distance_A"])
            assert claim["rendered_value"] == _half_up(entry["min_distance_A"])
            assert f"| {_md(claim['rendered_value'])} | {entry['count_lt_2_0']} | {entry['count_lt_1_5']} |" in row
        # strip_all: the prepared input has no water, so the water class has no partner
        run = new_run(world["root"], run_id=w["rid"], dry_run=False)
        assert _input(run.store, w["prepared"])["waters"] == 0 and "water" not in claimed
        assert "충돌 없음" not in markdown
    # 1CLL metal and ligand partners: the minimum computed here from the repaired mmCIF with gemmi
    w = world["1cll"]
    model = _read(w["raw"])
    new = [atom.pos for chain in model for res in chain for atom in res if atom.calc_flag == gemmi.CalcFlag.Calculated]
    partners: dict[str, list] = {"metal": [], "ligand": []}
    for chain in model:
        for res in chain:
            if res.het_flag != "H" or res.is_water():
                continue
            kind = "metal" if res.name in METAL_NAMES else "ligand"
            partners[kind].extend(atom.pos for atom in res if atom.element.name not in ("H", "D"))
    claimed = {c["row_selector"]["partner_class"]: c for c in w["report"]["manifest"]["claims"]
               if c["statement_id"] == "collision_min_distance"}
    for kind, positions in partners.items():
        assert positions, kind
        low = min(a.dist(b) for a in new for b in positions)
        assert math.isclose(claimed[kind]["exact_value"], low, rel_tol=1e-12, abs_tol=1e-12)
        assert claimed[kind]["rendered_value"] == _half_up(low)


# --- byte identity, nothing repaired again, list and download -----------------------------------------------------

def test_create_reopen_and_download_give_the_stored_bytes_and_nothing_is_repaired_again(world, client, monkeypatch):
    w = world["1cll"]
    root, rid = world["root"], w["rid"]
    for target, name in ((JobQueue, "_supervise"), (JobQueue, "submit"), (JobQueue, "start"), (sr, "build_repaired"),
                         (RJ, "prepared_objects"), (RJ, "m7_check"), (bundle, "store"), (openmm_method, "preflight")):
        monkeypatch.setattr(target, name, F.forbid)
    before = F.events(root, rid)
    objects = F.store_state(root, rid)
    built = _report(client, rid, w["record_handle"])
    after = F.events(root, rid)
    # a new manifest and its event only: the Markdown of the same record is the same bytes, so the content-addressed
    # store keeps the one Markdown object of the first report (no repair object, job or publication event)
    assert [(event["type"], event.get("kind")) for event in after[len(before):]] == [
        ("object_created", "method_report_manifest"), ("method_report_created", None)]
    assert after[:len(before)] == before
    assert F.store_state(root, rid)[1] == objects[1] + 1 and F.store_state(root, rid)[2] == objects[2]
    manifest, markdown = built["manifest"], built["markdown"]
    assert built["markdown_handle"] == w["report"]["markdown_handle"] and built["handle"] != w["report"]["handle"]
    assert (manifest["schema"], manifest["analysis_type"], manifest["render_version"], manifest["status"]) == (
        "method_report_manifest@1", "structure_repair", "structure_repair_markdown@1", "complete")
    assert set(manifest) == srr.MANIFEST_KEYS
    # the same record gives the same claims and Markdown (only the snapshot and the handles of the report differ)
    first = w["report"]
    assert manifest["claims"] == first["manifest"]["claims"] and markdown == first["markdown"]
    # reopen and download: the stored bytes
    again = client.get(f"/runs/{rid}/reports/selected", params={"handle": built["handle"]})
    assert again.status_code == 200, again.text
    assert again.json()["markdown"] == markdown and canonical_json(again.json()["manifest"]) == canonical_json(manifest)
    run = new_run(root, run_id=rid, dry_run=False)
    stored_md = run.store.load(built["markdown_handle"])
    md = client.get(f"/runs/{rid}/reports/download", params={"handle": built["handle"]})
    assert md.status_code == 200 and md.content == stored_md == markdown.encode("utf-8")
    assert md.headers["content-type"].startswith("text/markdown")
    as_json = client.get(f"/runs/{rid}/reports/download", params={"handle": built["handle"], "format": "json"})
    assert as_json.status_code == 200 and as_json.content == canonical_json(run.store.load(built["handle"]))
    assert json.loads(as_json.content) == manifest
    # the report list: the kind and the record; the Markdown names the list name
    listed = client.get(f"/runs/{rid}/reports")
    assert listed.status_code == 200, listed.text
    rows = [row for row in listed.json() if row["handle"] == built["handle"]]
    assert rows == [{"handle": built["handle"], "result_handle": w["record_handle"],
                     "analysis_type": "structure_repair", "markdown_handle": built["markdown_handle"],
                     "created_seq": after[-1]["seq"],
                     "snapshot_event_seq": manifest["snapshot"]["event_seq"]}]
    assert K.REPORT_LIST_NAME == "구조 보완 보고서" and markdown.split("\n", 1)[0] == "# 구조 보완 보고서 (structure repair)"
    # reading wrote nothing
    assert F.events(root, rid) == after


def test_events_only_reopening_gives_the_same_bytes(world, tmp_path):
    for name in NAMES:
        w = world[name]
        root = _copy(world, w["rid"], tmp_path / name)
        run = new_run(root, run_id=w["rid"], dry_run=False)
        reopened = srr.saved_structure_repair_report(run, w["report"]["handle"])
        assert reopened["markdown"] == w["report"]["markdown"]
        assert canonical_json(reopened["manifest"]) == canonical_json(w["report"]["manifest"])


# --- invalid evidence -------------------------------------------------------------------------------------------------

def _copy(world, rid: str, base: Path) -> Path:
    """An events-only copy of one run of the world (forgeries go there, the shared run stays untouched)."""
    root = base / "copy"
    (root / rid).mkdir(parents=True)
    shutil.copyfile(world["root"] / rid / "events.jsonl", root / rid / "events.jsonl")
    return root


def _forge(run, manifest: dict, markdown: str, label: str) -> str:
    """Fault injection: store an edited report and its creation event the way the builder does (the Markdown gets a
    last line naming the forgery, so each forgery has its own Markdown object)."""
    markdown = f"{markdown}<!-- forged T9 report: {label} -->\n"
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by="forged_t9_report", summary={"result_handle": manifest["result_handle"]})
        forged = {**manifest, "markdown_handle": md.handle}
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_t9_report",
                               summary={"result_handle": forged["result_handle"], "analysis_type": "structure_repair",
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def _claim_at(manifest: dict, statement: str, path: str) -> dict:
    found = [c for c in manifest["claims"] if c["statement_id"] == statement and c["field_path"] == path]
    assert len(found) == 1, (statement, path)
    return found[0]


def _edits(world) -> list[tuple[str, dict, str, str]]:
    """(label, edited manifest, Markdown, the refusal it must give) for the 8VF6 report."""
    base = world["8vf6"]["report"]
    other = world["1cll"]
    out = []

    def edit(label: str, change, expected: str, markdown: str | None = None) -> None:
        manifest = copy.deepcopy(base["manifest"])
        change(manifest)
        out.append((label, manifest, base["markdown"] if markdown is None else markdown, expected))

    def plus_one(m):   # a count one too high (value and text)
        claim = _claim_at(m, "added_atom_count", "counts.added_atoms")
        claim["exact_value"] += 1
        claim["rendered_value"] = str(claim["exact_value"])
    edit("count +1", plus_one, "structure_repair_claim_binding_mismatch")

    def gap_plus_one(m):
        claim = _claim_at(m, "gap_count", "gaps[0].length")
        claim["exact_value"] += 1
        claim["rendered_value"] = str(claim["exact_value"])
    edit("gap length +1", gap_plus_one, "structure_repair_claim_binding_mismatch")

    def one_decimal(m):   # another rounding of the same stored distance
        claim = _claim_at(m, "collision_min_distance", "collisions.protein.min_distance_A")
        claim["rendered_value"] = f"{claim['exact_value']:.1f}"
    edit("rounding to one decimal", one_decimal, "structure_repair_claim_binding_mismatch")

    def three_decimals(m):
        claim = _claim_at(m, "collision_min_distance", "collisions.protein.min_distance_A")
        claim["rendered_value"] = f"{claim['exact_value']:.3f}"
    edit("rounding to three decimals", three_decimals, "structure_repair_claim_binding_mismatch")

    def other_record_claim(m):   # mixed evidence: a claim citing the 1CLL record (another run)
        foreign = _claim_at(other["report"]["manifest"], "added_atom_count", "counts.added_atoms")
        m["claims"] = [foreign if c["field_path"] == "counts.added_atoms" else c for c in m["claims"]]
    edit("claim of another record", other_record_claim, "structure_repair_claim_source_mismatch")

    def other_record_rows(m):   # mixed evidence: the side chain rows of the 1CLL record
        m["side_chain_repairs"] = copy.deepcopy(other["record"]["side_chain_repairs"])
    edit("rows of another record", other_record_rows, "structure_repair_report_field_mismatch: side_chain_repairs")

    def other_run_record(m):   # the other run's record as the report's input
        m["result_handle"] = other["record_handle"]
    edit("record of another run", other_run_record, "structure_repair_record_invalid")

    def unapplied_class(m):
        claim = _claim_at(m, "repair_scope", "classes_applied")
        claim["exact_value"] = [*claim["exact_value"], MSE]
        claim["rendered_value"] = ", ".join(claim["exact_value"])
        m["classes_applied"] = list(claim["exact_value"])
    edit("a class that was not applied", unapplied_class, "structure_repair_claim_binding_mismatch")

    def reordered(m):
        m["limitations"] = [m["limitations"][1], m["limitations"][0], *m["limitations"][2:]]
    edit("limitations reordered", reordered, "structure_repair_report_field_mismatch: limitations")

    def reference_kind(m):
        _claim_at(m, "gap_count", "counts.gaps")["evidence_kind"] = "reference_value"
    edit("reference evidence kind", reference_kind, "structure_repair_claim_evidence_kind_mismatch")

    def outside_statement(m):
        _claim_at(m, "gap_count", "counts.gaps")["statement_id"] = "protein_heavy_atom_count"
    edit("statement outside the closed set", outside_statement, "structure_repair_claim_statement_not_allowed")

    def number_for_a_dash(m):   # a number for the partnerless water class
        claim = copy.deepcopy(_claim_at(m, "collision_min_distance", "collisions.protein.min_distance_A"))
        claim.update(field_path="collisions.water.min_distance_A", row_selector={"partner_class": "water"},
                     exact_value=0.0, rendered_value="0.00")
        m["claims"].append(claim)
    edit("a distance for a class without partner", number_for_a_dash, "structure_repair_claim_field_not_allowed")

    def dropped(m):
        m["claims"] = [c for c in m["claims"] if c["statement_id"] != "collision_min_distance"]
    edit("a claim dropped", dropped, "structure_repair_report_field_mismatch: claims")

    edit("interpretive Markdown", lambda m: None, "structure_repair_report_markdown_mismatch",
         base["markdown"].replace("## Limitations", "순위 1\n\n## Limitations"))
    return out


def test_wrong_mixed_and_other_run_evidence_is_report_evidence_invalid(world, tmp_path, monkeypatch):
    w = world["8vf6"]
    root = _copy(world, w["rid"], tmp_path)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    run = api_module._run(w["rid"])
    for label, manifest, markdown, expected in _edits(world):
        handle = _forge(run, manifest, markdown, label)
        with pytest.raises(EvidenceError, match=expected):
            srr.saved_structure_repair_report(run, handle)
        for route in ("selected", "download"):
            response = client.get(f"/runs/{w['rid']}/reports/{route}", params={"handle": handle})
            assert response.status_code == 422, (label, route, response.text)
            assert response.json()["detail"]["error"] == "report_evidence_invalid", (label, response.text)
            assert expected in response.json()["detail"]["message"], (label, response.text)
    # the creation route: another run's record, an unpublished record, a prepared structure
    for handle, expected in ((world["1cll"]["record_handle"], world["1cll"]["record_handle"]),
                             (w["structure"], "wrong_method_result_kind")):
        response = client.post(f"/runs/{w['rid']}/method_reports", json={"result_handle": handle})
        assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"
        assert expected in response.json()["detail"]["message"], response.text
    with run._owner():   # LABELLED fault injection: a record with one count changed, stored without a publication
        record = copy.deepcopy(w["record"])
        record["counts"]["added_atoms"] += 1
        unpublished = run.store.put(K.KIND, K.SCHEMA, record, produced_by="forged_t9_record").handle
    events = len(F.events(root, w["rid"]))
    response = client.post(f"/runs/{w['rid']}/method_reports", json={"result_handle": unpublished})
    assert response.status_code == 422 and response.json()["detail"]["error"] == "report_evidence_invalid"
    assert "structure_repair_record_invalid" in response.json()["detail"]["message"]
    assert len(F.events(root, w["rid"])) == events
    # the claim check alone
    good = _claim_at(w["report"]["manifest"], "terminal_oxt_count", "counts.terminal_oxt")
    assert srr.validate_repair_claim(run, w["record_handle"], copy.deepcopy(good)) == good
    with pytest.raises(EvidenceError, match="structure_repair_claim_binding_mismatch"):
        srr.validate_repair_claim(run, w["record_handle"], {**good, "exact_value": 3, "rendered_value": "3"})
    with pytest.raises(EvidenceError, match="structure_repair_claim_field_rule"):
        srr.validate_repair_claim(run, w["record_handle"], {**good, "field_path": "counts.added_atoms"})
    api_module.RUNS.clear()


def test_an_unavailable_environment_is_412_on_every_report_route(world, client, monkeypatch):
    w = world["1cll"]
    root, rid = world["root"], w["rid"]

    def unavailable():
        raise sr._unavailable()
    monkeypatch.setattr(sr, "_templates", unavailable)   # LABELLED fault injection: the installed template is gone
    before = F.events(root, rid)
    responses = [client.post(f"/runs/{rid}/method_reports", json={"result_handle": w["record_handle"]}),
                 client.get(f"/runs/{rid}/reports/selected", params={"handle": w["report"]["handle"]}),
                 client.get(f"/runs/{rid}/reports/download", params={"handle": w["report"]["handle"]}),
                 client.get(f"/runs/{rid}/reports")]
    for response in responses:
        assert response.status_code == 412, response.text
        body = response.json()
        assert body["error"] == "precondition" and body["detail"]["reason_code"] == "openmm_unavailable", body
    assert F.events(root, rid) == before


# --- wording, names and boundaries ------------------------------------------------------------------------------------

def test_no_interpretive_wording_and_the_fixed_sentences_verbatim(world):
    assert (K.RP1, K.RP2, K.RP3, K.RP4, K.RP5, K.RP6) == (RP1, RP2, RP3, RP4, RP5, RP6)
    assert tuple(srr.STATEMENTS) == K.REPORT_STATEMENT_IDS and srr.INTERPRETIVE is srr.m20.INTERPRETIVE
    assert (srr.ANALYSIS_TYPE, srr.RENDER_VERSION) == ("structure_repair", "structure_repair_markdown@1")
    for name in NAMES:
        manifest, markdown = world[name]["report"]["manifest"], world[name]["report"]["markdown"]
        assert manifest["limitations"] == world[name]["record"]["limitations"]
        text = "\n".join(line for line in markdown.split("\n") if line not in K.LIMITATION_ORDER)
        assert not [word for word in FORBIDDEN if word.lower() in text.lower()], name
        assert srr.check_no_interpretation(markdown) == markdown   # values filled in, too
        assert K.SO1 not in markdown and K.JW1 not in markdown     # not a downstream result's report
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        srr.check_no_interpretation("- 추가 원자 수: 266 (순위 1)")
    assert srr.check_no_interpretation(RP4) == RP4
    # every number of the Markdown outside the collision table and the identifiers is a claim's rendered value
    manifest = world["8vf6"]["report"]["manifest"]
    rendered = {c["rendered_value"] for c in manifest["claims"]}
    for line in world["8vf6"]["report"]["markdown"].split("\n"):
        if line.startswith("- ") and ("수 (" in line or line.startswith("- 추가")):
            assert any(_md(value) in line for value in rendered), line


def test_the_report_module_imports_no_engine_network_process_or_send_module():
    path = MW / "structure_repair_reports.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    absolute = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    absolute |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert absolute <= {"__future__", "hashlib", "math", "re", "uuid", "decimal", "typing"}, absolute
    relative = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 1}
    assert relative == {None, "core.handles", "pocket_reports", "reports"}, relative
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 1 and
                node.module is None for alias in node.names}
    assert imported == {"mutation_reports", "numbering_reports", "structure_repair_bundle",
                        "structure_repair_constants"}, imported
    for banned in ("raise_limits", "limit_approval", "subprocess", "jev_sends", "from .egress", "httpx",
                   "import pdbfixer", "import openmm", "import rdkit", "OPENROUTER", "API_KEY", "jobs."):
        assert banned not in text, banned
    code = ("import sys, mw.structure_repair_reports\n"
            "print(sorted(m for m in ('httpx', 'mw.jev_sends', 'mw.egress', 'openmm', 'pdbfixer', 'rdkit') "
            "if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
