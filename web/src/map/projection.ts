// Lunar CRSs for the browser map (proj4 + OpenLayers). The sphere radius comes from the body registry,
// the same single source the Rust engine uses; nothing here is a literal radius.
import { register } from "ol/proj/proj4";
import proj4 from "proj4";
import bodies from "../../../crates/stewie-contracts/fixtures/bodies.json";

const R = bodies.moon.ellipsoid_radius_m;

/** IAU 2015 Moon CRS codes (sphere R = registry radius). */
export const CRS = {
  geographic: "IAU_2015:30100",
  equirectangular: "IAU_2015:30110",
  polarSouth: "IAU_2015:30135",
} as const;

const DEFS: Record<string, string> = {
  [CRS.geographic]: `+proj=longlat +R=${R} +no_defs +type=crs`,
  [CRS.equirectangular]: `+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=${R} +units=m +no_defs +type=crs`,
  [CRS.polarSouth]: `+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +R=${R} +units=m +no_defs +type=crs`,
};

/** Register the lunar CRSs with proj4 and OpenLayers (idempotent). */
export function registerLunarProjections(): void {
  for (const [code, def] of Object.entries(DEFS)) proj4.defs(code, def);
  register(proj4);
}

/** [lon, lat] in degrees to the projected CRS. */
export function toProjected(code: string, lonLat: [number, number]): [number, number] {
  return proj4(CRS.geographic, code, lonLat) as [number, number];
}

/** Projected coordinates back to [lon, lat] in degrees. */
export function fromProjected(code: string, xy: [number, number]): [number, number] {
  return proj4(code, CRS.geographic, xy) as [number, number];
}
