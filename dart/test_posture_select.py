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
