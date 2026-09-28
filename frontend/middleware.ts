import { NextResponse, type NextRequest } from "next/server";
import { HOST_REJECT_MESSAGE, HOST_REJECT_STATUS, isAllowedHost } from "./src/lib/host-allowlist";

// No matcher: runs for every request (pages, static assets, and the /api/* rewrite proxy),
// before the proxy rewrites Host to 127.0.0.1:8000.
export function middleware(request: NextRequest) {
  if (!isAllowedHost(request.headers.get("host"))) {
    return new NextResponse(HOST_REJECT_MESSAGE, {
      status: HOST_REJECT_STATUS,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }
  return NextResponse.next();
}
