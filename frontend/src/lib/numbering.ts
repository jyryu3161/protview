/**
 * Pure logic of the M15 residue numbering panel in the "지식·보고서" tab (M15 spec sections 6 and 8).
 *
 * Every number shown comes from backend objects (`residue_numbering_map@1` rows, snapshot records); this
 * module never computes scientific values. It only decides form validity, the request body, row
 * filtering/paging of already-loaded rows, and whether a late response may still be applied.
 */
import type { ResidueRef, RunEvent } from "./contracts";

export type NumberingStatus = "mapped" | "unmapped" | "conflict";
export const NUMBERING_STATUSES: readonly NumberingStatus[] = ["mapped", "unmapped", "conflict"];
export const STATUS_LABEL: Record<NumberingStatus, string> = { mapped: "대응됨", unmapped: "대응 없음", conflict: "충돌" };
export const NUMBERING_STRUCTURE_KINDS = ["structure", "prepared_structure"] as const;
export type NumberingStructureKind = typeof NUMBERING_STRUCTURE_KINDS[number];
export const PDB_ID_PATTERN = /^[0-9][A-Za-z0-9]{3}$/;
/** Rows are read through `/objects` pages of this size (backend maximum). */
export const ROW_PAGE_LIMIT = 100;

export interface SnapshotFile { name: string; path: string; sha256: string; bytes: number; rows: number; use?: string }
export interface SnapshotSource { source: string; snapshot_id: string; date: string; version_hint: string | null;
  license: string; origin: string; url_count?: number; raw_sha256?: string[]; files?: SnapshotFile[] }
export interface ReferenceSnapshots { schema: "reference_snapshots@1"; available: boolean; reason_code: string | null;
  reason: string | null; set_hash: string | null; origin: string | null; imported_at: string | null;
  kbase_repo: { commit: string; dirty: boolean } | null; sources: SnapshotSource[] }
export interface SiftsChainHint { chain_auth: string; accessions: string[]; reason_code: string | null; reason: string | null }
export interface SiftsChains { schema: "reference_sifts_chains@1"; available: boolean; reason_code: string | null;
  reason: string | null; set_hash: string | null; pdb_id: string; chains: SiftsChainHint[] }
export interface UniprotEntry { accession: string; entry_name: string | null; gene: string | null; protein_name: string | null;
  organism: string | null; sequence_length: number }
export interface UniprotSearch { schema: "reference_uniprot_search@1"; query: string; offset: number; limit: number;
  available: boolean; reason_code: string | null; reason: string | null; set_hash: string | null; total: number;
  entries: UniprotEntry[] }
export interface PdbIdHint { structure: string; structure_kind: string; format: string; pdb_id: string | null;
  origin: "mmcif_entry_id" | "pdb_header" | null }
export interface NumberingMapListRow { handle: string; structure: string; structure_kind: NumberingStructureKind;
  model_number: number; pdb_id: string | null; chains: string[]; cross_checked_chains: string[]; set_hash: string;
  counts: Record<NumberingStatus, number>; row_count: number; null_result: boolean; created_seq: number;
  stale_snapshot: boolean; chain_details: NumberingChain[] }
export interface NumberingMapList { schema: "residue_numbering_map_list@1"; active_set_hash: string | null;
  snapshot_available: boolean; total: number; offset: number; limit: number; rows: NumberingMapListRow[] }

