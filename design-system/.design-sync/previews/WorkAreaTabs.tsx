import { WorkAreaTabs } from "@stewie/design-system";

export const Default = () => (
  <WorkAreaTabs active="plan" readiness={{ plan: "•", navigation: "•", perception: "!", metrics: "•" }} />
);
export const NavigationActive = () => <WorkAreaTabs active="navigation" />;
