# ADK Dev Web UI Launcher
# Loads environment variables from .env and starts ADK web targeting the agents directory

$ProjectRoot = Split-Path $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"

if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and ($line -match "^([^=]+)=(.*)$")) {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
}

# Locate ADK binary
$adkCandidates = @(
    "$env:LOCALAPPDATA\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\adk.exe",
    "$env:APPDATA\Python\Scripts\adk.exe",
    "$ProjectRoot\venv\Scripts\adk.exe"
)

$adkExe = $null
foreach ($cand in $adkCandidates) {
    if (Test-Path $cand) {
        $adkExe = $cand
        break
    }
}

if (-not $adkExe) {
    $cmd = Get-Command "adk" -ErrorAction SilentlyContinue
    if ($cmd) { $adkExe = $cmd.Source }
}

Set-Location $ProjectRoot
Write-Host "--- Google ADK Dev UI ---" -ForegroundColor Cyan
Write-Host "Target: http://127.0.0.1:8000/dev-ui/" -ForegroundColor Green
Write-Host "Agents Directory: $ProjectRoot\agents (ops_agent only)" -ForegroundColor Gray

if ($adkExe) {
    & $adkExe web --host 127.0.0.1 --port 8000 --session_service_uri=memory:// agents
} else {
    adk web --host 127.0.0.1 --port 8000 --session_service_uri=memory:// agents
}
