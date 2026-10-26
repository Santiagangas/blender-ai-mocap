"""Vectorised rotation helpers (numpy only). Arrays are (..., 3, 3) matrices
or (..., 4) quaternions in (w, x, y, z) order, matching Blender."""

import numpy as np

EPS = 1e-9


def normalize(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.maximum(n, EPS)


def dot(a, b):
    return np.sum(a * b, axis=-1)


def frame(primary, secondary):
    """Orthonormal frame with columns (e1, e2, e3): e1 along ``primary``,
    e2 = ``secondary`` orthogonalised against e1, e3 = e1 x e2."""
    e1 = normalize(primary)
    s = secondary - e1 * dot(secondary, e1)[..., None]
    e2 = normalize(s)
    e3 = np.cross(e1, e2)
    return np.stack([e1, e2, e3], axis=-1)


def transpose(m):
    return np.swapaxes(m, -1, -2)


def apply(m, v):
    """Rotate vectors v (..., 3) by matrices m (..., 3, 3)."""
    return np.einsum("...ij,...j->...i", m, v)


def rotation_between(a, b):
    """Minimal rotation taking direction a onto direction b (vectorised)."""
    a, b = normalize(a), normalize(b)
    a, b = np.broadcast_arrays(a, b)
    v = np.cross(a, b)
    c = dot(a, b)
    shape = a.shape[:-1]
    k = np.zeros(shape + (3, 3))
    k[..., 0, 1], k[..., 0, 2] = -v[..., 2], v[..., 1]
    k[..., 1, 0], k[..., 1, 2] = v[..., 2], -v[..., 0]
    k[..., 2, 0], k[..., 2, 1] = -v[..., 1], v[..., 0]
    eye = np.broadcast_to(np.eye(3), shape + (3, 3))
    factor = 1.0 / np.maximum(1.0 + c, EPS)
    r = eye + k + (k @ k) * factor[..., None, None]
    anti = c < -0.999999
    if np.any(anti):
        # 180 degrees about any axis perpendicular to a.
        aa = a[anti]
        helper = np.where(np.abs(aa[:, :1]) < 0.9, [[1.0, 0.0, 0.0]], [[0.0, 1.0, 0.0]])
        axis = normalize(np.cross(aa, helper))
        r[anti] = 2.0 * axis[:, :, None] * axis[:, None, :] - np.eye(3)
    return r


def quat_from_matrix(m):
    """Shepperd's method, vectorised. Returns unit quaternions (w, x, y, z)."""
    m = np.asarray(m, dtype=np.float64)
    m00, m11, m22 = m[..., 0, 0], m[..., 1, 1], m[..., 2, 2]
    tr = m00 + m11 + m22
    cand = np.stack([tr, m00, m11, m22], axis=-1)
    choice = np.argmax(cand, axis=-1)
    q = np.empty(m.shape[:-2] + (4,))

    def _set(mask, w, x, y, z):
        q[mask, 0], q[mask, 1], q[mask, 2], q[mask, 3] = w[mask], x[mask], y[mask], z[mask]

    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.sqrt(np.maximum(tr + 1.0, 0.0)) * 2.0
        _set(choice == 0, 0.25 * s, (m[..., 2, 1] - m[..., 1, 2]) / s,
             (m[..., 0, 2] - m[..., 2, 0]) / s, (m[..., 1, 0] - m[..., 0, 1]) / s)
        s = np.sqrt(np.maximum(1.0 + m00 - m11 - m22, 0.0)) * 2.0
        _set(choice == 1, (m[..., 2, 1] - m[..., 1, 2]) / s, 0.25 * s,
             (m[..., 0, 1] + m[..., 1, 0]) / s, (m[..., 0, 2] + m[..., 2, 0]) / s)
        s = np.sqrt(np.maximum(1.0 - m00 + m11 - m22, 0.0)) * 2.0
        _set(choice == 2, (m[..., 0, 2] - m[..., 2, 0]) / s, (m[..., 0, 1] + m[..., 1, 0]) / s,
             0.25 * s, (m[..., 1, 2] + m[..., 2, 1]) / s)
        s = np.sqrt(np.maximum(1.0 - m00 - m11 + m22, 0.0)) * 2.0
        _set(choice == 3, (m[..., 1, 0] - m[..., 0, 1]) / s, (m[..., 0, 2] + m[..., 2, 0]) / s,
             (m[..., 1, 2] + m[..., 2, 1]) / s, 0.25 * s)
    q = normalize(q)
    return np.where(q[..., :1] < 0, -q, q)


def matrix_from_quat(q):
    q = normalize(q)
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    m = np.empty(q.shape[:-1] + (3, 3))
    m[..., 0, 0] = 1 - 2 * (y * y + z * z)
    m[..., 0, 1] = 2 * (x * y - z * w)
    m[..., 0, 2] = 2 * (x * z + y * w)
    m[..., 1, 0] = 2 * (x * y + z * w)
    m[..., 1, 1] = 1 - 2 * (x * x + z * z)
    m[..., 1, 2] = 2 * (y * z - x * w)
    m[..., 2, 0] = 2 * (x * z - y * w)
    m[..., 2, 1] = 2 * (y * z + x * w)
    m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def axis_angle_matrix(axis, angle):
    axis = normalize(np.asarray(axis, dtype=np.float64))
    half = 0.5 * np.asarray(angle, dtype=np.float64)
    q = np.concatenate([np.cos(half)[..., None], axis * np.sin(half)[..., None]], axis=-1)
    return matrix_from_quat(q)


def fraction(m, t):
    """Rotation ``m`` scaled to fraction ``t`` of its angle (slerp from identity)."""
    q = quat_from_matrix(m)  # w >= 0 -> shortest arc
    angle = 2.0 * np.arccos(np.clip(q[..., 0], -1.0, 1.0))
    axis = normalize(q[..., 1:])
    return axis_angle_matrix(axis, angle * np.asarray(t, dtype=np.float64))


def make_continuous(quats):
    """Flip quaternion signs along axis 0 so consecutive keys stay in the same
    hemisphere (prevents 360-degree flips when interpolating keyframes)."""
    q = np.array(quats, dtype=np.float64, copy=True)
    for i in range(1, len(q)):
        if np.dot(q[i], q[i - 1]) < 0.0:
            q[i] = -q[i]
    return q


def angle_between_rotations(a, b):
    """Geodesic angle (radians) between rotation matrices."""
    r = transpose(a) @ b
    tr = np.clip((np.trace(r, axis1=-2, axis2=-1) - 1.0) * 0.5, -1.0, 1.0)
    return np.arccos(tr)
