targetScope = 'resourceGroup'

@description('Optional SECOND deployment only after main completes, RBAC propagates, and actual hosted-agent identity is known. Never called by main.')
param environmentName string
param location string
param deploymentId string

@description('Exact outputs from the owned main deployment, never customer resource IDs.')
param initializerIdentityName string = 'bpi-${uniqueString(resourceGroup().id, environmentName)}-initializer'
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

resource initializerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: initializerIdentityName
}

resource bootstrap 'Microsoft.ContainerInstance/containerGroups@2023-05-01' = {
  name: 'bpi-${uniqueString(resourceGroup().id, environmentName)}-bootstrap-aci'
  location: location
  tags: {
    bpiTemplate: 'business-performance-investigator'
    bpiEnvironment: environmentName
    bpiDeploymentId: deploymentId
    'bpi-owner': 'business-performance-investigator:${environmentName}:phase1'
    'bpi-environment': environmentName
    'bpi-phase': '1'
    bpiInitializationRun: forceUpdateTag
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${initializerIdentity.id}': {}
    }
  }
  properties: {
    osType: 'Linux'
    restartPolicy: 'Never'
    subnetIds: [
      {
        id: initializerSubnetId
      }
    ]
    containers: [
      {
        name: 'sql-initializer'
        properties: {
          image: 'mcr.microsoft.com/azure-powershell@sha256:82b5bb8daa75c8e974f5ff74a61a6add5e8ccd0d464a231a1a1e90ff0b713bd9'
          command: [
            'pwsh'
            '-NoLogo'
            '-NoProfile'
            '-NonInteractive'
            '-Command'
            loadTextContent('../scripts/initialize-sql.ps1')
          ]
          resources: {
            requests: {
              cpu: 1
              memoryInGB: json('1.5')
            }
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
        }
      }
    ]
  }
}

output bootstrapContainerGroupId string = bootstrap.id
output bootstrapContainerGroupName string = bootstrap.name
