#!/usr/bin/env python3
"""End-to-end world-state demo on a REAL lunar DEM (default: Haworth).

Drives the full mission -> world-state pipeline against a running STEWIE server and shows the linked
DT-01 world state evolving through it: plan a pad on the real LOLA Haworth DEM, record its conserved
terrain delta (which MOVES the authority content hash off genesis), SIM-execute the released plan
(per-leg + terminal events), then read back the single linked world transaction + the world/execution
timeline + the as-built terrain-memory summary.

Real data only (real LOLA DEM, real conserved authority, real planner/sim); every execution value is
SIM-labeled, never LIVE. Report-only: it asserts nothing and fabricates nothing -- it narrates what the
real pipeline produced. (Pivot note: this was scoped as a Katwijk demo, but no real Katwijk terrain DEM
is available -- only the SLAM traverse -- so the demo runs on the real lunar DEM we do have.)

Run against a live server (e.g. the cockpit on :8011):
    python scripts/demo/demo_world_state.py --base http://127.0.0.1:8011
The orchestration (run_world_state_demo) is client-agnostic (a FastAPI TestClient or an httpx client),
so it is exercised in-process by scripts/demo/test_demo_world_state.py with no live server.
"""
from __future__ import annotations

import os
import sys

ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 36.0, "depth_m": 0.3}]


def run_world_state_demo(client, *, site: str = "haworth", body: str = "moon",
                         headers: dict | None = None) -> dict:
    """Drive plan -> terrain record -> SIM execute -> world-state read-back through ``client`` (any
    object with .post/.get returning a response with .json(): a TestClient or an httpx client).
    Returns the structured result of each step -- the caller narrates it."""
    h = headers or {}
    name = "Haworth demo pad"
    plan = client.post("/plan", json={"name": name, "body": body, "site": site, "charger": [0, 0],
                                      "orders": ORDERS}, headers=h).json()
    mission = {"name": name, "body": body, "charger": [0, 0], "orders": ORDERS}
    terrain = client.post(f"/twin/terrain/{site}", json={"mission": mission}, headers=h).json()
    run = client.post("/executive/run", json={"orders": ORDERS, "site": site, "mission_id": name},
                      headers=h).json()
    world = client.get("/world/transaction", headers=h).json()
    timeline = client.get("/world/transactions?limit=20", headers=h).json()
    terrain_memory = client.get(f"/twin/terrain/{site}", headers=h).json()
    return {"plan": plan, "terrain": terrain, "run": run, "world": world,
            "timeline": timeline, "terrain_memory": terrain_memory}


def format_walkthrough(result: dict) -> str:
    """A human-readable narration of the real pipeline output (no invented values)."""
    p, t, run = result["plan"], result["terrain"], result["run"]
    w, tl, tm = result["world"], result["timeline"], result["terrain_memory"]
    pr = p.get("plan_result", {}) or {}
    out = ["STEWIE world-state demo — real lunar DEM (SIM-labeled execution)\n"]
    out.append(f"1. PLAN   site={p.get('site', '?')}  feasible={p.get('feasible')}  "
               f"orders={pr.get('n_orders', '?')}  terrain_source={p.get('terrain_source', '?')}")
    out.append(f"2. TERRAIN record  v{tm.get('version', '?')}  cells_changed={t.get('cells_changed', '?')}  "
               f"net_volume_m3={t.get('net_volume_m3', '?')}  (authority content hash moves)")
    out.append(f"3. SIM EXECUTE  final={run.get('final_state')}  legs={run.get('n_legs_total')}  "
               f"safed={run.get('safed')}  label={run.get('label')}")
    if w.get("committed"):
        tx = w["transaction"]
        out.append(f"4. LINKED WORLD STATE (DT-01)  seq={tx['seq']}  world_sha={tx['world_sha'][:12]}…  "
                   f"authority={tx['authority_sha'][:12]}…  twin v{tx['twin_version']}  plan={tx['plan_id']}")
    out.append("   EXECUTION/WORLD TIMELINE:")
    for x in tl.get("transactions", []):
        out.append(f"     #{x['seq']}  {x['provenance']}")
    return "\n".join(out)


def main(argv: list | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="STEWIE end-to-end world-state demo (real lunar DEM).")
    ap.add_argument("--base", default=os.environ.get("STEWIE_DEMO_BASE", "http://127.0.0.1:8011"),
                    help="base URL of a running STEWIE server")
    ap.add_argument("--site", default="haworth", help="real imported lunar DEM site")
    ap.add_argument("--api-key", default=os.environ.get("STEWIE_API_KEY"))
    args = ap.parse_args(argv)
    import httpx
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    with httpx.Client(base_url=args.base, timeout=60.0) as c:
        result = run_world_state_demo(c, site=args.site, headers=headers)
    print(format_walkthrough(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
