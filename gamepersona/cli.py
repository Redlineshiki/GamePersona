from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

import duckdb
import httpx

from .audit import audit, replay
from .collect import Fetcher, fetch_steam, fetch_steamspy, verify_sources
from .ingest import import_kaggle
from .sampling import select_games
from .storage import Store, load_credentials


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="GamePersona 第一阶段数据审计；不下载 Kaggle 文件")
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
