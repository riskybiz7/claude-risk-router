# claude-risk-router

**Risk-aware model routing for Claude Code, powered by TypeSafe's Jev.**

A Claude Code add-on that decides, per task, **which Claude model is allowed to do the work** and
**whether handing it to a cheaper model is worth it**. It is built for work where the failure that
matters is a *plausible wrong number*, not a crash: financial modeling, valuation, data analysis,
and research that feeds a decision.

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

## Where it helps

It pays off in any Claude Code session that mixes judgment calls with routine work, where a wrong
number costs more than a slow answer. The router answers two questions for each task: **what is the
lowest model that can safely do it**, and **is handing it off worth the overhead**. The examples below
come from the labeled eval set. The wording is shortened here; the exact prompts and results are in
[`eval_results.csv`](eval_results.csv).

| Task | Lowest safe model | Who does it | Why |
|---|---|---|---|
| Gut-check a financial-model assumption: "Is the terminal growth rate in the DCF reasonable?" | Opus | Main session | Touches a valuation driver, so the judgment stays with the strongest model |
| "Should this DCF use a mid-year discounting convention?" | Opus | Main session | A methodology choice that moves the answer |
| Decide how to treat a line item that is defined differently in two years of filings | Opus | Main session | Someone has to choose the definition, and that choice drives the numbers |
| Read 40 company documents and table each one's revenue and EBITDA with page citations | Sonnet | Sonnet subagent | Bulk reading that produces figures: worth handing off, but never to Haiku |
| Search the web for a company's 2026 acquisitions and list each with a source link | Sonnet | Sonnet subagent | Multi-page web research, which is cheaper to hand off than to do in the main session |
| Pull enrollment figures by state from a public data file into a CSV | Sonnet | Main session | Jev picked Haiku; the rules raised it to Sonnet because the output contains figures |
| Download one exhibit from each of five companies' annual filings | Haiku | Haiku subagent | Bulk, mechanical, and no figures to get wrong |
| Fix a failing unit test and re-run the suite | Sonnet | Main session | Too small for a hand-off to pay for itself |
| List every spreadsheet in a folder with its size and date | Haiku | Main session | Same: the brief would cost more than the task |

The risk questions are written for finance and analytical work. The capability and hand-off rules
apply to any task, and the eval includes coding and file-handling prompts. These are results from one
eval run of 37 prompts; [docs/EVALUATION.md](docs/EVALUATION.md) covers the misses and run-to-run
noise.

## Use it

Start a prompt with `route:` (any capitalization):

```
route: Download the FY2023-FY2025 10-K PDFs for HCA and Tenet into the filings folder
```

Not `!route`: in the Claude Code terminal, a leading `!` switches to shell mode, so the prompt would
never reach the hook.

The hook adds a note like this to Claude's context:

```
[Jev router] Route: HAIKU. Delegate the execution to the `tier-haiku` subagent (latest haiku): this is bulk work, where handing off saves usage.
  Jev pick: haiku (confidence 0.99; haiku 0.99, sonnet 0.01, opus 0.00)
  Triggers: produces_figure 0.12, ambiguous_method 0.01, valuation_driver 0.06
  Hand-off signals: bulk_work 0.62, web_research 0.42, capability 1.17 of 2
  Policy: bulk work 0.62 -> hand off to tier-haiku
  This is advisory. Apply route.md: escalate further if the work turns out riskier than it looks; never route below this tier.
```

These are Jev's real scores for this prompt from the v4 eval run (the first row of
[`eval_results.csv`](eval_results.csv)). Scores vary slightly from run to run; see
[docs/EVALUATION.md](docs/EVALUATION.md).

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
| `test_policy.py` | 35 unit tests: `python -m unittest -v` (free) |
| `eval.py`, `eval_prompts.csv` | Labeled eval: `python eval.py` (**paid**: one TypeSafe call per prompt), or `python eval.py --replay` (free offline replay) |
| `eval_results*.csv` | Saved raw answers from runs v1–v4, for comparison and free replay |
| `routing_log.jsonl` | Every real routed prompt, with Jev's raw answers and any override (local only) |
| `docs/` | Design, decision log, evaluation |
| `claude-config/` | Copies of the Claude Code files the router needs: routing rules (`route.md`), the three tier subagents, and a settings excerpt |

## Setup

1. A TypeSafe account: create one with [TypeSafe](https://docs.typesafe.ai) and add at least
   USD 5 of credit, the minimum to use Jev (as of September 2026). Then get an API key from the
   account.
2. Python 3 with the TypeSafe SDK: `pip install typesafe-sdk`.
3. Set `TYPESAFE_API_KEY` as a **user** environment variable (on Windows: System Properties →
   Environment Variables), then restart the terminal.
4. Install the Claude Code files as described in [claude-config/README.md](claude-config/README.md):
   copy the routing rules and subagents into `~/.claude/`, and merge the settings excerpt, which
   registers `hook.py` as a `UserPromptSubmit` hook.

**Platforms:** tested only on Windows 11. On macOS or Linux, the hook command may need `python3`
instead of `python`. Reports and fixes are welcome (see [Contributing](#contributing)).

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

## Contributing

Issues and pull requests are welcome. The owner reviews and approves every pull request before it
is merged. Good places to start:

- **macOS and Linux.** The router has only been tested on Windows 11. Setup notes or fixes for other
  platforms help.
- **Outcome checks.** The eval checks routing decisions, not whether the subagent then finished the
  task correctly ([Known limitations](docs/DESIGN.md#8-known-limitations)).
- **Routing misses.** If a real task routes to the wrong tier, open an issue with the prompt (with
  anything confidential removed) and the router's note.

Before opening a pull request, run the unit tests: `python -m unittest -v`. A change to the rules
can be re-scored for free against the saved answers in `eval_results*.csv`; a change to a question's
wording needs a fresh, paid eval run. See [docs/EVALUATION.md](docs/EVALUATION.md).
