import type { InteractionRow, InteractionType } from "@/lib/contracts";
import { ResidueId } from "./primitives";

export const INTERACTION_CLASS: Record<InteractionType, string> = {
  hbond: "mw-i-hbond mw-int--dashed", hydrophobic: "mw-i-hydrophobic", salt_bridge: "mw-i-salt",
  pi_stack: "mw-i-pi", cation_pi: "mw-i-cation", metal: "mw-i-metal", water_bridge: "mw-i-water mw-int--dashed",
};
/** The same token feeds the 3D representation: use cssVar(`int-${...}`) in the viewer. */
export const INTERACTION_TOKEN: Record<InteractionType, string> = {
  hbond: "int-hbond", hydrophobic: "int-hydrophobic", salt_bridge: "int-salt-bridge", pi_stack: "int-pi-stack",
  cation_pi: "int-cation-pi", metal: "int-metal", water_bridge: "int-water-bridge",
};

export function InteractionSwatch({ type, children }: { type: InteractionType; children?: React.ReactNode }) {
  return <span className={`mw-int ${INTERACTION_CLASS[type]}`}>{children ?? type}</span>;
}

export interface InteractionTableProps {
  rows: InteractionRow[];
  showSource?: boolean;
  total?: number;                 // n_edges from the handle summary
  onHover?: (row: InteractionRow | null) => void;
  onMaterializeMore?: () => void;
}
export function InteractionTable({ rows, showSource, total, onHover, onMaterializeMore }: InteractionTableProps) {
  return (
    <>
      <table className="mw-table">
        <thead>
          <tr><th>잔기</th><th>유형</th><th style={{ textAlign: "right" }}>거리</th>{showSource && <th>출처</th>}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} onMouseEnter={() => onHover?.(r)} onMouseLeave={() => onHover?.(null)}>
              <td><ResidueId residue={r.residue} /></td>
              <td><InteractionSwatch type={r.type} /></td>
              <td className="num">{r.distance_A.toFixed(2)} <small>Å</small></td>
              {showSource && <td className="mw-muted mw-mono">{r.engine}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {total != null && total > rows.length && (
        <div className="mw-muted" style={{ fontSize: 12, padding: "var(--space-2) var(--space-3)" }}>
          preview {rows.length} / {total} ·{" "}
          <button type="button" className="mw-btn mw-btn--sm mw-btn--ghost" onClick={onMaterializeMore}>나머지 materialize</button>
        </div>
      )}
    </>
  );
}
