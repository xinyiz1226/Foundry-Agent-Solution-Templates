"""Offline verification of hosted evidence; this module never contacts Azure."""

from dataclasses import asdict
import argparse
from ipaddress import ip_address, ip_network
import json
import math
from pathlib import Path
import re
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from .adaptive import AdaptiveLimits, CONTRACT_REASONS, strict_json
from .core import CsvSalesSource, Investigator, Limits, Period, run_baseline
from .evaluate import validate_report
from .hosted import HostedPolicy, PERMISSIONS, RESULT_MARKER
from .queries import plan_query


MAX_RESPONSE_BYTES = 8 * 1024 * 1024
DATA_LIMITS = Limits(max_seconds=120)
MODEL_LIMITS = AdaptiveLimits(max_seconds=120, max_top_k=5, max_tool_calls_per_response=2)


class ValidationFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Analytical evidence rejected: {code}.")


def _require(condition, code):
    if not condition:
        raise ValidationFailure(code)


def _same(actual, expected, code):
    _require(json.dumps(actual, sort_keys=True, allow_nan=False) ==
             json.dumps(expected, sort_keys=True, allow_nan=False), code)


def parse_response(text):
    """Accept one complete authoritative marker, not prose, duplicate JSON or probe evidence."""
    try:
        _require(isinstance(text, str) and len(text.encode("utf-8")) <= MAX_RESPONSE_BYTES, "response_size")
        plain = re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)
        _require(plain.count(RESULT_MARKER) == 1 and "BPI_PROBE_RESULT=" not in plain, "result_marker")
        matches = re.findall(r"(?m)^BPI_ANALYSIS_RESULT=(\{[^\r\n]*\})[ \t]*$", plain.replace("\r\n", "\n"))
        _require(len(matches) == 1, "result_marker")
        report = strict_json(matches[0])
        _require(isinstance(report, dict), "report_shape")
        return report
    except ValidationFailure:
        raise
    except (ValueError, TypeError, RecursionError):
        raise ValidationFailure("invalid_json") from None


