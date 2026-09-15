#Requires -Version 7.2
# Kept separate from deployment helpers: cleanup needs explicit not-found results,
# not generic CLI failures, and must never invoke azd or touch shared resources.

function Invoke-BpiCleanupAz {
    param([string[]]$Arguments, [switch]$AllowAbsent, [switch]$Mutation)
    $global:LASTEXITCODE = 0
    $text = @(& az @Arguments --output json --only-show-errors 2>&1 |
        ForEach-Object { [string]$_ }) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        # Only explicit ARM not-found codes qualify. Authentication failures and
        # arbitrary messages containing "not found" must never authorize deletion.
        $code = ''
        if ($text -match '(?m)^ERROR:\s*\((ResourceNotFound|ResourceGroupNotFound|ParentResourceNotFound)\)') {
            $code = $Matches[1]
        }
        elseif ($text -match '"error"\s*:\s*\{\s*"code"\s*:\s*"(ResourceNotFound|ResourceGroupNotFound|ParentResourceNotFound)"') {
            $code = $Matches[1]
        }
        elseif ($text -cmatch '\AERROR: Not Found\((\{[^\r\n]*\})\)\z') {
            # Cognitive Services uses NotFound inside az rest's HTTP-404 envelope.
            # Validate the entire JSON payload, not a substring of arbitrary errors.
            $document = $null
            try {
                $document = [System.Text.Json.JsonDocument]::Parse([string]$Matches[1])
                $root = $document.RootElement
                $errorBody = $root.GetProperty('error')
                $message = $errorBody.GetProperty('message').GetString()
                if (@($root.EnumerateObject()).Count -eq 1 -and
                    @($errorBody.EnumerateObject()).Count -eq 2 -and
                    $errorBody.GetProperty('code').GetString() -ceq 'NotFound' -and
                    -not [string]::IsNullOrWhiteSpace($message) -and
                    $message -notmatch '\b(?:401|403)\b|Unauthorized|Forbidden|AADSTS|AuthorizationFailed|AuthenticationFailed|ConnectionError|timed out') {
                    $code = 'NotFound'
                }
            }
            catch { $code = '' }
            finally { if ($null -ne $document) { $document.Dispose() } }
        }
        if ($AllowAbsent -and $code -and $text -notmatch 'AADSTS|AuthorizationFailed|AuthenticationFailed|Forbidden') {
            return $null
        }
        throw "Cleanup Azure request failed (exit $LASTEXITCODE): $text"
    }
    if ($Mutation) { return }
    if ([string]::IsNullOrWhiteSpace($text)) { throw 'Malformed cleanup response: empty JSON.' }
    $result = ConvertFrom-Json -InputObject $text -AsHashtable -NoEnumerate
    if ($null -eq $result) { throw 'Malformed cleanup response: null JSON is not a 404.' }
    return ,$result
}

function Get-BpiCleanupResource {
    param([string]$Id, [string]$Api = '2025-04-01-preview')
    $value = Invoke-BpiCleanupAz @('rest', '--method', 'get', '--url',
        "https://management.azure.com${Id}?api-version=$Api") -AllowAbsent
    if ($null -ne $value -and ($value -isnot [hashtable] -or
        -not $value.ContainsKey('id') -or $value.id -ine $Id)) {
        throw "Malformed or mismatched resource metadata for $Id."
    }
    return $value
}

function Get-BpiCleanupChildren {
    param([string]$Parent, [string]$Child, [string]$Api = '2025-04-01-preview')
    $value = Invoke-BpiCleanupAz @('rest', '--method', 'get', '--url',
        "https://management.azure.com$Parent/${Child}?api-version=$Api") -AllowAbsent
    if ($null -eq $value) {
        $parentResource = Get-BpiCleanupResource $Parent $Api
        if ($null -ne $parentResource) {
            if ((Get-BpiCleanupProvisioningState $parentResource) -ine 'Deleting') {
                throw "Child collection $Parent/$Child returned 404 while its parent exists."
            }
            if ($WhatIfPreference) {
                throw "Cannot inspect $Parent/$Child while its parent is Deleting. Rerun after Azure completes deletion."
            }
            Wait-BpiCleanup "already-Deleting parent $Parent after child collection 404" {
                $current = Get-BpiCleanupResource $Parent $Api
                if ($null -eq $current) { return $true }
                if ($Parent -ieq $script:CleanupAccountId) { Assert-BpiCleanupAccount $current }
                if ((Get-BpiCleanupProvisioningState $current) -ine 'Deleting') {
                    throw 'Parent left Deleting without confirmed absence; refusing cleanup.'
                }
                return $false
            }
        }
        return @()
    }
    if ($value -isnot [hashtable] -or -not $value.ContainsKey('value') -or
        $value.value -isnot [array] -or ($value.ContainsKey('nextLink') -and $value.nextLink)) {
        throw "Incomplete or malformed $Child collection; refusing cleanup."
    }
    foreach ($item in $value.value) {
        if ($item -isnot [hashtable] -or -not $item.ContainsKey('id') -or
            $item.id -inotmatch "^$([regex]::Escape("$Parent/$Child/"))[^/?#]+$") {
            throw "Unexpected child target in $Child collection."
        }
    }
    return $value.value
}

