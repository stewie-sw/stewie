/* WorkAreaTabs — the §11 FS-03 work-area rail (the .vtab pattern). Six areas; each carries an optional
 * readiness dot. Single-select (the active work area). Plan folds fleet in, so it is one area. */

export type WorkArea = "plan" | "navigation" | "perception" | "metrics" | "models" | "reports";

export const WORK_AREAS: { id: WorkArea; label: string }[] = [
  { id: "plan", label: "Plan" },
  { id: "navigation", label: "Navigation" },
  { id: "perception", label: "Perception" },
  { id: "metrics", label: "Metrics" },
  { id: "models", label: "Models" },
  { id: "reports", label: "Reports" },
];

export interface WorkAreaTabsProps {
  active: WorkArea;
  /** optional per-area readiness hint shown as a small dot (e.g. "•" ready, "!" attention) */
  readiness?: Partial<Record<WorkArea, string>>;
  onSelect?: (area: WorkArea) => void;
}

export function WorkAreaTabs({ active, readiness = {}, onSelect }: WorkAreaTabsProps): JSX.Element {
  return (
    <div className="ds-tabs" role="tablist" aria-label="Work areas">
      {WORK_AREAS.map((a) => (
        <button
          key={a.id}
          type="button"
          role="tab"
          aria-selected={a.id === active}
          className="ds-tab"
          onClick={() => onSelect?.(a.id)}
        >
          {a.label}
          {readiness[a.id] && <span className="ds-tab__dot">{readiness[a.id]}</span>}
        </button>
      ))}
    </div>
  );
}
