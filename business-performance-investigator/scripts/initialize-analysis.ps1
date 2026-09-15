#Requires -Version 7.2
[CmdletBinding()]
param(
    [switch]$PrepareOnly,
    [switch]$Offline,
    [string]$CacheDirectory = '.artifacts/adventureworks',
    [string]$OutputDirectory = '.artifacts/analysis-initialization',
    [string]$AgentClientId = $env:AGENT_CLIENT_ID,
    [string]$AgentPrincipalId = $env:AGENT_PRINCIPAL_ID
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$CacheDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($CacheDirectory)
$OutputDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)

# The same script runs locally and as the pinned PowerShell container command.
# Only the small public manifest is delivered in ARM; no data or credentials are embedded.
$manifestText = $env:BPI_ANALYSIS_MANIFEST
if ([string]::IsNullOrWhiteSpace($manifestText)) {
    $manifestText = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../data/adventureworks-manifest.json') -Raw
}
$manifest = $manifestText | ConvertFrom-Json -AsHashtable
$expectedHash = '45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f'
$datasetId = 'adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd'
if ($manifest.dataset_id -cne $datasetId -or
    $manifest.source.sha256 -cne '73c27309d17cd30bf5351665401106abf649d9f9a9ecb0c770682f6be965aba8' -or
    $manifest.source.size_bytes -ne 16765004 -or
    $manifest.source.url -cne 'https://github.com/microsoft/sql-server-samples/releases/download/adventureworks/AdventureWorksDW-data-warehouse-install-script.zip' -or
    $manifest.source.archive_name -cne 'AdventureWorksDW-data-warehouse-install-script.zip' -or
    $manifest.currency_filter.key -cne '100' -or $manifest.currency_filter.code -cne 'USD' -or
    $manifest.currency_filter.name -cne 'US Dollar') {
    throw 'AnalysisSnapshot requires the reviewed hash-pinned CurrencyKey 100 source manifest.'
}
$clientId = [guid]::Parse($AgentClientId)
$principalId = [guid]::Parse($AgentPrincipalId)
if ($clientId -eq [guid]::Empty -or $principalId -eq [guid]::Empty) {
    throw 'Nonzero actual runtime client and principal IDs are required, including PrepareOnly.'
}
if (-not $PrepareOnly) {
    if ($env:BPI_INITIALIZATION_MODE -cne 'AnalysisSnapshot' -or $env:BPI_OWNED_NEW_DATABASE -cne 'true' -or
        $env:AZURE_SQL_DATABASE -cne 'pilot' -or
        $env:AZURE_SQL_SERVER -cnotmatch '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]\.database\.windows\.net$') {
        throw 'Live initialization requires explicit owned-new-pilot AnalysisSnapshot deployment context.'
    }
    $initializerId = [guid]::Parse($env:INITIALIZER_CLIENT_ID)
    if ($initializerId -eq [guid]::Empty -or $initializerId -eq $clientId) {
        throw 'A distinct nonzero initializer identity is required.'
    }
    $addresses = @([Net.Dns]::GetHostAddresses($env:AZURE_SQL_SERVER))
    $private = @($addresses | Where-Object {
        $b = $_.GetAddressBytes()
        $b.Length -eq 4 -and ($b[0] -eq 10 -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or
            ($b[0] -eq 192 -and $b[1] -eq 168))
    })
    if ($addresses.Count -eq 0 -or $private.Count -ne $addresses.Count) {
        throw 'SQL DNS did not resolve exclusively to RFC1918; no SQL connection attempted.'
    }
}
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($CacheDirectory)) | Out-Null
$archive = Join-Path $CacheDirectory $manifest.source.archive_name
if (-not (Test-Path -LiteralPath $archive)) {
    if ($Offline) { throw 'Official sample cache missing; Offline never downloads.' }
    $http = [Net.Http.HttpClient]::new()
    $http.Timeout = [TimeSpan]::FromSeconds(120)
    $response = $null
    $stream = $null
    $file = $null
    $part = "$archive.$([guid]::NewGuid().ToString('N')).partial"
    try {
        $response = $http.GetAsync($manifest.source.url, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $response.EnsureSuccessStatusCode() | Out-Null
        if ($response.RequestMessage.RequestUri.Scheme -cne 'https') { throw 'Non-HTTPS source redirect refused.' }
        if ($response.Content.Headers.ContentLength -gt 20000000) { throw 'Source archive exceeds byte limit.' }
        $stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $file = [IO.File]::Open($part, [IO.FileMode]::CreateNew)
        $buffer = [byte[]]::new(65536)
        $total = 0
        $deadline = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(120))
        try {
            while (($count = $stream.ReadAsync($buffer, 0, $buffer.Length, $deadline.Token).GetAwaiter().GetResult()) -gt 0) {
                $total += $count
                if ($total -gt 20000000) { throw 'Source archive exceeds byte limit.' }
                $file.Write($buffer, 0, $count)
            }
        }
        finally { $deadline.Dispose() }
        $file.Dispose(); $file = $null
        if ((Get-Item -LiteralPath $part).Length -ne 16765004 -or
            (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifest.source.sha256) {
            throw 'Downloaded archive hash/size mismatch.'
        }
        Move-Item -LiteralPath $part -Destination $archive
    }
    finally {
        if ($null -ne $file) { $file.Dispose() }
        if ($null -ne $stream) { $stream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        $http.Dispose()
        if (Test-Path -LiteralPath $part) { Remove-Item -LiteralPath $part }
    }
}
if ((Get-Item -LiteralPath $archive).Length -ne 16765004 -or
    (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifest.source.sha256) {
    throw 'Cached archive hash/size mismatch; refusing to overwrite it or download a replacement.'
}

# .NET only: no assumption that Python is installed in the AzurePowerShell image.
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.IO.Compression;
using System.Collections.Generic;
using System.Data;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

public static class BpiAnalysisProjection {
    static readonly CultureInfo C = CultureInfo.InvariantCulture;
    public static readonly string[] Columns = {
        "order_date", "sales_order_number", "product_id", "product_name",
        "territory_id", "territory_name", "sales_amount", "total_product_cost"
    };
    static void Require(bool condition, string message) {
        if (!condition) throw new InvalidDataException(message);
    }
    static void Integer(string value) {
        Require(Regex.IsMatch(value, @"\A(?:0|[1-9][0-9]*)\z"), "Invalid canonical integer");
    }
    static decimal Money(string value) {
        Require(Regex.IsMatch(value, @"\A-?(?:0|[1-9][0-9]*)?\.[0-9]{4}\z"), "Invalid source money");
        decimal result = decimal.Parse(value, C);
        Require(result >= -922337203685477.5808m && result <= 922337203685477.5807m, "Money out of range");
        return result;
    }
    static string Escape(string value) {
        return value.IndexOfAny(new[]{',','"','\r','\n'}) >= 0 ? "\"" + value.Replace("\"","\"\"") + "\"" : value;
    }
    public static string[][] ReadTable(string content, int width, int expectedRows) {
        var rows = new List<string[]>();
        using (var reader = new StringReader(content)) {
            string line;
            while ((line = reader.ReadLine()) != null) {
                string[] row = line.Split('|');
                Require(row.Length == width, "Unexpected source column count");
                rows.Add(row);
            }
        }
        Require(rows.Count == expectedRows, "Unexpected source row count");
        return rows.ToArray();
    }
    static Dictionary<string,string> Dimension(string[][] rows, int column, bool dates) {
        var lookup = new Dictionary<string,string>(StringComparer.Ordinal);
        foreach (var row in rows) {
            Integer(row[0]);
            Require(!lookup.ContainsKey(row[0]), "Duplicate dimension key");
            string label = row[column];
            Require(!String.IsNullOrWhiteSpace(label) && !label.Any(c => c < 32), "Invalid dimension label");
            if (dates) {
                var date = DateTime.ParseExact(label, "yyyy-MM-dd", C);
                Require(date.ToString("yyyyMMdd", C) == row[0], "DateKey mismatch");
            }
            lookup.Add(row[0], label);
        }
        return lookup;
    }
    public static DataTable Project(Dictionary<string,string[][]> tables, string csvPath) {
        var dates = Dimension(tables["DimDate.csv"], 1, true);
        var products = Dimension(tables["DimProduct.csv"], 5, false);
        var territories = Dimension(tables["DimSalesTerritory.csv"], 2, false);
        var currencies = new Dictionary<string,string>(StringComparer.Ordinal);
        foreach (var row in tables["DimCurrency.csv"]) {
            Integer(row[0]);
            Require(!currencies.ContainsKey(row[0]) && Regex.IsMatch(row[1], @"\A[A-Z]{3}\z") &&
                !String.IsNullOrWhiteSpace(row[2]), "Invalid currency identity");
            currencies.Add(row[0], row[1] + "|" + row[2]);
        }
        Require(currencies["100"] == "USD|US Dollar", "CurrencyKey 100 identity mismatch");
        var table = new DataTable();
        Type[] types = {typeof(DateTime),typeof(string),typeof(string),typeof(string),
                        typeof(string),typeof(string),typeof(decimal),typeof(decimal)};
        for (int i = 0; i < Columns.Length; ++i) table.Columns.Add(Columns[i], types[i]);
        var keys = new HashSet<string>(StringComparer.Ordinal);
        var orders = new Dictionary<string,string>(StringComparer.Ordinal);
        decimal sourceSales = 0m, sourceCost = 0m, sales = 0m, cost = 0m;
        var csv = new StringBuilder(String.Join(",", Columns) + "\n");
        foreach (var row in tables["FactInternetSales.csv"]) {
            foreach (int i in new[]{0,1,6,7,9,11}) Integer(row[i]);
            Require(products.ContainsKey(row[0]) && dates.ContainsKey(row[1]) &&
                territories.ContainsKey(row[7]) && currencies.ContainsKey(row[6]), "Missing fact join");
            string date = dates[row[1]];
            Require(row[23] == date + " 00:00:00.000", "Fact OrderDate mismatch");
            Require(Regex.IsMatch(row[8], @"\ASO[0-9]+\z") && int.Parse(row[9], C) >= 1, "Invalid order line");
            Require(keys.Add(row[8] + "|" + row[9]), "Duplicate fact order line");
            string convention = date + "|" + row[7] + "|" + row[6];
            Require(!orders.ContainsKey(row[8]) || orders[row[8]] == convention, "Order convention mismatch");
            orders[row[8]] = convention;
            decimal unit = Money(row[12]), extended = Money(row[13]), unitCost = Money(row[16]);
            decimal lineCost = Money(row[17]), lineSales = Money(row[18]);
            int quantity = int.Parse(row[11], C);
            Require(quantity > 0 && unit * quantity == extended && unitCost * quantity == lineCost &&
                row[14] == "0.0" && row[15] == "0.0" && lineSales == extended, "Fact money convention mismatch");
            sourceSales += lineSales; sourceCost += lineCost;
            if (row[6] != "100") continue;
            string[] projected = {date,row[8],row[0],products[row[0]],row[7],territories[row[7]],row[18],row[17]};
            csv.Append(String.Join(",", projected.Select(Escape))).Append('\n');
            table.Rows.Add(DateTime.ParseExact(date,"yyyy-MM-dd",C),row[8],row[0],products[row[0]],
                row[7],territories[row[7]],lineSales,lineCost);
            sales += lineSales; cost += lineCost;
        }
        Require(keys.Count == 60398 && orders.Count == 27659 &&
            sourceSales == 29358677.2207m && sourceCost == 17277793.5757m, "Source output reconciliation failed");
        Require(table.Rows.Count == 33400 && sales == 14693465.3186m && cost == 8611268.3850m,
            "CurrencyKey 100 reconciliation failed");
        byte[] bytes = new UTF8Encoding(false, true).GetBytes(csv.ToString());
        string hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
        Require(hash == "45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f",
            "Normalized projection hash mismatch");
        File.WriteAllBytes(csvPath, bytes);
        return table;
    }
}
'@
$tables = [Collections.Generic.Dictionary[string,string[][]]]::new([StringComparer]::Ordinal)
$zip = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($archive))
try {
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    [long]$expanded = 0
    if ($zip.Entries.Count -gt 128) { throw 'ZIP exceeds member count limit.' }
    foreach ($entry in $zip.Entries) {
        $expanded += $entry.Length
        if (-not $names.Add($entry.FullName) -or $entry.FullName -match '[/\\:]' -or
            $entry.FullName -in @('.', '..') -or $entry.Length -gt 40000000 -or
            $entry.Length -gt [Math]::Max(1L, $entry.CompressedLength) * 1000 -or
            (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {
            throw 'Unsafe, duplicate or oversized ZIP member.'
        }
    }
    if ($expanded -gt 150000000) { throw 'ZIP exceeds expanded byte limit.' }
    $allowed = @('FactInternetSales.csv', 'DimDate.csv', 'DimProduct.csv', 'DimSalesTerritory.csv',
        'DimCurrency.csv', 'instawdbdw.sql')
    if ($manifest.members.Count -ne $allowed.Count) { throw 'Unexpected manifest members.' }
    foreach ($name in $manifest.members.Keys) {
        if ($name -cnotin $allowed) { throw 'Manifest member outside nonpersonal allow-list.' }
        $entry = $zip.GetEntry($name)
        $expected = $manifest.members[$name]
        if ($null -eq $entry -or $entry.Length -ne $expected.size_bytes) { throw "Missing or wrong-sized member $name." }
        $stream = $entry.Open()
        $memory = [IO.MemoryStream]::new()
        try { $stream.CopyTo($memory); $bytes = $memory.ToArray() }
        finally { $stream.Dispose(); $memory.Dispose() }
        $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
        if ($hash -cne $expected.sha256) { throw "Member hash mismatch: $name." }
        if ($name.EndsWith('.csv')) {
            $text = [Text.UTF8Encoding]::new($false, $true).GetString($bytes)
            $tables.Add($name, [BpiAnalysisProjection]::ReadTable($text, $expected.columns, $expected.rows))
        }
    }
}
finally { $zip.Dispose() }
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($OutputDirectory)) | Out-Null
$data = [BpiAnalysisProjection]::Project($tables, [IO.Path]::GetFullPath((Join-Path $OutputDirectory 'internet_sales.csv')))
$sid = '0x' + [Convert]::ToHexString($clientId.ToByteArray())
$guardSql = @'
SET XACT_ABORT ON;
SET LOCK_TIMEOUT 15000;
IF DB_NAME() <> N'pilot' OR EXISTS (SELECT 1 FROM sys.objects WHERE is_ms_shipped = 0)
    OR EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'bpi_probe_agent')
    THROW 51010, 'AnalysisSnapshot requires an empty owned new pilot; no adoption or overwrite.', 1;
'@
$snapshotSql = 'ALTER DATABASE [pilot] SET ALLOW_SNAPSHOT_ISOLATION ON;'
$createSql = @'
SET XACT_ABORT ON;
SET LOCK_TIMEOUT 15000;
IF EXISTS (SELECT 1 FROM sys.objects WHERE is_ms_shipped = 0)
    THROW 51010, 'Database changed after empty-pilot guard.', 1;
IF SCHEMA_ID(N'reporting') IS NULL EXEC(N'CREATE SCHEMA reporting AUTHORIZATION dbo');
CREATE TABLE reporting.internet_sales_snapshot (
    order_date date NOT NULL,
    sales_order_number nvarchar(32) NOT NULL,
    product_id nvarchar(16) NOT NULL,
    product_name nvarchar(100) NOT NULL,
    territory_id nvarchar(16) NOT NULL,
    territory_name nvarchar(100) NOT NULL,
    sales_amount decimal(19,4) NOT NULL,
    total_product_cost decimal(19,4) NOT NULL
);
CREATE TABLE reporting.pilot_probe (
    probe_id int NOT NULL PRIMARY KEY, label nvarchar(100) NOT NULL, amount decimal(18,2) NOT NULL
);
CREATE TABLE reporting.analysis_snapshot_manifest (
    snapshot_id tinyint NOT NULL PRIMARY KEY CHECK (snapshot_id = 1),
    source_sha256 char(64) NOT NULL,
    dataset_id nvarchar(200) NOT NULL,
    row_count int NOT NULL CHECK (row_count = 33400)
);
INSERT INTO reporting.pilot_probe(probe_id, label, amount) VALUES (1, N'private-sql-probe', 42.00);
'@
$finalizeSql = @"
SET XACT_ABORT ON;
SET LOCK_TIMEOUT 15000;
IF (SELECT COUNT_BIG(*) FROM reporting.internet_sales_snapshot) <> 33400
    OR (SELECT SUM(sales_amount) FROM reporting.internet_sales_snapshot) <> 14693465.3186
    OR (SELECT SUM(total_product_cost) FROM reporting.internet_sales_snapshot) <> 8611268.3850
    OR (SELECT COUNT(DISTINCT sales_order_number) FROM reporting.internet_sales_snapshot) <> 14860
    THROW 51011, 'Loaded snapshot reconciliation failed.', 1;
INSERT INTO reporting.analysis_snapshot_manifest(snapshot_id, source_sha256, dataset_id, row_count)
    VALUES (1, '45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f',
        N'adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd', 33400);
EXEC(N'CREATE VIEW reporting.v_internet_sales AS SELECT order_date, sales_order_number,
    product_id, product_name, territory_id, territory_name, sales_amount, total_product_cost
    FROM reporting.internet_sales_snapshot');
EXEC(N'CREATE VIEW reporting.v_pilot_probe AS SELECT probe_id, label, amount FROM reporting.pilot_probe');
EXEC(N'CREATE VIEW reporting.v_analysis_manifest AS SELECT source_sha256, dataset_id, row_count
    FROM reporting.analysis_snapshot_manifest');
CREATE USER [bpi_probe_agent] WITH SID = $sid, TYPE = E;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'bpi_probe_agent' AND sid = $sid AND type = 'E')
    THROW 51012, 'Runtime principal identity mismatch.', 1;
GRANT CONNECT TO [bpi_probe_agent];
GRANT SELECT ON OBJECT::reporting.v_internet_sales TO [bpi_probe_agent];
GRANT SELECT ON OBJECT::reporting.v_pilot_probe TO [bpi_probe_agent];
GRANT SELECT ON OBJECT::reporting.v_analysis_manifest TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.internet_sales_snapshot TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.pilot_probe TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.v_internet_sales TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.v_pilot_probe TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.analysis_snapshot_manifest TO [bpi_probe_agent];
GRANT VIEW DEFINITION ON OBJECT::reporting.v_analysis_manifest TO [bpi_probe_agent];
EXECUTE AS USER = N'bpi_probe_agent';
IF ISNULL(HAS_PERMS_BY_NAME(N'reporting.v_internet_sales', N'OBJECT', N'SELECT'), 0) <> 1
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.v_analysis_manifest', N'OBJECT', N'SELECT'), 0) <> 1
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.internet_sales_snapshot', N'OBJECT', N'SELECT'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.internet_sales_snapshot', N'OBJECT', N'INSERT'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.internet_sales_snapshot', N'OBJECT', N'UPDATE'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.internet_sales_snapshot', N'OBJECT', N'DELETE'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.internet_sales_snapshot', N'OBJECT', N'ALTER'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.analysis_snapshot_manifest', N'OBJECT', N'SELECT'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.analysis_snapshot_manifest', N'OBJECT', N'INSERT'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.analysis_snapshot_manifest', N'OBJECT', N'UPDATE'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.analysis_snapshot_manifest', N'OBJECT', N'DELETE'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(N'reporting.analysis_snapshot_manifest', N'OBJECT', N'ALTER'), 1) <> 0
    OR ISNULL(HAS_PERMS_BY_NAME(DB_NAME(), N'DATABASE', N'CREATE TABLE'), 1) <> 0
    THROW 51013, 'Runtime least-privilege verification failed.', 1;
IF (SELECT COUNT(*) FROM reporting.v_analysis_manifest) <> 1 OR NOT EXISTS (
    SELECT 1 FROM reporting.v_analysis_manifest
    WHERE source_sha256 = '45d1a25c2b301f730e635fc789fc3ee08c6bb7a9a946159105be7ad00997259f'
        AND dataset_id = N'adventureworksdw-2025-install-snapshot-internet-sales-currencykey-100-usd'
        AND row_count = 33400)
    THROW 51015, 'Runtime manifest evidence verification failed.', 1;
REVERT;
IF (SELECT snapshot_isolation_state FROM sys.databases WHERE database_id = DB_ID()) <> 1
    THROW 51014, 'Snapshot isolation is not ON.', 1;
"@
$evidence = @{
    initialized = $false
    mode = 'AnalysisSnapshot'
    datasetId = $datasetId
    normalizedSha256 = $expectedHash
    sourceArchiveSha256 = $manifest.source.sha256
    rows = 33400
    salesAmount = '14693465.3186'
    totalProductCost = '8611268.3850'
    databaseUser = 'bpi_probe_agent'
    agentClientId = $clientId.ToString()
    agentPrincipalId = $principalId.ToString()
    expectedProbeAmount = '42.00'
    view = 'reporting.v_internet_sales'
    table = 'reporting.internet_sales_snapshot'
    manifestView = 'reporting.v_analysis_manifest'
    manifestTable = 'reporting.analysis_snapshot_manifest'
    snapshotIsolationState = 0
}
foreach ($batch in @{ guard = $guardSql; snapshot = $snapshotSql; create = $createSql; finalize = $finalizeSql }.GetEnumerator()) {
    [IO.File]::WriteAllText([IO.Path]::GetFullPath((Join-Path $OutputDirectory "$($batch.Key).sql")), $batch.Value,
        [Text.UTF8Encoding]::new($false))
}
$evidence | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'preparation.json') -Encoding utf8
if ($PrepareOnly) {
    Write-Output ('BPI_ANALYSIS_PREPARATION=' + ($evidence | ConvertTo-Json -Compress))
    return
}

Install-Module SqlServer -RequiredVersion '22.4.5.1' -Scope CurrentUser `
    -Repository PSGallery -Force -AllowClobber -AcceptLicense -ErrorAction Stop
Import-Module SqlServer -RequiredVersion '22.4.5.1' -ErrorAction Stop
Disable-AzContextAutosave -Scope Process | Out-Null
Connect-AzAccount -Identity -AccountId $initializerId.ToString() | Out-Null
$token = Get-AzAccessToken -ResourceUrl 'https://database.windows.net/'
$connection = [Microsoft.Data.SqlClient.SqlConnection]::new(
    "Server=tcp:$($env:AZURE_SQL_SERVER),1433;Database=pilot;Encrypt=True;TrustServerCertificate=False;Connect Timeout=30;Application Name=BpiAnalysisInitializer")
$connection.AccessToken = if ($token.Token -is [Security.SecureString]) {
    [Net.NetworkCredential]::new('', $token.Token).Password
} else { [string]$token.Token }
$transaction = $null
function Invoke-AnalysisBatch([string]$Sql, $Transaction = $null) {
    $command = $connection.CreateCommand()
    try {
        $command.CommandText = $Sql
        $command.CommandTimeout = 60
        if ($null -ne $Transaction) { $command.Transaction = $Transaction }
        $command.ExecuteNonQuery() | Out-Null
    }
    finally { $command.Dispose() }
}
try {
    $connection.Open()
    Invoke-AnalysisBatch $guardSql
    Invoke-AnalysisBatch $snapshotSql
    $transaction = $connection.BeginTransaction()
    Invoke-AnalysisBatch $createSql $transaction
    $bulk = [Microsoft.Data.SqlClient.SqlBulkCopy]::new($connection,
        [Microsoft.Data.SqlClient.SqlBulkCopyOptions]::CheckConstraints, $transaction)
    try {
        $bulk.DestinationTableName = '[reporting].[internet_sales_snapshot]'
        $bulk.BulkCopyTimeout = 120
        $bulk.BatchSize = 5000
        foreach ($column in [BpiAnalysisProjection]::Columns) { $bulk.ColumnMappings.Add($column, $column) | Out-Null }
        $bulk.WriteToServer($data)
    }
    finally { $bulk.Dispose() }
    Invoke-AnalysisBatch $finalizeSql $transaction
    $transaction.Commit()
    $transaction.Dispose(); $transaction = $null
    $evidence.initialized = $true
    $evidence.snapshotIsolationState = 1
    Write-Output ('BPI_ANALYSIS_INITIALIZER_RESULT=' + ($evidence | ConvertTo-Json -Compress))
}
finally {
    if ($null -ne $transaction) {
        try { $transaction.Rollback() } finally { $transaction.Dispose() }
    }
    $connection.Dispose()
    $data.Dispose()
}
