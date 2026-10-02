"""M18 T7: the ligand docking report (``method_report_manifest@1``, ``analysis_type: "ligand_docking"``,
``ligand_docking_markdown@1``; spec 9).

Every docking result here is real product output: chemical imports -> POST /jobs -> approve -> start with the pinned
docking worker (``.deps/docking/venv-locked`` + ``.deps/qvina/env``; a missing environment FAILS, never skips). The
receptor is the public ProLIF example (a public prepared docking example, not experimental validation), the ligand the
labeled public-derived parent record and its real M17 candidate; small manual boxes and exhaustiveness 1 keep it short.
The only non-engine result is the zero-mode result: a genuine worker output whose mode rows were removed after the run
(LABELED TEST FABRICATION through the internal ``JobQueue._supervise`` hook, never a request field), because qvina does
not produce an empty result on demand. No report value is copied from the product: stored fields are re-resolved by
path, contact counts are recounted here with the test's own comparisons, and numbers are rendered with an independent
``Decimal`` oracle. Forged report manifests and edited objects are labeled test fabrications written only to prove the
validator rejects them.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mw import docking_bundle
from mw import docking_constants as C
from mw import docking_reports as dr
from mw.api import app as api_module
from mw.core.handles import canonical_json
from mw.jobs.queue import JobQueue
from mw.reports import EvidenceError

CHEM = Path(__file__).parent / "fixtures/chemical"
FIX = Path(__file__).parent / "fixtures/docking"
EXPECTED = json.loads((FIX / "expected.json").read_text())
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
COMPLEX = (FIX / "synthetic-complex-receptor-lig.pdb").read_bytes()
BLOCKS = (FIX / "synthetic-docking-blocks.smi").read_bytes()
CANDIDATE_ID = EXPECTED["m17_candidate"]["fixed_candidate_id"]
INSTANCE = EXPECTED["receptor_fixtures"]["instance"]
CENTER = EXPECTED["public_example_box"]["center_A"]
SMALL_BOX = {"source": "manual", "center_A": CENTER, "size_A": [12.0, 12.0, 12.0]}
ACK = {key: True for key in C.ACKNOWLEDGEMENT_KEYS}
PATH_PART = re.compile(r"([A-Za-z_0-9]+)(?:\[(\d+)\])?")
RESIDUE_FIELDS = ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")
POLAR = {"N", "O"}


def _round(value, places: str) -> str:
    rounded = Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return f"{abs(rounded) if rounded == 0 else rounded:.{len(places.split('.')[1])}f}"


def _score(value) -> str:
    return _round(value, "0.1")


def _distance(value) -> str:
    return _round(value, "0.01")


# ----------------------------------------------------------------- shared world (real jobs, built once)
def _import(client: TestClient, rid: str, kind: str, filename: str, raw: bytes) -> str:
    response = client.post(f"/runs/{rid}/chemical/imports", params={"kind": kind, "filename": filename},
                           content=raw, headers={"content-type": "application/octet-stream"})
    assert response.status_code == 201, response.text
    return response.json()["handle"]


def _run_job(client: TestClient, rid: str, protocol: str, args: dict, timeout_s: float = 600) -> dict:
    submitted = client.post(f"/runs/{rid}/jobs", json={"protocol_id": protocol, "args": args,
                                                       "timeout_s": timeout_s})
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job_id"]
    started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    if started.status_code == 409:
        assert client.post(f"/runs/{rid}/jobs/approve").status_code == 200
        started = client.post(f"/runs/{rid}/jobs/{job_id}/start")
    assert started.status_code == 200, started.text
    done = started.json()
    assert done["status"] == "done", done
    return done


def _args(receptor: str, ligand: dict, *, mode: str = "free", box: dict | None = None, seed: int = 1,
          instance: dict | None = None, params: dict | None = None) -> dict:
    return {"receptor_handle": receptor, "receptor_model_number": 1,
            "connectivity": {"kind": "pdb_conect", "sidecar_handle": None}, "receptor_instance": instance,
            "ligand": ligand, "mode": mode, "box": box or SMALL_BOX,
            "parameters": params or {"seed": seed, "exhaustiveness": 1, "num_modes": 3}, "acknowledgement": ACK}


def _empty_modes(original):
    """LABELED TEST FABRICATION: a genuine worker output with its mode rows removed, descriptor re-signed."""
    def supervise(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch):
        result, identity = original(self, job, attempt_id, nonce, attempt_dir, deadline, dispatch)
        data = json.loads((attempt_dir / "result.json").read_bytes())
        data["modes"] = []
        data["counts"].update(modes=0, contacts_by_mode=[], null_result=True)
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        (attempt_dir / "result.json").write_bytes(raw)
        result["payload"] = {"output_sha256": hashlib.sha256(raw).hexdigest(), "output_bytes": len(raw)}
        return result, identity
    return supervise


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("docking_reports") / "runs"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(api_module, "RUNS_DIR", root)
        api_module.RUNS.clear()
        client = TestClient(api_module.app, base_url="http://127.0.0.1")
        rid = client.post("/runs", json={"goal": "M18 docking reports", "dry_run": False}).json()["run_id"]
        receptor = _import(client, rid, "receptor", "rec.pdb", REC)
        parent = _import(client, rid, "ligand_sdf", "parent.sdf", PARENT)
        complex_receptor = _import(client, rid, "receptor", "complex.pdb", COMPLEX)
        blocks = _import(client, rid, "building_blocks_smiles", "blocks.smi", BLOCKS)
        inspected = _run_job(client, rid, "rdkit_inspect_v1", {"parent_sdf_handle": parent,
                                                               "block_handles": [blocks]}, 120)
        enumerated = _run_job(client, rid, "rdkit_enumerate_v1",
                              {"inspection_handle": inspected["output_handles"][0], "site_atoms": [22],
                               "use_fixed": True}, 120)
        candidate_set = enumerated["output_handles"][0]
        candidate = {"source": "candidate", "candidate_set_handle": candidate_set, "candidate_id": CANDIDATE_ID,
                     "parent_sdf_handle": parent}
        sdf = {"source": "sdf", "sdf_handle": parent}
        free = _run_job(client, rid, "qvina_dock_v1", _args(receptor, sdf))
        core = _run_job(client, rid, "qvina_dock_v1", _args(
            receptor, candidate, mode="core_fixed", box={"source": "ligand_range", "margin_A": 8.0},
            params={"seed": 7, "exhaustiveness": 1, "num_modes": 2, "conformers": 2}))
        cand_free = _run_job(client, rid, "qvina_dock_v1", _args(receptor, candidate, seed=3,
                                                                 params={"seed": 3, "exhaustiveness": 1,
                                                                         "num_modes": 2}))
        instance = _run_job(client, rid, "qvina_dock_v1", _args(complex_receptor, sdf, seed=4, instance=INSTANCE,
                                                                params={"seed": 4, "exhaustiveness": 1,
                                                                        "num_modes": 2}))
        with pytest.MonkeyPatch.context() as fault:
            fault.setattr(JobQueue, "_supervise", _empty_modes(JobQueue._supervise))
            empty = _run_job(client, rid, "qvina_dock_v1", _args(receptor, sdf, seed=5))
        handles = {name: job["artifacts"]["docking_result"] for name, job in (
            ("free", free), ("core", core), ("cand_free", cand_free), ("instance", instance), ("empty", empty))}
        jobs = {name: job["job_id"] for name, job in (
            ("free", free), ("core", core), ("cand_free", cand_free), ("instance", instance), ("empty", empty))}
        run = api_module._run(rid)
        stored = {name: run.store.load(handle) for name, handle in handles.items()}
    assert stored["free"]["modes"] and any(row["contacts"] for row in stored["free"]["modes"])
    assert stored["core"]["inputs"]["mode"] == "core_fixed" and stored["core"]["modes"]
    assert stored["instance"]["inputs"]["receptor"]["removed_instance"]["residue"] == INSTANCE
    assert stored["empty"]["modes"] == [] and stored["empty"]["counts"]["null_result"] is True
    return {"root": root, "rid": rid, "receptor": receptor, "parent": parent, "candidate_set": candidate_set,
            "complex": complex_receptor, "handles": handles, "jobs": jobs, "stored": stored}


@pytest.fixture
def client(world, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", world["root"])
    api_module.RUNS.clear()
    return TestClient(api_module.app, base_url="http://127.0.0.1")


@pytest.fixture
def private_client(world, monkeypatch, tmp_path):
    """A function-scoped copy of the shared run, for tests that store forged reports (they make the list fail)."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / world["rid"], root / world["rid"])
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    yield TestClient(api_module.app, base_url="http://127.0.0.1")
    api_module.RUNS.clear()


