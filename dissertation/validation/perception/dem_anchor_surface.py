#!/usr/bin/env python3
"""VISUAL check for solnav.perception.dem_anchor: render the NCC correlation surface that the DEM
anchor reads the horizontal offset off of.

MATH self-consistency on REAL DEM data: crop an observed patch from the REAL crater_boulders DEM,
shift it by a KNOWN offset, run the correlator, and confirm the recovered offset matches within one
cell. The figure shows (left) the DEM window with the observed-patch footprint and the recovered
peak, and (right) the normalized cross-correlation surface with the recovered peak and the
known-truth offset marked. No synthetic terrain; the clast TRUTH metadata is never read (I3).

  python3 validation/perception/dem_anchor_surface.py [--dem <heightmap.rf32>] [--output <dir>]
"""
import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from dart import dem_anchor  # noqa: E402

DEFAULT_DEM = "/mnt/projects/foss_ipex/dustgym/samples/crater_boulders/heightmap.rf32"
DEFAULT_N = 256
DEFAULT_POSTING_M = 0.02


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dem", default=DEFAULT_DEM, help="REAL DEM heightmap.rf32 (little-endian f32)")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="DEM side length in cells")
    ap.add_argument("--posting-m", type=float, default=DEFAULT_POSTING_M)
    ap.add_argument("--center", type=int, nargs=2, default=(92, 164),
                    help="(row, col) centre of the verified 2-D-distinctive region")
    ap.add_argument("--win", type=int, default=20, help="DEM search half-window (cells)")
    ap.add_argument("--half", type=int, default=12, help="observed patch half-size (cells)")
    ap.add_argument("--known", type=int, nargs=2, default=(3, -2), help="known (dr, dc) offset")
    ap.add_argument("--output", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    if not os.path.exists(args.dem):
        print(f"BLOCKED: real DEM not found at {args.dem}", file=sys.stderr)
        return 2

    Z = np.fromfile(args.dem, dtype="<f4").reshape(args.n, args.n).astype(np.float64)
    cr, cc = args.center
    win, half = args.win, args.half
    kdr, kdc = args.known

    dem_patch = Z[cr - win:cr + win, cc - win:cc + win]
    obs = Z[cr + kdr - half:cr + kdr + half, cc + kdc - half:cc + kdc + half]
    res = dem_anchor.anchor_offset(obs, dem_patch, method="ncc", posting_m=args.posting_m)

    surf = res.surface
    ctr_r = (surf.shape[0] - 1) / 2.0
    ctr_c = (surf.shape[1] - 1) / 2.0
    peak_r, peak_c = np.unravel_index(int(np.argmax(surf)), surf.shape)

    ok = res.offset_cells == (kdr, kdc)
    print(f"known offset (cells)   : ({kdr}, {kdc})")
    print(f"recovered offset (cells): {res.offset_cells}   {'MATCH' if ok else 'MISMATCH'}")
    print(f"recovered sub-cell     : ({res.offset_subcell[0]:+.3f}, {res.offset_subcell[1]:+.3f})")
    if res.offset_m is not None:
        print(f"recovered offset (m)   : ({res.offset_m[0]:+.4f}, {res.offset_m[1]:+.4f})")
    print(f"NCC peak / confidence  : {res.peak:.5f} / {res.confidence:.5f}")

    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(11, 4.6))

    ax0.imshow(dem_patch, cmap="terrain", origin="upper")
    # footprint of the recovered match (top-left corner = peak in surface coords)
    rect = plt.Rectangle((peak_c - 0.5, peak_r - 0.5), 2 * half, 2 * half,
                         fill=False, edgecolor="red", linewidth=1.6)
    ax0.add_patch(rect)
    ax0.set_title(f"REAL DEM window ({os.path.basename(os.path.dirname(args.dem))})\n"
                  f"recovered match footprint (red)")
    ax0.set_xlabel("col [cells]")
    ax0.set_ylabel("row [cells]")

    im = ax1.imshow(surf, cmap="viridis", origin="upper")
    fig.colorbar(im, ax=ax1, fraction=0.046, pad=0.04, label="NCC (TM_CCOEFF_NORMED)")
    ax1.scatter([peak_c], [peak_r], marker="x", s=120, c="red",
                label=f"recovered {res.offset_cells}")
    ax1.scatter([ctr_c + kdc], [ctr_r + kdr], marker="o", s=80, facecolors="none",
                edgecolors="white", linewidths=1.6, label=f"known ({kdr}, {kdc})")
    ax1.axhline(ctr_r, color="0.7", lw=0.6, ls=":")
    ax1.axvline(ctr_c, color="0.7", lw=0.6, ls=":")
    ax1.set_title(f"NCC correlation surface  (peak={res.peak:.4f})\n"
                  f"{'within 1 cell: PASS' if ok else 'MISMATCH'}")
    ax1.set_xlabel("surface col")
    ax1.set_ylabel("surface row")
    ax1.legend(loc="upper right", fontsize=8)

    os.makedirs(args.output, exist_ok=True)
    out_png = os.path.join(args.output, "dem_anchor_ncc_surface.png")
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    plt.close(fig)
    print(f"wrote {out_png}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
