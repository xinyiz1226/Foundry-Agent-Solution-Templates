import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_business_analysis import BASELINE, CURRENT, COLUMNS, LINES, investigator
from analysis import Coverage, CsvSalesSource, Limits, Period, View, plan_query, run_baseline


class WorkflowTests(unittest.TestCase):
    def test_fixed_workflow_links_facts_to_reproducible_offline_evidence(self):
        report = run_baseline(investigator(), BASELINE, CURRENT, top_k=1)
        self.assertEqual(report["selected_territory"]["id"], "10")
        self.assertEqual(report["products"]["other"]["change"], "-10.0000")
        self.assertEqual(report["execution"]["data_requests"], 10)
        self.assertEqual(report["execution"]["sql_queries_executed"], 0)
        self.assertEqual(len(report["evidence"]), 10)
        evidence_ids = {item["id"] for item in report["evidence"]}
        for fact in report["facts"]:
            self.assertTrue(set(fact["evidence_ids"]) <= evidence_ids)
            self.assertTrue(fact["evidence_ids"])
        for evidence in report["evidence"]:
            self.assertEqual(evidence["execution_mode"], "offline_csv")
            self.assertFalse(evidence["sql_executed"])
            self.assertIn("%s", evidence["query_plan"]["sql"])
            self.assertEqual(len(evidence["source_sha256"]), 64)
        self.assertTrue(report["missing_evidence"])
        self.assertEqual(report["causal_conclusions"], [])

    def test_invalid_money_and_inconsistent_dimension_labels_are_rejected_at_load(self):
        records = [dict(zip(COLUMNS, line)) for line in LINES]
        for value in ("NaN", "Infinity", "1.00001", "", "1e100", 1.5):
            with self.subTest(value=value):
                bad = [dict(row) for row in records]
                bad[0]["sales_amount"] = value
                with self.assertRaises(ValueError):
                    CsvSalesSource.from_records(bad, dataset_id="invalid")
        records[1]["territory_name"] = "Different label for the same ID"
        with self.assertRaisesRegex(ValueError, "label"):
            CsvSalesSource.from_records(records, dataset_id="invalid")

    def test_official_sample_money_without_leading_zero_is_exact(self):
        line = (*LINES[0][:6], ".8565", ".1234")
        result = investigator([line]).compare(BASELINE, CURRENT)
        self.assertEqual(result["baseline"]["sales"], "0.8565")
        self.assertEqual(result["baseline"]["gross_profit"], "0.7331")

    def test_query_values_cannot_become_sql_and_identifiers_are_allowlisted(self):
        value = "10'; DROP TABLE dbo.sales;--"
        plan = plan_query(BASELINE, dimension="product", filters={"territory": value})
        self.assertNotIn(value, plan.sql)
        self.assertIn(value, plan.parameters)
        self.assertIn("COUNT(DISTINCT [sales_order_number])", plan.sql)
        with self.assertRaises(ValueError):
            plan_query(BASELINE, dimension="product];DELETE")
        with self.assertRaises(ValueError):
            plan_query(BASELINE, filters={"unknown": "1"})
        with self.assertRaises(ValueError):
            View(name="sales;DELETE")

    def test_request_and_group_budgets_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "budget"):
            run_baseline(investigator(limits=Limits(max_requests=9)), BASELINE, CURRENT)
        with self.assertRaisesRegex(ValueError, "group budget"):
            investigator(limits=Limits(max_groups=1)).breakdown(BASELINE, CURRENT, dimension="territory")

    def test_empty_report_does_not_claim_a_successful_investigation(self):
        report = run_baseline(investigator([]), BASELINE, CURRENT)
        self.assertEqual(report["status"], "insufficient_data")
        self.assertIsNone(report["selected_territory"])
        self.assertIsNone(report["products"])
        self.assertEqual(report["execution"]["data_requests"], 6)

    def test_completed_report_evidence_is_not_changed_by_later_requests(self):
        analysis = investigator(limits=Limits(max_requests=12))
        report = run_baseline(analysis, BASELINE, CURRENT)
        analysis.compare(BASELINE, CURRENT)
        self.assertEqual(len(report["evidence"]), 10)

    def test_overlapping_periods_and_invalid_top_k_are_rejected(self):
        for top_k in (0, 21, True, 1.5):
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                investigator().breakdown(BASELINE, CURRENT, dimension="territory", top_k=top_k)
        with self.assertRaises(ValueError):
            investigator().compare(BASELINE, Period.parse("2024-01-15", "2024-02-15"))

    def test_malformed_configuration_types_raise_actionable_validation_errors(self):
        operations = [
            lambda: Limits(max_seconds="30"),
            lambda: Limits(max_seconds=True),
            lambda: Period.parse(20240101, "2024-02-01"),
            lambda: Coverage("not-a-period", "attested"),
            lambda: View(schema=None),
            lambda: plan_query(BASELINE, max_groups=True),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()

    def test_cli_generates_report_and_rejects_changed_source_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sales.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(COLUMNS)
                writer.writerows(LINES)
            config = {
                "dataset_id": "worked-example",
                "csv_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "coverage": {
                    "start": "2024-01-01", "end": "2024-04-01",
                    "attestation": "Complete hand-authored synthetic ledger.",
                },
                "baseline": {"start": "2024-01-01", "end": "2024-02-01"},
                "current": {"start": "2024-02-01", "end": "2024-03-01"},
            }
            settings = root / "config.json"
            settings.write_text(json.dumps(config), encoding="utf-8")
            command = [
                sys.executable, "-m", "analysis", "--csv", str(source),
                "--config", str(settings), "--output", str(root / "report"),
            ]
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root / "report" / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["comparison"]["baseline"]["sales"], "400.0000")
            self.assertEqual(report["evidence"][0]["source_sha256"], config["csv_sha256"])
            markdown = (root / "report" / "report.md").read_text(encoding="utf-8")
            self.assertIn("not executed", markdown)
            self.assertIn("130.0000", markdown)
            source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            command[-1] = str(root / "bad-report")
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA-256", result.stderr)
            self.assertFalse((root / "bad-report").exists())

    def test_checked_in_example_reproduces_with_portable_lf_bytes(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sales.csv"
            source.write_bytes((project / "evaluation" / "worked_sales.csv").read_bytes().replace(b"\r\n", b"\n"))
            result = subprocess.run(
                [sys.executable, "-m", "analysis", "--csv", str(source),
                 "--config", str(project / "evaluation" / "worked-example.json"),
                 "--output", str(root / "report")],
                cwd=project, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
