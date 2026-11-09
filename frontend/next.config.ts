import type { NextConfig } from "next";

const api = process.env.API_ORIGIN || "http://127.0.0.1:8000";

const config: NextConfig = {
  poweredByHeader: false,
  turbopack: { root: process.cwd() },
  outputFileTracingRoot: process.cwd(),
  async rewrites() {
    return [{ source: "/api/:path*", destination: api + "/api/:path*" }];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};
export default config;
