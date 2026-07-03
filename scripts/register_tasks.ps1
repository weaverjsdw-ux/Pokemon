<#
.SYNOPSIS
  Register the Pokemon discovery deal pipeline (Slice 4) as a repeating Windows
  Scheduled Task, so `python -m scanner.discovery.pipeline --once` runs on an
  interval without a terminal window staying open.

.DESCRIPTION
  The discovery pipeline is a ONE-SHOT program (not a daemon). This script
  registers a Scheduled Task that runs it once, then repeats every
  -IntervalMinutes (default 120 = the config default discovery.interval_seconds
  of 7200s). Crash-proof by design: each firing is an independent short run.

  By default this script only PRINTS the plan and changes nothing. Pass
  -Install to create the task, or -Unregister to remove it. It is meant to be
  run by the OPERATOR after review, never by the build.

  The at-logon restock scan loop (`python -m scanner`) is a SEPARATE task with
  its own registrar - do not duplicate it here:
      powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install

  Boundaries (unchanged): read-only stock queries only, no auto-checkout, no
  cart mutation, no bot-wall evasion, no live PPT credit spend on this path.

.PARAMETER Install
  Actually register the task (otherwise the script is a dry-run plan print).

.PARAMETER Unregister
  Remove the task. Reversible: this only deletes the Scheduled Task entry; it
  touches no code, config, or data.

.PARAMETER IntervalMinutes
  Minutes between one-shot runs (default 120). Match to discovery.interval_seconds/60.

.PARAMETER DryRunTask
  Register the task to run with --dry-run (validate/report, zero network, no
  alerts) instead of a live pass - useful to prove the schedule fires safely
  before going live.

.EXAMPLE
  # See the plan (no changes):
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1

.EXAMPLE
  # Register the live repeating pipeline every 2 hours:
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Install

.EXAMPLE
  # Register a safe dry-run schedule first, then remove it:
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Install -DryRunTask
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$Unregister,
    [int]$IntervalMinutes = 120,
    [switch]$DryRunTask,
    [string]$TaskName = "PokemonDiscoveryPipeline"
)

$ErrorActionPreference = "Stop"

# Repo root is the parent of this script's folder.
$RepoRoot = Split-Path -Parent $PSScriptRoot

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $existing) {
        Write-Host "No scheduled task named '$TaskName' found. Nothing to remove."
        return
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'. (Code/config/data untouched.)"
    return
}

if ($IntervalMinutes -lt 1) {
    throw "IntervalMinutes must be >= 1 (got $IntervalMinutes)."
}

# Prefer the project's virtualenv interpreter; pythonw.exe = no console window
# (a repeating task should not flash a window every interval).
$venvDir = Join-Path $RepoRoot ".venv\Scripts"
$pythonExe = $null
foreach ($cand in @("pythonw.exe", "python.exe")) {
    $p = Join-Path $venvDir $cand
    if (Test-Path $p) { $pythonExe = $p; break }
}
if ($null -eq $pythonExe) {
    $cmd = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($cmd) { $pythonExe = $cmd.Source }
}
if ($null -eq $pythonExe) {
    throw "Could not find a Python interpreter. Create the venv first: python -m venv .venv"
}

$pipelineArgs = if ($DryRunTask) {
    "-m scanner.discovery.pipeline --dry-run"
} else {
    "-m scanner.discovery.pipeline --once"
}
$modeLabel = if ($DryRunTask) { "DRY-RUN (no network, no alerts)" } else { "LIVE one-shot" }

Write-Host "Plan:"
Write-Host "  Task name : $TaskName"
Write-Host "  Program   : $pythonExe"
Write-Host "  Arguments : $pipelineArgs"
Write-Host "  Start in  : $RepoRoot"
Write-Host "  Trigger   : once now, then every $IntervalMinutes minute(s), indefinitely"
Write-Host "  Mode      : $modeLabel"
Write-Host ""
Write-Host "  Restock scan loop is a SEPARATE task:"
Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\install-scheduled-task.ps1 -Install"
Write-Host ""

if (-not $Install) {
    Write-Host "(dry run) Re-run with -Install to create the task, or -Unregister to delete it."
    return
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $pipelineArgs -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
# A one-shot run should finish in seconds; cap it so a hung fetch is killed, and
# never overlap two runs.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Pokemon discovery deal pipeline (one-shot, repeating). Reverse: -Unregister." `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' (every $IntervalMinutes min)."
Write-Host "Run it now with:      Start-ScheduledTask -TaskName $TaskName"
Write-Host "Inspect the result:   Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "Remove it later with: powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Unregister"
