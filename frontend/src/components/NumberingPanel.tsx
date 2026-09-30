"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type MethodReportArtifact } from "@/lib/api";
import type { CommandResult } from "@/lib/api";
import {
  NUMBERING_STATUSES, PDB_ID_PATTERN, ROW_PAGE_LIMIT, STATUS_LABEL, answerText, applySiftsHints, checkForm, emptyForm,
  filterRows, keyedIdle, keyedRequest, keyedResolve, licenseText, numberingStructures, polymerChains, residueText,
  pctOneDecimal, siftsFused, sourceVersion, withdrawSiftsHints,
  type Keyed, type LoadState, type NumberingChain, type NumberingForm, type NumberingMapList, type NumberingMapListRow,
  type NumberingRow, type NumberingStructureKind, type PdbIdHint, type ReferenceSnapshots, type SiftsChains,
  type StatusFilter, type UniprotSearch,
} from "@/lib/numbering";
import { Button, shortSha } from "./primitives";

/**
 * M15 residue numbering screen of the "지식·보고서" tab (spec section 8). Every value shown is a backend
 * field (snapshot records, `residue_numbering_map@1` rows and chain details); the browser only filters and
 * pages already-loaded rows. The panel is mounted only while the tab is shown and is keyed by run, so it
 * reads only then; late responses are dropped by run id + request sequence (`Keyed`).
 */
export interface NumberingPanelProps {
  /** Current run of the structure analysis screen; null when none is selected. */
  runId: string | null;
  /** Called after a report was created so the report library re-reads its list. */
  onReportCreated?: () => void;
}

export const IMPORT_COMMAND = "python scripts/import_reference_snapshots.py --from ../kbase_kinase";
const ROWS_PER_PAGE = 50;
const SEARCH_LIMIT = 20;

type AreaState = "idle" | "loading" | "ready" | "scientific_null" | "failure" | "unavailable";
interface Failure { message: string; code: string | null }
type StructureOption = { handle: string; kind: NumberingStructureKind };
type RowsValue = { handle: string; rows: NumberingRow[]; nullResult: boolean };
type SearchValue = { chain: string; query: string; offset: number; result: UniprotSearch };

function errorOf(error: unknown): Failure {
  if (error instanceof ApiError) return { message: error.message, code: error.code ?? null };
  return { message: error instanceof Error ? error.message : String(error), code: null };
}

/** One keyed read: a new request supersedes (and aborts) the previous one; late answers are dropped. */
function useKeyedLoad<T>(runId: string | null) {
  const [keyed, setKeyed] = useState<Keyed<T>>(() => keyedIdle<T>(runId));
  const seqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);
  const load = useCallback((fetcher: (signal: AbortSignal) => Promise<T>) => {
    if (runId === null) return;
    const seq = ++seqRef.current;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setKeyed(current => keyedRequest(current, runId, seq));
    fetcher(controller.signal).then(
      value => setKeyed(current => keyedResolve(current, runId, seq, { status: "ready", value })),
      error => { if (!controller.signal.aborted)
        setKeyed(current => keyedResolve<T>(current, runId, seq, { status: "error", ...errorOf(error) })); });
  }, [runId]);
  const reset = useCallback(() => {
    ++seqRef.current;
    abortRef.current?.abort();
    abortRef.current = null;
    setKeyed(keyedIdle<T>(runId));
  }, [runId]);
  return [keyed.state, load, reset] as const;
}

