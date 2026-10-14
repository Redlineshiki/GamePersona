from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import httpx
import pytest

from gamepersona.features import (
    DIMENSIONS, assign_features, build_features, load_rules, replay_features, validate_rules,
)
from gamepersona.storage import read_json, write_json


def evidence(*tags, source="kaggle", votes=None):
    return [{"tag": tag, "source": source, "votes": votes, "snapshot": "test", "collected_at": None} for tag in tags]


def test_aliases_duplicates_noise_and_source_votes_do_not_inflate_scores():
    rules = load_rules()
    original = evidence("Co-op", "e-sports", "Singleplayer", "Strategy")
    base = assign_features(original, True, rules)
    expanded = assign_features(original + evidence(" COOP ", "eSports", "single player", "Unrelated")
                               + evidence("Co-op", source="steamspy", votes=999999), True, rules)
    assert expanded["values"] == base["values"]
    assert base["values"]["COOP"] == base["values"]["COMP"] == base["values"]["SOLO"] == 1
    assert base["values"]["SOCIAL"] == .5
    assert base["values"]["P"] == .25
    assert len(expanded["matches"]["COOP"]) == 1
    assert len(expanded["matches"]["COOP"][0]["evidence"]) == 3


def test_maximum_aggregation_is_monotonic_not_a_sum():
    rules = load_rules()
    weak = assign_features(evidence("Strategy", "Tactical"), True, rules)
    strong = assign_features(evidence("Strategy", "Tactical", "Resource Management"), True, rules)
    assert weak["values"]["P"] == .5
    assert strong["values"]["P"] == 1
    assert all(strong["values"][k] >= weak["values"][k] for k in DIMENSIONS)


def test_unknown_zero_and_no_opposite_inference():
    rules = load_rules()
    unknown = assign_features([], False, rules)
    zero = assign_features(evidence("Indie", "PvE"), True, rules)
    solo = assign_features(evidence("Singleplayer"), True, rules)
    assert all(v is None for v in unknown["values"].values())
    assert not unknown["complete"] and not unknown["eligible"]
    assert all(v == 0 for v in zero["values"].values())
    assert zero["complete"] and not zero["eligible"] and zero["state"] == "no_rule_hit"
    assert solo["values"]["SOLO"] == 1 and solo["values"]["SOCIAL"] == 0
    assert solo["matches"]["SOCIAL"] == []


def test_guided_v2_weak_support_and_versioned_other_dimensions():
    old = load_rules(Path(str(files("gamepersona").joinpath("rules/tag_rules_v1.json"))))
    current = load_rules(Path(str(files("gamepersona").joinpath("rules/tag_rules_v2.json"))))
    assert old["version"] == "tag-rules-v1"
    assert current["version"] == "tag-rules-v2-guided"
    source = evidence("Platformer", "Puzzle", "Visual Novel", "Sandbox")
    before = assign_features(source, True, old)
    after = assign_features(source + evidence("Puzzle", source="steamspy", votes=500), True, current)
    assert before["values"]["G"] == 0
    assert after["values"]["G"] == .25  # Several weak tags and duplicated sources do not add.
    assert after["values"]["O"] == 1  # Guided support can coexist with open support.
    assert all(before["values"][d] == after["values"][d] for d in DIMENSIONS if d != "G")
    related = assign_features(source + evidence("Escape Room"), True, current)
    assert related["values"]["G"] == .5


def test_mechanics_v3_weak_genre_aliases_and_guided_coexist():
    current = load_rules()
    guided = load_rules(Path(str(files("gamepersona").joinpath("rules/tag_rules_v2.json"))))
    assert current["version"] == "tag-rules-v3-guided-mechanics"
    source = evidence("Rogue-like", "Rogue-lite", "Management", "Puzzle")
    before = assign_features(source, True, guided)
    weak = assign_features(source + evidence("Roguelike", source="steamspy", votes=200), True, current)
    assert before["values"]["M"] == 0
    assert weak["values"]["M"] == .25
    assert weak["values"]["G"] == .25
    assert all(weak["values"][d] == before["values"][d] for d in DIMENSIONS if d != "M")
    related = assign_features(source + evidence("Inventory Management"), True, current)
    strong = assign_features(source + evidence("Deckbuilding"), True, current)
    assert related["values"]["M"] == .5 and strong["values"]["M"] == 1


