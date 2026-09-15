from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Mapping, Protocol, Sequence
import hashlib
import json
import re
import csv
import io
from itertools import islice
from pathlib import Path
from time import monotonic

from .queries import QueryPlan, View, plan_query


MONEY = Decimal("0.0001")
RATIO = Decimal("0.000001")
FIELDS = (
    "order_date", "sales_order_number", "product_id", "product_name",
    "territory_id", "territory_name", "sales_amount", "total_product_cost",
)
MAX_RECORDS = 200000


def decimal_amount(value: str) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:[0-9]{1,15}(?:\.[0-9]{1,4})?|\.[0-9]{1,4})", value):
        raise ValueError("Money must be finite decimal text with at most four fractional digits.")
    return Decimal(value)


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY, rounding=ROUND_HALF_EVEN))


def ratio(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(RATIO, rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class Period:
    start: date
    end: date

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date or self.start >= self.end:
            raise ValueError("A period requires ordered dates and an exclusive end.")

    @classmethod
    def parse(cls, start: str, end: str) -> "Period":
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) for value in (start, end)):
            raise ValueError("Period dates must use YYYY-MM-DD strings.")
        return cls(date.fromisoformat(start), date.fromisoformat(end))

    def contains(self, value: date) -> bool:
        return self.start <= value < self.end

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end_exclusive": self.end.isoformat()}


@dataclass(frozen=True)
class Coverage:
    period: Period
    attestation: str

    def __post_init__(self):
        if not isinstance(self.period, Period):
            raise ValueError("Coverage requires a validated period.")
        if not isinstance(self.attestation, str) or not self.attestation.strip() or len(self.attestation) > 4096:
            raise ValueError("Explicit data-completeness attestation is required.")

    def validate(self, period: Period):
        if period.start < self.period.start or period.end > self.period.end:
            raise ValueError("Requested period lies outside attested complete coverage.")


@dataclass(frozen=True)
class Sale:
    order_date: date
    sales_order_number: str
    product_id: str
    product_name: str
    territory_id: str
    territory_name: str
    sales_amount: Decimal
    total_product_cost: Decimal


@dataclass(frozen=True)
class Totals:
    rows: int
    sales: Decimal
    cost: Decimal
    orders: int

    def __post_init__(self):
        if type(self.rows) is not int or type(self.orders) is not int or not 0 <= self.orders <= self.rows:
            raise ValueError("Invalid aggregate row/order counts.")
        for value in (self.sales, self.cost):
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError("Aggregate money must be finite Decimal values.")
        if self.rows == 0 and (self.sales or self.cost or self.orders):
            raise ValueError("Empty aggregates cannot contain sales, cost or orders.")

    @property
    def profit(self) -> Decimal:
        return self.sales - self.cost

    @property
    def margin(self) -> Decimal | None:
        return self.profit / self.sales if self.sales else None

    def as_dict(self) -> dict:
        return {
            "status": "ok" if self.rows else "no_data",
            "line_count": self.rows,
            "sales": money(self.sales),
            "total_product_cost": money(self.cost),
            "orders": self.orders,
            "gross_profit": money(self.profit),
            "gross_margin": ratio(self.margin),
        }


