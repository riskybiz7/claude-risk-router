"""Measure how often the router agrees with hand-labeled tiers and hand-off decisions.

Normal mode COSTS MONEY: one TypeSafe API call per row of eval_prompts.csv.
Replay mode is FREE: re-runs apply_policy() on saved answers from a results CSV,
grades against the current labels in eval_prompts.csv, writes no files, and lists
the prompts whose decision changed. Only runs saved with every answer the current
rules use can be replayed (today: eval_results.csv and eval_results_v4.csv).

Run from this folder:
  python eval.py                            # paid eval run via TypeSafe API
  python eval.py --replay                   # free replay of eval_results.csv
  python eval.py --replay eval_results.csv  # free replay of a specific results CSV

eval_prompts.csv columns:
  expected_tier    lowest tier allowed to do the work (haiku / sonnet / opus)
  expected_action  delegate (hand off to the tier's subagent) or keep (main loop)
  set              original = the first 20 prompts, which the 2026-09-28 policy
                   changes were tuned on; new = prompts written afterwards. Only
                   the "new" scores are an honest test of those changes.
"""

import argparse
import csv
import time
from collections import Counter
from pathlib import Path

from router import TIERS, TRIGGERS, apply_policy, ask_jev

HERE = Path(__file__).parent


def summarize(label, results):
    """Print one block of scores for a group of results."""
    n = len(results)
    if n == 0:
        return
    tier_hits = sum(r["final_tier"] == r["expected_tier"] for r in results)
    jev_hits = sum(r["jev_tier"] == r["expected_tier"] for r in results)
    has_action = any(r.get("expected_action") for r in results)
    action_hits = sum(r["final_action"] == r["expected_action"] for r in results) if has_action else 0
    # The failure that matters most: routed BELOW the expected tier.
    under = sum(TIERS.index(r["final_tier"]) < TIERS.index(r["expected_tier"]) for r in results)
    over = sum(TIERS.index(r["final_tier"]) > TIERS.index(r["expected_tier"]) for r in results)
    handed_off_wrongly = sum(r["final_action"] == "delegate" and r["expected_action"] == "keep" for r in results) if has_action else 0
    kept_wrongly = sum(r["final_action"] == "keep" and r["expected_action"] == "delegate" for r in results) if has_action else 0

    print(f"\n== {label}: {n} prompts ==")
    print(f"Final tier matches label:                     {tier_hits}/{n}")
    print(f"Jev's raw pick matches label (before policy): {jev_hits}/{n}")
    print(f"Tier BELOW label (unsafe):                    {under}")
    print(f"Tier ABOVE label (costly, not unsafe):        {over}")
    if has_action:
        print(f"Hand-off decision matches label:              {action_hits}/{n}")
        print(f"  handed off, label says keep:                {handed_off_wrongly}")
        print(f"  kept, label says hand off:                  {kept_wrongly}")


def print_row(r):
    """Print one prompt's result line (same format for paid runs and replays)."""
    tier_mark = "ok  " if r["final_tier"] == r["expected_tier"] else "MISS"
    action_mark = "ok  " if r["final_action"] == r["expected_action"] else "MISS"
    print(
        f"tier {tier_mark} {r['expected_tier']:<6}->{r['final_tier']:<6} "
        f"action {action_mark} {r['expected_action']:<8}->{r['final_action']:<8} {r['task'][:50]}"
    )


def print_report(results, all_label):
    """Print the score blocks and confusion counts (same for paid runs and replays)."""
    # Both sets have now informed policy decisions (original: v1 fixes; new: v2
    # decisions), so neither is a held-out test any more. Real routed prompts in
    # routing_log.jsonl are the honest test from here on.
    summarize("NEW prompts (used for the v2 decisions)", [r for r in results if r["set"] == "new"])
    summarize("ORIGINAL prompts (used for the v1 fixes)", [r for r in results if r["set"] == "original"])
    summarize(all_label, results)

    print("\nConfusion, tier (expected -> final):", dict(Counter((r["expected_tier"], r["final_tier"]) for r in results)))
    print("Confusion, action (expected -> final):", dict(Counter((r["expected_action"], r["final_action"]) for r in results)))


def load_labels(labels_path):
    """Read eval_prompts.csv into a lookup keyed on the exact task text (like a VLOOKUP)."""
    with Path(labels_path).open(encoding="utf-8") as f:
        return {row["task"]: row for row in csv.DictReader(f)}


# Every column apply_policy() needs from a saved run, and the rule that uses it.
# A file missing any of them is rejected: treating a missing answer as 0 would
# switch the rule off silently and give scores that look comparable but are not.
REPLAY_COLUMNS = {
    "task": "matching the prompt to its label in eval_prompts.csv",
    "jev_tier": "the starting tier",
    "jev_confidence": "the low-confidence escalation rule",
    "produces_figure": "the Haiku hard floor",
    "ambiguous_method": "the escalation rule",
    "valuation_driver": "the escalation rule",
    "capability_score": "the capability gate",
    "bulk_work": "the hand-off rule",
    "web_research": "the hand-off rule",
    "final_tier": 'the "Changed vs. the saved run" report',
    "final_action": 'the "Changed vs. the saved run" report',
}


