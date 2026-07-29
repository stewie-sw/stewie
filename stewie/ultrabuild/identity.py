"""Build and source identity for reproducible evidence artifacts."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import subprocess
from typing import Any


def build_identity() -> dict[str, Any]:
    explicit_commit = os.environ.get("STEWIE_EVIDENCE_COMMIT")
    root = Path(__file__).resolve().parents[2]
    commit = explicit_commit
    dirty: bool | None = None
    if commit is None and (root / ".git").exists():
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            commit = completed.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if status.returncode == 0:
            dirty = bool(status.stdout.strip())
    try:
        package_version = importlib.metadata.version("stewie")
    except importlib.metadata.PackageNotFoundError:
        package_version = "source-tree"
    return {
        "code_commit": commit or "unavailable",
        "source_dirty": dirty,
        "package_version": package_version,
    }
