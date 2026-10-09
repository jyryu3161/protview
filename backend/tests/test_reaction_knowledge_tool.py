"""M26 tool ``link_reaction_knowledge`` (``reaction_knowledge@1``): registration, the pre-check (pin -> 412, admission
order -> 422), the call key, storage, caps and events-only recovery.

Inputs: the LABELLED SYNTHETIC structures of ``fixtures/reaction/t2/`` (``structure_alpha.cif`` = 0SY1,
``structure_beta.pdb`` = 0SY2), the public ``public_1ubq.cif`` and ``public_1mq4.cif``, synthetic reaction reference
sets written by ``reaction_fixture.build_set`` under a temporary ``MW_REACTION_REFERENCE_DIR``, LABELLED SYNTHETIC
numbering-map objects stored with ``store.put`` (``_synthetic_map``) and one real M15 ``map_residue_numbering`` result
(1MQ4 + the M15 reference FIXTURE set). The M-CSA expectations come from the independent T2 oracle
(``fixtures/reaction/t2/expected.json``), never from the product function itself.
"""
from __future__ import annotations

import ast
import copy
import json
import shutil
from pathlib import Path

import pytest
import reaction_fixture as RF
from reference_fixture_set import build_fixture_set

from mw import reaction_knowledge as rk
from mw import reaction_knowledge_constants as K
from mw import reaction_snapshots as rs
from mw import reference_snapshots as m15_rs
from mw.core.errors import FailureClass, ToolFailure
from mw.runtime.orchestrator import replay
from mw.tools import reaction_knowledge as tool_module
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import CONFIG, build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
ALPHA = RF.T2 / "structure_alpha.cif"
BETA = RF.T2 / "structure_beta.pdb"
CIF_1UBQ = FIX / "public_1ubq.cif"
CIF_1MQ4 = FIX / "public_1mq4.cif"
TOOL = K.TOOL
ORACLE = json.loads((RF.T2 / "expected.json").read_text(encoding="utf-8"))["cases"]


# ------------------------------------------------------------------------------------------- helpers

@pytest.fixture
def refdir(tmp_path, monkeypatch):
    root = tmp_path / "reaction_reference"
    (root / "sets").mkdir(parents=True)
    monkeypatch.setenv(K.ENV_VAR, str(root))
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    yield root
    rs._VERIFIED.clear()
    rk.clear_index_cache()


@pytest.fixture
def ref(refdir):
    RF.build_set(refdir)
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


def _run(tmp_path, name="run_reaction", dry_run=False):
    reg, calls = _registry()
    return new_run(tmp_path / "runs", run_id=name, dry_run=dry_run, registry=reg), calls


def _load(run, path: Path) -> str:
    return run.call("load_structure", {"source": str(path)}).handle


def _prepare(run, structure: str) -> str:
    return run.call("prepare_structure", {"structure": structure, "altloc": "first", "waters": "keep_all",
                                          "hydrogens": "keep", "missing_residues": "leave_gaps",
                                          "symmetry_mates": "ignore"}).handle


def _events(run, kind=None):
    return [e for e in run.events.read() if kind is None or e["type"] == kind]


def _created(run):
    return [e for e in _events(run, "object_created") if e["kind"] == K.KIND]


def _args(structure, chains=(("A", "Q0SYN1"), ("B", None)), pdb_id="0SY1", numbering_map=None):
    return {"structure": structure, "pdb_id": pdb_id,
            "chains": [{"chain_auth": c, "uniprot_accession": a} for c, a in chains], "numbering_map": numbering_map}


def _residues(run, structure):
    return rk.chain_polymer_residues(_parse(ToolContext(store=run.store, call_id="test"), structure))


def _map_row(residue, status, accession=None, position=None, letter=None, match=None):
    return {"residue": dict(residue), "status": status, "uniprot_accession": accession,
            "uniprot_position": position, "uniprot_residue": letter, "residue_match": match, "klifs_index": None,
            "klifs_label": None, "klifs_match": None,
            "conflict_reason": "positions_differ" if status == "conflict" else None, "sifts": None,
            "alignment": None}


