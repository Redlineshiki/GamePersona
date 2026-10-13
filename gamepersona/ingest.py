from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath

from .database import connect, export, literal, rows
from .storage import Store, sha256, write_json

FILES = ("games.csv", "games_metadata.json", "users.csv", "recommendations.csv")
REQUIRED = {"games": {"app_id", "title"}, "users": {"user_id"},
            "recommendations": {"app_id", "user_id", "review_id", "hours", "date", "is_recommended"}}
FIELD_MAPPING = {
    "app_id": {"target": "app_id", "meaning": "Steam AppID；不是游戏名称"},
    "user_id": {"target": "user_key", "meaning": "kaggle:<原始匿名标识>；不与 SteamID 关联"},
    "hours": {"target": "hours_raw / duration_hours", "meaning": "来源游玩时长；转换需要单位证据"},
    "date": {"target": "review_date", "meaning": "评论日期；不作为游玩日期或采集顺序"},
    "is_recommended": {"target": "is_recommended", "meaning": "明确推荐标记；仅保留作验证"},
    "review_id": {"target": "review_id", "meaning": "来源评论标识"},
}


def validate_source(source: Path) -> dict[str, Path | zipfile.ZipInfo]:
    if source.name.lower().endswith((".crdownload", ".part", ".tmp")):
        raise ValueError("下载尚未完成；等待现有下载结束，不会重复下载")
    if source.is_dir():
        entries = {name: source / name for name in FILES}
        if not all(p.is_file() for p in entries.values()):
            raise ValueError("输入目录必须包含四个完整数据文件：" + ", ".join(FILES))
        return entries
    if not zipfile.is_zipfile(source):
        raise ValueError("输入不是完整 ZIP 或四文件目录")
    with zipfile.ZipFile(source) as z:
        found = {}
        for entry in z.infolist():
            name = PurePosixPath(entry.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts or ":" in entry.filename:
                raise ValueError("压缩包含不安全的路径")
            if not entry.is_dir() and name.name in FILES:
                if name.name in found:
                    raise ValueError("压缩包含重名数据文件")
                found[name.name] = entry
        if set(found) != set(FILES):
            raise ValueError("压缩包缺少必需数据文件")
        bad = z.testzip()
        if bad:
            raise ValueError(f"压缩包 CRC 校验失败：{bad}")
        return found


def prepare_metadata(raw: Path, target: Path, rejects: Path) -> dict:
    counts = {"input_lines": 0, "parsed_rows": 0, "rejected_lines": 0}
    with raw.open(encoding="utf-8-sig") as source, target.open("w", encoding="utf-8") as out, \
            rejects.open("w", encoding="utf-8") as rejected:
        for line_no, line in enumerate(source, 1):
            if not line.strip():
                continue
            counts["input_lines"] += 1
            try:
                value = json.loads(line)
                if not isinstance(value, dict) or "app_id" not in value:
                    raise ValueError("非对象或缺少 app_id")
                tags = value.get("tags")
                if tags is None:
                    state, clean = "missing", []
                elif not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                    state, clean = "invalid_format", []
                else:
                    clean = sorted({tag.strip() for tag in tags if tag.strip()})
                    state = "available" if clean else "empty"
                product_type = value.get("type", value.get("product_type"))
                record = {"app_id_raw": str(value["app_id"]), "tags_json": json.dumps(tags, ensure_ascii=False),
                          "tags": clean, "tag_state": state,
                          "product_kind": product_type if product_type in {"game", "dlc"} else "unknown"}
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                counts["parsed_rows"] += 1
            except (ValueError, TypeError) as e:
                rejected.write(json.dumps({"line": line_no, "reason": str(e), "raw": line.rstrip()},
                                          ensure_ascii=False) + "\n")
                counts["rejected_lines"] += 1
    return counts


def import_kaggle(store: Store, snapshot: str, source: Path, *, hours_unit: str = "unverified",
                  hours_evidence: str = "", dataset_version: str = "unverified",
                  duration_time_semantics: str = "unverified", time_evidence: str = "",
                  memory_limit: str = "2GiB", threads: int = 4) -> dict:
    if hours_unit not in {"unverified", "hours", "minutes"}:
        raise ValueError("时长单位仅支持 unverified、hours、minutes")
    if hours_unit != "unverified" and not hours_evidence.strip():
        raise ValueError("确认时长单位必须提供 --hours-evidence，不能仅凭字段名猜测")
    if duration_time_semantics not in {"unverified", "at_collection", "at_review"}:
        raise ValueError("不支持的时长时间语义")
    if duration_time_semantics != "unverified" and not time_evidence.strip():
        raise ValueError("确认时长时间语义必须提供 --time-evidence")
    started = time.monotonic()
    source = source.resolve()
    entries = validate_source(source)
    config = {"cleaning_version": "stage1-v1", "hours_unit": hours_unit,
              "hours_unit_evidence": hours_evidence, "duration_time_semantics": duration_time_semantics,
              "duration_time_evidence": time_evidence,
              "review_time_semantics": "review_date_not_play_date",
              "dataset_version": dataset_version, "memory_limit": memory_limit, "threads": threads,
              "conflict_policy": "quarantine_without_collection_order"}
    path, manifest = store.create(snapshot, "kaggle", config)
    raw = path / "raw"
    raw.mkdir()
    normalized = path / "normalized"
    normalized.mkdir()
    try:
        if source.is_dir():
            for name in FILES:
                shutil.copyfile(entries[name], raw / name)
        else:
            with zipfile.ZipFile(source) as z:
                for name in FILES:
                    with z.open(entries[name]) as src, (raw / name).open("wb") as dest:
                        shutil.copyfileobj(src, dest, 1024 * 1024)
        file_info = [{"name": name, "bytes": (raw / name).stat().st_size,
                      "sha256": sha256(raw / name)} for name in FILES]
        metadata_counts = prepare_metadata(raw / "games_metadata.json", path / "metadata.ndjson",
                                            normalized / "metadata_rejects.jsonl")
        con = connect(path / "audit.duckdb", memory_limit, threads)
        try:
            con.execute("CREATE MACRO to_appid(v) AS CASE WHEN regexp_full_match(trim(v),'[0-9]+') THEN try_cast(v AS BIGINT) ELSE NULL END")
            csv_counts = {}
            for table in REQUIRED:
                con.execute(f"CREATE TABLE raw_{table} AS SELECT * FROM read_csv("
                            f"{literal(raw / (table + '.csv'))}, header=true, all_varchar=true, "
                            f"ignore_errors=true, store_rejects=true, rejects_table='{table}_rejects', "
                            f"rejects_scan='{table}_reject_scans', parallel=false)")
                columns = {r[0] for r in con.execute(f"DESCRIBE raw_{table}").fetchall()}
                missing = REQUIRED[table] - columns
                if missing:
                    raise ValueError(f"{table}.csv 缺少字段：{', '.join(sorted(missing))}")
                rejected = con.execute(f"SELECT count(DISTINCT file_id || ':' || line) FROM {table}_rejects").fetchone()[0]
                parsed = con.execute(f"SELECT count(*) FROM raw_{table}").fetchone()[0]
                csv_counts[table] = {"parsed_rows": parsed, "rejected_rows": rejected}
                export(con, f"{table}_rejects", normalized / f"{table}_parse_rejects.parquet")
            if metadata_counts["parsed_rows"]:
                con.execute(f"CREATE TABLE raw_metadata AS SELECT * FROM read_json("
                            f"{literal(path / 'metadata.ndjson')}, format='newline_delimited', "
                            "columns={app_id_raw:'VARCHAR',tags_json:'VARCHAR',tags:'VARCHAR[]',"
                            "tag_state:'VARCHAR',product_kind:'VARCHAR'})")
            else:
                con.execute("CREATE TABLE raw_metadata(app_id_raw VARCHAR,tags_json VARCHAR,tags VARCHAR[],"
                            "tag_state VARCHAR,product_kind VARCHAR)")
            con.execute("""CREATE TABLE games_distinct AS SELECT DISTINCT * FROM raw_games;
                CREATE TABLE game_keys AS SELECT to_appid(app_id) app_id, count(*) variants
                FROM games_distinct GROUP BY 1;
                CREATE TABLE games AS SELECT to_appid(g.app_id) app_id, g.title,
                  'unknown'::VARCHAR product_kind FROM games_distinct g JOIN game_keys k
                  ON to_appid(g.app_id)=k.app_id
                  WHERE k.app_id>0 AND k.variants=1;
                CREATE TABLE users AS SELECT DISTINCT 'kaggle:' || user_id user_key
                  FROM raw_users WHERE user_id IS NOT NULL AND trim(user_id)<>'';
                CREATE TABLE metadata_distinct AS SELECT DISTINCT * FROM raw_metadata;
                CREATE TABLE metadata_keys AS SELECT to_appid(app_id_raw) app_id, count(*) variants
                  FROM metadata_distinct GROUP BY 1;
                CREATE TABLE metadata AS SELECT to_appid(m.app_id_raw) app_id,
                  m.tags_json, m.tags, m.tag_state, m.product_kind
                  FROM metadata_distinct m JOIN metadata_keys k ON to_appid(m.app_id_raw)=k.app_id
                  WHERE k.app_id>0 AND k.variants=1;
                CREATE TABLE recommendations_distinct AS SELECT DISTINCT * FROM raw_recommendations;
                CREATE TABLE user_game_keys AS SELECT user_id, app_id, count(*) variants
                  FROM recommendations_distinct GROUP BY 1,2;
                CREATE TABLE review_keys AS SELECT review_id, count(*) variants
                  FROM recommendations_distinct WHERE review_id IS NOT NULL GROUP BY 1;
                """)
            multiplier = "1.0" if hours_unit == "hours" else "1.0 / 60.0"
            duration = f"hours_value * ({multiplier})" if hours_unit != "unverified" else "NULL::DOUBLE"
            con.execute(f"""CREATE TABLE records AS
              WITH typed AS (
                SELECT r.*, to_appid(r.app_id) app_id_value,
                  try_cast(r.hours AS DOUBLE) hours_value, try_cast(r.date AS DATE) review_date_value,
                  try_cast(r.is_recommended AS BOOLEAN) recommendation_value,
                  p.variants pair_variants, coalesce(v.variants,0) review_variants
                FROM recommendations_distinct r
                JOIN user_game_keys p ON r.user_id IS NOT DISTINCT FROM p.user_id
                  AND r.app_id IS NOT DISTINCT FROM p.app_id
                LEFT JOIN review_keys v ON r.review_id=v.review_id
              ), classified AS (
                SELECT t.*, g.app_id IS NOT NULL game_matched, u.user_key IS NOT NULL user_matched,
                  CASE WHEN hours IS NULL OR trim(hours)='' THEN 'unknown'
                    WHEN hours_value IS NULL THEN 'invalid_type'
                    WHEN NOT isfinite(hours_value) THEN 'non_finite'
                    WHEN hours_value<0 THEN 'negative'
                    WHEN hours_value=0 THEN 'zero' ELSE 'positive' END duration_state,
                  CASE WHEN app_id_value IS NULL OR app_id_value<=0 THEN 'invalid_app_id'
                    WHEN user_id IS NULL OR trim(user_id)='' THEN 'missing_user_id'
                    WHEN pair_variants>1 THEN 'conflicting_user_game'
                    WHEN review_id IS NULL OR trim(review_id)='' THEN 'missing_review_id'
                    WHEN review_variants>1 THEN 'conflicting_review_id'
                    WHEN g.app_id IS NULL THEN 'unmatched_game'
                    WHEN u.user_key IS NULL THEN 'unmatched_user'
                    WHEN date IS NOT NULL AND review_date_value IS NULL THEN 'invalid_review_date'
                    WHEN recommendation_value IS NULL THEN 'invalid_recommendation'
                    ELSE NULL END exclusion_reason
                FROM typed t LEFT JOIN games g ON t.app_id_value=g.app_id
                  LEFT JOIN users u ON 'kaggle:' || t.user_id=u.user_key
              ) SELECT 'kaggle:' || user_id user_key, app_id_value app_id, app_id app_id_raw,
                  review_id, hours hours_raw, hours_value source_duration_value,
                  CASE WHEN duration_state IN ('positive','zero') THEN {duration} ELSE NULL END duration_hours,
                  duration_state, date review_date_raw, review_date_value review_date,
                  recommendation_value is_recommended, game_matched, user_matched,
                  coalesce(exclusion_reason, CASE WHEN duration_state NOT IN ('positive','zero')
                    THEN 'duration_' || duration_state ELSE NULL END) exclusion_reason
              FROM classified;
              CREATE TABLE clean_records AS SELECT * FROM records WHERE exclusion_reason IS NULL;
              CREATE TABLE quarantine AS SELECT * FROM records WHERE exclusion_reason IS NOT NULL;
              CREATE TABLE user_summary AS SELECT user_key, count(*) observable_games,
                count(*) FILTER (WHERE duration_state='positive') positive_games,
                count(*) FILTER (WHERE duration_state='zero') zero_games,
                sum(duration_hours) total_known_hours
                FROM clean_records GROUP BY user_key;
              CREATE TABLE user_observations AS SELECT user_key, count(*) observed_records,
                count(DISTINCT app_id) FILTER (WHERE app_id>0) observed_games,
                count(*) FILTER (WHERE duration_state='unknown')::DOUBLE / count(*) missing_duration_ratio,
                count(*) FILTER (WHERE exclusion_reason IS NOT NULL)::DOUBLE / count(*) filter_loss_ratio
                FROM records WHERE user_key IS NOT NULL GROUP BY user_key;
            """)
            for table in ("games", "users", "metadata", "records", "clean_records", "quarantine", "user_summary", "user_observations"):
                export(con, table, normalized / f"{table}.parquet")
            quality = {
                "csv": csv_counts, "metadata": metadata_counts,
                "exact_duplicate_rows_removed": {
                    t: con.execute(f"SELECT (SELECT count(*) FROM raw_{t})-"
                                   f"(SELECT count(*) FROM {t}_distinct)").fetchone()[0]
                    for t in ("games", "metadata", "recommendations")},
                "duplicate_user_ids": con.execute("SELECT count(*) FROM (SELECT user_id FROM raw_users GROUP BY 1 HAVING count(*)>1)").fetchone()[0],
                "conflicting_game_ids": con.execute("SELECT count(*) FROM game_keys WHERE variants>1").fetchone()[0],
                "invalid_game_ids": con.execute("SELECT count(*) FROM raw_games WHERE to_appid(app_id) IS NULL OR to_appid(app_id)<=0").fetchone()[0],
                "conflicting_metadata_ids": con.execute("SELECT count(*) FROM metadata_keys WHERE variants>1").fetchone()[0],
                "invalid_metadata_ids": con.execute("SELECT count(*) FROM raw_metadata WHERE to_appid(app_id_raw) IS NULL OR to_appid(app_id_raw)<=0").fetchone()[0],
                "conflicting_user_game_pairs": con.execute("SELECT count(*) FROM user_game_keys WHERE variants>1").fetchone()[0],
                "conflicting_review_ids": con.execute("SELECT count(*) FROM review_keys WHERE variants>1").fetchone()[0],
                "input_app_ids": con.execute("SELECT count(DISTINCT app_id) FROM records WHERE app_id>0").fetchone()[0],
                "normalized_records": con.execute("SELECT count(*) FROM records").fetchone()[0],
                "clean_records": con.execute("SELECT count(*) FROM clean_records").fetchone()[0],
                "quarantined_records": con.execute("SELECT count(*) FROM quarantine").fetchone()[0],
                "exclusion_reasons": rows(con, "SELECT exclusion_reason reason,count(*) records FROM quarantine GROUP BY 1 ORDER BY 1"),
                "duration_states": rows(con, "SELECT duration_state state,count(*) records FROM records GROUP BY 1 ORDER BY 1"),
            }
            write_json(path / "quality.json", quality)
        finally:
            con.close()
        store.finish(path, manifest, input_source=str(source), files=file_info, field_mapping=FIELD_MAPPING,
                     elapsed_seconds=round(time.monotonic() - started, 3), quality=quality,
                     normalized_files=[{"name": p.name, "sha256": sha256(p)} for p in sorted(normalized.glob("*.parquet"))])
        return manifest
    except Exception:
        manifest["state"] = "failed"
        write_json(path / "manifest.json", manifest)
        raise
