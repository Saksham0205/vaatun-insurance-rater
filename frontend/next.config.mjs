/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  devIndicators: false,
  // NEXT_DIST_DIR lets a verification build run beside `next dev` without sharing `.next`.
  distDir: process.env.NEXT_DIST_DIR || '.next',
};
export default nextConfig;
