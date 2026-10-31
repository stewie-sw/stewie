import type { SiteCatalog } from "../contracts/site";
import { CRS, fromProjected, toProjected } from "./projection";

export interface Pin {
  name: string;
  label: string;
  xy: [number, number];
}

/** One pin per catalog site, in the map's CRS. */
export function sitePins(catalog: SiteCatalog, crs: string): Pin[] {
  return Object.values(catalog).map((s) => ({ name: s.name, label: s.label, xy: toProjected(crs, [s.lon_deg, s.lat_deg]) }));
}

export interface Identified {
  lat_deg: number;
  lon_deg: number;
  polar_m: [number, number];
  equirect_m: [number, number];
}

/** The clicked map coordinate in every CRS the app shows. */
export function identify(xy: [number, number], crs: string): Identified {
  const [lon_deg, lat_deg] = fromProjected(crs, xy);
  return {
    lat_deg,
    lon_deg,
    polar_m: toProjected(CRS.polarSouth, [lon_deg, lat_deg]),
    equirect_m: toProjected(CRS.equirectangular, [lon_deg, lat_deg]),
  };
}

export interface Crumb {
  lat_deg: number;
  lon_deg: number;
}

/** Append a breadcrumb, keeping the most recent `cap`. */
export function addBreadcrumb(trail: Crumb[], c: Crumb, cap: number): Crumb[] {
  const next = [...trail, c];
  return next.length > cap ? next.slice(next.length - cap) : next;
}
