"""Predeclared candidate selection, followed by an untouched evaluation split."""
from __future__ import annotations

from bisect import bisect_right
from copy import deepcopy
from pathlib import Path

from .database import connect, literal, rows
from .features import DIMENSIONS, pin_input, verify_pins
from .scoring import H_SCALE, feature_index, score_records, model_config
from .offline import CANDIDATES, SPLIT_SALT
from .reference import FIXED_BOUNDS, make_reference, reference_positions, build_report
from .interpretation import interpret
from .storage import Store, content_hash, read_json, write_json, temporary_workspace

EXPERIMENT_VERSION = "stage3-experiment-v1"


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    index = p*(len(v)-1)
    lower = int(index)
    return v[lower] + (v[min(lower+1,len(v)-1)]-v[lower])*(index-lower)


def group_sql(bounds: dict) -> str:
    n = "+".join(f"CASE WHEN N>={x} THEN 1 ELSE 0 END" for x in bounds["N"])
    h = "+".join(f"CASE WHEN H_ticks>={int(x*H_SCALE)} THEN 1 ELSE 0 END" for x in bounds["H"])
    return f"cast(({n})-1 AS VARCHAR)||':'||cast(({h})-1 AS VARCHAR)"


def fit_reference(con, parquet: Path, model: dict, bounds: dict, versions: dict) -> dict:
    sql = f"""SELECT *,{group_sql(bounds)} group_id FROM read_parquet({literal(parquet)})
       WHERE split='fit' AND N>={model['min_games']} AND coverage>={model['min_coverage']}
         AND unknown_ratio<={model['max_unknown_ratio']}"""
    support = rows(con, f"SELECT group_id,count(*) full_samples,min(N) N_min,max(N) N_max,min(H_ticks) H_min,max(H_ticks) H_max FROM ({sql}) GROUP BY group_id")
    selected = rows(con, f"SELECT * FROM ({sql}) QUALIFY row_number() OVER(PARTITION BY group_id ORDER BY sha256('{SPLIT_SALT}'||user_key),user_key)<=5000")
    reference = make_reference(selected,model,bounds,versions)
    for group in support:
        entry = reference["groups"].get(group["group_id"])
        if entry:
            entry.update({k:v for k,v in group.items() if k!='group_id'})
    return reference


def load_sample(con, store: Store, aggregate: str, split: str) -> tuple[list[dict],dict[str,list[dict]]]:
    source = store.path(aggregate)/"log.parquet"
    selected = rows(con, f"SELECT * FROM read_parquet({literal(source)}) WHERE split='{split}' AND N>=5 AND coverage>=.8 ORDER BY sha256('{SPLIT_SALT}'||user_key),user_key LIMIT 500")
    if not selected:
        return [],{}
    # Bounded sample keys, not the complete offline user database.
    keys = ",".join(literal(r["user_key"]) for r in selected)
    manifest = store.load(aggregate,"aggregate")
    kg = manifest["config"]["inputs"]["kaggle"]["snapshot"]
    source_records = store.path(kg)/"normalized/records.parquet"
    records = rows(con, f"SELECT user_key,app_id,duration_hours,duration_state,exclusion_reason FROM read_parquet({literal(source_records)}) WHERE user_key IN ({keys}) ORDER BY user_key,app_id")
    grouped = {r["user_key"]:[] for r in selected}
    for record in records:
        grouped[record["user_key"]].append(record)
    return selected,grouped


def prepared_scores(records: dict, features: dict, model: dict) -> dict:
    result = {}
    for key, source in records.items():
        base = score_records(source,features,model)
        variants = []
        for scale in (.9,1.1):
            altered = [{**r,"duration_hours": r["duration_hours"]*scale if r["duration_hours"] is not None else None} for r in source]
            variants.append(score_records(altered,features,model))
        largest = max(base["contributions"],key=lambda c:sum(c["ticks"].values()),default=None)
        dropped = [r for r in source if not largest or r["app_id"] != largest["app_id"]]
        result[key] = (base,variants,score_records(dropped,features,model))
    return result


