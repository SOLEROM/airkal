"""Linear Kalman filter as pure functions: no hidden state, inputs untouched,
new (x, P) returned every call. Update uses the Joseph form, which stays
symmetric positive semi-definite under roundoff.
"""

import numpy as np

def _check_square(name: str, m: np.ndarray, n: int) -> None:
    if m.shape != (n, n):
        raise ValueError(f"{name} must be {n}x{n}, got {m.shape}")

def predict(x: np.ndarray, P: np.ndarray, F: np.ndarray,
            Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Time update: x' = F x, P' = F P Fᵀ + Q."""
    x = np.asarray(x, dtype=float).reshape(-1)
    n = x.shape[0]
    P = np.asarray(P, dtype=float)
    F = np.asarray(F, dtype=float)
    Q = np.asarray(Q, dtype=float)
    _check_square("P", P, n)
    _check_square("F", F, n)
    _check_square("Q", Q, n)
    x_new = F @ x
    P_new = F @ P @ F.T + Q
    return x_new, 0.5 * (P_new + P_new.T)

def update(x: np.ndarray, P: np.ndarray, z: np.ndarray, H: np.ndarray,
           R: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Measurement update (Joseph form): returns posterior (x, P)."""
    x = np.asarray(x, dtype=float).reshape(-1)
    n = x.shape[0]
    z = np.asarray(z, dtype=float).reshape(-1)
    m = z.shape[0]
    P = np.asarray(P, dtype=float)
    H = np.asarray(H, dtype=float)
    R = np.asarray(R, dtype=float)
    _check_square("P", P, n)
    _check_square("R", R, m)
    if H.shape != (m, n):
        raise ValueError(f"H must be {m}x{n}, got {H.shape}")

    y = z - H @ x                       # innovation
    S = H @ P @ H.T + R                 # innovation covariance
    K = P @ H.T @ np.linalg.solve(S.T, np.eye(m)).T   # K = P Hᵀ S⁻¹
    x_new = x + K @ y
    ikh = np.eye(n) - K @ H
    P_new = ikh @ P @ ikh.T + K @ R @ K.T
    return x_new, 0.5 * (P_new + P_new.T)

def nis(x: np.ndarray, P: np.ndarray, z: np.ndarray, H: np.ndarray,
        R: np.ndarray) -> float:
    """Normalized innovation squared — consistency metric for tests/telemetry."""
    x = np.asarray(x, dtype=float).reshape(-1)
    z = np.asarray(z, dtype=float).reshape(-1)
    H = np.asarray(H, dtype=float)
    y = z - H @ x
    S = H @ np.asarray(P, dtype=float) @ H.T + np.asarray(R, dtype=float)
    return float(y @ np.linalg.solve(S, y))