function Assert-BpiCleanupTags {
    param([hashtable]$Resource)
    if (-not $Resource.ContainsKey('tags') -or $Resource.tags -isnot [hashtable] -or
        $Resource.tags['bpiTemplate'] -cne $script:TemplateName -or
        $Resource.tags['bpiEnvironment'] -cne $config.environmentName -or
        $Resource.tags['bpiDeploymentId'] -cne $state.deploymentId) {
        throw "Resource ownership tags do not match: $($Resource.id)."
    }
}

function Get-BpiCleanupProvisioningState {
    param([hashtable]$Resource)
    if (-not $Resource.ContainsKey('properties') -or
        $Resource.properties -isnot [hashtable] -or
        -not $Resource.properties.ContainsKey('provisioningState') -or
        [string]::IsNullOrWhiteSpace([string]$Resource.properties.provisioningState)) {
        throw "Missing provisioningState for $($Resource.id)."
    }
    return [string]$Resource.properties.provisioningState
}

function Wait-BpiCleanup {
    param([string]$Label, [scriptblock]$Probe)
    $timer = [Diagnostics.Stopwatch]::StartNew()
    do {
        if (& $Probe) { Write-Host "$Label confirmed ($([int]$timer.Elapsed.TotalSeconds)s)."; return }
        Write-Host "Waiting: $Label ($([int]$timer.Elapsed.TotalSeconds)s; limit ${WaitTimeoutSeconds}s)."
        if ($timer.Elapsed.TotalSeconds -ge $WaitTimeoutSeconds) {
            throw "Timed out waiting for $Label. Cleanup is incomplete; rerun after investigating Azure status. Never delete or patch serviceAssociationLinks."
        }
        Start-Sleep -Seconds $PollIntervalSeconds
    } while ($true)
}

function Save-BpiCleanupProgress {
    param([string]$Stage)
    if ($WhatIfPreference -or -not $ApproveAzureChanges) { return }
    $state.cleanup.stage = $Stage
    $state.cleanup.observedAt = [DateTime]::UtcNow.ToString('o')
    Save-BpiState $config $state
}

function Invoke-BpiCleanupMutation {
    param([string]$Target, [string]$Action, [string[]]$Arguments)
    if (-not $WhatIfPreference) { Assert-BpiAzureApproval -Approved:$ApproveAzureChanges }
    if (-not $script:CleanupCmdlet.ShouldProcess($Target, $Action)) {
        if ($WhatIfPreference) { return $false }
        throw "Cleanup stopped: $Action was not confirmed."
    }
    Get-BpiCleanupInventory | Out-Null
    if ($script:CleanupAccountId) {
        $active = Get-BpiCleanupResource $script:CleanupAccountId
        if ($null -ne $active) { Assert-BpiCleanupAccount $active }
    }
    if ($Target -imatch '/providers/Microsoft.ContainerInstance/containerGroups/[^/]+$') {
        # A confirmation prompt can be left open while execution changes. Re-read
        # the complete initializer guard after confirmation, just before deletion.
        $initializer = Get-BpiCleanupInitializer $Target
        if ($null -eq $initializer) { return $true }
        Assert-BpiCleanupInitializerWorkStopped
        if ((Get-BpiCleanupProvisioningState $initializer) -eq 'Deleting') { return $true }
    }
    Save-BpiCleanupProgress "$Action about to be requested: $Target"
    Invoke-BpiCleanupAz $Arguments -Mutation -AllowAbsent | Out-Null
    Save-BpiCleanupProgress "$Action requested: $Target"
    return $true
}

