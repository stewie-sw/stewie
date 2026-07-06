/**
 * wholeMoonGlobe.js — framework-agnostic controller for the STEWIE "Whole Moon" overview globe
 * (artemis.stewie.space/ide/). Design option (b): a whole-Moon context surface, SEPARATE from the
 * south-polar QWC2 workbench (the polar-stereographic map cannot show the whole Moon — the north pole
 * projects to infinity), so the operator can see BOTH hemispheres for context and then dive into a site.
 *
 * WHY A DEDICATED 3-D GLOBE (not the 2-D map): a spinnable Cesium globe shows both hemispheres at once.
 * REUSE, not reinvent: this mirrors the proven lunar-globe setup the app.stewie.space cockpit already
 * ships (stewie/server/web/assets/cockpit.js: Moon ellipsoid via globe_ellipsoid.js + the LRO WAC global
 * mosaic streamed from NASA Trek through a Cesium GeographicTilingScheme). Same Cesium 1.119 build,
 * same imagery source, same equirectangular 2x1 pyramid.
 *
 * IMAGERY (real, no fabricated texture): the LRO WAC global mosaic (303 ppd), NASA Solar System Treks.
 * The operator's BROWSER fetches the tiles DIRECTLY from trek.nasa.gov: the artemis origin sets no CSP
 * (verified), and the artemis-web container has NO egress to trek.nasa.gov (verified — a same-origin
 * nginx proxy is therefore impossible), so browser-direct is both the CSP-safe AND the only viable path.
 * This is exactly how the cockpit already loads the same tiles on app.stewie.space.
 *
 * CESIUM is SELF-HOSTED same-origin (no CDN): served by nginx `location /ide/` from prod/cesium/, which
 * gis/qwc2/build.sh vendors from the repo's already-vendored Cesium 1.119 (stewie/server/cesium/).
 * CESIUM_BASE_URL must be set BEFORE Cesium.js so it locates its Workers/Assets same-origin.
 *
 * Pure DOM/Cesium; no React. The WholeMoon plugin (js/plugins/WholeMoon.jsx) mounts a container and
 * drives this. Exposed on window.STEWIE_WHOLE_MOON for parity with the other STEWIE window.* modules.
 */
// IAU 2015 mean radius (Archinal et al. 2018) — identical to globe_ellipsoid.js + cockpit.js.
const MOON_RADIUS_M = 1737400;

// Self-hosted Cesium 1.119 (no CDN). Served at /ide/cesium/ (nginx `location /ide/` -> prod/cesium/).
const CESIUM_BASE = "/ide/cesium/";

// Real LRO WAC global mosaic (303 ppd), NASA Solar System Treks — the SAME source + tiling the
// app.stewie.space cockpit uses (cockpit.js BODIES.moon.layers[0]). Equirectangular geographic pyramid.
const WAC = {
    url: "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg",
    maximumLevel: 8,
    tile: 256,
    credit: "NASA Trek — LRO WAC global mosaic (303 ppd)"
};

let cesiumPromise = null;

/**
 * Lazily load the self-hosted Cesium 1.119 bundle (so the IDE does not pay ~5 MB on every session — only
 * when the operator opens the Whole Moon overview). Resolves with window.Cesium. Idempotent.
 */
function loadCesium() {
    if (typeof window !== "undefined" && window.Cesium) {
        return Promise.resolve(window.Cesium);
    }
    if (cesiumPromise) {
        return cesiumPromise;
    }
    cesiumPromise = new Promise((resolve, reject) => {
        try { window.CESIUM_BASE_URL = CESIUM_BASE; } catch { /* read-only env: harmless */ }
        // Cesium Viewer chrome CSS (injected once, same-origin).
        if (!document.querySelector("link[data-stewie-cesium-css]")) {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = CESIUM_BASE + "Widgets/widgets.css";
            link.setAttribute("data-stewie-cesium-css", "1");
            document.head.appendChild(link);
        }
        const s = document.createElement("script");
        s.src = CESIUM_BASE + "Cesium.js";
        s.async = true;
        s.onload = () => {
            if (window.Cesium) {
                resolve(window.Cesium);
            } else {
                cesiumPromise = null;
                reject(new Error("Cesium.js loaded but window.Cesium is undefined"));
            }
        };
        s.onerror = () => {
            cesiumPromise = null;
            reject(new Error("failed to load " + s.src));
        };
        document.head.appendChild(s);
    });
    return cesiumPromise;
}

/**
 * Build the Moon globe into `container` (a DOM element). Returns a controller {viewer, ell, handler}.
 * onSitePick(site) fires when the operator clicks a site marker.
 */
