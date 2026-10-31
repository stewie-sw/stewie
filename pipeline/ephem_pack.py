"""Pack DE440 Sun and Earth directions for the Moon into Chebyshev segments (RW-12, navigator N6).

Positions are the light-time-corrected (LT) Sun and Earth seen from the Moon's centre, in MOON_ME_DE440_ME421
(the LOLA terrain frame), fitted per fixed-length segment in TDB, together with the Moon's barycentric
velocity in the same axes. The device subtracts the site vector and then applies stellar aberration for the
topocentric direction (SPICE stelab), which matches SPICE's site-based LT+S; applying the centre's aberration
to a topocentric direction would be wrong by v/c times the parallax (2e-5 deg for the Earth). The leap-second table and SPICE's TDB-TT
constants are read from the LSK so the device converts UTC to TDB exactly as SPICE does, without SPICE.
Every segment is checked at off-node epochs against SPICE before the file is written; a fit worse than
MAX_FIT_ERR_RAD aborts the build.

    python pipeline/fetch_spice.py && python pipeline/ephem_pack.py
"""
from __future__ import annotations

import hashlib
import json
import math
import os

import numpy as np
import spiceypy as sp
from numpy.polynomial import chebyshev as C

import fetch_spice

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(HERE, "..", "crates", "lunar-ephem", "data"))
NAME = "moon_de440_2026_2035"
FRAME = "MOON_ME_DE440_ME421"
TARGETS = ("SUN", "EARTH")
ABCORR = "LT"
SERIES = TARGETS + ("MOON_SSB_VELOCITY",)   # last series: Moon centre velocity vs SSB [m/s], ME axes
START_UTC, END_UTC = "2026-01-01T00:00:00", "2036-01-01T00:00:00"
SEGMENT_S = 4 * 86400.0
DEGREE = 12
CHECKS_PER_SEGMENT = 6
MAX_FIT_ERR_RAD = 1e-9          # 2e-4 arcsec: far inside the 0.005 deg (8.7e-5 rad) requirement R3


def load_kernels() -> dict[str, str]:
    paths = fetch_spice.fetch()
    sp.kclear()
    for p in paths.values():
        sp.furnsh(p)
    return paths


def lsk_constants() -> dict:
    pairs = sp.gdpool("DELTET/DELTA_AT", 0, 200)
    table = [[float(pairs[i + 1]), float(pairs[i])] for i in range(0, len(pairs), 2)]
    m = sp.gdpool("DELTET/M", 0, 2)
    return {"delta_at": table, "delta_t_a": float(sp.gdpool("DELTET/DELTA_T_A", 0, 1)[0]),
            "k": float(sp.gdpool("DELTET/K", 0, 1)[0]), "eb": float(sp.gdpool("DELTET/EB", 0, 1)[0]),
            "m0": float(m[0]), "m1": float(m[1])}


def target_pos(target: str, et: float) -> np.ndarray:
    pos, _lt = sp.spkpos(target, et, FRAME, ABCORR, "MOON")
    return np.asarray(pos, dtype=np.float64) * 1000.0          # km -> m


def moon_velocity(et: float) -> np.ndarray:
    """Moon centre velocity relative to the SSB [m/s]: inertial (J2000) velocity rotated into ME axes, the
    observer velocity SPICE's stellar aberration uses (not the rotating-frame state velocity)."""
    state, _lt = sp.spkezr("MOON", et, "J2000", "NONE", "SOLAR SYSTEM BARYCENTER")
    return np.asarray(sp.pxform("J2000", FRAME, et)) @ np.asarray(state[3:6]) * 1000.0


def series_value(name: str, et: float) -> np.ndarray:
    return moon_velocity(et) if name == "MOON_SSB_VELOCITY" else target_pos(name, et)


def angle(a: np.ndarray, b: np.ndarray) -> float:
    return math.atan2(float(np.linalg.norm(np.cross(a, b))), float(np.dot(a, b)))


def pack() -> tuple[str, str]:
    kernels = load_kernels()
    et0, et1 = sp.str2et(START_UTC), sp.str2et(END_UTC)          # ISO strings are UTC in SPICE
    n_seg = math.ceil((et1 - et0) / SEGMENT_S)
    nodes = np.cos(np.pi * (np.arange(DEGREE + 1) + 0.5) / (DEGREE + 1))
    rng = np.random.default_rng(20261031)                      # off-node check epochs (sampling only)
    coeffs = np.empty((n_seg, len(SERIES), 3, DEGREE + 1))
    worst = {t: 0.0 for t in SERIES}
    for s in range(n_seg):
        mid, half = et0 + (s + 0.5) * SEGMENT_S, SEGMENT_S / 2.0
        for ti, tgt in enumerate(SERIES):
            vals = np.array([series_value(tgt, mid + half * x) for x in nodes])
            for axis in range(3):
                coeffs[s, ti, axis] = C.chebfit(nodes, vals[:, axis], DEGREE)
            for x in rng.uniform(-1.0, 1.0, CHECKS_PER_SEGMENT):
                fit = np.array([C.chebval(x, coeffs[s, ti, a]) for a in range(3)])
                worst[tgt] = max(worst[tgt], angle(fit, series_value(tgt, mid + half * x)))
    for tgt, err in worst.items():
        if err > MAX_FIT_ERR_RAD:
            raise RuntimeError(f"{tgt}: worst fit error {err:.3e} rad exceeds {MAX_FIT_ERR_RAD:.0e}")
    os.makedirs(OUT_DIR, exist_ok=True)
    blob = coeffs.astype("<f8").tobytes()
    bin_path = os.path.join(OUT_DIR, f"{NAME}.bin")
    with open(bin_path, "wb") as fh:
        fh.write(blob)
    header = {
        "format": "stewie-ephem-chebyshev-v1",
        "frame": FRAME, "observer": "MOON", "targets": list(SERIES), "abcorr": ABCORR,
        "units": "m (positions), m/s (MOON_SSB_VELOCITY)", "aberration": "stellar applied on device (SPICE stelab)",
        "time_scale": "TDB seconds past J2000", "start_tdb": et0, "segment_s": SEGMENT_S,
        "n_segments": n_seg, "degree": DEGREE, "layout": "[segment][target][axis][coefficient] <f8",
        "span_utc": [START_UTC + "Z", END_UTC + "Z"],
        "lsk": lsk_constants(),
        "radii_m": {t: [float(v) * 1000.0 for v in sp.bodvrd(t, "RADII", 3)[1]] for t in TARGETS},
        "fit_max_err_rad": {t: worst[t] for t in SERIES},
        "bin_sha256": hashlib.sha256(blob).hexdigest(),
        "kernels": {os.path.basename(p): fetch_spice._sha256(p) for p in sorted(kernels.values())},
        "generator": "pipeline/ephem_pack.py",
    }
    json_path = os.path.join(OUT_DIR, f"{NAME}.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(header, indent=1, sort_keys=True) + "\n")
    return json_path, bin_path


if __name__ == "__main__":
    j, b = pack()
    print(j, os.path.getsize(b), "bytes")
    print(json.load(open(j))["fit_max_err_rad"])
