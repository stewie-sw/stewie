import { Icon, ICON_NAMES } from "@stewie/design-system";

export const AllIcons = () => (
  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", color: "var(--txt)" }}>
    {ICON_NAMES.map((n) => (
      <span key={n} style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 4, width: 56 }}>
        <Icon name={n} size={22} />
        <span style={{ fontSize: 9, color: "var(--dim)" }}>{n}</span>
      </span>
    ))}
  </div>
);
