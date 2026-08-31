import type { NextConfig } from 'next';

const isDev = process.env.NODE_ENV === 'development';

const nextConfig: NextConfig = {
  ...(isDev ? {} : { output: 'export' }),
  eslint: {
    ignoreDuringBuilds: true,
  },
  trailingSlash: false,
  images: {
    unoptimized: true,
  },
  compiler: {
    removeConsole: !isDev,
  },
  ...(isDev && {
    allowedDevOrigins: ['*.trycloudflare.com'],
    async rewrites() {
      return {
        beforeFiles: [
          {
            source: '/api/:path*',
            destination: 'http://localhost:8080/api/:path*',
          },
          {
            source: '/healthz',
            destination: 'http://localhost:8080/healthz',
          },
        ],
      };
    },
  }),
};

export default nextConfig;
