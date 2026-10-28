import type { NextConfig } from "next";

// The browser talks to /backend/*, which Next forwards to the API server-side, so the API needs
// no CORS rules and its address never reaches the browser.
const apiUrl = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default config;
