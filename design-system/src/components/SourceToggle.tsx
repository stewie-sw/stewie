/* SourceToggle — the PO-10 provenance layers that stack on the map canvas: forecast (PlanResult),
 * truth (conserved WorldState), belief (BeliefState/TwinStore), live (RuntimePacket telemetry). Layers
 * are independently toggled (they stack). INVARIANT: the `truth` layer is disabled whenever the active
 * mode has no truth channel (OPERATE on real hardware) — belief can never masquerade as truth. */
import type { StewieMode } from "./ModeBar";

export type SourceLayer = "forecast" | "truth" | "belief" | "live";

export const SOURCE_LAYERS: { id: SourceLayer; label: string }[] = [
  { id: "forecast", label: "Forecast" },
  { id: "truth", label: "Truth" },
  { id: "belief", label: "Belief" },
  { id: "live", label: "Live" },
];

/** modes that expose a ground-truth channel (SIM/EVALUATE). OPERATE/real hardware does NOT. */
export function truthAvailable(mode: StewieMode): boolean {
  return mode === "SIM-OPERATE" || mode === "EVALUATE";
}

export interface SourceToggleProps {
  active: SourceLayer[];
  mode: StewieMode;
  onToggle?: (layer: SourceLayer, on: boolean) => void;
}

export function SourceToggle({ active, mode, onToggle }: SourceToggleProps): JSX.Element {
  const truthOk = truthAvailable(mode);
  return (
    <div className="ds-source" role="group" aria-label="Source layers">
      {SOURCE_LAYERS.map((s) => {
        const disabled = s.id === "truth" && !truthOk;
        const on = active.includes(s.id) && !disabled;
        return (
          <button
            key={s.id}
            type="button"
            className="ds-source__opt"
            data-src={s.id}
            aria-pressed={on}
            disabled={disabled}
            title={disabled ? "No truth channel on real hardware (OPERATE)" : s.label}
            onClick={() => !disabled && onToggle?.(s.id, !on)}
          >
            <span className="ds-source__swatch" />
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
