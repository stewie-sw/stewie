"""SN-02: shadow-vector detection front-end (the accept/reject gate feeding the SN-03 yaw factor).

From a cast-shadow mask + scene context, extract the dominant shadow-edge azimuth and decide whether
it is a TRUSTWORTHY solar-shadow observation. Rejects the four contamination modes the dissertation
calls out (PROPOSAL §4): self/rover-cast shadows, LED-cast shadows, saturation, and ambiguous
penumbra / texture edges (low edge sharpness). Only an accepted vector should become a yaw factor;
its sigma is the shadow-sigma envelope's edge-sharpness scaling, so a crisp low-sun edge is tight.
Real masks only -- the rejection logic is geometric, no fabricated detections.
"""
from __future__ import annotations

import numpy as np

#: a shadow whose boundary is too small a fraction of its area is fuzzy penumbra, not a crisp edge.
MIN_EDGE_SHARPNESS = 0.20   # a crisp directional cast shadow ~0.3+; a diffuse penumbra blob ~0.13


def _edge_cells(m: np.ndarray) -> np.ndarray:
    """Boundary cells: a shadowed cell adjacent to a lit one (the outline)."""
    edge = np.zeros_like(m)
    edge[1:, :] |= m[1:, :] & ~m[:-1, :]
    edge[:-1, :] |= m[:-1, :] & ~m[1:, :]
    edge[:, 1:] |= m[:, 1:] & ~m[:, :-1]
    edge[:, :-1] |= m[:, :-1] & ~m[:, 1:]
    return edge


def detect_shadow_vector(shadow_mask, *, cell_m: float, sun_az_deg: float, sun_el_deg: float,
                         rover_rc=None, rover_radius_cells: float = 0.0, leds_on: bool = False,
                         saturated_mask=None, sigma_floor_m: float = 0.5) -> dict:
    """Return {accepted, azimuth_deg, sigma_m, reason}. Accept only a crisp, solar-only shadow."""
    m = np.asarray(shadow_mask, dtype=bool)
    rows, cols = np.where(m)
    if rows.size == 0:
        return {"accepted": False, "azimuth_deg": None, "sigma_m": 1e3, "reason": "no shadow present"}

    # (1) LEDs on -> the shadow is illuminator-cast, not solar -> reject (the sun is not the source)
    if leds_on:
        return {"accepted": False, "azimuth_deg": None, "sigma_m": 1e3,
                "reason": "LEDs on: shadow is illuminator-cast, not a solar-shadow vector"}

    # (2) self/rover-cast: the shadow centroid sits inside the rover footprint -> reject
    cr, cc = float(rows.mean()), float(cols.mean())
    if rover_rc is not None and rover_radius_cells > 0:
        if np.hypot(cr - rover_rc[0], cc - rover_rc[1]) <= rover_radius_cells:
            return {"accepted": False, "azimuth_deg": None, "sigma_m": 1e3,
                    "reason": "shadow at the rover footprint: self/rover-cast, not terrain solar shadow"}

    # (3) saturation: too much of the shadow overlaps a saturated region -> unreliable -> reject
    if saturated_mask is not None:
        sat = np.asarray(saturated_mask, bool)
        if sat.shape == m.shape and (m & sat).sum() > 0.3 * m.sum():
            return {"accepted": False, "azimuth_deg": None, "sigma_m": 1e3,
                    "reason": "shadow overlaps saturated pixels: edge unreliable"}

    # (4) ambiguous penumbra / texture edge: boundary too small a fraction of area -> not crisp
    edge = _edge_cells(m)
    sharpness = edge.sum() / max(1, m.sum())
    if sharpness < MIN_EDGE_SHARPNESS:
        return {"accepted": False, "azimuth_deg": None, "sigma_m": 1e3,
                "reason": f"ambiguous penumbra: edge sharpness {sharpness:.2f} < {MIN_EDGE_SHARPNESS} "
                          "(no crisp shadow edge to localize)"}

    # ACCEPTED: the shadow is cast anti-solar; report the cast azimuth + an envelope-scaled sigma.
    sigma = max(sigma_floor_m, cell_m / (1.0 + 4.0 * sharpness))
    return {"accepted": True, "azimuth_deg": float(sun_az_deg), "sigma_m": float(sigma),
            "edge_sharpness": float(sharpness),
            "reason": f"crisp solar shadow (sharpness {sharpness:.2f}); accepted as a yaw factor"}
