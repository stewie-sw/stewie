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


def extract_shadow_azimuth_p7(image, blur: int = 3, min_area: int = 12,
                              min_conf: float = 0.30, gate: bool = True) -> ShadowHeadingObs:
    """P7 segmentation front-end (spec sec 18): segment INDIVIDUAL cast-shadow blobs and take one
    DIRECTED vote per blob (major axis, oriented away from the brighter/caster end), then circular-
    mean over blobs. One clean vote per shadow rejects the boulder-rim clutter that defeats the
    per-pixel boundary method, so confidence stays high in dense scenes. Provenance IMAGE_DERIVED."""
    g = _to_gray(image)
    if blur and blur >= 3:
        g = cv2.GaussianBlur(g, (blur | 1, blur | 1), 0)
    from . import masking
    sh = masking.detect_shadow_mask(image).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(sh, connectivity=8)
    H, W = g.shape
    angs, wts = [], []
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < min_area:
            continue
        ys, xs = np.where(labels == k)
        pts = np.stack([xs, ys], 1).astype(float)
        c = pts.mean(0)
        P = pts - c
        cov = P.T @ P / max(len(P), 1)
        w_, V = np.linalg.eigh(cov)
        u = V[:, int(np.argmax(w_))]              # major (elongation) axis
        t = P @ u
        e1, e2 = c + u * t.max(), c + u * t.min()

        def bright(p, d):
            q = (p + d * 4.0).astype(int)
            return float(g[q[1], q[0]]) if (0 <= q[1] < H and 0 <= q[0] < W) else 0.0
        # caster end is brighter just outside; shadow points away from the caster
        dirv = (e2 - e1) if bright(e1, u) >= bright(e2, -u) else (e1 - e2)
        angs.append(np.arctan2(dirv[1], dirv[0]))
        wts.append(np.sqrt(len(pts)))
    if len(angs) < 3:
        raise ValueError("too few shadow blobs for a P7 vote")
    angs = np.array(angs); wts = np.array(wts)
    # AXIS concentration (mod 180, doubled angle) is the robust signal in clutter; the gate uses it.
    C2 = float(np.sum(wts * np.cos(2 * angs))); S2 = float(np.sum(wts * np.sin(2 * angs)))
    R_axis = float(np.hypot(C2, S2) / np.sum(wts))
    # directed azimuth from the (noisier) per-blob caster votes -- 180-deg resolution is the open part.
    C = float(np.sum(wts * np.cos(angs))); S = float(np.sum(wts * np.sin(angs)))
    if gate and R_axis < min_conf:
        raise ValueError(f"P7 axis concentration {R_axis:.3f} below gate {min_conf}")
    az = (np.degrees(np.arctan2(S, C))) % 360.0
    sigma_deg = float(np.degrees(np.sqrt(max(-2.0 * np.log(max(R_axis, 1e-6)), 1e-6)) / max(np.sqrt(len(angs)), 1)))
    return ShadowHeadingObs(z_shadow_body_deg=az, confidence=R_axis, n_edge_px=len(angs), sigma_deg=sigma_deg)


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
