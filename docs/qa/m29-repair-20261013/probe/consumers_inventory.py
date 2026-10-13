# PROTOTYPE (M29 T1 (b) measurement only; never product code, never imported by mw).
"""Inventory of every consumer of a ``prepared_structure`` handle / ``prepared_structure@1`` /
``preparation_manifest@1`` in the backend, the tool contracts, the pipelines and (briefly) the frontend.

Standard library only (ast, re, json, pathlib). Read-only: it parses source files and prints a report with
repository-relative paths. Usage::

    .venv/bin/python docs/qa/m29-repair-20261013/probe/consumers_inventory.py [REPO_ROOT] [--out FILE]

Every hit is one (file, line, enclosing function, pattern). The manual classification (CLASSIFICATION below) was
written by the T1 (b) reader after reading each hit's code; a hit whose enclosing function has no entry is printed as
UNCLASSIFIED so that a new consumer cannot hide. Categories: receive (modeling path, spec 5.1), refuse (spec 5.2),
read_only, blocked_upstream, judgement (needs a decision), unrelated (grep false positive).
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TARGET_STRINGS = {"prepared_structure", "prepared_structure@1", "preparation_manifest", "preparation_manifest@1",
                  "prepared_coordinates", "prepared_coordinates@1"}
MANIFEST_FIELDS = {"waters", "missing_residues", "input", "source_handle", "hydrogens", "altloc", "model_index",
                   "model_number", "symmetry_mates", "removed", "altloc_choices", "protonation", "repair"}
MANIFEST_VARS = {"manifest", "prep", "source_manifest", "prep_data"}
CALL_NAMES = {"_parse", "structure_bytes", "structure_residues", "atom_rows", "preflight", "openmm_preflight",
              "_load_source", "_source_rows", "create_session", "pdb_id_hint", "input_preflight",
              "pocket_preflight", "preview_chemical", "build_inspection_report", "inspect_complex", "create_plan"}
PROTOTYPE_HEADER = "# PROTOTYPE (M29 T1 (b) measurement only; never product code, never imported by mw)."

R, F, RO, BU, J, U, RV = "receive", "refuse", "read_only", "blocked_upstream", "judgement", "unrelated", "receive?"

# (relative file, enclosing qualname) -> (category, note). Written after reading each hit (T1 (b)).
CLASSIFICATION: dict[tuple[str, str], tuple[str, str]] = {
    # ---- producers / generic plumbing
    ("backend/mw/tools/structural.py", "register.prepare_structure"): (U, "producer of prepared_structure@1 (manifest writer)"),
    ("backend/mw/tools/structural.py", "_parse"): (J, "shared parser; prepared branch = obj['coordinates'] (no manifest read); "
                                                   "no refusal here (used by receive + read paths)"),
    ("backend/mw/tools/structural.py", "structure_residues"): (J, "shared helper (/structures/residues read, viewer, M20, M21); no refusal here"),
    ("backend/mw/tools/structural.py", "structure_bytes"): (J, "shared helper (/structures/bytes read, pocket, comparison); no refusal here"),
    ("backend/mw/tools/structural.py", "register.compute_interactions"): (F, "compute_interactions impl; earliest: Run._validated_bound"),
    ("backend/mw/core/contracts.py", "<module>"): (U, "CONVERSIONS: prepare_structure fix hint for kind mismatch"),
    ("backend/mw/core/contracts.py", "check_args"): (J, "generic accepts-kind check (kind only, no store); used by Run and queue else-branch"),
    ("backend/mw/runtime/orchestrator.py", "Run.satisfy_precondition"): (U, "prerequisite prepare_structure retry (creates a NEW prepared structure; never repaired)"),
    ("backend/mw/runtime/orchestrator.py", "Run._validated_bound"): (F, "central Run.call entry for every SUPPORTED tool (precheck -> check_args)"),
    # ---- M7
    ("backend/mw/tools/openmm_method.py", "preflight"): (R, "[HASH] M7 preflight; reads manifest input/waters/hydrogens/source_handle only; "
                                                         "used by M21/M23 (receive) and M7 job + /jobs/preflight (refuse at caller)"),
    ("backend/mw/openmm_bundle.py", "_selected_source"): (BU, "M7 result validation; only reachable after an M7 job on the structure"),
    ("backend/mw/openmm_reports.py", "validated_openmm"): (BU, "M7 report validation; blocked by M7 submission refusal"),
    ("backend/mw/openmm_reports.py", "build_openmm_report"): (BU, "M7 report"),
    ("backend/mw/openmm_reports.py", "saved_openmm_report"): (BU, "M7 report reopen"),
    ("backend/mw/openmm_reports.py", "_expected"): (BU, "M7 report"),
    ("backend/mw/api/app.py", "job_preflight"): (F, "GET /runs/{rid}/jobs/preflight (M7 preflight read, spec 5.2 lists it)"),
    ("backend/mw/jobs/queue.py", "JobQueue.submit"): (F, "POST /jobs dispatch; openmm_protein_minimize branch (else-branch check_args then preflight)"),
    # ---- M11
    ("backend/mw/chemical_inputs.py", "_source_rows"): (F, "M11 attach_existing complex source; shared by /chemical/preview, prolif_prepare_v1 submit, M13 plan"),
    # ---- M12
    ("backend/mw/pocket_input.py", "<module>"): (F, "SOURCE_KINDS of M12 pocket projection"),
    ("backend/mw/pocket_input.py", "_load_source"): (F, "M12 pocket projection source (preflight read + fpocket submit + reproject)"),
    ("backend/mw/pocket_input.py", "project"): (F, "M12 projection"),
    ("backend/mw/pocket_input.py", "preflight"): (F, "M12 /pockets/preflight read (judgement: spec 5.2 says 'M12 pocket')"),
    ("backend/mw/pocket_bundle.py", "<module>"): (BU, "pocket_set source kinds for result validation"),
    ("backend/mw/pocket_bundle.py", "submission"): (F, "fpocket_detect_v1 submission"),
    ("backend/mw/pocket_bundle.py", "preflight"): (F, "M12 preflight"),
    ("backend/mw/pocket_bundle.py", "_reproject"): (BU, "re-projection of an admitted job"),
    ("backend/mw/pocket_bundle.py", "complete_job"): (BU, "publication of an admitted job"),
    ("backend/mw/pocket_bundle.py", "_publish"): (BU, "publication"),
    # ---- comparison / sasa
    ("backend/mw/tools/comparison.py", "<module>"): (F, "SOURCE_TYPES of measure_distance/align_structures"),
    ("backend/mw/tools/comparison.py", "_source"): (J, "shared by atom_rows (read route /structures/atoms, pocket) and tools"),
    ("backend/mw/tools/comparison.py", "atom_rows"): (J, "shared catalog: /structures/atoms read + measure/align + pocket"),
    ("backend/mw/tools/comparison.py", "register.measure_distance"): (F, "measure_distance impl"),
    ("backend/mw/tools/comparison.py", "register.align_structures"): (F, "align_structures impl"),
    ("backend/mw/tools/sasa.py", "calculate"): (F, "compute_interface_sasa impl"),
    ("backend/mw/method_reports.py", "_source_links"): (BU, "interface_sasa report; blocked by compute_interface_sasa refusal"),
    ("backend/mw/method_reports.py", "validated_sasa"): (BU, "interface_sasa report"),
    ("backend/mw/method_reports.py", "build_method_report"): (BU, "interface_sasa report"),
    ("backend/mw/method_reports.py", "_build_method_report"): (BU, "interface_sasa report"),
    ("backend/mw/method_reports.py", "render_method_report"): (BU, "interface_sasa report"),
    ("backend/mw/comparison_reports.py", "validated_comparison_result"): (BU, "atom_distance/rigid_alignment report"),
    # ---- inspection report / inspect_complex pipeline
    ("backend/mw/reports.py", "_science_links"): (BU, "/reports inspection report; needs an interaction_set (compute_interactions refused)"),
    ("backend/mw/reports.py", "validate_claim"): (BU, "/reports claim validation"),
    ("backend/mw/reports.py", "_build_inspection_report"): (F, "POST /reports builder (spec 5.2 lists /reports); also blocked upstream"),
    ("backend/mw/reports.py", "build_inspection_report"): (F, "POST /reports"),
    ("backend/mw/reports.py", "render_report"): (BU, "inspection report render"),
    ("backend/mw/workflows.py", "_verified_content"): (BU, "inspect_complex replay verification"),
    ("backend/mw/workflows.py", "inspect_complex"): (F, "POST /runs/{rid}/inspect_complex fixed pipeline (NOT M13, NOT in spec 5.2 list); "
                                                     "input_handle may be a prepared_structure"),
    ("backend/mw/api/app.py", "inspection"): (F, "POST /runs/{rid}/inspect_complex route (new refusal target)"),
    # ---- M13
    ("backend/mw/analysis_plans.py", "<module>"): (BU, "M13 STRUCTURE_SCHEMAS (plan route refuses)"),
    ("backend/mw/analysis_plans.py", "_inspect_ligand"): (BU, "M13 plan compile"),
    ("backend/mw/analysis_plans.py", "_measure_atoms"): (BU, "M13 plan compile"),
    ("backend/mw/analysis_plans.py", "_compare"): (BU, "M13 plan compile"),
    ("backend/mw/analysis_plans.py", "_find_cavities"): (BU, "M13 plan compile"),
    ("backend/mw/analysis_plans.py", "_minimize"): (BU, "M13 plan compile"),
    ("backend/mw/analysis_executions.py", "_identity_check"): (BU, "M13 execution (reads chemical_preparation_manifest, not preparation_manifest@1)"),
    ("backend/mw/api/app.py", "analysis_plan_create"): (F, "POST /runs/{rid}/analysis/plans (M13 refusal at route, spec 5.2)"),
    # ---- viewer
    ("backend/mw/viewer_intents.py", "create_session"): (F, "POST /viewer/sessions (intents/scene/figure bind to the session)"),
    ("backend/mw/saved_scenes.py", "<module>"): (F, "SOURCE_SCHEMAS of saved scenes"),
    ("backend/mw/saved_scenes.py", "SceneArtifact"): (F, "viewer_scene@1 model"),
    ("backend/mw/saved_scenes.py", "_source"): (F, "POST /viewer/scenes source check"),
    # ---- M15 / M16 / M26 / M27
    ("backend/mw/tools/numbering.py", "<module>"): (F, "ALLOWED_KINDS map_residue_numbering"),
    ("backend/mw/tools/numbering.py", "precheck"): (F, "map_residue_numbering precheck (parses the structure)"),
    ("backend/mw/numbering_reads.py", "<module>"): (RO, "HINT_KINDS of /reference/pdb_id_hint"),
    ("backend/mw/numbering_reads.py", "pdb_id_hint"): (RO, "GET /reference/pdb_id_hint reads manifest source_handle (original source bytes)"),
    ("backend/mw/numbering_reports.py", "validated_numbering_map"): (BU, "M15 report; map cannot exist on a repaired structure"),
    ("backend/mw/tools/site_annotation.py", "register.annotate_reference_sites"): (F, "annotate_reference_sites (via numbering_map structure; upstream blocked by M15)"),
    ("backend/mw/site_annotation_reports.py", "validated_annotation"): (BU, "M16 report"),
    ("backend/mw/reaction_knowledge.py", "<module>"): (F, "M26 STRUCTURE_KINDS"),
    ("backend/mw/reaction_knowledge.py", "validated_result"): (BU, "M26 result validation"),
    ("backend/mw/tools/reaction_knowledge.py", "_structure"): (F, "link_reaction_knowledge precheck step 2"),
    ("backend/mw/kinase_precedents.py", "<module>"): (BU, "M27 STRUCTURE_KINDS (input is a numbering map)"),
    ("backend/mw/kinase_precedents.py", "validated_result"): (BU, "M27 result validation"),
    # ---- M20 / M21 / M23 / M24 / M25 (receive)
    ("backend/mw/mutation_constants.py", "<module>"): (R, "M20 STRUCTURE_KIND"),
    ("backend/mw/tools/mutations.py", "<module>"): (R, "M20 STRUCTURE_TYPE"),
    ("backend/mw/tools/mutations.py", "_admit"): (R, "M20 admission (spec 5.3 change point)"),
    ("backend/mw/tools/mutations.py", "register.generate_mutation_candidates"): (R, "M20 impl"),
    ("backend/mw/mutation_candidates.py", "<module>"): (R, "[HASH] M20 STRUCTURE_KIND import"),
    ("backend/mw/mutation_candidates.py", "build_candidate_set"): (R, "[HASH] M20 build"),
    ("backend/mw/mutation_candidates.py", "validated_set"): (R, "[HASH] M20 set validation (structure_kind == prepared_structure)"),
    ("backend/mw/mutation_model_constants.py", "<module>"): (R, "[HASH] M21 STRUCTURE_KIND"),
    ("backend/mw/mutation_model_inputs.py", "<module>"): (R, "M21 PREPARED_TYPE"),
    ("backend/mw/mutation_model_inputs.py", "check_structure"): (R, "M21 admission check 6"),
    ("backend/mw/mutation_model_inputs.py", "check_residue"): (R, "M21 admission check 7"),
    ("backend/mw/mutation_model_bundle.py", "_residues"): (R, "M21 structure_residues"),
    ("backend/mw/mutation_model_bundle.py", "selection"): (R, "M21 -> M7 preflight"),
    ("backend/mw/mutation_model_bundle.py", "validated_model"): (R, "M21 model validation"),
    ("backend/mw/mutation_model_math.py", "validated_model_content"): (R, "[HASH] M21 content check structure_kind"),
    ("backend/mw/sequence_ga_jobs.py", "candidate_set"): (R, "[HASH] M23 set + structure check"),
    ("backend/mw/sequence_ga_jobs.py", "_selection_projection"): (R, "[HASH] M23 -> M7 preflight"),
    ("backend/mw/jobs/sequence_ga_worker.py", "<module>"): (R, "[HASH] M23 worker STRUCTURE_KIND"),
    ("backend/mw/jev_constants.py", "<module>"): (R, "M24 STRUCTURE_KIND"),
    ("backend/mw/tools/jev.py", "_structure"): (R, "M24 projection parses the set's structure"),
    ("backend/mw/jev_projection.py", "validated_projection"): (R, "M24 projection validation (handle regex by kind)"),
    ("backend/mw/jev_loop_projection.py", "validated_loop_projection"): (R, "M25 projection validation"),
    ("backend/mw/jev_loops.py", "_pool"): (R, "M25 pool structure handle kind"),
    ("backend/mw/sequence_ga_inputs.py", "<module>"): (U, "[HASH] module-hash file list"),
    # ---- reads
    ("backend/mw/api/app.py", "residues"): (RO, "GET /structures/residues"),
    ("backend/mw/api/app.py", "coordinates"): (RO, "GET /structures/bytes (download; also the viewer's byte source)"),
    ("backend/mw/api/app.py", "atoms"): (RO, "GET /structures/atoms (atom catalog read)"),
    ("backend/mw/api/app.py", "reference_pdb_id_hint"): (RO, "GET /reference/pdb_id_hint"),
    ("backend/mw/api/app.py", "pockets_preflight"): (F, "GET /pockets/preflight (M12 read; judgement)"),
    ("backend/mw/api/app.py", "chemical_preview"): (F, "POST /chemical/preview (M11)"),
    ("backend/mw/api/app.py", "viewer_session_create"): (F, "POST /viewer/sessions"),
    ("backend/mw/api/app.py", "viewer_scene_save"): (F, "POST /viewer/scenes"),
    ("backend/mw/api/app.py", "create_report"): (F, "POST /reports"),
    ("backend/mw/api/app.py", "submit_job"): (F, "POST /jobs (M7/M11/M12 refuse, M21/M23 receive)"),
    ("backend/mw/api/app.py", "command"): (F, "POST /commands -> Run.call (generate_mutation_candidates receives)"),
    # ---- false positives
    ("backend/mw/chemical_bundle.py", "*"): (U, "chemical_preparation_manifest@1 (a different object)"),
    ("backend/mw/jobs/queue.py", "JobQueue._ingest_openmm"): (U, "openmm_preparation_manifest"),
    ("backend/mw/jobs/queue.py", "JobQueue._publish_openmm"): (U, "openmm_preparation_manifest"),
    ("backend/mw/jobs/queue.py", "JobQueue._verified_attempt"): (U, "openmm_preparation_manifest / chemical"),
    ("backend/mw/jobs/queue.py", "<module>"): (U, "chemical_preparation_manifest"),
    ("backend/mw/api/app.py", "chemical_preparation_manifest"): (U, "chemical_preparation_manifest read"),
    ("backend/mw/api/app.py", "_public_job"): (U, "chemical artifacts"),
    ("backend/mw/api/app.py", "report_download"): (U, "report manifest"),
    ("backend/mw/analysis_executions.py", "*"): (BU, "M13 execution driver"),
    ("backend/mw/jobs/sequence_model_worker.py", "<module>"): (U, "[HASH] docstring only"),
    # ---- second pass (after import-resolved aliases)
    ("backend/mw/analysis_plans.py", "Preparation"): (BU, "M13 request model (no missing_residues field)"),
    ("backend/mw/analysis_plans.py", "_chemical"): (BU, "M13 plan -> chemical_inputs.preview"),
    ("backend/mw/analysis_plans.py", "_compatibility"): (BU, "M13 OPERATIONS"),
    ("backend/mw/analysis_plans.py", "_output"): (BU, "M13 OPERATIONS"),
    ("backend/mw/analysis_plans.py", "_structure_meta"): (BU, "M13 STRUCTURE_SCHEMAS kind/schema check"),
    ("backend/mw/analysis_plans.py", "compile_plan"): (BU, "M13 OPERATIONS"),
    ("backend/mw/analysis_plans.py", "validate_plan"): (BU, "M13 OPERATIONS"),
    ("backend/mw/chemical_inputs.py", "preview"): (F, "M11 preview (shared by /chemical/preview, prolif_prepare_v1, M13 plan)"),
    ("backend/mw/comparison_reports.py", "_catalog"): (BU, "comparison report atom catalog"),
    ("backend/mw/jev_loop_projection.py", "_validate_header"): (R, "M25 loop projection validation"),
    ("backend/mw/jev_loop_store.py", "_admit_setup"): (R, "M25 protein loop -> M21 selection (M7 preflight)"),
    ("backend/mw/jev_loop_store.py", "step_job"): (R, "M25 protein loop compute -> M21 selection"),
    ("backend/mw/jev_loops.py", "parse_created"): (R, "M25 pool structure handle regex by kind"),
    ("backend/mw/jev_projection.py", "_validate_projection"): (R, "M24 projection validation (handle regex by kind)"),
    ("backend/mw/jobs/queue.py", "JobQueue._state"): (U, "openmm_preparation_manifest handle (M7 attempt state)"),
    ("backend/mw/jobs/sequence_ga_worker.py", "validate_manifest"): (R, "[HASH] M23 worker input structure_kind == prepared_structure"),
    ("backend/mw/kinase_precedents.py", "_validate"): (BU, "M27 result validation (structure_kind via numbering map)"),
    ("backend/mw/mutation_model_bundle.py", "_check_relations"): (R, "M21 model validation: structure kind/schema == prepared_structure@1"),
    ("backend/mw/mutation_model_math.py", "_validated"): (R, "[HASH] M21 content structure_kind == prepared_structure"),
    ("backend/mw/openmm_reports.py", "_markdown"): (BU, "M7 report manifest (report object, not preparation manifest)"),
    ("backend/mw/pocket_bundle.py", "_check_source"): (BU, "pocket_set source kind validation"),
    ("backend/mw/pocket_bundle.py", "publish"): (BU, "pocket projection manifest (pocket_input@1, not preparation manifest)"),
    ("backend/mw/pocket_reports.py", "render_pocket_report"): (BU, "pocket report manifest"),
    ("backend/mw/reaction_knowledge.py", "_validate"): (BU, "M26 result validation"),
    ("backend/mw/reference_snapshots.py", "_validate_manifest"): (U, "M15 reference snapshot manifest (different object)"),
    ("backend/mw/saved_scenes.py", "save_scene"): (F, "POST /viewer/scenes"),
    ("backend/mw/saved_scenes.py", "scene_detail"): (BU, "saved scene reopen (only scenes that passed save)"),
    ("backend/mw/sequence_ga_bundle.py", "_check_model"): (R, "[HASH] M23 set model structure_kind"),
    ("backend/mw/sequence_ga_jobs.py", "projection"): (R, "[HASH] M23 -> M7 preflight"),
    ("backend/mw/tools/comparison.py", "AtomRefV1"): (U, "AtomRef altloc field"),
    ("backend/mw/tools/comparison.py", "resolve"): (F, "measure/align internal"),
    ("backend/mw/tools/numbering.py", "_normalized"): (F, "map_residue_numbering admission (ALLOWED_KINDS)"),
    ("backend/mw/workflows.py", "InspectionRequest"): (F, "inspect_complex request model: missing_residues Literal['leave_gaps'] (strict)"),
}
WILDCARD_FILES = {key[0] for key in CLASSIFICATION if key[1] == "*"}


def repo_root(argv: list[str]) -> Path:
    args = [a for a in argv if not a.startswith("--")]
    return Path(args[0]).resolve() if args else Path(__file__).resolve().parents[4]


def hashed_files(root: Path) -> dict[str, str]:
    """Relative path -> why it is hashed (27 BASELINE_BLOBS, golden also_hashed_files, M21/M23 module lists)."""
    out: dict[str, str] = {}
    tree = ast.parse((root / "backend/tests/test_kinase_precedents_ast.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "BASELINE_BLOBS" for t in node.targets):
            for key in node.value.keys:
                out[key.value] = "BASELINE_BLOBS(27)"
    golden = json.loads((root / "backend/tests/fixtures/sequence_ga/golden_call_keys.json").read_text())

    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "also_hashed_files":
                    for rel in v:
                        out.setdefault(rel, "golden also_hashed_files")
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(golden)
    for rel, names in (("backend/mw/mutation_model_bundle.py", {"DEPENDENCIES", "WORKER"}),
                       ("backend/mw/sequence_ga_inputs.py", {"GA_MODULES"})):
        tree = ast.parse((root / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value.endswith(".py"):
                        path = sub.value if sub.value.startswith("backend/") else "backend/" + sub.value
                        out.setdefault(path, f"{Path(rel).name}:{'/'.join(sorted(names))}")
    return out


def module_key(rel: str) -> str:
    """backend/mw/tools/jev.py -> tools/jev ; backend/mw/api/app.py -> api/app"""
    return rel[len("backend/mw/"):-3]


def imports_of(rel: str, tree: ast.AST, modules: set[str]) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """(module aliases: local name -> module key, imported names: local name -> (module key, name))."""
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


def relevant_names(trees: dict[str, ast.AST], imports: dict[str, tuple]) -> set[tuple[str, str]]:
    """(module key, module-level name) whose value mentions a target string, directly or through such a name."""
    relevant: set[tuple[str, str]] = set()
    changed = True
    while changed:
        changed = False
        for key, tree in trees.items():
            mods, names = imports[key]
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                hit = any(isinstance(s, ast.Constant) and s.value in TARGET_STRINGS for s in ast.walk(node.value))
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Name) and ((key, sub.id) in relevant or names.get(sub.id) in relevant):
                        hit = True
                    if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and
                            (mods.get(sub.value.id), sub.attr) in relevant):
                        hit = True
                for t in targets:
                    if hit and isinstance(t, ast.Name) and (key, t.id) not in relevant:
                        relevant.add((key, t.id))
                        changed = True
    return relevant


# Calls whose callee (resolved to its defining module) reads a prepared structure or is a consumer entry.
CALL_TARGETS = {("tools/structural", n) for n in ("_parse", "structure_bytes", "structure_residues")} | {
    ("tools/comparison", "atom_rows"), ("tools/openmm_method", "preflight"),
    ("pocket_input", "_load_source"), ("pocket_input", "project"), ("pocket_input", "preflight"),
    ("pocket_bundle", "preflight"), ("pocket_bundle", "submission"),
    ("chemical_inputs", "_source_rows"), ("chemical_inputs", "preview"), ("chemical_bundle", "prepare_selected"),
    ("viewer_intents", "create_session"), ("saved_scenes", "save_scene"), ("saved_scenes", "_source"),
    ("numbering_reads", "pdb_id_hint"), ("reports", "build_inspection_report"), ("workflows", "inspect_complex"),
    ("analysis_plans", "create_plan"), ("mutation_model_bundle", "selection"), ("sequence_ga_jobs", "selection"),
}
MANIFEST_SCOPES = {"waters", "missing_residues", "altloc", "hydrogens", "symmetry_mates"}


class Scanner(ast.NodeVisitor):
    def __init__(self, rel: str, relevant: set, mods: dict, names: dict, local_defs: set[str]):
        self.rel, self.key = rel, module_key(rel)
        self.relevant, self.mods, self.names, self.local_defs = relevant, mods, names, local_defs
        self.stack: list[str] = []
        self.hits: list[tuple[int, str, str]] = []
        self.routes: dict[str, str] = {}

    def _qual(self) -> str:
        return ".".join(self.stack) if self.stack else "<module>"

    def _hit(self, node: ast.AST, pattern: str) -> None:
        self.hits.append((node.lineno, self._qual(), pattern))

    def _scope(self, node, name):
        for dec in getattr(node, "decorator_list", []):
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in
                    {"get", "post", "put", "delete", "patch"} and dec.args and isinstance(dec.args[0], ast.Constant)):
                self.routes[name] = f"{dec.func.attr.upper()} {dec.args[0].value}"
        self.stack.append(name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node):
        self._scope(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._scope(node, node.name)

    def visit_AnnAssign(self, node):
        if self.stack and isinstance(node.target, ast.Name) and node.target.id in MANIFEST_SCOPES:
            self._hit(node, f"request-model-field:{node.target.id}")
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            if node.value in TARGET_STRINGS or node.value in {"leave_gaps", "modeled_internal_gaps"}:
                self._hit(node, f"str:{node.value}")
            elif "(?:structure|prepared_structure)" in node.value:
                self._hit(node, "str:handle-regex(prepared_structure)")

    def _resolve_name(self, ident: str) -> tuple[str, str] | None:
        if (self.key, ident) in self.relevant:
            return (self.key, ident)
        if ident in self.names and self.names[ident] in self.relevant:
            return self.names[ident]
        return None

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and self.stack and self._resolve_name(node.id):
            self._hit(node, "alias:" + ".".join(self._resolve_name(node.id)))

    def visit_Attribute(self, node):
        if (isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Name) and
                (self.mods.get(node.value.id), node.attr) in self.relevant):
            self._hit(node, f"alias:{self.mods[node.value.id]}.{node.attr}")
        self.generic_visit(node)

    def visit_Subscript(self, node):
        key = node.slice.value if isinstance(node.slice, ast.Constant) else None
        if key == "manifest":
            self._hit(node, 'sub:["manifest"]')
        if isinstance(node.value, ast.Name) and node.value.id in MANIFEST_VARS and key in MANIFEST_FIELDS:
            self._hit(node, f'manifest-field:{node.value.id}["{key}"]')
        self.generic_visit(node)

    def _callee(self, func) -> tuple[str, str] | None:
        if isinstance(func, ast.Name):
            if func.id in self.local_defs:
                return (self.key, func.id)
            return self.names.get(func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in self.mods:
            return (self.mods[func.value.id], func.attr)
        return None

    def visit_Call(self, node):
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
        if name == "getattr" and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id == "req":
            self._hit(node, "getattr(req, field)")
        self.generic_visit(node)

    def visit_Compare(self, node):
        parts = [node.left, *node.comparators]

        def is_kind(n):
            return (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and n.slice.value in
                    {"kind", "schema", "structure_kind", "source_kind"})
        if any(is_kind(p) for p in parts) and any(isinstance(s, ast.Constant) and s.value in TARGET_STRINGS
                                                 for p in parts for s in ast.walk(p)):
            self._hit(node, "kind-compare")
        self.generic_visit(node)


def classify(rel: str, qual: str) -> tuple[str, str]:
    if (rel, qual) in CLASSIFICATION:
        return CLASSIFICATION[(rel, qual)]
    top = qual.split(".")[0]
    for key in ((rel, top), (rel, "register." + qual.split(".")[-1])):
        if key in CLASSIFICATION:
            return CLASSIFICATION[key]
    if rel in WILDCARD_FILES:
        return CLASSIFICATION[(rel, "*")]
    return ("UNCLASSIFIED", "")


def scan_yaml(root: Path) -> list[str]:
    lines: list[str] = []
    tools = (root / "config/tools.yaml").read_text().splitlines()
    name = None
    for number, text in enumerate(tools, 1):
        m = re.match(r"\s*- name:\s*(\S+)", text)
        if m:
            name = m.group(1)
        if re.search(r"prepared_structure|missing_residues|leave_gaps", text):
            lines.append(f"config/tools.yaml:{number} | tool={name} | {text.strip()}")
    for path in sorted((root / "config/pipelines").glob("*")):
        for number, text in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"prepared|missing_residues|leave_gaps|compute_interactions|prepare_structure", text):
                lines.append(f"{path.relative_to(root).as_posix()}:{number} | {text.strip()}")
    return lines


def tool_crosscheck(root: Path) -> list[str]:
    """tools.yaml accepts that include prepared_structure x HTTP reachability (SUPPORTED_TOOLS / JOB_PROTOCOLS)."""
    app = ast.parse((root / "backend/mw/api/app.py").read_text())
    supported: set[str] = set()
    for node in app.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SUPPORTED_TOOLS" for t in node.targets):
            supported = {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant)}
    energetic = ast.parse((root / "backend/mw/tools/energetic.py").read_text())
    job_tools: dict[str, str] = {}
    for node in energetic.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"PROTOCOLS", "JOB_PROTOCOLS"}
                                                for t in node.targets):
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Dict):
                    for k, v in zip(sub.keys, sub.values):
                        if isinstance(k, ast.Constant) and isinstance(v, ast.Tuple):
                            job_tools[v.elts[0].value] = k.value
    out, name = [], None
    lines = (root / "config/tools.yaml").read_text().splitlines()
    blocks: dict[str, str] = {}
    for text in lines:
        m = re.match(r"\s*- name:\s*(\S+)", text)
        if m:
            name = m.group(1)
            blocks[name] = ""
        elif name is not None:
            blocks[name] += text + "\n"
    for tool, body in blocks.items():
        acc = re.search(r"accepts:(.*?)(?:\n\s{4}\w|\Z)", body, re.S)
        if acc and "prepared_structure" in acc.group(1):
            lane = ("POST /commands (SUPPORTED_TOOLS)" if tool in supported else
                    f"POST /jobs protocol {job_tools[tool]}" if tool in job_tools else "no HTTP lane")
            out.append(f"{tool:28} accepts prepared_structure | {lane}")
    return out


FRONT_PATTERNS = {
    "/commands": r'runPath\(id, "/commands"\)',
    "/viewer/sessions POST": r'runPath\(id, "/viewer/sessions"\)',
    "/viewer/scenes POST": r'runPath\(id, "/viewer/scenes"\)',
    "/viewer/figures POST": r'runPath\(id, "/viewer/figures"\)',
    "/viewer/intents POST": r'runPath\(id, "/viewer/intents"\)',
    "/structures/bytes": r"/structures/bytes\?",
    "/structures/residues": r"/structures/residues\?",
    "/structures/atoms": r"`/structures/atoms\?",
    "/jobs/preflight": r"/jobs/preflight\?structure=",
    "/pockets/preflight": r"/pockets/preflight\?structure=",
    "/chemical/preview": r'"/chemical/preview"',
    "/reference/pdb_id_hint": r"/reference/pdb_id_hint\?structure=",
    "/analysis/plans POST": r'runPath\(id, "/analysis/plans"\), jsonPost',
    "/reports POST": r'createReport: .*runPath\(id, "/reports"\)',
    "/jobs POST protocol": r'(jsonPost\(|JSON\.stringify\()\{ protocol_id: "(openmm_protein_minimize|fpocket_detect_v1|prolif_prepare_v1|openmm_mutation_model_v1|sequence_ga_dock_v1|qvina_dock_v1)"',
    "kind filter prepared_structure": r'"prepared_structure"\]|\["structure", "prepared_structure"|=== "prepared_structure"|output\.kind !== "prepared_structure"',
}


def scan_front(root: Path) -> list[str]:
    out = []
    for base in ("frontend/src", "frontend/app"):
        for path in sorted((root / base).rglob("*")):
            rel = path.relative_to(root).as_posix()
            if path.suffix not in {".ts", ".tsx"} or "/gallery/" in rel or "/mock/" in rel:
                continue
            for number, text in enumerate(path.read_text().splitlines(), 1):
                for label, pattern in FRONT_PATTERNS.items():
                    if re.search(pattern, text):
                        out.append(f"{rel}:{number} | {label} | {text.strip()[:150]}")
    return out


def main(argv: list[str]) -> int:
    out_path = None
    if "--out" in argv:
        at = argv.index("--out")
        out_path = Path(argv[at + 1])
        argv = argv[:at] + argv[at + 2:]
    root = repo_root(argv)
    files = []
    for path in sorted((root / "backend/mw").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files.append((path.relative_to(root).as_posix(), ast.parse(path.read_text(), str(path.name))))
    modules = {module_key(rel) for rel, _t in files}
    trees = {module_key(rel): tree for rel, tree in files}
    imports = {module_key(rel): imports_of(rel, tree, modules) for rel, tree in files}
    relevant = relevant_names(trees, imports)
    hashed = hashed_files(root)
    report: list[str] = [PROTOTYPE_HEADER.lstrip("# "),
                         "M29 T1 (b) prepared_structure / preparation_manifest consumer inventory (repo-relative paths)",
                         f"backend files scanned: {len(files)}; hashed files known: {len(hashed)}",
                         "module-level names resolved as prepared_structure aliases: " +
                         ", ".join(f"{m}.{n}" for m, n in sorted(relevant)), ""]
    rows = []
    for rel, tree in files:
        local_defs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        mods, names = imports[module_key(rel)]
        scanner = Scanner(rel, relevant, mods, names, local_defs)
        scanner.visit(tree)
        for line, qual, pattern in scanner.hits:
            route = scanner.routes.get(qual.split(".")[0], "")
            cat, note = classify(rel, qual)
            rows.append((rel, line, qual, route, pattern, cat, note, "HASH" if rel in hashed else ""))
    report.append("== 1. backend hits (file:line | function [route] | pattern | category | hash | note)")
    for rel, line, qual, route, pattern, cat, note, h in rows:
        report.append(f"{rel}:{line} | {qual}{' [' + route + ']' if route else ''} | {pattern} | {cat} | {h} | {note}")
    report += ["", "== 2. per-function summary (category counts)"]
    per = defaultdict(list)
    for rel, line, qual, route, pattern, cat, note, h in rows:
        per[(rel, qual, cat, h)].append(line)
    for (rel, qual, cat, h), lines in sorted(per.items()):
        report.append(f"{cat:16} {h:4} {rel}:{min(lines)} {qual} ({len(lines)} hits)")
    counts = Counter(cat for *_x, cat, _n, _h in rows)
    report += ["", "== 3. totals", f"hits: {len(rows)}; functions: {len(per)}; by category: " +
               ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))]
    unclassified = sorted({(r[0], r[2]) for r in rows if r[5] == "UNCLASSIFIED"})
    report.append(f"unclassified functions: {len(unclassified)}")
    report += [f"  UNCLASSIFIED {rel} {qual}" for rel, qual in unclassified]
    report += ["", "== 4. hashed-file hits (manifest / kind reads inside call-key hashed files)"]
    report += [f"{rel}:{line} | {qual} | {pattern} | {hashed[rel]}" for rel, line, qual, _r, pattern, *_x in rows
               if rel in hashed]
    report += ["", "hashed files with no hit: " + ", ".join(sorted(set(hashed) - {r[0] for r in rows}))]
    report += ["", "== 5. config (tool contracts accepts / pipelines)"] + scan_yaml(root)
    report += ["", "== 5b. tool contracts accepting prepared_structure x HTTP lane"] + tool_crosscheck(root)
    report += ["", "== 6. frontend structure-handle senders (src + app, gallery/mock excluded)"] + scan_front(root)
    text = "\n".join(report) + "\n"
    if str(Path.home()) in text:
        raise SystemExit("absolute user path leaked into the report")
    if out_path is not None:
        out_path.write_text(text)
        print(f"wrote {out_path.name}: {len(text.encode())} bytes, {len(rows)} backend hits")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