export type MethodAnswer = { accession: string; position: number } | { absent_reason: string; absent_reasons?: string[] };
export interface NumberingRow {
  residue: ResidueRef & { model_number: number };
  status: NumberingStatus;
  uniprot_accession: string | null; uniprot_position: number | null; uniprot_residue: string | null;
  residue_match: boolean | null;
  klifs_index?: number | null; klifs_label?: string | null; klifs_match?: "contiguous" | "gapped_unique" | null;
  conflict_reason: "positions_differ" | "one_method_only" | null;
  sifts: MethodAnswer | null; alignment: MethodAnswer | null;
}
export interface NumberingChain {
  chain_auth: string; requested_uniprot_accession?: string | null; methods_run: string[]; cross_check: boolean;
  cross_check_absent_reason: string | null;
  sifts: { accessions: string[]; sifts_chain_match: string; sifts_residue_key: string } | null;
  alignment: { accession: string; identity_pct: number | null; coverage_pct: number | null; aligned_pairs: number;
    identical: number; chain_residue_count: number; chain_reason: string[]; ambiguous_residue_count?: number } | null;
  klifs: { accession: string; applied: boolean; absent_reason: string | null; unresolved_regions: string[];
    gapped_regions?: string[] }[];
  residue_rule?: { rule: string; modified_residue_count: number };
  counts: Record<NumberingStatus, number>;
}

/** Structure handles of this run that the numbering tool accepts, in creation order. */
export function numberingStructures(events: RunEvent[]): { handle: string; kind: NumberingStructureKind }[] {
  const seen = new Set<string>();
  const result: { handle: string; kind: NumberingStructureKind }[] = [];
  for (const event of events) {
    if (event.type !== "object_created") continue;
    if (!(NUMBERING_STRUCTURE_KINDS as readonly string[]).includes(event.kind) || seen.has(event.handle)) continue;
    seen.add(event.handle);
    result.push({ handle: event.handle, kind: event.kind as NumberingStructureKind });
  }
  return result;
}

/** Chains that have polymer residues, in first-seen order. */
export function polymerChains(residues: { chain_auth: string; category: string }[]): string[] {
  const chains: string[] = [];
  for (const residue of residues) if (residue.category === "polymer" && !chains.includes(residue.chain_auth)) chains.push(residue.chain_auth);
  return chains;
}

export interface ChainChoice { chain_auth: string; selected: boolean; accession: string | null }
export interface NumberingForm {
  structure: string | null;
  chains: ChainChoice[];
  /** Suggested id as typed/edited; used only when `pdbIdConfirmed`. */
  pdbId: string;
  pdbIdConfirmed: boolean;
  /** SIFTS hints of the confirmed PDB id (null = not loaded / not confirmed). */
  sifts: SiftsChainHint[] | null;
}

export function emptyForm(): NumberingForm {
  return { structure: null, chains: [], pdbId: "", pdbIdConfirmed: false, sifts: null };
}

/** SIFTS accession to prefill for a chain: only when exactly one usable accession exists. */
export function siftsPrefill(sifts: SiftsChainHint[] | null, chain: string): string | null {
  const hint = sifts?.find(item => item.chain_auth === chain);
  return hint && !hint.reason_code && hint.accessions.length === 1 ? hint.accessions[0] : null;
}

/** Applies SIFTS hints: fills empty accessions with the single SIFTS accession; never overwrites a user choice. */
export function applySiftsHints(form: NumberingForm, sifts: SiftsChainHint[] | null): NumberingForm {
  return { ...form, sifts,
    chains: form.chains.map(choice => choice.accession ? choice
      : { ...choice, accession: siftsPrefill(sifts, choice.chain_auth) }) };
}

function siftsUsable(form: NumberingForm, chain: string): boolean {
  if (!form.pdbIdConfirmed || !form.sifts) return false;
  const hint = form.sifts.find(item => item.chain_auth === chain);
  return !!hint && !hint.reason_code && hint.accessions.length > 0;
}

export type FormCheck =
  | { ok: true; body: { structure: string; pdb_id: string | null; chains: { chain_auth: string; uniprot_accession: string | null }[] } }
  | { ok: false; errors: string[] };

/**
 * Builds the tool arguments. The PDB id is sent only after explicit confirmation; every selected chain needs
 * a usable method (SIFTS of the confirmed id or a chosen accession). The server re-validates everything.
 */
