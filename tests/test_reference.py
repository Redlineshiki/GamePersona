from copy import deepcopy

import pytest

from gamepersona.features import DIMENSIONS
from gamepersona.interpretation import interpret, share_projection
from gamepersona.reference import FIXED_BOUNDS, make_reference, reference_positions, build_report
from gamepersona.scoring import model_config, E_SCALE, H_SCALE
from gamepersona.storage import content_hash


def fixture_reference():
    model = model_config(min_reference=3)
    rows = [{"N": 5, "H_ticks": 200*H_SCALE, "coverage": 1., "unknown_ratio": 0.,
             **{f"E_{k}": n*E_SCALE for k in DIMENSIONS}} for n in [0,1,1,3]]
    ref = make_reference(rows, model, FIXED_BOUNDS, {"feature": "fixture", "reference": "fixture"})
    score = {"model_sha256": content_hash(model), "read_status": "success", "N": 5, "H": 200, "H_ticks": 200*H_SCALE,
             "coverage": 1., "unknown_ratio": 0., "evidence_ticks": dict.fromkeys(DIMENSIONS,E_SCALE),
             "concentration": dict.fromkeys(DIMENSIONS,.4)}
    return model, ref, score


def test_ties_midrank_identical_and_zero_not_missing():
    model, ref, score = fixture_reference()
    assert all(p["value"] == 50 for p in reference_positions(score, ref, model).values())
    score["evidence_ticks"]["P"] = 0
    assert reference_positions(score,ref,model)["P"]["value"] == 12.5
    assert reference_positions(score,ref,model)["P"]["zero_evidence"]


@pytest.mark.parametrize("change,reason", [({"N": 2},"insufficient_games"),
    ({"coverage": .1},"insufficient_coverage"), ({"unknown_ratio": .5},"unknown_duration"),
    ({"read_status": "timeout"},"source_timeout"), ({"H": 100000,"H_ticks": 100000*H_SCALE},"no_reference_group"),
    ({"H": 201,"H_ticks": 201*H_SCALE},"outside_reference_range")])
def test_no_hidden_fallback(change, reason):
    m,r,s = fixture_reference()
    s.update(change)
    assert all(p["value"] is None and p["reason"] == reason for p in reference_positions(s,r,m).values())


def test_partial_degenerate_concentration_and_version_mismatch():
    m,r,s = fixture_reference()
    r["groups"]["1:1"]["distributions"]["G"] = [0]*4
    s["concentration"]["R"] = 1
    p = reference_positions(s,r,m)
    assert p["G"]["reason"] == "degenerate_reference"
    assert p["R"]["reason"] == "concentrated_evidence"
    assert p["P"]["value"] == 50
    bad = deepcopy(m); bad["version"] = "new"
    with pytest.raises(ValueError,match="不兼容"):
        reference_positions(s,r,bad)


def test_independent_levels_mixed_and_optional_type_without_rounding():
    m = model_config()
    p = {k: {"value": 85.} for k in DIMENSIONS}
    i = interpret(p,m)
    assert i["type"] is None and i["groups"][0]["level"] == "double_high"
    assert i["groups"][0]["tendency"] == "mixed"
    p["P"]["value"],p["R"]["value"] = 5,6
    assert interpret(p,m)["groups"][0]["level"] == "double_low"
    for a,b in [('P','R'),('G','O'),('M','N'),('H','C')]:
        p[a]["value"],p[b]["value"] = 80,69.9999
    assert interpret(p,m)["type"] == "PGMH"
    p['G']["value"] = None
    assert interpret(p,m)["type"] is None and interpret(p,m)["groups"][1]["tendency"] == "pending"


def test_report_fixed_and_share_allowlist_no_personal_data():
    m,r,s = fixture_reference()
    report = build_report(s,r,m,"input-01")
    assert report == build_report(s,r,m,"input-01")
    report["steam_id"] = "private"
    report["contributions"] = ["private game"]
    share = share_projection(report)
    assert "steam_id" not in share and "contributions" not in share and "score" not in share
    assert share["report_sha256"] == report["report_sha256"]
    assert list(share['dimensions']) == list(DIMENSIONS)
