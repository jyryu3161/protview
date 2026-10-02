"""Fixed, isolated M19 batch docking worker (spec .dryforge/spec.md 4, 7.2). JSON files only.

The guardian launches this script with the pinned ``.deps/docking/venv-locked`` interpreter, like the M18 worker.
Every row is computed by the M18 worker's own functions (``docking_worker.py`` loaded by file path, never a
package import), so a row's output is byte-identical to a standalone M18 ``qvina_dock_v1`` job on the same staged
row payload and control identity. The receptor block is decoded, checked and turned into PDBQT once per batch
(T1 (a): same bytes as per-row preparation). RDKit, Meeko and MDAnalysis are imported only through that module.
The only other ``mw`` code used is ``mw/docking_batch_constants.py`` (limits, states, reasons), loaded by file path.

Job mode (no arguments, cwd = private attempt directory). ``input.json`` = ``{adapter: "qvina_batch_dock_v1",
input_sha256 (of the structure.json bytes), job_id, attempt_id, ...}``; ``structure.json`` is the server's staged
request manifest (byte entries ``{"b64", "sha256"}`` as in M18)::

    {"schema": "docking_batch_worker_input@1",
     "receptor": <M18 docking_worker_input@1 receptor block>,      # shared by every row
     "parent_sdf": entry,                                         # the batch parent_sdf bytes
     "candidate_set_parent_sha256": hex,                          # ligand_candidate_set@1 parent_sha256
     "mode": "free" | "core_fixed", "box": <M18 box>, "parameters": <M18 parameters>,   # one per batch
     "rows": [{"row_index": int (= list position), "kind": "parent" | "candidate",
               "reuse": bool,                                     # true: a stored result is reused, not run
               "candidate": null | {"id", "smiles", "retained_parent_atoms", "stereo_flag"}}]}  # parent first

Row ``n`` is run as the M18 payload ``{"schema": "docking_worker_input@1", "receptor", "mode", "box",
"parameters", "ligand"}`` with ligand ``{"source": "sdf", "sdf": parent_sdf}`` (parent row) or ``{"source":
"candidate", "parent_sdf", "candidate_set_parent_sha256", "candidate"}`` (candidate row): exactly what
``mw.docking_bundle.stage`` stages for that row's M18 selection. Rows run one at a time in list order; reuse rows
are skipped and get no files.

Durable per-row files (temporary file + fsync + ``os.replace`` + directory fsync) in ``rows/``:
``<n>.started`` (empty) when the row starts; when it ends ``<n>.result.json`` (the M18 ``docking_worker_output@1``
bytes, with this job's ``job_id``/``attempt_id``, scored and null_result rows only) and then ``<n>.status.json``
(canonical ``{"reason_code": str | null, "state": str}``). States: ``scored``, ``null_result``, ``failed`` (M18
closed reason, ``candidate_timeout``), ``cancelled`` (``cancelled`` | ``time_exhausted``) and ``not_run``
(``resource_exceeded``: the total output cap). A row that fails still continues the batch; a cancel, the total
clock or the output cap stops it and later rows get no files. A hard kill leaves ``<n>.started`` alone.
After the receptor preparation and before the first row the worker writes ``prepared.json`` (same durable write,
canonical ``{"box": <the batch box in the row result's shape>, "engine": <engine identity>}``); a box refusal there
(``box_*``) fails the batch before any row like a receptor refusal.

Clocks (``time.monotonic``, inside the worker): ``ROW_LIMIT_S`` covers the whole row (ligand, sampling, qvina,
geometry); ``TOTAL_LIMIT_S`` counts from worker start (receptor preparation included). A deadline or SIGTERM
raises ``_Stop`` (a BaseException, so no M18 ``except Exception`` handler absorbs it) at the next Python bytecode;
``subprocess.run`` then kills the row's qvina2 (its only child) before re-raising. A native RDKit/Meeko call in
progress finishes first. File writes are done with SIGALRM/SIGTERM blocked.

On a normal end (all rows, total clock, output cap, or SIGTERM) the worker writes canonical ``result.json``
``{"attempt_id", "job_id", "protocol", "schema": "docking_batch_worker_output@1", "stop_reason": null |
"cancelled" | "time_exhausted" | "resource_exceeded"}`` and exits 0. A malformed manifest or a receptor/engine
refusal before any row (M18 reasons, e.g. ``receptor_prep_failed``) writes the M18 ``error.json`` envelope, no
row file, and exits 1.
"""
from __future__ import annotations

