# Catalyst-for-Cardboard — Service Plan & Execution Roadmap

> Working analysis pack produced 2026-06-14. Turns the local TCG MSRP restock scanner
> into a durable, doctrine-aligned **personal command center** with a clear roadmap,
> first-20 issues, and coding-agent handoff prompts.
>
> **Doctrine first:** hobby MSRP protection, not scalping. No auto-checkout, no proxy/
> distributed polling, no login-wall scraping, no queue/invite circumvention. Resale data
> is distortion context only. Secrets (addresses, webhook, API keys, config.yaml, route
> coordinates) never appear in any artifact.

## Read in this order

| # | Doc | What it answers |
|---|-----|-----------------|
| 00 | [Executive Brief](00_EXECUTIVE_BRIEF.md) | Can this be a real service? What kind? First 10 moves. Operator decisions. **Start here.** |
| 01 | [Repo Truth](01_REPO_TRUTH.md) | What actually exists in code (verified). Do-not-rebuild list. Leverage points. Dirty-state warning. |
| 02 | [Market & Retailer Map](02_MARKET_AND_RETAILER_MAP.md) | Release calendar, chase list, MSRP vs distortion, retailer scorecard, data-source durability, ID acquisition. |
| 03 | [Service Strategy](03_SERVICE_STRATEGY.md) | 4 service shapes, the recommended path, monetization reality, the source-policy fork. |
| 04 | [Doctrine & Safety](04_DOCTRINE_AND_SAFETY.md) | Allowed / caution / never matrix grounded in your doctrine (anti-scalp, polite, local-first) + source durability. Never-implement & ask-first lists. |
| 05 | [Product & UX](05_PRODUCT_UX.md) | Operator surfaces, information architecture, key flows, text wireframe, setup/daily/release-week feel. |
| 06 | [Engineering Roadmap](06_ENGINEERING_ROADMAP.md) | Phases 0–5: goals, files touched, tests, acceptance criteria, risks, what NOT to build yet. |
| 07 | [Delivery & Knowledge Systems](07_DELIVERY_AND_KNOWLEDGE.md) | First 20 GitHub issues, milestones, labels, CI; Notion workspace; learning-loop templates; ML feasibility; positioning. |
| 08 | [Coding-Agent Handoff](08_CODING_AGENT_HANDOFF.md) | Copy-paste prompts for Phase 0 and Phase 1, plus the first PR. |

## Label legend (used throughout)

- **[verified]** — confirmed against code I read/ran, or multiple/official web sources.
- **[inferred]** — reasoned from partial evidence.
- **[needs validation]** — single or weak source; confirm before relying.
- **[blocked]** — could not confirm; stated plainly, not invented.

## Execution assets (created alongside these docs)

- `phase0_cleanup.ps1` — dry-run-by-default cleanup + baseline-staging helper (clears the stale `.git/index.lock`, deletes scratch files, stages the baseline). Run with `-Apply`.
- `github_bootstrap.ps1` — dry-run-by-default creator for labels, 6 milestones, and the first 20 issues (needs `gh auth login`). Run with `-Apply`.
- **Notion workspace** "Catalyst Desk — TCG MSRP Command Center" — 9 databases (Product Releases, Catalog Research, Retailers/Sources, Verified ID Queue, Daily + Weekly Briefings, Risk Register, Decisions Log, Operator Runbook), seeded with the 2026 release calendar, retailer durability tiers, the source-policy decision, and the top reliability risks.

## One-paragraph verdict

Yes — but the honest shape is a **personal local command center first**, not a hosted multi-user
service. The codebase is already ~80% of that command center and is genuinely well-built
(170 passing tests). The reason to stay personal/local isn't retailer ToS — it's doctrine and
durability: centralizing other people's restock-scraping is exactly the scalper-scale infrastructure
your doctrine rejects (and a privacy liability), while official APIs (**Best Buy + eBay**) simply
**don't break** the way scraped internal endpoints do. So: a polite single-user monitor that leans on
the durable APIs for reliability, still polls the other retailers politely for personal use, and keeps
queues/invites **alert-only** (never jump ahead of other openers). See [00_EXECUTIVE_BRIEF](00_EXECUTIVE_BRIEF.md).
