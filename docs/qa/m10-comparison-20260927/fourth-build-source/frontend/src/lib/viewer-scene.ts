import type { ViewerCommand, ViewerSession, ViewerRepresentationValue } from "./viewer-agent";

/** Keep the visible outbound preview in step with the server's scene mutation. */
export function withViewerSceneUpdate(session: ViewerSession, update: {
  representation: ViewerRepresentationValue; selected_alias: string | null; action_revision: number;
}): ViewerSession {
  return { ...session, ...update, projection: { ...session.projection,
    representation: update.representation, selected_target: update.selected_alias } };
}

/** Guard the browser side before any async Mol* command starts. */
export function commandTargetsCurrentScene(command: ViewerCommand, session: ViewerSession,
  observed: { ready: boolean; sourceHandle: string | null; sessionId: string | null; generation: number | null }): boolean {
  return observed.ready && command.schema === "viewer_plan@1" &&
    command.viewer_session_id === session.viewer_session_id &&
    command.client_instance_id === session.client_instance_id &&
    command.scene_generation === session.scene_generation &&
    command.structure_handle === session.structure_handle &&
    command.catalog_hash === session.catalog_hash &&
    command.action_revision === session.action_revision &&
    observed.sessionId === session.viewer_session_id &&
    observed.generation === session.scene_generation &&
    observed.sourceHandle === session.structure_handle;
}

/** Source and catalog-scope changes share one monotonically increasing client generation. */
export function advanceSceneGeneration(previous: { key: string | null; generation: number },
  nextKey: string | null): { key: string | null; generation: number } {
  return previous.key === nextKey ? previous : { key: nextKey, generation: previous.generation + 1 };
}

export function cameraChanged(before: { position: number[]; target: number[]; radius: number; distance: number },
  after: { position: number[]; target: number[]; radius: number; distance: number }): boolean {
  return Math.abs(after.distance - before.distance) > 1e-4 ||
    Math.abs(after.radius - before.radius) > 1e-4 ||
    after.target.some((value, index) => Math.abs(value - before.target[index]) > 1e-4) ||
    after.position.some((value, index) => Math.abs(value - before.position[index]) > 1e-4);
}

export function viewerPromptAllowed(value: string, onlineEnabled: boolean, dryRun: boolean): boolean {
  if (!value.trim() || value.length > 512 || new TextEncoder().encode(value).length > 2048) return false;
  if ([...value].some(char => (char.charCodeAt(0) < 32 && !"\t\n\r".includes(char)) ||
    (char.charCodeAt(0) >= 127 && char.charCodeAt(0) < 160))) return false;
  return value.trim().startsWith("/") || onlineEnabled && !dryRun;
}
