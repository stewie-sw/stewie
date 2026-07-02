"""SN-08: active-morphology posture selection vs a fixed-posture baseline (canonical kinematics)."""
from dart import active_perception as AP
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


def test_sn14_info_per_joule_per_second_with_stability_hard_constraint():
    """SN-14 [REQ:SN-14]: the active-perception objective scores a candidate observation posture as
    expected viewpoint information / (maneuver energy [J] + hold power [W] * slew time [s]) -- info
    per joule AND per second -- with the stability margin as a HARD constraint: an infeasible
    posture is excluded (None) regardless of how much information it offers."""
    # (1) HARD constraint beats information: MEERKAT offers the MAXIMUM info of the whole candidate
    # sweep, yet under a 30 kg unbalanced front drum load its stability margin fails -> excluded.
    infos = [AP.info_gain_m(p) for p in AP.candidate_postures()]
    assert AP.info_gain_m(PS.MEERKAT_PITCH_RAD) == max(infos) > 0.0
    assert AP.score_observation_action(PS.MEERKAT_PITCH_RAD, fill_front_kg=30.0) is None
    meerkat = AP.score_observation_action(PS.MEERKAT_PITCH_RAD)
    assert meerkat is not None and meerkat > 0.0      # the LOAD gate excluded it, not the geometry

    # (2) higher info-per-cost wins the unified ranking (infeasible candidates never appear)
    ranked = AP.rank_observation_actions(fill_front_kg=0.0)
    scores = [s for s, _ in ranked]
    assert len(ranked) >= 2 and scores == sorted(scores, reverse=True)
    assert abs(ranked[0][1] - PS.MEERKAT_PITCH_RAD) < 1e-9    # best info-per-cost tops the ranking
    shallow = AP.score_observation_action(-0.5)
    assert shallow is not None and meerkat > shallow          # more info per cost -> higher score
    loaded = dict((p, s) for s, p in AP.rank_observation_actions(fill_front_kg=30.0))
    assert PS.MEERKAT_PITCH_RAD not in loaded                 # the gated posture is NOT ranked

    # (3) energy AND time both enter the denominator: the score IS info/(E + P_hold*t) with E>0 and
    # t>0, and worsening EITHER leg alone (half efficiency -> 2x energy; half slew rate -> 2x time)
    # strictly lowers the score.
    e = AP.maneuver_energy_j(PS.MEERKAT_PITCH_RAD)
    t = AP.maneuver_time_s(PS.MEERKAT_PITCH_RAD)
    assert e > 0.0 and t > 0.0
    expected = AP.info_gain_m(PS.MEERKAT_PITCH_RAD) / (e + AP.HOLD_POWER_W * t)
    assert abs(meerkat - expected) < 1e-12
    lossier = AP.score_observation_action(PS.MEERKAT_PITCH_RAD, efficiency=0.25)   # more joules
    slower = AP.score_observation_action(PS.MEERKAT_PITCH_RAD, rate_deg_s=10.0)    # more seconds
    assert lossier is not None and lossier < meerkat
    assert slower is not None and slower < meerkat
