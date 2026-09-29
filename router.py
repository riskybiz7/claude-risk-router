"""Jev model router: decide which Claude tier (Haiku / Sonnet / Opus) should handle a task.

The routing rules come from ~/.claude/commands/route.md ("the doctrine").
The split of responsibilities:

  * Jev (TypeSafe's System One model) supplies the *judgments*: which tier the
    task looks like, and whether each escalation trigger applies. One API call.
  * Plain Python (apply_policy below) supplies the *policy*: thresholds,
    escalation, the Haiku hard floor. Change a threshold here and re-run --
    no model call needed to understand why a route came out the way it did.

Think of it like an Excel model: Jev fills in the input cells (probabilities),
apply_policy is the formula block that turns inputs into the answer.
"""

from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, RetryPolicy, Score, TypeSafeClient

# --------------------------------------------------------------------------
# Tiers and models
# --------------------------------------------------------------------------

# Ordered lowest -> highest. "Escalate" means move one step right in this list.
TIERS = ["haiku", "sonnet", "opus"]

# Claude Code model aliases ("opus", "sonnet", "haiku") rather than exact IDs:
# an alias always points at the latest model in that family, so these never
# go stale. They must match the `model:` line in each agent file.
# The agent names refer to user-level subagents in ~/.claude/agents/.
# tier-opus is a fallback only: when the session itself runs on Opus, route.md
# keeps Opus work in the main loop, which has the full conversation context.
MODELS = {
    "opus": {"model_id": "opus", "agent": "tier-opus"},
    "sonnet": {"model_id": "sonnet", "agent": "tier-sonnet"},
    "haiku": {"model_id": "haiku", "agent": "tier-haiku"},
}

# --------------------------------------------------------------------------
# Policy thresholds -- STARTING VALUES, NOT CALIBRATED.
# 0.5 is the example value used in TypeSafe's docs. Tune these with eval.py
# against labeled prompts before trusting the router.
# --------------------------------------------------------------------------

TRIGGER_THRESHOLD = 0.5  # a trigger "fires" when its Noul probability >= this
# Raised from 0.5 after the 2026-09-28 eval: Jev's one wrong tier pick came
# with confidence 0.57, and 0.6 was the lowest cutoff that caught it.
CONFIDENCE_FLOOR = 0.6  # below this, Jev's tier pick counts as "unclear"
# Capability is a Score from 0 to 2 (see QUESTIONS). At or above this, the
# task leans toward "open-ended", so Haiku is not trusted to do it.
CAPABILITY_CUTOFF = 1.5
# "More likely than not" that the task is bulk work -> worth handing off.
BULK_THRESHOLD = 0.5
# Likewise for web research across several pages.
WEB_RESEARCH_THRESHOLD = 0.5

# --------------------------------------------------------------------------
# The questions Jev answers. All seven go in ONE request and are answered in
# parallel; none of them can see the others' answers.
# --------------------------------------------------------------------------

