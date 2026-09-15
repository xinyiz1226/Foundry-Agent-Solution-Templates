#Requires -Version 7.2
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path $PSScriptRoot -Parent
$script:TemplateName = 'business-performance-investigator'

function Invoke-BpiNative {
    param(
        [Parameter(Mandatory)][string]$Command,
        [string[]]$Arguments = @(),
        [switch]$Json
    )
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Required command '$Command' is not installed. See README prerequisites."
    }
    $result = @(& $Command @Arguments)
    if ($LASTEXITCODE -ne 0) {
        throw "'$Command $($Arguments[0])' failed with exit code $LASTEXITCODE. No later stage was run."
    }
    if ($Json) {
        if ($result.Count -eq 0) { throw "'$Command' returned no JSON." }
        return ($result -join "`n" | ConvertFrom-Json -AsHashtable)
    }
    return $result
}

function Read-BpiConfig {
    param([Parameter(Mandatory)][string]$Path)
    $config = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable
    foreach ($key in @('environmentName', 'subscriptionId', 'resourceGroupName',
            'location', 'modelName', 'modelVersion', 'modelSku', 'operatorPrincipalId',
            'operatorPrincipalType')) {
        if (-not $config.ContainsKey($key) -or
            [string]::IsNullOrWhiteSpace([string]$config[$key])) {
            throw "Configuration field '$key' is required."
        }
    }
    foreach ($key in @('subscriptionId', 'operatorPrincipalId')) {
        $id = [guid]::Empty
        if (-not [guid]::TryParse([string]$config[$key], [ref]$id) -or $id -eq [guid]::Empty) {
            throw "'$key' must be an actual, nonzero UUID, not the example placeholder."
        }
    }
    if ($config.environmentName -cnotmatch '^[a-z][a-z0-9-]{2,19}$') {
        throw 'environmentName must contain 3-20 lowercase letters, digits or hyphens, starting with a letter.'
    }
    if ($config.resourceGroupName -cnotmatch '^rg-bpi-[a-z0-9-]{1,60}$') {
        throw 'Use a dedicated new resource group named rg-bpi-<name>. Existing resource groups are not adopted.'
    }
    if ($config.location -cnotmatch '^[a-z][a-z0-9]+$') {
        throw 'location must be an Azure region identifier.'
    }
    if (-not $config.ContainsKey('modelCapacity') -or
        ($config.modelCapacity -isnot [long] -and $config.modelCapacity -isnot [int]) -or
        $config.modelCapacity -lt 1 -or $config.modelCapacity -gt 10) {
        throw 'modelCapacity must be an integer from 1 to 10 for this probe.'
    }
    if ($config.modelSku -notin @('GlobalStandard', 'Standard', 'DataZoneStandard')) {
        throw 'modelSku must be a pay-as-you-go Standard deployment type, not provisioned throughput.'
    }
    if ($config.operatorPrincipalType -notin @('User', 'ServicePrincipal')) {
        throw 'operatorPrincipalType must match the actual User or ServicePrincipal object.'
    }
    return $config
}

function Get-BpiStatePath {
    param([Parameter(Mandatory)][hashtable]$Config)
    return Join-Path $script:ProjectRoot ".artifacts/$($Config.environmentName)/state.json"
}

function Save-BpiState {
    param([Parameter(Mandatory)][hashtable]$Config, [Parameter(Mandatory)][hashtable]$State)
    $path = Get-BpiStatePath $Config
    New-Item -ItemType Directory -Force -Path (Split-Path $path -Parent) | Out-Null
    $State | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $path -Encoding utf8
}

function Read-BpiState {
    param([Parameter(Mandatory)][hashtable]$Config)
    $path = Get-BpiStatePath $Config
    if (-not (Test-Path -LiteralPath $path)) {
        throw "No ownership state at '$path'. Do not adopt or delete an existing resource group."
    }
    $state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json -AsHashtable
    foreach ($key in @('environmentName', 'subscriptionId', 'resourceGroupName')) {
        if ($state[$key] -ne $Config[$key]) { throw "State/config mismatch: $key." }
    }
    if (-not $state.ContainsKey('configuration')) { throw 'State is missing its approved configuration.' }
    foreach ($key in $Config.Keys) {
        if (-not $state.configuration.ContainsKey($key) -or $state.configuration[$key] -cne $Config[$key]) {
            throw "Configuration changed since provisioning: $key. Review before changing the experiment."
        }
    }
    return $state
}

function Assert-BpiOwnership {
    param([hashtable]$Config, [hashtable]$State, [hashtable]$Group)
    if (-not $Group.ContainsKey('tags') -or
        $Group.tags['bpiTemplate'] -ne $script:TemplateName -or
        $Group.tags['bpiEnvironment'] -ne $Config.environmentName -or
        $Group.tags['bpiDeploymentId'] -ne $State.deploymentId) {
        throw 'Resource-group ownership markers do not match local state. Refusing to modify or delete it.'
    }
    $expectedId = "/subscriptions/$($Config.subscriptionId)/resourceGroups/$($Config.resourceGroupName)"
    if ($Group.id -ine $expectedId) { throw 'Resource-group ID does not match the configured scope.' }
}

function Get-BpiGroup {
    param([hashtable]$Config, [hashtable]$State)
    $group = Invoke-BpiNative az @('group', 'show', '--subscription', $Config.subscriptionId,
        '--name', $Config.resourceGroupName, '--output', 'json') -Json
    Assert-BpiOwnership $Config $State $group
    return $group
}

function Get-BpiResources {
    param([hashtable]$Config)
    return @(Invoke-BpiNative az @('resource', 'list', '--subscription', $Config.subscriptionId,
        '--resource-group', $Config.resourceGroupName, '--output', 'json') -Json)
}

