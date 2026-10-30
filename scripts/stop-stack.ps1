<#
.SYNOPSIS
    Stops all local observability stack components on Windows.
.DESCRIPTION
    Terminates Jaeger, OpenTelemetry Collector, Prometheus, Grafana, and ADK Dev UI processes,
    and ensures all local ports are cleanly released.
#>

[CmdletBinding()]
param()

Write-Host "Stopping all ADK observability stack processes..." -ForegroundColor Yellow

# Terminate known stack binaries
$processNames = @("jaeger", "otelcol", "otelcol-contrib", "prometheus", "grafana-server", "grafana")
foreach ($name in $processNames) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Host "Stopping $name ($($procs.Count) process(es))..." -ForegroundColor Cyan
        $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

# Terminate any remaining processes bound to the stack's loopback ports
$ports = @(16686, 14317, 14318, 4317, 4318, 8889, 9090, 3000, 8000)
Get-NetTCPConnection -LocalPort $ports -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 0 } | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}

Write-Host "All local observability stack processes have been stopped and ports released." -ForegroundColor Green
