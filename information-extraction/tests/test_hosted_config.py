import asyncio
from contextlib import ExitStack
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from information_extraction import ExecutionError, InvalidInput, SQLiteStore
from tests.test_hosted_app import INVOCATIONS_AVAILABLE


HOSTED_ENV = {
    "AGENTSERVER_TASKS_BACKEND": "hosted",
    "AZURE_TOKEN_CREDENTIALS": "prod",
    "FOUNDRY_HOSTING_ENVIRONMENT": "synthetic-config-fixture",
    "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/example",
    "EXTRACTION_BLOB_ACCOUNT_URL": "https://example.blob.core.windows.net",
    "EXTRACTION_BLOB_CONTAINER": "synthetic-fixture",
    "EXTRACTION_BLOB_PREFIX": "synthetic-probe",
    "EXTRACTION_JOB_ID": "synthetic-job",
    "AZURE_CLIENT_ID": "",
    "FOUNDRY_AGENT_NAME": "synthetic-config-test",
    "FOUNDRY_AGENT_VERSION": "1",
    "FOUNDRY_AGENT_SESSION_ID": "offline",
    "PORT": "8000",
    "SSE_KEEPALIVE_INTERVAL": "0",
    "WS_KEEPALIVE_INTERVAL": "0",
}

PRODUCTION_CREDENTIAL_EXCLUSIONS = {
    "exclude_cli_credential": True,
    "exclude_developer_cli_credential": True,
    "exclude_powershell_credential": True,
    "exclude_visual_studio_code_credential": True,
    "exclude_shared_token_cache_credential": True,
    "exclude_interactive_browser_credential": True,
    "exclude_broker_credential": True,
}


