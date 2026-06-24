# A股价值投资助手

## 概述
### 功能
针对A股的价值投资AI助手，根据用户的个人投资偏好（持仓股、自选股、关注板块等信息），为用户进行投资辅助。

### 限制

- 只适用于A股的中长期投资（至少持股5个交易日）。
- 不会对用户的交易记录进行分析。
- 不会进行买卖建议。

## 技能列表

### 宏观背景维护（ashare-macro-context）

### A股技术面分析（ashare-technical-analysis）

### 盘中复盘报告（ashare-intraday-review）

### 晚间复盘报告（ashare-evening-review）

### 早间消息推送（ashare-morning-brief）

### 每周复盘报告（ashare-weekly-review）

## 项目结构

### 共享模板 (`templates/`)
存放所有技能共用的数据模板（持仓记录、自选股、短期机会、宏观记忆、关注板块），从对应模板复制到 `data/` 目录后填入个人数据即可使用。

### 运行时数据 (`data/`)
用户个人持仓、自选股、宏观记忆等运行时数据的存放目录。详见 `data/README.md`。

### 共享参考 (`references/`)
跨技能共享的规则与原则文档（最低持有纪律、消息面分类标准、Tier 3 事件处理协议），各技能 SKILL.md 中引用这些共享文件以避免重复定义。

### 技能目录 (`.claude/skills/`)
每个技能包含独立的 SKILL.md 和技能专属的 assets/ 文件（如输出模板）。
