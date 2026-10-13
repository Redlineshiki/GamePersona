# GamePersona：第一阶段数据审计

本工程实现 `projectplan.txt` 第 7.1 节的本地审计工具。输出用于准备八维特征模型，不产生玩家分数。真实阶段验收与软件测试分别记录，当前结果见 [实施状态](docs/STAGE1_STATUS.md)。

## 安装与测试

在项目根目录使用 Python 3.11 或以上版本（本机已验证 Python 3.14）：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pytest
python -m gamepersona --help
```

依赖全部固定版本；执行模块不需要安装项目本身。在本环境中虚拟环境的 ensurepip 受临时目录权限影响，已使用系统 pip 的 `--python .venv` 功能安装锁定依赖；已有 `.venv\Scripts\python.exe` 可直接运行。

## 运行顺序

以下快照名称是示例。使用已存在的快照标识不会重新导入或刷新来源；更换数据、证据或配置时使用新标识。命令没有 Kaggle 数据下载功能，请等待现有下载完成。

### 1. 本地导入

```powershell
python -m gamepersona import --source data_source/archive.zip --snapshot kaggle-local-01
```

也支持包含 `games.csv`、`games_metadata.json`、`users.csv`、`recommendations.csv` 的目录。ZIP 会先做完整 CRC 校验，再提取这四个文件；支持 ZIP64，拒绝路径穿越、重复文件名及未完成下载。

默认不根据 `hours` 字段名推断单位，保留原值但不生成小时数。核实来源口径后，可在新快照中显式登记证据：

```powershell
python -m gamepersona import --source data_source/archive.zip --snapshot kaggle-verified-01 --dataset-version 28 --hours-unit hours --hours-evidence "经核实的来源 URL 或文档位置及结论" --duration-time-semantics at_collection --time-evidence "经核实的累计时长时间口径依据"
```

上述 `hours` 和 `at_collection` 仅演示参数，**不是当前已确认的 Kaggle 结论**。时间语义支持 `unverified`、`at_collection`、`at_review`。来源版本必须与本地文件的下载记录相符；当前线上版本不自动代表本地文件版本。

默认 DuckDB 内存上限 2 GiB、4 个线程，可通过 `--memory-limit` 和 `--threads` 修改。数据流式读取，并允许聚合溢写到快照目录的 `spill`。原始文件、数据库和 Parquet 会额外占用磁盘空间。

### 2. 来源证据与许可

```powershell
python -m gamepersona verify-sources --snapshot sources-01
```

此命令只获取说明和元数据，不下载 Kaggle 文件。保存作者许可证声明、接口说明和 Steam 使用条件。SteamSpy API 公开可访问并不自动证明公开免费网站长期使用及派生产物用途已获许可，因此默认保留此阻塞项。

获得适用依据后，可以另建来源快照并提交本地 JSON 核验记录：

```json
{
  "steamspy_public_free_use": {
    "status": "verified",
    "evidence": "适用公开许可 URL 或本地书面许可位置",
    "rationale": "说明为何覆盖公开免费的测评、派生特征及分享图片"
  }
}
```

```powershell
python -m gamepersona verify-sources --snapshot sources-reviewed-01 --review-file permission-review.json
```

工具保存该人工判断及依据，不代替许可判断，也不会自行联系来源作者。来源说明获取失败仍保留为阻塞项。公开上线前落实隐私政策、保存说明和删除机制是第四阶段的交付条件。

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

未准备好账号、标签或来源快照时，可以只传 `--kaggle` 生成明确缺少实测项的离线报告。报告包含中文 Markdown、机器可读指标及内容哈希。重算不会创建 HTTP 客户端；校验原始和派生产物后重新计算指标，并要求与固定报告一致。

退出码：`0` 操作成功；`1` 输入或执行错误；`2` 读取/采集尚未完成，或报告的真实阶段验收未通过；`130` 手动中断。报告退出码 `2` 时仍会保存统计和阻塞原因。

## 保存与删除

默认输出位于 `artifacts/snapshots/<快照标识>`；账号响应、规范化记录、原始文件、报告及全局 SteamSpy 缓存均在本机保存。`artifacts/`、`data_source/`、`.env`、虚拟环境和测试缓存已列入 `.gitignore`。根目录没有 Git 初始化时，忽略文件仍用于后续接入版本控制。

本地数据保留到你主动删除。删除个人记录时，先查看其 Steam 快照及引用该快照的候选、标签和报告 manifest，删除这些目录；原始 Kaggle 文件和来源文档不属于该个人账号记录。只在确认绝对路径位于本项目 `artifacts` 内后，使用 PowerShell `Remove-Item -LiteralPath <明确快照目录> -Recurse`。需要彻底删除全部本地产物时，明确检查后删除整个 `artifacts`。已导出到其他位置的文件需单独删除。

字段映射、清洗及指标口径见 [审计规范](docs/AUDIT_SPEC.md)。
