"""[REQ:TR-01] FROZEN SCENARIOS — a named, pinned, content-hashed slice of a real lunar site.

WHY THIS EXISTS. You cannot train on a world that moves. Recording human demonstrations (or agent rollouts)
only means something if the world those runs happened in is the SAME world you later train and evaluate in.
viz2's world was already deterministic -- the terrain comes from a real DEM, the spawn is a deterministic
flattest-interior search, and the rock field is a seeded Golombek draw -- but two things were missing, and
both are quietly fatal to a training set:

  1. **You could not NAME or CHOOSE a section.** The spawn was implicit (whatever the flattest-interior
     search picked). To pin a section you had to remember raw IAU_2015:30135 coordinates.
  2. **Nothing PROVED the world was unchanged.** There was no fingerprint. If a code change perturbed the
     terrain window, the spawn, or the rock draw, every previously recorded demonstration would silently
     become invalid -- still replayable, still plausible-looking, but recorded in a world that no longer
     exists. Silent invalidation is the worst failure mode a dataset can have.

A Scenario fixes both: it is an immutable declaration of a world (site + section + resolution + rock seed),
and `world_fingerprint()` hashes what that declaration actually PRODUCES -- the real terrain heights in the
window, the resolved spawn, and the real clast field. Pin the fingerprint in a test and any drift in the
world fails LOUDLY, at the moment it happens, instead of poisoning a dataset months later.

It also repairs a dead knob: the rock field was seeded `world_seed=0` HARDCODED in the runtime, while the
stream's `world_seed` config only ever reached the *procedural* (synthetic) bundle path. So on a real site
the seed did nothing. A scenario declares its `rock_seed` and the runtime honours it -- which is also what
makes rock-layout domain randomisation possible later (same terrain, different draw).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(_HERE))
SAMPLES = os.path.join(REPO, "samples", "lunar_dem")
REGISTRY = os.path.join(_HERE, "scenarios.json")


@dataclasses.dataclass(frozen=True)
class Scenario:
    """An immutable declaration of a world. Everything that can change what the rover sees or drives on is
    named here; nothing else may vary between two runs of the same scenario."""

    name: str
    site: str                                   # the REAL DEM bundle under samples/lunar_dem/
    start_xy: tuple[float, float] | None = None  # IAU_2015:30135 metres; None = deterministic auto-spawn
    start_yaw: float = 0.0
    fine_cell_m: float = 0.05
    drum: str = "large"
    rock_seed: int = 0                          # the Golombek draw; now LIVE (was hardcoded 0)

    @property
    def bundle_dir(self) -> str:
        return os.path.join(SAMPLES, self.site)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if d["start_xy"] is not None:
            d["start_xy"] = list(d["start_xy"])
        return d


def load(name: str, registry: str = REGISTRY) -> Scenario:
    """Resolve a NAMED scenario. Naming is the point: a section you can ask for by name, not by
    remembering raw polar-stereographic metres."""
    with open(registry, encoding="utf-8") as fh:
        reg = json.load(fh)
    if name not in reg:
        raise KeyError(f"unknown scenario {name!r}; known: {sorted(reg)}")
    spec = dict(reg[name])
    xy = spec.get("start_xy")
    spec["start_xy"] = (float(xy[0]), float(xy[1])) if xy else None
    return Scenario(name=name, **spec)


def names(registry: str = REGISTRY) -> list[str]:
    with open(registry, encoding="utf-8") as fh:
        return sorted(json.load(fh))


def build_runtime(sc: Scenario, session_dir: str):
    """Construct the real Viz2Runtime this scenario declares. The ONE place a scenario becomes a world, so
    a run and a fingerprint can never disagree about what they were looking at."""
    from stewie.runtime.viz2_runtime import Viz2Runtime
    return Viz2Runtime(
        sc.bundle_dir, session_dir=session_dir, fine_cell_m=sc.fine_cell_m,
        start_xy=sc.start_xy, start_yaw=sc.start_yaw, drum=sc.drum, rock_seed=sc.rock_seed)


def world_fingerprint(sc: Scenario, session_dir: str) -> str:
    """A content hash of the world this scenario ACTUALLY produces -- not of its declaration.

    Hashing the declaration would be circular (it would agree with itself no matter what the code did).
    This hashes the OUTPUT: the real terrain heights in the active window, the resolved spawn, the grid
    resolution, and the real clast field (position + size of every rock the rover can hit). If any of those
    move, previously recorded demonstrations were taken in a different world, and the pinned-fingerprint
    test fails immediately instead of letting a stale dataset look healthy.
    """
    # RELEASE THE RUNTIME. Viz2Runtime.__init__ opens a LISTENING SOCKET (and writes a token file) before
    # start() is ever called, so a fingerprint that builds one and walks away leaks a file descriptor every
    # call. Fingerprinting is exactly the operation you do in a loop -- over scenarios, in tests, in a
    # dataset build -- so the leak compounds fast. `stop()` is safe on an unstarted runtime (its threads are
    # None) and closes the socket + removes the token. Learned the hard way: leaking these destabilised the
    # test process badly enough to SEGFAULT an unrelated native reader several hundred tests later.
    rt = build_runtime(sc, session_dir)
    try:
        h = hashlib.sha256()
        h.update(b"stewie-scenario-v1")
        h.update(sc.site.encode())
        h.update(np.asarray(rt.start_xy, dtype="<f8").tobytes())          # the resolved section
        h.update(np.asarray([rt.ws.fine_cell_m], dtype="<f8").tobytes())  # the grid it is sampled on
        height = rt.ws._require_fine().derive_height()
        h.update(np.ascontiguousarray(height, dtype="<f4").tobytes())     # the terrain itself
        clasts = rt.ws.clasts or []
        h.update(np.asarray([len(clasts)], dtype="<i8").tobytes())
        for c in clasts:                                                  # every rock the rover can hit
            ctr = c.get("center_m", [0.0, 0.0, 0.0])
            h.update(np.asarray([float(ctr[0]), float(ctr[1]), float(ctr[2]),
                                 float(c.get("radius_m", 0.0))], dtype="<f8").tobytes())
        return h.hexdigest()
    finally:
        rt.stop()