function Assert-BpiCleanupAccount {
    param([hashtable]$Account)
    Assert-BpiCleanupTags $Account
    if (-not $Account.ContainsKey('location') -or $Account.location -ine $config.location -or
        -not $Account.ContainsKey('systemData') -or
        $Account.systemData -isnot [hashtable] -or
        -not $Account.systemData.ContainsKey('createdAt')) {
        throw 'Account incarnation metadata is missing.'
    }
    $created = ConvertTo-BpiCleanupIncarnation $Account.systemData.createdAt
    if ($state.cleanup.ContainsKey('accountCreatedAt') -and
        (ConvertTo-BpiCleanupIncarnation $state.cleanup.accountCreatedAt) -cne $created) {
        throw 'Foundry account incarnation changed. Refusing a recreated account.'
    }
    if ($state.status -eq 'deleted' -or $state.cleanup.ContainsKey('accountAbsentAt')) {
        throw 'An active account reappeared after confirmed absence. Refusing a recreated account.'
    }
    $state.cleanup.accountCreatedAt = $created
}

function ConvertTo-BpiCleanupIncarnation {
    param($Value)
    # ConvertFrom-Json in PowerShell versions may deserialize ISO strings into
    # DateTime. Preserve ticks/offsets instead of comparing culture-formatted text.
    if ($Value -is [DateTime] -or $Value -is [DateTimeOffset]) {
        return ([DateTimeOffset]$Value).ToUniversalTime().ToString('o')
    }
    if ([string]::IsNullOrWhiteSpace([string]$Value)) { throw 'Missing account incarnation timestamp.' }
    return [DateTimeOffset]::Parse([string]$Value,
        [Globalization.CultureInfo]::InvariantCulture).ToUniversalTime().ToString('o')
}

function Remove-BpiCleanupResource {
    param([string]$Id, [string]$Api = '2025-04-01-preview', [switch]$Account)
    $resource = Get-BpiCleanupResource $Id $Api
    if ($null -eq $resource) { return }
    if ($Account) { Assert-BpiCleanupAccount $resource }
    if ($Id -imatch '/projects/[^/]+$|/natGateways/[^/]+$') { Assert-BpiCleanupTags $resource }
    $phase = Get-BpiCleanupProvisioningState $resource
    if ($phase -in @('Creating', 'Updating', 'Accepted', 'Running')) {
        if ($WhatIfPreference) { Write-Host "Would wait for provisioning before deleting $Id."; return }
        Wait-BpiCleanup "provisioning to settle for $Id" {
            $current = Get-BpiCleanupResource $Id $Api
            if ($null -eq $current) { return $true }
            if ($Account) { Assert-BpiCleanupAccount $current }
            $observed = Get-BpiCleanupProvisioningState $current
            if ($observed -in @('Creating', 'Updating', 'Accepted', 'Running')) { return $false }
            if ($observed -notin @('Succeeded', 'Failed', 'Canceled', 'Disabled', 'Deleting')) {
                throw "Unknown provisioning state $observed for $Id."
            }
            return $true
        }
        $resource = Get-BpiCleanupResource $Id $Api
        if ($null -eq $resource) { return }
        if ($Account) { Assert-BpiCleanupAccount $resource }
        if ($Id -imatch '/projects/[^/]+$|/natGateways/[^/]+$') { Assert-BpiCleanupTags $resource }
        $phase = Get-BpiCleanupProvisioningState $resource
    }
    if ($phase -ine 'Deleting') {
        if ($phase -inotin @('Succeeded', 'Failed', 'Canceled', 'Disabled')) {
            throw "Resource $Id is $phase; wait for provisioning to finish before cleanup."
        }
        if (-not (Invoke-BpiCleanupMutation $Id 'Delete owned resource' @('rest',
            '--method', 'delete', '--url', "https://management.azure.com${Id}?api-version=$Api"))) { return }
    }
    elseif ($WhatIfPreference) { Write-Host "Already Deleting: $Id (would wait)."; return }
    Wait-BpiCleanup "absence of $Id" {
        $current = Get-BpiCleanupResource $Id $Api
        if ($null -eq $current) { return $true }
        if ($Account) { Assert-BpiCleanupAccount $current }
        $currentPhase = Get-BpiCleanupProvisioningState $current
        if ($currentPhase -in @('Failed', 'Canceled')) {
            throw "Deletion failed for $Id ($currentPhase)."
        }
        return $false
    }
}

function Get-BpiCleanupSoftAccount {
    if (-not $script:CleanupAccountId) { return $null }
    return Get-BpiCleanupResource $script:CleanupSoftId
}

