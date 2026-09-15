#Requires -Version 7.2
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$ConfirmResourceGroup,
    [switch]$ApproveAzureChanges,
    [switch]$ApproveFoundryPurge,
    [ValidateRange(1, 3600)][int]$WaitTimeoutSeconds = 1800,
    [ValidateRange(1, 60)][int]$PollIntervalSeconds = 15
)
. "$PSScriptRoot/common.ps1"
. "$PSScriptRoot/cleanup-common.ps1"
if (-not $WhatIfPreference) { Assert-BpiAzureApproval -Approved:$ApproveAzureChanges }
$config = Read-BpiConfig $ConfigPath
if ($ConfirmResourceGroup -cne $config.resourceGroupName) {
    throw 'ConfirmResourceGroup must exactly match the isolated experiment resource group.'
}
$state = Read-BpiState $config
$script:CleanupCmdlet = $PSCmdlet
Invoke-BpiOrderedCleanup
