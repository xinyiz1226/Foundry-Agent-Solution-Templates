#Requires -Version 7.2

function Get-BpiPrivateInitializer {
    param([hashtable]$Config, [hashtable]$State, [string]$ContainerName)
    $container = Invoke-BpiNative az @('container', 'show', '--name', $ContainerName,
        '--resource-group', $Config.resourceGroupName, '--subscription', $Config.subscriptionId,
        '--output', 'json') -Json
    $expectedId = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$($Config.resourceGroupName)/providers/Microsoft.ContainerInstance/containerGroups/$ContainerName"
    if ($container.id -ine $expectedId -or -not $container.ContainsKey('tags') -or
        $container.tags['bpiTemplate'] -cne $script:TemplateName -or
        $container.tags['bpiEnvironment'] -cne $Config.environmentName -or
        $container.tags['bpiDeploymentId'] -cne $State.deploymentId) {
        throw 'Private initializer ownership does not match the approved experiment.'
    }
    if (@($container.containers).Count -ne 1 -or
        $container.containers[0].name -cne 'sql-initializer') {
        throw 'Expected exactly one owned SQL initializer container.'
    }
    $identityId = [string](Get-BpiOutput $State 'INITIALIZER_ID')
    $subnetId = [string](Get-BpiOutput $State 'initializerSubnetId')
    if ($container.identity.type -cne 'UserAssigned' -or
        $container.identity.userAssignedIdentities.Count -ne 1 -or
        @($container.identity.userAssignedIdentities.Keys | Where-Object { $_ -ieq $identityId }).Count -ne 1 -or
        @($container.subnetIds).Count -ne 1 -or $container.subnetIds[0].id -ine $subnetId) {
        throw 'Private initializer identity or subnet differs from the approved deployment.'
    }
    if ($container.containers[0].image -cne 'mcr.microsoft.com/azure-powershell@sha256:82b5bb8daa75c8e974f5ff74a61a6add5e8ccd0d464a231a1a1e90ff0b713bd9') {
        throw 'Private initializer image does not match the pinned Microsoft image.'
    }
    return $container
}

function Wait-BpiPrivateInitializer {
    param(
        [hashtable]$Config,
        [hashtable]$State,
        [string]$ContainerName,
        [guid]$AgentClientId,
        [guid]$AgentPrincipalId,
        [ValidateRange(1, 900)][int]$TimeoutSeconds = 900,
        [ValidateRange(1, 30)][int]$PollIntervalSeconds = 10
    )
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        $container = Get-BpiPrivateInitializer $Config $State $ContainerName
        if ($container.provisioningState -eq 'Failed') {
            throw 'Private initializer provisioning failed. Inspect its events; SQL is not initialized.'
        }
        $current = $container.containers[0].instanceView.currentState
        if ($current.state -eq 'Terminated') {
            if (-not $current.ContainsKey('exitCode') -or $current.exitCode -ne 0) {
                throw 'Private SQL initializer failed. Inspect its container logs before an explicit retry.'
            }
            $logs = Invoke-BpiNative az @('container', 'logs', '--name', $ContainerName,
                '--container-name', 'sql-initializer', '--resource-group', $Config.resourceGroupName,
                '--subscription', $Config.subscriptionId)
            $plain = [regex]::Replace(($logs -join "`n"), '\x1B\[[0-?]*[ -/]*[@-~]', '')
            $matches = [regex]::Matches($plain, '(?m)^BPI_INITIALIZER_RESULT=(\{[^\r\n]*\})\s*$')
            if ($matches.Count -ne 1) {
                throw 'Private initializer did not return exactly one completion evidence marker.'
            }
            $evidence = $matches[0].Groups[1].Value | ConvertFrom-Json -AsHashtable
            if ($evidence.initialized -isnot [bool] -or -not $evidence.initialized -or
                $evidence.databaseUser -cne 'bpi_probe_agent' -or
                $evidence.agentClientId -ine $AgentClientId.ToString() -or
                $evidence.agentPrincipalId -ine $AgentPrincipalId.ToString() -or
                $evidence.expectedProbeAmount -cne '42.00') {
                throw 'Private initializer evidence does not match the approved SQL identity and fixture.'
            }
            return $evidence
        }
        if ($current.state -notin @('Running', 'Waiting')) {
            throw 'Private initializer returned an unknown execution state. SQL completion is unverified.'
        }
        if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            Invoke-BpiNative az @('container', 'stop', '--name', $ContainerName,
                '--resource-group', $Config.resourceGroupName, '--subscription', $Config.subscriptionId,
                '--output', 'none') | Out-Null
            throw 'Private initializer timed out; its owned compute was stopped. Inspect and clean up the experiment.'
        }
        Write-Host "Private SQL initializer: $($current.state), $([int]$timer.Elapsed.TotalSeconds)s elapsed."
        Start-Sleep -Seconds $PollIntervalSeconds
    }
}
