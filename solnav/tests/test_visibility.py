"""Visibility-as-measurement on the real Haworth DEM."""
import os
import sys

from solnav.world import visibility as V

sys.path.insert(0, os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym"))
_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


class _LM:
    def __init__(self, i, x, y):
        self.id, self.x, self.y = i, x, y


def test_near_target_visible_and_consistency():
    if not _HAVE:
        return
    from planet_browser import mission_planner as MP
    dem = MP.load_haworth_dem()
    obs = (5000.0, 5000.0)
    assert V.is_visible(dem, (0, 0), obs, (5010.0, 5000.0))      # a target one cell away -> visible
    lms = [_LM(0, 5010, 5000), _LM(1, 5000, 5020), _LM(2, 5300, 5300)]
    pred = V.predict_visibility(dem, (0, 0), obs, lms)
    assert len(pred) == 3 and all(isinstance(v, bool) for _, v in pred)
    visible_ids = [lm.id for lm, v in pred if v]
    assert V.visibility_consistency(pred, visible_ids) == 1.0    # agrees with itself -> max at true pose
