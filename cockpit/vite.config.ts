import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";

// CSP-clean production build (front-end rewrite plan §2): the deployed cockpit CSP is
// `script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' …` with NO 'unsafe-inline'. Vite's default
// module-preload polyfill is an inline <script> that policy would block, so we disable it — the build
// then emits only external <script type=module src=…> + <link rel=modulepreload>, both CSP-clean.
// Verified by scripts/check-csp.mjs (asserts the built index.html has zero inline <script> bodies).
export default defineConfig({
  plugins: [react(), cesium()],
  build: {
    modulePreload: { polyfill: false },
    target: "es2020",
  },
});
