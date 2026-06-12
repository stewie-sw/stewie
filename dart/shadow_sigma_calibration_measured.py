"""Generator for the shadow-sigma calibration artifacts (envelope + MEASURED).

The dated artifacts in stewie/eval/validation/ are GENERATED, never hand-edited; this module is
their committed writer, so regeneration is scripted and G9 gate replay can reproduce them.

Two artifacts, one pipeline:
- ENVELOPE: the modelled 1.0 px edge-noise assumption propagated through real Haworth cast-shadow
  geometry (dart.shadow_sigma_calibration). Historical; superseded by the measured artifact.
- MEASURED: the same propagation driven by the MEASURED edge noise -- the median erf transition
  width over real Chang'e-3 descent-camera mosaic tiles (dart.shadow_edge_sigma), cross-checked on
  the Godot rover renders. Real imagery only; no fabricated edges.

The CE-3 tile directory is machine-local data (not in the repo), supplied via --ce3-dir or
$STEWIE_CE3_DIR. The Godot render cross-check uses the repo's own stewie/godot/out renders.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date as _date

from dart.shadow_edge_sigma import calibrate_measured_edge_sigma
from dart.shadow_sigma_calibration import calibrate_shadow_sigma

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VALIDATION_DIR = os.path.join(_REPO_ROOT, "stewie", "eval", "validation")
_RENDER_KEYWORDS = ("crater_boulders_rover", "drive_cam_front", "drive_cam_left",
                    "drive_cam_right", "a6_")
ELEV_SWEEP = [3, 5, 8, 12, 18, 25, 35]
DEM_WINDOW = ((900, 1100), (900, 1100))
SITE = "haworth"


def haworth_window() -> tuple:
    """The real LOLA Haworth sub-window the calibration runs on (1 km at 5 m per px)."""
    from lode.mission_planner import load_site_dem
    Z, cell = load_site_dem(SITE)
    (r0, r1), (c0, c1) = DEM_WINDOW
    return (Z[r0:r1, c0:c1], cell)


def _window_str() -> str:
    (r0, r1), (c0, c1) = DEM_WINDOW
    return f"rows{r0}-{r1},cols{c0}-{c1} (1km)"


def build_envelope_artifact(dem: tuple, *, date: str) -> dict:
    """The historical envelope artifact: modelled 1.0 px edge noise on the real DEM."""
    art = calibrate_shadow_sigma(dem, sun_az_deg=90.0, elev_sweep=ELEV_SWEEP, sigma_edge_px=1.0)
    art.update({"site": SITE, "dem_window": _window_str(), "date": date})
    return art


def render_xcheck_paths(render_dir: str | None = None) -> list[str]:
    """The repo's Godot rover renders used for the sim cross-check (same filter the evidence
    notebooks use)."""
    d = render_dir or os.path.join(_REPO_ROOT, "stewie", "godot", "out")
    return [p for p in sorted(glob.glob(os.path.join(d, "*.png")))
            if any(k in os.path.basename(p) for k in _RENDER_KEYWORDS)]


def build_measured_artifact(dem: tuple, ce3_paths: list[str], *, date: str,
                            render_dir: str | None = None) -> dict:
    """The MEASURED artifact: the propagation driven by the measured CE-3 edge noise."""
    m_ce3 = calibrate_measured_edge_sigma(ce3_paths)
    sigma_full = float(m_ce3["sigma_edge_px"])
    art = calibrate_shadow_sigma(dem, sun_az_deg=90.0, elev_sweep=ELEV_SWEEP,
                                 sigma_edge_px=sigma_full)
    provenance = {
        "type": "MEASURED (was modelled 1.0 envelope)",
        "method": "erf transition-width (penumbra+PSF) of real lit->shadow edges",
        "ce3_real_lunar": {
            "sigma_edge_px": round(sigma_full, 3), "n_images": int(m_ce3["n_images"]),
            "p25": round(float(m_ce3["p25"]), 3), "p75": round(float(m_ce3["p75"]), 3),
            "source": "Chang'e-3 descent-camera mosaic tiles, Zenodo 1203295 (datasets/lunar_ce3)",
        },
        "note": "measured edge width < the 1.0 px envelope assumption -> the envelope was "
                "CONSERVATIVE; the distribution is bimodal (sharp ~0.35 px population, soft tail "
                "to ~3 px; see p25/p75), so consumers gate on or carry the per-edge fitted width "
                "(dart.shadow_edge_sigma.per_edge_sigma) rather than apply the median globally.",
    }
    rover = render_xcheck_paths(render_dir)
    if len(rover) >= 3:
        m_rov = calibrate_measured_edge_sigma(rover)
        provenance["godot_render_xcheck"] = {
            "sigma_edge_px": round(float(m_rov["sigma_edge_px"]), 3),
            "n_images": int(m_rov["n_images"]),
        }
    art.update({
        "site": SITE, "dem_window": _window_str(), "date": date,
        "sigma_edge_px": round(sigma_full, 3),
        "sigma_edge_provenance": provenance,
        "provenance": "real DEM cast-shadow geometry + MEASURED edge sigma from real Chang'e-3 "
                      "descent-camera imagery (no longer a [CALIB] assumption)",
    })
    return art


def write_artifact(art: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(art, f, indent=1, sort_keys=True)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ce3-dir", default=os.environ.get("STEWIE_CE3_DIR"),
                    help="directory of real CE-3 tiles (recursive *.png); or $STEWIE_CE3_DIR")
    ap.add_argument("--render-dir", default=None,
                    help="Godot render dir for the sim cross-check (default: repo stewie/godot/out)")
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--out-dir", default=_VALIDATION_DIR)
    ap.add_argument("--mode", choices=["both", "envelope", "measured"], default="both")
    a = ap.parse_args(argv)

    dem = haworth_window()
    if a.mode in ("both", "envelope"):
        env = build_envelope_artifact(dem, date=a.date)
        p = os.path.join(a.out_dir, f"shadow_sigma_calibration_{a.date}.json")
        write_artifact(env, p)
        print(f"wrote {p} (envelope, sigma_edge 1.0 px)")
    if a.mode in ("both", "measured"):
        if not a.ce3_dir or not os.path.isdir(a.ce3_dir):
            raise SystemExit("MEASURED mode needs real CE-3 imagery: pass --ce3-dir or set "
                             "$STEWIE_CE3_DIR (refusing to proceed without real data)")
        ce3 = sorted(glob.glob(os.path.join(a.ce3_dir, "**", "*.png"), recursive=True))
        meas = build_measured_artifact(dem, ce3, date=a.date, render_dir=a.render_dir)
        p = os.path.join(a.out_dir, f"shadow_sigma_calibration_MEASURED_{a.date}.json")
        write_artifact(meas, p)
        print(f"wrote {p} (measured, sigma_edge {meas['sigma_edge_px']} px over "
              f"{meas['sigma_edge_provenance']['ce3_real_lunar']['n_images']} CE-3 images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
