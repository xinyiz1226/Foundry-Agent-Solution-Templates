"""Evaluation describes scripted coverage, not real DeepSeek quality or speed."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.evaluate import PriceConfig, run_evaluation, validate_report
from analysis.core import Limits
from analysis.cli import load_investigation
from test_adaptive import BoundaryClient, response
from analysis.model_client import ReplayClient
from test_business_analysis import BASELINE, CURRENT, investigator


def focused_steps(territory="20"):
    return [
        {"name": "compare", "arguments": {"filters": {}}},
        {"name": "breakdown", "arguments": {"dimension": "territory", "filters": {}, "top_k": 5}},
        {"name": "breakdown", "arguments": {
            "dimension": "product", "filters": {"territory": territory}, "top_k": 5,
        }},
        {"name": "finish", "arguments": {
            "result_ids": ["r1", "r2", "r3"], "evidence_ids": [f"q{index}" for index in range(1, 11)],
            "stop_reason": "complete",
        }},
    ]


class EvaluationTests(unittest.TestCase):
    def test_same_snapshot_budgets_and_question_with_explicit_scripted_coverage(self):
        source = investigator()
        evaluation = run_evaluation(source, BASELINE, CURRENT, "Investigate South products",
                                    ReplayClient(focused_steps()), "replay", target_territory_ids=["20"])
        self.assertEqual(evaluation["execution_kind"], "replay_harness_only")
        self.assertFalse(evaluation["real_model_quality_validated"])
        self.assertEqual(evaluation["baseline"]["metrics"]["data_requests"], 10)
        self.assertEqual(evaluation["adaptive"]["metrics"]["data_requests"], 10)
        self.assertEqual(evaluation["baseline"]["metrics"]["scope"]["selected_territory_ids"], ["10"])
        self.assertEqual(evaluation["adaptive"]["metrics"]["scope"]["selected_territory_ids"], ["20"])
        self.assertFalse(evaluation["baseline"]["metrics"]["scope"]["target_product_coverage"])
        self.assertTrue(evaluation["adaptive"]["metrics"]["scope"]["target_product_coverage"])
        self.assertTrue(evaluation["adaptive"]["metrics"]["validity"]["numeric_valid"])
        self.assertTrue(evaluation["adaptive"]["metrics"]["validity"]["evidence_valid"])
        self.assertEqual(evaluation["adaptive"]["metrics"]["cost"]["status"], "unknown")
        self.assertIsNone(evaluation["adaptive"]["metrics"]["token_usage"]["total_tokens"])
        self.assertEqual(source.requests, 0)
        self.assertEqual(source.evidence, [])
        for label in ("baseline", "adaptive"):
            for item in evaluation[label]["report"]["evidence"]:
                self.assertEqual(item["source_sha256"], evaluation["snapshot"]["source_sha256"])

    def test_validity_checks_recompute_using_existing_engine_not_trusted_fact_text(self):
        evaluation = run_evaluation(investigator(), BASELINE, CURRENT, "Investigate South",
                                    ReplayClient(focused_steps()), "replay")
        report = copy.deepcopy(evaluation["adaptive"]["report"])
        report["facts"][0]["values"]["change"]["sales"] = "99999.0000"
        self.assertFalse(validate_report(report)["numeric_valid"])
        report = copy.deepcopy(evaluation["adaptive"]["report"])
        report["facts"][0]["evidence_ids"] = ["q_stale"]
        self.assertFalse(validate_report(report)["evidence_valid"])

    def test_known_usage_needs_explicit_matching_prices_and_never_prices_the_platform(self):
        import json
        first = response()
        first["usage"] = {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}
        finish = response("finish", json.dumps({
            "result_ids": ["r1"], "evidence_ids": ["q1", "q2"], "stop_reason": "complete",
        }), "call_2")
        finish["usage"] = {"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240}
        prices = PriceConfig("boundary-double", "1", "2")
        output = run_evaluation(investigator(), BASELINE, CURRENT, "Compare",
                                BoundaryClient([first, finish]), "boundary-double", prices=prices)
        cost = output["adaptive"]["metrics"]["cost"]
        self.assertEqual(cost["estimated_model_cost"], "0.00044000")
        self.assertIsNone(cost["platform_cost"])
        output = run_evaluation(investigator(), BASELINE, CURRENT, "Compare",
                                BoundaryClient([first, finish]), "boundary-double")
        self.assertEqual(output["adaptive"]["metrics"]["cost"]["status"], "unknown")

    def test_failed_baseline_is_not_hidden_by_successful_adaptive_selection(self):
        output = run_evaluation(investigator(limits=Limits(max_requests=2)), BASELINE, CURRENT, "Compare",
                                ReplayClient(focused_steps()), "replay")
        self.assertEqual(output["baseline"]["metrics"]["status"], "error")
        self.assertEqual(output["baseline"]["metrics"]["validity"]["status"], "not_evaluated")
        self.assertEqual(output["adaptive"]["metrics"]["status"], "exhausted")
        self.assertEqual(output["adaptive"]["metrics"]["data_requests"], 2)

    @unittest.skipUnless(
        (Path(__file__).resolve().parents[1] / ".artifacts" / "adventureworks" / "internet_sales.csv").is_file(),
        "Optional hash-verified official sample is not present; no download is attempted.",
    )
    def test_official_northwest_replay_uses_source_id_one_not_synthetic_north_ten(self):
        import json
        root = Path(__file__).resolve().parents[1]
        source, baseline, current, top_k = load_investigation(
            root / ".artifacts" / "adventureworks" / "internet_sales.csv",
            root / ".artifacts" / "adventureworks" / "analysis-config.json",
        )
        fixture = json.loads((root / "evaluation" / "replays" / "northwest.json").read_text(encoding="utf-8"))
        self.assertEqual(source.source.groups(current, "territory")["1"][0], "Northwest")
        self.assertEqual(fixture["expected_dataset_id"], source.source.dataset_id)
        report = run_evaluation(source, baseline, current, fixture["question"], ReplayClient(fixture["steps"]),
                                "offline-replay", top_k=top_k, target_territory_ids=fixture["target_territory_ids"])
        self.assertEqual(report["adaptive"]["metrics"]["scope"]["selected_territory_ids"], ["1"])
        self.assertTrue(report["adaptive"]["metrics"]["validity"]["numeric_valid"])
        self.assertEqual(report["adaptive"]["metrics"]["data_requests"], 10)
        self.assertEqual(report["baseline"]["metrics"]["data_requests"], 10)


if __name__ == "__main__":
    unittest.main()
