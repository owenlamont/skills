# Installing the dependency-adoption hook

`adoption_hook.py` is a `PreToolUse` hook on Bash. It blocks the first `uv add`,
`pnpm add` or `npm install <pkg>` of a session with an instruction to load the
`dependency-adoption` skill, and afterwards blocks any add that would install rather
than lock. Install it in your user settings — per person, committing nothing to a repo.

Claude Code, `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --script ~/.claude/skills/dependency-adoption/scripts/adoption_hook.py"
          }
        ]
      }
    ]
  }
}
```

Codex, `~/.codex/hooks.json` — the same shape, with the path where Codex installs the
skill:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "uv run --script ~/.agents/skills/dependency-adoption/scripts/adoption_hook.py"
          }
        ]
      }
    ]
  }
}
```

Codex skips a new or changed hook until you trust it: run `/hooks` once in an
interactive Codex session after adding or editing the entry.