def _synthetic_map(run, structure, *, pdb_id="0SY1", structure_handle=None):
    """LABELLED SYNTHETIC ``residue_numbering_map@1`` object (hand-built rows, not an M15 result) for ``structure``:
    chain A positions 10, 12, 13 (two rows at 13), an unmapped and a conflict row; chain B residue 1 at 10."""
    residues = _residues(run, structure)

    def res(chain, seq_auth):
        (found,) = [r for r in residues[chain] if r["seq_auth"] == seq_auth and r["icode"] == ""]
        return found

    rows = [_map_row(res("A", 10), "mapped", "Q0SYN1", 10, "D", True),
            _map_row(res("A", 12), "mapped", "Q0SYN1", 12, "H", False),
            _map_row(res("A", 13), "mapped", "Q0SYN1", 13, "H", False),
            _map_row(res("A", 14), "mapped", "Q0SYN1", 13, "C", False),
            _map_row(res("A", 15), "unmapped"),
            _map_row(res("A", 16), "conflict"),
            _map_row(res("B", 1), "mapped", "Q0SYN1", 10, "A", False)]
    model_number = residues["A"][0]["model_number"]
    content = {"schema": "residue_numbering_map@1", "method_version": "mw.residue_numbering/v1",
               "structure": {"handle": structure_handle or structure, "structure_kind": "structure",
                             "model_number": model_number},
               "pdb_id": pdb_id,
               "chains": [{"chain_auth": c, "requested_uniprot_accession": None,
                           "methods_run": ["local_alignment"]} for c in ("A", "B")],
               "rows": rows, "null_result": False, "fixture": "SYNTHETIC constructed numbering map (not M15 output)"}
    return run.store.put("residue_numbering_map", "residue_numbering_map@1", content,
                         produced_by="synthetic_fixture").handle


def _rejected(run, calls, args, reason_code, cls=FailureClass.input_invalid):
    before = len(_created(run))
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.cls == cls, (caught.value.cls, caught.value.detail)
    assert caught.value.detail["reason_code"] == reason_code, caught.value.detail
    assert calls == [] and len(_created(run)) == before
    return caught.value


# ------------------------------------------------------------------------------------------- registration

def test_registered_as_a_cheap_l2_tool_with_a_precheck_everywhere():
    import yaml

    from mw.api import app as api_module

    reg = build_registry()
    spec = reg.specs[TOOL]
    assert TOOL in reg.impls and reg.prechecks[TOOL] is tool_module.precheck and TOOL not in reg.unavailable
    assert (spec.level, spec.cost_class, spec.emits, spec.idempotent) == ("L2", "cheap", K.KIND, True)
    assert spec.accepts == {"structure": ["structure", "prepared_structure"]}
    assert set(spec.params) == {"pdb_id", "chains", "numbering_map"}
    assert spec.params["pdb_id"] == {"default": None} and spec.params["numbering_map"] == {"default": None}
    assert spec.params["chains"] == {"type": "list", "required": True}
    yaml_spec = next(t for t in yaml.safe_load((CONFIG / "tools.yaml").read_text())["tools"] if t["name"] == TOOL)
    assert yaml_spec["cost_class"] == "cheap"
    assert TOOL in api_module.SUPPORTED_TOOLS and TOOL in api_module.REGISTRY.impls
    assert (K.RESULT_TOO_LARGE_REASON, K.TOO_MANY_LINKS_REASON) == ("result_too_large", "too_many_links")


# ------------------------------------------------------------------------------------------- result

