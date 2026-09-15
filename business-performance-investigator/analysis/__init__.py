"""Bounded, deterministic sales analysis, separate from the connectivity probe."""

from .core import Coverage, CsvSalesSource, Investigator, Limits, Period, run_baseline
from .queries import View, plan_query

__all__ = ["Coverage", "CsvSalesSource", "Investigator", "Limits", "Period", "View", "plan_query", "run_baseline"]
