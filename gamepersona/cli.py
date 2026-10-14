from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import duckdb
import httpx

from .audit import audit, replay
from .achievements import probe_achievements, replay_achievements
from .collect import Fetcher, fetch_steam, fetch_steamspy, verify_sources
from .features import build_features, replay_features
from .ingest import import_kaggle
from .sampling import select_games
from .storage import Store, load_credentials
from .offline import aggregate, replay_aggregate
from .calibration import experiment, replay_reference
from .assessment import score_steam, replay_score


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GamePersona 数据审计与第二阶段自动特征模型；不下载 Kaggle 文件")
    p.add_argument("--root", type=Path, default=Path("artifacts"), help="本地私有产物目录")
    commands = p.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="校验并导入本地完整 Kaggle ZIP 或目录")
    imp.add_argument("--source", type=Path, required=True)
    imp.add_argument("--snapshot", required=True)
    imp.add_argument("--dataset-version", default="unverified")
    imp.add_argument("--hours-unit", choices=["unverified", "hours", "minutes"], default="unverified")
    imp.add_argument("--hours-evidence", default="")
    imp.add_argument("--duration-time-semantics", choices=["unverified", "at_collection", "at_review"], default="unverified")
    imp.add_argument("--time-evidence", default="")
    imp.add_argument("--memory-limit", default="2GiB")
    imp.add_argument("--threads", type=int, default=4)
    account = commands.add_parser("fetch-steam", help="读取一个本地配置且已授权的 Steam 账号")
    account.add_argument("--snapshot", required=True)
    account.add_argument("--env-file", type=Path)
    selection = commands.add_parser("select", help="确定性选取 3000 款基础游戏并合并账号 AppID")
    selection.add_argument("--snapshot", required=True)
    selection.add_argument("--kaggle", required=True)
    selection.add_argument("--steam")
    selection.add_argument("--seed", default="gamepersona-stage1-v1")
    spy = commands.add_parser("fetch-steamspy", help="限速采集标签；复用同一快照标识断点恢复")
    spy.add_argument("--snapshot", required=True)
    spy.add_argument("--selection", required=True)
    spy.add_argument("--max-games", type=int, help="限制本次新增请求数；不会标为全量完成")
    sources = commands.add_parser("verify-sources", help="保存来源说明与许可证据，不下载数据集")
    sources.add_argument("--snapshot", required=True)
    sources.add_argument("--review-file", type=Path, help="保存附证据的人工许可核验记录")
    report = commands.add_parser("audit", help="基于固定快照生成中文报告和 JSON 指标")
    report.add_argument("--report", required=True)
    report.add_argument("--kaggle", required=True)
    for name in ("steamspy", "steam", "selection", "sources"):
        report.add_argument("--"+name)
    rep = commands.add_parser("replay", help="不联网，验证快照完整性并重算已有报告")
    rep.add_argument("--report", required=True)
    features = commands.add_parser("build-features", help="双源标签自动生成十二维支持程度及覆盖报告")
    features.add_argument("--snapshot", required=True)
    features.add_argument("--kaggle", required=True)
    features.add_argument("--steamspy", required=True)
    features.add_argument("--selection", required=True)
    features.add_argument("--rules", type=Path, help="可选版本化 JSON 规则配置")
    feature_replay = commands.add_parser("replay-features", help="不联网，验证输入并重算特征和报告")
    feature_replay.add_argument("--snapshot", required=True)
    achievements = commands.add_parser("probe-achievements", help="读取已授权账号的分层成就小样本并试算")
    achievements.add_argument("--snapshot", required=True)
    achievements.add_argument("--steam", required=True)
    achievements.add_argument("--env-file", type=Path)
    achievement_replay = commands.add_parser("replay-achievements", help="不联网，重算固定成就小样本")
    achievement_replay.add_argument("--snapshot", required=True)
    agg = commands.add_parser('aggregate-users', help='固定输入全量聚合四种时长候选，分离拟合/校准/评价')
    for name in ('snapshot','kaggle','features'):
        agg.add_argument('--'+name,required=True)
    reference = commands.add_parser('build-reference',help='按预声明协议校准并冻结参考版本')
    reference.add_argument('--snapshot',required=True)
    reference.add_argument('--aggregate',required=True)
    reference.add_argument('--protocol',type=Path,default=Path('docs/STAGE3_EXPERIMENT_PROTOCOL.md'))
    promote = commands.add_parser('promote-weight-reference',help='发布通过核验且采用当前标签规则的W参考')
    for name in ('snapshot','validation','aggregate','features','baseline'):
        promote.add_argument('--'+name,required=True)
    score = commands.add_parser('score-steam',help='固定账号输入生成实验性私人报告')
    for name in ('snapshot','steam','reference'):
        score.add_argument('--'+name,required=True)
    for command in ('replay-aggregate','replay-reference','replay-score'):
        replay_command = commands.add_parser(command,help='不联网验证并重算固定产物')
        replay_command.add_argument('--snapshot',required=True)
    return p


