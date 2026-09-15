#Requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ConfigPath
)
. "$PSScriptRoot/common.ps1"
$config = Read-BpiConfig $ConfigPath
if ($config.operatorPrincipalType -cne 'User') {
    throw 'This opt-in helper supports an already signed-in user, not a service principal or group.'
}
$account = Invoke-BpiNative az @('account', 'show', '--output', 'json') -Json
if ($account.id -ine $config.subscriptionId -or $account.state -cne 'Enabled') {
    throw 'Azure CLI must already select the approved, enabled subscription. This helper does not switch accounts.'
}
$tenant = [guid]::Empty
if (-not [guid]::TryParse([string]$account.tenantId, [ref]$tenant) -or $tenant -eq [guid]::Empty) {
    throw 'Azure CLI did not return a valid tenant for the approved subscription.'
}
if ($account.user.type -ine 'user') {
    throw 'Azure CLI is not using a signed-in user. This helper will not change identity.'
}
$operator = Invoke-BpiNative az @('ad', 'signed-in-user', 'show',
    '--query', '{id:id}', '--output', 'json') -Json
if ($operator.id -ine $config.operatorPrincipalId) {
    throw 'Azure CLI user object ID does not match the approved operator. No azd profile was changed.'
}

$previous = @{}
foreach ($name in @('AZD_CONFIG_DIR', 'AZURE_SUBSCRIPTION_ID', 'AZURE_TENANT_ID')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:AZD_CONFIG_DIR = Join-Path $script:ProjectRoot '.artifacts\azd-cli-auth'
    $env:AZURE_SUBSCRIPTION_ID = $config.subscriptionId
    $env:AZURE_TENANT_ID = $tenant.ToString()
    Invoke-BpiNative azd @('config', 'set', 'auth.useAzCliAuth', 'true') | Out-Null
}
catch {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    throw
}
Write-Host 'Selected project-isolated azd Azure CLI authentication for the verified operator.'
Write-Host 'Global azd login/configuration was not changed. No login, deployment, or policy changes were made.'
Write-Host 'Use this same PowerShell process for preflight and lifecycle commands; rerun this helper in each new shell.'
