// Promise RPC to the engine worker. One worker serves every screen; each call names its terrain.
import type { EngineApi } from "./api";
import type { Request, Terrain } from "./worker";

let worker: Worker | null = null;
let seq = 0;
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();

function call(terrain: Terrain, method: keyof EngineApi, args: unknown[]): Promise<unknown> {
  if (!worker) {
    worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    worker.onmessage = (ev: MessageEvent<{ id: number; ok: boolean; value?: unknown; error?: string }>) => {
      const p = pending.get(ev.data.id);
      pending.delete(ev.data.id);
      if (ev.data.ok) p?.resolve(ev.data.value);
      else p?.reject(new Error(ev.data.error));
    };
  }
  const id = ++seq;
  const req: Request = { id, terrain, method, args };
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker!.postMessage(req);
  });
}

/** The engine for one site's terrain (its 5 m bundle when it has one, over the device package). */
export function workerApi(terrain: Terrain): EngineApi {
  return {
    horizon: (...a) => call(terrain, "horizon", a) as ReturnType<EngineApi["horizon"]>,
    azEl: (...a) => call(terrain, "azEl", a) as ReturnType<EngineApi["azEl"]>,
    windows: (...a) => call(terrain, "windows", a) as ReturnType<EngineApi["windows"]>,
    stackSignature: () => call(terrain, "stackSignature", []) as ReturnType<EngineApi["stackSignature"]>,
  };
}
