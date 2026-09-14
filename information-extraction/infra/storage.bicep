targetScope = 'resourceGroup'

@description('Globally unique name for a new, dedicated Storage Account.')
@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Azure region for the new Storage Account.')
param location string

@description('Private Blob container for the G0 execution ledger.')
param containerName string = 'information-extraction'

@description('Object ID of the explicitly authorized operator in this tenant.')
param operatorPrincipalId string

var blobDataContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  tags: {
    solution: 'information-extraction'
    purpose: 'g0-validation'
  }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowCrossTenantReplication: false
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'None'
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

resource operatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: container
  name: guid(container.id, operatorPrincipalId, blobDataContributorRoleId)
  properties: {
    principalId: operatorPrincipalId
    principalType: 'User'
    roleDefinitionId: blobDataContributorRoleId
  }
}

output storageAccountId string = storage.id
output blobServiceEndpoint string = storage.properties.primaryEndpoints.blob
output blobContainerName string = container.name
output operatorRoleAssignmentId string = operatorRole.id
