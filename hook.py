"""Claude Code UserPromptSubmit hook for the Jev router.

Opt-in only: does nothing unless the prompt starts with `route:` (any case).
Only those prompts are sent to TypeSafe's API; everything else never leaves the
machine. (Not `!route`: in the Claude Code terminal a leading `!` switches to
shell mode, so the prompt would never reach this hook.)

Optional override: `route: [haiku|sonnet|opus] task` runs the task on that tier.
Jev is still asked, so the log records the router's own pick next to the user's.

Claude Code passes the hook a JSON object on stdin (it includes the typed
prompt). For UserPromptSubmit, anything printed to stdout is added to Claude's
context for that turn -- that is how the routing note reaches the main loop.

Fail-safe: if anything goes wrong (no key, timeout, bad response), the note
says "keep it at Opus". An error can only move work up a tier.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "route:"  # compared case-insensitively, so "Route:" works too
LOG_FILE = Path(__file__).parent / "routing_log.jsonl"

# Optional override right after the prefix: `route: [sonnet] do the thing`.
OVERRIDE_TAG = re.compile(r"^\[([A-Za-z]+)\]\s*(.*)$", re.DOTALL)
# Listed here rather than imported from router.py, so the fail-safe below
# still works if router.py itself fails to import.
TIER_NAMES = ("haiku", "sonnet", "opus")


def main():
    # Windows consoles default to cp1252; force UTF-8 so any character prints.
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return  # not something we understand; stay silent

    prompt = payload.get("prompt", "")
    if not prompt.lstrip().lower().startswith(PREFIX):
        return  # not opted in: print nothing, send nothing

    task = prompt.lstrip()[len(PREFIX):].strip()

    override = None
    tag = OVERRIDE_TAG.match(task)
    if tag:
        override, task = tag.group(1).lower(), tag.group(2).strip()
        if override not in TIER_NAMES:
            # A typo like [sonet] must not be silently ignored.
            print(
                f"[Jev router] Unknown override `[{tag.group(1)}]`; use [haiku], "
                "[sonnet], or [opus]. Nothing was routed."
            )
            return

    if not task:
        print("[Jev router] `route:` with no task text; nothing to route.")
        return

    try:
        # Imported here so non-routed prompts never pay the import cost.
        from router import apply_override, ask_jev, format_note

        # Jev runs even with an override, so the log shows what the router
        # would have picked next to what the user chose.
        response, decision = ask_jev(task)
        if override:
            decision = apply_override(decision, override)
        print(format_note(decision))
        _log(task, decision, response)
    except Exception as error:  # fail safe, upward
        # Self-contained on purpose: if router.py itself failed to import,
        # importing anything from it here would crash the fail-safe too.
        if override:
            where = (
                "keep it in the main loop if this session is on Opus, otherwise "
                "delegate it to the `tier-opus` subagent"
                if override == "opus"
                else f"delegate it to the `tier-{override}` subagent"
            )
            print(
                f"[Jev router] Routing unavailable ({type(error).__name__}). User "
                f"override: {override}, so {where}. No risk checks ran; verify the "
                "output against its sources."
            )
        else:
            print(
                f"[Jev router] Routing unavailable ({type(error).__name__}). "
                "Default: treat this as Opus work. If this session is running on Opus, "
                "keep it in the main loop; otherwise delegate it to the `tier-opus` subagent."
            )


def _log(task, decision, response):
    """Append one line per routed prompt, for tuning thresholds later. Local only."""
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "final_tier": decision.tier,
        "jev_tier": decision.jev_tier,
        "jev_confidence": decision.jev_confidence,
        "tier_probabilities": decision.tier_probabilities,
        "trigger_probabilities": decision.trigger_probabilities,
        "capability_score": decision.capability_score,
        "bulk_probability": decision.bulk_probability,
        "web_research_probability": decision.web_research_probability,
        "delegate": decision.delegate,
        "override": decision.override,
        "policy_tier": decision.policy_tier,
        "policy_delegate": decision.policy_delegate,
        "reasons": decision.reasons,
        "typesafe_model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # logging must never break the hook


if __name__ == "__main__":
    # Make `from router import ...` work no matter which directory Claude Code runs us from.
    sys.path.insert(0, str(Path(__file__).parent))
    main()
