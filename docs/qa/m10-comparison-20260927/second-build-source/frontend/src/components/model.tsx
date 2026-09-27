import type { DecisionSource } from "@/lib/contracts";
import { Button, Eyebrow } from "./primitives";
import { DecisionTag } from "./status";

/* PromptInspector ------------------------------------------------------------ */
export interface PromptPart { name: string; tokens: number }
export interface PromptInspectorProps {
  role: "jev.decide" | "frontier.plan" | "frontier.explain" | "repair";
  promptRef: string;            // "frontier.plan@0.1"
  promptSha: string;
  parts: PromptPart[];
  responseFormat?: string;
  cache?: { hit: boolean; key: string };
  blocked?: string[];           // egress blocked field names
  onShowFull?: () => void; onDiff?: () => void; onSaveFixture?: () => void;
}
export function PromptInspector(p: PromptInspectorProps) {
  const total = p.parts.reduce((a, b) => a + b.tokens, 0);
  const source: DecisionSource = p.role.startsWith("jev") ? "jev" : "frontier";
  return (
    <div className="mw-prompt">
      <div className="mw-row" style={{ justifyContent: "space-between" }}>
        <span className="mw-row">
          <DecisionTag source={source} label={p.role} />
          <span className="mw-mono mw-muted" style={{ fontSize: 12 }}>prompt {p.promptRef} · {p.promptSha}</span>
        </span>
        <span className="mw-mono" style={{ fontSize: 12 }}>{total.toLocaleString()} tok</span>
      </div>
      <div className="mw-parts">
        {p.parts.map((x) => [
          <span key={x.name + "k"} className="k">{x.name}</span>,
          <span key={x.name + "b"} className="mw-bar"><i style={{ width: `${(x.tokens / Math.max(1, total)) * 100}%` }} /></span>,
          <span key={x.name + "v"} className="v">{x.tokens.toLocaleString()}</span>,
        ])}
      </div>
      <dl className="mw-kv">
        {p.responseFormat && <><dt>response_format</dt><dd>{p.responseFormat}</dd></>}
        {p.cache && <><dt>cache</dt><dd>{p.cache.hit ? "hit" : "miss"} · key {p.cache.key}</dd></>}
        {p.blocked && <><dt>egress</dt><dd>{p.blocked.map((b) => `${b} ✕`).join(" · ")}</dd></>}
      </dl>
      <div className="mw-row">
        <Button size="sm" onClick={p.onShowFull}>전문 보기</Button>
        <Button size="sm" onClick={p.onDiff}>이전 버전과 diff</Button>
        <Button size="sm" variant="ghost" onClick={p.onSaveFixture}>픽스처로 저장</Button>
      </div>
    </div>
  );
}

/* ModelRoute ----------------------------------------------------------------- */
export interface ModelRouteProps {
  role: "jev" | "frontier";
  model: string;
  pinned: boolean;
  keyStatus: { ok: boolean; where: string };
  policy: { data_collection: string; zdr: boolean; require_parameters: boolean; allow_fallbacks: boolean };
  stats?: { label: string; value: string }[];
  servedMismatch?: { callId: string; served: string };
}
export function ModelRoute(p: ModelRouteProps) {
  const flags: [string, boolean][] = [
    [`data_collection: ${p.policy.data_collection}`, p.policy.data_collection === "deny"],
    [`zdr: ${p.policy.zdr}`, p.policy.zdr],
    ["require_parameters", p.policy.require_parameters],
    ["allow_fallbacks", p.policy.allow_fallbacks],
  ];
  return (
    <div className="mw-route">
      <div className="mw-route__head">
        <DecisionTag source={p.role} />
        <span className="mw-route__pin">{p.model}</span>
        {p.pinned && <span className="mw-muted mw-mono" style={{ fontSize: 12 }}>pinned</span>}
        <span style={{ flex: 1 }} />
        <span className="mw-row mw-mono" style={{ fontSize: 12, gap: "var(--space-1)" }}>
          <span className="mw-dot" style={{ color: p.keyStatus.ok ? "var(--state-done)" : "var(--fail-fatal)" }} />
          key · {p.keyStatus.where}
        </span>
      </div>
      <div className="mw-route__body">
        <div className="mw-stack" style={{ gap: "var(--space-1)" }}>
          <Eyebrow>provider policy</Eyebrow>
          {flags.map(([t, on]) => <span key={t} className={`mw-flag${on ? "" : " mw-flag--off"}`}>{t}</span>)}
        </div>
        {p.stats && (
          <div className="mw-stack" style={{ gap: "var(--space-1)" }}>
            <Eyebrow>recent calls</Eyebrow>
            <dl className="mw-kv">{p.stats.map((s) => [<dt key={s.label + "k"}>{s.label}</dt>, <dd key={s.label + "v"}>{s.value}</dd>])}</dl>
          </div>
        )}
      </div>
      {p.servedMismatch && (
        <p className="mw-route__notice"><b>served ≠ pin</b> · {p.servedMismatch.callId}은 <span className="mw-mono">{p.servedMismatch.served}</span>가 응답했습니다. 이 결정은 벤치마크에서 제외됩니다.</p>
      )}
    </div>
  );
}

/* ExplainPanel --------------------------------------------------------------- */
export interface ExplainSentence { text: string; cite?: string; dropped?: { actual: string } }
export function ExplainPanel({ sentences, streaming }: { sentences: ExplainSentence[]; streaming?: boolean }) {
  const kept = sentences.filter((s) => !s.dropped).length;
  return (
    <div className="mw-explain">
      <div className="mw-row">
        <DecisionTag source="frontier" label="frontier.explain" />
        <span className="mw-muted mw-mono" style={{ fontSize: 12 }}>verified {kept} / {sentences.length} sentences</span>
      </div>
      {sentences.map((s, i) => (
        <p key={i}>
          {s.dropped
            ? <><span className="mw-dropped">{s.text}</span><span className="mw-dropped__tag">dropped · 핸들 값 {s.dropped.actual}</span></>
            : <>{s.text}{s.cite && <span className="mw-cite">{s.cite}</span>}</>}
          {streaming && i === sentences.length - 1 && <span className="mw-stream" />}
        </p>
      ))}
    </div>
  );
}
