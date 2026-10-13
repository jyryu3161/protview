"""M29 T8a: the downstream report format versions and their "구조 출처" section (spec .dryforge/spec.md 6.1-6.3, 14).

A report of a result made on a repaired structure takes a new format version, and only then: M20
``mutation_candidates_markdown@3``, M21 ``mutation_model_markdown@2``, M24 ``jev_choice_markdown@2`` (mutation kind),
M25 ``jev_loop_markdown@2`` (protein branch) and M18 ``ligand_docking_markdown@2`` (receptor from such a model).

Inputs (labelled; REAL product objects unless marked):
* ``SYNTHETIC-1ubq-gap30-32-lys6.cif``: public 1UBQ without residues A/30-32 (listed in
  ``_pdbx_unobs_or_zero_occ_residues`` by the T4 fixture builder's own helpers, reused at test time) and without atoms
  CE, NZ of A/6 LYS; comment lines in the file say it is SYNTHETIC and not an experimental structure. It is repaired by
  the real worker through the product job (PDBFixer 1.12.0, ``pdbfixer_repair_v1``), then the product path runs on the
  repaired structure: an M20 set at A/44 ILE, one real M21 model of I44W, one real M18 free docking of the labelled
  synthetic phenol SDF into its mutant side (another seed than the loop's), one M24 send of the set and one ended
  protein M25 loop whose iteration 1 is a JEV choice of I44W (it adopts the stored model and runs its own mutant
  docking). JEV replies are fixture values through
  ``jev_send_fixture.Fake`` (MockTransport, inert sentinel credential; nothing leaves the process). The same file's
  unrepaired prepared structure gives one more M20 set and M24 send.
* Public 1UBQ (not repaired): the same M20 / M21 / M18 / M24 / M25 path.
* Public 1MQ4 repaired by the real worker, with the M15 FIXTURE reference set's numbering map and the M16 annotation
  made on its unrepaired prepared structure, handed off to an M20 set on the repaired structure (spec 5.3), and the
  same set request on the unrepaired structure (an M28 ``@2`` report); and an M26 result on the unrepaired structure
  from the LABELLED SYNTHETIC reaction reference set of the T7 tests (made-up PDB ID 0SY9 naming 1MQ4 A274 Asp and
  the gap residue A286 Arg), handed off as the catalytic annotation of another M20 set on the repaired structure.
* The baseline is the report modules of commit ``ea166565`` (``git show``; the five files are unchanged from there to
  the T8a start), loaded under other module names: for inputs that are not repaired the new code gives the same
  manifest and Markdown bytes, reports stored by the baseline reopen with the new code and new reports reopen with the
  baseline code.
Expected counts come from the input files (the edit rule and the installed template through
``test_structure_repair_common``; T5's file ``oracle`` for 1MQ4) and from the repaired mmCIF read with gemmi
(``_atom_site.calc_flag``), never from the record. Edited reports, claims and manifests are fault injection (marked)
in events-only copies; the M23 receptor path is a LABELLED stand-in for the sequence GA publication check (a real M23
run is not made here). A missing engine FAILS, never skips.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import shutil
import subprocess
import sys
import types
from pathlib import Path

import gemmi
import m20_catalytic_fixture as CF
import pytest
import reaction_fixture as RF
import structure_repair_lane_fixture as F
import test_structure_repair_common as C
from fastapi.testclient import TestClient
from jev_send_fixture import Fake, reply, send
from ligand_job_fixture import import_file, run_job
from reference_fixture_set import build_fixture_set
from test_jev_loop_reports import OTHER_SEED, alias_of, project
from test_jev_loops_api import I44, PHENOL, UBQ
from test_jev_loops_compute import (
    PROTEIN_FAST,
    A,
    B,
    Served,
    W,
    end_loop,
    hand_dock_request,
    hand_model_request,
    protein_loop,
)
from test_structure_repair_handoff import _mcsa_entry

from mw import docking_constants as DC
from mw import docking_reports as dr
from mw import jev_constants as J
from mw import jev_loop_reports as jlr
from mw import jev_reports as jr
from mw import jev_sends as S
from mw import mutation_model_bundle as mmb
from mw import mutation_model_constants as MC
from mw import mutation_model_reports as mmr
from mw import mutation_reports as mr
from mw import reaction_knowledge_constants as RKC
from mw import reference_snapshots as rs
from mw import sequence_ga_bundle
from mw import structure_origin_reports as origin_reports
from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import canonical_json
from mw.reports import EvidenceError, _md
from mw.workspace import new_run

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
MW = TESTS.parent / "mw"
BUILDER = TESTS / "fixtures" / "structure_repair" / "build_synthetic_fixtures.py"
BASE = "ea166565"
RID_REP, RID_PLAIN, RID_MQ = "run_m29_t8a_repaired", "run_m29_t8a_plain", "run_m29_t8a_mq4"
SYNTHETIC_NAME = "SYNTHETIC-1ubq-gap30-32-lys6.cif"
LYS6_REMOVED = ("CE", "NZ")
ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
CATALYTIC_POSITIONS = [{"model_number": 1, "chain_auth": "A", "seq_auth": number, "icode": "", "resname": name}
                       for number, name in ((274, "ASP"), (286, "ARG"), (126, "ARG"))]
HANDOFF = ("m20_handoff", "m20_catalytic")
SO1 = "이 결과의 구조는 보완 구조이다. 일부 잔기와 원자는 PDBFixer가 만든 모델링 좌표이며 실험으로 관측한 좌표가 아니다."
SO3 = ("번호 대응·참조 주석·촉매 연결·포켓 결과는 보완 전 원본 구조에서 만든 것이며 잔기 식별자 일치로 이었다. "
       "모델링한 잔기는 검사하지 않았다.")
STATEMENTS = ("repair_added_residue_count", "repair_added_atom_count")
FORBIDDEN = ("안정성", "ΔΔG", "순위", "추천", "최적", "개선", "활성", "예측", "유망", "좋은", "나쁜", "안전", "점수", "에너지",
             "수소결합", "stability", "rank", "recommend", "optimal", "improv", "activ", "predict", "promising", "good",
             "safe", "score", "energy", "hydrogen")
# case -> (world, result key, module, new render version, the earlier version's manifest keys)
CASES = {
    "m20": ("rep", "set", mr, "mutation_candidates_markdown@3", mr.MANIFEST_KEYS_V2),
    "m20_handoff": ("mq", "set_rep", mr, "mutation_candidates_markdown@3", mr.MANIFEST_KEYS_V2),
    "m20_catalytic": ("mq", "set_cat", mr, "mutation_candidates_markdown@3", mr.MANIFEST_KEYS_V2),
    "m21": ("rep", "model", mmr, "mutation_model_markdown@2", mmr.MANIFEST_KEYS),
    "m24": ("rep", "choice", jr, "jev_choice_markdown@2", jr.MANIFEST_KEYS),
    "m25": ("rep", "summary", jlr, "jev_loop_markdown@2", jlr.MANIFEST_KEYS),
    "m18": ("rep", "docking", dr, "ligand_docking_markdown@2", dr.MANIFEST_KEYS),
}
# not repaired -> (world, result key, module, its version)
PLAIN = {
    "m20_gap_structure": ("rep", "plain_set", "mutation_reports", "mutation_candidates_markdown@1"),
    "m24_gap_structure": ("rep", "plain_choice", "jev_reports", "jev_choice_markdown@1"),
    "m20_ubq": ("plain", "set", "mutation_reports", "mutation_candidates_markdown@1"),
    "m20_mq4_v2": ("mq", "set_plain", "mutation_reports", "mutation_candidates_markdown@2"),
    "m21_ubq": ("plain", "model", "mutation_model_reports", "mutation_model_markdown@1"),
    "m24_ubq": ("plain", "choice", "jev_reports", "jev_choice_markdown@1"),
    "m25_ubq": ("plain", "summary", "jev_loop_reports", "jev_loop_markdown@1"),
    "m18_ubq": ("plain", "docking", "docking_reports", "ligand_docking_markdown@1"),
}
BUILD = {"mutation_reports": "build_mutation_report", "mutation_model_reports": "build_mutation_model_report",
         "jev_reports": "build_jev_report", "jev_loop_reports": "build_jev_loop_report",
         "docking_reports": "build_docking_report"}
RENDER = {"mutation_reports": "render_mutation_report", "mutation_model_reports": "render_mutation_model_report",
          "jev_reports": "render_jev_report", "jev_loop_reports": "render_jev_loop_report",
          "docking_reports": "render_docking_report"}
SAVED = {"mutation_reports": "saved_mutation_report", "mutation_model_reports": "saved_mutation_model_report",
         "jev_reports": "saved_jev_report", "jev_loop_reports": "saved_jev_loop_report",
         "docking_reports": "saved_docking_report"}


# --- inputs -----------------------------------------------------------------------------------------------------------

def _builder():
    spec = importlib.util.spec_from_file_location("m29_t4_synthetic_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_ubq() -> bytes:
    """SYNTHETIC: public 1UBQ without A/30-32 (listed as unobserved, the T4 gap rule) and without A/6 LYS CE, NZ."""
    b = _builder()
    st = b._without_gap("SYNTHETIC_M29_T8A_GAP30_32_LYS6", b.GAP)
    lys = b._residue(st, 6)
    for index in sorted((i for i, atom in enumerate(lys) if atom.name in LYS6_REMOVED), reverse=True):
        del lys[index]
    head, rest = b._cif_with_listing(st, list(b.GAP)).decode().split("\n", 1)
    note = ("# SYNTHETIC TEST INPUT (M29 T8a): public 1UBQ without A/30-32 (listed as unobserved) and without A/6 LYS "
            "CE NZ; not an experimental structure")
    return f"{head}\n{note}\n{rest}".encode()


def _expected_ubq_counts() -> dict:
    """From the edit rule, the public file and the installed template (not the product): the three deleted residues
    come back with their template heavy atoms, the two LYS atoms come back, and an OXT only if the file has none."""
    b = _builder()
    names = {res.seqid.num: res.name for res in b._ubq("names")[0]["A"]}
    chain = list(b._ubq("oxt")[0]["A"])     # protein only: the builder removes hydrogens and waters
    oxt = 0 if any(atom.name == "OXT" for atom in chain[-1]) else 1
    atoms = sum(len(C.template_heavy_names(names[number])) for number in b.GAP) + len(LYS6_REMOVED) + oxt
    return {"added_residues": len(b.GAP), "added_atoms": atoms}


def _gemmi_counts(store, repaired: str, original: str) -> dict:
    """From the stored mmCIF bytes with gemmi (not the record): atoms flagged ``calc_flag = c`` and residues of the
    repaired structure whose identity the original prepared structure does not have."""
    def read(handle):
        raw = store.load(store.load(handle)["coordinates"])
        return gemmi.make_structure_from_block(gemmi.cif.read_string(raw.decode()).sole_block())[0]

    def keys(model):
        return {(chain.name, res.seqid.num, res.seqid.icode, res.name) for chain in model for res in chain}
    after, before = read(repaired), read(original)
    flagged = sum(atom.calc_flag == gemmi.CalcFlag.Calculated for chain in after for res in chain for atom in res)
    return {"added_residues": len(keys(after) - keys(before)), "added_atoms": flagged}


def _prepare(run, raw: bytes, name: str) -> str:
    source = run.call("load_structure", {"source": name, "model_index": 0}, source_bytes=raw,
                      source_format="cif").handle
    return run.call("prepare_structure", {"structure": source, "altloc": "highest_occupancy", "waters": "strip_all",
                                          "hydrogens": "strip", "missing_residues": "leave_gaps",
                                          "symmetry_mates": "ignore"}).handle


def _repair(run, prepared: str) -> tuple[str, str]:
    job = run_job(run, K.PROTOCOL, {"structure": prepared, "repair_policy": K.REPAIR_POLICY}, timeout_s=240)
    assert job["status"] == "done", job
    record, structure = job["output_handles"]
    return record, structure


def _i44_set(run, structure: str) -> str:
    return run.call("generate_mutation_candidates", {
        "structure": structure, "sources": {"pocket": None, "ligand_shell": None, "residues": [I44]}}).handle


def _send(run, source: str) -> str:
    projection = run.call(J.TOOL, {"source": source, "candidates": [W, A, B]}).handle
    record = send({"run": run, "projection": projection}, Fake(lambda request: reply("m01", confidence=0.6)))
    assert record["status"] == "completed", record
    return record["choice_handle"]


def _downstream(root: Path, rid: str, raw: bytes, name: str, *, repair: bool) -> dict:
    run = new_run(root, run_id=rid, dry_run=False)
    w = {"rid": rid, "prepared": _prepare(run, raw, name)}
    w["structure"] = w["prepared"]
    if repair:
        w["record"], w["structure"] = _repair(run, w["prepared"])
        w["plain_set"] = _i44_set(run, w["prepared"])
    w["set"] = _i44_set(run, w["structure"])
    w["refs"] = [row["index"] for row in run.store.load(w["set"])["candidates"]]
    w["phenol"] = import_file(run, "ligand_sdf", "phenol.sdf", PHENOL)
    model = run_job(run, MC.PROTOCOL, hand_model_request(w, w["refs"][W]), timeout_s=120)
    assert model["status"] == "done", model
    w["model"] = model["output_handles"][0]
    # another seed than the loop's: the loop still has I44W to compute (as in the M25 report tests)
    outside = {**hand_dock_request(w, w["model"]), "parameters": {**PROTEIN_FAST, "seed": OTHER_SEED}}
    docked = run_job(run, DC.PROTOCOL, outside, timeout_s=300)
    assert docked["status"] == "done", docked
    w["docking"] = docked["output_handles"][0]
    S.set_consent(run, True)
    w["choice"] = _send(run, w["set"])
    if repair:
        w["plain_choice"] = _send(run, w["plain_set"])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(api_module, "RUNS_DIR", root)
        patch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
        api_module.RUNS.clear()
        try:
            served = Served(rid, root)
            loop_id = served.create(protein_loop(w, (W, A, B), cap=2, goal="explore"))
            projection = project(served, loop_id, 1)
            alias = alias_of(served.run, projection, w["refs"][W])
            sent = served.send(Fake(lambda request: reply(alias, confidence=0.5)), projection)
            assert (sent["status"], sent["late"]) == ("completed", False), sent
            assert served.compute(loop_id, iteration=1, proposal=sent["choice_handle"]).status_code == 200
            computed = served.compute(loop_id, iteration=1)    # the mutant docking, in the loop
            assert computed.status_code == 200, computed.text
            record, _content = end_loop(served, loop_id, "ended_by_user")
            w["summary"] = record["result_handle"]
        finally:
            S.ACTIVE_SENDS.clear()
            api_module.RUNS.clear()
    return w


def _mq4(base: Path, root: Path) -> dict:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(rs.ENV_VAR, str(base / "reference"))
        (base / "reference").mkdir()
        build_fixture_set(base / "reference")
        reaction = base / "reaction"
        (reaction / "sets").mkdir(parents=True)
        patch.setenv(RKC.ENV_VAR, str(reaction))
        CF.reset_caches()
        rows = RF.synthetic_rows()
        rows["mcsa"] = [_mcsa_entry(609, "0SY9", [("Asp", 274, True), ("Arg", 286, False)])]
        RF.build_set(reaction, rows=rows)
        run = new_run(root, run_id=RID_MQ, dry_run=False)
        w = {"rid": RID_MQ, "prepared": _prepare(run, F.public("1mq4"), "public_1mq4.cif")}
        w["record"], w["structure"] = _repair(run, w["prepared"])
        w["map"] = run.call("map_residue_numbering", {"structure": w["prepared"], "pdb_id": "1MQ4",
                                                      "chains": [{"chain_auth": "A"}]}).handle
        w["annotation"] = run.call("annotate_reference_sites", {"numbering_map": w["map"]}).handle
        request = {"sources": {"pocket": None, "ligand_shell": {"radius_A": 5.0}, "residues": []}, "ligand": ADP,
                   "numbering_map": w["map"], "annotation": w["annotation"]}
        w["set_rep"] = run.call("generate_mutation_candidates", {"structure": w["structure"], **request}).handle
        w["set_plain"] = run.call("generate_mutation_candidates", {"structure": w["prepared"], **request}).handle
        w["cat"] = run.call("link_reaction_knowledge", {
            "structure": w["prepared"], "pdb_id": "0SY9", "chains": [{"chain_auth": "A", "uniprot_accession": None}],
            "numbering_map": None}).handle
        w["set_cat"] = run.call("generate_mutation_candidates", {
            "structure": w["structure"], "sources": {"pocket": None, "ligand_shell": None,
                                                     "residues": CATALYTIC_POSITIONS},
            "catalytic_annotation": w["cat"]}).handle
        CF.reset_caches()
    return w


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("m29_t8a_reports")
    root = base / "runs"
    S.ACTIVE_SENDS.clear()
    w = {"root": root,
         "rep": _downstream(root, RID_REP, _synthetic_ubq(), SYNTHETIC_NAME, repair=True),
         "plain": _downstream(root, RID_PLAIN, UBQ.read_bytes(), "public_1ubq.cif", repair=False),
         "mq": _mq4(base, root)}
    w["rep"]["expected"] = _expected_ubq_counts()
    oracle = F.oracle("1mq4")
    w["mq"]["expected"] = {"added_residues": oracle["added_residues"], "added_atoms": oracle["added_atoms"]}
    return w


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    monkeypatch.setattr(api_module, "SCIENCE_GATE", Fake().gate)
    api_module.RUNS.clear()
    yield TestClient(api_module.app, base_url="http://127.0.0.1")
    api_module.RUNS.clear()


def _report(client, rid: str, handle: str) -> dict:
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
    assert response.status_code == 201, response.text
    return response.json()


def _selected(client, rid: str, handle: str):
    return client.get(f"/runs/{rid}/reports/selected", params={"handle": handle})


def _refused(response) -> str:
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["error"] == "report_evidence_invalid", response.text
    return response.json()["detail"]["message"]


def _section(markdown: str) -> list[str]:
    """The lines of the one "## 구조 출처" section, which must be the last section before "## Limitations"."""
    assert markdown.count("\n## 구조 출처\n") == 1 and markdown.count("\n## Limitations\n") == 1
    start, end = markdown.index("\n## 구조 출처\n"), markdown.index("\n## Limitations\n")
    assert start < end and "\n## " not in markdown[start + 1:end]
    return markdown[start + 1:end].split("\n")


def _copy(world, rid: str, tmp_path: Path) -> Path:
    """An events-only copy of one run of the world (forgeries go there, the shared run stays untouched)."""
    root = tmp_path / "copy"
    (root / rid).mkdir(parents=True)
    shutil.copyfile(world["root"] / rid / "events.jsonl", root / rid / "events.jsonl")
    return root


def _forge(run, manifest: dict, markdown: str, analysis_type: str) -> str:
    """Fault injection: store an edited report and its creation event the way the builders do."""
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode("utf-8"), fmt="md",
                           produced_by="forged_t8a_report", summary={"result_handle": manifest["result_handle"]})
        forged = {**manifest, "markdown_handle": md.handle}
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_t8a_report",
                               summary={"result_handle": forged["result_handle"], "analysis_type": analysis_type,
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


# --- the new versions on a repaired structure -------------------------------------------------------------------------

@pytest.mark.parametrize("case", sorted(CASES))
def test_a_repaired_structure_report_takes_the_new_version_with_the_structure_origin_section(case, world, client):
    key, result, module, version, earlier_keys = CASES[case]
    w = world[key]
    built = _report(client, w["rid"], w[result])
    manifest, markdown = built["manifest"], built["markdown"]
    assert manifest["render_version"] == version and set(manifest) == earlier_keys | {"structure_origin"}
    # reopen, list and download give the stored bytes
    again = _selected(client, w["rid"], built["handle"])
    assert again.status_code == 200, again.text
    assert again.json()["markdown"] == markdown and canonical_json(again.json()["manifest"]) == canonical_json(manifest)
    download = client.get(f"/runs/{w['rid']}/reports/download", params={"handle": built["handle"]})
    assert download.status_code == 200 and download.content == markdown.encode("utf-8")
    listed = client.get(f"/runs/{w['rid']}/reports")
    assert listed.status_code == 200 and built["handle"] in {row["handle"] for row in listed.json()}
    # the manifest field: the three handles of this repaired structure and the fixed sentences verbatim
    handoff = case in HANDOFF
    origin = manifest["structure_origin"]
    assert origin == {"repair_record": w["record"], "repaired_structure": w["structure"],
                      "source_structure": w["prepared"],
                      "statements": [{"id": "SO1", "text": SO1}, *([{"id": "SO3", "text": SO3}] if handoff else [])]}
    assert (K.SO1, K.SO3) == (SO1, SO3)
    # the two claims cite the record's counts and equal the counts from the input file and from the mmCIF bytes
    run = api_module._run(w["rid"])
    independent = _gemmi_counts(run.store, w["structure"], w["prepared"])
    assert independent == w["expected"], (independent, w["expected"])
    claims = manifest["claims"][-2:]
    assert [claim["statement_id"] for claim in claims] == list(STATEMENTS)
    assert sum(claim["statement_id"] in STATEMENTS for claim in manifest["claims"]) == 2
    for claim, field in zip(claims, ("added_residues", "added_atoms"), strict=True):
        assert (claim["evidence_kind"], claim["source_handle"], claim["source_kind"], claim["source_schema"],
                claim["source_sha256"], claim["field_path"], claim["row_selector"], claim["unit"],
                claim["rounding"]) == ("computed", w["record"], "structure_repair", "structure_repair@1",
                                       w["record"].rsplit("/", 1)[-1], f"counts.{field}", None, "count", "integer")
        assert claim["exact_value"] == w["expected"][field] == run.store.load(w["record"])["counts"][field]
        assert claim["rendered_value"] == str(w["expected"][field])
        assert claim.get("reference") is None and ("reference" in claim) is (module is not dr)
    # the section: last before the limitations, SO1 (and SO3 for the hand-off) verbatim, the handle, the two counts
    lines = _section(markdown)
    assert lines[:4] == ["## 구조 출처", "", SO1, ""]
    assert (SO3 in lines) is handoff
    assert f"- 보완 기록: {_md(w['record'])} ({_md('structure_repair@1')})" in lines
    assert f"- 보완 구조: {_md(w['structure'])}" in lines and f"- 보완 전 원본 구조: {_md(w['prepared'])}" in lines
    assert (f"- 추가 잔기 수 (보완 기록 {_md('counts.added_residues')}): {w['expected']['added_residues']}" in lines)
    assert (f"- 추가 원자 수 (보완 기록 {_md('counts.added_atoms')}): {w['expected']['added_atoms']}" in lines)
    text = "\n".join(line for line in lines if line not in (SO1, SO3))
    assert not [word for word in FORBIDDEN if word.lower() in text.lower()]
    module.check_no_interpretation("\n".join(lines))   # the section, values filled (handles and counts only)
    if module is mr:   # @3 keeps the @2 source table only when it cites reference values
        assert (manifest["reference_snapshot_sets"] != []) is handoff
        assert ("\n## 참조 스냅샷\n" in markdown) is handoff
        if handoff:
            assert markdown.index("\n## 참조 스냅샷\n") < markdown.index("\n## 구조 출처\n")


def test_the_repaired_m20_set_takes_reference_results_of_the_original_structure_only_in_v3(world):
    """Spec 6.3: ``check_sources`` accepts the original structure's map and annotation only with the validated origin
    of the set's repaired structure; without it (the @1 / @2 rule) the same objects are another structure's."""
    w = world["mq"]
    run = new_run(world["root"], run_id=RID_MQ, dry_run=False)
    content = run.store.load(w["set_rep"])
    nmap, annotation = run.store.load(w["map"]), run.store.load(w["annotation"])
    assert nmap["structure"]["handle"] == annotation["structure"]["handle"] == w["prepared"] != w["structure"]
    with pytest.raises(EvidenceError, match="mutation_numbering_map_structure_mismatch"):
        mr.check_sources(content, nmap, annotation, None)
    found = origin_reports.origin(run, w["structure"])
    assert found["source_structure"] == w["prepared"] and found["repair_record"] == w["record"]
    mr.check_sources(content, nmap, annotation, None, None, found)
    assert origin_reports.origin(run, w["prepared"]) is None
    other = {**found, "source_structure": w["structure"]}   # fault injection: an origin naming another source
    with pytest.raises(EvidenceError, match="mutation_numbering_map_structure_mismatch"):
        mr.check_sources(content, nmap, annotation, None, None, other)
    # the catalytic hand-off: the M26 result of the original structure, accepted with the origin only
    with_catalytic, result = run.store.load(w["set_cat"]), run.store.load(w["cat"])
    assert result["structure"]["handle"] == w["prepared"]
    assert with_catalytic["protection_checks"]["catalytic_residue_database"]["covered_chains"] == ["A"]
    with pytest.raises(EvidenceError, match="mutation_catalytic_annotation_structure_mismatch"):
        mr.check_sources(with_catalytic, None, None, None, result)
    mr.check_sources(with_catalytic, None, None, None, result, found)


# --- refusals ---------------------------------------------------------------------------------------------------------

def _edits(world, w: dict, manifest: dict, module) -> list[tuple[str, dict]]:
    """(label, edited manifest) -- fault injection on a stored report of the new version."""
    other_record = world["mq" if w is world["rep"] else "rep"]["record"]   # another run's record

    def claim_edit(index: int, **changes):
        def edit(m):
            m["claims"][index - 2].update(changes)
        return edit

    def apply(change) -> dict:
        edited = copy.deepcopy(manifest)
        change(edited)
        return edited

    earlier = {mr: "mutation_candidates_markdown@2", mmr: "mutation_model_markdown@1", jr: "jev_choice_markdown@1",
               jlr: "jev_loop_markdown@1", dr: "ligand_docking_markdown@1"}[module]
    value = manifest["claims"][-1]["exact_value"]
    out = [
        ("wrong value", apply(claim_edit(1, exact_value=value + 1, rendered_value=str(value + 1)))),
        ("other run's record", apply(claim_edit(1, source_handle=other_record,
                                                source_sha256=other_record.rsplit("/", 1)[-1]))),
        ("result handle as the source", apply(claim_edit(0, source_handle=manifest["result_handle"],
                                                         source_sha256=manifest["result_sha256"]))),
        ("result kind as the source", apply(claim_edit(0, source_kind="mutation_candidate_set",
                                                       source_schema="mutation_candidate_set@1"))),
        ("another field", apply(claim_edit(0, field_path="counts.gaps"))),
        ("swapped fields", apply(claim_edit(1, field_path="counts.added_residues"))),
        ("not computed", apply(claim_edit(0, evidence_kind="reference_value"))),
        ("claim dropped", apply(lambda m: m["claims"].pop())),
        ("field dropped", apply(lambda m: m.pop("structure_origin"))),
        ("record swapped", apply(lambda m: m["structure_origin"].update(repair_record=other_record))),
        ("SO1 dropped", apply(lambda m: m["structure_origin"].update(statements=[]))),
        ("earlier version", apply(lambda m: m.update(render_version=earlier))),
        ("earlier version and keys", apply(lambda m: (m.update(render_version=earlier),
                                                      m.pop("structure_origin")))),
    ]
    return out


@pytest.mark.parametrize("case", sorted(CASES))
def test_edited_new_version_reports_are_refused(case, world, client, tmp_path, monkeypatch):
    key, result, module, _version, _keys = CASES[case]
    w = world[key]
    built = _report(client, w["rid"], w[result])
    manifest, markdown = built["manifest"], built["markdown"]
    root = _copy(world, w["rid"], tmp_path)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    run = api_module._run(w["rid"])
    analysis = manifest["analysis_type"]
    forged = [(label, _forge(run, edited, markdown, analysis)) for label, edited in _edits(world, w, manifest, module)]
    start, end = markdown.index("\n## 구조 출처\n"), markdown.index("\n## Limitations\n")
    block, rest = markdown[start:end], markdown[:start] + markdown[end:]
    for label, edited in (("section moved after the limitations", rest + block), ("section dropped", rest),
                          ("SO1 line edited", markdown.replace(SO1, SO1[:-1], 1)),
                          ("count line edited", markdown.replace(f"): {w['expected']['added_atoms']}\n",
                                                                 f"): {w['expected']['added_atoms'] + 1}\n", 1))):
        assert edited != markdown, label
        forged.append((label, _forge(run, manifest, edited, analysis)))
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    for label, handle in forged:
        response = _selected(client, w["rid"], handle)
        assert response.status_code == 422, (label, response.text)
        assert response.json()["detail"]["error"] == "report_evidence_invalid", (label, response.text)
    assert _selected(client, w["rid"], built["handle"]).status_code == 200


@pytest.mark.parametrize("case", sorted(CASES))
def test_mixed_and_other_run_claims_are_refused_by_the_claim_check(case, world, client):
    key, result, module, _version, _keys = CASES[case]
    w = world[key]
    manifest = _report(client, w["rid"], w[result])["manifest"]
    expected = manifest["claims"]
    other_record = world["mq" if key == "rep" else "rep"]["record"]
    for claim in expected[-2:]:
        assert module.match_claim(expected, copy.deepcopy(claim)) == claim
    residue, atom = (copy.deepcopy(claim) for claim in expected[-2:])
    edits = {
        "evidence_kind_mismatch": {**residue, "evidence_kind": "reference_value"},
        "field_rule": {**atom, "field_path": "counts.added_residues"},
        "source_kind_mismatch": {**residue, "source_kind": manifest["result_schema"].split("@")[0],
                                 "source_schema": manifest["result_schema"]},
        "source_mismatch": {**atom, "source_handle": other_record, "source_sha256": other_record.rsplit("/", 1)[-1]},
        "binding_mismatch": {**atom, "exact_value": atom["exact_value"] + 1},
    }
    for reason, proposed in edits.items():
        with pytest.raises(EvidenceError, match=reason):
            module.match_claim(expected, proposed)
    # an origin claim offered for a report without one (another result's claims) is not allowed
    base_claims = [claim for claim in expected if claim["statement_id"] not in STATEMENTS]
    with pytest.raises(EvidenceError, match="field_not_allowed"):
        module.match_claim(base_claims, residue)


@pytest.mark.parametrize("case", sorted(PLAIN))
def test_a_forged_new_version_for_a_structure_that_is_not_repaired_is_refused(case, world, client, tmp_path,
                                                                               monkeypatch):
    key, result, name, version = PLAIN[case]
    w = world[key]
    module = {"mutation_reports": mr, "mutation_model_reports": mmr, "jev_reports": jr, "jev_loop_reports": jlr,
              "docking_reports": dr}[name]
    built = _report(client, w["rid"], w[result])
    assert built["manifest"]["render_version"] == version and "structure_origin" not in built["manifest"]
    assert "## 구조 출처" not in built["markdown"]
    donor_case = {"mutation_reports": "m20", "mutation_model_reports": "m21", "jev_reports": "m24",
                  "jev_loop_reports": "m25", "docking_reports": "m18"}[name]
    donor_key, donor_result, _module, new_version, _keys = CASES[donor_case]
    donor = _report(client, world[donor_key]["rid"], world[donor_key][donor_result])["manifest"]
    forged = copy.deepcopy(built["manifest"])
    forged.update(render_version=new_version, structure_origin=donor["structure_origin"])
    forged["claims"] = forged["claims"] + donor["claims"][-2:]
    if module is mr:
        forged.setdefault("reference_snapshot_sets", [])
    root = _copy(world, w["rid"], tmp_path)
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    run = api_module._run(w["rid"])
    markdown = getattr(module, RENDER[name])(forged)
    assert "\n## 구조 출처\n" in markdown
    handle = _forge(run, forged, markdown, built["manifest"]["analysis_type"])
    message = _refused(TestClient(api_module.app, base_url="http://127.0.0.1").get(
        f"/runs/{w['rid']}/reports/selected", params={"handle": handle}))
    assert "structure_origin_mismatch" in message, message


# --- reports of structures that are not repaired: the baseline bytes --------------------------------------------------

_BASELINE: dict[str, types.ModuleType] = {}


def _baseline(name: str) -> types.ModuleType:
    """The report module as of commit ``ea166565`` (``git show``), loaded as ``mw._t8a_baseline_<name>``: its relative
    imports resolve to today's ``mw`` modules. A missing commit or git FAILS (never skips)."""
    if name not in _BASELINE:
        source = subprocess.run(["git", "show", f"{BASE}:backend/mw/{name}.py"], cwd=REPO, capture_output=True,
                                text=True, check=True).stdout
        module = types.ModuleType(f"mw._t8a_baseline_{name}")
        module.__package__ = "mw"
        module.__file__ = f"<{BASE}:backend/mw/{name}.py>"
        sys.modules[module.__name__] = module
        exec(compile(source, module.__file__, "exec"), module.__dict__)   # noqa: S102 (the repository's own file)
        _BASELINE[name] = module
    return _BASELINE[name]