def replay(csv_path, labels_path=HERE / "eval_prompts.csv"):
    """Re-score a saved run with the current rules. FREE: no TypeSafe calls, writes no files.

    Uses Jev's saved answers from csv_path and the CURRENT labels from labels_path,
    and reports which prompts would now get a different tier or hand-off decision.
    """
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Replay file not found: {csv_path}")

    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        rows = list(reader)

    missing = [col for col in REPLAY_COLUMNS if col not in fieldnames]
    if missing:
        details = "; ".join(f"{col} (needed for {REPLAY_COLUMNS[col]})" for col in missing)
        raise ValueError(
            f"Cannot replay {path.name}: missing column(s): {details}. "
            f"Only runs saved with every answer the current rules use can be replayed."
        )

    labels = load_labels(labels_path)
    unlabeled = [row["task"] for row in rows if row["task"] not in labels]
    if unlabeled:
        raise ValueError(
            f"Cannot replay {path.name}: {len(unlabeled)} prompt(s) not found in "
            f"{Path(labels_path).name}, e.g. {unlabeled[0][:80]!r}"
        )

    results = []
    for row in rows:
        label = labels[row["task"]]
        decision = apply_policy(
            jev_tier=row["jev_tier"],
            jev_confidence=float(row["jev_confidence"]),
            trigger_probabilities={t: float(row[t]) for t in TRIGGERS},
            tier_probabilities={t: float(row[f"p_{t}"]) for t in TIERS if row.get(f"p_{t}")},
            capability_score=float(row["capability_score"]),
            bulk_probability=float(row["bulk_work"]),
            web_research_probability=float(row["web_research"]),
        )
        result = {
            "set": label["set"],
            "expected_tier": label["expected_tier"],
            "final_tier": decision.tier,
            "jev_tier": decision.jev_tier,
            "expected_action": label["expected_action"],
            "final_action": "delegate" if decision.delegate else "keep",
            "saved_tier": row["final_tier"],
            "saved_action": row["final_action"],
            "task": row["task"],
        }
        results.append(result)
        print_row(result)

    print_report(results, f"ALL prompts (replayed from {path.name})")

    not_scored = len(labels) - len(results)
    if not_scored > 0:
        print(f"\nNote: {not_scored} prompt(s) in {Path(labels_path).name} are not in {path.name} and were not scored.")

    changed = [
        r for r in results
        if (r["final_tier"], r["final_action"]) != (r["saved_tier"], r["saved_action"])
    ]
    print(f"\n== Changed vs. the saved run: {len(changed)} of {len(results)} prompts ==")
    for r in changed:
        print(
            f"tier {r['saved_tier']:<6}->{r['final_tier']:<6} "
            f"action {r['saved_action']:<8}->{r['final_action']:<8} {r['task'][:50]}"
        )

    return results


def run_eval():
    with (HERE / "eval_prompts.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []
    for row in rows:
        start = time.perf_counter()
        response, decision = ask_jev(row["task"])
        latency = time.perf_counter() - start
        final_action = "delegate" if decision.delegate else "keep"
        results.append(
            {
                "set": row["set"],
                "expected_tier": row["expected_tier"],
                "final_tier": decision.tier,
                "jev_tier": decision.jev_tier,
                "expected_action": row["expected_action"],
                "final_action": final_action,
                "jev_confidence": decision.jev_confidence,
                **{f"p_{t}": decision.tier_probabilities.get(t) for t in TIERS},
                **{t: decision.trigger_probabilities[t] for t in TRIGGERS},
                "capability_score": decision.capability_score,
                "bulk_work": decision.bulk_probability,
                "web_research": decision.web_research_probability,
                "reasons": " | ".join(decision.reasons),
                "latency_s": latency,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "task": row["task"],
            }
        )
        print_row(results[-1])

    with (HERE / "eval_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    print_report(results, "ALL prompts")
    latencies = sorted(r["latency_s"] for r in results)
    print(f"Latency seconds: median {latencies[len(latencies) // 2]:.2f}, max {latencies[-1]:.2f}")
    tokens_in = sum(r["input_tokens"] or 0 for r in results)
    tokens_out = sum(r["output_tokens"] or 0 for r in results)
    print(f"TypeSafe tokens: {tokens_in} in, {tokens_out} out")
    print("Wrote eval_results.csv")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run or replay routing policy evaluation."
    )
    parser.add_argument(
        "--replay",
        nargs="?",
        const=str(HERE / "eval_results.csv"),
        default=None,
        metavar="FILE",
        help="Replay evaluation from saved results CSV without calling the API (default: eval_results.csv)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.replay:
        try:
            replay(args.replay)
        except (FileNotFoundError, ValueError) as err:
            raise SystemExit(f"Replay stopped: {err}")
    else:
        run_eval()


if __name__ == "__main__":
    main()
