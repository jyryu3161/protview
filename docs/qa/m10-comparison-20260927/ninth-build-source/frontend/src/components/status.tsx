import type { CostClass, DecisionSource, ResultClass, StepState } from "@/lib/contracts";

export const FAILURE_GLYPH: Record<ResultClass, string> = {
  transient: "↻", input_invalid: "✎", precondition: "⇢", resource_exceeded: "⊘", scientific_null: "∅", fatal: "■",
};
const FAILURE_CLS: Record<ResultClass, string> = {
  transient: "mw-f-transient", input_invalid: "mw-f-input", precondition: "mw-f-precondition",
  resource_exceeded: "mw-f-resource", scientific_null: "mw-f-null", fatal: "mw-f-fatal",
};

/** Failure class badge. scientific_null is a RESULT: neutral, dashed, never a warning color. */
export function FailureBadge({ cls, retry, short }: { cls: ResultClass; retry?: [number, number]; short?: string }) {
  return (
    <span className={`mw-badge ${FAILURE_CLS[cls]}`}>
      <span className="mw-badge__g">{FAILURE_GLYPH[cls]}</span>
      {short ?? cls}{retry && ` ${retry[0]}/${retry[1]}`}
    </span>
  );
}

export const DECISION_GLYPH: Record<DecisionSource, string> = { rule: "≡", jev: "◆", frontier: "✦", human: "●" };
export function DecisionTag({ source, label, modelPin }: { source: DecisionSource; label?: string; modelPin?: string }) {
  return (
    <span className={`mw-badge mw-p-${source}`} title={modelPin}>
      <span className="mw-badge__g">{DECISION_GLYPH[source]}</span>{label ?? source}
    </span>
  );
}

export const STEP_GLYPH: Record<StepState, string> = { pending: "○", running: "◐", done: "✓", failed: "✕" };

export function CostMark({ cost, text }: { cost: CostClass; text?: string }) {
  if (cost === "cheap" && !text) return null;
  return <span className={`mw-cost${cost === "expensive" ? " mw-cost--expensive" : ""}`}>{text ?? (cost === "expensive" ? "$$$" : "$$")}</span>;
}
