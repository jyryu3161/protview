"use client";

import { useEffect, useRef, useState } from "react";
import { api, type MethodReportArtifact, type RunSummary } from "@/lib/api";
import type { ReferenceSiteAnnotation, RunEvent, SiteAnnotationList } from "@/lib/contracts";
import { residueText, snapshotBadge, type NumberingMapList } from "@/lib/numbering";
import { annotationMatchesSource, annotationPanelState, annotationResponseCurrent, annotationsForSource, CONTACT_TYPE_LABEL,
  CONTACT_TYPES, contactCountText, contactSetsForSource, createAnnotationArgs, INITIAL_CONTACT_CHOICE,
  KLIFS_REFERENCE_NOTE, MIN_DISTANCE_NOTE, minDistanceText, NO_CONTACT_RESULT_TEXT, NO_MAP_PREREQUISITE,
  NULL_RESULT_TEXT, PANEL_LEGEND_TEXT, reconcileContactChoice, reconcileMapChoice, SCIENTIFIC_NULL_LABEL,
  SITE_ANNOTATION_REPORT_TYPE, SITE_OTHER_CONTACT_TOKEN, SITE_POLAR_LINE_TOKEN, SITE_REGION_TOKEN, siteReasonText,
  siteRegion, siteStatusText, mapsForSource, type AnnotationStamp, type ContactChoice, type SiteAnnotationReadback,
  type SiteAnnotationShown, type SiteRegion } from "@/lib/site-annotation";
import { Button } from "./primitives";

const PAGE_LIMIT = 100;
const STATE_TEXT = { loading: "불러오는 중", ready: "준비", scientific_null: SCIENTIFIC_NULL_LABEL, failure: "실패",
  unavailable: "사용할 수 없음" } as const;
const REGIONS: readonly SiteRegion[] = ["III", "αC", "GK", "hinge", "xDFG"];
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e);
const shortHandle = (handle: string) => handle.split("/").at(-1)?.slice(0, 12) ?? handle;

type Area = "maps" | "annotations" | "detail" | "create" | "report";
type Load<T> = { status: "idle" } | { status: "loading" } | { status: "ready"; value: T } | { status: "error"; message: string };

export interface SiteAnnotationPanelProps {
  run: RunSummary;
  /** undefined while capabilities are being read; null when the backend reports no such method. */
  capability: { available: boolean; reason: string | null } | null | undefined;
  /** The displayed (or loading) structure-screen source; only structure / prepared_structure can carry an annotation. */
  sourceHandle: string | null;
  sourceKind: string | null;
  /** The viewer shows `sourceHandle` and its atom catalog is validated. */
  viewerReady: boolean;
  events: RunEvent[];
  /** Reason the annotation cannot be turned on (source kind, pocket overlay, comparison). */
  blockedReason: string | null;
  shown: SiteAnnotationShown | null;
  /** Native readback / error of the shown annotation (viewer bridge), for the shown key only. */
  applied: SiteAnnotationReadback | null;
  appliedError: string | null;
  onShow: (requestRunId: string, request: SiteAnnotationShown | null) => void;
  onObjectsChanged: (runId: string) => void;
  onReportCreated: () => void;
  /** Changes when numbering maps may have been made elsewhere (지식·보고서 tab): re-reads the run's map list. */
  mapsReloadToken?: number;
}

