import numpy as np

from ai_mocap.retarget import rotations as R

rng = np.random.default_rng(7)


def random_rotations(n):
    q = R.normalize(rng.normal(size=(n, 4)))
    return R.matrix_from_quat(q)


def test_quat_matrix_roundtrip():
    m = random_rotations(500)
    m2 = R.matrix_from_quat(R.quat_from_matrix(m))
    assert np.allclose(m, m2, atol=1e-9)


def test_quat_from_matrix_handles_180_degrees():
    for axis in np.eye(3):
        m = R.axis_angle_matrix(axis, np.pi)
        assert np.allclose(R.matrix_from_quat(R.quat_from_matrix(m)), m, atol=1e-9)


def test_rotation_between_maps_a_to_b_including_antiparallel():
    a = R.normalize(rng.normal(size=(200, 3)))
    b = R.normalize(rng.normal(size=(200, 3)))
    b[:5] = -a[:5]
    m = R.rotation_between(a, b)
    assert np.allclose(R.apply(m, a), b, atol=1e-7)
    assert np.allclose(np.linalg.det(m), 1.0, atol=1e-7)


def test_frame_is_orthonormal_right_handed():
    f = R.frame(rng.normal(size=(100, 3)), rng.normal(size=(100, 3)))
    assert np.allclose(R.transpose(f) @ f, np.eye(3), atol=1e-9)
    assert np.allclose(np.linalg.det(f), 1.0)


def test_fraction_scales_angle():
    m = R.axis_angle_matrix([0, 0, 1], np.radians(80))
    half = R.fraction(m, 0.5)
    assert np.isclose(np.degrees(R.angle_between_rotations(np.eye(3), half)), 40.0)


def test_make_continuous_removes_sign_flips():
    q = np.tile([[1.0, 0.0, 0.0, 0.0]], (6, 1))
    q[3:] *= -1
    out = R.make_continuous(q)
    assert np.all(np.sum(out[1:] * out[:-1], axis=1) > 0)
