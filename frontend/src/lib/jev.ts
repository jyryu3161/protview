/**
 * Pure logic of the M24 "JEV 판정(외부 모델)" area in the 지식·보고서 tab (spec `.dryforge/spec.md` 2, 5, 6, 7, 9).
 *
 * The JEV answer is a proposal ("JEV 판정(모델 선택)"), never a computed value: this module never ranks, scores,
 * sorts, merges or compares proposals and never computes a scientific value. Numbers shown are the stored values the
 * server returned (confidence and probabilities rounded for display only with `decimalHalfUp`; the stored values are
 * never changed). The preview body is the exact string the server returned and is shown as is (never parsed,
 * re-serialized or reworded). It decides the candidate selection guard (at most 20, ligand candidates only when they
 * pass the applied filter, no duplicates, one source set), the tool arguments, the approval blockers, the `send_id`
 * of one approval, the result card, the send history rows, the closed reason labels and the wording check.
 */
import type { CommandResult } from "./api";
import type { JevKind, JevLocalDisplay, JevLocalRef, JevPreviewV1, JevProjectionArgs, JevProjectionSummary,
  JevReportArtifact, JevResidue, JevSelectionItem, JevSendDetail, JevSendRequest, JevSendV1, JevStatusV1, JevUsage,
  LigandCandidatePageRow, LigandCandidateSetListRow, LigandFilterSpec, MutationCandidateRow,
  MutationCandidateSetListRow } from "./contracts";
import { decimalHalfUp } from "./site-annotation";

// ---- closed sets, caps and fixed wording (backend/mw/jev_constants.py; change both sides together) ----

export const JEV_TOOL = "build_jev_projection";
export const JEV_REPORT_TYPE = "jev_choice";
export const JEV_CONFIRM = "send_to_jev";
export const JEV_MAX_CANDIDATES = 20;
export const JEV_SEND_CAP = 10;
export const QUESTION_IDS = ["ligand_candidate_choice@1", "mutation_candidate_choice@1"] as const;
export const PREVIEW_BLOCK_REASONS = ["dry_run", "consent_off", "cancelled", "egress_stopped", "send_cap_exhausted",
  "budget_exhausted", "send_in_progress"] as const;
export const REJECTED_REASONS = ["dry_run", "consent_off", "cancelled", "egress_stopped", "send_cap_exhausted",
  "budget_exhausted", "missing_configuration", "missing_credential"] as const;
export const FAILED_REASONS = ["external_timeout", "transport_error", "provider_http_error", "response_invalid",
  "missing_model", "model_mismatch", "delivery_unknown", "outcome_not_recorded"] as const;
export const LATE_REASONS = ["run_cancelled", "consent_off"] as const;
/** `build_jev_projection` admission reasons in check order, then the read refusal `projection_invalid`. */
export const PROJECTION_REASON_CODES = ["unknown_field", "source_invalid", "selection_invalid", "candidate_unknown",
  "filter_invalid", "candidate_filtered_out", "structure_unavailable", "wire_field_invalid", "payload_too_large",
  "projection_invalid"] as const;
/** Stored statuses, then the read-only derived `in_progress`. */
export const SEND_STATUSES = ["completed", "rejected", "failed", "in_progress"] as const;
/** Error codes of the JEV routes, the command route and the report route that this area can show. */
export const SEND_ERROR_CODES = ["preview_mismatch", "send_id_conflict", "send_in_progress", "busy", "not_found",
  "input_invalid", "dry_run", "cancelled", "run_corrupt", "method_evidence_invalid", "report_evidence_invalid",
  "resource_exceeded", "transient"] as const;

export const JEV_CHOICE_LABEL = "JEV 판정(모델 선택)";
export const JEV_CONFIDENCE_LABEL = "모델 보고 확신도(0–1, 과학 값 아님)";
export const JEV_REPORT_LABEL = "JEV 판정 보고서";
/** Display digits of confidence and probabilities (ROUND_HALF_UP on the decimal string; stored values unchanged). */
export const JEV_PROBABILITY_DIGITS = 3;

/** Fixed sentences J1–J7 (spec 6), verbatim and in order; the server stores the applicable ones in `limitations`. */
export const JEV_STATEMENTS = {
  J1: "JEV 판정은 외부 모델이 보낸 후보 목록에서 고른 하나일 뿐이며 계산 결과가 아니라 제안으로 따로 기록한 것이다. 순위·추천·예측이 아니다.",
  J2: "고른 이유는 알 수 없다. 응답에는 선택과 모델이 보고한 확신도·확률만 있으며 과학 값이 아니다.",
  J3: "외부로 나간 내용은 승인한 미리보기 본문과 바이트가 같고(해시로 확인) 그 본문이 이 기록의 근거 전부이다.",
  J4: "모델 선택은 후보 목록의 순서(로컬 저장 순서)의 영향을 받을 수 있다.",
  J5: "후보는 2D 그래프이고 속성값은 RDKit 추정값이며 결합·활성·합성 가능성을 계산하지 않았고 수용체 정보 없이 고른 것이다.",
  J6: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 " +
    "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 " +
    "했고 촉매 잔기 데이터베이스는 사용하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.",
  J7: "이 응답은 run 취소 또는 과학 전송 동의 끄기 뒤에 도착했으며 어떤 작업도 일으키지 않았다.",
} as const;
/**
 * M26 spec 9: the fifth sentence of a mutation projection follows its wire's `catalytic_residue_database` status.
 * `not_available` (every v1 candidate set) keeps J6 byte for byte; J6n / J6c are the v2 variants. They are not in
 * `JEV_STATEMENTS` (J1–J7 stay fixed) and pass the wording check without an exemption.
 */
export const JEV_J6_VARIANTS = {
  J6n: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 " +
    "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화 기준으로만 " +
    "했고 이 집합에서는 M-CSA 촉매 잔기 주석을 전부 검사하지 않았으며, 검사하지 않은 항목은 '없음'이 아니다.",
  J6c: "후보는 위치와 바꿀 잔기의 조합이고 이웃 잔기·구간·거리는 준비된 구조의 저장 좌표에서 잰 기하이며 변이의 효과나 " +
    "상호작용을 뜻하지 않는다. 보호 판정은 사용자 목록·KLIFS 주요 부위(주석이 있을 때)·금속 근접·이황화·M-CSA 촉매 " +
    "잔기 주석 기준으로만 했으며, 검사하지 않은 항목은 '없음'이 아니다.",
} as const;
export type JevCatalyticStatus = "not_available" | "not_checked" | "checked";
export const JEV_J6_BY_CATALYTIC_STATUS: Record<JevCatalyticStatus, string> = {
  not_available: JEV_STATEMENTS.J6, not_checked: JEV_J6_VARIANTS.J6n, checked: JEV_J6_VARIANTS.J6c };

/**
 * The `catalytic_residue_database` status of a projection wire (`backend/mw/jev_constants.catalytic_status`): a
 * ligand wire has no protection checks (`not_available`); a mutation wire's value outside the closed set is null.
 */
export function jevCatalyticStatus(kind: JevKind, wire: { protection_checks?: Record<string, unknown> } | null):
  JevCatalyticStatus | null {
  if (kind === "ligand") return "not_available";
  const value = wire?.protection_checks?.catalytic_residue_database;
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(JEV_J6_BY_CATALYTIC_STATUS, value)
    ? value as JevCatalyticStatus : null;
}

