"""Temporal reconstruction: gap filling and jitter filtering.

All functions operate on arrays shaped (F, ...) where F is the frame axis.
"""

import math

import numpy as np


def fill_gaps(values, valid):
    """Interpolate frames where ``valid`` is False, per joint and channel.

    values: (F, J, C) array, may contain NaN where invalid.
    valid:  (F, J) bool.
    Returns (filled, interpolated_mask, never_seen_joints_mask).
    Edges are held at the nearest valid value. Joints that are never valid
    are left at zero and reported in ``never_seen``.
    """
    values = np.array(values, dtype=np.float64, copy=True)
    F, Jn, C = values.shape
    frames = np.arange(F)
    interpolated = ~valid
    never_seen = np.zeros(Jn, dtype=bool)
    for j in range(Jn):
        idx = np.flatnonzero(valid[:, j])
        if idx.size == 0:
            values[:, j, :] = 0.0
            never_seen[j] = True
            continue
        for c in range(C):
            values[:, j, c] = np.interp(frames, idx, values[idx, j, c])
    return values, interpolated, never_seen


def trust_long_gaps(valid, detected, max_gap):
    """Accept the detector's own estimate during long low-confidence stretches.

    A joint hidden behind the body (side views, crossed legs) gets low
    confidence for many frames, yet the detector still places it plausibly.
    Interpolating such a stretch would freeze the limb in a pose from another
    moment, so only short gaps (glitches) stay invalid and get interpolated.

    valid: (F, J) bool, confidence above threshold.
    detected: (F,) bool, a person was found in the frame.
    max_gap: longest run (frames) that is still interpolated.
    Returns (new_valid, trusted_mask).
    """
    valid = np.array(valid, dtype=bool, copy=True)
    trusted = np.zeros_like(valid)
    F, Jn = valid.shape
    for j in range(Jn):
        f = 0
        while f < F:
            if valid[f, j]:
                f += 1
                continue
            end = f
            while end < F and not valid[end, j]:
                end += 1
            if end - f > max_gap:
                run = np.zeros(F, dtype=bool)
                run[f:end] = True
                run &= detected
                trusted[run, j] = True
                valid[run, j] = True
            f = end
    return valid, trusted


def flip_front_back(world_cam, image, conf, swap_index):
    """The monocular front/back alternative of a pose: left/right labels swapped
    and depth mirrored around the pelvis (2D projections stay identical)."""
    w = world_cam[:, swap_index].copy()
    w[..., 2] = -w[..., 2]
    return w, image[:, swap_index], conf[:, swap_index]


def resolve_facing(world_cam, swap_index, lr_pairs, initial="camera", fps=30.0):
    """Choose, per frame, between the detected pose and its front/back flip so
    that body orientation is temporally continuous (Viterbi, 2 states).

    world_cam: (F, J, 3) camera-space joints (gap-filled).
    lr_pairs: [(left_idx, right_idx), ...] joints defining the body's left axis.
    initial: "camera" (subject starts facing the camera) or "auto".
    Returns a bool array: True where the flipped interpretation is chosen.
    """
    F = len(world_cam)

    def left_axis(w):
        v = sum(w[:, l] - w[:, r] for l, r in lr_pairs)
        v = np.stack([v[:, 0], v[:, 2]], axis=-1)  # horizontal plane (x, z)
        return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)

    flipped = world_cam[:, swap_index].copy()
    flipped[..., 2] = -flipped[..., 2]  # same as flip_front_back, world part only
    axes = np.stack([left_axis(world_cam), left_axis(flipped)], axis=1)  # (F, 2, 2)

    # Unary: tiny preference for the detector's own answer; strong prior on
    # the first half second when the subject is known to face the camera
    # (facing the camera <=> the body's left axis points image-right, +x).
    unary = np.zeros((F, 2))
    unary[:, 1] = 0.02
    if initial == "camera":
        n0 = max(1, int(0.5 * fps))
        facing_away = 0.5 * (1.0 - axes[:n0, :, 0])  # 0 facing camera .. 1 facing away
        unary[:n0] += 2.0 * facing_away
    cost = unary[0].copy()
    back = np.zeros((F, 2), dtype=np.int8)
    for t in range(1, F):
        # pairwise[s_prev, s] = angle between consecutive left axes
        cosang = np.clip(np.einsum("pi,si->ps", axes[t - 1], axes[t]), -1.0, 1.0)
        total = cost[:, None] + np.arccos(cosang)
        back[t] = np.argmin(total, axis=0)
        cost = total[back[t], [0, 1]] + unary[t]
    states = np.zeros(F, dtype=np.int8)
    states[-1] = int(np.argmin(cost))
    for t in range(F - 1, 0, -1):
        states[t - 1] = back[t, states[t]]
    return states.astype(bool)


def _alpha(cutoff, dt):
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


def one_euro(values, fps, min_cutoff=1.5, beta=0.5, d_cutoff=1.0):
    """Causal One-Euro filter (Casiez et al. 2012), vectorised over channels.

    Low speed -> strong smoothing (removes jitter); high speed -> cutoff rises
    so fast motions are not lagged.
    """
    x = np.asarray(values, dtype=np.float64)
    out = np.empty_like(x)
    if len(x) == 0:
        return out
    dt = 1.0 / float(fps)
    a_d = _alpha(d_cutoff, dt)
    prev = x[0].copy()
    d_prev = np.zeros_like(prev)
    out[0] = prev
    for i in range(1, len(x)):
        dx = (x[i] - prev) / dt
        d_hat = a_d * dx + (1.0 - a_d) * d_prev
        cutoff = min_cutoff + beta * np.abs(d_hat)
        tau = 1.0 / (2.0 * math.pi * cutoff)
        a = 1.0 / (1.0 + tau / dt)
        prev = a * x[i] + (1.0 - a) * prev
        out[i] = prev
        d_prev = d_hat
    return out


def zero_phase_one_euro(values, fps, min_cutoff=1.5, beta=0.5):
    """Forward + backward One-Euro averaged: removes the causal lag.

    Offline processing has the whole sequence, so causality is not needed.
    """
    x = np.asarray(values, dtype=np.float64)
    fwd = one_euro(x, fps, min_cutoff, beta)
    bwd = one_euro(x[::-1], fps, min_cutoff, beta)[::-1]
    return 0.5 * (fwd + bwd)


def smoothing_to_cutoff(strength):
    """Map a user smoothing strength in [0, 1] to a One-Euro min cutoff (Hz)."""
    s = min(max(float(strength), 0.0), 1.0)
    # 0 -> 6 Hz (almost raw), 1 -> 0.4 Hz (very smooth); geometric interpolation.
    return 6.0 * (0.4 / 6.0) ** s


def median_filter_1d(x, window):
    """Running median along axis 0 (odd window, edges use shrinking window)."""
    x = np.asarray(x, dtype=np.float64)
    window = max(1, int(window) | 1)
    if window == 1 or len(x) < 3:
        return x.copy()
    half = window // 2
    out = np.empty_like(x)
    for i in range(len(x)):
        lo, hi = max(0, i - half), min(len(x), i + half + 1)
        out[i] = np.nanmedian(x[lo:hi], axis=0)
    return out
