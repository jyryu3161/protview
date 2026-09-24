import type { ReportArtifact, SavedReportRef } from "./api";

export function reportSelectionKey(runId: string | null | undefined, interactionHandle: string | null | undefined): string | null {
  return runId && interactionHandle ? JSON.stringify([runId, interactionHandle]) : null;
}

export function savedForSelection(reports: SavedReportRef[], interactionHandle: string | null | undefined): SavedReportRef | undefined {
  return interactionHandle ? reports.filter(item => item.interaction_handle === interactionHandle).at(-1) : undefined;
}

export function responseMatchesSelection(expectedKey: string, currentKey: string | null,
                                         runId: string, interactionHandle: string,
                                         artifact: ReportArtifact): boolean {
  return expectedKey === currentKey && expectedKey === reportSelectionKey(runId, interactionHandle) &&
    artifact.manifest.interaction_handle === interactionHandle;
}