/**
 * The fixed sentences of a projection (`backend/mw/jev_constants.limitations_for`): J1–J4, then J5 (ligand) or the J6
 * variant of `catalytic`, then J7 when late. Null for an input the server would refuse (no sentence is guessed).
 */
export function jevLimitationsFor(kind: JevKind, late: boolean, catalytic: string = "not_available"): string[] | null {
  if ((kind !== "ligand" && kind !== "mutation") ||
      !Object.prototype.hasOwnProperty.call(JEV_J6_BY_CATALYTIC_STATUS, catalytic) ||
      (kind === "ligand" && catalytic !== "not_available")) return null;
  const s = JEV_STATEMENTS;
  return [s.J1, s.J2, s.J3, s.J4, kind === "ligand" ? s.J5 : JEV_J6_BY_CATALYTIC_STATUS[catalytic as JevCatalyticStatus],
    ...(late ? [s.J7] : [])];
}

/** Fixed screen notes U1–U3 (spec 6), verbatim: U1 beside the send history, U2 and U3 beside the consent switch. */
export const JEV_SCREEN_NOTES = {
  U1: "같은 후보 목록을 다시 보내면 응답이 달라질 수 있다. 응답은 합치거나 다수결로 쓰지 않고 시간순으로 따로 보인다.",
  U2: "과학 전송은 뷰어 모델 명령과 같은 외부 토큰·USD 예산과 '사용량 모름' 중지 상태를 쓰며, 한쪽이 예산을 다 쓰거나 " +
    "사용량을 모르면 이 run에서 다른 쪽도 멈춘다.",
  U3: "보내는 서열 구간과 이웃 잔기 이름만으로도 어떤 단백질인지 알려질 수 있다. 번호 대응·accession은 보내지 않는다.",
} as const;

// ---- fixed screen text ----

export const JEV_PANEL_TITLE = "JEV 판정(외부 모델)";
export const SCIENCE_ALLOWED_BADGE = "과학 전송 허용";
export const SCIENCE_BADGE_NOTE = "과학 전송 동의는 뷰어 모델 명령의 해석 모드(local_only·online)와 별개인 run 상태입니다.";
/**
 * Fixed consent notice (spec 9 (1)); the content lines follow the wire allow-list of spec 3 (ligand and mutation body
 * each). The cap use and the remaining budget come from `jev_status@1`.
 */
export const CONSENT_NOTICE: readonly string[] = [
  "이 동의를 켜면 이 run의 과학 데이터를 외부 서비스로 보낼 수 있습니다. 목적지는 OpenRouter의 JEV 하나뿐입니다.",
  "보낼 수 있는 내용: 직접 고른 후보(최대 20개)의 별칭(c01·m01 …)과 저장된 값뿐이며, 후보 순서는 후보 집합의 저장 순서입니다.",
  "리간드 후보 본문: 부모의 정규 SMILES와 RDKit 추정 속성, 후보마다 후보 정규 SMILES·생성 방식 종류(fixed_replace·" +
    "user_rule)·입체 표시(stereo_flag)·RDKit 추정 속성(mol_weight·crippen_logp·hbd·hba·tpsa·rotatable_bonds·" +
    "heavy_atoms·formal_charge)과 그 정의 이름·PAINS 구조 경고 일치(목록·이름). 수용체·포켓 정보는 넣지 않습니다.",
  "변이 후보 본문: 위치마다 잔기 식별자(모델·체인·번호·삽입 코드·잔기 이름)·한 글자 코드·위치 출처·리간드까지 최소 " +
    "거리(저장 좌표의 기하)·보호 해제 여부·같은 체인의 서열 구간(앞뒤 5개)·5.0 Å 안 이웃 잔기 이름, 후보마다 위치와 " +
    "바꿀 잔기, 그리고 집합의 보호 검사 상태와 포켓 출처를 썼을 때의 포켓 요약.",
  "보내지 않는 것: 좌표·구조 파일·전체 서열·번호 대응 값(UniProt·KLIFS)·보호 사유 이름·handle·로컬 경로·API 키.",
  "동의만으로는 아무것도 보내지 않습니다. 전송마다 정확한 본문을 미리 보고 사람이 승인해야 한 번 보냅니다.",
  `run당 과학 전송은 ${JEV_SEND_CAP}회까지입니다(보낸 뒤 실패한 전송도 1회로 셉니다).`,
  "provider 정책: data_collection=deny, zdr(데이터 보존 없음).",
  "이 동의는 뷰어 모델 명령의 온라인 동의와 별개이며 서로 권한을 주지 않습니다.",
];
export const CONSENT_SWITCH_LABEL = "과학 전송 동의(이 run)";
export const BUILD_BUTTON_TEXT = "보낼 내용 만들기";
export const CONFIRM_CHECK_TEXT = "이 본문 그대로 외부 서비스(JEV)로 보내는 데 동의합니다";
export const SEND_BUTTON_TEXT = "이 내용을 JEV로 보냅니다";
export const NOT_SENT_TEXT = "전송하지 않음";
export const ALIAS_TABLE_NOTE = "별칭 ↔ 로컬 후보 대응은 이 화면에만 있으며 외부로 보내지 않습니다.";
export const CHOICE_REASON_TEXT = "고른 이유: 알 수 없음(응답에 이유가 없음)";
export const PROBABILITY_NOTE = "후보별 확률은 모델이 보고한 값이며 보낸 후보 순서 그대로 보입니다(정렬하지 않음).";
export const NOT_REPORTED_TEXT = "보고 없음";
export const UNKNOWN_TEXT = "알 수 없음";
export const NULL_TEXT = "—";
/** Shown for any value outside a closed set (the value itself is never echoed). */
export const UNKNOWN_CODE_TEXT = "목록에 없는 코드";
export const REQUEST_FAILED_TEXT = "요청 실패";
export const NO_RUN_REASON = "run이 없습니다. 구조 분석 탭에서 run을 먼저 고르세요.";
export const CAPABILITY_REASON = "JEV 판정 기능을 사용할 수 없습니다.";
export const STATUS_LOADING_REASON = "과학 전송 상태를 읽는 중입니다.";
export const NO_SOURCE_REASON = "후보 집합을 먼저 고르세요.";
export const SELECTION_FULL_REASON = `후보는 ${JEV_MAX_CANDIDATES}개까지 고를 수 있습니다. 더 고르려면 먼저 다른 후보의 체크를 해제하세요.`;
export const FILTERED_OUT_REASON = "적용한 필터를 통과하지 못한 후보는 고를 수 없습니다.";
export const SOURCE_MISMATCH_REASON = "지금 고른 후보 집합의 후보가 아닙니다.";
export const INVALID_SOURCE_REASON = "저장된 결과를 검증하지 못해 고를 수 없습니다.";
export const EMPTY_SOURCE_REASON = "후보가 0개라 고를 수 없습니다.";
export const NO_PREVIEW_REASON = "먼저 보낼 내용을 만들고 미리보기를 읽으세요.";
export const SENDING_REASON = "전송 중입니다. 응답이 올 때까지 기다리세요(한 번에 한 전송).";
export const CONFIRM_REQUIRED_REASON = `확인 체크를 켜세요: "${CONFIRM_CHECK_TEXT}".`;
export const CHOICE_MISMATCH_TEXT = "저장된 JEV 판정을 이 전송과 맞출 수 없어 보이지 않습니다.";
export const NOT_A_PROJECTION_TEXT = "도구 결과가 JEV 투영(jev_projection@1)이 아닙니다.";

