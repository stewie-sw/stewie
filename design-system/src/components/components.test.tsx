/* Unit tests for the STEWIE design-system components. The load-bearing ones assert the SAFETY invariants
 * the design encodes: §5 mode role-gating, and the PO-10 rule that the truth layer is unavailable on real
 * hardware (OPERATE). The rest assert variant/state wiring. RTL + jsdom; no jest-dom matchers needed. */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { ModeBar, MODES } from "./ModeBar";
import { SourceToggle, SOURCE_LAYERS, truthAvailable } from "./SourceToggle";
import { WorkAreaTabs, WORK_AREAS } from "./WorkAreaTabs";
import { Button } from "./Button";
import { MetricTile } from "./MetricTile";
import { SubsystemChip } from "./SubsystemChip";
import { Icon, ICON_NAMES } from "../Icon";

afterEach(cleanup);

describe("ModeBar (§5 truth-boundary selector)", () => {
  it("exposes all five modes; OPERATE is the only real-hardware one", () => {
    expect(MODES.map((m) => m.id)).toEqual(["GIS-PLAN", "TRAIN", "SIM-OPERATE", "EVALUATE", "OPERATE"]);
    expect(MODES.filter((m) => m.realHardware).map((m) => m.id)).toEqual(["OPERATE"]);
  });

  it("role-gates: a guest (rank 0) may only select GIS-PLAN", () => {
    render(<ModeBar mode="GIS-PLAN" roleRank={0} />);
    expect((screen.getByRole("button", { name: "GIS-PLAN" }) as HTMLButtonElement).disabled).toBe(false);
    for (const id of ["TRAIN", "SIM-OPERATE", "EVALUATE", "OPERATE"]) {
      expect((screen.getByRole("button", { name: id }) as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it("a director (rank 3) may select every mode, and onChange fires", () => {
    const onChange = vi.fn();
    render(<ModeBar mode="GIS-PLAN" roleRank={3} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "OPERATE" }));
    expect(onChange).toHaveBeenCalledWith("OPERATE");
  });
});

describe("SourceToggle (PO-10 provenance, the sim-vs-truth invariant)", () => {
  it("truthAvailable only in SIM-OPERATE / EVALUATE", () => {
    expect(truthAvailable("SIM-OPERATE")).toBe(true);
    expect(truthAvailable("EVALUATE")).toBe(true);
    expect(truthAvailable("GIS-PLAN")).toBe(false);
    expect(truthAvailable("TRAIN")).toBe(false);
    expect(truthAvailable("OPERATE")).toBe(false);   // no truth channel on real hardware
  });

  it("disables the truth layer in OPERATE and cannot toggle it on", () => {
    const onToggle = vi.fn();
    render(<SourceToggle mode="OPERATE" active={["forecast"]} onToggle={onToggle} />);
    const truthBtn = screen.getByRole("button", { name: /Truth/ }) as HTMLButtonElement;
    expect(truthBtn.disabled).toBe(true);
    fireEvent.click(truthBtn);
    expect(onToggle).not.toHaveBeenCalled();          // a disabled truth layer never fires
  });

  it("allows the truth layer in SIM-OPERATE", () => {
    render(<SourceToggle mode="SIM-OPERATE" active={["truth"]} />);
    const truthBtn = screen.getByRole("button", { name: /Truth/ }) as HTMLButtonElement;
    expect(truthBtn.disabled).toBe(false);
    expect(truthBtn.getAttribute("aria-pressed")).toBe("true");
    expect(SOURCE_LAYERS.map((s) => s.id)).toEqual(["forecast", "truth", "belief", "live"]);
  });
});

describe("WorkAreaTabs (§11 FS-03)", () => {
  it("has the six work areas with Plan first (fleet folded in)", () => {
    expect(WORK_AREAS.map((a) => a.id)).toEqual(
      ["plan", "navigation", "perception", "metrics", "models", "reports"]);
  });

  it("marks the active tab and fires onSelect", () => {
    const onSelect = vi.fn();
    render(<WorkAreaTabs active="plan" onSelect={onSelect} />);
    expect(screen.getByRole("tab", { name: "Plan" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "Navigation" }));
    expect(onSelect).toHaveBeenCalledWith("navigation");
  });
});

describe("Button / MetricTile / SubsystemChip / Icon", () => {
  it("Button applies the variant class + renders an icon", () => {
    const { container } = render(<Button variant="primary" icon="play">Go</Button>);
    const btn = container.querySelector("button")!;
    expect(btn.className).toContain("ds-btn--primary");
    expect(container.querySelector("svg")).not.toBeNull();   // the icon
  });

  it("MetricTile maps status to its modifier class", () => {
    const { container } = render(<MetricTile label="Battery" value={8} unit="%" status="danger" />);
    expect(container.querySelector(".ds-metric--danger")).not.toBeNull();
    expect(screen.getByText("8")).toBeTruthy();
  });

  it("SubsystemChip renders the tag with its full-name title", () => {
    render(<SubsystemChip name="FORGE" />);
    const chip = screen.getByText("FORGE");
    expect(chip.getAttribute("title")).toContain("Physics");
  });

  it("Icon renders every named glyph as an svg", () => {
    expect(ICON_NAMES.length).toBeGreaterThanOrEqual(10);
    for (const n of ICON_NAMES) {
      const { container } = render(<Icon name={n} />);
      expect(container.querySelector("svg")).not.toBeNull();
      cleanup();
    }
  });
});
