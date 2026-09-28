import type { ResidueRef, RunEvent } from "./contracts";
import { sameAtomRef, sameResidueRef, type AtomCatalog, type AtomRefV1 } from "./comparison";

export const chemicalCategories = ["HBDonor", "HBAcceptor", "Hydrophobic", "Cationic", "Anionic"] as const;
export type ChemicalCategory = typeof chemicalCategories[number];
export type ChemicalMode = "create_new" | "attach_existing";
export type HydrogenPolicy = "map_existing" | "replace_from_sdf";

/** Object creation precedes job commit; only successful terminals admit saved results. */
export function completedChemicalResultHandles(events: RunEvent[]): string[] {
  const kinds = new Map(events.filter(event => event.type === "object_created")
    .map(event => event.type === "object_created" ? [event.handle, event.kind] as const : ["", ""] as const));
  return [...new Set(events.filter(event => event.type === "job_terminal" && event.status === "done")
    .flatMap(event => event.type === "job_terminal" ? event.output_handles : [])
    .filter(handle => kinds.get(handle) === "chemical_interaction_set"))];
}

/** The jobs endpoint is newest-first. Default follows the newest preparation; history follows exact provenance. */
export function linkedChemicalJobs(jobs: ChemicalJob[], resultHandle: string | null = null,
  graphHandle: string | null = null): { prepare: ChemicalJob | null; detect: ChemicalJob | null } {
  const prepares = jobs.filter(job => job.protocol_id === "prolif_prepare_v1");
  const detects = jobs.filter(job => job.protocol_id === "prolif_detect_v1");
  const donePrepareFor = (graph: string) => prepares.find(job =>
    job.status === "done" && job.output_handles.includes(graph)) ?? null;
  if (resultHandle) {
    const detect = detects.find(job => job.status === "done" &&
      job.output_handles.includes(resultHandle)) ?? null;
    if (!detect || (graphHandle && !detect.input_handles.includes(graphHandle)))
      return { prepare: null, detect: null };
    const graph = graphHandle ?? detect.input_handles.find(handle => !!donePrepareFor(handle));
    return { prepare: graph ? donePrepareFor(graph) : null, detect };
  }
  if (graphHandle) return { prepare: donePrepareFor(graphHandle),
    detect: detects.find(job => job.input_handles.includes(graphHandle)) ?? null };
  const prepare = prepares[0] ?? null;
  if (!prepare || prepare.status !== "done") return { prepare, detect: null };
  const graph = prepare.artifacts?.chemical_graph ?? prepare.output_handles[2];
  return { prepare, detect: graph ? detects.find(job => job.input_handles.includes(graph)) ?? null : null };
}

/** Bound on waiting for the native camera around one chemical row focus (tunable). */
export const chemicalFocusSettleTimeoutMs = 3000;
export const chemicalFocusTimeoutMessage =
  "화학 원자 초점 카메라가 제한 시간 안에 멈추지 않았습니다. 초점을 다시 시도하세요.";

/** One native camera observation: `camera` is a serialized snapshot, `applied` whether the requested focus is in effect. */
export interface ChemicalCameraProbe { inTransition: boolean; camera: string; applied: boolean }

/**
 * Wait through orbit inertia, Mol*'s deferred focus request and its transition. Resolves the
 * settled camera after two consecutive unchanged calm frames, null once the intent is revoked,
 * and throws the retryable timeout at `deadline` without ever reporting the focus applied.
 */
export async function waitForChemicalCameraSettle(probe: () => ChemicalCameraProbe | null,
  nextFrame: () => Promise<void>, current: () => boolean, now: () => number,
  deadline: number): Promise<string | null> {
  let calmFrames = 0;
  let previous: string | null = null;
  for (;;) {
    await nextFrame();
    if (!current()) return null;
    const state = probe();
    const calm = !!state && !state.inTransition && state.applied;
    calmFrames = calm && state.camera === previous ? calmFrames + 1 : 0;
    previous = calm ? state.camera : null;
    if (calmFrames >= 2) return state!.camera;
    if (now() >= deadline) throw new Error(chemicalFocusTimeoutMessage);
  }
}

