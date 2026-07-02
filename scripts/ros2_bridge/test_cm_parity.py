"""[REQ:PM-11] cm-parity gate: report localization RMSE vs the [NAVLAB26] 0.038-0.067 m band and
REFUSE any parity claim until that band is reached on repeatable measurements.

PM-11 is the GATED target: repeatable centimetre-scale localization comparable to [NAVLAB26]
(0.038-0.067 m, PRD.md §2.1) BEFORE any parity claim. The cm-scale demonstration ITSELF needs the
GPU dense render -> depth + SuperPoint/LightGlue pipeline on LAC/IPEx sim data, which is absent on
this host, so the CLOSEABLE slice these tests pin is the comparison harness (cm_parity):

  * it reports the CURRENT real localization RMSE -- PM-10's Katwijk dead-reckoning leg
    (lac_suite.run_condition) on the committed ~30 s real fixture, ~1.46 m, meters-scale;
  * it WITHHOLDS the parity claim while that RMSE is outside the band (parity_allowed is False);
  * and the gate is NON-VACUOUS: fed enough REPEATABLE in-band values it WOULD grant parity (logic
    pinned on hand-chosen band values -- a gate BOUNDARY test, NOT a fabricated localization result).

REAL DATA ONLY: the measured RMSE is the real Katwijk ATE via PM-10 (lac_suite). No cm-scale number
is fabricated anywhere -- the band-boundary tests exercise the gate FUNCTION and assert no achievement.

CC0-1.0 (see ../../LICENSE).
"""

from __future__ import annotations

import math

import cm_parity


def test_navlab26_band_is_the_prd_reference_band():  # [REQ:PM-11]
    """The band is exactly the [NAVLAB26] localization-RMSE reference from PRD.md §2.1."""
    assert cm_parity.NAVLAB26_BAND_M == (0.038, 0.067)


def test_band_membership_gate_is_non_vacuous():  # [REQ:PM-11]
    """in_navlab26_band is a real predicate: edges/interior IN, just-outside + meters-scale OUT."""
    lo, hi = cm_parity.NAVLAB26_BAND_M
    for v in (lo, hi, 0.5 * (lo + hi)):
        assert cm_parity.in_navlab26_band(v)
    for v in (lo - 1e-3, hi + 1e-3, 1.4624, 3.35):
        assert not cm_parity.in_navlab26_band(v)
    # a missing / non-finite measurement is never "in band" (can't claim parity on a hole)
    assert not cm_parity.in_navlab26_band(None)
    assert not cm_parity.in_navlab26_band(float("nan"))


def test_current_real_localization_is_measured_and_meters_scale():  # [REQ:PM-11]
    """The measured number is PM-10's real committed Katwijk ATE (the ~1.2-1.7 m band
    test_lac_suite guards), not a fabricated cm figure."""
    m = cm_parity.measure_localization_rmse_m()
    assert m["status"] == "ok"
    assert m["rmse_m"] is not None and math.isfinite(m["rmse_m"])
    assert 1.2 < m["rmse_m"] < 1.7
    assert "Katwijk" in m["source"]


def test_harness_refuses_parity_on_the_current_real_number():  # [REQ:PM-11]
    """THE acceptance: the harness reports the real RMSE across repeats and withholds any parity
    claim while it sits outside the [NAVLAB26] band."""
    report = cm_parity.run_parity_benchmark()
    assert report["n_repeats"] >= cm_parity.MIN_REPEATS
    assert all(1.2 < r < 1.7 for r in report["rmse_m_per_repeat"])
    assert report["all_in_band"] is False
    assert report["parity_allowed"] is False
    assert report["parity_claim"] is None


def test_repeats_are_deterministic():  # [REQ:PM-11]
    """The real dead-reckoning pipeline is deterministic, so the repeats are genuinely repeatable
    (identical numbers), which is what makes 'across repeats' meaningful rather than luck."""
    report = cm_parity.run_parity_benchmark(repeats=4)
    vals = report["rmse_m_per_repeat"]
    assert len(vals) == 4 and len(set(vals)) == 1


def test_gate_would_grant_parity_only_on_repeatable_in_band_values():  # [REQ:PM-11]
    """The refuse-parity gate is not hard-coded False: fed enough repeatable in-band values it grants
    parity; one out-of-band repeat, too few repeats, or a missing number all refuse it.

    These are GATE-LOGIC boundary checks on hand-chosen band values -- they assert nothing about a
    real localization result (no cm-scale achievement is claimed anywhere).
    """
    lo, hi = cm_parity.NAVLAB26_BAND_M
    mid = 0.5 * (lo + hi)

    ok = cm_parity.evaluate_parity([mid, mid, mid])
    assert ok["parity_allowed"] is True and ok["parity_claim"] is not None

    just_out = cm_parity.evaluate_parity([mid, mid, hi + 1e-3])
    assert just_out["parity_allowed"] is False and just_out["parity_claim"] is None

    too_few = cm_parity.evaluate_parity([mid])
    assert too_few["parity_allowed"] is False and too_few["parity_claim"] is None

    with_hole = cm_parity.evaluate_parity([mid, mid, None])
    assert with_hole["parity_allowed"] is False and with_hole["parity_claim"] is None


def test_report_names_the_gated_cm_scale_pipeline():  # [REQ:PM-11]
    """The report is honest about WHY parity is withheld: the cm-scale demo needs the gated GPU
    dense-render + SuperPoint/LightGlue stack on LAC/IPEx sim data, absent on this host."""
    report = cm_parity.run_parity_benchmark()
    gated = report["gated"].lower()
    assert ("superpoint" in gated) or ("lightglue" in gated) or ("dense" in gated)
    assert ("lac" in gated) or ("ipex" in gated)


if __name__ == "__main__":
    # pure-python runner, mirroring the sibling test modules' convention
    test_navlab26_band_is_the_prd_reference_band()
    test_band_membership_gate_is_non_vacuous()
    test_current_real_localization_is_measured_and_meters_scale()
    test_harness_refuses_parity_on_the_current_real_number()
    test_repeats_are_deterministic()
    test_gate_would_grant_parity_only_on_repeatable_in_band_values()
    test_report_names_the_gated_cm_scale_pipeline()
    print("test_cm_parity: all assertions passed")
