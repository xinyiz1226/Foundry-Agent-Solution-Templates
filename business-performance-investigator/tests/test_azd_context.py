"""Offline tests for explicitly selecting an isolated, same-user azd profile."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@unittest.skipUnless(PWSH, "PowerShell 7 is required")
class AzdContextTests(unittest.TestCase):
    def test_context_selection_is_explicit_scoped_and_restored_on_failure(self):
        config = json.loads((ROOT / "config.example.json").read_text())
        config.update(
            subscriptionId="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            operatorPrincipalId="11111111-2222-3333-4444-555555555555",
        )
        for failure in ["", "subscription", "operator", "tenant", "disabled", "profile"]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps(config))
                account = {
                    "id": config["subscriptionId"] if failure != "subscription" else "wrong",
                    "tenantId": "22222222-2222-3333-4444-555555555555" if failure != "tenant" else "",
                    "state": "Disabled" if failure == "disabled" else "Enabled",
                    "user": {"type": "user"},
                }
                operator = config["operatorPrincipalId"] if failure != "operator" else "wrong"
                body = (
                    "$ErrorActionPreference='Stop';"
                    "$env:AZD_CONFIG_DIR='original-profile';"
                    "$env:AZURE_SUBSCRIPTION_ID='original-subscription';"
                    "$env:AZURE_TENANT_ID='original-tenant';"
                    "$global:profileWrites=0;"
                    "function az { $global:LASTEXITCODE=0;"
                    f"if ($args[0] -eq 'account') {{ '{json.dumps(account)}' }}"
                    f"elseif (($args[0..2] -join ' ') -eq 'ad signed-in-user show') {{ '{{\"id\":\"{operator}\"}}' }}"
                    "else { throw 'Unexpected Azure command' } };"
                    "function azd { $global:LASTEXITCODE=0;"
                    "if (($args -join ' ') -ne 'config set auth.useAzCliAuth true') "
                    "{ throw 'Unexpected azd action' };"
                    "if ($env:AZD_CONFIG_DIR -eq 'original-profile' -or "
                    f"$env:AZD_CONFIG_DIR -ne '{ROOT / '.artifacts' / 'azd-cli-auth'}') "
                    "{ throw 'Would modify global configuration' };"
                    "$global:profileWrites++;"
                    + ("$global:LASTEXITCODE=1;" if failure == "profile" else "")
                    + "};"
                    "$failed=$false;"
                    f"try {{ & '{ROOT / 'scripts' / 'use-azure-cli-auth.ps1'}' -ConfigPath '{path}' }}"
                    "catch { $failed=$true };"
                    + (
                        "if (-not $failed) { throw 'Expected refusal' };"
                        "if ($env:AZD_CONFIG_DIR -ne 'original-profile' -or "
                        "$env:AZURE_TENANT_ID -ne 'original-tenant' -or "
                        "$env:AZURE_SUBSCRIPTION_ID -ne 'original-subscription') "
                        "{ throw 'Caller environment was not restored' };"
                        f"if ($global:profileWrites -ne {1 if failure == 'profile' else 0}) "
                        "{ throw 'Unexpected profile write' }"
                        if failure else
                        "if ($failed) { throw 'Valid same-user selection failed' };"
                        "if ($global:profileWrites -ne 1) { throw 'Profile was not configured' };"
                        f"if ($env:AZURE_SUBSCRIPTION_ID -ne '{config['subscriptionId']}' -or "
                        "$env:AZURE_TENANT_ID -ne '22222222-2222-3333-4444-555555555555') "
                        "{ throw 'Approved context was not selected' }"
                    )
                )
                result = subprocess.run(
                    [PWSH, "-NoProfile", "-NonInteractive", "-Command", body],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
