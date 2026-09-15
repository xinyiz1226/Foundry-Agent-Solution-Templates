"""The actual cloud page with only external headers, credentials and HTTP replaced."""

from copy import deepcopy
import importlib.metadata
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.auth_fixtures import CLIENT, NOW, OPERATOR, TENANT, SignedIdentity
from tests.test_workbench_client import ROUND


PAGE = Path(__file__).resolve().parents[1] / "cloud_workbench.py"
try:
    for package in ("streamlit", "httpx", "PyJWT", "azure-identity", "cryptography"):
        importlib.metadata.version(package)
    AVAILABLE = True
except importlib.metadata.PackageNotFoundError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, "optional cloud-workbench dependencies unavailable")
class CloudWorkbenchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = SignedIdentity()

    def setUp(self):
        import httpx
        import streamlit as st
        from azure.core.credentials import AccessToken
        from azure.identity import ManagedIdentityCredential

        st.cache_resource.clear()
        self.now = NOW
        self.tokens = []
        self.commands = []
        self.http_requests = []
        self.projection = None
        self.pending = None
        self.gateway_status = 200
        self.expire_during_read = False
        owner = self

        class Headers:
            def get_all(self, name):
                if name.lower() != "x-ms-token-aad-id-token":
                    raise AssertionError("Unexpected identity-header contract")
                return list(owner.tokens)

        def handle_request(_, request):
            owner.http_requests.append(request)
            if request.url.host == "login.microsoftonline.com":
                return httpx.Response(200, json={"keys": [owner.identity.public_key]})
            if request.url.host != "fixture.services.ai.azure.com":
                raise AssertionError("Unapproved external request")
            command = json.loads(request.content)
            owner.commands.append(command)
            if command["action"] == "current":
                if owner.expire_during_read:
                    owner.now = NOW + 890
                result = {
                    "synthetic_only": True, "job_id": "synthetic-job",
                    "app_instance_id": "backend-1", "current": owner.projection,
                    "pending_request": owner.pending,
                }
                status = owner.gateway_status
            else:
                owner.projection = deepcopy(ROUND)
                owner.pending = None
                result = {
                    "synthetic_only": True,
                    "authorization": {"request_id": command["request_id"], "run_id": "run-1"},
                }
                status = 202
            return httpx.Response(
                status, json=result, headers={"x-agent-session-id": "gateway-session-1"},
            )

        for context in (
            patch.dict(os.environ, {
                "INFORMATION_EXTRACTION_PROJECT_ENDPOINT": "https://fixture.services.ai.azure.com/api/projects/test",
                "INFORMATION_EXTRACTION_AGENT_NAME": "synthetic-agent",
                "INFORMATION_EXTRACTION_WEB_TENANT_ID": TENANT,
                "INFORMATION_EXTRACTION_WEB_CLIENT_ID": CLIENT,
                "INFORMATION_EXTRACTION_WEB_OPERATOR_ID": OPERATOR,
                "INFORMATION_EXTRACTION_WEB_MAX_TOKEN_AGE": "900",
            }),
            patch.object(st, "context", SimpleNamespace(headers=Headers())),
            patch.object(httpx.HTTPTransport, "handle_request", handle_request),
            patch.object(ManagedIdentityCredential, "get_token", return_value=AccessToken("fixture-mi-token", NOW + 7200)),
            patch("information_extraction.workbench_cloud.time", SimpleNamespace(time=lambda: self.now)),
        ):
            context.start()
            self.addCleanup(context.stop)
        self.addCleanup(st.cache_resource.clear)

    def page(self):
        from streamlit.testing.v1 import AppTest

        page = AppTest.from_file(str(PAGE), default_timeout=15).run()
        self.assertEqual(len(page.exception), 0)
        return page

    def assert_protected_content_absent(self, page):
        self.assertEqual(len(page.table), 0)
        self.assertEqual(len(page.code), 0)
        self.assertEqual(len(page.selectbox), 0)
        self.assertFalse({"start", "resume", "retry"} & {b.key for b in page.button})
        self.assertTrue(page.error)

    def test_missing_identity_hides_sources_and_cannot_reach_the_gateway(self):
        page = self.page()
        self.assert_protected_content_absent(page)
        self.assertEqual(self.http_requests, [])

    def test_authorized_page_reads_and_recovers_without_spawning_sessions_or_work(self):
        self.tokens = [self.identity.token()]
        page = self.page()
        self.assertEqual(self.commands, [{"action": "current"}])
        page.button(key="start").click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual(page.table[0].value["Value"].tolist(), [120])
        reopened = self.page()
        self.assertEqual(reopened.table[0].value["Review"].tolist(), ["Pending"])
        self.assertEqual([c["action"] for c in self.commands].count("start"), 1)
        gateway = [r for r in self.http_requests if r.url.host == "fixture.services.ai.azure.com"]
        self.assertNotIn("agent_session_id", gateway[0].url.params)
        self.assertTrue(all(r.url.params["agent_session_id"] == "gateway-session-1" for r in gateway[1:]))
        self.assertTrue(all(r.headers["authorization"] == "Bearer fixture-mi-token" for r in gateway))
        self.assertTrue(all(self.tokens[0] not in r.content.decode() for r in gateway))

    def test_expired_open_page_cannot_submit_a_previously_visible_button(self):
        self.tokens = [self.identity.token()]
        page = self.page()
        self.now = NOW + 890
        page.button(key="start").click().run()
        self.assertEqual(len(page.exception), 0)
        self.assert_protected_content_absent(page)
        self.assertEqual(self.commands, [{"action": "current"}])
        self.assertTrue(any("expired" in e.value for e in page.error))

    def test_another_browser_cannot_reuse_the_cached_operators_identity(self):
        self.tokens = [self.identity.token()]
        self.projection = deepcopy(ROUND)
        self.page()
        self.tokens = [self.identity.token(oid=CLIENT)]
        page = self.page()
        self.assert_protected_content_absent(page)
        self.assertEqual(self.commands, [{"action": "current"}])

    def test_expiry_during_the_http_read_prevents_source_and_record_rendering(self):
        self.tokens = [self.identity.token()]
        self.projection = deepcopy(ROUND)
        self.expire_during_read = True
        page = self.page()
        self.assert_protected_content_absent(page)
        self.assertEqual(self.commands, [{"action": "current"}])

    def test_revoked_server_policy_blocks_a_previously_visible_command(self):
        self.tokens = [self.identity.token()]
        page = self.page()
        os.environ["INFORMATION_EXTRACTION_WEB_OPERATOR_ID"] = CLIENT
        page.button(key="start").click().run()
        self.assertEqual(len(page.exception), 0)
        self.assert_protected_content_absent(page)
        self.assertEqual(self.commands, [{"action": "current"}])

    def test_missing_configuration_never_falls_back_to_the_local_backend(self):
        self.tokens = [self.identity.token()]
        del os.environ["INFORMATION_EXTRACTION_WEB_CLIENT_ID"]
        page = self.page()
        self.assert_protected_content_absent(page)
        self.assertEqual(self.http_requests, [])

    def test_cloud_pending_retry_keeps_the_original_body_and_is_never_automatic(self):
        self.tokens = [self.identity.token()]
        self.pending = {
            "action": "resume", "run_id": "run-1", "request_id": "saved-request",
            "expected_revision": 1, "max_attempts": 1, "deadline": NOW - 1,
        }
        self.projection = deepcopy(ROUND)
        original = deepcopy(self.pending)
        page = self.page()
        self.assertEqual(self.commands, [{"action": "current"}])
        page.button(key="retry").click().run()
        self.assertEqual(len(page.exception), 0)
        self.assertEqual([c for c in self.commands if c["action"] != "current"], [original])

    def test_gateway_forbidden_is_visible_and_never_becomes_an_empty_job(self):
        self.tokens = [self.identity.token()]
        self.gateway_status = 403
        page = self.page()
        self.assert_protected_content_absent(page)
        self.assertEqual(self.commands, [{"action": "current"}])
