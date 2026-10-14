import math

import httpx
import pytest

from gamepersona.achievements import (
    classify_achievements, completion_summary, probe_achievements, replay_achievements,
    select_achievement_sample,
)
from gamepersona.collect import Fetcher
from gamepersona.storage import Store, write_json


def result(payload):
    return {"status": "ok", "response": payload}


def schema(*names):
    return result({"game": {"gameName": "Fixture", "availableGameStats": {"achievements": [{"name": n} for n in names]}}})


def player(**entries):
    return result({"playerstats": {"success": True, "achievements": [{"apiname": n, "achieved": v} for n, v in entries.items()]}})


@pytest.mark.parametrize("sc,pl,state", [
    (schema("a"), player(a=0), "available"),
    (schema(), player(), "no_achievements"),
    (result({"game": {}}), player(), "invalid_schema"),
    ({"status": "timeout"}, player(), "schema_timeout"),
    (schema("a"), {"status": "timeout"}, "player_timeout"),
    (schema("a"), result({"playerstats": {"success": False}}), "player_unavailable"),
    (schema("a", "b"), player(a=1), "incomplete_player_data"),
    (schema("a"), player(a=1, b=1), "incomplete_player_data"),
    (schema("a", "a"), player(a=1), "duplicate_schema_name"),
    (schema("a"), player(a=True), "invalid_player_data"),
])
def test_complete_zero_missing_and_failure_states(sc, pl, state):
    parsed = classify_achievements(sc, pl)
    assert parsed["state"] == state
    assert parsed["rate"] == (0 if state == "available" else None)


def record(app, hours, unlocked=0, total=10, state="available"):
    return {"app_id": app, "duration_hours": hours, "exclusion_reason": None, "state": state,
            "total": total, "unlocked": unlocked, "rate": unlocked / total if total else None}


def test_time_weighted_rate_caps_denominators_and_effective_games():
    records = [record(1, 1, 1, 1), record(2, 10000, 0, 100), record(3, 4, state="player_timeout")]
    summary = completion_summary(records, records + [record(4, 5)])
    expected = 100 * math.log1p(1) / (math.log1p(1) + math.log1p(100))
    assert summary["score"] == pytest.approx(expected)
    assert summary["valid_games"] == 2
    assert summary["sample_game_coverage"] == 2 / 3
    assert summary["account_game_coverage"] == .5
    assert 1 < summary["effective_games"] < 2
    assert summary["max_weight_share"] < 1
    assert summary["score"] > completion_summary(records, records, None)["score"]
    assert completion_summary([record(1, 100, 1, 2)], [])["score"] == completion_summary([record(1, 100, 50, 100)], [])["score"]
    for empty in ([], [record(1, 0)], [record(1, float("nan"))], [record(1, 5, state="no_achievements")]):
        out = completion_summary(empty, [])
        assert out["score"] is out["max_weight_share"] is out["effective_games"] is None
    assert completion_summary([record(1, 2, 0)], [])["score"] == 0


def test_sampling_tertiles_hash_order_is_stable_and_bounded():
    records = [record(i, i) for i in range(1, 61)] + [record(99, 0), record(100, -5)]
    selected = select_achievement_sample(records)
    assert selected == select_achievement_sample(list(reversed(records)))
    assert len(selected) == 15
    for label, lo, hi in (("low", 1, 20), ("middle", 21, 40), ("high", 41, 60)):
        group = [r for r in selected if r["stratum"] == label]
        assert len(group) == 5 and all(lo <= r["duration_hours"] <= hi for r in group)
    assert select_achievement_sample([]) == []
    with pytest.raises(ValueError, match="重复"):
        select_achievement_sample([record(1, 1), record(1, 2)])


def steam_input(store, records):
    path, manifest = store.create("steam", "steam", {})
    write_json(path / "records.json", records)
    store.finish(path, manifest)


def test_probe_real_parameters_privacy_resume_and_offline_replay(tmp_path, monkeypatch):
    store = Store(tmp_path)
    steam_input(store, [record(1, 1), record(2, 100)])
    key, steam_id = "sensitive-key", "76561198000000000"
    requests, interrupt = [], [True]
    def handler(request):
        assert request.url.host == "api.steampowered.com"
        assert request.url.params["key"] == key
        app = int(request.url.params["appid"])
        requests.append((app, request.url.path))
        if app == 2 and interrupt[0]:
            raise KeyboardInterrupt()
        if "GetSchemaForGame" in request.url.path:
            return httpx.Response(200, json=schema("a", "b")["response"])
        assert request.url.params["steamid"] == steam_id
        payload = player(a=app - 1, b=0)["response"]
        payload["playerstats"]["steamID"] = steam_id
        payload["playerstats"]["echo"] = key
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = Fetcher(client, interval=0, retries=0)
        with pytest.raises(KeyboardInterrupt):
            probe_achievements(store, "probe", "steam", key, steam_id, fetcher)
        with pytest.raises(ValueError, match="断点恢复"):
            probe_achievements(store, "probe", "steam", key, "76561198000000001", fetcher)
        interrupt[0] = False
        metrics = probe_achievements(store, "probe", "steam", key, steam_id, fetcher)
    assert metrics["probe_status"] == "passed"
    assert metrics["default"]["valid_games"] == 2
    assert sum(app == 1 for app, _ in requests) == 2  # completed pair was reused
    for p in store.path("probe").rglob("*.json"):
        text = p.read_text(encoding="utf-8")
        assert key not in text and steam_id not in text
    def offline(*args, **kwargs):
        raise AssertionError("replay must be offline")
    monkeypatch.setattr(httpx, "Client", offline)
    assert replay_achievements(store, "probe")["status"] == "identical"
    from gamepersona.cli import main
    assert main(["--root", str(store.root), "replay-achievements", "--snapshot", "probe"]) == 0
    write_json(store.path("probe") / "raw/1.json", {})
    with pytest.raises(ValueError, match="变化"):
        replay_achievements(store, "probe")


def test_no_achievements_skips_player_call_and_no_fake_score(tmp_path):
    store = Store(tmp_path)
    steam_input(store, [record(1, 5)])
    def handler(request):
        assert "GetSchemaForGame" in request.url.path
        return httpx.Response(200, json=schema()["response"])
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metrics = probe_achievements(store, "probe", "steam", "fixture-key", "76561198000000000", Fetcher(client))
    assert metrics["probe_status"] == "unavailable"
    assert metrics["default"]["score"] is None
    assert metrics["states"] == {"no_achievements": 1}
    assert replay_achievements(store, "probe")["status"] == "identical"


def test_wrong_account_response_is_rejected(tmp_path):
    store = Store(tmp_path)
    steam_input(store, [record(1, 5)])
    def handler(request):
        if "GetSchemaForGame" in request.url.path:
            return httpx.Response(200, json=schema("a")["response"])
        payload = player(a=1)["response"]
        payload["playerstats"]["steamID"] = "76561198000000001"
        return httpx.Response(200, json=payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        metrics = probe_achievements(store, "probe", "steam", "fixture-key", "76561198000000000", Fetcher(client, interval=0))
    assert metrics["states"] == {"player_account_mismatch": 1}
    assert metrics["default"]["score"] is None
