"""Versioned, continuous W reference with deterministic standard-library sums."""
from bisect import bisect_left, bisect_right
import math

from .features import DIMENSIONS
from .scoring import E_SCALE, sufficiency, validate_model
from .storage import content_hash

WEIGHT_REFERENCE_VERSION = "stage3-reference-weight-v1"
WEIGHT_METHOD = "continuous-log-weight-v1"


def validate_weight_reference(reference, model, full=False):
    validate_model(model)
    if (reference.get("version") != WEIGHT_REFERENCE_VERSION
            or model.get("reference_method") != WEIGHT_METHOD
            or reference.get("model_sha256") != content_hash(model)
            or model["time_function"] != "log1p" or model["cap_hours"] is not None):
        raise ValueError("W参考和模型版本不兼容")
    bandwidth = model.get("reference_bandwidth")
    if type(bandwidth) not in {int,float} or not math.isfinite(bandwidth) or bandwidth <= 0:
        raise ValueError("W参考带宽无效")
    observations = reference.get("observations")
    bounds = reference.get("W_ticks_range")
    if (not isinstance(observations,list) or not observations or reference.get("dimensions") != list(DIMENSIONS)
            or not isinstance(bounds,list) or len(bounds) != 2
            or bounds != [observations[0][0],observations[-1][0]]):
        raise ValueError("W参考观测或范围无效")
    if full:
        previous = -1
        for row in observations:
            if (not isinstance(row,list) or len(row) != 14 or type(row[0]) is not int or row[0] <= 0
                    or row[0] < previous or type(row[1]) not in {int,float}
                    or not math.isfinite(row[1]) or row[1] <= 0
                    or any(type(v) is not int or v < 0 for v in row[2:])):
                raise ValueError("W参考逐人观测无效")
            previous = row[0]


def make_weight_reference(observations, model, versions, limitations):
    if not isinstance(observations,list) or not observations:
        raise ValueError("W参考不能使用空观测")
    observations = sorted(observations, key=lambda r:(r[0],r[1],r[2:]))
    reference = {"version": WEIGHT_REFERENCE_VERSION, "model_sha256": content_hash(model),
        "dimensions": list(DIMENSIONS), "observations": observations,
        "W_ticks_range": [observations[0][0],observations[-1][0]], "versions": versions,
        "sample_definition": "固定评论拟合样本；每人一次；按旧N/H层确定性抽样并校正抽样率，按连续W比较。",
        "limitations": limitations}
    validate_weight_reference(reference,model,full=True)
    return reference


def weight_positions(score, reference, model):
    validate_weight_reference(reference,model)
    if type(score.get("W_ticks")) is not int or score["W_ticks"] < 0:
        raise ValueError("W评分缺少有效基础时长权重")
    reasons = sufficiency(score,model)
    reason = reasons[0] if reasons else None
    target = score["W_ticks"]
    if reason is None and not reference["W_ticks_range"][0] <= target <= reference["W_ticks_range"][1]:
        reason = "outside_reference_range"
    center = math.log1p(target/E_SCALE)
    bandwidth = model["reference_bandwidth"]
    rows = reference["observations"]
    coordinates = [r[0] for r in rows]
    lo = bisect_left(coordinates,math.expm1(center-bandwidth)*E_SCALE)
    hi = bisect_right(coordinates,math.expm1(center+bandwidth)*E_SCALE)
    local = []
    for row in rows[lo:hi]:
        u = (math.log1p(row[0]/E_SCALE)-center)/bandwidth
        if abs(u) < 1:
            weight = (1-u*u)**2 * row[1]
            if weight > 0:
                local.append((row,weight))
    total = math.fsum(w for _,w in local)
    square = math.fsum(w*w for _,w in local)
    effective = total*total/square if square else 0.
    if reason is None and effective < model["min_reference"]:
        reason = "insufficient_effective_reference"
    result = {}
    for i,d in enumerate(DIMENSIONS):
        why = reason
        if why is None and len({r[i+2] for r,_ in local}) == 1:
            why = "degenerate_reference"
        if why is None and score["concentration"][d] is not None and score["concentration"][d] > model["max_concentration"]:
            why = "concentrated_evidence"
        evidence = score["evidence_ticks"][d]
        value = None
        if why is None:
            lower = math.fsum(w for r,w in local if r[i+2] < evidence)
            equal = math.fsum(w for r,w in local if r[i+2] == evidence)
            value = 100*((lower+.5*equal)/total)
        result[d] = {"value": value, "reason": why, "zero_evidence": evidence == 0,
            "reference_group": "continuous-W", "reference_samples": len(local),
            "effective_reference": effective}
    return result
