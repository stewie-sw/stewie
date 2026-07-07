/**
 * evidenceReport — the PURE, framework-agnostic bridge to the STEWIE EVIDENCE/REPORT BUNDLE
 * ([REQ:EV-01]) for the lunar IDE (artemis.stewie.space/ide/).
 *
 * The backend's GET /api/evidence/bundle is a PUBLIC map-data read (like /world/layer-catalog): for a given
 * site (+ optional mission / edit-session), it assembles -- from the EXISTING persisted sources -- what a
 * mission ran on: plan inputs (world-log record_plan transactions + report artifacts), the selected layers
 * (LY-01 catalog + GW-03 confidence + DT-05 per-site freshness), the runtime profile (RT-01), the world
 * transactions (DT-03 log), and the audit trail (EG-07 executive chain + optional GW-08 edit-session). It
 * also declares the host-gated ROS/Gazebo/RViz/Godot run captures HONESTLY as 'not captured'.
 *
 * This module fetches that bundle and exposes PURE helpers that normalize it into render-ready rows +
 * a single "axes" summary (which of the 5 persisted axes reproduced, and the host-gated captures shown
 * honestly). It fabricates nothing: an empty world log / empty audit / missing freshness degrade to honest
 * empties, and a host-gated capture is rendered as "not captured" with its reason -- never invented.
 *
 * Node-testable + CSP-safe: pure data/logic + fetch helpers, no DOM, no React, no module globals.
 */
