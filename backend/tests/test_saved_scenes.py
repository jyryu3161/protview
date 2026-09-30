"""Real source-bound M9 scenes, bounded images and event-only recovery."""
from __future__ import annotations

import base64
import copy
import json
import struct
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

import mw.api.app as api_module
import mw.saved_scenes as scenes_module
from mw.core.handles import canonical_json, object_sha
from mw.saved_scenes import validate_png

FIX = Path(__file__).parent / "fixtures"


def _id():
    return str(uuid.uuid4())


def _camera():
    return {"mode": "perspective", "fov": 0.8, "position": [1.0, 2.0, 40.0],
            "target": [0.0, 0.0, 0.0], "up": [0.0, 1.0, 0.0], "radius": 10.0,
            "radiusMax": 20.0, "fog": 50.0, "clipFar": True, "minNear": 0.0, "minFar": 0.0}


def _png(width=64, height=64, pixel=b"\x20\x80\xb0\xff"):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = (b"\x00" + pixel * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path)
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")
    rid = client.post("/runs", json={}).json()["run_id"]
    raw = (FIX / "mini_complex.pdb").read_bytes()
    upload = client.post(f"/runs/{rid}/uploads?filename=mini_complex.pdb", content=raw)
    assert upload.status_code == 201
    loaded = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure",
        "args": {"source": upload.json()["upload_id"], "model_index": 0}})
    assert loaded.status_code == 200
    handle = loaded.json()["handle"]["handle"]
    session = client.post(f"/runs/{rid}/viewer/sessions", json={"client_instance_id": _id(),
        "scene_generation": 1, "structure_handle": handle})
    assert session.status_code == 201
    return client, rid, handle, session.json()


def _scene_body(handle, session, **changes):
    body = {"schema": "viewer_scene@1", "name": "view A", "structure_handle": handle,
            "selection": None, "representation": "cartoon", "camera": _camera(), "theme": "dark",
            "client_instance_id": session["client_instance_id"],
            "viewer_session_id": session["viewer_session_id"],
            "scene_generation": session["scene_generation"], "action_revision": 0,
            "request_id": _id()}
    body.update(changes)
    return body


def _figure_body(scene, session, png):
    value = scene["value"]
    return {"schema": "viewer_figure@1", "scene_handle": scene["handle"],
            "structure_handle": value["structure_handle"], "selection": value["selection"],
            "representation": value["representation"], "camera": value["camera"],
            "theme": value["theme"], "png_base64": base64.b64encode(png).decode(),
            "client_instance_id": session["client_instance_id"],
            "viewer_session_id": session["viewer_session_id"],
            "scene_generation": session["scene_generation"], "action_revision": 0,
            "request_id": _id()}


def test_scene_figure_download_and_events_only_replay(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    run = api_module.RUNS[rid]
    before_budget = client.get(f"/runs/{rid}/budget").json()
    before_reports = client.get(f"/runs/{rid}/reports").json()
    before_egress = client.get(f"/runs/{rid}").json()["egress"]
    saved = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session))
    assert saved.status_code == 201, saved.text
    scene = saved.json()
    assert scene["value"]["structure_handle"] == handle
    png = _png()
    figure_response = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(scene, session, png))
    assert figure_response.status_code == 201, figure_response.text
    figure = figure_response.json()
    for fmt, expected in (("png", png), ("json", json.dumps(figure["value"], sort_keys=True,
                                                separators=(",", ":"), ensure_ascii=False).encode())):
        downloaded = client.get(f"/runs/{rid}/viewer/figures/download", params={"handle": figure["handle"], "format": fmt})
        assert downloaded.status_code == 200 and downloaded.content == expected
    assert client.get(f"/runs/{rid}/viewer/scenes").json()["total"] == 1
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 1
    assert client.get(f"/runs/{rid}/budget").json() == before_budget
    assert client.get(f"/runs/{rid}/reports").json() == before_reports
    assert client.get(f"/runs/{rid}").json()["egress"] == before_egress == "local_only"
    run = api_module.RUNS.pop(rid)
    run.store.db.close()
    root = tmp_path / rid
    for item in (root / "objects").iterdir():
        item.unlink()
    (root / "index.sqlite").unlink()
    for item in (root / "uploads").iterdir():
        item.unlink()
    assert client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle": scene["handle"]}).status_code == 200
    assert client.get(f"/runs/{rid}/viewer/figures/download", params={"handle": figure["handle"], "format": "png"}).content == png


