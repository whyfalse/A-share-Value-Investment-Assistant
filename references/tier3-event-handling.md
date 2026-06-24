# Tier 3 事件驱动变量处理协议

## 定义

Tier 3 事件驱动变量属于宏观环境记忆中的"发生时即时更新"层，不设固定复核周期，需标注具体日期。

典型例子：央行议息决议、重要会议结论、地缘政治突发事件、关税/出口管制变动、重大人事变动。

## 各技能的处理协议

### 日常复盘/推送技能 (intraday-review, evening-review, morning-brief)

当发现 Tier 3 级别的新事件时：

1. 直接更新 `data/macro_context.json`（本地宏观记忆文件），无需用户确认
2. 判断新信息归属的类别代码（参照 macro-context 的 A-M 框架，如 A_政治与政策、I_国际形势、K_全球主要央行政策等）
3. **仅作事实记录，不据此下操作结论**
4. 更新协议：
   - 若匹配已有条目：覆盖式修订 `summary`，将旧 `summary` 推入 `history[]`，更新 `last_updated`（和 `next_review_due` 如适用）
   - 若为全新事实且现有条目无法覆盖：先记入 `candidates` 数组（标注 `first_noted`、`rationale`、`proposed_category`），不新建正式条目——正式条目的转正由 macro-context 或 weekly-review 负责
   - 若无法确定归属类别：仍须记录，类别暂用最接近的或标记待归类，不能因分类不确定就丢弃信息

### 周复盘 (weekly-review)

1. 核对本周每日复盘已自动写入的宏观记忆更新，做一致性复查
2. 统一核实本周热点新闻中是否还有遗漏的 Tier 3 级事件，通过 `ashare-macro-context` 的维护流程完成补充写入
3. 处理 `candidates` 数组中的候选项：转正/淘汰/合并决定

### 宏观背景维护 (macro-context)

1. 维护流程中优先处理 Tier 3 事件驱动类的新增/突发情况
2. 更新 `summary` 为覆盖式修订，旧内容放入 `history` 数组
3. `next_review_due` 可为 null（不设固定复核周期，或按"下次同类事件日期"设定）

## 硬边界

Tier 3 事件在任何复盘/推送技能中 **只能用于"解释现象"和"直接更新事实记录"**，严禁作为当日/当周买卖操作的直接依据。宏观记忆的更新属于事实记录，不构成操作建议。
