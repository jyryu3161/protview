"""M27 tool ``link_kinase_precedents`` (``kinase_precedents@1``): registration, the pre-check (pin -> 412, admission
order -> 422), the call key, storage, caps, the call-time record hash check and events-only recovery (spec 5).

Inputs: LABELLED SYNTHETIC precedent sets written by ``precedent_fixture.build_set`` under a temporary
``MW_PRECEDENT_REFERENCE_DIR`` (the T2 records by default), the LABELLED SYNTHETIC numbering-map dicts of
``fixtures/precedent/t2/numbering_maps.json`` stored with ``store.put`` against a real structure handle of the run
(public ``public_1mq4.cif``), and one real M15 ``map_residue_numbering`` result (1MQ4 + the M15 reference FIXTURE set).
The linking expectations come from the independent T2 oracle (``fixtures/precedent/t2/expected.json``), never from the
product function itself. No real kbase_kinase data, no network.
"""
from __future__ import annotations

import ast
import copy
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import precedent_fixture as PF
import pytest
from reference_fixture_set import build_fixture_set

from mw import kinase_precedents as kp
from mw import precedent_constants as K
from mw import precedent_snapshots as ps
from mw import reference_snapshots as m15_rs
from mw.core.errors import FailureClass, ToolFailure
from mw.runtime.orchestrator import replay
from mw.tools import kinase_precedents as tool_module
from mw.workspace import CONFIG, build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
CIF_1MQ4 = FIX / "public_1mq4.cif"
TOOL = K.TOOL
ORACLE = json.loads((PF.T2 / "expected.json").read_text(encoding="utf-8"))["cases"]
MAPS = json.loads((PF.T2 / "numbering_maps.json").read_text(encoding="utf-8"))
MAP_TYPE = ("residue_numbering_map", "residue_numbering_map@1")


# ------------------------------------------------------------------------------------------- helpers

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
def ref(refdir):
    PF.build_set(refdir)
    return refdir


def _registry():
    reg = build_registry()
    calls: list[dict] = []
    impl = reg.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    reg.impls[TOOL] = counted
    return reg, calls


def _run(tmp_path, name="run_precedent", dry_run=False):
    reg, calls = _registry()
    return new_run(tmp_path / "runs", run_id=name, dry_run=dry_run, registry=reg), calls


def _load(run, path: Path = CIF_1MQ4) -> str:
    return run.call("load_structure", {"source": str(path)}).handle


def _events(run, kind=None):
    return [e for e in run.events.read() if kind is None or e["type"] == kind]


def _created(run):
    return [e for e in _events(run, "object_created") if e["kind"] == K.KIND]


def _store_map(run, structure, name="main", label="", mutate=None) -> str:
    """Store the LABELLED SYNTHETIC T2 numbering-map dict ``name`` (hand-built, not an M15 result) for ``structure``."""
    content = copy.deepcopy(MAPS["maps"][name])
    content["structure"] = {"handle": structure, "structure_kind": "structure", "model_number": 1}
    content["fixture"] = f"SYNTHETIC constructed numbering map (not M15 output) {name}{label}"
    if mutate is not None:
        mutate(content)
    return run.store.put(*MAP_TYPE, content, produced_by="synthetic_fixture").handle


def _args(nmap, chains=None, include_flagged=False):
    return {"numbering_map": nmap, "chains": chains, "include_flagged": include_flagged}


def _without(content, *keys):
    return {k: v for k, v in content.items() if k not in keys}


def _rejected(run, calls, args, reason_code, cls=FailureClass.input_invalid):
    before = len(_created(run))
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.cls == cls, (caught.value.cls, caught.value.detail)
    assert caught.value.detail["reason_code"] == reason_code, caught.value.detail
    assert calls == [] and len(_created(run)) == before
    return caught.value


@pytest.fixture
def world(tmp_path, ref):
    run, calls = _run(tmp_path)
    structure = _load(run)
    return {"run": run, "calls": calls, "structure": structure, "ref": ref, "tmp": tmp_path,
            "main": _store_map(run, structure, "main"), "refs_only": _store_map(run, structure, "refs_only"),
            "unlinked": _store_map(run, structure, "unlinked")}


# ------------------------------------------------------------------------------------------- registration