class CsvSalesSource:
    mode = "offline_csv"

    def __init__(self, rows: Sequence[Sale], dataset_id: str):
        if not isinstance(dataset_id, str) or not dataset_id.strip() or len(dataset_id) > 256:
            raise ValueError("A bounded, nonempty dataset identifier is required.")
        if len(rows) > MAX_RECORDS:
            raise ValueError("Sample exceeds the maximum record budget.")
        for dimension in ("territory", "product"):
            names: dict[str, str] = {}
            for row in rows:
                key, name = getattr(row, dimension + "_id"), getattr(row, dimension + "_name")
                if key in names and names[key] != name:
                    raise ValueError(f"Inconsistent {dimension} label for a surrogate ID.")
                names[key] = name
        self._rows = tuple(rows)
        self.dataset_id = dataset_id
        self.sha256 = hashlib.sha256(
            json.dumps([asdict(row) for row in rows], default=str, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_records(cls, records: Sequence[Mapping[str, str]], *, dataset_id: str):
        if len(records) > MAX_RECORDS:
            raise ValueError("Sample exceeds the maximum record budget.")
        for row in records:
            if set(row) != set(FIELDS):
                raise ValueError("Normalized sales records must contain exactly the approved columns.")
            for key in FIELDS:
                value = row[key]
                if not isinstance(value, str) or not value.strip() or len(value) > 256:
                    raise ValueError("Normalized sales fields must be bounded nonempty text.")
                if key.endswith("_id") or key == "sales_order_number":
                    if len(value) > 128:
                        raise ValueError("Surrogate IDs and order numbers must fit 128 characters.")
        rows = [
            Sale(
                order_date=date.fromisoformat(row["order_date"]),
                sales_order_number=row["sales_order_number"],
                product_id=row["product_id"],
                product_name=row["product_name"],
                territory_id=row["territory_id"],
                territory_name=row["territory_name"],
                sales_amount=decimal_amount(row["sales_amount"]),
                total_product_cost=decimal_amount(row["total_product_cost"]),
            )
            for row in records
        ]
        return cls(rows, dataset_id)

    @classmethod
    def from_csv(cls, path: Path, *, dataset_id: str, expected_sha256: str):
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
            raise ValueError("A lowercase SHA-256 of the reviewed CSV is required.")
        with Path(path).open("rb") as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError("CSV exceeds the 64 MiB input budget.")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_sha256:
            raise ValueError("CSV SHA-256 does not match the reviewed configuration.")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        if reader.fieldnames is None or tuple(reader.fieldnames) != FIELDS:
            raise ValueError("CSV must contain the exact approved normalized header.")
        records = list(islice(reader, MAX_RECORDS + 1))
        result = cls.from_records(records, dataset_id=dataset_id)
        result.sha256 = digest
        return result

    @staticmethod
    def _sum(rows: Sequence[Sale]) -> Totals:
        return Totals(
            len(rows),
            sum((row.sales_amount for row in rows), Decimal(0)),
            sum((row.total_product_cost for row in rows), Decimal(0)),
            len({row.sales_order_number for row in rows}),
        )

    def _select(self, period: Period, filters: Mapping[str, str] | None):
        filters = filters or {}
        if any(key not in ("territory", "product") for key in filters):
            raise ValueError("Only approved territory/product filters are supported.")
        return [
            row for row in self._rows if period.contains(row.order_date)
            and all(getattr(row, key + "_id") == value for key, value in filters.items())
        ]

    def totals(self, period: Period, filters: Mapping[str, str] | None = None) -> Totals:
        return self._sum(self._select(period, filters))

    def groups(self, period: Period, dimension: str, filters: Mapping[str, str] | None = None):
        if dimension not in ("territory", "product"):
            raise ValueError("Only approved territory/product dimensions are supported.")
        groups: dict[str, list[Sale]] = {}
        for row in self._select(period, filters):
            groups.setdefault(getattr(row, dimension + "_id"), []).append(row)
        return {
            key: (getattr(rows[0], dimension + "_name"), self._sum(rows))
            for key, rows in groups.items()
        }

    def read(self, plan: QueryPlan):
        if plan.dimension:
            groups = self.groups(plan.period, plan.dimension, plan.filters)
            if len(groups) > plan.max_groups:
                raise ValueError("Dimension exceeds the group budget; no truncated evidence is returned.")
            return groups
        return self.totals(plan.period, plan.filters)


@dataclass(frozen=True)
class Limits:
    max_requests: int = 10
    max_groups: int = 1000
    max_seconds: float = 30

    def __post_init__(self):
        if type(self.max_requests) is not int or not 1 <= self.max_requests <= 50:
            raise ValueError("max_requests must be between 1 and 50.")
        if type(self.max_groups) is not int or not 1 <= self.max_groups <= 10000:
            raise ValueError("max_groups must be between 1 and 10000.")
        if type(self.max_seconds) not in (int, float) or not 0 < self.max_seconds <= 120:
            raise ValueError("max_seconds must be positive and at most 120.")


class SalesSource(Protocol):
    mode: str
    dataset_id: str
    sha256: str | None

    def read(self, plan: QueryPlan) -> Totals | dict[str, tuple[str, Totals]]: ...


class Investigator:
    def __init__(self, source: SalesSource, coverage: Coverage, *, limits=Limits(), view=View()):
        self.source = source
        self.coverage = coverage
        self.limits = limits
        self.view = view
        self.evidence: list[dict] = []
        self.requests = 0
        self._started: float | None = None

    def _read(self, period: Period, filters=None, dimension=None):
        plan = plan_query(period, filters=filters, dimension=dimension, max_groups=self.limits.max_groups, view=self.view)
        if self._started is None:
            self._started = monotonic()
        if self.requests >= self.limits.max_requests or monotonic() - self._started > self.limits.max_seconds:
            raise ValueError("Analysis execution budget exhausted.")
        self.requests += 1
        started = monotonic()
        result = self.source.read(plan)
        if monotonic() - self._started > self.limits.max_seconds:
            raise ValueError("Analysis execution time budget exhausted; result is not accepted.")
        records = (
            [{"id": key, "name": name, **totals.as_dict()} for key, (name, totals) in sorted(result.items())]
            if isinstance(result, dict) else result.as_dict()
        )
        self.evidence.append({
            "id": f"q{self.requests}",
            "execution_mode": self.source.mode,
            "sql_executed": self.source.mode == "azure_sql",
            "dataset_id": self.source.dataset_id,
            "source_sha256": self.source.sha256,
            "snapshot_attestation": getattr(self.source, "snapshot_attestation", None),
            "period": period.as_dict(),
            "filters": dict(plan.filters),
            "dimension": dimension,
            "query_plan": plan.as_dict(),
            "result": records,
            "elapsed_seconds": round(monotonic() - started, 6),
        })
        return result

    def _validate_periods(self, baseline: Period, current: Period):
        self.coverage.validate(baseline)
        self.coverage.validate(current)
        if baseline.end > current.start:
            raise ValueError("Comparison periods must be disjoint, baseline first.")

    def compare(self, baseline: Period, current: Period, *, filters=None) -> dict:
        with localcontext(prec=60):
            return self._compare(baseline, current, filters=filters)

    def _compare(self, baseline: Period, current: Period, *, filters=None) -> dict:
        self._validate_periods(baseline, current)
        before = self._read(baseline, filters)
        after = self._read(current, filters)
        return {
            "evidence_ids": [item["id"] for item in self.evidence[-2:]],
            "baseline": before.as_dict(),
            "current": after.as_dict(),
            "change": {
                "sales": money(after.sales - before.sales),
                "orders": after.orders - before.orders,
                "gross_profit": money(after.profit - before.profit),
                "sales_relative": ratio((after.sales - before.sales) / before.sales)
                if before.sales > 0 else None,
                "sales_relative_status": "defined" if before.sales > 0 else "nonpositive_baseline",
                "gross_margin_percentage_points": ratio((after.margin - before.margin) * 100)
                if after.margin is not None and before.margin is not None else None,
            },
        }

    def breakdown(self, baseline: Period, current: Period, *, dimension: str, filters=None, top_k=5) -> dict:
        with localcontext(prec=60):
            return self._breakdown(baseline, current, dimension=dimension, filters=filters, top_k=top_k)

    def _breakdown(self, baseline: Period, current: Period, *, dimension: str, filters=None, top_k=5) -> dict:
        self._validate_periods(baseline, current)
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20.")
        before = self._read(baseline, filters, dimension)
        after = self._read(current, filters, dimension)
        empty = ("", Totals(0, Decimal(0), Decimal(0), 0))
        changes = []
        for key in before.keys() | after.keys():
            name = before.get(key, after.get(key, empty))[0]
            first = before.get(key, empty)[1]
            last = after.get(key, empty)[1]
            changes.append((key, name, first.sales, last.sales, last.sales - first.sales))
        changes.sort(key=lambda row: (-abs(row[4]), row[0]))
        current_total = self._read(current, filters).sales
        baseline_total = self._read(baseline, filters).sales
        if (sum((row[2] for row in changes), Decimal(0)) != baseline_total
                or sum((row[3] for row in changes), Decimal(0)) != current_total):
            raise ValueError("Dimension period totals do not reconcile to overall sales.")
        total = current_total - baseline_total
        if sum((row[4] for row in changes), Decimal(0)) != total:
            raise ValueError("Dimension changes do not reconcile to the overall sales change.")
        return {
            "evidence_ids": [item["id"] for item in self.evidence[-4:]],
            "dimension": dimension,
            "baseline_sales": money(baseline_total),
            "current_sales": money(current_total),
            "total_change": money(total),
            "segments": [
                {
                    "id": key, "name": name, "baseline_sales": money(first),
                    "current_sales": money(last), "change": money(change),
                    "contribution_share": ratio(change / total) if abs(total) > Decimal("0.01") else None,
                }
                for key, name, first, last, change in changes[:top_k]
            ],
            "other": {
                "group_count": len(changes[top_k:]),
                "baseline_sales": money(sum((row[2] for row in changes[top_k:]), Decimal(0))),
                "current_sales": money(sum((row[3] for row in changes[top_k:]), Decimal(0))),
                "change": money(sum((row[4] for row in changes[top_k:]), Decimal(0))),
            },
            "contribution_share_status": "defined" if abs(total) > Decimal("0.01") else "near_zero_net_change",
            "reconciled": True,
        }


def run_baseline(investigator: Investigator, baseline: Period, current: Period, *, top_k=5) -> dict:
    if investigator.requests:
        raise ValueError("A report requires a fresh investigator and execution budget.")
    comparison = investigator.compare(baseline, current)
    territories = investigator.breakdown(baseline, current, dimension="territory", top_k=top_k)
    if (territories["baseline_sales"] != comparison["baseline"]["sales"]
            or territories["current_sales"] != comparison["current"]["sales"]):
        raise ValueError("Territory totals do not reconcile to the original comparison; verify snapshot consistency.")
    selected = next((row for row in territories["segments"] if Decimal(row["change"]) != 0), None)
    products = None
    if selected:
        products = investigator.breakdown(
            baseline, current, dimension="product", filters={"territory": selected["id"]}, top_k=top_k
        )
        if (products["total_change"] != selected["change"]
                or products["baseline_sales"] != selected["baseline_sales"]
                or products["current_sales"] != selected["current_sales"]):
            raise ValueError("Product drilldown does not reconcile to its selected territory.")
    facts = [
        {"kind": "overall_metrics", "evidence_ids": comparison["evidence_ids"], "values": comparison},
        {"kind": "territory_sales_changes", "evidence_ids": territories["evidence_ids"], "values": territories},
    ]
    if products:
        facts.append({"kind": "selected_territory_product_changes", "evidence_ids": products["evidence_ids"], "values": products})
    return {
        "schema_version": 1,
        "status": "insufficient_data" if any(comparison[key]["status"] == "no_data" for key in ("baseline", "current")) else "ok",
        "workflow": "fixed_comparison_territory_largest_absolute_change_product",
        "baseline_period": baseline.as_dict(),
        "current_period": current.as_dict(),
        "coverage": {"period": investigator.coverage.period.as_dict(), "attestation": investigator.coverage.attestation},
        "comparison": comparison,
        "territories": territories,
        "selected_territory": selected,
        "products": products,
        "facts": facts,
        "hypotheses": [],
        "causal_conclusions": [],
        "missing_evidence": [
            "Sales attribution is descriptive, not causal; campaigns, pricing, availability and demand evidence are not present.",
            "Different period lengths and seasonality are not controlled by a comparison of totals.",
            "Completeness depends on the declared source attestation, not the maximum transaction date.",
            "This fixed baseline drills one territory only; other material offsets are not investigated exhaustively.",
        ],
        "execution": {
            "mode": investigator.source.mode,
            "data_requests": investigator.requests,
            "sql_queries_executed": sum(item["sql_executed"] for item in investigator.evidence),
            "model_requests": 0,
            "limits": asdict(investigator.limits),
        },
        "evidence": list(investigator.evidence),
    }
