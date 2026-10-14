"""Shared model eligibility and deterministic evidence for source-adapted records."""
from __future__ import annotations

import math
import json
from collections import Counter, defaultdict
from copy import deepcopy

from .features import DIMENSIONS, unique_apps
from .storage import content_hash

SCORING_VERSION = "stage3-evidence-v1"
E_SCALE = 10**10
H_SCALE = 10**8


def model_config(**changes) -> dict:
    config = {"version": "model-candidate-v1", "scoring_version": SCORING_VERSION,
              "time_function": "log1p", "cap_hours": None, "min_games": 5,
              "min_coverage": .8, "max_unknown_ratio": .2, "min_reference": 200,
              "max_concentration": .8, "high": 80., "low": 20., "tolerance": 10.}
    config.update(changes)
    validate_model(config)
    return config


def validate_model(model: dict) -> None:
    if not isinstance(model, dict) or model.get("scoring_version") != SCORING_VERSION:
        raise ValueError("不兼容的评分版本")
    if not isinstance(model.get("version"), str) or not model["version"]:
        raise ValueError("模型必须具有版本")
    if model.get("time_function") not in {"log1p", "linear"}:
        raise ValueError("未知时长函数")
    cap = model.get("cap_hours")
    if cap is not None and (type(cap) not in {int, float} or not math.isfinite(cap) or cap <= 0):
        raise ValueError("时长上限必须为正有限值")
    for key in ("min_games", "min_reference"):
        if type(model.get(key)) is not int or model[key] < 1:
            raise ValueError("样本数量门槛必须为正整数")
    for key in ("min_coverage", "max_unknown_ratio", "max_concentration"):
        if type(model.get(key)) not in {int, float} or not 0 <= model[key] <= 1:
            raise ValueError("比例门槛必须位于 [0,1]")
    if not all(type(model.get(k)) in {int, float} and math.isfinite(model[k]) for k in ("high", "low", "tolerance")):
        raise ValueError("类型门槛必须为有限数")
    if not 0 <= model["low"] < model["high"] <= 100 or not 0 <= model["tolerance"] <= 100:
        raise ValueError("类型门槛无效")


def ticks(value: float, scale: int) -> int:
    return math.floor(value * scale + .5)


def time_weight(hours: float, model: dict) -> float:
    value = min(hours, model["cap_hours"]) if model["cap_hours"] is not None else hours
    return math.log1p(value) if model["time_function"] == "log1p" else value


def feature_index(features: list[dict]) -> dict:
    result = unique_apps(features)
    for item in result.values():
        vector = item["modes"]["combined"]
        values = vector["values"]
        if set(values) != set(DIMENSIONS) or any(v is not None and
                (type(v) not in {int, float} or not math.isfinite(v) or v not in (0, .25, .5, 1))
                for v in values.values()):
            raise ValueError("特征不符合固定十二维规则")
        complete = all(v is not None for v in values.values())
        eligible = complete and any(v > 0 for v in values.values())
        if vector["complete"] != complete or vector["eligible"] != eligible:
            raise ValueError("特征状态与向量不一致")
    return result


