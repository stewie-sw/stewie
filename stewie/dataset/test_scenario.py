"""[REQ:TR-01] Frozen scenarios: a named section of a real site that does NOT change, proven by a hash.

WHY THIS FILE EXISTS. The point of a frozen scenario is to make recorded runs trainable. A demonstration is
only training data if the world it was recorded in is the world you later train and evaluate in. viz2's
world was already deterministic, but nothing PROVED it -- so a change to the terrain window, the spawn
search, or the rock draw would have silently invalidated every run ever recorded: still replayable, still
plausible, and wrong. Silent invalidation is the worst failure a dataset can have, because nothing tells you.

So the fingerprint below is PINNED. If the world moves for any reason, this test fails the moment it happens
-- loudly, at the change -- instead of quietly poisoning a dataset you only discover months later when a
policy trained on it behaves strangely.

It also pins the repair of a dead knob: the rock field was seeded `world_seed=0` HARDCODED, while the
stream's `world_seed` config only reached the procedural/synthetic path. On a real site the seed did
nothing. A scenario now DECLARES its rock seed and the runtime honours it -- which is what makes rock-layout
domain randomisation (same terrain, different draw) possible at all.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from stewie.dataset import scenario as S

SFS = os.path.join(S.SAMPLES, "haworth_sfs_2km_1m")
pytestmark = pytest.mark.skipif(not os.path.isdir(SFS), reason="real Haworth SfS bundle not on disk")

def test_a_named_scenario_resolves_to_a_real_section() -> None:
    """[REQ:TR-01] You can ASK for a section by name instead of remembering raw 30135 metres."""
    sc = S.load("haworth_pad_a")
    assert sc.site == "haworth_sfs_2km_1m"
    assert sc.start_xy is not None, "a frozen scenario must PIN its section, not auto-pick one"
    assert os.path.isdir(sc.bundle_dir)
    assert "haworth_pad_a" in S.names()


def test_the_same_scenario_yields_a_byte_identical_world_twice() -> None:
    """[REQ:TR-01] The whole premise: same name -> same world. Terrain, spawn, grid AND every rock."""
    sc = S.load("haworth_pad_a")
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        fa = S.world_fingerprint(sc, a)
        fb = S.world_fingerprint(sc, b)
    assert fa == fb, "the same scenario produced two different worlds -- nothing recorded in it is trainable"


def test_the_scenario_honours_its_pinned_section_not_the_auto_spawn() -> None:
    """[REQ:TR-01] A pinned start_xy must actually be used. If the runtime silently fell back to the
    flattest-interior search, the 'section you selected' would not be the section you drove."""
    sc = S.load("haworth_pad_a")
    with tempfile.TemporaryDirectory() as d:
        rt = S.build_runtime(sc, d)
        try:
            assert rt.start_xy == pytest.approx(sc.start_xy), \
                "the runtime ignored the scenario's pinned section"
        finally:
            rt.stop()          # __init__ opens a listening socket; release it (see scenario.py)


def test_the_rock_seed_is_live_and_actually_changes_the_world() -> None:
    """[REQ:TR-01] The seed was a DEAD KNOB (hardcoded 0 for real sites). Prove it is wired: same terrain,
    same spawn, DIFFERENT rock draw -> a different world. This is what makes domain randomisation possible,
    and it is also why a scenario must declare the seed rather than inherit a hidden constant."""
    sc0 = S.load("haworth_pad_a")
    sc9 = S.Scenario(**{**sc0.to_dict(), "start_xy": sc0.start_xy, "rock_seed": 9})
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        f0 = S.world_fingerprint(sc0, a)
        f9 = S.world_fingerprint(sc9, b)
    assert f0 != f9, "changing the rock seed did not change the world -- the seed is still a dead knob"


def test_the_default_seed_preserves_the_world_that_already_existed() -> None:
    """[REQ:TR-01] Making the seed live must NOT move the world out from under anything already recorded.
    rock_seed=0 is the value that was hardcoded, so the default must reproduce the pre-change world."""
    from stewie.runtime.viz2_runtime import Viz2Runtime
    sc = S.load("haworth_pad_a")
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        legacy = Viz2Runtime(sc.bundle_dir, session_dir=a, fine_cell_m=sc.fine_cell_m,
                             start_xy=sc.start_xy)               # no rock_seed -> the old default path
        via_scenario = S.build_runtime(sc, b)                     # rock_seed=0 declared
        try:
            assert (legacy.ws.clasts or []) == (via_scenario.ws.clasts or []), \
                "the declared default seed does not reproduce the pre-change rock field"
        finally:
            legacy.stop(); via_scenario.stop()


def test_the_world_fingerprint_is_pinned() -> None:
    """[REQ:TR-01] THE GUARD THAT PROTECTS THE DATASET. The fingerprint of `haworth_pad_a` is pinned to a
    constant. Any drift in the terrain window, the spawn, or the rock draw changes it and fails HERE --
    which is exactly what you want, because the alternative is a training set that is quietly wrong.

    If this fails after a deliberate world change: every demonstration recorded against the OLD hash is no
    longer valid training data for the NEW world. Re-record or re-label; do not just update the constant."""
    sc = S.load("haworth_pad_a")
    with tempfile.TemporaryDirectory() as d:
        fp = S.world_fingerprint(sc, d)
    expected = os.environ.get("STEWIE_PAD_A_FINGERPRINT", _PINNED)
    assert fp == expected, (
        f"the frozen world MOVED.\n  expected {expected}\n  actual   {fp}\n"
        "Every run recorded against the expected hash was taken in a different world and is NOT valid "
        "training data for this one. Re-record, or deliberately re-pin and invalidate the old dataset.")


#: Pinned by construction from the real bundle (see the module docstring). Changing this constant is a
#: deliberate act that invalidates previously recorded demonstrations.
_PINNED = "8e48b858ae9ccaa1094ac66ad0a05a02512be0f6fe465648064cf5b4e1aaddae"