def test_the_baseline_files_are_the_t8a_start_files():
    for name in BUILD:
        start = subprocess.run(["git", "show", f"b87a3e61:backend/mw/{name}.py"], cwd=REPO, capture_output=True,
                               check=True).stdout
        base = subprocess.run(["git", "show", f"{BASE}:backend/mw/{name}.py"], cwd=REPO, capture_output=True,
                              check=True).stdout
        assert start == base, name


@pytest.mark.parametrize("case", sorted(PLAIN))
def test_a_structure_that_is_not_repaired_keeps_the_baseline_report_bytes(case, world, client):
    key, result, name, version = PLAIN[case]
    w = world[key]
    module = sys.modules[f"mw.{name}"]
    old = _baseline(name)
    run = api_module._run(w["rid"])
    expected_new, expected_old = module._expected(run, w[result]), old._expected(run, w[result])
    assert canonical_json(expected_new) == canonical_json(expected_old)
    assert expected_new["render_version"] == version and "structure_origin" not in expected_new
    # a report the baseline code stores reopens with the new code byte for byte
    stored = getattr(old, BUILD[name])(run, w[result])
    reopened = _selected(client, w["rid"], stored["handle"])
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["markdown"] == stored["markdown"]
    assert canonical_json(reopened.json()["manifest"]) == canonical_json(stored["manifest"])
    assert run.store.load_bounded_bytes(stored["markdown_handle"], 1 << 24).decode() == stored["markdown"]
    # a report the new code stores is the baseline's: same manifest fields and Markdown, and the baseline reopens it
    built = _report(client, w["rid"], w[result])
    assert built["markdown"] == stored["markdown"]
    snapshot_free = {"snapshot", "markdown_handle"}
    assert canonical_json({k: v for k, v in built["manifest"].items() if k not in snapshot_free}) == \
        canonical_json({k: v for k, v in stored["manifest"].items() if k not in snapshot_free})
    api_module.RUNS.clear()
    again = api_module._run(w["rid"])
    assert getattr(old, SAVED[name])(again, built["handle"])["markdown"] == built["markdown"]


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_baseline_code_cannot_read_a_new_version(case, world, client):
    """The new versions are new formats: the ``ea166565`` code refuses them (and new code reads both)."""
    key, result, module, _version, _keys = CASES[case]
    w = world[key]
    built = _report(client, w["rid"], w[result])
    old = _baseline(module.__name__.split(".")[-1])
    with pytest.raises(EvidenceError, match="schema_invalid"):
        getattr(old, SAVED[module.__name__.split(".")[-1]])(api_module._run(w["rid"]), built["handle"])


