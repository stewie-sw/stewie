// TS half of the contract tests (D-R22): the real registry fixtures validate against the same JSON Schemas
// the Rust crate generates its types from; malformed copies (labelled synthetic mutations) are rejected.
import Ajv from "ajv";
import { describe, expect, it } from "vitest";
import bodySchema from "../../../crates/stewie-contracts/schema/body.schema.json";
import siteSchema from "../../../crates/stewie-contracts/schema/site.schema.json";
import bodies from "../../../crates/stewie-contracts/fixtures/bodies.json";
import sites from "../../../crates/stewie-contracts/fixtures/sites.json";
import type { SiteCatalog } from "./site";

const ajv = new Ajv({ strict: false });

describe("contracts", () => {
  it("the real site catalog validates and types as SiteCatalog", () => {
    expect(ajv.validate(siteSchema, sites)).toBe(true);
    const cat: SiteCatalog = sites;
    expect(cat["haworth"]?.lat_deg).toBeCloseTo(-86.33);
  });

  it("the real body registry validates", () => {
    expect(ajv.validate(bodySchema, bodies)).toBe(true);
  });

  it("a site with a latitude beyond the pole is rejected", () => {
    const bad = structuredClone(sites) as Record<string, { lat_deg: number }>;
    bad["haworth"]!.lat_deg = -91;
    expect(ajv.validate(siteSchema, bad)).toBe(false);
  });
});
