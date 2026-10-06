"""M24 T3 cheap tool ``build_jev_projection`` (``mw.tools.jev``) -> ``jev_projection@1`` (spec .dryforge/spec.md 3).

Inputs:
* REAL M17 set: ``ligand_job_fixture.standard_run`` (real RDKit jobs through ``JobQueue`` on the labelled synthetic
  methacetin fixtures; 10 candidates, one PAINS row). The worker FAILS, never skips, when its environment is missing.
* REAL M20 sets made by the unmodified cheap tool through ``Run.call`` on public 1UBQ and public 1MQ4 (+ ADP shell, the
  M15 map and M16 annotation from the reference FIXTURE set), in this run, in another run and in a dry-run run.
* LABELLED SYNTHETIC: a 1UBQ copy whose chain is renamed "A.B" (an identifier the wire refuses), forged or edited
  stored objects (``store.put`` without a publication) and monkeypatched caps or checks, each marked
  "fault injection" where it is used.

Expected projections are the pure T2 functions on the same stored objects (``mw.jev_projection``); neighbor and window
values against the independent oracle are covered by ``test_jev_projection.py``.
"""
from __future__ import annotations

import ast
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import gemmi
import pytest
from fastapi.testclient import TestClient
from ligand_job_fixture import standard_run
from reference_fixture_set import build_fixture_set

from mw import jev_constants as J
from mw import jev_projection as P
from mw import ligand_bundle, ligand_filters
from mw import mutation_candidates as mc
from mw import reference_snapshots as rs
from mw.api import app as api_module
from mw.core.errors import FailureClass, ToolFailure
from mw.core.handles import canonical_json
from mw.tools import jev as tool_module
from mw.tools.registry import ToolContext
from mw.tools.structural import _parse
from mw.workspace import CONFIG, build_registry, new_run

FIX = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[2]
MW = REPO / "backend/mw"
TOOL = J.TOOL
EXPECTED = json.loads((FIX / "jev/expected.json").read_text())["structures"]
ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}
REASONS = set(J.PROJECTION_REASON_CODES) | {J.PROJECTION_INVALID}
FORBIDDEN_WORDS = ("점수", "순위", "추천", "최적", "개선", "안정성", "ΔΔG", "친화도", "활성", "예측", "안전", "유망")


def res(seq_auth: int, resname: str, chain_auth: str = "A") -> dict:
    return {"model_number": 1, "chain_auth": chain_auth, "seq_auth": seq_auth, "icode": "", "resname": resname}


def _counted_registry():
    reg = build_registry()
    calls: list[dict] = []
    impl = reg.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    reg.impls[TOOL] = counted
    return reg, calls


def _events(run, kind=None) -> list[dict]:
    return [e for e in run.events.read() if kind is None or e["type"] == kind]


def _projection_objects(run) -> list[str]:
    return [e["handle"] for e in _events(run, "object_created") if e["kind"] == J.PROJECTION_KIND]


def _rejected(world, args, reason_code, cls=FailureClass.input_invalid) -> ToolFailure:
    """A pre-check refusal: one ``proposal_rejected`` event, no tool call, no object."""
    run, calls = world["run"], world["calls"]
    before, made, called = len(_events(run)), len(_projection_objects(run)), len(calls)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, args)
    assert caught.value.cls == cls and caught.value.detail["reason_code"] == reason_code, (
        reason_code, caught.value.detail, caught.value.message)
    assert caught.value.detail["reason_code"] in REASONS
    new = _events(run)[before:]
    assert [e["type"] for e in new if e["type"] != "wall_charged"] == ["proposal_rejected"]
    assert len(calls) == called and len(_projection_objects(run)) == made
    return caught.value


def _keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            found |= _keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _keys(item)
    return found


