"""Unit tests for the routing policy. No API calls, no cost.

Run from this folder:  python -m unittest -v
"""

import io
import json
import sys
import unittest
from contextlib import ExitStack
from itertools import product
from unittest import mock

from router import TIERS, apply_override, apply_policy, format_note

QUIET = {"produces_figure": 0.1, "ambiguous_method": 0.1, "valuation_driver": 0.1}


def triggers(**overrides):
    return {**QUIET, **overrides}


class PolicyTests(unittest.TestCase):
    def test_no_triggers_keeps_jev_pick(self):
        for tier in TIERS:
            self.assertEqual(apply_policy(tier, 0.9, QUIET).tier, tier)

    def test_figure_bumps_haiku_to_sonnet(self):
        d = apply_policy("haiku", 0.9, triggers(produces_figure=0.9))
        self.assertEqual(d.tier, "sonnet")

    def test_figure_is_a_sonnet_minimum_not_a_bump(self):
        # Owner's decision (2026-09-28): a figure keeps work off Haiku but does
        # not push Sonnet work to Opus.
        self.assertEqual(apply_policy("sonnet", 0.9, triggers(produces_figure=0.9)).tier, "sonnet")
        self.assertEqual(apply_policy("opus", 0.9, triggers(produces_figure=0.9)).tier, "opus")

    def test_bulk_figure_work_is_handed_to_sonnet(self):
        # e.g. "pull revenue and EBITDA from 40 CIMs with page citations"
        d = apply_policy("sonnet", 0.9, triggers(produces_figure=0.9), bulk_probability=0.9)
        self.assertEqual((d.tier, d.delegate, d.agent), ("sonnet", True, "tier-sonnet"))

    def test_valuation_driver_bumps_sonnet_to_opus(self):
        d = apply_policy("sonnet", 0.9, triggers(valuation_driver=0.7))
        self.assertEqual(d.tier, "opus")

    def test_opus_is_the_ceiling(self):
        d = apply_policy("opus", 0.2, triggers(produces_figure=0.9, valuation_driver=0.9))
        self.assertEqual(d.tier, "opus")

    def test_low_confidence_escalates(self):
        d = apply_policy("haiku", 0.3, QUIET)
        self.assertEqual(d.tier, "sonnet")

    def test_threshold_is_inclusive(self):
        # Exactly at the threshold counts as fired (>=).
        self.assertEqual(apply_policy("sonnet", 0.9, triggers(ambiguous_method=0.5)).tier, "opus")
        self.assertEqual(apply_policy("sonnet", 0.9, triggers(ambiguous_method=0.49)).tier, "sonnet")

    def test_several_triggers_still_one_bump(self):
        # route.md: "any one bumps the subtask up a tier" -- one bump, not one per trigger.
        d = apply_policy("haiku", 0.9, triggers(ambiguous_method=0.9, valuation_driver=0.9))
        self.assertEqual(d.tier, "sonnet")

    def test_haiku_floor_holds_even_with_looser_bump_threshold(self):
        # If only the figure trigger fires, the result is never haiku.
        d = apply_policy("haiku", 0.9, triggers(produces_figure=0.6))
        self.assertNotEqual(d.tier, "haiku")

    def test_never_demotes(self):
        # Exhaustive grid: the final tier is never below Jev's pick, whatever the
        # capability score, bulk, or web-research probability, and Opus work is
        # never handed off.
        levels = [0.0, 0.49, 0.5, 1.0]
        for tier, conf, a, b, c, cap, bulk, web in product(
            TIERS, levels, levels, levels, levels, [0.0, 1.5, 2.0], [0.0, 1.0], [0.0, 1.0]
        ):
            d = apply_policy(
                tier,
                conf,
                {"produces_figure": a, "ambiguous_method": b, "valuation_driver": c},
                capability_score=cap,
                bulk_probability=bulk,
                web_research_probability=web,
            )
            self.assertGreaterEqual(TIERS.index(d.tier), TIERS.index(tier))
            if a >= 0.5:
                self.assertNotEqual(d.tier, "haiku")
            if d.tier == "opus":
                self.assertFalse(d.delegate)

    def test_confidence_floor_is_point_six(self):
        # 0.57 was Jev's one wrong pick in the first eval; it must now escalate.
        self.assertEqual(apply_policy("haiku", 0.57, QUIET).tier, "sonnet")
        self.assertEqual(apply_policy("haiku", 0.6, QUIET).tier, "haiku")

    def test_capability_gate_bumps_haiku_only(self):
        self.assertEqual(apply_policy("haiku", 0.9, QUIET, capability_score=1.6).tier, "sonnet")
        self.assertEqual(apply_policy("haiku", 0.9, QUIET, capability_score=1.4).tier, "haiku")
        # Sonnet and Opus are capable of open-ended work; the gate leaves them alone.
        self.assertEqual(apply_policy("sonnet", 0.9, QUIET, capability_score=2.0).tier, "sonnet")
        self.assertEqual(apply_policy("opus", 0.9, QUIET, capability_score=2.0).tier, "opus")

    def test_only_bulk_work_is_handed_off(self):
        self.assertTrue(apply_policy("haiku", 0.9, QUIET, bulk_probability=0.8).delegate)
        self.assertTrue(apply_policy("sonnet", 0.9, QUIET, bulk_probability=0.5).delegate)
        self.assertFalse(apply_policy("haiku", 0.9, QUIET, bulk_probability=0.49).delegate)
        self.assertFalse(apply_policy("sonnet", 0.9, QUIET).delegate)

    def test_web_research_alone_is_handed_off(self):
        # Owner's decision: multi-page web research is worth handing off, even
        # when Jev doesn't see it as bulk work.
        d = apply_policy("sonnet", 0.9, QUIET, bulk_probability=0.2, web_research_probability=0.8)
        self.assertEqual((d.tier, d.delegate, d.agent), ("sonnet", True, "tier-sonnet"))
        note = format_note(d)
        self.assertIn("web research across several pages", note)
        self.assertIn("web_research 0.80", note)
        self.assertFalse(apply_policy("sonnet", 0.9, QUIET, web_research_probability=0.49).delegate)

    def test_opus_web_research_is_never_handed_off(self):
        self.assertFalse(apply_policy("opus", 0.9, QUIET, web_research_probability=1.0).delegate)

    def test_opus_work_is_never_handed_off(self):
        self.assertFalse(apply_policy("opus", 0.9, QUIET, bulk_probability=1.0).delegate)
        # Escalated into Opus by a trigger: still never handed off.
        d = apply_policy("sonnet", 0.9, triggers(valuation_driver=0.9), bulk_probability=1.0)
        self.assertEqual(d.tier, "opus")
        self.assertFalse(d.delegate)

    def test_hand_off_goes_to_the_final_tier_not_jevs_pick(self):
        # Jev says haiku, a figure is produced -> floor is sonnet -> sonnet's agent.
        d = apply_policy("haiku", 0.9, triggers(produces_figure=0.9), bulk_probability=0.9)
        self.assertEqual((d.tier, d.delegate, d.agent), ("sonnet", True, "tier-sonnet"))

    def test_override_forces_tier_and_hand_off(self):
        d = apply_override(apply_policy("opus", 0.9, QUIET), "sonnet")
        self.assertEqual((d.tier, d.delegate, d.agent), ("sonnet", True, "tier-sonnet"))
        # The policy's own answer is kept, so the log records the correction.
        self.assertEqual((d.override, d.policy_tier, d.policy_delegate), ("sonnet", "opus", False))

    def test_opus_override_stays_in_main_loop(self):
        d = apply_override(apply_policy("haiku", 0.9, QUIET, bulk_probability=0.9), "opus")
        self.assertEqual((d.tier, d.delegate), ("opus", False))

    def test_override_below_floor_warns(self):
        base = apply_policy("haiku", 0.9, triggers(produces_figure=0.9))  # floor is sonnet
        note = format_note(apply_override(base, "haiku"))
        self.assertIn("HAIKU (user override)", note)
        self.assertIn("WARNING: haiku is below the policy floor (sonnet)", note)

    def test_override_at_or_above_floor_does_not_warn(self):
        base = apply_policy("haiku", 0.9, QUIET)
        for tier in TIERS:
            reasons = apply_override(base, tier).reasons
            self.assertFalse(any(r.startswith("WARNING") for r in reasons), tier)

    def test_note_names_model_and_agent(self):
        note = format_note(apply_policy("haiku", 0.9, QUIET, bulk_probability=0.9))
        self.assertIn("latest haiku", note)
        self.assertIn("tier-haiku", note)
        note = format_note(apply_policy("haiku", 0.9, QUIET, bulk_probability=0.1))
        self.assertIn("Keep this in the main loop", note)
        self.assertNotIn("Delegate", note)
        note = format_note(apply_policy("opus", 0.9, QUIET))
        # Opus: main loop if the session is Opus, tier-opus fallback otherwise.
        self.assertIn("main loop", note)
        self.assertIn("tier-opus", note)


