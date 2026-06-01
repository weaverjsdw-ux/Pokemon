<#
.SYNOPSIS
  Run the Pokemon TCG restock scanner unattended via Windows Task Scheduler,
  so it keeps scanning without a terminal window staying open.

.DESCRIPTION
  Registers a Scheduled Task that launches the scanner at logon and restarts
  it if it ever exits. By default this script only PRINTS the plan - pass
  -Install to actually create the task, or -Remove to delete it.

  Two modes:
    (default)  python -m scanner       # console scan loop, no window (pythonw)
    -Web       python -m scanner.web   # local dashboard + interval scanner

.EXAMPLE
  # See what it would do (no changes):
  powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1

.EXAMPLE
  # Actually install the background scan loop:
  powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install

.EXAMPLE
  # Install the local web dashboard instead, then remove later:
  powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install -Web
  powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Remove
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Remove,
    [switch]$Web,
    [string]$TaskName = "PokemonRestockScanner"
)

$ErrorActionPreference = "Stop"

# Repo root is the parent of this script's folder.
$RepoRoot = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "No scheduled task named '$TaskName' found. Nothing to remove."
        return
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

# Prefer the project's virtualenv interpreter; pythonw.exe = no console window.
$venvDir = Join-Path $RepoRoot ".venv\Scripts"
if ($Web) {
    # The web UI prints a URL; keep a console so that's visible.
    $exeCandidates = @("python.exe")
} else {
    $exeCandidates = @("pythonw.exe", "python.exe")
}

$pythonExe = $null
foreach ($cand in $exeCandidates) {
    $p = Join-Path $venvDir $cand
    if (Test-Path $p) { $pythonExe = $p; break }
}
if ($null -eq $pythonExe) {
    $cmd = Get-Command ($exeCandidates[-1]) -ErrorAction SilentlyContinue
    if ($cmd) { $pythonExe = $cmd.Source }
}
if ($null -eq $pythonExe) {
    throw "Could not find a Python interpreter. Create the venv first: python -m venv .venv"
}

$module = if ($Web) { "scanner.web" } else { "scanner" }
$arguments = "-m $module"

Write-Host "Plan:"
Write-Host "  Task name : $TaskName"
Write-Host "  Program   : $pythonExe"
Write-Host "  Arguments : $arguments"
Write-Host "  Start in  : $RepoRoot"
Write-Host "  Trigger   : at user logon, restart-on-exit"
Write-Host ""

if (-not $Install) {
    Write-Host "(dry run) Re-run with -Install to create the task, or -Remove to delete it."
    return
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)  # 0 = no time limit

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Pokemon TCG restock scanner ($module), unattended." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'. It will start at your next logon."
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
