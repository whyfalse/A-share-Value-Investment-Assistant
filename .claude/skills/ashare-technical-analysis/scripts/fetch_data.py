#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_data.py — A股历史日线数据获取与标准化

职责:
1. 把用户输入的股票代码/名称标准化为 6位代码 + 交易所
2. 按 config/data_source.yaml 中配置的优先级,依次尝试数据源,直到成功
3. 把不同数据源返回的字段统一成标准列: date, open, high, low, close, volume, amount, turnover, pct_chg
4. 做基础数据质量检查(历史长度是否够、是否疑似停牌、是否ST、近期是否频繁涨跌停)
5. 可选抓取基准指数(默认沪深300)用于后续相对强弱计算
6. 输出: 标准化CSV + 一份metadata JSON(同时打印到stdout,方便直接读取)

用法示例:
    python fetch_data.py --code 600519 --out-dir ./output
    python fetch_data.py --code 000001.SZ --start 2023-01-01 --config ./my_config.yaml
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

import pandas as pd
import yaml

STANDARD_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"]


# ----------------------------------------------------------------------------
# 代码标准化
# ----------------------------------------------------------------------------
def normalize_code(raw: str):
    """把用户输入标准化为 (code6, exchange)。exchange in {SH, SZ, BJ}。
    支持输入形式: 600519 / 600519.SH / SH600519 / sh600519
    若无法识别交易所,按A股常见规则从代码段推断:
        6xx/68x -> SH(沪市主板/科创板)
        0xx/3xx -> SZ(深市主板/创业板)
        8xx/4xx -> BJ(北交所)
    """
    raw = raw.strip().upper().replace(" ", "")
    m = re.match(r"^(SH|SZ|BJ)?(\d{6})(\.(SH|SZ|BJ))?$", raw)
    if not m:
        raise ValueError(
            f"无法识别股票代码: '{raw}'。本skill仅支持A股,请提供6位代码"
            "(如 600519、000001.SZ、SH600519 等格式),不支持股票名称/港股/美股/基金代码。"
        )
    code6 = m.group(2)
    exch = m.group(1) or m.group(4)
    if not exch:
        if code6.startswith(("60", "68")):
            exch = "SH"
        elif code6.startswith(("0", "3")):
            exch = "SZ"
        elif code6.startswith(("8", "4")):
            exch = "BJ"
        else:
            exch = "SH"
    return code6, exch


# ----------------------------------------------------------------------------
# 各数据源适配器: 每个函数都返回 (DataFrame[标准列] 或 None, 错误信息或None)
# ----------------------------------------------------------------------------
def _safe_pct_chg(df):
    if "pct_chg" not in df.columns or df["pct_chg"].isna().all():
        df["pct_chg"] = df["close"].pct_change() * 100
    return df


def fetch_via_akshare(code6, exch, start, end):
    try:
        import akshare as ak
    except ImportError:
        return None, "未安装akshare,请先执行: pip install akshare"
    try:
        df = ak.stock_zh_a_hist(
            symbol=code6,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",  # 前复权,保证均线/指标在除权除息后依然连续可比
        )
        if df is None or df.empty:
            return None, "akshare返回空数据(代码可能错误、停牌或未上市)"
        df = df.rename(
            columns={
                "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                "最低": "low", "成交量": "volume", "成交额": "amount",
                "涨跌幅": "pct_chg", "换手率": "turnover",
            }
        )
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        for c in ["open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"]:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[["date"] + [c for c in STANDARD_COLUMNS if c != "date"]]
        return _safe_pct_chg(df), None
    except Exception as e:  # noqa: BLE001
        return None, f"akshare请求失败: {e}"


def fetch_via_tushare(ts_code, start, end, token):
    try:
        import tushare as ts
    except ImportError:
        return None, "未安装tushare,请先执行: pip install tushare"
    if not token:
        return None, "未配置tushare token"
    if token.startswith("${") and token.endswith("}"):
        env_key = token[2:-1]
        token = os.environ.get(env_key, "")
    if not token:
        return None, "tushare token为空"
    try:
        pro = ts.pro_api(token)
        df = pro.daily(ts_code=ts_code, start_date=start.replace("-", ""), end_date=end.replace("-", ""))
        if df is None or df.empty:
            return None, "tushare返回空数据"
        # tushare的daily是不复权数据; vol单位为"手"(100股), amount单位为"千元"
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["volume"] = df["volume"] * 100  # 手 -> 股
        df["amount"] = df["amount"] * 1000  # 千元 -> 元
        df["turnover"] = pd.NA
        df = df.sort_values("date")
        df = df[["date"] + [c for c in STANDARD_COLUMNS if c != "date"]]
        return _safe_pct_chg(df), None
    except Exception as e:  # noqa: BLE001
        return None, f"tushare请求失败: {e}"


