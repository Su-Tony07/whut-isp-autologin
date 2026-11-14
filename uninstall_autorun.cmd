@echo off
rem WHUT-ISP autologin uninstaller: removes logon autostart and all tasks.
rem Tasks that were never installed will report "does not exist" - that is fine.
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v WHUT-AutoLogin /f
schtasks /Delete /F /TN "WHUT-AutoLogin-Watch"
schtasks /Delete /F /TN "WHUT-AutoLogin-Wake"
schtasks /Delete /F /TN "WHUT-AutoLogin-Morning"
schtasks /Delete /F /TN "WHUT-NetReport-Morning"
echo All WHUT autologin tasks removed.
pause
