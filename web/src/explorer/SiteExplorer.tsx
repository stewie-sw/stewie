import { useEffect, useState } from "react";
import { Comparison } from "../compare/Comparison";
import type { Scenario } from "../compare/timeline";
import type { Site } from "../contracts/site";
import type { EngineApi, EngineHorizon } from "../engine/api";
import { Panorama, type Track } from "../sky/Panorama";
import { SkyPlot } from "../sky/SkyPlot";

const WINDOW_DAYS = 30;

interface Result {
  horizon: EngineHorizon;
  tracks: Track[];
  scenario: Scenario;
}

function dayStart(utc: string): string {
  return `${utc.slice(0, 10)}T00:00:00Z`;
}

function addDays(utc: string, days: number): string {
  return new Date(Date.parse(utc) + days * 86_400_000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** Where and when to evaluate: the sky, the horizon and the coming month of light at one catalog site. */
export function SiteExplorer({ api, site, utc }: { api: EngineApi; site: Site; utc: string }) {
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setResult(null);
    setError(null);
    (async () => {
      const { lat_deg: lat, lon_deg: lon } = site;
      const horizon = await api.horizon(lat, lon);
      const day = dayStart(utc);
      const hours = Array.from({ length: 24 }, (_, i) => addDays(day, i / 24));
      const track = async (body: "SUN" | "EARTH") => Promise.all(hours.map((t) => api.azEl(body, t, lat, lon).then(([az, el]) => ({ az, el }))));
      const end = addDays(day, WINDOW_DAYS);
      const [sun, earth, sunW, earthW, signature] = await Promise.all([
        track("SUN"),
        track("EARTH"),
        api.windows("SUN", lat, lon, day, end, horizon),
        api.windows("EARTH", lat, lon, day, end, horizon),
        api.stackSignature(),
      ]);
      const scenario: Scenario = { name: site.label, site: site.name, lat_deg: lat, lon_deg: lon, sources: horizon.sources, stack_signature: signature, windows: { SUN: sunW, EARTH: earthW } };
      if (live) setResult({ horizon, tracks: [{ body: "Sun", points: sun }, { body: "Earth", points: earth }], scenario });
    })().catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [api, site, utc]);

  if (error) return <p role="alert">{site.label}: cannot assess. {error}</p>;
  if (!result) return <p aria-busy="true">Computing {site.label}…</p>;
  const complete = result.horizon.complete.filter(Boolean).length;
  return (
    <section aria-label={`Site explorer: ${site.label}`}>
      <h2>{site.label}</h2>
      <SkyPlot horizon={result.horizon} tracks={result.tracks} radius={160} />
      <Panorama horizon={result.horizon} tracks={result.tracks} width={720} height={200} />
      <Comparison scenarios={[result.scenario]} width={720} />
      <p>
        terrain sources: {result.horizon.sources.join(", ")} · stack {result.scenario.stack_signature} · {complete} of{" "}
        {result.horizon.complete.length} azimuths complete (incomplete sectors are reported as unknown, never as open sky)
      </p>
    </section>
  );
}
