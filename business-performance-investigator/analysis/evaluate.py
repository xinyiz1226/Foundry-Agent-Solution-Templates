"""Matched local snapshot evaluation; replay measures the harness, not model quality."""

import copy
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
import re
from time import monotonic

from .adaptive import AdaptiveLimits, run_adaptive
from .core import Coverage, CsvSalesSource, Investigator, Limits, Period, Totals, run_baseline


@dataclass(frozen=True)
class PriceConfig:
    model: str
    input_per_million: str
    output_per_million: str
    currency: str = "USD"

    def __post_init__(self):
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 256:
            raise ValueError("An explicit priced model identifier is required.")
        if not isinstance(self.currency, str) or not re.fullmatch("[A-Z]{3}", self.currency):
            raise ValueError("Currency must be an explicit three-letter code.")
        for value in (self.input_per_million, self.output_per_million):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,8})?", value):
                raise ValueError("Prices must be finite nonnegative bounded decimal strings.")


@dataclass(frozen=True)
class _CsvSnapshot:
    _source: CsvSalesSource = field(repr=False)

    @property
    def mode(self):
        return self._source.mode

    @property
    def dataset_id(self):
        return self._source.dataset_id

    @property
    def sha256(self):
        return self._source.sha256

    def read(self, plan):
        return self._source.read(plan)


class _EvidenceSource:
    """Re-evaluate captured aggregates through core, without any new data requests."""

    mode = "evidence_replay"
    dataset_id = "evaluation-evidence"
    sha256 = None

    def __init__(self, evidence):
        self._evidence = iter(evidence)

    @staticmethod
    def _totals(record):
        totals = Totals(record["line_count"], Decimal(record["sales"]),
                        Decimal(record["total_product_cost"]), record["orders"])
        if any(record.get(key) != value for key, value in totals.as_dict().items()):
            raise ValueError("Aggregate evidence contains inconsistent derived values.")
        return totals

    def read(self, plan):
        item = next(self._evidence)
        if (item["period"] != plan.period.as_dict() or item["dimension"] != plan.dimension
                or item["filters"] != dict(plan.filters)):
            raise ValueError("Evidence scope does not match the analytical operation.")
        value = item["result"]
        if plan.dimension:
            if not isinstance(value, list) or len(value) > 10000:
                raise ValueError("Invalid group evidence.")
            result = {}
            for record in value:
                if record["id"] in result:
                    raise ValueError("Duplicate group evidence.")
                result[record["id"]] = (record["name"], self._totals(record))
            return result
        return self._totals(value)


def _period(value):
    return Period.parse(value["start"], value["end_exclusive"])