# --- environment, wording, the M18 model chain, module boundary -----------------------------------------------------

def _no_template():
    raise sr._unavailable()   # LABELLED hook: the installed Amber14 template made unavailable


@pytest.mark.parametrize("case", ["m20", "m21", "m18"])
def test_an_unavailable_template_is_a_precondition_never_invalid_evidence(case, world, client, monkeypatch):
    key, result, module, _version, _keys = CASES[case]
    w = world[key]
    built = _report(client, w["rid"], w[result])
    monkeypatch.setattr(sr, "_templates", _no_template)
    response = client.post(f"/runs/{w['rid']}/method_reports", json={"result_handle": w[result]})
    assert response.status_code == 412, response.text
    assert response.json()["detail"]["reason_code"] == "openmm_unavailable", response.text
    with pytest.raises(ToolFailure) as caught:
        getattr(module, SAVED[module.__name__.split(".")[-1]])(api_module._run(w["rid"]), built["handle"])
    assert caught.value.cls is FailureClass.precondition
    # a structure that is not repaired needs no template
    plain = world["plain"]
    assert client.post(f"/runs/{plain['rid']}/method_reports",
                       json={"result_handle": plain[result]}).status_code == 201


@pytest.mark.parametrize("case", sorted(CASES))
def test_interpretive_wording_in_the_section_template_refuses_the_report(case, world, client, monkeypatch):
    key, result, module, _version, _keys = CASES[case]
    w = world[key]
    built = _report(client, w["rid"], w[result])
    assert module.check_no_interpretation(SO1) == SO1
    with pytest.raises(EvidenceError, match="interpretive_statement"):
        module.check_no_interpretation(SO1 + " 순위")
    monkeypatch.setattr(origin_reports, "SECTION", "## 구조 출처 (순위)")
    response = client.post(f"/runs/{w['rid']}/method_reports", json={"result_handle": w[result]})
    assert "interpretive_statement" in _refused(response)
    assert "interpretive_statement" in _refused(_selected(client, w["rid"], built["handle"]))


