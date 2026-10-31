// Sky plot and horizon panorama against real engine output: the committed R10 golden scenario
// (crates/stewie-wasm/golden/scenario.json: the stacked Haworth horizon and the hourly Sun/Earth track).
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import golden from "../../../crates/stewie-wasm/golden/scenario.json";
import { Panorama } from "./Panorama";
import { SkyPlot } from "./SkyPlot";
import { type Horizon, classify, horizonAt, panoramaPoint, skyPoint } from "./geometry";

const n = golden.horizon_elev_deg.length;
const horizon: Horizon = { az_deg: golden.horizon_elev_deg.map((_, k) => (360 * k) / n), elev_deg: golden.horizon_elev_deg };
const sun = golden.sun_az_el.map(([az, el]) => ({ az: az!, el: el! }));
const earth = golden.earth_az_el.map(([az, el]) => ({ az: az!, el: el! }));
const BOX = { width: 720, height: 240 };

describe("sky geometry", () => {
  it("interpolates the horizon linearly between azimuth bins, wrapping at 360", () => {
    const e0 = horizon.elev_deg[0]!;
    const e1 = horizon.elev_deg[1]!;
    expect(horizonAt(horizon, 0.25)).toBeCloseTo(0.5 * (e0 + e1), 12);
    expect(horizonAt(horizon, 359.75)).toBeCloseTo(0.5 * (horizon.elev_deg[n - 1]! + e0), 12);
  });

  // On 2027-01-01 at Haworth the real Sun stays above the terrain and the real Earth stays below it, so
  // the two tracks together exercise both branches; the counts guard against a vacuous pass.
  it("draws a body below the terrain line exactly when it is below the horizon", () => {
    let below = 0;
    let above = 0;
    for (const p of [...sun, ...earth]) {
      const h = horizonAt(horizon, p.az);
      if (h === null) continue;
      const bodyY = panoramaPoint(p.az, p.el, BOX).y;
      const terrainY = panoramaPoint(p.az, h, BOX).y;
      if (p.el < h) {
        below += 1;
        expect(bodyY).toBeGreaterThan(terrainY);
        expect(classify(p, horizon)).toBe("below terrain");
      } else {
        above += 1;
        expect(bodyY).toBeLessThanOrEqual(terrainY);
        expect(classify(p, horizon)).toBe("above terrain");
      }
    }
    expect(below).toBeGreaterThan(0);
    expect(above).toBeGreaterThan(0);
  });

  it("puts the zenith at the centre and east to the right of north on the sky plot", () => {
    const c = skyPoint(0, 90, 100);
    expect(c.x).toBeCloseTo(0, 9);
    expect(c.y).toBeCloseTo(0, 9);
    const north = skyPoint(0, 0, 100);
    const east = skyPoint(90, 0, 100);
    expect(north.y).toBeLessThan(0);
    expect(east.x).toBeGreaterThan(0);
  });
});

describe("rendered views", () => {
  it("labels every Sun marker in text, not colour alone (R9)", () => {
    const { container } = render(<Panorama horizon={horizon} tracks={[{ body: "Sun", points: sun }]} width={720} height={240} />);
    const marks = container.querySelectorAll("circle[data-body='Sun']");
    expect(marks.length).toBe(sun.length);
    for (const m of marks) expect(m.getAttribute("aria-label")).toMatch(/Sun .* (above|below) terrain|Sun .* horizon unknown/);
  });

  it("the sky plot draws the horizon polygon and the track", () => {
    const { container } = render(<SkyPlot horizon={horizon} tracks={[{ body: "Sun", points: sun }]} radius={150} />);
    expect(container.querySelector("path[data-role='horizon']")).not.toBeNull();
    expect(container.querySelectorAll("circle[data-body='Sun']").length).toBe(sun.length);
  });
});