def _floats(value, path="") -> list[str]:
    if isinstance(value, dict):
        return [p for key, item in value.items() for p in _floats(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [p for item in value for p in _floats(item, f"{path}[]")]
    return [path] if type(value) is float else []


def _first_candidates(content: dict, limit: int = 20) -> list[int]:
    """The first candidate of each position (most positions), filled up with further candidates to ``limit``."""
    first: dict[int, int] = {}
    for candidate in content["candidates"]:
        first.setdefault(candidate["position_index"], candidate["index"])
    chosen = list(first.values())[:limit]
    rest = [c["index"] for c in content["candidates"] if c["index"] not in set(chosen)]
    return chosen + rest[:limit - len(chosen)]


# ---------------------------------------------------------------- worlds (module scoped)


@pytest.fixture(scope="module")
def ligand(tmp_path_factory):
    root = tmp_path_factory.mktemp("jev_tool_lig")
    made = standard_run(root, "run_jev_tool_lig")
    reg, calls = _counted_registry()
    run = new_run(root, run_id="run_jev_tool_lig", dry_run=False, registry=reg)   # same run, counted tool
    content, inspection = ligand_bundle.validated_candidate_set(run, made["candidate_set"])
    return {"root": root, "run": run, "calls": calls, "handle": made["candidate_set"], "content": content,
            "inspection": inspection, "ids": [row["id"] for row in content["candidates"]], "made": made}


def _load(run, path: Path) -> str:
    return run.call("load_structure", {"source": str(path), "model_index": 0}).handle


def _prepare(run, structure: str) -> str:
    return run.call("prepare_structure", {"structure": structure}).handle


def _m20(run, prepared: str, **kw) -> str:
    args = {"structure": prepared, "sources": {"pocket": None, "ligand_shell": kw.pop("ligand_shell", None),
                                               "residues": kw.pop("residues", [])}, **kw}
    return run.call("generate_mutation_candidates", args).handle


def _renamed_chain_cif(name: str) -> bytes:
    """SYNTHETIC: public 1UBQ with its chain renamed (coordinates unchanged)."""
    st = gemmi.read_structure(str(FIX / "public_1ubq.cif"))
    st.setup_entities()
    for chain in st[0]:
        chain.name = name
    return st.make_mmcif_document().as_string().encode()


@pytest.fixture(scope="module")
def mutation(tmp_path_factory):
    base = tmp_path_factory.mktemp("jev_tool_mut")
    root = base / "runs"
    reference = base / "reference"
    reference.mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(rs.ENV_VAR, str(reference))
        build_fixture_set(reference)
        reg, calls = _counted_registry()
        run = new_run(root, run_id="run_jev_tool_mut", dry_run=False, registry=reg)
        ubq_loaded = _load(run, FIX / "public_1ubq.cif")
        ubq = _prepare(run, ubq_loaded)
        ubq_user = [res(p["residue"]["seq_auth"], p["residue"]["resname"]) for p in EXPECTED["1UBQ"]["positions"]]
        ubq_set = _m20(run, ubq, residues=ubq_user)
        mq4 = _prepare(run, _load(run, FIX / "public_1mq4.cif"))
        numbering_map = run.call("map_residue_numbering", {"structure": mq4, "pdb_id": "1MQ4",
                                                           "chains": [{"chain_auth": "A"}]}).handle
        annotation = run.call("annotate_reference_sites", {"numbering_map": numbering_map}).handle
        mq4_user = [res(p["residue"]["seq_auth"], p["residue"]["resname"]) for p in EXPECTED["1MQ4"]["positions"]]
        mq4_set = _m20(run, mq4, ligand_shell={"radius_A": 5.0}, residues=mq4_user, ligand=ADP,
                       released_residues=[res(162, "LYS"), res(211, "GLU"), res(274, "ASP")],
                       numbering_map=numbering_map, annotation=annotation)
        unsafe_loaded = run.call("load_structure", {"source": "synthetic_1ubq_chain_AB.cif", "model_index": 0},
                                 source_bytes=_renamed_chain_cif("A.B"), source_format="cif").handle
        unsafe = _prepare(run, unsafe_loaded)
        unsafe_set = _m20(run, unsafe, residues=[res(1, "MET", "A.B")])
        other = new_run(root, run_id="run_jev_tool_other", dry_run=False)
        other_set = _m20(other, _prepare(other, _load(other, FIX / "public_1ubq.cif")), residues=[res(1, "MET")])
    sets = {"ubq_set": ubq_set, "mq4_set": mq4_set, "unsafe_set": unsafe_set}
    return {"root": root, "run": run, "calls": calls, "ubq_loaded": ubq_loaded, "ubq": ubq, "mq4": mq4,
            "unsafe_loaded": unsafe_loaded, "unsafe": unsafe, "other": other, "other_set": other_set,
            "numbering_map": numbering_map, "annotation": annotation, **sets,
            "content": {name: run.store.load(handle) for name, handle in sets.items()}}


def _structure(run, prepared):
    return _parse(ToolContext(store=run.store, call_id="jev_t3_test"), prepared)


# ---------------------------------------------------------------- registration


def test_registered_in_all_four_places_with_a_precheck():
    import yaml

    spec = next(t for t in yaml.safe_load((CONFIG / "tools.yaml").read_text())["tools"] if t["name"] == TOOL)
    assert spec["level"] == "L2" and spec["version"] == "1" and spec["cost_class"] == "cheap"
    assert spec["accepts"] == {"source": ["ligand_candidate_set", "mutation_candidate_set"]}
    assert spec["emits"] == "jev_projection"
    assert {"source", *spec["params"]} == set(tool_module.ARG_KEYS) == {"source", "candidates", "filter"}
    assert spec["params"]["candidates"]["required"] is True and spec["params"]["filter"] == {"default": None}
    assert not any(word in spec["description"] for word in FORBIDDEN_WORDS)
    reg = build_registry()
    assert TOOL in reg.impls and reg.prechecks[TOOL] is tool_module.precheck and TOOL not in reg.unavailable
    assert reg.specs[TOOL].idempotent is True
    assert TOOL in api_module.SUPPORTED_TOOLS and TOOL in api_module.REGISTRY.impls
    assert "jev.register(reg)" in (MW / "workspace.py").read_text()


# ---------------------------------------------------------------- stored projections


def test_ligand_projection_is_the_pure_build_of_the_stored_set(ligand):
    run, ids = ligand["run"], ligand["ids"]
    chosen = [ids[7], ids[2], ids[5], ids[0]]
    out = run.call(TOOL, {"source": ligand["handle"], "candidates": chosen})
    assert out.kind == J.PROJECTION_KIND and out.schema_ == J.PROJECTION_SCHEMA and out.null_result is False
    content = run.store.load(out.handle)
    assert P.validated_projection(content) == content
    wire, selection = P.build_ligand_wire(ligand["content"], chosen, inspection=ligand["inspection"])
    assert content == P.build_projection_content("ligand", ligand["handle"], wire, selection)
    assert [s["candidate_id"] for s in content["selection"]] == [ids[0], ids[2], ids[5], ids[7]]   # stored order
    assert content["filter"] is None and content["structure"] is None
    assert out.summary == {"kind": "ligand", "source": ligand["handle"], "selection_count": 4,
                           "body_bytes": content["body_bytes"], "body_sha256": content["body_sha256"]}
    called = [e for e in _events(run, "tool_called") if e["tool"] == TOOL][-1]
    assert called["args"] == {"source": ligand["handle"], "candidates": [ids[0], ids[2], ids[5], ids[7]],
                              "filter": None}


def test_same_normalized_input_gives_the_same_key_and_handle(ligand, mutation):
    run, ids, calls = ligand["run"], ligand["ids"], ligand["calls"]
    before = len(calls)
    first = run.call(TOOL, {"source": ligand["handle"], "candidates": [ids[9], ids[1], ids[4]]})
    again = run.call(TOOL, {"source": ligand["handle"], "candidates": [ids[1], ids[4], ids[9]]})
    nulled = run.call(TOOL, {"source": ligand["handle"], "candidates": [ids[4], ids[9], ids[1]], "filter": None})
    assert first.handle == again.handle == nulled.handle and len(calls) == before + 1
    called = [e for e in _events(run, "tool_called") if e["tool"] == TOOL][-1]
    hits = [e for e in _events(run, "cache_hit") if e["tool"] == TOOL][-2:]
    assert [hit["key"] for hit in hits] == [called["key"]] * 2
    mrun, mcalls = mutation["run"], mutation["calls"]
    before = len(mcalls)
    chosen = _first_candidates(mutation["content"]["ubq_set"])
    a = mrun.call(TOOL, {"source": mutation["ubq_set"], "candidates": chosen})
    b = mrun.call(TOOL, {"source": mutation["ubq_set"], "candidates": chosen[::-1]})
    assert a.handle == b.handle and len(mcalls) == before + 1
    assert mrun.store.load(a.handle) == mrun.store.load(b.handle)


def test_mutation_projection_is_the_pure_build_on_the_prepared_structure(mutation):
    run, content = mutation["run"], mutation["content"]["mq4_set"]
    chosen = _first_candidates(content)
    assert len(chosen) == J.MAX_CANDIDATES
    out = run.call(TOOL, {"source": mutation["mq4_set"], "candidates": chosen[::-1]})
    stored = run.store.load(out.handle)
    assert P.validated_projection(stored) == stored
    wire, selection = P.build_mutation_wire(content, chosen, _structure(run, mutation["mq4"]))
    assert stored == P.build_projection_content("mutation", mutation["mq4_set"], wire, selection,
                                                structure={"handle": mutation["mq4"], "model_number": 1})
    assert stored["structure"] == {"handle": mutation["mq4"], "model_number": 1} and stored["filter"] is None
    assert [s["candidate_index"] for s in stored["selection"]] == sorted(chosen)
    assert out.summary == {"kind": "mutation", "source": mutation["mq4_set"], "selection_count": 20,
                           "body_bytes": stored["body_bytes"], "body_sha256": stored["body_sha256"]}
    assert stored["body_bytes"] <= J.MAX_BODY_BYTES


def test_stored_projection_has_no_coordinates_extra_handles_or_numbering_values(mutation):
    run, content = mutation["run"], mutation["content"]["mq4_set"]
    out = run.call(TOOL, {"source": mutation["mq4_set"], "candidates": _first_candidates(content)})
    stored = run.store.load(out.handle)
    text = canonical_json(stored).decode()
    wire_text = canonical_json(stored["wire"]).decode()
    # handles: only the local source / structure fields, never in the wire
    assert text.count("obj://") == 2 and stored["source"]["handle"] in text and stored["structure"]["handle"] in text
    assert "obj://" not in wire_text and not _keys(stored["wire"]) & {"handle", "run_id", "path", "pocket_set"}
    for handle in (mutation["numbering_map"], mutation["annotation"], mutation["ubq_loaded"]):
        assert handle not in text
    # no coordinates: the only floats in the stored object are the stored ligand distances
    assert set(_floats(stored)) == {".wire.positions[].ligand_min_distance_A"}
    assert not _keys(stored) & {"x", "y", "z", "coordinates", "atoms", "heavy", "numbering", "klifs_sites",
                                "reasons", "metal", "disulfide_partner", "exclusion_reasons"}
    assert "_atom_site" not in text and "ATOM " not in text
    # no numbering map / annotation values (UniProt accession, KLIFS labels) and no protection reason names
    numbering = {v for p in content["positions"] if p["numbering"] for k, v in p["numbering"].items()
                 if k in ("uniprot_accession", "klifs_label") and isinstance(v, str) and v}
    labels = {label for p in content["positions"] for label in (p["protection"]["klifs_sites"] or [])}
    assert numbering and labels
    for value in numbering | labels | {"user_protected", "klifs_key_site", "disulfide_cys", "MG"}:
        assert json.dumps(value) not in text, value


def test_dry_run_executes_the_cheap_tool_and_stores(tmp_path):
    reg, calls = _counted_registry()
    run = new_run(tmp_path / "runs", run_id="run_jev_tool_dry", dry_run=True, registry=reg)
    prepared = _prepare(run, _load(run, FIX / "public_1ubq.cif"))
    source = _m20(run, prepared, residues=[res(1, "MET"), res(44, "ILE")])
    out = run.call(TOOL, {"source": source, "candidates": [3, 30, 0]})
    assert out.kind == J.PROJECTION_KIND and len(calls) == 1
    stored = run.store.load(out.handle)
    assert P.validated_projection(stored) == stored
    assert [s["candidate_index"] for s in stored["selection"]] == [0, 3, 30]
    assert not [e for e in _events(run, "tool_called") if e.get("plan_only")]
    assert not _events(run, "budget_reserved")


# ---------------------------------------------------------------- admission (spec 3 order, first failure only)


def test_unknown_field_comes_first(ligand, mutation):
    _rejected(ligand, {"source": 5, "candidates": [], "filter": "x", "rank": 1}, "unknown_field")
    _rejected(mutation, {"source": mutation["ubq_set"], "candidates": [0], "structure": mutation["ubq"]},
              "unknown_field")


def test_source_invalid(ligand, mutation):
    ids = ligand["ids"]
    lrun = ligand["run"]
    for source in (None, 5, "", "not a handle", ["x"], ligand["made"]["inspection"], ligand["made"]["parent"],
                   f"obj://{lrun.run_id}/ligand_candidate_set/" + "0" * 64,   # forged: never stored
                   mutation["other_set"].replace("run_jev_tool_other", lrun.run_id)):
        _rejected(ligand, {"source": source, "candidates": [ids[0]]}, "source_invalid")
    _rejected(ligand, {"candidates": [ids[0]]}, "source_invalid")
    _rejected(ligand, {"source": ligand["handle"].replace(lrun.run_id, "run_jev_tool_other"),
                       "candidates": [ids[0]]}, "source_invalid")   # another run's namespace
    # source_invalid comes before every later check (bad selection, filter on a mutation set, ...)
    _rejected(ligand, {"source": ligand["made"]["inspection"], "candidates": [], "filter": {"x": 1}},
              "source_invalid")
    mrun = mutation["run"]
    for source in (mutation["other_set"], mutation["ubq"], mutation["numbering_map"],
                   f"obj://{mrun.run_id}/mutation_candidate_set/" + "f" * 64):
        _rejected(mutation, {"source": source, "candidates": [0]}, "source_invalid")


def test_unpublished_or_invalid_stored_sources_are_refused(ligand, mutation, monkeypatch):
    lrun, content = ligand["run"], ligand["content"]
    # fault injection: an M17 set copy stored without any job publication (content edited so the handle differs)
    forged = copy.deepcopy(content)
    forged["candidates"] = forged["candidates"][:-1]
    forged["counts"] = {**forged["counts"], "candidates": len(forged["candidates"])}
    handle = lrun.store.put("ligand_candidate_set", "ligand_candidate_set@1", forged,
                            produced_by="synthetic_forgery").handle
    _rejected(ligand, {"source": handle, "candidates": [forged["candidates"][0]["id"]]}, "source_invalid")
    # fault injection: the published set's stored-object check fails
    def broken(*_args, **_kwargs):
        raise ValueError("synthetic: stored object check fails")

    monkeypatch.setattr(ligand_bundle, "check_candidate_set", broken)
    _rejected(ligand, {"source": ligand["handle"], "candidates": [ligand["ids"][0]]}, "source_invalid")
    monkeypatch.undo()
    # fault injection: an M20 set that fails validated_set (counts edited)
    mrun = mutation["run"]
    bad = copy.deepcopy(mutation["content"]["ubq_set"])
    bad["counts"]["candidates"] += 1
    with pytest.raises(mc.MutationSetInvalid):
        mc.validated_set(copy.deepcopy(bad))
    handle = mrun.store.put("mutation_candidate_set", "mutation_candidate_set@1", bad,
                            produced_by="synthetic_forgery").handle
    _rejected(mutation, {"source": handle, "candidates": [0]}, "source_invalid")


@pytest.mark.parametrize("candidates", [
    None, "c_0000000000000000", {}, [], [1], [None], ["C_0000000000000000"], ["c_000000000000000"],
    ["c_000000000000000g"]])
def test_ligand_selection_invalid(ligand, candidates):
    _rejected(ligand, {"source": ligand["handle"], "candidates": candidates}, "selection_invalid")


def test_selection_counts_duplicates_and_unknown_candidates(ligand, mutation):
    ids = ligand["ids"]
    _rejected(ligand, {"source": ligand["handle"], "candidates": [ids[0], ids[1], ids[0]]}, "selection_invalid")
    fake = [f"c_{n:016x}" for n in range(21)]   # 21 well-formed ids: the count fails before candidate_unknown
    _rejected(ligand, {"source": ligand["handle"], "candidates": fake}, "selection_invalid")
    _rejected(ligand, {"source": ligand["handle"], "candidates": [ids[0], "c_" + "0" * 16]}, "candidate_unknown")
    source = mutation["ubq_set"]
    total = len(mutation["content"]["ubq_set"]["candidates"])
    assert total > 21
    for bad in ([], list(range(21)), [0, 0], [True], [0.0], ["0"], [1, None]):
        _rejected(mutation, {"source": source, "candidates": bad}, "selection_invalid")
    for unknown in ([total], [-1], [0, 10**6]):
        _rejected(mutation, {"source": source, "candidates": unknown}, "candidate_unknown")
    exact = mutation["run"].call(TOOL, {"source": source, "candidates": list(range(20))[::-1]})
    assert len(mutation["run"].store.load(exact.handle)["selection"]) == 20
    one = mutation["run"].call(TOOL, {"source": source, "candidates": [total - 1]})
    assert mutation["run"].store.load(one.handle)["selection"][0]["candidate_index"] == total - 1
    # selection_invalid before candidate_unknown before filter_invalid
    _rejected(mutation, {"source": source, "candidates": [total, total], "filter": {}}, "selection_invalid")
    _rejected(mutation, {"source": source, "candidates": [total], "filter": {}}, "candidate_unknown")


def test_filter_rules(ligand, mutation):
    run, rows = ligand["run"], ligand["content"]["candidates"]
    pains =[row["id"] for row in rows if row["pains"]["matches"]]
    clean = [row["id"] for row in rows if not row["pains"]["matches"]]
    assert len(pains) == 1 and len(clean) == 9
    spec = {"pains_exclude": True, "ranges": {"mol_weight": {"max": 1000}}}
    out = run.call(TOOL, {"source": ligand["handle"], "candidates": clean[:3], "filter": spec})
    stored = run.store.load(out.handle)
    assert stored["filter"] == ligand_filters.normalize_filter_spec(spec)
    plain = run.call(TOOL, {"source": ligand["handle"], "candidates": clean[:3]})
    assert plain.handle != out.handle and run.store.load(plain.handle)["wire"] == stored["wire"]
    failing = _rejected(ligand, {"source": ligand["handle"], "candidates": [clean[0], pains[0]], "filter": spec},
                        "candidate_filtered_out")
    assert failing.detail == {"reason_code": "candidate_filtered_out", "candidates": pains}
    weights = sorted(row["properties"]["mol_weight"] for row in rows)
    light = {"ranges": {"mol_weight": {"max": weights[4]}}}   # stored values: the five lightest pass
    heavy = [row["id"] for row in rows if row["properties"]["mol_weight"] > weights[4]]
    _rejected(ligand, {"source": ligand["handle"], "candidates": heavy[:2], "filter": light}, "candidate_filtered_out")
    passing = [row["id"] for row in rows if row["properties"]["mol_weight"] <= weights[4]]
    assert len(run.store.load(run.call(TOOL, {"source": ligand["handle"], "candidates": passing,
                                              "filter": light}).handle)["selection"]) == 5
    # an inactive filter keeps every candidate (M17 passes_only / M22 eligibility rule) and is stored as given
    inactive = run.call(TOOL, {"source": ligand["handle"], "candidates": [pains[0]], "filter": {}})
    assert run.store.load(inactive.handle)["filter"] == {"ranges": {}, "pains_exclude": False}
    for bad in ({"ranges": {"qed": {"max": 1}}}, {"rank": True}, {"pains_exclude": 1}, [], "pains",
                {"ranges": {"tpsa": {"min": 5, "max": 1}}}, {"ranges": {"tpsa": {"min": float("nan")}}}):
        _rejected(ligand, {"source": ligand["handle"], "candidates": [clean[0]], "filter": bad}, "filter_invalid")
    # filter_invalid before candidate_filtered_out
    _rejected(ligand, {"source": ligand["handle"], "candidates": [pains[0]], "filter": {"pains_exclude": "yes"}},
              "filter_invalid")
    # any filter on a mutation set is refused, before structure_unavailable; null is the absent filter
    for value in ({}, {"pains_exclude": True}, {"ranges": {}}, [], 0, False):
        _rejected(mutation, {"source": mutation["ubq_set"], "candidates": [0], "filter": value}, "filter_invalid")
    _rejected(mutation, {"source": mutation["unsafe_set"], "candidates": [0], "filter": {}}, "filter_invalid")
    assert (mutation["run"].call(TOOL, {"source": mutation["ubq_set"], "candidates": [0], "filter": None}).handle
            == mutation["run"].call(TOOL, {"source": mutation["ubq_set"], "candidates": [0]}).handle)


def _forged_set(mutation, name: str, **changes) -> str:
    """Fault injection: a stored copy of a real M20 set (no tool publication) with structure fields edited; it still
    passes ``validated_set`` (an M20 set's own check), so only the structure check can refuse it."""
    content = copy.deepcopy(mutation["content"][name])
    content["structure"].update(changes)
    mc.validated_set(copy.deepcopy(content))
    return mutation["run"].store.put("mutation_candidate_set", "mutation_candidate_set@1", content,
                                     produced_by="synthetic_forgery").handle


def test_structure_unavailable(mutation):
    # the set's structure is a raw (not prepared) structure of this run
    _rejected(mutation, {"source": _forged_set(mutation, "ubq_set", handle=mutation["ubq_loaded"]),
                         "candidates": [0]}, "structure_unavailable")
    # a prepared structure of this run whose residues do not resolve the stored positions (1MQ4 for a 1UBQ set)
    _rejected(mutation, {"source": _forged_set(mutation, "ubq_set", handle=mutation["mq4"]), "candidates": [0]},
              "structure_unavailable")
    # another run's prepared structure, and a model number the structure does not have
    other_prepared = next(e["handle"] for e in mutation["other"].events.read()
                          if e["type"] == "object_created" and e["kind"] == "prepared_structure")
    _rejected(mutation, {"source": _forged_set(mutation, "ubq_set", handle=other_prepared), "candidates": [0]},
              "structure_unavailable")
    # structure_unavailable comes before wire_field_invalid (the "A.B" set would fail the wire too)
    _rejected(mutation, {"source": _forged_set(mutation, "unsafe_set", handle=mutation["unsafe_loaded"]),
                         "candidates": [0]}, "structure_unavailable")


def test_wire_field_invalid(ligand, mutation, monkeypatch):
    # SYNTHETIC structure, real tool path: chain "A.B" is stored as the 7-field chain_auth but is not a safe identifier
    _rejected(mutation, {"source": mutation["unsafe_set"], "candidates": [0]}, "wire_field_invalid")
    # fault injection: the observed property method strings no longer match the stored ones
    changed = {**J.PROPERTY_METHODS, "tpsa": "rdkit CalcTPSA (changed)"}
    monkeypatch.setattr(P, "PROPERTY_METHODS", changed)
    _rejected(ligand, {"source": ligand["handle"], "candidates": [ligand["ids"][0]]}, "wire_field_invalid")


def test_payload_too_large_stores_nothing(ligand, monkeypatch):
    # fault injection: the 64 KiB cap is lowered so that a real 10-candidate body exceeds it (the exact 65,536-byte
    # boundary is tested with labelled synthetic rows in test_jev_projection.py)
    run, calls = ligand["run"], ligand["calls"]
    monkeypatch.setattr(P, "MAX_BODY_BYTES", 1_000)
    before, made, called = len(_events(run)), len(_projection_objects(run)), len(calls)
    with pytest.raises(ToolFailure) as caught:
        run.call(TOOL, {"source": ligand["handle"], "candidates": ligand["ids"]})
    assert caught.value.cls == FailureClass.resource_exceeded
    detail = caught.value.detail
    assert detail["reason_code"] == "payload_too_large" and detail["limit"] == 1_000 and detail["body_bytes"] > 1_000
    new = [e["type"] for e in _events(run)[before:] if e["type"] != "wall_charged"]
    assert new == ["tool_called", "tool_failed"] and len(calls) == called + 1
    assert len(_projection_objects(run)) == made and not [e for e in _events(run)[before:]
                                                         if e["type"] == "object_created"]


def test_a_build_that_fails_validation_is_never_stored(ligand, monkeypatch):
    run = ligand["run"]
    original = P.build_projection_content

    def tampered(*args, **kwargs):   # fault injection: the built content gains a field the validator refuses
        return {**original(*args, **kwargs), "rank": [1]}

    monkeypatch.setattr(P, "build_projection_content", tampered)
    before = len(_events(run))
    with pytest.raises(ToolFailure) as caught:   # a selection no other test builds (never a cache hit)
        run.call(TOOL, {"source": ligand["handle"], "candidates": [ligand["ids"][6], ligand["ids"][8]]})
    assert caught.value.cls == FailureClass.input_invalid
    assert caught.value.detail["reason_code"] == J.PROJECTION_INVALID
    assert not [e for e in _events(run)[before:] if e["type"] == "object_created"]


# ---------------------------------------------------------------- events-only recovery


@pytest.mark.parametrize("which", ["ligand", "mutation"])
def test_events_only_recovery(which, ligand, mutation, tmp_path):
    world = ligand if which == "ligand" else mutation
    run = world["run"]
    args = ({"source": ligand["handle"], "candidates": ligand["ids"][3:6]} if which == "ligand"
            else {"source": mutation["mq4_set"], "candidates": _first_candidates(mutation["content"]["mq4_set"], 7)})
    out = run.call(TOOL, args)
    raw = (run.run_dir / "objects" / f"{out.handle.rsplit('/', 1)[1]}.json").read_bytes()
    root = tmp_path / "replayed"
    (root / run.run_id).mkdir(parents=True)
    shutil.copyfile(run.run_dir / "events.jsonl", root / run.run_id / "events.jsonl")   # events only
    reg, calls = _counted_registry()
    reopened = new_run(root, run_id=run.run_id, dry_run=False, registry=reg)
    assert (reopened.run_dir / "objects" / f"{out.handle.rsplit('/', 1)[1]}.json").read_bytes() == raw
    content = reopened.store.load(out.handle)
    assert P.validated_projection(content) == content
    assert reopened.store.meta(out.handle)["summary"] == out.summary
    again = reopened.call(TOOL, {**args, "candidates": args["candidates"][::-1]})   # cache hit, nothing re-run
    assert again.handle == out.handle and calls == []


# ---------------------------------------------------------------- HTTP


@pytest.fixture
def http(monkeypatch):
    calls: list[dict] = []
    impl = api_module.REGISTRY.impls[TOOL]

    def counted(ctx, **kwargs):
        calls.append(kwargs)
        return impl(ctx, **kwargs)

    monkeypatch.setitem(api_module.REGISTRY.impls, TOOL, counted)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    client.calls = calls
    yield client
    api_module.RUNS.clear()


def _command(client, rid, tool, args):
    return client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})