def _run(world):
    return api_module._run(world["rid"])


def _report(client, world, name: str) -> dict:
    created = client.post(f"/runs/{world['rid']}/method_reports", json={"result_handle": world["handles"][name]})
    assert created.status_code == 201, created.text
    return created.json()


def _selected(client, world, handle):
    return client.get(f"/runs/{world['rid']}/reports/selected", params={"handle": handle})


def _resolve(document, path):
    value = document
    for part in path.split("."):
        match = PATH_PART.fullmatch(part)
        assert match, path
        value = value[match.group(1)]
        if match.group(2) is not None:
            value = value[int(match.group(2))]
    return value


def _claim(manifest, statement, path=None, **selector):
    found = [claim for claim in manifest["claims"] if claim["statement_id"] == statement and
             (path is None or claim["field_path"] == path) and
             all((claim["row_selector"] or {}).get(k) == v for k, v in selector.items())]
    assert len(found) == 1, (statement, path, selector, len(found))
    return found[0]


def _statements(manifest) -> set[str]:
    return {claim["statement_id"] for claim in manifest["claims"]}


def _kind(a: str, b: str) -> str:
    a, b = a.upper(), b.upper()
    if a in POLAR and b in POLAR:
        return "polar_contact"
    return "hydrophobic_contact" if a == "C" and b == "C" else "contact"


