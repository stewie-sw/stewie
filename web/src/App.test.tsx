import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { createAppStore } from "./store/store";

describe("App shell", () => {
  it("switches mode without losing the selected sites, and shows the shared clock", () => {
    const store = createAppStore({ mode: "planning", utc: "2027-01-01T00:00:00Z", selectedSites: [] });
    render(<App store={store} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Haworth \(work site\)/ }));
    fireEvent.click(screen.getByRole("tab", { name: "Field" }));
    expect(screen.getByRole("tab", { name: "Field" }).getAttribute("aria-selected")).toBe("true");
    expect((screen.getByRole("checkbox", { name: /Haworth \(work site\)/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByLabelText("UTC").getAttribute("value")).toBe("2027-01-01T00:00:00Z");
  });

  it("lists every catalog site with its source coordinates", () => {
    const store = createAppStore({ mode: "planning", utc: "2027-01-01T00:00:00Z", selectedSites: [] });
    render(<App store={store} />);
    expect(screen.getAllByRole("checkbox").length).toBe(14);
    expect(screen.getByText(/-86\.33.*-25\.51/)).toBeTruthy();
  });
});
