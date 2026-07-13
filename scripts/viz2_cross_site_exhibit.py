"""viz2 PRD Phase G — the cross-site DEM comparison EXHIBIT (rendered from REAL data).

Renders a single figure from :mod:`dart.dem_site_compare`:
  * a hillshade + slope panel for each populated on-disk bundle (visibly different relief across the
    real Haworth / Nobile-rim / Shackleton-rim / SfS sites),
  * the per-site statistics table (slope median/RMS, roughness, relief, cell size, verbatim citation),
  * the G2a resolution-difference residual map (SfS 1 m − LOLA 5 m over the same Haworth footprint),
    or an honest "BLOCKED" note if the raw 5 m source is not on host,
  * the cross-site residual verdict (every bundled pair is a disjoint crater -> REFUSE).

No synthetic terrain, no fabricated statistics: every panel is a real ``heightmap.rf32`` run through
the same producers the backend uses. Output: ``out/viz2/cross_site/cross_site_exhibit.png``.

    PYTHONPATH=<repo>:... .venv/bin/python scripts/viz2_cross_site_exhibit.py
"""
from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from dart import dem_site_compare as dsc  # noqa: E402
from stewie.terrain.site_dem import load_haworth_dem, slope_deg_map  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OUT_DIR = os.path.join(_REPO_ROOT, "out", "viz2", "cross_site")


def _hillshade(Z: np.ndarray, cell: float, az_deg: float = 315.0, alt_deg: float = 25.0) -> np.ndarray:
    """A standard analytical hillshade of a real heightmap (grazing low-sun to bring relief out)."""
    gy, gx = np.gradient(Z, cell)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = np.radians(360.0 - az_deg + 90.0)
    alt = np.radians(alt_deg)
    hs = (np.sin(alt) * np.sin(slope)
          + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return np.clip(hs, 0.0, 1.0)


def build_exhibit(out_dir: str = _OUT_DIR) -> str:
    os.makedirs(out_dir, exist_ok=True)
    rows = dsc.compare_table()
    populated = [r for r in rows if r.has_heightmap]

    fig = plt.figure(figsize=(16, 12), constrained_layout=True)
    fig.suptitle("STEWIE viz2 Phase G — cross-site lunar DEM comparison (real LOLA + LRO NAC SfS bundles)",
                 fontsize=15, fontweight="bold")
    gs = fig.add_gridspec(3, len(populated))

    # Row 0-1: per-site hillshade + slope, real relief.
    for i, r in enumerate(populated):
        Z, cell = load_haworth_dem(bundle_dir=os.path.join(dsc.DEFAULT_SITE_ROOT, r.name))
        hs = _hillshade(Z, cell)
        ax0 = fig.add_subplot(gs[0, i])
        ax0.imshow(hs, cmap="gray", origin="upper")
        ax0.set_title(f"{r.region}\n{r.extent_km:g} km @ {r.cell_m:g} m  relief {r.relief_m:.0f} m",
                      fontsize=10)
        ax0.set_xticks([]); ax0.set_yticks([])

        ax1 = fig.add_subplot(gs[1, i])
        sl = slope_deg_map(Z, cell)
        im = ax1.imshow(sl, cmap="magma", origin="upper", vmin=0, vmax=45)
        ax1.set_title(f"slope: med {r.slope_median_deg:.1f}° / rms {r.slope_rms_deg:.1f}°\n"
                      f"roughness med {r.roughness_median_m:.2f} m", fontsize=9)
        ax1.set_xticks([]); ax1.set_yticks([])
        fig.colorbar(im, ax=ax1, fraction=0.046, pad=0.02, label="deg")

    # Row 2 left: the stat + provenance table.
    axt = fig.add_subplot(gs[2, 0:max(1, len(populated) - 1)])
    axt.axis("off")
    cols = ["site", "cell", "extent", "relief", "slope\nmed°", "slope\nrms°", "rough\nmed m", "provenance (verbatim)"]
    cells = []
    for r in rows:
        sm = f"{r.slope_median_deg:.1f}" if r.slope_median_deg is not None else "n/a"
        sr = f"{r.slope_rms_deg:.1f}" if r.slope_rms_deg is not None else "n/a"
        rm = f"{r.roughness_median_m:.2f}" if r.roughness_median_m is not None else "n/a"
        cite = r.citation.split(";")[0]
        cite = (cite[:52] + "…") if len(cite) > 53 else cite
        cells.append([r.name, f"{r.cell_m:g} m", f"{r.extent_km:g} km", f"{r.relief_m:.0f} m",
                      sm, sr, rm, cite])
    tbl = axt.table(cellText=cells, colLabels=cols, loc="center", cellLoc="left")
    tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1.0, 1.5)
    axt.set_title("Per-site statistics (real producers) + verbatim provenance — "
                  "SfS cites Alexandrov & Beyer, LOLA cites Barker/Mazarico",
                  fontsize=10, loc="left")

    # Row 2 right: the G2a residual map (SfS 1 m - LOLA 5 m) or BLOCKED.
    axr = fig.add_subplot(gs[2, len(populated) - 1])
    g2a = dsc.haworth_1m_vs_5m_residual(keep_array=True)
    if g2a.get("blocked"):
        axr.axis("off")
        axr.text(0.5, 0.5, "G2a residual BLOCKED\n\n" + g2a["reason"],
                 ha="center", va="center", wrap=True, fontsize=9, color="firebrick")
    else:
        res = g2a["residual_m"]
        vmax = float(np.nanpercentile(np.abs(res), 98))
        im = axr.imshow(res, cmap="RdBu", origin="upper", vmin=-vmax, vmax=vmax)
        axr.set_title(f"G2a residual: SfS 1 m − LOLA 5 m (same Haworth footprint)\n"
                      f"n={g2a['n']}  mean {g2a['mean_m']:.2f} m  rms {g2a['rms_m']:.2f} m  "
                      f"max|.| {g2a['max_abs_m']:.2f} m", fontsize=9)
        axr.set_xticks([]); axr.set_yticks([])
        fig.colorbar(im, ax=axr, fraction=0.046, pad=0.02, label="m")

    out = os.path.join(out_dir, "cross_site_exhibit.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def main() -> None:
    out = build_exhibit()
    print("viz2 cross-site exhibit ->", out)
    print()
    print(dsc.format_table(dsc.compare_table()))
    g2a = dsc.haworth_1m_vs_5m_residual()
    if g2a.get("blocked"):
        print("\nG2a residual: BLOCKED —", g2a["reason"])
    else:
        print(f"\nG2a residual (SfS 1 m − LOLA 5 m): n={g2a['n']} mean={g2a['mean_m']:.3f} "
              f"rms={g2a['rms_m']:.3f} max|.|={g2a['max_abs_m']:.3f} m")


if __name__ == "__main__":
    main()
