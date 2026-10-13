from __future__ import annotations

from collections import Counter
from pathlib import Path

from .database import connect, rows
from .storage import Store, content_hash, read_json, sha256, write_json

# Conflicting cumulative observations cannot be added even for coverage denominators.
UNIQUE_DURATION = "exclusion_reason IS DISTINCT FROM 'conflicting_user_game' AND exclusion_reason IS DISTINCT FROM 'conflicting_review_id'"


def coverage(numerator: int | float, denominator: int | float, scope: str) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if denominator else None, "scope": scope}


def distribution(con, table: str, column: str) -> dict:
    return rows(con, f"SELECT count({column}) observations,min({column}) minimum,"
                f"quantile_cont({column},0.25) p25,quantile_cont({column},0.5) median,"
                f"quantile_cont({column},0.75) p75,quantile_cont({column},0.95) p95,"
                f"max({column}) maximum FROM {table}")[0]


def attach_tags(con, records: list[dict]) -> None:
    con.execute("CREATE TEMP TABLE spy_tags(app_id BIGINT,status VARCHAR,tag_count BIGINT,total_votes BIGINT)")
    if records:
        con.executemany("INSERT INTO spy_tags VALUES (?,?,?,?)", [
            (r["app_id"], r["status"], len(r["tags"]), sum(t["votes"] for t in r["tags"])) for r in records])


def tag_metrics(app_ids: set[int], tags: list[dict], scope: str) -> dict:
    relevant = [r for r in tags if r["app_id"] in app_ids]
    attempted = [r for r in relevant if r["status"] != "not_collected"]
    responses = [r for r in relevant if r["status"] in {"available", "no_tags", "no_positive_votes", "invalid_tag_format"}]
    available = [r for r in relevant if r["status"] == "available"]
    states = Counter(r["status"] for r in relevant)
    states["not_selected"] = len(app_ids - {r["app_id"] for r in relevant})
    return {"collection_coverage": coverage(len(attempted),len(app_ids),scope),
            "matched_response_coverage": coverage(len(responses),len(app_ids),scope),
            "tag_coverage": coverage(len(available),len(app_ids),scope),
            "tag_availability_after_response": coverage(len(available),len(responses),scope+"；成功返回对应 AppID 的响应"),
            "states": dict(sorted(states.items()))}