QUESTIONS = {
    "tier": Choice(
        instructions=(
            "`task` is a request a user typed to an AI coding assistant working on "
            "finance and healthcare-valuation projects. Which model tier should do "
            "this work? Tier by decision risk, not by task size: the question is "
            "how costly a plausible-but-wrong result would be."
        ),
        criteria={
            "haiku": (
                "Purely mechanical work with no judgment and no figures derived: "
                "file downloads, archive population, checksums, manifest rows, "
                "grep/glob sweeps returning raw excerpts and paths, file inventory, "
                "or running an existing, unmodified script and returning its output verbatim."
            ),
            "sonnet": (
                "Execution against a settled plan: editing scripts plus the "
                "rebuild/verify loop, building an artifact from an agreed spec, "
                "sourcing and research with citations, writing up an outcome that is "
                "already decided, programmatic re-footing and reconciliation."
            ),
            "opus": (
                "Judgment: planning, deciding whether an answer is right rather than "
                "merely computed, reviewing a verification or fact-check report, or "
                "anything where being wrong costs real money, credibility, or a decision."
            ),
        },
    ),
    # Escalation triggers 1-3 from route.md. Triggers 4 ("an agent returns
    # unclear") and 5 ("a second failed attempt") happen at run time, so they
    # are not questions here -- see the low-confidence rule in apply_policy.
    "produces_figure": Noul(
        instructions=(
            "Will the output of `task` contain a number that reaches a financial "
            "model, memo, or decision? Counts of files, lines, or search hits do not count."
        ),
    ),
    # Rewritten after the 2026-09-28 eval: the old wording ("...ambiguous or
    # not specified?") fired on almost every short prompt, because nearly any
    # one-line request leaves some detail unspecified. The exclusion sentence
    # mirrors the one that keeps produces_figure well-behaved.
    "ambiguous_method": Noul(
        instructions=(
            "Does `task` require choosing between competing definitions of a "
            "financial line item, an accounting treatment, or a valuation "
            "methodology, where the choice changes a number? Unspecified file "
            "names, file formats, folder locations, tools, search terms, or "
            "wording do not count."
        ),
    ),
    "valuation_driver": Noul(
        instructions=(
            "Does `task` touch a valuation driver, a discount rate, or another "
            "assumption or override that sets the answer of an analysis?"
        ),
    ),
    # Delegation question. Anthropic measured that handing work to cheaper
    # models saved money mainly when there was bulk to hand off; on work one
    # model handles in a single context, doing it in place was cheaper
    # (platform.claude.com, "Optimizing for cost and intelligence").
    "bulk_work": Noul(
        instructions=(
            "Does `task` require separately working through many independent "
            "pieces -- for example many filings, web pages, documents, or records "
            "that each need their own lookup, reading, or handling -- or reading "
            "more material than fits comfortably in one working session, such as "
            "hundreds of pages? A task that one command or script handles in a "
            "single step does not count, even if it touches many files."
        ),
    ),
    # Web research gets its own question (owner's decision: it counts as work
    # worth handing off). Folding it into bulk_work in eval v3 moved the three
    # web-research prompts by only +0.03 to +0.10, so it is asked on its own,
    # per TypeSafe's guidance to ask one narrow judgment per question.
    "web_research": Noul(
        instructions=(
            "Does `task` require searching the web and reading several web pages "
            "to find or gather information? Downloading a file from a known "
            "website along a predictable path does not count."
        ),
    ),
    # Capability question: can the cheapest tier actually do it? Level 2 folds
    # in two of Haiku 4.5's published limits (Models overview): a 200K-token
    # context window and a Feb 2025 reliable knowledge cutoff.
    "capability": Score(
        instructions=(
            "Apart from any financial judgment, how open-ended or demanding is "
            "the work needed to complete `task`?"
        ),
        criteria=[
            "One direct action: the file, command, web address, or location is "
            "named or obvious.",
            "A few steps along a predictable path, such as opening a named filing "
            "on a known website and downloading an attachment from it.",
            "Open-ended or demanding: the location or approach is unknown and must "
            "be searched for, several sources must be compared, likely obstacles "
            "must be worked around, a single document of hundreds of pages must be "
            "read in full, or the work depends on knowing about events after early "
            "2025 without looking them up.",
        ],
    ),
}

TRIGGERS = ["produces_figure", "ambiguous_method", "valuation_driver"]
# Triggers that bump a task up one tier. produces_figure is deliberately NOT
# one of them (owner's decision, 2026-09-28): a figure only sets a Sonnet
# minimum. Sonnet may produce figures with citations, and route.md requires
# the main loop to check each cited source before a figure is used.
ESCALATION_TRIGGERS = ["ambiguous_method", "valuation_driver"]


# --------------------------------------------------------------------------
# Policy (pure Python -- no API calls, fully unit-tested in test_policy.py)
# --------------------------------------------------------------------------


@dataclass
class RouteDecision:
    tier: str  # final tier after policy
    jev_tier: str  # what Jev picked before policy
    jev_confidence: float
    tier_probabilities: dict
    trigger_probabilities: dict
    reasons: list = field(default_factory=list)
    capability_score: float = 0.0  # Jev's 0-2 Score: how open-ended the work is
    bulk_probability: float = 0.0  # Jev's Noul: probability the task is bulk work
    web_research_probability: float = 0.0  # Jev's Noul: probability it is multi-page web research
    delegate: bool = False  # True -> hand off to the tier's subagent; False -> main loop
    override: str = None  # tier the user forced with `route: [tier] ...`, else None
    policy_tier: str = None  # what the policy chose before an override (for the log)
    policy_delegate: bool = None  # likewise, the policy's hand-off decision

    @property
    def model_id(self):
        return MODELS[self.tier]["model_id"]

    @property
    def agent(self):
        return MODELS[self.tier]["agent"]


