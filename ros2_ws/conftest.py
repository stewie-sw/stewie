"""Host-side pytest path shim for the ROS2 workspace: put every package root on sys.path so the
per-package import gates run without a colcon build/install step (in a real workspace, colcon's
install space provides this). Test dirs are rootless (no __init__.py) with unique basenames."""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
for pkg in sorted(_SRC.iterdir()) if _SRC.is_dir() else []:
    if pkg.is_dir() and (pkg / "setup.py").exists() and str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
