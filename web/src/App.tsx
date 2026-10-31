import { useState, useSyncExternalStore } from "react";
import sites from "../../crates/stewie-contracts/fixtures/sites.json";
import type { SiteCatalog } from "./contracts/site";
import { MapView } from "./map/MapView";
import { type AppStore, type Mode, isUtc } from "./store/store";

const MODES: { id: Mode; label: string }[] = [
  { id: "rover", label: "Rover Ops" },
  { id: "planning", label: "Planning" },
  { id: "field", label: "Field" },
  { id: "learn", label: "Learn" },
];

const CATALOG: SiteCatalog = sites;

export function App({ store }: { store: AppStore }) {
  const state = useSyncExternalStore(store.subscribe, store.get);
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? state.utc;
  return (
    <div className="shell">
      <header>
        <div role="tablist" aria-label="Mode">
          {MODES.map((m) => (
            <button key={m.id} role="tab" aria-selected={state.mode === m.id} onClick={() => store.setMode(m.id)}>
              {m.label}
            </button>
          ))}
        </div>
        <label>
          UTC
          <input
            aria-label="UTC"
            value={shown}
            aria-invalid={!isUtc(shown)}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => {
              if (draft !== null && isUtc(draft)) store.setUtc(draft);
              setDraft(null);
            }}
          />
        </label>
      </header>
      {(state.mode === "planning" || state.mode === "field") && <MapView catalog={CATALOG} />}
      <section aria-label="Sites">
        <h2>Sites</h2>
        <ul>
          {Object.values(CATALOG).map((s) => (
            <li key={s.name}>
              <label>
                <input type="checkbox" checked={state.selectedSites.includes(s.name)} onChange={() => store.toggleSite(s.name)} />
                {s.label}
              </label>{" "}
              <span>
                {s.lat_deg}, {s.lon_deg}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
