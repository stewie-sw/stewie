#!/usr/bin/env python3
"""CLI: the viz2 ``--fine on|off`` producer — a REAL DEM window at 2 cm-fine or base resolution.

Crops an active window from a REAL committed bundle (``samples/lunar_dem/<site>``) and writes it as
a standalone INTERFACE.md bundle under ``out/fine_window/<name>/`` that ``viz2.sh --site`` renders.

  * ``--mode on``  -> refine the window to a 2 cm fine cell with a CONSERVATION-BOUNDED fbm sub-DEM
    overlay (coarsen(fine) == the real DEM). Detail ON the real surface, NOT free synthetic.
  * ``--mode off`` -> the same window at the REAL base resolution (straight real crop).

Used by ``viz2.sh --fine on|off --fine-site <real bundle>`` (it calls this), and standalone:

    python scripts/generate_fine_window.py --site samples/lunar_dem/haworth_sfs_2km_1m \
        --mode on --name haworth_fine_on --window-cells 24
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: E402

from stewie.terrain import fine_window as fw  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Produce a REAL DEM window at 2 cm-fine or base res.")
    ap.add_argument("--site", required=True, help="the REAL source bundle dir (samples/lunar_dem/<x>)")
    ap.add_argument("--mode", choices=["on", "off"], default="on",
                    help="on = 2 cm fine overlay on the real window; off = real base-res crop")
    ap.add_argument("--name", default=None,
                    help="output bundle name under out/fine_window/ (default derived from site+mode)")
    ap.add_argument("--window-cells", type=int, default=fw.DEFAULT_WINDOW_CELLS,
                    help="active-window side in BASE cells")
    ap.add_argument("--center-rc", default=None, metavar="ROW,COL",
                    help="window center in base (row,col); default = grid center")
    ap.add_argument("--fine-cell-m", type=float, default=fw.DEFAULT_FINE_CELL_M)
    ap.add_argument("--seed", type=int, default=0, help="world_seed for the fbm detail (fine mode)")
    ap.add_argument("--fbm-nu0", type=float, default=None,
                    help="override the fine-band fbm variance [m^2] (default: calibrated placeholder)")
    ap.add_argument("--no-previews", action="store_true")
    args = ap.parse_args(argv)

    site = args.site
    if not os.path.isabs(site):
        site = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), site)
    center_rc = None
    if args.center_rc:
        r, c = args.center_rc.split(",")
        center_rc = (int(r), int(c))
    name = args.name or (os.path.basename(os.path.normpath(site)) + f"_fine_{args.mode}")

    fields, meta = fw.real_fine_window(
        site, name, fine_on=(args.mode == "on"), center_rc=center_rc,
        window_cells=args.window_cells, fine_cell_m=args.fine_cell_m,
        world_seed=args.seed, fbm_nu0=args.fbm_nu0, write_previews=not args.no_previews)

    out_dir = fw._resolve_out_dir(name)
    # Print the out dir on the LAST line so a caller (viz2.sh) can capture it via `tail -1`.
    print(f"mode={args.mode} grid={meta['grid']['width']}x{meta['grid']['height']} "
          f"@ {meta['grid']['cell_m']} m  window_base_rc={meta['window_base_rc']}")
    if args.mode == "on":
        fo = meta["fine_overlay"]
        print(f"  fine overlay: added_detail_rms={fo['added_detail_rms_m']} m  "
              f"coarsen_equals_real_dem={fo['conservation_check']['coarsen_equals_real_dem']}")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
