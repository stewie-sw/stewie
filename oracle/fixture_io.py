"""Golden-fixture writer for the Rust oracle harness (stewie-oracle).

A fixture is two files in a fixture directory:
  <name>.payload.json  the oracle's inputs and outputs (sorted keys, stable formatting)
  <name>.meta.json     {fixture, generator, payload_sha256, sources: {repo-relative path: sha256}}

The Rust loader recomputes the payload hash and every source hash, so a hand-edited payload or a
changed real input (a re-imported DEM, say) fails loudly instead of testing against stale truth.
"""
from __future__ import annotations

import hashlib
import json
import os

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_fixture(out_dir: str, name: str, generator: str, sources: list[str], payload: dict) -> str:
    """Write <name>.payload.json and <name>.meta.json; `sources` are repo-relative real input files."""
    os.makedirs(out_dir, exist_ok=True)
    body = json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    payload_path = os.path.join(out_dir, f"{name}.payload.json")
    with open(payload_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    meta = {
        "fixture": name,
        "generator": generator,
        "payload_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "sources": {rel: sha256_file(os.path.join(REPO, rel)) for rel in sorted(sources)},
    }
    with open(os.path.join(out_dir, f"{name}.meta.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return payload_path