def test_every_rule_has_effect_and_explanation():
    config = load_rules()
    for rule in config["rules"]:
        result = assign_features(evidence(rule["tag"]), True, config)
        assert result["values"][rule["dimension"]] == rule["weight"]
        assert all(m["reason"] for m in result["matches"][rule["dimension"]])
    bad = deepcopy(config)
    bad["rules"][0]["weight"] = .9
    with pytest.raises(ValueError, match="权重"):
        validate_rules(bad)
    bad = deepcopy(config)
    bad["rules"][0]["aliases"].append("Co-op")
    with pytest.raises(ValueError, match="多个"):
        validate_rules(bad)


@pytest.mark.parametrize("config", [None, [], {}, {"schema_version": "stage2-tag-support-v1", "version": "v1", "dimensions": [None]}])
def test_invalid_custom_rule_shapes_are_rejected(config):
    with pytest.raises(ValueError):
        validate_rules(config)


def feature_inputs(store):
    path, manifest = store.create("sel", "selection", {"kaggle_snapshot": "kg"})
    write_json(path / "candidates.json", [{"app_id": i, "tags": [], "reasons": ["top_review_users"]} for i in range(1, 6)])
    store.finish(path, manifest)
    path, manifest = store.create("spy", "steamspy", {"selection_snapshot": "sel"})
    tags = [
        {"app_id": 1, "status": "available", "tags": [{"tag": "Resource Management", "votes": 1}, {"tag": "Difficult", "votes": 0}]},
        {"app_id": 2, "status": "available", "tags": [{"tag": "PvP", "votes": 2}, {"tag": "Co-op", "votes": 3}]},
        {"app_id": 3, "status": "no_tags", "tags": []},
        {"app_id": 4, "status": "no_tags", "tags": []},
        {"app_id": 5, "status": "available", "tags": [{"tag": "Indie", "votes": 1}]},
    ]
    write_json(path / "tags.json", tags)
    store.finish(path, manifest)


def test_full_source_join_snapshots_replay_and_tamper_detection(imported, monkeypatch):
    store = imported
    feature_inputs(store)
    def offline(*args, **kwargs):
        raise AssertionError("feature commands must not open HTTP clients")
    monkeypatch.setattr(httpx, "Client", offline)
    metrics = build_features(store, "features", "kg", "spy", "sel")
    outputs = read_json(store.path("features") / "features.json")
    assert outputs[0]["modes"]["combined"]["values"]["R"] == .25  # full metadata, not empty selection tags
    assert outputs[0]["modes"]["combined"]["values"]["P"] == 1
    assert outputs[0]["modes"]["combined"]["values"]["H"] == 0  # zero-vote tags do not count
    assert outputs[1]["modes"]["combined"]["values"]["COOP"] == 1
    assert outputs[1]["modes"]["combined"]["values"]["COMP"] == 1
    assert outputs[3]["modes"]["combined"]["state"] == "unknown"
    combined = metrics["groups"]["all"]["modes"]["combined"]
    assert (combined["complete"], combined["eligible"], combined["all_zero"], combined["unknown"]) == (4, 2, 2, 1)
    assert metrics["integrity_checks"]["status"] == "passed"
    assert replay_features(store, "features")["status"] == "identical"
    with pytest.raises(ValueError, match="已存在"):
        build_features(store, "features", "kg", "spy", "sel")
    write_json(store.path("spy") / "tags.json", [])
    with pytest.raises(ValueError, match="变化"):
        replay_features(store, "features")


def test_mismatched_snapshot_lineage_is_rejected(imported):
    feature_inputs(imported)
    with pytest.raises(ValueError, match="来源关联"):
        build_features(imported, "features", "different-kg", "spy", "sel")


def test_feature_cli_build_and_replay_stay_offline(imported, monkeypatch, capsys):
    from gamepersona.cli import main

    feature_inputs(imported)
    def offline(*args, **kwargs):
        raise AssertionError("feature CLI must not create an HTTP client")
    monkeypatch.setattr(httpx, "Client", offline)
    common = ["--root", str(imported.root)]
    assert main(common + ["build-features", "--snapshot", "features", "--kaggle", "kg", "--steamspy", "spy", "--selection", "sel"]) == 0
    assert main(common + ["replay-features", "--snapshot", "features"]) == 0
    assert "identical" in capsys.readouterr().out
