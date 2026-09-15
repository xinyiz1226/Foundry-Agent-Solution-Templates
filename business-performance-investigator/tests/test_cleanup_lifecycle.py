"""Exercise the real ordered cleanup entrypoint against a strictly offline Azure fake."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
SUB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
GROUP = f"/subscriptions/{SUB}/resourceGroups/rg-bpi-cleanup-test"
ACCOUNT = f"{GROUP}/providers/Microsoft.CognitiveServices/accounts/bpi-test-foundry"
PROJECT = f"{ACCOUNT}/projects/pilot"
PROJECT_HOST = f"{PROJECT}/capabilityHosts/default"
ACCOUNT_HOST = f"{ACCOUNT}/capabilityHosts/bpi-test-foundry@aml_aiagentservice"
VNET = f"{GROUP}/providers/Microsoft.Network/virtualNetworks/bpi-test-vnet"
NAT = f"{GROUP}/providers/Microsoft.Network/natGateways/bpi-test-initializer-nat"
ACI = f"{GROUP}/providers/Microsoft.ContainerInstance/containerGroups/bpi-test-bootstrap-aci"
IDENTITY = f"{GROUP}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/bpi-test-initializer"
LEGACY_JOB = f"{GROUP}/providers/Microsoft.Resources/deploymentScripts/bpi-test-bootstrap"
SOFT = (
    f"/subscriptions/{SUB}/providers/Microsoft.CognitiveServices/locations/centralus"
    "/resourceGroups/rg-bpi-cleanup-test/deletedAccounts/bpi-test-foundry"
)
CREATED = "2026-09-14T01:00:00.0000000+00:00"
TAGS = {
    "bpiTemplate": "business-performance-investigator",
    "bpiEnvironment": "cleanup-test",
    "bpiDeploymentId": "cleanup-owned-run",
}


def resource(id_, type_, **properties):
    return {
        "id": id_,
        "name": id_.rsplit("/", 1)[-1],
        "type": type_,
        "location": "centralus",
        "tags": copy.deepcopy(TAGS),
        "systemData": {"createdAt": CREATED},
        "properties": {"provisioningState": "Succeeded", **properties},
    }


def fixture():
    config = json.loads((ROOT / "config.example.json").read_text())
    config.update(
        environmentName="cleanup-test",
        subscriptionId=SUB,
        operatorPrincipalId="11111111-2222-3333-4444-555555555555",
        resourceGroupName="rg-bpi-cleanup-test",
        location="centralus",
    )
    resources = {
        GROUP: resource(GROUP, "Microsoft.Resources/resourceGroups"),
        ACCOUNT: resource(ACCOUNT, "Microsoft.CognitiveServices/accounts"),
        PROJECT: resource(PROJECT, "Microsoft.CognitiveServices/accounts/projects"),
        PROJECT_HOST: resource(PROJECT_HOST, "Microsoft.CognitiveServices/accounts/projects/capabilityHosts"),
        ACCOUNT_HOST: resource(ACCOUNT_HOST, "Microsoft.CognitiveServices/accounts/capabilityHosts"),
        VNET: resource(
            VNET, "Microsoft.Network/virtualNetworks",
            subnets=[
                {"id": f"{VNET}/subnets/{name}", "name": name,
                 "properties": {
                     "serviceAssociationLinks": [],
                     **({"natGateway": {"id": NAT}} if name == "initializer" else {}),
                 }}
                for name in ("foundry", "private-endpoints", "initializer")
            ],
        ),
        NAT: resource(NAT, "Microsoft.Network/natGateways",
                      subnets=[{"id": f"{VNET}/subnets/initializer"}]),
    }
    state = {
        "environmentName": config["environmentName"],
        "subscriptionId": SUB,
        "resourceGroupName": config["resourceGroupName"],
        "configuration": config,
        "deploymentId": TAGS["bpiDeploymentId"],
        "resourceIds": [id_ for id_ in resources if id_ != GROUP],
        "outputs": {},
        "status": "provisionFailed",
    }
    return {
        "config": config, "state": state, "resources": resources, "errors": {},
        "stuck": [], "vanish": [], "vanishAfterDelete": [],
        "vanishAt": {},
        "badCollections": {}, "softOnDelete": True,
        "newIncarnation": False, "noOpGroupDelete": False,
        "salReads": 0, "injectResourceAfterAccountDelete": False,
    }


def initializer_fixture():
    data = fixture()
    data["resources"][IDENTITY] = resource(IDENTITY, "Microsoft.ManagedIdentity/userAssignedIdentities")
    data["resources"][LEGACY_JOB] = resource(
        LEGACY_JOB, "Microsoft.Resources/deploymentScripts", provisioningState="Failed",
    )
    data["resources"][ACI] = resource(
        ACI, "Microsoft.ContainerInstance/containerGroups",
        restartPolicy="Never", osType="Linux",
        subnetIds=[{"id": f"{VNET}/subnets/initializer"}],
        containers=[{
            "name": "sql-initializer",
            "properties": {
                "image": "mcr.microsoft.com/azure-powershell@sha256:82b5bb8daa75c8e974f5ff74a61a6add5e8ccd0d464a231a1a1e90ff0b713bd9",
                "instanceView": {"currentState": {"state": "Terminated", "exitCode": 0}},
            },
        }],
    )
    data["resources"][ACI]["identity"] = {
        "type": "UserAssigned", "userAssignedIdentities": {IDENTITY: {}},
    }
    data["state"]["resourceIds"].extend([IDENTITY, LEGACY_JOB, ACI])
    data["state"]["outputs"] = {
        "INITIALIZER_ID": {"value": IDENTITY},
        "initializerSubnetId": {"value": f"{VNET}/subnets/initializer"},
    }
    data["aciLinkReads"] = 2
    return data


def capability_host_not_found(host_id):
    host_name = host_id.rsplit("/", 1)[-1]
    payload = {"error": {
        "code": "UserError",
        "message": f"CapabilityHost '{host_name}' not found in workspace 'bpi-test-foundry@AML'",
        "details": [],
        "additionalInfo": [
            {"type": "ComponentName", "info": {"value": "managementfrontend"}},
            {"type": "InnerError", "info": {"value": {"code": "NotFoundError", "innerError": None}}},
        ],
    }}
    return f"ERROR: CapabilityHost '{host_name}' not found in workspace 'bpi-test-(" + json.dumps(payload, separators=(",", ":")) + ")"


HARNESS = r"""
$ErrorActionPreference = 'Stop'
$global:f = Get-Content -LiteralPath '__FIXTURE__' -Raw | ConvertFrom-Json -AsHashtable
$global:calls = [Collections.Generic.List[object]]::new()
$global:readCounts = @{}
$global:groupId = '__GROUP__'
$global:accountId = '__ACCOUNT__'
$global:softId = '__SOFT__'
function Emit($value) { ConvertTo-Json -InputObject $value -Depth 40 -Compress }
function Absent {
    $global:LASTEXITCODE = 3
    'ERROR: (ResourceNotFound) The exact resource was not found.'
}
function Start-Sleep {
    param($Seconds)
    $groupDeleteRequested = @($global:calls | Where-Object { $_[0] -eq 'group' -and $_[1] -eq 'delete' }).Count -gt 0
    $networkWait = @($global:readCounts.Keys | Where-Object {
        $_ -match '/virtualNetworks/[^/]+$' -and $global:readCounts[$_] -gt 1
    }).Count -gt 0
    $deletingStuck = @($global:f.stuck | Where-Object {
        $global:f.resources.ContainsKey($_) -and $global:f.resources[$_].properties.provisioningState -eq 'Deleting'
    }).Count -gt 0
    if ($deletingStuck -or ($global:f.noOpGroupDelete -and $groupDeleteRequested) -or
        ($global:f.salReads -eq -1 -and $networkWait)) {
        [Threading.Thread]::Sleep(1050)
    }
}
function az {
    $a = @($args)
    $global:LASTEXITCODE = 0
    $global:calls.Add($a)
    if ($a[0] -eq 'rest') {
        $method = $a[[array]::IndexOf($a, '--method') + 1]
        $url = $a[[array]::IndexOf($a, '--url') + 1]
        $id = ($url -replace '^https://management.azure.com', '') -replace '\?.*$', ''
        if ($global:f.ContainsKey('afterDeletionResponses') -and
            -not $global:f.resources.ContainsKey($global:f.afterDeletionTarget) -and
            $global:f.afterDeletionResponses.ContainsKey("$method $id")) {
            $response = $global:f.afterDeletionResponses["$method $id"]
            $global:LASTEXITCODE = $response.exitCode
            $response.text
            return
        }
        if ($global:f.errors.ContainsKey("$method $id")) {
            $global:LASTEXITCODE = 1
            $global:f.errors["$method $id"]
            return
        }
        if ($method -eq 'get') {
            if (-not $global:readCounts.ContainsKey($id)) { $global:readCounts[$id] = 0 }
            $global:readCounts[$id]++
            $vanishAt = if ($global:f.vanishAt.ContainsKey($id)) { $global:f.vanishAt[$id] } else { 2 }
            if ($id -in $global:f.vanish -or
                ($id -in $global:f.vanishAfterDelete -and $global:readCounts[$id] -ge $vanishAt)) {
                $global:f.resources.Remove($id)
            }
            if ($global:f.newIncarnation -and $id -eq $global:accountId -and $global:readCounts[$id] -ge 2) {
                $global:f.resources[$id].systemData.createdAt = '2026-09-15T03:00:00Z'
            }
            if ($global:f.badCollections.ContainsKey($id)) {
                $global:f.badCollections[$id]
                return
            }
            if ($id -match '/(projects|capabilityHosts)$') {
                $children = @($global:f.resources.Values | Where-Object {
                    $_.id -match "^$([regex]::Escape($id))/[^/]+$"
                })
                Emit @{value=$children}
                return
            }
            if ($id -match '/subnets/initializer$') {
                $parent = $id -replace '/subnets/initializer$', ''
                $subnet = @($global:f.resources[$parent].properties.subnets |
                    Where-Object { $_.name -eq 'initializer' })[0]
                Emit $subnet
                return
            }
            if (-not $global:f.resources.ContainsKey($id)) { Absent; return }
            $result = $global:f.resources[$id]
            if ($global:f.ContainsKey('settle') -and $global:f.settle.ContainsKey($id) -and
                $global:readCounts[$id] -ge $global:f.settle[$id]) {
                $result.properties.provisioningState = 'Succeeded'
            }
            if ($id -match '/containerGroups/[^/]+$' -and $global:f.ContainsKey('restartAt') -and
                $global:readCounts[$id] -ge $global:f.restartAt) {
                $result.properties.containers[0].properties.instanceView.currentState.state = 'Running'
            }
            if ($id -match '/virtualNetworks/[^/]+$' -and $global:f.salReads -ne 0) {
                $result.properties.subnets[0].properties.serviceAssociationLinks = @(@{id='service-owned-SAL'})
                if ($global:f.salReads -gt 0) { $global:f.salReads-- }
            } elseif ($id -match '/virtualNetworks/[^/]+$') {
                $result.properties.subnets[0].properties.serviceAssociationLinks = @()
            }
            if ($id -match '/virtualNetworks/[^/]+$' -and $global:f.ContainsKey('aciLinkReads')) {
                $aciExists = @($global:f.resources.Values | Where-Object {
                    $_.type -eq 'Microsoft.ContainerInstance/containerGroups'
                }).Count -gt 0
                if ($aciExists -or $global:f.aciLinkReads -ne 0) {
                    $result.properties.subnets[2].properties.ipConfigurations = @(@{id='owned-aci-ip'})
                    if (-not $aciExists -and $global:f.aciLinkReads -gt 0) { $global:f.aciLinkReads-- }
                } else {
                    $result.properties.subnets[2].properties.ipConfigurations = @()
                }
            }
            Emit $result
            return
        }
        if ($method -eq 'delete') {
            if ($id -match 'serviceAssociationLinks' -or $id -notin @($global:f.resources.Keys)) {
                if (-not $global:f.resources.ContainsKey($id)) { Absent; return }
                throw 'Forbidden mutation'
            }
            if ($id -in $global:f.stuck) {
                $global:f.resources[$id].properties.provisioningState = 'Deleting'
                return
            }
            if ($id -eq $global:accountId -and $global:f.softOnDelete) {
                $soft = $global:f.resources[$id].Clone()
                $soft.id = $global:softId
                $global:f.resources[$global:softId] = $soft
            }
            $global:f.resources.Remove($id)
            if ($id -eq $global:accountId -and $global:f.injectResourceAfterAccountDelete) {
                $unownedId = "$global:groupId/providers/Microsoft.Storage/storageAccounts/unowned"
                $global:f.resources[$unownedId] = @{id=$unownedId;type='Microsoft.Storage/storageAccounts'}
            }
            return
        }
        throw "Unexpected REST mutation: $($a -join ' ')"
    }
    if ($a[0] -eq 'group' -and $a[1] -eq 'show') {
        if (-not $global:f.resources.ContainsKey($global:groupId)) { Absent; return }
        Emit $global:f.resources[$global:groupId]
        return
    }
    if ($a[0] -eq 'resource' -and $a[1] -eq 'list') {
        if ($global:f.ContainsKey('rawInventory')) { $global:f.rawInventory; return }
        $items = @($global:f.resources.Values | Where-Object { $_.id.StartsWith("$global:groupId/providers/") })
        Emit $items
        return
    }
    if ($a[0] -eq 'container' -and $a[1] -eq 'show') {
        $name = $a[[array]::IndexOf($a, '--name') + 1]
        $id = "$global:groupId/providers/Microsoft.ContainerInstance/containerGroups/$name"
        if (-not $global:f.resources.ContainsKey($id)) { Absent; return }
        $source = $global:f.resources[$id]
        $flat = $source.Clone()
        foreach ($key in $source.properties.Keys) { $flat[$key] = $source.properties[$key] }
        $flat.containers = @($source.properties.containers | ForEach-Object {
            $c = $_.properties.Clone()
            $c.name = $_.name
            $c
        })
        Emit $flat
        return
    }
    if (($a[0..3] -join ' ') -eq 'network vnet subnet update') {
        if (($a[-6..-1] -join ' ') -notmatch 'natGateway --output json --only-show-errors') {
            throw 'Unexpected subnet update'
        }
        $id = $a[[array]::IndexOf($a, '--ids') + 1]
        $vnet = $global:f.resources[($id -replace '/subnets/initializer$', '')]
        $vnet.properties.subnets[2].properties.Remove('natGateway')
        return
    }
    if ($a[0] -eq 'group' -and $a[1] -eq 'delete') {
        if (-not $global:f.noOpGroupDelete) {
            foreach ($id in @($global:f.resources.Keys)) {
                if ($id -eq $global:groupId -or $id.StartsWith("$global:groupId/")) {
                    $global:f.resources.Remove($id)
                }
            }
        }
        return
    }
    throw "Unmocked Azure command (network access forbidden): $($a -join ' ')"
}
try {
    & '__ENTRY__' -ConfigPath '__CONFIG__' -ConfirmResourceGroup '__CONFIRM__' __FLAGS__ -Confirm:$false -WaitTimeoutSeconds 1 -PollIntervalSeconds 1
} catch {
    [Console]::Error.WriteLine($_.ToString())
    $global:failed = $true
} finally {
    ConvertTo-Json -InputObject @($global:calls) -Depth 40 | Set-Content -LiteralPath '__CALLS__'
}
if ($global:failed) { exit 1 }
"""


@unittest.skipUnless(PWSH, "PowerShell 7 required")
class CleanupLifecycleTests(unittest.TestCase):
    def run_cleanup(self, data=None, flags="-ApproveAzureChanges", confirm=None):
        data = data or fixture()
        # Explicit repo-local scratch root: never use the system temp directory.
        with tempfile.TemporaryDirectory(prefix=".cleanup-test-", dir=ROOT) as directory:
            work = Path(directory)
            scripts = work / "scripts"
            scripts.mkdir()
            for name in ("common.ps1", "initializer-common.ps1", "cleanup-common.ps1", "cleanup.ps1"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            config_path = work / "config.json"
            config_path.write_text(json.dumps(data["config"]))
            state_path = work / ".artifacts" / data["config"]["environmentName"] / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps(data["state"]))
            before = state_path.read_bytes()
            fixture_path = work / "fixture.json"
            fixture_path.write_text(json.dumps(data))
            calls_path = work / "calls.json"
            replacements = {
                "FIXTURE": str(fixture_path), "GROUP": GROUP, "ACCOUNT": ACCOUNT,
                "SOFT": SOFT, "ENTRY": str(scripts / "cleanup.ps1"),
                "CONFIG": str(config_path), "CALLS": str(calls_path),
                "CONFIRM": confirm or data["config"]["resourceGroupName"],
            }
            body = HARNESS
            for key, value in replacements.items():
                body = body.replace(f"__{key}__", value.replace("'", "''"))
            body = body.replace("__FLAGS__", flags)
            harness_path = work / "harness.ps1"
            harness_path.write_text(body)
            result = subprocess.run(
                [PWSH, "-NoProfile", "-NonInteractive", "-File", str(harness_path)],
                capture_output=True, text=True, timeout=25, check=False,
            )
            calls = json.loads(calls_path.read_text(encoding="utf-8-sig")) if calls_path.exists() else []
            after = state_path.read_bytes()
            return result, calls, json.loads(after), before == after

    def mutations(self, calls):
        return [
            " ".join(call) for call in calls
            if (call[0] == "rest" and call[2] != "get")
            or call[:2] == ["group", "delete"]
            or call[:4] == ["network", "vnet", "subnet", "update"]
        ]

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_refused_without_mutations(self, data, text, **kwargs):
        result, calls, _, _ = self.run_cleanup(data, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(text, result.stderr)
        self.assertEqual(self.mutations(calls), [])

    def test_ordered_entrypoint_and_retained_soft_delete(self):
        result, calls, state, _ = self.run_cleanup()
        self.assert_ok(result)
        writes = self.mutations(calls)
        expected = [PROJECT_HOST, ACCOUNT_HOST, PROJECT, ACCOUNT,
                    f"{VNET}/subnets/initializer", NAT, "group delete"]
        self.assertEqual(len(writes), len(expected), writes)
        for write, target in zip(writes, expected):
            self.assertIn(target, write)
        self.assertNotIn(SOFT, "\n".join(writes))
        self.assertIn("Purge is NOT approved", result.stdout)
        self.assertEqual(state["status"], "deleted")
        self.assertIn("accountAbsentAt", state["cleanup"])
        self.assertEqual(state["cleanup"]["accountCreatedAt"], CREATED)
        self.assertEqual(state["cleanup"]["retainedSoftDeletedAccountId"], SOFT)

    def test_whatif_reads_and_previews_without_state_or_azure_mutations(self):
        result, calls, _, unchanged = self.run_cleanup(flags="-WhatIf")
        self.assert_ok(result)
        self.assertTrue(unchanged)
        self.assertEqual(self.mutations(calls), [])
        self.assertIn("What if:", result.stdout)
        self.assertIn("SAL release", result.stdout)

    def test_confirmation_and_approval_are_required(self):
        self.assert_refused_without_mutations(fixture(), "ConfirmResourceGroup", confirm="rg-bpi-wrong")
        self.assert_refused_without_mutations(fixture(), "Azure execution is disabled", flags="")

    def test_approval_guard_precedes_config_reads(self):
        result = subprocess.run(
            [PWSH, "-NoProfile", "-NonInteractive", "-File",
             str(ROOT / "scripts" / "cleanup.ps1"),
             "-ConfigPath", str(ROOT / "missing-cleanup-config.json"),
             "-ConfirmResourceGroup", "rg-bpi-cleanup-test"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Azure execution is disabled", result.stderr)
        self.assertNotIn("Cannot find path", result.stderr)

    def test_wrong_group_and_account_tags(self):
        for target in (GROUP, ACCOUNT, PROJECT, VNET):
            with self.subTest(target=target):
                data = fixture()
                data["resources"][target]["tags"]["bpiDeploymentId"] = "not-owned"
                self.assert_refused_without_mutations(data, "ownership")

    def test_inventory_and_unexpected_projects(self):
        data = fixture()
        data["state"]["resourceIds"].remove(NAT)
        self.assert_refused_without_mutations(data, "Unrecorded")
        data = fixture()
        extra = f"{ACCOUNT}/projects/other"
        data["resources"][extra] = resource(extra, "Microsoft.CognitiveServices/accounts/projects")
        data["state"]["resourceIds"].append(extra)
        self.assert_refused_without_mutations(data, "Unexpected Foundry project")

    def test_external_inventory_target_is_never_adopted(self):
        data = fixture()
        data["state"]["resourceIds"].append(
            f"/subscriptions/{SUB}/resourceGroups/shared/providers/Microsoft.CognitiveServices/accounts/deepseek"
        )
        self.assert_refused_without_mutations(data, "external or invalid")

    def test_incarnation_mismatch_and_recreated_deleted_group(self):
        data = fixture()
        data["state"]["cleanup"] = {"accountCreatedAt": "2020-01-01T00:00:00.0000000+00:00"}
        self.assert_refused_without_mutations(data, "incarnation changed")
        data = fixture()
        data["state"]["status"] = "deleted"
        self.assert_refused_without_mutations(data, "reappeared")

    def test_missing_account_incarnation_is_not_permission(self):
        data = fixture()
        del data["resources"][ACCOUNT]["systemData"]
        self.assert_refused_without_mutations(data, "incarnation metadata")

    def test_resume_deleting_hosts_without_repeating_delete(self):
        data = fixture()
        data["resources"][PROJECT_HOST]["properties"]["provisioningState"] = "Deleting"
        data["vanishAfterDelete"] = [PROJECT_HOST]
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(state["status"], "deleted")
        self.assertFalse(any(PROJECT_HOST in write for write in self.mutations(calls)))

    def test_resume_deleting_account_and_absent_children(self):
        data = fixture()
        for id_ in (PROJECT_HOST, ACCOUNT_HOST, PROJECT):
            del data["resources"][id_]
        data["resources"][ACCOUNT]["properties"]["provisioningState"] = "Deleting"
        data["vanishAfterDelete"] = [ACCOUNT]
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(state["status"], "deleted")
        self.assertFalse(any(ACCOUNT in write for write in self.mutations(calls)))

    def test_host_delete_race_explicit_404_is_verified(self):
        data = fixture()
        data["errors"][f"delete {PROJECT_HOST}"] = "ERROR: (ResourceNotFound) Already gone."
        data["vanishAfterDelete"] = [PROJECT_HOST]
        result, calls, _, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(sum(PROJECT_HOST in write for write in self.mutations(calls)), 1)

    def test_account_already_absent_in_partial_provisioning(self):
        data = fixture()
        for id_ in (ACCOUNT, PROJECT, PROJECT_HOST, ACCOUNT_HOST):
            del data["resources"][id_]
        result, _, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(state["status"], "deleted")

    def test_empty_partial_group_needs_no_intact_outputs(self):
        data = fixture()
        data["state"]["resourceIds"] = []
        data["resources"] = {GROUP: data["resources"][GROUP]}
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(len(self.mutations(calls)), 1)
        self.assertEqual(state["status"], "deleted")

    def test_already_gone_group_is_read_only_even_with_deleted_state_and_purge_flag(self):
        for status in ("deleted", "provisionFailed"):
            with self.subTest(status=status):
                data = fixture()
                data["state"]["status"] = status
                soft = copy.deepcopy(data["resources"][ACCOUNT])
                soft["id"] = SOFT
                data["resources"] = {SOFT: soft}
                result, calls, _, unchanged = self.run_cleanup(
                    data, flags="-ApproveAzureChanges -ApproveFoundryPurge",
                )
                self.assert_ok(result)
                self.assertTrue(unchanged)
                self.assertEqual(self.mutations(calls), [])
                self.assertIn(SOFT, result.stdout)
                self.assertIn("already absent", result.stdout)

    def test_auth_errors_and_generic_not_found_are_not_absence(self):
        for text in (
            "ERROR: (AuthorizationFailed) Resource was not found or access denied.",
            "ERROR: AADSTS530036 Authentication failed.",
            "ERROR: command not found",
            "ERROR: (ResourceNotFound) AADSTS530036 authentication failed",
        ):
            with self.subTest(text=text):
                data = fixture()
                data["errors"][f"get {GROUP}"] = text
                self.assert_refused_without_mutations(data, "Cleanup Azure request failed")

    def test_service_not_found_soft_account_while_active_account_exists(self):
        data = fixture()
        data["errors"][f"get {SOFT}"] = (
            'ERROR: Not Found({"error":{"code":"NotFound","message":'
            f'"The deleted account \'{ACCOUNT}\' could not be found."'
            '}})'
        )
        result, calls, _, unchanged = self.run_cleanup(data, flags="-WhatIf")
        self.assert_ok(result)
        self.assertTrue(unchanged)
        self.assertEqual(self.mutations(calls), [])
        self.assertIn("No exact soft-deleted account currently visible", result.stdout)

    def test_service_not_found_parser_rejects_non_404_and_malformed_errors(self):
        for text in (
            "ERROR: NotFound",
            'ERROR: (NotFound) an arbitrary failure',
            'ERROR: ConnectionError: Not Found({"error":{"code":"NotFound","message":"offline"}})',
            'ERROR: Unauthorized({"error":{"code":"NotFound","message":"401"}})',
            'ERROR: Forbidden({"error":{"code":"NotFound","message":"403"}})',
            'ERROR: Not Found({"error":{"code":"AuthorizationFailed","message":"403"}})',
            'ERROR: Not Found({"error":{"code":"NotFound","message":"absent"},"statusCode":403})',
            'ERROR: Not Found({"error":{"code":"NotFound","message":"absent","statusCode":401}})',
            'ERROR: Not Found({"error":{"code":"NotFound","message":"absent"}})\nHTTP 403 Forbidden',
            'ERROR: Not Found({"error":{"code":"NotFound","message":"absent"}}',
            'ERROR: Not Found({"error":{"code":"NotFound","message":"absent",}})',
            'ERROR: Not Found({"error":{"code":"NotFound"}})',
            'ERROR: Not Found({"error":{"code":"NotFound","message":null}})',
        ):
            with self.subTest(text=text):
                data = fixture()
                data["errors"][f"get {SOFT}"] = text
                self.assert_refused_without_mutations(
                    data, "Cleanup Azure request failed", flags="-WhatIf",
                )

    def test_provider_user_error_host_absence_requires_successful_parent_list(self):
        for host in (PROJECT_HOST, ACCOUNT_HOST):
            with self.subTest(host=host):
                data = fixture()
                data["afterDeletionTarget"] = host
                data["afterDeletionResponses"] = {
                    f"get {host}": {"exitCode": 1, "text": capability_host_not_found(host)},
                }
                result, calls, state, _ = self.run_cleanup(data)
                self.assert_ok(result)
                self.assertEqual(state["status"], "deleted")
                self.assertEqual(sum(f"{host}?api-version" in w for w in self.mutations(calls)), 1)
                self.assertIn("corroborated by successful parent capabilityHosts list", result.stdout)

    def test_provider_user_error_does_not_hide_host_still_in_parent_list(self):
        data = fixture()
        data["errors"][f"get {PROJECT_HOST}"] = capability_host_not_found(PROJECT_HOST)
        self.assert_refused_without_mutations(data, "Cleanup Azure request failed")

    def test_provider_user_error_requires_valid_successful_complete_parent_list(self):
        parent_list = PROJECT_HOST.rsplit("/", 1)[0]
        for response in (
            {"exitCode": 1, "text": "ERROR: (AuthorizationFailed) Forbidden"},
            {"exitCode": 1, "text": "ERROR: (ResourceNotFound) Parent collection missing"},
            {"exitCode": 1, "text": "ERROR: ConnectionError timed out"},
            {"exitCode": 0, "text": '{"value":null}'},
            {"exitCode": 0, "text": '{"value":[],}'},
            {"exitCode": 0, "text": "null"},
            {"exitCode": 0, "text": '{"value":[],"nextLink":"more"}'},
            {"exitCode": 0, "text": '{"value":[{"id":"/unexpected"}]}'},
        ):
            with self.subTest(response=response):
                data = fixture()
                data["afterDeletionTarget"] = PROJECT_HOST
                data["afterDeletionResponses"] = {
                    f"get {PROJECT_HOST}": {"exitCode": 1, "text": capability_host_not_found(PROJECT_HOST)},
                    f"get {parent_list}": response,
                }
                result, calls, state, _ = self.run_cleanup(data)
                self.assertNotEqual(result.returncode, 0)
                writes = self.mutations(calls)
                self.assertEqual(len(writes), 1)
                self.assertIn(PROJECT_HOST, writes[0])
                self.assertNotEqual(state["status"], "deleted")

    def test_provider_user_error_is_not_globally_treated_as_404(self):
        for target in (GROUP, ACCOUNT, SOFT):
            with self.subTest(target=target):
                data = fixture()
                data["errors"][f"get {target}"] = capability_host_not_found(PROJECT_HOST)
                self.assert_refused_without_mutations(data, "Cleanup Azure request failed")

    def test_provider_user_error_candidate_rejects_auth_network_and_malformed_payloads(self):
        exact = capability_host_not_found(PROJECT_HOST)
        for text in (
            exact.replace('"UserError"', '"AuthorizationFailed"'),
            exact.replace('"NotFoundError"', '"PermissionDenied"'),
            exact.replace("ERROR: CapabilityHost", "ERROR: ConnectionError CapabilityHost"),
            exact.replace("ERROR: CapabilityHost", "ERROR: network is unreachable CapabilityHost"),
            exact.replace("'default'", "'another-host'"),
            exact.replace('"details":[]', '"details":[{"code":"Forbidden","status":403}]'),
            exact.replace('"details":[]', '"details":[{"code":"UnrelatedFailure"}]'),
            exact.replace('"innerError":null', '"innerError":{"code":"AuthenticationFailed"}'),
            exact[:-1],
            exact.replace('"code":"UserError",', '"code":"UserError",broken,'),
            "ERROR: (UserError) CapabilityHost not found",
        ):
            with self.subTest(text=text):
                data = fixture()
                data["afterDeletionTarget"] = PROJECT_HOST
                data["afterDeletionResponses"] = {
                    f"get {PROJECT_HOST}": {"exitCode": 1, "text": text},
                }
                result, calls, state, _ = self.run_cleanup(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Cleanup Azure request failed", result.stderr)
                self.assertEqual(len(self.mutations(calls)), 1)
                self.assertNotEqual(state["status"], "deleted")

    def test_soft_deleted_read_permission_failure_stops_before_mutation(self):
        data = fixture()
        data["errors"][f"get {SOFT}"] = "ERROR: (AuthorizationFailed) Forbidden"
        self.assert_refused_without_mutations(data, "AuthorizationFailed")

    def test_malformed_and_paginated_child_metadata_fails_closed(self):
        for metadata in ("null", "{}", '{"value":null}', '{"value":[],"nextLink":"more"}'):
            with self.subTest(metadata=metadata):
                data = fixture()
                data["badCollections"][f"{ACCOUNT}/projects"] = metadata
                self.assert_refused_without_mutations(data, "alformed")

    def test_host_timeout_does_not_delete_parent_or_mark_success(self):
        data = fixture()
        data["stuck"] = [PROJECT_HOST]
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out", result.stderr)
        writes = self.mutations(calls)
        self.assertEqual(len(writes), 1)
        self.assertIn(PROJECT_HOST, writes[0])
        self.assertNotEqual(state["status"], "deleted")

    def test_sal_timeout_never_patches_link_or_deletes_network_group(self):
        data = fixture()
        data["salReads"] = -1
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SAL release", result.stderr)
        writes = "\n".join(self.mutations(calls))
        self.assertNotIn("network vnet", writes)
        self.assertNotIn(NAT, writes)
        self.assertNotIn("group delete", writes)
        self.assertNotIn("serviceAssociationLinks", writes)
        self.assertNotIn(f"--url https://management.azure.com{SOFT}", writes)
        self.assertNotEqual(state["status"], "deleted")

    def test_sal_polling_resumes_when_platform_releases_link(self):
        data = fixture()
        data["salReads"] = 2
        result, _, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(state["status"], "deleted")

    def test_group_delete_acceptance_is_not_completion(self):
        data = fixture()
        data["noOpGroupDelete"] = True
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out", result.stderr)
        self.assertEqual(sum("group delete" in write for write in self.mutations(calls)), 1)
        self.assertNotEqual(state["status"], "deleted")

    def test_unexpected_resource_appearing_during_cleanup_stops_group_delete(self):
        data = fixture()
        data["injectResourceAfterAccountDelete"] = True
        result, calls, _, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unrecorded", result.stderr)
        self.assertFalse(any("group delete" in write for write in self.mutations(calls)))

    def test_purge_requires_separate_switch_and_verified_incarnation(self):
        result, calls, _, _ = self.run_cleanup(flags="-ApproveAzureChanges -ApproveFoundryPurge")
        self.assert_ok(result)
        writes = self.mutations(calls)
        self.assertEqual(sum(SOFT in write for write in writes), 1)
        self.assertLess(next(i for i, w in enumerate(writes) if SOFT in w),
                        next(i for i, w in enumerate(writes) if "network vnet" in w))
        data = fixture()
        for id_ in (ACCOUNT, PROJECT, PROJECT_HOST, ACCOUNT_HOST):
            del data["resources"][id_]
        data["resources"][SOFT] = resource(SOFT, "Microsoft.CognitiveServices/deletedAccounts")
        result, calls, _, _ = self.run_cleanup(data, flags="-ApproveAzureChanges -ApproveFoundryPurge")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incarnation", result.stderr)
        self.assertEqual(self.mutations(calls), [])

    def test_unsafe_initializer_association_is_not_detached(self):
        data = fixture()
        data["resources"][VNET]["properties"]["subnets"][2]["properties"]["natGateway"]["id"] = (
            "/subscriptions/other/resourceGroups/shared/providers/Microsoft.Network/natGateways/shared"
        )
        result, calls, _, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NAT association is not owned", result.stderr)
        self.assertFalse(any("network vnet" in write or "group delete" in write
                             for write in self.mutations(calls)))
        self.assertEqual(self.mutations(calls), [])

    def test_malformed_inventory_cannot_authorize_empty_group_deletion(self):
        for raw in ("null", "{}", '""'):
            with self.subTest(raw=raw):
                data = fixture()
                data["rawInventory"] = raw
                self.assert_refused_without_mutations(data, "alformed")

    def test_account_recreation_between_inspection_and_first_mutation(self):
        data = fixture()
        data["newIncarnation"] = True
        self.assert_refused_without_mutations(data, "incarnation changed")

    def test_account_delete_timeout_blocks_network_and_group(self):
        data = fixture()
        data["stuck"] = [ACCOUNT]
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"absence of {ACCOUNT}", result.stderr)
        writes = self.mutations(calls)
        self.assertFalse(any("network vnet" in w or "group delete" in w for w in writes))
        self.assertEqual(sum(f"{ACCOUNT}?api-version" in w for w in writes), 1)
        self.assertNotEqual(state["status"], "deleted")

    def test_resume_group_deleting_without_repeating_delete(self):
        data = fixture()
        data["state"]["resourceIds"] = []
        data["resources"] = {GROUP: data["resources"][GROUP]}
        data["resources"][GROUP]["properties"]["provisioningState"] = "Deleting"
        data["vanishAfterDelete"] = [GROUP]
        data["vanishAt"][GROUP] = 3
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertEqual(self.mutations(calls), [])
        self.assertEqual(state["status"], "deleted")

    def test_purge_already_requested_is_polled_not_repeated(self):
        data = fixture()
        data["resources"] = {
            GROUP: data["resources"][GROUP],
            SOFT: resource(SOFT, "Microsoft.CognitiveServices/deletedAccounts"),
        }
        data["state"]["cleanup"] = {
            "accountCreatedAt": CREATED,
            "purgeRequestedFor": CREATED,
        }
        data["vanishAfterDelete"] = [SOFT]
        data["vanishAt"][SOFT] = 6
        result, calls, state, _ = self.run_cleanup(data, flags="-ApproveAzureChanges -ApproveFoundryPurge")
        self.assert_ok(result)
        self.assertEqual(state["status"], "deleted")
        self.assertFalse(any(SOFT in write for write in self.mutations(calls)))

    def test_child_collection_404_does_not_hide_existing_parent(self):
        data = fixture()
        data["errors"][f"get {ACCOUNT}/projects"] = "ERROR: (ResourceNotFound) Missing collection."
        self.assert_refused_without_mutations(data, "while its parent exists")

    def test_initializer_work_must_finish_before_nat_detachment(self):
        data = fixture()
        job_id = f"{GROUP}/providers/Microsoft.Resources/deploymentScripts/bpi-test-bootstrap"
        data["resources"][job_id] = resource(
            job_id, "Microsoft.Resources/deploymentScripts", provisioningState="Running",
        )
        data["state"]["resourceIds"].append(job_id)
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("remaining initializer work", result.stderr)
        self.assertFalse(any("network vnet" in write or "group delete" in write
                             for write in self.mutations(calls)))
        self.assertNotEqual(state["status"], "deleted")

    def test_missing_provisioning_metadata_is_not_deletion(self):
        data = fixture()
        del data["resources"][PROJECT_HOST]["properties"]["provisioningState"]
        self.assert_refused_without_mutations(data, "Missing provisioningState")

    def test_transient_provisioning_is_polled_before_delete(self):
        data = fixture()
        data["resources"][PROJECT_HOST]["properties"]["provisioningState"] = "Updating"
        data["settle"] = {PROJECT_HOST: 2}
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertIn("provisioning to settle", result.stdout)
        self.assertEqual(state["status"], "deleted")
        host_calls = [
            call for call in calls
            if call[0] == "rest" and f"https://management.azure.com{PROJECT_HOST}?api-version=2025-04-01-preview" in call
        ]
        delete_at = next(i for i, call in enumerate(host_calls) if call[2] == "delete")
        self.assertGreaterEqual(delete_at, 3)

    def test_child_404_during_account_deleting_waits_for_real_parent_absence(self):
        data = fixture()
        for id_ in (PROJECT, PROJECT_HOST, ACCOUNT_HOST):
            del data["resources"][id_]
        data["resources"][ACCOUNT]["properties"]["provisioningState"] = "Deleting"
        data["errors"][f"get {ACCOUNT}/projects"] = "ERROR: (ParentResourceNotFound) Parent deleting."
        data["vanishAfterDelete"] = [ACCOUNT]
        data["vanishAt"][ACCOUNT] = 3
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertIn("already-Deleting parent", result.stdout)
        self.assertFalse(any(ACCOUNT in write for write in self.mutations(calls)))
        self.assertEqual(state["status"], "deleted")

    def test_terminal_direct_initializer_and_failed_legacy_script_cleanup_order(self):
        result, calls, state, _ = self.run_cleanup(initializer_fixture())
        self.assert_ok(result)
        writes = self.mutations(calls)
        aci_delete = next(i for i, w in enumerate(writes) if ACI in w)
        account_delete = next(i for i, w in enumerate(writes) if f"{ACCOUNT}?api-version" in w)
        nat_detach = next(i for i, w in enumerate(writes) if "network vnet subnet update" in w)
        self.assertLess(account_delete, aci_delete)
        self.assertLess(aci_delete, nat_detach)
        self.assertEqual(sum(ACI in w for w in writes), 1)
        self.assertFalse(any(LEGACY_JOB in w for w in writes))
        self.assertIn("private initializer ACI absence", result.stdout)
        self.assertIn("Waiting: SAL release", result.stdout)
        self.assertEqual(state["status"], "deleted")

    def test_terminal_direct_initializer_whatif_is_read_only(self):
        result, calls, _, unchanged = self.run_cleanup(initializer_fixture(), flags="-WhatIf")
        self.assert_ok(result)
        self.assertTrue(unchanged)
        self.assertEqual(self.mutations(calls), [])
        self.assertIn("Delete verified terminal private initializer ACI", result.stdout)

    def test_direct_initializer_requires_explicit_approval(self):
        self.assert_refused_without_mutations(
            initializer_fixture(), "Azure execution is disabled", flags="",
        )

    def test_terminal_failed_initializer_can_be_deleted_without_claiming_sql_success(self):
        data = initializer_fixture()
        data["resources"][ACI]["properties"]["containers"][0]["properties"]["instanceView"]["currentState"]["exitCode"] = 17
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertTrue(any(ACI in w for w in self.mutations(calls)))
        self.assertEqual(state["status"], "deleted")

    def test_direct_initializer_running_waiting_unknown_or_missing_exit_code_refused(self):
        for execution in (
            {"state": "Running", "exitCode": 0},
            {"state": "Waiting", "exitCode": 0},
            {"state": "Unknown", "exitCode": 0},
            {"state": "Terminated"},
            {"state": "Terminated", "exitCode": None},
            {"state": "Terminated", "exitCode": "0"},
        ):
            with self.subTest(execution=execution):
                data = initializer_fixture()
                data["resources"][ACI]["properties"]["containers"][0]["properties"]["instanceView"]["currentState"] = execution
                self.assert_refused_without_mutations(data, "terminal state", flags="-WhatIf")

    def test_direct_initializer_ownership_and_topology_mismatches_refused(self):
        for mismatch in ("tags", "identity", "extra_identity", "subnet", "image", "restart", "public", "name", "outputs", "unrecorded", "os", "provisioning", "extra_container", "missing_execution"):
            with self.subTest(mismatch=mismatch):
                data = initializer_fixture()
                aci = data["resources"][ACI]
                props = aci["properties"]
                if mismatch == "tags":
                    aci["tags"]["bpiDeploymentId"] = "unowned"
                elif mismatch == "identity":
                    aci["identity"]["userAssignedIdentities"] = {IDENTITY + "-other": {}}
                elif mismatch == "extra_identity":
                    aci["identity"]["userAssignedIdentities"][IDENTITY + "-other"] = {}
                elif mismatch == "subnet":
                    props["subnetIds"][0]["id"] = f"{VNET}/subnets/foundry"
                elif mismatch == "image":
                    props["containers"][0]["properties"]["image"] = "mcr.microsoft.com/azure-powershell:latest"
                elif mismatch == "restart":
                    props["restartPolicy"] = "Always"
                elif mismatch == "public":
                    props["ipAddress"] = {"type": "Public"}
                elif mismatch == "name":
                    other = ACI + "-other"
                    aci["id"] = other
                    data["resources"][other] = data["resources"].pop(ACI)
                    data["state"]["resourceIds"].append(other)
                elif mismatch == "outputs":
                    data["state"]["outputs"] = {}
                elif mismatch == "unrecorded":
                    data["state"]["resourceIds"].remove(ACI)
                elif mismatch == "os":
                    props["osType"] = "Windows"
                elif mismatch == "provisioning":
                    props["provisioningState"] = "Creating"
                elif mismatch == "extra_container":
                    props["containers"].append(copy.deepcopy(props["containers"][0]))
                elif mismatch == "missing_execution":
                    del props["containers"][0]["properties"]["instanceView"]
                result, calls, _, _ = self.run_cleanup(data)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.mutations(calls), [], result.stdout + result.stderr)

    def test_direct_initializer_deleting_resume_does_not_repeat_delete(self):
        data = initializer_fixture()
        data["resources"][ACI]["properties"]["provisioningState"] = "Deleting"
        data["vanishAfterDelete"] = [ACI]
        data["vanishAt"][ACI] = 3
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertFalse(any(ACI in w for w in self.mutations(calls)))
        self.assertEqual(state["status"], "deleted")

    def test_direct_initializer_already_absent_resumes(self):
        data = initializer_fixture()
        del data["resources"][ACI]
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertFalse(any(ACI in w for w in self.mutations(calls)))
        self.assertEqual(state["status"], "deleted")

    def test_direct_initializer_delete_timeout_never_detaches_nat(self):
        data = initializer_fixture()
        data["stuck"] = [ACI]
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting for private initializer ACI absence", result.stderr)
        writes = self.mutations(calls)
        self.assertEqual(sum(ACI in w for w in writes), 1)
        self.assertFalse(any("network vnet" in w or "group delete" in w for w in writes))
        self.assertNotEqual(state["status"], "deleted")

    def test_direct_initializer_subnet_release_timeout_never_detaches_nat(self):
        data = initializer_fixture()
        data["aciLinkReads"] = -1
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting for SAL release", result.stderr)
        writes = self.mutations(calls)
        self.assertTrue(any(ACI in w for w in writes))
        self.assertFalse(any("network vnet" in w or "group delete" in w for w in writes))
        self.assertNotEqual(state["status"], "deleted")

    def test_active_legacy_script_blocks_direct_initializer_deletion(self):
        data = initializer_fixture()
        data["resources"][LEGACY_JOB]["properties"]["provisioningState"] = "Running"
        self.assert_refused_without_mutations(data, "Legacy initializer deploymentScript work remains active")

    def test_direct_initializer_read_authorization_failure_is_not_absence(self):
        data = initializer_fixture()
        data["errors"][f"get {ACI}"] = "ERROR: (AuthorizationFailed) Forbidden."
        self.assert_refused_without_mutations(data, "AuthorizationFailed")

    def test_direct_initializer_revalidated_immediately_before_delete(self):
        data = initializer_fixture()
        data["restartAt"] = 3
        result, calls, state, _ = self.run_cleanup(data)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("terminal state", result.stderr)
        self.assertFalse(any(ACI in w or "network vnet" in w or "group delete" in w
                             for w in self.mutations(calls)))
        self.assertNotEqual(state["status"], "deleted")

    def test_direct_initializer_disappears_before_delete_request(self):
        data = initializer_fixture()
        data["vanishAfterDelete"] = [ACI]
        data["vanishAt"][ACI] = 3
        result, calls, state, _ = self.run_cleanup(data)
        self.assert_ok(result)
        self.assertFalse(any(ACI in w for w in self.mutations(calls)))
        self.assertEqual(state["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