def test_registered_as_a_cheap_l2_tool_with_a_precheck_everywhere():
    import yaml

    from mw.api import app as api_module

    reg = build_registry()
    spec = reg.specs[TOOL]
    assert TOOL in reg.impls and reg.prechecks[TOOL] is tool_module.precheck and TOOL not in reg.unavailable
    assert (spec.level, spec.version, spec.cost_class, spec.emits, spec.idempotent) == ("L2", "1", "cheap", K.KIND,
                                                                                          True)
    assert spec.accepts == {"numbering_map": ["residue_numbering_map"]}
    assert spec.params == {"chains": {"default": None}, "include_flagged": {"type": "bool", "required": True}}
    yaml_spec = next(t for t in yaml.safe_load((CONFIG / "tools.yaml").read_text())["tools"] if t["name"] == TOOL)
    assert yaml_spec["cost_class"] == "cheap"
    assert TOOL in api_module.SUPPORTED_TOOLS and TOOL in api_module.REGISTRY.impls
    assert api_module.REGISTRY.prechecks[TOOL] is tool_module.precheck
    assert (K.RESULT_TOO_LARGE_REASON, K.RESULT_INVALID_REASON) == ("result_too_large", "result_invalid")


# ------------------------------------------------------------------------------------------- result

@pytest.mark.parametrize("name", sorted(ORACLE))
def test_stored_result_matches_the_independent_oracle(world, name):
    case = ORACLE[name]
    run, calls = world["run"], world["calls"]
    nmap = world[case["map"]]
    out = run.call(TOOL, _args(nmap, case["chains"], case["include_flagged"]))
    assert out.kind == K.KIND and out.schema_ == K.SCHEMA and len(calls) == 1
    content = run.store.load(out.handle)
    assert kp.validated_result(copy.deepcopy(content)) == content
    skip = ("precedent_set", "structure", "numbering_map")
    assert K.canonical_json(_without(content, *skip)) == K.canonical_json(_without(case["result"], *skip)), name
    assert content["structure"] == {"handle": world["structure"], "structure_kind": "structure", "model_number": 1}
    assert content["numbering_map"] == {"handle": nmap}
    assert content["precedent_set"] == kp.precedent_set_record(ps.pin_active_set())
    meta = run.store.meta(out.handle)
    assert meta["null_result"] is content["null_result"] is out.null_result
    assert meta["summary"] == out.summary == {
        "numbering_map": nmap, "pdb_id": content["pdb_id"], "chains": [c["chain_auth"] for c in content["chains"]],
        "include_flagged": case["include_flagged"], "set_hash": content["precedent_set"]["set_hash"],
        "linked_chains": content["counts"]["linked_chains"]}
    text = K.canonical_json(content).decode()
    assert "call_" not in text and run.run_id + "/" + K.KIND not in text   # no call ID, no own handle


def test_the_tool_builds_with_exactly_the_pure_function(world):
    run = world["run"]
    out = run.call(TOOL, _args(world["main"], ["B", "C"], True))
    pinned, index = kp.pin_and_index()
    expected = kp.build_kinase_precedents(pinned=pinned, index=index, numbering_map=run.store.load(world["main"]),
                                          numbering_map_handle=world["main"], chains=["B", "C"], include_flagged=True)
    assert run.store.load(out.handle) == expected


