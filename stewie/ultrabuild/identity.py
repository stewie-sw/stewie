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
    commit: str | None = None
    commit_status = "unavailable"
    dirty: bool | None = None
    if explicit_commit is not None:
        if len(explicit_commit) == 40 and all(
            character in "0123456789abcdef" for character in explicit_commit
        ):
            commit = explicit_commit
            commit_status = "externally_declared"
    elif (root / ".git").exists():
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            discovered = completed.stdout.strip()
            if len(discovered) == 40 and all(
                character in "0123456789abcdef" for character in discovered
            ):
                commit = discovered
                commit_status = "repository_discovered"
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
        "code_commit_status": commit_status,
        "source_dirty": dirty,
        "package_version": package_version,
    }
