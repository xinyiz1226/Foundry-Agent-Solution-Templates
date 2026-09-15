"""Adapter for a caller-owned, read-only SQL snapshot cursor; no connection setup."""

from decimal import Decimal
from typing import Protocol, Sequence

from .core import Totals
from .queries import QueryPlan


class ReadCursor(Protocol):
    description: Sequence[Sequence[object]] | None

    def execute(self, sql: str, parameters: tuple) -> object: ...
    def fetchmany(self, size: int) -> Sequence[Sequence[object]]: ...


class SqlSalesSource:
    mode = "azure_sql"
    sha256 = None

    def __init__(self, cursor: ReadCursor, *, dataset_id: str, snapshot_attestation: str):
        if not isinstance(dataset_id, str) or not dataset_id.strip() or len(dataset_id) > 256:
            raise ValueError("A bounded, nonempty SQL dataset identifier is required.")
        if not isinstance(snapshot_attestation, str) or not snapshot_attestation.strip() or len(snapshot_attestation) > 2048:
            raise ValueError("The caller must attest a read-only, timeout-bounded snapshot transaction.")
        self.cursor = cursor
        self.dataset_id = dataset_id
        self.snapshot_attestation = snapshot_attestation

    @staticmethod
    def _totals(values: Sequence[object]) -> Totals:
        if len(values) != 4:
            raise ValueError("Unexpected SQL aggregate result shape.")
        rows, sales, cost, orders = values
        if type(rows) is not int or type(orders) is not int or not isinstance(sales, Decimal) or not isinstance(cost, Decimal):
            raise ValueError("SQL aggregate types differ from the approved view contract.")
        return Totals(rows, sales, cost, orders)

    def read(self, plan: QueryPlan) -> Totals | dict[str, tuple[str, Totals]]:
        self.cursor.execute(plan.sql, plan.parameters)
        columns = ["line_count", "sales", "cost", "orders"]
        if plan.dimension:
            columns = ["group_id", "group_name", *columns]
        description = self.cursor.description
        if description is None or [item[0] for item in description] != columns:
            raise ValueError("SQL result columns differ from the approved query contract.")
        maximum = plan.max_groups if plan.dimension else 1
        records = self.cursor.fetchmany(maximum + 1)
        if len(records) > maximum:
            raise ValueError("SQL result exceeds the group budget; partial results are not accepted.")
        if not plan.dimension:
            if len(records) != 1:
                raise ValueError("Expected one explicit overall aggregate, including an empty-data aggregate.")
            return self._totals(records[0])
        groups: dict[str, tuple[str, Totals]] = {}
        for row in records:
            if len(row) != 6:
                raise ValueError("Unexpected SQL group result shape.")
            key, name = row[:2]
            if not isinstance(key, str) or not key or len(key) > 128 or not isinstance(name, str) or not name or len(name) > 256:
                raise ValueError("Invalid SQL dimension identity or label.")
            if key in groups:
                raise ValueError("Duplicate SQL dimension identity; labels/joins require correction.")
            groups[key] = (name, self._totals(row[2:]))
        return groups