def _verify_independently(world, name: str, manifest) -> None:
    """Re-resolve every claim from the stored result; recount contacts; check every rendering."""
    handle = world["handles"][name]
    stored = world["stored"][name]
    assert manifest["result_handle"] == handle and manifest["result_sha256"] == handle.rsplit("/", 1)[-1]
    seen = set()
    for claim in manifest["claims"]:
        key = (claim["statement_id"], claim["field_path"], json.dumps(claim["row_selector"], sort_keys=True))
        assert key not in seen
        seen.add(key)
        assert claim["evidence_kind"] == "computed"
        assert claim["source_handle"] == handle and claim["source_sha256"] == handle.rsplit("/", 1)[-1]
        assert claim["source_kind"] == "docking_result" and claim["source_schema"] == "docking_result@1"
        statement, value, path = claim["statement_id"], claim["exact_value"], claim["field_path"]
        if statement in ("score_minimum", "score_maximum"):
            scores = [row["score_kcal_mol"] for row in stored["modes"]]
            assert path == "modes[*].score_kcal_mol"
            assert value == (min(scores) if statement == "score_minimum" else max(scores))
            assert claim["operation"] == ("minimum" if statement == "score_minimum" else "maximum")
        elif statement == "contact_count":
            rows = _resolve(stored, path)
            assert claim["row_selector"] == {"mode": int(path[6:path.index("]")]) + 1}
            assert value == len(rows)
            assert value == stored["counts"]["contacts_by_mode"][claim["row_selector"]["mode"] - 1]
        elif statement == "contact_kind_count":
            rows = _resolve(stored, path)
            kind = claim["row_selector"]["kind"]
            assert value == sum(1 for row in rows if row["kind"] == kind)
            assert value == sum(1 for row in rows if _kind(row["ligand_element"],
                                                           row["receptor_atom"]["element"]) == kind)
            assert kind in claim["operation"]
        else:
            assert "[*]" not in path
            assert value == _resolve(stored, path)
            # an uncomputed (null) field is never a statement; only null residue labels are kept as read
            assert value is not None or statement == "removed_instance"
        rendered = claim["rendered_value"]
        if claim["rounding"] == "score_1dp":
            assert rendered == _score(value) and claim["unit"] == "kcal/mol"
        elif claim["rounding"] == "distance_2dp":
            assert rendered == _distance(value) and claim["unit"] == "A"
        elif claim["rounding"] == "integer":
            assert type(value) is int and rendered == str(value)
        elif claim["rounding"] == "flag":
            assert rendered == ("true" if value else "false")
    for index, row in enumerate(stored["modes"]):
        assert _claim(manifest, "score", f"modes[{index}].score_kcal_mol")["rendered_value"] == \
            _score(row["score_kcal_mol"])
    assert not [c for c in manifest["claims"] if "pose_sdf" in c["field_path"]]


# ----------------------------------------------------------------- rendering and forbidden words
@pytest.mark.parametrize(("value", "text"), [
    (-7.05, "-7.1"), (-7.04, "-7.0"), (-5.25, "-5.3"), (2.25, "2.3"), (-0.04, "0.0"), (-0.05, "-0.1"),
    (-6.0, "-6.0"), (0.0, "0.0"), (-12.349, "-12.3")])
def test_score_rendering_is_one_decimal_half_up(value, text):
    assert dr.render_score(value) == text == _score(value)
    assert round(-5.25, 1) == -5.2   # the float rounding the rule forbids


@pytest.mark.parametrize(("value", "text"), [(2.675, "2.68"), (3.004999, "3.00"), (0.005, "0.01"), (12.0, "12.00")])
def test_distance_rendering_is_two_decimals_half_up(value, text):
    assert dr.render_distance(value) == text == _distance(value)


