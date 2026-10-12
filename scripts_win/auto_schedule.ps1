# StockEye: register weekday tasks for daytrade (08:50), limitcatch (08:55) and closingbet (14:45) in Windows Task Scheduler.
# Run via 18_auto_schedule.bat (once). "-Off" removes them.
param([switch]$Off)
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$tasks = @(
  @{ Name = 'StockEye Daytrade';   Bat = '14_daytrade.bat';   At = '08:50' },
  @{ Name = 'StockEye Limitcatch'; Bat = '19_limitcatch.bat'; At = '08:55' },
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
  Write-Host "Logs: data\logs\daytrade.log, data\logs\limitcatch.log, data\logs\closingbet.log"
}