function Assert-BpiInventory {
    param([hashtable]$State, [object[]]$Resources)
    if (-not $State.ContainsKey('resourceIds')) { throw 'State is missing its resource inventory.' }
    $unexpected = @($Resources | Where-Object { $_.id -notin $State.resourceIds })
    if ($unexpected.Count -gt 0) {
        throw "Unrecorded resources found; inspect them before proceeding: $($unexpected.id -join ', ')"
    }
}

function Get-BpiOutput {
    param([hashtable]$State, [string]$Name)
    if (-not $State.ContainsKey('outputs') -or -not $State.outputs.ContainsKey($Name) -or
        $null -eq $State.outputs[$Name].value -or
        [string]::IsNullOrWhiteSpace([string]$State.outputs[$Name].value)) {
        throw "Deployment output '$Name' is missing. Infrastructure provisioning may be incomplete."
    }
    return $State.outputs[$Name].value
}

function Assert-BpiAzureApproval {
    param([switch]$Approved)
    if (-not $Approved) {
        throw 'Azure execution is disabled. Review docs/deployment-approval.md, obtain approval, then pass -ApproveAzureChanges.'
    }
}

function Get-BpiAgentPrincipalId {
    param([Parameter(Mandatory)][hashtable]$Agent)
    $candidates = @(
        foreach ($path in @(
            @('instance_identity', 'principal_id'),
            @('identity', 'principalId'),
            @('identity', 'principal_id'),
            @('agent_identity', 'principal_id'),
            @('agentIdentity', 'principalId')
        )) {
            $value = $Agent
            foreach ($key in $path) {
                if ($value -isnot [hashtable] -or -not $value.ContainsKey($key)) {
                    $value = $null
                    break
                }
                $value = $value[$key]
            }
            if ($value) {
                $id = [guid]::Parse([string]$value)
                if ($id -eq [guid]::Empty) { throw 'Agent metadata contains an empty identity.' }
                $id.ToString()
            }
        }
    ) | Select-Object -Unique
    if (@($candidates).Count -ne 1) {
        throw 'Agent metadata must expose one unambiguous principal ID. Inspect the installed azd extension; do not substitute a project identity.'
    }
    return [string](@($candidates)[0])
}

function ConvertFrom-BpiProbeEvidence {
    param([Parameter(Mandatory)][string]$Text)
    $plain = [regex]::Replace($Text, '\x1B\[[0-?]*[ -/]*[@-~]', '')
    $matches = [regex]::Matches($plain, '(?m)BPI_PROBE_RESULT=(\{[^\r\n]*\})')
    if ($matches.Count -ne 1) {
        throw 'Expected exactly one deterministic BPI_PROBE_RESULT marker; a narrative answer is not proof.'
    }
    return ($matches[0].Groups[1].Value | ConvertFrom-Json -AsHashtable)
}

function Assert-BpiProbeEvidence {
    param(
        [Parameter(Mandatory)][hashtable]$Evidence,
        [Parameter(Mandatory)][string]$ExpectedServer,
        [Parameter(Mandatory)][string]$ExpectedDatabase,
        [Parameter(Mandatory)][guid]$ExpectedClientId,
        [Parameter(Mandatory)][string[]]$ExpectedPrivateIps
    )
    if ($Evidence.schema_version -ne 1 -or $Evidence.ok -cne $true) {
        throw 'Agent reported a failed or unsupported SQL probe. Inspect its error code.'
    }
    if ($Evidence.server -ine $ExpectedServer -or $Evidence.database -cne $ExpectedDatabase -or
        $Evidence.authenticated_database -cne $ExpectedDatabase -or
        $Evidence.identity_mode -cne 'managed_identity') {
        throw 'Probe endpoint, database, or credential mode does not match the deployed experiment.'
    }
    if ($Evidence.database_principal -cne 'bpi_probe_agent' -or
        $Evidence.principal_sid_status -cne 'available' -or
        [guid]::Parse($Evidence.database_principal_sid) -ne $ExpectedClientId) {
        throw 'Authenticated database principal does not match the approved runtime identity.'
    }
    if ($Evidence.fixture.probe_id -ne 1 -or
        $Evidence.fixture.label -cne 'private-sql-probe' -or
        $Evidence.fixture.amount -cne '42.00' -or $Evidence.fixture_matches -cne $true) {
        throw 'Probe fixture does not match the expected exact values.'
    }
    if ($Evidence.tls.hostname_verification -cne $true -or
        $Evidence.tls.full_session_encryption -cne $true) {
        throw 'Probe did not use hostname-validated, full-session TLS.'
    }
    if ($ExpectedPrivateIps.Count -eq 0 -or $Evidence.dns.all_candidates_private -cne $true -or
        @($Evidence.dns.candidates).Count -eq 0 -or
        @($Evidence.dns.candidates | Where-Object { $_ -notin $ExpectedPrivateIps }).Count -gt 0) {
        throw 'Agent DNS candidates do not match the deployed SQL private endpoint.'
    }
    if ($Evidence.permission_check.status -cne 'passed') {
        throw 'Permission checks are incomplete or failed; NULL metadata is not a denial.'
    }
    foreach ($key in @('base_select', 'base_insert', 'base_update', 'base_delete',
            'view_select', 'view_insert', 'view_update', 'view_delete', 'view_alter',
            'view_control', 'schema_alter', 'schema_control', 'database_create_table',
            'database_create_view', 'database_alter_any_schema', 'database_control')) {
        $expected = if ($key -eq 'view_select') { 1 } else { 0 }
        if (-not $Evidence.permissions.ContainsKey($key) -or
            $null -eq $Evidence.permissions[$key] -or $Evidence.permissions[$key] -ne $expected) {
            throw "Effective permission '$key' is unexpected or unknown."
        }
    }
}
