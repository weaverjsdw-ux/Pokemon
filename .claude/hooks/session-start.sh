#!/bin/bash
# SessionStart hook — make the test suite runnable in Claude Code on the web.
#
# Why this exists: CLAUDE.md's canonical test command is `.venv/Scripts/python.exe -m pytest -q`,
# the operator's Windows venv. A remote container has no venv and no pytest, so the suite cannot
# run at all — and the poke-* skills correctly refuse to claim a green suite or to install
# dependencies without operator go-ahead. That combination stops an agent on its first task,
# every time. This hook does the setup once, at session start, so the agent never has to ask.
#
# It installs ONLY what requirements-dev.txt already declares (requests, PyYAML, polyline,
# pytest). It adds nothing to the project's dependency footprint — that stays exactly as
# committed, per CLAUDE.md.
#
# Local sessions are a no-op: the operator's own .venv is theirs to manage.
set -euo pipefail

# Remote (Claude Code on the web) only.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# Idempotent: a venv that can already import the deps is left alone, so a resumed or compacted
# session re-runs this in a second instead of rebuilding.
if [ -x .venv/bin/python ] && .venv/bin/python -c "import pytest" >/dev/null 2>&1; then
    echo "session-start: .venv already usable"
    exit 0
fi

echo "session-start: provisioning .venv for the network-mocked test suite"
python3 -m venv .venv
.venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

# Prove it before declaring success — a hook that "succeeds" while leaving pytest unimportable
# would hand the session a false green, which is the exact failure this repo cannot absorb.
if ! .venv/bin/python -c "import pytest, requests, yaml, polyline" >/dev/null 2>&1; then
    echo "session-start: FAILED — dependencies did not import; the suite will NOT run." >&2
    echo "session-start: report this to the operator; do not claim a green suite." >&2
    exit 1
fi

echo "session-start: ready — $(.venv/bin/python -m pytest --version 2>&1 | head -1)"
echo "session-start: run the suite with .claude/scripts/poke-pytest -q"
