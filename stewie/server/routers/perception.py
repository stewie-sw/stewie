"""Perception router (ARCH-3): the estimation + render surface -- algorithm comparison (/compare),
the articulation-parallax relocalization fix (/localize), the integrated SLAM run + class comparison
over real Katwijk (/slam, /slam/compare), the two-posture parallax capture plan + measured render-pair
fix (/render/parallax, /localize/render), structure decomposition (/structure), drum-fill sensing
(/sense), and the Godot earthwork render (/render).

Shared deps come from server.schemas (Order/_MAX_ORDERS), server.state (the DEM), and server.services
(audit log, report-lock, report pruning); the heavy dart/leap/godot/render modules import lazily. No
app-module import (no cycle)."""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from stewie.server import state
from stewie.server.deps import _env, require_auth
from stewie.server.schemas import Order, _MAX_ORDERS
from stewie.server.services import log_event, prune_reports, report_lock

router = APIRouter()
log = logging.getLogger("stewie.server")

# the server package dir (server/), one level up from routers/ -- the bundled assets sit above it
_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HAWORTH = os.path.normpath(os.path.join(_PKG, "..", "..", "samples", "lunar_dem", "haworth_10km_5m"))
_PARALLAX_RENDER_DIR = os.path.normpath(os.path.join(_PKG, "..", "godot", "out", "parallax"))
_PARALLAX_SCENE_DIR = os.path.normpath(os.path.join(_PKG, "..", "..", "samples", "crater_boulders"))

_PRP = None
_PRP_LOADED = False


def _load_prp():
    """Lazy + memoized import of the Godot-driving plan_render_pipeline (it lives in scripts/). Returns
    None when the sidecar/binary is absent -- /render then degrades to 503, never fabricates."""
    global _PRP, _PRP_LOADED
    if _PRP_LOADED:
        return _PRP
    _PRP_LOADED = True
    try:
        from lode import mission_planner as MP
        sys.path.insert(0, os.path.join(MP._REPO_ROOT, "scripts"))
        import plan_render_pipeline as PRP
        _PRP = PRP
    except Exception as e:   # noqa: BLE001 -- /render just becomes unavailable
        log.info("render pipeline unavailable (Godot sidecar import failed: %r); /render -> 503", e)
        _PRP = None
    return _PRP


# ---- request models -------------------------------------------------------------------------
class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(default="mission", max_length=200)
    body: str = Field(default="moon", max_length=40)
    orders: list[Order] = Field(default_factory=list, max_length=_MAX_ORDERS)
    objective: str = Field(default="time", max_length=40)


class SenseRequest(BaseModel):
    true_mass_kg: float = Field(ge=0.0, le=1e5)
    capacity_kg: float | None = Field(default=None, gt=0.0, le=1e5)
    noise_frac: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = Field(default=0, ge=0)


class StructureRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = Field(default=None, max_length=80)
    x: float = 0.0
    y: float = 0.0
    params: dict = Field(default_factory=dict)


class RenderRequest(BaseModel):
    u: float = Field(default=0.5, ge=0.0, le=1.0)
    v: float = Field(default=0.5, ge=0.0, le=1.0)
    pad_frac: float = Field(default=0.5, gt=0.0, le=1.0)
    mission_t_s: float | None = None   # T6.3: render under the planner's mission-time sun


class LocalizeRequest(BaseModel):
    # I3: the estimator surface is observation-only -- forbid extra keys so no truth/hidden-state field
    # (true_pose, slip, terrain truth) can ride in on the request and silently enter the estimator.
    model_config = ConfigDict(extra="forbid")
    landmarks_xy: list[tuple[float, float]] = Field(max_length=256)   # known shadow-tip landmark (x,y)
    pixel_shifts: list[float] = Field(max_length=256)                # vertical parallax shift per landmark (px)
    dh_m: float = Field(gt=0.0, le=10.0)                # commanded chassis lift (m) -- the parallax baseline
    fx_px: float = Field(gt=0.0, le=1e5)                # camera focal length (px)
    sigma_px: float = Field(default=0.3, gt=0.0, le=100.0)           # measured shadow-edge pixel noise
    prior_xy: tuple[float, float] = (0.0, 0.0)          # current dead-reckoned pose guess
    prior_yaw: float = Field(default=0.0, ge=-7.0, le=7.0)
    prior_sigma_xy: float = Field(default=50.0, gt=0.0, le=1e6)      # weak by default -> the fix dominates
    prior_sigma_yaw: float = Field(default=1.0, gt=0.0, le=1e3)
    # #148: OPTIONAL shadow-nav heading fusion -- close the shadow + parallax loop in one update. Per
    # detected shadow landmark: the body-frame bearing of the anti-solar shadow ray + its contrast (the
    # acceptance gate); plus the ephemeris anti-solar azimuth. When present, /localize adds a shadow_yaw
    # heading factor (dart.shadow_factors) to the same graph as the parallax (x,y) fix.
    shadow_bearings_deg: list[float] | None = Field(default=None, max_length=256)
    shadow_contrasts: list[float] | None = Field(default=None, max_length=256)
    anti_solar_az_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    shadow_sigma_deg: float = Field(default=8.0, gt=0.0, le=90.0)
    shadow_min_contrast: float = Field(default=20.0, ge=0.0, le=255.0)


class SlamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")          # I3: observation/config only -- no truth injection
    # pattern-validated -> the segment name cannot path-traverse out of the dataset root
    segment: str = Field(default="Part1", pattern=r"^Part[1-9][0-9]?$", max_length=12)
    n_keyframes: int = Field(default=30, ge=5, le=200)
    seed: int = Field(default=0, ge=0, le=10000)


class SlamCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment: str = Field(default="Part1", pattern=r"^Part[1-9][0-9]?$", max_length=12)
    n_keyframes: int = Field(default=30, ge=5, le=200)
    n_seeds: int = Field(default=12, ge=1, le=100)


class LocalizeRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: str = Field(default="front_left", pattern=r"^[a-z_]+$", max_length=32)
    drift_m: float = Field(default=1.41, gt=0.0, le=50.0)


class ParallaxPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: str = Field(default="crater_boulders", pattern=r"^[A-Za-z0-9_\-]+$", max_length=64)
    sun_az_deg: float = Field(ge=0.0, le=360.0)
    sun_el_deg: float = Field(ge=0.0, le=90.0)
    posture_from: str = Field(default="TRANSIT", pattern=r"^[A-Z_]+$", max_length=32)
    posture_to: str = Field(default="MEERKAT", pattern=r"^[A-Z_]+$", max_length=32)
    size: str = Field(default="1024x768", pattern=r"^\d{2,5}x\d{2,5}$", max_length=12)


# ---- endpoints ------------------------------------------------------------------------------
@router.post("/compare")
def post_compare(req: CompareRequest, _auth: None = Depends(require_auth)):
    from lode import mission_planner as MP
    payload = req.model_dump(exclude_unset=True)
    try:
        mission = MP.mission_from_dict(payload)
        dem, origin = state.moon_dem() if mission.body == "moon" else (None, (0.0, 0.0))
        result = MP.compare_algorithms(mission, objective=req.objective, dem=dem, dem_origin=origin)
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, **result}


