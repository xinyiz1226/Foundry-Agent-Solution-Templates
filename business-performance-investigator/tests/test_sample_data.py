"""Behavioral tests for the local sample-data preparation boundary."""

import importlib.util
import csv
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_sample_data", ROOT / "scripts" / "prepare_sample_data.py"
)
sample_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sample_data)


class SampleDataTests(unittest.TestCase):
    def setUp(self):
        self.work = ROOT / ".artifacts" / "adventureworks" / ("test-" + uuid.uuid4().hex)
        self.work.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.work)

    def fixture(self, *, change=None, extra=None, currency=False):
        """Tiny synthetic transport fixture, never represented as AdventureWorks data."""
        fact = [""] * 26
        for index, value in {
            0: "42", 1: "20131101", 7: "6", 8: "SO123", 9: "1", 11: "1",
            6: "100", 12: "12.3400", 13: "12.3400", 14: "0.0", 15: "0.0",
            16: "8.1234", 17: "8.1234", 18: "12.3400",
            23: "2013-11-01 00:00:00.000",
        }.items():
            fact[index] = value
        product = [""] * 36
        product[0], product[5] = "42", "Test product, small"
        date = ["20131101", "2013-11-01"] + [""] * 17
        territory = ["6", "99", "Test region", "", "", ""]
        tables = {
            "FactInternetSales": [fact], "DimDate": [date],
            "DimProduct": [product], "DimSalesTerritory": [territory],
        }
        if currency:
            tables["DimCurrency"] = [["100", "USD", "US Dollar"], ["6", "AUD", "Australian Dollar"]]
        if change:
            change(tables)
        manifest = {
            "source": {
                "archive_name": "fixture.zip", "url": "https://example.invalid/fixture.zip",
                "version": "synthetic-test-only", "max_download_bytes": 100000,
            },
            "members": {},
            "demonstration_periods": [],
        }
        archive = self.work / "fixture.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for table, rows in tables.items():
                content = ("\n".join("|".join(row) for row in rows) + "\n").encode()
                name = table + ".csv"
                z.writestr(name, content)
                manifest["members"][name] = {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content), "rows": len(rows),
                    "columns": len(rows[0]),
                }
            if extra:
                z.writestr(*extra)
        content = archive.read_bytes()
        manifest["source"].update(
            sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
        )
        path = self.work / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_currency_filter_is_verified_and_counts_exclusions(self):
        def change(tables):
            other = tables["FactInternetSales"][0][:]
            other[6], other[8] = "6", "SO124"
            tables["FactInternetSales"].append(other)
        path = self.fixture(change=change, currency=True)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["currency_filter"] = {"key": "100", "code": "USD", "name": "US Dollar"}
        path.write_text(json.dumps(manifest), encoding="utf-8")
        audit = sample_data.prepare_sample_data(path, self.work, offline=True)
        self.assertEqual(audit["output"]["rows"], 1)
        self.assertEqual(audit["scope_filter"]["input_fact_rows"], 2)
        self.assertEqual(audit["scope_filter"]["excluded_fact_rows"], 1)
        self.assertEqual(audit["scope_filter"]["sql_predicate"], "[fis].[CurrencyKey] = 100")
        self.assertEqual(audit["output_currency_key_row_counts"], {"100": 1})
        manifest["currency_filter"]["code"] = "AUD"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(sample_data.SampleDataError, "currency.*match"):
            sample_data.prepare_sample_data(path, self.work, offline=True)

    def test_proposed_sql_view_matches_manifest_projection_without_other_statements(self):
        manifest = json.loads((ROOT / "data" / "adventureworks-manifest.json").read_text(encoding="utf-8"))
        key = manifest["currency_filter"]["key"]
        expected = f"""
            CREATE OR ALTER VIEW [reporting].[v_internet_sales] AS SELECT
            CAST([dd].[FullDateAlternateKey] AS date) AS [order_date],
            [fis].[SalesOrderNumber] AS [sales_order_number],
            [fis].[ProductKey] AS [product_id],
            [dp].[EnglishProductName] AS [product_name],
            [fis].[SalesTerritoryKey] AS [territory_id],
            [dst].[SalesTerritoryRegion] AS [territory_name],
            CAST([fis].[SalesAmount] AS decimal(19,4)) AS [sales_amount],
            CAST([fis].[TotalProductCost] AS decimal(19,4)) AS [total_product_cost]
            FROM [dbo].[FactInternetSales] AS [fis]
            INNER JOIN [dbo].[DimDate] AS [dd] ON [dd].[DateKey] = [fis].[OrderDateKey]
            INNER JOIN [dbo].[DimProduct] AS [dp] ON [dp].[ProductKey] = [fis].[ProductKey]
            INNER JOIN [dbo].[DimSalesTerritory] AS [dst]
                ON [dst].[SalesTerritoryKey] = [fis].[SalesTerritoryKey]
            WHERE [fis].[CurrencyKey] = {key};
        """
        sql = (ROOT / "sql" / "analysis-view.sql").read_text(encoding="utf-8")
        sql = re.sub(r"--[^\r\n]*", "", sql)
        tokens = lambda text: re.findall(r"\[[^\]]+\]|[A-Za-z_][A-Za-z_0-9]*|\d+|[^\s]", text.lower())
        self.assertEqual(tokens(sql), tokens(expected))

    def test_proposed_sql_view_parses_to_the_expected_relational_projection(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell/ScriptDom unavailable; full static SQL contract still runs")
        command = r"""
$ErrorActionPreference = 'Stop'
$assembly = $env:SCRIPT_DOM_ASSEMBLY
if (-not $assembly) {
    $module = Get-Module -ListAvailable SqlServer | Sort-Object Version -Descending | Select-Object -First 1
    if ($module) {
        $assembly = Get-ChildItem $module.ModuleBase -Recurse -Filter Microsoft.SqlServer.TransactSql.ScriptDom.dll |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $assembly) {
    '{"available":false}' | Write-Output
    exit 0
}
Add-Type -Path $assembly
$parser = [Microsoft.SqlServer.TransactSql.ScriptDom.TSql160Parser]::new($true)
$errors = $null
$reader = [System.IO.StringReader]::new([System.IO.File]::ReadAllText($env:BPI_VIEW_SQL_PATH))
try { $tree = $parser.Parse($reader, [ref]$errors) } finally { $reader.Dispose() }
if ($errors.Count) { throw (($errors | ForEach-Object { $_.Message }) -join '; ') }
$statements = @($tree.Batches | ForEach-Object { $_.Statements })
if ($statements.Count -ne 1) { throw 'Expected exactly one proposed view statement' }
$view = $statements[0]
if ($view.GetType().Name -ne 'CreateOrAlterViewStatement') { throw 'Unexpected executable SQL statement' }
$query = $view.SelectStatement.QueryExpression
function ColumnName($expression) {
    if ($expression.GetType().Name -ne 'ColumnReferenceExpression') { throw 'Expected a column reference' }
    return (($expression.MultiPartIdentifier.Identifiers | ForEach-Object { $_.Value }) -join '.')
}
function Tables($reference) {
    if ($reference.GetType().Name -eq 'QualifiedJoin') {
        Tables $reference.FirstTableReference
        Tables $reference.SecondTableReference
    } elseif ($reference.GetType().Name -eq 'NamedTableReference') {
        @{ name = (($reference.SchemaObject.Identifiers | ForEach-Object { $_.Value }) -join '.'); alias = $reference.Alias.Value }
    } else { throw 'Unexpected table source' }
}
function Joins($reference) {
    if ($reference.GetType().Name -eq 'QualifiedJoin') {
        Joins $reference.FirstTableReference
        Joins $reference.SecondTableReference
        $condition = $reference.SearchCondition
        if ($condition.GetType().Name -ne 'BooleanComparisonExpression') { throw 'Unexpected join predicate' }
        @{ type = $reference.QualifiedJoinType.ToString(); comparison = $condition.ComparisonType.ToString()
           left = (ColumnName $condition.FirstExpression); right = (ColumnName $condition.SecondExpression) }
    }
}
$columns = @($query.SelectElements | ForEach-Object {
    $expression = $_.Expression
    $cast = $null
    $parameters = @()
    if ($expression.GetType().Name -eq 'CastCall') {
        $cast = $expression.DataType.SqlDataTypeOption.ToString().ToLowerInvariant()
        $parameters = @($expression.DataType.Parameters | ForEach-Object { $_.Value })
        $expression = $expression.Parameter
    }
    @{ alias = $_.ColumnName.Value; source = (ColumnName $expression); cast = $cast; parameters = $parameters }
})
$filter = $query.WhereClause.SearchCondition
if ($filter.GetType().Name -ne 'BooleanComparisonExpression' -or
    $filter.SecondExpression.GetType().Name -ne 'IntegerLiteral') { throw 'Unexpected scope predicate' }
@{
    available = $true
    view = (($view.SchemaObjectName.Identifiers | ForEach-Object { $_.Value }) -join '.')
    columns = $columns
    tables = @(Tables $query.FromClause.TableReferences[0])
    joins = @(Joins $query.FromClause.TableReferences[0])
    filter = @{ left = (ColumnName $filter.FirstExpression); comparison = $filter.ComparisonType.ToString(); value = $filter.SecondExpression.Value }
} | ConvertTo-Json -Depth 8 -Compress
"""
        environment = os.environ.copy()
        environment["BPI_VIEW_SQL_PATH"] = str(ROOT / "sql" / "analysis-view.sql")
        parsed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", command],
            env=environment, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        result = json.loads(parsed.stdout)
        if not result["available"]:
            self.skipTest("ScriptDom unavailable; set SCRIPT_DOM_ASSEMBLY to an installed DLL")
        manifest = json.loads((ROOT / "data" / "adventureworks-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(result["view"], "reporting.v_internet_sales")
        self.assertEqual(result["filter"], {
            "left": "fis.CurrencyKey", "comparison": "Equals", "value": manifest["currency_filter"]["key"],
        })
        self.assertEqual(result["tables"], [
            {"name": "dbo.FactInternetSales", "alias": "fis"},
            {"name": "dbo.DimDate", "alias": "dd"},
            {"name": "dbo.DimProduct", "alias": "dp"},
            {"name": "dbo.DimSalesTerritory", "alias": "dst"},
        ])
        self.assertEqual(result["joins"], [
            {"type": "Inner", "comparison": "Equals", "left": "dd.DateKey", "right": "fis.OrderDateKey"},
            {"type": "Inner", "comparison": "Equals", "left": "dp.ProductKey", "right": "fis.ProductKey"},
            {"type": "Inner", "comparison": "Equals", "left": "dst.SalesTerritoryKey", "right": "fis.SalesTerritoryKey"},
        ])
        self.assertEqual(result["columns"], [
            {"alias": alias, "source": source, "cast": cast, "parameters": parameters}
            for alias, source, cast, parameters in (
                ("order_date", "dd.FullDateAlternateKey", "date", []),
                ("sales_order_number", "fis.SalesOrderNumber", None, []),
                ("product_id", "fis.ProductKey", None, []),
                ("product_name", "dp.EnglishProductName", None, []),
                ("territory_id", "fis.SalesTerritoryKey", None, []),
                ("territory_name", "dst.SalesTerritoryRegion", None, []),
                ("sales_amount", "fis.SalesAmount", "decimal", ["19", "4"]),
                ("total_product_cost", "fis.TotalProductCost", "decimal", ["19", "4"]),
            )
        ])

    def test_offline_preparation_reports_missing_verified_archive(self):
        with self.assertRaisesRegex(sample_data.SampleDataError, "Offline.*archive"):
            sample_data.prepare_sample_data(
                ROOT / "data" / "adventureworks-manifest.json",
                ROOT / ".artifacts" / "adventureworks" / "missing-test-archive",
                offline=True,
            )

    def test_verified_archive_projects_exact_decimal_text_and_surrogate_keys(self):
        audit = sample_data.prepare_sample_data(self.fixture(), self.work, offline=True)
        with (self.work / "internet_sales.csv").open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, [
                "order_date", "sales_order_number", "product_id", "product_name",
                "territory_id", "territory_name", "sales_amount", "total_product_cost",
            ])
            self.assertEqual(list(reader), [{
                "order_date": "2013-11-01", "sales_order_number": "SO123",
                "product_id": "42", "product_name": "Test product, small",
                "territory_id": "6", "territory_name": "Test region",
                "sales_amount": "12.3400", "total_product_cost": "8.1234",
            }])
        self.assertEqual(audit["output"]["rows"], 1)
        self.assertEqual(audit["output"]["sales_amount"], "12.3400")
        self.assertFalse(audit["completeness"]["production_certified"])

    def test_untrusted_archives_fail_closed_before_output(self):
        for kind in ("hash", "size", "member_hash", "traversal", "duplicate", "symlink"):
            with self.subTest(kind=kind):
                path = self.fixture(extra=("../escape.csv", "secret") if kind == "traversal" else None)
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if kind == "hash":
                    manifest["source"]["sha256"] = "0" * 64
                elif kind == "size":
                    manifest["source"]["max_download_bytes"] = 1
                elif kind == "member_hash":
                    manifest["members"]["DimDate.csv"]["sha256"] = "0" * 64
                elif kind in ("duplicate", "symlink"):
                    with zipfile.ZipFile(self.work / "fixture.zip", "a") as archive:
                        if kind == "duplicate":
                            import warnings
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore", UserWarning)
                                archive.writestr("DimDate.csv", "duplicate")
                        else:
                            info = zipfile.ZipInfo("link.csv")
                            info.create_system = 3
                            info.external_attr = 0o120777 << 16
                            archive.writestr(info, "target")
                    content = (self.work / "fixture.zip").read_bytes()
                    manifest["source"].update(
                        sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
                    )
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(sample_data.SampleDataError):
                    sample_data.prepare_sample_data(path, self.work, offline=True)
                self.assertFalse((self.work / "internet_sales.csv").exists())

    def test_invalid_business_joins_and_conventions_are_rejected(self):
        cases = {
            "duplicate dimension": lambda t: t["DimProduct"].append(t["DimProduct"][0][:]),
            "missing product": lambda t: t["FactInternetSales"][0].__setitem__(0, "999"),
            "missing date": lambda t: t["FactInternetSales"][0].__setitem__(1, "20131102"),
            "missing territory": lambda t: t["FactInternetSales"][0].__setitem__(7, "999"),
            "duplicate line": lambda t: t["FactInternetSales"].append(t["FactInternetSales"][0][:]),
            "date mismatch": lambda t: t["DimDate"][0].__setitem__(1, "2013-11-02"),
            "non-midnight": lambda t: t["FactInternetSales"][0].__setitem__(23, "2013-11-01 12:00:00.000"),
            "invalid money": lambda t: t["FactInternetSales"][0].__setitem__(18, "NaN"),
            "rounded money": lambda t: t["FactInternetSales"][0].__setitem__(18, "12.34"),
            "blank name": lambda t: t["DimProduct"][0].__setitem__(5, ""),
            "wrong width": lambda t: t["FactInternetSales"][0].pop(),
        }
        for name, change in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(sample_data.SampleDataError):
                    sample_data.prepare_sample_data(self.fixture(change=change), self.work, offline=True)
                self.assertFalse((self.work / "internet_sales.csv").exists())

    def test_source_money_without_leading_zero_is_preserved(self):
        def change(tables):
            tables["FactInternetSales"][0][16:18] = [".8565", ".8565"]
        sample_data.prepare_sample_data(self.fixture(change=change), self.work, offline=True)
        with (self.work / "internet_sales.csv").open(encoding="utf-8", newline="") as stream:
            self.assertEqual(next(csv.DictReader(stream))["total_product_cost"], ".8565")

    def test_audit_records_exact_evidence_without_certifying_completeness(self):
        audit = sample_data.prepare_sample_data(self.fixture(), self.work, offline=True)
        self.assertEqual(audit["source_tables"]["FactInternetSales.csv"]["rows"], 1)
        self.assertEqual(audit["output"]["orders"], 1)
        self.assertEqual(audit["output"]["min_order_date"], "2013-11-01")
        self.assertEqual(audit["output"]["total_product_cost"], "8.1234")
        self.assertEqual(audit["months"]["2013-11"]["active_days"], 1)
        self.assertEqual(audit["months"]["2013-11"]["calendar_days"], 30)
        self.assertEqual(audit["months"]["2013-11"]["status"], "partial_boundary")
        self.assertEqual(audit["currency_key_row_counts"], {"100": 1})
        self.assertEqual(audit["validation"]["missing_dimension_keys"], 0)
        self.assertIn("data-owner", audit["completeness"]["limitations"])
        first = (self.work / "audit.json").read_bytes()
        sample_data.prepare_sample_data(self.work / "manifest.json", self.work, offline=True)
        self.assertEqual((self.work / "audit.json").read_bytes(), first)

    def test_online_download_is_verified_bounded_and_reused_offline(self):
        path = self.fixture()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        url = "https://github.com/microsoft/sql-server-samples/releases/download/adventureworks/fixture.zip"
        manifest["source"]["url"] = url
        path.write_text(json.dumps(manifest), encoding="utf-8")
        content = (self.work / "fixture.zip").read_bytes()
        (self.work / "fixture.zip").unlink()
        response = io.BytesIO(content)
        response.headers = {"Content-Length": str(len(content))}
        response.geturl = lambda: url
        with patch("urllib.request.urlopen", return_value=response):
            audit = sample_data.prepare_sample_data(path, self.work)
        self.assertEqual(audit["output"]["rows"], 1)
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline network")):
            sample_data.prepare_sample_data(path, self.work, offline=True)
        (self.work / "fixture.zip").unlink()
        response = io.BytesIO(content + b"untrusted")
        response.headers = {}
        response.geturl = lambda: url
        manifest["source"]["max_download_bytes"] = len(content)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(sample_data.SampleDataError, "limit"):
                sample_data.prepare_sample_data(path, self.work)
        self.assertFalse((self.work / "fixture.zip").exists())

    def test_manifest_count_and_date_expectations_fail_without_replacing_verified_output(self):
        path = self.fixture()
        sample_data.prepare_sample_data(path, self.work, offline=True)
        previous = (self.work / "internet_sales.csv").read_bytes()
        original = json.loads(path.read_text(encoding="utf-8"))
        for kind in ("count", "date", "boundary"):
            manifest = json.loads(json.dumps(original))
            if kind == "count":
                manifest["members"]["FactInternetSales.csv"]["rows"] = 2
            elif kind == "date":
                manifest["expected_output"] = {"min_order_date": "2012-01-01"}
            else:
                manifest["demonstration_periods"] = [{
                    "name": "not-interior", "start": "2013-11-01", "end": "2013-11-01",
                }]
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(kind=kind), self.assertRaises(sample_data.SampleDataError):
                sample_data.prepare_sample_data(path, self.work, offline=True)
            self.assertEqual((self.work / "internet_sales.csv").read_bytes(), previous)

    def test_cli_reports_paths_and_explicit_offline_failure(self):
        path = self.fixture()
        with redirect_stdout(io.StringIO()) as stdout:
            status = sample_data.main([
                "--manifest", str(path), "--artifacts-dir", str(self.work), "--offline",
            ])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())["output"]["rows"], 1)
        with redirect_stderr(io.StringIO()) as stderr:
            status = sample_data.main([
                "--manifest", str(path), "--artifacts-dir", str(self.work / "absent"), "--offline",
            ])
        self.assertEqual(status, 1)
        self.assertIn("Offline mode requires", stderr.getvalue())

    @unittest.skipUnless(
        (ROOT / ".artifacts" / "adventureworks" /
         "AdventureWorksDW-data-warehouse-install-script.zip").is_file(),
        "Official archive not yet downloaded; fixture tests never use network",
    )
    def test_cached_official_snapshot_matches_reviewed_baseline(self):
        archive = ROOT / ".artifacts" / "adventureworks" / "AdventureWorksDW-data-warehouse-install-script.zip"
        shutil.copyfile(archive, self.work / archive.name)
        audit = sample_data.prepare_sample_data(
            ROOT / "data" / "adventureworks-manifest.json", self.work, offline=True,
        )
        self.assertEqual(audit["output"]["rows"], 33400)
        self.assertEqual(audit["output"]["sha256"], "45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f")
        self.assertEqual(audit["output"]["total_product_cost"], "8611268.3850")
        self.assertEqual(audit["source_money_without_leading_zero"], 1768)
        self.assertEqual(audit["scope_filter"]["input_fact_rows"], 60398)
        self.assertEqual(audit["scope_filter"]["excluded_fact_rows"], 26998)
        self.assertEqual(audit["scope_filter"]["currency"], {"key": "100", "code": "USD", "name": "US Dollar"})
        self.assertEqual(audit["completeness"]["boundary_periods_observed"], ["2010-12", "2014-01"])
        self.assertEqual(
            [(p["name"], p["rows"], p["orders"], p["active_days"]) for p in audit["demonstration_periods"]],
            [("baseline", 2966, 1164, 30), ("comparison", 3091, 1203, 31)],
        )
        self.assertEqual(audit["baseline"], {"start": "2013-11-01", "end": "2013-12-01"})
        self.assertEqual(audit["current"], {"start": "2013-12-01", "end": "2014-01-01"})
        self.assertEqual(audit["coverage"]["start"], "2013-11-01")
        self.assertEqual(audit["coverage"]["end"], "2014-01-01")
        self.assertIn("sample snapshot assumption", audit["coverage"]["attestation"])
        self.assertIn("not a production", audit["coverage"]["attestation"])
        config = json.loads((self.work / "analysis-config.json").read_text(encoding="utf-8"))
        self.assertEqual(set(config), {
            "dataset_id", "csv_sha256", "coverage", "baseline", "current",
            "top_k", "limits", "view",
        })
        self.assertEqual(config["csv_sha256"], audit["output"]["sha256"])
        self.assertEqual(config["coverage"], audit["coverage"])
        self.assertEqual(config["limits"], {"max_requests": 10, "max_groups": 1000, "max_seconds": 30})
        self.assertEqual(config["view"], {"schema": "reporting", "name": "v_internet_sales"})
        self.assertEqual(audit["currency_key_row_counts"], {
            "6": 12988, "19": 7135, "29": 76, "39": 59, "98": 6740, "100": 33400,
        })
        self.assertFalse(audit["monetary_interpretation"]["base_currency_certified"])
        self.assertTrue(audit["monetary_interpretation"]["single_currency_subset_applied"])
        self.assertIn("single-CurrencyKey", audit["monetary_interpretation"]["production_gate"])


if __name__ == "__main__":
    unittest.main()
