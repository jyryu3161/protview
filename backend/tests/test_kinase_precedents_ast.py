"""M27 T5: one place for the source and artifact checks of all six M27 server modules (spec 9.3, 9.4, 10 "AST·문자열").

(a) No network module, chemistry package or process module is imported; absolute imports are standard library only;
    ``precedent_constants.py`` imports no ``mw`` module at all; ``precedent_snapshots.py`` uses the standard library and
    the constants module only.
(b) No kbase path or ``.git`` reference, no credential name.
(c) No limit-raise name; the ``Run.raise_limits`` callers (M19 / M22 / M23) and the ``request_science`` /
    ``run_send`` callers (M24) are unchanged (read the same way as ``test_jev_ast.py``).
(d) A sentinel credential in the environment reaches no M27 artifact: tool result, reads, reports, downloads, the run
    folder and the reference folder (LABELLED SYNTHETIC precedent set, public 1MQ4, SYNTHETIC T2 numbering map).
(e) The 27 call-key hash files are byte-identical to the M27 baseline (``docs/qa/m27-precedents-20261010/
    preflight.md`` (h): git blob of each file and the SHA-256 of the ``git ls-tree`` lines, embedded below).
Static reads of the source only, except (d); nothing reaches the network.
"""
from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path

import precedent_fixture as PF
import pytest
from fastapi.testclient import TestClient
from test_kinase_precedents_tool import CIF_1MQ4, _store_map

from mw import kinase_precedents as kp
from mw import precedent_constants as K
from mw import precedent_snapshots as ps

MW = Path(__file__).resolve().parents[1] / "mw"
BACKEND = MW.parent
SERVER_MODULES = ("precedent_constants.py", "precedent_snapshots.py", "kinase_precedents.py",
                  "kinase_precedents_reads.py", "kinase_precedents_reports.py", "tools/kinase_precedents.py")
NETWORK = {"socket", "urllib", "urllib3", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp", "websockets",
           "smtplib", "telnetlib", "xmlrpc", "socketserver", "asyncio"}
