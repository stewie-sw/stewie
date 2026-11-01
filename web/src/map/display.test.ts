// RW-71c: the display tiles' grid in the browser against the generator's own placement of every catalog site (the
// fixture is written by `cargo run -p xtask -- display-tiles` from the REAL 240 m south polar tier).
import fixture from "../fixtures/display_grid.json";
import { type DisplayIndex, displayGrid, tileAt } from "./mapLogic";
import { CRS, registerLunarProjections, toProjected } from "./projection";

registerLunarProjections();
const index = fixture.grid as unknown as DisplayIndex;

describe("display tiles", () => {
  it("serve from the device package in the polar CRS, and refuse another CRS", () => {
    const g = displayGrid(index, CRS.polarSouth);
    expect(g?.url).toBe("/data/package/south_polar_sites/display/{z}/{x}/{y}.png");
    expect(g?.resolutions).toEqual(index.resolutions);
    expect(displayGrid(index, CRS.equirectangular)).toBeNull();
  });

  it("place every catalog site on the generator's tile and pixel (proj4 agrees with the engine's projection)", () => {
    expect(fixture.sites.length).toBeGreaterThanOrEqual(10);
    for (const s of fixture.sites) {
      const xy = toProjected(CRS.polarSouth, [s.lon_deg, s.lat_deg]);
      const [e, n] = s.xy as [number, number];
      expect(Math.abs(xy[0] - e)).toBeLessThan(1e-6);
      expect(Math.abs(xy[1] - n)).toBeLessThan(1e-6);
      expect(tileAt(index, xy, index.max_zoom)).toEqual({ tile: s.tile, pixel: s.pixel });
    }
  });

  it("has no tile outside the grid", () => {
    expect(tileAt(index, [index.extent[2] + 1, 0], index.max_zoom)).toBeNull();
    expect(tileAt(index, [0, 0], index.max_zoom + 1)).toBeNull();
  });
});
