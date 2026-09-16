"""Adaptive orchestration tests use the real analytical engine, not mocked arithmetic."""

import sys
import copy
import json
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_business_analysis import BASELINE, CURRENT, investigator
from analysis.adaptive import AdaptiveLimits, run_adaptive
from analysis.core import CsvSalesSource, Investigator, Limits, Period
from analysis.model_client import ReplayClient


class BoundaryClient:
    """External model boundary double; the analysis implementation remains real."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def response(name="compare", arguments='{"filters":{}}', call_id="call_1", **message_fields):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None,
        "tool_calls": [{"id": call_id, "type": "function",
                       "function": {"name": name, "arguments": arguments}}],
        **message_fields,
    }}]}


class AdaptiveTests(unittest.TestCase):
    def test_opted_in_batch_is_validated_then_executed_serially_with_all_replies(self):
        first = response(reasoning_content="private-continuation")
        first["choices"][0]["message"]["tool_calls"] += response(
            "breakdown", '{"dimension":"territory","filters":{},"top_k":5}', "call_2"
        )["choices"][0]["message"]["tool_calls"]
        client = BoundaryClient([
            first,
            response("breakdown", '{"dimension":"product","filters":{"territory":"10"},"top_k":5}', "call_3"),
            response("finish", json.dumps({"result_ids": ["r1", "r2", "r3"],
                     "evidence_ids": [f"q{i}" for i in range(1, 11)], "stop_reason": "complete"}), "call_4"),
        ])
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Investigate North", client, "deepseek",
                              limits=AdaptiveLimits(max_tool_calls_per_response=2))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["execution"]["data_requests"], 10)
        self.assertEqual(report["execution"]["model_calls"], 3)
        messages = client.requests[1]["messages"]
        self.assertEqual([item["tool_call_id"] for item in messages if item["role"] == "tool"], ["call_1", "call_2"])
        self.assertEqual(messages[-3]["reasoning_content"], "private-continuation")
        self.assertNotIn("private-continuation", json.dumps(report))
        self.assertFalse(client.requests[0]["parallel_tool_calls"])

    def test_batch_rejects_all_calls_before_data_on_invalid_args_or_budget(self):
        for scenario in ("bad-second", "duplicate-id", "mixed-finish", "over-budget", "unseen-id", "over-count"):
            first = response()
            second = response("breakdown", '{"dimension":"territory","filters":{},"top_k":5}', "call_2")
            if scenario == "bad-second":
                second = response("breakdown", '{"sql":"unsafe"}', "call_2")
            if scenario == "duplicate-id":
                second["choices"][0]["message"]["tool_calls"][0]["id"] = "call_1"
            if scenario == "mixed-finish":
                second = response("finish", '{"result_ids":[],"evidence_ids":[],"stop_reason":"insufficient_evidence"}', "call_2")
            if scenario == "unseen-id":
                first = response("breakdown", '{"dimension":"territory","filters":{},"top_k":5}')
                second = response("compare", '{"filters":{"territory":"10"}}', "call_2")
            first["choices"][0]["message"]["tool_calls"] += second["choices"][0]["message"]["tool_calls"]
            if scenario == "over-count":
                first["choices"][0]["message"]["tool_calls"] += response(call_id="call_3")["choices"][0]["message"]["tool_calls"]
            engine = investigator(limits=Limits(max_requests=5 if scenario == "over-budget" else 10))
            report = run_adaptive(engine, BASELINE, CURRENT, "Compare", BoundaryClient([first]), "deepseek",
                                  limits=AdaptiveLimits(max_tool_calls_per_response=2))
            with self.subTest(scenario=scenario):
                self.assertNotEqual(report["status"], "ok")
                self.assertEqual(report["stop_reason"],
                                 "data_request_limit" if scenario == "over-budget" else "invalid_model_response")
                self.assertEqual(report["execution"]["data_requests"], 0)
                self.assertEqual(report["facts"], [])

    def test_invalid_model_response_has_bounded_diagnostics_without_private_content(self):
        malformed = response(reasoning_content="private-secret")
        malformed["choices"][0]["message"]["tool_calls"] *= 2
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare",
                              BoundaryClient([malformed]), "deepseek")
        self.assertEqual(report["diagnostics"]["reason"], "tool_call_count")
        self.assertEqual(report["diagnostics"]["tool_call_count"], 2)
        self.assertEqual(report["diagnostics"]["finish_reason"], "tool_calls")
        self.assertNotIn("private-secret", json.dumps(report))
        self.assertEqual(report["execution"]["data_requests"], 0)

    def test_finish_rejects_stale_or_fabricated_evidence_and_duplicate_ids(self):
        for args in (
            {"result_ids": ["r99"], "evidence_ids": ["q1", "q2"], "stop_reason": "complete"},
            {"result_ids": ["r1"], "evidence_ids": ["q1", "q99"], "stop_reason": "complete"},
            {"result_ids": ["r1", "r1"], "evidence_ids": ["q1", "q2"], "stop_reason": "complete"},
            {"result_ids": ["r1"], "evidence_ids": ["q1", "q2"], "stop_reason": "caused_by_price"},
            {"result_ids": ["r1"], "evidence_ids": ["q1", "q2"], "stop_reason": "complete", "sales": 999},
        ):
            with self.subTest(args=args):
                client = BoundaryClient([response(), response("finish", json.dumps(args), "call_2")])
                report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare", client, "deepseek")
                self.assertEqual(report["stop_reason"], "invalid_model_response")
                self.assertEqual(report["facts"], [])
                self.assertEqual(report["execution"]["data_requests"], 2)
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare",
                              BoundaryClient([response(), response()]), "deepseek")
        self.assertEqual(report["stop_reason"], "invalid_model_response")
        self.assertEqual(report["execution"]["data_requests"], 2)

    def test_budget_exhaustion_preserves_evidence_without_success_facts(self):
        for limits, reason in (
            (AdaptiveLimits(max_model_calls=1), "model_call_limit"),
            (AdaptiveLimits(max_tool_summary_chars=1), "tool_summary_limit"),
        ):
            with self.subTest(reason=reason):
                report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare",
                                      BoundaryClient([response()]), "deepseek", limits=limits)
                self.assertEqual(report["status"], "exhausted")
                self.assertEqual(report["stop_reason"], reason)
                self.assertEqual(report["facts"], [])
                self.assertEqual(len(report["evidence"]), 2)
        over = response()
        over["usage"] = {"prompt_tokens": 100, "completion_tokens": 1025, "total_tokens": 1125}
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare", BoundaryClient([over]), "deepseek")
        self.assertEqual(report["stop_reason"], "token_limit")
        self.assertEqual(report["execution"]["data_requests"], 0)

    def test_large_group_evidence_is_not_sent_to_the_model(self):
        from test_business_analysis import COLUMNS, COVERAGE
        records = [dict(zip(COLUMNS, (
            "2024-01-05", f"O{index}", "1", "Alpha", str(index), f"Area-{index}", "1", "0",
        ))) for index in range(1000)]
        engine = Investigator(CsvSalesSource.from_records(records, dataset_id="many-groups"), COVERAGE)
        client = BoundaryClient([
            response("breakdown", '{"filters":{},"dimension":"territory","top_k":1}'),
            response("finish", '{"result_ids":[],"evidence_ids":[],"stop_reason":"insufficient_evidence"}', "call_2"),
        ])
        report = run_adaptive(engine, BASELINE, CURRENT, "Find a territory", client, "deepseek")
        summary = json.loads(client.requests[1]["messages"][-1]["content"])
        self.assertEqual(len(summary["values"]["segments"]), 1)
        self.assertEqual(summary["values"]["other"]["group_count"], 999)
        self.assertEqual(len(report["evidence"][0]["result"]), 1000)
        self.assertNotIn("query_plan", json.dumps(client.requests))
        self.assertEqual(report["status"], "insufficient_data")

    def test_changing_source_across_tools_is_not_successful(self):
        from test_business_analysis import LINES
        engine = investigator()
        changed = list(LINES)
        changed[0] = (*changed[0][:6], "110", "60")
        original, other = engine.source, investigator(changed).source

        class MovingSnapshot:
            mode, dataset_id, sha256 = original.mode, original.dataset_id, original.sha256
            calls = 0

            def read(self, plan):
                self.calls += 1
                return (original if self.calls <= 2 else other).read(plan)

        engine.source = MovingSnapshot()
        client = ReplayClient([
            {"name": "compare", "arguments": {"filters": {}}},
            {"name": "breakdown", "arguments": {"filters": {}, "dimension": "territory", "top_k": 5}},
            {"name": "finish", "arguments": {
                "result_ids": ["r1", "r2"], "evidence_ids": [f"q{index}" for index in range(1, 7)],
                "stop_reason": "complete",
            }},
        ])
        report = run_adaptive(engine, BASELINE, CURRENT, "Compare", client, "replay")
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["stop_reason"], "inconsistent_evidence")
        self.assertEqual(report["facts"], [])

    def test_sdk_default_retries_are_rejected_before_model_call(self):
        from types import SimpleNamespace
        client = BoundaryClient([response()])
        client._client = SimpleNamespace(max_retries=2)
        with self.assertRaisesRegex(ValueError, "retries"):
            run_adaptive(investigator(), BASELINE, CURRENT, "Compare", client, "deepseek")
        self.assertEqual(client.requests, [])

    def test_host_wall_budget_does_not_expand_per_model_transport_timeout(self):
        client = BoundaryClient([response()])
        report = run_adaptive(
            investigator(), BASELINE, CURRENT, "Compare", client, "deepseek",
            limits=AdaptiveLimits(max_seconds=120, max_model_calls=1),
        )
        self.assertEqual(report["stop_reason"], "model_call_limit")
        self.assertEqual(client.requests[0]["timeout"], 30)

    def test_limits_stop_before_overspending_and_keep_usage_unknown(self):
        for limits, reason in (
            (AdaptiveLimits(max_total_tokens=1), "token_limit"),
            (AdaptiveLimits(max_context_chars=1), "context_limit"),
        ):
            with self.subTest(reason=reason):
                client = BoundaryClient([])
                report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare",
                                      client, "deepseek", limits=limits)
                self.assertEqual(report["stop_reason"], reason)
                self.assertEqual(client.requests, [])
        client = ReplayClient([{"name": "breakdown", "arguments": {
            "dimension": "territory", "filters": {}, "top_k": 5,
        }}])
        report = run_adaptive(investigator(limits=Limits(max_requests=3)), BASELINE, CURRENT,
                              "Compare", client, "replay")
        self.assertEqual(report["status"], "exhausted")
        self.assertEqual(report["stop_reason"], "data_request_limit")
        self.assertEqual(report["execution"]["data_requests"], 0)

    def test_continuation_keeps_private_reasoning_but_report_never_does(self):
        first = response(reasoning_content="private plan 9999", content="fabricated revenue 12345")
        first["usage"] = {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}
        finish = response("finish", json.dumps({
            "result_ids": ["r1"], "evidence_ids": ["q1", "q2"], "stop_reason": "complete",
        }), "call_2")
        finish["usage"] = {"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240}
        client = BoundaryClient([first, finish])
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare", client, "deepseek")
        self.assertEqual(client.requests[1]["messages"][2]["reasoning_content"], "private plan 9999")
        self.assertEqual(client.requests[1]["messages"][3]["tool_call_id"], "call_1")
        self.assertNotIn("private plan", json.dumps(report))
        self.assertNotIn("12345", json.dumps(report))
        self.assertEqual(report["execution"]["token_usage"]["total_tokens"], 370)

    def test_unknown_partial_usage_is_not_reported_as_zero(self):
        first = response()
        first["usage"] = {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare",
                              BoundaryClient([first, RuntimeError("secret credential")]), "deepseek")
        self.assertEqual(report["stop_reason"], "model_error")
        self.assertIsNone(report["execution"]["token_usage"]["total_tokens"])
        self.assertNotIn("secret credential", json.dumps(report))
        self.assertEqual(report["facts"], [])
        self.assertEqual(len(report["results"]), 1)

    def test_no_data_cannot_be_finished_as_success(self):
        client = ReplayClient([
            {"name": "compare", "arguments": {"filters": {}}},
            {"name": "finish", "arguments": {
                "result_ids": ["r1"], "evidence_ids": ["q1", "q2"], "stop_reason": "complete",
            }},
        ])
        report = run_adaptive(investigator(), BASELINE, Period.parse("2024-03-01", "2024-04-01"),
                              "Compare", client, "replay")
        self.assertEqual(report["status"], "insufficient_data")
        self.assertEqual(report["stop_reason"], "no_data")

    def test_late_response_is_discarded_instead_of_executing_tool(self):
        class SlowClient:
            def create(self, **kwargs):
                time.sleep(0.02)
                return response()
        for limits in (AdaptiveLimits(max_seconds=0.001),
                       AdaptiveLimits(max_seconds=120, max_model_seconds=0.001)):
            with self.subTest(limits=limits):
                report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare", SlowClient(), "deepseek",
                                      limits=limits)
                self.assertEqual(report["stop_reason"], "time_limit")
                self.assertEqual(report["execution"]["data_requests"], 0)

    def test_invalid_model_protocol_never_executes_a_data_request(self):
        multiple = response()
        multiple["choices"][0]["message"]["tool_calls"] *= 2
        invalid = [
            multiple, response("execute_sql"), response(arguments='{"filters":{},"filters":{}}'),
            response(arguments='{"filters":{"territory":NaN}}'),
            response(arguments='{"filters":{"territory":"not_observed"}}'),
            response(arguments='{"filters":{},"view":"dbo.secret"}'),
            response(arguments='{"filters":[]}'), response(call_id=""),
            response("breakdown", '{"filters":{},"dimension":"region","top_k":5}'),
            response("breakdown", '{"filters":{},"dimension":"territory","top_k":true}'),
        ]
        for completion in invalid:
            with self.subTest(completion=completion):
                report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare",
                                      BoundaryClient([completion]), "deepseek")
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["stop_reason"], "invalid_model_response")
                self.assertEqual(report["execution"]["data_requests"], 0)
                self.assertEqual(report["facts"], [])

    def test_finish_publishes_only_selected_deterministic_results(self):
        client = ReplayClient([
            {"name": "compare", "arguments": {"filters": {}}},
            {"name": "finish", "arguments": {
                "result_ids": ["r1"], "evidence_ids": ["q1", "q2"],
                "stop_reason": "complete",
            }},
        ])
        report = run_adaptive(investigator(), BASELINE, CURRENT, "Compare profit", client, "replay")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["facts"][0]["values"]["change"]["gross_profit"], "-6.0000")
        self.assertEqual(report["facts"][0]["evidence_ids"], ["q1", "q2"])
        self.assertEqual(report["execution"]["data_requests"], 2)
        self.assertIsNone(report["execution"]["token_usage"]["total_tokens"])
        self.assertEqual(report["causal_conclusions"], [])


if __name__ == "__main__":
    unittest.main()
