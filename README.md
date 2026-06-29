# A股价值投资助手

基于 Claude Code 技能体系构建的 A股投资辅助系统。覆盖"盘前→盘中→盘后→周末"完整周期，维护本地宏观记忆，结合持仓/自选股/板块，提供贯穿交易日的纪律核对与信息汇总。

## 设计原则

- **核心持股纪律**：以投资逻辑（thesis）是否发生实质性变化为持有/卖出判断依据，短期消息/技术信号只能标记观察，不能单独驱动买卖
- **不构成投资建议**：只输出"发现了什么、有什么待办"，不预测走势
- **短/中长期分栏**：催化剂驱动与基本面驱动分开呈现，不混用判断标准
- **宏观只做校准**：宏观背景用于解释现象和环境校准，不反向驱动个股买卖结论
- **单一写入者**：`macro_context.json` 只有 `ashare-macro-context` 可写；其他技能只追加队列建议

完整边界见 `references/boundaries.md`。

## 系统架构

```
用户触发 / 定时调度
        │
        ▼
┌───────────────────────────────┐
│  investment-assistant (编排层) │  意图识别 · 时间窗路由 · 自动接力
└──────────────┬────────────────┘
               │
   ┌───────────┼───────────┐
   ▼           ▼           ▼
┌──────┐  ┌──────┐  ┌──────────┐
│ 复盘  │  │ 分析  │  │ 宏观记忆  │
│ 技能  │  │ 技能  │  │ 维护技能  │
└──┬───┘  └──────┘  └────┬─────┘
   │                      │
   │  Tier 3 事件追加队列  │
   ├─────────────────────►│
   │                      │
   ▼                      ▼
┌─────────────────────────────────┐
│         本地数据层               │
│  positions.json  watchlist.json │
│  macro_context.json  queue.json │
└─────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│  定时调度器 (run_review.py)      │
│  交易日判断 · 无头调用 · 邮件推送 │
│  数据看板渲染 (可选)              │
└─────────────────────────────────┘
```

## 24 小时信息闭环

| 时段 | 技能 | 做什么 |
|---|---|---|
| 08:00–09:15 盘前 | `ashare-morning-brief` | 隔夜美股/欧洲/全球汇总，核对隔夜观察事项，产出今日观察清单 |
| 14:20–15:00 盘中 | `ashare-intraday-review` | 15 分钟快速检查：持仓异动、纪律核对、板块情绪、短期机会 |
| 17:00–23:30 盘后 | `ashare-evening-review` | A股全天+亚太收盘复盘，白天消息面整理，产出隔夜观察事项交棒 |
| 周日 09:00–12:00 | `ashare-weekly-review` | 周度深度复盘：大盘/持仓/板块/未结事项清算，下周事件预告 |

四个技能首尾衔接，通过"待观察事项"在彼此间交棒。周复盘清算本周积压事项，产出下周预告作为新一周的起点。

## 技能一览

| 技能 | 触发方式 | 职责 |
|---|---|---|
| `ashare-morning-brief` | 时间窗 / 手动 | 盘前隔夜推送 |
| `ashare-intraday-review` | 时间窗 / 手动 | 盘中快速检查 |
| `ashare-evening-review` | 时间窗 / 手动 | 盘后深度复盘 |
| `ashare-weekly-review` | 时间窗 / 手动 | 周末深度复盘 |
| `ashare-technical-analysis` | 用户点名个股 | 多维技术指标综合评分（均线/MACD/RSI/布林带/量能等） |
| `ashare-macro-context` | 手动 / 自动接力 | 13 维度宏观记忆维护（完整维护 & 队列消费两种模式） |
| `ashare-dashboard` | 自动接力 | 复盘报告 → 移动端数据看板 HTML |
| `ashare-data-source-config` | 手动 | 探测本地可用的金融数据工具，生成取数优先级配置 |

**自动接力**：复盘技能跑完后，编排层检查输出末尾的宏观更新队列，有 Tier 3 新事件时自动接力 `ashare-macro-context` 消费队列。周复盘后自动触发完整维护模式。数据看板开启时，复盘后自动接力 `ashare-dashboard` 生成 HTML 看板。

## 定时调度 & 邮件推送

`scheduler/run_review.py` — 被 cron/任务计划按固定时刻拉起：

1. 按当前时间命中时间窗 → 选出对应技能
2. 判断当天是否 A股交易日（akshare 交易日历，支持退化为工作日判断）
3. 无头调用 Claude Code 执行技能
4. 通过 SMTP 发送报告到配置邮箱
5. 可选：自动生成数据看板 HTML 作为邮件正文

```bash
# 按当前时间自动选技能
python scheduler/run_review.py

# 强制指定技能
python scheduler/run_review.py --skill ashare-evening-review

# 调试：只判断不执行
python scheduler/run_review.py --dry-run
```

配置文件 `scheduler/config.yaml`（从 `config.example.yaml` 复制修改）：

```yaml
dashboard:
  enabled: true    # 是否生成数据看板 HTML (关闭则发纯文本)
email:
  enabled: true    # 是否发送邮件
```

## 目录结构

```
.claude/agents/      编排 Agent（investment-assistant）
.claude/skills/      七个技能，各含 SKILL.md 及专属资源
data/                运行时个人数据（持仓/自选股/宏观记忆，不入库）
output/              技能输出产物（报告/看板/技术缓存）
references/          跨技能共享规则（边界/消息分类/Tier 3 协议/技术深度指南）
scheduler/           定时调度入口 + 邮件模块 + 配置文件
templates/           数据模板（从模板复制到 data/ 初始化）
```
