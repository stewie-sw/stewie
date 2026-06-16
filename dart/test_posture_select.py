"""SN-08: active-morphology posture selection vs a fixed-posture baseline (canonical kinematics)."""
from dart import posture_select as PS


def test_selector_raises_camera_and_buys_parallax_vs_static():
    """SN-08 [REQ:SN-08]: active morphology lifts the camera and yields a vertical parallax baseline
    that a STATIC rover (TRANSIT) cannot get (parallax 0). The improvement vs fixed posture."""
    active = PS.select_viewpoint_posture(min_margin_m=0.05)
    g = PS.viewpoint_gain(active)
    assert g["active_lift_m"] > 0.05 and g["stable"]          # a raised, feasible posture
    assert g["parallax_baseline_m"] > 0.05                    # active morphology BUYS vertical parallax
    assert g["camera_height_gain_m"] > 0.05                   # higher camera -> more horizon/shadow
    assert g["active_lift_m"] <= 0.175                        # capped by the canonical MEERKAT lift (0.174 m)
    # the static baseline gets ZERO parallax (one fixed view)
    assert PS.viewpoint_gain(0.0)["parallax_baseline_m"] == 0.0


def test_stability_gate_caps_the_lift_under_load():
    """Honest: a heavy asymmetric drum load shrinks the stability margin, so the selector returns a
    LOWER (more conservative) posture -- active morphology respects the tip limit, never force-lifts."""
    light = PS.viewpoint_gain(PS.select_viewpoint_posture(fill_front_kg=0.0, min_margin_m=0.05))
    heavy = PS.viewpoint_gain(PS.select_viewpoint_posture(fill_front_kg=30.0, min_margin_m=0.05))
    assert heavy["active_lift_m"] <= light["active_lift_m"]   # load forces a more conservative viewpoint


def test_selected_posture_is_always_feasible():
    for load in (0.0, 10.0, 30.0):
        a = PS.select_viewpoint_posture(fill_front_kg=load, min_margin_m=0.05)
        assert PS.viewpoint_gain(a)["stable"], f"selector must return a feasible posture at load {load}"


def test_asymmetric_recovers_viewpoint_under_heavy_unbalanced_load():
    """#92 [REQ:SN-08b]: under a heavily unbalanced drum load the SYMMETRIC selector finds NO feasible
    raised posture (the off-centre CG tips it at every symmetric raised pitch), but exploring ASYMMETRIC
    postures recovers a feasible raised viewpoint by balancing the fore/aft moment with asymmetric drum
    reach (the heavy end planted deeper -> shorter reach -> smaller moment arm)."""
    sym = PS.select_viewpoint_posture(fill_front_kg=30.0, fill_rear_kg=0.0, min_margin_m=0.05)
    front, rear = PS.select_viewpoint_posture_asym(fill_front_kg=30.0, fill_rear_kg=0.0, min_margin_m=0.05)
    assert PS.viewpoint_gain(sym)["active_lift_m"] == 0.0          # symmetric: no feasible raised posture
    g = PS.viewpoint_gain_asym(front, rear, fill_front_kg=30.0, fill_rear_kg=0.0)
    assert g["active_lift_m"] > 0.10 and g["stable"]              # asymmetric recovers a real raised viewpoint
    assert front != rear                                          # genuinely asymmetric


def test_asymmetric_reduces_to_symmetric_when_balanced():
    """A balanced (or zero) load needs no asymmetry: the asymmetric optimum IS the symmetric MEERKAT."""
    for ff, fr in [(0.0, 0.0), (15.0, 15.0)]:
        front, rear = PS.select_viewpoint_posture_asym(fill_front_kg=ff, fill_rear_kg=fr, min_margin_m=0.05)
        sym = PS.select_viewpoint_posture(fill_front_kg=ff, fill_rear_kg=fr, min_margin_m=0.05)
        la = PS.viewpoint_gain_asym(front, rear, fill_front_kg=ff, fill_rear_kg=fr)["active_lift_m"]
        assert abs(la - PS.viewpoint_gain(sym)["active_lift_m"]) < 1e-6


def test_asymmetric_selected_posture_always_feasible():
    for ff, fr in [(0.0, 0.0), (30.0, 0.0), (0.0, 30.0), (20.0, 5.0), (30.0, 30.0)]:
        front, rear = PS.select_viewpoint_posture_asym(fill_front_kg=ff, fill_rear_kg=fr, min_margin_m=0.05)
        assert PS.viewpoint_gain_asym(front, rear, fill_front_kg=ff, fill_rear_kg=fr)["stable"], \
            f"asymmetric selector must return a feasible posture at load {ff},{fr}"
