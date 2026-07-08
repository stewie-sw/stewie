/**
 * runtimeClient — the PURE bridge to the STEWIE RUNTIME PROFILE REGISTRY (RT-01) for the IDE's Runtime
 * Context rail (surface-the-backend inc2b). GET /api/runtime/profiles is a PUBLIC informational read (made
 * keyless in 090ee9a): the 7 execution environments a mission can run in -- desktop_sil / digital_twin /
 * ros2_replay / gazebo_sim / hil / field_test / live_rover -- each with its command capability
 * (none/bounded/full), evidence class, and whether it can release / execute on real hardware. This module
 * builds the URL + normalizes the response; no DOM/React -> node-testable.
 */
(function (root) {
  "use strict";
  var API_BASE = "/api";
  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  function profilesUrl() { return API_BASE + "/runtime/profiles"; }

  function fetchProfiles() {
    return fetch(profilesUrl()).then(function (r) {
      if (!r.ok) { throw new Error("runtime-profiles HTTP " + r.status); }
      return r.json();
    });
  }

  // A profile carries LIVE command authority only if it can release/execute on real hardware.
  function _authority(p) {
    if (p.can_execute || p.can_release) { return "live command"; }
    if (p.command_capability && p.command_capability !== "none") { return "bounded (sim)"; }
    return "evidence only";
  }

  function buildProfilesModel(data) {
    if (!data || data.ok === false) {
      return { ok: false, error: (data && data.error) || "runtime profiles unavailable" };
    }
    var profiles = (data.profiles || []).map(function (p) {
      return {
        id: p.id, kind: p.kind || "", authority: _authority(p),
        command: p.command_capability || "none", evidence: p.evidence_class || null,
        release: !!p.can_release, execute: !!p.can_execute, desc: p.description || ""
      };
    });
    return { ok: true, count: profiles.length, profiles: profiles };
  }

  var API = { base: base, setApiBase: setApiBase, profilesUrl: profilesUrl, fetchProfiles: fetchProfiles, buildProfilesModel: buildProfilesModel };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_RUNTIME = API; }                                         // browser (window)
})(typeof window !== "undefined" ? window : null);