def validate_context(context):
    _require(isinstance(context, dict), "context")
    _require(isinstance(context["server"], str) and re.fullmatch(
        r"[a-z0-9][a-z0-9-]*\.database\.windows\.net", context["server"]), "context_server")
    _require(isinstance(context["database"], str) and 1 <= len(context["database"]) <= 128, "context_database")
    for key in ("agent_principal_id", "agent_client_id"):
        _require(isinstance(context[key], str) and UUID(context[key]).int != 0, "context_identity")
    _require(isinstance(context["model"], str) and 1 <= len(context["model"]) <= 256, "context_model")
    ips = context["private_ips"]
    _require(isinstance(ips, list) and 1 <= len(ips) <= 16 and len(set(ips)) == len(ips), "context_ips")
    networks = [ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")]
    for value in ips:
        address = ip_address(value)
        _require(any(address in network for network in networks), "context_ips")


def _security(report, policy, context):
    record = report["security"]
    for key, value in {
        "status": "passed", "identity_mode": "managed_identity",
        "server": context["server"],
        "database_principal": policy.database_principal, "database_name": context["database"],
        "source_sha256": policy.source_sha256, "actual_row_count": policy.row_count,
        "all_candidates_private": True, "connection_closed": True,
        "snapshot": "explicit SNAPSHOT transaction",
        "tls": {"hostname_verification": True, "full_session_encryption": True, "ca_source": "certifi"},
        "permissions": {key: definition[3] for key, definition in PERMISSIONS.items()},
    }.items():
        _same(record[key], value, "security_" + key)
    _require(UUID(record["database_principal_sid"]) == UUID(context["agent_client_id"]), "sql_identity")
    candidates = record["dns_candidates"]
    _require(isinstance(candidates, list) and 1 <= len(candidates) <= 16 and
             all(value in context["private_ips"] for value in candidates), "sql_dns")
    _same(report["approved_sample_policy"], {
        "source_sha256": policy.source_sha256, "row_count": policy.row_count,
        "periods_are_model_controlled": False,
    }, "sample_policy")
    for key in ("snapshot_begin", "identity_manifest_permission_query", "rollback"):
        _same(report["sql_control_operations"][key], 1, "sql_control_operations")


def validate_run(report, *, mode, source, policy, context):
    """Verify every captured aggregate against the hash-checked reference, including unused results."""
    try:
        validate_context(context)
        _require(type(source) is CsvSalesSource and source.sha256 == policy.source_sha256
                 and source.dataset_id == policy.dataset_id, "reference_source")
        _require(mode in ("baseline", "adaptive"), "mode")
        _same(report["schema_version"], 1, "schema_version")
        _require(report["status"] == "ok", "runtime_failed")
        _same(report["baseline_period"], policy.baseline.as_dict(), "baseline_period")
        _same(report["current_period"], policy.current.as_dict(), "current_period")
        _same(report["coverage"], {"period": policy.coverage.period.as_dict(),
                                   "attestation": policy.coverage.attestation}, "coverage")
        _same(report["causal_conclusions"], [], "unsupported_causality")
        _same(report["hypotheses"], [], "unsupported_hypotheses")
        _security(report, policy, context)
        evidence = report["evidence"]
        _require(isinstance(evidence, list) and 2 <= len(evidence) <= DATA_LIMITS.max_requests, "evidence_count")
        _require(isinstance(report["facts"], list) and 1 <= len(report["facts"]) <= 5, "fact_count")
        execution = report["execution"]
        _require(execution["mode"] == "azure_sql", "execution_mode")
        for key in ("data_requests", "sql_queries_executed"):
            _same(execution[key], len(evidence), "execution_count")
        _same(execution["limits" if mode == "baseline" else "data_limits"], asdict(DATA_LIMITS), "data_limits")
        for index, item in enumerate(evidence, 1):
            _require(item["id"] == f"q{index}", "evidence_ids")
            _require(item["execution_mode"] == "azure_sql" and item["sql_executed"] is True, "sql_execution")
            _require(item["dataset_id"] == policy.dataset_id and item["source_sha256"] is None, "evidence_source")
            period = Period.parse(item["period"]["start"], item["period"]["end_exclusive"])
            _same(item["period"], period.as_dict(), "evidence_period")
            _require(period in (policy.baseline, policy.current), "evidence_period")
            _require(isinstance(item["filters"], dict), "evidence_filters")
            plan = plan_query(period, dimension=item["dimension"], filters=item["filters"],
                              max_groups=DATA_LIMITS.max_groups)
            _same(item["query_plan"], plan.as_dict(), "query_plan")
            values = source.read(plan)
            expected = ([{"id": key, "name": name, **totals.as_dict()}
                         for key, (name, totals) in sorted(values.items())]
                        if isinstance(values, dict) else values.as_dict())
            _same(item["result"], expected, "reference_aggregate")
        _require(validate_report(report)["status"] == "valid", "fact_evidence")
        if mode == "baseline":
            _same(execution["model_requests"], 0, "baseline_model_calls")
            _require(execution.get("model_calls", 0) == 0 and execution.get("model_inference_requests", 0) == 0,
                     "baseline_model_calls")
            expected = run_baseline(Investigator(source, policy.coverage, limits=DATA_LIMITS),
                                    policy.baseline, policy.current)
            for key in ("workflow", "comparison", "territories", "selected_territory", "products", "facts"):
                _same(report[key], expected[key], "baseline_" + key)
            model_calls = 0
            usage = {"status": "known", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        else:
            _require(report["workflow"] == "bounded_adaptive_chat_completions" and report["stop_reason"] == "complete",
                     "adaptive_completion")
            _require(execution["client_kind"] == "inference" and execution["model"] == context["model"], "model_identity")
            _same(execution["limits"], asdict(MODEL_LIMITS), "model_limits")
            model_calls = execution["model_calls"]
            _require(type(model_calls) is int and 2 <= model_calls <= MODEL_LIMITS.max_model_calls, "model_calls")
            _same(execution["model_inference_requests"], model_calls, "model_calls")
            results = report["results"]
            _require(isinstance(results, list) and 1 <= len(results) <= 5, "results")
            _require([item["result_id"] for item in results] == [f"r{i + 1}" for i in range(len(results))], "result_ids")
            _require(validate_report({**report, "facts": results})["status"] == "valid", "all_results")
            fact_ids = [item["result_id"] for item in report["facts"]]
            _require(len(set(fact_ids)) == len(fact_ids), "duplicate_facts")
            for item in results:
                _require(set(item) == {"result_id", "kind", "scope", "evidence_ids", "values"}, "result_shape")
                engine = Investigator(source, policy.coverage, limits=DATA_LIMITS)
                if item["kind"] == "compare":
                    expected = engine.compare(policy.baseline, policy.current, **item["scope"])
                elif item["kind"] == "breakdown":
                    expected = engine.breakdown(policy.baseline, policy.current, **item["scope"])
                else:
                    raise ValidationFailure("result_kind")
                expected["evidence_ids"] = item["evidence_ids"]
                _same(item["values"], expected, "result_values")
            consumed = [key for item in results for key in item["evidence_ids"]]
            _require(consumed == [item["id"] for item in evidence], "unused_evidence")
            _require(any(item["kind"] == "compare" and item["scope"]["filters"] == {} for item in report["facts"]),
                     "overall_comparison")
            _require(all(item.get("scope", {}).get("top_k", 1) <= 5 for item in results), "top_k")
            usage = execution["token_usage"]
            _require(usage["status"] in ("known", "unknown"), "token_usage")
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage[key]
                _require(value is None or type(value) is int and 0 <= value <= MODEL_LIMITS.max_total_tokens, "token_usage")
            _require((usage["status"] == "known") == all(usage[k] is not None for k in
                     ("prompt_tokens", "completion_tokens", "total_tokens")), "token_usage")
            if usage["status"] == "known":
                _require(usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"], "token_usage")
            by_call = execution["usage_by_call"]
            _require(isinstance(by_call, list) and len(by_call) == model_calls, "usage_by_call")
            token_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
            for call in by_call:
                _require(isinstance(call, dict) and set(call) == set(token_keys), "usage_by_call")
                for key in token_keys:
                    _require(call[key] is None or type(call[key]) is int and 0 <= call[key] <= 100000, "usage_by_call")
                _require(call["completion_tokens"] is None or call["completion_tokens"] <= 1024, "usage_by_call")
                if all(call[key] is not None for key in token_keys):
                    _require(call["total_tokens"] == call["prompt_tokens"] + call["completion_tokens"], "usage_by_call")
            for key in token_keys:
                total = sum(call[key] for call in by_call) if all(call[key] is not None for call in by_call) else None
                _same(usage[key], total, "token_usage_total")
            reserved = execution["reserved_tokens"]
            _require(type(reserved) is int and 0 < reserved <= MODEL_LIMITS.max_total_tokens, "reserved_tokens")
            elapsed = execution["elapsed_seconds"]
            _require(type(elapsed) in (int, float) and math.isfinite(elapsed) and 0 <= elapsed <= 120, "elapsed_seconds")
        return {"status": "passed", "reference_checked_requests": len(evidence),
                "model_inference_requests": model_calls, "token_usage": usage, "model_cost": "unknown",
                "numeric_basis": "Every aggregate compared to the pinned CSV; facts recomputed through shared core.",
                "report": report}
    except ValidationFailure:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError, RecursionError):
        raise ValidationFailure("malformed_evidence") from None


def _read(path, limit=MAX_RESPONSE_BYTES):
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    _require(len(content) <= limit, "file_size")
    return content.decode("utf-8-sig")


def failure_receipt(report):
    """Keep bounded diagnostic categories/counters, never unvalidated prose or model context."""
    receipt = {"status": report.get("status") if report.get("status") in
               ("failed", "error", "exhausted", "insufficient_data", "ok") else "unrecognized",
               "accepted_as_success": False}
    if report.get("stop_reason") in ("invalid_model_response", "model_error", "data_error",
                                    "time_limit", "token_limit", "data_request_limit", "insufficient_evidence"):
        receipt["stop_reason"] = report["stop_reason"]
    execution = report.get("execution")
    if isinstance(execution, dict):
        receipt["reported_counters"] = {
            key: execution[key] for key in ("model_calls", "model_inference_requests", "data_requests")
            if type(execution.get(key)) is int and 0 <= execution[key] <= 50
        }
        usage = execution.get("token_usage")
        if isinstance(usage, dict):
            receipt["reported_token_usage"] = {
                key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if type(usage.get(key)) is int and 0 <= usage[key] <= 1000000
            }
    diagnostic = report.get("diagnostics")
    if isinstance(diagnostic, dict):
        safe = {key: diagnostic[key] for key in ("choice_count", "tool_call_count")
                if type(diagnostic.get(key)) is int and 0 <= diagnostic[key] <= 100}
        if diagnostic.get("reason") in set(CONTRACT_REASONS.values()) | {"invalid_metadata_or_json"}:
            safe["reason"] = diagnostic["reason"]
        if diagnostic.get("finish_reason") in ("tool_calls", "stop", "length", "content_filter", "function_call", "other"):
            safe["finish_reason"] = diagnostic["finish_reason"]
        receipt["diagnostics"] = safe
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate pinned reference and saved analytical evidence. No network calls.")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--adaptive", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)
    result = {"schema_version": 1, "status": "failed", "execution_kind": "offline_evidence_validation",
              "real_model_quality_validated": False, "cloud_calls_made": 0}
    try:
        inputs = [args.csv, args.context, args.baseline, args.adaptive]
        _require(all(path is None or path.resolve() != args.output.resolve() for path in inputs), "output_overwrites_input")
        policy = HostedPolicy.load(Path(__file__).with_name("hosted-policy.json"))
        source = CsvSalesSource.from_csv(args.csv, dataset_id=policy.dataset_id, expected_sha256=policy.source_sha256)
        result["reference"] = {"dataset_id": policy.dataset_id, "sha256": policy.source_sha256,
                               "expected_row_count": policy.row_count}
        if args.prepare_only:
            _require(not any((args.baseline, args.adaptive)), "prepare_arguments")
            if args.context:
                validate_context(strict_json(_read(args.context, 16384)))
            result.update(status="prepared", cloud_validation="not_run")
        else:
            _require(args.context is not None and args.baseline is not None, "missing_arguments")
            context = strict_json(_read(args.context, 16384))
            runs = result["runs"] = {}
            for mode, path in (("baseline", args.baseline), ("adaptive", args.adaptive)):
                if path is None:
                    continue
                report = parse_response(_read(path))
                try:
                    runs[mode] = validate_run(report, mode=mode, source=source, policy=policy, context=context)
                except ValidationFailure:
                    runs[mode] = {"status": "failed", "receipt": failure_receipt(report)}
                    raise
            result.update(status="passed" if args.adaptive else "baseline_passed", runs=runs,
                          same_sql_transaction=False,
                          snapshot_basis="Initializer-attested hash plus every captured aggregate matched to the pinned CSV.",
                          limitations=["Saved evidence verification does not independently prove a live invocation.",
                                       "One pair is not a statistical quality, semantic usefulness or cost evaluation."])
    except (ValidationFailure, ValueError, TypeError, KeyError, OSError, RecursionError) as error:
        result["error"] = {"code": error.code if isinstance(error, ValidationFailure) else "invalid_input_or_reference",
                           "message": "Evidence validation failed; raw transcript and exception details are omitted."}
    # Never replace an input even when reporting an invalid output path.
    if any(path is not None and path.resolve() == args.output.resolve()
           for path in (args.csv, args.context, args.baseline, args.adaptive)):
        print(json.dumps({"status": "failed", "error": "output_overwrites_input"}), file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "execution_kind": result["execution_kind"]}))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
