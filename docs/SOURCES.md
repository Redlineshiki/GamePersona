# 数据来源核验记录

记录日期：2026-10-13。预期使用场景：公开免费的个人 Steam 游戏偏好测评网站。

实际获取的说明与响应保存在本机 `artifacts/snapshots/stage1-sources-20261013`；每项记录包含 URL、获取状态、采集时间、原始内容和 SHA-256。

## Kaggle

- 入口：[Game Recommendations on Steam](https://www.kaggle.com/datasets/antonkozyriev/game-recommendations-on-steam)。
- 发布者：Anton Kozyriev；元数据接口返回当前版本 28、最后更新时间 2024-08-14、许可证声明 CC0: Public Domain。
- 作者说明包含游戏与附加内容、匿名用户及评论记录。匿名用户 ID 不等于 SteamID；评论样本不等于完整游戏库。
- 文件清单为 `games.csv`、`games_metadata.json`、`users.csv`、`recommendations.csv`。本地文件仍在下载中，未将当前线上版本自动赋予本地快照。
- 许可证声明是发布者提供的证据。底层第三方素材权利另行考虑，首版不公开再分发游戏描述、原始评论或原始用户样本。
- `hours` 单位及累计时长对应时间尚未取得充分的字段级证据，保持未核实。评论日期不能作为游玩日期。

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
- API 可用性已实测；公开免费网站长期使用、派生特征和分享图片用途的许可依据仍未明确，保留为阶段阻塞项。
- 不将 SteamSpy 平均游玩时长当作玩家累计时长或游戏典型长度修正。

## 下一阶段质量目标登记

第二阶段需在独立核验前登记按维度、游戏类别和长尾情况划分的覆盖目标、未知率、人工一致性及规则误差；记录调参集和独立核验集的划分。第一阶段没有冻结这些数值，也没有生成八维特征或参考分布。