def fetch_via_efinance(code6, start, end):
    try:
        import efinance as ef
    except ImportError:
        return None, "未安装efinance,请先执行: pip install efinance"
    try:
        df = ef.stock.get_quote_history(code6, beg=start.replace("-", ""), end=end.replace("-", ""))
        if df is None or df.empty:
            return None, "efinance返回空数据"
        df = df.rename(
            columns={
                "日期": "date", "开盘": "open", "收盘": "close", "最高": "high",
                "最低": "low", "成交量": "volume", "成交额": "amount",
                "涨跌幅": "pct_chg", "换手率": "turnover",
            }
        )
        for c in ["open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"]:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[["date"] + [c for c in STANDARD_COLUMNS if c != "date"]]
        return _safe_pct_chg(df), None
    except Exception as e:  # noqa: BLE001
        return None, f"efinance请求失败: {e}"


def fetch_via_local_csv(code6, source_cfg):
    path = source_cfg.get("path", "").format(code=code6)
    if not os.path.exists(path):
        return None, f"本地文件不存在: {path}"
    try:
        df = pd.read_csv(path)
        col_map = source_cfg.get("columns_map", {})
        inv_map = {v: k for k, v in col_map.items()}
        df = df.rename(columns=inv_map)
        date_fmt = source_cfg.get("date_format")
        if date_fmt:
            df["date"] = pd.to_datetime(df["date"].astype(str), format=date_fmt).dt.strftime("%Y-%m-%d")
        else:
            df["date"] = pd.to_datetime(df["date"].astype(str)).dt.strftime("%Y-%m-%d")
        for c in ["open", "high", "low", "close", "volume", "amount", "turnover", "pct_chg"]:
            if c not in df.columns:
                df[c] = pd.NA
        df = df.sort_values("date")
        df = df[["date"] + [c for c in STANDARD_COLUMNS if c != "date"]]
        return _safe_pct_chg(df), None
    except Exception as e:  # noqa: BLE001
        return None, f"本地CSV解析失败: {e}"


