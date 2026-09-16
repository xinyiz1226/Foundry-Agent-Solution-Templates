#Requires -Version 7.2
[CmdletBinding(DefaultParameterSetName = 'Live')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Live')][string]$ConfigPath,
    [Parameter(Mandatory, ParameterSetName = 'Live')]
    [ValidatePattern('^[a-zA-Z0-9_-]{1,128}$')][string]$SessionId,
    [Parameter(ParameterSetName = 'Live')][switch]$ApproveAzureChanges,
    [Parameter(ParameterSetName = 'Live')][switch]$ApproveModelInference,
    [Parameter(ParameterSetName = 'Live')]
    [ValidateLength(1, 3000)][string]$Question = 'Compare the approved periods and investigate the largest territory sales changes and their products.',
    [Parameter(Mandatory, ParameterSetName = 'Prepare')][switch]$PrepareOnly,
    [Parameter(ParameterSetName = 'Prepare')][string]$OutputPath = '',
    [string]$PythonPath = '',
    [string]$SourceCsv = ''
)
. "$PSScriptRoot/common.ps1"
if (-not $PrepareOnly) {
    Assert-BpiAzureApproval -Approved:$ApproveAzureChanges
    if (-not $ApproveModelInference) {
        throw 'Model execution is disabled. Obtain fresh cost/scope approval and pass -ApproveModelInference.'
    }
}
if (-not $PythonPath) {
    $PythonPath = Join-Path $script:ProjectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        $PythonPath = Join-Path $script:ProjectRoot '.venv/bin/python'
    }
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not $SourceCsv) { $SourceCsv = Join-Path $script:ProjectRoot '.artifacts/adventureworks/internet_sales.csv' }
$SourceCsv = (Resolve-Path -LiteralPath $SourceCsv).Path
if ($PrepareOnly) {
    if (-not $OutputPath) { $OutputPath = Join-Path $script:ProjectRoot '.artifacts/analysis-validation-preparation.json' }
    $OutputPath = [IO.Path]::GetFullPath($OutputPath)
    Push-Location $script:ProjectRoot
    try {
        Invoke-BpiNative $PythonPath @('-m', 'analysis.cloud_validation', '--prepare-only',
            '--csv', $SourceCsv, '--output', $OutputPath) | Write-Host
    }
    finally { Pop-Location }
    Write-Host 'Reference prepared locally. No Azure, SQL or model calls were made; cloud validation remains not_run.'
    return
}

