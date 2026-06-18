import { describe, it, expect, vi, afterEach } from "vitest";
import { roleRank, fetchMe, login } from "./auth";

afterEach(() => vi.restoreAllMocks());

describe("roleRank (AG-01 ladder)", () => {
  it("orders guest<trainee<operator<director; unknown/null ranks below guest", () => {
    expect(roleRank("guest")).toBe(0);
    expect(roleRank("trainee")).toBe(1);
    expect(roleRank("operator")).toBe(2);
    expect(roleRank("director")).toBe(3);
    expect(roleRank("bogus")).toBe(-1);
    expect(roleRank(null)).toBe(-1);
  });
});

describe("fetchMe (maps the real /auth/me shape)", () => {
  it("maps {ok,identity,role,has_password} to an Identity with derived roleRank", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      status: 200, ok: true,
      json: async () => ({ ok: true, identity: "a@b", role: "operator", has_password: true }),
    })));
    expect(await fetchMe()).toEqual({ identity: "a@b", role: "operator", roleRank: 2, hasPassword: true });
  });
  it("returns null when unauthenticated (401)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ status: 401, ok: false, json: async () => ({}) })));
    expect(await fetchMe()).toBeNull();
  });
});

describe("login", () => {
  it("maps success and surfaces the server error verbatim", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, must_set_password: false }) })));
    expect((await login("a@b", "pw")).ok).toBe(true);
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, json: async () => ({ ok: false, error: "invalid credentials" }) })));
    const r = await login("a@b", "pw");
    expect(r.ok).toBe(false);
    expect(r.error).toBe("invalid credentials");
  });
});
