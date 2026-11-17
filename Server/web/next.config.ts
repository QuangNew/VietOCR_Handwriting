import type { NextConfig } from "next";

const target = process.env.VIETOCR_API_ORIGIN || "http://127.0.0.1:5080";
const buildDirectory = process.env.VIETOCR_WEB_BUILD_DIR || ".next";
if (!/^\.next(?:-[a-z0-9-]+)?$/.test(buildDirectory)) {
  throw new Error("VIETOCR_WEB_BUILD_DIR must be a dedicated .next directory inside the web project.");
}
if (!/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/.test(target)) {
  throw new Error("VIETOCR_API_ORIGIN must be a local backend origin.");
}
const config: NextConfig = {
  distDir: buildDirectory,
  poweredByHeader: false,
  async rewrites() { return [{ source: "/api/:path*", destination: `${target}/api/:path*` }]; },
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "same-origin" },
      { key: "X-Frame-Options", value: "DENY" }
    ] }];
  },
};
export default config;
