# Register the Pokemon scanner as a Windows Scheduled Task that runs at
# logon and restarts on failure. Run this from an elevated PowerShell
# prompt (Right-click → Run as Administrator).
#
#   .\Install-ScannerTask.ps1                      # use defaults
#   .\Install-ScannerTask.ps1 -RepoPath C:\Pokemon # explicit repo path

[CmdletBinding()]
param(
    [string]$RepoPath = "$env:USERPROFILE\Pokemon",
    [string]$TaskName = "PokemonScanner",
    [string]$PythonExe = ""
)

if (-not (Test-Path $RepoPath)) {
    throw "Repo path not found: $RepoPath"
}

# Prefer the project's venv; fall back to the system `python` on PATH.
if (-not $PythonExe) {
    $venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m scanner" `
    -WorkingDirectory $RepoPath

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Pokemon TCG restock scanner — auto-start at logon, restart on failure." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green
Write-Host "Start now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Stop with:       Stop-ScheduledTask  -TaskName $TaskName"
Write-Host "Uninstall with:  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
