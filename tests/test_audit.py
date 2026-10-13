import pytest

from gamepersona.audit import audit, calculate, coverage, render, replay
from gamepersona.sampling import select_games
from gamepersona.storage import read_json, write_json
from gamepersona.ingest import import_kaggle
from gamepersona.storage import Store


def test_zero_denominator_unknown():
    assert coverage(0,0,"empty")["ratio"] is None


def test_deterministic_sampling(imported):
    first=select_games(imported,"selection1","kg",top=1,stratified=2)
    select_games(imported,"selection2","kg",top=1,stratified=2)
    assert read_json(imported.path("selection1") / "candidates.json")==read_json(imported.path("selection2") / "candidates.json")
    assert first["base_games"]==3
    candidates=read_json(imported.path("selection1") / "candidates.json")
    assert len({r["app_id"] for r in candidates})==3


def test_audit_metrics_and_offline_replay(imported,monkeypatch):
    result=audit(imported,"report",kaggle="kg")
    assert result["offline"]["game_match_rate"]==coverage(4,5,"离线评论输入去重且有效格式的 AppID；包含未匹配项")
    assert result["offline"]["kaggle_metadata_tag_coverage"]["ratio"]==2/5
    assert result["offline"]["steamspy"]["states"]["not_selected"]==5
    assert result["online"]["status"]=="not_measured"
    assert result["stage_acceptance"]["status"]=="blocked"
    assert result["offline"]["feature_availability"]["value"] is None
    assert result["offline"]["users_before_cleaning"]==3
    assert result["offline"]["users_after_cleaning"]==1
    # The conflicting pair's 10 + 20 minutes must not inflate the coverage denominator.
    assert result["offline"]["metadata_duration_coverage"]["denominator"]==65/60
    import httpx
    monkeypatch.setattr(httpx.Client,"__init__",lambda *args,**kwargs:pytest.fail("offline replay must not create HTTP client"))
    assert replay(imported,"report")["status"]=="identical"


def test_replay_detects_changed_raw(imported):
    audit(imported,"report",kaggle="kg")
    (imported.path("kg") / "raw" / "users.csv").write_text("changed")
    with pytest.raises(ValueError,match="原始"):
        replay(imported,"report")


def test_full_fractional_duration_audit_is_exact_and_replayable(tmp_path):
    source = tmp_path / "fractional"
    source.mkdir()
    (source / "games.csv").write_text("app_id,title\n1,One\n", encoding="utf-8")
    (source / "games_metadata.json").write_text('{"app_id":1,"tags":["Action"]}\n', encoding="utf-8")
    # Multiple database row groups expose parallel floating-point reduction drift.
    count = 300000
    with (source / "users.csv").open("w", encoding="utf-8") as users, \
            (source / "recommendations.csv").open("w", encoding="utf-8") as records:
        users.write("user_id\n")
        records.write("app_id,user_id,review_id,hours,date,is_recommended\n")
        for i in range(count):
            users.write(f"{i}\n")
            records.write(f"1,{i},{i},0.1,2024-01-01,true\n")
    store = Store(tmp_path / "artifacts")
    import_kaggle(store, "kg", source, hours_unit="hours", hours_evidence="fixture specification",
                  memory_limit="256MiB", threads=1)
    result = audit(store, "report", kaggle="kg")
    rate = result["offline"]["metadata_duration_coverage"]
    assert rate["numerator"] == rate["denominator"] == 30000.0
    assert rate["ratio"] == 1.0
    for _ in range(3):
        assert replay(store, "report")["status"] == "identical"


def test_legacy_report_replays_with_its_saved_calculation_version(imported):
    metrics = calculate(imported, "kg", None, None, None, None, calculation_version="stage1-audit-v1")
    path, manifest = imported.create("legacy-report", "report", metrics["snapshots"])
    write_json(path / "metrics.json", metrics)
    (path / "report.md").write_text(render(metrics), encoding="utf-8")
    imported.finish(path, manifest)
    assert replay(imported, "legacy-report")["metrics_sha256"] == metrics["metrics_sha256"]