@router.post("/localize")
def post_localize(req: LocalizeRequest, _auth: None = Depends(require_auth)):
    """[REQ:PM-06] SN-10 articulation-parallax relocalization, wired into the estimator. From the
    shadow-tip PIXEL shifts observed under a commanded chassis lift dh, triangulate landmark ranges,
    fix the rover (x,y) heading-free, inject it into a one-node PoseGraphSE2 as an ABSOLUTE factor with
    the geometry-DERIVED covariance, and return the re-optimized fix + 1-sigma. This is the missing
    endpoint that makes the validated estimator reachable from the live system (PRD §22 P1.1)."""
    from dart import articulated_parallax as AP
    from dart import pose_graph_se2 as PG
    n = len(req.landmarks_xy)
    if n < 2:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "need >= 2 landmarks for a heading-free fix"})
    if len(req.pixel_shifts) != n:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "pixel_shifts must match landmarks_xy in length"})
    # #148: optional shadow-nav heading fusion -- needs the ephemeris anti-solar azimuth to turn a
    # body-frame shadow bearing into a heading. Validate the pairing before touching the estimator.
    shadow_added = 0
    if req.shadow_bearings_deg:
        if req.anti_solar_az_deg is None:
            return JSONResponse(status_code=400, content={"ok": False, "error":
                "shadow_bearings_deg requires anti_solar_az_deg (the ephemeris anti-solar azimuth)"})
        if req.shadow_contrasts is not None and len(req.shadow_contrasts) != len(req.shadow_bearings_deg):
            return JSONResponse(status_code=400, content={"ok": False, "error":
                "shadow_contrasts must match shadow_bearings_deg in length"})
    try:
        graph = PG.PoseGraphSE2()
        graph.add_prior(0, (float(req.prior_xy[0]), float(req.prior_xy[1]), float(req.prior_yaw)),
                        float(req.prior_sigma_xy), float(req.prior_sigma_yaw))
        if req.shadow_bearings_deg:                          # add shadow_yaw factors BEFORE the parallax
            from dart import shadow_factors as SF            # solve so the final optimize fuses both
            contrasts = (req.shadow_contrasts if req.shadow_contrasts is not None
                         else [req.shadow_min_contrast] * len(req.shadow_bearings_deg))
            facs = SF.shadow_yaw_factors([{"contrast": float(c)} for c in contrasts],
                                         [float(b) for b in req.shadow_bearings_deg],
                                         anti_solar_az_deg=float(req.anti_solar_az_deg),
                                         sigma_deg=float(req.shadow_sigma_deg),
                                         min_contrast=float(req.shadow_min_contrast))
            shadow_added = SF.add_shadow_yaw_factors(graph, 0, facs)
        out = AP.articulation_localize(
            graph, 0, [(float(x), float(y)) for x, y in req.landmarks_xy],
            [float(s) for s in req.pixel_shifts],
            dh_m=float(req.dh_m), fx_px=float(req.fx_px), sigma_px=float(req.sigma_px))
    except (ValueError, RuntimeError) as e:                 # degenerate geometry -> honest 400, not a 500
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    fix = out["fix_xy"]
    log_event("api", "localize", f"{n} landmarks -> fix ({fix[0]:.2f},{fix[1]:.2f}) sigma "
              f"{out['fix_sigma_m']:.3f}m" + (f" + {shadow_added} shadow-yaw" if shadow_added else ""))
    return {
        "ok": True,
        "fix_xy": [float(fix[0]), float(fix[1])],
        "fix_sigma_m": float(out["fix_sigma_m"]),
        "shadow_yaw_factors_added": int(shadow_added),   # #148: shadow-nav heading factors fused (0 if none)
        # H-14: a < 3-non-collinear-landmark fix is mirror-ambiguous -- surface the flag + both hypotheses
        # so the operator/executive does not treat the near-prior basin as a unique heading-free fix.
        "ambiguous": bool(out.get("ambiguous", False)),
        "hypotheses": [[float(x), float(y)] for (x, y) in out.get("hypotheses", [fix])],
        "pose": {str(k): [float(c) for c in v] for k, v in out["pose"].items()},
        "xy_sigma": {str(k): float(v) for k, v in out["xy_sigma"].items()},
        "yaw_sigma": {str(k): float(v) for k, v in out["yaw_sigma"].items()},
    }


_KATWIJK_CACHE: dict = {}   # part name -> loaded real arrays (parse once, reuse across requests)


def _katwijk_arrays(segment: str):
    """Resolve + cache the REAL Katwijk arrays for a segment. Returns None if the dataset is not on this
    host (not bundled -- ESA license + size); the /slam endpoint then answers 503, never fabricates.
    No machine-specific path in source: the root is $STEWIE_KATWIJK_DIR."""
    if segment in _KATWIJK_CACHE:
        return _KATWIJK_CACHE[segment]
    root = _env("KATWIJK_DIR")
    if not root:
        return None
    part_dir = os.path.join(root, segment)
    if not os.path.isdir(part_dir):
        return None
    from dart import integrated_slam as ISLAM
    arrays = ISLAM.load_katwijk_arrays(part_dir)
    _KATWIJK_CACHE[segment] = arrays
    return arrays


