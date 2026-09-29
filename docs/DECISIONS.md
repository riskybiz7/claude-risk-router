# Decision log

Every design decision, with its reason and who made it. "Owner" means the project owner decided.
"Proposed, approved" means Claude proposed it and the owner approved it. All entries are dated
2026-09-28 unless noted. The open questions at the end are the places the owner may want to weigh in.

---

### D1. Tier by decision risk, not task size
- **Context:** The owner's routing rules (`~/.claude/commands/route.md`) existed before the router.
- **Decision:** Opus does judgment; Sonnet executes settled plans; Haiku does mechanical work and
  never produces a figure. A risk trigger escalates work.
- **Why:** In valuation work the costly failure is a *plausible* wrong number, not an obvious error.
- **Decided by:** Owner (the rules predate this log).

### D2. Jev supplies judgments; plain Python supplies policy
- **Decision:** Jev answers typed questions. Thresholds and rules live in `apply_policy()`.
- **Why:** Rules can be read, unit-tested, and re-tuned by replaying saved answers, with no new API calls.
- **Decided by:** Part of the original build.

### D3. API key in a Windows user environment variable
- **Decision:** `TYPESAFE_API_KEY` lives in Windows user environment variables, not in Claude Code's
  `settings.json`.
- **Why:** Every script can read it, it stays out of files that get printed while troubleshooting,
  and there is one copy to rotate.
- **Decided by:** Owner set it up; Claude verified it and recommended keeping it there.

### D4. Prefix `!route` changed to `route:`
- **Context:** In the Claude Code terminal, a leading `!` switches to shell mode, so `!route ...` would
  most likely run as a shell command (Windows even has a `route` command) instead of reaching the
  hook. This wasn't tested in the terminal, but the router's log showed it had never fired.
- **Decision:** Use `route:` (any capitalization). A test confirms `!route` no longer triggers.
- **Decided by:** Proposed, approved.

### D5. Subagents use model aliases
- **Decision:** `tier-haiku` / `tier-sonnet` use `model: haiku` / `model: sonnet`, not pinned IDs.
- **Why:** The pinned `claude-sonnet-5` was already a generation behind Sonnet 5.5.
- **Decided by:** Proposed, approved.

### D6. Sessions default to Opus; `tier-opus` as a fallback
- **Decision:** `"model": "opus"` in `settings.json`. A `tier-opus` subagent handles Opus-tier work
  only when the session has been switched to a cheaper model.
- **Why:** A hook can't change the session's model, so Opus work would otherwise silently run on
  whatever model the session is using.
- **Decided by:** Proposed, approved.

### D7. Ambiguity question rewritten
- **Context:** Eval v1: Jev's raw tier pick matched 19/20 labels, but only 11/20 after the rules. The
  old question ("...ambiguous or not specified?") fired on 4 of 7 Haiku-labeled and 5 of 6
  Sonnet-labeled prompts, because nearly every one-line prompt leaves *something* unspecified.
- **Decision:** It now counts only competing definitions of a financial line item, accounting
  treatment, or valuation methodology, and explicitly excludes unspecified file names, formats,
  tools, or wording.
- **Decided by:** Proposed, approved.

### D8. Confidence cutoff raised from 0.5 to 0.6
- **Why:** Jev's one wrong pick in eval v1 came with confidence 0.57. Below the cutoff, a task moves up
  a tier.
- **Decided by:** Proposed, approved. Tuned on the same 20 prompts, so later runs were needed to test it.

### D9. Capability is measured, not guessed
- **Context:** The owner asked to base model choice on Anthropic's published documentation rather
  than on personal guesses.
- **Decision:** Anthropic's hard published limits (Haiku 4.5: 200K context, Feb 2025 knowledge cutoff)
  are written into the `capability` question. Everything else about capability is left to
  measurement: the eval now, and real use and overrides later.
