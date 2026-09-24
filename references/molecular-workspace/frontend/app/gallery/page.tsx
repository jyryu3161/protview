"use client";
import type { ReactNode } from "react";
import {
  ApprovalGate, BudgetMeter, Button, CommandBar, DdgTable, DecisionTag, EgressGateView, EnergyBreakdown,
  ExplainPanel, FailureBadge, GoalComposer, HandleChip, InteractionTable, InterfaceScorecard, JobQueue,
  ModelPanel, ModelRoute, PAEPlot, PromptInspector, ResidueId, ScaleLegend, Segmented, SequenceTrack,
  StepList, ToolErrorCard,
} from "@/components";
import * as mock from "@/mock/run";

function Card({ name, children, width = 640 }: { name: string; children: ReactNode; width?: number }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <span className="mw-eyebrow">{name}</span>
      <div style={{ background: "var(--surface-100)", border: "1px solid var(--line)", borderRadius: "var(--radius-md)", padding: "var(--space-4)", maxWidth: width }}>{children}</div>
    </section>
  );
}

/** Every component with representative props. The visual contract is design/previews/*.html. */
export default function Gallery() {
  return (
    <div className="mw-root" style={{ background: "var(--surface-000)", minHeight: "100vh", padding: "var(--space-5)", display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
      <div className="mw-row"><h1 className="t-display" style={{ margin: 0 }}>Component gallery</h1><span style={{ flex: 1 }} />
        <Button onClick={() => { const r = document.documentElement; r.dataset.theme = r.dataset.theme === "dark" ? "light" : "dark"; }}>테마 전환</Button></div>
      <Card name="Button · Segmented"><div className="mw-row"><Button variant="primary">▶ 파이프라인 실행</Button><Button>드라이런</Button><Button variant="ghost">스냅샷</Button><Button variant="stop">■ 중단</Button>
        <Segmented label="egress" value="local_only" options={[{ value: "online", dotColor: "var(--egress-online)" }, { value: "local_only", dotColor: "var(--egress-local)" }, { value: "dry_run" }]} /></div></Card>
      <Card name="HandleChip · ResidueId"><div className="mw-row"><HandleChip handle={mock.handles.interactions} /><ResidueId residue={mock.interactions[0].residue} /></div></Card>
      <Card name="FailureBadge · DecisionTag"><div className="mw-row">
        {(["transient", "input_invalid", "precondition", "resource_exceeded", "scientific_null", "fatal"] as const).map((c) => <FailureBadge key={c} cls={c} />)}
        {(["rule", "jev", "frontier", "human"] as const).map((s) => <DecisionTag key={s} source={s} />)}</div></Card>
      <Card name="StepRow" width={420}><StepList steps={mock.steps} selected={3} /></Card>
      <Card name="BudgetMeter" width={360}><BudgetMeter budget={mock.budget} /></Card>
      <Card name="ApprovalGate" width={480}><ApprovalGate gate="expensive_first_call" question="relax_structure를 실행할까요?" why="예상 3분, expensive 예산 6/8 사용 중." plan={["relax_structure   structure 7a10…e2", "estimate_stability  mutations 3건"]} planSource="jev" onDryRun={() => {}} /></Card>
      <Card name="ToolError"><ToolErrorCard tool="estimate_stability" message="energy_table은 relax된 구조가 필요합니다." cls="precondition" fix={{ tool: "relax_structure", args: { structure: mock.handles.prepared.handle } }} /></Card>
      <Card name="EgressGate"><EgressGateView mode="online" destination="OpenRouter → frontier" tokens={3812} logRef="#0031" fields={[{ name: "compact_state", blocked: false }, { name: "coords", blocked: true }, { name: "sequence", blocked: true }]} /></Card>
      <Card name="InteractionTable"><InteractionTable rows={mock.interactions} showSource total={47} /></Card>
      <Card name="GoalComposer"><GoalComposer context={[{ ...mock.handles.structure, label: "#1 · 7XYZ" }, { ...mock.handles.selection, label: "pocket P1 · 14 res" }]} estimateTokens={(g) => 1800 + g.length * 2} onSubmit={() => {}} /></Card>
      <Card name="CommandBar"><CommandBar specs={mock.toolSpecs} resolveRef={mock.resolveRef} onRun={() => {}} /></Card>
      <Card name="PromptInspector"><PromptInspector role="frontier.plan" promptRef="frontier.plan@0.1" promptSha="3a91e2c0d4b1" parts={[{ name: "system", tokens: 930 }, { name: "compact_state", tokens: 2020 }]} responseFormat="json_schema plan@1" cache={{ hit: false, key: "7c0e…19" }} /></Card>
      <Card name="ModelRoute"><ModelRoute role="jev" model="typesafe/jev-1.13" pinned keyStatus={{ ok: true, where: "OS keychain" }} policy={{ data_collection: "deny", zdr: true, require_parameters: true, allow_fallbacks: false }} stats={[{ label: "p50 latency", value: "0.41 s" }, { label: "429", value: "2 → transient" }]} servedMismatch={{ callId: "call_0031", served: "typesafe/jev-1.12" }} /></Card>
      <Card name="ExplainPanel"><ExplainPanel streaming sentences={[{ text: "D100A의 측쇄가 리간드와 2.80 Å 수소결합을 이룹니다.", cite: "9f3c" }, { text: "L48A는 ΔΔG −1.9 REU로 가장 안정화됩니다.", dropped: { actual: "+0.42" } }]} /></Card>
      <Card name="ModelPanel" width={420}><ModelPanel models={mock.models} selected="#2" /></Card>
      <Card name="SequenceTrack" width={900}><SequenceTrack label="#2 A" startAuth={40} sequence={mock.sequence} mask={mock.mask} paintWith="design" tracks={[{ name: "pLDDT", kind: "plddt", bins: mock.plddtBins }, { name: "ΔΔG", kind: "energy", bins: mock.ddgBins }]} /></Card>
      <Card name="PAEPlot"><PAEPlot title="#2 AF3 rank_1" matrix={mock.pae} dividers={[14]} domainsText="2 (A:1–140, A:141–240)" /></Card>
      <Card name="ScaleLegend" width={320}><ScaleLegend kind="energy" title="color by · per_residue ΔΔG (REU)" note="값 없음 = 기본 색" /></Card>
      <Card name="EnergyBreakdown"><EnergyBreakdown title="per-residue · A/48 LEU → ALA" prov={{ scorefxn: "ref2015_cart", rosettaVersion: "a1b2c3", seed: 1207 }} total={0.42}
        terms={[{ name: "fa_atr", value: 1.21 }, { name: "fa_rep", value: -0.33 }, { name: "fa_sol", value: -0.88 }, { name: "fa_elec", value: 0.02 }, { name: "fa_dun", value: 0.4 }]} /></Card>
      <Card name="DdgTable"><DdgTable rows={mock.ddg} /></Card>
      <Card name="InterfaceScorecard"><InterfaceScorecard s={{ dG_separated: -38.2, dSASA_int: 1412, dG_dSASA_x100: -2.71, packstat: 0.64, delta_unsatHbonds: 5, hbonds_int: 11 }} /></Card>
      <Card name="JobQueue" width={760}><JobQueue jobs={mock.jobs} /></Card>
    </div>
  );
}
