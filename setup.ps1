$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        python -m venv (Join-Path $projectRoot '.venv')
    } else {
        py -3 -m venv (Join-Path $projectRoot '.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required.' }
}
& (Join-Path $projectRoot '.venv\Scripts\python.exe') -c "import sys, tkinter; assert sys.version_info >= (3,11), 'Python 3.11+ required'; print('Python and Tkinter ready')"
if ($LASTEXITCODE -ne 0) { throw 'Python/Tkinter verification failed.' }
Write-Host 'Ready. Double-click launch.cmd, or run .\fuji-tool.cmd --help'