@router.post("/slam")
def post_slam(req: SlamRequest, _auth: None = Depends(require_auth)):
    """[REQ:PM-06] The integrated multi-factor SLAM run, exposed. Fuse odometry + IMU-yaw + shadow-yaw
    + articulation-parallax + DEM-registration over a real Katwijk segment and return the trajectory,
    the aligned + absolute trajectory error, the odometry-only baseline, and the leave-one-out factor
    attribution. The raw Katwijk traverse is not bundled (ESA license + size); when it is not on this
    host the endpoint answers 503 -- it never fabricates a trajectory (PRD §22 P1.2)."""
    from dart import integrated_slam as ISLAM
    arrays = _katwijk_arrays(req.segment)
    if arrays is None:
        return JSONResponse(status_code=503, content={
            "ok": False, "error": f"Katwijk segment {req.segment!r} unavailable (set STEWIE_KATWIJK_DIR "
            "to the dataset root; not bundled -- ESA license + size)"})
    truth, dr, tyaw, gyro = arrays
    try:
        loo = ISLAM.leave_one_out(truth, dr, tyaw, gyro, n_keyframes=req.n_keyframes, seed=req.seed)
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    full, base = loo["full"], loo["baseline_odom"]
    log_event("api", "slam",
              f"{req.segment}: fused {full['abs_max_err_m']:.2f}m vs baseline {base['abs_max_err_m']:.2f}m")
    return {
        "ok": True, "segment": req.segment, "n_keyframes": req.n_keyframes,
        "ate_aligned_m": full["ate_aligned_m"], "abs_max_err_m": full["abs_max_err_m"],
        "baseline_abs_max_err_m": base["abs_max_err_m"],
        "reduction_x": round(base["abs_max_err_m"] / max(full["abs_max_err_m"], 1e-9), 1),
        "n_fix": full["n_fix"],
        "trajectory_xy": [[float(x), float(y)] for x, y in full["est_xy"]],
        "baseline_xy": [[float(x), float(y)] for x, y in base["est_xy"]],   # odom-only path -> est-vs-DR plot
        "leave_one_out": loo["leave_one_out"],
    }


@router.post("/slam/compare")
def post_slam_compare(req: SlamCompareRequest, _auth: None = Depends(require_auth)):
    """[REQ:SN-12] The shared-testbed head-to-head, surfaced. The SAME pose graph over the SAME real
    Katwijk trajectory under three approach classes, each at its characteristic absolute-fix sigma:
    passive single-pass (no fix), ShadowNav-class global map-match (~3 m), ARGUS articulation parallax
    (~0.5 m). Each class is MODELED at its reported accuracy against the real drift -- the proprietary
    stacks are not executed (honest comparison-of-classes, not of stacks). 503 when the dataset is
    absent (PRD §22 P3)."""
    from dart import integrated_slam as ISLAM
    arrays = _katwijk_arrays(req.segment)
    if arrays is None:
        return JSONResponse(status_code=503, content={
            "ok": False, "error": f"Katwijk segment {req.segment!r} unavailable (set STEWIE_KATWIJK_DIR; "
            "not bundled -- ESA license + size)"})
    truth, dr, tyaw, gyro = arrays
    try:
        cmp = ISLAM.shared_testbed_comparison(truth, dr, tyaw, gyro,
                                              n_seeds=req.n_seeds, n_keyframes=req.n_keyframes)
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "segment": req.segment, "n_seeds": req.n_seeds,
            "modeled": "each class at its reported sigma vs the real drift; stacks not executed", "comparison": cmp}


@router.post("/render/parallax")
def post_render_parallax(req: ParallaxPlanRequest, _auth: None = Depends(require_auth)):
    """[REQ:SN-10] Wire the articulation-parallax capture onto the render surface. Return the
    two-posture standstill capture plan: the known baseline dh = lift_B - lift_A and the two Godot
    render commands (posture A + posture B, same scene + sun, the 8-camera rig) a GPU host runs to
    capture the parallax pair. The plan + the exact dh are deterministic; executing the renders and
    reading the shadow-tip pixel SHIFT is the gated GPU/photometric layer (PRD §22 P1.3)."""
    from stewie.godot import articulation_bridge as AB
    try:
        plan = AB.parallax_capture_plan(
            req.scene, sun_az_deg=req.sun_az_deg, sun_el_deg=req.sun_el_deg,
            posture_from=req.posture_from, posture_to=req.posture_to, size=req.size)
    except (KeyError, ValueError) as e:                 # unknown posture name -> get_posture raises KeyError
        return JSONResponse(status_code=400, content={"ok": False, "error": f"unknown posture: {e}"})
    return {"ok": True, "scene": req.scene, **plan}


