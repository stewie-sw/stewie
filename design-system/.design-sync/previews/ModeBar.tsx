import { ModeBar } from "@stewie/design-system";

// a director sees every mode; SIM-OPERATE is active
export const Director = () => <ModeBar mode="SIM-OPERATE" roleRank={3} />;
// a guest may only select GIS-PLAN — the rest are role-gated (greyed)
export const GuestGated = () => <ModeBar mode="GIS-PLAN" roleRank={0} />;
// OPERATE active: the only mode that commands real hardware
export const OperateLive = () => <ModeBar mode="OPERATE" roleRank={3} />;
