import numpy as np
import pytest

from kalmanlib import kf

def test_predict_matches_hand_computation():
    x = np.array([1.0, 2.0])
    P = np.eye(2)
    F = np.array([[1.0, 0.5], [0.0, 1.0]])
    Q = 0.1 * np.eye(2)
    x2, P2 = kf.predict(x, P, F, Q)
    assert np.allclose(x2, [2.0, 2.0])
    assert np.allclose(P2, F @ P @ F.T + Q)

def test_predict_does_not_mutate_inputs():
    x = np.array([1.0, 2.0])
    P = np.eye(2)
    x_copy, P_copy = x.copy(), P.copy()
    kf.predict(x, P, np.eye(2), np.eye(2))
    assert np.array_equal(x, x_copy) and np.array_equal(P, P_copy)

def test_update_golden_1d_repeated_measurements():
    """Static scalar target: after n measurements of variance r starting from a
    diffuse prior, the posterior mean → sample mean, variance → r/n."""
    rng = np.random.default_rng(7)
    truth, r, n = 5.0, 0.5, 200
    zs = truth + rng.normal(0.0, np.sqrt(r), size=n)
    x, P = np.array([0.0]), np.array([[1e6]])
    H, R = np.eye(1), np.array([[r]])
    for z in zs:
        x, P = kf.update(x, P, np.array([z]), H, R)
    assert abs(x[0] - zs.mean()) < 1e-3
    assert abs(P[0, 0] - r / n) < 1e-4

def test_update_joseph_form_keeps_covariance_symmetric_psd():
    rng = np.random.default_rng(3)
    x = rng.normal(size=4)
    A = rng.normal(size=(4, 4))
    P = A @ A.T + 1e-6 * np.eye(4)
    H = np.eye(4)[:2]
    R = np.diag([1e-9, 1e-9])                 # tiny R stresses roundoff
    for _ in range(50):
        x, P = kf.update(x, P, rng.normal(size=2), H, R)
    assert np.allclose(P, P.T)
    assert np.linalg.eigvalsh(P).min() > -1e-12

def test_update_moves_estimate_toward_measurement():
    x, P = np.array([0.0]), np.array([[1.0]])
    x2, P2 = kf.update(x, P, np.array([2.0]), np.eye(1), np.array([[1.0]]))
    assert 0.0 < x2[0] < 2.0
    assert P2[0, 0] < P[0, 0]

def test_shape_validation():
    with pytest.raises(ValueError):
        kf.predict(np.zeros(2), np.eye(3), np.eye(2), np.eye(2))
    with pytest.raises(ValueError):
        kf.predict(np.zeros(2), np.eye(2), np.eye(3), np.eye(2))
    with pytest.raises(ValueError):
        kf.update(np.zeros(2), np.eye(2), np.zeros(1), np.eye(2), np.eye(1))
    with pytest.raises(ValueError):
        kf.update(np.zeros(2), np.eye(2), np.zeros(2), np.eye(2), np.eye(1))

def test_nis_is_chi_square_scaled():
    x, P = np.array([0.0]), np.array([[1.0]])
    val = kf.nis(x, P, np.array([2.0]), np.eye(1), np.array([[1.0]]))
    assert val == pytest.approx(4.0 / 2.0)     # y^2 / (P + R)
