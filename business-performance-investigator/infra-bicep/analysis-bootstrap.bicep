targetScope = 'resourceGroup'

@description('Explicit FIRST Initialize opt-in only. A normalized CurrencyKey100 reporting snapshot, NOT a full AdventureWorksDW restore or customer SQL adoption.')
param environmentName string
param location string
param deploymentId string

@description('Actual deployed hosted-agent service principal object ID, verified against agent metadata and its client ID by deploy.ps1.')
@minLength(36)
@maxLength(36)
param agentPrincipalId string

@description('Client/application ID of that same runtime service principal; not the initializer identity.')
@minLength(36)
@maxLength(36)
param agentClientId string

@description('Explicit failed-run retry only. No time-based automatic privileged restart.')
param forceUpdateTag string = deploymentId

var prefix = 'bpi-${uniqueString(resourceGroup().id, environmentName)}'

resource initializerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: '${prefix}-initializer'
}

// Exactly the original planned ACI name: ownership inventory and cleanup do not gain a second container.
resource bootstrap 'Microsoft.ContainerInstance/containerGroups@2023-05-01' = {
  name: '${prefix}-bootstrap-aci'
  location: location
  tags: {
    bpiTemplate: 'business-performance-investigator'
    bpiEnvironment: environmentName
    bpiDeploymentId: deploymentId
    'bpi-owner': 'business-performance-investigator:${environmentName}:phase1'
    'bpi-environment': environmentName
    'bpi-phase': '1'
    bpiInitializationRun: forceUpdateTag
    bpiInitializationMode: 'AnalysisSnapshot'
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
        id: resourceId('Microsoft.Network/virtualNetworks/subnets', '${prefix}-vnet', 'initializer')
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
            loadTextContent('../scripts/initialize-analysis.ps1')
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
              value: '${prefix}-sql${environment().suffixes.sqlServerHostname}'
            }
            {
              name: 'AZURE_SQL_DATABASE'
              value: 'pilot'
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
            {
              name: 'BPI_INITIALIZATION_MODE'
              value: 'AnalysisSnapshot'
            }
            {
              name: 'BPI_OWNED_NEW_DATABASE'
              value: 'true'
            }
            {
              name: 'BPI_ANALYSIS_MANIFEST'
              value: loadTextContent('../data/adventureworks-manifest.json')
            }
          ]
        }
      }
    ]
  }
}

output bootstrapContainerGroupId string = bootstrap.id
output bootstrapContainerGroupName string = bootstrap.name
