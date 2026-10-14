"""Deterministic tag-support features; these are not measured mechanic intensities."""
from __future__ import annotations

import math
from collections import Counter
from importlib.resources import files
from pathlib import Path

from .database import connect, rows
from .storage import Store, content_hash, read_json, sha256, write_json

FEATURE_VERSION = "stage2-tag-support-v1"
DIMENSIONS = ("P", "R", "G", "O", "M", "N", "H", "C", "SOLO", "SOCIAL", "COMP", "COOP")


def normalize_tag(tag: str) -> str:
    return " ".join(tag.casefold().split())


def load_rules(path: Path | None = None) -> dict:
    config = read_json(path or Path(str(files("gamepersona").joinpath("rules/tag_rules_v3.json"))))
    validate_rules(config)
    return config


def validate_rules(config: dict) -> None:
    if (not isinstance(config, dict) or config.get("schema_version") != FEATURE_VERSION
            or not isinstance(config.get("version"), str) or not config["version"].strip()):
        raise ValueError("不支持的特征规则版本")
    dimensions = config.get("dimensions")
    if (not isinstance(dimensions, list) or not all(isinstance(d, dict) for d in dimensions)
            or [d.get("code") for d in dimensions] != list(DIMENSIONS)):
        raise ValueError("规则必须按固定顺序定义十二个维度")
    aggregation = config.get("aggregation")
    if (aggregation not in {"maximum_per_dimension", "maximum_per_dimension_with_competitive_coop_cap"}
            or config.get("meaning") != "tag_support_not_measured_mechanic_intensity"
            or config.get("missing_policy") != "available_unmatched_zero_both_unavailable_unknown"):
        raise ValueError("规则聚合、含义或缺失策略与当前实现不兼容")
    if not isinstance(config.get("rules"), list) or not all(isinstance(r, dict) for r in config["rules"]):
        raise ValueError("规则必须是对象列表")
    aliases, ids, pairs = {}, set(), set()
    for rule in config.get("rules", []):
        tag, dimension = rule.get("tag"), rule.get("dimension")
        if not isinstance(tag, str) or not normalize_tag(tag) or dimension not in DIMENSIONS:
            raise ValueError("规则标签或维度无效")
        if type(rule.get("weight")) not in (int, float) or rule["weight"] not in (0.25, 0.5, 1.0):
            raise ValueError("规则权重必须为 0.25、0.5 或 1.0")
        if not isinstance(rule.get("reason"), str) or not rule["reason"].strip():
            raise ValueError("每项规则必须有赋值理由")
        rule_id = rule.get("id")
        pair = (normalize_tag(tag), dimension)
        if not isinstance(rule_id, str) or not rule_id or rule_id in ids or pair in pairs:
            raise ValueError("规则 ID 或标签维度重复")
        ids.add(rule_id)
        pairs.add(pair)
        if not isinstance(rule.get("aliases", []), list):
            raise ValueError("同义词必须是明确列出的字符串列表")
        for alias in [tag, *rule.get("aliases", [])]:
            if not isinstance(alias, str) or not normalize_tag(alias):
                raise ValueError("同义词无效")
            key, canonical = normalize_tag(alias), normalize_tag(tag)
            if key in aliases and aliases[key] != canonical:
                raise ValueError("同义词指向多个标签")
            aliases[key] = canonical
    if not ids or {r["dimension"] for r in config["rules"]} != set(DIMENSIONS):
        raise ValueError("每个维度至少需要一项规则")
    if aggregation == "maximum_per_dimension_with_competitive_coop_cap":
        cap = config.get("competitive_coop_cap")
        if (not isinstance(cap, dict) or type(cap.get("maximum")) not in (int, float)
                or cap["maximum"] != .5 or not isinstance(cap.get("reason"), str)
                or not cap["reason"].strip() or not isinstance(cap.get("trigger_tags"), list)
                or not all(isinstance(tag, str) for tag in cap["trigger_tags"])
                or {normalize_tag(tag) for tag in cap["trigger_tags"]} != {"competitive", "e-sports"}):
            raise ValueError("竞争合作上限必须由 Competitive/e-sports 触发且为 0.5")
        competition_tags = {normalize_tag(r["tag"]) for r in config["rules"] if r["dimension"] == "COMP"}
        if not {"competitive", "e-sports"} <= competition_tags:
            raise ValueError("竞争合作上限缺少对应竞争标签规则")
    elif "competitive_coop_cap" in config:
        raise ValueError("合作上限必须显式使用条件聚合模式")


def competitive_coop_limit(matches: dict, config: dict) -> float:
    """Only explicit Competitive/e-sports support limits cooperation, never PvP alone."""
    cap = config.get("competitive_coop_cap")
    if cap is None:
        return 1.
    triggers = {normalize_tag(tag) for tag in cap["trigger_tags"]}
    return cap["maximum"] if any(normalize_tag(m["tag"]) in triggers for m in matches["COMP"]) else 1.


