/** Identity captured before an asynchronous OpenMM action. All fields are live at commit. */
export type OpenmmActionIdentity = {
  epoch: number;
  runId: string | null;
  input: string | undefined;
  jobId: string | null;
  result: string | undefined;
  action: number;
};

export function currentOpenmmAction(captured: OpenmmActionIdentity, live: OpenmmActionIdentity): boolean {
  return captured.epoch === live.epoch && captured.runId === live.runId &&
    captured.input === live.input && captured.jobId === live.jobId &&
    captured.result === live.result && captured.action === live.action;
}

export type OpenmmContext = { runId: string | undefined; input: string | undefined; jobId: string | null };

export function openmmContextChange(previous: OpenmmContext | null, current: OpenmmContext) {
  const inputChanged = previous !== null && (previous.runId !== current.runId || previous.input !== current.input);
  return { resetPolicy: inputChanged, resetErrors: inputChanged ||
    (previous !== null && previous.jobId !== current.jobId) };
}

export function selectedOpenmmReadError(error: { key: string; message: string } | null, key: string | null): string | null {
  return error?.key === key ? error.message : null;
}

export type OpenmmBudgetRequest = { request: number; epoch: number; runId: string | null; jobId: string | null };

export function currentOpenmmBudgetRequest(captured: OpenmmBudgetRequest, live: OpenmmBudgetRequest): boolean {
  return captured.request === live.request && captured.epoch === live.epoch &&
    captured.runId === live.runId && captured.jobId === live.jobId;
}

/** Decimal ROUND_HALF_UP, including negative ties, matching report claims. */
export function formatEnergy2(value: number): string {
  if (!Number.isFinite(value) || Math.abs(value) >= 1e15) return "invalid";
  const [mantissa, exponent = "0"] = Math.abs(value).toString().toLowerCase().split("e");
  const [whole, fractional = ""] = mantissa.split(".");
  const digits = whole + fractional;
  const decimal = whole.length + Number(exponent);
  const expanded = decimal <= 0 ? `0.${"0".repeat(-decimal)}${digits}`
    : decimal >= digits.length ? `${digits}${"0".repeat(decimal - digits.length)}.0`
      : `${digits.slice(0, decimal)}.${digits.slice(decimal)}`;
  const [integer, fraction = ""] = expanded.split(".");
  const padded = `${fraction}000`;
  let cents = BigInt(integer) * 100n + BigInt(padded.slice(0, 2));
  if (Number(padded[2]) >= 5) cents += 1n;
  const rendered = `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
  return value < 0 && cents !== 0n ? `-${rendered}` : rendered;
}
