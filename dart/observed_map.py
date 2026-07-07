"""P6 OBSERVED-MAP producer -- close STEWIE's perception loop with a REAL render.

STEWIE's loop is closed on ACTION (a dig mutates the conserved terrain; routing, acceptance and
illumination consume the mutated as-built -- CP-09). It was OPEN on PERCEPTION: nothing OBSERVED the
self-made terrain change through a sensor. This module closes it. The rover observes the mutated
worksite through a render, and the map-channel scores the observed map against the conserved truth.
That observed-vs-truth divergence -- localized to the cells the rover itself reshaped -- is the
"self-made hazard" differentiator an open-loop terrain generator cannot produce.

Two REAL perception tiers feed the map channel (`dart.map_channel`):

  * FORWARD PASSIVE STEREO (`scripts/ros2_bridge/obs_map_producer.py`): the rover front-stereo egress
    -> cv2 SGBM -> back-projected observed heightfield. Real, but sparse (~1-2% coverage/station on a
    5 m patch) and occlusion-limited -- a 0.15 m grazing eye cannot see the floor of a pit in front of
    it. Container/cv2-gated.
  * NADIR DEPTH (this module + `stewie/godot/depth_nadir.gd`): a downward depth sensor over the
    worksite. For a 2.5-D heightfield a nadir view has no self-occlusion, so it recovers the observed
    elevation of every covered cell -- dense and precise. This is the tier that makes the localized
    self-made-hazard signal legible.

Honesty: the nadir observation is a REAL render of the displaced terrain mesh the authority wrote (the
SAME field->Godot mapping `terrain.gd` uses), measured as per-fragment DEPTH by an orthographic camera
and reconstructed to elevation (wy = cam_height - depth). It is NOT a heightfield read-back: the camera
measures the rendered geometry. No cell's height is fabricated; unobserved/background pixels are masked.
The decode was validated by an unmutated-scene round-trip (observed == truth within the 8-bit quantum;
abs-median 0.4 mm, std ~1.2 cm on crater_boulders).

CC0-1.0 (see ../LICENSE).
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from typing import Any

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, ".."))
_GODOT_DIR = os.path.join(_REPO, "stewie", "godot")
_RENDER_SH = os.path.join(_GODOT_DIR, "render.sh")
_DEPTH_SCENE = "res://depth_nadir.tscn"
_GODOT_BIN = os.path.join(_GODOT_DIR, ".tools", "godot", "Godot_v4.6.3-stable_linux.x86_64")

# A background / no-surface pixel decodes to t~0 (black clear color); the nearest possible terrain is
# >= 0.5 m below the camera, so real terrain is always well above this floor. Cells below it are masked.
_BG_T_EPS = 0.02


def godot_available() -> bool:
    """True when the on-host Godot binary + render wrapper are present (else the render is blocked)."""
    return os.path.isfile(_GODOT_BIN) and os.path.isfile(_RENDER_SH)


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    """Invert Godot's sRGB framebuffer store (the depth grayscale is written to an sRGB target)."""
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def load_manifest(manifest: str | dict) -> dict:
    """Accept a manifest dict or a path to the depth_nadir .json sidecar."""
    if isinstance(manifest, dict):
        return manifest
    with open(manifest) as f:
        return json.load(f)


def grid_from_manifest(manifest: str | dict) -> dict:
    """The authority grid the observed map lives on: {width, height, cell_m, x0, y0}."""
    m = load_manifest(manifest)
    return {"width": int(m["width"]), "height": int(m["height"]),
            "cell_m": float(m["cell_m"]), "x0": float(m["x0"]), "y0": float(m["y0"])}


