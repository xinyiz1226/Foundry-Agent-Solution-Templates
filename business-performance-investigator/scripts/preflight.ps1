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
foreach ($id in @('azure.ai.agents', 'azure.ai.projects')) {
    if (@($extensions | Where-Object { $_.id -eq $id }).Count -ne 1) {
        throw "Install the '$id' azd extension before deployment. Preflight will not install extensions."
    }
}
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
foreach ($namespace in @('Microsoft.CognitiveServices', 'Microsoft.App', 'Microsoft.Sql',
        'Microsoft.Network', 'Microsoft.ManagedIdentity', 'Microsoft.Storage',
        'Microsoft.ContainerInstance')) {
    $provider = Invoke-BpiNative az @('provider', 'show', '--subscription',
        $config.subscriptionId, '--namespace', $namespace, '--output', 'json') -Json
    if ($provider.registrationState -ne 'Registered') {
        throw "Provider '$namespace' must be registered by an authorized operator. Preflight will not register it."
    }
}
Write-Host 'Read-only account/provider checks passed. Verify model availability/quota, azd agent extension and operator permissions separately.'
