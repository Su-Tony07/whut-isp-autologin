# WHUT-ISP 校园网自动登录

武汉理工大学运营商网（WHUT-ISP）自动登录工具。认证页为华为 ME60 内置 Portal：

```
http://172.30.21.100/tpl/isp/login_account.html?acip=...&acname=WHUT-Bras-ME60-A&nasId=...
```

断网自动重连、开机自启；可选每天定时唤醒电脑 + 微信推送登录结果。
解决宿舍 23 点断电、次日账号掉线要手动登录的问题。

> ⚠️ 仅适用于上面这种 `tpl/isp` 华为 Portal 页面（运营商网）。
> 宿舍区深澜（srun）门户 `172.30.16.34` 不适用本工具。

## 功能

- 掉线自动登录：NCSI 探测判掉线 → 借微软重定向自动取 nasId → CSRF → 认证 → PPPoE 拨号
- 45 秒联网复核轮询（实测拨号后数据面要 10~20 秒才真正通，一次探测定成败会误报）
- 残留会话卡拨号时自动登出清理后重试
- 睡眠唤醒立即重登录（计划任务事件触发，Modern Standby / S3 都覆盖）
- 日志全留痕（不记密码），超 2MB 自动轮转
- 凭据只存本地、只发往校园网关，无遥测无第三方上报

## 快速开始

```bash
pip install requests
copy config.example.json config.json   # 然后用记事本填 username/password
python whut_autologin.py               # 掉线状态下实测一次
```

- 登录用户名 = 校园卡卡号后六位的绝对值；密码 = 智慧校园密码
- 门户弹验证码时脚本无法处理，手动登一次即可，之后继续自动化

## 注册自启（PowerShell）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install_autorun.ps1            # 基础：开机自启 + 每10分钟兜底 + 唤醒即登
powershell -NoProfile -ExecutionPolicy Bypass -File install_autorun.ps1 -Morning   # 可选：每天 07:00 唤醒电脑（电脑在宿舍、上课 pad 远程的场景）
powershell -NoProfile -ExecutionPolicy Bypass -File install_autorun.ps1 -Report    # 可选：每天早上微信推送登录结果
```

- `-Morning` 会在每天 `wake_time`（config.json，默认 07:00）唤醒电脑、登录后保持
  唤醒 `hold_hours` 小时（默认 12），期间手动睡眠不受影响
- 卸载：双击 `uninstall_autorun.cmd`（全部任务一键移除）

## 微信早报（可选）

1. 微信扫码登录 [sct.ftqq.com](https://sct.ftqq.com)，复制 SendKey（`SCT` 开头）
2. 填入 `config.json` 的 `serverchan_sendkey` 字段
3. `install_autorun.ps1 -Report` 注册每天 `wake_time+5 分钟` 的推送任务

推送内容只有结论（✅成功 / ❌失败原因 / ⚠️未唤醒）和门户响应摘要，不含任何凭据。
登录动作本身始终只直连学校网关，不经过第三方。

## 安全与隐私

- 账号密码只存在本机 `config.json`（已 gitignore），只发送到认证网关
- 日志只记用户名和门户响应摘要；门户原始 JSON 含姓名/MAC/token，截图分享时注意遮挡
- 认证协议与 [zhxycn/WHUT-WLAN](https://github.com/zhxycn/WHUT-WLAN) 一致，
  本仓库为其加固版实现（超时 / URL 编码 / 轮询验证 / 残留会话清理 / 日志轮转）
- 认证走 HTTP 明文是校园网 Portal 固有特性
- `docs/AI助手配置任务书.txt`：把这份 txt 发给你电脑上的 AI 助手（ZCode/DSH 等），
  它会照文档自动完成全部部署

## License

[MIT](LICENSE)
