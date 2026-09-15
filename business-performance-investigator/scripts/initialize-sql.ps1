# Executed only by the private initializer container as its initializer identity.
#Requires -Version 7.2
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

foreach ($name in @('AZURE_SQL_SERVER', 'AZURE_SQL_DATABASE', 'INITIALIZER_CLIENT_ID',
        'AGENT_CLIENT_ID', 'AGENT_PRINCIPAL_ID')) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Required initializer environment variable '$name' is missing."
    }
}
if ($env:AZURE_SQL_SERVER -cnotmatch '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]\.database\.windows\.net$') {
    throw 'Expected the normal Azure SQL server hostname, not a private IP or privatelink hostname.'
}
if ($env:AZURE_SQL_DATABASE -cnotmatch '^[a-zA-Z0-9_-]{1,128}$') {
    throw 'Invalid probe database name.'
}
$agentClientId = [guid]::Parse($env:AGENT_CLIENT_ID)
$agentPrincipalId = [guid]::Parse($env:AGENT_PRINCIPAL_ID)
$initializerClientId = [guid]::Parse($env:INITIALIZER_CLIENT_ID)
if ($agentClientId -eq [guid]::Empty -or $agentPrincipalId -eq [guid]::Empty -or
    $agentClientId -eq $initializerClientId) {
    throw 'A distinct, nonzero runtime agent identity is required.'
}
$addresses = @([Net.Dns]::GetHostAddresses($env:AZURE_SQL_SERVER))
$privateAddresses = @($addresses | Where-Object {
    $b = $_.GetAddressBytes()
    $b.Length -eq 4 -and ($b[0] -eq 10 -or
        ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or
        ($b[0] -eq 192 -and $b[1] -eq 168))
})
if ($addresses.Count -eq 0 -or $privateAddresses.Count -ne $addresses.Count) {
    throw 'SQL DNS did not resolve exclusively to RFC1918 addresses. No bootstrap was attempted.'
}

Install-Module SqlServer -RequiredVersion '22.4.5.1' -Scope CurrentUser `
    -Repository PSGallery -Force -AllowClobber -AcceptLicense -ErrorAction Stop
Import-Module SqlServer -RequiredVersion '22.4.5.1' -ErrorAction Stop
Disable-AzContextAutosave -Scope Process | Out-Null
Connect-AzAccount -Identity -AccountId $initializerClientId.ToString() | Out-Null
$token = Get-AzAccessToken -ResourceUrl 'https://database.windows.net/'

# Service-principal database SIDs use the application/client ID, not its object ID.
$sid = '0x' + [Convert]::ToHexString($agentClientId.ToByteArray())
$query = @"
SET XACT_ABORT ON;
BEGIN TRANSACTION;
IF SCHEMA_ID(N'reporting') IS NULL EXEC(N'CREATE SCHEMA reporting AUTHORIZATION dbo');
IF OBJECT_ID(N'reporting.pilot_probe', N'U') IS NULL
    CREATE TABLE reporting.pilot_probe (
        probe_id int NOT NULL PRIMARY KEY,
        label nvarchar(100) NOT NULL,
        amount decimal(18,2) NOT NULL
    );
IF NOT EXISTS (SELECT 1 FROM reporting.pilot_probe WHERE probe_id = 1)
    INSERT INTO reporting.pilot_probe(probe_id, label, amount)
    VALUES (1, N'private-sql-probe', 42.00);
IF EXISTS (SELECT 1 FROM reporting.pilot_probe
           WHERE probe_id <> 1 OR label <> N'private-sql-probe' OR amount <> 42.00)
    THROW 51000, 'Unexpected probe data; refusing to overwrite it.', 1;
EXEC(N'CREATE OR ALTER VIEW reporting.v_pilot_probe AS
       SELECT probe_id, label, amount FROM reporting.pilot_probe');
IF DATABASE_PRINCIPAL_ID(N'bpi_probe_agent') IS NULL
    CREATE USER [bpi_probe_agent] WITH SID = $sid, TYPE = E;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals
               WHERE name = N'bpi_probe_agent' AND sid = $sid AND type = 'E')
    THROW 51001, 'Existing runtime principal does not match the approved identity.', 1;
GRANT CONNECT TO [bpi_probe_agent];
GRANT SELECT ON OBJECT::reporting.v_pilot_probe TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.pilot_probe TO [bpi_probe_agent];
COMMIT TRANSACTION;
"@
Invoke-Sqlcmd -ServerInstance $env:AZURE_SQL_SERVER -Database $env:AZURE_SQL_DATABASE `
    -AccessToken $token.Token -Query $query -Encrypt Mandatory `
    -ConnectionTimeout 30 -QueryTimeout 60 -AbortOnError -DisableVariables `
    -DisableCommands -ErrorAction Stop | Out-Null

$result = @{
    initialized = $true
    databaseUser = 'bpi_probe_agent'
    agentClientId = $agentClientId.ToString()
    agentPrincipalId = $agentPrincipalId.ToString()
    expectedProbeAmount = '42.00'
}
Write-Output ('BPI_INITIALIZER_RESULT=' + ($result | ConvertTo-Json -Compress))
