"""Experimental continuous N/H reference. Not connected to production scoring."""
import math
import numpy as np

DIMENSIONS = ("P", "R", "G", "O", "M", "N", "H", "C", "SOLO", "SOCIAL", "COMP", "COOP")


class SmoothReference:
    def __init__(self, observations, bandwidth, minimum_effective=200):
        # Columns: N, H, sampling correction, twelve integer evidence values.
        a = np.asarray(observations, dtype=np.float64)
        if a.ndim != 2 or a.shape[1] != 15 or not len(a) or not np.isfinite(a).all():
            raise ValueError("Invalid reference observations")
        if (a[:, :2] < 0).any() or (a[:, 2] <= 0).any() or (a[:, 3:] < 0).any():
            raise ValueError("Invalid reference values")
        if (a[:, 3:] > 2**53).any():
            raise ValueError("Evidence integers exceed exact float64 range")
        self.bandwidth = np.asarray(bandwidth, dtype=float)
        if self.bandwidth.shape != (2,) or not np.isfinite(self.bandwidth).all() or (self.bandwidth <= 0).any():
            raise ValueError("Invalid bandwidth")
        self.coordinates = np.log1p(a[:, :2])
        self.correction = a[:, 2]
        self.evidence = a[:, 3:]
        if not math.isfinite(minimum_effective) or minimum_effective <= 0:
            raise ValueError("Invalid effective reference threshold")
        self.minimum_effective = minimum_effective
        self.bounds = (a[:, :2].min(axis=0), a[:, :2].max(axis=0))

    def positions(self, score, enforce_concentration=True):
        reasons = score["sufficiency_reasons"]
        reason = reasons[0] if reasons else None
        q = np.array([score["N"], score["H"]], dtype=float)
        if not np.isfinite(q).all() or (q < 0).any():
            raise ValueError("Invalid query")
        if reason is None and ((q < self.bounds[0]).any() or (q > self.bounds[1]).any()):
            reason = "outside_reference_range"
        delta = (self.coordinates - np.log1p(q)) / self.bandwidth
        mask = (np.abs(delta) < 1).all(axis=1)
        local_delta = delta[mask]
        # Compact biweight: weight and first derivative tend to zero at the edge.
        w = np.prod((1 - local_delta ** 2) ** 2, axis=1) * self.correction[mask]
        total = float(w.sum())
        ess = total ** 2 / float(np.square(w).sum()) if total else 0.0
        if reason is None and ess < self.minimum_effective:
            reason = "insufficient_effective_reference"
        e = self.evidence[mask]
        output = {}
        for i, d in enumerate(DIMENSIONS):
            why = reason
            if why is None and e[:, i].min() == e[:, i].max():
                why = "degenerate_reference"
            if (why is None and enforce_concentration and score["concentration"][d] is not None
                    and score["concentration"][d] > .8):
                why = "concentrated_evidence"
            value = low = tie = None
            if why is None:
                target = score["evidence_ticks"][d]
                low = float(w[e[:, i] < target].sum()) / total
                tie = float(w[e[:, i] == target].sum()) / total
                value = 100 * (low + .5 * tie)
            output[d] = {"value": value, "reason": why, "effective_reference": ess,
                         "nearby_observations": len(w), "cdf_lower": low, "cdf_tie": tie}
        return output


def interpretation(values):
    pairs = [("P", "R"), ("G", "O"), ("M", "N"), ("H", "C"),
             ("SOLO", "SOCIAL"), ("COMP", "COOP")]
    result = []
    for a, b in pairs:
        x, y = values[a]["value"], values[b]["value"]
        result.append(None if x is None or y is None else
                      "mixed" if abs(x - y) <= 10 else a if x > y else b)
    return result


def numeric_summary(values):
    if not values:
        return {"count": 0, "median": None, "p95": None, "max": None}
    return {"count": len(values), "median": float(np.median(values)),
            "p95": float(np.quantile(values, .95)), "max": float(max(values))}
