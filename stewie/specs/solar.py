"""Sun azimuth/elevation at a lunar site from MISSION TIME (real spherical geometry).

The Moon's spin axis is inclined 1.54 deg to the ecliptic normal (IAU/Cassini state), so the
SUB-SOLAR LATITUDE oscillates +/-1.54 deg sinusoidally over a month while the sub-solar LONGITUDE
sweeps 360 deg per SYNODIC month (29.530589 days, the lunar day). Site elevation and azimuth then
follow from the standard spherical alt-az transform:

    sin(el) = sin(phi) sin(delta) + cos(phi) cos(delta) cos(H)
    az      = atan2( -cos(delta) sin(H),  cos(phi) sin(delta) - sin(phi) cos(delta) cos(H) )

with phi = site latitude, delta = sub-solar latitude, H = hour angle (site lon - sub-solar lon).
Azimuth is measured from local NORTH, eastward -- matching dart.illumination's convention.

DISCLOSED APPROXIMATION (not fabrication): mean motions only -- no ephemeris perturbations, no
eccentricity equation-of-time, no parallax/refraction (vacuum), epoch phase = 0 at mission start
unless given. At a polar site the consequences the planner cares about are exact in structure:
azimuth circles the horizon once per lunar day; elevation breathes inside
+/- (colatitude + 1.54 deg); polar winter/summer alternate. Upgrade path: SPICE kernels swap in
behind the same signature.
"""
from __future__ import annotations

import math

LUNAR_OBLIQUITY_DEG = 1.54           # spin axis vs ecliptic normal (IAU Cassini state)
SYNODIC_MONTH_S = 29.530589 * 86400.0   # the lunar day (sub-solar longitude period)
SIDEREAL_MONTH_S = 27.321661 * 86400.0  # the sub-solar LATITUDE oscillation period


def sub_solar_point(mission_time_s: float, *, lon0_deg: float = 0.0,
                    season_phase_rad: float = 0.0) -> tuple:
    """(latitude, longitude) of the sub-solar point at mission time [deg]."""
    lat = LUNAR_OBLIQUITY_DEG * math.sin(
        2.0 * math.pi * mission_time_s / SIDEREAL_MONTH_S + season_phase_rad)
    # H-18: the sub-solar longitude moves WESTWARD (decreasing, east-positive convention) -- the Moon
    # rotates prograde so the Sun tracks east->west. SPICE-validated (subslr/reclat: -89.96 deg per
    # quarter synodic month). This is the ONE solar authority; dart.geometry.solar delegates here.
    lon = (lon0_deg - 360.0 * mission_time_s / SYNODIC_MONTH_S) % 360.0
    return lat, lon


def sun_az_el(site_lat_deg: float, mission_time_s: float, *, site_lon_deg: float = 0.0,
              lon0_deg: float = 0.0, season_phase_rad: float = 0.7) -> tuple:
    """Sun (azimuth from local north [deg, eastward], elevation [deg]) at the site."""
    delta_deg, sun_lon = sub_solar_point(mission_time_s, lon0_deg=lon0_deg,
                                         season_phase_rad=season_phase_rad)
    phi = math.radians(site_lat_deg)
    delta = math.radians(delta_deg)
    H = math.radians((site_lon_deg - sun_lon) % 360.0)
    sin_el = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(H)
    el = math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))
    az = math.degrees(math.atan2(
        -math.cos(delta) * math.sin(H),
        math.cos(phi) * math.sin(delta) - math.sin(phi) * math.cos(delta) * math.cos(H)))
    return az % 360.0, el


# ---- SPICE backend (the correct wheel; Aaron 2026-06-10: "NASA has already built it") -----------
# SpiceyPy + the NAIF generic kernels: de440s (planetary ephemeris), moon_pa_de440 +
# moon_de440 frames kernel (MOON_ME body-fixed), naif0012 leapseconds, pck00011. Kernels live
# OUTSIDE the repo ($STEWIE_SPICE_KERNELS, default /mnt/projects/datasets/spice_kernels); the
# mean-motion model above stays as the documented kernel-free fallback, its accuracy REPORTED by
# crosscheck_meanmotion(). MISSION_EPOCH_UTC anchors mission_time_s=0 to a real date.
import os as _os
import threading as _threading

# SPICE (SPICELIB) keeps global state and is NOT thread-safe; uvicorn runs sync endpoints in a
# threadpool, so concurrent furnsh/spkpos calls corrupt its state and the toolkit hard-ABORTs the
# whole process (SIGABRT). Serialize every SPICE call behind this lock (reentrant: sun_az_el_spice
# holds it across its own _ensure_kernels call).
_SPICE_LOCK = _threading.RLock()

MISSION_EPOCH_UTC = "2026-11-15T00:00:00"   # [ASSUMPTION] notional IPEx demo epoch; settable
_KERNEL_DIR = _os.environ.get("STEWIE_SPICE_KERNELS", "/mnt/projects/datasets/spice_kernels")
_KERNELS = ("naif0012.tls", "pck00011.tpc", "de440s.bsp",
            "moon_pa_de440_200625.bpc", "moon_de440_250416.tf")
