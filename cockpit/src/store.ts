/* The one routeable cockpit state (FS-16): the signed-in identity + role (AG-01), the truth-boundary mode,
 * the active source layers, and the work area. Zustand — the single store the panes subscribe to. Encodes
 * the sim-vs-truth invariant: leaving a truth-bearing mode drops the truth layer. roleRank is DERIVED from
 * the authenticated role (never hardcoded) and drives mode/command gating. */
import { create } from "zustand";
import { truthAvailable, type StewieMode, type SourceLayer, type WorkArea } from "@stewie/design-system";
import { fetchMe, login as apiLogin, logout as apiLogout, type Identity } from "./auth";

export interface CockpitState {
  // --- auth (AG-01/02) ---
  identity: Identity | null;
  authChecked: boolean; // false until the first /auth/me resolves
  roleRank: number; // identity ? rank : -1 (below guest -> no command)
  loadMe: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  signOut: () => Promise<void>;
  // --- view state (FS-16) ---
  mode: StewieMode;
  sources: SourceLayer[];
  workArea: WorkArea;
  setMode: (m: StewieMode) => void;
  toggleSource: (l: SourceLayer, on: boolean) => void;
  setWorkArea: (a: WorkArea) => void;
  // --- Plan authoring: click-placed build orders in the order frame (x,y metres), typed cut|fill ---
  orders: { x: number; y: number; kind: "cut" | "fill" }[];
  placeMode: "cut" | "fill";
  setPlaceMode: (m: "cut" | "fill") => void;
  addOrder: (x: number, y: number) => void;
  clearOrders: () => void;
  // --- chrome (FS-20) + prefs (UI-1/UI-2), persisted ---
  chrome: ChromeView | null;
  theme: "dark" | "light";
  fontPx: number;
  openChrome: (c: ChromeView) => void;
  closeChrome: () => void;
  setTheme: (t: "dark" | "light") => void;
  setFontPx: (px: number) => void;
}

export type ChromeView = "settings" | "system" | "admin";

const lsGet = (k: string, d: string): string => {
  try {
    return localStorage.getItem(k) ?? d;
  } catch {
    return d;
  }
};
const lsSet = (k: string, v: string) => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* ignore */
  }
};

export const useCockpit = create<CockpitState>((set) => ({
  identity: null,
  authChecked: false,
  roleRank: -1,
  loadMe: async () => {
    const id = await fetchMe().catch(() => null);
    set({ identity: id, roleRank: id ? id.roleRank : -1, authChecked: true });
  },
  signIn: async (email, password) => {
    const r = await apiLogin(email, password);
    if (r.ok) {
      const id = await fetchMe().catch(() => null);
      set({ identity: id, roleRank: id ? id.roleRank : -1, authChecked: true });
    }
    return { ok: r.ok, error: r.error };
  },
  signOut: async () => {
    await apiLogout();
    set({ identity: null, roleRank: -1 });
  },

  mode: "SIM-OPERATE",
  sources: ["forecast", "truth", "belief"],
  workArea: "plan",
  setMode: (mode) =>
    set((s) => ({
      mode,
      // INVARIANT: no truth channel on real hardware -> drop the truth layer when leaving SIM/EVALUATE
      sources: truthAvailable(mode) ? s.sources : s.sources.filter((x) => x !== "truth"),
    })),
  toggleSource: (l, on) =>
    set((s) => ({ sources: on ? [...new Set([...s.sources, l])] : s.sources.filter((x) => x !== l) })),
  setWorkArea: (workArea) => set({ workArea }),

  orders: [],
  placeMode: "fill",
  setPlaceMode: (placeMode) => set({ placeMode }),
  addOrder: (x, y) => set((s) => ({ orders: [...s.orders, { x, y, kind: s.placeMode }] })),
  clearOrders: () => set({ orders: [] }),

  chrome: null,
  theme: lsGet("stewie_theme", "dark") === "light" ? "light" : "dark",
  fontPx: Number(lsGet("stewie_fontpx", "13")) || 13,
  openChrome: (chrome) => set({ chrome }),
  closeChrome: () => set({ chrome: null }),
  setTheme: (theme) => {
    lsSet("stewie_theme", theme);
    set({ theme });
  },
  setFontPx: (fontPx) => {
    lsSet("stewie_fontpx", String(fontPx));
    set({ fontPx });
  },
}));
