"""Persistent-vs-mutable landmark hierarchy from the real Haworth DEM."""
import os

from dart import landmarks as LM

_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def test_extract_immutable_anchors_from_real_dem():
    if not _HAVE:
        return
    from lode import mission_planner as MP
    dem = MP.load_haworth_dem()
    lms = LM.extract_persistent_landmarks(dem, neighborhood_m=300.0, min_prominence_m=30.0, max_landmarks=50)
    assert lms and all(m.immutable and m.is_global_anchor for m in lms)        # large-scale -> immutable
    assert lms[0].prominence_m >= lms[-1].prominence_m                          # prominence-sorted
    immut, mut = LM.split_by_persistence(lms)
    assert len(immut) == len(lms) and len(mut) == 0                            # all global anchors here


def test_small_neighborhood_is_mutable():
    if not _HAVE:
        return
    from lode import mission_planner as MP
    dem = MP.load_haworth_dem()
    lms = LM.extract_persistent_landmarks(dem, neighborhood_m=30.0, immutable_scale_m=100.0, max_landmarks=20)
    assert lms and all(not m.immutable for m in lms)                           # sub-scale -> NOT a global anchor


def test_flat_ground_beside_pit_is_not_an_anchor():
    # audit 2026-06-09 (critical): flat terrain ties maximum_filter and "prominence" measured pit depth
    import numpy as np

    from dart import landmarks as LM2
    z = np.zeros((100, 100)); z[40:60, 40:60] = -80.0           # flat plate with a deep pit
    lms = LM2.extract_persistent_landmarks((z, 5.0), neighborhood_m=300.0, min_prominence_m=30.0)
    assert lms == []                                            # featureless flat must mint NO anchors
