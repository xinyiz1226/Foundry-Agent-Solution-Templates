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
    if ($global:f.stuck.Count -or ($global:f.noOpGroupDelete -and $groupDeleteRequested) -or
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
            if ($id -match '/virtualNetworks/[^/]+$' -and $global:f.salReads -ne 0) {
                $result.properties.subnets[0].properties.serviceAssociationLinks = @(@{id='service-owned-SAL'})
                if ($global:f.salReads -gt 0) { $global:f.salReads-- }
            } elseif ($id -match '/virtualNetworks/[^/]+$') {
                $result.properties.subnets[0].properties.serviceAssociationLinks = @()
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
            for name in ("common.ps1", "cleanup-common.ps1", "cleanup.ps1"):
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


if __name__ == "__main__":
    unittest.main()
