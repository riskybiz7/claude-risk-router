# claude-risk-router

**Risk-aware model routing for Claude Code, powered by TypeSafe's Jev.**

A Claude Code add-on that decides, per task, **which Claude model is allowed to do the work** and
**whether handing it to a cheaper model is worth it**. It was built for healthcare valuation and
transaction advisory, where the failure that matters is a plausible wrong number, not a crash.

It uses [TypeSafe's](https://docs.typesafe.ai) Jev model to answer seven quick yes/no-style
questions about a task. Plain, unit-tested Python rules then turn those answers into a routing
decision. The main Claude session (Opus) keeps the judgment work and hands off only bulk or research
work to cheaper subagents (Sonnet or Haiku).

- **Why and how:** [docs/DESIGN.md](docs/DESIGN.md)
- **Every decision and who made it:** [docs/DECISIONS.md](docs/DECISIONS.md)
- **How well it works:** [docs/EVALUATION.md](docs/EVALUATION.md)

## At a glance

| | |
|---|---|
| **Goal** | Use cheaper models only where they are safe *and* able, and hand off only where it saves usage |
| **Safety rule** | When unsure, route **up**. A figure never comes from Haiku. Opus-tier work never leaves the main session |
| **Latest eval (v4)** | 37 labeled prompts: tier 35/37, hand-off decision 35/37, **0 routed below label** |
| **Routing cost** | 1 TypeSafe call per routed prompt (median 0.19 s in v4); unrouted prompts: hook exits in a median 38 ms and sends nothing |
| **Tests** | 32 unit tests (free), plus a paid labeled eval with free offline replay |

## Use it

Start a prompt with `route:` (any capitalization):

```
route: download the FY2023-FY2025 10-Ks for HCA and Tenet
```

Not `!route`: in the Claude Code terminal, a leading `!` switches to shell mode, so the prompt would
never reach the hook.

The hook adds a note like this to Claude's context:

```
[Jev router] Route: HAIKU. Delegate the execution to the `tier-haiku` subagent (latest haiku): this is bulk work, where handing off saves usage.
  Jev pick: haiku (confidence 0.91; haiku 0.93, sonnet 0.06, opus 0.01)
  Triggers: produces_figure 0.04, ambiguous_method 0.03, valuation_driver 0.01
  Hand-off signals: bulk_work 0.88, web_research 0.05, capability 0.95 of 2
```

(The numbers above are illustrative, not real output.)

**Override:** put a tier in brackets right after the prefix to choose the model yourself:

```
route: [sonnet] pull Q2 EBITDA for the comps set from the new 10-Qs
```

- `[haiku]` / `[sonnet]` hand the task to that tier's subagent; `[opus]` keeps it in the main session.
- Jev still runs, and the log stores its pick next to yours, so every override is a labeled
  correction for re-tuning.
- Forcing a tier below the risk floor is allowed but never silent: the note carries a WARNING.
- An unknown tag such as `[sonet]` is rejected with a message, not ignored.

Prompts without `route:` are never sent anywhere.

## How it decides (summary)

1. **Tier: the lowest model allowed.**
   - Risk: an ambiguous finance methodology, a valuation driver (including comps), or low confidence
     from Jev moves the task up one tier.
   - A figure means at least Sonnet.
   - Open-ended work means at least Sonnet (the capability gate uses Anthropic's published Haiku limits).
2. **Hand off or keep.** Below Opus, hand off only bulk work or multi-page web research; everything
   else stays in the main session.
3. **Any failure** (no API key, timeout) routes the task as Opus work.

Full rules, thresholds, and reasons: [docs/DESIGN.md](docs/DESIGN.md).

## Files

In this folder:

| File | Purpose |
|---|---|
| `router.py` | The seven questions, the policy rules, the override, and the Jev API call |
| `hook.py` | The Claude Code `UserPromptSubmit` hook: prefix, override tag, fail-safe, logging |
| `test_policy.py` | 32 unit tests: `python -m unittest -v` (free) |
| `eval.py`, `eval_prompts.csv` | Labeled eval: `python eval.py` (**paid**: one TypeSafe call per prompt) |
| `eval_results*.csv` | Saved raw answers from runs v1–v4, for comparison and free replay |
| `routing_log.jsonl` | Every real routed prompt, with Jev's raw answers and any override (local only) |
| `docs/` | Design, decision log, evaluation |
| `claude-config/` | Copies of the Claude Code files the router needs: routing rules (`route.md`), the three tier subagents, and a settings excerpt |

## Setup

1. Python 3 with the TypeSafe SDK: `pip install typesafe-sdk`.
2. Set `TYPESAFE_API_KEY` as a **user** environment variable (on Windows: System Properties →
   Environment Variables), then restart the terminal.
3. Install the Claude Code files as described in [claude-config/README.md](claude-config/README.md):
   copy the routing rules and subagents into `~/.claude/`, and merge the settings excerpt, which
   registers `hook.py` as a `UserPromptSubmit` hook.

## Uninstall

Remove the `"hooks"` block from `~/.claude/settings.json` (or restore
`~/.claude/settings.json.pre-jev-router`), then delete `~/.claude/agents/tier-haiku.md`,
`tier-sonnet.md`, and `tier-opus.md`. Remove `"model": "opus"` if you no longer want sessions
pinned to Opus.

## Status

- **Self-refining by design.** No threshold is final. Real routed prompts and overrides in
  `routing_log.jsonl` are the evidence for the next round of tuning ([docs/EVALUATION.md](docs/EVALUATION.md)).
- The capability (1.5), bulk (0.5), and web-research (0.5) cutoffs are starting values, **not
  calibrated**.
- Open questions for the owner: [docs/DECISIONS.md](docs/DECISIONS.md#open-questions-owner-input-welcome).
