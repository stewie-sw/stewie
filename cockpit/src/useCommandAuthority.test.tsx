import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCommandAuthority } from "./useCommandAuthority";

const KEY = "stewie_cmd_authority";

function foreignFreshClaim() {
  localStorage.setItem(KEY, JSON.stringify({ id: "another-window", ts: Date.now() }));
  window.dispatchEvent(new StorageEvent("storage", { key: KEY }));
}

describe("useCommandAuthority (FS-17 single command authority)", () => {
  beforeEach(() => localStorage.clear());

  it("the first/only window claims ownership", () => {
    const { result } = renderHook(() => useCommandAuthority());
    expect(result.current.isOwner).toBe(true);
    expect(document.body.dataset.cmdrole).toBe("owner");
  });

  it("goes read-only when another window holds a fresh claim", () => {
    const { result } = renderHook(() => useCommandAuthority());
    act(foreignFreshClaim);
    expect(result.current.isOwner).toBe(false);
    expect(document.body.dataset.cmdrole).toBe("readonly");
  });

  it("takeover explicitly reclaims authority", () => {
    const { result } = renderHook(() => useCommandAuthority());
    act(foreignFreshClaim);
    expect(result.current.isOwner).toBe(false);
    act(() => result.current.takeover());
    expect(result.current.isOwner).toBe(true);
    expect(document.body.dataset.cmdrole).toBe("owner");
  });
});