function Complete-BpiCleanupAccount {
    if (-not $WhatIfPreference -and $null -ne (Get-BpiCleanupResource $script:CleanupAccountId)) {
        throw 'An active account remains or reappeared; soft-delete completion refused.'
    }
    $soft = Get-BpiCleanupSoftAccount
    if ($null -ne $soft) {
        Write-Host "Retained exact soft-deleted Foundry account: $script:CleanupSoftId"
        if ($ApproveFoundryPurge) {
            if (-not $state.cleanup.ContainsKey('accountCreatedAt') -or
                -not $soft.ContainsKey('systemData') -or
                $soft.systemData -isnot [hashtable] -or
                -not $soft.systemData.ContainsKey('createdAt') -or
                (ConvertTo-BpiCleanupIncarnation $soft.systemData.createdAt) -cne
                    (ConvertTo-BpiCleanupIncarnation $state.cleanup.accountCreatedAt)) {
                throw 'Cannot validate the soft-deleted account incarnation; irreversible purge refused.'
            }
            Assert-BpiCleanupTags $soft
            $purgePending = $state.cleanup.ContainsKey('purgeRequestedFor') -and
                (ConvertTo-BpiCleanupIncarnation $state.cleanup.purgeRequestedFor) -ceq
                    (ConvertTo-BpiCleanupIncarnation $state.cleanup.accountCreatedAt)
            $requested = $false
            if (-not $purgePending) {
                $requested = Invoke-BpiCleanupMutation $script:CleanupSoftId 'IRREVERSIBLY purge owned Foundry account' @(
                'rest', '--method', 'delete', '--url',
                "https://management.azure.com$($script:CleanupSoftId)?api-version=2025-04-01-preview")
                if ($requested) {
                    $state.cleanup.purgeRequestedFor = $state.cleanup.accountCreatedAt
                    Save-BpiCleanupProgress 'purge request accepted; absence not yet confirmed'
                }
            }
            if ($requested -or ($purgePending -and -not $WhatIfPreference)) {
                Wait-BpiCleanup "purged account $script:CleanupSoftId" {
                    if ($null -ne (Get-BpiCleanupResource $script:CleanupAccountId)) {
                        throw 'Active account reappeared during purge.'
                    }
                    return $null -eq (Get-BpiCleanupSoftAccount)
                }
                $soft = $null
            }
        }
        else {
            Write-Host 'Purge is NOT approved and was not requested. -ApproveFoundryPurge is separate, irreversible approval.'
        }
    }
    else { Write-Host "No exact soft-deleted account currently visible: $script:CleanupSoftId (not a purge claim)." }
    $state.cleanup.retainedSoftDeletedAccountId = if ($null -ne $soft) { $script:CleanupSoftId } else { $null }
}

function Get-BpiCleanupInventory {
    Get-BpiGroup $config $state | Out-Null
    $items = Invoke-BpiCleanupAz @('resource', 'list', '--subscription', $config.subscriptionId,
        '--resource-group', $config.resourceGroupName)
    if ($items -isnot [array]) { throw 'Malformed resource inventory; an explicit JSON array is required.' }
    foreach ($item in $items) {
        if ($item -isnot [hashtable] -or -not $item.ContainsKey('id') -or
            -not $item.ContainsKey('type') -or
            $item.id -inotmatch "^$([regex]::Escape("$script:CleanupGroupId/providers/"))") {
            throw 'Malformed or out-of-scope resource inventory.'
        }
    }
    Assert-BpiInventory $state $items
    return $items
}

function Assert-BpiCleanupNetwork {
    param([hashtable]$Vnet)
    Assert-BpiCleanupTags $Vnet
    if (-not $Vnet.ContainsKey('properties') -or
        -not $Vnet.properties.ContainsKey('subnets') -or $Vnet.properties.subnets -isnot [array]) {
        throw 'Malformed VNet subnet metadata.'
    }
    foreach ($subnet in $Vnet.properties.subnets) {
        if ($subnet.name -cnotin @('foundry', 'private-endpoints', 'initializer') -or
            $subnet.id -ine "$($Vnet.id)/subnets/$($subnet.name)" -or
            $subnet.properties -isnot [hashtable]) {
            throw 'Unexpected or malformed subnet.'
        }
        if ($subnet.properties.ContainsKey('natGateway') -and $null -ne $subnet.properties.natGateway) {
            $expected = $Vnet.id -replace '/virtualNetworks/([^/]+)-vnet$', '/natGateways/$1-initializer-nat'
            if ($subnet.name -cne 'initializer' -or
                $subnet.properties.natGateway -isnot [hashtable] -or
                $subnet.properties.natGateway.id -ine $expected -or $expected -notin $state.resourceIds) {
                throw 'Initializer NAT association is not owned.'
            }
            $nat = Get-BpiCleanupResource $expected '2024-07-01'
            if ($null -eq $nat) { throw 'Attached initializer NAT is absent; metadata is inconsistent.' }
            Assert-BpiCleanupTags $nat
            if ($nat.properties.ContainsKey('subnets') -and
                @($nat.properties.subnets | Where-Object { $_.id -ine $subnet.id }).Count) {
                throw 'Initializer NAT has an unexpected subnet association.'
            }
            foreach ($key in @('publicIpAddresses', 'publicIpPrefixes')) {
                if (-not $nat.properties.ContainsKey($key)) { continue }
                if ($nat.properties[$key] -isnot [array]) { throw "Malformed NAT $key metadata." }
                foreach ($association in $nat.properties[$key]) {
                    $expectedIp = $expected -replace '/natGateways/([^/]+)-initializer-nat$', '/publicIPAddresses/$1-initializer-egress-ip'
                    if ($key -ne 'publicIpAddresses' -or $association.id -ine $expectedIp -or
                        $association.id -notin $state.resourceIds) {
                        throw 'Initializer NAT has an unexpected public IP association.'
                    }
                }
            }
        }
    }
}

