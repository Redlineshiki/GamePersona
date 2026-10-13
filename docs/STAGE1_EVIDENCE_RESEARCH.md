# 第一阶段字段与用途证据核查

核查日期：2026-10-13（Asia/Hong_Kong）。仅使用发布者、Kaggle、Valve 和 SteamSpy 本人的来源，以及本地 ZIP 元信息。未下载或替换数据集，未读取凭据。现有代码的证据约束见 `gamepersona/ingest.py` 的 `import_kaggle`。

## 结论及可传入参数

| 核查事项 | 结论 | 导入参数 |
|---|---|---|
| Kaggle `hours` 单位 | 作者关联目标数据集的历史采集、转换和 CSV 导出代码明确提取十进制小时；见下文固定 commit 证据 | `--hours-unit hours` 并提供下列 evidence |
| 累计时长对应时点 | 上述实现采集网页当时显示的 `hrs on record` 累计值；不是评论创建时的冻结值，没有逐行采集时间 | `--duration-time-semantics at_collection` 并提供下列 evidence |
| 本地数据集版本 | ZIP 总大小、四文件大小和打包日期均与当前 v28 信息吻合；缺少版本下载记录或官方内容校验和，保留候选 v28 | `--dataset-version unverified` |
| SteamSpy 派生特征公开免费网站用途 | 官方 API 可读及限速明确；当前取得的官方页面没有这项用途的明确许可条款 | 官方证据状态仍为 unresolved；用户非商业用途判断单独登记 |

推荐 `--hours-evidence` 文本：`作者关联目标Kaggle数据集的采集/转换/CSV导出代码 commit 41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583：review.py明确十进制小时并提取hrs on record；transform及dump保留hours不换算。原文快照 stage1-author-pipeline-evidence-20261013；docs/STAGE1_EVIDENCE_RESEARCH.md。`

推荐 `--time-evidence` 文本：`同一固定commit抓取Steam网页.vote_header .hours::text中的hrs on record累计小时，date独立解析评论日期；SQL允许保留旧采集值或替换成新采集值，未输出逐行采集时间。因此at_collection指被保存的采集观测时点，不是at_review或统一截至导出日期。原文快照 stage1-author-pipeline-evidence-20261013；docs/STAGE1_EVIDENCE_RESEARCH.md。`

这是作者公开实现的来源级字段语义证据，不能证明本地每一行由该 commit 生成，也不能证明小时数没有解析失真。本地版本仍为 unverified，数据质量限制必须和新导入快照一起记录。此前仅靠 Kaggle 总说明不能确认单位的结论，被下文新增代码证据补充。

## Kaggle 作者与平台证据

