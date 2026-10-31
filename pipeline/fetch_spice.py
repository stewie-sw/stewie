"""Materialise the NAIF kernels named in pipeline/spice_kernels.json into code/.cache/spice/.

Each kernel is copied from $STEWIE_SPICE_DIR (default /mnt/projects/datasets/spice_kernels) when a
hash-matching copy is there, otherwise downloaded from NAIF. Every file is verified against the manifest
sha256; a mismatch is an error, never a warning.

    python pipeline/fetch_spice.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.normpath(os.path.join(HERE, "..", ".cache", "spice"))
LOCAL = os.environ.get("STEWIE_SPICE_DIR", "/mnt/projects/datasets/spice_kernels")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch() -> dict[str, str]:
    manifest = json.load(open(os.path.join(HERE, "spice_kernels.json"), encoding="utf-8"))
    os.makedirs(CACHE, exist_ok=True)
    out = {}
    for name, k in sorted(manifest["kernels"].items()):
        dest = os.path.join(CACHE, name)
        if not (os.path.isfile(dest) and _sha256(dest) == k["sha256"]):
            local = os.path.join(LOCAL, name)
            if os.path.isfile(local) and _sha256(local) == k["sha256"]:
                shutil.copyfile(local, dest)
            else:
                with urllib.request.urlopen(k["url"], timeout=120) as r, open(dest, "wb") as fh:
                    shutil.copyfileobj(r, fh)
            got = _sha256(dest)
            if got != k["sha256"]:
                os.remove(dest)
                raise RuntimeError(f"{name}: sha256 {got} != manifest {k['sha256']}")
        out[name] = dest
    return out


if __name__ == "__main__":
    for path in fetch().values():
        print(path)
    sys.exit(0)
