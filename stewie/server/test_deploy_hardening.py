"""Deploy-file regressions: O-04 (duplicate COPY) and S-13 (supply-chain pinning).

O-04: deploy/Dockerfile.backend copied `stewie` twice (a wasted layer). The COPY must appear once.

S-13: the docs build installed mkdocs-material UNPINNED, and the Docker base used a mutable tag with
no digest. Pin them: the mkdocs install carries a version (==), and the Dockerfile bases are pinned by
digest (@sha256:).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_deploy_hardening.py -q
"""
from __future__ import annotations

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel: str) -> str:
    with open(os.path.join(_ROOT, rel)) as f:
        return f.read()


def test_dockerfile_backend_copies_stewie_once():
    """O-04: the `COPY stewie ./stewie` line must appear exactly once (the duplicate is removed)."""
    text = _read("deploy/Dockerfile.backend")
    copies = [ln for ln in text.splitlines()
              if re.match(r"\s*COPY\s+stewie\s+\./stewie\s*$", ln)]
    assert len(copies) == 1, f"expected exactly one `COPY stewie ./stewie`, found {len(copies)} (O-04)"


def test_mkdocs_material_install_is_pinned():
    """S-13: the docs workflow must pin mkdocs-material to a version (no bare `pip install`)."""
    text = _read(".github/workflows/pages.yml")
    install_lines = [ln for ln in text.splitlines() if "mkdocs-material" in ln and "pip install" in ln]
    assert install_lines, "no mkdocs-material install line found"
    for ln in install_lines:
        assert "==" in ln, f"mkdocs-material is installed UNPINNED (S-13): {ln.strip()!r}"


def test_dockerfiles_pin_base_image_by_digest():
    """S-13: production images must pin the base by digest (@sha256:), not a mutable tag, so a rebuild
    from the same revision uses the same bytes."""
    for df in ("deploy/Dockerfile.backend", "deploy/Dockerfile.frontend"):
        text = _read(df)
        from_lines = [ln for ln in text.splitlines() if ln.strip().upper().startswith("FROM ")]
        assert from_lines, f"{df} has no FROM line"
        for ln in from_lines:
            # a multi-stage `FROM base AS x` that references a prior local stage is fine; only external
            # image references (with a registry tag) must be digest-pinned.
            ref = ln.split()[1]
            if ":" in ref and "/" not in ref.split(":")[0] and "@sha256:" not in ref:
                # e.g. python:3.12-slim -> external image with a mutable tag, no digest
                assert "@sha256:" in ln, f"{df} base is not digest-pinned (S-13): {ln.strip()!r}"