function Get-BpiAnalysisCloudContext {
    param([hashtable]$Config, [hashtable]$State)
    Get-BpiGroup $Config $State | Out-Null
    Assert-BpiInventory $State (Get-BpiResources $Config)
    $model = Get-BpiModelConfiguration $Config
    if ($model.api -cne 'chat_completions') { throw 'Analysis requires explicit Chat Completions configuration.' }
    if ((Get-BpiOutput $State 'AZURE_AI_MODEL_DEPLOYMENT_NAME') -cne $Config.modelName -or
        (Get-BpiOutput $State 'AZURE_AI_MODEL_API') -cne $model.api -or
        (Get-BpiOutput $State 'AZURE_AI_MODEL_ENDPOINT' -AllowEmpty) -cne $model.endpoint) {
        throw 'Recorded model output differs from the approved model configuration.'
    }
    $modelVersion = if ($model.mode -eq 'existing') {
        (Get-BpiExistingModel $Config).version
    } else {
        $modelId = [string](Get-BpiOutput $State 'modelDeploymentId')
        $groupPrefix = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$($Config.resourceGroupName)/"
        if (-not $modelId.StartsWith($groupPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'New-model deployment is outside the owned group.'
        }
        $deployment = Invoke-BpiNative az @('resource', 'show', '--ids', $modelId,
            '--api-version', '2025-04-01-preview', '--output', 'json') -Json
        if ($deployment.id -ine $modelId -or $deployment.name -cne $Config.modelName -or
            $deployment.properties.provisioningState -cne 'Succeeded' -or
            $deployment.properties.model.version -cne $model.version -or
            [string]$deployment.properties.capabilities.chatCompletion -ine 'true') {
            throw 'Owned model deployment no longer matches the approved configuration.'
        }
        $deployment.properties.model.version
    }
    $environment = Invoke-BpiNative azd @('env', 'get-values', '--output', 'json', '-e', $Config.environmentName) -Json
    foreach ($key in @('AZURE_AI_PROJECT_ENDPOINT', 'AZURE_AI_PROJECT_ID', 'AZURE_SQL_SERVER',
            'AZURE_SQL_DATABASE', 'AZURE_AI_MODEL_DEPLOYMENT_NAME', 'AZURE_AI_MODEL_API', 'AZURE_AI_MODEL_ENDPOINT')) {
        $expected = Get-BpiOutput $State $key -AllowEmpty:($key -eq 'AZURE_AI_MODEL_ENDPOINT')
        if (-not $environment.ContainsKey($key) -or $environment[$key] -cne $expected) {
            throw 'azd environment differs from the approved deployment outputs.'
        }
    }
    if ($environment.FOUNDRY_PROJECT_ENDPOINT -cne (Get-BpiOutput $State 'AZURE_AI_PROJECT_ENDPOINT')) {
        throw 'azd project endpoint differs from the approved project.'
    }
    $agent = Invoke-BpiNative azd @('ai', 'agent', 'show', 'business-investigator',
        '--output', 'json', '-e', $Config.environmentName) -Json
    if ($agent.name -cne 'business-investigator' -or $agent.status -cne 'active' -or
        $agent.version -isnot [string] -or $agent.version -cnotmatch '^[1-9][0-9]{0,10}$' -or
        (Get-BpiAgentPrincipalId $agent) -ine $State.agentPrincipalId) {
        throw 'Active analytical agent name/version/identity does not match the experiment.'
    }
    $principal = Invoke-BpiNative az @('ad', 'sp', 'show', '--id', $State.agentPrincipalId,
        '--query', '{id:id,appId:appId}', '--output', 'json') -Json
    if ($principal.id -ine $State.agentPrincipalId -or $principal.appId -ine $State.agentClientId -or
        $principal.appId -ieq (Get-BpiOutput $State 'INITIALIZER_CLIENT_ID')) {
        throw 'Directory object/client mapping changed or belongs to the initializer.'
    }
    $serverId = Get-BpiOutput $State 'sqlServerId'
    $server = Invoke-BpiNative az @('sql', 'server', 'show', '--name', (Get-BpiOutput $State 'sqlServerName'),
        '--resource-group', $Config.resourceGroupName, '--subscription', $Config.subscriptionId, '--output', 'json') -Json
    if ($server.id -ine $serverId -or $server.id -notin $State.resourceIds -or
        $server.publicNetworkAccess -cne 'Disabled' -or
        $server.fullyQualifiedDomainName -cne (Get-BpiOutput $State 'AZURE_SQL_SERVER')) {
        throw 'Approved SQL server identity, hostname or public-access setting does not match.'
    }
    $endpoints = @(Invoke-BpiNative az @('network', 'private-endpoint', 'list',
        '--resource-group', $Config.resourceGroupName, '--subscription', $Config.subscriptionId, '--output', 'json') -Json)
    $matches = @($endpoints | Where-Object {
        @($_.privateLinkServiceConnections | Where-Object { $_.privateLinkServiceId -ieq $serverId }).Count -gt 0
    })
    if ($matches.Count -ne 1) { throw 'Expected exactly one SQL private endpoint.' }
    $endpoint = $matches[0]
    $subnetId = Get-BpiOutput $State 'privateEndpointSubnetId'
    if ($endpoint.id -notin $State.resourceIds -or $endpoint.id -notin (Get-BpiOutput $State 'privateEndpointIds') -or
        $endpoint.provisioningState -cne 'Succeeded' -or $endpoint.subnet.id -ine $subnetId -or
        @($endpoint.privateLinkServiceConnections).Count -ne 1 -or
        $endpoint.privateLinkServiceConnections[0].privateLinkServiceConnectionState.status -cne 'Approved' -or
        @($endpoint.privateLinkServiceConnections[0].groupIds).Count -ne 1 -or
        $endpoint.privateLinkServiceConnections[0].groupIds[0] -cne 'sqlServer' -or
        ($endpoint.ContainsKey('manualPrivateLinkServiceConnections') -and @($endpoint.manualPrivateLinkServiceConnections).Count -gt 0) -or
        @($endpoint.networkInterfaces).Count -ne 1) {
        throw 'SQL private endpoint is unowned, unapproved or outside the recorded subnet.'
    }
    $nicId = $endpoint.networkInterfaces[0].id
    $nic = Invoke-BpiNative az @('network', 'nic', 'show', '--ids', $nicId,
        '--subscription', $Config.subscriptionId, '--output', 'json') -Json
    if ($nic.id -ine $nicId -or $nic.id -notin $State.resourceIds -or $nic.privateEndpoint.id -ine $endpoint.id -or
        @($nic.ipConfigurations).Count -lt 1 -or @($nic.ipConfigurations).Count -gt 16) {
        throw 'Private endpoint NIC is not the recorded owned interface.'
    }
    $ips = @(
        foreach ($ip in $nic.ipConfigurations) {
            if ($ip.subnet.id -ine $subnetId -or $ip.privateIPAddress -isnot [string]) {
                throw 'Private endpoint NIC address/subnet is invalid.'
            }
            $ip.privateIPAddress
        }
    ) | Sort-Object -Unique
    return [ordered]@{
        server = $server.fullyQualifiedDomainName
        database = (Get-BpiOutput $State 'AZURE_SQL_DATABASE')
        agent_principal_id = $principal.id
        agent_client_id = $principal.appId
        private_ips = @($ips)
        model = $Config.modelName
        model_version = $modelVersion
        agent_version = $agent.version
        private_endpoint_id = $endpoint.id
        private_endpoint_subnet_id = $subnetId
        public_network_access = $server.publicNetworkAccess
        project_endpoint = $environment.FOUNDRY_PROJECT_ENDPOINT
    }
}

$config = Read-BpiConfig $ConfigPath
$state = Read-BpiState $config
$statePath = Get-BpiStatePath $config
$stateHash = (Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash
$attempt = Join-Path (Split-Path $statePath -Parent) ("cloud-analysis/" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $attempt -Force | Out-Null
$reportPath = Join-Path $attempt 'report.json'
$report = @{
    schema_version = 1; timestamp = [DateTime]::UtcNow.ToString('o')
    scope = 'single-cloud-analysis-pair'; status = 'failed'; sessionId = $SessionId
    question = $Question; cleanup = 'not_run'; idleResume = 'not_run'
    real_model_quality_validated = $false; invocations_attempted = @()
    invocation_wall_seconds = @{}
    cost = @{ status = 'unknown'; platformCharges = 'unknown' }
}
$stage = 'local_preconditions'
$lock = $null
$lockPath = Join-Path (Split-Path $statePath -Parent) 'analysis-validation.lock'
Push-Location $script:ProjectRoot
try {
    # A leftover lock requires inspection; never silently override another invocation.
    $lock = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    if ($state.agentName -cne 'business-investigator' -or $state.initializationMode -cne 'AnalysisSnapshot' -or
        $state.status -cnotin @('initialized', 'validated') -or [string]::IsNullOrWhiteSpace($Question)) {
        throw 'An initialized analytical service and a bounded question are required.'
    }
    foreach ($key in @('agentClientId', 'agentPrincipalId')) {
        if ([guid]::Parse($state[$key]) -eq [guid]::Empty) { throw 'Recorded runtime identities must be nonzero.' }
    }
    $policy = Get-Content (Join-Path $script:ProjectRoot 'analysis/hosted-policy.json') -Raw | ConvertFrom-Json -AsHashtable
    if ((Get-FileHash -LiteralPath $SourceCsv -Algorithm SHA256).Hash -ine $policy.source_sha256) {
        throw 'Pinned local reference hash does not match the hosted sample policy.'
    }
    $initial = $state.initializerEvidence
    foreach ($pair in @(
        @('mode', 'AnalysisSnapshot'), @('databaseUser', $policy.database_principal),
        @('agentClientId', $state.agentClientId), @('agentPrincipalId', $state.agentPrincipalId),
        @('normalizedSha256', $policy.source_sha256), @('datasetId', $policy.dataset_id),
        @('salesAmount', $policy.sales_amount), @('totalProductCost', $policy.total_product_cost)
    )) {
        if ($initial[$pair[0]] -isnot [string] -or $initial[$pair[0]] -cne $pair[1]) {
            throw 'Recorded analysis initialization differs from the approved sample or runtime identity.'
        }
    }
    if ($initial.initialized -isnot [bool] -or -not $initial.initialized -or
        $initial.rows -isnot [long] -or $initial.rows -ne $policy.row_count -or
        $initial.snapshotIsolationState -isnot [long] -or $initial.snapshotIsolationState -ne 1) {
        throw 'Recorded initialization does not prove the expected row count and snapshot isolation.'
    }
    $stage = 'cloud_preconditions'
    $report | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $reportPath -Encoding utf8
    $context = Get-BpiAnalysisCloudContext $config $state
    $contextJson = $context | ConvertTo-Json -Depth 10 -Compress
    $contextPath = Join-Path $attempt 'context.json'
    $contextJson | Set-Content -LiteralPath $contextPath -Encoding utf8
    $report.context = $context
    Invoke-BpiNative $PythonPath @('-m', 'analysis.cloud_validation', '--prepare-only',
        '--csv', $SourceCsv, '--context', $contextPath, '--output', (Join-Path $attempt 'preparation.json')) | Out-Null
    $baselinePath = Join-Path $attempt 'baseline.txt'
    $adaptivePath = Join-Path $attempt 'adaptive.txt'
    $evidencePath = Join-Path $attempt 'evidence-validation.json'
    foreach ($mode in @('baseline', 'adaptive')) {
        $stage = "$mode-invocation"
        $request = @{ mode = $mode; question = $Question } | ConvertTo-Json -Compress
        $report.invocations_attempted += $mode
        $report | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $reportPath -Encoding utf8
        $timer = [Diagnostics.Stopwatch]::StartNew()
        try {
            $response = Invoke-BpiNative azd @('ai', 'agent', 'invoke', 'business-investigator',
                '--new-conversation', $request, '--session-id', $SessionId, '-e', $config.environmentName)
        }
        finally {
            $timer.Stop()
            $report.invocation_wall_seconds[$mode] = [math]::Round($timer.Elapsed.TotalSeconds, 6)
        }
        $responsePath = if ($mode -eq 'baseline') { $baselinePath } else { $adaptivePath }
        $response -join "`n" | Set-Content -LiteralPath $responsePath -Encoding utf8
        $stage = "$mode-evidence"
        $arguments = @('-m', 'analysis.cloud_validation', '--csv', $SourceCsv, '--context', $contextPath,
            '--baseline', $baselinePath, '--output', $evidencePath)
        if ($mode -eq 'adaptive') { $arguments += @('--adaptive', $adaptivePath) }
        Invoke-BpiNative $PythonPath $arguments | Out-Null
        $stage = "$mode-postconditions"
        if ((Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash -cne $stateHash) {
            throw 'Ownership state changed during validation; no state update is allowed.'
        }
        $current = Get-BpiAnalysisCloudContext $config $state
        if (($current | ConvertTo-Json -Depth 10 -Compress) -cne $contextJson) {
            throw 'Agent version, identity, model or SQL network context changed during validation.'
        }
    }
    $validation = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json -AsHashtable
    if ($validation.status -cne 'passed') { throw 'Both analytical runs must pass local evidence validation.' }
    $report.validation = $validation
    $stage = 'recording_result'
    if ((Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash -cne $stateHash) {
        throw 'Ownership state changed before recording the result.'
    }
    $state.status = 'validated'
    $state.analysisValidation = @{
        reportPath = $reportPath; sessionId = $SessionId; agentVersion = $context.agent_version
        timestamp = $report.timestamp; scope = $report.scope
    }
    $report.status = 'passed'
    $report | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $reportPath -Encoding utf8
    Save-BpiState $config $state
}
catch {
    $report.status = 'failed'
    $report.error = @{ code = $stage; message = 'Analytical validation failed. Raw CLI/model exceptions are omitted.' }
    throw "Analytical validation failed at '$stage'. See '$reportPath'; no subsequent invocation was attempted."
}
finally {
    try {
        $report | ConvertTo-Json -Depth 60 | Set-Content -LiteralPath $reportPath -Encoding utf8
        foreach ($name in @('baseline.txt', 'adaptive.txt')) {
            $path = Join-Path $attempt $name
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
        }
    }
    finally {
        if ($null -ne $lock) {
            $lock.Dispose()
            Remove-Item -LiteralPath $lockPath
        }
        Pop-Location
    }
}
Write-Host "Analytical connectivity and numerical evidence passed: $reportPath"
Write-Host 'One pair does not establish model quality or cost. The selected session, temporary roles and resource cleanup remain operator-owned.'
