import type { ReactNode } from "react";
// Self-hosted fonts (no request to Google at runtime — local-first).
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/noto-sans-kr/400.css";
import "@fontsource/noto-sans-kr/600.css";
import "@/design/tokens.css";
import "@/design/components.css";
import "./globals.css";

export const metadata = { title: "Molecular Workspace", description: "로컬 단백질 구조 워크스페이스 + 자율 에이전트 런타임" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko" data-theme="dark" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