def test_forbidden_words_with_fixed_limitation_and_score_label_exemptions():
    assert dr.FIXED_LIMITATIONS == C.LIMITATIONS and dr.SCORE_LABEL == C.SCORE_LABEL
    label_line = f"- 점수 이름: {C.SCORE_LABEL}"
    text = "\n".join(["# x", *C.LIMITATIONS, label_line, C.SCORE_LABEL, "ok"])
    assert dr.check_no_interpretation(text) == text
    for bad in ("순위 1", "최고 점수", "개선된 점수", "결합 강도", "결합강도", "rank 1", "ranked", "best pose", "Best",
                "improve", "improved", "stronger", "친화도", "binding", "affinity", "좋은 포즈", "나쁜 포즈", "약물 유사",
                "독성", "안전", "활성", "억제", "합성 가능", "최적 포즈", "중요", "핵심", "기능", "drug-like", "toxic",
                "safe", "synthesizable", "optimal", "good", "active", "inhibitor", "important", "hydrogen bond",
                "H-bond", "수소결합"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            dr.check_no_interpretation(f"ok\n{bad}")
    # the score label exempts only its own exact text: anything else on that line is still checked
    for near in (f"{label_line} best", f"{label_line} 순위 1", f"친화 {C.SCORE_LABEL}",
                 f"친{C.SCORE_LABEL}화", f"rank{C.SCORE_LABEL}", f"{C.SCORE_LABEL}stronger",
                 C.SCORE_LABEL.replace("친화도가 아님", "친화도임"), C.SCORE_LABEL.replace("값.", "값"),
                 "qvina 점수(kcal/mol, 친화도가 아님)", C.SCORE_LABEL.lower() + " 친화"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            dr.check_no_interpretation(near)
    # the fixed limitation lines are exempt only when the whole line is exactly the sentence
    for near in (f"- {C.LIMITATIONS[0]}", C.LIMITATIONS[0] + " ", " " + C.LIMITATIONS[7],
                 C.LIMITATIONS[1] + " best", C.LIMITATIONS[0] + C.SCORE_LABEL, C.LIMITATIONS[4][:-1]):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            dr.check_no_interpretation(near)


# ----------------------------------------------------------------- correct reports
def test_free_sdf_report_round_trips_and_every_value_is_bound(client, world):
    run = _run(world)
    events_before = len(list(run.events.read()))
    created = _report(client, world, "free")
    added = list(run.events.read())[events_before:]
    assert [e["type"] for e in added if e["type"] != "object_created"] == ["method_report_created"]
    assert {e.get("kind") for e in added if e["type"] == "object_created"} == {"report_markdown",
                                                                               "method_report_manifest"}
    assert not [e for e in added if e["type"].startswith("job_") or e["type"].startswith("budget")]
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["free"]
    assert manifest["schema"] == "method_report_manifest@1" and manifest["analysis_type"] == "ligand_docking"
    assert manifest["render_version"] == "ligand_docking_markdown@1" and manifest["status"] == "complete"
    assert manifest["generation_mode"] == "local_rules_no_egress" and manifest["result_schema"] == "docking_result@1"
    assert manifest["null_result"] is False and manifest["score_label"] == C.SCORE_LABEL
    assert manifest["limitations"] == list(C.applicable_limitations(mode="free", source="sdf", removed_instance=False,
                                                                     unspecified_stereo_centers=None))
    for key in ("method", "input_sha256", "inputs", "box", "parameters", "engine", "preparation", "counts"):
        assert manifest[key] == stored[key], key
    assert "modes" not in manifest and "pose_sdf" not in json.dumps(manifest)
    assert manifest["provenance"]["docking"]["job_id"] == world["jobs"]["free"]
    _verify_independently(world, "free", manifest)
    assert _claim(manifest, "mode_count", "counts.modes")["rendered_value"] == str(len(stored["modes"]))
    scores = [row["score_kcal_mol"] for row in stored["modes"]]
    assert _claim(manifest, "score_minimum")["rendered_value"] == _score(min(scores))
    assert _claim(manifest, "score_maximum")["rendered_value"] == _score(max(scores))
    for index, row in enumerate(stored["modes"]):
        number = index + 1
        assert _claim(manifest, "contact_count", mode=number)["exact_value"] == len(row["contacts"])
        for kind in C.CONTACT_KINDS:
            _claim(manifest, "contact_kind_count", mode=number, kind=kind)
        assert _claim(manifest, "min_heavy_atom_distance", mode=number)["rendered_value"] == \
            _distance(row["min_heavy_atom_distance_A"])
        assert _claim(manifest, "atoms_outside_box", mode=number)["exact_value"] == row["atoms_outside_box"]
        assert f"| 모드 {number}(엔진 출력 순서) | {_score(row['score_kcal_mol'])} | {len(row['contacts'])} |" in markdown
    for axis in range(3):
        assert _claim(manifest, "box", f"box.center_A[{axis}]")["rendered_value"] == \
            _distance(stored["box"]["center_A"][axis])
        assert _claim(manifest, "box", f"box.size_A[{axis}]")["rendered_value"] == \
            _distance(stored["box"]["size_A"][axis])
    for key in ("seed", "exhaustiveness", "num_modes", "energy_range", "cpu"):
        _claim(manifest, "parameter", f"parameters.{key}")
    assert _claim(manifest, "engine", "engine.name")["rendered_value"] == "qvina"
    assert _claim(manifest, "engine", "engine.version")["exact_value"] == stored["engine"]["version"]
    assert _claim(manifest, "ligand_input", "inputs.ligand.source")["rendered_value"] == "sdf"
    assert _claim(manifest, "ligand_input", "inputs.ligand.generated.hydrogens")["rendered_value"] == "false"
    # no statement for what this result did not compute
    assert not _statements(manifest) & {"core_max_deviation", "sample_count", "removed_instance"}
    assert not [c for c in manifest["claims"] if c["field_path"] in ("parameters.conformers", "box.margin_A",
                                                                    "inputs.ligand.parent_sdf_sha256")]
    # wording: the full score label, mode naming, limitations verbatim, no sample naming
    assert f"\n- 점수 이름: {C.SCORE_LABEL}\n" in markdown
    assert "| 모드 | qvina 점수(kcal/mol) |" in markdown and "샘플" not in markdown
    assert "점수 최솟값" in markdown and "점수 최댓값" in markdown
    for line in manifest["limitations"]:
        assert f"\n{line}\n" in markdown
    assert dr.check_no_interpretation(markdown) == markdown
    # snapshot
    snapshot = manifest["snapshot"]
    assert snapshot["event_seq"] == events_before and snapshot["capability"]["available"] is True
    assert set(snapshot["budget"]) >= {"expensive_calls"}
    # list / selected / download are byte-identical and write no event
    rid = world["rid"]
    events_before = len(list(run.events.read()))
    listed = client.get(f"/runs/{rid}/reports")
    assert listed.status_code == 200, listed.text
    entry = next(item for item in listed.json() if item["handle"] == created["handle"])
    assert entry["analysis_type"] == "ligand_docking" and entry["result_handle"] == world["handles"]["free"]
    selected = _selected(client, world, created["handle"])
    assert selected.status_code == 200 and selected.json()["markdown"] == markdown
    assert canonical_json(selected.json()["manifest"]) == canonical_json(manifest)
    md = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "markdown"})
    js = client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"], "format": "json"})
    assert md.status_code == js.status_code == 200
    assert md.content == markdown.encode("utf-8") == run.store.load(created["markdown_handle"])
    assert js.content == canonical_json(manifest) == canonical_json(run.store.load(created["handle"]))
    assert len(list(run.events.read())) == events_before
    # a second report of the same result is a new object; the first report's bytes do not change
    second = _report(client, world, "free")
    assert second["handle"] != created["handle"] and second["manifest"]["claims"] == manifest["claims"]
    assert client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}).content == md.content


