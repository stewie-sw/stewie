import { SourceToggle } from "@stewie/design-system";

// in SIM-OPERATE the truth layer is available and can stack with forecast + belief
export const SimWithTruth = () => (
  <SourceToggle mode="SIM-OPERATE" active={["forecast", "truth", "belief"]} />
);
// in OPERATE (real hardware) the truth layer is DISABLED — belief can never masquerade as truth
export const OperateNoTruth = () => (
  <SourceToggle mode="OPERATE" active={["forecast", "belief", "live"]} />
);
