"""SQL Server plans: identifiers are approved, values are always parameters."""

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from .core import Period


@dataclass(frozen=True)
class View:
    schema: str = "reporting"
    name: str = "v_internet_sales"

    def __post_init__(self):
        if any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", item) for item in (self.schema, self.name)):
            raise ValueError("Approved view identifiers must be simple SQL identifiers.")

    @property
    def sql(self) -> str:
        return f"[{self.schema}].[{self.name}]"


@dataclass(frozen=True)
class QueryPlan:
    period: "Period"
    dimension: str | None
    filters: Mapping[str, str]
    max_groups: int
    sql: str
    parameters: tuple

    def as_dict(self) -> dict:
        return {
            "dialect": "azure_sql",
            "sql": self.sql,
            "parameters": [value.isoformat() if hasattr(value, "isoformat") else value for value in self.parameters],
            "parameter_style": "python-tds positional %s",
        }


def plan_query(period: "Period", *, dimension=None, filters=None, max_groups=1000, view=View()) -> QueryPlan:
    if type(max_groups) is not int or not 1 <= max_groups <= 10000:
        raise ValueError("max_groups must be between 1 and 10000.")
    filters = dict(filters or {})
    if dimension not in (None, "territory", "product"):
        raise ValueError("Unapproved analysis dimension.")
    if any(key not in ("territory", "product") for key in filters):
        raise ValueError("Unapproved analysis filter.")
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in filters.values()):
        raise ValueError("Filter IDs must be nonempty strings of at most 128 characters.")
    parameters: list = []
    select = ""
    group = ""
    if dimension:
        select = f"CONVERT(nvarchar(128), [{dimension}_id]) AS group_id, [{dimension}_name] AS group_name,\n"
        group = f"\nGROUP BY [{dimension}_id], [{dimension}_name]\nORDER BY [{dimension}_id], [{dimension}_name]"
    parameters.append(max_groups + 1 if dimension else 1)
    parameters.extend((period.start, period.end))
    predicates = ["[order_date] >= %s", "[order_date] < %s"]
    for key, value in sorted(filters.items()):
        predicates.append(f"CONVERT(nvarchar(128), [{key}_id]) = %s")
        parameters.append(value)
    sql = (
        f"SELECT TOP (%s) {select}COUNT_BIG(*) AS line_count,\n"
        "COALESCE(SUM([sales_amount]), 0) AS sales,\n"
        "COALESCE(SUM([total_product_cost]), 0) AS cost,\n"
        "COUNT(DISTINCT [sales_order_number]) AS orders\n"
        f"FROM {view.sql}\nWHERE " + " AND ".join(predicates) + group + ";"
    )
    return QueryPlan(period, dimension, filters, max_groups, sql, tuple(parameters))
