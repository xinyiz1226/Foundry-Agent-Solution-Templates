#Requires -Version 7.2

function Assert-BpiInitializationMode {
    param([hashtable]$State, [ValidateSet('Probe', 'AnalysisSnapshot')][string]$Mode)
    if ($State.ContainsKey('initializationMode') -and $State.initializationMode -cne $Mode) {
        throw 'Initializer mode differs from the recorded first Initialize choice. Use a fresh experiment.'
    }
    if ($Mode -eq 'AnalysisSnapshot' -and -not $State.ContainsKey('initializationMode') -and
        ($State.status -ne 'agentDeployed' -or $State.ContainsKey('initializerEvidence'))) {
        throw 'AnalysisSnapshot must be selected at the first Initialize in a new disposable pilot.'
    }
    if ($Mode -eq 'AnalysisSnapshot' -and (Get-BpiOutput $State 'AZURE_SQL_DATABASE') -cne 'pilot') {
        throw 'AnalysisSnapshot refuses customer databases; only the owned new pilot output is supported.'
    }
}

function Assert-BpiInitializerModeContainer {
    param(
        [hashtable]$Container, [hashtable]$State,
        [ValidateSet('Probe', 'AnalysisSnapshot')][string]$Mode,
        [guid]$AgentClientId, [guid]$AgentPrincipalId
    )
    $actualMode = if ($Container.tags.ContainsKey('bpiInitializationMode')) {
        [string]$Container.tags.bpiInitializationMode
    } else { 'Probe' }
    if ($actualMode -cne $Mode) {
        throw 'Existing initializer mode does not match this Initialize request. Never switch modes or adopt its evidence.'
    }
    if ($Mode -eq 'Probe') { return }
    $identityId = [string](Get-BpiOutput $State 'INITIALIZER_ID')
    $expectedName = ($identityId.Split('/')[-1] -replace '-initializer$', '-bootstrap-aci')
    if (-not $identityId.EndsWith('-initializer') -or $Container.id.Split('/')[-1] -cne $expectedName) {
        throw 'Analysis initializer is not the exact owned planned bootstrap-aci name.'
    }
    $variables = @{}
    foreach ($item in $Container.containers[0].environmentVariables) {
        if ($variables.ContainsKey($item.name)) { throw 'Duplicate initializer environment variable.' }
        $variables[$item.name] = $item.value
    }
    $expected = @{
        BPI_INITIALIZATION_MODE = 'AnalysisSnapshot'
        BPI_OWNED_NEW_DATABASE = 'true'
        AZURE_SQL_SERVER = [string](Get-BpiOutput $State 'AZURE_SQL_SERVER')
        AZURE_SQL_DATABASE = 'pilot'
        INITIALIZER_CLIENT_ID = [string](Get-BpiOutput $State 'INITIALIZER_CLIENT_ID')
        AGENT_CLIENT_ID = $AgentClientId.ToString()
        AGENT_PRINCIPAL_ID = $AgentPrincipalId.ToString()
    }
    foreach ($key in $expected.Keys) {
        if (-not $variables.ContainsKey($key) -or $variables[$key] -cne $expected[$key]) {
            throw "Analysis initializer context mismatch: $key."
        }
    }
}

function Wait-BpiAnalysisInitializer {
    param(
        [hashtable]$Config, [hashtable]$State, [string]$ContainerName,
        [guid]$AgentClientId, [guid]$AgentPrincipalId,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 900,
        [ValidateRange(1, 30)][int]$PollIntervalSeconds = 10
    )
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        $container = Get-BpiPrivateInitializer $Config $State $ContainerName
        Assert-BpiInitializerModeContainer $container $State 'AnalysisSnapshot' $AgentClientId $AgentPrincipalId
        if ($container.provisioningState -eq 'Failed') { throw 'Analysis initializer provisioning failed; SQL remains unverified.' }
        $current = $container.containers[0].instanceView.currentState
        if ($current.state -eq 'Terminated') {
            if (-not $current.ContainsKey('exitCode') -or $current.exitCode -ne 0) {
                throw 'Private analysis initializer failed. Inspect its logs before an explicit retry.'
            }
            $logs = Invoke-BpiNative az @('container', 'logs', '--name', $ContainerName,
                '--container-name', 'sql-initializer', '--resource-group', $Config.resourceGroupName,
                '--subscription', $Config.subscriptionId)
            $plain = [regex]::Replace(($logs -join "`n"), '\x1B\[[0-?]*[ -/]*[@-~]', '')
            $markers = [regex]::Matches($plain, '(?m)^BPI_ANALYSIS_INITIALIZER_RESULT=(\{[^\r\n]*\})\s*$')
            if ($markers.Count -ne 1 -or $plain -match '(?m)^BPI_INITIALIZER_RESULT=') {
                throw 'Expected exactly one analysis completion evidence marker, never probe-mode evidence.'
            }
            $evidence = $markers[0].Groups[1].Value | ConvertFrom-Json -AsHashtable
            $expected = @{
                mode = 'AnalysisSnapshot'
                databaseUser = 'bpi_probe_agent'
                agentClientId = $AgentClientId.ToString()
                agentPrincipalId = $AgentPrincipalId.ToString()
                normalizedSha256 = '45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f'
                sourceArchiveSha256 = '73c27309d17cd30bf5351665401106abf649d9f9a9ecb0c770682f6be965aba8'
                salesAmount = '14693465.3186'
                totalProductCost = '8611268.3850'
                expectedProbeAmount = '42.00'
                view = 'reporting.v_internet_sales'
                table = 'reporting.internet_sales_snapshot'
                manifestView = 'reporting.v_analysis_manifest'
                manifestTable = 'reporting.analysis_snapshot_manifest'
                datasetId = 'adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd'
            }
            foreach ($key in $expected.Keys) {
                if (-not $evidence.ContainsKey($key) -or $evidence[$key] -isnot [string] -or
                    $evidence[$key] -cne $expected[$key]) {
                    throw "Analysis completion evidence mismatch: $key."
                }
            }
            if ($evidence.initialized -isnot [bool] -or -not $evidence.initialized -or
                $evidence.rows -isnot [long] -or $evidence.rows -ne 33400 -or
                $evidence.snapshotIsolationState -isnot [long] -or $evidence.snapshotIsolationState -ne 1) {
                throw 'Analysis completion must prove initialization, 33400 rows and snapshot isolation ON.'
            }
            return $evidence
        }
        if ($current.state -notin @('Running', 'Waiting')) { throw 'Unknown analysis initializer execution state.' }
        if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            Invoke-BpiNative az @('container', 'stop', '--name', $ContainerName,
                '--resource-group', $Config.resourceGroupName, '--subscription', $Config.subscriptionId,
                '--output', 'none') | Out-Null
            throw 'Analysis initializer timed out; its exact owned compute was stopped. Inspect and clean up.'
        }
        Write-Host "Private analysis initializer: $($current.state), $([int]$timer.Elapsed.TotalSeconds)s elapsed."
        Start-Sleep -Seconds $PollIntervalSeconds
    }
}
