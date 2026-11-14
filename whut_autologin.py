# -*- coding: utf-8 -*-
"""WHUT-ISP 校园网自动登录器（运行器 v3）

认证协议来自审计过的 zhxycn/WHUT-WLAN（main.py），加固点：
1. 所有请求带超时（上游无超时，计划任务挂死风险）
2. POST body 用 urlencode 编码（上游原样拼接，密码含 &/+ 会坏）
3. 联网验证改为 45 秒轮询（实测 PPPoE 拨号后数据面要 10~20 秒才真正通）
4. 认证通过但始终不在线时：登出清理残留会话后重登一次（拨号冲突兜底）
5. 登录前先等网关就绪（睡眠唤醒后 WiFi 重连要几秒~几十秒，防止任务扑空）
6. 不在校园网（如连手机热点）时静默跳过，不报错
7. --hold N：登录后阻止系统自动睡眠 N 小时（早上唤醒任务用，pad 远程场景）

凭据从本目录 config.json 读取，不经过命令行参数（进程列表不可见）。
日志只记用户名和门户响应，永不记录密码。
"""
import argparse
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

RUN_DIR = Path(__file__).resolve().parent
CONFIG_PATH = RUN_DIR / "config.json"
LOG_PATH = RUN_DIR / "whut_autologin.log"

PORTAL = "http://172.30.21.100"
NCSI_PROBE = "http://www.msftconnecttest.com/connecttest.txt"
NCSI_REDIRECT = "http://www.msftconnecttest.com/redirect"
NCSI_BODY = "Microsoft Connect Test"
TIMEOUT = 6
VERIFY_WINDOW = 45   # 联网验证轮询窗口（秒）
VERIFY_STEP = 4      # 轮询间隔（秒）
PORTAL_WAIT = 240    # 等网关就绪的最长时间（秒）——实测唤醒后 WiFi 重连可能要几分钟

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def hold_awake(hours):
    """阻止系统自动睡眠（不阻止手动睡眠），hold_hours 小时后自动恢复。"""
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    log(f"进入保持唤醒状态 {hours} 小时（手动睡眠不受影响，期间 pad 随时可远程）")
    end = time.time() + hours * 3600
    while time.time() < end:
        time.sleep(60)
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    log("保持唤醒结束，恢复系统自动睡眠策略")


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        # 轮转：超 2MB 归档为 .log.old（每 10 分钟一条打卡，约半年涨满 2MB）
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2 * 1024 * 1024:
            old = LOG_PATH.with_suffix(".log.old")
            if old.exists():
                old.unlink()
            LOG_PATH.rename(old)
    except Exception:
        pass
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_online():
    """NCSI 探测：被门户劫持时响应内容会变，以此区分在线/掉线。"""
    try:
        r = requests.get(NCSI_PROBE, timeout=TIMEOUT)
        return r.status_code == 200 and NCSI_BODY in r.text
    except Exception:
        return False


def verify_online(window=VERIFY_WINDOW):
    """耐心轮询验证：拨号成功 ≠ 数据面立刻通，实测要十几秒。"""
    deadline = time.time() + window
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        if is_online():
            log(f"联网验证：成功 ✅（第 {attempt} 次探测）")
            return True
        time.sleep(VERIFY_STEP)
    log(f"联网验证：{window} 秒内仍未在线 ❌")
    return False


def wait_for_portal(max_wait=PORTAL_WAIT):
    """等校园网网关就绪（唤醒后 WiFi 重连中，网关暂时不可达是正常的）。"""
    deadline = time.time() + max_wait
    waited = 0
    while time.time() < deadline:
        try:
            r = requests.get(f"{PORTAL}/api/csrf-token", timeout=TIMEOUT)
            if r.status_code == 200:
                if waited:
                    log(f"网关就绪（等待 {waited} 秒）")
                return True
        except Exception:
            pass
        time.sleep(4)
        waited += 4
    return False


def get_nasid(session, fallback):
    """复用上游逻辑：借 NCSI 重定向从门户劫持 URL 里解析 nasId。"""
    try:
        r = session.get(NCSI_REDIRECT, timeout=TIMEOUT, allow_redirects=True)
        qs = parse_qs(urlparse(r.url).query)
        if qs.get("nasId"):
            return qs["nasId"][0]
    except Exception as e:
        log(f"nasId 解析失败（{e}），使用兜底值")
    return fallback