def _escalate(tier):
    """One step up the tier list; Opus is the ceiling."""
    index = TIERS.index(tier)
    return TIERS[min(index + 1, len(TIERS) - 1)]


def apply_policy(
    jev_tier,
    jev_confidence,
    trigger_probabilities,
    tier_probabilities=None,
    trigger_threshold=TRIGGER_THRESHOLD,
    confidence_floor=CONFIDENCE_FLOOR,
    capability_score=0.0,
    bulk_probability=0.0,
    capability_cutoff=CAPABILITY_CUTOFF,
    bulk_threshold=BULK_THRESHOLD,
    web_research_probability=0.0,
    web_research_threshold=WEB_RESEARCH_THRESHOLD,
):
    """Turn Jev's raw answers into a final tier and a hand-off decision, following route.md.

    Two separate outputs, like two columns in a model:
      * tier     -- the LOWEST model allowed to do the work (a floor, set by risk and capability)
      * delegate -- whether handing the work to that tier's subagent is worth it at all

    Rules, in order:
      1. Start from Jev's tier pick.
      2. Escalation: if ANY escalation trigger fires (ambiguous_method or
         valuation_driver >= threshold, or Jev's tier confidence < floor), bump
         up ONE tier. route.md: "any one bumps the subtask up a tier" -- so
         several triggers still mean one bump.
      3. Haiku hard floor: if produces_figure fires, the tier is at least Sonnet.
         A figure sets this minimum only; it does not push Sonnet work to Opus.
      4. Capability gate: if the work leans open-ended (capability score >= cutoff),
         Haiku is not trusted to do it, so the tier becomes Sonnet.
      5. Hand-off: below Opus, delegate bulk work or multi-page web research.
         Everything else stays in the main loop, whose model is at least as
         capable as the tier floor.
    Nothing in here ever lowers a tier: "escalation is automatic; demotion never is."
    """
    tier = jev_tier
    reasons = []

    fired = [
        f"{name} {trigger_probabilities[name]:.2f}"
        for name in ESCALATION_TRIGGERS
        if trigger_probabilities[name] >= trigger_threshold
    ]
    if jev_confidence < confidence_floor:
        fired.append(f"low tier confidence {jev_confidence:.2f}")

    if fired and tier != "opus":
        tier = _escalate(tier)
        reasons.append(f"escalated {jev_tier} -> {tier} ({'; '.join(fired)})")
    elif fired:
        reasons.append(f"already at opus ({'; '.join(fired)})")

    if tier == "haiku" and trigger_probabilities["produces_figure"] >= trigger_threshold:
        tier = "sonnet"
        reasons.append(
            f"Haiku hard floor: task produces a figure "
            f"({trigger_probabilities['produces_figure']:.2f}) -> at least sonnet"
        )

    if tier == "haiku" and capability_score >= capability_cutoff:
        tier = "sonnet"
        reasons.append(f"capability gate: open-ended work (score {capability_score:.2f} of 2) -> sonnet")

    # Opus work never leaves the main loop (see format_note for the fallback).
    worth_handing_off = []
    if bulk_probability >= bulk_threshold:
        worth_handing_off.append(f"bulk work {bulk_probability:.2f}")
    if web_research_probability >= web_research_threshold:
        worth_handing_off.append(f"web research {web_research_probability:.2f}")
    delegate = tier != "opus" and bool(worth_handing_off)
    if tier != "opus":
        if delegate:
            reasons.append(f"{'; '.join(worth_handing_off)} -> hand off to tier-{tier}")
        else:
            reasons.append(
                f"not bulk work ({bulk_probability:.2f}) or web research "
                f"({web_research_probability:.2f}) -> keep in main loop"
            )

    return RouteDecision(
        tier=tier,
        jev_tier=jev_tier,
        jev_confidence=jev_confidence,
        tier_probabilities=tier_probabilities or {},
        trigger_probabilities=dict(trigger_probabilities),
        reasons=reasons,
        capability_score=capability_score,
        bulk_probability=bulk_probability,
        web_research_probability=web_research_probability,
        delegate=delegate,
    )


