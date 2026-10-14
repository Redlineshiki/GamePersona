from copy import deepcopy
import math
import pytest
from gamepersona.features import DIMENSIONS
from gamepersona.scoring import model_config,score_records,E_SCALE
from gamepersona.reference import reference_positions,build_report
from gamepersona.weight_reference import make_weight_reference,validate_weight_reference,WEIGHT_METHOD
from gamepersona.storage import Store,write_json,content_hash
from gamepersona.web.worker import AssessmentEngine


def setup_reference():
    model=model_config(min_reference=3,reference_method=WEIGHT_METHOD,reference_bandwidth=.1)
    observations=[[10*E_SCALE,w,*([e*E_SCALE]*12)] for w,e in [(1,0),(2,1),(3,1),(4,3)]]
    ref=make_weight_reference(observations,model,{"reference":"test","feature":"v3","rules":"v3"},[])
    s={"N":5,"H":100,"read_status":"success","coverage":1.,"unknown_ratio":0,
       "W_ticks":10*E_SCALE,"concentration":dict.fromkeys(DIMENSIONS,.4),
       "evidence_ticks":dict.fromkeys(DIMENSIONS,E_SCALE),"model_sha256":content_hash(model)}
    return model,ref,s


def test_weighted_midrank_and_effective_count():
    model,ref,s=setup_reference()
    model["min_reference"]=1;ref["model_sha256"]=content_hash(model)
    p=reference_positions(s,ref,model)
    assert p["P"]["value"]==35
    assert p["P"]["effective_reference"]==pytest.approx(100/30)
    model["min_reference"]=4;ref["model_sha256"]=content_hash(model)
    assert reference_positions(s,ref,model)["P"]["reason"]=="insufficient_effective_reference"


def test_game_count_and_hours_do_not_change_reference_coordinates():
    m,r,s=setup_reference()
    before=reference_positions(s,r,m)
    s["N"]=100;s["H"]=1000000
    assert reference_positions(s,r,m)==before


@pytest.mark.parametrize("change,reason",[("few","insufficient_games"),("range","outside_reference_range"),
    ("concentrated","concentrated_evidence"),("source","source_timeout")])
def test_no_fallback_or_fabricated_support(change,reason):
    m,r,s=setup_reference()
    if change=="few":s["N"]=2
    elif change=="range":s["W_ticks"]=11*E_SCALE
    elif change=="concentrated":s["concentration"]["P"]=.9
    else:s["read_status"]="timeout"
    assert reference_positions(s,r,m)["P"]["reason"]==reason


def test_scoring_adds_W_only_for_new_model_and_keeps_evidence():
    features=[{"app_id":i,"modes":{"combined":{"complete":True,"eligible":True,
        "values":dict.fromkeys(DIMENSIONS,1.),"matches":{}}}} for i in range(1,7)]
    records=[{"app_id":i,"duration_hours":10} for i in range(1,6)]
    legacy=score_records(records,features,model_config())
    new_model=model_config(reference_method=WEIGHT_METHOD,reference_bandwidth=.1)
    new=score_records(records,features,new_model)
    assert "W_ticks" not in legacy
    assert new["W_ticks"]==new["evidence_ticks"]["P"]
    assert new["evidence_ticks"]==legacy["evidence_ticks"]
    added=score_records(records+[{"app_id":6,"duration_hours":.1}],features,new_model)
    assert added["W"]-new["W"]==pytest.approx(math.log1p(.1),abs=1e-10)


def test_frozen_versions_degenerate_and_invalid_rows():
    m,r,s=setup_reference()
    bad=deepcopy(m);bad["reference_bandwidth"]*=2
    with pytest.raises(ValueError,match="不兼容"):reference_positions(s,r,bad)
    malformed=deepcopy(r);malformed["observations"][1][2]=-1
    with pytest.raises(ValueError,match="逐人"):validate_weight_reference(malformed,m,full=True)
    for row in r["observations"]:row[2]=0
    assert reference_positions(s,r,m)["P"]["reason"]=="degenerate_reference"


def test_production_engine_and_report_use_v3_provenance(tmp_path):
    m,r,s=setup_reference()
    store=Store(tmp_path)
    features=[{"app_id":i,"modes":{"combined":{"complete":True,"eligible":True,
        "values":dict.fromkeys(DIMENSIONS,1.),"matches":{}}}} for i in range(1,6)]
    records=[{"app_id":i,"duration_hours":math.expm1(2)} for i in range(1,6)]
    actual_W=score_records(records,features,m)["W_ticks"]
    for row in r["observations"]:row[0]=actual_W
    r["W_ticks_range"]=[actual_W,actual_W]
    path,manifest=store.create("W","reference",{})
    for name,value in [("model.json",m),("reference.json",r),("features.json",features)]:write_json(path/name,value)
    store.finish(path,manifest,experimental_acceptance="passed")
    engine=AssessmentEngine(store)
    report=engine.assess(records,"success","W","input")
    assert "W_ticks" in report["score"] and report["versions"]["rules"]=="v3"
    assert all(p["value"] is not None for p in report["percentiles"].values())
    assert report==engine.assess(records,"success","W","input")
