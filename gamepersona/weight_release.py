"""Promote a passed, pinned W validation together with its current feature rules."""
import csv
from pathlib import Path
from .features import pin_input, verify_pins, load_rules
from .storage import read_json, write_json, content_hash, sha256
from .scoring import E_SCALE
from .weight_reference import make_weight_reference, WEIGHT_METHOD


def release_products(store, snapshot, config):
    verify_pins(store,config["inputs"])
    validation = store.path(config["validation"]["snapshot"])
    for name,h in config["validation"]["artifact_hashes"].items():
        if sha256(validation/name) != h:
            raise ValueError("W验证产物已变化")
    metrics,selected,inputs = (read_json(validation/name) for name in ("metrics.json","selection.json","inputs.json"))
    baseline_pin=config["inputs"]["baseline"]
    aggregate_pin=config["inputs"]["aggregate"]
    if (inputs["pins"]["log"]["snapshot"] != aggregate_pin["snapshot"]
            or inputs["pins"]["log"]["artifact_hashes"]["log.parquet"] != aggregate_pin["artifact_hashes"]["log.parquet"]
            or inputs["model_sha256"] != baseline_pin["artifact_hashes"]["model.json"]
            or inputs["old_reference_sha256"] != baseline_pin["artifact_hashes"]["reference.json"]):
        raise ValueError("W验证使用的聚合或原参考与发布输入不一致")
    if (metrics["acceptance"] != "passed" or not all(metrics["checks"].values())
            or selected["selected_mode"] != "W" or selected["selected_bandwidth"][0] != .1
            or not metrics["exposure_verification"]["passed"]):
        raise ValueError("W联合版本未通过固定发布条件")
    feature_path = store.path(config["inputs"]["features"]["snapshot"])
    feature_manifest = store.load(config["inputs"]["features"]["snapshot"],"features")
    rules,features = read_json(feature_path/"rules.json"),read_json(feature_path/"features.json")
    if content_hash(rules) != config["rules_sha256"]:
        raise ValueError("发布标签规则版本不一致")
    aggregate = config["inputs"]["aggregate"]["snapshot"]
    am = store.load(aggregate,"aggregate")
    if am["config"]["inputs"]["features"]["snapshot"] != config["inputs"]["features"]["snapshot"]:
        raise ValueError("W聚合与发布特征不一致")
    # The validation reference supplies the unchanged scoring/interpretation parameters.
    model = read_json(store.path(config["inputs"]["baseline"]["snapshot"])/"model.json")
    model.update(version="model-stage3-weight-v3-v1", reference_method=WEIGHT_METHOD, reference_bandwidth=.1)
    fitted = sorted(read_json(validation/"fit_exposure.json"),key=lambda r:r["user_key"])
    with (validation/"fit.csv").open(encoding="utf-8",newline="") as f:
        lines = list(csv.reader(f))
    if len(lines) != len(fitted):
        raise ValueError("W拟合样本行数不一致")
    observations=[]
    for row,user in zip(lines,fitted):
        if (float(row[0]) != user["W_ticks"]/E_SCALE or float(row[1]) != user["H_ticks"]/1e8
                or any(int(row[i+3]) != user["E_"+d] for i,d in enumerate(rules_dimension_codes(rules)))):
            raise ValueError("W拟合观测与逐人暴露权重不一致")
        observations.append([user["W_ticks"],float(row[2]),*[int(v) for v in row[3:]]])
    versions={"feature":config["inputs"]["features"]["snapshot"],"aggregate":aggregate,"reference":snapshot,
              "rules":rules["version"],"rules_sha256":config["rules_sha256"]}
    baseline = read_json(store.path(config["inputs"]["baseline"]["snapshot"])/"reference.json")
    if baseline["versions"]["feature"] != config["inputs"]["features"]["snapshot"]:
        raise ValueError("W验证和正式发布必须使用同一标签特征")
    reference=make_weight_reference(observations,model,versions,baseline["limitations"])
    return model,reference,features,rules,metrics


def rules_dimension_codes(rules):
    return [d["code"] for d in rules["dimensions"]]


def promote_weight_reference(store, snapshot, validation, aggregate, features, baseline):
    if store.path(snapshot).exists():
        raise ValueError("参考快照已存在；新版本须使用新名称")
    path = store.path(validation)
    proof=read_json(path/"manifest.json")
    for name,h in proof["artifacts"].items():
        if sha256(path/name) != h:
            raise ValueError("W验证清单不一致")
    feature_path=store.path(features)
    rules=read_json(feature_path/"rules.json")
    if content_hash(rules) != content_hash(load_rules()):
        raise ValueError("正式发布必须采用当前标签规则；请重建特征及W验证")
    config={"version":"weight-production-v1", "inputs":{
        "aggregate":pin_input(store,aggregate,"aggregate",["log.parquet","features.json"]),
        "features":pin_input(store,features,"features",["features.json","rules.json"]),
        "baseline":pin_input(store,baseline,"reference",["model.json","reference.json"])},
        "validation":{"snapshot":validation,"artifact_hashes":{n:sha256(path/n) for n in
            ("metrics.json","selection.json","inputs.json","fit.csv","fit_exposure.json","exposure_verification.json","protocol.md")}},
        "rules_sha256":content_hash(rules)}
    products=release_products(store,snapshot,config)
    output,manifest=store.create(snapshot,"reference",config)
    for name,value in zip(("model.json","reference.json","features.json","rules.json","validation.json"),products):
        write_json(output/name,value)
    (output/"protocol.md").write_text((path/"protocol.md").read_text(encoding="utf-8"),encoding="utf-8")
    store.finish(output,manifest,experimental_acceptance="passed", reference_method=WEIGHT_METHOD,
                 rule_version=rules["version"],reference_sha256=content_hash(products[1]))
    return {"snapshot":snapshot,"reference_method":WEIGHT_METHOD,"rules":rules["version"],"observations":len(products[1]["observations"])}


def replay_weight_reference(store,snapshot):
    manifest=store.load(snapshot,"reference")
    store.verify(snapshot)
    products=release_products(store,snapshot,manifest["config"])
    for name,value in zip(("model.json","reference.json","features.json","rules.json","validation.json"),products):
        if value != read_json(store.path(snapshot)/name):
            raise ValueError("W正式参考离线重算不一致："+name)
    return {"status":"identical","reference_sha256":content_hash(products[1])}