def test_result_is_stored_validated_and_matches_the_independent_oracle(tmp_path, ref):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    nmap = _synthetic_map(run, structure)
    out = run.call(TOOL, _args(structure, numbering_map=nmap))
    assert out.kind == K.KIND and out.schema_ == K.SCHEMA and len(calls) == 1
    content = run.store.load(out.handle)
    assert rk.validated_result(copy.deepcopy(content)) == content
    a, b = content["chains"]
    assert a["mcsa"] == ORACLE["alpha_A"]["mcsa"]                     # independent oracle (T2)
    assert b["mcsa"] == ORACLE["alpha_B_chain_not_listed"]["mcsa"]
    assert content["structure"] == {"handle": structure, "structure_kind": "structure", "model_number": 2}
    assert content["pdb_id"] == "0SY1" and content["numbering_map"] == {"handle": nmap, "pdb_id": "0SY1"}
    assert (a["accession"], a["accession_source"]) == ("Q0SYN1", "user")
    assert (b["accession"], b["accession_source"]) == ("Q0SYN1", "numbering_map")
    assert a["uniprot"]["linked_via"] == "numbering_map" and b["uniprot"]["linked_via"] == "numbering_map"
    assert content["snapshot_set"]["set_hash"] == rs.pin_active_set().set_hash
    assert content["limitations"] == list(K.LIMITATIONS) and content["null_result"] is False
    meta = run.store.meta(out.handle)
    assert meta["null_result"] is False and meta["summary"] == out.summary
    assert out.summary == {"structure": structure, "pdb_id": "0SY1", "chains": ["A", "B"],
                           "set_hash": content["snapshot_set"]["set_hash"], "covered_chains": 1}
    text = K.canonical_json(content).decode()
    assert "call_" not in text and run.run_id + "/" + K.KIND not in text   # no call ID, no own handle


def test_the_tool_builds_with_exactly_the_pure_function(tmp_path, ref):
    run, _ = _run(tmp_path)
    structure = _load(run, BETA)
    out = run.call(TOOL, _args(structure, chains=(("A", None), ("B", "Q0SYN5")), pdb_id="0sy2"))
    pinned, index = rk.pin_and_index()
    st = _parse(ToolContext(store=run.store, call_id="test"), structure)
    expected = rk.build_reaction_knowledge(
        pinned=pinned, index=index, structure_handle=structure, structure_kind="structure",
        model_number=st[0].num, pdb_id="0SY2", chains=[{"chain_auth": "A", "uniprot_accession": None},
                                                       {"chain_auth": "B", "uniprot_accession": "Q0SYN5"}],
        chain_residues=rk.chain_polymer_residues(st))
    assert run.store.load(out.handle) == expected
    content = run.store.load(out.handle)
    assert content["chains"][0]["mcsa"] == ORACLE["beta_A_null_labels"]["mcsa"]
    assert content["chains"][1]["mcsa"] == ORACLE["beta_B_null_labels"]["mcsa"]


def test_prepared_structure_and_request_chain_order(tmp_path, ref):
    run, _ = _run(tmp_path)
    prepared = _prepare(run, _load(run, BETA))
    out = run.call(TOOL, _args(prepared, chains=(("B", None), ("A", None)), pdb_id="0SY2"))
    content = run.store.load(out.handle)
    assert content["structure"]["structure_kind"] == "prepared_structure"
    assert [c["chain_auth"] for c in content["chains"]] == ["B", "A"]   # request order, not file order


def test_public_structure_not_in_the_snapshot_is_a_valid_empty_result(tmp_path, ref):
    run, _ = _run(tmp_path)
    structure = _load(run, CIF_1UBQ)
    out = run.call(TOOL, _args(structure, chains=(("A", None),), pdb_id="1ubq"))
    content = run.store.load(out.handle)
    (chain,) = content["chains"]
    assert chain["mcsa"] == {"status": "checked", "reason": None, "coverage": "pdb_not_in_snapshot",
                             "entries": None, "rows": None, "counts": None}
    assert chain["uniprot"]["status"] == "not_checked" and chain["reactions"]["status"] == "not_checked"
    assert content["counts"]["mcsa_rows"] is None and content["counts"]["uniprot_features"] is None
    assert content["null_result"] is True and out.null_result is True
    none = run.call(TOOL, _args(structure, chains=(("A", None),), pdb_id=None))
    assert run.store.load(none.handle)["chains"][0]["mcsa"]["status"] == "not_checked"


