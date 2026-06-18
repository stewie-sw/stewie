/* The Perception work area: surfaces GET /evidence — the localization-approach comparison (ARGUS vs the
 * Stanford NAV Lab / ShadowNav baselines): the photometric+depth modality precision + each approach's
 * accuracy/precision metrics. The LIVE stereo/depth render (camera -> depth -> point cloud) is the gated
 * tier (the render pipeline); this is the evidence/comparison surface, which is bindable now. */
import { useEffect, useState } from "react";
import { MetricTile, Panel } from "@stewie/design-system";
import { fetchEvidence, type Evidence } from "../api";

type State = "loading" | "ok" | "error";

function num(v: unknown): string {
  return typeof v === "number" ? (Math.abs(v) >= 100 || Number.isInteger(v) ? String(v) : v.toFixed(3)) : String(v);
}

export function PerceptionView() {
  const [state, setState] = useState<State>("loading");
  const [e, setE] = useState<Evidence | null>(null);
  useEffect(() => {
    let live = true;
    fetchEvidence()
      .then((ev) => {
        if (!live) return;
        setE(ev);
        setState(ev ? "ok" : "error");
      })
      .catch(() => live && setState("error"));
    return () => {
      live = false;
    };
  }, []);

  const ms = e?.modalitySigma || {};
  return (
    <div style={{ flex: 1, minWidth: 0, overflow: "auto", padding: "var(--sp-5)", background: "var(--bg)" }}>
      <Panel title="Modality precision (photometric + depth)">
        {state === "loading" && <Note>Loading /evidence…</Note>}
        {state === "error" && <Note>Could not load /evidence.</Note>}
        {state === "ok" && (
          <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap" }}>
            {"range_m" in ms && <MetricTile label="Range" value={num(ms.range_m)} unit="m" />}
            {"stereo_sigma_m" in ms && <MetricTile label="Stereo σ" value={num(ms.stereo_sigma_m)} unit="m" />}
            {"articulation_parallax_sigma_m" in ms && <MetricTile label="Parallax σ" value={num(ms.articulation_parallax_sigma_m)} unit="m" status="ok" />}
            {"articulation_advantage_x" in ms && <MetricTile label="Articulation gain" value={num(ms.articulation_advantage_x)} unit="×" status="ok" />}
          </div>
        )}
      </Panel>

      {state === "ok" && e && (
        <div style={{ marginTop: "var(--sp-4)", display: "flex", gap: "var(--sp-4)", flexWrap: "wrap" }}>
          {Object.entries(e.accuracy).map(([approach, metrics]) => (
            <div key={approach} style={{ flex: "1 1 280px", minWidth: 240 }}>
              <Panel title={approach} subsystem={approach === "ARGUS" ? "LEAP" : undefined}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--fs-sm)", color: "var(--txt)" }}>
                  <tbody>
                    {Object.entries(metrics as Record<string, unknown>).map(([k, v]) => (
                      <tr key={k}>
                        <td style={{ padding: "2px 0", color: "var(--muted)" }}>{k}</td>
                        <td style={{ padding: "2px 0", textAlign: "right", color: "var(--txt)", fontFamily: "var(--font-display)" }}>{num(v)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          ))}
        </div>
      )}

      {e?.note && <Note>{e.note}</Note>}
      <Note>Live stereo → depth → point-cloud render (camera-frame perception) is the gated tier — it binds with the render pipeline (PM-13..16).</Note>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <div style={{ color: "var(--dim)", fontSize: "var(--fs-sm)", lineHeight: 1.6, marginTop: "var(--sp-3)" }}>{children}</div>;
}
