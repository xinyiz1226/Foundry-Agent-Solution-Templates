"""Public PrepareOnly and Initialize seams; no Azure/SQL connections."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
CACHE = ROOT / ".artifacts" / "adventureworks"
CLIENT = "11111111-2222-3333-4444-555555555555"
PRINCIPAL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class AnalysisBootstrapTests(unittest.TestCase):
    def test_probe_validator_rejects_analysis_before_any_cloud_call(self):
        directory = ROOT / ".artifacts" / ("analysis-validation-" + uuid.uuid4().hex)
        scripts = directory / "scripts"
        scripts.mkdir(parents=True)
        try:
            for name in ("validate-agent.ps1", "common.ps1"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            config = json.loads((ROOT / "config.example.json").read_text())
            config.update(subscriptionId=PRINCIPAL, operatorPrincipalId=CLIENT)
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(config))
            state_path = directory / ".artifacts" / config["environmentName"] / "state.json"
            state_path.parent.mkdir(parents=True)
            for binding in ({"agentName": "business-investigator"}, {"initializationMode": "AnalysisSnapshot"}):
                state = dict(
                    **{k: config[k] for k in ("environmentName", "subscriptionId", "resourceGroupName")},
                    configuration=config, deploymentId="test-run", status="initialized", **binding,
                )
                state_path.write_text(json.dumps(state))
                body = (
                    "$ErrorActionPreference='Stop';"
                    "function az { throw 'Forbidden cloud call' };"
                    "function azd { throw 'Forbidden agent call' };"
                    f"& '{scripts / 'validate-agent.ps1'}' -ConfigPath '{config_path}' -ApproveAzureChanges"
                )
                result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", body],
                                        capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("probe-specific", result.stderr)
                self.assertNotIn("Forbidden", result.stderr)
                self.assertEqual(json.loads(state_path.read_text("utf-8-sig"))["status"], "initialized")
                self.assertFalse((state_path.parent / "cloud-probe.json").exists())
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_initialize_entrypoint_selects_opt_in_and_refuses_mode_drift(self):
        for case in ("first-analysis", "default-probe", "wrong-mode", "active-retry",
                     "wrong-evidence", "analysis-reuse", "state-mode-drift",
                     "missing-marker", "duplicate-marker", "wrong-snapshot", "wrong-client",
                     "successful-retry", "wrong-owner", "wrong-name", "failed-exit",
                     "analysis-wrong-service", "business-without-opt-in", "agent-first",
                     "agent-switch", "legacy-agent-switch", "invalid-agent-binding"):
            with self.subTest(case=case):
                self._initialize(case)

    def _initialize(self, case):
        directory = ROOT / ".artifacts" / ("analysis-entry-" + uuid.uuid4().hex)
        scripts = directory / "scripts"
        scripts.mkdir(parents=True)
        try:
            for name in ("deploy.ps1", "common.ps1", "initializer-common.ps1",
                         "analysis-initializer-common.ps1", "initialize-analysis.ps1"):
                source = ROOT / "scripts" / name
                if source.exists():
                    shutil.copyfile(source, scripts / name)
            (scripts / "preflight.ps1").write_text("param($ConfigPath,[switch]$CheckAzure)\n")
            config = json.loads((ROOT / "config.example.json").read_text())
            config.update(subscriptionId=PRINCIPAL, operatorPrincipalId=CLIENT)
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(config))
            prefix = f"/subscriptions/{PRINCIPAL}/resourceGroups/{config['resourceGroupName']}"
            initializer = prefix + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/bpi-test-initializer"
            subnet = prefix + "/providers/Microsoft.Network/virtualNetworks/bpi-test-vnet/subnets/initializer"
            container_id = prefix + "/providers/Microsoft.ContainerInstance/containerGroups/bpi-test-bootstrap-aci"
            existing = case not in ("first-analysis", "default-probe", "state-mode-drift",
                                   "agent-first", "agent-switch", "legacy-agent-switch",
                                   "analysis-wrong-service", "business-without-opt-in", "invalid-agent-binding")
            agent_stage = case in ("agent-first", "agent-switch", "invalid-agent-binding")
            requested_agent = "sql-probe" if case in ("default-probe", "analysis-wrong-service") else "business-investigator"
            tags = {"bpiTemplate": "business-performance-investigator", "bpiEnvironment": config["environmentName"],
                    "bpiDeploymentId": "test-run"}
            evidence = dict(initialized=True, databaseUser="bpi_probe_agent", agentClientId=CLIENT,
                            agentPrincipalId=PRINCIPAL, expectedProbeAmount="42.00", mode="AnalysisSnapshot",
                            normalizedSha256="45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f",
                            sourceArchiveSha256="73c27309d17cd30bf5351665401106abf649d9f9a9ecb0c770682f6be965aba8",
                            rows=33400, salesAmount="14693465.3186", totalProductCost="8611268.3850",
                            view="reporting.v_internet_sales", table="reporting.internet_sales_snapshot",
                            manifestView="reporting.v_analysis_manifest", manifestTable="reporting.analysis_snapshot_manifest",
                            datasetId="adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd",
                            snapshotIsolationState=1)
            if case == "wrong-evidence":
                evidence["rows"] = 1
            if case == "wrong-snapshot":
                evidence["snapshotIsolationState"] = True
            if case == "wrong-client":
                evidence["agentClientId"] = PRINCIPAL
            mode = "Probe" if case in ("default-probe", "wrong-mode") else "AnalysisSnapshot"
            container = dict(
                id=container_id, tags={**tags, "bpiInitializationMode": mode}, provisioningState="Succeeded",
                identity={"type": "UserAssigned", "userAssignedIdentities": {initializer: {}}},
                subnetIds=[{"id": subnet}],
                containers=[dict(name="sql-initializer",
                    image="mcr.microsoft.com/azure-powershell@sha256:82b5bb8daa75c8e974f5ff74a61a6add5e8ccd0d464a231a1a1e90ff0b713bd9",
                    environmentVariables=[{"name": k, "value": v} for k, v in {
                        "BPI_INITIALIZATION_MODE": mode, "BPI_OWNED_NEW_DATABASE": "true",
                        "AGENT_CLIENT_ID": CLIENT, "AGENT_PRINCIPAL_ID": PRINCIPAL,
                        "INITIALIZER_CLIENT_ID": "99999999-2222-3333-4444-555555555555",
                        "AZURE_SQL_DATABASE": "pilot", "AZURE_SQL_SERVER": "bpi-test-sql.database.windows.net",
                    }.items()],
                    instanceView={"currentState": {"state": "Running" if case == "active-retry" else "Terminated",
                                                   "exitCode": 1 if case == "failed-exit" else 0}})],
            )
            if case == "wrong-owner":
                container["tags"]["bpiDeploymentId"] = "another-run"
            if case == "wrong-name":
                container["id"] = container_id.replace("bpi-test-bootstrap-aci", "unplanned-bootstrap-aci")
            baseline = [dict(id=prefix + "/owned/project", name="pilot", type="fixture")]
            resources = baseline + [dict(id=container_id, name="bpi-test-bootstrap-aci",
                                         type="Microsoft.ContainerInstance/containerGroups")]
            state = dict(
                **{k: config[k] for k in ("environmentName", "subscriptionId", "resourceGroupName")},
                configuration=config, deploymentId="test-run", status="agentDeployed",
                agentName="sql-probe" if case in ("default-probe", "agent-switch") else "business-investigator",
                azdEnvironmentCreated=True,
                resourceIds=[r["id"] for r in (resources if existing else baseline)], outputs={k: {"value": v} for k, v in {
                    "INITIALIZER_ID": initializer, "initializerSubnetId": subnet,
                    "INITIALIZER_CLIENT_ID": "99999999-2222-3333-4444-555555555555",
                    "AZURE_SQL_DATABASE": "pilot", "AZURE_SQL_SERVER": "bpi-test-sql.database.windows.net",
                    "AZURE_AI_PROJECT_ENDPOINT": "https://bpi-test.services.ai.azure.com/api/projects/pilot",
                    "AZURE_AI_PROJECT_NAME": "pilot", "AZURE_AI_ACCOUNT_NAME": "bpi-test",
                    "AZURE_AI_PROJECT_ID": prefix + "/owned/project", "AZURE_AI_MODEL_DEPLOYMENT_NAME": "model",
                    "AZURE_AI_MODEL_API": "responses", "AZURE_AI_MODEL_ENDPOINT": "",
                }.items()},
            )
            if case == "agent-first":
                state.pop("agentName")
                state["status"] = "provisioned"
            if case == "legacy-agent-switch":
                state.pop("agentName")
            if case == "invalid-agent-binding":
                state["agentName"] = ""
            if case == "state-mode-drift":
                state["initializationMode"] = "Probe"
            state_path = directory / ".artifacts" / config["environmentName"] / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps(state))
            marker = ("BPI_INITIALIZER_RESULT=" if case == "default-probe" else
                      "BPI_ANALYSIS_INITIALIZER_RESULT=") + json.dumps(evidence)
            if case == "missing-marker":
                marker = "ARM succeeded but SQL has no evidence"
            if case == "duplicate-marker":
                marker += "\n" + marker
            body = (
                "$ErrorActionPreference='Stop';"
                f"$global:created=${str(existing).lower()}; $global:deploys=0;"
                "function az { $global:LASTEXITCODE=0; switch ($args[0]) {"
                f"'group' {{ '{json.dumps(dict(id=prefix, tags=tags))}' }}"
                f"'resource' {{ if ($global:created) {{ '{json.dumps(resources)}' }} else {{ '{json.dumps(baseline)}' }} }}"
                f"'ad' {{ '{json.dumps(dict(id=PRINCIPAL, appId=CLIENT))}' }}"
                """'account' { '{"tenantId":"test-tenant"}' }"""
                "'deployment' { $global:deploys++; $global:created=$true;"
                f"if ($args -notcontains 'infra-bicep/{'bootstrap' if case == 'default-probe' else 'analysis-bootstrap'}.bicep')"
                " { throw 'Wrong template selected' };"
                """'{"properties":{"outputs":{"bootstrapContainerGroupName":{"value":"bpi-test-bootstrap-aci"}}}}' }"""
                "'container' { switch ($args[1]) {"
                f"'show' {{ '{json.dumps(container)}' }} 'logs' {{ '{marker}' }}"
                "default { throw 'Unexpected container mutation' } } }"
                "default { throw 'Unexpected Azure command' } } };"
                "function azd { $global:LASTEXITCODE=0; switch ($args[0]) {"
                "'env' { if ($args[1] -ne 'set') { throw 'Unexpected environment operation' } }"
                f"'deploy' {{ if ($args[1] -cne '{requested_agent}') {{ throw 'Wrong agent deployed' }} }}"
                f"'ai' {{ if ($args[3] -cne '{requested_agent}') {{ throw 'Wrong agent inspected' }};"
                f"""'{{"identity":{{"principalId":"{PRINCIPAL}"}}}}' }}"""
                "default { throw 'Unexpected azd action' } } };"
                f"& '{scripts / 'deploy.ps1'}' -ConfigPath '{config_path}' -Stage {'Agent' if agent_stage else 'Initialize'} "
                f"-ApproveAzureChanges -AgentPrincipalId '{PRINCIPAL}' "
                + ("" if case == "default-probe" else f"-AgentName {requested_agent} ")
                + ("" if case in ("default-probe", "business-without-opt-in") or agent_stage else "-InitializationMode AnalysisSnapshot ")
                + ("-RetryInitialization " if case in ("active-retry", "successful-retry") else "")
            )
            result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", body],
                                    capture_output=True, text=True, timeout=30)
            success = case in ("first-analysis", "default-probe", "analysis-reuse", "agent-first")
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            after = json.loads(state_path.read_text("utf-8-sig"))
            if success:
                self.assertEqual(after["agentName"], requested_agent)
                self.assertEqual(after["status"], "agentDeployed" if agent_stage else "initialized")
                if not agent_stage:
                    self.assertIn(container_id, after["resourceIds"])
                if case != "default-probe" and not agent_stage:
                    self.assertEqual(after["initializationMode"], "AnalysisSnapshot")
                    self.assertEqual(after["initializerEvidence"]["normalizedSha256"], evidence["normalizedSha256"])
            else:
                self.assertNotEqual(after["status"], "initialized")
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_prepare_only_refuses_bad_cache_without_replacement(self):
        directory = ROOT / ".artifacts" / ("analysis-bad-cache-" + uuid.uuid4().hex)
        directory.mkdir(parents=True)
        archive = directory / "AdventureWorksDW-data-warehouse-install-script.zip"
        with archive.open("wb") as stream:
            stream.write(b"tampered-cache")
            stream.truncate(16765004)
        original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        try:
            body = (
                "$ErrorActionPreference='Stop';"
                "function Connect-AzAccount { throw 'Forbidden token request' };"
                "function Get-AzAccessToken { throw 'Forbidden token request' };"
                f"& '{ROOT / 'scripts' / 'initialize-analysis.ps1'}' -PrepareOnly -Offline "
                f"-CacheDirectory '{directory}' -OutputDirectory '{directory / 'out'}' "
                f"-AgentClientId {CLIENT} -AgentPrincipalId {PRINCIPAL}"
            )
            result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", body],
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cached archive hash/size mismatch", result.stderr)
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), original_hash)
            self.assertFalse((directory / "out").exists())
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_prepare_only_reproduces_real_cached_python_projection(self):
        archive = CACHE / "AdventureWorksDW-data-warehouse-install-script.zip"
        if not archive.exists():
            self.skipTest("Prepare the official sample cache first; tests never download")
        output = ROOT / ".artifacts" / ("analysis-test-" + uuid.uuid4().hex)
        try:
            result = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-Command",
                 f"Set-Location '{ROOT}'; & .\\scripts\\initialize-analysis.ps1 -PrepareOnly "
                 f"-Offline -CacheDirectory .artifacts\\adventureworks -OutputDirectory '{output}' "
                 f"-AgentClientId {CLIENT} -AgentPrincipalId {PRINCIPAL}"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            prepared = json.loads((output / "preparation.json").read_text("utf-8-sig"))
            content = (output / "internet_sales.csv").read_bytes()
            self.assertEqual(content, (CACHE / "internet_sales.csv").read_bytes())
            self.assertEqual(prepared["normalizedSha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(prepared["rows"], 33400)
            self.assertEqual(prepared["salesAmount"], "14693465.3186")
            self.assertEqual(prepared["totalProductCost"], "8611268.3850")
            self.assertFalse(prepared["initialized"])
            self.assertEqual(prepared["mode"], "AnalysisSnapshot")
            self.assertEqual(prepared["agentClientId"], CLIENT)
            self.assertIn("reporting.internet_sales_snapshot", (output / "create.sql").read_text())
            self.assertIn("reporting.v_internet_sales", (output / "finalize.sql").read_text())
            self.assertIn("reporting.analysis_snapshot_manifest", (output / "create.sql").read_text())
            self.assertIn("reporting.v_analysis_manifest", (output / "finalize.sql").read_text())
            self.assertIn("source_sha256, dataset_id, row_count", (output / "finalize.sql").read_text())
            self.assertEqual(prepared["manifestView"], "reporting.v_analysis_manifest")
            self.assertEqual(prepared["manifestTable"], "reporting.analysis_snapshot_manifest")
            if os.environ.get("SCRIPT_DOM_ASSEMBLY"):
                parser = (
                    "$ErrorActionPreference='Stop'; Add-Type -Path $env:SCRIPT_DOM_ASSEMBLY;"
                    "$parser=[Microsoft.SqlServer.TransactSql.ScriptDom.TSql160Parser]::new($true);"
                    f"Get-ChildItem '{output}' -Filter *.sql | ForEach-Object {{"
                    "$errors=$null; $reader=[IO.StringReader]::new([IO.File]::ReadAllText($_.FullName));"
                    "try { $tree=$parser.Parse($reader,[ref]$errors) } finally { $reader.Dispose() };"
                    "if ($errors.Count) { throw ($errors.Message -join '; ') };"
                    "foreach ($batch in $tree.Batches) { foreach ($statement in $batch.Statements) {"
                    "if ($statement -is [Microsoft.SqlServer.TransactSql.ScriptDom.ExecuteStatement]) {"
                    "foreach ($text in $statement.ExecuteSpecification.ExecutableEntity.Strings) {"
                    "$nested=[IO.StringReader]::new($text.Value);"
                    "try { $null=$parser.Parse($nested,[ref]$errors) } finally { $nested.Dispose() };"
                    "if ($errors.Count) { throw ($errors.Message -join '; ') } } } } } }"
                )
                parsed = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", parser],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(parsed.returncode, 0, parsed.stderr)
        finally:
            shutil.rmtree(output, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
