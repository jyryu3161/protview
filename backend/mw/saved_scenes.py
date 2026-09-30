"""Immutable local viewer scenes and client-rendered figures.

Viewer state is not scientific evidence. The server validates source identity and
durable bytes, while the offscreen QA renderer independently checks pixels.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import math
import struct
import uuid
import zlib
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from . import site_annotation as site_annotations
from .core.errors import ToolFailure
from .core.handles import canonical_json, object_sha, sha256_hex
from .openmm_reports import validated_minimized_structure
from .tools.structural import structure_residues
from .viewer_intents import ViewerError, _current_session, _session

SCENE_SCHEMA = "viewer_scene@1"
FIGURE_SCHEMA = "viewer_figure@1"
# M16: a scene saved with a reference site annotation shown, and its figures. @1 stays unchanged.
SCENE_SCHEMA_V2 = "viewer_scene@2"
FIGURE_SCHEMA_V2 = "viewer_figure@2"
SCENE_SCHEMAS = (SCENE_SCHEMA, SCENE_SCHEMA_V2)
FIGURE_SCHEMAS = (FIGURE_SCHEMA, FIGURE_SCHEMA_V2)
CAPTURE_METHOD = "molstar_image_pass"
CAPTURE_METHOD_LEGEND = "molstar_image_pass+legend"
PNG_SCHEMA = "viewer_png@1"
RENDERER = {"name": "molstar", "version": "5.11.0", "scene_schema": "protview_scene@1"}
LIMITATIONS = "Client-rendered molecular view; this figure is not a new scientific measurement."
SOURCE_SCHEMAS = {
    ("structure", "structure_selection@2"),
    ("prepared_structure", "prepared_structure@1"),
    ("openmm_minimized_structure", "openmm_minimized_structure@1"),
}
MAX_PNG = 8 * 1024 * 1024
MAX_SCENES = 100
MAX_FIGURES = 100
MAX_RUN_PNG_BYTES = 64 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ExactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ExactResidue(ExactModel):
    model_number: StrictInt
    chain_auth: str
    seq_auth: StrictInt
    icode: str
    chain_label: str | None
    seq_label: StrictInt | None
    resname: str


class CameraState(ExactModel):
    mode: Literal["perspective", "orthographic"]
    fov: StrictFloat
    position: list[StrictFloat]
    up: list[StrictFloat]
    target: list[StrictFloat]
    radius: StrictFloat
    radiusMax: StrictFloat
    fog: StrictFloat
    clipFar: StrictBool
    minNear: StrictFloat
    minFar: StrictFloat

    @field_validator("position", "up", "target")
    @classmethod
    def vec3(cls, value: list[float]) -> list[float]:
        if len(value) != 3:
            raise ValueError("camera vector requires exactly three components")
        return value

    @model_validator(mode="after")
    def bounded(self) -> CameraState:
        scalars = (self.fov, self.radius, self.radiusMax, self.fog, self.minNear, self.minFar)
        if not all(math.isfinite(value) for value in (*scalars, *self.position, *self.target, *self.up)):
            raise ValueError("nonfinite camera")
        if any(abs(value) > 1e7 for value in (*self.position, *self.target)):
            raise ValueError("camera coordinate out of bounds")
        direction = tuple(p - t for p, t in zip(self.position, self.target))
        distance = math.sqrt(sum(value * value for value in direction))
        up_norm = math.sqrt(sum(value * value for value in self.up))
        if not 1e-4 <= distance <= 1e7 or not 0.5 <= up_norm <= 2:
            raise ValueError("camera distance or up invalid")
        cross = (direction[1] * self.up[2] - direction[2] * self.up[1],
                 direction[2] * self.up[0] - direction[0] * self.up[2],
                 direction[0] * self.up[1] - direction[1] * self.up[0])
        if math.sqrt(sum(value * value for value in cross)) / (distance * up_norm) < 1e-4:
            raise ValueError("camera up is parallel to view")
        if not (0.01 <= self.fov <= 3.13 and 1e-4 <= self.radius <= self.radiusMax <= 1e7 and
                0 <= self.fog <= 100 and 0 <= self.minNear <= 1e7 and 0 <= self.minFar <= 1e7):
            raise ValueError("camera scalar out of bounds")
        return self


class Binding(ExactModel):
    client_instance_id: str
    viewer_session_id: str
    scene_generation: StrictInt
    action_revision: StrictInt
    request_id: str

    @field_validator("client_instance_id", "viewer_session_id", "request_id")
    @classmethod
    def uuid_only(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError("invalid UUID") from exc
        if str(parsed) != value:
            raise ValueError("noncanonical UUID")
        return value


class SceneSave(Binding):
    schema_: Literal["viewer_scene@1"] = Field(alias="schema")
    name: str
    structure_handle: str
    selection: ExactResidue | None
    representation: Literal["cartoon", "ball_and_stick", "surface"]
    camera: CameraState
    theme: Literal["dark", "light"]

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _valid_name(value)


class SceneAnnotation(ExactModel):
    handle: str
    legend: StrictBool


class SceneSaveV2(SceneSave):
    schema_: Literal["viewer_scene@2"] = Field(alias="schema")
    annotation: SceneAnnotation


def _valid_name(value: str) -> str:
    if value != value.strip() or not 1 <= len(value) <= 80 or len(value.encode("utf-8")) > 320:
        raise ValueError("invalid scene name")
    if any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value):
        raise ValueError("control character in scene name")
    return value


class Renderer(ExactModel):
    name: Literal["molstar"]
    version: Literal["5.11.0"]
    scene_schema: Literal["protview_scene@1"]


class SceneArtifact(ExactModel):
    schema_: Literal["viewer_scene@1"] = Field(alias="schema")
    name: str
    structure_handle: str
    structure_kind: Literal["structure", "prepared_structure", "openmm_minimized_structure"]
    structure_schema: Literal["structure_selection@2", "prepared_structure@1", "openmm_minimized_structure@1"]
    model_number: StrictInt
    selection: ExactResidue | None
    representation: Literal["cartoon", "ball_and_stick", "surface"]
    camera: CameraState
    theme: Literal["dark", "light"]
    renderer: Renderer

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _valid_name(value)


class SceneArtifactV2(SceneArtifact):
    schema_: Literal["viewer_scene@2"] = Field(alias="schema")
    annotation: SceneAnnotation


class FigureArtifact(ExactModel):
    schema_: Literal["viewer_figure@1"] = Field(alias="schema")
    scene_handle: str
    structure_handle: str
    model_number: StrictInt
    png_handle: str
    png_sha256: str
    width: StrictInt
    height: StrictInt
    media_type: Literal["image/png"]
    renderer: Renderer
    capture_method: Literal["molstar_image_pass"]
    provenance: Literal["client_rendered_local_view"]
    limitations: Literal["Client-rendered molecular view; this figure is not a new scientific measurement."]


class FigureSave(Binding):
    schema_: Literal["viewer_figure@1"] = Field(alias="schema")
    scene_handle: str
    structure_handle: str
    selection: ExactResidue | None
    representation: Literal["cartoon", "ball_and_stick", "surface"]
    camera: CameraState
    theme: Literal["dark", "light"]
    png_base64: str


class FigureAnnotation(ExactModel):
    handle: str
    legend: StrictBool
    numbering_map: str
    contacts: str | None
    snapshot_set_hash: str
    display_labels: list[str]


class FigureArtifactV2(FigureArtifact):
    schema_: Literal["viewer_figure@2"] = Field(alias="schema")
    capture_method: Literal["molstar_image_pass", "molstar_image_pass+legend"]
    annotation: FigureAnnotation


class FigureSaveV2(FigureSave):
    schema_: Literal["viewer_figure@2"] = Field(alias="schema")
    # True when the client drew the fixed legend text into the PNG (only allowed when the scene's legend is on).
    legend_composited: StrictBool


_SCENE_SAVE = TypeAdapter(Annotated[SceneSave | SceneSaveV2, Field(discriminator="schema_")])
_FIGURE_SAVE = TypeAdapter(Annotated[FigureSave | FigureSaveV2, Field(discriminator="schema_")])


def parse_scene_save(raw: bytes) -> SceneSave:
    """``viewer_scene@1`` or ``viewer_scene@2`` save body by its ``schema``; pydantic ValidationError otherwise."""
    return _SCENE_SAVE.validate_json(raw)


def parse_figure_save(raw: bytes) -> FigureSave:
    """``viewer_figure@1`` or ``viewer_figure@2`` save body by its ``schema``; pydantic ValidationError otherwise."""
    return _FIGURE_SAVE.validate_json(raw)


def _source(run: Any, handle: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        meta = run.store.meta(handle)
        if (meta["kind"], meta["schema"]) not in SOURCE_SCHEMAS:
            raise ViewerError("input_invalid", "unsupported scene source kind")
        if meta["kind"] == "openmm_minimized_structure":
            validated_minimized_structure(run, handle)
        residues = structure_residues(run.store, handle)
    except (KeyError, ValueError, ToolFailure) as exc:
        raise ViewerError("scene_invalid", "scene source is missing or corrupt", 422) from exc
    return meta, residues


def _selection(residues: dict[str, Any], selection: ExactResidue | None) -> dict[str, Any] | None:
    if selection is None:
        return None
    expected = selection.model_dump()
    matches = [row for row in residues["residues"] if all(row[key] == value for key, value in expected.items())]
    if len(matches) != 1:
        raise ViewerError("scene_invalid", "selected residue is not a unique authoritative source residue")
    return expected


def _annotation(run: Any, handle: str, structure_handle: str) -> dict[str, Any]:
    """The same run's ``reference_site_annotation@1`` whose structure is the scene source (typed failure otherwise)."""
    if not handle.startswith(f"obj://{run.run_id}/"):
        raise ViewerError("input_invalid", "annotation handle is not an object of this run")
    try:
        meta = run.store.meta(handle)
    except KeyError as exc:
        raise ViewerError("input_invalid", "annotation not found in this run") from exc
    if (meta["kind"], meta["schema"]) != (site_annotations.KIND, site_annotations.SCHEMA):
        raise ViewerError("input_invalid", "handle is not a reference site annotation")
    try:
        content = run.store.load(handle)
        if type(content) is not dict or content.get("schema") != site_annotations.SCHEMA:
            raise ValueError("annotation payload invalid")
        annotated_structure = content["structure"]["handle"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ViewerError("scene_invalid", "annotation is missing or corrupt", 409) from exc
    if annotated_structure != structure_handle:
        raise ViewerError("structure_mismatch", "annotation structure differs from the scene source")
    return content


def _figure_annotation(run: Any, scene: dict[str, Any]) -> dict[str, Any]:
    """``viewer_figure@2`` annotation provenance, copied from the stored annotation object (nothing recomputed)."""
    content = _annotation(run, scene["annotation"]["handle"], scene["structure_handle"])
    return {"handle": scene["annotation"]["handle"], "legend": scene["annotation"]["legend"],
            "numbering_map": content["numbering_map"],
            "contacts": content["contacts"]["handle"] if content["contacts"] is not None else None,
            "snapshot_set_hash": content["snapshot_set_hash"],
            "display_labels": [site["display_label"] for group in content["groups"] for site in group["sites"]
                               if site["status"] == "annotated"]}


def _binding(run: Any, body: Binding, structure_handle: str, representation: str,
             selection: dict[str, Any] | None) -> None:
    session = _session(run, body.viewer_session_id)
    if (not _current_session(run, session) or session["client_instance_id"] != body.client_instance_id or
            session["scene_generation"] != body.scene_generation or
            session["structure_handle"] != structure_handle or
            session["action_revision"] != body.action_revision or
            session["representation"] != representation):
        raise ViewerError("stale_scene", "saved scene binding is stale", 409)
    selected_alias = session["selected_alias"]
    if selected_alias is not None:
        if selection is None or session["mapping"].get(selected_alias) != selection:
            raise ViewerError("stale_scene", "saved selection differs from current session", 409)
    elif selection is not None:
        aliases = [alias for alias, ref in session["mapping"].items() if ref == selection]
        if aliases:
            raise ViewerError("stale_scene", "saved selection differs from current session", 409)


def _records(run: Any, event_type: str) -> list[dict[str, Any]]:
    return [event for event in run.events.read() if event["type"] == event_type]


def _admission_type(event_type: str) -> str:
    return event_type.replace("_saved", "_admitted")


def _completed_handles(run: Any, event_type: str, kind: str, schemas: tuple[str, ...]) -> list[str]:
    """An admitted object is visible once its immutable bytes are durable.

    A crash after ObjectStore.put but before the final event cannot hide a
    persisted artifact or free its capacity reservation.
    """
    admitted = [event["handle"] for event in run.events.read()
                if event["type"] in (event_type, _admission_type(event_type))]
    handles = []
    for handle in dict.fromkeys(admitted):
        try:
            meta = run.store.meta(handle)
        except KeyError:
            continue
        if meta["kind"] == kind and meta["schema"] in schemas:
            handles.append(handle)
    handles.reverse()
    return handles


def _admit(run: Any, event_type: str, body: Binding, payload_hash: str, cap: int,
           candidate_handle: str) -> dict[str, Any] | None:
    records = [event for event in run.events.read()
               if event["type"] in (event_type, _admission_type(event_type))]
    existing = next((event for event in reversed(records) if event["request_id"] == body.request_id), None)
    if existing is not None:
        if existing["payload_sha256"] != payload_hash:
            raise ViewerError("request_conflict", "request UUID was reused with different content", 409)
        return existing
    handles = {event["handle"] for event in records}
    if len(handles) >= cap and candidate_handle not in handles:
        raise ViewerError("resource_exceeded", "saved viewer artifact limit reached", 429)
    return None


def _request_hash(body: Binding) -> str:
    # Request idempotency includes the binding; immutable object identity does not.
    payload = body.model_dump(by_alias=True)
    del payload["request_id"]
    return sha256_hex(canonical_json(payload))


def _detail(run: Any, handle: str, kind: str, schemas: tuple[str, ...]) -> dict[str, Any]:
    try:
        meta = run.store.meta(handle)
        if meta["kind"] != kind or meta["schema"] not in schemas:
            raise ViewerError("input_invalid", "wrong saved viewer artifact kind")
        value = run.store.load(handle)
        if not isinstance(value, dict) or value.get("schema") != meta["schema"]:
            raise ViewerError("scene_invalid", "saved viewer artifact is corrupt", 409)
    except KeyError as exc:
        raise ViewerError("not_found", "saved viewer artifact not found", 404) from exc
    except ValueError as exc:
        raise ViewerError("scene_invalid", "saved viewer artifact is corrupt", 409) from exc
    return {"handle": handle, "value": value}


def scene_detail(run: Any, handle: str) -> dict[str, Any]:
    detail = _detail(run, handle, "viewer_scene", SCENE_SCHEMAS)
    scene = detail["value"]
    try:
        parsed = (SceneArtifactV2 if scene["schema"] == SCENE_SCHEMA_V2 else SceneArtifact).model_validate(scene)
        if parsed.renderer.model_dump() != RENDERER:
            raise ValueError("unsupported renderer")
        meta, residues = _source(run, parsed.structure_handle)
        if (meta["kind"] != scene["structure_kind"] or meta["schema"] != scene["structure_schema"] or
                residues["model_number"] != scene["model_number"]):
            raise ViewerError("scene_invalid", "saved source identity changed", 409)
        _selection(residues, parsed.selection)
        if isinstance(parsed, SceneArtifactV2):
            _annotation(run, parsed.annotation.handle, parsed.structure_handle)
    except (ValueError, KeyError, ViewerError) as exc:
        raise ViewerError("scene_invalid", "saved scene validation failed", 409) from exc
    return detail


def save_scene(run: Any, body: SceneSave) -> dict[str, Any]:
    meta, residues = _source(run, body.structure_handle)
    selection = _selection(residues, body.selection)
    schema = SCENE_SCHEMA
    if isinstance(body, SceneSaveV2):
        _annotation(run, body.annotation.handle, body.structure_handle)
        schema = SCENE_SCHEMA_V2
    content = {"schema": schema, "name": body.name, "structure_handle": body.structure_handle,
               "structure_kind": meta["kind"], "structure_schema": meta["schema"],
               "model_number": residues["model_number"], "selection": selection,
               "representation": body.representation, "camera": body.camera.model_dump(),
               "theme": body.theme, "renderer": RENDERER}
    if isinstance(body, SceneSaveV2):
        content["annotation"] = body.annotation.model_dump()
    payload_hash = _request_hash(body)
    candidate_handle = f"obj://{run.run_id}/viewer_scene/{object_sha('viewer_scene', schema, canonical_json(content))}"
    with run._transition():
        duplicate = _admit(run, "viewer_scene_saved", body, payload_hash, MAX_SCENES, candidate_handle)
        if duplicate is not None and duplicate["type"] == "viewer_scene_saved":
            return scene_detail(run, duplicate["handle"])
        if duplicate is None:
            _binding(run, body, body.structure_handle, body.representation, selection)
            run.events.append("viewer_scene_admitted", handle=candidate_handle, request_id=body.request_id,
                              payload_sha256=payload_hash, viewer_session_id=body.viewer_session_id)
        saved = run.store.put("viewer_scene", schema, content,
                              summary={"name": body.name, "structure_handle": body.structure_handle,
                                       "model_number": residues["model_number"]})
        run.events.append("viewer_scene_saved", handle=saved.handle, request_id=body.request_id,
                          payload_sha256=payload_hash, viewer_session_id=body.viewer_session_id)
    return {"handle": saved.handle, "value": content}


def list_scenes(run: Any, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    handles = _completed_handles(run, "viewer_scene_saved", "viewer_scene", SCENE_SCHEMAS)
    return {"total": len(handles), "offset": offset, "limit": limit,
            "rows": [scene_detail(run, handle) for handle in handles[offset:offset + limit]]}


def validate_png(raw: bytes) -> tuple[int, int]:
    if not PNG_SIGNATURE == raw[:8] or len(raw) > MAX_PNG:
        raise ViewerError("image_invalid", "PNG signature or size invalid")
    offset = 8
    width = height = None
    idat = bytearray()
    chunks = 0
    ended = False
    idat_started = False
    idat_closed = False
    while offset + 12 <= len(raw) and chunks < 10_000:
        length = struct.unpack_from(">I", raw, offset)[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        if length > MAX_PNG or end > len(raw):
            raise ViewerError("image_invalid", "truncated PNG chunk")
        data = raw[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", raw, offset + 8 + length)[0]
        if binascii.crc32(kind + data) & 0xffffffff != crc:
            raise ViewerError("image_invalid", "PNG chunk CRC invalid")
        if (not all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind) or
                not 65 <= kind[2] <= 90):
            raise ViewerError("image_invalid", "PNG chunk name invalid")
        if chunks == 0:
            if kind != b"IHDR" or length != 13:
                raise ViewerError("image_invalid", "PNG IHDR invalid")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            if (not 64 <= width <= 2048 or not 64 <= height <= 2048 or width * height > 4_000_000 or
                    depth != 8 or color not in (2, 6) or compression or filtering or interlace):
                raise ViewerError("image_invalid", "PNG dimensions or encoding unsupported")
        elif kind == b"IDAT":
            if idat_closed:
                raise ViewerError("image_invalid", "PNG IDAT chunks are not contiguous")
            idat_started = True
            idat.extend(data)
        elif kind == b"IEND":
            if length or end != len(raw) or not idat_started:
                raise ViewerError("image_invalid", "PNG has trailing data")
            ended = True
            break
        else:
            if idat_started:
                idat_closed = True
            if kind[0] & 0x20 == 0:
                raise ViewerError("image_invalid", "unsupported critical PNG chunk")
        offset = end
        chunks += 1
    if not ended or not idat or width is None or height is None:
        raise ViewerError("image_invalid", "incomplete PNG")
    channels = 4 if color == 6 else 3
    expected = height * (1 + width * channels)
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(bytes(idat), expected + 1)
    except zlib.error as exc:
        raise ViewerError("image_invalid", "PNG pixel stream invalid") from exc
    if (len(pixels) != expected or not decompressor.eof or decompressor.unused_data or
            decompressor.unconsumed_tail):
        raise ViewerError("image_invalid", "PNG pixel stream length invalid")
    stride = 1 + width * channels
    if any(pixels[row * stride] > 4 for row in range(height)):
        raise ViewerError("image_invalid", "PNG row filter invalid")
    return width, height


def _camera_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    if actual["mode"] != expected["mode"] or actual["clipFar"] != expected["clipFar"]:
        return False
    for key in ("fov", "radius", "radiusMax", "fog", "minNear", "minFar"):
        value, original = actual[key], expected[key]
        tolerance = 1e-6 if key in ("fov", "fog") else max(1e-4, abs(original) * 1e-6)
        if abs(value - original) > tolerance:
            return False
    for key in ("position", "up", "target"):
        for value, original in zip(actual[key], expected[key]):
            tolerance = 1e-6 if key == "up" else max(1e-4, abs(original) * 1e-6)
            if abs(value - original) > tolerance:
                return False
    return True


def _png_budget_allows(run: Any, png_handle: str, byte_count: int) -> None:
    """Count persisted PNGs plus fsynced reservations before a new admission.

    This prevents an interrupted figure write from oversubscribing the shared
    byte limit, while a rejected image leaves no UUID or figure-slot record.
    """
    sizes: dict[str, int] = {}
    for event in run.events.read():
        if event["type"] == "object_created" and event["kind"] == "viewer_png":
            try:
                size = len(base64.b64decode(event["payload_b64"], validate=True))
            except (binascii.Error, ValueError) as exc:
                raise ViewerError("scene_invalid", "stored PNG ledger is corrupt", 409) from exc
            sizes[event["handle"]] = size
        elif event["type"] == "viewer_figure_admitted":
            prior = sizes.setdefault(event["png_handle"], event["png_bytes"])
            if prior != event["png_bytes"]:
                raise ViewerError("scene_invalid", "PNG reservation size differs", 409)
    if png_handle not in sizes and sum(sizes.values()) + byte_count > MAX_RUN_PNG_BYTES:
        raise ViewerError("resource_exceeded", "saved PNG byte budget exhausted", 429)


def figure_detail(run: Any, handle: str) -> dict[str, Any]:
    detail = _detail(run, handle, "viewer_figure", FIGURE_SCHEMAS)
    value = detail["value"]
    try:
        v2 = value["schema"] == FIGURE_SCHEMA_V2
        parsed = (FigureArtifactV2 if v2 else FigureArtifact).model_validate(value)
        scene = scene_detail(run, parsed.scene_handle)["value"]
        if scene["schema"] != (SCENE_SCHEMA_V2 if v2 else SCENE_SCHEMA):
            raise ValueError("figure schema does not match its scene")
        if isinstance(parsed, FigureArtifactV2) and (
                parsed.annotation.model_dump() != _figure_annotation(run, scene) or
                (parsed.capture_method == CAPTURE_METHOD_LEGEND and not parsed.annotation.legend)):
            raise ValueError("figure annotation provenance mismatch")
        png_meta = run.store.meta(parsed.png_handle)
        if (png_meta["kind"], png_meta["schema"], png_meta["fmt"]) != ("viewer_png", PNG_SCHEMA, "png"):
            raise ValueError("wrong PNG object")
        raw = run.store.load(parsed.png_handle)
        width, height = validate_png(raw)
        if (parsed.renderer.model_dump() != RENDERER or
                parsed.structure_handle != scene["structure_handle"] or
                parsed.model_number != scene["model_number"] or
                parsed.png_sha256 != hashlib.sha256(raw).hexdigest() or
                (parsed.width, parsed.height) != (width, height)):
            raise ValueError("figure source or image mismatch")
    except (KeyError, ValueError, ViewerError) as exc:
        raise ViewerError("scene_invalid", "stored figure provenance is invalid", 409) from exc
    return detail


def save_figure(run: Any, body: FigureSave) -> dict[str, Any]:
    if len(body.png_base64) > (MAX_PNG * 4 // 3 + 8):
        raise ViewerError("image_invalid", "encoded PNG exceeds limit")
    try:
        raw = base64.b64decode(body.png_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ViewerError("image_invalid", "PNG base64 invalid") from exc
    width, height = validate_png(raw)
    scene = scene_detail(run, body.scene_handle)["value"]
    v2 = isinstance(body, FigureSaveV2)
    if scene["schema"] != (SCENE_SCHEMA_V2 if v2 else SCENE_SCHEMA):
        raise ViewerError("scene_mismatch", "figure schema does not match the saved scene schema", 409)
    if v2 and body.legend_composited and not scene["annotation"]["legend"]:
        raise ViewerError("input_invalid", "legend composited although the saved scene has the legend off")
    if (scene["structure_handle"] != body.structure_handle or scene["selection"] !=
            (body.selection.model_dump() if body.selection else None) or scene["representation"] != body.representation or
            not _camera_matches(body.camera.model_dump(), scene["camera"]) or scene["theme"] != body.theme):
        raise ViewerError("scene_mismatch", "current rendered view differs from saved scene", 409)
    payload_hash = _request_hash(body)
    png_handle = f"obj://{run.run_id}/viewer_png/{object_sha('viewer_png', PNG_SCHEMA, raw)}"
    schema = FIGURE_SCHEMA_V2 if v2 else FIGURE_SCHEMA
    value = {"schema": schema, "scene_handle": body.scene_handle,
             "structure_handle": scene["structure_handle"], "model_number": scene["model_number"],
             "png_handle": png_handle, "png_sha256": hashlib.sha256(raw).hexdigest(),
             "width": width, "height": height, "media_type": "image/png", "renderer": RENDERER,
             "capture_method": CAPTURE_METHOD, "provenance": "client_rendered_local_view",
             "limitations": LIMITATIONS}
    if v2:
        value["capture_method"] = CAPTURE_METHOD_LEGEND if body.legend_composited else CAPTURE_METHOD
        value["annotation"] = _figure_annotation(run, scene)
    figure_handle = f"obj://{run.run_id}/viewer_figure/{object_sha('viewer_figure', schema, canonical_json(value))}"
    with run._transition():
        duplicate = _admit(run, "viewer_figure_saved", body, payload_hash, MAX_FIGURES, figure_handle)
        if duplicate is not None and duplicate["type"] == "viewer_figure_saved":
            return figure_detail(run, duplicate["handle"])
        if duplicate is None:
            _binding(run, body, body.structure_handle, body.representation,
                     body.selection.model_dump() if body.selection else None)
            _png_budget_allows(run, png_handle, len(raw))
            run.events.append("viewer_figure_admitted", handle=figure_handle, request_id=body.request_id,
                              payload_sha256=payload_hash, viewer_session_id=body.viewer_session_id,
                              png_handle=png_handle, png_bytes=len(raw))
        try:
            existing_png = run.store.meta(png_handle)
            if existing_png["kind"] != "viewer_png" or existing_png["schema"] != PNG_SCHEMA:
                raise ViewerError("scene_invalid", "existing image object is invalid", 409)
        except KeyError:
            # A new UUID reserved these bytes above. A retry of a prior
            # admission owns its earlier reservation and may finish safely.
            pass
        png = run.store.put("viewer_png", PNG_SCHEMA, raw, fmt="png",
                            summary={"width": width, "height": height})
        if png.handle != png_handle:
            raise ViewerError("scene_invalid", "saved image identity mismatch", 409)
        figure = run.store.put("viewer_figure", schema, value,
                               summary={"scene_handle": body.scene_handle, "width": width, "height": height})
        run.events.append("viewer_figure_saved", handle=figure.handle, request_id=body.request_id,
                          payload_sha256=payload_hash, viewer_session_id=body.viewer_session_id)
    return {"handle": figure.handle, "value": value}


def list_figures(run: Any, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    handles = _completed_handles(run, "viewer_figure_saved", "viewer_figure", FIGURE_SCHEMAS)
    return {"total": len(handles), "offset": offset, "limit": limit,
            "rows": [figure_detail(run, handle) for handle in handles[offset:offset + limit]]}


def figure_download(run: Any, handle: str, fmt: str) -> bytes:
    figure = figure_detail(run, handle)["value"]
    if fmt == "png":
        return run.store.load(figure["png_handle"])
    if fmt == "json":
        return canonical_json(figure)
    raise ViewerError("input_invalid", "unsupported figure download format")
