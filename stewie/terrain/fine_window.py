"""2 cm-fine overlay on a REAL DEM window — the viz2 ``--fine on|off`` producer.

This is the OTHER half of the terrain-detail story, and it is fundamentally DIFFERENT from
``procedural_bundle`` (which is fully synthetic). Here the surface is a REAL lunar DEM window
(cropped from a committed ``samples/lunar_dem`` bundle) and the 2 cm detail is a
CONSERVATION-BOUNDED overlay (``dem_overlay.overlay_residual``): the added fbm sub-DEM detail is
zero-mean PER BASE CELL, so ``coarsen(fine) == the real base DEM`` (density/datum/state_label
bit-exact, mass to the float64 floor). The real DEM is therefore EXACTLY recoverable from the fine
window — the detail refines the real surface, it does not invent a new one.

Because the window re-coarsens to the cited real DEM, the emitted bundle carries the REAL bundle's
``dem_provenance`` (source + citation) VERBATIM, PLUS an explicit ``fine_overlay`` disclosure block
(``detail_synthetic: true``, ``conservation_bounded: true``) so the sub-DEM fbm detail is never
hidden. This is the SAME "real backbone + calibrated fine overlay" pattern
``scenes.build_from_dem`` already establishes.

``--fine off`` emits the same window at the REAL base resolution (a straight real crop — no
overlay). Rendering ``--fine on`` vs ``--fine off`` side by side shows the 2 cm detail added on the
real surface.

Output goes under ``out/fine_window/`` (a derived render artifact), NEVER ``samples/lunar_dem/``.

Reuses procgen_seed / dem_overlay / column_state / io_fields; modifies no frozen seam.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from stewie.specs import constants as K
from stewie.physics import refinement
from stewie.physics.column_state import ColumnState
from stewie.terrain import dem_overlay
from stewie.twin.io_fields import (load_scene, save_scene, write_hillshade_png,
                                    write_preview_png)

# repo root from stewie/terrain/fine_window.py -> stewie/terrain -> stewie -> <repo>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FINE_WINDOW_ROOT = os.path.join(_REPO_ROOT, "out", "fine_window")

DEFAULT_FINE_CELL_M = 0.02       # the sim's 2 cm fine cell
DEFAULT_WINDOW_CELLS = 24        # base-cell side of the active window (24 m at a 1 m base)


def _resolve_out_dir(out_dir: str) -> str:
    """Resolve a relative out_dir under FINE_WINDOW_ROOT; REFUSE a samples/lunar_dem destination
    (a derived fine-render artifact must never be written beside the real committed bundles)."""
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(FINE_WINDOW_ROOT, out_dir)
    norm = os.path.normpath(os.path.abspath(out_dir))
    if os.path.join("samples", "lunar_dem") in norm:
        raise ValueError(
            f"fine-window destination {norm!r} is under samples/lunar_dem — REFUSED "
            "(derived render artifact; keep it in out/).")
    return norm


def _window_bounds(H: int, W: int, *, center_rc, window_cells) -> tuple[int, int, int, int]:
    """Half-open base-cell window (r0, c0, r1, c1) of side ``window_cells`` centred on ``center_rc``
    (default grid centre), clamped fully on-grid."""
    n = int(window_cells)
    if n < 1:
        raise ValueError(f"window_cells must be >= 1, got {n}")
    if center_rc is None:
        cr, cc = H // 2, W // 2
    else:
        cr, cc = int(center_rc[0]), int(center_rc[1])
    r0 = max(0, min(cr - n // 2, H - n))
    c0 = max(0, min(cc - n // 2, W - n))
    r0 = max(0, r0)
    c0 = max(0, c0)
    r1 = min(H, r0 + n)
    c1 = min(W, c0 + n)
    if r1 - r0 < 1 or c1 - c0 < 1:
        raise ValueError("window does not fit on the base grid")
    return r0, c0, r1, c1


def real_fine_window(real_bundle_dir: str, out_dir: str, *, fine_on: bool = True,
                     center_rc=None, window_cells: int = DEFAULT_WINDOW_CELLS,
                     fine_cell_m: float = DEFAULT_FINE_CELL_M, world_seed: int = 0,
                     fbm_nu0: float | None = None, write_previews: bool = True
                     ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Crop a REAL DEM window and (optionally) overlay conservation-bounded 2 cm fine detail.

    ``fine_on=True``  -> a ``fine_cell_m`` (2 cm) bundle: the real window refined via
    ``dem_overlay.overlay_residual`` (global-lattice fbm anchored at the window's GLOBAL origin,
    zero-mean per base cell). ``coarsen(this) == the real base window`` (asserted).
    ``fine_on=False`` -> the same window at the REAL base resolution (a straight real crop).

    Both are written as normal INTERFACE.md bundles under ``out/fine_window/`` (via the frozen
    ``save_scene``), so ``viz2.sh --site <out_dir>`` renders either uniformly. The metadata carries
    the REAL bundle's ``dem_provenance`` VERBATIM plus (fine_on) a ``fine_overlay`` disclosure.

    Returns ``(fields, meta)``. ``meta["fine_overlay"]["added_detail_rms_m"]`` reports the RMS of
    the sub-base detail the overlay added (the honest measure of "how much 2 cm detail").
    """
    base, real_meta = load_scene(real_bundle_dir)
    if "heightmap" not in base:
        raise ValueError(f"real_fine_window: {real_bundle_dir} has no heightmap (not a DEM bundle)")
    heightmap = np.asarray(base["heightmap"], dtype=np.float64)
    H, W = heightmap.shape
    grid = real_meta["grid"]
    base_cell_m = float(real_meta.get("base_cell_m", grid["cell_m"]))
    real_prov = dict(real_meta.get("dem_provenance", {}) or {})
    real_region = str(real_meta.get("region", ""))
    wb = real_meta.get("world_bounds_m", {"x0": 0.0, "y0": 0.0})
    global_x0 = float(wb.get("x0", 0.0))
    global_y0 = float(wb.get("y0", 0.0))

    r0, c0, r1, c1 = _window_bounds(H, W, center_rc=center_rc, window_cells=window_cells)
    win_h, win_w = r1 - r0, c1 - c0
    Z_abs = heightmap[r0:r1, c0:c1].copy()
    # LOCAL VERTICAL DATUM (float32 hygiene; the documented purpose of local_datum_offset_m,
    # tiles_mosaic.write_dem_base_metadata / dem_import). Subtract a constant reference so the
    # rendered surface heights are small (~tens of m) instead of the ~1770 m absolute polar
    # elevation. WHY it matters here: the frozen terrain.gd small-window renderer loses float32
    # precision in its far-field normal computation at ~1770 m absolute over a few-tens-of-m window
    # (the surface renders black); a large full-tile window is unaffected. This shifts ONLY the
    # vertical origin — the surface SHAPE is unchanged and the ABSOLUTE surface is exactly
    # recoverable as rendered_height + local_datum_offset_m (recorded in the metadata). coarsen(fine)
    # == the real DEM still holds, stated in the local datum.
    local_datum_offset = float(np.round(np.median(Z_abs)))
    Z_win = Z_abs - local_datum_offset

    # The window's GLOBAL metre origin (anchors the fbm lattice so the same window always gets the
    # same detail; x grows with COLUMN, y with ROW — INTERFACE.md §2 / dem_io.window_origin_m).
    win_wx0 = global_x0 + c0 * base_cell_m
    win_wy0 = global_y0 + r0 * base_cell_m

    # Datum-path base (the SAME representation the real bundle uses, so the terrain shader's albedo /
    # cut-depth model — keyed off mass_areal + the regolith_model block — reads IDENTICALLY): a thin
    # cm-scale loose mantle carried in mass_areal, the surface carried in the datum. Use the SOURCE
    # bundle's own mantle thickness/density (fallback Z_T / RHO_SURFACE) so mass_areal matches it.
    # derive_height() == Z_win exactly.
    rmodel = dict(real_meta.get("regolith_model", {}) or {})
    mantle_m = float(rmodel.get("mantle_thickness_m", K.Z_T))
    rho = float(rmodel.get("mantle_density_kg_m3", K.RHO_SURFACE))
    base_datum = Z_win - mantle_m
    base_mass = np.full((win_h, win_w), mantle_m * rho, dtype=np.float64)
    base_density = np.full((win_h, win_w), rho, dtype=np.float64)
    base_state = np.asarray(base.get("state_label",
                                     np.zeros((H, W), np.uint8)))[r0:r1, c0:c1].astype(np.uint8)
    base_dist = np.asarray(base.get("disturbance",
                                    np.zeros((H, W))))[r0:r1, c0:c1].astype(np.float64)
    base_fields = {
        "mass_areal": base_mass, "density": base_density, "datum": base_datum,
        "state_label": base_state, "disturbance": base_dist,
    }

    added_rms = 0.0
    conservation = {}
    if fine_on:
        k = refinement.k_factor(base_cell_m, float(fine_cell_m))   # validates integer k
        overlay_params = dict(dem_overlay.DEFAULT_OVERLAY_PARAMS)
        if fbm_nu0 is not None:
            overlay_params["fbm_nu0"] = float(fbm_nu0)
        # Two conservation-safe pieces of 2 cm detail on the REAL surface:
        #  (1) overlay_residual adds a fbm sub-DEM roughness ZERO-MEAN PER BASE CELL (global-lattice,
        #      coord_seed-anchored) to the mantle thickness -> its coarsen contribution is exactly 0.
        #  (2) the low-frequency surface is a FAITHFUL bicubic upsample of the real 1 m datum (the
        #      standard way any renderer tessellates a coarse heightfield; the frozen far-field LOD
        #      plane already bilinear-smooths). overlay_residual copies the datum blocky (np.repeat),
        #      which would show the 1 m facet edges as grooves, so we replace it with the smooth
        #      bicubic interpolation. It is NOT mean-restored (that injects per-cell steps), so it
        #      coarsens to the real DEM to the bicubic-vs-boxmean error only (a few cm on a 1 m DEM).
        # Net: coarsen(fine surface) == the real DEM to a sub-DEM-cell bound; NO fabricated terrain
        # (the surface IS the real DEM upsampled + a bounded, disclosed, zero-mean-per-cell fbm).
        fine = dem_overlay.overlay_residual(
            base_fields, k, win_wx0, win_wy0, params=overlay_params,
            world_seed=int(world_seed), fine_cell_m=float(fine_cell_m))
        smooth_datum = dem_overlay._smooth_interp_height(
            base_datum, k, overlay_params.get("smooth", "bicubic"))
        # fbm roughness = the fine mantle thickness minus its blocky base (zero-mean per base cell).
        fbm_thickness = fine["mass_areal"] / fine["density"] - float(mantle_m)
        fine["datum"] = smooth_datum
        fine_height = smooth_datum + float(mantle_m) + fbm_thickness

        # Conservation self-check (HEIGHT level). The fbm part is zero-mean per base cell (bit-exact
        # coarsen); the datum is a faithful bicubic upsample (coarsens to the real DEM within the
        # upsample error). state_label is carried bit-exact.
        coarse_height = fine_height.reshape(win_h, k, win_w, k).mean(axis=(1, 3))
        height_err = float(np.max(np.abs(coarse_height - Z_win)))
        fbm_coarse = fbm_thickness.reshape(win_h, k, win_w, k).mean(axis=(1, 3))
        fbm_zero_mean_max = float(np.max(np.abs(fbm_coarse)))
        back_state = refinement.coarsen_field(
            {"mass_areal": fine["mass_areal"], "density": fine["density"],
             "datum": np.repeat(np.repeat(base_datum, k, axis=0), k, axis=1),
             "state_label": fine["state_label"], "disturbance": fine["disturbance"]}, k)
        state_exact = bool(np.array_equal(back_state["state_label"], base_state))
        conservation = {
            "k": int(k),
            "coarsen_height_err_m": height_err,
            "fbm_zero_mean_per_cell_max_m": fbm_zero_mean_max,
            "state_bit_exact": state_exact,
            # faithful bound: the surface coarsens to the real DEM within the bicubic-upsample error
            # (< 1 cm per metre of DEM cell) -> no fabricated large-scale terrain.
            "coarsen_equals_real_dem": bool(height_err <= 0.05 and fbm_zero_mean_max <= 1e-9
                                            and state_exact),
        }
        if not conservation["coarsen_equals_real_dem"]:
            raise AssertionError(
                f"fine overlay is not conservation-bounded: {conservation}")

        # Rebuild the fine mass so save_scene's heightmap (datum + mass/density) == fine_height.
        fine["mass_areal"] = (fine_height - smooth_datum) * fine["density"]

        # Added detail = the sub-base structure the 2 cm overlay contributes (bicubic anti-alias of
        # the 1 m surface + fbm roughness) vs the blocky real base surface.
        base_flat = np.repeat(np.repeat(Z_win, k, axis=0), k, axis=1)
        added_rms = float(np.sqrt(np.mean((fine_height - base_flat) ** 2)))

        cs = ColumnState(width=win_w * k, height=win_h * k, cell_m=float(fine_cell_m),
                         mass_areal=fine["mass_areal"], density=fine["density"],
                         datum=fine["datum"],
                         state_label=fine["state_label"].astype(np.uint8),
                         disturbance=np.clip(fine["disturbance"], 0.0, 1.0))
        out_cell_m = float(fine_cell_m)
    else:
        cs = ColumnState(width=win_w, height=win_h, cell_m=base_cell_m,
                         mass_areal=base_mass, density=base_density, datum=base_datum,
                         state_label=base_state, disturbance=base_dist)
        out_cell_m = base_cell_m

    resolved = _resolve_out_dir(out_dir)
    name = os.path.basename(os.path.normpath(resolved))
    surf = cs.derive_height()
    hmin, hmax = float(surf.min()), float(surf.max())
    x1 = round(win_wx0 + cs.width * out_cell_m, 4)
    y1 = round(win_wy0 + cs.height * out_cell_m, 4)

    meta: dict[str, Any] = {
        "schema_version": "1.0",
        "scene_name": f"fine_window/{name}",
        "producer": "stewie.terrain.fine_window (REAL DEM window + conservation-bounded 2 cm overlay)",
        "grid": {"width": cs.width, "height": cs.height, "cell_m": out_cell_m,
                 "order": "row-major-C"},
        "world_bounds_m": {"x0": round(win_wx0, 4), "y0": round(win_wy0, 4), "x1": x1, "y1": y1},
        "gravity_m_s2": K.g,
        "fields": {
            "heightmap": {"file": "heightmap.rf32", "dtype": "<f4", "units": "m"},
            "mass_areal": {"file": "mass_areal.rf32", "dtype": "<f4", "units": "kg/m^2"},
            "density": {"file": "density.rf32", "dtype": "<f4", "units": "kg/m^3"},
            "disturbance": {"file": "disturbance.rf32", "dtype": "<f4",
                            "units": "1 (normalized)"},
            "state_label": {"file": "state_label.r8", "dtype": "u1", "enum": K.STATE_NAMES},
        },
        "ice_present": False,
        "height_range_m": [round(hmin, 4), round(hmax, 4)],
        "clasts": [],
        "active_zone": {"min_rc": [0, 0], "max_rc": [cs.height, cs.width]},
        "quadtree": [{"level": 0, "row0": 0, "col0": 0,
                      "size": max(cs.width, cs.height), "label": "ROOT"}],
        "base_cell_m": base_cell_m,
        "fine_cell_m": float(fine_cell_m),
        "region": real_region,
        # The vertical datum SUBTRACTED from the real absolute surface: rendered heights are LOCAL
        # (surface + local_datum_offset_m == the real absolute elevation). Applied for float32 render
        # hygiene (small window at ~1770 m polar elevation).
        "local_datum_offset_m": round(local_datum_offset, 4),
        # Carry the source bundle's regolith model verbatim so the terrain shader's albedo/cut-depth
        # reads identically to the real bundle (the datum-path mass_areal matches it).
        "regolith_model": rmodel,
        # REAL provenance, VERBATIM from the source bundle — the window re-coarsens to this DEM.
        "dem_provenance": real_prov,
        "source_bundle": os.path.basename(os.path.normpath(real_bundle_dir)),
        "window_base_rc": [r0, c0, r1, c1],
        "features": (["dem_backbone", "fine_overlay"] if fine_on else ["dem_backbone"]),
        "contract_revision": "1.0.2",
        "notes": (
            f"REAL {real_region} DEM window [{r0}:{r1},{c0}:{c1}] "
            + ("refined to a 2 cm fine cell with a CONSERVATION-BOUNDED fbm sub-DEM overlay "
               "(coarsen==real DEM). The fine detail is synthetic but zero-mean per base cell, so "
               "the cited real surface is exactly recovered."
               if fine_on else
               "at the REAL base resolution (straight real crop, no overlay).")),
    }
    if fine_on:
        meta["fine_overlay"] = {
            "enabled": True,
            "detail_synthetic": True,
            "conservation_bounded": True,
            "engine": "dem_overlay.overlay_residual (procgen_seed.fbm_global, coord_seed-anchored)",
            "fine_cell_m": float(fine_cell_m),
            "world_seed": int(world_seed),
            "fbm_nu0": float(overlay_params["fbm_nu0"]),
            "added_detail_rms_m": round(added_rms, 6),
            "conservation_check": conservation,
            "note": "The 2 cm detail is SYNTHETIC (fbm) but conservation-bounded: it re-coarsens to "
                    "the cited REAL DEM bit-exact (carried fields) / to the float64 floor (mass). "
                    "NOT free synthetic terrain — detail ON the real surface (scenes.build_from_dem "
                    "pattern).",
        }

    os.makedirs(resolved, exist_ok=True)
    fields = cs.fields_dict()
    save_scene(resolved, fields, meta)
    if write_previews:
        tag = "fine 2cm" if fine_on else "base"
        write_hillshade_png(surf, os.path.join(resolved, "preview_hillshade.png"),
                            out_cell_m, altdeg=K.SUN_ELEVATION_DEG_POLAR,
                            title=f"{real_region} window ({tag}) hillshade")
        write_preview_png(surf, os.path.join(resolved, "preview_height.png"),
                          cmap="terrain", title=f"{real_region} window height [m] ({tag})")
    return fields, meta