def fetch_index_via_akshare(index_code, start, end):
    """抓取基准指数(默认沪深300),用于相对强弱计算。失败时静默返回None,不影响主流程。"""
    try:
        import akshare as ak

        df = ak.index_zh_a_hist(
            symbol=index_code, period="daily",
            start_date=start.replace("-", ""), end_date=end.replace("-", ""),
        )
        if df is None or df.empty:
            return None
        df = df.rename(columns={"日期": "date", "收盘": "close"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df[["date", "close"]].sort_values("date")
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------------------
# 数据质量检查
# ----------------------------------------------------------------------------
def quality_checks(df, name_hint=""):
    flags = {}
    warnings = []

    n = len(df)
    flags["rows"] = n
    flags["insufficient_history"] = n < 60
    if flags["insufficient_history"]:
        warnings.append(f"历史数据仅{n}个交易日(<60),可能为次新股或停牌过久,中长期均线/趋势判断可信度低。")

    # 疑似停牌缺口检测: 连续两条记录之间日历日差超过15天,在A股语境下大概率是长期停牌
    dates = pd.to_datetime(df["date"])
    gaps = dates.diff().dt.days
    big_gaps = gaps[gaps > 15]
    flags["suspected_suspension_gaps"] = int(len(big_gaps))
    if len(big_gaps) > 0:
        warnings.append(f"检测到{len(big_gaps)}处可能的长期停牌缺口(间隔>15天),期间技术形态被打断,解读时需谨慎。")

    # ST/*ST 标记(仅能从名称推断,best-effort)
    is_st = bool(re.search(r"ST", name_hint.upper())) if name_hint else False
    flags["is_st"] = is_st
    if is_st:
        warnings.append("股票名称包含ST标记,存在退市/财务异常风险,技术分析对此类标的参考价值显著降低。")

    # 近期涨跌停频繁检测(用最近20个交易日的pct_chg绝对值估算,科创板/创业板/北交所阈值~20%,其余~10%)
    recent = df.tail(20)
    threshold = 19.5 if name_hint.upper().startswith(("688", "300")) else 9.5
    limit_days = (recent["pct_chg"].abs() >= threshold).sum()
    flags["recent_limit_move_days"] = int(limit_days)
    if limit_days >= 3:
        warnings.append(f"最近20个交易日中有{int(limit_days)}天接近涨跌停,波动极端,指标可能失真,建议降低仓位/放宽止损。")

    return flags, warnings


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def load_config(config_path):
    default_cfg = {
        "sources": [{"type": "akshare", "enabled": True}],
        "benchmark": {"enabled": True, "code": "000300"},
    }
    if not config_path or not os.path.exists(config_path):
        return default_cfg
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not cfg or "sources" not in cfg:
        return default_cfg
    return cfg


def main():
    parser = argparse.ArgumentParser(description="A股日线数据获取")
    parser.add_argument("--code", required=True, help="股票代码,如 600519 / 600519.SH / 000001.SZ")
    parser.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD,默认回溯约2年以保证年线等长周期指标有效")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD,默认今天")
    parser.add_argument("--lookback-days", type=int, default=730, help="未指定--start时,从--end往前回溯的日历天数")
    parser.add_argument("--config", default=None, help="data_source.yaml路径,默认仅尝试akshare")
    parser.add_argument("--out-dir", default="./output", help="输出目录")
    args = parser.parse_args()

    end = args.end or datetime.now().strftime("%Y-%m-%d")
    start = args.start or (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=args.lookback_days)).strftime("%Y-%m-%d")

    code6, exch = normalize_code(args.code)
    ts_code = f"{code6}.{exch}"

    cfg = load_config(args.config)
    errors = {}
    df = None
    used_source = None

    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        stype = src["type"]
        if stype == "akshare":
            df, err = fetch_via_akshare(code6, exch, start, end)
        elif stype == "tushare":
            df, err = fetch_via_tushare(ts_code, start, end, src.get("token", ""))
        elif stype == "efinance":
            df, err = fetch_via_efinance(code6, start, end)
        elif stype == "local_csv":
            df, err = fetch_via_local_csv(code6, src)
        else:
            df, err = None, f"未知数据源类型: {stype}"

        if df is not None and not df.empty:
            used_source = stype
            break
        errors[stype] = err

    os.makedirs(args.out_dir, exist_ok=True)

    if df is None or df.empty:
        meta = {
            "ok": False,
            "code": ts_code,
            "error": "所有已启用的数据源均获取失败,无法继续分析。",
            "errors_by_source": errors,
            "hint": "请检查网络连接、akshare版本(pip install -U akshare)、或在config中启用其它数据源/补充token。",
        }
        out_meta_path = os.path.join(args.out_dir, f"{code6}_meta.json")
        with open(out_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        sys.exit(1)

    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    flags, warnings = quality_checks(df, name_hint=code6)

    # 基准指数(可选,失败不影响主流程)
    bench_cfg = cfg.get("benchmark", {"enabled": True, "code": "000300"})
    bench_df = None
    if bench_cfg.get("enabled", True):
        bench_df = fetch_index_via_akshare(bench_cfg.get("code", "000300"), start, end)

    out_csv_path = os.path.join(args.out_dir, f"{code6}_daily.csv")
    df.to_csv(out_csv_path, index=False, encoding="utf-8-sig")

    bench_csv_path = None
    if bench_df is not None and not bench_df.empty:
        bench_csv_path = os.path.join(args.out_dir, f"benchmark_{bench_cfg.get('code', '000300')}.csv")
        bench_df.to_csv(bench_csv_path, index=False, encoding="utf-8-sig")
    else:
        warnings.append("基准指数数据获取失败,本次分析将跳过'相对大盘强弱'维度,其余维度权重会按比例重新分配。")

    meta = {
        "ok": True,
        "code": ts_code,
        "data_source_used": used_source,
        "date_range": [df["date"].iloc[0], df["date"].iloc[-1]],
        "rows": int(len(df)),
        "latest_close": float(df["close"].iloc[-1]),
        "latest_pct_chg": None if pd.isna(df["pct_chg"].iloc[-1]) else float(df["pct_chg"].iloc[-1]),
        "flags": flags,
        "warnings": warnings,
        "csv_path": out_csv_path,
        "benchmark_code": bench_cfg.get("code") if bench_csv_path else None,
        "benchmark_csv_path": bench_csv_path,
        "errors_by_source": errors,
    }
    out_meta_path = os.path.join(args.out_dir, f"{code6}_meta.json")
    with open(out_meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
