"""PO-14: deployment documentation + a supported server image, with optional Godot/ROS as explicit
compose PROFILES.

Lives under scripts/ because deploy/ is not on the pytest testpaths (pyproject) but scripts/ is, so this
gate runs in CI. It asserts the DECLARED shape of the deploy, not a live container:

  * deployment docs exist (deploy/DEPLOY.md + deploy/README.md);
  * the supported server image is defined -- Dockerfile.backend + Dockerfile.frontend + the backend and
    frontend compose services;
  * the optional heavy capabilities are opt-in compose PROFILES, and BOTH `ros2` AND `godot` are declared
    (before PO-14, ros2 was a profile but godot was not a profile at all).

The godot render service is GPU-gated (a live render needs the NVIDIA host + the gitignored Godot binary);
PO-14 is the DECLARATION + docs, which are not gated -- so this test checks the profile is declared and
documented, never that a render ran.
"""
from __future__ import annotations

import os

import pytest

yaml = pytest.importorskip("yaml")   # pyyaml is in the dev extra / server lockfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEPLOY = os.path.join(_ROOT, "deploy")


def _compose() -> dict:
    with open(os.path.join(_DEPLOY, "compose.yml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_deployment_docs_exist_and_are_nonempty():  # [REQ:PO-14]
    for name in ("DEPLOY.md", "README.md"):
        p = os.path.join(_DEPLOY, name)
        assert os.path.isfile(p), f"deployment doc {name} missing"
        assert os.path.getsize(p) > 200, f"{name} is a stub"


def test_supported_server_image_is_defined():  # [REQ:PO-14]
    # the supported server image = the backend + frontend Dockerfiles and their compose services.
    for dockerfile in ("Dockerfile.backend", "Dockerfile.frontend"):
        assert os.path.isfile(os.path.join(_DEPLOY, dockerfile)), f"{dockerfile} missing"
    services = _compose()["services"]
    for svc in ("backend", "frontend"):
        assert svc in services, f"compose has no {svc} service (supported server image)"
        assert "build" in services[svc], f"{svc} service does not build an image"
    # the supported services are NOT profile-gated (they come up by default).
    assert "profiles" not in services["backend"] and "profiles" not in services["frontend"], \
        "the supported server image must not be behind an opt-in profile"


def test_optional_capabilities_are_explicit_profiles_including_ros2_and_godot():  # [REQ:PO-14]
    services = _compose()["services"]
    assert "ros2" in services and services["ros2"].get("profiles") == ["ros2"], \
        "ros2 is not declared as an opt-in compose profile"
    assert "godot" in services, "no godot service in compose (PO-14: Godot must be an explicit profile)"
    assert services["godot"].get("profiles") == ["godot"], \
        "godot is not declared as an opt-in compose profile"
    assert "build" in services["godot"], "godot service does not define a buildable image"


def test_godot_profile_is_documented_as_gpu_gated():  # [REQ:PO-14]
    with open(os.path.join(_DEPLOY, "DEPLOY.md"), encoding="utf-8") as f:
        doc = f.read().lower()
    assert "godot" in doc and "profile" in doc, "DEPLOY.md does not document the godot profile"
    assert "gpu" in doc, "DEPLOY.md does not name the godot render GPU gate"
    # the render runtime Dockerfile for the profile exists (Xvfb+Vulkan), even though the binary is host-mounted.
    assert os.path.isfile(os.path.join(_DEPLOY, "Dockerfile.godot")), "Dockerfile.godot missing"
