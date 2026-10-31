import { describe, expect, it, vi } from "vitest";
import { createAppStore } from "./store";

const T0 = "2027-01-01T00:00:00Z";

describe("app store", () => {
  it("propagates a clock change to every subscriber", () => {
    const s = createAppStore({ mode: "planning", utc: T0, selectedSites: [] });
    const a = vi.fn();
    const b = vi.fn();
    s.subscribe(a);
    s.subscribe(b);
    s.setUtc("2027-01-02T06:30:00Z");
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    expect(s.get().utc).toBe("2027-01-02T06:30:00Z");
  });

  it("keeps the selected sites across a mode switch", () => {
    const s = createAppStore({ mode: "planning", utc: T0, selectedSites: [] });
    s.toggleSite("haworth");
    s.toggleSite("shackleton_rim");
    s.setMode("field");
    s.setMode("rover");
    expect(s.get().mode).toBe("rover");
    expect(s.get().selectedSites).toEqual(["haworth", "shackleton_rim"]);
  });

  it("rejects a malformed UTC instead of storing it", () => {
    const s = createAppStore({ mode: "planning", utc: T0, selectedSites: [] });
    expect(() => s.setUtc("2027-13-01T00:00:00Z")).toThrow();
    expect(s.get().utc).toBe(T0);
  });

  it("an unsubscribed listener stops hearing changes", () => {
    const s = createAppStore({ mode: "planning", utc: T0, selectedSites: [] });
    const a = vi.fn();
    const off = s.subscribe(a);
    off();
    s.setMode("learn");
    expect(a).not.toHaveBeenCalled();
  });
});
