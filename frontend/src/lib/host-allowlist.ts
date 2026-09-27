// Host header allowlist (DNS-rebinding guard). Mirrors backend/mw/api/app.py host_allowed:
// only loopback names, optional numeric port, case-insensitive. Anything else (or no Host) is rejected.
export const HOST_REJECT_STATUS = 400;
export const HOST_REJECT_MESSAGE = "Host header not allowed";

const ALLOWED_HOST_RE = /^(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?$/i;

export function isAllowedHost(host: string | null | undefined): boolean {
  return typeof host === "string" && ALLOWED_HOST_RE.test(host);
}
