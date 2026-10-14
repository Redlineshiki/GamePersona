"""Bounded-memory offline aggregation, pinned to audited sources."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .database import connect, literal, rows
from .features import DIMENSIONS, pin_input, verify_pins
from .scoring import E_SCALE, H_SCALE, feature_index, model_config, sql_weight
from .storage import Store, content_hash, read_json, write_json, sha256, temporary_workspace

AGGREGATE_VERSION = "stage3-aggregate-v1"
SPLIT_SALT = "gamepersona-stage3-split-v1:"
CANDIDATES = {"log": model_config(), "cap100": model_config(cap_hours=100),
              "cap200": model_config(cap_hours=200), "linear": model_config(time_function="linear")}


def user_split(user_key: str) -> str:
    bucket = int(hashlib.sha256((SPLIT_SALT + user_key).encode()).hexdigest()[:8], 16) % 100
    return "fit" if bucket < 60 else "calibration" if bucket < 80 else "evaluation"


def aggregate(store: Store, snapshot: str, kaggle: str, features: str) -> dict:
    kg = store.load(kaggle, "kaggle")
    if kg["config"]["hours_unit"] == "unverified":
        raise ValueError("参考聚合需要已核实的小时单位")
    fm = store.load(features, "features")
    if fm["config"]["inputs"]["kaggle"]["snapshot"] != kaggle:
        raise ValueError("特征和离线数据来源不一致")
    pins = {"kaggle": pin_input(store, kaggle, "kaggle", ["normalized/records.parquet", "normalized/clean_records.parquet"]),
            "features": pin_input(store, features, "features", ["features.json", "rules.json"])}
    path, manifest = store.create(snapshot, "aggregate", {"inputs": pins, "version": AGGREGATE_VERSION,
                                "split_salt": SPLIT_SALT, "candidates": CANDIDATES,
                                "minimum_materialized_games": 3, "threads": 1, "memory_limit": "2GiB"})
    metrics = calculate_aggregate(store, pins, path)
    write_json(path / "metrics.json", metrics)
    store.finish(path, manifest, metrics_sha256=content_hash(metrics))
    return metrics


def calculate_aggregate(store: Store, pins: dict, path: Path) -> dict:
    verify_pins(store, pins)
    fs = read_json(store.path(pins["features"]["snapshot"]) / "features.json")
    feature_index(fs)
    fp = store.path(pins["features"]["snapshot"]) / "features.json"
    rp = store.path(pins["kaggle"]["snapshot"]) / "normalized/records.parquet"
    cp = store.path(pins["kaggle"]["snapshot"]) / "normalized/clean_records.parquet"
    con = connect(path / "work.duckdb", threads=1)
    try:
        values = ",".join(f"modes.combined.values.{k}::DOUBLE x_{k}" for k in DIMENSIONS)
        con.execute(f"CREATE OR REPLACE TABLE f AS SELECT app_id,{values} FROM read_json_auto({literal(fp)}) WHERE modes.combined.eligible")
        # Source conflicts are already quarantined; model coverage keeps unsupported games.
        con.execute(f"""CREATE OR REPLACE TABLE observations AS
            SELECT user_key, count(*) observed_games,
              sum(CASE WHEN exclusion_reason IS NULL AND duration_hours>0
                THEN floor(duration_hours*{H_SCALE}+.5)::BIGINT ELSE 0 END)::BIGINT known_ticks,
              count(*) FILTER(WHERE duration_hours IS NULL AND coalesce(exclusion_reason,'')!='conflicting_user_game') unknown_games
            FROM read_parquet({literal(rp)}) WHERE user_key IS NOT NULL GROUP BY user_key""")
        con.execute(f"""CREATE OR REPLACE TABLE eligible AS
            SELECT r.user_key,r.app_id,floor(duration_hours*{H_SCALE}+.5)::BIGINT hours_ticks,f.* EXCLUDE(app_id)
            FROM read_parquet({literal(cp)}) r JOIN f USING(app_id) WHERE duration_hours>0""")
        distribution = rows(con, "SELECT N,count(*) users FROM (SELECT user_key,count(*) N FROM eligible GROUP BY user_key) GROUP BY N ORDER BY N")
        con.execute("CREATE OR REPLACE TABLE eligible_users AS SELECT user_key,count(*) N FROM eligible GROUP BY user_key HAVING count(*)>=3")
        con.execute("CREATE OR REPLACE TABLE selected AS SELECT e.* FROM eligible e JOIN eligible_users USING(user_key) ORDER BY user_key,app_id")
        split = f"CASE WHEN ('0x'||substr(sha256('{SPLIT_SALT}'||user_key),1,8))::UBIGINT%100<60 THEN 'fit' WHEN ('0x'||substr(sha256('{SPLIT_SALT}'||user_key),1,8))::UBIGINT%100<80 THEN 'calibration' ELSE 'evaluation' END"
        counts = {}
        for name, model in CANDIDATES.items():
            print(f"聚合候选 {name}", flush=True)
            weight = sql_weight(f"hours_ticks::DOUBLE/{H_SCALE}", model)
            ct = ",".join(f"floor(({weight})*x_{k}*{E_SCALE}+.5)::BIGINT c_{k}" for k in DIMENSIONS)
            agg = ",".join(f"sum(c_{k})::BIGINT E_{k},max(c_{k})::BIGINT max_{k},count(*) FILTER(WHERE c_{k}>0) pos_{k}" for k in DIMENSIONS)
            con.execute(f"""CREATE OR REPLACE TABLE scored AS
                WITH contributions AS (SELECT user_key,hours_ticks,{ct} FROM selected),
                evidence AS (SELECT user_key,count(*)::BIGINT N,sum(hours_ticks)::BIGINT H_ticks,{agg}
                            FROM contributions GROUP BY user_key)
                SELECT e.*,o.observed_games,o.unknown_games,o.known_ticks,
                  H_ticks::DOUBLE/nullif(known_ticks,0) coverage,
                  unknown_games::DOUBLE/observed_games unknown_ratio,{split} split
                FROM evidence e JOIN observations o USING(user_key) ORDER BY user_key""")
            target = path / f"{name}.parquet"
            con.execute(f"COPY scored TO {literal(target)} (FORMAT PARQUET,COMPRESSION ZSTD)")
            counts[name] = rows(con, "SELECT split,count(*) users, count(*) FILTER(WHERE N>=5 AND coverage>=.8) initial_eligible FROM scored GROUP BY split ORDER BY split")
        totals = rows(con, "SELECT count(*) users,sum(observed_games)::BIGINT records,sum(unknown_games)::BIGINT unknown_games FROM observations")[0]
        metrics = {"version": AGGREGATE_VERSION, "totals": totals, "effective_game_distribution": distribution,
                   "materialized_candidates": counts, "split_salt": SPLIT_SALT,
                   "candidates": CANDIDATES, "minimum_materialized_games": 3}
        write_json(path / "features.json", fs)
        return metrics
    finally:
        con.close()
        # The disposable work database is not a versioned product; only explicitly
        # named files in this freshly created snapshot are removed.
        for name in ("work.duckdb", "work.duckdb.wal"):
            target = path / name
            if target.is_file():
                target.unlink()


def replay_aggregate(store: Store, snapshot: str) -> dict:
    manifest = store.load(snapshot, "aggregate")
    store.verify(snapshot)
    verify_pins(store, manifest["config"]["inputs"])
    with temporary_workspace(store.root,"replay-aggregate-") as path:
        actual = calculate_aggregate(store, manifest["config"]["inputs"], path)
        if actual != read_json(store.path(snapshot) / "metrics.json"):
            raise ValueError("聚合指标重算不一致")
        for name in CANDIDATES:
            # Parquet hash also checks canonical row order and exact integer evidence.
            if sha256(path / f"{name}.parquet") != sha256(store.path(snapshot) / f"{name}.parquet"):
                raise ValueError("用户聚合重算不一致")
    return {"status": "identical", "metrics_sha256": content_hash(actual)}
