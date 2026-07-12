"""WS protocol for the viz2 stream service: session config + per-frame input parsing.

Two pure, unit-tested functions define the browser<->server contract (the SAME contract the
future three.js setup screen must speak):

  * ``parse_config(raw)`` — the FIRST WS message, a JSON session config:
        {"mode": "real"|"procedural",
         "site": "<sample bundle name>",     # real mode; default haworth_sfs_2km_1m
         "world_seed": <int>,                # procedural mode
         "params": {H, feature_wavelength_m, amplitude_m, octaves},   # procedural mode
         "fine": 0.05|0.02,                  # runtime fine-cell size (0.02 is gated/heavy)
         "sun": {"az": <deg>, "el": <deg>}}
    Returns a normalized dict with every field resolved to a concrete value.

  * ``normalize_input(msg)`` — every SUBSEQUENT WS message, a control frame relayed to Godot:
        {"v": <-1..1>, "omega": <-1..1>,     # NORMALIZED drive intent (Godot scales to the
                                             #   IPEx envelope via LIVE_LIN/LIVE_ANG, so the
                                             #   runtime M-04 bound is honored on the Godot side)
         "dig": <bool>, "dump": <bool>,      # one-shot conserved excavate/deposit
         "sun_az": <deg>, "sun_el": <deg>}   # optional live sun move
    Non-finite / out-of-range values are dropped or clamped so no NaN/inf ever reaches Godot.

Validation only — no I/O, no subprocess. ``app.py`` owns the process lifecycle.
"""
from __future__ import annotations

import json
import math
from typing import Any

#: The real sample bundles the stream may open (mode=real). Segregated from procedural output.
DEFAULT_SITE = "haworth_sfs_2km_1m"

#: Fine-cell sizes the runtime accepts. 0.02 m is heavier (gated) but not refused here.
_ALLOWED_FINE = (0.05, 0.02)

#: Default hard sun for a fresh session (grazing polar band; overridable per config / per frame).
DEFAULT_SUN_AZ = 135.0
DEFAULT_SUN_EL = 18.0


class ConfigError(ValueError):
    """Raised on a malformed session config (the WS handler closes with this reason)."""


def _finite_float(value: Any, default: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def parse_config(raw: str | bytes | dict) -> dict[str, Any]:
    """Parse + normalize the first WS config message. Raises ``ConfigError`` on a bad shape."""
    if isinstance(raw, dict):
        cfg = raw
    else:
        try:
            cfg = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ConfigError(f"config is not JSON: {exc}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError("config must be a JSON object")

    mode = str(cfg.get("mode", "real")).lower()
    if mode not in ("real", "procedural"):
        raise ConfigError(f"mode must be 'real' or 'procedural', got {mode!r}")

    sun = cfg.get("sun") or {}
    if not isinstance(sun, dict):
        sun = {}
    out: dict[str, Any] = {
        "mode": mode,
        "fine_cell_m": _resolve_fine(cfg.get("fine")),
        "sun_az": _finite_float(sun.get("az"), DEFAULT_SUN_AZ),
        "sun_el": _finite_float(sun.get("el"), DEFAULT_SUN_EL),
    }

    if mode == "real":
        site = cfg.get("site") or DEFAULT_SITE
        site = str(site).strip()
        # Reject path escapes — a real site is a bare bundle NAME under samples/lunar_dem/.
        if not site or "/" in site or "\\" in site or site.startswith("."):
            raise ConfigError(f"real-mode site must be a bare bundle name, got {site!r}")
        out["site"] = site
    else:  # procedural
        out["world_seed"] = int(cfg.get("world_seed", 0))
        params = cfg.get("params") or {}
        if not isinstance(params, dict):
            raise ConfigError("procedural params must be an object")
        out["params"] = params  # validated downstream by procedural_bundle._normalize_params
    return out


def _resolve_fine(value: Any) -> float:
    f = _finite_float(value, _ALLOWED_FINE[0])
    # snap to the nearest allowed fine size (defensive; a stray value never reaches the runtime raw)
    return min(_ALLOWED_FINE, key=lambda a: abs(a - f))


def normalize_input(msg: str | bytes | dict) -> dict[str, Any]:
    """Parse + clamp one browser control frame into the minimal command relayed to Godot.

    Only keys that are actually present + valid appear in the result, so an absent field never
    overwrites Godot's retained state (e.g. a lone ``{"dig": true}`` does not zero the twist).
    """
    if isinstance(msg, dict):
        m = msg
    else:
        try:
            m = json.loads(msg)
        except (ValueError, TypeError):
            return {}
    if not isinstance(m, dict):
        return {}

    out: dict[str, Any] = {}
    if "v" in m or "omega" in m:
        out["v"] = max(-1.0, min(1.0, _finite_float(m.get("v"), 0.0)))
        out["omega"] = max(-1.0, min(1.0, _finite_float(m.get("omega"), 0.0)))
    if bool(m.get("dig", False)):
        out["dig"] = True
    if bool(m.get("dump", False)):
        out["dump"] = True
    if "sun_az" in m:
        out["sun_az"] = _finite_float(m.get("sun_az"), DEFAULT_SUN_AZ) % 360.0
    if "sun_el" in m:
        out["sun_el"] = max(-5.0, min(90.0, _finite_float(m.get("sun_el"), DEFAULT_SUN_EL)))
    # camera-mode toggle (rover view <-> 3rd person) + orbit drag/zoom deltas
    if bool(m.get("cam_next", False)):
        out["cam_next"] = True
    if "cam_mode" in m:
        out["cam_mode"] = int(_finite_float(m.get("cam_mode"), 0.0)) % 4
    for k in ("orbit_dyaw", "orbit_dpitch", "orbit_dzoom"):
        if k in m:
            out[k] = max(-90.0, min(90.0, _finite_float(m.get(k), 0.0)))
    # manual articulation: drum spin command (-1..1, 0=hold) + per-arm angle deltas (rad)
    if "drum" in m:
        out["drum"] = max(-1.0, min(1.0, _finite_float(m.get("drum"), 0.0)))
    for k in ("arm_front_d", "arm_back_d"):
        if k in m:
            out[k] = max(-0.5, min(0.5, _finite_float(m.get(k), 0.0)))
    # planning: click-to-plot a waypoint (canvas pixel), start/stop autonomous traverse, clear route
    click = m.get("click_px")
    if isinstance(click, (list, tuple)) and len(click) == 2:
        out["click_px"] = [_finite_float(click[0], 0.0), _finite_float(click[1], 0.0)]
    if "traverse" in m:
        out["traverse"] = bool(m.get("traverse"))
    if bool(m.get("clear_wp", False)):
        out["clear_wp"] = True
    return out