def test_real_m15_numbering_map_links_uniprot_sites(tmp_path, ref, monkeypatch):
    """Real M15 result for public 1MQ4 (FIXTURE M15 set). The SYNTHETIC M26 UniProt row for O14965 holds made-up
    sites; the expected structure residue is read from the M15 SIFTS segment arithmetic (PDBe = label_seq 6..272 ->
    UniProt 125..391, offset 119), not from the M26 code."""
    m15 = tmp_path / "m15_reference"
    m15.mkdir()
    monkeypatch.setenv(m15_rs.ENV_VAR, str(m15))
    build_fixture_set(m15)
    rows = RF.synthetic_rows()
    rows["uniprot_function"].insert(0, {
        "accession": "O14965", "entry_name": "SYNTHETIC_FIXTURE", "protein_name": "SYNTHETIC fixture protein",
        "organism": "synthetic", "sequence_length": 403, "ec_numbers": [], "catalytic_activities": [],
        "features": [{"type": "Active site", "start": 256, "end": 256, "description": "SYNTHETIC fixture site",
                      "ligand_name": None, "ligand_id": None},
                     {"type": "Site", "start": 400, "end": 401, "description": "", "ligand_name": None,
                      "ligand_id": None}]})
    RF.build_set(ref, rows=rows, imported_at="2026-10-08T00:00:11Z")
    run, _ = _run(tmp_path)
    structure = _load(run, CIF_1MQ4)
    mapped = run.call("map_residue_numbering", {"structure": structure, "pdb_id": "1MQ4",
                                                "chains": [{"chain_auth": "A", "uniprot_accession": "O14965"}]})
    shutil.rmtree(m15)   # the M26 tool never reads the M15 reference folder
    out = run.call(TOOL, _args(structure, chains=(("A", None),), pdb_id="1MQ4", numbering_map=mapped.handle))
    (chain,) = run.store.load(out.handle)["chains"]
    assert chain["mcsa"]["coverage"] == "pdb_not_in_snapshot"
    assert (chain["accession"], chain["accession_source"]) == ("O14965", "numbering_map")
    uniprot = chain["uniprot"]
    assert (uniprot["status"], uniprot["linked_via"], uniprot["link_reason"]) == ("checked", "numbering_map", None)
    (link,) = uniprot["features"][0]["links"]
    assert (link["position"], link["status"]) == (256, "mapped")
    assert link["residue"]["chain_auth"] == "A" and link["residue"]["seq_label"] == 256 - 119
    assert [x["status"] for x in uniprot["features"][1]["links"]] == ["not_in_map", "not_in_map"]


# ------------------------------------------------------------------------------------------- admission (5.2)

@pytest.fixture
def world(tmp_path, ref):
    run, calls = _run(tmp_path)
    alpha = _load(run, ALPHA)
    beta = _load(run, BETA)
    world = {"run": run, "calls": calls, "alpha": alpha, "beta": beta,
             "map": _synthetic_map(run, alpha),
             "map_beta": _synthetic_map(run, alpha, pdb_id="0SY2", structure_handle=beta),
             "map_pdb_other": _synthetic_map(run, alpha, pdb_id="0SY2"),
             "source": run.store.load(alpha)["source"]}
    return world


def _w(world, **changes):
    args = _args(world["alpha"], numbering_map=world["map"])
    args.update(changes)
    return args


OTHER_RUN = "obj://run_other/structure/" + "a" * 64
UNKNOWN = "obj://run_reaction/structure/" + "c" * 64