/** Settle, read back, and repeat the readback if the camera moved while it was being taken. */
export async function settleChemicalFocus<T>(probe: () => ChemicalCameraProbe | null,
  nextFrame: () => Promise<void>, current: () => boolean, now: () => number, deadline: number,
  readback: () => Promise<T>): Promise<{ value: T; camera: string } | null> {
  for (;;) {
    const camera = await waitForChemicalCameraSettle(probe, nextFrame, current, now, deadline);
    if (camera === null) return null;
    const value = await readback();
    if (!current()) return null;
    const state = probe();
    if (state && !state.inTransition && state.applied && state.camera === camera) return { value, camera };
    if (now() >= deadline) throw new Error(chemicalFocusTimeoutMessage);
  }
}

/** Compare new chemical-lane element symbols without changing durable AtomRefs. */
export function canonicalChemicalElement(symbol: string): string {
  return symbol.trim().toUpperCase();
}

/** Every busy page action ends in a run reopen that closes the chemical workspace, so entry waits for it. */
export function chemicalEntryBlockedReason(busy: string): string | null {
  return busy ? `${busy} 끝난 뒤 열 수 있습니다.` : null;
}

export function canHydrateChemicalJobs(requestRun: string, currentRun: string,
  selectionAtStart: number, currentSelection: number,
  jobs: { run_id: string; protocol_id: string }[]): boolean {
  return requestRun === currentRun && selectionAtStart === currentSelection &&
    jobs.every(job => job.run_id === requestRun);
}

export function chemicalJobActionCurrent(ticket: number, currentTicket: number,
  runId: string, jobId: string, protocolId: string,
  returned: { run_id: string; job_id: string; protocol_id: string }): boolean {
  return ticket === currentTicket && returned.run_id === runId && returned.job_id === jobId &&
    returned.protocol_id === protocolId;
}

export function chemicalCanCancel(status: string, cancelRequested: boolean, cancelBusy: boolean): boolean {
  return !cancelBusy && !cancelRequested && ["running", "queued", "claimed"].includes(status);
}

export function declaredTerminalNames(residue: ResidueRef, text: string, atoms: AtomRefV1[]): string[] {
  const names = text.split(",").map(name => name.trim()).filter(Boolean);
  if (!names.length || new Set(names).size !== names.length)
    throw new Error("말단 확장 원자 이름은 중복 없이 하나 이상 입력하세요.");
  for (const name of names) {
    const hits = atoms.filter(atom => atom.atom_name === name && sameResidueRef(atom.residue, residue));
    if (hits.length !== 1) throw new Error(`말단 확장 원자 ${name}의 공급 site가 없거나 모호합니다.`);
  }
  return names;
}

export function chemicalApprovalRequired(status: number,
  approval: { gate: string; tool: string } | undefined, stage: "prepare" | "detect"): boolean {
  return status === 409 && approval?.gate === "expensive_first_call" &&
    approval.tool === (stage === "prepare" ? "prepare_chemical_structure" : "compute_chemical_interactions");
}

export function previewMatchesRequest(previewRequest: string, args: ChemicalPrepareArgs): boolean {
  return previewRequest !== "" && previewRequest === JSON.stringify(args);
}

export interface ChemicalImport { schema: "chemical_raw_input@1"; handle: string;
  kind: "receptor" | "ligand_sdf" | "receptor_bonds"; format: string; sha256: string; size: number }
export interface ChemicalInspect { kind: ChemicalImport["kind"]; handle: string; sha256: string;
  model_numbers?: number[]; records?: { index: number; title: string; atom_count: number;
    heavy_atom_count: number; hydrogen_count: number; has_3d: boolean }[];
  [key: string]: unknown }
export interface ChemicalLigandAtom { sdf_atom_index: number; atom_name: string | null;
  name_generated: boolean; atom_map_tag: string | null; element: string; hydrogen: boolean;
  formal_charge?: number; coordinate_A: [number, number, number] }
export interface ChemicalMapping { sdf_atom_index: number; source_atom: AtomRefV1 }
export interface ChemicalPreview { schema: "chemical_preparation_preview@1"; ready: boolean;
  blockers: { code: string; message: string; atoms: AtomRefV1[] }[];
  included_receptor_atoms: number; excluded_water_atoms: number; selected_ligand_atoms: number;
  ligand_atoms: ChemicalLigandAtom[]; ligand_mapping: (ChemicalMapping & { discrepancy_A: number })[];
  mapping_proposals: { sdf_atom_index: number; candidates?: { source_atom: AtomRefV1; discrepancy_A: number }[];
    reason?: string }[];
  terminal_extensions: { residue: ResidueRef; atom_names: string[]; declared: boolean;
    resolved_atoms?: AtomRefV1[]; terminal_anchor?: "N" | "C" | null;
    attachment_bonds?: { first: AtomRefV1; second: AtomRefV1 }[];
    extension_bonds?: { first: AtomRefV1; second: AtomRefV1 }[] }[];
  limitations: string[] }
