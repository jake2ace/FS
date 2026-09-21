// The frontend talks to the FastAPI backend through same-origin /api/* calls.
// Next.js rewrites proxy them to BACKEND_URL, so the browser never needs CORS
// and the backend URL is never hard-coded in the client bundle.
const backend = (process.env.BACKEND_URL || 'http://localhost:8000').replace(/\/$/, '');

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${backend}/api/:path*` },
      { source: '/backend-health', destination: `${backend}/health` },
    ];
  },
  // A single analysis can take a while when the AI provider is slow or retrying;
  // the default rewrite proxy timeout (30 s) would otherwise surface as a 500 in the UI.
  experimental: { proxyTimeout: 600_000 },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
