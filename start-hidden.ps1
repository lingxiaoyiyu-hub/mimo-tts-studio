$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

try {
    Set-Location $root

    $pythonCmd = Get-Command python -ErrorAction Stop
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"

    if (-not (Test-Path $venvPython)) {
        & $pythonCmd.Source -m venv ".venv" *> (Join-Path $logs "mmtts-venv.log")
    }

    $installLog = Join-Path $logs "mmtts-install.log"
    $ErrorActionPreference = "Continue"
    & $venvPython -m pip install --retries 3 -r "requirements.txt" *> $installLog
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($installExitCode -ne 0) {
        throw "Dependency installation failed. See $installLog"
    }

    $listening = Get-NetTCPConnection -LocalPort 8300 -State Listen -ErrorAction SilentlyContinue
    if (-not $listening) {
        Start-Process -FilePath $venvPython `
            -ArgumentList @("-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8300") `
            -WorkingDirectory $root `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logs "mmtts-server.log") `
            -RedirectStandardError (Join-Path $logs "mmtts-server.err.log")
    }

    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:8300"
} catch {
    $_ | Out-File -FilePath (Join-Path $logs "mmtts-startup.err.log") -Append -Encoding utf8
}
