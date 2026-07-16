"""Constant-velocity (CV) process model, n spatial dimensions.

State layout: [p_1..p_n, v_1..v_n]. Process noise is the standard
white-noise-acceleration model with strength sigma_a [m/s^2]:

    Q_axis(dt) = sigma_a^2 * [[dt^4/4, dt^3/2],
                              [dt^3/2, dt^2  ]]

This is deliberately the only model in the demo — richer models (CA/CT/IMM)
are out of scope by design.
"""

import numpy as np

def cv_F(dt: float, dims: int = 3) -> np.ndarray:
    """State transition over dt seconds: p' = p + v*dt, v' = v."""
    if dt < 0:
        raise ValueError(f"dt must be >= 0, got {dt}")
    eye = np.eye(dims)
    return np.block([[eye, dt * eye],
                     [np.zeros((dims, dims)), eye]])

def cv_Q(dt: float, sigma_a: float, dims: int = 3) -> np.ndarray:
    """White-noise-acceleration process noise over dt seconds."""
    if dt < 0:
        raise ValueError(f"dt must be >= 0, got {dt}")
    if sigma_a < 0:
        raise ValueError(f"sigma_a must be >= 0, got {sigma_a}")
    eye = np.eye(dims)
    var = sigma_a ** 2
    q_pp = var * dt ** 4 / 4.0
    q_pv = var * dt ** 3 / 2.0
    q_vv = var * dt ** 2
    return np.block([[q_pp * eye, q_pv * eye],
                     [q_pv * eye, q_vv * eye]])

def cv_H(dims: int = 3) -> np.ndarray:
    """Observation matrix for a full-state (p, v) measurement."""
    return np.eye(2 * dims)
