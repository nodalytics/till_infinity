import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next dev` otherwise writes a `web/AGENTS.md` describing itself, which is
  // a generated file in a repository that already has one at its root.
  agentRules: false,
  // The floating dev badge sits over the bottom-left of the chart.
  devIndicators: false,
  // Emits a server plus only the modules it actually imports, instead of
  // requiring `node_modules` at runtime. The trading host has two cores and
  // 3.8GB, shared with the live desk, so the runtime layer being small is
  // the difference between this being deployable there and not.
  output: "standalone",
  // The repository root, so the standalone trace does not stop at `web/`.
  outputFileTracingRoot: path.join(__dirname, ".."),
};

export default nextConfig;
