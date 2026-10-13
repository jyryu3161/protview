#!/usr/bin/env python3
"""Export the M29 product constants the acceptance compares with the spec text (``m29_fixed_sentences@1`` JSON).

Run only as a subprocess of ``scripts/m29_offscreen_acceptance.py`` (and its unit test) with
``PYTHONPATH=<code root>/backend``: the runner never imports ``mw`` itself. This script imports one dependency-free
module, ``mw.structure_repair_constants``, reads its fixed sentences RP1-RP6, SO1-SO3, JW1 and closed sets, and calls no
tool, route or store.

Usage: PYTHONPATH=backend .venv/bin/python scripts/m29_export_fixed_sentences.py --out <file.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

NAMES = ("RP1", "RP2", "RP3", "RP4", "RP5", "RP6", "SO1", "SO2", "SO3", "JW1")


def export() -> dict:
    # the one product module this subprocess reads
    from mw import structure_repair_constants as K

    sentences = {name: getattr(K, name) for name in NAMES}
    body = {"schema": "m29_fixed_sentences@1", "sentences": sentences,
            "repairClasses": list(K.REPAIR_CLASSES), "refusalReasons": list(K.REFUSAL_REASONS),
            "failureReasons": list(K.FAILURE_REASON_CODES), "reportStatementIds": list(K.REPORT_STATEMENT_IDS),
            "originStatementIds": list(K.ORIGIN_STATEMENT_IDS), "refusedCode": K.REPAIRED_NOT_ACCEPTED,
            "refusedMessage": K.REPAIRED_NOT_ACCEPTED_MESSAGE}
    body["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, help="the JSON file to write")
    args = parser.parse_args(argv)
    Path(args.out).write_text(json.dumps(export(), indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
