param([switch]$LocalDatabase)

$ErrorActionPreference = 'Stop'

$listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
$localAddresses = @('0.0.0.0', '::', '127.0.0.1', '::1')
$busyPorts = @($listeners | Where-Object {
    $_.Port -in 3000, 8000 -and $_.Address.ToString() -in $localAddresses
} | Select-Object -ExpandProperty Port -Unique)
if ($busyPorts.Count -gt 0) {
    throw "Port(s) $($busyPorts -join ', ') are already in use. If VERIFEX is running, open http://localhost:3000. To restart it, press Ctrl+C in its original terminal, then run .\run.ps1 again."
}

$frontend = Join-Path $PSScriptRoot 'frontend'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Python virtual environment missing. Follow the local setup in documentation/SETUP.md.'
}
if ((Get-Command node.exe, npm.cmd -ErrorAction SilentlyContinue | Measure-Object).Count -ne 2) {
    throw 'Node.js and npm are required. Install Node.js and reopen your terminal.'
}
if (-not (Test-Path -LiteralPath (Join-Path $frontend 'node_modules/next/package.json') -PathType Leaf)) {
    throw 'Frontend dependencies missing. Run npm.cmd --prefix frontend ci from the project folder.'
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.env') -PathType Leaf)) {
    & $python (Join-Path $PSScriptRoot 'backend/setup_env.py')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Start-DevService($executable, $arguments, $workingDirectory, $databaseUrl) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new($executable, $arguments)
    $startInfo.WorkingDirectory = $workingDirectory
    $startInfo.UseShellExecute = $false
    if ($databaseUrl) {
        $startInfo.EnvironmentVariables['DATABASE_URL'] = $databaseUrl
    }
    [System.Diagnostics.Process]::Start($startInfo)
}

$databaseUrl = if ($LocalDatabase) {
    Write-Host 'Using local SQLite at .verifex/verifex.sqlite3.'
    'sqlite:///./.verifex/verifex.sqlite3'
}
$api = $null
$web = $null
try {
    $api = Start-DevService $python '-m uvicorn backend.verifex.main:app --host 127.0.0.1 --port 8000' $PSScriptRoot $databaseUrl
    Write-Host 'Starting the VERIFEX API. Press Ctrl+C to stop.'

    # Uvicorn opens its listening socket after the application startup completes.
    while (-not $api.WaitForExit(250)) {
        $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        if ($listeners | Where-Object { $_.Port -eq 8000 -and $_.Address.ToString() -eq '127.0.0.1' }) {
            break
        }
    }
    if (-not $api.HasExited) {
        $web = Start-DevService $env:ComSpec '/d /c npm.cmd run dev -- --hostname localhost --port 3000' $frontend
        Write-Host 'VERIFEX is starting at http://localhost:3000. Press Ctrl+C to stop both services.'
        while (-not $api.WaitForExit(250) -and -not $web.HasExited) {}
    }
    if ($api.HasExited) {
        throw "The API stopped (exit code $($api.ExitCode)). Check the startup log above."
    }
    throw "The frontend stopped (exit code $($web.ExitCode)). Check the startup log above."
}
finally {
    foreach ($service in @($web, $api)) {
        if ($null -ne $service) {
            if (-not $service.HasExited) {
                taskkill.exe /PID $service.Id /T /F | Out-Null
            }
            $service.Dispose()
        }
    }
}