def rule_index(config: dict) -> tuple[dict, dict]:
    aliases, index = {}, {}
    for rule in config["rules"]:
        key = normalize_tag(rule["tag"])
        for alias in [rule["tag"], *rule.get("aliases", [])]:
            aliases[normalize_tag(alias)] = key
        index.setdefault(key, []).append(rule)
    return aliases, index


def assign_features(evidence: list[dict], available: bool, config: dict,
                    sources: set[str] | None = None) -> dict:
    aliases, index = rule_index(config)
    scores = {k: 0.0 if available else None for k in DIMENSIONS}
    matched = {k: [] for k in DIMENSIONS}
    grouped = {}
    for item in evidence:
        if sources is not None and item["source"] not in sources:
            continue
        key = normalize_tag(item["tag"])
        key = aliases.get(key, key)
        grouped.setdefault(key, []).append(item)
    for key in sorted(grouped):
        for rule in index.get(key, []):
            dimension = rule["dimension"]
            if not available:
                raise ValueError("未知特征不能包含有效标签证据")
            scores[dimension] = max(scores[dimension], rule["weight"])
            matched[dimension].append({"rule_id": rule["id"], "tag": rule["tag"],
                                       "weight": rule["weight"], "reason": rule["reason"],
                                       "evidence": sorted(grouped[key], key=content_hash)})
    adjustments = []
    limit = competitive_coop_limit(matched, config)
    if available and scores["COOP"] > limit:
        cap = config["competitive_coop_cap"]
        original = scores["COOP"]
        scores["COOP"] = limit
        trigger_tags = sorted(m["tag"] for m in matched["COMP"]
                              if normalize_tag(m["tag"]) in {normalize_tag(tag) for tag in cap["trigger_tags"]})
        adjustments.append({"dimension": "COOP", "original_value": original, "effective_value": limit,
                            "trigger_tags": trigger_tags, "reason": cap["reason"]})
        # Contributions already carry match reasons into the private report/UI.
        for match in matched["COOP"]:
            match["reason"] += "；" + cap["reason"]
    informative = available and any(v > 0 for v in scores.values())
    result = {"values": scores, "state": "unknown" if not available else "supported" if informative else "no_rule_hit",
            "complete": available, "eligible": informative, "matches": matched,
            "unmapped_tags": sorted(key for key in grouped if key not in index)}
    if "competitive_coop_cap" in config:
        result["adjustments"] = adjustments
    return result


def pin_input(store: Store, snapshot: str, source: str, names: list[str]) -> dict:
    manifest = store.load(snapshot, source)
    hashes = {}
    for name in names:
        expected = manifest["artifact_hashes"].get(name)
        target = store.path(snapshot) / name
        if expected is None or not target.is_file() or sha256(target) != expected:
            raise ValueError(f"输入快照产物不完整或已变化：{snapshot}/{name}")
        hashes[name] = expected
    return {"snapshot": snapshot, "source": source, "artifact_hashes": hashes,
            "manifest_sha256": sha256(store.path(snapshot) / "manifest.json")}


def verify_pins(store: Store, pins: dict) -> None:
    for pin in pins.values():
        actual = pin_input(store, pin["snapshot"], pin["source"], list(pin["artifact_hashes"]))
        if actual != pin:
            raise ValueError("输入快照与固定版本不一致")


def unique_apps(records: list[dict]) -> dict[int, dict]:
    result = {}
    for record in records:
        app = record.get("app_id")
        if type(app) is not int or app <= 0 or app in result:
            raise ValueError("输入包含无效或重复 AppID")
        result[app] = record
    return result


def source_evidence(app: int, metadata: dict, spy: dict, pins: dict) -> tuple[list[dict], dict]:
    kg, ss = metadata.get(app), spy.get(app)
    kg_state = kg["tag_state"] if kg else "unmatched_app"
    spy_state = ss["status"] if ss else "not_collected"
    evidence = []
    if kg_state == "available":
        for tag in kg["tags"]:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("Kaggle available 标签格式无效")
            evidence.append({"source": "kaggle", "snapshot": pins["kaggle"]["snapshot"],
                             "tag": tag, "votes": None, "collected_at": None})
    if spy_state == "available":
        for tag in ss["tags"]:
            if not isinstance(tag.get("tag"), str) or not tag["tag"].strip() or type(tag.get("votes")) is not int or tag["votes"] < 0:
                raise ValueError("SteamSpy 标签或票数无效")
            if tag["votes"] > 0:
                evidence.append({"source": "steamspy", "snapshot": pins["steamspy"]["snapshot"],
                                 "tag": tag["tag"], "votes": tag["votes"], "collected_at": ss.get("collected_at")})
    states = {"kaggle": kg_state, "steamspy": spy_state}
    for source, state in states.items():
        if state == "available" and not any(e["source"] == source for e in evidence):
            raise ValueError("available 来源必须包含有效标签")
    return evidence, states


