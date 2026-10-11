param(
    [Parameter(Mandatory = $false)]
    [string]$DataDir = "$env:LOCALAPPDATA\Postgres\data",

    [Parameter(Mandatory = $false)]
    [int]$Port = 5432,

    [switch]$NoSuite
)

<#
PostgreSQL production deployment test (real server, detached).

Owns the server lifecycle OUTSIDE the terminal process tree: starting
postgres from inside a slaved terminal made every spawned backend abort with
STATUS_DLL_INIT_FAILED (backends inherited console handles from a killed
launcher). Launching via WMI Win32_Process.Create detaches the server so it
boots and serves backends cleanly.

Runs `scripts/postgres_deploytest.py` (schema bootstrap + canonical-table
asserts + full pytest on PostgreSQL). Binaries expected at
`<DataDir parent>\pgsql\bin` (EDB portable *-binaries.zip layout; nothing is
installed as a Windows service).

Usage:
    powershell -ExecutionPolicy Bypass -File scripts\postgres_prod_test.ps1
    powershell -ExecutionPolicy Bypass -File scripts\postgres_prod_test.ps1 -Port 55432 -DataDir "$env:LOCALAPPDATA\Postgres\data16" -NoSuite
#>

$ErrorActionPreference = "Stop"

$Bin = Join-Path (Split-Path $DataDir -Parent) "pgsql\bin"
$PgCtl = Join-Path $Bin "pg_ctl.exe"
$Initdb = Join-Path $Bin "initdb.exe"
$Psql = Join-Path $Bin "psql.exe"
$Log = Join-Path $DataDir "pg.log"

if (-not (Test-Path $Initdb)) {
    throw "PostgreSQL binaries not found under '$Bin' (extract the EDB *-binaries.zip there first)"
}

Write-Host "== postgres-prod-test: DataDir=$DataDir Port=$Port"

if (-not (Test-Path (Join-Path $DataDir "PG_VERSION"))) {
    Write-Host ">> initdb (fresh cluster)"
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
    & $Initdb -D $DataDir --auth=trust --auth-local=trust --encoding=utf8 -U postgres --locale=C
    if ($LASTEXITCODE -ne 0) { throw "initdb failed with exit $LASTEXITCODE" }
}

$listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$startedByUs = $false
if (-not $listening) {
    Write-Host ">> starting server detached (WMI)"
    $cmdline = ('"{0}" -D "{1}" -l "{2}" -o "-h 127.0.0.1 -p {3}" -w start' -f $PgCtl, $DataDir, $Log, $Port)
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmdline }
    if ($r.ReturnValue -ne 0) { throw "WMI launch failed with return code $($r.ReturnValue)" }
    $startedByUs = $true
}

try {
    Write-Host ">> waiting for readiness"
    $ready = $false
    foreach ($i in 1..90) {
        $out = & $Psql -h 127.0.0.1 -p $Port -U postgres -d postgres -tAc "SELECT 1" 2>$null
        if ($out -match "1") { $ready = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "server did not become ready in 180s (see $Log)" }

    $pyArgs = @("scripts\postgres_deploytest.py", "--port", "$Port")
    if ($NoSuite) { $pyArgs += "--no-suite" }

    Write-Host ">> running deployment verification"
    & python @pyArgs
    $rc = $LASTEXITCODE
    Write-Host "== postgres-prod-test: exit $rc"
    exit $rc
}
finally {
    if ($startedByUs) {
        Write-Host ">> stopping server"
        & $PgCtl -D $DataDir -m fast -w stop
    }
}
