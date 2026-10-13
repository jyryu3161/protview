"""Test support (M29 T2): hold a real worker's running engine step so a test can act while the step cannot finish.

Measured on this macOS machine while the Stop hook's eighteen pytest groups ran at once
(``docs/qa/m29-repair-20261013/t2-flaky-tests.md``):

- A SIGSTOP sent to a process group can leave a child that the leader was just forking, or that was still in
  ``exec``, running: psutil reports the leader stopped as soon as the signal is posted while its thread can still be
  on a CPU, and in 800-stop runs some group members were running 50 ms after the stop, some even after every member
  had been seen stopped once.
- One psutil pass over every system process (``Process.children``) took 0.4 s (median) to 8 s there, so a qvina2 run
  (about 0.9 s) that escaped the stop finished while the test was still looking for it.

So a look here lists only the worker's direct children (macOS libproc ``proc_listchildpids``: one system call), and a
step counts as held only once it is stopped, no thread of it is on a CPU and its CPU time stays the same over 20 ms.
A process is blocked once every thread waits (libproc thread run state): macOS reports a blocked process as running,
and a CPU time that stays the same can also mean a process the scheduler has not run yet. Elsewhere psutil's status
gives the same facts.
"""
from __future__ import annotations

import ctypes
import os
import signal
import sys
import threading
import time
from pathlib import Path

import psutil


class _ThreadInfo(ctypes.Structure):
    """``struct proc_threadinfo`` of <sys/proc_info.h>."""
    _fields_ = [("pth_user_time", ctypes.c_uint64), ("pth_system_time", ctypes.c_uint64),
                ("pth_cpu_usage", ctypes.c_int32), ("pth_policy", ctypes.c_int32),
                ("pth_run_state", ctypes.c_int32), ("pth_flags", ctypes.c_int32),
                ("pth_sleep_time", ctypes.c_int32), ("pth_curpri", ctypes.c_int32),
                ("pth_priority", ctypes.c_int32), ("pth_maxpriority", ctypes.c_int32),
                ("pth_name", ctypes.c_char * 64)]


PROC_PIDLISTTHREADS, PROC_PIDTHREADINFO = 6, 5
TH_STATE_RUNNING, TH_STATE_WAITING = 1, 3
if sys.platform == "darwin":
    _LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    _LIBPROC.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    _LIBPROC.proc_pidinfo.restype = ctypes.c_int
    _LIBPROC.proc_listchildpids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    _LIBPROC.proc_listchildpids.restype = ctypes.c_int
else:
    _LIBPROC = None


def child_pids(pid: int) -> list[int]:
    """The direct children of ``pid`` (in one system call on macOS)."""
    if _LIBPROC is None:
        return [child.pid for child in psutil.Process(pid).children()]
    buffer = (ctypes.c_int * 4096)()
    count = _LIBPROC.proc_listchildpids(pid, buffer, ctypes.sizeof(buffer))
    return [value for value in buffer[:max(count, 0)] if value > 0]


