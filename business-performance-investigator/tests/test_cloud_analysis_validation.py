"""Public evidence and command seams. All SQL/model boundaries are offline doubles."""

import copy
from decimal import Decimal
import json
from pathlib import Path
import sys
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent")]

from analysis import CsvSalesSource, Investigator, Limits, run_baseline
from analysis.adaptive import AdaptiveLimits, run_adaptive
from analysis.cloud_validation import ValidationFailure, parse_response, validate_run
from analysis.hosted import HostedPolicy, render_analysis_result
from analysis.model_client import ReplayClient
from test_business_analysis import BASELINE, CURRENT, COVERAGE
from test_hosted_analysis import security_record


CLIENT_ID = "11111111-2222-3333-4444-555555555555"
CONTEXT = {
    "server": "pilot.database.windows.net", "database": "pilot",
    "agent_principal_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "agent_client_id": CLIENT_ID, "private_ips": ["10.72.1.4"],
    "model": "DeepSeek-V4-Flash-0731",
}


def fixture(official=False):
    if official:
        policy = HostedPolicy.load(ROOT / "analysis" / "hosted-policy.json")
        path = ROOT / ".artifacts" / "adventureworks" / "internet_sales.csv"
    else:
        config = json.loads((ROOT / "evaluation" / "worked-example.json").read_text())
        policy = HostedPolicy("worked-example", config["csv_sha256"], 8, Decimal(800), Decimal(546),
                              "bpi_probe_agent", COVERAGE, BASELINE, CURRENT)
        path = ROOT / "evaluation" / "worked_sales.csv"
    source = CsvSalesSource.from_csv(path, dataset_id=policy.dataset_id, expected_sha256=policy.source_sha256)

    class SqlBoundary:
        mode, sha256, dataset_id = "azure_sql", None, policy.dataset_id
        snapshot_attestation = "Offline database double for the public hosted report contract."
        def read(self, plan):
            return source.read(plan)

    def engine():
        return Investigator(SqlBoundary(), policy.coverage, limits=Limits(max_seconds=120))

    steps = json.loads((ROOT / "evaluation" / "replays" /
                       ("northwest.json" if official else "synthetic-north.json")).read_text())["steps"]
    class ModelBoundary(ReplayClient):
        execution_kind = "inference"  # A doubled transport, not a real inference claim.

    fixed = run_baseline(engine(), policy.baseline, policy.current)
    adaptive = run_adaptive(engine(), policy.baseline, policy.current, "Investigate the changes.",
                            ModelBoundary(steps), CONTEXT["model"], limits=AdaptiveLimits(max_seconds=120, max_top_k=5))
    for report in (fixed, adaptive):
        permissions = {k: v for k, v in security_record().items()
                       if k.endswith(("_select", "_insert", "_update", "_delete", "_alter", "_table", "_view", "_control"))}
        report["security"] = {
            "status": "passed", "identity_mode": "managed_identity", "database_principal": "bpi_probe_agent",
            "server": CONTEXT["server"],
            "database_principal_sid": CLIENT_ID, "database_name": "pilot",
            "source_sha256": policy.source_sha256, "actual_row_count": policy.row_count,
            "permissions": permissions, "dns_candidates": ["10.72.1.4"], "all_candidates_private": True,
            "tls": {"hostname_verification": True, "full_session_encryption": True, "ca_source": "certifi"},
            "snapshot": "explicit SNAPSHOT transaction", "connection_closed": True,
        }
        report["approved_sample_policy"] = {"source_sha256": policy.source_sha256,
                                            "row_count": policy.row_count, "periods_are_model_controlled": False}
        report["sql_control_operations"] = {
            "snapshot_begin": 1, "identity_manifest_permission_query": 1, "rollback": 1,
            "note": "Additional control operations.",
        }
    return policy, source, fixed, adaptive


