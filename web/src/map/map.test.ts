// Map logic (no canvas): catalog pins, identify in both projections, breadcrumbs.
import { describe, expect, it } from "vitest";
import sites from "../../../crates/stewie-contracts/fixtures/sites.json";
import { addBreadcrumb, identify, sitePins } from "./mapLogic";
import { CRS, fromProjected, registerLunarProjections } from "./projection";

registerLunarProjections();

describe("map logic", () => {
  it("places one pin per catalog site at its catalog coordinates in the map CRS", () => {
    const pins = sitePins(sites, CRS.polarSouth);
    expect(pins.length).toBe(Object.keys(sites).length);
    for (const p of pins) {
      const s = sites[p.name as keyof typeof sites];
      const [lon, lat] = fromProjected(CRS.polarSouth, p.xy);
      expect(Math.abs(lat - s.lat_deg)).toBeLessThan(1e-9);
      expect(Math.abs(((lon - s.lon_deg + 540) % 360) - 180)).toBeLessThan(1e-9);
    }
  });

  it("identify reports the clicked point in geographic, polar and equirectangular terms", () => {
    const h = sites.haworth;
    const xy = sitePins(sites, CRS.polarSouth).find((p) => p.name === "haworth")!.xy;
    const id = identify(xy, CRS.polarSouth);
    expect(id.lat_deg).toBeCloseTo(h.lat_deg, 9);
    expect(id.polar_m[0]).toBeCloseTo(xy[0], 6);
    const [lon, lat] = fromProjected(CRS.equirectangular, id.equirect_m);
    expect(lat).toBeCloseTo(h.lat_deg, 9);
    expect(lon).toBeCloseTo(h.lon_deg, 9);
  });

  it("breadcrumbs append in order and cap their length", () => {
    let trail: { lat_deg: number; lon_deg: number }[] = [];
    for (let i = 0; i < 205; i++) trail = addBreadcrumb(trail, { lat_deg: -86 - i * 1e-4, lon_deg: -25 }, 200);
    expect(trail.length).toBe(200);
    expect(trail[0]!.lat_deg).toBeCloseTo(-86 - 5e-4, 12);
    expect(trail[199]!.lat_deg).toBeCloseTo(-86 - 204e-4, 12);
  });
});
