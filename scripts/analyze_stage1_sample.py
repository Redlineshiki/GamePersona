"""Summarize a completed sample without changing the fixed full-input audit."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

# Allow running the saved script from the project root without installing the project.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gamepersona.audit import tag_metrics
from gamepersona.database import connect
from gamepersona.storage import Store, read_json, write_json


def summarize(candidates: list[dict], tags: list[dict], metadata_tags: dict[int, list[str]] | None = None) -> dict:
    groups = {
        "all_candidates": candidates,
        "base_sample": [c for c in candidates if set(c["reasons"]) & {"top_review_users", "stratified"}],
        "popular": [c for c in candidates if "top_review_users" in c["reasons"]],
        "stratified": [c for c in candidates if "stratified" in c["reasons"]],
        "authorized_account": [c for c in candidates if "authorized_account" in c["reasons"]],
        "account_additions": [c for c in candidates if c["reasons"] == ["authorized_account"]],
    }
    by_id = {t["app_id"]: t for t in tags}
    results = {}
    for name, subset in groups.items():
        ids = {c["app_id"] for c in subset}
        result = tag_metrics(ids, tags, name + "; selected distinct AppIDs only")
        gaps = [c for c in subset if by_id[c["app_id"]]["status"] != "available"]
        result["unavailable_games"] = len(gaps)
        # Account additions have placeholder candidate tags; inspect actual metadata.
        with_metadata = sum(bool(metadata_tags.get(c["app_id"], [])) if metadata_tags is not None
                            else bool(c["tags"]) for c in gaps)
        result["gaps_with_kaggle_tags"] = with_metadata
        result["gaps_without_kaggle_tags"] = len(gaps) - with_metadata
        result["gap_primary_tags"] = dict(sorted(Counter(c["primary_tag"] for c in gaps).items()))
        results[name] = result
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="第一阶段选样覆盖与标签缺口补充分析")
    parser.add_argument("--root", type=Path, default=Path("artifacts"))
    parser.add_argument("--selection", required=True)
    parser.add_argument("--steamspy", required=True)
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    store = Store(args.root)
    selection = store.load(args.selection, "selection")
    spy = store.load(args.steamspy, "steamspy")
    if spy["config"]["selection_snapshot"] != args.selection:
        raise ValueError("标签必须对应同一候选快照")
    store.verify(args.selection)
    store.verify(args.steamspy)
    candidates = read_json(store.path(args.selection) / "candidates.json")
    tags = read_json(store.path(args.steamspy) / "tags.json")
    if {c["app_id"] for c in candidates} != {t["app_id"] for t in tags}:
        raise ValueError("标签与候选 AppID 集合不一致")
    if any(t["status"] == "not_collected" for t in tags):
        raise ValueError("补充分析要求候选采集已完成")
    kaggle = selection["config"]["kaggle_snapshot"]
    store.load(kaggle, "kaggle")
    con = connect(store.path(kaggle) / "audit.duckdb", read_only=True)
    try:
        metadata_tags = dict(con.execute("SELECT app_id,tags FROM metadata WHERE tag_state='available'").fetchall())
    finally:
        con.close()
    metrics = summarize(candidates, tags, metadata_tags)
    path, manifest = store.create(args.snapshot, "sample_analysis", {
        "selection_snapshot": args.selection, "steamspy_snapshot": args.steamspy,
        "kaggle_snapshot": selection["config"]["kaggle_snapshot"],
        "scope": "selected sample; groups overlap; not population estimates",
    })
    write_json(path / "metrics.json", metrics)
    (path / "analysis.py").write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    labels = {"all_candidates": "全部候选", "base_sample": "基础样本", "popular": "热门样本",
              "stratified": "分层样本", "authorized_account": "授权账号", "account_additions": "账号新增"}
    lines = ["# 第一阶段选样覆盖与缺口分析", "",
             "各组分母为组内有效去重 AppID；账号与基础样本有交集，不能将各组相加。热门及分层样本不是全体游戏的随机样本，不外推总体覆盖率。", "",
             "| 集合 | 游戏数 | 有标签 | 标签覆盖 | 缺口有 Kaggle 标签 | 缺口无 Kaggle 标签 |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, result in metrics.items():
        rate = result["tag_coverage"]
        ratio = f"{rate['ratio']:.2%}" if rate["ratio"] is not None else "不可计算"
        lines.append(f"| {labels[name]} | {rate['denominator']} | {rate['numerator']} | {ratio} | "
                     f"{result['gaps_with_kaggle_tags']} | {result['gaps_without_kaggle_tags']} |")
    lines += ["", "## 缺口处理", "",
              "- 网络失败、无法匹配、隐藏和无标签状态分别保留在 metrics.json，不将请求失败解释为游戏没有标签。",
              "- 缺口存在 Kaggle 标签时，将其列为第二阶段补充证据候选；两个来源的时间和票数口径不同，不自动视作 SteamSpy 等价标签。",
              "- 两源均缺标签的游戏保持特征未知；在人工校验中评估 Steam 商店机制证据，证据不足时收窄支持范围。",
              "- 标签存在率不是八维特征完整率，也不是可计分时长覆盖率。规则与独立校验尚未完成，不生成玩家分数。", ""]
    (path / "report.md").write_text("\n".join(lines), encoding="utf-8")
    store.finish(path, manifest)
    print(path / "report.md")


if __name__ == "__main__":
    main()
