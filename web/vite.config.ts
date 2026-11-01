import { createReadStream, existsSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

/** Development only: serve terrain from the repository at /data (production reads the data package). */
function repoTerrain(): Plugin {
  const repo = resolve(import.meta.dirname, "..");
  const routes: [RegExp, (m: RegExpMatchArray) => string][] = [
    [/^\/data\/tiles\/([a-z0-9_]+)\/(metadata\.json|heightmap\.rf32)$/, (m) => resolve(repo, "samples/lunar_dem", m[1]!, m[2]!)],
    [/^\/data\/package\/south_polar_sites\/([a-z0-9_]+\.(?:json|lbl|img))$/, (m) => resolve(repo, ".cache/package/south_polar_sites", m[1]!)],
    [/^\/data\/package\/south_polar_sites\/display\/(tiles\.json|\d+\/\d+\/\d+\.png)$/, (m) => resolve(repo, ".cache/package/south_polar_sites/display", m[1]!)],
  ];
  return {
    name: "stewie-repo-terrain",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        for (const [re, path] of routes) {
          const m = req.url?.match(re);
          if (m) {
            const file = path(m);
            if (!existsSync(file)) {
              res.statusCode = 404;
              res.end();
              return;
            }
            createReadStream(file).pipe(res);
            return;
          }
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), repoTerrain()],
  server: { fs: { allow: [".."] } }, // the contract schemas and fixtures live in ../crates/stewie-contracts
  worker: { format: "es" },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test-setup.ts"] },
});
