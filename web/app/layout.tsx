import type { Metadata } from "next";
import { BOOT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "till_infinity desk",
  description: "What the desk traded, what it refused, and what that came to.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `suppressHydrationWarning` because the script below sets `data-theme`
    // before React sees the document, so the server's markup and the client's
    // differ by exactly that attribute and by design.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Resolving the theme in an effect paints the wrong one and then
            corrects it; this runs before first paint. `BOOT` is a constant in
            `lib/theme.ts` built from a literal key - no value from a request,
            a URL or storage is interpolated into it, so there is nothing here
            for a caller to inject. */}
        <script dangerouslySetInnerHTML={{ __html: BOOT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