export const KIND_LABEL: Record<JevKind, string> = { ligand: "리간드 후보", mutation: "변이 후보" };
export const SOURCE_KIND_LABEL: Record<JevKind, string> = { ligand: "리간드 후보 집합", mutation: "변이 후보 집합" };
export const DRY_RUN_NOTE = "dry-run run: 보낼 내용 만들기와 미리보기는 할 수 있지만 외부로 보내지 않으며 과학 전송 동의를 " +
  "켤 수 없습니다 (dry_run).";
export const BUILDING_REASON = "보낼 내용을 만드는 중입니다.";
export const SEND_LOCK_REASON = "전송 중에는 보낼 내용을 새로 만들 수 없습니다(한 번에 한 전송).";
export const RESPONSE_SHAPE_TEXT = "응답 형식이나 대상이 요청과 다릅니다.";

/** Layout text of the JevPanel screen (every visible string of the area comes from this module). */
export const JEV_TEXT = {
  loadingCapability: "기능 상태를 확인하는 중",
  unavailable: "사용할 수 없음",
  loading: "읽는 중",
  retry: "다시 읽기",
  areaStatus: "① 상태와 동의",
  areaSource: "② 후보 집합",
  areaCandidates: "③ 후보 고르기",
  areaBuild: "④ 보낼 내용과 미리보기",
  areaApproval: "⑤ 승인과 전송",
  areaResult: `⑥ ${JEV_CHOICE_LABEL}`,
  areaHistory: "⑦ 전송 기록",
  consentOn: "켜짐",
  consentOff: "꺼짐",
  consentBusy: "동의 상태를 바꾸는 중",
  destination: "목적지",
  models: "모델",
  kindLegend: "후보 집합 종류 (자동으로 고르지 않음)",
  sourceLegend: "이 run의 후보 집합 (자동으로 고르지 않음)",
  chooseKind: "후보 집합 종류를 먼저 고르세요.",
  noSets: "이 run에 이 종류의 후보 집합이 없습니다.",
  setsReload: "후보 집합 목록 다시 읽기",
  passesOnly: "필터 통과만 보기",
  ligandFilterNote: "리간드 후보는 적용한 필터를 통과한 후보만 고를 수 있습니다(필터를 적용하지 않았으면 모든 후보).",
  orderNote: "고른 후보는 클릭 순서가 아니라 후보 집합의 저장 순서로 보냅니다(변이: 후보 번호 순서, 리간드: 생성 순서).",
  rowsLoading: "후보 행을 읽는 중",
  noRows: "표시할 후보 행이 없습니다.",
  previous: "이전",
  next: "다음",
  headerPick: "고르기",
  headerOrder: "생성 순서",
  headerCandidateId: "후보 id",
  headerSmiles: "SMILES (2D)",
  headerFilter: "모든 필터",
  headerIndex: "후보 번호",
  headerPosition: "위치 번호",
  headerResidue: "잔기",
  headerChange: "치환",
  candidateCheck: "이 후보 고르기",
  conflictNote: "선택한 후보 중 지금 적용한 필터를 통과하지 못하는 후보(체크를 해제하세요):",
  building: "보낼 내용을 만드는 중",
  projectionMade: "보낼 내용(jev_projection@1)을 저장했습니다",
  previewLoading: "미리보기를 읽는 중",
  previewReload: "미리보기 다시 읽기",
  kind: "종류",
  question: "질문 (고정 문구)",
  bodySummary: "정확한 본문 (펼쳐 보기, 이 문자열 그대로 보냄)",
  bytes: "본문 바이트",
  sha256: "본문 SHA-256",
  aliasAlias: "별칭 (보냄)",
  aliasLocal: "로컬 후보",
  aliasSent: "로컬 후보 전송",
  serverBlockers: "서버가 알린 차단 이유",
  noServerBlockers: "서버가 알린 차단 이유 없음",
  sendBlockers: "보낼 수 없는 이유",
  sendingNow: "전송 중입니다. 응답이 올 때까지 다시 눌러도 같은 전송으로 처리합니다.",
  sendRecorded: "전송 기록을 받았습니다",
  sendId: "전송 id",
  resultNone: "아직 연 결과가 없습니다. 보내거나 전송 기록에서 \"결과 열기\"를 누르세요.",
  resultLoading: "결과를 읽는 중",
  chosenAlias: "고른 후보 별칭",
  localRef: "로컬 참조",
  localDisplay: "로컬 표기",
  requestedModel: "요청 모델",
  servedModel: "응답 모델",
  usage: "사용량",
  lateMark: "늦은 응답",
  fixedSentences: "고정 문장",
  probabilities: "후보별 확률 (모델 보고값, 펼쳐 보기)",
  open: "결과 열기",
  report: "보고서 만들기",
  reportLoading: "보고서를 만드는 중",
  reportDone: "보고서를 저장했습니다. 아래 보고서 목록에서 열고 받을 수 있습니다",
  historyReload: "전송 기록 다시 읽기",
  noSends: "이 run에 과학 전송 기록이 없습니다.",
  headerApproved: "승인 기록 순번",
  headerStatus: "상태",
  headerKind: "종류",
  headerCount: "후보 수",
  headerHash: "본문 해시 앞부분",
  headerLate: "늦은 응답",
  headerActions: "동작",
} as const;

/** A preview's `send_in_progress` that a status read after that preview no longer reports (see `jevPreviewBlockers`). */
export const SEND_IN_PROGRESS_STALE_TEXT = "다시 읽기 필요: 미리보기를 읽은 뒤 이 run의 다른 과학 전송이 끝났습니다. " +
  `"${JEV_TEXT.previewReload}"를 누르세요 (send_in_progress)`;

// ---- closed reason labels ("한국어 (code)"; anything outside a set is UNKNOWN_CODE_TEXT) ----

