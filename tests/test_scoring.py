from copy import deepcopy
import math

import pytest

from gamepersona.collect import normalize_steam
from gamepersona.features import DIMENSIONS, assign_features, load_rules
from gamepersona.scoring import feature_index, model_config, score_records, time_weight


def features():
    return [{"app_id": i, "rule_version": "fixture", "modes": {"combined": assign_features(
        [{"tag": t, "source": "kaggle"} for t in tags], bool(tags), load_rules())}}
        for i, tags in enumerate([[], ["Strategy", "Action"], ["Singleplayer"], ["Indie"], []]) if i]


def records(*hours):
    return [{"app_id": i+1, "duration_hours": h, "exclusion_reason": None} for i, h in enumerate(hours)]


def test_common_set_zero_unknown_coverage_and_double_positive():
    result = score_records(records(10, 2, 3, 4) + [{"app_id": 99, "duration_hours": 1}], features(), model_config())
    assert result["N"] == 2
    assert result["H"] == 12
    assert result["coverage"] == .6
    assert result["E"]["P"] > 0 and result["E"]["R"] > 0
    assert result["exclusion_counts"] == {"all_zero_feature": 1, "unknown_feature": 1, "unmatched_feature": 1}
    assert result["E"]["G"] == 0 and result["concentration"]["G"] is None


def test_duplicates_conflicts_no_sum_and_no_date_ordering():
    r = records(2, 4)
    base = score_records(r, features(), model_config())
    assert base == score_records(r + r, features(), model_config())
    conflict = score_records(r + [{**r[0], "duration_hours": 20}], features(), model_config())
    assert conflict["H"] == 4 and conflict["known_positive_hours"] == 4
    assert conflict["exclusion_counts"]["conflicting_user_game"] == 1


def test_sources_same_model_contract_and_determinism():
    online = normalize_steam([{"appid": 1, "playtime_forever": 120}, {"appid": 2, "playtime_forever": 240}], "x")
    a = score_records(online, features(), model_config())
    b = score_records(records(2, 4), features(), model_config())
    assert a == b
    assert a == score_records(list(reversed(online)), features(), model_config())


def test_missing_zero_invalid_and_read_failure_stay_distinct():
    result = score_records(records(None, 0), features(), model_config())
    assert result["coverage"] is None and result["unknown_duration_games"] == 1
    assert result["E"] == dict.fromkeys(DIMENSIONS, 0)
    assert result["exclusion_counts"] == {"duration_unknown_or_invalid": 1, "zero_duration": 1}
    failed = score_records(records(10), features(), model_config(), "timeout")
    assert failed["N"] == 0 and "source_timeout" in failed["sufficiency_reasons"]
    assert "source_timeout" in score_records([], features(), model_config(), "timeout")["sufficiency_reasons"]


def test_partial_features_and_bad_models_rejected():
    f = features()
    f[0]["modes"]["combined"]["values"]["P"] = None
    with pytest.raises(ValueError, match="状态"):
        feature_index(f)
    with pytest.raises(ValueError):
        model_config(cap_hours=float('nan'))
    with pytest.raises(ValueError):
        model_config(min_reference=True)


def test_caps_and_extreme_duration_reduce_marginal_contribution():
    m = model_config()
    assert time_weight(10000, m) < 10000
    assert time_weight(10000, model_config(cap_hours=100)) == math.log1p(100)
    a = score_records(records(10000), features(), m)
    assert a["concentration"]["P"] == 1 and a["effective_games"]["P"] == 1
    assert "insufficient_games" in a["sufficiency_reasons"]


def test_source_conflict_does_not_count_as_unknown_duration():
    a = score_records([{"app_id": 1, "duration_hours": None, "exclusion_reason": "conflicting_user_game"}], features(), model_config())
    assert a["unknown_duration_games"] == 0
    assert a["known_positive_hours"] == 0


@pytest.mark.parametrize("hours", [float('nan'), float('inf'), -1, True, 'bad'])
def test_bad_duration_is_excluded_without_nonfinite_output(hours):
    a = score_records(records(hours), features(), model_config())
    assert a["N"] == 0 and a["unknown_duration_games"] == 1