来源 [Kaggle 作者页面](https://www.kaggle.com/datasets/antonkozyriev/game-recommendations-on-steam?select=recommendations.csv)、[view API](https://www.kaggle.com/api/v1/datasets/view/antonkozyriev/game-recommendations-on-steam)、[metadata API](https://www.kaggle.com/api/v1/datasets/metadata/antonkozyriev/game-recommendations-on-steam) 和 [文件列表 API](https://www.kaggle.com/api/v1/datasets/list/antonkozyriev/game-recommendations-on-steam)，本轮均实际返回 200。

- 作者说数据包含 Steam Store 用户推荐/评论，`recommendations.csv` 表示游戏和用户的多对多关系；用户标识经过匿名化。作者声明来源是 Steam Official Store。
- view 返回 `currentVersionNumber: 28`、`lastUpdated: 2024-08-14T13:15:03.88Z`、版本注释 `Update 2024-08-14`。metadata 的许可证为 `CC0-1.0`；view 为 `CC0: Public Domain`。这记录发布者的声明，不能自动证明所有底层素材的权利。
- 作者说明未定义 `hours` 或原始 Steam 字段。metadata 返回 `data: []`，文件列表各文件返回 `columns: []`，所以本轮响应没有字段级单位或采集时点证据。网页的初始 HTML 也只有总说明和结构化数据，不能把未载入的字段说明当作已读取。
- 作者页面的 JSON-LD 指明 `version: 28`，其 distribution 指向 `download?datasetVersionNumber=28`，`contentSize: "692315526 bytes"`。没有调用下载 URL。

现有来源快照 `artifacts/snapshots/stage1-sources-20261013-verified` 归档 view 的原始响应，状态 ready；`kaggle.json` SHA-256 为 `d9fe9279e28a347242b92ff3259462e0405014a90043451a4a67f5621e247e65`。其 manifest 记录采集时间和 URL。

补充快照 `artifacts/snapshots/stage1-field-evidence-20261013` 使用 `Store.create/finish` 保存原始响应，source 为 evidence，状态 ready，并通过 `Store.verify` 全部哈希校验。`requests.json` 记录每次请求 URL、最终 URL、HTTP 状态、采集时间和原始文件名。JSON-LD 是从同快照的网页原文提取的结构化派生产物。未调用任何数据集下载 URL。

| 证据文件 | SHA-256 |
|---|---|
| kaggle_metadata.json | `e0591c7e03daaeb791a84c6616504ae7a4290bfccbfa5cfcff156f609354b365` |
| kaggle_file_list.json | `b80d4e7ab4d16a2beecc859e985d65daa69f661373a8bee508d57d8ff4f453c5` |
| kaggle_page.html | `7a0a4b37bc627b4569ad79365ca8afacff5f5a71af56b967d282da05211a8997` |
| kaggle_jsonld.json | `cbd5628f2cb54adb4557ac09471f9dbd5f0cae20ccff52b25e90855aa4cccba1` |
| valve_review_fields.html | `ba26cf2cdb9279f829bb8d6865a0bc69e27330e286665591c975b8c8eac81074` |
| requests.json | `52ad6e09f6b46f49ab6c1bb0972ac9be65af7db1b0f96ccd5ab9b0a817aebddd` |

## 本地 ZIP 与版本关联

实际检查 `data_source/archive.zip`：总大小 692,315,526 bytes，ZIP comment 为空，只有四个预期文件，没有版本说明文件。读取 ZIP 目录即可得到下表；本核查没有额外执行全量解压或 CRC 校验，导入器负责完整校验。

| 文件 | 本地未压缩大小 | 官方当前文件大小 | ZIP 时间 |
|---|---:|---:|---|
| games.csv | 4,863,790 | 4,863,790 | 2024-08-14 13:17:40 |
| games_metadata.json | 17,548,605 | 17,548,605 | 2024-08-14 13:17:40 |
| recommendations.csv | 2,023,223,067 | 2,023,223,067 | 2024-08-14 13:17:56 |
| users.csv | 193,068,018 | 193,068,018 | 2024-08-14 13:20:16 |

这些匹配支持“候选 v28”，但相同大小不能证明相同内容，ZIP 时间也不是采集时间。将导入后的文件 SHA-256 作为本地内容身份；若取得该次下载的 version=28 记录或官方对应内容哈希，再创建新证据版本确认版本。

最后的严格关联尝试仅对上文 JSON-LD 发布的 `download?datasetVersionNumber=28`、对应 API 查询版本 URL 和 API `/28` 路径发送 HEAD。2026-10-13 21:06（香港时间）三者均返回 404，无重定向、无 ETag、content-md5 或 x-goog-hash，响应实体读取字节数均为 0。未改用 GET 数据请求，也未下载数据集；不能据此断言 v28 文件不存在，只能说本轮 HEAD 未取得可比较的官方内容校验和。本地版本因此仍保留 unverified。

该次尝试归档为不可变快照 `artifacts/snapshots/stage1-version-head-evidence-20261013`，source=evidence，state=ready，并通过 Store.verify；原始请求、响应头及采集时间保存在以下文件：

| 文件 | SHA-256 |
|---|---|
| head_1.json | `2baeefa4f34b131292b77b68d2bbea82ef4c3c0bc3741228c33382ce39d30dc7` |
| head_2.json | `3d29c5d421941f3daaecbf45879fce73e7b75424607d86a0caf12afd0aa3f0dc` |
| head_3.json | `ffd5ddb94b5cc835be1832c45813eb424a00ce9c04d52cdb13930ddbc7f3f16e` |

## Valve 评论时长字段不能替代 Kaggle 映射

[Valve 官方 IUserReviewsService](https://partner.steamgames.com/doc/webapi/IUserReviewsService) 本轮实际读取 200。其 author 字段说明明确区分：

- `playtime_forever`："Lifetime playtime in the app, in minutes."
- `playtime_at_review`："Playtime when the review was written, in minutes."
- `timestamp_created`：评论创建的 Unix 时间戳。

当前官方页面注明新接口替代旧 `/appreviews`，返回字段基本相同。单凭这份 API 文档不能证明 Kaggle 作者使用哪一个字段、是否除以 60 或怎样截断/舍入。新增作者源码表明所核查的实现使用网页文本，而不是这里的分钟字段；评论日期仍不是游玩日期。

## 新增：作者身份、采集和导出实现的第一手证据

固定作者项目 commit：`41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583`，GitHub commit 元数据日期为 2023-12-01T14:25:48Z。项目目前已删除旧 processing pipeline，不能只读取当前 HEAD 判断过去没有实现。

身份链：GitHub 用户 `kaydotdev` 的公开 name 是 Anton Kozyriev；其个人网站仓库固定 commit `d01647fcac392ec3e08171c0d045640e4c393b27` 的 [个人网页源码](https://github.com/kaydotdev/antonkozyriev.me/blob/d01647fcac392ec3e08171c0d045640e4c393b27/src/routes/%2Bpage.svelte) 同时链接 `github.com/kaydotdev` 与 `kaggle.com/antonkozyriev`。作者 [推荐项目 README](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/README.md#L4) 直接链接本项目使用的目标数据集。不是仅凭同名推断作者关系。

该固定 commit 的实现链如下：

1. [review scraper](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/webcrawlers/steampowered/spiders/reviews.py#L200) 读取 `.vote_header .hours::text`，独立读取评论内容和发布日期。
2. [hours parser](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/pipeline/udf/review.py#L47) 文档明确 "Returns hours number in a decimal format."；正则为 `([\d.]+) hrs on record`，再转 float，没有分钟到小时的除法。
3. [transform](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/pipeline/transform.py#L203) 将该 parser 输出保留为 `hours`；`date` 独立解析评论发布日期。
4. [CSV export](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/pipeline/dump.py#L248) 只将 `hours` 转 DoubleType；导出 recommendations 的八个列名和顺序与本地源 schema 一致。
5. [append SQL](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/pipeline/sql/append.sql#L25) 冲突时保留旧记录；[update SQL](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/pipeline/sql/update.sql#L44) 则可把小时换成新采集值。因此只能说保留下来的采集观测时点；不同记录可能来自不同采集批次，不能统一解释成导出日期或评论日期。

Valve 官方 [Steam 评论列表](https://steamcommunity.com/app/570/reviews/?browsefilter=toprated&filterLanguage=all&l=english) 本轮返回 200，其 `.hours` 实际显示 `hrs on record`。此当前网页仅佐证来源标签，不用于把当前数值反向关联到匿名 Kaggle 用户。结合作者解析及独立日期映射，可将来源级时点口径登记为 at_collection；本地文件没有逐行采集时间及原始页面，不能核验每条记录观测日期。

### 作者实现暴露的数据质量限制

- 千位逗号：作者正则没有接受逗号。例如当前 Valve 原文 `1,583.0 hrs on record`，按该正则得到 `583.0`，而不是 `1583.0`。`10,583.0` 同样得到 `583.0`。这证明该实现存在解析风险；缺少本地每行原文和生成记录，不能断言某一行确实被如此截断，也不能从现值恢复丢失的千位。
- 失败默认零：`parse_hours_or_default(..., default=0.0)` 将无法解析的内容置零。来源中的 0.0 因而可能表示真实零，也可能表示解析失败；仅看 CSV 无法区分。第一阶段应保留零状态并把这项来源限制加入审计，不能把它计为可靠的正向时长证据。
- [导出代码](https://github.com/kaydotdev/steam-game-recommendations/blob/41acb9fbe0bcfe9d9ca6ff2300e96531ad97a583/src/pipeline/dump.py#L240) 使用 `monotonically_increasing_id()` 生成 `review_id`。该实现中的 review_id 不是 Steam 原始 recommendationid，不能当成跨数据集版本稳定键；单一快照内的重复和冲突检查仍有意义。`user_id` 由 StringIndexer 生成，不是 SteamID。
- 明确单位不意味着数值质量通过验收。未知版本、潜在千位丢失、失败零值和没有逐行采集时间分别保留，未对原始值进行猜测修复，也未执行下载来的源码。

### 作者实现证据归档

新增不可变快照 `artifacts/snapshots/stage1-author-pipeline-evidence-20261013`：source=evidence，state=ready，使用 Store.create/finish 并通过 Store.verify。原始请求和采集时间保存在 requests.json；manifest 保存固定仓库 commit、作者身份网页 commit、所有文件 SHA-256。官方评论页面原文仅留在本地私有快照，不作为公开再分发素材。

| 文件 | SHA-256 |
|---|---|
| author_identity_links.txt | `c7e67d9a9fdd49b1de612d7b20e3f8df367d7bfa40c5f6929d35b1e04ea468e2` |
| readme.txt | `c4bc38518f81815d35c5ca15d07062c5c872bb8fc97b31be3a86e6867b59ea92` |
| review_scraper.txt | `ef826afd49ae9bfb6ad4bf83f15adf69b63f43337d215b9c51ccd99347903a44` |
| review_parser.txt | `ffc5e85083f0c1108a935cf3fe941e9585f54667c00d75b255ba39b2f18a34bf` |
| transform.txt | `cb6bfce2fd82351b25b8153b8e730dfce8cec8d6b2f36ecfcd30eb6a96f655d2` |
| csv_export.txt | `bb334f41246bb703bf6e1f2967769a68adae3cba6497c61a2b09f5b06a2faeb8` |
| sql_append.txt | `06bf71287ae5c2ac7819e3f8d3fef10500154ba6041d2fbbf9ba7a136e6f091b` |
| sql_update.txt | `0a747e06bd8ee7e63d158c57443ecaddb73567710a719d36354bb813af3ecca0` |
| steam_review_page.html | `6b84427141f1c94c81da150a0aff263600a866697411b0c057b867eec6fd70a1` |
| parser_demonstration.json | `f0de52b2e004782388080080dee1236d81579f379d67270a6af06e91613c10d5` |

parser_demonstration 只重现上述正则和默认值，不加载或执行外部脚本。更多仓库、commit、tree、身份 profile 的完整原文及哈希见同快照 manifest。

## SteamSpy 官方页面与用户用途判断

来源 [官方 API 说明](https://steamspy.com/api.php) 和 [About](https://steamspy.com/about)，归档于上述 verified 快照：`steamspy_api.json` SHA-256 为 `4c602bfd1d8e5bb741ca0db1ca788f6c35bb5c56c5196522b7e5e58aafea3bf7`，`steamspy_about.json` 为 `df18c9a6729436af8d3fc0f88c54a234b80548684a6dc385b37c8f1d432b9b31`。

- API 写明每天刷新；同一信息无须 24 小时内重复请求。通常每秒一次，`all` 每 60 秒一次；tags 返回带票数的游戏标签。
- API 的 `average_forever` 和 `median_forever` 明确为分钟；它们是聚合时长，不能用于确认 Kaggle 单个用户 `hours` 的单位。
- About 说服务面向独立开发者、记者、学生和关注 PC 游戏的人，数据来自有限样本、可能缺失和错误。该用途说明没有明确授权本站的派生评分或分享图片用途。
- 本轮核查的这两个官方页面没有发现适用于公开免费网站的明确派生数据许可。API 可访问、免费访问、服务目标和非商业属性不能自行补成具体许可条款。这里是“未取得依据”，不是断言 SteamSpy 禁止此用途。

用户已在本轮明确表示，Kaggle 与 SteamSpy 的非商业用途可调取；这是运营者对本项目非商业使用的判断与授权，可以继续本地采集审计。应单独保存其适用范围，不能将其写成 SteamSpy 官方授权或扩展到商业化、原始数据公开再分发。官方派生依据状态保持未核实，待提供适用条款或权利人的说明后补充；本核查没有联系任何第三方。
