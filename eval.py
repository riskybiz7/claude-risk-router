"""Measure how often the router agrees with hand-labeled tiers and hand-off decisions.

Normal mode COSTS MONEY: one TypeSafe API call per row of eval_prompts.csv.
Replay mode is FREE: re-runs apply_policy() on saved answers from eval_results*.csv.

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


def replay(csv_path):
    """Replay saved Jev responses from a results CSV through apply_policy()."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"Replay file not found: {csv_path}")

    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = set(reader.fieldnames or [])
        rows = list(reader)

    # Validate essential columns needed to score tiers and apply the base policy
    required = {"expected_tier", "jev_tier", "jev_confidence", "produces_figure", "ambiguous_method", "valuation_driver"}
    missing_required = required - fieldnames
    if missing_required:
        raise ValueError(
            f"Cannot replay {path.name}: missing required column(s): {', '.join(sorted(missing_required))}"
        )

    missing_optional = []
    if "capability_score" not in fieldnames:
        missing_optional.append("capability_score (capability gate rule not applied)")
    if "bulk_work" not in fieldnames:
        missing_optional.append("bulk_work (bulk delegation rule not applied)")
    if "web_research" not in fieldnames:
        missing_optional.append("web_research (web research delegation rule not applied)")

    if missing_optional:
        print(f"Note: {path.name} is missing column(s): {'; '.join(missing_optional)}.")

    results = []
    for row in rows:
        tier_probs = {t: float(row[f"p_{t}"]) for t in TIERS if f"p_{t}" in row and row[f"p_{t}"] != ""}
        decision = apply_policy(
            jev_tier=row["jev_tier"],
            jev_confidence=float(row["jev_confidence"]),
            trigger_probabilities={t: float(row[t]) for t in TRIGGERS},
            tier_probabilities=tier_probs,
            capability_score=float(row["capability_score"]) if "capability_score" in row and row["capability_score"] != "" else 0.0,
            bulk_probability=float(row["bulk_work"]) if "bulk_work" in row and row["bulk_work"] != "" else 0.0,
            web_research_probability=float(row["web_research"]) if "web_research" in row and row["web_research"] != "" else 0.0,
        )
        final_action = "delegate" if decision.delegate else "keep"
        expected_action = row.get("expected_action", "")
        results.append(
            {
                "set": row.get("set", ""),
                "expected_tier": row["expected_tier"],
                "final_tier": decision.tier,
                "jev_tier": decision.jev_tier,
                "expected_action": expected_action,
                "final_action": final_action,
                "task": row.get("task", ""),
            }
        )
        tier_mark = "ok  " if decision.tier == row["expected_tier"] else "MISS"
        action_mark = "ok  " if final_action == expected_action else "MISS" if expected_action else "    "
        action_str = f"{expected_action:<8}->{final_action:<8}" if expected_action else f"->{final_action:<8}"
        print(
            f"tier {tier_mark} {row['expected_tier']:<6}->{decision.tier:<6} "
            f"action {action_mark} {action_str} {row.get('task', '')[:50]}"
        )

    has_sets = any(r["set"] for r in results)
    if has_sets:
        new_prompts = [r for r in results if r["set"] == "new"]
        if new_prompts:
            summarize("NEW prompts (used for the v2 decisions)", new_prompts)
        orig_prompts = [r for r in results if r["set"] == "original"]
        if orig_prompts:
            summarize("ORIGINAL prompts (used for the v1 fixes)", orig_prompts)
    summarize(f"ALL prompts (replayed from {path.name})", results)

    print("\nConfusion, tier (expected -> final):", dict(Counter((r["expected_tier"], r["final_tier"]) for r in results)))
    if any(r["expected_action"] for r in results):
        print("Confusion, action (expected -> final):", dict(Counter((r["expected_action"], r["final_action"]) for r in results)))

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
        tier_mark = "ok  " if decision.tier == row["expected_tier"] else "MISS"
        action_mark = "ok  " if final_action == row["expected_action"] else "MISS"
        print(
            f"tier {tier_mark} {row['expected_tier']:<6}->{decision.tier:<6} "
            f"action {action_mark} {row['expected_action']:<8}->{final_action:<8} {row['task'][:50]}"
        )

    with (HERE / "eval_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)

    # Both sets have now informed policy decisions (original: v1 fixes; new: v2
    # decisions), so neither is a held-out test any more. Real routed prompts in
    # routing_log.jsonl are the honest test from here on.
    summarize("NEW prompts (used for the v2 decisions)", [r for r in results if r["set"] == "new"])
    summarize("ORIGINAL prompts (used for the v1 fixes)", [r for r in results if r["set"] == "original"])
    summarize("ALL prompts", results)

    print("\nConfusion, tier (expected -> final):", dict(Counter((r["expected_tier"], r["final_tier"]) for r in results)))
    print("Confusion, action (expected -> final):", dict(Counter((r["expected_action"], r["final_action"]) for r in results)))
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
        const="eval_results.csv",
        default=None,
        metavar="FILE",
        help="Replay evaluation from saved results CSV without calling the API (default: eval_results.csv)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.replay:
        replay(args.replay)
    else:
        run_eval()


if __name__ == "__main__":
    main()

