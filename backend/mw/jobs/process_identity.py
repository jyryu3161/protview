"""Version-bound raw psutil start identity for owned POSIX processes.

psutil 7.2.2's public Darwin create_time is adjusted by interpreter-local boot
time. Its internal monotonic path is the stable PID-reuse component used here.
"""
from __future__ import annotations

import math
import sys
from typing import Any

import psutil

KIND = "psutil_raw_start_v1"
VERSION = "7.2.2"
PLATFORMS = {"darwin", "linux"}


class IdentityUnavailable(RuntimeError):
    """The pinned raw identity mechanism cannot safely authorize a launch."""


def _positive_finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return value > 0 and math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        # math.isfinite coerces an oversized int to float and may overflow.
        return False


def supported() -> None:
    if sys.platform not in PLATFORMS or psutil.__version__ != VERSION:
        raise IdentityUnavailable("unsupported process identity platform or psutil version")
    try:
        internal = psutil.Process()._proc  # pinned private psutil 7.2.2 API
        method = internal.create_time
        value = method(monotonic=True)
    except (AttributeError, TypeError, psutil.Error, OSError) as exc:
        raise IdentityUnavailable("raw psutil start identity unavailable") from exc
    if not _positive_finite(value):
        raise IdentityUnavailable("invalid raw psutil start identity")


def valid(record: Any) -> bool:
    return (isinstance(record, dict) and set(record) == {"kind", "platform", "psutil_version", "value"} and
            isinstance(record["kind"], str) and isinstance(record["platform"], str) and
            isinstance(record["psutil_version"], str) and record["kind"] == KIND and record["platform"] == sys.platform and
            record["platform"] in PLATFORMS and record["psutil_version"] == VERSION and
            psutil.__version__ == VERSION and _positive_finite(record["value"]))


def capture(pid: int) -> dict[str, str | int | float]:
    supported()
    try:
        value = psutil.Process(pid)._proc.create_time(monotonic=True)
    except (psutil.NoSuchProcess, ProcessLookupError):
        # An exited PID during a fresh cohort scan is absent, not an adapter
        # failure. Callers recheck their anchor and may skip this observation.
        raise
    except (AttributeError, TypeError, psutil.Error, OSError) as exc:
        raise IdentityUnavailable("raw psutil start identity unavailable") from exc
    record = {"kind": KIND, "platform": sys.platform, "psutil_version": VERSION, "value": value}
    if not valid(record):
        raise IdentityUnavailable("invalid raw psutil start identity")
    return record


def matches(pid: int, record: Any) -> bool:
    if not valid(record):
        return False
    try:
        return capture(pid) == record
    except (IdentityUnavailable, psutil.Error, OSError):
        return False
