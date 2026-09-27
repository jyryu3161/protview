/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Backend (FastAPI) runs on :8000. Proxy so the browser never talks to anything else.
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" }];
  },
};
export default nextConfig;
