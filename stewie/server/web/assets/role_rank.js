// FS-24: role-authority ordering. The single pure helper that turns a role name into its rank in the
// guest < trainee < operator < director ladder, so the cockpit can gate chrome and command authority
// with `_rrank(role) >= _rrank("operator")`. An unknown role returns -1 (below guest), which keeps an
// unrecognised role from accidentally clearing a gate. No DOM, no globals -- extracted from cockpit.js
// (PRD FS-24) verbatim so the ordering is unit-testable without a browser; behaviour is preserved
// exactly. node:test'able.
(function (root) {
  "use strict";

  var _ROLES = ["guest", "trainee", "operator", "director"];

  // role name -> ladder index (guest 0 .. director 3); unknown role -> -1 (below guest).
  function rrank(r) { return _ROLES.indexOf(r); }

  var API = { rrank: rrank };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ROLE_RANK = API;                                        // browser (window)
})(typeof window !== "undefined" ? window : null);