def calculate(store: Store, kaggle: str, steamspy: str | None, steam: str | None,
              selection: str | None, sources: str | None) -> dict:
    kg = store.load(kaggle, "kaggle")
    spy = store.load(steamspy, "steamspy") if steamspy else None
    sel = store.load(selection, "selection") if selection else None
    st = store.load(steam, "steam") if steam else None
    source = store.load(sources, "sources") if sources else None
    if sel and sel["config"]["kaggle_snapshot"] != kaggle:
        raise ValueError("候选快照与 Kaggle 快照不兼容")
    if spy:
        if not sel or spy["config"]["selection_snapshot"] != selection:
            raise ValueError("标签审计必须提供其对应的候选快照")
    if sel and sel["config"]["steam_snapshot"] != steam:
        raise ValueError("账号快照必须与候选选样时一致")
    tags = read_json(store.path(steamspy) / "tags.json") if steamspy else []
    con = connect(store.path(kaggle) / "audit.duckdb", read_only=True)
    try:
        attach_tags(con, tags)
        app_ids = {r[0] for r in con.execute("SELECT DISTINCT app_id FROM records WHERE app_id>0").fetchall()}
        matched = con.execute("SELECT count(DISTINCT app_id) FROM records WHERE app_id>0 AND game_matched").fetchone()[0]
        meta = con.execute("SELECT count(DISTINCT r.app_id) FROM records r JOIN metadata m ON r.app_id=m.app_id WHERE m.tag_state='available'").fetchone()[0]
        positive = con.execute("SELECT count(*) FROM records WHERE duration_state='positive'").fetchone()[0]
        clean_positive = con.execute("SELECT count(*) FROM clean_records WHERE duration_state='positive'").fetchone()[0]
        maximum = con.execute("SELECT max(source_duration_value) FROM records WHERE duration_state IN ('positive','zero')").fetchone()[0]
        max_count = con.execute("SELECT count(*) FROM records WHERE source_duration_value=? AND duration_state IN ('positive','zero')", [maximum]).fetchone()[0] if maximum is not None else 0
        scope = "离线评论输入去重且有效格式的 AppID；包含未匹配项"
        offline = {
            "quality": kg["quality"],
            "game_match_rate": coverage(matched,len(app_ids),scope),
            "kaggle_metadata_tag_coverage": coverage(meta,len(app_ids),scope),
            "steamspy": tag_metrics(app_ids,tags,scope),
            "source_positive_duration_records": positive,
            "usable_positive_duration_records": clean_positive,
            "source_duration_maximum": maximum,
            "records_at_maximum": max_count,
            "maximum_concentration": coverage(max_count, positive + con.execute("SELECT count(*) FROM records WHERE duration_state='zero'").fetchone()[0], "已知非负来源时长记录；不是完整账户时长"),
            "duration_top_values": rows(con, "SELECT source_duration_value AS duration,count(*) records FROM records WHERE duration_state IN ('positive','zero') GROUP BY 1 ORDER BY records DESC,duration LIMIT 20"),
            "duration_censoring_conclusion": "仅记录上限集中现象；是否被截断须结合来源说明核验",
            "user_observable_games": distribution(con,"user_summary","observable_games"),
            "user_input_observable_games": distribution(con,"user_observations","observed_games"),
            "user_missing_duration_ratio": distribution(con,"user_observations","missing_duration_ratio"),
            "user_filter_loss_ratio": distribution(con,"user_observations","filter_loss_ratio"),
            "users_before_cleaning": con.execute("SELECT count(*) FROM user_observations").fetchone()[0],
            "users_after_cleaning": con.execute("SELECT count(*) FROM user_summary").fetchone()[0],
            "user_positive_games": distribution(con,"user_summary","positive_games"),
            "user_known_hours": distribution(con,"user_summary","total_known_hours"),
            "review_date_range": rows(con,"SELECT min(review_date)::VARCHAR earliest,max(review_date)::VARCHAR latest,count(*) FILTER (WHERE review_date IS NULL) missing_dates FROM records")[0],
            "product_kinds": rows(con,"SELECT coalesce(m.product_kind,g.product_kind) product_kind,count(*) games FROM games g LEFT JOIN metadata m ON g.app_id=m.app_id GROUP BY 1 ORDER BY 1"),
            "metadata_tag_states": rows(con,"SELECT tag_state state,count(*) games FROM metadata GROUP BY 1 ORDER BY 1"),
            "metadata_tag_count": rows(con,"SELECT len(tags) tag_count,count(*) games FROM metadata GROUP BY 1 ORDER BY 1"),
            "spy_tag_counts": distribution(con,"spy_tags","tag_count"),
            "spy_vote_totals": distribution(con,"spy_tags","total_votes"),
            "feature_availability": {"value": None,"reason": "待第二阶段冻结八维规则"},
            "scorable_duration_coverage": {"value": None,"reason": "待第二阶段；有标签不等于可计分"},
        }
        if kg["config"]["hours_unit"] != "unverified":
            total_hours = con.execute(f"SELECT coalesce(sum(duration_hours),0) FROM records WHERE duration_state='positive' AND {UNIQUE_DURATION}").fetchone()[0]
            matched_hours = con.execute(f"SELECT coalesce(sum(duration_hours),0) FROM records WHERE duration_state='positive' AND game_matched AND {UNIQUE_DURATION}").fetchone()[0]
            tagged_hours = con.execute(f"SELECT coalesce(sum(r.duration_hours),0) FROM records r JOIN spy_tags s ON r.app_id=s.app_id WHERE r.duration_state='positive' AND s.status='available' AND {UNIQUE_DURATION}").fetchone()[0]
            offline["duration_coverage_conflict_policy"] = "冲突累计时长不进入加权覆盖分子或分母，数量在隔离统计中另报"
            offline["metadata_duration_coverage"] = coverage(matched_hours,total_hours,"离线已核实单位的已知正时长；仅元数据匹配")
            offline["tag_duration_coverage"] = coverage(tagged_hours,total_hours,"离线已核实单位的已知正时长；仅标签存在")
        else:
            offline["metadata_duration_coverage"] = {"ratio": None,"reason": "来源时长单位待核实"}
            offline["tag_duration_coverage"] = {"ratio": None,"reason": "来源时长单位待核实"}
        known_games = {r[0] for r in con.execute("SELECT app_id FROM games").fetchall()}
    finally:
        con.close()
    online = {"status": "not_measured", "limitation": "尚未读取授权账号，离线覆盖不能代替线上覆盖"}
    if st:
        records = read_json(store.path(steam) / "records.json")
        account_ids = {r["app_id"] for r in records if r["app_id"] is not None}
        online = {"status": st["read_status"], "observed_records": st["observed_records"],
                  "normalized_records": len(records), "unique_app_ids": len(account_ids),
                  "duration_states": dict(sorted(Counter(r["duration_state"] for r in records).items())),
                  "excluded_records": sum(r["exclusion_reason"] is not None for r in records),
                  "exclusion_reasons": dict(sorted(Counter(r["exclusion_reason"] for r in records if r["exclusion_reason"]).items())),
                  "game_match_rate": coverage(len(account_ids & known_games),len(account_ids),"单一授权账号去重 AppID"),
                  "steamspy": tag_metrics(account_ids,tags,"单一授权账号去重 AppID"),
                  "limitation": "单账号实测不是 Steam 玩家总体覆盖；未通过 OpenID 身份验证"}
        positive_hours = sum(r["duration_hours"] for r in records if r["duration_state"]=="positive" and r["duration_hours"] is not None)
        available_ids = {r["app_id"] for r in tags if r["status"]=="available"}
        tagged_hours = sum(r["duration_hours"] for r in records if r["app_id"] in available_ids and r["duration_state"]=="positive" and r["duration_hours"] is not None)
        online["tag_duration_coverage"] = coverage(tagged_hours,positive_hours,"单一授权账号已知正时长；仅标签存在")
        online["scorable_duration_coverage"] = {"ratio":None,"reason":"待第二阶段特征规则"}
    blockers = []
    if clean_positive == 0 or matched == 0:
        blockers.append("离线样本尚无可关联且已知正时长的可用记录")
    if kg["config"]["hours_unit"] == "unverified":
        blockers.append("Kaggle 时长单位尚未核实")
    if kg["config"]["duration_time_semantics"] == "unverified":
        blockers.append("Kaggle 累计时长对应采集时还是评论时尚未核实")
    if kg["config"]["dataset_version"] == "unverified":
        blockers.append("本地数据集来源版本尚未核实")
    if not st or st["read_status"] != "success":
        blockers.append("尚未成功读取至少一个包含游戏记录的授权账号")
    elif not any(r["app_id"] is not None and r["exclusion_reason"] is None for r in records):
        blockers.append("授权账号未取得具有已知时长的有效 AppID 记录")
    if not sel or sel["base_games"] < 3000:
        blockers.append("尚未完成 3000 款基础候选选样")
    if not spy or spy.get("uncollected_games",1):
        blockers.append("约定候选的 SteamSpy 采集尝试尚未完成")
    elif not any(r["status"] == "available" for r in tags):
        blockers.append("SteamSpy 尚未取得任何可用标签；需排查来源或收窄支持范围")
    if not source:
        blockers.append("尚未保存来源与许可核验快照")
    else:
        blockers.extend(source["findings"]["unresolved"])
        if source["findings"]["kaggle"]["status"] == "unverified":
            blockers.append("Kaggle 发布者许可声明尚未核实")
        for name, evidence in source["evidence"].items():
            if evidence["status"] != "ok":
                blockers.append(f"来源证据获取失败：{name}")
    result = {"schema_version":"stage1-audit-v1", "snapshots": {"kaggle":kaggle,"steamspy":steamspy,
              "steam":steam,"selection":selection,"sources":sources},
              "offline":offline,"online":online,
              "selection": {k: sel[k] for k in ("base_games","account_games","total_games","available_population")} if sel else None,
              "stage_acceptance": {"status":"blocked" if blockers else "passed","blockers":blockers},
              "second_stage_quality_targets": ["按维度和游戏类别登记特征未知率及覆盖目标", "登记人工一致性及独立核验误差目标", "校准集与独立核验集分离", "未知特征不填零；目标数值在第二阶段实验前冻结"]}
    result["metrics_sha256"] = content_hash(result)
    return result