async function allMaps(runId: string, signal: AbortSignal): Promise<NumberingMapList> {
  const first = await api.numberingMaps(runId, 0, ROW_PAGE_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.numberingMaps(runId, rows.length, ROW_PAGE_LIMIT, signal);
    if (page.total !== first.total || !page.rows.length) throw new Error("대응 목록이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  return { ...first, offset: 0, limit: rows.length, rows };
}

async function allRows(runId: string, handle: string, signal: AbortSignal): Promise<RowsValue> {
  const first = await api.numberingRows(runId, handle, 0, ROW_PAGE_LIMIT, signal);
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const page = await api.numberingRows(runId, handle, rows.length, ROW_PAGE_LIMIT, signal);
    if (page.meta.handle !== handle || page.total !== first.total || !page.rows.length)
      throw new Error("대응 행이 읽는 동안 바뀌었습니다. 다시 읽으세요.");
    rows.push(...page.rows);
  }
  return { handle, rows, nullResult: first.meta.null_result };
}

function Area({ area, state, title, children }: { area: string; state: AreaState; title: string; children: ReactNode }) {
  return <section className="mw-numbering-section" data-numbering-area={area} data-state={state} aria-label={title}>
    <h3 className="mw-numbering-title">{title}</h3>
    {children}
  </section>;
}

function Loading({ text = "불러오는 중" }: { text?: string }) {
  return <p className="mw-numbering-note" aria-busy="true">{text}</p>;
}

function FailureLine({ failure, onRetry, testId }: { failure: Failure; onRetry?: () => void; testId?: string }) {
  return <div className="mw-numbering-error" role="alert">
    <span>실패: {failure.message}{failure.code ? ` (${failure.code})` : ""}</span>
    {onRetry && <Button size="sm" onClick={onRetry} data-testid={testId}>다시 시도</Button>}
  </div>;
}

function Handle({ handle, kind }: { handle: string; kind?: string }) {
  return <code title={handle}>{kind ? `${kind} ` : ""}{shortSha(handle)}</code>;
}

function stateOf<T>(state: LoadState<T>): AreaState {
  return state.status === "error" ? "failure" : state.status;
}

export function NumberingPanel({ runId, onReportCreated }: NumberingPanelProps) {
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const reportCallback = useRef(onReportCreated);
  reportCallback.current = onReportCreated;

  const [snapshots, loadSnapshots] = useKeyedLoad<ReferenceSnapshots>(runId);
  const [structures, loadStructures] = useKeyedLoad<StructureOption[]>(runId);
  const [chains, loadChains, resetChains] = useKeyedLoad<{ structure: string; chains: string[] }>(runId);
  const [hint, loadHint, resetHint] = useKeyedLoad<PdbIdHint>(runId);
  const [sifts, loadSifts, resetSifts] = useKeyedLoad<SiftsChains>(runId);
  const [search, loadSearch, resetSearch] = useKeyedLoad<SearchValue>(runId);
  const [command, loadCommand] = useKeyedLoad<CommandResult>(runId);
  const [maps, loadMaps] = useKeyedLoad<NumberingMapList>(runId);
  const [rows, loadRows, resetRows] = useKeyedLoad<RowsValue>(runId);
  const [report, loadReport, resetReport] = useKeyedLoad<MethodReportArtifact>(runId);

  const [form, setForm] = useState<NumberingForm>(emptyForm);
  const [userPicked, setUserPicked] = useState<string[]>([]);
  const [pickerChain, setPickerChain] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedMap, setSelectedMap] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);

  const readSnapshots = useCallback(() => loadSnapshots(signal => api.referenceSnapshots(signal)), [loadSnapshots]);
  const readStructures = useCallback(() => {
    if (runId !== null) loadStructures(signal => api.allEvents(runId, signal).then(numberingStructures));
  }, [runId, loadStructures]);
  const readMaps = useCallback(() => { if (runId !== null) loadMaps(signal => allMaps(runId, signal)); }, [runId, loadMaps]);
  const readChains = useCallback((structure: string) => {
    if (runId !== null) loadChains(() => api.residues(runId, structure)
      .then(list => ({ structure, chains: polymerChains(list.residues) })));
  }, [runId, loadChains]);
  const readHint = useCallback((structure: string) => {
    if (runId !== null) loadHint(signal => api.pdbIdHint(runId, structure, signal));
  }, [runId, loadHint]);
  const readRows = useCallback((handle: string) => {
    if (runId !== null) loadRows(signal => allRows(runId, handle, signal));
  }, [runId, loadRows]);

  useEffect(() => {
    if (runId === null) return;
    readSnapshots(); readStructures(); readMaps();
  }, [runId, readSnapshots, readStructures, readMaps]);

  // Residues of the chosen structure → chain checkboxes (none selected). A SIFTS answer already in the form is re-applied.
  useEffect(() => {
    if (chains.status !== "ready") return;
    const value = chains.value;
    setForm(current => current.structure !== value.structure ? current : applySiftsHints({ ...current,
      chains: value.chains.map(chain => ({ chain_auth: chain, selected: false, accession: null })) }, current.sifts));
  }, [chains]);

  // The PDB ID suggestion only fills an untouched, unconfirmed input; it is never confirmed automatically.
  useEffect(() => {
    if (hint.status !== "ready" || !hint.value.pdb_id) return;
    const suggested = hint.value.pdb_id;
    setForm(current => current.structure !== hint.value.structure || current.pdbId || current.pdbIdConfirmed ? current
      : { ...current, pdbId: suggested });
  }, [hint]);

  useEffect(() => {
    if (sifts.status !== "ready") return;
    const value = sifts.value;
    setForm(current => !current.pdbIdConfirmed || current.pdbId.trim().toUpperCase() !== value.pdb_id.toUpperCase() ? current
      : applySiftsHints(current, value.available ? value.chains : []));
  }, [sifts]);

  const chooseStructure = (structure: string) => {
    resetChains(); resetHint(); resetSifts(); resetSearch();
    setPickerChain(null); setUserPicked([]);
    setForm({ ...emptyForm(), structure: structure || null });
    if (structure) { readChains(structure); readHint(structure); }
  };

  const withdraw = () => {
    resetSifts();
    setForm(current => withdrawSiftsHints(current, userPicked));
  };

  const setConfirmed = (checked: boolean) => {
    if (!checked) { withdraw(); return; }
    const pdbId = form.pdbId.trim().toUpperCase();
    setForm(current => ({ ...current, pdbIdConfirmed: true, sifts: null }));
    if (PDB_ID_PATTERN.test(pdbId)) loadSifts(signal => api.siftsChains(pdbId, signal));
  };

  const editPdbId = (value: string) => {
    if (form.pdbIdConfirmed) withdraw();
    setForm(current => ({ ...current, pdbId: value }));
  };

  const toggleChain = (chain: string, selected: boolean) =>
    setForm(current => ({ ...current, chains: current.chains.map(choice => choice.chain_auth === chain ? { ...choice, selected } : choice) }));

  const pickAccession = (chain: string, accession: string | null) => {
    setForm(current => ({ ...current, chains: current.chains.map(choice => choice.chain_auth === chain ? { ...choice, accession } : choice) }));
    setUserPicked(current => accession ? (current.includes(chain) ? current : [...current, chain]) : current.filter(item => item !== chain));
  };

  const runSearch = (chain: string, text: string, offset: number) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    loadSearch(signal => api.uniprotSearch(trimmed, offset, SEARCH_LIMIT, signal)
      .then(result => ({ chain, query: trimmed, offset, result })));
  };

  const selectMap = (handle: string) => {
    setSelectedMap(handle); setFilter("all"); setPage(0); resetReport(); resetRows();
    readRows(handle);
  };

  const check = checkForm(form);
  const snapshotReady = snapshots.status === "ready" && snapshots.value.available;

  const submit = () => {
    if (!check.ok || runId === null) return;
    const body = check.body;
    loadCommand(signal => api.command(runId, "map_residue_numbering", body, signal).then(result => {
      if (result.ok && alive.current) { readMaps(); selectMap(result.handle.handle); }
      return result;
    }));
  };

  const createReport = (handle: string) => {
    if (runId === null) return;
    loadReport(signal => api.createMethodReport(runId, handle, signal).then(artifact => {
      reportCallback.current?.();
      return artifact;
    }));
  };

  if (runId === null) {
    return <section className="mw-numbering" aria-label="잔기 번호 대응">
      <h2 className="mw-numbering-heading">잔기 번호 대응</h2>
      <p className="mw-numbering-note" data-testid="numbering-no-run">구조 분석 탭에서 run을 먼저 선택하세요</p>
    </section>;
  }

  const mapRows = maps.status === "ready" ? maps.value.rows : [];
  const selectedRow = mapRows.find(row => row.handle === selectedMap) ?? null;

  return <section className="mw-numbering" aria-label="잔기 번호 대응">
    <h2 className="mw-numbering-heading">잔기 번호 대응</h2>

    <SnapshotArea state={snapshots} onRetry={readSnapshots} />

    <Area area="create" title="대응 만들기" state={snapshots.status === "ready" && !snapshots.value.available ? "unavailable"
      : stateOf(structures)}>
      {snapshots.status === "ready" && !snapshots.value.available
        ? <p className="mw-numbering-unavailable">사용할 수 없음: 참조 스냅샷이 없어 대응을 만들 수 없습니다.</p>
        : structures.status === "loading" || structures.status === "idle" ? <Loading />
        : structures.status === "error" ? <FailureLine failure={structures} onRetry={readStructures} testId="numbering-structures-retry" />
        : !structures.value.length ? <p className="mw-numbering-note">이 run에 구조가 없습니다. 구조 분석 탭에서 구조를 불러오세요.</p>
        : <div className="mw-numbering-form">
          <label className="mw-numbering-field">구조
            <select className="mw-numbering-input" data-testid="numbering-structure" value={form.structure ?? ""}
              onChange={event => chooseStructure(event.target.value)}>
              <option value="">구조를 고르세요</option>
              {structures.value.map(option => <option key={option.handle} value={option.handle} title={option.handle}>
                {option.kind} {shortSha(option.handle)}</option>)}
            </select>
          </label>
          {form.structure && <>
            <fieldset className="mw-numbering-fieldset" data-testid="numbering-chains">
              <legend>체인 (polymer 잔기가 있는 체인)</legend>
              {chains.status === "loading" || chains.status === "idle" ? <Loading />
                : chains.status === "error" ? <FailureLine failure={chains} onRetry={() => form.structure && readChains(form.structure)} testId="numbering-chains-retry" />
                : !form.chains.length ? <p className="mw-numbering-note">polymer 잔기가 있는 체인이 없습니다.</p>
                : form.chains.map(choice => <ChainChoiceRow key={choice.chain_auth} chain={choice.chain_auth} selected={choice.selected}
                  accession={choice.accession} userPicked={userPicked.includes(choice.chain_auth)}
                  siftsHint={form.pdbIdConfirmed ? form.sifts?.find(item => item.chain_auth === choice.chain_auth) ?? null : null}
                  siftsLoaded={form.pdbIdConfirmed && form.sifts !== null}
                  fused={form.pdbIdConfirmed && siftsFused(form.sifts, choice.chain_auth)}
                  onToggle={selected => toggleChain(choice.chain_auth, selected)}
                  onPick={accession => pickAccession(choice.chain_auth, accession)}
                  pickerOpen={pickerChain === choice.chain_auth}
                  onOpenPicker={() => { setPickerChain(pickerChain === choice.chain_auth ? null : choice.chain_auth); setQuery(""); resetSearch(); }}
                  picker={<UniprotPicker chain={choice.chain_auth} query={query} onQuery={setQuery} state={search}
                    onSearch={offset => runSearch(choice.chain_auth, query, offset)}
                    onPick={accession => { pickAccession(choice.chain_auth, accession); setPickerChain(null); }} />} />)}
            </fieldset>
            <fieldset className="mw-numbering-fieldset">
              <legend>PDB ID</legend>
              <p className="mw-numbering-note" data-testid="numbering-pdb-hint">
                {hint.status === "loading" ? "제안을 읽는 중"
                  : hint.status === "error" ? `제안을 읽지 못했습니다: ${hint.message}`
                  : hint.status === "ready" ? hint.value.pdb_id
                    ? `업로드 원본의 제안: ${hint.value.pdb_id} (${hint.value.origin}). 제안일 뿐이므로 확인해야 보냅니다.`
                    : "업로드 원본에 PDB ID가 없습니다." : ""}
              </p>
              {hint.status === "error" && <Button size="sm" data-testid="numbering-hint-retry"
                onClick={() => form.structure && readHint(form.structure)}>다시 시도</Button>}
              <div className="mw-numbering-inline">
                <input className="mw-numbering-input" data-testid="numbering-pdb-id" aria-label="PDB ID" value={form.pdbId}
                  maxLength={4} onChange={event => editPdbId(event.target.value)} placeholder="예: 1MQ4" />
                <label className="mw-numbering-check">
                  <input type="checkbox" data-testid="numbering-pdb-confirm" checked={form.pdbIdConfirmed}
                    disabled={!form.pdbId.trim()} onChange={event => setConfirmed(event.target.checked)} />
                  이 PDB ID가 맞습니다
                </label>
              </div>
              {form.pdbIdConfirmed && <p className="mw-numbering-note" data-testid="numbering-sifts-state">
                {sifts.status === "loading" ? "SIFTS 체인 대응을 읽는 중"
                  : sifts.status === "error" ? `SIFTS 체인 대응을 읽지 못했습니다: ${sifts.message}`
                  : sifts.status === "ready" ? sifts.value.available
                    ? sifts.value.chains.length ? `SIFTS 스냅샷에서 ${sifts.value.pdb_id}의 체인 대응을 읽었습니다(한 accession만 있는 체인은 미리 채움, 수정 가능).`
                      : `SIFTS 스냅샷에 ${sifts.value.pdb_id}의 체인 대응이 없습니다. 체인별로 UniProt 항목을 고르세요.`
                    : `SIFTS를 사용할 수 없음: ${sifts.value.reason ?? sifts.value.reason_code ?? ""}` : ""}
              </p>}
              {form.pdbIdConfirmed && sifts.status === "error" && <Button size="sm" data-testid="numbering-sifts-retry"
                onClick={() => setConfirmed(true)}>다시 시도</Button>}
            </fieldset>
          </>}
          {!check.ok && <ul className="mw-numbering-errors" data-testid="numbering-form-errors">
            {check.errors.map(error => <li key={error}>{error}</li>)}</ul>}
          <div className="mw-numbering-inline">
            <Button variant="primary" size="sm" data-testid="numbering-run" disabled={!check.ok || !snapshotReady || command.status === "loading"}
              onClick={submit}>실행</Button>
            {command.status === "loading" && <span className="mw-numbering-note" aria-busy="true">실행 중</span>}
          </div>
          <CommandOutcome state={command} onRetry={submit} />
        </div>}
    </Area>

    <Area area="maps" title="대응 목록" state={stateOf(maps)}>
      {maps.status === "loading" || maps.status === "idle" ? <Loading />
        : maps.status === "error" ? <FailureLine failure={maps} onRetry={readMaps} testId="numbering-maps-retry" />
        : <>
          <div className="mw-numbering-inline">
            <span className="mw-numbering-note">대응 {maps.value.rows.length}개</span>
            <Button size="sm" data-testid="numbering-maps-refresh" onClick={readMaps}>새로 고침</Button>
          </div>
          {!maps.value.rows.length ? <p className="mw-numbering-note">아직 대응이 없습니다.</p>
            : <ul className="mw-numbering-maps">{maps.value.rows.map(row => <li key={row.handle}>
              <MapButton row={row} selected={row.handle === selectedMap} onSelect={() => selectMap(row.handle)} />
            </li>)}</ul>}
        </>}
    </Area>

    {selectedMap && <MapDetail handle={selectedMap} row={selectedRow} rows={rows} filter={filter} page={page}
      onFilter={value => { setFilter(value); setPage(0); }} onPage={setPage} onRetry={() => readRows(selectedMap)}
      report={report} onReport={() => createReport(selectedMap)} />}
  </section>;
}

