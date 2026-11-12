# Cree (ou remplace) la tache planifiee Windows "JobHunter" : tous les jours a 20:00,
# puis la lance une fois pour verifier qu'elle fonctionne. Rapport : logs\installation_tache.txt
$dir = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $dir "run_daily.bat"
$log = Join-Path $dir "logs\installation_tache.txt"
New-Item -ItemType Directory -Force -Path (Join-Path $dir "logs") | Out-Null
$out = @()
try {
    # 1) Diagnostic de la tache existante
    $old = Get-ScheduledTask -TaskName "JobHunter" -ErrorAction SilentlyContinue
    if ($old) {
        $oi = Get-ScheduledTaskInfo -TaskName "JobHunter"
        $out += "AVANT : etat=$($old.State) dernier_lancement=$($oi.LastRunTime) resultat=0x{0:X} manques=$($oi.NumberOfMissedRuns)" -f $oi.LastTaskResult
        $out += "AVANT : logon=$($old.Principal.LogonType) user=$($old.Principal.UserId)"
        $ev = Get-WinEvent -LogName "Microsoft-Windows-TaskScheduler/Operational" -MaxEvents 300 -ErrorAction SilentlyContinue |
              Where-Object { $_.Message -like "*JobHunter*" } | Select-Object -First 8
        foreach ($e in $ev) { $out += "EVENT $($e.TimeCreated) id=$($e.Id) $(($e.Message -split "`n")[0])" }
    }
    # 2) Nouvelle tache : commande directe, reveille le PC, rattrape les passages manques
    $action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`"" -WorkingDirectory $dir
    $trigger  = New-ScheduledTaskTrigger -Daily -At "20:00"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
                  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName "JobHunter" -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "Offres early career corporate finance en Suisse (Documents\jobhunter)" -Force | Out-Null
    # 3) Test : on la lance maintenant
    Start-ScheduledTask -TaskName "JobHunter"
    Start-Sleep -Seconds 25
    $t = Get-ScheduledTask -TaskName "JobHunter"; $i = Get-ScheduledTaskInfo -TaskName "JobHunter"
    $out += "APRES : etat=$($t.State) dernier_lancement=$($i.LastRunTime) resultat=0x{0:X} prochaine=$($i.NextRunTime)" -f $i.LastTaskResult
    $q = Join-Path $dir "logs\tache_quotidienne.log"
    if (Test-Path $q) { $out += "TEST OK : run_daily.bat a demarre (logs\tache_quotidienne.log cree)" }
    else { $out += "TEST ECHEC : run_daily.bat n'a pas demarre" }
} catch {
    $out += "ERREUR : $($_.Exception.Message)"
}
$out | Out-File -Encoding utf8 $log