class EvidenceValidationTests(unittest.TestCase):
    def test_known_usage_is_checked_without_inventing_a_price(self):
        policy, source, baseline, report = fixture()
        calls = report["execution"]["model_calls"]
        report["execution"]["usage_by_call"] = [
            {"prompt_tokens": 100, "completion_tokens": 25, "total_tokens": 125} for _ in range(calls)
        ]
        report["execution"]["token_usage"] = {
            "status": "known", "prompt_tokens": 100 * calls,
            "completion_tokens": 25 * calls, "total_tokens": 125 * calls,
        }
        result = validate_run(report, mode="adaptive", source=source, policy=policy, context=CONTEXT)
        self.assertEqual(result["token_usage"]["total_tokens"], 500)
        self.assertEqual(result["model_cost"], "unknown")
        report["execution"]["usage_by_call"][0]["total_tokens"] = 126
        with self.assertRaises(ValidationFailure):
            validate_run(report, mode="adaptive", source=source, policy=policy, context=CONTEXT)

    def test_invalid_markers_and_ambiguous_json_are_rejected(self):
        for text in ('BPI_PROBE_RESULT={"ok":true}', 'BPI_ANALYSIS_RESULT={"a":1,"a":2}',
                     'BPI_ANALYSIS_RESULT={"a":NaN}', 'BPI_ANALYSIS_RESULT={"status":"ok"} trailing',
                     'BPI_ANALYSIS_RESULT={}\nBPI_ANALYSIS_RESULT={}'):
            with self.subTest(text=text), self.assertRaises(ValidationFailure):
                parse_response(text)
        text = render_analysis_result({"value": "BPI_ANALYSIS_RESULT=untrusted"})
        self.assertEqual(parse_response("\x1b[32m" + text + "\x1b[0m")["value"], "BPI_ANALYSIS_RESULT=untrusted")

    def test_rejects_identity_network_permissions_reference_and_accounting_drift(self):
        policy, source, baseline, adaptive = fixture()
        cases = [
            ("baseline", ("security", "database_principal_sid"), CONTEXT["agent_principal_id"]),
            ("baseline", ("security", "server"), "wrong.database.windows.net"),
            ("baseline", ("security", "dns_candidates"), ["10.72.1.99"]),
            ("baseline", ("security", "connection_closed"), False),
            ("baseline", ("security", "permissions", "base_select"), None),
            ("baseline", ("security", "permissions", "base_select"), True),
            ("baseline", ("security", "source_sha256"), "0" * 64),
            ("baseline", ("evidence", 0, "result", "sales"), "401.0000"),
            ("baseline", ("evidence", 0, "query_plan", "sql"), "SELECT * FROM dbo.secret"),
            ("baseline", ("execution", "data_requests"), 9),
            ("adaptive", ("execution", "client_kind"), "replay"),
            ("adaptive", ("execution", "model"), "different-model"),
            ("adaptive", ("execution", "model_inference_requests"), 0),
            ("adaptive", ("execution", "limits", "max_top_k"), 20),
            ("adaptive", ("status",), "exhausted"),
            ("adaptive", ("results", 0, "values", "baseline", "sales"), "401.0000"),
            ("adaptive", ("facts",), [adaptive["facts"][0], adaptive["facts"][0]]),
            ("adaptive", ("execution", "usage_by_call"), []),
        ]
        for mode, keys, value in cases:
            report = copy.deepcopy(baseline if mode == "baseline" else adaptive)
            target = report
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            with self.subTest(keys=keys), self.assertRaises(ValidationFailure):
                validate_run(report, mode=mode, source=source, policy=policy, context=CONTEXT)

    def test_validates_both_paths_against_pinned_reference_without_inference(self):
        policy, source, baseline, adaptive = fixture()
        for mode, report in (("baseline", baseline), ("adaptive", adaptive)):
            result = validate_run(parse_response(render_analysis_result(report)), mode=mode,
                                  source=source, policy=policy, context=CONTEXT)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["reference_checked_requests"], 10)
        self.assertEqual(baseline["comparison"]["baseline"]["sales"], "400.0000")