def test_core_fixed_candidate_report_names_samples_and_carries_core_deviation(client, world):
    created = _report(client, world, "core")
    manifest, markdown = created["manifest"], created["markdown"]
    stored = world["stored"]["core"]
    _verify_independently(world, "core", manifest)
    assert manifest["method"] == "qvina_core_fixed_score_only_v1"
    assert manifest["limitations"] == list(C.applicable_limitations(
        mode="core_fixed", source="candidate", removed_instance=False,
        unspecified_stereo_centers=stored["inputs"]["ligand"]["unspecified_stereo_centers"]))
    for index, row in enumerate(stored["modes"]):
        number = index + 1
        claim = _claim(manifest, "core_max_deviation", f"modes[{index}].core_max_deviation_A", mode=number)
        assert claim["rendered_value"] == _distance(row["core_max_deviation_A"]) and claim["unit"] == "A"
        assert f"| 샘플 {number}(점수 오름차순 나열) | {_score(row['score_kcal_mol'])} |" in markdown
    # two stored rows: the minimum and maximum are over both (the derived values; never "best")
    scores = [row["score_kcal_mol"] for row in stored["modes"]]
    assert len(scores) == 2
    assert _claim(manifest, "score_minimum")["rendered_value"] == _score(min(scores))
    assert _claim(manifest, "score_maximum")["rendered_value"] == _score(max(scores))
    for key in ("samples_generated", "samples_scored"):
        assert _claim(manifest, "sample_count", f"counts.{key}")["exact_value"] == stored["counts"][key]
    assert _claim(manifest, "parameter", "parameters.conformers")["rendered_value"] == "2"
    assert _claim(manifest, "box", "box.margin_A")["rendered_value"] == "8.00"
    assert "엔진 출력 순서)" not in markdown and "코어 최대 이탈" in markdown
    _check_candidate_provenance(world, "core", manifest, markdown)


def _check_candidate_provenance(world, name, manifest, markdown) -> None:
    lig = world["stored"][name]["inputs"]["ligand"]
    assert _claim(manifest, "ligand_input", "inputs.ligand.source")["rendered_value"] == "candidate"
    assert _claim(manifest, "ligand_input", "inputs.ligand.candidate_set_handle")["exact_value"] == \
        world["candidate_set"]
    assert _claim(manifest, "ligand_input", "inputs.ligand.candidate_id")["exact_value"] == CANDIDATE_ID
    assert _claim(manifest, "ligand_input", "inputs.ligand.parent_sdf_handle")["exact_value"] == world["parent"]
    parent_sha = _claim(manifest, "ligand_input", "inputs.ligand.parent_sdf_sha256")["exact_value"]
    assert parent_sha == hashlib.sha256(PARENT).hexdigest() == lig["parent_sdf_sha256"]
    for key in ("hydrogens", "coordinates"):
        assert _claim(manifest, "ligand_input", f"inputs.ligand.generated.{key}")["rendered_value"] == "true"
    assert _claim(manifest, "ligand_input", "inputs.ligand.unspecified_stereo_centers")["exact_value"] == \
        lig["unspecified_stereo_centers"]
    assert parent_sha in markdown and "RDKit이 만든 수소: true" in markdown and "RDKit이 만든 좌표: true" in markdown
    assert C.LIMITATIONS[6] in manifest["limitations"]


def test_candidate_free_report_carries_candidate_provenance(client, world):
    created = _report(client, world, "cand_free")
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(world, "cand_free", manifest)
    _check_candidate_provenance(world, "cand_free", manifest, markdown)
    assert C.LIMITATIONS[9] in manifest["limitations"] and "core_max_deviation" not in _statements(manifest)
    assert "| 모드 1(엔진 출력 순서) |" in markdown


def test_removed_instance_report_lists_the_seven_fields(client, world):
    created = _report(client, world, "instance")
    manifest, markdown = created["manifest"], created["markdown"]
    removed = world["stored"]["instance"]["inputs"]["receptor"]["removed_instance"]
    _verify_independently(world, "instance", manifest)
    for field in RESIDUE_FIELDS:
        claim = _claim(manifest, "removed_instance", f"inputs.receptor.removed_instance.residue.{field}")
        assert claim["exact_value"] == INSTANCE[field] and claim["rendered_value"] == json.dumps(INSTANCE[field])
    assert _claim(manifest, "removed_instance", "inputs.receptor.removed_instance.atom_count")["exact_value"] == \
        removed["atom_count"]
    assert C.LIMITATIONS[8] in manifest["limitations"] and "뺀 리간드 인스턴스" in markdown
    assert _claim(manifest, "receptor_input", "inputs.receptor.handle")["exact_value"] == world["complex"]


def test_zero_mode_report_has_no_row_statistics(client, world):
    created = _report(client, world, "empty")
    manifest, markdown = created["manifest"], created["markdown"]
    _verify_independently(world, "empty", manifest)
    assert manifest["null_result"] is True and manifest["counts"]["modes"] == 0
    assert _claim(manifest, "mode_count", "counts.modes")["rendered_value"] == "0"
    assert not _statements(manifest) & {"score", "score_minimum", "score_maximum", "contact_count",
                                        "contact_kind_count", "atoms_outside_box", "min_heavy_atom_distance"}
    assert "scientific\\_null" in markdown and "점수 최솟값 (" not in markdown and "| 모드 |" not in markdown


# ----------------------------------------------------------------- rejections
def _forge(run, manifest: dict, markdown: str, mutate) -> str:
    """LABELED TEST FABRICATION: store a tampered report manifest and its creation event."""
    forged = copy.deepcopy(manifest)
    mutate(forged)
    with run._owner():
        md = run.store.put("report_markdown", "report_markdown@1", markdown.encode(), fmt="md",
                           produced_by="forged_test_report", summary={"result_handle": manifest["result_handle"]})
        forged["markdown_handle"] = md.handle
        report = run.store.put("method_report_manifest", "method_report_manifest@1", forged,
                               produced_by="forged_test_report",
                               summary={"result_handle": forged["result_handle"], "analysis_type": "ligand_docking",
                                        "status": "complete"})
        run.events.append("method_report_created", report_handle=report.handle, markdown_handle=md.handle,
                          result_handle=forged["result_handle"], snapshot_event_seq=forged["snapshot"]["event_seq"])
    return report.handle


