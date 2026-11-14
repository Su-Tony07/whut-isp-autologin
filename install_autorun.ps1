# WHUT-ISP autologin installer (current user, no admin needed)
# Base: HKCU Run + 10-min watch task + wake-from-sleep task
# -Morning: daily wake task (for laptop-in-dorm + pad-remote users)
# -Report:  daily morning report task (push result to WeChat via ServerChan)
param([switch]$Morning, [switch]$Report)

$runDir = $PSScriptRoot
$py     = (Get-Command python.exe).Source
$pyw    = Join-Path (Split-Path $py) 'pythonw.exe'
$script = Join-Path $runDir 'whut_autologin.py'
$userid = $env:COMPUTERNAME + '\' + $env:USERNAME

# ---- 1) logon autostart ----
$val = '"' + $pyw + '" "' + $script + '"'
Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'WHUT-AutoLogin' -Value $val
Write-Host "[OK] logon autostart registered"

# ---- 2) 10-min keepalive ----
$action  = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $script + '"')
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName 'WHUT-AutoLogin-Watch' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[OK] WHUT-AutoLogin-Watch created (every 10 min, battery allowed)"

# ---- 3) wake-from-sleep task ----
# Event 1 Power-Troubleshooter = resume from S3/hibernate; Event 507 Kernel-Power = exit modern standby
$escPyw = $pyw.Replace('&','&amp;')
$escScr = $script.Replace('&','&amp;')
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>WHUT autologin on wake from sleep</Description></RegistrationInfo>
  <Triggers>
    <EventTrigger><Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and (EventID=1)]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
    <EventTrigger><Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Kernel-Power'] and (EventID=507)]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>$userid</UserId><LogonType>InteractiveToken</LogonType></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>$escPyw</Command><Arguments>"$escScr"</Arguments></Exec>
  </Actions>
</Task>
"@
Register-ScheduledTask -TaskName 'WHUT-AutoLogin-Wake' -Xml $xml -Force | Out-Null
Write-Host "[OK] WHUT-AutoLogin-Wake created (resume triggers login)"

# ---- 4) optional: morning wake task ----
if ($Morning) {
    $cfgPath = Join-Path $runDir 'config.json'
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $wake = if ($cfg.wake_time) { $cfg.wake_time } else { '07:00' }
    $hold = if ($cfg.hold_hours) { [string]$cfg.hold_hours } else { '12' }
    $startBoundary = '{0:yyyy-MM-dd}T{1}:00' -f (Get-Date), $wake
    $xmlMorning = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>WHUT autologin: daily wake at $wake, login, hold awake $hold h</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>$userid</UserId><LogonType>InteractiveToken</LogonType></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>$escPyw</Command><Arguments>"$escScr" --hold $hold</Arguments></Exec>
  </Actions>
</Task>
"@
    Register-ScheduledTask -TaskName 'WHUT-AutoLogin-Morning' -Xml $xmlMorning -Force | Out-Null
    Write-Host "[OK] WHUT-AutoLogin-Morning created (daily $wake, WakeToRun, hold ${hold}h)"
}

# ---- 5) optional: morning report task (ServerChan push to WeChat) ----
if ($Report) {
    $reportScript = Join-Path $runDir 'morning_report.py'
    $cfgPath = Join-Path $runDir 'config.json'
    $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
    $wake = if ($cfg.wake_time) { $cfg.wake_time } else { '07:00' }
    $hh = [int]($wake.Split(':')[0]); $mm = [int]($wake.Split(':')[1]) + 5
    if ($mm -ge 60) { $mm -= 60; $hh += 1 }
    $reportTime = '{0:D2}:{1:D2}' -f $hh, $mm
    $startBoundary2 = '{0:yyyy-MM-dd}T{1}:00' -f (Get-Date), $reportTime
    $escRpt = $reportScript.Replace('&','&amp;')
    $xmlReport = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>WHUT autologin morning report via ServerChan at $reportTime</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$startBoundary2</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>$userid</UserId><LogonType>InteractiveToken</LogonType></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>$pyw</Command><Arguments>"$escRpt"</Arguments></Exec>
  </Actions>
</Task>
"@
    Register-ScheduledTask -TaskName 'WHUT-NetReport-Morning' -Xml $xmlReport -Force | Out-Null
    Write-Host "[OK] WHUT-NetReport-Morning created (daily $reportTime, ServerChan report)"
}

# ---- verify ----
$names = @('WHUT-AutoLogin-Watch','WHUT-AutoLogin-Wake')
if ($Morning) { $names += 'WHUT-AutoLogin-Morning' }
if ($Report)  { $names += 'WHUT-NetReport-Morning' }
foreach ($name in $names) {
    $t = Get-ScheduledTask -TaskName $name
    $s = $t.Settings
    Write-Host ("[CHECK] {0}: state={1} battStart={2} battStop={3}" -f $name, $t.State, $s.DisallowStartIfOnBatteries, $s.StopIfGoingOnBatteries)
}
Write-Host "DONE. battStart/battStop must both be False."
