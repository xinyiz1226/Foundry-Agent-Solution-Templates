targetScope = 'resourceGroup'

@description('Name of a new dedicated Linux Basic B1 App Service Plan.')
@minLength(1)
@maxLength(40)
param planName string

@description('Globally unique name of a new empty Web App.')
@minLength(2)
@maxLength(60)
param webAppName string

@description('Explicitly approved Azure region.')
param location string

@description('Non-secret ownership label for this separately approved deployment.')
@minLength(1)
@maxLength(128)
param ownershipLabel string

var resourceTags = {
  solution: 'information-extraction'
  purpose: 'empty-workbench-host'
  ownership: ownershipLabel
}

resource plan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: planName
  location: location
  kind: 'linux'
  tags: resourceTags
  sku: {
    name: 'B1'
    tier: 'Basic'
    capacity: 1
  }
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2024-11-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  tags: resourceTags
  properties: {
    serverFarmId: plan.id
    reserved: true
    httpsOnly: true
    publicNetworkAccess: 'Disabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.13'
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      http20Enabled: true
    }
  }
}

resource ftpBasicAuthentication 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: webApp
  name: 'ftp'
  properties: {
    allow: false
  }
}

resource scmBasicAuthentication 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2024-11-01' = {
  parent: webApp
  name: 'scm'
  properties: {
    allow: false
  }
}

output appServicePlanId string = plan.id
output webAppId string = webApp.id
output webAppHostName string = webApp.properties.defaultHostName
