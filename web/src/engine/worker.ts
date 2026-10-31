/// <reference lib="webworker" />
// Web Worker hosting the WASM engine, so horizon and window computation never blocks the UI thread.
// Terrain is fetched from /data (served from the repo in development; the data package in production).
import bodies from "../../../crates/stewie-contracts/fixtures/bodies.json";
import { type EngineApi, directApi } from "./api";
import init, { Engine } from "./pkg/stewie_wasm.js";

export interface Request {
  id: number;
  bundle: string | null;
  method: keyof EngineApi;
  args: unknown[];
}

const ready = init();
let global: { label: string; img: Uint8Array } | null = null;
let current: { bundle: string | null; api: EngineApi } | null = null;

async function fetchOk(url: string): Promise<Response> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`terrain not installed: ${url} (${r.status})`);
  return r;
}

async function apiFor(bundle: string | null): Promise<EngineApi> {
  await ready;
  if (current && current.bundle === bundle) return current.api;
  global ??= {
    label: await (await fetchOk("/data/global/ldem_16.lbl")).text(),
    img: new Uint8Array(await (await fetchOk("/data/global/ldem_16.img")).arrayBuffer()),
  };
  const e = new Engine(JSON.stringify(bodies));
  if (bundle) {
    const meta = await (await fetchOk(`/data/tiles/${bundle}/metadata.json`)).text();
    const heights = new Uint8Array(await (await fetchOk(`/data/tiles/${bundle}/heightmap.rf32`)).arrayBuffer());
    e.addTile(1, bundle, meta, heights);
  }
  e.addGlobal(9, "ldem_16", global.label, global.img);
  current = { bundle, api: directApi(e) };
  return current.api;
}

self.onmessage = async (ev: MessageEvent<Request>) => {
  const { id, bundle, method, args } = ev.data;
  try {
    const api = await apiFor(bundle);
    const value = await (api[method] as (...a: unknown[]) => Promise<unknown>)(...args);
    self.postMessage({ id, ok: true, value });
  } catch (e) {
    self.postMessage({ id, ok: false, error: e instanceof Error ? e.message : String(e) });
  }
};
