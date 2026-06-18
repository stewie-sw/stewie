/* AG-01/02 gate: the cockpit renders only for an authenticated identity. On mount it calls /auth/me; while
 * unauthenticated it shows the sign-in screen (email + password -> /auth/login). The role drives every
 * downstream gate (mode selection, command emission) via store.roleRank. */
import { useEffect, useState } from "react";
import { Button, Panel } from "@stewie/design-system";
import { useCockpit } from "./store";

function SignIn() {
  const signIn = useCockpit((s) => s.signIn);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await signIn(email.trim(), password);
    setBusy(false);
    if (!r.ok) setError(r.error || "Sign-in failed");
  };

  const field: React.CSSProperties = {
    background: "var(--field)", border: "1px solid var(--field-bd)", borderRadius: "var(--r-sm)",
    color: "var(--txt)", font: "var(--fs-body) var(--font-body)", padding: "var(--sp-2) var(--sp-3)", width: "100%",
  };
  return (
    <div className="ds-root" style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <form onSubmit={submit} style={{ width: 340 }}>
        <div className="ds-display" style={{ color: "var(--accent)", fontSize: 22, textAlign: "center", marginBottom: "var(--sp-5)" }}>
          STEWIE
        </div>
        <Panel title="Sign in">
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-3)" }}>
            <input style={field} type="email" placeholder="operator email" autoComplete="username"
              value={email} onChange={(e) => setEmail(e.target.value)} aria-label="email" />
            <input style={field} type="password" placeholder="password" autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)} aria-label="password" />
            {error && <div style={{ color: "var(--accent)", fontSize: "var(--fs-sm)" }} role="alert">{error}</div>}
            <Button variant="primary" type="submit" disabled={busy || !email || !password}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
            <div style={{ color: "var(--dim)", fontSize: "var(--fs-cap)", lineHeight: 1.5 }}>
              Invitation-only. Your role (guest / trainee / operator / director) governs what you can do.
            </div>
          </div>
        </Panel>
      </form>
    </div>
  );
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { authChecked, identity, loadMe } = useCockpit();
  useEffect(() => {
    void loadMe();
  }, [loadMe]);

  if (!authChecked) {
    return (
      <div className="ds-root" style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
        <span className="ds-display" style={{ fontSize: 12 }}>STEWIE · loading…</span>
      </div>
    );
  }
  if (!identity) return <SignIn />;
  return <>{children}</>;
}
