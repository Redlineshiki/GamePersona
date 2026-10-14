from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from .storage import Store, content_hash, read_json, sha256, utc_now, write_json

STEAM_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
STEAMSPY_URL = "https://steamspy.com/api.php"


class Fetcher:
    """One shared rate limiter also covers retries; error text never contains request URLs."""

    def __init__(self, client: httpx.Client, interval: float = 1.05, retries: int = 2,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.client, self.interval, self.retries = client, interval, retries
        self.sleep, self.clock = sleep, clock
        self.last_start: float | None = None

    def get(self, url: str, params: dict | None = None, *, as_json: bool = True) -> dict:
        for attempt in range(self.retries + 1):
            if self.last_start is not None:
                self.sleep(max(0, self.interval - (self.clock() - self.last_start)))
            self.last_start = self.clock()
            status, code, data = "network_failure", None, None
            retry_after = 0.0
            try:
                response = self.client.get(url, params=params, timeout=30)
                code = response.status_code
                if code in {401, 403}:
                    status = "credential_or_access_error"
                elif code == 429:
                    status = "rate_limited"
                    try:
                        retry_after = min(300.0, max(0.0, float(response.headers.get("Retry-After", 0))))
                    except ValueError:
                        pass
                elif code >= 500:
                    status = "service_failure"
                elif code != 200:
                    status = "http_failure"
                else:
                    try:
                        data = response.json() if as_json else response.text
                        status = "ok"
                    except ValueError:
                        status = "invalid_response"
            except httpx.TimeoutException:
                status = "timeout"
            except httpx.RequestError:
                status = "network_failure"
            if status not in {"rate_limited", "service_failure", "timeout", "network_failure"} or attempt == self.retries:
                return {"status": status, "http_status": code, "response": data,
                        "attempts": attempt + 1, "collected_at": utc_now()}
            self.sleep(max(retry_after, 2.0 ** attempt))
        raise AssertionError("unreachable")


def classify_steam(payload: object) -> tuple[str, list[dict]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        return "insufficient_response", []
    response = payload["response"]
    count, games = response.get("game_count"), response.get("games")
    if type(count) is not int or count < 0:
        return "insufficient_response", []
    if count == 0 and (games is None or games == []):
        return "explicit_empty", []
    if not isinstance(games, list) or len(games) != count or not all(isinstance(g, dict) for g in games):
        return "insufficient_response", []
    return "success", games


def normalize_steam(games: list[dict], snapshot: str) -> list[dict]:
    groups: dict[int, list[dict]] = {}
    invalid = []
    for game in games:
        app_id = game.get("appid")
        if type(app_id) is not int or app_id <= 0:
            invalid.append({"app_id": None, "duration_hours": None, "duration_state": "unknown",
                            "exclusion_reason": "invalid_app_id"})
        else:
            groups.setdefault(app_id, []).append(game)
    records = []
    for app_id, group in sorted(groups.items()):
        distinct = {content_hash(game): game for game in group}
        if len(distinct) > 1:
            records.append({"app_id": app_id, "duration_hours": None, "duration_state": "unknown",
                            "exclusion_reason": "conflicting_user_game"})
            continue
        game = next(iter(distinct.values()))
        value = game.get("playtime_forever")
        if value is None:
            state = "unknown"
        elif type(value) not in {int, float}:
            state = "invalid_type"
        elif not math.isfinite(value):
            state = "non_finite"
        elif value < 0:
            state = "negative"
        elif value == 0:
            state = "zero"
        else:
            state = "positive"
        records.append({"app_id": app_id, "duration_hours": value / 60 if state in {"positive", "zero"} else None,
                        "duration_state": state,
                        "exclusion_reason": None if state in {"positive", "zero"} else "duration_" + state})
    for record in records + invalid:
        record["user_key"] = "steam-snapshot:" + snapshot
    return records + invalid


def fetch_steam(store: Store, snapshot: str, key: str, steam_id: str,
                fetcher: Fetcher) -> dict:
    path, manifest = store.create(snapshot, "steam", {
        "endpoint": STEAM_URL, "include_appinfo": True, "include_played_free_games": True,
        "source_duration_unit": "minutes", "cleaning_version": "stage1-v1",
        "duration_time_semantics": "API-reported cumulative playtime at collection",
        "scope": "one_authorized_account", "identity_verification": "operator_supplied_not_OpenID"})
    result = fetcher.get(STEAM_URL, {"key": key, "steamid": steam_id,
                                   "include_appinfo": 1, "include_played_free_games": 1})
    records, games = [], []
    if result["status"] == "ok":
        state, games = classify_steam(result["response"])
        records = normalize_steam(games, snapshot)
    else:
        state = result["status"]
    # Raw response is private. Neither credentials nor the request query are persisted.
    write_json(path / "raw_response.json", result)
    write_json(path / "records.json", records)
    store.finish(path, manifest, read_status=state, observed_records=len(games), normalized_records=len(records),
                 excluded_records=sum(r["exclusion_reason"] is not None for r in records),
                 raw_sha256=sha256(path / "raw_response.json"))
    return manifest


def classify_tags(payload: object, app_id: int) -> tuple[str, list[dict]]:
    if not isinstance(payload, dict):
        return "invalid_response", []
    if payload.get("appid") == 999999:
        return "hidden", []
    if payload.get("appid") != app_id:
        return "unmatched_app", []
    tags = payload.get("tags")
    if tags is None or tags == {} or tags == []:
        return "no_tags", []
    if not isinstance(tags, dict):
        return "invalid_tag_format", []
    clean = []
    for tag, votes in tags.items():
        if not isinstance(tag, str) or not tag.strip() or type(votes) is not int or votes < 0:
            return "invalid_tag_format", []
        clean.append({"tag": tag, "votes": votes})
    if not any(t["votes"] > 0 for t in clean):
        return "no_positive_votes", clean
    return "available", sorted(clean, key=lambda t: t["tag"])


def fetch_steamspy(store: Store, snapshot: str, selection: str, fetcher: Fetcher,
                  max_games: int | None = None, progress: Callable[[str], None] = print) -> dict:
    store.load(selection, "selection")
    candidates = read_json(store.path(selection) / "candidates.json")
    path = store.path(snapshot)
    if path.exists():
        manifest = store.load(snapshot, "steamspy", ready=False)
        if manifest["config"]["selection_snapshot"] != selection:
            raise ValueError("断点恢复必须使用同一候选快照")
        if manifest["state"] == "ready":
            store.verify(snapshot)
            return manifest
    else:
        path, manifest = store.create(snapshot, "steamspy", {
            "selection_snapshot": selection, "endpoint": STEAMSPY_URL,
            "minimum_request_interval_seconds": fetcher.interval,
            "cache_hours": 24, "max_retries": fetcher.retries})
    raw = path / "raw"
    raw.mkdir(exist_ok=True)
    cache = store.root / "cache" / "steamspy"
    cache.mkdir(parents=True, exist_ok=True)
    if max_games is not None and max_games < 0:
        raise ValueError("max-games 不得为负")
    processed = 0
    started = time.monotonic()
    for candidate in candidates:
        app_id = candidate["app_id"]
        target = raw / f"{app_id}.json"
        if target.exists():
            continue
        if max_games is not None and processed >= max_games:
            break
        cached = cache / f"{app_id}.json"
        result = None
        if cached.exists():
            previous = read_json(cached)
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(previous["collected_at"])).total_seconds()
            if previous["status"] == "ok" and 0 <= age < 86400:
                result = previous
        if result is None:
            result = fetcher.get(STEAMSPY_URL, {"request": "appdetails", "appid": app_id})
            write_json(cached, result)
        tag_state, tags = classify_tags(result["response"], app_id) if result["status"] == "ok" else (result["status"], [])
        write_json(target, {**result, "requested_app_id": app_id, "tag_state": tag_state, "tags": tags})
        processed += 1
        if processed % 100 == 0:
            progress(f"SteamSpy：本次已处理 {processed} 款")
    records = []
    for candidate in candidates:
        target = raw / f"{candidate['app_id']}.json"
        if target.exists():
            result = read_json(target)
            records.append({"app_id": candidate["app_id"], "status": result["tag_state"],
                            "tags": result["tags"], "collected_at": result["collected_at"]})
        else:
            records.append({"app_id": candidate["app_id"], "status": "not_collected", "tags": [],
                            "collected_at": None})
    write_json(path / "tags.json", records)
    remaining = sum(r["status"] == "not_collected" for r in records)
    manifest.update(state="building" if remaining else "ready", expected_games=len(candidates),
                    attempted_games=len(candidates)-remaining, uncollected_games=remaining,
                    last_elapsed_seconds=round(time.monotonic()-started, 3), updated_at=utc_now())
    write_json(path / "manifest.json", manifest)
    if not remaining:
        store.finish(path, manifest)
    return manifest


SOURCE_URLS = {
    "kaggle": "https://www.kaggle.com/api/v1/datasets/view/antonkozyriev/game-recommendations-on-steam",
    "steamspy_api": STEAMSPY_URL,
    "steamspy_about": "https://steamspy.com/about",
    "steam_terms": "https://steamcommunity.com/dev/apiterms",
    "steam_interface": "https://partner.steamgames.com/doc/webapi/IPlayerService",
    "steam_overview": "https://partner.steamgames.com/doc/webapi_overview",
}


def verify_sources(store: Store, snapshot: str, fetcher: Fetcher, review_file: Path | None = None) -> dict:
    path, manifest = store.create(snapshot, "sources", {"intended_use": "first_stage_local_data_audit"})
    results = {}
    for name, url in SOURCE_URLS.items():
        result = fetcher.get(url, as_json=name == "kaggle")
        write_json(path / f"{name}.json", result)
        results[name] = {"url": url, "status": result["status"], "sha256": sha256(path / f"{name}.json")}
    kaggle = read_json(path / "kaggle.json")
    data = kaggle.get("response") or {}
    declared = data.get("licenseName") if isinstance(data, dict) else None
    findings = {
        "intended_use": "第一阶段本地非商业数据审计",
        "kaggle": {"declared_license": declared, "source_version": data.get("currentVersionNumber") if isinstance(data, dict) else None,
                   "status": "declared_license_recorded" if declared else "unverified",
                   "note": "发布者声明不自动证明所有底层第三方内容权利；不将原始描述和评论公开再分发"},
        "steam": {"status": "conditions_recorded" if results["steam_terms"]["status"] == "ok" else "unverified",
                  "conditions": ["按用户请求读取", "密钥保密", "公布保存内容和所在地及隐私政策", "不收集 Steam 密码", "遵守调用限制"]},
        "steamspy": {"status": "not_assessed_for_stage1",
                     "note": "本阶段仅验收本地数据审计；公开部署、派生特征和分享用途不在本阶段验收范围"},
        "unresolved": [],
        "out_of_scope": ["公开部署前需另行评估 SteamSpy 数据及派生产物的适用条件"],
        "rollout_obligations": ["上线前落实 Steam 数据保存说明、隐私政策和删除机制（第四阶段）"],
    }
    if review_file:
        review = read_json(review_file)
        permission = review.get("steamspy_public_free_use", {})
        if permission.get("status") == "verified" and permission.get("evidence") and permission.get("rationale"):
            findings["steamspy"] = {"status":"verified_by_operator", **permission}
            findings["unresolved"] = []
        write_json(path / "operator_review.json", review)
    write_json(path / "findings.json", findings)
    store.finish(path, manifest, evidence=results, findings=findings)
    return manifest
