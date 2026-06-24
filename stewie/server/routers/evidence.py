"""Navigation-evidence router (#108): surface the grounded navigation evidence for the cockpit System
pane -- the comparison (accuracy/precision vs the cited Stanford-LAC and ShadowNav baselines), the
generalization (the capability matrix positioning the three approach classes by regime), and the
photometric+depth modality precision (articulation parallax vs physical stereo). Every number comes
from dart.comparison (sourced constants + the parallax covariance model), so this is read-only published
methodology, no secrets -> an open GET like /figures and /metrics. No app-module import (dart is a leaf
subsystem here), so no router<->app cycle.
"""
from fastapi import APIRouter

from dart import comparison as CMP

router = APIRouter()

_MODALITY_RANGE_M = 6.0   # near-range landmarks (~shadow-tip distance) where the modalities are compared


@router.get("/evidence")
def get_evidence() -> dict:
    """The navigation evidence bundle: comparison / generalization / photometric+depth + op cost."""
    return {
        "ok": True,
        "capability_matrix": CMP.nav_capability_matrix(),               # generalization: 3 approach classes
        "accuracy_precision": CMP.accuracy_precision_comparison(),       # comparison vs the cited baselines
        "modality_sigma": {"range_m": _MODALITY_RANGE_M,                 # photometric+depth precision
                           **CMP.modality_range_sigma(_MODALITY_RANGE_M)},
        "operational_cost": CMP.operational_cost(),                      # time/energy of a fix + a traverse
    }
