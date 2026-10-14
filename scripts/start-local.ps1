$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$port = if ($env:CONTRA_PORT) { [int]$env:CONTRA_PORT } else { 8000 }
if ($port -lt 1 -or $port -gt 65535) { throw 'CONTRA_PORT must be between 1 and 65535' }
$baseUrl = "http://127.0.0.1:$port/"
$healthUri = $baseUrl + 'health'

function Test-ContraHealth {
    try {
        $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 2
        return $health.status -eq 'ok' -and $health.fixture_loaded -eq $true
    } catch {
        return $false
    }
}

if (Test-ContraHealth) {
    Write-Output "CONTRA is already running at $baseUrl"
    exit 0
}

$pythonCommand = Get-Command python -ErrorAction Stop
$dataDir = Join-Path $repoRoot 'data'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$stdout = Join-Path $dataDir "local-server-$port.stdout.log"
$stderr = Join-Path $dataDir "local-server-$port.stderr.log"
$stdin = Join-Path $dataDir 'empty.stdin'
if (-not (Test-Path -LiteralPath $stdin)) { New-Item -ItemType File -Path $stdin | Out-Null }

$serverProcess = Start-Process -FilePath $pythonCommand.Source `
    -ArgumentList '-m', 'contra.server' `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -RedirectStandardInput $stdin `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

for ($attempt = 0; $attempt -lt 24; $attempt++) {
    Start-Sleep -Milliseconds 250
    if (Test-ContraHealth) {
        Write-Output "CONTRA is ready at $baseUrl (PID $($serverProcess.Id))"
        exit 0
    }
    if ($serverProcess.HasExited) {
        throw "CONTRA exited before becoming ready. Check $stderr"
    }
}

throw "CONTRA did not become ready within six seconds. Check $stderr"