function SnapshotArea({ state, onRetry }: { state: LoadState<ReferenceSnapshots>; onRetry: () => void }) {
  const areaState: AreaState = state.status === "ready" && !state.value.available ? "unavailable" : stateOf(state);
  return <Area area="snapshots" title="참조 스냅샷 상태" state={areaState}>
    {state.status === "loading" || state.status === "idle" ? <Loading />
      : state.status === "error" ? <FailureLine failure={state} onRetry={onRetry} testId="numbering-snapshots-retry" />
      : !state.value.available ? <div className="mw-numbering-unavailable" data-testid="numbering-snapshot-unavailable">
        <p><b>사용할 수 없음</b>{state.value.reason_code ? ` (${state.value.reason_code})` : ""}: {state.value.reason ?? "참조 스냅샷이 없습니다."}</p>
        <p>docs/operations.md의 참조 스냅샷 가져오기 명령으로 가져오세요:</p>
        <pre className="mw-numbering-command">{IMPORT_COMMAND}</pre>
      </div>
      : <>
        <dl className="mw-numbering-facts">
          <dt>세트 해시</dt><dd><code data-testid="numbering-set-hash" title={state.value.set_hash ?? ""}>
            {state.value.set_hash ? state.value.set_hash.slice(0, 12) : "없음"}</code></dd>
          <dt>가공본</dt><dd>kbase_kinase 가공본{state.value.origin ? ` (${state.value.origin})` : ""}</dd>
          <dt>가져온 시각</dt><dd>{state.value.imported_at ?? "없음"}</dd>
          {state.value.kbase_repo && <><dt>kbase 커밋</dt><dd><code title={state.value.kbase_repo.commit}>
            {state.value.kbase_repo.commit.slice(0, 12)}</code>{state.value.kbase_repo.dirty ? " (작업 트리 변경 있음)" : ""}</dd></>}
        </dl>
        <table className="mw-numbering-table" data-testid="numbering-snapshot-sources">
          <thead><tr><th>출처</th><th>버전</th><th>날짜</th><th>라이선스</th><th>스냅샷</th></tr></thead>
          <tbody>{state.value.sources.map(source => <tr key={source.source} data-snapshot-source={source.source}>
            <td>{source.source}</td><td>{sourceVersion(source)}</td><td>{source.date}</td>
            <td>{licenseText(source.license)}</td><td><code>{source.snapshot_id}</code> · {source.origin}</td>
          </tr>)}</tbody>
        </table>
      </>}
  </Area>;
}

