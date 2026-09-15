#Requires -Version 7.2
[CmdletBinding()]
param(
    [string]$PythonPath = '',
    [string]$BicepPath = ''
)
. "$PSScriptRoot/common.ps1"
if (-not $PythonPath) {
    $candidate = Join-Path $script:ProjectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path $candidate)) {
        $candidate = Join-Path $script:ProjectRoot '.venv/bin/python'
    }
    if (-not (Test-Path $candidate)) {
        throw 'Create a Python 3.13 virtual environment and install agent requirements first; see README.'
    }
    $PythonPath = $candidate
}
if (-not $BicepPath) {
    $bicep = Get-Command bicep -ErrorAction SilentlyContinue
    if (-not $bicep) { throw 'Install the standalone Bicep CLI or supply -BicepPath. No Azure login is needed.' }
    $BicepPath = $bicep.Source
}
$artifacts = Join-Path $script:ProjectRoot '.artifacts'
New-Item -ItemType Directory -Force -Path $artifacts | Out-Null
$report = @{
    timestamp = [DateTime]::UtcNow.ToString('o')
    scope = 'local-only'
    cloudValidation = 'not_run'
    checks = @()
    status = 'failed'
}
$previousBicep = $env:BICEP_CLI
$env:BICEP_CLI = $BicepPath
Push-Location $script:ProjectRoot
try {
    Invoke-BpiNative $PythonPath @('-m', 'pip', 'check') | Write-Host
    $report.checks += 'dependency-consistency'
    Invoke-BpiNative $PythonPath @('-m', 'unittest', 'discover', '-s', 'tests', '-v') | Write-Host
    $report.checks += 'unit-and-lifecycle-contracts'
    foreach ($entry in @('main', 'bootstrap', 'analysis-bootstrap')) {
        Invoke-BpiNative $BicepPath @('build', "infra-bicep/$entry.bicep",
            '--outfile', (Join-Path $artifacts "$entry.json")) | Write-Host
        $report.checks += "bicep-$entry"
    }
    $report.status = 'passed'
}
finally {
    Pop-Location
    $env:BICEP_CLI = $previousBicep
    $report | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath (Join-Path $artifacts 'local-validation.json') -Encoding utf8
}
Write-Host 'Local checks passed. Hosted runtime, Azure permissions, private connectivity and cleanup are NOT verified.'