function Wait-BpiCleanupNetwork {
    param([object[]]$Vnets)
    Wait-BpiCleanup 'SAL release and no remaining initializer work (retained soft account may require service support)' {
        $ready = $true
        $inventory = @(Get-BpiCleanupInventory)
        foreach ($item in $inventory) {
            if ($item.type -ieq 'Microsoft.ContainerInstance/containerGroups') { $ready = $false }
            if ($item.type -ieq 'Microsoft.Resources/deploymentScripts') {
                $job = Get-BpiCleanupResource $item.id '2023-08-01'
                if ($null -ne $job -and (Get-BpiCleanupProvisioningState $job) -notin @('Succeeded', 'Failed', 'Canceled')) {
                    $ready = $false
                }
            }
        }
        foreach ($item in $Vnets) {
            $vnet = Get-BpiCleanupResource $item.id '2024-07-01'
            if ($null -eq $vnet) { continue }
            Assert-BpiCleanupNetwork $vnet
            foreach ($subnet in $vnet.properties.subnets) {
                foreach ($key in @('serviceAssociationLinks', 'ipConfigurations', 'resourceNavigationLinks')) {
                    if ($subnet.properties.ContainsKey($key)) {
                        if ($null -eq $subnet.properties[$key] -or $subnet.properties[$key] -isnot [array]) {
                            throw "Malformed subnet $key metadata."
                        }
                        if (($key -eq 'serviceAssociationLinks' -or $subnet.name -eq 'initializer') -and
                            $subnet.properties[$key].Count -gt 0) { $ready = $false }
                    }
                }
            }
        }
        return $ready
    }
}

function Get-BpiCleanupInitializer {
    param([string]$Id)
    $identityId = [string](Get-BpiOutput $state 'INITIALIZER_ID')
    $identityPrefix = "$script:CleanupGroupId/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
    if ($identityId -inotmatch "^$([regex]::Escape($identityPrefix))(bpi-[a-z0-9]+)-initializer$" -or
        $identityId -notin $state.resourceIds) {
        throw 'Initializer identity output is not a recorded, planned owned target.'
    }
    $stem = $Matches[1]
    $expectedSubnet = "$script:CleanupGroupId/providers/Microsoft.Network/virtualNetworks/$stem-vnet/subnets/initializer"
    $expectedId = "$script:CleanupGroupId/providers/Microsoft.ContainerInstance/containerGroups/$stem-bootstrap-aci"
    if ($Id -ine $expectedId -or $Id -notin $state.resourceIds -or
        (Get-BpiOutput $state 'initializerSubnetId') -ine $expectedSubnet -or
        ($expectedSubnet -replace '/subnets/initializer$', '') -notin $state.resourceIds) {
        throw 'Initializer container or subnet is not the exact recorded, planned owned target.'
    }
    $active = Get-BpiCleanupResource $Id '2023-05-01'
    if ($null -eq $active) { return $null }
    Assert-BpiCleanupTags $active
    # Reuse deployment's independent CLI validation of tags, exact identity and
    # subnet, single named container, and the pinned Microsoft image.
    $container = Get-BpiPrivateInitializer $config $state "$stem-bootstrap-aci"
    if (-not $container.ContainsKey('restartPolicy') -or $container.restartPolicy -cne 'Never' -or
        -not $container.ContainsKey('osType') -or $container.osType -cne 'Linux' -or
        ($container.ContainsKey('ipAddress') -and $null -ne $container.ipAddress -and
            ($container.ipAddress -isnot [hashtable] -or $container.ipAddress['type'] -cne 'Private'))) {
        throw 'Initializer must retain its planned private Linux topology and Never restart policy.'
    }
    $phase = Get-BpiCleanupProvisioningState $active
    if (-not $container.ContainsKey('provisioningState') -or
        $container.provisioningState -cne $phase -or
        $phase -notin @('Succeeded', 'Failed', 'Canceled', 'Deleting')) {
        throw 'Initializer provisioning is active, unknown, or inconsistent; deletion refused.'
    }
    $instance = $container.containers[0]
    if (-not $instance.ContainsKey('instanceView') -or $instance.instanceView -isnot [hashtable] -or
        -not $instance.instanceView.ContainsKey('currentState') -or
        $instance.instanceView.currentState -isnot [hashtable]) {
        throw 'Initializer terminal execution metadata is missing.'
    }
    $current = $instance.instanceView.currentState
    if ($current['state'] -cne 'Terminated' -or -not $current.ContainsKey('exitCode') -or
        ($current.exitCode -isnot [int] -and $current.exitCode -isnot [long])) {
        throw 'Initializer must have a verified terminal state and integer exit code; running or unknown work is never deleted.'
    }
    return $active
}

