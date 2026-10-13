from scripts.analyze_stage1_sample import summarize


def test_sample_denominators_and_overlapping_account_gaps():
    candidates = [
        {"app_id": 1, "reasons": ["top_review_users"], "tags": ["Action"], "primary_tag": "Action"},
        {"app_id": 2, "reasons": ["stratified"], "tags": ["Strategy"], "primary_tag": "Strategy"},
        {"app_id": 3, "reasons": ["stratified", "authorized_account"], "tags": [], "primary_tag": "unknown"},
        {"app_id": 4, "reasons": ["authorized_account"], "tags": [], "primary_tag": "unknown"},
    ]
    tags = [
        {"app_id": 1, "status": "available", "tags": [{"tag": "Action", "votes": 10}]},
        {"app_id": 2, "status": "no_tags", "tags": []},
        {"app_id": 3, "status": "network_failure", "tags": []},
        {"app_id": 4, "status": "available", "tags": [{"tag": "Story", "votes": 2}]},
    ]
    groups = summarize(candidates, tags)
    assert groups["base_sample"]["tag_coverage"]["denominator"] == 3
    assert groups["base_sample"]["tag_coverage"]["ratio"] == 1 / 3
    assert groups["all_candidates"]["tag_coverage"]["ratio"] == 1 / 2
    assert groups["authorized_account"]["tag_coverage"]["ratio"] == 1 / 2
    assert groups["account_additions"]["tag_coverage"]["denominator"] == 1
    assert groups["stratified"]["gaps_with_kaggle_tags"] == 1
    assert groups["stratified"]["gaps_without_kaggle_tags"] == 1
    assert groups["stratified"]["states"]["no_tags"] == 1
    assert groups["stratified"]["states"]["network_failure"] == 1


def test_account_placeholder_tags_do_not_hide_kaggle_evidence():
    candidates = [{"app_id": 4, "reasons": ["authorized_account"], "tags": [], "primary_tag": "unknown"}]
    tags = [{"app_id": 4, "status": "no_tags", "tags": []}]
    groups = summarize(candidates, tags, {4: ["Action"]})
    assert groups["account_additions"]["gaps_with_kaggle_tags"] == 1
    assert groups["account_additions"]["gaps_without_kaggle_tags"] == 0