def test_http_commands_build_projections(http, tmp_path, ligand, monkeypatch):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    tools = {t["name"]: t for t in http.get("/tools", params={"levels": "L2"}).json()}
    assert tools[TOOL]["emits"] == "jev_projection" and tools[TOOL]["cost_class"] == "cheap"
    created = http.post("/runs", json={"goal": "M24 projection", "dry_run": False})
    assert created.status_code == 201, created.text
    rid = created.json()["run_id"]
    upload = http.post(f"/runs/{rid}/uploads", params={"filename": "1ubq.cif"},
                       content=(FIX / "public_1ubq.cif").read_bytes(),
                       headers={"content-type": "application/octet-stream"})
    assert upload.status_code == 201, upload.text
    loaded = _command(http, rid, "load_structure", {"source": upload.json()["upload_id"]}).json()["handle"]["handle"]
    prepared = _command(http, rid, "prepare_structure", {"structure": loaded}).json()["handle"]["handle"]
    made = _command(http, rid, "generate_mutation_candidates",
                    {"structure": prepared, "sources": {"pocket": None, "ligand_shell": None,
                                                        "residues": [res(1, "MET"), res(48, "LYS")]}})
    source = made.json()["handle"]["handle"]
    first = _command(http, rid, TOOL, {"source": source, "candidates": [20, 2, 0]})
    assert first.status_code == 200, first.text
    handle = first.json()["handle"]
    assert handle["kind"] == "jev_projection" and handle["summary"]["selection_count"] == 3
    second = _command(http, rid, TOOL, {"source": source, "candidates": [0, 20, 2]})
    assert second.json()["handle"]["handle"] == handle["handle"] and len(http.calls) == 1
    stored = api_module._run(rid).store.load(handle["handle"])
    assert P.validated_projection(stored) == stored
    refused = _command(http, rid, TOOL, {"source": source, "candidates": [0], "filter": {}})
    assert refused.status_code == 422 and refused.json()["error"] == "input_invalid"
    assert refused.json()["detail"] == {"reason_code": "filter_invalid"}
    unknown = _command(http, rid, TOOL, {"source": source, "candidates": [0], "extra": 1})
    assert unknown.status_code == 422 and unknown.json()["detail"]["reason_code"] == "unknown_field"
    monkeypatch.setattr(P, "MAX_BODY_BYTES", 1_000)   # fault injection: lowered cap
    too_large = _command(http, rid, TOOL, {"source": source, "candidates": [1, 3]})
    assert too_large.status_code == 429 and too_large.json()["error"] == "resource_exceeded"
    assert too_large.json()["detail"]["reason_code"] == "payload_too_large"
    kinds = [e["kind"] for e in api_module._run(rid).events.read() if e["type"] == "object_created"]
    assert kinds.count("jev_projection") == 1 and len(http.calls) == 2
    monkeypatch.setattr(P, "MAX_BODY_BYTES", J.MAX_BODY_BYTES)
    # a real M17 set of another run root, through the same route
    monkeypatch.setattr(api_module, "RUNS_DIR", ligand["root"])
    api_module.RUNS.clear()
    lig = _command(http, ligand["run"].run_id, TOOL, {"source": ligand["handle"], "candidates": ligand["ids"][:2]})
    assert lig.status_code == 200, lig.text
    assert lig.json()["handle"]["summary"]["kind"] == "ligand"


