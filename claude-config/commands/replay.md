---
description: Free what-if for the model router — pick rules from a menu, try new cutoffs against a saved eval run, and see what would change. No API calls; the live router is untouched.
argument-hint: [saved results file, optional — defaults to the latest run]
---

Run a free what-if replay of the Jev router's eval. Saved results file: $ARGUMENTS
(if empty, use the latest run, `eval_results.csv`).

The repo is at `<ABSOLUTE-PATH-TO-REPO>`. Run every command from there.

## Hard rules
- **Free only.** Run `eval.py` only with `--replay` or `--list-rules`. Never run a plain
  `python eval.py` (that is the paid eval).
- **Never edit `router.py`** or any other file. `--set` changes cutoffs for one replay only, and the
  live router in Claude Code sessions must stay as it is.
- Every figure you report comes from the replay output. Don't estimate.

## Steps

1. **Get the rules.** Run `python eval.py --list-rules`. Build the menus from its output, never from
   memory: rules are added over time.

2. **Rule menu.** Ask with AskUserQuestion, one question per group in the output ("Tier rules",
   "Hand-off rules"), `multiSelect: true`. Each option: label = the rule's plain-English name,
   description = "today X" plus its one-line description. A question allows at most 4 options: if a
   group has more, split it ("Tier rules (1 of 2)"). One call holds at most 4 questions; use a second
   call if needed. If nothing is picked, stop.

3. **Value menu.** For each picked rule, ask one single-select question with 4 suggested values near
   today's cutoff, inside its allowed range: today ±0.1 and ±0.2 (±0.25 and ±0.5 for a 0–2 scale).
   Mark which way each goes: a **higher** cutoff makes the rule fire **less often** (fewer bumps or
   fewer hand-offs); a lower one, more often. "Other" lets the user type any value.

4. **Run two replays** of the same file:
   - baseline: `python eval.py --replay [file]`
   - what-if: `python eval.py --replay [file] --set name=value [--set name=value ...]`

   If either stops with an error, show the message and stop.

5. **Report in plain English**, baseline → what-if:
   - **Tier BELOW label (unsafe)** first. If it rose above 0, say so prominently: the change routes
     work to a cheaper model than allowed.
   - Final tier = label, and hand-off = label.
   - Each prompt in "Changed vs. the saved run": what it was, what it is now, and the label.
   - A one-line verdict: **improvement**, **trade** (fixes and breaks the same number), **worse**,
     or **no change**.
   - The caution, when it applies: a result that rests on one or two prompts sitting near a cutoff is
     probably run-to-run noise, and tuning to these 37 prompts risks overfitting. Patterns in real
     use (`routing_log.jsonl`) are better evidence.

6. **Offer next steps:** try other values, or stop. Adopting a cutoff is a real rule change: it means
   editing `router.py`, which needs the owner's approval and a paid confirming run. Don't do it as
   part of this command.
