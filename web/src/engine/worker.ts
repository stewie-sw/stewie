/// <reference lib="webworker" />
// Web Worker hosting the WASM engine, so horizon and window computation never blocks the UI thread.
// Terrain comes from the device package (pipeline/build_package.py: south_polar_sites), served at /data in
// development: the site's 5 m tile when it has one, the site's 40 m crop, the 240 m south polar tier and
// LDEM_16. That is the R5-validated polar stack plus a finer near field (D-R47, D-R70).
import bodies from "../../../crates/stewie-contracts/fixtures/bodies.json";
import { type EngineApi, directApi } from "./api";
import init, { Engine } from "./pkg/stewie_wasm.js";

/** Which terrain an engine is built for: a catalog site and its optional 5 m bundle. */
export interface Terrain {
  site: string;
  bundle: string | null;
}

export interface Request {
  id: number;
  terrain: Terrain;
  method: keyof EngineApi;
  args: unknown[];
}

const PKG = "/data/package/south_polar_sites";
const ready = init();
interface Layer { id: string; kind: string; label: { path: string }; image: { path: string } }
let shared: { layers: Layer[]; files: Map<string, { label: string; img: Uint8Array }> } | null = null;
let current: { key: string; api: EngineApi } | null = null;

async function fetchOk(url: string): Promise<Response> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`terrain not installed: ${url} (${r.status})`);
  return r;
}

async function load(l: Layer): Promise<{ label: string; img: Uint8Array }> {
  return {
    label: await (await fetchOk(`${PKG}/${l.label.path}`)).text(),
    img: new Uint8Array(await (await fetchOk(`${PKG}/${l.image.path}`)).arrayBuffer()),
  };
}

async function apiFor(t: Terrain): Promise<EngineApi> {
  await ready;
  const key = `${t.site}|${t.bundle ?? ""}`;
  if (current && current.key === key) return current.api;
  if (!shared) {
    const manifest = (await (await fetchOk(`${PKG}/manifest.json`)).json()) as { layers: Layer[] };
    shared = { layers: manifest.layers, files: new Map() };
    for (const id of ["ldem_75s_240m", "ldem_16"]) {
      const l = manifest.layers.find((x) => x.id === id);
      if (!l) throw new Error(`terrain not installed: ${id} missing from the package`);
      shared.files.set(id, await load(l));
    }
  }
  const e = new Engine(JSON.stringify(bodies));
  if (t.bundle) {
    const meta = await (await fetchOk(`/data/tiles/${t.bundle}/metadata.json`)).text();
    const heights = new Uint8Array(await (await fetchOk(`/data/tiles/${t.bundle}/heightmap.rf32`)).arrayBuffer());
    e.addTile(0, t.bundle, meta, heights);
  }
  const crop = shared.layers.find((x) => x.id === `ldem_85s_40m_${t.site}`);
  if (crop) {
    const f = await load(crop);
    e.addPolar(1, crop.id, f.label, f.img);
  }
  const polar = shared.files.get("ldem_75s_240m")!;
  e.addPolar(2, "ldem_75s_240m", polar.label, polar.img);
  const global = shared.files.get("ldem_16")!;
  e.addGlobal(9, "ldem_16", global.label, global.img);
  current = { key, api: directApi(e) };
  return current.api;
}

self.onmessage = async (ev: MessageEvent<Request>) => {
  const { id, terrain, method, args } = ev.data;
  try {
    const api = await apiFor(terrain);
    const value = await (api[method] as (...a: unknown[]) => Promise<unknown>)(...args);
    self.postMessage({ id, ok: true, value });
  } catch (e) {
    self.postMessage({ id, ok: false, error: e instanceof Error ? e.message : String(e) });
  }
};
