"""The fixture reproducibility gate's comparison rules, on SYNTHETIC inputs (labelled): ULP drift passes, a real
change fails, a digest may differ only where it hashes a file the gate compares numerically itself."""
from __future__ import annotations

import io
import json

import numpy as np

from scripts import check_fixtures_reproduce as C


def _check(path: str, old, new) -> C.Drift:
    d = C.Drift()
    d.file(path, json.dumps(old).encode(), json.dumps(new).encode())
    return d


def test_float_drift_within_tolerance_passes_and_a_real_change_fails():
    ok = _check("x.payload.json", {"v": [14.25314616988004, 9.16420583960906e-11]},
                {"v": [14.253146170714738, 9.164209636354707e-11]})       # the runner's measured drift
    assert ok.errors == [] and ok.drifted == {"x.payload.json"}
    bad = _check("x.payload.json", {"v": [14.25]}, {"v": [14.26]})
    assert len(bad.errors) == 1


def test_structure_strings_integers_and_booleans_are_exact():
    for old, new in (({"a": 1}, {"a": 2}), ({"a": "s"}, {"a": "t"}), ({"a": True}, {"a": False}),
                     ({"a": [1.0]}, {"a": [1.0, 2.0]}), ({"a": 1.0}, {"b": 1.0}), ({"a": 1}, {"a": 1.0})):
        assert _check("x.payload.json", old, new).errors, (old, new)


def test_digests_drift_only_where_the_hashed_file_is_compared_itself():
    meta_old = {"payload_sha256": "a" * 64, "sources": {"crates/x/fixtures/y.json": "b" * 64, "lode/z.py": "c" * 64}}
    drifted = dict(meta_old, payload_sha256="d" * 64, sources={**meta_old["sources"], "crates/x/fixtures/y.json": "e" * 64})
    assert _check("f.meta.json", meta_old, drifted).errors == []
    edited_source = dict(meta_old, sources={**meta_old["sources"], "lode/z.py": "f" * 64})
    assert _check("f.meta.json", meta_old, edited_source).errors           # a source edit without regeneration
    pkg = {"ephemeris": {"header": {"bytes": 2593, "sha256": "a" * 64}}, "layers": [{"sha256": "b" * 64}]}
    pkg_drift = {"ephemeris": {"header": {"bytes": 2594, "sha256": "c" * 64}}, "layers": [{"sha256": "b" * 64}]}
    assert _check("pipeline/packages/p.json", pkg, pkg_drift).errors == []
    pkg_layer = {"ephemeris": pkg["ephemeris"], "layers": [{"sha256": "d" * 64}]}
    assert _check("pipeline/packages/p.json", pkg, pkg_layer).errors      # a source-data layer is pinned exactly


def test_binary_coefficients_and_npz_arrays_compare_numerically():
    a = np.array([1.0, 2.0, 3.0])
    d = C.Drift()
    d.file("e.bin", a.astype("<f8").tobytes(), (a * (1 + 1e-15)).astype("<f8").tobytes())
    assert d.errors == []
    d.file("e.bin", a.astype("<f8").tobytes(), (a + 1e-3).astype("<f8").tobytes())
    assert len(d.errors) == 1

    def npz(**arrays) -> bytes:
        buf = io.BytesIO()
        np.savez(buf, **arrays)
        return buf.getvalue()
    d = C.Drift()
    d.file("t.npz", npz(h=a, m=np.array([1, 2])), npz(h=a * (1 + 1e-14), m=np.array([1, 2])))
    assert d.errors == []
    d.file("t.npz", npz(h=a, m=np.array([1, 2])), npz(h=a, m=np.array([1, 3])))
    assert len(d.errors) == 1


def test_fit_coefficients_compare_against_their_array_scale():
    # SYNTHETIC coefficients: a small one moving by far more than 1e-9 of itself, but by 1e-15 of the series scale
    a = np.array([3.0e8, 27.934642494691257, 1.0e5])
    b = a.copy()
    b[1] = 27.93464275185851                                               # the runner's measured drift
    d = C.Drift()
    d.file("e.bin", a.astype("<f8").tobytes(), b.astype("<f8").tobytes())
    assert d.errors == []
    b[1] = 28.5                                                           # a real change
    d.file("e.bin", a.astype("<f8").tobytes(), b.astype("<f8").tobytes())
    assert len(d.errors) == 1
