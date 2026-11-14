# Runs pull_data.py for several categories in order. Used by run_stream1.ps1 / run_stream2.ps1.
# Each category logs to logs\pull_<category>.log. A failing category is recorded and the
# next one still runs. Prints a one-line summary per category at the end.
#   -Cleanup : after ALL categories succeed, delete their raw granule caches (frees disk)
#   -Start   : first month to pull (YYYY-MM), default 2000-01
#   -Python  : python executable (default: venv\Scripts\python.exe, else python on PATH)
param(
    [Parameter(Mandatory = $true)][string[]]$Categories,
    [string]$Start = "2000-01",
    [switch]$Cleanup,
    [string]$Python = ""
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot
# "-File ... -Categories a,b" arrives as ONE string "a,b"; split it into a list
$Categories = @($Categories | ForEach-Object { $_ -split "," } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

if (-not $Python) {
    $venvPy = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
    if (Test-Path $venvPy) { $Python = $venvPy } else { $Python = "python" }
}
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "logs") | Out-Null

$env:PYTHONIOENCODING = "utf-8"   # logs are UTF-8
$env:TQDM_DISABLE = "1"           # no download progress bars in the logs

function Invoke-Pull([string]$Category, [string[]]$ExtraArgs, [string]$Log) {
    $argLine = (@("-u", "pull_data.py", $Category) + $ExtraArgs) -join " "
    # cmd.exe does the redirection: avoids PowerShell 5.1 turning stderr lines into errors
    cmd /c "`"$Python`" $argLine >> `"$Log`" 2>&1"
    return $LASTEXITCODE
}

$results = @()
foreach ($cat in $Categories) {
    $log = Join-Path $PSScriptRoot "logs\pull_$cat.log"
    $t0 = Get-Date
    Add-Content -LiteralPath $log -Encoding utf8 -Value "===== $($t0.ToString('yyyy-MM-dd HH:mm:ss')) pull $cat --start $Start ====="
    Write-Host "[$($t0.ToString('HH:mm:ss'))] $cat started (log: logs\pull_$cat.log)"
    $code = Invoke-Pull $cat @("--start", $Start) $log
    $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    switch ($code) {
        0       { $status = "OK" }
        3       { $status = "GAPS (some granules failed; re-run to retry)" }
        default { $status = "FAILED (exit $code)" }
    }
    Add-Content -LiteralPath $log -Encoding utf8 -Value "===== result: $status after $mins min ====="
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] $cat finished: $status"
    $results += [pscustomobject]@{ Category = $cat; Status = $status; Code = $code; Minutes = $mins }
}

$allOk = -not ($results | Where-Object { $_.Code -ne 0 })
if ($Cleanup) {
    if ($allOk) {
        foreach ($cat in $Categories) {
            $log = Join-Path $PSScriptRoot "logs\pull_$cat.log"
            Invoke-Pull $cat @("--cleanup") $log | Out-Null
        }
        Write-Host "Raw caches removed for: $($Categories -join ', ')"
    } else {
        Write-Host "Cleanup skipped: not every category succeeded (cache kept so a re-run is fast)."
    }
}

Write-Host ""
Write-Host "Summary:"
foreach ($r in $results) {
    $mark = if ($r.Code -eq 0) { "SUCCESS" } else { "FAILURE" }
    Write-Host ("  {0,-17} {1}: {2}  ({3} min, log: logs\pull_{0}.log)" -f $r.Category, $mark, $r.Status, $r.Minutes)
}
if ($allOk) { exit 0 } else { exit 1 }