def test_mixed_evidence_and_other_statement_fields_are_rejected(private_client, world):
    client = private_client
    run = _run(world)
    handle = world["handles"]["free"]
    created = _report(client, world, "free")
    manifest, markdown = created["manifest"], created["markdown"]
    score = _claim(manifest, "score", "modes[0].score_kcal_mol")
    contacts = _claim(manifest, "contact_count", mode=1)
    core = _report(client, world, "core")["manifest"]
    core_score = _claim(core, "score", "modes[0].score_kcal_mol")
    core_dev = _claim(core, "core_max_deviation", mode=1)
    for claim in (score, contacts):
        assert dr.validate_docking_claim(run, handle, copy.deepcopy(claim)) == claim
    cases = [
        ("source_mismatch", core_score),                     # a core-fixed result's score in a free report
        ("source_mismatch", core_dev),
        ("source_mismatch", {**score, "source_handle": world["handles"]["core"]}),
        ("source_mismatch", {**score, "source_sha256": "0" * 64}),
        ("evidence_kind_mismatch", {**score, "evidence_kind": "reference_value"}),
        ("field_rule", {**score, "field_path": "modes[0].min_heavy_atom_distance_A"}),   # another statement's field
        ("field_rule", {**score, "field_path": "modes[*].score_kcal_mol"}),
        ("field_rule", {**contacts, "field_path": "counts.contacts_by_mode"}),
        ("field_rule", {**score, "field_path": "modes[0].engine_rmsd_lb_A"}),
        ("statement_not_allowed", {**score, "statement_id": "binding_affinity"}),
        ("source_kind_mismatch", {**score, "source_kind": "ligand_candidate_set"}),
        ("binding_mismatch", {**score, "quantity": "affinity_kcal_mol"}),
        ("binding_mismatch", {**score, "unit": "kJ/mol"}),
        ("binding_mismatch", {**score, "subject": {"docking_result_handle": world["handles"]["core"]}}),
        ("field_not_allowed", {**score, "row_selector": {"mode": 2}}),
    ]
    for reason, claim in cases:
        with pytest.raises(EvidenceError, match=reason):
            dr.validate_docking_claim(run, handle, claim)
    for reason, claim in cases:
        def mutate(forged, claim=claim):
            index = next(i for i, c in enumerate(forged["claims"]) if c == score)
            forged["claims"][index] = claim
        assert _selected(client, world, _forge(run, manifest, markdown, mutate)).status_code == 422, reason
    # a core-fixed result's rows appended to a free report (mixing the two methods) is refused
    mixed = _forge(run, manifest, markdown, lambda f: f["claims"].append(core_dev))
    assert _selected(client, world, mixed).status_code == 422
    # the core-fixed method fields copied into a free report are refused
    swapped = _forge(run, manifest, markdown, lambda f: f.update(method=core["method"]))
    assert _selected(client, world, swapped).status_code == 422


def test_wrong_rounding_is_rejected(private_client, world):
    client = private_client
    run = _run(world)
    handle = world["handles"]["free"]
    created = _report(client, world, "free")
    manifest = created["manifest"]
    score = _claim(manifest, "score", "modes[0].score_kcal_mol")
    exact = score["exact_value"]
    good = _score(exact)
    wrong_texts = {f"{Decimal(str(exact)):.2f}", repr(exact), f"{round(exact, 1) - 0.1:.1f}", good + "0",
                   str(int(exact))} - {good}
    for wrong in wrong_texts:
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            dr.validate_docking_claim(run, handle, {**score, "rendered_value": wrong})
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        dr.validate_docking_claim(run, handle, {**score, "rounding": "distance_2dp",
                                                "rendered_value": _distance(exact)})
    distance = _claim(manifest, "min_heavy_atom_distance", mode=1)
    for wrong in (_score(distance["exact_value"]), f"{distance['exact_value']:.3f}"):
        with pytest.raises(EvidenceError, match="binding_mismatch"):
            dr.validate_docking_claim(run, handle, {**distance, "rendered_value": wrong})
    count = _claim(manifest, "contact_count", mode=1)
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        dr.validate_docking_claim(run, handle, {**count, "exact_value": count["exact_value"] + 1,
                                                "rendered_value": str(count["exact_value"] + 1)})
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        dr.validate_docking_claim(run, handle, {**count, "rendered_value": f"{count['exact_value']}.0"})
    forged = _forge(run, manifest, created["markdown"],
                    lambda f: next(c for c in f["claims"] if c == score).update(rendered_value=f"{exact:.2f}"))
    assert _selected(client, world, forged).status_code == 422
    row = f"| 모드 1(엔진 출력 순서) | {good} |"
    edited = _forge(run, manifest, created["markdown"].replace(row, f"| 모드 1(엔진 출력 순서) | {exact:.2f} |"),
                    lambda f: None)
    assert row in created["markdown"] and _selected(client, world, edited).status_code == 422


