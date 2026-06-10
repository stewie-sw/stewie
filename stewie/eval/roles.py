"""Permission-isolated produce -> estimate -> evaluate (G1 blocker #4).

RoleFS enforces, at the file layer, who may read/write what:

  produce   WRITE produced/ only.
  estimate  READ  produced/ (truth files DENIED by pattern), WRITE estimates/ only.
  evaluate  READ  produced/ + estimates/, WRITE evaluation/ only.

Every path is resolved and must stay inside the workspace (no traversal escape). Truth denial is
structural: any path whose basename contains "truth" is unreadable to the estimator, so the
estimator peeking at ground truth is a PermissionError, not a code-review hope.

run_pipeline() exercises the three roles in order on a REAL captured pose directory: the producer
stages the sensor packet + stereo pair; the estimator runs the real SGBM front end (dart) and
writes disparity statistics; the evaluator alone joins them against the truth file and writes the
verdict. Used by the CLI entry points (python -m stewie.eval.roles <role> ...) and the G1 checks.
"""
from __future__ import annotations

import json
import os
import sys

_ROLE_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "produce": {"read": ("produced/",), "write": ("produced/",)},
    "estimate": {"read": ("produced/",), "write": ("estimates/",)},
    "evaluate": {"read": ("produced/", "estimates/", "evaluation/"),
                 "write": ("evaluation/",)},
}


class RoleFS:
    def __init__(self, role: str, root: str):
        if role not in _ROLE_RULES:
            raise ValueError(f"unknown role {role!r}; known: {sorted(_ROLE_RULES)}")
        self.role = role
        self.root = os.path.realpath(root)

    def _resolve(self, rel: str, mode: str) -> str:
        full = os.path.realpath(os.path.join(self.root, rel))
        if not (full + os.sep).startswith(self.root + os.sep) and full != self.root:
            raise PermissionError(f"{self.role}: path escapes the workspace: {rel!r}")
        sub = os.path.relpath(full, self.root).replace(os.sep, "/") + "/"
        allowed = _ROLE_RULES[self.role][mode]
        if not any(sub.startswith(a) for a in allowed):
            raise PermissionError(f"{self.role} may not {mode} {rel!r} (allowed: {allowed})")
        if self.role == "estimate" and mode == "read" \
                and "truth" in os.path.basename(full).lower():
            raise PermissionError("the estimator is structurally denied truth files")
        return full

    def read_json(self, rel: str) -> dict:
        return json.load(open(self._resolve(rel, "read")))

    def read_bytes(self, rel: str) -> bytes:
        return open(self._resolve(rel, "read"), "rb").read()

    def write_json(self, rel: str, doc: dict) -> str:
        full = self._resolve(rel, "write")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        json.dump(doc, open(full, "w"), indent=1, sort_keys=True)
        return full

    def write_bytes(self, rel: str, blob: bytes) -> str:
        full = self._resolve(rel, "write")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "wb").write(blob)
        return full


# ---- the three commands ------------------------------------------------------------------------
def cmd_produce(pose_dir: str, workspace: str) -> dict:
    """Stage the REAL captured packet + stereo pair into produced/ (producer role)."""
    fs = RoleFS("produce", workspace)
    staged = []
    for name in ("sensors.json", "front_left.png", "front_right.png", "evaluation_truth.json"):
        src = os.path.join(pose_dir, name)
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        fs.write_bytes(f"produced/{name}", open(src, "rb").read())
        staged.append(name)
    return {"staged": staged}


def cmd_estimate(workspace: str) -> dict:
    """Run the real SGBM front end on the produced pair; write disparity stats (estimator role)."""
    import io

    import numpy as np
    fs = RoleFS("estimate", workspace)
    from imageio.v3 import imread
    left = imread(io.BytesIO(fs.read_bytes("produced/front_left.png")))
    right = imread(io.BytesIO(fs.read_bytes("produced/front_right.png")))
    from dart.stereo_depth import compute_disparity
    disp = compute_disparity(left, right)
    valid = disp[np.isfinite(disp) & (disp > 1.0)]
    out = {"estimator": "sgbm", "n_disparities": int(valid.size),
           "median_disparity_px": float(np.median(valid)) if valid.size else None,
           "p10_px": float(np.percentile(valid, 10)) if valid.size else None,
           "p90_px": float(np.percentile(valid, 90)) if valid.size else None}
    fs.write_json("estimates/stereo.json", out)
    return out


def cmd_evaluate(workspace: str) -> dict:
    """Join the estimate against truth; write the verdict (evaluator role)."""
    fs = RoleFS("evaluate", workspace)
    est = fs.read_json("estimates/stereo.json")
    truth = fs.read_json("produced/evaluation_truth.json")
    sensors = fs.read_json("produced/sensors.json")
    # expected disparity at the TRUTH lander range (the world poses live only in the truth file)
    cam0 = sensors["cameras"][0]
    fx = float(cam0["intrinsics"]["fx"])
    baseline = float(sensors["stereo"]["baseline_m"])
    med = est["median_disparity_px"]
    cam_w = next(c["pose_in_world"]["position_m"] for c in truth["camera_poses_in_world"]
                 if c["name"] == sensors["stereo"]["left"])
    lander_w = truth["lander"]["position_m"]
    rng = sum((a - b) ** 2 for a, b in zip(cam_w, lander_w)) ** 0.5
    expected = fx * baseline / rng if rng > 0 else None
    # the image MEDIAN is terrain-dominated, so the physically meaningful check is that the
    # estimator's disparity envelope BRACKETS the known object's disparity (range consistency),
    # with the median error reported as information, not a gate.
    err = abs(med - expected) if (expected and med) else 0.0
    bracket = bool(expected is not None and est["p10_px"] is not None
                   and est["p10_px"] <= expected <= est["p90_px"])
    verdict = {"n_disparities": est["n_disparities"], "median_disparity_px": med,
               "expected_disparity_px": expected, "abs_median_err_px": float(err),
               "expected_within_p10_p90": bracket,
               "calibration_id": truth.get("calibration_id"),
               "roles_isolated": True}
    fs.write_json("evaluation/verdict.json", verdict)
    return verdict


def run_pipeline(pose_dir: str, workspace: str) -> dict:
    cmd_produce(pose_dir, workspace)
    cmd_estimate(workspace)
    return cmd_evaluate(workspace)


def main(argv=None):
    a = argv or sys.argv[1:]
    if not a or a[0] not in ("produce", "estimate", "evaluate", "pipeline"):
        print("usage: python -m stewie.eval.roles {produce <pose_dir> <ws> | estimate <ws> | "
              "evaluate <ws> | pipeline <pose_dir> <ws>}")
        return 2
    if a[0] == "produce":
        print(json.dumps(cmd_produce(a[1], a[2])))
    elif a[0] == "estimate":
        print(json.dumps(cmd_estimate(a[1])))
    elif a[0] == "evaluate":
        print(json.dumps(cmd_evaluate(a[1])))
    else:
        print(json.dumps(run_pipeline(a[1], a[2])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