def test_the_m18_report_follows_an_m23_set_model_to_its_candidate_set_structure(world, tmp_path, monkeypatch):
    """LABELLED stand-in: a SYNTHETIC ``mutation_set_model@1`` object (stored in an events-only copy) and
    ``sequence_ga_jobs.set_model`` replaced by a loader of that object (the GA publication check itself is tested by
    the M23 tests; no M23 run is made here). The chain model -> candidate set -> structure is then the report's."""
    w = world["rep"]
    root = _copy(world, w["rid"], tmp_path)
    run = new_run(root, run_id=w["rid"], dry_run=False)
    with run._owner():
        synthetic = {"label": "SYNTHETIC M29 T8a stand-in, not a sequence GA model", "candidate_set": w["set"],
                     "structure": {"handle": w["structure"], "model_number": 1}}
        model = run.store.put("mutation_set_model", "mutation_set_model@1", synthetic, produced_by="test").handle
        stale = run.store.put("mutation_set_model", "mutation_set_model@1",
                              {**synthetic, "candidate_set": w["plain_set"]}, produced_by="test").handle
    import mw.sequence_ga_jobs as gajobs

    monkeypatch.setattr(gajobs, "set_model", lambda run_, handle: (run_.store.load(handle), None))
    found = dr._receptor_origin(run, {"source": {"kind": "mutation_model", "mutation_model": model, "side": "mutant"}})
    assert (found["repair_record"], found["repaired_structure"]) == (w["record"], w["structure"])
    with pytest.raises(EvidenceError, match="receptor_structure_mismatch"):
        dr._receptor_origin(run, {"source": {"kind": "mutation_model", "mutation_model": stale, "side": "mutant"}})

    def refused(run_, handle):
        raise sequence_ga_bundle.SequenceGaEvidenceError("LABELLED: no publication")
    monkeypatch.setattr(gajobs, "set_model", refused)
    with pytest.raises(EvidenceError, match="receptor_model_invalid"):
        dr._receptor_origin(run, {"source": {"kind": "mutation_model", "mutation_model": model, "side": "mutant"}})
    # the M21 chain: a model whose stored validation fails is invalid evidence, an imported receptor reads nothing
    monkeypatch.setattr(mmb, "validated_result", refused)
    with pytest.raises(EvidenceError, match="receptor_model_invalid"):
        dr._receptor_origin(run, {"source": {"kind": "mutation_model", "mutation_model": w["model"],
                                             "side": "mutant"}})
    assert dr._receptor_origin(run, {"handle": "obj://x/receptor/0"}) is None
    plain = world["plain"]
    assert dr._receptor_origin(new_run(world["root"], run_id=plain["rid"], dry_run=False), {
        "source": {"kind": "mutation_model", "mutation_model": plain["model"], "side": "mutant"}}) is None


