# 明确竞技标签的合作上限 v4

2026-10-14（Asia/Hong_Kong）。用户明确选择：命中Competitive或e-sports时，合作权重上限0.5；仅PvP不触发。继承v3全部81项标签映射、引导和机制扩展。

版本为tag-rules-v4-competitive-coop-cap，位于gamepersona/rules/tag_rules_v4.json。先按每维最大标签权重赋值，再应用合作上限。Competitive/e-sports沿用明确同义词和大小写/空白规范化；并集中的任一可用来源可以触发。只有正票数SteamSpy标签才进入上游证据集合。

Co-op/Online Co-Op等从1降到0.5；原Team-Based的0.5保持0.5；没有合作证据仍为0。竞争及其他十个维度不变。条件上限是用户选择的解释规则，不是实际合作时长推断。

特征中保留原标签权重和来源，adjustments记录最终上限及触发标签；合作匹配理由附上限说明，以便现有私人贡献页面解释最终权重。来源并集可能新增竞技触发而降低合作，所以v4的完整性检查使用“经过并集条件上限后的单源值”检查；v1-v3仍保持原最大值和单调性检查、原输出结构及固定快照重算。

本侧聊只新增显式可选v4，不切换默认规则、网站参考、W发布配置或旧报告，避免干扰主聊天正在进行的W/v3发布。正式采用v4时需以新规则生成特征，再重算所有参考用户证据和W参考，验证后发布新的模型/参考版本；不能把v4账号证据直接套入v3参考。

显式生成特征：

```powershell
.\.venv\Scripts\python.exe -m gamepersona build-features --snapshot stage2-features-competitive-coop-v4-20261014 --kaggle stage1-kaggle-v3-20261014 --steamspy stage1-tags-v3-20261014 --selection stage1-selection-v3-20261014 --rules gamepersona/rules/tag_rules_v4.json
.\.venv\Scripts\python.exe -m gamepersona replay-features --snapshot stage2-features-competitive-coop-v4-20261014
```

## 本轮核验

新增及已有特征测试23项通过。v4产物3064款游戏、110304项逐维完整性检查全部通过；85款游戏的合作支持从1降至0.5，其他十一个维度逐游戏与v3完全一致。AppID 730（CS:GO/CS2）合作1→0.5，竞争1、社交0.5不变；《黑魂3》《为了吾王2》《消逝的光芒》的合作值保持原值。

v4新特征快照与旧v3特征快照的replay-features均返回identical。此核验确认规则与特征，未将v4证据套入旧参考生成正式分位，未切换默认规则或主聊天的发布配置。