def _run_states(pid: int) -> list[int] | None:
    """The run state of every thread of ``pid`` (macOS), or None when it cannot be read (the process ended)."""
    handles = (ctypes.c_uint64 * 1024)()
    size = _LIBPROC.proc_pidinfo(pid, PROC_PIDLISTTHREADS, 0, handles, ctypes.sizeof(handles))
    if size <= 0:
        return None
    states = []
    info = _ThreadInfo()
    for handle in handles[:size // ctypes.sizeof(ctypes.c_uint64)]:
        if _LIBPROC.proc_pidinfo(pid, PROC_PIDTHREADINFO, handle, ctypes.byref(info),
                                 ctypes.sizeof(info)) != ctypes.sizeof(info):
            return None
        states.append(info.pth_run_state)
    return states


def on_cpu(process: psutil.Process) -> bool:
    """A thread of ``process`` runs or waits to run."""
    if _LIBPROC is None:
        return process.status() == psutil.STATUS_RUNNING
    states = _run_states(process.pid)
    return states is None or TH_STATE_RUNNING in states


def all_waiting(process: psutil.Process) -> bool:
    """Every thread of ``process`` waits (blocked in the kernel); False when stopped or runnable."""
    if process.status() == psutil.STATUS_STOPPED:
        return False
    if _LIBPROC is None:
        return process.status() == psutil.STATUS_SLEEPING
    states = _run_states(process.pid)
    return bool(states) and all(state == TH_STATE_WAITING for state in states)


def cpu(process: psutil.Process) -> list[float] | None:
    """[user, system] CPU seconds for diagnostics; None when the process is gone."""
    try:
        times = process.cpu_times()
        return [round(times.user, 4), round(times.system, 4)]
    except (psutil.Error, SystemError):
        return None


def hold(process: psutil.Process, timeout: float = 10.0) -> bool:
    """Stop ``process`` for good: SIGSTOP until it is reported stopped, no thread of it is on a CPU and its CPU time is
    the same 20 ms later (a stop lost in ``exec`` shows as a moving CPU time and is sent again). False when it has
    ended."""
    end = time.monotonic() + timeout
    try:
        while True:
            process.suspend()
            state = process.status()
            if state == psutil.STATUS_ZOMBIE:
                return False
            before = process.cpu_times()[:2]
            time.sleep(0.02)
            if (process.status() == psutil.STATUS_STOPPED and not on_cpu(process) and
                    process.cpu_times()[:2] == before):
                return True
            assert time.monotonic() < end, f"pid {process.pid} did not stay stopped"
    except psutil.NoSuchProcess:
        return False


def hold_past_exec(process: psutil.Process, timeout: float = 10.0) -> bool:
    """Hold ``process`` once it has run its own code (user CPU time above 0, so its ``exec`` is over and the parent's
    ``Popen`` no longer waits on it): while it has not, it alone is let run for 1 ms (its parent stays stopped).
    False when it has ended."""
    end = time.monotonic() + timeout
    while hold(process):
        if process.cpu_times().user > 0:
            return True
        assert time.monotonic() < end, f"pid {process.pid} never ran its own code"
        process.resume()
        time.sleep(0.001)
    return False


def wait_blocked(process: psutil.Process, timeout: float = 60.0) -> None:
    """Wait until the resumed ``process`` is blocked: every thread waits and its CPU time is the same over three looks
    50 ms apart."""
    end = time.monotonic() + timeout
    seen: list[tuple[bool, tuple]] = []
    while time.monotonic() < end:
        seen = [*seen[-2:], (all_waiting(process), tuple(process.cpu_times()[:2]))]
        if len(seen) == 3 and all(waiting for waiting, _ in seen) and seen[0][1] == seen[2][1]:
            return
        time.sleep(0.05)
    raise AssertionError(f"pid {process.pid} did not block")


def stop_group(pgid: int, *members: psutil.Process) -> None:
    """SIGSTOP the group and wait until each named member is reported stopped (a member that ended fails)."""
    os.killpg(pgid, signal.SIGSTOP)
    end = time.monotonic() + 10
    for member in members:
        while member.status() != psutil.STATUS_STOPPED:
            assert member.status() != psutil.STATUS_ZOMBIE, f"pid {member.pid} ended"
            assert time.monotonic() < end, f"pid {member.pid} did not stop"
            time.sleep(0.001)


def named_child(pid: int, name: str) -> psutil.Process | None:
    """The first live direct child of ``pid`` whose process name is ``name`` (its ``exec`` has begun)."""
    for child_pid in child_pids(pid):
        try:
            child = psutil.Process(child_pid)
            if child.name() == name and child.status() != psutil.STATUS_ZOMBIE:
                return child
        except (psutil.Error, SystemError):     # it ended while read (psutil's proc_* race: SystemError)
            continue
    return None


def hold_job_engine(worker_pid: int, name: str, *, start: Path | None = None, ended: Path | None = None,
                    gap_s: float = 0.002, timeout_s: float = 300.0) -> tuple[psutil.Process, int]:
    """(engine, looks): the ``name`` child of a worker that the job guardian runs, held stopped.

    The guardian leads the process group (guardian, worker, engine). Once ``start`` exists (at once when None) the
    group is stopped for each look and run ``gap_s`` between looks; the first look that sees the engine holds it for
    good (``hold_past_exec``); then the guardian and the worker go on, the worker waiting on the held engine, so the
    step cannot end before whatever the test does next (a cancel, a fault) reaches it. ``ended``, a file the worker
    writes once the step is over, must not exist when the engine is held. A failure leaves no stopped process."""
    end = time.monotonic() + timeout_s
    while start is not None and not start.exists():
        assert time.monotonic() < end, f"{start.name} never appeared"
        time.sleep(0.02)
    pgid = os.getpgid(worker_pid)
    guardian, worker = psutil.Process(pgid), psutil.Process(worker_pid)
    looks = 0
    while True:
        looks += 1
        try:
            stop_group(pgid, guardian, worker)
            engine = named_child(worker_pid, name)
            held = engine is not None and hold_past_exec(engine)
            assert ended is None or not ended.exists(), f"{ended.name} exists before {name} was held ({looks} looks)"
            assert engine is None or held, f"{name} ended before it was held ({looks} looks)"
        except BaseException:
            os.killpg(pgid, signal.SIGCONT)
            raise
        if held:
            guardian.resume()
            worker.resume()
            return engine, looks
        os.killpg(pgid, signal.SIGCONT)
        assert time.monotonic() < end, f"no {name} process appeared ({looks} looks)"
        time.sleep(gap_s)


def _gone(process: psutil.Process) -> bool:
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def hold_then_cancel(patch, name: str, start: str, ended: str, held: list) -> None:
    """Install, with ``patch`` (a pytest MonkeyPatch), two internal test hooks on ``mw.jobs.queue`` for the one queue
    job that then runs: a cancel that reaches the step's running engine, in a fixed order.

    On STARTED a thread (1) holds the worker's ``name`` engine from ``<attempt>/<start>`` on (``hold_job_engine``;
    ``<attempt>/<ended>`` must not exist yet) and waits until the worker blocks on it, (2) holds the guardian, (3)
    requests the cancel through the queue and waits until the queue has sent the guardian STOP (the ``_send``
    wrapper), (4) sends the worker the SIGTERM the guardian sends on STOP and waits until the worker has ended its
    engine, (5) resumes the guardian, which then stops the group as usual. What it held, or why it could not, goes to
    ``held`` for the test to check.

    Why (M29 T2): a short step (a qvina2 run of about a second) used to end before the cancel reached it, because
    under Stop-hook load the guardian lists every system process for each memory sample and again before it signals.
    With the engine held the step cannot end; but the guardian signals the group in pid order, so after a pid wrap the
    held engine can get SIGTERM before the worker, and the worker then records the engine's death (``engine_failed``)
    instead of the cancel (seen once: a product race, recorded in docs/qa/m29-repair-20261013/t2-flaky-tests.md).
    Here the worker gets its SIGTERM first, as when its pid is the lower one."""
    from mw.jobs import queue as queue_module

    stopped = threading.Event()
    original_send, original_record = queue_module._send, queue_module.JobQueue._record_control

    def send(sock, value):
        original_send(sock, value)
        if value.get("kind") == "STOP":
            stopped.set()

    def record(self, message, job_id, attempt_id, nonce):
        done = original_record(self, message, job_id, attempt_id, nonce)
        if message and message.get("kind") == "STARTED":
            attempt = self.run.run_dir / "jobs" / job_id / attempt_id
            worker_pid = message["pid"]

            def watch() -> None:
                guardian = None
                try:
                    engine, looks = hold_job_engine(worker_pid, name, start=attempt / start, ended=attempt / ended)
                    wait_blocked(psutil.Process(worker_pid))
                    guardian = psutil.Process(os.getpgid(worker_pid))
                    assert hold(guardian), "the guardian ended before the cancel"
                    self.request_cancel(job_id)
                    assert stopped.wait(120), "the queue never sent the guardian STOP"
                    os.kill(worker_pid, signal.SIGTERM)
                    end = time.monotonic() + 60
                    while not _gone(engine):
                        assert time.monotonic() < end, f"the worker did not end its {name}"
                        time.sleep(0.01)
                    held.append({"pid": engine.pid, "looks": looks})
                except (AssertionError, OSError, psutil.Error) as exc:
                    held.append({"error": f"{type(exc).__name__}: {exc}"})
                    self.request_cancel(job_id)
                finally:
                    if guardian is not None:
                        guardian.resume()
            threading.Thread(target=watch, daemon=True).start()
        return done

    patch.setattr(queue_module, "_send", send)
    patch.setattr(queue_module.JobQueue, "_record_control", record)
