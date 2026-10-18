# Live wiring smoke — boots the real FastAPI app with uvicorn and drives it
# with the actual `tradraig` console (which talks HTTP, the same path a
# browser dashboard uses). Proves: server boots, startup has no surprises (no
# on_event startup hooks), routing serves the recent surface (governance / ops
# feed / copy), and the console client parses every JSON response.
# Non-destructive: persistence disabled, Redis mirror off.
#
# It prefers :8000 but does NOT require it: a 24/7 host keeps a live backend
# there, and the supervisor will re-take the port mid-run, which used to abort
# this gate and make VERIFY_ALL report a warning dressed as a pass. When :8000
# is taken the smoke runs isolated on the next free port and says so.
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\smoke_live.ps1
$ErrorActionPreference = "Stop"

$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PY   = "python"

function Get-FreePort([int[]]$candidates) {
    foreach ($candidate in $candidates) {
        if (Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue) {
            continue
        }
        $listener = $null
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
            # .NET leaves ExclusiveAddressUse false by default, which lets the bind
            # SUCCEED against a port another process is already serving. Without
            # this the smoke silently attaches to the live 24/7 backend and runs
            # its "non-destructive" steps against production data.
            $listener.ExclusiveAddressUse = $true
            $listener.Start()
            return $candidate
        } catch { }
        finally { if ($listener) { try { $listener.Stop() } catch { } } }
    }
    return $null
}

$API_PORT = Get-FreePort @(8000, 8010, 8020, 8030, 8040)
if ($null -eq $API_PORT) { Write-Output "ABORT: no free port for the smoke server"; exit 2 }
if ($API_PORT -ne 8000) {
    Write-Output "note: :8000 is owned by the live 24/7 backend; smoke runs isolated on :$API_PORT"
}
$env:API_PORT = "$API_PORT"

$env:TRADERAIG_PERSIST = "0"
$env:TRADERAIG_STATE_REDIS = "0"
# Pin enforcement off for the isolated server. The host's .env may turn
# TRADERAIG_AUTH on, which makes a write step (change submit) need a human
# session the console does not carry — the smoke is a wiring test, not an auth
# test (that is tests/test_operations/test_auth.py), so it runs ungated. A
# process env var wins over .env (dotenv does not override it).
$env:TRADERAIG_AUTH = "0"

$logOut = Join-Path $env:TEMP "tradraig-smoke-server.out.log"
$logErr = Join-Path $env:TEMP "tradraig-smoke-server.err.log"
$server = Start-Process -FilePath $PY -ArgumentList @(
    "-m", "uvicorn", "operations.api:app",
    "--host", "127.0.0.1", "--port", "$API_PORT", "--log-level", "warning"
) -WorkingDirectory $ROOT -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru

$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 250
    try {
        $h = Invoke-RestMethod -Uri "http://127.0.0.1:$API_PORT/health" -TimeoutSec 2
        if ($h.status -eq "ok") { $healthy = $true; break }
    } catch { }
}

$results = [System.Collections.Generic.List[string]]::new()
$resultLog = Join-Path $env:TEMP "tradraig-smoke-results.txt"
Remove-Item $resultLog -ErrorAction SilentlyContinue
function Step([string]$label, [string]$cmdLine, [int[]]$okCodes) {
    $argsList = @($cmdLine -split "\s+")
    $out = & $PY (Join-Path $ROOT "tools\tradraig.py") @argsList 2>&1
    $rc = $LASTEXITCODE
    $retried = $false
    if (-not ($okCodes -contains $rc)) {
        Start-Sleep -Milliseconds 1500
        $out = & $PY (Join-Path $ROOT "tools\tradraig.py") @argsList 2>&1
        $rc = $LASTEXITCODE
        $retried = $true
    }
    $ok = if ($okCodes -contains $rc) { $true } else { $false }
    $tag = if ($retried) { " (retried)" } else { "" }
    $results.Add(("{0} | {1} | return {2}{3}" -f $(if ($ok) { "PASS" } else { "FAIL" }), $label, $rc, $tag))
    Add-Content -Path $resultLog -Value ("{0} | {1} | command: tradraig {2}{3}" -f $(if ($ok) { "PASS" } else { "FAIL" }), $label, $cmdLine, $tag)
    foreach ($line in ($out | Select-Object -First 3)) { Add-Content -Path $resultLog -Value ("      " + $line) }
    Write-Output ("{0}{1}  {2}" -f $(if ($ok) { "[ok]" } else { "[!!]" }), $tag, $label)
    if (-not $ok) { $out | ForEach-Object { Write-Output ("      $_") } }
    return $ok
}

try {
    if (-not $healthy) {
        Write-Output "ABORT: server did not become healthy on :$API_PORT"
        if (Test-Path $logErr) { Get-Content $logErr -Tail 15 }
        exit 1
    }
    Write-Output "server healthy on :$API_PORT"

    Step "probe /system/health via console status"  "status"                    @(0)   | Out-Null
    Step "probe all dashboard read-only feeds"      "board --json"              @(0)   | Out-Null
    Step "submit a change request (kind=config)"    "change submit --kind config --target risk.max_daily_loss_pct --reason smoke" @(0) | Out-Null
    Step "list change requests (pending)"           "change list --status pending" @(0) | Out-Null
    Step "tail operations event feed (after=0)"     "events --after 0"          @(0)   | Out-Null
    Step "copy-engine follower snapshot (json)"     "copy --json"               @(0)   | Out-Null
    Step "backup dry target (isolated dir)"         "backup --out $env:TEMP\tradraig-smoke-backup --json" @(0) | Out-Null

    $fails = @($results | Where-Object { $_ -like "FAIL*" })
    Write-Output ""
    Write-Output ("SMOKE: {0} steps, {1} passed, {2} failed" -f $results.Count, ($results.Count - $fails.Count), $fails.Count)
    if ($fails.Count -gt 0) { $fails | ForEach-Object { Write-Output "  $_" } }
    exit $(if ($fails.Count -eq 0) { 0 } else { 1 })
}
finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
        Write-Output "server stopped (pid $($server.Id))"
    }
    Remove-Item Env:TRADERAIG_PERSIST -ErrorAction SilentlyContinue
    Remove-Item Env:TRADERAIG_STATE_REDIS -ErrorAction SilentlyContinue
    Remove-Item Env:TRADERAIG_AUTH -ErrorAction SilentlyContinue
    Remove-Item Env:API_PORT -ErrorAction SilentlyContinue
}
