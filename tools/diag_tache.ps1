$dir = Split-Path -Parent $PSScriptRoot
$out = Join-Path $dir "logs\diag_tache.txt"
$r = @()
try {
  $t = Get-ScheduledTask -TaskName "JobHunter"
  $i = Get-ScheduledTaskInfo -TaskName "JobHunter"
  $r += "etat=$($t.State) dernier=$($i.LastRunTime) resultat=0x{0:X} prochaine=$($i.NextRunTime) manques=$($i.NumberOfMissedRuns)" -f $i.LastTaskResult
  $r += "action=$($t.Actions[0].Execute) $($t.Actions[0].Arguments)"
  $r += "logon=$($t.Principal.LogonType) user=$($t.Principal.UserId) wake=$($t.Settings.WakeToRun) avail=$($t.Settings.StartWhenAvailable) enabled=$($t.Settings.Enabled)"
  $r += "trigger=$($t.Triggers[0].StartBoundary) enabled=$($t.Triggers[0].Enabled)"
} catch { $r += "ERREUR tache: $($_.Exception.Message)" }
try {
  $ev = Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 2000 -ErrorAction Stop |
        Where-Object { $_.Message -like "*JobHunter*" } | Select-Object -First 25
  foreach ($e in $ev) { $r += "EV $($e.TimeCreated) id=$($e.Id) $(($e.Message -split "`n")[0])" }
} catch { $r += "journal TaskScheduler indisponible: $($_.Exception.Message)" }
try {
  $p = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1,42,107,506,507,6005,6006,6008; StartTime=(Get-Date).AddDays(-4)} -MaxEvents 60 -ErrorAction Stop
  foreach ($e in $p) { $r += "SYS $($e.TimeCreated) id=$($e.Id) $(($e.Message -split "`n")[0])" }
} catch { $r += "journal System: $($_.Exception.Message)" }
$r += "powercfg wake timers:"
$r += (powercfg /q SCHEME_CURRENT SUB_SLEEP RTCWAKE 2>&1 | Out-String)
$r | Out-File -Encoding utf8 $out
