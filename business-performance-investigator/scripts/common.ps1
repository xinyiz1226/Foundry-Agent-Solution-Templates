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
            'location', 'modelName', 'operatorPrincipalId',
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
    Get-BpiModelConfiguration $config | Out-Null
    if ($config.operatorPrincipalType -notin @('User', 'ServicePrincipal')) {
        throw 'operatorPrincipalType must match the actual User or ServicePrincipal object.'
    }
    return $config
}

function Get-BpiModelConfiguration {
    param([Parameter(Mandatory)][hashtable]$Config)
    $mode = if ($Config.ContainsKey('modelMode')) { [string]$Config.modelMode } else { 'new' }
    $api = if ($Config.ContainsKey('modelApi')) { [string]$Config.modelApi } else { 'responses' }
    if ($mode -cnotin @('new', 'existing')) { throw 'modelMode must be new or existing.' }
    if ($api -cnotin @('responses', 'chat_completions')) {
        throw 'modelApi must be responses or chat_completions.'
    }
    if ($Config.modelName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw 'modelName must be an Azure model deployment name.'
    }
    if ($mode -ceq 'new') {
        foreach ($key in @('modelVersion', 'modelSku')) {
            if (-not $Config.ContainsKey($key) -or [string]::IsNullOrWhiteSpace([string]$Config[$key])) {
                throw "Configuration field '$key' is required when modelMode is new."
            }
        }
        if (-not $Config.ContainsKey('modelCapacity') -or
            ($Config.modelCapacity -isnot [long] -and $Config.modelCapacity -isnot [int]) -or
            $Config.modelCapacity -lt 1 -or $Config.modelCapacity -gt 10) {
            throw 'modelCapacity must be an integer from 1 to 10 for this probe.'
        }
        if ($Config.modelSku -notin @('GlobalStandard', 'Standard', 'DataZoneStandard')) {
            throw 'modelSku must be a pay-as-you-go Standard deployment type, not provisioned throughput.'
        }
        foreach ($key in @('existingModelResourceId', 'modelEndpoint')) {
            if ($Config.ContainsKey($key) -and -not [string]::IsNullOrEmpty([string]$Config[$key])) {
                throw "Do not set '$key' when modelMode is new."
            }
        }
        return @{
            mode = $mode; api = $api; endpoint = ''; deployModel = $true
            version = $Config.modelVersion; sku = $Config.modelSku; capacity = $Config.modelCapacity
        }
    }
    foreach ($key in @('existingModelResourceId', 'modelEndpoint', 'modelApi')) {
        if (-not $Config.ContainsKey($key) -or [string]::IsNullOrWhiteSpace([string]$Config[$key])) {
            throw "Configuration field '$key' is required when modelMode is existing."
        }
    }
    foreach ($key in @('modelVersion', 'modelSku', 'modelCapacity')) {
        if ($Config.ContainsKey($key)) {
            throw "Do not configure '$key' for an externally managed model deployment."
        }
    }
    $resourceId = [string]$Config.existingModelResourceId
    $pattern = '^/subscriptions/(?<subscription>[0-9a-f-]{36})/resourceGroups/(?<group>[^/\x00-\x1f]+)/providers/Microsoft.CognitiveServices/accounts/(?<account>[a-z0-9][a-z0-9-]{1,63})/deployments/(?<deployment>[A-Za-z0-9][A-Za-z0-9._-]{0,127})$'
    if ($resourceId -notmatch $pattern) { throw 'existingModelResourceId must identify an Azure Cognitive Services model deployment.' }
    $parts = $Matches.Clone()
    if ($parts.subscription -ine $Config.subscriptionId) {
        throw 'This probe only reuses models in the explicitly selected subscription.'
    }
    if ($parts.group -ieq $Config.resourceGroupName) {
        throw 'An existing shared model must be outside the disposable experiment resource group.'
    }
    if ($parts.deployment -cne $Config.modelName) {
        throw 'modelName must match the deployment name in existingModelResourceId.'
    }
    $endpoint = [string]$Config.modelEndpoint
    $uri = $null
    if ($endpoint -ne $endpoint.Trim() -or $endpoint -match '[\x00-\x1f]' -or
        -not [uri]::TryCreate($endpoint, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -cne 'https' -or $uri.Port -ne 443 -or $uri.UserInfo -or
        $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -cnotmatch '^/openai/v1/?$' -or
        $uri.DnsSafeHost -inotin @("$($parts.account).openai.azure.com", "$($parts.account).services.ai.azure.com")) {
        throw 'modelEndpoint must be the matching Azure account HTTPS /openai/v1 endpoint, without credentials or query parameters.'
    }
    return @{
        mode = $mode; api = $api; endpoint = $endpoint.TrimEnd('/') + '/'; deployModel = $false
        resourceId = $resourceId; accountId = $resourceId.Substring(0, $resourceId.LastIndexOf('/deployments/', [StringComparison]::OrdinalIgnoreCase))
        version = ''; sku = ''; capacity = 1
    }
}

function Get-BpiExistingModel {
    param([Parameter(Mandatory)][hashtable]$Config)
    $model = Get-BpiModelConfiguration $Config
    if ($model.mode -ne 'existing') { throw 'Existing-model checks require modelMode existing.' }
    $deployment = Invoke-BpiNative az @('resource', 'show', '--ids', $model.resourceId,
        '--api-version', '2025-04-01-preview', '--output', 'json') -Json
    if ($deployment.id -ine $model.resourceId -or $deployment.name -cne $Config.modelName -or
        $deployment.properties.provisioningState -cne 'Succeeded') {
        throw 'The existing model deployment is missing, mismatched or not successfully provisioned.'
    }
    $capability = if ($model.api -eq 'chat_completions') { 'chatCompletion' } else { 'responses' }
    if (-not $deployment.properties.ContainsKey('capabilities') -or
        [string]$deployment.properties.capabilities[$capability] -ine 'true') {
        throw "The existing deployment does not advertise '$capability'. Verify the chosen API before deployment."
    }
    $account = Invoke-BpiNative az @('resource', 'show', '--ids', $model.accountId,
        '--api-version', '2025-04-01-preview', '--output', 'json') -Json
    if ($account.id -ine $model.accountId -or $account.properties.publicNetworkAccess -cne 'Enabled') {
        throw 'Existing-model reuse currently requires its approved public Entra-authenticated endpoint; no shared network settings will be changed.'
    }
    if ($account.properties.ContainsKey('networkAcls') -and $null -ne $account.properties.networkAcls -and
        $account.properties.networkAcls.defaultAction -cne 'Allow') {
        throw 'The shared model account restricts outbound callers. Obtain an approved route; preflight will not modify its firewall.'
    }
    return @{
        resourceId = $deployment.id; endpoint = $model.endpoint; api = $model.api
        name = $deployment.properties.model.name; version = $deployment.properties.model.version
        accountLocation = $account.location
    }
}

function Assert-BpiSqlAvailability {
    param([Parameter(Mandatory)][hashtable]$Capabilities)
    $available = @('Available', 'Default')
    if ($Capabilities.status -cnotin $available) {
        throw 'SQL provisioning is not available in the selected region. Review SQL capabilities with the subscription owner; no resources were created.'
    }
    $editions = @(
        foreach ($version in $Capabilities.supportedServerVersions) {
            if ($version.name -ceq '12.0' -and $version.status -cin $available) {
                foreach ($edition in $version.supportedEditions) {
                    if ($edition.name -ceq 'Basic' -and $edition.status -cin $available) { $edition }
                }
            }
        }
    )
    if ($editions.Count -eq 0) { throw 'SQL Basic on server version 12.0 is not available in the selected region.' }
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
    param([hashtable]$State, [string]$Name, [switch]$AllowEmpty)
    if (-not $State.ContainsKey('outputs') -or -not $State.outputs.ContainsKey($Name) -or
        $null -eq $State.outputs[$Name].value -or
        (-not $AllowEmpty -and [string]::IsNullOrWhiteSpace([string]$State.outputs[$Name].value))) {
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

function Assert-BpiExtensions {
    param([Parameter(Mandatory)][AllowEmptyCollection()][hashtable[]]$Extensions)
    $minimumVersions = @{
        'azure.ai.agents' = '1.0.0-beta.4'
        'azure.ai.projects' = '1.0.0-beta.1'
    }
    foreach ($id in $minimumVersions.Keys) {
        $matches = @($Extensions | Where-Object { $_.id -eq $id })
        if ($matches.Count -ne 1 -or
            -not $matches[0].ContainsKey('installedVersion') -or
            [string]::IsNullOrWhiteSpace([string]$matches[0].installedVersion)) {
            throw "Install the '$id' azd extension. A catalog entry is not an installed extension."
        }
        try {
            $installed = [semver]$matches[0].installedVersion
        }
        catch {
            throw "The '$id' installed version is not valid semantic version metadata."
        }
        if ($installed -lt [semver]$minimumVersions[$id]) {
            throw "Update '$id' to at least $($minimumVersions[$id]); installed version is $installed."
        }
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
