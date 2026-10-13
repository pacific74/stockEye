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
  @{ Name = 'StockEye Intraday';   Bat = '22_intraday.bat';   At = '08:50' },
  @{ Name = 'StockEye Closingbet'; Bat = '16_closingbet.bat'; At = '14:45' }
)
foreach ($t in $tasks) {
  if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
  }
  if ($Off) { Write-Host "removed: $($t.Name)"; continue }
  $bat = Join-Path $dir $t.Bat
  $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$bat`" auto" -WorkingDirectory $dir
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $t.At
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) -MultipleInstances IgnoreNew
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
  Write-Host "registered: $($t.Name)  Mon-Fri $($t.At)  -> $($t.Bat) auto"
}
if (-not $Off) {
  Write-Host ""
  Write-Host "OK. Check: Task Scheduler (taskschd.msc) > Task Scheduler Library > StockEye ..."
  Write-Host "Logs: data\logs\intraday.log, data\logs\closingbet.log"
}
