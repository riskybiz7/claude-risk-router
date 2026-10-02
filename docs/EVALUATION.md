# Evaluation

How the router is tested, what four evaluation runs showed, and what the numbers do and don't mean.

## Method

**Two kinds of test:**

| Test | What it checks | Cost |
|---|---|---|
| `python -m unittest` (32 tests) | The rules in `apply_policy()`, the override, and the hook's fail-safes, with Jev mocked out | Free |
| `python eval.py` | Jev + rules on labeled prompts: does the router agree with the owner's labels? | 1 TypeSafe call per prompt |

**The labeled prompts** (`eval_prompts.csv`, 37 rows) are short, realistic requests written for
testing. They contain no client data. Each has:
- `expected_tier`: the *lowest* model allowed to do the work (haiku / sonnet / opus)
- `expected_action`: `delegate` (hand off to a subagent) or `keep` (main session)
- `set`: `original` (the first 20) or `new` (17 added later)

Claude drafted the labels following the owner's rules, and the owner reviewed them from run v2 onward.

**The metrics, in order of importance:**
1. **Tier below label.** The router chose a cheaper model than allowed. This is the unsafe failure;
   the target is zero.
2. **Wrong hand-off.** Work was handed off that should have stayed in the main session.
3. **Agreement.** The final tier and the hand-off decision match the labels.
4. **Tier above label.** Costs more, but isn't risky.

**Free replay.** Every run saves Jev's raw answers (`eval_results*.csv`). A rule change can be
re-scored against those saved answers without new API calls. Only a change to a question's wording
needs a fresh run.

```
python eval.py --replay                       # re-score eval_results.csv (the latest run)
python eval.py --replay path/to/saved_run.csv # or another saved run
```

Replay grades against the current labels in `eval_prompts.csv`, writes no files, and ends with a
"Changed vs. the saved run" list: every prompt whose tier or hand-off decision differs from what
that run decided. It refuses a file that lacks an answer the current rules use, rather than
treating the missing answer as 0, which would switch a rule off and give scores that look
comparable but aren't. Today only `eval_results.csv` (v4) has every answer; v1–v3 predate the
capability, bulk-work or web-research questions.

## Results

Computed from each run's saved results file, scored against the labels stored in that run:

| Run | Prompts | Jev raw pick = label | Final tier = label | Below label | Above label | Hand-off = label | Wrong hand-offs | Median latency (s) | TypeSafe tokens in / out |
|---|---|---|---|---|---|---|---|---|---|
| v1 | 20 | 19/20 | 11/20 | 0 | 9 | n/a | n/a | 0.25 | 12,735 / 1,953 |
| v2 | 37 | 33/37 | 32/37 | 0 | 5 | 32/37 | 0 | 0.20 | 33,787 / 4,798 |
| v3 | 37 | 33/37 | 33/37 | 0 | 4 | 33/37 | 0 | 0.20 | 34,157 / 4,799 |
| v4 | 37 | 31/37 | 35/37 | 0 | 2 | 35/37 | 1 | 0.19 | 35,415 / 5,501 |

**Across all four runs, no task was ever routed below its label.** Every miss erred toward the more
capable model.

Files: `eval_results_v1.csv`, `eval_results_v2.csv`, `eval_results_v3.csv`, and `eval_results.csv` (v4).

## What each run taught us

**v1: Jev was right, but the rules weren't.** Jev's own pick matched 19 of 20 labels, but after the
rules only 11 did. One question, `ambiguous_method`, fired on nearly everything:

| Labeled tier | Score range | Fired (≥ 0.5) |
|---|---|---|
| Haiku | 0.20–0.84 | 4 of 7 |
| Sonnet | 0.44–0.75 | 5 of 6 |
| Opus | 0.70–0.92 | 7 of 7 |

It caused 8 of the 9 misses; the ninth was a low-confidence bump. The question was rewritten and the
confidence cutoff raised (decisions D7, D8).

**v2: 17 new prompts, and three distinct causes of misses.**
- **A contradiction in the rules on figures.** The Q2 comps update and the 40-CIM extraction were
  pushed to Opus by their figure scores (0.78 and 0.70), so they couldn't be handed off. The owner
  decided a figure is a Sonnet minimum, not a bump (D14), and that comps updates are valuation
  drivers (D15).
- **Low confidence.** "Restyle the charts" (confidence 0.27) and the CMS press-release search (0.42)
  moved up a tier. This is working as designed.
- **Web research didn't count as bulk.** Three web-research prompts scored 0.20–0.39 on the bulk
  question, so they stayed in the main session. The owner decided web research should be handed off.

**v3: folding web research into the bulk question didn't work.** The three web-research scores rose
by only +0.03 to +0.10 (to 0.44, 0.23, and 0.47). None crossed 0.5, and no routing decision changed
compared with a free replay of the v2 answers.

**v4: web research as its own question.** Each outcome that changed, compared with v3:

| Prompt | Outcome | Cause |
|---|---|---|
| CMS price-transparency search | fixed (handed off) | New question (score 0.62) |
| U.S. Physical Therapy acquisitions search | fixed (handed off) | New question (0.94) |
| Check every link in sources.md | wrong hand-off (label: keep) | New question (0.61). Haiku work, so a cost miss, not a risk |
| Extract figures from 40 CIMs | fixed | **Noise:** confidence 0.55 → 0.60, exactly the cutoff |
| Restyle the charts | fixed | **Noise:** Jev's pick flipped between two near-tied options |

## Run-to-run noise

Jev's answers vary slightly between identical calls. Comparing v3 with v4, on answers whose question
wording didn't change (tier confidence, figure, ambiguity, valuation driver, capability):
- The average absolute change was 0.025 or less, and the largest was 0.08.
- Jev's tier pick flipped on 2 of 37 prompts, both near-ties (confidence about 0.25–0.30).

**What that means:** most routing decisions are stable, but a few sit within 0.05 of a cutoff and can
go either way between runs. The wobble is only ever between "keep" and "hand off", or between Sonnet
and Opus, never below the label. Tuning further on these 37 prompts would mean chasing noise.

## Caveats

- **Small sample.** 37 prompts; one prompt moves a score by about 3 percentage points.
- **Tuned on.** Both prompt sets have now informed decisions, so neither is a held-out test.
- **Labels are judgments.** They encode the owner's rules; a different practitioner might label some
  borderline prompts differently.
- **The eval checks routing decisions, not outcomes.** It doesn't check whether a subagent then
  completed the task correctly. That's Phase 2 (see DECISIONS.md, open question 3).
- **Token counts are TypeSafe's**, for the routing calls themselves. They aren't Claude usage, and
  this eval doesn't measure Claude-usage savings.

## Next evidence: real use

From here, the honest test is real work. Each `route:` prompt is logged to `routing_log.jsonl` with
Jev's raw answers, and each `route: [tier]` override records the router's pick next to the owner's.
After a few dozen entries, candidate rule changes can be replayed against real decisions for free.