def render(metrics: dict) -> str:
    offline, online = metrics["offline"], metrics["online"]
    lines = ["# GamePersona 第一阶段数据审计", "", "## 验收结论", "",
             "阶段状态：" + metrics["stage_acceptance"]["status"], "",
             "本报告不计算八维分数；工具测试与真实阶段验收分别记录。", ""]
    for blocker in metrics["stage_acceptance"]["blockers"]:
        lines.append("- " + blocker)
    lines += ["", "## 离线全量统计", "", "```json", __import__('json').dumps(offline["quality"], ensure_ascii=False,indent=2), "```", "",
              "| 指标 | 分子 | 分母 | 比率 |", "|---|---:|---:|---:|"]
    for name, value in [("游戏匹配率",offline["game_match_rate"]),
                        ("Kaggle 元数据标签覆盖",offline["kaggle_metadata_tag_coverage"]),
                        ("SteamSpy 采集覆盖",offline["steamspy"]["collection_coverage"]),
                        ("SteamSpy 标签覆盖",offline["steamspy"]["tag_coverage"]),
                        ("返回对应条目后的标签可用率",offline["steamspy"]["tag_availability_after_response"])]:
        ratio = f"{value['ratio']:.2%}" if value["ratio"] is not None else "不可计算"
        lines.append(f"| {name} | {value['numerator']} | {value['denominator']} | {ratio} |")
    lines += ["", "统计分母为评论输入中格式有效的去重 AppID，包括未匹配项。未选样、未采集、失败和无标签分开统计。",
              "", "## 时长与用户记录", "",
              f"来源时长最大值：{offline['source_duration_maximum']}；该值记录数：{offline['records_at_maximum']}。",
              "上限集中不证明真实游玩上限；时间语义未核实前不能用于历史预测。",
              "", "```json", __import__('json').dumps({k:offline[k] for k in ['users_before_cleaning','users_after_cleaning','user_input_observable_games','user_observable_games','user_missing_duration_ratio','user_filter_loss_ratio','user_positive_games','user_known_hours','review_date_range','duration_top_values','metadata_tag_states','metadata_tag_count','spy_tag_counts','spy_vote_totals','product_kinds','metadata_duration_coverage','tag_duration_coverage','steamspy']}, ensure_ascii=False,indent=2), "```",
              "", "## 线上实测", "", "```json", __import__('json').dumps(online, ensure_ascii=False,indent=2), "```",
              "", "## 特征与下一阶段", "", "八维特征可用率与可计分时长覆盖率：待第二阶段。标签存在率不能代替特征完整性。", ""]
    lines.extend("- "+target for target in metrics["second_stage_quality_targets"])
    lines += ["", "## 追溯", "", f"指标内容哈希：`{metrics['metrics_sha256']}`", "",
              "原始证据、许可记录、字段映射和各来源快照在对应 manifest.json 中追溯；本报告不展示账号标识或个人游戏明细。", ""]
    return "\n".join(lines)