def calculate_features(store: Store, pins: dict, config: dict) -> tuple[list[dict], dict]:
    validate_rules(config)
    verify_pins(store, pins)
    selection = pins["selection"]["snapshot"]
    candidates = unique_apps(read_json(store.path(selection) / "candidates.json"))
    spy = unique_apps(read_json(store.path(pins["steamspy"]["snapshot"]) / "tags.json"))
    if set(spy) != set(candidates):
        raise ValueError("SteamSpy 与候选 AppID 集合不一致")
    kg_path = store.path(pins["kaggle"]["snapshot"]) / "normalized/metadata.parquet"
    con = connect(":memory:")
    try:
        metadata = unique_apps(rows(con, "SELECT app_id,tags,tag_state,tags_json FROM read_parquet('" + str(kg_path).replace("'", "''") + "')"))
    finally:
        con.close()
    outputs, grouped = [], {name: [] for name in ("all", "base", "popular", "stratified", "account", "account_new")}
    for app, candidate in sorted(candidates.items()):
        evidence, states = source_evidence(app, metadata, spy, pins)
        modes = {}
        for mode, sources in (("kaggle", {"kaggle"}), ("steamspy", {"steamspy"}), ("combined", None)):
            available = any(states[s] == "available" for s in (sources or states))
            modes[mode] = assign_features(evidence, available, config, sources)
        kg = metadata.get(app)
        record = {"app_id": app, "reasons": candidate.get("reasons", []),
                  "rule_version": config["version"], "source_states": states,
                  "kaggle_raw_tags_json": kg.get("tags_json") if kg else None,
                  "evidence": sorted(evidence, key=content_hash), "modes": modes}
        outputs.append(record)
        reasons = set(record["reasons"])
        grouped["all"].append(record)
        base = bool(reasons & {"top_review_users", "stratified"})
        if base:
            grouped["base"].append(record)
        for reason, name in (("top_review_users", "popular"), ("stratified", "stratified"), ("authorized_account", "account")):
            if reason in reasons:
                grouped[name].append(record)
        if "authorized_account" in reasons and not base:
            grouped["account_new"].append(record)
    metrics = {"schema_version": FEATURE_VERSION, "rule_version": config["version"],
               "meaning": "tag_support_not_measured_mechanic_intensity", "accuracy_validated": False,
               "groups": {name: summarize_features(records) for name, records in grouped.items()},
               "integrity_checks": feature_integrity(outputs, config)}
    metrics["metrics_sha256"] = content_hash(metrics)
    return outputs, metrics


def summarize_features(records: list[dict]) -> dict:
    n = len(records)
    result = {"games": n, "modes": {}}
    for mode in ("kaggle", "steamspy", "combined"):
        selected = [r["modes"][mode] for r in records]
        complete, eligible = sum(r["complete"] for r in selected), sum(r["eligible"] for r in selected)
        result["modes"][mode] = {
            "complete": complete, "complete_rate": complete / n if n else None,
            "eligible": eligible, "eligible_rate": eligible / n if n else None,
            "unknown": n - complete, "all_zero": sum(r["state"] == "no_rule_hit" for r in selected),
            "positive_by_dimension": {k: sum(r["values"][k] is not None and r["values"][k] > 0 for r in selected) for k in DIMENSIONS},
            "unmapped_tags": dict(sorted(Counter(t for r in selected for t in r["unmapped_tags"]).items()))}
    result["source_states"] = {s: dict(sorted(Counter(r["source_states"][s] for r in records).items())) for s in ("kaggle", "steamspy")}
    result["combined_added_eligible_vs_steamspy"] = sum(r["modes"]["combined"]["eligible"] and not r["modes"]["steamspy"]["eligible"] for r in records)
    result["combined_added_positive_cells_vs_steamspy"] = sum(
        (r["modes"]["combined"]["values"][k] or 0) > 0 and not (r["modes"]["steamspy"]["values"][k] or 0) for r in records for k in DIMENSIONS)
    result["combined_increased_cells_vs_steamspy"] = sum(
        (r["modes"]["combined"]["values"][k] or 0) > (r["modes"]["steamspy"]["values"][k] or 0) for r in records for k in DIMENSIONS)
    return result