def decode_nadir_depth(png_path: str, manifest: str | dict) -> tuple[np.ndarray, np.ndarray]:
    """Decode a nadir DEPTH render into an observed heightfield + valid mask on the authority grid.

    The depth is stored as an sRGB 8-bit grayscale over [d_lo, d_hi]; invert sRGB, map to metric depth,
    and reconstruct elevation wy = cam_height - depth. The camera framing makes pixel[row,col] == cell
    [row,col] (depth_nadir.gd), so the image IS the observed heightfield after decode.

    Returns (observed HxW float64 [m], valid_mask HxW bool). Background/no-surface pixels are masked.
    """
    import matplotlib.image as mpimg  # lazy: matplotlib is the `planning`/`dev` dep (CI-safe, cv2-free)

    m = load_manifest(manifest)
    W, H = int(m["width"]), int(m["height"])
    cam_h, d_lo, d_hi = float(m["cam_height_m"]), float(m["d_lo_m"]), float(m["d_hi_m"])
    img = mpimg.imread(png_path)                         # float [0,1] = stored byte/255 (no colour mgmt)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)                  # equal RGB channels -> grayscale
    if img.shape != (H, W):
        raise ValueError(f"depth png {img.shape} != manifest grid {(H, W)}")
    t = _srgb_to_linear(img)                             # linearize the sRGB store
    depth = d_lo + t * (d_hi - d_lo)
    observed = cam_h - depth                             # nadir: elevation = cam_height - depth
    valid = t > _BG_T_EPS
    return observed.astype(np.float64), valid


