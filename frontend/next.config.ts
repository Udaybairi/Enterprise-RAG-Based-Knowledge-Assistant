import type { NextConfig } from "next";

const apiOrigin = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").origin;
  } catch {
    return "http://localhost:8000";
  }
})();

/**
 * Content-Security-Policy.
 *
 * The main protection is on where data can go and where code can come from: scripts only from this
 * origin, network requests only to this origin and the API, no plugins, no framing, no foreign forms.
 * That stops an injected script from loading a payload or exfiltrating the access token.
 *
 * Trade-off: Next.js inlines its bootstrap/RSC scripts, so script-src needs 'unsafe-inline' unless
 * every page is rendered dynamically with a per-request nonce (which would give up static rendering).
 * Moving the token to an HttpOnly cookie (planned) removes the remaining token-theft risk.
 */
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}`,
  "frame-src 'self' blob:", // PDF viewer renders the authenticated file from a blob: URL
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    const headers = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ];
    // The dev server needs eval for hot reloading, so the policy applies to production builds only.
    if (process.env.NODE_ENV === "production") headers.push({ key: "Content-Security-Policy", value: csp });
    return [{ source: "/(.*)", headers }];
  },
};

export default nextConfig;
