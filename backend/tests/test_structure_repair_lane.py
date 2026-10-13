"""M29 T5: the ``pdbfixer_repair_v1`` lane without a worker process (spec 4.1-4.6, 14.6).

Registration (job-only tool, protocol table, guardian adapter, queue bounds, ``/tools``, capability), the import
boundary of the new server modules, the admission order (every input code, then 412 unavailability, then the 422
``repair_not_possible`` of every refusal reason, then the 429 staged size), dry-run, the pinned start, the free
preflight read and the read routes on an unpublished record. Inputs: public structures (``fixtures/public_*.cif``) and
the SYNTHETIC structure-repair fixtures of T4 (labelled in their files). No job reaches a worker here; fault
injections are labelled internal hooks (monkeypatched functions or limits), never request fields.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
import structure_repair_lane_fixture as F
import test_structure_repair_common as C

from mw import structure_repair_bundle as bundle
from mw import structure_repair_constants as K
from mw import structure_repair_jobs as jobs
from mw import structure_repair_reads as reads
from mw.api import app as api_module
from mw.jobs import guardian as guardian_module
from mw.jobs import process_identity
from mw.jobs import queue as queue_module
from mw.jobs.queue import JobQueue
from mw.runtime.orchestrator import Run
from mw.tools import openmm_method
from mw.tools.energetic import JOB_ONLY_TOOLS, JOB_PROTOCOLS
from mw.tools.structure_repair import PREFLIGHT_KEYS

MW = Path(__file__).resolve().parents[1] / "mw"
SERVER_MODULES = ("structure_repair_jobs.py", "structure_repair_bundle.py", "structure_repair_reads.py",
                  "tools/structure_repair.py")
NETWORK = {"socket", "urllib", "urllib3", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp", "websockets",
           "smtplib", "telnetlib", "xmlrpc", "socketserver", "asyncio"}
PROCESS = {"subprocess", "multiprocessing", "pty", "concurrent", "signal"}
ENGINES = {"openmm", "pdbfixer", "rdkit", "meeko", "MDAnalysis", "prolif", "freesasa"}
UBQ = F.public("1ubq")
CLL = F.public("1cll")


def _imports(path: Path) -> tuple[set[str], set[str]]:
    absolute, relative = set(), set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            absolute.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                absolute.add(node.module or "")
            else:
                base = "." * node.level + (node.module or "")
                relative.add(base)
                relative.update(f"{base}.{alias.name}" for alias in node.names)
    return absolute, relative


def _prepare(client, world: dict, **policy) -> str:
    """Another prepared structure of the world's source (another manifest, so another handle and call key)."""
    return F.command(client, world["rid"], "prepare_structure", {
        "structure": world["source"], "altloc": policy.get("altloc", "highest_occupancy"),
        "waters": policy.get("waters", "strip_all"), "hydrogens": policy.get("hydrogens", "strip"),
        "missing_residues": "leave_gaps", "symmetry_mates": "ignore"})