function ChainChoiceRow(p: { chain: string; selected: boolean; accession: string | null; userPicked: boolean;
  siftsHint: { accessions: string[]; reason_code: string | null; reason: string | null } | null; siftsLoaded: boolean;
  fused: boolean;
  onToggle: (selected: boolean) => void; onPick: (accession: string | null) => void;
  pickerOpen: boolean; onOpenPicker: () => void; picker: ReactNode }) {
  return <div className="mw-numbering-chain" data-numbering-chain={p.chain}>
    <label className="mw-numbering-check">
      <input type="checkbox" data-testid={`numbering-chain-${p.chain}`} checked={p.selected} onChange={event => p.onToggle(event.target.checked)} />
      체인 <code>{p.chain}</code>
    </label>
    <span className="mw-numbering-note" data-testid={`numbering-accession-${p.chain}`}>
      UniProt: {p.fused ? "SIFTS 단독 사용(융합 체인: accession 여러 개)"
        : p.accession ? <><code>{p.accession}</code>{p.userPicked ? " (직접 고름)" : " (SIFTS 미리 채움)"}</> : "고르지 않음"}
    </span>
    {p.siftsLoaded && <span className="mw-numbering-note">
      SIFTS: {!p.siftsHint ? "이 체인 대응 없음"
        : p.siftsHint.reason_code ? `${p.siftsHint.reason_code}${p.siftsHint.reason ? ` (${p.siftsHint.reason})` : ""}`
        : p.fused ? <span data-testid={`numbering-sifts-fused-${p.chain}`}>{p.siftsHint.accessions.map((accession, i) =>
          <span key={accession}>{i ? ", " : ""}<code>{accession}</code></span>)}</span>
        : p.siftsHint.accessions.map(accession => <Button key={accession} size="sm" onClick={() => p.onPick(accession)}
          data-testid={`numbering-sifts-pick-${p.chain}-${accession}`}>{accession}</Button>)}
    </span>}
    {!p.fused && <Button size="sm" data-testid={`numbering-picker-${p.chain}`} onClick={p.onOpenPicker}>UniProt 검색</Button>}
    {!p.fused && p.accession && <Button size="sm" data-testid={`numbering-clear-${p.chain}`} onClick={() => p.onPick(null)}>선택 지우기</Button>}
    {!p.fused && p.pickerOpen && p.picker}
  </div>;
}