def test_scene_binding_names_identity_and_idempotency(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    body = _scene_body(handle, session)
    first = client.post(f"/runs/{rid}/viewer/scenes", json=body)
    assert first.status_code == 201
    second = client.post(f"/runs/{rid}/viewer/scenes", json=body)
    assert second.status_code == 201 and second.json()["handle"] == first.json()["handle"]
    assert client.get(f"/runs/{rid}/viewer/scenes").json()["total"] == 1
    assert client.post(f"/runs/{rid}/viewer/scenes", json={**body, "name": "different"}).status_code == 409
    assert client.post(f"/runs/{rid}/viewer/scenes", json={**body, "request_id": body["request_id"],
        "action_revision": 1}).status_code == 409
    for name in ("", "../bad", "bad\nname"):
        response = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session, name=name))
        if name == "../bad":
            assert response.status_code == 201  # label is safe data, never a path
        else:
            assert response.status_code == 422
    stale = _scene_body(handle, session, scene_generation=2)
    assert client.post(f"/runs/{rid}/viewer/scenes", json=stale).status_code == 409
    foreign = _scene_body(handle.replace(rid, "run_foreign"), session)
    assert client.post(f"/runs/{rid}/viewer/scenes", json=foreign).status_code == 422
    wrong = _scene_body(handle, session, selection={"model_number": 1, "chain_auth": "Z", "seq_auth": 999,
        "icode": "", "chain_label": None, "seq_label": None, "resname": "ALA"})
    assert client.post(f"/runs/{rid}/viewer/scenes", json=wrong).status_code == 422


def test_camera_and_png_limits_before_object_write(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    invalid = _scene_body(handle, session, camera={**_camera(), "up": [0.0, 0.0, 1.0],
                                                  "position": [0.0, 0.0, 40.0]})
    assert client.post(f"/runs/{rid}/viewer/scenes", json=invalid).status_code == 422
    invalid = _scene_body(handle, session, camera={**_camera(), "fov": True})
    assert client.post(f"/runs/{rid}/viewer/scenes", json=invalid).status_code == 422
    scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    good = _png()
    assert validate_png(good) == (64, 64)
    damaged = [good[:-1], good + b"x", good[:29] + b"x" + good[30:], _png(width=2049)]
    # CRC-correct compressed data whose decoded bytes exceed the stated rows.
    idat = zlib.compress(b"\x00" * (64 * 64 * 4 * 4))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    damaged.append(good[:33] + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    for png in damaged:
        response = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(scene, session, png))
        assert response.status_code == 422, response.text
    unicode_image = _figure_body(scene, session, good)
    unicode_image["png_base64"] = "한글"
    response = client.post(f"/runs/{rid}/viewer/figures", json=unicode_image)
    assert response.status_code == 422 and response.json()["detail"]["error"] == "image_invalid"
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 0
    assert not any(event["type"] == "object_created" and event["kind"] == "viewer_png"
                   for event in api_module.RUNS[rid].events.read())


def test_scene_figure_caps_distinct_png_budget_and_request_conflict(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(scenes_module, "MAX_SCENES", 1)
    first = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    same = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session))
    assert same.status_code == 201 and same.json()["handle"] == first["handle"]
    distinct = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session, name="new"))
    assert distinct.status_code == 429
    png = _png()
    monkeypatch.setattr(scenes_module, "MAX_RUN_PNG_BYTES", len(png))
    figure_body = _figure_body(first, session, png)
    figure = client.post(f"/runs/{rid}/viewer/figures", json=figure_body)
    assert figure.status_code == 201, figure.text
    assert client.post(f"/runs/{rid}/viewer/figures", json={**figure_body, "theme": "light"}).status_code == 409
    same_png = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(first, session, png))
    assert same_png.status_code == 201 and same_png.json()["handle"] == figure.json()["handle"]
    changed_png = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(first, session,
        _png(pixel=b"\x40\x70\x90\xff")))
    assert changed_png.status_code == 429
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 1


def test_figure_camera_tolerance_and_exact_other_axes(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    close = _figure_body(scene, session, _png())
    close["camera"] = {**close["camera"], "position": [1.00005, 2.0, 40.0], "fov": 0.8000005}
    assert client.post(f"/runs/{rid}/viewer/figures", json=close).status_code == 201
    far = copy.deepcopy(close); far["request_id"] = _id(); far["camera"]["position"][0] = 1.01
    assert client.post(f"/runs/{rid}/viewer/figures", json=far).status_code == 409
    for key, changed in (("theme", "light"), ("representation", "surface"), ("structure_handle", "foreign")):
        bad = {**close, "request_id": _id(), key: changed}
        assert client.post(f"/runs/{rid}/viewer/figures", json=bad).status_code in (409, 422)


def test_figure_cap_counts_distinct_manifests(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    monkeypatch.setattr(scenes_module, "MAX_FIGURES", 1)
    first = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(scene, session, _png()))
    assert first.status_code == 201
    duplicate = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(scene, session, _png()))
    assert duplicate.status_code == 201 and duplicate.json()["handle"] == first.json()["handle"]
    second = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(scene, session,
        _png(pixel=b"\x40\x70\x90\xff")))
    assert second.status_code == 429 and second.json()["detail"]["error"] == "resource_exceeded"
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 1


