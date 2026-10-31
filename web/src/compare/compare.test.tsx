// Comparison cards + timeline against real engine output (src/fixtures/engine_comparison.json, written by
// `cargo run -p xtask -- web-fixtures`: three catalog sites on tile-over-LDEM_16 stacks, plus Haworth on
// LDEM_16 alone).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import data from "../fixtures/engine_comparison.json";
import { Comparison } from "./Comparison";
import { type Scenario, barSpan, comparable, hours } from "./timeline";

const scenarios = data.scenarios as Scenario[];
const span = { start_s: 0, end_s: 30 * 86_400 };
const W = 600;

describe("timeline geometry", () => {
  it("maps every window edge exactly onto the axis", () => {
    for (const s of scenarios)
      for (const w of [...s.windows.SUN, ...s.windows.EARTH]) {
        const b = barSpan(w, span, W);
        expect(b.x).toBeCloseTo((w.start_s / span.end_s) * W, 9);
        expect(b.x + b.width).toBeCloseTo((w.end_s / span.end_s) * W, 9);
      }
  });

  it("sums lit, shadow and unknown hours from the windows", () => {
    for (const s of scenarios) {
      const h = hours(s.windows.SUN);
      const total = s.windows.SUN.reduce((a, w) => a + (w.end_s - w.start_s), 0) / 3600;
      expect(h.Lit + h.Shadow + h.Unknown).toBeCloseTo(total, 9);
    }
  });

  it("is comparable only when every stack signature matches", () => {
    expect(comparable(scenarios.slice(0, 3))).toBe(true);
    expect(comparable(scenarios)).toBe(false);
  });
});

describe("Comparison view", () => {
  it("draws one labelled bar per window, positioned at the engine's times", () => {
    const { container } = render(<Comparison scenarios={scenarios.slice(0, 3)} width={W} />);
    const bars = container.querySelectorAll("rect[data-verdict]");
    const n = scenarios.slice(0, 3).reduce((a, s) => a + s.windows.SUN.length + s.windows.EARTH.length, 0);
    expect(bars.length).toBe(n);
    const first = scenarios[0]!.windows.SUN[0]!;
    const r = container.querySelector("rect[data-verdict]")!;
    expect(Number(r.getAttribute("x"))).toBeCloseTo(barSpan(first, span, W).x, 9);
    expect(r.getAttribute("aria-label")).toMatch(/Sun .*(Lit|Shadow|Unknown)/);
    expect(screen.queryByText(/not comparable/i)).toBeNull();
  });

  it("withholds comparison across different terrain stacks and never ranks", () => {
    render(<Comparison scenarios={scenarios} width={W} />);
    expect(screen.getByText(/not comparable/i).textContent).toMatch(/ldem_16@1895\.2m/);
    expect(document.body.textContent).not.toMatch(/best|recommend|winner|rank/i);
  });
});