- **Why:** The docs give limits and general guidance, not per-task answers ("can Haiku navigate
  EDGAR?"). Anthropic's own guide says to test on your own tasks.
- **Decided by:** Owner set the direction; the split between published limits and measurement was
  proposed and approved.

### D10. Hand off only bulk work
- **Context:** The owner's goal is lower usage without losing quality. Anthropic's cost guide found
  that delegating to cheaper workers paid off mainly on bulk work, and that on work one model could
  handle alone, that model at lower effort was cheaper.
- **Decision:** The tier is a **floor**, not an assignment. Work below Opus is handed off only if it
  is bulk work; everything else stays in the main session.
- **Decided by:** Owner chose this "revised plan" over three alternatives (tier every task, measure
  first, drop Jev).

### D11. Keep Jev rather than an Opus router agent
- **Why:** An Opus router subagent would start from scratch and duplicate what the main session
  already does. Jev gives consistent, logged, tunable judgments without using Claude usage.
- **Trade-off accepted:** Jev sees only the prompt, and that prompt text goes to TypeSafe.
- **Decided by:** Owner, as part of D10's choice.

### D12. Opus default effort set to `medium`
- **Decision:** Both Opus entries in `settings.json` use `effortLevel: medium`, Anthropic's default for
  Opus 5.5. The router's design sessions ran at `xhigh`, deliberately.
- **Decided by:** Owner.

### D13. User override `route: [tier] ...`
- **Decision:** Brackets force a tier. Jev still runs, and both answers are logged, so every override
  is a labeled correction. Forcing a tier below the floor adds a WARNING. Unknown tags are rejected.
- **Decided by:** Proposed as an idea, adapted in this project's own way; approved by the owner.

### D14. A figure is a Sonnet minimum, not a bump
- **Context:** Eval v2 showed a contradiction in the rules. One said "any figure bumps a tier" (so
  Sonnet work with figures went to Opus); another said figures may be produced "at Sonnet or above".
  The result: bulk work that produces figures could never be handed off.
- **Decision:** A figure keeps work off Haiku, and that's all. Sonnet may produce figures, citing a
  source for each, and the main session checks each source before a figure is used.
- **Decided by:** Owner (option b).

### D15. Updating comps counts as a valuation driver
- **Decision:** Any task touching comps data escalates to Opus.
- **Why (owner):** Comps are used to sanity-check the model's own EBITDA margin assumptions, so an
  error in comps can move the conclusion.
- **Decided by:** Owner. Written into `route.md` trigger 3.

### D16. Web research is worth handing off, via its own question
- **Context:** Eval v3 folded web research into the bulk question. The three web-research prompts'
  scores rose by only +0.03 to +0.10 and none crossed 0.5. Eval v4 gave it a separate question: two
  of those prompts were then handed off correctly, and one link-checking task was handed off wrongly
  (a cost miss, not a risk).
- **Decision:** Hand off below Opus if the task is bulk work **or** web research.
- **Decided by:** Owner decided that web research should count; the separate question was proposed
  and approved.

### D17. Stop tuning on the eval prompts
- **Context:** Eval v4 measured run-to-run noise: answers to unchanged questions moved by 0.025 on
  average and 0.08 at most, and several decisions sit within that distance of a cutoff.
- **Decision:** Further tuning comes from real use: `routing_log.jsonl` plus overrides.
- **Decided by:** Proposed; owner agreed.

### D18. Original work only
- **Decision:** This project's code and wording are original. Nothing is copied from other
  projects; cited sources are quoted and linked.
- **Decided by:** Owner.

### D19. Publish as `claude-risk-router`
- **Decision:** A public GitHub repository under the MIT license. It started private; on 2026-09-29
  the owner decided to make it public, so developers can find it while Jev is new and contribute to
  it. The owner reviews and approves every pull request. Commits use the owner's GitHub noreply
  address, not a personal email.
  The Claude Code files the router
  depends on are copied into `claude-config/`, so the whole design is readable in one place.
  `routing_log.jsonl` is excluded (real prompts may mention clients), and the settings excerpt uses a
  placeholder path instead of the owner's home folder.
- **Decided by:** Owner (name, license, visibility, config copies); the exclusions were proposed.

---

## Open questions (owner input welcome)

1. **Low-confidence escalation cost.** When Jev is unsure (confidence below 0.6), the task moves up a
   tier. That's safe, but it sent "restyle the charts" to Opus in one run. Keep it this strict?
2. **Link checking counts as web research.** "Check every link in sources.md" was handed to Haiku.
   Accept that (it's cheap and mechanical), or tighten the web-research question?
3. **Phase 2: measuring capability.** Run the Haiku-labeled tasks for real through `tier-haiku`, and
   log whether each one succeeded or had to be escalated. That uses Claude usage.
4. **Status line.** Show the last routing decision in Claude Code's status bar? (Not built.)
5. **Haiku successor.** Haiku 4.5's earliest possible retirement is 2026-10-15. Recheck the `haiku`
   alias and the capability limits when a successor ships.
6. **Confidentiality.** Review TypeSafe's data terms before routing prompts that mention clients or deals.
7. **Related-work mention** in DESIGN.md: keep or remove?
