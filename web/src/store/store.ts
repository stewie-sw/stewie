// The one store every screen reads: the active mode, the shared UTC clock and the selected sites.
export type Mode = "rover" | "planning" | "field" | "learn";

export interface AppState {
  mode: Mode;
  /** ISO 8601 UTC instant, `YYYY-MM-DDTHH:MM:SSZ`. */
  utc: string;
  selectedSites: string[];
}

export interface AppStore {
  get(): AppState;
  subscribe(listener: () => void): () => void;
  setMode(mode: Mode): void;
  setUtc(utc: string): void;
  toggleSite(name: string): void;
}

const ISO_UTC = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$/;

/** True when `utc` is a real calendar instant in the accepted form (no rollover of 2027-02-30 and the like). */
export function isUtc(utc: string): boolean {
  const m = ISO_UTC.exec(utc);
  if (!m) return false;
  const [y, mo, d, h, mi, s] = m.slice(1).map(Number) as [number, number, number, number, number, number];
  const t = new Date(Date.UTC(y, mo - 1, d, h, mi, s));
  return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d && h < 24 && mi < 60 && s < 60;
}

export function createAppStore(initial: AppState): AppStore {
  let state = initial;
  const listeners = new Set<() => void>();
  const update = (next: AppState) => {
    state = next;
    for (const l of listeners) l();
  };
  return {
    get: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setMode: (mode) => update({ ...state, mode }),
    setUtc(utc) {
      if (!isUtc(utc)) throw new Error(`not a UTC instant: ${utc}`);
      update({ ...state, utc });
    },
    toggleSite(name) {
      const on = state.selectedSites.includes(name);
      update({ ...state, selectedSites: on ? state.selectedSites.filter((s) => s !== name) : [...state.selectedSites, name] });
    },
  };
}