const REFUSAL_LABEL: Record<string, string> = {
  dry_run: "dry-run run이라 보낼 수 없음",
  consent_off: "과학 전송 동의가 꺼져 있음",
  cancelled: "run이 취소됨",
  egress_stopped: "이 run의 외부 전송이 멈춤(예산 소진 또는 사용량 모름)",
  send_cap_exhausted: `run당 과학 전송 ${JEV_SEND_CAP}회를 모두 씀`,
  budget_exhausted: "남은 외부 토큰·USD 또는 활동 시간이 예약값보다 적음",
  send_in_progress: "이 run의 다른 과학 전송이 진행 중",
  missing_configuration: "요청·응답 모델 고정값이 맞지 않음",
  missing_credential: "서버에서 API 키를 찾지 못함",
};
const FAILED_LABEL: Record<string, string> = {
  external_timeout: "응답 제한 시간(15초) 초과",
  transport_error: "전송 연결 오류",
  provider_http_error: "외부 서비스가 HTTP 오류로 답함",
  response_invalid: "응답 형식이 질문과 맞지 않음(제안을 저장하지 않음)",
  missing_model: "응답에 모델 이름이 없음",
  model_mismatch: "응답 모델이 허용한 모델과 다름",
  delivery_unknown: "보냈는지·응답이 왔는지 알 수 없음(자동으로 다시 보내지 않음)",
  outcome_not_recorded: "응답은 받았으나 결과 기록이 없음(중단)",
};
const LATE_LABEL: Record<string, string> = { run_cancelled: "run 취소 뒤 도착", consent_off: "동의 끈 뒤 도착" };
const PROJECTION_LABEL: Record<string, string> = {
  unknown_field: "알 수 없는 요청 항목",
  source_invalid: "이 run의 게시·검증된 후보 집합이 아님",
  selection_invalid: `후보 선택 형식 오류(1–${JEV_MAX_CANDIDATES}개, 중복 없음)`,
  candidate_unknown: "후보 집합에 없는 후보",
  filter_invalid: "필터 명세 오류(변이 후보 집합에는 필터를 줄 수 없음)",
  candidate_filtered_out: "적용한 필터를 통과하지 못한 후보가 있음",
  structure_unavailable: "후보 집합의 전처리 구조를 읽을 수 없거나 위치 잔기가 구조와 맞지 않음",
  wire_field_invalid: "보낼 수 있는 값의 형식 규칙에 맞지 않는 값이 있음",
  payload_too_large: "본문이 64 KiB를 넘음(자르지 않고 저장하지 않음)",
  projection_invalid: "저장된 투영이 검증되지 않음",
};
const STATUS_LABEL: Record<string, string> = {
  completed: "완료(제안 저장)", rejected: "거절(보내지 않음)", failed: "실패(보냈으나 제안 없음)", in_progress: "전송 중",
};
const ERROR_LABEL: Record<string, string> = {
  preview_mismatch: "승인한 본문 해시가 이 투영의 본문과 다름(미리보기를 다시 읽으세요)",
  send_id_conflict: "같은 전송 id가 다른 내용으로 이미 승인됨(새 전송 id로 다시 보내세요)",
  send_in_progress: REFUSAL_LABEL.send_in_progress,
  busy: "run이 다른 작업 중(아무것도 승인·전송하지 않음)",
  not_found: "이 run에 없음",
  input_invalid: "요청 형식 오류",
  dry_run: REFUSAL_LABEL.dry_run,
  cancelled: REFUSAL_LABEL.cancelled,
  run_corrupt: "기록을 읽을 수 없음",
  method_evidence_invalid: "저장된 JEV 판정이 검증되지 않음",
  report_evidence_invalid: "보고서 근거가 검증되지 않음",
  resource_exceeded: "상한 초과",
  transient: "일시적 오류(run이 다른 작업 중일 수 있음, 다시 시도)",
};
const EGRESS_STOP_LABEL: Record<string, string> = { usage_unknown: "사용량 모름", budget_exhausted: "예산 소진" };

function own(table: Record<string, string>, code: string): string | undefined {
  return Object.prototype.hasOwnProperty.call(table, code) ? table[code] : undefined;
}

function labelled(codes: readonly string[], table: Record<string, string>, code: unknown, withCode = true): string {
  if (typeof code !== "string" || !codes.includes(code)) return UNKNOWN_CODE_TEXT;
  const label = own(table, code);
  if (!label) return UNKNOWN_CODE_TEXT;
  return withCode ? `${label} (${code})` : label;
}

/** A `jev_preview@1.blocked_by` reason. */
export function blockReasonText(code: unknown): string { return labelled(PREVIEW_BLOCK_REASONS, REFUSAL_LABEL, code); }
/** A stored `rejected` reason (sent nothing; the cap is not used). */
export function rejectedReasonText(code: unknown): string { return labelled(REJECTED_REASONS, REFUSAL_LABEL, code); }
/** A stored `failed` reason (sent, no proposal). */
export function failedReasonText(code: unknown): string { return labelled(FAILED_REASONS, FAILED_LABEL, code); }
/** Late arrival mark: "run 취소 뒤 도착" / "동의 끈 뒤 도착". */
export function lateReasonText(code: unknown): string { return labelled(LATE_REASONS, LATE_LABEL, code, false); }
export function projectionReasonText(code: unknown): string {
  return labelled(PROJECTION_REASON_CODES, PROJECTION_LABEL, code);
}
export function sendStatusText(status: unknown): string { return labelled(SEND_STATUSES, STATUS_LABEL, status); }
export function errorCodeText(code: unknown): string { return labelled(SEND_ERROR_CODES, ERROR_LABEL, code); }

/** The reason of one send record: null for completed and in-progress sends. */
export function sendReasonText(status: string, code: unknown): string | null {
  if (status === "rejected") return rejectedReasonText(code);
  if (status === "failed") return failedReasonText(code);
  return null;
}

export function egressStopText(reason: string | null): string | null {
  if (reason === null) return null;
  const label = own(EGRESS_STOP_LABEL, reason);
  return `이 run의 외부 전송이 멈춤: ${label ? `${label} (${reason})` : UNKNOWN_CODE_TEXT}`;
}

// ---- errors ----

export interface JevErrorInfo { status: number | null; code: string | null; reasonCode: string | null; text: string }

/** This module's own fixed texts a thrown `Error` may carry; they are the only messages shown after the label. */
const OWN_ERROR_TEXTS: readonly string[] = [RESPONSE_SHAPE_TEXT];

/**
 * An `ApiError` (or any thrown value) as status, code, `detail.reason_code` and text. JEV routes answer
 * `{"detail": {error, message, ...}}`, the command route `{"ok": false, error, message, detail: {reason_code}}`;
 * `ApiError` carries both as `code` and `detail`. The reason code wins over the error class. The text is the Korean
 * label with its code ("한국어 (code)"): the server's English `message` and a browser error's message are never shown
 * (only this module's own fixed text, e.g. an answer of the wrong shape, follows the label).
 */
export function jevErrorInfo(error: unknown): JevErrorInfo {
  if (typeof error !== "object" || error === null)
    return { status: null, code: null, reasonCode: null, text: REQUEST_FAILED_TEXT };
  const { status, code, message, detail } = error as { status?: unknown; code?: unknown; message?: unknown;
    detail?: { reason_code?: unknown } | null };
  const reasonCode = typeof detail?.reason_code === "string" ? detail.reason_code : null;
  const codeText = typeof code === "string" ? code : null;
  const head = reasonCode !== null
    ? ((PROJECTION_REASON_CODES as readonly string[]).includes(reasonCode) ? projectionReasonText(reasonCode)
      : errorCodeText(reasonCode))
    : codeText !== null ? errorCodeText(codeText) : REQUEST_FAILED_TEXT;
  const own = typeof message === "string" && OWN_ERROR_TEXTS.includes(message) ? message : null;
  return { status: typeof status === "number" ? status : null, code: codeText, reasonCode,
    text: own !== null ? `${head}: ${own}` : head };
}

// ---- panel state, status and sources ----

export type JevPanelState = { state: "loading" } | { state: "ready" } | { state: "failed"; message: string } |
  { state: "unavailable"; reason: string };

/**
 * `capability` undefined = not read yet, null = absent from `/capabilities`; `status` undefined or null = not read
 * yet. There is no scientific result here, so there is no empty-result state.
 */
export function jevPanelState(input: { runId: string | null;
  capability?: { available: boolean; reason: string | null } | null; status?: unknown; error?: string | null }):
  JevPanelState {
  if (input.runId === null) return { state: "unavailable", reason: NO_RUN_REASON };
  if (input.capability === null || input.capability?.available === false)
    return { state: "unavailable", reason: input.capability?.reason ?? CAPABILITY_REASON };
  if (input.error) return { state: "failed", message: input.error };
  if (input.capability === undefined || input.status === undefined || input.status === null) return { state: "loading" };
  return { state: "ready" };
}

