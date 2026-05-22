# Running the scanner as a service

The scanner is a long-running process. These deploy templates let it
restart automatically across crashes, reboots, and logouts on the three
common host OSes.

## Linux (systemd)

```bash
sudo cp deploy/systemd/pokemon-scanner.service /etc/systemd/system/
sudoedit /etc/systemd/system/pokemon-scanner.service   # tweak paths/user
sudo useradd --system --home /opt/pokemon-scanner scanner
sudo chown -R scanner:scanner /opt/pokemon-scanner
sudo systemctl daemon-reload
sudo systemctl enable --now pokemon-scanner
sudo journalctl -u pokemon-scanner -f
```

Secrets live in `/opt/pokemon-scanner/.env` (`DISCORD_WEBHOOK=...`,
`BESTBUY_API_KEY=...`). `EnvironmentFile=-` makes it optional, but
`config.yaml` will then need the secrets inline.

## macOS (launchd)

```bash
# Edit the CHANGEME paths first.
$EDITOR deploy/launchd/com.user.pokemon-scanner.plist
cp deploy/launchd/com.user.pokemon-scanner.plist ~/Library/LaunchAgents/
launchctl load   ~/Library/LaunchAgents/com.user.pokemon-scanner.plist
launchctl start  com.user.pokemon-scanner
log stream --predicate 'subsystem == "com.user.pokemon-scanner"' --info
```

To stop:

```bash
launchctl stop   com.user.pokemon-scanner
launchctl unload ~/Library/LaunchAgents/com.user.pokemon-scanner.plist
```

## Windows (Task Scheduler)

From an **elevated** PowerShell:

```powershell
cd <path-to-repo>
.\deploy\windows\Install-ScannerTask.ps1
Start-ScheduledTask -TaskName PokemonScanner
```

The script auto-detects `.venv\Scripts\python.exe` if present, falls back
to system `python`. Override with `-PythonExe` or `-RepoPath`.

## Docker (any host)

If you already use Docker, the simpler alternative to any of the above
is `docker compose up -d` — `restart: unless-stopped` in `compose.yaml`
handles both crashes and reboots without touching the host's init
system.

## Cloud (Fly.io / Railway)

If you don't want to run it on hardware you own at all:

- **Fly.io** — see [`deploy/fly/fly.toml`](fly/fly.toml). One-line
  install + a `fly launch`. Cheapest steady-state (~\$2/mo); has a
  built-in persistent volume for `data/`.
- **Railway** — see [`deploy/railway/README.md`](railway/README.md).
  Web-GUI workflow, no CLI. Free trial → ~\$5/mo.

Both pull the same `Dockerfile` the local Docker path uses, so the
build is identical and switching hosts is a no-op.