def get_csrf(session):
    return session.get(f"{PORTAL}/api/csrf-token", timeout=TIMEOUT).json()["csrf_token"]


def portal_login(session, csrf, username, password, nasid):
    data = urlencode({
        "username": username,
        "password": password,
        "switchip": "",
        "nasId": nasid,
        "userIpv4": "",
        "userMac": "",
        "captcha": "",
        "captchaId": "",
    })
    resp = session.post(
        f"{PORTAL}/api/account/login",
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-csrf-token": csrf,
        },
        data=data,
        timeout=TIMEOUT,
    )
    return resp.text


def portal_logout(session, csrf):
    """尽力而为地清理本机残留会话（只影响当前 IP/MAC 的会话）。"""
    try:
        session.get(
            f"{PORTAL}/api/account/logout",
            headers={"x-csrf-token": csrf},
            timeout=TIMEOUT,
        )
        log("已发送登出，清理残留会话")
    except Exception as e:
        log(f"登出请求失败（忽略）：{e}")


def parse_portal_response(text):
    """提取门户响应里的关键字段，方便日志判断。"""
    try:
        j = json.loads(text)
        code = j.get("code")
        auth = f'{j.get("authCode", "")} {j.get("authMsg", "")}'.strip()
        dial = f'{j.get("dialCode", "")} {j.get("dialMsg", "")}'.strip()
        msg = j.get("msg", "")
        return code, auth, dial, msg
    except Exception:
        return None, "", "", text[:200]


def attempt(username, password, nasid_fallback):
    """完整登录一次。返回 (门户响应原文, code, session, csrf)。"""
    session = requests.Session()
    nasid = get_nasid(session, nasid_fallback)
    csrf = get_csrf(session)
    text = portal_login(session, csrf, username, password, nasid)
    code, auth, dial, msg = parse_portal_response(text)
    log(f"门户响应：code={code} 认证[{auth}] 拨号[{dial}] msg={msg}")
    return text, code, session, csrf


def main():
    ap = argparse.ArgumentParser(description="WHUT-ISP autologin")
    ap.add_argument("--hold", type=float, default=0.0,
                    help="登录后保持系统唤醒的小时数（早上唤醒任务用）")
    args = ap.parse_args()
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log("config.json 不存在")
        return 3
    username = cfg.get("username", "").strip()
    password = cfg.get("password", "")
    nasid_fallback = str(cfg.get("nasid_fallback", "")).strip()
    if not username or not password:
        log("config.json 里 username/password 还没填")
        return 3

    if is_online():
        log("已在线，无需登录")
        if args.hold > 0:
            hold_awake(args.hold)
        return 0

    log(f"检测到掉线，开始登录（用户名 {username}，nasId 兜底 {nasid_fallback or '无'}）")
    if not wait_for_portal():
        log("网关 90 秒不可达：大概率不在校园网（如热点），本轮跳过")
        if args.hold > 0:
            hold_awake(args.hold)
        return 0

    try:
        text, code, session, csrf = attempt(username, password, nasid_fallback)
    except Exception as e:
        log(f"登录请求异常：{e}")
        return 2

    result_ok = False
    if code == 0:
        result_ok = verify_online()
        if not result_ok:
            # 认证通过但迟迟不在线：多半是残留 PPPoE 会话卡住拨号，登出清理后重来
            log("认证通过但未联网，执行登出清理后重试一次")
            portal_logout(session, csrf)
            time.sleep(3)
            try:
                text, code, session, csrf = attempt(username, password, nasid_fallback)
            except Exception as e:
                log(f"重试登录请求异常：{e}")
                code = None
            if code == 0:
                result_ok = verify_online()
    else:
        log(f"认证未通过（code={code}），不重试。若门户要求验证码或密码已改，请手动处理")

    if not result_ok:
        log("本轮自动登录未能恢复联网")

    if args.hold > 0:
        hold_awake(args.hold)

    return 0 if result_ok else 2


if __name__ == "__main__":
    sys.exit(main())
