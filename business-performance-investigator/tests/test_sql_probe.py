"""SQL tests never contact SQL, DNS, Azure or a credential endpoint."""

from decimal import Decimal
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

import certifi
import pytds
import pytds.tls
from OpenSSL import SSL, crypto
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from probe_agent.config import Settings
from probe_agent.sql_probe import PERMISSIONS, PROBE_SQL, SQL_SCOPE, SqlProbe, resolve_candidates, ProbeFailure


def settings():
    return Settings(
        server="pilot.database.windows.net",
        database="pilot",
        project_endpoint="https://pilot.services.ai.azure.com/api/projects/pilot",
        model="model",
    )


def fixture_row():
    return {
        "probe_id": 1, "label": "private-sql-probe", "amount": Decimal("42.00"),
        "database_principal": "bpi_probe_agent", "database_name": "pilot",
        "database_principal_sid": UUID("00000000-0000-0000-0000-000000000001"),
        **{key: int(key == "view_select") for key in PERMISSIONS},
    }


class SqlProbeTests(unittest.TestCase):
    def setUp(self):
        self.credential = Mock()
        self.credential.get_token.return_value.token = "not-a-real-token"
        self.connect = Mock()
        self.cursor = self.connect.return_value.cursor.return_value
        self.cursor.fetchmany.return_value = [fixture_row()]
        self.resolver = Mock(return_value=["10.1.2.3"])
        self.probe = SqlProbe(settings(), self.credential, connect=self.connect, resolver=self.resolver)

    def test_fixed_query_and_known_fixture(self):
        result = self.probe.run()
        self.assertTrue(result["ok"])
        self.assertTrue(result["fixture_matches"])
        self.assertEqual(result["fixture"]["amount"], "42.00")
        self.assertEqual(result["database_principal"], "bpi_probe_agent")
        self.assertEqual(result["database_principal_sid"], "00000000-0000-0000-0000-000000000001")
        self.assertEqual(result["principal_sid_status"], "available")
        self.assertEqual(result["permission_check"]["status"], "passed")
        self.cursor.execute.assert_called_once_with(PROBE_SQL)
        self.cursor.fetchmany.assert_called_once_with(2)
        self.cursor.close.assert_called_once()
        self.connect.return_value.close.assert_called_once()
        self.credential.get_token.assert_not_called()

    def test_real_driver_signature_and_secure_tls_options(self):
        options = self.probe.connection_options()
        inspect.signature(pytds.connect).bind(**options)
        self.assertEqual(options["dsn"], settings().server)
        self.assertEqual(options["cafile"], certifi.where())
        self.assertTrue(options["validate_host"])
        self.assertFalse(options["enc_login_only"])
        self.assertFalse(options["pooling"])
        self.assertTrue(options["disable_connect_retry"])
        self.assertEqual(options["timeout"], 15)
        self.assertEqual(options["login_timeout"], 15)
        self.assertNotIn("password", options)
        self.assertNotIn("user", options)
        self.assertTrue(pytds.tls.OPENSSL_AVAILABLE)
        context = pytds.tls.create_context(options["cafile"])
        self.assertEqual(context.get_verify_mode(), SSL.VERIFY_PEER)
        self.assertEqual(options["access_token_callable"](), "not-a-real-token")
        self.credential.get_token.assert_called_once_with(SQL_SCOPE)

    def test_fresh_connection_and_token_callback_each_probe(self):
        def connect(**kwargs):
            kwargs["access_token_callable"]()
            return Mock(cursor=Mock(return_value=self.cursor))
        self.connect.side_effect = connect
        self.assertTrue(self.probe.run()["ok"])
        self.assertTrue(self.probe.run()["ok"])
        self.assertEqual(self.connect.call_count, 2)
        self.assertEqual(self.credential.get_token.call_count, 2)

    def test_no_public_localhost_or_mixed_dns_fallback(self):
        for candidates in ([], ["127.0.0.1"], ["169.254.169.254"], ["8.8.8.8"], ["10.1.2.3", "8.8.8.8"]):
            with self.subTest(candidates=candidates):
                self.resolver.return_value = candidates
                result = self.probe.run()
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "private_dns_required")
                self.connect.assert_not_called()

    def test_wrong_fixture_rows_and_values_fail(self):
        for rows in ([], [fixture_row(), fixture_row()], [{**fixture_row(), "amount": Decimal("42.001")}], [{**fixture_row(), "probe_id": None}], [{**fixture_row(), "label": "wrong"}]):
            with self.subTest(rows=rows):
                self.cursor.fetchmany.return_value = rows
                result = self.probe.run()
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "fixture_mismatch")

    def test_unknown_permission_is_not_reported_denied(self):
        self.cursor.fetchmany.return_value = [{**fixture_row(), "base_select": None}]
        result = self.probe.run()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "permission_metadata_incomplete")
        self.assertIsNone(result["permissions"]["base_select"])
        self.assertEqual(result["permission_check"]["status"], "incomplete")
        self.assertEqual(result["permission_check"]["unknown"], ["base_select"])

    def test_only_integer_permission_flags_are_accepted(self):
        for value in (False, True, "0", "1", Decimal("0"), 2):
            with self.subTest(value=value):
                self.cursor.fetchmany.return_value = [{**fixture_row(), "base_select": value}]
                result = self.probe.run()
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "permission_metadata_invalid")

    def test_unavailable_sid_is_explicit_not_inferred_from_identity(self):
        self.cursor.fetchmany.return_value = [{**fixture_row(), "database_principal_sid": None}]
        result = self.probe.run()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["database_principal_sid"])
        self.assertEqual(result["principal_sid_status"], "unavailable")

    def test_invalid_sid_is_sanitized(self):
        self.cursor.fetchmany.return_value = [{**fixture_row(), "database_principal_sid": "fake-secret"}]
        result = self.probe.run()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "principal_sid_invalid")
        self.assertNotIn("fake-secret", json.dumps(result))

    def test_each_unexpected_permission_fails(self):
        for key in PERMISSIONS:
            if key == "view_select":
                continue
            with self.subTest(key=key):
                self.cursor.fetchmany.return_value = [{**fixture_row(), key: 1}]
                result = self.probe.run()
                self.assertFalse(result["ok"])
                self.assertEqual(result["permission_check"]["unexpected_grants"], [key])

    def test_missing_view_permission_or_wrong_database_fails(self):
        for change, code in (({"view_select": 0}, "permission_check_failed"), ({"database_name": "wrong"}, "database_mismatch")):
            self.cursor.fetchmany.return_value = [{**fixture_row(), **change}]
            self.assertEqual(self.probe.run()["error"]["code"], code)

    def test_wrong_authenticated_principal_fails_and_reports_actual_identity(self):
        self.cursor.fetchmany.return_value = [{**fixture_row(), "database_principal": "other_agent"}]
        result = self.probe.run()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "principal_mismatch")
        self.assertEqual(result["database_principal"], "other_agent")
        self.assertEqual(result["database_principal_sid"], "00000000-0000-0000-0000-000000000001")

    def test_cleanup_failure_overrides_success_without_exposing_exception(self):
        self.cursor.close.side_effect = RuntimeError("fake-secret")
        result = self.probe.run()
        self.assertFalse(result["ok"])
        self.assertTrue(result["cleanup_failed"])
        self.assertEqual(result["cleanup_failed_resources"], ["cursor"])
        self.assertEqual(result["error"]["code"], "cleanup_failed")
        self.connect.return_value.close.assert_called_once()
        self.assertNotIn("fake-secret", json.dumps(result))

    def test_cleanup_failure_preserves_sanitized_primary_error(self):
        self.cursor.execute.side_effect = TimeoutError("fake-secret")
        self.cursor.close.side_effect = RuntimeError("fake-secret")
        self.connect.return_value.close.side_effect = RuntimeError("fake-secret")
        result = self.probe.run()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "cleanup_failed")
        self.assertEqual(result["primary_error"]["code"], "query_timeout")
        self.assertEqual(result["cleanup_failed_resources"], ["cursor", "connection"])
        self.assertNotIn("fake-secret", json.dumps(result))

    def test_identity_failure_sanitized_no_fallback(self):
        self.credential.get_token.side_effect = RuntimeError("fake-secret")
        self.connect.side_effect = lambda **kwargs: kwargs["access_token_callable"]()
        result = self.probe.run()
        self.assertEqual(result["error"]["code"], "identity_failed")
        self.assertNotIn("fake-secret", json.dumps(result))
        self.credential.get_token.assert_called_once_with(SQL_SCOPE)

    def test_driver_failure_and_timeout_sanitized_resources_closed(self):
        for error, expected in ((RuntimeError("fake-secret"), "query_failed"), (TimeoutError("fake-secret"), "query_timeout")):
            self.cursor.execute.side_effect = error
            result = self.probe.run()
            self.assertEqual(result["error"]["code"], expected)
            self.assertNotIn("fake-secret", json.dumps(result))
            self.assertFalse(result["ok"])
        self.assertEqual(self.connect.return_value.close.call_count, 2)

    def test_connection_failure_sanitized(self):
        self.connect.side_effect = RuntimeError("not-a-real-token")
        result = self.probe.run()
        self.assertEqual(result["error"]["code"], "connect_failed")
        self.assertNotIn("not-a-real-token", json.dumps(result))
        self.cursor.execute.assert_not_called()

    def test_dns_results_and_failures_offline(self):
        with patch("probe_agent.sql_probe.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("10.1.2.3", 1433))]):
            self.assertEqual(resolve_candidates(settings().server, 1), ["10.1.2.3"])
        with patch("probe_agent.sql_probe.socket.getaddrinfo", side_effect=RuntimeError("fake-secret")):
            with self.assertRaises(ProbeFailure) as caught:
                resolve_candidates(settings().server, 1)
            self.assertEqual(caught.exception.code, "dns_failed")
            self.assertNotIn("fake-secret", str(caught.exception))


class DriverTLSContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pilot.database.windows.net")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(minutes=5))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("pilot.database.windows.net")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        cls.certificate = crypto.X509.from_cryptography(certificate)
        cls.server_certificate = certificate
        cls.key = key

    def test_driver_rejects_wrong_certificate_hostname(self):
        self.assertTrue(pytds.tls.validate_host(self.certificate, b"pilot.database.windows.net"))
        self.assertFalse(pytds.tls.validate_host(self.certificate, b"other.database.windows.net"))

    def test_driver_ca_context_rejects_untrusted_certificate_without_network(self):
        client = SSL.Connection(pytds.tls.create_context(certifi.where()))
        server_context = SSL.Context(SSL.TLS_SERVER_METHOD)
        server_context.use_certificate(self.server_certificate)
        server_context.use_privatekey(self.key)
        server = SSL.Connection(server_context)
        client.set_connect_state()
        server.set_accept_state()
        # Memory BIOs exercise the real TLS engine, not DNS or a network socket.
        with self.assertRaises(SSL.Error) as caught:
            for _ in range(20):
                for source, target in ((client, server), (server, client)):
                    try:
                        source.do_handshake()
                    except (SSL.WantReadError, SSL.WantWriteError):
                        pass
                    try:
                        target.bio_write(source.bio_read(65536))
                    except SSL.WantReadError:
                        pass
        self.assertIn("certificate verify failed", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
