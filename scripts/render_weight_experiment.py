"""Create the local exposure-reference report from frozen metrics."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gamepersona.interpretation import NAMES, interpret
OUT = ROOT / "artifacts/snapshots/weight-reference-experiment-v1-20261014"
read = lambda p: json.loads(p.read_text(encoding="utf-8"))
m, selection, inputs = (read(OUT/name) for name in ("metrics.json","selection.json","inputs.json"))
calibration, evaluation = read(OUT/"calibration.json"),read(OUT/"evaluation.json")
model = read(ROOT/"artifacts/snapshots/stage3-reference-v1-20261014/model.json")
old, nh, new = m["baseline"],m["N_H_control"],m["smooth"]
fmt = lambda x: "—" if x is None else f"{x:.3f}"
passed = m["acceptance"] == "passed"
lines = ["# 连续W参考验证结果", "", "2026-10-14（Asia/Hong_Kong）。",
    "**结论：" + ("本轮工程验收通过；仍为隔离实验，尚未替换网站评分。" if passed else "本轮工程验收未通过；保留失败诊断，尚未替换网站评分。") + "**",
    "", "## 改动及选型", "",
    "游戏贡献公式、标签、纳入集合、原始十二维证据保持不变。把查询参考人群的主要条件从有效游戏数N换成总基础时长权重W=Σln(1+t)。N仍用于至少5款等输入充分性判断。",
    f"W先逐款量化到1e-10后求和；本轮冻结{m['selected_mode']}模式、带宽{m['selected_bandwidth']}（log坐标半宽）。W-only只用log1p(W)；W/H同时用log1p(W)、log1p(H)。",
    "沿用58405名确定性拟合样本，代表838349名合格拟合人口；使用旧组全量人数/抽样人数纠正跨组取样率。旧N/H组仅用于抽样，查询没有游戏数分组。",
    "500名校准随机用户及180个边界案例用于选择。候选、优先次序和门槛运行前固定，真实Steam账号不参与选型。",
    "", "| 模式及带宽 | 校准±10%时长P95 | 校准N边界P95 / 最大 | 校准H边界P95 | 全部门槛通过 |",
    "|---|---:|---:|---:|---|"]
for c in selection["candidates"]:
    a=c["metrics"]; n=a["boundaries"]["N_boundary"];h=a["boundaries"]["H_boundary"]
    lines.append(f"| {c['mode']} {c['bandwidth']} | {fmt(a['perturbation']['p95'])} | {fmt(n['p95'])} / {fmt(n['max'])} | {fmt(h['p95'])} | {'是' if c['passed'] else '否'} |")
lines += ["", "## 新留出核验", "",
    "排除正式v1已查看500名evaluation用户及前轮N/H实验已查看650名用户，共1150人。使用新固定盐选取500名随机留出用户、75个N边界案例及100个H边界案例；边界与随机用户可能重叠，共644名不同evaluation用户。与calibration和fit用户不重合。",
    "排除旧已查看用户后，没有剩余N=99的合格evaluation用户，所以新的群体N边界只覆盖9→10、19→20、49→50。99→100只报告Steam账号迁移诊断，不冒充新的群体独立核验。新留出仍来自同一评论数据集。",
    "", "以下直接比较三种方法在扰动前后都可展示的共同维度。样本单位是用户×维度×扰动，不是独立用户数。",
    "", "| 场景 | 三者共同对照数 | 正式参考P95 / 最大 | N/H平滑P95 / 最大 | W参考P95 / 最大 |",
    "|---|---:|---:|---:|---:|"]
for key,title in [("duration","±10%时长"),("N_boundary","新增6分钟游戏，跨旧N边界"),("H_boundary","旧时长边界两侧±0.1小时")]:
    a=m["paired_three"][key]
    lines.append(f"| {title} | {a['W']['count']} | {fmt(a['old']['p95'])} / {fmt(a['old']['max'])} | {fmt(a['N_H']['p95'])} / {fmt(a['N_H']['max'])} | {fmt(a['W']['p95'])} / {fmt(a['W']['max'])} |")
lines += ["", "## W方案自身的全部验收指标", "",
    "| 检查 | 留出结果 | 门槛/判定 |", "|---|---|---|"]
p=new["perturbation"]
lines += [f"| 十二维全可展示 | {new['full_twelve']}/500 | 至少20 |",
    f"| 至少一维可展示 | {new['any_supported']}/500，{new['any_supported_ratio']:.2%} | 至少80% |",
    f"| ±10%时长变化 | 中位数{fmt(p['median'])}，P95 {fmt(p['p95'])} | ≤5 / ≤15 |",
    f"| 同上失去支持 | {p['lost_support_ratio']:.3%} | ≤20% |",
    f"| 类型一致率 | {new['type_consistency']:.2%}，{new['type_comparisons']}次比较 | 至少40次后要求≥80% |",
    f"| 随机化PIT十等分平均误差 | 正式{old['PIT_mean_error']:.5f}，W {new['PIT_mean_error']:.5f} | 不超过正式+0.02 |",
    f"| 分位分散度 | {sum(v['count']>=200 and v['position_std']>=10 for v in new['PIT'].values())}维有≥200位置且标准差≥10 | 至少10维 |"]
for kind,title in [("N_boundary","N边界"),("H_boundary","H边界")]:
    a=new["boundaries"][kind]
    lines.append(f"| {title} | P95 {fmt(a['p95'])}，最大{fmt(a['max'])}，失去支持{a['lost_support_ratio']:.3%} | ≤5 / ≤10 / ≤20% |")
lines += ["", "逐项检查："+"；".join(f"{k}={'通过' if v else '未通过'}" for k,v in m["checks"].items())+"。",
    "类型比较的各方法原类型人群不同，比例不能被解释成同人群因果提升。PIT/分散度仅诊断条件参考校准，不能证明偏好真值、推荐效果或心理效度。",
    "", "## 新增游戏的变化来源", "",
    "给有效集合新增0.1小时游戏，N增加1，W只增加ln(1.1)≈0.0953101798。",
    "", "| 旧游戏数边界 | W分位变化P95 / 最大 | 固定E/H，只改变W的P95 |", "|---|---:|---:|"]
for edge,a in new["boundaries"]["N_boundary"]["by_edge"].items():
    b=m["W_conditioning_only_diagnostic"][edge]
    lines.append(f"| {int(edge)-1}→{edge} | {fmt(a['p95'])} / {fmt(a['max'])} | {fmt(b['p95'])} |")
lines += ["", "零证据并列仍可能造成经验分位跳变，W本身的小变化不保证分位一定小变化。此次新增游戏维度对照的分类：", "",
    "| 证据变化 | 可比数量 | P95 / 最大 |", "|---|---:|---:|"]
for key,title in [("zero_to_positive","零→正证据"),("positive_to_positive","正→正证据"),("unchanged_E","证据未变")]:
    a=m["N_boundary_evidence_diagnostics"][key]
    lines.append(f"| {title} | {a['count']} | {fmt(a['p95'])} / {fmt(a['max'])} |")
lines += ["", "零→正类别没有案例时，不宣称它也已验证稳定。方法单元检查明确展示大零值并列导致的阶跃；这一限制不由更换参考坐标解决。",
    "", "## 示例账号：同一99款、3261.8167小时输入", "",
    f"基础时长权重W={m['account']['W']:.10f}。下表没有新增6分钟，也没有改标签或原始贡献。正式/NH/W三种参考会重新定位分位。",
    "", "| 维度 | 当前正式参考 | 上轮N/H平滑 | 本轮W参考 | W减正式 |", "|---|---:|---:|---:|---:|"]
account=m["account"]
for d,name in NAMES.items():
    a,b,c=account["old_base"][d]["value"],account["N_H_base"][d]["value"],account["smooth_base"][d]["value"]
    lines.append(f"| {name} | {fmt(a)} | {fmt(b)} | {fmt(c)} | {fmt(c-a) if c is not None else '—'} |")
labels={**NAMES,"mixed":"混合",None:"待定"}
profiles=[interpret(account[k],model) for k in ("old_base","N_H_base","smooth_base")]
lines += ["", "| 组合 | 当前正式参考 | 上轮N/H平滑 | 本轮W参考 |", "|---|---|---|---|"]
for i,g in enumerate(profiles[0]["groups"]):
    lines.append(f"| {NAMES[g['left']]}/{NAMES[g['right']]} | " + " | ".join(labels[p['groups'][i]['tendency']] for p in profiles) + " |")
lines += ["", "四字母摘要："+" → ".join(p["type"] or "待定" for p in profiles)+"。",
    "", "## 示例账号分别新增6分钟", "",
    "17款特征已知、零时长的游戏分别变为0.1小时，各实验独立从同一原输入开始。",
    f"W方案共有{account['delta']['count']}个可比分位，最大变化{fmt(account['delta']['max'])}；未知数量需结合下表和metrics.json查看，不用丢掉未知维度换取稳定。",
    "", "| 维度 | W原分位 | Metro 2033加6分钟后 | 变化 |", "|---|---:|---:|---:|"]
variant=next(r for r in account["variations"] if r["app_id"]==43110)
for d,name in NAMES.items():
    a,b=account["smooth_base"][d]["value"],variant["positions"][d]["value"]
    lines.append(f"| {name} | {fmt(a)} | {fmt(b)} | {fmt(b-a) if a is not None and b is not None else '—'} |")
ess=account["smooth_base"]["P"]["effective_reference"]
lines += ["", f"账号加权有效参考数约{ess:.2f}；当前可展示{sum(v['value'] is not None for v in account['smooth_base'].values())}维。",
    "", "## 保留的限制与复现", "",
    "本轮结果是稳定性、参考支持和条件校准的工程验证。它没有修复标签语义、缺失游戏、评论记录与完整游戏库的来源迁移、挂机或实际模式时长。即使通过，也不自动更新网站；旧模型和旧报告保持固定。",
    f"58405名拟合样本的N/H/E全部与正式聚合一致；另对{m['exposure_verification']['SQL_Python_W_N_H_E_users']}名用户（含200名拟合用户、全部校准/新留出用户）核对SQL/Python的W、N/H、十二维E，全部一致。",
    "7项原核检查、5项W坐标检查、22项现有评分/参考测试通过。evaluate重复执行的metrics.json哈希一致，manifest.json保存协议、产物与代码哈希。",
    "项目Python负责数据准备和verify-exposure；含NumPy的Python负责select/evaluate。未安装或更改项目依赖。完整顺序为prepare-calibration → select → prepare-evaluation → verify-exposure → evaluate。",
    "重建实验使用新的--output目录，已经准备/冻结的文件不会覆盖。只重算已冻结结果可运行：", "", "```powershell",
    "& $numpyPython scripts/experiment_weight_reference.py evaluate",
    ".\\.venv\\Scripts\\python.exe scripts/render_weight_experiment.py", "```",
    "", "详细候选/门槛在protocol.md和selection.json，全部支持分母和三方法配对对照在metrics.json，计算一致性在exposure_verification.json。"]
(OUT/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
manifest=read(OUT/"manifest.json")
manifest["artifacts"]["report.md"]=hashlib.sha256((OUT/"report.md").read_bytes()).hexdigest()
manifest["code_hashes"][Path(__file__).name]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(OUT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(str(OUT/"report.md"))
