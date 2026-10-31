import { type Horizon, type TrackPoint, classify, horizonPath, label, panoramaPoint } from "./geometry";

export interface Track {
  body: string;
  points: TrackPoint[];
}

/** First-person horizon panorama: terrain line plus body tracks, every marker labelled in text. */
export function Panorama({ horizon, tracks, width, height }: { horizon: Horizon; tracks: Track[]; width: number; height: number }) {
  const box = { width, height };
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Horizon panorama">
      <path data-role="horizon" d={horizonPath(horizon, (az, el) => panoramaPoint(az, el, box))} fill="none" stroke="currentColor" />
      {tracks.map((t) =>
        t.points.map((p, i) => {
          const { x, y } = panoramaPoint(p.az, p.el, box);
          return <circle key={`${t.body}-${i}`} data-body={t.body} data-state={classify(p, horizon)} cx={x} cy={y} r={3} aria-label={label(t.body, p, horizon)} />;
        }),
      )}
    </svg>
  );
}