def test_rejected_png_budget_does_not_reserve_figure_slot(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    first_scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    second_scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session, name="view B")).json()
    first_png = _png()
    monkeypatch.setattr(scenes_module, "MAX_FIGURES", 2)
    monkeypatch.setattr(scenes_module, "MAX_RUN_PNG_BYTES", len(first_png))
    assert client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(first_scene, session, first_png)).status_code == 201
    before = [event for event in api_module.RUNS[rid].events.read() if event["type"] == "viewer_figure_admitted"]
    rejected = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(second_scene, session,
        _png(pixel=b"\x40\x70\x90\xff")))
    assert rejected.status_code == 429 and rejected.json()["detail"]["error"] == "resource_exceeded"
    after = [event for event in api_module.RUNS[rid].events.read() if event["type"] == "viewer_figure_admitted"]
    assert after == before
    allowed = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(second_scene, session, first_png))
    assert allowed.status_code == 201, allowed.text
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 2


def test_concurrent_request_id_and_stale_session(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    body = _scene_body(handle, session)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(f"/runs/{rid}/viewer/scenes", json=body), range(4)))
    assert [response.status_code for response in responses] == [201] * 4
    assert len({response.json()["handle"] for response in responses}) == 1
    shared = _id()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda name: client.post(f"/runs/{rid}/viewer/scenes",
            json={**body, "request_id": shared, "name": name}), ("first", "second")))
    assert sorted(response.status_code for response in responses) == [201, 409]
    # A changed payload with the same UUID never aliases the existing request.
    assert client.post(f"/runs/{rid}/viewer/scenes", json={**body, "name": "other"}).status_code == 409
    newer = client.post(f"/runs/{rid}/viewer/sessions", json={"client_instance_id": session["client_instance_id"],
        "scene_generation": 2, "structure_handle": handle})
    assert newer.status_code == 201
    assert client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).status_code == 409


def test_prepared_and_multimodel_insertion_identity(monkeypatch, tmp_path):
    client, rid, loaded, session = _setup(monkeypatch, tmp_path)
    prepared = client.post(f"/runs/{rid}/commands", json={"tool": "prepare_structure", "args": {
        "structure": loaded, "altloc": "highest_occupancy", "waters": "strip_all",
        "hydrogens": "strip", "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}})
    assert prepared.status_code == 200, prepared.text
    prepared_handle = prepared.json()["handle"]["handle"]
    prepared_session = client.post(f"/runs/{rid}/viewer/sessions", json={
        "client_instance_id": session["client_instance_id"], "scene_generation": 2,
        "structure_handle": prepared_handle}).json()
    saved = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(prepared_handle, prepared_session))
    assert saved.status_code == 201, saved.text
    assert saved.json()["value"]["structure_kind"] == "prepared_structure"
    fixture = Path(__file__).parents[2] / "frontend/tests/offscreen/fixtures/m9-identities.pdb"
    upload = client.post(f"/runs/{rid}/uploads?filename=m9-identities.pdb", content=fixture.read_bytes())
    assert upload.status_code == 201
    selected = client.post(f"/runs/{rid}/commands", json={"tool": "load_structure", "args": {
        "source": upload.json()["upload_id"], "model_index": 1}})
    assert selected.status_code == 200, selected.text
    second_handle = selected.json()["handle"]["handle"]
    residues = client.get(f"/runs/{rid}/structures/residues", params={"handle": second_handle}).json()
    assert residues["model_number"] == 2
    ref = {key: residues["residues"][0][key] for key in
           ("model_number", "chain_auth", "chain_label", "seq_auth", "seq_label", "icode", "resname")}
    assert ref["icode"] == "A" and ref["seq_label"] is None
    selected_session = client.post(f"/runs/{rid}/viewer/sessions", json={
        "client_instance_id": session["client_instance_id"], "scene_generation": 3,
        "structure_handle": second_handle, "scope_target": ref, "selected_target": ref})
    assert selected_session.status_code == 201, selected_session.text
    identity_scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(second_handle,
        selected_session.json(), selection=ref))
    assert identity_scene.status_code == 201, identity_scene.text
    assert identity_scene.json()["value"]["selection"] == ref
    assert identity_scene.json()["value"]["model_number"] == 2


def test_scene_read_rejects_wrong_kind_missing_and_bad_manifests(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    saved = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    run = api_module.RUNS[rid]
    wrong = client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle": handle})
    assert wrong.status_code == 422
    missing = client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle":
        f"obj://{rid}/viewer_scene/" + "0" * 64})
    assert missing.status_code == 404
    foreign_run = client.post("/runs", json={}).json()["run_id"]
    assert client.get(f"/runs/{foreign_run}/viewer/scenes/selected",
                      params={"handle": saved["handle"]}).status_code in (404, 422)
    for change in ({"renderer": {"name": "molstar", "version": "0", "scene_schema": "protview_scene@1"}},
                   {"name": "bad\nname"}, {"unexpected": 1},
                   {"structure_handle": f"obj://{foreign_run}/structure/" + "0" * 64}):
        artifact = run.store.put("viewer_scene", "viewer_scene@1", {**saved["value"], **change})
        assert client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle": artifact.handle}).status_code == 409
    figure = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(saved, session, _png())).json()
    for change in ({"capture_method": "fake"}, {"renderer": {"name": "fake"}}, {"unexpected": 1}):
        artifact = run.store.put("viewer_figure", "viewer_figure@1", {**figure["value"], **change})
        assert client.get(f"/runs/{rid}/viewer/figures/selected", params={"handle": artifact.handle}).status_code == 409


