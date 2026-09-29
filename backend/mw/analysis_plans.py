"""M13 deterministic local analysis plans (``analysis_plan@1``).

Plans are compiled only from the checked-in templates below. Compilation reads stored
bytes/metadata and the method capability values ``/capabilities`` already computes, and runs
pure checks (M10 atom catalogs, M11 read-only preparation preview, M12 input projection
preflight, OpenMM read-only preflight). It never calls a tool implementation, ``Run.call``,
``JobQueue`` or a report builder, never infers chemistry and never produces numeric previews.

Interface for the execution driver (M13 T3):

* ``compile_plan(run, goal, inputs) -> dict``: pure; raises ``ToolFailure`` for malformed input
  (``input_invalid`` → 422, ``resource_exceeded`` → 429). Unmet prerequisites are recorded in the
  plan, not raised.
* ``create_plan(run, request_id, goal, inputs) -> dict``: idempotent admission + ``ObjectStore.put``
  + ``analysis_plan_created`` event under a short ``run._transition()``.
* ``load_plan(run, handle) -> dict``: validated stored plan (same run, recorded, well formed).
* ``check_compatibility(run, plan) -> dict``: recomputes the compatibility section.
* ``canonical_plan_hash(plan)``: sha256 of the canonical plan JSON (approval binding).
* ``request_binding(events, request_id)``: the ``analysis_*`` event binding a request UUID.

Step dict: ``{step_id, operation, operation_version, lane, bindings, params, outputs, depends_on}``.
Bindings map a *tool argument name* to ``{"kind": "existing", handle, expected_kind, expected_schema}``
or ``{"kind": "step_output", step_id, output_name, expected_kind, expected_schema}``.

* ``run_call``: ``Run.call(operation, {**resolved bindings, **params})``.
* ``durable_job``: ``params["timeout_s"]`` is the submit timeout; the remaining params plus
  resolved bindings are the job args, except ``prolif_prepare_v1`` whose job args are exactly
  ``params["request"]`` (its bindings list the request's handles for same-run verification only).
* ``report``: ``params["analysis_type"]`` selects a fixed builder in ``REPORT_TYPES``;
  ``inspection_report`` binds ``interaction_handle`` and ``prepared_handle``, ``method_report``
  binds ``result_handle``.
"""
from __future__ import annotations

import hashlib
import math
import uuid
from importlib.metadata import PackageNotFoundError
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from .core.errors import FailureClass, ToolFailure
from .core.handles import HANDLE_PREFIX, canonical_json, object_sha
from .tools.comparison import AtomRefV1, CompleteResidueRef, atom_rows

SCHEMA = "analysis_plan@1"
KIND = "analysis_plan"
PLANNER = "local_rules@1"
SOURCE = "local_rules"
PLAN_EVENT = "analysis_plan_created"
MAX_PLAN_BYTES = 64 * 1024
MAX_PLANS_PER_RUN = 100
MAX_STEPS = 8
LIMITS = {"max_steps": MAX_STEPS, "max_physical_attempts": 24, "max_active_wall_s": 1800,
          "max_retries_per_step": 1}
JOB_TIMEOUT_S = 120  # every fixed M11/M12/OpenMM protocol accepts at most 120 s
CHEMICAL_CATEGORIES = ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"]
CONTACT_TYPES = ("contact", "polar_contact", "hydrophobic_contact")
GOALS = ("inspect_ligand", "measure_atoms", "compare_structures", "chemical_interactions",
         "find_cavities", "minimize_protein")
TEMPLATE_VERSIONS = {goal: f"{goal}@1" for goal in GOALS}
LANES = ("run_call", "durable_job", "report")
TOP_LEVEL_KEYS = frozenset({"schema", "planner", "source", "plan_only", "goal", "template_version", "inputs",
                            "compatibility", "steps", "limits", "unmet_prerequisites", "deferred_bindings"})
STEP_KEYS = frozenset({"step_id", "operation", "operation_version", "lane", "bindings", "params", "outputs",
                       "depends_on"})
STRUCTURE_SCHEMAS = {"structure": "structure_selection@2", "prepared_structure": "prepared_structure@1",
                     "openmm_minimized_structure": "openmm_minimized_structure@1",
                     "chemical_structure": "chemical_structure@1"}
NATURAL_LANGUAGE_REASON = (
    "자연어 계획과 모델 보조 실행은 과학 데이터 전송 통로(게이트 투영·전송 전 미리보기·예산, 로드맵 M24)와 "
    "새 실제 호출 할당이 없어 사용할 수 없습니다. M8 뷰어 동의는 워크플로·모델·과학 권한을 주지 않습니다.")

