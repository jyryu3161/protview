"""M29 T6: every consumer of a prepared structure is declared, and every refusal it relies on exists (spec
.dryforge/spec.md 5.1, 5.2; plan T6; handoff absolute condition 4).

T1's measurement ``docs/qa/m29-repair-20261013/probe/consumers_inventory.py`` moved into a test (standard library
AST and string scan of the source; PyYAML for ``config/tools.yaml``; no ``mw`` import, no ``.deps``, a few seconds).
A consumer is any function, class or route of ``backend/mw`` that

* holds one of the strings ``prepared_structure(@1)`` / ``preparation_manifest(@1)`` / ``prepared_coordinates(@1)`` /
  ``leave_gaps`` / ``modeled_internal_gaps`` or a handle pattern that admits a prepared structure,
* reads a module-level name whose value (through imports) holds such a string,
* subscripts ``["manifest"]`` / calls ``.get("manifest")`` or reads a preparation-manifest field of a manifest variable,
* compares a ``kind`` / ``schema`` / ``structure_kind`` / ``source_kind`` with such a string,
* calls a known structure consumer (the structure parser, residue / byte / atom catalogs, the M7 preflight, the pocket
  projection, the chemical preview, the viewer session and saved-view / figure writers, the inspection report and
  pipeline, the M13 plan, the PDB ID hint, the M21 / M23 selections),
* declares a preparation policy field (``waters``, ``missing_residues``, ...) or a structure handle field
  (``structure_handle``, ``prepared_handle``, ``input_handle``) on a model, or is a route with a ``structure`` query.

Each consumer must be DECLARED below (receive | refuse | read_only | blocked_upstream | judgement | unrelated, one
reason line each) or call the refusal itself. A ``refuse`` or ``blocked_upstream`` declaration names the guard
functions it relies on, and each named guard must contain a refusal call (``reject_if_repaired``, or the API helper
``_repaired_refusal`` that calls it). ``receive``, ``read_only`` and ``judgement`` points must not refuse. The tool
contracts that accept a prepared structure (or a numbering map, which only a structure makes) are declared per lane,
and the ``Run.call`` allow-list is exactly the modeling entry ``generate_mutation_candidates``. The self-tests at the
end check that the inventory catches a new undeclared consumer, a removed refusal call, a widened allow-list, a refusing
receive point and an undeclared tool contract. The behaviour of every refusal target is in
``test_structure_repair_refusals.py``.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MW_DIR = ROOT / "backend" / "mw"
TOOLS_YAML = ROOT / "config" / "tools.yaml"

TARGET_STRINGS = frozenset({"prepared_structure", "prepared_structure@1", "preparation_manifest",
                            "preparation_manifest@1", "prepared_coordinates", "prepared_coordinates@1"})
GAP_STRINGS = frozenset({"leave_gaps", "modeled_internal_gaps"})
MANIFEST_FIELDS = frozenset({"waters", "missing_residues", "input", "source_handle", "hydrogens", "altloc",
                             "model_index", "model_number", "symmetry_mates", "removed", "altloc_choices",
                             "protonation", "repair"})
MANIFEST_VARS = frozenset({"manifest", "prep", "source_manifest", "prep_data"})
MANIFEST_SCOPES = frozenset({"waters", "missing_residues", "altloc", "hydrogens", "symmetry_mates"})
HANDLE_FIELDS = frozenset({"structure_handle", "prepared_handle", "input_handle"})
ROUTE_METHODS = frozenset({"get", "post", "put", "delete", "patch"})
# Calls whose callee (resolved to its defining module) reads a prepared structure or is a consumer entry (T1 + figures).
CALL_TARGETS = frozenset({("tools/structural", n) for n in ("_parse", "structure_bytes", "structure_residues")} | {
    ("tools/comparison", "atom_rows"), ("tools/openmm_method", "preflight"),
    ("pocket_input", "_load_source"), ("pocket_input", "project"), ("pocket_input", "preflight"),
    ("pocket_bundle", "preflight"), ("pocket_bundle", "submission"),
    ("chemical_inputs", "_source_rows"), ("chemical_inputs", "preview"), ("chemical_bundle", "prepare_selected"),
    ("viewer_intents", "create_session"), ("saved_scenes", "save_scene"), ("saved_scenes", "save_figure"),
    ("saved_scenes", "_source"), ("numbering_reads", "pdb_id_hint"), ("reports", "build_inspection_report"),
    ("workflows", "inspect_complex"), ("analysis_plans", "create_plan"), ("mutation_model_bundle", "selection"),
    ("sequence_ga_jobs", "selection")})
REFUSAL = "reject_if_repaired"
API_HELPER = "_repaired_refusal"
REFUSAL_CALLS = frozenset({REFUSAL, API_HELPER})
ORCHESTRATOR = "backend/mw/runtime/orchestrator.py"
APP = "backend/mw/api/app.py"
ENERGETIC = "backend/mw/tools/energetic.py"
ALLOW_LIST = "REPAIRED_STRUCTURE_TOOLS"
MODELING_TOOLS = frozenset({"generate_mutation_candidates"})   # spec 5.1: the only Run.call entry of the modeling path

R, F, RO, BU, J, U = "receive", "refuse", "read_only", "blocked_upstream", "judgement", "unrelated"
CATEGORIES = (R, F, RO, BU, J, U)

# --- guards (file::qualname; each must contain a refusal call) ------------------------------------------------------
G_RUN = f"{ORCHESTRATOR}::Run._validated_bound"           # every Run.call tool but generate_mutation_candidates
G_JOB = "backend/mw/jobs/queue.py::JobQueue.submit"        # the generic job branch: M7 minimization, PyRosetta
G_POCKET = "backend/mw/pocket_input.py::_load_source"      # M12 job submission and re-projection
G_CHEM = "backend/mw/chemical_inputs.py::_source_rows"     # M11 preview, prolif_prepare_v1, M13 chemistry
G_M16 = "backend/mw/tools/site_annotation.py::precheck"    # M16 annotation of a map's structure
G_M7_READ = f"{APP}::job_preflight"
G_POCKET_READ = f"{APP}::pockets_preflight"
G_SESSION = f"{APP}::viewer_session_create"
G_SCENE = f"{APP}::viewer_scene_save"
G_FIGURE = f"{APP}::viewer_figure_save"
G_REPORT = f"{APP}::create_report"
G_INSPECT = f"{APP}::inspection"
G_PLAN = f"{APP}::analysis_plan_create"

M = "backend/mw/"
HASH = "[call-key hash file, unchanged] "

# --- the declaration table: (file, qualname) -> (category, guards, reason) -----------------------------------------
# A qualname matches itself, then its top-level definition, then ``register.<name>``, then the file wildcard ``*``.
DECLARED: dict[tuple[str, str], tuple[str, tuple[str, ...], str]] = {
    # ---- Run.call tools (POST /commands, the M13 driver, the inspect_complex pipeline): refused in _validated_bound
    (M + "tools/structural.py", "register.compute_interactions"): (F, (G_RUN,), "compute_interactions"),
    (M + "tools/sasa.py", "calculate"): (F, (G_RUN,), "compute_interface_sasa"),
    (M + "tools/comparison.py", "<module>"): (F, (G_RUN,), "SOURCE_TYPES of measure_distance / align_structures"),
    (M + "tools/comparison.py", "register.measure_distance"): (F, (G_RUN,), "measure_distance"),
    (M + "tools/comparison.py", "register.align_structures"): (F, (G_RUN,), "align_structures (either side)"),
    (M + "tools/comparison.py", "resolve"): (F, (G_RUN,), "AtomRef resolution of measure / align"),
    (M + "tools/numbering.py", "<module>"): (F, (G_RUN,), "ALLOWED_KINDS of map_residue_numbering"),
    (M + "tools/numbering.py", "_normalized"): (F, (G_RUN,), "map_residue_numbering admission"),
    (M + "tools/numbering.py", "precheck"): (F, (G_RUN,), "map_residue_numbering pre-check (runs after the guard)"),
    (M + "tools/reaction_knowledge.py", "_structure"): (F, (G_RUN,), "link_reaction_knowledge (M26) structure"),
    (M + "reaction_knowledge.py", "<module>"): (F, (G_RUN,), "M26 STRUCTURE_KINDS of link_reaction_knowledge"),
    (M + "tools/site_annotation.py", "register.annotate_reference_sites"): (
        F, (G_M16,), "M16 reads the map's structure; its pre-check refuses a repaired one"),
    # ---- generic job branch (POST /jobs): M7 minimization and PyRosetta protocols; the M7 preflight read
    (M + "jobs/queue.py", "JobQueue.submit"): (
        F, (G_JOB, G_POCKET, G_CHEM), ("POST /jobs: generic branch refuses; fpocket / ProLIF refuse in their "
                                      "admission; M21 / M23 take a set, the repair lane says already_repaired")),
    (M + "api/app.py", "job_preflight"): (F, (G_M7_READ,), "GET /jobs/preflight (M7 standalone minimization read)"),
    # ---- M12 pockets
    (M + "pocket_input.py", "<module>"): (F, (G_POCKET,), "SOURCE_KINDS of the pocket projection"),
    (M + "pocket_input.py", "_load_source"): (F, (G_POCKET,), "pocket source read: refuses here"),
    (M + "pocket_input.py", "project"): (F, (G_POCKET,), "projection for submission and re-projection"),
    (M + "pocket_input.py", "preflight"): (
        F, (G_POCKET_READ,), "projection summary: the route refuses first, so no M12 reject carries the code"),
    (M + "pocket_bundle.py", "<module>"): (F, (G_POCKET, G_POCKET_READ), "SOURCE_KINDS of pocket sources"),
    (M + "pocket_bundle.py", "_check_source"): (F, (G_POCKET, G_POCKET_READ), "source check before the projection"),
    (M + "pocket_bundle.py", "submission"): (F, (G_POCKET,), "fpocket_detect_v1 admission (projects the source)"),
    (M + "pocket_bundle.py", "_reproject"): (F, (G_POCKET,), "re-projection of an admitted job"),
    (M + "pocket_bundle.py", "preflight"): (F, (G_POCKET_READ,), "GET /pockets/preflight summary"),
    (M + "pocket_bundle.py", "publish"): (BU, (G_POCKET,), "publication of an admitted fpocket job"),
    (M + "pocket_reports.py", "render_pocket_report"): (BU, (G_POCKET,), "pocket report of a published set"),
    (M + "api/app.py", "pockets_preflight"): (F, (G_POCKET_READ,), "GET /pockets/preflight: the same 422 at the route"),
    # ---- M11 chemistry
    (M + "chemical_inputs.py", "_source_rows"): (F, (G_CHEM,), "attach_existing complex source: refuses here"),
    (M + "chemical_inputs.py", "preview"): (F, (G_CHEM,), "M11 preview (route, prolif_prepare_v1, M13 plan)"),
    (M + "chemical_bundle.py", "prepare_selected"): (F, (G_CHEM,), "prolif_prepare_v1 submission (strict preview)"),
    (M + "chemical_bundle.py", "validated_graph"): (BU, (G_CHEM,), "atom catalog of an admitted attach source"),
    (M + "chemical_bundle.py", "validated_source"): (U, (), "chemical_preparation_manifest@1 (another object)"),
    (M + "api/app.py", "chemical_preview"): (F, (G_CHEM,), "POST /chemical/preview"),
    # ---- viewer sessions, saved views, figures (intents and session state need a session)
    (M + "viewer_intents.py", "create_session"): (F, (G_SESSION,), "viewer session of a structure"),
    (M + "api/app.py", "viewer_session_create"): (F, (G_SESSION,), "POST /viewer/sessions"),
    (M + "api/app.py", "ViewerSessionRequest"): (F, (G_SESSION,), "session request structure_handle"),
    (M + "saved_scenes.py", "<module>"): (F, (G_SCENE,), "SOURCE_SCHEMAS of saved views"),
    (M + "saved_scenes.py", "_source"): (F, (G_SCENE,), "saved view source check (save; reopen of saved ones)"),
    (M + "saved_scenes.py", "save_scene"): (F, (G_SCENE,), "saved view writer"),
    (M + "saved_scenes.py", "SceneSave"): (F, (G_SCENE,), "saved view request structure_handle"),
    (M + "saved_scenes.py", "SceneArtifact"): (BU, (G_SCENE,), "stored view model: only views that passed save"),
    (M + "saved_scenes.py", "scene_detail"): (BU, (G_SCENE,), "reopen of a saved view"),
    (M + "saved_scenes.py", "FigureSave"): (F, (G_FIGURE,), "figure request structure_handle"),
    (M + "saved_scenes.py", "FigureArtifact"): (BU, (G_FIGURE, G_SCENE), "stored figure model of a saved view"),
    (M + "api/app.py", "viewer_scene_save"): (F, (G_SCENE,), "POST /viewer/scenes"),
    (M + "api/app.py", "viewer_figure_save"): (F, (G_FIGURE,), "POST /viewer/figures"),
    # ---- inspection report and the fixed inspect_complex pipeline (T1: outside the spec list)
    (M + "api/app.py", "create_report"): (F, (G_REPORT,), "POST /reports prepared_handle"),
    (M + "api/app.py", "ReportRequest"): (F, (G_REPORT,), "report request prepared_handle"),
    (M + "reports.py", "build_inspection_report"): (F, (G_REPORT,), "POST /reports builder"),
    (M + "reports.py", "_build_inspection_report"): (
        BU, (G_RUN, G_REPORT), "the interaction set's structure (compute_interactions refuses)"),
    (M + "reports.py", "_science_links"): (BU, (G_RUN,), "inspection report evidence of an interaction set"),
    (M + "reports.py", "validate_claim"): (BU, (G_RUN,), "inspection report claim check"),
    (M + "reports.py", "render_report"): (BU, (G_RUN,), "inspection report rendering"),
    (M + "api/app.py", "inspection"): (F, (G_INSPECT,), "POST /inspect_complex: refused before the pipeline records"),
    (M + "workflows.py", "InspectionRequest"): (F, (G_INSPECT,), "pipeline request input_handle and policies"),
    (M + "workflows.py", "inspect_complex"): (F, (G_INSPECT, G_RUN), "pipeline (its steps are Run.call)"),
    (M + "workflows.py", "_verified_content"): (BU, (G_INSPECT,), "replay check of a pipeline's recorded steps"),
    # ---- M13 analysis flows: refused at the plan route; the M13 modules are unchanged (spec 5.2)
    (M + "api/app.py", "analysis_plan_create"): (F, (G_PLAN,), "POST /analysis/plans walks the inputs"),
    (M + "analysis_plans.py", "*"): (BU, (G_PLAN,), "M13 plan compile: only reached through the plan route"),
    (M + "analysis_executions.py", "*"): (
        BU, (G_PLAN, G_RUN, G_JOB), "M13 driver: runs stored plans only; its calls and jobs pass the guards again"),
    # ---- results and reports whose producing tool or job refuses
    (M + "method_reports.py", "*"): (BU, (G_RUN,), "interface_sasa report: compute_interface_sasa refuses"),
    (M + "comparison_reports.py", "_catalog"): (BU, (G_RUN,), "distance / alignment report atom catalog"),
    (M + "numbering_reports.py", "validated_numbering_map"): (BU, (G_RUN,), "M15 report: the map tool refuses"),
    (M + "site_annotation_reports.py", "validated_annotation"): (BU, (G_M16, G_RUN), "M16 report of an annotation"),
    (M + "reaction_knowledge.py", "_validate"): (BU, (G_RUN,), "M26 result check: the link tool refuses"),
    (M + "kinase_precedents.py", "*"): (
        BU, (G_RUN,), "M27 reads only a numbering map, which map_residue_numbering refuses to make (T1 (b))"),
    (M + "openmm_bundle.py", "_selected_source"): (BU, (G_JOB,), "M7 result check: the M7 job refuses"),
    (M + "openmm_reports.py", "*"): (BU, (G_JOB,), "M7 report: the M7 job refuses"),
    (M + "jobs/queue.py", "JobQueue._publish_openmm"): (BU, (G_JOB,), "M7 result publication of an admitted job"),
    # ---- the modeling path (spec 5.1): M20 and what uses its candidate sets
    (M + "mutation_constants.py", "<module>"): (R, (), "M20 STRUCTURE_KIND"),
    (M + "tools/mutations.py", "_admit"): (R, (), "M20 admission (T7 hand-off checks the repair link)"),
    (M + "tools/mutations.py", "register.generate_mutation_candidates"): (R, (), "M20 tool (Run.call allow-list)"),
    (M + "mutation_handoff.py", "read_view"): (R, (), "M20 hand-off read of a repaired set (T7)"),
    (M + "mutation_candidates.py", "*"): (R, (), HASH + "M20 build and set check"),
    (M + "mutation_model_constants.py", "<module>"): (R, (), HASH + "M21 STRUCTURE_KIND"),
    (M + "mutation_model_math.py", "_validated"): (R, (), HASH + "M21 content structure kind"),
    (M + "mutation_model_inputs.py", "*"): (R, (), "M21 admission of a candidate set's structure"),
    (M + "mutation_model_bundle.py", "*"): (R, (), "M21 selection (M7 preflight) and model check"),
    (M + "sequence_ga_jobs.py", "projection"): (R, (), HASH + "M23 -> M7 preflight"),
    (M + "sequence_ga_bundle.py", "_check_model"): (R, (), HASH + "M23 model structure kind"),
    (M + "jobs/sequence_ga_worker.py", "*"): (R, (), HASH + "M23 worker input structure kind"),
    (M + "jev_constants.py", "<module>"): (R, (), "M24 STRUCTURE_KIND (variant projection of a set)"),
    (M + "tools/jev.py", "_structure"): (R, (), "M24 projection parses the set's structure"),
    (M + "jev_projection.py", "_validate_projection"): (R, (), "M24 projection check"),
    (M + "jev_loop_projection.py", "_validate_header"): (R, (), "M25 loop projection check"),
    (M + "jev_loops.py", "parse_created"): (R, (), "M25 pool structure kind"),
    (M + "jev_loop_store.py", "*"): (R, (), "M25 protein loop -> M21 selection"),
    (M + "tools/openmm_method.py", "preflight"): (
        R, (), HASH + "M7 preflight: the modeling path's entry check (M21 / M23 / M25, the repair check); its "
                      "standalone callers refuse (job_preflight, the generic job branch)"),
    # ---- reads (spec 5.2: listing and downloading are not refused)
    (M + "api/app.py", "residues"): (RO, (), "GET /structures/residues"),
    (M + "api/app.py", "coordinates"): (RO, (), "GET /structures/bytes (download)"),
    (M + "api/app.py", "atoms"): (RO, (), "GET /structures/atoms"),
    (M + "api/app.py", "reference_pdb_id_hint"): (RO, (), "GET /reference/pdb_id_hint (original source PDB ID)"),
    (M + "numbering_reads.py", "*"): (RO, (), "PDB ID hint read of the manifest's source"),
    (M + "api/app.py", "site_annotation_list"): (RO, (), "M16 list filtered by a structure handle"),
    (M + "api/app.py", "mutation_model_contacts"): (RO, (), "M21 read; 'structure' names a model side"),
    (M + "api/app.py", "structure_repair_preflight_read"): (
        RO, (), "M29 repair preflight read: a repaired structure gets its own already_repaired (spec 4.2)"),
    (M + "structure_repair_reads.py", "*"): (RO, (), "M29 repair record reads (spec 4.5)"),
    (M + "structure_origin.py", "*"): (RO, (), "M29 origin judge behind reject_if_repaired (spec 6.1)"),
    # ---- shared helpers used by receive and read paths (T1 judgement: no refusal here)
    (M + "tools/structural.py", "structure_residues"): (J, (), "residue catalog (reads, viewer, M20, M21)"),
    (M + "tools/structural.py", "structure_bytes"): (J, (), "structure bytes (download, pocket, comparison)"),
    (M + "tools/comparison.py", "_source"): (J, (), "atom catalog source (reads, measure / align, pocket)"),
    (M + "tools/comparison.py", "atom_rows"): (J, (), "atom catalog (GET /structures/atoms and consumers)"),
    (M + "tools/comparison.py", "AtomRefV1"): (J, (), "shared AtomRef model (structure_handle, altloc)"),
    (M + "core/contracts.py", "check_args"): (J, (), "generic kind check of Run.call and the job queue"),
    # ---- producers and unrelated matches
    (M + "tools/structural.py", "register.prepare_structure"): (U, (), "producer (takes a raw structure only)"),
    (M + "core/contracts.py", "<module>"): (U, (), "CONVERSIONS: prepare_structure fix hint for a kind mismatch"),
    (M + "runtime/orchestrator.py", "Run.satisfy_precondition"): (
        U, (), "prerequisite prepare_structure retry: makes a new (never repaired) prepared structure"),
    (M + "api/app.py", "_public_job"): (U, (), "job artifact labels (repair job outputs)"),
    (M + "api/app.py", "report_download"): (U, (), "report manifest (not a preparation manifest)"),
    (M + "jobs/queue.py", "JobQueue._state"): (U, (), "M7 attempt preparation handles (not a preparation manifest)"),
    (M + "reference_snapshots.py", "_validate_manifest"): (U, (), "M15 reference set manifest (another object)"),
    (M + "structure_repair_constants.py", "<module>"): (U, (), "M29 constants (kinds, schemas)"),
    (M + "structure_repair.py", "*"): (
        U, (), "M29 repair core: input of the repair lane, a repaired input is already_repaired (spec 4.2)"),
    (M + "structure_repair_bundle.py", "*"): (U, (), "M29 repair publication (producer of repaired structures)"),
    (M + "structure_repair_jobs.py", "*"): (
        U, (), "M29 repair admission (already_repaired) and its pre-publication M7 check (spec 3.4 4)"),
}

# --- tool contracts that accept a prepared structure or a numbering map: tool -> (lane, category, guards, reason) ----
TOOL_LANES: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "compute_interactions": ("run_call", F, (G_RUN,), "refused before its pre-check"),
    "compute_interface_sasa": ("run_call", F, (G_RUN,), "refused before its pre-check"),
    "measure_distance": ("run_call", F, (G_RUN,), "refused before its pre-check"),
    "align_structures": ("run_call", F, (G_RUN,), "either handle refused"),
    "compile_state": ("run_call", F, (G_RUN,), "any listed handle refused"),
    "map_residue_numbering": ("run_call", F, (G_RUN,), "refused before the reference set is pinned"),
    "link_reaction_knowledge": ("run_call", F, (G_RUN,), "refused before the reference set is pinned"),
    "annotate_reference_sites": ("run_call", F, (G_M16,), "a map of a repaired structure is refused"),
    "link_kinase_precedents": ("run_call", BU, (G_RUN,), "only a map, which the map tool refuses to make"),
    "generate_mutation_candidates": ("run_call", R, (), "the modeling path's entry (spec 5.1)"),
    "openmm_protein_minimize": ("job:openmm_protein_minimize", F, (G_JOB, G_M7_READ), "M7 standalone"),
    "relax_structure": ("job:relax", F, (G_JOB,), "PyRosetta (412 today; refused before)"),
    "score_interface": ("job:interface_analyzer", F, (G_JOB,), "PyRosetta (412 today; refused before)"),
    "detect_pockets": ("job:fpocket_detect_v1", F, (G_POCKET,), "M12 fpocket"),
    "measure": ("none", U, (), "no lane (no route, no protocol)"),
    "align": ("none", U, (), "no lane (no route, no protocol)"),
    "define_mutations": ("none", U, (), "no lane (no route, no protocol)"),
}


# ====================================================================================================================
# scanner
# ====================================================================================================================

@dataclass(frozen=True)
class Hit:
    rel: str
    line: int
    qual: str
    pattern: str


def load_sources() -> dict[str, str]:
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(MW_DIR.rglob("*.py")) if "__pycache__" not in path.parts}


def load_tools() -> list[dict[str, Any]]:
    return yaml.safe_load(TOOLS_YAML.read_text(encoding="utf-8"))["tools"]


@lru_cache(maxsize=1024)
def _parsed(rel: str, text: str) -> ast.Module:
    return ast.parse(text, rel)


def parse(sources: dict[str, str]) -> dict[str, ast.Module]:
    return {rel: _parsed(rel, text) for rel, text in sources.items()}


def module_key(rel: str) -> str:
    """backend/mw/tools/jev.py -> tools/jev; backend/mw/api/app.py -> api/app"""
    return rel[len("backend/mw/"):-3]


@lru_cache(maxsize=2048)
def _imports(rel: str, text: str, modules: frozenset) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """(module aliases: local name -> module key, imported names: local name -> (module key, name))."""
    tree = _parsed(rel, text)
    package = module_key(rel).split("/")[:-1]
    mods: dict[str, str] = {}
    names: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level == 0:
            continue
        base = package[:len(package) - (node.level - 1)] if node.level > 1 else list(package)
        target = "/".join(base + (node.module.split(".") if node.module else []))
        for alias in node.names:
            local = alias.asname or alias.name
            candidate = (target + "/" if target else "") + alias.name
            if candidate in modules:
                mods[local] = candidate
            else:
                names[local] = (target, alias.name)
    return mods, names


def _relevant(trees: dict[str, ast.Module], imports: dict[str, tuple]) -> set[tuple[str, str]]:
    """(module key, module-level name) whose value holds a target string, directly or through such a name."""
    relevant: set[tuple[str, str]] = set()
    changed = True
    while changed:
        changed = False
        for rel, tree in trees.items():
            key = module_key(rel)
            mods, names = imports[key]
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                hit = any(isinstance(sub, ast.Constant) and sub.value in TARGET_STRINGS for sub in ast.walk(node.value))
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Name) and ((key, sub.id) in relevant or names.get(sub.id) in relevant):
                        hit = True
                    if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and
                            (mods.get(sub.value.id), sub.attr) in relevant):
                        hit = True
                for target in targets:
                    if hit and isinstance(target, ast.Name) and (key, target.id) not in relevant:
                        relevant.add((key, target.id))
                        changed = True
    return relevant


class _Scanner(ast.NodeVisitor):
    def __init__(self, rel: str, relevant: set, mods: dict, names: dict, local_defs: set[str]) -> None:
        self.rel, self.key = rel, module_key(rel)
        self.relevant, self.mods, self.names, self.local_defs = relevant, mods, names, local_defs
        self.stack: list[str] = []
        self.hits: list[Hit] = []

    def _qual(self) -> str:
        return ".".join(self.stack) if self.stack else "<module>"

    def _hit(self, node: ast.AST, pattern: str) -> None:
        self.hits.append(Hit(self.rel, node.lineno, self._qual(), pattern))

    def _scope(self, node: ast.AST, name: str) -> None:
        self.stack.append(name)
        for dec in getattr(node, "decorator_list", []):
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in ROUTE_METHODS
                    and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                    any(arg.arg == "structure" for arg in node.args.args + node.args.kwonlyargs)):
                self._hit(node, "route-param:structure")
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope(node, node.name)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.stack and isinstance(node.target, ast.Name):
            if node.target.id in MANIFEST_SCOPES:
                self._hit(node, f"model-field:{node.target.id}")
            elif node.target.id in HANDLE_FIELDS:
                self._hit(node, f"handle-field:{node.target.id}")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            if node.value in TARGET_STRINGS or node.value in GAP_STRINGS:
                self._hit(node, f"str:{node.value}")
            elif "(?:structure|prepared_structure)" in node.value:
                self._hit(node, "str:handle-regex(prepared_structure)")

    def _resolve(self, ident: str) -> tuple[str, str] | None:
        if (self.key, ident) in self.relevant:
            return (self.key, ident)
        if ident in self.names and self.names[ident] in self.relevant:
            return self.names[ident]
        return None

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and self.stack and self._resolve(node.id):
            self._hit(node, "alias:" + ".".join(self._resolve(node.id)))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name) and
                (self.mods.get(node.value.id), node.attr) in self.relevant):
            self._hit(node, f"alias:{self.mods[node.value.id]}.{node.attr}")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        key = node.slice.value if isinstance(node.slice, ast.Constant) else None
        if key == "manifest":
            self._hit(node, 'sub:["manifest"]')
        if isinstance(node.value, ast.Name) and node.value.id in MANIFEST_VARS and key in MANIFEST_FIELDS:
            self._hit(node, f'manifest-field:{node.value.id}["{key}"]')
        self.generic_visit(node)

    def _callee(self, func: ast.AST) -> tuple[str, str] | None:
        if isinstance(func, ast.Name):
            return (self.key, func.id) if func.id in self.local_defs else self.names.get(func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in self.mods:
            return (self.mods[func.value.id], func.attr)
        return None

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        callee = self._callee(func)
        if callee in CALL_TARGETS:
            self._hit(node, f"call:{callee[0]}.{callee[1]}(")
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name == "get" and isinstance(func, ast.Attribute) and node.args and isinstance(node.args[0], ast.Constant):
            key = node.args[0].value
            if key == "manifest":
                self._hit(node, '.get("manifest")')
            elif isinstance(func.value, ast.Name) and func.value.id in MANIFEST_VARS and key in MANIFEST_FIELDS:
                self._hit(node, f'manifest-field:{func.value.id}.get("{key}")')
        if name == "set" and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id in MANIFEST_VARS:
            self._hit(node, f"strict-keys:set({node.args[0].id})")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        parts = [node.left, *node.comparators]

        def is_kind(item: ast.AST) -> bool:
            return (isinstance(item, ast.Subscript) and isinstance(item.slice, ast.Constant) and
                    item.slice.value in {"kind", "schema", "structure_kind", "source_kind"})
        targets = any(isinstance(sub, ast.Constant) and sub.value in TARGET_STRINGS
                      for part in parts for sub in ast.walk(part))
        if targets and any(is_kind(part) for part in parts):
            self._hit(node, "kind-compare")
        self.generic_visit(node)


@lru_cache(maxsize=2048)
def _file_hits(rel: str, text: str, relevant: frozenset, modules: frozenset) -> tuple[Hit, ...]:
    tree = _parsed(rel, text)
    mods, names = _imports(rel, text, modules)
    local_defs = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    scanner = _Scanner(rel, set(relevant), mods, names, local_defs)
    scanner.visit(tree)
    return tuple(scanner.hits)


def scan(sources: dict[str, str]) -> list[Hit]:
    trees = parse(sources)
    modules = frozenset(module_key(rel) for rel in trees)
    imports = {module_key(rel): _imports(rel, text, modules) for rel, text in sources.items()}
    relevant = frozenset(_relevant(trees, imports))
    return [hit for rel, text in sources.items() for hit in _file_hits(rel, text, relevant, modules)]


@lru_cache(maxsize=2048)
def definitions(rel: str, text: str) -> dict[str, ast.AST]:
    """qualname -> function or class node (nested names joined by dots, as the scanner's)."""
    tree = _parsed(rel, text)
    found: dict[str, ast.AST] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                found[name] = child
                walk(child, name + ".")
            else:
                walk(child, prefix)
    walk(tree, "")
    return found


def calls(node: ast.AST, names: Iterable[str]) -> bool:
    """Does ``node`` (nested definitions included) call one of ``names`` (a plain or attribute call)?"""
    wanted = set(names)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if name in wanted:
                return True
    return False


def classify(rel: str, qual: str, declared: dict) -> tuple[str, tuple[str, ...], str] | None:
    """Exact (file, qualname), then the top-level definition, then ``register.<name>``, then the file wildcard."""
    top = qual.split(".")[0]
    for key in ((rel, qual), (rel, top), (rel, "register." + qual.split(".")[-1]), (rel, "*")):
        if key in declared:
            return declared[key]
    return None


def _module_constant(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node.value
    return None


def _strings(node: ast.AST | None) -> set[str]:
    return {sub.value for sub in ast.walk(node) if isinstance(sub, ast.Constant) and isinstance(sub.value, str)} \
        if node is not None else set()


def _lanes(trees: dict[str, ast.Module], tools: list[dict[str, Any]]) -> dict[str, str]:
    """Tool -> lane ("run_call" | "job:<protocol>" | "none") for every tool contract that accepts a prepared structure
    or a numbering map."""
    supported = _strings(_module_constant(trees[APP], "SUPPORTED_TOOLS"))
    jobs: dict[str, str] = {}
    for name in ("PROTOCOLS", "JOB_PROTOCOLS"):
        value = _module_constant(trees[ENERGETIC], name)
        for sub in ast.walk(value) if value is not None else ():
            if isinstance(sub, ast.Dict):
                for key, item in zip(sub.keys, sub.values, strict=True):
                    if isinstance(key, ast.Constant) and isinstance(item, ast.Tuple):
                        jobs[item.elts[0].value] = key.value
    lanes: dict[str, str] = {}
    for tool in tools:
        kinds = {kind for accepted in (tool.get("accepts") or {}).values() for kind in accepted}
        if kinds & {"prepared_structure", "residue_numbering_map"}:
            name = tool["name"]
            lanes[name] = ("run_call" if name in supported else f"job:{jobs[name]}" if name in jobs else "none")
    return lanes


def problems(sources: dict[str, str], declared: dict, tool_lanes: dict, tools: list[dict[str, Any]]) -> list[str]:
    trees = parse(sources)
    defs = {rel: definitions(rel, text) for rel, text in sources.items()}
    found: list[str] = []
    used: set[tuple[str, str]] = set()

    def node(ref: tuple[str, str]) -> ast.AST | None:
        rel, qual = ref
        return defs.get(rel, {}).get(qual) if qual != "<module>" else trees.get(rel)

    def refuses(rel: str, qual: str) -> bool:
        target = node((rel, qual.split(".")[0])) if qual != "<module>" else None
        return target is not None and calls(target, REFUSAL_CALLS)

    def guard_ok(guard: str) -> bool:
        rel, _sep, qual = guard.partition("::")
        target = node((rel, qual))
        return target is not None and calls(target, REFUSAL_CALLS)

    for hit in scan(sources):
        entry = classify(hit.rel, hit.qual, declared)
        if entry is None:
            if not refuses(hit.rel, hit.qual):
                found.append(f"undeclared consumer {hit.rel}:{hit.line} {hit.qual} ({hit.pattern})")
            continue
        top = hit.qual.split(".")[0]
        for key in ((hit.rel, hit.qual), (hit.rel, top), (hit.rel, "register." + hit.qual.split(".")[-1]),
                    (hit.rel, "*")):
            if key in declared:
                used.add(key)
                break
    for key, (category, guards, reason) in sorted(declared.items()):
        rel, qual = key
        where = f"{rel}::{qual}"
        if key not in used:
            found.append(f"stale declaration {where}")
        if category not in CATEGORIES or not reason.strip():
            found.append(f"bad declaration {where}")
        if category in (F, BU) and not guards:
            found.append(f"{category} without a guard {where}")
        found.extend(f"guard without a refusal call {guard} (for {where})" for guard in guards if not guard_ok(guard))
        scope = trees.get(rel) if qual == "*" else None if qual == "<module>" else node(key)
        if category in (R, RO, J) and scope is not None and calls(scope, REFUSAL_CALLS):
            found.append(f"{category} point refuses {where}")
    helper = node((APP, API_HELPER))
    if helper is None or not calls(helper, {REFUSAL}):
        found.append(f"{APP}::{API_HELPER} does not call {REFUSAL}")
    allow = _strings(_module_constant(trees[ORCHESTRATOR], ALLOW_LIST))
    if allow != set(MODELING_TOOLS):
        found.append(f"{ALLOW_LIST} is {sorted(allow)}, not {sorted(MODELING_TOOLS)}")
    for tool, lane in sorted(_lanes(trees, tools).items()):
        entry = tool_lanes.get(tool)
        if entry is None:
            found.append(f"undeclared tool contract {tool} ({lane})")
            continue
        declared_lane, category, guards, _reason = entry
        if declared_lane != lane:
            found.append(f"tool {tool}: declared lane {declared_lane}, found {lane}")
        if lane == "run_call" and (category == R) != (tool in allow):
            found.append(f"tool {tool}: {category} but the Run.call allow-list says otherwise")
        found.extend(f"guard without a refusal call {guard} (for tool {tool})" for guard in guards
                     if not guard_ok(guard))
        if category in (F, BU) and not guards:
            found.append(f"tool {tool}: {category} without a guard")
    found.extend(f"stale tool declaration {tool}" for tool in sorted(set(tool_lanes) - set(_lanes(trees, tools))))
    return found


# ====================================================================================================================
# tests
# ====================================================================================================================

def test_every_consumer_is_declared_and_every_refusal_it_relies_on_exists():
    assert problems(load_sources(), DECLARED, TOOL_LANES, load_tools()) == []


# --- self-tests: the inventory catches what it must (each builds a modified copy of the sources; nothing is written) -

@lru_cache(maxsize=1)
def _real() -> tuple[dict[str, str], tuple[dict[str, Any], ...]]:
    return load_sources(), tuple(load_tools())


def _check(sources: dict[str, str] | None = None, declared: dict | None = None, lanes: dict | None = None,
           tools: list[dict[str, Any]] | None = None) -> list[str]:
    real_sources, real_tools = _real()
    return problems(real_sources if sources is None else sources, DECLARED if declared is None else declared,
                    TOOL_LANES if lanes is None else lanes, list(real_tools) if tools is None else tools)


def _edit(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new)


def _strip_refusals(text: str, rel: str, qual: str) -> str:
    """The source with every refusal call inside one definition renamed (an omitted call)."""
    node = definitions(rel, text)[qual]
    lines = text.splitlines(keepends=True)
    for index in range(node.lineno - 1, node.end_lineno):
        lines[index] = lines[index].replace(f"{REFUSAL}(", "no_refusal(").replace(f"{API_HELPER}(", "no_refusal(")
    return "".join(lines)


NEW = "backend/mw/m29_t6_probe_{}.py"
PROBES = {
    "kind": ("def consumer(store, handle):\n"
             "    meta = store.meta(handle)\n"
             "    if meta[\"kind\"] == \"prepared_structure\":\n"
             "        return store.load(handle)\n"),
    "alias": ("from .structure_repair_constants import STRUCTURE_KIND\n\n\n"
              "def consumer(store, handle):\n"
              "    return store.meta(handle)[\"kind\"] == STRUCTURE_KIND\n"),
    "call": ("from .tools.structural import structure_residues\n\n\n"
             "def consumer(store, handle):\n"
             "    return structure_residues(store, handle)\n"),
    "manifest": ("def consumer(store, handle):\n"
                 "    return store.load(store.load(handle)[\"manifest\"])\n"),
}


def test_a_new_consumer_without_a_declaration_or_a_refusal_call_is_caught():
    sources, _tools = _real()
    probes = {NEW.format(name): text for name, text in PROBES.items()}
    found = _check({**sources, **probes})
    assert found and all(item.startswith("undeclared consumer backend/mw/m29_t6_probe_") for item in found), found
    assert {item.split()[2].split(":")[0] for item in found} == set(probes)
    # the same consumers calling the refusal pass without a declaration
    guarded = {rel: "from .structure_origin import reject_if_repaired\n" + _edit(
        text, "def consumer(store, handle):\n", "def consumer(store, handle):\n    reject_if_repaired(store, handle)\n")
        for rel, text in probes.items()}
    assert _check({**sources, **guarded}) == []
    # and with a declaration
    declared = {**DECLARED, **{(rel, "consumer"): (U, (), "probe") for rel in probes}}
    assert _check({**sources, **probes}, declared=declared) == []


def test_an_omitted_refusal_call_in_any_guard_is_caught():
    sources, _tools = _real()
    guards = sorted({guard for _c, gs, _r in DECLARED.values() for guard in gs} |
                    {guard for _l, _c, gs, _r in TOOL_LANES.values() for guard in gs})
    assert len(guards) == 13
    edited = dict(sources)
    for guard in guards:
        rel, _sep, qual = guard.partition("::")
        edited[rel] = _strip_refusals(edited[rel], rel, qual)
    found = _check(edited)
    for guard in guards:
        assert any(item.startswith(f"guard without a refusal call {guard} ") for item in found), guard
    # the API helper that the route guards call must itself refuse
    helper = _edit(sources[APP], f"                {REFUSAL}(run.store, value)\n", "                pass\n")
    assert _check({**sources, APP: helper}) == [f"{APP}::{API_HELPER} does not call {REFUSAL}"]


def test_a_widened_allow_list_a_moved_lane_and_an_undeclared_tool_contract_are_caught():
    sources, tools = _real()
    widened = _edit(sources[ORCHESTRATOR], 'frozenset({"generate_mutation_candidates"})',
                    'frozenset({"generate_mutation_candidates", "compute_interactions"})')
    moved = _edit(sources[APP], '"link_reaction_knowledge", "link_kinase_precedents"}',
                  '"link_reaction_knowledge", "link_kinase_precedents", "measure"}')
    new_tool = {"name": "m29_t6_probe_tool", "level": "L2", "emits": "thing",
                "accepts": {"structure": ["prepared_structure"]}}
    found = _check({**sources, ORCHESTRATOR: widened, APP: moved}, tools=[*tools, new_tool])
    assert sorted(found) == sorted([
        (f"{ALLOW_LIST} is ['compute_interactions', 'generate_mutation_candidates'], "
         "not ['generate_mutation_candidates']"),
        "tool compute_interactions: refuse but the Run.call allow-list says otherwise",
        "tool measure: declared lane none, found run_call",
        "undeclared tool contract m29_t6_probe_tool (none)"])
    lanes = {**TOOL_LANES, "m29_t6_probe_gone": ("none", U, (), "probe")}
    assert _check(lanes=lanes) == ["stale tool declaration m29_t6_probe_gone"]


def test_a_refusing_receive_point_a_missing_and_a_stale_declaration_are_caught():
    sources, _tools = _real()
    rel = M + "tools/mutations.py"
    node = definitions(rel, sources[rel])["_admit"]
    lines = sources[rel].splitlines(keepends=True)
    first = node.body[0]
    indent = " " * first.col_offset
    lines.insert(first.lineno - 1, f"{indent}{REFUSAL}(store, structure)\n")
    declared = {key: value for key, value in DECLARED.items() if key != (M + "tools/sasa.py", "calculate")}
    declared[(M + "m29_t6_probe_gone.py", "gone")] = (U, (), "probe")
    found = _check({**sources, rel: "".join(lines)}, declared=declared)
    assert f"receive point refuses {rel}::_admit" in found
    assert any(item.startswith(f"undeclared consumer {M}tools/sasa.py:") and " calculate " in item for item in found)
    assert f"stale declaration {M}m29_t6_probe_gone.py::gone" in found
    assert len(found) == 3, found
