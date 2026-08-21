import type { NextConfig } from "next";

/**
 * Static export. The app is a browser client that talks to the FastAPI backend
 * over HTTPS, so it needs no Node runtime of its own — which makes Amplify
 * Hosting a plain CDN deploy with no SSR compute to pay for or debug.
 * See ADR.md, decision 4.
 */
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
