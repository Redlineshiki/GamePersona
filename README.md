# GamePersona：游戏偏好画像

本工程已实现数据审计、双源逻辑十二维特征、共享玩家评分及条件参考分布，并提供本地 Steam 登录、私人报告、雷达图和 PNG 分享网站。标签支持不等于机制不存在与否、现实人格或喜欢概率。阶段三预声明工程验收通过；阶段四实现及自动/浏览器样例检查已完成，用户已在外部浏览器验证真实登录和报告/图片一致；正式库实时读取证据已核实，外部实账号退出动作尚未由助手观察。实测见 [阶段一](docs/STAGE1_STATUS.md)、[阶段二](docs/STAGE2_STATUS.md)、[阶段三](docs/STAGE3_STATUS.md) 和 [阶段四](docs/STAGE4_STATUS.md)。

任务完成情况与剩余真实验收见 [实施计划](IMPLEMENTATION_PLAN.md)。所有模型结果持续标为“评论样本参考分位（实验性）”。

## 安装与测试

在项目根目录使用 Python 3.11 或以上版本（本轮已验证 Python 3.14.6）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pytest
python -m gamepersona --help
```

依赖全部固定版本；执行模块不需要安装项目本身。当前 `.venv\Scripts\python.exe` 可直接运行；环境内没有 pip 时，使用系统 Python 的 `-m pip --python .venv install -r requirements.lock` 安装锁定依赖。

## 运行顺序

以下快照名称是示例。使用已存在的快照标识不会重新导入或刷新来源；更换数据、证据或配置时使用新标识。命令没有 Kaggle 数据下载功能。本轮 `data_source/archive.zip` 已下载完成并通过全量导入；真实快照及验收结果见 [实施状态](docs/STAGE1_STATUS.md)，字段证据见 [核查记录](docs/STAGE1_EVIDENCE_RESEARCH.md)。

### 1. 本地导入

```powershell
python -m gamepersona import --source data_source/archive.zip --snapshot kaggle-local-01
```

也支持包含 `games.csv`、`games_metadata.json`、`users.csv`、`recommendations.csv` 的目录。ZIP 会先做完整 CRC 校验，再提取这四个文件；支持 ZIP64，拒绝路径穿越、重复文件名及未完成下载。

默认不根据 `hours` 字段名推断单位，保留原值但不生成小时数。核实来源口径后，可在新快照中显式登记证据：

```powershell
python -m gamepersona import --source data_source/archive.zip --snapshot kaggle-local-01 --hours-unit hours --hours-evidence "作者采集/转换管线证据及本地归档引用" --duration-time-semantics at_collection --time-evidence "累计时长采集时点证据及限制"
```

导入会以 SHA-256 固定本地归档内容；不要求本地文件证明 Kaggle 上游发行版本号。单位与采集时间语义仍须有来源依据。归档来源版本如无法确认，应如实记录，不影响本地数据审计验收。

默认 DuckDB 内存上限 2 GiB、4 个线程，可通过 `--memory-limit` 和 `--threads` 修改。数据流式读取，并允许聚合溢写到快照目录的 `spill`。原始文件、数据库和 Parquet 会额外占用磁盘空间。

### 2. 来源记录

```powershell
python -m gamepersona verify-sources --snapshot sources-01
```

此命令只获取说明和元数据，不下载 Kaggle 文件。来源说明快照用于审计追溯；许可判断不属于第一阶段本地数据审计的通过门槛。通过不表示已取得 SteamSpy 公开部署、派生特征或分享用途的授权。相关评估及隐私政策、保存说明和删除机制应在公开上线前完成。

### 3. 授权账号读取

复制 `.env.example` 为 `.env`，在本机填写 `STEAM_API_KEY` 与 `STEAM_ID`，不要将密钥发到聊天或提交版本控制。也可设置同名环境变量，环境变量优先。

```powershell
python -m gamepersona fetch-steam --snapshot steam-01 --env-file .env
```

普通 Web API Key 可从 [Steam API Key 页面](https://steamcommunity.com/dev/apikey) 获取；SteamID 应使用你本人或明确授权读取的账号的 17 位 ID。游戏详情需对当前读取方式可见。工具将账号标识作为输入，不完成 OpenID 身份认证；OpenID 登录属于第四阶段。

请求包括已玩免费游戏。明确空库、无法判断、凭据或访问错误、限流、超时及服务失败各有状态；空对象不会被判为空库。`playtime_forever` 按分钟转换为小时，不读取或收集 Steam 密码。输出报告不包含 SteamID 或个人游戏明细。

### 4. 确定性选样与标签采集

```powershell
python -m gamepersona select --snapshot selection-01 --kaggle kaggle-verified-01 --steam steam-01
python -m gamepersona fetch-steamspy --snapshot steamspy-01 --selection selection-01
```

基础集合为评论用户数最多的 1500 款，以及其余游戏分层抽取的 1500 款，再并入实测账号 AppID。分层使用五个热度层、排序后的首个元数据标签和标签稀疏状态，固定 MD5 顺序轮流取样。记录配置与选样原因；可关联游戏不足 3000 时如实输出，并保留阶段阻塞项。

采集每次请求至少相隔 1.05 秒，失败最多重试两次并退避，响应支持 24 小时缓存。3000 款未缓存游戏正常情况下至少需要约 53 分钟，重试和网络延迟会增加耗时。

中断后重跑同一命令可恢复。终态失败记录保留，不静默循环请求；复核失败或主动刷新时新建标签快照。已完成的快照保持固定，24 小时内的新快照仍复用成功缓存。首次采集也可使用 `--max-games 10` 分批执行；未完成快照不能用于固定报告。

### 5. 固定报告与离线重算

```powershell
python -m gamepersona audit --report audit-01 --kaggle kaggle-verified-01 --steam steam-01 --selection selection-01 --steamspy steamspy-01 --sources sources-01
python -m gamepersona replay --report audit-01
```

完成标签采集后，额外按热门、分层样本及账号集合检查覆盖和缺口：

```powershell
python scripts/analyze_stage1_sample.py --selection selection-01 --steamspy steamspy-01 --snapshot sample-analysis-01
```

该分析固定输入快照并保存代码、JSON 和中文报告，分别展示每组分母及缺口能否从 Kaggle 获得标签证据。账号和基础集合有交集，不把各组数量相加，也不将选样覆盖外推为全量游戏覆盖。Kaggle 标签仅作为补充证据候选，不能直接冒充同时间的 SteamSpy 票数标签。

未准备好账号、标签或来源快照时，可以只传 `--kaggle` 生成明确缺少实测项的离线报告。报告包含中文 Markdown、机器可读指标及内容哈希。重算不会创建 HTTP 客户端；校验原始和派生产物后重新计算指标，并要求与固定报告一致。

退出码：`0` 操作成功；`1` 输入或执行错误；`2` 读取/采集尚未完成，或报告的真实阶段验收未通过；`130` 手动中断。报告退出码 `2` 时仍会保存统计和阻塞原因。

## 第二阶段：双源逻辑赋值与成就预览

当前默认规则位于 [tag_rules_v3.json](gamepersona/rules/tag_rules_v3.json)：81 条规则覆盖十二维，包含新增引导和机制的 0.5 相关证据、0.25 弱证据，按标签并集、明确同义词和每维最大值赋分。两源重复不叠加，票数不调强度。未命中记零标签证据；两源不可用记未知；全零向量保留但不计分。

```powershell
python -m gamepersona build-features --snapshot stage2-features-v1-20261014 --rules gamepersona/rules/tag_rules_v1.json --kaggle stage1-kaggle-v3-20261014 --steamspy stage1-tags-v3-20261014 --selection stage1-selection-v3-20261014
python -m gamepersona replay-features --snapshot stage2-features-v1-20261014
python -m gamepersona probe-achievements --snapshot stage2-achievements-v1-20261014 --steam stage1-steam-20261013-01 --env-file .env
python -m gamepersona replay-achievements --snapshot stage2-achievements-v1-20261014
```

上述实测快照已存在；直接使用两条 replay 命令复核，重新生成特征或刷新成就请更换快照标识。特征生成与所有 replay 命令均不创建 HTTP 客户端，只校验实际消费的输入文件及清单哈希。特征重算使用快照内固定规则，不读取当前默认规则覆盖旧版本。

成就核验按正时长低／中／高秩分层，每组固定哈希选最多五款，读取游戏定义和玩家完整成就列表。先算单游戏解锁率，再按 `ln(1+min(小时数,100))` 加权；比较无上限及 50、100、200 小时上限。该分数只是小样本完成倾向，不是全库结果或通关证明，不使用评论样本分位。

成就采集受共享限速及重试约束；中断可复用同一 building 快照恢复，输入与账号绑定必须一致。已完成快照不重复请求，终态失败若需刷新应使用新标识。退出码 `2` 表示成就核验部分可用或无有效成就；状态与排除原因仍保存。

特征产物包括 `rules.json`、`features.json`、`metrics.json` 和中文 `report.md`；成就产物包括 `sample.json`、移除密钥／SteamID 的响应、`records.json`、指标和报告。个人样本及贡献仍是本地私有数据。边界及验收口径见 [自动规则规范](docs/STAGE2_QUALITY_TARGETS.md)，实际结果见 [第二阶段状态](docs/STAGE2_STATUS.md)。

## 第三阶段：共享评分与条件参考

本轮已固定以下三个快照；重算不联网。重新实验或读取新记录须使用新标识，不能覆盖旧报告。

```powershell
python -m gamepersona aggregate-users --snapshot stage3-aggregate-v1-20261014 --kaggle stage1-kaggle-v3-20261014 --features stage2-features-v1-20261014
python -m gamepersona build-reference --snapshot stage3-reference-v1-20261014 --aggregate stage3-aggregate-v1-20261014 --protocol docs/STAGE3_EXPERIMENT_PROTOCOL.md
python -m gamepersona score-steam --snapshot stage3-account-v1-20261014 --steam stage1-steam-20261013-01 --reference stage3-reference-v1-20261014
python -m gamepersona replay-aggregate --snapshot stage3-aggregate-v1-20261014
python -m gamepersona replay-reference --snapshot stage3-reference-v1-20261014
python -m gamepersona replay-score --snapshot stage3-account-v1-20261014
```

前三条是生成示例，本机这些快照已存在，应直接使用后三条复核。聚合约 4115 万条记录，物化 N≥3 用户，比较四种时长函数；参考在用户级 60/20/20 切分中拟合/校准/独立核验，每条件组固定抽样最多 5000 人。选择对数无封顶和固定 H/N 分组，数字门槛及边界见 [阶段三状态](docs/STAGE3_STATUS.md)。参考不足、退化、超范围和单维贡献过于集中返回 null，不偷偷回退总体分位。两个端点分别计分，混合和待定允许无完整类型。

当前网站默认使用 `stage3-reference-weight-v3-20261014`：连续 W 参考与81项引导/机制 v3 标签联合版本。W 为共同计分游戏的 `Σln(1+t)`，游戏数继续用于充分性检查；相近投入的有效参考不足则返回未知。发布与新留出核验见 [W正式模型状态](docs/PRODUCTION_W_V3_STATUS.md)，标签清单与覆盖见 [扩展状态](docs/GUIDED_MECHANICS_V3_STATUS.md)。历史快照和报告保持固定，重放使用各自保存的规则；页面、雷达和分享图显示中文名称加可读缩写。

## 第四阶段：本地网站

需要 Python 3.11+、Node 22.12+ 和当前通过实验的参考快照。先在项目根目录安装 Python 锁定依赖（本机 `.venv` 无 pip 时仍由系统 pip 管理），再构建前端：

```powershell
python -m pip --python .venv install -r requirements.lock
Set-Location web
npm.cmd ci --offline=false --cache ../.cache/npm
npm.cmd test
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe scripts/local_database.py start
.\scripts\start-local.ps1
```

打开 [本地测评网站](http://127.0.0.1:8000/)。首次数据库启动脚本只在项目 `.cache` 下载和核验官方 PostgreSQL 18.6 便携包（约385 MB），生成 `.env.web` 中的随机本地数据库密码，初始化 SCRAM 认证并仅监听 127.0.0.1:55432；不注册系统服务。若已有 PostgreSQL，可复制 `.env.web.example` 配置 DATABASE_URL 后直接运行下面的后端命令，跳过便携启动脚本。

```powershell
.\.venv\Scripts\python.exe -m uvicorn gamepersona.web.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

