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

/** The display-tile index the pipeline writes beside the device package (RW-71c, D-R104). */
export interface DisplayIndex {
  tile_size: number;
  extent: [number, number, number, number];
  origin: [number, number];
  resolutions: number[];
  max_zoom: number;
  source: { crs: string; layer: string };
}

/** Where the device package's display tiles are served (the same origin, so they load offline). */
export const DISPLAY_ROOT = "/data/package/south_polar_sites/display";

/** The tile layer's URL template and grid, or null when the tiles are not in the map's CRS. */
export function displayGrid(index: DisplayIndex, crs: string) {
  if (index.source.crs !== crs) return null;
  return {
    url: `${DISPLAY_ROOT}/{z}/{x}/{y}.png`,
    extent: index.extent,
    origin: index.origin,
    resolutions: index.resolutions,
    tileSize: index.tile_size,
  };
}

/** The tile (z, x, y) and the pixel within it holding a projected point, or null outside the grid. */
export function tileAt(index: DisplayIndex, xy: [number, number], z: number): { tile: [number, number, number]; pixel: [number, number] } | null {
  const res = index.resolutions[z];
  if (res === undefined) return null;
  const px = Math.floor((xy[0] - index.origin[0]) / res);
  const py = Math.floor((index.origin[1] - xy[1]) / res);
  const side = index.tile_size * 2 ** z;
  if (px < 0 || py < 0 || px >= side || py >= side) return null;
  return {
    tile: [z, Math.floor(px / index.tile_size), Math.floor(py / index.tile_size)],
    pixel: [px % index.tile_size, py % index.tile_size],
  };
}
