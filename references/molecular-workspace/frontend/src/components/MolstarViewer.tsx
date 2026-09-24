"use client";
/**
 * Mol* viewport — PLACEHOLDER until M1.
 *
 * M1 task (docs/milestones/M1.md):
 *   npm i molstar
 *   - create the plugin with `createPluginUI` inside a ref'd div (dynamic import, ssr: false)
 *   - load structures from GET /api/runs/{id}/objects?handle=... (bytes endpoint to add)
 *   - color interactions with the SAME tokens as the tables: read CSS vars at runtime
 *       getComputedStyle(document.documentElement).getPropertyValue("--int-hbond")
 *   - expose: focusResidues(refs), setRepresentation("cartoon"|"surface"|"plddt"), snapshot() -> viewer_state
 *   - selection in 3D <-> SequenceTrack selection (both directions)
 *
 * Props stay stable so the shell does not change when Mol* replaces this placeholder.
 */
import type { ResidueRef } from "@/lib/contracts";

export interface MolstarViewerProps {
  structures: { id: string; handle: string; color: string; visible: boolean }[];
  representation: "cartoon" | "surface" | "plddt";
  highlight?: ResidueRef[];
  onSelect?: (residues: ResidueRef[]) => void;
}

export function MolstarViewer({ representation }: MolstarViewerProps) {
  return (
    <svg viewBox="0 0 600 596" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" aria-label="뷰어 자리표시 (Mol*는 M1)">
      <path d="M60 470 C140 380 90 300 180 260 S300 300 320 220 S260 120 360 100 S520 160 540 90" fill="none" stroke="var(--ink-muted)" strokeWidth={10} strokeLinecap="round" opacity={0.55} />
      <path d="M80 140 C160 170 200 120 250 170 S230 330 330 360 S470 330 520 420" fill="none" stroke="var(--ink-muted)" strokeWidth={10} strokeLinecap="round" opacity={0.55} />
      <path d="M250 170 C270 200 250 250 280 280" fill="none" stroke="var(--brand)" strokeWidth={10} strokeLinecap="round" />
      <path d="M300 300 l30 -12 l24 16 l-4 30 l-30 12 l-24 -16 z" fill="none" stroke="var(--ink)" strokeWidth={3} />
      <line x1={280} y1={280} x2={300} y2={300} stroke="var(--int-hbond)" strokeWidth={2} strokeDasharray="4 3" />
      <line x1={350} y1={334} x2={372} y2={372} stroke="var(--int-metal)" strokeWidth={2} />
      <text x={20} y={580} fill="var(--ink-muted)" fontSize={12} fontFamily="var(--font-mono)">Mol* placeholder · {representation}</text>
    </svg>
  );
}
