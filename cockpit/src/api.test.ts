import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchEvents, fetchOperators, fetchHealth, fetchMetrics, fetchNavContract, submitPlan } from "./api";

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

  it("fetchNavContract maps stages with present/gated + on_host_complete (FS-05)", async () => {
    stub(200, { ok: true, version: "1.0", on_host_complete: true, stages: [
      { stage: "global_route", present: true, seam: "route_leg", note: "" },
      { stage: "live_planner_binary", present: false, seam: "autoware", note: "gated: needs a ROS host" },
    ] });
    const c = await fetchNavContract();
    expect(c!.version).toBe("1.0");
    expect(c!.onHostComplete).toBe(true);
    expect(c!.stages).toHaveLength(2);
    expect(c!.stages.find((s) => s.stage === "live_planner_binary")!.present).toBe(false);
  });

  it("submitPlan maps the PlanResult (feasible, totals, IR actions)", async () => {
    stub(200, { ok: true, feasible: true,
      totals: { makespan_s: 600, energy_actual_kj: 2040, mass_moved_kg: 120 },
      plan_ir: { plan_id: "p1", actions: [{}, {}, {}] } });
    const r = await submitPlan([{ action: "pad", kind: "fill", x: 1, y: 1, footprint_m2: 16, depth_m: 0.3 }]);
    expect(r.feasible).toBe(true);
    expect(r.makespanS).toBe(600);
    expect(r.energyMJ).toBeCloseTo(2.04);
    expect(r.massKg).toBe(120);
    expect(r.nActions).toBe(3);
    expect(r.planId).toBe("p1");
  });

  it("submitPlan surfaces the server error on a 400", async () => {
    stub(400, { ok: false, error: "bad order field" });
    const r = await submitPlan([]);
    expect(r.feasible).toBe(false);
    expect(r.error).toBe("bad order field");
  });
});
