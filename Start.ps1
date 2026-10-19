param([switch]$Local, [switch]$Offline)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$demoPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $demoPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the Python environment.' }
}
& $demoPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Unable to install dependencies.' }
$demoArgs = @('main.py')
if ($Local) { $demoArgs += '--local' }
if ($Offline) { $demoArgs += '--offline' }
& $demoPython @demoArgs
exit $LASTEXITCODE
