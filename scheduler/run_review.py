#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_review.py — A股复盘定时调度入口

被操作系统定时器(cron / systemd timer / Windows 任务计划)按固定时刻拉起,
本脚本自身完成:
  1. 按当前本地时间落入哪个时间窗, 选出对应的复盘技能(也可 --skill 强制指定)
  2. 判断当天是否为A股交易日(非交易日且窗口要求交易日 -> 直接跳过)
  3. 以无头模式调用 claude 执行该技能, 捕获其输出报告
  4. 通过 SMTP 把报告发送到配置的邮箱(失败可选发告警邮件)
  5. 全程写日志, 并清理过期日志

用法:
  python scheduler/run_review.py                  # 按当前时间自动选技能
  python scheduler/run_review.py --skill ashare-evening-review
  python scheduler/run_review.py --dry-run        # 只做判断与选择, 不调用claude/不发邮件
  python scheduler/run_review.py --config scheduler/config.yaml --no-email
"""

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

from scheduler.email_sender import send_email

try:
    import yaml
except ImportError:
    sys.stderr.write("缺少依赖 PyYAML, 请先 pip install pyyaml\n")
    raise

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEEKDAY_ALIASES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_LOG_LINES = []


def log(msg):
    """同时写 stdout 与内存缓冲(供落盘和告警邮件复用)。"""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    _LOG_LINES.append(line)


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"找不到配置文件 {path}\n"
            f"请先复制示例: cp scheduler/config.example.yaml scheduler/config.yaml"
        )
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg


def parse_hhmm(s: str) -> dt.time:
    h, m = s.strip().split(":")
    return dt.time(int(h), int(m))


def pick_window(windows: list, now: dt.datetime):
    """返回当前时间命中的第一个窗口 dict, 没有则 None。"""
    cur = now.time()
    wd = now.weekday()
    for w in windows:
        days = [WEEKDAY_ALIASES[d.lower()] for d in w.get("days", [])] if w.get("days") else list(range(7))
        if wd not in days:
            continue
        start = parse_hhmm(w["start"])
        end = parse_hhmm(w["end"])
        if start <= cur < end:
            return w
    return None


# ---------- 交易日判断 ----------
def is_trading_day(now: dt.datetime, cfg: dict) -> bool:
    """优先用 akshare 交易日历; 不可用时按配置退化为仅判断工作日。"""
    tcfg = cfg.get("trading_day", {}) or {}
    source = tcfg.get("source", "akshare")
    today = now.date()

    if source == "akshare":
        try:
            import akshare as ak
            df = ak.tool_trade_date_hist_sina()
            # 该接口返回一列 trade_date(datetime.date 或可解析字符串)
            dates = set()
            for v in df["trade_date"].tolist():
                if isinstance(v, dt.date):
                    dates.add(v)
                else:
                    dates.add(dt.date.fromisoformat(str(v)[:10]))
            result = today in dates
            log(f"交易日历(akshare): {today} -> {'交易日' if result else '非交易日'}")
            return result
        except Exception as e:
            log(f"akshare 交易日历不可用: {e}")
            if not tcfg.get("fallback_to_weekday", True):
                raise SystemExit("交易日历获取失败且未允许退化判断, 中止。")
            log("退化为仅判断工作日(无法识别法定节假日!)")

    # weekday 退化方案 / 显式配置 source: weekday
    result = now.weekday() < 5
    log(f"工作日判断: {today} 周{now.weekday()+1} -> {'工作日' if result else '周末'}")
    return result


# ---------- 调用 claude 无头执行技能 ----------
def run_skill(skill: str, cfg: dict) -> str:
    """以无头模式调用 claude 执行技能, 返回报告正文; 失败抛 RuntimeError。"""
    ccfg = cfg.get("claude", {}) or {}
    prompt = ccfg.get("prompt", "请执行 {skill} 技能并输出完整中文报告。").format(skill=skill)

    cmd = [ccfg.get("bin", "claude"), "-p", prompt, "--output-format", "text"]

    perm = ccfg.get("permission_mode", "bypassPermissions")
    if perm == "bypassPermissions":
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd += ["--permission-mode", perm]
        allowed = ccfg.get("allowed_tools") or []
        if allowed:
            cmd += ["--allowedTools", ",".join(allowed)]

    if ccfg.get("model"):
        cmd += ["--model", ccfg["model"]]
    cmd += list(ccfg.get("extra_args") or [])

    timeout = int(ccfg.get("timeout_seconds", 1800))
    log(f"调用 claude 执行技能 {skill} (超时 {timeout}s): {' '.join(cmd[:3])} ...")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude 执行超时(>{timeout}s)")

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude 退出码 {proc.returncode}\nstderr:\n{(proc.stderr or '').strip()[:2000]}"
        )
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError("claude 输出为空")
    log(f"技能执行完成, 报告长度 {len(out)} 字符")
    return out


# ---------- 日志落盘与清理 ----------
def flush_log(cfg: dict, skill: str):
    lcfg = cfg.get("log", {}) or {}
    log_dir = PROJECT_ROOT / lcfg.get("dir", "scheduler/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = log_dir / f"{stamp}_{skill or 'none'}.log"
    fname.write_text("\n".join(_LOG_LINES) + "\n", encoding="utf-8")

    keep_days = int(lcfg.get("keep_days", 30))
    if keep_days > 0:
        cutoff = dt.datetime.now() - dt.timedelta(days=keep_days)
        for old in log_dir.glob("*.log"):
            try:
                if dt.datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
                    old.unlink()
            except OSError:
                pass


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser(description="A股复盘定时调度入口")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "scheduler" / "config.yaml"),
                    help="配置文件路径(默认 scheduler/config.yaml)")
    ap.add_argument("--skill", default=None, help="强制指定技能, 跳过时间窗判断")
    ap.add_argument("--dry-run", action="store_true",
                    help="只做技能选择与交易日判断, 不调用claude、不发邮件")
    ap.add_argument("--no-email", action="store_true", help="本次不发邮件(仍调用claude)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    now = dt.datetime.now()
    log(f"启动 run_review, 当前时间 {now.strftime('%Y-%m-%d %H:%M:%S')} 周{now.weekday()+1}")

    # 1. 选技能
    if args.skill:
        skill = args.skill
        window = next((w for w in cfg.get("windows", []) if w.get("skill") == skill), {})
        log(f"强制指定技能: {skill}")
    else:
        window = pick_window(cfg.get("windows", []), now)
        if not window:
            log("当前时间不在任何配置的时间窗内, 退出(非错误)。")
            flush_log(cfg, "none")
            return 0
        skill = window["skill"]
        log(f"命中时间窗 [{window['start']}-{window['end']}] -> 技能 {skill}")

    # 2. 交易日判断
    require_td = window.get("require_trading_day", True) if window else True
    if require_td and not is_trading_day(now, cfg):
        log(f"今天非A股交易日, 技能 {skill} 跳过(非错误)。")
        flush_log(cfg, skill)
        return 0

    if args.dry_run:
        log(f"[dry-run] 将执行技能 {skill} 并发邮件(此处跳过)。")
        flush_log(cfg, skill)
        return 0

    # 3. 执行 + 发邮件
    ecfg = cfg.get("email", {}) or {}
    prefix = ecfg.get("subject_prefix", "[A股复盘]")
    date_str = now.strftime("%Y-%m-%d")
    try:
        report = run_skill(skill, cfg)
        if not args.no_email:
            send_email(ecfg, f"{prefix} {skill} {date_str}", report, log)
        flush_log(cfg, skill)
        return 0
    except Exception as e:
        log(f"执行失败: {e}")
        if not args.no_email and ecfg.get("send_on_failure", True):
            try:
                send_email(ecfg, f"{prefix} 失败告警 {skill} {date_str}",
                           f"技能 {skill} 执行失败:\n\n{e}\n\n--- 运行日志 ---\n" + "\n".join(_LOG_LINES), log)
            except Exception as e2:
                log(f"告警邮件也发送失败: {e2}")
        flush_log(cfg, skill)
        return 1


if __name__ == "__main__":
    sys.exit(main())
