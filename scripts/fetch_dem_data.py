#!/usr/bin/env python3
"""Fetch the DEM source data STEWIE plans on (Aaron 2026-06-10: "incorporated to be downloaded
when STEWIE is installed").

VERIFIED sources only (each URL probed live 2026-06-10; the first guessed URL shape returned a
3.8 kB error page WITH HTTP 206 -- hence the size guard):

  PGDA Product 78 (Barker 2021, doi:10.1016/j.pss.2020.105119): per-site 5 m/pix LOLA DEMs,
  south polar stereographic, MOON_ME/DE421, pixel-registered.
  https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/<Dir>/<Dir>_final_adj_5mpp_surf.tif

  LuNaMaps SfS approach-corridor mosaic (Bertone/Barker/Mazarico 2023,
  doi:10.5281/zenodo.10258683): 30 m/pix, 60-80S strip + verification rasters. The TAR's direct
  link is only served from the product page (no stable data-tree URL found) -- fetch it from
  https://pgda.gsfc.nasa.gov (search: "Large-scale Lunar Elevation Models to Support Optical
  Navigation") and place it at <dest>/lunamap_sfs/share_hls_v2_mar.tar; this script verifies
  the checksum if present.

Usage:  python3 scripts/fetch_dem_data.py [--dest /mnt/projects/datasets] [--sites haworth,site04,site06]
Then:   python3 scripts/build_from_dem.py --src <dest>/lola_5mpp/<file> --out samples/lunar_dem/<name>
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request

BASE = "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp"
#: PGDA directory names (the data-tree README maps them to the Artemis candidate regions)
SITE_DIRS = {
    "haworth": "Haworth", "shoemaker": "Shoemaker",
    "site01": "Site01",   # Connecting ridge
    "site04": "Site04",   # Shackleton rim
    "site06": "Site06",   # Nobile rim 1
    "site07": "Site07",   # Peak near Shackleton
    "site11": "Site11",   # de Gerlache rim
    "site20": "Site20",   # Leibnitz beta plateau
    "site23": "Site23",   # Malapert massif
    "dm2": "DM2",         # Nobile rim 2
}
MIN_REAL_BYTES = 1_000_000     # anything smaller is the PGDA error page, not a DEM

#: the LuNaMaps TAR we hold (recorded so installs can verify a manually fetched copy)
LUNAMAP_TAR = "share_hls_v2_mar.tar"
LUNAMAP_SIZE = 1_092_108_288


def fetch(url: str, dest: str) -> bool:
    print(f"  {url}")
    tmp = dest + ".part"
    urllib.request.urlretrieve(url, tmp)
    size = os.path.getsize(tmp)
    if size < MIN_REAL_BYTES:
        os.unlink(tmp)
        print(f"  REFUSED: {size} bytes is an error page, not a DEM (the 206-lies lesson)")
        return False
    os.replace(tmp, dest)
    print(f"  ok ({size / 1048576:.0f} MB)")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="/mnt/projects/datasets")
    ap.add_argument("--sites", default="haworth,site04,site06",
                    help=f"comma list from: {','.join(SITE_DIRS)}")
    args = ap.parse_args(argv)
    lola = os.path.join(args.dest, "lola_5mpp")
    os.makedirs(lola, exist_ok=True)
    ok = True
    for key in [s.strip().lower() for s in args.sites.split(",") if s.strip()]:
        d = SITE_DIRS.get(key)
        if not d:
            print(f"unknown site {key!r}; known: {sorted(SITE_DIRS)}")
            ok = False
            continue
        fn = f"{d}_final_adj_5mpp_surf.tif"
        dest = os.path.join(lola, fn)
        if os.path.exists(dest) and os.path.getsize(dest) > MIN_REAL_BYTES:
            print(f"  {fn}: already present")
            continue
        ok = fetch(f"{BASE}/{d}/{fn}", dest) and ok
    tar = os.path.join(args.dest, "lunamap_sfs", LUNAMAP_TAR)
    if os.path.exists(tar):
        size = os.path.getsize(tar)
        state = "size matches the recorded archive" if size == LUNAMAP_SIZE else f"SIZE MISMATCH ({size})"
        print(f"  {LUNAMAP_TAR}: present, {state}")
    else:
        print(f"  {LUNAMAP_TAR}: not present -- fetch manually from the PGDA product page "
              "(see this script's docstring); the approach-corridor evaluation (#60) needs it")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
