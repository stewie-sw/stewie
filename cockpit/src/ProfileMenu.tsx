/* FS-20 chrome IA: System / Settings / Admin live in a profile menu (NOT the work-area tab bar), role-gated
 * — an operator sees only the mission work areas + the entries their role permits. Settings: any signed-in
 * user; System: operator+ (engineering/ops); Admin: director only. Plus sign-out. Phase-1 entries are the
 * gated IA surface; their panels land in Phase 2. */
import { useState } from "react";
import { Icon } from "@stewie/design-system";
import { useCockpit, type ChromeView } from "./store";

interface ChromeItem {
  id: string;
  label: string;
  minRank: number; // 0 guest, 2 operator, 3 director
}
const ITEMS: ChromeItem[] = [
  { id: "settings", label: "Settings", minRank: 0 },
  { id: "system", label: "System", minRank: 2 },
  { id: "admin", label: "Admin", minRank: 3 },
];

export function ProfileMenu() {
  const { identity, roleRank, signOut, openChrome } = useCockpit();
  const [open, setOpen] = useState(false);
  if (!identity) return null;

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        aria-label="Profile menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        style={{ display: "inline-flex", alignItems: "center", gap: "var(--sp-2)", background: "none",
          border: "1px solid var(--line)", borderRadius: "var(--r-sm)", color: "var(--muted)",
          padding: "var(--sp-1) var(--sp-3)", cursor: "pointer", font: "var(--fs-sm) var(--font-body)" }}
      >
        <span style={{ color: "var(--txt)" }}>{identity.identity}</span>
        <span style={{ color: "var(--dim)", fontSize: "var(--fs-cap)", textTransform: "uppercase" }}>{identity.role}</span>
        <Icon name="chevron" size={12} style={{ transform: open ? "rotate(90deg)" : "none" }} />
      </button>
      {open && (
        <div role="menu" style={{ position: "absolute", right: 0, top: "calc(100% + 4px)", zIndex: 100,
          minWidth: 180, background: "var(--panel)", border: "1px solid var(--line)", borderRadius: "var(--r-md)",
          boxShadow: "var(--shadow-modal)", padding: "var(--sp-1)" }}>
          {ITEMS.filter((it) => roleRank >= it.minRank).map((it) => (
            <button key={it.id} role="menuitem" data-chrome={it.id} type="button"
              style={menuItemStyle} onClick={() => { setOpen(false); openChrome(it.id as ChromeView); }}>
              {it.label}
            </button>
          ))}
          <div style={{ height: 1, background: "var(--line)", margin: "var(--sp-1) 0" }} />
          <button role="menuitem" type="button" style={menuItemStyle}
            onClick={() => { setOpen(false); void signOut(); }}>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

const menuItemStyle: React.CSSProperties = {
  display: "block", width: "100%", textAlign: "left", background: "none", border: "none",
  color: "var(--txt)", font: "var(--fs-sm) var(--font-body)", padding: "var(--sp-2) var(--sp-3)",
  borderRadius: "var(--r-sm)", cursor: "pointer",
};
