// [REQ:RF-01] the 13 pane identities, mirrored EXACTLY from the vanilla cockpit's .vtab[data-view] set +
// their data-minrole gates (stewie/server/index.html). The React shell shows the same identities with the
// same role visibility; a role that outranks a pane's minRole sees it. Keep this list in lockstep with the
// vanilla cockpit until each pane is migrated (ADR-0007 strangler-fig).

export type Role = "guest" | "operator" | "director";

// role rank, mirroring the vanilla cockpit's _rrank (guest < operator < director).
export const RANK: Record<Role, number> = { guest: 0, operator: 1, director: 2 };

export interface Pane {
  readonly id: string; // matches the vanilla data-view
  readonly label: string;
  readonly system?: string; // the owning subsystem badge (LODE/DART/LEAP/FORGE), where the vanilla shows one
  readonly minRole: Role; // lowest role that may see the pane
  readonly group: "spine" | "cluster" | "menu";
}

// The six-slot ConOps spine, the operator cluster, and the menu utilities — 13 total, order as in the vanilla.
export const PANES: readonly Pane[] = [
  { id: "plan", label: "Plan", system: "LODE", minRole: "guest", group: "spine" },
  { id: "rehearse", label: "Rehearse", minRole: "director", group: "spine" },
  { id: "validate", label: "Validate", minRole: "guest", group: "spine" },
  { id: "release", label: "Release", minRole: "director", group: "spine" },
  { id: "metrics", label: "Execute", minRole: "guest", group: "spine" },
  { id: "report", label: "Report", system: "FORGE", minRole: "guest", group: "spine" },
  { id: "fleet", label: "Fleet", minRole: "operator", group: "cluster" },
  { id: "construction", label: "Construction", minRole: "operator", group: "cluster" },
  { id: "models", label: "Models", minRole: "operator", group: "cluster" },
  { id: "trainer", label: "Trainer", minRole: "operator", group: "cluster" },
  { id: "settings", label: "Settings", minRole: "guest", group: "menu" },
  { id: "system", label: "System", minRole: "director", group: "menu" },
  { id: "admin", label: "Admin", minRole: "director", group: "menu" },
];

export function visiblePanes(role: Role): readonly Pane[] {
  return PANES.filter((p) => RANK[role] >= RANK[p.minRole]);
}
