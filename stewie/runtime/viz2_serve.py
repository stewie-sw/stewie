"""Standalone launcher for ``Viz2Runtime`` — the viz2 PRD Phase B3 LIVE capture harness.

Constructs a ``Viz2Runtime`` over a REAL DEM bundle, starts its actor loop (the 0600 token file is
written into ``--session-dir``), and HOLDS it alive for ``--seconds`` — or until a ``STOP`` sentinel
appears in the session dir — so a Godot client (``viz2_root.gd --live``) can connect, drive on
conserved terramechanics, dig, and capture. Real runtime, real socket; no synthetic terrain, no
faked timing. This is the process ``viz2_live.sh`` backgrounds before it launches the Godot client.
"""
from __future__ import annotations

import argparse
import os
import time

from stewie.runtime.viz2_runtime import Viz2Runtime


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve a Viz2Runtime for the live Godot client.")
    ap.add_argument("--bundle", required=True, help="DEM bundle dir (e.g. samples/lunar_dem/haworth_sfs_2km_1m)")
    ap.add_argument("--session-dir", required=True, help="session dir for the token file + generation manifests")
    ap.add_argument("--seconds", type=float, default=60.0, help="max wall-time to hold the runtime alive")
    ap.add_argument("--fine-cell-m", type=float, default=0.05, help="fine window cell size (0.05 default / 0.02 gated)")
    ap.add_argument("--start-xy", default="", help='"x,y" global-metre start pose; empty -> base-grid centre')
    args = ap.parse_args()

    start_xy = None
    if args.start_xy:
        xs = args.start_xy.split(",")
        start_xy = (float(xs[0]), float(xs[1]))

    rt = Viz2Runtime(args.bundle, session_dir=args.session_dir,
                     fine_cell_m=args.fine_cell_m, start_xy=start_xy)
    stop_path = os.path.join(args.session_dir, "STOP")
    with rt:
        if not rt.wait_ready(10.0):
            raise SystemExit("viz2_serve: runtime failed to become ready")
        print(f"viz2_serve: ready port={rt.port} token={rt.token_path} "
              f"window={rt.window_shape()} fine_cell_m={rt.ws.fine_cell_m}", flush=True)
        end = time.monotonic() + float(args.seconds)
        while time.monotonic() < end and not os.path.exists(stop_path):
            time.sleep(0.1)
    # E3: on session end (actor stopped by the `with` exit — a race-free world read), emit the REAL
    # RegolithVolumeEstimate over the worked window: conserved_mass_kg = cut_total_kg (CUT mass ONLY),
    # with placed_total_kg / inventory_kg reported SEPARATELY (the round-3 contract).
    if rt.ws.cut_total_kg > 0.0 or rt.ws.placed_total_kg > 0.0:
        ev = rt.emit_volume_evidence()
        e = ev["estimate"]
        print(f"viz2_serve: E3 volume evidence — observed_mass={e.observed_mass_kg:.2f} kg "
              f"cut_total={ev['cut_total_kg']:.2f} kg agreement_conserved={e.agreement_conserved} "
              f"acceptance={e.acceptance} | placed_total={ev['placed_total_kg']:.2f} kg "
              f"inventory={ev['inventory_kg']:.2f} kg (SEPARATE) dig_energy={ev['dig_energy_j']:.0f} J",
              flush=True)
    print("viz2_serve: stopped", flush=True)


if __name__ == "__main__":
    main()
