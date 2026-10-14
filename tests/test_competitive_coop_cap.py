from copy import deepcopy
from pathlib import Path

import pytest

from gamepersona.features import assign_features, feature_integrity, load_rules, validate_rules


RULES = Path(__file__).resolve().parents[1] / "gamepersona/rules"


def evidence(*tags, source="kaggle"):
    return [{"tag": tag, "source": source} for tag in tags]


@pytest.mark.parametrize("trigger", ["Competitive", "e-sports", " ESPORTS "])
def test_strong_competition_caps_coop_without_changing_competition(trigger):
    rules = load_rules(RULES / "tag_rules_v4.json")
    result = assign_features(evidence(trigger, "Co-op", "Online Co-Op", "Team-Based"), True, rules)
    assert result["values"]["COOP"] == .5
    assert result["values"]["COMP"] == 1
    assert result["values"]["SOCIAL"] == .5
    assert result["adjustments"][0]["original_value"] == 1
    assert all("上限为 0.5" in m["reason"] for m in result["matches"]["COOP"])


def test_pvp_alone_and_team_based_support_are_not_halved():
    rules = load_rules(RULES / "tag_rules_v4.json")
    pvp = assign_features(evidence("PvP", "Co-op"), True, rules)
    team = assign_features(evidence("Competitive", "Team-Based"), True, rules)
    assert pvp["values"]["COOP"] == 1 and pvp["adjustments"] == []
    assert team["values"]["COOP"] == .5 and team["adjustments"] == []


def test_source_union_trigger_and_duplicate_tags_preserve_integrity():
    rules = load_rules(RULES / "tag_rules_v4.json")
    tags = evidence("Co-op") + evidence("e-sports", source="steamspy")
    modes = {mode: assign_features(tags, True, rules, sources)
             for mode, sources in [("kaggle", {"kaggle"}), ("steamspy", {"steamspy"}), ("combined", None)]}
    assert modes["kaggle"]["values"]["COOP"] == 1
    assert modes["combined"]["values"]["COOP"] == .5
    assert assign_features(tags + tags, True, rules)["values"] == modes["combined"]["values"]
    assert feature_integrity([{"app_id": 730, "modes": modes}], rules)["status"] == "passed"


def test_legacy_rules_unchanged_and_unknown_remains_unknown():
    old = load_rules(RULES / "tag_rules_v3.json")
    new = load_rules(RULES / "tag_rules_v4.json")
    assert old["rules"] == new["rules"]
    source = evidence("Competitive", "Co-op")
    legacy = assign_features(source, True, old)
    assert legacy["values"]["COOP"] == 1 and "adjustments" not in legacy
    unknown = assign_features([], False, new)
    assert all(v is None for v in unknown["values"].values())


@pytest.mark.parametrize("change", [
    {"maximum": .25}, {"maximum": True}, {"trigger_tags": ["PvP"]}, {"trigger_tags": None},
])
def test_unapproved_cap_shapes_are_rejected(change):
    rules = deepcopy(load_rules(RULES / "tag_rules_v4.json"))
    rules["competitive_coop_cap"].update(change)
    with pytest.raises(ValueError, match="上限"):
        validate_rules(rules)
