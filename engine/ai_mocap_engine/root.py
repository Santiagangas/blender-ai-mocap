"""Root (pelvis) trajectory estimation from a single uncalibrated camera.

MediaPipe world landmarks are hip-centred, so the global displacement has to
be recovered separately. We use a pinhole model with an assumed horizontal
field of view: depth is inferred from the apparent size of the body
(metric 3D segment length vs. its length in pixels). This is an ESTIMATE:
the absolute scale depends on the assumed FOV and depth is noisy for
motions towards the camera.
"""

import math

import numpy as np

from .skeleton import J, SIZE_SEGMENTS, FOOT_JOINTS, camera_to_contract
from .temporal import median_filter_1d, zero_phase_one_euro


def estimate_depth(world_cam, image, confidence, width, height, hfov_deg):
    """Per-frame camera distance to the pelvis, in metres."""
    focal = 0.5 * width / math.tan(math.radians(hfov_deg) * 0.5)
    px = image * np.array([width, height], dtype=np.float64)
    estimates = []
    for a, b in SIZE_SEGMENTS:
        ia, ib = J[a], J[b]
        l3 = np.linalg.norm(world_cam[:, ia] - world_cam[:, ib], axis=-1)
        l2 = np.linalg.norm(px[:, ia] - px[:, ib], axis=-1)
        ok = (np.minimum(confidence[:, ia], confidence[:, ib]) > 0.5) & (l2 > 4.0)
        d = np.where(ok, focal * l3 / np.maximum(l2, 1e-6), np.nan)
        estimates.append(d)
    estimates = np.stack(estimates, axis=1)
    # Foreshortening can only shrink a 2D length, which inflates its depth
    # estimate, so the least-foreshortened segments give the lowest values.
    with np.errstate(all="ignore"):
        depth = np.nanpercentile(estimates, 25, axis=1)
    if np.all(np.isnan(depth)):
        depth = np.full(len(depth), 3.0)
    idx = np.flatnonzero(~np.isnan(depth))
    depth = np.interp(np.arange(len(depth)), idx, depth[idx])
    return depth, focal


def estimate_root(world_cam, image, confidence, width, height, fps,
                  hfov_deg=60.0, depth_smoothing_hz=0.5):
    """Return the pelvis trajectory in contract space (metres).

    X/Y are relative to the first frame; Z is the pelvis height above the
    ground plane, which is placed under the lowest foot contacts.
    """
    depth, focal = estimate_depth(world_cam, image, confidence, width, height, hfov_deg)
    depth = median_filter_1d(depth, max(3, int(fps * 0.5)))
    depth = zero_phase_one_euro(depth, fps, min_cutoff=depth_smoothing_hz, beta=0.05)

    px = image * np.array([width, height], dtype=np.float64)
    hip_px = 0.5 * (px[:, J["left_hip"]] + px[:, J["right_hip"]])
    cx, cy = 0.5 * width, 0.5 * height
    x = (hip_px[:, 0] - cx) * depth / focal
    y_down = (hip_px[:, 1] - cy) * depth / focal
    root_cam = np.stack([x, y_down, depth], axis=1)
    root = camera_to_contract(root_cam)  # (x, depth, up)

    # Ground plane: lowest foot point over time (robust percentile) -> z = 0.
    feet = camera_to_contract(world_cam[:, list(FOOT_JOINTS)])  # hip-relative
    lowest = root[:, 2] + feet[:, :, 2].min(axis=1)
    ground = np.percentile(lowest, 5)
    root[:, 2] -= ground
    root[:, 0] -= root[0, 0]
    root[:, 1] -= root[0, 1]
    return root, depth
