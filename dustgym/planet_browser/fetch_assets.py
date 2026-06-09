"""Fetch the real LOLA Haworth DEM, which is NOT bundled in the wheel -- it is downloaded and
CHECKSUM-VERIFIED post-install (keeps the wheel light). Source of truth: PGDA Product 78
(see assets_manifest.json). Downloads each asset from a configurable base (env DUSTGYM_DEM_URL or
--source; supports http(s):// and file:// mirrors), verifies its SHA256 against the manifest, and
REFUSES on mismatch -- the DEM must be the genuine PGDA ingest, never fabricated/corrupt terrain.
Idempotent: an asset already present with the right checksum is skipped.

  dustgym-fetch-dem --source https://<mirror>/haworth_10km_5m   # or file:///abs/dir, or $DUSTGYM_DEM_URL
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_MANIFEST = os.path.join(_HERE, "assets_manifest.json")
_REPO_ROOT = os.path.dirname(_HERE)            # holds samples/


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: str = _MANIFEST) -> dict:
    with open(path) as f:
        return json.load(f)


def dem_dest_dir(manifest: dict | None = None, repo_root: str = _REPO_ROOT) -> str:
    return os.path.join(repo_root, (manifest or load_manifest())["dest_rel"])


def is_present(manifest: dict | None = None, repo_root: str = _REPO_ROOT) -> bool:
    """True iff every manifest asset exists at the destination with the manifest checksum."""
    m = manifest or load_manifest()
    d = dem_dest_dir(m, repo_root)
    for a in m["assets"]:
        p = os.path.join(d, a["name"])
        if not os.path.isfile(p) or _sha256(p) != a["sha256"]:   # a DIRECTORY at the path crashed
            return False                                          # the checksum read (audit L34)
    return True


def fetch(source_base: str, *, manifest: dict | None = None, repo_root: str = _REPO_ROOT,
          force: bool = False) -> list:
    """Download each manifest asset from ``source_base/<name>``, verify SHA256 (+ size), place under
    dest_rel. ``source_base`` is an http(s):// or file:// prefix mirroring the asset files."""
    m = manifest or load_manifest()
    d = dem_dest_dir(m, repo_root)
    os.makedirs(d, exist_ok=True)
    fetched = []
    for a in m["assets"]:
        dest = os.path.join(d, a["name"])
        if not force and os.path.exists(dest) and _sha256(dest) == a["sha256"]:
            continue                            # idempotent: already present + verified
        url = source_base.rstrip("/") + "/" + a["name"]
        tmp = dest + ".part"
        urllib.request.urlretrieve(url, tmp)    # noqa: S310 -- operator-supplied mirror of a public DEM
        got = _sha256(tmp)
        if got != a["sha256"]:
            os.remove(tmp)
            raise ValueError(
                f"checksum mismatch for {a['name']}: got {got[:12]}, expected {a['sha256'][:12]} -- refusing "
                "(the DEM must be the verified PGDA Product-78 ingest, not fabricated/corrupt terrain)")
        if a.get("bytes") and os.path.getsize(tmp) != a["bytes"]:
            os.remove(tmp)
            raise ValueError(f"size mismatch for {a['name']}")
        os.replace(tmp, dest)
        fetched.append(a["name"])
    return fetched


def main(argv=None) -> int:
    m = load_manifest()
    ap = argparse.ArgumentParser(description="Fetch + checksum-verify the real LOLA Haworth DEM (PGDA Product 78).")
    ap.add_argument("--source", default=os.environ.get("DUSTGYM_DEM_URL"),
                    help="base URL/dir mirroring the asset files (http(s):// or file://); see assets_manifest.json")
    ap.add_argument("--force", action="store_true", help="re-download even if present")
    a = ap.parse_args(argv)
    if is_present(m) and not a.force:
        print("DEM already present + checksum-verified at", dem_dest_dir(m))
        return 0
    if not a.source:
        print("DEM not present. Provide --source <url | file://dir> mirroring the assets, or set "
              "DUSTGYM_DEM_URL.\nSource of truth:", m["source"])
        return 2
    got = fetch(a.source, manifest=m, force=a.force)
    print("fetched + verified:", got or "(all already present)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
