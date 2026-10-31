// Pure helpers for comparing scenarios over a shared time axis (navigator Scenario Comparison rules).
export type Verdict = "Lit" | "Shadow" | "Unknown";

export interface Interval {
  /** Seconds from the comparison start (TDB offset; every scenario shares the same start instant). */
  start_s: number;
  end_s: number;
  verdict: Verdict;
}

export interface Scenario {
  name: string;
  site: string;
  lat_deg: number;
  lon_deg: number;
  sources: string[];
  stack_signature: string;
  windows: { SUN: Interval[]; EARTH: Interval[] };
}

export function barSpan(w: Interval, span: { start_s: number; end_s: number }, width: number): { x: number; width: number } {
  const scale = width / (span.end_s - span.start_s);
  return { x: (w.start_s - span.start_s) * scale, width: (w.end_s - w.start_s) * scale };
}

export function hours(ws: Interval[]): Record<Verdict, number> {
  const h: Record<Verdict, number> = { Lit: 0, Shadow: 0, Unknown: 0 };
  for (const w of ws) h[w.verdict] += (w.end_s - w.start_s) / 3600;
  return h;
}

/** Comparable only when every scenario uses the same terrain-stack shape. */
export function comparable(scenarios: Scenario[]): boolean {
  return new Set(scenarios.map((s) => s.stack_signature)).size <= 1;
}
