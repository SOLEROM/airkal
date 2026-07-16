import numpy as np
import pytest

from kalmanlib import models

def test_cv_F_propagates_position_by_velocity():
    F = models.cv_F(2.0)
    x = np.array([1.0, 2.0, 3.0, 0.5, -0.5, 0.0])
    x2 = F @ x
    assert np.allclose(x2[:3], [2.0, 1.0, 3.0])
    assert np.allclose(x2[3:], x[3:])

def test_cv_F_identity_at_zero_dt():
    assert np.allclose(models.cv_F(0.0), np.eye(6))

def test_cv_Q_zero_at_zero_dt_and_psd():
    assert np.allclose(models.cv_Q(0.0, 3.0), np.zeros((6, 6)))
    Q = models.cv_Q(1.7, 3.0)
    assert np.allclose(Q, Q.T)
    assert np.linalg.eigvalsh(Q).min() >= -1e-12

def test_cv_Q_grows_with_dt_and_sigma():
    q1 = models.cv_Q(1.0, 3.0)[0, 0]
    q2 = models.cv_Q(2.0, 3.0)[0, 0]
    assert q2 > q1
    assert models.cv_Q(1.0, 6.0)[0, 0] == pytest.approx(4 * q1)

def test_cv_Q_block_values():
    dt, sa = 0.5, 2.0
    Q = models.cv_Q(dt, sa)
    assert Q[0, 0] == pytest.approx(sa**2 * dt**4 / 4)
    assert Q[0, 3] == pytest.approx(sa**2 * dt**3 / 2)
    assert Q[3, 3] == pytest.approx(sa**2 * dt**2)
    assert Q[0, 1] == 0.0                     # axes are independent

def test_negative_inputs_raise():
    with pytest.raises(ValueError):
        models.cv_F(-0.1)
    with pytest.raises(ValueError):
        models.cv_Q(-0.1, 3.0)
    with pytest.raises(ValueError):
        models.cv_Q(0.1, -3.0)

def test_cv_H_full_state():
    assert np.allclose(models.cv_H(), np.eye(6))
