"""Procedural (SYNTHETIC) terrain bundle producer — seed-driven fbm_global generator.

SEGREGATION GUARDRAIL (the whole point of this module). It produces SYNTHETIC terrain: a heightmap
drawn from the deterministic global-lattice fbm engine (``procgen_seed.fbm_global`` /
``coord_seed``), NOT a real lunar DEM. Every bundle it writes is therefore, without exception:

  * UNMISTAKABLY LABELLED synthetic. ``metadata.dem_provenance`` is
    ``{"source": "PROCEDURAL — STEWIE fbm_global (coord_seed)", "synthetic": true,
    "world_seed": N, "params": {...}, "citation": null}`` — the citation is ALWAYS ``null``,
    NEVER a real reference. A top-level ``metadata.synthetic = true`` mirrors it for consumers
    that only look shallow.
  * SEGREGATED from the real pipeline. Bundles are written under ``out/procedural_sandbox/``,
    NEVER ``samples/lunar_dem/`` (the producer REFUSES a samples/lunar_dem destination), and
    ``dart.dem_site_compare`` filters synthetic bundles out of the real cross-site table, so a
    procedural bundle can never enter a comparison that echoes real citations.

REUSE, not reinvention. The heightmap comes from ``procgen_seed.fbm_global`` (the SAME
global-lattice, deviogram-anchored, coordinate-hashed engine the real 2 cm corridor overlay uses),
and the surface is injected via the SAME datum path ``dem_import.dem_to_base`` uses
(``datum = Z - mantle_m``; ``mass_areal = mantle_m * rho``; ``derive_height() == Z``). The result
is a NORMAL INTERFACE.md raster bundle (heightmap + mass_areal + density + disturbance +
state_label + metadata.json), so every Python / Godot consumer loads it UNCHANGED — the ONLY
differences from a real bundle are the provenance block (synthetic / citation null) and the
``out/`` location.

Determinism. ``generate_procedural_bundle`` is a pure function of (world_seed, params, extent_m,
cell_m, origin, base_elevation) — the same inputs produce byte-identical rasters and a
byte-identical ``metadata.json`` (no timestamps, no host paths in the metadata). ``world_seed`` is
the single re-roll knob; a different seed yields different terrain over the same coordinates.

Pure NumPy + stdlib; reuses procgen_seed / column_state / io_fields. Modifies none of the frozen
seams (io_fields is used as a library exactly as a real bundle uses it).
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from stewie.specs import constants as K
from stewie.terrain import procgen_seed
from stewie.physics.column_state import ColumnState
from stewie.twin.io_fields import save_scene, write_hillshade_png, write_preview_png

# repo root from stewie/terrain/procedural_bundle.py -> stewie/terrain -> stewie -> <repo>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The ONE sanctioned destination root for procedural bundles (contract: segregated from
#: samples/lunar_dem/). A relative out_dir is resolved under this; an absolute out_dir is
#: honoured but still guarded against a samples/lunar_dem destination.
PROCEDURAL_SANDBOX_ROOT = os.path.join(_REPO_ROOT, "out", "procedural_sandbox")

#: The fixed provenance SOURCE string. dem_site_compare / any citation-echoing surface keys off
#: ``dem_provenance.synthetic``; this string is the human-facing tag.
PROCEDURAL_SOURCE = "PROCEDURAL — STEWIE fbm_global (coord_seed)"

#: Default generator parameters (all TUNABLE by the setup screen; see PROCEDURAL_PARAM_KEYS).
#: These are deliberately synthetic magnitudes (no sourced provenance) — a legible rolling-relief
#: patch at the sim's 2 cm fine cell.
DEFAULT_PARAMS: dict[str, float | int] = {
    "H": 0.9,                     # Hurst / roughness exponent (procgen_seed.fbm_global H)
    "feature_wavelength_m": 40.0,  # octave-0 feature wavelength (base_wavelength_m)
    "amplitude_m": 8.0,            # target surface roughness: sample std ~ amplitude_m (nu0=amp^2)
    "octaves": 6,                  # fbm octaves
}

#: The exact param keys the setup-screen JSON config must supply (order is documentation only).
PROCEDURAL_PARAM_KEYS = ("H", "feature_wavelength_m", "amplitude_m", "octaves")

#: fbm lacunarity is fixed at 2 (octave wavelength halves each octave) — not a setup-screen knob;
#: it is the standard fbm doubling the Hurst gain assumes (procgen_seed.fbm_global default).
_LACUNARITY = 2.0


def procedural_provenance(world_seed: int, params: dict[str, Any]) -> dict[str, Any]:
    """The SYNTHETIC provenance block for a procedural bundle (the guardrail's core).

    ``citation`` is ALWAYS ``None`` and ``synthetic`` ALWAYS ``True`` — a procedural bundle must
    never carry a real citation (contract). ``world_seed`` + ``params`` make the bundle fully
    reproducible from its own metadata.
    """
    return {
        "source": PROCEDURAL_SOURCE,
        "synthetic": True,
        "world_seed": int(world_seed),
        "params": _normalize_params(params),
        "citation": None,
        "frame": "SYNTHETIC local metric frame (NOT a real lunar projection); no georeference",
        "license_basis": "generated content — no external data, no citation, CC0 by construction",
    }


def _normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate + coerce the 4 generator params to their canonical types (deterministic metadata).

    Missing keys fall back to ``DEFAULT_PARAMS``; unknown keys are dropped so the metadata is a
    stable, minimal record. Raises ``ValueError`` on a non-positive wavelength/amplitude/octaves or
    an out-of-range Hurst (procgen_seed uses H in (0, 1]).
    """
    p = dict(DEFAULT_PARAMS)
    for k in PROCEDURAL_PARAM_KEYS:
        if k in params and params[k] is not None:
            p[k] = params[k]
    H = float(p["H"])
    wl = float(p["feature_wavelength_m"])
    amp = float(p["amplitude_m"])
    octaves = int(p["octaves"])
    if not (0.0 < H <= 1.0):
        raise ValueError(f"procedural params: H must be in (0, 1], got {H}")
    if wl <= 0.0:
        raise ValueError(f"procedural params: feature_wavelength_m must be > 0, got {wl}")
    if amp < 0.0:
        raise ValueError(f"procedural params: amplitude_m must be >= 0, got {amp}")
    if octaves < 1:
        raise ValueError(f"procedural params: octaves must be >= 1, got {octaves}")
    return {"H": H, "feature_wavelength_m": wl, "amplitude_m": amp, "octaves": octaves}


def _resolve_out_dir(out_dir: str) -> str:
    """Resolve + GUARD the destination: a relative path lands under PROCEDURAL_SANDBOX_ROOT; any
    path that would write into ``samples/lunar_dem`` is REFUSED (synthetic must never live beside
    the real bundles the cross-site table reads)."""
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(PROCEDURAL_SANDBOX_ROOT, out_dir)
    norm = os.path.normpath(os.path.abspath(out_dir))
    if os.path.join("samples", "lunar_dem") in norm:
        raise ValueError(
            f"procedural bundle destination {norm!r} is under samples/lunar_dem — REFUSED. "
            "Synthetic terrain must be segregated in out/procedural_sandbox/ (guardrail).")
    return norm


def generate_procedural_fields(*, world_seed: int, params: dict[str, Any],
                               extent_m: float, cell_m: float,
                               world_x0: float = 0.0, world_y0: float = 0.0,
                               base_elevation_m: float = 0.0
                               ) -> tuple[ColumnState, dict[str, Any]]:
    """Generate a procedural surface as a mass-conserving ``ColumnState`` (the datum path).

    The heightmap is ``base_elevation_m + fbm_global(...)``: a zero-mean, variance-anchored
    (``nu0 = amplitude_m**2`` so the sample std ~ ``amplitude_m`` — physical roughness, NOT a
    min-max renorm) global-lattice fbm relief, offset by a constant base elevation. The surface is
    injected via the SAME datum path ``dem_import.dem_to_base`` uses so the bundle is a normal
    conserved scene: ``datum = Z - Z_T``, ``mass_areal = Z_T * rho``, ``density = rho`` (uniform
    surface density), ``state_label = VIRGIN``, ``disturbance = 0`` — and ``derive_height() == Z``
    exactly.

    Deterministic in (world_seed, params, extent_m, cell_m, world_x0, world_y0, base_elevation_m).

    Returns ``(cs, resolved_params)`` where ``cs.derive_height()`` is the procedural heightmap and
    ``resolved_params`` is the canonicalized param dict (for the metadata record).
    """
    p = _normalize_params(params)
    n = int(round(float(extent_m) / float(cell_m)))
    if n <= 0:
        raise ValueError(f"procedural: extent_m/cell_m must give a positive grid, got n={n}")

    amp = float(p["amplitude_m"])
    relief = procgen_seed.fbm_global(
        float(world_x0), float(world_y0), n, float(cell_m),
        H=float(p["H"]), nu0=amp * amp, world_seed=int(world_seed),
        octaves=int(p["octaves"]), base_wavelength_m=float(p["feature_wavelength_m"]),
        lacunarity=_LACUNARITY, base_cell_class=0)
    Z = float(base_elevation_m) + relief   # the procedural heightmap [m]

    # Datum-path surface injection (identical seam to dem_import.dem_to_base): a thin cm-scale
    # loose mantle (Z_T at RHO_SURFACE) on top of a datum that carries everything below it, so
    # derive_height() == Z and mass is conserved by construction.
    mantle_m = float(K.Z_T)
    rho = float(K.RHO_SURFACE)
    datum = Z - mantle_m
    mass_areal = np.full((n, n), mantle_m * rho, dtype=np.float64)
    density = np.full((n, n), rho, dtype=np.float64)
    state_label = np.zeros((n, n), dtype=np.uint8)     # VIRGIN (enum 0)
    disturbance = np.zeros((n, n), dtype=np.float64)

    cs = ColumnState(width=n, height=n, cell_m=float(cell_m),
                     mass_areal=mass_areal, density=density, datum=datum,
                     state_label=state_label, disturbance=disturbance)

    # Assert the datum-path round-trip reproduces the intended surface (contract; matches
    # dem_to_base's own >1e-3 m guard).
    err = float(np.max(np.abs(cs.derive_height() - Z)))
    if err > 1e-6:
        raise AssertionError(
            f"procedural datum-path injection deviates from the fbm surface by {err:.3e} m")
    return cs, p


def build_procedural_metadata(*, name: str, cs: ColumnState, world_seed: int,
                              params: dict[str, Any], extent_m: float, cell_m: float,
                              world_x0: float = 0.0, world_y0: float = 0.0,
                              fine_cell_m: float = 0.02) -> dict[str, Any]:
    """The INTERFACE.md metadata for a procedural bundle (mirrors a real bundle's SHAPE, with the
    SYNTHETIC provenance/segregation markers). Deterministic (no timestamps / host paths)."""
    surf = cs.derive_height()
    hmin, hmax = float(surf.min()), float(surf.max())
    x0 = float(world_x0)
    y0 = float(world_y0)
    x1 = round(x0 + cs.width * float(cell_m), 4)
    y1 = round(y0 + cs.height * float(cell_m), 4)
    meta: dict[str, Any] = {
        "schema_version": "1.0",
        "scene_name": f"procedural_sandbox/{name}",
        "producer": "stewie.terrain.procedural_bundle (SYNTHETIC fbm_global generator)",
        # TOP-LEVEL synthetic flag (shallow consumers) + the full provenance block below.
        "synthetic": True,
        "grid": {"width": cs.width, "height": cs.height, "cell_m": float(cell_m),
                 "order": "row-major-C"},
        "world_bounds_m": {"x0": round(x0, 4), "y0": round(y0, 4), "x1": x1, "y1": y1},
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
        "base_cell_m": float(cell_m),
        "fine_cell_m": float(fine_cell_m),
        "region": "PROCEDURAL_SANDBOX",
        "local_datum_offset_m": 0.0,
        "regolith_model": {
            "uniform_mantle": True,
            "mantle_thickness_m": float(K.Z_T),
            "mantle_density_kg_m3": round(float(K.RHO_SURFACE), 4),
            "mantle_density_source": "uniform RHO_SURFACE (synthetic; no sourced density profile)",
            "mantle_areal_kg_m2": round(float(K.Z_T * K.RHO_SURFACE), 4),
            "note": "SYNTHETIC surface injected via the datum path: datum=Z-Z_T, "
                    "mass_areal=Z_T*rho, derive_height()==Z. rho is a uniform stand-in "
                    "(no real density model on synthetic terrain).",
        },
        "dem_provenance": procedural_provenance(world_seed, params),
        "features": ["procedural_fbm"],
        "contract_revision": "1.0.2",
        "notes": "SYNTHETIC procedural terrain generated by stewie.terrain.procedural_bundle via "
                 "procgen_seed.fbm_global (coordinate-hashed, variance-anchored). NOT a real lunar "
                 "DEM; carries NO citation; segregated under out/procedural_sandbox/. "
                 "world_seed is the re-roll knob; deterministic in seed+params+coords.",
    }
    return meta


def generate_procedural_bundle(out_dir: str, *, world_seed: int,
                               params: dict[str, Any] | None = None,
                               extent_m: float = 256.0, cell_m: float = 1.0,
                               world_x0: float = 0.0, world_y0: float = 0.0,
                               base_elevation_m: float = 0.0,
                               fine_cell_m: float = 0.02,
                               write_previews: bool = True
                               ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Generate + WRITE a full procedural bundle to ``out_dir`` (SYNTHETIC, segregated, deterministic).

    ``out_dir`` (relative -> under ``out/procedural_sandbox/``; a ``samples/lunar_dem`` destination
    is REFUSED) receives a normal INTERFACE.md raster bundle: ``heightmap.rf32`` /
    ``mass_areal.rf32`` / ``density.rf32`` / ``disturbance.rf32`` / ``state_label.r8`` +
    ``metadata.json`` (SYNTHETIC provenance) via the frozen ``io_fields.save_scene``, plus optional
    hillshade/height previews. Godot's ``viz2.sh --site <out_dir>`` renders it exactly like a real
    bundle (uniform loader).

    Returns ``(fields, meta)`` where ``fields`` is the written raster dict (heightmap derived) and
    ``meta`` is the metadata written to disk. Same inputs -> byte-identical bundle.
    """
    params = params or dict(DEFAULT_PARAMS)
    resolved = _resolve_out_dir(out_dir)
    name = os.path.basename(os.path.normpath(resolved))

    cs, p = generate_procedural_fields(
        world_seed=world_seed, params=params, extent_m=extent_m, cell_m=cell_m,
        world_x0=world_x0, world_y0=world_y0, base_elevation_m=base_elevation_m)
    meta = build_procedural_metadata(
        name=name, cs=cs, world_seed=world_seed, params=p, extent_m=extent_m, cell_m=cell_m,
        world_x0=world_x0, world_y0=world_y0, fine_cell_m=fine_cell_m)

    os.makedirs(resolved, exist_ok=True)
    fields = cs.fields_dict()
    save_scene(resolved, fields, meta)

    if write_previews:
        surf = cs.derive_height()
        write_hillshade_png(surf, os.path.join(resolved, "preview_hillshade.png"),
                            float(cell_m), altdeg=K.SUN_ELEVATION_DEG_POLAR,
                            title=f"SYNTHETIC {name} hillshade (seed={world_seed}, grazing sun "
                                  f"{K.SUN_ELEVATION_DEG_POLAR}deg)")
        write_preview_png(surf, os.path.join(resolved, "preview_height.png"),
                          cmap="terrain",
                          title=f"SYNTHETIC {name} height [m] (seed={world_seed})")
    return fields, meta
