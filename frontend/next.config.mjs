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
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