def run(args: argparse.Namespace) -> tuple[dict, int]:
    store = Store(args.root)
    if args.command == "import":
        result = import_kaggle(store,args.snapshot,args.source,hours_unit=args.hours_unit,
                               hours_evidence=args.hours_evidence,dataset_version=args.dataset_version,
                               duration_time_semantics=args.duration_time_semantics,time_evidence=args.time_evidence,
                               memory_limit=args.memory_limit,threads=args.threads)
        return {"snapshot":args.snapshot,"state":result["state"],"quality":result["quality"]}, 0
    if args.command == "select":
        result = select_games(store,args.snapshot,args.kaggle,args.steam,args.seed)
        return {"snapshot":args.snapshot,"base_games":result["base_games"],"total_games":result["total_games"]}, 0
    if args.command == "audit":
        result = audit(store,args.report,kaggle=args.kaggle,steamspy=args.steamspy,
                       steam=args.steam,selection=args.selection,sources=args.sources)
        return {"report":str(store.path(args.report) / "report.md"),"stage_acceptance":result["stage_acceptance"]}, 0 if result["stage_acceptance"]["status"]=="passed" else 2
    if args.command == "replay":
        return replay(store,args.report), 0
    if args.command == "build-features":
        result = build_features(store, args.snapshot, args.kaggle, args.steamspy, args.selection, args.rules)
        return {"snapshot": args.snapshot, "report": str(store.path(args.snapshot) / "report.md"),
                "groups": {name: {"games": group["games"], "combined": {k: v for k, v in group["modes"]["combined"].items() if k != "unmapped_tags"}}
                           for name, group in result["groups"].items()},
                "integrity_checks": result["integrity_checks"]}, 0 if result["integrity_checks"]["status"] == "passed" else 2
    if args.command == "replay-features":
        return replay_features(store, args.snapshot), 0
    if args.command == "replay-achievements":
        return replay_achievements(store, args.snapshot), 0
    if args.command == 'aggregate-users':
        result = aggregate(store,args.snapshot,args.kaggle,args.features)
        return {'snapshot':args.snapshot,'totals':result['totals'],'candidates':result['materialized_candidates']},0
    if args.command == 'build-reference':
        result = experiment(store,args.snapshot,args.aggregate,args.protocol)
        return {k:v for k,v in result.items() if k!='support_groups'},0 if result['acceptance']=='passed' else 2
    if args.command == 'promote-weight-reference':
        from .weight_release import promote_weight_reference
        return promote_weight_reference(store,args.snapshot,args.validation,args.aggregate,args.features,args.baseline),0
    if args.command == 'score-steam':
        result = score_steam(store,args.snapshot,args.steam,args.reference)
        return {'snapshot':args.snapshot,'report_sha256':result['report_sha256'],'percentiles':result['percentiles'],'type':result['interpretation']['type']},0
    if args.command == 'replay-score':
        return replay_score(store,args.snapshot),0
    if args.command == 'replay-reference':
        return replay_reference(store,args.snapshot),0
    if args.command == 'replay-aggregate':
        return replay_aggregate(store,args.snapshot),0
    # Only explicitly named collection commands create an HTTP client.
    with httpx.Client(headers={"User-Agent":"GamePersona-stage1/0.1 (local data audit)"}, follow_redirects=True) as client:
        fetcher = Fetcher(client)
        if args.command == "fetch-steam":
            key, steam_id = load_credentials(args.env_file)
            result = fetch_steam(store,args.snapshot,key,steam_id,fetcher)
            return {"snapshot":args.snapshot,"read_status":result["read_status"],
                    "observed_records":result["observed_records"]}, 0 if result["read_status"] in {"success","explicit_empty"} else 2
        if args.command == "fetch-steamspy":
            result = fetch_steamspy(store,args.snapshot,args.selection,fetcher,args.max_games)
            return {"snapshot":args.snapshot,"state":result["state"],"attempted_games":result["attempted_games"],
                    "uncollected_games":result["uncollected_games"]}, 0 if result["state"]=="ready" else 2
        if args.command == "probe-achievements":
            key, steam_id = load_credentials(args.env_file)
            result = probe_achievements(store, args.snapshot, args.steam, key, steam_id, fetcher)
            return {"snapshot": args.snapshot, "report": str(store.path(args.snapshot) / "report.md"),
                    "probe_status": result["probe_status"],
                    "summary": {k: v for k, v in result["default"].items() if k != "contributions"},
                    "states": result["states"]}, 0 if result["probe_status"] == "passed" else 2
        result = verify_sources(store,args.snapshot,fetcher,args.review_file)
        return {"snapshot":args.snapshot,"findings":result["findings"]}, 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result, code = run(args)
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return code
    except (ValueError, OSError, zipfile.BadZipFile, duckdb.Error) as e:
        print(f"操作未完成：{e}",file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已中断；标签采集可使用同一快照标识恢复。",file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
