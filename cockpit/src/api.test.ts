import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchEvents, fetchOperators, fetchHealth, fetchMetrics } from "./api";

afterEach(() => vi.restoreAllMocks());
function stub(status: number, json: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ status, json: async () => json })));
}

describe("api adapters (map the real route shapes)", () => {
  it("fetchEvents maps {ts,actor,action,target} and formats the UTC timestamp", async () => {
    stub(200, { ok: true, events: [{ ts: 1718000000, actor: "a@b", action: "auth.login", target: "bootstrap" }] });
    const rows = await fetchEvents(10);
    expect(rows).toHaveLength(1);
    expect(rows[0].actor).toBe("a@b");
    expect(rows[0].action).toBe("auth.login");
    expect(rows[0].tsLabel).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  });

  it("fetchEvents returns [] for a non-director (403)", async () => {
    stub(403, { ok: false });
    expect(await fetchEvents()).toEqual([]);
  });

  it("fetchOperators maps the roster (created_at -> createdAt)", async () => {
    stub(200, { ok: true, operators: [{ email: "a@b", role: "director", status: "active", created_at: 1 }] });
    expect(await fetchOperators()).toEqual([{ email: "a@b", role: "director", status: "active", createdAt: 1 }]);
  });

  it("fetchHealth maps status/version/uptime and derives ok", async () => {
    stub(200, { status: "ok", version: "1.2.3", uptime_s: 42 });
    expect(await fetchHealth()).toEqual({ status: "ok", version: "1.2.3", uptimeS: 42, ok: true });
    stub(200, { status: "degraded", version: "1.2.3", uptime_s: 9 });
    expect((await fetchHealth())!.ok).toBe(false);
  });

  it("fetchMetrics surfaces uptime + the raw snapshot", async () => {
    stub(200, { uptime_s: 100, latency: {} });
    expect((await fetchMetrics())!.uptimeS).toBe(100);
  });
});
