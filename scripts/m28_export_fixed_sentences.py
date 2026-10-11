#!/usr/bin/env python3
"""Export the product's fixed sentences and report field rules as JSON (M28, .dryforge/spec.md §4.4 X4, §7 item 5).

Run as a SUBPROCESS with ``PYTHONPATH=<code root>/backend``: this is the only M28 script that imports ``mw`` (it reads
module constants and never calls a tool, a route or the store). The M28 runner and the trace audit never import ``mw``;
they read the JSON this script writes.

Output ``m28_fixed_sentences@1``:
  sentences   [{id, text}]  fixed sentences of the product (limitations, statements, screen notes, labels…): the
              constants named in T1 preflight (k) and the fixed question instructions of M24 / M25
              (``jev_constants.INSTRUCTIONS``, ``jev_loop_constants.INSTRUCTIONS``: the request body shows them) plus
              every module-level constant of the report / constants modules whose name says it is fixed wording
              (LIMITATION, STATEMENT, NOTE, WARNING, SCOPE, TERMS, LABEL), flattened.
  inline      [{id, text}]  string literals of the six older report paths (inspection, interface SASA, OpenMM,
              comparison, chemical, pocket) and of the M11 report renderer that carry an X4 core forbidden word inside
              a negation sentence (T1 (k): they are inline literals, not constants). Exact-line exemptions only.
  phrases     [{id, text}]  labels written inside a line (the qvina score labels): removed before the X4 check.
  reportRules {analysis_type: {module, renderVersion, evidenceKinds, fields: {kind: regex}, referenceNote,
              modelResponseNote}}  the product's field rules per evidence kind (check 4 of the trace audit).
  sha256      SHA-256 of the canonical JSON of everything above.

Usage: PYTHONPATH=backend .venv/bin/python scripts/m28_export_fixed_sentences.py [--out <file>]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import m28_common as c  # no mw: the X4 word list

# T1 preflight (k): the fixed-sentence constants of every report family (module → attribute names).
NAMED = {
    "pocket_reports": ("EVIDENCE_STATEMENT", "DRUGGABILITY_WARNING", "DISPLAY_CENTER_NOTE"),
    "pocket_output": ("LIMITATIONS",),
    "numbering_reports": ("REFERENCE_NOTE", "KLIFS_TERMS", "REFERENCE_STATEMENT", "LEGACY_REPORT_LIMITATIONS",
                          "SNAPSHOT_SCOPE"),
    "site_annotation": ("LIMITATIONS",),
    "ligand_constants": ("LIMITATIONS",),
    "docking_constants": ("LIMITATIONS", "SCORE_LABEL", "SCORE_COLUMN_LABEL"),
    "docking_batch_constants": ("BATCH_STATEMENTS",),
    "mutation_constants": ("LIMITATIONS", "LIMITATIONS_V2", "LIMITATION_3_CHECKED", "LIMITATION_3_NOT_CHECKED"),
    "mutation_model_constants": ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "LIMITATION_ORDER"),
    "ligand_ga_constants": ("STATEMENTS",),
    "sequence_ga_constants": ("STATEMENTS", "SCORE_LABEL"),
    "jev_constants": ("STATEMENTS", "J6_BY_CATALYTIC_STATUS", "SCREEN_NOTES", "INSTRUCTIONS"),
    "jev_loop_constants": ("STATEMENTS", "SCREEN_NOTES", "INSTRUCTIONS"),
    "reaction_knowledge_constants": ("STATEMENTS", "LIMITATIONS", "SCREEN_NOTES"),
    "precedent_constants": ("STATEMENTS", "LIMITATIONS", "SCREEN_NOTES"),
}
# Report modules (field rules and their own fixed wording).
REPORT_MODULES = ("numbering_reports", "site_annotation_reports", "ligand_reports", "docking_reports",
                  "docking_batch_reports", "ligand_ga_reports", "sequence_ga_reports", "mutation_reports",
                  "mutation_model_reports", "jev_reports", "jev_loop_reports", "reaction_knowledge_reports",
                  "kinase_precedents_reports", "pocket_reports", "method_reports", "openmm_reports",
                  "comparison_reports", "chemical_reports", "reports")
WORDING_NAME = re.compile(r"(?:LIMITATION|STATEMENT|NOTE|WARNING|SCOPE|TERMS|LABEL)")
# The inline literals of the six older report paths (T1 (k)) and of the M11 report renderer (its native-assignment
# sentence, T9).
INLINE_FILES = ("reports.py", "method_reports.py", "tools/sasa.py", "openmm_reports.py", "tools/comparison.py",
                "chemical_bundle.py", "chemical_reports.py", "pocket_reports.py")
PHRASES = (("docking_constants", "SCORE_LABEL"), ("docking_constants", "SCORE_COLUMN_LABEL"),
           ("sequence_ga_constants", "SCORE_LABEL"))


def flatten(value: object, key: str) -> list[tuple[str, str]]:
    """(id, text) for every string inside a constant (str, or nested tuple / list / dict / frozenset of them)."""
    if isinstance(value, str):
        return [(key, value)] if value.strip() else []
    if isinstance(value, dict):
        return [item for name, inner in value.items() for item in flatten(inner, f"{key}[{name}]")]
    if isinstance(value, (list, tuple)):
        return [item for index, inner in enumerate(value) for item in flatten(inner, f"{key}[{index}]")]
    if isinstance(value, (set, frozenset)):
        return [item for index, inner in enumerate(sorted(v for v in value if isinstance(v, str)))
                for item in flatten(inner, f"{key}[{index}]")]
    return []


def sentences() -> list[dict]:
    found: dict[str, str] = {}
    for module, names in NAMED.items():
        loaded = importlib.import_module(f"mw.{module}")
        for name in names:
            for key, text in flatten(getattr(loaded, name), f"mw.{module}.{name}"):
                found.setdefault(key, text)
    for module in {*NAMED, *REPORT_MODULES}:
        loaded = importlib.import_module(f"mw.{module}")
        for name in sorted(vars(loaded)):
            if name.isupper() and WORDING_NAME.search(name):
                for key, text in flatten(getattr(loaded, name), f"mw.{module}.{name}"):
                    found.setdefault(key, text)
    return [{"id": key, "text": text} for key, text in sorted(found.items())]


def inline(backend: Path) -> list[dict]:
    out = []
    for rel in INLINE_FILES:
        tree = ast.parse((backend / "mw" / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and " " in node.value
                    and c.CORE_FORBIDDEN.search(node.value)):
                out.append({"id": f"mw/{rel}:{node.lineno}", "text": node.value})
    return sorted(out, key=lambda item: item["id"])


def pattern_of(value: object) -> str | None:
    if isinstance(value, re.Pattern):
        return value.pattern
    if isinstance(value, (set, frozenset, tuple, list)):
        return "|".join(re.escape(item) for item in sorted(value))
    if isinstance(value, str):
        return re.escape(value)
    return None


def report_rules() -> dict:
    """The product's field rules per evidence kind: the module's COMPUTED_FIELDS / REFERENCE_FIELDS /
    MODEL_RESPONSE_FIELDS when present, else the union of its statement rules of that kind."""
    rules = {}
    for module in REPORT_MODULES:
        loaded = importlib.import_module(f"mw.{module}")
        kinds = getattr(loaded, "EVIDENCE_KINDS", None)
        analysis = getattr(loaded, "ANALYSIS_TYPE", None)
        if not kinds or not analysis:
            continue
        constants = {"computed": "COMPUTED_FIELDS", "reference_value": "REFERENCE_FIELDS",
                     "model_response": "MODEL_RESPONSE_FIELDS"}
        fields = {}
        statements = getattr(loaded, "STATEMENTS", {}) or {}
        for kind in kinds:
            pattern = pattern_of(getattr(loaded, constants[kind], None))
            if pattern is None:
                parts = []
                for rule in statements.values():
                    if isinstance(rule, re.Pattern) and kind == "computed" and tuple(kinds) == ("computed",):
                        parts.append(rule.pattern)
                    elif isinstance(rule, tuple) and rule and rule[0] == kind and isinstance(rule[1], re.Pattern):
                        parts.append(rule[1].pattern)
                pattern = "|".join(f"(?:{part})" for part in parts) if parts else None
            if pattern is not None:
                fields[kind] = pattern
        rules[analysis] = {"module": f"mw.{module}", "renderVersion": getattr(loaded, "RENDER_VERSION", None),
                           "evidenceKinds": list(kinds), "fields": fields,
                           "referenceNote": getattr(loaded, "REFERENCE_NOTE", None),
                           "modelResponseNote": getattr(loaded, "MODEL_RESPONSE_NOTE", None)}
    return rules


def export(backend: Path) -> dict:
    body = {"schema": "m28_fixed_sentences@1", "sentences": sentences(), "inline": inline(backend),
            "phrases": [{"id": f"mw.{module}.{name}", "text": getattr(importlib.import_module(f"mw.{module}"), name)}
                        for module, name in PHRASES],
            "reportRules": report_rules()}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return {**body, "sha256": hashlib.sha256(raw).hexdigest()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the JSON here (else stdout)")
    args = parser.parse_args(argv)
    import mw
    backend = Path(mw.__file__).resolve().parents[1]
    text = json.dumps(export(backend), indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
