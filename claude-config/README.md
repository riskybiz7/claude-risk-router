# Claude Code configuration

The router lives partly in Claude Code's own configuration folder (`~/.claude/`). These files are
**copies** of the live versions, kept here so the whole design can be read in one place.

| File here | Install to | Purpose |
|---|---|---|
| `commands/route.md` | `~/.claude/commands/route.md` | The routing rules, also the `/route` dry-run command |
| `agents/tier-haiku.md` | `~/.claude/agents/tier-haiku.md` | Haiku subagent: mechanical work, never derives a figure |
| `agents/tier-sonnet.md` | `~/.claude/agents/tier-sonnet.md` | Sonnet subagent: executes settled plans; cites a source for every figure |
| `agents/tier-opus.md` | `~/.claude/agents/tier-opus.md` | Opus fallback, used only when the session isn't running on Opus |
| `settings.snippet.json` | merge into `~/.claude/settings.json` | Registers the hook; sets Opus as the default model at `medium` effort |

## Install

1. Copy the `commands/` and `agents/` files to the locations above.
2. **Merge** `settings.snippet.json` into your existing `~/.claude/settings.json`. Don't replace the
   file: add the `hooks` entry alongside any hooks you already have. Replace `<ABSOLUTE-PATH-TO-REPO>`
   with this repository's path, using forward slashes.
3. Set `TYPESAFE_API_KEY` as an environment variable, and `pip install typesafe-sdk`.
4. Start a new Claude Code session so the new settings and subagents load.

## Keeping copies in sync

The live files in `~/.claude/` are what Claude Code actually uses. After editing one of them, copy it
back here so the repository stays accurate. These copies match the live files as of 2026-09-28.
