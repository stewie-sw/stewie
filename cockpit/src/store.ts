/* The one routeable cockpit state (FS-16): mode (truth boundary), the active source layers, the work
 * area, and the operator role. Zustand — the single store the panes subscribe to. Encodes the sim-vs-truth
 * invariant: leaving a truth-bearing mode drops the truth layer (it can never linger on real hardware). */
import { create } from "zustand";
import { truthAvailable, type StewieMode, type SourceLayer, type WorkArea } from "@stewie/design-system";

export interface CockpitState {
  mode: StewieMode;
  sources: SourceLayer[];
  workArea: WorkArea;
  roleRank: number; // AG-01 ladder: 0 guest, 1 trainee, 2 operator, 3 director
  setMode: (m: StewieMode) => void;
  toggleSource: (l: SourceLayer, on: boolean) => void;
  setWorkArea: (a: WorkArea) => void;
}

export const useCockpit = create<CockpitState>((set) => ({
  mode: "SIM-OPERATE",
  sources: ["forecast", "truth", "belief"],
  workArea: "plan",
  roleRank: 3,
  setMode: (mode) =>
    set((s) => ({
      mode,
      // INVARIANT: no truth channel on real hardware -> drop the truth layer when leaving SIM/EVALUATE
      sources: truthAvailable(mode) ? s.sources : s.sources.filter((x) => x !== "truth"),
    })),
  toggleSource: (l, on) =>
    set((s) => ({ sources: on ? [...new Set([...s.sources, l])] : s.sources.filter((x) => x !== l) })),
  setWorkArea: (workArea) => set({ workArea }),
}));