def validate_report(report):
    """Check provenance and recompute facts using core; not an independent math oracle."""
    numeric_valid, evidence_valid = True, True
    facts = report.get("facts", [])
    if not facts:
        return {"status": "not_evaluated", "numeric_valid": None, "evidence_valid": None, "facts_checked": 0}
    try:
        evidence_list = report["evidence"]
        evidence = {item["id"]: item for item in evidence_list}
        if len(evidence) != len(evidence_list):
            raise ValueError("Duplicate evidence IDs.")
        identities = {(item["dataset_id"], item["source_sha256"]) for item in evidence_list}
        if len(identities) != 1:
            raise ValueError("Mismatched evidence sources.")
        before, after = _period(report["baseline_period"]), _period(report["current_period"])
        coverage = Coverage(_period(report["coverage"]["period"]), report["coverage"]["attestation"])
    except (KeyError, TypeError, ValueError):
        return {"status": "invalid", "numeric_valid": False, "evidence_valid": False, "facts_checked": 0}
    for fact in facts:
        try:
            ids = fact["evidence_ids"]
            if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                    or ids != fact["values"]["evidence_ids"] or any(key not in evidence for key in ids)):
                raise ValueError("Invalid fact evidence IDs.")
            rows = [evidence[key] for key in ids]
        except (KeyError, TypeError, ValueError):
            evidence_valid, numeric_valid = False, False
            continue
        try:
            engine = Investigator(_EvidenceSource(rows), coverage,
                                  limits=Limits(max_requests=4, max_groups=10000, max_seconds=120))
            dimension = rows[0]["dimension"]
            filters = rows[0]["filters"]
            if dimension is None:
                expected = engine.compare(before, after, filters=filters)
            else:
                top_k = fact.get("scope", {}).get("top_k", max(1, len(fact["values"]["segments"])))
                expected = engine.breakdown(before, after, dimension=dimension, filters=filters, top_k=top_k)
            expected["evidence_ids"] = ids
            if expected != fact["values"] or len(rows) != engine.requests:
                numeric_valid = False
            if "scope" in fact:
                expected_scope = {"filters": filters}
                if dimension is not None:
                    expected_scope.update(dimension=dimension, top_k=top_k)
                if (fact["scope"] != expected_scope
                        or fact["kind"] != ("compare" if dimension is None else "breakdown")):
                    evidence_valid = False
            if "result_id" in fact:
                matches = [item for item in report["results"] if item["result_id"] == fact["result_id"]]
                if len(matches) != 1 or matches[0] != fact:
                    evidence_valid, numeric_valid = False, False
        except (KeyError, TypeError, ValueError, InvalidOperation, StopIteration):
            numeric_valid = False
            evidence_valid = False
    return {
        "status": "valid" if numeric_valid and evidence_valid else "invalid",
        "numeric_valid": numeric_valid, "evidence_valid": evidence_valid, "facts_checked": len(facts),
    }


def _scope(report, targets):
    evidence = {item["id"]: item for item in report["evidence"]}
    selected, products, discovered = set(), set(), {}
    for result in report.get("results", report.get("facts", [])):
        rows = [evidence[key] for key in result["evidence_ids"]]
        filters = rows[0]["filters"]
        if "territory" in filters:
            selected.add(filters["territory"])
            if rows[0]["dimension"] == "product":
                products.add(filters["territory"])
        if rows[0]["dimension"] == "territory":
            for row in result["values"]["segments"]:
                discovered[row["id"]] = row["name"]
    return {
        "declared_coverage": report["coverage"], "discovered_territories": discovered,
        "selected_territory_ids": sorted(selected), "product_drilldown_territory_ids": sorted(products),
        "target_territory_ids": targets,
        "target_product_coverage": set(targets).issubset(products) if targets else None,
        "uncovered_target_territory_ids": sorted(set(targets) - products),
        "exhaustive_coverage_claimed": False,
    }


def _cost(usage, prices, model, is_replay):
    unknown = {"status": "unknown", "estimated_model_cost": None, "currency": None,
               "platform_cost": None, "price_config": asdict(prices) if prices else None}
    if is_replay or prices is None or usage["status"] != "known":
        return unknown
    if prices.model != model:
        raise ValueError("Price configuration must identify the exact selected model.")
    value = (Decimal(usage["prompt_tokens"]) * Decimal(prices.input_per_million)
             + Decimal(usage["completion_tokens"]) * Decimal(prices.output_per_million)) / Decimal(1000000)
    return {
        "status": "estimated", "estimated_model_cost": str(value.quantize(Decimal("0.00000001"))),
        "currency": prices.currency, "platform_cost": None, "price_config": asdict(prices),
        "basis": "Explicit flat token rates; excludes caching, discounts, taxes and platform resources.",
    }


