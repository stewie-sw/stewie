/* artemis.stewie.space/viz page controller: wires the DOM controls to the STEWIE_VIZ full-res 3D viewer.
 * External module (CSP: script-src 'self' -- no inline handlers). Site-parametrized via ?site= (Haworth
 * default); the analysis-drape kinds + gridlines + coordinate readout are the mission-planning surface.
 */
const VIZ = window.STEWIE_VIZ;

// the imported sites that carry a real LOLA DEM bundle (stewie.specs.sites, bundle_dir set). The endpoints
// render ANY registry site; a ?site= not in this list is added so a freshly-imported site is still reachable.
const KNOWN_SITES = [
  { id: "haworth", label: "Haworth (10 km, 5 m)" },
  { id: "connecting_ridge", label: "Connecting Ridge" },
  { id: "de_gerlache_rim", label: "de Gerlache Rim" },
  { id: "de_gerlache_kocher", label: "de Gerlache-Kocher Massif" },
  { id: "leibnitz_beta", label: "Leibnitz Beta" },
  { id: "malapert_massif", label: "Malapert Massif" },
  { id: "nobile_rim", label: "Nobile Rim" },
  { id: "nobile_rim2", label: "Nobile Rim 2" },
  { id: "peak_near_shackleton", label: "Peak near Shackleton" },
  { id: "shackleton_rim", label: "Shackleton Rim" },
  { id: "shoemaker", label: "Shoemaker" },
];
const LAYERS = [
  { id: "elevation", label: "Elevation (height ramp)" },
  { id: "dem", label: "Hillshade (315/45)" },
  { id: "slope", label: "Slope (deg)" },
  { id: "aspect", label: "Aspect (gradient azimuth)" },
  { id: "curvature", label: "Curvature (Laplacian)" },
  { id: "roughness", label: "Roughness (RMS slope)" },
  { id: "hazard", label: "Hazard / no-go" },
  { id: "illumination", label: "Shadow (sun horizon)" },
  { id: "psr", label: "PSR (never lit)" },
  { id: "cost", label: "Traversability cost" },
];

function $(id) { return document.getElementById(id); }
function fmt(v, d) { return (v == null || isNaN(v)) ? "—" : (+v).toFixed(d == null ? 1 : d); }

function setStatus(msg) { const s = $("viz-status"); if (s) s.textContent = msg; }

function fillSelect(sel, items, current) {
  sel.replaceChildren();                 // MT-03: safe DOM clear
  items.forEach((it) => {
    const o = document.createElement("option");
    o.value = it.id; o.textContent = it.label;
    if (it.id === current) o.selected = true;
    sel.appendChild(o);
  });
}

async function loadSite(site) {
  setStatus("loading " + site + " at full resolution…");
  try {
    const meta = await VIZ.loadSite(site, {});
    const res = meta.lod ? (meta.n + "×" + meta.n + " (LOD, native " + meta.native_n + ")")
      : (meta.n + "×" + meta.n + " native");
    setStatus(site + " · " + res + " @ " + fmt(meta.cell_m, 1) + " m/cell · "
      + fmt(meta.window_m / 1000, 2) + " km window · relief " + fmt(meta.z_min, 0)
      + "…" + fmt(meta.z_max, 0) + " m");
  } catch (e) {
    setStatus("could not load " + site + ": " + (e && e.message ? e.message : e));
  }
}

function _bold(s) { const b = document.createElement("b"); b.textContent = s; return b; }
function _txt(s) { return document.createTextNode(s); }

function updateHud(h) {
  const el = $("viz-hud");
  if (!el) return;
  if (!h) { el.classList.add("dim"); return; }
  el.classList.remove("dim");
  const ll = (h.lat != null && h.lon != null)
    ? ("lat " + fmt(h.lat, 5) + "°  lon " + fmt(h.lon, 5) + "°") : "lat —  lon —";
  el.replaceChildren(                    // MT-03: safe DOM build, same rendered HUD
    _bold("E"), _txt(" " + fmt(h.e_m, 1) + " m   "),
    _bold("N"), _txt(" " + fmt(h.n_m, 1) + " m   "),
    _bold("elev"), _txt(" " + fmt(h.elev_m, 1) + " m"),
    document.createElement("br"),
    _txt(ll),
  );
}

function init() {
  if (!VIZ) { setStatus("viewer failed to load (STEWIE_VIZ missing)"); return; }
  const params = new URLSearchParams(location.search);
  let site = params.get("site") || "haworth";
  const sites = KNOWN_SITES.slice();
  if (!sites.some((s) => s.id === site)) sites.unshift({ id: site, label: site });

  VIZ.mount($("viz-root"));
  VIZ.onHover(updateHud);
  VIZ.onLayerError((kind) => { setStatus("layer '" + kind + "' unavailable for this window — reverted to elevation"); const ls = $("viz-layer"); if (ls) ls.value = "elevation"; });

  const siteSel = $("viz-site"); fillSelect(siteSel, sites, site);
  const layerSel = $("viz-layer"); fillSelect(layerSel, LAYERS, "elevation");

  siteSel.addEventListener("change", () => { site = siteSel.value; loadSite(site); });
  layerSel.addEventListener("change", () => VIZ.setLayer(layerSel.value));

  const vex = $("viz-vex"), vexOut = $("viz-vex-out");
  vex.addEventListener("input", () => { VIZ.setVertExag(+vex.value); vexOut.textContent = (+vex.value).toFixed(1) + "×"; });

  const sunAz = $("viz-sun-az"), sunAzOut = $("viz-sun-az-out");
  const sunEl = $("viz-sun-el"), sunElOut = $("viz-sun-el-out");
  function applySun() { VIZ.setSun(+sunAz.value, +sunEl.value); sunAzOut.textContent = sunAz.value + "°"; sunElOut.textContent = sunEl.value + "°"; }
  sunAz.addEventListener("input", applySun);
  sunEl.addEventListener("input", applySun);

  $("viz-grid").addEventListener("change", (e) => VIZ.setMetricGrid(e.target.checked));
  $("viz-grat").addEventListener("change", (e) => VIZ.setGraticule(e.target.checked));
  $("viz-wire").addEventListener("change", (e) => VIZ.setWireframe(e.target.checked));

  // task #79: measure/waypoints tool -- toggle + clear + a live count/distance readout (textContent only,
  // MT-03 safe-DOM convention: never a raw-HTML sink).
  $("viz-measure").addEventListener("change", (e) => VIZ.setMeasureMode(e.target.checked));
  $("viz-measure-clear").addEventListener("click", () => VIZ.clearMeasure());
  VIZ.onMeasure((m) => {
    const out = $("viz-measure-out");
    if (!out) return;
    out.textContent = m.count ? (m.count + " pts · " + (m.totalDist_m >= 1000
      ? (m.totalDist_m / 1000).toFixed(2) + " km" : m.totalDist_m.toFixed(1) + " m")) : "—";
  });

  // task #77: the lon/lat graticule checkbox now defaults checked (viz_haworth.html); set the flag before
  // loadSite() builds the mesh -- loadGraticule() guards on S.meta, so calling it pre-mesh is a safe no-op,
  // and loadSite's own `if (S._gratOn) loadGraticule();` then loads it once the mesh is ready.
  VIZ.setGraticule($("viz-grat").checked);
  loadSite(site);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
