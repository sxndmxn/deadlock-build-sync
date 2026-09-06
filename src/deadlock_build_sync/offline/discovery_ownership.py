from __future__ import annotations

import numpy as np


def ownership(matrix: np.ndarray, core: tuple[int, ...]) -> np.ndarray:
    return np.asarray(matrix[:, core].all(axis=1))


def joint_lift(matrix: np.ndarray, core: tuple[int, ...], count: int) -> float:
    if not len(matrix):
        return 0.0
    expected = float(matrix[:, core].mean(axis=0).prod())
    return count / len(matrix) / expected if expected > 0 else 0.0
