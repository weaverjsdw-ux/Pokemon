---
name: poke-finish
description: Use when implementation on a branch is complete and tests pass, to decide how to integrate the work in this repo - merges to LOCAL main by default and never pushes without explicit operator instruction. Forked from superpowers:finishing-a-development-branch.
---

# Poke Finish — integrate a development branch

Forked from `superpowers:finishing-a-development-branch` (v6.2.0, MIT). Read
`.claude/poke-invariants.md` first.

**Core principle:** verify tests → present options → execute the operator's choice → clean up.

**Announce at start:** "Using poke-finish to complete this work."

<HARD-GATE>
**Local `main` may intentionally diverge from `origin/main`.** The default integration for this
repo is a **local** merge. Never push to any remote — and never open a PR — without explicit
operator instruction for this specific branch. A push is not implied by "the work is done".
</HARD-GATE>

## Step 1: Verify tests

```bash
.claude/scripts/poke-pytest -q
```

**If tests fail:** report the failures **with their output** and stop. The menu comes after a
green suite.

**If the suite cannot run** (exit 3 — no venv, no pytest): stop and tell the operator plainly.
Do not present the menu, do not install dependencies, and do not describe the branch as verified.
An unverified branch can still be kept as-is, but that is the operator's call to make knowingly.

**If tests pass:** continue.

## Step 2: Pre-merge sweep

Before presenting the menu, confirm on the branch diff:

- `git status` is clean and `config.yaml` / `data/state.db` are **not** staged or committed.
- No API key, webhook URL, or address appears in any commit on this branch:
  `git log -p <base>..HEAD | grep -iE "api[_-]?key|webhook|token"` — investigate any hit.
- Every commit message follows the conventional style with the right scope.
- The SDD ledger's deferred-minor and parked findings have been triaged — anything load-bearing
  is fixed, not carried into main.

Report anything found; do not silently fix a secret leak — a committed key needs the operator's
decision about rotation.

## Step 3: Determine the base branch

The base is whatever this work forked from — usually named in the plan or the branch's upstream.
In this repo that is normally local `main`. If it is not already known, ask:
"This branch split from `<best guess>` — is that correct?" Merging into the wrong base is
expensive to undo.

## Step 4: Present options

Present exactly these, and wait:

```
Implementation complete, suite green (<N> passed). What would you like to do?

1. Merge back to local <base-branch>  (default for this repo — nothing is pushed)
2. Push and open a PR                 (requires your explicit go-ahead)
3. Keep the branch as-is

Which option?
```

The integration decision is the operator's. Discarding work happens **only** in response to an
explicit request — it is not on this menu.

## Step 5: Execute the choice

### Option 1 — merge locally

```bash
git checkout <base-branch>
git merge <feature-branch>
```

Do **not** `git pull` first — this repo's local `main` may intentionally diverge from
`origin/main`, and pulling would silently reconcile that divergence. If the base is genuinely
behind a remote and should be updated, that is an operator decision; ask.

Verify the suite on the **merged result**:

```bash
.claude/scripts/poke-pytest -q
```

If it fails: stop, leave the branch in place, investigate. Nothing was pushed, so the merge is
local and recoverable (`git merge --abort`, or reset the base branch).

Once green:

```bash
git branch -d <feature-branch>
```

### Option 2 — push and open a PR

**Only on explicit operator instruction for this branch.** Confirm the branch name and target
before pushing:

```bash
git push -u origin <feature-branch>
```

Then open the PR against `<base-branch>` following any template in `.github/`, and report the URL.

### Option 3 — keep as-is

Report: "Keeping branch `<name>`. Nothing merged, nothing pushed."

### If the operator asks to discard

Only in response to an explicit request. Confirm first:

```
This will permanently delete:
- Branch <name>
- All commits: <commit-list>

Type 'discard' to confirm.
```

Wait for that exact word, then `git branch -D <feature-branch>`. No `git clean -fdx` — it would
destroy the git-ignored `.superpowers/` workspace and any local `config.yaml`.

## Quick reference

| Option | Merge | Push | Delete branch |
| --- | --- | --- | --- |
| 1. Merge locally | yes | no | yes |
| 2. Push + PR (explicit go-ahead only) | no | yes | no |
| 3. Keep as-is | no | no | no |
| Discard (explicit request only) | no | no | yes (force) |

## Common rationalizations

| Excuse | Reality |
| --- | --- |
| "Tests passed earlier this session" | Run the suite on the tree you are about to integrate. |
| "The work is done, so obviously push it" | Never. This repo's remote pushes are explicit-instruction-only. |
| "Local main is behind origin, I'll pull" | The divergence may be intentional. Ask before reconciling it. |
| "They obviously want it merged" | Present the menu and wait. |
| "'Yeah, get rid of it' counts as confirmation" | Only the typed word `discard` authorizes deletion. |
| "The suite won't run here, but the code is fine" | Then say the suite did not run. Don't call it verified. |
| "The push was rejected — force-push will fix it" | A rejected push means the remote moved. Investigate; force-push only on explicit request. |
| "`git clean -fdx` will tidy the worktree" | It destroys the SDD workspace and local config. Never run it here. |