function Assert-BpiCleanupInitializerWorkStopped {
    foreach ($item in @(Get-BpiCleanupInventory)) {
        if ($item.type -ine 'Microsoft.Resources/deploymentScripts') { continue }
        $job = Get-BpiCleanupResource $item.id '2023-08-01'
        if ($null -ne $job -and (Get-BpiCleanupProvisioningState $job) -notin @('Succeeded', 'Failed', 'Canceled')) {
            throw 'Legacy initializer deploymentScript work remains active; container deletion refused.'
        }
    }
}

function Remove-BpiCleanupInitializer {
    param([string]$Id)
    $container = Get-BpiCleanupInitializer $Id
    if ($null -eq $container) { return }
    Assert-BpiCleanupInitializerWorkStopped
    if ((Get-BpiCleanupProvisioningState $container) -ine 'Deleting') {
        if (-not (Invoke-BpiCleanupMutation $Id 'Delete verified terminal private initializer ACI' @(
            'rest', '--method', 'delete', '--url',
            "https://management.azure.com${Id}?api-version=2023-05-01"))) { return }
    }
    elseif ($WhatIfPreference) { Write-Host "Already Deleting: $Id (would wait for verified ACI absence)."; return }
    Wait-BpiCleanup "private initializer ACI absence $Id" {
        # Local request markers never substitute for exact Azure absence. If an
        # initializer is recreated or restarts while polling, validation stops us.
        return $null -eq (Get-BpiCleanupInitializer $Id)
    }
    Save-BpiCleanupProgress "private initializer ACI absence confirmed: $Id"
}

function Remove-BpiCleanupInitializerNetwork {
    param([object[]]$Vnets)
    foreach ($item in $Vnets) {
        $vnet = Get-BpiCleanupResource $item.id '2024-07-01'
        if ($null -eq $vnet) { continue }
        Assert-BpiCleanupNetwork $vnet
        foreach ($subnet in $vnet.properties.subnets) {
            if ($subnet.name -cne 'initializer' -or -not $subnet.properties.ContainsKey('natGateway') -or
                $null -eq $subnet.properties.natGateway) { continue }
            $natId = [string]$subnet.properties.natGateway.id
            $expectedNat = $vnet.id -replace '/virtualNetworks/([^/]+)-vnet$', '/natGateways/$1-initializer-nat'
            if ($natId -ine $expectedNat -or $natId -notin $state.resourceIds) {
                throw 'Initializer NAT association is not owned.'
            }
            $nat = Get-BpiCleanupResource $natId '2024-07-01'
            if ($null -eq $nat) { throw 'Attached initializer NAT is absent; metadata is inconsistent.' }
            Assert-BpiCleanupTags $nat
            if ($nat.properties.ContainsKey('subnets') -and
                @($nat.properties.subnets | Where-Object { $_.id -ine $subnet.id }).Count) {
                throw 'Initializer NAT has an unexpected subnet association.'
            }
            if (-not $WhatIfPreference) { Wait-BpiCleanupNetwork $Vnets }
            if (Invoke-BpiCleanupMutation $subnet.id 'Detach owned initializer NAT after SAL and work release' @(
                'network', 'vnet', 'subnet', 'update', '--ids', $subnet.id, '--remove', 'natGateway')) {
                Wait-BpiCleanup "initializer NAT detachment $($subnet.id)" {
                    $current = Get-BpiCleanupResource $subnet.id '2024-07-01'
                    return $null -eq $current -or
                        (-not $current.properties.ContainsKey('natGateway')) -or $null -eq $current.properties.natGateway
                }
                Remove-BpiCleanupResource $natId '2024-07-01'
            }
            elseif ($WhatIfPreference) { Remove-BpiCleanupResource $natId '2024-07-01' }
        }
    }
}

