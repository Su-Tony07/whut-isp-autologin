# -*- coding: utf-8 -*-
"""WHUT-ISP 每日早报：分析自动登录日志，经 Server酱 推送微信通知。

流程：07:05 由计划任务 WHUT-NetReport-Morning 触发（比 07:00 的登录任务晚 5 分钟），
读取 whut_autologin.log 中今天 [唤醒时刻-5分钟, +30分钟] 窗口内的记录，判定
登录结果，调用 Server酱 API 推送到微信。

判定优先级（窗口内）：
  1. 有"联网验证：成功"        → 成功（掉线后自动登录成功）
  2. 只有"已在线，无需登录"    → 成功（账号整夜保持在线）
  3. 有"仍未在线/认证未通过"   → 失败（附门户响应摘要）
  4. 窗口内无任何日志          → 状态未知（电脑可能没被唤醒，兜底任务会接管）

SendKey 未配置时仅写日志不推送。
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
CONFIG_PATH = RUN_DIR / "config.json"
LOG_PATH = RUN_DIR / "whut_autologin.log"


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [早报] {msg}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_window():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    wake = str(cfg.get("wake_time", "07:00"))
    key = str(cfg.get("serverchan_sendkey", "")).strip()
    hh, mm = (wake.split(":") + ["0"])[:2]
    w = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    win_start = w - timedelta(minutes=5)
    win_end = w + timedelta(minutes=30)
    lines = []
    if LOG_PATH.exists():
        for ln in LOG_PATH.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", ln)
            if not m:
                continue
            try:
                t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if t.date() == w.date() and win_start <= t <= win_end:
                lines.append(ln)
    return key, wake, lines


def judge(lines, wake):
    """返回 (title, detail)。"""
    ok_verify = [ln for ln in lines if "联网验证：成功" in ln]
    ok_online = [ln for ln in lines if "已在线，无需登录" in ln]
    fail = [ln for ln in lines if ("仍未在线" in ln or "认证未通过" in ln or "登录请求异常" in ln)]
    portal = [ln for ln in lines if "门户响应" in ln]
    date = f"{datetime.now():%m-%d}"
    if ok_verify:
        return "✅ 校园网自动登录成功", f"{date} 唤醒后掉线，已自动登录恢复。\n" + ok_verify[-1].split("] ", 1)[-1]
    if ok_online:
        return "✅ 校园网账号在线", f"{date} 早上账号保持在线，无需登录（未掉线）。"
    if fail:
        detail = fail[-1].split("] ", 1)[-1]
        if portal:
            detail += "\n" + portal[-1].split("] ", 1)[-1][:150]
        return "❌ 校园网自动登录失败", f"{date} 自动登录未能恢复联网。\n{detail}\n（兜底任务每10分钟会继续重试；若持续失败请手动登录并检查 config.json 密码）"
    if lines:
        return "⚠️ 校园网状态待确认", f"{date} 唤醒窗口内有日志但无明确结论，兜底任务会继续处理。"
    return "⚠️ 未检测到登录记录", f"{date} {wake} 前后无任何日志——电脑可能没被唤醒或任务未触发。兜底任务每10分钟会尝试登录。"


def push(key, title, detail):
    url = f"https://sctapi.ftqq.com/{key}.send"
    data = urllib.parse.urlencode({"title": title, "desp": detail}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("code") == 0


def main():
    key, wake, lines = load_window()
    title, detail = judge(lines, wake)
    log(f"判定：{title}（窗口内 {len(lines)} 条日志）")
    if not key:
        log("SendKey 未配置，跳过推送。请在 config.json 的 serverchan_sendkey 填入 Server酱 SendKey")
        return 0
    try:
        ok = push(key, title, detail)
        log("Server酱推送：" + ("成功 ✅" if ok else f"失败：响应异常"))
    except Exception as e:
        ok = False
        log(f"Server酱推送异常：{e}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
