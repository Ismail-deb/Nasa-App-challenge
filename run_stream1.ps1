# Stream 1: MERRA-2 categories (share the M2TMNXSLV granule cache).
# Can run at the same time as run_stream2.ps1 in another terminal.
#   powershell -ExecutionPolicy Bypass -File .\run_stream1.ps1 [-Cleanup] [-Start 2000-01]
param([string]$Start = "2000-01", [switch]$Cleanup, [string]$Python = "")
& (Join-Path $PSScriptRoot "pull_stream.ps1") -Categories weather_climate, atmosphere_solar `
    -Start $Start -Cleanup:$Cleanup -Python $Python
exit $LASTEXITCODE