# ---------------------------------------------------------------------------------------------
# Reviewed internal mapping table: the only place contract names meet accepted implementations.
# ``contract_name`` is the M13 contract wording; the other fields are the accepted M1–M12 names.
OPERATIONS: dict[str, dict[str, Any]] = {
    "prepare_structure": {"lane": "run_call", "tool": "prepare_structure", "method": None,
                          "contract_name": "optional prepare",
                          "outputs": [("prepared_structure", "prepared_structure", "prepared_structure@1")]},
    "compute_interactions": {"lane": "run_call", "tool": "compute_interactions", "method": None,
                             "contract_name": "geometric contacts",
                             "outputs": [("interaction_set", "interaction_set", "interaction_set@1")]},
    "compute_interface_sasa": {"lane": "run_call", "tool": "compute_interface_sasa", "method": "interface_sasa",
                               "contract_name": "FreeSASA",
                               "outputs": [("interface_sasa", "interface_sasa", "interface_sasa@1")]},
    "measure_distance": {"lane": "run_call", "tool": "measure_distance", "method": None,
                         "contract_name": "distance",
                         "outputs": [("atom_distance", "atom_distance", "atom_distance@1")]},
    "align_structures": {"lane": "run_call", "tool": "align_structures", "method": None,
                         "contract_name": "alignment",
                         "outputs": [("rigid_alignment", "rigid_alignment", "rigid_alignment@1")]},
    "prolif_prepare_v1": {"lane": "durable_job", "protocol_id": "prolif_prepare_v1",
                          "tool": "prepare_chemical_structure",
                          "implementation_version": "prolif_prepared_explicit_h@1",
                          "method": "chemical_interactions", "contract_name": "required M11 conversion",
                          "outputs": [("preparation_manifest", "chemical_preparation_manifest",
                                       "chemical_preparation_manifest@1"),
                                      ("chemical_structure", "chemical_structure", "chemical_structure@1"),
                                      ("chemical_graph", "chemical_graph", "chemical_graph@1")]},
    "prolif_detect_v1": {"lane": "durable_job", "protocol_id": "prolif_detect_v1",
                         "tool": "compute_chemical_interactions",
                         "implementation_version": "prolif_prepared_explicit_h@1",
                         "method": "chemical_interactions", "contract_name": "M11 calculation",
                         "outputs": [("chemical_interaction_set", "chemical_interaction_set",
                                      "chemical_interaction_set@1")]},
    "fpocket_detect_v1": {"lane": "durable_job", "protocol_id": "fpocket_detect_v1", "tool": "detect_pockets",
                          "implementation_version": "fpocket_detect_v1@1", "method": "pocket_detection",
                          "contract_name": "detector projection/detection",
                          "outputs": [("pocket_set", "pocket_set", "pocket_set@1")]},
    "openmm_protein_minimize": {"lane": "durable_job", "protocol_id": "openmm_protein_minimize",
                                "tool": "openmm_protein_minimize",
                                "implementation_version": "openmm_protein_minimize_v1",
                                "method": "openmm_protein_minimize", "contract_name": "OpenMM job",
                                "outputs": [("openmm_minimization", "openmm_minimization",
                                             "openmm_protein_minimization@1")]},
    "inspection_report": {"lane": "report", "contract_name": "saved contact report",
                          "outputs": [("report", "report_manifest", "report_manifest@1")]},
    "method_report": {"lane": "report", "contract_name": "method report",
                      "outputs": [("report", "method_report_manifest", "method_report_manifest@1")]},
}
# analysis_type -> fixed existing report builder, accepted result type and render version.
REPORT_TYPES: dict[str, dict[str, str]] = {
    "interaction_contacts": {"builder": "build_inspection_report", "result_kind": "interaction_set",
                             "result_schema": "interaction_set@1", "report_schema": "report_manifest@1",
                             "render_version": "inspection_markdown@1"},
    "interface_sasa": {"builder": "build_method_report", "result_kind": "interface_sasa",
                       "result_schema": "interface_sasa@1", "report_schema": "method_report_manifest@1",
                       "render_version": "interface_sasa_markdown@1"},
    "atom_distance": {"builder": "build_comparison_report", "result_kind": "atom_distance",
                      "result_schema": "atom_distance@1", "report_schema": "method_report_manifest@1",
                      "render_version": "comparison_markdown@1"},
    "rigid_alignment": {"builder": "build_comparison_report", "result_kind": "rigid_alignment",
                        "result_schema": "rigid_alignment@1", "report_schema": "method_report_manifest@1",
                        "render_version": "comparison_markdown@1"},
    "chemical_interactions": {"builder": "build_chemical_report", "result_kind": "chemical_interaction_set",
                              "result_schema": "chemical_interaction_set@1",
                              "report_schema": "method_report_manifest@1", "render_version": "chemical_markdown@1"},
    "pocket_detection": {"builder": "build_pocket_report", "result_kind": "pocket_set",
                         "result_schema": "pocket_set@1", "report_schema": "method_report_manifest@1",
                         "render_version": "pocket_markdown@2"},
    "openmm_protein_minimize": {"builder": "build_openmm_report", "result_kind": "openmm_minimization",
                                "result_schema": "openmm_protein_minimization@1",
                                "report_schema": "method_report_manifest@1", "render_version": "openmm_markdown@1"},
}
TEMPLATE_METHODS = {"inspect_ligand": "interface_sasa", "measure_atoms": None, "compare_structures": None,
                    "chemical_interactions": "chemical_interactions", "find_cavities": "pocket_detection",
                    "minimize_protein": "openmm_protein_minimize"}