`.env` 或环境变量的 STEAM_API_KEY 仅由服务器读取；网站不使用操作员输入的 STEAM_ID 作为登录身份。浏览器必须通过 Steam 官方 OpenID 登录，服务器才能绑定验证后的账号并读取可见游戏。API 身份输入和旧快照不能替代真实浏览器认证。`.env.web` 指定 GAMEPERSONA_REFERENCE，重算产生新的固定报告，旧报告继续使用原结果。

报告包含六组分数条、十二维多边形雷达图、贡献与覆盖解释；未知维度留空，部分图只连接相邻已知点。PNG 使用当前报告的公开字段，包含雷达图与实际数值；不会再次评分、默认加入身份或库明细。下载仅在浏览器生成，服务器不保存 PNG。

退出即时撤销会话；“删除网站个人记录”删除网站账号关联、会话、登录事务、任务、输入和报告。已下载 PNG 和旧 CLI 产物需单独删除。网站数据保留到主动删除，不默认加入参考分布或研究。启动时数据库迁移自动执行；中断任务和临时数据库掉线可恢复。当前只交付本地服务，公网部署条件另验收。

验证命令为完整 `python -m pytest`、`web` 中 `npm.cmd test` 和构建。PostgreSQL 集成测试读取本地 `.env.web`，每次创建并清理独立测试 schema；没有该文件时相应测试明确 skip，不视为通过。`tests/browser_server.py` 是 loopback 浏览器验收替身，不得当作正式服务，正式服务没有模拟登录入口。

