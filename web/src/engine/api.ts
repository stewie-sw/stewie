// The asynchronous engine surface the UI uses. In the app it is a Web Worker running the WASM engine; in
// tests it is the same engine called directly (directApi), so components are tested on real computation.
import type { Interval } from "../compare/timeline";
import type { Horizon } from "../sky/geometry";
import type { Engine } from "./pkg/stewie_wasm.js";

export interface EngineHorizon extends Horizon {
  reach_m: number[];
  complete: boolean[];
  sources: string[];
}

export interface EngineApi {
  horizon(lat: number, lon: number): Promise<EngineHorizon>;
  azEl(body: "SUN" | "EARTH", utc: string, lat: number, lon: number): Promise<[number, number]>;
  windows(body: "SUN" | "EARTH", lat: number, lon: number, startUtc: string, endUtc: string, horizon: EngineHorizon): Promise<Interval[]>;
  stackSignature(): Promise<string>;
}

/** Horizon sampling used by every screen: 720 azimuths, 200 km, 50 m steps, 1.5 m eye (navigator R4). */
export const HORIZON = { nAz: 720, maxRangeM: 200_000, stepM: 50, eyeM: 1.5 } as const;
export const WINDOW_SAMPLE_S = 600;

export function directApi(e: Engine): EngineApi {
  return {
    horizon: async (lat, lon) => JSON.parse(e.horizon(lat, lon, HORIZON.nAz, HORIZON.maxRangeM, HORIZON.stepM, HORIZON.eyeM)),
    azEl: async (body, utc, lat, lon) => {
      const v = e.azEl(body, utc, lat, lon, HORIZON.eyeM);
      return [v[0]!, v[1]!];
    },
    windows: async (body, lat, lon, startUtc, endUtc, horizon) =>
      JSON.parse(e.windows(body, lat, lon, startUtc, endUtc, WINDOW_SAMPLE_S, HORIZON.eyeM, JSON.stringify(horizon))),
    stackSignature: async () => e.stackSignature(),
  };
}