def test_encoded_body_bounds_before_parsing_or_writes(monkeypatch, tmp_path):
    client, rid, _, _ = _setup(monkeypatch, tmp_path)
    scene_route = f"/runs/{rid}/viewer/scenes"
    figure_route = f"/runs/{rid}/viewer/figures"
    scene_body = b"{" + b" " * (api_module.SCENE_BODY_LIMIT + 1)
    assert client.post(scene_route, content=scene_body,
                       headers={"content-length": str(len(scene_body))}).status_code == 413
    assert client.post(scene_route, content=scene_body,
                       headers={"content-length": "1"}).status_code == 413
    figure_body = b"{" + b" " * (api_module.FIGURE_BODY_LIMIT + 1)
    assert client.post(figure_route, content=figure_body,
                       headers={"content-length": "1"}).status_code == 413
    assert client.get(scene_route).json()["total"] == 0
    assert client.get(figure_route).json()["total"] == 0


def test_scene_admission_survives_each_write_boundary(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    run = api_module.RUNS[rid]
    body = _scene_body(handle, session)
    original_put = run.store.put
    def before_object(kind, *args, **kwargs):
        if kind == "viewer_scene":
            raise RuntimeError("injected before scene object")
        return original_put(kind, *args, **kwargs)
    monkeypatch.setattr(run.store, "put", before_object)
    try:
        client.post(f"/runs/{rid}/viewer/scenes", json=body)
    except RuntimeError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("fault not reached")
    assert client.get(f"/runs/{rid}/viewer/scenes").json()["total"] == 0
    assert client.post(f"/runs/{rid}/viewer/scenes", json={**body, "name": "changed"}).status_code == 409
    monkeypatch.setattr(run.store, "put", original_put)
    original_append = run.events.append
    def before_final(event_type, **payload):
        if event_type == "viewer_scene_saved":
            raise RuntimeError("injected after scene object")
        return original_append(event_type, **payload)
    monkeypatch.setattr(run.events, "append", before_final)
    try:
        client.post(f"/runs/{rid}/viewer/scenes", json=body)
    except RuntimeError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("fault not reached")
    monkeypatch.setattr(run.events, "append", original_append)
    # Durable admission + object bytes make the object visible even without
    # the optional final event, including after an events-only restart.
    assert client.get(f"/runs/{rid}/viewer/scenes").json()["total"] == 1
    api_module.RUNS.pop(rid).store.db.close()
    root = tmp_path / rid
    for item in (root / "objects").iterdir(): item.unlink()
    (root / "index.sqlite").unlink()
    assert client.get(f"/runs/{rid}/viewer/scenes").json()["total"] == 1
    resumed = client.post(f"/runs/{rid}/viewer/scenes", json=body)
    assert resumed.status_code == 201
    assert client.get(f"/runs/{rid}/viewer/scenes").json()["total"] == 1


def test_figure_admission_png_budget_and_final_replay(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(handle, session)).json()
    body = _figure_body(scene, session, _png())
    run = api_module.RUNS[rid]
    monkeypatch.setattr(scenes_module, "MAX_FIGURES", 1)
    monkeypatch.setattr(scenes_module, "MAX_RUN_PNG_BYTES", len(_png()))
    original_put = run.store.put
    def before_figure(kind, *args, **kwargs):
        if kind == "viewer_figure":
            raise RuntimeError("injected after PNG")
        return original_put(kind, *args, **kwargs)
    monkeypatch.setattr(run.store, "put", before_figure)
    try:
        client.post(f"/runs/{rid}/viewer/figures", json=body)
    except RuntimeError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("fault not reached")
    monkeypatch.setattr(run.store, "put", original_put)
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 0
    assert client.post(f"/runs/{rid}/viewer/figures", json={**body, "theme": "light"}).status_code == 409
    assert client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(scene, session,
        _png(pixel=b"\x40\x70\x90\xff"))).status_code == 429
    api_module.RUNS.pop(rid).store.db.close()
    root = tmp_path / rid
    for item in (root / "objects").iterdir(): item.unlink()
    (root / "index.sqlite").unlink()
    resumed = client.post(f"/runs/{rid}/viewer/figures", json=body)
    assert resumed.status_code == 201, resumed.text
    assert client.get(f"/runs/{rid}/viewer/figures").json()["total"] == 1