# ----------------------------------------------------------------- registration and boundaries
def test_registration_dispatch_table_bounds_tools_listing_and_capability(tmp_path, monkeypatch):
    assert JOB_PROTOCOLS[K.PROTOCOL] == (K.TOOL, "pdbfixer")
    assert K.TOOL in JOB_ONLY_TOOLS and K.TOOL not in api_module.SUPPORTED_TOOLS
    assert K.TOOL in api_module.REGISTRY.impls and K.TOOL in api_module.REGISTRY.unavailable
    spec = api_module.REGISTRY.specs[K.TOOL]
    assert spec.cost_class == "expensive" and spec.emits == K.KIND and spec.level == "L3"
    # Code-owned dispatch: the fixed worker module in the project interpreter (as M7 and M21), monitored, 4 MB output.
    assert guardian_module.STRUCTURE_REPAIR_ADAPTER == K.PROTOCOL
    assert guardian_module.STRUCTURE_REPAIR == MW / "jobs/structure_repair_worker.py" == jobs.WORKER
    assert K.PROTOCOL not in guardian_module.PINNED_PYTHON_ADAPTERS | guardian_module.DOCKING_ADAPTERS
    assert K.PROTOCOL in guardian_module.MONITORED_ADAPTERS
    worker = ast.parse(jobs.WORKER.read_text())
    bound = next(node.value.value for node in worker.body if isinstance(node, ast.Assign) and
                 any(getattr(t, "id", None) == "MAX_OUTPUT_BYTES" for t in node.targets))
    assert guardian_module.STRUCTURE_REPAIR_OUTPUT_LIMIT == jobs.OUTPUT_LIMIT == bound == 4_000_000
    assert queue_module.REPAIR_PROTOCOL == K.PROTOCOL
    assert (queue_module.REPAIR_TIMEOUT_MAX_S, queue_module.REPAIR_TIMEOUT_DEFAULT_S) == (240, 120)
    capability = jobs.capability()
    assert capability["available"] is True, f"OpenMM 8.6.0 + PDBFixer 1.12.0 must be installed: {capability}"
    assert capability["reason_code"] is None and capability["reason"] is None
    assert capability["versions"]["openmm"] == "8.6.0" and capability["versions"]["pdbfixer"] == "1.12.0"
    assert capability["protocol_id"] == K.PROTOCOL and capability["tool_id"] == K.TOOL
    assert capability["timeout_s"] == {"default": 120, "max": 240}
    client = F.client(tmp_path / "runs", monkeypatch)
    methods = client.get("/capabilities").json()["methods"]
    assert methods["structure_repair"] == capability
    assert methods["openmm_protein_minimize"] == openmm_method.capability()
    l3 = {tool["name"]: tool for tool in client.get("/tools", params={"levels": "L3"}).json()}
    assert l3[K.TOOL]["execution_lane"] == "durable_job" and l3[K.TOOL]["submit_protocol_id"] == K.PROTOCOL
    assert K.TOOL not in {tool["name"] for tool in client.get("/tools").json()}
    # Neither the command route nor Run.call runs the job-only tool.
    world = F.world(client, "M29 job-only tool (public 1UBQ, not experimental validation)", UBQ, "public_1ubq.cif")
    refused = client.post(f"/runs/{world['rid']}/commands", json={"tool": K.TOOL, "args": F.args(world["structure"])})
    assert refused.status_code == 422 and refused.json()["message"] == f"unsupported tool '{K.TOOL}'"
    with pytest.raises(queue_module.ToolFailure) as caught:
        api_module._run(world["rid"]).call(K.TOOL, F.args(world["structure"]))
    assert caught.value.detail["reason_code"] == "job_only_tool"


@pytest.mark.parametrize("rel", SERVER_MODULES)
def test_server_modules_import_no_pdbfixer_network_process_or_engine_module(rel):
    absolute, relative = _imports(MW / rel)
    tops = {name.split(".")[0] for name in absolute}
    assert not tops & (NETWORK | PROCESS | ENGINES), tops
    assert tops - {"__future__"} <= set(sys.stdlib_module_names), tops
    names = {name.lstrip(".").split(".")[-1] for name in relative}
    assert not names & (NETWORK | PROCESS | ENGINES | {"egress", "jev_sends", "gate", "science", "queue", "guardian",
                                                       "structure_repair_worker"})
    source = (MW / rel).read_text(encoding="utf-8")
    for banned in ("raise_limits", "limit_approval", "subprocess", "__import__", "os.system", "os.popen", "os.exec",
                   "os.spawn", "import_module", "OPENROUTER", "API_KEY", "pdbfixer import", "import pdbfixer"):
        assert banned not in source, (rel, banned)


