"""Setup-screen preview data for the viz2 stream service (the three.js heightfield previews).

Three pure producers feed the setup screen's live orbitable preview mesh — the SAME frame the
"Launch drive" button then opens in Godot:

  * ``list_real_bundles()`` — the REAL ``samples/lunar_dem/`` bundles for the site dropdown, with
    each site's VERBATIM ``dem_provenance`` citation. It reuses ``dart.dem_site_compare`` so the
    SYNTHETIC-bundle filter is the exact same one the cross-site table uses — a procedural bundle
    can never appear here or lend a real citation.
  * ``real_heightmap_preview(site)`` — a REAL on-disk heightmap, decimated to ~``PREVIEW_N``² for a
    lightweight displacement mesh, carrying the site's REAL citation (guardrail: a real preview
    always shows the real reference).
  * ``procedural_heightmap_preview(seed, params)`` — the SYNTHETIC preview: it runs the REAL
    ``procgen_seed.fbm_global`` engine (the SAME generator ``procedural_bundle`` writes and Godot
    then renders) over a fixed preview window, so the preview matches what the drive will show. It
    is UNMISTAKABLY labelled synthetic (``synthetic: true``, ``citation: null``, ``label:
    "SYNTHETIC"``) per the generator's segregation convention — NEVER a real citation.

Pure NumPy + the real repo producers; no HTTP, no subprocess. ``app.py`` maps the exceptions raised
here (``ValueError`` -> 400, ``FileNotFoundError`` -> 404) onto HTTP responses.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from dart.dem_site_compare import (
    DEFAULT_SITE_ROOT,
    is_synthetic_bundle,
    list_site_bundles,
    provenance_pane,
)
from stewie.terrain import procgen_seed
from stewie.terrain.procedural_bundle import (
    PROCEDURAL_SOURCE,
    _normalize_params,
    procedural_provenance,
)
from stewie.twin.io_fields import load_scene

# ── preview window constants (the three.js setup-screen contract) ─────────────────────────────
#: Preview grid side (fine cells). Both preview kinds return an (N x N) heightfield the mesh
#: displaces from. Small enough to ship as JSON on every debounced param change.
PREVIEW_N = 128
#: Procedural preview cell size [m]. N*CELL = 256 m — the SAME 256 m patch (at world origin) the
#: procedural DRIVE bundle generates (``app._resolve_bundle`` -> extent_m=256, cell_m=1), just
#: sampled coarser. Because ``fbm_global`` is resolution-consistent (a world point reads the same
#: global lattice at any cell size), this 128² preview samples the SAME field the 256² drive bundle
#: will, so the preview matches what Godot renders.
PREVIEW_CELL_M = 2.0
#: fbm lacunarity + resolution class — fixed to ``procedural_bundle``'s own values so the preview's
#: fbm_global call is identical to the bundle's (only the 4 setup-screen params + seed vary).
PREVIEW_LACUNARITY = 2.0
PREVIEW_BASE_CELL_CLASS = 0
#: The procedural preview is evaluated at the world origin (same as the drive bundle's default).
PREVIEW_WORLD_X0 = 0.0
PREVIEW_WORLD_Y0 = 0.0

#: The real-mode default site (mirrors ``protocol.DEFAULT_SITE``; surfaced so the dropdown can
#: pre-select it without importing the protocol module).
DEFAULT_SITE = "haworth_sfs_2km_1m"


def _valid_site_name(site: str) -> str:
    """Reject a path-escaping site (same guard as ``protocol.parse_config``): a real site is a bare
    bundle NAME under ``samples/lunar_dem/``. Raises ``ValueError`` on an unsafe name."""
    s = str(site).strip()
    if not s or "/" in s or "\\" in s or s.startswith("."):
        raise ValueError(f"site must be a bare bundle name, got {site!r}")
    return s


def _bundle_dir(site: str, root: str = DEFAULT_SITE_ROOT) -> str:
    """Resolve + validate a real bundle directory. Raises ``ValueError`` on a bad name /
    ``FileNotFoundError`` on a missing bundle / ``ValueError`` on a synthetic bundle (never
    previewed with a real-citation surface)."""
    s = _valid_site_name(site)
    bundle = os.path.join(root, s)
    if not os.path.isfile(os.path.join(bundle, "metadata.json")):
        raise FileNotFoundError(f"real site {s!r} not found under {root}")
    if is_synthetic_bundle(bundle):
        raise ValueError(f"site {s!r} is a SYNTHETIC bundle — refused on the real-preview path")
    return bundle


def _has_heightmap(bundle: str) -> bool:
    return os.path.isfile(os.path.join(bundle, "heightmap.rf32"))


def _downsample(Z: np.ndarray, n: int) -> np.ndarray:
    """Decimate ``Z`` to at most (n, n) by even index selection (no interpolated/invented heights).

    Uses ``np.linspace`` node picks so the corners (and thus the tile's real extent) are retained;
    a smaller-than-n input is returned as-is. Returns float64 for a clean JSON round-trip."""
    Z = np.asarray(Z)
    h, w = Z.shape
    if h <= n and w <= n:
        return Z.astype(np.float64)
    rows = np.linspace(0, h - 1, min(n, h)).round().astype(np.int64)
    cols = np.linspace(0, w - 1, min(n, w)).round().astype(np.int64)
    return Z[np.ix_(rows, cols)].astype(np.float64)


# ── /bundles — real site dropdown + citations ─────────────────────────────────────────────────

def list_real_bundles(root: str = DEFAULT_SITE_ROOT) -> list[dict[str, Any]]:
    """The real-site dropdown payload: one row per on-disk REAL bundle under ``root`` (synthetic
    bundles EXCLUDED via the shared ``dem_site_compare`` filter), each with its VERBATIM
    ``dem_provenance`` source + citation. ``default`` marks the real-mode default site."""
    rows: list[dict[str, Any]] = []
    for bundle in list_site_bundles(root):
        pane = provenance_pane(bundle)          # name/region/source/citation/frame/license/cell_m
        rows.append({
            "name": pane["name"],
            "region": pane["region"],
            "cell_m": pane["cell_m"],
            "source": pane["source"],
            "citation": pane["citation"],
            "frame": pane["frame"],
            "license_basis": pane["license_basis"],
            "has_heightmap": _has_heightmap(bundle),
            "synthetic": False,
            "default": pane["name"] == DEFAULT_SITE,
        })
    return rows


# ── /preview/heightmap — real, decimated ──────────────────────────────────────────────────────

def real_heightmap_preview(site: str, root: str = DEFAULT_SITE_ROOT,
                           n: int = PREVIEW_N) -> dict[str, Any]:
    """A REAL heightmap decimated to <=``n``² for the setup-screen displacement mesh, with the
    site's REAL citation echoed verbatim.

    ``z`` is the row-major decimated grid in metres; ``z_min``/``z_max`` bound THAT grid (mesh
    scaling). ``full_min_m``/``full_max_m``/``relief_m`` are the FULL on-disk heightmap's real stats
    (they match the bundle's ``height_range_m``). A metadata-only bundle (no ``heightmap.rf32``)
    returns ``has_heightmap: false`` with an empty grid but the citation still present."""
    bundle = _bundle_dir(site, root)
    pane = provenance_pane(bundle)
    out: dict[str, Any] = {
        "site": pane["name"],
        "synthetic": False,
        "region": pane["region"],
        "cell_m": pane["cell_m"],
        "source": pane["source"],
        "citation": pane["citation"],
        "frame": pane["frame"],
        "license_basis": pane["license_basis"],
        "has_heightmap": _has_heightmap(bundle),
        "n": 0,
        "z": [],
    }
    if not _has_heightmap(bundle):
        out["note"] = "metadata-only bundle (no heightmap.rf32) — no mesh preview for this tile"
        return out

    fields, _meta = load_scene(bundle)
    Z = fields["heightmap"]
    grid = _downsample(Z, n)
    full_min, full_max = float(Z.min()), float(Z.max())
    out.update({
        "n": int(grid.shape[0]),
        "ncols": int(grid.shape[1]),
        "z": grid.reshape(-1).tolist(),
        "z_min": float(grid.min()),
        "z_max": float(grid.max()),
        "full_min_m": full_min,
        "full_max_m": full_max,
        "relief_m": full_max - full_min,
        "full_shape": [int(Z.shape[0]), int(Z.shape[1])],
    })
    return out


# ── /preview/procedural — SYNTHETIC, real fbm_global ──────────────────────────────────────────

def procedural_heightmap_preview(world_seed: int,
                                 params: dict[str, Any] | None = None,
                                 n: int = PREVIEW_N) -> dict[str, Any]:
    """The SYNTHETIC setup-screen preview: the REAL ``fbm_global`` field over the fixed preview
    window, UNMISTAKABLY labelled synthetic (``citation: null``, ``label: "SYNTHETIC"``).

    Bit-exact by construction with a direct ``fbm_global`` call using ``_normalize_params(params)``
    and this module's ``PREVIEW_*`` constants — the SAME generator + params the drive bundle uses,
    so the preview matches what Godot will render. Raises ``ValueError`` (via ``_normalize_params``)
    on a bad H / wavelength / amplitude / octaves."""
    p = _normalize_params(params or {})
    amp = float(p["amplitude_m"])
    z = procgen_seed.fbm_global(
        PREVIEW_WORLD_X0, PREVIEW_WORLD_Y0, int(n), PREVIEW_CELL_M,
        H=float(p["H"]), nu0=amp * amp, world_seed=int(world_seed),
        octaves=int(p["octaves"]), base_wavelength_m=float(p["feature_wavelength_m"]),
        lacunarity=PREVIEW_LACUNARITY, base_cell_class=PREVIEW_BASE_CELL_CLASS)
    z = np.asarray(z, dtype=np.float64)
    return {
        "synthetic": True,
        "label": "SYNTHETIC",
        "source": PROCEDURAL_SOURCE,
        "citation": None,
        "provenance": procedural_provenance(int(world_seed), p),
        "world_seed": int(world_seed),
        "params": p,
        "cell_m": PREVIEW_CELL_M,
        "extent_m": round(PREVIEW_CELL_M * int(n), 4),
        "n": int(z.shape[0]),
        "ncols": int(z.shape[1]) if z.ndim == 2 else 0,
        "z": z.reshape(-1).tolist(),
        "z_min": float(z.min()) if z.size else 0.0,
        "z_max": float(z.max()) if z.size else 0.0,
        "std_m": float(z.std()) if z.size else 0.0,
    }