async function allMaps(runId: string, signal: AbortSignal): Promise<NumberingMapList> {
  const first = await api.numberingMaps(runId, 0, PAGE_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.numberingMaps(runId, rows.length, PAGE_LIMIT, signal);
    if (page.total !== first.total || !page.rows.length) throw new Error("번호 대응 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  return { ...first, offset: 0, limit: rows.length, rows };
}

async function allAnnotations(runId: string, structure: string, signal: AbortSignal): Promise<SiteAnnotationList> {
  const first = await api.siteAnnotations(runId, structure, 0, PAGE_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.siteAnnotations(runId, structure, rows.length, PAGE_LIMIT, signal);
    if (page.total !== first.total || !page.rows.length) throw new Error("주석 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  if (first.schema !== "reference_site_annotation_list@1") throw new Error("주석 목록 형식이 다릅니다.");
  return { ...first, offset: 0, limit: rows.length, rows };
}

function StaleBadge({ badge, hash }: { badge: "stale" | "no_active_set" | null; hash: string }) {
  return badge === "stale" ? <span className="mw-numbering-badge mw-numbering-badge--stale" title={hash}>이전 스냅샷 기준</span>
    : badge === "no_active_set" ? <span className="mw-numbering-badge mw-numbering-badge--stale" title={hash}>사용 중 스냅샷 없음</span>
      : null;
}

export function SiteAnnotationPanel(p: SiteAnnotationPanelProps) {
  const runId = p.run.run_id;
  const source = p.sourceHandle;
  const [maps, setMaps] = useState<Load<NumberingMapList>>({ status: "idle" });
  const [mapsRetry, setMapsRetry] = useState(0);
  const [annotations, setAnnotations] = useState<Load<SiteAnnotationList>>({ status: "idle" });
  const [annotationsRetry, setAnnotationsRetry] = useState(0);
  const [mapChoice, setMapChoice] = useState<string | null>(null);
  const [contactChoice, setContactChoice] = useState<ContactChoice>(INITIAL_CONTACT_CHOICE);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ handle: string; load: Load<ReferenceSiteAnnotation> } | null>(null);
  const [legend, setLegend] = useState(true);
  const [createState, setCreateState] = useState<Load<string>>({ status: "idle" });
  const [report, setReport] = useState<{ handle: string; load: Load<MethodReportArtifact> } | null>(null);

  // Late responses: the panel is keyed by run; every area also checks the source and its own request sequence.
  const mounted = useRef(true);
  const seqs = useRef<Record<Area, number>>({ maps: 0, annotations: 0, detail: 0, create: 0, report: 0 });
  const live = useRef({ runId, sourceHandle: source });
  live.current = { runId, sourceHandle: source };
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; for (const area of Object.keys(seqs.current) as Area[]) seqs.current[area] += 1; };
  }, []);
  const stamp = (area: Area): AnnotationStamp => ({ ...live.current, seq: ++seqs.current[area] });
  const current = (area: Area, captured: AnnotationStamp) => mounted.current &&
    annotationResponseCurrent(captured, { ...live.current, seq: seqs.current[area],
      // The numbering map list is run-wide (filtered by source at render), so only run and sequence bind it.
      ...(area === "maps" ? { sourceHandle: captured.sourceHandle } : {}) });
  const latest = useRef(p);
  latest.current = p;

  // A source change drops every source-bound choice and invalidates pending source-bound responses.
  useEffect(() => {
    for (const area of ["annotations", "detail", "create", "report"] as Area[]) seqs.current[area] += 1;
    setMapChoice(null); setContactChoice(INITIAL_CONTACT_CHOICE); setSelected(null); setDetail(null);
    setCreateState({ status: "idle" }); setReport(null); setAnnotations({ status: "idle" });
  }, [source]);

  useEffect(() => {
    const captured = stamp("maps");
    const controller = new AbortController();
    setMaps({ status: "loading" });
    allMaps(runId, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (current("maps", captured)) setMaps({ status: "ready", value });
    }).catch(e => { if (current("maps", captured)) setMaps({ status: "error", message: `번호 대응 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // stamp/current read live refs; the read is keyed by run, retry and the reload token.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, mapsRetry, p.mapsReloadToken]);

  useEffect(() => {
    if (!source) return;
    const captured = stamp("annotations");
    const controller = new AbortController();
    setAnnotations({ status: "loading" });
    allAnnotations(runId, source, AbortSignal.any([controller.signal, AbortSignal.timeout(30000)])).then(value => {
      if (current("annotations", captured)) setAnnotations({ status: "ready", value });
    }).catch(e => { if (current("annotations", captured)) setAnnotations({ status: "error", message: `주석 목록 읽기 실패: ${errorText(e)}` }); });
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, source, annotationsRetry]);

  // The page may show an annotation the panel did not pick (viewer_scene@2 restore): follow it.
  const shownHandle = p.shown && p.shown.sourceHandle === source ? p.shown.handle : null;
  useEffect(() => {
    const shown = latest.current.shown;
    if (!shown || shown.handle !== shownHandle || shown.sourceHandle !== live.current.sourceHandle) return;
    seqs.current.detail += 1;
    setSelected(shown.handle); setDetail({ handle: shown.handle, load: { status: "ready", value: shown.annotation } });
    setLegend(shown.legend);
  }, [shownHandle]);

  function openAnnotation(handle: string) {
    if (!source) return;
    const shown = latest.current.shown;
    if (shown && shown.handle !== handle) latest.current.onShow(runId, null);
    const captured = stamp("detail");
    setSelected(handle); setDetail({ handle, load: { status: "loading" } }); setReport(null);
    api.siteAnnotation(runId, handle, AbortSignal.timeout(30000)).then(value => {
      if (!current("detail", captured)) return;
      if (value.meta.handle !== handle || value.meta.kind !== "reference_site_annotation" ||
          value.annotation.schema !== "reference_site_annotation@1" || !annotationMatchesSource(value.annotation, captured.sourceHandle))
        throw new Error("주석 내용이 고른 handle 또는 표시 중인 구조와 다릅니다.");
      setDetail({ handle, load: { status: "ready", value: value.annotation } });
    }).catch(e => { if (current("detail", captured)) setDetail({ handle, load: { status: "error", message: `주석 읽기 실패: ${errorText(e)}` } }); });
  }

  const allMapRows = maps.status === "ready" ? maps.value.rows : [];
  const sourceMaps = mapsForSource(allMapRows, source);
  const snapshotAvailable = maps.status === "ready" && maps.value.snapshot_available;
  const contactSets = contactSetsForSource(p.events, source);
  const mapPick = reconcileMapChoice(mapChoice, sourceMaps);
  const contactPick = reconcileContactChoice(contactChoice, contactSets);
  const annotationRows = annotations.status === "ready" ? annotationsForSource(annotations.value.rows, source) : [];
  const annotationSnapshot = annotations.status === "ready" && annotations.value.active_set_hash !== null;
  const opened = detail && detail.handle === selected && detail.load.status === "ready" ? detail.load.value : null;
  const create = createAnnotationArgs({ sourceHandle: source, mapHandle: mapPick, contactChoice: contactPick,
    maps: allMapRows, contactSets });

  const panelState = annotationPanelState({ sourceKind: p.sourceKind,
    capability: p.capability === undefined ? undefined : p.capability === null ? null
      : { available: p.capability.available, reason: p.capability.reason },
    loading: maps.status === "loading" || annotations.status === "loading" || detail?.load.status === "loading",
    error: (detail?.handle === selected && detail?.load.status === "error" ? detail.load.message : null) ??
      (annotations.status === "error" ? annotations.message : null) ?? (maps.status === "error" ? maps.message : null),
    annotation: opened });

  async function makeAnnotation() {
    if (!create.ok || createState.status === "loading") return;
    const captured = stamp("create");
    setCreateState({ status: "loading" });
    try {
      const result = await api.annotateReferenceSites(runId, create.args.numbering_map, create.args.contacts);
      if (!current("create", captured)) return;
      if (!result.ok) {
        const message = "message" in result ? `${result.error}${typeof result.detail?.reason_code === "string"
          ? ` (${result.detail.reason_code})` : ""}: ${result.message}` : "approval" in result ? result.approval.reason : result.loop_stop.reason;
        setCreateState({ status: "error", message: `주석 만들기 실패: ${message}` });
        return;
      }
      if (result.handle.kind !== "reference_site_annotation") throw new Error("도구 결과가 참조 주석이 아닙니다.");
      setCreateState({ status: "ready", value: result.handle.handle });
      latest.current.onObjectsChanged(runId);
      setAnnotationsRetry(value => value + 1);
      openAnnotation(result.handle.handle);
    } catch (e) { if (current("create", captured)) setCreateState({ status: "error", message: `주석 만들기 실패: ${errorText(e)}` }); }
  }

  async function makeReport() {
    if (!opened || !selected || report?.load.status === "loading") return;
    const handle = selected, captured = stamp("report");
    setReport({ handle, load: { status: "loading" } });
    try {
      const artifact = await api.createSiteAnnotationReport(runId, handle, AbortSignal.timeout(60000));
      if (!current("report", captured)) return;
      if (artifact.manifest.schema !== "method_report_manifest@1" ||
          artifact.manifest.analysis_type !== SITE_ANNOTATION_REPORT_TYPE || artifact.manifest.result_handle !== handle)
        throw new Error("보고서가 고른 주석과 다릅니다.");
      setReport({ handle, load: { status: "ready", value: artifact } });
      latest.current.onReportCreated();
    } catch (e) { if (current("report", captured)) setReport({ handle, load: { status: "error", message: `보고서 만들기 실패: ${errorText(e)}` } }); }
  }

  const shownHere = p.shown && p.shown.sourceHandle === source && p.shown.handle === selected ? p.shown : null;
  const appliedHere = shownHere && p.applied && p.applied.handle === shownHere.handle && p.applied.legend === shownHere.legend
    ? p.applied : null;
  const showDisabledReason = p.blockedReason ?? (!opened ? "표시할 주석을 고르세요."
    : !p.viewerReady ? "구조가 뷰어에 표시될 때까지 기다리세요." : null);

  function toggleShown() {
    if (shownHere) { p.onShow(runId, null); return; }
    if (showDisabledReason || !opened || !selected || !source) return;
    p.onShow(runId, { runId, sourceHandle: source, handle: selected, annotation: opened, legend });
  }
  function toggleLegend(value: boolean) {
    setLegend(value);
    if (shownHere) p.onShow(runId, { ...shownHere, legend: value });
  }

  const unavailable = panelState.state === "unavailable";
  return <section className="mw-site-annotation" aria-label="참조 주석" data-testid="site-annotation-panel"
    data-site-annotation-state={panelState.state}>
    <div className="mw-site-annotation-head"><strong>참조 주석</strong>
      <span className="mw-badge" data-testid="site-annotation-state">{STATE_TEXT[panelState.state]}</span></div>
    {panelState.state === "unavailable" && <p role="status" className="mw-site-annotation-blocked"
      data-testid="site-annotation-unavailable">{panelState.reason}</p>}
    {panelState.state === "failure" && <p role="alert" className="mw-table-error" data-testid="site-annotation-failure">{panelState.message}</p>}
    {!unavailable && <>
      <p className="mw-muted">KLIFS 주요 자리(참조값)와 저장된 기하 접촉 결과(계산값)를 같은 구조 handle에서만 합칩니다.</p>

      <div className="mw-site-annotation-group" aria-label="참조 주석 만들기">
        <span className="mw-eyebrow">번호 대응 (이 구조 handle)</span>
        {maps.status === "loading" && <p className="mw-muted" aria-busy="true">번호 대응 목록을 읽는 중…</p>}
        {maps.status === "error" && <div role="alert" className="mw-table-error"><p>{maps.message}</p>
          <Button size="sm" data-testid="site-annotation-maps-retry" onClick={() => setMapsRetry(value => value + 1)}>번호 대응 목록 다시 읽기</Button></div>}
        {maps.status === "ready" && !sourceMaps.length && <p role="status" className="mw-site-annotation-blocked"
          data-testid="site-annotation-prerequisite">{NO_MAP_PREREQUISITE}</p>}
        {sourceMaps.length > 0 && <fieldset className="mw-site-annotation-choices" data-testid="site-annotation-maps">
          <legend>번호 대응 선택</legend>
          {sourceMaps.map(row => { const badge = snapshotBadge(row, snapshotAvailable);
            return <label key={row.handle} data-site-map={row.handle} data-stale={badge === "stale"} data-no-active-set={badge === "no_active_set"}>
              <input type="radio" name={`site-map-${runId}`} checked={mapPick === row.handle} onChange={() => setMapChoice(row.handle)} />
              <span className="mw-mono">{row.structure_kind} · 모델 {row.model_number} · 체인 {row.chains.join(", ")} · {row.pdb_id ?? "PDB ID 없음"} · 생성 순번 {row.created_seq} · {shortHandle(row.handle)}</span>
              <StaleBadge badge={badge} hash={row.set_hash} />
            </label>; })}
        </fieldset>}

        <span className="mw-eyebrow">접촉 결과 (이 구조 handle)</span>
        <fieldset className="mw-site-annotation-choices" data-testid="site-annotation-contacts">
          <legend>접촉 결과 선택 (자동으로 고르지 않음)</legend>
          <label data-site-contact="none"><input type="radio" name={`site-contact-${runId}`} checked={contactPick.kind === "none"}
            onChange={() => setContactChoice({ kind: "none" })} /> 접촉 결과 없이</label>
          {contactSets.map(option => <label key={option.handle} data-site-contact={option.handle}>
            <input type="radio" name={`site-contact-${runId}`} checked={contactPick.kind === "set" && contactPick.handle === option.handle}
              onChange={() => setContactChoice({ kind: "set", handle: option.handle })} />
            <span className="mw-mono">리간드 {residueText(option.ligand)} · cutoff {option.cutoff_A} Å · 종류 {option.types.join(", ")}
              {option.null_result ? " · 접촉 행 0 (scientific_null)" : option.n_edges !== null ? ` · 접촉 행 ${option.n_edges}` : ""} · {shortHandle(option.handle)}</span>
          </label>)}
          {!contactSets.length && <p className="mw-muted">이 구조의 접촉 결과가 없습니다. 접촉 결과 없이 주석할 수 있습니다.</p>}
        </fieldset>
        <Button size="sm" variant="primary" data-testid="site-annotation-create" disabled={!create.ok || createState.status === "loading"}
          title={create.ok ? undefined : create.errors.join(" ")} onClick={() => void makeAnnotation()}>주석 만들기</Button>
        {!create.ok && <span className="mw-muted" data-testid="site-annotation-create-reason">{create.errors.join(" ")}</span>}
        {createState.status === "loading" && <p role="status" className="mw-muted">annotate_reference_sites 실행 중…</p>}
        {createState.status === "error" && <p role="alert" className="mw-table-error" data-testid="site-annotation-create-error">{createState.message}</p>}
      </div>

      <div className="mw-site-annotation-group" aria-label="저장된 참조 주석">
        <span className="mw-eyebrow">이 구조의 주석</span>
        {annotations.status === "error" && <div role="alert" className="mw-table-error"><p>{annotations.message}</p>
          <Button size="sm" data-testid="site-annotation-list-retry" onClick={() => setAnnotationsRetry(value => value + 1)}>주석 목록 다시 읽기</Button></div>}
        {annotations.status === "ready" && !annotationRows.length && <p className="mw-muted">이 구조로 만든 주석이 없습니다.</p>}
        {annotationRows.length > 0 && <fieldset className="mw-site-annotation-choices" data-testid="site-annotation-list">
          <legend>주석 선택</legend>
          {annotationRows.map(row => { const badge = snapshotBadge(row, annotationSnapshot);
            return <label key={row.handle} data-site-annotation-row={row.handle} data-stale={badge === "stale"}
              data-no-active-set={badge === "no_active_set"} data-null-result={row.null_result}>
              <input type="radio" name={`site-annotation-${runId}`} checked={selected === row.handle} onChange={() => openAnnotation(row.handle)} />
              <span className="mw-mono">생성 순번 {row.created_seq} · 주석됨 {row.counts.annotated} · 없음 {row.counts.absent}
                · {row.contacts ? `접촉 결과 ${shortHandle(row.contacts)}` : NO_CONTACT_RESULT_TEXT} · 대응 {shortHandle(row.numbering_map)} · {shortHandle(row.handle)}</span>
              <StaleBadge badge={badge} hash={row.set_hash} />
            </label>; })}
        </fieldset>}
        {detail?.handle === selected && detail.load.status === "error" && selected &&
          <Button size="sm" data-testid="site-annotation-detail-retry" onClick={() => openAnnotation(selected)}>주석 다시 읽기</Button>}
        <div className="mw-chemical-inline">
          <Button size="sm" data-testid="site-annotation-toggle" aria-pressed={!!shownHere}
            disabled={!shownHere && !!showDisabledReason} title={shownHere ? undefined : showDisabledReason ?? undefined}
            onClick={toggleShown}>{shownHere ? "주석 끄기" : "주석 표시"}</Button>
          <label><input type="checkbox" data-testid="site-annotation-legend" checked={legend}
            onChange={e => toggleLegend(e.target.checked)} /> 그림 범례 넣기</label>
        </div>
        {!shownHere && showDisabledReason && <p role="status" className="mw-site-annotation-blocked"
          data-testid="site-annotation-show-reason">{showDisabledReason}</p>}
        {shownHere && <p role="status" className="mw-muted" data-testid="site-annotation-viewer-status"
          data-site-annotation-viewer={appliedHere ? "applied" : p.appliedError ? "error" : "pending"}>
          {appliedHere ? `뷰어 표시 확인 · 부위 ${appliedHere.drawnSiteCount}개 · 점선 ${appliedHere.drawnLineCount}개 · 그리지 못한 점선 ${appliedHere.undrawnPairs.length}개 (Mol* 읽기 확인)`
            : p.appliedError ? `주석 표시 실패: ${p.appliedError}` : "Mol*에 주석을 적용하는 중…"}</p>}
      </div>

      {opened && selected && <SiteTable annotation={opened} handle={selected} applied={appliedHere}
        nullResult={panelState.state === "scientific_null"} />}

      {opened && selected && <div className="mw-site-annotation-group" aria-label="참조 주석 보고서">
        <Button size="sm" data-testid="site-annotation-report" disabled={report?.handle === selected && report.load.status === "loading"}
          onClick={() => void makeReport()}>보고서 만들기</Button>
        {report?.handle === selected && report.load.status === "loading" && <p role="status" className="mw-muted">보고서를 만드는 중…</p>}
        {report?.handle === selected && report.load.status === "ready" && <p role="status" className="mw-capability"
          data-testid="site-annotation-report-done" data-report-handle={report.load.value.handle}>
          보고서를 저장했습니다 · {shortHandle(report.load.value.handle)}. 지식·보고서 탭의 보고서 목록에서 열고 받을 수 있습니다.</p>}
        {report?.handle === selected && report.load.status === "error" && <p role="alert" className="mw-table-error"
          data-testid="site-annotation-report-error">{report.load.message}</p>}
      </div>}

      <div className="mw-site-annotation-group" aria-label="참조 주석 범례" data-testid="site-annotation-legend-text">
        <p>{PANEL_LEGEND_TEXT}</p>
        <p className="mw-muted">{KLIFS_REFERENCE_NOTE}</p>
        <p className="mw-site-annotation-swatches">{REGIONS.map(region => <span key={region}>
          <i className="mw-site-swatch" style={{ background: `var(--${SITE_REGION_TOKEN[region]})` }} /> {region} 구역 부위</span>)}
          <span><i className="mw-site-swatch" style={{ background: `var(--${SITE_OTHER_CONTACT_TOKEN})` }} /> 다른 접촉 잔기(색만)</span>
          <span><i className="mw-site-swatch mw-site-swatch--line" style={{ borderColor: `var(--${SITE_POLAR_LINE_TOKEN})` }} /> 점선</span></p>
      </div>
    </>}
  </section>;
}

function SiteTable({ annotation, handle, applied, nullResult }: { annotation: ReferenceSiteAnnotation; handle: string;
  applied: SiteAnnotationReadback | null; nullResult: boolean }) {
  const contacts = annotation.contacts;
  return <div className="mw-site-annotation-group" aria-label="주요 부위 표" data-testid="site-annotation-sites"
    data-site-annotation-handle={handle} data-null-result={annotation.null_result}>
    <p className="mw-mono">주석 {shortHandle(handle)} · 대응 {shortHandle(annotation.numbering_map)} · 부위 목록 {annotation.site_set.id}
      · 스냅샷 세트 {annotation.snapshot_set_hash.slice(0, 12)}</p>
    {contacts ? <p className="mw-mono" data-testid="site-annotation-contact-source">접촉 결과 {shortHandle(contacts.handle)} · 리간드 {residueText(contacts.ligand)}
      · cutoff {contacts.cutoff_A} Å · 계산한 종류 {contacts.types.join(", ")}</p>
      : <p className="mw-muted" data-testid="site-annotation-contact-source">{NO_CONTACT_RESULT_TEXT} (접촉 결과 없이 만든 주석)</p>}
    {nullResult && <p role="status" className="mw-site-annotation-blocked" data-testid="site-annotation-null-result">{NULL_RESULT_TEXT}</p>}
    {annotation.groups.map(group => <div key={`${group.chain_auth}:${group.accession ?? ""}`} className="mw-site-annotation-table"
      data-site-group={`${group.chain_auth}:${group.accession ?? ""}`} data-klifs-applied={group.klifs_applied}>
      <p><strong>체인 {group.chain_auth}</strong> · {group.accession ? `UniProt ${group.accession}` : "UniProt 항목 없음"} · {group.klifs_applied
        ? "KLIFS 번호 적용" : `KLIFS 번호 미적용: ${group.klifs_absent_reason ? siteReasonText(group.klifs_absent_reason) : "이유 없음"}`}</p>
      <div className="mw-table-scroll" role="region" aria-label={`주요 부위 체인 ${group.chain_auth} ${group.accession ?? "없음"}`} tabIndex={0}>
        <table className="mw-table"><thead><tr><th>KLIFS 표기(참조)</th><th>상태</th><th>이름표</th>
          {CONTACT_TYPES.map(type => <th key={type}>{CONTACT_TYPE_LABEL[type]} 행 수</th>)}<th>최소 거리</th></tr></thead>
          <tbody>{group.sites.map(site => { const region = siteRegion(site.klifs_index);
            return <tr key={site.klifs_index} data-site-klifs={site.klifs_label} data-site-status={site.status}
              data-site-absent-reason={site.absent_reason ?? undefined}>
              <td>{region && <i className="mw-site-swatch" style={{ background: `var(--${SITE_REGION_TOKEN[region]})` }} />} {site.klifs_label}</td>
              <td>{siteStatusText(site)}</td>
              <td>{site.display_label ?? "—"}</td>
              {CONTACT_TYPES.map(type => <td key={type} className="mw-mono" data-site-count={type}>{contactCountText(annotation, site, type)}</td>)}
              <td className="mw-mono" data-site-min-distance>{minDistanceText(annotation, site)}</td>
            </tr>; })}</tbody></table>
      </div>
    </div>)}
    {contacts && <p className="mw-muted">{MIN_DISTANCE_NOTE}</p>}
    {applied && <div data-testid="site-annotation-undrawn" data-undrawn-count={applied.undrawnPairs.length}>
      <span className="mw-eyebrow">그리지 못한 점선</span>
      {applied.undrawnPairs.length ? <ul className="mw-site-annotation-undrawn">{applied.undrawnPairs.map(pair =>
        <li key={`${pair.contact_row_index}:${pair.protein_atom}:${pair.ligand_atom}`} data-undrawn-row={pair.contact_row_index}
          data-undrawn-reason={pair.reason}>
          {pair.display_label ?? pair.klifs_label} · {pair.protein_atom}–{pair.ligand_atom} · 접촉 행 #{pair.contact_row_index} · {pair.text}</li>)}</ul>
        : <p className="mw-muted">없음 (저장된 극성 쌍을 모두 그렸습니다)</p>}
    </div>}
    <details><summary>한계</summary>{annotation.limitations.map((item, index) => <p key={index} className="mw-muted">{item}</p>)}</details>
  </div>;
}
