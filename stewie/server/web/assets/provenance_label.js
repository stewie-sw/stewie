// FS-03: the ONE reusable EPISTEMIC PROVENANCE label. Every work-area pane declares what KIND of
// knowledge it shows via a `data-epistemic="truth|belief|forecast|live"` placeholder in its header;
// this module renders the placeholder into a labelled chip (text names the kind -- never colour
// alone, WCAG 1.4.1). The vocabulary is the cockpit's own epistemics:
//   truth    -- the server's source of record: committed registries (specs/*.py), the conserved sim
//               authority, the account store. Not an estimate.
//   belief   -- what the system ESTIMATES the world to be: state estimation, the observed twin.
//   forecast -- a simulated PREDICTION: the planned mission, forward-compare, the execution replay,
//               the Godot sensor render of a planned scene.
//   live     -- a genuinely flowing feed from the running system (the /rc/telemetry/stream SSE).
//               NEVER claimed statically: the page ships it IDLE (data-live="idle"), and cockpit.js
//               flips it on/off from startRcStream/stopRcStream as the EventSource actually opens
//               and closes -- distinct from data-fresh (UI-5, recency) and #wsbadge (workspace).
// Pure + node:test'able (applyProvenanceLabels/setLiveState take any doc exposing querySelectorAll,
// mirroring the window.STEWIE_* module pattern of fleet_render.js / panel_layout.js).
(function (root) {
  "use strict";

  var KINDS = {
    truth: { text: "TRUTH", color: "#19c37d",
      title: "source of record: committed registry / conserved authority (not an estimate)" },
    belief: { text: "BELIEF", color: "#8ab4ff",
      title: "estimated state: what the system believes the world to be (estimator / observed twin)" },
    forecast: { text: "FORECAST", color: "#e0b300",
      title: "simulated prediction: planned mission / replay / rendered scene (not a live rover)" },
    live: { text: "LIVE", color: "#e8273f",
      title: "flowing feed from the running system (RC telemetry stream); IDLE until it streams" },
  };

  function epistemicKinds() { return Object.keys(KINDS); }

  // the chip markup for one kind. `state` applies to "live" only: "idle" renders the chip dimmed
  // with an explicit ·IDLE suffix so a non-streaming page never reads as a live feed.
  function badgeHTML(kind, state) {
    var k = KINDS[kind];
    if (!k) throw new Error("unknown epistemic kind: " + kind);
    var idle = kind === "live" && state !== "on";
    var text = k.text + (idle ? "·IDLE" : "");
    var color = idle ? "var(--muted, #7a8290)" : k.color;
    return '<span class="epis epis-' + kind + '" title="' + k.title + '"'
      + ' style="display:inline-flex;align-items:center;font:700 8px/1.5 \'Orbitron\',system-ui,sans-serif;'
      + "letter-spacing:.08em;padding:1px 6px;margin:0 5px;border-radius:8px;vertical-align:middle;"
      + 'border:1px solid ' + color + ";color:" + color + '">' + text + "</span>";
  }

  // render every [data-epistemic] placeholder in `doc`; returns how many were labelled.
  function applyProvenanceLabels(doc) {
    var els = doc.querySelectorAll("[data-epistemic]"), n = 0;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.innerHTML = badgeHTML(el.getAttribute("data-epistemic"), el.getAttribute("data-live"));
      n++;
    }
    return n;
  }

  // flip every live-kind label between flowing/idle (cockpit.js calls this from startRcStream once
  // the EventSource is open, and from stopRcStream); returns how many labels were flipped.
  function setLiveState(doc, on) {
    var els = doc.querySelectorAll('[data-epistemic="live"]'), n = 0;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      el.setAttribute("data-live", on ? "on" : "idle");
      el.innerHTML = badgeHTML("live", on ? "on" : "idle");
      n++;
    }
    return n;
  }

  var API = { epistemicKinds: epistemicKinds, badgeHTML: badgeHTML,
              applyProvenanceLabels: applyProvenanceLabels, setLiveState: setLiveState };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_PROVENANCE = API;                                      // browser (window)
})(typeof window !== "undefined" ? window : null);