export interface ChemicalAck { schema: "chemical_preparation_ack@1"; supplied_graph_complete: boolean;
  supplied_hydrogens_complete: boolean; use_supplied_protonation_tautomer: boolean;
  infer_receptor_orders_charges: boolean; description: string; ph_annotation: number | null }
export interface TerminalExtension { residue: ResidueRef; atom_names: string[]; approve_supplied_graph: boolean }
export type ChemicalPrepareArgs = { schema: "chemical_prepare_request@1";
  connectivity: { kind: "pdb_conect" | "sidecar"; sidecar_handle: string | null };
  ligand_sdf_handle: string; sdf_record_index: number; terminal_extensions: TerminalExtension[];
  acknowledgement: ChemicalAck } & (
  { mode: "create_new"; receptor_input_handle: string; receptor_model_number: number;
    ligand_instance: ResidueRef } |
  { mode: "attach_existing"; complex_handle: string; complex_model_number: number;
    selected_ligand: ResidueRef; hydrogen_policy: HydrogenPolicy; mapping: ChemicalMapping[] });
export interface ChemicalView { schema: "chemical_structure_view@1"; handle: string;
  kind: "chemical_structure"; format: "mmcif"; text: string; model_number: number;
  viewer_source_sha256: string; manifest_handle: string; manifest_sha256: string }
export interface ChemicalPreparationManifest { schema: "chemical_preparation_manifest@1";
  mode: ChemicalMode; request: ChemicalPrepareArgs; derived_coordinate_policy: string;
  terminal_extension_inventory: unknown[]; limitations: string[] }
export interface ChemicalRow { row_id: string; category: ChemicalCategory; backend_category: string;
  ligand_atoms: AtomRefV1[]; receptor_atoms: AtomRefV1[];
  roles: Record<string, AtomRefV1>; role_coordinates_A: Record<string, number[]>;
  engine_role_coordinates_A: Record<string, number[]>;
  native_parent_indices: { ligand: number[]; protein: number[] };
  native_within_residue_indices: { ligand: number[]; protein: number[] };
  distance_A: number; distance_roles: [string, string]; DHA_angle_deg: number | null;
  native_metadata: Record<string, unknown> }
export interface ChemicalResult { schema: "chemical_interaction_set@1";
  chemical_structure_handle: string; graph_handle: string; manifest_handle: string;
  rows: ChemicalRow[]; total: number; null_result: boolean; limitations: string[];
  method: Record<string, unknown>; dependency_manifest: Record<string, unknown>;
  criteria: Record<string, unknown> }
export interface ChemicalResultPage { schema: "chemical_interaction_page@1"; handle: string;
  total: number; offset: number; limit: number; rows: ChemicalRow[] }
export interface ChemicalJob { job_id: string; run_id: string; protocol_id: "prolif_prepare_v1" | "prolif_detect_v1";
  status: string; blocked_reason: string | null; failure: ChemicalJobFailure | null;
  input_handles: string[]; output_handles: string[]; attempt_ordinal: number;
  cancel_requested: boolean; timeout_s: number;
  artifacts?: { preparation_manifest?: string; chemical_structure?: string;
    chemical_graph?: string; chemical_interaction_set?: string } }
export interface ChemicalJobFailure {
  error: string; message: string; reason_code?: string;
  source_residues?: ResidueRef[]; source_atoms?: AtomRefV1[]; sdf_atom_indices?: number[];
}