import time

STARTED_AT = time.monotonic()   # total clock origin: worker start, before the chemistry imports

import importlib.util
import json
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any


def _load_row_worker() -> Any:
    path = Path(__file__).resolve().with_name("docking_worker.py")
    spec = importlib.util.spec_from_file_location("docking_worker_pinned", path)
    if spec is None or spec.loader is None:
        raise ImportError("pinned docking worker unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # denies Python sockets before its chemistry imports
    return module


def _load_batch_constants() -> Any:
    path = Path(__file__).resolve().parents[1] / "docking_batch_constants.py"
    spec = importlib.util.spec_from_file_location("docking_batch_constants_pinned", path)
    if spec is None or spec.loader is None:
        raise ImportError("pinned docking batch constants unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dw = _load_row_worker()
K = dw.K
B = _load_batch_constants()

ADAPTER = B.PROTOCOL
# Spec 4.2 / 4.4 limits (code constants in docking_batch_constants; tests shrink these module copies only).
MAX_ROWS = B.MAX_CANDIDATES + 1                 # + the optional parent row
ROW_LIMIT_S = float(B.PER_CANDIDATE_S)
TOTAL_LIMIT_S = float(B.TOTAL_S)
MAX_TOTAL_OUTPUT_BYTES = B.MAX_OUTPUT_BYTES     # sum of rows/*.result.json
STATE_REASONS = {"scored": (None,), "null_result": (None,), "failed": K.REASONS + B.FAILED_EXTRA_REASONS,
                 "cancelled": B.CANCELLED_REASONS, "not_run": ("resource_exceeded",)}
ROW_DIR = Path("rows")
SIGNALS = {signal.SIGALRM, signal.SIGTERM}


class _Stop(BaseException):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Clock:
    active = False                  # a row (or the receptor preparation) may be interrupted
    cancelled = False
    row_deadline = float("inf")


CLOCK = _Clock()


def _total_deadline() -> float:
    return STARTED_AT + TOTAL_LIMIT_S


def _arm() -> None:
    remaining = min(CLOCK.row_deadline, _total_deadline()) - time.monotonic()
    signal.setitimer(signal.ITIMER_REAL, max(remaining, 0.001))


def _on_alarm(_signum: int, _frame: Any) -> None:
    if not CLOCK.active:
        return
    now = time.monotonic()
    if now >= _total_deadline():
        CLOCK.active = False
        raise _Stop("time_exhausted")
    if now >= CLOCK.row_deadline:
        CLOCK.active = False
        raise _Stop("candidate_timeout")
    _arm()   # early tick


def _on_term(_signum: int, _frame: Any) -> None:
    CLOCK.cancelled = True
    if CLOCK.active:
        CLOCK.active = False
        raise _Stop("cancelled")


def _quiet() -> None:
    """Stop interruptions: block the two signals, disarm the timer, leave the interruptible section."""
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    signal.setitimer(signal.ITIMER_REAL, 0)
    CLOCK.active = False


def _write_durable(path: Path, raw: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _status(index: int, state: str, reason: str | None) -> None:
    if state not in B.ROW_STATES or reason not in STATE_REASONS[state]:
        raise ValueError("row status outside the closed set")
    _write_durable(ROW_DIR / f"{index}.status.json", dw.canonical_json({"state": state, "reason_code": reason}))


# ------------------------------------------------------------------ staged manifest
def _validate_manifest(p: Any) -> None:
    ok = (type(p) is dict and set(p) == {"schema", "receptor", "parent_sdf", "candidate_set_parent_sha256", "mode",
                                         "box", "parameters", "rows"} and
          p["schema"] == "docking_batch_worker_input@1" and type(p["candidate_set_parent_sha256"]) is str and
          dw.SHA_RE.fullmatch(p["candidate_set_parent_sha256"]) is not None and
          type(p["rows"]) is list and 1 <= len(p["rows"]) <= MAX_ROWS)
    rows = p["rows"] if ok else []
    for position, row in enumerate(rows):
        ok = ok and type(row) is dict and set(row) == {"row_index", "kind", "reuse", "candidate"} and \
            type(row["row_index"]) is int and row["row_index"] == position and type(row["reuse"]) is bool and (
                (row["kind"] == "parent" and position == 0 and row["candidate"] is None and p["mode"] == "free") or
                (row["kind"] == "candidate" and type(row["candidate"]) is dict))
    ids = [row["candidate"].get("id") for row in rows if ok and row["kind"] == "candidate"]
    if not ok or len(set(map(str, ids))) != len(ids):
        raise dw._malformed("batch manifest shape")
    for position in range(len(rows)):
        dw._validate_payload(row_payload(p, position))   # every row is a valid M18 payload


def row_payload(p: dict[str, Any], index: int) -> dict[str, Any]:
    """Row ``index`` as the M18 ``docking_worker_input@1`` payload (``docking_bundle.stage`` shape)."""
    row = p["rows"][index]
    ligand = ({"source": "sdf", "sdf": p["parent_sdf"]} if row["kind"] == "parent" else
              {"source": "candidate", "parent_sdf": p["parent_sdf"],
               "candidate_set_parent_sha256": p["candidate_set_parent_sha256"], "candidate": row["candidate"]})
    return {"schema": "docking_worker_input@1", "receptor": p["receptor"], "ligand": ligand, "mode": p["mode"],
            "box": p["box"], "parameters": p["parameters"]}


# ------------------------------------------------------------------ batch
def batch_box(p: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
    """The box every row computes (``dock_row``'s box steps: ``ligand_range`` is the parent SDF heavy-atom range),
    in the row result's shape. A refusal (``box_*``, unreadable parent) fails the batch before any row."""
    req, receptor = p["box"], shared["checked"]
    rows = receptor["rows"]
    if req["source"] == "manual":
        box = {"center_A": [float(x) + 0.0 for x in req["center_A"]], "size_A": [float(x) + 0.0 for x in req["size_A"]]}
    elif req["source"] == "instance_range":
        if not receptor["instance_sites"]:
            raise dw._refuse("box_invalid", "instance_range needs a receptor_instance")
        box = dw.range_box([rows[s]["coordinate_A"] for s in receptor["instance_sites"]
                            if rows[s]["element"].upper() != "H"] or
                           [rows[s]["coordinate_A"] for s in receptor["instance_sites"]], float(req["margin_A"]))
    else:
        parent = dw.read_sdf(dw._entry(p["parent_sdf"]), parent=True)
        box = dw.range_box(dw._heavy_points(parent), float(req["margin_A"]))
    dw.check_box(box, [atom["xyz"] for atom in shared["heavy"]])
    return {"center_A": box["center_A"], "size_A": box["size_A"], "source": req["source"],
            "margin_A": None if req["source"] == "manual" else float(req["margin_A"]) + 0.0}


def _row(p: dict[str, Any], index: int, shared: dict[str, Any], prepared: tuple[str, dict[str, Any]],
         control: dict[str, Any]) -> tuple[str, str | None, bytes | None]:
    """(state, reason, output bytes) of one row; interrupted by ``_Stop`` from the clocks or SIGTERM."""
    workdir = Path("qvina_work")
    os.mkdir(workdir, 0o700)
    try:
        output = dw.dock_row(row_payload(p, index), workdir, shared, prepared)
        raw = dw.canonical_json({**output, "job_id": control["job_id"], "attempt_id": control["attempt_id"]})
        if not 0 < len(raw) <= K.MAX_RESULT_BYTES:   # the M18 result cap: a row failure, never truncated
            return "failed", "resource_exceeded", None
        return ("null_result" if output["counts"]["null_result"] else "scored"), None, raw
    except dw.DockingWorkerError as exc:
        return "failed", exc.reason_code, None
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, MemoryError, RecursionError):
        return "failed", "engine_failed", None   # M18 internal-error mapping
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_batch(p: dict[str, Any], control: dict[str, Any]) -> str | None:
    """Prepare the receptor once, run the rows in order and return the stop reason (None: every row ended)."""
    CLOCK.active = True
    _arm()
    try:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, SIGNALS)   # inside try: a pending signal raises here
        shared = dw.receptor_inputs(p["receptor"])
        prepared = dw.receptor_prepared(shared)
    except _Stop as stop:
        _quiet()
        return "cancelled" if stop.reason == "cancelled" else "time_exhausted"
    finally:
        _quiet()
    # The batch box (one per batch) and engine identity, durable before any row starts: the server builds the
    # summary from them even when no row produces a result or the worker dies later.
    _write_durable(Path("prepared.json"), dw.canonical_json({"box": batch_box(p, shared), "engine": prepared[1]}))
    total = 0
    for index, row in enumerate(p["rows"]):
        if row["reuse"]:
            continue
        if CLOCK.cancelled or signal.SIGTERM in signal.sigpending():
            return "cancelled"
        if time.monotonic() >= _total_deadline():
            return "time_exhausted"
        _write_durable(ROW_DIR / f"{index}.started", b"")
        CLOCK.row_deadline = time.monotonic() + ROW_LIMIT_S
        CLOCK.active = True
        _arm()
        try:
            signal.pthread_sigmask(signal.SIG_UNBLOCK, SIGNALS)
            state, reason, raw = _row(p, index, shared, prepared, control)
            _quiet()
        except _Stop as stop:
            _quiet()
            state, reason, raw = (("failed", "candidate_timeout", None) if stop.reason == "candidate_timeout" else
                                  ("cancelled", stop.reason, None))
        if raw is not None and total + len(raw) > MAX_TOTAL_OUTPUT_BYTES:
            _status(index, "not_run", "resource_exceeded")   # this row's result is not stored
            return "resource_exceeded"
        if raw is not None:
            _write_durable(ROW_DIR / f"{index}.result.json", raw)
            total += len(raw)
        _status(index, state, reason)
        if state == "cancelled":
            return reason
    return None   # every row ended; a later signal does not make the batch partial (spec 4.4)


def run_job() -> dict[str, Any]:
    if dw.versions() != dw.PINNED:
        raise dw._fatal("engine_failed", "pinned Meeko/RDKit/MDAnalysis/gemmi versions unavailable")
    try:
        control = json.loads(dw._read_bounded("input.json", 4096))
        raw = dw._read_bounded("structure.json", dw.MAX_STAGED_BYTES)
        payload = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise dw._malformed("staged JSON unreadable") from exc
    if (type(control) is not dict or control.get("adapter") != ADAPTER or
            type(control.get("input_sha256")) is not str or dw._sha(raw) != control["input_sha256"] or
            any(type(control.get(key)) is not str or not dw.CONTROL_ID_RE.fullmatch(control[key])
                for key in ("job_id", "attempt_id"))):
        raise dw._malformed("control record or staged hash mismatch")
    _validate_manifest(payload)
    os.mkdir(ROW_DIR, 0o700)
    stop = run_batch(payload, control)
    return {"schema": "docking_batch_worker_output@1", "protocol": ADAPTER, "job_id": control["job_id"],
            "attempt_id": control["attempt_id"], "stop_reason": stop}


def handshake() -> dict[str, Any]:
    """The M18 handshake with this protocol and both module hashes; nothing is computed, qvina2 is not run."""
    return {**dw.handshake(), "schema": "docking_batch_worker_handshake@1", "protocols": [ADAPTER],
            "worker_sha256": dw._sha(Path(__file__).read_bytes()),
            "row_worker_sha256": dw._sha(Path(dw.__file__).read_bytes())}


def main(argv: list[str]) -> int:
    if argv == ["--handshake"]:
        sys.stdout.write(json.dumps(handshake(), sort_keys=True, separators=(",", ":")) + "\n")
        return 0
    if argv:
        return 2
    signal.pthread_sigmask(signal.SIG_BLOCK, SIGNALS)
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.signal(signal.SIGTERM, _on_term)
    output = dw.canonical_json(run_job())
    _write_durable(Path("result.json"), output)
    return 0


def entry(argv: list[str]) -> int:
    try:
        return main(argv)
    except dw.DockingWorkerError as exc:
        dw._write_error(exc.envelope())
        return 1
    except (ValueError, TypeError, KeyError, IndexError, OSError, RuntimeError, ImportError,
            MemoryError, RecursionError) as exc:
        dw._write_error({"schema": "docking_worker_error@1", "error_class": "fatal", "reason_code": "engine_failed",
                         "message": f"docking batch worker internal error ({type(exc).__name__})"[:240],
                         "detail": {}})
        return 1


if __name__ == "__main__":
    raise SystemExit(entry(sys.argv[1:]))