class ValidationCliTests(unittest.TestCase):
    def test_live_entrypoint_runs_bounded_pair_and_never_promotes_failed_evidence(self):
        for case in ("pass", "public-sql", "wrong-sid", "wrong-endpoint", "wrong-client",
                     "version-drift", "bad-baseline", "bad-adaptive", "state-drift", "public-ip",
                     "wrong-owner", "wrong-environment", "wrong-service", "wrong-initialization",
                     "existing-pass", "existing-model-drift"):
            with self.subTest(case=case):
                self.run_live_case(case)

    def run_live_case(self, case):
        policy, source, baseline, adaptive = fixture(official=True)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("common.ps1", "validate-analysis.ps1"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            shutil.copytree(ROOT / "analysis", root / "analysis", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "agent" / "probe_agent", root / "agent" / "probe_agent",
                            ignore=shutil.ignore_patterns("__pycache__"))
            config = json.loads((ROOT / ("config.existing-model.example.json" if case.startswith("existing-")
                                        else "config.example.json")).read_text())
            config.update(subscriptionId=CONTEXT["agent_principal_id"], operatorPrincipalId=CLIENT_ID,
                          modelName=CONTEXT["model"], modelApi="chat_completions")
            if case.startswith("existing-"):
                config["existingModelResourceId"] = config["existingModelResourceId"].replace(
                    "00000000-0000-0000-0000-000000000000", config["subscriptionId"])
            (root / "config.json").write_text(json.dumps(config))
            group = f"/subscriptions/{config['subscriptionId']}/resourceGroups/{config['resourceGroupName']}"
            server, endpoint, nic, subnet = (group + value for value in (
                "/providers/Microsoft.Sql/servers/pilot",
                "/providers/Microsoft.Network/privateEndpoints/sql",
                "/providers/Microsoft.Network/networkInterfaces/sql-nic",
                "/providers/Microsoft.Network/virtualNetworks/pilot/subnets/private-endpoints"))
            tags = {"bpiTemplate": "business-performance-investigator",
                    "bpiEnvironment": config["environmentName"], "bpiDeploymentId": "test-run"}
            env = {
                "AZURE_AI_PROJECT_ENDPOINT": "https://pilot.services.ai.azure.com/api/projects/pilot",
                "FOUNDRY_PROJECT_ENDPOINT": "https://pilot.services.ai.azure.com/api/projects/pilot",
                "AZURE_AI_PROJECT_ID": group + "/providers/Microsoft.CognitiveServices/accounts/pilot/projects/pilot",
                "AZURE_SQL_SERVER": CONTEXT["server"], "AZURE_SQL_DATABASE": "pilot",
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": CONTEXT["model"], "AZURE_AI_MODEL_API": "chat_completions",
                "AZURE_AI_MODEL_ENDPOINT": config.get("modelEndpoint", ""),
            }
            initialization = {
                "initialized": True, "mode": "AnalysisSnapshot", "databaseUser": "bpi_probe_agent",
                "agentClientId": CLIENT_ID, "agentPrincipalId": CONTEXT["agent_principal_id"],
                "normalizedSha256": policy.source_sha256, "rows": 33400,
                "datasetId": policy.dataset_id, "salesAmount": "14693465.3186",
                "totalProductCost": "8611268.3850", "snapshotIsolationState": 1,
            }
            state = {
                **{key: config[key] for key in ("environmentName", "subscriptionId", "resourceGroupName")},
                "configuration": config, "deploymentId": "test-run", "status": "initialized",
                "agentName": "business-investigator", "initializationMode": "AnalysisSnapshot",
                "agentClientId": CLIENT_ID, "agentPrincipalId": CONTEXT["agent_principal_id"],
                "initializerEvidence": initialization, "resourceIds": [server, endpoint, nic],
                "outputs": {key: {"value": value} for key, value in {
                    **{k: v for k, v in env.items() if k != "FOUNDRY_PROJECT_ENDPOINT"},
                    "sqlServerId": server, "sqlServerName": "pilot", "privateEndpointSubnetId": subnet,
                    "privateEndpointIds": [endpoint], "INITIALIZER_CLIENT_ID": "99999999-2222-3333-4444-555555555555",
                    "modelDeploymentId": group + "/providers/Microsoft.CognitiveServices/accounts/pilot/deployments/" + CONTEXT["model"],
                }.items()},
            }
            state_path = root / ".artifacts" / config["environmentName"] / "state.json"
            state_path.parent.mkdir(parents=True)
            if case == "wrong-service":
                state["agentName"] = "sql-probe"
            if case == "wrong-initialization":
                state["initializerEvidence"]["rows"] = 1
            state_path.write_text(json.dumps(state))
            if case == "wrong-sid":
                baseline["security"]["database_principal_sid"] = CONTEXT["agent_principal_id"]
            (root / "baseline.txt").write_text(
                "invalid evidence" if case == "bad-baseline" else render_analysis_result(baseline))
            (root / "adaptive.txt").write_text(
                "invalid evidence" if case == "bad-adaptive" else render_analysis_result(adaptive))
            responses = {
                "group show": {"id": group, "tags": tags},
                "resource list": [{"id": value} for value in state["resourceIds"]],
                "sql server": {"id": server, "fullyQualifiedDomainName": CONTEXT["server"],
                               "publicNetworkAccess": "Enabled" if case == "public-sql" else "Disabled"},
                "network private-endpoint": [{
                    "id": endpoint, "provisioningState": "Succeeded", "subnet": {"id": subnet},
                    "privateLinkServiceConnections": [{"privateLinkServiceId": server, "groupIds": ["sqlServer"],
                                                       "privateLinkServiceConnectionState": {"status": "Approved"}}],
                    "networkInterfaces": [{"id": nic}],
                }],
                "network nic": {"id": nic, "privateEndpoint": {"id": endpoint},
                                "ipConfigurations": [{"privateIPAddress": "10.72.1.99" if case == "wrong-endpoint" else "10.72.1.4",
                                                      "subnet": {"id": subnet}}]},
                "ad sp": {"id": CONTEXT["agent_principal_id"],
                          "appId": CONTEXT["agent_principal_id"] if case == "wrong-client" else CLIENT_ID},
                "env": env,
                "agent": {"name": "business-investigator", "version": "1", "status": "active",
                          "instance_identity": {"principal_id": CONTEXT["agent_principal_id"]}},
            }
            if case == "public-ip":
                responses["network nic"]["ipConfigurations"][0]["privateIPAddress"] = "8.8.8.8"
            if case == "wrong-owner":
                responses["group show"]["tags"]["bpiDeploymentId"] = "another-run"
            if case == "wrong-environment":
                responses["env"]["AZURE_SQL_SERVER"] = "another.database.windows.net"
            if case.startswith("existing-"):
                model_id = config["existingModelResourceId"]
                responses["existingDeployment"] = {
                    "id": model_id, "name": CONTEXT["model"],
                    "properties": {"provisioningState": "Succeeded", "capabilities": {"chatCompletion": "true"},
                                   "model": {"name": CONTEXT["model"], "version": "2026-07-31"}},
                }
                responses["existingAccount"] = {
                    "id": model_id.rsplit("/deployments/", 1)[0], "location": "eastus",
                    "properties": {"publicNetworkAccess": "Enabled", "networkAcls": {"defaultAction": "Allow"}},
                }
            else:
                responses["existingDeployment"] = {
                    "id": state["outputs"]["modelDeploymentId"]["value"], "name": CONTEXT["model"],
                    "properties": {"provisioningState": "Succeeded", "capabilities": {"chatCompletion": "true"},
                                   "model": {"name": CONTEXT["model"], "version": config["modelVersion"]}},
                }
            (root / "responses.json").write_text(json.dumps(responses))
            body = f"""
$ErrorActionPreference='Stop'
$global:fixture=Get-Content '{root / 'responses.json'}' -Raw | ConvertFrom-Json -AsHashtable
$global:shows=0
function global:az {{
  $global:LASTEXITCODE=0
  $key="$($args[0]) $($args[1])"
  if ($key -eq 'resource show') {{
    $id=$args[[Array]::IndexOf($args,'--ids')+1]
    $key=if ($id -match '/deployments/') {{ 'existingDeployment' }} else {{ 'existingAccount' }}
    if ('{case}' -eq 'existing-model-drift' -and $global:shows -gt 0 -and $key -eq 'existingDeployment') {{
      $global:fixture[$key].properties.model.version='changed'
    }}
  }}
  if (-not $global:fixture.ContainsKey($key)) {{ throw "Unexpected Azure operation: $key" }}
  $global:fixture[$key] | ConvertTo-Json -Depth 30 -Compress
}}
function global:azd {{
  $global:LASTEXITCODE=0
  if ($args[0] -eq 'env') {{ $global:fixture.env | ConvertTo-Json -Compress; return }}
  if ($args[0..2] -join ' ' -eq 'ai agent show') {{
    $global:shows++
    if ('{case}' -eq 'version-drift' -and $global:shows -gt 1) {{ $global:fixture.agent.version='2' }}
    $global:fixture.agent | ConvertTo-Json -Depth 5 -Compress
    return
  }}
  if ($args[0..2] -join ' ' -ne 'ai agent invoke') {{ throw 'Unexpected azd operation' }}
  if ($args[3] -cne 'business-investigator' -or $args -contains '--new-session' -or
      $args -notcontains '--session-id') {{ throw 'Unapproved agent/session invocation' }}
  $index=[Array]::IndexOf($args,'--new-conversation')
  $request=$args[$index+1] | ConvertFrom-Json
  Add-Content '{root / 'calls.txt'}' $request.mode
  if ('{case}' -eq 'state-drift') {{
    $s=Get-Content '{state_path}' -Raw | ConvertFrom-Json -AsHashtable
    $s.concurrent='preserve-me'
    $s | ConvertTo-Json -Depth 30 | Set-Content '{state_path}'
  }}
  Get-Content (Join-Path '{root}' "$($request.mode).txt")
}}
& '{scripts / 'validate-analysis.ps1'}' -ConfigPath '{root / 'config.json'}' `
  -SessionId approved-session -ApproveAzureChanges -ApproveModelInference `
  -PythonPath '{sys.executable}' -SourceCsv '{ROOT / '.artifacts' / 'adventureworks' / 'internet_sales.csv'}'
"""
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", body],
                                    capture_output=True, text=True, timeout=60)
            current = json.loads(state_path.read_text("utf-8-sig"))
            calls = (root / "calls.txt").read_text().splitlines() if (root / "calls.txt").exists() else []
            reports = list(state_path.parent.glob("cloud-analysis/*/report.json"))
            self.assertEqual(len(reports), 1, result.stderr)
            report = json.loads(reports[0].read_text("utf-8-sig"))
            if case in ("pass", "existing-pass"):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ["baseline", "adaptive"])
                self.assertEqual(current["status"], "validated")
                self.assertEqual(report["status"], "passed")
                self.assertEqual(report["scope"], "single-cloud-analysis-pair")
                self.assertFalse(report["real_model_quality_validated"])
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(current["status"], "initialized")
                self.assertEqual(report["status"], "failed")
                if case not in ("bad-adaptive", "state-drift"):
                    self.assertNotIn("adaptive", calls)
                if case == "state-drift":
                    self.assertEqual(current["concurrent"], "preserve-me")

    def test_cloud_entrypoint_requires_both_approvals_before_reading_config(self):
        script = ROOT / "scripts" / "validate-analysis.ps1"
        for extra in ([], ["-ApproveAzureChanges"]):
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), "-ConfigPath", "missing.json",
                                     "-SessionId", "approved-session", *extra],
                                    cwd=ROOT, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("execution is disabled" if not extra else "ApproveModelInference", result.stderr)
            self.assertNotIn("missing.json", result.stderr)

    def test_prepare_only_checks_real_reference_without_cloud_or_model(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "preparation.json"
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(ROOT / "scripts" / "validate-analysis.ps1"),
                                     "-PrepareOnly", "-PythonPath", sys.executable, "-OutputPath", str(output)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "prepared")
            self.assertEqual(report["cloud_calls_made"], 0)
            self.assertEqual(report["cloud_validation"], "not_run")

    def test_saved_cloud_transcripts_are_verified_locally_and_failure_is_persisted(self):
        policy, source, baseline, adaptive = fixture(official=True)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            context = directory / "context.json"
            context.write_text(json.dumps(CONTEXT))
            before, after, output = [directory / name for name in ("baseline.txt", "adaptive.txt", "result.json")]
            before.write_text(render_analysis_result(baseline))
            after.write_text(render_analysis_result(adaptive))
            command = [sys.executable, "-m", "analysis.cloud_validation", "--csv",
                       str(ROOT / ".artifacts" / "adventureworks" / "internet_sales.csv"),
                       "--context", str(context), "--baseline", str(before), "--adaptive", str(after),
                       "--output", str(output)]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["execution_kind"], "offline_evidence_validation")
            self.assertFalse(report["real_model_quality_validated"])
            self.assertEqual(report["runs"]["adaptive"]["reference_checked_requests"], 10)
            after.write_text('BPI_ANALYSIS_RESULT={"status":"failed"}')
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40)
            self.assertNotEqual(result.returncode, 0)
            failed = json.loads(output.read_text())
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["runs"]["baseline"]["status"], "passed")
            self.assertEqual(failed["runs"]["adaptive"]["receipt"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
