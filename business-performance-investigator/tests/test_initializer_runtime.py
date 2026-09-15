"""Private initializer completion must be proven, not inferred from ARM success."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
IMAGE = "mcr.microsoft.com/azure-powershell@sha256:82b5bb8daa75c8e974f5ff74a61a6add5e8ccd0d464a231a1a1e90ff0b713bd9"


@unittest.skipUnless(PWSH, "PowerShell 7 is required")
class InitializerTests(unittest.TestCase):
    def test_completion_evidence_and_ownership_fail_closed(self):
        client = "11111111-2222-3333-4444-555555555555"
        principal = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        evidence = dict(initialized=True, databaseUser="bpi_probe_agent",
                        agentClientId=client, agentPrincipalId=principal, expectedProbeAmount="42.00")
        for case in ["success", "failed", "missing-marker", "wrong-client", "duplicate-marker",
                     "wrong-owner", "wrong-identity", "wrong-subnet", "wrong-image", "timeout"]:
            with self.subTest(case=case):
                container = {
                    "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ContainerInstance/containerGroups/init",
                    "tags": {"bpiTemplate": "business-performance-investigator", "bpiEnvironment": "probe",
                             "bpiDeploymentId": "other" if case == "wrong-owner" else "run"},
                    "provisioningState": "Succeeded",
                    "identity": {"type": "UserAssigned", "userAssignedIdentities": {
                        "/wrong" if case == "wrong-identity" else "/owned/initializer": {}
                    }},
                    "subnetIds": [{"id": "/wrong" if case == "wrong-subnet" else "/owned/subnet"}],
                    "containers": [{"name": "sql-initializer", "image": "wrong" if case == "wrong-image" else IMAGE,
                                    "instanceView": {"currentState": {
                        "state": "Running" if case == "timeout" else "Terminated",
                        "exitCode": 1 if case == "failed" else 0,
                    }}}],
                }
                payload = {**evidence, **({"agentClientId": principal} if case == "wrong-client" else {})}
                marker = "BPI_INITIALIZER_RESULT=" + json.dumps(payload)
                logs = "no evidence" if case == "missing-marker" else marker
                if case == "duplicate-marker":
                    logs += "\n" + marker
                body = (
                    f". '{ROOT / 'scripts' / 'common.ps1'}';"
                    f". '{ROOT / 'scripts' / 'initializer-common.ps1'}';"
                    "$config=@{subscriptionId='sub';resourceGroupName='rg';environmentName='probe'};"
                    "$state=@{deploymentId='run';outputs=@{INITIALIZER_ID=@{value='/owned/initializer'};"
                    "initializerSubnetId=@{value='/owned/subnet'}}}; $global:stopped=$false;"
                    "function Invoke-BpiNative { param($Command,$Arguments,[switch]$Json);"
                    "switch ($Arguments[1]) {"
                    f"'show' {{ '{json.dumps(container)}' | ConvertFrom-Json -AsHashtable }}"
                    f"'logs' {{ '{logs}' }}"
                    "'stop' { $global:stopped=$true }"
                    "default { throw 'Unexpected command' } } };"
                    "$failed=$false;"
                    "try { Wait-BpiPrivateInitializer -Config $config -State $state -ContainerName init "
                    f"-AgentClientId '{client}' -AgentPrincipalId '{principal}' "
                    "-TimeoutSeconds 1 -PollIntervalSeconds 1 | Out-Null } catch { $failed=$true };"
                    f"if ($failed -ne ${str(case != 'success').lower()}) {{ throw 'Wrong completion verdict' }};"
                    f"if ($global:stopped -ne ${str(case == 'timeout').lower()}) {{ throw 'Wrong stop behavior' }}"
                )
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-NonInteractive", "-Command", body],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
