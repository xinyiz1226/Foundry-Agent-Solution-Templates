"""Optional real-sample oracle: SQLite is test-only, not a supported backend."""

import csv
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import run_baseline
from analysis.cli import load_investigation

SOURCE = ROOT / ".artifacts" / "adventureworks" / "internet_sales.csv"
CONFIG = SOURCE.with_name("analysis-config.json")


def units(value: str) -> int:
    return int(Decimal(value) * 10000)


@unittest.skipUnless(SOURCE.is_file() and CONFIG.is_file(), "Prepare the hash-verified official sample to run its independent SQL oracle.")
class AdventureWorksOracleTests(unittest.TestCase):
    def test_real_sample_metrics_and_drilldowns_match_independent_integer_sql(self):
        investigator, baseline, current, top_k = load_investigation(SOURCE, CONFIG)
        report = run_baseline(investigator, baseline, current, top_k=top_k)
        with closing(sqlite3.connect(":memory:")) as database:
            database.execute(
                "CREATE TABLE sales (order_date TEXT, order_number TEXT, product_id TEXT, product_name TEXT,"
                " territory_id TEXT, territory_name TEXT, sales_units INTEGER, cost_units INTEGER)"
            )
            with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
                database.executemany(
                    "INSERT INTO sales VALUES (?,?,?,?,?,?,?,?)",
                    (
                        (row["order_date"], row["sales_order_number"], row["product_id"], row["product_name"],
                         row["territory_id"], row["territory_name"], units(row["sales_amount"]), units(row["total_product_cost"]))
                        for row in csv.DictReader(stream)
                    ),
                )
            for label, period in (("baseline", baseline), ("current", current)):
                row = database.execute(
                    "SELECT COUNT(*),COALESCE(SUM(sales_units),0),COALESCE(SUM(cost_units),0),"
                    "COUNT(DISTINCT order_number) FROM sales WHERE order_date>=? AND order_date<?",
                    (period.start.isoformat(), period.end.isoformat()),
                ).fetchone()
                actual = report["comparison"][label]
                self.assertEqual(
                    (actual["line_count"], units(actual["sales"]), units(actual["total_product_cost"]), actual["orders"]),
                    row,
                )

            def expected_groups(dimension, territory=None):
                # Identifiers are fixed by this test, never inputs to the application.
                filter_sql = " AND territory_id=?" if territory is not None else ""
                rows = database.execute(
                    f"SELECT {dimension}_id,{dimension}_name,"
                    "SUM(CASE WHEN order_date<? THEN sales_units ELSE 0 END),"
                    "SUM(CASE WHEN order_date>=? THEN sales_units ELSE 0 END)"
                    f" FROM sales WHERE order_date>=? AND order_date<?{filter_sql}"
                    f" GROUP BY {dimension}_id,{dimension}_name",
                    (baseline.end.isoformat(), current.start.isoformat(), baseline.start.isoformat(), current.end.isoformat())
                    + ((territory,) if territory is not None else ()),
                ).fetchall()
                return sorted(rows, key=lambda row: (-abs(row[3] - row[2]), row[0]))

            territories = expected_groups("territory")
            self.assertEqual(report["selected_territory"]["id"], territories[0][0])
            for actual, expected in (
                (report["territories"], territories),
                (report["products"], expected_groups("product", territories[0][0])),
            ):
                self.assertEqual(
                    [(row["id"], row["name"], units(row["baseline_sales"]), units(row["current_sales"])) for row in actual["segments"]],
                    expected[:top_k],
                )
                remaining = expected[top_k:]
                self.assertEqual(units(actual["other"]["baseline_sales"]), sum(row[2] for row in remaining))
                self.assertEqual(units(actual["other"]["current_sales"]), sum(row[3] for row in remaining))
                self.assertEqual(units(actual["total_change"]), sum(row[3] - row[2] for row in expected))


if __name__ == "__main__":
    unittest.main()