TEMPLATE_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "inspect_ligand": {
        "required_inputs": ["source (structure with preparation policy, or prepared_structure)",
                            "ligand (exact 7-field residue identity)", "cutoff_A (2.5-6.0)",
                            "types (nonempty subset of contact types)"],
        "steps": ["prepare_structure (raw structure only)", "compute_interactions", "compute_interface_sasa",
                  "inspection_report", "method_report"]},
    "measure_atoms": {"required_inputs": ["source", "first AtomRef", "second AtomRef"],
                      "steps": ["measure_distance", "method_report"]},
    "compare_structures": {"required_inputs": ["reference", "moving", "pairs (3-1000 explicit CA AtomRef pairs)"],
                           "steps": ["align_structures", "method_report"]},
    "chemical_interactions": {
        "required_inputs": ["request (chemical_prepare_request@1, create_new or attach_existing, preview ready)"],
        "steps": ["prolif_prepare_v1", "prolif_detect_v1", "method_report"],
        "fixed": {"categories": CHEMICAL_CATEGORIES}},
    "find_cavities": {"required_inputs": [("source (prepared_structure, chemical_structure or "
                                           "openmm_minimized_structure)"), "chains (nonempty chain_auth list)"],
                      "steps": ["fpocket_detect_v1", "method_report"]},
    "minimize_protein": {"required_inputs": ["source (prepared_structure)", "selection_policy=protein_only",
                                             "hydrogen_policy=rebuild_pH7"],
                         "steps": ["openmm_protein_minimize", "method_report"]},
}
PREREQUISITE_MESSAGES = {
    "ligand_required": "리간드 인스턴스를 명시적으로 선택해야 합니다.",
    "ligand_ambiguous": "선택한 리간드 식별자가 소스에서 하나로 정해지지 않습니다.",
    "atoms_required": "기존 측정 화면에서 원자 두 개를 먼저 고르세요.",
    "ca_pairs_required": "기존 비교 화면에서 CA 대응표를 먼저 만드세요.",
    "chemical_request_required": "화학 작업 화면에서 준비 요청을 먼저 만드세요.",
    "chemical_preparation_not_ready": "화학 준비 미리보기가 준비되지 않았습니다(차단 항목 있음).",
    "chains_required": "공동 찾기에 쓸 체인을 명시적으로 고르세요.",
    "unsupported_source": "이 분석 목표는 선택한 소스 종류를 지원하지 않습니다.",
    "engine_unavailable": "이 분석에 필요한 방법을 사용할 수 없습니다.",
    "method_preflight_rejected": "방법의 읽기 전용 사전 검사가 이 입력을 거부했습니다.",
}


def _invalid(message: str, **detail: Any) -> ToolFailure:
    return ToolFailure(FailureClass.input_invalid, message, detail=detail)