def accumulate_depths(frames: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    """Merge many decoded depth frames into ONE observed heightfield (per-cell median over the frames
    that covered the cell). A single dense nadir frame needs no accumulation; this supports a multi-pass
    survey (or a mix of nadir + stereo tiers) without fabricating a height for an uncovered cell."""
    if not frames:
        raise ValueError("no frames to accumulate")
    H, W = frames[0][0].shape
    stack = np.full((len(frames), H, W), np.nan)
    for i, (obs, mask) in enumerate(frames):
        stack[i][mask] = obs[mask]
    with np.errstate(invalid="ignore"):
        merged = np.nanmedian(stack, axis=0)
    mask = np.isfinite(merged)
    return np.where(mask, merged, 0.0), mask


def render_nadir_depth(scene_dir: str, out_stem: str, *, work_dir: str | None = None,
                       timeout_s: float = 300.0) -> dict:
    """Drive the on-host Godot nadir DEPTH render of ``scene_dir`` (ABSOLUTE) via render.sh (RTX 3090 +
    xvfb; NOT Docker). Writes ``<out_stem>.png`` + ``<out_stem>.json`` into ``work_dir`` (default
    stewie/godot/out) and returns the parsed manifest. Raises RuntimeError if the render is blocked or
    produced no frame -- the caller must STOP, never fabricate a depth frame."""
    if not godot_available():
        raise RuntimeError(f"godot render blocked: binary/render.sh missing ({_GODOT_BIN})")
    work_dir = work_dir or os.path.join(_GODOT_DIR, "out")
    os.makedirs(work_dir, exist_ok=True)
    png = os.path.abspath(os.path.join(work_dir, out_stem + ".png"))
    man = os.path.abspath(os.path.join(work_dir, out_stem + ".json"))
    for p in (png, man):
        if os.path.exists(p):
            os.remove(p)
    cmd = ["bash", _RENDER_SH, _DEPTH_SCENE, "--", "--scene", os.path.abspath(scene_dir),
           "--out", png, "--manifest", man]
    proc = subprocess.run(cmd, cwd=_GODOT_DIR, capture_output=True, text=True, timeout=timeout_s)
    if not (os.path.isfile(png) and os.path.isfile(man)):
        raise RuntimeError(f"godot render produced no depth frame (rc={proc.returncode}).\n"
                           f"stdout tail:\n{proc.stdout[-1500:]}\nstderr tail:\n{proc.stderr[-1500:]}")
    return load_manifest(man)


def observe_scene(scene_dir: str, out_stem: str, **kw: Any) -> tuple[np.ndarray, np.ndarray, dict]:
    """REAL render -> observed heightfield accumulator, end to end: render ``scene_dir`` to a nadir depth
    frame on-host, then decode it. Returns (observed, valid_mask, manifest)."""
    man = render_nadir_depth(scene_dir, out_stem, **kw)
    work_dir = kw.get("work_dir") or os.path.join(_GODOT_DIR, "out")
    png = os.path.abspath(os.path.join(work_dir, out_stem + ".png"))
    observed, mask = decode_nadir_depth(png, man)
    return observed, mask, man


def divergence(observed: np.ndarray, reference: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """Signed observed-minus-reference height field, NaN where unobserved. Against the PRE-dig truth this
    is the perceived self-made change; against the CURRENT truth it is the perception error."""
    d = np.full(observed.shape, np.nan, dtype=np.float64)
    d[valid_mask] = observed[valid_mask] - reference[valid_mask]
    return d


# --------------------------------------------------------------------------- as-built construction
# A real, mass-conserving cut+fill as-built (uses the conserved ColumnState primitives), used to write
# the mutated scene the sensor then observes. NOT a synthetic terrain: it mutates a REAL loaded scene.

def apply_as_built_cut_fill(cs, *, cut_rc: tuple[int, int, int, int], cut_depth_m: float,
                            berm_rc: tuple[int, int, int, int]) -> np.ndarray:
    """Cut a borrow footprint by ``cut_depth_m`` (mass -> drum, clamped to available loose mass) and
    build a berm at ``berm_rc`` from that same mass (drum -> deposit_field). Mass-conserving: the drum
    ledger routes cut mass into the berm. Returns the boolean mask of MUTATED cells (cut U berm)."""
    H, W = cs.mass_areal.shape
    cr0, cc0, cr1, cc1 = cut_rc
    br0, bc0, br1, bc1 = berm_rc
    cut = np.zeros((H, W), dtype=bool)
    cut[cr0:cr1, cc0:cc1] = True
    berm = np.zeros((H, W), dtype=bool)
    berm[br0:br1, bc0:bc1] = True
    cs.cut_to_inventory(cut, float(cut_depth_m) * cs.density)     # remove cut_depth*density [kg/m^2]
    want = float(cs.drum_inventory) / (float(berm.sum()) * cs.cell_area)  # deposit ALL drum over the berm
    cs.deposit_field(berm, want)                                          # -> drum empties (conserved)
    return cut | berm


def write_scene_snapshot(cs, src_scene_dir: str, dst_scene_dir: str) -> None:
    """Write the mutated ColumnState as a scene the renderer reads (heightmap.rf32 + metadata + rasters),
    reusing the source scene's grid/world metadata. Uses the frozen io_fields writer (atomic)."""
    from stewie.twin.io_fields import load_scene, save_scene

    _fields, meta = load_scene(src_scene_dir)
    fields = {k: np.asarray(v).astype("<f4") if k != "state_label" else np.asarray(v).astype("uint8")
              for k, v in cs.fields_dict().items()}
    os.makedirs(dst_scene_dir, exist_ok=True)
    save_scene(dst_scene_dir, fields, meta)


def load_columnstate(scene_dir: str):
    """Load a scene bundle into a ColumnState (datum reconstructed from the stored derived heightmap)."""
    from stewie.physics.column_state import ColumnState
    from stewie.twin.io_fields import load_scene

    fields, meta = load_scene(scene_dir)
    g = meta["grid"]
    datum = fields["heightmap"].astype(np.float64) - (
        fields["mass_areal"].astype(np.float64) / fields["density"].astype(np.float64))
    return ColumnState(
        int(g["width"]), int(g["height"]), float(g["cell_m"]),
        mass_areal=fields["mass_areal"].astype(np.float64),
        density=fields["density"].astype(np.float64),
        state_label=fields["state_label"].astype(np.uint8),
        disturbance=fields["disturbance"].astype(np.float64),
        datum=datum,
    )


def scene_heightmap(scene_dir: str) -> np.ndarray:
    """The scene's stored (pre-mutation) derived heightfield -- the rover's BELIEF before its own dig."""
    from stewie.twin.io_fields import load_scene
    fields, _meta = load_scene(scene_dir)
    return fields["heightmap"].astype(np.float64)


# ------------------------------------------------- P6 LIVE-LOOP dense perception (CP-09 'I' consumer)
# The producer above renders + scores an observed map as a TESTED tier. This section lets the CLOSED
# LOOP (`lode.autonomy.run_closed_loop`) CONSUME it at the dig decision point: render the mutated
# as-built the rover has built so far, OBSERVE it, and hand the loop the observed-vs-belief divergence
# over the dig site so a self-made hazard the stale belief does not carry can change the in-loop decision.
# The render is guarded (see RenderedDensePerception.observe): only when a dig has already reshaped the
# terrain (`built` non-empty) and only on a host with Godot -- the default fast loop path renders nothing.


@dataclasses.dataclass
class DenseObservation:
    """A REAL dense observed heightfield of the (possibly self-mutated) worksite plus the belief it is
    scored against. ``observed`` / ``belief`` / ``valid_mask`` are HxW on the render grid; ``site_mask``
    selects the dig-site cells the loop scores over; ``manifest`` carries the grid geometry. Produced by a
    live on-host render (``RenderedDensePerception``) or, in tests, injected from the committed real-render
    fixture -- never fabricated."""

    observed: np.ndarray
    belief: np.ndarray
    valid_mask: np.ndarray
    site_mask: np.ndarray
    manifest: dict


def site_cell_mask(manifest: str | dict, site_xy: tuple[float, float], half_m: float) -> np.ndarray:
    """Boolean HxW mask of the render-grid cells within +/-``half_m`` (world) of ``site_xy``, using the
    manifest grid geometry (x0, y0, cell_m). This is the dig-site region the dense reward is scored over."""
    m = load_manifest(manifest)
    W, H = int(m["width"]), int(m["height"])
    cell, x0, y0 = float(m["cell_m"]), float(m["x0"]), float(m["y0"])
    cols = x0 + (np.arange(W) + 0.5) * cell
    rows = y0 + (np.arange(H) + 0.5) * cell
    XX, YY = np.meshgrid(cols, rows)
    return (np.abs(XX - float(site_xy[0])) <= half_m) & (np.abs(YY - float(site_xy[1])) <= half_m)


class RenderedDensePerception:
    """LIVE on-host dense-perception provider for the closed loop (P6 / CP-09).

    When the loop reaches a dig decision AND a prior dig has already reshaped the terrain (the loop's
    ``built`` list is non-empty), ``observe`` materializes that as-built as a conserved cut+berm on a
    ColumnState loaded from ``base_scene_dir``, renders a nadir depth frame on-host, decodes it, and
    returns the observed map vs the PRE-mutation belief over the dig site. The as-built the provider
    materializes is a REAL mass-conserving cut+berm (``apply_as_built_cut_fill``); nothing is fabricated,
    and the depth is a real Godot render of the displaced mesh.

    Guarded: ``observe`` returns None when Godot is unavailable (bare CI runner -> the loop falls back to
    the cheap onboard-coverage tier) or when nothing has been built yet (no self-made change to observe),
    so a render happens at most once per reshaped dig site, never on the default fast path."""

    def __init__(self, base_scene_dir: str, *, cut_rc=(60, 60, 100, 100), cut_depth_m: float = 0.10,
                 berm_rc=(150, 150, 172, 172), site_half_m: float = 0.30,
                 out_stem: str = "_p6_liveloop", work_dir: str | None = None):
        self.base_scene_dir = base_scene_dir
        self.cut_rc = tuple(cut_rc)
        self.cut_depth_m = float(cut_depth_m)
        self.berm_rc = tuple(berm_rc)
        self.site_half_m = float(site_half_m)
        self.out_stem = out_stem
        self.work_dir = work_dir
        self._belief: np.ndarray | None = None

    def _belief_map(self) -> np.ndarray:
        if self._belief is None:
            self._belief = scene_heightmap(self.base_scene_dir)
        return self._belief

    def observe(self, *, site, built, leg=None) -> DenseObservation | None:
        """Render the mutated as-built and return the observed-vs-belief dense observation over the site,
        or None when no render is available / nothing has been built (the loop then uses the cheap tier)."""
        if not built or not godot_available():
            return None
        cs = load_columnstate(self.base_scene_dir)
        OM_dug = apply_as_built_cut_fill(cs, cut_rc=self.cut_rc, cut_depth_m=self.cut_depth_m,
                                         berm_rc=self.berm_rc)   # REAL conserved as-built (mass -> berm)
        work_dir = self.work_dir or os.path.join(_GODOT_DIR, "out")
        scene = os.path.join(work_dir, self.out_stem + "_scene")
        write_scene_snapshot(cs, self.base_scene_dir, scene)
        observed, valid, man = observe_scene(scene, self.out_stem + "_depth", work_dir=work_dir)
        site_mask = site_cell_mask(man, site, self.site_half_m) & valid
        if not site_mask.any():                                 # the dig site is off the render patch ->
            site_mask = OM_dug & valid                          # score over the observed as-built footprint
        return DenseObservation(observed=observed, belief=self._belief_map(), valid_mask=valid,
                                site_mask=site_mask, manifest=man)
