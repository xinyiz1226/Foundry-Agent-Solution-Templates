import json
import unittest

from scripts.web_login_diagnostics import observe_response


HOST = "workbench.example.azurewebsites.net"
TENANT = "11111111-2222-3333-4444-555555555555"


class WebLoginDiagnosticsTests(unittest.TestCase):
    def observe(self, status, headers, accept="text/html"):
        return observe_response(status, headers, expected_host=HOST, tenant_id=TENANT, accept=accept)

    def test_failed_gate_keeps_status_and_safe_metadata(self):
        result = self.observe(401, {
            "Content-Type": "application/json; charset=utf-8",
            "X-MS-Request-ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "Set-Cookie": "private-cookie",
            "WWW-Authenticate": 'Bearer token="private-token"',
        })
        self.assertEqual(result["status_code"], 401)
        self.assertEqual(result["content_type"], "application/json")
        self.assertEqual(result["request_id"], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertFalse(result["login_redirect"])
        self.assertNotIn("private", json.dumps(result))

    def test_expected_relative_and_absolute_login_redirects(self):
        for target in (
            "/.auth/login/aad?state=private-state",
            f"https://{HOST}/.auth/login/aad?code=private-code",
            f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize?nonce=private-nonce",
        ):
            with self.subTest(target=target):
                result = self.observe(302, {"Location": target})
                self.assertTrue(result["login_redirect"])
                self.assertNotIn("private", json.dumps(result))
                self.assertNotIn("?", json.dumps(result))

    def test_other_tenant_scheme_port_provider_and_host_are_not_accepted(self):
        for target in (
            f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?state=private",
            f"http://{HOST}/.auth/login/aad",
            f"https://{HOST}:444/.auth/login/aad",
            f"https://{HOST}/.auth/login/github",
            f"https://user:password@{HOST}/.auth/login/aad",
            "https://unrelated.example/private-path?token=private",
            "//unrelated.example/.auth/login/aad",
            "https://[invalid",
        ):
            with self.subTest(target=target):
                result = self.observe(302, {"Location": target})
                self.assertFalse(result["login_redirect"])
                self.assertNotIn("private", json.dumps(result))
                self.assertNotIn("password", json.dumps(result))
                self.assertNotIn("unrelated.example", json.dumps(result))

    def test_status_does_not_become_success_just_because_location_is_valid(self):
        for status in (200, 401, 403, 404, 500, 503):
            with self.subTest(status=status):
                result = self.observe(status, {"Location": "/.auth/login/aad"})
                self.assertFalse(result["login_redirect"])
                self.assertEqual(result["status_code"], status)

    def test_untrusted_header_values_are_not_echoed(self):
        result = self.observe(403, {
            "Content-Type": "private-media/private-value",
            "X-MS-Request-ID": "private-token",
            "Location": "/private-path?state=private",
        }, accept="*/*")
        self.assertEqual(result["accept"], "*/*")
        self.assertEqual(result["content_type"], "other")
        self.assertIsNone(result["request_id"])
        self.assertNotIn("private", json.dumps(result))

    def test_invalid_operator_configuration_is_explicit(self):
        with self.assertRaises(ValueError):
            observe_response(302, {}, expected_host="https://host/path", tenant_id=TENANT, accept="text/html")
        with self.assertRaises(ValueError):
            observe_response(302, {}, expected_host=HOST, tenant_id="common", accept="text/html")
        with self.assertRaises(ValueError):
            self.observe(True, {})
