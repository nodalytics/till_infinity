import type { Metadata } from "next";
import { BOOT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "till_infinity desk",
  description: "What the desk traded, what it refused, and what that came to.",
  /**
   * Named here rather than left to `app/icon.*` file conventions, so the
   * three assets live in one directory with the mark the top bar uses and
   * `public/` is referenced from more than one place - a `public/` nothing
   * references is a `public/` that quietly fails to reach a build.
   *
   * The `.ico` exists because a browser asks for `/favicon.ico` whether or
   * not a page declares one, and a 404 on every load is noise in exactly the
   * console somebody is reading to debug something else. The `.svg` is the
   * brand-green mark, which is the one variant that works against both a
   * light and a dark tab strip; the apple-touch icon is 180px on the dark
   * ground, because iOS composites a transparent icon onto black.
   */
  icons: {
    icon: [
      { url: "/till-infinity-logo.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "32x32 16x16" },
    ],
    apple: [{ url: "/till-infinity-apple-touch.png", sizes: "180x180", type: "image/png" }],
  },
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
