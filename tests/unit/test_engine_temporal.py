import numpy as np

from ai_mocap_engine.skeleton import (CAMERA_TO_CONTRACT, J, JOINT_NAMES, LR_AXIS_PAIRS,
                                      SWAP_LR, camera_to_contract)
from ai_mocap_engine.temporal import (fill_gaps, flip_front_back, one_euro, resolve_facing,
                                      smoothing_to_cutoff, zero_phase_one_euro)


def test_camera_to_contract_is_a_proper_rotation():
    assert np.isclose(np.linalg.det(CAMERA_TO_CONTRACT), 1.0)
    # camera "up" (-y) becomes +Z, "away" (+z) becomes +Y
    assert np.allclose(camera_to_contract(np.array([0.0, -1.0, 0.0])), [0, 0, 1])
    assert np.allclose(camera_to_contract(np.array([0.0, 0.0, 1.0])), [0, 1, 0])


def test_swap_table_is_an_involution():
    swap = np.array(SWAP_LR)
    assert np.array_equal(swap[swap], np.arange(len(JOINT_NAMES)))
    assert JOINT_NAMES[SWAP_LR[J["left_knee"]]] == "right_knee"
    assert SWAP_LR[J["nose"]] == J["nose"]


def test_fill_gaps_interpolates_and_holds_edges():
    x = np.zeros((5, 1, 1))
    x[:, 0, 0] = [np.nan, 1.0, np.nan, 3.0, np.nan]
    valid = ~np.isnan(x[:, :, 0])
    out, interp, never = fill_gaps(x, valid)
    assert np.allclose(out[:, 0, 0], [1, 1, 2, 3, 3])
    assert interp[:, 0].tolist() == [True, False, True, False, True]
    assert not never.any()


def test_one_euro_preserves_constant_and_reduces_noise():
    rng = np.random.default_rng(0)
    const = np.full((100, 3), 2.0)
    assert np.allclose(one_euro(const, 30), const)
    noisy = np.sin(np.linspace(0, 3, 300))[:, None] + rng.normal(0, 0.05, (300, 1))
    smooth = zero_phase_one_euro(noisy, 30, min_cutoff=smoothing_to_cutoff(0.5), beta=0.3)
    clean = np.sin(np.linspace(0, 3, 300))[:, None]
    assert np.abs(smooth - clean).mean() < 0.5 * np.abs(noisy - clean).mean()


def _standing_pose():
    w = np.zeros((33, 3))
    # camera space, subject facing the camera: left side at +x, chest towards camera (-z)
    w[J["left_hip"]], w[J["right_hip"]] = [0.1, 0, 0], [-0.1, 0, 0]
    w[J["left_shoulder"]], w[J["right_shoulder"]] = [0.18, -0.5, 0], [-0.18, -0.5, 0]
    w[J["nose"]] = [0, -0.7, -0.1]
    return w


def test_resolve_facing_repairs_front_back_flips():
    F = 40
    world = np.repeat(_standing_pose()[None], F, axis=0)
    image = np.zeros((F, 33, 2))
    conf = np.ones((F, 33))
    bad = np.zeros(F, dtype=bool)
    bad[10:18] = True
    bad[:3] = True  # detector starts with the wrong interpretation
    fw, _, _ = flip_front_back(world[bad], image[bad], conf[bad], list(SWAP_LR))
    world[bad] = fw
    flip = resolve_facing(world, list(SWAP_LR), LR_AXIS_PAIRS, "camera", 30)
    assert np.array_equal(flip, bad)
