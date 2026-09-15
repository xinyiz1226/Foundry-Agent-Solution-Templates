targetScope = 'resourceGroup'

@description('Phase 1 only: deploy into a NEW, dedicated, lifecycle-owned resource group. Existing/customer SQL is not supported.')
@minLength(1)
@maxLength(20)
param environmentName string

@description('Unique lifecycle run ID, also applied to the dedicated resource group by the caller.')
param deploymentId string

@description('Explicit approved region supporting source-hosted Foundry agents, network injection, the model, SQL Basic and private ACI.')
param location string

@description('Explicit deployment operator object ID; grants Foundry Project Manager at project scope, not SQL access.')
@minLength(36)
@maxLength(36)
param operatorPrincipalId string

@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param deploymentPrincipalType string = 'User'

@description('Select initializer for the NEW owned probe only. Caller mode requires separate authorization of the initializer inside SQL before bootstrap.')
@allowed([
  'initializer'
  'caller'
])
param sqlAdminMode string

@description('User-supplied Entra administrator object ID. Supply an empty string only when sqlAdminMode is initializer. No directory lookup or Graph consent is performed.')
param sqlAdminObjectId string

@description('User-supplied Entra administrator display/login name. Supply an empty string only when sqlAdminMode is initializer.')
param sqlAdminLogin string

@description('Explicit model/version/SKU/capacity must be checked against regional availability and quota before approval.')
param modelName string
param modelVersion string
param modelSku string
@minValue(1)
param modelCapacity int
param modelDeploymentName string = modelName
@description('False reuses an externally owned model endpoint; this template never manages or authorizes that shared account.')
param deployModel bool = true
@description('Explicit existing Azure account /openai/v1/ endpoint, or empty for the new project model route.')
param modelEndpoint string = ''
@allowed([
  'responses'
  'chat_completions'
])
param modelApi string = 'responses'

param vnetAddressPrefix string = '10.72.0.0/16'
param foundrySubnetPrefix string = '10.72.0.0/24'
param privateEndpointSubnetPrefix string = '10.72.1.0/24'
param initializerSubnetPrefix string = '10.72.2.0/24'

var suffix = uniqueString(resourceGroup().id, environmentName)
var stem = 'bpi-${suffix}'
var ownershipMarker = 'business-performance-investigator:${environmentName}:phase1'
var tags = {
  bpiTemplate: 'business-performance-investigator'
  bpiEnvironment: environmentName
  bpiDeploymentId: deploymentId
  'bpi-owner': ownershipMarker
  'bpi-environment': environmentName
  'bpi-phase': '1'
}
var foundryUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var foundryProjectManagerRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'eadc314b-1a2d-4efa-be10-5d325db5065e')

resource initializerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${stem}-initializer'
  location: location
  tags: tags
}

// https://learn.microsoft.com/azure/container-instances/container-instances-nat-gateway
// ACI documents NAT as its only supported VNet outbound configuration.
// These billed resources serve initialization only and persist until RG cleanup.
resource initializerPublicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  name: '${stem}-initializer-egress-ip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource initializerNatGateway 'Microsoft.Network/natGateways@2024-07-01' = {
  name: '${stem}-initializer-nat'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    idleTimeoutInMinutes: 4
    publicIpAddresses: [
      {
        id: initializerPublicIp.id
      }
    ]
  }
}

// No forced tunnel, firewall, or public SQL exception. NAT does not filter egress:
// initialization needs HTTPS to MCR, PSGallery/package CDN, Entra and Azure APIs.
resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: '${stem}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: 'foundry'
        properties: {
          addressPrefix: foundrySubnetPrefix
          delegations: [
            {
              name: 'foundry-environments'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'private-endpoints'
        properties: {
          addressPrefix: privateEndpointSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'initializer'
        properties: {
          addressPrefix: initializerSubnetPrefix
          natGateway: {
            id: initializerNatGateway.id
          }
          delegations: [
            {
              name: 'initializer-containers'
              properties: {
                serviceName: 'Microsoft.ContainerInstance/containerGroups'
              }
            }
          ]
        }
      }
    ]
  }
}

var foundrySubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'foundry')
var privateEndpointSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'private-endpoints')
var initializerSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnet.name, 'initializer')

// Source: local private-network-hosted-agent/modules/foundry.bicep. Preserve the
// account-at-creation injection shape, but deliberately retain PUBLIC Entra ingress.
resource foundryAccount 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: '${stem}-foundry'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: '${stem}-foundry'
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkInjections: [
      {
        scenario: 'agent'
        subnetArmId: foundrySubnetId
        useMicrosoftManagedNetwork: false
      }
    ]
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: foundryAccount
  name: 'pilot'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Business Performance Investigator Phase 1'
    description: 'Source-hosted agent private SQL connectivity probe; not the analyst application.'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = if (deployModel) {
  parent: foundryAccount
  name: modelDeploymentName
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource projectModelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, foundryProject.id, foundryUserRoleId)
  scope: foundryAccount
  properties: {
    principalId: foundryProject.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: foundryUserRoleId
  }
}

resource deploymentFoundryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryProject.id, operatorPrincipalId, foundryProjectManagerRoleId)
  scope: foundryProject
  properties: {
    principalId: operatorPrincipalId
    principalType: deploymentPrincipalType
    roleDefinitionId: foundryProjectManagerRoleId
  }
}

resource sqlServer 'Microsoft.Sql/servers@2023-08-01' = {
  name: '${stem}-sql'
  location: location
  tags: tags
  properties: {
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      principalType: sqlAdminMode == 'initializer' ? 'Application' : null
      login: sqlAdminMode == 'initializer' ? initializerIdentity.name : sqlAdminLogin
      sid: sqlAdminMode == 'initializer' ? initializerIdentity.properties.principalId : sqlAdminObjectId
      tenantId: tenant().tenantId
    }
  }
}

resource sqlConnectionPolicy 'Microsoft.Sql/servers/connectionPolicies@2023-08-01' = {
  parent: sqlServer
  name: 'default'
  properties: {
    connectionType: 'Proxy'
  }
}

resource sqlDatabase 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: sqlServer
  name: 'pilot'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
    tier: 'Basic'
    capacity: 5
  }
  properties: {
    maxSizeBytes: 2147483648
    requestedBackupStorageRedundancy: 'Local'
    collation: 'SQL_Latin1_General_CP1_CI_AS'
  }
}

// Official private deploymentScripts guidance uses an Azure Files PE and this
// scoped data role. No blob payloads, account keys, public bypass or Graph grants.
resource initializerStorage 'Microsoft.Storage/storageAccounts@2025-06-01' = {
  name: 'bpist${suffix}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    publicNetworkAccess: 'Disabled'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
    }
  }
}

resource initializerStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(initializerStorage.id, initializerIdentity.id, 'storage-file-privileged-contributor')
  scope: initializerStorage
  properties: {
    principalId: initializerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69566ab7-960f-475b-8e7c-b3118f30c6bd')
  }
}

var endpointSpecs = [
  {
    name: 'sql'
    resourceId: sqlServer.id
    groupId: 'sqlServer'
    zoneName: 'privatelink${environment().suffixes.sqlServerHostname}'
  }
  {
    name: 'initializer-file'
    resourceId: initializerStorage.id
    groupId: 'file'
    zoneName: 'privatelink.file.${environment().suffixes.storage}'
  }
]

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for endpoint in endpointSpecs: {
  name: endpoint.zoneName
  location: 'global'
  tags: tags
}]

resource privateDnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (endpoint, i) in endpointSpecs: {
  parent: privateDnsZones[i]
  name: '${stem}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-07-01' = [for endpoint in endpointSpecs: {
  name: '${stem}-${endpoint.name}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: endpoint.name
        properties: {
          privateLinkServiceId: endpoint.resourceId
          groupIds: [
            endpoint.groupId
          ]
        }
      }
    ]
  }
}]

resource privateDnsZoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-07-01' = [for (endpoint, i) in endpointSpecs: {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: endpoint.name
        properties: {
          privateDnsZoneId: privateDnsZones[i].id
        }
      }
    ]
  }
}]

