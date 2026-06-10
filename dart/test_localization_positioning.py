import numpy as np
import pytest

from dart import localization as pos


def test_multipoint_triangulate_three_rays():
    target = np.array([3.0, 4.0])
    centers = [[0, 0], [6, 0], [0, 8]]
    bearings = [np.degrees(np.arctan2(target[1]-c[1], target[0]-c[0])) for c in centers]
    est = pos.multipoint_triangulate(centers, bearings)
    assert np.allclose(est, target, atol=1e-6)


def test_resection_fixes_rover_from_known_landmarks():
    rover = np.array([2.0, 1.5])
    lms = [[10, 0], [0, 10], [-8, -3]]
    # world bearings FROM the rover TO each landmark
    wb = [np.degrees(np.arctan2(L[1]-rover[1], L[0]-rover[0])) for L in lms]
    est = pos.resect_position(lms, wb)
    assert np.allclose(est, rover, atol=1e-6)


def test_trilateration_from_ranges():
    rover = np.array([2.0, 1.5])
    lms = [[10, 0], [0, 10], [-8, -3], [5, 5]]
    ranges = [np.linalg.norm(np.array(L) - rover) for L in lms]
    est = pos.trilaterate(lms, ranges)
    assert np.allclose(est, rover, atol=1e-6)


def test_trilateration_needs_three():
    with pytest.raises(ValueError):
        pos.trilaterate([[0, 0], [1, 0]], [1.0, 1.0])


def test_residual_zero_for_consistent_rays():
    target = np.array([3.0, 4.0]); centers = [[0, 0], [6, 0], [0, 8]]
    bearings = [np.degrees(np.arctan2(target[1]-c[1], target[0]-c[0])) for c in centers]
    assert pos.triangulation_residual_m(target, centers, bearings) < 1e-9
