import type { ResidueRef } from "./contracts";

export interface AtomRefV1 {
  structure_handle: string;
  residue: ResidueRef;
  atom_name: string;
  altloc: string;
  element: string;
  site_index: number;
}
export interface AtomRow {
  ref: AtomRefV1;
  coordinate_A: [number, number, number];
  protein: boolean;
  viewer_source_index: number;
}
export interface AtomCatalog {
  schema: "atom_catalog@1";
  structure_handle: string;
  viewer_source_sha256: string;
  model_number: number;
  total: number;
  offset: number;
  limit: number;
  rows: AtomRow[];
}
export interface AtomDistance {
  schema: "atom_distance@1";
  structure_handle: string;
  first: AtomRefV1;
  second: AtomRefV1;
  first_coordinate_A: number[];
  second_coordinate_A: number[];
  distance_A: number;
  unit: "angstrom";
  method: "euclidean_atom_distance@1";
  limitations: string;
}
export interface AlignmentPair {
  reference: AtomRefV1;
  moving: AtomRefV1;
  reference_coordinate_A: number[];
  moving_coordinate_A: number[];
  before_residual_A: number;
  after_residual_A: number;
}
export interface RigidAlignment {
  schema: "rigid_alignment@1";
  reference_handle: string;
  moving_handle: string;
  reference_model_number: number;
  moving_model_number: number;
  pairs: AlignmentPair[];
  pair_count: number;
  method: string;
  numpy_version: string;
  rotation: number[][];
  translation_A: number[];
  rmsd_A: number;
  unaligned_rmsd_A: number;
  unit: "angstrom";
  limitations: string;
}
export type MeasurementResult = AtomDistance | RigidAlignment;

export interface ComparisonActionStamp { action: number; epoch: number; runId: string; scope: string }
export function sameComparisonAction(current: ComparisonActionStamp, expected: ComparisonActionStamp): boolean {
  return current.action === expected.action && current.epoch === expected.epoch &&
    current.runId === expected.runId && current.scope === expected.scope;
}

export function sameAtomRef(a: AtomRefV1, b: AtomRefV1): boolean {
  const ar = a.residue, br = b.residue;
  return a.structure_handle === b.structure_handle && a.site_index === b.site_index &&
    a.atom_name === b.atom_name && a.altloc === b.altloc && a.element === b.element &&
    ar.model_number === br.model_number && ar.chain_auth === br.chain_auth &&
    ar.seq_auth === br.seq_auth && ar.icode === br.icode && ar.resname === br.resname &&
    ar.chain_label === br.chain_label && ar.seq_label === br.seq_label;
}

export function sameResidueRef(a: ResidueRef, b: ResidueRef): boolean {
  return a.model_number === b.model_number && a.chain_auth === b.chain_auth &&
    a.seq_auth === b.seq_auth && a.icode === b.icode && a.chain_label === b.chain_label &&
    a.seq_label === b.seq_label && a.resname === b.resname;
}

/** Resolve native input-row indices through the already validated exact-byte catalog. */
export function residueFromNativeSites(catalog: AtomCatalog, sourceIndices: number[]): ResidueRef | null {
  if (!sourceIndices.length) return null;
  if (catalog.offset !== 0 || catalog.rows.length !== catalog.total) throw new Error("Incomplete atom catalog");
  const rows = new Map<number, AtomRow>();
  const sites = new Set<number>();
  for (const row of catalog.rows) {
    if (row.ref.structure_handle !== catalog.structure_handle ||
        row.ref.residue.model_number !== catalog.model_number ||
        rows.has(row.viewer_source_index) || sites.has(row.ref.site_index))
      throw new Error("Ambiguous atom catalog");
    rows.set(row.viewer_source_index, row);
    sites.add(row.ref.site_index);
  }
  let selected: ResidueRef | null = null;
  for (const index of new Set(sourceIndices)) {
    const row = rows.get(index);
    if (!row) throw new Error("Unknown native atom source index");
    if (selected && !sameResidueRef(selected, row.ref.residue)) throw new Error("Mixed native residue selection");
    selected = row.ref.residue;
  }
  return selected;
}

/** Full seven-field source identity; never select a native residue by parser labels. */
export function rowsForAuthoritativeResidue(catalog: AtomCatalog, target: ResidueRef): AtomRow[] {
  if (catalog.offset !== 0 || catalog.rows.length !== catalog.total) throw new Error("Incomplete atom catalog");
  const rows = catalog.rows.filter(row => row.ref.structure_handle === catalog.structure_handle &&
    sameResidueRef(row.ref.residue, target));
  if (!rows.length || new Set(rows.map(row => row.ref.site_index)).size !== rows.length ||
      new Set(rows.map(row => row.viewer_source_index)).size !== rows.length) return [];
  return rows;
}

export function nativeIntentCurrent(expected: { token: number; revision: number; intent: number },
                                    current: { token: number; revision: number; intent: number }): boolean {
  return expected.token === current.token && expected.revision === current.revision &&
    expected.intent === current.intent;
}

export function nativeDeadline<T>(operation: Promise<T>, milliseconds: number, onTimeout: () => void): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => { onTimeout(); reject(new Error("Mol* native operation timed out")); }, milliseconds);
  });
  return Promise.race([operation, deadline]).finally(() => clearTimeout(timer));
}

export function atomPickFailure(representation: string, elementLocus: boolean, size: number,
                                atomic: boolean): "representation" | "locus" | "multi" | "non_atomic" | null {
  if (representation !== "ball-and-stick") return "representation";
  if (!elementLocus) return "locus";
  if (size !== 1) return "multi";
  return atomic ? null : "non_atomic";
}

export function singleSourceSceneCompatible(comparison: boolean, measure: boolean,
                                            pending: boolean, result: boolean): boolean {
  return !comparison && !measure && !pending && !result;
}

export function atomLabel(ref: AtomRefV1, layer?: string): string {
  const residue = ref.residue;
  return `${layer ? `${layer} · ` : ""}${residue.resname} ${residue.chain_auth}/${residue.seq_auth}${residue.icode || ""}` +
    ` · ${ref.atom_name}${ref.altloc ? ` alt ${ref.altloc}` : ""} · model ${residue.model_number} · site ${ref.site_index}`;
}

export function transformPoint(result: RigidAlignment, point: number[]): [number, number, number] {
  return [0, 1, 2].map(i => result.rotation[i].reduce((sum, value, j) => sum + value * point[j], result.translation_A[i])) as [number, number, number];
}

/** Mol* Mat4 is column-major; result.rotation stores mathematical rows. */
export function alignmentMat4(result: RigidAlignment, aligned: boolean): number[] {
  if (!aligned) return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const r = result.rotation, t = result.translation_A;
  return [r[0][0], r[1][0], r[2][0], 0,
    r[0][1], r[1][1], r[2][1], 0,
    r[0][2], r[1][2], r[2][2], 0,
    t[0], t[1], t[2], 1];
}
