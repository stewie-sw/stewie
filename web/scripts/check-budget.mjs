// RW-56: the browser bundle budget. After `npm run build`, every built asset of each kind (the engine's
// WebAssembly, the JavaScript) must fit the raw and gzip byte limits committed in ../budget.json; a kind with no
// built asset fails, so the check cannot pass vacuously.
import { readFileSync, readdirSync } from "node:fs";
import { gzipSync } from "node:zlib";

const budget = JSON.parse(readFileSync(new URL("../budget.json", import.meta.url), "utf8"));
const dir = new URL("../dist/assets/", import.meta.url);
const assets = readdirSync(dir);
let failed = false;
for (const [kind, limit] of Object.entries(budget.kinds)) {
  const files = assets.filter((f) => f.endsWith(`.${kind}`));
  if (files.length === 0) {
    console.error(`budget: no .${kind} asset in dist/assets (run npm run build first)`);
    process.exit(1);
  }
  let raw = 0;
  let gzip = 0;
  for (const f of files) {
    const bytes = readFileSync(new URL(f, dir));
    raw += bytes.length;
    gzip += gzipSync(bytes, { level: 9 }).length;
  }
  const ok = raw <= limit.raw_bytes && gzip <= limit.gzip_bytes;
  console.log(
    `${kind}: ${raw} B raw (budget ${limit.raw_bytes}), ${gzip} B gzip (budget ${limit.gzip_bytes}) ${ok ? "ok" : "OVER"}`,
  );
  failed ||= !ok;
}
process.exit(failed ? 1 : 0);
