/* Typed auth client (FS-15 adapter) for the real /auth/* routes. Maps the backend shapes verbatim:
 *   GET  /auth/me     -> {ok, identity, role, has_password}   (401 when unauthenticated)
 *   POST /auth/login  -> {ok, operator, role, must_set_password} | {ok:false, error}
 *   POST /auth/logout -> clears the session cookie
 * Role is the AG-01 ladder guest<trainee<operator<director; roleRank() is the capability order. */

export type Role = "guest" | "trainee" | "operator" | "director";
const LADDER: Role[] = ["guest", "trainee", "operator", "director"];

/** capability rank; an unknown/empty role ranks -1 (below guest) so it can never satisfy a gate. */
export function roleRank(role: string | null | undefined): number {
  return role ? LADDER.indexOf(role as Role) : -1;
}

export interface Identity {
  identity: string;
  role: Role;
  roleRank: number;
  hasPassword: boolean;
}

/** GET /auth/me — returns the signed-in identity, or null when unauthenticated (401). */
export async function fetchMe(): Promise<Identity | null> {
  const r = await fetch("/auth/me", { credentials: "same-origin" });
  if (r.status === 401 || r.status === 403) return null;
  if (!r.ok) throw new Error(`/auth/me ${r.status}`);
  const j = await r.json();
  if (!j || j.ok === false) return null;
  return { identity: j.identity, role: j.role, roleRank: roleRank(j.role), hasPassword: !!j.has_password };
}

export interface LoginResult {
  ok: boolean;
  error?: string;
  mustSetPassword?: boolean;
}

/** POST /auth/login {email,password} — sets the session cookie on success. */
export async function login(email: string, password: string): Promise<LoginResult> {
  const r = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ email, password }),
  });
  const j = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
  return { ok: !!j.ok, error: j.error, mustSetPassword: !!j.must_set_password };
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
}