def run_evaluation(investigator: Investigator, baseline: Period, current: Period,
                   question: str, client, model: str, *, limits=AdaptiveLimits(), top_k=5,
                   target_territory_ids=(), prices: PriceConfig | None = None):
    """Run both paths on one private read-only CSV copy. No SQL/cloud source accepted."""
    if type(investigator.source) is not CsvSalesSource or investigator.requests or investigator.evidence:
        raise ValueError("Evaluation requires a fresh local CsvSalesSource investigator.")
    if type(top_k) is not int or not 1 <= top_k <= limits.max_top_k:
        raise ValueError("Baseline top_k must fit the shared adaptive top_k cap.")
    limits = replace(limits, max_top_k=top_k)
    if (not isinstance(question, str) or not question.strip() or len(question) > limits.max_question_chars
            or not isinstance(model, str) or not model.strip() or len(model) > 256):
        raise ValueError("A bounded question and model identifier are required.")
    if not isinstance(target_territory_ids, (list, tuple)):
        raise ValueError("Target territory IDs must be a list or tuple, not text.")
    targets = list(target_territory_ids)
    if (len(targets) > 20 or any(not isinstance(item, str) or not item or len(item) > 128 for item in targets)
            or len(targets) != len(set(targets))):
        raise ValueError("Targets must be unique bounded territory IDs.")
    if prices is not None and (not isinstance(prices, PriceConfig) or prices.model != model):
        raise ValueError("Price configuration must identify the exact selected model.")
    source = _CsvSnapshot(copy.deepcopy(investigator.source))
    engines = [Investigator(source, investigator.coverage, limits=investigator.limits, view=investigator.view)
               for _ in range(2)]
    started = monotonic()
    try:
        fixed = run_baseline(engines[0], baseline, current, top_k=top_k)
    except Exception:
        fixed = {
            "status": "error", "stop_reason": "baseline_failed", "facts": [],
            "evidence": list(engines[0].evidence), "baseline_period": baseline.as_dict(),
            "current_period": current.as_dict(),
            "coverage": {"period": investigator.coverage.period.as_dict(), "attestation": investigator.coverage.attestation},
            "execution": {"data_requests": engines[0].requests},
        }
    fixed_elapsed = round(monotonic() - started, 6)
    adaptive = run_adaptive(engines[1], baseline, current, question, client, model, limits=limits)
    replay = adaptive["execution"]["client_kind"] == "replay"
    zero_usage = {"status": "known", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    output = {
        "schema_version": 1,
        "execution_kind": "replay_harness_only" if replay else "caller_supplied_model",
        "real_model_quality_validated": False,
        "question": question, "baseline_uses_question": False,
        "snapshot": {"dataset_id": source.dataset_id, "source_sha256": source.sha256,
                     "mode": source.mode, "matched": True, "read_only_private_copy": True},
        "shared_configuration": {
            "baseline": baseline.as_dict(), "current": current.as_dict(),
            "coverage": adaptive["coverage"], "data_limits": asdict(investigator.limits),
            "baseline_top_k": top_k, "max_top_k": limits.max_top_k, "adaptive_limits": asdict(limits),
        },
        "limitations": [
            "Replay tool selections are scripted; results do not establish DeepSeek intelligence, quality, latency or cost.",
            "The baseline is question-agnostic and always selects the largest absolute territory change.",
            "Validity replays aggregate evidence through core; the existing twelve mathematical reference tests remain the oracle.",
            "No causal correctness, business usefulness, generalization or cloud runtime was evaluated.",
        ],
    }
    for label, report, elapsed, usage in (
        ("baseline", fixed, fixed_elapsed, zero_usage),
        ("adaptive", adaptive, adaptive["execution"]["elapsed_seconds"], adaptive["execution"]["token_usage"]),
    ):
        output[label] = {"report": report, "metrics": {
            "status": report["status"], "validity": validate_report(report),
            "scope": _scope(report, targets), "data_requests": report["execution"]["data_requests"],
            "model_calls": report["execution"].get("model_calls", 0),
            "model_inference_requests": report["execution"].get("model_calls", 0) if not replay else 0,
            "elapsed_seconds": elapsed,
            "latency_kind": "local_replay_wall_time" if replay else "caller_wall_time",
            "token_usage": usage,
            "cost": _cost(usage, prices, model, replay) if label == "adaptive" else {
                "status": "not_applicable_no_model", "estimated_model_cost": None,
                "currency": None, "platform_cost": None, "price_config": None,
            },
        }}
    return output