def score_records(records: list[dict], features: list[dict] | dict, model: dict,
                  read_status: str = "success") -> dict:
    validate_model(model)
    index = feature_index(features) if isinstance(features, list) else features
    groups, invalid = defaultdict(list), []
    # User keys belong to the source adapter; this function scores one user only.
    keys = {r.get("user_key") for r in records if r.get("user_key") is not None}
    if len(keys) > 1:
        raise ValueError("单次评分不能混合多个用户")
    for record in records:
        app = record.get("app_id")
        if type(app) is not int or app <= 0:
            invalid.append({"app_id": None, "reason": "invalid_app_id"})
        else:
            # Only identical adapted records collapse; no arbitrary latest selection.
            groups[app].append(record)
    excluded, contributions = list(invalid), []
    unknown = 0
    known_ticks = 0
    source_readable = read_status in {"success", "explicit_empty"}
    for app, group in sorted(groups.items()):
        distinct = {json.dumps({k: v for k, v in r.items() if k != "user_key"}, sort_keys=True): r for r in group}
        record = next(iter(distinct.values()))
        reason = "conflicting_user_game" if len(distinct) > 1 else record.get("exclusion_reason")
        hours = record.get("duration_hours")
        if reason:
            excluded.append({"app_id": app, "reason": reason})
            if reason != "conflicting_user_game" and (type(hours) not in {int,float} or not math.isfinite(hours) or hours<0):
                unknown += 1
            continue
        if type(hours) not in {int, float} or not math.isfinite(hours) or hours < 0:
            unknown += 1
            excluded.append({"app_id": app, "reason": "duration_unknown_or_invalid"})
            continue
        if hours == 0:
            excluded.append({"app_id": app, "reason": "zero_duration"})
            continue
        ht = ticks(hours, H_SCALE)
        known_ticks += ht
        game = index.get(app)
        vector = game["modes"]["combined"] if game else None
        reason = "unmatched_feature" if not game else "unknown_feature" if not vector["complete"] else "all_zero_feature" if not vector["eligible"] else None
        if not source_readable:
            reason = "source_unreadable"
        if reason:
            excluded.append({"app_id": app, "reason": reason})
            continue
        hours = ht / H_SCALE
        values = vector["values"]
        ct = {k: ticks(time_weight(hours, model) * values[k], E_SCALE) for k in DIMENSIONS}
        contributions.append({"app_id": app, "hours": hours, "hours_ticks": ht,
                              "values": deepcopy(values), "ticks": ct,
                              "evidence": {k: ct[k] / E_SCALE for k in DIMENSIONS},
                              "matches": deepcopy(vector.get("matches", {})),
                              "rule_version": game.get("rule_version")})
    totals = {k: sum(c["ticks"][k] for c in contributions) for k in DIMENSIONS}
    h = sum(c["hours_ticks"] for c in contributions)
    n = len(contributions)
    observed = len(groups) + len(invalid)
    result = {"scoring_version": SCORING_VERSION, "model_sha256": content_hash(model),
              "read_status": read_status, "observed_games": observed, "N": n,
              "H_ticks": h, "H": h / H_SCALE, "known_positive_hours": known_ticks / H_SCALE,
              "coverage": h / known_ticks if known_ticks else None,
              "unknown_duration_games": unknown, "unknown_ratio": unknown / observed if observed else None,
              "evidence_ticks": totals, "E": {k: totals[k] / E_SCALE for k in DIMENSIONS},
              "concentration": {k: max((c["ticks"][k] for c in contributions), default=0) / totals[k]
                                if totals[k] else None for k in DIMENSIONS},
              "positive_games": {k: sum(c["ticks"][k] > 0 for c in contributions) for k in DIMENSIONS},
              "effective_games": {k: totals[k]**2 / sum(c["ticks"][k]**2 for c in contributions)
                                  if totals[k] else None for k in DIMENSIONS},
              "excluded": excluded, "exclusion_counts": dict(sorted(Counter(x["reason"] for x in excluded).items())),
              "contributions": contributions}
    result["sufficiency_reasons"] = sufficiency(result, model)
    if model.get("reference_method") == "continuous-log-weight-v1":
        result["W_ticks"] = sum(ticks(time_weight(c["hours"],model),E_SCALE) for c in contributions)
        result["W"] = result["W_ticks"] / E_SCALE
    return result


def sufficiency(score: dict, model: dict) -> list[str]:
    reasons = []
    if score["read_status"] not in {"success", "explicit_empty"}:
        reasons.append("source_" + score["read_status"])
    if score["N"] < model["min_games"]:
        reasons.append("insufficient_games")
    if score["coverage"] is None or score["coverage"] < model["min_coverage"]:
        reasons.append("insufficient_coverage")
    if score["unknown_ratio"] is not None and score["unknown_ratio"] > model["max_unknown_ratio"]:
        reasons.append("unknown_duration")
    return reasons


def sql_weight(hours: str, model: dict) -> str:
    """SQL and Python use the same per-game integer quantization and model."""
    validate_model(model)
    value = f"least({hours},{model['cap_hours']})" if model["cap_hours"] is not None else hours
    return f"ln(1+({value}))" if model["time_function"] == "log1p" else f"({value})"