def test_real_m15_numbering_map_links_by_its_mapped_accession(tmp_path, refdir, monkeypatch):
    """A real M15 result for public 1MQ4 (FIXTURE M15 set) has the fields the linking reads. The precedent set adds
    SYNTHETIC records and a SYNTHETIC reference for the map's accession O14965 (made-up values, not kbase data)."""
    m15 = tmp_path / "m15_reference"
    m15.mkdir()
    monkeypatch.setenv(m15_rs.ENV_VAR, str(m15))
    build_fixture_set(m15)
    records = PF.t2_records()
    moves = records["moves"] + [PF.make_move("MOVE-0300", uniprot="O14965", variant="SYN-V1"),
                                PF.make_move("MOVE-0301", uniprot="O14965", resolution_basis="alias")]
    flagged = records["moves_flagged"] + [PF.make_move("MOVE-0302", uniprot="O14965")]
    references = records["references"] + [PF.make_reference("REF-SYN-0300", "O14965")]
    PF.build_set(refdir, moves=moves, moves_flagged=flagged, references=references)
    run, calls = _run(tmp_path)
    structure = _load(run)
    mapped = run.call("map_residue_numbering", {"structure": structure, "pdb_id": "1MQ4",
                                                "chains": [{"chain_auth": "A", "uniprot_accession": "O14965"}]})
    nmap = run.store.load(mapped.handle)
    assert kp.numbering_map_shape_ok(nmap)
    shutil.rmtree(m15)   # the M27 tool never reads the M15 reference folder
    out = run.call(TOOL, _args(mapped.handle))
    content = run.store.load(out.handle)
    (chain,) = content["chains"]
    (m15_chain,) = nmap["chains"]
    counts = m15_chain["counts"]
    assert (chain["status"], chain["reason"], chain["accession"], chain["accessions"]) == (
        "linked", None, "O14965", ["O14965"])
    assert chain["mapped_residue_count"] == counts["mapped"] >= 1
    assert chain["total_residue_count"] == counts["mapped"] + counts["unmapped"] + counts["conflict"]
    assert (chain["cross_check"], chain["cross_check_absent_reason"]) == (
        m15_chain["cross_check"], m15_chain["cross_check_absent_reason"])
    (target,) = content["targets"]
    assert (target["accession"], target["chains"], target["status"]) == ("O14965", ["A"], "precedents_found")
    assert [i["record"]["move_id"] for i in target["records"]] == ["MOVE-0300", "MOVE-0301"]
    assert (target["counts"]["moves"], target["counts"]["moves_flagged"], target["excluded_flagged"]) == (2, None, 1)
    assert [r["ref_id"] for r in target["references"]] == ["REF-SYN-0300"]
    assert content["structure"]["handle"] == structure and content["pdb_id"] == "1MQ4" and len(calls) == 1


# ------------------------------------------------------------------------------------------- admission (5.2)

OTHER_RUN_MAP = "obj://run_other/residue_numbering_map/" + "b" * 64
UNKNOWN_MAP = "obj://run_precedent/residue_numbering_map/" + "c" * 64


def _w(world, drop=(), **changes):
    args = _args(world["main"])
    args.update(changes)
    for key in drop:
        args.pop(key)
    return args


def _damaged(world, mutate):
    return _store_map(world["run"], world["structure"], "main", " (SYNTHETIC damaged)", mutate)


SINGLE = [
    ("unknown_field", lambda w: _w(w, extra=1)),
    ("unknown_field", lambda w: _w(w, structure=w["structure"])),
    ("numbering_map_invalid", lambda w: _w(w, drop=("numbering_map",))),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=None)),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=7)),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map="not-a-handle")),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=OTHER_RUN_MAP)),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=UNKNOWN_MAP)),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=w["structure"])),          # another kind
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=_damaged(w, lambda m: m.pop("pdb_id")))),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=_damaged(w, lambda m: m["chains"][0].pop("counts")))),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=_damaged(
        w, lambda m: m["rows"][0].update(uniprot_accession=None)))),                  # a mapped row without accession
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=_damaged(w, lambda m: m.update(chains=[], rows=[])))),
    ("include_flagged_invalid", lambda w: _w(w, drop=("include_flagged",))),
    ("include_flagged_invalid", lambda w: _w(w, include_flagged=None)),
    ("include_flagged_invalid", lambda w: _w(w, include_flagged="true")),
    ("include_flagged_invalid", lambda w: _w(w, include_flagged=1)),
    ("include_flagged_invalid", lambda w: _w(w, include_flagged=0)),
    ("chains_invalid", lambda w: _w(w, chains="A")),
    ("chains_invalid", lambda w: _w(w, chains=[])),
    ("chains_invalid", lambda w: _w(w, chains=[5])),
    ("chains_invalid", lambda w: _w(w, chains=[None])),
    ("chains_invalid", lambda w: _w(w, chains=["A", "A"])),
    ("chains_invalid", lambda w: _w(w, chains={"A": 1})),
    ("chains_invalid", lambda w: _w(w, chains=True)),
    ("chain_not_in_map", lambda w: _w(w, chains=["Z"])),
    ("chain_not_in_map", lambda w: _w(w, chains=["a"])),                                # case matters
    ("chain_not_in_map", lambda w: _w(w, chains=[""])),
    ("chain_not_in_map", lambda w: _w(w, chains=["A", "Z"])),
]


@pytest.mark.parametrize("reason, make", SINGLE, ids=[f"{i}-{r}" for i, (r, _) in enumerate(SINGLE)])
def test_each_admission_reason_refuses_before_the_implementation(world, reason, make):
    failure = _rejected(world["run"], world["calls"], make(world), reason)
    assert failure.message


