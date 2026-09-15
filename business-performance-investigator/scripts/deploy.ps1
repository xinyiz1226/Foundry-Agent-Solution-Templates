#Requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][ValidateSet('Provision', 'Agent', 'Initialize')][string]$Stage,
    [switch]$ApproveAzureChanges,
    [string]$AgentPrincipalId = '',
    [switch]$RetryInitialization
)
. "$PSScriptRoot/common.ps1"
Assert-BpiAzureApproval -Approved:$ApproveAzureChanges
$config = Read-BpiConfig $ConfigPath
if ($RetryInitialization -and $Stage -ne 'Initialize') {
    throw '-RetryInitialization is only valid for the Initialize stage.'
}
& "$PSScriptRoot/preflight.ps1" -ConfigPath $ConfigPath -CheckAzure

Push-Location $script:ProjectRoot
try {
    if ($Stage -eq 'Provision') {
        if (Test-Path -LiteralPath (Get-BpiStatePath $config)) {
            throw 'An ownership state already exists. Inspect/clean up that experiment before provisioning another.'
        }
        $exists = Invoke-BpiNative az @('group', 'exists', '--name', $config.resourceGroupName,
            '--subscription', $config.subscriptionId, '--output', 'json') -Json
        if ($exists) { throw 'The resource group already exists. This probe never adopts existing groups.' }
        $state = @{
            environmentName = $config.environmentName
            subscriptionId = $config.subscriptionId
            resourceGroupName = $config.resourceGroupName
            deploymentId = [guid]::NewGuid().ToString()
            configuration = $config
            resourceIds = @()
            status = 'creating'
            outputs = @{}
        }
        Save-BpiState $config $state
        Invoke-BpiNative az @('group', 'create', '--name', $config.resourceGroupName,
            '--location', $config.location, '--subscription', $config.subscriptionId,
            '--tags', "bpiTemplate=$script:TemplateName",
            "bpiEnvironment=$($config.environmentName)", "bpiDeploymentId=$($state.deploymentId)",
            '--output', 'none') | Out-Null
        try {
            $parameters = @{
                environmentName = @{ value = $config.environmentName }
                location = @{ value = $config.location }
                deploymentId = @{ value = $state.deploymentId }
                modelName = @{ value = $config.modelName }
                modelVersion = @{ value = $config.modelVersion }
                modelSku = @{ value = $config.modelSku }
                modelCapacity = @{ value = $config.modelCapacity }
                operatorPrincipalId = @{ value = $config.operatorPrincipalId }
                deploymentPrincipalType = @{ value = $config.operatorPrincipalType }
                sqlAdminMode = @{ value = 'initializer' }
                sqlAdminObjectId = @{ value = '' }
                sqlAdminLogin = @{ value = '' }
            }
            $parameterFile = Join-Path (Split-Path (Get-BpiStatePath $config) -Parent) 'main.parameters.json'
            @{
                '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
                contentVersion = '1.0.0.0'
                parameters = $parameters
            } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $parameterFile -Encoding utf8
            $deployment = Invoke-BpiNative az @('deployment', 'group', 'create',
                '--subscription', $config.subscriptionId, '--resource-group', $config.resourceGroupName,
                '--name', 'bpi-core', '--template-file', 'infra-bicep/main.bicep',
                '--parameters', "@$parameterFile", '--output', 'json') -Json
            $state.outputs = $deployment.properties.outputs
            $state.status = 'provisioned'
        }
        catch {
            $state.status = 'provisionFailed'
            throw
        }
        finally {
            Save-BpiState $config $state
            # The group was created exclusively for this run; record partial deployments too.
            $state.resourceIds = @((Get-BpiResources $config) | ForEach-Object { $_.id })
            Save-BpiState $config $state
        }
        Write-Host 'Infrastructure provisioned. No agent, SQL fixture, or connectivity has been validated.'
        return
    }

    $state = Read-BpiState $config
    Get-BpiGroup $config $state | Out-Null
    Assert-BpiInventory $state (Get-BpiResources $config)
    if ($state.status -in @('creating', 'provisionFailed', 'deleted')) {
        throw "State '$($state.status)' cannot proceed. Inspect the failed deployment or clean up."
    }
    if ($Stage -eq 'Agent') {
        if (-not $state.ContainsKey('azdEnvironmentCreated')) {
            if (Test-Path -LiteralPath (Join-Path '.azure' $config.environmentName)) {
                throw 'An azd environment already exists without matching ownership state. Inspect it manually.'
            }
            Invoke-BpiNative azd @('env', 'new', $config.environmentName,
                '--subscription', $config.subscriptionId, '--location', $config.location,
                '--no-prompt') | Write-Host
            $state.azdEnvironmentCreated = $true
            Save-BpiState $config $state
        }
        foreach ($key in @('AZURE_AI_PROJECT_ENDPOINT', 'AZURE_AI_PROJECT_NAME',
                'AZURE_AI_ACCOUNT_NAME', 'AZURE_AI_PROJECT_ID',
                'AZURE_AI_MODEL_DEPLOYMENT_NAME', 'AZURE_SQL_SERVER', 'AZURE_SQL_DATABASE')) {
            $value = [string](Get-BpiOutput $state $key)
            Invoke-BpiNative azd @('env', 'set', $key, $value, '-e', $config.environmentName) | Out-Null
        }
        Invoke-BpiNative azd @('env', 'set', 'AZURE_RESOURCE_GROUP', $config.resourceGroupName,
            '-e', $config.environmentName) | Out-Null
        Invoke-BpiNative azd @('deploy', 'sql-probe', '--no-prompt', '-e',
            $config.environmentName) | Write-Host
        $state.status = 'agentDeployed'
        Save-BpiState $config $state
        Write-Host 'Agent deployment command completed. SQL access is not configured yet.'
        return
    }

    if ($state.status -notin @('agentDeployed', 'initialized', 'validated')) {
        throw 'Deploy the agent before initializing SQL so its actual identity can be verified.'
    }
    if (-not $AgentPrincipalId) {
        throw 'Supply -AgentPrincipalId with the deployed agent identity object ID, not the project or Web identity.'
    }
    $principalId = [guid]::Parse($AgentPrincipalId)
    if ($principalId -eq [guid]::Empty) { throw 'AgentPrincipalId must not be zero.' }
    $agent = Invoke-BpiNative azd @('ai', 'agent', 'show', 'sql-probe', '--output',
        'json', '-e', $config.environmentName) -Json
    if ((Get-BpiAgentPrincipalId $agent) -ine $principalId.ToString()) {
        throw 'Supplied principal does not match the deployed agent metadata. SQL was not initialized.'
    }
    $principal = Invoke-BpiNative az @('ad', 'sp', 'show', '--id', $principalId.ToString(),
        '--query', '{id:id,appId:appId}', '--output', 'json') -Json
    if ($principal.id -ine $principalId.ToString()) { throw 'Directory identity lookup did not match the supplied object ID.' }
    $clientId = [guid]::Parse($principal.appId)
    if ($clientId -eq [guid]::Empty -or
        $clientId.ToString() -eq (Get-BpiOutput $state 'INITIALIZER_CLIENT_ID')) {
        throw 'The runtime identity cannot be the initializer identity.'
    }
    $parameters = @{
        environmentName = @{ value = $config.environmentName }
        location = @{ value = $config.location }
        deploymentId = @{ value = $state.deploymentId }
        agentPrincipalId = @{ value = $principalId.ToString() }
        agentClientId = @{ value = $clientId.ToString() }
    }
    if ($RetryInitialization) {
        $parameters.forceUpdateTag = @{ value = [guid]::NewGuid().ToString() }
    }
    $parameterFile = Join-Path (Split-Path (Get-BpiStatePath $config) -Parent) 'bootstrap.parameters.json'
    @{
        '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters = $parameters
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $parameterFile -Encoding utf8
    try {
        Invoke-BpiNative az @('deployment', 'group', 'create', '--subscription',
            $config.subscriptionId, '--resource-group', $config.resourceGroupName,
            '--name', 'bpi-bootstrap', '--template-file', 'infra-bicep/bootstrap.bicep',
            '--parameters', "@$parameterFile", '--output', 'none') | Out-Null
        $state.agentPrincipalId = $principalId.ToString()
        $state.agentClientId = $clientId.ToString()
        $state.status = 'initialized'
    }
    finally {
        $state.resourceIds = @((Get-BpiResources $config) | ForEach-Object { $_.id })
        Save-BpiState $config $state
    }
    Write-Host 'Private SQL initialization completed. Run agent validation before claiming connectivity works.'
}
finally {
    Pop-Location
}
