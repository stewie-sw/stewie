"""Image-derived shadow azimuth (Algorithm P4 sec 15.2) -- the first genuine sensor->factor.

Per FORMAL_ALGORITHM_SYSTEM_SPEC.md: the image extractor MUST produce `z_shadow_body`
(ephemeris alone is not a measurement; provenance = IMAGE_DERIVED, NOT truth -> invariant
I3 No Truth Ingress). At a shadow boundary the intensity gradient points dark->light, i.e.
toward the Sun-lit side; the shadow direction is that plus 180 deg. We take the
magnitude-weighted circular mean of boundary-gradient directions; the resultant length R is
the multi-edge concentration confidence (the spec's gate). Real CV on rendered pixels; the
result carries a covariance (invariant I4).

For a top-down (orthographic-ish) frame the image direction maps to the ground azimuth up to
a fixed image-to-world offset, so the SUN-RESPONSE is validated by the change in extracted
direction across known Sun azimuths (no truth pose needed).
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ShadowHeadingObs:
    z_shadow_body_deg: float        # extracted shadow azimuth in the image/body frame [MEASUREMENT]
    confidence: float               # circular concentration R in [0,1] (multi-edge gate)
    n_edge_px: int
    sigma_deg: float                # covariance accompanies the measurement (I4)
    provenance: str = "IMAGE_DERIVED"


def _to_gray(img):
    g = np.asarray(img)
    if g.ndim == 3:
        g = cv2.cvtColor(g[..., :3].astype(np.uint8), cv2.COLOR_RGB2GRAY)
    return g.astype(np.float32)


def extract_shadow_azimuth(image, blur: int = 5, min_conf: float = 0.30,
                           gate: bool = True) -> ShadowHeadingObs:
    """Extract the dominant shadow azimuth (deg) from a frame, restricted to the lit pixels on
    the boundary of the shadow mask (the lit->shadow transition), where the intensity gradient
    points toward the Sun. The magnitude-weighted circular mean gives the direction; resultant
    length R is the confidence. Raises ValueError below `min_conf` (the spec gate) when gate=True.
    Clean single-caster shadows reach R~0.99; dense clutter (many boulder rims) gives low R, which
    the gate correctly rejects -- a real segmentation/association front-end (P7) is then required."""
    from . import masking
    g = _to_gray(image)
    if blur and blur >= 3:
        g = cv2.GaussianBlur(g, (blur | 1, blur | 1), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    sh = masking.detect_shadow_mask(image)
    boundary = (cv2.dilate(sh.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & (~sh)
    if boundary.sum() < 20:
        raise ValueError("too few shadow-boundary pixels")
    phi = np.arctan2(gy[boundary], gx[boundary])     # dark->light = toward Sun-lit side
    w = mag[boundary]
    C = float(np.sum(w * np.cos(phi))); S = float(np.sum(w * np.sin(phi)))
    R = float(np.hypot(C, S) / max(np.sum(w), 1e-9))
    if gate and R < min_conf:
        raise ValueError(f"shadow-edge concentration {R:.3f} below gate {min_conf} "
                         "(cluttered scene; needs a segmentation front-end)")
    toward_light = np.arctan2(S, C)
    shadow_dir = (np.degrees(toward_light) + 180.0) % 360.0
    sigma_deg = float(np.degrees(np.sqrt(max(-2.0 * np.log(max(R, 1e-6)), 1e-6))))
    return ShadowHeadingObs(z_shadow_body_deg=shadow_dir, confidence=R,
                            n_edge_px=int(boundary.sum()), sigma_deg=sigma_deg)