# ---------------------------------------------------------------- module hygiene


def _imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            found.add("." * node.level + (node.module or ""))
    return found


def test_tool_module_imports_and_forbidden_strings():
    path = MW / "tools/jev.py"
    assert _imports(path) <= {"__future__", "json", "typing", "..", "..core.errors", "..core.handles",
                              "..jev_constants", "..ligand_bundle", "..mutation_candidates", ".registry",
                              ".structural"}
    text = path.read_text()
    for word in ("raise_limits", "limit_approval", "httpx", "pydantic", "rdkit", "meeko", "MDAnalysis", "pdbfixer",
                 "openmm", "egress", "reference_snapshots", "urllib", "socket", "requests"):
        assert word not in text, word
    for name in ("analysis_plans.py", "analysis_executions.py", "workflows.py"):   # M13 flows never call it
        assert TOOL not in (MW / name).read_text(), name


def test_importing_the_tool_loads_no_network_reference_or_chemistry_package():
    code = ("import sys, mw.tools.jev\n"
            "bad = [m for m in ('httpx', 'rdkit', 'meeko', 'MDAnalysis', 'pdbfixer', 'openmm', 'fastapi',"
            " 'mw.egress', 'mw.egress.gate', 'mw.llm', 'mw.reference_snapshots') if m in sys.modules]\n"
            "print(bad)\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         cwd=str(MW.parent))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
