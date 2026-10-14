"""Render the frozen experiment metrics without rerunning or selecting models."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/snapshots/smooth-reference-experiment-v1-20261014"
read = lambda p: json.loads(p.read_text(encoding="utf-8"))
m, selection, inputs = (read(OUT / name) for name in ("metrics.json", "selection.json", "inputs.json"))
names = {"P":"规划", "R":"反应", "G":"引导", "O":"开放", "M":"机制", "N":"叙事",
         "H":"高压", "C":"舒缓", "SOLO":"独玩", "SOCIAL":"社交", "COMP":"竞争", "COOP":"合作"}
old, new = m["baseline"], m["smooth"]
lines = ["# N/H平滑条件参考验证结果", "", "2026-10-14（Asia/Hong_Kong）。",
    "**结论：明显改善，但未通过本轮全部预声明验收条件。暂不替换网站评分。**",
    "失败条件是N边界稳定性；其他支持、时长扰动、类型、随机化PIT校准、分位分散度及H边界目标通过。",
    "", "## 实验范围", "",
    "保留ln(1+t)×标签最大权重的共享贡献公式，标签、资格、集中度、类型门槛均不变。只替换参考查询为log1p(N)/log1p(H)上的平滑加权经验CDF。",
    f"拟合人口{inputs['fit_population']:,}人，沿用旧版确定性抽样{inputs['fit_users']:,}人；跨组查询按原组全量人数/抽样人数校正抽样率。原组只用于抽样，查询没有整组切换。",
    "核为紧支撑biweight乘积；三个带宽固定为(0.25,0.40)、(0.40,0.65)、(0.60,1.00)。有效加权参考数至少200、超出实际N/H范围不外推，没有总体回退。",
    "500名随机校准用户及180个校准边界案例参与选型。三个候选都未通过N边界门槛，因此按协议冻结最小带宽(0.25,0.40)作失败诊断，而非宣称最佳生产模型。",
    "冻结后核验500名新留出随机用户及182个留出边界案例；与v1已查看的500名evaluation用户不重合，也与校准用户不重合。边界案例和随机用户可能重叠，两阶段共1305名不同用户；N/H/E重算与原聚合完全一致。",
    "新留出数据来自同一评论数据集，不是新的外部来源；Steam示例账号未参与候选选择。",
    "", "## 三个候选的校准表现", "",
    "| 带宽(N,H) | ±10%时长P95 | N边界P95 / 最大 | H边界P95 | 全部门槛通过 |",
    "|---|---:|---:|---:|---|"]
for c in selection["candidates"]:
    a = c["metrics"]
    n, h = a["boundaries"]["N_boundary"], a["boundaries"]["H_boundary"]
    lines.append(f"| {c['bandwidth']} | {a['perturbation']['p95']:.3f} | {n['p95']:.3f} / {n['max']:.3f} | {h['p95']:.3f} | {'是' if c['passed'] else '否'} |")
lines += ["", "## 新留出样本：同一批可展示维度的直接对照", "",
    "两种方法的支持范围不同。以下先取两种方法在扰动前后均可展示的共同维度，避免通过改变分母夸大改善。每个指标的样本是用户×维度×扰动，而非独立用户数。",
    "", "| 场景 | 共同对照数 | 原方法中位数 / P95 / 最大 | 平滑方法中位数 / P95 / 最大 |",
    "|---|---:|---:|---:|"]
for key, title in [("duration","±10%时长"),("N_boundary","游戏数边界，新增0.1小时游戏"),("H_boundary","小时边界两侧±0.1小时")]:
    a,b = m["paired"][key]["old"],m["paired"][key]["smooth"]
    lines.append(f"| {title} | {a['count']} | {a['median']:.3f} / {a['p95']:.3f} / {a['max']:.3f} | {b['median']:.3f} / {b['p95']:.3f} / {b['max']:.3f} |")
lines += ["", "新增边界目标要求P95≤5且最大≤10。平滑N边界仍为6.947/14.198，因此未通过。H边界通过。",
    "", "## 剩余N效应的位置", "", "| 有效游戏数变化 | 平滑P95 | 最大变化 | 固定H/E，仅改变N条件的P95 |", "|---|---:|---:|---:|"]
for edge, v in new["boundaries"]["N_boundary"]["by_edge"].items():
    d = m["N_conditioning_only_diagnostic"][edge]
    lines.append(f"| {int(edge)-1}→{edge} | {v['p95']:.3f} | {v['max']:.3f} | {d['p95']:.3f} |")
lines += ["", "固定E/H而只改变N的反事实诊断仍能复现大部分变化，说明剩余变化主要来自参考条件改变，而非新增6分钟的标签贡献。该反事实只用于归因，不被当作真实输入重算或验收样本。",
    "在9→10款时，游戏数增加约11%，但新增游戏可能只玩6分钟。即使取消硬分组，连续N仍会把它视为具有更大体验广度的玩家。因此平滑修复了整批切换，却没有消除N与证据量不一致的问题。",
    "", "## 支持、校准及其他稳定性", "",
    f"随机留出样本原方法至少一维可展示500/500；平滑{new['any_supported']}/500（{new['any_supported_ratio']:.1%}）。两者十二维全可展示均为{new['full_twelve']}/500。平滑新增3名用户因有效局部参考不足而全维未知，没有回退。",
    f"原方法类型扰动一致率{old['type_consistency']:.2%}（{old['type_comparisons']}次）；平滑{new['type_consistency']:.2%}（{new['type_comparisons']}次）。两者原类型人群不同，不能当作同人群因果提升。",
    f"未按集中度筛选的条件校准：随机化PIT十等分平均绝对偏差原方法{old['PIT_mean_error']:.5f}，平滑{new['PIT_mean_error']:.5f}，未见明显恶化。12维均有至少200个位置且分位标准差≥10；这能排除恒定50分假稳定，但不能证明预测或心理效度。",
    "",
    f"删除最大总证据游戏：原方法中位数{old['deletion']['median']:.3f}、P95 {old['deletion']['p95']:.3f}、失去支持{old['deletion']['lost_support_ratio']:.2%}；平滑中位数{new['deletion']['median']:.3f}、P95 {new['deletion']['p95']:.3f}、失去支持{new['deletion']['lost_support_ratio']:.2%}。该较强扰动仅作诊断，支持集合不同。",
    "原方法H=5000边界的这些案例无可比维度，平滑则有支持；上述H边界共同对照表不包含这部分新增支持。所有完整分母、每个边界和失去支持比例保存在metrics.json。",
    "", "## Steam示例：99→100款", "",
    "给Metro 2033新增6分钟，以下是同一游戏扰动前后的结果。平滑方法会重新定位原账号分位，不能理解为沿用旧分数再平滑展示。",
    "", "| 维度 | 原方法：前→后 | 平滑方法：前→后 |", "|---|---:|---:|"]
account = m["account"]
variant = next(r for r in account["variations"] if r["app_id"] == 43110)
for d,name in names.items():
    a,b = account["old_base"][d]["value"],variant["old"][d]["value"]
    c,e = account["smooth_base"][d]["value"],variant["positions"][d]["value"]
    lines.append(f"| {name} | {a:.2f}→{b:.2f} | {c:.2f}→{e:.2f} |")
lines += ["", f"17款零时长游戏分别新增6分钟，共204个维度对照，平滑最大变化{account['delta']['max']:.3f}。示例账号加权有效参考约370.29人，十二维均可展示。",
    "", "## 结论与后续方向", "",
    "本轮已完成第一种方案的验证，证据支持它能显著减轻硬分组跳变；但保留连续N仍对低游戏数玩家的少量新游玩敏感，因此暂不直接替换生产参考。下一候选可以比较总有效时长权重W=sum ln(1+t)，或以实际投入定义的体验广度条件，仍需预声明新的实验和新的留出验证。",
    "标签语义、未知游戏、评论样本到完整库迁移、挂机与实际模式时长问题均未解决。没有修改现有网站、规则、参考快照、旧报告或模型依赖。",
    "", "## 复现与检查", "",
    "数据准备使用项目Python 3.14.6和DuckDB 1.5.6；数值实验使用Codex捆绑Python 3.12.14及NumPy 2.3.5。没有安装或修改项目依赖。核实现7项单元检查、现有评分/参考22项测试通过；evaluate重复执行的metrics.json内容哈希相同。",
    "阶段顺序：prepare-calibration → select → prepare-evaluation → evaluate；准备阶段只读旧快照并写新目录。已存在的准备或选型文件不会覆盖。重建全部实验时指定新的--output目录；仅evaluate可重算现有冻结输入。",
    "", "```powershell",
    ".\\.venv\\Scripts\\python.exe scripts/experiment_smooth_reference.py prepare-calibration --output artifacts/snapshots/smooth-reference-rerun",
    "# 数值阶段需要含NumPy的Python；本次使用捆绑runtime/python/python.exe",
    "& $numpyPython scripts/experiment_smooth_reference.py select --output artifacts/snapshots/smooth-reference-rerun",
    ".\\.venv\\Scripts\\python.exe scripts/experiment_smooth_reference.py prepare-evaluation --output artifacts/snapshots/smooth-reference-rerun",
    "& $numpyPython scripts/experiment_smooth_reference.py evaluate --output artifacts/snapshots/smooth-reference-rerun",
    "```", "",
    "protocol.md固定运行前协议；inputs.json固定数据哈希；selection.json记录校准与冻结参数；metrics.json保存留出/配对/归因/示例结果；manifest.json固定产物与代码哈希。"]
(OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
manifest = read(OUT / "manifest.json")
manifest["artifacts"]["report.md"] = hashlib.sha256((OUT / "report.md").read_bytes()).hexdigest()
manifest["code_hashes"][Path(__file__).name] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(str(OUT / "report.md"))