# --- M16: viewer_scene@2 / viewer_figure@2 (annotation provenance) ---------------------------------------------

# Pinned on the pre-M16 code (commit a9f3fe3) with the mini_complex fixture and the default _scene_body/_png: the
# sha256 of the canonical stored value after replacing the run id, the loaded structure handle and the scene handle
# (the structure handle differs per upload) with placeholders. Saving without an annotation must keep producing
# exactly these bytes, and the handles must stay the viewer_scene@1 / viewer_figure@1 object identities.
GOLDEN_SCENE_SHA = "f24f0e63e9d028eedd97eb796cc531b6f5fb4539da6626504d43411b30751bb6"
GOLDEN_FIGURE_SHA = "f30bdf0d94023b8a3c0ef4013acc78229e3a3d89d8dc70fb13bfdd93e21b1abc"
CIF_1MQ4 = FIX / "public_1mq4.cif"
ADP = {"model_number": 1, "chain_auth": "A", "seq_auth": 2001, "icode": "", "resname": "ADP"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _normalized(value, rid, structure, scene):
    raw = _canonical(value).replace(structure.encode(), b"STRUCTURE").replace(scene.encode(), b"SCENE")
    return raw.replace(rid.encode(), b"RID")


def _sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def test_scene_and_figure_without_annotation_match_pre_m16_golden(monkeypatch, tmp_path):
    client, rid, handle, session = _setup(monkeypatch, tmp_path)
    body = _scene_body(handle, session)
    scene = client.post(f"/runs/{rid}/viewer/scenes", json=body)
    assert scene.status_code == 201, scene.text
    scene = scene.json()
    assert scene["value"]["schema"] == "viewer_scene@1" and "annotation" not in scene["value"]
    assert _sha(_normalized(scene["value"], rid, handle, scene["handle"])) == GOLDEN_SCENE_SHA
    assert scene["handle"] == f"obj://{rid}/viewer_scene/" + object_sha("viewer_scene", "viewer_scene@1",
                                                                          canonical_json(scene["value"]))
    figure_body = _figure_body(scene, session, _png())
    figure = client.post(f"/runs/{rid}/viewer/figures", json=figure_body)
    assert figure.status_code == 201, figure.text
    figure = figure.json()
    assert figure["value"]["schema"] == "viewer_figure@1" and "annotation" not in figure["value"]
    assert _sha(_normalized(figure["value"], rid, handle, scene["handle"])) == GOLDEN_FIGURE_SHA
    assert figure["handle"] == f"obj://{rid}/viewer_figure/" + object_sha("viewer_figure", "viewer_figure@1",
                                                                            canonical_json(figure["value"]))
    # The idempotency hash is still the request body without request_id (no added default keys).
    run = api_module.RUNS[rid]
    for event_type, sent in (("viewer_scene_saved", body), ("viewer_figure_saved", figure_body)):
        event = next(e for e in run.events.read() if e["type"] == event_type)
        expected = {key: value for key, value in sent.items() if key != "request_id"}
        assert event["payload_sha256"] == _sha(_canonical(expected))
    # An annotation field on a viewer_scene@1 body and a legend flag on a viewer_figure@1 body are unknown fields.
    extra = {**_scene_body(handle, session), "annotation": {"handle": handle, "legend": True}}
    assert client.post(f"/runs/{rid}/viewer/scenes", json=extra).status_code == 422
    extra = {**_figure_body(scene, session, _png()), "legend_composited": False}
    assert client.post(f"/runs/{rid}/viewer/figures", json=extra).status_code == 422


def _m16_setup(monkeypatch, tmp_path):
    from reference_fixture_set import build_fixture_set

    from mw import reference_snapshots as rs
    root = tmp_path / "reference"
    root.mkdir()
    monkeypatch.setenv(rs.ENV_VAR, str(root))
    build_fixture_set(root)
    monkeypatch.setattr(api_module, "RUNS_DIR", tmp_path / "runs")
    api_module.RUNS.clear()
    client = TestClient(api_module.app, base_url="http://127.0.0.1")

    def new_run():
        rid = client.post("/runs", json={}).json()["run_id"]
        upload = client.post(f"/runs/{rid}/uploads", params={"filename": "1mq4.cif"},
                             content=CIF_1MQ4.read_bytes()).json()

        def command(tool, args):
            response = client.post(f"/runs/{rid}/commands", json={"tool": tool, "args": args})
            assert response.status_code == 200, response.text
            return response.json()["handle"]["handle"]
        structure = command("load_structure", {"source": upload["upload_id"]})
        prepared = command("prepare_structure", {"structure": structure})
        numbering_map = command("map_residue_numbering", {"structure": prepared, "pdb_id": "1MQ4",
                                                          "chains": [{"chain_auth": "A"}]})
        contacts = command("compute_interactions", {"structure": prepared, "ligand": ADP})
        annotation = command("annotate_reference_sites", {"numbering_map": numbering_map, "contacts": contacts})
        bare = command("annotate_reference_sites", {"numbering_map": numbering_map})
        return {"rid": rid, "structure": structure, "prepared": prepared, "numbering_map": numbering_map,
                "contacts": contacts, "annotation": annotation, "bare": bare}
    return client, new_run


def _session(client, rid, structure, generation, client_id):
    response = client.post(f"/runs/{rid}/viewer/sessions", json={"client_instance_id": client_id,
                           "scene_generation": generation, "structure_handle": structure})
    assert response.status_code == 201, response.text
    return response.json()


def _scene2(handle, session, annotation, legend=True, **changes):
    return _scene_body(handle, session, schema="viewer_scene@2",
                       annotation={"handle": annotation, "legend": legend}, **changes)


def _figure2(scene, session, png, composited):
    return {**_figure_body(scene, session, png), "schema": "viewer_figure@2", "legend_composited": composited}


def _admissions(client, rid):
    return [e for e in api_module.RUNS[rid].events.read() if e["type"].startswith("viewer_") and
            e["type"].endswith(("_admitted", "_saved"))]


def test_scene_v2_save_validates_the_annotation(monkeypatch, tmp_path):
    client, new_run = _m16_setup(monkeypatch, tmp_path)
    r = new_run()
    other = new_run()
    rid, prepared = r["rid"], r["prepared"]
    client_id = _id()
    original_session = _session(client, rid, r["structure"], 1, client_id)
    # The annotation is on the prepared structure; a scene of the original structure must not carry it.
    mismatch = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(r["structure"], original_session,
                                                                       r["annotation"]))
    assert mismatch.status_code == 422 and mismatch.json()["detail"]["error"] == "structure_mismatch"
    session = _session(client, rid, prepared, 2, client_id)
    for wrong in (r["numbering_map"], r["contacts"], prepared, other["annotation"],
                  f"obj://{rid}/reference_site_annotation/" + "0" * 64, "not-a-handle"):
        response = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(prepared, session, wrong))
        assert response.status_code == 422 and response.json()["detail"]["error"] == "input_invalid", wrong
    malformed = [
        _scene_body(prepared, session, schema="viewer_scene@2"),                           # annotation missing
        _scene2(prepared, session, r["annotation"], legend="yes"),
        _scene2(prepared, session, r["annotation"], legend=1),
        {**_scene2(prepared, session, r["annotation"]), "annotation": {"handle": r["annotation"]}},
        {**_scene2(prepared, session, r["annotation"]),
         "annotation": {"handle": r["annotation"], "legend": True, "extra": 1}},
        {**_scene2(prepared, session, r["annotation"]), "unexpected": 1},
        _scene_body(prepared, session, schema="viewer_scene@3"),
    ]
    for body in malformed:
        assert client.post(f"/runs/{rid}/viewer/scenes", json=body).status_code == 422, body
    assert _admissions(client, rid) == []
    body = _scene2(prepared, session, r["annotation"])
    saved = client.post(f"/runs/{rid}/viewer/scenes", json=body)
    assert saved.status_code == 201, saved.text
    value = saved.json()["value"]
    assert value["schema"] == "viewer_scene@2"
    assert value["annotation"] == {"handle": r["annotation"], "legend": True}
    plain = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(prepared, session)).json()["value"]
    assert {key: val for key, val in value.items() if key not in ("schema", "annotation")} == \
        {key: val for key, val in plain.items() if key != "schema"}
    assert client.post(f"/runs/{rid}/viewer/scenes", json=body).json()["handle"] == saved.json()["handle"]
    changed = {**body, "annotation": {"handle": r["annotation"], "legend": False}}
    assert client.post(f"/runs/{rid}/viewer/scenes", json=changed).status_code == 409
    off = client.post(f"/runs/{rid}/viewer/scenes", json={**changed, "request_id": _id()})
    assert off.status_code == 201 and off.json()["handle"] != saved.json()["handle"]
    assert off.json()["value"]["annotation"]["legend"] is False
    bare = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(prepared, session, r["bare"]))
    assert bare.status_code == 201