def test_the_five_reasons_are_the_closed_tuple():
    assert {reason for reason, _ in SINGLE} == set(K.ADMISSION_REASON_CODES)
    assert K.ADMISSION_REASON_CODES == ("unknown_field", "numbering_map_invalid", "include_flagged_invalid",
                                        "chains_invalid", "chain_not_in_map")


# Each payload fails the named check AND every later one it can; the earliest one in spec order is reported.
PAIRS = [
    ("unknown_field", lambda w: _w(w, extra=1, numbering_map=7, include_flagged="x", chains=[])),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=w["structure"], include_flagged="x", chains=["Z", "Z"])),
    ("include_flagged_invalid", lambda w: _w(w, include_flagged=None, chains=[])),
    ("chains_invalid", lambda w: _w(w, chains=["Z", "Z"])),   # an unknown chain repeated: the list check comes first
    ("chain_not_in_map", lambda w: _w(w, chains=["Z"])),
]


@pytest.mark.parametrize("reason, make", PAIRS, ids=[r for r, _ in PAIRS])
def test_admission_order_is_the_spec_order(world, reason, make):
    _rejected(world["run"], world["calls"], make(world), reason)


def test_chain_level_refusals_name_the_chain(world):
    failure = _rejected(world["run"], world["calls"], _w(world, chains=["A", "Z"]), "chain_not_in_map")
    assert failure.detail == {"reason_code": "chain_not_in_map", "chain_auth": "Z"}
    failure = _rejected(world["run"], world["calls"], _w(world, chains=["B", "B"]), "chains_invalid")
    assert failure.detail == {"reason_code": "chains_invalid", "chain_auth": "B"}


def test_deeply_nested_map_object_is_numbering_map_invalid_not_a_crash(world):
    """SYNTHETIC damaged map object: raw JSON nested past the recursion limit (``store.load`` raises RecursionError)."""
    run = world["run"]
    depth = 100000
    deep = run.store.put(*MAP_TYPE, b"[" * depth + b"]" * depth, produced_by="synthetic_fixture").handle
    with pytest.raises(RecursionError):
        run.store.load(deep)
    _rejected(run, world["calls"], _w(world, numbering_map=deep), "numbering_map_invalid")


def test_chains_null_absent_full_list_and_request_order_are_one_call(world):
    run, calls = world["run"], world["calls"]
    first = run.call(TOOL, _args(world["main"]))
    assert calls[-1] == {"numbering_map": world["main"], "chains": ["A", "B", "C", "D", "E"], "include_flagged": False}
    for args in (_w(world, drop=("chains",)), _w(world, chains=["A", "B", "C", "D", "E"]),
                 _w(world, chains=["E", "D", "C", "B", "A"]), _w(world, chains=["C", "A", "B", "D", "E"])):
        assert run.call(TOOL, args).handle == first.handle
    assert len(calls) == 1
    hits = [e for e in _events(run, "cache_hit") if e["tool"] == TOOL]
    assert len(hits) == 4 and {h["output"]["handle"] for h in hits} == {first.handle}
    subset = run.call(TOOL, _w(world, chains=["C", "B"]))
    assert run.call(TOOL, _w(world, chains=["B", "C"])).handle == subset.handle != first.handle
    assert calls[-1]["chains"] == ["B", "C"] and len(calls) == 2
    assert [c["chain_auth"] for c in run.store.load(subset.handle)["chains"]] == ["C", "B"]   # the map's order
    flagged = run.call(TOOL, _w(world, include_flagged=True))
    assert flagged.handle not in (first.handle, subset.handle) and len(calls) == 3


def test_argument_repair_path_runs_the_same_precheck(world):
    run, calls = world["run"], world["calls"]
    with pytest.raises(ToolFailure):
        run.call(TOOL, _w(world, chains=["Z"]))
    failed = _events(run, "proposal_rejected")[-1]["proposal_id"]
    with pytest.raises(ToolFailure) as caught:
        run.repair_call(failed, _w(world, include_flagged="no"))
    assert caught.value.detail["reason_code"] == "include_flagged_invalid" and calls == []


# ------------------------------------------------------------------------------------------- 412 before the cache

