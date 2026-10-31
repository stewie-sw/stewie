"""Native measured-terrain scenario identity and reproducibility checks."""
from __future__ import annotations

import os
import tempfile

import pytest

from stewie.dataset import scenario as S

SFS = os.path.join(S.SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")



def test_the_same_scenario_yields_a_byte_identical_world_twice() -> None:
    """[REQ:TR-01] The whole premise: same name -> same world. Terrain, spawn, grid AND every rock."""
    sc = S.load("haworth_pad_a_native")
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        fa = S.world_fingerprint(sc, a)
        fb = S.world_fingerprint(sc, b)
    assert fa == fb, "the same scenario produced two different worlds -- nothing recorded in it is trainable"


def test_the_scenario_honours_its_pinned_section_not_the_auto_spawn() -> None:
    """[REQ:TR-01] A pinned start_xy must actually be used. If the runtime silently fell back to the
    flattest-interior search, the 'section you selected' would not be the section you drove."""
    sc = S.load("haworth_pad_a_native")
    with tempfile.TemporaryDirectory() as d:
        rt = S.build_runtime(sc, d)
        try:
            assert rt.start_xy == pytest.approx(sc.start_xy), \
                "the runtime ignored the scenario's pinned section"
        finally:
            rt.stop()          # __init__ opens a listening socket; release it (see scenario.py)


def test_retired_generated_scenario_is_not_relabelled_as_native():
    with pytest.raises(KeyError, match="unknown scenario"):
        S.load("haworth_pad_a")
