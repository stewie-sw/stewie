import { chromium } from "@playwright/test";
const SCR = "/tmp/claude-1000/-mnt-projects/0e6e85aa-70b0-4aae-8bf9-42ab645b19e0/scratchpad";
const b = await chromium.launch({ args: ["--use-gl=angle","--use-angle=gl-egl","--enable-gpu","--ignore-gpu-blocklist"] });
const p = await b.newPage({ viewport: { width: 1600, height: 1000 } });
const errs=[]; p.on("pageerror",e=>errs.push(String(e.message||e).slice(0,120)));
// count WMS GetMap tiles the /ide loads from the qgis-server (/ows) for the local terrain layers.
const owsTiles=[]; p.on("response", r=>{ if(/\/ows\/.*GetMap/i.test(r.url())) owsTiles.push(r.status()); });
await p.goto("http://127.0.0.1:8083/ide/",{waitUntil:"domcontentloaded",timeout:45000});
await p.waitForTimeout(9000);
await p.getByText("STEWIE Lunar South Pole",{exact:false}).first().click({timeout:6000}).catch(()=>{});
await p.waitForTimeout(6000);
await p.screenshot({path:SCR+"/ide_gw05_map.png"});
// map CRS + no-Earth check via the running app config.
const crs = await p.evaluate(()=>{ try{ const s=window.qwc2.getState(); return {mapCrs: s.map && s.map.projection, };}catch(e){return {err:String(e)};} });
await b.close().catch(()=>{});
console.log(JSON.stringify({owsGetMapTiles: owsTiles.length, owsStatuses:[...new Set(owsTiles)], crs, pageerrs: errs.slice(0,4)},null,2));