/** "0.1000 USD": a stored USD amount with four decimals (display only; M25 loop area reuses it). */
export function usdText(value: number): string { return `${decimalHalfUp(value, 4)} USD`; }

/** "run당 과학 전송 10회 · 사용 n회 · 남은 m회" from a status or preview (server counts). */
export function jevCapText(value: { send_cap: number; used: number; remaining: number }): string {
  return `run당 과학 전송 ${value.send_cap}회 · 사용 ${value.used}회 · 남은 ${value.remaining}회`;
}

export function jevBudgetText(budget: JevStatusV1["budget"]): string {
  return `외부 토큰 남은 ${budget.external_tokens.remaining} / 한도 ${budget.external_tokens.limit} · ` +
    `USD 남은 ${decimalHalfUp(budget.usd.remaining, 4)} / 한도 ${decimalHalfUp(budget.usd.limit, 4)}`;
}

/** The global run line mark: only when this run's science consent is on. */
export function scienceBadgeText(status: Pick<JevStatusV1, "enabled"> | null | undefined): string | null {
  return status?.enabled === true ? SCIENCE_ALLOWED_BADGE : null;
}

/** The page's last known science consent of one run (from a status read or a consent change). */
export interface ScienceConsentMark { runId: string; enabled: boolean }

export function scienceMarkFromStatus(runId: string, status: Pick<JevStatusV1, "enabled">): ScienceConsentMark {
  return { runId, enabled: status.enabled === true };
}

/** The global line mark of the page's current run: only when the last mark is for that same run and says on. */
export function globalScienceBadge(mark: ScienceConsentMark | null, runId: string | null):
  { text: string; note: string } | null {
  if (runId === null || mark === null || mark.runId !== runId) return null;
  const text = scienceBadgeText(mark);
  return text === null ? null : { text, note: SCIENCE_BADGE_NOTE };
}

/** Request order of the page's global mark (one per page). */
export interface ScienceMarkGate {
  /** A page status read starts: its ticket supersedes every earlier read. */
  begin(): number;
  /** The JEV area reported a status (its own read or a consent change): every page read still in flight is older. */
  report(): void;
  /** Whether a page read's answer may be applied (no later read or report came since it started). */
  current(ticket: number): boolean;
}

/** A new request order: only the latest request's answer reaches the global mark. */
export function scienceMarkGate(): ScienceMarkGate {
  let latest = 0;
  return { begin: () => ++latest, report: () => { latest += 1; }, current: ticket => ticket === latest };
}

export interface JevStatusView {
  enabled: boolean; switchText: string; dryRun: boolean;
  /** Cap use and remaining external budget; null in a dry-run run (nothing can be sent there: the reason only). */
  capText: string | null; budgetText: string | null;
  /** Dry-run, cancelled, stopped egress and a send in progress, in this order (reasons only). */
  notes: string[]; destinationText: string; modelText: string;
}

export function jevStatusView(status: JevStatusV1): JevStatusView {
  const notes: string[] = [];
  if (status.dry_run) notes.push(DRY_RUN_NOTE);
  if (status.cancelled) notes.push(blockReasonText("cancelled"));
  const stop = egressStopText(status.egress_stop_reason);
  if (stop !== null) notes.push(stop);
  if (status.send_in_progress) notes.push(blockReasonText("send_in_progress"));
  const enabled = status.enabled === true;
  return { enabled, switchText: `${CONSENT_SWITCH_LABEL}: ${enabled ? JEV_TEXT.consentOn : JEV_TEXT.consentOff}`,
    dryRun: status.dry_run === true, capText: status.dry_run ? null : jevCapText(status),
    budgetText: status.dry_run ? null : jevBudgetText(status.budget), notes,
    destinationText: `${JEV_TEXT.destination}: ${status.destination}`,
    modelText: `${JEV_TEXT.requestedModel} ${status.request_model} · 허용 ${JEV_TEXT.servedModel} ` +
      status.allowed_served_model };
}

/** A `jev_status@1` answer (status read or consent change). */
export function jevStatusMatches(value: unknown): value is JevStatusV1 {
  return typeof value === "object" && value !== null && (value as { schema?: unknown }).schema === "jev_status@1";
}

/** Why the consent switch cannot move to `nextEnabled` (null = it can); turning it off is always possible. */
export function consentSwitchDisabledReason(status: Pick<JevStatusV1, "dry_run"> | null, nextEnabled: boolean):
  string | null {
  if (status === null) return STATUS_LOADING_REASON;
  if (nextEnabled && status.dry_run) return "dry-run run에서는 과학 전송 동의를 켤 수 없음 (dry_run)";
  return null;
}

export interface JevSourceOption { handle: string; text: string; disabledReason: string | null }

function sourceOption(kind: JevKind, row: { handle: string; created_seq: number; valid: boolean },
                      candidates: number | null): JevSourceOption {
  const count = candidates === null ? `후보 수 ${NULL_TEXT}` : `후보 ${candidates}개`;
  return { handle: row.handle, text: `${SOURCE_KIND_LABEL[kind]} · 기록 순번 ${row.created_seq} · ${count}`,
    disabledReason: !row.valid ? INVALID_SOURCE_REASON : candidates === 0 ? EMPTY_SOURCE_REASON : null };
}

/** This run's M17 candidate sets in server order; nothing is pre-selected. */
export function ligandSourceOptions(rows: readonly Pick<LigandCandidateSetListRow, "handle" | "created_seq" | "valid" |
  "candidates">[]): JevSourceOption[] {
  return rows.map(row => sourceOption("ligand", row, row.candidates));
}

/** This run's M20 candidate sets in server order; nothing is pre-selected. */
export function mutationSourceOptions(rows: readonly (Pick<MutationCandidateSetListRow, "handle" | "created_seq" |
  "valid"> & { counts: { candidates: number } | null })[]): JevSourceOption[] {
  return rows.map(row => sourceOption("mutation", row, row.counts?.candidates ?? null));
}

// ---- candidate selection (at most 20, one source set, stored order) ----

export type JevCandidateKey = string | number;
/** Chosen candidates of one source set, kept in the set's stored order (`order`), never click order. */
export interface JevSelection { kind: JevKind; source: string; items: readonly { key: JevCandidateKey; order: number }[] }
/** One checkable candidate row: ligand id with its stored order and filter result, or mutation candidate index. */
export type JevCandidateOption =
  | { kind: "ligand"; source: string; key: string; order: number; passesAll: boolean | null }
  | { kind: "mutation"; source: string; key: number; order: number };

export function emptyJevSelection(kind: JevKind, source: string): JevSelection { return { kind, source, items: [] }; }

/** `passes_all` null means no filter is applied (every candidate is kept); false means the applied filter refuses it. */
export function ligandCandidateOption(source: string, row: Pick<LigandCandidatePageRow, "generation_order" |
  "candidate" | "passes_all">): JevCandidateOption {
  return { kind: "ligand", source, key: row.candidate.id, order: row.generation_order, passesAll: row.passes_all };
}

/** Mutation candidates are in candidate index order. */
export function mutationCandidateOption(source: string, row: Pick<MutationCandidateRow, "index">): JevCandidateOption {
  return { kind: "mutation", source, key: row.index, order: row.index };
}

export function jevCandidateChecked(selection: JevSelection, option: JevCandidateOption): boolean {
  return option.kind === selection.kind && option.source === selection.source &&
    selection.items.some(item => item.key === option.key);
}

