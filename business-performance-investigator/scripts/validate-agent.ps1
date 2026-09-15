#Requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [ValidatePattern('^[a-zA-Z0-9_-]{1,128}$')][string]$SessionId = '',
    [switch]$ApproveAzureChanges
)
. "$PSScriptRoot/common.ps1"
Assert-BpiAzureApproval -Approved:$ApproveAzureChanges
$config = Read-BpiConfig $ConfigPath
$state = Read-BpiState $config
if (($state.ContainsKey('agentName') -and $state.agentName -cne 'sql-probe') -or
    ($state.ContainsKey('initializationMode') -and $state.initializationMode -cne 'Probe')) {
    throw 'This validator is probe-specific. Analytical validation requires a dedicated approved cloud validator; probe evidence cannot validate business-investigator.'
}
Get-BpiGroup $config $state | Out-Null
if ((Get-BpiModelConfiguration $config).mode -eq 'existing') {
    Get-BpiExistingModel $config | Out-Null
}
if ($state.status -notin @('initialized', 'validated')) {
    throw 'Initialize the approved SQL identity and fixture before invoking the probe.'
}
$sqlServerId = Get-BpiOutput $state 'sqlServerId'
$sqlServerName = Get-BpiOutput $state 'sqlServerName'
$server = Invoke-BpiNative az @('sql', 'server', 'show', '--name', $sqlServerName,
    '--resource-group', $config.resourceGroupName, '--subscription', $config.subscriptionId,
    '--output', 'json') -Json
if ($server.publicNetworkAccess -cne 'Disabled') { throw 'SQL public network access is not disabled.' }
$endpoints = @(Invoke-BpiNative az @('network', 'private-endpoint', 'list',
    '--resource-group', $config.resourceGroupName, '--subscription', $config.subscriptionId,
    '--output', 'json') -Json)
$sqlEndpoints = @($endpoints | Where-Object {
    @($_.privateLinkServiceConnections | Where-Object {
        $_.privateLinkServiceId -ieq $sqlServerId -and
        $_.privateLinkServiceConnectionState.status -ceq 'Approved'
    }).Count -eq 1
})
if ($sqlEndpoints.Count -ne 1) { throw 'Expected one approved SQL private endpoint in the experiment group.' }
$ips = @(
    foreach ($nic in $sqlEndpoints[0].networkInterfaces) {
        $record = Invoke-BpiNative az @('network', 'nic', 'show', '--ids', $nic.id,
            '--subscription', $config.subscriptionId, '--output', 'json') -Json
        foreach ($ip in $record.ipConfigurations) { $ip.privateIPAddress }
    }
)
$report = @{
    timestamp = [DateTime]::UtcNow.ToString('o')
    scope = 'single-cloud-probe'
    status = 'failed'
    idleResume = 'not_run'
    cleanup = 'not_run'
    requestedSessionId = $SessionId
}
Push-Location $script:ProjectRoot
try {
    $agent = Invoke-BpiNative azd @('ai', 'agent', 'show', 'sql-probe', '--output',
        'json', '-e', $config.environmentName) -Json
    if ($agent.status -notin @('active', 'deployed')) { throw 'Hosted agent is not active.' }
    if ((Get-BpiAgentPrincipalId $agent) -ine $state.agentPrincipalId) {
        throw 'Deployed agent identity changed after SQL initialization.'
    }
    $response = Invoke-BpiNative azd (Get-BpiProbeInvokeArguments `
        -EnvironmentName $config.environmentName -SessionId $SessionId)
    $evidence = ConvertFrom-BpiProbeEvidence ($response -join "`n")
    $report.evidence = $evidence
    Assert-BpiProbeEvidence -Evidence $evidence `
        -ExpectedServer (Get-BpiOutput $state 'AZURE_SQL_SERVER') `
        -ExpectedDatabase (Get-BpiOutput $state 'AZURE_SQL_DATABASE') `
        -ExpectedClientId ([guid]$state.agentClientId) -ExpectedPrivateIps $ips
    $report.status = 'passed'
    $state.status = 'validated'
    Save-BpiState $config $state
}
finally {
    Pop-Location
    $path = Join-Path (Split-Path (Get-BpiStatePath $config) -Parent) 'cloud-probe.json'
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $path -Encoding utf8
}
Write-Host 'The single cloud probe passed. Idle/resume, teardown and the full application remain unverified.'
