"""Round-trip tests of the retargeting maths on the real X Bot rest pose.

Landmarks are synthesised from the character's own rest skeleton, so the
expected bone rotations are known exactly.
"""

import numpy as np
import pytest

from ai_mocap.retarget import rotations as R
from ai_mocap.retarget import solver as S

HIP_HEIGHT_M = 1.0


def rest_landmarks(rig, settings=S.SolverSettings()):
    """33 contract-space landmarks (metres, pelvis-relative) matching the rest pose."""
    rc = S.capture_to_armature_matrix(rig)
    left, up, fwd = S.canonical_axes(rig)
    pts = {}
    for side, (sh, el, wr, idx, pky, hip, kn, an, ft) in {
            "L": (11, 13, 15, 19, 17, 23, 25, 27, 31),
            "R": (12, 14, 16, 20, 18, 24, 26, 28, 32)}.items():
        pts[sh] = rig.head(f"upper_arm.{side}")
        pts[el] = rig.head(f"forearm.{side}")
        pts[wr] = rig.head(f"hand.{side}")
        pts[idx] = rig.head(f"index1.{side}")
        pts[pky] = rig.head(f"pinky1.{side}")
        pts[hip] = rig.head(f"thigh.{side}")
        pts[kn] = rig.head(f"shin.{side}")
        pts[an] = rig.head(f"foot.{side}")
        pts[ft] = rig.head(f"toe_end.{side}")
    head = rig.head("head")
    pitch = np.radians(settings.head_pitch_offset_deg)
    pts[7], pts[8] = head + 8 * left, head - 8 * left
    pts[0] = head + 10 * (np.cos(pitch) * fwd - np.sin(pitch) * up)
    hip_mid = 0.5 * (pts[23] + pts[24])
    arm = np.array([pts.get(j, hip_mid) for j in range(33)])
    scale = 0.01  # armature units (cm) -> metres
    return ((arm - hip_mid) * scale) @ rc  # rc^T maps armature -> contract


def solve_frames(rig, world, settings=None):
    F = world.shape[0]
    root = np.zeros((F, 3))
    root[:, 2] = HIP_HEIGHT_M
    return S.solve(rig, world, root, settings or S.SolverSettings())


def angle_deg(q):
    return np.degrees(2 * np.arccos(np.clip(np.abs(q[..., 0]), -1, 1)))


def rotate_points(world, ids, center, rot):
    out = world.copy()
    for j in ids:
        out[:, j] = (world[:, j] - center) @ rot.T + center
    return out


def test_rest_pose_gives_identity(xbot_rig):
    world = rest_landmarks(xbot_rig)[None].repeat(3, axis=0)
    res = solve_frames(xbot_rig, world)
    assert len(res.quaternions) == 18
    for name, q in res.quaternions.items():
        assert angle_deg(q).max() < 1e-4, name
    assert np.abs(res.root_location).max() < 1e-6


def test_whole_body_turn_only_rotates_hips(xbot_rig):
    world = rest_landmarks(xbot_rig)[None]
    turn = R.axis_angle_matrix([0, 0, 1], np.radians(40))
    world = world @ turn.T
    res = solve_frames(xbot_rig, world)
    hips = xbot_rig.mapping["hips"]
    assert angle_deg(res.quaternions[hips])[0] == pytest.approx(40, abs=1e-3)
    for name, q in res.quaternions.items():
        if name != hips:
            assert angle_deg(q)[0] < 1e-3, name


def test_raising_straight_arm_rotates_only_upper_arm(xbot_rig):
    world = rest_landmarks(xbot_rig)[None]
    raise_ = R.axis_angle_matrix([0, 1, 0], np.radians(-60))  # left arm up
    world = rotate_points(world, [13, 15, 17, 19, 21], world[0, 11], raise_)
    res = solve_frames(xbot_rig, world)
    m = xbot_rig.mapping
    assert angle_deg(res.quaternions[m["upper_arm.L"]])[0] == pytest.approx(60, abs=1e-3)
    assert angle_deg(res.quaternions[m["forearm.L"]])[0] < 1e-3
    assert angle_deg(res.quaternions[m["hand.L"]])[0] < 1e-3
    assert angle_deg(res.quaternions[m["upper_arm.R"]])[0] < 1e-3


def test_elbow_flex_is_a_pure_hinge(xbot_rig):
    world = rest_landmarks(xbot_rig)[None]
    flex = R.axis_angle_matrix([0, 0, -1], np.radians(90))  # left forearm forward
    world = rotate_points(world, [15, 17, 19, 21], world[0, 13], flex)
    res = solve_frames(xbot_rig, world)
    m = xbot_rig.mapping
    assert angle_deg(res.quaternions[m["forearm.L"]])[0] == pytest.approx(90, abs=1e-3)
    assert angle_deg(res.quaternions[m["upper_arm.L"]])[0] < 1e-3


def test_knee_flex_and_root_height(xbot_rig):
    world = rest_landmarks(xbot_rig)[None]
    flex = R.axis_angle_matrix([1, 0, 0], np.radians(70))  # shin swings back
    world = rotate_points(world, [27, 29, 31], world[0, 25], flex)
    res = solve_frames(xbot_rig, world)
    m = xbot_rig.mapping
    assert angle_deg(res.quaternions[m["shin.L"]])[0] == pytest.approx(70, abs=1e-3)
    assert angle_deg(res.quaternions[m["thigh.L"]])[0] < 1e-3


def test_root_modes(xbot_rig):
    world = rest_landmarks(xbot_rig)[None].repeat(2, axis=0)
    root = np.array([[0.0, 0.0, HIP_HEIGHT_M], [0.5, 0.0, HIP_HEIGHT_M]])
    full = S.solve(xbot_rig, world, root, S.SolverSettings(root_mode="FULL"))
    vert = S.solve(xbot_rig, world, root, S.SolverSettings(root_mode="VERTICAL"))
    none = S.solve(xbot_rig, world, root, S.SolverSettings(root_mode="NONE"))
    assert none.root_location is None
    assert np.abs(vert.root_location).max() < 1e-6
    moved = np.linalg.norm(full.root_location[1] - full.root_location[0])
    assert moved == pytest.approx(0.5 * full.scale_factor, rel=1e-6)
