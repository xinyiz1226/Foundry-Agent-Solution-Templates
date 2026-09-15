"""Local lifecycle contracts: no Azure commands are permitted in these tests."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 is required for lifecycle contract tests")
class LifecycleTests(unittest.TestCase):
    def run_ps(self, body):
        result = subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-Command",
             f". '{ROOT / 'scripts' / 'common.ps1'}'; {body}"],
            capture_output=True, text=True, check=False,
        )
        return result

    def test_all_powershell_files_parse(self):
        root = str(ROOT / "scripts").replace("'", "''")
        result = self.run_ps(
            f"Get-ChildItem '{root}' -Filter *.ps1 -Recurse | ForEach-Object {{ "
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            "$_.FullName,[ref]$tokens,[ref]$errors) | Out-Null; "
            "if ($errors.Count) { throw ($errors.Message -join '; ') } }"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_example_config_cannot_deploy(self):
        result = self.run_ps(f"Read-BpiConfig '{ROOT / 'config.example.json'}'")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("placeholder", result.stderr)

    def test_available_extensions_are_not_mistaken_for_installed(self):
        for version, valid in [
            ("", False), ("1.0.0-beta.3", False), ("1.0.0-beta.15", True),
            ("invalid", False),
        ]:
            with self.subTest(version=version):
                result = self.run_ps(
                    "Assert-BpiExtensions @("
                    f"@{{id='azure.ai.agents';installedVersion='{version}'}},"
                    "@{id='azure.ai.projects';installedVersion='1.0.0-beta.10'})"
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_preflight_requires_installed_extensions(self):
        for installed in [False, True]:
            with self.subTest(installed=installed):
                extensions = [
                    {"id": name, "version": version,
                     "installedVersion": version if installed else ""}
                    for name, version in [
                        ("azure.ai.agents", "1.0.0-beta.15"),
                        ("azure.ai.projects", "1.0.0-beta.10"),
                    ]
                ]
                result = self.run_ps(
                    "function az { $global:LASTEXITCODE=0; '{}' };"
                    "function azd { $global:LASTEXITCODE=0;"
                    "if ($args[0] -eq 'extension') {"
                    f"'{json.dumps(extensions)}'"
                    "} else { 'azd mock version' } };"
                    f"& '{ROOT / 'scripts' / 'preflight.ps1'}'"
                )
                self.assertEqual(result.returncode == 0, installed, result.stderr)
                if not installed:
                    self.assertIn("catalog entry", result.stderr)

    def test_azure_execution_requires_explicit_approval(self):
        result = self.run_ps("Assert-BpiAzureApproval")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Azure execution is disabled", result.stderr)

    def test_cloud_preflight_checks_azd_tokens_not_cached_login_status(self):
        config = json.loads((ROOT / "config.example.json").read_text())
        config["subscriptionId"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        config["operatorPrincipalId"] = "11111111-2222-3333-4444-555555555555"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config))
            for authenticated in ["none", "scoped_only", "both"]:
                with self.subTest(authenticated=authenticated):
                    result = self.run_ps(
                        "$global:authScopes=@(); $global:scopedRequests=0;"
                        "function az { $global:LASTEXITCODE=0;"
                        "switch ($args[0]) {"
                        "'version' { '{}' }"
                        "'account' { '{\"state\":\"Enabled\",\"tenantId\":\"test-tenant\"}' }"
                        "'provider' { '{\"registrationState\":\"Registered\"}' }"
                        "'rest' { '{\"status\":\"Available\",\"supportedServerVersions\":["
                        "{\"name\":\"12.0\",\"status\":\"Available\",\"supportedEditions\":["
                        "{\"name\":\"Basic\",\"status\":\"Available\"}]}]}' }"
                        "default { throw 'Unexpected Azure command' } } };"
                        "function azd { $global:LASTEXITCODE=0;"
                        "switch ($args[0]) {"
                        "'version' { 'mock azd' }"
                        "'extension' { '[{\"id\":\"azure.ai.agents\",\"installedVersion\":\"1.0.0-beta.15\"},"
                        "{\"id\":\"azure.ai.projects\",\"installedVersion\":\"1.0.0-beta.10\"}]' }"
                        "'auth' {"
                        "if ($args[1] -ne 'token' -or "
                        "$args -notcontains '--no-prompt') { throw 'Wrong authentication check' };"
                        "if ($args -contains '--tenant-id') {"
                        "if ($args -notcontains 'test-tenant') { throw 'Wrong tenant' };"
                        "$global:scopedRequests++ };"
                        "$global:authScopes += $args[([array]::IndexOf($args,'--scope')+1)];"
                        f"if ('{authenticated}' -eq 'both' -or "
                        f"('{authenticated}' -eq 'scoped_only' -and $args -contains '--tenant-id')) {{"
                        "'{\"token\":\"fake-secret-do-not-print\",\"expiresOn\":\"2999-01-01T00:00:00Z\"}'"
                        "} else { $global:LASTEXITCODE=1; 'AADSTS530036 fake-secret-do-not-print' }"
                        + " } default { throw 'Unexpected azd command' } } };"
                        f"& '{ROOT / 'scripts' / 'preflight.ps1'}' -ConfigPath '{path}' -CheckAzure;"
                        "if ($global:authScopes.Count -ne 4 -or $global:scopedRequests -ne 2 -or "
                        "$global:authScopes -notcontains 'https://management.azure.com/.default' -or "
                        "$global:authScopes -notcontains 'https://ai.azure.com/.default') "
                        "{ throw 'Required azd scopes were not checked' }"
                    )
                    self.assertEqual(result.returncode == 0, authenticated == "both", result.stderr)
                    if authenticated != "both":
                        self.assertIn("AADSTS530036", result.stderr)
                    self.assertNotIn("fake-secret-do-not-print", result.stdout + result.stderr)

    def test_valid_config_and_capacity_bounds(self):
        config = json.loads((ROOT / "config.example.json").read_text())
        config["subscriptionId"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        config["operatorPrincipalId"] = "11111111-2222-3333-4444-555555555555"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for value, valid in [(1, True), (10, True), (0, False), (11, False),
                                 ("1", False), (1.5, False)]:
                with self.subTest(capacity=value):
                    config["modelCapacity"] = value
                    path.write_text(json.dumps(config))
                    result = self.run_ps(f"Read-BpiConfig '{path}' | Out-Null")
                    self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_existing_model_configuration_is_explicit_and_external(self):
        config = json.loads((ROOT / "config.existing-model.example.json").read_text())
        config["subscriptionId"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        config["operatorPrincipalId"] = "11111111-2222-3333-4444-555555555555"
        config["existingModelResourceId"] = config["existingModelResourceId"].replace(
            "00000000-0000-0000-0000-000000000000", config["subscriptionId"]
        )
        cases = [
            ({}, True),
            ({"modelEndpoint": "http://shared-model-account.openai.azure.com/openai/v1/"}, False),
            ({"modelEndpoint": "https://another-account.openai.azure.com/openai/v1/"}, False),
            ({"modelEndpoint": "https://shared-model-account.openai.azure.com.attacker.test/openai/v1/"}, False),
            ({"modelEndpoint": "https://shared-model-account.openai.azure.com/openai/v1/?token=fake-secret"}, False),
            ({"modelEndpoint": "https://shared-model-account.openai.azure.com:8443/openai/v1/"}, False),
            ({"modelCapacity": 1}, False),
            ({"modelApi": "automatic"}, False),
            ({"modelName": "different-deployment"}, False),
            ({"existingModelResourceId": config["existingModelResourceId"].replace(
                "rg-shared-models", config["resourceGroupName"])}, False),
            ({"existingModelResourceId": config["existingModelResourceId"].replace(
                config["subscriptionId"], "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee")}, False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for changes, valid in cases:
                with self.subTest(changes=changes):
                    path.write_text(json.dumps({**config, **changes}))
                    result = self.run_ps(f"Read-BpiConfig '{path}' | Out-Null")
                    self.assertEqual(result.returncode == 0, valid, result.stderr)
                    self.assertNotIn("fake-secret", result.stderr)
            path.write_text(json.dumps(config))
            result = self.run_ps(
                f"$model=Get-BpiModelConfiguration (Read-BpiConfig '{path}');"
                "if ($model.deployModel -or $model.sku -or $model.version) { throw 'would create a model' };"
                "if ($model.endpoint -notlike 'https://*/openai/v1/') { throw 'bad endpoint' }"
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_model_metadata_checks_are_read_only_and_fail_closed(self):
        config = json.loads((ROOT / "config.existing-model.example.json").read_text())
        config["subscriptionId"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        config["existingModelResourceId"] = config["existingModelResourceId"].replace(
            "00000000-0000-0000-0000-000000000000", config["subscriptionId"])
        deployment_id = config["existingModelResourceId"]
        deployment = {
            "id": deployment_id, "name": config["modelName"],
            "properties": {
                "provisioningState": "Succeeded", "capabilities": {"chatCompletion": "true"},
                "model": {"name": config["modelName"], "version": "2026-07-31"},
            },
        }
        account = {
            "id": deployment_id.rsplit("/deployments/", 1)[0], "location": "eastus",
            "properties": {"publicNetworkAccess": "Enabled", "networkAcls": {"defaultAction": "Allow"}},
        }
        for state, public, capability, valid in [
            ("Succeeded", "Enabled", "true", True),
            ("Failed", "Enabled", "true", False),
            ("Succeeded", "Disabled", "true", False),
            ("Succeeded", "Enabled", "false", False),
        ]:
            with self.subTest(state=state, public=public, capability=capability):
                deployment["properties"]["provisioningState"] = state
                deployment["properties"]["capabilities"]["chatCompletion"] = capability
                account["properties"]["publicNetworkAccess"] = public
                result = self.run_ps(
                    f"$config='{json.dumps(config)}' | ConvertFrom-Json -AsHashtable;"
                    f"$deployment='{json.dumps(deployment)}' | ConvertFrom-Json -AsHashtable;"
                    f"$account='{json.dumps(account)}' | ConvertFrom-Json -AsHashtable;"
                    "function Invoke-BpiNative { param($Command,$Arguments,[switch]$Json);"
                    "if ($Command -ne 'az' -or $Arguments[0] -ne 'resource' -or $Arguments[1] -ne 'show')"
                    "{ throw 'unexpected write or query' };"
                    "if ($Arguments[3] -eq $deployment.id) { return $deployment }; return $account };"
                    "Get-BpiExistingModel $config | Out-Null"
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_sql_visible_is_not_available(self):
        for region_status, edition_status, valid in [
            ("Available", "Available", True), ("Available", "Default", True),
            ("Visible", "Available", False), ("Available", "Visible", False),
        ]:
            with self.subTest(region=region_status, edition=edition_status):
                capabilities = {
                    "status": region_status,
                    "supportedServerVersions": [{
                        "name": "12.0", "status": "Available",
                        "supportedEditions": [{"name": "Basic", "status": edition_status}],
                    }],
                }
                result = self.run_ps(
                    f"Assert-BpiSqlAvailability ('{json.dumps(capabilities)}' | ConvertFrom-Json -AsHashtable)"
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_persisted_outputs_accept_azure_cli_key_casing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_ps(
                f"$script:ProjectRoot='{directory}';"
                "$config=@{environmentName='probe';subscriptionId='sub';resourceGroupName='rg'};"
                "$outputs='{\"azurE_AI_PROJECT_ENDPOINT\":{\"value\":\"https://probe.services.ai.azure.com/api/projects/pilot\"},"
                "\"initializeR_CLIENT_ID\":{\"value\":\"11111111-2222-3333-4444-555555555555\"}}'"
                " | ConvertFrom-Json -AsHashtable;"
                "$state=@{environmentName='probe';subscriptionId='sub';resourceGroupName='rg';"
                "configuration=$config;outputs=$outputs};"
                "Save-BpiState $config $state; $saved=Read-BpiState $config;"
                "if ((Get-BpiOutput $saved 'AZURE_AI_PROJECT_ENDPOINT') -cne "
                "'https://probe.services.ai.azure.com/api/projects/pilot') { throw 'Wrong endpoint' };"
                "if ((Get-BpiOutput $saved 'INITIALIZER_CLIENT_ID') -cne "
                "'11111111-2222-3333-4444-555555555555') { throw 'Wrong initializer' }"
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_output_lookup_rejects_case_ambiguous_json_keys(self):
        result = self.run_ps(
            "$state='{\"outputs\":{\"endpoint\":{\"value\":\"first\"},"
            "\"ENDPOINT\":{\"value\":\"second\"}}}' | ConvertFrom-Json -AsHashtable;"
            "Get-BpiOutput $state 'endpoint'"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr)

    def test_empty_output_requires_explicit_optional_contract(self):
        result = self.run_ps("Get-BpiOutput @{outputs=@{endpoint=@{value=''}}} 'endpoint'")
        self.assertNotEqual(result.returncode, 0)
        result = self.run_ps(
            "Get-BpiOutput @{outputs=@{endpoint=@{value=''}}} 'endpoint' -AllowEmpty"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_ps("Get-BpiOutput @{outputs=@{}} 'endpoint' -AllowEmpty")
        self.assertNotEqual(result.returncode, 0)

    def test_resource_ownership_and_extra_resources_fail_closed(self):
        result = self.run_ps(
            "$config=@{subscriptionId='s';resourceGroupName='rg-bpi-test';environmentName='test'};"
            "$state=@{deploymentId='mine';resourceIds=@('/known')};"
            "$group=@{id='/subscriptions/s/resourceGroups/rg-bpi-test';"
            "tags=@{bpiTemplate='business-performance-investigator';"
            "bpiEnvironment='test';bpiDeploymentId='someone-else'}};"
            "Assert-BpiOwnership $config $state $group"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ownership", result.stderr)
        result = self.run_ps(
            "Assert-BpiInventory @{resourceIds=@('/known')} @(@{id='/unexpected'})"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unrecorded resources", result.stderr)

    def test_native_failures_do_not_become_json_success(self):
        result = self.run_ps(
            "function fake { $global:LASTEXITCODE=7; '{\"ok\":true}' };"
            "Invoke-BpiNative fake @('show') -Json"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit code 7", result.stderr)

    def test_cleanup_requires_foundry_teardown_before_group_deletion(self):
        result = self.run_ps(
            "function Invoke-BpiNative { throw 'Unexpected Azure mutation or query' };"
            "Assert-BpiCleanupReady @(@{type='Microsoft.CognitiveServices/accounts';id='/owned/account'})"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ordered Foundry", result.stderr)
        self.assertIn("No resource-group deletion", result.stderr)
        self.assertNotIn("Unexpected Azure", result.stderr)

    def test_cleanup_waits_for_service_managed_subnet_links(self):
        for links, ready in [
            ([], True), (None, True),
            ([{"name": "legionservicelink", "allowDelete": False}], False),
        ]:
            with self.subTest(links=links):
                vnet = {"subnets": [{"serviceAssociationLinks": links}]}
                result = self.run_ps(
                    "function Invoke-BpiNative { param($Command,$Arguments,[switch]$Json);"
                    "if (($Arguments[0..2] -join ' ') -ne 'network vnet show') "
                    "{ throw 'Unexpected Azure mutation' };"
                    f"'{json.dumps(vnet)}' | ConvertFrom-Json -AsHashtable }};"
                    "Assert-BpiCleanupReady @(@{type='Microsoft.Network/virtualNetworks';id='/owned/vnet'})"
                )
                self.assertEqual(result.returncode == 0, ready, result.stderr)
                if not ready:
                    self.assertIn("service-managed subnet association", result.stderr)

    def test_native_auth_failure_reports_only_safe_error_code(self):
        result = self.run_ps(
            "function fake { $global:LASTEXITCODE=1; "
            "'AADSTS530036 secret-that-must-not-appear'; };"
            "Invoke-BpiNative fake @('auth','token') -Json"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("AADSTS530036", result.stderr)
        self.assertNotIn("secret-that-must-not-appear", result.stdout + result.stderr)

    def test_agent_identity_is_not_guessed(self):
        object_id = "11111111-2222-3333-4444-555555555555"
        result = self.run_ps(
            f"Get-BpiAgentPrincipalId @{{identity=@{{principalId='{object_id}'}}}}"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), object_id)
        for metadata in [
            "@{name='sql-probe'}",
            "@{identity=@{principalId='11111111-2222-3333-4444-555555555555'};"
            "agent_identity=@{principal_id='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'}}",
        ]:
            result = self.run_ps(f"Get-BpiAgentPrincipalId {metadata}")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unambiguous", result.stderr)

    def test_write_entrypoints_refuse_without_approval(self):
        for name, extra in [
            ("deploy.ps1", ["-Stage", "Provision"]),
            ("cleanup.ps1", ["-ConfirmResourceGroup", "rg-bpi-test"]),
            ("validate-agent.ps1", []),
        ]:
            with self.subTest(script=name):
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-NonInteractive", "-File",
                     str(ROOT / "scripts" / name), "-ConfigPath", "not-a-file.json", *extra],
                    capture_output=True, text=True, check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Azure execution is disabled", result.stderr)

    def test_missing_output_does_not_use_a_default(self):
        result = self.run_ps("Get-BpiOutput @{outputs=@{}} 'AZURE_SQL_SERVER'")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing", result.stderr)

    def test_configuration_cannot_change_after_provisioning(self):
        with tempfile.TemporaryDirectory() as directory:
            root = str(Path(directory)).replace("'", "''")
            result = self.run_ps(
                f"$script:ProjectRoot='{root}';"
                "$config=@{environmentName='test';subscriptionId='sub';"
                "resourceGroupName='rg-bpi-test';location='eastus2'};"
                "$state=@{environmentName='test';subscriptionId='sub';"
                "resourceGroupName='rg-bpi-test';configuration=$config.Clone()};"
                "Save-BpiState $config $state;"
                "$config.location='westus';Read-BpiState $config"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Configuration changed", result.stderr)

    def test_probe_requires_exactly_one_machine_evidence_marker(self):
        for text, valid in [
            ('A convincing answer with 42.00', False),
            ('BPI_PROBE_RESULT={"ok":true}', True),
            ('BPI_PROBE_RESULT={"ok":true}\nBPI_PROBE_RESULT={"ok":true}', False),
        ]:
            encoded = text.replace("'", "''")
            result = self.run_ps(f"ConvertFrom-BpiProbeEvidence '{encoded}' | Out-Null")
            self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_existing_probe_session_is_not_silently_replaced(self):
        for session in ["", "retained-session"]:
            with self.subTest(session=session):
                result = self.run_ps(
                    f"$arguments=@(Get-BpiProbeInvokeArguments -EnvironmentName probe -SessionId '{session}');"
                    "if ($arguments -notcontains '--new-conversation') { throw 'Conversation must be fresh' };"
                    + (
                        "if ($arguments -contains '--new-session' -or $arguments -notcontains '--session-id') "
                        "{ throw 'Retained session would be replaced' };"
                        "if ($arguments[([array]::IndexOf($arguments,'--session-id')+1)] -cne 'retained-session') "
                        "{ throw 'Wrong retained session' }"
                        if session else
                        "if ($arguments -notcontains '--new-session' -or $arguments -contains '--session-id') "
                        "{ throw 'Default session behavior changed' }"
                    )
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_evidence_format_matches_cli_validator(self):
        sys.path.insert(0, str(ROOT / "agent"))
        try:
            from probe_agent.orchestrator import render_evidence
        finally:
            sys.path.pop(0)
        text = render_evidence({"schema_version": 1, "ok": False})
        result = self.run_ps(
            f"$e=ConvertFrom-BpiProbeEvidence '{text.replace(chr(39), chr(39)*2)}';"
            "if ($e.schema_version -ne 1 -or $e.ok -cne $false) { throw 'Evidence changed' }"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_probe_evidence_checks_actual_identity_and_permissions(self):
        permissions = dict.fromkeys([
            "base_select", "base_insert", "base_update", "base_delete",
            "view_select", "view_insert", "view_update", "view_delete", "view_alter",
            "view_control", "schema_alter", "schema_control", "database_create_table",
            "database_create_view", "database_alter_any_schema", "database_control",
        ], 0)
        permissions["view_select"] = 1
        evidence = {
            "schema_version": 1, "ok": True, "server": "sample.database.windows.net",
            "database": "probe", "authenticated_database": "probe",
            "identity_mode": "managed_identity", "database_principal": "bpi_probe_agent",
            "database_principal_sid": "11111111-2222-3333-4444-555555555555",
            "principal_sid_status": "available",
            "fixture": {"probe_id": 1, "label": "private-sql-probe", "amount": "42.00"},
            "fixture_matches": True,
            "tls": {"hostname_verification": True, "full_session_encryption": True},
            "dns": {"all_candidates_private": True, "candidates": ["10.72.1.4"]},
            "permission_check": {"status": "passed"}, "permissions": permissions,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            for variation in ["valid", "unknown", "wrong_identity", "wrong_ip", "write"]:
                candidate = json.loads(json.dumps(evidence))
                if variation == "unknown":
                    candidate["permissions"]["base_select"] = None
                elif variation == "wrong_identity":
                    candidate["database_principal"] = "dbo"
                elif variation == "wrong_ip":
                    candidate["dns"]["candidates"] = ["10.73.1.4"]
                elif variation == "write":
                    candidate["permissions"]["view_update"] = 1
                path.write_text(json.dumps(candidate))
                result = self.run_ps(
                    f"$e=Get-Content '{path}' -Raw | ConvertFrom-Json -AsHashtable;"
                    "Assert-BpiProbeEvidence $e 'sample.database.windows.net' 'probe' "
                    "'11111111-2222-3333-4444-555555555555' @('10.72.1.4')"
                )
                self.assertEqual(result.returncode == 0, variation == "valid", result.stderr)


if __name__ == "__main__":
    unittest.main()
