param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverDir = Join-Path $projectRoot 'server'
$logDir = Join-Path $projectRoot '.runlogs'
$backendOut = Join-Path $logDir 'backend.out.log'
$backendErr = Join-Path $logDir 'backend.err.log'
$frontendOut = Join-Path $logDir 'frontend.out.log'
$frontendErr = Join-Path $logDir 'frontend.err.log'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-PortListening {
    param([int]$Port)
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
}

function Get-PortOwners {
    param([int]$Port)
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Stop-PortOwners {
    param(
        [int]$Port,
        [string]$Name
    )

    $owners = @(Get-PortOwners -Port $Port)
    if (-not $owners.Count) {
        Write-Host "No running $Name process detected on port $Port."
        return
    }

    foreach ($owner in $owners) {
        if (-not $owner -or $owner -eq $PID) {
            continue
        }
        try {
            $process = Get-Process -Id $owner -ErrorAction Stop
            Write-Host "Stopping $Name on port $Port (pid=$owner, process=$($process.ProcessName))..."
            Stop-Process -Id $owner -Force -ErrorAction Stop
        } catch {
            Write-Host ("Failed to stop pid={0} on port {1}: {2}" -f $owner, $Port, $_.Exception.Message)
        }
    }

    Start-Sleep -Milliseconds 800
}

function Wait-PortListening {
    param(
        [int]$Port,
        [int]$TimeoutSec = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $Port) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-DetachedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$StdOut,
        [string]$StdErr
    )

    if (-not (Test-Path $FilePath) -and $FilePath -eq 'npm.cmd') {
        $resolvedNpm = (Get-Command npm.cmd -ErrorAction Stop).Source
        $FilePath = $resolvedNpm
    }

    Write-Host "Starting $Name..."
    $process = Start-Process -WindowStyle Hidden -PassThru -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr
    Write-Host "$Name pid=$($process.Id)"
    return $process
}

Write-Host "Project root: $projectRoot"

Stop-PortOwners -Port 5001 -Name 'backend'
$backend = Start-DetachedProcess `
    -Name 'backend' `
    -FilePath 'python' `
    -ArgumentList @('app.py') `
    -WorkingDirectory $serverDir `
    -StdOut $backendOut `
    -StdErr $backendErr

if (-not (Wait-PortListening -Port 5001 -TimeoutSec 60)) {
    Write-Host "Backend failed to start. Last log lines:"
    if (Test-Path $backendErr) { Get-Content -Encoding UTF8 $backendErr -Tail 80 }
    throw "Backend did not listen on port 5001."
}

$env:VITE_API_BASE_URL = 'http://127.0.0.1:5001'

Stop-PortOwners -Port 5173 -Name 'frontend'
$frontend = Start-DetachedProcess `
    -Name 'frontend' `
    -FilePath 'npm.cmd' `
    -ArgumentList @('run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173') `
    -WorkingDirectory $projectRoot `
    -StdOut $frontendOut `
    -StdErr $frontendErr

if (-not (Wait-PortListening -Port 5173 -TimeoutSec 60)) {
    Write-Host "Frontend failed to start. Last log lines:"
    if (Test-Path $frontendErr) { Get-Content -Encoding UTF8 $frontendErr -Tail 80 }
    throw "Frontend did not listen on port 5173."
}

Write-Host ""
Write-Host "Ready:"
Write-Host "  Frontend: http://127.0.0.1:5173"
Write-Host "  Backend:  http://127.0.0.1:5001"

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:5173"
}
