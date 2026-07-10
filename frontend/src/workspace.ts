// [REQ:RF-02] the cockpit workspace state model. Mirrors the vanilla cockpit_state.js authority tuple (FS-16)
// + the FS-25 route/state vocabulary (product mode, runnable profile, physics backend) as the AUTHORITY_KEYS
// the mission package uses (lode/mission_package.py: body/site/mission/runtime_mode/runnable_profile/
// source_class/vehicle/role/command_namespace). Pure reducer + enum enforcement + URL (de)serialization; the
// Release/Execute mismatch guard is NOT re-implemented here -- it defers to the real backend /rc/eligibility
// verdict (the AuthorityPane binds it directly). Defaults match cockpit_state.js (site=haworth, body=moon).

export type SourceClass = "live" | "sim" | "eval"; // cockpit_state.js SOURCES
export type CommandNamespace = "sandbox" | "live"; // cockpit_state.js MODES (AG-07 namespace)
// FS-25 product modes (the route/state vocabulary the cockpit carries)
export type ProductMode = "GIS-PLAN" | "TRAIN" | "SIM-OPERATE" | "EVALUATE" | "OPERATE";
// FS-25 runnable profiles (desktop_sil + ros2_replay are wired in the backend today; the rest are declared)
export type RunnableProfile =
  | "desktop_sil" | "digital_twin" | "ros2_replay" | "hil_jetson"
  | "sensor_bench" | "rover_bench" | "field_traverse" | "monte_carlo";
// [dispatch-audit R4] ONLY the ids the backend /physics/backends declares selectable_backends -- tier2_numpy
// (the conserved release authority). The PX-03 Chrono oracle is listed in /physics/backends models for
// transparency but is NOT selectable until it conserves mass, so the UI must not advertise it as a backend a
// mission can pick (the old "tier3_chrono" was also the wrong id -- the ledger backend_id is "tier2_chrono").
export type PhysicsBackend = "tier2_numpy"; // PX-02 /physics/backends selectable_backends

export const SOURCE_CLASSES: readonly SourceClass[] = ["live", "sim", "eval"];
export const COMMAND_NAMESPACES: readonly CommandNamespace[] = ["sandbox", "live"];
export const PRODUCT_MODES: readonly ProductMode[] = ["GIS-PLAN", "TRAIN", "SIM-OPERATE", "EVALUATE", "OPERATE"];
export const RUNNABLE_PROFILES: readonly RunnableProfile[] = [
  "desktop_sil", "digital_twin", "ros2_replay", "hil_jetson",
  "sensor_bench", "rover_bench", "field_traverse", "monte_carlo",
];
export const PHYSICS_BACKENDS: readonly PhysicsBackend[] = ["tier2_numpy"];
// BD-03: the selectable bodies (registry keys from stewie_bodies / /physics/compatibility). Moon/Mars/Ceres/
// Earth/BP-1 are gravity-loaded (Bekker regime); Bennu/Phobos are microgravity (refused fail-closed).
export const BODIES: readonly string[] = ["moon", "mars", "ceres", "bennu", "phobos", "earth", "bp1_testbed"];

export interface WorkspaceState {
  mission: string | null;
  site: string;
  body: string;
  vehicle: string | null;
  productMode: ProductMode;
  runnableProfile: RunnableProfile;
  sourceClass: SourceClass;
  physicsBackend: PhysicsBackend;
  commandNamespace: CommandNamespace;
  depthSource: string; // FR-02: the selected perception depth source (a /perception/depth-sources name)
  workArea: string;
  // [REQ:GW-02] the rest of the unified PRD2 workspace context — spatial CRS/frame, selection, and the
  // mission-lifecycle cursor (branch/release/run/time). One routeable context drives every view.
  siteCrs: string;               // site_crs — the site's geographic/body-fixed frame (e.g. MOON_ME)
  localFrame: string;            // local_frame_id — the site-local XY order frame
  fleet: string | null;          // fleet_id
  selectedEntity: string | null; // selected_entity — the inspected feature/asset
  selectedLayers: string[];      // selected_layers — active layer ids (from the LY-01 catalog)
  timeCursor: string | null;     // time_cursor — the mission time cursor
  branch: string | null;         // branch_id — the sim/replay/live branch
  release: string | null;        // release_id
  run: string | null;            // run_id
}

export function defaultWorkspace(): WorkspaceState {
  // matches cockpit_state.js defaultState (site=haworth, body=moon) + the FS-25 planning defaults. `role` is
  // NOT here -- it is session-derived (session.ts useRole), not a routeable workspace field.
  return {
    mission: null, site: "haworth", body: "moon", vehicle: null,
    productMode: "GIS-PLAN", runnableProfile: "desktop_sil", sourceClass: "sim",
    physicsBackend: "tier2_numpy", commandNamespace: "sandbox", depthSource: "stereo_front", workArea: "plan",
    siteCrs: "MOON_ME", localFrame: "site_xy", fleet: null, selectedEntity: null, selectedLayers: [],
    timeCursor: null, branch: null, release: null, run: null,
  };
}

const ENUMS: Partial<Record<keyof WorkspaceState, readonly string[]>> = {
  productMode: PRODUCT_MODES, runnableProfile: RUNNABLE_PROFILES, sourceClass: SOURCE_CLASSES,
  physicsBackend: PHYSICS_BACKENDS, commandNamespace: COMMAND_NAMESPACES,
};

// pure transition (mirrors cockpit_state.js setState): a patch that names an unknown enum value throws.
export function applyPatch(state: WorkspaceState, patch: Partial<WorkspaceState>): WorkspaceState {
  for (const [k, allowed] of Object.entries(ENUMS)) {
    const v = patch[k as keyof WorkspaceState];
    if (v !== undefined && !allowed.includes(v as string)) {
      throw new Error(`unknown ${k} ${String(v)}`);
    }
  }
  return { ...state, ...patch };
}

// the routeable subset <-> URL query params, so a link restores the view + reload restores state (FS-16).
// scalar routeable fields (selectedLayers is an array, handled separately below).
const ROUTEABLE: (keyof WorkspaceState)[] = [
  "mission", "site", "body", "vehicle", "productMode", "runnableProfile",
  "sourceClass", "physicsBackend", "commandNamespace", "depthSource",
  "siteCrs", "localFrame", "fleet", "selectedEntity", "timeCursor", "branch", "release", "run",
];

export function toSearchParams(state: WorkspaceState): URLSearchParams {
  const p = new URLSearchParams();
  const d = defaultWorkspace();
  for (const k of ROUTEABLE) {
    const v = state[k];
    if (v != null && v !== d[k]) p.set(k, String(v)); // only non-default fields (short, stable links)
  }
  if (state.selectedLayers.length) p.set("layers", state.selectedLayers.join(",")); // [REQ:GW-02] array field
  return p;
}

export function fromSearchParams(params: URLSearchParams): WorkspaceState {
  let state = defaultWorkspace();
  const patch: Partial<WorkspaceState> = {};
  for (const k of ROUTEABLE) {
    const v = params.get(k);
    if (v != null) (patch as Record<string, string>)[k] = v;
  }
  const layers = params.get("layers");
  if (layers) patch.selectedLayers = layers.split(",").filter(Boolean); // [REQ:GW-02] array field
  try {
    state = applyPatch(state, patch); // an invalid URL value is ignored (fail-safe to defaults)
  } catch {
    state = defaultWorkspace();
  }
  return state;
}
