import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Handle, ResidueRef } from "@/lib/contracts";
import { residueUid } from "@/lib/contracts";

/* Button ------------------------------------------------------------------ */
export type ButtonVariant = "default" | "primary" | "ghost" | "stop";
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
}
export function Button({ variant = "default", size = "md", className = "", ...rest }: ButtonProps) {
  const cls = ["mw-btn", variant !== "default" && `mw-btn--${variant}`, size === "sm" && "mw-btn--sm", className]
    .filter(Boolean).join(" ");
  return <button type="button" className={cls} {...rest} />;
}

export const Kbd = ({ children }: { children: ReactNode }) => <span className="mw-kbd">{children}</span>;
export const Eyebrow = ({ children }: { children: ReactNode }) => <span className="mw-eyebrow">{children}</span>;

/* Segmented --------------------------------------------------------------- */
export interface SegmentedOption<T extends string> { value: T; label?: string; dotColor?: string }
export interface SegmentedProps<T extends string> {
  label: string; options: SegmentedOption<T>[]; value: T; onChange?: (v: T) => void;
}
export function Segmented<T extends string>({ label, options, value, onChange }: SegmentedProps<T>) {
  return (
    <div className="mw-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} onClick={() => onChange?.(o.value)}>
          {o.dotColor && <span className="mw-dot" style={{ color: o.dotColor }} />}
          {o.label ?? o.value}
        </button>
      ))}
    </div>
  );
}

/* HandleChip -------------------------------------------------------------- */
/** Short display of a handle: kind | obj://<run>/<sha4…sha2> | @schema. Full string on title + copy. */
export function shortSha(h: string) {
  const sha = h.split("/").pop() ?? "";
  return sha.length > 8 ? `${sha.slice(0, 4)}…${sha.slice(-2)}` : sha;
}
export interface HandleChipProps {
  handle: Pick<Handle, "handle" | "kind"> & { schema?: string };
  label?: string;             // override the ref part (e.g. "step #03")
  onOpen?: (handle: string) => void;
}
export function HandleChip({ handle, label, onOpen }: HandleChipProps) {
  const run = handle.handle.replace("obj://", "").split("/")[0];
  const ver = handle.schema?.split("@")[1];
  return (
    <span className="mw-handle" title={handle.handle} role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined} onClick={() => onOpen?.(handle.handle)}>
      <span className="mw-handle__kind">{handle.kind}</span>
      <span className="mw-handle__ref">{label ?? <>obj://{run.replace(/^run_\d+_/, "run_")}/<b>{shortSha(handle.handle)}</b></>}</span>
      {ver && <span className="mw-handle__schema">@{ver}</span>}
    </span>
  );
}

/* ResidueId --------------------------------------------------------------- */
export function ResidueId({ residue, showLabel = false }: { residue: ResidueRef; showLabel?: boolean }) {
  const differs = (residue.chain_label != null && residue.chain_label !== residue.chain_auth) || (residue.seq_label != null && residue.seq_label !== residue.seq_auth);
  return (
    <span className="mw-res">
      <span className="mw-res__name">{residue.resname}</span>
      {residueUid(residue)}
      {(showLabel || differs) && residue.seq_label != null && (
        <span className="mw-res__label">label {residue.chain_label}·{residue.seq_label}</span>
      )}
    </span>
  );
}
