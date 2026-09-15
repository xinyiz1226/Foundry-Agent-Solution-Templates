"""Compile real Bicep and inspect ARM JSON; this is not an Azure deployment test."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InfrastructureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = os.environ.get("BICEP_CLI") or shutil.which("bicep")
        if not compiler:
            raise unittest.SkipTest("Set BICEP_CLI to a standalone Bicep executable")
        cls.templates = {}
        for name in ("main", "bootstrap"):
            result = subprocess.run(
                [compiler, "build", str(ROOT / "infra-bicep" / f"{name}.bicep"), "--stdout"],
                check=True,
                capture_output=True,
                text=True,
            )
            cls.templates[name] = json.loads(result.stdout)

    def resource(self, template, resource_type):
        matches = [
            resource
            for resource in self.templates[template]["resources"]
            if resource["type"] == resource_type
        ]
        self.assertEqual(len(matches), 1, resource_type)
        return matches[0]

    def test_foundry_keeps_public_authenticated_ingress_and_creation_time_injection(self):
        account = self.resource("main", "Microsoft.CognitiveServices/accounts")
        self.assertEqual(account["apiVersion"], "2025-04-01-preview")
        self.assertEqual(account["kind"], "AIServices")
        properties = account["properties"]
        self.assertEqual(properties["publicNetworkAccess"], "Enabled")
        self.assertTrue(properties["disableLocalAuth"])
        injection = properties["networkInjections"]
        self.assertEqual(len(injection), 1)
        self.assertEqual(injection[0]["scenario"], "agent")
        self.assertFalse(injection[0]["useMicrosoftManagedNetwork"])
        self.assertEqual(injection[0]["subnetArmId"], "[variables('foundrySubnetId')]")
        self.assertNotIn("networkAcls", properties)
        self.assertNotIn("encryption", properties)

    def test_three_dedicated_subnets_and_private_sql_dns(self):
        vnet = self.resource("main", "Microsoft.Network/virtualNetworks")
        subnets = {item["name"]: item["properties"] for item in vnet["properties"]["subnets"]}
        self.assertEqual(set(subnets), {"foundry", "private-endpoints", "initializer"})
        self.assertEqual(
            subnets["foundry"]["delegations"][0]["properties"]["serviceName"],
            "Microsoft.App/environments",
        )
        self.assertEqual(
            subnets["initializer"]["delegations"][0]["properties"]["serviceName"],
            "Microsoft.ContainerInstance/containerGroups",
        )
        self.assertEqual(subnets["private-endpoints"]["privateEndpointNetworkPolicies"], "Disabled")
        endpoints = self.templates["main"]["variables"]["endpointSpecs"]
        self.assertEqual([item["groupId"] for item in endpoints], ["sqlServer", "file"])
        self.assertIn("sqlServerHostname", endpoints[0]["zoneName"])
        links = self.resource("main", "Microsoft.Network/privateDnsZones/virtualNetworkLinks")
        self.assertFalse(links["properties"]["registrationEnabled"])
        group = self.resource("main", "Microsoft.Network/privateEndpoints/privateDnsZoneGroups")
        self.assertEqual(len(group["properties"]["privateDnsZoneConfigs"]), 1)

    def test_sql_basic_private_entra_only_with_deliberate_proxy_policy(self):
        server = self.resource("main", "Microsoft.Sql/servers")
        properties = server["properties"]
        self.assertEqual(properties["publicNetworkAccess"], "Disabled")
        self.assertEqual(properties["minimalTlsVersion"], "1.2")
        self.assertTrue(properties["administrators"]["azureADOnlyAuthentication"])
        self.assertNotIn("administratorLoginPassword", properties)
        admin_sid = properties["administrators"]["sid"]
        self.assertIn("Microsoft.ManagedIdentity/userAssignedIdentities", admin_sid)
        self.assertIn("sqlAdminObjectId", admin_sid)
        self.assertNotIn("foundryProject", admin_sid)
        policy = self.resource("main", "Microsoft.Sql/servers/connectionPolicies")
        self.assertEqual(policy["properties"]["connectionType"], "Proxy")
        database = self.resource("main", "Microsoft.Sql/servers/databases")
        self.assertEqual(database["sku"], {"name": "Basic", "tier": "Basic", "capacity": 5})
        self.assertEqual(database["properties"]["maxSizeBytes"], 2147483648)

    def test_initializer_storage_has_no_public_bypass_or_inline_secrets(self):
        storage = self.resource("main", "Microsoft.Storage/storageAccounts")
        self.assertEqual(storage["sku"]["name"], "Standard_LRS")
        self.assertEqual(storage["properties"]["publicNetworkAccess"], "Disabled")
        self.assertEqual(storage["properties"]["networkAcls"]["bypass"], "None")
        self.assertFalse(storage["properties"]["allowBlobPublicAccess"])
        script = self.resource("bootstrap", "Microsoft.Resources/deploymentScripts")
        self.assertEqual(script["kind"], "AzurePowerShell")
        self.assertEqual(
            self.templates["bootstrap"]["parameters"]["azPowerShellVersion"]["defaultValue"],
            "14.0",
        )
        self.assertEqual(set(script["properties"]["storageAccountSettings"]), {"storageAccountName"})
        self.assertEqual(script["properties"]["cleanupPreference"], "Always")
        self.assertEqual(script["properties"]["timeout"], "PT15M")
        self.assertEqual(script["properties"]["retentionInterval"], "PT1H")
        self.assertEqual(len(script["properties"]["containerSettings"]["subnetIds"]), 1)
        self.assertEqual(script["identity"]["type"], "UserAssigned")

    def test_bootstrap_is_separate_and_binds_actual_agent_identity(self):
        self.assertNotIn(
            "Microsoft.Resources/deploymentScripts",
            [resource["type"] for resource in self.templates["main"]["resources"]],
        )
        script = self.resource("bootstrap", "Microsoft.Resources/deploymentScripts")
        environment = {
            item["name"]: item["value"]
            for item in script["properties"]["environmentVariables"]
        }
        self.assertEqual(
            environment["AGENT_PRINCIPAL_ID"],
            "[parameters('agentPrincipalId')]",
        )
        self.assertEqual(environment["AGENT_CLIENT_ID"], "[parameters('agentClientId')]")
        script_content = script["properties"]["scriptContent"]
        if script_content.startswith("[variables("):
            variable_name = script_content[len("[variables('"):-len("')]")]
            script_content = self.templates["bootstrap"]["variables"][variable_name]
        self.assertEqual(
            script_content.splitlines(),
            (ROOT / "scripts" / "initialize-sql.ps1").read_text(encoding="utf-8").splitlines(),
        )
        parameters = self.templates["bootstrap"]["parameters"]
        for parameter in ("agentPrincipalId", "agentClientId"):
            self.assertNotIn("defaultValue", parameters[parameter])
        self.assertEqual(parameters["forceUpdateTag"]["defaultValue"], "[parameters('deploymentId')]")

    def test_topology_excludes_unapproved_resources_and_implicit_model_quota(self):
        allowed_types = {
            "Microsoft.ManagedIdentity/userAssignedIdentities",
            "Microsoft.Network/virtualNetworks",
            "Microsoft.Network/natGateways",
            "Microsoft.Network/publicIPAddresses",
            "Microsoft.CognitiveServices/accounts",
            "Microsoft.CognitiveServices/accounts/projects",
            "Microsoft.CognitiveServices/accounts/deployments",
            "Microsoft.Authorization/roleAssignments",
            "Microsoft.Sql/servers",
            "Microsoft.Sql/servers/connectionPolicies",
            "Microsoft.Sql/servers/databases",
            "Microsoft.Storage/storageAccounts",
            "Microsoft.Network/privateDnsZones",
            "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
            "Microsoft.Network/privateEndpoints",
            "Microsoft.Network/privateEndpoints/privateDnsZoneGroups",
        }
        actual_types = {resource["type"] for resource in self.templates["main"]["resources"]}
        self.assertEqual(actual_types, allowed_types)
        parameters = self.templates["main"]["parameters"]
        for name in ("modelName", "modelVersion", "modelSku", "modelCapacity", "location",
                     "sqlAdminMode", "sqlAdminObjectId", "sqlAdminLogin"):
            self.assertNotIn("defaultValue", parameters[name])

    def test_nat_is_explicit_and_initializer_only(self):
        nat = self.resource("main", "Microsoft.Network/natGateways")
        public_ip = self.resource("main", "Microsoft.Network/publicIPAddresses")
        self.assertEqual(nat["sku"]["name"], "Standard")
        self.assertEqual(public_ip["sku"]["name"], "Standard")
        self.assertEqual(public_ip["properties"]["publicIPAllocationMethod"], "Static")
        vnet = self.resource("main", "Microsoft.Network/virtualNetworks")
        for subnet in vnet["properties"]["subnets"]:
            self.assertEqual("natGateway" in subnet["properties"], subnet["name"] == "initializer")
        for name in ("initializerNatGatewayId", "initializerNatGatewayName",
                     "initializerPublicIpId", "initializerPublicIpName"):
            self.assertIn(name, self.templates["main"]["outputs"])

    def test_existing_model_mode_does_not_own_or_deploy_a_shared_model(self):
        template = self.templates["main"]
        deployment = self.resource("main", "Microsoft.CognitiveServices/accounts/deployments")
        self.assertEqual(deployment["condition"], "[parameters('deployModel')]")
        self.assertTrue(template["parameters"]["deployModel"]["defaultValue"])
        self.assertEqual(template["parameters"]["modelEndpoint"]["defaultValue"], "")
        self.assertEqual(template["parameters"]["modelApi"]["defaultValue"], "responses")
        outputs = template["outputs"]
        self.assertEqual(outputs["AZURE_AI_MODEL_ENDPOINT"]["value"], "[parameters('modelEndpoint')]")
        self.assertEqual(outputs["AZURE_AI_MODEL_API"]["value"], "[parameters('modelApi')]")
        self.assertEqual(outputs["AZURE_AI_MODEL_DEPLOYMENT_NAME"]["value"], "[parameters('modelDeploymentName')]")
        self.assertIn("if(parameters('deployModel')", outputs["modelDeploymentId"]["value"])
        self.assertIn("if(parameters('deployModel')", outputs["ownedResourceIds"]["value"])
        self.assertNotIn("existingModelResourceId", template["parameters"])

    def test_operator_can_deploy_and_project_can_access_models(self):
        roles = [
            resource for resource in self.templates["main"]["resources"]
            if resource["type"] == "Microsoft.Authorization/roleAssignments"
        ]
        operator_roles = [
            role for role in roles
            if role["properties"]["principalId"] == "[parameters('operatorPrincipalId')]"
        ]
        self.assertEqual(len(operator_roles), 1)
        self.assertEqual(
            operator_roles[0]["properties"]["roleDefinitionId"],
            "[variables('foundryProjectManagerRoleId')]",
        )
        self.assertIn("Microsoft.CognitiveServices/accounts/projects", operator_roles[0]["scope"])
        model_roles = [
            role for role in roles
            if role["properties"]["roleDefinitionId"] == "[variables('foundryUserRoleId')]"
        ]
        self.assertEqual(len(model_roles), 1)
        self.assertIn("Microsoft.CognitiveServices/accounts/projects", model_roles[0]["properties"]["principalId"])

    def test_cleanup_and_lifecycle_outputs(self):
        outputs = self.templates["main"]["outputs"]
        for name in (
            "resourceGroupId", "resourceGroupName", "ownershipMarker", "ownedResourceIds",
            "foundryAccountId", "foundryAccountName", "foundryProjectId",
            "foundryProjectName", "foundryProjectEndpoint", "modelDeploymentName",
            "sqlServerId", "sqlServerFqdn", "sqlDatabaseId", "sqlDatabaseName",
            "initializerIdentityId", "initializerIdentityClientId", "initializerIdentityPrincipalId",
            "initializerStorageId", "initializerStorageName", "initializerSubnetId", "vnetId",
            "AZURE_AI_PROJECT_ENDPOINT", "AZURE_AI_PROJECT_NAME", "AZURE_AI_PROJECT_ID",
            "AZURE_AI_ACCOUNT_NAME", "AZURE_AI_MODEL_DEPLOYMENT_NAME", "AZURE_SQL_SERVER",
            "AZURE_SQL_DATABASE", "SQL_SERVER_NAME", "INITIALIZER_CLIENT_ID",
            "INITIALIZER_PRINCIPAL_ID", "INITIALIZER_ID", "INITIALIZER_SUBNET_ID",
            "INITIALIZER_STORAGE_NAME",
        ):
            self.assertIn(name, outputs)
        self.assertNotIn("runtimeIdentityPrincipalId", outputs)
        tags = self.templates["main"]["variables"]["tags"]
        self.assertEqual(tags["bpiTemplate"], "business-performance-investigator")
        self.assertEqual(tags["bpiEnvironment"], "[parameters('environmentName')]")
        for resource in self.templates["main"]["resources"]:
            if "tags" in resource:
                self.assertEqual(resource["tags"], "[variables('tags')]")


if __name__ == "__main__":
    unittest.main()
