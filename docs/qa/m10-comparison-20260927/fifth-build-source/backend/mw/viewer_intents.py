"""Local scene identity, exact target catalog, bounded viewer plans and durable acks.

This module never runs scientific tools or accepts model-selected operation names.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from .core.handles import canonical_json
from .core.residue import ResidueRef
from .openmm_reports import validated_minimized_structure
from .tools.structural import structure_residues

CATALOG_LIMIT = 256
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,16}\Z")
ALIAS = re.compile(r"t[0-9]{4}\Z")
REPRESENTATIONS = ("keep", "cartoon", "ball_and_stick", "surface")
SELECTIONS = ("keep", "clear")
CAMERAS = ("keep", "focus_selected", "zoom_in", "zoom_out", "reset")
DISPOSITIONS = ("apply", "clarify", "unsupported")
PLAN_VERSION = "viewer_plan@1"
QUESTION_VERSION = "viewer_questions@2"
MAX_BODY_BYTES = 65_536
ACTIVE_INTENTS: set[str] = set()


class ViewerError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    alias: str
    category: Literal["polymer", "nonpolymer", "water"]
    model_number: StrictInt | None = None
    chain_auth: str | None = None
    seq_auth: StrictInt | None = None
    icode: str | None = None
    chain_label: str | None = None
    seq_label: StrictInt | None = None

    @field_validator("alias")
    @classmethod
    def alias_valid(cls, value: str) -> str:
        if not ALIAS.fullmatch(value):
            raise ValueError("invalid alias")
        return value

    @field_validator("chain_auth", "icode", "chain_label")
    @classmethod
    def identifier_valid(cls, value: str | None) -> str | None:
        if value is not None and not IDENTIFIER.fullmatch(value):
            raise ValueError("unsafe identifier")
        return value

    @field_validator("model_number", "seq_auth", "seq_label")
    @classmethod
    def number_valid(cls, value: int | None) -> int | None:
        if value is not None and not -999_999 <= value <= 999_999:
            raise ValueError("identifier number out of bounds")
        return value


class EgressViewerIntentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    schema_: Literal["viewer_intent@1"] = Field(alias="schema")
    prompt: str
    representation: Literal["cartoon", "ball_and_stick", "surface"]
    selected_target: str | None
    scope_complete: StrictBool
    catalog: list[CatalogEntry]

    @field_validator("prompt")
    @classmethod
    def prompt_valid(cls, value: str) -> str:
        if not 1 <= len(value) <= 512 or len(value.encode("utf-8")) > 2048:
            raise ValueError("invalid prompt length")
        if any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) < 160 for char in value):
            raise ValueError("control character in prompt")
        return value

    @field_validator("catalog")
    @classmethod
    def catalog_valid(cls, value: list[CatalogEntry]) -> list[CatalogEntry]:
        if len(value) > CATALOG_LIMIT or len({item.alias for item in value}) != len(value):
            raise ValueError("invalid catalog")
        return value

    @model_validator(mode="after")
    def target_valid(self) -> EgressViewerIntentV1:
        if self.selected_target is not None and self.selected_target not in {item.alias for item in self.catalog}:
            raise ValueError("selected target is not in catalog")
        return self

    def wire(self) -> dict[str, Any]:
        return {"schema": self.schema_, "prompt": self.prompt,
                "representation": self.representation, "selected_target": self.selected_target,
                "scope_complete": self.scope_complete,
                "catalog": [entry.model_dump(exclude_none=True) for entry in self.catalog]}


def _uuid(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError) as exc:
        raise ViewerError("input_invalid", "invalid UUID") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ViewerError("input_invalid", "UUID must be canonical version 4")
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _safe_identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and IDENTIFIER.fullmatch(value) else None


def _catalog_projection(alias: str, item: dict[str, Any]) -> dict[str, Any]:
    # Any unsafe source identifier makes this an alias-only target. It can be
    # named by the model only after the user selects it locally.
    if any(item.get(key) is not None and not (key == "icode" and item.get(key) == "")
           and _safe_identifier(item.get(key)) is None
           for key in ("chain_auth", "icode", "chain_label")):
        return {"alias": alias, "category": item["category"]}
    entry: dict[str, Any] = {"alias": alias, "category": item["category"],
                             "model_number": item["model_number"]}
    for key in ("chain_auth", "icode", "chain_label"):
        safe = _safe_identifier(item.get(key))
        if safe:
            entry[key] = safe
    for key in ("seq_auth", "seq_label"):
        value = item.get(key)
        if type(value) is int and -999_999 <= value <= 999_999:
            entry[key] = value
    return CatalogEntry.model_validate(entry).model_dump(exclude_none=True)


def _events(run: Any) -> list[dict[str, Any]]:
    return list(run.events.read())


def _session_events(run: Any, session_id: str) -> list[dict[str, Any]]:
    return [event for event in _events(run) if event.get("viewer_session_id") == session_id]


def _session(run: Any, session_id: str) -> dict[str, Any]:
    created = next((event for event in _events(run) if event["type"] == "viewer_session_created"
                    and event["viewer_session_id"] == session_id), None)
    if created is None:
        raise ViewerError("not_found", "unknown viewer session", 404)
    latest = dict(created)
    for event in _session_events(run, session_id):
        if event["type"] == "viewer_scene_updated":
            latest["representation"] = event["representation"]
            latest["selected_alias"] = event["selected_alias"]
            latest["action_revision"] = event["action_revision"]
    return latest


def _current_session(run: Any, session: dict[str, Any]) -> bool:
    sessions = [event for event in _events(run) if event["type"] == "viewer_session_created"
                and event["client_instance_id"] == session["client_instance_id"]]
    return bool(sessions) and sessions[-1]["viewer_session_id"] == session["viewer_session_id"]


def _ref_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return ResidueRef.model_validate({key: item[key] for key in ResidueRef.model_fields}).key


def create_session(run: Any, *, client_instance_id: str, scene_generation: int,
                   structure_handle: str, representation: str = "cartoon",
                   scope_chain_auth: str | None = None,
                   scope_target: dict[str, Any] | None = None,
                   selected_target: dict[str, Any] | None = None) -> dict[str, Any]:
    _uuid(client_instance_id)
    if type(scene_generation) is not int or not 1 <= scene_generation <= 1_000_000:
        raise ViewerError("input_invalid", "invalid scene generation")
    if representation not in {"cartoon", "ball_and_stick", "surface"}:
        raise ViewerError("input_invalid", "invalid representation")
    try:
        meta = run.store.meta(structure_handle)
    except KeyError as exc:
        raise ViewerError("input_invalid", "unknown same-run structure handle") from exc
    if (meta["kind"], meta["schema"]) not in {
        ("structure", "structure_selection@2"),
        ("prepared_structure", "prepared_structure@1"),
        ("openmm_minimized_structure", "openmm_minimized_structure@1"),
    }:
        raise ViewerError("input_invalid", "unsupported scene structure kind")
    if meta["kind"] == "openmm_minimized_structure":
        validated_minimized_structure(run, structure_handle)
    data = structure_residues(run.store, structure_handle)
    rows = data["residues"]
    if scope_chain_auth is not None:
        if not isinstance(scope_chain_auth, str) or not scope_chain_auth:
            raise ViewerError("input_invalid", "invalid chain scope")
        scoped = [row for row in rows if row["chain_auth"] == scope_chain_auth]
        if not scoped:
            raise ViewerError("input_invalid", "chain scope has no targets")
        rows = scoped
    if scope_target is not None:
        try:
            target_key = _ref_key(scope_target)
        except (KeyError, ValueError) as exc:
            raise ViewerError("input_invalid", "invalid exact target scope") from exc
        rows = [row for row in rows if _ref_key(row) == target_key]
        if len(rows) != 1:
            raise ViewerError("input_invalid", "exact target scope is not unique")
    # Keep the viewer usable for targetless actions on large structures. Never
    # export an arbitrary first slice and pretend it is a complete catalog.
    oversized_scope = len(rows) > CATALOG_LIMIT
    if oversized_scope:
        rows = []
    mapping: dict[str, dict[str, Any]] = {}
    catalog = []
    for i, row in enumerate(rows, 1):
        alias = f"t{i:04d}"
        mapping[alias] = {key: row[key] for key in ResidueRef.model_fields}
        catalog.append(_catalog_projection(alias, row))
    if selected_target is not None:
        try:
            selected_key = _ref_key(selected_target)
        except (KeyError, ValueError) as exc:
            raise ViewerError("input_invalid", "invalid selected target") from exc
        matches = [alias for alias, ref in mapping.items() if _ref_key(ref) == selected_key]
        if len(matches) != 1:
            raise ViewerError("input_invalid", "selected target is outside the catalog")
        selected_alias = matches[0]
    else:
        selected_alias = None
    catalog_hash = _sha({"catalog": catalog, "mapping": mapping, "structure": structure_handle})
    session_id = str(uuid.uuid4())
    with run._transition():
        previous = [event for event in _events(run) if event["type"] == "viewer_session_created"
                    and event["client_instance_id"] == client_instance_id]
        if previous and scene_generation <= previous[-1]["scene_generation"]:
            raise ViewerError("stale_scene", "scene generation must increase", 409)
        run.events.append("viewer_session_created", viewer_session_id=session_id,
                          client_instance_id=client_instance_id, scene_generation=scene_generation,
                          structure_handle=structure_handle, catalog_hash=catalog_hash,
                          catalog=catalog, mapping=mapping,
                          scope_complete=not oversized_scope and scope_chain_auth is None and scope_target is None,
                          representation=representation, selected_alias=selected_alias,
                          action_revision=0)
    return session_public(run, session_id)


def session_public(run: Any, session_id: str) -> dict[str, Any]:
    session = _session(run, session_id)
    return {key: session[key] for key in ("viewer_session_id", "client_instance_id", "scene_generation",
                                          "structure_handle", "catalog_hash", "catalog", "scope_complete",
                                          "representation", "selected_alias", "action_revision")} | {
        "targets": [{"alias": alias, "residue": ref} for alias, ref in session["mapping"].items()],
        "current": _current_session(run, session),
    }


def update_scene(run: Any, session_id: str, *, representation: str,
                 selected_alias: str | None, action_revision: int) -> dict[str, Any]:
    with run._transition():
        session = _session(run, session_id)
        if not _current_session(run, session):
            raise ViewerError("stale_scene", "viewer session is detached", 409)
        if representation not in {"cartoon", "ball_and_stick", "surface"}:
            raise ViewerError("input_invalid", "invalid representation")
        if selected_alias is not None and selected_alias not in session["mapping"]:
            raise ViewerError("input_invalid", "selected target not in scene")
        if type(action_revision) is not int or action_revision <= session["action_revision"]:
            raise ViewerError("stale_revision", "viewer action revision must increase", 409)
        run.events.append("viewer_scene_updated", viewer_session_id=session_id,
                          representation=representation, selected_alias=selected_alias,
                          action_revision=action_revision)
    return session_public(run, session_id)


def effective_online(run: Any) -> bool:
    changed = [event for event in _events(run) if event["type"] == "viewer_consent_changed"]
    return bool(changed and changed[-1]["enabled"] and not run.dry_run)


def consent_epoch(run: Any) -> int:
    return sum(event["type"] == "viewer_consent_changed" for event in _events(run))


def viewer_used(run: Any) -> int:
    return sum(event["type"] == "viewer_dispatch_started" for event in _events(run))


def set_online(run: Any, enabled: bool) -> dict[str, Any]:
    if type(enabled) is not bool:
        raise ViewerError("input_invalid", "enabled must be boolean")
    if enabled and run.dry_run:
        raise ViewerError("dry_run", "dry-run cannot enable model interpretation", 412)
    with run._transition():
        # An online consent does not resolve the independent expensive scientific gate.
        run.events.append("viewer_consent_changed", enabled=enabled, policy="viewer_model@1",
                          request_cap=4, request_model="typesafe/jev-1.13",
                          allowed_served_model="typesafe/jev-1.13-20260917")
        run.egress_config = {**run.egress_config, "mode": "online" if enabled else "local_only"}
    return {"enabled": enabled, "mode": run.egress_config["mode"], "policy": "viewer_model@1",
            "request_cap": 4, "used": viewer_used(run), "remaining": max(0, 4 - viewer_used(run)),
            "scientific_job_approved": run.approved_expensive}


def online_status(run: Any) -> dict[str, Any]:
    enabled = effective_online(run)
    return {"enabled": enabled, "mode": "online" if enabled else "local_only",
            "policy": "viewer_model@1", "request_cap": 4, "used": viewer_used(run),
            "remaining": max(0, 4 - viewer_used(run)), "scientific_job_approved": run.approved_expensive}


def _intent_events(run: Any, intent_id: str) -> list[dict[str, Any]]:
    return [event for event in _events(run) if event.get("intent_id") == intent_id]


def intent_public(run: Any, intent_id: str) -> dict[str, Any]:
    records = _intent_events(run, intent_id)
    requested = next((event for event in records if event["type"] == "viewer_intent_requested"), None)
    if requested is None:
        raise ViewerError("not_found", "unknown viewer intent", 404)
    outcome = next((event for event in reversed(records) if event["type"] == "viewer_intent_outcome"), None)
    cancelled = any(event["type"] == "viewer_intent_cancelled" for event in records)
    commands = outcome.get("commands", []) if outcome else []
    acks = [event for event in records if event["type"] == "viewer_command_ack"]
    status = outcome["status"] if outcome else "interpreting" if intent_id in ACTIVE_INTENTS else "detached"
    if cancelled:
        status = "cancelled"
    elif outcome and outcome["status"] == "planned":
        if len(acks) == len(commands) and commands:
            status = ("applied" if all(ack["status"] == "applied" for ack in acks) else
                      "no_change" if all(ack["status"] == "no_change" for ack in acks) else "partial")
        elif acks:
            status = "applying"
        elif (not _current_session(run, _session(run, requested["viewer_session_id"])) or
              _session(run, requested["viewer_session_id"])["action_revision"] != requested["action_revision"] or
              (requested["source"] == "jev" and not intent_live(run, intent_id))):
            status = "detached"
    return {"intent_id": intent_id, "status": status,
            "source": requested["source"], "viewer_session_id": requested["viewer_session_id"],
            "scene_generation": requested["scene_generation"], "structure_handle": requested["structure_handle"],
            "catalog_hash": requested["catalog_hash"], "prompt_sha256": requested["prompt_sha256"],
            "projection_sha256": outcome.get("projection_sha256") if outcome else None,
            "question_version": outcome.get("question_version") if outcome else None,
            "requested_model": outcome.get("requested_model") if outcome else None,
            "served_model": outcome.get("served_model") if outcome else None,
            "audit_id": outcome.get("audit_id") if outcome else None,
            "reason_code": outcome.get("reason_code") if outcome else None,
            "commands": commands, "acks": [{"command_id": ack["command_id"], "status": ack["status"],
                                            "reason_code": ack.get("reason_code")} for ack in acks]}


def list_intents(run: Any) -> list[dict[str, Any]]:
    return [intent_public(run, event["intent_id"]) for event in _events(run)
            if event["type"] == "viewer_intent_requested"]


def _choice(data: dict[str, Any], key: str, allowed: set[str]) -> str:
    answer = data.get(key)
    if (not isinstance(answer, dict) or set(answer) - {"type", "choice", "confidence", "probabilities"}
            or answer.get("type") != "choice" or not isinstance(answer.get("choice"), str)
            or answer["choice"] not in allowed):
        raise ViewerError("response_invalid", "invalid model answer")
    confidence = answer.get("confidence")
    if "confidence" in answer and (type(confidence) not in (int, float) or not 0 <= confidence <= 1):
        raise ViewerError("response_invalid", "invalid answer confidence")
    probabilities = answer.get("probabilities")
    if "probabilities" in answer and (not isinstance(probabilities, dict) or len(probabilities) > len(allowed)
            or any(name not in allowed or type(value) not in (int, float) or not 0 <= value <= 1
                   for name, value in probabilities.items())):
        raise ViewerError("response_invalid", "invalid answer probabilities")
    return answer["choice"]


def compile_answers(answers: dict[str, Any], session: dict[str, Any], *, intent_id: str) -> tuple[str, list[dict[str, Any]], str]:
    if not isinstance(answers, dict) or set(answers) != {"disposition", "representation", "selection", "camera"}:
        raise ViewerError("response_invalid", "unexpected model answer IDs")
    disposition = _choice(answers, "disposition", set(DISPOSITIONS))
    representation = _choice(answers, "representation", set(REPRESENTATIONS))
    selectable = {item["alias"] for item in session["catalog"]
                  if "model_number" in item or item["alias"] == session["selected_alias"]}
    selection = _choice(answers, "selection", set(SELECTIONS) | selectable)
    camera = _choice(answers, "camera", set(CAMERAS))
    if disposition != "apply":
        return "clarification" if disposition == "clarify" else "unsupported", [], disposition
    if selection == "clear" and camera == "focus_selected":
        raise ViewerError("response_invalid", "cannot focus a cleared selection")
    if camera == "focus_selected" and selection in {"keep"} and session["selected_alias"] is None:
        raise ViewerError("response_invalid", "no selected target to focus")
    commands = []
    binding = {"schema": PLAN_VERSION, "intent_id": intent_id,
               "viewer_session_id": session["viewer_session_id"],
               "client_instance_id": session["client_instance_id"],
               "scene_generation": session["scene_generation"],
               "structure_handle": session["structure_handle"],
               "catalog_hash": session["catalog_hash"],
               "action_revision": session["action_revision"]}
    def add(axis: str, value: str, target: dict[str, Any] | None = None) -> None:
        commands.append({**binding, "command_id": str(uuid.uuid4()), "axis": axis,
                         "value": value, **({"target": target} if target is not None else {})})
    if representation != "keep" and representation != session["representation"]:
        add("representation", representation)
    if selection == "clear" and session["selected_alias"] is not None:
        add("selection", "clear")
    elif selection not in {"keep", "clear"}:
        add("selection", "select", session["mapping"][selection])
    if camera != "keep":
        target_alias = selection if selection not in {"keep", "clear"} else session["selected_alias"]
        add("camera", camera, session["mapping"].get(target_alias) if camera == "focus_selected" else None)
    return ("planned" if commands else "no_change"), commands, "accepted" if commands else "no_change"


def local_answers(prompt: str, session: dict[str, Any]) -> dict[str, Any]:
    parts = prompt.strip().split()
    if not parts or not parts[0].startswith("/"):
        raise ViewerError("local_command_required", "offline mode accepts explicit /commands", 412)
    values = {"disposition": "apply", "representation": "keep", "selection": "keep", "camera": "keep"}
    if parts[:1] == ["/representation"] and len(parts) == 2:
        values["representation"] = {"ball-and-stick": "ball_and_stick"}.get(parts[1], parts[1])
        if values["representation"] not in REPRESENTATIONS[1:]:
            raise ViewerError("unsupported", "unknown representation")
    elif parts[:1] == ["/focus"] and len(parts) == 2 and parts[1] in session["mapping"]:
        values["selection"] = parts[1]
        values["camera"] = "focus_selected"
    elif parts == ["/clear"]:
        values["selection"] = "clear"
    elif parts == ["/zoom", "in"]:
        values["camera"] = "zoom_in"
    elif parts == ["/zoom", "out"]:
        values["camera"] = "zoom_out"
    elif parts == ["/reset"]:
        values["camera"] = "reset"
    else:
        raise ViewerError("unsupported", "unknown local viewer command")
    return {key: {"type": "choice", "choice": value} for key, value in values.items()}


def request_intent(run: Any, *, client_instance_id: str, viewer_session_id: str,
                   scene_generation: int, request_id: str, prompt: str) -> tuple[str, dict[str, Any], bool]:
    # Admission and durable idempotency must be one short atomic transition.
    with run._transition():
        return _request_intent_locked(run, client_instance_id=client_instance_id,
                                      viewer_session_id=viewer_session_id,
                                      scene_generation=scene_generation,
                                      request_id=request_id, prompt=prompt)


def _request_intent_locked(run: Any, *, client_instance_id: str, viewer_session_id: str,
                           scene_generation: int, request_id: str, prompt: str) -> tuple[str, dict[str, Any], bool]:
    _uuid(client_instance_id)
    _uuid(request_id)
    session = _session(run, viewer_session_id)
    payload = {"client_instance_id": client_instance_id, "viewer_session_id": viewer_session_id,
               "scene_generation": scene_generation, "request_id": request_id, "prompt": prompt}
    payload_hash = _sha(payload)
    existing = [event for event in _events(run) if event["type"] == "viewer_intent_requested"
                and event["request_id"] == request_id]
    if existing:
        if existing[0]["payload_sha256"] != payload_hash:
            raise ViewerError("idempotency_conflict", "request UUID reused with different payload", 409)
        return existing[0]["intent_id"], session, True
    if run.cancelled or run._cancel_path.exists():
        raise ViewerError("run_cancelled", "run is cancelled", 409)
    if (session["client_instance_id"] != client_instance_id or
            session["scene_generation"] != scene_generation or not _current_session(run, session)):
        raise ViewerError("stale_scene", "intent scene does not match current viewer", 409)
    try:
        EgressViewerIntentV1.model_validate({"schema": "viewer_intent@1", "prompt": prompt,
                                             "representation": session["representation"],
                                             "selected_target": session["selected_alias"],
                                             "scope_complete": session["scope_complete"],
                                             "catalog": session["catalog"]})
    except ValueError as exc:
        raise ViewerError("input_invalid", "invalid viewer prompt or state") from exc
    source = "local_command" if prompt.strip().startswith("/") else "jev"
    # The browser knows this ID before the long provider call, so Stop works
    # while the POST is still pending.
    intent_id = request_id
    run.events.append("viewer_intent_requested", intent_id=intent_id, request_id=request_id,
                      payload_sha256=payload_hash, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                      source=source, viewer_session_id=viewer_session_id,
                      client_instance_id=client_instance_id, scene_generation=scene_generation,
                      structure_handle=session["structure_handle"], catalog_hash=session["catalog_hash"],
                      action_revision=session["action_revision"], consent_epoch=consent_epoch(run))
    # A scoped Stop may have arrived before this POST was admitted.
    return intent_id, session, any(event["type"] == "viewer_intent_cancelled"
                                    for event in _intent_events(run, intent_id))


def finish_intent(run: Any, intent_id: str, *, status: str, reason_code: str,
                  commands: list[dict[str, Any]] | None = None, **metadata: Any) -> dict[str, Any]:
    if any(event["type"] == "viewer_intent_cancelled" for event in _intent_events(run, intent_id)):
        status, commands = "cancelled", []
        reason_code = "cancelled"
    run.events.append("viewer_intent_outcome", intent_id=intent_id, status=status,
                      reason_code=reason_code, commands=commands or [], **metadata)
    return intent_public(run, intent_id)


def cancel_intent(run: Any, intent_id: str, *, client_instance_id: str | None = None,
                  viewer_session_id: str | None = None, scene_generation: int | None = None) -> dict[str, Any]:
    with run._transition():
        records = _intent_events(run, intent_id)
        if not records:
            _uuid(intent_id)
            if not client_instance_id or not viewer_session_id or scene_generation is None:
                raise ViewerError("not_found", "unknown viewer intent", 404)
            _uuid(client_instance_id)
            session = _session(run, viewer_session_id)
            if (session["client_instance_id"] != client_instance_id or
                    session["scene_generation"] != scene_generation or not _current_session(run, session)):
                raise ViewerError("stale_scene", "stop scope does not match current viewer", 409)
            run.events.append("viewer_intent_cancelled", intent_id=intent_id,
                              client_instance_id=client_instance_id,
                              viewer_session_id=viewer_session_id,
                              scene_generation=scene_generation, pre_admission=True)
            return {"intent_id": intent_id, "status": "cancelled"}
        requested = next((event for event in records if event["type"] == "viewer_intent_requested"), None)
        if requested is None:
            return {"intent_id": intent_id, "status": "cancelled"}
        if (client_instance_id is not None and client_instance_id != requested["client_instance_id"] or
                viewer_session_id is not None and viewer_session_id != requested["viewer_session_id"] or
                scene_generation is not None and scene_generation != requested["scene_generation"]):
            raise ViewerError("stale_scene", "stop scope does not match intent", 409)
        current = intent_public(run, intent_id)
        if current["status"] in {"applied", "no_change", "clarification", "unsupported", "rejected", "failed"}:
            raise ViewerError("intent_terminal", "completed viewer intent cannot be cancelled", 409)
        if not any(event["type"] == "viewer_intent_cancelled" for event in records):
            run.events.append("viewer_intent_cancelled", intent_id=intent_id)
    return intent_public(run, intent_id)


def intent_live(run: Any, intent_id: str) -> bool:
    records = _intent_events(run, intent_id)
    if any(event["type"] == "viewer_intent_cancelled" for event in records):
        return False
    requested = next((event for event in records if event["type"] == "viewer_intent_requested"), None)
    return bool(requested and effective_online(run) and not run.cancelled and
                not run._cancel_path.exists() and
                requested.get("consent_epoch") == consent_epoch(run) and
                _current_session(run, _session(run, requested["viewer_session_id"])) and
                _session(run, requested["viewer_session_id"])["action_revision"] == requested["action_revision"])


def acknowledge(run: Any, intent_id: str, *, command_id: str, status: str,
                reason_code: str | None, client_instance_id: str,
                viewer_session_id: str, scene_generation: int,
                action_revision: int) -> dict[str, Any]:
    with run._transition():
        public = intent_public(run, intent_id)
        if public["status"] in {"cancelled", "detached", "clarification", "unsupported", "no_change", "failed", "rejected"}:
            raise ViewerError("stale_intent", "intent is not awaiting application", 409)
        session = _session(run, viewer_session_id)
        requested = next(event for event in _intent_events(run, intent_id)
                         if event["type"] == "viewer_intent_requested")
        latest_for_scene = [event for event in _events(run) if event["type"] == "viewer_intent_requested"
                            and event["viewer_session_id"] == viewer_session_id]
        if (public["viewer_session_id"] != viewer_session_id or
                session["client_instance_id"] != client_instance_id or
                session["scene_generation"] != scene_generation or
                session["action_revision"] != action_revision or
                (requested["source"] == "jev" and not intent_live(run, intent_id)) or
                latest_for_scene[-1]["intent_id"] != intent_id or
                not _current_session(run, session)):
            raise ViewerError("stale_scene", "acknowledgment scene mismatch", 409)
        command = next((item for item in public["commands"] if item["command_id"] == command_id), None)
        if command is None or command["action_revision"] != action_revision:
            raise ViewerError("unknown_command", "command is not in this exact plan", 422)
        if status not in {"applied", "no_change", "failed"}:
            raise ViewerError("input_invalid", "invalid acknowledgment status")
        if reason_code is not None and (not isinstance(reason_code, str) or not re.fullmatch(r"[a-z_]{1,40}", reason_code)):
            raise ViewerError("input_invalid", "invalid acknowledgment reason")
        previous = next((ack for ack in public["acks"] if ack["command_id"] == command_id), None)
        if previous:
            if previous["status"] == status and previous["reason_code"] == reason_code:
                return public
            raise ViewerError("ack_conflict", "command already acknowledged differently", 409)
        run.events.append("viewer_command_ack", intent_id=intent_id, command_id=command_id,
                          status=status, reason_code=reason_code)
    return intent_public(run, intent_id)


def projected_state(session: dict[str, Any], prompt: str) -> EgressViewerIntentV1:
    return EgressViewerIntentV1.model_validate({"schema": "viewer_intent@1", "prompt": prompt,
                                                "representation": session["representation"],
                                                "selected_target": session["selected_alias"],
                                                "scope_complete": session["scope_complete"],
                                                "catalog": session["catalog"]})


def projection_preview(session: dict[str, Any]) -> dict[str, Any]:
    """Exact fixed fields except the user prompt, which the browser adds visibly."""
    return {"schema": "viewer_intent@1", "representation": session["representation"],
            "selected_target": session["selected_alias"], "scope_complete": session["scope_complete"],
            "catalog": session["catalog"]}