class HookTests(unittest.TestCase):
    """The hook's opt-in gate and fail-safe, with the API mocked out."""

    def run_hook(self, prompt, ask_jev=None):
        import hook

        stdin = io.StringIO(json.dumps({"prompt": prompt, "hook_event_name": "UserPromptSubmit"}))
        stdout = io.StringIO()
        stdout.reconfigure = lambda **kw: None  # StringIO has no reconfigure
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "stdin", stdin))
            stack.enter_context(mock.patch.object(sys, "stdout", stdout))
            if ask_jev is not None:
                stack.enter_context(mock.patch("router.ask_jev", ask_jev))
            hook.main()
        return stdout.getvalue()

    def test_unmarked_prompt_is_silent_and_never_calls_jev(self):
        never = mock.Mock(side_effect=AssertionError("Jev must not be called"))
        self.assertEqual(self.run_hook("fix the chart colors", ask_jev=never), "")
        never.assert_not_called()

    def test_old_bang_prefix_no_longer_routes(self):
        # A leading "!" is shell mode in the Claude Code terminal; it must not be the trigger.
        never = mock.Mock(side_effect=AssertionError("Jev must not be called"))
        self.assertEqual(self.run_hook("!route download the filings", ask_jev=never), "")

    def test_prefix_is_case_insensitive(self):
        boom = mock.Mock(side_effect=TimeoutError("slow"))
        for prompt in ("route: download the filings", "Route: download the filings"):
            self.assertIn("Routing unavailable", self.run_hook(prompt, ask_jev=boom))

    def test_empty_route_prompt(self):
        self.assertIn("nothing to route", self.run_hook("route:   "))

    def test_override_is_applied_and_logged(self):
        fake = mock.Mock(return_value=(mock.Mock(), apply_policy("opus", 0.9, QUIET)))
        with mock.patch("hook._log") as log:  # keep test runs out of routing_log.jsonl
            out = self.run_hook("route: [Sonnet] pull the filings", ask_jev=fake)
        fake.assert_called_once_with("pull the filings")  # tag stripped before Jev sees it
        self.assertIn("SONNET (user override)", out)
        self.assertIn("tier-sonnet", out)
        logged = log.call_args.args[1]
        self.assertEqual((logged.override, logged.policy_tier), ("sonnet", "opus"))

    def test_unknown_override_is_rejected_not_ignored(self):
        never = mock.Mock(side_effect=AssertionError("Jev must not be called"))
        out = self.run_hook("route: [sonet] pull the filings", ask_jev=never)
        self.assertIn("Unknown override `[sonet]`", out)

    def test_override_survives_routing_failure(self):
        boom = mock.Mock(side_effect=TimeoutError("slow"))
        out = self.run_hook("route: [haiku] pull the filings", ask_jev=boom)
        self.assertIn("User override: haiku", out)
        self.assertIn("tier-haiku", out)

    def test_override_with_no_task(self):
        self.assertIn("nothing to route", self.run_hook("route: [opus]"))

    def test_failure_defaults_to_opus(self):
        boom = mock.Mock(side_effect=TimeoutError("slow"))
        out = self.run_hook("route: download the filings", ask_jev=boom)
        self.assertIn("Routing unavailable (TimeoutError)", out)
        self.assertIn("Opus work", out)
        self.assertIn("tier-opus", out)


if __name__ == "__main__":
    unittest.main()