def evaluate(prepared: dict, reference: dict, model: dict) -> dict:
    full = any_supported = dimensions = lost = comparable = type_total = type_stable = 0
    deltas, deleted_deltas = [],[]
    deletion_lost = deletion_total = 0
    reasons = {}
    for score, altered, dropped in prepared.values():
        original = reference_positions(score,reference,model)
        valid = [k for k in DIMENSIONS if original[k]["value"] is not None]
        full += len(valid)==12
        any_supported += bool(valid)
        dimensions += len(valid)
        original_type = interpret(original,model)["type"]
        for other in altered:
            current = reference_positions(other,reference,model)
            for k in valid:
                comparable += 1
                if current[k]["value"] is None:
                    lost += 1
                else:
                    deltas.append(abs(current[k]["value"]-original[k]["value"]))
            if original_type:
                type_total += 1
                type_stable += interpret(current,model)["type"] == original_type
        removed = reference_positions(dropped,reference,model)
        for k in valid:
            deletion_total += 1
            if removed[k]["value"] is None:
                deletion_lost += 1
            else:
                deleted_deltas.append(abs(removed[k]["value"]-original[k]["value"]))
        for value in original.values():
            if value["reason"]:
                reasons[value["reason"]] = reasons.get(value["reason"],0)+1
    n = len(prepared)
    metrics = {"users": n, "full_twelve_users": full, "any_supported_users": any_supported,
               "any_supported_ratio": any_supported/n if n else 0, "displayable_dimensions": dimensions,
               "perturbation": {"median_absolute_delta": quantile(deltas,.5), "p95_absolute_delta": quantile(deltas,.95),
                                "lost_support_ratio": lost/comparable if comparable else None,
                                "comparable_dimensions": comparable,"retained_dimensions":len(deltas)},
               "deletion": {"median_absolute_delta":quantile(deleted_deltas,.5), "p95_absolute_delta":quantile(deleted_deltas,.95),
                            "lost_support_ratio":deletion_lost/deletion_total if deletion_total else None},
               "type": {"original_type_perturbations":type_total,"retained_same":type_stable,
                        "consistency":type_stable/type_total if type_total else None,
                        "stability_evaluated":type_total>=40}, "reasons":reasons}
    p = metrics["perturbation"]
    metrics["passed"] = (n>=200 and full>=20 and metrics["any_supported_ratio"]>=.8
                          and p["median_absolute_delta"] is not None and p["median_absolute_delta"]<=5
                          and p["p95_absolute_delta"]<=15 and p["lost_support_ratio"]<=.2
                          and (type_total<40 or metrics["type"]["consistency"]>=.8))
    return metrics


def experiment(store: Store, snapshot: str, aggregate: str, protocol: Path) -> dict:
    am = store.load(aggregate,"aggregate")
    pins = {"aggregate":pin_input(store,aggregate,"aggregate",["features.json","metrics.json",*[f"{k}.parquet" for k in CANDIDATES]])}
    path,manifest = store.create(snapshot,"reference", {"inputs":pins,"version":EXPERIMENT_VERSION,
                                    "protocol_sha256":content_hash(protocol.read_text(encoding='utf-8'))})
    (path/"protocol.md").write_text(protocol.read_text(encoding='utf-8'),encoding='utf-8')
    metrics = calculate_experiment(store, aggregate, snapshot, path)
    write_json(path/"metrics.json",metrics)
    store.finish(path,manifest,experimental_acceptance=metrics["acceptance"],metrics_sha256=content_hash(metrics))
    return metrics


