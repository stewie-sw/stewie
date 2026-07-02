"""PM-11 cm-parity harness: report localization RMSE vs the [NAVLAB26] band, REFUSE parity until reached.

PM-11 is the GATED navigation target -- repeatable centimetre-scale localization comparable to the
[NAVLAB26] reference (localization RMSE ~0.038-0.067 m, PRD.md §2.1) BEFORE any parity claim.  The
cm-scale demonstration ITSELF requires the GPU dense render -> depth + SuperPoint/LightGlue pipeline
on LAC/IPEx sim data, which is NOT present on this host, so it CANNOT be produced here and no cm-scale
number is invented anywhere in this module.

What IS buildable here -- and what this harness is -- is the honest comparison gate:

  * it measures the CURRENT real localization RMSE by calling PM-10's fixed LAC-style suite
    (`lac_suite.run_condition` -> the real ESA Katwijk dead-reckoning ATE on the committed ~30 s real
    fixture, ~1.46 m, meters-scale), and REPEATS the measurement to show it is repeatable;
  * it compares each measured RMSE to the [NAVLAB26] band, and
  * it WITHHOLDS the parity claim (`parity_allowed=False`, `parity_claim=None`) while the band is
    unreached -- the "refuse parity until reached" behaviour PM-11 requires.

The gate is non-vacuous: `evaluate_parity` grants parity (and emits a claim) exactly when there are
enough REPEATABLE in-band measurements, and refuses on any out-of-band / missing / too-few case.  The
band-membership logic can be exercised on any value, but the DEMONSTRATION half stays gated: the real
number reported here is meters-scale and is never inflated toward the centimetre band.

Pure stdlib + the repo's own PM-10 scorer.  No ROS import; runs on the bare host .venv.

CC0-1.0 (see ../../LICENSE).
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Optional, Sequence

import lac_suite

BENCHMARK_NAME = "navlab26_cm_parity_v1"

# [NAVLAB26] A. Dai et al., arXiv:2603.17232v1 -- reported localization RMSE ~0.038-0.067 m across
# presets/seeds (PRD.md §2.1).  A benchmark, NOT evidence STEWIE currently achieves it.
NAVLAB26_BAND_M: tuple[float, float] = (0.038, 0.067)

# Parity is a REPEATABILITY claim, not a single lucky run: require at least this many measurements,
# ALL in band, before the gate will grant it.
MIN_REPEATS = 3

# The condition whose localization leg we read from PM-10.  The Katwijk localization leg is
# condition-insensitive on the CPU path (one real deterministic dataset -- lac_suite flags this), so
# the choice of seed/light/rocks does not move the number; a single fixed condition is honest.
_DEFAULT_CONDITION: dict[str, Any] = {"seed": 0, "light": "lit", "rocks": True}

# Why the cm-scale demonstration cannot complete on this host (carried on every report; never faked).
GATED_NOTE = (
    "cm-scale LAC parity needs the GPU dense render -> depth + SuperPoint/LightGlue pipeline on "
    "LAC/IPEx sim data, absent on this host; the number reported here is the real Katwijk "
    "dead-reckoning ATE (PM-10 localization leg) and is never inflated toward the centimetre band."
)


def in_navlab26_band(rmse_m: Optional[float]) -> bool:
    """True iff `rmse_m` is a finite value inside the closed [NAVLAB26] band.

    A None / NaN / inf measurement is NOT in band -- parity is never granted on a missing number.
    """
    if rmse_m is None or not math.isfinite(rmse_m):
        return False
    lo, hi = NAVLAB26_BAND_M
    return lo <= rmse_m <= hi


def evaluate_parity(
    rmse_m_list: Sequence[Optional[float]], *, min_repeats: int = MIN_REPEATS
) -> dict:
    """Pure parity gate over a list of measured RMSE values (m).

    Grants parity ONLY when there are at least `min_repeats` measurements and EVERY one is a finite
    value inside the [NAVLAB26] band; otherwise the claim is withheld (`parity_allowed=False`,
    `parity_claim=None`).  This is the "refuse parity until reached" rule as a standalone function so
    both the live benchmark and the boundary tests share one gate.
    """
    per_repeat_in_band = [in_navlab26_band(r) for r in rmse_m_list]
    enough_repeats = len(rmse_m_list) >= min_repeats
    all_in_band = len(per_repeat_in_band) > 0 and all(per_repeat_in_band)
    parity_allowed = enough_repeats and all_in_band
    lo, hi = NAVLAB26_BAND_M
    claim = (
        f"PARITY REACHED: {len(rmse_m_list)} repeatable localization RMSE values all within the "
        f"[NAVLAB26] {lo}-{hi} m band."
        if parity_allowed
        else None
    )
    return {
        "band_m": NAVLAB26_BAND_M,
        "min_repeats": min_repeats,
        "n_repeats": len(rmse_m_list),
        "per_repeat_in_band": per_repeat_in_band,
        "enough_repeats": enough_repeats,
        "all_in_band": all_in_band,
        "parity_allowed": parity_allowed,
        "parity_claim": claim,
    }


def measure_localization_rmse_m(
    *, condition: Mapping[str, Any] = _DEFAULT_CONDITION, **suite_kwargs: Any
) -> dict:
    """One real localization measurement via PM-10 (`lac_suite.run_condition`).

    Returns the localization leg's RMSE (m), its leg status, and the real source string -- exactly the
    number PM-10 reports (real committed Katwijk ATE), surfaced here for the band comparison.  A failed
    leg carries `rmse_m=None` with its status, never a substituted value.
    """
    row = lac_suite.run_condition(condition, **suite_kwargs)
    loc = row["context"].get("localization", {})
    return {
        "rmse_m": row["metrics"]["localization_rmse_m"],
        "status": row["status"]["localization_rmse_m"],
        "source": loc.get("source", "PM-10 lac_suite localization leg"),
        "eval_track_length_m": loc.get("eval_track_length_m"),
    }


def run_parity_benchmark(
    repeats: int = MIN_REPEATS,
    *,
    condition: Mapping[str, Any] = _DEFAULT_CONDITION,
    **suite_kwargs: Any,
) -> dict:
    """Measure the localization RMSE `repeats` times, compare to the band, and report -- REFUSING any
    parity claim until the band is reached (report-only, no CI gate, no fabricated cm number).
    """
    measurements = [
        measure_localization_rmse_m(condition=condition, **suite_kwargs)
        for _ in range(repeats)
    ]
    rmse_list = [m["rmse_m"] for m in measurements]
    gate = evaluate_parity(rmse_list, min_repeats=MIN_REPEATS)

    report: dict[str, Any] = {
        "benchmark": BENCHMARK_NAME,
        "report_only": True,
        "reference": "[NAVLAB26] localization RMSE 0.038-0.067 m (PRD.md §2.1)",
        "n_repeats": repeats,
        "rmse_m_per_repeat": rmse_list,
        "status_per_repeat": [m["status"] for m in measurements],
        "data_source": measurements[0]["source"] if measurements else None,
        "gated": GATED_NOTE,
    }
    # merge the gate verdict (band_m, in-band flags, parity_allowed/claim) without clobbering the
    # report-level n_repeats / band already set above
    for k, v in gate.items():
        report.setdefault(k, v)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: print the parity report JSON to stdout (report-only, like lac_suite / eval_harness)."""
    print(json.dumps(run_parity_benchmark(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
