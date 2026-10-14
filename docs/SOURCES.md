# 数据来源核验记录

记录日期：2026-10-13。预期使用场景：公开免费的个人 Steam 游戏偏好测评网站。

本轮实际获取的说明与响应保存在本机 `artifacts/snapshots/stage1-sources-20261013-verified`；六项来源均成功获取，每项记录包含 URL、获取状态、采集时间、原始内容和 SHA-256。字段及作者代码另有固定证据快照，见 [字段与用途核查](STAGE1_EVIDENCE_RESEARCH.md)。

## Kaggle

- 入口：[Game Recommendations on Steam](https://www.kaggle.com/datasets/antonkozyriev/game-recommendations-on-steam)。
- 发布者：Anton Kozyriev；元数据接口返回当前版本 28、最后更新时间 2024-08-14、许可证声明 CC0: Public Domain。
- 作者说明包含游戏与附加内容、匿名用户及评论记录。匿名用户 ID 不等于 SteamID；评论样本不等于完整游戏库。
- 文件清单为 `games.csv`、`games_metadata.json`、`users.csv`、`recommendations.csv`。本地 ZIP 已完整下载并通过 CRC 和全量导入；总大小、四文件大小及打包日期与 v28 吻合，严格版本身份仍未核实，内容已用 SHA-256 固定。
- 许可证声明是发布者提供的证据。底层第三方素材权利另行考虑，首版不公开再分发游戏描述、原始评论或原始用户样本。
- 新取得作者公开采集、转换与导出代码证据：`hours` 为十进制小时，来自采集网页时显示的累计值；逐行采集时间没有保留，不能将打包日期作为共同截至时点。评论日期不能作为游玩日期，也不能将时长当作评论时冻结值。
- 作者历史解析器可能丢失千位逗号前的数字，失败默认零；单位核实不代表来源数值全部准确。`review_id` 是导出生成标识，不是跨版本稳定的 Steam 原始评论 ID。代码原文、固定 commit 与适用边界见上述核查记录。

## Steam Web API

- [接口概览](https://partner.steamgames.com/doc/webapi_overview) 区分公开 API 主机和发布者合作方主机；本工程使用 `api.steampowered.com`。
- [GetOwnedGames](https://partner.steamgames.com/doc/webapi/IPlayerService) 返回结果受游戏详情可见性限制；明确传入已玩免费游戏包含参数。
- [使用条件](https://steamcommunity.com/dev/apiterms) 已归档：按用户请求读取、密钥保密、告知保存内容和所在地、落实隐私说明、遵守调用限制。
- 第一阶段使用运营者配置的授权 SteamID 检验读取；[OpenID 身份验证](https://partner.steamgames.com/doc/features/auth) 留到第四阶段。身份验证和游戏数据可见性是不同条件。
- 更新本地凭据后，已成功读取授权账号的 136 条记录，包含 117 条正时长和 19 条零时长，未发现异常或冲突记录。元数据匹配及完整标签覆盖需要对应来源快照，不从离线样本推断线上覆盖。
- 预期站点地址为 [GamePersona](https://gamepersona.niumode.workers.dev/)，实际 HTTP 检查返回 200；第一阶段读取结果保存在本机。

## SteamSpy

- [API 说明](https://steamspy.com/api.php) 已归档，普通请求最多每秒一次；数据每日更新，同一信息不应在 24 小时内重复获取。
- [来源说明](https://steamspy.com/about) 记录了采样及缺失限制，来源的统计数据不作为全体玩家的精确真值。
- 实际 AppID 570 详情请求成功，取得 20 个标签，原文、票数、时间和请求状态保存在 `stage1-live-spy-probe` 快照中。这只是单游戏探测。
- 授权账号 136 个 AppID 已全部完成采集，114 个有可用标签，22 个返回无标签。单账号标签覆盖为 83.82%，已知正时长标签覆盖为 91.47%；不能替代全量离线覆盖或八维可计分覆盖。
- 本轮在获准常规网络环境下完成 3064 款真实候选采集：2975 款有可用标签，89 款无标签，无请求失败；基础 3000 款的标签覆盖为 97.73%。正式标签快照 `stage1-tags-20261013-evidenced` 和完整报告可离线复核。用户已明确同意 Kaggle 与 SteamSpy 的非商业调取，判断和本地审计范围保存在 `stage1-operator-scope-20261013`；官方派生用途依据仍单独记为未核实，不将运营者判断写成 SteamSpy 官方条款。
- 不将 SteamSpy 平均游玩时长当作玩家累计时长或游戏典型长度修正。

## 第二阶段规则与成就来源

按用户确认的方案，第二阶段取消人工标注与人工误差门槛，改为双源逻辑标签十二维支持程度及自动执行验收，见 [规则规范](STAGE2_QUALITY_TARGETS.md)。同一标签不因两源出现重复加分，票数不直接换算强度，非命中零值不表示机制不存在。第一阶段历史快照不改写。

独立成就小样本使用 Valve 的 [GetSchemaForGame / GetPlayerAchievements](https://partner.steamgames.com/doc/webapi/ISteamUserStats)；实现采用 `api.steampowered.com` 的普通用户 Web API 端点，以已配置的授权账号读取。完整成就定义与玩家列表按名称匹配后计算解锁率，按累计小时加权；不使用 SteamSpy 平均时长、全球成就稀有度或匿名 Kaggle 用户映射。实际核验与边界见 [第二阶段状态](STAGE2_STATUS.md)。
