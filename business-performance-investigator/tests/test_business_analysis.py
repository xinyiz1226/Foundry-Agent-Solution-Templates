"""Analytical contracts with independently worked monetary reference values."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis import Coverage, CsvSalesSource, Investigator, Period


COLUMNS = (
    "order_date", "sales_order_number", "product_id", "product_name",
    "territory_id", "territory_name", "sales_amount", "total_product_cost",
)
LINES = [
    ("2024-01-05", "O1", "1", "Alpha", "10", "North", "100", "60"),
    ("2024-01-05", "O1", "2", "Beta", "10", "North", "50", "30"),
    ("2024-01-12", "O2", "1", "Alpha", "20", "South", "200", "160"),
    ("2024-01-20", "O3", "2", "Beta", "20", "South", "50", "20"),
    ("2024-02-05", "O4", "1", "Alpha", "10", "North", "80", "56"),
    ("2024-02-05", "O4", "2", "Beta", "10", "North", "40", "24"),
    ("2024-02-12", "O5", "1", "Alpha", "20", "South", "280", "196"),
    ("2024-02-20", "O6", "2", "Beta", "20", "South", "0", "0"),
]
BASELINE = Period.parse("2024-01-01", "2024-02-01")
CURRENT = Period.parse("2024-02-01", "2024-03-01")
COVERAGE = Coverage(
    Period.parse("2024-01-01", "2024-04-01"),
    "Hand-authored complete synthetic ledger; March intentionally has no sales.",
)


def investigator(lines=LINES, **kwargs):
    source = CsvSalesSource.from_records(
        [dict(zip(COLUMNS, line)) for line in lines], dataset_id="worked-example"
    )
    return Investigator(source, COVERAGE, **kwargs)


class BusinessAnalysisTests(unittest.TestCase):
    def test_period_comparison_uses_declared_sales_and_profit(self):
        result = investigator().compare(BASELINE, CURRENT)
        self.assertEqual(result["baseline"]["sales"], "400.0000")
        self.assertEqual(result["baseline"]["gross_profit"], "130.0000")
        self.assertEqual(result["current"]["sales"], "400.0000")
        self.assertEqual(result["current"]["gross_profit"], "124.0000")
        self.assertEqual(result["change"]["sales"], "0.0000")
        self.assertEqual(result["change"]["gross_profit"], "-6.0000")

    def test_offsetting_territories_reconcile_without_dividing_by_zero(self):
        result = investigator().breakdown(BASELINE, CURRENT, dimension="territory")
        self.assertEqual(
            [(row["id"], row["change"], row["contribution_share"]) for row in result["segments"]],
            [("10", "-30.0000", None), ("20", "30.0000", None)],
        )
        self.assertEqual(result["total_change"], "0.0000")
        self.assertTrue(result["reconciled"])

    def test_product_drilldown_retains_other_and_parent_scope(self):
        result = investigator().breakdown(
            BASELINE, CURRENT, dimension="product", filters={"territory": "10"}, top_k=1
        )
        self.assertEqual(result["segments"][0]["id"], "1")
        self.assertEqual(result["segments"][0]["change"], "-20.0000")
        self.assertEqual(result["other"]["change"], "-10.0000")
        self.assertEqual(result["total_change"], "-30.0000")
        self.assertEqual(result["other"]["group_count"], 1)

    def test_orders_count_distinct_orders_not_sales_lines(self):
        result = investigator().compare(BASELINE, CURRENT)
        self.assertEqual(result["baseline"]["line_count"], 4)
        self.assertEqual(result["baseline"]["orders"], 3)
        self.assertEqual(result["current"]["orders"], 3)

    def test_margin_is_ratio_of_totals_not_average_row_margin(self):
        result = investigator().compare(BASELINE, CURRENT)
        self.assertEqual(result["baseline"]["gross_margin"], "0.325000")
        self.assertEqual(result["current"]["gross_margin"], "0.310000")
        self.assertEqual(result["change"]["gross_margin_percentage_points"], "-1.500000")

    def test_empty_complete_period_is_explicit_not_an_invented_margin(self):
        result = investigator().compare(BASELINE, Period.parse("2024-03-01", "2024-04-01"))
        self.assertEqual(result["current"]["status"], "no_data")
        self.assertEqual(result["current"]["sales"], "0.0000")
        self.assertIsNone(result["current"]["gross_margin"])

    def test_zero_baseline_does_not_invent_a_growth_percentage(self):
        result = investigator(LINES[4:]).compare(BASELINE, CURRENT)
        self.assertEqual(result["change"]["sales"], "400.0000")
        self.assertIsNone(result["change"]["sales_relative"])
        self.assertEqual(result["change"]["sales_relative_status"], "nonpositive_baseline")

    def test_incomplete_period_is_rejected_before_analysis(self):
        with self.assertRaisesRegex(ValueError, "complete coverage"):
            investigator().compare(BASELINE, Period.parse("2024-03-01", "2024-04-02"))

    def test_period_end_is_exclusive(self):
        extra = ("2024-02-01", "O7", "1", "Alpha", "10", "North", "10", "1")
        result = investigator(LINES + [extra]).compare(BASELINE, CURRENT)
        self.assertEqual(result["baseline"]["sales"], "400.0000")
        self.assertEqual(result["current"]["sales"], "410.0000")

    def test_sales_growth_can_coexist_with_falling_profit(self):
        lines = list(LINES)
        lines[4] = (*LINES[4][:6], "120", "200")
        result = investigator(lines).compare(BASELINE, CURRENT)
        self.assertEqual(result["change"]["sales"], "40.0000")
        self.assertEqual(result["change"]["gross_profit"], "-110.0000")
        self.assertEqual(result["change"]["sales_relative"], "0.100000")

    def test_near_zero_change_keeps_exact_money_without_unstable_shares(self):
        extra = ("2024-02-21", "O7", "1", "Alpha", "20", "South", "0.0050", "0")
        result = investigator(LINES + [extra]).breakdown(BASELINE, CURRENT, dimension="territory")
        self.assertEqual(result["total_change"], "0.0050")
        self.assertEqual(result["contribution_share_status"], "near_zero_net_change")
        self.assertTrue(all(row["contribution_share"] is None for row in result["segments"]))

    def test_equal_display_names_do_not_merge_distinct_territories(self):
        lines = [(*line[:5], "North", *line[6:]) for line in LINES]
        result = investigator(lines).breakdown(BASELINE, CURRENT, dimension="territory")
        self.assertEqual([row["id"] for row in result["segments"]], ["10", "20"])
        self.assertEqual([row["change"] for row in result["segments"]], ["-30.0000", "30.0000"])


if __name__ == "__main__":
    unittest.main()
