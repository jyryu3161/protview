"""M22 T3: the isolated GA design worker (``mw/jobs/ligand_ga_worker.py``) in its pinned interpreter.

The worker runs in ``.deps/docking/venv-locked`` as the guardian will launch it (``python -I ligand_ga_worker.py`` in a
private directory with ``input.json`` + ``structure.json``) with the real ``qvina2`` and real RDKit fingerprints.
Clocks and output caps are shrunk only here, by loading the module by path in that interpreter and assigning its
constants before ``entry`` (no request field, no environment variable). When either pinned environment is missing
these tests fail (no skip). The server test process never imports RDKit, Meeko or MDAnalysis.

References (never the worker's own code):
- the independent standard-library oracle ``fixtures/ligand_ga/independent_ga_oracle.py`` (spec 3, written in T1 before
  this worker) and its recorded paths in ``fixtures/ligand_ga/expected.json``; the oracle's similarity is the exact
  ratio of the stored RDKit on-bit sets;
- a standalone M18 ``docking_worker.py`` run on the same staged payload (an individual = a single M18 docking);
- ``t1_observations.small_pool_docking``: real qvina2 first-mode scores recorded in T1 (observations).

Two kinds of runs: real-engine runs (every docking is real qvina2; reused individuals carry real result bytes from an
earlier real run in this module) and selection-logic runs (``SYNTHETIC``) where only the per-individual docking
function is replaced in the test process of the worker by a stand-in that returns the vector's labelled synthetic
scores, so the oracle vectors with ties and no-score individuals can be compared rng call by rng call; fingerprints
there are still real RDKit. Synthetic values never leave ``tmp_path``.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import engine_hold as EH
import psutil
import pytest

from mw import ligand_ga_constants as GC
from mw import ligand_ga_inputs

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "backend/mw/jobs/ligand_ga_worker.py"
SINGLE = ROOT / "backend/mw/jobs/docking_worker.py"
PY = ROOT / ".deps/docking/venv-locked/bin/python"
QVINA = ROOT / ".deps/qvina/env/bin/qvina2"
GA_FIX = Path(__file__).parent / "fixtures/ligand_ga"
REC = (Path(__file__).parent / "fixtures/chemical/prolif-vina-rec.pdb").read_bytes()
PARENT = (Path(__file__).parent / "fixtures/docking/public-derived-parent-record0.sdf").read_bytes()
EXPECTED = json.loads((GA_FIX / "expected.json").read_text())
CANDIDATE_SET = json.loads((GA_FIX / "m17-candidate-set-small-pool.json").read_text())
CANDS = CANDIDATE_SET["candidates"]
IDS = [c["id"] for c in CANDS]
OBS = EXPECTED["t1_observations"]["small_pool_docking"]
OBS_SCORES = {row["candidate_id"]: row["first_mode_score_kcal_mol"] for row in OBS["rows"]}
VECTORS = EXPECTED["ga_vectors"]
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
HANDLE = "obj://run_t3/chemical_raw_input/" + "a" * 64
CONTROL = {"nonce": "0" * 32, "job_id": "job_m22t3", "attempt_id": "att_m22t3"}
PARAMS = {"seed": 1, "exhaustiveness": 1, "num_modes": 2, "energy_range": 3.0, "conformers": None}   # = OBS
RECORD_KEYS = ["candidate_id", "origin", "parent_candidate_id", "similarity", "evaluation", "eval_index"]
LOAD = ("import importlib.util, json, os, sys, time\n"
        f"spec = importlib.util.spec_from_file_location('lgw', {str(WORKER)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n")


def _oracle():
    spec = importlib.util.spec_from_file_location("independent_ga_oracle", GA_FIX / "independent_ga_oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = _oracle()
BITS = {row["candidate_id"]: frozenset(row["morgan_r2_2048_on_bits"]) for row in EXPECTED["pools"]["small"]["candidates"]}


def _env_ready() -> None:
    assert PY.is_file(), f"pinned docking interpreter missing at {PY} (no skip)"
    assert QVINA.is_file(), f"pinned qvina2 missing at {QVINA} (no skip)"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _entry(raw: bytes) -> dict:
    return {"b64": base64.b64encode(raw).decode(), "sha256": _sha(raw)}


def _ga(**values) -> dict:
    base = {key: default for key, (_low, _high, default) in GC.GA_RANGES.items()}
    out = {**base, **values}
    out["random_fraction"] = float(out["random_fraction"])
    return out


def _manifest(ga: dict, *, reuse: dict[str, bytes] | None = None, eligible: list[bool] | None = None,
              cands: list[dict] | None = None, params: dict | None = None) -> dict:
    """The staged ``ligand_ga_worker_input@1``. ``input_sha256`` is a staging stand-in here (the worker only checks its
    shape and records it nowhere; the server's real value is ``docking_inputs.input_sha256``)."""
    cands = cands or CANDS
    eligible = eligible or [True] * len(cands)
    reuse = reuse or {}
    pool = []
    for index, (cand, ok) in enumerate(zip(cands, eligible, strict=True)):
        pool.append({"index": index, "candidate_id": cand["id"], "smiles": cand["smiles"], "eligible": ok,
                     "retained_parent_atoms": cand["retained_parent_atoms"] if ok else None,
                     "stereo_flag": cand["stereo_flag"] if ok else None,
                     "input_sha256": _sha(cand["id"].encode()) if ok else None,
                     "reuse_result_bytes": _entry(reuse[cand["id"]]) if ok and cand["id"] in reuse else None})
    return {"schema": "ligand_ga_worker_input@1",
            "receptor": {"handle": HANDLE, "format": "pdb", "bytes": _entry(REC), "model_number": 1,
                         "connectivity": {"kind": "pdb_conect", "sidecar": None}, "instance": None},
            "parent_sdf": _entry(PARENT), "candidate_set_parent_sha256": CANDIDATE_SET["parent_sha256"],
            "box": {"source": "manual", "center_A": OBS["box"]["center_A"], "size_A": OBS["box"]["size_A"]},
            "parameters": params or PARAMS, "ga": ga, "pool": pool}


def _payload(manifest: dict, cid: str) -> dict:
    """The M18 staged payload of one individual, built test-side (docking_bundle.stage shape)."""
    row = next(r for r in manifest["pool"] if r["candidate_id"] == cid)
    candidate = {"id": cid, "smiles": row["smiles"], "retained_parent_atoms": row["retained_parent_atoms"],
                 "stereo_flag": row["stereo_flag"]}
    return {"schema": "docking_worker_input@1", "receptor": manifest["receptor"],
            "ligand": {"source": "candidate", "parent_sdf": manifest["parent_sdf"],
                       "candidate_set_parent_sha256": manifest["candidate_set_parent_sha256"], "candidate": candidate},
            "mode": "free", "box": manifest["box"], "parameters": manifest["parameters"]}


def _stage(root: Path, payload: dict, adapter: str) -> None:
    _env_ready()
    root.mkdir(parents=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps({**CONTROL, "adapter": adapter, "input_sha256": _sha(raw)}))


def _argv(patch: str | None) -> list[str]:
    if patch is None:
        return [str(PY), "-I", str(WORKER)]
    return [str(PY), "-I", "-c", LOAD + patch + "\nraise SystemExit(m.entry([]))\n"]


def _dir(root: Path, name: str) -> dict[str, bytes]:
    folder = root / name
    return {} if not folder.is_dir() else {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def _canonical(raw: bytes) -> dict:
    data = json.loads(raw)
    assert raw == json.dumps(data, sort_keys=True, separators=(",", ":")).encode(), "canonical JSON"
    return data


class Out:
    def __init__(self, root: Path, code: int):
        self.root, self.code = root, code
        self.files = _dir(root, "individuals")
        self.gens = {int(name[:-5]): _canonical(raw) for name, raw in _dir(root, "generations").items()}
        self.result = _canonical((root / "result.json").read_bytes()) if (root / "result.json").exists() else None
        self.error = json.loads((root / "error.json").read_bytes()) if (root / "error.json").exists() else None

    def status(self, k: int) -> list:
        data = _canonical(self.files[f"{k}.status.json"])
        assert set(data) == {"state", "reason_code"}
        return [data["state"], data["reason_code"]]

    def score(self, k: int) -> float | None:
        name = f"{k}.result.json"
        if name not in self.files:
            return None
        modes = json.loads(self.files[name])["modes"]
        return modes[0]["score_kcal_mol"] if modes else None

    def records(self) -> list[dict]:
        return [self.gens[g] for g in sorted(self.gens)]

    def all_bytes(self) -> dict[str, bytes]:
        out = {f"individuals/{k}": v for k, v in self.files.items()}
        out.update({f"generations/{k}": v for k, v in _dir(self.root, "generations").items()})
        for name in ("prepared.json", "result.json"):
            out[name] = (self.root / name).read_bytes()
        return out


def _ga_run(root: Path, manifest: dict, patch: str | None = None) -> Out:
    _stage(root, manifest, "qvina_ga_dock_v1")
    proc = subprocess.run(_argv(patch), cwd=root, capture_output=True, timeout=1200, check=False,
                          env={**ENV, "TMPDIR": str(root)})
    assert len(proc.stderr) < 64_000, proc.stderr[-2000:]
    assert not (root / "qvina_work").exists(), "private engine files are removed"
    assert not list(root.glob("**/*.tmp")), "no torn temporary file is left"
    return Out(root, proc.returncode)


def _single(root: Path, payload: dict) -> bytes:
    _stage(root, payload, "qvina_dock_v1")
    proc = subprocess.run([str(PY), "-I", str(SINGLE)], cwd=root, capture_output=True, timeout=900, check=False,
                          env={**ENV, "TMPDIR": str(root)})
    assert proc.returncode == 0, proc.stderr[-2000:]
    return (root / "result.json").read_bytes()


def _result(stop: str, done: int) -> dict:
    return {"schema": "ligand_ga_worker_output@1", "protocol": "qvina_ga_dock_v1", "job_id": CONTROL["job_id"],
            "attempt_id": CONTROL["attempt_id"], "stop_reason": stop, "generations_done": done}


def _expected_records(expected: dict) -> list[dict]:
    return [{"index": g["index"], "complete": g["complete"],
             "individuals": [{key: e[key] for key in RECORD_KEYS} for e in g["individuals"]]}
            for g in expected["generations"]]


def _oracle_run(ga: dict, scores: dict, *, reusable=(), eligible=None, unscored=None) -> dict:
    return ORACLE.run_ga(IDS, eligible or [True] * len(IDS), BITS, scores, set(reusable), ga, unscored)


def _assert_path(out: Out, expected: dict) -> None:
    """Worker generation records, stop and individual files agree with an oracle path."""
    assert out.code == 0 and out.error is None, out.error
    assert out.result == _result(expected["stop_reason"], expected["generations_done"])
    assert out.records() == _expected_records(expected)
    evaluated = {e["eval_index"]: e for g in expected["generations"] for e in g["individuals"]
                 if e["origin"] != "carried"}
    for k, e in evaluated.items():
        if e["evaluation"] == "reused":
            assert not any(name.startswith(f"{k}.") for name in out.files), "a reused individual gets no file"
            continue
        assert out.files[f"{k}.started"] == b""
        state = out.status(k)[0]
        assert state == e["state"] and out.score(k) == e["score"], (k, e)
    docked = sum(e["evaluation"] == "docked" for e in evaluated.values())
    assert docked == expected["new_dockings_used"]
    assert sum(name.endswith(".status.json") for name in out.files) == docked


def _qvina_under(root: Path) -> list[int]:
    """Live qvina2 processes working under ``root``. Nothing is prefetched: a prefetch runs inside ``process_iter``,
    outside this ``try``, where psutil's ``SystemError`` from a process ending mid-read escaped under load (M28 T2,
    ``test_sequence_ga_worker._engines_under``); here it means the process is gone, as ``psutil.Error`` does
    (M29 T2)."""
    found = []
    for proc in psutil.process_iter():
        try:
            if proc.name() == "qvina2" and str(root) in proc.cwd():
                found.append(proc.pid)
        except (psutil.Error, OSError, SystemError):
            continue
    return found


# ------------------------------------------------------------------ handshake, isolation, pure pieces
def test_handshake_names_the_ga_protocol_and_module_hashes():
    _env_ready()
    out = subprocess.run([str(PY), "-I", str(WORKER), "--handshake"], capture_output=True, text=True, timeout=120,
                         check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    shake = json.loads(out.stdout)
    assert shake["schema"] == "ligand_ga_worker_handshake@1" and shake["protocols"] == ["qvina_ga_dock_v1"]
    assert shake["worker_sha256"] == _sha(WORKER.read_bytes())
    assert shake["row_worker_sha256"] == _sha(SINGLE.read_bytes())
    assert shake["ga_constants_sha256"] == _sha((ROOT / "backend/mw/ligand_ga_constants.py").read_bytes())
    assert shake["versions"] == shake["versions_expected"] and shake["engine"]["hash_match"] is True


def test_server_modules_never_import_the_ga_worker_or_chemistry():
    pattern = re.compile(r"^\s*(from\s+\S*ligand_ga_worker\s+import|import\s+\S*ligand_ga_worker|"
                         r"from\s+\.+jobs\s+import\s+.*ligand_ga_worker)", re.MULTILINE)
    offenders = [str(path) for path in (ROOT / "backend/mw").rglob("*.py") if pattern.search(path.read_text())]
    assert offenders == []
    text = WORKER.read_text()
    chemistry = re.findall(r"^\s*(?:import|from)\s+(rdkit\S*|meeko|MDAnalysis)\b.*$", text, re.MULTILINE)
    assert chemistry == ["rdkit", "rdkit.Chem"], "RDKit only, for the Morgan fingerprints"
    assert not re.search(r"^\s*(import|from)\s+subprocess\b|\bQVINA\b|run_qvina", text, re.MULTILINE), \
        "qvina2 runs only inside docking_worker.dock_row"
    modules = [f"mw.{path.stem}" for path in sorted((ROOT / "backend/mw").glob("ligand_ga_*.py"))]
    assert modules, "the GA server modules exist"
    code = (f"import sys\nfor name in {modules!r}:\n    __import__(name)\n"
            "print(sorted(m for m in ('rdkit', 'meeko', 'MDAnalysis') if m in sys.modules))")
    out = subprocess.run([str(ROOT / ".venv/bin/python"), "-c", code], capture_output=True, text=True, timeout=120,
                         check=False, cwd=ROOT / "backend", env={**ENV, "PYTHONPATH": str(ROOT / "backend")})
    assert out.returncode == 0 and out.stdout.strip() == "[]", out.stderr


def test_fingerprints_tanimoto_rounding_and_reserved_units_match_independent_values():
    _env_ready()
    rows = EXPECTED["pools"]["small"]["candidates"]
    table = EXPECTED["arithmetic"]["reservation"]
    code = LOAD + (
        "from rdkit import DataStructs\n"
        "from rdkit.Chem import rdFingerprintGenerator\n"
        "rows = json.loads(sys.stdin.read())\n"
        "bits = m.fingerprints({r['candidate_id']: r['smiles'] for r in rows['pool']})\n"
        "gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)\n"
        "fps = [gen.GetFingerprint(m.Chem.MolFromSmiles(r['smiles'])) for r in rows['pool']]\n"
        "ids = [r['candidate_id'] for r in rows['pool']]\n"
        "out = {'bits': {c: sorted(b) for c, b in bits.items()},\n"
        "       'float': [[float(m.tanimoto(bits[a], bits[b])) for b in ids] for a in ids],\n"
        "       'rdkit': [list(DataStructs.BulkTanimotoSimilarity(f, fps)) for f in fps],\n"
        "       'round6': [[m.round6(m.tanimoto(bits[a], bits[b])) for b in ids] for a in ids],\n"
        "       'edge': [m.round6(m.Fraction(1, 128)), m.round6(m.Fraction(3, 640)), m.round6(m.Fraction(1)),\n"
        "                m.round6(m.Fraction(0))],\n"
        "       'reserved': [m.reserved_units(r['ga']) for r in rows['reservation']]}\n"
        "print(json.dumps(out))\n")
    payload = json.dumps({"pool": [{"candidate_id": c["id"], "smiles": c["smiles"]} for c in CANDS],
                          "reservation": table})
    proc = subprocess.run([str(PY), "-I", "-c", code], input=payload, capture_output=True, text=True, timeout=300,
                          check=False, env=ENV)
    assert proc.returncode == 0, proc.stderr[-2000:]
    got = json.loads(proc.stdout)
    assert got["bits"] == {row["candidate_id"]: row["morgan_r2_2048_on_bits"] for row in rows}
    assert got["float"] == got["rdkit"] == [row["rdkit_tanimoto_double"] for row in rows]
    assert got["round6"] == [row["tanimoto_round6"] for row in rows]
    # Exact halves (denominators 128 and 640) round up; 3/640 = 0.0046875 is not exact as a double.
    assert got["edge"] == ["0.007813", "0.004688", "1.000000", "0.000000"]
    assert got["reserved"] == [row["reserved_units"] for row in table] == \
        [ligand_ga_inputs.reserved_units(row["ga"]) for row in table]


def test_malformed_manifests_fail_before_any_file(tmp_path):
    cases = {"schema": lambda p: p.update(schema="ligand_ga_worker_input@2"),
             "elite_rule": lambda p: p["ga"].update(population_size=4, elite_count=3),
             "bool_int": lambda p: p["ga"].update(generations=True),
             "fraction_int": lambda p: p["ga"].update(random_fraction=0),
             "too_small_pool": lambda p: p["ga"].update(population_size=12, max_new_dockings=12),
             "duplicate_id": lambda p: p["pool"][1].update(candidate_id=p["pool"][0]["candidate_id"]),
             "index": lambda p: p["pool"][2].update(index=7),
             "ineligible_fields": lambda p: p["pool"][3].update(eligible=False),
             "reuse_other": lambda p: p["pool"][0].update(reuse_result_bytes=p["pool"][1]["reuse_result_bytes"])}
    fake = {cid: json.dumps({"method": "qvina_free_v1", "inputs": {"ligand": {"candidate_id": cid}},
                             "modes": []}).encode() for cid in IDS[:2]}   # shape only; refused before any use
    for name, change in cases.items():
        manifest = _manifest(_ga(seed=1, population_size=4, max_new_dockings=10), reuse=fake)
        change(manifest)
        out = _ga_run(tmp_path / name, manifest)
        assert out.code == 1 and out.result is None and out.error["reason_code"] == "engine_failed", name
        assert out.files == {} and out.gens == {} and not (out.root / "prepared.json").exists(), name


# ------------------------------------------------------------------ selection logic against every oracle vector
STAND_IN = r"""
VECTORS = json.loads(open(sys.argv[1]).read())
class Recording(m.random.Random):
    calls = []
    def sample(self, population, k):
        got = super().sample(population, k)
        Recording.calls.append({"call": "sample", "population": [_id(x) for x in population], "k": k,
                                "result": [_id(x) for x in got]})
        return got
    def choice(self, population):
        got = super().choice(population)
        Recording.calls.append({"call": "choice", "population": [_id(x) for x in population], "result": _id(got)})
        return got
def _id(x):
    return x["candidate_id"] if type(x) is dict else x
m.random.Random = Recording
base = os.getcwd()
for name, vector in VECTORS.items():
    os.chdir(os.path.join(base, name))
    unscored = vector.get("unscored") or {}
    def stand_in(payload, shared, prepared, control, vector=vector, unscored=unscored):
        cid = payload["ligand"]["candidate"]["id"]
        score = vector["scores"][cid]
        if score is None and unscored.get(cid) == "failed":
            return "failed", "engine_failed", None, None
        raw = m.dw.canonical_json({"SYNTHETIC": "selection-logic stand-in, not engine output", "candidate_id": cid,
                                   "modes": [] if score is None else [{"score_kcal_mol": score}]})
        return ("scored", None, raw, score) if score is not None else ("null_result", None, raw, None)
    m._dock = stand_in
    Recording.calls = []
    m.CLOCK.cancelled = False
    code = m.entry([])
    open("rng_calls.json", "w").write(json.dumps({"code": code, "calls": Recording.calls}))
os.chdir(base)
"""


def test_selection_logic_follows_every_oracle_vector_call_by_call(tmp_path):
    """SYNTHETIC stand-in docking (labelled vector scores), real RDKit fingerprints, real receptor preparation."""
    _env_ready()
    for name, vector in VECTORS.items():
        reuse = {cid: json.dumps({"SYNTHETIC": "selection-logic stand-in", "method": "qvina_free_v1",
                                  "inputs": {"ligand": {"candidate_id": cid}},
                                  "modes": [{"score_kcal_mol": vector["scores"][cid]}]}).encode()
                 for cid in vector.get("reusable", [])}
        _stage(tmp_path / name, _manifest(vector["ga"], reuse=reuse, eligible=vector.get("eligible")),
               "qvina_ga_dock_v1")
    (tmp_path / "vectors.json").write_text(json.dumps(VECTORS))
    proc = subprocess.run([str(PY), "-I", "-c", LOAD + STAND_IN, str(tmp_path / "vectors.json")], cwd=tmp_path,
                          capture_output=True, timeout=600, check=False, env={**ENV, "TMPDIR": str(tmp_path)})
    assert proc.returncode == 0, proc.stderr[-3000:]
    for name, vector in VECTORS.items():
        out = Out(tmp_path / name, json.loads((tmp_path / name / "rng_calls.json").read_text())["code"])
        expected = vector["expected"]
        calls = json.loads((tmp_path / name / "rng_calls.json").read_text())["calls"]
        oracle_calls = [{**c, "population": [x["candidate_id"] if type(x) is dict else x for x in c["population"]],
                         "result": ([x["candidate_id"] if type(x) is dict else x for x in c["result"]]
                                    if c["call"] == "sample" else c["result"])} for c in expected["rng_calls"]]
        assert calls == oracle_calls, name
        _assert_path(out, expected)
        # Reused individuals are evaluations (eval_index) without files; reserved_units is the docking cap.
        assert sum(e["evaluation"] == "reused" for g in out.records() for e in g["individuals"]) == \
            expected["reused_count"], name
        assert expected["new_dockings_used"] <= ligand_ga_inputs.reserved_units(vector["ga"]), name
    stops = {vector["expected"]["stop_reason"] for vector in VECTORS.values()}
    assert stops == {"generations_complete", "pool_exhausted", "docking_limit", "no_change"}


# ------------------------------------------------------------------ real engine
@pytest.fixture(scope="module")
def seed7(tmp_path_factory):
    """The oracle vector ``small_observed_seed7`` run for real: ten new dockings (every pool candidate)."""
    root = tmp_path_factory.mktemp("ga_seed7")
    manifest = _manifest(VECTORS["small_observed_seed7"]["ga"])
    out = _ga_run(root / "run", manifest)
    by_id = {}
    for g in out.records():
        for e in g["individuals"]:
            if e["evaluation"] == "docked":
                by_id[e["candidate_id"]] = out.files[f"{e['eval_index']}.result.json"]
    return {"root": root, "manifest": manifest, "out": out, "results": by_id}


def test_real_run_follows_the_oracle_and_each_individual_is_a_standalone_m18_docking(seed7):
    out = seed7["out"]
    expected = VECTORS["small_observed_seed7"]["expected"]
    _assert_path(out, expected)
    assert sorted(seed7["results"]) == sorted(IDS)
    assert {cid: json.loads(raw)["modes"][0]["score_kcal_mol"] for cid, raw in seed7["results"].items()} == OBS_SCORES
    first = expected["generations"][0]["individuals"][0]["candidate_id"]
    reference = _single(seed7["root"] / "single", _payload(seed7["manifest"], first))
    assert out.files["0.result.json"] == reference, "an individual's bytes = the standalone M18 job"
    prepared = _canonical((out.root / "prepared.json").read_bytes())
    assert prepared["box"] == json.loads(reference)["box"] and prepared["engine"] == json.loads(reference)["engine"]
    sims = [e["similarity"] for g in out.records() for e in g["individuals"] if e["origin"] == "similar"]
    assert sims and all(re.fullmatch(r"0\.[0-9]{6}|1\.000000", s) for s in sims)


def test_same_seed_and_inputs_give_byte_identical_outputs(seed7):
    again = _ga_run(seed7["root"] / "again", seed7["manifest"])
    assert again.all_bytes() == seed7["out"].all_bytes()


def test_other_ga_seed_takes_another_path_and_reuses_same_docking_seed_results(seed7, tmp_path):
    """small_observed_seed8 with every candidate's stored result (same docking seed) staged for reuse."""
    vector = VECTORS["small_observed_seed8"]
    out = _ga_run(tmp_path / "seed8", _manifest(vector["ga"], reuse=seed7["results"]))
    expected = _oracle_run(vector["ga"], OBS_SCORES, reusable=IDS)
    assert [[e["candidate_id"] for e in g["individuals"]] for g in expected["generations"]] == \
        [[e["candidate_id"] for e in g["individuals"]] for g in vector["expected"]["generations"]], "same path"
    _assert_path(out, expected)
    assert out.files == {} and expected["reused_count"] == 10 and expected["new_dockings_used"] == 0
    assert out.records() != seed7["out"].records(), "another GA seed, another path"
    assert all(e["evaluation"] in ("reused", None) for g in out.records() for e in g["individuals"])


def test_docking_limit_with_reuse_writes_the_partial_generation(seed7, tmp_path):
    """small_observed_limit5_reuse_two for real: two reused individuals, five new dockings, then docking_limit."""
    vector = VECTORS["small_observed_limit5_reuse_two"]
    reuse = {cid: seed7["results"][cid] for cid in vector["reusable"]}
    out = _ga_run(tmp_path / "limit", _manifest(vector["ga"], reuse=reuse))
    _assert_path(out, vector["expected"])
    assert out.result["stop_reason"] == "docking_limit" and out.gens[3]["complete"] is False
    assert [g["complete"] for g in out.records()] == [True, True, False]
    for g in out.records():
        for e in g["individuals"]:
            if e["evaluation"] == "docked":   # same docking seed and control identity: the same bytes
                assert out.files[f"{e['eval_index']}.result.json"] == seed7["results"][e["candidate_id"]]


def test_pool_exhausted_no_change_and_filter_excluded_on_stored_real_results(seed7, tmp_path):
    exhausted = _ga(seed=5, population_size=4, generations=8, elite_count=0, tournament_size=2, neighbor_count=3,
                    random_fraction=0.25, patience=8, max_new_dockings=40, total_s=600)
    cases = {"exhausted": (exhausted, None)}
    flat = _ga(seed=0, population_size=4, generations=8, elite_count=1, tournament_size=2, neighbor_count=3,
               random_fraction=0.25, patience=1, max_new_dockings=40, total_s=600)
    seed = next(s for s in range(200) if _oracle_run({**flat, "seed": s}, OBS_SCORES, reusable=IDS)["stop_reason"]
                == "no_change")
    cases["no_change"] = ({**flat, "seed": seed}, None)
    mask = VECTORS["synthetic_filter_excluded"]["eligible"]
    cases["filtered"] = (VECTORS["synthetic_filter_excluded"]["ga"], mask)
    stops = {}
    for name, (ga, eligible) in cases.items():
        reuse = {cid: raw for cid, raw in seed7["results"].items() if eligible is None or mask[IDS.index(cid)]}
        out = _ga_run(tmp_path / name, _manifest(ga, reuse=reuse, eligible=eligible))
        expected = _oracle_run(ga, OBS_SCORES, reusable=IDS, eligible=eligible)
        _assert_path(out, expected)
        stops[name] = expected["stop_reason"]
        if eligible is not None:
            picked = {e["candidate_id"] for g in out.records() for e in g["individuals"]}
            assert not picked & {cid for cid, ok in zip(IDS, mask, strict=True) if not ok}
    assert stops == {"exhausted": "pool_exhausted", "no_change": "no_change", "filtered": "pool_exhausted"}
    assert [len(g["individuals"]) for g in Out(tmp_path / "exhausted", 0).records()] == [4, 4, 2]


def test_failed_individuals_are_evaluated_without_retry_and_never_parents(seed7, tmp_path):
    # Per-individual clock shrunk to 0.5 s: every new docking (about 7-12 s here) fails candidate_timeout.
    ga = VECTORS["small_observed_seed7"]["ga"]
    first = [e["candidate_id"] for e in VECTORS["small_observed_seed7"]["expected"]["generations"][0]["individuals"]]
    reusable = first[:2]
    out = _ga_run(tmp_path / "timeout", _manifest(ga, reuse={c: seed7["results"][c] for c in reusable}),
                  patch="m.ROW_LIMIT_S = 0.5")
    scores = {cid: (OBS_SCORES[cid] if cid in reusable else None) for cid in IDS}
    expected = _oracle_run(ga, scores, reusable=reusable, unscored={c: "failed" for c in IDS if c not in reusable})
    _assert_path(out, expected)
    docked = [e["eval_index"] for g in out.records() for e in g["individuals"] if e["evaluation"] == "docked"]
    assert docked and all(out.status(k) == ["failed", "candidate_timeout"] for k in docked)
    assert not any(name.endswith(".result.json") for name in out.files)
    parents = {e["parent_candidate_id"] for g in out.records() for e in g["individuals"] if e["origin"] == "similar"}
    assert parents <= set(reusable)
    assert _qvina_under(out.root) == []
    # M18 refusals are failed individuals with the M18 reason; the run continues.
    cands = [CANDS[0], CANDS[1], {**CANDS[2], "id": "c_torsions", "smiles": "C" * 40},
             {**CANDS[3], "id": "c_fragments", "smiles": "CCO.CC"}]
    one = _ga(seed=3, population_size=4, generations=1, elite_count=0, max_new_dockings=4, total_s=600)
    out = _ga_run(tmp_path / "m18", _manifest(one, cands=cands, reuse={IDS[0]: seed7["results"][IDS[0]],
                                                                      IDS[1]: seed7["results"][IDS[1]]}))
    assert out.code == 0 and out.result == _result("generations_complete", 1)
    entries = {e["candidate_id"]: e for e in out.gens[1]["individuals"]}
    assert {entries[c]["evaluation"] for c in IDS[:2]} == {"reused"}
    assert out.status(entries["c_torsions"]["eval_index"]) == ["failed", "ligand_too_many_torsions"]
    assert out.status(entries["c_fragments"]["eval_index"]) == ["failed", "ligand_multiple_fragments"]


def test_total_clock_stops_during_preparation_before_an_individual_and_during_docking(seed7, tmp_path):
    ga = VECTORS["small_observed_seed7"]["ga"]
    first = [e["candidate_id"] for e in VECTORS["small_observed_seed7"]["expected"]["generations"][0]["individuals"]]
    reuse = {c: seed7["results"][c] for c in first[:2]}
    # (a) already over before the receptor preparation: no file but result.json.
    out = _ga_run(tmp_path / "prep", _manifest(ga, reuse=reuse), patch="m.TOTAL_LIMIT_S = 0.0")
    assert out.code == 0 and out.result == _result("time_exhausted", 0)
    assert out.files == {} and out.gens == {} and not (out.root / "prepared.json").exists()
    # (b) over right after prepared.json: the check before the first individual stops it; generation 1 is empty.
    patch = ("box = m.run_box\n"
             "def late(p, shared):\n"
             "    out = box(p, shared); m.TOTAL_LIMIT_S = time.monotonic() - m.STARTED_AT; return out\n"
             "m.run_box = late")
    out = _ga_run(tmp_path / "before", _manifest(ga, reuse=reuse), patch=patch)
    assert out.result == _result("time_exhausted", 0) and out.files == {}
    assert out.gens == {1: {"index": 1, "complete": False, "individuals": []}}
    # (c) during the first new docking (after two reused individuals): partial generation 1, only <k>.started.
    patch = ("box = m.run_box\n"
             "def late(p, shared):\n"
             "    out = box(p, shared); m.TOTAL_LIMIT_S = time.monotonic() - m.STARTED_AT + 2.0; return out\n"
             "m.run_box = late")
    root = tmp_path / "during"
    out = _ga_run(root, _manifest(ga, reuse=reuse), patch=patch)
    assert out.result == _result("time_exhausted", 0)
    assert out.files == {"2.started": b""}
    assert out.gens[1]["complete"] is False
    assert [(e["candidate_id"], e["evaluation"], e["eval_index"]) for e in out.gens[1]["individuals"]] == \
        [(first[0], "reused", 0), (first[1], "reused", 1)]
    assert _qvina_under(root) == []


def test_output_cap_stops_without_storing_the_result(seed7, tmp_path):
    ga = VECTORS["small_observed_seed7"]["ga"]
    first = [e["candidate_id"] for e in VECTORS["small_observed_seed7"]["expected"]["generations"][0]["individuals"]]
    out = _ga_run(tmp_path / "cap", _manifest(ga, reuse={c: seed7["results"][c] for c in first[:3]}),
                  patch="m.MAX_TOTAL_OUTPUT_BYTES = 1000")
    assert out.code == 0 and out.result == _result("resource_exceeded", 0)
    assert out.files == {"3.started": b""}
    assert [e["evaluation"] for e in out.gens[1]["individuals"]] == ["reused"] * 3 and not out.gens[1]["complete"]


def _held_docking(proc: subprocess.Popen, root: Path, eval_index: int) -> psutil.Process:
    """The qvina2 of new docking ``eval_index``, held (M29 T2). The test used to send SIGTERM once a pass over every
    system process had seen a qvina2; under Stop-hook load such a pass took up to seconds while this docking
    (exhaustiveness 1) is far shorter, so it could end and the run go on before the signal. From
    ``individuals/<eval_index>.started`` the worker's process group (the worker and qvina2) is stopped for each look
    (the worker's own children, ``engine_hold``) and run 10 ms between looks; the first look that sees qvina2 holds it
    for good once it has run its own code. Returns with the group stopped."""
    sign, ended = root / f"individuals/{eval_index}.started", root / f"individuals/{eval_index}.status.json"
    worker = psutil.Process(proc.pid)
    looks = 0
    end = time.monotonic() + 300
    while time.monotonic() < end:
        assert proc.poll() is None, f"worker exited before eval_index {eval_index} ran qvina2"
        if looks or sign.exists():
            looks += 1
            EH.stop_group(proc.pid, worker)
            engine = EH.named_child(proc.pid, "qvina2")
            if engine is not None:
                held = EH.hold_past_exec(engine)
                assert held and not ended.exists(), f"eval_index {eval_index} ended before held ({looks} looks)"
                return engine
            assert not ended.exists(), f"eval_index {eval_index} ended before its qvina2 was seen ({looks} looks)"
            os.killpg(proc.pid, signal.SIGCONT)
        time.sleep(0.01)
    raise AssertionError(f"eval_index {eval_index} never started qvina2")


def test_sigterm_cancels_the_running_docking_and_keeps_the_evaluated_individuals(seed7, tmp_path):
    ga = VECTORS["small_observed_seed7"]["ga"]
    first = [e["candidate_id"] for e in VECTORS["small_observed_seed7"]["expected"]["generations"][0]["individuals"]]
    root = tmp_path / "term"
    _stage(root, _manifest(ga, reuse={first[0]: seed7["results"][first[0]]}), "qvina_ga_dock_v1")
    proc = subprocess.Popen(_argv(None), cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**ENV, "TMPDIR": str(root)}, start_new_session=True)
    held: list[psutil.Process] = []
    try:
        held.append(_held_docking(proc, root, 2))   # the second new docking (eval_index 2) runs qvina2
        os.kill(proc.pid, signal.SIGCONT)            # the worker only: its qvina2 stays held, so only it can end it
        EH.wait_blocked(psutil.Process(proc.pid))
        os.kill(proc.pid, signal.SIGTERM)
        assert proc.wait(timeout=5.0) == 0, "exits within the guardian grace period"
    finally:
        if proc.poll() is None:                      # a failure above leaves no stopped group behind
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    engines = [process.pid for process in held]
    try:
        out = Out(root, 0)
        assert out.result == _result("cancelled", 0)
        assert sorted(out.files) == ["1.result.json", "1.started", "1.status.json", "2.started"]
        assert out.gens[1]["complete"] is False
        assert [(e["evaluation"], e["eval_index"]) for e in out.gens[1]["individuals"]] == [("reused", 0),
                                                                                         ("docked", 1)]
        assert out.files["1.result.json"] == seed7["results"][first[1]]
        assert not (root / "qvina_work").exists()
        assert not any(psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
                       for pid in engines)
    finally:
        for process in held:                         # a held engine the worker left must not stay stopped
            if process.is_running():
                process.kill()


def test_a_finished_docking_survives_a_late_sigterm_and_a_stale_private_directory(seed7, tmp_path):
    """Labeled faults in the worker's own process: a ``qvina_work`` left by an earlier interrupted removal, and a
    SIGTERM sent to itself while the private directory of a finished docking is being removed. The finished docking
    is kept (result, status, listed), the stop is the next check's ``cancelled`` and no private directory is left."""
    ga = VECTORS["small_observed_seed7"]["ga"]
    first = [e["candidate_id"] for e in VECTORS["small_observed_seed7"]["expected"]["generations"][0]["individuals"]]
    patch = ("os.mkdir('qvina_work', 0o700)\n"            # stale directory before the first new docking
             "real = m.shutil.rmtree\n"
             "sent = []\n"
             "def rmtree(path, ignore_errors=False):\n"
             "    if not sent and os.path.isdir(path) and os.listdir(path):\n"   # a docking ran in it
             "        sent.append(1); os.kill(os.getpid(), m.signal.SIGTERM); time.sleep(0.2)\n"
             "    return real(path, ignore_errors=ignore_errors)\n"
             "import types\n"
             "m.shutil = types.SimpleNamespace(rmtree=rmtree)\n")
    out = _ga_run(tmp_path / "late", _manifest(ga, reuse={first[0]: seed7["results"][first[0]]}), patch=patch)
    assert out.code == 0 and out.error is None, out.error
    assert out.result == _result("cancelled", 0)
    assert sorted(out.files) == ["1.result.json", "1.started", "1.status.json"]
    assert out.status(1) == ["scored", None]
    assert out.files["1.result.json"] == seed7["results"][first[1]]
    assert [(e["evaluation"], e["eval_index"]) for e in out.gens[1]["individuals"]] == [("reused", 0), ("docked", 1)]
    assert out.gens[1]["complete"] is False
