# Local verification gate — the exact crossroads from AGENTS.md, one command.
# Runs: lint (ruff) -> compile (py_compile) -> full pytest suite -> dashboard
# typecheck/build, and optionally the live wiring smoke (7/7).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1        # all gates incl. smoke
#   powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1 -SkipSmoke
#   powershell -ExecutionPolicy Bypass -File scripts\verify_all.ps1 -Gate pytest
#
# Exit code 0 = all selected gates green; 1 = at least one failed.
param(
    [switch]$SkipSmoke,
    [ValidateSet("all", "lint", "compile", "pytest", "dash", "smoke")]
    [string]$Gate = "all"
)

$ErrorActionPreference = "Stop"

$ROOT = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PY   = "python"
$DASH = Join-Path $ROOT "TAIG Dash"

$selected = if ($Gate -eq "all") {
    @("lint", "compile", "pytest", "dash") + $(if ($SkipSmoke) { @() } else { @("smoke") })
} else { @($Gate) }

$results = [System.Collections.Generic.List[string]]::new()
function Step([string]$label, [scriptblock]$body) {
    Write-Output ("== {0} ==" -f $label)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        & $body
        $ok = $LASTEXITCODE -eq 0
    } catch {
        Write-Output ("  ERROR: {0}" -f $_.Exception.Message)
        $ok = $false
    }
    $sw.Stop()
    $tag = if ($ok) { "[ok]" } else { "[!!]" }
    $results.Add((("{0}  {1}  ({2}s)" -f $tag, $label, [Math]::Round($sw.Elapsed.TotalSeconds, 1))))
    Write-Output ("{0}  {1}" -f $tag, $label)
}

if ($selected -contains "lint") {
    Step "ruff lint" {
        Push-Location $ROOT
        try { & $PY -m ruff check .; if ($LASTEXITCODE -ne 0) { throw "ruff exit code $LASTEXITCODE" } } finally { Pop-Location }
    }
}

if ($selected -contains "compile") {
    Step "py_compile" {
        $pyFiles = Get-ChildItem $ROOT -Recurse -Filter *.py |
            Where-Object { $_.FullName -notmatch '\\mt5-dev\\|\\mt5-portable\\|\\TAIG Dash\\|node_modules|\.pytest_cache|__pycache__|\\logs\\|\\\.data\\' } |
            Select-Object -ExpandProperty FullName
        & $PY -m py_compile $pyFiles; if ($LASTEXITCODE -ne 0) { throw "py_compile exit code $LASTEXITCODE" }
    }
}

if ($selected -contains "pytest") {
    Step "full pytest suite" {
        Push-Location $ROOT
        try { & $PY -m pytest -q -p no:cacheprovider; if ($LASTEXITCODE -ne 0) { throw "pytest exit code $LASTEXITCODE" } } finally { Pop-Location }
    }
}

if ($selected -contains "dash") {
    Step "dashboard tsc --noEmit" {
        Push-Location $DASH
        try { & node .\node_modules\typescript\bin\tsc --noEmit; if ($LASTEXITCODE -ne 0) { throw "tsc exit code $LASTEXITCODE" } } finally { Pop-Location }
    }
    Step "dashboard vite build" {
        Push-Location $DASH
        try { & node .\node_modules\vite\bin\vite.js build; if ($LASTEXITCODE -ne 0) { throw "vite exit code $LASTEXITCODE" } } finally { Pop-Location }
    }
}

if ($selected -contains "smoke") {
    if (-not $SkipSmoke) {
        Step "live wiring smoke (7/7)" {
            & powershell -ExecutionPolicy Bypass -File (Join-Path $ROOT "scripts\smoke_live.ps1")
            if ($LASTEXITCODE -ne 0) { throw "smoke exit code $LASTEXITCODE" }
        }
    }
}

Write-Output ""
# -like treats "[!!]" as a character class, so a failed gate never matches
# and the summary reports every run as green. Compare the tag literally.
$fails = @($results | Where-Object { $_.StartsWith("[!!]") })
Write-Output ("VERIFY_ALL: {0} gates, {1} passed, {2} failed" -f $results.Count, ($results.Count - $fails.Count), $fails.Count)
foreach ($r in $results) { Write-Output "  $r" }
exit $(if ($fails.Count -eq 0) { 0 } else { 1 })