function UniprotPicker(p: { chain: string; query: string; onQuery: (value: string) => void; state: LoadState<SearchValue>;
  onSearch: (offset: number) => void; onPick: (accession: string) => void }) {
  const shown = p.state.status === "ready" && p.state.value.chain === p.chain ? p.state.value : null;
  return <div className="mw-numbering-picker" data-testid="numbering-uniprot-picker">
    <form className="mw-numbering-inline" onSubmit={event => { event.preventDefault(); p.onSearch(0); }}>
      <input className="mw-numbering-input" data-testid="numbering-uniprot-query" aria-label="UniProt 검색어"
        value={p.query} maxLength={100} onChange={event => p.onQuery(event.target.value)} placeholder="accession, 유전자, 이름" />
      <Button size="sm" type="submit" data-testid="numbering-uniprot-search" disabled={!p.query.trim()}>검색</Button>
    </form>
    {p.state.status === "loading" ? <Loading text="검색 중" />
      : p.state.status === "error" ? <FailureLine failure={p.state} onRetry={() => p.onSearch(0)} testId="numbering-uniprot-retry" />
      : shown && !shown.result.available ? <p className="mw-numbering-unavailable">사용할 수 없음: {shown.result.reason ?? shown.result.reason_code}</p>
      : shown && <>
        <p className="mw-numbering-note">“{shown.query}” 결과 {shown.result.total}개 중 {shown.result.entries.length ? `${shown.offset + 1}–${shown.offset + shown.result.entries.length}` : "0"}</p>
        {shown.result.entries.length > 0 && <ul className="mw-numbering-results">{shown.result.entries.map(entry => <li key={entry.accession}>
          <button type="button" className="mw-numbering-result" data-uniprot-accession={entry.accession} onClick={() => p.onPick(entry.accession)}>
            <code>{entry.accession}</code> {entry.entry_name ?? ""} · {entry.gene ?? "유전자 없음"} · {entry.protein_name ?? "이름 없음"}
            {" "}· {entry.organism ?? "생물종 없음"} · 길이 {entry.sequence_length}
          </button></li>)}</ul>}
        <div className="mw-numbering-inline">
          <Button size="sm" disabled={shown.offset === 0} onClick={() => p.onSearch(Math.max(0, shown.offset - SEARCH_LIMIT))}>이전</Button>
          <Button size="sm" disabled={shown.offset + shown.result.entries.length >= shown.result.total}
            onClick={() => p.onSearch(shown.offset + SEARCH_LIMIT)}>다음</Button>
        </div>
      </>}
  </div>;
}