SINGLE = [
    ("unknown_field", lambda w: _w(w, extra=1)),
    ("structure_invalid", lambda w: _w(w, structure=OTHER_RUN)),
    ("structure_invalid", lambda w: _w(w, structure=UNKNOWN)),
    ("structure_invalid", lambda w: _w(w, structure=5)),
    ("structure_invalid", lambda w: _w(w, structure=w["source"])),          # structure_source: kind not allowed
    ("structure_invalid", lambda w: _w(w, structure=w["map"])),
    ("pdb_id_invalid", lambda w: _w(w, pdb_id="SY01")),
    ("pdb_id_invalid", lambda w: _w(w, pdb_id="0SY12")),
    ("pdb_id_invalid", lambda w: _w(w, pdb_id=1234)),
    ("pdb_id_invalid", lambda w: _w(w, pdb_id="")),
    ("chains_invalid", lambda w: _w(w, chains=[])),
    ("chains_invalid", lambda w: _w(w, chains="A")),
    ("chains_invalid", lambda w: _w(w, chains=["A"])),
    ("chains_invalid", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": None, "note": 1}])),
    ("chains_invalid", lambda w: _w(w, chains=[{"chain_auth": "", "uniprot_accession": None}])),
    ("chains_invalid", lambda w: _w(w, chains=[{"uniprot_accession": "Q0SYN1"}])),
    ("chains_invalid", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": 5}])),
    ("chains_invalid", lambda w: _w(w, chains=[{"chain_auth": "A"}, {"chain_auth": "A"}])),
    ("chain_not_found", lambda w: _w(w, chains=[{"chain_auth": "Z", "uniprot_accession": None}])),
    ("chain_not_found", lambda w: _w(w, chains=[{"chain_auth": "a", "uniprot_accession": None}])),  # case matters
    ("accession_invalid", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": "q0syn1"}])),
    ("accession_invalid", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": ""}])),
    ("accession_invalid", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": "Q0SYN1-2"}])),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=w["alpha"])),     # another kind
    ("numbering_map_invalid", lambda w: _w(w, numbering_map="obj://run_other/residue_numbering_map/" + "b" * 64)),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=7)),
    ("structure_mismatch", lambda w: _w(w, numbering_map=w["map_beta"], pdb_id=None)),
    ("map_pdb_mismatch", lambda w: _w(w, numbering_map=w["map_pdb_other"])),
]


@pytest.mark.parametrize("reason, make", SINGLE, ids=[f"{i}-{r}" for i, (r, _) in enumerate(SINGLE)])
def test_each_admission_reason_refuses_before_the_implementation(world, reason, make):
    failure = _rejected(world["run"], world["calls"], make(world), reason)
    assert failure.message


def test_the_nine_reasons_are_the_closed_tuple():
    assert {reason for reason, _ in SINGLE} == set(K.ADMISSION_REASON_CODES)


# Each payload fails the named check AND every later one it can; the earliest one in spec order is reported.
PAIRS = [
    ("unknown_field", lambda w: _w(w, extra=1, structure=OTHER_RUN, pdb_id="bad", chains=[])),
    ("structure_invalid", lambda w: _w(w, structure=w["source"], pdb_id="bad", chains=[])),
    ("pdb_id_invalid", lambda w: _w(w, pdb_id="bad", chains=[], numbering_map=w["alpha"])),
    ("chains_invalid", lambda w: _w(w, chains=[{"chain_auth": "Z", "uniprot_accession": "bad"},
                                              {"chain_auth": "Z", "uniprot_accession": None}])),
    # chain_not_found is checked for every chain before any accession: a bad accession on an earlier chain loses
    ("chain_not_found", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": "bad"},
                                               {"chain_auth": "Z", "uniprot_accession": None}],
                                     numbering_map=w["alpha"])),
    ("accession_invalid", lambda w: _w(w, chains=[{"chain_auth": "A", "uniprot_accession": "bad"}],
                                       numbering_map=w["alpha"])),
    ("numbering_map_invalid", lambda w: _w(w, numbering_map=w["beta"], pdb_id="0SY9")),
    ("structure_mismatch", lambda w: _w(w, numbering_map=w["map_beta"], pdb_id="0SY1")),  # its pdb_id also differs
]


@pytest.mark.parametrize("reason, make", PAIRS, ids=[r for r, _ in PAIRS])
def test_admission_order_is_the_spec_order(world, reason, make):
    _rejected(world["run"], world["calls"], make(world), reason)


def test_chain_level_refusals_name_the_chain(world):
    failure = _rejected(world["run"], world["calls"], _w(world, chains=[{"chain_auth": "A", "uniprot_accession": None},
                                                                     {"chain_auth": "Z", "uniprot_accession": None}]),
                        "chain_not_found")
    assert failure.detail["chain_auth"] == "Z"


def test_malformed_map_content_is_numbering_map_invalid(world):
    run = world["run"]
    content = copy.deepcopy(run.store.load(world["map"]))
    content["rows"][0].pop("uniprot_position")        # SYNTHETIC damaged map object
    content["fixture"] = "SYNTHETIC damaged numbering map"
    damaged = run.store.put("residue_numbering_map", "residue_numbering_map@1", content).handle
    _rejected(run, world["calls"], _w(world, numbering_map=damaged), "numbering_map_invalid")


def test_deeply_nested_map_object_is_numbering_map_invalid_not_a_crash(world):
    """SYNTHETIC damaged map object: raw JSON nested past the recursion limit (``store.load`` raises RecursionError)."""
    run = world["run"]
    depth = 100000
    deep = run.store.put("residue_numbering_map", "residue_numbering_map@1", b"[" * depth + b"]" * depth,
                         produced_by="synthetic_fixture").handle
    with pytest.raises(RecursionError):
        run.store.load(deep)
    failure = _rejected(run, world["calls"], _w(world, numbering_map=deep), "numbering_map_invalid")
    assert failure.message


def test_absent_accession_and_null_map_are_accepted_and_normalized(world):
    run = world["run"]
    out = run.call(TOOL, {"structure": world["alpha"], "chains": [{"chain_auth": "A"}]})
    calls = world["calls"]
    assert calls[-1] == {"structure": world["alpha"], "pdb_id": None,
                         "chains": [{"chain_auth": "A", "uniprot_accession": None}], "numbering_map": None}
    lower = run.call(TOOL, _w(world, pdb_id="0sy1"))
    upper = run.call(TOOL, _w(world, pdb_id="0SY1"))
    assert lower.handle == upper.handle and run.store.load(lower.handle)["pdb_id"] == "0SY1"
    assert len(calls) == 2 and _events(run, "cache_hit")[-1]["output"]["handle"] == upper.handle
    assert out.kind == K.KIND


def test_argument_repair_path_runs_the_same_precheck(world):
    run, calls = world["run"], world["calls"]
    with pytest.raises(ToolFailure):
        run.call(TOOL, _w(world, chains=[{"chain_auth": "Z", "uniprot_accession": None}]))
    failed = _events(run, "proposal_rejected")[-1]["proposal_id"]
    with pytest.raises(ToolFailure) as caught:
        run.repair_call(failed, _w(world, pdb_id="bad"))
    assert caught.value.detail["reason_code"] == "pdb_id_invalid" and calls == []


# ------------------------------------------------------------------------------------------- 412 before the cache

def test_not_installed_is_a_precondition_before_any_admission_check(tmp_path, refdir):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    for args in (_args(structure), {**_args(structure), "extra": 1}, {"structure": 5}):
        failure = _rejected(run, calls, args, "not_installed", FailureClass.precondition)
        assert failure.message == K.SNAPSHOT_REASONS["not_installed"]
        assert "scripts/import_reaction_references.py" in failure.message


def test_snapshot_invalid_and_not_installed_come_before_the_cache_lookup(tmp_path, ref):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    first = run.call(TOOL, _args(structure))
    assert len(calls) == 1
    hits = len(_events(run, "cache_hit"))
    entries = next(ref.glob("sets/*/files/rhea/reactions.jsonl"))
    original = entries.read_bytes()
    entries.write_bytes(original.replace(b"synthetic", b"Synthetic", 1))   # same size, other hash
    assert entries.read_bytes() != original
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    calls.clear()
    failure = _rejected(run, calls, _args(structure), "snapshot_invalid", FailureClass.precondition)
    assert failure.message == K.SNAPSHOT_REASONS["snapshot_invalid"]
    entries.write_bytes(original)
    shutil.rmtree(ref)
    _rejected(run, calls, _args(structure), "not_installed", FailureClass.precondition)
    assert len(_events(run, "cache_hit")) == hits     # a refused call never reaches the completed-call lookup
    assert [e["output"]["handle"] for e in _events(run, "tool_succeeded") if e["tool"] == TOOL] == [first.handle]


def test_unknown_content_format_is_snapshot_invalid(tmp_path, refdir):
    rows = RF.synthetic_rows()
    data = K.encode_jsonl("mcsa", rows["mcsa"]).replace(b'"mcsa_id":101', b'"mcsa_id": 101', 1)
    RF.build_set(refdir, file_bytes={"mcsa": data})
    run, calls = _run(tmp_path)
    _rejected(run, calls, _args(_load(run, ALPHA)), "snapshot_invalid", FailureClass.precondition)


# ------------------------------------------------------------------------------------------- call key

def test_same_input_same_set_is_a_cache_hit_and_another_set_another_handle(tmp_path, ref):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    first = run.call(TOOL, _args(structure))
    again = run.call(TOOL, _args(structure))
    assert again.handle == first.handle and len(calls) == 1
    (hit,) = [e for e in _events(run, "cache_hit") if e["tool"] == TOOL]
    assert hit["output"]["handle"] == first.handle
    first_set = rs.pin_active_set().set_hash
    second_set = RF.build_set(ref, imported_at="2026-10-08T00:00:05Z")
    other = run.call(TOOL, _args(structure))
    assert len(calls) == 2 and other.handle != first.handle
    content = run.store.load(other.handle)
    assert content["snapshot_set"]["set_hash"] == second_set != first_set
    assert {**content, "snapshot_set": None} == {**run.store.load(first.handle), "snapshot_set": None}
    keys = [e["key"] for e in _events(run, "tool_succeeded") if e["tool"] == TOOL]
    assert len(set(keys)) == 2
    RF.activate(ref, first_set)
    back = run.call(TOOL, _args(structure))
    assert back.handle == first.handle and len(calls) == 2


def test_the_implementation_uses_the_set_the_precheck_pinned(tmp_path, ref, monkeypatch):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    pinned_hash = rs.pin_active_set().set_hash
    later = RF.build_set(ref, imported_at="2026-10-08T00:00:06Z", activate_set=False)
    real = tool_module.precheck

    def swap_after_precheck(store, args, bound=None):
        result = real(store, args, bound)
        RF.activate(ref, later)        # a concurrent import lands between the pre-check and the implementation
        return result

    run.registry.prechecks[TOOL] = swap_after_precheck
    out = run.call(TOOL, _args(structure))
    assert run.store.load(out.handle)["snapshot_set"]["set_hash"] == pinned_hash != later
    assert len(calls) == 1

    def uninstall_after_precheck(store, args, bound=None):
        result = real(store, args, bound)
        (ref / K.ACTIVE_NAME).unlink(missing_ok=True)   # the set disappears before the implementation runs
        return result

    run.registry.prechecks[TOOL] = uninstall_after_precheck
    gone = run.call(TOOL, _args(structure, chains=(("A", None),)))
    assert run.store.load(gone.handle)["snapshot_set"]["set_hash"] == later and len(calls) == 2


# ------------------------------------------------------------------------------------------- dry run, caps, storage

def test_dry_run_executes_the_cheap_tool(tmp_path, ref):
    run, calls = _run(tmp_path, name="run_dry", dry_run=True)
    structure = _load(run, ALPHA)
    out = run.call(TOOL, _args(structure))
    assert out.kind == K.KIND and len(calls) == 1
    assert not [e for e in _events(run, "tool_called") if e.get("plan_only")]
    wet, _ = _run(tmp_path, name="run_wet")
    wet_out = wet.call(TOOL, _args(_load(wet, ALPHA)))
    dry_content, wet_content = run.store.load(out.handle), wet.store.load(wet_out.handle)
    dry_content["structure"]["handle"] = wet_content["structure"]["handle"] = None
    assert dry_content == wet_content


def test_a_result_that_does_not_validate_is_never_stored(tmp_path, ref, monkeypatch):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    real = rk.build_reaction_knowledge

    def tampered(**kwargs):
        content = real(**kwargs)
        content["counts"]["chains"] = 3     # SYNTHETIC defect: counts disagree with the chains
        return content

    monkeypatch.setattr(rk, "build_reaction_knowledge", tampered)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, _args(structure))
    assert caught.value.cls == FailureClass.input_invalid
    assert caught.value.detail["reason_code"] == K.RESULT_INVALID_REASON == "result_invalid"
    assert len(calls) == 1 and _created(run) == []