@router.post("/localize/render")
def post_localize_render(req: LocalizeRenderRequest, _auth: None = Depends(require_auth)):
    """[REQ:SN-10] REAL measured articulation-parallax fix from the committed two-posture render-pair.
    A truth-free confidence gate + RANSAC over the measured shadow/clast vertical parallax recovers the
    rover ground position in the DEM-local frame (where it sits on the 3D DEM). TRL-5-faithful: the
    matched features lie inside the IPEx rig's sourced 0.37-1.9 m resolvable range. 503 when the
    render-pair is absent -- never a fabricated fix (PRD §22 P3)."""
    if not os.path.exists(os.path.join(_PARALLAX_RENDER_DIR, "A", req.camera + ".png")):
        return JSONResponse(status_code=503, content={
            "ok": False, "error": "two-posture render-pair unavailable "
            "(stewie/godot/out/parallax); render it with the Godot sidecar first"})
    from stewie.godot import articulation_bridge as AB
    try:
        res = AB.localize_on_render_pair(_PARALLAX_RENDER_DIR, _PARALLAX_SCENE_DIR,
                                         camera=req.camera, drift_m=req.drift_m)
    except (ValueError, RuntimeError, KeyError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event("api", "localize/render", f"{req.camera}: fix err {res['error_m']} m, {res['n_inliers']} inliers")
    return {"ok": True, **res}


@router.post("/structure")
def post_structure(req: StructureRequest, _auth: None = Depends(require_auth)):
    """Decompose a named structure (Landing Pad / Haul Road / Berm / ...) at (x,y) into mass-balanced
    cut/fill orders (structures.decompose). Returns orders the build queue can adopt."""
    from leap import structures as ST
    if len(req.params or {}) > 32:                      # N8: cap the param dict (decompose also rejects unknown keys)
        return JSONResponse(status_code=400, content={"ok": False, "error": "too many structure params (max 32)"})
    try:
        orders = ST.decompose(req.name, req.x, req.y, **(req.params or {}))
    except (ValueError, TypeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "name": req.name, "orders": orders}


@router.post("/sense")
def post_sense(req: SenseRequest, _auth: None = Depends(require_auth)):
    """Drum-fill sensing (ICE-RASSOR): true drum mass -> motor-current observable -> inferred mass +
    offload decision. `noise_frac` toggles seeded sensor noise (0 = OFF)."""
    from lode import mission_planner as MP
    cap = req.capacity_kg if req.capacity_kg is not None else float(MP.RM.REGOLITH_PER_CYCLE_KG)
    grid = [cap * f for f in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0)]
    sensor = MP.RM.DrumSensor.calibrated(grid, capacity_kg=cap, noise_frac=req.noise_frac, seed=req.seed)
    current = sensor.current(req.true_mass_kg)
    inferred = sensor.infer(current)
    dec = sensor.offload(inferred)
    return {
        "ok": True, "true_mass_kg": req.true_mass_kg, "current_a": current, "inferred_kg": inferred,
        "uncertainty_frac": dec.uncertainty_frac, "lower_kg": dec.lower_kg, "upper_kg": dec.upper_kg,
        "capacity_kg": cap, "offload": dec.offload, "noise_frac": req.noise_frac,
    }


@router.post("/render")
def post_render(req: RenderRequest, _auth: None = Depends(require_auth)):
    """Crop a Haworth window at the picked (u,v), plan a flatten, render BEFORE/AFTER in Godot, and
    return the figure URL + earthwork volumes. Slow (two Godot renders); 503 if the binary is absent."""
    from stewie.specs import config as CFG
    PRP = _load_prp()
    if PRP is None:
        return JSONResponse(status_code=503,
                            content={"ok": False, "error": "render pipeline unavailable (Godot binary absent)"})
    prune_reports()
    reports = CFG.reports_dir()
    stem = "render_" + hashlib.sha1(f"{req.u:.4f}_{req.v:.4f}_{req.pad_frac:.2f}".encode()).hexdigest()[:10]
    try:
        with report_lock:
            r = PRP.render_map_area(_HAWORTH, req.u, req.v, os.path.join(reports, stem),
                                    pad_frac=req.pad_frac, mission_t_s=req.mission_t_s)
    except Exception as e:                              # noqa: BLE001 -- render failure -> honest 500
        log.exception("render failed for (u=%s, v=%s)", req.u, req.v)
        return JSONResponse(status_code=500, content={"ok": False, "error": f"render failed: {e}"})
    fig_name = stem + ".png"
    shutil.copyfile(r["figure"], os.path.join(reports, fig_name))
    return {
        "ok": True, "figure": "/reports/" + fig_name,
        "cut_vol_m3": round(r["cut_vol_m3"], 2), "fill_vol_m3": round(r["fill_vol_m3"], 2),
        "cut_kg": round(r["cut_kg"]), "extent_m": round(r["extent_m"], 1), "cell_m": round(r["cell_m"], 2),
    }
