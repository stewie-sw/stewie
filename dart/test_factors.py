import json

import numpy as np
import pytest

from dart.evidence_ledger import write_navigation_evidence
from dart.factors import EvidenceClass, FactorType, Frame, MeasurementFactor


def test_measurement_factor_keeps_type_covariance_and_evidence():
    f = MeasurementFactor(
        factor_type=FactorType.PARALLAX_XY,
        keyframe=4,
        value=[1.0, 2.0],
        covariance=[[0.04, 0.0], [0.0, 0.25]],
        frame=Frame.WORLD,
        source="dart.articulated_parallax",
        evidence_class=EvidenceClass.COMPUTED,
    )
    assert f.xy_covariance() == pytest.approx(np.diag([0.04, 0.25]))
    assert f.to_json()["factor_type"] == FactorType.PARALLAX_XY


def test_shadow_yaw_allows_measured_heading_but_metric_shadow_is_guarded():
    MeasurementFactor(
        factor_type=FactorType.SHADOW_YAW,
        keyframe=1,
        value=0.1,
        covariance=[[0.01]],
        frame=Frame.WORLD,
        source="dart.shadow_factors",
        evidence_class=EvidenceClass.MEASURED,
    )
    with pytest.raises(ValueError, match="sigma_n_two_split"):
        MeasurementFactor(
            factor_type=FactorType.SHADOW_LENGTH,
            keyframe=1,
            value=2.0,
            covariance=[[0.04]],
            frame=Frame.CAMERA,
            source="sigma_n_two_split_2026-06-24.json",
            evidence_class=EvidenceClass.MEASURED,
        )


def test_navigation_evidence_ledger_writes_factor_evidence(tmp_path):
    f = MeasurementFactor(
        factor_type=FactorType.SHADOW_YAW,
        keyframe=2,
        value=0.2,
        covariance=[[0.09]],
        frame=Frame.WORLD,
        source="test",
        evidence_class=EvidenceClass.MODELED_SIGMA,
    )
    out = tmp_path / "ledger.json"
    record = write_navigation_evidence(out, run_id="unit", factors=[f], result={"ate": 1.0})
    loaded = json.loads(out.read_text())
    assert loaded == record
    assert loaded["evidence_classes"] == [EvidenceClass.MODELED_SIGMA]
    assert loaded["factors"][0]["factor_type"] == FactorType.SHADOW_YAW
