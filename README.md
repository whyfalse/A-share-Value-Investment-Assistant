# A股价值投资助手

基于 Claude Code 技能（Skills）与编排 Agent 构建的 A股投资辅助系统。它把"盘前 → 盘中 → 盘后 → 周末"的完整复盘节奏拆成可独立调用、又能相互衔接的技能，并维护一份本地宏观环境长期记忆，结合用户的持仓、自选股与关注板块，提供贯穿交易日的信息汇总与纪律核对。

## 概述

### 功能
针对 A股的价值投资 AI 助手，根据用户的个人投资偏好（持仓股、自选股、关注板块等信息），在不同时间窗口为用户进行投资辅助：盘前隔夜信息推送、盘中快速检查、盘后当日复盘、周末深度复盘，以及单只个股的技术面研判和宏观环境记忆维护。

### 核心设计原则
- **最低持有纪律**：核心持仓为中长期持股，最低持有 5 个交易日以上。任何当日新闻、宏观事件、短期波动只能用于"标记待观察"或"核对是否触及用户预设的止盈止损线"，不能单独成为买卖长期持仓的理由。
- **不构成投资建议**：所有技能输出的是"发现了什么、是否触及预设纪律线、有什么待办"，是否操作由用户自行判断，不预测走势、不给买卖结论。
- **短期机会与中长期持仓分栏**：两者判断标准完全不同（催化剂驱动 vs 基本面/估值逻辑），输出中必须分栏呈现，不混用标准。
- **宏观背景只用于校准**：宏观记忆只用于"解释现象"和"环境校准"，不能反过来驱动个股买卖结论。
- **不读取交易记录**：只使用持仓/自选股/板块的当前快照和已发生的客观事实，持有期窗口判断仅基于持仓快照中的 `buy_date` 字段。

完整边界定义见 `references/boundaries.md`。

### 限制
- 只适用于 A股（沪深京）的中长期投资（至少持股 5 个交易日），不支持港股、美股、期货期权、可转债、基金。
- 不对用户的历史交易记录（买卖流水）进行分析。
- 不进行买卖时点建议，不预测市场走势。

## 系统架构

### 编排层：investment-assistant Agent
`.claude/agents/investment-assistant.md` 是用户主动触发的编排 Agent，负责识别用户意图并路由到对应技能，本身不改变任何技能的逻辑、输入或输出。

**时间窗路由**（消解"复盘一下"这类模糊请求，按当前时刻自动路由；用户已明确指定的以用户为准）：

| 当前场景 / 时间 | 路由到的技能 |
|---|---|
| 交易日开盘前（约 8:00–9:15，集合竞价前） | `ashare-morning-brief` |
| 交易日盘中（约 9:30–15:00，典型 14:30 收盘前窗口） | `ashare-intraday-review` |
| 交易日收盘后当晚（15:00 之后） | `ashare-evening-review` |
| 周末 / 周日上午 | `ashare-weekly-review` |
| 用户点名某只个股要技术面研判 | `ashare-technical-analysis` |
| 用户要维护 / 刷新宏观背景 | `ashare-macro-context`（完整维护模式） |

**宏观记忆自动接力**：复盘/推送技能跑完后，若其输出末尾的「宏观更新队列」提示发现了 Tier 3 新事件，编排层在同一回合内自动接力调用 `ashare-macro-context` 的【队列消费模式】，把新事件即时落库，无需用户手动触发。周复盘跑完后则接力调用其【完整维护模式】，做一次彻底的全量维护。

**定时自动触发（可选）**：Agent 具备 `CronCreate` 等工具，可把复盘排成定时任务，但默认不主动创建，仅在用户明确要求时创建。定时任务触发后会先判断当天是否为 A股交易日，非交易日直接跳过。

### 24 小时信息闭环
四个日常技能首尾相接，覆盖完整 24 小时不留缝隙，并通过"待观察事项"在彼此间交棒：

```
早间推送(隔夜欧美)  →  盘中复盘(14:30 检查)  →  晚间复盘(A股+亚太收盘)  →  次日早间推送
   今日观察清单    →     盘中给出结论       →    隔夜需观察事项交棒    →    核对隔夜进展
```

周复盘则在周日清算本周积压的未结事项，并产出"下周事件预告"作为下周每日推送的起点。

### 宏观记忆单一写入者原则
`data/macro_context.json` 的唯一写入者是 `ashare-macro-context`。日常复盘/推送技能发现 Tier 3 级事件时只产出更新建议追加到 `data/macro_updates_queue.json`，由编排层接力调用 macro-context 消费队列后统一写入。协议详见 `references/tier3-event-handling.md`。

## 技能列表

### 宏观背景维护（ashare-macro-context）
维护 A股复盘所需的宏观环境背景信息，涵盖 13 大维度（政治政策、宏观经济、货币流动性、财政、汇率与跨境资本、房地产、通胀大宗、人口结构、国际形势、资本市场制度、全球央行、会议日历、长期产业热点）。按更新频率分层维护：Tier 1 慢变量约 90 天复核、Tier 2 周期变量约 30 天复核、Tier 3 事件驱动即时更新。提供完整维护与队列消费两种运行模式，并内置维度扩展机制（候选维度暂存区）。

