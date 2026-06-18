/* SubsystemChip — the STEWIE subsystem tag (the .sysb pattern): DART (decision/autonomy), LODE
 * (operations/dev env), LEAP (localization/estimation), FORGE (physics/terramechanics). */

export type Subsystem = "DART" | "LODE" | "LEAP" | "FORGE";

export const SUBSYSTEMS: Record<Subsystem, string> = {
  DART: "Decision & Autonomy",
  LODE: "Lunar Operations & Development",
  LEAP: "Localization, Estimation & Analysis",
  FORGE: "Physics / Terramechanics / Excavation",
};

export interface SubsystemChipProps {
  name: Subsystem;
}

export function SubsystemChip({ name }: SubsystemChipProps): JSX.Element {
  return (
    <span className="ds-chip" title={SUBSYSTEMS[name]}>
      {name}
    </span>
  );
}
