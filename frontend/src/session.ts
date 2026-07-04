import { useEffect, useState } from "react";

import type { Role } from "./panes";

// The current operator role, from the backend session (GET /auth/whoami). Unauthenticated -> "guest".
// Role drives pane visibility (panes.ts); it is fetched once on mount and fail-closed to guest on any error.
export function useRole(): Role {
  const [role, setRole] = useState<Role>("guest");
  useEffect(() => {
    let live = true;
    fetch("/auth/me", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : { role: "guest" }))
      .then((d) => { if (live) setRole((d.role ?? "guest") as Role); })
      .catch(() => { if (live) setRole("guest"); });
    return () => { live = false; };
  }, []);
  return role;
}
