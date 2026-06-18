/* STEWIE design system — public surface. Re-exports every component + the icon set, and (in a browser)
 * registers them on window.StewieDS so the IIFE dist/ bundle can be consumed without a module loader
 * (the form /design-sync uploads, and the form the gallery renders). */
export { Button, type ButtonProps } from "./components/Button";
export { ModeBar, MODES, type StewieMode, type ModeSpec, type ModeBarProps } from "./components/ModeBar";
export {
  SourceToggle, SOURCE_LAYERS, truthAvailable, type SourceLayer, type SourceToggleProps,
} from "./components/SourceToggle";
export { WorkAreaTabs, WORK_AREAS, type WorkArea, type WorkAreaTabsProps } from "./components/WorkAreaTabs";
export { Panel, type PanelProps } from "./components/Panel";
export { MetricTile, type MetricStatus, type MetricTileProps } from "./components/MetricTile";
export { SubsystemChip, SUBSYSTEMS, type Subsystem, type SubsystemChipProps } from "./components/SubsystemChip";
export { Icon, ICON_NAMES, type IconName, type IconProps } from "./Icon";

import * as DS from "./index";

declare global {
  interface Window {
    StewieDS?: typeof DS;
  }
}

if (typeof window !== "undefined") {
  window.StewieDS = DS;
}
