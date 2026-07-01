// FS-03 (node:test): the Fleet-pane renderers are pure -> unit-testable without a browser. FS-15: the
// roster fixture below is the RAW /fleet response shape, routed through adapters.normalizeFleetRoster
// exactly as the cockpit does -- this tests the response-fixture -> adapter -> render chain, and the
// failure modes (empty registry, error/empty outcome mapping) below it.
// Run: node --test stewie/server/web/assets/fleet_render.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const F = require("./fleet_render.js");
const A = require("./adapters.js");

// identity-ish escaper standing in for window.STEWIE_HTMLESC.esc (real one is tested in htmlesc.test.js).
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// a real /fleet payload shape (specs/vehicles.py: ipex + the data-only bodies).
const FLEET = {
  ok: true, count: 3, ui_visible_count: 1, default_vehicle: "ipex",
  vehicles: [
    { id: "ipex", label: "ISRU Pilot Excavator (IPEx)", dry_mass_kg: 30.0, drum_capacity_kg: 30.0,
      drive_power_w: 40.38, dig_energy_j_per_kg: 4151.4, can_dig: true, ui_visible: true,
      capabilities: ["compact", "drive", "dump", "excavate", "haul"],
      onboard_power: [{ id: "ipex_battery", label: "IPEx 12S/30Ah Li-ion", kind: "battery", capacity_j: 4795200 }] },
    { id: "rassor2", label: "RASSOR 2.0 (TRL-4 breadboard precursor)", dry_mass_kg: 65.0, drum_capacity_kg: 80.0,
      drive_power_w: 40.38, dig_energy_j_per_kg: 4151.4, can_dig: true, ui_visible: false,
      capabilities: ["drive", "excavate"], onboard_power: [] },
  ],
};

test("fleetRosterHTML: renders one row per registry vehicle with its real specs (via the FS-15 VM)", () => {
  const html = F.fleetRosterHTML(A.normalizeFleetRoster(FLEET), esc);
  assert.ok(html.includes("ipex"), "ipex id present");
  assert.ok(html.includes("ISRU Pilot Excavator"), "ipex label present");
  assert.ok(html.includes("30.0"), "ipex dry mass present");
  assert.ok(html.includes("80.0"), "rassor2 drum capacity present");
  assert.ok(html.includes("4.80 MJ"), "onboard power capacity in MJ (derived capacityMJ)");
  assert.ok(html.includes("excavate"), "capability rendered");
  assert.ok(html.includes("IPEx 12S/30Ah"), "onboard power label rendered");
  assert.ok(html.includes("(data only)"), "ui_visible=false flagged, not hidden");
  assert.ok(html.includes("default ipex"), "default vehicle footer");
});

test("fleetRosterHTML: honest empty when the registry serves no vehicles (adapter -> null VM)", () => {
  assert.strictEqual(A.normalizeFleetRoster({ ok: true, vehicles: [] }), null);  // empty payload -> null VM
  const html = F.fleetRosterHTML(null, esc);
  assert.ok(html.includes("No vehicle registry"), "empty state shown");
});

test("FS-15 failure modes: /fleet outcomes map to error/empty/loading view states", () => {
  const err = A.toViewState({ status: 403, json: { ok: false, error: "operator role required" },
    normalize: A.normalizeFleetRoster });
  assert.strictEqual(err.state, "error");
  assert.strictEqual(err.error, "operator role required");
  const empty = A.toViewState({ status: 200, json: { ok: true, vehicles: [] },
    normalize: A.normalizeFleetRoster });
  assert.strictEqual(empty.state, "empty");
  assert.strictEqual(A.toViewState({ status: "pending" }).state, "loading");
});

test("fleetPlanHTML: empty state when no plan has been run", () => {
  assert.ok(F.fleetPlanHTML(null, esc).includes("No fleet allocation"));
  assert.ok(F.fleetPlanHTML({ vehicles_detail: [] }, esc).includes("No fleet allocation"));
});

test("fleetPlanHTML: renders the live per-vehicle allocation + makespan + conflicts", () => {
  const totals = {
    vehicles: 2, makespan_s: 7200, makespan_parallel_s: 3600,
    vehicle_conflicts: 0, temporal_conflicts: 0, haul_path_conflicts: 0, charger_conflicts: 1,
    fleet_needs_replan: false,
    vehicles_detail: [
      { vehicle: "v0", n_trips: 4, time_s: 3600, energy_J: 5e6, distance_m: 1200, charges: 1,
        charger_wait_s: 0, crowd_wait_s: 0, precedence_wait_s: 0,
        health: { health: "nominal", min_batt_frac: 0.42 } },
      { vehicle: "v1", n_trips: 3, time_s: 3000, energy_J: 4e6, distance_m: 900, charges: 0,
        charger_wait_s: 600, crowd_wait_s: 0, precedence_wait_s: 0,
        health: { health: "low_margin", min_batt_frac: 0.11 } },
    ],
  };
  const html = F.fleetPlanHTML(totals, esc);
  assert.ok(html.includes("2 rovers"), "fleet size");
  assert.ok(html.includes("makespan"), "makespan label");
  assert.ok(html.includes("2.00 h"), "makespan in hours (7200s)");
  assert.ok(html.includes("v0") && html.includes("v1"), "both vehicles");
  assert.ok(html.includes("low_margin"), "health rollup rendered");
  assert.ok(html.includes("charger: 1"), "charger conflict count surfaced");
  assert.ok(html.includes("chg 0.17h"), "charger wait (600s) rendered");
});

test("fleetPlanHTML: surfaces the stranded-rover replan flag", () => {
  const totals = {
    vehicles: 1, makespan_s: 100, vehicle_conflicts: 0,
    fleet_needs_replan: true,
    vehicles_detail: [{ vehicle: "v0", n_trips: 1, time_s: 100, energy_J: 1, distance_m: 1, charges: 0,
      health: { health: "stranded", min_batt_frac: 0.0 } }],
  };
  const html = F.fleetPlanHTML(totals, esc);
  assert.ok(html.includes("needs replan"), "replan warning shown");
  assert.ok(html.includes("stranded"), "stranded health shown");
});
