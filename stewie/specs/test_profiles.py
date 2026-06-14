import json
import os

import pytest

from stewie.bridge import sensor_io
from stewie.specs.profiles import (
    MixedProfileError,
    ProfileError,
    available_profiles,
    get_profile,
    load_profile,
    validate_sensor_frame,
)
from stewie.specs.system_profile import IPExSpecs
from dart.camera_rig import CameraRig

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "frame", "runtime_sensors.json")


def test_packaged_profiles_validate_and_have_distinct_geometry():
    assert available_profiles() == ("OFFICIAL_LAC_2025_UNVERIFIED", "STEWIE_IPEX_V1")
    stewie = load_profile("stewie")
    official = load_profile("official")
    assert stewie.status == "VERIFIED"
    assert official.status == "UNVERIFIED"
    assert stewie.data["stereo"]["front"]["baseline_m"] == 0.07
    assert official.data["stereo"]["front"]["baseline_m"] == 0.162
    assert stewie.sha256 != official.sha256


def test_unverified_profile_cannot_be_required_as_verified():
    with pytest.raises(ProfileError, match="verified data was required"):
        load_profile("official", require_verified=True)


def test_environment_selects_profile(monkeypatch):
    monkeypatch.setenv("SOLNAV_PROFILE", "official")
    assert get_profile().profile_id == "OFFICIAL_LAC_2025_UNVERIFIED"


def test_runtime_stewie_frame_matches_stewie_profile():
    frame = sensor_io.read_sensors(FIX)
    validate_sensor_frame(load_profile("stewie"), frame)
    rig = CameraRig.from_sensors(FIX, "stewie")
    assert rig.profile.profile_id == "STEWIE_IPEX_V1"


def test_runtime_stewie_frame_rejected_by_official_profile():
    frame = sensor_io.read_sensors(FIX)
    with pytest.raises(MixedProfileError, match="profile_id|camera set mismatch|baseline"):
        validate_sensor_frame(load_profile("official"), frame)
    with pytest.raises(MixedProfileError):
        CameraRig.from_sensors(FIX, "official")


def test_profile_drives_ipex_specs():
    stewie = IPExSpecs.from_profile("stewie")
    official = IPExSpecs.from_profile("official")
    assert stewie.profile_id == "STEWIE_IPEX_V1"
    assert stewie.pack_wh == 1332.0
    assert official.pack_wh == 283.0
    assert stewie.stereo_baseline_m == 0.07
    assert official.stereo_baseline_m == 0.162


@pytest.mark.parametrize("mutation,match", [
    (lambda d: d["stereo"]["front"].update(baseline_m=0.1), "baseline mismatch"),
    (lambda d: d["cameras"]["optics"].update(fx_px=100.0), "inconsistent"),
])
def test_invalid_profile_is_rejected(tmp_path, mutation, match):
    profile = load_profile("stewie")
    data = json.loads(json.dumps(profile.data))
    mutation(data)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ProfileError, match=match):
        load_profile(str(path))