(function (root) {
  "use strict";

  // Same-origin mission API (the IDE is served at /ide/; FastAPI is reverse-proxied at /api/). Overridable.
  var API_BASE = "/api";

  // The 5 axes the EV-01 acceptance says the report must REPRODUCE, in display order.
  var AXES = [
    { key: "plan_inputs",        label: "Plan inputs",        glyph: "◎" },
    { key: "selected_layers",    label: "Selected layers",    glyph: "▤" },
    { key: "runtime_profile",    label: "Runtime profile",    glyph: "⚙" },
    { key: "world_transactions", label: "World transactions", glyph: "◍" },
    { key: "audit",              label: "Audit trail",        glyph: "▦" }
  ];

  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  function bundleUrl(opts) {
    opts = opts || {};
    var qs = ["site=" + encodeURIComponent(opts.site || "haworth")];
    if (opts.mission) qs.push("mission=" + encodeURIComponent(opts.mission));
    if (opts.session) qs.push("session=" + encodeURIComponent(opts.session));
    if (opts.limit) qs.push("limit=" + encodeURIComponent(opts.limit));
    return API_BASE + "/evidence/bundle?" + qs.join("&");
  }

  // --- pure formatters --------------------------------------------------------------------------
  function shortSha(sha) {
    var s = String(sha || "");
    return s ? s.slice(0, 12) : "";
  }
  function humanTime(epochOrIso) {
    if (epochOrIso == null) return "";
    if (typeof epochOrIso === "number") {
      try { return new Date(epochOrIso * 1000).toISOString().slice(0, 19).replace("T", " "); }
      catch (e) { return ""; }
    }
    return String(epochOrIso).slice(0, 19).replace("T", " ");
  }
  function humanSize(bytes) {
    var n = Number(bytes);
    if (!isFinite(n) || n < 0) return "";
    if (n < 1024) return n + " B";
    var units = ["KB", "MB", "GB"], i = -1;
    do { n = n / 1024; i++; } while (n >= 1024 && i < units.length - 1);
    return (n < 10 ? n.toFixed(1) : Math.round(n)) + " " + units[i];
  }

  // --- pure axis + section derivations ----------------------------------------------------------
  // A per-axis reproduced/summary row from the real persisted counts. `reproduced` is derived from the
  // backend's own `reproduced` list (the axes it assembled from persisted state), never assumed.
  function axes(bundle) {
    var repro = (bundle && bundle.reproduced) || [];
    var pi = (bundle && bundle.plan_inputs) || {};
    var sl = (bundle && bundle.selected_layers) || {};
    var rp = (bundle && bundle.runtime_profile) || {};
    var wt = (bundle && bundle.world_transactions) || {};
    var au = ((bundle && bundle.audit) || {}).executive || {};
    var summary = {
      plan_inputs: (pi.n_plans || 0) + " plan tx · " + (pi.n_reports || 0) + " reports",
      selected_layers: (sl.n_planning_layers || 0) + " planning layers · " +
        (sl.freshness ? ("freshness " + sl.freshness.provenance_class) : "no freshness"),
      runtime_profile: (rp.active_profile_id || "?") + " · " + (rp.count || 0) + " profiles",
      world_transactions: (wt.count || 0) + " tx · chain " + (wt.verified ? "verified" : "UNVERIFIED"),
      audit: (au.count || 0) + " records · chain " + (au.verified ? "verified" : "UNVERIFIED")
    };
    return AXES.map(function (a) {
      return { key: a.key, label: a.label, glyph: a.glyph,
               reproduced: repro.indexOf(a.key) >= 0, summary: summary[a.key] || "" };
    });
  }

  function planTxnRows(bundle) {
    var pi = (bundle && bundle.plan_inputs) || {};
    return (pi.plan_transactions || []).map(function (t) {
      return { seq: t.seq, planId: shortSha(t.plan_id), mission: t.mission || "", provenance: t.provenance || "" };
    });
  }
  function reportRows(bundle) {
    var pi = (bundle && bundle.plan_inputs) || {};
    return (pi.reports || []).map(function (r) {
      return { stem: r.stem, pdf: r.pdf, md: r.md, size: humanSize(r.size_bytes), when: humanTime(r.mtime) };
    });
  }
  function layerRows(bundle) {
    var sl = (bundle && bundle.selected_layers) || {};
    return (sl.planning_layers || []).map(function (ly) {
      var c = ly.confidence || {};
      return { id: ly.id, domain: ly.domain, sourceClass: ly.source_class,
               confidence: c.cls || "unknown", tier: c.tier || "n/a",
               releaseExecute: !!ly.release_execute_eligible };
    });
  }
  function profileRows(bundle) {
    var rp = (bundle && bundle.runtime_profile) || {};
    var active = rp.active_profile_id;
    return (rp.registry || []).map(function (p) {
      return { id: p.id, kind: p.kind, command: p.command_capability, evidence: p.evidence_class,
               canRelease: !!p.can_release, canExecute: !!p.can_execute, active: p.id === active };
    });
  }
  function worldTxnRows(bundle) {
    var wt = (bundle && bundle.world_transactions) || {};
    return (wt.transactions || []).map(function (t) {
      return { seq: t.seq, worldSha: shortSha(t.world_sha), planId: shortSha(t.plan_id),
               mission: t.mission || "", provenance: t.provenance || "" };
    });
  }
  function auditRows(bundle) {
    var au = ((bundle && bundle.audit) || {}).executive || {};
    return (au.records || []).map(function (r) {
      return { actor: r.actor, action: r.action, when: humanTime(r.timestamp), location: r.location,
               mode: r.mode, before: r.before_state, after: r.after_state, evidence: r.evidence };
    });
  }
  function editSession(bundle) {
    return ((bundle && bundle.audit) || {}).edit_session || null;
  }
  // The host-gated captures, HONEST: each row carries captured:false + its reason (never a fabricated path),
  // or captured:true with real paths IF a run genuinely persisted one under data_dir/captures.
  function captureRows(bundle) {
    var art = (bundle && bundle.artifacts) || {};
    return (art.captures || []).map(function (cap) {
      return { kind: cap.kind, what: cap.what, captured: !!cap.captured,
               reason: cap.reason || "", paths: cap.paths || [], count: cap.count || 0 };
    });
  }
  function rosEvidence(bundle) {
    return ((bundle && bundle.artifacts) || {}).ros_gazebo_rviz || null;
  }
  function freshness(bundle) {
    return ((bundle && bundle.selected_layers) || {}).freshness || null;
  }

  // The full normalized view model the panel renders (one place, tested; the plugin is a dumb renderer).
  function buildModel(bundle) {
    return {
      ok: !!(bundle && bundle.ok),
      site: (bundle && bundle.site) || "",
      mission: (bundle && bundle.mission) || null,
      bundleSha: (bundle && bundle.bundle_sha) || "",
      axes: axes(bundle),
      planTxns: planTxnRows(bundle),
      reports: reportRows(bundle),
      layers: layerRows(bundle),
      profiles: profileRows(bundle),
      worldTxns: worldTxnRows(bundle),
      audit: auditRows(bundle),
      editSession: editSession(bundle),
      captures: captureRows(bundle),
      rosEvidence: rosEvidence(bundle),
      freshness: freshness(bundle),
      hostGated: (bundle && bundle.host_gated) || []
    };
  }

  // --- async fetch helpers (guard the global fetch so the module still imports under node) --------
  function _fetch() { return (typeof fetch !== "undefined") ? fetch : null; }
  function fetchBundle(opts) {
    var f = _fetch();
    if (!f) return Promise.reject(new Error("no fetch"));
    var url = bundleUrl(opts);
    return f(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
      return r.json();
    });
  }

  var API = {
    AXES: AXES,
    base: base, setApiBase: setApiBase, bundleUrl: bundleUrl,
    shortSha: shortSha, humanTime: humanTime, humanSize: humanSize,
    axes: axes, planTxnRows: planTxnRows, reportRows: reportRows, layerRows: layerRows,
    profileRows: profileRows, worldTxnRows: worldTxnRows, auditRows: auditRows,
    editSession: editSession, captureRows: captureRows, rosEvidence: rosEvidence,
    freshness: freshness, buildModel: buildModel, fetchBundle: fetchBundle
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test + `import X from`
  if (root) root.STEWIE_EVIDENCE_REPORT = API;                                 // browser (window)
})(typeof window !== "undefined" ? window : null);