function CommandOutcome({ state, onRetry }: { state: LoadState<CommandResult>; onRetry: () => void }) {
  if (state.status === "error") return <FailureLine failure={state} onRetry={onRetry} testId="numbering-run-retry" />;
  if (state.status !== "ready") return null;
  const result = state.value;
  if (result.ok) return <p className="mw-numbering-note" data-testid="numbering-run-result">대응을 만들었습니다: <Handle handle={result.handle.handle} /></p>;
  const message = "approval" in result ? `승인 필요: ${result.approval.reason}`
    : "loop_stop" in result ? `중단: ${result.loop_stop.reason}` : `${result.error}: ${result.message}`;
  return <div className="mw-numbering-error" role="alert" data-testid="numbering-run-result">실행하지 못했습니다: {message}</div>;
}

function Counts({ counts }: { counts: Record<"mapped" | "unmapped" | "conflict", number> }) {
  return <span className="mw-numbering-counts">{NUMBERING_STATUSES.map(status =>
    <span key={status} data-count-status={status}>{STATUS_LABEL[status]} {counts[status]}</span>)}</span>;
}

function MapButton({ row, selected, onSelect }: { row: NumberingMapListRow; selected: boolean; onSelect: () => void }) {
  return <button type="button" className="mw-numbering-map" aria-pressed={selected} data-numbering-map={row.handle}
    data-stale={row.stale_snapshot} data-null-result={row.null_result} onClick={onSelect}>
    <span><Handle handle={row.structure} kind={row.structure_kind} /> · 모델 {row.model_number}</span>
    <span>체인 {row.chains.join(", ")}</span>
    <span>{row.pdb_id ?? "PDB ID 없음"}</span>
    <Counts counts={row.counts} />
    {row.null_result && <span className="mw-numbering-badge mw-numbering-badge--null">대응된 잔기 없음(계산은 성공)</span>}
    {row.stale_snapshot && <span className="mw-numbering-badge mw-numbering-badge--stale" title={row.set_hash}>이전 스냅샷 기준</span>}
    <span className="mw-numbering-note">생성 순번 {row.created_seq}</span>
  </button>;
}

