"""SQL transport contracts, not a claim of live Azure SQL query execution."""

from decimal import Decimal
import unittest

from test_business_analysis import BASELINE, CURRENT, COVERAGE
from analysis import Investigator, Limits, run_baseline
from analysis.sql_source import SqlSalesSource


class Cursor:
    def __init__(self, results, columns):
        self.results = iter(results)
        self.description = [(column,) for column in columns]
        self.calls = []

    def execute(self, sql, parameters):
        self.calls.append((sql, parameters))

    def fetchmany(self, limit):
        return next(self.results)


class SqlTransportTests(unittest.TestCase):
    def test_bounded_parameterized_cursor_results_use_the_same_metric_contract(self):
        cursor = Cursor(
            [[(4, Decimal("400"), Decimal("270"), 3)], [(4, Decimal("400"), Decimal("276"), 3)]],
            ["line_count", "sales", "cost", "orders"],
        )
        source = SqlSalesSource(cursor, dataset_id="approved-view-snapshot", snapshot_attestation="Caller holds a read-only snapshot transaction with a 15s query timeout.")
        analysis = Investigator(source, COVERAGE)
        result = analysis.compare(BASELINE, CURRENT)
        self.assertEqual(result["baseline"]["gross_profit"], "130.0000")
        self.assertEqual(result["current"]["gross_margin"], "0.310000")
        self.assertEqual(cursor.calls[0][1], (1, BASELINE.start, BASELINE.end))
        self.assertNotIn("2024-01-01", cursor.calls[0][0])
        self.assertTrue(analysis.evidence[0]["sql_executed"])
        self.assertIsNone(analysis.evidence[0]["source_sha256"])

    def test_sql_result_limits_and_malformed_aggregates_are_not_silently_accepted(self):
        columns = ["group_id", "group_name", "line_count", "sales", "cost", "orders"]
        cursor = Cursor([[("10", "North", 1, Decimal(1), Decimal(0), 1),
                          ("20", "South", 1, Decimal(1), Decimal(0), 1)]], columns)
        source = SqlSalesSource(cursor, dataset_id="test", snapshot_attestation="Test boundary fixture")
        with self.assertRaisesRegex(ValueError, "group budget"):
            Investigator(source, COVERAGE, limits=Limits(max_groups=1)).breakdown(BASELINE, CURRENT, dimension="territory")
        cursor = Cursor([[(1, Decimal("NaN"), Decimal(0), 1)]], ["line_count", "sales", "cost", "orders"])
        source = SqlSalesSource(cursor, dataset_id="test", snapshot_attestation="Test boundary fixture")
        with self.assertRaises(ValueError):
            Investigator(source, COVERAGE).compare(BASELINE, CURRENT)

    def test_matching_net_changes_do_not_hide_wrong_period_totals(self):
        class AggregateCursor(Cursor):
            def execute(self, sql, parameters):
                super().execute(sql, parameters)
                names = (["group_id", "group_name"] if "GROUP BY" in sql else []) + ["line_count", "sales", "cost", "orders"]
                self.description = [(name,) for name in names]

        cursor = AggregateCursor(
            [
                [("10", "North", 1, Decimal("500"), Decimal(0), 1)],
                [("10", "North", 1, Decimal("500"), Decimal(0), 1)],
                [(1, Decimal("400"), Decimal(0), 1)],
                [(1, Decimal("400"), Decimal(0), 1)],
            ], [],
        )
        source = SqlSalesSource(cursor, dataset_id="inconsistent-snapshot", snapshot_attestation="Test fixture")
        with self.assertRaisesRegex(ValueError, "period totals"):
            Investigator(source, COVERAGE).breakdown(BASELINE, CURRENT, dimension="territory")

    def test_large_exact_totals_do_not_overflow_ratio_rounding(self):
        cursor = Cursor(
            [[(1, Decimal("0.0001"), Decimal(0), 1)],
             [(200000, Decimal("99999999999999999999"), Decimal(0), 1)]],
            ["line_count", "sales", "cost", "orders"],
        )
        source = SqlSalesSource(cursor, dataset_id="large-reference", snapshot_attestation="Test boundary fixture")
        result = Investigator(source, COVERAGE).compare(BASELINE, CURRENT)
        self.assertEqual(result["change"]["sales_relative"], "999999999999999999989999.000000")

    def test_report_rejects_snapshot_drift_between_comparison_and_breakdown(self):
        class ChangingCursor(Cursor):
            def execute(self, sql, parameters):
                super().execute(sql, parameters)
                names = (["group_id", "group_name"] if "GROUP BY" in sql else []) + ["line_count", "sales", "cost", "orders"]
                self.description = [(name,) for name in names]

        def total(sales):
            return (1, Decimal(sales), Decimal(0), 1)

        cursor = ChangingCursor(
            [
                [total("400")], [total("400")],
                [("10", "North", *total("400"))],
                [("10", "North", *total("420"))],
                [total("420")], [total("400")],
                [("1", "Alpha", *total("400"))],
                [("1", "Alpha", *total("420"))],
                [total("420")], [total("400")],
            ], [],
        )
        source = SqlSalesSource(cursor, dataset_id="drifting", snapshot_attestation="An intentionally false test attestation")
        with self.assertRaisesRegex(ValueError, "comparison"):
            run_baseline(Investigator(source, COVERAGE), BASELINE, CURRENT)

if __name__ == "__main__":
    unittest.main()
