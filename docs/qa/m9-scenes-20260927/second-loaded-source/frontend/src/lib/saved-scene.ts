import type { ResidueRef } from "./contracts";
import type { ViewerRepresentationValue } from "./viewer-agent";

/** Exact Mol* 5.11 camera snapshot fields admitted by the M9 server. */
export interface NativeCameraState {
  mode: "perspective" | "orthographic";
  fov: number;
  position: number[];
  up: number[];
  target: number[];
  radius: number;
  radiusMax: number;
  fog: number;
  clipFar: boolean;
  minNear: number;
  minFar: number;
}

export interface NativeSceneState {
  structure_handle: string;
  selection: ResidueRef | null;
  representation: ViewerRepresentationValue;
  camera: NativeCameraState;
  theme: "dark" | "light";
}

export interface SavedScene extends NativeSceneState {
  schema: "viewer_scene@1";
  name: string;
  structure_kind: "structure" | "prepared_structure" | "openmm_minimized_structure";
  structure_schema: string;
  model_number: number;
  renderer: { name: "molstar"; version: "5.11.0"; scene_schema: "protview_scene@1" };
}
export interface SavedSceneDetail { handle: string; value: SavedScene }
export interface SavedFigure {
  schema: "viewer_figure@1";
  scene_handle: string;
  structure_handle: string;
  model_number: number;
  png_handle: string;
  png_sha256: string;
  width: number;
  height: number;
  media_type: "image/png";
  capture_method: "molstar_image_pass";
  provenance: "client_rendered_local_view";
  limitations: string;
  renderer: SavedScene["renderer"];
}
export interface SavedFigureDetail { handle: string; value: SavedFigure }
export interface SavedPage<T> { rows: T[]; total: number; offset: number; limit: number }

export interface SceneBindingIdentity {
  sessionId: string; clientId: string; generation: number; sourceHandle: string;
  catalogHash: string; actionRevision: number;
}
export function bindingMatches(actual: SceneBindingIdentity | null, expected: SceneBindingIdentity): boolean {
  return !!actual && actual.sessionId === expected.sessionId && actual.clientId === expected.clientId &&
    actual.generation === expected.generation && actual.sourceHandle === expected.sourceHandle &&
    actual.catalogHash === expected.catalogHash && actual.actionRevision === expected.actionRevision;
}

export function cameraMatches(actual: NativeCameraState, expected: NativeCameraState): boolean {
  if (actual.mode !== expected.mode || actual.clipFar !== expected.clipFar) return false;
  for (const key of ["fov", "radius", "radiusMax", "fog", "minNear", "minFar"] as const) {
    const a = actual[key], e = expected[key];
    const tolerance = key === "fov" || key === "fog" ? 1e-6 : Math.max(1e-4, Math.abs(e) * 1e-6);
    if (!Number.isFinite(a) || Math.abs(a - e) > tolerance) return false;
  }
  for (const key of ["position", "up", "target"] as const) {
    if (actual[key].length !== 3 || expected[key].length !== 3) return false;
    for (let i = 0; i < 3; i += 1) {
      const e = expected[key][i], a = actual[key][i];
      const tolerance = key === "up" ? 1e-6 : Math.max(1e-4, Math.abs(e) * 1e-6);
      if (!Number.isFinite(a) || Math.abs(a - e) > tolerance) return false;
    }
  }
  return true;
}

export function sameResidue(a: ResidueRef | null, b: ResidueRef | null): boolean {
  if (a === null || b === null) return a === b;
  return a.model_number === b.model_number && a.chain_auth === b.chain_auth && a.seq_auth === b.seq_auth &&
    (a.icode ?? "") === (b.icode ?? "") && a.resname === b.resname &&
    (a.chain_label ?? null) === (b.chain_label ?? null) && (a.seq_label ?? null) === (b.seq_label ?? null);
}

export function sceneMatches(actual: NativeSceneState, expected: NativeSceneState): boolean {
  return actual.structure_handle === expected.structure_handle &&
    actual.representation === expected.representation && actual.theme === expected.theme &&
    sameResidue(actual.selection, expected.selection) && cameraMatches(actual.camera, expected.camera);
}
