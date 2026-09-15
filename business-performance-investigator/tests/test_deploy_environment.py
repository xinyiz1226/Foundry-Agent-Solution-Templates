"""Exercise the agent-stage environment handoff without Azure calls."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 is required")
class DeployEnvironmentTests(unittest.TestCase):
    def test_agent_dependency_receives_canonical_project_endpoint(self):
        config = json.loads((ROOT / "config.example.json").read_text())
        config.update(
            subscriptionId="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            operatorPrincipalId="11111111-2222-3333-4444-555555555555",
        )
        endpoint = "https://probe.services.ai.azure.com/api/projects/pilot"
        outputs = {key: {"value": value} for key, value in {
            "AZURE_AI_PROJECT_ENDPOINT": endpoint,
            "AZURE_AI_PROJECT_NAME": "pilot",
            "AZURE_AI_ACCOUNT_NAME": "probe",
            "AZURE_AI_PROJECT_ID": "/owned/project",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": "model",
            "AZURE_AI_MODEL_API": "responses",
            "AZURE_AI_MODEL_ENDPOINT": "",
            "AZURE_SQL_SERVER": "probe.database.windows.net",
            "AZURE_SQL_DATABASE": "pilot",
        }.items()}
        state = {
            **{key: config[key] for key in ("environmentName", "subscriptionId", "resourceGroupName")},
            "configuration": config, "deploymentId": "fixture-run",
            "resourceIds": ["/owned/project"], "outputs": outputs, "status": "provisioned",
            "azdEnvironmentCreated": True,
        }
        group = {
            "id": f"/subscriptions/{config['subscriptionId']}/resourceGroups/{config['resourceGroupName']}",
            "tags": {"bpiTemplate": "business-performance-investigator",
                     "bpiEnvironment": config["environmentName"], "bpiDeploymentId": "fixture-run"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            for name in ("common.ps1", "initializer-common.ps1", "deploy.ps1"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            (scripts / "preflight.ps1").write_text("param($ConfigPath,[switch]$CheckAzure)\n")
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config))
            state_path = root / ".artifacts" / config["environmentName"] / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps(state))
            body = (
                "$ErrorActionPreference='Stop'; $global:values=@{}; $global:deploys=0;"
                "function az { $global:LASTEXITCODE=0;"
                f"if ($args[0] -eq 'group') {{ '{json.dumps(group)}' }}"
                "elseif ($args[0] -eq 'resource') { '[{\"id\":\"/owned/project\"}]' }"
                "elseif ($args[0] -eq 'account') { '{\"tenantId\":\"approved-tenant\"}' }"
                "else { throw 'Unexpected Azure action' } };"
                "function azd { $global:LASTEXITCODE=0;"
                "if (($args[0..1] -join ' ') -eq 'env set') { $global:values[$args[2]]=$args[3] }"
                "elseif ($args[0] -eq 'deploy') {"
                f"if ($global:values['FOUNDRY_PROJECT_ENDPOINT'] -ne '{endpoint}') "
                "{ throw 'Missing canonical project endpoint at dependency validation' };"
                "if ($global:values['FOUNDRY_PROJECT_ENDPOINT'] -ne $global:values['AZURE_AI_PROJECT_ENDPOINT']) "
                "{ throw 'Project endpoint aliases disagree' }; $global:deploys++ }"
                "else { throw 'Unexpected azd action' } };"
                f"& '{scripts / 'deploy.ps1'}' -ConfigPath '{config_path}' -Stage Agent -ApproveAzureChanges;"
                "if ($global:deploys -ne 1) { throw 'Agent was not deployed exactly once' }"
            )
            result = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-Command", body],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8-sig"))["status"], "agentDeployed")


if __name__ == "__main__":
    unittest.main()
