// ARCH-02: CESIUM_BASE_URL must be set BEFORE Cesium.js loads so Cesium locates its Workers/Assets at
// the self-hosted same-origin path (WEB-01). Externalized from an inline <script> so the production CSP
// script-src can drop 'unsafe-inline'. Loaded immediately before /cesium/Cesium.js in index.html.
window.CESIUM_BASE_URL = "/cesium/";