def test_not_installed_is_a_precondition_before_any_admission_check(tmp_path, refdir):
    run, calls = _run(tmp_path)
    nmap = _store_map(run, _load(run))
    for args in (_args(nmap), {**_args(nmap), "extra": 1}, {}, {"numbering_map": 5}):
        failure = _rejected(run, calls, args, "not_installed", FailureClass.precondition)
        assert failure.message == K.SNAPSHOT_REASONS["not_installed"]
        assert "scripts/import_precedent_snapshots.py" in failure.message
        assert failure.detail == {"reason_code": "not_installed"}


def test_snapshot_invalid_and_not_installed_come_before_the_cache_lookup(world):
    run, calls, ref = world["run"], world["calls"], world["ref"]
    first = run.call(TOOL, _args(world["main"]))
    assert len(calls) == 1
    hits = len(_events(run, "cache_hit"))
    moves = next(ref.glob("sets/*/files/dist/moves.jsonl"))
    original = moves.read_bytes()
    moves.write_bytes(original.replace(b"SYNTHETIC", b"Synthetic", 1))   # same size, other hash
    assert moves.read_bytes() != original
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    calls.clear()
    failure = _rejected(run, calls, _args(world["main"]), "snapshot_invalid", FailureClass.precondition)
    assert failure.message == K.SNAPSHOT_REASONS["snapshot_invalid"]
    moves.write_bytes(original)
    shutil.rmtree(ref)
    _rejected(run, calls, _args(world["main"]), "not_installed", FailureClass.precondition)
    assert len(_events(run, "cache_hit")) == hits     # a refused call never reaches the completed-call lookup
    assert [e["output"]["handle"] for e in _events(run, "tool_succeeded") if e["tool"] == TOOL] == [first.handle]


def test_records_outside_the_format_are_snapshot_invalid(tmp_path, refdir):
    """SYNTHETIC set whose files match the manifest hashes but whose record leaves the spec 3.4 format."""
    bad = PF.make_move("MOVE-0001", review_status="reviewed")     # hash recomputed: only the format is wrong
    PF.build_set(refdir, moves=[bad], moves_flagged=[])
    assert ps.capability()["available"] is True                     # the file hashes alone are fine
    run, calls = _run(tmp_path)
    _rejected(run, calls, _args(_store_map(run, _load(run))), "snapshot_invalid", FailureClass.precondition)


def test_record_hash_mismatch_at_call_time_is_412_and_stores_nothing(world):
    run, calls = world["run"], world["calls"]
    _pinned, index = kp.pin_and_index()
    for _file, record in index.by_uniprot["P0SYN1"]:
        if record["move_id"] == "MOVE-0007":
            record["observation"]["text"] = "SYNTHETIC changed in memory after the set was read"
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, _args(world["main"]))
    assert caught.value.cls == FailureClass.precondition
    assert caught.value.detail == {"reason_code": "snapshot_invalid"}
    assert caught.value.message == K.SNAPSHOT_REASONS["snapshot_invalid"]
    assert len(calls) == 1 and _created(run) == []
    (failed,) = [e for e in _events(run, "tool_failed") if e["tool"] == TOOL]
    assert failed["error"] == "precondition"
    out = run.call(TOOL, _args(world["main"]))           # the damaged index was dropped; the files are intact
    assert out.kind == K.KIND and len(calls) == 2 and len(_created(run)) == 1


# ------------------------------------------------------------------------------------------- call key

def test_call_key_adds_the_pinned_set_hash_and_method_version(world):
    run = world["run"]
    normalized, bound = tool_module.precheck(run.store, _args(world["main"], ["C", "A"], True))
    assert normalized == {"numbering_map": world["main"], "chains": ["A", "C"], "include_flagged": True}
    assert bound.key_fields == {"_precedent_set_hash": ps.pin_active_set().set_hash,
                                "_method_version": "mw.kinase_precedents/v1"}
    key = run._key(TOOL, "1", normalized, None, None, bound)
    other = SimpleNamespace(key_fields={**bound.key_fields, "_method_version": "mw.kinase_precedents/v2"})
    assert key != run._key(TOOL, "1", normalized, None, None, other)
    assert key != run._key(TOOL, "1", normalized, None, None, None)


