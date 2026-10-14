"""Continuous total log-time exposure reference; experimental only."""
import numpy as np
from smooth_reference import SmoothReference


class WeightReference(SmoothReference):
    def __init__(self, observations, bandwidth, mode="W", minimum_effective=200):
        if mode not in {"W", "WH"}:
            raise ValueError("Unknown exposure reference mode")
        self.mode = mode
        a = np.array(observations, dtype=float, copy=True)
        if a.ndim != 2 or a.shape[1] != 15:
            raise ValueError("Invalid exposure observations")
        # First input column is W, not N. W-only deliberately ignores total H.
        if mode == "W":
            a[:, 1] = 0
        super().__init__(a, bandwidth, minimum_effective)

    def positions(self, score, enforce_concentration=True):
        if "W" not in score:
            raise ValueError("Score lacks total log-time exposure")
        query = {**score, "N": score["W"], "H": score["H"] if self.mode == "WH" else 0}
        # Eligibility was calculated using the original N; only coordinates change.
        return super().positions(query, enforce_concentration)