@pytest.mark.parametrize("cap, value, reason", [("MAX_LINKS", 12, "too_many_links"),
                                                ("MAX_RESULT_BYTES", 2048, "result_too_large")])
def test_caps_are_resource_exceeded_and_store_nothing(tmp_path, ref, monkeypatch, cap, value, reason):
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    nmap = _synthetic_map(run, structure)
    monkeypatch.setattr(K, cap, value)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, _args(structure, numbering_map=nmap))
    assert caught.value.cls == FailureClass.resource_exceeded
    assert caught.value.detail["reason_code"] == reason and caught.value.detail["limit"] == value
    assert len(calls) == 1 and _created(run) == []
    monkeypatch.undo()
    monkeypatch.setenv(K.ENV_VAR, str(ref))
    assert run.call(TOOL, _args(structure, numbering_map=nmap)).kind == K.KIND   # nothing was cached as done


def test_real_link_cap_without_patching(tmp_path, refdir):
    rows = RF.synthetic_rows()
    q1 = next(r for r in rows["uniprot_function"] if r["accession"] == "Q0SYN1")
    q1["sequence_length"] = 5000
    q1["features"] = [{"type": "Binding site", "start": 1, "end": 2000, "description": "SYNTHETIC long site",
                       "ligand_name": None, "ligand_id": None}]
    RF.build_set(refdir, rows=rows)
    run, calls = _run(tmp_path)
    structure = _load(run, ALPHA)
    nmap = _synthetic_map(run, structure)
    with pytest.raises(ToolFailure) as caught:   # positions 1..2000 + a second map row at 13 = 2001 link elements
        run.call(TOOL, _args(structure, chains=(("A", "Q0SYN1"),), numbering_map=nmap))
    assert K.MAX_LINKS == 2000
    assert caught.value.cls == FailureClass.resource_exceeded
    assert caught.value.detail == {"reason_code": "too_many_links", "limit": 2000}
    assert len(calls) == 1 and _created(run) == []


