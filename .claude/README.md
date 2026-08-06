# `.claude/` — the Poke fork of Superpowers

A project-local fork of the [Superpowers](https://github.com/obra/superpowers) skills library
(v6.2.0, MIT), narrowed to the seven skills this repo actually uses and rewritten so the repo's
non-negotiables travel with them.

## Why this exists

**Availability.** `superpowers` is enabled on the operator's Claude account, but marketplace
plugins are not pushed into remote/web containers — a Claude Code on the web session has no
`superpowers:*` skills at all, so `/superpowers:brainstorming` silently does not exist there.
Checked into the repo, these load everywhere: web, CLI, and desktop.

**Customization.** Upstream is deliberately generic. It does not know that a number without a
source is a stop-work defect here, that `limit=1` is a money leak when removed, that local `main`
diverges from `origin/main` on purpose, or that the canonical test command points at a Windows
venv. Generic reviewers pass fabricated prices, because nothing in a diff announces itself as one.

## What's here

| Path | What it is |
| --- | --- |
| `poke-invariants.md` | The shared guardrail block. Single source of truth; every skill inherits it. |
| `scripts/poke-pytest` | Resolves the project interpreter (Windows venv / POSIX venv / system) and runs pytest. Exit 3 = the suite did **not** run. |
| `commands/pokebuild.md` | `/pokebuild` — the dev advisor/coder session contract, previously documented but not an actual command. |
| `skills/poke-brainstorm/` | Idea → reviewed design spec in `docs/superpowers/specs/`. |
| `skills/poke-plan/` | Spec → TDD implementation plan in `docs/superpowers/plans/`. |
| `skills/poke-sdd/` | Subagent-driven execution (recommended executor) + prompt templates + helper scripts. |
| `skills/poke-execute/` | Inline execution, for when subagents are unavailable or tasks are coupled. |
| `skills/poke-tdd/` | Red/green/refactor with this repo's provenance, credit, and worked-example test classes. |
| `skills/poke-review/` | Dispatches a reviewer with the domain rubric + the reviewer prompt template. |
| `skills/poke-finish/` | Branch integration — merges to **local** main; never pushes unasked. |

## The workflow

```
/pokebuild  →  poke-brainstorm  →  poke-plan  →  poke-sdd  →  poke-finish
                    (spec)          (plan)      (execute)     (merge local)
                                                    ↑
                                    poke-tdd + poke-review run inside it
```

`poke-execute` substitutes for `poke-sdd` when subagents are unavailable.

## What was customized

Everything below is a deliberate divergence from upstream, not drift:

1. **Part 0: Domain Gates** — a new review stage ahead of spec and quality review, in the task
   reviewer, the final code reviewer, and the scoped re-reviewer. Covers price provenance, exact
   identity, PPT credit accounting, doctrine (advise ≠ execute), fail-safe defaults, and secrets.
   Every violation is Critical and is never parked at the fix-loop breaker.
2. **The Poke Design Interrogation** in `poke-brainstorm` — the provenance / credit / doctrine /
   fail-safe / scope questions a design must answer before it gets written up.
3. **A prewired Global Constraints block** in `poke-plan`, matching the one the repo's existing
   plans already carry, plus the PIN-FIRST gate pattern.
4. **Worked-example arithmetic is mandatory** for money assertions, and is recomputed by hand at
   three checkpoints (plan self-review, pre-flight scan, task review). A worked example that did
   not reconcile has shipped as a code bug here before.
5. **Repo test classes** in `poke-tdd`: provenance, sentinel-leak, credit-accounting (including
   asserting `limit=1` is actually passed), fail-safe, and dated-era tests.
6. **Portable test command.** Upstream assumes a working suite. `scripts/poke-pytest` resolves the
   interpreter across Windows/POSIX/system, and exits 3 rather than letting a session claim a
   green suite it never ran or `pip install` its way out.
7. **`poke-finish` never pushes**, drops upstream's `git pull` before merging (local `main` may
   intentionally diverge from `origin/main`), and adds a pre-merge secret sweep.
8. **Hard stops** in `poke-sdd`/`poke-execute` for fabricating a number, removing `limit=1`,
   flipping a PIN-FIRST value, executing a transaction, installing a dependency, spending credits,
   or pushing.
9. **Load-bearing structures** (`poke-invariants.md` §10) are named so a reviewer does not "fix"
   the D-vs-E split, the `_shipping_for` twins, the three ledgers, or the TCGCSV non-independence.
10. **Conventional commit scopes** (`feat(poke):` …) replace upstream's generic `feat:`.

Dropped from upstream as unused here: `using-git-worktrees`, `dispatching-parallel-agents`,
`systematic-debugging`, `verification-before-completion`, `writing-skills`, `receiving-code-review`,
`using-superpowers`. The three SDD helper scripts (`sdd-workspace`, `task-brief`, `review-package`)
are vendored **verbatim**.

## Relationship to the upstream plugin

The `poke-` prefix means there is no collision: on a machine with the plugin installed, both
`poke-plan` and `superpowers:writing-plans` are available and you pick per session. These skills
are self-contained — they do not call into the plugin and work fine when it is absent.

## Re-syncing with upstream

```bash
git clone --depth 1 https://github.com/obra/superpowers.git /tmp/sp
diff -u /tmp/sp/skills/writing-plans/SKILL.md .claude/skills/poke-plan/SKILL.md
```

Fork base: **obra/superpowers v6.2.0**. Read upstream's changes, port what's worth porting, and
keep the ten customizations above. The vendored scripts can be replaced wholesale; the SKILL.md
files cannot.

## Precedence

`CLAUDE.md` and direct operator instructions outrank these skills. Where `CLAUDE.md`,
`docs/poke/pokebuild-opener.md`, and `.claude/poke-invariants.md` state the same guardrail, all
copies are load-bearing — change one, change them all.

Upstream is MIT licensed; see https://github.com/obra/superpowers.
