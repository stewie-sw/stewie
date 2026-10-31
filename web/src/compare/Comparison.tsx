import { type Interval, type Scenario, barSpan, comparable, hours } from "./timeline";

const BODIES: { key: "SUN" | "EARTH"; label: string }[] = [
  { key: "SUN", label: "Sun" },
  { key: "EARTH", label: "Earth" },
];
const ROW = 14;

function days(s: number): string {
  return (s / 86_400).toFixed(2);
}

/** Side-by-side scenario cards over one time axis. Shows facts only: it never ranks or recommends. */
export function Comparison({ scenarios, width }: { scenarios: Scenario[]; width: number }) {
  const end = Math.max(...scenarios.flatMap((s) => [...s.windows.SUN, ...s.windows.EARTH].map((w) => w.end_s)));
  const span = { start_s: 0, end_s: end };
  const signatures = [...new Set(scenarios.map((s) => s.stack_signature))];
  return (
    <section aria-label="Scenario comparison">
      {!comparable(scenarios) && (
        <p role="note">Not comparable: these scenarios use different terrain stacks ({signatures.join("; ")}).</p>
      )}
      {scenarios.map((s) => (
        <article key={s.name} aria-label={s.name}>
          <h3>{s.name}</h3>
          <p>
            {s.lat_deg}, {s.lon_deg} · terrain {s.stack_signature}
          </p>
          <table>
            <thead>
              <tr>
                <th>Body</th>
                <th>Lit h</th>
                <th>Shadow h</th>
                <th>Unknown h</th>
              </tr>
            </thead>
            <tbody>
              {BODIES.map((b) => {
                const h = hours(s.windows[b.key]);
                return (
                  <tr key={b.key}>
                    <td>{b.label}</td>
                    <td>{h.Lit.toFixed(1)}</td>
                    <td>{h.Shadow.toFixed(1)}</td>
                    <td>{h.Unknown.toFixed(1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <svg viewBox={`0 0 ${width} ${2 * ROW}`} role="img" aria-label={`${s.name} timeline`}>
            {BODIES.map((b, row) =>
              s.windows[b.key].map((w: Interval, i) => {
                const { x, width: wd } = barSpan(w, span, width);
                return (
                  <rect
                    key={`${b.key}-${i}`}
                    data-verdict={w.verdict}
                    x={x}
                    y={row * ROW}
                    width={wd}
                    height={ROW - 2}
                    aria-label={`${b.label} ${w.verdict} from day ${days(w.start_s)} to day ${days(w.end_s)}`}
                  />
                );
              }),
            )}
          </svg>
        </article>
      ))}
    </section>
  );
}