def test_figure_v2_records_annotation_provenance_and_capture_method(monkeypatch, tmp_path):
    client, new_run = _m16_setup(monkeypatch, tmp_path)
    r = new_run()
    rid, prepared = r["rid"], r["prepared"]
    session = _session(client, rid, prepared, 1, _id())
    on = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(prepared, session, r["annotation"])).json()
    off = client.post(f"/runs/{rid}/viewer/scenes",
                      json=_scene2(prepared, session, r["annotation"], legend=False, name="no legend")).json()
    plain = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(prepared, session, name="plain")).json()
    content = client.get(f"/runs/{rid}/site_annotations/detail", params={"handle": r["annotation"]}).json()
    content = content["annotation"]
    labels = [site["display_label"] for group in content["groups"] for site in group["sites"]
              if site["status"] == "annotated"]
    assert "Glu211 (hinge.46)" in labels and len(labels) == 10
    png = _png()
    composited = client.post(f"/runs/{rid}/viewer/figures", json=_figure2(on, session, png, True))
    assert composited.status_code == 201, composited.text
    value = composited.json()["value"]
    assert value["schema"] == "viewer_figure@2" and value["capture_method"] == "molstar_image_pass+legend"
    assert value["annotation"] == {"handle": r["annotation"], "legend": True, "numbering_map": r["numbering_map"],
                                   "contacts": r["contacts"], "snapshot_set_hash": content["snapshot_set_hash"],
                                   "display_labels": labels}
    plain_figure = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(plain, session, png)).json()["value"]
    assert {key: val for key, val in value.items() if key not in ("schema", "annotation", "scene_handle",
                                                                  "capture_method")} == \
        {key: val for key, val in plain_figure.items() if key not in ("schema", "scene_handle", "capture_method")}
    # Legend on but nothing composited (e.g. no dashed line): the existing capture method.
    not_composited = client.post(f"/runs/{rid}/viewer/figures", json=_figure2(on, session, _png(pixel=b"\x40\x70\x90\xff"),
                                                                             False))
    assert not_composited.status_code == 201
    assert not_composited.json()["value"]["capture_method"] == "molstar_image_pass"
    no_legend = client.post(f"/runs/{rid}/viewer/figures", json=_figure2(off, session, png, False))
    assert no_legend.status_code == 201
    assert no_legend.json()["value"]["capture_method"] == "molstar_image_pass"
    assert no_legend.json()["value"]["annotation"]["legend"] is False
    before = _admissions(client, rid)
    # A composited legend on a legend-off scene, or a schema that does not match the scene, is refused.
    rejected = client.post(f"/runs/{rid}/viewer/figures", json=_figure2(off, session, png, True))
    assert rejected.status_code == 422 and rejected.json()["detail"]["error"] == "input_invalid"
    assert client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(on, session, png)).status_code == 409
    assert client.post(f"/runs/{rid}/viewer/figures", json=_figure2(plain, session, png, False)).status_code == 409
    assert client.post(f"/runs/{rid}/viewer/figures", json=_figure2(on, session, png, "yes")).status_code == 422
    missing = {key: val for key, val in _figure2(on, session, png, True).items() if key != "legend_composited"}
    assert client.post(f"/runs/{rid}/viewer/figures", json=missing).status_code == 422
    assert _admissions(client, rid) == before
    bare_scene = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(prepared, session, r["bare"],
                                                                        name="bare")).json()
    bare_figure = client.post(f"/runs/{rid}/viewer/figures", json=_figure2(bare_scene, session, png, False))
    assert bare_figure.status_code == 201 and bare_figure.json()["value"]["annotation"]["contacts"] is None
    handle = composited.json()["handle"]
    downloaded = client.get(f"/runs/{rid}/viewer/figures/download", params={"handle": handle, "format": "json"})
    assert downloaded.status_code == 200 and downloaded.content == _canonical(value)
    downloaded = client.get(f"/runs/{rid}/viewer/figures/download", params={"handle": handle, "format": "png"})
    assert downloaded.content == png


