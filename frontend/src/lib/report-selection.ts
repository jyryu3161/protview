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

export function savedMethodForSelection(reports: SavedReportRef[], resultHandle: string | null | undefined): SavedReportRef | undefined {
  return resultHandle ? reports.filter(item => item.analysis_type === "interface_sasa" && item.result_handle === resultHandle).at(-1) : undefined;
}

export function responseMatchesMethodSelection(expectedKey: string, currentKey: string | null,
                                               runId: string, resultHandle: string,
                                               artifact: { manifest: { schema: string; analysis_type: string; result_handle: string } }): boolean {
  return expectedKey === currentKey && expectedKey === reportSelectionKey(runId, resultHandle) &&
    artifact.manifest.schema === "method_report_manifest@1" && artifact.manifest.analysis_type === "interface_sasa" &&
    artifact.manifest.result_handle === resultHandle;
}

export function savedOpenmmForSelection(reports: SavedReportRef[], resultHandle: string | null | undefined): SavedReportRef | undefined {
  return resultHandle ? reports.filter(item => item.analysis_type === "openmm_protein_minimize" && item.result_handle === resultHandle).at(-1) : undefined;
}

export function responseMatchesOpenmmSelection(expectedKey: string, currentKey: string | null,
                                               runId: string, resultHandle: string,
                                               artifact: { manifest: { schema: string; analysis_type: string; result_handle: string } }): boolean {
  return expectedKey === currentKey && expectedKey === reportSelectionKey(runId, resultHandle) &&
    artifact.manifest.schema === "method_report_manifest@1" && artifact.manifest.analysis_type === "openmm_protein_minimize" &&
    artifact.manifest.result_handle === resultHandle;
}
