"""Image-derived shadow direction candidates for Algorithm P4 section 15.2.

These functions operate in image coordinates (x right, y down). They do not produce a
body-frame heading measurement: calibrated camera geometry plus a ground/surface model is
still required to map an image direction into the rover body frame. The returned angular
spread is a heuristic concentration statistic, not a calibrated factor covariance.

The blob method recovers an axis modulo 180 degrees. Its direction must be resolved by caster
association or another cue before it can become an absolute-heading factor.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ShadowHeadingObs:
    z_shadow_image_deg: float
    confidence: float
    n_support: int
    dispersion_deg: float
    periodicity_deg: int
    direction_resolved: bool
    coordinate_frame: str = "IMAGE_X_RIGHT_Y_DOWN"
    covariance_calibrated: bool = False
    provenance: str = "RUNTIME_DERIVED"


@dataclass(frozen=True)
class GroundShadowObservation:
    base_ground_m: np.ndarray
    tip_ground_m: np.ndarray
    direction_body_xz: np.ndarray
    azimuth_body_deg: float
    variance_deg2: float
    periodicity_deg: int
    direction_resolved: bool
    camera_id: str
    sample_id: str
    coordinate_frame: str = "BASE_LINK_GODOT_X_FORWARD_Z_RIGHT"
    covariance_calibrated: bool = False
    provenance: str = "RUNTIME_DERIVED"


def _to_gray(img):
    g = np.asarray(img)
    if g.ndim == 3:
        g = cv2.cvtColor(g[..., :3].astype(np.uint8), cv2.COLOR_RGB2GRAY)
    return g.astype(np.float32)


def extract_shadow_azimuth_p7(image, blur: int = 3, min_area: int = 12,
                              min_conf: float = 0.30, gate: bool = True) -> ShadowHeadingObs:
    """Segment cast-shadow blobs and recover their dominant image-plane axis.

    The major-axis concentration is robust in clutter, but the caster-end heuristic is not
    sufficient to establish a calibrated 360-degree direction. The result is therefore axial
    (period 180 degrees) and cannot directly feed an absolute-heading Gaussian factor."""
    g = _to_gray(image)
    if blur and blur >= 3:
        g = cv2.GaussianBlur(g, (blur | 1, blur | 1), 0)
    from dart import masking
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
    n_blobs = len(angs)
    if n_blobs < 3:
        raise ValueError("too few shadow blobs for a P7 vote")
    a = np.asarray(angs); w = np.asarray(wts)
    # AXIS concentration (mod 180, doubled angle) is the robust signal in clutter; the gate uses it.
    C2 = float(np.sum(w * np.cos(2 * a))); S2 = float(np.sum(w * np.sin(2 * a)))
    R_axis = float(np.hypot(C2, S2) / np.sum(w))
    # The directed vote is retained as a representative axis orientation. Its opposite is
    # equally valid until a separate caster-association stage resolves the ambiguity.
    C = float(np.sum(w * np.cos(a))); S = float(np.sum(w * np.sin(a)))
    if gate and R_axis < min_conf:
        raise ValueError(f"P7 axis concentration {R_axis:.3f} below gate {min_conf}")
    az = (np.degrees(np.arctan2(S, C))) % 360.0
    dispersion_deg = float(
        0.5 * np.degrees(np.sqrt(max(-2.0 * np.log(max(R_axis, 1e-6)), 1e-6)))
    )
    return ShadowHeadingObs(
        z_shadow_image_deg=az,
        confidence=R_axis,
        n_support=n_blobs,
        dispersion_deg=dispersion_deg,
        periodicity_deg=180,
        direction_resolved=False,
    )


def extract_shadow_azimuth(image, blur: int = 5, min_conf: float = 0.30,
                           gate: bool = True) -> ShadowHeadingObs:
    """Extract the dominant shadow azimuth (deg) from a frame, restricted to the lit pixels on
    the boundary of the shadow mask (the lit->shadow transition), where the intensity gradient
    points toward the Sun. The magnitude-weighted circular mean gives the direction; resultant
    length R is the confidence. Raises ValueError below `min_conf` (the spec gate) when gate=True.
    Clean single-caster shadows reach R~0.99; dense clutter (many boulder rims) gives low R, which
    the gate correctly rejects -- a real segmentation/association front-end (P7) is then required."""
    from dart import masking
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
    dispersion_deg = float(np.degrees(np.sqrt(max(-2.0 * np.log(max(R, 1e-6)), 1e-6))))
    return ShadowHeadingObs(
        z_shadow_image_deg=shadow_dir,
        confidence=R,
        n_support=int(boundary.sum()),
        dispersion_deg=dispersion_deg,
        periodicity_deg=360,
        direction_resolved=True,
    )


def map_shadow_segment_to_ground(
    base_uv,
    tip_uv,
    camera_position_base_m,
    camera_quaternion_xyzw,
    width_px: int,
    height_px: int,
    vertical_fov_deg: float,
    ground_y_m: float,
    *,
    camera_id: str,
    sample_id: str,
    periodicity_deg: int,
    direction_resolved: bool,
    pixel_sigma: float = 1.0,
    covariance_calibrated: bool = False,
) -> GroundShadowObservation:
    """Map an associated shadow base/tip segment into the rover ground frame.

    Godot cameras look along local ``-Z``. The returned azimuth is clockwise
    from rover ``+X`` toward rover ``+Z``. Axial observations retain period 180;
    callers may not label them absolute heading until caster association resolves
    the direction.
    """

    from dart.geometry import shadow_metric
    from .camera_rig import quat_to_R

    if periodicity_deg not in (180, 360):
        raise ValueError("shadow periodicity must be 180 or 360 degrees")
    if direction_resolved and periodicity_deg != 360:
        raise ValueError("a resolved direction must use 360-degree periodicity")
    if not camera_id or not sample_id:
        raise ValueError("camera_id and sample_id are required")
    if not np.isfinite(pixel_sigma) or pixel_sigma < 0.0:
        raise ValueError("pixel_sigma must be finite and nonnegative")

    rotation = quat_to_R(np.asarray(camera_quaternion_xyzw, dtype=float))
    basis = (rotation[:, 0], rotation[:, 1], -rotation[:, 2])
    eye = np.asarray(camera_position_base_m, dtype=float)

    def project_segment(base, tip):
        base_ground = shadow_metric.pixel_to_ground(
            base[0], base[1], eye, basis, width_px, height_px, vertical_fov_deg, ground_y_m
        )
        tip_ground = shadow_metric.pixel_to_ground(
            tip[0], tip[1], eye, basis, width_px, height_px, vertical_fov_deg, ground_y_m
        )
        direction = (tip_ground - base_ground)[[0, 2]]
        length = float(np.linalg.norm(direction))
        if length <= 1e-9:
            raise ValueError("shadow base and tip map to the same ground point")
        direction /= length
        angle = float(np.degrees(np.arctan2(direction[1], direction[0])) % 360.0)
        return base_ground, tip_ground, direction, angle

    base = np.asarray(base_uv, dtype=float)
    tip = np.asarray(tip_uv, dtype=float)
    if base.shape != (2,) or tip.shape != (2,) or not np.all(np.isfinite([*base, *tip])):
        raise ValueError("shadow base/tip pixels must be finite 2-vectors")
    base_ground, tip_ground, direction, angle = project_segment(base, tip)

    errors = []
    if pixel_sigma > 0.0:
        for target in ("base", "tip"):
            for axis in range(2):
                for sign in (-1.0, 1.0):
                    perturbed_base = base.copy()
                    perturbed_tip = tip.copy()
                    selected = perturbed_base if target == "base" else perturbed_tip
                    selected[axis] += sign * pixel_sigma
                    _, _, _, perturbed_angle = project_segment(perturbed_base, perturbed_tip)
                    period = float(periodicity_deg)
                    error = (perturbed_angle - angle + period / 2.0) % period - period / 2.0
                    errors.append(error)
    variance = float(np.mean(np.square(errors))) if errors else 0.0
    return GroundShadowObservation(
        base_ground_m=base_ground,
        tip_ground_m=tip_ground,
        direction_body_xz=direction,
        azimuth_body_deg=angle,
        variance_deg2=variance,
        periodicity_deg=periodicity_deg,
        direction_resolved=direction_resolved,
        camera_id=camera_id,
        sample_id=sample_id,
        covariance_calibrated=covariance_calibrated,
    )


def associate_base_tip(image, *, dark_frac: float = 0.5, bright_frac: float = 1.5,
                       adjacency_px: int = 12) -> dict:
    """GENERAL image-derived shadow base/tip association (G2 blocker 3).

    From a single image: segment the cast shadow (dark vs median), find its principal axis, and
    resolve WHICH end is the BASE by caster adjacency -- the end whose neighbourhood contains
    sunlit-caster pixels (bright vs median). Returns {base_px, tip_px, direction_deg (FULL 360,
    base->tip = anti-sun azimuth in IMAGE_X_RIGHT_Y_DOWN), confidence}. Raises if no shadow or if
    neither end is caster-adjacent (no association -- never a fabricated default).
    """
    gray = np.asarray(image, dtype=float)
    if gray.ndim == 3:
        gray = gray[..., :3].mean(axis=2)
    med = float(np.median(gray))
    dark = gray < dark_frac * med
    # caster cue lives in _caster (local max vs median); see the asymmetry refusal below
    rows, cols = np.where(dark)
    if rows.size < 12:
        raise ValueError("no usable shadow-dark region for base/tip association")
    pts = np.stack([cols, rows], axis=1).astype(float)        # (x, y) image frame
    mean = pts.mean(axis=0)
    u, s, vt = np.linalg.svd(pts - mean, full_matrices=False)
    axis = vt[0]                                              # principal direction (axial)
    proj = (pts - mean) @ axis
    end_a = pts[int(np.argmin(proj))]
    end_b = pts[int(np.argmax(proj))]

    def _caster(end):
        """(score, highlight position): score = how much the end's local max exceeds the median."""
        x0, y0 = int(round(end[0])), int(round(end[1]))
        r = adjacency_px
        ys = slice(max(0, y0 - r), min(gray.shape[0], y0 + r + 1))
        xs = slice(max(0, x0 - r), min(gray.shape[1], x0 + r + 1))
        nb = gray[ys, xs]
        j = int(np.argmax(nb))
        hy, hx = divmod(j, nb.shape[1])
        return float(nb.max() - med), np.array([xs.start + hx, ys.start + hy], float)

    (sa, pa), (sb, pb) = _caster(end_a), _caster(end_b)
    hi, lo = max(sa, sb), min(sa, sb)
    if hi < 0.03 * max(med, 1.0) or (hi - lo) < 0.5 * hi:
        # no caster highlight, or both ends equally bright (no ASYMMETRY -> no association): refuse
        # rather than guess -- a wrong base silently flips the recovered sun direction by 180 deg
        raise ValueError("no asymmetric sunlit caster at a shadow end -- association impossible")
    # the BASE is the CASTER's ground position (the highlight), not the first detectable dark pixel:
    # the penumbra delays darkness by several px, which biased the height ~10% low on the p5 evidence
    base, tip = (pa, end_b) if sa >= sb else (pb, end_a)
    d = tip - base
    direction = float(np.degrees(np.arctan2(d[1], d[0])) % 360.0)
    denom = sa + sb
    return {"base_px": base, "tip_px": tip, "direction_deg": direction,
            "confidence": float(max(sa, sb) / denom)}
