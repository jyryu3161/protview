"use client";
import { useState } from "react";
import {
  ApprovalGate, CommandBar, CostMark, DdgTable, EgressGateView, ExplainPanel, HandleChip, InspectorSection,
  InteractionSwatch, InteractionTable, JobQueue, ModelPanel, MolstarViewer, PromptInspector, Segmented,
  SequenceTrack, StepList, WorkspaceShell, type MaskState, type Step,
} from "@/components";
import type { EgressMode } from "@/lib/contracts";
import * as mock from "@/mock/run";

/**
 * Static workspace wired to mock data (src/mock/run.ts).
 * Milestones replace mock sources with api.ts one panel at a time — see docs/milestones/.
 */
export default function WorkspacePage() {
  const [egress, setEgress] = useState<EgressMode>("local_only");
  const [selected, setSelected] = useState<Step>(mock.steps[2]);
  const [rep, setRep] = useState<"cartoon" | "surface" | "plddt">("cartoon");
  const [mask, setMask] = useState<MaskState[]>(mock.mask);
  const [sel, setSel] = useState<Set<number>>(new Set([8, 9, 12]));
  const [models, setModels] = useState(mock.models);
  const [history, setHistory] = useState<string[]>([]);
  const toggleTheme = () => {
    const r = document.documentElement;
    r.dataset.theme = r.dataset.theme === "dark" ? "light" : "dark";
  };

  const inspector = (() => {
    if (selected.tool === "plan") {
      return (
        <>
          <InspectorSection>
            <PromptInspector role="frontier.plan" promptRef="frontier.plan@0.1" promptSha="3a91e2c0d4b1"
              parts={[{ name: "system", tokens: 930 }, { name: "tool_schemas L5", tokens: 760 }, { name: "compact_state", tokens: 2020 }, { name: "goal", tokens: 112 }]}
              responseFormat="json_schema plan@1 (strict)" cache={{ hit: false, key: "7c0e…19" }} blocked={["coords", "sequence", "file_path"]} />
          </InspectorSection>
          <InspectorSection>
            <EgressGateView mode={egress} destination="OpenRouter → frontier" tokens={3812} logRef="#0031"
              fields={[{ name: "compact_state", blocked: false }, { name: "residue_ids ×47", blocked: false }, { name: "coords", blocked: true }, { name: "sequence", blocked: true }]} />
          </InspectorSection>
          <InspectorSection>
            <ExplainPanel sentences={[
              { text: "D100A의 측쇄가 리간드와 2.80 Å 수소결합을 이룹니다.", cite: "9f3c" },
              { text: "L48A는 ΔΔG −1.9 REU로 가장 안정화됩니다.", dropped: { actual: "+0.42" } },
              { text: "후보는 표면 쪽 V52I, T61S로 좁혀집니다.", cite: "e5d0" },
            ]} />
          </InspectorSection>
        </>
      );
    }
    if (selected.tool === "estimate_stability") {
      return <InspectorSection flush><DdgTable rows={mock.ddg} stub /></InspectorSection>;
    }
    return (
      <>
        <InspectorSection>
          <HandleChip handle={mock.handles.interactions} />
          <dl className="mw-kv"><dt>n_edges</dt><dd>47</dd><dt>n_hbond</dt><dd>12</dd><dt>n_hydrophobic</dt><dd>26</dd><dt>produced_by</dt><dd>call_0007</dd></dl>
        </InspectorSection>
        <InspectorSection flush><InteractionTable rows={mock.interactions} total={47} /></InspectorSection>
      </>
    );
  })();

  return (
    <WorkspaceShell
      runId={mock.RUN_ID} pipeline="inspect_complex → estimate_stability"
      egress={egress} onEgressChange={setEgress}
      budgetShort={<CostMark cost="expensive" text="expensive 6/8" />}
      onToggleTheme={toggleTheme}
      railCounts={{ run: mock.steps.length, models: models.length, jobs: 1 }}
      rail={{
        run: <StepList steps={mock.steps} selected={selected.n} onSelect={setSelected} />,
        models: <ModelPanel models={models} selected="#2" onToggle={(id) => setModels((ms) => ms.map((m) => (m.id === id ? { ...m, visible: !m.visible } : m)))} />,
        jobs: <JobQueue jobs={mock.jobs} />,
      }}
      railFooter={<ApprovalGate compact gate="expensive_first_call" question="relax_structure를 실행할까요?" why="expensive 첫 호출 · 예상 3분" />}
      canvas={<MolstarViewer structures={[]} representation={rep} />}
      canvasOverlayTopLeft={<>
        <Segmented label="view" value={rep} onChange={setRep} options={[{ value: "cartoon" }, { value: "surface" }, { value: "plddt", label: "pLDDT" }]} />
        <HandleChip handle={{ handle: "obj://run/viewer_state/03", kind: "viewer_state" }} label={`step #${String(selected.n).padStart(2, "0")}`} />
      </>}
      canvasLegend={<><InteractionSwatch type="hbond">hbond 12</InteractionSwatch><InteractionSwatch type="hydrophobic">hydrophobic 26</InteractionSwatch><InteractionSwatch type="metal">metal 1</InteractionSwatch></>}
      strip={<>
        <SequenceTrack label="#2 A" startAuth={40} sequence={mock.sequence} selected={sel} onSelect={(i) => setSel(new Set(i))}
          mask={mask} onMaskChange={setMask} paintWith="design" />
        <CommandBar specs={mock.toolSpecs} resolveRef={mock.resolveRef} history={history}
          onRun={(c) => setHistory((h) => [...h, `${c.tool} ${Object.entries(c.args).map(([k, v]) => `${k}=${v}`).join(" ")}`])} />
      </>}
      inspectorTitle={`Inspector · step #${String(selected.n).padStart(2, "0")}`}
      inspector={inspector}
    />
  );
}
