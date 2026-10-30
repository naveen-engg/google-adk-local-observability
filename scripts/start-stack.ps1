<#
.SYNOPSIS
    Orchestrates and launches the complete local observability stack on Windows.
.DESCRIPTION
    Starts Jaeger, OpenTelemetry Collector, Prometheus, Grafana, and ADK Dev UI in dependency
    order, each in its own PowerShell process. Performs port polling, handles shims,
    and configures all feature flags and local loopback bindings.
#>

[CmdletBinding()]
param (
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

# Ensure Scoop shims and local tools are prioritized in PATH
$ScoopShims = Join-Path $env:USERPROFILE "scoop\shims"
if (Test-Path $ScoopShims) {
    $env:PATH = "$ScoopShims;$env:PATH"
}

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host " Starting ADK Local Observability Stack (adk-otel)" -ForegroundColor Cyan
Write-Host " Root Directory: $ProjectRoot" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

# ------------------------------------------------------------------------------
# Helper Functions
# ------------------------------------------------------------------------------
function Test-PortListening {
    param (
        [string]$Address = "127.0.0.1",
        [int]$Port
    )
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($Address, $Port, $null, $null)
        $wait = $iar.AsyncWaitHandle.WaitOne(400, $false)
        if ($wait) {
            $tcp.EndConnect($iar)
            $tcp.Close()
            return $true
        }
        $tcp.Close()
        return $false
    } catch {
        return $false
    }
}

function Wait-ForPort {
    param (
        [string]$ServiceName,
        [string]$Address = "127.0.0.1",
        [int]$Port,
        [int]$Timeout = 30
    )
    Write-Host "Waiting for $ServiceName on $Address`:$Port..." -NoNewline
    $elapsed = 0
    while ($elapsed -lt $Timeout) {
        if (Test-PortListening -Address $Address -Port $Port) {
            Write-Host " [READY]" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds 1
        $elapsed++
        Write-Host "." -NoNewline
    }
    Write-Host " [TIMED OUT]" -ForegroundColor Red
    return $false
}

function Find-RealExecutable {
    param (
        [string]$Name
    )
    # Check Python scripts directories
    $pyScripts = @(
        "$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\$Name.exe",
        "$env:APPDATA\Python\Scripts\$Name.exe",
        "$ProjectRoot\venv\Scripts\$Name.exe"
    )
    foreach ($ps in $pyScripts) {
        if (Test-Path $ps) { return $ps }
    }

    # Check Scoop apps directory first for the real binary
    $scoopApp = "$env:USERPROFILE\scoop\apps\$Name\current\$Name.exe"
    if (Test-Path $scoopApp) { return $scoopApp }
    $scoopAppBin = "$env:USERPROFILE\scoop\apps\$Name\current\bin\$Name.exe"
    if (Test-Path $scoopAppBin) { return $scoopAppBin }

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { return $null }
    
    # Resolve shims (e.g., Scoop/Chocolatey shims) to the target binary
    $path = $cmd.Source
    if ($path -like "*\shims\*" -or $path -like "*\chocolatey\bin\*") {
        $real = (Get-ChildItem -Path (Split-Path (Split-Path $path)) -Filter "$Name.exe" -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike "*\shims\*" -and $_.FullName -notlike "*\bin\*" } | Select-Object -First 1)
        if ($real) { return $real.FullName }
    }
    return $path
}

# ------------------------------------------------------------------------------
# 0. Validate Environment (.env is required for ADK web & credentials)
# ------------------------------------------------------------------------------
$EnvFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[ERROR] .env file not found in $ProjectRoot!" -ForegroundColor Red
    Write-Host "Please copy .env.example to .env and configure your preferences before starting." -ForegroundColor Yellow
    exit 1
}

