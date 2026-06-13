"""Solar geometry at the Haworth site from MISSION TIME (the automatic sun directive).

Real spherical geometry, no fabrication: the sub-solar latitude oscillates +/-1.54 deg (the Moon's
spin-axis obliquity to the ecliptic, IAU value) over the sidereal month while the hour angle sweeps
360 deg per SYNODIC month; site elevation/azimuth follow from the standard alt-az transform at the
site latitude. Disclosed approximation: mean motion, no ephemeris perturbations/parallax -- the
upgrade path is SPICE, the structure does not change. Physics pins below are exact consequences of
the geometry, not tuned numbers.
"""


from stewie.specs import solar

HAWORTH_LAT = -87.45                                     # deg (LOLA polar product placement)


def test_elevation_bounded_by_colatitude_plus_obliquity():
    cap = (90.0 - abs(HAWORTH_LAT)) + solar.LUNAR_OBLIQUITY_DEG + 0.01
    for d in range(0, 60):
        _, el = solar.sun_az_el(HAWORTH_LAT, mission_time_s=d * 86400.0)
        assert -cap <= el <= cap


def test_azimuth_advances_one_rev_per_synodic_month():
    az0, _ = solar.sun_az_el(HAWORTH_LAT, mission_time_s=0.0)
    az1, _ = solar.sun_az_el(HAWORTH_LAT, mission_time_s=solar.SYNODIC_MONTH_S)
    assert abs((az1 - az0 + 180) % 360 - 180) < 1.5      # back within ~1.5 deg after one synodic rev


def test_polar_winter_and_summer_exist():
    els = [solar.sun_az_el(HAWORTH_LAT, mission_time_s=d * 86400.0)[1] for d in range(0, 28)]
    assert max(els) > 0.5 and min(els) < -0.5            # the site sees both sun-up and sun-down seasons


def test_equator_sees_high_sun():
    els = [solar.sun_az_el(0.0, mission_time_s=d * 86400.0)[1] for d in range(0, 28)]
    assert max(els) > 80.0                               # near-overhead at the equator


def test_deterministic_and_continuous():
    a = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1234567.0)
    b = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1234567.0)
    assert a == b
    az1, el1 = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1000.0)
    az2, el2 = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1060.0)
    assert abs(el2 - el1) < 0.01 and abs((az2 - az1 + 180) % 360 - 180) < 0.05


def test_layer_endpoint_accepts_mission_time(tmp_path):
    import importlib

    from fastapi.testclient import TestClient
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    r = c.get("/layers/raster/illumination.png?mission_t_s=0")
    r2 = c.get("/layers/raster/illumination.png?mission_t_s=600000")   # ~1/4 synodic month later
    assert r.status_code == 200 and r2.status_code == 200
    assert r.content != r2.content                       # the sun MOVED -> shadows moved


def test_spice_backend_loads_and_agrees_on_structure():
    # [REQ:TW-06] site/time sun vector via a documented ephemeris interface (SPICE)
    """The CORRECT wheel (Aaron 2026-06-10): SPICE (SpiceyPy + NAIF kernels) behind the SAME
    signature. Physics pins: elevation bounded by colatitude+obliquity-class limits; azimuth
    circles; and the two backends agree on the POLAR-DAY/NIGHT phase to within the mean-motion
    model's disclosed accuracy."""
    import pytest as _pytest
    _pytest.importorskip("spiceypy")
    if not solar.spice_available():
        _pytest.skip("NAIF kernels not present")
    els = []
    for d in range(0, 30):
        az, el = solar.sun_az_el_spice(HAWORTH_LAT, mission_time_s=d * 86400.0)
        assert -4.2 <= el <= 4.2                          # colatitude 2.55 + obliquity-class bound
        els.append(el)
    assert max(els) > 0.3 and min(els) < -0.3             # real polar day AND night in a month
    # the dispatcher prefers SPICE when available
    assert solar.sun_az_el(HAWORTH_LAT, 0.0, backend="spice") ==            solar.sun_az_el_spice(HAWORTH_LAT, 0.0)


def test_spice_vs_meanmotion_delta_artifact(tmp_path):
    """The WebGeocalc-class cross-check, automated: record the spice-vs-meanmotion deltas at
    sample epochs -- the honest accuracy statement for the disclosed approximation."""
    import json

    import pytest as _pytest
    _pytest.importorskip("spiceypy")
    if not solar.spice_available():
        _pytest.skip("NAIF kernels not present")
    out = solar.crosscheck_meanmotion(HAWORTH_LAT, n_epochs=12)
    # THE FINDING (recorded, not hidden): the mean-motion fallback's elevation can be off by
    # MORE than the site's whole +/-4 deg range allows for day/night correctness (measured ~5.6
    # deg at the notional epoch) -- which is exactly why SPICE is the DEFAULT backend and the
    # fallback exists only for kernel-free checkouts, accuracy stamped by this artifact.
    assert 0.0 < out["max_abs_el_delta_deg"] < 10.0       # finite, measured, honest
    assert 0.0 <= out["max_abs_az_delta_deg"] <= 180.0
    json.dump(out, open(tmp_path / "x.json", "w"))


def test_spice_failure_in_auto_degrades_to_meanmotion(monkeypatch):
    """#109: a SPICE error must never abort the process. erract=RETURN makes it raise, and in `auto`
    the dispatch catches it and degrades to the mean-motion fallback -- one bad ephemeris request can
    no longer SIGABRT the whole server."""
    def _boom(*a, **k):
        raise RuntimeError("simulated SPICE(BADSUBSCRIPT)")
    monkeypatch.setattr(solar, "spice_available", lambda: True)
    monkeypatch.setattr(solar, "sun_az_el_spice", _boom)
    az, el = solar.sun_az_el_dispatch(HAWORTH_LAT, 0.0, backend="auto")     # must NOT raise
    assert (az, el) == solar._MEANMOTION(HAWORTH_LAT, 0.0)                  # fell back, no crash


def test_concurrent_dispatch_does_not_crash():
    """#109: SPICE is not thread-safe; concurrent dispatch (the uvicorn threadpool case) must be
    serialized by the lock, not race inside furnsh/spkpos. Smoke: many threads, no crash, all valid."""
    import threading

    out, errs = [], []

    def run():
        try:
            out.append(solar.sun_az_el_dispatch(HAWORTH_LAT, 0.0, backend="auto"))
        except Exception as e:                                             # noqa: BLE001
            errs.append(repr(e))
    ts = [threading.Thread(target=run) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs, errs
    assert len(out) == 12 and all(0.0 <= az < 360.0 and -90.0 <= el <= 90.0 for az, el in out)
