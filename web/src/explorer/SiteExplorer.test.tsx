// Site Explorer on the real engine (WASM in node, real Haworth tile over LDEM_16): sky plot, panorama,
// timeline and evidence for a catalog site and a day; an uncovered point says cannot assess.
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import bodies from "../../../crates/stewie-contracts/fixtures/bodies.json";
import sites from "../../../crates/stewie-contracts/fixtures/sites.json";
import { directApi } from "../engine/api";
import { Engine, initSync } from "../engine/pkg/stewie_wasm.js";
import { SiteExplorer } from "./SiteExplorer";

const repo = (p: string) => resolve(process.cwd(), "..", p);
initSync({ module: readFileSync(repo("web/src/engine/pkg/stewie_wasm_bg.wasm")) });
const e = new Engine(JSON.stringify(bodies));
e.addTile(1, "haworth_10km_5m", readFileSync(repo("samples/lunar_dem/haworth_10km_5m/metadata.json"), "utf8"), readFileSync(repo("samples/lunar_dem/haworth_10km_5m/heightmap.rf32")));
e.addGlobal(9, "ldem_16", readFileSync(repo(".cache/terrain/ldem_16.lbl"), "utf8"), readFileSync(repo(".cache/terrain/ldem_16.img")));
const api = directApi(e);

describe("SiteExplorer", () => {
  it("shows the sky plot, panorama, 30-day timeline and evidence for a catalog site", async () => {
    const { container } = render(<SiteExplorer api={api} site={sites.haworth} utc="2027-01-01T06:30:00Z" />);
    expect(await screen.findByRole("img", { name: "Sky plot" }, { timeout: 20_000 })).toBeTruthy();
    expect(container.querySelectorAll("svg[aria-label='Sky plot'] circle[data-body='Sun']").length).toBe(24);
    expect(container.querySelectorAll("svg[aria-label='Horizon panorama'] circle[data-body='Earth']").length).toBe(24);
    expect(container.querySelectorAll("rect[data-verdict]").length).toBeGreaterThan(0);
    expect(screen.getByText(/terrain sources: haworth_10km_5m, ldem_16/)).toBeTruthy();
    expect(screen.getByText(/stack regional@5\.0m > ldem_16@/)).toBeTruthy();
    expect(screen.getByText(/\d+ of 720 azimuths complete/)).toBeTruthy();
  }, 30_000);

  it("says cannot assess where no installed terrain covers the site", async () => {
    const cap = { ...sites.haworth, name: "polar_cap", label: "Polar cap", lat_deg: -89.99, lon_deg: 0 };
    render(<SiteExplorer api={api} site={cap} utc="2027-01-01T00:00:00Z" />);
    expect((await screen.findByRole("alert", undefined, { timeout: 20_000 })).textContent).toMatch(/cannot assess/i);
  }, 30_000);
});
