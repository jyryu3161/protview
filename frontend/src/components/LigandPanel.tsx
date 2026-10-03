"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type RunSummary } from "@/lib/api";
import type { BudgetSnapshot, LigandBlockLibrary, LigandCandidatePage, LigandCandidateSetDetail,
  LigandCandidateSetList, LigandCapability, LigandCounts, LigandFilterSpec, LigandImport, LigandImportKind,
  LigandInspectionDetail, LigandInspectionList, LigandJob, LigandPropertyName, LigandProperties, LigandProtocol,
  LigandReportArtifact, LigandSitePreview, LigandSortDirection, LigandSortKey } from "@/lib/contracts";
import { appliedFilterCount, blockLimitText, CANDIDATE_2D_NOTE, CANDIDATE_PAGE_LIMIT, candidateCountText,
  candidateRowsQuery, checkFilterInput, countText, emptyAppliedFilter, emptyFilterInput, emptySiteSelection, enumerateArgs, enumerateReady,
  filterSummaryText, inspectArgs, LIGAND_APPROVAL_NOTICE, LIGAND_TOOLS, ligandApprovalRequired, ligandJobPhase, ligandJobText, ligandNoticeAfterJob, ligandPanelState,
  ligandReasonText, ligandResponseCurrent, ligandStartBlockedReason, ligandStartProgressed, ligandSubmitText,
  limitReachedText, MAX_RULES, PAINS_HEADER, PAINS_NOTE, painsText, passText, previewBlockingText, PRODUCT_REJECT_REASONS,
  PROPERTY_LABEL, PROPERTY_NAMES, PROPERTY_NOTE, propertyHeader, propertyText, RULE_VALID, ruleStatusText, SORT_KEYS,
  siteAtomChecked, siteSelectionDisabledReason, svgDataUri, toggleSiteAtom, usableRuleIds,
  type AppliedFilter, type CandidateView, type LigandFilterInput, type LigandStamp, type SiteSelection } from "@/lib/ligand";
import { Button } from "./primitives";

/**
 * M17 "리간드 설계·탐색" tab body (spec section 8). Every number shown is a stored backend value (inspection,
 * candidate set, server-evaluated candidate page); decisions, wording and rounding come from `lib/ligand.ts`.
 * The page mounts it only while the tab is shown and keys it by run; late responses are dropped by run +
 * selected handle + per-area request sequence (`ligandResponseCurrent`).
 */
export interface LigandPanelProps {
  /** Current run of the structure analysis screen (run selection lives only there); null when none. */
  run: RunSummary | null;
  /** undefined while capabilities are being read; null when the backend reports no ligand method. */
  capability: LigandCapability | null | undefined;
  /** After a report was created: the page re-reads the knowledge-tab report list (it drops another run's call). */
  onReportCreated: (runId: string) => void;
}

const STATE_TEXT = { loading: "불러오는 중", ready: "준비", scientific_null: "빈 결과 (후보 0개)", failure: "실패",
  unavailable: "사용할 수 없음" } as const;
const PROTOCOLS: readonly LigandProtocol[] = ["rdkit_inspect_v1", "rdkit_enumerate_v1"];
const ACTIVE = new Set(["queued", "claimed", "running"]);
const LIST_LIMIT = 100;
const SORT_LABEL = (key: LigandSortKey) => key === "generation_order" ? "생성 순서" : PROPERTY_LABEL[key];
const PAINS_FILTER = "pains_exclude";

type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };
type Area = "imports" | "inspections" | "sets" | "inspection" | "preview" | "set" | "rows" | "report" | "job" | "budget";
type Slot = "parent" | "blockSdf" | "blockSmiles";
const SLOT_KIND: Record<Slot, LigandImportKind> = { parent: "ligand_sdf", blockSdf: "building_blocks_sdf",
  blockSmiles: "building_blocks_smiles" };
const SLOT_LABEL: Record<Slot, string> = { parent: "부모 리간드 SDF (V2000, 분자 1개)",
  blockSdf: "building block SDF (선택)", blockSmiles: "building block SMILES 목록 (선택, 줄마다 SMILES 이름)" };
const SLOT_ACCEPT: Record<Slot, string> = { parent: ".sdf", blockSdf: ".sdf", blockSmiles: ".smi,.txt" };
const SLOTS: readonly Slot[] = ["parent", "blockSdf", "blockSmiles"];

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const reason = typeof e.detail?.reason_code === "string" ? ligandReasonText(e.detail.reason_code) : e.code;
    return reason ? `${reason} · ${e.message}` : e.message;
  }
  return e instanceof Error ? e.message : String(e);
}
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

