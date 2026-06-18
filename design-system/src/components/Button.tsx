/* Button — the primary STEWIE control. variant: primary | ghost | danger; size: sm | md. Optional icon. */
import * as React from "react";
import { Icon, type IconName } from "../Icon";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: IconName;
}

export function Button({
  variant = "ghost", size = "md", icon, children, className = "", ...rest
}: ButtonProps): JSX.Element {
  const cls = [
    "ds-btn",
    variant === "primary" && "ds-btn--primary",
    variant === "danger" && "ds-btn--danger",
    variant === "ghost" && "ds-btn--ghost",
    size === "sm" && "ds-btn--sm",
    className,
  ].filter(Boolean).join(" ");
  return (
    <button type="button" className={cls} {...rest}>
      {icon && <Icon name={icon} size={size === "sm" ? 13 : 15} />}
      {children}
    </button>
  );
}
