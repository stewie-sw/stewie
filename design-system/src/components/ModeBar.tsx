/* ModeBar — the PRD §5 mode selector: the truth boundary the whole cockpit operates under. Always
 * labelled (§5: "simulated truth must never be presented as a live measurement"). EVALUATE/OPERATE are
 * role-gated; OPERATE is the only mode that reaches real hardware (rendered with a warning halo). */

export type StewieMode = "GIS-PLAN" | "TRAIN" | "SIM-OPERATE" | "EVALUATE" | "OPERATE";

export interface ModeSpec {
  id: StewieMode;
  /** the §5 truth boundary, one line */
  truth: string;
  /** minimum role rank to select it (AG-01 ladder: 0 guest..3 director) */
  minRank: number;
  /** OPERATE alone commands real hardware */
  realHardware?: boolean;
}

export const MODES: ModeSpec[] = [
  { id: "GIS-PLAN", truth: "model forecast over validated data", minRank: 0 },
  { id: "TRAIN", truth: "operator path is truth-isolated", minRank: 2 },
  { id: "SIM-OPERATE", truth: "simulation only — no truth fields on the wire", minRank: 2 },
  { id: "EVALUATE", truth: "the only mode with truth access", minRank: 3 },
  { id: "OPERATE", truth: "real telemetry + real commands (gated)", minRank: 2, realHardware: true },
];

export interface ModeBarProps {
  mode: StewieMode;
  /** the operator's AG-01 role rank (0 guest, 1 trainee, 2 operator, 3 director) */
  roleRank?: number;
  onChange?: (mode: StewieMode) => void;
}

export function ModeBar({ mode, roleRank = 0, onChange }: ModeBarProps): JSX.Element {
  return (
    <div className="ds-modebar" role="group" aria-label="Operating mode (truth boundary)">
      {MODES.map((m) => {
        const allowed = roleRank >= m.minRank;
        const active = m.id === mode;
        return (
          <button
            key={m.id}
            type="button"
            className="ds-modebar__opt"
            aria-pressed={active}
            disabled={!allowed}
            data-operate={m.realHardware ? "true" : undefined}
            title={`${m.id}: ${m.truth}${allowed ? "" : " (requires a higher role)"}`}
            onClick={() => allowed && onChange?.(m.id)}
          >
            {m.id}
          </button>
        );
      })}
    </div>
  );
}
