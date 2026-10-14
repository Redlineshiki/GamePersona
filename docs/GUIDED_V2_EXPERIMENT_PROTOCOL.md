# 引导标签 v2 重算协议

2026-10-14（Asia/Hong_Kong），在本轮聚合/参考实验之前固定。

用户确认把引导扩展清单中的0.25弱证据全部纳入。v2新增8个0.5相关标签（On-Rails Shooter、Precision Platformer、Puzzle Platformer、Hidden Object、Sokoban、Escape Room、Tower Defense、Rhythm）与6个0.25弱标签（Platformer、2D Platformer、3D Platformer、Puzzle、Visual Novel、Interactive Fiction）。同维取最大值，跨来源重复不叠加。Point & Click、Score Attack不在确认的清单内。其他十一个维度的规则保持v1内容。

固定输入：stage1-kaggle-v3-20261014、stage1-tags-v3-20261014、stage1-selection-v3-20261014；特征stage2-features-guided-v2-20261014；规则tag-rules-v2-guided，共62项。全量聚合stage3-aggregate-guided-v2-20261014；参考stage3-reference-guided-v2-20261014。

聚合、评分、参考候选、条件分组和工程门槛沿用STAGE3_EXPERIMENT_PROTOCOL.md：四种时长函数；固定/分位分组；基线充分性及预声明单因素对照；通过时优先简单基线。不会将扩展后的G证据套入旧分布，也不会通过降低门槛让新版本通过。

切分和抽样沿用固定SHA-256定义。原评价切分曾用于v1工程验证，这次是同一固定数据上的版本回归评价，不能称为新收集的盲测或心理测量效度证据。先按校准选择并冻结新模型/参考，再执行评价；评价失败不据此回调标签或门槛。

输出完整特征覆盖、SQL/Python数值对齐、小时扰动支持及版本重算检查，并生成示例账号新报告。报告核查每款新增G贡献与规则来源。正式网站采用验收通过的新参考时，新测评生成新报告；已有报告保留固定版本。

风险：Rhythm可能用于非音乐游戏，Platformer可能用于自由探索；弱证据不证明线性或教程引导。此次纳入是用户确认的标签支持范围，不宣称机制真值。沿用固定N/H分组，已发现的组边界跳变不属于本次标签扩展修复；其他平滑参考实验不自动并入生产。
