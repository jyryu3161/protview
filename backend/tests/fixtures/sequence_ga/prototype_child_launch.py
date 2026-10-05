# PROTOTYPE (M23 T1 measurement only; never product code, never imported by mw).
"""Two interpreters in one process group, as spec 8 plans it (T1 (b)).

``standin <attempt-dir> <mode>`` (project ``.venv``; the caller starts it with ``start_new_session=True`` so it is the
session and group leader, like the guardian) launches ``worker`` exactly as ``guardian.py`` launches a docking-env
worker (``[.deps/docking/venv-locked/bin/python, "-I", file]``, the guardian worker environment, stdin closed), samples
the guardian RSS formula (worker + ``children(recursive=True)``) and ends with the real ``guardian.cleanup`` /
``guardian.members`` functions, writing ``standin.json``.

``worker`` (docking env) loads the unmodified ``docking_worker.py`` by file path first (sockets denied), computes the
project interpreter from its own file location (``<repo>/.venv/bin/python``, final symlink NOT resolved), and for each
individual of ``worker_input.json`` runs the modeling child ``[project python, "-I", prototype_sequence_model.py,
"child"]`` with the same environment rules, then prepares that individual's receptor (``receptor_inputs`` +
``receptor_prepared``) and docks with ``dock_row``. Modes: ``complete``; ``cancel_wait`` (the stand-in cancels while
the child models); ``model_timeout`` (the worker's own child timeout kills the child).
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]
PROJECT_PYTHON = REPO / ".venv/bin/python"               # like guardian.DOCKING_PYTHON: the venv link, not resolved
DOCKING_PYTHON = REPO / ".deps/docking/venv-locked/bin/python"
MODEL_PROGRAM = HERE.with_name("prototype_sequence_model.py")
CHILD_OUTPUT_LIMIT = 1024 * 1024


def worker_env(cwd: Path) -> dict[str, str]:
    """The environment ``guardian.py`` gives every worker (and spec 8 gives the modeling child)."""
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "TMPDIR": str(cwd),
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}


def _load_by_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _b64(raw: bytes) -> dict[str, str]:
    return {"b64": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()}


def worker() -> int:
    t0 = time.monotonic()
    dw = _load_by_path(REPO / "backend/mw/jobs/docking_worker.py", "docking_worker_pinned")
    import_s = time.monotonic() - t0
    attempt = Path.cwd()
    spec = json.loads((attempt / "worker_input.json").read_text())
    log = {"import_docking_worker_s": import_s, "project_python": str(PROJECT_PYTHON),
           "project_python_is_symlink": PROJECT_PYTHON.is_symlink(), "individuals": []}
    for key, item in spec["individuals"].items():
        folder = attempt / "individuals" / key
        folder.mkdir(parents=True)
        (folder / "model_input.json").write_text(json.dumps(item["model_input"], sort_keys=True))
        entry = {"key": key}
        started = time.monotonic()
        with (folder / "child.stdout").open("wb") as out, (folder / "child.stderr").open("wb") as err:
            child = subprocess.Popen([str(PROJECT_PYTHON), "-I", str(MODEL_PROGRAM), "child"], cwd=folder,
                                     env=worker_env(attempt), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                     close_fds=True)
            entry["child_pid"] = child.pid
            (attempt / "child.pid").write_text(str(child.pid))
            try:
                child.wait(timeout=spec["model_timeout_s"])
            except subprocess.TimeoutExpired:             # what subprocess.run does on its timeout
                child.kill()
                child.wait()
                entry["child_timed_out"] = True
        entry["child_returncode"] = child.returncode
        entry["child_wall_s"] = time.monotonic() - started
        entry["child_pid_exists_after"] = _exists(child.pid)
        entry["child_stream_bytes"] = sum((folder / n).stat().st_size for n in ("child.stdout", "child.stderr"))
        if child.returncode != 0 or spec["mode"] != "complete":
            entry["error"] = (folder / "error.json").read_text() if (folder / "error.json").exists() else None
            log["individuals"].append(entry)
            continue
        info = json.loads((folder / "t1_child.json").read_text())
        cif, sidecar = (folder / "model.cif").read_bytes(), (folder / "receptor_bonds.json").read_bytes()
        payload = {"schema": "docking_worker_input@1",
                   "receptor": {"handle": info["handle"], "format": "cif", "bytes": _b64(cif),
                                "model_number": item["model_input"]["model_number"],
                                "connectivity": {"kind": "sidecar", "sidecar": _b64(sidecar)}, "instance": None,
                                "source": "mutation_model"},
                   "ligand": {"source": "sdf", "sdf": _b64(base64.b64decode(spec["ligand_sdf_b64"]))},
                   "mode": "free", "box": spec["box"], "parameters": spec["parameters"]}
        dw._validate_payload(payload)
        started = time.monotonic()
        shared = dw.receptor_inputs(payload["receptor"])
        entry["receptor_inputs_s"] = time.monotonic() - started
        started = time.monotonic()
        prepared = dw.receptor_prepared(shared)
        entry["receptor_prepared_s"] = time.monotonic() - started
        work = folder / "qvina_work"
        os.mkdir(work, 0o700)
        started = time.monotonic()
        output = dw.dock_row(payload, work, shared, prepared)
        entry["dock_row_s"] = time.monotonic() - started
        raw = dw.canonical_json(output)
        (attempt / "individuals" / f"{key}.result.json").write_bytes(raw)
        entry.update(result_sha256=hashlib.sha256(raw).hexdigest(), result_bytes=len(raw), child=info,
                     modes=len(output["modes"]))
        log["individuals"].append(entry)
    log["worker_modules"] = sorted(m for m in ("openmm", "pdbfixer", "rdkit", "meeko", "MDAnalysis")
                                   if m in sys.modules)
    (attempt / "worker_log.json").write_text(json.dumps(log, indent=1, sort_keys=True, default=str))
    return 0


def _exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def standin(attempt: Path, mode: str) -> int:
    import psutil

    from mw.jobs import guardian

    own = os.getpid()
    pgid = os.getpgid(own)
    report = {"leader": own == pgid == os.getsid(own), "mode": mode}
    stdout = (attempt / "stdout.log").open("wb")
    stderr = (attempt / "stderr.log").open("wb")
    started = time.monotonic()
    worker_proc = subprocess.Popen([str(DOCKING_PYTHON), "-I", str(HERE), "worker"], stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, close_fds=True, cwd=attempt,
                                   env=worker_env(attempt))
    stdout.close()
    stderr.close()
    samples = max_rss = max_child = 0
    child_seen = child_in_tree = False
    child_since = None
    while worker_proc.poll() is None:
        try:
            process = psutil.Process(worker_proc.pid)
            tree = [m for m in process.children(recursive=True) if m.is_running()]
            rss = process.memory_info().rss + sum(m.memory_info().rss for m in tree)   # guardian.py formula
            max_rss = max(max_rss, rss)
            samples += 1
            pid_file = attempt / "child.pid"
            if pid_file.exists():
                child_pid = int(pid_file.read_text() or 0)
                if psutil.pid_exists(child_pid):
                    child_seen = True
                    child_in_tree = child_in_tree or child_pid in {m.pid for m in tree}
                    try:
                        max_child = max(max_child, psutil.Process(child_pid).memory_info().rss)
                    except psutil.Error:
                        pass
                    child_since = child_since or time.monotonic()
            if mode == "cancel_wait" and child_since is not None and time.monotonic() - child_since > 3.0:
                break
        except psutil.NoSuchProcess:
            pass
        time.sleep(0.025)
    child_pid = int((attempt / "child.pid").read_text()) if (attempt / "child.pid").exists() else None
    before = guardian.members(pgid, own)
    report["members_before_cleanup"] = sorted(m["pid"] for m in before)
    report["child_pid"] = child_pid
    report["worker_pid"] = worker_proc.pid
    clean, known = guardian.cleanup(pgid, own, worker_proc, 2.0)
    report.update(clean=clean, known=sorted(m["pid"] for m in known), members_after=guardian.members(pgid, own),
                  child_exists_after=None if child_pid is None else _exists(child_pid),
                  worker_returncode=worker_proc.returncode, wall_s=time.monotonic() - started, samples=samples,
                  max_tree_rss_bytes=max_rss, max_child_rss_bytes=max_child, child_seen=child_seen,
                  child_in_recursive_children=child_in_tree)
    (attempt / "standin.json").write_text(json.dumps(report, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["worker"]:
        raise SystemExit(worker())
    if sys.argv[1:2] == ["standin"] and len(sys.argv) == 4:
        raise SystemExit(standin(Path(sys.argv[2]), sys.argv[3]))
    raise SystemExit(2)
