import pytest

from gamepersona.audit import audit, coverage, replay
from gamepersona.sampling import select_games
from gamepersona.storage import read_json


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
