// GI-02: drive the Cesium globe's ellipsoid from the SELECTED body so the Moon/Mars globe is rendered at
// its true radius instead of the Earth-sized WGS84 default (PRD presentation gap). Pure body-key -> radii
// lookup so it is unit-testable without a browser; the renderer (cockpit.js) builds a Cesium.Ellipsoid and
// hands it to the Viewer via Cesium 1.119's `ellipsoid` constructor option (the supported per-body path --
// NOT the custom-Globe path that errored in 1.119 and black-screened the prior rewrite).
//
// SOURCED radii (meters):
//   Moon  - 1737.4 km mean radius. IAU/NASA Moon fact sheet (LRO/LOLA); Archinal et al. 2018
//           "Report of the IAU WG on Cartographic Coordinates and Rotational Elements: 2015".
//   Mars  - 3389.5 km volumetric mean radius. NASA Mars fact sheet; Archinal et al. 2018 (IAU 2015).
//   Earth - WGS84 (equatorial 6378137.0 m, polar 6356752.314245 m) -- unchanged.
"use strict";
(function (root) {
  // Spheres for the Moon/Mars globe: the streamed NASA Trek imagery is equirectangular against a sphere,
  // so a triaxial figure would mis-register the tiles. Earth keeps the oblate WGS84 figure.
  const BODY_RADII = {
    moon:  { x: 1737400,    y: 1737400,    z: 1737400 },
    mars:  { x: 3389500,    y: 3389500,    z: 3389500 },
    earth: { x: 6378137.0,  y: 6378137.0,  z: 6356752.314245 },
  };

  // Resolve a body key to its radii. Case-insensitive; an unknown key degrades to Earth so the render path
  // never throws on a bad selection (the body dropdown is enum-bounded, but the globe must not black-screen).
  function radiiFor(key) {
    const k = (typeof key === "string") ? key.toLowerCase() : "";
    return BODY_RADII[k] || BODY_RADII.earth;
  }

  // Build a Cesium.Ellipsoid for the body. Returns null when Cesium is absent so the caller degrades
  // cleanly (same contract as cockpit.js's `typeof Cesium === "undefined"` guard) instead of throwing.
  function bodyEllipsoid(Cesium, key) {
    if (!Cesium || typeof Cesium.Ellipsoid !== "function") return null;
    const r = radiiFor(key);
    return new Cesium.Ellipsoid(r.x, r.y, r.z);
  }

  const API = { BODY_RADII: BODY_RADII, radiiFor: radiiFor, bodyEllipsoid: bodyEllipsoid };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_GLOBE = API;                                           // browser (window)
})(typeof window !== "undefined" ? window : null);