def test_uncomputed_values_written_as_zero_are_rejected(private_client, world):
    client = private_client
    run = _run(world)
    free = _report(client, world, "free")
    empty = _report(client, world, "empty")
    score = _claim(free["manifest"], "score", "modes[0].score_kcal_mol")
    distance = _claim(free["manifest"], "min_heavy_atom_distance", mode=1)
    seed = _claim(free["manifest"], "parameter", "parameters.seed")
    free_cases = {
        "core_deviation": {**distance, "statement_id": "core_max_deviation", "field_path":
                           "modes[0].core_max_deviation_A", "quantity": "core_max_deviation_A", "exact_value": 0.0,
                           "rendered_value": "0.00"},
        "conformers": {**seed, "field_path": "parameters.conformers", "quantity": "conformers", "exact_value": 0,
                       "rendered_value": "0"},
        "margin": {**distance, "statement_id": "box", "field_path": "box.margin_A", "row_selector": None,
                   "quantity": "margin_A", "exact_value": 0.0, "rendered_value": "0.00"},
        "samples": {**seed, "statement_id": "sample_count", "field_path": "counts.samples_generated",
                    "quantity": "samples_generated", "exact_value": 0, "rendered_value": "0"},
    }
    empty_cases = {
        "score": {**score, "source_handle": world["handles"]["empty"],
                  "source_sha256": world["handles"]["empty"].rsplit("/", 1)[-1],
                  "subject": {"docking_result_handle": world["handles"]["empty"]}, "exact_value": 0.0,
                  "rendered_value": "0.0"},
    }
    empty_cases["minimum"] = {**empty_cases["score"], "statement_id": "score_minimum",
                              "field_path": "modes[*].score_kcal_mol", "row_selector": None, "operation": "minimum"}
    for name, claim in free_cases.items():
        with pytest.raises(EvidenceError, match="field_not_allowed"):
            dr.validate_docking_claim(run, world["handles"]["free"], claim)
        forged = _forge(run, free["manifest"], free["markdown"], lambda f, claim=claim: f["claims"].append(claim))
        assert _selected(client, world, forged).status_code == 422, name
    for name, claim in empty_cases.items():
        with pytest.raises(EvidenceError, match="field_not_allowed"):
            dr.validate_docking_claim(run, world["handles"]["empty"], claim)
        forged = _forge(run, empty["manifest"], empty["markdown"], lambda f, claim=claim: f["claims"].append(claim))
        assert _selected(client, world, forged).status_code == 422, name


def test_required_candidate_provenance_and_core_deviation(private_client, world, monkeypatch):
    """LABELED TEST FABRICATIONS (in memory): stored results with a required field removed."""
    core_handle, cand_handle = world["handles"]["core"], world["handles"]["cand_free"]
    core, cand = world["stored"]["core"], world["stored"]["cand_free"]
    assert dr.claims_for(core_handle, core)
    for mutate in (lambda c: c["modes"][0].update(core_max_deviation_A=None),
                   lambda c: c["modes"][-1].pop("core_max_deviation_A")):
        edited = copy.deepcopy(core)
        mutate(edited)
        with pytest.raises(EvidenceError, match="core_max_deviation_missing"):
            dr.claims_for(core_handle, edited)
    for key, value in (("parent_sdf_sha256", None), ("parent_sdf_handle", None), ("candidate_set_handle", None),
                       ("candidate_id", None)):
        edited = copy.deepcopy(cand)
        edited["inputs"]["ligand"][key] = value
        with pytest.raises(EvidenceError, match="candidate_provenance_missing"):
            dr.claims_for(cand_handle, edited)
    for generated in ({"hydrogens": False, "coordinates": True}, {"hydrogens": True, "coordinates": False}):
        edited = copy.deepcopy(cand)
        edited["inputs"]["ligand"]["generated"] = generated
        with pytest.raises(EvidenceError, match="candidate_provenance_missing"):
            dr.claims_for(cand_handle, edited)
    edited = copy.deepcopy(core)
    edited["method"] = C.METHODS["free"]   # a core-fixed result labeled free: methods are never mixed
    with pytest.raises(EvidenceError, match="method_mismatch"):
        dr.claims_for(core_handle, edited)
    # the build path refuses too (report creation never proceeds without the field)
    real = docking_bundle.validated_result

    def without_deviation(run, handle):
        content = copy.deepcopy(real(run, handle))
        if handle == core_handle:
            content["modes"][0]["core_max_deviation_A"] = None
        return content
    monkeypatch.setattr(docking_bundle, "validated_result", without_deviation)
    response = private_client.post(f"/runs/{world['rid']}/method_reports", json={"result_handle": core_handle})
    assert response.status_code == 422 and "core_max_deviation_missing" in response.text


def test_interpretive_statements_are_rejected(private_client, world):
    client = private_client
    run = _run(world)
    created = _report(client, world, "free")
    manifest, markdown = created["manifest"], created["markdown"]
    forged = [
        _forge(run, manifest, markdown.replace("## Limitations", "모드 1이 best 포즈다.\n\n## Limitations"),
               lambda f: None),
        _forge(run, manifest, markdown.replace("## Limitations", "모드 1의 순위가 가장 높다.\n\n## Limitations"),
               lambda f: None),
        _forge(run, manifest, markdown.replace(f"- 점수 이름: {C.SCORE_LABEL}",
                                               f"- 점수 이름: {C.SCORE_LABEL} 개선됨"), lambda f: None),
        _forge(run, manifest, markdown, lambda f: f["limitations"].append("점수가 낮아 친화도가 높다.")),
        _forge(run, manifest, markdown, lambda f: f.update(evidence_statement="모드 1이 최고다.")),
        _forge(run, manifest, markdown, lambda f: f.update(score_label="qvina 점수(kcal/mol, 결합 친화도)")),
    ]
    for handle in forged:
        assert _selected(client, world, handle).status_code == 422
    for extra in ("rank 1", "improve", "stronger", "친화"):
        with pytest.raises(EvidenceError, match="interpretive_statement"):
            dr.render_docking_report({**manifest, "limitations": [*manifest["limitations"], extra]})
    assert client.get(f"/runs/{world['rid']}/reports").status_code == 422   # forged objects fail the list closed


