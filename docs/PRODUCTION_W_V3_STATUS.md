# W与v3标签正式模型状态

2026-10-14（Asia/Hong_Kong）。**已切换本地正式默认模型，已为网站现有输入生成新报告；旧报告保持固定。**

正式参考：`stage3-reference-weight-v3-20261014`；模型：`model-stage3-weight-v3-v1`；规则：`tag-rules-v3-guided-mechanics`（81项）。规则包含引导新增14项、机制新增19项，并已使用这些特征重建全部W参考观测。
W-only采用log1p(W)的biweight条件经验中位秩，带宽0.10、有效参考至少200。N保留充分性用途；H不再切组。生产评分使用标准Python与math.fsum，无新增NumPy运行依赖。

## 发布核验

- 固定参数v3校准及新留出工程验收：passed，全部门槛通过。新留出500名随机用户加75个N边界、100个H边界案例，共645名不同用户，排除1794名此前已查看的evaluation用户。没有新的N=99群体样本，99→100仅用Steam账号作迁移诊断。
- v3拟合人口838,409人，抽样58,408名逐人观测；所有拟合N/H/E与v3聚合一致。另对1501名用户含200名拟合用户核对SQL/Python W/N/H/E，全部一致。
- 新留出±10%时长分位变化P95 1.178；新增6分钟跨旧N边界P95 0.354、最大0.809；H边界P95 0.067。完整分母在验证metrics.json。
- 正式引擎与NumPy实验逐值核对2368个输入、23021个可展示维度，最大差5.68e-14（门槛1e-9），不可展示原因也一致。
- Python完整测试118 passed；切换配置后网站集成10 passed；前端6 passed、构建成功；git diff --check无空白错误。Vite第一次受Windows子进程沙箱限制，授权构建在正常执行环境中成功。
- 新W正式参考、新W示例报告、历史v1报告、历史v3固定N/H报告离线重算均identical。旧报告没有被新默认规则或新W字段覆盖。

## 示例账号评分与标签变化

以下均为同一99款、3261.8167小时输入。参考方法/标签版本不同会重新定位分位，不可把分位差直接归因为单款标签。

| 维度 | 原固定N/H＋v3 | 此前W实验＋v1 | 正式W＋v3 |
|---|---:|---:|---:|
| 规划 | 48.68 | 32.62 | 32.60 |
| 反应 | 66.32 | 34.33 | 34.35 |
| 引导 | 74.93 | 62.44 | 69.66 |
| 开放 | 62.39 | 37.38 | 37.37 |
| 机制 | 85.70 | 49.57 | 71.24 |
| 叙事 | 35.55 | 24.78 | 24.77 |
| 高压 | 93.27 | 87.79 | 87.80 |
| 舒缓 | 77.29 | 71.60 | 71.55 |
| 独玩 | 50.96 | 8.88 | 8.87 |
| 社交 | 96.77 | 94.64 | 94.66 |
| 竞争 | 59.45 | 46.44 | 46.48 |
| 合作 | 98.70 | 96.71 | 96.73 |

引导实际贡献28款、机制46款，来源与0.5/0.25最大权重解释均采用v3规则。其他十维账号原始证据沿用同一口径。17次新增6分钟实验共204个分位比较，最大变化0.623。
规划/反应为混合，引导/开放偏引导，机制/叙事偏机制，高压/舒缓偏高压，独玩/社交偏社交，竞争/合作偏合作；完整四字母摘要缺省。

## 网站生效与历史保留

默认设置、.env.web和.env.web.example统一使用新参考。网站数据读取时间保留原采集时间，新报告另记录recomputed_at和saved Steam GetOwnedGames input，不伪造新的Steam采集。
已更新1份新报告，保留4份历史报告。新报告/分享十二维逐值一致，规则版本和内容哈希独立核对。
本地服务已启动，http://127.0.0.1:8000/与/api/session均返回200，首页与本轮构建一致、Cache-Control=no-store。助手未代替用户操作真实Steam登录；现有会话与身份关联保留。

## 来源和复现

- [发布协议](PRODUCTION_W_V3_PROTOCOL.md)
- [正式参考](../artifacts/snapshots/stage3-reference-weight-v3-20261014/manifest.json)
- [v3新留出验证](../artifacts/snapshots/production-weight-v3-validation-20261014/metrics.json)
- [示例新报告](../artifacts/snapshots/stage3-account-weight-v3-20261014/report.json)
- [生产/实验对照](../artifacts/weight-v3-rollout-evidence/parity.json)

```powershell
.\.venv\Scripts\python.exe -m gamepersona replay-reference --snapshot stage3-reference-weight-v3-20261014
.\.venv\Scripts\python.exe -m gamepersona replay-score --snapshot stage3-account-weight-v3-20261014
```

标签支持仍不证明真实模式时长或机制强度；零证据大并列、未知游戏、评论记录到完整库迁移与心理效度限制保留。正式采用表示采用本轮通过的工程模型，所有分位继续标为实验性。