_loaded = False


def spice_available() -> bool:
    try:
        import spiceypy  # noqa: F401
    except ImportError:
        return False
    return all(_os.path.exists(_os.path.join(_KERNEL_DIR, k)) for k in _KERNELS)


def _ensure_kernels() -> None:
    global _loaded
    if _loaded:
        return
    import spiceypy as sp
    with _SPICE_LOCK:
        if _loaded:
            return
        sp.erract("SET", 10, "RETURN")   # a SPICE error RETURNS (raises in spiceypy), never ABORTs the process
        sp.errprt("SET", 10, "NONE")     # suppress the toolkit's own stderr traceback
        for k in _KERNELS:
            sp.furnsh(_os.path.join(_KERNEL_DIR, k))
        _loaded = True


def sun_az_el_spice(site_lat_deg: float, mission_time_s: float, *, site_lon_deg: float = 0.0,
                    epoch_utc: str | None = None) -> tuple:
    """Sun (azimuth from local north [deg, eastward], elevation [deg]) via SPICE: the Sun state
    from the Moon center in the MOON_ME body-fixed frame (LT+S aberration), transformed to the
    site's topocentric ENU on the IAU sphere."""
    import spiceypy as sp
    with _SPICE_LOCK:                  # serialize: SPICE is not thread-safe
        _ensure_kernels()
        et = sp.str2et(epoch_utc or MISSION_EPOCH_UTC) + float(mission_time_s)
        sun_pos, _lt = sp.spkpos("SUN", et, "MOON_ME", "LT+S", "MOON")
    lat, lon = math.radians(site_lat_deg), math.radians(site_lon_deg)
    r_moon = 1737.4
    # site rectangular position = latrec(r, lon, lat) = r * radial-unit; computed inline (pure
    # spherical->rectangular, no SPICE call) so it needn't hold _SPICE_LOCK (audit M-34)
    up = [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    site = [r_moon * u for u in up]
    v = [sun_pos[i] - site[i] for i in range(3)]
    # local ENU basis at the site on the sphere
    east = [-math.sin(lon), math.cos(lon), 0.0]
    north = [-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)]
    d = math.sqrt(sum(x * x for x in v))
    e = sum(v[i] * east[i] for i in range(3)) / d
    n = sum(v[i] * north[i] for i in range(3)) / d
    u = sum(v[i] * up[i] for i in range(3)) / d
    el = math.degrees(math.asin(max(-1.0, min(1.0, u))))
    az = math.degrees(math.atan2(e, n)) % 360.0
    return az, el


_MEANMOTION = sun_az_el


def sun_az_el_dispatch(site_lat_deg: float, mission_time_s: float, *, backend: str = "auto",
                       **kw) -> tuple:
    """SPICE when available (the correct wheel), mean-motion otherwise (disclosed fallback). A SPICE
    failure (bad kernel, etc.) now RAISES (erract=RETURN) instead of aborting the process; in `auto`
    it is caught and degrades to mean-motion so one bad ephemeris request can never take down the
    server. `backend="spice"` re-raises (the caller explicitly demanded SPICE)."""
    if backend == "spice" or (backend == "auto" and spice_available()):
        try:
            return sun_az_el_spice(site_lat_deg, mission_time_s,
                                   site_lon_deg=kw.get("site_lon_deg", 0.0))
        except Exception:              # noqa: BLE001 -- SPICE error -> reset state, then fall back / re-raise
            try:
                import spiceypy as sp
                with _SPICE_LOCK:
                    sp.reset()
            except Exception:          # noqa: BLE001
                pass
            if backend == "spice":
                raise
    return _MEANMOTION(site_lat_deg, mission_time_s, **kw)


def crosscheck_meanmotion(site_lat_deg: float, *, n_epochs: int = 12) -> dict:
    """The accuracy artifact: spice-vs-meanmotion deltas across a synodic month (the honest
    statement of what the kernel-free fallback costs)."""
    daz = del_ = 0.0
    rows = []
    for i in range(n_epochs):
        t = i * SYNODIC_MONTH_S / n_epochs
        az_s, el_s = sun_az_el_spice(site_lat_deg, t)
        az_m, el_m = _MEANMOTION(site_lat_deg, t)
        da = abs((az_s - az_m + 180.0) % 360.0 - 180.0)
        de = abs(el_s - el_m)
        daz, del_ = max(daz, da), max(del_, de)
        rows.append({"t_s": t, "spice": [az_s, el_s], "meanmotion": [az_m, el_m]})
    return {"schema": "solar_crosscheck/1.0", "epoch_utc": MISSION_EPOCH_UTC,
            "site_lat_deg": site_lat_deg, "n_epochs": n_epochs,
            "max_abs_az_delta_deg": round(daz, 3), "max_abs_el_delta_deg": round(del_, 3),
            "rows": rows}


# the public name keeps the original signature PLUS the backend switch
sun_az_el = sun_az_el_dispatch  # noqa: F811 -- deliberate: SPICE-preferring dispatcher