def test_contact_counts_are_recounted_from_stored_rows(world):
    handle = world["handles"]["free"]
    stored = world["stored"]["free"]
    claims = dr.claims_for(handle, stored)
    index = next(i for i, row in enumerate(stored["modes"]) if row["contacts"])
    manifest = {"claims": claims}
    kind = stored["modes"][index]["contacts"][0]["kind"]
    claim = _claim(manifest, "contact_kind_count", mode=index + 1, kind=kind)
    edited = copy.deepcopy(stored)   # LABELED TEST FABRICATION (in memory): one contact row's kind changed
    edited["modes"][index]["contacts"][0]["kind"] = next(k for k in C.CONTACT_KINDS if k != kind)
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        dr.match_claim(dr.claims_for(handle, edited), claim)
    edited = copy.deepcopy(stored)   # one contact row removed: the total is recounted
    edited["modes"][index]["contacts"].pop()
    with pytest.raises(EvidenceError, match="binding_mismatch"):
        dr.match_claim(dr.claims_for(handle, edited), _claim(manifest, "contact_count", mode=index + 1))
    assert "count_where(kind == " in claim["operation"] and claim["row_selector"] == {"mode": index + 1, "kind": kind}


def test_reopen_rejects_tampered_result_and_manifest(world, monkeypatch, tmp_path):
    """A copy of the run whose stored bytes were edited in place (labeled fault injection)."""
    root = tmp_path / "runs"
    shutil.copytree(world["root"] / world["rid"], root / world["rid"])
    monkeypatch.setattr(api_module, "RUNS_DIR", root)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = world["rid"]
    created = _report(client, world, "free")
    other = _report(client, world, "core")
    api_module.RUNS.clear()
    assert _selected(client, world, created["handle"]).status_code == 200
    # the report manifest edited in place (a score rendering changed) never reopens
    path = root / rid / "objects" / f"{other['handle'].rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["claims"][0]["rendered_value"] = "x"
    path.write_bytes(canonical_json(content))
    assert _selected(client, world, other["handle"]).status_code == 422
    # the docking result edited in place: no reopen, no download, no new report
    path = root / rid / "objects" / f"{world['handles']['free'].rsplit('/', 1)[-1]}.json"
    content = json.loads(path.read_bytes())
    content["modes"][0]["score_kcal_mol"] = -99.0
    path.write_bytes(canonical_json(content))
    for response in (_selected(client, world, created["handle"]),
                     client.get(f"/runs/{rid}/reports/download", params={"handle": created["handle"]}),
                     client.get(f"/runs/{rid}/reports/download",
                                params={"handle": created["handle"], "format": "json"})):
        assert response.status_code == 422 and "-99" not in response.text
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["handles"]["free"]})
    assert response.status_code == 422


def test_unpublished_wrong_kind_and_filtered_sources_are_refused(private_client, world):
    client = private_client
    run = _run(world)
    rid = world["rid"]
    content = copy.deepcopy(world["stored"]["free"])   # LABELED TEST FABRICATION: no job published this object
    content["modes"][0]["score_kcal_mol"] = -1.0
    with run._owner():
        forged = run.store.put("docking_result", "docking_result@1", content, produced_by="forged_test_docking")
    response = client.post(f"/runs/{rid}/method_reports", json={"result_handle": forged.handle})
    assert response.status_code == 422 and "docking_result_invalid" in response.text
    response = client.post(f"/runs/{rid}/method_reports",
                           json={"result_handle": world["handles"]["free"], "filters": {}})
    assert response.status_code == 422 and "filters" in response.text
    for handle in (world["receptor"], world["parent"], f"obj://{rid}/docking_result/{'1' * 64}"):
        assert client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle}).status_code == 422


def test_existing_report_kinds_and_saved_bytes_are_unchanged(private_client, world):
    """A ligand candidate report saved before docking reports exist reads back byte for byte afterwards."""
    client = private_client
    rid = world["rid"]
    created = client.post(f"/runs/{rid}/method_reports", json={"result_handle": world["candidate_set"]})
    assert created.status_code == 201, created.text
    ligand = created.json()
    before = {fmt: client.get(f"/runs/{rid}/reports/download", params={"handle": ligand["handle"], "format": fmt})
              .content for fmt in ("markdown", "json")}
    docking = _report(client, world, "free")
    after = {fmt: client.get(f"/runs/{rid}/reports/download", params={"handle": ligand["handle"], "format": fmt})
             .content for fmt in ("markdown", "json")}
    assert after == before and before["markdown"] == ligand["markdown"].encode("utf-8")
    assert before["json"] == canonical_json(ligand["manifest"])
    listed = {row["handle"]: row["analysis_type"] for row in client.get(f"/runs/{rid}/reports").json()}
    assert listed[ligand["handle"]] == "ligand_candidates" and listed[docking["handle"]] == "ligand_docking"
    assert ligand["manifest"]["analysis_type"] == "ligand_candidates"


def test_report_module_reads_only_stored_evidence():
    source = Path(dr.__file__).read_text()
    tree = ast.parse(source)
    names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    names |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(name.split(".")[0] in ("rdkit", "meeko", "MDAnalysis") for name in names)
    for forbidden in ("subprocess", "requests", "httpx", "urllib", "socket", "JobQueue", ".submit(", "stage(",
                      "qvina2"):
        assert forbidden not in source
