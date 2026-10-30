# Grafana Server Launcher
# Sets provisioning path and feature toggles

$ProjectRoot = Split-Path $PSScriptRoot
$grafanaHome = "$env:USERPROFILE\scoop\apps\grafana\current"
$env:GF_PATHS_PROVISIONING = Join-Path $ProjectRoot "grafana\provisioning"
$env:GF_FEATURE_TOGGLES_ENABLE = "jaegerGrpcSupport"
$env:GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS = "yesoreyeram-infinity-datasource"

$grafanaBin = "$grafanaHome\bin\grafana.exe"
if (-not (Test-Path $grafanaBin)) {
    $grafanaBin = "grafana-server"
}

Write-Host "--- Grafana Server ---" -ForegroundColor Cyan
Write-Host "Provisioning: $env:GF_PATHS_PROVISIONING" -ForegroundColor Gray
Write-Host "Homepath: $grafanaHome" -ForegroundColor Gray

& $grafanaBin server --homepath="$grafanaHome"
