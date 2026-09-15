targetScope = 'resourceGroup'

@description('Optional SECOND deployment only after main completes, RBAC propagates, and actual hosted-agent identity is known. Never called by main.')
param environmentName string
param location string
param deploymentId string

@description('Exact outputs from the owned main deployment, never customer resource IDs.')
param initializerIdentityName string = 'bpi-${uniqueString(resourceGroup().id, environmentName)}-initializer'
param initializerStorageName string = 'bpist${uniqueString(resourceGroup().id, environmentName)}'
param initializerSubnetId string = resourceId('Microsoft.Network/virtualNetworks/subnets', 'bpi-${uniqueString(resourceGroup().id, environmentName)}-vnet', 'initializer')
param sqlServerFqdn string = 'bpi-${uniqueString(resourceGroup().id, environmentName)}-sql${environment().suffixes.sqlServerHostname}'
param sqlDatabaseName string = 'pilot'

@description('Actual agent service-principal object ID discovered after source deployment; NOT a project principal or client ID.')
@minLength(36)
@maxLength(36)
param agentPrincipalId string

@description('Application/client ID of that same deployed agent service principal, verified against its object ID by the lifecycle. Not the initializer or project identity.')
@minLength(36)
@maxLength(36)
param agentClientId string

@description('Explicit rerun marker. No utcNow/newGuid default that silently reruns privileged SQL on redeployment.')
param forceUpdateTag string = deploymentId

@description('PowerShell version from official private deploymentScripts example. The initializer explicitly installs its pinned SqlServer module; no sqlcmd availability is assumed.')
param azPowerShellVersion string = '14.0'

resource initializerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: initializerIdentityName
}

resource initializerStorage 'Microsoft.Storage/storageAccounts@2025-06-01' existing = {
  name: initializerStorageName
}

resource bootstrap 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'bpi-${uniqueString(resourceGroup().id, environmentName)}-bootstrap'
  location: location
  tags: {
    bpiTemplate: 'business-performance-investigator'
    bpiEnvironment: environmentName
    bpiDeploymentId: deploymentId
    'bpi-owner': 'business-performance-investigator:${environmentName}:phase1'
    'bpi-environment': environmentName
    'bpi-phase': '1'
  }
  kind: 'AzurePowerShell'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${initializerIdentity.id}': {}
    }
  }
  properties: {
    azPowerShellVersion: azPowerShellVersion
    storageAccountSettings: {
      storageAccountName: initializerStorage.name
    }
    containerSettings: {
      containerGroupName: 'bpi-${uniqueString(resourceGroup().id, environmentName)}-bootstrap-aci'
      subnetIds: [
        {
          id: initializerSubnetId
        }
      ]
    }
    environmentVariables: [
      {
        name: 'AZURE_SQL_SERVER'
        value: sqlServerFqdn
      }
      {
        name: 'AZURE_SQL_DATABASE'
        value: sqlDatabaseName
      }
      {
        name: 'AGENT_PRINCIPAL_ID'
        value: agentPrincipalId
      }
      {
        name: 'AGENT_CLIENT_ID'
        value: agentClientId
      }
      {
        name: 'INITIALIZER_CLIENT_ID'
        value: initializerIdentity.properties.clientId
      }
    ]
    scriptContent: loadTextContent('../scripts/initialize-sql.ps1')
    timeout: 'PT15M'
    retentionInterval: 'PT1H'
    cleanupPreference: 'Always'
    forceUpdateTag: forceUpdateTag
  }
}

output bootstrapDeploymentScriptId string = bootstrap.id
output bootstrapDeploymentScriptName string = bootstrap.name
output bootstrapContainerGroupId string = resourceId('Microsoft.ContainerInstance/containerGroups', 'bpi-${uniqueString(resourceGroup().id, environmentName)}-bootstrap-aci')