/** Explicit source identities from a validated worker failure; null labels stay visible as null. */
export function chemicalFailureDetails(failure: ChemicalJobFailure): string[] {
  const residue = (ref: ResidueRef) =>
    `model ${ref.model_number ?? "null"}, auth ${ref.chain_auth}/${ref.seq_auth}${ref.icode ? ` insertion ${ref.icode}` : " insertion ∅"}, ` +
    `label ${ref.chain_label ?? "null"}/${ref.seq_label ?? "null"}, ${ref.resname}`;
  const lines = failure.reason_code ? [`reason_code ${failure.reason_code}`] : [];
  for (const ref of failure.source_residues ?? []) lines.push(`source residue: ${residue(ref)}`);
  for (const ref of failure.source_atoms ?? []) lines.push(
    `source atom: ${residue(ref.residue)}, atom ${ref.atom_name}, altloc ${ref.altloc || "∅"}, ` +
    `element ${ref.element}, site ${ref.site_index}, structure ${ref.structure_handle}`);
  for (const index of failure.sdf_atom_indices ?? [])
    lines.push(`SDF atom index (zero-based): ${index}`);
  return lines;
}
export interface ChemicalCapability { available: boolean; reason?: string; protocol?: string;
  [key: string]: unknown }

export function exactChemicalRow(row: ChemicalRow, sourceHandle: string): boolean {
  const roles = Object.values(row.roles);
  const sourceAtoms = [...row.ligand_atoms, ...row.receptor_atoms];
  const hydrogenBond = row.category === "HBDonor" || row.category === "HBAcceptor";
  return !!row.row_id && chemicalCategories.includes(row.category) &&
    row.ligand_atoms.length > 0 && row.receptor_atoms.length > 0 &&
    row.distance_roles.length === 2 && row.distance_roles.every(key => !!row.roles[key]) &&
    roles.every(ref => sourceAtoms.some(atom => sameAtomRef(atom, ref))) &&
    (!hydrogenBond || (row.distance_roles[0] === "donor" && row.distance_roles[1] === "acceptor" &&
      !!row.roles.donor && !!row.roles.hydrogen && !!row.roles.acceptor && row.DHA_angle_deg != null)) &&
    (hydrogenBond || row.DHA_angle_deg == null) &&
    [...row.ligand_atoms, ...row.receptor_atoms, ...roles].every(ref =>
      ref.structure_handle === sourceHandle && Number.isInteger(ref.site_index) && ref.site_index >= 0) &&
    Number.isFinite(row.distance_A) && row.distance_A >= 0 &&
    (row.DHA_angle_deg == null || (Number.isFinite(row.DHA_angle_deg) &&
      row.DHA_angle_deg >= 0 && row.DHA_angle_deg <= 180));
}

export function validateChemicalCatalog(view: ChemicalView, catalog: AtomCatalog): boolean {
  return view.handle === catalog.structure_handle && view.viewer_source_sha256 === catalog.viewer_source_sha256 &&
    view.model_number === catalog.model_number && catalog.rows.length === catalog.total &&
    new Set(catalog.rows.map(row => row.viewer_source_index)).size === catalog.total &&
    new Set(catalog.rows.map(row => JSON.stringify(row.ref))).size === catalog.total &&
    catalog.rows.every(row => row.ref.structure_handle === view.handle &&
      row.viewer_source_index >= 0 && row.viewer_source_index < catalog.total);
}

/** Bounded M11-only pages; the native viewer receives one ordered, fully checked catalog. */
export async function collectChemicalAtomCatalog(handle: string,
  fetchPage: (offset: number, limit: number) => Promise<AtomCatalog>, limit = 1000): Promise<AtomCatalog> {
  if (limit < 1 || limit > 1000 || !Number.isInteger(limit)) throw new Error("화학 원자 페이지 크기가 올바르지 않습니다.");
  let first: AtomCatalog | null = null;
  const rows: AtomCatalog["rows"] = [];
  const refs = new Set<string>();
  const sites = new Set<number>();
  for (let offset = 0; ; offset += limit) {
    const page = await fetchPage(offset, limit);
    if (page.schema !== "atom_catalog@1" || page.structure_handle !== handle ||
        !Number.isInteger(page.total) || page.total < 1 || page.total > 10256 ||
        page.offset !== offset || page.limit !== limit || !Array.isArray(page.rows))
      throw new Error("화학 원자 목록의 페이지 식별자가 올바르지 않습니다.");
    if (!first) first = page;
    if (page.total !== first.total || page.model_number !== first.model_number ||
        page.viewer_source_sha256 !== first.viewer_source_sha256 ||
        !/^[a-f0-9]{64}$/.test(page.viewer_source_sha256) ||
        page.rows.length !== Math.min(limit, first.total - offset))
      throw new Error("화학 원자 목록의 크기·모델·바이트 SHA가 일치하지 않습니다.");
    for (let i = 0; i < page.rows.length; i++) {
      const row = page.rows[i];
      const key = JSON.stringify(row.ref);
      if (row.viewer_source_index !== offset + i || row.ref.structure_handle !== handle ||
          !Number.isInteger(row.ref.site_index) || row.ref.site_index < 0 ||
          row.ref.site_index >= first.total ||
          row.ref.residue.model_number !== page.model_number ||
          typeof row.ref.residue.chain_auth !== "string" ||
          (row.ref.residue.chain_label !== null && typeof row.ref.residue.chain_label !== "string") ||
          !Number.isInteger(row.ref.residue.seq_auth) ||
          (row.ref.residue.seq_label !== null && !Number.isInteger(row.ref.residue.seq_label)) ||
          typeof row.ref.residue.icode !== "string" || typeof row.ref.residue.resname !== "string" ||
          typeof row.ref.atom_name !== "string" || typeof row.ref.altloc !== "string" ||
          typeof row.ref.element !== "string" ||
          refs.has(key) || sites.has(row.ref.site_index) ||
          !Array.isArray(row.coordinate_A) || row.coordinate_A.length !== 3 ||
          !row.coordinate_A.every(Number.isFinite))
        throw new Error("화학 원자 목록의 원자 위치·식별자가 중복되거나 빠졌습니다.");
      refs.add(key); sites.add(row.ref.site_index); rows.push(row);
    }
    if (rows.length === first.total) return { ...first, rows };
  }
}

