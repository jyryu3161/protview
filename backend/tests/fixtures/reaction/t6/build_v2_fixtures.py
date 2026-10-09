"""Builder (M26 T6b) of the STORED M20 v2 candidate sets ``m20-candidate-set-v2-1ubq-{not_checked,checked}.json``.

Through the product tools only (``Run.call``): run ``run_m26_t6b_v2`` -> ``load_structure`` (public 1UBQ by file path)
-> ``prepare_structure`` (defaults) -> ``link_reaction_knowledge`` (made-up PDB ID 0SY8, chain A) over the LABELLED
SYNTHETIC reaction set of ``m20_v2_fixture.activate_ubq`` -> ``generate_mutation_candidates`` for the TINY positions
without and with that result as ``catalytic_annotation``. Each file is ``{handle, content}`` (canonical JSON +
newline). See ``SYNTHETIC-PROVENANCE-t6b.md``.

``--write`` writes the two files after two fresh builds agree; ``--check`` exits 0 only if a fresh build equals the
committed files. The files are STORED sets: once the M20 code changes, ``--check`` may fail by design and the stored
copies stay as they are (rewrite them only on purpose). Runs and the reaction set live in a temporary folder; no
network. Not product code.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE.parents[2]
for extra in (str(TESTS.parent), str(TESTS)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import m20_v2_fixture as V2
import pytest

from mw.core.handles import canonical_json
from mw.workspace import new_run


def build() -> dict[str, bytes]:
    with tempfile.TemporaryDirectory(prefix="m26_t6b_v2_") as tmp, pytest.MonkeyPatch.context() as patch:
        V2.activate_ubq(Path(tmp) / "reaction_reference", patch)
        run = new_run(Path(tmp) / "runs", run_id=V2.RUN_ID, dry_run=False)
        prepared = V2.load_prepare(run)
        sets = V2.make_sets(run, prepared, V2.link_ubq(run, prepared))
        return {name: canonical_json({"handle": handle, "content": run.store.load(handle)}) + b"\n"
                for name, handle in sets.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    first = build()
    if check:
        same = all(V2.fixture_path(name).read_bytes() == raw for name, raw in first.items())
        print("stored v2 sets match a fresh build" if same else "stored v2 sets differ from a fresh build")
        return 0 if same else 1
    if build() != first:
        print("two fresh builds differ; nothing written")
        return 1
    for name, raw in first.items():
        V2.fixture_path(name).write_bytes(raw)
        content = json.loads(raw)["content"]
        print(name, json.loads(raw)["handle"], content["protection_checks"]["catalytic_residue_database"]["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