### A股技术面分析（ashare-technical-analysis）
对单只 A股个股做纯技术面分析，综合均线、MACD、RSI、KDJ、布林带、ADX、量能、ATR、支撑阻力位、量价背离等多维指标，服务于至少持有 5 个交易日的中长期决策。附带 Python 脚本完成数据获取、指标计算与五维度加权打分（含风险否决规则），最终输出结构化中文报告。

### 盘中复盘（ashare-intraday-review）
交易日盘中（典型 14:30–14:45 收盘前窗口）的 15 分钟快速检查清单：持仓异动与纪律核对、自选股监控、宏观背景校准、大盘板块情绪、短期机会发掘、待办收尾。定位是"中继检查"而非深度复盘。

### 晚间复盘（ashare-evening-review）
交易日收盘后当晚的信息汇总与衔接：以 A股当日全天表现为主、亚太市场为辅，整理白天消息面，并承接当日盘中复盘留下的未结事项给出结论，产出"隔夜需观察事项"交棒给次日早间推送。

### 早间消息推送（ashare-morning-brief）
开盘前（典型 8:00–8:20，集合竞价前）汇总隔夜美股、欧洲及全球其他市场表现与隔夜消息（不含亚太，由前一晚晚间复盘覆盖），核对昨晚遗留的隔夜观察事项，产出"今日观察清单"交棒给当日盘中复盘。

### 周复盘（ashare-weekly-review）
周日上午（全球主要股市休市）围绕持仓、自选股、关注板块进行上一周的深度复盘：大盘回顾、周度热点汇总、持仓/自选股/板块复盘、短期机会发掘、未结事项清算、下周事件预告与重点关注。

## 项目结构

```
.claude/
  agents/investment-assistant.md   编排 Agent：意图识别、时间窗路由、自动接力、定时任务
  skills/                          六个技能，各含独立 SKILL.md 及专属 assets/references/scripts
templates/                         共享数据模板（持仓/自选股/关注板块/宏观记忆）
data/                              运行时个人数据（从模板初始化，详见 data/README.md）
references/                        跨技能共享的规则文档
README.md
```

### 编排 Agent（`.claude/agents/`）
`investment-assistant.md` 是用户主动触发的编排层，只做技能的编排调用，不更改技能的逻辑、输入参数与输出内容。

### 技能目录（`.claude/skills/`）
每个技能包含独立的 `SKILL.md` 和技能专属文件（如 `assets/` 输出模板、`references/` 详细规则、`scripts/` 脚本）。

### 共享模板（`templates/`）
存放所有技能共用的数据模板（持仓记录、自选股、关注板块、宏观记忆），从对应模板复制到 `data/` 目录后填入个人数据即可使用。模板是结构定义，应保留在版本控制中。

### 运行时数据（`data/`）
用户个人持仓、自选股、关注板块、宏观记忆等运行时数据的存放目录。属于个人数据，不应提交到版本控制（建议加入 `.gitignore`）。详见 `data/README.md`。

| 数据文件 | 从模板初始化 | 读取方 | 写入方 |
|---|---|---|---|
| `positions.json` | `templates/positions_template.json` | 四个日常技能 | 用户（手动） |
| `watchlist.json` | `templates/watchlist_template.json` | 四个日常技能 | 用户（手动） |
| `sector_watchlist.json` | `templates/sector_watchlist_template.json` | weekly-review | 用户（手动） |
| `macro_context.json` | `templates/macro_context_template.json` | 所有技能 | macro-context（唯一写入者） |
| `macro_updates_queue.json` | 运行时自动创建 | macro-context | 三个日常推送技能（追加建议） |

### 共享参考（`references/`）
跨技能共享的规则与原则文档，各技能 `SKILL.md` 引用这些文件以避免重复定义：
- `boundaries.md` — 共享边界声明（最低持有纪律、不构成投资建议、短期/中长期分栏、消息面范围、宏观引用边界、不读取交易记录）
- `message-classification.md` — 消息面四类标准分类（固定顺序）
- `tier3-event-handling.md` — Tier 3 事件队列处理协议与单一写入者原则
- `holding-discipline.md` — 最低持有纪律（内容已并入 boundaries.md，保留以向后兼容）

## 快速开始

1. 将所需模板复制到 `data/` 目录并填入个人数据：

```bash
cp templates/positions_template.json data/positions.json
cp templates/watchlist_template.json data/watchlist.json
cp templates/sector_watchlist_template.json data/sector_watchlist.json
cp templates/macro_context_template.json data/macro_context.json
```

2. 编辑各文件填入实际持仓、自选股、关注板块数据。

3. 通过 `investment-assistant` Agent 触发复盘，或直接调用对应技能。模糊请求（如"复盘一下"）会按当前时刻自动路由到合适的技能。

> 技术面分析技能（`ashare-technical-analysis`）的数据获取脚本默认使用 akshare，首次使用需 `pip install akshare`；也可复制 `config/data_source.example.yaml` 为 `data_source.yaml` 配置 tushare token 或本地 CSV。
