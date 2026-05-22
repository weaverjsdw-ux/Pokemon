# Railway deployment

[Railway](https://railway.app) is the lowest-friction host for this
project — no `flyctl`, no manual volume setup, free trial available.

## One-time setup

1. Push the repo to GitHub (or fork this one).
2. Sign in to Railway → **New Project** → **Deploy from GitHub repo**
   → pick this repo.
3. **Variables** tab → set:
   - `DISCORD_WEBHOOK` (required for alerts)
   - `BESTBUY_API_KEY` (if you enabled Best Buy)
   - `MAPBOX_TOKEN` / `GOOGLE_API_KEY` (optional, for geocoder fallback)
   - `OPERATOR_EMAIL` (recommended — feeds the `From:` header)
4. **Settings → Volumes**: mount a 1 GB volume at `/app/data`. Without
   this, your alert dedupe history + backups vanish on every redeploy.

## config.yaml on Railway

The repo's `config.yaml` is gitignored. Two options:

**Option A — environment variables only.** Use a minimal `config.yaml`
that pulls every secret from env (`${DISCORD_WEBHOOK}`, etc.). Most
fields are fine with their defaults.

**Option B — bake it in.** Create a `config.railway.yaml` (NOT
gitignored — keep secrets in env vars only) and rename it to
`config.yaml` in a `Procfile` start command. Less flexible but works
when you want addresses pinned to the repo.

## Cost

The free trial runs ~indefinitely on a tiny scanner like this (256 MB
RAM, low CPU). After trial, a single-instance scanner is in the
~\$5/mo range. If you outgrow that you've probably outgrown the
single-user assumptions of this project too.

## Compared to Fly.io

| | Railway | Fly.io |
|---|---|---|
| Setup | Web GUI | `fly launch` CLI |
| Volumes | Click | `fly volumes create` |
| Cost (small) | Free trial → ~\$5/mo | Free allowance → ~\$2/mo |
| Multi-region | Pro plan | Built in |

Pick Railway if you want zero CLI; pick Fly.io if you want multi-region
or the cheapest steady-state. Either is fine.