# ------------------------------------------------------------------------------------------- events-only recovery

def test_events_only_recovery_without_the_reference_folder(tmp_path, ref):
    run, _ = _run(tmp_path)
    structure = _load(run, ALPHA)
    out = run.call(TOOL, _args(structure, numbering_map=_synthetic_map(run, structure)))
    sha = out.handle.rsplit("/", 1)[1]
    raw = (run.run_dir / "objects" / f"{sha}.json").read_bytes()
    handles = run.store.handles()
    shutil.rmtree(run.run_dir / "objects")
    (run.run_dir / "index.sqlite").unlink()
    shutil.rmtree(ref)
    rs._VERIFIED.clear()
    rk.clear_index_cache()
    assert rk.capability()["available"] is False
    reopened, calls = _run(tmp_path)
    assert (reopened.run_dir / "objects" / f"{sha}.json").read_bytes() == raw
    assert reopened.store.handles() == handles and calls == []
    assert reopened.store.meta(out.handle)["summary"] == out.summary
    assert rk.validated_result(reopened.store.load(out.handle)) == json.loads(raw)
    replayed = replay(run.run_dir / "events.jsonl", tmp_path / "replay" / run.run_id, build_registry(), run.run_id)
    assert replayed == handles
    assert (tmp_path / "replay" / run.run_id / "objects" / f"{sha}.json").read_bytes() == raw


# ------------------------------------------------------------------------------------------- module boundary

NEW_MODULES = [Path(tool_module.__file__), Path(tool_module.__file__).parents[1] / "reaction_knowledge_reads.py"]
NETWORK = {"socket", "urllib", "http", "httpx", "requests", "ssl", "ftplib", "aiohttp", "websockets"}
M15_DATA = {"reference_snapshots", "numbering_reads", "sifts_mapping", "klifs_numbering", "residue_numbering",
            "numbering_reports", "tools.numbering"}


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
def test_new_modules_never_network_raise_limits_or_read_m15_reference_data(path):
    source = path.read_text()
    absolute, relative = _imports(path)
    assert not {name.split(".")[0] for name in absolute} & NETWORK
    assert not {name.split(".")[0] for name in absolute} & {"rdkit", "meeko", "MDAnalysis", "pdbfixer", "openmm"}
    assert not {name for name in relative} & M15_DATA
    assert not {name.split(".")[-1] for name in relative} & {"reference_snapshots", "numbering_reads",
                                                               "sifts_mapping", "klifs_numbering", "numbering",
                                                               "residue_numbering", "jev_sends"}
    assert "raise_limits" not in source and "limit_approval" not in source
