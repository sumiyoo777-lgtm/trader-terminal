import type { NextConfig } from "next";

// All /api/trader-terminal/* calls are proxied to the FastAPI backend so the
// browser stays same-origin (no CORS, one URL).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/trader-terminal/:path*",
        destination: `${BACKEND_URL}/api/trader-terminal/:path*`,
      },
    ];
  },
};

export default nextConfig;
