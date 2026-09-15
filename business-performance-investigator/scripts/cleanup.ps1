#Requires -Version 7.2
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][string]$ConfigPath,
    [Parameter(Mandatory)][string]$ConfirmResourceGroup,
    [switch]$ApproveAzureChanges
)
. "$PSScriptRoot/common.ps1"
Assert-BpiAzureApproval -Approved:$ApproveAzureChanges
$config = Read-BpiConfig $ConfigPath
if ($ConfirmResourceGroup -cne $config.resourceGroupName) {
    throw 'ConfirmResourceGroup must exactly match the isolated experiment resource group.'
}
$state = Read-BpiState $config
if ($state.status -eq 'deleted') { throw 'This experiment is already recorded as deleted.' }
Get-BpiGroup $config $state | Out-Null
Assert-BpiInventory $state (Get-BpiResources $config)
if ($PSCmdlet.ShouldProcess(
        "$($config.subscriptionId)/$($config.resourceGroupName)",
        'Delete the entire isolated probe resource group and all recorded resources')) {
    Invoke-BpiNative az @('group', 'delete', '--subscription', $config.subscriptionId,
        '--name', $config.resourceGroupName, '--yes') | Out-Null
    $exists = Invoke-BpiNative az @('group', 'exists', '--subscription', $config.subscriptionId,
        '--name', $config.resourceGroupName, '--output', 'json') -Json
    if ($exists) { throw 'Resource group still exists. Cleanup has not completed.' }
    $state.status = 'deleted'
    $state.deletedAt = [DateTime]::UtcNow.ToString('o')
    Save-BpiState $config $state
    Write-Host 'Isolated resource group deletion confirmed. Local evidence/state and azd metadata were retained.'
    Write-Host 'Check Foundry/Entra for any retained agent identity lifecycle artifacts; no directory objects were deleted.'
}