export function checkForm(form: NumberingForm): FormCheck {
  const errors: string[] = [];
  if (!form.structure) errors.push("구조를 고르세요.");
  const selected = form.chains.filter(choice => choice.selected);
  if (!selected.length) errors.push("체인을 하나 이상 고르세요.");
  const pdbId = form.pdbId.trim().toUpperCase();
  if (form.pdbIdConfirmed && !PDB_ID_PATTERN.test(pdbId)) errors.push("PDB ID 형식이 올바르지 않습니다(예: 1MQ4).");
  for (const choice of selected) {
    if (!choice.accession && !siftsUsable(form, choice.chain_auth))
      errors.push(`체인 ${choice.chain_auth}: 확인한 PDB ID의 SIFTS 대응이 없으므로 UniProt 항목을 고르세요.`);
  }
  if (errors.length || !form.structure) return { ok: false, errors };
  return { ok: true, body: { structure: form.structure, pdb_id: form.pdbIdConfirmed ? pdbId : null,
    chains: selected.map(choice => ({ chain_auth: choice.chain_auth, uniprot_accession: choice.accession })) } };
}

export type StatusFilter = "all" | NumberingStatus;

/** Filters already-loaded rows for display; `total` is always the full row count of the object. */
export function filterRows(rows: NumberingRow[], filter: StatusFilter, offset: number, limit: number) {
  const matched = filter === "all" ? rows : rows.filter(row => row.status === filter);
  return { total: rows.length, matched: matched.length, rows: matched.slice(offset, offset + limit) };
}

export function answerText(answer: MethodAnswer | null): string {
  if (!answer) return "실행 안 함";
  if ("position" in answer) return `${answer.accession} ${answer.position}`;
  return (answer.absent_reasons?.length ? answer.absent_reasons : [answer.absent_reason]).join(", ");
}

export function residueText(residue: ResidueRef & { model_number?: number }): string {
  const label = residue.chain_label === null && residue.seq_label === null ? "label 없음"
    : `label ${residue.chain_label ?? "null"}/${residue.seq_label ?? "null"}`;
  return `모델 ${residue.model_number ?? "?"} ${residue.chain_auth} ${residue.resname} ${residue.seq_auth}${residue.icode} (${label})`;
}

/** Read-state keyed by run and request sequence; late responses (older run or older request) are dropped. */
export interface Keyed<T> { runId: string | null; seq: number; state: LoadState<T> }
export type LoadState<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T }
  | { status: "error"; message: string; code: string | null };

export function keyedIdle<T>(runId: string | null): Keyed<T> { return { runId, seq: 0, state: { status: "idle" } }; }

export function keyedRequest<T>(current: Keyed<T>, runId: string | null, seq: number): Keyed<T> {
  if (runId === null || seq <= current.seq) return current;
  return { runId, seq, state: { status: "loading" } };
}

export function keyedResolve<T>(current: Keyed<T>, runId: string, seq: number, result: LoadState<T>): Keyed<T> {
  if (current.runId !== runId || current.seq !== seq) return current;
  return { ...current, state: result };
}

/**
 * Withdraws the PDB ID confirmation: SIFTS hints are dropped and accessions that only came from the SIFTS
 * prefill are cleared; accessions the user picked (`userPicked` chains) stay.
 */
export function withdrawSiftsHints(form: NumberingForm, userPicked: readonly string[]): NumberingForm {
  return { ...form, pdbIdConfirmed: false, sifts: null,
    chains: form.chains.map(choice => userPicked.includes(choice.chain_auth) ? choice : { ...choice, accession: null }) };
}

/** License text as recorded in the snapshot manifest; KLIFS states no terms (spec 4.3). */
export function licenseText(license: string): string {
  return license === "none-stated" ? "이용 조건 명시 없음(none-stated)" : license;
}

/** Version shown for a snapshot source: the manifest version hint, else the snapshot date. */
export function sourceVersion(source: Pick<SnapshotSource, "version_hint" | "date">): string {
  return source.version_hint ?? source.date;
}
