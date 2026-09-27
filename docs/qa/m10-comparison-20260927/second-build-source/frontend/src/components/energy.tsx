import { Button, Eyebrow } from "./primitives";
import { FailureBadge } from "./status";
import type { ResultClass } from "@/lib/contracts";

/** Energy binning shared by bars, 3D coloring and SequenceTrack. REU, negative = stabilizing. */
export function energyToken(v: number): string {
  if (v <= -2) return "energy-favorable-strong";
  if (v <= -0.5) return "energy-favorable";
  if (v < 0.5) return "energy-neutral";
  if (v < 2) return "energy-unfavorable";
  return "energy-unfavorable-strong";
}
const verdict = (v: number) => (v <= -0.5 ? "안정" : v < 0.5 ? "중립" : "불안정");
const fmt = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2);

export interface Provenance { scorefxn: string; rosettaVersion: string; seed: number; stub?: boolean }
const provText = (p: Provenance) => `${p.scorefxn} · rosetta@${p.rosettaVersion} · seed ${p.seed}${p.stub ? " · STUB" : ""}`;

/* EnergyBreakdown ------------------------------------------------------------ */
export function EnergyBreakdown({ title, terms, total, range = 4, prov }: {
  title: string; terms: { name: string; value: number }[]; total: number; range?: number; prov: Provenance;
}) {
  const bar = (v: number, key?: string) => {
    const w = Math.min(50, (Math.abs(v) / range) * 50);
    return <span key={key} className="mw-ebar"><i style={{ left: v < 0 ? `${50 - w}%` : "50%", width: `${Math.max(w, 1)}%`, background: `var(--${energyToken(v)})` }} /></span>;
  };
  return (
    <div className="mw-stack">
      <div className="mw-row" style={{ justifyContent: "space-between" }}>
        <Eyebrow>{title}</Eyebrow><span className="mw-mono mw-muted" style={{ fontSize: 12 }}>{provText(prov)}</span>
      </div>
      <div className="mw-eterms">
        {terms.map((t) => [<span key={t.name + "k"} className="k">{t.name}</span>, bar(t.value, t.name + "b"), <span key={t.name + "v"} className="v">{fmt(t.value)}</span>])}
        <span className="k" style={{ color: "var(--ink)", fontWeight: 500 }}>total</span>{bar(total)}<span className="v">{fmt(total)}</span>
      </div>
      <span className="mw-muted" style={{ fontSize: 12 }}>REU · 막대 눈금 ±{range} REU · 0 = 가운데 선</span>
    </div>
  );
}

/* DdgTable ------------------------------------------------------------------- */
export interface DdgRow { mutation: string; ddg_REU: number; sd_REU: number; rounds_REU: number[]; iterations: number; converged?: boolean }
export function DdgTable({ rows, axis = 5, stub }: { rows: DdgRow[]; axis?: number; stub?: boolean }) {
  const pos = (x: number) => `${50 + (Math.max(-axis, Math.min(axis, x)) / axis) * 50}%`;
  return (
    <table className="mw-table">
      <thead><tr><th>mutation</th><th style={{ textAlign: "right" }}>ΔΔG REU</th><th>rounds (−{axis} … +{axis})</th><th>판정</th><th>iter</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.mutation}>
            <td className="mw-mono">{r.mutation}{stub && <span className="mw-muted"> · stub</span>}</td>
            <td className="num">{fmt(r.ddg_REU)} <small>±{r.sd_REU.toFixed(2)}</small></td>
            <td style={{ width: 180 }}><div className="mw-dots">{r.rounds_REU.map((x, i) => <i key={i} style={{ left: pos(x) }} />)}<b style={{ left: pos(r.ddg_REU) }} /></div></td>
            <td><span className="mw-sign" style={{ color: `var(--${energyToken(r.ddg_REU)})` }}><span style={{ color: "var(--ink)" }}>{verdict(r.ddg_REU)}</span></span></td>
            <td className="mw-muted mw-mono">{r.rounds_REU.length}/{r.iterations}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* InterfaceScorecard --------------------------------------------------------- */
export interface InterfaceScores { dG_separated: number; dSASA_int: number; dG_dSASA_x100: number; packstat: number; delta_unsatHbonds: number; hbonds_int: number }
export function InterfaceScorecard({ s, thresholds = { delta_unsatHbonds: 3 } }: { s: InterfaceScores; thresholds?: { delta_unsatHbonds: number } }) {
  const cells: [string, string, string | null, string, boolean][] = [
    ["dG_separated", s.dG_separated.toFixed(1), "REU", "분리 시 에너지 변화", false],
    ["dSASA_int", Math.round(s.dSASA_int).toLocaleString(), "Å²", "인터페이스 매몰 면적", false],
    ["dG/dSASA ×100", s.dG_dSASA_x100.toFixed(2), null, "면적당 결합 에너지", false],
    ["packstat", s.packstat.toFixed(2), null, "0 나쁨 · 1 완벽", false],
    ["delta_unsatHbonds", String(s.delta_unsatHbonds), null, "매몰된 불만족 H-bond", s.delta_unsatHbonds > thresholds.delta_unsatHbonds],
    ["hbonds_int", String(s.hbonds_int), null, "인터페이스 H-bond", false],
  ];
  return (
    <div className="mw-scorecard">
      {cells.map(([k, v, u, n, flag]) => (
        <div key={k} className="mw-metric">
          <span className="mw-metric__k">{k}</span>
          <span className="mw-metric__v" style={flag ? { color: "var(--fail-input)" } : undefined}>{v}{u && <small>{u}</small>}</span>
          <span className="mw-metric__n">{n}</span>
        </div>
      ))}
    </div>
  );
}

/* JobQueue ------------------------------------------------------------------- */
export interface Job { id: string; protocol: string; status: "queued" | "running" | "done" | "failed"; progress?: number; elapsed?: string; seed: number; worker?: string; failure?: ResultClass; failureText?: string }
export function JobQueue({ jobs, onKill }: { jobs: Job[]; onKill?: (id: string) => void }) {
  return (
    <table className="mw-jobs">
      <thead><tr><th>job</th><th>protocol</th><th>진행</th><th>seed</th><th>worker</th><th /></tr></thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id}>
            <td>{j.id}</td><td>{j.protocol}</td>
            <td>
              {j.status === "running" && <><span className="mw-bar"><i style={{ width: `${(j.progress ?? 0) * 100}%` }} /></span>{j.elapsed}</>}
              {j.status === "queued" && <><span className="mw-bar"><i style={{ width: 0 }} /></span>queued</>}
              {j.status === "done" && <><span className="mw-s-done">✓</span> {j.elapsed}</>}
              {j.status === "failed" && j.failure && <FailureBadge cls={j.failure} short={j.failureText} />}
            </td>
            <td className="m">{j.seed}</td><td className="m">{j.worker ?? "—"}</td>
            <td>{(j.status === "running" || j.status === "queued") && <Button size="sm" variant="ghost" onClick={() => onKill?.(j.id)}>{j.status === "running" ? "kill" : "취소"}</Button>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
