# -*- coding: utf-8 -*-
"""WHUT-ISP 每日早报 v2：分析自动登录日志，经 Server酱 推送微信通知。

流程：由计划任务 WHUT-NetReport-Morning 在唤醒时刻+5分钟触发，读取
whut_autologin.log 中今天 [唤醒时刻-5分钟, +60分钟] 窗口内的记录。

v2 改进（11-15 实测早报误报后）：
1. 等待判决：若窗口内尚无"联网验证"结论行，每 20 秒重读日志，
   最多等到唤醒时刻+30分钟（登录可能还在等 WiFi 重连），再下结论
2. 窗口放宽到 +60 分钟（实测登录成功发生在唤醒后 ~12 分钟）
3. 推送前等 DNS 就绪（实测唤醒初期 DNS 未就绪导致推送失败），失败重试一次

判定优先级（窗口内）：
  1. 有"联网验证：成功"        → 成功（掉线后自动登录成功）
  2. 只有"已在线，无需登录"    → 成功（账号整夜保持在线）
  3. 有"仍未在线/认证未通过"   → 失败（附门户响应摘要）
  4. 窗口内无任何日志          → 状态未知（电脑可能没被唤醒，兜底任务会接管）

SendKey 未配置时仅写日志不推送。
"""
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent
CONFIG_PATH = RUN_DIR / "config.json"
LOG_PATH = RUN_DIR / "whut_autologin.log"

PUSH_HOST = "sctapi.ftqq.com"


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [早报] {msg}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_window_lines(win_start, win_end):
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
            if win_start <= t <= win_end:
                lines.append(ln)
    return lines


def wait_for_net(timeout=60):
    """等 DNS 能解析推送服务（唤醒初期 DNS 可能未就绪）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.getaddrinfo(PUSH_HOST, 443)
            return True
        except Exception:
            time.sleep(6)
    return False


def push(key, title, detail):
    url = f"https://{PUSH_HOST}/{key}.send"
    data = urllib.parse.urlencode({"title": title, "desp": detail}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("code") == 0


def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = str(cfg.get("serverchan_sendkey", "")).strip()
    wake = str(cfg.get("wake_time", "07:00"))
    hh, mm = (wake.split(":") + ["0"])[:2]
    w = datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    win_start = w - timedelta(minutes=5)
    win_end = w + timedelta(minutes=60)
    verdict_deadline = w + timedelta(minutes=30)

    lines = read_window_lines(win_start, win_end)
    # 等待判决：登录可能还在等网络，直到出现"联网验证"结论行或超过 +30 分钟
    if datetime.now() < verdict_deadline and not any("联网验证" in ln for ln in lines):
        log("窗口内暂无登录结论，等待登录任务出结果…")
        while datetime.now() < verdict_deadline:
            time.sleep(20)
            lines = read_window_lines(win_start, win_end)
            if any("联网验证" in ln for ln in lines):
                break

    ok_verify = [ln for ln in lines if "联网验证：成功" in ln]
    ok_online = [ln for ln in lines if "已在线，无需登录" in ln]
    fail = [ln for ln in lines if ("仍未在线" in ln or "认证未通过" in ln or "登录请求异常" in ln)]
    portal = [ln for ln in lines if "门户响应" in ln]
    date = f"{datetime.now():%m-%d}"

    if ok_verify:
        title = "✅ 校园网自动登录成功"
        detail = f"{date} 唤醒后掉线，已自动登录恢复。\n" + ok_verify[-1].split("] ", 1)[-1]
    elif ok_online:
        title = "✅ 校园网账号在线"
        detail = f"{date} 早上账号保持在线，无需登录（未掉线）。"
    elif fail:
        detail = fail[-1].split("] ", 1)[-1]
        if portal:
            detail += "\n" + portal[-1].split("] ", 1)[-1][:150]
        title = "❌ 校园网自动登录失败"
        detail = f"{date} 自动登录未能恢复联网。\n{detail}\n（兜底任务每10分钟会继续重试；若持续失败请手动登录并检查 config.json 密码）"
    elif lines:
        title = "⚠️ 校园网状态待确认"
        detail = f"{date} 唤醒窗口内有日志但无明确结论，兜底任务会继续处理。"
    else:
        title = "⚠️ 未检测到登录记录"
        detail = f"{date} {wake} 前后无任何日志——电脑可能没被唤醒或任务未触发。兜底任务每10分钟会尝试登录。"

    log(f"判定：{title}（窗口内 {len(lines)} 条日志）")

    if not key:
        log("SendKey 未配置，跳过推送。请在 config.json 的 serverchan_sendkey 填入 Server酱 SendKey")
        return 0

    if not wait_for_net():
        log("DNS 60 秒未就绪，仍尝试推送一次")
    try:
        ok = push(key, title, detail)
        log("Server酱推送：" + ("成功 ✅" if ok else "失败：响应异常"))
    except Exception as e:
        log(f"推送第一次失败：{e}，30 秒后重试一次")
        time.sleep(30)
        try:
            ok = push(key, title, detail)
            log("重试推送：" + ("成功 ✅" if ok else "失败：响应异常"))
        except Exception as e2:
            log(f"重试推送仍失败：{e2}")
            ok = False
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