function Invoke-BpiOrderedCleanup {
    $script:CleanupGroupId = "/subscriptions/$($config.subscriptionId)/resourceGroups/$($config.resourceGroupName)"
    if (-not $state.ContainsKey('cleanup')) { $state.cleanup = @{} }
    if ($state.cleanup -isnot [hashtable] -or -not $state.ContainsKey('resourceIds') -or
        $state.resourceIds -isnot [array]) { throw 'Missing or malformed cleanup ownership state.' }
    foreach ($id in $state.resourceIds) {
        if ($id -isnot [string] -or $id -inotmatch "^$([regex]::Escape("$script:CleanupGroupId/providers/"))") {
            throw 'State inventory contains an external or invalid resource ID.'
        }
        if ($id -match '[?#%\\\x00-\x20]') { throw 'State inventory contains a noncanonical resource ID.' }
    }
    $accounts = @($state.resourceIds | Where-Object {
        $_ -imatch '/providers/Microsoft.CognitiveServices/accounts/[^/]+$'
    })
    if ($accounts.Count -gt 1) { throw 'More than one owned Foundry account in state.' }
    $script:CleanupAccountId = if ($accounts.Count) { $accounts[0] } else { '' }
    $script:CleanupSoftId = if ($accounts.Count) {
        "/subscriptions/$($config.subscriptionId)/providers/Microsoft.CognitiveServices/locations/$($config.location)/resourceGroups/$($config.resourceGroupName)/deletedAccounts/$(($accounts[0] -split '/')[-1])"
    } else { '' }
    $group = Get-BpiCleanupResource $script:CleanupGroupId '2022-09-01'
    if ($null -eq $group) {
        # Exact absence is read-only, including for a completed state. Never adopt
        # a new group or turn a local deleted marker into evidence of Azure absence.
        if ($script:CleanupAccountId -and $null -ne (Get-BpiCleanupResource $script:CleanupAccountId)) {
            throw 'Account exists despite absent group; refusing inconsistent metadata.'
        }
        if ($script:CleanupAccountId) {
            if ($ApproveFoundryPurge) {
                Write-Host 'Resource group is already absent. This read-only path never purges residual accounts.'
            }
            $savedPurgeApproval = $ApproveFoundryPurge
            try { $ApproveFoundryPurge = $false; Complete-BpiCleanupAccount }
            finally { $ApproveFoundryPurge = $savedPurgeApproval }
        }
        else { Write-Host 'No recorded account target; residual soft-delete status cannot be determined.' }
        Write-Host 'Exact resource group is already absent. No Azure or local state changes.'
        return
    }
    Assert-BpiOwnership $config $state $group
    if ($state.status -eq 'deleted') { throw 'Resource group reappeared after deleted state; refusing adoption.' }
    $resources = @(Get-BpiCleanupInventory)
    $vnets = @($resources | Where-Object { $_.type -ieq 'Microsoft.Network/virtualNetworks' })
    foreach ($item in $vnets) {
        $vnet = Get-BpiCleanupResource $item.id '2024-07-01'
        if ($null -ne $vnet) { Assert-BpiCleanupNetwork $vnet }
    }
    $initializers = @($resources | Where-Object { $_.type -ieq 'Microsoft.ContainerInstance/containerGroups' })
    foreach ($initializer in $initializers) {
        Get-BpiCleanupInitializer $initializer.id | Out-Null
    }
    if ($initializers.Count) { Assert-BpiCleanupInitializerWorkStopped }
    $projects = @()
    $projectHosts = @()
    $accountHosts = @()
    if ($script:CleanupAccountId) {
        $account = Get-BpiCleanupResource $script:CleanupAccountId
        if ($null -ne $account) {
            Assert-BpiCleanupAccount $account
            $projects = @(Get-BpiCleanupChildren $script:CleanupAccountId 'projects')
            foreach ($project in $projects) {
                if ($project.id -ine "$script:CleanupAccountId/projects/pilot") {
                    throw "Unexpected Foundry project: $($project.id)."
                }
                Assert-BpiCleanupTags $project
                $projectHosts += @(Get-BpiCleanupChildren $project.id 'capabilityHosts')
            }
            $accountHosts = @(Get-BpiCleanupChildren $script:CleanupAccountId 'capabilityHosts')
        }
        # Read the exact residual before any mutation; 403 is not evidence of absence.
        Get-BpiCleanupSoftAccount | Out-Null
    }
    Write-Host 'Order: project hosts -> account hosts -> project -> account -> active/soft status -> terminal initializer ACI -> SAL/subnet release -> initializer NAT -> resource group.'
    foreach ($hostResource in $projectHosts) { Remove-BpiCleanupResource $hostResource.id }
    foreach ($project in $projects) {
        if (-not $WhatIfPreference -and @(Get-BpiCleanupChildren $project.id 'capabilityHosts').Count) {
            throw 'Project capability hosts remain or reappeared; account host deletion refused.'
        }
    }
    foreach ($hostResource in $accountHosts) { Remove-BpiCleanupResource $hostResource.id }
    foreach ($project in $projects) {
        if (-not $WhatIfPreference -and @(Get-BpiCleanupChildren $project.id 'capabilityHosts').Count) {
            throw 'Project capability hosts remain or reappeared; project deletion refused.'
        }
        Remove-BpiCleanupResource $project.id
    }
    if ($script:CleanupAccountId) {
        if (-not $WhatIfPreference -and $null -ne (Get-BpiCleanupResource $script:CleanupAccountId)) {
            if (@(Get-BpiCleanupChildren $script:CleanupAccountId 'projects').Count -or
                @(Get-BpiCleanupChildren $script:CleanupAccountId 'capabilityHosts').Count) {
                throw 'Foundry children remain or reappeared; account deletion refused.'
            }
        }
        Remove-BpiCleanupResource $script:CleanupAccountId -Account
        if (-not $WhatIfPreference) {
            $script:CleanupAbsenceCount = 0
            Wait-BpiCleanup 'three active-account absence observations with exact soft-delete reads' {
                if ($null -ne (Get-BpiCleanupResource $script:CleanupAccountId)) {
                    throw 'Active account reappeared after deletion.'
                }
                Get-BpiCleanupSoftAccount | Out-Null
                $script:CleanupAbsenceCount++
                return $script:CleanupAbsenceCount -ge 3
            }
            $state.cleanup.accountAbsentAt = [DateTime]::UtcNow.ToString('o')
            Save-BpiCleanupProgress 'active account absence confirmed'
        }
        Complete-BpiCleanupAccount
    }
    foreach ($initializer in $initializers) { Remove-BpiCleanupInitializer $initializer.id }
    if ($WhatIfPreference) {
        Write-Host 'WhatIf: would wait for account absence, SAL release and initializer work completion before network changes.'
    }
    else { Wait-BpiCleanupNetwork $vnets }
    Remove-BpiCleanupInitializerNetwork $vnets
    $resources = @(Get-BpiCleanupInventory)
    if (-not $WhatIfPreference) {
        if (@($resources | Where-Object { $_.type -ieq 'Microsoft.CognitiveServices/accounts' }).Count) {
            throw 'An active Foundry account remains; resource group deletion refused.'
        }
        Wait-BpiCleanupNetwork $vnets
    }
    $group = Get-BpiCleanupResource $script:CleanupGroupId '2022-09-01'
    if ($null -ne $group) {
        Assert-BpiOwnership $config $state $group
        $phase = Get-BpiCleanupProvisioningState $group
        if ($phase -ine 'Deleting') {
            if (-not (Invoke-BpiCleanupMutation $script:CleanupGroupId 'Delete isolated resource group' @(
                'group', 'delete', '--subscription', $config.subscriptionId,
                '--name', $config.resourceGroupName, '--yes', '--no-wait'))) { return }
        }
        if ($WhatIfPreference) { return }
        Wait-BpiCleanup "resource group absence $script:CleanupGroupId" {
            $current = Get-BpiCleanupResource $script:CleanupGroupId '2022-09-01'
            if ($null -eq $current) { return $true }
            Assert-BpiOwnership $config $state $current
            $remaining = @(Get-BpiCleanupInventory)
            Write-Host "Remaining resources ($($remaining.Count)): $($remaining.id -join ', ')"
            if ((Get-BpiCleanupProvisioningState $current) -in @('Failed', 'Canceled')) {
                throw 'Resource group deletion failed; cleanup is incomplete.'
            }
            return $false
        }
    }
    if ($script:CleanupAccountId) { Complete-BpiCleanupAccount }
    if (-not $WhatIfPreference -and $ApproveAzureChanges) {
        $state.status = 'deleted'
        $state.deletedAt = [DateTime]::UtcNow.ToString('o')
        Save-BpiCleanupProgress 'resource group absence confirmed'
    }
    Write-Host 'Isolated resource group deletion confirmed. Local state/evidence and azd metadata retained.'
    Write-Host 'No directory identities or external resources/role assignments were changed. Soft-deleted account status is reported separately.'
}
