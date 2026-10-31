"""Materialise the external inputs named in pipeline/*.json manifests into code/.cache/<subdir>/.

Each manifest lists files with a URL and sha256. A file is copied from the manifest's local directory
($<local_dir_env>, default <local_dir_default>) when a hash-matching copy is there, otherwise downloaded.
Every file is verified against its sha256; a mismatch is an error, never a warning.

    python pipeline/fetch.py                     # every manifest
    python pipeline/fetch.py spice_kernels.json  # one manifest
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_ROOT = os.path.normpath(os.path.join(HERE, "..", ".cache"))
MANIFESTS = ("spice_kernels.json", "terrain_sources.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(manifest: str) -> dict[str, str]:
    """Return {file name: cached path} for every entry of `manifest`, fetching what is missing."""
    m = json.load(open(os.path.join(HERE, manifest), encoding="utf-8"))
    cache = os.path.join(CACHE_ROOT, m["cache_subdir"])
    local = os.environ.get(m["local_dir_env"], m["local_dir_default"])
    os.makedirs(cache, exist_ok=True)
    out = {}
    for name, entry in sorted(m["entries"].items()):
        dest = os.path.join(cache, name)
        if not (os.path.isfile(dest) and sha256(dest) == entry["sha256"]):
            src = os.path.join(local, name)
            if os.path.isfile(src) and sha256(src) == entry["sha256"]:
                shutil.copyfile(src, dest)
            else:
                with urllib.request.urlopen(entry["url"], timeout=300) as r, open(dest, "wb") as fh:
                    shutil.copyfileobj(r, fh)
            got = sha256(dest)
            if got != entry["sha256"]:
                os.remove(dest)
                raise RuntimeError(f"{name}: sha256 {got} != manifest {entry['sha256']}")
        out[name] = dest
    return out


if __name__ == "__main__":
    for manifest in sys.argv[1:] or MANIFESTS:
        for path in fetch(manifest).values():
            print(path)
