"""M29 T4: source and fixture boundaries of the three core modules (spec 14.6; handoff absolute condition 8).

(a) No network, process, engine or chemistry module is imported (PDBFixer and OpenMM are never imported: the template
    XML is located with ``importlib.util.find_spec`` and read as a file); ``structure_repair_constants.py`` imports
    nothing; ``structure_origin.py`` imports only the constants and ``core`` (so read modules with import limits may use
    it); no limit-raise name.
(b) Importing the modules (and reading the template) loads no engine, network or send module.
(c) The SYNTHETIC fixtures are labelled and rebuild byte for byte; the measured fixtures are labelled; no fixture holds a
    user path.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import test_structure_repair_common as C

MW = Path(__file__).resolve().parents[1] / "mw"
MODULES = ("structure_repair_constants.py", "structure_repair.py", "structure_origin.py")
NETWORK = {"socket", "urllib", "urllib3", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp", "websockets",
           "smtplib", "telnetlib", "xmlrpc", "socketserver", "asyncio"}
PROCESS = {"subprocess", "multiprocessing", "pty", "concurrent", "signal"}
ENGINES = {"openmm", "pdbfixer", "rdkit", "meeko", "MDAnalysis", "prolif", "freesasa", "psutil"}


def _imports(rel: str) -> tuple[set[str], set[str]]:
    absolute, relative = set(), set()
    for node in ast.walk(ast.parse((MW / rel).read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            absolute.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                absolute.add(node.module or "")
            else:
                base = "." * node.level + (node.module or "")
                relative.add(base)
                relative.update(f"{base}.{alias.name}" if node.module else f"{base}{alias.name}"
                                for alias in node.names)
    return absolute, relative


@pytest.mark.parametrize("rel", MODULES)
def test_no_network_process_or_engine_module_and_no_limit_raise_name(rel):
    absolute, relative = _imports(rel)
    tops = {name.split(".")[0] for name in absolute}
    assert not tops & (NETWORK | PROCESS | ENGINES), tops
    assert tops - {"__future__", "gemmi", "numpy"} <= set(sys.stdlib_module_names), tops
    names = {name.lstrip(".").split(".")[-1] for name in relative}
    assert not names & (NETWORK | PROCESS | ENGINES | {"egress", "jev_sends", "gate", "science", "queue", "guardian"})
    source = (MW / rel).read_text(encoding="utf-8")
    for banned in ("raise_limits", "limit_approval", "subprocess", "__import__", "os.system", "os.popen", "os.exec",
                   "os.spawn", "import_module", "OPENROUTER", "API_KEY"):
        assert banned not in source, (rel, banned)


def test_the_constants_module_imports_nothing():
    absolute, relative = _imports("structure_repair_constants.py")
    assert (absolute, relative) == ({"__future__"}, set())


def test_the_origin_module_imports_only_the_constants_and_core():
    absolute, relative = _imports("structure_origin.py")
    assert absolute == {"__future__", "typing"}
    assert relative == {".", ".structure_repair_constants", ".core.errors", ".core.errors.FailureClass",
                        ".core.errors.ToolFailure"}


def test_the_core_module_imports_only_its_allowed_mw_modules():
    absolute, relative = _imports("structure_repair.py")
    assert {name.split(".")[0] for name in absolute} - set(sys.stdlib_module_names) == {"gemmi", "numpy"}
    assert relative <= {".", ".structure_repair_constants", ".core.errors", ".core.errors.FailureClass",
                        ".core.errors.ToolFailure", ".core.handles", ".core.handles.HANDLE_PREFIX",
                        ".core.handles.canonical_json", ".core.handles.object_sha", ".core.handles.sha256_hex",
                        ".openmm_bundle", ".openmm_bundle.FORCEFIELD_SHA256", ".tools.structural",
                        ".tools.structural.METALS", ".tools.structural._res_ref"}, relative


def test_importing_and_reading_the_template_loads_no_engine_network_or_send_module():
    code = ("import sys\nimport mw.structure_origin\n"
            "light = [m for m in ('gemmi', 'numpy', 'openmm', 'pdbfixer', 'httpx', 'mw.jev_sends', 'mw.egress') "
            "if m in sys.modules]\n"
            "import mw.structure_repair as sr\nsr.template_heavy('ALA', True)\n"
            "heavy = [m for m in ('openmm', 'pdbfixer', 'httpx', 'mw.jev_sends', 'mw.egress', 'mw.jobs.queue') "
            "if m in sys.modules]\nprint(light, heavy)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[] []", out.stdout + out.stderr


def test_synthetic_fixtures_are_labelled_and_rebuild_byte_for_byte():
    path = C.SR_FIX / "build_synthetic_fixtures.py"
    spec = importlib.util.spec_from_file_location("m29_t4_build_synthetic_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True   # no __pycache__ in the fixture folder
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    built = module.build()
    assert {name: (C.SR_FIX / name).read_bytes() for name in built} == built
    provenance = json.loads(built["synthetic-fixtures.provenance.json"])
    names = sorted(p.name for p in C.SR_FIX.glob("synthetic-*") if p.name != "synthetic-fixtures.provenance.json")
    assert sorted(provenance["files"]) == names and "SYNTHETIC" in provenance["label"]
    for name in names:
        raw = (C.SR_FIX / name).read_bytes()
        assert provenance["files"][name]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert b"SYNTHETIC TEST FIXTURE" in raw[:2000] and b"not an experimental structure" in raw[:2000]


def test_measured_fixtures_are_labelled_and_no_fixture_holds_a_user_path():
    for name in C.MEASURED:
        data = json.loads((C.SR_FIX / f"{name}-additions.pdbfixer-measured.json").read_text())
        assert data["schema"] == "m29_t1_pdbfixer_measured_additions@1"
        assert "PDBFixer 측정 고정 자료(제품 값 아님)" in data["label"]
        assert data["input"]["file"] in (f"backend/tests/fixtures/public_{name}.cif",
                                         f"runs/stk33-8vf6-20261013/{name.upper()}.cif")
        assert data["input"]["sha256"] == hashlib.sha256((C.FIX / f"public_{name}.cif").read_bytes()).hexdigest()
    provenance = json.loads((C.SR_FIX / "pdbfixer-measured-fixtures.provenance.json").read_text())
    assert sorted(provenance["files"]) == sorted(f"{n}-additions.pdbfixer-measured.json" for n in C.MEASURED
                                                 if n != "8vf6")
    for file, item in provenance["files"].items():
        assert item["sha256"] == hashlib.sha256((C.SR_FIX / file).read_bytes()).hexdigest()
    for path in (p for p in C.SR_FIX.iterdir() if p.is_file()):
        text = path.read_bytes()
        assert b"/Users/" not in text and b"/private/" not in text and b"/home/" not in text, path.name
