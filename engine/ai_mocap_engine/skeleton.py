"""Joint layout of the engine output (MediaPipe BlazePose topology, 33 joints)
and the camera -> Blender coordinate conversion."""

import numpy as np

JOINT_NAMES = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
)
J = {name: i for i, name in enumerate(JOINT_NAMES)}
NUM_JOINTS = len(JOINT_NAMES)

# Joints used to measure the apparent body size (depth estimation).
SIZE_SEGMENTS = (
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_hip", "left_knee"), ("right_hip", "right_knee"),
    ("left_knee", "left_ankle"), ("right_knee", "right_ankle"),
    ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("left_shoulder", "left_elbow"), ("right_shoulder", "right_elbow"),
)


def _mirror_name(name):
    for a, b in (("left_", "right_"), ("right_", "left_")):
        if name.startswith(a):
            return b + name[len(a):]
    for a, b in (("_left", "_right"), ("_right", "_left")):
        if name.endswith(a):
            return name[:-len(a)] + b
    return name


# Index permutation that swaps every left joint with its right counterpart.
SWAP_LR = tuple(J[_mirror_name(n)] for n in JOINT_NAMES)

# Pairs defining the body's left-right axis (used for facing resolution).
LR_AXIS_PAIRS = ((J["left_hip"], J["right_hip"]), (J["left_shoulder"], J["right_shoulder"]))

FOOT_JOINTS = tuple(J[n] for n in (
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index"))

# Camera space (MediaPipe): +X image right, +Y image down, +Z away from camera.
# Contract space (Blender): +X image right, +Y away from camera, +Z up.
# A subject facing the camera therefore faces -Y, like a Mixamo character.
CAMERA_TO_CONTRACT = np.array([
    [1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.0, -1.0, 0.0],
], dtype=np.float64)


def camera_to_contract(points):
    """Convert (..., 3) camera-space points to contract space."""
    return points @ CAMERA_TO_CONTRACT.T
