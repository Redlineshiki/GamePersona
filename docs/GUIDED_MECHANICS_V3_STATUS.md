# 引导与机制标签 v3 状态

2026-10-14，已完成并切换本地默认规则与网站参考。规则共 81 项，新增引导 14 项、机制 19 项；完整清单与冻结口径见 [实验协议](GUIDED_MECHANICS_V3_EXPERIMENT_PROTOCOL.md)。包括用户确认的全部 0.25 弱证据，以及 0.5 相关证据。同维度取最大权重，标签、同义词和双源重复均不叠加；其他十维规则不变。

后续更新：用户已明确授权采用连续W正式模型，当前网站参考为 `stage3-reference-weight-v3-20261014`，沿用本页81项v3规则并重新核验W分布。示例引导69.66、机制71.24；下文74.9/85.7及固定N/H验收是此前标签扩展版本的历史结果。新发布见 [W正式模型状态](PRODUCTION_W_V3_STATUS.md)。

## 覆盖与示例账号

| 口径 | 引导 v1 → v3 | 机制 v1 → v3 |
|---|---:|---:|
| 固定特征集 3,064 款，有标签支持 | 58 → 797 | 378 → 1,069 |
| 示例账号全部 136 款，有标签支持 | 4 → 32 | 19 → 51 |
| 示例账号实际正时长贡献 | 3 → 28 | 15 → 46 |
| 示例账号参考分位 | 66.3 → 74.9 | 61.8 → 85.7 |

3,064 款是本轮固定特征集，不是数据库全部 50,872 个目录 AppID。示例账号仍纳入 99 款、3,261.8 小时，其他十维证据及分位未变。标签命中包含零时长游戏，所以不能把 32/51 当成实际贡献数量。

机制新增贡献示例：Tabletop Simulator（AppID 286160）通过 Trading Card Game 获得 0.5 支持；宽泛 Roguelike、Action RPG 等仍只给 0.25。引导仍有标签歧义，例如 Sekiro 的 Rhythm；纳入表示标签支持，不证明真实引导强度。每款游戏的 G/M 权重、时长、贡献与标签见 [贡献明细](../artifacts/analysis/guided-mechanics-v3/contributions.md)。

## 固定版本与验收

- 特征：`stage2-features-guided-mechanics-v3-20261014`，完整性通过，离线重放 identical。
- 聚合：`stage3-aggregate-guided-mechanics-v3-20261014`，处理 41,154,794 条记录、13,781,059 名用户。
- 参考：`stage3-reference-guided-mechanics-v3-20261014`，选中 log 与 fixed；工程验收 passed，离线重放 identical。
- 示例报告：`stage3-account-guided-mechanics-v3-20261014`，离线重放 identical，报告 SHA-256 为 `905f0c59985d3b88fa8431cc131dd00d2edd01cee210a0abb0d0975ccbb459f0`。

2,000 名用户 SQL/Python 计算对齐通过。固定评价部分 500 人，小时扰动绝对分位变化中位数 1.34、P95 13.334，类型一致率 116/120（96.67%）；验收沿用预先冻结的门槛。此评价切分曾用于 v1，因此属于版本回归，不属于新盲测，迁移偏差和心理测量效度仍未验证。固定 N/H 分组边界跳变仍是已知限制，本轮未合并平滑参考实验。

## 页面显示

页面分数、雷达、贡献标题和分享图统一采用中文名称加缩写：PLAN、REACT、GUIDE、OPEN、MECH、NARR、HARD、CALM、SOLO、SOCIAL、COMP、COOP。类型摘要显示 `REACT · GUIDE · MECH · HARD`。内部字段兼容旧报告，历史报告保持固定；重新生成才采用新参考。

Python 全量 108 项测试通过；切换参考配置后网站 9 项测试再次通过；前端 6 项测试与构建通过。用隔离数据库和本地登录/采集替身验证新参考报告，桌面 1,280px 与手机 390px 均无缩写裁切或横向溢出；PNG 下载与贡献标题已核对。验收服务已关闭并清理临时数据库 schema。

![桌面页面](../artifacts/analysis/guided-mechanics-v3/desktop.png)

![手机页面](../artifacts/analysis/guided-mechanics-v3/mobile.png)
