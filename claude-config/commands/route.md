---
description: Dry-run the model router on a task — classify it, assign a tier per subtask, and show the dispatch plan before spending execution tokens.
argument-hint: [task description]
---

Route this task, but **do not execute any of it**: $ARGUMENTS

You are performing a dry run of the routing doctrine stated below. The doctrine is self-contained
in this file — do not go looking for a project spec. If the current project's `CLAUDE.md` has its
own routing section or agent roster, that overrides this one; say so and route by theirs instead.

## The doctrine

**The main loop stays on the highest tier and orchestrates.** It plans, decides, and delegates
bulk execution. Planning is never delegated.

**Tier by decision risk, not task size.**

- **Opus (main loop, never delegated)** — judgment calls; deciding whether an answer is *right*
  rather than merely computed; planning; the final read of any verification or fact-check report;
  anything where being wrong costs real money, credibility, or a decision.
  *One exception:* if the session itself is not running on Opus (the user switched models),
  delegate Opus-tier work to the `tier-opus` subagent with a complete brief rather than doing it
  on a lower tier. Opus work never runs below Opus.
- **Sonnet** — script edits plus the rebuild/verify loop; building an artifact from a
  settled spec; sourcing and research with citations; writing up a log once the outcome is decided;
  programmatic re-footing and reconciliation.
- **Haiku** — file downloads, archive population, checksums, manifest rows; grep/glob
  sweeps returning raw excerpts and paths; file inventory; running an *existing, unmodified* script
  and returning its stdout verbatim. Not for open-ended work: an unknown location to search for,
  several sources to compare, a single document of hundreds of pages read in full, or anything that
  depends on knowing events after early 2025 without looking them up (Haiku 4.5's published limits:
  200K-token context, Feb 2025 reliable knowledge cutoff).

**A tier is a floor, not an assignment. Delegate only when there is bulk to hand off.** Hand
Sonnet- or Haiku-tier work to its subagent only when it means working through many independent
pieces (many filings, pages, documents, or records, each needing its own lookup or reading), web
research that means searching and reading several web pages, or more reading than fits comfortably
in one session. Otherwise the main loop does the work itself: its model
is at least as capable as the floor, and handing off a single, small task costs a brief, a cold
start, and a read-back that doing it inline does not. Anthropic measured the same thing: delegating to
cheaper workers saved money mainly on bulk work, and on work one model could handle alone, that model
at lower effort was cheaper ("Optimizing for cost and intelligence", platform.claude.com).

**Haiku hard floor: a Haiku agent never derives, sums, reconciles, or states a figure of its own.**
Any number reaching a model, memo, or decision is produced at Sonnet or above. This is a floor, not
a bump: a figure by itself does not push Sonnet work to Opus. Sonnet produces figures with a cited
source for each, and the main loop checks those sources before any figure is used (see Return
contract).

**Escalation triggers — any one of triggers 2–5 bumps the subtask up a tier** (trigger 1 is the
Haiku hard floor above):
1. the output will contain a number that reaches a model, memo, or decision — at least Sonnet;
2. a line-item definition or methodology is ambiguous;
3. the task touches a valuation driver, discount rate, or other override that sets the answer. A
   valuation driver is any input whose value can move the conclusion, including benchmark data used
   to test the model's own assumptions — e.g. updating comps EBITDA, because comps sanity-check the
   model's EBITDA margin assumptions;
4. an agent returns "unclear" or a non-empty `UNCERTAIN` block;
5. a second failed attempt — escalate rather than retry.

**Escalation is automatic; demotion never is.** Route downward only once the answer is already
decided and the subagent is purely executing.

**Return contract.** Every delegated agent ends with `DONE:` / `FILES:` / `FIGURES:` / `UNCERTAIN:`;
Haiku agents assert `FIGURES: none derived`. **Never propagate a subagent's figure into a
deliverable without opening the cited source directly** — delegation moves the labor, not the
traceability obligation. A non-empty `UNCERTAIN` block is trigger #4 and is never silently accepted.

**Why this does not trade accuracy for speed.** Delegation buys cost, not speed. Cheap models are
kept away from producing figures at all, so their residual errors are *detectable* (missing file,
empty result, check row off zero) rather than *plausible*. The plausible wrong number is the
failure this doctrine exists to catch, and it stays at the top tier.

## Output

Produce exactly these five sections, then stop and wait for approval.

**1. Classification.** One or two sentences: what kind of task this is, and whether it is a single
unit of work or needs decomposing. If it needs decomposing, list the subtasks — everything below is
per-subtask.

**2. Tier assignment.** A table: subtask · tier (opus / sonnet / haiku) · the specific rule above
that put it there. Cite the rule, do not just assert the tier. If a subtask started lower and was
escalated, say which of the five triggers fired.

**3. Dispatch plan.** Which agent handles which subtask, in what order, and — stated explicitly —
what stays in the main loop and why. Note anything that can run in parallel. Use whatever agents
the current project actually defines; if it defines none, say which generic subagent type you would
use and what its return contract would be.

**4. Escalation risks.** What could come back needing a higher tier, and what the tell would be. Be
specific: name the figure, the ambiguity, or the file that would trigger it. If a subtask is one
where a wrong answer would be *plausible* rather than *detectable*, flag it here — that is the
class of failure this doctrine exists to catch.

**5. Verification gate.** What runs at the end, what it is given, and what it is asked to verify.
If the project defines a fact-checker or reviewer agent, name it; otherwise state the check
directly (re-foot the tables, run the suite, open each cited source). If the task produces no
figure and needs no gate, say so explicitly rather than omitting the section.

Then stop. Do not dispatch anything, edit anything, or begin the work. Wait for approval, and
expect the routing to be corrected — that is the point of the command.
