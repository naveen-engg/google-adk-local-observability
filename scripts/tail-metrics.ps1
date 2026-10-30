<#
.SYNOPSIS
    Follows and formats live OpenTelemetry metrics from a JSONL log file or pipeline stream.
.DESCRIPTION
    Tails a Collector debug output or telemetry log file, filters metric records (default 'gen_ai'),
    and prints human-readable timestamps, metric names, units, values, and attributes.
.PARAMETER Path
    Path to the JSONL log file to tail. Defaults to 'collector.log'.
.PARAMETER Filter
    Substring or regex pattern to filter metric names. Defaults to 'gen_ai'.
#>

[CmdletBinding()]
param (
    [string]$Path = "collector.log",
    [string]$Filter = "gen_ai",
    [switch]$Wait
)

if (-not (Test-Path $Path)) {
    Write-Host "Specified telemetry file '$Path' does not exist." -ForegroundColor Yellow
    Write-Host "Ensure the OpenTelemetry Collector debug exporter is configured to log to file, or redirect output:" -ForegroundColor Yellow
    Write-Host "  otelcol.exe --config=otel-collector-config.yaml > collector.log" -ForegroundColor Cyan
    exit 0
}

Write-Host "Tailing metrics from '$Path' matching filter '$Filter'..." -ForegroundColor Cyan

Get-Content -Path $Path -Tail 20 -Wait:$Wait | ForEach-Object {
    $line = $_.Trim()
    if (-not $line) { return }

    # Attempt JSON parse if collector outputs JSON structured records
    if ($line.StartsWith("{") -and $line.EndsWith("}")) {
        try {
            $record = $line | ConvertFrom-Json
            # Check for resourceMetrics structure
            if ($record.resourceMetrics) {
                foreach ($rm in $record.resourceMetrics) {
                    foreach ($sm in $rm.scopeMetrics) {
                        foreach ($m in $sm.metrics) {
                            if ($m.name -match $Filter) {
                                $ts = if ($m.timeUnixNano) { [DateTimeOffset]::FromUnixTimeMilliseconds([int64]($m.timeUnixNano / 1000000)).LocalDateTime } else { Get-Date }
                                Write-Host "[$ts] " -NoNewline -ForegroundColor DarkGray
                                Write-Host "$($m.name) " -NoNewline -ForegroundColor Green
                                Write-Host "($($m.unit)) " -NoNewline -ForegroundColor Yellow
                                if ($m.sum -and $m.sum.dataPoints) {
                                    $val = $m.sum.dataPoints[0].asDouble -or $m.sum.dataPoints[0].asInt
                                    Write-Host "= $val " -NoNewline -ForegroundColor White
                                } elseif ($m.histogram -and $m.histogram.dataPoints) {
                                    $dp = $m.histogram.dataPoints[0]
                                    Write-Host "[count=$($dp.count), sum=$($dp.sum)] " -NoNewline -ForegroundColor White
                                }
                                Write-Host ""
                            }
                        }
                    }
                }
            }
        } catch {
            # Non-JSON or plaintext collector output fallback
            if ($line -match $Filter) {
                Write-Host $line -ForegroundColor Gray
            }
        }
    } elseif ($line -match $Filter) {
        Write-Host $line -ForegroundColor Gray
    }
}
