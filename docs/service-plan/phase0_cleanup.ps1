<#
  Phase 0 cleanup — TCG MSRP scanner
  ---------------------------------------------------------------------------
  Dry-run by DEFAULT (prints the plan, changes nothing). Pass -Apply to act.
  Safe by design: only ever touches a fixed scratch set + a stale git lock.
  It NEVER deletes source, data/*.db, config.yaml, or anything else.

  Usage (from anywhere):
    powershell -ExecutionPolicy Bypass -File docs\service-plan\phase0_cleanup.ps1
    powershell -ExecutionPolicy Bypass -File docs\service-plan\phase0_cleanup.ps1 -Apply
#>
[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = 'Stop'
$repo = (Get-Item $PSScriptRoot).Parent.Parent.FullName   # docs/service-plan -> docs -> repo root
Set-Location $repo
Write-Host "Repo root: $repo`n"

# 1) Clear a stale git index lock (it blocked in-session tooling; safe to remove if no git is running)
$lock = Join-Path $repo ".git\index.lock"
if (Test-Path $lock) {
    if ($Apply) { Remove-Item $lock -Force; Write-Host "Removed stale .git\index.lock" }
    else        { Write-Host "(dry-run) would remove stale .git\index.lock" }
} else { Write-Host "No stale index.lock." }

# 2) Scratch files to delete (explicit allow-list only)
$scratch = @(
  "sprint1.txt","sprint1_full.txt","sprint2.txt","sprint3a.txt",
  "iddoctor_offline.txt","test_baseline.txt"
)
$scratch += (Get-ChildItem -File -Filter ".tmp_web_*.err.log" -EA SilentlyContinue | % Name)
$scratch += (Get-ChildItem -File -Path "data" -Filter "*.bak" -EA SilentlyContinue | % { "data\$($_.Name)" })
Write-Host "`nScratch cleanup:"
foreach ($f in $scratch) {
  if (Test-Path $f) {
    if ($Apply) { Remove-Item $f -Force; Write-Host "  deleted $f" }
    else        { Write-Host "  (dry-run) would delete $f" }
  }
}

# 3) Verify BEFORE committing (run these yourself; needs the venv + deps)
Write-Host "`nVerify (run these, expect 170 passed + no secrets printed):"
Write-Host "  python -m pytest -q"
Write-Host "  python -m scanner --check-config"
Write-Host "  python -m scanner --safe-demo"

# 4) Stage the intended baseline (only with -Apply). Does NOT auto-commit so you can eyeball it.
if ($Apply) {
  Write-Host "`nStaging intended files..."
  git add .gitignore README.md config.example.yaml data/ scanner/ tests/ `
          DOCTRINE.md ADVISOR_ROLE.md ROADMAP.md docs/
  Write-Host "`nStaged set (CONFIRM no *.db / *.bak / config.yaml appears):"
  git status --short
  Write-Host "`nIf clean, commit:"
  Write-Host '  git commit -m "Phase 0: clean baseline (new modules + docs + ignore *.bak)"'
} else {
  Write-Host "`n(dry-run) Re-run with -Apply to delete scratch + stage the baseline."
}
