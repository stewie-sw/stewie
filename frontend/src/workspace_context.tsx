import { createContext, useCallback, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { applyPatch, fromSearchParams, toSearchParams } from "./workspace";
import type { WorkspaceState } from "./workspace";

// [REQ:RF-02] the workspace state lives in the URL query params (the single source of truth), so a shared
// link restores the exact view and a reload restores state. `patch` validates enums (applyPatch throws on an
// unknown value) then writes the routeable subset back to the URL -> state re-derives. React Router owns the
// history entry (replace, so workspace tweaks don't spam the back stack).
interface WorkspaceCtx {
  state: WorkspaceState;
  patch: (p: Partial<WorkspaceState>) => void;
}

const Ctx = createContext<WorkspaceCtx | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => fromSearchParams(searchParams), [searchParams]);
  const patch = useCallback(
    (p: Partial<WorkspaceState>) => {
      const next = applyPatch(state, p); // throws on an unknown enum value (fail-loud on a bad set)
      setSearchParams(toSearchParams(next), { replace: true });
    },
    [state, setSearchParams],
  );
  return <Ctx.Provider value={{ state, patch }}>{children}</Ctx.Provider>;
}

export function useWorkspace(): WorkspaceCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useWorkspace must be used within a WorkspaceProvider");
  return c;
}
