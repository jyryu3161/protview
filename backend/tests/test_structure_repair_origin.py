"""M29 T4: ``structure_origin`` / ``is_repaired`` / ``reject_if_repaired`` decide by the manifest ``repair`` key only
(spec 3.1, 5.2, 6.1). The repaired objects are stored here in the spec order (coordinates -> record -> manifest ->
structure) from a real 1HSG build with the PDBFixer-measured additions; T5 owns the product publication path."""
from __future__ import annotations

import pytest
import test_structure_repair_common as C

from mw import structure_origin as so
from mw import structure_repair as sr
from mw import structure_repair_constants as K
from mw.core.errors import ToolFailure
from mw.tools.structural import structure_residues


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    C.use_root(tmp_path_factory.mktemp("m29_t4_origin"))
    inputs, run = C.prepared((C.FIX / "public_1hsg.cif").read_bytes(), "cif", "keep_all")
    raw, record = sr.build_repaired(inputs, C.additions("1hsg"))
    store = run.store
    coordinates = store.put(K.COORDINATES_KIND, K.COORDINATES_SCHEMA, raw, fmt=K.COORDINATES_FMT, produced_by="test")
    stored = store.put(K.KIND, K.SCHEMA, record, produced_by="test")
    original = store.load(inputs.prepared_structure)
    manifest = {**store.load(original["manifest"]), "missing_residues": K.MISSING_RESIDUES_LEFT,
                K.MANIFEST_REPAIR_KEY: {"record": stored.handle, "source": inputs.prepared_structure}}
    manifest_handle = store.put(K.MANIFEST_KIND, K.MANIFEST_SCHEMA, manifest, produced_by="test").handle
    repaired = store.put(K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, {
        "coordinates": coordinates.handle, "manifest": manifest_handle, "model_index": original["model_index"],
        "model_number": original["model_number"]}, produced_by="test").handle
    return {"store": store, "inputs": inputs, "record": record, "record_handle": stored.handle, "raw": raw,
            "coordinates": coordinates.handle, "repaired": repaired, "manifest": manifest}


def test_the_record_names_the_coordinates_object_it_will_be_stored_as(world):
    assert world["record"]["result"]["coordinates"] == world["coordinates"]
    store = world["store"]
    reloaded = sr.validated_repair(world["inputs"], store.load(world["coordinates"]), store.load(world["record_handle"]))
    assert reloaded == world["record"]


def test_origin_of_a_repaired_structure(world):
    store = world["store"]
    assert so.is_repaired(store, world["repaired"]) is True
    assert so.structure_origin(store, world["repaired"]) == {
        "repair_record": world["record_handle"], "repaired_structure": world["repaired"],
        "source_structure": world["inputs"].prepared_structure, "counts": world["record"]["counts"]}
    with pytest.raises(ToolFailure) as caught:
        so.reject_if_repaired(store, world["repaired"])
    assert caught.value.cls.value == "input_invalid"
    assert (caught.value.message, caught.value.detail) == ("보완 구조는 모델링 경로에서만 쓴다",
                                                           {"reason_code": "repaired_structure_not_accepted"})


def test_everything_else_is_not_a_repaired_structure(world):
    store = world["store"]
    other_run = "obj://run_other/prepared_structure/" + "0" * 64
    unknown = f"obj://{store.run_id}/prepared_structure/" + "1" * 64
    for handle in (world["inputs"].prepared_structure, world["coordinates"], world["record_handle"], other_run, unknown,
                   None, 3, "not a handle"):
        assert so.is_repaired(store, handle) is False
        assert so.structure_origin(store, handle) is None
        assert so.reject_if_repaired(store, handle) is None


def test_a_malformed_link_is_still_refused_and_never_described(world):
    store = world["store"]
    manifest = {**world["manifest"], K.MANIFEST_REPAIR_KEY: {"record": world["coordinates"],
                                                             "source": world["inputs"].prepared_structure}}
    handle = store.put(K.MANIFEST_KIND, K.MANIFEST_SCHEMA, manifest, produced_by="test").handle
    structure = store.put(K.STRUCTURE_KIND, K.STRUCTURE_SCHEMA, {
        **store.load(world["repaired"]), "manifest": handle}, produced_by="test").handle
    assert so.is_repaired(store, structure) is True
    with pytest.raises(ToolFailure) as caught:
        so.structure_origin(store, structure)
    assert caught.value.detail == {"reason_code": "repair_record_mismatch"}
    with pytest.raises(ToolFailure):
        so.reject_if_repaired(store, structure)


def test_the_product_structure_reader_accepts_the_calc_flag_column(world):
    residues = structure_residues(world["store"], world["repaired"])
    original = structure_residues(world["store"], world["inputs"].prepared_structure)
    key = ("chain_auth", "seq_auth", "icode", "chain_label", "seq_label", "resname")
    assert sorted(tuple(r[k] for k in key) for r in residues["residues"]) == sorted(
        tuple(r[k] for k in key) for r in original["residues"])
    assert b"_atom_site.calc_flag" in world["raw"]
