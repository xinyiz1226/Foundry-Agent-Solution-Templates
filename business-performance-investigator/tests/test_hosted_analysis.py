"""Public private-session/host contracts at the database and model boundaries."""

from decimal import Decimal
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from analysis.hosted import AnalysisAgent, HostedPolicy, PrivateAnalysisSession, SessionFailure
from analysis import CsvSalesSource
from probe_agent.config import Settings
from test_business_analysis import BASELINE, CURRENT, COVERAGE, COLUMNS, LINES


POLICY = HostedPolicy.load(ROOT / "analysis" / "hosted-policy.json")
SETTINGS = Settings(
    server="pilot.database.windows.net", database="pilot",
    project_endpoint="https://pilot.services.ai.azure.com/api/projects/pilot",
    model="DeepSeek-V4-Flash-0731", model_api="chat_completions",
)


def security_record():
    return {
        "database_principal": "bpi_probe_agent",
        "database_principal_sid": UUID("00000000-0000-0000-0000-000000000001"),
        "database_name": "pilot",
        "source_sha256": "45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f",
        "dataset_id": "adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd",
        "row_count": 33400, "actual_row_count": 33400,
        "sales_amount": Decimal("14693465.3186"), "total_product_cost": Decimal("8611268.3850"),
        "view_select": 1, "manifest_view_select": 1,
        "base_select": 0, "base_insert": 0, "base_update": 0, "base_delete": 0,
        "manifest_base_select": 0, "manifest_base_insert": 0, "manifest_base_update": 0, "manifest_base_delete": 0,
        "view_insert": 0, "view_update": 0, "view_delete": 0,
        "schema_alter": 0, "database_create_table": 0, "database_create_view": 0, "database_control": 0,
    }


class Cursor:
    def __init__(self, record):
        self.record = record
        self.description = [(key,) for key in record]
        self.commands = []
        self.closed = False

    def execute(self, sql, parameters=()):
        self.commands.append((sql, parameters))

    def fetchmany(self, limit):
        return [tuple(self.record.values())]

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, record):
        self.reader = Cursor(record)
        self.closed = False

    def cursor(self):
        return self.reader

    def close(self):
        self.closed = True


class PrivateSessionTests(unittest.TestCase):
    def test_policy_rejects_malformed_nested_fields_and_nonexact_money(self):
        original = json.loads((ROOT / "analysis" / "hosted-policy.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            for key, value in (("baseline", None), ("coverage", []), ("schema_version", True),
                               ("sales_amount", 1.5), ("total_product_cost", "NaN")):
                with self.subTest(key=key):
                    path.write_text(json.dumps({**original, key: value}))
                    with self.assertRaises(ValueError):
                        HostedPolicy.load(path)

    def test_private_snapshot_checks_identity_fixture_permissions_and_closes(self):
        connection = Connection(security_record())
        options = {}

        def connect(**kwargs):
            options.update(kwargs)
            return connection

        credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="fake-test-token"))
        with PrivateAnalysisSession(SETTINGS, credential, POLICY, connect=connect, resolver=lambda *args: ["10.72.1.4"]) as session:
            self.assertEqual(session.security["status"], "passed")
            self.assertEqual(session.security["actual_row_count"], 33400)
            self.assertEqual(session.security["server"], "pilot.database.windows.net")
            self.assertEqual(session.source.mode, "azure_sql")
        self.assertTrue(options["validate_host"])
        self.assertFalse(options["enc_login_only"])
        self.assertFalse(options["pooling"])
        self.assertFalse(options["as_dict"])
        self.assertEqual(options["access_token_callable"](), "fake-test-token")
        self.assertTrue(connection.closed and connection.reader.closed)
        self.assertIn("SNAPSHOT", connection.reader.commands[0][0])
        self.assertIn("ROLLBACK", connection.reader.commands[-1][0])

    def test_public_dns_is_rejected_before_connecting(self):
        def forbidden(**kwargs):
            self.fail("No connection is allowed after public DNS")
        with self.assertRaises(SessionFailure):
            with PrivateAnalysisSession(SETTINGS, object(), POLICY, connect=forbidden, resolver=lambda *args: ["8.8.8.8"]):
                pass

    def test_wrong_snapshot_or_unknown_permissions_fail_without_leaking_connection(self):
        for key, value in (("source_sha256", "0" * 64), ("actual_row_count", 33399), ("view_select", 0), ("base_select", 1), ("base_update", None)):
            with self.subTest(key=key):
                record = security_record()
                record[key] = value
                connection = Connection(record)
                with self.assertRaises(SessionFailure):
                    with PrivateAnalysisSession(SETTINGS, object(), POLICY, connect=lambda **kwargs: connection, resolver=lambda *args: ["10.72.1.4"]):
                        pass
                self.assertTrue(connection.closed and connection.reader.closed)


