/* CSP gate (front-end rewrite §2): the deployed cockpit CSP is `script-src 'self' …` with NO
 * 'unsafe-inline'. Assert the built dist/index.html has zero INLINE <script> bodies — every script must
 * be an external src= (CSP-clean). Exits non-zero (fails the build) if any inline script body is found. */
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../dist/index.html", import.meta.url), "utf8");
const inline = [];
const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
let m;
while ((m = re.exec(html))) {
  const attrs = m[1] || "";
  const body = (m[2] || "").trim();
  const hasSrc = /\bsrc\s*=/.test(attrs);
  if (!hasSrc && body.length > 0) inline.push(body.slice(0, 80));
}
if (inline.length) {
  console.error(`[CSP] ${inline.length} inline <script> body(ies) in dist/index.html — these violate ` +
    `script-src 'self'. First: ${JSON.stringify(inline[0])}`);
  process.exit(1);
}
console.log("[CSP] ok — dist/index.html has no inline script bodies (all scripts are external src=)");
