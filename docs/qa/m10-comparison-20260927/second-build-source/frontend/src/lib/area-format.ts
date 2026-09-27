/** Decimal ROUND_HALF_UP for finite SASA values stored as JSON numbers. */
export function formatArea2(value: number): string {
  if (!Number.isFinite(value) || Math.abs(value) >= 1e15) return "invalid";
  if (Math.abs(value) < 0.0001) return "0.00";
  const [whole, fraction = ""] = Math.abs(value).toString().split(".");
  const padded = `${fraction}000`;
  let cents = BigInt(whole) * 100n + BigInt(padded.slice(0, 2));
  if (Number(padded[2]) >= 5) cents += 1n;
  const result = `${cents / 100n}.${String(cents % 100n).padStart(2, "0")}`;
  return value < 0 && cents !== 0n ? `-${result}` : result;
}
