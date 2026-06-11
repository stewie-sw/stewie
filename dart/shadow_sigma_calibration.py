"""#81: shadow-channel sigma calibration (the highest-priority evidence-path run).

Characterizes the shadow-channel measurement covariance on REAL terrain: across a sun-elevation
sweep, the cast-shadow geometry (dart.shadow_predict) gives a shadow length L; the sub-pixel
edge-localization noise sigma_edge_px maps to a length noise sigma_L = sigma_edge_px * m_per_px,
which the published first-order model (dart.geometry.shadow_metric.shadow_height_sigma) propagates
to a height-fix sigma_H. The calibration identifies the OPERATING ENVELOPE (the sun-elevation band
where sigma_H is small enough for the shadow factor to inform the pose graph) and reports it with a
dev/held-out split, mirroring the stereo disparity-sigma calibration that G2 used. Real DEM only;
the only modelled input is the documented sub-pixel edge noise (NOT fabricated data).
"""
from __future__ import annotations

import numpy as np

from dart.geometry.shadow_metric import shadow_height_sigma
from dart.shadow_predict import cast_shadow_mask


def _max_shadow_run_m(mask, cell_m, sun_az_deg):
    """Longest contiguous shadowed run along the sun azimuth [m] -- the measurable shadow length.
    March a line through EVERY cell (dense) in the azimuth direction, counting the contiguous
    shadowed span; return the longest found * cell_m."""
    import math
    m = np.asarray(mask, bool)
    h, w = m.shape
    dx, dy = math.cos(math.radians(sun_az_deg)), math.sin(math.radians(sun_az_deg))
    best = 0
    for r0 in range(h):
        for c0 in range(w):
            if not m[r0, c0]:
                continue
            run = 0; r, c = float(r0), float(c0)
            while 0 <= int(round(r)) < h and 0 <= int(round(c)) < w and m[int(round(r)), int(round(c))]:
                run += 1; r += dy; c += dx
            if run > best:
                best = run
    return best * cell_m


def calibrate_shadow_sigma(dem, *, sun_az_deg=90.0, elev_sweep=None, sigma_edge_px=1.0,
                           m_per_px=None, holdout_frac=0.4, useful_sigma_h_m=0.5):
    """Calibrate sigma_H across an elevation sweep on a real DEM. Returns the artifact dict:
    per-elevation (L, sigma_H), the calibrated dev sigma, the held-out coverage, and the operating
    envelope (elevations where sigma_H <= useful_sigma_h_m)."""
    Z, cell_m = dem[0], float(dem[1])
    m_per_px = float(m_per_px or cell_m)
    elevs = list(elev_sweep or [5, 10, 15, 20, 30, 45, 60, 75])
    sigma_L = float(sigma_edge_px) * m_per_px
    rows = []
    for el in elevs:
        mask = cast_shadow_mask((Z, cell_m), sun_az_deg=float(sun_az_deg), sun_el_deg=float(el))
        L = _max_shadow_run_m(mask, cell_m, sun_az_deg)
        if L <= 0.0:
            continue
        sH = shadow_height_sigma(L, float(el), sigma_L, sigma_e_deg=0.1)
        rows.append({"elev_deg": float(el), "shadow_len_m": round(L, 2),
                     "sigma_H_m": round(sH, 4)})
    # dev/held-out split on the sweep (interleaved so both span the elevation range)
    dev = rows[::2]
    held = rows[1::2]
    dev_sigma = float(np.median([r["sigma_H_m"] for r in dev])) if dev else float("nan")
    covered = sum(1 for r in held if r["sigma_H_m"] <= max(dev_sigma * 1.5, useful_sigma_h_m))
    coverage = covered / len(held) if held else 0.0
    envelope = [r["elev_deg"] for r in rows if r["sigma_H_m"] <= useful_sigma_h_m]
    return {
        "schema_version": "stewie_shadow_sigma_calibration/1.0",
        "channel": "shadow", "sun_az_deg": float(sun_az_deg),
        "sigma_edge_px": float(sigma_edge_px), "m_per_px": m_per_px, "sigma_L_m": round(sigma_L, 4),
        "per_elevation": rows, "n": len(rows),
        "dev_sigma_H_m": round(dev_sigma, 4), "holdout_coverage": round(coverage, 3),
        "operating_envelope_elev_deg": envelope, "useful_sigma_h_m": useful_sigma_h_m,
        "provenance": "real DEM cast-shadow geometry; sub-pixel edge noise the only modelled input; "
                      "shadow_height_sigma first-order propagation (spec sec 16). [CALIB] magnitude "
                      "pending a measured-edge dataset.",
    }
