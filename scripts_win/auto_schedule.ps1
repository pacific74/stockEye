# StockEye: register weekday tasks in Windows Task Scheduler.
#   08:50  StockEye Intraday   -> 22_intraday.bat auto  (daytrade + limitcatch, realtime, one process)
#   14:45  StockEye Closingbet -> 16_closingbet.bat auto
# The old separate tasks (StockEye Daytrade / StockEye Limitcatch) are removed: two processes on one KIS key can conflict.
# Run via 18_auto_schedule.bat (once). "-Off" removes them all.
param([switch]$Off)
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($old in @('StockEye Daytrade', 'StockEye Limitcatch')) {
  if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $old -Confirm:$false
    Write-Host "removed old: $old"
  }
}
$tasks = @(
  @{ Name = 'StockEye Intraday';   Bat = '22_intraday.bat';   At = '08:50'; Catchup = $true },
  @{ Name = 'StockEye Closingbet'; Bat = '16_closingbet.bat'; At = '14:45'; Catchup = $false }  # 14:45 only (no catch-up when the PC was off)
)
foreach ($t in $tasks) {
  if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
  }
  if ($Off) { Write-Host "removed: $($t.Name)"; continue }
  $bat = Join-Path $dir $t.Bat
  $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$bat`" auto" -WorkingDirectory $dir
  $trigger = @(New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $t.At)
  if ($t.Catchup) {
    # PC turned on late (after 08:50): StartWhenAvailable alone did not start it -> also start at logon.
    # The program exits by itself on weekends/holidays/after 15:40, and with --logon it skips before 08:45 (the 08:50 trigger covers that).
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$bat`" logon" -WorkingDirectory $dir
    $trigger += New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
  }
  $opts = @{ AllowStartIfOnBatteries = $true; DontStopIfGoingOnBatteries = $true
             ExecutionTimeLimit = (New-TimeSpan -Hours 8); MultipleInstances = 'IgnoreNew' }
  if ($t.Catchup) { $opts.StartWhenAvailable = $true }   # Intraday: if started late the same day it still helps
  $settings = New-ScheduledTaskSettingsSet @opts
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
  Write-Host "registered: $($t.Name)  Mon-Fri $($t.At)  -> $($t.Bat) auto"
}
if (-not $Off) {
  Write-Host ""
  Write-Host "OK. Check: Task Scheduler (taskschd.msc) > Task Scheduler Library > StockEye ..."
  Write-Host "Logs: data\logs\intraday.log, data\logs\closingbet.log"
}
