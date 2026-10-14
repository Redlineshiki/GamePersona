"""Frozen, conditional empirical reference positions; no fallback distribution."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import math

from .features import DIMENSIONS
from .scoring import E_SCALE, H_SCALE, sufficiency, validate_model
from .interpretation import interpret
from .storage import content_hash

REFERENCE_VERSION = "stage3-reference-v1"
FIXED_BOUNDS = {"N": [3,5,10,20,50,100], "H": [0,100,500,1500,5000]}


def group_key(n: int, h: float, bounds: dict) -> str | None:
    ni, hi = bisect_right(bounds["N"], n)-1, bisect_right(bounds["H"], h)-1
    return f"{ni}:{hi}" if min(ni,hi)>=0 else None


def validate_reference(reference: dict, model: dict) -> None:
    if reference.get("version") == "stage3-reference-weight-v1":
        from .weight_reference import validate_weight_reference
        validate_weight_reference(reference,model)
        return
    validate_model(model)
    if reference.get("version") != REFERENCE_VERSION or reference.get("model_sha256") != content_hash(model):
        raise ValueError("参考和模型版本不兼容")
    for key in ("N", "H"):
        values = reference["bounds"][key]
        if not values or values != sorted(set(values)) or any(not math.isfinite(x) for x in values):
            raise ValueError("参考边界无效")


def make_reference(rows: list[dict], model: dict, bounds: dict, versions: dict) -> dict:
    groups = {}
    for row in rows:
        if row["N"] < model["min_games"] or row["coverage"] is None or row["coverage"] < model["min_coverage"] or row["unknown_ratio"] > model["max_unknown_ratio"]:
            continue
        key = group_key(row["N"], row["H_ticks"]/H_SCALE, bounds)
        if key is None:
            continue
        group = groups.setdefault(key, {"N_min": row["N"], "N_max": row["N"], "H_min": row["H_ticks"],
                    "H_max": row["H_ticks"], "samples": 0, "distributions": {k: [] for k in DIMENSIONS}})
        group["samples"] += 1
        group["N_min"], group["N_max"] = min(group["N_min"], row["N"]), max(group["N_max"], row["N"])
        group["H_min"], group["H_max"] = min(group["H_min"], row["H_ticks"]), max(group["H_max"], row["H_ticks"])
        for k in DIMENSIONS:
            group["distributions"][k].append(row[f"E_{k}"])
    for group in groups.values():
        for values in group["distributions"].values():
            values.sort()
    reference = {"version": REFERENCE_VERSION, "model_sha256": content_hash(model), "bounds": bounds,
                 "groups": groups, "versions": versions,
                 "sample_definition": "固定 Steam Recommendations 评论观察样本；每人一次；每条件组按固定哈希抽样最多5000名拟合用户。",
                 "limitations": ["评论记录不是完整游戏库，迁移偏差未消除。", "来源时长可能受千位解析和失败默认零影响。", "标签支持不等于喜欢概率或现实人格。"]}
    validate_reference(reference, model)
    return reference


def reference_positions(score: dict, reference: dict, model: dict) -> dict:
    if reference.get("version") == "stage3-reference-weight-v1":
        from .weight_reference import weight_positions
        return weight_positions(score,reference,model)
    validate_reference(reference, model)
    reasons = sufficiency(score, model)
    key = group_key(score["N"], score["H"], reference["bounds"])
    group = reference["groups"].get(key)
    if not reasons:
        if group is None:
            reasons.append("no_reference_group")
        elif not (group["N_min"] <= score["N"] <= group["N_max"] and group["H_min"] <= score["H_ticks"] <= group["H_max"]):
            reasons.append("outside_reference_range")
        elif group["samples"] < model["min_reference"]:
            reasons.append("insufficient_reference")
    result = {}
    for k in DIMENSIONS:
        reason = reasons[0] if reasons else None
        values = group["distributions"][k] if group else []
        if reason is None and values[0] == values[-1]:
            reason = "degenerate_reference"
        if reason is None and score["concentration"][k] is not None and score["concentration"][k] > model["max_concentration"]:
            reason = "concentrated_evidence"
        value = None if reason else 100*(bisect_left(values,score["evidence_ticks"][k])+bisect_right(values,score["evidence_ticks"][k]))/(2*len(values))
        result[k] = {"value": value, "reason": reason, "zero_evidence": score["evidence_ticks"][k] == 0,
                     "reference_group": key, "reference_samples": len(values)}
    return result


def build_report(score: dict, reference: dict, model: dict, input_version: str) -> dict:
    if score.get('model_sha256') != content_hash(model):
        raise ValueError('评分结果与报告模型版本不兼容')
    percentiles = reference_positions(score, reference, model)
    report = {"schema_version": "report-v1", "label": "评论样本参考分位（实验性）", "score": score,
              "percentiles": percentiles, "interpretation": interpret(percentiles,model),
              "versions": {**reference["versions"], "model": model["version"], "model_sha256": content_hash(model),
                           "reference_sha256": content_hash(reference), "input": input_version},
              "limitations": reference["limitations"]}
    report["report_sha256"] = content_hash(report)
    return report