function pct(value: number | null): ReactNode {
  return value === null ? "없음" : <span title={`${value} %`}>{pctOneDecimal(value)} %</span>;
}

function ChainSummary({ chain }: { chain: NumberingChain }) {
  return <div className="mw-numbering-chain-summary" data-chain-summary={chain.chain_auth} data-cross-check={chain.cross_check}>
    <h4>체인 <code>{chain.chain_auth}</code></h4>
    <dl className="mw-numbering-facts">
      <dt>실행한 방법</dt><dd>{chain.methods_run.length ? chain.methods_run.join(", ") : "없음"}</dd>
      {chain.requested_uniprot_accession !== undefined && <><dt>고른 UniProt</dt><dd>{chain.requested_uniprot_accession ?? "없음"}</dd></>}
      <dt>교차 확인</dt><dd>{chain.cross_check ? "예" : `교차 확인 없음${chain.cross_check_absent_reason ? ` (${chain.cross_check_absent_reason})` : ""}`}</dd>
      {chain.sifts && <><dt>SIFTS</dt><dd>{chain.sifts.accessions.join(", ") || "accession 없음"} · {chain.sifts.sifts_chain_match} · {chain.sifts.sifts_residue_key}</dd></>}
      {chain.alignment && <>
        <dt>정렬 (ProtView 계산)</dt>
        <dd>{chain.alignment.accession} · 일치율 {pct(chain.alignment.identity_pct)} · 정렬 범위 {pct(chain.alignment.coverage_pct)}
          {" "}· 정렬 쌍 {chain.alignment.aligned_pairs} · 같은 잔기 {chain.alignment.identical} · 체인 잔기 {chain.alignment.chain_residue_count}
          {chain.alignment.ambiguous_residue_count !== undefined ? ` · 모호 잔기 ${chain.alignment.ambiguous_residue_count}` : ""}
          {chain.alignment.chain_reason.length ? ` · 체인 기준 미달: ${chain.alignment.chain_reason.join(", ")}` : ""}</dd>
      </>}
      <dt>KLIFS</dt>
      <dd>{!chain.klifs.length ? "대응된 accession 없음" : chain.klifs.map(entry => <span key={entry.accession} className="mw-numbering-klifs"
        data-klifs-applied={entry.applied}>
        {entry.accession}: {entry.applied ? "적용됨" : `적용 안 됨 (${entry.absent_reason ?? "이유 없음"})`}
        {entry.unresolved_regions.length ? ` · 미해결 구역 ${entry.unresolved_regions.join(", ")}` : ""}
        {entry.gapped_regions?.length ? ` · 건너뛴 일치 구역 ${entry.gapped_regions.join(", ")}` : ""}
      </span>)}</dd>
      {chain.residue_rule && <><dt>수식 잔기</dt><dd>{chain.residue_rule.modified_residue_count} ({chain.residue_rule.rule})</dd></>}
      <dt>행 개수</dt><dd><Counts counts={chain.counts} /></dd>
    </dl>
  </div>;
}

const FILTERS: { value: StatusFilter; label: string }[] = [{ value: "all", label: "전체" },
  ...NUMBERING_STATUSES.map(status => ({ value: status as StatusFilter, label: STATUS_LABEL[status] }))];