def test_pdbfixer_is_imported_by_the_worker_only_and_never_by_the_server_process():
    for path in MW.rglob("*.py"):
        absolute, _ = _imports(path)
        if any(name.split(".")[0] == "pdbfixer" for name in absolute):
            assert path.relative_to(MW).as_posix() in {"jobs/structure_repair_worker.py",
                                                       "jobs/openmm_mutation_worker.py"}, path
    absolute, _relative = _imports(jobs.WORKER)
    assert "pdbfixer" in absolute and not {name.split(".")[0] for name in absolute} & (NETWORK | {"subprocess"})
    for name in ("jobs/queue.py", "jobs/guardian.py", "api/app.py", "tools/energetic.py", "workspace.py"):
        imported = " ".join(sorted(_imports(MW / name)[0] | _imports(MW / name)[1]))
        assert "pdbfixer" not in imported and "structure_repair_worker" not in imported, name
    code = ("import sys; import mw.api.app, mw.structure_repair_jobs, mw.structure_repair_bundle, "
            "mw.structure_repair_reads, mw.tools.structure_repair, mw.jobs.queue; "
            "from mw import structure_repair_jobs as j; assert j.capability()['available']; "
            "print(sorted(m for m in sys.modules if m.split('.')[0] == 'pdbfixer' or 'structure_repair_worker' in m))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180,
                         cwd=str(MW.parent), check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


# ----------------------------------------------------------------- admission (no job, no budget, no event)
def test_admission_order_reaches_every_input_code_without_a_job(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 admission (public 1UBQ, not experimental validation)", UBQ, "public_1ubq.cif")
    other = F.world(client, "M29 admission other run (public 1UBQ)", UBQ, "public_1ubq.cif")
    rid, structure = world["rid"], world["structure"]
    before = (root / rid / "events.jsonl").read_bytes()

    def refused(job_args, reason, timeout_s=240):
        response = F.submit(client, rid, job_args, timeout_s)
        assert response.status_code == 422, (reason, response.text)
        assert response.json()["error"] == "input_invalid"
        assert response.json()["detail"]["reason_code"] == reason, (reason, response.json())

    refused({**F.args(structure), "seed": 2}, "unknown_field")
    refused({**F.args(structure), "argv": ["x"]}, "unknown_field")
    refused({"structure": 7, "repair_policy": "x", "extra": 1}, "unknown_field")   # the first failing check only
    refused({"structure": structure}, "confirmation_missing")
    refused(F.args(structure, repair_policy="complete"), "confirmation_missing")
    refused({"structure": 7, "repair_policy": "x"}, "confirmation_missing")
    for bad in (7, "", None):
        refused(F.args(bad), "argument_invalid")
    for timeout_s in (241, 900, 15000):   # inside the API model bound; the lane bound is 240
        refused(F.args(structure), "argument_invalid", timeout_s=timeout_s)
    refused(F.args("obj://nope"), "structure_invalid")
    for wrong in (world["source"], other["structure"], f"obj://{rid}/prepared_structure/{'0' * 64}"):
        refused(F.args(wrong), "structure_invalid")
    for timeout_s in (0, -1, float("nan"), True):   # the queue checks them too (the API model refuses them first)
        with pytest.raises(queue_module.ToolFailure) as caught:
            JobQueue(api_module._run(rid)).submit(K.PROTOCOL, F.args(structure), timeout_s=timeout_s)
        assert caught.value.detail["reason_code"] == "argument_invalid"
    # The API request model's own refusals keep the closed reason for this protocol.
    for timeout_s in (0, -1, 15001, "x"):
        refused(F.args(structure), "argument_invalid", timeout_s=timeout_s)
    for job_args in ([], "x", 7, None):
        refused(job_args, "argument_invalid")
    extra = client.post(f"/runs/{rid}/jobs", json={"protocol_id": K.PROTOCOL, "args": F.args(structure), "x": 1})
    assert extra.status_code == 422 and "reason_code" not in extra.json()["detail"]
    assert (root / rid / "events.jsonl").read_bytes() == before
    assert F.used(client, rid) == 0
    assert K.ADMISSION_REASON_CODES == ("unknown_field", "confirmation_missing", "argument_invalid",
                                        "structure_invalid", "already_repaired")


REFUSALS = [   # (input, file name, refusal reason, extra detail)
    (F.public("1ubq"), "public_1ubq.cif", "nothing_to_repair", {}),
    (F.public("1s9i"), "public_1s9i.cif", "gap_too_long", {}),
    (F.public("1fin"), "public_1fin.cif", "atom_limit_exceeded", {}),
    ((C.SR_FIX / "synthetic-chain-identity-duplicate.cif").read_bytes(), "synthetic-chain-identity-duplicate.cif",
     "chain_identity_duplicate", {}),
    ((C.SR_FIX / "synthetic-unsupported-residue.cif").read_bytes(), "synthetic-unsupported-residue.cif",
     "unsupported_residue", {}),
    ((C.SR_FIX / "synthetic-unexpected-atoms.cif").read_bytes(), "synthetic-unexpected-atoms.cif",
     "unexpected_atoms", {}),
    ((C.SR_FIX / "synthetic-backbone-atoms-missing.cif").read_bytes(), "synthetic-backbone-atoms-missing.cif",
     "backbone_atoms_missing", {}),
    ((C.SR_FIX / "synthetic-gap-listing-missing.cif").read_bytes(), "synthetic-gap-listing-missing.cif",
     "gap_listing_missing", {}),
    ((C.SR_FIX / "synthetic-chain-break.pdb").read_bytes(), "synthetic-chain-break.pdb", "m7_condition_unsupported",
     {"m7_reason": "peptide_geometry"}),
]


def test_every_refusal_reason_is_a_422_repair_not_possible_without_a_job(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    reached = []
    for raw, name, reason, extra in REFUSALS:
        world = F.world(client, f"M29 refusal {reason} ({name}; public or SYNTHETIC, not experimental validation)",
                        raw, name)
        rid = world["rid"]
        before = (root / rid / "events.jsonl").read_bytes()
        response = F.submit(client, rid, F.args(world["structure"]))
        assert response.status_code == 422, (name, response.text)
        body = response.json()
        detail = body["detail"]
        assert body["error"] == "input_invalid" and detail["error"] == K.REPAIR_NOT_POSSIBLE, (name, body)
        assert detail["reason_code"] == reason and detail["blockers"][0]["reason_code"] == reason, (name, detail)
        assert [K.REFUSAL_REASONS.index(b["reason_code"]) for b in detail["blockers"]] == sorted(
            K.REFUSAL_REASONS.index(b["reason_code"]) for b in detail["blockers"])
        for key, value in extra.items():
            assert detail[key] == value, (name, detail)
        # The free preflight read lists the same blockers (200) and admits nothing.
        preflight = client.get(f"/runs/{rid}/structure_repair/preflight", params={"structure": world["structure"]})
        assert preflight.status_code == 200
        read = preflight.json()
        assert read["repairable"] is False and read["blockers"] == detail["blockers"]
        assert read["admission"] == {"admitted": False, "error": "input_invalid", "reason_code": reason,
                                     "message": body["message"], "detail": detail}
        assert (root / rid / "events.jsonl").read_bytes() == before and F.used(client, rid) == 0
        reached.append(reason)
    assert sorted(reached) == sorted(K.REFUSAL_REASONS)


def test_unavailable_environment_is_412_before_the_analysis_and_before_any_reservation(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 unavailable (public 1CLL, not experimental validation)", CLL, "public_1cll.cif")
    ubq = F.world(client, "M29 unavailable, nothing to repair (public 1UBQ)", UBQ, "public_1ubq.cif")
    rid = world["rid"]

    def unsupported():
        raise process_identity.IdentityUnavailable("labelled fixture: unsupported raw process identity")

    def missing_pdbfixer():
        raise PackageNotFoundError("pdbfixer")

    states = {
        "process_identity_unavailable": lambda patch: (patch.setattr(openmm_method, "supported", unsupported),
                                                       patch.setattr(queue_module, "supported", unsupported),
                                                       patch.setitem(sys.modules, "openmm", None)),
        "openmm_unavailable": lambda patch: (patch.setitem(sys.modules, "openmm", None),
                                             patch.setattr(jobs, "_pdbfixer_version", missing_pdbfixer)),
        "pdbfixer_unavailable": lambda patch: patch.setattr(jobs, "_pdbfixer_version", missing_pdbfixer),
        "pdbfixer_version": lambda patch: patch.setattr(jobs, "_pdbfixer_version", lambda: "1.11"),
    }
    variants = [world["structure"]] + [_prepare(client, world, **policy) for policy in (
        {"waters": "keep_all"}, {"altloc": "first"}, {"hydrogens": "keep"})]
    for structure, (name, apply) in zip(variants, states.items(), strict=True):
        expected = "pdbfixer_unavailable" if name == "pdbfixer_version" else name
        # A job queued while everything was available cannot start once the engine is gone (one structure per state:
        # a refused start leaves the job claimed).
        queued = F.submit(client, rid, F.args(structure)).json()
        assert queued["status"] == "queued", queued
        with monkeypatch.context() as patch:
            apply(patch)
            patch.setattr(JobQueue, "_supervise", F.forbid)
            capability = client.get("/capabilities").json()["methods"]["structure_repair"]
            assert capability["available"] is False and capability["reason_code"] == expected, capability
            assert capability["reason"] == jobs.REASONS[expected] and capability["versions"] is None
            for target in (structure, ubq["structure"]):   # 412 before the analysis (1UBQ has nothing to repair)
                run_id = rid if target == structure else ubq["rid"]
                refused = F.submit(client, run_id, F.args(target))
                assert refused.status_code == 412 and refused.json()["detail"]["reason_code"] == expected, refused.text
                read = client.get(f"/runs/{run_id}/structure_repair/preflight", params={"structure": target}).json()
                assert read["admission"]["admitted"] is False and read["admission"]["reason_code"] == expected
                assert read["capability"]["available"] is False
            blocked = F.approve_start(client, rid, queued["job_id"])
            assert blocked.status_code == 412 and blocked.json()["detail"]["reason_code"] == expected
    for run_id in (rid, ubq["rid"]):
        events = F.events(root, run_id)
        assert F.used(client, run_id) == 0
        assert not any(e["type"] in {"budget_reserved", "job_dispatch_intent"} for e in events)
    assert len([e for e in F.events(root, rid) if e["type"] == "job_submitted"]) == len(states)
    assert K.UNAVAILABLE_REASON_CODES == ("process_identity_unavailable", "openmm_unavailable", "pdbfixer_unavailable")
    assert jobs.capability()["available"] is True


def test_staged_size_is_429_after_the_analysis_refusal(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 staged size (public 1CLL, not experimental validation)", CLL, "public_1cll.cif")
    ubq = F.world(client, "M29 staged size, nothing to repair (public 1UBQ)", UBQ, "public_1ubq.cif")
    with monkeypatch.context() as patch:
        patch.setattr(K, "MAX_STAGED_INPUT_BYTES", 1000)   # labelled internal hook: the staged bound lowered
        refused = F.submit(client, world["rid"], F.args(world["structure"]))
        assert refused.status_code == 429, refused.text
        assert refused.json()["error"] == "resource_exceeded"
        assert refused.json()["detail"]["reason_code"] == "resource_exceeded"
        assert refused.json()["detail"]["limit"] == "staged_input_bytes" and refused.json()["detail"]["bytes"] > 1000
        read = client.get(f"/runs/{world['rid']}/structure_repair/preflight",
                          params={"structure": world["structure"]}).json()
        assert read["repairable"] is True and read["admission"]["error"] == "resource_exceeded"
        first = F.submit(client, ubq["rid"], F.args(ubq["structure"]))   # the analysis refusal comes first
        assert first.status_code == 422 and first.json()["detail"]["reason_code"] == "nothing_to_repair"
    for run_id in (world["rid"], ubq["rid"]):
        assert not any(e["type"] == "job_submitted" for e in F.events(root, run_id))


def test_dry_run_returns_the_plan_before_any_engine(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 dry run (public 1CLL)", CLL, "public_1cll.cif", dry_run=True)
    run = api_module._run(world["rid"])
    assert run.dry_run is True
    with monkeypatch.context() as patch:   # as M7 and M21: the plan is returned before the engines and the analysis
        patch.setattr(jobs, "require_ready", F.forbid)
        patch.setattr(jobs, "selection", F.forbid)
        plan = JobQueue(run).submit(K.PROTOCOL, F.args(world["structure"]))
    assert plan == {"plan_only": True, "protocol_id": K.PROTOCOL, "reason_code": "dry_run", "available": False,
                    "output_handles": [], "normalized_parameters": F.args(world["structure"])}
    over = F.submit(client, world["rid"], {**F.args(world["structure"]), "extra": 1})
    assert over.status_code == 422 and over.json()["detail"]["reason_code"] == "unknown_field"
    assert not any(e["type"] in {"job_submitted", "budget_reserved"} for e in F.events(root, world["rid"]))


def test_changed_dependency_changes_the_key_and_refuses_the_pinned_start(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 dependency pin (public 1CLL)", CLL, "public_1cll.cif")
    rid = world["rid"]
    assert set(jobs.DEPENDENCIES) == {"mw/structure_repair.py", "mw/structure_repair_constants.py",
                                      "mw/jobs/openmm_worker.py", "mw/tools/openmm_method.py",
                                      "mw/mutation_model_constants.py"}
    for name, path in jobs.DEPENDENCIES.items():
        assert path == MW.parent / name and path.is_file()
    queued = F.submit(client, rid, F.args(world["structure"])).json()
    assert queued["status"] == "queued"
    same = F.submit(client, rid, F.args(world["structure"])).json()
    assert same["job_id"] == queued["job_id"] and same["call_key"] == queued["call_key"]
    for ordinal, name in enumerate(sorted(jobs.DEPENDENCIES)):
        changed = tmp_path / f"changed_{ordinal}.py"     # labelled: a stand-in for an edited dependency file
        changed.write_bytes(jobs.DEPENDENCIES[name].read_bytes() + b"\n# changed\n")
        with monkeypatch.context() as patch:
            patch.setitem(jobs.DEPENDENCIES, name, changed)
            patch.setattr(JobQueue, "_supervise", F.forbid)
            other = F.submit(client, rid, F.args(world["structure"]))
            assert other.status_code == 200 and other.json()["call_key"] != queued["call_key"], name
            if ordinal == 0:
                blocked = F.approve_start(client, rid, queued["job_id"])
                assert blocked.status_code == 412, blocked.text
                assert blocked.json()["detail"]["reason_code"] == K.WORKER_VERSION_INVALID
    assert F.used(client, rid) == 0
    assert not any(e["type"] in {"budget_reserved", "job_dispatch_intent"} for e in F.events(root, rid))


# ----------------------------------------------------------------- the free preflight read
def test_preflight_read_answers_every_key_starts_nothing_and_shows_a_shortfall(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 preflight (public 1CLL, not experimental validation)", CLL, "public_1cll.cif")
    rid = world["rid"]
    before = (root / rid / "events.jsonl").read_bytes()
    response = client.get(f"/runs/{rid}/structure_repair/preflight", params={"structure": world["structure"]})
    assert response.status_code == 200
    body = response.json()
    assert tuple(sorted(body)) == tuple(sorted(PREFLIGHT_KEYS)) and body["schema"] == K.PREFLIGHT_SCHEMA
    assert body["starts_job"] is False and body["capability"] == jobs.capability()
    assert body["repairable"] is True and body["blockers"] == []
    # 1CLL (strip_all): side-chain atoms and the C-terminal OXT, from the file and the installed template.
    expected = F.oracle("1cll")
    assert expected["gap_lengths"] == {"A": []} and expected["terminal_oxt"] == 1
    assert body["expected_added_residues"] == expected["added_residues"] == 0
    assert body["expected_added_heavy_atoms"] == expected["added_atoms"] == 5
    assert [(d["residue"]["chain_auth"], d["residue"]["seq_auth"]) for d in body["defects"]["side_chain_residues"]] \
        == expected["side_chain_residues"]
    assert len(body["defects"]["terminal_oxt"]) == 1 and body["defects"]["gaps"] == []
    assert body["statements"] == [K.RP1, K.RP2, *([K.RP4] if expected["unobserved_tails"] else [])]
    assert body["admission"] == {"admitted": True, "error": None, "reason_code": None, "message": None,
                                 "detail": None}
    assert body["shortfall"] == {"expensive_calls": 0}
    assert set(body["budget"]) == {"expensive_calls", "wall_clock_s"}
    assert body["remaining"]["expensive_calls"] == (body["budget"]["expensive_calls"]["limit"] -
                                                    body["budget"]["expensive_calls"]["used"])
    real_snapshot = Run.budget_snapshot

    def exhausted(self):   # labelled internal hook: the run's expensive units used up
        snapshot = real_snapshot(self)
        snapshot["expensive_calls"]["used"] = snapshot["expensive_calls"]["limit"]
        return snapshot

    with monkeypatch.context() as patch:
        patch.setattr(Run, "budget_snapshot", exhausted)
        short = client.get(f"/runs/{rid}/structure_repair/preflight", params={"structure": world["structure"]}).json()
    assert short["shortfall"] == {"expensive_calls": 1} and short["admission"]["admitted"] is True
    for wrong in (world["source"], "obj://nope"):
        refused = client.get(f"/runs/{rid}/structure_repair/preflight", params={"structure": wrong})
        assert refused.status_code == 200 and refused.json()["admission"]["reason_code"] == "structure_invalid"
        assert refused.json()["defects"] is None and refused.json()["blockers"] == []
    assert client.get(f"/runs/{rid}/structure_repair/preflight").status_code == 422
    assert client.get(f"/runs/{rid}/structure_repair/preflight",
                      params={"structure": world["structure"], "x": 1}).status_code == 422
    assert (root / rid / "events.jsonl").read_bytes() == before
    assert not any(e["type"] == "job_submitted" for e in F.events(root, rid))


# ----------------------------------------------------------------- envelopes and unpublished records
def test_worker_error_envelope_is_closed(tmp_path):
    def read(value) -> dict:
        path = tmp_path / "error.json"
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        return jobs.worker_error(tmp_path)

    for code in K.FAILURE_REASON_CODES:
        good = {"reason_code": code, "message": "labelled", "detail": {"reason_code": code}}
        assert read(good) == {"error": jobs.FAILURE_CLASSES[code], "reason_code": code, "message": "labelled",
                              "detail": good["detail"]}
    assert set(jobs.FAILURE_CLASSES) == set(K.FAILURE_REASON_CODES)
    good = {"reason_code": "coordinates_changed", "message": "moved", "detail": {"reason_code": "coordinates_changed"}}
    fatal = {"error": "fatal", "message": "worker exit or invalid structure-repair error envelope"}
    for bad in ({**good, "reason_code": "not_a_reason"}, {**good, "extra": 1}, {**good, "message": ""},
                {**good, "detail": []}, {**good, "detail": {"reason_code": "engine_failed"}}, b"{not json",
                {**good, "message": "x" * 400}):
        assert read(bad) == fatal, bad
    (tmp_path / "error.json").unlink()
    assert jobs.worker_error(tmp_path) == fatal


def test_an_unpublished_record_never_reads(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    client = F.client(root, monkeypatch)
    world = F.world(client, "M29 forged record (public 1UBQ)", UBQ, "public_1ubq.cif")
    rid = world["rid"]
    run = api_module._run(rid)
    forged = run.store.put(K.KIND, K.SCHEMA, {key: None for key in K.RECORD_KEYS}).handle   # LABELLED forgery
    with pytest.raises(bundle.RepairEvidenceError):
        bundle.validated_result(run, forged)
    rows = client.get(f"/runs/{rid}/structure_repairs").json()
    assert rows["total"] == 1 and rows["rows"][0]["valid"] is False
    assert all(rows["rows"][0][key] is None for key in ("prepared_structure", "source_structure", "classes_applied",
                                                        "counts"))
    for sub in ("", "/atoms", "/structure"):
        response = client.get(f"/runs/{rid}/structure_repairs/{forged}{sub}")
        assert response.status_code == 422 and response.json()["detail"]["error"] == "method_evidence_invalid", sub
    for wrong in (world["structure"], None, f"obj://other_run/{K.KIND}/{'1' * 64}"):
        with pytest.raises(bundle.RepairEvidenceError):
            bundle.validated_result(run, wrong)
    assert reads.list_repairs(run, 0, 50)["rows"][0]["valid"] is False


def test_the_overlay_offers_meta_and_load_only(tmp_path, monkeypatch):
    """Spec 3.4: the pre-publication view gives ``meta`` and ``load`` and nothing else (no write, no event log)."""
    from mw import structure_repair as sr

    client = F.client(tmp_path / "runs", monkeypatch)
    world = F.world(client, "M29 overlay surface (public 1CLL)", CLL, "public_1cll.cif")
    run = api_module._run(world["rid"])
    inputs = sr.load_inputs(run.store, world["structure"])
    raw, record = sr.build_repaired(inputs, C.additions("1cll"))   # PDBFixer-measured rows (T1 fixture)
    objects = bundle.pending(run, inputs, raw, record)
    overlay = bundle.Overlay(run.store, objects)
    assert {name for name in dir(overlay) if not name.startswith("_")} == {"meta", "load"}
    for name in ("put", "events", "run_id", "store", "handles", "rebuild_from_events", "__dict__"):
        assert not hasattr(overlay, name), name
    with pytest.raises(AttributeError):
        overlay.events = run.store.events
    assert overlay.meta(objects.structure)["kind"] == K.STRUCTURE_KIND and overlay.load(objects.coordinates) == raw
    assert overlay.meta(world["structure"]) == run.store.meta(world["structure"])
    with pytest.raises(KeyError):
        run.store.meta(objects.structure)        # nothing reached the store


def test_a_list_without_repairs_needs_no_template(tmp_path, monkeypatch):
    """Spec 4.6: the list re-validates only existing records, so an unavailable template (LABELLED hook) does not
    refuse a run that has none."""
    from mw import structure_repair as sr

    client = F.client(tmp_path / "runs", monkeypatch)
    world = F.world(client, "M29 empty list (public 1UBQ)", UBQ, "public_1ubq.cif")

    def unavailable():
        raise sr._unavailable()

    with monkeypatch.context() as patch:
        patch.setattr(sr, "_templates", unavailable)
        listing = client.get(f"/runs/{world['rid']}/structure_repairs")
    assert listing.status_code == 200 and listing.json()["rows"] == [] and listing.json()["total"] == 0
