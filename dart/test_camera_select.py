"""SN-06: camera direction/exposure selection vs a fixed-camera baseline."""
from dart import camera_select as CS


def test_washout_high_facing_low_sun_zero_when_high_or_behind():
    assert CS.washout_risk(0.0, 0.0, 3.0) > 0.7          # looking straight at a low sun -> washed
    assert CS.washout_risk(0.0, 180.0, 3.0) == 0.0       # sun behind -> no washout
    assert CS.washout_risk(0.0, 0.0, 40.0) == 0.0        # sun high -> no washout


def test_selector_picks_the_pair_away_from_the_sun():
    v = CS.select_view(0.0, 3.0)                          # sun low + ahead -> front washes -> pick BACK
    assert v["pair"] == "back" and v["usable"]
    v2 = CS.select_view(180.0, 3.0)                       # sun low + behind -> pick FRONT
    assert v2["pair"] == "front" and v2["usable"]


def test_selector_beats_fixed_front_baseline_across_the_sun_sweep():
    """SN-06 [REQ:SN-06]: across a full body-sun azimuth sweep at low sun, the selector keeps a
    usable stereo pair far more often than a fixed front-only baseline."""
    def selector(az, el):
        return CS.select_view(az, el)

    def fixed_front(az, el):
        worst = max(CS.washout_risk(a, az, el) for a, p in CS.CAMERA_RIG.values() if p == "front")
        return {"usable": worst < 0.5}

    sel = CS.usable_fraction(selector, 3.0)
    base = CS.usable_fraction(fixed_front, 3.0)
    assert sel > base, f"selector must beat fixed-front baseline: {sel} !> {base}"
    assert sel > 0.95                                    # front+back 180 apart -> nearly always usable
