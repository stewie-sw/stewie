// The browser engine through its generated JS bindings (src/engine/pkg, `npm run build:engine`), on the same
// real inputs as the native R10 golden: the bindings must reproduce the native results.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import bodies from "../../../crates/stewie-contracts/fixtures/bodies.json";
import golden from "../../../crates/stewie-wasm/golden/scenario.json";
import { Engine, initSync } from "./pkg/stewie_wasm.js";

const repo = (p: string) => resolve(process.cwd(), "..", p);
initSync({ module: readFileSync(repo("web/src/engine/pkg/stewie_wasm_bg.wasm")) });

const SITE = { lat: -86.31839866054835, lon: -25.414052740154946 };

function engine(): Engine {
  const e = new Engine(JSON.stringify(bodies));
  e.addTile(1, "haworth_10km_5m", readFileSync(repo("samples/lunar_dem/haworth_10km_5m/metadata.json"), "utf8"), readFileSync(repo("samples/lunar_dem/haworth_10km_5m/heightmap.rf32")));
  e.addGlobal(9, "ldem_16", readFileSync(repo(".cache/terrain/ldem_16.lbl"), "utf8"), readFileSync(repo(".cache/terrain/ldem_16.img")));
  return e;
}

describe("engine bindings", () => {
  const e = engine();
  const hJson = e.horizon(SITE.lat, SITE.lon, 720, 200_000, 50, 1.5);
  const h = JSON.parse(hJson) as { elev_deg: (number | null)[]; sources: string[]; complete: boolean[] };

  it("horizon equals the native golden", () => {
    expect(h.elev_deg.length).toBe(720);
    h.elev_deg.forEach((v, k) => expect(Math.abs(v! - golden.horizon_elev_deg[k]!)).toBeLessThanOrEqual(1e-9));
    expect(h.sources).toEqual(["haworth_10km_5m", "ldem_16"]);
  });

  it("Sun and Earth az-el equal the native golden", () => {
    for (let i = 0; i < 24; i++) {
      const t = `2027-01-01T${String(i).padStart(2, "0")}:00:00Z`;
      const sun = e.azEl("SUN", t, SITE.lat, SITE.lon, 1.5);
      const earth = e.azEl("EARTH", t, SITE.lat, SITE.lon, 1.5);
      expect(Math.abs(sun[0]! - golden.sun_az_el[i]![0]!)).toBeLessThanOrEqual(1e-9);
      expect(Math.abs(earth[1]! - golden.earth_az_el[i]![1]!)).toBeLessThanOrEqual(1e-9);
    }
  });

  it("windows from the returned horizon equal the native golden", () => {
    const w = JSON.parse(e.windows("SUN", SITE.lat, SITE.lon, "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z", 600, 1.5, hJson)) as {
      start_s: number;
      end_s: number;
      verdict: string;
    }[];
    expect(w.length).toBe(golden.sun_windows.length);
    w.forEach((x, i) => {
      expect(Math.abs(x.end_s - golden.sun_windows[i]!.end_utc_offset_s)).toBeLessThanOrEqual(1e-6);
      expect(x.verdict).toBe(golden.sun_windows[i]!.verdict);
    });
  });

  it("refusals surface as exceptions, never values", () => {
    expect(() => e.azEl("MARS", "2027-01-01T00:00:00Z", SITE.lat, SITE.lon, 1.5)).toThrow();
    // LDEM_16 covers the whole Moon except within half a pixel of a pole: the cap is the uncovered case
    expect(() => e.horizon(-89.99, 0, 8, 1000, 50, 1.5)).toThrow(/cannot assess|no installed terrain/i);
    expect(e.stackSignature()).toMatch(/^regional@5\.0m > ldem_16@/);
  });
});