可用 `.venv/Scripts/python.exe scripts/local_database.py stop` 停止本项目便携数据库；先退出本地网站服务。更多实际验收、样例 PNG 与未完成项见 [阶段四状态](docs/STAGE4_STATUS.md)。

## 保存与删除

默认输出位于 `artifacts/snapshots/<快照标识>`；账号响应、规范化记录、原始文件、报告及全局 SteamSpy 缓存均在本机保存。`artifacts/cache/steamspy/` 纳入版本控制，保存本轮 3064 款游戏的公开 API 缓存（约 3.40 MB），每条包含响应及采集时间；采集器仍只复用 24 小时内的成功缓存。其余 `artifacts/` 产物、`data_source/`、`.env`、虚拟环境和测试缓存继续由 `.gitignore` 排除。

本地数据保留到你主动删除。删除个人记录时，先查看其 Steam 快照及引用该快照的候选、标签和报告 manifest，删除这些目录；原始 Kaggle 文件和来源文档不属于该个人账号记录。只在确认绝对路径位于本项目 `artifacts` 内后，使用 PowerShell `Remove-Item -LiteralPath <明确快照目录> -Recurse`。需要彻底删除全部本地产物时，明确检查后删除整个 `artifacts`。已导出到其他位置的文件需单独删除。

字段映射、清洗及指标口径见 [审计规范](docs/AUDIT_SPEC.md)。
