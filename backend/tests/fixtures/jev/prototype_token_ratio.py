"""PROTOTYPE (M24 T1 measurement only): bytes per reported token of the three real M8 Jev calls.

Rebuilds the exact viewer request bodies of the committed M8 live evidence (``docs/qa/m8/raw/live-v1-events.json``
sessions + the prompts in ``live-v1.jsonl``) with the unmodified ``mw.egress.viewer.body_for`` and accepts a rebuild
only when its SHA-256 equals the recorded ``prepared.payload_sha256``. The recorded usage is the provider's own report.
This calibrates the spec 5 science reservation ``min(40000, 4096 + ceil(body_bytes / 2))`` before any real science
call (none is made here). No network, no credential. Prints one JSON report.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

from mw.egress.viewer import body_for
from mw.viewer_intents import projected_state

EVENTS = REPO / "docs/qa/m8/raw/live-v1-events.json"
PROMPTS = REPO / "docs/qa/m8/raw/live-v1.jsonl"


def main() -> int:
    events = json.loads(EVENTS.read_text(encoding="utf-8"))
    prompts = sorted(set(re.findall(r'"prompt":"([^"]+)"', PROMPTS.read_text(encoding="utf-8"))))
    sessions = {event["viewer_session_id"]: event for event in events if event["type"] == "viewer_session_created"}
    prepared = {event.get("viewer_intent_id"): event for event in events
                if event["type"] == "egress" and event.get("stage") == "prepared"}
    received = {event["audit_id"]: event for event in events
                if event["type"] == "egress" and event.get("stage") == "response_received"}
    rows = []
    for intent in (event for event in events if event["type"] == "viewer_intent_requested"):
        audit = prepared[intent["intent_id"]]
        session = sessions[intent["viewer_session_id"]]
        aliases = [None, *[entry["alias"] for entry in session["catalog"]]]
        match = None
        for prompt in prompts:
            for representation in ("cartoon", "ball_and_stick", "surface"):
                for alias in aliases:
                    state = projected_state({**session, "representation": representation, "selected_alias": alias},
                                            prompt)
                    raw = body_for(state)
                    if hashlib.sha256(raw).hexdigest() == audit["payload_sha256"]:
                        match = raw
                        break
                if match:
                    break
            if match:
                break
        usage = received[audit["audit_id"]]["usage"]
        row = {"intent_seq": intent["seq"], "catalog_entries": len(session["catalog"]),
               "body_rebuilt_sha256_equal": match is not None, "usage": usage}
        if match is not None:
            sizes = [len(match)]
        else:   # APPROXIMATE: today's viewer.py wording; the M8-time bytes were not reproduced
            sizes = [len(body_for(projected_state({**session, "representation": representation,
                                                   "selected_alias": alias}, prompt)))
                     for prompt in prompts for representation in ("cartoon", "ball_and_stick", "surface")
                     for alias in (None, session["catalog"][0]["alias"] if session["catalog"] else None)]
        low, high = min(sizes), max(sizes)
        row["body_bytes_range"] = [low, high]
        row["bytes_per_input_token_range"] = [round(low / usage["input_tokens"], 4),
                                              round(high / usage["input_tokens"], 4)]
        row["science_formula_reserve_for_same_bytes"] = [min(40_000, 4_096 + math.ceil(size / 2))
                                                         for size in (low, high)]
        row["reported_external_tokens"] = usage["external_tokens"]
        rows.append(row)
    print(json.dumps({"calls": rows}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
