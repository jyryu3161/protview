"use client";
import { useRef, useState } from "react";
import { Button, Eyebrow } from "./primitives";

/* ModelPanel ----------------------------------------------------------------- */
export interface ModelItem {
  id: string;                  // "#1", "#2.1" — same as CommandBar short refs; never reused in a session
  name: string;
  handle: string;
  color: "model-a" | "model-b" | "model-c" | "model-d";
  visible: boolean;
  meta?: string;
  child?: boolean;
}
export function ModelPanel({ models, selected, onSelect, onToggle }: {
  models: ModelItem[]; selected?: string; onSelect?: (id: string) => void; onToggle?: (id: string) => void;
}) {
  return (
    <ul className="mw-models">
      {models.map((m) => (
        <li key={m.id} className={`mw-model${m.child ? " mw-model--child" : ""}`} aria-selected={m.id === selected} onClick={() => onSelect?.(m.id)}>
          <button type="button" className="mw-model__eye" aria-label={m.visible ? "숨기기" : "보이기"} style={{ background: "none", border: 0, padding: 0, cursor: "pointer" }}
            onClick={(e) => { e.stopPropagation(); onToggle?.(m.id); }}>{m.visible ? "●" : "○"}</button>
          <span className="mw-model__sw" style={{ background: `var(--${m.color})` }} />
          <span className="mw-model__id">{m.id}</span>
          <span className="mw-model__name">{m.name}</span>
          <span className="mw-model__meta">{m.meta}</span>
        </li>
      ))}
    </ul>
  );
}

/* SequenceTrack -------------------------------------------------------------- */
export type MaskState = "design" | "repack" | "fixed";
export type TrackBin = "vh" | "c" | "l" | "vl" | "fs" | "f" | "n" | "u" | "us" | null;
export interface SequenceTrackProps {
  label: string;               // "#2 A"
  startAuth: number;           // auth number of the first residue shown
  sequence: string;            // display only — never sent through egress
  selected?: Set<number>;      // indices
  mask?: MaskState[];
  tracks?: { name: string; kind: "plddt" | "energy"; bins: TrackBin[] }[];
  onSelect?: (indices: number[]) => void;
  onMaskChange?: (mask: MaskState[]) => void;   // emits a new design_mask via define_mutations upstream
  paintWith?: MaskState;
}
const MASK_CLS: Record<MaskState, string> = { design: "m-d", repack: "m-r", fixed: "m-f" };
const BIN_CLS: Record<string, string> = { vh: "p-vh", c: "p-c", l: "p-l", vl: "p-vl", fs: "e-fs", f: "e-f", n: "e-n", u: "e-u", us: "e-us" };

export function SequenceTrack(p: SequenceTrackProps) {
  const drag = useRef<{ from: number; target: "seq" | "mask" } | null>(null);
  const [preview, setPreview] = useState<[number, number] | null>(null);
  const seq = p.sequence.split("");
  const inRange = (i: number) => preview && i >= Math.min(...preview) && i <= Math.max(...preview);
  const end = (i: number) => {
    if (!drag.current) return;
    const a = Math.min(drag.current.from, i), b = Math.max(drag.current.from, i);
    const idx = Array.from({ length: b - a + 1 }, (_, k) => a + k);
    if (drag.current.target === "seq") p.onSelect?.(idx);
    else if (p.mask && p.paintWith) p.onMaskChange?.(p.mask.map((m, k) => (idx.includes(k) ? p.paintWith! : m)));
    drag.current = null; setPreview(null);
  };
  const cellHandlers = (i: number, target: "seq" | "mask") => ({
    onMouseDown: () => { drag.current = { from: i, target }; setPreview([i, i]); },
    onMouseEnter: () => drag.current && setPreview([drag.current.from, i]),
    onMouseUp: () => end(i),
  });
  return (
    <div className="mw-seq" onMouseLeave={() => { drag.current = null; setPreview(null); }}>
      <div className="mw-seq__row"><span className="mw-seq__lab">{p.label.split(" ").pop()}</span>
        <span className="mw-seq__cells mw-seq__ruler">{seq.map((_, i) => <span key={i}>{(p.startAuth + i) % 10 === 0 ? p.startAuth + i : ""}</span>)}</span></div>
      <div className="mw-seq__row"><span className="mw-seq__lab">{p.label}</span>
        <span className="mw-seq__cells mw-seq__aa">{seq.map((c, i) => (
          <span key={i} className={p.selected?.has(i) || (drag.current?.target === "seq" && inRange(i)) ? "sel" : c === "-" ? "gap" : ""} {...cellHandlers(i, "seq")}>{c}</span>
        ))}</span></div>
      {p.mask && (
        <div className="mw-seq__row"><span className="mw-seq__lab">design</span>
          <span className="mw-seq__cells">{seq.map((c, i) => (
            <span key={i} className={MASK_CLS[drag.current?.target === "mask" && inRange(i) && p.paintWith ? p.paintWith : p.mask![i]]} {...cellHandlers(i, "mask")}>{c}</span>
          ))}</span></div>
      )}
      {p.tracks?.map((t) => (
        <div key={t.name} className="mw-seq__row"><span className="mw-seq__lab">{t.name}</span>
          <span className="mw-seq__cells mw-seq__track">{t.bins.map((b, i) => <span key={i} className={b ? BIN_CLS[b] : ""} />)}</span></div>
      ))}
    </div>
  );
}