class HostAgentTests(unittest.TestCase):
    def test_adaptive_dispatch_matches_baseline_time_and_data_budgets(self):
        from unittest.mock import Mock
        source = CsvSalesSource.from_records([dict(zip(COLUMNS, row)) for row in LINES], dataset_id="test")
        class Session:
            security = {"status": "passed"}
            def __enter__(self):
                self.source = source
                return self
            def __exit__(self, *args):
                self.security["connection_closed"] = True
        runner = Mock(return_value={"status": "stopped"})
        agent = AnalysisAgent(SETTINGS, object(), object(), POLICY, session_factory=Session, adaptive_runner=runner)
        agent.answer("Investigate the largest decline.")
        call = runner.call_args
        self.assertEqual(call.args[0].limits.max_requests, 10)
        self.assertEqual(call.args[0].limits.max_seconds, 120)
        self.assertEqual(call.kwargs["limits"].max_seconds, 120)
        self.assertEqual(call.kwargs["limits"].max_top_k, 5)
        self.assertEqual(call.kwargs["limits"].max_tool_calls_per_response, 2)
        self.assertEqual(call.kwargs["limits"].max_filter_corrections, 1)

    def test_cleanup_failure_cannot_publish_successful_analytical_evidence(self):
        source = CsvSalesSource.from_records([dict(zip(COLUMNS, row)) for row in LINES], dataset_id="test")
        policy = HostedPolicy("test", "0" * 64, 8, Decimal(800), Decimal(546), "bpi_probe_agent", COVERAGE, BASELINE, CURRENT)
        class Session:
            def __enter__(self):
                self.source = source
                return self
            def __exit__(self, *args):
                raise SessionFailure("cleanup_failed", "Analytical SQL resources did not close cleanly.")
        agent = AnalysisAgent(SETTINGS, object(), object(), policy, session_factory=Session)
        result = json.loads(agent.answer('{"mode":"baseline","question":"Compare"}').split("BPI_ANALYSIS_RESULT=")[1])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "cleanup_failed")
        self.assertNotIn("comparison", result)

    def test_baseline_request_is_deterministic_and_calls_no_model(self):
        policy = HostedPolicy(
            "test", "0" * 64, 8, Decimal(800), Decimal(546), "bpi_probe_agent",
            COVERAGE, BASELINE, CURRENT,
        )
        source = CsvSalesSource.from_records([dict(zip(COLUMNS, row)) for row in LINES], dataset_id="test")

        class Session:
            security = {"status": "passed"}
            def __enter__(self):
                self.source = source
                return self
            def __exit__(self, *args):
                self.security["connection_closed"] = True

        def forbidden(*args, **kwargs):
            self.fail("A baseline request must not call the model")

        agent = AnalysisAgent(SETTINGS, object(), object(), policy, session_factory=lambda: Session(), adaptive_runner=forbidden)
        response = agent.answer('{"mode":"baseline","question":"Compare the approved periods."}')
        payload = json.loads(response.split("BPI_ANALYSIS_RESULT=", 1)[1])
        self.assertEqual(payload["comparison"]["baseline"]["sales"], "400.0000")
        self.assertEqual(payload["execution"]["model_requests"], 0)
        self.assertTrue(payload["security"]["connection_closed"])

    def test_model_cannot_supply_periods_sql_or_duplicate_request_keys(self):
        def forbidden():
            self.fail("Invalid requests must not open SQL")
        agent = AnalysisAgent(SETTINGS, object(), object(), POLICY, session_factory=forbidden)
        for question in ('{"mode":"baseline","sql":"SELECT *"}',
                         '{"mode":"baseline","mode":"adaptive","question":"test"}',
                         '{"mode":"baseline","question":"test","baseline":"1900"}'):
            with self.subTest(question=question):
                self.assertIn('"code":"invalid_input"', agent.answer(question))


class AnalysisProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_errors_use_analysis_marker_without_raw_details(self):
        import httpx
        from unittest.mock import Mock
        from main import create_app
        from analysis.hosted import analysis_error

        app = create_app(Mock(answer=Mock(side_effect=RuntimeError("fake-secret"))), error_renderer=analysis_error)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://offline") as client:
            response = await client.post("/responses", json={"input": "Compare", "stream": False, "store": False})
        text = response.json()["output"][0]["content"][0]["text"]
        self.assertEqual(json.loads(text.split("BPI_ANALYSIS_RESULT=")[1])["error"]["code"], "runtime_failed")
        self.assertNotIn("fake-secret", text)
        self.assertNotIn("BPI_PROBE_RESULT=", text)


if __name__ == "__main__":
    unittest.main()
