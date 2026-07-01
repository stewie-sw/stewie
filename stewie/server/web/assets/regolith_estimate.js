// FS-24: pure dig-only feasibility estimate. computeEstimate() takes the pad dims + cut/berm inputs, the
// body terramechanics p (density, g), and the IPEx constants ix, and returns the estimate object (no DOM).
// feasibilityBreakdownHTML() renders the ⓘ popover table from that object. The badges + DOM wiring stay in
// cockpit.js. Dig-dominant by design (cutMass drives everything). Sets window.STEWIE_REGOLITH_ESTIMATE.
(function (root) {
  "use strict";

  function computeEstimate(inp, p, ix) {
    const padW = +inp.padW, padL = +inp.padL, cut = +inp.cut, bermH = +inp.bermH;
    const cutVol = padW * padL * cut;                        // m^3
    const cutMass = cutVol * p.density;                      // kg
    const weightN = cutMass * p.g;                           // N (weight on THIS body)
    const bermArea = bermH > 0 ? cutMass / (bermH * p.density) : 0;   // mass-balanced berm footprint [m^2]
    const drumLoads = Math.ceil(cutMass / ix.drum_kg);
    const energyJ = cutMass * ix.dig_j_per_kg;               // excavation energy (dominant term)
    const charges = energyJ / ix.battery_j, hrs = cutMass / ix.dig_rate_kg_hr;
    const rw = (ix.recharge_w || 700), perChargeH = ix.battery_j / rw / 3600;
    const rechargeH = charges * perChargeH;
    return { padW, padL, cut, bermH, cutVol, cutMass, weightN, bermArea, drumLoads, energyJ,
             charges, hrs, rw, perChargeH, rechargeH, p, digJPerKg: ix.dig_j_per_kg };
  }

  function feasibilityBreakdownHTML(e2) {
    const row = function (k, v) {
      return '<tr><td style="color:var(--muted);padding-right:10px">' + k
        + '</td><td style="text-align:right">' + v + "</td></tr>";
    };
    return "<b>Feasibility breakdown</b><table style=\"width:100%;border-collapse:collapse;margin-top:4px\">"
      + row("excavated volume", e2.cutVol.toFixed(0) + " m³")
      + row("mass (ρ = " + e2.p.density + " kg/m³)", (e2.cutMass / 1000).toFixed(1) + " t")
      + row("weight @ " + e2.p.g + " m/s²", (e2.weightN / 1000).toFixed(0) + " kN")
      + row("drum loads", e2.drumLoads.toLocaleString())
      + row("berm footprint @ " + e2.bermH + " m", e2.bermArea.toFixed(0) + " m²")
      + row("dig energy", (e2.energyJ / 1e6).toFixed(1) + " MJ")
      + row("battery charges", e2.charges.toFixed(1))
      + row("dig time", "~" + Math.round(e2.hrs).toLocaleString() + " h")
      + row("recharge time", "~" + Math.round(e2.rechargeH).toLocaleString() + " h ("
          + e2.charges.toFixed(0) + " × " + e2.perChargeH.toFixed(1) + " h @ " + e2.rw + " W [CALIB])")
      + row("<b>mission timeline</b>", "<b>~" + Math.round(e2.hrs + e2.rechargeH).toLocaleString() + " h</b>")
      + '</table><div style="opacity:.6;margin-top:4px">dig-energy basis: ' + Math.round(e2.digJPerKg)
      + " J/kg (excavation mechanics — cutting + drum + losses; ~8,600× the pure m·g·h lift floor). The "
      + "sandbox is DIG-dominant by design; the solver in 4·Plan adds travel + slip + recharge routing "
      + "per leg. Updates live.</div>";
  }

  var API = { computeEstimate: computeEstimate, feasibilityBreakdownHTML: feasibilityBreakdownHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_REGOLITH_ESTIMATE = API;                               // browser (window)
})(typeof window !== "undefined" ? window : null);