/* PAEPlot -------------------------------------------------------------------- */
export interface PAEPlotProps {
  title: string;
  matrix: number[][];          // downsampled PAE in Å (materialize with projection)
  dividers?: number[];         // chain/domain boundaries (indices)
  cell?: number;
  domainsText?: string;
  onSelectRegion?: (r: { i0: number; i1: number; j0: number; j1: number; mean: number }) => void;
  onColorDomains?: () => void;
  onContacts?: () => void;
}
const paeBin = (v: number) => (v < 5 ? 0 : v < 10 ? 1 : v < 15 ? 2 : v < 25 ? 3 : 4);
export function PAEPlot({ title, matrix, dividers = [], cell = 7, domainsText, onSelectRegion, onColorDomains, onContacts }: PAEPlotProps) {
  const n = matrix.length, size = n * cell;
  const [sel, setSel] = useState<{ i0: number; j0: number; i1: number; j1: number } | null>(null);
  const [start, setStart] = useState<[number, number] | null>(null);
  const at = (e: React.MouseEvent<SVGSVGElement>): [number, number] => {
    const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    return [Math.min(n - 1, Math.max(0, Math.floor((e.clientY - r.top) / cell))), Math.min(n - 1, Math.max(0, Math.floor((e.clientX - r.left) / cell)))];
  };
  const mean = sel ? (() => { let s = 0, c = 0; for (let i = Math.min(sel.i0, sel.i1); i <= Math.max(sel.i0, sel.i1); i++) for (let j = Math.min(sel.j0, sel.j1); j <= Math.max(sel.j0, sel.j1); j++) { s += matrix[i][j]; c++; } return s / c; })() : null;
  return (
    <div className="mw-pae">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-label="PAE 행렬"
        onMouseDown={(e) => { const p = at(e); setStart(p); setSel({ i0: p[0], j0: p[1], i1: p[0], j1: p[1] }); }}
        onMouseMove={(e) => { if (start) { const p = at(e); setSel({ i0: start[0], j0: start[1], i1: p[0], j1: p[1] }); } }}
        onMouseUp={() => { if (sel && mean != null) onSelectRegion?.({ i0: Math.min(sel.i0, sel.i1), i1: Math.max(sel.i0, sel.i1), j0: Math.min(sel.j0, sel.j1), j1: Math.max(sel.j0, sel.j1), mean }); setStart(null); }}>
        {matrix.map((row, i) => row.map((v, j) => <rect key={`${i}-${j}`} className={`pae${paeBin(v)}`} x={j * cell} y={i * cell} width={cell} height={cell} />))}
        {dividers.map((d) => <g key={d}><line className="mw-pae__div" x1={d * cell} y1={0} x2={d * cell} y2={size} /><line className="mw-pae__div" x1={0} y1={d * cell} x2={size} y2={d * cell} /></g>)}
        {sel && <rect className="mw-pae__sel" x={Math.min(sel.j0, sel.j1) * cell} y={Math.min(sel.i0, sel.i1) * cell} width={(Math.abs(sel.j1 - sel.j0) + 1) * cell} height={(Math.abs(sel.i1 - sel.i0) + 1) * cell} />}
      </svg>
      <div className="mw-stack">
        <Eyebrow>PAE · {title}</Eyebrow>
        <ScaleLegend kind="pae" />
        <dl className="mw-kv">
          {domainsText && <><dt>domains</dt><dd>{domainsText}</dd></>}
          {mean != null && <><dt>selection</dt><dd>mean {mean.toFixed(1)} Å</dd></>}
        </dl>
        <div className="mw-row"><Button size="sm" onClick={onColorDomains}>도메인으로 채색</Button><Button size="sm" onClick={onContacts}>선택 영역 contacts</Button></div>
      </div>
    </div>
  );
}

/* ScaleLegend ---------------------------------------------------------------- */
const SCALES = {
  energy: { tokens: ["energy-favorable-strong", "energy-favorable", "energy-neutral", "energy-unfavorable", "energy-unfavorable-strong"], ticks: ["≤−2 안정화", "0", "불안정화 ≥+2"] },
  pae: { tokens: ["pae-0", "pae-1", "pae-2", "pae-3", "pae-4"], ticks: ["0", "10", "25+ Å"] },
  plddt: { tokens: ["plddt-very-low", "plddt-low", "plddt-confident", "plddt-very-high"], ticks: ["<50", "70", ">90"] },
} as const;
export function ScaleLegend({ kind, title, note }: { kind: keyof typeof SCALES; title?: string; note?: string }) {
  const s = SCALES[kind];
  return (
    <div className="mw-stack" style={{ maxWidth: 280, gap: "var(--space-1)" }}>
      {title && <Eyebrow>{title}</Eyebrow>}
      <div className="mw-scale">
        <div className="mw-scale__bar">{s.tokens.map((t) => <i key={t} style={{ background: `var(--${t})`, boxShadow: t === "pae-4" ? "inset 0 0 0 1px var(--line)" : undefined }} />)}</div>
        <div className="mw-scale__ticks">{s.ticks.map((t) => <span key={t}>{t}</span>)}</div>
      </div>
      {note && <span className="mw-muted" style={{ fontSize: 12 }}>{note}</span>}
    </div>
  );
}