CHEMISTRY = {"rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "prolif", "openbabel", "pybel", "vina", "gemmi"}
PROCESS = {"subprocess", "multiprocessing", "pty", "concurrent"}
SENTINEL = "sentinel_m27_t5_key_do_not_store"


def _tree(rel: str) -> ast.Module:
    return ast.parse((MW / rel).read_text(encoding="utf-8"))


def _imports(rel: str) -> tuple[set[str], set[str]]:
    """(absolute module names, relative module names with their dots) imported by a module."""
    absolute, relative = set(), set()
    for node in ast.walk(_tree(rel)):
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


# ------------------------------------------------------------------------------------------- (a) imports

def test_the_six_server_modules_are_the_m27_server_modules():
    for rel in SERVER_MODULES:
        assert (MW / rel).is_file(), rel
    assert sorted(p.name for p in MW.glob("*precedent*.py")) == sorted(
        ["precedent_constants.py", "precedent_snapshots.py", "kinase_precedents.py", "kinase_precedents_reads.py",
         "kinase_precedents_reports.py"])


@pytest.mark.parametrize("rel", SERVER_MODULES)
def test_no_network_chemistry_or_process_module_and_only_standard_library_absolute_imports(rel):
    absolute, relative = _imports(rel)
    tops = {name.split(".")[0] for name in absolute}
    assert not tops & (NETWORK | CHEMISTRY | PROCESS), tops
    assert tops - {"__future__"} <= set(sys.stdlib_module_names), tops
    names = {name.lstrip(".").split(".")[-1] for name in relative}
    assert not names & (NETWORK | CHEMISTRY | PROCESS | {"egress", "jev_sends", "gate", "science"}), names
    source = (MW / rel).read_text(encoding="utf-8")
    for call in ("__import__", "importlib", "os.system", "os.popen", "os.exec", "os.spawn"):
        assert call not in source, (rel, call)


def test_precedent_constants_imports_no_mw_module_at_all():
    absolute, relative = _imports("precedent_constants.py")
    assert relative == set() and not any(name.split(".")[0] == "mw" for name in absolute)


def test_precedent_snapshots_uses_the_standard_library_and_the_constants_module_only():
    absolute, relative = _imports("precedent_snapshots.py")
    assert relative == {".", ".precedent_constants"}
    assert not any(name.split(".")[0] == "mw" for name in absolute)


def test_the_other_modules_read_only_their_own_family_and_shared_runtime_helpers():
    allowed = {".", ".precedent_constants", ".precedent_snapshots", ".kinase_precedents", ".reports",
               ".core.handles", ".core.handles.canonical_json", ".reports.EvidenceError", ".reports._md",
               ".reports._provenance", "..", "..kinase_precedents", "..precedent_constants", "..precedent_snapshots",
               "..core.errors", "..core.errors.FailureClass", "..core.errors.ToolFailure", "..core.handles",
               "..core.handles.Handle", "..core.handles.canonical_json", ".registry", ".registry.ToolContext",
               ".registry.ToolRegistry"}
    for rel in ("kinase_precedents.py", "kinase_precedents_reads.py", "kinase_precedents_reports.py",
                "tools/kinase_precedents.py"):
        _absolute, relative = _imports(rel)
        assert relative <= allowed, (rel, relative - allowed)


# ------------------------------------------------------------------------------------------- (b) paths, credentials

@pytest.mark.parametrize("rel", SERVER_MODULES)
def test_no_kbase_path_git_or_credential_reference(rel):
    source = (MW / rel).read_text(encoding="utf-8")
    for banned in ("../kbase", "kbase_kinase/", "/kbase_kinase", "Projects/kbase", ".git", "OPENROUTER", "API_KEY",
                   "dotenv", "Authorization", "Bearer "):
        assert banned not in source, (rel, banned)
    strings = {node.value for node in ast.walk(_tree(rel)) if isinstance(node, ast.Constant)
               and isinstance(node.value, str)}
    assert not {s for s in strings if s == ".env" or s.endswith("/.env")}, rel


# ------------------------------------------------------------------------------------------- (c) callers

def _sources():
    for path in sorted(MW.rglob("*.py")):
        yield str(path.relative_to(MW)), ast.parse(path.read_text(encoding="utf-8"))


def _owners(tree):
    owner = {}

    def visit(node, name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owner[child] = name
                visit(child, child.name if name == "<module>" else f"{name}.{child.name}")
            else:
                owner[child] = name
                visit(child, name)
    visit(tree, "<module>")
    return owner


def _references(name):
    """(file, enclosing function, 'call' | 'ref') for every Name / Attribute spelled ``name`` in backend/mw."""
    found = set()
    for rel, tree in _sources():
        owner = _owners(tree)
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
                if called == name:
                    calls.add(id(func))
        for node in ast.walk(tree):
            spelled = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
            if spelled == name:
                found.add((rel, owner[node], "call" if id(node) in calls else "ref"))
    return found


@pytest.mark.parametrize("rel", SERVER_MODULES)
def test_no_limit_raise_or_science_send_name_in_the_m27_modules(rel):
    source = (MW / rel).read_text(encoding="utf-8")
    for name in ("raise_limits", "limit_approval", "request_science", "run_send", "SCIENCE_GATE", "begin_send",
                 "EgressGate"):
        assert name not in source, (rel, name)


def test_the_limit_raise_callers_are_still_the_three():
    callers = {(rel, owner) for rel, owner, kind in _references("raise_limits") if kind == "call"}
    assert callers == {("docking_batch_jobs.py", "limit_approval"), ("ligand_ga_jobs.py", "limit_approval"),
                       ("sequence_ga_jobs.py", "limit_approval")}


def test_request_science_and_run_send_callers_are_unchanged():
    assert _references("request_science") == {("jev_sends.py", "run_send", "call"),
                                              ("egress/gate.py", "EgressGate.request_science", "call")}
    assert _references("run_send") == {("api/app.py", "jev_send_create", "call")}


# ------------------------------------------------------------------------------------------- (d) sentinel

@pytest.fixture
def refdir(tmp_path, monkeypatch):
    root = tmp_path / "precedent_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    yield root
    ps._VERIFIED.clear()
    kp.clear_index_cache()


@pytest.fixture
def client(tmp_path, monkeypatch):
    import mw.api.app as appmod
    monkeypatch.setattr(appmod, "RUNS_DIR", tmp_path / "runs")
    appmod.RUNS.clear()
    yield TestClient(appmod.app, base_url="http://127.0.0.1")
    appmod.RUNS.clear()


def _bytes_under(root: Path) -> list[tuple[Path, bytes]]:
    return [(path, path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file()]


def test_a_sentinel_credential_reaches_no_m27_artifact(client, refdir, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SENTINEL)
    monkeypatch.setenv("MW_SENTINEL_TOKEN", SENTINEL)
    PF.build_set(refdir)
    import mw.api.app as appmod
    rid = client.post("/runs", json={"goal": "kinase precedent sentinel", "dry_run": False}).json()["run_id"]
    upload = client.post(f"/runs/{rid}/uploads", params={"filename": CIF_1MQ4.name}, content=CIF_1MQ4.read_bytes(),
                         headers={"content-type": "application/octet-stream"})
    structure = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure", "args": {
        "source": upload.json()["upload_id"]}}).json()["handle"]["handle"]
    run = appmod._run(rid)
    nmap = _store_map(run, structure, "main")
    bodies = []
    handles = []
    for include in (False, True):
        response = client.post(f"/runs/{rid}/commands", json={"tool": K.TOOL, "args": {
            "numbering_map": nmap, "chains": None, "include_flagged": include}})
        assert response.status_code == 200, response.text
        bodies.append(response.text)
        handles.append(response.json()["handle"]["handle"])
    for handle in handles:
        bodies.append(client.get(f"/runs/{rid}/kinase_precedents/{handle}").text)
        report = client.post(f"/runs/{rid}/method_reports", json={"result_handle": handle})
        assert report.status_code == 201, report.text
        bodies.append(report.text)
        report_handle = report.json()["handle"]
        bodies.append(client.get(f"/runs/{rid}/reports/selected", params={"handle": report_handle}).text)
        for fmt in ("markdown", "json"):
            bodies.append(client.get(f"/runs/{rid}/reports/download",
                                     params={"handle": report_handle, "format": fmt}).text)
    bodies += [client.get(f"/runs/{rid}/kinase_precedents").text, client.get("/precedent_reference/status").text,
               client.get("/capabilities").text, client.get(f"/runs/{rid}/reports").text]
    for body in bodies:
        assert SENTINEL not in body
    for path, data in _bytes_under(run.run_dir) + _bytes_under(refdir):
        assert SENTINEL.encode() not in data, path


