// FS-21: NAMED saved workspace layouts. PURE collection logic only -- the DOM capture/apply glue and the
// dropdown UI live in cockpit.js (wirePanelLayout). A "layout" is a named snapshot of the sidebar's VIEW
// state: the pane ORDER (the same key list panel_layout.js reorders) plus each pane's COLLAPSED/EXPANDED
// state. An operator can SAVE the current arrangement under a name, LIST saved layouts, LOAD one (restores
// order + collapsed state), RENAME, DELETE, and mark one DEFAULT (auto-applied on boot).
//
// FS-21 INVARIANT: a layout is a VIEW preference ONLY. It carries pane keys + open/closed booleans -- never
// a role, a contract, an AG gate, or any command authority. Loading a layout reorders + opens/closes panes;
// it can never change which controls a pane holds or what an operator is allowed to command.
//
// Persistence (per operator, this browser): the whole collection serialises to ONE localStorage value under
// KEY, matching the existing single-layout mechanism (stewie_panel_order / stewie_sections). The glue owns
// read/write; this module is pure data transforms over a plain { layouts:[...], defaultName } store so it is
// node:test'able without a browser.
(function (root) {
  "use strict";
  var KEY = "stewie_named_layouts";
  var MAX_NAME = 40;            // a name longer than this is truncated (a layout name is a label, not free text)
  var MAX_LAYOUTS = 50;         // a generous per-operator cap so a runaway client cannot bloat localStorage

  // Normalise an arbitrary parsed value into a well-formed store. Never throws: a corrupt / legacy / null
  // value yields the empty store, so a bad localStorage entry can never break boot. Pure.
  function normalize(raw) {
    var store = { layouts: [], defaultName: null };
    if (!raw || typeof raw !== "object") return store;
    var list = Array.isArray(raw.layouts) ? raw.layouts : [];
    var seen = Object.create(null);
    list.forEach(function (e) {
      if (!e || typeof e !== "object") return;
      var name = _cleanName(e.name);
      if (!name || seen[name.toLowerCase()]) return;        // drop blanks + case-insensitive dupes
      seen[name.toLowerCase()] = true;
      var order = Array.isArray(e.order) ? e.order.filter(_isStr) : [];
      var collapsed = (e.collapsed && typeof e.collapsed === "object") ? _cleanCollapsed(e.collapsed) : {};
      store.layouts.push({ name: name, order: order, collapsed: collapsed });
    });
    var def = _isStr(raw.defaultName) ? raw.defaultName : null;
    store.defaultName = (def && _find(store.layouts, def)) ? _find(store.layouts, def).name : null;
    return store;
  }

  function _isStr(x) { return typeof x === "string"; }
  function _cleanName(n) { return _isStr(n) ? n.trim().slice(0, MAX_NAME) : ""; }
  function _cleanCollapsed(c) {
    var out = {};
    Object.keys(c).forEach(function (k) { if (_isStr(k)) out[k] = !!c[k]; });
    return out;
  }
  // case-insensitive lookup; returns the stored entry (with its canonical-cased name) or null. Pure.
  function _find(layouts, name) {
    var key = _cleanName(name).toLowerCase();
    if (!key) return null;
    for (var i = 0; i < layouts.length; i++) {
      if (layouts[i].name.toLowerCase() === key) return layouts[i];
    }
    return null;
  }

  // --- queries (pure) ---
  function list(store) { return normalize(store).layouts.map(function (e) { return e.name; }); }
  function get(store, name) {
    var e = _find(normalize(store).layouts, name);
    return e ? { name: e.name, order: e.order.slice(), collapsed: _cleanCollapsed(e.collapsed) } : null;
  }
  function defaultName(store) { return normalize(store).defaultName; }

  // --- mutations: each returns a NEW store, never mutates its input (pure) ---

  // Save the current snapshot under `name`. A name that already exists (case-insensitive) is OVERWRITTEN in
  // place (keeping its slot + default flag). Returns { store, error }: error is a string when rejected
  // (blank name, or the cap is hit by a genuinely new name), else null.
  function save(store, name, snapshot) {
    var s = normalize(store);
    var clean = _cleanName(name);
    if (!clean) return { store: s, error: "A layout needs a name." };
    var snap = _cleanSnapshot(snapshot);
    var existing = _find(s.layouts, clean);
    var layouts = s.layouts.map(function (e) {
      return (existing && e.name.toLowerCase() === clean.toLowerCase())
        ? { name: e.name, order: snap.order, collapsed: snap.collapsed }   // overwrite, keep canonical name
        : e;
    });
    if (!existing) {
      if (layouts.length >= MAX_LAYOUTS) return { store: s, error: "Layout limit reached (" + MAX_LAYOUTS + ")." };
      layouts = layouts.concat([{ name: clean, order: snap.order, collapsed: snap.collapsed }]);
    }
    return { store: { layouts: layouts, defaultName: s.defaultName }, error: null };
  }

  function _cleanSnapshot(snapshot) {
    snapshot = snapshot || {};
    return {
      order: Array.isArray(snapshot.order) ? snapshot.order.filter(_isStr) : [],
      collapsed: (snapshot.collapsed && typeof snapshot.collapsed === "object") ? _cleanCollapsed(snapshot.collapsed) : {}
    };
  }

  // Rename `from` -> `to`. Rejects a blank target or a collision with a DIFFERENT existing layout. Carries
  // the default flag along if `from` was the default. Returns { store, error }.
  function rename(store, from, to) {
    var s = normalize(store);
    var src = _find(s.layouts, from);
    if (!src) return { store: s, error: "No such layout." };
    var clean = _cleanName(to);
    if (!clean) return { store: s, error: "A layout needs a name." };
    var clash = _find(s.layouts, clean);
    if (clash && clash.name.toLowerCase() !== src.name.toLowerCase()) {
      return { store: s, error: "A layout named that already exists." };
    }
    var layouts = s.layouts.map(function (e) {
      return e.name.toLowerCase() === src.name.toLowerCase()
        ? { name: clean, order: e.order, collapsed: e.collapsed } : e;
    });
    var def = (s.defaultName && s.defaultName.toLowerCase() === src.name.toLowerCase()) ? clean : s.defaultName;
    return { store: { layouts: layouts, defaultName: def }, error: null };
  }

  // Delete `name`. Clears the default flag if it pointed at the deleted layout. Returns { store, error }.
  function remove(store, name) {
    var s = normalize(store);
    var target = _find(s.layouts, name);
    if (!target) return { store: s, error: "No such layout." };
    var layouts = s.layouts.filter(function (e) { return e.name.toLowerCase() !== target.name.toLowerCase(); });
    var def = (s.defaultName && s.defaultName.toLowerCase() === target.name.toLowerCase()) ? null : s.defaultName;
    return { store: { layouts: layouts, defaultName: def }, error: null };
  }

  // Mark `name` the default (auto-applied on boot). Passing null/"" CLEARS the default. Returns { store, error }.
  function setDefault(store, name) {
    var s = normalize(store);
    if (name == null || _cleanName(name) === "") {
      return { store: { layouts: s.layouts, defaultName: null }, error: null };
    }
    var target = _find(s.layouts, name);
    if (!target) return { store: s, error: "No such layout." };
    return { store: { layouts: s.layouts, defaultName: target.name }, error: null };
  }

  var API = {
    KEY: KEY, MAX_NAME: MAX_NAME, MAX_LAYOUTS: MAX_LAYOUTS,
    normalize: normalize, list: list, get: get, defaultName: defaultName,
    save: save, rename: rename, remove: remove, setDefault: setDefault
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_NAMED_LAYOUTS = API;
})(typeof window !== "undefined" ? window : null);
