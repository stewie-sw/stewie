import type { Track } from "./Panorama";
import { type Horizon, classify, horizonPath, label, skyPoint } from "./geometry";

/** Polar sky plot centred on the zenith: horizon polygon plus body tracks, every marker labelled in text. */
export function SkyPlot({ horizon, tracks, radius }: { horizon: Horizon; tracks: Track[]; radius: number }) {
  return (
    <svg viewBox={`${-radius} ${-radius} ${2 * radius} ${2 * radius}`} role="img" aria-label="Sky plot">
      <path data-role="horizon" d={horizonPath(horizon, (az, el) => skyPoint(az, el, radius))} fill="none" stroke="currentColor" />
      {tracks.map((t) =>
        t.points.map((p, i) => {
          const { x, y } = skyPoint(p.az, p.el, radius);
          return <circle key={`${t.body}-${i}`} data-body={t.body} data-state={classify(p, horizon)} cx={x} cy={y} r={3} aria-label={label(t.body, p, horizon)} />;
        }),
      )}
    </svg>
  );
}