# ------------------------------------------------------------------------------------------- (e) call-key files

HASH_FILE_PATTERN = re.compile(r"docking_worker\.py|docking_constants\.py|openmm_mutation_worker\.py|"
                               r"mutation_model_constants\.py|mutation_model_math\.py|mutation_candidates\.py|"
                               r"ligand_ga_|sequence_ga_|docking_batch_")
# git blob ids at main 6ac3a59 (docs/qa/m27-precedents-20261010/preflight.md (h)); never re-recorded by M27
BASELINE_BLOBS = {
    "backend/mw/docking_batch_bundle.py": "99324f07fc9519454330c4195f5036f8344752b2",
    "backend/mw/docking_batch_constants.py": "b9eb497a8edf27d0a38a203d70a4fe9958923851",
    "backend/mw/docking_batch_inputs.py": "21c96abe501b6c3a01e8dc62435901f2499c6d5b",
    "backend/mw/docking_batch_jobs.py": "25db2dbfb5c016b6fff3d78dedc512ade3ffd1d6",
    "backend/mw/docking_batch_reads.py": "b10e8ab712c530d8d3eaebb808be47be13ac7652",
    "backend/mw/docking_batch_reports.py": "e5985e188bf8bbcb4862a26be126c8fb529db1d4",
    "backend/mw/docking_constants.py": "4097a474d3adaf16a70eb9914d2864fff2c62c68",
    "backend/mw/jobs/docking_batch_worker.py": "252582abf85478358857837a936a95a8e72a4000",
    "backend/mw/jobs/docking_worker.py": "2585689176091e19cae66ac798b37e92d8bc64b0",
    "backend/mw/jobs/ligand_ga_worker.py": "17c19542bbf8a340b6fa86e3c656bfa191938642",
    "backend/mw/jobs/openmm_mutation_worker.py": "71e5e9d90409dbb15aba5088b4686f00a832989d",
    "backend/mw/jobs/sequence_ga_worker.py": "6e3a6f9ff8b1eb4a5af6e5647bf45dc41c877763",
    "backend/mw/ligand_ga_bundle.py": "0da89ee65d9812819ac0f06acd6fe20ca8de1ceb",
    "backend/mw/ligand_ga_constants.py": "d3dce79f3966272de2d994ddec8dbc8c8c19265d",
    "backend/mw/ligand_ga_inputs.py": "f6916713dbfef8ce32fcb4be9aad884b0e22b2d5",
    "backend/mw/ligand_ga_jobs.py": "1fa628897baaf4bce7e2ea602f16f3b21d8284f1",
    "backend/mw/ligand_ga_reads.py": "3f05e3d6040f17130d0a0c8f807e1f7a8aefbd02",
    "backend/mw/ligand_ga_reports.py": "2d0bd4c3160f4bec5d3e014febc83f79a39129cb",
    "backend/mw/mutation_candidates.py": "ec3f5468b869b4109050ccdb2ade79d8b46ca784",
    "backend/mw/mutation_model_constants.py": "f9187acf8583d16a595bf7b75ebd4430d48d8d33",
    "backend/mw/mutation_model_math.py": "6cb8b5abb2246ceb02b9d3604b1e44a6cc72b70b",
    "backend/mw/sequence_ga_bundle.py": "aaa946823f99b474ffcca2f3c89bc0db84bb5823",
    "backend/mw/sequence_ga_constants.py": "53c679fdc18bd5fd80d198cc2b0664ae640389e2",
    "backend/mw/sequence_ga_inputs.py": "926a13c267c383798cb1ed5a1c1f1220c716f2e8",
    "backend/mw/sequence_ga_jobs.py": "bd11e964b5f6d5533ded1dbc0a2eb1b60e63a154",
    "backend/mw/sequence_ga_reads.py": "e35e0de40469061bbce95229431ab69a2f29b3f1",
    "backend/mw/sequence_ga_reports.py": "5074ae2479b984c3c6b78e11dc08f573b3777c1a",
}
# sha256 of the `git ls-tree HEAD <27 files>` output at the baseline (mode 100644 for all 27)
BASELINE_DIGEST = "3a2fc4093bbb61b936c347741f06dd2c9b39df21e305c168d9d4d57872193cb0"


def _blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def test_the_call_key_hash_files_are_byte_identical_to_the_m27_baseline():
    found = sorted(path.relative_to(BACKEND.parent).as_posix() for path in MW.rglob("*.py")
                   if HASH_FILE_PATTERN.search(path.relative_to(BACKEND.parent).as_posix()))
    assert found == sorted(BASELINE_BLOBS) and len(found) == 27
    blobs = {rel: _blob((BACKEND.parent / rel).read_bytes()) for rel in found}
    assert blobs == BASELINE_BLOBS
    listing = "".join(f"100644 blob {blobs[rel]}\t{rel}\n" for rel in found)
    assert hashlib.sha256(listing.encode()).hexdigest() == BASELINE_DIGEST
