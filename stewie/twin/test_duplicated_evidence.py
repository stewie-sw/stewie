"""[F7] One reading presented twice, and where the mechanism's scope ends.

This family does not add a defence. It establishes a boundary, and the boundary is sharp.

``m_eff`` is derived from the declared per-cell source graph. Known
duplication can be represented by an edge. A relabelled copy presented as a
genuine new identity with no edge instead counterfeits an independent
component. The two copies agree perfectly, because they are the same numbers,
so corroboration passes trivially and the duplicated reading overrules a
correct physical model.

Measured: a faulty reading presented once is declined in every trial; the same reading relabelled as
two sources is accepted in **every** trial and is harmful in all of them.

The graph can represent possible dependency from any declared provenance
mechanism, but it cannot infer hidden common identity from equal values without
making source admission value-dependent. Source integrity is therefore R3,
not a property supplied by the graph.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.veto_experiment import run_duplicated_evidence_sweep

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

N = 32
OFFSETS = [0.3, 0.6, 1.0]


def _truth() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    base = z.reshape(side, side)[1000:1000 + N, 1000:1000 + N].astype(np.float64)
    cut = np.zeros_like(base)
    cut[8:20, 8:20] = -0.40
    return base + cut


def test_a_single_faulty_reading_is_declined():
    """The control. With one source there is nothing to corroborate, the model disagrees, and the
    rule correctly refuses."""
    truth = _truth()
    res = run_duplicated_evidence_sweep(truth, OFFSETS, duplicate=False)
    assert all(x.n_harmful == 0 for x in res["gate"])
    assert all(x.abstain_rate == 1.0 for x in res["gate"])


def test_relabelling_the_same_reading_as_two_sources_defeats_the_rule_completely():
    """The boundary, and it is not a soft one. The identical reading under a second source name is
    accepted in every trial at every offset, and is harmful in all of them. Corroboration is
    satisfied by construction because the two 'sources' carry the same numbers."""
    truth = _truth()
    res = run_duplicated_evidence_sweep(truth, OFFSETS, duplicate=True)
    assert all(x.n_harmful == 20 for x in res["gate"]), \
        f"expected total failure under duplication: {[(x.level_m, x.n_harmful) for x in res['gate']]}"
    assert all(x.abstain_rate == 0.0 for x in res["gate"])


def test_the_dependency_correction_cannot_see_hidden_relabelling():
    """Why it fails, stated as a property rather than left to inference.

    ``m_eff`` is a function of the declared graph. Hidden relabelling adds a
    source without adding the dependency edge that its common origin requires,
    so claimed support rises while real independent support does not.
    """
    truth = _truth()
    once = run_duplicated_evidence_sweep(truth, [0.6], duplicate=False)["gate"][0]
    twice = run_duplicated_evidence_sweep(truth, [0.6], duplicate=True)["gate"][0]
    # No identity/provenance edge is supplied, so this layer cannot distinguish them.
    assert once.n_harmful == 0 and twice.n_harmful == 20
    assert once.abstain_rate == 1.0 and twice.abstain_rate == 0.0


def test_this_is_a_scope_limit_not_a_regression():
    """Recorded so a later reader does not treat it as a defect to be fixed inside m_eff.

    Detecting duplication requires source-identity integrity --- knowing that two labels denote two
    genuine observations. That is a different guarantee from the one under study and would be
    supplied by the evidence pipeline, not inferred from equal values."""
    truth = _truth()
    res = run_duplicated_evidence_sweep(truth, [1.0], duplicate=True)["gate"][0]
    assert res.n_harmful == 20
    assert res.mean_error_m > 0.9, "the accepted state carries the full injected offset"
