/* STEWIE icon set — replaces the cockpit's emoji glyphs (🔔 ▦ ▸ ⤓ ⦿ …) with a standardized SVG set.
 * One <Icon name=… />, currentColor, 24x24 grid, 1.6 stroke. Add an icon = add a path here, never an emoji. */
import * as React from "react";

export type IconName =
  | "alert" | "view3d" | "chevron" | "download" | "target"
  | "rover" | "layers" | "sun" | "play" | "safe-stop";

const PATHS: Record<IconName, React.ReactNode> = {
  // bell / alert (was 🔔)
  alert: <path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6M10 20a2 2 0 0 0 4 0" />,
  // 3D view (was ▦)
  view3d: <path d="M12 3 21 8v8l-9 5-9-5V8zM3 8l9 5 9-5M12 13v8" />,
  // expand / disclosure (was ▸)
  chevron: <path d="M9 6l6 6-6 6" />,
  // download / export (was ⤓)
  download: <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" />,
  // source / target reticle (was ⦿)
  target: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" /></>,
  // rover (IPEx-ish: body + two drums)
  rover: <><rect x="5" y="9" width="14" height="6" rx="1" /><circle cx="4" cy="17" r="2.5" /><circle cx="20" cy="17" r="2.5" /><path d="M9 9V6h6v3" /></>,
  // map layers
  layers: <path d="M12 3 3 8l9 5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5" />,
  // sun / illumination
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></>,
  // play / execute
  play: <path d="M7 4v16l13-8z" />,
  // safe-stop (SF-01 octagon)
  "safe-stop": <path d="M8 3h8l5 5v8l-5 5H8l-5-5V8zM9 9h6v6H9z" />,
};

export interface IconProps extends React.SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 16, ...rest }: IconProps): JSX.Element {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={rest["aria-label"] ? undefined : true}
      role={rest["aria-label"] ? "img" : undefined}
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}

export const ICON_NAMES = Object.keys(PATHS) as IconName[];