def test_same_input_same_set_is_a_cache_hit_and_another_set_another_handle(world):
    run, calls, ref = world["run"], world["calls"], world["ref"]
    first = run.call(TOOL, _args(world["main"]))
    again = run.call(TOOL, _args(world["main"]))
    assert again.handle == first.handle and len(calls) == 1
    (hit,) = [e for e in _events(run, "cache_hit") if e["tool"] == TOOL]
    assert hit["output"]["handle"] == first.handle
    first_set = ps.pin_active_set().set_hash
    second_set = PF.build_set(ref, imported_at="2026-10-10T00:00:05Z")      # same records, another set
    other = run.call(TOOL, _args(world["main"]))
    assert len(calls) == 2 and other.handle != first.handle
    content = run.store.load(other.handle)
    assert content["precedent_set"]["set_hash"] == second_set != first_set
    assert _without(content, "precedent_set") == _without(run.store.load(first.handle), "precedent_set")
    keys = [e["key"] for e in _events(run, "tool_succeeded") if e["tool"] == TOOL]
    assert len(set(keys)) == 2
    PF.activate(ref, first_set)
    back = run.call(TOOL, _args(world["main"]))
    assert back.handle == first.handle and len(calls) == 2


def test_the_implementation_uses_the_set_the_precheck_pinned(world):
    run, calls, ref = world["run"], world["calls"], world["ref"]
    pinned_hash = ps.pin_active_set().set_hash
    later = PF.build_set(ref, imported_at="2026-10-10T00:00:06Z", activate_set=False)
    real = tool_module.precheck

    def swap_after_precheck(store, args, bound=None):
        result = real(store, args, bound)
        PF.activate(ref, later)        # a concurrent import lands between the pre-check and the implementation
        return result

    run.registry.prechecks[TOOL] = swap_after_precheck
    out = run.call(TOOL, _args(world["main"]))
    assert run.store.load(out.handle)["precedent_set"]["set_hash"] == pinned_hash != later
    assert len(calls) == 1

    def uninstall_after_precheck(store, args, bound=None):
        result = real(store, args, bound)
        (ref / K.ACTIVE_NAME).unlink(missing_ok=True)   # the set disappears before the implementation runs
        return result

    run.registry.prechecks[TOOL] = uninstall_after_precheck
    gone = run.call(TOOL, _args(world["main"], ["A"]))
    assert run.store.load(gone.handle)["precedent_set"]["set_hash"] == later and len(calls) == 2


# ------------------------------------------------------------------------------------------- dry run, caps, storage

def test_dry_run_executes_the_cheap_tool(tmp_path, ref):
    run, calls = _run(tmp_path, name="run_dry", dry_run=True)
    out = run.call(TOOL, _args(_store_map(run, _load(run))))
    assert out.kind == K.KIND and len(calls) == 1
    assert not [e for e in _events(run, "tool_called") if e.get("plan_only")]
    wet, _ = _run(tmp_path, name="run_wet")
    wet_out = wet.call(TOOL, _args(_store_map(wet, _load(wet))))
    skip = ("structure", "numbering_map")
    assert _without(run.store.load(out.handle), *skip) == _without(wet.store.load(wet_out.handle), *skip)


def test_a_result_that_does_not_validate_is_never_stored(world, monkeypatch):
    run, calls = world["run"], world["calls"]
    real = kp.build_kinase_precedents

    def tampered(**kwargs):
        content = real(**kwargs)
        content["counts"]["chains"] = 9     # SYNTHETIC defect: counts disagree with the chains
        return content

    monkeypatch.setattr(kp, "build_kinase_precedents", tampered)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, _args(world["main"]))
    assert caught.value.cls == FailureClass.input_invalid
    assert caught.value.detail == {"reason_code": "result_invalid"}
    assert len(calls) == 1 and _created(run) == []


def test_size_cap_is_resource_exceeded_and_stores_nothing(world, monkeypatch):
    run, calls = world["run"], world["calls"]
    monkeypatch.setattr(K, "MAX_RESULT_BYTES", 4096)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, _args(world["main"], include_flagged=True))
    failure = caught.value
    assert failure.cls == FailureClass.resource_exceeded
    detail = failure.detail
    assert set(detail) == {"reason_code", "limit", "actual", "size_without_flagged", "target_sizes"}
    assert detail["reason_code"] == "result_too_large" and detail["limit"] == 4096 and detail["actual"] > 4096
    assert type(detail["size_without_flagged"]) is int
    assert [t["accession"] for t in detail["target_sizes"]] == ["P0SYN1", "Q0SYN2"]
    assert "include_flagged" in failure.message
    assert len(calls) == 1 and _created(run) == []
    (failed,) = [e for e in _events(run, "tool_failed") if e["tool"] == TOOL]
    assert failed["error"] == "resource_exceeded" and failed["detail"]["reason_code"] == "result_too_large"
    monkeypatch.undo()
    monkeypatch.setenv(K.ENV_VAR, str(world["ref"]))
    assert run.call(TOOL, _args(world["main"], include_flagged=True)).kind == K.KIND   # nothing was cached as done