output resourceGroupId string = resourceGroup().id
output resourceGroupName string = resourceGroup().name
@description('The lifecycle must verify the dedicated RG ownership tag before deleting the group; this RG-scoped template does not create/tag its own RG.')
output ownershipMarker string = ownershipMarker
output resourceTags object = tags
output foundryAccountId string = foundryAccount.id
output foundryAccountName string = foundryAccount.name
output foundryProjectId string = foundryProject.id
output foundryProjectName string = foundryProject.name
output foundryProjectEndpoint string = 'https://${foundryAccount.name}.services.ai.azure.com/api/projects/${foundryProject.name}'
output modelDeploymentId string = deployModel ? modelDeployment!.id : ''
output modelDeploymentName string = modelDeploymentName
output sqlServerId string = sqlServer.id
output sqlServerName string = sqlServer.name
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
output sqlDatabaseId string = sqlDatabase.id
output sqlDatabaseName string = sqlDatabase.name
output sqlAdminMode string = sqlAdminMode
output sqlAdminPrincipalObjectId string = sqlAdminMode == 'initializer' ? initializerIdentity.properties.principalId : sqlAdminObjectId
output initializerIdentityId string = initializerIdentity.id
output initializerIdentityName string = initializerIdentity.name
output initializerIdentityClientId string = initializerIdentity.properties.clientId
output initializerIdentityPrincipalId string = initializerIdentity.properties.principalId
output initializerStorageId string = initializerStorage.id
output initializerStorageName string = initializerStorage.name
output initializerNatGatewayId string = initializerNatGateway.id
output initializerNatGatewayName string = initializerNatGateway.name
output initializerPublicIpId string = initializerPublicIp.id
output initializerPublicIpName string = initializerPublicIp.name
output vnetId string = vnet.id
output vnetName string = vnet.name
output foundrySubnetId string = foundrySubnetId
output initializerSubnetId string = initializerSubnetId
output privateEndpointSubnetId string = privateEndpointSubnetId
output AZURE_AI_PROJECT_ENDPOINT string = 'https://${foundryAccount.name}.services.ai.azure.com/api/projects/${foundryProject.name}'
output AZURE_AI_PROJECT_NAME string = foundryProject.name
output AZURE_AI_PROJECT_ID string = foundryProject.id
output AZURE_AI_ACCOUNT_NAME string = foundryAccount.name
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = modelDeploymentName
output AZURE_AI_MODEL_ENDPOINT string = modelEndpoint
output AZURE_AI_MODEL_API string = modelApi
output AZURE_SQL_SERVER string = sqlServer.properties.fullyQualifiedDomainName
output AZURE_SQL_DATABASE string = sqlDatabase.name
output SQL_SERVER_NAME string = sqlServer.name
output INITIALIZER_CLIENT_ID string = initializerIdentity.properties.clientId
output INITIALIZER_PRINCIPAL_ID string = initializerIdentity.properties.principalId
output INITIALIZER_ID string = initializerIdentity.id
output INITIALIZER_SUBNET_ID string = initializerSubnetId
output INITIALIZER_STORAGE_NAME string = initializerStorage.name
output privateEndpointIds array = [for (endpoint, i) in endpointSpecs: privateEndpoints[i].id]
output privateDnsZoneIds array = [for (endpoint, i) in endpointSpecs: privateDnsZones[i].id]
var endpointIds = [for (endpoint, i) in endpointSpecs: privateEndpoints[i].id]
var zoneIds = [for (endpoint, i) in endpointSpecs: privateDnsZones[i].id]
var linkIds = [for (endpoint, i) in endpointSpecs: privateDnsLinks[i].id]
var zoneGroupIds = [for (endpoint, i) in endpointSpecs: privateDnsZoneGroups[i].id]
output ownedResourceIds array = concat([
  initializerIdentity.id
  initializerPublicIp.id
  initializerNatGateway.id
  vnet.id
  foundryAccount.id
  foundryProject.id
  projectModelAccess.id
  deploymentFoundryAccess.id
  sqlServer.id
  sqlConnectionPolicy.id
  sqlDatabase.id
  initializerStorage.id
  initializerStorageAccess.id
], deployModel ? [modelDeployment!.id] : [], endpointIds, zoneIds, linkIds, zoneGroupIds)
