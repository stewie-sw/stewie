// [REQ:FS-28] the Execute-pane command-authority evidence card renders the eligibility verdict --
// every named gate, and on an ineligible command the LEGIBLE refusal reason -- so the operator sees a
// command's authority (and why it is refused) before sending it. node --test; pure, no DOM.
const test = require("node:test");
const assert = require("node:assert");
const { commandAuthorityHTML } = require("./command_authority_html.js");

// the same SEC-04 escaper shape the cockpit injects (htmlesc.js): escape the five HTML-significant chars.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

test("commandAuthorityHTML: an ineligible verdict surfaces the legible refusal reason", () => {
  const h = commandAuthorityHTML(
    { eligible: false, reason: "unauthorized_sandbox", mode_ok: false, released: false,
      safe_inactive: true, link_ack: true, watchdog_alive: true }, esc);
  assert.ok(h.includes("INELIGIBLE"), "shows the INELIGIBLE state");
  assert.ok(h.includes("unauthorized_sandbox"), "surfaces the refusal reason string");
  assert.ok(h.includes("✗ role"), "a failed gate renders its ✗ mark");
});

test("commandAuthorityHTML: an eligible verdict shows ELIGIBLE and every named gate", () => {
  const h = commandAuthorityHTML(
    { eligible: true, reason: "eligible", mode_ok: true, released: true, safe_inactive: true,
      link_ack: true, watchdog_alive: true }, esc);
  assert.ok(h.includes("ELIGIBLE") && !h.includes("INELIGIBLE"));
  for (const gate of ["role", "released", "SAFE-clear", "link", "watchdog"]) {
    assert.ok(h.includes("✓ " + gate), `gate '${gate}' rendered as passing`);
  }
});

test("commandAuthorityHTML: escapes a hostile reason string (SEC-04)", () => {
  const h = commandAuthorityHTML({ eligible: false, reason: "<img onerror=x src=y>" }, esc);
  assert.ok(!h.includes("<img onerror=x"), "the raw hostile tag is not injected");
  assert.ok(h.includes("&lt;img"), "the reason is HTML-escaped");
});

test("commandAuthorityHTML: a missing/empty verdict does not crash", () => {
  const h = commandAuthorityHTML(undefined, esc);
  assert.ok(h.includes("INELIGIBLE"), "an absent verdict fails closed to ineligible");
});