# Parse .env file into key-value pairs
$EnvMap = @{}
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and ($line -match "^([^=]+)=(.*)$")) {
        $key = $matches[1].Trim()
        $val = $matches[2].Trim()
        $EnvMap[$key] = $val
        [Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
}

# ------------------------------------------------------------------------------
# 1. Step 1: Jaeger (Traces Backend & UI)
# ------------------------------------------------------------------------------
$JaegerPort = 16686
$JaegerOtlpGrpcPort = 14317

if (Test-PortListening -Port $JaegerPort) {
    Write-Host "[SKIP] Jaeger is already running on port $JaegerPort." -ForegroundColor Yellow
} else {
    $JaegerExe = if ($env:JAEGER_BIN) { $env:JAEGER_BIN } else {
        $v2 = Find-RealExecutable "jaeger"
        if ($v2) { $v2 } else { Find-RealExecutable "jaeger-all-in-one" }
    }

    if (-not $JaegerExe) {
        Write-Host "[WARNING] Jaeger binary ('jaeger.exe' or 'jaeger-all-in-one.exe') not found in PATH." -ForegroundColor Yellow
        Write-Host "Install Jaeger via Scoop ('scoop install jaeger') or Chocolatey, or set JAEGER_BIN environment variable." -ForegroundColor Yellow
    } else {
        $isV2 = ($JaegerExe -like "*jaeger.exe*" -and $JaegerExe -notlike "*all-in-one*")
        Write-Host "Launching Jaeger ($JaegerExe)..." -ForegroundColor Cyan
        if ($isV2) {
            # Jaeger v2 command syntax: remap gRPC and HTTP OTLP ports to avoid colliding with Collector :4317/:4318
            $jaegerArgs = "--set=receivers.otlp.protocols.grpc.endpoint=127.0.0.1:$JaegerOtlpGrpcPort --set=receivers.otlp.protocols.http.endpoint=127.0.0.1:14318"
        } else {
            # Jaeger v1 all-in-one syntax
            $jaegerArgs = "--collector.otlp.grpc.host-port=127.0.0.1:$JaegerOtlpGrpcPort --query.host-port=127.0.0.1:$JaegerPort"
        }
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host '--- Jaeger Tracing ---' -ForegroundColor Cyan; & '$JaegerExe' $jaegerArgs"
        if (-not (Wait-ForPort -ServiceName "Jaeger" -Port $JaegerPort -Timeout $TimeoutSeconds)) {
            Write-Host "Failed to verify Jaeger on port $JaegerPort within $TimeoutSeconds seconds." -ForegroundColor Red
        }
    }
}

# ------------------------------------------------------------------------------
# 2. Step 2: OpenTelemetry Collector (Fan-out, Spanmetrics & OpenMetrics)
# ------------------------------------------------------------------------------
$CollectorHttpPort = 4318
$CollectorPromPort = 8889

if (Test-PortListening -Port $CollectorHttpPort) {
    Write-Host "[SKIP] OpenTelemetry Collector is already listening on port $CollectorHttpPort." -ForegroundColor Yellow
} else {
    $ColExe = Find-RealExecutable "otelcol"
    if (-not $ColExe) { $ColExe = Find-RealExecutable "otelcol-contrib" }
    
    if (-not $ColExe) {
        Write-Host "[WARNING] OpenTelemetry Collector binary ('otelcol.exe') not found in PATH." -ForegroundColor Yellow
        Write-Host "Download otelcol from https://github.com/open-telemetry/opentelemetry-collector-releases/releases" -ForegroundColor Yellow
    } else {
        Write-Host "Launching OpenTelemetry Collector ($ColExe)..." -ForegroundColor Cyan
        $colConfig = Join-Path $ProjectRoot "otel-collector-config.yaml"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host '--- OpenTelemetry Collector ---' -ForegroundColor Cyan; & '$ColExe' --config='$colConfig'"
        if (-not (Wait-ForPort -ServiceName "OTel Collector HTTP" -Port $CollectorHttpPort -Timeout $TimeoutSeconds)) {
            Write-Host "Failed to verify Collector HTTP receiver on port $CollectorHttpPort within $TimeoutSeconds seconds." -ForegroundColor Red
        }
        Wait-ForPort -ServiceName "OTel Collector Prometheus Exporter" -Port $CollectorPromPort -Timeout $TimeoutSeconds | Out-Null
    }
}

# ------------------------------------------------------------------------------
# 3. Step 3: Prometheus (Scraping 127.0.0.1:8889 with Exemplars Enabled)
# ------------------------------------------------------------------------------
$PromPort = 9090
if (Test-PortListening -Port $PromPort) {
    Write-Host "[SKIP] Prometheus is already running on port $PromPort." -ForegroundColor Yellow
} else {
    $PromExe = Find-RealExecutable "prometheus"
    if (-not $PromExe) {
        Write-Host "[WARNING] Prometheus binary ('prometheus.exe') not found in PATH." -ForegroundColor Yellow
    } else {
        Write-Host "Launching Prometheus ($PromExe)..." -ForegroundColor Cyan
        $promConfig = Join-Path $ProjectRoot "prometheus\prometheus.yml"
        $promArgs = "--config.file='$promConfig' --web.listen-address='127.0.0.1:$PromPort' --enable-feature=exemplar-storage"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", "Write-Host '--- Prometheus Metrics ---' -ForegroundColor Cyan; & '$PromExe' $promArgs"
        if (-not (Wait-ForPort -ServiceName "Prometheus" -Port $PromPort -Timeout $TimeoutSeconds)) {
            Write-Host "Failed to verify Prometheus on port $PromPort within $TimeoutSeconds seconds." -ForegroundColor Red
        }
    }
}

# ------------------------------------------------------------------------------
# 4. Step 4: Grafana (Provisioned Datasources & Dashboards)
# ------------------------------------------------------------------------------
$GrafanaPort = 3000
if (Test-PortListening -Port $GrafanaPort) {
    Write-Host "[SKIP] Grafana is already running on port $GrafanaPort." -ForegroundColor Yellow
} else {
    $GrafanaServerExe = Find-RealExecutable "grafana-server"
    if (-not $GrafanaServerExe) {
        $GrafanaServerExe = Find-RealExecutable "grafana"
    }
    $GrafanaCliExe = Find-RealExecutable "grafana-cli"

    if (-not $GrafanaServerExe) {
        Write-Host "[WARNING] Grafana binary ('grafana.exe' or 'grafana-server.exe') not found." -ForegroundColor Yellow
    } else {
        # Resolve Grafana homepath (where conf/defaults.ini and public/ reside)
        $grafanaHome = if (Test-Path "$env:USERPROFILE\scoop\apps\grafana\current") {
            "$env:USERPROFILE\scoop\apps\grafana\current"
        } else {
            Split-Path (Split-Path $GrafanaServerExe)
        }

        # Pre-install Infinity plugin if grafana-cli is accessible
        if ($GrafanaCliExe) {
            Write-Host "Checking Grafana Infinity datasource plugin..." -ForegroundColor Cyan
            & $GrafanaCliExe --homepath="$grafanaHome" plugins install yesoreyeram-infinity-datasource 2>&1 | Out-Null
        }

        Write-Host "Launching Grafana via launcher script..." -ForegroundColor Cyan
        $grafanaScript = Join-Path $ProjectRoot "scripts\run-grafana.ps1"
        Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Write-Host '--- Grafana ---' -ForegroundColor Cyan; & '$grafanaScript'"
        if (-not (Wait-ForPort -ServiceName "Grafana" -Port $GrafanaPort -Timeout $TimeoutSeconds)) {
            Write-Host "Failed to verify Grafana on port $GrafanaPort within $TimeoutSeconds seconds." -ForegroundColor Red
        }
    }
}

# ------------------------------------------------------------------------------
# 5. Step 5: ADK Dev Web UI
# ------------------------------------------------------------------------------
$AdkWebPort = 8000
if (Test-PortListening -Port $AdkWebPort) {
    Write-Host "[SKIP] ADK Dev Web UI is already running on port $AdkWebPort." -ForegroundColor Yellow
} else {
    Write-Host "Launching ADK Dev UI on port $AdkWebPort..." -ForegroundColor Cyan
    
    # Launch ADK web server bound to 127.0.0.1 pointing to agents directory via dedicated runner
    $adkScript = Join-Path $ProjectRoot "scripts\run-adk-web.ps1"
    Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "Write-Host '--- Google ADK Dev UI ---' -ForegroundColor Cyan; & '$adkScript'"
    Wait-ForPort -ServiceName "ADK Dev UI" -Port $AdkWebPort -Timeout $TimeoutSeconds | Out-Null
}

# ------------------------------------------------------------------------------
# Summary Table
# ------------------------------------------------------------------------------
Write-Host ""
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " ADK Observability Stack is Ready!" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host " ADK Dev Web UI:       http://127.0.0.1:8000" -ForegroundColor White
Write-Host " Grafana Dashboards:   http://127.0.0.1:3000 (Default login: admin/admin)" -ForegroundColor White
Write-Host "   - GenAI Metrics:    http://127.0.0.1:3000/d/adk-genai" -ForegroundColor Gray
Write-Host "   - Traces Waterfall: http://127.0.0.1:3000/d/adk-traces" -ForegroundColor Gray
Write-Host " Jaeger UI:            http://127.0.0.1:16686" -ForegroundColor White
Write-Host " Prometheus UI:        http://127.0.0.1:9090" -ForegroundColor White
Write-Host " OTel Collector HTTP:  http://127.0.0.1:4318 (Agent OTLP target)" -ForegroundColor White
Write-Host " OTel Collector Prom:  http://127.0.0.1:8889/metrics (Scrape target)" -ForegroundColor White
Write-Host "=====================================================================" -ForegroundColor Green
Write-Host "To chat via interactive terminal: python main.py" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Green
