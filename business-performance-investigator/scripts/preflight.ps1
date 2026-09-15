#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$ConfigPath = '',
    [switch]$CheckAzure
)
. "$PSScriptRoot/common.ps1"

foreach ($command in @('az', 'azd')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing '$command'. Install the prerequisites from README before deployment."
    }
}
Invoke-BpiNative az @('version', '--output', 'json') -Json | Out-Null
Invoke-BpiNative azd @('version') | Write-Host
$extensions = @(Invoke-BpiNative azd @('extension', 'list', '--output', 'json') -Json)
Assert-BpiExtensions $extensions
if (-not $ConfigPath) {
    if ($CheckAzure) { throw '-ConfigPath is required with -CheckAzure.' }
    Write-Host 'Local CLI checks passed. No Azure login, quota, or connectivity was checked.'
    return
}
$config = Read-BpiConfig $ConfigPath
if (-not $CheckAzure) {
    Write-Host 'Local configuration and CLI checks passed. Cloud readiness remains unverified.'
    return
}
$account = Invoke-BpiNative az @('account', 'show', '--subscription',
    $config.subscriptionId, '--output', 'json') -Json
if ($account.state -ne 'Enabled') { throw 'Selected Azure subscription is not enabled.' }
foreach ($context in @('configured-tenant', 'default')) {
    foreach ($scope in @('https://management.azure.com/.default', 'https://ai.azure.com/.default')) {
        Write-Host "Checking $context azd token acquisition for $scope."
        $arguments = @('auth', 'token', '--scope', $scope, '--output', 'json', '--no-prompt')
        if ($context -eq 'configured-tenant') {
            $arguments += @('--tenant-id', $account.tenantId)
        }
        try {
            $token = Invoke-BpiNative azd $arguments -Json
            if ($token -isnot [hashtable] -or -not $token.ContainsKey('token') -or
                [string]::IsNullOrWhiteSpace([string]$token.token)) {
                throw 'azd did not return a usable access token. Resolve tenant authentication before provisioning.'
            }
        }
        finally {
            $token = $null
        }
    }
}
if ((Get-BpiModelConfiguration $config).mode -eq 'existing') {
    Get-BpiExistingModel $config | Out-Null
}
foreach ($namespace in @('Microsoft.CognitiveServices', 'Microsoft.App', 'Microsoft.Sql',
        'Microsoft.Network', 'Microsoft.ManagedIdentity', 'Microsoft.Storage',
        'Microsoft.ContainerInstance')) {
    $provider = Invoke-BpiNative az @('provider', 'show', '--subscription',
        $config.subscriptionId, '--namespace', $namespace, '--output', 'json') -Json
    if ($provider.registrationState -ne 'Registered') {
        throw "Provider '$namespace' must be registered by an authorized operator. Preflight will not register it."
    }
}
$sqlCapabilities = Invoke-BpiNative az @('rest', '--method', 'get', '--url',
    "https://management.azure.com/subscriptions/$($config.subscriptionId)/providers/Microsoft.Sql/locations/$($config.location)/capabilities?api-version=2023-08-01",
    '--output', 'json') -Json
Assert-BpiSqlAvailability $sqlCapabilities
Write-Host 'Read-only account/azd token/provider/SQL availability checks passed. Model invocation, runtime identity permissions and actual deployment capacity remain unverified.'
