"""Small authorized-account probe and an independent time-weighted completion index."""
from __future__ import annotations

import hashlib
import math
from collections import Counter

from .collect import Fetcher
from .features import pin_input, verify_pins
from .storage import Store, content_hash, read_json, write_json

ACHIEVEMENT_VERSION = "stage2-achievement-v1"
SCHEMA_URL = "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"
PLAYER_URL = "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v1/"
CAPS = (None, 50, 100, 200)


def positive_record(record: dict) -> bool:
    h = record.get("duration_hours")
    return (type(record.get("app_id")) is int and record["app_id"] > 0
            and record.get("exclusion_reason") is None
            and type(h) in (int, float) and math.isfinite(h) and h > 0)


def select_achievement_sample(records: list[dict]) -> list[dict]:
    positive = sorted((r for r in records if positive_record(r)), key=lambda r: (r["duration_hours"], r["app_id"]))
    if len({r["app_id"] for r in positive}) != len(positive):
        raise ValueError("成就样本不能包含重复 AppID")
    groups = {k: [] for k in ("low", "middle", "high")}
    for i, record in enumerate(positive):
        group = ("low", "middle", "high")[min(2, i * 3 // len(positive))]
        groups[group].append({"app_id": record["app_id"], "duration_hours": record["duration_hours"], "stratum": group})
    selected = []
    for group in groups.values():
        selected.extend(sorted(group, key=lambda r: (hashlib.sha256(
            f"{ACHIEVEMENT_VERSION}:{r['app_id']}".encode()).hexdigest(), r["app_id"]))[:5])
    return selected


def classify_achievements(schema: dict, player: dict) -> dict:
    def state(name):
        return {"state": name, "total": None, "unlocked": None, "rate": None}

    if schema.get("status") != "ok":
        return state("schema_" + schema.get("status", "missing"))
    payload = schema.get("response")
    game = payload.get("game") if isinstance(payload, dict) else None
    if not isinstance(game, dict) or not game or game.get("success") is False:
        return state("invalid_schema")
    stats = game.get("availableGameStats")
    if stats is None:
        return state("no_achievements") if isinstance(game.get("gameName"), str) and game["gameName"] else state("invalid_schema")
    if not isinstance(stats, dict):
        return state("invalid_schema")
    definitions = stats.get("achievements", [])
    if not isinstance(definitions, list):
        return state("invalid_schema")
    if not definitions:
        return state("no_achievements")
    names = []
    for entry in definitions:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
            return state("invalid_schema")
        names.append(entry["name"])
    if len(set(names)) != len(names):
        return state("duplicate_schema_name")
    if player.get("status") != "ok":
        return state("player_" + player.get("status", "missing"))
    payload = player.get("response")
    stats = payload.get("playerstats") if isinstance(payload, dict) else None
    if not isinstance(stats, dict) or stats.get("success") is not True:
        return state("player_unavailable")
    entries = stats.get("achievements")
    if not isinstance(entries, list):
        return state("incomplete_player_data")
    achieved = {}
    for entry in entries:
        if not isinstance(entry, dict):
            return state("invalid_player_data")
        name, value = entry.get("apiname"), entry.get("achieved")
        if not isinstance(name, str) or name in achieved or type(value) is not int or value not in (0, 1):
            return state("invalid_player_data")
        achieved[name] = value
    if set(achieved) != set(names):
        return state("incomplete_player_data")
    total, unlocked = len(names), sum(achieved.values())
    return {"state": "available", "total": total, "unlocked": unlocked, "rate": unlocked / total}


def redact(value, secrets: tuple[str, ...]):
    """API responses can echo SteamID; retain useful raw evidence without account identifiers."""
    if isinstance(value, dict):
        return {k: "<redacted>" if k.casefold() in {"steamid", "steam_id", "key", "api_key"} else redact(v, secrets)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "<redacted>")
    if isinstance(value, int) and str(value) in secrets:
        return "<redacted>"
    return value


def completion_summary(records: list[dict], account_records: list[dict], cap: int | None = 100) -> dict:
    if cap is not None and (type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0):
        raise ValueError("时长上限必须为正有限数或 None")
    valid, weights = [], []
    for record in records:
        if record.get("state") != "available" or not positive_record(record):
            continue
        total, unlocked = record.get("total"), record.get("unlocked")
        if type(total) is not int or total <= 0 or type(unlocked) is not int or not 0 <= unlocked <= total:
            raise ValueError("可用成就计数无效")
        rate = unlocked / total
        if record.get("rate") != rate:
            raise ValueError("成就率与计数不一致")
        h = record["duration_hours"]
        valid.append(record)
        weights.append(math.log1p(h if cap is None else min(h, cap)))
    total_weight = math.fsum(weights)
    sample_hours = math.fsum(r["duration_hours"] for r in records if positive_record(r))
    account_positive = [r for r in account_records if positive_record(r)]
    account_hours = math.fsum(r["duration_hours"] for r in account_positive)
    valid_hours = math.fsum(r["duration_hours"] for r in valid)
    return {"cap_hours": cap, "score": 100 * math.fsum(w * r["rate"] for w, r in zip(weights, valid)) / total_weight if total_weight else None,
            "valid_games": len(valid), "sample_games": len(records), "account_positive_games": len(account_positive),
            "sample_game_coverage": len(valid) / len(records) if records else None,
            "account_game_coverage": len(valid) / len(account_positive) if account_positive else None,
            "sample_positive_duration_coverage": valid_hours / sample_hours if sample_hours else None,
            "account_positive_duration_coverage": valid_hours / account_hours if account_hours else None,
            "max_weight_share": max(weights) / total_weight if total_weight else None,
            "effective_games": total_weight ** 2 / math.fsum(w * w for w in weights) if total_weight else None,
            "contributions": [{"app_id": r["app_id"], "rate": r["rate"], "weight": w,
                               "weight_share": w / total_weight} for w, r in zip(weights, valid)]}


def calculate_probe(sample: list[dict], raw: dict, account: list[dict]) -> tuple[list[dict], dict]:
    records = []
    for game in sample:
        app = str(game["app_id"])
        result = raw[app]
        classified = classify_achievements(result["schema"], result["player"])
        records.append({**game, **classified})
    summaries = {"uncapped" if cap is None else str(cap): completion_summary(records, account, cap) for cap in CAPS}
    available = summaries["100"]["valid_games"]
    failures = sum(r["state"] not in {"available", "no_achievements"} for r in records)
    metrics = {"schema_version": ACHIEVEMENT_VERSION, "default_cap_hours": 100,
               "scope": "authorized_account_small_sample_preview_not_full_library_score",
               "interpretation": "low_mainline_tendency_estimate_not_proof_of_completion_high_achievement_completion_tendency",
               "accuracy_validated": False, "confidence_probability": None, "classification_threshold": None,
               "states": dict(sorted(Counter(r["state"] for r in records).items())),
               "probe_status": "passed" if available and not failures else "partial" if available else "unavailable",
               "default": summaries["100"], "sensitivity": summaries}
    scores = [s["score"] for s in summaries.values() if s["score"] is not None]
    metrics["sensitivity_score_range"] = max(scores) - min(scores) if scores else None
    metrics["metrics_sha256"] = content_hash(metrics)
    return records, metrics


def render_achievements(metrics: dict) -> str:
    summary = metrics["default"]
    score = f"{summary['score']:.2f}" if summary["score"] is not None else "不可计算"
    lines = ["# 第二阶段：成就完成倾向小样本核验", "", f"核验状态：{metrics['probe_status']}；100 小时上限预览分数：{score}。", "",
             "本分数仅描述固定小样本，不是完整游戏库画像、分类概率或评论样本参考分位。",
             "高值粗略对应偏全成就型；低值粗略对应偏主线型，也可能是尚未完成、探索或其他游玩方式，不证明通关。",
             "时长权重为 ln(1+min(小时数,100))；成就总数先在每款游戏内归一化。", "",
             f"有效游戏：{summary['valid_games']} / 样本 {summary['sample_games']}；账号正时长游戏：{summary['account_positive_games']}。",
             "覆盖率、有效样本量和最大单游戏权重见 metrics.json；这些是证据充分性指标，不是已验证的置信概率。", "",
             "| 时长上限（小时） | 完成倾向分数 | 有效游戏数 |", "|---|---:|---:|"]
    for name, result in metrics["sensitivity"].items():
        value = f"{result['score']:.2f}" if result["score"] is not None else "不可计算"
        lines.append(f"| {name} | {value} | {result['valid_games']} |")
    lines += ["", "读取状态：" + str(metrics["states"]), "",
              "原始响应已移除密钥及账号标识；单游戏记录与贡献属于本地私有产物，不用于默认公开分享。",
              "本轮不设置正式类型阈值；规则可靠执行与偏好推断有效性分别记录。", "",
              f"指标哈希：`{metrics['metrics_sha256']}`。", ""]
    return "\n".join(lines)


def probe_achievements(store: Store, snapshot: str, steam: str, key: str, steam_id: str,
                       fetcher: Fetcher) -> dict:
    pin = pin_input(store, steam, "steam", ["records.json"])
    account = read_json(store.path(steam) / "records.json")
    sample = select_achievement_sample(account)
    config = {"inputs": {"steam": pin}, "calculation_version": ACHIEVEMENT_VERSION,
              "account_binding": hashlib.sha256((key + ":" + steam_id).encode()).hexdigest(),
              "seed": ACHIEVEMENT_VERSION, "per_stratum": 5, "default_cap_hours": 100,
              "sampling": "positive-time rank tertiles; duration then AppID; sha256 ordering within each stratum",
              "endpoints": {"schema": SCHEMA_URL, "player": PLAYER_URL}}
    path = store.path(snapshot)
    if path.exists():
        manifest = store.load(snapshot, "achievements", ready=False)
        if manifest["config"] != config:
            raise ValueError("成就断点恢复输入不一致；请使用新快照标识")
        if manifest["state"] == "ready":
            replay_achievements(store, snapshot)
            return read_json(path / "metrics.json")
        if read_json(path / "sample.json") != sample:
            raise ValueError("成就样本与断点不一致")
    else:
        path, manifest = store.create(snapshot, "achievements", config)
        write_json(path / "sample.json", sample)
    raw = {}
    for game in sample:
        app = str(game["app_id"])
        target = path / "raw" / f"{app}.json"
        if target.exists():
            raw[app] = read_json(target)
            continue
        schema = fetcher.get(SCHEMA_URL, {"key": key, "appid": app, "l": "english"})
        if classify_achievements(schema, {"status": "not_requested"})["state"] == "player_not_requested":
            player = fetcher.get(PLAYER_URL, {"key": key, "steamid": steam_id, "appid": app, "l": "english"})
            payload = player.get("response")
            stats = payload.get("playerstats") if isinstance(payload, dict) else None
            if isinstance(stats, dict) and stats.get("steamID") is not None and str(stats["steamID"]) != steam_id:
                player = {**player, "status": "account_mismatch"}
        else:
            player = {"status": "not_requested", "response": None}
        raw[app] = redact({"schema": schema, "player": player}, (key, steam_id))
        write_json(target, raw[app])
    records, metrics = calculate_probe(sample, raw, account)
    write_json(path / "records.json", records)
    write_json(path / "metrics.json", metrics)
    (path / "report.md").write_text(render_achievements(metrics), encoding="utf-8")
    store.finish(path, manifest, probe_status=metrics["probe_status"], metrics_sha256=metrics["metrics_sha256"])
    return metrics


def replay_achievements(store: Store, snapshot: str) -> dict:
    manifest = store.load(snapshot, "achievements")
    store.verify(snapshot)
    verify_pins(store, manifest["config"]["inputs"])
    steam = manifest["config"]["inputs"]["steam"]["snapshot"]
    account = read_json(store.path(steam) / "records.json")
    sample = select_achievement_sample(account)
    if sample != read_json(store.path(snapshot) / "sample.json"):
        raise ValueError("成就样本离线重算不一致")
    raw = {str(r["app_id"]): read_json(store.path(snapshot) / "raw" / f"{r['app_id']}.json") for r in sample}
    records, metrics = calculate_probe(sample, raw, account)
    if records != read_json(store.path(snapshot) / "records.json") or metrics != read_json(store.path(snapshot) / "metrics.json"):
        raise ValueError("成就离线重算不一致")
    if render_achievements(metrics) != (store.path(snapshot) / "report.md").read_text(encoding="utf-8"):
        raise ValueError("成就报告离线重算不一致")
    return {"status": "identical", "metrics_sha256": metrics["metrics_sha256"]}