class AnalysisConflict(Exception):
    """A typed 409 admission conflict with a fixed message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------------------------
# Strict request shapes. Identity models are the reviewed M10 ones (all 7 residue fields required).


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class Preparation(_Strict):
    altloc: Literal["highest_occupancy", "first"]
    waters: Literal["strip_all", "keep_all"]
    hydrogens: Literal["strip", "keep"]


class InspectLigandInputs(_Strict):
    source: str
    preparation: Preparation | None = None
    ligand: CompleteResidueRef | None = None
    cutoff_A: float = Field(ge=2.5, le=6.0, allow_inf_nan=False)
    types: list[Literal["contact", "polar_contact", "hydrophobic_contact"]] = Field(min_length=1, max_length=3)


class MeasureAtomsInputs(_Strict):
    source: str
    first: AtomRefV1 | None = None
    second: AtomRefV1 | None = None


class CaPair(_Strict):
    reference: AtomRefV1
    moving: AtomRefV1


class CompareInputs(_Strict):
    reference: str
    moving: str
    pairs: list[CaPair] | None = Field(default=None, max_length=1000)


class ChemicalInputs(_Strict):
    request: dict[str, Any] | None = None


class FindCavitiesInputs(_Strict):
    source: str
    chains: list[str] = Field(max_length=62)


class MinimizeInputs(_Strict):
    source: str
    selection_policy: Literal["protein_only"]
    hydrogen_policy: Literal["rebuild_pH7"]


INPUT_MODELS: dict[str, type[_Strict]] = {
    "inspect_ligand": InspectLigandInputs, "measure_atoms": MeasureAtomsInputs,
    "compare_structures": CompareInputs, "chemical_interactions": ChemicalInputs,
    "find_cavities": FindCavitiesInputs, "minimize_protein": MinimizeInputs}


# ---------------------------------------------------------------------------------------------
# Capabilities (the same values /capabilities computes; nothing here runs a scientific method).
def _method_capability(method: str) -> dict[str, Any]:
    if method == "interface_sasa":
        try:
            from .tools import sasa
            value = sasa.engine_capability()
            dependencies = sasa.dependencies()
        except (AttributeError, ImportError, OSError, PackageNotFoundError, RuntimeError, ToolFailure,
                ValueError) as exc:  # the same probe failures /capabilities reports as unavailable
            reason = exc.detail.get("reason_code") if isinstance(exc, ToolFailure) else None
            return {"available": False, "reason_code": reason or "engine_missing_or_invalid"}
        return {"available": True, "reason_code": None, "method_id": value["method_id"],
                "engine_version": value["engine_version"],
                "dependencies_sha256": hashlib.sha256(canonical_json(dependencies)).hexdigest()}
    if method == "openmm_protein_minimize":
        from .tools import openmm_method
        value = openmm_method.capability()
        if not value["available"]:
            return {"available": False, "reason_code": value.get("reason_code") or "openmm_unavailable"}
        return {"available": True, "reason_code": None, "method_id": value["method_id"],
                "distribution_version": value["distribution_version"], "engine_build": value["engine_build"]}
    if method == "chemical_interactions":
        from .jobs.queue import chemical_capability
        value = chemical_capability()
        if not value["available"]:
            return {"available": False, "reason_code": value.get("reason_code") or "worker_missing"}
        return {"available": True, "reason_code": None, "protocol": value["protocol"],
                "versions": value["versions"], "worker_sha256": value["worker_sha256"],
                "dependency_manifest_sha256": value["dependency_manifest_sha256"]}
    if method == "pocket_detection":
        from . import pocket_bundle
        value = pocket_bundle.capability_snapshot()
        if not value["available"]:
            return {"available": False, "reason_code": value.get("reason_code") or value["status"]}
        return {"available": True, "reason_code": None,
                **{key: value[key] for key in ("release", "build", "package_sha256", "executable_sha256",
                                               "parser_version")},
                "worker_sha256": pocket_bundle.worker_sha256()}
    raise ValueError("unknown analysis method")


def _compatibility(run: Any, goal: str, operations: list[tuple[str, dict[str, Any]]],
                   cache: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    cache = {} if cache is None else cache
    entries = []
    for index, (operation, params) in enumerate(operations, 1):
        table = OPERATIONS[operation]
        entry: dict[str, Any] = {"step_id": f"s{index:02d}", "operation": operation, "lane": table["lane"]}
        if table["lane"] == "report":
            report = REPORT_TYPES[params["analysis_type"]]
            entry.update(analysis_type=params["analysis_type"], builder=report["builder"],
                         report_schema=report["report_schema"], render_version=report["render_version"])
        else:
            entry.update(tool=table["tool"], tool_version=run.registry.specs[table["tool"]].version)
            if table["lane"] == "durable_job":
                entry.update(protocol_id=table["protocol_id"], implementation_version=table["implementation_version"])
            method = table["method"]
            if method is not None and method not in cache:
                cache[method] = _method_capability(method)
            entry["method"] = cache[method] if method is not None else None
        entries.append(entry)
    return {"planner": PLANNER, "template_version": TEMPLATE_VERSIONS[goal], "steps": entries}


def _template_availability(methods: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for goal in GOALS:
        method = TEMPLATE_METHODS[goal]
        value = methods.get(method) if method else None
        available = True if method is None else bool(value and value.get("available"))
        reason_code = None if available else ((value or {}).get("reason_code") or "method_unavailable")
        result[goal] = {"available": available, "method": method, "reason_code": reason_code,
                        "reason": None if available else PREREQUISITE_MESSAGES["engine_unavailable"]}
    return result


def capability(methods: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """``/capabilities`` entry; ``methods`` are the already computed method capabilities."""
    if methods is None:
        methods = {method: _method_capability(method) for method in
                   ("interface_sasa", "openmm_protein_minimize", "chemical_interactions", "pocket_detection")}
    return {"available": True, "planner": PLANNER, "source": SOURCE, "plan_schema": SCHEMA,
            "templates": _template_availability(methods),
            "natural_language_planning": {"available": False, "reason": NATURAL_LANGUAGE_REASON},
            "limits": dict(LIMITS), "max_plans_per_run": MAX_PLANS_PER_RUN, "max_plan_bytes": MAX_PLAN_BYTES}


def templates() -> dict[str, Any]:
    cap = capability()
    rows = [{"goal": goal, "template_version": TEMPLATE_VERSIONS[goal], **TEMPLATE_DESCRIPTIONS[goal],
             **cap["templates"][goal]} for goal in GOALS]
    return {"schema": "analysis_templates@1", "planner": PLANNER, "source": SOURCE, "templates": rows,
            "natural_language_planning": cap["natural_language_planning"], "limits": dict(LIMITS)}


# ---------------------------------------------------------------------------------------------
# Input checks (pure reads of stored bytes).
def _meta(run: Any, handle: Any, name: str) -> dict[str, Any]:
    if type(handle) is not str:
        raise _invalid("handle must be a string", field=name)
    try:
        return run.store.meta(handle)
    except (KeyError, ValueError, TypeError) as exc:
        raise _invalid("unknown or foreign-run handle", field=name) from exc


def _structure_meta(run: Any, handle: Any, name: str) -> dict[str, Any]:
    meta = _meta(run, handle, name)
    if STRUCTURE_SCHEMAS.get(meta["kind"]) != meta["schema"]:
        raise _invalid("handle is not a supported structure kind/schema", field=name)
    return meta


def _existing(meta: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "existing", "handle": meta["handle"], "expected_kind": meta["kind"],
            "expected_schema": meta["schema"]}


def _output(step_id: str, operation: str, name: str) -> dict[str, Any]:
    _, kind, schema = next(item for item in OPERATIONS[operation]["outputs"] if item[0] == name)
    return {"kind": "step_output", "step_id": step_id, "output_name": name, "expected_kind": kind,
            "expected_schema": schema}


def _prereq(code: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, "message": PREREQUISITE_MESSAGES[code], "detail": detail}


def _unsupported(meta: dict[str, Any], reason_code: str = "unsupported_source_kind") -> dict[str, Any]:
    return _prereq("unsupported_source", source_kind=meta["kind"], reason_code=reason_code)


def _resolved_atom(source: str, ref: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    if ref["structure_handle"] != source:
        raise _invalid("atom belongs to a different structure source")
    rows = catalog["rows"]
    index = ref["site_index"]
    if index >= len(rows) or rows[index]["ref"] != ref:
        raise _invalid("atom identity does not match source site")
    return rows[index]


# ---------------------------------------------------------------------------------------------
# Templates.
def _inspect_ligand(run: Any, data: InspectLigandInputs, prereqs: list[dict[str, Any]]) -> tuple[dict, list]:
    meta = _structure_meta(run, data.source, "source")
    raw = meta["kind"] == "structure"
    if raw and data.preparation is None:
        raise _invalid("a raw structure needs an explicit preparation policy")
    if not raw and data.preparation is not None:
        raise _invalid("preparation policy applies only to a raw structure")
    if len(set(data.types)) != len(data.types):
        raise _invalid("contact types must be unique")
    ligand = data.ligand.model_dump() if data.ligand is not None else None
    supported = meta["kind"] in {"structure", "prepared_structure"}
    if not supported:
        prereqs.append(_unsupported(meta))
    if ligand is None:
        prereqs.append(_prereq("ligand_required"))
    elif supported:
        from .tools.structural import structure_residues
        matches = [item for item in structure_residues(run.store, meta["handle"])["ligands"] if item == ligand]
        if not matches:
            raise _invalid("selected ligand is not a ligand instance of the source")
        if len(matches) > 1:
            prereqs.append(_prereq("ligand_ambiguous", ligand=ligand))
    preparation = ({**data.preparation.model_dump(), "missing_residues": "leave_gaps", "symmetry_mates": "ignore"}
                   if raw else None)
    types = sorted(data.types)
    inputs = {"source": meta["handle"], "source_kind": meta["kind"], "preparation": preparation, "ligand": ligand,
              "cutoff_A": float(data.cutoff_A), "types": types, "engine": "geometric"}
    steps: list[tuple[str, dict, dict, list[str]]] = []
    if raw:
        steps.append(("prepare_structure", {"structure": _existing(meta)}, dict(preparation), []))
        prepared = _output("s01", "prepare_structure", "prepared_structure")
        base: list[str] = ["s01"]
    else:
        prepared = _existing(meta)
        base = []
    offset = len(steps)
    contacts, sasa = f"s{offset + 1:02d}", f"s{offset + 2:02d}"
    steps.append(("compute_interactions", {"structure": prepared},
                  {"ligand": ligand, "cutoff_A": float(data.cutoff_A), "types": types, "engine": "geometric"},
                  list(base)))
    steps.append(("compute_interface_sasa", {"structure": prepared}, {"ligand": ligand}, list(base)))
    steps.append(("inspection_report", {"interaction_handle": _output(contacts, "compute_interactions",
                                                                       "interaction_set"),
                                        "prepared_handle": prepared},
                  {"analysis_type": "interaction_contacts"}, sorted({contacts, *base})))
    steps.append(("method_report", {"result_handle": _output(sasa, "compute_interface_sasa", "interface_sasa")},
                  {"analysis_type": "interface_sasa"}, [sasa]))
    return inputs, steps


def _measure_atoms(run: Any, data: MeasureAtomsInputs, prereqs: list[dict[str, Any]]) -> tuple[dict, list]:
    meta = _structure_meta(run, data.source, "source")
    supported = meta["kind"] in {"structure", "prepared_structure", "openmm_minimized_structure"}
    if not supported:
        prereqs.append(_unsupported(meta))
    first = data.first.model_dump() if data.first is not None else None
    second = data.second.model_dump() if data.second is not None else None
    if first is None or second is None:
        prereqs.append(_prereq("atoms_required"))
    for ref in (first, second):
        if ref is not None and ref["structure_handle"] != meta["handle"]:
            raise _invalid("atom belongs to a different structure source")
    if supported and first is not None and second is not None:
        catalog = atom_rows(run.store, meta["handle"])
        _resolved_atom(meta["handle"], first, catalog)
        _resolved_atom(meta["handle"], second, catalog)
    inputs = {"source": meta["handle"], "source_kind": meta["kind"], "first": first, "second": second}
    steps = [("measure_distance", {"structure": _existing(meta)}, {"first": first, "second": second}, []),
             ("method_report", {"result_handle": _output("s01", "measure_distance", "atom_distance")},
              {"analysis_type": "atom_distance"}, ["s01"])]
    return inputs, steps


def _compare(run: Any, data: CompareInputs, prereqs: list[dict[str, Any]]) -> tuple[dict, list]:
    reference = _structure_meta(run, data.reference, "reference")
    moving = _structure_meta(run, data.moving, "moving")
    if reference["handle"] == moving["handle"]:
        raise _invalid("reference and moving source must differ")
    allowed = {"structure", "prepared_structure", "openmm_minimized_structure"}
    supported = True
    for meta in (reference, moving):
        if meta["kind"] not in allowed:
            prereqs.append(_unsupported(meta))
            supported = False
    pairs = [pair.model_dump() for pair in data.pairs] if data.pairs else None
    if not pairs:
        prereqs.append(_prereq("ca_pairs_required"))
    elif len(pairs) < 3:
        raise _invalid("alignment requires 3-1000 explicit CA pairs")
    else:
        for pair in pairs:
            if (pair["reference"]["structure_handle"] != reference["handle"] or
                    pair["moving"]["structure_handle"] != moving["handle"]):
                raise _invalid("pair atom belongs to a different structure source")
        if supported:
            ref_catalog, mov_catalog = atom_rows(run.store, reference["handle"]), atom_rows(run.store, moving["handle"])
            used_ref: set[int] = set()
            used_mov: set[int] = set()
            for pair in pairs:
                a = _resolved_atom(reference["handle"], pair["reference"], ref_catalog)
                b = _resolved_atom(moving["handle"], pair["moving"], mov_catalog)
                if not (a["protein"] and b["protein"] and a["ref"]["atom_name"] == b["ref"]["atom_name"] == "CA"):
                    raise _invalid("alignment accepts protein CA sites only")
                ai, bi = a["ref"]["site_index"], b["ref"]["site_index"]
                if ai in used_ref or bi in used_mov:
                    raise _invalid("duplicate CA site in correspondence")
                used_ref.add(ai)
                used_mov.add(bi)
    inputs = {"reference": reference["handle"], "reference_kind": reference["kind"], "moving": moving["handle"],
              "moving_kind": moving["kind"], "pairs": pairs}
    steps = [("align_structures", {"reference": _existing(reference), "moving": _existing(moving)},
              {"pairs": pairs}, []),
             ("method_report", {"result_handle": _output("s01", "align_structures", "rigid_alignment")},
              {"analysis_type": "rigid_alignment"}, ["s01"])]
    return inputs, steps


def _chemical(run: Any, data: ChemicalInputs, prereqs: list[dict[str, Any]]) -> tuple[dict, list]:
    request = data.request
    bindings: dict[str, Any] = {}
    if request is None:
        prereqs.append(_prereq("chemical_request_required"))
    else:
        from .chemical_inputs import preview
        mode = request.get("mode")
        try:
            preview(run.store, request, strict=True)
        except ToolFailure as exc:
            if exc.cls is not FailureClass.precondition:
                raise _invalid("invalid chemical preparation request") from exc
            codes = sorted({item.get("code") for item in exc.detail.get("blockers", [])
                            if isinstance(item, dict) and isinstance(item.get("code"), str)})
            prereqs.append(_prereq("chemical_preparation_not_ready", blocker_codes=codes))
        except (KeyError, ValueError, TypeError, AttributeError, IndexError, UnicodeError) as exc:
            raise _invalid("invalid chemical preparation request") from exc
        names = (("complex", "complex_handle"), ("ligand_sdf", "ligand_sdf_handle")) if mode == "attach_existing" \
            else (("receptor_input", "receptor_input_handle"), ("ligand_sdf", "ligand_sdf_handle"))
        for name, key in names:
            bindings[name] = _existing(_meta(run, request[key], key))
        sidecar = request["connectivity"].get("sidecar_handle")
        if sidecar is not None:
            bindings["connectivity_sidecar"] = _existing(_meta(run, sidecar, "sidecar_handle"))
    inputs = {"request": request, "mode": request.get("mode") if request else None,
              "categories": list(CHEMICAL_CATEGORIES)}
    steps = [("prolif_prepare_v1", bindings, {"request": request, "timeout_s": JOB_TIMEOUT_S}, []),
             ("prolif_detect_v1", {"graph_handle": _output("s01", "prolif_prepare_v1", "chemical_graph")},
              {"schema": "chemical_detect_request@1", "categories": list(CHEMICAL_CATEGORIES),
               "timeout_s": JOB_TIMEOUT_S}, ["s01"]),
             ("method_report", {"result_handle": _output("s02", "prolif_detect_v1", "chemical_interaction_set")},
              {"analysis_type": "chemical_interactions"}, ["s02"])]
    return inputs, steps


def _find_cavities(run: Any, data: FindCavitiesInputs, prereqs: list[dict[str, Any]]) -> tuple[dict, list]:
    meta = _structure_meta(run, data.source, "source")
    if len(set(data.chains)) != len(data.chains) or any(not chain for chain in data.chains):
        raise _invalid("chains must be unique nonempty chain_auth strings")
    chains = sorted(data.chains)
    supported = meta["kind"] in {"prepared_structure", "chemical_structure", "openmm_minimized_structure"}
    if not supported:
        prereqs.append(_unsupported(meta, "raw_structure_requires_preparation" if meta["kind"] == "structure"
                                    else "unsupported_source_kind"))
    if not chains:
        prereqs.append(_prereq("chains_required"))
    elif supported:
        from .pocket_bundle import preflight
        summary = preflight(run, meta["handle"], chains)
        reject = summary.get("reject")
        if reject is not None:
            if reject.get("reason_code") in {"unknown_chain", "invalid_chain_selection"}:
                raise _invalid("selected chain is not in the source")
            prereqs.append(_prereq("method_preflight_rejected", method="pocket_detection",
                                   reason_code=reject.get("reason_code"), stage=reject.get("stage")))
        elif summary.get("selected_chains") != chains:
            raise _invalid("chain selection does not resolve exactly")
    inputs = {"source": meta["handle"], "source_kind": meta["kind"], "chains": chains}
    steps = [("fpocket_detect_v1", {"structure": _existing(meta)}, {"chains": chains, "timeout_s": JOB_TIMEOUT_S},
              []),
             ("method_report", {"result_handle": _output("s01", "fpocket_detect_v1", "pocket_set")},
              {"analysis_type": "pocket_detection"}, ["s01"])]
    return inputs, steps


def _minimize(run: Any, data: MinimizeInputs, prereqs: list[dict[str, Any]],
              method: dict[str, Any]) -> tuple[dict, list]:
    meta = _structure_meta(run, data.source, "source")
    if meta["kind"] != "prepared_structure":
        prereqs.append(_unsupported(meta, "raw_structure_requires_preparation" if meta["kind"] == "structure"
                                    else "unsupported_source_kind"))
    elif method.get("available"):
        from .tools.openmm_method import preflight
        try:
            preflight(run.store, meta["handle"], seed=run.seed)
        except ToolFailure as exc:
            prereqs.append(_prereq("method_preflight_rejected", method="openmm_protein_minimize",
                                   reason_code=exc.detail.get("reason_code") or exc.cls.value))
    inputs = {"source": meta["handle"], "source_kind": meta["kind"], "selection_policy": data.selection_policy,
              "hydrogen_policy": data.hydrogen_policy}
    steps = [("openmm_protein_minimize", {"structure": _existing(meta)},
              {"selection_policy": data.selection_policy, "hydrogen_policy": data.hydrogen_policy,
               "timeout_s": JOB_TIMEOUT_S}, []),
             ("method_report", {"result_handle": _output("s01", "openmm_protein_minimize", "openmm_minimization")},
              {"analysis_type": "openmm_protein_minimize"}, ["s01"])]
    return inputs, steps


def compile_plan(run: Any, goal: Any, inputs: Any) -> dict[str, Any]:
    """Compile one checked-in template into a plan dict (not stored). Pure; no scientific call."""
    if goal not in GOALS:
        raise _invalid("unknown analysis goal")
    if type(inputs) is not dict:
        raise _invalid("inputs must be an object")
    try:
        _finite(inputs)
        data = INPUT_MODELS[goal].model_validate(inputs)
    except PydanticValidationError as exc:
        raise _invalid("analysis inputs are invalid for this goal") from exc
    prereqs: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}
    method = TEMPLATE_METHODS[goal]
    if method is not None:
        cache[method] = _method_capability(method)
    if goal == "inspect_ligand":
        normalized, raw_steps = _inspect_ligand(run, data, prereqs)
    elif goal == "measure_atoms":
        normalized, raw_steps = _measure_atoms(run, data, prereqs)
    elif goal == "compare_structures":
        normalized, raw_steps = _compare(run, data, prereqs)
    elif goal == "chemical_interactions":
        normalized, raw_steps = _chemical(run, data, prereqs)
    elif goal == "find_cavities":
        normalized, raw_steps = _find_cavities(run, data, prereqs)
    else:
        normalized, raw_steps = _minimize(run, data, prereqs, cache[method])
    if method is not None and not cache[method]["available"]:
        prereqs.append(_prereq("engine_unavailable", method=method, reason_code=cache[method]["reason_code"]))
    compatibility = _compatibility(run, goal, [(operation, params) for operation, _, params, _ in raw_steps], cache)
    steps = []
    for index, (operation, bindings, params, depends) in enumerate(raw_steps, 1):
        table = OPERATIONS[operation]
        entry = compatibility["steps"][index - 1]
        version = (entry["tool_version"] if table["lane"] != "report" else
                   f"{entry['report_schema']}/{entry['render_version']}")
        steps.append({"step_id": f"s{index:02d}", "operation": operation, "operation_version": version,
                      "lane": table["lane"], "bindings": bindings, "params": params,
                      "outputs": [{"name": name, "kind": kind, "schema": schema}
                                  for name, kind, schema in table["outputs"]],
                      "depends_on": depends})
    deferred = [{"step_id": step["step_id"], "output_name": output["name"], "kind": output["kind"],
                 "schema": output["schema"]} for step in steps for output in step["outputs"]]
    plan = {"schema": SCHEMA, "planner": PLANNER, "source": SOURCE, "plan_only": True, "goal": goal,
            "template_version": TEMPLATE_VERSIONS[goal], "inputs": normalized, "compatibility": compatibility,
            "steps": steps, "limits": dict(LIMITS), "unmet_prerequisites": prereqs, "deferred_bindings": deferred}
    validate_plan(plan)
    if len(canonical_json(plan)) > MAX_PLAN_BYTES:
        raise ToolFailure(FailureClass.resource_exceeded, "analysis plan exceeds 64 KiB",
                          detail={"reason_code": "plan_too_large"})
    return plan


def _finite(value: Any, depth: int = 0) -> None:
    if depth > 32:
        raise _invalid("inputs are nested too deeply")
    if isinstance(value, float) and not math.isfinite(value):
        raise _invalid("numeric inputs must be finite")
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise _invalid("input keys must be strings")
            _finite(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _finite(item, depth + 1)


def validate_plan(plan: Any) -> None:
    """Structural check of an ``analysis_plan@1`` dict; raises ValueError."""
    if type(plan) is not dict or set(plan) != TOP_LEVEL_KEYS:
        raise ValueError("analysis plan top-level keys differ")
    if (plan["schema"] != SCHEMA or plan["planner"] != PLANNER or plan["source"] != SOURCE or
            plan["plan_only"] is not True or plan["goal"] not in GOALS or
            plan["template_version"] != TEMPLATE_VERSIONS[plan["goal"]] or plan["limits"] != LIMITS):
        raise ValueError("analysis plan identity differs")
    steps = plan["steps"]
    if type(steps) is not list or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError("analysis plan step count out of range")
    outputs: dict[tuple[str, str], tuple[str, str]] = {}
    for index, step in enumerate(steps, 1):
        if type(step) is not dict or set(step) != STEP_KEYS or step["step_id"] != f"s{index:02d}":
            raise ValueError("analysis plan step shape differs")
        table = OPERATIONS.get(step["operation"])
        if table is None or step["lane"] != table["lane"] or step["lane"] not in LANES:
            raise ValueError("analysis plan operation or lane differs")
        earlier = {f"s{i:02d}" for i in range(1, index)}
        if type(step["depends_on"]) is not list or not set(step["depends_on"]) <= earlier or \
                len(set(step["depends_on"])) != len(step["depends_on"]):
            raise ValueError("analysis plan dependency is not an earlier step")
        if step["outputs"] != [{"name": n, "kind": k, "schema": s} for n, k, s in table["outputs"]]:
            raise ValueError("analysis plan outputs differ")
        if type(step["params"]) is not dict or type(step["bindings"]) is not dict:
            raise ValueError("analysis plan params or bindings are not objects")
        for binding in step["bindings"].values():
            if type(binding) is not dict:
                raise ValueError("analysis plan binding shape differs")
            if binding.get("kind") == "existing":
                if set(binding) != {"kind", "handle", "expected_kind", "expected_schema"}:
                    raise ValueError("analysis plan existing binding shape differs")
            elif binding.get("kind") == "step_output":
                if (set(binding) != {"kind", "step_id", "output_name", "expected_kind", "expected_schema"} or
                        binding["step_id"] not in step["depends_on"] or
                        outputs.get((binding["step_id"], binding["output_name"])) !=
                        (binding["expected_kind"], binding["expected_schema"])):
                    raise ValueError("analysis plan step-output binding differs")
            else:
                raise ValueError("analysis plan binding kind differs")
        for name, kind, schema in table["outputs"]:
            outputs[(step["step_id"], name)] = (kind, schema)
    prereqs = plan["unmet_prerequisites"]
    if type(prereqs) is not list or any(type(item) is not dict or set(item) != {"code", "message", "detail"} or
                                        item["code"] not in PREREQUISITE_MESSAGES for item in prereqs):
        raise ValueError("analysis plan prerequisites differ")


def canonical_plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(plan)).hexdigest()


def check_compatibility(run: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """Recompute the compatibility manifest from current capabilities; report exact mismatches."""
    validate_plan(plan)
    current = _compatibility(run, plan["goal"], [(step["operation"], step["params"]) for step in plan["steps"]])
    recorded = plan["compatibility"]
    previous = {entry.get("step_id"): entry for entry in recorded.get("steps", []) if type(entry) is dict}
    mismatched = [entry["step_id"] for entry in current["steps"] if previous.get(entry["step_id"]) != entry]
    return {"compatible": recorded == current, "mismatched_steps": mismatched, "current": current}


# ---------------------------------------------------------------------------------------------
# Admission, storage and reads.
def _request_uuid(value: Any) -> str:
    try:
        parsed = uuid.UUID(value) if type(value) is str else None
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != value:
        raise _invalid("request_id must be a canonical lowercase UUID")
    return value


def request_binding(events: list[dict[str, Any]], request_id: str) -> dict[str, Any] | None:
    """The first ``analysis_*`` event that bound ``request_id`` (request IDs are unique per run)."""
    return next((event for event in events if str(event.get("type", "")).startswith("analysis_") and
                 event.get("request_id") == request_id), None)


def _recorded(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["type"] == PLAN_EVENT and event.get("plan_handle") not in first:
            first[event["plan_handle"]] = event
    return list(first.values())


def _replay(run: Any, binding: dict[str, Any], request_sha: str) -> dict[str, Any]:
    if binding.get("type") != PLAN_EVENT or binding.get("request_sha256") != request_sha:
        raise AnalysisConflict("request_id_conflict", "request_id was already used with a different body")
    return _public(run, binding["plan_handle"]) | {"replayed": True}


def create_plan(run: Any, request_id: Any, goal: Any, inputs: Any) -> dict[str, Any]:
    request_id = _request_uuid(request_id)
    try:
        request_sha = hashlib.sha256(canonical_json({"goal": goal, "inputs": inputs})).hexdigest()
    except (TypeError, ValueError) as exc:
        raise _invalid("analysis request must be finite JSON") from exc
    binding = request_binding(list(run.events.read()), request_id)
    if binding is not None:
        return _replay(run, binding, request_sha)
    plan = compile_plan(run, goal, inputs)
    raw_handle = _plan_handle(run, plan)
    with run._transition():
        events = list(run.events.read())
        binding = request_binding(events, request_id)
        if binding is not None:
            return _replay(run, binding, request_sha)
        recorded = _recorded(events)
        if raw_handle not in {event["plan_handle"] for event in recorded} and len(recorded) >= MAX_PLANS_PER_RUN:
            raise ToolFailure(FailureClass.resource_exceeded, "analysis plan limit per run reached",
                              detail={"reason_code": "plan_limit"})
        try:
            run.store.meta(raw_handle)
        except KeyError:
            if any(event["type"] == "object_created" and event.get("handle") == raw_handle for event in events):
                run.store.rebuild_from_events()
        stored = run.store.put(KIND, SCHEMA, plan, summary={"goal": plan["goal"],
                                                            "template_version": plan["template_version"],
                                                            "executable": not plan["unmet_prerequisites"]})
        if stored.handle != raw_handle:
            raise ValueError("analysis plan handle mismatch")
        run.events.append(PLAN_EVENT, request_id=request_id, request_sha256=request_sha, plan_handle=stored.handle,
                          plan_sha256=canonical_plan_hash(plan), goal=plan["goal"],
                          executable=not plan["unmet_prerequisites"])
    return _public(run, stored.handle) | {"replayed": False}


def _plan_handle(run: Any, plan: dict[str, Any]) -> str:
    return f"{HANDLE_PREFIX}{run.run_id}/{KIND}/{object_sha(KIND, SCHEMA, canonical_json(plan))}"


def load_plan(run: Any, handle: Any) -> dict[str, Any]:
    """A validated, recorded plan of this run. Raises ToolFailure(input_invalid) otherwise."""
    meta = _meta(run, handle, "handle")
    if (meta["kind"], meta["schema"], meta["fmt"]) != (KIND, SCHEMA, "json"):
        raise _invalid("handle is not an analysis plan")
    if not any(event["type"] == PLAN_EVENT and event.get("plan_handle") == handle for event in run.events.read()):
        raise _invalid("analysis plan was not admitted in this run")
    try:
        plan = run.store.load_bounded_json(handle, MAX_PLAN_BYTES)
        validate_plan(plan)
    except (KeyError, ValueError, TypeError) as exc:
        raise _invalid("stored analysis plan is corrupt") from exc
    return plan


def _public(run: Any, handle: str) -> dict[str, Any]:
    plan = load_plan(run, handle)
    ordinal = next(i for i, event in enumerate(_recorded(list(run.events.read())), 1)
                   if event["plan_handle"] == handle)
    return {"handle": handle, "plan": plan, "plan_sha256": canonical_plan_hash(plan),
            "executable": not plan["unmet_prerequisites"], "ordinal": ordinal}


def plan_detail(run: Any, handle: Any) -> dict[str, Any]:
    return _public(run, handle)


def list_plans(run: Any) -> dict[str, Any]:
    rows = [{"handle": event["plan_handle"], "goal": event.get("goal"), "ordinal": ordinal,
             "created_seq": event["seq"], "executable": event.get("executable")}
            for ordinal, event in enumerate(_recorded(list(run.events.read())), 1)]
    return {"schema": "analysis_plan_list@1", "total": len(rows), "rows": rows[:MAX_PLANS_PER_RUN]}
