# data-source-config.json 结构说明

本文件定义 `ashare-data-source-config` 写入 auto-memory 的 `data-source-config.json` 结构。各复盘技能按 `references/data-source-priority.md` 读取本配置取数。

## 顶层结构

```json
{
  "version": 1,
  "generated_at": "YYYY-MM-DD",
  "next_review_due": "YYYY-MM-DD",
  "probe_summary": "一句话:本次探测到哪些工具、各自可用状态",
  "tools": [ ... ],
  "routing": { ... }
}
```

- `version`:配置结构版本号,结构有破坏性变更时递增。
- `generated_at`:本次完整探测编排的日期(绝对日期)。
- `next_review_due`:建议下次重新完整探测的日期。工具环境通常较稳,默认给 30 天;轻量校验每次复盘前都会跑,过期只是兜底。
- `probe_summary`:人类可读的一句话总结。
- `tools`:探测到的工具清单(下节)。
- `routing`:数据类型 → 工具链的编排映射(下节)。

## tools[] — 探测到的工具

每个工具一条:

```json
{
  "id": "wind_mcp",
  "kind": "professional | local_script | web_search",
  "invoke": "skill:wind-mcp-skill | mcp:工具名 | script:相对路径 | builtin:WebSearch",
  "status": "available | blocked | unavailable | unverified",
  "status_note": "blocked/unavailable 时的原因(认证/额度/网络/依赖缺失等)",
  "markets": ["A股","港股","美股","基金","指数","债券","宏观EDB","公告新闻"],
  "not_covered": ["日股","欧股","汇率","期货","加密货币"],
  "data_types": ["行情","K线","财务","资金流向","估值","股东","事件","公告","新闻","宏观指标"],
  "verified_by": "最小试探调用的内容或'描述文档'"
}
```

- `markets` / `not_covered`:**关键字段**。很多专业工具有明确不覆盖的市场,编排时据此把这些市场路由到联网搜索兜底。
- `status`:`available` 才能进 `routing` 的 primary;`blocked`(认证/额度/网络可恢复)可作降级备选并注明;`unavailable` 不编入;`unverified` 仅凭描述、未试探成功的能力。

## routing — 数据类型到工具链的编排

按数据类型分桶,每桶一条有序工具链(取到即停):

```json
{
  "<桶名>": {
    "primary": "tool_id",
    "fallbacks": ["tool_id", ...],
    "notes": "口径/限制/兜底诚实声明要求"
  }
}
```

推荐覆盖的桶(按实际环境增减):

| 桶名 | 含义 |
|---|---|
| `cn_equity_quote` | A股行情/K线/分钟线/估值/资金流向等结构化数值 |
| `cn_equity_fundamental` | A股财务基本面/股东/事件 |
| `hk_us_equity` | 港股/美股结构化数值(若有专业源) |
| `fund_index_bond` | 基金/ETF/指数/债券数值(若有专业源) |
| `cn_tech_daily` | A股技术指标计算用日线(技术引擎专用,通常本地脚本) |
| `macro_indicator` | 宏观经济指标(GDP/CPI/PPI/PMI/社融/利率等) |
| `announcement_doc` | 公告/财报文档 |
| `news_policy` | 消息资讯/新闻/政策/事件(专业接口+搜索交叉印证) |
| `overseas_uncovered` | 专业工具不覆盖的市场(日股/欧股/汇率/隔夜外盘),只能联网搜索、仅采信定性信息 |

### 编排纪律(写进每桶 notes 的依据)

- **结构化数值类**(quote/fundamental/fund/index/bond/macro/tech_daily):能用专业工具就绝不用搜索凑数字;专业工具字段缺失按各技能降级规则如实声明,不编造。联网搜索若作兜底,notes 须写明"只采信定性信息(涨跌/方向/大致区间),精确数字注明未经专业源核对"。
- **消息资讯类**(news_policy / announcement_doc):默认多工具组合、交叉印证,以专业/官方来源为准,搜索补时效广度,不只用单一搜索。
- **未覆盖市场**(overseas_uncovered):明确无专业源,只能搜索兜底,精确数字不当可靠数据填报。

## 最小示例(仅示意结构,实际以探测结果为准)

```json
{
  "version": 1,
  "generated_at": "2026-06-26",
  "next_review_due": "2026-07-26",
  "probe_summary": "Wind MCP 可用(A股/港股/美股/基金/指数/债券/公告/宏观),akshare 本地脚本就绪,联网搜索三件套可用",
  "tools": [
    {"id":"wind_mcp","kind":"professional","invoke":"skill:wind-mcp-skill","status":"available","markets":["A股","港股","美股","基金","指数","债券","宏观EDB","公告新闻"],"not_covered":["日股","欧股","汇率","期货","加密货币"],"data_types":["行情","K线","财务","股东","事件","公告","新闻","宏观指标"],"verified_by":"查贵州茅台最新价"},
    {"id":"web_search","kind":"web_search","invoke":"builtin:WebSearch","status":"available","markets":["全球"],"not_covered":[],"data_types":["新闻","定性行情"],"verified_by":"描述文档"}
  ],
  "routing": {
    "cn_equity_quote": {"primary":"wind_mcp","fallbacks":["web_search"],"notes":"精确数值优先Wind;搜索兜底仅采信定性信息"},
    "cn_tech_daily": {"primary":"wind_mcp","fallbacks":["web_search"],"notes":"技术引擎日线优先专业金融工具;不可用则走本地Python行情包;都不可用时联网搜索兜底"},
    "macro_indicator": {"primary":"wind_mcp","fallbacks":["web_search"],"notes":"优先Wind economic_data;搜索仅补定性"},
    "news_policy": {"primary":"wind_mcp","fallbacks":["web_search"],"notes":"Wind financial_news拿可核对来源+联网搜索补时效广度,交叉印证"},
    "overseas_uncovered": {"primary":"web_search","fallbacks":[],"notes":"日股/欧股/汇率Wind不覆盖,只能联网搜索,精确数字注明未经专业源核对"}
  }
}
```
