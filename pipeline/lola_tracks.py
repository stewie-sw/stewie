"""Fetch the LOLA RDR shot extracts named in pipeline/lola_tracks.json into code/.cache/lola/ (RW-60c, D-R105).

Each box is one ODE Granular Data System query for simple topography (longitude, latitude, radius minus 1,737.4 km);
the service answers with a short-lived file URL, so the extract is pinned by its query and sha256, not by URL. A
cached file whose hash matches is kept; anything else is fetched and verified, and a mismatch is an error.

    python pipeline/lola_tracks.py           # fetch and verify
    python pipeline/lola_tracks.py --pin     # (re)record the hashes after a deliberate change of boxes
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request

import fetch

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "lola_tracks.json")


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=600) as r:      # noqa: S310 -- the pinned PDS endpoint
        return r.read()


def query_url(endpoint: str, box: dict) -> str:
    params = {"query": "lolardr", "results": "u", "output": "XML"}
    params.update({k: box[k] for k in ("minlat", "maxlat", "westernlon", "easternlon")})
    return endpoint + "?" + urllib.parse.urlencode(params)


def fetch_box(endpoint: str, box: dict, dest: str) -> None:
    """Run the box's query and save the simple-topography CSV it returns."""
    xml = _get(query_url(endpoint, box)).decode("utf-8")
    if "<Status>Success</Status>" not in xml:
        raise RuntimeError(f"ODE query failed: {xml[:400]}")
    urls = re.findall(r"<URL>([^<]*topo_simple_csv\.csv)</URL>", xml)
    if len(urls) != 1:
        raise RuntimeError(f"ODE returned {len(urls)} CSV files: {xml[:400]}")
    data = _get(urls[0])
    with open(dest, "wb") as fh:
        fh.write(data)


def main(pin: bool) -> dict[str, str]:
    m = json.load(open(MANIFEST, encoding="utf-8"))
    cache = os.path.join(fetch.CACHE_ROOT, m["cache_subdir"])
    os.makedirs(cache, exist_ok=True)
    out = {}
    for name, box in sorted(m["boxes"].items()):
        dest = os.path.join(cache, f"{name}.csv")
        want = box.get("sha256")
        if not (os.path.exists(dest) and want and fetch.sha256(dest) == want):
            fetch_box(m["endpoint"], box, dest)
        got = fetch.sha256(dest)
        if pin:
            box["sha256"] = got
            box["rows"] = sum(1 for _ in open(dest, encoding="ascii")) - 1
        elif got != want:
            raise RuntimeError(f"{name}: sha256 {got} != pinned {want}")
        out[name] = dest
        print(f"{name}: {dest}")
    if pin:
        with open(MANIFEST, "w", encoding="utf-8") as fh:
            json.dump(m, fh, indent=2)
            fh.write("\n")
    return out


if __name__ == "__main__":
    main("--pin" in sys.argv[1:])