function createGlobe(Cesium, container, opts) {
    const options = opts || {};
    // Moon sphere at true radius (the streamed WAC imagery is equirectangular against a sphere), built via
    // Cesium 1.119's supported per-body path: Ellipsoid.default + the `ellipsoid` Viewer option BEFORE
    // construction (NOT the custom-Globe path that black-screened the prior cockpit rewrite).
    const ell = new Cesium.Ellipsoid(MOON_RADIUS_M, MOON_RADIUS_M, MOON_RADIUS_M);
    try { Cesium.Ellipsoid.default = ell; } catch { /* older Cesium: per-body via the Viewer option */ }

    const viewer = new Cesium.Viewer(container, {
        baseLayer: false, baseLayerPicker: false, geocoder: false, timeline: false,
        animation: false, sceneModePicker: false, homeButton: false, navigationHelpButton: false,
        fullscreenButton: false, infoBox: false, selectionIndicator: false,
        ellipsoid: ell,
        contextOptions: { webgl: { preserveDrawingBuffer: true } }   // allow scene.canvas.toDataURL() capture
    });

    // No Earth atmosphere on a per-body ellipsoid (guard: scene.skyAtmosphere is undefined for non-WGS84).
    if (viewer.scene.skyAtmosphere) { viewer.scene.skyAtmosphere.show = false; }
    viewer.scene.globe.showGroundAtmosphere = false;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#12121a");
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#05050a");
    viewer.scene.globe.enableLighting = false;   // uniform illumination -> both hemispheres readable
    // Hide the default celestial actors: this is a flat context view, not an ephemeris scene. Removes the
    // stray sun lens-flare glint + the (Earth's-)moon billboard + the star skybox for a clean space backdrop.
    if (viewer.scene.sun) { viewer.scene.sun.show = false; }
    if (viewer.scene.moon) { viewer.scene.moon.show = false; }
    if (viewer.scene.skyBox) { viewer.scene.skyBox.show = false; }
    viewer.canvas.style.cursor = "grab";

    // Real LRO WAC drape (browser fetches trek.nasa.gov directly).
    viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
        url: WAC.url,
        maximumLevel: WAC.maximumLevel,
        tileWidth: WAC.tile,
        tileHeight: WAC.tile,
        credit: WAC.credit,
        tilingScheme: new Cesium.GeographicTilingScheme({ numberOfLevelZeroTilesX: 2, numberOfLevelZeroTilesY: 1 })
    }));

    // Frame the whole disk, biased toward the south pole (the mission region). Distance ~3.4R keeps the
    // full limb (both hemispheres of the visible disk) inside the FOV; the operator can spin/zoom freely.
    viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(0, -35, MOON_RADIUS_M * 2.4, ell)
    });

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((e) => {
        const p = viewer.scene.pick(e.position);
        if (p && p.id && p.id._stewieSite && typeof options.onSitePick === "function") {
            options.onSitePick(p.id._stewieSite);
        }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return { viewer, ell, handler };
}

/**
 * Add the real Artemis-site registry as clickable markers (real region names as labels). `sites` is the
 * /api/sites payload rows: {name, label, lat, lon, imported, ...}. Imported sites (a real DEM bundle on
 * disk) render green; candidate-only sites render amber — the same honesty convention as the cockpit.
 */
function addSites(Cesium, ctrl, sites) {
    if (!ctrl || !ctrl.viewer) { return 0; }
    const ell = ctrl.ell;
    let n = 0;
    (sites || []).forEach((s) => {
        if (!s || typeof s.lon !== "number" || typeof s.lat !== "number") { return; }
        const col = Cesium.Color.fromCssColorString(s.imported ? "#39ff14" : "#e0b300");
        const ent = ctrl.viewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(s.lon, s.lat, 0, ell),
            point: {
                pixelSize: 8,
                color: col,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 1,
                disableDepthTestDistance: Number.POSITIVE_INFINITY   // markers stay visible over the limb
            },
            label: {
                text: s.label || s.name,
                font: "12px system-ui, sans-serif",
                fillColor: Cesium.Color.WHITE,
                outlineColor: Cesium.Color.fromCssColorString("#05050a"),
                outlineWidth: 3,
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                pixelOffset: new Cesium.Cartesian2(11, 0),
                horizontalOrigin: Cesium.HorizontalOrigin.LEFT,
                verticalOrigin: Cesium.VerticalOrigin.CENTER,
                disableDepthTestDistance: Number.POSITIVE_INFINITY,
                scaleByDistance: new Cesium.NearFarScalar(1.5e6, 1.0, 8.0e6, 0.55)
            }
        });
        ent._stewieSite = s;
        n += 1;
    });
    return n;
}

/** Fly the camera to frame a single site (used when a header chip is clicked without leaving the overview). */
function focusSite(Cesium, ctrl, site) {
    if (!ctrl || !ctrl.viewer || !site) { return; }
    ctrl.viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(site.lon, site.lat, MOON_RADIUS_M * 0.35, ctrl.ell),
        duration: 1.1
    });
}

/** Tear down the viewer + handler. Safe to call repeatedly. */
function destroy(ctrl) {
    if (!ctrl) { return; }
    try { if (ctrl.handler && !ctrl.handler.isDestroyed()) { ctrl.handler.destroy(); } } catch { /* */ }
    try { if (ctrl.viewer && !ctrl.viewer.isDestroyed()) { ctrl.viewer.destroy(); } } catch { /* */ }
}

const API = {
    MOON_RADIUS_M,
    CESIUM_BASE,
    WAC,
    loadCesium,
    createGlobe,
    addSites,
    focusSite,
    destroy
};

if (typeof window !== "undefined") { window.STEWIE_WHOLE_MOON = API; }

export default API;
