import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next dev` otherwise writes a `web/AGENTS.md` describing itself, which is
  // a generated file in a repository that already has one at its root.
  agentRules: false,
  // The floating dev badge sits over the bottom-left of the chart.
  devIndicators: false,
};

export default nextConfig;