def calculate_experiment(store: Store, aggregate: str, reference_id: str, path: Path) -> dict:
    am = store.load(aggregate,"aggregate")
    features = read_json(store.path(aggregate)/"features.json")
    index = feature_index(features)
    versions = {"feature":am["config"]["inputs"]["features"]["snapshot"],"aggregate":aggregate,"reference":reference_id}
    con = connect(":memory:",threads=1)
    con.execute("SET temp_directory = ?",[str(path/"spill")])
    try:
        calibration_rows,calibration_records = load_sample(con,store,aggregate,"calibration")
        variants, comparisons, parity = {}, [], []
        for candidate,model in CANDIDATES.items():
            print("校准候选 "+candidate,flush=True)
            prepared = prepared_scores(calibration_records,index,model)
            variants[candidate] = prepared
            sql_scores = rows(con,f"SELECT * FROM read_parquet({literal(store.path(aggregate)/f'{candidate}.parquet')}) WHERE user_key IN ("+",".join(literal(k) for k in prepared)+")")
            aligned = {r['user_key']:r for r in sql_scores}
            for key,(score,_,_) in prepared.items():
                actual = aligned[key]
                parity.append(score['N']==actual['N'] and score['H_ticks']==actual['H_ticks']
                              and all(score['evidence_ticks'][k]==actual[f'E_{k}'] for k in DIMENSIONS))
            fixed = deepcopy(FIXED_BOUNDS)
            quantiles = rows(con, f"SELECT quantile_cont(N,[0,.5,.8,.95]) n,quantile_cont(ln(1+H_ticks::DOUBLE/{H_SCALE}),[0,.5,.8,.95]) h FROM read_parquet({literal(store.path(aggregate)/f'{candidate}.parquet')}) WHERE split='fit'")[0]
            import math
            quantile_bounds = {"N":sorted(set(max(3,int(x)) for x in quantiles['n'])),
                               "H":sorted(set([0.,*[math.expm1(x) for x in quantiles['h'][1:]]]))}
            for grouping,bounds in (("fixed",fixed),("quantile",quantile_bounds)):
                ref = fit_reference(con,store.path(aggregate)/f'{candidate}.parquet',model,bounds,versions)
                metrics = evaluate(prepared,ref,model)
                comparisons.append({"candidate":candidate,"grouping":grouping,"model":model,"bounds":bounds,"metrics":metrics})
        passing = [r for r in comparisons if r['candidate']!='linear' and r['metrics']['passed']]
        selected = next((r for r in passing if r['candidate']=='log' and r['grouping']=='fixed'),None)
        if selected is None:
            selected = min(passing,key=lambda r:r['metrics']['perturbation']['p95_absolute_delta'],default=comparisons[0])
        candidate, model, bounds = selected['candidate'],deepcopy(selected['model']),selected['bounds']
        sensitivity = []
        for change in ({"min_games":3},{"min_coverage":.9},{"min_reference":500},{"max_concentration":.6},{"max_unknown_ratio":0}):
            alternate = {**model,**change}
            ref = fit_reference(con,store.path(aggregate)/f'{candidate}.parquet',alternate,bounds,versions)
            sensitivity.append({"change":change,"metrics":evaluate(variants[candidate],ref,alternate)})
        # Type parameters do not alter evidence or the fitted observation set.
        types = []
        for high,low in ((80.,20.),(75.,25.)):
            for tolerance in (10.,5.):
                alternate = {**model,"high":high,"low":low,"tolerance":tolerance}
                ref = fit_reference(con,store.path(aggregate)/f'{candidate}.parquet',alternate,bounds,versions)
                types.append({"high":high,"low":low,"tolerance":tolerance,"metrics":evaluate(variants[candidate],ref,alternate)})
        reference = fit_reference(con,store.path(aggregate)/f'{candidate}.parquet',model,bounds,versions)
        # Freeze before the first access to the independent evaluation split.
        model['version'] = 'model-stage3-v1'
        reference['model_sha256'] = content_hash(model)
        write_json(path/'model.json',model)
        write_json(path/'reference.json',reference)
        write_json(path/'features.json',features)
        write_json(path/'selection.json',{'comparisons':comparisons,'selected':selected,'sensitivity':sensitivity,'type_candidates':types})
        _,evaluation_records = load_sample(con,store,aggregate,'evaluation')
        prepared = prepared_scores(evaluation_records,index,model)
        validation = evaluate(prepared,reference,model)
        normal = next(((key,s) for key,(s,_,_) in prepared.items() if all(v['value'] is not None for v in reference_positions(s,reference,model).values())),None)
        if normal:
            write_json(path/'normal-report.json',build_report(normal[1],reference,model,'independent-comment-sample'))
        groups = {key:{'samples':g['samples'],'full_samples':g['full_samples'], 'N_range':[g['N_min'],g['N_max']],
                      'H_range':[g['H_min']/H_SCALE,g['H_max']/H_SCALE],
                      'dimensions':{k:{'distinct_values':len(set(v)), 'largest_tie_ratio': max(__import__('collections').Counter(v).values())/len(v), 'zero_ratio':v.count(0)/len(v)} for k,v in g['distributions'].items()}}
                  for key,g in reference['groups'].items()}
        return {"version":EXPERIMENT_VERSION,"selected_candidate":candidate,"selected_grouping":selected['grouping'],
                "calibration":selected['metrics'],"independent_evaluation":validation,
                "sql_python_parity":{'checked_users':len(parity),'passed':all(parity)},"support_groups":groups,
                "acceptance":"passed" if passing and validation['passed'] and all(parity) and normal else "failed",
                "protocol_sha256":content_hash((path/'protocol.md').read_text(encoding='utf-8')),
                "migration_bias_resolved":False,"psychometric_validity_verified":False}
    finally:
        con.close()


def replay_reference(store: Store, snapshot: str) -> dict:
    manifest = store.load(snapshot,"reference")
    if manifest['config'].get('version') == 'weight-production-v1':
        from .weight_release import replay_weight_reference
        return replay_weight_reference(store,snapshot)
    store.verify(snapshot)
    verify_pins(store,manifest['config']['inputs'])
    with temporary_workspace(store.root,'reference-replay-') as path:
        (path/'protocol.md').write_text((store.path(snapshot)/'protocol.md').read_text(encoding='utf-8'),encoding='utf-8')
        aggregate = manifest['config']['inputs']['aggregate']['snapshot']
        actual = calculate_experiment(store,aggregate,snapshot,path)
        if actual != read_json(store.path(snapshot)/'metrics.json'):
            raise ValueError('参考实验离线重算不一致')
        for name in ('model.json','reference.json','selection.json','normal-report.json','features.json'):
            if (path/name).exists() != (store.path(snapshot)/name).exists() or ((path/name).exists() and read_json(path/name)!=read_json(store.path(snapshot)/name)):
                raise ValueError('参考产物离线重算不一致：'+name)
    return {'status':'identical','metrics_sha256':content_hash(actual)}
