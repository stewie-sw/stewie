// Browser projections against the pyproj oracle: the 160 real DEM cell centres in stewie-oracle
// `dem_samples` (IAU_2015:30135, georeferenced from each bundle's metadata), and round trips.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import oracle from "../../../crates/stewie-oracle/fixtures/dem_samples.payload.json";
import { CRS, fromProjected, registerLunarProjections, toProjected } from "./projection";

registerLunarProjections();

const cells = oracle.bundles.flatMap((b) => {
  const meta = JSON.parse(readFileSync(resolve(process.cwd(), `../samples/lunar_dem/${b.bundle}/metadata.json`), "utf8"));
  const { x0, y1 } = meta.world_bounds_m;
  return b.cells.map((c) => ({
    e: x0 + b.cell_m * (c.col + 0.5),
    n: y1 - b.cell_m * (c.row + 0.5),
    lat: c.lat_deg,
    lon: c.lon_deg,
  }));
});
const dlon = (a: number, b: number) => Math.abs(((a - b + 540) % 360) - 180);

describe("lunar projections", () => {
  it("polar stereographic inverse matches pyproj on every real cell", () => {
    expect(cells.length).toBe(160);
    for (const c of cells) {
      const [lon, lat] = fromProjected(CRS.polarSouth, [c.e, c.n]);
      expect(Math.abs(lat - c.lat)).toBeLessThan(1e-9);
      expect(dlon(lon, c.lon)).toBeLessThan(1e-9);
    }
  });

  it("polar stereographic forward matches within a millimetre", () => {
    for (const c of cells) {
      const [e, n] = toProjected(CRS.polarSouth, [c.lon, c.lat]);
      expect(Math.abs(e - c.e)).toBeLessThan(1e-3);
      expect(Math.abs(n - c.n)).toBeLessThan(1e-3);
    }
  });

  it("a point clicked in either projection maps back to the same lon/lat", () => {
    for (const c of cells) {
      const eq = toProjected(CRS.equirectangular, [c.lon, c.lat]);
      const [lon, lat] = fromProjected(CRS.equirectangular, eq);
      expect(Math.abs(lat - c.lat)).toBeLessThan(1e-9);
      expect(dlon(lon, c.lon)).toBeLessThan(1e-9);
    }
  });
});