def audit(store: Store, report: str, *, kaggle: str, steamspy: str | None = None,
          steam: str | None = None, selection: str | None = None, sources: str | None = None) -> dict:
    metrics = calculate(store,kaggle,steamspy,steam,selection,sources)
    path, manifest = store.create(report,"report", metrics["snapshots"])
    write_json(path / "metrics.json",metrics)
    (path / "report.md").write_text(render(metrics),encoding="utf-8")
    store.finish(path,manifest,stage_status=metrics["stage_acceptance"]["status"],metrics_sha256=metrics["metrics_sha256"])
    return metrics


def replay(store: Store, report: str) -> dict:
    manifest = store.load(report,"report")
    config = manifest["config"]
    store.verify(report)
    for snapshot in config.values():
        if snapshot:
            store.verify(snapshot)
    kg = store.load(config["kaggle"],"kaggle")
    for info in kg["files"]:
        if sha256(store.path(config["kaggle"]) / "raw" / info["name"]) != info["sha256"]:
            raise ValueError("原始 Kaggle 快照已发生变化")
    for info in kg["normalized_files"]:
        if sha256(store.path(config["kaggle"]) / "normalized" / info["name"]) != info["sha256"]:
            raise ValueError("规范化快照已发生变化")
    metrics = calculate(store,**{k:config[k] for k in ("kaggle","steamspy","steam","selection","sources")})
    expected = read_json(store.path(report) / "metrics.json")
    if metrics != expected:
        raise ValueError("离线重算与固定报告不一致；请检查快照是否被修改")
    return {"status":"identical","metrics_sha256":metrics["metrics_sha256"]}