/** Per-request read bound for chemical source loads (tunable). */
export const chemicalReadTimeoutMs = 30000;

/**
 * Read one chemical source catalog with a fresh deadline for every page. A single signal shared by
 * the whole load made a slow-but-healthy backend time out a valid source (release3 attach).
 */
export function readChemicalAtomCatalog<S>(handle: string,
  fetchPage: (offset: number, limit: number, signal: S) => Promise<AtomCatalog>,
  newSignal: () => S, limit = 1000): Promise<AtomCatalog> {
  return collectChemicalAtomCatalog(handle, (offset, pageLimit) => fetchPage(offset, pageLimit, newSignal()), limit);
}

/** A Start whose HTTP response was lost still took effect when the same durable job moved past queued. */
export function chemicalStartProgressed(before: Pick<ChemicalJob, "run_id" | "job_id" | "protocol_id" | "attempt_ordinal">,
  durable: Pick<ChemicalJob, "run_id" | "job_id" | "protocol_id" | "status" | "attempt_ordinal">): boolean {
  return durable.run_id === before.run_id && durable.job_id === before.job_id &&
    durable.protocol_id === before.protocol_id &&
    (!["queued", "claimed"].includes(durable.status) || durable.attempt_ordinal > before.attempt_ordinal);
}

/** Submission is idempotent: identical inputs return the existing durable job, whatever its status. */
export function chemicalSubmitStatus(stage: "prepare" | "detect", job: Pick<ChemicalJob, "job_id" | "status">): string {
  if (job.status === "queued") return stage === "prepare"
    ? "준비 작업이 저장되었습니다. 시작을 누르면 실제 계산이 실행됩니다."
    : "화학 상호작용 작업이 저장되었습니다. 별도로 시작하세요.";
  return `같은 입력의 기존 작업을 다시 표시합니다 · ${job.job_id} · ${job.status} (새 작업을 만들지 않았습니다)`;
}

export function chemicalAnnotationForRow(row: ChemicalRow, sourceHandle: string) {
  if (!exactChemicalRow(row, sourceHandle)) throw new Error("저장된 화학 상호작용의 원자 식별자가 현재 구조와 다릅니다.");
  const [first, second] = row.distance_roles;
  const angle = row.DHA_angle_deg == null ? undefined :
    row.roles.donor && row.roles.hydrogen && row.roles.acceptor
      ? { donor: row.roles.donor, hydrogen: row.roles.hydrogen,
          acceptor: row.roles.acceptor, value_deg: row.DHA_angle_deg } : undefined;
  if (row.DHA_angle_deg != null && !angle) throw new Error("D–H···A 역할 정보가 불완전합니다.");
  return { sourceHandle, rowId: row.row_id, visible: true,
    distance: { first: row.roles[first], second: row.roles[second], value_A: row.distance_A,
      label: first === "donor" && second === "acceptor" ? "D···A" : `${first}···${second}` },
    angle };
}
