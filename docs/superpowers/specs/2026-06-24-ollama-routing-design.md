# Ollama Local Routing — Design Spec
**Date:** 2026-06-24  
**Scope:** Global (all Claude Code sessions + all Codex sessions)

---

## Goal

Route lightweight, context-free tasks to a local Ollama model (`qwen3.5:9b`) instead of consuming Claude API tokens. Claude/Codex makes the call silently, returns the result, and falls back to answering itself if Ollama is unavailable. No user action required.

---

## The Stack

- **Ollama:** `http://localhost:11434` (host machine, bound to 0.0.0.0, firewalled to Docker/WSL subnet only)
- **Models:**
  - `qwen3.5:9b` — default for all routed tasks (text, code snippets, vision)
  - `qwen3-vl-fast:latest` — only if user explicitly requests vision-optimized output
  - `gemma4:latest` — not used for routing
- **Odysseus (Open WebUI):** `http://localhost:7000` — UI layer; not used for API calls
- **Hardware:** RTX 3070 8 GB, ~80/20 GPU/CPU split on `qwen3.5:9b`

---

## Files Changed

| File | Action |
|------|---------|
| `C:/Users/Weave/.claude/CLAUDE.md` | Create (global Claude Code instructions) |
| `C:/Users/Weave/OneDrive/Desktop/AGENTS.md` | Append routing section |

---

## Routing Rules

### Tier 1 — Fast Path (always Ollama, no deliberation)

Task matches one of these types:
1. Summarize text or a document passage
2. Explain a concept, term, acronym, or error message (no files needed)
3. Reformat or convert content (JSON↔YAML, CSV→markdown table, casing conversions on pasted text, etc.)
4. Proofread or improve prose
5. Draft boilerplate (email, commit message draft, comment template, README section)
6. Standalone Q&A answerable from general knowledge
7. Translate text
8. Generate a simple regex, SQL query, or single-expression snippet *for user review before use*

### Tier 2 — Judgment Gate (Ollama if ALL four pass)

- No tool calls needed (no Read, Edit, Write, Bash, Glob, Grep)
- No file or codebase content required to answer correctly
- Answer doesn't depend on what's already happened in this session
- Output won't feed directly into another tool or structured downstream process without review

### Tier 3 — Hard NO (always Claude)

**Requires tools Ollama can't use:**
- Needs Read, Edit, Write, Bash, Glob, or Grep
- Needs actual file or code content to answer (reading to explain ≠ general explanation)
- Needs web search or real-time data

**Doctrine/calibration-sensitive:**
- Any 4THEBOT or LEGGO workflow step: grading, mentor closeout, advisor session, log authoring, gate review, FL adjudication, calibration language
- Any math or signal touching a trade decision

**Session/context-dependent:**
- Answer depends on prior tool results from this session
- Output goes directly to commit, deploy, or structured downstream consumer without review

**Complexity ceiling:**
- Complex enough that you'd normally reach for the advisor
- Requires structured JSON schema output for downstream tool consumption

---

## Call Mechanics

PowerShell block, run silently. `$null` return = fall through to Claude.

```powershell
try {
  $body = @{
    model    = "qwen3.5:9b"
    stream   = $false
    think    = $false
    messages = @(
      @{ role = "system"; content = "Concise, direct. No flattery, no preamble. Reason first, answer second." }
      @{ role = "user";   content = "<task prompt — stripped to essentials, no session history>" }
    )
  } | ConvertTo-Json -Depth 4

  $r = Invoke-RestMethod `
    -Uri "http://localhost:11434/api/chat" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) `
    -TimeoutSec 60

  "[local: qwen3.5:9b] " + $r.message.content
} catch {
  $null
}
```

**Key decisions baked in:**
- `think = $false` — disables internal reasoning chain; keeps latency low for small tasks
- `-TimeoutSec 60` — handles cold model loads (~5s) without hanging indefinitely
- UTF-8 byte encoding — prevents corruption on Windows PowerShell 5.1 with non-ASCII input
- System prompt injected at `system` role — applies no-flattery preset to direct API calls (bypasses Odysseus UI preset)
- Strip prompt to essentials — only the task goes to Ollama, no session context, no routing reasoning
- `[local: qwen3.5:9b]` prefix — one-liner transparency without being intrusive

---

## Fallback Behavior

| Condition | Result |
|-----------|--------|
| Ollama unreachable | Catch silently, Claude answers |
| Ollama returns empty or refuses | Treat as failure, Claude answers |
| Model swapping (loading delay) | TimeoutSec 60 covers ~5s load + inference; if exceeded, Claude answers |
| Task misrouted (wrong tier) | User corrects; Claude answers going forward in that session |

---

## Future Extension Note

If a faster/smaller model is pulled later (e.g., `qwen3:4b`, `phi4-mini`), the model name in the instruction is the only thing that changes. The CLAUDE.md should treat the model name as a named constant — one place to update.

---

## Out of Scope

- Odysseus HTTP API — routing goes directly to Ollama; Odysseus UI is for interactive use only
- Per-project enable/disable — global by default; a project-level `CLAUDE.md` with `OLLAMA_ROUTING: disabled` can override
- Slash command — no `/local` command; routing is fully autonomous
- Streaming responses — `stream = $false` always; appropriate for small tasks