async function allInspections(runId: string, signal: AbortSignal): Promise<LigandInspectionList> {
  const first = await api.ligandInspections(runId, 0, LIST_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.ligandInspections(runId, rows.length, LIST_LIMIT, signal);
    if (page.total !== first.total || !page.rows.length) throw new Error("점검 결과 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  if (first.schema !== "ligand_inspection_list@1") throw new Error("점검 결과 목록 형식이 다릅니다.");
  return { ...first, offset: 0, limit: rows.length, rows };
}

async function allSets(runId: string, signal: AbortSignal): Promise<LigandCandidateSetList> {
  const first = await api.ligandCandidateSets(runId, null, 0, LIST_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.ligandCandidateSets(runId, null, rows.length, LIST_LIMIT, signal);
    if (page.total !== first.total || !page.rows.length) throw new Error("후보 집합 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  if (first.schema !== "ligand_candidate_set_list@1") throw new Error("후보 집합 목록 형식이 다릅니다.");
  return { ...first, offset: 0, limit: rows.length, rows };
}

function Section({ area, title, state, children }: { area: string; title: string; state?: string; children: ReactNode }) {
  return <section className="mw-ligand-section" data-ligand-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-ligand-title">{title}</h3>
    {children}
  </section>;
}

function ErrorLine({ message, onRetry, testId }: { message: string; onRetry?: () => void; testId?: string }) {
  return <div className="mw-ligand-error" role="alert" data-testid={testId}>
    <span>{message}</span>
    {onRetry && <Button size="sm" onClick={onRetry}>다시 읽기</Button>}
  </div>;
}

export function LigandPanel(p: LigandPanelProps) {
  const runId = p.run?.run_id ?? null;
  const gate = ligandPanelState({ runId, capability: p.capability });
  if (!p.run || gate.state === "unavailable" || p.capability === undefined || p.capability === null) {
    const state = gate.state === "unavailable" ? "unavailable" : "loading";
    return <section className="mw-ligand" aria-label="리간드 설계·탐색" data-testid="ligand-panel" data-ligand-state={state}>
      <h2 className="mw-ligand-heading">리간드 설계·탐색 · 부분 교체 후보</h2>
      {gate.state === "unavailable" ? <p className="mw-ligand-unavailable" role="status"
        data-testid={runId === null ? "ligand-no-run" : "ligand-unavailable"}><b>{STATE_TEXT.unavailable}</b>: {gate.reason}</p>
        : <p className="mw-ligand-note" aria-busy="true">기능 상태를 확인하는 중</p>}
    </section>;
  }
  return <LigandWorkspace run={p.run} capability={p.capability} onReportCreated={p.onReportCreated} />;
}

function LigandWorkspace({ run, capability, onReportCreated }: { run: RunSummary; capability: LigandCapability;
  onReportCreated: (runId: string) => void }) {
  const runId = run.run_id;
  const [files, setFiles] = useState<Record<Slot, File | null>>({ parent: null, blockSdf: null, blockSmiles: null });
  const [imports, setImports] = useState<Record<Slot, LigandImport | null>>({ parent: null, blockSdf: null, blockSmiles: null });
  const [importState, setImportState] = useState<Load<true>>({ status: "idle" });
  const [rulesText, setRulesText] = useState("");
  const [inspections, setInspections] = useState<Load<LigandInspectionList>>({ status: "idle" });
  const [inspectionsReload, setInspectionsReload] = useState(0);
  const [sets, setSets] = useState<Load<LigandCandidateSetList>>({ status: "idle" });
  const [setsReload, setSetsReload] = useState(0);
  const [selectedInspection, setSelectedInspection] = useState<string | null>(null);
  const [inspection, setInspection] = useState<{ handle: string; load: Load<LigandInspectionDetail> } | null>(null);
  const [site, setSite] = useState<SiteSelection>(() => emptySiteSelection(null));
  const [useFixed, setUseFixed] = useState(true);
  const [chosenRules, setChosenRules] = useState<string[]>([]);
  const [preview, setPreview] = useState<{ key: string; load: Load<LigandSitePreview> } | null>(null);
  const [selectedSet, setSelectedSet] = useState<string | null>(null);
  const [setDetail, setSetDetail] = useState<{ handle: string; load: Load<LigandCandidateSetDetail> } | null>(null);
  const [filterInput, setFilterInput] = useState<LigandFilterInput>(emptyFilterInput);
  const [filterErrors, setFilterErrors] = useState<string[]>([]);
  const [applied, setApplied] = useState<AppliedFilter>(emptyAppliedFilter);
  const [view, setView] = useState<CandidateView>({ sort: "generation_order", direction: "asc", offset: 0,
    limit: CANDIDATE_PAGE_LIMIT, passesOnly: false });
  const [rows, setRows] = useState<{ key: string; load: Load<LigandCandidatePage> } | null>(null);
  const [rowsRetry, setRowsRetry] = useState(0);
  const [report, setReport] = useState<{ handle: string; load: Load<LigandReportArtifact> } | null>(null);
  const [job, setJob] = useState<LigandJob | null>(null);
  // The job decides the panel state only until the user opens a stored result (ligandPanelState: job null then).
  const [jobFocus, setJobFocus] = useState(false);
  const [approvalPending, setApprovalPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [jobError, setJobError] = useState("");
  const [notice, setNotice] = useState("");
  const [resultNotice, setResultNotice] = useState<{ text: string; handle: string | null } | null>(null);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [budgetReload, setBudgetReload] = useState(0);

  // Late responses: keyed by run (page key), selected handle of the area and the area's request sequence.
  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>({ imports: 0, inspections: 0, sets: 0, inspection: 0, preview: 0, set: 0,
    rows: 0, report: 0, job: 0, budget: 0 });
  const live = useRef({ inspection: selectedInspection, set: selectedSet });
  live.current = { inspection: selectedInspection, set: selectedSet };
  useEffect(() => {
    mounted.current = true;
    const counters = seqs.current;
    return () => { mounted.current = false; for (const area of Object.keys(counters) as Area[]) counters[area] += 1; };
  }, []);
  const handleOf = (area: Area): string | null => area === "inspection" || area === "preview" ? live.current.inspection
    : area === "set" || area === "rows" || area === "report" ? live.current.set : null;
  const stamp = (area: Area): LigandStamp => ({ runId, handle: handleOf(area), seq: ++seqs.current[area] });
  const current = (area: Area, captured: LigandStamp) => mounted.current &&
    ligandResponseCurrent(captured, { runId, handle: handleOf(area), seq: seqs.current[area] });

  // ---- reads ----
  useEffect(() => {
    const captured = stamp("inspections"), controller = new AbortController();
    setInspections({ status: "loading" });
    allInspections(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (current("inspections", captured)) setInspections({ status: "ready", value });
    }).catch(e => { if (current("inspections", captured)) setInspections({ status: "error", message: `점검 결과 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // stamp/current read live refs; the read is keyed by run and its reload counter.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, inspectionsReload]);

  useEffect(() => {
    const captured = stamp("sets"), controller = new AbortController();
    setSets({ status: "loading" });
    allSets(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (current("sets", captured)) setSets({ status: "ready", value });
    }).catch(e => { if (current("sets", captured)) setSets({ status: "error", message: `후보 집합 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, setsReload]);

  useEffect(() => {
    const captured = stamp("budget");
    api.budget(runId).then(value => { if (current("budget", captured)) setBudget(value); }).catch(() => undefined);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, budgetReload]);

  // After a remount the durable job list tells whether this tab's job is still queued or running.
  useEffect(() => {
    const captured = stamp("job"), controller = new AbortController();
    api.ligandJobs(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(list => {
      if (!current("job", captured) || !Array.isArray(list)) return;
      const running = list.filter(item => item.run_id === runId && PROTOCOLS.includes(item.protocol_id) &&
        ACTIVE.has(item.status)).at(-1);
      if (running) { setJob(previous => previous ?? running); setJobFocus(true); }
    }).catch(() => undefined);
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Polling reads only, while this panel's job is queued, claimed or running.
  useEffect(() => {
    if (!job || !ACTIVE.has(job.status)) return;
    let active = true;
    const jobId = job.job_id;
    const timer = window.setInterval(() => {
      void api.ligandJob(runId, jobId).then(value => {
        if (active && mounted.current && value.run_id === runId && value.job_id === jobId)
          setJob(previous => previous?.job_id === jobId ? value : previous);
      }).catch(() => undefined);
    }, 1000);
    return () => { active = false; window.clearInterval(timer); };
  // Restarted only when the job id or status changes (each poll answer is a new object).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, job?.job_id, job?.status]);

  // A finished job refreshes the lists; its result is never opened automatically (the user picks it).
  useEffect(() => {
    if (!job) return;
    setNotice(previous => ligandNoticeAfterJob(previous, job.status));
    if (job.status === "done") {
      const handle = job.artifacts.ligand_inspection ?? job.artifacts.ligand_candidate_set ?? null;
      if (job.protocol_id === "rdkit_inspect_v1") {
        setInspectionsReload(value => value + 1);
        setResultNotice({ text: `점검 결과가 저장되었습니다${handle ? ` (${shortHandle(handle)})` : ""}. 아래 점검 결과 목록에서 직접 고르세요.`, handle });
      } else {
        setSetsReload(value => value + 1);
        setResultNotice({ text: `후보 집합이 저장되었습니다${handle ? ` (${shortHandle(handle)})` : ""}. 아래 후보 집합 목록에서 직접 고르세요.`, handle });
      }
    }
    if (!ACTIVE.has(job.status)) setBudgetReload(value => value + 1);
  // Only a new job id or status triggers the follow-up reads.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, job?.status]);

  function openInspection(handle: string) {
    setSelectedInspection(handle); live.current = { ...live.current, inspection: handle };
    setSite(emptySiteSelection(handle)); setChosenRules([]); setPreview(null); setJobFocus(false);
    const captured = stamp("inspection");
    setInspection({ handle, load: { status: "loading" } });
    api.ligandInspection(runId, handle, AbortSignal.timeout(30000)).then(value => {
      if (!current("inspection", captured)) return;
      if (value.schema !== "ligand_inspection_detail@1" || value.handle !== handle) throw new Error("점검 결과가 고른 handle과 다릅니다.");
      setInspection({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("inspection", captured)) setInspection({ handle, load: { status: "error", message: `점검 결과 읽기 실패: ${errorText(e)}` } }); });
  }

  function openSet(handle: string) {
    setSelectedSet(handle); live.current = { ...live.current, set: handle };
    setView(previous => ({ ...previous, offset: 0 })); setReport(null); setRows(null); setJobFocus(false);
    const captured = stamp("set");
    setSetDetail({ handle, load: { status: "loading" } });
    api.ligandCandidateSet(runId, handle, AbortSignal.timeout(30000)).then(value => {
      if (!current("set", captured)) return;
      if (value.schema !== "ligand_candidate_set_detail@1" || value.handle !== handle) throw new Error("후보 집합이 고른 handle과 다릅니다.");
      setSetDetail({ handle, load: { status: "ready", value } });
    }).catch(e => { if (current("set", captured)) setSetDetail({ handle, load: { status: "error", message: `후보 집합 읽기 실패: ${errorText(e)}` } }); });
  }

  const inspected = inspection && inspection.handle === selectedInspection && inspection.load.status === "ready"
    ? inspection.load.value : null;
  const openedSet = setDetail && setDetail.handle === selectedSet && setDetail.load.status === "ready" ? setDetail.load.value : null;

  // ---- site preview: only the answer to the current request is used ----
  const ruleIds = inspected ? inspected.inspection.rules.map(rule => rule.rule_id).filter(id => chosenRules.includes(id)) : [];
  const enumeration = enumerateArgs({ inspectionHandle: inspected ? inspected.handle : null,
    siteAtoms: site.inspectionHandle === selectedInspection ? site.atoms : [], useFixed, ruleIds });
  const previewKey = enumeration.ok ? JSON.stringify(enumeration.args) : null;
  useEffect(() => {
    if (!enumeration.ok || previewKey === null) return;
    const args = enumeration.args, key = previewKey, captured = stamp("preview"), controller = new AbortController();
    setPreview({ key, load: { status: "loading" } });
    api.ligandPreview(runId, args, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("preview", captured)) return;
      if (value.schema !== "ligand_site_preview@1" || value.inspection_handle !== args.inspection_handle)
        throw new Error("부위 검사 응답이 고른 점검 결과와 다릅니다.");
      setPreview({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("preview", captured) && !controller.signal.aborted)
      setPreview({ key, load: { status: "error", message: `부위 검사 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  // Keyed by the exact request body.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);
  const previewLoad = preview && preview.key === previewKey ? preview.load : null;
  const previewValue = previewLoad?.status === "ready" ? previewLoad.value : null;

  // ---- candidate rows (server-evaluated filter, sort, page) ----
  const rowsKey = selectedSet ? candidateRowsQuery(selectedSet, applied, view) : null;
  useEffect(() => {
    if (!selectedSet || rowsKey === null) return;
    const key = rowsKey, handle = selectedSet, captured = stamp("rows"), controller = new AbortController();
    setRows({ key, load: { status: "loading" } });
    api.ligandCandidateRows(runId, key, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (!current("rows", captured)) return;
      if (value.schema !== "ligand_candidate_page@1" || value.handle !== handle) throw new Error("후보 행이 고른 후보 집합과 다릅니다.");
      setRows({ key, load: { status: "ready", value } });
    }).catch(e => { if (current("rows", captured) && !controller.signal.aborted)
      setRows({ key, load: { status: "error", message: `후보 행 읽기 실패: ${errorText(e)}` } }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowsKey, rowsRetry]);
  const rowsLoad = rows && rows.key === rowsKey ? rows.load : null;
  const page = rowsLoad?.status === "ready" ? rowsLoad.value : null;

  // ---- imports and jobs ----
  const chosenNotImported = SLOTS.filter(slot => files[slot] && !imports[slot]);
  const inspect = inspectArgs({ parent: imports.parent?.handle ?? null, blockSdf: imports.blockSdf?.handle ?? null,
    blockSmiles: imports.blockSmiles?.handle ?? null, rulesText });
  const startBlocked = ligandStartBlockedReason({ capability, dryRun: run.dry_run, busy, activeJob: job });
  const inspectBlocked = startBlocked ?? (chosenNotImported.length ? "고른 파일을 먼저 가져오세요." : null)
    ?? (inspect.ok ? null : inspect.errors.join(" "));
  const enumerateBlocked = startBlocked ?? (!enumeration.ok ? enumeration.errors.join(" ")
    : !previewValue ? "부위 검사 결과를 기다리는 중입니다."
      : !enumerateReady(previewValue, enumeration.args) ? "부위 검사를 통과해야 시작할 수 있습니다." : null);

  async function importFiles() {
    const pending = SLOTS.filter(slot => files[slot] && !imports[slot]);
    if (!pending.length || importState.status === "loading") return;
    const captured = stamp("imports");
    setImportState({ status: "loading" });
    try {
      for (const slot of pending) {
        const file = files[slot]!;
        const value = await api.ligandImport(runId, SLOT_KIND[slot], file, AbortSignal.timeout(60000));
        if (!current("imports", captured)) return;
        if (value.kind !== SLOT_KIND[slot] || value.schema !== "chemical_raw_input@1") throw new Error("가져오기 응답의 종류가 다릅니다.");
        setImports(previous => ({ ...previous, [slot]: value }));
      }
      setImportState({ status: "ready", value: true });
    } catch (e) { if (current("imports", captured)) setImportState({ status: "error", message: `가져오기 실패: ${errorText(e)}` }); }
  }

  function chooseFile(slot: Slot, file: File | null) {
    seqs.current.imports += 1;
    setFiles(previous => ({ ...previous, [slot]: file }));
    setImports(previous => ({ ...previous, [slot]: null }));
    setImportState({ status: "idle" });
  }

  async function start(before: LigandJob) {
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice(""); setJobFocus(true);
    try {
      const value = await api.startJob(runId, before.job_id) as unknown as LigandJob;
      if (!current("job", captured)) return;
      if (value.run_id !== runId || value.job_id !== before.job_id) throw new Error("시작 응답이 이 작업과 다릅니다.");
      setApprovalPending(false); setJob(value);
    } catch (e) {
      if (!current("job", captured)) return;
      if (e instanceof ApiError && ligandApprovalRequired(e.status, e.approval, before.protocol_id)) {
        setApprovalPending(true); setBudgetReload(value => value + 1);
        return;
      }
      // The start may have taken effect although its response was lost: the stored job decides.
      const stored = await api.ligandJob(runId, before.job_id).catch(() => null);
      if (!current("job", captured)) return;
      if (stored && stored.run_id === runId && stored.job_id === before.job_id) setJob(stored);
      if (!stored || !ligandStartProgressed(before, stored)) setJobError(`작업 시작 실패: ${errorText(e)}`);
    } finally { if (mounted.current) setBusy(false); }
  }

  async function submit(protocol: LigandProtocol) {
    if (protocol === "rdkit_inspect_v1" ? inspectBlocked || !inspect.ok : enumerateBlocked || !enumeration.ok) return;
    const captured = stamp("job");
    setBusy(true); setJobError(""); setNotice(""); setResultNotice(null); setApprovalPending(false); setJobFocus(true);
    try {
      const result = protocol === "rdkit_inspect_v1" && inspect.ok ? await api.submitLigandInspect(runId, inspect.args)
        : enumeration.ok ? await api.submitLigandEnumerate(runId, enumeration.args) : null;
      if (!result || !current("job", captured)) return;
      if ("plan_only" in result) { setNotice(ligandSubmitText(result)); return; }
      if (result.run_id !== runId || result.protocol_id !== protocol) throw new Error("제출 응답이 요청과 다릅니다.");
      setJob(result);
      if (result.status !== "queued") { setNotice(ligandSubmitText(result)); return; }
      await start(result);
    } catch (e) { if (current("job", captured)) setJobError(`작업 제출 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function approve() {
    if (!job) return;
    const captured = stamp("job");
    setBusy(true); setJobError("");
    try {
      await api.approveOpenmm(runId);
      if (!current("job", captured)) return;
      setApprovalPending(false); setBudgetReload(value => value + 1);
      setNotice(LIGAND_APPROVAL_NOTICE);
    } catch (e) { if (current("job", captured)) setJobError(`승인 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function jobAction(kind: "cancel" | "retry") {
    if (!job) return;
    const captured = stamp("job"), jobId = job.job_id;
    setBusy(true); setJobError("");
    try {
      const value = (kind === "cancel" ? (await api.cancelJob(runId, jobId)).job : await api.retryJob(runId, jobId)) as unknown as LigandJob;
      if (current("job", captured) && value.run_id === runId && value.job_id === jobId) setJob(value);
    } catch (e) { if (current("job", captured)) setJobError(`작업 ${kind === "cancel" ? "취소" : "재시도"} 실패: ${errorText(e)}`); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function makeReport() {
    if (!openedSet || !selectedSet || report?.load.status === "loading") return;
    const handle = selectedSet, filters = appliedFilterCount(applied.spec) ? applied.spec : null, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createLigandReport(runId, handle, filters, AbortSignal.timeout(60000));
      if (!current("report", captured)) return;
      if (artifact.manifest.schema !== "method_report_manifest@1" || artifact.manifest.analysis_type !== "ligand_candidates" ||
          artifact.manifest.result_handle !== handle) throw new Error("보고서가 고른 후보 집합과 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
      onReportCreated(runId);
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  function applyFilters() {
    const check = checkFilterInput(filterInput);
    if (!check.ok) { setFilterErrors(check.errors); return; }
    setFilterErrors([]); setApplied({ spec: check.spec, bounds: check.bounds }); setView(previous => ({ ...previous, offset: 0 }));
  }

  function clearFilters() {
    setFilterInput(emptyFilterInput()); setFilterErrors([]); setApplied(emptyAppliedFilter());
    setView(previous => ({ ...previous, offset: 0 }));
  }

  // ---- panel state ----
  const readError = (setDetail?.handle === selectedSet && setDetail?.load.status === "error" ? setDetail.load.message : null)
    ?? (rowsLoad?.status === "error" ? rowsLoad.message : null)
    ?? (inspection?.handle === selectedInspection && inspection?.load.status === "error" ? inspection.load.message : null)
    ?? (inspections.status === "error" ? inspections.message : null) ?? (sets.status === "error" ? sets.message : null)
    ?? (jobError || null);
  const panelState = ligandPanelState({ runId, capability,
    loading: inspections.status === "loading" || sets.status === "loading" || inspection?.load.status === "loading" ||
      setDetail?.load.status === "loading" || rowsLoad?.status === "loading",
    error: readError, job: jobFocus ? job : null, candidates: openedSet ? openedSet.candidate_count : null });
  const phase = ligandJobPhase(job, approvalPending);

  return <section className="mw-ligand" aria-label="리간드 설계·탐색" data-testid="ligand-panel" data-ligand-state={panelState.state}>
    <div className="mw-ligand-head">
      <h2 className="mw-ligand-heading">리간드 설계·탐색 · 부분 교체 후보</h2>
      <span className="mw-badge" data-testid="ligand-state">{STATE_TEXT[panelState.state]}</span>
    </div>
    {panelState.state === "failure" && <p role="alert" className="mw-ligand-error" data-testid="ligand-failure">{panelState.message}</p>}
    {panelState.state === "scientific_null" && <p role="status" className="mw-ligand-null" data-testid="ligand-null-result">{panelState.message}</p>}
    <p className="mw-ligand-note">{CANDIDATE_2D_NOTE} {PROPERTY_NOTE} {PAINS_NOTE}</p>
    {run.dry_run && <p role="status" className="mw-ligand-unavailable" data-testid="ligand-dry-run">
      dry-run run: 미리보기 전용입니다. 가져오기·저장된 결과 보기·부위 검사는 할 수 있지만 점검·생성 작업은 시작하지 않습니다(dry-run의 비싼 작업은 계획만이며 실제 계산과 결과 객체가 없음).</p>}
    <p className="mw-ligand-note mw-mono" data-testid="ligand-capability">
      {capability.engine} {capability.rdkit_version_expected} · 제한 시간 {capability.timeout_s}s · 작업마다 비싼 계산 예산 1단위
      {budget ? <span data-testid="ligand-budget" data-used={budget.expensive_calls.used} data-limit={budget.expensive_calls.limit}>
        {` · 비싼 계산 ${budget.expensive_calls.used}/${budget.expensive_calls.limit}`}</span> : null}</p>

    <Section area="inputs" title="① 입력" state={importState.status}>
      <div className="mw-ligand-form">
        {SLOTS.map(slot => <label key={slot} className="mw-ligand-field">
          <span>{SLOT_LABEL[slot]}</span>
          <input type="file" accept={SLOT_ACCEPT[slot]} data-testid={`ligand-file-${slot}`} disabled={importState.status === "loading"}
            onChange={event => chooseFile(slot, event.target.files?.[0] ?? null)} />
          {imports[slot] ? <span className="mw-ligand-note mw-mono" data-ligand-import={SLOT_KIND[slot]} data-import-handle={imports[slot]!.handle}>
            가져옴 · {imports[slot]!.format} · {imports[slot]!.size} B · {shortHandle(imports[slot]!.handle)}</span>
            : files[slot] ? <span className="mw-ligand-note">아직 가져오지 않음</span> : null}
        </label>)}
        <div className="mw-ligand-inline">
          <Button size="sm" data-testid="ligand-import" disabled={!chosenNotImported.length || importState.status === "loading"}
            onClick={() => void importFiles()}>가져오기</Button>
          {importState.status === "loading" && <span className="mw-ligand-note" aria-busy="true">가져오는 중</span>}
        </div>
        {importState.status === "error" && <ErrorLine message={importState.message} testId="ligand-import-error" />}
        <label className="mw-ligand-field mw-ligand-field--block">
          <span>반응 규칙 (반응 SMARTS, 한 줄에 규칙 하나, 최대 {MAX_RULES}개, 선택). 규칙 검증은 점검 작업이 합니다.</span>
          <textarea className="mw-ligand-textarea" data-testid="ligand-rules" rows={4} spellCheck={false} value={rulesText}
            onChange={event => setRulesText(event.target.value)} placeholder="[C:1][OH]>>[C:1]Cl" />
        </label>
      </div>
    </Section>

    <Section area="inspect" title="② 점검 작업">
      <p className="mw-ligand-note">부모 검증, 번호 붙은 2D 그림, 원자 표, building block·규칙 검증을 RDKit 작업으로 한 번 실행합니다.</p>
      <div className="mw-ligand-inline">
        <Button size="sm" variant="primary" data-testid="ligand-inspect-start" disabled={!!inspectBlocked}
          title={inspectBlocked ?? undefined} onClick={() => void submit("rdkit_inspect_v1")}>점검 시작</Button>
        {inspectBlocked && <span className="mw-ligand-note" data-testid="ligand-inspect-blocked">{inspectBlocked}</span>}
      </div>
    </Section>

    {(job || notice || resultNotice || jobError) && <Section area="job" title="작업 진행">
      {job && <div className="mw-ligand-job" data-testid="ligand-job" data-ligand-job-protocol={job.protocol_id}
        data-ligand-job-phase={phase} data-ligand-job-status={job.status} data-ligand-job-id={job.job_id}>
        <p className="mw-ligand-note" role="status">{ligandJobText(job.protocol_id, job, approvalPending)}</p>
        <p className="mw-ligand-note mw-mono">{LIGAND_TOOLS[job.protocol_id]} · 작업 {job.status} · 시도 {job.attempt_ordinal} · {job.job_id}</p>
        {job.blocked_reason && <p className="mw-ligand-note">시작 대기 이유: {job.blocked_reason}</p>}
        <div className="mw-ligand-inline">
          {phase === "awaiting_approval" && <Button size="sm" data-testid="ligand-job-approve" disabled={busy}
            onClick={() => void approve()}>비싼 계산 승인</Button>}
          {phase === "saved" && <Button size="sm" data-testid="ligand-job-start" disabled={busy || run.dry_run}
            onClick={() => void start(job)}>작업 시작</Button>}
          {ACTIVE.has(job.status) && <Button size="sm" data-testid="ligand-job-cancel" disabled={busy || job.cancel_requested}
            onClick={() => void jobAction("cancel")}>작업 취소</Button>}
          {["failed", "interrupted"].includes(job.status) && job.attempt_ordinal < 4 && <Button size="sm" data-testid="ligand-job-retry"
            disabled={busy} onClick={() => void jobAction("retry")}>작업 재시도</Button>}
        </div>
      </div>}
      {notice && <p role="status" className="mw-ligand-note" data-testid="ligand-notice">{notice}</p>}
      {resultNotice && <p role="status" className="mw-ligand-note" data-testid="ligand-result-notice"
        data-ligand-new-result={resultNotice.handle ?? undefined}>{resultNotice.text}</p>}
      {jobError && <ErrorLine message={jobError} testId="ligand-job-error" />}
    </Section>}

    <Section area="inspections" title="③ 점검 결과" state={inspections.status}>
      {inspections.status === "loading" && <p className="mw-ligand-note" aria-busy="true">점검 결과 목록을 읽는 중</p>}
      {inspections.status === "error" && <ErrorLine message={inspections.message} onRetry={() => setInspectionsReload(value => value + 1)} />}
      {inspections.status === "ready" && (!inspections.value.rows.length
        ? <p className="mw-ligand-note">이 run에 점검 결과가 없습니다. 부모 SDF를 가져와 점검을 시작하세요.</p>
        : <fieldset className="mw-ligand-choices" data-testid="ligand-inspections">
          <legend>점검 결과 선택 (자동으로 고르지 않음)</legend>
          {inspections.value.rows.map(row => <label key={row.handle} data-ligand-inspection={row.handle} data-valid={row.valid}>
            <input type="radio" name={`ligand-inspection-${runId}`} checked={selectedInspection === row.handle} disabled={!row.valid}
              onChange={() => openInspection(row.handle)} />
            <span className="mw-mono">생성 순번 {row.created_seq} · {shortHandle(row.handle)} · {row.valid
              ? `${row.parent_canonical_smiles} · 중원자 ${row.heavy_atom_count} · 수락 block ${row.blocks_accepted} · 검증 통과 규칙 ${row.rules_valid}/${row.rules_total}`
              : `읽을 수 없음: ${ligandReasonText(row.reason_code ?? "evidence_invalid")}`}</span>
          </label>)}
        </fieldset>)}
      {inspections.status !== "loading" && <Button size="sm" data-testid="ligand-inspections-refresh"
        onClick={() => setInspectionsReload(value => value + 1)}>점검 결과 목록 다시 읽기</Button>}
      {inspection?.handle === selectedInspection && inspection.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">점검 결과를 읽는 중</p>}
      {inspection?.handle === selectedInspection && inspection.load.status === "error" &&
        <ErrorLine message={inspection.load.message} onRetry={() => selectedInspection && openInspection(selectedInspection)} />}
      {inspected && <InspectionView detail={inspected} site={site} onToggle={serial =>
        setSite(previous => toggleSiteAtom(previous, inspected.handle, serial))} />}
    </Section>

    <Section area="site" title="부위 지정과 부위 검사">
      {(() => {
        const reason = siteSelectionDisabledReason({ inspectionHandle: selectedInspection, inspectionLoaded: !!inspected });
        return reason ? <p className="mw-ligand-unavailable" data-testid="ligand-site-disabled">{reason}</p> : null;
      })()}
      {inspected && <>
        <p className="mw-ligand-note" data-testid="ligand-site-atoms" data-site-atoms={site.atoms.join(",")}>
          고른 부위 원자 (SDF 번호): {site.atoms.length ? site.atoms.join(", ") : "없음"}</p>
        <fieldset className="mw-ligand-choices" data-testid="ligand-methods">
          <legend>생성 방법</legend>
          <label><input type="checkbox" data-testid="ligand-use-fixed" checked={useFixed} onChange={event => setUseFixed(event.target.checked)} />
            고정 교체 (replace_single_bond_v1, 표시 원자 * 1개 block)</label>
          {inspected.inspection.rules.map(rule => <label key={rule.rule_id} data-rule-id={rule.rule_id} data-rule-status={rule.status}>
            <input type="checkbox" data-testid={`ligand-rule-${rule.rule_id}`} checked={chosenRules.includes(rule.rule_id)}
              disabled={rule.status !== RULE_VALID} onChange={event => setChosenRules(previous => event.target.checked
                ? [...previous, rule.rule_id] : previous.filter(id => id !== rule.rule_id))} />
            <span className="mw-mono">{rule.rule_id} (user_reaction_smarts_v1) · {ruleStatusText(rule)}</span>
            {rule.status !== RULE_VALID && <span className="mw-ligand-note">생성에 쓸 수 없음</span>}
          </label>)}
          {!usableRuleIds(inspected.inspection.rules).length && <p className="mw-ligand-note">검증을 통과한 반응 규칙이 없습니다.</p>}
        </fieldset>
        {!enumeration.ok && <ul className="mw-ligand-errors" data-testid="ligand-enumerate-errors">
          {enumeration.errors.map(error => <li key={error}>{error}</li>)}</ul>}
        {previewLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">부위 검사 중</p>}
        {previewLoad?.status === "error" && <ErrorLine message={previewLoad.message} testId="ligand-preview-error" />}
        {previewValue && <PreviewView preview={previewValue} />}
      </>}
    </Section>

    <Section area="enumerate" title="④ 후보 생성 작업">
      <div className="mw-ligand-inline">
        <Button size="sm" variant="primary" data-testid="ligand-enumerate-start" disabled={!!enumerateBlocked}
          title={enumerateBlocked ?? undefined} onClick={() => void submit("rdkit_enumerate_v1")}>후보 생성 시작</Button>
        {enumerateBlocked && <span className="mw-ligand-note" data-testid="ligand-enumerate-blocked">{enumerateBlocked}</span>}
      </div>
    </Section>

    <Section area="sets" title="⑤ 후보 집합" state={sets.status}>
      {sets.status === "loading" && <p className="mw-ligand-note" aria-busy="true">후보 집합 목록을 읽는 중</p>}
      {sets.status === "error" && <ErrorLine message={sets.message} onRetry={() => setSetsReload(value => value + 1)} />}
      {sets.status === "ready" && (!sets.value.rows.length ? <p className="mw-ligand-note">이 run에 후보 집합이 없습니다.</p>
        : <fieldset className="mw-ligand-choices" data-testid="ligand-candidate-sets">
          <legend>후보 집합 선택 (자동으로 고르지 않음, 각 집합은 자기 점검 결과에 묶임)</legend>
          {sets.value.rows.map(row => <label key={row.handle} data-ligand-candidate-set={row.handle}
            data-inspection-handle={row.inspection_handle ?? undefined} data-valid={row.valid} data-null-result={row.null_result ?? undefined}>
            <input type="radio" name={`ligand-set-${runId}`} checked={selectedSet === row.handle} disabled={!row.valid}
              onChange={() => openSet(row.handle)} />
            <span className="mw-mono">생성 순번 {row.created_seq} · {shortHandle(row.handle)} · {row.valid
              ? `점검 ${shortHandle(row.inspection_handle ?? "")}${row.inspection_handle === selectedInspection ? " (고른 점검)" : ""} · 부위 ${row.site_atoms?.join(", ")} · 고정 교체 ${row.use_fixed ? "사용" : "안 씀"} · 규칙 ${row.rule_ids?.length ? row.rule_ids.join(", ") : "없음"} · ${row.null_result ? "후보 0개 (빈 결과)" : `후보 ${row.candidates}개`}${row.limit_reached ? " · 상한 도달" : ""}`
              : `읽을 수 없음: ${ligandReasonText(row.reason_code ?? "evidence_invalid")}`}</span>
          </label>)}
        </fieldset>)}
      {sets.status !== "loading" && <Button size="sm" data-testid="ligand-sets-refresh" onClick={() => setSetsReload(value => value + 1)}>후보 집합 목록 다시 읽기</Button>}
      {setDetail?.handle === selectedSet && setDetail.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">후보 집합을 읽는 중</p>}
      {setDetail?.handle === selectedSet && setDetail.load.status === "error" &&
        <ErrorLine message={setDetail.load.message} onRetry={() => selectedSet && openSet(selectedSet)} />}
      {openedSet && <SetSummary detail={openedSet} />}
      {openedSet && <>
        <FilterForm input={filterInput} errors={filterErrors} applied={applied.spec} onInput={setFilterInput}
          onApply={applyFilters} onClear={clearFilters} />
        <div className="mw-ligand-inline" aria-label="표시 설정">
          <label className="mw-ligand-check"><input type="checkbox" data-testid="ligand-passes-only" checked={view.passesOnly}
            onChange={event => setView(previous => ({ ...previous, passesOnly: event.target.checked, offset: 0 }))} /> 필터 통과만 보기</label>
          <label className="mw-ligand-check">정렬
            <select className="mw-select" data-testid="ligand-sort" value={view.sort}
              onChange={event => setView(previous => ({ ...previous, sort: event.target.value as LigandSortKey, offset: 0 }))}>
              {SORT_KEYS.map(key => <option key={key} value={key}>{SORT_LABEL(key)}</option>)}
            </select></label>
          <label className="mw-ligand-check">방향
            <select className="mw-select" data-testid="ligand-direction" value={view.direction}
              onChange={event => setView(previous => ({ ...previous, direction: event.target.value as LigandSortDirection, offset: 0 }))}>
              <option value="asc">오름차순</option><option value="desc">내림차순</option>
            </select></label>
        </div>
        {rowsLoad?.status === "loading" && <p className="mw-ligand-note" aria-busy="true">후보 행을 읽는 중</p>}
        {rowsLoad?.status === "error" && <ErrorLine message={rowsLoad.message} onRetry={() => setRowsRetry(value => value + 1)} testId="ligand-rows-error" />}
        {page && <CandidateTable page={page} onPage={offset => setView(previous => ({ ...previous, offset }))} />}
        <div className="mw-ligand-inline" aria-label="후보 보고서">
          <Button size="sm" data-testid="ligand-report" disabled={report?.handle === selectedSet && report.load.status === "loading"}
            onClick={() => void makeReport()}>⑥ 보고서 만들기</Button>
          <span className="mw-ligand-note" data-testid="ligand-report-filter">보고서에 넣을 필터: {filterSummaryText(applied.spec)}</span>
        </div>
        {report?.handle === selectedSet && report.load.status === "loading" && <p className="mw-ligand-note" aria-busy="true">보고서를 만드는 중</p>}
        {report?.handle === selectedSet && report.load.status === "ready" && <p role="status" className="mw-ligand-note"
          data-testid="ligand-report-done" data-report-handle={report.load.value.handle}>
          보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서 열고 받을 수 있습니다.</p>}
        {report?.handle === selectedSet && report.load.status === "error" && <ErrorLine message={report.load.message} testId="ligand-report-error" />}
      </>}
    </Section>
  </section>;
}

function PropertyList({ properties, testId }: { properties: LigandProperties; testId: string }) {
  return <dl className="mw-ligand-facts" data-testid={testId}>
    {PROPERTY_NAMES.map(name => <div key={name} className="mw-ligand-fact" data-property={name}>
      <dt>{propertyHeader(name)}</dt><dd className="mw-mono">{propertyText(name, properties[name])}</dd></div>)}
  </dl>;
}

function InspectionView({ detail, site, onToggle }: { detail: LigandInspectionDetail; site: SiteSelection;
  onToggle: (serial: number) => void }) {
  const value = detail.inspection, parent = value.parent;
  return <div className="mw-ligand-inspection" data-testid="ligand-inspection" data-ligand-inspection-handle={detail.handle}>
    <p className="mw-ligand-note mw-mono">점검 {shortHandle(detail.handle)} · 작업 {detail.job_id} · 부모 {shortHandle(value.parent_handle)}
      · SDF 원자 {parent.atoms_in_sdf}개 · 중원자 {parent.heavy_atom_count}개 · {Object.entries(value.method).map(([key, text]) => `${key} ${text}`).join(" · ")}</p>
    <p className="mw-ligand-note">부모 정규 SMILES: <code className="mw-mono" data-testid="ligand-parent-smiles">{parent.canonical_smiles}</code></p>
    <div className="mw-ligand-parent">
      <figure className="mw-ligand-figure">
        <img className="mw-ligand-svg" data-testid="ligand-parent-svg" src={svgDataUri(parent.svg)}
          alt="부모 리간드 2D 그림 (RDKit, 원자 번호는 SDF 순번)" />
        <figcaption className="mw-ligand-note">RDKit 2D 그림 · 번호 = SDF 원자 순번 (수소 숨김)</figcaption>
      </figure>
      <div className="mw-ligand-table-wrap">
        <table className="mw-ligand-table" data-testid="ligand-atoms">
          <thead><tr><th>부위</th><th>번호 (SDF)</th><th>원소</th><th>형식 전하</th><th>이웃 (SDF 번호)</th></tr></thead>
          <tbody>{parent.atoms.map(atom => <tr key={atom.serial} data-atom-serial={atom.serial}>
            <td><input type="checkbox" aria-label={`원자 ${atom.serial} 부위에 넣기`} data-serial={atom.serial} data-element={atom.element}
              checked={siteAtomChecked(site, detail.handle, atom.serial)} onChange={() => onToggle(atom.serial)} /></td>
            <td className="mw-mono">{atom.serial}</td><td>{atom.element}</td><td className="mw-mono">{atom.formal_charge}</td>
            <td className="mw-mono">{atom.neighbors.join(", ")}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </div>
    <span className="mw-eyebrow">부모 속성 (RDKit 추정값)</span>
    <PropertyList properties={parent.properties} testId="ligand-parent-properties" />
    <span className="mw-eyebrow">building block 검증</span>
    <BlockSummary libraries={value.block_libraries} />
    <span className="mw-eyebrow">반응 규칙 검증</span>
    {!value.rules.length ? <p className="mw-ligand-note">반응 규칙 없음</p>
      : <ul className="mw-ligand-list" data-testid="ligand-rules-status">{value.rules.map(rule => <li key={rule.rule_id}
        data-rule-id={rule.rule_id} data-rule-status={rule.status}>
        <span className="mw-mono">{rule.rule_id}</span> · {ruleStatusText(rule)} · <code className="mw-mono">{rule.text ?? "텍스트 저장 안 함"}</code></li>)}</ul>}
  </div>;
}

function BlockSummary({ libraries }: { libraries: LigandBlockLibrary[] }) {
  const limit = blockLimitText(libraries);
  if (!libraries.length) return <p className="mw-ligand-note" data-testid="ligand-blocks">building block 없음 (가져온 라이브러리 없음)</p>;
  return <div data-testid="ligand-blocks">
    {limit && <p role="status" className="mw-ligand-unavailable" data-testid="ligand-block-limit">{limit}</p>}
    {libraries.map(library => <div key={library.kind} className="mw-ligand-block" data-block-kind={library.kind}
      data-block-limit-reached={library.block_limit_reached}>
      <p className="mw-ligand-note mw-mono">{library.kind} ({library.input_format}) · 레코드 {library.records_total}개 중 {library.records_read}개 읽음
        · 수락 {countText(library.accepted)} · 거부 {countText(library.rejected_total)} · 고정 교체 대상 {countText(library.fixed_targets)}
        · 규칙 대상 {countText(library.rule_targets)}{library.block_limit_reached ? " · block 상한 도달 (block_limit_reached)" : ""}</p>
      {Object.keys(library.rejected_counts).length > 0 && <p className="mw-ligand-note">거부 이유별 개수: {Object.entries(library.rejected_counts)
        .map(([code, count]) => <span key={code} data-rejected-reason={code} data-count={count}>{ligandReasonText(code)} {count}개 </span>)}</p>}
      {library.rejected.length > 0 && <details><summary>거부된 레코드 {library.rejected.length}개 (최대 200개 표시)</summary>
        <ul className="mw-ligand-list">{library.rejected.map(item => <li key={`${item.ordinal}`} data-rejected-ordinal={item.ordinal}>
          #{item.ordinal} <code className="mw-mono">{item.name}</code> · {ligandReasonText(item.reason)}</li>)}</ul></details>}
    </div>)}
  </div>;
}

function PreviewView({ preview }: { preview: LigandSitePreview }) {
  const check = preview.site_check;
  return <div className="mw-ligand-preview" data-testid="ligand-preview" data-ligand-preview-ready={preview.ready}
    data-site-valid={check.valid} data-site-reason={check.reason ?? undefined}>
    <p className={check.valid ? "mw-ligand-note" : "mw-ligand-unavailable"} role="status">
      {check.valid ? `부위 검사 통과: 부위와 나머지를 잇는 결합 1개 (${check.crossing_bonds?.map(bond =>
        `코어 ${bond.core_atom} – 부위 ${bond.site_atom}, ${bond.order}`).join("; ")})`
        : `부위 검사 거절: ${ligandReasonText(check.reason ?? "")}`}</p>
    {check.unknown_atoms?.length ? <p className="mw-ligand-note">원자 표에 없는 번호: {check.unknown_atoms.join(", ")}</p> : null}
    {check.valid && check.site_hydrogens?.length ? <p className="mw-ligand-note">부위와 함께 떼는 명시적 수소 (SDF 번호): {check.site_hydrogens.join(", ")}</p> : null}
    {preview.rules.length > 0 && <p className="mw-ligand-note">고른 규칙: {preview.rules.map(rule =>
      `${rule.rule_id} ${rule.usable ? "사용 가능" : `사용 불가 (${ligandReasonText(rule.status ?? "rule_invalid")})`}`).join(" · ")}</p>}
    {preview.blocking_reasons.length > 0 && <ul className="mw-ligand-errors" data-testid="ligand-preview-blocking">
      {previewBlockingText(preview).map((text, index) => <li key={text} data-blocking-reason={preview.blocking_reasons[index]}>{text}</li>)}</ul>}
  </div>;
}

function CountsView({ counts }: { counts: LigandCounts }) {
  const rejected = [...PRODUCT_REJECT_REASONS.filter(code => code in counts.rejected),
    ...Object.keys(counts.rejected).filter(code => !(PRODUCT_REJECT_REASONS as readonly string[]).includes(code))];
  return <div data-testid="ligand-counts" data-candidates={counts.candidates} data-raw-products={counts.raw_products}
    data-duplicate-products={counts.duplicate_products}>
    <p className="mw-ligand-note mw-mono">수락 block {countText(counts.blocks_accepted)} · 원시 생성물 {countText(counts.raw_products)}
      · 후보 {countText(counts.candidates)} · 중복 생성물 (duplicate_products) {countText(counts.duplicate_products)}</p>
    <p className="mw-ligand-note">거부 이유별 개수: {rejected.length ? rejected.map(code => <span key={code} data-rejected-reason={code}
      data-count={counts.rejected[code]}>{ligandReasonText(code)} {countText(counts.rejected[code])}개 </span>) : "기록된 거부 없음"}</p>
    <p className="mw-ligand-note">규칙별 적용 불가 (not_applicable): {Object.keys(counts.not_applicable).length
      ? Object.entries(counts.not_applicable).map(([rule, count]) => <span key={rule} data-not-applicable-rule={rule} data-count={count}>
        {rule} {countText(count)}개 </span>) : "기록 없음"}</p>
  </div>;
}

function SetSummary({ detail }: { detail: LigandCandidateSetDetail }) {
  const set = detail.candidate_set;
  const limit = limitReachedText(set), blocks = blockLimitText(set.block_libraries);
  return <div className="mw-ligand-set" data-testid="ligand-set-detail" data-ligand-set-handle={detail.handle}
    data-candidate-count={detail.candidate_count} data-limit-reached={set.limit_reached} data-null-result={detail.candidate_count === 0}>
    <p className="mw-ligand-note mw-mono">후보 집합 {shortHandle(detail.handle)} · 작업 {detail.job_id} · 점검 {shortHandle(set.inspection_handle)}에 묶임
      · {Object.entries(set.method).map(([key, text]) => `${key} ${text}`).join(" · ")}</p>
    <p className="mw-ligand-note">부위 (SDF 번호): {set.site_atoms.join(", ")} · 교차 결합 코어 {set.crossing_bond.core_atom} – 부위 {set.crossing_bond.site_atom}
      ({set.crossing_bond.order}) · 남긴 부모 중원자 {set.retained_parent_atoms.length}개</p>
    <ul className="mw-ligand-list" data-testid="ligand-rules-used">{set.rules_used.map(rule => <li key={rule.rule_id} data-rule-id={rule.rule_id}>
      <span className="mw-mono">{rule.rule_id} · {rule.method}</span>{rule.text !== null && <> · <code className="mw-mono">{rule.text}</code></>}</li>)}</ul>
    {detail.candidate_count === 0 && <p role="status" className="mw-ligand-null" data-testid="ligand-set-null">
      후보 0개 · 빈 과학 결과입니다(실패가 아님). 아래 거부 이유별 개수와 규칙별 적용 불가 개수를 확인하세요.</p>}
    <CountsView counts={set.counts} />
    {limit && <p role="status" className="mw-ligand-unavailable" data-testid="ligand-limit-reached" data-stop-reason={set.stop_reason ?? undefined}>{limit}</p>}
    {blocks && <p role="status" className="mw-ligand-unavailable" data-testid="ligand-block-limit">{blocks}</p>}
    <details open data-testid="ligand-limitations"><summary>한계</summary>
      {set.limitations.map((text, index) => <p key={index} className="mw-ligand-note">{text}</p>)}</details>
  </div>;
}

/** Also used by the batch docking area with its own `idPrefix` (test ids must not collide in the same tab). */
export function FilterForm({ input, errors, applied, onInput, onApply, onClear, idPrefix = "ligand" }: { input: LigandFilterInput;
  errors: string[]; applied: LigandFilterSpec; onInput: (next: LigandFilterInput) => void; onApply: () => void;
  onClear: () => void; idPrefix?: string }) {
  const setBound = (name: LigandPropertyName, side: "min" | "max", text: string) =>
    onInput({ ...input, ranges: { ...input.ranges, [name]: { ...input.ranges[name], [side]: text } } });
  return <form className="mw-ligand-filters" data-testid={`${idPrefix}-filters`} aria-label="후보 필터"
    onSubmit={event => { event.preventDefault(); onApply(); }}>
    <p className="mw-ligand-note">필터는 저장된 RDKit 추정값에 서버가 적용합니다(경계 포함, 비우면 범위 없음). 후보를 다시 생성하지 않습니다.</p>
    <div className="mw-ligand-filter-grid">
      {PROPERTY_NAMES.map(name => <div key={name} className="mw-ligand-filter" data-filter-property={name}>
        <span>{propertyHeader(name)}</span>
        <input className="mw-ligand-input" inputMode="decimal" aria-label={`${PROPERTY_LABEL[name]} 최솟값`} placeholder="최솟값"
          data-testid={`${idPrefix}-filter-${name}-min`} value={input.ranges[name].min} onChange={event => setBound(name, "min", event.target.value)} />
        <input className="mw-ligand-input" inputMode="decimal" aria-label={`${PROPERTY_LABEL[name]} 최댓값`} placeholder="최댓값"
          data-testid={`${idPrefix}-filter-${name}-max`} value={input.ranges[name].max} onChange={event => setBound(name, "max", event.target.value)} />
      </div>)}
    </div>
    <label className="mw-ligand-check"><input type="checkbox" data-testid={`${idPrefix}-filter-pains`} checked={input.painsExclude}
      onChange={event => onInput({ ...input, painsExclude: event.target.checked })} /> {PAINS_HEADER} 후보 제외</label>
    <div className="mw-ligand-inline">
      <Button size="sm" type="submit" data-testid={`${idPrefix}-filter-apply`}>필터 적용</Button>
      <Button size="sm" type="button" data-testid={`${idPrefix}-filter-clear`} onClick={onClear}>필터 지우기</Button>
      <span className="mw-ligand-note" data-testid={`${idPrefix}-filter-applied`} data-applied-count={appliedFilterCount(applied)}>{filterSummaryText(applied)}</span>
    </div>
    {errors.length > 0 && <ul className="mw-ligand-errors" role="alert" data-testid={`${idPrefix}-filter-errors`}>
      {errors.map(error => <li key={error}>{error}</li>)}</ul>}
  </form>;
}

function CandidateTable({ page, onPage }: { page: LigandCandidatePage; onPage: (offset: number) => void }) {
  const filterKeys = [...PROPERTY_NAMES.filter(name => page.filter_spec.ranges[name]),
    ...(page.filter_spec.pains_exclude ? [PAINS_FILTER] : [])];
  const filterLabel = (key: string) => key === PAINS_FILTER ? "PAINS 제외" : `${PROPERTY_LABEL[key as LigandPropertyName]} 범위`;
  const first = page.rows.length ? page.offset + 1 : 0, last = page.offset + page.rows.length;
  return <div className="mw-ligand-candidates">
    <p className="mw-ligand-note" data-testid="ligand-candidate-count" data-total={page.total} data-passing={page.passing ?? undefined}
      data-failing={page.failing ?? undefined} data-hidden={page.hidden_by_filter} data-matched={page.matched}>{candidateCountText(page)}</p>
    {page.total === 0 ? <p className="mw-ligand-note">표시할 후보 행이 없습니다 (후보 0개).</p> : <>
      <div className="mw-ligand-table-wrap">
        <table className="mw-ligand-table" data-testid="ligand-candidates">
          <thead><tr><th>생성 순서</th><th>SMILES (2D)</th><th>입체 (stereo_flag)</th><th>출처 (규칙 · block)</th>
            {PROPERTY_NAMES.map(name => <th key={name}>{propertyHeader(name)}</th>)}<th>{PAINS_HEADER}</th>
            {filterKeys.map(key => <th key={key}>{filterLabel(key)}</th>)}<th>모든 필터</th></tr></thead>
          <tbody>
            <tr className="mw-ligand-parent-row" data-testid="ligand-parent-row">
              <td>부모</td><td className="mw-mono">{page.parent_canonical_smiles}</td><td>—</td><td>—</td>
              {PROPERTY_NAMES.map(name => <td key={name} className="mw-mono" data-property={name}>{propertyText(name, page.parent_properties[name])}</td>)}
              <td>—</td>{filterKeys.map(key => <td key={key}>—</td>)}<td>—</td>
            </tr>
            {page.rows.map(row => { const candidate = row.candidate;
              return <tr key={candidate.id} data-candidate-id={candidate.id} data-generation-order={row.generation_order}
                data-passes-all={row.passes_all === null ? "null" : String(row.passes_all)} data-stereo-flag={candidate.stereo_flag}>
                <td className="mw-mono">{row.generation_order}</td>
                <td className="mw-mono mw-ligand-smiles">{candidate.smiles}</td>
                <td>{ligandReasonText(candidate.stereo_flag)}</td>
                <td>{candidate.origins.map((origin, index) => <span key={index} className="mw-ligand-origin">
                  <span className="mw-mono">{origin.rule_id}</span> · {origin.block_name}</span>)}</td>
                {PROPERTY_NAMES.map(name => <td key={name} className="mw-mono" data-property={name}>{propertyText(name, candidate.properties[name])}</td>)}
                <td data-pains-count={candidate.pains.matches.length}>{painsText(candidate.pains.matches)}</td>
                {filterKeys.map(key => <td key={key} data-filter={key} data-pass={key in row.filters ? String(row.filters[key]) : "missing"}>
                  {key in row.filters ? passText(row.filters[key]) : "—"}</td>)}
                <td data-testid="ligand-passes-all-cell">{passText(row.passes_all)}</td>
              </tr>; })}
          </tbody>
        </table>
      </div>
      <div className="mw-ligand-inline">
        <Button size="sm" data-testid="ligand-page-prev" disabled={page.offset === 0}
          onClick={() => onPage(Math.max(0, page.offset - page.limit))}>이전</Button>
        <span className="mw-ligand-note" data-testid="ligand-page" data-offset={page.offset}>행 {first}–{last} / {page.matched}</span>
        <Button size="sm" data-testid="ligand-page-next" disabled={last >= page.matched}
          onClick={() => onPage(page.offset + page.limit)}>다음</Button>
      </div>
    </>}
  </div>;
}
