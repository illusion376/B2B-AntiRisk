import type { NextConfig } from 'next';
import { PHASE_DEVELOPMENT_SERVER } from 'next/constants';

export default function nextConfig(phase: string): NextConfig {
  const development = phase === PHASE_DEVELOPMENT_SERVER;
  return {
    ...(development ? { experimental: { proxyClientMaxBodySize:'1100mb', proxyTimeout:300000 }, rewrites: async () => [{ source:'/api/:path*', destination:`${process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'}/api/:path*` }] } : { output:'export' as const }),
    trailingSlash: !development,
    poweredByHeader: false,
    images: { unoptimized:true },
    devIndicators: false,
    allowedDevOrigins: ['terminal.local'],
  };
}
