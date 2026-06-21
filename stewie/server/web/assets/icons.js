// ICON-SET: production-grade monochrome inline-SVG icons for the cockpit toolbar.
//
// Why: an earlier sweep removed the color emoji from icon-only toolbar buttons and left interim TEXT
// WORDS in their place ("plot", "measure", "fly", "coords", "edit", "delete", "box", "keep-out circle",
// "note", "pause", "clear plots", the alert bell). Words on icon-only buttons read as a placeholder, not
// a finished UI. This module supplies clean, stroke-based monochrome glyphs that inherit the cockpit's
// graphite/drum-red brand via `stroke="currentColor"` (so they recolor with the button text + the active
// accent automatically) -- no color emoji, no raster, no external icon font.
//
// CSP-safe by construction: icon() returns inline <svg> MARKUP (or a built SVGElement), never a <script>.
// The host inserts it via innerHTML / appendChild; nothing here evals or injects executable script.
// viewBox 0 0 24 24, fill="none", stroke="currentColor"; sizing/stroke-width come from the `.ic` CSS
// class in index.html (width/height 1em, stroke-width 2), so a glyph scales with the button font-size.
//
// Pure + node:test'able: the paths are static strings; icon() does string assembly only (DOM is used
// only in the optional element() helper, guarded for the browser). Extracted standalone so the icon
// inventory is unit-testable without a browser (each named icon must be a valid, script-free <svg>).
(function (root) {
  "use strict";

  // Each entry is the INNER markup of a 24x24 stroke glyph (paths/shapes only). `icon(name)` wraps it
  // in the <svg> shell with the shared attributes. Kept as inner-only so the shell is defined once and
  // every glyph is guaranteed the same viewBox / stroke contract.
  var GLYPHS = {
    // map-pin + center dot: "plot a labeled coordinate marker on the surface"
    plot: '<path d="M12 21s-6-5.2-6-10a6 6 0 0 1 12 0c0 4.8-6 10-6 10Z"/><circle cx="12" cy="11" r="2"/>',
    // ruler on the diagonal with tick marks: "measure distance between two points"
    measure: '<rect x="2.5" y="8.5" width="19" height="7" rx="1" transform="rotate(-45 12 12)"/><path d="M9 9l1.4 1.4M12 6l1.4 1.4M15 9l1.4 1.4"/>',
    // four-way move arrows (free-look / fly through the 3D world)
    fly: '<path d="M12 3v18M3 12h18M12 3l-2.4 2.4M12 3l2.4 2.4M12 21l-2.4-2.4M12 21l2.4-2.4M3 12l2.4-2.4M3 12l2.4 2.4M21 12l-2.4-2.4M21 12l-2.4 2.4"/>',
    // crosshair target: "live cursor coordinate readout"
    coords: '<circle cx="12" cy="12" r="7"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="1.5"/>',
    // pencil: "edit session / draw mode"
    edit: '<path d="M14.5 5.5l4 4M4 20l1-4L16 5a2.1 2.1 0 0 1 3 3L8 19l-4 1Z"/>',
    // trash can: "delete the selected pin"
    delete: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M10 11v6M14 11v6"/>',
    // rectangle: "rectangular keep-out barrier (box)"
    box: '<rect x="4" y="6" width="16" height="12" rx="1"/>',
    // no-entry sign: "keep-out circle barrier"
    keepout: '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
    // note page with lines: "attach a text note"
    note: '<path d="M6 3h8l4 4v14a0 0 0 0 1 0 0H6a0 0 0 0 1 0 0V3Z"/><path d="M14 3v4h4M8 12h8M8 16h6"/>',
    // two bars: "pause"
    pause: '<rect x="7" y="5" width="3.2" height="14" rx="1"/><rect x="13.8" y="5" width="3.2" height="14" rx="1"/>',
    // right-pointing triangle: "play / resume"
    play: '<path d="M8 5.5v13l11-6.5-11-6.5Z"/>',
    // backspace key: "clear plotted markers"
    clear: '<path d="M9 5h11a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H9L2 12 9 5Z"/><path d="M16 9l-5 6M11 9l5 6"/>',
    // bell: "alerts"
    alert: '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    // gear: "settings"
    settings: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5 5l2.1 2.1M16.9 16.9 19 19M19 5l-2.1 2.1M7.1 16.9 5 19"/>',
    // sun with rays: "sun / lighting geometry"
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M19.8 4.2l-2.1 2.1M6.3 17.7l-2.1 2.1"/>',
    // floppy-disk outline: "save"
    save: '<path d="M5 4h11l3 3v13H5V4Z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    // camera outline: "twin snapshot"
    snapshot: '<path d="M4 8h3l1.5-2h7L17 8h3v11H4V8Z"/><circle cx="12" cy="13" r="3.2"/>',
    // compass / orientation
    compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5 13 13l-4.5 2.5L11 11l4.5-2.5Z"/>'
  };

  // <svg> shell + shared brand contract. opts.cls appends extra classes (default just `.ic`); opts.title
  // adds an accessible <title> child (most callers keep the button's own title=/aria-label instead).
  function icon(name, opts) {
    var inner = GLYPHS[name];
    if (inner == null) throw new Error("STEWIE_ICONS: unknown icon '" + name + "'");
    opts = opts || {};
    var cls = "ic" + (opts.cls ? " " + opts.cls : "");
    var title = opts.title ? "<title>" + _esc(opts.title) + "</title>" : "";
    return '<svg class="' + cls + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
           'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
           title + inner + "</svg>";
  }

  // The five HTML-significant characters, for the optional title= path (defence in depth; titles here
  // are app-authored, but escaping keeps icon() injection-safe for any caller).
  var _ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function _esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return _ESC[c]; }); }

  // Browser convenience: parse the markup into a real <svg> element (CSP-safe -- markup, not script).
  function element(name, opts) {
    if (typeof document === "undefined") throw new Error("STEWIE_ICONS.element requires a DOM");
    var tpl = document.createElement("template");
    tpl.innerHTML = icon(name, opts);
    return tpl.content.firstElementChild;
  }

  // Names available, for callers/tests that want to iterate the inventory.
  function names() { return Object.keys(GLYPHS); }

  var API = { icon: icon, element: element, names: names, GLYPHS: GLYPHS };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ICONS = API;                                            // browser (window)
})(typeof window !== "undefined" ? window : null);
