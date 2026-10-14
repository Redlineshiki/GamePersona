# 第四阶段本地网站与验收状态

2026-10-14（Asia/Hong_Kong）。**实现与自动检查已完成；用户已在外部浏览器完成真实登录，并确认报告与图片一致。** 正式数据库独立核实有1个真实账号、1次成功实时读取和1份十二维均可展示的报告；不使用内置浏览器的独立会话否认外部登录。公网部署未执行。实账号退出/删除的人工观察尚未记录，隔离 PostgreSQL 集成验证已通过。

## 交付与启动

FastAPI / React 本地网站，PostgreSQL 18.6 私人持久化；Steam OpenID 2.0、限频读取、可恢复任务、固定报告、六组分数条、十二维雷达图、贡献解释和浏览器 PNG。首次部署步骤见 README。

```powershell
# 先按 README 安装锁定依赖与构建 web；本地 .env 保存 STEAM_API_KEY。
.\.venv\Scripts\python.exe scripts/local_database.py start
.\scripts\start-local.ps1
```

产品地址 `http://127.0.0.1:8000/`。网站数据在 PostgreSQL `.cache/postgres-data`；身份、任务、输入和报告均有用户所有权。`.env.web` 保持本地且忽略提交；数据库仅监听 127.0.0.1:55432，使用 SCRAM 密码。官方便携 ZIP 版本、下载地址与 SHA-256 在 local_database.py 固定，未注册系统服务。

登录用 python3-openid 3.2.0 完成签名字段、return_to、nonce 校验，Steam 固定提供方通过 HTTPS 直接核验签名；不跟随任意身份 URL 发现。事务绑定浏览器 Cookie，十分钟有效且只能消费一次；会话/登录 Cookie 按站点 origin 分开，避免不同本地端口互相覆盖。会话12小时有效；退出即时撤销。普通 Web API Key 留在后端，访问日志禁用，来源异常返回固定错误码。

任务持久化并由单个后台 worker 执行；schema 内主锁避免并行恢复，重启把中断 running 任务恢复为 pending。删除先锁用户，再级联删除身份、会话、登录事务、任务、输入和报告；完成写入前复核用户与任务，防止删后重建。网站不保存 PNG 文件，下载由浏览器完成。

## 自动与浏览器验收

- PostgreSQL 实际迁移、测试独立 schema、双用户报告/分享/任务越权拒绝、CSRF、登录绑定与重放、签名字段与 nonce、退出、超时状态、采集期间删除及中断任务恢复测试通过。
- React 构建通过；分享测试覆盖等待中文字体、长中文换行、nullable 与真实零、完整/部分/无雷达面、全部待定标题。
- 最终完整 `.venv/Scripts/python.exe -m pytest`：106 passed（60.91秒）；`web` 中 `npm.cmd test`：5 passed；`npm.cmd run build -- --logLevel error` 成功；`git diff --check` 无空白错误。
- 浏览器测试使用独立 schema 的 loopback 实例，正常记录来自之前真实授权账号快照；登录/采集为测试替身，报告明确标注样例。生产服务没有模拟登录开关。
- 正常报告：十二个分位可见，类型 null，雷达图与分数条一致，PNG 已下载并逐值对照。
- 零时长报告：N=0，十二个分位均 `—`，雷达点=0、填充面=0，PNG 标“数据不足·画像待定”。
- 部分可估计报告：9 维可见；M/C/COMP 因集中度抑制，9 个雷达点、无填充面，不跨未知轴连接；PNG 已下载。
- 390 px 手机宽度检查：12 个轴标签，无横向溢出；检查后恢复视口。图片视觉检查中文字与标记可读、无截断。
- [浏览器固定检查](../artifacts/snapshots/stage4-browser-v1-20261014/checks.json)、[雷达截图](../artifacts/snapshots/stage4-browser-v1-20261014/report-radar.jpg)、[正常 PNG](../artifacts/snapshots/stage4-browser-v1-20261014/normal.png)、[不足 PNG](../artifacts/snapshots/stage4-browser-v1-20261014/zero.png)、[部分 PNG](../artifacts/snapshots/stage4-browser-v1-20261014/partial.png)。manifest 固定文件哈希，目录为本地私人产物。

## 第七节场景映射

| 场景 | 验证与结果 |
|---|---|
| 正常参考支持 | 阶段三真实账号+独立样本；浏览器正常样例，pass；本轮真实登录和实时读取已由正式库核实，报告/PNG一致由用户外部浏览器确认 |
| 双高/双低、混合、小差异 | test_reference 的未舍入倾向与独立水平测试，pass |
| 单游戏极高时长/集中 | test_scoring/test_reference；部分浏览器报告抑制3维，pass |
| 部分缺标签/未知维度 | 共同集合整款排除、覆盖与不可估计测试，pass |
| 零或未知时长 | 共享评分边界+零时长浏览器/PNG，pass |
| 充分输入某维零证据 | 中位秩+zero_evidence 提示测试，pass |
| 不足/退化/超范围参考 | 单元与小型离线实际执行+不得回退测试，pass |
| 身份与不可读取、服务超时 | 登录/读取独立状态和失败无报告测试，pass；真实认证已由正式库核实 |
| 类型缺省/部分缺失 | 正常、部分及不足报告与 PNG，pass |
| 旧报告/版本更新 | 固定 JSON 报告、模型哈希校验、replay-score，pass |
| 重复记录/重复计算 | 共同清洗、整数聚合及三个全量 replay，pass |
| 预测目标隔离 | 本阶段未开展预测实验；不声称已验证未来偏好 |

## 审查修复与剩余事项

自动复核修复了后台主锁跨 schema 争用、临时数据库掉线后任务停滞、不同端口 Cookie 覆盖、JSONB 键顺序影响 PNG 维度顺序、静态文件根路径、中文字体按实际字符加载，以及完全待定报告被称作混合。报告切换/退出后的旧请求和旧字体加载不会覆盖新报告预览；导出使用独立 canvas。相关回归与浏览器复核通过。个人贡献显示 API 提供的游戏名称或 AppID，并可打开商店，名称不进入分享字段。

2026-10-14后续核验：用户在外部浏览器完成真实登录并确认报告/图片一致。正式库中的任务状态为 succeeded/read_status=success，99款有效游戏、十二维全部可展示，完整类型缺省；报告内容哈希独立校验通过。固定证据见 artifacts/snapshots/stage4-real-login-v1-20261014/。原“未真实登录”阻塞已消除。外部实账号退出/删除未由助手观察，不能把该动作写成已执行；退出、会话撤销、跨用户隔离及删除竞态继续引用已通过的真实PostgreSQL隔离测试，不要求删除用户报告作为验证替代。

公网许可/来源使用条件、域名 HTTPS、备份和日志保留、运行监控另行落实。源码无公开报告 URL、排行榜或默认研究收集。当前依赖有两条弃用提示（Starlette 对 httpx 测试适配、openid 的 XML 导入），功能检查未失败；后续升级需重新验证。
