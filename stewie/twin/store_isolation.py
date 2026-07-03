"""[REQ:EG-03] DB/branch isolation by environment mode.

The store a session writes is a FUNCTION OF ITS MODE: each mode resolves a physically separate store root
(``<base_dir>/<store>``), so a TRAINING write can never land in the LIVE store. This is minimal
directory-namespace isolation over the existing file-based Terrain-Memory persistence
(:mod:`stewie.twin.terrain_memory`) -- NOT a new database engine; the same ``load_site`` / ``save_site``,
rooted per mode. Writing the LIVE (accepted-world) store additionally requires ``modify_accepted_world``
authority (EG-02), so it fails closed for any non-LIVE session.

Wiring: this is the mode-isolated store API; existing callers that pass a raw ``data_dir`` are unchanged
(byte-identical). Threading the active session mode into every WorldStateService/router call site is the
remaining EG-03 integration (a [REQ:EG-03] follow-up), not duplicated here.
"""
from __future__ import annotations

import os

from stewie.contracts.governance import EnvironmentMode, require_authority
from stewie.twin import terrain_memory as TM

#: PRD §29.3 stores. The six modes map onto the four stores (dev/training/live/archive); LIVE alone -> "live".
STORE_FOR_MODE: dict[EnvironmentMode, str] = {
    EnvironmentMode.DEV: "dev",
    EnvironmentMode.TRAINING: "training",
    EnvironmentMode.REHEARSAL: "training",      # mission sim on real configs -> training-adjacent, non-live
    EnvironmentMode.LIVE: "live",
    EnvironmentMode.REPLAY: "archive",          # read-only historical reconstruction -> the archive store
    EnvironmentMode.ARCHIVE: "archive",
}
LIVE_STORE = STORE_FOR_MODE[EnvironmentMode.LIVE]


def store_key(mode: EnvironmentMode | str) -> str:
    """The store partition (dev/training/live/archive) a mode's data lives in (§29.3). LIVE alone -> 'live'."""
    return STORE_FOR_MODE[EnvironmentMode(mode)]


def store_root(mode: EnvironmentMode | str, base_dir: str = "data") -> str:
    """The mode-isolated store root ``<base_dir>/<store_key(mode)>``. Distinct per store; LIVE is physically
    separate, so a non-LIVE session never resolves the live store. Pure function of ``(mode, base_dir)``."""
    return os.path.join(base_dir, store_key(mode))


def require_live_store_write(mode: EnvironmentMode | str) -> None:
    """Guard a write to the LIVE (accepted-world) store: only a mode granting ``modify_accepted_world`` (LIVE)
    may (EG-02). A training/rehearsal/replay/dev/archive session is rejected -> it cannot reach live state."""
    require_authority(mode, "modify_accepted_world")


def save_site_for_mode(mode: EnvironmentMode | str, base_dir: str, memory) -> str:
    """Persist a site's Terrain Memory into the MODE'S OWN store (structural isolation). A write into the LIVE
    store additionally requires ``modify_accepted_world`` authority."""
    if store_key(mode) == LIVE_STORE:
        require_live_store_write(mode)
    return TM.save_site(store_root(mode, base_dir), memory)


def load_site_for_mode(mode: EnvironmentMode | str, base_dir: str, site: str):
    """Load a site's Terrain Memory from the MODE'S OWN store (or None if nothing recorded there yet)."""
    return TM.load_site(store_root(mode, base_dir), site)
