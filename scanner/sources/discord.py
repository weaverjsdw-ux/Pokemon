"""Discord channel ingest (design stub — not wired in yet).

The goal: mirror public restock-tracker servers' alerts into the user's
own channel, deduplicated against the scanner's own polling. The path:

  1. User creates a Discord bot via the developer portal.
  2. User invites the bot to whichever server(s) they want to mirror.
     The bot needs the 'Read Message History' + 'View Channel' perms.
  3. Bot token + channel IDs go in config:

        community_signal:
          discord:
            enabled: true
            bot_token: "\${DISCORD_BOT_TOKEN}"
            channels:
              - { name: "restock-alerts", id: "1234567890" }

  4. We poll each channel via GET /channels/{id}/messages every N seconds,
     dedupe by message id, and emit SignalHits.

Why this is a stub: Discord bot setup is non-trivial (developer portal,
OAuth invite flow, gateway-vs-REST tradeoffs, intent declarations) and
most users won't go through it. The Reddit + Nitter sources cover most
of the practical value here without a bot.

To actually implement this, replace this stub with a real DiscordSource
class following sources.reddit.RedditSource's shape — request via
`https://discord.com/api/v10/channels/{id}/messages?limit=20` with an
`Authorization: Bot <token>` header. Dedupe via `state.signal_should_alert`.
The migration v4 signal_seen table already exists for that purpose."""
from __future__ import annotations

# Intentionally empty. See module docstring.
