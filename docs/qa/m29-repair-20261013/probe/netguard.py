# PROTOTYPE (M29 T1 probe helper only; never product code, never imported by mw).
"""Refuse every non-loopback socket connect in this process and count the attempts.

Imported first by the T1 probe scripts that run engines (PDBFixer has URL/CCD download paths that must stay unused).
"""
from __future__ import annotations

import socket

ATTEMPTS: list[str] = []
_ORIGINAL = socket.socket.connect
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _guarded(self, address):  # noqa: ANN001
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host in _LOOPBACK:
        return _ORIGINAL(self, address)
    ATTEMPTS.append(str(host))
    raise OSError("non-loopback connect refused by the M29 T1 probe")


socket.socket.connect = _guarded


def summary() -> str:
    return f"non_loopback_connect_attempts={len(ATTEMPTS)}"