function MapDetail(p: { handle: string; row: NumberingMapListRow | null; rows: LoadState<RowsValue>; filter: StatusFilter; page: number;
  onFilter: (value: StatusFilter) => void; onPage: (page: number) => void; onRetry: () => void;
  report: LoadState<MethodReportArtifact>; onReport: () => void }) {
  const loaded = p.rows.status === "ready" && p.rows.value.handle === p.handle ? p.rows.value : null;
  const areaState: AreaState = loaded ? (loaded.nullResult ? "scientific_null" : "ready") : stateOf(p.rows);
  const chainByAuth = new Map((p.row?.chain_details ?? []).map(chain => [chain.chain_auth, chain]));
  const view = loaded ? filterRows(loaded.rows, p.filter, p.page * ROWS_PER_PAGE, ROWS_PER_PAGE) : null;
  const pages = view ? Math.max(1, Math.ceil(view.matched / ROWS_PER_PAGE)) : 1;
  return <Area area="detail" title="고른 대응" state={areaState}>
    <p className="mw-numbering-note">대응 <Handle handle={p.handle} />{p.row?.stale_snapshot ? " · " : ""}
      {p.row?.stale_snapshot && <span className="mw-numbering-badge mw-numbering-badge--stale">이전 스냅샷 기준</span>}</p>
    <div className="mw-numbering-inline">
      <Button size="sm" data-testid="numbering-report" disabled={p.report.status === "loading"} onClick={p.onReport}>보고서 만들기</Button>
      {p.report.status === "loading" && <span className="mw-numbering-note" aria-busy="true">보고서를 만드는 중</span>}
      {p.report.status === "ready" && <span className="mw-numbering-note" data-testid="numbering-report-done">
        보고서 목록에 추가됨: <Handle handle={p.report.value.handle} /></span>}
    </div>
    {p.report.status === "error" && <FailureLine failure={p.report} onRetry={p.onReport} testId="numbering-report-retry" />}
    {p.row && <div className="mw-numbering-chains">{p.row.chain_details.map(chain => <ChainSummary key={chain.chain_auth} chain={chain} />)}</div>}
    {p.rows.status === "loading" || p.rows.status === "idle" ? <Loading text="행을 불러오는 중" />
      : p.rows.status === "error" ? <FailureLine failure={p.rows} onRetry={p.onRetry} testId="numbering-rows-retry" />
      : loaded && view && <>
        {loaded.nullResult && <p className="mw-numbering-null" data-testid="numbering-null-result">대응된 잔기 없음(계산은 성공)</p>}
        <p className="mw-numbering-note">UniProt accession·위치·잔기와 KLIFS 번호는 참조 스냅샷 값이며 계산값이 아닙니다.</p>
        <div className="mw-numbering-inline" role="group" aria-label="상태 필터">
          {FILTERS.map(item => <Button key={item.value} size="sm" data-testid={`numbering-filter-${item.value}`}
            aria-pressed={p.filter === item.value} onClick={() => p.onFilter(item.value)}>{item.label}</Button>)}
          <span className="mw-numbering-note" data-testid="numbering-filter-count">필터 결과 {view.matched} / 전체 {view.total}</span>
        </div>
        {!view.rows.length ? <p className="mw-numbering-note">이 필터에 맞는 행이 없습니다.</p>
          : <div className="mw-numbering-table-wrap"><table className="mw-numbering-table" data-testid="numbering-rows">
            <thead><tr><th>잔기 (모델·체인·이름·번호·label)</th><th>상태</th><th>UniProt (참조)</th><th>잔기 비교</th>
              <th>교차 확인</th><th>KLIFS 번호 (참조)</th><th>방법별 답</th></tr></thead>
            <tbody>{view.rows.map((row, index) => {
              const chain = chainByAuth.get(row.residue.chain_auth);
              return <tr key={p.page * ROWS_PER_PAGE + index} data-numbering-status={row.status}>
                <td className="mw-mono">{residueText(row.residue)}</td>
                <td>{STATUS_LABEL[row.status]}{row.conflict_reason ? ` (${row.conflict_reason})` : ""}</td>
                <td>{row.uniprot_accession !== null
                  ? <><code>{row.uniprot_accession}</code> {row.uniprot_position ?? "없음"} {row.uniprot_residue ?? ""}</> : "없음"}</td>
                <td>{row.residue_match === false ? <span className="mw-numbering-badge" data-residue-mismatch="true">잔기 불일치</span>
                  : row.residue_match === true ? "일치" : "—"}</td>
                <td>{chain && !chain.cross_check ? <span className="mw-numbering-badge" data-no-cross-check="true">교차 확인 없음</span> : chain ? "예" : "—"}</td>
                <td>{row.klifs_label ? <span title="KLIFS 스냅샷 값 · 이용 조건 명시 없음(none-stated)">KLIFS {row.klifs_label}
                  {row.klifs_match === "gapped_unique" && <span className="mw-numbering-badge" data-klifs-gapped="true">건너뛴 일치</span>}</span> : "없음"}</td>
                <td className="mw-numbering-answers">SIFTS: {answerText(row.sifts)}<br />정렬: {answerText(row.alignment)}</td>
              </tr>;
            })}</tbody>
          </table></div>}
        <div className="mw-numbering-inline">
          <Button size="sm" data-testid="numbering-page-prev" disabled={p.page === 0} onClick={() => p.onPage(p.page - 1)}>이전</Button>
          <span className="mw-numbering-note" data-testid="numbering-page">페이지 {p.page + 1} / {pages}</span>
          <Button size="sm" data-testid="numbering-page-next" disabled={p.page + 1 >= pages} onClick={() => p.onPage(p.page + 1)}>다음</Button>
        </div>
      </>}
  </Area>;
}