@unittest.skipUnless(INVOCATIONS_AVAILABLE, "optional Invocations SDK not installed")
class HostedConfigTests(unittest.TestCase):
    def setUp(self):
        from azure.ai.agentserver.core.tasks import resilient_tasks_enabled, set_resilient_tasks_enabled
        from azure.ai.agentserver.core.tasks._decorator import _REGISTERED_DESCRIPTORS
        enabled = resilient_tasks_enabled()
        descriptors = list(_REGISTERED_DESCRIPTORS)
        log_factory = logging.getLogRecordFactory()
        self.addCleanup(lambda: self.assertIs(logging.getLogRecordFactory(), log_factory))
        self.addCleanup(set_resilient_tasks_enabled, enabled)
        self.addCleanup(lambda: _REGISTERED_DESCRIPTORS.__setitem__(slice(None), descriptors))

    def test_production_requires_explicit_prod_credential_category_before_construction(self):
        from information_extraction.hosted_app import create_app
        for category in ("", "dev", "azureclicredential", "managedidentitycredential", "PROD", " prod "):
            with (
                self.subTest(category=category),
                patch.dict(os.environ, {**HOSTED_ENV, "AZURE_TOKEN_CREDENTIALS": category}),
                patch("azure.identity.DefaultAzureCredential") as credential,
                patch("azure.storage.blob.ContainerClient") as container,
            ):
                with self.assertRaisesRegex(InvalidInput, "^explicit_production_credentials_required$"):
                    create_app()
                credential.assert_not_called()
                container.assert_not_called()

    def test_production_requires_hosted_backend_and_complete_valid_blob_config(self):
        from information_extraction.hosted_app import create_app
        for key, value in (
            ("AGENTSERVER_TASKS_BACKEND", ""),
            ("AGENTSERVER_TASKS_BACKEND", "local"),
            ("FOUNDRY_HOSTING_ENVIRONMENT", ""),
            ("FOUNDRY_PROJECT_ENDPOINT", ""),
            ("EXTRACTION_BLOB_ACCOUNT_URL", ""),
            ("EXTRACTION_BLOB_ACCOUNT_URL", "https://example.blob.core.windows.net?sig=secret"),
            ("EXTRACTION_BLOB_CONTAINER", "Invalid/Container"),
            ("EXTRACTION_BLOB_PREFIX", "../other"),
            ("EXTRACTION_JOB_ID", ""),
            ("EXTRACTION_JOB_ID", "invalid/job"),
        ):
            with self.subTest(key=key), patch.dict(os.environ, {**HOSTED_ENV, key: value}):
                with self.assertRaises(InvalidInput):
                    create_app()

    def test_production_construction_has_no_token_or_blob_calls_and_closes_on_startup_failure(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import ContainerClient
        from information_extraction.hosted_app import create_app

        credential = Mock(spec=DefaultAzureCredential)
        container = Mock(spec=ContainerClient)
        with (
            patch.dict(os.environ, {
                **HOSTED_ENV, "FOUNDRY_AGENT_INSTANCE_CLIENT_ID": "must-not-be-used",
            }),
            patch("azure.identity.DefaultAzureCredential", return_value=credential) as make_credential,
            patch("azure.identity.ManagedIdentityCredential", side_effect=AssertionError("unverified_identity")),
            patch("azure.storage.blob.ContainerClient", return_value=container),
        ):
            app = create_app()
            make_credential.assert_called_once_with(**PRODUCTION_CREDENTIAL_EXCLUSIONS)
            credential.get_token.assert_not_called()
            container.get_blob_client.assert_not_called()
            container.list_blobs.assert_not_called()

            async def reject_changed_backend():
                with patch.dict(os.environ, {"AGENTSERVER_TASKS_BACKEND": "local"}):
                    with self.assertRaises(ExecutionError):
                        async with app.router.lifespan_context(app):
                            self.fail("production_must_not_fall_back_to_local")

            asyncio.run(reject_changed_backend())
        container.close.assert_called_once()
        credential.close.assert_called_once()

    def test_production_preserves_platform_identity_selection_and_cleans_up_constructor_failure(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import ContainerClient
        from information_extraction.hosted_app import create_app

        client_id = "00000000-0000-0000-0000-000000000001"
        credential = Mock(spec=DefaultAzureCredential)
        container = Mock(spec=ContainerClient)
        with (
            patch.dict(os.environ, {**HOSTED_ENV, "AZURE_CLIENT_ID": client_id, "PORT": "invalid-port"}),
            patch("azure.identity.DefaultAzureCredential", return_value=credential) as make_credential,
            patch("azure.identity.ManagedIdentityCredential", side_effect=AssertionError("unverified_identity")),
            patch("azure.storage.blob.ContainerClient", return_value=container),
        ):
            with self.assertRaisesRegex(ExecutionError, "^synthetic_app_construction_failed$"):
                create_app()
            self.assertEqual(os.environ["AZURE_CLIENT_ID"], client_id)
        make_credential.assert_called_once_with(**PRODUCTION_CREDENTIAL_EXCLUSIONS)
        credential.get_token.assert_not_called()
        container.get_blob_client.assert_not_called()
        container.close.assert_called_once()
        credential.close.assert_called_once()

    def test_real_sdk_never_admits_developer_credentials_even_when_environment_selects_them(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import ContainerClient
        from information_extraction.hosted_app import create_app

        developer_classes = (
            "AzureCliCredential", "AzureDeveloperCliCredential", "AzurePowerShellCredential",
            "VisualStudioCodeCredential", "SharedTokenCacheCredential",
            "InteractiveBrowserCredential", "BrokerCredential",
        )
        for selection in (
            "", "prod", "dev", "azureclicredential", "azuredeveloperclicredential",
            "azurepowershellcredential", "visualstudiocodecredential",
            "interactivebrowsercredential", "brokercredential",
        ):
            with self.subTest(selection=selection), ExitStack() as guards:
                guards.enter_context(patch.dict(os.environ, {
                    **HOSTED_ENV,
                    "PORT": "invalid-port",
                    "AZURE_TOKEN_CREDENTIALS": selection,
                    "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                    "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000002",
                    "AZURE_FEDERATED_TOKEN_FILE": str(Path(".test-data") / "unused-token-fixture"),
                }, clear=True))
                forbidden = [
                    guards.enter_context(patch(
                        f"{DefaultAzureCredential.__module__}.{name}",
                        side_effect=AssertionError("developer_credential_forbidden"),
                    ))
                    for name in developer_classes
                ]
                for target in (
                    "socket.socket.connect", "socket.socket.connect_ex", "socket.getaddrinfo",
                    "subprocess.Popen",
                ):
                    forbidden.append(guards.enter_context(patch(
                        target, side_effect=AssertionError("network_or_process_forbidden"),
                    )))
                for method in ("get_token", "get_token_info"):
                    forbidden.append(guards.enter_context(patch.object(
                        DefaultAzureCredential, method, side_effect=AssertionError("token_forbidden"),
                    )))

                created = []

                def credential_factory(**kwargs):
                    credential = DefaultAzureCredential(**kwargs)
                    created.append(credential)
                    guards.callback(credential.close)
                    return credential

                guards.enter_context(patch("azure.identity.DefaultAzureCredential", side_effect=credential_factory))
                container = Mock(spec=ContainerClient)
                make_container = guards.enter_context(patch(
                    "azure.storage.blob.ContainerClient", return_value=container,
                ))
                expected_error = (
                    "^synthetic_app_construction_failed$" if selection == "prod"
                    else "^explicit_production_credentials_required$"
                )
                with self.assertRaisesRegex(ExecutionError, expected_error):
                    create_app()
                if selection == "prod":
                    self.assertEqual(len(created), 1)
                    self.assertEqual(
                        {type(credential).__name__ for credential in created[0].credentials},
                        {"EnvironmentCredential", "WorkloadIdentityCredential", "ManagedIdentityCredential"},
                    )
                    make_container.assert_called_once()
                    container.close.assert_called_once()
                    container.get_blob_client.assert_not_called()
                else:
                    self.assertEqual(created, [])
                    make_container.assert_not_called()
                for dependency in forbidden:
                    dependency.assert_not_called()

    def test_explicit_offline_factory_closes_owned_resources_even_on_lifespan_error(self):
        from information_extraction.hosted_app import create_offline_app
        Path(".test-data").mkdir(exist_ok=True)
        with TemporaryDirectory(dir=".test-data") as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                **HOSTED_ENV,
                "AGENTSERVER_TASKS_BACKEND": "local",
                "FOUNDRY_HOSTING_ENVIRONMENT": "",
                "AGENTSERVER_STATE_ROOT": str(root / "tasks"),
                "AGENTSERVER_SHUTDOWN_GRACE_SECONDS": "1",
                "FOUNDRY_PROJECT_ENDPOINT": "",
            }):
                client, credential = Mock(), Mock()
                resources = ExitStack()
                resources.callback(credential.close)
                resources.callback(client.close)
                app = create_offline_app(SQLiteStore(root / "ledger.sqlite3"), close_resources=resources.close)

                async def fail():
                    with self.assertRaisesRegex(ExecutionError, "^synthetic_host_lifecycle_failed$"):
                        async with app.router.lifespan_context(app):
                            raise RuntimeError("secret_failure_detail")

                asyncio.run(fail())
                client.close.assert_called_once()
                credential.close.assert_called_once()