def apply_override(decision, tier):
    """Apply a user override (`route: [tier] ...`) on top of the policy's decision.

    Naming a model means "run it on this model": Haiku and Sonnet are handed to
    their subagent regardless of bulk, Opus stays in the main loop. The policy's
    own answer is kept alongside, so every override is logged as a correction --
    the raw material for re-tuning. Forcing a tier BELOW the policy's floor is
    allowed (the user owns the call) but never silent: it adds a warning.
    """
    reasons = list(decision.reasons)
    reasons.append(
        f"override: user forced {tier} (policy chose {decision.tier}, "
        f"{'hand off' if decision.delegate else 'keep'})"
    )
    if TIERS.index(tier) < TIERS.index(decision.tier):
        reasons.append(
            f"WARNING: {tier} is below the policy floor ({decision.tier}). The risk "
            "checks above say this task needs a stronger model; verify the output "
            "against its sources before relying on it."
        )
    return RouteDecision(
        tier=tier,
        jev_tier=decision.jev_tier,
        jev_confidence=decision.jev_confidence,
        tier_probabilities=decision.tier_probabilities,
        trigger_probabilities=decision.trigger_probabilities,
        reasons=reasons,
        capability_score=decision.capability_score,
        bulk_probability=decision.bulk_probability,
        web_research_probability=decision.web_research_probability,
        delegate=tier != "opus",
        override=tier,
        policy_tier=decision.tier,
        policy_delegate=decision.delegate,
    )


# --------------------------------------------------------------------------
# The one API call
# --------------------------------------------------------------------------


def ask_jev(task, timeout=6.0):
    """Send the task + seven questions to Jev. Returns (response, decision).

    Reads TYPESAFE_API_KEY from the environment (the SDK does this itself).
    One retry at most, so a slow service can't stall the Claude Code hook.
    """
    retry = RetryPolicy(max_retries=1, timeout=timeout + 2)
    with TypeSafeClient(timeout=timeout, retry=retry) as client:
        response = client.system_one(state={"task": task}, questions=QUESTIONS)

    tier_answer = response.choices["tier"]
    decision = apply_policy(
        jev_tier=tier_answer.choice,
        jev_confidence=tier_answer.confidence,
        tier_probabilities=dict(tier_answer.probabilities),
        trigger_probabilities={name: response.nouls[name].noul for name in TRIGGERS},
        capability_score=response.scores["capability"].score,
        bulk_probability=response.nouls["bulk_work"].noul,
        web_research_probability=response.nouls["web_research"].noul,
    )
    return response, decision


def format_note(decision):
    """The text the hook hands to Claude as context for this turn."""
    # Hooks can't see or change the session's model, so the Opus case is written
    # as a condition for the main loop to resolve -- it knows which model it is.
    if decision.tier == "opus":
        action = (
            "If this session is running on Opus, keep it in the main loop (it has the "
            f"full conversation context). Otherwise delegate it to the `{decision.agent}` "
            "subagent and pass it all the context it needs."
        )
    elif decision.override:
        action = (
            f"Delegate the execution to the `{decision.agent}` subagent (latest "
            f"{decision.model_id}), as the user requested."
        )
    elif decision.delegate:
        kind = (
            "bulk work"
            if decision.bulk_probability >= BULK_THRESHOLD
            else "web research across several pages"
        )
        action = (
            f"Delegate the execution to the `{decision.agent}` subagent (latest "
            f"{decision.model_id}): this is {kind}, where handing off saves usage."
        )
    else:
        action = (
            f"Keep this in the main loop. {decision.model_id.capitalize()} is the lowest "
            "tier allowed, but this is neither bulk work nor web research, so handing "
            "it off would likely cost more than doing it here."
        )

    probs = ", ".join(f"{k} {v:.2f}" for k, v in decision.tier_probabilities.items())
    triggers = ", ".join(f"{k} {v:.2f}" for k, v in decision.trigger_probabilities.items())
    source = " (user override)" if decision.override else ""
    lines = [
        f"[Jev router] Route: {decision.tier.upper()}{source}. {action}",
        f"  Jev pick: {decision.jev_tier} (confidence {decision.jev_confidence:.2f}; {probs})",
        f"  Triggers: {triggers}",
        f"  Hand-off signals: bulk_work {decision.bulk_probability:.2f}, "
        f"web_research {decision.web_research_probability:.2f}, "
        f"capability {decision.capability_score:.2f} of 2",
    ]
    lines += [f"  Policy: {r}" for r in decision.reasons]
    lines.append(
        "  This is advisory. Apply route.md: escalate further if the work turns out "
        "riskier than it looks; never route below this tier."
    )
    return "\n".join(lines)
