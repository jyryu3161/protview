"""M19 T3: the isolated batch docking worker (``mw/jobs/docking_batch_worker.py``) in its pinned interpreter.

The worker runs in ``.deps/docking/venv-locked`` as the guardian launches it (``python -I docking_batch_worker.py`` in
a private directory with ``input.json`` + ``structure.json``) with the real ``qvina2``. The clocks and output caps are
shrunk only here, by loading the module by path in that interpreter and assigning its constants before ``entry``
(no request field, no environment variable). The reference for every row is a standalone M18 ``docking_worker.py``
run on the same staged row payload and control identity (the M18 job a single docking would run). The server test
process never imports RDKit, Meeko or MDAnalysis. When either pinned environment is missing these tests fail.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import psutil

from mw import docking_constants as C

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "backend/mw/jobs/docking_batch_worker.py"
SINGLE = ROOT / "backend/mw/jobs/docking_worker.py"
PY = ROOT / ".deps/docking/venv-locked/bin/python"
QVINA = ROOT / ".deps/qvina/env/bin/qvina2"
FIX = Path(__file__).parent / "fixtures/docking"
CHEM = Path(__file__).parent / "fixtures/chemical"
EXPECTED = json.loads((FIX / "expected.json").read_text())
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
REC = (CHEM / "prolif-vina-rec.pdb").read_bytes()
COMPLEX = (FIX / "synthetic-complex-receptor-lig.pdb").read_bytes()
PARENT = (FIX / "public-derived-parent-record0.sdf").read_bytes()
PLANAR = (FIX / "synthetic-ligand-planar-z0.sdf").read_bytes()
ENUM = json.loads((FIX / "m17-enumerate-result-record0-nmethyl.json").read_text())
CANDS = [{key: c[key] for key in ("id", "smiles", "retained_parent_atoms", "stereo_flag")} for c in ENUM["candidates"]]
INSTANCE = EXPECTED["receptor_fixtures"]["instance"]
MANUAL_BOX = {"source": "manual", "center_A": EXPECTED["public_example_box"]["center_A"], "size_A": [22.0, 22.0, 22.0]}
HANDLE = "obj://run_t3/chemical_raw_input/" + "a" * 64
CONTROL = {"nonce": "0" * 32, "job_id": "job_m19t3", "attempt_id": "att_m19t3"}
LOAD = ("import importlib.util, json, os, sys, time\n"
        f"spec = importlib.util.spec_from_file_location('dbw', {str(BATCH)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n")


def _env_ready() -> None:
    assert PY.is_file(), f"pinned docking interpreter missing at {PY} (no skip)"
    assert QVINA.is_file(), f"pinned qvina2 missing at {QVINA} (no skip)"


def _entry(raw: bytes) -> dict:
    return {"b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cand(index: int, **changes) -> dict:
    return {**CANDS[index], **changes}


def _manifest(rows: list, *, mode: str = "free", receptor: bytes = REC, instance: dict | None = None,
              sidecar: bytes | None = None, parent: bytes = PARENT, box: dict | None = None, exhaustiveness: int = 1,
              num_modes: int = 3, conformers: int | None = None) -> dict:
    """``rows``: ``"parent"`` or ``(candidate dict, reuse)`` / candidate dict, in batch order."""
    out = []
    for index, row in enumerate(rows):
        candidate, reuse = row if type(row) is tuple else (row, False)
        out.append({"row_index": index, "kind": "parent" if candidate == "parent" else "candidate", "reuse": reuse,
                    "candidate": None if candidate == "parent" else candidate})
    connectivity = ({"kind": "pdb_conect", "sidecar": None} if sidecar is None else
                    {"kind": "sidecar", "sidecar": _entry(sidecar)})
    return {"schema": "docking_batch_worker_input@1",
            "receptor": {"handle": HANDLE, "format": "pdb", "bytes": _entry(receptor), "model_number": 1,
                         "connectivity": connectivity, "instance": instance},
            "parent_sdf": _entry(parent), "candidate_set_parent_sha256": _sha(parent), "mode": mode,
            "box": box or {"source": "ligand_range", "margin_A": 8.0},
            "parameters": {"seed": 42, "exhaustiveness": exhaustiveness, "num_modes": num_modes,
                           "energy_range": 3.0, "conformers": conformers},
            "rows": out}


def _row_payload(manifest: dict, index: int) -> dict:
    """The M18 staged payload of row ``index``, built test-side from the manifest (docking_bundle.stage shape)."""
    row = manifest["rows"][index]
    ligand = ({"source": "sdf", "sdf": manifest["parent_sdf"]} if row["kind"] == "parent" else
              {"source": "candidate", "parent_sdf": manifest["parent_sdf"],
               "candidate_set_parent_sha256": manifest["candidate_set_parent_sha256"], "candidate": row["candidate"]})
    return {"schema": "docking_worker_input@1", "receptor": manifest["receptor"], "ligand": ligand,
            "mode": manifest["mode"], "box": manifest["box"], "parameters": manifest["parameters"]}


def _stage(root: Path, payload: dict, adapter: str) -> None:
    _env_ready()
    root.mkdir(parents=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    (root / "structure.json").write_bytes(raw)
    (root / "input.json").write_text(json.dumps({**CONTROL, "adapter": adapter, "input_sha256": _sha(raw)}))


def _argv(patch: str | None) -> list[str]:
    if patch is None:
        return [str(PY), "-I", str(BATCH)]
    return [str(PY), "-I", "-c", LOAD + patch + "\nraise SystemExit(m.entry([]))\n"]


def _files(root: Path) -> dict[str, bytes]:
    rows = root / "rows"
    return {} if not rows.is_dir() else {p.name: p.read_bytes() for p in sorted(rows.iterdir())}


def _batch(root: Path, manifest: dict, patch: str | None = None) -> tuple[int, dict, dict | None, dict | None]:
    """(exit code, rows/ files, result.json, error.json) of one batch worker run."""
    _stage(root, manifest, "qvina_batch_dock_v1")
    proc = subprocess.run(_argv(patch), cwd=root, capture_output=True, timeout=900, check=False,
                          env={**ENV, "TMPDIR": str(root)})
    assert len(proc.stderr) < 64_000, proc.stderr[-2000:]
    assert not (root / "qvina_work").exists(), "private engine files are removed"
    assert not list(root.glob("**/*.tmp")), "no torn temporary file is left"
    result = json.loads((root / "result.json").read_bytes()) if (root / "result.json").exists() else None
    error = json.loads((root / "error.json").read_bytes()) if (root / "error.json").exists() else None
    return proc.returncode, _files(root), result, error


def _single(root: Path, payload: dict) -> tuple[bytes | None, str | None]:
    """Standalone M18 worker run: (result.json bytes, error reason)."""
    _stage(root, payload, "qvina_dock_v1")
    proc = subprocess.run([str(PY), "-I", str(SINGLE)], cwd=root, capture_output=True, timeout=900, check=False,
                          env={**ENV, "TMPDIR": str(root)})
    assert proc.returncode in (0, 1), proc.stderr[-2000:]
    result = (root / "result.json").read_bytes() if (root / "result.json").exists() else None
    error = json.loads((root / "error.json").read_bytes())["reason_code"] if (root / "error.json").exists() else None
    return result, error


def _status(files: dict, index: int) -> list:
    data = json.loads(files[f"{index}.status.json"])
    assert files[f"{index}.status.json"] == json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    assert set(data) == {"state", "reason_code"}
    return [data["state"], data["reason_code"]]


def _result_record(stop: str | None) -> dict:
    return {"schema": "docking_batch_worker_output@1", "protocol": "qvina_batch_dock_v1",
            "job_id": CONTROL["job_id"], "attempt_id": CONTROL["attempt_id"], "stop_reason": stop}


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


# ------------------------------------------------------------------ handshake and isolation
def test_handshake_names_the_batch_protocol_and_both_module_hashes():
    _env_ready()
    out = subprocess.run([str(PY), "-I", str(BATCH), "--handshake"], capture_output=True, text=True, timeout=120,
                         check=False, env=ENV)
    assert out.returncode == 0, out.stderr
    shake = json.loads(out.stdout)
    assert shake["schema"] == "docking_batch_worker_handshake@1" and shake["protocols"] == ["qvina_batch_dock_v1"]
    assert shake["worker_sha256"] == _sha(BATCH.read_bytes())
    assert shake["row_worker_sha256"] == _sha(SINGLE.read_bytes())
    assert shake["versions"] == shake["versions_expected"] == {"meeko": "0.8.0", "rdkit": "2026.03.6",
                                                               "MDAnalysis": "2.10.0", "gemmi": "0.7.5"}
    assert shake["engine"]["hash_match"] is True


def test_server_modules_never_import_the_batch_worker_or_chemistry():
    pattern = re.compile(r"^\s*(from\s+\S*docking_batch_worker\s+import|import\s+\S*docking_batch_worker|"
                         r"from\s+\.+jobs\s+import\s+.*docking_batch_worker)", re.MULTILINE)
    offenders = [str(path) for path in (ROOT / "backend/mw").rglob("*.py") if pattern.search(path.read_text())]
    assert offenders == []
    chemistry = re.compile(r"^\s*(import|from)\s+(rdkit|meeko|MDAnalysis)\b", re.MULTILINE)
    assert not chemistry.search(BATCH.read_text()), "the batch worker reaches chemistry only through docking_worker"
    modules = ["mw.docking_constants", "mw.docking_inputs", "mw.docking_bundle"] + [
        f"mw.{path.stem}" for path in sorted((ROOT / "backend/mw").glob("docking_batch_*.py"))]
    code = (f"import sys\nfor name in {modules!r}:\n    __import__(name)\n"
            "print(sorted(m for m in ('rdkit', 'meeko', 'MDAnalysis') if m in sys.modules))")
    out = subprocess.run([str(ROOT / ".venv/bin/python"), "-c", code], capture_output=True, text=True, timeout=120,
                         check=False, cwd=ROOT / "backend", env={**ENV, "PYTHONPATH": str(ROOT / "backend")})
    assert out.returncode == 0 and out.stdout.strip() == "[]", out.stderr


# ------------------------------------------------------------------ shared preparation = standalone M18
def test_free_batch_rows_are_byte_identical_to_standalone_m18_and_reproducible(tmp_path):
    manifest = _manifest(["parent", _cand(0), _cand(1)])
    code, files, result, error = _batch(tmp_path / "batch_a", manifest)
    assert code == 0 and error is None and result == _result_record(None)
    assert sorted(files) == [f"{i}.{kind}" for i in range(3) for kind in ("result.json", "started", "status.json")]
    for index in range(3):
        reference, reason = _single(tmp_path / f"single_{index}", _row_payload(manifest, index))
        assert reason is None and files[f"{index}.result.json"] == reference, f"row {index} differs from M18"
        assert files[f"{index}.started"] == b"" and _status(files, index) == ["scored", None]
    first = json.loads(files["0.result.json"])
    assert first["inputs"]["ligand"]["source"] == "sdf" and first["method"] == "qvina_free_v1"
    assert [json.loads(files[f"{i}.result.json"])["inputs"]["ligand"]["candidate_id"] for i in (1, 2)] == \
        [CANDS[0]["id"], CANDS[1]["id"]]
    assert len({json.dumps(json.loads(files[f"{i}.result.json"])["box"]) for i in range(3)}) == 1, "one box"
    # Same input twice: identical row files and record.
    code, again, result_again, _ = _batch(tmp_path / "batch_b", manifest)
    assert code == 0 and again == files and result_again == result


def test_core_fixed_batch_with_sidecar_and_removed_instance_matches_standalone_m18(tmp_path):
    code = ("import importlib.util, json, sys\n"
            f"spec = importlib.util.spec_from_file_location('dw', {str(SINGLE)!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "raw = sys.stdin.buffer.read()\n"
            f"rows = m.receptor_rows(raw, 'pdb', {HANDLE!r}, 1)\n"
            "pairs = sorted(m._pdb_conect(rows, raw))\n"
            f"print(json.dumps({{'schema': 'receptor_bonds@1', 'complete': True, 'source_handle': {HANDLE!r},\n"
            "                  'bonds': [{'first': rows[a]['ref'], 'second': rows[b]['ref']} for a, b in pairs]}))\n")
    proc = subprocess.run([str(PY), "-I", "-c", code], input=COMPLEX, capture_output=True, timeout=300, check=False,
                          env=ENV)
    assert proc.returncode == 0, proc.stderr[-2000:]
    sidecar = proc.stdout.strip()
    manifest = _manifest([_cand(0), _cand(2)], mode="core_fixed", receptor=COMPLEX, instance=INSTANCE,
                         sidecar=sidecar, box={"source": "instance_range", "margin_A": 8.0}, conformers=5)
    code, files, result, error = _batch(tmp_path / "batch", manifest)
    assert code == 0 and error is None and result == _result_record(None)
    for index in range(2):
        reference, reason = _single(tmp_path / f"single_{index}", _row_payload(manifest, index))
        assert reason is None and files[f"{index}.result.json"] == reference, f"row {index} differs from M18"
        assert _status(files, index) == ["scored", None]
        out = json.loads(files[f"{index}.result.json"])
        assert out["method"] == "qvina_core_fixed_score_only_v1"
        assert out["inputs"]["receptor"]["connectivity"]["sidecar_sha256"] == _sha(sidecar)
        assert out["inputs"]["receptor"]["removed_instance"]["residue"] == INSTANCE


# ------------------------------------------------------------------ row failures continue
def test_failed_rows_keep_the_m18_reason_and_the_batch_continues(tmp_path):
    torsions, fragments = _cand(1, id="c_torsions", smiles="C" * 40), _cand(2, id="c_fragments", smiles="CCO.CC")
    manifest = _manifest(["parent", torsions, fragments, _cand(0)], parent=PLANAR, box=MANUAL_BOX, num_modes=2)
    code, files, result, error = _batch(tmp_path / "free", manifest)
    assert code == 0 and error is None and result == _result_record(None)
    assert [_status(files, i) for i in range(4)] == [["failed", "ligand_not_3d"],
                                                    ["failed", "ligand_too_many_torsions"],
                                                    ["failed", "ligand_multiple_fragments"], ["scored", None]]
    assert sorted(name for name in files if name.endswith(".result.json")) == ["3.result.json"], "failed: status only"
    for index in range(4):
        reference, reason = _single(tmp_path / f"free_{index}", _row_payload(manifest, index))
        assert (reason is None and files[f"{index}.result.json"] == reference) or reason == _status(files, index)[1]
    core = _manifest([_cand(0, id="c_nocore", smiles="CCO"), _cand(1)], mode="core_fixed", conformers=3)
    code, files, result, _error = _batch(tmp_path / "core", core)
    assert code == 0 and result == _result_record(None)
    assert [_status(files, i) for i in range(2)] == [["failed", "core_match_failed"], ["scored", None]]


def test_receptor_refusal_fails_the_job_before_any_row(tmp_path):
    lines = []
    for line in REC.decode().splitlines():
        if line.startswith(("ATOM", "HETATM")) and line[21] == "A" and int(line[22:26]) == 139:
            line = line[:17] + "HSE" + line[20:]
        lines.append(line)
    broken = ("\n".join(lines) + "\n").encode()
    code, files, result, error = _batch(tmp_path / "prep", _manifest([_cand(0), _cand(1)], receptor=broken))
    assert code == 1 and result is None and files == {}
    assert [error["error_class"], error["reason_code"]] == ["input_invalid", "receptor_prep_failed"]
    assert error["reason_code"] in C.REASONS
    bad = _manifest([_cand(0)])
    bad["rows"][0]["reuse"] = "no"
    code, files, result, error = _batch(tmp_path / "malformed", bad)
    assert code == 1 and result is None and files == {} and error["reason_code"] == "engine_failed"


# ------------------------------------------------------------------ clocks and signals
def test_row_clock_fails_only_that_row_and_kills_its_engine(tmp_path):
    torsions, fragments = _cand(1, id="c_torsions", smiles="C" * 40), _cand(2, id="c_fragments", smiles="CCO.CC")
    manifest = _manifest([torsions, _cand(0), fragments], exhaustiveness=8)
    root = tmp_path / "row"
    code, files, result, _error = _batch(root, manifest, patch="m.ROW_LIMIT_S = 2.0")
    assert code == 0 and result == _result_record(None)
    assert [_status(files, i) for i in range(3)] == [["failed", "ligand_too_many_torsions"],
                                                    ["failed", "candidate_timeout"],
                                                    ["failed", "ligand_multiple_fragments"]]
    assert not any(name.endswith(".result.json") for name in files)
    elapsed = (root / "rows/1.status.json").stat().st_mtime - (root / "rows/1.started").stat().st_mtime
    assert 2.0 <= elapsed < 6.0, elapsed   # an exhaustiveness-8 free row takes > 30 s here (T1 (b))
    assert _qvina_under(root) == []


def test_total_clock_cancels_the_running_row_and_leaves_later_rows_without_files(tmp_path):
    torsions = _cand(1, id="c_torsions", smiles="C" * 40)
    manifest = _manifest([torsions, _cand(0), _cand(2)], exhaustiveness=8)
    root = tmp_path / "total"
    patch = "m.TOTAL_LIMIT_S = (time.monotonic() - m.STARTED_AT) + 8.0"
    code, files, result, _error = _batch(root, manifest, patch=patch)
    assert code == 0 and result == _result_record("time_exhausted")
    assert sorted(files) == ["0.started", "0.status.json", "1.started", "1.status.json"]
    assert [_status(files, i) for i in range(2)] == [["failed", "ligand_too_many_torsions"],
                                                    ["cancelled", "time_exhausted"]]
    assert _qvina_under(root) == []


def _start(root: Path, manifest: dict) -> tuple[subprocess.Popen, list[int]]:
    """Start the real entry point in its own session; return once row 0 runs qvina2 (its pids)."""
    _stage(root, manifest, "qvina_batch_dock_v1")
    proc = subprocess.Popen(_argv(None), cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**ENV, "TMPDIR": str(root)}, start_new_session=True)
    end = time.monotonic() + 300
    while time.monotonic() < end:
        engines = [child.pid for child in psutil.Process(proc.pid).children(recursive=True)
                   if child.name() == "qvina2"]
        if engines and (root / "rows/0.started").exists():
            return proc, engines
        assert proc.poll() is None, "worker exited before its first engine run"
        time.sleep(0.05)
    proc.kill()
    raise AssertionError("row 0 never started qvina2")


def test_sigterm_kills_the_engine_writes_the_row_cancelled_and_exits_cleanly(tmp_path):
    root = tmp_path / "term"
    proc, engines = _start(root, _manifest([_cand(0), _cand(1)], exhaustiveness=8))
    os.kill(proc.pid, signal.SIGTERM)   # the worker only: it must stop its own qvina2
    assert proc.wait(timeout=2.0) == 0, "exits within the guardian grace period"
    files = _files(root)
    assert sorted(files) == ["0.started", "0.status.json"] and _status(files, 0) == ["cancelled", "cancelled"]
    assert json.loads((root / "result.json").read_bytes()) == _result_record("cancelled")
    assert not (root / "qvina_work").exists()
    assert not any(psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE for pid in engines)


def test_hard_kill_leaves_only_the_started_marker(tmp_path):
    root = tmp_path / "kill"
    proc, engines = _start(root, _manifest([_cand(0), _cand(1)], exhaustiveness=8))
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    end = time.monotonic() + 5
    while time.monotonic() < end and any(psutil.pid_exists(pid) for pid in engines):
        time.sleep(0.05)
    assert _files(root) == {"0.started": b""}
    assert not (root / "result.json").exists() and not (root / "error.json").exists()


# ------------------------------------------------------------------ reuse rows and output caps
def test_reuse_rows_are_skipped_and_the_output_caps_stop_or_fail_rows(tmp_path):
    rows = [(_cand(0), True), _cand(1), _cand(2)]
    manifest = _manifest(rows, mode="core_fixed", conformers=2)
    code, files, result, _error = _batch(tmp_path / "base", manifest)
    assert code == 0 and result == _result_record(None)
    assert sorted(files) == [f"{i}.{kind}" for i in (1, 2) for kind in ("result.json", "started", "status.json")]
    size = len(files["1.result.json"])
    # Total cap: row 1 fits, row 2 would pass the cap -> not stored, not_run/resource_exceeded, the batch stops.
    code, capped, result, _error = _batch(tmp_path / "total", manifest, patch=f"m.MAX_TOTAL_OUTPUT_BYTES = {size + 1}")
    assert code == 0 and result == _result_record("resource_exceeded")
    assert capped["1.result.json"] == files["1.result.json"] and "2.result.json" not in capped
    assert _status(capped, 1) == ["scored", None] and _status(capped, 2) == ["not_run", "resource_exceeded"]
    # Per-row M18 cap (4 MiB): that row fails resource_exceeded and the batch continues.
    code, failed, result, _error = _batch(tmp_path / "row", manifest, patch="m.K.MAX_RESULT_BYTES = 1000")
    assert code == 0 and result == _result_record(None)
    assert [_status(failed, i) for i in (1, 2)] == [["failed", "resource_exceeded"]] * 2
    assert not any(name.endswith(".result.json") for name in failed)