/** Why this candidate cannot be checked now (null = it can be checked or unchecked). */
export function jevCandidateBlockedReason(selection: JevSelection, option: JevCandidateOption): string | null {
  if (option.kind !== selection.kind || option.source !== selection.source) return SOURCE_MISMATCH_REASON;
  if (jevCandidateChecked(selection, option)) return null;
  if (option.kind === "ligand" && option.passesAll === false) return FILTERED_OUT_REASON;
  if (selection.items.length >= JEV_MAX_CANDIDATES) return SELECTION_FULL_REASON;
  return null;
}

/** Checks or unchecks one candidate; a refused check changes nothing and says why. */
export function toggleJevCandidate(selection: JevSelection, option: JevCandidateOption, checked: boolean):
  { selection: JevSelection; refused: string | null } {
  if (!checked) {
    if (!jevCandidateChecked(selection, option)) return { selection, refused: null };
    return { selection: { ...selection, items: selection.items.filter(item => item.key !== option.key) }, refused: null };
  }
  const refused = jevCandidateBlockedReason(selection, option);
  if (refused !== null) return { selection, refused };
  if (jevCandidateChecked(selection, option)) return { selection, refused: null };
  const items = [...selection.items, { key: option.key, order: option.order }]
    .sort((a, b) => a.order - b.order || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return { selection: { ...selection, items }, refused: null };
}

export function jevSelectionCountText(selection: JevSelection): string {
  return `선택 ${selection.items.length}/${JEV_MAX_CANDIDATES}`;
}

/** The chosen candidates in stored order: ligand ids or mutation candidate indices. */
export function jevSelectedCandidates(selection: JevSelection): string[] | number[] {
  return selection.kind === "ligand" ? selection.items.map(item => item.key as string)
    : selection.items.map(item => item.key as number);
}

/** Chosen ligand candidates that the current filter refuses (shown so the person unchecks them; none is dropped). */
export function jevFilterConflicts(selection: JevSelection,
                                   rows: readonly Pick<LigandCandidatePageRow, "candidate" | "passes_all">[]): string[] {
  if (selection.kind !== "ligand") return [];
  const failing = new Set(rows.filter(row => row.passes_all === false).map(row => row.candidate.id));
  return selection.items.map(item => item.key as string).filter(id => failing.has(id));
}

/** The applied M17 filter, or null when it applies nothing (no range and no PAINS exclusion). */
export function activeJevFilter(spec: LigandFilterSpec | null): LigandFilterSpec | null {
  return spec !== null && (Object.keys(spec.ranges).length > 0 || spec.pains_exclude) ? spec : null;
}

export type JevProjectionArgsCheck = { ok: true; args: JevProjectionArgs } | { ok: false; errors: string[] };

/** `build_jev_projection` arguments in the server shape (exactly source, candidates and filter). */
export function jevProjectionArgs(selection: JevSelection | null, filter: LigandFilterSpec | null):
  JevProjectionArgsCheck {
  if (selection === null) return { ok: false, errors: [NO_SOURCE_REASON] };
  const errors: string[] = [];
  if (!selection.items.length) errors.push("후보를 1개 이상 고르세요 (selection_invalid).");
  if (selection.items.length > JEV_MAX_CANDIDATES)
    errors.push(`후보는 ${JEV_MAX_CANDIDATES}개까지 고를 수 있습니다 (selection_invalid).`);
  const active = activeJevFilter(filter);
  if (selection.kind === "mutation" && active !== null)
    errors.push("변이 후보 집합에는 필터를 줄 수 없습니다 (filter_invalid).");
  if (errors.length) return { ok: false, errors };
  return { ok: true, args: { source: selection.source, candidates: jevSelectedCandidates(selection),
    filter: selection.kind === "ligand" ? active : null } };
}

/** Every reason "보낼 내용 만들기" is closed now (empty = it can be pressed). */
export function jevBuildBlockers(input: { selection: JevSelection | null; filter: LigandFilterSpec | null;
  building: boolean; sending: boolean }): string[] {
  const check = jevProjectionArgs(input.selection, input.filter);
  const reasons = check.ok ? [] : [...check.errors];
  if (input.building) reasons.push(BUILDING_REASON);
  if (input.sending) reasons.push(SEND_LOCK_REASON);
  return reasons;
}

/** "변이 후보 3개 · 본문 1234 바이트" of a stored projection summary. */
export function projectionSummaryText(summary: JevProjectionSummary): string {
  return `${KIND_LABEL[summary.kind] ?? NULL_TEXT} ${summary.selection_count}개 · 본문 ${summary.body_bytes} 바이트`;
}

export type JevProjectionOutcome = { ok: true; handle: string; summary: JevProjectionSummary } |
  { ok: false; text: string; reasonCode: string | null };

/** The command envelope of `build_jev_projection`: a stored `jev_projection@1` handle, or the refusal. */
export function jevProjectionOutcome(result: CommandResult): JevProjectionOutcome {
  if (!result.ok) {
    if ("message" in result) {
      const info = jevErrorInfo({ code: result.error, message: result.message, detail: result.detail });
      return { ok: false, text: info.text, reasonCode: info.reasonCode };
    }
    return { ok: false, text: REQUEST_FAILED_TEXT, reasonCode: null };
  }
  if (result.handle.kind !== "jev_projection" || result.handle.schema !== "jev_projection@1")
    return { ok: false, text: NOT_A_PROJECTION_TEXT, reasonCode: null };
  return { ok: true, handle: result.handle.handle, summary: result.handle.summary as unknown as JevProjectionSummary };
}

// ---- preview and approval ----

/** "후보 c_…" or "후보 번호 12 · 위치 번호 3" (local references; never sent). */
export function localRefText(ref: JevSelectionItem | JevLocalRef): string {
  return "candidate_id" in ref ? `후보 ${ref.candidate_id}`
    : `후보 번호 ${ref.candidate_index} · 위치 번호 ${ref.position_index}`;
}

export interface JevPreviewBlocker { code: string; text: string; stale: boolean }

/**
 * The preview's server refusals as shown. `send_in_progress` is the server's answer when the preview was read; when a
 * status read that arrived after that preview (`laterStatus`) no longer reports a send in progress, the reason is shown
 * as stale ("다시 읽기 필요") and still closes the send button until the person re-reads the preview (the screen never
 * re-reads it by itself: the preview read is a POST the person presses). Every other reason is shown as it is.
 */
export function jevPreviewBlockers(preview: Pick<JevPreviewV1, "blocked_by">,
                                   laterStatus: Pick<JevStatusV1, "send_in_progress"> | null = null): JevPreviewBlocker[] {
  return preview.blocked_by.map(code => {
    const stale = code === "send_in_progress" && laterStatus !== null && laterStatus.send_in_progress === false;
    return { code, text: stale ? SEND_IN_PROGRESS_STALE_TEXT : blockReasonText(code), stale };
  });
}

export interface JevPreviewView {
  projectionHandle: string; kind: JevKind; kindText: string; questionId: string;
  /** The fixed question wording and the exact body, verbatim from the server. */
  instructions: string; body: string; bodyBytesText: string; bodySha256: string;
  aliasRows: { alias: string; localRefText: string; sentText: string }[];
  reservationText: string; capText: string; budgetRemainingText: string;
  blocked: JevPreviewBlocker[]; previousSendsText: string;
}

export function jevPreviewView(preview: JevPreviewV1,
                               laterStatus: Pick<JevStatusV1, "send_in_progress"> | null = null): JevPreviewView {
  return {
    projectionHandle: preview.projection_handle, kind: preview.kind, kindText: KIND_LABEL[preview.kind],
    questionId: preview.question.id, instructions: preview.question.instructions, body: preview.body,
    bodyBytesText: `${preview.body_bytes} 바이트`, bodySha256: preview.body_sha256,
    aliasRows: preview.selection.map(item => ({ alias: item.alias, localRefText: localRefText(item),
      sentText: NOT_SENT_TEXT })),
    reservationText: `예약: 외부 토큰 ${preview.reservation.external_tokens} · ${usdText(preview.reservation.usd)}`,
    capText: jevCapText(preview),
    budgetRemainingText: `남은 외부 토큰 ${preview.budget_remaining.external_tokens} · 남은 ` +
      usdText(preview.budget_remaining.usd),
    blocked: jevPreviewBlockers(preview, laterStatus),
    previousSendsText: `같은 투영으로 이전에 보낸 수: ${preview.previous_sends}회`,
  };
}

export interface JevSendGuardInput {
  preview: JevPreviewV1 | null; confirmed: boolean; sending: boolean;
  /** A status read that arrived after the preview (null or absent = none). */
  laterStatus?: Pick<JevStatusV1, "send_in_progress"> | null;
}

/** Every reason the send button is closed now (empty = it can be pressed). */
export function jevSendBlockers(input: JevSendGuardInput): string[] {
  if (input.preview === null) return [NO_PREVIEW_REASON];
  const reasons = jevPreviewBlockers(input.preview, input.laterStatus ?? null).map(item => item.text);
  if (input.sending) reasons.push(SENDING_REASON);
  if (!input.confirmed) reasons.push(CONFIRM_REQUIRED_REASON);
  return reasons;
}

/** True only with zero server blockers, the confirmation checked and no send in flight. */
export function jevCanSend(input: JevSendGuardInput): boolean {
  return jevSendBlockers(input).length === 0;
}

/** The confirmation is bound to the exact body hash it was given for (a different body is not confirmed). */
export function jevConfirmed(confirmedFor: string | null, preview: Pick<JevPreviewV1, "body_sha256"> | null): boolean {
  return preview !== null && confirmedFor !== null && confirmedFor === preview.body_sha256;
}

/** A `jev_preview@1` answer for exactly this projection. */
export function jevPreviewMatches(value: unknown, projectionHandle: string): value is JevPreviewV1 {
  if (typeof value !== "object" || value === null) return false;
  const preview = value as Partial<JevPreviewV1>;
  return preview.schema === "jev_preview@1" && preview.projection_handle === projectionHandle &&
    typeof preview.body === "string" && typeof preview.body_sha256 === "string" && Array.isArray(preview.blocked_by);
}

// ---- send_id (client v4 UUID, one per approval) ----

export const UUID_V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
export interface CryptoLike { randomUUID?: () => string; getRandomValues?: (array: Uint8Array) => unknown }

/** A canonical lowercase v4 UUID: `crypto.randomUUID` when it gives one, else built from random bytes. */
export function newSendId(source: CryptoLike | null | undefined = globalThis.crypto): string {
  const direct = typeof source?.randomUUID === "function" ? source.randomUUID() : null;
  if (typeof direct === "string" && UUID_V4_RE.test(direct)) return direct;
  const bytes = new Uint8Array(16);
  if (typeof source?.getRandomValues === "function") source.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** One approval attempt: the previewed projection and body hash and the `send_id` every retry of it reuses. */
export interface JevSendAttempt { projectionHandle: string; bodySha256: string; sendId: string }

/** The attempt for this preview: the current one when it is for the same projection and body, else a new id. */
export function jevSendAttempt(current: JevSendAttempt | null,
                               preview: Pick<JevPreviewV1, "projection_handle" | "body_sha256">,
                               make: () => string = () => newSendId()): JevSendAttempt {
  if (current !== null && current.projectionHandle === preview.projection_handle &&
      current.bodySha256 === preview.body_sha256) return current;
  return { projectionHandle: preview.projection_handle, bodySha256: preview.body_sha256, sendId: make() };
}

/**
 * After an answer: any `jev_send@1` record (completed, rejected, failed) or a `send_id_conflict` ends the attempt (the
 * next send makes a new id). With no record (network error, busy, in progress, mismatch) the same id is kept, so a
 * retry is the same send (the server answers an approved id with its existing record).
 */
export function jevAttemptAfter(current: JevSendAttempt | null,
                                outcome: { record: true } | { record: false; code: string | null }): JevSendAttempt | null {
  if (outcome.record || outcome.code === "send_id_conflict") return null;
  return current;
}

export function jevSendRequest(attempt: JevSendAttempt): JevSendRequest {
  return { send_id: attempt.sendId, projection: attempt.projectionHandle, body_sha256: attempt.bodySha256,
    confirm: JEV_CONFIRM };
}

/** The `jev_send@1` answer is the record of exactly this attempt (same id, projection and body hash). */
export function jevSendResponseMatches(record: unknown, attempt: JevSendAttempt): record is JevSendV1 {
  if (typeof record !== "object" || record === null) return false;
  const value = record as Partial<JevSendV1>;
  return value.schema === "jev_send@1" && value.send_id === attempt.sendId &&
    value.projection_handle === attempt.projectionHandle && value.body_sha256 === attempt.bodySha256;
}

/** A send detail answer for exactly this send id. */
export function jevDetailMatches(detail: unknown, sendId: string): detail is JevSendDetail {
  if (typeof detail !== "object" || detail === null) return false;
  const value = detail as Partial<JevSendDetail>;
  return value.schema === "jev_send@1" && value.send_id === sendId;
}

// ---- result card (a proposal, shown as stored) ----

function identText(value: string | null, empty: string): string {
  return value === null ? NULL_TEXT : value === "" ? empty : value;
}

/** "LYS 체인 A · seq_auth 42 · 삽입 코드 없음 · 모델 1" from the stored 7 fields (null kept as "—"). */
export function residueText(residue: JevResidue): string {
  return `${residue.resname} 체인 ${identText(residue.chain_auth, "(빈 문자열)")} · seq_auth ${residue.seq_auth} · ` +
    `삽입 코드 ${identText(residue.icode, "없음")} · 모델 ${residue.model_number}`;
}

/** Ligand: the stored canonical SMILES as is; mutation: the residue with from→to. */
export function localDisplayText(display: JevLocalDisplay): string {
  return "smiles" in display ? display.smiles : `${residueText(display.residue)} · ${display.from}→${display.to}`;
}

/** Display text of a model-reported value in 0–1; null is "보고 없음". */
export function confidenceText(value: number | null): string {
  return value === null ? NOT_REPORTED_TEXT : decimalHalfUp(value, JEV_PROBABILITY_DIGITS);
}

export interface JevProbabilityRow { alias: string; localRefText: string; value: number | null; text: string }

/** One row per sent candidate in the sent (stored) order; a candidate without a reported value says so. */
export function probabilityRows(selection: readonly JevSelectionItem[], probabilities: Record<string, number>):
  JevProbabilityRow[] {
  return selection.map(item => {
    const value = Object.prototype.hasOwnProperty.call(probabilities, item.alias) ? probabilities[item.alias] : null;
    return { alias: item.alias, localRefText: localRefText(item), value, text: confidenceText(value) };
  });
}

export interface JevUsageRow { key: keyof JevUsage; label: string; text: string }
const USAGE_LABEL: [keyof JevUsage, string][] = [["input_tokens", "입력 토큰"], ["output_tokens", "출력 토큰"],
  ["external_tokens", "외부 토큰(입력+출력)"], ["cost", "비용(USD, 응답 보고값)"]];

/** Reported usage as is; a value the reply did not report is "알 수 없음" (never 0). */
export function usageRows(usage: JevUsage | null): JevUsageRow[] {
  return USAGE_LABEL.map(([key, label]) => {
    const value = usage === null ? null : usage[key];
    return { key, label, text: value === null ? UNKNOWN_TEXT : String(value) };
  });
}

export interface JevChoiceCard {
  sendId: string; choiceHandle: string; label: string; chosenAlias: string; localRefText: string;
  localDisplayText: string; localDisplay: JevLocalDisplay; confidenceLabel: string; confidence: number | null;
  confidenceText: string; probabilitiesReported: boolean; probabilityRows: JevProbabilityRow[];
  probabilityText: string | null; reasonText: string; requestedModel: string; servedModel: string;
  usageRows: JevUsageRow[]; lateText: string | null; limitations: readonly string[];
}

export type JevResultView =
  | { state: "in_progress"; statusText: string }
  | { state: "rejected" | "failed"; statusText: string; reasonText: string }
  | { state: "completed"; statusText: string; card: JevChoiceCard }
  | { state: "invalid"; statusText: string; message: string };

/** One send's result: the proposal card when completed, the reason only when refused or failed. */
export function jevResultView(detail: JevSendDetail): JevResultView {
  const statusText = sendStatusText(detail.status);
  if (detail.status === "in_progress") return { state: "in_progress", statusText };
  if (detail.status === "rejected" || detail.status === "failed")
    return { state: detail.status, statusText, reasonText: sendReasonText(detail.status, detail.reason_code) ?? "" };
  const choice = detail.choice;
  if (detail.status !== "completed" || choice === null || detail.choice_handle === null ||
      choice.send.send_id !== detail.send_id || choice.label !== JEV_CHOICE_LABEL || choice.scientific_result !== false)
    return { state: "invalid", statusText, message: CHOICE_MISMATCH_TEXT };
  const answer = choice.answer;
  const reported = answer.probabilities !== null;
  return { state: "completed", statusText, card: {
    sendId: detail.send_id, choiceHandle: detail.choice_handle, label: JEV_CHOICE_LABEL,
    chosenAlias: answer.choice_alias, localRefText: localRefText(answer.local_ref),
    localDisplayText: localDisplayText(answer.local_display), localDisplay: answer.local_display,
    confidenceLabel: JEV_CONFIDENCE_LABEL, confidence: answer.confidence, confidenceText: confidenceText(answer.confidence),
    probabilitiesReported: reported,
    probabilityRows: answer.probabilities === null ? [] : probabilityRows(choice.selection, answer.probabilities),
    probabilityText: reported ? null : NOT_REPORTED_TEXT, reasonText: CHOICE_REASON_TEXT,
    requestedModel: choice.requested_model, servedModel: choice.served_model, usageRows: usageRows(choice.usage),
    lateText: choice.arrival.late ? lateReasonText(choice.arrival.late_reason) : null,
    limitations: choice.limitations,
  } };
}

// ---- send history (this run, oldest first, each send on its own) ----

export interface JevSendRow {
  sendId: string; status: string; statusText: string; reasonText: string | null; kindText: string; countText: string;
  bodyHashText: string; lateText: string | null; inProgress: boolean; choiceHandle: string | null; canOpen: boolean;
  canReport: boolean; approvedSeq: number;
}

export function jevSendRows(records: readonly JevSendV1[]): JevSendRow[] {
  return [...records].sort((a, b) => a.approved_event_seq - b.approved_event_seq).map(item => ({
    sendId: item.send_id, status: item.status, statusText: sendStatusText(item.status),
    reasonText: sendReasonText(item.status, item.reason_code), kindText: KIND_LABEL[item.kind] ?? NULL_TEXT,
    countText: `후보 ${item.selection_count}개`, bodyHashText: item.body_sha256.slice(0, 8),
    lateText: item.late ? lateReasonText(item.late_reason) : null, inProgress: item.status === "in_progress",
    choiceHandle: item.choice_handle, canOpen: item.status !== "in_progress",
    canReport: item.status === "completed" && item.choice_handle !== null, approvedSeq: item.approved_event_seq,
  }));
}

/** The send list is re-read (reads only) every `JEV_POLL_MS` while a listed send is still in progress. */
export const JEV_POLL_MS = 2000;

export function jevSendsPending(records: readonly Pick<JevSendV1, "status">[]): boolean {
  return records.some(item => item.status === "in_progress");
}

/** A send list answer: an array of `jev_send@1` records. */
export function jevSendListMatches(value: unknown): value is JevSendV1[] {
  return Array.isArray(value) && value.every(item => typeof item === "object" && item !== null &&
    (item as { schema?: unknown }).schema === "jev_send@1");
}

// ---- reports ----

export function jevReportMatches(artifact: JevReportArtifact, choiceHandle: string): boolean {
  return artifact.manifest.schema === "method_report_manifest@1" &&
    artifact.manifest.analysis_type === JEV_REPORT_TYPE && artifact.manifest.result_handle === choiceHandle;
}

// ---- late responses (run + projection/send handle + request number per area) ----

export const JEV_AREAS = ["status", "consent", "sources", "candidates", "projection", "preview", "send", "sends", "detail",
  "report"] as const;
export interface JevStamp { runId: string | null; handle: string | null; seq: number }

/** Applied only when run, handle and request number are all still current. */
export function jevResponseCurrent(captured: JevStamp, live: JevStamp): boolean {
  return captured.runId !== null && captured.runId === live.runId && captured.handle === live.handle &&
    captured.seq === live.seq;
}

// ---- wording check (a proposal is never a rank, recommendation, prediction or effect) ----

/** Lines exempt from the check: exactly a fixed sentence J1–J7 or screen note U1–U3. */
export const JEV_FIXED_LINES: readonly string[] = [...Object.values(JEV_STATEMENTS), ...Object.values(JEV_SCREEN_NOTES)];
/**
 * Spec 2 and 8 wording (plus 최고, 가장 높/낮 and highest). "비활성" (inactive) is not "활성". The offscreen harness
 * (`tests/offscreen/jev-flow.cjs`) and the acceptance runner (`scripts/m24_offscreen_acceptance.py`) use this same
 * pattern and line rule; tests on both sides compare them.
 */
export const JEV_FORBIDDEN = /순위|추천|최고|최적|개선|예측|유망|점수|에너지|(?<!비)활성|친화|안정성|ΔΔG|좋은|나쁜|안전|가장 높|가장 낮|winner|\bbest|\brank|recommend|highest/gi;

/** Forbidden words in screen text, line by line; a line exactly equal to a fixed sentence or note is exempt. */
export function jevForbiddenWords(text: string): string[] {
  const found: string[] = [];
  for (const line of text.split("\n")) {
    if (JEV_FIXED_LINES.includes(line)) continue;
    for (const match of line.matchAll(JEV_FORBIDDEN)) found.push(match[0]);
  }
  return found;
}