def test_real_size_cap_without_patching(tmp_path, refdir):
    """SYNTHETIC filler records (~21 KB each) put one target above 1 MiB only when moves_flagged is included."""
    def big(move_id, uniprot):
        return PF.make_move(move_id, uniprot=uniprot, observation_text="SYNTHETIC filler " * 1250)

    PF.build_set(refdir, moves=[big(f"MOVE-{1000 + i}", "P0SYN1") for i in range(28)],
                 moves_flagged=[big(f"MOVE-{3000 + i}", "P0SYN1") for i in range(28)])
    run, calls = _run(tmp_path)
    nmap = _store_map(run, _load(run))
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, _args(nmap, ["A"], True))
    assert K.MAX_RESULT_BYTES == 1024 * 1024
    detail = caught.value.detail
    assert caught.value.cls == FailureClass.resource_exceeded and detail["reason_code"] == "result_too_large"
    assert detail["limit"] == K.MAX_RESULT_BYTES < detail["actual"]
    assert detail["size_without_flagged"] <= K.MAX_RESULT_BYTES
    assert detail["target_sizes"] == [{"accession": "P0SYN1", "chains": ["A"], "bytes": detail["actual"]}]
    assert len(calls) == 1 and _created(run) == []
    assert run.call(TOOL, _args(nmap, ["A"], False)).kind == K.KIND   # the hint holds: without flagged it fits
    assert len(calls) == 2 and len(_created(run)) == 1


# ------------------------------------------------------------------------------------------- events-only recovery

def test_events_only_recovery_without_the_reference_folder(world):
    run, ref = world["run"], world["ref"]
    out = run.call(TOOL, _args(world["main"], include_flagged=True))
    sha = out.handle.rsplit("/", 1)[1]
    raw = (run.run_dir / "objects" / f"{sha}.json").read_bytes()
    handles = run.store.handles()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    shutil.rmtree(ref)
    ps._VERIFIED.clear()
    kp.clear_index_cache()
    assert kp.capability()["available"] is False
    reopened, calls = _run(world["tmp"])
    assert (reopened.run_dir / "objects" / f"{sha}.json").read_bytes() == raw
    assert reopened.store.handles() == handles and calls == []
    assert reopened.store.meta(out.handle)["summary"] == out.summary
    assert kp.validated_result(reopened.store.load(out.handle)) == json.loads(raw)
    target = world["tmp"] / "replay" / run.run_id
    replayed = replay(run.run_dir / "events.jsonl", target, build_registry(), run.run_id)
    assert replayed == handles
    assert (target / "objects" / f"{sha}.json").read_bytes() == raw


# ------------------------------------------------------------------------------------------- module boundary

NEW_MODULES = [Path(tool_module.__file__), Path(kp.__file__).parent / "kinase_precedents_reads.py"]
NETWORK = {"socket", "urllib", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp", "websockets"}
CHEMISTRY = {"rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm", "gemmi"}
OTHER_FAMILIES = {"reference_snapshots", "numbering_reads", "sifts_mapping", "klifs_numbering", "residue_numbering",
                  "numbering", "reaction_snapshots", "reaction_knowledge", "reaction_knowledge_reads", "jev_sends",
                  "egress"}


def _imports(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text())
    absolute, relative = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                absolute.add(node.module or "")
            else:
                base = node.module or ""
                relative.add(base)
                relative.update(f"{base}.{alias.name}".strip(".") for alias in node.names)
    return absolute, relative


@pytest.mark.parametrize("path", NEW_MODULES, ids=lambda p: p.name)
def test_new_modules_never_network_spawn_or_read_other_reference_families(path):
    source = path.read_text()
    absolute, relative = _imports(path)
    tops = {name.split(".")[0] for name in absolute}
    assert not tops & (NETWORK | CHEMISTRY | {"subprocess", "multiprocessing"})
    assert tops - {"__future__"} <= set(sys.stdlib_module_names)
    assert not {name.split(".")[-1] for name in relative} & OTHER_FAMILIES
    for banned in ("raise_limits", "limit_approval", "kbase_kinase/", "../kbase", ".git", "request_science"):
        assert banned not in source