def test_the_section_module_imports_no_engine_network_process_or_send_module():
    path = MW / "structure_origin_reports.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    absolute = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    absolute |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert absolute <= {"__future__", "typing"}, absolute
    relative = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 1}
    assert relative == {None, "core.errors", "core.handles", "reports", "structure_origin"}, relative
    for banned in ("raise_limits", "limit_approval", "subprocess", "jev_sends", "egress", "httpx", "import pdbfixer",
                   "import openmm", "import rdkit", "OPENROUTER", "API_KEY"):
        assert banned not in text, banned
    code = ("import sys, mw.structure_origin_reports\n"
            "print(sorted(m for m in ('httpx', 'mw.jev_sends', 'mw.egress', 'openmm', 'pdbfixer', 'rdkit') "
            "if m in sys.modules))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr


def test_the_fixed_sentences_and_names_come_from_the_constants():
    assert origin_reports.STATEMENT_IDS == K.ORIGIN_STATEMENT_IDS == STATEMENTS
    assert origin_reports.FIXED_LINES == {K.SO1, K.SO3}
    assert (mr.RENDER_VERSION_V3, mmr.RENDER_VERSION_V2, jr.RENDER_VERSION_V2, jlr.RENDER_VERSION_V2,
            dr.RENDER_VERSION_V2) == ("mutation_candidates_markdown@3", "mutation_model_markdown@2",
                                      "jev_choice_markdown@2", "jev_loop_markdown@2", "ligand_docking_markdown@2")
    assert (mr.RENDER_VERSION, mr.RENDER_VERSION_V2, mmr.RENDER_VERSION, jr.RENDER_VERSION, jlr.RENDER_VERSION,
            dr.RENDER_VERSION) == ("mutation_candidates_markdown@1", "mutation_candidates_markdown@2",
                                   "mutation_model_markdown@1", "jev_choice_markdown@1", "jev_loop_markdown@1",
                                   "ligand_docking_markdown@1")
    # the earlier manifest key sets are unchanged; each new one adds structure_origin only
    assert mr.MANIFEST_KEYS_BY_VERSION[mr.RENDER_VERSION_V3] == mr.MANIFEST_KEYS_V2 | {"structure_origin"}
    for module, new in ((mmr, mmr.RENDER_VERSION_V2), (jr, jr.RENDER_VERSION_V2), (jlr, jlr.RENDER_VERSION_V2),
                        (dr, dr.RENDER_VERSION_V2)):
        assert module.MANIFEST_KEYS_BY_VERSION == {module.RENDER_VERSION: module.MANIFEST_KEYS,
                                                   new: module.MANIFEST_KEYS | {"structure_origin"}}
