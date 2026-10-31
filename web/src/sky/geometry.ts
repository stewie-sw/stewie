// Pure geometry for the sky plot and the horizon panorama (no DOM, no chart library: D-R37).
export interface Horizon {
  az_deg: number[];
  /** Terrain elevation per azimuth bin; null where no terrain was covered. */
  elev_deg: (number | null)[];
}

export interface TrackPoint {
  az: number;
  el: number;
}

export interface Box {
  width: number;
  height: number;
}

/** Elevation range shown by both views [deg]. */
export const EL_MIN = -30;
export const EL_MAX = 90;

/** Horizon elevation at `az`, linear between bins (the engine's rule); null if either bin is unknown. */
export function horizonAt(h: Horizon, az: number): number | null {
  const n = h.elev_deg.length;
  const k = (((az % 360) + 360) % 360) / (360 / n);
  const k0 = Math.floor(k) % n;
  const a = h.elev_deg[k0];
  const b = h.elev_deg[(k0 + 1) % n];
  if (a == null || b == null) return null;
  const f = k - Math.floor(k);
  return (1 - f) * a + f * b;
}

export type State = "above terrain" | "below terrain" | "horizon unknown";

export function classify(p: TrackPoint, h: Horizon): State {
  const he = horizonAt(h, p.az);
  if (he === null) return "horizon unknown";
  return p.el < he ? "below terrain" : "above terrain";
}

/** Panorama: azimuth left to right, elevation up. */
export function panoramaPoint(az: number, el: number, box: Box): { x: number; y: number } {
  return { x: (az / 360) * box.width, y: ((EL_MAX - el) / (EL_MAX - EL_MIN)) * box.height };
}

/** Sky plot, centred on the zenith, north up, east right: radius grows as elevation falls. */
export function skyPoint(az: number, el: number, radius: number): { x: number; y: number } {
  const r = ((EL_MAX - el) / (EL_MAX - EL_MIN)) * radius;
  const a = (az * Math.PI) / 180;
  return { x: r * Math.sin(a), y: -r * Math.cos(a) };
}

/** SVG path through the known horizon bins, broken wherever a bin is unknown. */
export function horizonPath(h: Horizon, project: (az: number, el: number) => { x: number; y: number }): string {
  let d = "";
  let pen = false;
  h.az_deg.forEach((az, k) => {
    const el = h.elev_deg[k];
    if (el == null) {
      pen = false;
      return;
    }
    const p = project(az, el);
    d += `${pen ? "L" : "M"}${p.x.toFixed(2)},${p.y.toFixed(2)}`;
    pen = true;
  });
  return d;
}

export function label(body: string, p: TrackPoint, h: Horizon): string {
  return `${body} az ${p.az.toFixed(1)}° el ${p.el.toFixed(1)}°: ${classify(p, h)}`;
}