def test_mixed_v1_v2_list_detail_download_tamper_and_events_only_recovery(monkeypatch, tmp_path):
    import shutil
    client, new_run = _m16_setup(monkeypatch, tmp_path)
    r = new_run()
    rid, prepared = r["rid"], r["prepared"]
    session = _session(client, rid, prepared, 1, _id())
    v1 = client.post(f"/runs/{rid}/viewer/scenes", json=_scene_body(prepared, session)).json()
    v2 = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(prepared, session, r["annotation"])).json()
    png = _png()
    f1 = client.post(f"/runs/{rid}/viewer/figures", json=_figure_body(v1, session, png)).json()
    f2 = client.post(f"/runs/{rid}/viewer/figures", json=_figure2(v2, session, png, True)).json()
    scenes = client.get(f"/runs/{rid}/viewer/scenes").json()
    figures = client.get(f"/runs/{rid}/viewer/figures").json()
    assert [row["handle"] for row in scenes["rows"]] == [v2["handle"], v1["handle"]] and scenes["total"] == 2
    assert [row["handle"] for row in figures["rows"]] == [f2["handle"], f1["handle"]] and figures["total"] == 2
    events_before = client.get(f"/runs/{rid}/events", params={"limit": 500}).json()
    expected = {}
    for scene in (v1, v2):
        detail = client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle": scene["handle"]})
        assert detail.status_code == 200 and detail.json() == scene
    for figure in (f1, f2):
        detail = client.get(f"/runs/{rid}/viewer/figures/selected", params={"handle": figure["handle"]})
        assert detail.status_code == 200 and detail.json() == figure
        for fmt in ("png", "json"):
            response = client.get(f"/runs/{rid}/viewer/figures/download",
                                  params={"handle": figure["handle"], "format": fmt})
            assert response.status_code == 200
            expected[(figure["handle"], fmt)] = response.content
    assert expected[(f2["handle"], "json")] == _canonical(f2["value"])
    assert client.get(f"/runs/{rid}/events", params={"limit": 500}).json() == events_before
    run = api_module.RUNS[rid]
    # Tampered viewer_scene@2 / viewer_figure@2 manifests are refused on read.
    for change in ({"annotation": {"handle": r["numbering_map"], "legend": True}},
                   {"annotation": {"handle": r["annotation"], "legend": True, "x": 1}},
                   {"annotation": None}, {"structure_handle": r["structure"]}):
        artifact = run.store.put("viewer_scene", "viewer_scene@2", {**v2["value"], **change})
        assert client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle": artifact.handle}).status_code == 409
    no_legend = client.post(f"/runs/{rid}/viewer/scenes", json=_scene2(prepared, session, r["annotation"],
                                                                        legend=False, name="off")).json()
    annotation = f2["value"]["annotation"]
    for change in ({"annotation": {**annotation, "display_labels": ["Met1 (hinge.46)"]}},
                   {"annotation": {**annotation, "contacts": None}},
                   {"annotation": {**annotation, "legend": False}},
                   {"scene_handle": no_legend["handle"],
                    "annotation": {**annotation, "legend": False}},                  # +legend on a legend-off scene
                   {"scene_handle": v1["handle"]}, {"capture_method": "fake"}, {"annotation": None}):
        artifact = run.store.put("viewer_figure", "viewer_figure@2", {**f2["value"], **change})
        assert client.get(f"/runs/{rid}/viewer/figures/selected", params={"handle": artifact.handle}).status_code == 409
    artifact = run.store.put("viewer_figure", "viewer_figure@1", {**f1["value"], "scene_handle": v2["handle"]})
    assert client.get(f"/runs/{rid}/viewer/figures/selected", params={"handle": artifact.handle}).status_code == 409
    # Events-only recovery: objects, SQLite, uploads and the reference folder removed.
    api_module.RUNS.pop(rid).store.db.close()
    root = tmp_path / "runs" / rid
    shutil.rmtree(root / "objects")
    (root / "index.sqlite").unlink()
    shutil.rmtree(root / "uploads", ignore_errors=True)
    shutil.rmtree(tmp_path / "reference")
    assert [row["handle"] for row in client.get(f"/runs/{rid}/viewer/scenes").json()["rows"]] == \
        [no_legend["handle"], v2["handle"], v1["handle"]]
    assert client.get(f"/runs/{rid}/viewer/scenes/selected", params={"handle": v2["handle"]}).json() == v2
    assert client.get(f"/runs/{rid}/viewer/figures/selected", params={"handle": f2["handle"]}).json() == f2
    for (handle, fmt), raw in expected.items():
        response = client.get(f"/runs/{rid}/viewer/figures/download", params={"handle": handle, "format": fmt})
        assert response.status_code == 200 and response.content == raw
