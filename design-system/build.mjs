/* esbuild build for the STEWIE design-system seed.
 * Produces:
 *   dist/stewie-ds.js   — the library IIFE (sets window.StewieDS; React bundled in for standalone use)
 *   dist/stewie-ds.css  — tokens + @font-face + component styles (fonts copied to dist/fonts/)
 *   dist/gallery.js      — LOCAL-ONLY showcase app (ReactDOM-renders every component) for screenshotting
 * The first two are the shippable design system; gallery.* is the review/verification harness. */
import * as esbuild from "esbuild";
import { mkdirSync } from "node:fs";

mkdirSync("dist", { recursive: true });

const common = {
  bundle: true,
  jsx: "automatic",
  loader: { ".woff2": "file" },
  assetNames: "fonts/[name]",
  logLevel: "info",
};

// 1) the library bundle (IIFE, window.StewieDS) — standalone use + the gallery
await esbuild.build({
  ...common,
  entryPoints: ["src/index.tsx"],
  outfile: "dist/stewie-ds.js",
  format: "iife",
  globalName: "StewieDSBundle",
  minify: true,
});

// 1b) the ESM library entry (react/react-dom external) — the entry /design-sync's converter consumes
await esbuild.build({
  ...common,
  entryPoints: ["src/index.tsx"],
  outfile: "dist/index.js",
  format: "esm",
  external: ["react", "react-dom", "react/jsx-runtime"],
});

// 2) the stylesheet (resolves @import tokens + the @font-face woff2)
await esbuild.build({
  ...common,
  entryPoints: ["src/styles.css"],
  outfile: "dist/stewie-ds.css",
  minify: true,
});

// 3) the local gallery app (NOT shipped — renders every component for visual review)
await esbuild.build({
  ...common,
  entryPoints: ["gallery/gallery.tsx"],
  outfile: "dist/gallery.js",
  format: "iife",
});

console.log("build ok: dist/stewie-ds.js, dist/stewie-ds.css, dist/gallery.js");