def feature_integrity(records: list[dict], config: dict) -> dict:
    failures = []
    checks = 0
    for record in records:
        for mode, output in record["modes"].items():
            for dimension, value in output["values"].items():
                checks += 1
                if output["state"] == "unknown":
                    valid = value is None and not output["matches"][dimension]
                else:
                    expected = max((m["weight"] for m in output["matches"][dimension]), default=0)
                    if dimension == "COOP":
                        expected = min(expected, competitive_coop_limit(output["matches"], config))
                    valid = value == expected and math.isfinite(value) and 0 <= value <= 1
                if not valid:
                    failures.append({"app_id": record["app_id"], "mode": mode, "dimension": dimension})
            if output["complete"] != all(v is not None for v in output["values"].values()):
                failures.append({"app_id": record["app_id"], "mode": mode, "reason": "completeness"})
        for k in DIMENSIONS:
            combined = record["modes"]["combined"]["values"][k]
            for source in ("kaggle", "steamspy"):
                single = record["modes"][source]["values"][k]
                if single is not None and k == "COOP":
                    # A trigger present only in the other source can lower the union.
                    single = min(single, competitive_coop_limit(record["modes"]["combined"]["matches"], config))
                if single is not None and (combined is None or combined < single):
                    failures.append({"app_id": record["app_id"], "dimension": k, "reason": "non_monotonic"})
    return {"status": "passed" if not failures else "failed", "checked_values": checks, "failures": failures,
            "rule_count": len(config["rules"]), "meaning": "execution_integrity_not_accuracy"}


def render_features(metrics: dict) -> str:
    lines = ["# 第二阶段：双源标签支持程度", "", "零分表示标签未提供支持，不表示游戏没有对应机制。未知与零分分别记录。",
             "规则执行检查：" + metrics["integrity_checks"]["status"] + "；偏好推断准确性尚未验证。", "",
             "| 集合 | 游戏数 | Kaggle 可计分 | SteamSpy 可计分 | 双源可计分 | 双源未知 | 双源全零 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, group in metrics["groups"].items():
        modes = group["modes"]
        lines.append(f"| {name} | {group['games']} | {modes['kaggle']['eligible']} | {modes['steamspy']['eligible']} | {modes['combined']['eligible']} | {modes['combined']['unknown']} | {modes['combined']['all_zero']} |")
    lines += ["", "完整覆盖（complete）包含全零向量；可计分覆盖（eligible）另排除全零。各集合有交集，不相加。",
              "单源／双源逐维正证据数、来源状态、新增命中、全部未映射标签及分母见 metrics.json。",
              "本报告不生成玩家十二维评分或评论样本分位。规则、原始标签及命中理由见 rules.json 和 features.json。",
              "", f"规则版本：`{metrics['rule_version']}`；指标哈希：`{metrics['metrics_sha256']}`。", ""]
    return "\n".join(lines)


def build_features(store: Store, snapshot: str, kaggle: str, steamspy: str, selection: str,
                   rules_path: Path | None = None) -> dict:
    config = load_rules(rules_path)
    sel = store.load(selection, "selection")
    ss = store.load(steamspy, "steamspy")
    if sel["config"].get("kaggle_snapshot") != kaggle or ss["config"].get("selection_snapshot") != selection:
        raise ValueError("特征输入快照的来源关联不一致")
    pins = {"kaggle": pin_input(store, kaggle, "kaggle", ["normalized/metadata.parquet"]),
            "steamspy": pin_input(store, steamspy, "steamspy", ["tags.json"]),
            "selection": pin_input(store, selection, "selection", ["candidates.json"])}
    outputs, metrics = calculate_features(store, pins, config)
    path, manifest = store.create(snapshot, "features", {"inputs": pins, "calculation_version": FEATURE_VERSION,
                                                        "rules_sha256": content_hash(config)})
    write_json(path / "rules.json", config)
    write_json(path / "features.json", outputs)
    write_json(path / "metrics.json", metrics)
    (path / "report.md").write_text(render_features(metrics), encoding="utf-8")
    store.finish(path, manifest, execution_status=metrics["integrity_checks"]["status"],
                 metrics_sha256=metrics["metrics_sha256"], games=len(outputs))
    return metrics


def replay_features(store: Store, snapshot: str) -> dict:
    manifest = store.load(snapshot, "features")
    store.verify(snapshot)
    config = read_json(store.path(snapshot) / "rules.json")
    if content_hash(config) != manifest["config"]["rules_sha256"]:
        raise ValueError("规则内容与快照不一致")
    outputs, metrics = calculate_features(store, manifest["config"]["inputs"], config)
    if outputs != read_json(store.path(snapshot) / "features.json") or metrics != read_json(store.path(snapshot) / "metrics.json"):
        raise ValueError("特征离线重算不一致")
    if render_features(metrics) != (store.path(snapshot) / "report.md").read_text(encoding="utf-8"):
        raise ValueError("特征报告离线重算不一致")
    return {"status": "identical", "metrics_sha256": metrics["metrics_sha256"]}
