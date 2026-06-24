# Runtime Data Convention

本目录是A股投资技能共用的运行时用户数据存放位置。

## 文件清单

| 数据文件 | 从模板初始化 | 读取方 | 写入方 |
|---|---|---|---|
| `positions.json` | `../templates/positions_template.json` | intraday-review, evening-review, morning-brief, weekly-review | 用户(手动) |
| `watchlist.json` | `../templates/watchlist_template.json` | intraday-review, evening-review, morning-brief, weekly-review | 用户(手动) |
| `macro_context.json` | `../templates/macro_context_template.json` | 所有技能 | macro-context, weekly-review |
| `sector_watchlist.json` | `../templates/sector_watchlist_template.json` | weekly-review | 用户(手动), weekly-review |

## 初始化

将对应模板复制到本目录并填入个人数据:

```bash
cp ../templates/positions_template.json ./positions.json
# 然后编辑 positions.json 填入实际持仓数据
```

## 原则

- `data/` 目录下的文件是个人运行时数据，不应提交到版本控制（建议加入 `.gitignore`）
- `../templates/` 中的模板是结构定义，应保留在版本控制中
- 各技能读取 `data/` 文件，但只有以下情况会写入：
  - `ashare-macro-context` 写入 `macro_context.json`
  - `ashare-weekly-review` 写入 `macro_context.json`
- `ashare-intraday-review` 只读取 `positions.json`/`watchlist.json` 做盘中核对，并对短期机会做当日发掘式输出。
